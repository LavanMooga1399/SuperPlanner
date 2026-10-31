"""Work orders (M2-DESIGN 3.7, 7, 12.3 #134-147): frozen component lists generated from the effective BOM
(`mfg.workorders.generate_components` = the MRP engine's `order_components`), status flow, hard reservations,
per-WO kitting and the plant-wide kitting check. Issues/returns/receipts are inventory postings.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ....mfg import workorders as WOR
from ....mfg import purchasing as PUR
from ....mfg.model_m2 import EPS, NETTABLE_NOW_KINDS, WorkOrderInput
from ....mfg.purchasing import RuleError
from ....mfg.units import is_count
from ....mfg.workdays import WorkCalendar
from ...context import AppContext
from ...db import new_id, utcnow
from ...errors import ApiError
from ...schemas import as_utc
from .. import repo, repo_m2
from ..db_models import MfgBomRow, MfgItemRow, MfgRoutingRow
from ..db_models_m2 import (MfgDemandLineRow, MfgDemandOrderRow, MfgInvBalanceRow, MfgInvReservationRow,
                            MfgInvTransactionRow, MfgLocationRow, MfgLotRow, MfgPurchaseDocRow, MfgPurchaseLineRow,
                            MfgPurchaseScheduleRow, MfgWoComponentRow, MfgWorkOrderRow)
from .common import audit, check_version, ensure_unique, ilike, read_tx, touch, unknown_ref
from .inventory import release_reservations
from .m2util import iref, items, page, r6, rule_error, run_tx, today

WHAT = "Work order"


# ---------------------------------------------------------------- records


def _components(s: Session, wo_ids: list[str]) -> dict[str, list[MfgWoComponentRow]]:
    out: dict[str, list[MfgWoComponentRow]] = {i: [] for i in wo_ids}
    if wo_ids:
        for c in s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id.in_(wo_ids))
                           .order_by(MfgWoComponentRow.find_number, MfgWoComponentRow.id)).scalars():
            out[c.wo_id].append(c)
    return out


def _reserved(s: Session, comp_ids: list[str]) -> dict[str, float]:
    if not comp_ids:
        return {}
    return {k: float(v) for k, v in s.execute(select(MfgInvReservationRow.wo_component_id,
                                                     func.sum(MfgInvReservationRow.qty))
                                              .where(MfgInvReservationRow.wo_component_id.in_(comp_ids))
                                              .group_by(MfgInvReservationRow.wo_component_id)).all()}


def wo_records(s: Session, wos: list[MfgWorkOrderRow], *, full: bool = True) -> list[dict[str, Any]]:
    ids = [w.id for w in wos]
    comps = _components(s, ids)
    allc = [c for v in comps.values() for c in v]
    its = items(s, [w.item_id for w in wos] + ([c.item_id for c in allc] if full else []))
    res = _reserved(s, [c.id for c in allc]) if full else {}
    boms = {b.id: b for b in s.execute(select(MfgBomRow).where(MfgBomRow.id.in_(
        sorted({w.bom_id for w in wos if w.bom_id})))).scalars()} if full and any(w.bom_id for w in wos) else {}
    rtgs = {r.id: r for r in s.execute(select(MfgRoutingRow).where(MfgRoutingRow.id.in_(
        sorted({w.routing_id for w in wos if w.routing_id})))).scalars()} if full and any(w.routing_id for w in wos) \
        else {}
    dls: dict[str, Any] = {}
    if full and any(w.demand_line_id for w in wos):
        for dl, o in s.execute(select(MfgDemandLineRow, MfgDemandOrderRow).join(
                MfgDemandOrderRow, MfgDemandOrderRow.id == MfgDemandLineRow.order_id).where(
                MfgDemandLineRow.id.in_(sorted({w.demand_line_id for w in wos if w.demand_line_id})))).all():
            dls[dl.id] = {"id": dl.id, "order_id": o.id, "order_number": o.number, "line_no": dl.line_no}
    out = []
    for w in wos:
        base = {"id": w.id, "number": w.number, "status": w.status, "item_id": w.item_id,
                "item": iref(its.get(w.item_id), w.item_id), "qty": r6(w.qty), "qty_completed": r6(w.qty_completed),
                "qty_scrapped": r6(w.qty_scrapped), "open_qty": r6(WOR.open_qty(w.qty, w.qty_completed)),
                "due_date": w.due_date, "start_date": w.start_date, "priority": w.priority,
                "serial_from": w.serial_from, "serial_to": w.serial_to, "source": w.source,
                "source_run_no": w.source_run_no, "source_planned_no": w.source_planned_no,
                "row_version": w.row_version, "created_at": as_utc(w.created_at), "updated_at": as_utc(w.updated_at)}
        if not full:
            base["component_count"] = len(comps[w.id])
            out.append(base)
            continue
        b = boms.get(w.bom_id or "")
        r = rtgs.get(w.routing_id or "")
        base.update(demand_line_id=w.demand_line_id, demand_line=dls.get(w.demand_line_id or ""), note=w.note,
                    external_ref=w.external_ref,
                    bom={"id": b.id, "revision": b.revision, "version": b.version} if b else None,
                    routing={"id": r.id, "code": r.code, "version": r.version} if r else None,
                    released_at=as_utc(w.released_at), completed_at=as_utc(w.completed_at),
                    receipt_location_id=w.receipt_location_id,
                    released_to_floor_at=as_utc(w.released_to_floor_at), release_override=w.release_override,
                    closed_at=as_utc(w.closed_at), shortage_count=None,
                    components=[{"id": c.id, "item_id": c.item_id, "item": iref(its.get(c.item_id), c.item_id),
                                 "required_qty": r6(c.required_qty), "issued_qty": r6(c.issued_qty),
                                 "open_qty": r6(max(0.0, c.required_qty - c.issued_qty)),
                                 "reserved_qty": r6(res.get(c.id, 0.0)), "operation_seq": c.operation_seq,
                                 "find_number": c.find_number, "alt_group": c.alt_group,
                                 "bom_line_id": c.bom_line_id, "note": c.note} for c in comps[w.id]])
        out.append(base)
    return out


def _get(s: Session, wo_id: str, lock: bool = False) -> MfgWorkOrderRow:
    return repo.get_row(s, MfgWorkOrderRow, wo_id, what=WHAT, lock=lock)


def get_wo(ctx: AppContext, wo_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        w = _get(s, wo_id)
        rec = wo_records(s, [w])[0]
        if w.status in WOR.SUPPLY_STATUSES:
            rec["shortage_count"] = kitting_in(s, w)["totals"]["short_components"]
        return rec


def list_wos(ctx: AppContext, *, status: list[str] | None, item_id: str | None, q: str | None,
             start_from: date | None, start_to: date | None, source: str | None, sort: str, limit: int,
             offset: int) -> dict[str, Any]:
    W = MfgWorkOrderRow
    conds: list[Any] = []
    if status:
        conds.append(W.status.in_(status))
    if item_id:
        conds.append(W.item_id == item_id)
    if source:
        conds.append(W.source == source)
    if start_from:
        conds.append(W.start_date >= start_from)
    if start_to:
        conds.append(W.start_date <= start_to)
    if q:
        conds.append(ilike(W.number, q) | W.item_id.in_(select(MfgItemRow.id).where(ilike(MfgItemRow.part_number, q))))
    order = {"start_date": (W.start_date, W.number), "due_date": (W.due_date, W.number), "number": (W.number,),
             "priority": (W.priority, W.start_date, W.number)}[sort]
    with read_tx(ctx) as s:
        rows = list(s.execute(select(W).where(*conds).order_by(*order, W.id).limit(limit).offset(offset)).scalars())
        total = int(s.execute(select(func.count()).select_from(W).where(*conds)).scalar() or 0)
        return page(wo_records(s, rows, full=False), total, limit, offset)


# ---------------------------------------------------------------- create / update


def calendar(ds: Any) -> WorkCalendar:
    return WorkCalendar(ds.plant.mrp_workdays, WOR.plant_holidays(ds))


def _check_item(s: Session, item_id: str) -> MfgItemRow:
    it = items(s, [item_id]).get(item_id)
    if it is None:
        raise unknown_ref(["body", "item_id"], item_id, "Item")
    if it.make_buy != "make":
        raise ApiError(422, "MFG_ITEM_NOT_MAKE", f"{it.part_number} is not a make item.", {"loc": ["body", "item_id"]})
    return it


def _check_serial(it: MfgItemRow, inp: WorkOrderInput) -> None:
    if inp.serial_from is None:
        return
    if not it.serialized:
        raise ApiError(422, "MFG_SERIAL_NOT_ALLOWED", f"{it.part_number} is not serialized.",
                       {"loc": ["body", "serial_from"]})
    if inp.serial_to - inp.serial_from + 1 != round(inp.qty):
        raise ApiError(422, "DEM_SERIAL_QTY_MISMATCH", "The serial range must hold exactly the WO quantity.",
                       {"loc": ["body", "serial_to"]})


def _check_components(s: Session, comps: list[Any]) -> dict[str, MfgItemRow]:
    its = items(s, [c.item_id for c in comps])
    for i, c in enumerate(comps):
        it = its.get(c.item_id)
        if it is None:
            raise unknown_ref(["body", "components", i, "item_id"], c.item_id, "Item")
        if it.make_buy == "phantom":
            raise ApiError(422, "VALIDATION_ERROR", f"{it.part_number} is a phantom; list its components instead.",
                           {"errors": [{"loc": ["body", "components", i, "item_id"], "msg": "phantom item",
                                        "type": "value_error"}]})
        if is_count(it.uom) and abs(c.required_qty - round(c.required_qty)) > EPS:
            raise ApiError(422, "INV_FRACTIONAL_QTY", f"{it.part_number} is counted in {it.uom}; use whole numbers.",
                           {"loc": ["body", "components", i, "required_qty"]})
    return its


def _generated(ds: Any, item_id: str, qty: float, on: date, serial: int | None) -> Any:
    return WOR.generate_components(ds, item_id, qty, on=on, serial=serial)


def _receipt_loc(s: Session, inp: WorkOrderInput) -> str | None:
    lid = getattr(inp, "receipt_location_id", None)
    if lid is not None and s.get(MfgLocationRow, lid) is None:
        raise unknown_ref(["body", "receipt_location_id"], lid, "Location")
    return lid


def new_wo(s: Session, ds: Any, inp: WorkOrderInput, *, source: str = "manual", status: str = "planned",
           run_no: int | None = None, planned_no: int | None = None, bom_id: str | None = None,
           routing_id: str | None = None, generated: Any = None) -> tuple[MfgWorkOrderRow, list[dict[str, Any]]]:
    """Insert one WO with its components in the caller's transaction (also used by MRP conversion)."""
    it = _check_item(s, inp.item_id)
    _check_serial(it, inp)
    if is_count(it.uom) and abs(inp.qty - round(inp.qty)) > EPS:
        raise ApiError(422, "INV_FRACTIONAL_QTY", f"{it.part_number} is counted in {it.uom}; use a whole number.",
                       {"loc": ["body", "qty"]})
    if inp.external_ref is not None:
        ensure_unique(s, MfgWorkOrderRow, "A work order", {"external_ref": inp.external_ref})
    if inp.demand_line_id is not None:
        _check_demand_line(s, inp.demand_line_id)
    d = today(s)
    start = inp.start_date or WOR.default_start_date(ds, it.id, inp.qty, inp.due_date, calendar(ds),
                                                      on=max(inp.due_date, d), serial=inp.serial_from)
    warnings: list[dict[str, Any]] = []
    expl = generated
    if expl is None:
        expl = _generated(ds, it.id, inp.qty, max(start, d), inp.serial_from)
    comps: list[dict[str, Any]] = []
    if inp.components is not None:
        _check_components(s, inp.components)
        comps = [{"item_id": c.item_id, "required_qty": c.required_qty, "operation_seq": c.operation_seq,
                  "find_number": c.find_number, "alt_group": None, "bom_line_id": None, "note": c.note}
                 for c in inp.components]
    else:
        if expl.bom_id is None:
            warnings.append({"code": "WO_NO_EFFECTIVE_BOM",
                             "message": f"{it.part_number} has no effective BOM; the work order has no components."})
        comps = [{"item_id": c.item_id, "required_qty": c.qty, "operation_seq": c.operation_seq,
                  "find_number": c.find_number, "alt_group": c.alt_group, "bom_line_id": c.bom_line_id, "note": ""}
                 for c in expl.components]
    if inp.number is not None:
        ensure_unique(s, MfgWorkOrderRow, "A work order", {"number": inp.number})
    number = inp.number or repo_m2.next_number(s, "WO", repo_m2.number_taken(s, MfgWorkOrderRow))
    now = utcnow()
    w = MfgWorkOrderRow(id=new_id("wko_"), number=number, item_id=it.id, qty=inp.qty, qty_completed=0.0,
                        qty_scrapped=0.0, start_date=start, due_date=inp.due_date, status=status,
                        priority=inp.priority, serial_from=inp.serial_from, serial_to=inp.serial_to,
                        bom_id=bom_id or expl.bom_id, routing_id=routing_id or expl.routing_id,
                        demand_line_id=inp.demand_line_id, source=source, source_run_no=run_no,
                        source_planned_no=planned_no, released_at=now if status == "released" else None,
                        completed_at=None, closed_at=None, note=inp.note, external_ref=inp.external_ref,
                        receipt_location_id=_receipt_loc(s, inp), row_version=1, created_at=now, updated_at=now)
    if start > inp.due_date:
        raise ApiError(422, "VALIDATION_ERROR", "start_date must not be after due_date.",
                       {"errors": [{"loc": ["body", "start_date"], "msg": "after due_date", "type": "value_error"}]})
    s.add(w)
    s.flush()
    s.add_all([MfgWoComponentRow(id=new_id("woc_"), wo_id=w.id, issued_qty=0.0, row_version=1, created_at=now,
                                 updated_at=now, **c) for c in comps])
    s.flush()
    return w, warnings


def create_wo(ctx: AppContext, inp: WorkOrderInput) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        ds = repo.load_dataset(s)
        w, warnings = new_wo(s, ds, inp)
        audit(s, "work_order", w.id, "create", {"number": w.number})
        rec = wo_records(s, [w])[0]
        rec["warnings"] = warnings
        return rec

    return run_tx(ctx, fn)


def _check_demand_line(s: Session, demand_line_id: str) -> None:
    """Owned lookup (central ownership filter): another workspace's line is unknown here."""
    if s.execute(select(MfgDemandLineRow.id).where(MfgDemandLineRow.id == demand_line_id)).first() is None:
        raise unknown_ref(["body", "demand_line_id"], demand_line_id, "Demand line")


def _check_component_items(s: Session, comps: list[Any], old: dict[str, Any]) -> None:
    """A component's item cannot change once it has issues, transactions or reservations (they belong to the old
    item's stock)."""
    for i, ci in enumerate(comps):
        c = old.get(ci.id) if ci.id else None
        if c is None or ci.item_id == c.item_id:
            continue
        used = c.issued_qty > EPS or s.execute(select(MfgInvTransactionRow.id).where(
            MfgInvTransactionRow.wo_component_id == c.id).limit(1)).first() is not None or s.execute(
            select(MfgInvReservationRow.id).where(MfgInvReservationRow.wo_component_id == c.id).limit(1)
            ).first() is not None
        if used:
            raise ApiError(422, "WO_COMPONENT_IN_USE", "The item of a component with issues, transactions or "
                           "reservations cannot change; unreserve it, or add a new component instead.",
                           {"loc": ["body", "components", i, "item_id"], "component_id": c.id})


def _has_txn(s: Session, wo_id: str) -> bool:
    return s.execute(select(MfgInvTransactionRow.id).where(MfgInvTransactionRow.wo_id == wo_id).limit(1)).first() \
        is not None


def update_wo(ctx: AppContext, wo_id: str, inp: WorkOrderInput, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        w = _get(s, wo_id, lock=True)
        check_version(w, if_match)
        old = {c.id: c for c in repo_m2.lock_children_of(s, MfgWoComponentRow, "wo_id", [w.id])}
        comps_chk = []
        if inp.components is not None:
            for i, c in enumerate(inp.components):
                if c.id is not None:
                    if c.id not in old:
                        raise unknown_ref(["body", "components", i, "id"], c.id, "Component")
                    comps_chk.append((i, c.required_qty, old[c.id].issued_qty))
        try:
            WOR.check_put(w.status, qty=inp.qty, qty_completed=w.qty_completed, item_changed=inp.item_id != w.item_id,
                          components=comps_chk)
        except RuleError as e:
            raise rule_error(e) from None
        it = _check_item(s, inp.item_id)
        _check_serial(it, inp)
        if inp.demand_line_id is not None and inp.demand_line_id != w.demand_line_id:
            _check_demand_line(s, inp.demand_line_id)
        if inp.components is not None:
            _check_component_items(s, inp.components, old)
        if inp.number is not None and inp.number != w.number:
            ensure_unique(s, MfgWorkOrderRow, "A work order", {"number": inp.number}, exclude_id=w.id)
            w.number = inp.number
        if inp.external_ref is not None:
            ensure_unique(s, MfgWorkOrderRow, "A work order", {"external_ref": inp.external_ref}, exclude_id=w.id)
        w.qty, w.due_date, w.priority, w.note, w.external_ref = inp.qty, inp.due_date, inp.priority, inp.note, \
            inp.external_ref
        w.receipt_location_id = _receipt_loc(s, inp)
        if inp.start_date is not None:
            w.start_date = inp.start_date
        if w.start_date > w.due_date:
            raise ApiError(422, "VALIDATION_ERROR", "start_date must not be after due_date.",
                           {"errors": [{"loc": ["body", "start_date"], "msg": "after due_date",
                                        "type": "value_error"}]})
        if w.status == "planned":
            w.serial_from, w.serial_to, w.demand_line_id = inp.serial_from, inp.serial_to, inp.demand_line_id
        now = utcnow()
        if inp.components is not None:
            _check_components(s, inp.components)
            keep = {c.id for c in inp.components if c.id}
            gone = [c for c in old.values() if c.id not in keep]
            for c in gone:
                if c.issued_qty > EPS:
                    raise ApiError(422, "WO_COMPONENT_BELOW_ISSUED", "A component with issues cannot be removed.",
                                   {"component_id": c.id})
            if gone:
                release_reservations(s, [c.id for c in gone], now)
                if s.execute(select(MfgInvTransactionRow.id).where(MfgInvTransactionRow.wo_component_id.in_(
                        [c.id for c in gone])).limit(1)).first() is not None:
                    raise ApiError(409, "WO_HAS_TRANSACTIONS", "A component with transactions cannot be removed.",
                                   {})
                s.execute(delete(MfgWoComponentRow).where(MfgWoComponentRow.id.in_([c.id for c in gone]))
                          .execution_options(synchronize_session=False))
                for c in gone:
                    s.expunge(c)
            for ci in inp.components:
                if ci.id is not None:
                    c = old[ci.id]
                    c.item_id, c.required_qty, c.operation_seq, c.find_number, c.note = (
                        ci.item_id, ci.required_qty, ci.operation_seq, ci.find_number, ci.note)
                    touch(c, now)
                else:
                    s.add(MfgWoComponentRow(id=new_id("woc_"), wo_id=w.id, item_id=ci.item_id,
                                            required_qty=ci.required_qty, issued_qty=0.0,
                                            operation_seq=ci.operation_seq, find_number=ci.find_number,
                                            alt_group=None, bom_line_id=None, note=ci.note, row_version=1,
                                            created_at=now, updated_at=now))
            s.flush()
            _trim_reservations(s, w.id, now)
        touch(w, now)
        s.flush()
        audit(s, "work_order", w.id, "update", {"number": w.number, "version": w.row_version})
        return wo_records(s, [w])[0]

    return run_tx(ctx, fn)


def _trim_reservations(s: Session, wo_id: str, now: Any) -> None:
    """A reservation never exceeds its component's open qty (4.4): excess is released. Balances are locked first,
    then the reservations re-read `FOR UPDATE` (M3: no stale qty against a concurrent posting)."""
    comps = {c.id: c for c in s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id == wo_id)).scalars()}
    if not comps:
        return
    bals, res = repo_m2.lock_reservations_of(s, comps)
    res.sort(key=lambda r: (-as_utc(r.created_at).timestamp(), r.id))
    by_comp: dict[str, list[MfgInvReservationRow]] = {}
    for r in res:
        by_comp.setdefault(r.wo_component_id, []).append(r)
    for cid, rs in by_comp.items():
        c = comps[cid]
        excess = sum(r.qty for r in rs) - max(0.0, c.required_qty - c.issued_qty)
        for r in rs:
            if excess <= EPS:
                break
            take = min(r.qty, excess)
            b = bals[r.balance_id]
            b.qty_reserved = round(max(0.0, b.qty_reserved - take), 6)
            b.updated_at = now
            excess -= take
            if r.qty - take <= EPS:
                s.delete(r)
            else:
                r.qty = round(r.qty - take, 6)
                r.updated_at = now
    s.flush()


def delete_wo(ctx: AppContext, wo_id: str, if_match: str | None) -> None:
    def fn(s: Session) -> None:
        w = _get(s, wo_id, lock=True)
        check_version(w, if_match)
        try:
            WOR.check_deletable(w.status, _has_txn(s, w.id))
        except RuleError as e:
            raise rule_error(e) from None
        comps = [c.id for c in s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id == w.id)).scalars()]
        release_reservations(s, comps, utcnow())
        audit(s, "work_order", w.id, "delete", {"number": w.number})
        s.delete(w)
        s.flush()

    run_tx(ctx, fn)


def action(ctx: AppContext, wo_id: str, act: str, if_match: str | None, *, reserve: bool = False,
           override_reason: str | None = None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        w = _get(s, wo_id, lock=True)
        check_version(w, if_match)
        now = datetime.now(UTC)
        try:
            target = WOR.check_action(w.status, act)
            if act in ("cancel", "refresh-components") and _has_txn(s, w.id):
                WOR.check_no_transactions(True, act)
        except RuleError as e:
            raise rule_error(e) from None
        comps = repo_m2.lock_children_of(s, MfgWoComponentRow, "wo_id", [w.id])
        reserved: list[dict[str, Any]] | None = None
        extra: dict[str, Any] = {}
        if act == "release":
            w.status, w.released_at = "released", now
            if reserve:
                reserved = reserve_in(s, w, comps, None)
            from .floor import release_to_floor          # M4-DESIGN 4.1

            release_to_floor(s, w, override_reason, now)
            if w.release_override:
                extra["override_reason"] = w.release_override
        elif act in ("complete", "cancel"):
            extra["released_qty"] = r6(release_reservations(s, [c.id for c in comps], now))
            w.status = target
            if act == "complete":
                w.completed_at = now
        elif act == "close":
            w.status, w.closed_at = "closed", now
        elif act == "refresh-components":
            if any(c.issued_qty > EPS for c in comps):
                raise ApiError(409, "WO_HAS_TRANSACTIONS", "Components were issued; return them first.", {})
            ds = repo.load_dataset(s)
            expl = _generated(ds, w.item_id, w.qty, max(w.start_date, today(s)), w.serial_from)
            release_reservations(s, [c.id for c in comps], now)
            s.execute(delete(MfgWoComponentRow).where(MfgWoComponentRow.wo_id == w.id)
                      .execution_options(synchronize_session=False))
            for c in comps:
                s.expunge(c)
            s.add_all([MfgWoComponentRow(id=new_id("woc_"), wo_id=w.id, item_id=c.item_id, required_qty=c.qty,
                                         issued_qty=0.0, operation_seq=c.operation_seq, find_number=c.find_number,
                                         alt_group=c.alt_group, bom_line_id=c.bom_line_id, note="", row_version=1,
                                         created_at=now, updated_at=now) for c in expl.components])
            w.bom_id, w.routing_id = expl.bom_id, expl.routing_id
            extra["components"] = len(expl.components)
        touch(w, now)
        s.flush()
        audit(s, "work_order", w.id, act, {"number": w.number, "status": w.status, **extra,
                                           **({"reserved": len(reserved)} if reserved is not None else {})})
        rec = wo_records(s, [w])[0]
        if act == "release":
            rec["reserved"] = reserved or []
        return rec

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- reservations (7.3)


def _usable_balances(s: Session, item_ids: list[str], *, lock: bool) -> list[WOR.StockBal]:
    if not item_ids:
        return []
    q = select(MfgInvBalanceRow, MfgLocationRow).join(MfgLocationRow, MfgLocationRow.id == MfgInvBalanceRow.location_id) \
        .where(MfgInvBalanceRow.item_id.in_(sorted(set(item_ids))), MfgInvBalanceRow.qty_on_hand > EPS,
               MfgLocationRow.kind.in_(NETTABLE_NOW_KINDS)) \
        .order_by(MfgInvBalanceRow.item_id, MfgInvBalanceRow.location_id, MfgInvBalanceRow.lot_key)
    if lock:
        q = q.with_for_update(of=MfgInvBalanceRow).execution_options(populate_existing=True)
    rows = s.execute(q).all()
    lot_ids = sorted({b.lot_id for b, _l in rows if b.lot_id})
    lots = {x.id: x for x in s.execute(select(MfgLotRow).where(MfgLotRow.id.in_(lot_ids))).scalars()} if lot_ids \
        else {}
    out = []
    for b, loc in rows:
        lot = lots.get(b.lot_id or "")
        out.append(WOR.StockBal(b.id, b.item_id, b.location_id, loc.code, loc.kind, b.lot_id,
                                lot.lot_code if lot else None, lot.expires_on if lot else None,
                                lot.hold if lot else False, b.qty_on_hand, b.qty_reserved, loc.active))
    return out


def reserve_in(s: Session, w: MfgWorkOrderRow, comps: list[MfgWoComponentRow], component_ids: list[str] | None
               ) -> list[dict[str, Any]]:
    sel = [c for c in comps if component_ids is None or c.id in component_ids]
    have = _reserved(s, [c.id for c in sel])
    bals = _usable_balances(s, [c.item_id for c in sel], lock=True)
    plan, summary = WOR.plan_reservations(
        [WOR.ResComp(c.id, c.item_id, max(0.0, c.required_qty - c.issued_qty), have.get(c.id, 0.0)) for c in sel],
        bals, today(s))
    if plan:
        now = utcnow()
        brow = {b.id: b for b in s.execute(select(MfgInvBalanceRow).where(
            MfgInvBalanceRow.id.in_(sorted({p[1] for p in plan}))).execution_options(populate_existing=True))
            .scalars()}
        existing = {(r.wo_component_id, r.balance_id): r for r in s.execute(select(MfgInvReservationRow).where(
            MfgInvReservationRow.wo_component_id.in_([c.id for c in sel])).with_for_update()).scalars()}
        for cid, bid, q in plan:
            b = brow[bid]
            b.qty_reserved = round(b.qty_reserved + q, 6)
            b.updated_at = now
            r = existing.get((cid, bid))
            if r is not None:
                r.qty = round(r.qty + q, 6)
                r.updated_at = now
            else:
                s.add(MfgInvReservationRow(id=new_id("rsv_"), wo_component_id=cid, balance_id=bid, qty=q,
                                           created_at=now, updated_at=now))
        s.flush()
    return summary


def reserve(ctx: AppContext, wo_id: str, component_ids: list[str] | None, if_match: str | None,
            *, release: bool = False) -> dict[str, Any]:
    act = "unreserve" if release else "reserve"

    def fn(s: Session) -> dict[str, Any]:
        w = _get(s, wo_id, lock=True)
        check_version(w, if_match)
        try:
            WOR.check_action(w.status, act)
        except RuleError as e:
            raise rule_error(e) from None
        comps = repo_m2.lock_children_of(s, MfgWoComponentRow, "wo_id", [w.id])
        if component_ids is not None:
            ids = {c.id for c in comps}
            for i, cid in enumerate(component_ids):
                if cid not in ids:
                    raise unknown_ref(["body", "component_ids", i], cid, "Component")
        if release:
            sel = [c.id for c in comps if component_ids is None or c.id in component_ids]
            qty = release_reservations(s, sel, utcnow())
            summary = None
        else:
            summary = reserve_in(s, w, comps, component_ids)
            qty = sum(x["qty"] for x in summary)
        touch(w)
        s.flush()
        audit(s, "work_order", w.id, act, {"number": w.number, "qty": r6(qty)})
        rec = wo_records(s, [w])[0]
        if summary is not None:
            rec["reserved"] = summary
        return rec

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- kitting (7.4)


def next_supplies(s: Session, item_ids: list[str], d: date) -> dict[str, dict[str, Any]]:
    """Earliest open PO/PR schedule or WO per item: `{type, label, date, qty, link}`."""
    ids = sorted(set(item_ids))
    if not ids:
        return {}
    out: dict[str, dict[str, Any]] = {}
    its = items(s, ids)

    def put(item_id: str, cand: dict[str, Any]) -> None:
        cur = out.get(item_id)
        if cur is None or (cand["date"], cand["label"]) < (cur["date"], cur["label"]):
            out[item_id] = cand

    for sc, ln, doc in s.execute(select(MfgPurchaseScheduleRow, MfgPurchaseLineRow, MfgPurchaseDocRow)
                                 .join(MfgPurchaseLineRow, MfgPurchaseLineRow.id == MfgPurchaseScheduleRow.line_id)
                                 .join(MfgPurchaseDocRow, MfgPurchaseDocRow.id == MfgPurchaseLineRow.doc_id)
                                 .where(MfgPurchaseLineRow.item_id.in_(ids), MfgPurchaseScheduleRow.closed.is_(False),
                                        MfgPurchaseLineRow.status == "open")).all():
        oq = PUR.schedule_open_qty(sc.qty, sc.received_qty, sc.closed)
        if not PUR.is_supply(doc.doc_type, doc.status, ln.status, oq, sc.closed):
            continue
        it = its.get(ln.item_id)
        dt = PUR.available_date(PUR.dock_date(sc.requested_date, sc.confirmed_date), it.receiving_days if it else 0)
        put(ln.item_id, {"type": f"{doc.doc_type}_schedule", "label": f"{doc.number} / {ln.line_no} / {sc.seq}",
                         "date": dt, "qty": r6(oq),
                         "link": f"/mfg/purchasing/{'orders' if doc.doc_type == 'po' else 'requests'}/{doc.id}"
                                 f"?schedule={sc.id}"})
    for w in s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.item_id.in_(ids),
                                                     MfgWorkOrderRow.status.in_(WOR.SUPPLY_STATUSES))).scalars():
        oq = WOR.open_qty(w.qty, w.qty_completed)
        if oq > EPS:
            put(w.item_id, {"type": "work_order", "label": w.number, "date": w.due_date, "qty": r6(oq),
                            "link": f"/mfg/work-orders/{w.id}"})
    del d
    return out


def _kit_wo(w: MfgWorkOrderRow, comps: list[MfgWoComponentRow], res: dict[str, float]) -> WOR.KitWo:
    return WOR.KitWo(w.id, w.number, w.status, w.priority, w.start_date,
                     [WOR.KitComponent(c.id, c.item_id, c.required_qty, c.issued_qty, res.get(c.id, 0.0))
                      for c in comps])


def kitting_in(s: Session, w: MfgWorkOrderRow) -> dict[str, Any]:
    comps = _components(s, [w.id])[w.id]
    res = _reserved(s, [c.id for c in comps])
    d = today(s)
    bals = _usable_balances(s, [c.item_id for c in comps], lock=False)
    short_items = [c.item_id for c in comps]
    out = WOR.kitting(_kit_wo(w, comps, res), bals, d, next_supplies(s, short_items, d))
    its = items(s, [c.item_id for c in comps])
    for row in out["rows"]:
        row["item"] = iref(its.get(row["item_id"]), row["item_id"])
    return out


def kitting(ctx: AppContext, wo_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        w = _get(s, wo_id)
        out = kitting_in(s, w)
        out["wo"] = {"id": w.id, "number": w.number, "status": w.status, "start_date": w.start_date}
        return out


def kitting_check_in(s: Session, wo_ids: list[str] | None, order: str, horizon_days: int,
                     statuses: tuple[str, ...] = ("released", "planned")) -> dict[str, Any]:
    from ....mfg import limits as L

    d = today(s)
    if wo_ids is not None:
        wos = list(s.execute(select(MfgWorkOrderRow).where(MfgWorkOrderRow.id.in_(wo_ids))).scalars())
        found = {w.id for w in wos}
        for i, wid in enumerate(wo_ids):
            if wid not in found:
                raise unknown_ref(["body", "wo_ids", i], wid, "Work order")
    else:
        wos = list(s.execute(select(MfgWorkOrderRow).where(
            MfgWorkOrderRow.status.in_(statuses),
            (MfgWorkOrderRow.status != "planned") | (MfgWorkOrderRow.start_date <= d + timedelta(days=horizon_days))
        ).order_by(MfgWorkOrderRow.number).limit(L.KITTING_CHECK_MAX_WOS)).scalars())
    comps = _components(s, [w.id for w in wos])
    allc = [c for v in comps.values() for c in v]
    res = _reserved(s, [c.id for c in allc])
    bals = _usable_balances(s, [c.item_id for c in allc], lock=False)
    sup = next_supplies(s, [c.item_id for c in allc], d)
    out = WOR.simulate_kitting([_kit_wo(w, comps[w.id], res) for w in wos], bals, sup, order, d)
    its = items(s, [c.item_id for c in allc])
    for row in out["rows"]:
        row["wo"] = {"id": row.pop("wo_id"), "number": row.pop("number")}
        row["link"] = f"/mfg/work-orders/{row['wo']['id']}"
        for x in row["shortages"]:
            x["item"] = iref(its.get(x["item_id"]), x["item_id"])
    for x in out["items_short"]:
        x["item"] = iref(its.get(x["item_id"]), x["item_id"])
    return out


def kitting_check(ctx: AppContext, wo_ids: list[str] | None, order: str, horizon_days: int) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return kitting_check_in(s, wo_ids, order, horizon_days)
