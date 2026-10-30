"""M3 tables (M3-DESIGN 10) on the shared `Base`; migration `0005_mfg_m3`.

M1/M2 conventions: owned tables, `new_id(prefix)` ids, no server defaults, named constraints, an `owner_id`-led
index on every table and an index led by every FK column. Master tables (rates, setup matrix, absences) follow the
plant lock / `data_version` rules; `mfg_wo_op_progress` is transactional; APS result tables store master ids as plain
strings without FKs (only `run_id` is a FK, CASCADE; the parent run reference is SET NULL).

Registries: `M3_MODELS` (FK order); `ALL_MFG_MODELS` = M1 + M2 + M3 data models (reset deletes them in reverse).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Double, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base, JsonType
from ..db.ownership import OwnedMixin
from .db_models import _Editable
from .db_models_m2 import ALL_MFG_MODELS as _M1_M2_MODELS


def _dt(nullable: bool = True) -> Any:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


# ---------------------------------------------------------------- master data (3.2)

class MfgOperationLineRateRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_operation_line_rates"
    __table_args__ = (UniqueConstraint("operation_id", "line_id", name="uq_mfg_operation_line_rates_key"),
                      Index("ix_mfg_operation_line_rates_line", "line_id"),
                      Index("ix_mfg_operation_line_rates_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("mfg_operations.id", ondelete="CASCADE"))
    line_id: Mapped[str] = mapped_column(ForeignKey("mfg_lines.id", ondelete="CASCADE"))
    setup_minutes: Mapped[float | None] = mapped_column(Double, nullable=True)
    run_minutes: Mapped[float | None] = mapped_column(Double, nullable=True)
    note: Mapped[str] = mapped_column(String(500))


class MfgSetupMatrixRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_setup_matrix"
    __table_args__ = (UniqueConstraint("owner_id", "line_setup_family", "from_family", "to_family",
                                       name="uq_mfg_setup_matrix_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    line_setup_family: Mapped[str] = mapped_column(String(32))
    from_family: Mapped[str] = mapped_column(String(32))
    to_family: Mapped[str] = mapped_column(String(32))
    setup_minutes: Mapped[float] = mapped_column(Double)


class MfgOperatorAbsenceRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_operator_absences"
    __table_args__ = (Index("ix_mfg_operator_absences_operator_start", "operator_id", "start_at"),
                      Index("ix_mfg_operator_absences_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operator_id: Mapped[str] = mapped_column(ForeignKey("mfg_operators.id", ondelete="CASCADE"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(500))


# ---------------------------------------------------------------- WO operation progress (3.3)

class MfgWoOpProgressRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_wo_op_progress"
    __table_args__ = (UniqueConstraint("wo_id", "seq", name="uq_mfg_wo_op_progress_key"),
                      Index("ix_mfg_wo_op_progress_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wo_id: Mapped[str] = mapped_column(ForeignKey("mfg_work_orders.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    done: Mapped[bool] = mapped_column(Boolean)
    done_at: Mapped[datetime | None] = _dt()
    done_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ---------------------------------------------------------------- APS runs and results (10)

class MfgApsRunRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_aps_runs"
    __table_args__ = (UniqueConstraint("owner_id", "run_no", name="uq_mfg_aps_runs_no"),
                      Index("uq_mfg_aps_runs_active", "owner_id", unique=True,
                            postgresql_where=text("status IN ('queued', 'running')")),
                      Index("uq_mfg_aps_runs_published", "owner_id", unique=True,
                            postgresql_where=text("is_published")),
                      Index("ix_mfg_aps_runs_owner_created", "owner_id", "created_at"),
                      Index("ix_mfg_aps_runs_parent", "parent_run_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(String(500))
    pinned: Mapped[bool] = mapped_column(Boolean)
    is_published: Mapped[bool] = mapped_column(Boolean)
    published_at: Mapped[datetime | None] = _dt()
    published_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_aps_runs.id", ondelete="SET NULL"),
                                                      nullable=True)
    copy_of_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mrp_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JsonType)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    master_fingerprint: Mapped[str] = mapped_column(String(64))
    data_version: Mapped[int] = mapped_column(Integer)
    inputs_token: Mapped[dict[str, Any]] = mapped_column(JsonType)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean)
    progress: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    score: Mapped[list[Any] | None] = mapped_column(JsonType, nullable=True)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    #: demand view rows and bottlenecks (small; read with the run)
    extras: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    error: Mapped[Any | None] = mapped_column(JsonType, nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = _dt()
    finished_at: Mapped[datetime | None] = _dt()
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MfgApsOpRow(OwnedMixin, Base):
    __tablename__ = "mfg_aps_ops"
    __table_args__ = (UniqueConstraint("run_id", "op_no", name="uq_mfg_aps_ops_no"),
                      Index("ix_mfg_aps_ops_run_line_start", "run_id", "line_id", "start_at"),
                      Index("ix_mfg_aps_ops_run_order", "run_id", "order_id"),
                      Index("ix_mfg_aps_ops_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_aps_runs.id", ondelete="CASCADE"))
    op_no: Mapped[int] = mapped_column(Integer)
    order_type: Mapped[str] = mapped_column(String(8))
    order_id: Mapped[str] = mapped_column(String(64))
    order_number: Mapped[str] = mapped_column(String(32))
    planned_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_id: Mapped[str] = mapped_column(String(64))
    part_number: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    group_id: Mapped[str] = mapped_column(String(64))
    line_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    split_index: Mapped[int] = mapped_column(Integer)
    split_count: Mapped[int] = mapped_column(Integer)
    qty: Mapped[float] = mapped_column(Double)
    start_at: Mapped[datetime | None] = _dt()
    end_at: Mapped[datetime | None] = _dt()
    setup_minutes: Mapped[int] = mapped_column(Integer)
    run_minutes: Mapped[int] = mapped_column(Integer)
    pieces: Mapped[Any] = mapped_column(JsonType)
    crew: Mapped[Any] = mapped_column(JsonType)
    tools: Mapped[Any] = mapped_column(JsonType)
    release: Mapped[Any] = mapped_column(JsonType)
    locked: Mapped[bool] = mapped_column(Boolean)
    frozen: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[Any] = mapped_column(JsonType)
    due_at: Mapped[datetime | None] = _dt()
    late_minutes: Mapped[int] = mapped_column(Integer)
    family: Mapped[str] = mapped_column(String(32))
    setup_from_family: Mapped[str | None] = mapped_column(String(32), nullable=True)


class MfgApsOvertimeRow(OwnedMixin, Base):
    __tablename__ = "mfg_aps_overtime"
    __table_args__ = (Index("ix_mfg_aps_overtime_run_line", "run_id", "line_id", "start_at"),
                      Index("ix_mfg_aps_overtime_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_aps_runs.id", ondelete="CASCADE"))
    line_id: Mapped[str] = mapped_column(String(64))
    assignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    minutes: Mapped[int] = mapped_column(Integer)
    cost: Mapped[float] = mapped_column(Double)
    status: Mapped[str] = mapped_column(String(16))
    tardiness_saved_minutes: Mapped[float | None] = mapped_column(Double, nullable=True)
    reason: Mapped[str] = mapped_column(String(500))
    orders: Mapped[Any] = mapped_column(JsonType)


class MfgApsOrderRow(OwnedMixin, Base):
    __tablename__ = "mfg_aps_orders"
    __table_args__ = (Index("ix_mfg_aps_orders_run_late", "run_id", "late_minutes"),
                      Index("ix_mfg_aps_orders_run_order", "run_id", "order_id"),
                      Index("ix_mfg_aps_orders_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_aps_runs.id", ondelete="CASCADE"))
    order_type: Mapped[str] = mapped_column(String(8))
    order_id: Mapped[str] = mapped_column(String(64))
    number: Mapped[str] = mapped_column(String(32))
    planned_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_id: Mapped[str] = mapped_column(String(64))
    part_number: Mapped[str] = mapped_column(String(64))
    qty: Mapped[float] = mapped_column(Double)
    due_at: Mapped[datetime | None] = _dt()
    start_at: Mapped[datetime | None] = _dt()
    end_at: Mapped[datetime | None] = _dt()
    late_minutes: Mapped[int] = mapped_column(Integer)
    weight: Mapped[float] = mapped_column(Double)
    priority: Mapped[int] = mapped_column(Integer)
    rank_label: Mapped[str] = mapped_column(String(100))
    demand_refs: Mapped[Any] = mapped_column(JsonType)
    late_chain: Mapped[Any] = mapped_column(JsonType)
    late_text: Mapped[str] = mapped_column(String(1000))
    unscheduled_ops: Mapped[int] = mapped_column(Integer)


class MfgApsExceptionRow(OwnedMixin, Base):
    __tablename__ = "mfg_aps_exceptions"
    __table_args__ = (Index("ix_mfg_aps_exceptions_run_sev_code", "run_id", "severity", "code"),
                      Index("ix_mfg_aps_exceptions_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_aps_runs.id", ondelete="CASCADE"))
    ex_no: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(8))
    subject: Mapped[Any] = mapped_column(JsonType)
    op_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_ref: Mapped[Any | None] = mapped_column(JsonType, nullable=True)
    message: Mapped[str] = mapped_column(String(1000))
    refs: Mapped[Any] = mapped_column(JsonType)


class MfgApsLoadRow(OwnedMixin, Base):
    __tablename__ = "mfg_aps_load"
    __table_args__ = (Index("ix_mfg_aps_load_run_group_day", "run_id", "group_id", "day"),
                      Index("ix_mfg_aps_load_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_aps_runs.id", ondelete="CASCADE"))
    group_id: Mapped[str] = mapped_column(String(64))
    line_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    day: Mapped[date] = mapped_column(Date)
    scheduled_minutes: Mapped[float] = mapped_column(Double)
    required_minutes: Mapped[float] = mapped_column(Double)
    base_minutes: Mapped[float] = mapped_column(Double)
    optional_minutes: Mapped[float] = mapped_column(Double)
    opened_minutes: Mapped[float] = mapped_column(Double)


M3_MASTER_MODELS: tuple[type[Base], ...] = (MfgOperationLineRateRow, MfgSetupMatrixRow, MfgOperatorAbsenceRow)
APS_RESULT_MODELS: tuple[type[Base], ...] = (MfgApsOpRow, MfgApsOvertimeRow, MfgApsOrderRow, MfgApsExceptionRow,
                                             MfgApsLoadRow)
M3_MODELS: tuple[type[Base], ...] = M3_MASTER_MODELS + (MfgWoOpProgressRow, MfgApsRunRow) + APS_RESULT_MODELS
M3_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in M3_MODELS)
#: M1 + M2 + M3 data tables in FK order (reset deletes in reverse; memberships are not data)
ALL_MFG_MODELS: tuple[type[Base], ...] = _M1_M2_MODELS + M3_MODELS
ALL_MFG_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in ALL_MFG_MODELS)
