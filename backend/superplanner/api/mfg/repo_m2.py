"""M2 repository (M2-DESIGN 9.5): loaders of the M2 master tables and the transactional state, the MRP snapshot,
the staleness token, lockers in the binding lock order (4.5) and the number series.

Every query is an ORM query (the ownership filter applies). Loaders run a fixed number of statements (one per table,
no lazy loads). Rows that may not exist yet (lots, balances, number series) are created with the M1 savepoint
pattern: `begin_nested`, insert, on a unique violation roll back the savepoint and select `FOR UPDATE` again.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...mfg.dataset import (MfgDataset, TxnBalance, TxnData, TxnDemandLine, TxnDemandOrder, TxnLot, TxnPurchaseDoc,
                            TxnPurchaseLine, TxnReservation, TxnSchedule, TxnWoComponent, TxnWorkOrder, mrp_inputs)
from ...mfg.limits import SQL_IN_CHUNK
from ...mfg.model_m2 import ItemSupplierRecord, LocationRecord, SupplierRecord
from ..db.locks import is_unique_violation
from ..db.models import new_id, utcnow
from ..schemas import as_utc
from .db_models_m2 import (MfgDemandLineRow, MfgDemandOrderRow, MfgInvBalanceRow, MfgInvReservationRow,
                           MfgInvTransactionRow, MfgItemSupplierRow, MfgLocationRow, MfgLotRow, MfgNumberSeriesRow,
                           MfgPurchaseDocRow, MfgPurchaseLineRow, MfgPurchaseScheduleRow, MfgSupplierRow,
                           MfgWoComponentRow, MfgWorkOrderRow)

SERIES_PREFIX = {"PO": "PO-", "PR": "PR-", "DO": "DO-", "WO": "WO-", "TXN": "TXN-"}
SERIES_WIDTH = 6


# ---------------------------------------------------------------- rows -> records


def _stamp(row: Any) -> dict[str, Any]:
    return {"id": row.id, "row_version": row.row_version, "created_at": as_utc(row.created_at),
            "updated_at": as_utc(row.updated_at)}


def location_record(row: MfgLocationRow) -> LocationRecord:
    return LocationRecord.model_construct(code=row.code, name=row.name, kind=row.kind,
                                          receipt_default=row.receipt_default, active=row.active,
                                          external_ref=row.external_ref, note=row.note, **_stamp(row))


def supplier_record(row: MfgSupplierRow, item_count: int = 0) -> SupplierRecord:
    return SupplierRecord.model_construct(
        code=row.code, name=row.name, lead_time_days=row.lead_time_days, currency=row.currency,
        contact_name=row.contact_name, email=row.email, phone=row.phone, address=row.address, active=row.active,
        external_ref=row.external_ref, note=row.note, item_count=item_count, **_stamp(row))


def item_supplier_record(row: MfgItemSupplierRow, item: Any = None, supplier: Any = None) -> ItemSupplierRecord:
    return ItemSupplierRecord.model_construct(
        item_id=row.item_id, supplier_id=row.supplier_id, supplier_part_number=row.supplier_part_number,
        lead_time_days=row.lead_time_days, min_order_qty=row.min_order_qty, order_multiple=row.order_multiple,
        purchase_unit=row.purchase_unit, units_per_purchase_unit=row.units_per_purchase_unit,
        unit_price=row.unit_price, currency=row.currency, preferred=row.preferred, active=row.active,
        note=row.note, item=item, supplier=supplier, **_stamp(row))


# ---------------------------------------------------------------- loaders


def load_master_m2(s: Session, ds: MfgDataset) -> None:
    """Locations, suppliers, item-suppliers into `ds` (3 statements; `dataset.link` fills refs/counts)."""
    for r in s.execute(select(MfgLocationRow)).scalars():
        ds.locations[r.id] = location_record(r)
    for r in s.execute(select(MfgSupplierRow)).scalars():
        ds.suppliers[r.id] = supplier_record(r)
    for r in s.execute(select(MfgItemSupplierRow)).scalars():
        ds.item_suppliers[r.id] = item_supplier_record(r)


def load_dataset(s: Session) -> MfgDataset:
    from . import repo

    return repo.load_dataset(s)


_PO_SUPPLY = ("draft", "open", "partially_received")
_PR_SUPPLY = ("draft", "submitted", "approved")


def load_txn(s: Session, *, open_only: bool = False) -> TxnData:
    """The transactional state (10 statements). `open_only` (MRP): balances with stock, supply documents (5.5),
    `open` demand orders and WOs `planned`/`released`/`in_progress` only."""
    t = TxnData()
    for r in s.execute(select(MfgLotRow)).scalars():
        t.lots[r.id] = TxnLot(r.id, r.item_id, r.lot_code, r.expires_on, r.received_on, r.supplier_lot, r.hold,
                              r.note)
    q = select(MfgInvBalanceRow)
    if open_only:
        q = q.where(MfgInvBalanceRow.qty_on_hand > 1e-6)
    for r in s.execute(q).scalars():
        t.balances[r.id] = TxnBalance(r.id, r.item_id, r.location_id, r.lot_id, r.lot_key, r.qty_on_hand,
                                      r.qty_reserved, r.last_receipt_on)
    for r in s.execute(select(MfgInvReservationRow)).scalars():
        t.reservations[r.id] = TxnReservation(r.id, r.wo_component_id, r.balance_id, r.qty)
    q = select(MfgPurchaseDocRow)
    if open_only:
        q = q.where(((MfgPurchaseDocRow.doc_type == "po") & MfgPurchaseDocRow.status.in_(_PO_SUPPLY))
                    | ((MfgPurchaseDocRow.doc_type == "pr") & MfgPurchaseDocRow.status.in_(_PR_SUPPLY)))
    for r in s.execute(q).scalars():
        t.purchase_docs[r.id] = TxnPurchaseDoc(r.id, r.doc_type, r.number, r.status, r.supplier_id, r.currency,
                                               r.order_date, r.note, r.source, r.source_run_no, r.external_ref)
    lines: dict[str, TxnPurchaseLine] = {}
    q = select(MfgPurchaseLineRow)
    if open_only:
        q = q.where(MfgPurchaseLineRow.status == "open")
    for r in s.execute(q).scalars():
        d = t.purchase_docs.get(r.doc_id)
        if d is None:
            continue
        ln = TxnPurchaseLine(r.id, r.line_no, r.item_id, r.unit_price, r.status, r.note, r.source_pr_line_id)
        d.lines.append(ln)
        lines[r.id] = ln
    q = select(MfgPurchaseScheduleRow)
    if open_only:
        q = q.where(MfgPurchaseScheduleRow.closed.is_(False))
    for r in s.execute(q).scalars():
        ln = lines.get(r.line_id)
        if ln is not None:
            ln.schedules.append(TxnSchedule(r.id, r.seq, r.requested_date, r.confirmed_date, r.qty, r.received_qty,
                                            r.closed))
    q = select(MfgDemandOrderRow)
    if open_only:
        q = q.where(MfgDemandOrderRow.status == "open")
    for r in s.execute(q).scalars():
        t.demand_orders[r.id] = TxnDemandOrder(r.id, r.number, r.demand_type, r.status, r.customer, r.program,
                                               r.priority, r.note, r.external_ref)
    for r in s.execute(select(MfgDemandLineRow)).scalars():
        o = t.demand_orders.get(r.order_id)
        if o is not None:
            o.lines.append(TxnDemandLine(r.id, r.line_no, r.item_id, r.qty, r.due_date, r.shipped_qty, r.serial_from,
                                         r.serial_to, r.priority, r.note))
    q = select(MfgWorkOrderRow)
    if open_only:
        q = q.where(MfgWorkOrderRow.status.in_(("planned", "released", "in_progress")))
    for r in s.execute(q).scalars():
        t.work_orders[r.id] = TxnWorkOrder(r.id, r.number, r.item_id, r.qty, r.start_date, r.due_date, r.status,
                                           r.qty_completed, r.qty_scrapped, r.priority, r.serial_from, r.serial_to,
                                           r.bom_id, r.routing_id, r.demand_line_id, r.source, r.note, r.external_ref)
    for r in s.execute(select(MfgWoComponentRow)).scalars():
        w = t.work_orders.get(r.wo_id)
        if w is not None:
            w.components.append(TxnWoComponent(r.id, r.item_id, r.required_qty, r.issued_qty, r.operation_seq,
                                               r.find_number, r.alt_group, r.bom_line_id, r.note))
    return t


def load_import_dataset(s: Session) -> MfgDataset:
    """Master data + the complete transactional state (imports, `scope=transactions|all` exports)."""
    ds = load_dataset(s)
    ds.txn = load_txn(s)
    return ds


def load_mrp_snapshot(s: Session, as_of: date) -> Any:
    """`MrpSnapshot` (8.2): the caller opened a REPEATABLE READ read-only transaction (`snapshot_tx`). 20 + 10
    statements, no N+1."""
    from ...mfg.mrp.model import MrpSnapshot

    ds = load_dataset(s)
    ds.txn = load_txn(s, open_only=True)
    return MrpSnapshot(as_of=as_of, dataset=ds, **mrp_inputs(ds, as_of))


def inputs_token(s: Session) -> dict[str, Any]:
    """Staleness token (8.14): max transaction seq, max `updated_at` of purchase docs / demand orders / work
    orders, plant `data_version` (one statement)."""
    from .db_models import MfgPlantRow

    row = s.execute(select(
        select(func.max(MfgInvTransactionRow.seq)).scalar_subquery(),
        select(func.max(MfgPurchaseDocRow.updated_at)).scalar_subquery(),
        select(func.max(MfgDemandOrderRow.updated_at)).scalar_subquery(),
        select(func.max(MfgWorkOrderRow.updated_at)).scalar_subquery(),
        select(func.max(MfgPlantRow.data_version)).scalar_subquery())).one()

    def ts(v: Any) -> str | None:
        return as_utc(v).isoformat() if v is not None else None

    return {"seq": int(row[0] or 0), "purchase_docs": ts(row[1]), "demand_orders": ts(row[2]),
            "work_orders": ts(row[3]), "data_version": int(row[4] or 0)}


@contextmanager
def snapshot_tx(db: Any) -> Iterator[Session]:
    """A read session whose first statement sets REPEATABLE READ READ ONLY (one consistent MRP snapshot)."""
    with db.read() as s:
        s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        yield s


# ---------------------------------------------------------------- lockers (4.5)


def _chunks(ids: list[Any]) -> Iterator[list[Any]]:
    for i in range(0, len(ids), SQL_IN_CHUNK):
        yield ids[i:i + SQL_IN_CHUNK]


def lock_docs(s: Session, model: Any, ids: Iterable[str]) -> list[Any]:
    """Document headers sorted by id, `FOR NO KEY UPDATE` (lock order step 3)."""
    out: list[Any] = []
    for chunk in _chunks(sorted(set(ids))):
        out += list(s.execute(select(model).where(model.id.in_(chunk)).order_by(model.id)
                              .with_for_update(key_share=True).execution_options(populate_existing=True)).scalars())
    return out


def lock_children(s: Session, model: Any, ids: Iterable[str]) -> list[Any]:
    """Document children sorted by id, `FOR UPDATE` (step 4)."""
    out: list[Any] = []
    for chunk in _chunks(sorted(set(ids))):
        out += list(s.execute(select(model).where(model.id.in_(chunk)).order_by(model.id).with_for_update()
                              .execution_options(populate_existing=True)).scalars())
    return out


def lock_children_of(s: Session, model: Any, fk: str, parent_ids: Iterable[str]) -> list[Any]:
    out: list[Any] = []
    col = getattr(model, fk)
    for chunk in _chunks(sorted(set(parent_ids))):
        out += list(s.execute(select(model).where(col.in_(chunk)).order_by(model.id).with_for_update()
                              .execution_options(populate_existing=True)).scalars())
    return out


def lock_lots(s: Session, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], MfgLotRow]:
    ks = sorted(set(keys))
    out: dict[tuple[str, str], MfgLotRow] = {}
    items = sorted({k[0] for k in ks})
    for chunk in _chunks(items):
        for r in s.execute(select(MfgLotRow).where(MfgLotRow.item_id.in_(chunk))
                           .order_by(MfgLotRow.item_id, MfgLotRow.lot_code).with_for_update()
                           .execution_options(populate_existing=True)).scalars():
            if (r.item_id, r.lot_code) in set(ks):
                out[(r.item_id, r.lot_code)] = r
    return out


def lock_or_create_lots(s: Session, specs: dict[tuple[str, str], dict[str, Any]]) -> dict[tuple[str, str], MfgLotRow]:
    """Lots by `(item_id, lot_code)` (step 6), created with `specs[key]` values when missing (savepoint
    pattern)."""
    found = lock_lots(s, specs)
    now = utcnow()
    for key in sorted(specs):
        if key in found:
            continue
        v = specs[key]
        try:
            with s.begin_nested():
                row = MfgLotRow(id=new_id("lot_"), item_id=key[0], lot_code=key[1], expires_on=v.get("expires_on"),
                                received_on=v.get("received_on"), supplier_lot=v.get("supplier_lot") or "",
                                hold=False, note="", row_version=1, created_at=now, updated_at=now)
                s.add(row)
                s.flush()
            found[key] = row
        except IntegrityError as exc:
            if not is_unique_violation(exc, "uq_mfg_lots_key"):
                raise
            found.update(lock_lots(s, [key]))
    return found


def lock_balances(s: Session, keys: Iterable[tuple[str, str, str]]) -> dict[tuple[str, str, str], MfgInvBalanceRow]:
    """Existing balances of the given keys, locked `FOR UPDATE` in key order (step 7)."""
    ks = set(keys)
    out: dict[tuple[str, str, str], MfgInvBalanceRow] = {}
    pairs = sorted({(k[0], k[1]) for k in ks})
    items = sorted({p[0] for p in pairs})
    for chunk in _chunks(items):
        q = select(MfgInvBalanceRow).where(MfgInvBalanceRow.item_id.in_(chunk)) \
            .order_by(MfgInvBalanceRow.item_id, MfgInvBalanceRow.location_id, MfgInvBalanceRow.lot_key) \
            .with_for_update().execution_options(populate_existing=True)
        for r in s.execute(q).scalars():
            if (r.item_id, r.location_id, r.lot_key) in ks:
                out[(r.item_id, r.location_id, r.lot_key)] = r
    return out


def lock_balances_at(s: Session, pairs: Iterable[tuple[str, str]]) -> dict[tuple[str, str, str], MfgInvBalanceRow]:
    """Every balance (all lots) of the given (item, location) pairs, locked in key order (FEFO picking)."""
    ps = set(pairs)
    out: dict[tuple[str, str, str], MfgInvBalanceRow] = {}
    for chunk in _chunks(sorted({p[0] for p in ps})):
        q = select(MfgInvBalanceRow).where(MfgInvBalanceRow.item_id.in_(chunk)) \
            .order_by(MfgInvBalanceRow.item_id, MfgInvBalanceRow.location_id, MfgInvBalanceRow.lot_key) \
            .with_for_update().execution_options(populate_existing=True)
        for r in s.execute(q).scalars():
            if (r.item_id, r.location_id) in ps:
                out[(r.item_id, r.location_id, r.lot_key)] = r
    return out


def lock_or_create_balances(s: Session, keys: Iterable[tuple[str, str, str]], lot_ids: dict[tuple[str, str], str]
                            ) -> dict[tuple[str, str, str], MfgInvBalanceRow]:
    """Balances by key, created (zero) when missing; `lot_ids[(item_id, lot_code)]` for lot balances."""
    ks = sorted(set(keys))
    found = lock_balances(s, ks)
    now = utcnow()
    for key in ks:
        if key in found:
            continue
        try:
            with s.begin_nested():
                row = MfgInvBalanceRow(id=new_id("bal_"), item_id=key[0], location_id=key[1],
                                       lot_id=lot_ids.get((key[0], key[2])) if key[2] else None, lot_key=key[2],
                                       qty_on_hand=0.0, qty_reserved=0.0, last_receipt_on=None, updated_at=now)
                s.add(row)
                s.flush()
            found[key] = row
        except IntegrityError as exc:
            if not is_unique_violation(exc, "uq_mfg_inv_balances_key"):
                raise
            found.update(lock_balances(s, [key]))
    return found


# ---------------------------------------------------------------- number series


def _lock_series(s: Session, kind: str) -> MfgNumberSeriesRow:
    q = select(MfgNumberSeriesRow).where(MfgNumberSeriesRow.kind == kind).with_for_update() \
        .execution_options(populate_existing=True)
    row = s.execute(q).scalars().first()
    if row is not None:
        return row
    try:
        with s.begin_nested():
            row = MfgNumberSeriesRow(id=new_id("nsr_"), kind=kind, prefix=SERIES_PREFIX[kind], next_value=1)
            s.add(row)
            s.flush()
        return row
    except IntegrityError as exc:
        if not is_unique_violation(exc, "uq_mfg_number_series_kind"):
            raise
        row = s.execute(q).scalars().first()
        assert row is not None
        return row


def next_number(s: Session, kind: str, taken: Callable[[str], bool]) -> str:
    """Lock the series row (step 5) and return the next free number (`PO-000001`, ...), skipping numbers already
    used (imported documents may carry series-like numbers)."""
    row = _lock_series(s, kind)
    n = int(row.next_value)
    while True:
        cand = f"{row.prefix}{n:0{SERIES_WIDTH}d}"
        n += 1
        if not taken(cand):
            row.next_value = n
            s.flush()
            return cand


def number_taken(s: Session, model: Any, **where: Any) -> Callable[[str], bool]:
    def taken(cand: str) -> bool:
        q = select(model.id).where(model.number == cand, *[getattr(model, k) == v for k, v in where.items()])
        return s.execute(q.limit(1)).first() is not None
    return taken


__all__ = ["SERIES_PREFIX", "inputs_token", "item_supplier_record", "load_dataset", "load_import_dataset",
           "load_master_m2", "load_mrp_snapshot", "load_txn", "location_record", "lock_balances",
           "lock_balances_at", "lock_children", "lock_children_of", "lock_docs", "lock_lots",
           "lock_or_create_balances", "lock_or_create_lots", "next_number", "number_taken", "snapshot_tx",
           "supplier_record"]
