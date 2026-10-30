"""Helpers for tests/mfg_m2_db: write a pure dataset including its transactional state (`ds.txn`) as ORM rows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mfgdb_helpers import write_dataset
from superplanner.api.db.models import new_id
from superplanner.api.mfg import db_models_m2 as m2
from superplanner.mfg.dataset import MfgDataset


def write_all(s: Any, ds: MfgDataset) -> dict[str, str]:
    """Master (`write_dataset`) + transactional rows; returns old id -> new id."""
    ids = write_dataset(s, ds)

    def nid(old: str) -> str:
        if old not in ids:
            ids[old] = new_id(old[:4])
        return ids[old]

    def opt(old: str | None) -> str | None:
        return nid(old) if old else None

    t = ds.txn
    if t is None:
        return ids
    now = datetime.now(UTC)
    st = {"row_version": 1, "created_at": now, "updated_at": now}
    for x in t.lots.values():
        s.add(m2.MfgLotRow(id=nid(x.id), item_id=nid(x.item_id), lot_code=x.lot_code, expires_on=x.expires_on,
                           received_on=x.received_on, supplier_lot=x.supplier_lot, hold=x.hold, note=x.note, **st))
    s.flush()
    for b in t.balances.values():
        s.add(m2.MfgInvBalanceRow(id=nid(b.id), item_id=nid(b.item_id), location_id=nid(b.location_id),
                                  lot_id=opt(b.lot_id), lot_key=b.lot_key, qty_on_hand=b.qty_on_hand,
                                  qty_reserved=b.qty_reserved, last_receipt_on=b.last_receipt_on, updated_at=now))
    for d in t.purchase_docs.values():
        s.add(m2.MfgPurchaseDocRow(id=nid(d.id), doc_type=d.doc_type, number=d.number, status=d.status,
                                   supplier_id=opt(d.supplier_id), currency=d.currency, order_date=d.order_date,
                                   note=d.note, source=d.source, source_run_no=d.source_run_no, submitted_at=None,
                                   submitted_by=None, approved_at=None, approved_by=None, rejected_reason="",
                                   external_ref=d.external_ref, idempotency_key=None, **st))
    for o in t.demand_orders.values():
        s.add(m2.MfgDemandOrderRow(id=nid(o.id), number=o.number, demand_type=o.demand_type, customer=o.customer,
                                   program=o.program, priority=o.priority, status=o.status, note=o.note,
                                   external_ref=o.external_ref, **st))
    s.flush()
    for d in t.purchase_docs.values():
        for ln in d.lines:
            s.add(m2.MfgPurchaseLineRow(id=nid(ln.id), doc_id=nid(d.id), line_no=ln.line_no, item_id=nid(ln.item_id),
                                        unit_price=ln.unit_price, status=ln.status, source_pr_line_id=None,
                                        note=ln.note, **st))
    for o in t.demand_orders.values():
        for ln in o.lines:
            s.add(m2.MfgDemandLineRow(id=nid(ln.id), order_id=nid(o.id), line_no=ln.line_no, item_id=nid(ln.item_id),
                                      qty=ln.qty, due_date=ln.due_date, shipped_qty=ln.shipped_qty,
                                      serial_from=ln.serial_from, serial_to=ln.serial_to, priority=ln.priority,
                                      note=ln.note, **st))
    s.flush()
    for d in t.purchase_docs.values():
        for ln in d.lines:
            for sc in ln.schedules:
                s.add(m2.MfgPurchaseScheduleRow(id=nid(sc.id), line_id=nid(ln.id), seq=sc.seq,
                                                requested_date=sc.requested_date, confirmed_date=sc.confirmed_date,
                                                qty=sc.qty, received_qty=sc.received_qty, closed=sc.closed, **st))
    for w in t.work_orders.values():
        s.add(m2.MfgWorkOrderRow(id=nid(w.id), number=w.number, item_id=nid(w.item_id), qty=w.qty,
                                 qty_completed=w.qty_completed, qty_scrapped=w.qty_scrapped, start_date=w.start_date,
                                 due_date=w.due_date, status=w.status, priority=w.priority, serial_from=w.serial_from,
                                 serial_to=w.serial_to, bom_id=opt(w.bom_id), routing_id=opt(w.routing_id),
                                 demand_line_id=opt(w.demand_line_id), source=w.source, source_run_no=None,
                                 source_planned_no=None, released_at=None, completed_at=None, closed_at=None,
                                 note=w.note, external_ref=w.external_ref, **st))
    s.flush()
    for w in t.work_orders.values():
        for c in w.components:
            s.add(m2.MfgWoComponentRow(id=nid(c.id), wo_id=nid(w.id), item_id=nid(c.item_id),
                                       required_qty=c.required_qty, issued_qty=c.issued_qty,
                                       operation_seq=c.operation_seq, find_number=c.find_number,
                                       alt_group=c.alt_group, bom_line_id=c.bom_line_id, note=c.note, **st))
    s.flush()
    for r in t.reservations.values():
        s.add(m2.MfgInvReservationRow(id=nid(r.id), wo_component_id=nid(r.wo_component_id),
                                      balance_id=nid(r.balance_id), qty=r.qty, created_at=now, updated_at=now))
    s.flush()
    return ids
