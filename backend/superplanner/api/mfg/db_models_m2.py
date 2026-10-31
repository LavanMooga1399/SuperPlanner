"""M2 tables (M2-DESIGN 9.3) on the shared `Base`; migration `0004_mfg_m2`.

M1 6.1 conventions: every table is owned (`OwnedMixin`), ids are `new_id(prefix)`, no server defaults, named
constraints <= 63 characters, an `owner_id`-led index on every table and an index led by every FK column.
Additions (9.1): MRP result tables store master ids as plain strings without FKs (only `run_id` is a FK, CASCADE);
self references are `SET NULL`; `mfg_inv_transactions.seq` is an always-generated identity (global order and the
staleness token). Relationships are not used (loaders select per table; ORM writes only).

Registries (9.4): `ALL_MFG_MODELS` = M1 `MFG_MODELS` + the M2 data models in FK order (reset deletes them in
reverse); `MFG_ACCESS_MODELS` = workspace memberships (survive a data reset).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, Double, ForeignKey, Identity, Index,
                        Integer, String, UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base, JsonType, utcnow
from ..db.ownership import OwnedMixin
from .db_models import MFG_MODELS, _Editable


def _extref(table: str, *lead: str) -> Index:
    return Index(f"uq_{table}_extref", "owner_id", *lead, "external_ref", unique=True,
                 postgresql_where=text("external_ref IS NOT NULL"))


def _dt(nullable: bool = True) -> Any:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


# ---------------------------------------------------------------- master data

class MfgLocationRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_locations"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_mfg_locations_code"),
                      _extref("mfg_locations"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))
    receipt_default: Mapped[bool] = mapped_column(Boolean)
    active: Mapped[bool] = mapped_column(Boolean)
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str] = mapped_column(String(500))


class MfgSupplierRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_suppliers"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_mfg_suppliers_code"),
                      _extref("mfg_suppliers"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8))
    contact_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(50))
    address: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean)
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str] = mapped_column(String(500))


class MfgItemSupplierRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_item_suppliers"
    __table_args__ = (UniqueConstraint("owner_id", "item_id", "supplier_id", name="uq_mfg_item_suppliers_key"),
                      Index("ix_mfg_item_suppliers_item", "item_id"),
                      Index("ix_mfg_item_suppliers_supplier", "supplier_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="CASCADE"))
    supplier_id: Mapped[str] = mapped_column(ForeignKey("mfg_suppliers.id", ondelete="CASCADE"))
    supplier_part_number: Mapped[str] = mapped_column(String(64))
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_order_qty: Mapped[float] = mapped_column(Double)
    order_multiple: Mapped[float] = mapped_column(Double)
    purchase_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    units_per_purchase_unit: Mapped[float] = mapped_column(Double)
    unit_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    currency: Mapped[str] = mapped_column(String(8))
    preferred: Mapped[bool] = mapped_column(Boolean)
    active: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str] = mapped_column(String(500))


# ---------------------------------------------------------------- lots, purchasing, demand, work orders

class MfgLotRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_lots"
    __table_args__ = (UniqueConstraint("owner_id", "item_id", "lot_code", name="uq_mfg_lots_key"),
                      Index("ix_mfg_lots_owner_expires", "owner_id", "expires_on"),
                      Index("ix_mfg_lots_item", "item_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    lot_code: Mapped[str] = mapped_column(String(64))
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier_lot: Mapped[str] = mapped_column(String(64))
    hold: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str] = mapped_column(String(500))


class MfgPurchaseDocRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_purchase_docs"
    __table_args__ = (UniqueConstraint("owner_id", "doc_type", "number", name="uq_mfg_purchase_docs_number"),
                      Index("ix_mfg_purchase_docs_owner_status", "owner_id", "doc_type", "status"),
                      Index("ix_mfg_purchase_docs_supplier", "supplier_id"),
                      _extref("mfg_purchase_docs", "doc_type"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(2))
    number: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_suppliers.id", ondelete="RESTRICT"),
                                                    nullable=True)
    currency: Mapped[str] = mapped_column(String(8))
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(8))
    source_run_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime | None] = _dt()
    submitted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = _dt()
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejected_reason: Mapped[str] = mapped_column(String(500))
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)


class MfgPurchaseLineRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_purchase_lines"
    __table_args__ = (UniqueConstraint("doc_id", "line_no", name="uq_mfg_purchase_lines_no"),
                      Index("ix_mfg_purchase_lines_item", "item_id"),
                      Index("ix_mfg_purchase_lines_source_pr_line", "source_pr_line_id"),
                      Index("ix_mfg_purchase_lines_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("mfg_purchase_docs.id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    unit_price: Mapped[float | None] = mapped_column(Double, nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    source_pr_line_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_purchase_lines.id", ondelete="SET NULL"),
                                                          nullable=True)
    note: Mapped[str] = mapped_column(String(500))


class MfgPurchaseScheduleRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_purchase_schedules"
    __table_args__ = (UniqueConstraint("line_id", "seq", name="uq_mfg_purchase_schedules_seq"),
                      Index("ix_mfg_purchase_schedules_owner_requested", "owner_id", "requested_date"),
                      CheckConstraint("received_qty >= 0", name="ck_mfg_purchase_schedules_received"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    line_id: Mapped[str] = mapped_column(ForeignKey("mfg_purchase_lines.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    requested_date: Mapped[date] = mapped_column(Date)
    confirmed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    qty: Mapped[float] = mapped_column(Double)
    received_qty: Mapped[float] = mapped_column(Double)
    closed: Mapped[bool] = mapped_column(Boolean)


class MfgDemandOrderRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_demand_orders"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_demand_orders_number"),
                      Index("ix_mfg_demand_orders_owner_status", "owner_id", "status"),
                      _extref("mfg_demand_orders"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = mapped_column(String(32))
    demand_type: Mapped[str] = mapped_column(String(16))
    customer: Mapped[str] = mapped_column(String(200))
    program: Mapped[str | None] = mapped_column(String(32), nullable=True)
    priority: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(500))
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MfgDemandLineRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_demand_lines"
    __table_args__ = (UniqueConstraint("order_id", "line_no", name="uq_mfg_demand_lines_no"),
                      Index("ix_mfg_demand_lines_item", "item_id"),
                      Index("ix_mfg_demand_lines_owner_due", "owner_id", "due_date"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("mfg_demand_orders.id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    qty: Mapped[float] = mapped_column(Double)
    due_date: Mapped[date] = mapped_column(Date)
    shipped_qty: Mapped[float] = mapped_column(Double)
    serial_from: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    serial_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(500))


class MfgWorkOrderRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_work_orders"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_work_orders_number"),
                      Index("ix_mfg_work_orders_owner_status", "owner_id", "status"),
                      Index("ix_mfg_work_orders_item", "item_id"),
                      Index("ix_mfg_work_orders_bom", "bom_id"),
                      Index("ix_mfg_work_orders_routing", "routing_id"),
                      Index("ix_mfg_work_orders_receipt_location", "receipt_location_id"),        # M4
                      Index("ix_mfg_work_orders_demand_line", "demand_line_id"),
                      _extref("mfg_work_orders"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = mapped_column(String(32))
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    qty: Mapped[float] = mapped_column(Double)
    qty_completed: Mapped[float] = mapped_column(Double)
    qty_scrapped: Mapped[float] = mapped_column(Double)
    start_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))
    priority: Mapped[int] = mapped_column(Integer)
    serial_from: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    serial_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bom_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_boms.id", ondelete="SET NULL"), nullable=True)
    routing_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_routings.id", ondelete="SET NULL"), nullable=True)
    demand_line_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_demand_lines.id", ondelete="SET NULL"),
                                                       nullable=True)
    source: Mapped[str] = mapped_column(String(8))
    source_run_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_planned_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    released_at: Mapped[datetime | None] = _dt()
    # M4-DESIGN 3.1 / 4.1
    receipt_location_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_locations.id", ondelete="SET NULL"),
                                                            nullable=True)
    released_to_floor_at: Mapped[datetime | None] = _dt()
    release_override: Mapped[str | None] = mapped_column(String(200), nullable=True)
    completed_at: Mapped[datetime | None] = _dt()
    closed_at: Mapped[datetime | None] = _dt()
    note: Mapped[str] = mapped_column(String(500))
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MfgWoComponentRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_wo_components"
    __table_args__ = (Index("ix_mfg_wo_components_wo", "wo_id"), Index("ix_mfg_wo_components_item", "item_id"),
                      Index("ix_mfg_wo_components_owner", "owner_id"),
                      CheckConstraint("issued_qty >= 0", name="ck_mfg_wo_components_issued"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wo_id: Mapped[str] = mapped_column(ForeignKey("mfg_work_orders.id", ondelete="CASCADE"))
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    required_qty: Mapped[float] = mapped_column(Double)
    issued_qty: Mapped[float] = mapped_column(Double)
    operation_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    find_number: Mapped[str | None] = mapped_column(String(16), nullable=True)
    alt_group: Mapped[str | None] = mapped_column(String(16), nullable=True)
    bom_line_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str] = mapped_column(String(500))


# ---------------------------------------------------------------- inventory ledger

class MfgInvBalanceRow(OwnedMixin, Base):
    __tablename__ = "mfg_inv_balances"
    __table_args__ = (UniqueConstraint("owner_id", "item_id", "location_id", "lot_key",
                                       name="uq_mfg_inv_balances_key"),
                      Index("ix_mfg_inv_balances_item", "item_id"),
                      Index("ix_mfg_inv_balances_location", "location_id"),
                      Index("ix_mfg_inv_balances_lot", "lot_id"),
                      CheckConstraint("qty_on_hand >= 0", name="ck_mfg_inv_balances_on_hand"),
                      CheckConstraint("qty_reserved >= 0", name="ck_mfg_inv_balances_reserved"),
                      CheckConstraint("qty_reserved <= qty_on_hand + 0.000001",
                                      name="ck_mfg_inv_balances_reserved_le_on_hand"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    location_id: Mapped[str] = mapped_column(ForeignKey("mfg_locations.id", ondelete="RESTRICT"))
    lot_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_lots.id", ondelete="RESTRICT"), nullable=True)
    lot_key: Mapped[str] = mapped_column(String(64))
    qty_on_hand: Mapped[float] = mapped_column(Double)
    qty_reserved: Mapped[float] = mapped_column(Double)
    last_receipt_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MfgInvReservationRow(OwnedMixin, Base):
    __tablename__ = "mfg_inv_reservations"
    __table_args__ = (UniqueConstraint("wo_component_id", "balance_id", name="uq_mfg_inv_reservations_key"),
                      Index("ix_mfg_inv_reservations_balance", "balance_id"),
                      Index("ix_mfg_inv_reservations_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wo_component_id: Mapped[str] = mapped_column(ForeignKey("mfg_wo_components.id", ondelete="RESTRICT"))
    balance_id: Mapped[str] = mapped_column(ForeignKey("mfg_inv_balances.id", ondelete="RESTRICT"))
    qty: Mapped[float] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MfgInvPostingRow(OwnedMixin, Base):
    __tablename__ = "mfg_inv_postings"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_inv_postings_number"),
                      Index("uq_mfg_inv_postings_idem", "owner_id", "idempotency_key", unique=True,
                            postgresql_where=text("idempotency_key IS NOT NULL")),
                      Index("ix_mfg_inv_postings_owner_created", "owner_id", "created_at"),
                      Index("ix_mfg_inv_postings_reversal_of", "reversal_of_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(16))
    txn_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(500))
    reason_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    reversal_of_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_inv_postings.id", ondelete="SET NULL"),
                                                       nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MfgInvTransactionRow(OwnedMixin, Base):
    __tablename__ = "mfg_inv_transactions"
    __table_args__ = (UniqueConstraint("seq", name="uq_mfg_inv_transactions_seq"),
                      Index("ix_mfg_inv_transactions_owner_seq", "owner_id", "seq"),
                      Index("ix_mfg_inv_transactions_item_seq", "item_id", "seq"),
                      Index("ix_mfg_inv_transactions_location", "location_id"),
                      Index("ix_mfg_inv_transactions_lot", "lot_id"),
                      Index("ix_mfg_inv_transactions_posting", "posting_id"),
                      Index("ix_mfg_inv_transactions_schedule", "schedule_id"),
                      Index("ix_mfg_inv_transactions_wo", "wo_id"),
                      Index("ix_mfg_inv_transactions_wo_component", "wo_component_id"),
                      Index("ix_mfg_inv_transactions_demand_line", "demand_line_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    posting_id: Mapped[str] = mapped_column(ForeignKey("mfg_inv_postings.id", ondelete="CASCADE"))
    line_no: Mapped[int] = mapped_column(Integer)
    txn_type: Mapped[str] = mapped_column(String(16))
    txn_date: Mapped[date] = mapped_column(Date)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    location_id: Mapped[str] = mapped_column(ForeignKey("mfg_locations.id", ondelete="RESTRICT"))
    lot_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_lots.id", ondelete="RESTRICT"), nullable=True)
    qty: Mapped[float] = mapped_column(Double)
    balance_after: Mapped[float] = mapped_column(Double)
    unit_cost: Mapped[float | None] = mapped_column(Double, nullable=True)
    #: `wo_receipt`: scrap recorded with this receipt line (moves no stock; the reversal negates it)
    scrap_qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_purchase_schedules.id", ondelete="RESTRICT"),
                                                    nullable=True)
    wo_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_work_orders.id", ondelete="RESTRICT"), nullable=True)
    wo_component_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_wo_components.id", ondelete="RESTRICT"),
                                                        nullable=True)
    demand_line_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_demand_lines.id", ondelete="RESTRICT"),
                                                       nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MfgNumberSeriesRow(OwnedMixin, Base):
    __tablename__ = "mfg_number_series"
    __table_args__ = (UniqueConstraint("owner_id", "kind", name="uq_mfg_number_series_kind"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))
    prefix: Mapped[str] = mapped_column(String(16))
    next_value: Mapped[int] = mapped_column(BigInteger)


# ---------------------------------------------------------------- MRP runs and results (snapshots, no master FKs)

class MfgMrpRunRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_mrp_runs"
    __table_args__ = (UniqueConstraint("owner_id", "run_no", name="uq_mfg_mrp_runs_no"),
                      Index("uq_mfg_mrp_runs_running", "owner_id", unique=True,
                            postgresql_where=text("status = 'running'")),
                      Index("ix_mfg_mrp_runs_owner_created", "owner_id", "created_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(String(500))
    pinned: Mapped[bool] = mapped_column(Boolean)
    params: Mapped[dict[str, Any]] = mapped_column(JsonType)
    as_of: Mapped[date] = mapped_column(Date)
    horizon_days: Mapped[int] = mapped_column(Integer)
    master_fingerprint: Mapped[str] = mapped_column(String(64))
    data_version: Mapped[int] = mapped_column(Integer)
    inputs_token: Mapped[dict[str, Any]] = mapped_column(JsonType)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = _dt()
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)


class MfgMrpPlannedOrderRow(OwnedMixin, Base):
    __tablename__ = "mfg_mrp_planned_orders"
    __table_args__ = (UniqueConstraint("run_id", "planned_no", name="uq_mfg_mrp_planned_orders_no"),
                      Index("ix_mfg_mrp_planned_orders_run_kind_start", "run_id", "kind", "start_date"),
                      Index("ix_mfg_mrp_planned_orders_run_item", "run_id", "item_id"),
                      Index("ix_mfg_mrp_planned_orders_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_mrp_runs.id", ondelete="CASCADE"))
    planned_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))
    item_id: Mapped[str] = mapped_column(String(64))
    part_number: Mapped[str] = mapped_column(String(64))
    supplier_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    qty: Mapped[float] = mapped_column(Double)
    need_date: Mapped[date] = mapped_column(Date)
    start_date: Mapped[date] = mapped_column(Date)
    dock_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    projected_start: Mapped[date] = mapped_column(Date)
    projected_due: Mapped[date] = mapped_column(Date)
    late_days: Mapped[int] = mapped_column(Integer)
    release_status: Mapped[str] = mapped_column(String(16))
    segment: Mapped[Any | None] = mapped_column(JsonType, nullable=True)
    bom_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    routing_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llc: Mapped[int] = mapped_column(Integer)
    lot_note: Mapped[str] = mapped_column(String(200))
    peg_summary: Mapped[Any] = mapped_column(JsonType)
    order_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))
    converted_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    converted_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    converted_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    converted_at: Mapped[datetime | None] = _dt()
    converted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MfgMrpExceptionRow(OwnedMixin, Base):
    __tablename__ = "mfg_mrp_exceptions"
    __table_args__ = (Index("ix_mfg_mrp_exceptions_run_sev_code", "run_id", "severity", "code"),
                      Index("ix_mfg_mrp_exceptions_run_item", "run_id", "item_id"),
                      Index("ix_mfg_mrp_exceptions_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_mrp_runs.id", ondelete="CASCADE"))
    ex_no: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(8))
    item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    demand_line_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject: Mapped[Any] = mapped_column(JsonType)
    ex_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    qty: Mapped[float | None] = mapped_column(Double, nullable=True)
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(String(1000))
    action: Mapped[str] = mapped_column(String(500))
    suggested: Mapped[Any | None] = mapped_column(JsonType, nullable=True)
    related: Mapped[Any] = mapped_column(JsonType)


class MfgMrpItemResultRow(OwnedMixin, Base):
    __tablename__ = "mfg_mrp_item_results"
    __table_args__ = (UniqueConstraint("run_id", "item_id", name="uq_mfg_mrp_item_results_item"),
                      Index("ix_mfg_mrp_item_results_run_pn", "run_id", "part_number"),
                      Index("ix_mfg_mrp_item_results_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_mrp_runs.id", ondelete="CASCADE"))
    item_id: Mapped[str] = mapped_column(String(64))
    part_number: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500))
    make_buy: Mapped[str] = mapped_column(String(8))
    uom: Mapped[str] = mapped_column(String(8))
    llc: Mapped[int] = mapped_column(Integer)
    on_hand: Mapped[float] = mapped_column(Double)
    gross_qty: Mapped[float] = mapped_column(Double)
    existing_supply_qty: Mapped[float] = mapped_column(Double)
    planned_qty: Mapped[float] = mapped_column(Double)
    planned_count: Mapped[int] = mapped_column(Integer)
    first_short_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    short_qty: Mapped[float] = mapped_column(Double)
    late_qty: Mapped[float] = mapped_column(Double)
    min_balance: Mapped[float] = mapped_column(Double)
    exception_count: Mapped[int] = mapped_column(Integer)
    detail: Mapped[Any] = mapped_column(JsonType)


class MfgMrpDemandResultRow(OwnedMixin, Base):
    __tablename__ = "mfg_mrp_demand_results"
    __table_args__ = (Index("ix_mfg_mrp_demand_results_run_late", "run_id", "late_days"),
                      Index("ix_mfg_mrp_demand_results_run_line", "run_id", "demand_line_id"),
                      Index("ix_mfg_mrp_demand_results_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_mrp_runs.id", ondelete="CASCADE"))
    demand_line_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_number: Mapped[str] = mapped_column(String(32))
    line_no: Mapped[int] = mapped_column(Integer)
    extra: Mapped[bool] = mapped_column(Boolean)
    item_id: Mapped[str] = mapped_column(String(64))
    part_number: Mapped[str] = mapped_column(String(64))
    qty: Mapped[float] = mapped_column(Double)
    due_date: Mapped[date] = mapped_column(Date)
    projected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    late_days: Mapped[int] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    program: Mapped[str | None] = mapped_column(String(32), nullable=True)
    segment: Mapped[Any | None] = mapped_column(JsonType, nullable=True)
    limiting: Mapped[Any] = mapped_column(JsonType)


# ---------------------------------------------------------------- workspace members (10)

class MfgPlantMemberRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_plant_members"
    __table_args__ = (UniqueConstraint("owner_id", "user_id", name="uq_mfg_plant_members_user"),
                      Index("ix_mfg_plant_members_user", "user_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    roles: Mapped[list[Any]] = mapped_column(JsonType)
    active: Mapped[bool] = mapped_column(Boolean)
    invited_by: Mapped[str] = mapped_column(String(64))


#: The 21 M2 data tables in FK (creation) order.
M2_MODELS: tuple[type[Base], ...] = (
    MfgLocationRow, MfgSupplierRow, MfgItemSupplierRow, MfgLotRow, MfgPurchaseDocRow, MfgPurchaseLineRow,
    MfgPurchaseScheduleRow, MfgDemandOrderRow, MfgDemandLineRow, MfgWorkOrderRow, MfgWoComponentRow,
    MfgInvBalanceRow, MfgInvReservationRow, MfgInvPostingRow, MfgInvTransactionRow, MfgNumberSeriesRow,
    MfgMrpRunRow, MfgMrpPlannedOrderRow, MfgMrpExceptionRow, MfgMrpItemResultRow, MfgMrpDemandResultRow)
MFG_ACCESS_MODELS: tuple[type[Base], ...] = (MfgPlantMemberRow,)
#: M1 + M2 data tables in FK order (reset deletes in reverse; memberships are not data)
ALL_MFG_MODELS: tuple[type[Base], ...] = MFG_MODELS + M2_MODELS
ALL_MFG_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in ALL_MFG_MODELS)
M2_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in M2_MODELS + MFG_ACCESS_MODELS)
