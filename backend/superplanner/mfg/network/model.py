"""Network planning contract (M9-DESIGN 4, 5.1; frozen at S0).

Pydantic: inputs (`LaneInput`, `SourcingInput`, `NetParams`, `RampCurvesInput`) and API records (what the N routes
answer; the UI mirrors them in `frontend/src/mfg/api/typesM9.ts`). Dataclasses: the pure engine input `NetProblem`
(built by `network/build.py`) and output `NetResult` (`network/engine.py`, checked by `network/validator.py`).
Weeks are Monday dates; money in the report currency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from ..model import Code, EntityId, MfgModel, Name

NodeKind = Literal["plant", "dc", "network"]
LaneMode = Literal["road", "rail", "sea", "air"]
SourceKind = Literal["plant", "supplier"]
RunStatus = Literal["queued", "running", "completed", "failed"]
ShortageCause = Literal["NET_CAPACITY_SHORT", "NET_NO_SOURCE", "NET_LEAD_TIME", "NET_SUPPLIER_CAP"]
PegKind = Literal["order", "forecast", "ss", "dependent", "transfer"]
DemandKind = Literal["order", "forecast", "transfer_open"]
SupplyKind = Literal["stock", "po", "wo", "rate", "transfer_in"]
Ccy = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{3}$")]
Country = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{2}$")]
ItemKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Family = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
Label = Annotated[str, StringConstraints(max_length=100)]
Pct100 = Annotated[float, Field(ge=0, le=100)]

#: planning_settings keys of the network workspace (3) and their defaults
NET_SETTINGS_DEFAULTS: dict[str, Any] = {
    "net_horizon_weeks": 26, "net_firm_days": 14, "net_prebuild_weeks": 4, "net_constrained": True,
    "report_currency": "USD", "domestic_country": "US", "duty_base": {"*": "fob"}, "other_cost_pct": 0.5,
    "holding_rate_pct": 20.0,
    "sop_calendar": {"demand_review": 5, "supply_review": 8, "pre_sop": 10, "executive": 12}}


# ---------------------------------------------------------------- shared records

class Violation(MfgModel):
    code: str
    detail: Any = None


class ValidatorReport(MfgModel):
    ok: bool
    violations: list[Violation] = Field(default_factory=list)


class Explanation(MfgModel):
    code: str
    node: str | None = None
    key: str | None = None
    family: str | None = None
    week: date | None = None
    month: date | None = None
    detail: dict[str, Any] | None = None


# ---------------------------------------------------------------- topology (4; N1-N7, N16)

class NodeRecord(MfgModel):
    owner_id: EntityId
    code: str
    name: str
    kind: Literal["plant", "dc"]
    country: str | None
    currency: str
    tz: str
    member: bool
    lines: int = 0


class LaneInput(MfgModel):
    from_owner_id: EntityId
    to_owner_id: EntityId
    mode: LaneMode = "road"
    transit_days: Annotated[int, Field(ge=0, le=120)]
    freight_per_unit: Annotated[float, Field(ge=0, le=1_000_000)] = 0.0
    freight_per_kg: Annotated[float, Field(ge=0, le=1_000_000)] | None = None
    currency: Ccy = "USD"
    active: bool = True

    @model_validator(mode="after")
    def _distinct(self) -> "LaneInput":
        if self.from_owner_id == self.to_owner_id:
            raise ValueError("a lane joins two different nodes")
        return self


class LaneRecord(LaneInput):
    id: EntityId
    row_version: int
    updated_at: datetime


class SourcingInput(MfgModel):
    dest_owner_id: EntityId
    item_key: ItemKey | None = None
    family: Family | None = None
    source_kind: SourceKind = "plant"
    source_owner_id: EntityId | None = None
    supplier_code: Code | None = None
    priority: Annotated[int, Field(ge=1, le=99)] = 1
    quota_pct: Pct100 | None = None
    lane_id: EntityId | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    active: bool = True

    @model_validator(mode="after")
    def _check(self) -> "SourcingInput":
        if (self.item_key is None) == (self.family is None):
            raise ValueError("give exactly one of item_key and family")
        if self.source_kind == "plant":
            if self.source_owner_id is None or self.supplier_code is not None:
                raise ValueError("a plant source needs source_owner_id (and no supplier_code)")
            if self.source_owner_id == self.dest_owner_id:
                raise ValueError("a node cannot source from itself")
        elif self.supplier_code is None or self.source_owner_id is not None or self.lane_id is not None:
            raise ValueError("a supplier source needs supplier_code (and no source_owner_id / lane_id)")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not be before valid_from")
        return self


class SourcingRecord(SourcingInput):
    id: EntityId
    row_version: int
    updated_at: datetime


class ResolveSource(MfgModel):
    rule_id: EntityId
    source_kind: SourceKind
    source_owner_id: EntityId | None
    supplier_code: str | None
    priority: int
    quota_pct: float | None
    lane_id: EntityId | None
    transit_days: int | None


class ResolveResult(MfgModel):
    dest_owner_id: EntityId
    key: str
    date: date
    family: str | None
    matched_by: Literal["item", "family"] | None
    mode: Literal["quota", "priority", "none"]
    sources: list[ResolveSource]
    warnings: list[str] = Field(default_factory=list)


class RampPoint(MfgModel):
    week: Annotated[float, Field(ge=0, le=520)]
    rate_pct: Pct100
    yield_pct: Pct100


def check_points(points: list[RampPoint]) -> list[RampPoint]:
    weeks = [p.week for p in points]
    if any(b <= a for a, b in zip(weeks, weeks[1:])):
        raise ValueError("curve weeks must be strictly ascending")
    return points


class RampCurve(MfgModel):
    code: Code
    name: Name
    points: Annotated[list[RampPoint], Field(min_length=1, max_length=60)]

    @model_validator(mode="after")
    def _asc(self) -> "RampCurve":
        check_points(self.points)
        return self


class RampCurvesInput(MfgModel):            # PUT /net/ramp-curves (list replace)
    curves: Annotated[list[RampCurve], Field(max_length=200)]


# ---------------------------------------------------------------- runs (5; N8-N15)

class NetParams(MfgModel):                   # POST /net/runs; None = network planning_settings
    as_of: date | None = None
    horizon_weeks: Annotated[int, Field(ge=1, le=52)] | None = None
    constrained: bool | None = None
    prebuild_weeks: Annotated[int, Field(ge=0, le=12)] | None = None
    firm_days: Annotated[int, Field(ge=0, le=60)] | None = None
    node_ids: Annotated[list[EntityId], Field(max_length=50)] | None = None
    forecast_versions: dict[EntityId, EntityId] | None = None
    label: Label = ""


class NetKpis(MfgModel):
    fill_rate: float | None
    shortage_units: float
    inventory_value: float | None
    transfer_units: float
    currency: str


class NetRunSummary(NetKpis):
    nodes: int
    keys: int
    transfers: int
    firm_transfers: int
    shortages: int
    max_utilisation: float | None


class PublishTo(MfgModel):
    to_id: EntityId
    number: str
    src_owner_id: EntityId
    dst_owner_id: EntityId
    ship_date: date
    lines: int
    qty: float


class NetPublishResult(MfgModel):
    created: list[PublishTo] = Field(default_factory=list)
    kept: list[PublishTo] = Field(default_factory=list)
    cancelled: list[PublishTo] = Field(default_factory=list)
    network_demands: int = 0
    network_supplies: int = 0
    warnings: list[Explanation] = Field(default_factory=list)


class NetRunRecord(MfgModel):
    id: EntityId
    number: str
    label: str = ""
    status: RunStatus
    as_of: date
    params: dict[str, Any]
    input_hash: str | None
    summary: NetRunSummary | None
    validator: ValidatorReport | None
    explanations: list[Explanation] = Field(default_factory=list)
    published: bool
    published_at: datetime | None
    published_by: str | None
    publish_result: NetPublishResult | None = None
    error: str | None
    actor_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


class PegRecord(MfgModel):
    node: str
    kind: PegKind
    ref: str
    qty: float


class GridCell(MfgModel):
    week: date
    gross: float
    receipts: float
    planned_in: float
    planned_out: float
    projected: float
    ss: float


class GridRow(MfgModel):
    node_owner_id: EntityId
    item_key: str
    item_id: EntityId | None
    description: str | None
    family: str | None
    uom: str
    cells: list[GridCell]


class GridPage(MfgModel):
    items: list[GridRow]
    total: int
    limit: int
    offset: int
    weeks: list[date]


class TransferRecord(MfgModel):
    id: EntityId
    src_owner_id: EntityId
    dst_owner_id: EntityId
    item_key: str
    lane_id: EntityId | None
    ship_date: date
    receive_date: date
    qty: float
    uom: str
    firm: bool
    to_id: EntityId | None
    to_number: str | None
    pegs: list[PegRecord]


class ShortageRecord(MfgModel):
    id: EntityId
    node_owner_id: EntityId
    item_key: str
    week: date
    qty: float
    uom: str
    cause: ShortageCause
    detail: dict[str, Any]


class UtilisationRecord(MfgModel):
    node: EntityId
    cap_group: str
    week: date
    available: float
    used: float


class PegNode(MfgModel):
    id: str
    kind: Literal["demand", "transfer", "production", "purchase", "supply", "component", "shortage"]
    node_owner_id: EntityId
    item_key: str
    week: date | None
    qty: float
    ref: str | None
    cause: str | None = None
    link: str | None = None
    children: list["PegNode"] = Field(default_factory=list)


class PeggingResult(MfgModel):
    direction: Literal["down", "up"]
    root: PegNode


class NetworkCreated(MfgModel):              # O1
    owner_id: EntityId
    code: str
    name: str


# ---------------------------------------------------------------- pure engine input / output (5.1)

@dataclass(frozen=True)
class NetNode:
    id: str
    code: str
    kind: str                                 # plant | dc
    country: str | None = None
    currency: str = "USD"
    tz: str = "UTC"
    workdays: tuple[int, ...] = (0, 1, 2, 3, 4)   # weekday numbers worked (source calendar for transit)
    holidays: frozenset[date] = frozenset()


@dataclass(frozen=True)
class NetItem:
    node: str
    key: str
    item_id: str
    family: str | None = None
    uom: str = "EA"
    std_cost: float = 0.0
    ss: float = 0.0
    lead_days: int = 0                        # make / buy lead time (calendar days)
    make_buy: str = "make"
    order_multiple: float = 0.0
    min_qty: float = 0.0
    replenishment: str = "mrp"


@dataclass(frozen=True)
class NetDemand:
    node: str
    key: str
    week: date
    qty: float
    kind: str                                 # order | forecast | transfer_open
    ref: str
    priority: int = 5


@dataclass(frozen=True)
class NetSupply:
    node: str
    key: str
    week: date
    qty: float
    kind: str                                 # stock | po | wo | rate | transfer_in
    ref: str


@dataclass(frozen=True)
class NetRule:
    id: str
    dest: str
    key: str | None
    family: str | None
    source_kind: str                          # plant | supplier
    source: str | None                        # source node id
    supplier_code: str | None
    priority: int
    quota_pct: float | None
    lane_id: str | None
    valid_from: date | None = None
    valid_to: date | None = None


@dataclass(frozen=True)
class NetLane:
    id: str
    src: str
    dst: str
    mode: str
    transit_days: int
    freight_per_unit: float = 0.0
    active: bool = True


@dataclass(frozen=True)
class NetBomLine:
    node: str
    parent_key: str
    component_key: str
    qty_per: float


@dataclass(frozen=True)
class NetCap:
    node: str
    cap_group: str
    week: date
    hours: float


@dataclass(frozen=True)
class NetLoad:
    node: str
    cap_group: str
    key: str
    hours_per_unit: float


@dataclass(frozen=True)
class NetProblem:
    as_of: date
    horizon_weeks: int
    constrained: bool
    prebuild_weeks: int
    firm_days: int
    nodes: list[NetNode]
    items: list[NetItem]
    demand: list[NetDemand] = field(default_factory=list)
    supply: list[NetSupply] = field(default_factory=list)
    rules: list[NetRule] = field(default_factory=list)
    lanes: list[NetLane] = field(default_factory=list)
    bom: list[NetBomLine] = field(default_factory=list)
    capacity: list[NetCap] = field(default_factory=list)
    load: list[NetLoad] = field(default_factory=list)
    currency: str = "USD"
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class NetPeg:
    node: str
    kind: str                                 # order | forecast | ss | dependent | transfer
    ref: str
    qty: float
    late_weeks: int = 0


@dataclass
class NetTransfer:
    src: str
    dst: str
    key: str
    lane_id: str | None
    ship_date: date
    receive_date: date
    qty: float
    firm: bool
    rule_id: str | None = None
    pegs: list[NetPeg] = field(default_factory=list)
    requested: float = 0.0                    # quantity before capacity cuts at the source
    spill: bool = False                       # created by a capacity spill (3c), exempt from the quota check


@dataclass
class NetProduction:
    node: str
    key: str
    week: date
    qty: float
    kind: str                                 # make | buy
    cap_group: str | None = None
    hours: float = 0.0
    prebuilt_from: date | None = None
    supplier_code: str | None = None
    pegs: list[NetPeg] = field(default_factory=list)


@dataclass
class NetShortage:
    node: str
    key: str
    week: date
    qty: float
    cause: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class NetProjection:
    node: str
    key: str
    week: date
    gross: float
    receipts: float
    planned_in: float
    planned_out: float
    projected: float
    ss: float


@dataclass
class NetUtil:
    node: str
    cap_group: str
    week: date
    available: float
    used: float


@dataclass
class NetResult:
    weeks: list[date]
    transfers: list[NetTransfer] = field(default_factory=list)
    production: list[NetProduction] = field(default_factory=list)
    shortages: list[NetShortage] = field(default_factory=list)
    projection: list[NetProjection] = field(default_factory=list)
    utilisation: list[NetUtil] = field(default_factory=list)
    kpis: dict[str, Any] = field(default_factory=dict)
    explanations: list[dict[str, Any]] = field(default_factory=list)
    validator: dict[str, Any] = field(default_factory=dict)


class NetError(Exception):
    """A network problem the engine refuses (422): `NET_CYCLE`, `NET_QUOTA_SUM`, `NET_NO_LANE`."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}
