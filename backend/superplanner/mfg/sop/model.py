"""S&OP / IBP contract (M9-DESIGN 6, 7; frozen at S0).

Pydantic: cycle, demand review, scenario (`ScenarioChange` = union on `kind`), approval and the read models of
S1-S23. Dataclasses: the pure LP input `SopProblem` (built by `sop/scenario.py`) and output `SopResult` (`sop/lp.py`,
checked by `sop/validator.py`). Months are first-of-month dates; money in the report currency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Any, Literal, Union

from pydantic import Field, StringConstraints, model_validator

from ...esig.model import SignatureInput
from ..model import Code, EntityId, MfgModel, Name
from ..network.model import Explanation, LaneMode, RampPoint, ValidatorReport, check_points
from ..trade.model import TariffRateInput

STEPS: tuple[str, ...] = ("draft", "demand_review", "supply_review", "pre_sop", "executive", "approved", "published")
SopStep = Literal["draft", "demand_review", "supply_review", "pre_sop", "executive", "approved", "published"]
SopStatus = Literal["draft", "demand_review", "supply_review", "pre_sop", "executive", "approved", "published",
                    "cancelled"]
ScenarioStatus = Literal["draft", "running", "completed", "failed"]
Ccy = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{3}$")]
Country = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{2}$")]
Family = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
NodeRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]   # owner id or code
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Note = Annotated[str, StringConstraints(max_length=2000)]
Share = Annotated[float, Field(ge=0, le=1)]
Money = Annotated[float, Field(ge=0, le=1e12)]


def _first(d: date | None) -> date | None:
    if d is not None and d.day != 1:
        raise ValueError("months are the 1st of a month")
    return d


# ---------------------------------------------------------------- cycle (6.1; S1-S6)

class CycleInput(MfgModel):
    period: date
    horizon_months: Annotated[int, Field(ge=3, le=36)] = 18
    forecast_versions: dict[EntityId, EntityId] | None = None   # node -> version (None = active)

    @model_validator(mode="after")
    def _p(self) -> "CycleInput":
        _first(self.period)
        return self


class AdvanceInput(MfgModel):
    note: Annotated[str, StringConstraints(max_length=500)] = ""


class ReopenInput(MfgModel):
    to_step: Literal["demand_review", "supply_review", "pre_sop", "executive"]
    reason: Reason


class CancelInput(MfgModel):
    reason: Reason


class StepInfo(MfgModel):
    step: SopStep
    due: date | None
    owner_id: str | None
    owner_name: str | None = None
    done_at: datetime | None
    done_by: str | None
    note: str | None
    overdue: bool = False


class FollowUp(MfgModel):
    change_id: str
    kind: str
    label: str
    node: str | None


class PublishNode(MfgModel):
    node: EntityId
    forecast_version_id: EntityId | None
    targets: int
    warnings: list[Explanation] = Field(default_factory=list)


class SopPublishResult(MfgModel):
    nodes: list[PublishNode]
    follow_ups: list[FollowUp]
    published_at: datetime


class CycleRecord(MfgModel):
    id: EntityId
    row_version: int
    number: str
    period: date
    horizon_months: int
    status: SopStatus
    steps: list[StepInfo]
    demand_sources: dict[str, str]
    recommended_scenario_id: EntityId | None
    recommend_note: str | None
    approved_scenario_id: EntityId | None
    content_hash: str | None
    publish_result: SopPublishResult | None
    publish_job_status: Literal["queued", "running", "completed", "failed"] | None = None
    reopen_reason: str | None
    report_currency: str
    signatures: list[dict[str, Any]] = Field(default_factory=list)
    people: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- demand review (6.2; S7-S10)

class DemandRowRecord(MfgModel):
    id: EntityId
    node_owner_id: EntityId
    family: str
    month: date
    stat_qty: float
    order_qty: float
    base_qty: float
    prior_consensus: float | None
    consensus_qty: float
    asp: float | None
    asp_currency: str
    asp_source: Literal["history", "cost", "manual"]


class OverrideInput(MfgModel):
    node_owner_id: EntityId | None = None
    family: Family
    month_from: date
    month_to: date
    mode: Literal["abs", "pct"]
    value: Annotated[float, Field(ge=-100, le=1e10)]
    reason: Reason

    @model_validator(mode="after")
    def _check(self) -> "OverrideInput":
        _first(self.month_from), _first(self.month_to)
        if self.month_to < self.month_from:
            raise ValueError("month_to must not be before month_from")
        if self.mode == "abs" and self.value < 0:
            raise ValueError("an absolute override is >= 0")
        return self


class OverrideRecord(OverrideInput):
    id: EntityId
    seq: int
    created_by: str
    created_at: datetime
    removed_at: datetime | None
    reason: str                                 # type: ignore[assignment]


class DemandView(MfgModel):
    months: list[date]
    families: list[str]
    items: list[DemandRowRecord]
    overrides: list[OverrideRecord]


class AspRow(MfgModel):
    node_owner_id: EntityId
    family: Family
    asp: Annotated[float, Field(ge=0, le=1e9)]
    currency: Ccy


class AspInput(MfgModel):
    rows: Annotated[list[AspRow], Field(min_length=1, max_length=5000)]
    reason: Annotated[str, StringConstraints(max_length=500)] = ""


# ---------------------------------------------------------------- scenario changes (7)

class _Change(MfgModel):
    id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    label: Annotated[str, StringConstraints(max_length=200)] = ""
    note: Annotated[str, StringConstraints(max_length=1000)] = ""


class AddLine(_Change):
    kind: Literal["add_line"] = "add_line"
    node: NodeRef
    cap_group: Code
    name: Name
    start: date
    hours_per_week: Annotated[float, Field(gt=0, le=168)]
    hpu_by_family: dict[Family, Annotated[float, Field(gt=0, le=1e4)]] | None = None
    uph_by_family: dict[Family, Annotated[float, Field(gt=0, le=1e7)]] | None = None
    oee: Annotated[float, Field(gt=0, le=1)] | None = None
    curve: Code | None = None
    points: Annotated[list[RampPoint], Field(max_length=60)] | None = None
    capex: Money | None = None
    capex_currency: Ccy | None = None
    fixed_cost_per_month: Money | None = None

    @model_validator(mode="after")
    def _check(self) -> "AddLine":
        if not self.hpu_by_family and not self.uph_by_family:
            raise ValueError("give hpu_by_family or uph_by_family")
        if self.points:
            check_points(self.points)
        if self.capex is not None and self.capex_currency is None:
            raise ValueError("capex needs capex_currency")
        return self


class NodeLane(MfgModel):
    from_: NodeRef | None = Field(default=None, alias="from")
    to: NodeRef | None = None
    mode: LaneMode = "road"
    transit_days: Annotated[int, Field(ge=0, le=120)]
    freight_per_unit: Annotated[float, Field(ge=0, le=1e6)] = 0.0

    model_config = {"extra": "forbid", "populate_by_name": True}

    @model_validator(mode="after")
    def _one(self) -> "NodeLane":
        if (self.from_ is None) == (self.to is None):
            raise ValueError("a new node's lane has exactly one of from / to")
        return self


class AddNode(_Change):
    kind: Literal["add_node"] = "add_node"
    code: Code
    name: Name
    node_kind: Literal["plant", "dc"] = "plant"
    country: Country
    currency: Ccy
    start: date
    lanes: Annotated[list[NodeLane], Field(max_length=50)] = Field(default_factory=list)


class CapacityChange(_Change):
    kind: Literal["capacity_change"] = "capacity_change"
    node: NodeRef
    cap_group: Code
    from_: date = Field(alias="from")
    to: date | None = None
    pct: Annotated[float, Field(ge=-100, le=1000)]

    model_config = {"extra": "forbid", "populate_by_name": True}


class ShareRow(MfgModel):
    source_node: NodeRef | None = None
    supplier_code: Code | None = None
    code: Code | None = None                  # supplier_allocation rows
    min_share: Share = 0.0
    max_share: Share = 1.0
    cap_per_month: Annotated[float, Field(ge=0, le=1e10)] | None = None

    @model_validator(mode="after")
    def _check(self) -> "ShareRow":
        if sum(x is not None for x in (self.source_node, self.supplier_code, self.code)) != 1:
            raise ValueError("give one of source_node / supplier_code / code")
        if self.max_share < self.min_share:
            raise ValueError("max_share must not be below min_share")
        return self


class Sourcing(_Change):
    kind: Literal["sourcing"] = "sourcing"
    dest_node: NodeRef
    family: Family
    sources: Annotated[list[ShareRow], Field(min_length=1, max_length=20)]


class BuyOption(MfgModel):
    code: Code
    unit_price: Annotated[float, Field(ge=0, le=1e9)]
    currency: Ccy
    coo: Country | None = None
    hts_code: Annotated[str, StringConstraints(pattern=r"^[0-9]{6,10}$")] | None = None
    freight_per_unit: Annotated[float, Field(ge=0, le=1e6)] | None = None
    cap_per_month: Annotated[float, Field(ge=0, le=1e10)] | None = None


class MakeVsBuy(_Change):
    kind: Literal["make_vs_buy"] = "make_vs_buy"
    node: NodeRef
    family: Family
    option: Literal["make", "buy", "both"]
    supplier: BuyOption | None = None

    @model_validator(mode="after")
    def _check(self) -> "MakeVsBuy":
        if self.option != "make" and self.supplier is None:
            raise ValueError("buy / both need a supplier")
        return self


class SupplierAllocation(_Change):
    kind: Literal["supplier_allocation"] = "supplier_allocation"
    node: NodeRef
    family: Family
    suppliers: Annotated[list[ShareRow], Field(min_length=1, max_length=20)]


class DemandChange(_Change):
    kind: Literal["demand_change"] = "demand_change"
    node: NodeRef | None = None
    family: Family | None = None
    from_: date = Field(alias="from")
    to: date | None = None
    pct: Annotated[float, Field(ge=-100, le=1000)]

    model_config = {"extra": "forbid", "populate_by_name": True}


class FxChange(MfgModel):
    from_: Ccy = Field(alias="from")
    to: Ccy
    rate: Annotated[float, Field(gt=0, le=1e6)]
    from_month: date

    model_config = {"extra": "forbid", "populate_by_name": True}


class FreightChange(MfgModel):
    lane: EntityId
    pct: Annotated[float, Field(ge=-100, le=1000)]


class CostChange(_Change):
    kind: Literal["cost_change"] = "cost_change"
    tariff: Annotated[list[TariffRateInput], Field(max_length=500)] | None = None
    fx: FxChange | None = None
    freight: FreightChange | None = None

    @model_validator(mode="after")
    def _one(self) -> "CostChange":
        if sum(x is not None for x in (self.tariff, self.fx, self.freight)) != 1:
            raise ValueError("a cost change is one of tariff / fx / freight")
        return self


ScenarioChange = Annotated[Union[AddLine, AddNode, CapacityChange, Sourcing, MakeVsBuy, SupplierAllocation,
                                 DemandChange, CostChange], Field(discriminator="kind")]


# ---------------------------------------------------------------- scenarios (S11-S21)

class ScenarioInput(MfgModel):
    cycle_id: EntityId | None = None          # POST only (None = template)
    name: Name
    changes: Annotated[list[ScenarioChange], Field(max_length=100)] = Field(default_factory=list)
    capex_note: Annotated[str, StringConstraints(max_length=2000)] = ""
    enforce_milestones: bool = False

    @model_validator(mode="after")
    def _ids(self) -> "ScenarioInput":
        ids = [c.id for c in self.changes]
        if len(ids) != len(set(ids)):
            raise ValueError("change ids are unique within a scenario")
        return self


class CopyInput(MfgModel):
    cycle_id: EntityId | None = None
    name: Name | None = None


class RecommendInput(MfgModel):
    scenario_id: EntityId
    note: Annotated[str, StringConstraints(max_length=2000)] = ""


class ApproveInput(MfgModel):
    scenario_id: EntityId
    signature: SignatureInput | None = None


class KpiSet(MfgModel):
    delivered_units: float
    consensus_units: float
    unmet_units: float
    service_pct: float | None
    revenue: float | None
    cogs: float | None
    gross_margin: float | None
    gm_pct: float | None
    inventory_value: float | None
    days_of_cover: float | None
    capex: float


class SopKpis(MfgModel):
    currency: str
    horizon: KpiSet
    year: KpiSet
    next3: KpiSet
    utilisation: list[dict[str, Any]] = Field(default_factory=list)   # {node, cap_group, max_pct, avg_pct}
    domestic: list[dict[str, Any]] = Field(default_factory=list)      # {milestone_id, code, family, min_pct, ...}


class ScenarioRecord(MfgModel):
    id: EntityId
    row_version: int
    number: str
    cycle_id: EntityId | None
    baseline: bool
    name: str
    changes: list[dict[str, Any]]
    capex_note: str
    enforce_milestones: bool
    status: ScenarioStatus
    input_hash: str | None
    kpis: SopKpis | None
    validator: ValidatorReport | None
    warnings: list[Explanation] = Field(default_factory=list)
    error: str | None
    run_at: datetime | None
    updated_at: datetime


class PlanRow(MfgModel):
    node_owner_id: str
    family: str
    month: date
    consensus: float
    make: float
    buy: dict[str, float]
    ship_in: float
    ship_out: float
    inv: float
    delivered: float
    unmet: float
    ss_short: float
    ss_target: float


class PlanView(MfgModel):
    months: list[date]
    items: list[PlanRow]


class RoughCutRow(MfgModel):
    node_owner_id: str
    cap_group: str
    month: date
    available: float
    required: float
    planned: float
    util: float | None
    factor: float | None


class RoughCutView(MfgModel):
    months: list[date]
    items: list[RoughCutRow]


class FinRow(MfgModel):
    key: str
    month: date | None
    revenue: float | None
    cogs: float | None
    freight: float | None
    gross_margin: float | None
    gm_pct: float | None
    inventory_value: float | None
    days_of_cover: float | None
    capex: float


class FinTotals(MfgModel):
    horizon: FinRow
    year: FinRow
    next3: FinRow


class FinancialView(MfgModel):
    currency: str
    group_by: Literal["total", "node", "family"]
    months: list[date]
    rows: list[FinRow]
    totals: FinTotals
    warnings: list[Explanation] = Field(default_factory=list)


class MakeBuyRow(MfgModel):
    node_owner_id: str
    family: str
    currency: str
    make_unit_cost: float | None
    buy: list[dict[str, Any]]                 # {supplier_code, coo, landed_unit_cost, duty_share}
    split_make: float
    split_buy: float
    hours_freed: float


class CompareEntry(MfgModel):
    scenario: dict[str, Any]                  # {id, number, name, status, baseline, validator_ok}
    kpis: SopKpis | None
    delta: dict[str, Any] | None


class CompareView(MfgModel):
    currency: str
    items: list[CompareEntry]


# ---------------------------------------------------------------- pure LP input / output (6.3)

@dataclass(frozen=True)
class SopLane:
    id: str
    src: str
    dst: str
    transit_months: int
    freight_per_unit: float                   # report currency
    families: frozenset[str] | None = None    # None = every family the rules allow


@dataclass(frozen=True)
class SopBuy:
    """A supplier option at a node for a family: landed unit cost in report currency (None = FX missing)."""
    node: str
    family: str
    code: str
    landed: float | None
    cap_per_month: float | None = None
    min_share: float = 0.0
    max_share: float = 1.0
    domestic: float = 0.0                     # domestic share of this supply (milestones)


@dataclass(frozen=True)
class SopProblem:
    months: list[date]
    nodes: list[str]
    families: list[str]
    demand: dict[tuple[str, str, date], float]                 # (node, family, month) -> consensus
    priority_weight: dict[tuple[str, str, date], float]        # orders before forecast (default 1)
    init_inv: dict[tuple[str, str], float]
    ss_target: dict[tuple[str, str], float]
    hours: dict[tuple[str, str, date], float]                  # (node, cap_group, month) -> effective hours
    hpu: dict[tuple[str, str, str], float]                     # (node, cap_group, family) -> hours / good unit
    make_allowed: frozenset[tuple[str, str]]                   # (node, family)
    conv_cost: dict[tuple[str, str], float]                    # (node, family) -> conversion cost / unit
    std_cost: dict[tuple[str, str], float]
    buys: list[SopBuy] = field(default_factory=list)
    lanes: list[SopLane] = field(default_factory=list)
    holding_rate: float = 0.2
    fixed_cost: float = 0.0                                    # fixed cost of added lines over the horizon
    make_domestic: dict[tuple[str, str], float] = field(default_factory=dict)
    milestones: list[dict[str, Any]] = field(default_factory=list)   # [{family, min_share}] when enforced
    ship_shares: dict[tuple[str, str], list[tuple[str, float, float]]] = field(default_factory=dict)
    # (dest, family) -> [(lane id, min share, max share)] from `sourcing` changes


@dataclass
class SopResult:
    status: str                                # optimal | infeasible | ...
    make: dict[tuple[str, str, date], float] = field(default_factory=dict)
    buy: dict[tuple[str, str, str, date], float] = field(default_factory=dict)   # (node, family, code, month)
    ship: dict[tuple[str, str, date], float] = field(default_factory=dict)       # (lane, family, ship month)
    inv: dict[tuple[str, str, date], float] = field(default_factory=dict)
    unmet: dict[tuple[str, str, date], float] = field(default_factory=dict)
    ss_short: dict[tuple[str, str, date], float] = field(default_factory=dict)
    objective: dict[str, float] = field(default_factory=dict)
    explanations: list[dict[str, Any]] = field(default_factory=list)
