"""M9 tables (M9-DESIGN 3) on the shared `Base`; migration `0012_m9` (expand).

Network-owned (`owner_id` = the organisation's network workspace): lanes, sourcing rules, network runs and their
transfers / production / shortages / projection, S&OP cycles, demand rows and overrides, scenarios, ramp curves,
tariff / FX / milestone / country-risk tables and tariff reports. Plant-owned: MPS targets and item trade data.
Columns on existing tables live on their ORM classes (plant kind, item-supplier trade fields, lot COO / domestic
shares, transfer order source) and are listed in `M9_COLUMNS`. No server defaults (M1-M8 conventions).
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


def _d(nullable: bool = False) -> Any:
    return mapped_column(Date, nullable=nullable)


def _b(nullable: bool = False) -> Any:
    return mapped_column(Boolean, nullable=nullable)


def _id() -> Any:
    return mapped_column(String(64), primary_key=True)


# ---------------------------------------------------------------- topology (4)

class MfgNetLaneRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_net_lanes"
    __table_args__ = (UniqueConstraint("owner_id", "from_owner_id", "to_owner_id", "mode", name="uq_mfg_net_lanes_key"),)

    id: Mapped[str] = _id()
    from_owner_id: Mapped[str] = _s(64)
    to_owner_id: Mapped[str] = _s(64)
    mode: Mapped[str] = _s(8)
    transit_days: Mapped[int] = _i()
    freight_per_unit: Mapped[float] = _f()
    freight_per_kg: Mapped[float | None] = _f(True)
    currency: Mapped[str] = _s(8)
    active: Mapped[bool] = _b()


class MfgNetSourcingRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_net_sourcing"
    __table_args__ = (Index("ix_mfg_net_sourcing_owner", "owner_id", "dest_owner_id"),
                      Index("ix_mfg_net_sourcing_lane", "lane_id"))

    id: Mapped[str] = _id()
    dest_owner_id: Mapped[str] = _s(64)
    item_key: Mapped[str | None] = _s(64, True)
    family: Mapped[str | None] = _s(32, True)
    source_kind: Mapped[str] = _s(8)
    source_owner_id: Mapped[str | None] = _s(64, True)
    supplier_code: Mapped[str | None] = _s(32, True)
    priority: Mapped[int] = _i()
    quota_pct: Mapped[float | None] = _f(True)
    lane_id: Mapped[str | None] = mapped_column(ForeignKey("mfg_net_lanes.id", ondelete="SET NULL"), nullable=True)
    valid_from: Mapped[date | None] = _d(True)
    valid_to: Mapped[date | None] = _d(True)
    active: Mapped[bool] = _b()


class MfgNetRampCurveRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_net_ramp_curves"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_mfg_net_ramp_curves_code"),)

    id: Mapped[str] = _id()
    code: Mapped[str] = _s(16)
    name: Mapped[str] = _s(200)
    points: Mapped[list[Any]] = _j()


# ---------------------------------------------------------------- network runs (5)

class MfgNetRunRow(OwnedMixin, Base):
    __tablename__ = "mfg_net_runs"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_net_runs_number"),
                      Index("ix_mfg_net_runs_owner", "owner_id", "created_at"))

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    label: Mapped[str] = _s(100)
    params: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(16)
    as_of: Mapped[date] = _d()
    input_hash: Mapped[str | None] = _s(64, True)
    summary: Mapped[dict[str, Any] | None] = _j(True)
    validator: Mapped[dict[str, Any] | None] = _j(True)
    explanations: Mapped[list[Any] | None] = _j(True)
    published: Mapped[bool] = _b()
    published_at: Mapped[datetime | None] = _dt()
    published_by: Mapped[str | None] = _s(64, True)
    publish_result: Mapped[dict[str, Any] | None] = _j(True)
    error: Mapped[str | None] = _s(2000, True)
    actor_id: Mapped[str | None] = _s(64, True)
    created_at: Mapped[datetime] = _dt(False)
    started_at: Mapped[datetime | None] = _dt()
    finished_at: Mapped[datetime | None] = _dt()
    duration_ms: Mapped[int | None] = _i(True)


def _run_fk() -> Any:
    return mapped_column(ForeignKey("mfg_net_runs.id", ondelete="CASCADE"))


class MfgNetTransferRow(OwnedMixin, Base):
    __tablename__ = "mfg_net_transfers"
    __table_args__ = (Index("ix_mfg_net_transfers_run", "run_id", "dst_owner_id", "item_key"),
                      Index("ix_mfg_net_transfers_owner", "owner_id"))

    id: Mapped[str] = _id()
    run_id: Mapped[str] = _run_fk()
    src_owner_id: Mapped[str] = _s(64)
    dst_owner_id: Mapped[str] = _s(64)
    item_key: Mapped[str] = _s(64)
    lane_id: Mapped[str | None] = _s(64, True)
    ship_date: Mapped[date] = _d()
    receive_date: Mapped[date] = _d()
    qty: Mapped[float] = _f()
    firm: Mapped[bool] = _b()
    to_id: Mapped[str | None] = _s(64, True)
    pegs: Mapped[list[Any]] = _j()


class MfgNetProductionRow(OwnedMixin, Base):
    __tablename__ = "mfg_net_production"
    __table_args__ = (Index("ix_mfg_net_production_run", "run_id", "node_owner_id", "item_key"),
                      Index("ix_mfg_net_production_owner", "owner_id"))

    id: Mapped[str] = _id()
    run_id: Mapped[str] = _run_fk()
    node_owner_id: Mapped[str] = _s(64)
    item_key: Mapped[str] = _s(64)
    week: Mapped[date] = _d()
    qty: Mapped[float] = _f()
    kind: Mapped[str] = _s(4)
    cap_group: Mapped[str | None] = _s(32, True)
    hours: Mapped[float] = _f()
    prebuilt_from: Mapped[date | None] = _d(True)
    pegs: Mapped[list[Any]] = _j()


class MfgNetShortageRow(OwnedMixin, Base):
    __tablename__ = "mfg_net_shortages"
    __table_args__ = (Index("ix_mfg_net_shortages_run", "run_id", "node_owner_id"),
                      Index("ix_mfg_net_shortages_owner", "owner_id"))

    id: Mapped[str] = _id()
    run_id: Mapped[str] = _run_fk()
    node_owner_id: Mapped[str] = _s(64)
    item_key: Mapped[str] = _s(64)
    week: Mapped[date] = _d()
    qty: Mapped[float] = _f()
    cause: Mapped[str] = _s(24)
    detail: Mapped[dict[str, Any]] = _j()


class MfgNetProjectionRow(OwnedMixin, Base):
    __tablename__ = "mfg_net_projection"
    __table_args__ = (UniqueConstraint("run_id", "node_owner_id", "item_key", "week", name="uq_mfg_net_projection_key"),
                      Index("ix_mfg_net_projection_owner", "owner_id"))

    id: Mapped[str] = _id()
    run_id: Mapped[str] = _run_fk()
    node_owner_id: Mapped[str] = _s(64)
    item_key: Mapped[str] = _s(64)
    week: Mapped[date] = _d()
    gross: Mapped[float] = _f()
    receipts: Mapped[float] = _f()
    planned_in: Mapped[float] = _f()
    planned_out: Mapped[float] = _f()
    projected: Mapped[float] = _f()
    ss: Mapped[float] = _f()


# ---------------------------------------------------------------- S&OP (6, 7)

class MfgSopCycleRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_sop_cycles"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_sop_cycles_number"),
                      Index("ix_mfg_sop_cycles_owner", "owner_id", "period"))

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    period: Mapped[date] = _d()
    horizon_months: Mapped[int] = _i()
    status: Mapped[str] = _s(16)
    steps: Mapped[list[Any]] = _j()
    demand_sources: Mapped[dict[str, Any]] = _j()
    recommended_scenario_id: Mapped[str | None] = _s(64, True)
    recommend_note: Mapped[str | None] = _s(2000, True)
    approved_scenario_id: Mapped[str | None] = _s(64, True)
    content_hash: Mapped[str | None] = _s(64, True)
    publish_result: Mapped[dict[str, Any] | None] = _j(True)
    reopen_reason: Mapped[str | None] = _s(500, True)


def _cycle_fk(nullable: bool = False) -> Any:
    return mapped_column(ForeignKey("mfg_sop_cycles.id", ondelete="CASCADE"), nullable=nullable)


class MfgSopDemandRow(OwnedMixin, Base):
    __tablename__ = "mfg_sop_demand"
    __table_args__ = (UniqueConstraint("cycle_id", "node_owner_id", "family", "month", name="uq_mfg_sop_demand_key"),
                      Index("ix_mfg_sop_demand_owner", "owner_id"))

    id: Mapped[str] = _id()
    cycle_id: Mapped[str] = _cycle_fk()
    node_owner_id: Mapped[str] = _s(64)
    family: Mapped[str] = _s(32)
    month: Mapped[date] = _d()
    stat_qty: Mapped[float] = _f()
    order_qty: Mapped[float] = _f()
    base_qty: Mapped[float] = _f()
    prior_consensus: Mapped[float | None] = _f(True)
    consensus_qty: Mapped[float] = _f()
    asp: Mapped[float | None] = _f(True)
    asp_currency: Mapped[str] = _s(8)
    asp_source: Mapped[str] = _s(8)
    #: item drill-down / disaggregation basis: {item_key: {stat, order, base}}
    items: Mapped[dict[str, Any]] = _j()


class MfgSopOverrideRow(OwnedMixin, Base):
    __tablename__ = "mfg_sop_demand_overrides"
    __table_args__ = (Index("ix_mfg_sop_demand_overrides_cycle", "cycle_id", "seq"),
                      Index("ix_mfg_sop_demand_overrides_owner", "owner_id"))

    id: Mapped[str] = _id()
    cycle_id: Mapped[str] = _cycle_fk()
    node_owner_id: Mapped[str | None] = _s(64, True)
    family: Mapped[str] = _s(32)
    month_from: Mapped[date] = _d()
    month_to: Mapped[date] = _d()
    mode: Mapped[str] = _s(4)
    value: Mapped[float] = _f()
    reason: Mapped[str] = _s(500)
    seq: Mapped[int] = _i()
    created_by: Mapped[str] = _s(64)
    created_at: Mapped[datetime] = _dt(False)
    removed_at: Mapped[datetime | None] = _dt()


class MfgSopScenarioRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_sop_scenarios"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_sop_scenarios_number"),
                      Index("ix_mfg_sop_scenarios_cycle", "cycle_id"))

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    cycle_id: Mapped[str | None] = _cycle_fk(True)
    name: Mapped[str] = _s(200)
    baseline: Mapped[bool] = _b()
    changes: Mapped[list[Any]] = _j()
    capex_note: Mapped[str] = _s(2000)
    enforce_milestones: Mapped[bool] = _b()
    status: Mapped[str] = _s(12)
    input_hash: Mapped[str | None] = _s(64, True)
    result: Mapped[dict[str, Any] | None] = _j(True)
    kpis: Mapped[dict[str, Any] | None] = _j(True)
    validator: Mapped[dict[str, Any] | None] = _j(True)
    warnings: Mapped[list[Any] | None] = _j(True)
    error: Mapped[str | None] = _s(2000, True)
    run_at: Mapped[datetime | None] = _dt()


class MfgMpsTargetRow(OwnedMixin, Base):
    """Plant-owned: the published S&OP make plan (family x month)."""
    __tablename__ = "mfg_mps_targets"
    __table_args__ = (UniqueConstraint("owner_id", "family", "month", name="uq_mfg_mps_targets_key"),)

    id: Mapped[str] = _id()
    cycle_id: Mapped[str] = _s(64)
    cycle_number: Mapped[str | None] = _s(32, True)
    family: Mapped[str] = _s(32)
    month: Mapped[date] = _d()
    qty_target: Mapped[float] = _f()
    hours: Mapped[dict[str, Any]] = _j()
    created_at: Mapped[datetime] = _dt(False)


# ---------------------------------------------------------------- trade (8)

class MfgItemTradeRow(OwnedMixin, _Editable, Base):
    """Plant master, 1:1 item."""
    __tablename__ = "mfg_item_trade"
    __table_args__ = (UniqueConstraint("item_id", name="uq_mfg_item_trade_item"),
                      Index("ix_mfg_item_trade_owner", "owner_id"))

    id: Mapped[str] = _id()
    item_id: Mapped[str] = mapped_column(ForeignKey("mfg_items.id", ondelete="CASCADE"))
    hts_code: Mapped[str | None] = _s(10, True)
    coo: Mapped[str | None] = _s(2, True)
    material_class: Mapped[str | None] = _s(16, True)
    unit_weight_kg: Mapped[float | None] = _f(True)


class MfgTariffRateRow(OwnedMixin, Base):
    __tablename__ = "mfg_tariff_rates"
    __table_args__ = (UniqueConstraint("owner_id", "dest_country", "hts_prefix", "coo", "layer", "valid_from",
                                       name="uq_mfg_tariff_rates_key"),)

    id: Mapped[str] = _id()
    dest_country: Mapped[str] = _s(2)
    hts_prefix: Mapped[str] = _s(10)
    coo: Mapped[str] = _s(2)
    layer: Mapped[str] = _s(16)
    rate_pct: Mapped[float] = _f()
    per_unit: Mapped[float | None] = _f(True)
    per_unit_currency: Mapped[str | None] = _s(8, True)
    valid_from: Mapped[date] = _d()
    valid_to: Mapped[date | None] = _d(True)
    note: Mapped[str] = _s(500)


class MfgFxRateRow(OwnedMixin, Base):
    __tablename__ = "mfg_fx_rates"
    __table_args__ = (UniqueConstraint("owner_id", "from_ccy", "to_ccy", "month", name="uq_mfg_fx_rates_key"),)

    id: Mapped[str] = _id()
    from_ccy: Mapped[str] = _s(3)
    to_ccy: Mapped[str] = _s(3)
    month: Mapped[date] = _d()
    rate: Mapped[float] = _f()
    source: Mapped[str] = _s(16)


class MfgTariffMilestoneRow(OwnedMixin, _Editable, Base):
    __tablename__ = "mfg_tariff_milestones"
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_mfg_tariff_milestones_code"),)

    id: Mapped[str] = _id()
    code: Mapped[str] = _s(32)
    name: Mapped[str] = _s(200)
    dest_country: Mapped[str] = _s(2)
    family: Mapped[str | None] = _s(32, True)
    hts_prefix: Mapped[str | None] = _s(10, True)
    rule: Mapped[dict[str, Any]] = _j()
    effective: Mapped[date] = _d()
    note: Mapped[str] = _s(500)


class MfgTariffReportRow(OwnedMixin, Base):
    __tablename__ = "mfg_tariff_reports"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_mfg_tariff_reports_number"),)

    id: Mapped[str] = _id()
    number: Mapped[str] = _s(32)
    params: Mapped[dict[str, Any]] = _j()
    status: Mapped[str] = _s(16)
    result: Mapped[dict[str, Any] | None] = _j(True)
    error: Mapped[str | None] = _s(2000, True)
    actor_id: Mapped[str | None] = _s(64, True)
    created_at: Mapped[datetime] = _dt(False)
    started_at: Mapped[datetime | None] = _dt()
    finished_at: Mapped[datetime | None] = _dt()


class MfgCountryRiskRow(OwnedMixin, Base):
    __tablename__ = "mfg_country_risk"
    __table_args__ = (UniqueConstraint("owner_id", "country", name="uq_mfg_country_risk_country"),)

    id: Mapped[str] = _id()
    country: Mapped[str] = _s(2)
    score: Mapped[int] = _i()
    note: Mapped[str] = _s(500)


# ---------------------------------------------------------------- registries

#: FK order (reset deletes in reverse)
M9_NET_MODELS: tuple[type[Base], ...] = (
    MfgNetLaneRow, MfgNetSourcingRow, MfgNetRampCurveRow, MfgNetRunRow, MfgNetTransferRow, MfgNetProductionRow,
    MfgNetShortageRow, MfgNetProjectionRow, MfgSopCycleRow, MfgSopDemandRow, MfgSopOverrideRow, MfgSopScenarioRow,
    MfgTariffRateRow, MfgFxRateRow, MfgTariffMilestoneRow, MfgTariffReportRow, MfgCountryRiskRow)
M9_PLANT_MODELS: tuple[type[Base], ...] = (MfgMpsTargetRow, MfgItemTradeRow)
M9_OWNED_MODELS: tuple[type[Base], ...] = M9_NET_MODELS + M9_PLANT_MODELS
M9_TABLES: tuple[str, ...] = tuple(m.__tablename__ for m in M9_OWNED_MODELS)
M9_RESET_MODELS: tuple[type[Base], ...] = M9_OWNED_MODELS
#: (table, column) pairs added to existing tables by 0012_m9
M9_COLUMNS: tuple[tuple[str, str], ...] = (
    ("mfg_plant", "kind"), ("mfg_item_suppliers", "coo"), ("mfg_item_suppliers", "hts_code"),
    ("mfg_item_suppliers", "incoterm"), ("mfg_item_suppliers", "freight_per_unit"),
    ("mfg_item_suppliers", "cap_per_month"), ("mfg_lots", "coo"), ("mfg_lots", "coo_source"),
    ("mfg_lots", "unit_value"), ("mfg_lots", "dom_share_value"), ("mfg_lots", "dom_share_weight"),
    ("mfg_lots", "dom_estimated"), ("mfg_lots", "dom_computed_at"), ("mfg_transfer_orders", "source"),
    ("mfg_transfer_orders", "net_run_id"))
M9_ID_PREFIXES = {"lane": "nln_", "sourcing": "nsg_", "net_run": "nrn_", "net_transfer": "npt_",
                  "net_production": "npp_", "net_shortage": "nsh_", "net_projection": "npj_", "sop_cycle": "scy_",
                  "sop_demand": "sdm_", "sop_override": "sdo_", "sop_scenario": "ssc_", "ramp_curve": "rmp_",
                  "mps_target": "mps_", "item_trade": "itr_", "tariff": "trf_", "fx": "fxr_", "milestone": "tms_",
                  "tariff_report": "trp_", "country_risk": "ckr_"}
#: job kinds (duty runs on `maintenance_runs`)
M9_JOB_KINDS = ("net_run", "net_publish", "sop_scenario_run", "sop_publish", "content_rollup", "tariff_report")
