"""Trade contract (M9-DESIGN 8; frozen at S0): item trade data, tariff / FX / milestone / country-risk tables (T1-T4),
tariff-milestone reports (T5-T6), lot content (T7, P4), landed cost (P2) and supplier risk (T8, P3)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from ..model import Code, EntityId, MfgModel, Name

Ccy = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{3}$")]
Country = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{2}$")]
CooOrAny = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^([A-Z]{2}|\*)$")]
Hts = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6,10}$")]
HtsPrefix = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{2,10}$")]
Layer = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9_]{1,16}$")]
MaterialClass = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[a-z0-9_\-]{1,16}$")]
CooSource = Literal["receipt", "supplier", "item", "plant", "transfer"]
Incoterm = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{3}$")]
Note = Annotated[str, StringConstraints(max_length=500)]
MilestoneStatus = Literal["met", "at_risk", "missed"]


def month_start(d: date) -> date:
    return d.replace(day=1)


# ---------------------------------------------------------------- item trade (P1)

class ItemTradeInput(MfgModel):
    hts_code: Hts | None = None
    coo: Country | None = None
    material_class: MaterialClass | None = None
    unit_weight_kg: Annotated[float, Field(ge=0, le=100_000)] | None = None


class LotCooInput(MfgModel):
    """PUT /lots/{id}/coo (8.1): a regulated correction of a received lot's country of origin."""
    coo: Country | None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ItemTradeRecord(ItemTradeInput):
    item_id: EntityId
    row_version: int


# ---------------------------------------------------------------- tables (T1-T4)

class TariffRateInput(MfgModel):
    dest_country: Country
    hts_prefix: HtsPrefix
    coo: CooOrAny = "*"
    layer: Layer = "mfn"
    rate_pct: Annotated[float, Field(ge=0, le=1000)] = 0.0
    per_unit: Annotated[float, Field(ge=0, le=1_000_000)] | None = None
    per_unit_currency: Ccy | None = None
    valid_from: date
    valid_to: date | None = None
    note: Note = ""

    @model_validator(mode="after")
    def _check(self) -> "TariffRateInput":
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not be before valid_from")
        if self.per_unit is not None and self.per_unit_currency is None:
            raise ValueError("per_unit needs per_unit_currency")
        return self


class TariffRateRecord(TariffRateInput):
    id: EntityId


class TariffsInput(MfgModel):              # PUT /trade/tariffs: bulk upsert by (dest, prefix, coo, layer, valid_from)
    rows: Annotated[list[TariffRateInput], Field(max_length=20_000)]
    replace: bool = False                  # True = rows not given are deleted


class FxRateInput(MfgModel):
    from_ccy: Ccy
    to_ccy: Ccy
    month: date
    rate: Annotated[float, Field(gt=0, le=1_000_000)]
    source: Annotated[str, StringConstraints(max_length=16)] = "manual"

    @model_validator(mode="after")
    def _check(self) -> "FxRateInput":
        if self.from_ccy == self.to_ccy:
            raise ValueError("from_ccy and to_ccy differ")
        if self.month.day != 1:
            raise ValueError("month is the 1st of a month")
        return self


class FxRateRecord(FxRateInput):
    id: EntityId


class FxInput(MfgModel):                   # PUT /trade/fx: upsert by (from, to, month)
    rows: Annotated[list[FxRateInput], Field(max_length=20_000)]
    replace: bool = False


class MilestoneRule(MfgModel):
    domestic_country: Country = "US"
    basis: Literal["value", "weight"] = "value"
    material_classes: Annotated[list[MaterialClass], Field(max_length=20)] = Field(default_factory=list)
    include_conversion: bool = False
    min_pct: Annotated[float, Field(ge=0, le=100)] = 0.0

    @model_validator(mode="after")
    def _check(self) -> "MilestoneRule":
        if self.include_conversion and self.basis != "value":
            raise ValueError("include_conversion needs the value basis")
        return self


class MilestoneInput(MfgModel):
    code: Code
    name: Name
    dest_country: Country
    family: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)] | None = None
    hts_prefix: HtsPrefix | None = None
    rule: MilestoneRule
    effective: date
    note: Note = ""

    @model_validator(mode="after")
    def _scope(self) -> "MilestoneInput":
        if self.family is None and self.hts_prefix is None:
            raise ValueError("a milestone needs a family or an HTS prefix")
        return self


class MilestoneRecord(MilestoneInput):
    id: EntityId


class MilestonesInput(MfgModel):           # PUT /trade/milestones: list replace by code
    rows: Annotated[list[MilestoneInput], Field(max_length=500)]


class CountryRiskInput(MfgModel):
    country: Country
    score: Annotated[int, Field(ge=0, le=25)]
    note: Note = ""


class CountryRiskRecord(CountryRiskInput):
    id: EntityId


class CountryRiskListInput(MfgModel):      # PUT /trade/country-risk: list replace
    rows: Annotated[list[CountryRiskInput], Field(max_length=300)]


class BulkResult(MfgModel):
    inserted: int
    updated: int
    deleted: int


# ---------------------------------------------------------------- reports (T5-T6)

class ProjectionInput(MfgModel):
    scenario_id: EntityId | None = None


class ReportInput(MfgModel):
    milestone_ids: Annotated[list[EntityId], Field(min_length=1, max_length=20)]
    from_: date = Field(alias="from")
    to: date
    nodes: Annotated[list[EntityId], Field(max_length=50)] | None = None
    group_by: Literal["family", "item"] = "family"
    projection: ProjectionInput | None = None

    model_config = {"extra": "forbid", "populate_by_name": True}

    @model_validator(mode="after")
    def _range(self) -> "ReportInput":
        if self.to < self.from_:
            raise ValueError("to must not be before from")
        if (self.to.year - self.from_.year) * 12 + self.to.month - self.from_.month > 47:
            raise ValueError("at most 48 months")
        return self


class ReportCell(MfgModel):
    month: date
    share_pct: float | None
    status: MilestoneStatus | None
    projected: bool
    lots: int
    lots_below: int
    qty_below_pct: float | None
    estimated_pct: float | None


class ReportLot(MfgModel):
    plant_owner_id: EntityId
    lot_id: EntityId
    lot_code: str
    item_key: str
    month: date
    qty: float
    share_pct: float | None
    estimated: bool


class ReportGroup(MfgModel):
    key: str
    label: str
    cells: list[ReportCell]


class ReportMilestone(MfgModel):
    milestone_id: EntityId
    code: str
    name: str
    min_pct: float
    effective: date
    basis: Literal["value", "weight"]
    groups: list[ReportGroup]
    first_missed_month: date | None
    lots_below: list[ReportLot]


class ReportResult(MfgModel):
    months: list[date]
    projection_from: date | None
    projection_source: str | None
    milestones: list[ReportMilestone]


class ReportRecord(MfgModel):
    id: EntityId
    number: str
    params: dict[str, Any]
    status: Literal["queued", "running", "completed", "failed"]
    result: ReportResult | None
    error: str | None
    actor_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------- lot content (T7, P4)

class ContentNode(MfgModel):
    kind: Literal["made", "bought", "possible", "conversion"]
    lot_id: EntityId | None
    lot_code: str | None
    item_key: str
    description: str | None
    coo: str | None
    material_class: str | None
    qty: float
    uom: str
    value: float | None
    weight_kg: float | None
    domestic: float | None
    estimated: bool
    children: list["ContentNode"] = Field(default_factory=list)


class LotContentRecord(MfgModel):
    lot_id: EntityId
    lot_code: str
    item_key: str
    coo: str | None
    coo_source: CooSource | None
    share_value: float | None
    share_weight: float | None
    estimated: bool
    computed_at: datetime | None
    milestone_id: EntityId | None
    currency: str
    tree: ContentNode


# ---------------------------------------------------------------- landed cost (P2) and risk (T8, P3)

class DutyLayer(MfgModel):
    layer: str
    rate_pct: float
    per_unit: float | None
    amount: float


class LandedCost(MfgModel):
    """8.4, per base unit in plant currency; `total` (and the parts that need FX) null when FX is missing."""
    unit_price: float | None
    freight: float
    customs_value: float | None
    duty: list[DutyLayer]
    other: float | None
    total: float | None
    currency: str
    fx_rate: float | None
    flags: list[str] = Field(default_factory=list)


class LandedRow(MfgModel):
    item_supplier_id: EntityId
    supplier_code: str
    supplier_name: str
    coo: str | None
    hts_code: str | None
    incoterm: str | None
    preferred: bool
    landed: LandedCost


class RiskSuggestion(MfgModel):
    supplier_code: str
    supplier_name: str
    node_owner_id: EntityId
    coo: str | None
    landed_delta: float | None
    score: float | None
    basis: Literal["family", "heading"]


class RiskParts(MfgModel):
    single_source: int
    country: int
    lead_time: int
    otd: int
    tariff: int


class RiskRow(MfgModel):
    node_owner_id: EntityId
    item_id: EntityId
    item_key: str
    part_number: str
    description: str
    family: str | None
    supplier_code: str
    supplier_name: str
    coo: str | None
    score: int
    parts: RiskParts
    flags: list[Literal["single_source", "sole_country"]]
    spend_12m: float
    currency: str
    otd_pct: float | None
    lead_days: int | None
    duty_pct: float | None
    suggestions: list[RiskSuggestion] = Field(default_factory=list)


class MpsTargetRecord(MfgModel):           # P5
    id: EntityId
    cycle_id: str
    cycle_number: str | None
    family: str
    month: date
    qty_target: float
    hours: dict[str, float]
    actual_qty: float
    attainment: float | None
