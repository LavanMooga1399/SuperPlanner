"""Unit serials (M4-DESIGN 10, 11 #214-215): captured units with their WO and one-level as-built links."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...context import AppContext
from ...schemas import as_utc
from .. import repo
from ..db_models import MfgItemRow
from ..db_models_m2 import MfgWorkOrderRow
from ..db_models_m4 import MfgUnitSerialRow
from .common import ilike, read_tx
from .m2util import page


def serial_records(s: Session, rows: list[MfgUnitSerialRow]) -> list[dict[str, Any]]:
    if not rows:
        return []
    its = {i.id: i for i in s.execute(select(MfgItemRow).where(MfgItemRow.id.in_({r.item_id for r in rows})))
           .scalars()}
    wids = {r.wo_id for r in rows if r.wo_id}
    wos = {w.id: w.number for w in s.execute(select(MfgWorkOrderRow.id, MfgWorkOrderRow.number).where(
        MfgWorkOrderRow.id.in_(wids))).all()} if wids else {}
    out = []
    for r in rows:
        it = its.get(r.item_id)
        out.append({"id": r.id, "row_version": r.row_version, "created_at": as_utc(r.created_at),
                    "updated_at": as_utc(r.updated_at),
                    "item": {"id": r.item_id, "part_number": it.part_number if it else "",
                             "description": it.description if it else ""},
                    "serial": r.serial, "wo": {"id": r.wo_id, "number": wos.get(r.wo_id, "")} if r.wo_id else None,
                    "status": r.status, "captured_at": as_utc(r.captured_at), "captured_op_seq": r.captured_op_seq,
                    "parent_serial_id": r.parent_serial_id, "consumed_at": as_utc(r.consumed_at),
                    "consumed_wo_id": r.consumed_wo_id})
    return out


def list_serials(ctx: AppContext, *, item_id: str | None, q: str | None, status: str | None, wo_id: str | None,
                 limit: int, offset: int) -> dict[str, Any]:
    conds: list[Any] = []
    if item_id:
        conds.append(MfgUnitSerialRow.item_id == item_id)
    if status:
        conds.append(MfgUnitSerialRow.status == status)
    if wo_id:
        conds.append(or_(MfgUnitSerialRow.wo_id == wo_id, MfgUnitSerialRow.consumed_wo_id == wo_id))
    if q:
        conds.append(ilike(MfgUnitSerialRow.serial, q))
    with read_tx(ctx) as s:
        total = int(s.execute(select(func.count()).select_from(MfgUnitSerialRow).where(*conds)).scalar() or 0)
        rows = list(s.execute(select(MfgUnitSerialRow).where(*conds).order_by(
            MfgUnitSerialRow.item_id, MfgUnitSerialRow.serial, MfgUnitSerialRow.id).limit(limit).offset(offset))
            .scalars())
        return page(serial_records(s, rows), total, limit, offset)


def get_serial(ctx: AppContext, serial_id: str) -> dict[str, Any]:
    with read_tx(ctx) as s:
        u = repo.get_row(s, MfgUnitSerialRow, serial_id, what="Serial")
        rec = serial_records(s, [u])[0]
        parent = s.get(MfgUnitSerialRow, u.parent_serial_id) if u.parent_serial_id else None
        kids = list(s.execute(select(MfgUnitSerialRow).where(MfgUnitSerialRow.parent_serial_id == u.id)
                              .order_by(MfgUnitSerialRow.item_id, MfgUnitSerialRow.serial)).scalars())
        cw = s.get(MfgWorkOrderRow, u.consumed_wo_id) if u.consumed_wo_id else None
        rec.update(parent=serial_records(s, [parent])[0] if parent is not None else None,
                   children=serial_records(s, kids),
                   consumed_by_wo={"id": cw.id, "number": cw.number} if cw is not None else None)
        return rec
