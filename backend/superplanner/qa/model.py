"""M7 quality contract (M7-DESIGN 3, 5-9; frozen at S0): QA settings, sampling schemes, inspection plans,
inspection lots and results, holds, NCRs, CAPAs, complaints, field actions, equipment and calibrations,
attachments and links. Pure pydantic (no database)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from ..esig.model import SignatureInput, SignatureManifest
from ..mfg.model import Code, EntityId, MfgModel

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text500 = Annotated[str, StringConstraints(max_length=500)]
Text2000 = Annotated[str, StringConstraints(max_length=2000)]
LongText = Annotated[str, StringConstraints(max_length=20_000)]
Severity = Literal["critical", "major", "minor"]
Scope = Literal["incoming", "in_process", "final"]
DocStatus = Literal["draft", "approved", "obsolete"]
Aql = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,4}(\.[0-9]{1,3})?$")]     # "0.65", "1.0", "2.5"
Level = Literal["S-1", "S-2", "S-3", "S-4", "I", "II", "III"]
LEVELS: tuple[str, ...] = ("S-1", "S-2", "S-3", "S-4", "I", "II", "III")
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
QA_LINK_TYPES: tuple[str, ...] = ("ncr", "capa", "complaint", "field_action", "eco", "inspection_lot", "equipment")
LinkType = Literal["ncr", "capa", "complaint", "field_action", "eco", "inspection_lot", "equipment"]
AttachmentEntity = Literal["inspection_plan", "inspection_lot", "ncr", "capa", "complaint", "field_action",
                           "equipment", "calibration"]


class Stamped(MfgModel):
    """Every QA record (9): id, row_version, created_at, updated_at, signatures, links, attachments."""
    id: str
    row_version: int
    created_at: datetime
    updated_at: datetime
    signatures: list[SignatureManifest] = Field(default_factory=list)
    links: list[dict[str, Any]] = Field(default_factory=list)          # LinkRecord
    attachments: list[dict[str, Any]] = Field(default_factory=list)    # AttachmentRecord (no data)


# ---------------------------------------------------------------- QA settings (3)

class DefectCode(MfgModel):
    code: Code
    name: Text200
    severity: Severity


class ReportabilityRule(MfgModel):
    regime: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,32}$")]
    event_type: Literal["all", "death", "serious_injury", "malfunction", "other"]
    days: Annotated[int, Field(ge=0, le=365)]


class InspectionDueHours(MfgModel):
    incoming: Annotated[int, Field(ge=1, le=8760)] = 48
    in_process: Annotated[int, Field(ge=1, le=8760)] = 4
    final: Annotated[int, Field(ge=1, le=8760)] = 24


class QaSettings(MfgModel):
    defect_codes: Annotated[list[DefectCode], Field(max_length=500)] = Field(default_factory=list)
    mrb_location_id: EntityId | None = None
    cal_due_warning_days: Annotated[int, Field(ge=0, le=365)] = 14
    inspection_due_hours: InspectionDueHours = Field(default_factory=InspectionDueHours)
    reportability_rules: Annotated[list[ReportabilityRule], Field(max_length=100)] = Field(
        default_factory=lambda: [ReportabilityRule(regime="fda_mdr", event_type="all", days=30),
                                 ReportabilityRule(regime="hc_mdpr", event_type="death", days=10),
                                 ReportabilityRule(regime="hc_mdpr", event_type="serious_injury", days=10),
                                 ReportabilityRule(regime="hc_mdpr", event_type="all", days=30)])
    capa_sor: Literal["superplanner", "external"] = "superplanner"
    complaint_sor: Literal["superplanner", "external"] = "superplanner"
    final_release_role: Literal["qa_approver", "qa_engineer", "qa_inspector"] = "qa_approver"


class QaSettingsInput(QaSettings):
    """PUT body: changing `capa_sor` / `complaint_sor` is signed (`qa_settings.sor_change`, review M7)."""
    signature: SignatureInput | None = None


class QaSettingsRecord(QaSettings):
    row_version: int                          # the plant row's version (If-Match)


# ---------------------------------------------------------------- sampling schemes (5.1)

class SamplePlan(MfgModel):
    n: Annotated[int, Field(ge=1, le=1_000_000)]
    ac: Annotated[int, Field(ge=0, le=1_000_000)]
    re: Annotated[int, Field(ge=1, le=1_000_001)]


class LotSizeRange(MfgModel):
    min: Annotated[int, Field(ge=1)]
    max: Annotated[int, Field(ge=1)] | None = None          # None = open-ended (last range)
    letters: dict[Level, Annotated[str, StringConstraints(pattern=r"^[A-Z]$")]]


class SchemeTable(MfgModel):
    levels: Annotated[list[Level], Field(min_length=1)]
    lot_size_ranges: Annotated[list[LotSizeRange], Field(min_length=1, max_length=50)]
    #: {"normal": {letter: {aql: {n, ac, re}}}, "tightened": {...}}
    plans: dict[Literal["normal", "tightened"], dict[str, dict[Aql, SamplePlan]]]
    switching: dict[str, dict[str, int]] = Field(
        default_factory=lambda: {"to_tightened": {"rejected": 2, "of_last": 5},
                                 "to_normal": {"consecutive_accepted": 5}})


class SchemeInput(MfgModel):
    code: Code
    name: Text200
    kind: Literal["fixed", "percent", "full", "table"]
    fixed_n: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    percent: Annotated[float, Field(gt=0, le=100)] | None = None
    table: SchemeTable | None = None
    switching: bool = False
    note: Text500 = ""

    @model_validator(mode="after")
    def _kind(self) -> "SchemeInput":
        need = {"fixed": "fixed_n", "percent": "percent", "table": "table"}.get(self.kind)
        if need is not None and getattr(self, need) is None:
            raise ValueError(f"kind {self.kind!r} needs {need}")
        return self


class SchemeRecord(Stamped):
    code: str
    name: str
    kind: str
    fixed_n: int | None = None
    percent: float | None = None
    table: dict[str, Any] | None = None
    switching: bool
    status: DocStatus
    approved_at: datetime | None = None
    note: str


class ApproveInput(MfgModel):
    """Body of the signed approve/close/verify actions without other fields."""
    note: Text500 = ""
    signature: SignatureInput | None = None


class SamplingPreview(MfgModel):
    lot_size: float
    level: str
    aql: str
    state: str
    n: int
    ac: int
    re: int
    full: bool                                # 100 % inspection


# ---------------------------------------------------------------- inspection plans (5.1)

class CharacteristicInput(MfgModel):
    id: EntityId | None = None                # keep the id of an existing characteristic on update
    seq: Annotated[int, Field(ge=1, le=9999)]
    code: Code
    name: Text200
    kind: Literal["variable", "attribute"]
    severity: Severity
    unit: Annotated[str, StringConstraints(max_length=16)] | None = None
    nominal: float | None = None
    lsl: float | None = None
    usl: float | None = None
    method: Text500 = ""
    equipment_class: Code | None = None
    sample_override: dict[str, Any] | None = None           # {scheme_id, level, aql}
    destructive: bool = False

    @model_validator(mode="after")
    def _limits(self) -> "CharacteristicInput":
        if self.kind == "variable":
            if self.lsl is None and self.usl is None:
                raise ValueError("a variable characteristic needs lsl and/or usl")
            lo = self.lsl if self.lsl is not None else float("-inf")
            hi = self.usl if self.usl is not None else float("inf")
            if lo > hi or (self.nominal is not None and not (lo <= self.nominal <= hi)):
                raise ValueError("limits must satisfy lsl <= nominal <= usl")
        return self


class PlanInput(MfgModel):
    name: Text200
    item_id: EntityId
    scope: Scope
    operation_seq: Annotated[int, Field(ge=1, le=99999)] | None = None
    supplier_id: EntityId | None = None
    customer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    scheme_id: EntityId
    inspection_level: Level = "II"
    aql: dict[Severity, Aql] = Field(default_factory=lambda: {"critical": "0.065", "major": "0.65", "minor": "2.5"})
    effective_from: date | None = None
    note: Text500 = ""
    characteristics: Annotated[list[CharacteristicInput], Field(max_length=500)] = Field(default_factory=list)

    @model_validator(mode="after")
    def _scope(self) -> "PlanInput":
        if self.scope == "in_process" and self.operation_seq is None:
            raise ValueError("an in-process plan needs operation_seq")
        if self.scope != "in_process" and self.operation_seq is not None:
            raise ValueError("operation_seq is only for in-process plans")
        if self.supplier_id is not None and self.scope != "incoming":
            raise ValueError("supplier_id is only for incoming plans")
        if self.customer is not None and self.scope != "final":
            raise ValueError("customer is only for final plans")
        seqs = [c.seq for c in self.characteristics]
        if len(seqs) != len(set(seqs)):
            raise ValueError("characteristic seq values must be unique")
        return self


class CharacteristicRecord(MfgModel):
    id: str
    seq: int
    code: str
    name: str
    kind: str
    severity: str
    unit: str | None = None
    nominal: float | None = None
    lsl: float | None = None
    usl: float | None = None
    method: str
    equipment_class: str | None = None
    sample_override: dict[str, Any] | None = None
    destructive: bool


class PlanRecord(Stamped):
    number: str
    version: int
    name: str
    item_id: str
    item: dict[str, Any] | None = None       # {id, part_number, revision, name}
    scope: str
    operation_seq: int | None = None
    supplier_id: str | None = None
    customer: str | None = None
    scheme_id: str
    scheme_code: str | None = None
    inspection_level: str
    aql: dict[str, str]
    status: DocStatus
    effective_from: date | None = None
    supersedes_id: str | None = None
    approved_at: datetime | None = None
    note: str
    characteristics: list[CharacteristicRecord] = Field(default_factory=list)


# ---------------------------------------------------------------- inspection lots and results (5.2)

LotStatus = Literal["open", "in_progress", "ready", "accepted", "rejected", "cancelled"]


class InspectionLotInput(MfgModel):
    """Manual lot (re-inspection, customer request)."""
    plan_id: EntityId
    lot_id: EntityId | None = None
    wo_id: EntityId | None = None
    lot_size: Annotated[float, Field(gt=0, le=1_000_000_000)]
    hold: bool = False
    note: Text500 = ""


class ResultInput(MfgModel):
    characteristic_id: EntityId
    sample_no: Annotated[int, Field(ge=1, le=1_000_000)]
    value: float | None = None
    passed: bool | None = None
    defects: Annotated[int, Field(ge=0, le=1000)] | None = None
    equipment_id: EntityId | None = None
    note: Text500 = ""
    corrects_result_id: EntityId | None = None
    reason: Reason | None = None

    @model_validator(mode="after")
    def _one(self) -> "ResultInput":
        if self.value is None and self.passed is None:
            raise ValueError("give value (variable) or passed (attribute)")
        if self.corrects_result_id is not None and self.reason is None:
            raise ValueError("a correction needs a reason")
        return self


class ResultsBatch(MfgModel):
    client_batch_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:\-]{1,64}$")]
    results: Annotated[list[ResultInput], Field(min_length=1, max_length=2000)]


class ResultRecord(MfgModel):
    id: str
    characteristic_id: str
    sample_no: int
    value: float | None = None
    passed: bool
    defects: int
    equipment_id: str | None = None
    note: str
    reason: str | None = None
    entered_by: str
    entered_at: datetime
    corrects_result_id: str | None = None
    superseded: bool


class CharacteristicVerdict(MfgModel):
    characteristic_id: str
    code: str
    n: int
    ac: int
    re: int
    entered: int
    defective: int
    verdict: Literal["pending", "accept", "reject"]


class LotVerdict(MfgModel):
    verdict: Literal["pending", "accept", "reject"]
    characteristics: list[CharacteristicVerdict]


class DecisionInput(MfgModel):
    decision: Literal["accept", "reject"]
    note: Text500 = ""
    ncr_id: EntityId | None = None
    signature: SignatureInput | None = None


class CancelInput(MfgModel):
    reason: Reason
    signature: SignatureInput | None = None


class InspectionLotRecord(Stamped):
    number: str
    plan_id: str
    plan_number: str | None = None
    plan_version: int
    scope: str
    item_id: str
    item: dict[str, Any] | None = None
    lot_id: str | None = None
    lot_code: str | None = None
    wo_id: str | None = None
    wo_number: str | None = None
    wo_operation_id: str | None = None
    operation_seq: int | None = None
    posting_id: str | None = None
    supplier_id: str | None = None
    customer: str | None = None
    lot_size: float
    sampling: dict[str, Any]
    status: LotStatus
    verdict: LotVerdict | None = None
    decision: Literal["accept", "reject"] | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_note: str = ""
    ncr_id: str | None = None
    hold: bool
    source: str
    due_at: datetime | None = None
    overdue: bool = False
    characteristics: list[CharacteristicRecord] = Field(default_factory=list)
    results: list[ResultRecord] = Field(default_factory=list)


class ResultsBatchResponse(MfgModel):
    inspection_lot_id: str
    client_batch_id: str
    accepted: int
    replayed: bool = False
    results: list[ResultRecord]
    verdict: LotVerdict
    status: LotStatus
    row_version: int


# ---------------------------------------------------------------- holds (5.3)

HoldSource = Literal["inspection", "ncr", "recall", "field_action", "manual"]


class HoldInput(MfgModel):
    lot_id: EntityId | None = None
    serial_id: EntityId | None = None
    reason: Reason

    @model_validator(mode="after")
    def _one(self) -> "HoldInput":
        if (self.lot_id is None) == (self.serial_id is None):
            raise ValueError("give lot_id or serial_id")
        return self


class HoldReleaseInput(MfgModel):
    note: Text500 = ""
    signature: SignatureInput | None = None


class HoldRecord(Stamped):
    lot_id: str | None = None
    lot_code: str | None = None
    serial_id: str | None = None
    serial: str | None = None
    item_id: str
    item: dict[str, Any] | None = None
    source: HoldSource
    source_id: str | None = None
    source_number: str | None = None
    reason: str
    placed_by: str
    placed_at: datetime
    released_by: str | None = None
    released_at: datetime | None = None
    release_signature_id: str | None = None
    release_note: str = ""
    open: bool


# ---------------------------------------------------------------- NCR / MRB (6)

NcrStatus = Literal["draft", "open", "proposed", "approved", "implemented", "closed", "cancelled"]
DispositionKind = Literal["scrap", "rework", "use_as_is", "return_to_supplier"]


class NcrInput(MfgModel):
    title: Text200
    source: Literal["inspection", "floor", "complaint", "supplier", "internal", "audit"] = "internal"
    severity: Severity = "major"
    item_id: EntityId | None = None
    lot_id: EntityId | None = None
    serial_ids: Annotated[list[EntityId], Field(max_length=1000)] = Field(default_factory=list)
    supplier_id: EntityId | None = None
    wo_id: EntityId | None = None
    complaint_id: EntityId | None = None
    location_id: EntityId | None = None
    place: Literal["stock", "wip"] = "stock"
    qty_nc: Annotated[float, Field(ge=0, le=1_000_000_000)] = 0
    defect_codes: Annotated[list[Code], Field(max_length=50)] = Field(default_factory=list)
    description: LongText = ""
    containment: LongText = ""
    investigation: LongText = ""
    capa_required: bool = False
    external_ref: Annotated[str, StringConstraints(max_length=64)] | None = None


class DispositionInput(MfgModel):
    kind: DispositionKind
    qty: Annotated[float, Field(gt=0, le=1_000_000_000)]
    location_id: EntityId | None = None
    rework_routing_id: EntityId | None = None
    rework_to_seq: Annotated[int, Field(ge=1, le=99999)] | None = None
    instructions: Text2000 = ""
    justification: Text2000 = ""


class ProposeInput(MfgModel):
    dispositions: Annotated[list[DispositionInput], Field(min_length=1, max_length=50)]


class DispositionRecord(MfgModel):
    id: str
    line_no: int
    kind: DispositionKind
    qty: float
    location_id: str | None = None
    rework_routing_id: str | None = None
    rework_to_seq: int | None = None
    instructions: str
    justification: str
    implemented_at: datetime | None = None
    refs: dict[str, Any] = Field(default_factory=dict)


class NcrRecord(Stamped):
    number: str
    title: str
    source: str
    severity: str
    item_id: str | None = None
    item: dict[str, Any] | None = None
    lot_id: str | None = None
    lot_code: str | None = None
    serial_ids: list[str] = Field(default_factory=list)
    supplier_id: str | None = None
    wo_id: str | None = None
    wo_operation_id: str | None = None
    operation_seq: int | None = None
    inspection_lot_id: str | None = None
    complaint_id: str | None = None
    place: str
    location_id: str | None = None
    qty_nc: float
    defect_codes: list[str]
    description: str
    containment: str
    investigation: str
    status: NcrStatus
    capa_required: bool
    author_id: str
    closed_at: datetime | None = None
    external_ref: str | None = None
    dispositions: list[DispositionRecord] = Field(default_factory=list)
    rework_wos: list[dict[str, Any]] = Field(default_factory=list)   # [{id, number, status}]
    next_actions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- CAPA (7)

CapaStatus = Literal["draft", "investigation", "plan_approval", "implementation", "effectiveness_check", "closed",
                     "cancelled"]


class CapaRisk(MfgModel):
    severity: Annotated[int, Field(ge=1, le=5)]
    occurrence: Annotated[int, Field(ge=1, le=5)]
    level: Literal["low", "medium", "high"] | None = None


class RootCause(MfgModel):
    method: Literal["5_why", "fishbone", "fault_tree", "8d", "other"]
    text: LongText


class Effectiveness(MfgModel):
    criteria: Text2000 = ""
    check_due_on: date | None = None
    result: Literal["effective", "not_effective"] | None = None
    evidence: Text2000 = ""


class CapaInput(MfgModel):
    title: Text200
    kind: Literal["corrective", "preventive"] = "corrective"
    problem: LongText = ""
    risk: CapaRisk | None = None
    owner_user_id: Annotated[str, StringConstraints(max_length=64)] | None = None
    due_on: date | None = None
    root_cause: RootCause | None = None
    effectiveness: Effectiveness | None = None
    external_ref: Annotated[str, StringConstraints(max_length=64)] | None = None
    #: external SoR stubs: free status text
    external_status: Annotated[str, StringConstraints(max_length=32)] | None = None


class CapaActionInput(MfgModel):
    kind: Literal["correction", "corrective", "preventive"] = "corrective"
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    owner_user_id: Annotated[str, StringConstraints(max_length=64)] | None = None
    due_on: date | None = None
    status: Literal["open", "done", "cancelled"] = "open"
    evidence: Text2000 = ""
    eco_id: EntityId | None = None


class CapaAdvanceInput(MfgModel):
    to: Literal["investigation", "plan_approval", "effectiveness_check"]
    note: Text500 = ""


class CapaVerifyInput(MfgModel):
    result: Literal["effective", "not_effective"]
    evidence: Text2000 = ""
    signature: SignatureInput | None = None


class CapaActionRecord(MfgModel):
    id: str
    seq: int
    kind: str
    description: str
    owner_user_id: str | None = None
    due_on: date | None = None
    status: str
    done_at: datetime | None = None
    evidence: str
    eco_id: str | None = None
    row_version: int


class CapaRecord(Stamped):
    number: str
    title: str
    kind: str
    problem: str
    risk: dict[str, Any] | None = None
    owner_user_id: str | None = None
    due_on: date | None = None
    root_cause: dict[str, Any] | None = None
    effectiveness: dict[str, Any] | None = None
    status: str
    author_id: str
    closed_at: datetime | None = None
    external_ref: str | None = None
    sor: Literal["superplanner", "external"]
    overdue: bool = False
    actions: list[CapaActionRecord] = Field(default_factory=list)


# ---------------------------------------------------------------- complaints (7)

ComplaintStatus = Literal["open", "investigation", "closed"]
EventType = Literal["death", "serious_injury", "malfunction", "other"]


class Reportability(MfgModel):
    assessed: bool = False
    reportable: bool | None = None
    regimes: list[str] = Field(default_factory=list)
    report_ref: Annotated[str, StringConstraints(max_length=100)] | None = None


class ComplaintInput(MfgModel):
    received_on: date
    aware_on: date
    channel: Literal["phone", "email", "web", "field", "distributor", "other"] = "email"
    customer: Text200
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] | None = None
    item_id: EntityId | None = None
    lots: Annotated[list[Annotated[str, StringConstraints(min_length=1, max_length=64)]], Field(max_length=200)] = \
        Field(default_factory=list)
    serials: Annotated[list[Annotated[str, StringConstraints(min_length=1, max_length=64)]],
                       Field(max_length=1000)] = Field(default_factory=list)
    qty_affected: Annotated[float, Field(ge=0, le=1_000_000_000)] | None = None
    description: LongText = ""
    event_type: EventType = "other"
    reportability: Reportability = Field(default_factory=Reportability)
    investigation: LongText = ""
    external_ref: Annotated[str, StringConstraints(max_length=64)] | None = None

    @model_validator(mode="after")
    def _dates(self) -> "ComplaintInput":
        if self.aware_on < self.received_on:
            raise ValueError("aware_on must not be before received_on")
        return self


class ComplaintAdvanceInput(MfgModel):
    to: Literal["investigation"]
    note: Text500 = ""


class ComplaintRecord(Stamped):
    number: str
    received_on: date
    aware_on: date
    channel: str
    customer: str
    country: str | None = None
    item_id: str | None = None
    lots: list[dict[str, Any]]                # [{code, lot_id|null}]
    serials: list[dict[str, Any]]             # [{code, serial_id|null}]
    warnings: list[str] = Field(default_factory=list)
    qty_affected: float | None = None
    description: str
    event_type: str
    reportability: dict[str, Any]
    reporting_due: list[dict[str, Any]] = Field(default_factory=list)   # [{regime, days, due_on, overdue}]
    investigation: str
    status: ComplaintStatus
    author_id: str
    closed_at: datetime | None = None
    external_ref: str | None = None
    sor: Literal["superplanner", "external"]


# ---------------------------------------------------------------- field actions (7)

FaStatus = Literal["draft", "approved", "in_progress", "completed", "closed", "cancelled"]
UnitStatus = Literal["pending", "notified", "acknowledged", "returned", "corrected", "destroyed", "not_reachable"]
UNIT_DONE: tuple[str, ...] = ("acknowledged", "returned", "corrected", "destroyed")


class FieldActionInput(MfgModel):
    title: Text200
    kind: Literal["recall", "correction", "removal", "safety_notice", "software_update"] = "recall"
    class_: Literal["I", "II", "III"] | None = Field(default=None, alias="class")
    regimes: Annotated[list[Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,32}$")]],
                       Field(max_length=10)] = Field(default_factory=list)
    strategy: LongText = ""
    recall_id: EntityId

    model_config = {"extra": "forbid", "populate_by_name": True}


class FieldActionUpdate(MfgModel):
    title: Text200
    kind: Literal["recall", "correction", "removal", "safety_notice", "software_update"] = "recall"
    class_: Literal["I", "II", "III"] | None = Field(default=None, alias="class")
    regimes: list[str] = Field(default_factory=list)
    strategy: LongText = ""

    model_config = {"extra": "forbid", "populate_by_name": True}


class FaCompleteInput(MfgModel):
    reason: Reason | None = None


class UnitUpdate(MfgModel):
    unit_id: EntityId
    status: UnitStatus
    note: Text500 = ""


class UnitsBulkInput(MfgModel):
    items: Annotated[list[UnitUpdate], Field(min_length=0, max_length=1000)] = Field(default_factory=list)
    #: CSV "code,status,note" lines keyed by serial or lot code (alternative to items)
    csv: Annotated[str, StringConstraints(max_length=1_000_000)] | None = None


class FieldActionUnitRecord(MfgModel):
    id: str
    kind: str
    serial_id: str | None = None
    lot_id: str | None = None
    code: str
    item_id: str
    customer: str
    demand_line_id: str | None = None
    qty: float
    in_stock: bool
    status: UnitStatus
    note: str
    updated_by: str | None = None
    updated_at: datetime | None = None


class FieldActionRecord(Stamped):
    number: str
    title: str
    kind: str
    class_: str | None = Field(default=None, alias="class")
    regimes: list[str]
    strategy: str
    recall_id: str
    recall_number: str | None = None
    status: FaStatus
    complete_reason: str | None = None
    author_id: str
    closed_at: datetime | None = None
    units_total: int = 0
    effectiveness: dict[str, Any] = Field(default_factory=dict)   # {overall, by_customer: [{customer, done, total, pct}]}

    model_config = {"extra": "forbid", "populate_by_name": True}


# ---------------------------------------------------------------- equipment and calibration (8)

EquipmentKind = Literal["gauge", "instrument", "fixture", "tool", "line_equipment", "chamber"]
EquipmentStatus = Literal["active", "out_of_service", "retired"]


class EquipmentInput(MfgModel):
    code: Code
    name: Text200
    kind: EquipmentKind
    equipment_class: Code
    line_id: EntityId | None = None
    tool_pool_id: EntityId | None = None
    serial_no: Annotated[str, StringConstraints(max_length=64)] = ""
    manufacturer: Annotated[str, StringConstraints(max_length=100)] = ""
    location: Annotated[str, StringConstraints(max_length=100)] = ""
    calibration_required: bool = True
    interval_days: Annotated[int, Field(ge=1, le=3650)] | None = None
    grace_days: Annotated[int, Field(ge=0, le=90)] = 0
    due_on: date | None = None
    procedure_ref: Annotated[str, StringConstraints(max_length=100)] = ""
    provider: Literal["internal", "external"] = "internal"
    note: Text500 = ""

    @model_validator(mode="after")
    def _cal(self) -> "EquipmentInput":
        if self.calibration_required and self.interval_days is None:
            raise ValueError("calibration_required needs interval_days")
        return self


class EquipmentStatusInput(MfgModel):
    status: EquipmentStatus
    reason: Reason
    signature: SignatureInput | None = None


class CalibrationInput(MfgModel):
    performed_on: date
    performed_by: Annotated[str, StringConstraints(max_length=64)] | None = None
    provider_name: Annotated[str, StringConstraints(max_length=200)] = ""
    result: Literal["pass", "adjusted_pass", "fail"]
    as_found: Text2000 = ""
    as_left: Text2000 = ""
    certificate_ref: Annotated[str, StringConstraints(max_length=200)] = ""
    next_due_on: date | None = None
    signature: SignatureInput | None = None


class CalibrationRecord(Stamped):
    equipment_id: str
    performed_on: date
    performed_by: str | None = None
    provider_name: str
    result: str
    as_found: str
    as_left: str
    certificate_ref: str
    next_due_on: date | None = None


class EquipmentRecord(Stamped):
    code: str
    name: str
    kind: str
    equipment_class: str
    line_id: str | None = None
    tool_pool_id: str | None = None
    serial_no: str
    manufacturer: str
    location: str
    status: EquipmentStatus
    calibration_required: bool
    interval_days: int | None = None
    grace_days: int
    last_calibrated_on: date | None = None
    due_on: date | None = None
    failed_on: date | None = None
    procedure_ref: str
    provider: str
    note: str
    valid: bool                               # Valid(e, now) (8)
    due_state: Literal["ok", "due_soon", "in_grace", "overdue", "not_required", "out_of_service", "retired"]


class ImpactRecord(MfgModel):
    equipment_id: str
    since: date | None = None                 # last passing calibration before the failure
    results: int
    inspection_lots: list[dict[str, Any]]     # [{id, number, status, decision, lot_id, lot_code, item_id, results}]


# ---------------------------------------------------------------- attachments and links (9)

class AttachmentRecord(MfgModel):
    id: str
    entity_type: str
    entity_id: str
    filename: str
    content_type: str
    size: int
    sha256: str
    uploaded_by: str
    uploaded_at: datetime


class LinkInput(MfgModel):
    from_type: LinkType
    from_id: EntityId
    to_type: LinkType
    to_id: EntityId


class LinkRecord(MfgModel):
    id: str
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    label: str | None = None                  # number of the other side
    created_by: str
    created_at: datetime


class QaSummary(MfgModel):
    open_lots: int
    overdue_lots: int
    open_ncrs: int
    overdue_capas: int
    equipment_due: int
