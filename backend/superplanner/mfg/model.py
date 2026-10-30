"""Manufacturing domain models (M1-DESIGN 3, 5, 7; contract frozen at milestone A1).

Two model kinds per entity: `<Entity>Input` (what POST/PUT accept) and `<Entity>Record` (Input fields + `id`,
`row_version`, `created_at`, `updated_at` + read-only denormalised fields). All models forbid extra fields.
Single-model rules are model validators (422 `VALIDATION_ERROR`); rules across lines/operations of a document live in
`release.validate_bom_document` / `validate_routing_document`, cross-entity rules in the services and the health
check. Records built from stored rows use `model_construct` (validated on write).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from pydantic import (AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints,
                      model_validator)

from .limits import MAX_ATTR_INT, MAX_BOM_LINES_PER_BOM, MAX_DATE, MAX_OPERATIONS_PER_ROUTING, MIN_DATE
from .units import UOM_CODES

# ---------------------------------------------------------------- common types (3.1)

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_CTRL_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")      # tab, LF, CR allowed in free text


def _no_ctrl(v: str) -> str:
    if _CTRL.search(v):
        raise ValueError("must not contain control characters")
    return v


def _no_ctrl_text(v: str) -> str:
    if _CTRL_TEXT.search(v):
        raise ValueError("must not contain control characters other than tab and line breaks")
    return v


EntityId = Annotated[str, StringConstraints(pattern=r"^[a-z]{3}_[0-9a-f]{32}$")]
Code = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,31}$")]
PartNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64,
                                              pattern=r"^[^\x00-\x1f\x7f]+$")]
Revision = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_.\-]{1,16}$")]
FindNumber = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_.\-]{1,16}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
                 AfterValidator(_no_ctrl)]
Text500 = Annotated[str, StringConstraints(max_length=500), AfterValidator(_no_ctrl_text)]
HHMM = Annotated[str, StringConstraints(pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UtcOffset = Annotated[str, StringConstraints(pattern=r"^[+-](0\d|1[0-4]):[0-5]\d$")]
ExtRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64,
                                          pattern=r"^[^\x00-\x1f\x7f]+$")]          # M2-DESIGN 3
Money = Annotated[float, Field(ge=0, le=1_000_000_000)]
Qty = Annotated[float, Field(gt=0, le=1_000_000)]
NonNegQty = Annotated[float, Field(ge=0, le=1_000_000_000)]
Minutes = Annotated[float, Field(ge=0, le=100_000)]
Pct = Annotated[float, Field(ge=0, lt=100)]
YieldPct = Annotated[float, Field(gt=0, le=100)]
Status = Literal["draft", "released", "obsolete"]
MakeBuy = Literal["make", "buy", "phantom"]
AttrValue = (Annotated[str, StringConstraints(max_length=500), AfterValidator(_no_ctrl_text)] | int
             | Annotated[float, Field(allow_inf_nan=False)] | bool)       # finite numbers only (NaN/inf -> 422)


def _attr_ints(v: Any) -> Any:
    # integers beyond 2**53 - 1 would silently become (rounded) floats in JSON / JavaScript
    if isinstance(v, dict):
        for k, x in v.items():
            if isinstance(x, int) and not isinstance(x, bool) and abs(x) > MAX_ATTR_INT:
                raise ValueError(f"attribute {k!r}: integers must be between -{MAX_ATTR_INT} and {MAX_ATTR_INT}")
    return v


Attributes = Annotated[dict[Code, AttrValue], Field(max_length=50), BeforeValidator(_attr_ints)]
Severity = Literal["error", "warning", "info"]


def _date_in_range(v: date) -> date:
    if not MIN_DATE <= v <= MAX_DATE:
        raise ValueError(f"must be between {MIN_DATE.isoformat()} and {MAX_DATE.isoformat()}")
    return v


def _datetime_in_range(v: datetime) -> datetime:
    # the local date first: converting an out-of-range value to UTC could itself overflow
    _date_in_range(v.date())
    _date_in_range(v.astimezone(UTC).date())
    return v


PlanDate = Annotated[date, AfterValidator(_date_in_range)]             # 1900-01-01 .. 2199-12-31
PlanDateTime = Annotated[AwareDatetime, AfterValidator(_datetime_in_range)]


def _short(max_len: int, min_len: int = 0) -> Any:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_len, max_length=max_len),
                     AfterValidator(_no_ctrl)]


WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ID_PREFIXES: dict[str, str] = {
    "item": "itm_", "bom": "bom_", "bom_line": "bml_", "routing": "rtg_", "operation": "opr_", "group": "wcg_",
    "line": "lin_", "shift_template": "sht_", "shift_assignment": "sha_", "calendar_exception": "cex_",
    "skill": "skl_", "operator": "emp_", "tool_pool": "tlp_", "import": "imp_", "plant": "plt_",
    # M2-DESIGN 3
    "location": "loc_", "supplier": "sup_", "item_supplier": "isu_", "lot": "lot_", "balance": "bal_",
    "posting": "pst_", "transaction": "txn_", "reservation": "rsv_", "purchase_doc": "pdc_", "purchase_line": "pln_",
    "purchase_schedule": "psc_", "demand_order": "dmo_", "demand_line": "dml_", "work_order": "wko_",
    "wo_component": "woc_", "number_series": "nsr_", "mrp_run": "mrr_", "planned_order": "mpo_",
    "mrp_exception": "mex_", "mrp_item_result": "mir_", "mrp_demand_result": "mdr_", "member": "mbr_",
}
ENUMS: dict[str, tuple[str, ...]] = {
    "make_buy": ("make", "buy", "phantom"), "lot_rule": ("lot_for_lot", "fixed", "period"),
    "status": ("draft", "released", "obsolete"), "run_per": ("unit", "panel", "batch"),
    "labor": ("attended", "unattended"), "assignment_kind": ("base", "optional"),
    "target_type": ("group", "line"), "exception_scope": ("plant", "group", "line"),
    "exception_kind": ("holiday", "shutdown", "maintenance"), "weekday": WEEKDAYS,
}


class MfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_uom(v: str | None) -> str | None:
    if v is not None and v not in UOM_CODES:
        raise ValueError(f"unknown unit of measure {v!r} (allowed: {', '.join(UOM_CODES)})")
    return v


UomCode = Annotated[str, AfterValidator(_check_uom)]


def _unique(values: list[Any], what: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{what} must be unique")


def _effectivity(m: Any) -> None:
    if m.effective_from is not None and m.effective_to is not None and not m.effective_from < m.effective_to:
        raise ValueError("effective_from must be before effective_to")
    if (m.serial_from is None) != (m.serial_to is None):
        raise ValueError("serial_from and serial_to must both be set or both be empty")
    if m.serial_from is not None and m.serial_from > m.serial_to:
        raise ValueError("serial_from must not be greater than serial_to")


# ---------------------------------------------------------------- refs

class ItemRef(MfgModel):
    id: str
    part_number: str
    revision: str
    description: str
    uom: str
    make_buy: MakeBuy
    active: bool


class Ref(MfgModel):
    """`{id, code, name}` reference to a group, skill, tool pool, shift template, ..."""
    id: str
    code: str
    name: str


class TargetRef(MfgModel):
    type: Literal["group", "line"]
    id: str
    code: str
    name: str


class EntityRef(MfgModel):
    type: str
    id: str | None
    label: str


class _Stamped(MfgModel):
    id: EntityId
    row_version: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- plant (3.3)

MRP_DEFAULT_WORKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat")


class PlantInput(MfgModel):
    name: Name = "Plant"
    utc_offset: UtcOffset = "+00:00"
    planning_horizon_days: Annotated[int, Field(ge=7, le=730)] = 90
    currency: _short(8) = ""
    attributes: Attributes = Field(default_factory=dict)
    # M2-DESIGN 3.1 (MRP)
    mrp_workdays: Annotated[list[Weekday], Field(min_length=1, max_length=7)] = \
        Field(default_factory=lambda: list(MRP_DEFAULT_WORKDAYS))
    mrp_day_minutes: Annotated[float, Field(ge=60, le=1440)] = 480
    mrp_defer_tolerance_days: Annotated[int, Field(ge=0, le=90)] = 7
    mrp_release_window_days: Annotated[int, Field(ge=0, le=90)] = 7
    over_receipt_pct: Annotated[float, Field(ge=0, le=100)] = 0
    # M3-DESIGN 3.1 (APS)
    time_zone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None = None
    aps_freeze_hours: Annotated[int, Field(ge=0, le=336)] = 48
    aps_horizon_days: Annotated[int, Field(ge=7, le=120)] = 42
    aps_overtime_policy: Literal["off", "suggest", "allow"] = "suggest"

    @model_validator(mode="after")
    def _workdays(self) -> "PlantInput":
        _unique(self.mrp_workdays, "mrp_workdays")
        return self   # time_zone: checked against the zone database by the plant service (422 MFG_TZ_INVALID)


class PlantRecord(PlantInput):
    id: EntityId | None = None            # None = unsaved default (nothing stored yet, ETag "0")
    row_version: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    data_version: int = 0


# ---------------------------------------------------------------- item (3.4)

class ItemInput(MfgModel):
    part_number: PartNumber
    revision: Revision = "A"
    description: Text500 = ""
    uom: UomCode = "EA"
    make_buy: MakeBuy
    family: Code | None = None
    setup_family: Code | None = None
    lead_time_days: Annotated[int, Field(ge=0, le=730)] | None = None
    receiving_days: Annotated[int, Field(ge=0, le=60)] = 0
    lot_rule: Literal["lot_for_lot", "fixed", "period"] = "lot_for_lot"
    fixed_lot_qty: Qty | None = None
    min_order_qty: NonNegQty = 0
    order_multiple: NonNegQty = 0
    safety_stock: NonNegQty = 0
    serialized: bool = False
    shelf_life_days: Annotated[int, Field(ge=1, le=36500)] | None = None
    handling_class: Code | None = None
    handling_note: Text500 = ""
    attributes: Attributes = Field(default_factory=dict)
    active: bool = True
    # M2-DESIGN 3.1
    external_ref: ExtRef | None = None
    standard_cost: Money | None = None
    lot_controlled: bool = False
    lot_period_days: Annotated[int, Field(ge=1, le=365)] | None = None

    @model_validator(mode="after")
    def _lot(self) -> "ItemInput":
        if (self.lot_rule == "fixed") != (self.fixed_lot_qty is not None):
            raise ValueError("fixed_lot_qty is required when lot_rule is 'fixed' and not allowed otherwise")
        if (self.lot_rule == "period") != (self.lot_period_days is not None):
            raise ValueError("lot_period_days is required when lot_rule is 'period' and not allowed otherwise")
        return self


class ItemRecord(ItemInput, _Stamped):
    has_bom: bool = False
    has_routing: bool = False
    used_in_count: int = 0


# ---------------------------------------------------------------- BOM (3.5)

class BomLineInput(MfgModel):
    id: EntityId | None = None
    find_number: FindNumber
    child_item_id: EntityId
    qty_per: Qty
    uom: UomCode | None = None              # None: the service fills in the child's uom
    scrap_pct: Pct = 0
    ref_designators: Annotated[str, StringConstraints(max_length=4000), AfterValidator(_no_ctrl_text)] = ""
    alt_group: FindNumber | None = None
    alt_priority: Annotated[int, Field(ge=1, le=99)] = 1
    operation_seq: Annotated[int, Field(ge=1, le=9999)] | None = None
    note: Text500 = ""


class BomInput(MfgModel):
    item_id: EntityId
    revision: Revision | None = None        # None: the item's revision at create
    version: Annotated[int, Field(ge=1, le=9999)] | None = None   # None: max for (item, revision) + 1
    effective_from: PlanDate | None = None
    effective_to: PlanDate | None = None
    serial_from: Annotated[int, Field(ge=1, le=1_000_000_000)] | None = None
    serial_to: Annotated[int, Field(ge=1, le=1_000_000_000)] | None = None
    note: Text500 = ""
    lines: Annotated[list[BomLineInput], Field(max_length=MAX_BOM_LINES_PER_BOM)] = Field(default_factory=list)

    @model_validator(mode="after")
    def _eff(self) -> "BomInput":
        _effectivity(self)
        return self


class BomLineRecord(BomLineInput):
    id: EntityId
    uom: UomCode
    child: ItemRef


class BomRecord(BomInput, _Stamped):
    revision: Revision
    version: int
    lines: list[BomLineRecord] = Field(default_factory=list)
    status: Status
    released_at: datetime | None = None
    obsoleted_at: datetime | None = None
    item: ItemRef


# ---------------------------------------------------------------- routing (3.6)

class OperationToolInput(MfgModel):
    tool_pool_id: EntityId
    qty: Annotated[int, Field(ge=1, le=100)] = 1


class OperationInput(MfgModel):
    id: EntityId | None = None
    seq: Annotated[int, Field(ge=1, le=9999)]
    name: _short(100, 1)
    description: Text500 = ""
    group_id: EntityId
    setup_minutes: Minutes = 0
    run_minutes: Minutes = 0
    run_per: Literal["unit", "panel", "batch"] = "unit"
    units_per_panel: Annotated[int, Field(ge=1, le=10_000)] | None = None
    units_per_batch: Annotated[int, Field(ge=1, le=100_000)] | None = None
    queue_minutes: Minutes = 0
    move_minutes: Minutes = 0
    wait_minutes: Minutes = 0
    labor: Literal["attended", "unattended"] = "attended"
    crew_size: Annotated[int, Field(ge=0, le=50)] = 1
    skill_id: EntityId | None = None
    tools: list[OperationToolInput] = Field(default_factory=list)
    transfer_batch: Annotated[int, Field(ge=1, le=100_000)] | None = None
    yield_pct: YieldPct = 100
    inspection_gate: bool = False
    interruptible: bool = True

    @model_validator(mode="after")
    def _rules(self) -> "OperationInput":
        if (self.run_per == "panel") != (self.units_per_panel is not None):
            raise ValueError("units_per_panel is required when run_per is 'panel' and not allowed otherwise")
        if (self.run_per == "batch") != (self.units_per_batch is not None):
            raise ValueError("units_per_batch is required when run_per is 'batch' and not allowed otherwise")
        if self.crew_size == 0 and self.labor != "unattended":
            raise ValueError("crew_size 0 is only allowed for unattended operations")
        _unique([t.tool_pool_id for t in self.tools], "tool pools of an operation")
        return self


class RoutingInput(MfgModel):
    item_id: EntityId
    revision: Revision | None = None
    code: Code = "STD"
    version: Annotated[int, Field(ge=1, le=9999)] | None = None
    priority: Annotated[int, Field(ge=1, le=9)] = 1
    effective_from: PlanDate | None = None
    effective_to: PlanDate | None = None
    serial_from: Annotated[int, Field(ge=1, le=1_000_000_000)] | None = None
    serial_to: Annotated[int, Field(ge=1, le=1_000_000_000)] | None = None
    note: Text500 = ""
    operations: Annotated[list[OperationInput], Field(max_length=MAX_OPERATIONS_PER_ROUTING)] = \
        Field(default_factory=list)

    @model_validator(mode="after")
    def _eff(self) -> "RoutingInput":
        _effectivity(self)
        return self


class OperationToolRecord(OperationToolInput):
    tool_pool: Ref


class OperationRecord(OperationInput):
    id: EntityId
    tools: list[OperationToolRecord] = Field(default_factory=list)
    group: Ref
    skill: Ref | None = None


class RoutingRecord(RoutingInput, _Stamped):
    revision: Revision
    version: int
    operations: list[OperationRecord] = Field(default_factory=list)
    status: Status
    released_at: datetime | None = None
    obsoleted_at: datetime | None = None
    item: ItemRef


# ---------------------------------------------------------------- groups and lines (3.7)

class GroupInput(MfgModel):
    code: Code
    name: Name
    description: Text500 = ""
    kind: Code | None = None
    active: bool = True


class GroupRecord(GroupInput, _Stamped):
    line_count: int = 0


class LineInput(MfgModel):
    group_id: EntityId
    code: Code
    name: Name
    speed_factor: Annotated[float, Field(ge=0.05, le=20)] = 1.0
    parallel_capacity: Annotated[int, Field(ge=1, le=100)] = 1
    setup_family: Code | None = None
    eligible_families: Annotated[list[Code], Field(max_length=50)] = Field(default_factory=list)
    eligible_item_ids: Annotated[list[EntityId], Field(max_length=500)] = Field(default_factory=list)
    cost_per_hour: Annotated[float, Field(ge=0, le=1_000_000)] = 0
    active: bool = True

    @model_validator(mode="after")
    def _uniq(self) -> "LineInput":
        _unique(self.eligible_families, "eligible_families")
        _unique(self.eligible_item_ids, "eligible_item_ids")
        return self


class LineRecord(LineInput, _Stamped):
    group: Ref
    eligible_items: list[ItemRef] = Field(default_factory=list)


# ---------------------------------------------------------------- shifts and calendar (3.8)

class BreakDef(MfgModel):
    name: _short(32) = ""
    start: HHMM
    end: HHMM


class ShiftDef(MfgModel):
    name: _short(32, 1)
    days: Annotated[list[Weekday], Field(min_length=1, max_length=7)]
    start: HHMM
    end: HHMM
    breaks: Annotated[list[BreakDef], Field(max_length=10)] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rules(self) -> "ShiftDef":
        _unique(self.days, "days")
        if self.start == "24:00":
            raise ValueError("start must be 00:00..23:59")
        return self


class ShiftTemplateInput(MfgModel):
    code: Code
    name: Name
    description: Text500 = ""
    shifts: Annotated[list[ShiftDef], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def _names(self) -> "ShiftTemplateInput":
        _unique([s.name for s in self.shifts], "shift names of a template")
        return self


class ShiftTemplateRecord(ShiftTemplateInput, _Stamped):
    assignment_count: int = 0
    operator_count: int = 0


class ShiftAssignmentInput(MfgModel):
    shift_template_id: EntityId
    target_type: Literal["group", "line"]
    group_id: EntityId | None = None
    line_id: EntityId | None = None
    kind: Literal["base", "optional"] = "base"
    shift_names: list[_short(32, 1)] = Field(default_factory=list)
    effective_from: PlanDate
    effective_to: PlanDate | None = None
    cost_per_hour: Annotated[float, Field(ge=0, le=1_000_000)] | None = None
    max_hours_per_week: Annotated[float, Field(ge=0, le=168)] | None = None
    note: Text500 = ""

    @model_validator(mode="after")
    def _rules(self) -> "ShiftAssignmentInput":
        if self.target_type == "group" and (self.group_id is None or self.line_id is not None):
            raise ValueError("a group assignment needs group_id and no line_id")
        if self.target_type == "line" and (self.line_id is None or self.group_id is not None):
            raise ValueError("a line assignment needs line_id and no group_id")
        if self.kind == "base" and (self.cost_per_hour is not None or self.max_hours_per_week is not None):
            raise ValueError("cost_per_hour and max_hours_per_week are only allowed on optional assignments")
        if self.effective_to is not None and not self.effective_from < self.effective_to:
            raise ValueError("effective_from must be before effective_to")
        _unique(self.shift_names, "shift_names")
        return self


class ShiftAssignmentRecord(ShiftAssignmentInput, _Stamped):
    template: Ref
    target: TargetRef


class CalendarExceptionInput(MfgModel):
    scope: Literal["plant", "group", "line"]
    group_id: EntityId | None = None
    line_id: EntityId | None = None
    kind: Literal["holiday", "shutdown", "maintenance"]
    start: PlanDateTime
    end: PlanDateTime
    label: _short(100) = ""

    @model_validator(mode="after")
    def _rules(self) -> "CalendarExceptionInput":
        if self.scope == "plant" and (self.group_id is not None or self.line_id is not None):
            raise ValueError("a plant exception has no group_id or line_id")
        if self.scope == "group" and (self.group_id is None or self.line_id is not None):
            raise ValueError("a group exception needs group_id and no line_id")
        if self.scope == "line" and (self.line_id is None or self.group_id is not None):
            raise ValueError("a line exception needs line_id and no group_id")
        if not self.start < self.end:
            raise ValueError("start must be before end")
        if (self.end - self.start).total_seconds() > 366 * 86400:
            raise ValueError("an exception may last at most 366 days")
        return self


class CalendarExceptionRecord(CalendarExceptionInput, _Stamped):
    target: TargetRef | None = None


# ---------------------------------------------------------------- skills, operators, tooling (3.9)

class SkillInput(MfgModel):
    code: Code
    name: Name
    description: Text500 = ""


class SkillRecord(SkillInput, _Stamped):
    operator_count: int = 0
    operation_count: int = 0


class OperatorInput(MfgModel):
    code: Code
    name: Name
    skill_ids: list[EntityId] = Field(default_factory=list)
    shift_template_id: EntityId | None = None
    shift_names: list[_short(32, 1)] = Field(default_factory=list)
    home_group_id: EntityId | None = None
    active: bool = True

    @model_validator(mode="after")
    def _rules(self) -> "OperatorInput":
        _unique(self.skill_ids, "skill_ids")
        _unique(self.shift_names, "shift_names")
        if self.shift_names and self.shift_template_id is None:
            raise ValueError("shift_names need a shift_template_id")
        return self


class OperatorRecord(OperatorInput, _Stamped):
    skills: list[Ref] = Field(default_factory=list)
    shift_template: Ref | None = None
    home_group: Ref | None = None


class ToolPoolInput(MfgModel):
    code: Code
    name: Name
    kind: Code | None = None
    quantity: Annotated[int, Field(ge=0, le=10_000)]
    note: Text500 = ""


class ToolPoolRecord(ToolPoolInput, _Stamped):
    operation_count: int = 0


# ---------------------------------------------------------------- health (7.1)

class HealthIssue(MfgModel):
    code: str
    severity: Severity
    message: str
    fix: str
    entity: EntityRef
    related: list[EntityRef] = Field(default_factory=list)
    link: str | None = None
    field: str | None = None


class HealthCounts(MfgModel):
    error: int = 0
    warning: int = 0
    info: int = 0


class HealthReport(MfgModel):
    ok: bool
    as_of: date
    horizon_days: int
    fingerprint: str
    counts: HealthCounts
    by_code: dict[str, int]
    truncated: bool
    issues: list[HealthIssue]
    data_version: int = 0


# ---------------------------------------------------------------- explosion / where-used (5)

class ExplosionAlternate(MfgModel):
    line_id: str
    item_id: str
    part_number: str
    qty_per: float
    line_uom: str
    alt_priority: int


class ExplosionRow(MfgModel):
    row: int
    parent_row: int | None
    subtree_end: int
    level: int
    line_id: str | None
    bom_id: str | None
    item_id: str
    part_number: str
    revision: str
    description: str
    make_buy: MakeBuy
    uom: str
    family: str | None
    lead_time_days: int | None
    active: bool
    find_number: str | None
    ref_designators: str
    qty_per: float | None
    line_uom: str | None
    scrap_pct: float | None
    operation_seq: int | None
    extended_qty: float
    alternates: list[ExplosionAlternate]
    is_phantom: bool
    has_children: bool
    is_shared: bool
    routing_id: str | None


class SummarizedRow(MfgModel):
    item_id: str
    part_number: str
    description: str
    make_buy: MakeBuy
    uom: str
    total_qty: float
    min_level: int
    max_level: int
    occurrences: int
    lead_time_days: int | None


class ExplosionTotals(MfgModel):
    rows: int
    distinct_items: int
    max_level: int
    make_items: int
    buy_items: int
    phantom_items: int


class ExplosionWarning(MfgModel):
    code: str
    message: str
    item_id: str | None = None


class Explosion(MfgModel):
    item_id: str
    part_number: str
    on: date | None
    serial: int | None
    qty: float
    mode: Literal["indented", "summarized"]
    rows: list[ExplosionRow] | list[SummarizedRow]
    totals: ExplosionTotals
    warnings: list[ExplosionWarning]


class WhereUsedRow(MfgModel):
    row: int
    level: int
    parent_row: int | None
    item_id: str
    part_number: str
    revision: str
    description: str
    make_buy: MakeBuy
    bom_id: str
    bom_revision: str
    bom_version: int
    bom_status: Status
    line_id: str
    find_number: str
    qty_per: float
    line_uom: str
    is_top: bool


class WhereUsedTotals(MfgModel):
    rows: int
    top_items: int


class WhereUsed(MfgModel):
    item_id: str
    part_number: str
    mode: Literal["single", "indented"]
    include: Literal["effective", "all"]
    on: date | None
    rows: list[WhereUsedRow]
    totals: WhereUsedTotals


# ---------------------------------------------------------------- time (4.5, 4.6)

class OpTime(MfgModel):
    setup: float
    run: float
    total: float
    loads: float


class Window(MfgModel):
    start: datetime
    end: datetime
    kind: Literal["base", "optional"]
    assignment_id: str | None
    shift_label: str
    cost_per_hour: float | None = None


class WeekWindow(MfgModel):
    shift: str
    day: Weekday
    start_minute: int
    end_minute: int


class TimePreviewLine(MfgModel):
    line_id: str
    code: str
    speed_factor: float
    eligible: bool
    reason: str | None = None
    setup_minutes: float
    run_minutes: float
    total_minutes: float


class TimePreviewOperation(MfgModel):
    seq: int
    name: str
    group: Ref
    input_qty: float
    output_qty: float
    run_per: Literal["unit", "panel", "batch"]
    loads: float
    queue_minutes: float
    move_minutes: float
    wait_minutes: float
    labor: Literal["attended", "unattended"]
    lines: list[TimePreviewLine]


class TimePreviewTotals(MfgModel):
    fastest_minutes: float
    slowest_minutes: float
    passive_minutes: float
    cumulative_yield: float


class TimePreview(MfgModel):
    routing_id: str
    item_id: str
    qty: float
    uom: str
    operations: list[TimePreviewOperation]
    totals: TimePreviewTotals


# ---------------------------------------------------------------- record -> input

INPUT_OF: dict[type[BaseModel], type[BaseModel]] = {
    PlantRecord: PlantInput, ItemRecord: ItemInput, BomRecord: BomInput, BomLineRecord: BomLineInput,
    RoutingRecord: RoutingInput, OperationRecord: OperationInput, OperationToolRecord: OperationToolInput,
    GroupRecord: GroupInput, LineRecord: LineInput, ShiftTemplateRecord: ShiftTemplateInput,
    ShiftAssignmentRecord: ShiftAssignmentInput, CalendarExceptionRecord: CalendarExceptionInput,
    SkillRecord: SkillInput, OperatorRecord: OperatorInput, ToolPoolRecord: ToolPoolInput,
}


def input_data(record: BaseModel) -> dict[str, Any]:
    """The Input-model fields of a record as a plain dict (nested lines/operations/tools reduced too); e.g. the
    body of a PUT that changes nothing."""
    cls = INPUT_OF[type(record)]
    out: dict[str, Any] = {}
    for name in cls.model_fields:
        v = getattr(record, name)
        if isinstance(v, list) and v and isinstance(v[0], BaseModel) and type(v[0]) in INPUT_OF:
            v = [input_data(x) for x in v]
        elif isinstance(v, BaseModel):
            v = v.model_dump()
        elif isinstance(v, (list, dict)):
            v = v.copy()
        out[name] = v
    return out


def to_input(record: BaseModel) -> BaseModel:
    return INPUT_OF[type(record)].model_validate(input_data(record))


def construct_fast(cls: type[BaseModel], values: dict[str, Any]) -> Any:
    """`model_construct` without defaults/alias processing for hot paths (explosion rows): `values` must contain
    every field of `cls`. No validation (as `model_construct`)."""
    m = cls.__new__(cls)
    object.__setattr__(m, "__dict__", values)
    object.__setattr__(m, "__pydantic_fields_set__", set(values))
    object.__setattr__(m, "__pydantic_extra__", None)
    object.__setattr__(m, "__pydantic_private__", None)
    return m
