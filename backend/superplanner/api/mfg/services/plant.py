"""Plant settings, work-center groups, lines, shift templates, assignments, calendar exceptions and line windows
(M1-DESIGN 3.3, 3.7, 3.8, 4.6; 9.3 #3-4, #29-53)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ....mfg import limits as L
from ....mfg.calendar import (expand_template_week, line_windows, offset_tz, validate_template, week_minutes_per_day,
                              window_minutes)
from ....mfg.dataset import MfgDataset, item_ref, ref
from ....mfg.model import (CalendarExceptionInput, CalendarExceptionRecord, GroupInput, GroupRecord, LineInput,
                           LineRecord, PlantInput, PlantRecord, ShiftAssignmentInput, ShiftAssignmentRecord,
                           ShiftTemplateInput, ShiftTemplateRecord, TargetRef)
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError, validation_details
from .. import repo
from ..db_models import (MfgCalendarExceptionRow, MfgGroupRow, MfgItemRow, MfgLineItemRow, MfgLineRow,
                         MfgOperationRow, MfgOperatorRow, MfgPlantRow, MfgShiftAssignmentRow, MfgShiftTemplateRow)
from .common import (audit, check_limit, check_version, count, ensure_unique, ilike, in_use, read_tx, touch,
                     unknown_ref, write_tx)

# ---------------------------------------------------------------- plant


def get_plant(ctx: AppContext) -> PlantRecord:
    with read_tx(ctx) as s:
        return repo.plant_or_default(s)


def put_plant(ctx: AppContext, inp: PlantInput, if_match: str | None) -> PlantRecord:
    with write_tx(ctx, lock=False) as (s, _):
        # "0" (nothing stored) only when this transaction inserted the row; a row created concurrently by another
        # first write is compared by its row_version (review F4: no lost update between two first-time PUTs)
        row, created = repo.lock_plant_created(s)
        current = 0 if created else row.row_version
        check_version(row, if_match, current=current)
        if inp.time_zone is not None:
            from ....mfg.tz import current_offset, valid_zone

            if not valid_zone(inp.time_zone):
                raise ApiError(422, "MFG_TZ_INVALID", f"{inp.time_zone!r} is not an IANA time zone (for example "
                               "Asia/Kolkata).", {"loc": ["body", "time_zone"], "time_zone": inp.time_zone})
            # M3 5: with a zone, utc_offset is display only and calendar exceptions stay UTC instants (no rebase)
            rebased = 0
            row.name, row.utc_offset = inp.name, current_offset(inp)
        else:
            rebased = rebase_exceptions(s, row.utc_offset, inp.utc_offset) if not created and not row.time_zone \
                else 0
            row.name, row.utc_offset = inp.name, inp.utc_offset
        row.planning_horizon_days, row.currency = inp.planning_horizon_days, inp.currency
        row.attributes = dict(inp.attributes)
        for k, v in repo.plant_mrp_columns(inp).items():       # M2-DESIGN 3.1
            setattr(row, k, v)
        row.row_version = current + 1
        row.updated_at = utcnow()
        s.flush()
        details: dict[str, Any] = {"version": row.row_version}
        if rebased:
            details["rebased_exceptions"] = rebased
        audit(s, "plant", row.id, "create" if current == 0 else "update", details)
        return repo.to_record(row)


def rebase_exceptions(s: Session, old_offset: str, new_offset: str) -> int:
    """Calendar exceptions are stored as UTC instants but entered and shown as plant-local wall-clock times, like
    shift windows. When the plant offset changes, move every exception by (old - new offset) so it keeps its local
    times (review F7); bumps their row_version. Returns the number of rows moved."""
    if old_offset == new_offset:
        return 0
    delta = offset_tz(old_offset).utcoffset(None) - offset_tz(new_offset).utcoffset(None)
    now = utcnow()
    n = 0
    for x in s.execute(select(MfgCalendarExceptionRow).order_by(MfgCalendarExceptionRow.id)).scalars():
        x.start_at, x.end_at = x.start_at + delta, x.end_at + delta
        x.row_version = (x.row_version or 0) + 1
        x.updated_at = now
        n += 1
    if n:
        s.flush()
    return n


def plant_offset(s: Session) -> str:
    return s.execute(select(MfgPlantRow.utc_offset)).scalar() or "+00:00"


# ---------------------------------------------------------------- groups


def _line_counts(s: Session, group_ids: list[str] | None = None) -> dict[str, int]:
    q = select(MfgLineRow.group_id, func.count()).group_by(MfgLineRow.group_id)
    if group_ids is not None:
        q = q.where(MfgLineRow.group_id.in_(group_ids))
    return {g: int(n) for g, n in s.execute(q).all()}


def group_record(s: Session, row: MfgGroupRow) -> GroupRecord:
    return repo.to_record(row, line_count=_line_counts(s, [row.id]).get(row.id, 0))


def list_groups(ctx: AppContext, q: str | None, active: bool | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        stmt = select(MfgGroupRow)
        if q:
            stmt = stmt.where(ilike(MfgGroupRow.code, q) | ilike(MfgGroupRow.name, q))
        if active is not None:
            stmt = stmt.where(MfgGroupRow.active.is_(active))
        rows = list(s.execute(stmt.order_by(MfgGroupRow.code, MfgGroupRow.id)).scalars())
        counts = _line_counts(s)
        return {"items": [repo.to_record(r, line_count=counts.get(r.id, 0)) for r in rows]}


def _set_group(row: MfgGroupRow, inp: GroupInput) -> None:
    row.code, row.name, row.description, row.kind, row.active = (inp.code, inp.name, inp.description, inp.kind,
                                                                  inp.active)


def create_group(ctx: AppContext, inp: GroupInput) -> GroupRecord:
    with write_tx(ctx) as (s, _):
        ensure_unique(s, MfgGroupRow, "A stage", {"code": inp.code})
        check_limit(s, MfgGroupRow, L.MAX_GROUPS, "stages")
        now = utcnow()
        row = MfgGroupRow(id=new_id("wcg_"), row_version=1, created_at=now, updated_at=now)
        _set_group(row, inp)
        s.add(row)
        s.flush()
        audit(s, "group", row.id, "create", {"version": 1})
        return repo.to_record(row)


def get_group(ctx: AppContext, group_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        row = repo.get_row(s, MfgGroupRow, group_id, what="Stage")
        lines = list(s.execute(select(MfgLineRow).where(MfgLineRow.group_id == row.id)
                               .order_by(MfgLineRow.code, MfgLineRow.id)).scalars())
        line_ids = [ln.id for ln in lines]
        cond = MfgShiftAssignmentRow.group_id == row.id
        if line_ids:
            cond = or_(cond, MfgShiftAssignmentRow.line_id.in_(line_ids))
        asg = list(s.execute(select(MfgShiftAssignmentRow).where(cond)).scalars())
        rec = repo.to_record(row, line_count=len(lines))
        out = dict(rec.__dict__)
        out["lines"] = line_records(s, lines)
        out["assignments"] = assignment_records(s, asg)
        return out


def update_group(ctx: AppContext, group_id: str, inp: GroupInput, if_match: str | None) -> GroupRecord:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgGroupRow, group_id, what="Stage", lock=True)
        check_version(row, if_match)
        ensure_unique(s, MfgGroupRow, "A stage", {"code": inp.code}, exclude_id=row.id)
        _set_group(row, inp)
        touch(row)
        s.flush()
        audit(s, "group", row.id, "update", {"version": row.row_version})
        return group_record(s, row)


def delete_group(ctx: AppContext, group_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgGroupRow, group_id, what="Stage", lock=True)
        check_version(row, if_match)
        refs = {"lines": count(s, MfgLineRow, MfgLineRow.group_id == row.id),
                "operations": count(s, MfgOperationRow, MfgOperationRow.group_id == row.id)}
        if any(refs.values()):
            raise in_use(f"Stage {row.code}", refs)
        s.delete(row)
        s.flush()
        audit(s, "group", row.id, "delete", {"version": row.row_version})


# ---------------------------------------------------------------- lines


def line_records(s: Session, rows: list[MfgLineRow]) -> list[LineRecord]:
    if not rows:
        return []
    ids = [r.id for r in rows]
    links: dict[str, list[str]] = {}
    for lid, iid in s.execute(select(MfgLineItemRow.line_id, MfgLineItemRow.item_id)
                              .where(MfgLineItemRow.line_id.in_(ids))
                              .order_by(MfgLineItemRow.line_id, MfgLineItemRow.item_id)).all():
        links.setdefault(lid, []).append(iid)
    item_ids = sorted({i for v in links.values() for i in v})
    items = {r.id: repo.to_record(r) for r in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_(item_ids)))
             .scalars()} if item_ids else {}
    groups = {g.id: g for g in s.execute(select(MfgGroupRow).where(
        MfgGroupRow.id.in_(sorted({r.group_id for r in rows})))).scalars()}
    out = []
    for r in rows:
        elig = sorted(links.get(r.id, []), key=lambda i: (items[i].part_number if i in items else i))
        g = groups.get(r.group_id)
        out.append(repo.to_record(r, eligible_item_ids=elig, group=ref(g) if g else None,
                                  eligible_items=[item_ref(items[i]) for i in elig if i in items]))
    return out


def list_lines(ctx: AppContext, group_id: str | None, q: str | None, active: bool | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        stmt = select(MfgLineRow)
        if group_id:
            stmt = stmt.where(MfgLineRow.group_id == group_id)
        if q:
            stmt = stmt.where(ilike(MfgLineRow.code, q) | ilike(MfgLineRow.name, q))
        if active is not None:
            stmt = stmt.where(MfgLineRow.active.is_(active))
        rows = list(s.execute(stmt.order_by(MfgLineRow.code, MfgLineRow.id)).scalars())
        return {"items": line_records(s, rows)}


def _line_refs(s: Session, inp: LineInput) -> None:
    if s.execute(select(MfgGroupRow.id).where(MfgGroupRow.id == inp.group_id)).scalar() is None:
        raise unknown_ref(["body", "group_id"], inp.group_id, "Stage")
    if inp.eligible_item_ids:
        found = set(s.execute(select(MfgItemRow.id).where(MfgItemRow.id.in_(inp.eligible_item_ids))).scalars())
        for i, iid in enumerate(inp.eligible_item_ids):
            if iid not in found:
                raise unknown_ref(["body", "eligible_item_ids", i], iid, "Item")


def _set_line(s: Session, row: MfgLineRow, inp: LineInput, old_items: list[str]) -> None:
    for f in ("group_id", "code", "name", "speed_factor", "parallel_capacity", "setup_family", "cost_per_hour",
              "active"):
        setattr(row, f, getattr(inp, f))
    row.eligible_families = list(inp.eligible_families)
    s.flush()
    new, old = set(inp.eligible_item_ids), set(old_items)
    for iid in sorted(old - new):
        link_row = s.get(MfgLineItemRow, (row.id, iid))
        if link_row is not None:
            s.delete(link_row)
    for iid in sorted(new - old):
        s.add(MfgLineItemRow(line_id=row.id, item_id=iid))


def create_line(ctx: AppContext, inp: LineInput) -> LineRecord:
    with write_tx(ctx) as (s, _):
        _line_refs(s, inp)
        ensure_unique(s, MfgLineRow, "A line", {"code": inp.code})
        check_limit(s, MfgLineRow, L.MAX_LINES, "lines")
        now = utcnow()
        row = MfgLineRow(id=new_id("lin_"), row_version=1, created_at=now, updated_at=now)
        s.add(row)
        _set_line(s, row, inp, [])
        s.flush()
        audit(s, "line", row.id, "create", {"version": 1})
        return line_records(s, [row])[0]


def get_line(ctx: AppContext, line_id: str) -> LineRecord:
    with read_tx(ctx) as s:
        return line_records(s, [repo.get_row(s, MfgLineRow, line_id, what="Line")])[0]


def update_line(ctx: AppContext, line_id: str, inp: LineInput, if_match: str | None) -> LineRecord:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgLineRow, line_id, what="Line", lock=True)
        check_version(row, if_match)
        _line_refs(s, inp)
        ensure_unique(s, MfgLineRow, "A line", {"code": inp.code}, exclude_id=row.id)
        old = list(s.execute(select(MfgLineItemRow.item_id).where(MfgLineItemRow.line_id == row.id)).scalars())
        _set_line(s, row, inp, old)
        touch(row)
        s.flush()
        audit(s, "line", row.id, "update", {"version": row.row_version})
        return line_records(s, [row])[0]


def delete_line(ctx: AppContext, line_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgLineRow, line_id, what="Line", lock=True)
        check_version(row, if_match)
        s.delete(row)
        s.flush()
        audit(s, "line", row.id, "delete", {"version": row.row_version})


def windows(ctx: AppContext, line_id: str, d0: date, d1: date, kinds: list[str]) -> dict[str, Any]:
    """Line windows (4.6) from a minimal snapshot: plant, line, group, assignments of line+group, their templates,
    exceptions overlapping the range (<= 6 statements)."""
    if d1 <= d0 or (d1 - d0).days > L.MAX_WINDOW_RANGE_DAYS:
        raise ApiError(422, "MFG_RANGE_TOO_LONG",
                       f"Choose a range of 1 to {L.MAX_WINDOW_RANGE_DAYS} days ('to' is exclusive).",
                       {"max_days": L.MAX_WINDOW_RANGE_DAYS})
    with read_tx(ctx) as s:
        plant = repo.plant_or_default(s)
        line = repo.get_row(s, MfgLineRow, line_id, what="Line")
        ds = MfgDataset(plant=plant)
        ds.lines[line.id] = repo.to_record(line)
        asg = list(s.execute(select(MfgShiftAssignmentRow).where(or_(
            MfgShiftAssignmentRow.line_id == line.id, MfgShiftAssignmentRow.group_id == line.group_id))).scalars())
        tpl_ids = sorted({a.shift_template_id for a in asg})
        for t in (s.execute(select(MfgShiftTemplateRow).where(MfgShiftTemplateRow.id.in_(tpl_ids))).scalars()
                  if tpl_ids else []):
            ds.shift_templates[t.id] = repo.to_record(t)
        for a in asg:
            ds.shift_assignments[a.id] = repo.to_record(a)
        tz = offset_tz(plant.utc_offset)
        lo = datetime(d0.year, d0.month, d0.day, tzinfo=tz) - timedelta(days=1)
        hi = datetime(d1.year, d1.month, d1.day, tzinfo=tz) + timedelta(days=1)
        for x in s.execute(select(MfgCalendarExceptionRow).where(
                MfgCalendarExceptionRow.start_at < hi.astimezone(UTC), MfgCalendarExceptionRow.end_at > lo.astimezone(UTC),
                or_(MfgCalendarExceptionRow.scope == "plant", MfgCalendarExceptionRow.group_id == line.group_id,
                    MfgCalendarExceptionRow.line_id == line.id))).scalars():
            ds.calendar_exceptions[x.id] = repo.to_record(x, utc_offset=plant.utc_offset)
        # the group's active flag matters (inactive group: its assignments do not apply)
        g = s.get(MfgGroupRow, line.group_id)
        if g is not None:
            ds.groups[g.id] = repo.to_record(g)
        wins = line_windows(ds, line.id, d0, d1, kinds=tuple(kinds))
        totals = window_minutes(wins)
        return {"line_id": line.id, "from": d0, "to": d1, "utc_offset": plant.utc_offset, "windows": wins,
                "totals": totals}


# ---------------------------------------------------------------- shift templates


def _template_counts(s: Session, ids: list[str] | None = None) -> tuple[dict[str, int], dict[str, int]]:
    qa = select(MfgShiftAssignmentRow.shift_template_id, func.count()).group_by(MfgShiftAssignmentRow.shift_template_id)
    qo = select(MfgOperatorRow.shift_template_id, func.count()).where(MfgOperatorRow.shift_template_id.is_not(None)) \
        .group_by(MfgOperatorRow.shift_template_id)
    if ids is not None:
        qa = qa.where(MfgShiftAssignmentRow.shift_template_id.in_(ids))
        qo = qo.where(MfgOperatorRow.shift_template_id.in_(ids))
    return ({k: int(v) for k, v in s.execute(qa).all()}, {k: int(v) for k, v in s.execute(qo).all()})


def template_record(s: Session, row: MfgShiftTemplateRow) -> ShiftTemplateRecord:
    a, o = _template_counts(s, [row.id])
    return repo.to_record(row, assignment_count=a.get(row.id, 0), operator_count=o.get(row.id, 0))


def _template_problems(inp: ShiftTemplateInput) -> None:
    errors = validate_template(inp)
    if errors:
        raise ApiError(422, "MFG_SHIFT_INVALID", "The shift pattern is not valid: " + errors[0]["msg"],
                       validation_details(errors))


def preview_template(inp: ShiftTemplateInput) -> dict[str, Any]:
    _template_problems(inp)
    per_day = week_minutes_per_day(inp)
    return {"week_windows": expand_template_week(inp), "minutes_per_day": per_day,
            "total_minutes": sum(per_day.values())}


def list_templates(ctx: AppContext) -> dict[str, Any]:
    with read_tx(ctx) as s:
        rows = list(s.execute(select(MfgShiftTemplateRow).order_by(MfgShiftTemplateRow.code,
                                                                    MfgShiftTemplateRow.id)).scalars())
        a, o = _template_counts(s)
        return {"items": [repo.to_record(r, assignment_count=a.get(r.id, 0), operator_count=o.get(r.id, 0))
                          for r in rows]}


def _set_template(row: MfgShiftTemplateRow, inp: ShiftTemplateInput) -> None:
    row.code, row.name, row.description = inp.code, inp.name, inp.description
    row.shifts = [sh.model_dump() for sh in inp.shifts]


def create_template(ctx: AppContext, inp: ShiftTemplateInput) -> ShiftTemplateRecord:
    with write_tx(ctx) as (s, _):
        ensure_unique(s, MfgShiftTemplateRow, "A shift template", {"code": inp.code})
        _template_problems(inp)
        check_limit(s, MfgShiftTemplateRow, L.MAX_SHIFT_TEMPLATES, "shift templates")
        now = utcnow()
        row = MfgShiftTemplateRow(id=new_id("sht_"), row_version=1, created_at=now, updated_at=now)
        _set_template(row, inp)
        s.add(row)
        s.flush()
        audit(s, "shift_template", row.id, "create", {"version": 1})
        return repo.to_record(row)


def get_template(ctx: AppContext, template_id: str) -> ShiftTemplateRecord:
    with read_tx(ctx) as s:
        return template_record(s, repo.get_row(s, MfgShiftTemplateRow, template_id, what="Shift template"))


def update_template(ctx: AppContext, template_id: str, inp: ShiftTemplateInput, if_match: str | None
                    ) -> ShiftTemplateRecord:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgShiftTemplateRow, template_id, what="Shift template", lock=True)
        check_version(row, if_match)
        ensure_unique(s, MfgShiftTemplateRow, "A shift template", {"code": inp.code}, exclude_id=row.id)
        _template_problems(inp)
        check_shift_names_kept(s, row.id, row.code, {sh.name for sh in inp.shifts})
        _set_template(row, inp)
        touch(row)
        s.flush()
        audit(s, "shift_template", row.id, "update", {"version": row.row_version})
        return template_record(s, row)


def shift_name_users(s: Session, template_id: str, names: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Assignments and operators of the template whose `shift_names` name a shift outside `names`:
    (`[{type, id, label, shift_names}]`, sorted missing names)."""
    users: list[dict[str, Any]] = []
    missing: set[str] = set()
    asg = list(s.execute(select(MfgShiftAssignmentRow).where(MfgShiftAssignmentRow.shift_template_id == template_id)
                         .order_by(MfgShiftAssignmentRow.id)).scalars())
    groups, lines = _targets(s, {a.group_id for a in asg if a.group_id}, {a.line_id for a in asg if a.line_id})
    tcode = s.execute(select(MfgShiftTemplateRow.code).where(MfgShiftTemplateRow.id == template_id)).scalar() or "?"
    for a in asg:
        gone = sorted(n for n in (a.shift_names or []) if n not in names)
        if gone:
            tgt = _target_ref(a.target_type, a.group_id, a.line_id, groups, lines)
            users.append({"type": "shift_assignment", "id": a.id,
                          "label": f"{tcode} on {tgt.code if tgt else '?'} ({a.kind})", "shift_names": gone})
            missing.update(gone)
    for o in s.execute(select(MfgOperatorRow).where(MfgOperatorRow.shift_template_id == template_id)
                       .order_by(MfgOperatorRow.code, MfgOperatorRow.id)).scalars():
        gone = sorted(n for n in (o.shift_names or []) if n not in names)
        if gone:
            users.append({"type": "operator", "id": o.id, "label": o.code, "shift_names": gone})
            missing.update(gone)
    return users, sorted(missing)


def shift_names_in_use_error(template_code: str, users: list[dict[str, Any]], missing: list[str]) -> ApiError:
    refs = {"shift_assignments": sum(u["type"] == "shift_assignment" for u in users),
            "operators": sum(u["type"] == "operator" for u in users)}
    refs = {k: v for k, v in refs.items() if v}
    kind = {"shift_assignment": "assignment", "operator": "operator"}
    shown = ", ".join(f"{kind[u['type']]} {u['label']}" for u in users[:5]) + \
        (f" and {len(users) - 5} more" if len(users) > 5 else "")
    what = f"shift {missing[0]} is" if len(missing) == 1 else f"shifts {', '.join(missing)} are"
    return ApiError(409, "MFG_IN_USE", f"Shift template {template_code}: {what} still used by {shown}. Change those "
                    "first (or keep the shift name).", {"references": refs, "shift_names": missing, "used_by": users})


def check_shift_names_kept(s: Session, template_id: str, template_code: str, names: set[str]) -> None:
    """409 `MFG_IN_USE` when renaming/removing a shift still named by assignments or operators (review F2)."""
    users, missing = shift_name_users(s, template_id, names)
    if users:
        raise shift_names_in_use_error(template_code, users, missing)


def delete_template(ctx: AppContext, template_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgShiftTemplateRow, template_id, what="Shift template", lock=True)
        check_version(row, if_match)
        refs = {"shift_assignments": count(s, MfgShiftAssignmentRow, MfgShiftAssignmentRow.shift_template_id == row.id),
                "operators": count(s, MfgOperatorRow, MfgOperatorRow.shift_template_id == row.id)}
        if any(refs.values()):
            raise in_use(f"Shift template {row.code}", refs)
        s.delete(row)
        s.flush()
        audit(s, "shift_template", row.id, "delete", {"version": row.row_version})


# ---------------------------------------------------------------- shift assignments


def _targets(s: Session, group_ids: set[str], line_ids: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    groups = {g.id: g for g in s.execute(select(MfgGroupRow).where(MfgGroupRow.id.in_(sorted(group_ids))))
              .scalars()} if group_ids else {}
    lines = {x.id: x for x in s.execute(select(MfgLineRow).where(MfgLineRow.id.in_(sorted(line_ids)))).scalars()} \
        if line_ids else {}
    return groups, lines


def _target_ref(kind: str, gid: str | None, lid: str | None, groups: dict[str, Any], lines: dict[str, Any]
                ) -> TargetRef | None:
    if kind == "group":
        g = groups.get(gid or "")
        return TargetRef.model_construct(type="group", id=gid or "", code=g.code if g else "?",
                                         name=g.name if g else "")
    if kind == "line":
        x = lines.get(lid or "")
        return TargetRef.model_construct(type="line", id=lid or "", code=x.code if x else "?",
                                         name=x.name if x else "")
    return None


def assignment_records(s: Session, rows: list[MfgShiftAssignmentRow]) -> list[ShiftAssignmentRecord]:
    if not rows:
        return []
    tpl = {t.id: t for t in s.execute(select(MfgShiftTemplateRow).where(
        MfgShiftTemplateRow.id.in_(sorted({r.shift_template_id for r in rows})))).scalars()}
    groups, lines = _targets(s, {r.group_id for r in rows if r.group_id}, {r.line_id for r in rows if r.line_id})
    out = []
    for r in rows:
        t = tpl.get(r.shift_template_id)
        out.append(repo.to_record(r, template=ref(t) if t else None,
                                  target=_target_ref(r.target_type, r.group_id, r.line_id, groups, lines)))
    out.sort(key=lambda a: (a.target.code if a.target else "", a.kind, a.effective_from, a.id))
    return out


def list_assignments(ctx: AppContext, group_id: str | None, line_id: str | None, template_id: str | None
                     ) -> dict[str, Any]:
    with read_tx(ctx) as s:
        stmt = select(MfgShiftAssignmentRow)
        if group_id:
            stmt = stmt.where(MfgShiftAssignmentRow.group_id == group_id)
        if line_id:
            stmt = stmt.where(MfgShiftAssignmentRow.line_id == line_id)
        if template_id:
            stmt = stmt.where(MfgShiftAssignmentRow.shift_template_id == template_id)
        return {"items": assignment_records(s, list(s.execute(stmt).scalars()))}


def _assignment_refs(s: Session, inp: ShiftAssignmentInput) -> None:
    t = s.execute(select(MfgShiftTemplateRow).where(MfgShiftTemplateRow.id == inp.shift_template_id)).scalars().first()
    if t is None:
        raise unknown_ref(["body", "shift_template_id"], inp.shift_template_id, "Shift template")
    if inp.target_type == "group":
        if s.execute(select(MfgGroupRow.id).where(MfgGroupRow.id == inp.group_id)).scalar() is None:
            raise unknown_ref(["body", "group_id"], inp.group_id or "", "Stage")
    elif s.execute(select(MfgLineRow.id).where(MfgLineRow.id == inp.line_id)).scalar() is None:
        raise unknown_ref(["body", "line_id"], inp.line_id or "", "Line")
    names = {sh["name"] for sh in t.shifts or []}
    bad = [n for n in inp.shift_names if n not in names]
    if bad:
        raise ApiError(422, "VALIDATION_ERROR", f"The shift template has no shift named {bad[0]!r}.",
                       {"errors": [{"loc": ["body", "shift_names", inp.shift_names.index(b)],
                                    "msg": f"unknown shift name {b!r}", "type": "value_error"} for b in bad]})


_ASG_FIELDS = ("shift_template_id", "target_type", "group_id", "line_id", "kind", "effective_from", "effective_to",
               "cost_per_hour", "max_hours_per_week", "note")


def _set_assignment(row: MfgShiftAssignmentRow, inp: ShiftAssignmentInput) -> None:
    for f in _ASG_FIELDS:
        setattr(row, f, getattr(inp, f))
    row.shift_names = list(inp.shift_names)


def create_assignment(ctx: AppContext, inp: ShiftAssignmentInput) -> ShiftAssignmentRecord:
    with write_tx(ctx) as (s, _):
        _assignment_refs(s, inp)
        check_limit(s, MfgShiftAssignmentRow, L.MAX_SHIFT_ASSIGNMENTS, "shift assignments")
        now = utcnow()
        row = MfgShiftAssignmentRow(id=new_id("sha_"), row_version=1, created_at=now, updated_at=now)
        _set_assignment(row, inp)
        s.add(row)
        s.flush()
        audit(s, "shift_assignment", row.id, "create", {"version": 1})
        return assignment_records(s, [row])[0]


def update_assignment(ctx: AppContext, assignment_id: str, inp: ShiftAssignmentInput, if_match: str | None
                      ) -> ShiftAssignmentRecord:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgShiftAssignmentRow, assignment_id, what="Shift assignment", lock=True)
        check_version(row, if_match)
        _assignment_refs(s, inp)
        _set_assignment(row, inp)
        touch(row)
        s.flush()
        audit(s, "shift_assignment", row.id, "update", {"version": row.row_version})
        return assignment_records(s, [row])[0]


def delete_assignment(ctx: AppContext, assignment_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgShiftAssignmentRow, assignment_id, what="Shift assignment", lock=True)
        check_version(row, if_match)
        s.delete(row)
        s.flush()
        audit(s, "shift_assignment", row.id, "delete", {"version": row.row_version})


# ---------------------------------------------------------------- calendar exceptions


def exception_records(s: Session, rows: list[MfgCalendarExceptionRow], utc_offset: str
                      ) -> list[CalendarExceptionRecord]:
    groups, lines = _targets(s, {r.group_id for r in rows if r.group_id}, {r.line_id for r in rows if r.line_id})
    return [repo.to_record(r, utc_offset=utc_offset, target=_target_ref(r.scope, r.group_id, r.line_id, groups, lines))
            for r in rows]


def list_exceptions(ctx: AppContext, d0: date | None, d1: date | None, scope: str | None, group_id: str | None,
                    line_id: str | None) -> dict[str, Any]:
    with read_tx(ctx) as s:
        off = plant_offset(s)
        tz = offset_tz(off)
        stmt = select(MfgCalendarExceptionRow)
        if d0 is not None:
            stmt = stmt.where(MfgCalendarExceptionRow.end_at
                               > datetime(d0.year, d0.month, d0.day, tzinfo=tz).astimezone(UTC))
        if d1 is not None:
            stmt = stmt.where(MfgCalendarExceptionRow.start_at
                               < datetime(d1.year, d1.month, d1.day, tzinfo=tz).astimezone(UTC))
        if scope:
            stmt = stmt.where(MfgCalendarExceptionRow.scope == scope)
        if group_id:
            stmt = stmt.where(MfgCalendarExceptionRow.group_id == group_id)
        if line_id:
            stmt = stmt.where(MfgCalendarExceptionRow.line_id == line_id)
        rows = list(s.execute(stmt.order_by(MfgCalendarExceptionRow.start_at, MfgCalendarExceptionRow.id)).scalars())
        return {"items": exception_records(s, rows, off)}


def _exception_refs(s: Session, inp: CalendarExceptionInput) -> None:
    if inp.scope == "group" and s.execute(select(MfgGroupRow.id).where(MfgGroupRow.id == inp.group_id)).scalar() is None:
        raise unknown_ref(["body", "group_id"], inp.group_id or "", "Stage")
    if inp.scope == "line" and s.execute(select(MfgLineRow.id).where(MfgLineRow.id == inp.line_id)).scalar() is None:
        raise unknown_ref(["body", "line_id"], inp.line_id or "", "Line")


def _set_exception(row: MfgCalendarExceptionRow, inp: CalendarExceptionInput) -> None:
    row.scope, row.group_id, row.line_id, row.kind = inp.scope, inp.group_id, inp.line_id, inp.kind
    row.start_at, row.end_at = inp.start.astimezone(UTC), inp.end.astimezone(UTC)
    row.label = inp.label


def create_exception(ctx: AppContext, inp: CalendarExceptionInput) -> CalendarExceptionRecord:
    with write_tx(ctx) as (s, plant):
        _exception_refs(s, inp)
        check_limit(s, MfgCalendarExceptionRow, L.MAX_CALENDAR_EXCEPTIONS, "calendar exceptions")
        now = utcnow()
        row = MfgCalendarExceptionRow(id=new_id("cex_"), row_version=1, created_at=now, updated_at=now)
        _set_exception(row, inp)
        s.add(row)
        s.flush()
        audit(s, "calendar_exception", row.id, "create", {"version": 1})
        return exception_records(s, [row], plant.utc_offset)[0]


def update_exception(ctx: AppContext, exception_id: str, inp: CalendarExceptionInput, if_match: str | None
                     ) -> CalendarExceptionRecord:
    with write_tx(ctx) as (s, plant):
        row = repo.get_row(s, MfgCalendarExceptionRow, exception_id, what="Calendar exception", lock=True)
        check_version(row, if_match)
        _exception_refs(s, inp)
        _set_exception(row, inp)
        touch(row)
        s.flush()
        audit(s, "calendar_exception", row.id, "update", {"version": row.row_version})
        return exception_records(s, [row], plant.utc_offset)[0]


def delete_exception(ctx: AppContext, exception_id: str, if_match: str | None) -> None:
    with write_tx(ctx) as (s, _):
        row = repo.get_row(s, MfgCalendarExceptionRow, exception_id, what="Calendar exception", lock=True)
        check_version(row, if_match)
        s.delete(row)
        s.flush()
        audit(s, "calendar_exception", row.id, "delete", {"version": row.row_version})

