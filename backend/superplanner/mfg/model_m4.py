"""M4 execution contract (M4-DESIGN 3-11; frozen at S0): WO operations, floor events, downtime, batch loads, unit
serials, replan triggers, notifications, risk simulations and KPI shapes. Conventions as `mfg.model` /
`mfg.model_m2` / `mfg.model_m3`: inputs forbid extra fields; records are built with `model_construct` by services.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from .model import EntityId, MfgModel, PlanDateTime, Ref, _Stamped

# ---------------------------------------------------------------- enumerations

WoOpStatus = Literal["pending", "ready", "setup", "running", "paused", "completed", "skipped"]
WO_OP_STATUSES: tuple[str, ...] = ("pending", "ready", "setup", "running", "paused", "completed", "skipped")
#: stored statuses (`ready` is computed on read from `pending`, 4.2)
STORED_OP_STATUSES: tuple[str, ...] = ("pending", "setup", "running", "paused", "completed", "skipped")
WoOpSource = Literal["release", "lazy", "migrated"]
EventType = Literal["setup_start", "start", "pause", "resume", "report", "complete", "reopen", "correct", "skip"]
EVENT_TYPES: tuple[str, ...] = ("setup_start", "start", "pause", "resume", "report", "complete", "reopen", "correct",
                                "skip")
#: event types that need `floor_supervise` (11 #203)
SUPERVISOR_EVENTS: frozenset[str] = frozenset({"reopen", "correct", "skip"})
DowntimeKind = Literal["breakdown", "maintenance", "no_crew", "no_material", "other"]
DOWNTIME_KINDS: tuple[str, ...] = ("breakdown", "maintenance", "no_crew", "no_material", "other")
BatchStatus = Literal["open", "running", "completed", "cancelled"]
SerialStatus = Literal["wip", "in_stock", "consumed", "shipped", "scrapped"]
SERIAL_STATUSES: tuple[str, ...] = ("wip", "in_stock", "consumed", "shipped", "scrapped")
TriggerKind = Literal["line_down", "late_receipt", "scrap_shortfall", "overrun", "rush_order", "not_started",
                      "start_short"]
TRIGGER_KINDS: tuple[str, ...] = ("line_down", "late_receipt", "scrap_shortfall", "overrun", "rush_order",
                                  "not_started", "start_short")
TriggerStatus = Literal["open", "attached", "handled", "ignored"]
Severity = Literal["info", "warning", "critical"]
SimStatus = Literal["queued", "running", "completed", "failed"]
KpiDim = Literal["plant", "group", "line"]
KPI_METRICS: tuple[str, ...] = ("otd", "wo_on_time", "utilisation", "availability", "performance", "fpy", "oee",
                                "wip", "setup", "adherence", "scrap_rate")
ScanType = Literal["work_order", "operation", "lot", "serial", "location", "line", "operator", "batch_load"]

ClientEventId = Annotated[str, StringConstraints(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$")]
ReasonCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32,
                                              pattern=r"^[^\x00-\x1f\x7f]+$")]
Note500 = Annotated[str, StringConstraints(max_length=500, pattern=r"^[^\x00\x7f]*$")]
SerialText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64,
                                              pattern=r"^[^\x00-\x1f\x7f]+$")]
EventQty = Annotated[float, Field(ge=0, le=1_000_000)]
#: default floor reason codes (pause / scrap / rework); a plant overrides a list with the attribute
#: `floor_reasons_<kind>` = "CODE:Label,CODE:Label" (16.WP-S)
DEFAULT_REASON_CODES: dict[str, list[tuple[str, str]]] = {
    "pause": [("BREAK", "Break"), ("NO_MATERIAL", "Waiting for material"), ("NO_OPERATOR", "No operator"),
              ("MACHINE", "Machine problem"), ("QUALITY", "Quality hold"), ("CHANGEOVER", "Changeover"),
              ("OTHER", "Other")],
    "scrap": [("SOLDER_BRIDGE", "Solder bridge"), ("TOMBSTONE", "Tombstone"), ("MISSING_PART", "Missing part"),
              ("DAMAGED", "Damaged"), ("TEST_FAIL", "Test failure"), ("OTHER", "Other")],
    "rework": [("RESOLDER", "Resolder"), ("REPLACE_PART", "Replace part"), ("RETEST", "Retest"),
               ("CLEAN", "Clean / recoat"), ("OTHER", "Other")],
}
MAX_EVENT_SERIALS = 1000
MAX_EVENT_OPERATORS = 20
MAX_LOAD_MEMBERS = 50


# ---------------------------------------------------------------- WO operations (3.2 / 4)

class WoOperationRecord(MfgModel):
    """`GET /work-orders/{id}/operations` item (M3 #176 extended, 11 #206) and the `operation` of floor responses.
    M3's fields (`setup_minutes`, `run_minutes`, `labor`, `done*`, `placement`) are kept; `done` = completed or
    skipped. `qty_available` = input still available for good + scrap (4.2)."""
    id: str
    wo_id: str
    seq: int
    name: str
    group: Ref
    status: WoOpStatus
    qty_planned: float
    qty_good: float = 0.0
    qty_scrap: float = 0.0
    qty_rework_out: float = 0.0
    qty_rework_in: float = 0.0
    qty_input: float = 0.0
    qty_available: float = 0.0
    line: Ref | None = None
    setup_minutes_actual: float = 0.0
    run_minutes_actual: float = 0.0
    labour_minutes: float = 0.0
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    started_short: bool = False
    source: WoOpSource = "release"
    capture_serial: bool = False
    last_event_seq: int | None = None
    # M3 #176 fields
    setup_minutes: float = 0.0
    run_minutes: float = 0.0
    labor: str = "attended"
    done: bool = False
    done_at: datetime | None = None
    done_by: Ref | None = None
    placement: list[dict[str, Any]] = Field(default_factory=list)
    row_version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------- floor events (3.2 / 4.2 / 11)

class ConsumedSerial(MfgModel):
    item_id: EntityId
    serial: SerialText


class EventSerials(MfgModel):
    produced: Annotated[list[SerialText], Field(max_length=MAX_EVENT_SERIALS)] = Field(default_factory=list)
    consumed: Annotated[list[ConsumedSerial], Field(max_length=MAX_EVENT_SERIALS)] = Field(default_factory=list)


class ForceInput(MfgModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class FloorEventInput(MfgModel):
    """`POST /floor/events`. Exactly one of `wo_operation_id` / `scan` (`WO-000143/30`) or a `batch_load_id`
    (start/complete of a load apply to every member). `operator_codes` are badge scans (`OP:<code>` or the code)."""
    client_event_id: ClientEventId
    wo_operation_id: EntityId | None = None
    scan: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    event_type: EventType
    event_at: PlanDateTime | None = None
    line_id: EntityId | None = None
    operator_ids: Annotated[list[EntityId], Field(max_length=MAX_EVENT_OPERATORS)] = Field(default_factory=list)
    operator_codes: Annotated[list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                                                    max_length=40)]],
                              Field(max_length=MAX_EVENT_OPERATORS)] = Field(default_factory=list)
    qty_good: EventQty | None = None
    qty_scrap: EventQty | None = None
    qty_rework: EventQty | None = None
    rework_to_seq: Annotated[int, Field(ge=0, le=99_999)] | None = None
    reason_code: ReasonCode | None = None
    note: Note500 = ""
    batch_load_id: EntityId | None = None
    serials: EventSerials | None = None
    corrects_event_id: EntityId | None = None
    force: ForceInput | None = None

    @model_validator(mode="after")
    def _target(self) -> "FloorEventInput":
        n = sum(x is not None for x in (self.wo_operation_id, self.scan))
        if n > 1:
            raise ValueError("give wo_operation_id or scan, not both")
        if n == 0 and self.batch_load_id is None and self.corrects_event_id is None:
            raise ValueError("wo_operation_id, scan or batch_load_id is required")
        if (self.qty_rework or 0) > 0 and self.rework_to_seq is None:
            raise ValueError("rework_to_seq is required with qty_rework")
        if self.event_type == "correct" and self.corrects_event_id is None:
            raise ValueError("corrects_event_id is required for a correct event")
        return self


class FloorEventRecord(MfgModel):
    id: str
    seq: int
    wo_operation_id: str
    wo_id: str
    wo_number: str = ""
    op_seq: int = 0
    event_type: EventType
    event_at: datetime
    recorded_at: datetime
    line: Ref | None = None
    operators: list[Ref] = Field(default_factory=list)
    qty_good: float | None = None
    qty_scrap: float | None = None
    qty_rework: float | None = None
    rework_to_seq: int | None = None
    reason_code: str | None = None
    note: str = ""
    client_event_id: str | None = None
    batch_load_id: str | None = None
    serials: dict[str, Any] | None = None
    corrects_event_id: str | None = None
    corrected: bool = False
    forced: str | None = None
    actor: Ref | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class FloorWarning(MfgModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class FloorEventResult(MfgModel):
    """201 body of `POST /floor/events` (also the replay body, header `Idempotent-Replay: true`)."""
    event: FloorEventRecord
    operation: WoOperationRecord
    operations: list[WoOperationRecord] = Field(default_factory=list)   # other operations changed (rework, load)
    wo: dict[str, Any]                       # {id, number, status, qty, qty_completed, qty_scrapped, row_version}
    postings: list[dict[str, Any]] = Field(default_factory=list)       # [{id, number, type, lines}]
    warnings: list[FloorWarning] = Field(default_factory=list)
    triggers: list[dict[str, Any]] = Field(default_factory=list)       # ReplanTriggerRecord dicts raised


class BackflushRetryInput(MfgModel):
    wo_id: EntityId | None = None


# ---------------------------------------------------------------- queue / operation screen / scan (5, 11)

class ScanResult(MfgModel):
    type: ScanType
    id: str
    label: str
    link: str
    context: dict[str, Any] = Field(default_factory=dict)


class QueueRow(MfgModel):
    wo_operation_id: str | None
    wo: dict[str, Any]                 # {id, number, item: {id, part_number, description}, qty, due_date, priority}
    seq: int
    name: str
    status: WoOpStatus
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    op_no: int | None = None
    qty_planned: float = 0.0
    qty_good: float = 0.0
    kit: Literal["kitted", "partial", "short", "none"] = "none"
    batch_load_id: str | None = None
    next_actions: list[EventType] = Field(default_factory=list)


class QueueResponse(MfgModel):
    line: Ref
    date: str
    shift: str | None = None
    run_id: str | None = None
    down: dict[str, Any] | None = None        # open downtime of the line
    shifts: list[dict[str, Any]] = Field(default_factory=list)
    items: list[QueueRow] = Field(default_factory=list)


class FloorOperationDetail(MfgModel):
    operation: WoOperationRecord
    wo: dict[str, Any]
    instructions: str = ""
    components: list[dict[str, Any]] = Field(default_factory=list)  # {item, required, issued, backflush, kit, ...}
    tools: list[dict[str, Any]] = Field(default_factory=list)
    eligible_lines: list[Ref] = Field(default_factory=list)
    expected_input: float = 0.0
    events: list[FloorEventRecord] = Field(default_factory=list)
    allowed_actions: list[EventType] = Field(default_factory=list)
    serials: dict[str, Any] = Field(default_factory=dict)            # {capture, produced: [...], consumable: [...]}
    reason_codes: dict[str, list[dict[str, str]]] = Field(default_factory=dict)   # pause / scrap / rework


# ---------------------------------------------------------------- downtime (3.2)

class DowntimeInput(MfgModel):
    line_id: EntityId
    kind: DowntimeKind = "breakdown"
    planned: bool = False
    start_at: PlanDateTime | None = None          # None = now
    end_at: PlanDateTime | None = None            # None = open
    expected_end_at: PlanDateTime | None = None
    reason: Annotated[str, StringConstraints(max_length=200)] = ""
    note: Note500 = ""

    @model_validator(mode="after")
    def _span(self) -> "DowntimeInput":
        if self.start_at is not None and self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if self.start_at is not None and self.expected_end_at is not None and self.expected_end_at <= self.start_at:
            raise ValueError("expected_end_at must be after start_at")
        return self


class DowntimeUpdate(MfgModel):
    """`PUT /downtime/{id}`: close (`end_at`, `close: true` = now), move the expected end, edit reason/note."""
    close: bool = False
    end_at: PlanDateTime | None = None
    expected_end_at: PlanDateTime | None = None
    kind: DowntimeKind | None = None
    reason: Annotated[str, StringConstraints(max_length=200)] | None = None
    note: Note500 | None = None


class DowntimeRecord(_Stamped):
    line: Ref
    kind: DowntimeKind
    planned: bool
    start_at: datetime
    end_at: datetime | None = None
    expected_end_at: datetime | None = None
    open: bool = True
    minutes: float | None = None
    reason: str = ""
    note: str = ""
    reported_by: Ref | None = None
    closed_by: Ref | None = None
    triggers: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------- batch loads (6.3)

class BatchMemberInput(MfgModel):
    wo_operation_id: EntityId
    qty: Annotated[float, Field(gt=0, le=1_000_000)]


class BatchLoadInput(MfgModel):
    line_id: EntityId
    members: Annotated[list[BatchMemberInput], Field(min_length=1, max_length=MAX_LOAD_MEMBERS)]
    aps_run_id: EntityId | None = None

    @model_validator(mode="after")
    def _uniq(self) -> "BatchLoadInput":
        ids = [m.wo_operation_id for m in self.members]
        if len(set(ids)) != len(ids):
            raise ValueError("members must be distinct operations")
        return self


class BatchLoadRecord(_Stamped):
    load_no: str = ""                        # `BL:<id-suffix>` scan code
    line: Ref
    status: BatchStatus
    started_at: datetime | None = None
    ended_at: datetime | None = None
    aps_run_id: str | None = None
    units: float = 0.0
    members: list[dict[str, Any]] = Field(default_factory=list)   # [{wo_operation_id, wo: {id, number}, seq, qty}]


# ---------------------------------------------------------------- unit serials (10)

class UnitSerialRecord(_Stamped):
    item: dict[str, Any]                     # {id, part_number, description}
    serial: str
    wo: dict[str, Any] | None = None         # {id, number}
    status: SerialStatus
    captured_at: datetime
    captured_op_seq: int | None = None
    parent_serial_id: str | None = None
    consumed_at: datetime | None = None
    consumed_wo_id: str | None = None


class UnitSerialDetail(UnitSerialRecord):
    parent: UnitSerialRecord | None = None
    children: list[UnitSerialRecord] = Field(default_factory=list)
    consumed_by_wo: dict[str, Any] | None = None


# ---------------------------------------------------------------- replan / notifications (7)

class ReplanTriggerRecord(MfgModel):
    id: str
    kind: TriggerKind
    severity: Severity
    ref_type: str
    ref_id: str
    detected_at: datetime
    dedupe_key: str
    details: dict[str, Any] = Field(default_factory=dict)
    status: TriggerStatus
    aps_run_id: str | None = None
    handled_by: Ref | None = None
    handled_at: datetime | None = None
    message: str = ""


class TriggerNote(MfgModel):
    note: Note500 = ""


class ReplanRunInput(MfgModel):
    trigger_ids: Annotated[list[EntityId], Field(max_length=200)] | None = None


class NotificationRecord(MfgModel):
    id: str
    kind: str
    severity: Severity
    title: str
    body: str = ""
    link: str = ""
    trigger_id: str | None = None
    created_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: Ref | None = None


# ---------------------------------------------------------------- simulation (8)

class SimulationInput(MfgModel):
    base_run_id: EntityId
    samples: Annotated[int, Field(ge=1, le=50)] = 20
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 1
    horizon_days: Annotated[int, Field(ge=7, le=120)] | None = None


class SimulationRecord(_Stamped):
    base_run_id: str
    status: SimStatus
    samples: int
    params: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] | None = None   # {demand: [...], lines: [...], suppliers: [...], samples_done}
    error: Any | None = None
    job_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


# ---------------------------------------------------------------- KPIs (9)

class KpiValue(MfgModel):
    value: float | None
    num: float
    den: float
    unit: str = "ratio"


class KpiResponse(MfgModel):
    period: dict[str, Any]                  # {from, to, bucket, dim, dim_id}
    metrics: dict[str, Any]                 # otd, wo_on_time, utilisation, availability, performance, fpy, oee,
    #                                         scrap_rate -> KpiValue; wip {count, value, avg_age_days}; setup {...}
    series: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)   # metric -> [{bucket, value}]
    top_scrap: list[dict[str, Any]] = Field(default_factory=list)
    top_downtime: list[dict[str, Any]] = Field(default_factory=list)
    worst_adherence_lines: list[dict[str, Any]] = Field(default_factory=list)
    by_dim: list[dict[str, Any]] = Field(default_factory=list)


class AdherenceRow(MfgModel):
    wo_operation_id: str | None
    wo: dict[str, Any]
    seq: int
    line: Ref | None = None
    planned_start: datetime
    planned_end: datetime
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    start_delta_minutes: float | None = None
    end_delta_minutes: float | None = None
    adherent: bool = False


__all__ = [n for n in dir() if not n.startswith("_") and n not in ("annotations", "datetime", "Annotated", "Any",
                                                                     "Literal", "Field", "StringConstraints",
                                                                     "model_validator")]
