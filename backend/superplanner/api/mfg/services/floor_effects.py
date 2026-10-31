"""Automatic effects of floor events (M4-DESIGN 4.3, 4.4, 10), applied in the event's transaction after the
operation rows (lock order WO header -> operations -> postings):

- scrap of every operation -> `work_orders.qty_scrapped` (cumulative per operation in `effects.scrap`, so
  corrections adjust it; no stock movement - 16.WP-S: the last operation's scrap is booked the same way instead of as
  the receipt line's `scrap_qty`);
- backflush (4.4): per component of the operation whose item has `issue_method = backflush`, the cumulative target
  `(good + scrap) x per-unit requirement` is issued (`wo_issue`, FEFO lots, `over_issue`) from the line location ->
  plant backflush location; a posting that fails (insufficient stock, no location) is not posted, the remainder is
  pending (`effects.backflush[component].pending`, warning `FLR_BACKFLUSH_PENDING`, retried by #205);
- the last operation's good output -> `wo_receipt` to `wo.receipt_location_id` -> `plant.wo_receipt_location_id`
  (422 `FLR_NO_RECEIPT_LOCATION`); lot-controlled output is received into the lot named after the WO number. A
  correction below the received quantity reverses the operation's receipts and re-posts the new total; `reopen`
  reverses them (WO back to in progress) until the next report/complete;
- unit serials (10): produced serials at the capturing operation (`wip`, `in_stock` at the receipt), consumed child
  serials at the consuming operation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....mfg.floor import engine as E
from ....mfg.model_m2 import EPS, WoIssueLine, WoIssuePosting, WoReceiptLine, WoReceiptPosting
from ....mfg.units import is_count
from ...db import new_id
from ...errors import ApiError
from ..db_models import MfgItemRow, MfgLineRow, MfgOperationRow, MfgPlantRow
from ..db_models_m2 import MfgInvPostingRow, MfgWoComponentRow, MfgWorkOrderRow
from ..db_models_m4 import MfgFloorEventRow, MfgUnitSerialRow, MfgWoOperationRow


def _eff(row: MfgWoOperationRow) -> dict[str, Any]:
    return dict(row.effects or {})


def pending_of(row: MfgWoOperationRow) -> bool:
    return any(float(v.get("pending") or 0) > EPS for v in ((row.effects or {}).get("backflush") or {}).values())


def _plant(s: Session) -> MfgPlantRow | None:
    return s.execute(select(MfgPlantRow)).scalars().first()


def _txn_date(s: Session, at: datetime) -> Any:
    from ....mfg.tz import plant_tz

    p = _plant(s)
    from datetime import UTC

    return at.astimezone(plant_tz(p) if p is not None else UTC).date()


def _posting_ref(s: Session, row: MfgInvPostingRow) -> dict[str, Any]:
    from ..db_models_m2 import MfgInvTransactionRow

    lines = [{"item_id": t.item_id, "location_id": t.location_id, "qty": t.qty, "lot_id": t.lot_id}
             for t in s.execute(select(MfgInvTransactionRow).where(MfgInvTransactionRow.posting_id == row.id)
                                .order_by(MfgInvTransactionRow.seq)).scalars()]
    return {"id": row.id, "number": row.number, "type": row.type, "reversal_of_id": row.reversal_of_id,
            "lines": lines}


def apply_effects(c: Any, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow], before: dict[str, E.OpState],
                  after: dict[str, E.OpState], op: MfgWoOperationRow, ev: MfgFloorEventRow, inp: Any,
                  item: MfgItemRow | None, at: datetime) -> None:
    s = c.s
    last = rows[-1]
    if ev.event_type not in E.QTY_EVENTS and ev.event_type not in ("correct", "reopen", "skip"):
        return                       # transitions without quantities have no automatic effects (FP1)
    _scrap(s, wo, rows)
    if ev.event_type in E.QTY_EVENTS or ev.event_type == "correct":
        _serials(c, wo, rows, op, ev, inp, item, before, after, at)
    _backflush(c, wo, rows, op, at)
    if ev.event_type == "reopen" and op.id == last.id:
        _reverse_receipts(c, wo, last, at, hold=True)
    elif op.id == last.id and ev.event_type in E.QTY_EVENTS:
        eff = _eff(last)
        if eff.get("hold"):
            eff.pop("hold")
            last.effects = eff
    _receipt(c, wo, last, item, at, rows)


# ---------------------------------------------------------------- scrap

def _scrap(s: Session, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow]) -> None:
    delta = 0.0
    for r in rows:
        eff = _eff(r)
        booked = float(eff.get("scrap") or 0.0)
        if abs(r.qty_scrap - booked) > EPS:
            delta += r.qty_scrap - booked
            eff["scrap"] = round(r.qty_scrap, 6)
            r.effects = eff
    if abs(delta) > EPS:
        from .common import touch

        wo.qty_scrapped = round(max(0.0, wo.qty_scrapped + delta), 6)
        touch(wo)


# ---------------------------------------------------------------- backflush (4.4)

def _components_of(s: Session, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow], op: MfgWoOperationRow
                   ) -> list[tuple[MfgWoComponentRow, MfgItemRow]]:
    seqs = {r.seq for r in rows}
    first = rows[0].seq
    out = []
    for cpt, it in s.execute(select(MfgWoComponentRow, MfgItemRow).join(
            MfgItemRow, MfgItemRow.id == MfgWoComponentRow.item_id).where(
            MfgWoComponentRow.wo_id == wo.id, MfgItemRow.issue_method == "backflush")
            .order_by(MfgWoComponentRow.id)).all():
        seq = cpt.operation_seq if cpt.operation_seq in seqs else first
        if seq == op.seq:
            out.append((cpt, it))
    return out


def _bf_location(s: Session, op: MfgWoOperationRow) -> str | None:
    if op.line_id:
        ln = s.get(MfgLineRow, op.line_id)
        if ln is not None and ln.location_id:
            return ln.location_id
    p = _plant(s)
    return p.backflush_location_id if p is not None else None


def _backflush(c: Any, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow], op: MfgWoOperationRow,
               at: datetime) -> list[dict[str, Any]]:
    s = c.s
    comps = _components_of(s, wo, rows, op)
    if not comps:
        return []
    eff = _eff(op)
    bf = dict(eff.get("backflush") or {})
    units = op.qty_good + op.qty_scrap
    results = []
    loc = _bf_location(s, op)
    for cpt, it in comps:
        st = dict(bf.get(cpt.id) or {"posted": 0.0, "pending": 0.0})
        target = E.backflush_target(units, _per_wo_required(cpt, wo), wo.qty, is_count(it.uom))
        delta = round(target - float(st.get("posted") or 0.0), 6)
        st["pending"] = 0.0
        if delta > EPS:
            ok, info = _issue(s, wo, cpt, it, loc, delta, at)
            if ok:
                st["posted"] = round(float(st.get("posted") or 0.0) + delta, 6)
                st.setdefault("postings", []).append(info["id"])
                c.postings.append(info)
                results.append({"component_id": cpt.id, "item_id": it.id, "part_number": it.part_number,
                                "qty": delta, "status": "posted", "posting_id": info["id"],
                                "wo_operation_id": op.id})
            else:
                st["pending"] = delta
                st["reason"] = info.get("message", "")
                results.append({"component_id": cpt.id, "item_id": it.id, "part_number": it.part_number,
                                "qty": delta, "status": "pending", "posting_id": None, "wo_operation_id": op.id,
                                "available": info.get("available"), "location_id": loc,
                                "message": info.get("message", "")})
        bf[cpt.id] = st
    eff["backflush"] = bf
    op.effects = eff
    pend = [r for r in results if r["status"] == "pending"]
    if pend:
        text = "; ".join(f"{r['part_number']}: {r['qty']:g}" for r in pend)
        c.warnings.append({"code": "FLR_BACKFLUSH_PENDING",
                           "message": f"{len(pend)} backflush issue(s) could not be posted ({text}).",
                           "details": {"pending": [{k: r.get(k) for k in ("component_id", "item_id", "qty",
                                                                          "available", "location_id", "message")}
                                                   for r in pend]}})
        if hasattr(c, "notify_backflush"):
            c.notify_backflush(pend)
    return results


def _per_wo_required(cpt: MfgWoComponentRow, wo: MfgWorkOrderRow) -> float:
    """The component's requirement for the whole WO quantity (its `required_qty`, M2 7.2)."""
    return float(cpt.required_qty)


def _issue(s: Session, wo: MfgWorkOrderRow, cpt: MfgWoComponentRow, it: MfgItemRow, loc: str | None, qty: float,
           at: datetime) -> tuple[bool, dict[str, Any]]:
    from .inventory import post_in_session

    if loc is None:
        return False, {"message": "no backflush location (line or plant)", "available": 0.0}
    if wo.status not in ("released", "in_progress", "completed"):
        return False, {"message": f"{wo.number} is {wo.status}", "available": None}
    # a pending backflush of a WO that completed meanwhile is still consumed material (4.4): post it as if the WO
    # were in progress (M2 issue rule), the WO stays completed with its completion time
    was = (wo.status, wo.completed_at) if wo.status == "completed" else None
    if was is not None:
        wo.status = "in_progress"
    inp = WoIssuePosting.model_construct(
        type="wo_issue", txn_date=None, note=f"Backflush {wo.number}", reason_code="BACKFLUSH",
        lines=[WoIssueLine.model_construct(wo_component_id=cpt.id, location_id=loc, qty=qty, over_issue=True,
                                           lot_code=None)])
    try:
        with s.begin_nested():
            row, _w = post_in_session(s, inp, system=True, txn_date=_txn_date(s, at), note_audit=False)
    except ApiError as e:
        if was is not None:
            wo.status, wo.completed_at = was
        return False, {"message": e.message, "available": (e.details or {}).get("available")}
    if was is not None:
        wo.status, wo.completed_at = was
        s.flush()
    return True, _posting_ref(s, row)


def retry_wo(s: Session, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow]) -> list[dict[str, Any]]:
    from ...db import utcnow

    class _C:
        def __init__(self) -> None:
            self.s, self.postings, self.warnings = s, [], []

    c = _C()
    out = []
    now = utcnow()
    for r in rows:
        if pending_of(r):
            for x in _backflush(c, wo, rows, r, now):
                x["wo"] = {"id": wo.id, "number": wo.number}
                out.append(x)
    s.flush()
    return out


# ---------------------------------------------------------------- receipt (4.3)

def _receipt_location(s: Session, wo: MfgWorkOrderRow) -> str | None:
    if wo.receipt_location_id:
        return wo.receipt_location_id
    p = _plant(s)
    return p.wo_receipt_location_id if p is not None else None


def _reverse_receipts(c: Any, wo: MfgWorkOrderRow, last: MfgWoOperationRow, at: datetime, *, hold: bool) -> None:
    from .inventory import reverse_in_session

    s = c.s
    eff = _eff(last)
    for pid in list(eff.get("receipts") or []):
        done = s.execute(select(MfgInvPostingRow.id).where(MfgInvPostingRow.reversal_of_id == pid)).first()
        if done is None:
            rev = reverse_in_session(s, pid, f"Reopen of {wo.number} op {last.seq}", txn_date=_txn_date(s, at))
            c.postings.append(_posting_ref(s, rev))
    eff["receipts"] = []
    eff["received"] = 0.0
    if hold:
        eff["hold"] = True
    last.effects = eff
    s.flush()
    s.refresh(wo)


def _receipt(c: Any, wo: MfgWorkOrderRow, last: MfgWoOperationRow, item: MfgItemRow | None, at: datetime,
             rows: list[MfgWoOperationRow] | None = None) -> None:
    from .inventory import post_in_session

    s = c.s
    eff = _eff(last)
    if eff.get("hold"):
        return
    received = float(eff.get("received") or 0.0)
    target = round(last.qty_good, 6)
    if last.status == "skipped" and rows:      # review M4: a skipped last operation passes its input on
        from .floor import _chain

        target = round(_chain(rows)[last.seq].qty_input, 6)
    if target < received - EPS:
        _reverse_receipts(c, wo, last, at, hold=False)
        eff = _eff(last)
        received = 0.0
    delta = round(target - received, 6)
    if delta <= EPS:
        return
    loc = _receipt_location(s, wo)
    if loc is None:
        raise ApiError(422, "FLR_NO_RECEIPT_LOCATION", f"{wo.number} has no receipt location and the plant has no WO "
                       "receipt location; set one first.", {"wo_id": wo.id})
    lot = wo.number if item is not None and item.lot_controlled else None
    inp = WoReceiptPosting.model_construct(
        type="wo_receipt", txn_date=None, note=f"Floor receipt {wo.number} op {last.seq}", reason_code=None,
        lines=[WoReceiptLine.model_construct(wo_id=wo.id, location_id=loc, qty=delta, scrap_qty=0.0, lot_code=lot,
                                             expires_on=None)])
    row, _w = post_in_session(s, inp, system=True, txn_date=_txn_date(s, at), note_audit=False)
    eff["receipts"] = list(eff.get("receipts") or []) + [row.id]
    eff["received"] = round(received + delta, 6)
    last.effects = eff
    c.postings.append(_posting_ref(s, row))
    s.flush()
    s.refresh(wo)
    # serials of this WO become in stock with the receipt (10)
    for u in s.execute(select(MfgUnitSerialRow).where(MfgUnitSerialRow.wo_id == wo.id,
                                                      MfgUnitSerialRow.item_id == wo.item_id,
                                                      MfgUnitSerialRow.status == "wip")).scalars():
        u.status = "in_stock"


# ---------------------------------------------------------------- serials (10)

def captures_serials(s: Session, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow], op: MfgWoOperationRow,
                     item: MfgItemRow | None) -> bool:
    """A serialized item's serials are captured at the operation flagged `capture_serial`, else at the last one."""
    if item is None or not item.serialized or not rows:
        return False
    from .floor import routing_of

    rid = routing_of(s, wo)
    flagged = set(s.execute(select(MfgOperationRow.seq).where(MfgOperationRow.routing_id == rid,
                                                              MfgOperationRow.capture_serial.is_(True))).scalars()) \
        if rid else set()
    if flagged & {r.seq for r in rows}:
        return op.seq in flagged
    return op.id == rows[-1].id


def _serials(c: Any, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow], op: MfgWoOperationRow,
             ev: MfgFloorEventRow, inp: Any, item: MfgItemRow | None, before: dict[str, E.OpState],
             after: dict[str, E.OpState], at: datetime) -> None:
    s = c.s
    ser = inp.serials
    produced = [x.strip() for x in (ser.produced if ser is not None else [])]
    consumed = list(ser.consumed if ser is not None else [])
    good_delta = round(after[op.id].qty_good - before[op.id].qty_good, 6)
    capture = captures_serials(s, wo, rows, op, item)
    if capture and ev.event_type in E.QTY_EVENTS:
        if len(produced) != int(round(max(0.0, good_delta))) or len(set(p.upper() for p in produced)) != len(produced):
            raise ApiError(422, "FLR_SERIALS_REQUIRED", f"{wo.number} op {op.seq} captures serials: give exactly "
                           f"{max(0, int(round(good_delta)))} distinct serial(s) ({len(produced)} given).",
                           {"loc": ["body", "serials", "produced"], "required": max(0, int(round(good_delta))),
                            "given": len(produced)})
        if produced:
            dup = s.execute(select(MfgUnitSerialRow.serial).where(
                MfgUnitSerialRow.item_id == wo.item_id,
                func.upper(MfgUnitSerialRow.serial).in_([p.upper() for p in produced])).limit(1)).scalar()
            if dup is not None:
                raise ApiError(409, "FLR_SERIAL_DUPLICATE", f"Serial {dup} of {item.part_number} exists already.",
                               {"serial": dup, "item_id": wo.item_id})
            if wo.serial_from is not None and wo.serial_to is not None:
                out = [p for p in produced if not (p.isdigit() and wo.serial_from <= int(p) <= wo.serial_to)]
                if out:
                    c.warnings.append({"code": "FLR_SERIAL_OUT_OF_RANGE",
                                       "message": f"{len(out)} serial(s) are outside {wo.number}'s unit range "
                                                  f"{wo.serial_from}-{wo.serial_to}.", "details": {"serials": out}})
            for p in produced:
                s.add(MfgUnitSerialRow(id=new_id("ser_"), item_id=wo.item_id, serial=p, wo_id=wo.id, status="wip",
                                       captured_at=at, captured_op_seq=op.seq, parent_serial_id=None,
                                       consumed_at=None, consumed_wo_id=None, event_id=ev.id, row_version=1,
                                       created_at=c.now, updated_at=c.now))
            s.flush()
    elif produced:
        raise ApiError(422, "VALIDATION_ERROR", "This operation does not capture serials.",
                       {"errors": [{"loc": ["body", "serials", "produced"], "msg": "no serial capture here",
                                    "type": "value_error"}]})
    if consumed:
        _consume(c, wo, rows, op, ev, consumed, produced, at)


def _consume(c: Any, wo: MfgWorkOrderRow, rows: list[MfgWoOperationRow], op: MfgWoOperationRow,
             ev: MfgFloorEventRow, consumed: list[Any], produced: list[str], at: datetime) -> None:
    s = c.s
    seqs = {r.seq for r in rows}
    allowed = {cpt.item_id for cpt in s.execute(select(MfgWoComponentRow).where(MfgWoComponentRow.wo_id == wo.id))
               .scalars() if (cpt.operation_seq if cpt.operation_seq in seqs else rows[0].seq) == op.seq}
    parent = None
    if produced:
        parent = s.execute(select(MfgUnitSerialRow).where(MfgUnitSerialRow.item_id == wo.item_id,
                                                          MfgUnitSerialRow.serial == produced[0])).scalars().first()
    for i, x in enumerate(consumed):
        if x.item_id not in allowed:
            raise ApiError(422, "FLR_SERIAL_NOT_AVAILABLE", "That item is not a component of this operation.",
                           {"loc": ["body", "serials", "consumed", i], "item_id": x.item_id})
        u = s.execute(select(MfgUnitSerialRow).where(MfgUnitSerialRow.item_id == x.item_id,
                                                     func.upper(MfgUnitSerialRow.serial) == x.serial.upper())
                      .with_for_update()).scalars().first()
        if u is None or u.status not in ("in_stock", "wip"):
            raise ApiError(422, "FLR_SERIAL_NOT_AVAILABLE", f"Serial {x.serial} is not available"
                           + (f" ({u.status})." if u is not None else "."),
                           {"loc": ["body", "serials", "consumed", i], "serial": x.serial,
                            "status": u.status if u is not None else None})
        u.status, u.consumed_at, u.consumed_wo_id = "consumed", at, wo.id
        u.parent_serial_id = parent.id if parent is not None else None
        u.row_version += 1
        u.updated_at = c.now
    s.flush()


__all__ = ["apply_effects", "captures_serials", "pending_of", "retry_wo"]
