"""M8 shared contract (M8-DESIGN 3, 4.6, 6.2, 9, 10, 11; frozen at S0): planning settings, item planning and
packaging, line rates and the changeover matrix, flow/sterilisation line fields, kanban loops and cards, SAP
settings, validation baselines. Domain contracts live in `mfg/{forecast,invopt,rate,ster}/model.py`."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from .model import Code, EntityId, MfgModel

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Replenishment = Literal["mrp", "rate", "kanban"]
PackLevel = Literal["each", "inner", "case", "pallet"]
PACK_LEVELS: tuple[str, ...] = ("each", "inner", "case", "pallet")
LinePlanning = Literal["discrete", "flow", "sterilisation"]
ReleaseMode = Literal["none", "bi", "parametric"]
ChangeoverKind = Literal["changeover", "cleaning", "clearance"]
Key = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^(\*|[A-Za-z0-9][A-Za-z0-9_.\-/]{0,31})$")]
Hours = Annotated[float, Field(ge=0, le=10_000)]

DEFAULT_SL_MATRIX: dict[str, float] = {"AX": 0.99, "AY": 0.98, "AZ": 0.95, "BX": 0.98, "BY": 0.97, "BZ": 0.95,
                                       "CX": 0.97, "CY": 0.95, "CZ": 0.90}


#: M8-DESIGN 12: dashboard tiles added to the M6 plant dashboard (not part of the organisation totals)
M8_TILE_NAMES: tuple[str, ...] = ("forecast_accuracy", "rate_shortages", "ster_release")


# ---------------------------------------------------------------- planning settings (4.6)

class PlanningSettings(MfgModel):
    forecast_bucket: Literal["m", "w"] = "m"
    horizon_periods: Annotated[int, Field(ge=1, le=156)] = 18
    history_basis: Literal["shipments", "orders"] = "shipments"
    outlier_clean: bool = True
    consume_back_days: Annotated[int, Field(ge=0, le=365)] = 30
    consume_fwd_days: Annotated[int, Field(ge=0, le=365)] = 30
    forecast_priority: Annotated[int, Field(ge=1, le=9)] = 7
    daily_days: Annotated[int, Field(ge=0, le=365)] = 28
    weekly_weeks: Annotated[int, Field(ge=0, le=104)] = 26
    abc_cutoffs: Annotated[list[Annotated[float, Field(gt=0, lt=1)]], Field(min_length=2, max_length=2)] = \
        Field(default_factory=lambda: [0.8, 0.95])
    xyz_cutoffs: Annotated[list[Annotated[float, Field(gt=0, le=10)]], Field(min_length=2, max_length=2)] = \
        Field(default_factory=lambda: [0.5, 1.0])
    sl_matrix: dict[Annotated[str, StringConstraints(pattern=r"^[ABC][XYZ]$")],
                    Annotated[float, Field(gt=0.5, lt=1)]] = Field(default_factory=lambda: dict(DEFAULT_SL_MATRIX))
    ss_max_cover_days: Annotated[int, Field(ge=0, le=730)] = 60
    rate_horizon_days: Annotated[int, Field(ge=7, le=60)] = 30
    rate_firm_days: Annotated[int, Field(ge=0, le=30)] = 3
    rate_wo_split: Literal["day", "campaign"] = "day"
    rate_time_budget_s: Annotated[int, Field(ge=10, le=900)] = 240
    ster_max_wait_hours: Annotated[float, Field(ge=0, le=720)] = 8
    nightly_at: Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] = "02:00"
    nightly_enabled: bool = False
    auto_publish: bool = False

    @model_validator(mode="after")
    def _cutoffs(self) -> "PlanningSettings":
        if not self.abc_cutoffs[0] < self.abc_cutoffs[1]:
            raise ValueError("abc_cutoffs must be increasing")
        if not self.xyz_cutoffs[0] < self.xyz_cutoffs[1]:
            raise ValueError("xyz_cutoffs must be increasing")
        missing = {a + x for a in "ABC" for x in "XYZ"} - set(self.sl_matrix)
        if missing:
            raise ValueError(f"sl_matrix needs every class ({', '.join(sorted(missing))} missing)")
        return self


class PlanningSettingsRecord(PlanningSettings):
    row_version: int


# ---------------------------------------------------------------- item planning, packaging (3)

class ItemPlanningInput(MfgModel):
    replenishment: Replenishment = "mrp"
    forecast: bool = False
    like_item_id: EntityId | None = None
    like_factor: Annotated[float, Field(gt=0, le=100)] = 1.0
    service_level: Annotated[float, Field(gt=0.5, lt=1)] | None = None
    order_pack_level: PackLevel | None = None
    campaign_key: Code | None = None
    campaign_min_hours: Hours = 0
    campaign_max_hours: Annotated[float, Field(gt=0, le=10_000)] | None = None
    target_cover_days: Annotated[int, Field(ge=0, le=365)] = 10
    ster_cycle_code: Code | None = None
    aeration_hours: Hours | None = None
    release_mode: ReleaseMode = "none"
    release_days: Annotated[float, Field(ge=0, le=90)] = 0
    post_days: Annotated[int, Field(ge=0, le=365)] | None = None

    @model_validator(mode="after")
    def _check(self) -> "ItemPlanningInput":
        if self.campaign_max_hours is not None and self.campaign_max_hours < self.campaign_min_hours:
            raise ValueError("campaign_max_hours must not be less than campaign_min_hours")
        return self


class ItemPlanningRecord(ItemPlanningInput):
    id: str | None                       # None until first saved (defaults shown)
    item_id: str
    abc: Literal["A", "B", "C"] | None = None
    xyz: Literal["X", "Y", "Z"] | None = None
    row_version: int


class PackagingLevelInput(MfgModel):
    level: PackLevel
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    qty_base: Annotated[float, Field(gt=0, le=100_000_000)]
    gtin: Annotated[str, StringConstraints(pattern=r"^[0-9]{8,14}$")] | None = None
    weight_kg: Annotated[float, Field(ge=0, le=100_000)] | None = None


class PackagingInput(MfgModel):
    """PUT /items/{id}/packaging: the full level list (replaces). Strictly increasing by level order, each an
    integer multiple of the previous level."""
    levels: Annotated[list[PackagingLevelInput], Field(max_length=4)]

    @model_validator(mode="after")
    def _check(self) -> "PackagingInput":
        seen = [lv.level for lv in self.levels]
        if len(set(seen)) != len(seen):
            raise ValueError("each packaging level may appear once")
        ordered = sorted(self.levels, key=lambda lv: PACK_LEVELS.index(lv.level))
        if [lv.level for lv in ordered] != seen:
            raise ValueError("levels must be listed in the order each, inner, case, pallet")
        prev = None
        for lv in ordered:
            if prev is not None:
                ratio = lv.qty_base / prev
                if lv.qty_base <= prev or abs(ratio - round(ratio)) > 1e-9:
                    raise ValueError(f"{lv.level} qty_base must be a larger integer multiple of the previous level")
            prev = lv.qty_base
        return self


class PackagingLevelRecord(PackagingLevelInput):
    id: str
    seq: int


class PackagingRecord(MfgModel):
    item_id: str
    levels: list[PackagingLevelRecord]
    row_version: int                     # item planning row version (If-Match for PUT)


# ---------------------------------------------------------------- line rates, changeover matrix (3, 7)

class LineRateInput(MfgModel):
    item_id: EntityId | None = None
    item_family: Code | None = None
    units_per_hour: Annotated[float, Field(gt=0, le=10_000_000)]
    oee: Annotated[float, Field(gt=0, le=1)] | None = None

    @model_validator(mode="after")
    def _one(self) -> "LineRateInput":
        if (self.item_id is None) == (self.item_family is None):
            raise ValueError("exactly one of item_id and item_family is required")
        return self


class LinePlanningInput(MfgModel):
    """Line planning fields (PUT /lines/{id}/rates `line`)."""
    planning: LinePlanning = "discrete"
    oee: Annotated[float, Field(gt=0, le=1)] = 0.85
    clearance_minutes: Annotated[int, Field(ge=0, le=10_000)] = 0
    clean_every_hours: Annotated[float, Field(gt=0, le=10_000)] | None = None
    clean_minutes: Annotated[int, Field(ge=0, le=10_000)] | None = None
    chamber_pallets: Annotated[int, Field(ge=1, le=10_000)] | None = None
    cycle_hours: Annotated[float, Field(gt=0, le=1_000)] | None = None


class LineRatesInput(MfgModel):
    line: LinePlanningInput | None = None
    rates: Annotated[list[LineRateInput], Field(max_length=5_000)]


class LineRateRecord(LineRateInput):
    id: str


class LineRatesRecord(MfgModel):
    line_id: str
    line_code: str
    line: LinePlanningInput
    rates: list[LineRateRecord]
    row_version: int                     # the line's row version


class ChangeoverRowInput(MfgModel):
    line_setup_family: Code
    from_key: Key
    to_key: Key
    minutes: Annotated[int, Field(ge=0, le=100_000)]
    cost: Annotated[float, Field(ge=0, le=1_000_000_000)] = 0
    kind: ChangeoverKind = "changeover"


class ChangeoverMatrixInput(MfgModel):
    rows: Annotated[list[ChangeoverRowInput], Field(max_length=20_000)]

    @model_validator(mode="after")
    def _unique(self) -> "ChangeoverMatrixInput":
        keys = [(r.line_setup_family, r.from_key, r.to_key, r.kind) for r in self.rows]
        if len(set(keys)) != len(keys):
            raise ValueError("each (line_setup_family, from_key, to_key, kind) may appear once")
        return self


class ChangeoverRowRecord(ChangeoverRowInput):
    id: str


class ChangeoverMatrixRecord(MfgModel):
    rows: list[ChangeoverRowRecord]
    version: int                         # max row version (If-Match for PUT)


# ---------------------------------------------------------------- kanban (6.2)

KanbanSource = Literal["buy", "make"]
CardState = Literal["full", "empty", "in_process"]


class KanbanLoopInput(MfgModel):
    item_id: EntityId
    location_id: EntityId
    source: KanbanSource
    supplier_id: EntityId | None = None
    line_id: EntityId | None = None
    cards: Annotated[int, Field(ge=1, le=500)]
    container_qty: Annotated[float, Field(gt=0, le=10_000_000)]
    lead_time_days: Annotated[int, Field(ge=0, le=365)]
    trigger: Literal["scan", "consumption"] = "scan"
    status: Literal["active", "inactive"] = "active"


class KanbanCardRecord(MfgModel):
    id: str
    loop_id: str
    card_no: int
    code: str                            # KB:<card id>
    state: CardState
    doc_type: str | None = None          # pr | wo
    doc_id: str | None = None
    doc_number: str | None = None
    changed_at: datetime


class KanbanLoopRecord(KanbanLoopInput):
    id: str
    number: str
    item: dict[str, Any] | None = None
    location_code: str | None = None
    card_counts: dict[str, int]
    consumed_since_signal: float = 0
    sizing: dict[str, Any]               # {daily_demand, suggested_cards, undersized}
    row_version: int
    created_at: datetime
    updated_at: datetime


class KanbanScanInput(MfgModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=80)]


class KanbanScanResult(MfgModel):
    card: KanbanCardRecord
    loop_id: str
    signal: dict[str, Any] | None        # {doc_type, doc_id, number, qty}


# ---------------------------------------------------------------- nightly chain (6.1)

class NightlyRunResult(MfgModel):
    run_id: str
    status: str
    steps: list[dict[str, Any]]          # [{step, status, ref_id, error}]
    started_at: datetime | None = None


# ---------------------------------------------------------------- SAP settings (9)

SapEntity = Literal["product", "bom", "routing", "supplier", "info_record", "stock", "purchase_order",
                    "sales_order", "billing", "planned_order_out", "pr_out", "pir_out", "confirmation_out"]
SAP_IN_ENTITIES: tuple[str, ...] = ("product", "bom", "routing", "supplier", "info_record", "stock",
                                    "purchase_order", "sales_order", "billing")


class SapSettings(MfgModel):
    enabled: bool = False
    base_url: Annotated[str, StringConstraints(max_length=500)] = ""
    odata_version: Literal["v2", "v4"] = "v2"
    plant: Annotated[str, StringConstraints(max_length=8)] = ""
    auth: Literal["basic", "oauth2"] = "basic"
    username: Annotated[str, StringConstraints(max_length=200)] = ""
    password: Annotated[str, StringConstraints(max_length=500)] | None = None     # write-only (encrypted)
    token_url: Annotated[str, StringConstraints(max_length=500)] = ""
    client_id: Annotated[str, StringConstraints(max_length=200)] = ""
    client_secret: Annotated[str, StringConstraints(max_length=500)] | None = None  # write-only (encrypted)
    location_map: dict[Annotated[str, StringConstraints(max_length=8)], Code] = Field(default_factory=dict)
    unit_map: dict[Annotated[str, StringConstraints(max_length=8)], Annotated[str, StringConstraints(max_length=8)]] = \
        Field(default_factory=lambda: {"PCE": "EA", "ST": "EA", "KGM": "KG", "MTR": "M", "LTR": "L"})
    mrp_controllers: Annotated[list[Annotated[str, StringConstraints(max_length=8)]], Field(max_length=100)] = \
        Field(default_factory=list)
    strip_zeros: bool = True
    order_types: dict[str, Annotated[str, StringConstraints(max_length=8)]] = Field(
        default_factory=lambda: {"planned_order": "LA", "purchase_req": "NB", "sales_order": "OR"})
    page_size: Annotated[int, Field(ge=10, le=5_000)] = 2_000
    schedule: dict[SapEntity, Annotated[int, Field(ge=0, le=10_080)]] = Field(default_factory=dict)  # minutes


class SapSettingsRecord(SapSettings):
    password_set: bool = False
    client_secret_set: bool = False
    cursors: dict[str, str] = Field(default_factory=dict)     # entity -> LastChangeDateTime cursor
    last_sync: dict[str, Any] = Field(default_factory=dict)   # entity -> {at, status, records, error}
    row_version: int


class SapSyncInput(MfgModel):
    entities: Annotated[list[SapEntity], Field(min_length=1, max_length=13)]
    full: bool = False                    # ignore cursors


class SapSyncResult(MfgModel):
    run_id: str
    status: str
    entities: list[str]


# ---------------------------------------------------------------- validation kit (10)

class BaselineInput(MfgModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class BaselineRecord(MfgModel):
    id: str
    label: str
    sha256: str
    created_by: str
    created_at: datetime
    content: dict[str, Any] | None = None     # omitted in lists


class BaselineDiff(MfgModel):
    a: str
    b: str
    a_sha256: str
    b_sha256: str
    same: bool
    changes: list[dict[str, Any]]             # [{path, kind: added|removed|changed, a, b}]


class TraceMatrixInfo(MfgModel):
    generated_at: datetime | None
    requirements: int
    covered: int
    gaps: list[dict[str, Any]]                # [{id, title, risk}]
    high_risk_gaps: int
    rows: list[dict[str, Any]]                # [{id, title, risk, tests, last_result}]
    csv_url: str | None = None
