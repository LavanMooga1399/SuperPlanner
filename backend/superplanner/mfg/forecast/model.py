"""Forecast contract (M8-DESIGN 4; frozen at S0): history rows, run params and results, versions, lines,
overrides, the consumption output (`ForecastSnap`) fed to MRP, accuracy. Pure pydantic / dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from ..model import Code, EntityId, MfgModel, PlanDate
from ..model_m8 import Reason

Bucket = Literal["m", "w"]
Method = Literal["zero", "snaive", "ma", "ses", "holt_damped", "hw_add", "hw_mul", "croston", "sba"]
METHODS: tuple[str, ...] = ("zero", "snaive", "ma", "ses", "holt_damped", "hw_add", "hw_mul", "croston", "sba")
DemandClass = Literal["smooth", "erratic", "intermittent", "lumpy", "short"]
Flag = Literal["FC_OUTLIER", "FC_HISTORY_SHORT", "FC_HIGH_ERROR", "FC_LIKE_ITEM", "FC_OVERCONSUMED", "FC_NO_COST"]
VersionStatus = Literal["draft", "active", "archived"]
HistorySource = Literal["ledger", "import", "sap"]


# ---------------------------------------------------------------- history (4.1)

class HistoryRecord(MfgModel):
    id: str
    item_id: str
    period_start: date
    bucket: Bucket
    qty: float
    cleaned_qty: float | None
    source: HistorySource
    outlier: bool = False
    updated_at: datetime


class HistoryUpdate(MfgModel):
    """PUT /forecast/history/{id}: `cleaned_qty` None = reset to the raw value (planner restores an outlier)."""
    cleaned_qty: Annotated[float, Field(ge=0, le=1_000_000_000)] | None = None
    reason: Reason


class HistoryRefreshResult(MfgModel):
    rows_written: int
    items: int
    periods: int
    outliers: int


# ---------------------------------------------------------------- runs (4.2)

class ForecastParams(MfgModel):
    """POST /forecast/runs."""
    label: Annotated[str, StringConstraints(max_length=100)] = ""
    as_of: PlanDate | None = None                   # None = plant today; history up to the last closed period
    bucket: Bucket | None = None                    # None = planning_settings.forecast_bucket
    horizon_periods: Annotated[int, Field(ge=1, le=156)] | None = None
    item_ids: Annotated[list[EntityId], Field(max_length=20_000)] | None = None   # None = items with forecast true
    methods: list[Method] | None = None             # restrict candidates (None = all by class)
    create_version: bool = True                     # a draft version from the run


class ItemResult(MfgModel):
    item_id: str
    part_number: str | None = None
    demand_class: DemandClass
    adi: float | None
    cv2: float | None
    method: Method
    params: dict[str, float]
    holdout_wape: float | None
    bias: float | None
    rmse1: float
    mean: float                                     # mean period demand (history)
    n_periods: int
    abc: Literal["A", "B", "C"] | None = None
    flags: list[Flag]
    fitted_tail: list[float]                        # last 12 fitted values (aligned to history end)
    forecast: list[float]                           # horizon values from the first forecast period
    candidates: dict[str, float | None] = Field(default_factory=dict)   # method -> holdout WAPE


class ForecastRunRecord(MfgModel):
    id: str
    number: str
    params: dict[str, Any]
    status: Literal["queued", "running", "completed", "failed"]
    as_of: date
    bucket: Bucket
    first_period: date | None = None                # first forecast period
    item_count: int
    summary: dict[str, Any]                         # {wape, bias, by_abc: {A: {wape, bias, items}}, method_mix}
    version_id: str | None = None
    error: str | None = None
    started_at: datetime | None
    finished_at: datetime | None
    actor_id: str


class ForecastRunDetail(ForecastRunRecord):
    results: dict[str, Any]                         # page {items: [ItemResult], total, limit, offset}


# ---------------------------------------------------------------- versions, lines, overrides (4.3)

class VersionInput(MfgModel):
    """POST /forecast/versions: from a completed run (stat), optionally copying the active version's overrides."""
    run_id: EntityId
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    copy_overrides: bool = True
    note: Annotated[str, StringConstraints(max_length=500)] = ""


class VersionRecord(MfgModel):
    id: str
    number: str
    name: str
    run_id: str | None
    status: VersionStatus
    bucket: Bucket
    start: date
    periods: int
    item_count: int = 0
    total_stat: float = 0
    total_final: float = 0
    override_count: int = 0
    activated_by: str | None
    activated_at: datetime | None
    note: str
    row_version: int
    created_at: datetime
    updated_at: datetime


class LineRecord(MfgModel):
    item_id: str
    part_number: str | None = None
    family: str | None = None
    abc: str | None = None
    xyz: str | None = None
    method: str | None = None
    periods: list[date]
    stat: list[float]
    final: list[float]
    overridden: list[bool]
    # additive (UI request): item name and the latest run's backtest figures
    name: str | None = None
    holdout_wape: float | None = None
    bias: float | None = None
    flags: list[str] = Field(default_factory=list)


class OverrideInput(MfgModel):
    item_id: EntityId | None = None
    item_family: Code | None = None
    period_from: PlanDate
    period_to: PlanDate
    mode: Literal["abs", "pct"]
    value: Annotated[float, Field(ge=-100, le=1_000_000_000)]
    reason: Reason

    @model_validator(mode="after")
    def _check(self) -> "OverrideInput":
        if (self.item_id is None) == (self.item_family is None):
            raise ValueError("exactly one of item_id and item_family is required")
        if self.period_to < self.period_from:
            raise ValueError("period_to must not be before period_from")
        if self.mode == "abs" and self.value < 0:
            raise ValueError("an absolute override must not be negative")
        return self


class OverrideRecord(OverrideInput):
    id: str
    version_id: str
    seq: int
    created_by: str
    created_at: datetime
    removed_at: datetime | None = None
    changes: list[dict[str, Any]] = Field(default_factory=list)   # [{item_id, period_start, old, new}]


# ---------------------------------------------------------------- consumption -> MRP (4.4)

@dataclass(frozen=True, slots=True)
class ForecastSnap:
    """One time-zoned forecast requirement for MRP (after consumption)."""
    item_id: str
    date: date
    qty: float
    version_id: str
    period_start: date


class ConsumptionRow(MfgModel):
    item_id: str
    period_start: date
    forecast: float
    consumed: float
    open: float                                    # unconsumed (requirement) in the period, after as_of drop
    orders: float                                  # customer order qty due in the period
    overconsumed: float = 0


class ItemForecastView(MfgModel):
    """GET /forecast/items/{item_id} (F16)."""
    item: dict[str, Any]
    planning: dict[str, Any]
    history: list[HistoryRecord]
    result: ItemResult | None
    versions: list[dict[str, Any]]                 # [{version_id, number, status, periods, final}]
    consumption: list[ConsumptionRow]
    accuracy: dict[str, Any]


class AccuracyRow(MfgModel):
    key: str                                       # item id / family / ABC class / "all"
    label: str
    periods: int
    actual: float
    forecast: float
    wape: float | None
    bias: float | None


class AccuracyReport(MfgModel):
    lag: int                                       # 1 and 3 in the UI (any 1..12 accepted)
    group_by: Literal["item", "family", "abc", "all"]
    rows: list[AccuracyRow]
    backtest: dict[str, Any] | None = None         # latest run summary
    trend: list[dict[str, Any]] = Field(default_factory=list)   # [{period_start, actual, forecast, wape, bias}]
