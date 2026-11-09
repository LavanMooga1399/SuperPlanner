"""M6 mfg contract (M6-DESIGN 2, 3; frozen at S0): dashboards, thresholds, digests, approvals inbox, downtime ack."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from .model import MfgModel

Period = Literal["4w", "13w", "52w"]
TileStatus = Literal["ok", "watch", "alert", "n/a"]
TILE_NAMES: tuple[str, ...] = ("otd", "backlog", "material_risk", "execution", "inventory", "late_pos", "quality",
                               "integration")
#: 3.1 defaults (fractions); per plant `dashboard_thresholds` overrides keys
DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "otd": {"alert_below": 0.85, "watch_below": 0.95},
    "adherence": {"alert_below": 0.70, "watch_below": 0.85},
    "fpy": {"alert_below": 0.95, "watch_below": 0.98},
    "backlog_load": {"watch_above": 0.90, "alert_above": 1.10},
    "material_risk": {"watch_above": 1, "alert_above": 10},
    "late_pos": {"watch_above": 1, "alert_above": 10},
}


class Threshold(MfgModel):
    alert_below: Annotated[float, Field(ge=0, le=1_000_000)] | None = None
    watch_below: Annotated[float, Field(ge=0, le=1_000_000)] | None = None
    watch_above: Annotated[float, Field(ge=0, le=1_000_000)] | None = None
    alert_above: Annotated[float, Field(ge=0, le=1_000_000)] | None = None


class ThresholdsInput(MfgModel):
    """D7 body: keys of DEFAULT_THRESHOLDS; omitted keys keep the defaults."""
    thresholds: dict[Literal["otd", "adherence", "fpy", "backlog_load", "material_risk", "late_pos"], Threshold]


class Drill(MfgModel):
    label: str
    path: str                                  # internal UI path, e.g. /mfg/kpis?from=..


class Tile(MfgModel):
    value: float | int | None = None
    unit: str = ""                             # "%", "h", "count", currency code, "turns"
    trend: list[dict[str, Any]] = Field(default_factory=list)      # [{period, value}]
    status: TileStatus = "ok"
    thresholds: dict[str, Any] = Field(default_factory=dict)
    drill: list[Drill] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)          # tile specific breakdown
    note: str = ""


class Dashboard(MfgModel):
    as_of: datetime
    period: Period
    plant: dict[str, Any]                      # {owner_id, name, currency, time_zone}
    tiles: dict[str, Tile]
    source: Literal["primary", "replica"] = "primary"
    computed_ms: int = 0
    timings_ms: dict[str, int] = Field(default_factory=dict)


class OrgDashboardPlant(MfgModel):
    plant: dict[str, Any]                      # {owner_id, code, name}
    tiles: dict[str, Tile]


class OrgDashboard(MfgModel):
    as_of: datetime
    period: Period
    org: dict[str, Any]
    plants: list[OrgDashboardPlant]
    totals: dict[str, Tile]                    # sums / weighted averages (`details.weights` states the weights)
    computed_ms: int = 0


class DigestInput(MfgModel):
    scope: Literal["plant", "org"]
    scope_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    frequency: Literal["daily", "weekly"] = "daily"
    local_time: Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")] = "07:00"
    weekday: Annotated[int, Field(ge=0, le=6)] | None = None      # 0 = Monday; weekly only (default Monday)

    @model_validator(mode="after")
    def _weekday(self) -> "DigestInput":
        if self.frequency == "daily" and self.weekday is not None:
            raise ValueError("weekday is only for weekly digests")
        return self


class DigestRecord(MfgModel):
    id: str
    scope: Literal["plant", "org"]
    scope_id: str
    scope_label: str = ""
    frequency: Literal["daily", "weekly"]
    local_time: str
    weekday: int | None = None
    time_zone: str
    created_at: datetime
    last_sent_at: datetime | None = None


class ApprovalItem(MfgModel):
    kind: Literal["pr", "eco", "replan_proposal", "overtime"]
    id: str
    number: str = ""                           # PR / CR number, run no
    title: str
    summary: str = ""
    waiting_since: datetime | None = None
    permission: str                            # pr_approve / eco_approve / schedule_publish / schedule_run
    row_version: int | None = None             # If-Match for the action
    actions: list[dict[str, Any]] = Field(default_factory=list)   # [{label, method, path, body}]
    link: str = ""


class Approvals(MfgModel):
    items: list[ApprovalItem]
    counts: dict[str, int]


class DowntimeAck(MfgModel):
    """M4 body (optional): offline replays carry the client id (idempotent)."""
    client_id: Annotated[str, StringConstraints(max_length=64)] | None = None


class InventorySnapshotRow(MfgModel):
    day: date
    item_family: str
    location_kind: str
    qty_value: float
    items: int
