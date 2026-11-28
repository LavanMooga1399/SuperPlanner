"""M8 tables (M8-DESIGN 3) on the shared `Base`; migration `0011_m8` (expand).

Forecasting (history, runs, versions, lines, overrides), safety-stock proposals, item planning and packaging, line
rates, the changeover matrix, rate runs and blocks, sterilisation loads and members, kanban loops and cards, and the
validation baselines. Every table is owned by the plant (`owner_id`) with an owner-led index and an index led by
every FK column; no server defaults (M1-M7 conventions).

Registries: `M8_OWNED_MODELS` (FK order; reset deletes them in reverse), `M8_TABLES`, `M8_COLUMNS` (columns added
to existing tables; they live on their ORM classes: lines, plant, work orders, lot holds, int_settings).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Double, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base, JsonType
from ..db.ownership import OwnedMixin
from .db_models import _Editable


def _dt(nullable: bool = True) -> Any:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


def _s(n: int, nullable: bool = False) -> Any:
    return mapped_column(String(n), nullable=nullable)


def _j(nullable: bool = False) -> Any:
    return mapped_column(JsonType, nullable=nullable)


def _f(nullable: bool = False) -> Any:
    return mapped_column(Double, nullable=nullable)


def _i(nullable: bool = False) -> Any:
    return mapped_column(Integer, nullable=nullable)


def _item_fk(nullable: bool = False) -> Any:
    return mapped_column(ForeignKey("mfg_items.id", ondelete="CASCADE"), nullable=nullable)


# ---------------------------------------------------------------- master: item planning, packaging, rates (3)

class MfgItemPlanningRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_item_planning"
    __table_args__ = (UniqueConstraint("item_id", name="uq_mfg_item_planning_item"),
                      Index("ix_mfg_item_planning_owner", "owner_id", "replenishment"),
                      Index("ix_mfg_item_planning_like", "like_item_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = _item_fk()
    replenishment: Mapped[str] = _s(8)
    forecast: Mapped[bool] = mapped_column(Boolean)
    like_item_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_items.id", ondelete="SET NULL"), nullable=True)
    like_factor: Mapped[float] = _f()
    service_level: Mapped[float | None] = _f(True)
    order_pack_level: Mapped[str | None] = _s(8, True)
    campaign_key: Mapped[str | None] = _s(32, True)
    campaign_min_hours: Mapped[float] = _f()
    campaign_max_hours: Mapped[float | None] = _f(True)
    target_cover_days: Mapped[int] = _i()
    ster_cycle_code: Mapped[str | None] = _s(16, True)
    aeration_hours: Mapped[float | None] = _f(True)
    release_mode: Mapped[str] = _s(12)
    release_days: Mapped[float] = _f()
    post_days: Mapped[int | None] = _i(True)
    abc: Mapped[str | None] = _s(1, True)
    xyz: Mapped[str | None] = _s(1, True)
    #: M10-DESIGN 3: eDHR release required (None = the plant default, QA settings `dhr_required`)
    dhr_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class MfgItemPackagingRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_item_packaging"
    __table_args__ = (UniqueConstraint("item_id", "level", name="uq_mfg_item_packaging_level"),
                      Index("ix_mfg_item_packaging_owner", "owner_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = _item_fk()
    level: Mapped[str] = _s(8)
    seq: Mapped[int] = _i()
    code: Mapped[str] = _s(32)
    qty_base: Mapped[float] = _f()
    gtin: Mapped[str | None] = _s(14, True)
    weight_kg: Mapped[float | None] = _f(True)


class MfgLineRateRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_line_rates"
    __table_args__ = (UniqueConstraint("line_id", "item_id", "item_family", name="uq_mfg_line_rates_key"),
                      Index("ix_mfg_line_rates_owner", "owner_id"),
                      Index("ix_mfg_line_rates_item", "item_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    line_id: Mapped[str] = mapped_column(ForeignKey("mfg_lines.id", ondelete="CASCADE"))
    item_id: Mapped[str | None] = _item_fk(True)
    item_family: Mapped[str | None] = _s(32, True)
    units_per_hour: Mapped[float] = _f()
    oee: Mapped[float | None] = _f(True)


class MfgChangeoverRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_changeover_rows"
    __table_args__ = (UniqueConstraint("owner_id", "line_setup_family", "from_key", "to_key", "kind",
                                       name="uq_mfg_changeover_rows_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    line_setup_family: Mapped[str] = _s(32)
    from_key: Mapped[str] = _s(32)
    to_key: Mapped[str] = _s(32)
    minutes: Mapped[int] = _i()
    cost: Mapped[float] = _f()
    kind: Mapped[str] = _s(10)


# ---------------------------------------------------------------- forecasting (4)

class MfgDemandHistoryRow(OwnedMixin, Base):
    __tablename__ = "mfg_demand_history"
    __table_args__ = (UniqueConstraint("owner_id", "item_id", "bucket", "period_start", "source",
                                       name="uq_mfg_demand_history_key"),
                      Index("ix_mfg_demand_history_item", "item_id", "bucket", "period_start"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = _item_fk()
    period_start: Mapped[date] = mapped_column(Date)
    bucket: Mapped[str] = _s(1)
    qty: Mapped[float] = _f()
    cleaned_qty: Mapped[float | None] = _f(True)
    #: planner-set cleaned value (wins over automatic cleaning; None = automatic)
    manual_qty: Mapped[float | None] = _f(True)
    source: Mapped[str] = _s(8)
    updated_at: Mapped[datetime] = _dt(False)


class MfgForecastRunRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_forecast_runs"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_forecast_runs_number"),
                      Index("ix_mfg_forecast_runs_owner", "owner_id", "created_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    params: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(16)
    as_of: Mapped[date] = mapped_column(Date)
    bucket: Mapped[str] = _s(1)
    first_period: Mapped[date | None] = mapped_column(Date, nullable=True)
    item_count: Mapped[int] = _i()
    summary: Mapped[dict[str, Any]] = _j()
    results: Mapped[dict[str, Any] | None] = _j(True)
    error: Mapped[str | None] = _s(500, True)
    started_at: Mapped[datetime | None] = _dt()
    finished_at: Mapped[datetime | None] = _dt()
    actor_id: Mapped[str] = _s(64)


class MfgForecastVersionRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_forecast_versions"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_forecast_versions_number"),
                      Index("ix_mfg_forecast_versions_owner", "owner_id", "status"),
                      Index("ix_mfg_forecast_versions_run", "run_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    name: Mapped[str] = _s(100)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_forecast_runs.id", ondelete="SET NULL"),
                                               nullable=True)
    status: Mapped[str] = _s(10)
    bucket: Mapped[str] = _s(1)
    start: Mapped[date] = mapped_column(Date)
    periods: Mapped[int] = _i()
    activated_by: Mapped[str | None] = _s(64, True)
    activated_at: Mapped[datetime | None] = _dt()
    archived_at: Mapped[datetime | None] = _dt()
    note: Mapped[str] = _s(500)


class MfgForecastLineRow(OwnedMixin, Base):
    __tablename__ = "mfg_forecast_lines"
    __table_args__ = (UniqueConstraint("version_id", "item_id", "period_start", name="uq_mfg_forecast_lines_key"),
                      Index("ix_mfg_forecast_lines_item", "owner_id", "item_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("mfg_forecast_versions.id", ondelete="CASCADE"))
    item_id: Mapped[str] = _item_fk()
    period_start: Mapped[date] = mapped_column(Date)
    stat_qty: Mapped[float] = _f()
    final_qty: Mapped[float] = _f()


class MfgForecastOverrideRow(OwnedMixin, Base):
    __tablename__ = "mfg_forecast_overrides"
    __table_args__ = (Index("ix_mfg_forecast_overrides_version", "version_id", "seq"),
                      Index("ix_mfg_forecast_overrides_owner", "owner_id"),
                      Index("ix_mfg_forecast_overrides_item", "item_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("mfg_forecast_versions.id", ondelete="CASCADE"))
    item_id: Mapped[str | None] = _item_fk(True)
    item_family: Mapped[str | None] = _s(32, True)
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = _s(4)
    value: Mapped[float] = _f()
    reason: Mapped[str] = _s(500)
    seq: Mapped[int] = _i()
    created_by: Mapped[str] = _s(64)
    created_at: Mapped[datetime] = _dt(False)
    removed_at: Mapped[datetime | None] = _dt()


# ---------------------------------------------------------------- safety stock (5)

class MfgSsRunRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_ss_runs"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_ss_runs_number"),
                      Index("ix_mfg_ss_runs_owner", "owner_id", "created_at"),
                      Index("ix_mfg_ss_runs_version", "forecast_version_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    params: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(16)
    forecast_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("mfg_forecast_versions.id", ondelete="SET NULL"), nullable=True)
    summary: Mapped[dict[str, Any]] = _j()
    error: Mapped[str | None] = _s(500, True)
    actor_id: Mapped[str] = _s(64)
    finished_at: Mapped[datetime | None] = _dt()


class MfgSsLineRow(OwnedMixin, Base):
    __tablename__ = "mfg_ss_lines"
    __table_args__ = (Index("ix_mfg_ss_lines_run", "run_id", "item_id"),
                      Index("ix_mfg_ss_lines_owner", "owner_id"),
                      Index("ix_mfg_ss_lines_item", "item_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_ss_runs.id", ondelete="CASCADE"))
    item_id: Mapped[str] = _item_fk()
    abc: Mapped[str] = _s(1)
    xyz: Mapped[str] = _s(1)
    service_level: Mapped[float] = _f()
    z: Mapped[float] = _f()
    d_day: Mapped[float] = _f()
    sigma_d_day: Mapped[float] = _f()
    lt_days: Mapped[float] = _f()
    sigma_lt_days: Mapped[float] = _f()
    current_ss: Mapped[float] = _f()
    proposed_ss: Mapped[float] = _f()
    delta_value: Mapped[float] = _f()
    flags: Mapped[list[str]] = _j()
    decision: Mapped[str] = _s(10)
    decided_by: Mapped[str | None] = _s(64, True)
    decided_at: Mapped[datetime | None] = _dt()


# ---------------------------------------------------------------- rate engine (7)

class MfgRateRunRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_rate_runs"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_rate_runs_number"),
                      Index("ix_mfg_rate_runs_owner", "owner_id", "created_at"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    label: Mapped[str] = _s(100)
    params: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(20)
    mrp_run_id: Mapped[str | None] = _s(64, True)
    as_of: Mapped[date] = mapped_column(Date)
    horizon_days: Mapped[int] = _i()
    published: Mapped[bool] = mapped_column(Boolean)
    published_at: Mapped[datetime | None] = _dt()
    published_by: Mapped[str | None] = _s(64, True)
    objective: Mapped[dict[str, Any] | None] = _j(True)
    summary: Mapped[dict[str, Any] | None] = _j(True)
    explanations: Mapped[list[Any] | None] = _j(True)
    shortages: Mapped[list[Any] | None] = _j(True)
    validator: Mapped[dict[str, Any] | None] = _j(True)
    duration_ms: Mapped[int | None] = _i(True)
    error: Mapped[str | None] = _s(500, True)
    actor_id: Mapped[str] = _s(64)
    finished_at: Mapped[datetime | None] = _dt()


class MfgRateBlockRow(OwnedMixin, Base):
    __tablename__ = "mfg_rate_blocks"
    __table_args__ = (Index("ix_mfg_rate_blocks_run_line", "run_id", "line_id", "start"),
                      Index("ix_mfg_rate_blocks_owner", "owner_id"),
                      Index("ix_mfg_rate_blocks_line", "line_id"),
                      Index("ix_mfg_rate_blocks_item", "item_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("mfg_rate_runs.id", ondelete="CASCADE"))
    line_id: Mapped[str] = mapped_column(ForeignKey("mfg_lines.id", ondelete="CASCADE"))
    kind: Mapped[str] = _s(10)
    item_id: Mapped[str | None] = _item_fk(True)
    campaign_no: Mapped[int] = _i()
    start: Mapped[datetime] = _dt(False)
    end: Mapped[datetime] = _dt(False)
    qty: Mapped[float] = _f()
    cases: Mapped[int | None] = _i(True)
    prod_date: Mapped[date] = mapped_column(Date)
    wo_id: Mapped[str | None] = _s(64, True)


# ---------------------------------------------------------------- sterilisation (8)

class MfgSterLoadRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_ster_loads"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_ster_loads_number"),
                      Index("ix_mfg_ster_loads_owner", "owner_id", "status", "planned_start"),
                      Index("ix_mfg_ster_loads_chamber", "chamber_line_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    run_id: Mapped[str | None] = _s(64, True)             # rate run planned from (None = ad hoc)
    chamber_line_id: Mapped[str] = mapped_column(ForeignKey("mfg_lines.id", ondelete="RESTRICT"))
    aeration_line_id: Mapped[str | None] = _s(64, True)
    cycle_code: Mapped[str] = _s(16)
    status: Mapped[str] = _s(16)
    pallets: Mapped[int] = _i()
    planned_start: Mapped[datetime] = _dt(False)
    planned_end: Mapped[datetime] = _dt(False)
    aeration_end: Mapped[datetime] = _dt(False)
    release_due: Mapped[date] = mapped_column(Date)
    actual_start: Mapped[datetime | None] = _dt()
    actual_end: Mapped[datetime | None] = _dt()
    actual_aeration_end: Mapped[datetime | None] = _dt()
    batch_load_id: Mapped[str | None] = _s(64, True)
    release_signature_id: Mapped[str | None] = _s(64, True)
    ncr_id: Mapped[str | None] = _s(64, True)
    flags: Mapped[list[str]] = _j()


class MfgSterLoadMemberRow(OwnedMixin, Base):
    __tablename__ = "mfg_ster_load_members"
    __table_args__ = (Index("ix_mfg_ster_load_members_load", "load_id"),
                      Index("ix_mfg_ster_load_members_owner", "owner_id"),
                      Index("ix_mfg_ster_load_members_lot", "lot_id"),
                      Index("ix_mfg_ster_load_members_wo", "wo_id"),
                      Index("ix_mfg_ster_load_members_item", "item_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    load_id: Mapped[str] = mapped_column(ForeignKey("mfg_ster_loads.id", ondelete="CASCADE"))
    wo_id: Mapped[str | None] = _s(64, True)
    rate_block_id: Mapped[str | None] = _s(64, True)
    lot_id: Mapped[str | None] = _s(64, True)
    item_id: Mapped[str] = _item_fk()
    qty: Mapped[float] = _f()
    pallets: Mapped[float] = _f()


# ---------------------------------------------------------------- kanban (6.2)

class MfgKanbanLoopRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_kanban_loops"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_kanban_loops_number"),
                      UniqueConstraint("item_id", "location_id", name="uq_mfg_kanban_loops_item_location"),
                      Index("ix_mfg_kanban_loops_owner", "owner_id"),
                      Index("ix_mfg_kanban_loops_location", "location_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    number: Mapped[str] = _s(32)
    item_id: Mapped[str] = _item_fk()
    location_id: Mapped[str] = mapped_column(ForeignKey("mfg_locations.id", ondelete="RESTRICT"))
    source: Mapped[str] = _s(4)
    supplier_id: Mapped[str | None] = _s(64, True)
    line_id: Mapped[str | None] = _s(64, True)
    cards: Mapped[int] = _i()
    container_qty: Mapped[float] = _f()
    lead_time_days: Mapped[int] = _i()
    trigger: Mapped[str] = _s(12)
    status: Mapped[str] = _s(12)
    consumed: Mapped[float] = _f()                        # consumption trigger counter (since the last signal)


class MfgKanbanCardRow(OwnedMixin, Base):
    __tablename__ = "mfg_kanban_cards"
    __table_args__ = (UniqueConstraint("loop_id", "card_no", name="uq_mfg_kanban_cards_no"),
                      Index("ix_mfg_kanban_cards_owner", "owner_id"),
                      Index("ix_mfg_kanban_cards_doc", "doc_id"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    loop_id: Mapped[str] = mapped_column(ForeignKey("mfg_kanban_loops.id", ondelete="CASCADE"))
    card_no: Mapped[int] = _i()
    state: Mapped[str] = _s(12)
    doc_type: Mapped[str | None] = _s(8, True)
    doc_id: Mapped[str | None] = _s(64, True)
    changed_at: Mapped[datetime] = _dt(False)


# ---------------------------------------------------------------- validation kit (10)

class ValBaselineRow(OwnedMixin, Base):
    __tablename__ = "val_baselines"
    __table_args__ = (Index("ix_val_baselines_owner", "owner_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = _s(200)
    created_by: Mapped[str] = _s(64)
    created_at: Mapped[datetime] = _dt(False)
    sha256: Mapped[str] = _s(64)
    content: Mapped[dict[str, Any]] = _j()


M8_OWNED_MODELS: tuple[type[Base], ...] = (
    MfgItemPlanningRow, MfgItemPackagingRow, MfgLineRateRow, MfgChangeoverRow, MfgDemandHistoryRow,
    MfgForecastRunRow, MfgForecastVersionRow, MfgForecastLineRow, MfgForecastOverrideRow, MfgSsRunRow, MfgSsLineRow,
    MfgRateRunRow, MfgRateBlockRow, MfgSterLoadRow, MfgSterLoadMemberRow, MfgKanbanLoopRow, MfgKanbanCardRow,
    ValBaselineRow)
M8_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in M8_OWNED_MODELS)
#: reset (M2 9.4) deletes the plant's M8 rows (in reverse) with its data
M8_RESET_MODELS: tuple[type[Base], ...] = M8_OWNED_MODELS
#: (table, column) pairs added to existing tables by 0011_m8
M8_COLUMNS: tuple[tuple[str, str], ...] = (
    ("mfg_lines", "planning"), ("mfg_lines", "oee"), ("mfg_lines", "clearance_minutes"),
    ("mfg_lines", "clean_every_hours"), ("mfg_lines", "clean_minutes"), ("mfg_lines", "chamber_pallets"),
    ("mfg_lines", "cycle_hours"), ("mfg_plant", "planning_settings"), ("mfg_work_orders", "rate_run_id"),
    ("mfg_lot_holds", "planned_release"), ("int_settings", "sap"))
#: ID prefixes (3; every prefix three letters so ids match `EntityId`: dh_ -> dhi_, ipl8_ -> ipn_, rr_ -> rrn_,
#: rb_ -> rbk_, sl_ -> stl_, vb_ -> vbl_)
M8_ID_PREFIXES = {"history": "dhi_", "forecast_run": "fcr_", "forecast_version": "fcv_", "forecast_line": "fcl_",
                  "forecast_override": "fco_", "ss_run": "ssp_", "ss_line": "ssl_", "packaging": "pkg_",
                  "item_planning": "ipn_", "line_rate": "lrt_", "changeover": "chg_", "rate_run": "rrn_",
                  "rate_block": "rbk_", "ster_load": "stl_", "ster_member": "slm_", "kanban_loop": "kbl_",
                  "kanban_card": "kbc_", "baseline": "vbl_"}
