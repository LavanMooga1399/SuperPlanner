"""Rate / campaign engine contract (M8-DESIGN 7.1; frozen at S0).

`RateParams` is the body of `POST /mfg/rate/runs`. `RateProblem` (lines, items, demands, firm blocks) is the pure
engine input built by `rate/build.py`; `RateResult` the pure output (blocks, shortages, objective, explanations,
validator). API records (`RateRunRecord`, `RateBlockRecord`, `RateGrid`) are what the routes answer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from ..model import EntityId, MfgModel

BlockKind = Literal["production", "changeover", "cleaning", "clearance", "down"]
BLOCK_KINDS: tuple[str, ...] = ("production", "changeover", "cleaning", "clearance", "down")
DemandSource = Literal["order", "forecast", "ss", "dependent"]
ShortageCause = Literal["RATE_CAPACITY", "RATE_NO_LINE", "RATE_MIN_CAMPAIGN", "RATE_CHANGEOVER_BOUND"]
RunStatus = Literal["queued", "running", "completed", "failed", "failed_validation"]


class RateParams(MfgModel):            # POST /mfg/rate/runs
    label: Annotated[str, StringConstraints(max_length=100)] = ""
    mrp_run_id: EntityId | None = None                      # None = latest live pass-1 run
    horizon_days: Annotated[int, Field(ge=7, le=60)] | None = None   # None = planning_settings
    line_ids: Annotated[list[EntityId], Field(max_length=500)] | None = None   # None = all flow lines
    overtime: Literal["off", "suggest", "allow"] = "suggest"
    time_budget_s: Annotated[int, Field(ge=10, le=900)] | None = None
    keep_firm: bool = True                                  # blocks of the published run inside firm zone fixed


# ---------------------------------------------------------------- engine input / output (pure)

@dataclass(frozen=True, slots=True)
class RateDemand:
    item_id: str
    due: date
    qty: float
    priority: int
    source: str                         # order | forecast | ss | dependent


@dataclass(frozen=True, slots=True)
class Window:
    start: datetime
    end: datetime
    overtime: bool = False


@dataclass(frozen=True, slots=True)
class ChangeoverRule:
    line_setup_family: str
    from_key: str
    to_key: str
    minutes: int
    cost: float
    kind: str                           # changeover | cleaning | clearance


@dataclass(frozen=True)
class RateLine:
    id: str
    code: str
    setup_family: str | None
    windows: tuple[Window, ...]
    rates: dict[str, float]             # item id -> effective units/hour (rate x OEE)
    clearance_minutes: int = 0
    clean_every_hours: float | None = None
    clean_minutes: int | None = None
    overtime_cost_per_hour: float = 0.0
    tz_offset_minutes: int = 0          # plant-local prod_date = (start + offset).date()


@dataclass(frozen=True)
class RateItem:
    id: str
    part_number: str
    key: str                            # campaign_key, else setup_family, else part number
    case_qty: float | None              # case qty_base (rounding), None = no rounding
    campaign_min_hours: float = 0.0
    campaign_max_hours: float | None = None
    target_cover_days: int = 10
    initial_stock: float = 0.0
    post_days: int = 0
    daily_demand: float = 0.0           # average demand per day over the horizon (cover)


@dataclass(slots=True)
class RateBlock:
    line_id: str
    kind: str
    item_id: str | None
    campaign_no: int
    start: datetime
    end: datetime
    qty: float = 0.0
    cases: int | None = None
    prod_date: date | None = None
    firm: bool = False
    wo_id: str | None = None


@dataclass(frozen=True)
class RateProblem:
    as_of: datetime                     # horizon start (UTC)
    horizon_end: datetime
    lines: tuple[RateLine, ...]
    items: dict[str, RateItem]
    demands: tuple[RateDemand, ...]
    changeovers: tuple[ChangeoverRule, ...] = ()
    firm_blocks: tuple[RateBlock, ...] = ()
    component_avail: dict[str, list[tuple[str, date]]] = field(default_factory=dict)  # item -> [(comp, avail)]
    time_budget_s: float = 60.0
    workers: int = 4
    #: firm blocks are already netted in the demands (their WOs are MRP supply): they add no supply
    firm_netted: bool = False


@dataclass
class Shortage:
    item_id: str
    due: date
    qty: float
    cause: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class RateResult:
    blocks: list[RateBlock]
    shortages: list[Shortage]
    objective: dict[str, float]         # shortage_unit_days, changeover_cost, changeover_hours,
                                        # excess_cover_unit_days, overtime_cost
    explanations: list[dict[str, Any]]  # [{code, severity, item_id, line_id, message, detail}]
    validator: dict[str, Any]           # {ok, violations: [{code, line_id, block_ix, detail}]}
    stats: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- API records

class RateRunRecord(MfgModel):
    id: str
    number: str
    label: str
    params: dict[str, Any]
    status: RunStatus
    mrp_run_id: str | None
    as_of: date
    horizon_days: int
    published: bool
    published_at: datetime | None
    published_by: str | None
    objective: dict[str, Any] | None
    summary: dict[str, Any] | None      # {lines, blocks, campaigns, production_qty, shortage_qty, utilisation}
    explanations: list[dict[str, Any]] | None
    validator: dict[str, Any] | None
    shortages: list[dict[str, Any]] | None = None
    duration_ms: int | None
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class RateBlockRecord(MfgModel):
    id: str
    line_id: str
    line_code: str | None = None
    kind: BlockKind
    item_id: str | None
    part_number: str | None = None
    campaign_no: int
    start: datetime
    end: datetime
    qty: float
    cases: int | None
    prod_date: date
    wo_id: str | None


class RateGridCell(MfgModel):
    line_id: str
    bucket: str                         # ISO date or "YYYY-MM-DDTHH" shift start
    item_id: str | None
    part_number: str | None = None
    qty: float
    cases: int | None
    hours: float


class RateGrid(MfgModel):
    bucket: Literal["shift", "day"]
    buckets: list[str]
    lines: list[dict[str, Any]]         # [{line_id, code, utilisation: {bucket: pct}}]
    cells: list[RateGridCell]


class RateCompare(MfgModel):
    a: str
    b: str
    objective: dict[str, dict[str, float]]       # metric -> {a, b, delta}
    lines: list[dict[str, Any]]                  # [{line_id, code, a_qty, b_qty, a_changeovers, b_changeovers}]
    items: list[dict[str, Any]]                  # [{item_id, a_qty, b_qty, a_short, b_short}]


class PublishResult(MfgModel):
    run_id: str
    created_wo_ids: list[str]
    cancelled_wo_ids: list[str]
    kept_wo_ids: list[str]
    rate_supplies: int
