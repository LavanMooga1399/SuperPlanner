"""M4 tables (M4-DESIGN 3.2) on the shared `Base`; migration `0006_mfg_m4`.

M1-M3 conventions: owned tables, `new_id(prefix)` ids, no server defaults, named constraints, an `owner_id`-led
index on every table and an index led by every FK column. `mfg_wo_operations` is the execution state maintained
from the append-only `mfg_floor_events` (4.2); the M3 `mfg_wo_op_progress` table is gone (migrated rows become
`source = migrated` operations).

Registries: `M4_MODELS` (FK order); `ALL_MFG_MODELS` = M1 + M2 + M3 + M4 data models (reset deletes them in reverse).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, Double, ForeignKey, Identity, Index, Integer, String,
                        UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base, JsonType
from ..db.ownership import OwnedMixin
from .db_models import _Editable
from .db_models_m3 import ALL_MFG_MODELS as _M1_M3_MODELS


def _dt(nullable: bool = True) -> Any:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


class MfgWoOperationRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_wo_operations"
    __table_args__ = (UniqueConstraint("wo_id", "seq", name="uq_mfg_wo_operations_key"),
                      Index("ix_mfg_wo_operations_owner_status", "owner_id", "status"),
                      Index("ix_mfg_wo_operations_line", "line_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wo_id: Mapped[str] = mapped_column(ForeignKey("mfg_work_orders.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    group_id: Mapped[str] = mapped_column(String(64))
    #: stored status; `ready` is computed on read (4.2)
    status: Mapped[str] = mapped_column(String(16))
    qty_planned: Mapped[float] = mapped_column(Double)
    qty_good: Mapped[float] = mapped_column(Double)
    qty_scrap: Mapped[float] = mapped_column(Double)
    qty_rework_out: Mapped[float] = mapped_column(Double)
    qty_rework_in: Mapped[float] = mapped_column(Double)
    line_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_lines.id", ondelete="SET NULL"), nullable=True)
    setup_minutes_actual: Mapped[float] = mapped_column(Double)
    run_minutes_actual: Mapped[float] = mapped_column(Double)
    labour_minutes: Mapped[float] = mapped_column(Double)
    actual_start: Mapped[datetime | None] = _dt()
    actual_end: Mapped[datetime | None] = _dt()
    started_short: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(8))
    #: the latest applied event `seq` (None = no event) - the recompute cursor
    last_event_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: 16.WP-S: the automatic effects of this operation (cumulative, so reports never double-post and reopen can
    #: reverse): {"received": qty, "backflush": {component_id: {"posted": q, "pending": q}}}
    effects: Mapped[dict[str, Any]] = mapped_column(JsonType)
    completed_at: Mapped[datetime | None] = _dt()
    completed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MfgBatchLoadRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_batch_loads"
    __table_args__ = (Index("ix_mfg_batch_loads_line_status", "line_id", "status"),
                      Index("ix_mfg_batch_loads_owner_status", "owner_id", "status"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    line_id: Mapped[str] = mapped_column(ForeignKey("mfg_lines.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime | None] = _dt()
    ended_at: Mapped[datetime | None] = _dt()
    aps_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MfgBatchLoadMemberRow(OwnedMixin, Base):
    __tablename__ = "mfg_batch_load_members"
    __table_args__ = (UniqueConstraint("load_id", "wo_operation_id", name="uq_mfg_batch_load_members_key"),
                      Index("ix_mfg_batch_load_members_wo_operation", "wo_operation_id"),
                      Index("ix_mfg_batch_load_members_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    load_id: Mapped[str] = mapped_column(ForeignKey("mfg_batch_loads.id", ondelete="CASCADE"))
    wo_operation_id: Mapped[str] = mapped_column(ForeignKey("mfg_wo_operations.id", ondelete="RESTRICT"))
    qty: Mapped[float] = mapped_column(Double)


class MfgFloorEventRow(OwnedMixin, Base):
    """Append-only (F1): never updated except `corrected_by_event_id`-free bookkeeping; corrections are events."""
    __tablename__ = "mfg_floor_events"
    __table_args__ = (Index("uq_mfg_floor_events_client", "owner_id", "client_event_id", unique=True,
                            postgresql_where=text("client_event_id IS NOT NULL")),
                      Index("ix_mfg_floor_events_op_seq", "wo_operation_id", "seq"),
                      Index("ix_mfg_floor_events_owner_at", "owner_id", "event_at"),
                      Index("ix_mfg_floor_events_line_at", "line_id", "event_at"),
                      Index("ix_mfg_floor_events_wo", "wo_id"),
                      Index("ix_mfg_floor_events_batch_load", "batch_load_id"),
                      Index("ix_mfg_floor_events_corrects", "corrects_event_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    wo_operation_id: Mapped[str] = mapped_column(ForeignKey("mfg_wo_operations.id", ondelete="RESTRICT"))
    wo_id: Mapped[str] = mapped_column(ForeignKey("mfg_work_orders.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(String(16))
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    line_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator_ids: Mapped[list[str]] = mapped_column(JsonType)
    qty_good: Mapped[float | None] = mapped_column(Double, nullable=True)
    qty_scrap: Mapped[float | None] = mapped_column(Double, nullable=True)
    qty_rework: Mapped[float | None] = mapped_column(Double, nullable=True)
    rework_to_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(String(500))
    client_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    batch_load_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_batch_loads.id", ondelete="SET NULL"),
                                                      nullable=True)
    serials: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    corrects_event_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_floor_events.id", ondelete="SET NULL"),
                                                          nullable=True)
    #: `force.reason` (supervisor override, 4.2)
    forced: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: warnings, batch member quantities, posting ids, the replay response key
    details: Mapped[dict[str, Any]] = mapped_column(JsonType)
    actor_id: Mapped[str] = mapped_column(String(64))


class MfgDowntimeRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_downtime"
    __table_args__ = (Index("ix_mfg_downtime_line_start", "line_id", "start_at"),
                      Index("ix_mfg_downtime_owner_start", "owner_id", "start_at"),
                      Index("uq_mfg_downtime_idem", "owner_id", "idempotency_key", unique=True,
                            postgresql_where=text("idempotency_key IS NOT NULL")))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    line_id: Mapped[str] = mapped_column(ForeignKey("mfg_lines.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16))
    planned: Mapped[bool] = mapped_column(Boolean)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = _dt()
    expected_end_at: Mapped[datetime | None] = _dt()
    reason: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(500))
    reported_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: `Idempotency-Key` of the POST (offline tablets replay their queue, 16.WP-S)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)


class MfgUnitSerialRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_unit_serials"
    __table_args__ = (UniqueConstraint("owner_id", "item_id", "serial", name="uq_mfg_unit_serials_key"),
                      Index("ix_mfg_unit_serials_item_status", "item_id", "status"),
                      Index("ix_mfg_unit_serials_wo", "wo_id"),
                      Index("ix_mfg_unit_serials_parent", "parent_serial_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="RESTRICT"))
    serial: Mapped[str] = mapped_column(String(64))
    wo_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_work_orders.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    captured_op_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_serial_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_unit_serials.id", ondelete="SET NULL"),
                                                         nullable=True)
    consumed_at: Mapped[datetime | None] = _dt()
    consumed_wo_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: the event that captured it (reopen/correct reverse their own serials)
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MfgReplanTriggerRow(OwnedMixin, Base):
    __tablename__ = "mfg_replan_triggers"
    __table_args__ = (Index("uq_mfg_replan_triggers_open", "owner_id", "dedupe_key", unique=True,
                            postgresql_where=text("status IN ('open', 'attached')")),
                      Index("ix_mfg_replan_triggers_owner_status", "owner_id", "status", "detected_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(String(8))
    ref_type: Mapped[str] = mapped_column(String(16))
    ref_id: Mapped[str] = mapped_column(String(64))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    details: Mapped[dict[str, Any]] = mapped_column(JsonType)
    status: Mapped[str] = mapped_column(String(16))
    aps_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    handled_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    handled_at: Mapped[datetime | None] = _dt()
    note: Mapped[str] = mapped_column(String(500))


class MfgNotificationRow(OwnedMixin, Base):
    __tablename__ = "mfg_notifications"
    __table_args__ = (Index("ix_mfg_notifications_owner_created", "owner_id", "created_at"),
                      Index("ix_mfg_notifications_trigger", "trigger_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(1000))
    link: Mapped[str] = mapped_column(String(300))
    trigger_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_replan_triggers.id", ondelete="SET NULL"),
                                                   nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = _dt()
    acknowledged_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MfgApsSimulationRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_aps_simulations"
    __table_args__ = (Index("uq_mfg_aps_simulations_active", "owner_id", unique=True,
                            postgresql_where=text("status IN ('queued', 'running')")),
                      Index("ix_mfg_aps_simulations_owner_created", "owner_id", "created_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    base_run_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    samples: Mapped[int] = mapped_column(Integer)
    params: Mapped[dict[str, Any]] = mapped_column(JsonType)
    results: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    error: Mapped[Any | None] = mapped_column(JsonType, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean)
    actor_id: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = _dt()
    finished_at: Mapped[datetime | None] = _dt()
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MfgKpiDailyRow(OwnedMixin, Base):
    """Closed-day KPI cache (9). `dim_id` is `""` for the plant (16.WP-S: not NULL, so the unique key holds)."""
    __tablename__ = "mfg_kpi_daily"
    __table_args__ = (UniqueConstraint("owner_id", "day", "metric", "dim_type", "dim_id", name="uq_mfg_kpi_daily_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    metric: Mapped[str] = mapped_column(String(32))
    dim_type: Mapped[str] = mapped_column(String(8))
    dim_id: Mapped[str] = mapped_column(String(64))
    num: Mapped[float] = mapped_column(Double)
    den: Mapped[float] = mapped_column(Double)
    value: Mapped[float | None] = mapped_column(Double, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


M4_MODELS: tuple[type[Base], ...] = (MfgWoOperationRow, MfgBatchLoadRow, MfgBatchLoadMemberRow, MfgFloorEventRow,
                                     MfgDowntimeRow, MfgUnitSerialRow, MfgReplanTriggerRow, MfgNotificationRow,
                                     MfgApsSimulationRow, MfgKpiDailyRow)
M4_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in M4_MODELS)
#: M1 + M2 + M3 + M4 data tables in FK order (reset deletes in reverse; memberships are not data)
ALL_MFG_MODELS: tuple[type[Base], ...] = _M1_M3_MODELS + M4_MODELS
ALL_MFG_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in ALL_MFG_MODELS)
