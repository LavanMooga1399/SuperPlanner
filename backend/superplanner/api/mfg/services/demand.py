"""Demand orders (M2-DESIGN 3.6, 6, 12.3 #126-133): lines with due dates, priorities and unit serial ranges;
status machine from `mfg.demand`; shipped quantities move only through `ship` postings. Line projections come from
the latest completed live MRP run."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ....mfg import demand as DEM
from ....mfg.model_m2 import EPS, DemandOrderInput
from ....mfg.purchasing import RuleError
from ....mfg.units import is_count
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError
from ...schemas import as_utc
from .. import repo, repo_m2
from ..db_models_m2 import MfgDemandLineRow, MfgDemandOrderRow, MfgMrpDemandResultRow, MfgMrpRunRow
from .common import audit, check_version, ensure_unique, ilike, read_tx, touch, unknown_ref
from .m2util import iref, items, page, r6, rule_error, run_tx

WHAT = "Demand order"


def latest_live_run(s: Session) -> MfgMrpRunRow | None:
    return s.execute(select(MfgMrpRunRow).where(MfgMrpRunRow.kind == "live", MfgMrpRunRow.status == "completed")
                     .order_by(MfgMrpRunRow.run_no.desc()).limit(1)).scalars().first()


def _projections(s: Session, line_ids: list[str]) -> dict[str, dict[str, Any]]:
    run = latest_live_run(s)
    if run is None or not line_ids:
        return {}
    rows = s.execute(select(MfgMrpDemandResultRow).where(MfgMrpDemandResultRow.run_id == run.id,
                                                         MfgMrpDemandResultRow.demand_line_id.in_(line_ids))).scalars()
    return {r.demand_line_id: {"run_id": run.id, "run_no": run.run_no, "projected_date": r.projected_date,
                               "late_days": r.late_days, "status": r.status} for r in rows}


def order_records(s: Session, orders: list[MfgDemandOrderRow], *, full: bool = True) -> list[dict[str, Any]]:
    ids = [o.id for o in orders]
    lines: dict[str, list[MfgDemandLineRow]] = {i: [] for i in ids}
    if ids:
        for ln in s.execute(select(MfgDemandLineRow).where(MfgDemandLineRow.order_id.in_(ids))
                            .order_by(MfgDemandLineRow.line_no)).scalars():
            lines[ln.order_id].append(ln)
    all_lines = [x for v in lines.values() for x in v]
    proj = _projections(s, [x.id for x in all_lines])
    its = items(s, [x.item_id for x in all_lines]) if full else {}
    out = []
    for o in orders:
        base = {"id": o.id, "number": o.number, "demand_type": o.demand_type, "customer": o.customer,
                "program": o.program, "priority": o.priority, "status": o.status, "row_version": o.row_version,
                "created_at": as_utc(o.created_at), "updated_at": as_utc(o.updated_at)}
        if not full:
            open_lines = [x for x in lines[o.id] if x.qty - x.shipped_qty > EPS]
            base.update(line_count=len(lines[o.id]), open_qty=r6(sum(x.qty - x.shipped_qty for x in open_lines)),
                        next_due=min((x.due_date for x in open_lines), default=None),
                        late_lines=sum(1 for x in lines[o.id] if proj.get(x.id, {}).get("late_days", 0) > 0)
                        if proj else None)
            out.append(base)
            continue
        base.update(note=o.note, external_ref=o.external_ref, lines=[{
            "id": x.id, "line_no": x.line_no, "item_id": x.item_id, "item": iref(its.get(x.item_id), x.item_id),
            "qty": r6(x.qty), "due_date": x.due_date, "serial_from": x.serial_from, "serial_to": x.serial_to,
            "priority": x.priority, "note": x.note, "shipped_qty": r6(x.shipped_qty),
            "open_qty": r6(DEM.open_qty(x.qty, x.shipped_qty)), "line_status": DEM.line_status(x.qty, x.shipped_qty),
            "effective_priority": DEM.effective_priority(x.priority, o.priority), "projection": proj.get(x.id)}
            for x in lines[o.id]])
        out.append(base)
    return out


def get_order(ctx: AppContext, order_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return order_records(s, [repo.get_row(s, MfgDemandOrderRow, order_id, what=WHAT)])[0]


def list_orders(ctx: AppContext, *, status: str | None, demand_type: str | None, program: str | None,
                item_id: str | None, due_from: date | None, due_to: date | None, late_only: bool, q: str | None,
                limit: int, offset: int) -> dict[str, Any]:
    O, Ln = MfgDemandOrderRow, MfgDemandLineRow
    conds: list[Any] = []
    for col, v in ((O.status, status), (O.demand_type, demand_type), (O.program, program)):
        if v:
            conds.append(col == v)
    if q:
        conds.append(ilike(O.number, q) | ilike(O.customer, q) | ilike(func.coalesce(O.external_ref, ""), q))
    line_conds = []
    if item_id:
        line_conds.append(Ln.item_id == item_id)
    if due_from:
        line_conds.append(Ln.due_date >= due_from)
    if due_to:
        line_conds.append(Ln.due_date <= due_to)
    if line_conds:
        conds.append(O.id.in_(select(Ln.order_id).where(*line_conds)))
    with read_tx(ctx) as s:
        if late_only:
            run = latest_live_run(s)
            if run is None:
                return page([], 0, limit, offset)
            conds.append(O.id.in_(select(MfgMrpDemandResultRow.order_id).where(
                MfgMrpDemandResultRow.run_id == run.id, MfgMrpDemandResultRow.late_days > 0)))
        rows = list(s.execute(select(O).where(*conds).order_by(O.number, O.id).limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(O).where(*conds)).scalar() or 0)
        return page(order_records(s, rows, full=False), total, limit, offset)


def _validate(s: Session, inp: DemandOrderInput) -> None:
    its = items(s, [ln.item_id for ln in inp.lines])
    for i, ln in enumerate(inp.lines):
        it = its.get(ln.item_id)
        if it is None:
            raise unknown_ref(["body", "lines", i, "item_id"], ln.item_id, "Item")
        if not it.active or it.make_buy == "phantom":
            raise ApiError(422, "DEM_ITEM_NOT_PLANNABLE", f"{it.part_number} is {'a phantom' if it.active else 'inactive'}"
                           " and cannot be ordered.", {"loc": ["body", "lines", i, "item_id"]})
        if is_count(it.uom) and abs(ln.qty - round(ln.qty)) > EPS:
            raise ApiError(422, "INV_FRACTIONAL_QTY", f"{it.part_number} is counted in {it.uom}; use whole numbers.",
                           {"loc": ["body", "lines", i, "qty"]})
        err = DEM.serial_qty_error(it.serialized, ln.qty, ln.serial_from, ln.serial_to)
        if err is not None:
            err.details["loc"] = ["body", "lines", i, "serial_from"]
            raise rule_error(err)
    pairs = DEM.serial_overlaps([DEM.SerialLine(i, ln.item_id, ln.serial_from, ln.serial_to)
                                 for i, ln in enumerate(inp.lines)])
    if pairs:
        a, b = pairs[0]
        raise ApiError(422, "DEM_SERIAL_OVERLAP", f"Lines {a + 1} and {b + 1} use overlapping serial numbers.",
                       {"loc": ["body", "lines", b, "serial_from"], "lines": [a, b]})


def _write_lines(s: Session, o: MfgDemandOrderRow, inp: DemandOrderInput, creating: bool) -> None:
    now = utcnow()
    old = {x.id: x for x in repo_m2.lock_children_of(s, MfgDemandLineRow, "order_id", [o.id])} if not creating else {}
    used = [ln.line_no for ln in inp.lines if ln.line_no is not None]
    nxt = 10
    keep: dict[str, int] = {}
    new: list[MfgDemandLineRow] = []
    for i, li in enumerate(inp.lines):
        no = li.line_no
        if no is None:
            while nxt in used:
                nxt += 10
            no = nxt
            used.append(no)
            nxt += 10
        if li.id is not None:
            x = old.get(li.id)
            if x is None:
                raise unknown_ref(["body", "lines", i, "id"], li.id, "Line")
            try:
                DEM.check_line_edit(x.shipped_qty > EPS, False, li.qty, x.shipped_qty, i)
            except RuleError as e:
                raise rule_error(e) from None
            if x.shipped_qty > EPS and x.item_id != li.item_id:
                raise ApiError(422, "DEM_LINE_HAS_SHIPMENTS", "A line with shipments cannot change its item.",
                               {"loc": ["body", "lines", i, "item_id"]})
            x.item_id, x.qty, x.due_date, x.serial_from, x.serial_to = (li.item_id, li.qty, li.due_date,
                                                                         li.serial_from, li.serial_to)
            x.priority, x.note = li.priority, li.note
            keep[x.id] = no
            touch(x, now)
        else:
            new.append(MfgDemandLineRow(id=new_id("dml_"), order_id=o.id, line_no=no, item_id=li.item_id, qty=li.qty,
                                        due_date=li.due_date, shipped_qty=0.0, serial_from=li.serial_from,
                                        serial_to=li.serial_to, priority=li.priority, note=li.note, row_version=1,
                                        created_at=now, updated_at=now))
    gone = [x for x in old.values() if x.id not in keep]
    for x in gone:
        if x.shipped_qty > EPS:
            raise ApiError(422, "DEM_LINE_HAS_SHIPMENTS", f"Line {x.line_no} has shipments and cannot be removed.",
                           {"line_id": x.id})
    if gone:
        s.execute(delete(MfgDemandLineRow).where(MfgDemandLineRow.id.in_([x.id for x in gone]))
                  .execution_options(synchronize_session=False))
        for x in gone:
            s.expunge(x)
    for k, x in enumerate(old.get(i) for i in keep):
        x.line_no = -(k + 1)
    s.flush()
    for i, no in keep.items():
        old[i].line_no = no
    s.flush()
    s.add_all(new)
    s.flush()


def create_order(ctx: AppContext, inp: DemandOrderInput) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        _validate(s, inp)
        if inp.number is not None:
            ensure_unique(s, MfgDemandOrderRow, "A demand order", {"number": inp.number})
        if inp.external_ref is not None:
            ensure_unique(s, MfgDemandOrderRow, "A demand order", {"external_ref": inp.external_ref})
        number = inp.number or repo_m2.next_number(s, "DO", repo_m2.number_taken(s, MfgDemandOrderRow))
        now = utcnow()
        o = MfgDemandOrderRow(id=new_id("dmo_"), number=number, demand_type=inp.demand_type, customer=inp.customer,
                              program=inp.program, priority=inp.priority, status="draft", note=inp.note,
                              external_ref=inp.external_ref, row_version=1, created_at=now, updated_at=now)
        s.add(o)
        s.flush()
        _write_lines(s, o, inp, True)
        audit(s, "demand_order", o.id, "create", {"number": number, "lines": len(inp.lines)})
        rec = order_records(s, [o])[0]
        rec["_rush"] = _rush(s, o)
        return rec

    return _after_rush(ctx, run_tx(ctx, fn))


def _rush(s: Session, o: MfgDemandOrderRow) -> list[Any]:
    """M4-DESIGN 7 `rush_order`: demand lines of priority <= 2 (line priority, else the order's)."""
    from . import replan

    out: list[Any] = []
    for dl in s.execute(select(MfgDemandLineRow).where(MfgDemandLineRow.order_id == o.id)).scalars():
        prio = dl.priority if dl.priority is not None else o.priority
        out += replan.on_document(s, "demand_line", dl.id, f"{o.number}/{dl.line_no}", prio, dl.due_date)
    return out


def _after_rush(ctx: AppContext, rec: dict[str, Any]) -> dict[str, Any]:
    if rec.pop("_rush", None):
        from . import replan

        replan.apply_policy(ctx)
    return rec


def update_order(ctx: AppContext, order_id: str, inp: DemandOrderInput, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        o = repo.get_row(s, MfgDemandOrderRow, order_id, what=WHAT, lock=True)
        check_version(o, if_match)
        try:
            DEM.check_editable(o.status)
        except RuleError as e:
            raise rule_error(e) from None
        _validate(s, inp)
        if inp.number is not None and inp.number != o.number:
            ensure_unique(s, MfgDemandOrderRow, "A demand order", {"number": inp.number}, exclude_id=o.id)
            o.number = inp.number
        if inp.external_ref is not None:
            ensure_unique(s, MfgDemandOrderRow, "A demand order", {"external_ref": inp.external_ref},
                          exclude_id=o.id)
        o.demand_type, o.customer, o.program, o.priority = inp.demand_type, inp.customer, inp.program, inp.priority
        o.note, o.external_ref = inp.note, inp.external_ref
        _write_lines(s, o, inp, False)
        lines = list(s.execute(select(MfgDemandLineRow.qty, MfgDemandLineRow.shipped_qty)
                               .where(MfgDemandLineRow.order_id == o.id)).all())
        o.status = DEM.derive_status(o.status, [(a, b) for a, b in lines])
        touch(o)
        s.flush()
        audit(s, "demand_order", o.id, "update", {"number": o.number, "version": o.row_version})
        rec = order_records(s, [o])[0]
        rec["_rush"] = _rush(s, o)
        return rec

    return _after_rush(ctx, run_tx(ctx, fn))


def _shipped(s: Session, order_id: str) -> bool:
    return bool(s.execute(select(func.count()).select_from(MfgDemandLineRow).where(
        MfgDemandLineRow.order_id == order_id, MfgDemandLineRow.shipped_qty > EPS)).scalar())


def delete_order(ctx: AppContext, order_id: str, if_match: str | None) -> None:
    def fn(s: Session) -> None:
        o = repo.get_row(s, MfgDemandOrderRow, order_id, what=WHAT, lock=True)
        check_version(o, if_match)
        try:
            DEM.check_deletable(o.status, _shipped(s, o.id))
        except RuleError as e:
            raise rule_error(e) from None
        audit(s, "demand_order", o.id, "delete", {"number": o.number})
        s.delete(o)
        s.flush()

    run_tx(ctx, fn)


def action(ctx: AppContext, order_id: str, act: str, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        o = repo.get_row(s, MfgDemandOrderRow, order_id, what=WHAT, lock=True)
        check_version(o, if_match)
        try:
            o.status = DEM.check_action(o.status, act, has_shipments=_shipped(s, o.id))
        except RuleError as e:
            raise rule_error(e) from None
        touch(o)
        s.flush()
        audit(s, "demand_order", o.id, act, {"number": o.number, "status": o.status})
        return order_records(s, [o])[0]

    return run_tx(ctx, fn)
