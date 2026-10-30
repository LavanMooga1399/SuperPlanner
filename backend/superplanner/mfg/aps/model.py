"""APS contract (M3-DESIGN 6.1; **frozen at S0** - changes only via LEAD editing the design).

- `ApsParams`: the body of `POST /aps/runs` (and the stored params of a run).
- `ApsSnapshot` and its parts: what `repo_m3.load_aps_snapshot` hands to the pure scheduler (one REPEATABLE READ
  transaction). Plain frozen dataclasses.
- `ApsResult` and its parts: what the scheduler returns and `aps_store` persists; every instant is an aware UTC
  datetime, every duration whole minutes. `canonical(result)` is the byte-stable JSON used by the determinism test.
- View shapes returned by `aps.views` (gantt, load, dispatch, compare, bottlenecks) are typed here too.

`superplanner.mfg.aps` imports only `superplanner.mfg` and `ortools`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from ..model import EntityId, MfgModel, PlanDateTime

OvertimePolicy = Literal["off", "suggest", "allow"]
OVERTIME_POLICIES: tuple[str, ...] = ("off", "suggest", "allow")
RunKind = Literal["live", "what_if"]
RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
RUN_STATUSES: tuple[str, ...] = ("queued", "running", "completed", "failed", "cancelled")
OrderType = Literal["wo", "planned"]
OpStatus = Literal["scheduled", "unscheduled"]
ReasonCode = Literal["as_of", "material", "predecessor", "line_busy", "no_window", "crew", "tool", "setup", "frozen",
                     "locked", "elapsed", "edit", "beyond_horizon", "material_missing", "no_line", "in_progress"]
REASON_CODES: tuple[str, ...] = ("as_of", "material", "predecessor", "line_busy", "no_window", "crew", "tool",
                                 "setup", "frozen", "locked", "elapsed", "edit", "beyond_horizon",
                                 "material_missing", "no_line", "in_progress")
#: unscheduled reasons (an operation without a placement always has one of these)
UNSCHEDULED_REASONS: tuple[str, ...] = ("beyond_horizon", "material_missing", "no_window", "no_line", "crew", "tool")
OvertimeStatus = Literal["opened", "suggested", "forced"]
Severity = Literal["critical", "warning", "info"]
APS_MAX_OPERATIONS = 50_000
APS_MAX_OVERRIDES = 200
APS_MAX_EDITS = 500
APS_MAX_GANTT_BARS = 5_000
#: objective tuple field names (7.3), in lexicographic order
SCORE_FIELDS: tuple[str, ...] = ("hard_violations", "weighted_tardiness_minutes", "overtime_cost", "wip_minutes",
                                 "makespan_minutes", "setup_minutes")


# ---------------------------------------------------------------- params (POST /aps/runs body)

class CapacityOverride(MfgModel):
    """What-if capacity (6.8): force-open optional shift time (`open_optional`, counted as overtime) or close a
    line / all lines of a group (breakdown, maintenance) for `[start, end)`."""
    target_type: Literal["line", "group"]
    target_id: EntityId
    start: PlanDateTime
    end: PlanDateTime
    mode: Literal["open_optional", "close"]

    @model_validator(mode="after")
    def _span(self) -> "CapacityOverride":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if (self.end - self.start).days > 366:
            raise ValueError("an override spans at most 366 days")
        return self


class ScheduleEdit(MfgModel):
    """Manual edit (6.7). `move {op_no, line_id?, start?}`, `lock {op_no}`, `unlock {op_no}`,
    `resequence {line_id, op_nos}`."""
    kind: Literal["move", "lock", "unlock", "resequence"]
    op_no: Annotated[int, Field(ge=1)] | None = None
    line_id: EntityId | None = None
    start: PlanDateTime | None = None
    op_nos: Annotated[list[Annotated[int, Field(ge=1)]], Field(max_length=500)] | None = None

    @model_validator(mode="after")
    def _shape(self) -> "ScheduleEdit":
        if self.kind == "resequence":
            if not self.line_id or not self.op_nos or len(self.op_nos) < 2:
                raise ValueError("resequence needs line_id and at least two op_nos")
            if len(set(self.op_nos)) != len(self.op_nos):
                raise ValueError("op_nos must be unique")
            if self.op_no is not None or self.start is not None:
                raise ValueError("resequence takes line_id and op_nos only")
        else:
            if self.op_no is None:
                raise ValueError(f"{self.kind} needs op_no")
            if self.op_nos is not None:
                raise ValueError(f"{self.kind} does not take op_nos")
            if self.kind != "move" and (self.line_id is not None or self.start is not None):
                raise ValueError(f"{self.kind} takes op_no only")
            if self.kind == "move" and self.line_id is None and self.start is None:
                raise ValueError("move needs line_id and/or start")
        return self


class ApsParams(MfgModel):
    label: Annotated[str, StringConstraints(max_length=100)] = ""
    note: Annotated[str, StringConstraints(max_length=500)] = ""
    as_of: PlanDateTime | None = None             # None = now (rounded up to the minute); given -> what_if
    horizon_days: Annotated[int, Field(ge=7, le=120)] | None = None   # None = plant.aps_horizon_days
    mrp_run_id: EntityId | None = None            # None = latest completed live MRP run
    include_planned: bool = True                  # MRP planned make orders starting before the horizon end
    overtime: OvertimePolicy | None = None        # None = plant.aps_overtime_policy
    split: bool = True
    material: Literal["strict", "ignore"] = "strict"      # ignore -> what_if
    improve_seconds: Annotated[int, Field(ge=0, le=300)] = 30
    capacity_overrides: Annotated[list[CapacityOverride], Field(max_length=APS_MAX_OVERRIDES)] = \
        Field(default_factory=list)
    edits: Annotated[list[ScheduleEdit], Field(max_length=APS_MAX_EDITS)] = Field(default_factory=list)
    #: Q1 escalation (16): re-run run `copy_of` with identical inputs (its resolved as_of, horizon, MRP run, params)
    #: and only `overtime` / `label` / `note` / `improve_seconds` taken from this body; the kind follows the source
    copy_of: EntityId | None = None
    #: accepted suggested overtime (16 Q1): opened as planned overtime; not a what-if input
    open_shifts: Annotated[list[OpenShift], Field(max_length=APS_MAX_OVERRIDES)] = Field(default_factory=list)


#: body fields that may accompany `copy_of`
COPY_FIELDS: frozenset[str] = frozenset({"copy_of", "overtime", "label", "note", "improve_seconds", "open_shifts"})


class OpenShift(MfgModel):
    """An optional shift instance to open as planned overtime (accepting a suggestion, 6.8 / 16 Q1): the optional
    windows of `line_id` overlapping [start, end) are opened; the run stays live and publishable."""
    line_id: EntityId
    start: PlanDateTime
    end: PlanDateTime

    @model_validator(mode="after")
    def _span(self) -> "OpenShift":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class EditsRequest(MfgModel):
    edits: Annotated[list[ScheduleEdit], Field(min_length=1, max_length=APS_MAX_EDITS)]
    override_freeze: bool = False


class PublishRequest(MfgModel):
    """`POST /aps/runs/{id}/publish` body (optional): publish although the run was frozen against another published
    run (409 `APS_RUN_STALE_BASIS` otherwise)."""
    confirm_stale_basis: bool = False


class RunUpdate(MfgModel):
    label: Annotated[str, StringConstraints(max_length=100)] | None = None
    note: Annotated[str, StringConstraints(max_length=500)] | None = None
    pinned: bool | None = None


# ---------------------------------------------------------------- snapshot (repo_m3.load_aps_snapshot)

@dataclass(frozen=True)
class ApsComponent:
    id: str                     # wo component id, or "<planned_no>:<item_id>" for planned orders
    item_id: str
    qty: float                  # open (required - issued) qty in the item's stock UoM
    operation_seq: int | None   # None / not found -> the order's first operation


@dataclass(frozen=True)
class WoSnap:
    id: str
    number: str
    status: str                 # planned | released | in_progress
    item_id: str
    qty: float                  # open good qty to make (qty - qty_completed)
    due_date: date
    start_date: date
    priority: int
    routing_id: str | None
    serial_from: int | None
    components: tuple[ApsComponent, ...]
    done_seqs: frozenset[int] = frozenset()


@dataclass(frozen=True)
class PegSupply:
    """One supply pegged to a component requirement (M2 8.2)."""
    kind: str                   # stock | po_schedule | pr_schedule | work_order | planned
    ref_id: str | None          # balance / schedule / WO id / str(planned_no)
    label: str
    qty: float
    available_date: date | None     # buy supplies: available date; stock: as_of date; make: MRP due
    planned_no: int | None = None


@dataclass(frozen=True)
class PlannedMake:
    planned_no: int
    id: str                     # mpo_ id of the stored MRP planned order
    item_id: str
    qty: float
    need_date: date
    start_date: date
    routing_id: str | None
    bom_id: str | None
    serial_from: int | None
    order_key: str
    components: tuple[ApsComponent, ...]


@dataclass(frozen=True)
class DemandPeg:
    demand_line_id: str | None
    order_id: str | None
    order_number: str
    line_no: int
    item_id: str
    qty: float
    due_date: date
    priority: int
    program: str | None
    supplies: tuple[PegSupply, ...]


@dataclass(frozen=True)
class MrpPegView:
    run_id: str
    run_no: int
    kind: str                   # live | what_if
    planned: tuple[PlannedMake, ...]
    #: (order_type, order_id, component item_id) -> pegged supplies; order_id = WO id or str(planned_no)
    pegs: dict[tuple[str, str, str], tuple[PegSupply, ...]]
    #: (order_type, order_id) -> best M2 rank (8.8) of the demand pegged to the order
    ranks: dict[tuple[str, str], tuple[Any, ...]]
    rank_labels: dict[tuple[str, str], str]
    demand: tuple[DemandPeg, ...]


@dataclass(frozen=True)
class SupplySnap:
    kind: str                   # po_schedule | pr_schedule
    ref_id: str
    label: str
    item_id: str
    qty: float                  # open qty
    available_date: date


@dataclass(frozen=True)
class PublishedOp:
    op_no: int
    order_type: str
    order_id: str
    seq: int
    split_index: int
    split_count: int
    qty: float
    line_id: str | None
    start: datetime | None
    end: datetime | None
    crew: tuple[tuple[str, datetime, datetime], ...] = ()
    pieces: tuple[tuple[datetime, datetime], ...] = ()
    setup_minutes: int = 0
    run_minutes: int = 0


@dataclass(frozen=True)
class PublishedView:
    run_id: str
    run_no: int
    ops: tuple[PublishedOp, ...]


@dataclass(frozen=True)
class ApsSnapshot:
    as_of: datetime                     # aware, rounded up to the minute
    tz: tzinfo
    dataset: Any                        # MfgDataset incl. the M3 master tables (line rates, setup matrix, absences)
    work_orders: list[WoSnap]
    mrp: MrpPegView | None
    stock_now: dict[str, float]         # item -> free nettable stock (live fallback, 6.4)
    open_supply: list[SupplySnap]
    published: PublishedView | None
    edits: tuple[ScheduleEdit, ...] = ()
    #: (order_type, order_id, seq, split_index) -> locked placement taken from the parent run (edits, 6.7)
    locked: dict[tuple[str, str, int, int], PublishedOp] = field(default_factory=dict)
    override_freeze: bool = False
    #: move edits translated to operation keys: (order_type, order_id, seq, split_index) -> (line_id, start)
    moves: dict[tuple[str, str, int, int], tuple[str | None, datetime | None]] = field(default_factory=dict)
    #: resequence edits: (line_id, [(order_type, order_id, seq)])
    resequence: tuple[tuple[str, tuple[tuple[str, str, int], ...]], ...] = ()


# ---------------------------------------------------------------- result

class OrderRef(MfgModel):
    type: OrderType
    id: str                             # WO id, or mpo_ id of the planned order
    number: str                         # WO number, or "P-<planned_no>"
    planned_no: int | None = None
    item_id: str


class SplitInfo(MfgModel):
    index: int = 0                      # 0-based part
    count: int = 1


class Span(MfgModel):
    start: datetime
    end: datetime


class CrewSlot(MfgModel):
    operator_id: str
    start: datetime
    end: datetime


class ToolUse(MfgModel):
    tool_pool_id: str
    qty: int


class RefItem(MfgModel):
    type: str                           # stock | po_schedule | pr_schedule | work_order | planned | operation |
    id: str | None                      # line | operator | tool_pool | window | group
    label: str
    at: datetime | None = None


class ReleaseInfo(MfgModel):
    material_at: datetime | None = None
    predecessor_at: datetime | None = None
    refs: list[RefItem] = Field(default_factory=list)


class StartReason(MfgModel):
    code: ReasonCode
    refs: list[RefItem] = Field(default_factory=list)
    text: str


class ScheduledOp(MfgModel):
    op_no: int
    order: OrderRef
    seq: int
    name: str
    group_id: str
    qty: float
    split: SplitInfo = Field(default_factory=SplitInfo)
    line_id: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    setup_minutes: int = 0
    run_minutes: int = 0
    pieces: list[Span] = Field(default_factory=list)
    crew: list[CrewSlot] = Field(default_factory=list)
    tools: list[ToolUse] = Field(default_factory=list)
    release: ReleaseInfo = Field(default_factory=ReleaseInfo)
    locked: bool = False
    frozen: bool = False
    status: OpStatus = "scheduled"
    reason: StartReason
    due: datetime | None = None
    late_minutes: int = 0
    family: str = ""
    setup_from_family: str | None = None


class OvertimeWindow(MfgModel):
    line_id: str
    assignment_id: str | None
    start: datetime
    end: datetime
    minutes: int
    cost: float
    status: OvertimeStatus
    tardiness_saved_minutes: float | None = None    # suggested: weighted late minutes saved (6.8)
    reason: str = ""                                # why it is opened / suggested (which late work it helps)
    orders: list["OvertimeOrder"] = Field(default_factory=list)


class OvertimeOrder(MfgModel):
    """An order whose operations run in an opened / suggested overtime window."""
    order: OrderRef
    op_nos: list[int] = Field(default_factory=list)       # operations of this run in the window (opened only)
    minutes: int = 0                                       # operation minutes inside the window
    late_minutes: int = 0                                  # the order's lateness in the run that opened it


class LateStep(MfgModel):
    kind: Literal["material", "capacity", "calendar", "lead_time", "frozen", "locked", "crew", "tool",
                  "predecessor", "setup", "as_of"]
    op_no: int | None = None
    text: str
    refs: list[RefItem] = Field(default_factory=list)


class DemandRef(MfgModel):
    demand_line_id: str | None
    order_number: str
    line_no: int


class OrderResult(MfgModel):
    order: OrderRef
    part_number: str
    qty: float
    due: datetime | None
    start: datetime | None
    end: datetime | None
    late_minutes: int
    weight: float
    priority: int
    rank_label: str = ""
    demand_refs: list[DemandRef] = Field(default_factory=list)
    late_chain: list[LateStep] = Field(default_factory=list)
    late_text: str = ""
    unscheduled_ops: int = 0


class DemandResult(MfgModel):
    demand_line_id: str | None
    order_id: str | None
    order_number: str
    line_no: int
    item_id: str
    part_number: str
    qty: float
    due: datetime
    scheduled_end: datetime | None
    late_minutes: int
    priority: int
    program: str | None = None
    orders: list[OrderRef] = Field(default_factory=list)
    late_text: str = ""


class ApsException(MfgModel):
    code: str
    severity: Severity
    subject: RefItem
    op_no: int | None = None
    order: OrderRef | None = None
    message: str
    refs: list[RefItem] = Field(default_factory=list)


class LoadRow(MfgModel):
    group_id: str
    line_id: str | None                 # None = the group total
    day: date
    scheduled_minutes: float
    required_minutes: float
    base_minutes: float
    optional_minutes: float
    opened_minutes: float


class Violation(MfgModel):
    code: str                           # APS_V_* (7.4)
    op_no: int | None = None
    message: str
    refs: dict[str, Any] = Field(default_factory=dict)


class Validation(MfgModel):
    ok: bool
    violations: list[Violation] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class Bottleneck(MfgModel):
    group_id: str
    rank: int
    utilisation: float                  # scheduled / base capacity over the horizon, 0..1+
    late_chains: int
    suggestion: str | None = None
    saved_minutes: float | None = None


class ApsSummary(MfgModel):
    policy: OvertimePolicy
    operations: int = 0
    scheduled_operations: int = 0
    unscheduled: dict[str, int] = Field(default_factory=dict)     # reason -> count
    orders: int = 0
    late_orders: int = 0
    late_wos: int = 0
    demand_lines: int = 0
    demand_lines_on_time: int = 0
    demand_lines_late: int = 0
    late_demand_count: int = 0          # = demand_lines_late (Q1: the UI offers "Re-run with Allow" when > 0)
    weighted_tardiness: float = 0.0
    max_lateness_minutes: int = 0
    overtime_minutes: int = 0           # opened + forced
    overtime_cost: float = 0.0
    suggested_overtime_minutes: int = 0
    suggested_overtime_cost: float = 0.0
    suggested_tardiness_saved: float = 0.0
    utilisation: dict[str, float] = Field(default_factory=dict)   # group_id -> scheduled / base
    bottlenecks: list[str] = Field(default_factory=list)          # group ids, most loaded first
    setup_minutes: int = 0
    changeovers: int = 0
    avg_flow_days: float = 0.0
    makespan_minutes: int = 0
    validation_ok: bool = True
    violations: int = 0
    splits: int = 0
    iterations: int = 0
    accepted_moves: int = 0
    budget_used: float = 0.0            # deterministic seconds spent by LNS
    budget_cut: bool = False            # the wall-clock safety cap cut LNS short (S3)
    timings_ms: dict[str, int] = Field(default_factory=dict)      # load, construct, improve, validate, store


class ApsResult(MfgModel):
    params: ApsParams
    kind: RunKind
    as_of: datetime
    horizon_end: datetime
    summary: ApsSummary
    score: list[float]                  # SCORE_FIELDS order
    validation: Validation
    operations: list[ScheduledOp]
    overtime: list[OvertimeWindow]
    orders: list[OrderResult]
    demand: list[DemandResult]
    exceptions: list[ApsException]
    load: list[LoadRow]
    bottlenecks: list[Bottleneck]
    iterations: int = 0
    budget_used: float = 0.0


def canonical(result: ApsResult) -> str:
    """Byte-stable JSON of a result without timings (determinism test T-S15)."""
    d = result.model_dump(mode="json")
    d["summary"].pop("timings_ms", None)
    d["summary"].pop("budget_cut", None)
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------- view shapes (aps.views; API 188-199)

class GanttRow(MfgModel):
    key: str                            # line:<id> | group:<id> | order:<type>:<id> | demand:<id>
    label: str
    kind: Literal["group", "line", "order", "demand"]
    parent_key: str | None = None


class GanttBar(MfgModel):
    op_no: int
    row_key: str
    start: datetime
    end: datetime
    setup_end: datetime                 # end of the setup part (== start when no setup)
    pieces: list[Span]
    label: str
    order_number: str
    item_part_number: str
    qty: float
    late_minutes: int
    frozen: bool
    locked: bool
    split: SplitInfo
    status_color: Literal["on_time", "late", "critical", "frozen", "locked"]


class GanttBand(MfgModel):
    row_key: str
    start: datetime
    end: datetime
    kind: Literal["base", "optional_opened", "optional_suggested", "closed", "absence"]


class Gantt(MfgModel):
    view: Literal["line", "order", "demand"]
    rows: list[GanttRow]
    bars: list[GanttBar]
    bands: list[GanttBand]
    truncated: bool


class DispatchRow(MfgModel):
    op_no: int
    position: int
    start: datetime
    end: datetime
    order: OrderRef
    part_number: str
    qty: float
    seq: int
    name: str
    setup_minutes: int
    run_minutes: int
    setup_from_family: str | None
    family: str
    crew: list[CrewSlot]
    tools: list[ToolUse]
    predecessor_status: Literal["none", "done", "scheduled_before", "open"]
    material_status: Literal["kitted", "partial", "short", "n/a"]
    done: bool
    shift_label: str
    wo_row_version: int | None = None    # If-Match for the done / reopen buttons (WO operations)


class CompareDelta(MfgModel):
    key: str
    a: float | None
    b: float | None
    delta: float | None


class OrderDelta(MfgModel):
    order: OrderRef
    end_a: datetime | None
    end_b: datetime | None
    delta_minutes: int | None
    late_a: int
    late_b: int


class Compare(MfgModel):
    a: dict[str, Any]                   # {id, run_no, label, policy}
    b: dict[str, Any]
    kpis: list[CompareDelta]
    #: Q1: "lateness saved vs overtime hours added" of b relative to a
    tradeoff: dict[str, float]          # weighted_tardiness_saved, late_minutes_saved, late_demand_saved,
                                        # overtime_hours_added, overtime_cost_added
    orders: list[OrderDelta]            # changed only, max 500
    utilisation: list[CompareDelta]     # per group
    truncated: bool


__all__ = [n for n in dir() if not n.startswith("_") and (n[0].isupper() or n == "canonical")]
