"""Manufacturing repository (M1-DESIGN 6.4): the only DB reads the mfg services use, plus the per-owner plant lock.

- Every query is an ORM query, so the central ownership filter (`with_loader_criteria`) applies; nothing here
  filters by owner itself.
- Loaders issue a fixed or depth-bounded number of SELECTs (asserted by statement-count tests); relationships are
  `lazy="raise"`, so the loaders never touch them.
- `to_record` builds records with `model_construct` (rows were validated on write); datetimes go through `as_utc`
  (SQLite returns naive datetimes).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...mfg.calendar import offset_tz
from ...mfg.dataset import BomIndex, MfgDataset, ParentIndex, item_ref, link, pick_effective, primary_ops_of
from ...mfg.limits import SQL_IN_CHUNK
from ...mfg.model import (BomLineRecord, BomRecord, BreakDef, CalendarExceptionRecord, GroupRecord, ItemRecord,
                          LineRecord, OperationRecord, OperationToolRecord, OperatorRecord, PlantInput, PlantRecord,
                          RoutingRecord, ShiftAssignmentRecord, ShiftDef, ShiftTemplateRecord, SkillRecord,
                          ToolPoolRecord)
from ...mfg.routing import effective_routings
from ..db.locks import is_unique_violation
from ..db.models import new_id, utcnow
from ..errors import not_found
from ..schemas import as_utc
from .db_models import (MfgBomLineRow, MfgBomRow, MfgCalendarExceptionRow, MfgGroupRow, MfgItemRow, MfgLineItemRow,
                        MfgLineRow, MfgOperationRow, MfgOperationToolRow, MfgOperatorRow, MfgOperatorSkillRow,
                        MfgPlantRow, MfgRoutingRow, MfgShiftAssignmentRow, MfgShiftTemplateRow, MfgSkillRow,
                        MfgToolPoolRow)

# ---------------------------------------------------------------- plant


def _default_plant() -> PlantRecord:
    return PlantRecord.model_construct(**PlantInput().__dict__, id=None, row_version=0, created_at=None,
                                       updated_at=None, data_version=0)


def plant_or_default(s: Session) -> PlantRecord:
    """Read path (review R6): the stored plant row, or an unsaved default (`id None`, `row_version 0`). Never
    inserts."""
    row = s.execute(select(MfgPlantRow)).scalars().first()
    return to_record(row) if row is not None else _default_plant()


def _select_plant_locked(s: Session) -> MfgPlantRow | None:
    return s.execute(select(MfgPlantRow).with_for_update(key_share=True)
                     .execution_options(populate_existing=True)).scalars().first()


def lock_plant(s: Session) -> MfgPlantRow:
    """Write path (6.1): lock the owner's plant row `FOR NO KEY UPDATE` (the per-owner mutex), creating the default
    row inside a savepoint if absent (a concurrent first write that loses the `uq_mfg_plant_owner` race rolls the
    savepoint back and locks the winner's row), then bump `data_version`. Call once per write transaction, first."""
    row = _select_plant_locked(s)
    if row is None:
        d = PlantInput()
        now = utcnow()
        try:
            with s.begin_nested():
                row = MfgPlantRow(id=new_id("plt_"), name=d.name, utc_offset=d.utc_offset,
                                  planning_horizon_days=d.planning_horizon_days, currency=d.currency, attributes={},
                                  data_version=0, row_version=1, created_at=now, updated_at=now)
                s.add(row)
                s.flush()
        except IntegrityError as exc:
            if not is_unique_violation(exc, "uq_mfg_plant_owner", "mfg_plant.owner_id"):
                raise
            row = _select_plant_locked(s)
            if row is None:  # pragma: no cover - the winner's row must be visible after its commit
                raise
    row.data_version = (row.data_version or 0) + 1
    s.flush()
    return row


def get_row(s: Session, model: Any, row_id: str, *, what: str, lock: bool = False) -> Any:
    """Owned lookup by id (`not_found(what, id)` -> 404 for unknown and foreign ids alike). `lock=True` takes
    `FOR NO KEY UPDATE` (no-op on SQLite)."""
    stmt = select(model).where(model.id == row_id)
    if lock:
        stmt = stmt.with_for_update(key_share=True)
    row = s.execute(stmt).scalars().first()
    if row is None:
        raise not_found(what, row_id)
    return row


# ---------------------------------------------------------------- rows -> records


def _stamp(row: Any) -> dict[str, Any]:
    return {"id": row.id, "row_version": row.row_version, "created_at": as_utc(row.created_at),
            "updated_at": as_utc(row.updated_at)}


def _shift_defs(raw: list[dict[str, Any]]) -> list[ShiftDef]:
    out = []
    for sh in raw or []:
        out.append(ShiftDef.model_construct(
            name=sh["name"], days=list(sh["days"]), start=sh["start"], end=sh["end"],
            breaks=[BreakDef.model_construct(name=b.get("name", ""), start=b["start"], end=b["end"])
                    for b in sh.get("breaks") or []]))
    return out


def to_record(row: Any, **extra: Any) -> Any:
    """ORM row -> `<Entity>Record` (`model_construct`). Pass denormalised fields the caller knows (refs, counts,
    `lines`/`operations`/`tools`, `eligible_item_ids`, `skill_ids`) as keywords; counts default to 0 and lists to
    empty. Calendar exceptions accept `utc_offset` to return `start`/`end` in the plant offset."""
    if isinstance(row, MfgPlantRow):
        return PlantRecord.model_construct(
            name=row.name, utc_offset=row.utc_offset, planning_horizon_days=row.planning_horizon_days,
            currency=row.currency, attributes=dict(row.attributes or {}), data_version=row.data_version,
            **_stamp(row), **extra)
    if isinstance(row, MfgItemRow):
        data = dict(part_number=row.part_number, revision=row.revision, description=row.description, uom=row.uom,
                    make_buy=row.make_buy, family=row.family, setup_family=row.setup_family,
                    lead_time_days=row.lead_time_days, receiving_days=row.receiving_days, lot_rule=row.lot_rule,
                    fixed_lot_qty=row.fixed_lot_qty, min_order_qty=row.min_order_qty,
                    order_multiple=row.order_multiple, safety_stock=row.safety_stock, serialized=row.serialized,
                    shelf_life_days=row.shelf_life_days, handling_class=row.handling_class,
                    handling_note=row.handling_note, attributes=dict(row.attributes or {}), active=row.active,
                    has_bom=False, has_routing=False, used_in_count=0)
        data.update(extra)
        return ItemRecord.model_construct(**_stamp(row), **data)
    if isinstance(row, MfgBomRow):
        data = dict(item_id=row.item_id, revision=row.revision, version=row.version, status=row.status,
                    effective_from=row.effective_from, effective_to=row.effective_to, serial_from=row.serial_from,
                    serial_to=row.serial_to, note=row.note, released_at=as_utc(row.released_at),
                    obsoleted_at=as_utc(row.obsoleted_at), lines=[])
        data.update(extra)
        return BomRecord.model_construct(**_stamp(row), **data)
    if isinstance(row, MfgBomLineRow):
        data = dict(id=row.id, find_number=row.find_number, child_item_id=row.child_item_id, qty_per=row.qty_per,
                    uom=row.uom, scrap_pct=row.scrap_pct, ref_designators=row.ref_designators,
                    alt_group=row.alt_group, alt_priority=row.alt_priority, operation_seq=row.operation_seq,
                    note=row.note)
        data.update(extra)
        return BomLineRecord.model_construct(**data)
    if isinstance(row, MfgRoutingRow):
        data = dict(item_id=row.item_id, revision=row.revision, code=row.code, version=row.version,
                    priority=row.priority, status=row.status, effective_from=row.effective_from,
                    effective_to=row.effective_to, serial_from=row.serial_from, serial_to=row.serial_to,
                    note=row.note, released_at=as_utc(row.released_at), obsoleted_at=as_utc(row.obsoleted_at),
                    operations=[])
        data.update(extra)
        return RoutingRecord.model_construct(**_stamp(row), **data)
    if isinstance(row, MfgOperationRow):
        data = dict(id=row.id, seq=row.seq, name=row.name, description=row.description, group_id=row.group_id,
                    setup_minutes=row.setup_minutes, run_minutes=row.run_minutes, run_per=row.run_per,
                    units_per_panel=row.units_per_panel, units_per_batch=row.units_per_batch,
                    queue_minutes=row.queue_minutes, move_minutes=row.move_minutes, wait_minutes=row.wait_minutes,
                    labor=row.labor, crew_size=row.crew_size, skill_id=row.skill_id,
                    transfer_batch=row.transfer_batch, yield_pct=row.yield_pct, inspection_gate=row.inspection_gate,
                    interruptible=row.interruptible, tools=[], skill=None)
        data.update(extra)
        return OperationRecord.model_construct(**data)
    if isinstance(row, MfgOperationToolRow):
        return OperationToolRecord.model_construct(tool_pool_id=row.tool_pool_id, qty=row.qty, **extra)
    if isinstance(row, MfgGroupRow):
        data = dict(code=row.code, name=row.name, description=row.description, kind=row.kind, active=row.active,
                    line_count=0)
        data.update(extra)
        return GroupRecord.model_construct(**_stamp(row), **data)
    if isinstance(row, MfgLineRow):
        data = dict(group_id=row.group_id, code=row.code, name=row.name, speed_factor=row.speed_factor,
                    parallel_capacity=row.parallel_capacity, setup_family=row.setup_family,
                    eligible_families=list(row.eligible_families or []), eligible_item_ids=[],
                    cost_per_hour=row.cost_per_hour, active=row.active, eligible_items=[])
        data.update(extra)
        return LineRecord.model_construct(**_stamp(row), **data)
    if isinstance(row, MfgShiftTemplateRow):
        data = dict(code=row.code, name=row.name, description=row.description, shifts=_shift_defs(row.shifts),
                    assignment_count=0, operator_count=0)
        data.update(extra)
        return ShiftTemplateRecord.model_construct(**_stamp(row), **data)
    if isinstance(row, MfgShiftAssignmentRow):
        data = dict(shift_template_id=row.shift_template_id, target_type=row.target_type, group_id=row.group_id,
                    line_id=row.line_id, kind=row.kind, shift_names=list(row.shift_names or []),
                    effective_from=row.effective_from, effective_to=row.effective_to,
                    cost_per_hour=row.cost_per_hour, max_hours_per_week=row.max_hours_per_week, note=row.note)
        data.update(extra)
        return ShiftAssignmentRecord.model_construct(**_stamp(row), **data)
    if isinstance(row, MfgCalendarExceptionRow):
        offset = extra.pop("utc_offset", None)
        start, end = as_utc(row.start_at), as_utc(row.end_at)
        if offset is not None:
            tz = offset_tz(offset)
            start, end = start.astimezone(tz), end.astimezone(tz)
        data = dict(scope=row.scope, group_id=row.group_id, line_id=row.line_id, kind=row.kind, start=start,
                    end=end, label=row.label, target=None)
        data.update(extra)
        return CalendarExceptionRecord.model_construct(**_stamp(row), **data)
    if isinstance(row, MfgSkillRow):
        data = dict(code=row.code, name=row.name, description=row.description, operator_count=0, operation_count=0)
        data.update(extra)
        return SkillRecord.model_construct(**_stamp(row), **data)
    if isinstance(row, MfgOperatorRow):
        data = dict(code=row.code, name=row.name, skill_ids=[], shift_template_id=row.shift_template_id,
                    shift_names=list(row.shift_names or []), home_group_id=row.home_group_id, active=row.active,
                    skills=[], shift_template=None, home_group=None)
        data.update(extra)
        return OperatorRecord.model_construct(**_stamp(row), **data)
    if isinstance(row, MfgToolPoolRow):
        data = dict(code=row.code, name=row.name, kind=row.kind, quantity=row.quantity, note=row.note,
                    operation_count=0)
        data.update(extra)
        return ToolPoolRecord.model_construct(**_stamp(row), **data)
    raise TypeError(f"no record type for {type(row).__name__}")


# ---------------------------------------------------------------- full snapshot


def load_dataset(s: Session) -> MfgDataset:
    """The owner's complete snapshot: one SELECT per table (17, the plant included), no lazy loads; refs and
    counts are filled by `dataset.link`."""
    def rows(model: Any) -> list[Any]:
        return list(s.execute(select(model)).scalars())

    plant_rows = rows(MfgPlantRow)
    plant = to_record(plant_rows[0]) if plant_rows else _default_plant()
    ds = MfgDataset(plant=plant)
    for r in rows(MfgItemRow):
        ds.items[r.id] = to_record(r)
    lines_by_bom: dict[str, list[BomLineRecord]] = {}
    boms = rows(MfgBomRow)
    for r in rows(MfgBomLineRow):
        lines_by_bom.setdefault(r.bom_id, []).append(to_record(r))
    for r in boms:
        ds.boms[r.id] = to_record(r, lines=lines_by_bom.get(r.id, []))
    routings = rows(MfgRoutingRow)
    ops = rows(MfgOperationRow)
    tools_by_op: dict[str, list[OperationToolRecord]] = {}
    for r in sorted(rows(MfgOperationToolRow), key=lambda t: t.id):
        tools_by_op.setdefault(r.operation_id, []).append(to_record(r))
    ops_by_routing: dict[str, list[OperationRecord]] = {}
    for r in ops:
        ops_by_routing.setdefault(r.routing_id, []).append(to_record(r, tools=tools_by_op.get(r.id, [])))
    for r in routings:
        ds.routings[r.id] = to_record(r, operations=ops_by_routing.get(r.id, []))
    for r in rows(MfgGroupRow):
        ds.groups[r.id] = to_record(r)
    items_by_line: dict[str, list[str]] = {}
    lines = rows(MfgLineRow)
    for r in sorted(rows(MfgLineItemRow), key=lambda x: (x.line_id, x.item_id)):
        items_by_line.setdefault(r.line_id, []).append(r.item_id)
    for r in lines:
        ds.lines[r.id] = to_record(r, eligible_item_ids=items_by_line.get(r.id, []))
    for r in rows(MfgShiftTemplateRow):
        ds.shift_templates[r.id] = to_record(r)
    for r in rows(MfgShiftAssignmentRow):
        ds.shift_assignments[r.id] = to_record(r)
    for r in rows(MfgCalendarExceptionRow):
        ds.calendar_exceptions[r.id] = to_record(r, utc_offset=plant.utc_offset)
    for r in rows(MfgSkillRow):
        ds.skills[r.id] = to_record(r)
    skills_by_op: dict[str, list[str]] = {}
    operators = rows(MfgOperatorRow)
    for r in sorted(rows(MfgOperatorSkillRow), key=lambda x: (x.operator_id, x.skill_id)):
        skills_by_op.setdefault(r.operator_id, []).append(r.skill_id)
    for r in operators:
        ds.operators[r.id] = to_record(r, skill_ids=skills_by_op.get(r.id, []))
    for r in rows(MfgToolPoolRow):
        ds.tool_pools[r.id] = to_record(r)
    return link(ds)


# ---------------------------------------------------------------- level-wise loaders


def _chunks(ids: Iterable[str]) -> Iterator[list[str]]:
    ids = list(ids)
    for i in range(0, len(ids), SQL_IN_CHUNK):
        yield ids[i:i + SQL_IN_CHUNK]


def _in(s: Session, stmt_for: Any, ids: Iterable[str]) -> list[Any]:
    out: list[Any] = []
    for chunk in _chunks(ids):
        out.extend(s.execute(stmt_for(chunk)).all())
    return out


def load_bom_index_down(s: Session, root_item_id: str, on: date, serial: int | None) -> BomIndex:
    """Level-wise BFS from the root (6.4): per level <= 3 SELECTs (items, released BOM headers of the level's
    make/phantom items, lines of the effective BOMs), then 2 (released routings of every make item seen,
    operations of the primary routings). Items already loaded are never re-selected; alternates are loaded but not
    descended into. Unknown root -> `not_found`."""
    from ...mfg.limits import MAX_BOM_DEPTH

    items: dict[str, ItemRecord] = {}
    effective: dict[str, BomRecord | None] = {}
    frontier = [root_item_id]          # items of this level (primaries and alternates)
    descend = {root_item_id}           # the ones whose structure is followed (primaries)
    level = 0
    while frontier:
        fresh = [i for i in dict.fromkeys(frontier) if i not in items]
        for (row,) in _in(s, lambda ids: select(MfgItemRow).where(MfgItemRow.id.in_(ids)), fresh):
            items[row.id] = to_record(row)
        if root_item_id not in items:
            raise not_found("Item", root_item_id)
        parents = [i for i in fresh if i in descend and i in items and items[i].make_buy in ("make", "phantom")]
        if not parents:
            break
        headers: dict[str, list[BomRecord]] = {}
        for (row,) in _in(s, lambda ids: select(MfgBomRow).where(MfgBomRow.item_id.in_(ids),
                                                                 MfgBomRow.status == "released"), parents):
            headers.setdefault(row.item_id, []).append(to_record(row))
        chosen: dict[str, BomRecord] = {}
        for p in parents:
            b = pick_effective(headers.get(p, []), on, serial)
            effective[p] = b
            if b is not None:
                chosen[b.id] = b
        if not chosen:
            break
        for (row,) in _in(s, lambda ids: select(MfgBomLineRow).where(MfgBomLineRow.bom_id.in_(ids)), chosen):
            chosen[row.bom_id].lines.append(to_record(row))
        if level >= MAX_BOM_DEPTH:      # explode cuts here (MFG_BOM_TOO_DEEP); deeper items are never needed
            break
        frontier = [ln.child_item_id for b in chosen.values() for ln in b.lines]
        descend = {ln.child_item_id for b in chosen.values() for ln in b.lines
                   if ln.alt_group is None or ln.alt_priority == 1}
        level += 1
    makes = [i for i, it in items.items() if it.make_buy == "make"]
    by_item: dict[str, list[RoutingRecord]] = {}
    for (row,) in _in(s, lambda ids: select(MfgRoutingRow).where(MfgRoutingRow.item_id.in_(ids),
                                                                 MfgRoutingRow.status == "released"), makes):
        by_item.setdefault(row.item_id, []).append(to_record(row))
    shadow = MfgDataset(plant=_default_plant())
    for rs in by_item.values():
        for r in rs:
            shadow.routings[r.id] = r
    primary: dict[str, RoutingRecord] = {}
    for item_id in by_item:
        rs = effective_routings(shadow, item_id, on, serial)
        if rs:
            primary[rs[0].id] = rs[0]
    if primary:
        for (row,) in _in(s, lambda ids: select(MfgOperationRow).where(MfgOperationRow.routing_id.in_(ids)),
                          primary):
            primary[row.routing_id].operations.append(to_record(row))
    refs = {i: item_ref(it) for i, it in items.items()}
    for b in effective.values():
        if b is not None:
            b.item = refs[b.item_id]
            for ln in b.lines:
                if ln.child_item_id in refs:
                    ln.child = refs[ln.child_item_id]
    ops = {r.item_id: primary_ops_of(r) for r in primary.values()}
    rids = {r.item_id: r.id for r in primary.values()}
    return BomIndex(items, effective, ops, routing_ids=rids, on=on, serial=serial)


def load_parent_index(s: Session, item_id: str, on: date | None, include: str) -> ParentIndex:
    """Level-wise upward (6.4): 1 SELECT for the item, then per level 1 SELECT of (line, header) pairs using the
    frontier as children (headers filtered by `include`/`on` as `ParentIndex.bom_in_scope`) and 1 SELECT of the
    new parent items: <= 2 x levels + 1 (the 6.4 bound is 3 x levels + 1)."""
    items: dict[str, ItemRecord] = {}
    for (row,) in _in(s, lambda ids: select(MfgItemRow).where(MfgItemRow.id.in_(ids)), [item_id]):
        items[row.id] = to_record(row)
    if item_id not in items:
        raise not_found("Item", item_id)
    parent_lines: dict[str, list[tuple[BomRecord, BomLineRecord]]] = {}
    boms: dict[str, BomRecord] = {}
    done: set[str] = set()
    frontier = [item_id]
    while frontier:
        done.update(frontier)

        def stmt(ids: list[str]) -> Any:
            q = select(MfgBomLineRow, MfgBomRow).join(MfgBomRow, MfgBomRow.id == MfgBomLineRow.bom_id) \
                .where(MfgBomLineRow.child_item_id.in_(ids))
            if include == "all":
                return q.where(MfgBomRow.status != "obsolete")
            q = q.where(MfgBomRow.status == "released")
            if on is not None:
                q = q.where((MfgBomRow.effective_from.is_(None)) | (MfgBomRow.effective_from <= on),
                            (MfgBomRow.effective_to.is_(None)) | (MfgBomRow.effective_to > on))
            return q

        new_parents: list[str] = []
        for ln_row, b_row in _in(s, stmt, frontier):
            b = boms.get(b_row.id)
            if b is None:
                b = boms[b_row.id] = to_record(b_row)
            ln = to_record(ln_row)
            parent_lines.setdefault(ln.child_item_id, []).append((b, ln))
            if b.item_id not in done and b.item_id not in items:
                new_parents.append(b.item_id)
        new_parents = list(dict.fromkeys(new_parents))
        for (row,) in _in(s, lambda ids: select(MfgItemRow).where(MfgItemRow.id.in_(ids)), new_parents):
            items[row.id] = to_record(row)
        frontier = [p for p in new_parents if p not in done]
    refs = {i: item_ref(it) for i, it in items.items()}
    for b in boms.values():
        if b.item_id in refs:
            b.item = refs[b.item_id]
    for pairs in parent_lines.values():
        for _b, ln in pairs:
            if ln.child_item_id in refs:
                ln.child = refs[ln.child_item_id]
    return ParentIndex(items, parent_lines, on=on, include=include)  # type: ignore[arg-type]


def bom_edge_list(s: Session) -> list[tuple[str, str]]:
    """(parent item, child item) over draft + released BOMs: one SELECT."""
    q = select(MfgBomRow.item_id, MfgBomLineRow.child_item_id).join(MfgBomRow, MfgBomRow.id == MfgBomLineRow.bom_id) \
        .where(MfgBomRow.status != "obsolete").distinct().order_by(MfgBomRow.item_id, MfgBomLineRow.child_item_id)
    return [(a, b) for a, b in s.execute(q).all()]
