"""MRP contract types (M2-DESIGN 8.2; frozen at milestone E0).

- `MrpParams` is the body of `POST /mrp/runs` (Pydantic, `extra="forbid"`).
- `MrpSnapshot` is the immutable input built by `api.mfg.repo_m2.load_mrp_snapshot` (rows of `mfg.model_m2`).
- `MrpResult` and its parts are plain dataclasses (pure output, persisted by `api/mfg/mrp_store.py`).
  `to_jsonable(result)` / `canonical_json(result)` give the canonical JSON form (sorted keys, ISO dates); the same
  inputs always give byte-identical canonical JSON (P10).

Additive extensions of the 8.2 field lists are documented in M2-DESIGN 22.WP-E.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from ..dataset import MfgDataset
from ..limits import MAX_PROTECT_PROGRAMS, MRP_MAX_EXTRA_DEMAND, MRP_MAX_OVERRIDES
from ..model import Code, EntityId, MfgModel, PlanDate, Qty, Text500
from ..model_m2 import BalanceSnap, DemandSnap, ReservationSnap, ScheduleSnap, WoSnap

EPS = 1e-6
DemandType = Literal["customer", "internal", "spares", "project"]
Priority = Annotated[int, Field(ge=1, le=9)]
Serial = Annotated[int, Field(ge=1, le=1_000_000_000)]

# ---------------------------------------------------------------- params (= POST /mrp/runs body)


class DemandFilter(MfgModel):
    order_ids: Annotated[list[EntityId], Field(max_length=20_000)] | None = None
    programs: Annotated[list[Code], Field(max_length=200)] | None = None
    types: list[DemandType] | None = None


class ExtraDemand(MfgModel):
    item_id: EntityId
    qty: Qty
    due_date: PlanDate
    priority: Priority = 5
    serial_from: Serial | None = None
    serial_to: Serial | None = None
    label: Annotated[str, StringConstraints(max_length=100)] = ""

    @model_validator(mode="after")
    def _serials(self) -> "ExtraDemand":
        if (self.serial_from is None) != (self.serial_to is None):
            raise ValueError("serial_from and serial_to must both be set or both be empty")
        if self.serial_from is not None and self.serial_from > self.serial_to:
            raise ValueError("serial_from must not be greater than serial_to")
        return self


class SupplyDateOverride(MfgModel):
    schedule_id: EntityId | None = None
    wo_id: EntityId | None = None
    date: PlanDate

    @model_validator(mode="after")
    def _one(self) -> "SupplyDateOverride":
        if (self.schedule_id is None) == (self.wo_id is None):
            raise ValueError("exactly one of schedule_id and wo_id is required")
        return self


class LeadTimeOverride(MfgModel):
    item_id: EntityId
    lead_time_days: Annotated[int, Field(ge=0, le=730)]


class MrpParams(MfgModel):
    label: Annotated[str, StringConstraints(max_length=100)] = ""
    note: Text500 = ""
    as_of: PlanDate | None = None
    horizon_days: Annotated[int, Field(ge=7, le=730)] | None = None
    allocation: Literal["priority", "due_date"] = "priority"
    alternates: Literal["never", "when_short"] = "when_short"
    safety_stock: bool = True
    include_pr_supply: bool = True
    protect_programs: Annotated[list[Code], Field(max_length=MAX_PROTECT_PROGRAMS)] = Field(default_factory=list)
    demand_filter: DemandFilter | None = None
    exclude_demand_line_ids: Annotated[list[EntityId], Field(max_length=20_000)] = Field(default_factory=list)
    extra_demand: Annotated[list[ExtraDemand], Field(max_length=MRP_MAX_EXTRA_DEMAND)] = Field(default_factory=list)
    supply_date_overrides: Annotated[list[SupplyDateOverride], Field(max_length=MRP_MAX_OVERRIDES)] = \
        Field(default_factory=list)
    lead_time_overrides: Annotated[list[LeadTimeOverride], Field(max_length=MRP_MAX_OVERRIDES)] = \
        Field(default_factory=list)

    def what_if_inputs(self) -> bool:
        """True when any what-if input other than `as_of` is set (8.14)."""
        return bool(self.demand_filter is not None or self.exclude_demand_line_ids or self.extra_demand
                    or self.supply_date_overrides or self.lead_time_overrides or not self.include_pr_supply)


# ---------------------------------------------------------------- snapshot


@dataclass(frozen=True)
class MrpSnapshot:
    """Everything one run reads. `as_of` = plant today at load time; `dataset` = M1 master data + locations,
    suppliers, item_suppliers; `lots` by id; balances with `qty_on_hand > EPS`; open schedules (5.5); open demand
    lines of `open` orders; WOs `planned`/`released`/`in_progress`; whole-day plant holidays."""
    as_of: date
    dataset: MfgDataset
    lots: Mapping[str, Any] = field(default_factory=dict)
    balances: list[BalanceSnap] = field(default_factory=list)
    reservations: list[ReservationSnap] = field(default_factory=list)
    schedules: list[ScheduleSnap] = field(default_factory=list)
    demand: list[DemandSnap] = field(default_factory=list)
    work_orders: list[WoSnap] = field(default_factory=list)
    holidays: frozenset[date] = frozenset()


# ---------------------------------------------------------------- result parts

RequirementKind = Literal["demand", "extra_demand", "safety_stock", "planned_component", "wo_component"]
SupplyKind = Literal["stock", "inspection", "po", "pr", "wo", "planned"]


@dataclass(slots=True)
class SerialRange:
    serial_from: int
    serial_to: int

    def __len__(self) -> int:
        return self.serial_to - self.serial_from + 1

    def key(self) -> str:
        return f"{self.serial_from}-{self.serial_to}"


@dataclass(slots=True)
class SourceRef:
    """Where a requirement comes from / what a supply is.

    Requirement sources: `demand_line` (id = demand line id), `extra` (id = `extra:<index>`), `safety_stock`
    (id = item id), `planned_order` / `work_order` (parent: `item_id` + `node` = the parent supply node; work orders
    also `id` = WO id and `component_id`). Supply refs: `balance` (id = balance id), `po_schedule` / `pr_schedule`
    (id = schedule id, `number` = document number), `work_order` (id = WO id), `planned_order` (id = str(planned_no))."""
    type: str
    id: str | None
    label: str
    item_id: str | None = None
    node: int | None = None
    number: str | None = None
    component_id: str | None = None


@dataclass(slots=True)
class Peg:
    supply_item_id: str
    supply_node: int
    requirement_item_id: str
    requirement_node: int
    qty: float
    late_days: int


@dataclass(slots=True)
class Requirement:
    node: int
    kind: str
    need_date: date
    qty: float
    rank: tuple
    rank_label: str
    source: SourceRef
    segment: SerialRange | None
    pegs: list[Peg]
    satisfied_date: date | None
    late_days: int


@dataclass(slots=True)
class Supply:
    node: int
    kind: str
    qty: float
    avail_date: date
    projected_date: date | None
    expires_on: date | None
    ref: SourceRef
    pegged_qty: float
    component_nodes: list[tuple[str, int]]       # (item_id, requirement node) of a make supply's components
    planned_no: int | None
    start_date: date | None = None               # make supplies (WO / planned make), planned buys (order date)
    due_date: date | None = None                 # make supplies


@dataclass(slots=True)
class LeadTimeInfo:
    source: str          # override | item_supplier | supplier | item | routing | fixed
    days: int            # buy: purchase lead time (calendar); make: MLT for qty 1 (working)
    unit: str            # calendar | working
    receiving_days: int = 0


@dataclass(slots=True)
class LotInfo:
    rule: str
    moq: float
    multiple: float
    pack: float
    period_days: int | None
    fixed_qty: float | None


@dataclass(slots=True)
class TimelineEvent:
    date: date
    kind: str            # on_hand | requirement | supply | planned | expiry
    node: int | None
    label: str
    qty: float           # signed
    balance_existing: float
    balance_planned: float


@dataclass(slots=True)
class ItemStats:
    on_hand: float
    gross_qty: float
    existing_supply_qty: float
    planned_qty: float
    planned_count: int
    first_short_date: date | None
    short_qty: float
    late_qty: float
    min_balance: float
    exception_count: int


@dataclass(slots=True)
class ItemPlan:
    item_id: str
    part_number: str
    llc: int
    uom: str
    make_buy: str
    lead_time: LeadTimeInfo
    lot: LotInfo
    requirements: list[Requirement]
    supplies: list[Supply]
    timeline: list[TimelineEvent]
    stats: ItemStats
    supplier_id: str | None = None


@dataclass(slots=True)
class PegSummary:
    demand_line_id: str | None
    label: str
    qty: float


@dataclass(slots=True)
class PlannedOrder:
    planned_no: int
    kind: str                    # make | buy
    item_id: str
    part_number: str
    llc: int
    qty: float
    need_date: date
    start_date: date
    dock_date: date | None
    projected_start: date
    projected_due: date
    late_days: int
    release_status: str          # start_in_past | release_now | later
    supplier_id: str | None
    segment: SerialRange | None
    bom_id: str | None
    routing_id: str | None
    lot_note: str
    peg_summary: list[PegSummary]
    order_key: str
    supply_node: int
    directives: dict[str, float] = field(default_factory=dict)   # alt key -> primary-equivalent qty moved (8.9)


@dataclass(slots=True)
class ExRef:
    type: str
    id: str | None
    label: str


@dataclass(slots=True)
class MrpException:
    code: str
    severity: str                # critical | warning | info
    item_id: str | None
    part_number: str | None
    subject: ExRef
    demand_line_id: str | None
    date: date | None
    qty: float | None
    days: int | None
    message: str
    action: str
    suggested: dict[str, Any]
    related: list[ExRef]


@dataclass(slots=True)
class LimitStep:
    item_id: str
    part_number: str
    label: str
    date: date | None
    reason: str                  # lead_time | start_in_past | supply_date | component


@dataclass(slots=True)
class DemandProjection:
    demand_line_id: str | None
    extra: bool
    extra_index: int | None
    order_id: str | None
    order_number: str
    demand_type: str | None
    customer: str
    program: str | None
    line_no: int
    item_id: str
    part_number: str
    qty: float
    due_date: date
    priority: int
    segment: SerialRange | None
    projected_date: date | None
    late_days: int
    status: str                  # on_time | late | past_due
    limiting: list[LimitStep]
    node: int
    label: str


@dataclass(slots=True)
class MrpSummary:
    demand_lines: int
    demand_on_time: int
    demand_late: int
    demand_past_due: int
    max_late_days: int
    items: int
    items_short: int
    planned_make: int
    planned_buy: int
    release_now: int
    start_in_past: int
    alternates_used: int
    iterations: int
    exceptions_truncated: bool
    exceptions: dict[str, dict[str, int]]
    requirements: int = 0
    demand_outside_horizon: int = 0


@dataclass(slots=True)
class MrpResult:
    params: MrpParams
    as_of: date
    horizon_end: date
    kind: str                    # live | what_if
    summary: MrpSummary
    items: list[ItemPlan]
    planned_orders: list[PlannedOrder]
    exceptions: list[MrpException]
    demand: list[DemandProjection]
    iterations: int

    def item(self, item_id: str) -> ItemPlan | None:
        for p in self.items:
            if p.item_id == item_id:
                return p
        return None


# ---------------------------------------------------------------- errors


class MrpError(Exception):
    """Base of the errors `run_mrp` raises on purpose."""


class MrpPreflightError(MrpError):
    """422 `MRP_PREFLIGHT_FAILED`; `issues` in health-issue shape (dicts)."""

    def __init__(self, issues: list[dict[str, Any]]):
        super().__init__(f"MRP preflight failed ({len(issues)} issue(s))")
        self.issues = issues


class MrpTooLarge(MrpError):
    """422 `MRP_TOO_LARGE`: more than `MRP_MAX_REQUIREMENTS` requirement nodes."""

    def __init__(self, limit: int):
        super().__init__(f"The MRP run has more than {limit} requirements.")
        self.limit = limit


# ---------------------------------------------------------------- canonical JSON


def to_jsonable(x: Any) -> Any:
    """Dataclasses -> dicts (field order), dates -> ISO strings, tuples -> lists, Pydantic -> JSON mode dump."""
    if x is None or isinstance(x, (bool, int, str)):
        return x
    if isinstance(x, float):
        return 0.0 if x == 0 else x
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, BaseModel):
        return x.model_dump(mode="json")
    if is_dataclass(x):
        return {f.name: to_jsonable(getattr(x, f.name)) for f in fields(x)}
    if isinstance(x, dict):
        return {str(k): to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_jsonable(v) for v in x]
    raise TypeError(f"not JSON-serialisable: {type(x).__name__}")


def canonical_json(result: Any) -> bytes:
    return json.dumps(to_jsonable(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


# ---------------------------------------------------------------- JSON -> dataclasses (views over stored results)


def _d(v: Any) -> date | None:
    return date.fromisoformat(v) if isinstance(v, str) else v


def _seg(v: Any) -> SerialRange | None:
    return SerialRange(v["serial_from"], v["serial_to"]) if v else None


def _src(v: dict[str, Any]) -> SourceRef:
    return SourceRef(**v)


def item_plan_from_jsonable(d: Mapping[str, Any]) -> ItemPlan:
    """Inverse of `to_jsonable(ItemPlan)` (for `mrp_store` detail JSON and the views)."""
    reqs = [Requirement(node=r["node"], kind=r["kind"], need_date=_d(r["need_date"]), qty=r["qty"],
                        rank=tuple(r["rank"]), rank_label=r["rank_label"], source=_src(r["source"]),
                        segment=_seg(r["segment"]), pegs=[Peg(**p) for p in r["pegs"]],
                        satisfied_date=_d(r["satisfied_date"]), late_days=r["late_days"])
            for r in d["requirements"]]
    sups = [Supply(node=s["node"], kind=s["kind"], qty=s["qty"], avail_date=_d(s["avail_date"]),
                   projected_date=_d(s["projected_date"]), expires_on=_d(s["expires_on"]), ref=_src(s["ref"]),
                   pegged_qty=s["pegged_qty"], component_nodes=[(a, b) for a, b in s["component_nodes"]],
                   planned_no=s["planned_no"], start_date=_d(s.get("start_date")), due_date=_d(s.get("due_date")))
            for s in d["supplies"]]
    tl = [TimelineEvent(date=_d(e["date"]), kind=e["kind"], node=e["node"], label=e["label"], qty=e["qty"],
                        balance_existing=e["balance_existing"], balance_planned=e["balance_planned"])
          for e in d["timeline"]]
    st = dict(d["stats"])
    st["first_short_date"] = _d(st["first_short_date"])
    return ItemPlan(item_id=d["item_id"], part_number=d["part_number"], llc=d["llc"], uom=d["uom"],
                    make_buy=d["make_buy"], lead_time=LeadTimeInfo(**d["lead_time"]), lot=LotInfo(**d["lot"]),
                    requirements=reqs, supplies=sups, timeline=tl, stats=ItemStats(**st),
                    supplier_id=d.get("supplier_id"))


__all__ = [
    "DemandFilter", "DemandProjection", "EPS", "ExRef", "ExtraDemand", "ItemPlan", "ItemStats", "LeadTimeInfo",
    "LeadTimeOverride", "LimitStep", "LotInfo", "MrpError", "MrpException", "MrpParams", "MrpPreflightError",
    "MrpResult", "MrpSnapshot", "MrpSummary", "MrpTooLarge", "Peg", "PegSummary", "PlannedOrder", "Requirement",
    "SerialRange", "SourceRef", "Supply", "SupplyDateOverride", "TimelineEvent", "canonical_json",
    "item_plan_from_jsonable", "to_jsonable",
]
