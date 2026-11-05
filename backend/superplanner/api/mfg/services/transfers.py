"""Inter-plant transfer orders (M5-DESIGN 3.5).

One document in the source plant (`direction out`) mirrored in the destination (`direction in`, same number,
`mirror_of` = source order id; lines linked both ways by `mirror_line_id`). Both plants are written in one
transaction under `system_scope` with explicit owner stamps. Items of the destination are matched by
`external_ref`, else part number (422 `TRF_ITEM_UNMATCHED` per line). MRP: open source lines are demand (type
`transfer`), destination lines supply at their receive date (`repo_m2.load_mrp_snapshot`).

Movements are M2 postings: `transfer_ship` in the source (lots recorded as in transit on the mirror line) and
`transfer_receipt` in the destination (only what is in transit, lots carried over with expiry and supplier lot);
`before_post` / `after_post` are called by `inventory.post_in_session` in the posting's transaction.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....mfg import transfers as TR
from ...context import AppContext
from ...db import new_id, utcnow
from ...db.ownership import SYSTEM, current_owner, system_scope
from ...errors import ApiError, not_found
from ...schemas import as_utc
from .. import repo_m2
from ..db_models import MfgItemRow
from ..db_models_m2 import MfgLocationRow, MfgLotRow
from ..db_models_m5 import MfgTransferLineRow, MfgTransferOrderRow
from .common import audit, check_version, read_tx, touch
from .m2util import actor_id, page, run_tx

EPS = 1e-9


def _codes(s: Session, owners: list[str]) -> dict[str, str]:
    from .trace import _plant_codes

    with system_scope():
        return _plant_codes(s, owners)


def record(s: Session, o: MfgTransferOrderRow, lines: list[MfgTransferLineRow] | None = None) -> dict[str, Any]:
    if lines is None:
        with system_scope():
            lines = list(s.execute(select(MfgTransferLineRow).where(MfgTransferLineRow.order_id == o.id)
                                   .order_by(MfgTransferLineRow.line_no)).scalars())
    codes = _codes(s, [o.source_owner_id, o.dest_owner_id])
    return {"id": o.id, "number": o.number, "direction": o.direction, "status": o.status,
            "source_plant": {"owner_id": o.source_owner_id, "code": codes.get(o.source_owner_id, "")},
            "dest_plant": {"owner_id": o.dest_owner_id, "code": codes.get(o.dest_owner_id, "")},
            "mirror_of": o.mirror_of, "from_location_id": o.from_location_id, "to_location_id": o.to_location_id,
            "note": o.note, "row_version": o.row_version, "created_at": as_utc(o.created_at),
            "updated_at": as_utc(o.updated_at),
            "lines": [{"id": ln.id, "line_no": ln.line_no, "item_id": ln.item_id, "qty": ln.qty,
                       "shipped_qty": ln.shipped_qty, "received_qty": ln.received_qty,
                       "ship_date": ln.ship_date.isoformat(), "receive_date": ln.receive_date.isoformat(),
                       "mirror_line_id": ln.mirror_line_id, "in_transit": ln.in_transit or []} for ln in lines]}


def _can_use_plant(s: Session, owner: str, user: str) -> bool:
    from .trace import visible_owners

    with system_scope():
        return owner in visible_owners(s, user, user)


def _lines_of(s: Session, order_id: str) -> list[MfgTransferLineRow]:
    with system_scope():
        return list(s.execute(select(MfgTransferLineRow).where(MfgTransferLineRow.order_id == order_id)
                              .order_by(MfgTransferLineRow.line_no).with_for_update()).scalars())


def _mirror(s: Session, o: MfgTransferOrderRow) -> MfgTransferOrderRow | None:
    with system_scope():
        if o.direction == "out":
            return s.execute(select(MfgTransferOrderRow).where(MfgTransferOrderRow.mirror_of == o.id)
                             .with_for_update()).scalars().first()
        return s.get(MfgTransferOrderRow, o.mirror_of, with_for_update=True) if o.mirror_of else None


def _write_lines(s: Session, src: MfgTransferOrderRow, dst: MfgTransferOrderRow, inp: Any) -> None:
    """(Re)write both line sets from the input (draft only)."""
    with system_scope():
        old = _lines_of(s, src.id) + _lines_of(s, dst.id)
        for ln in old:
            s.delete(ln)
        s.flush()
        src_items = {r.id: r for r in s.execute(select(MfgItemRow).where(
            MfgItemRow.owner_id == src.owner_id, MfgItemRow.id.in_([x.item_id for x in inp.lines]))).scalars()}
        dest_items = list(s.execute(select(MfgItemRow).where(MfgItemRow.owner_id == dst.owner_id)).scalars())
        errors = []
        now = utcnow()
        for i, x in enumerate(inp.lines):
            it = src_items.get(x.item_id)
            if it is None:
                raise not_found("Item", x.item_id)
            d = TR.match_item(it, dest_items)
            if d is None:
                errors.append({"loc": ["body", "lines", i, "item_id"], "part_number": it.part_number})
                continue
            no = x.line_no or (i + 1)
            sl = MfgTransferLineRow(id=new_id("trl_"), owner_id=src.owner_id, order_id=src.id, line_no=no,
                                    item_id=it.id, qty=x.qty, shipped_qty=0.0, received_qty=0.0,
                                    ship_date=x.ship_date, receive_date=x.receive_date, mirror_line_id=None,
                                    in_transit=[], row_version=1, created_at=now, updated_at=now)
            dl = MfgTransferLineRow(id=new_id("trl_"), owner_id=dst.owner_id, order_id=dst.id, line_no=no,
                                    item_id=d.id, qty=x.qty, shipped_qty=0.0, received_qty=0.0,
                                    ship_date=x.ship_date, receive_date=x.receive_date, mirror_line_id=sl.id,
                                    in_transit=[], row_version=1, created_at=now, updated_at=now)
            sl.mirror_line_id = dl.id
            s.add_all([sl, dl])
        if errors:
            raise ApiError(422, "TRF_ITEM_UNMATCHED", f"{len(errors)} item(s) have no match in the destination "
                           f"plant (by external ref or part number): "
                           f"{', '.join(e['part_number'] for e in errors[:5])}.", {"lines": errors})
        s.flush()


def _dest_location(s: Session, owner: str, code: str | None) -> str | None:
    with system_scope():
        q = select(MfgLocationRow).where(MfgLocationRow.owner_id == owner, MfgLocationRow.active.is_(True))
        if code:
            r = s.execute(q.where(MfgLocationRow.code == code)).scalars().first()
            if r is None:
                raise ApiError(422, "VALIDATION_ERROR", f"Location {code} does not exist in the destination plant.",
                               {"errors": [{"loc": ["body", "to_location_code"], "msg": "unknown",
                                            "type": "value_error"}]})
            return r.id
        r = s.execute(q.where(MfgLocationRow.receipt_default.is_(True))).scalars().first()
        return r.id if r else None


def create(ctx: AppContext, inp: Any) -> dict[str, Any]:
    home = str(current_owner())
    user = actor_id()
    if inp.dest_plant_owner_id == home:
        raise ApiError(422, "VALIDATION_ERROR", "The destination must be another plant.",
                       {"errors": [{"loc": ["body", "dest_plant_owner_id"], "msg": "same plant",
                                    "type": "value_error"}]})

    def fn(s: Session) -> dict[str, Any]:
        if not _can_use_plant(s, inp.dest_plant_owner_id, user):
            raise ApiError(403, "TRF_PLANT_ACCESS", "You are not a member of the destination plant.",
                           {"owner_id": inp.dest_plant_owner_id})
        number = (inp.number or "").strip()
        with system_scope():
            if number:
                for o in (home, inp.dest_plant_owner_id):
                    if s.execute(select(MfgTransferOrderRow.id).where(MfgTransferOrderRow.owner_id == o,
                                                                      MfgTransferOrderRow.number == number)).first():
                        raise ApiError(409, "MFG_DUPLICATE", f"Transfer order {number} exists already.",
                                       {"number": number})
        if not number:
            def taken(c: str) -> bool:
                with system_scope():
                    return s.execute(select(MfgTransferOrderRow.id).where(
                        MfgTransferOrderRow.owner_id.in_([home, inp.dest_plant_owner_id]),
                        MfgTransferOrderRow.number == c)).first() is not None
            number = repo_m2.next_number(s, "TO", taken)
        now = utcnow()
        src = MfgTransferOrderRow(id=new_id("tro_"), owner_id=home, number=number, direction="out", status="draft",
                                  source_owner_id=home, dest_owner_id=inp.dest_plant_owner_id, mirror_of=None,
                                  from_location_id=inp.from_location_id, to_location_id=None, note=inp.note,
                                  row_version=1, created_at=now, updated_at=now)
        dst = MfgTransferOrderRow(id=new_id("tro_"), owner_id=inp.dest_plant_owner_id, number=number,
                                  direction="in", status="draft", source_owner_id=home,
                                  dest_owner_id=inp.dest_plant_owner_id, mirror_of=src.id,
                                  from_location_id=inp.from_location_id,
                                  to_location_id=_dest_location(s, inp.dest_plant_owner_id, inp.to_location_code),
                                  note=inp.note, row_version=1, created_at=now, updated_at=now)
        src.to_location_id = dst.to_location_id
        with system_scope():
            s.add_all([src, dst])
            s.flush()
        _write_lines(s, src, dst, inp)
        audit(s, "transfer_order", src.id, "create", {"number": number, "dest": inp.dest_plant_owner_id})
        return record(s, src)

    return run_tx(ctx, fn)


def _get(s: Session, to_id: str, lock: bool = False) -> MfgTransferOrderRow:
    q = select(MfgTransferOrderRow).where(MfgTransferOrderRow.id == to_id)
    if lock:
        q = q.with_for_update()
    r = s.execute(q).scalars().first()
    if r is None:
        raise not_found("Transfer order", to_id)
    return r


def get(ctx: AppContext, to_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        return record(s, _get(s, to_id))


def list_(ctx: AppContext, direction: str | None, status: str | None, limit: int, offset: int) -> dict[str, Any]:
    conds = []
    if direction:
        conds.append(MfgTransferOrderRow.direction == direction)
    if status:
        conds.append(MfgTransferOrderRow.status == status)
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgTransferOrderRow).where(*conds)).scalar() or 0)
        rows = list(s.execute(select(MfgTransferOrderRow).where(*conds).order_by(
            MfgTransferOrderRow.created_at.desc(), MfgTransferOrderRow.id).limit(limit).offset(offset)).scalars())
        return page([record(s, r) for r in rows], total, limit, offset)


def _source_for_edit(s: Session, to_id: str, if_match: str | None) -> tuple[MfgTransferOrderRow, Any]:
    o = _get(s, to_id, lock=True)
    check_version(o, if_match)
    if o.direction != "out":
        raise ApiError(409, "MFG_INVALID_STATE", "Edit the transfer order in its source plant.",
                       {"status": o.status, "action": "edit", "allowed_from": []})
    m = _mirror(s, o)
    return o, m


def update(ctx: AppContext, to_id: str, inp: Any, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        o, m = _source_for_edit(s, to_id, if_match)
        if o.status != "draft":
            raise ApiError(409, "MFG_INVALID_STATE", "Only draft transfer orders can be edited.",
                           {"status": o.status, "action": "edit", "allowed_from": ["draft"]})
        if inp.dest_plant_owner_id != o.dest_owner_id:
            raise ApiError(422, "VALIDATION_ERROR", "The destination plant cannot be changed.",
                           {"errors": [{"loc": ["body", "dest_plant_owner_id"], "msg": "immutable",
                                        "type": "immutable"}]})
        o.note, o.from_location_id = inp.note, inp.from_location_id
        with system_scope():
            m.note, m.from_location_id = inp.note, inp.from_location_id
            m.to_location_id = o.to_location_id = _dest_location(s, o.dest_owner_id, inp.to_location_code) \
                if inp.to_location_code else m.to_location_id
            touch(m)
        touch(o)
        _write_lines(s, o, m, inp)
        audit(s, "transfer_order", o.id, "update", {"lines": len(inp.lines)})
        return record(s, o)

    return run_tx(ctx, fn)


def delete(ctx: AppContext, to_id: str, if_match: str | None) -> None:
    def fn(s: Session) -> None:
        o, m = _source_for_edit(s, to_id, if_match)
        if o.status != "draft":
            raise ApiError(409, "MFG_INVALID_STATE", "Only draft transfer orders can be deleted (cancel it).",
                           {"status": o.status, "action": "delete", "allowed_from": ["draft"]})
        with system_scope():
            for ln in _lines_of(s, o.id) + (_lines_of(s, m.id) if m else []):
                s.delete(ln)
            s.flush()
            if m is not None:
                s.delete(m)
            s.delete(o)
        audit(s, "transfer_order", to_id, "delete", {"number": o.number})

    run_tx(ctx, fn)


def action(ctx: AppContext, to_id: str, name: str, if_match: str | None) -> dict[str, Any]:
    def fn(s: Session) -> dict[str, Any]:
        o = _get(s, to_id, lock=True)
        check_version(o, if_match)
        if name != "close" and o.direction != "out":
            raise ApiError(409, "MFG_INVALID_STATE", "Open or cancel the transfer order in its source plant.",
                           {"status": o.status, "action": name, "allowed_from": []})
        m = _mirror(s, o)
        shipped = sum(ln.shipped_qty for ln in _lines_of(s, o.id))
        if not TR.can(name, o.status, shipped):
            raise ApiError(409, "MFG_INVALID_STATE", f"A {o.status} transfer order cannot be {TR.TARGET[name]}.",
                           {"status": o.status, "action": name, "allowed_from": list(TR.ACTIONS[name])})
        if name == "open" and not _lines_of(s, o.id):
            raise ApiError(422, "VALIDATION_ERROR", "A transfer order needs at least one line.", {})
        o.status = TR.TARGET[name]
        touch(o)
        if m is not None:
            with system_scope():
                m.status = o.status
                touch(m)
        s.flush()
        audit(s, "transfer_order", o.id, name, {"number": o.number})
        return record(s, o)

    return run_tx(ctx, fn)


# ---------------------------------------------------------------- postings (called by inventory.post_in_session)

def before_post(s: Session, inp: Any) -> Any:
    """Check the lines against the transfer orders (locked) and fill carried-over lot data on receipts."""
    ids = sorted({ln.transfer_line_id for ln in inp.lines})
    with system_scope():
        rows = {r.id: r for r in s.execute(select(MfgTransferLineRow).where(MfgTransferLineRow.id.in_(ids))
                                           .with_for_update()).scalars()}
        orders = {o.id: o for o in s.execute(select(MfgTransferOrderRow).where(MfgTransferOrderRow.id.in_(
            sorted({r.order_id for r in rows.values()})))).scalars()}
    me = current_owner()
    ship = inp.type == "transfer_ship"
    want: dict[str, float] = {}
    new_lines = []
    for i, ln in enumerate(inp.lines):
        r = rows.get(ln.transfer_line_id)
        o = orders.get(r.order_id) if r else None
        if r is None or o is None or (me != SYSTEM and r.owner_id != me):
            raise not_found("Transfer line", ln.transfer_line_id)
        if o.direction != ("out" if ship else "in"):
            raise ApiError(409, "MFG_INVALID_STATE", "Ship in the source plant, receive in the destination plant.",
                           {"status": o.status, "action": inp.type, "allowed_from": []})
        if o.status not in ("open", "shipped"):
            raise ApiError(409, "MFG_INVALID_STATE", f"A {o.status} transfer order cannot be "
                           f"{'shipped' if ship else 'received'}.", {"status": o.status, "action": inp.type,
                                                                     "allowed_from": ["open", "shipped"]})
        if ln.item_id != r.item_id:
            raise ApiError(422, "VALIDATION_ERROR", "The item does not match the transfer line.",
                           {"errors": [{"loc": ["body", "lines", i, "item_id"], "msg": "must be the line's item",
                                        "type": "value_error"}]})
        want[r.id] = want.get(r.id, 0.0) + ln.qty
        left = (r.qty - r.shipped_qty) if ship else sum(float(x["qty"]) for x in r.in_transit or [])
        if want[r.id] > left + 1e-6:
            raise ApiError(409, "TRF_OVER_QUANTITY", f"Only {round(max(0.0, left), 6)} of line {r.line_no} "
                           f"{'remain to ship' if ship else 'are in transit'}.",
                           {"loc": ["body", "lines", i, "qty"], "line_no": r.line_no, "available": round(left, 6)})
        if not ship:
            if TR.take_in_transit(r.in_transit or [], ln.lot_code, ln.qty) is None:
                raise ApiError(409, "TRF_OVER_QUANTITY", f"Lot {ln.lot_code or '(none)'} is not in transit on line "
                               f"{r.line_no} in that quantity.", {"loc": ["body", "lines", i, "lot_code"]})
            src = next((x for x in r.in_transit or [] if (x.get("lot_code") or None) == (ln.lot_code or None)), {})
            if getattr(ln, "expires_on", None) is None and src.get("expires_on"):
                ln = ln.model_copy(update={"expires_on": date.fromisoformat(src["expires_on"])})
        new_lines.append(ln)
    return inp.model_copy(update={"lines": new_lines})


def after_post(s: Session, posting: Any, plan: Any) -> None:
    from ....integration import outbox
    from ..db_models_m2 import MfgInvTransactionRow

    ship = posting.type == "transfer_ship"
    txns = list(s.execute(select(MfgInvTransactionRow).where(MfgInvTransactionRow.posting_id == posting.id))
                .scalars())
    lots = {r.id: r for r in s.execute(select(MfgLotRow).where(MfgLotRow.id.in_(
        [t.lot_id for t in txns if t.lot_id]))).scalars()} if any(t.lot_id for t in txns) else {}
    touched: set[str] = set()
    with system_scope():
        for t in txns:
            r = s.get(MfgTransferLineRow, t.transfer_line_id, with_for_update=True)
            other = s.get(MfgTransferLineRow, r.mirror_line_id, with_for_update=True) if r.mirror_line_id else None
            q = abs(t.qty)
            lot = lots.get(t.lot_id) if t.lot_id else None
            if ship:
                r.shipped_qty = round(r.shipped_qty + q, 6)
                if other is not None:
                    other.shipped_qty = r.shipped_qty
                    it = list(other.in_transit or [])
                    it.append({"lot_code": lot.lot_code if lot else None, "qty": round(q, 6),
                               "expires_on": lot.expires_on.isoformat() if lot and lot.expires_on else None,
                               "supplier_lot": lot.supplier_lot if lot else "", "posting": posting.number})
                    other.in_transit = it
                    touch(other)
            else:
                code = lot.lot_code if lot else None
                src = next((x for x in r.in_transit or [] if (x.get("lot_code") or None) == code), {})
                r.received_qty = round(r.received_qty + q, 6)
                r.in_transit = TR.take_in_transit(r.in_transit or [], code, q) or []
                if other is not None:
                    other.received_qty = r.received_qty
                    touch(other)
                if lot is not None and not lot.supplier_lot:       # carried over from the source lot
                    sup = src.get("supplier_lot") or (_source_supplier_lot(s, other, lot.lot_code)
                                                      if other is not None else None)
                    if sup:
                        lot.supplier_lot = sup
            touch(r)
            touched.add(r.order_id)
            if other is not None:
                touched.add(other.order_id)
        s.flush()
        numbers = []
        for oid in sorted(touched):
            o = s.get(MfgTransferOrderRow, oid, with_for_update=True)
            lines = list(s.execute(select(MfgTransferLineRow).where(MfgTransferLineRow.order_id == oid)).scalars())
            o.status = TR.derive_status(o.status, [(x.qty, x.shipped_qty, x.received_qty) for x in lines])
            touch(o)
            numbers.append(o.number)
        s.flush()
    if outbox.enabled(s):
        outbox.emit(s, "transfer_order.shipped" if ship else "transfer_order.received",
                    {"number": numbers[0] if numbers else "", "posting": posting.number,
                     "lines": [{"transfer_line_id": t.transfer_line_id, "item_id": t.item_id, "qty": abs(t.qty),
                                "lot_code": lots[t.lot_id].lot_code if t.lot_id in lots else None} for t in txns]},
                    numbers[0] if numbers else None)


def _source_supplier_lot(s: Session, src_line: MfgTransferLineRow, lot_code: str) -> str | None:
    r = s.execute(select(MfgLotRow.supplier_lot).where(MfgLotRow.owner_id == src_line.owner_id,
                                                       MfgLotRow.item_id == src_line.item_id,
                                                       MfgLotRow.lot_code == lot_code)).scalar()
    return r or None


def mrp_rows(s: Session) -> tuple[list[Any], list[Any]]:
    """(demand snaps of open source lines, schedule snaps of open destination lines) of the bound plant."""
    from ....mfg.model_m2 import DemandSnap, ScheduleSnap

    dem, sup = [], []
    codes: dict[str, str] = {}
    rows = list(s.execute(select(MfgTransferOrderRow, MfgTransferLineRow).join(
        MfgTransferLineRow, MfgTransferLineRow.order_id == MfgTransferOrderRow.id).where(
        MfgTransferOrderRow.status.in_(("open", "shipped")))).all())
    if rows:
        codes = _codes(s, sorted({o.dest_owner_id for o, _l in rows}))
    for o, ln in sorted(rows, key=lambda x: (x[0].number, x[1].line_no)):
        if o.direction == "out":
            oq = round(ln.qty - ln.shipped_qty, 6)
            if oq > EPS:
                dem.append(DemandSnap(o.id, o.number, "transfer", codes.get(o.dest_owner_id, ""), None, ln.id,
                                      ln.line_no, ln.item_id, oq, ln.ship_date, 5, None, None))
        else:
            oq = round(ln.qty - ln.received_qty, 6)
            if oq > EPS:
                sup.append(ScheduleSnap("po", o.id, o.number, "open", ln.id, ln.line_no, ln.id, 1, ln.item_id, None,
                                        oq, ln.receive_date, None))
    return dem, sup
