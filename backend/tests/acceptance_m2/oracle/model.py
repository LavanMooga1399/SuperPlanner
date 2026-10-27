"""Plain input/output structures of the independent MRP oracle (WP-D, M2-DESIGN 17.2).

Written from docs/M2-DESIGN.md section 8 (and M1-DESIGN 3.2/4.1/4.4/4.5 for effectivity, units, yields and
operation loads) only. Nothing here imports `superplanner`: the oracle must stay independent of the engine
(`superplanner.mfg.mrp`) and of the M1 pure helpers it uses. Adapters to and from the product types live in
`oracle/adapters.py`.

All quantities are in the item's stock UoM. Dates are `datetime.date`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

EPS = 1e-6
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# ---------------------------------------------------------------- master data


@dataclass
class OItem:
    id: str
    part_number: str
    make_buy: str                      # make | buy | phantom
    uom: str = "EA"
    lead_time_days: int | None = None
    receiving_days: int = 0
    lot_rule: str = "lot_for_lot"      # lot_for_lot | fixed | period
    fixed_lot_qty: float | None = None
    lot_period_days: int | None = None
    min_order_qty: float = 0.0
    order_multiple: float = 0.0
    safety_stock: float = 0.0
    serialized: bool = False
    active: bool = True
    family: str | None = None


@dataclass
class OBomLine:
    id: str
    find_number: str
    child_id: str
    qty_per: float
    uom: str
    scrap_pct: float = 0.0
    alt_group: str | None = None
    alt_priority: int = 1
    operation_seq: int | None = None


@dataclass
class OBom:
    id: str
    item_id: str
    lines: list[OBomLine] = field(default_factory=list)
    status: str = "released"
    version: int = 1
    revision: str = "A"
    effective_from: date | None = None
    effective_to: date | None = None
    serial_from: int | None = None
    serial_to: int | None = None


@dataclass
class OOp:
    seq: int
    group_id: str
    setup_minutes: float = 0.0
    run_minutes: float = 0.0
    run_per: str = "unit"
    units_per_panel: int | None = None
    units_per_batch: int | None = None
    queue_minutes: float = 0.0
    move_minutes: float = 0.0
    wait_minutes: float = 0.0
    yield_pct: float = 100.0


@dataclass
class ORouting:
    id: str
    item_id: str
    ops: list[OOp] = field(default_factory=list)
    status: str = "released"
    priority: int = 1
    version: int = 1
    revision: str = "A"
    code: str = "STD"
    effective_from: date | None = None
    effective_to: date | None = None
    serial_from: int | None = None
    serial_to: int | None = None


@dataclass
class OLine:
    id: str
    group_id: str
    speed_factor: float = 1.0
    active: bool = True
    eligible_families: list[str] = field(default_factory=list)
    eligible_item_ids: list[str] = field(default_factory=list)


@dataclass
class OSupplier:
    id: str
    code: str
    lead_time_days: int | None = None
    active: bool = True


@dataclass
class OItemSupplier:
    id: str
    item_id: str
    supplier_id: str
    lead_time_days: int | None = None
    min_order_qty: float = 0.0
    order_multiple: float = 0.0
    units_per_purchase_unit: float = 1.0
    preferred: bool = False
    active: bool = True


# ---------------------------------------------------------------- transactional data (8.2 MrpSnapshot)


@dataclass
class OBalance:
    id: str
    item_id: str
    location_id: str
    location_kind: str                 # stores | line_side | inspection | quarantine
    qty_on_hand: float
    qty_reserved: float = 0.0
    lot_id: str | None = None
    lot_code: str | None = None
    expires_on: date | None = None
    hold: bool = False
    last_receipt_on: date | None = None


@dataclass
class OReservation:
    wo_component_id: str
    balance_id: str
    qty: float


@dataclass
class OSchedule:
    doc_type: str                      # po | pr
    doc_id: str
    number: str
    doc_status: str
    line_id: str
    line_no: int
    schedule_id: str
    seq: int
    item_id: str
    open_qty: float
    requested_date: date
    confirmed_date: date | None = None
    supplier_id: str | None = None


@dataclass
class ODemand:
    order_id: str
    number: str
    line_id: str
    line_no: int
    item_id: str
    open_qty: float
    due_date: date
    priority: int = 5                  # effective priority
    demand_type: str = "customer"
    program: str | None = None
    customer: str = ""
    serial_from: int | None = None
    serial_to: int | None = None


@dataclass
class OWoComponent:
    id: str
    item_id: str
    open_qty: float
    operation_seq: int | None = None


@dataclass
class OWorkOrder:
    id: str
    number: str
    status: str                        # planned | released | in_progress
    item_id: str
    open_qty: float
    start_date: date
    due_date: date
    priority: int = 5
    serial_from: int | None = None
    serial_to: int | None = None
    routing_id: str | None = None
    components: list[OWoComponent] = field(default_factory=list)


@dataclass
class OExtraDemand:
    item_id: str
    qty: float
    due_date: date
    priority: int = 5
    serial_from: int | None = None
    serial_to: int | None = None
    label: str = ""


@dataclass
class OParams:
    """MrpParams (8.2) as the oracle needs them. `as_of` is the resolved date (the snapshot's)."""
    as_of: date
    horizon_days: int | None = None
    allocation: str = "priority"
    alternates: str = "when_short"
    safety_stock: bool = True
    include_pr_supply: bool = True
    protect_programs: list[str] = field(default_factory=list)
    demand_filter: dict[str, Any] | None = None    # {order_ids, programs, types}
    exclude_demand_line_ids: list[str] = field(default_factory=list)
    extra_demand: list[OExtraDemand] = field(default_factory=list)
    supply_date_overrides: dict[str, date] = field(default_factory=dict)   # schedule_id or wo_id -> date
    lead_time_overrides: dict[str, int] = field(default_factory=dict)      # item_id -> days


@dataclass
class OPlant:
    params: OParams
    items: dict[str, OItem] = field(default_factory=dict)
    boms: list[OBom] = field(default_factory=list)
    routings: list[ORouting] = field(default_factory=list)
    lines: list[OLine] = field(default_factory=list)
    suppliers: dict[str, OSupplier] = field(default_factory=dict)
    item_suppliers: list[OItemSupplier] = field(default_factory=list)
    balances: list[OBalance] = field(default_factory=list)
    reservations: list[OReservation] = field(default_factory=list)
    schedules: list[OSchedule] = field(default_factory=list)
    demand: list[ODemand] = field(default_factory=list)
    work_orders: list[OWorkOrder] = field(default_factory=list)
    holidays: frozenset[date] = frozenset()
    workdays: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat")
    day_minutes: float = 480.0
    planning_horizon_days: int = 90
    release_window_days: int = 7
    defer_tolerance_days: int = 7


# ---------------------------------------------------------------- results


@dataclass
class OPeg:
    supply_item_id: str
    supply_node: int
    requirement_item_id: str
    requirement_node: int
    qty: float


@dataclass
class OReq:
    item_id: str
    node: int
    kind: str          # demand | extra_demand | safety_stock | planned_component | wo_component
    need_date: date
    qty: float
    source: tuple[Any, ...]   # ("demand", line_id) | ("extra", idx) | ("ss", item_id)
    #                           | ("wo_component", wo_id, component_id) | ("planned_component", parent_planned_no)
    segment: tuple[int, int] | None = None
    rank: tuple[Any, ...] | None = None
    pegs: list[OPeg] = field(default_factory=list)
    satisfied_date: date | None = None
    late_days: int = 0

    @property
    def pegged(self) -> float:
        return sum(p.qty for p in self.pegs)


@dataclass
class OSup:
    item_id: str
    node: int
    kind: str          # stock | inspection | po | pr | wo | planned
    qty: float
    avail_date: date
    ref: tuple[Any, ...]      # ("balance", balance_id) | ("reservation", balance_id, component_id)
    #                           | ("schedule", schedule_id) | ("wo", wo_id) | ("planned", planned_no)
    expires_on: date | None = None
    pegged: float = 0.0
    pegs: list[OPeg] = field(default_factory=list)
    projected_date: date | None = None
    component_nodes: list[tuple[str, int]] = field(default_factory=list)   # (child item, requirement node)
    planned_no: int | None = None
    bound_component_id: str | None = None   # reservation supplies only
    # make supplies (wo / planned make): dates used by the forward pass
    start_date: date | None = None
    due_date: date | None = None
    comp_ready: date | None = None
    ready: date | None = None

    @property
    def remaining(self) -> float:
        return self.qty - self.pegged


@dataclass
class OPlanned:
    planned_no: int
    kind: str          # make | buy
    item_id: str
    qty: float
    need_date: date
    start_date: date
    dock_date: date | None
    segment: tuple[int, int] | None
    order_key: str
    supplier_id: str | None = None
    bom_id: str | None = None
    routing_id: str | None = None
    release_status: str = "later"
    projected_start: date | None = None
    projected_due: date | None = None
    late_days: int = 0
    lot_note: str = ""
    supply_node: int = 0


@dataclass
class ODemandProj:
    key: tuple[Any, ...]       # ("demand", line_id) | ("extra", idx)
    item_id: str
    qty: float
    due_date: date
    projected_date: date | None
    late_days: int
    status: str
    limiting: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OException:
    code: str
    severity: str
    item_id: str | None
    subject: tuple[str, Any]   # (type, id)
    date: date | None = None
    qty: float | None = None
    days: int | None = None
    suggested: dict[str, Any] | None = None


@dataclass
class OResult:
    as_of: date
    horizon_end: date
    kind: str
    requirements: dict[str, list[OReq]]
    supplies: dict[str, list[OSup]]
    planned: list[OPlanned]
    demand: list[ODemandProj]
    exceptions: list[OException]
    iterations: int
    llc: dict[str, int]
    directives: dict[tuple[str, str], float] = field(default_factory=dict)

    def planned_by_no(self) -> dict[int, OPlanned]:
        return {p.planned_no: p for p in self.planned}

    def exception_codes(self) -> set[str]:
        return {e.code for e in self.exceptions}

    def exceptions_of(self, code: str) -> list[OException]:
        return [e for e in self.exceptions if e.code == code]
