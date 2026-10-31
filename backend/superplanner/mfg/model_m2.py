"""M2 domain models (M2-DESIGN 3; contract frozen at milestone A1): inputs, records, refs and the MRP input
snapshot rows.

Conventions as `mfg.model` (M1-DESIGN 3): `<Entity>Input` is what POST/PUT accept (`extra="forbid"`), `<Entity>Record`
is the response. Single-model rules are model validators (422 `VALIDATION_ERROR`); rules that need stored data
(stock, statuses, count-UoM integrality, ...) live in the pure rule modules (`inventory`, `purchasing`, `demand`,
`workorders`) and the services, with their specific error codes. All M2 quantities are in the item's stock UoM.
Records built from rows use `model_construct` (validated on write).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Any, Literal, NamedTuple

from pydantic import Field, StringConstraints, model_validator

from .limits import MAX_DOC_LINES, MAX_POSTING_LINES, MAX_SCHEDULES_PER_LINE, MAX_WO_COMPONENTS
from .model import (Code, EntityId, ExtRef, FindNumber, ItemRef, MfgModel, Money, Name, NonNegQty, PlanDate, Qty,
                    Ref, Text500, _short, _unique)

# ---------------------------------------------------------------- common types (3)

EPS = 1e-6
DocNumber = Code
LotCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64,
                                           pattern=r"^[^\x00-\x1f\x7f]+$")]
SignedQty = Annotated[float, Field(ge=-1_000_000_000, le=1_000_000_000)]
Priority = Annotated[int, Field(ge=1, le=9)]
Role = Literal["viewer", "planner", "purchaser", "store_keeper", "approver", "operator", "supervisor"]   # M4 roles
ROLES: tuple[str, ...] = ("viewer", "planner", "purchaser", "store_keeper", "approver", "operator", "supervisor")
LocationKind = Literal["stores", "line_side", "inspection", "quarantine"]
LOCATION_KINDS: tuple[str, ...] = ("stores", "line_side", "inspection", "quarantine")
NETTABLE_NOW_KINDS: tuple[str, ...] = ("stores", "line_side")
Serial = Annotated[int, Field(ge=1, le=1_000_000_000)]
LeadDays = Annotated[int, Field(ge=0, le=730)]
Currency = _short(8)
SupplierLot = _short(64)
PostingType = Literal["receipt_misc", "issue_misc", "adjust", "count", "transfer", "po_receipt", "wo_issue",
                      "wo_return", "wo_receipt", "ship"]
POSTING_TYPES: tuple[str, ...] = ("receipt_misc", "issue_misc", "adjust", "count", "transfer", "po_receipt",
                                  "wo_issue", "wo_return", "wo_receipt", "ship")
DemandType = Literal["customer", "internal", "spares", "project"]
DEMAND_TYPES: tuple[str, ...] = ("customer", "internal", "spares", "project")
PR_STATUSES: tuple[str, ...] = ("draft", "submitted", "approved", "rejected", "ordered", "cancelled")
PO_STATUSES: tuple[str, ...] = ("draft", "open", "partially_received", "received", "closed", "cancelled")
DEMAND_STATUSES: tuple[str, ...] = ("draft", "open", "closed", "cancelled")
WO_STATUSES: tuple[str, ...] = ("planned", "released", "in_progress", "completed", "closed", "cancelled")
DOC_SOURCES: tuple[str, ...] = ("manual", "mrp", "import")


def _serial_pair(m: Any, qty: float | None, *, qty_rule: bool = True) -> None:
    if (m.serial_from is None) != (m.serial_to is None):
        raise ValueError("serial_from and serial_to must both be set or both be empty")
    if m.serial_from is not None and m.serial_from > m.serial_to:
        raise ValueError("serial_from must not be greater than serial_to")


# ---------------------------------------------------------------- refs

class LocationRef(MfgModel):
    id: str
    code: str
    name: str
    kind: LocationKind


class LotRef(MfgModel):
    id: str
    lot_code: str
    expires_on: date | None
    hold: bool


class ActorRef(MfgModel):
    id: str | None
    name: str


class DocRef(MfgModel):
    type: Literal["po", "pr", "wo", "demand"]
    id: str
    number: str
    line_no: int | None = None
    schedule_seq: int | None = None
    label: str


class NumberRef(MfgModel):
    id: str
    number: str


class _Stamped(MfgModel):
    id: EntityId
    row_version: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- location (3.2)

class LocationInput(MfgModel):
    code: Code
    name: Name
    kind: LocationKind
    receipt_default: bool = False
    active: bool = True
    external_ref: ExtRef | None = None
    note: Text500 = ""


class LocationRecord(LocationInput, _Stamped):
    pass


# ---------------------------------------------------------------- supplier, item-supplier (3.3)

class SupplierInput(MfgModel):
    code: Code
    name: Name
    lead_time_days: LeadDays | None = None
    currency: Currency = ""
    contact_name: _short(200) = ""
    email: _short(200) = ""
    phone: _short(50) = ""
    address: Text500 = ""
    active: bool = True
    external_ref: ExtRef | None = None
    note: Text500 = ""


class SupplierRecord(SupplierInput, _Stamped):
    item_count: int = 0


class ItemSupplierInput(MfgModel):
    item_id: EntityId
    supplier_id: EntityId
    supplier_part_number: _short(64) = ""
    lead_time_days: LeadDays | None = None
    min_order_qty: NonNegQty = 0
    order_multiple: NonNegQty = 0
    purchase_unit: Code | None = None
    units_per_purchase_unit: Annotated[float, Field(gt=0, le=1_000_000)] = 1
    unit_price: Money | None = None
    currency: Currency = ""
    preferred: bool = False
    active: bool = True
    note: Text500 = ""


class ItemSupplierRecord(ItemSupplierInput, _Stamped):
    item: ItemRef
    supplier: Ref


# ---------------------------------------------------------------- lots, balances, ledger (3.4)

class LotUpdate(MfgModel):
    expires_on: PlanDate | None = None
    supplier_lot: SupplierLot = ""
    hold: bool = False
    note: Text500 = ""


class LotRecord(_Stamped):
    item: ItemRef
    item_id: str
    lot_code: str
    expires_on: date | None = None
    received_on: date | None = None
    supplier_lot: str = ""
    hold: bool = False
    note: str = ""
    on_hand: float = 0.0


class BalanceRow(MfgModel):
    id: str
    item: ItemRef
    location: LocationRef
    lot: LotRef | None
    qty_on_hand: float
    qty_reserved: float
    qty_available: float
    nettable: bool
    last_receipt_on: date | None
    value: float | None
    updated_at: datetime


class TransactionRow(MfgModel):
    id: str
    seq: int
    posting_id: str
    posting_number: str
    line_no: int
    txn_type: str
    txn_date: date
    item: ItemRef
    location: LocationRef
    lot: LotRef | None
    qty: float
    balance_after: float
    unit_cost: float | None
    ref: DocRef | None
    actor: ActorRef
    created_at: datetime


class PostingWarning(MfgModel):
    code: str
    message: str


class PostingRecord(MfgModel):
    id: str
    number: str
    type: str
    txn_date: date
    note: str
    reason_code: str | None
    actor: ActorRef
    created_at: datetime
    reversal_of: NumberRef | None = None
    reversed_by: NumberRef | None = None
    lines: list[TransactionRow] = Field(default_factory=list)
    warnings: list[PostingWarning] = Field(default_factory=list)


class ReservationRow(MfgModel):
    id: str
    wo: NumberRef
    component_id: str
    item: ItemRef
    balance_id: str
    location: LocationRef
    lot: LotRef | None
    qty: float
    created_at: datetime


# ---------------------------------------------------------------- posting inputs (4.1)

class _LineBase(MfgModel):
    lot_code: LotCode | None = None


class ReceiptMiscLine(_LineBase):
    item_id: EntityId
    location_id: EntityId
    qty: Qty
    expires_on: PlanDate | None = None
    supplier_lot: SupplierLot = ""
    unit_cost: Money | None = None


class IssueMiscLine(_LineBase):
    item_id: EntityId
    location_id: EntityId
    qty: Qty


class AdjustLine(_LineBase):
    item_id: EntityId
    location_id: EntityId
    qty: SignedQty
    expires_on: PlanDate | None = None

    @model_validator(mode="after")
    def _nonzero(self) -> "AdjustLine":
        if abs(self.qty) <= EPS:
            raise ValueError("an adjustment quantity must not be 0")
        return self


class CountLine(_LineBase):
    item_id: EntityId
    location_id: EntityId
    counted_qty: NonNegQty
    expires_on: PlanDate | None = None


class TransferLine(_LineBase):
    item_id: EntityId
    from_location_id: EntityId
    to_location_id: EntityId
    qty: Qty


class PoReceiptLine(_LineBase):
    schedule_id: EntityId
    location_id: EntityId | None = None
    qty: Qty
    expires_on: PlanDate | None = None
    supplier_lot: SupplierLot = ""
    unit_cost: Money | None = None


class WoIssueLine(_LineBase):
    wo_component_id: EntityId
    location_id: EntityId
    qty: Qty
    over_issue: bool = False


class WoReturnLine(_LineBase):
    wo_component_id: EntityId
    location_id: EntityId
    qty: Qty


class WoReceiptLine(_LineBase):
    wo_id: EntityId
    location_id: EntityId
    qty: NonNegQty
    scrap_qty: NonNegQty = 0
    expires_on: PlanDate | None = None

    @model_validator(mode="after")
    def _some(self) -> "WoReceiptLine":
        if self.qty + self.scrap_qty <= EPS:
            raise ValueError("qty + scrap_qty must be greater than 0")
        return self


class ShipLine(_LineBase):
    demand_line_id: EntityId
    location_id: EntityId
    qty: Qty


class _PostingBase(MfgModel):
    txn_date: PlanDate | None = None
    note: Text500 = ""
    reason_code: Code | None = None


def _lines(cls: Any) -> Any:
    return Annotated[list[cls], Field(min_length=1, max_length=MAX_POSTING_LINES)]


class ReceiptMiscPosting(_PostingBase):
    type: Literal["receipt_misc"]
    lines: _lines(ReceiptMiscLine)


class IssueMiscPosting(_PostingBase):
    type: Literal["issue_misc"]
    lines: _lines(IssueMiscLine)


class AdjustPosting(_PostingBase):
    type: Literal["adjust"]
    lines: _lines(AdjustLine)


class CountPosting(_PostingBase):
    type: Literal["count"]
    lines: _lines(CountLine)


class TransferPosting(_PostingBase):
    type: Literal["transfer"]
    lines: _lines(TransferLine)


class PoReceiptPosting(_PostingBase):
    type: Literal["po_receipt"]
    lines: _lines(PoReceiptLine)


class WoIssuePosting(_PostingBase):
    type: Literal["wo_issue"]
    lines: _lines(WoIssueLine)


class WoReturnPosting(_PostingBase):
    type: Literal["wo_return"]
    lines: _lines(WoReturnLine)


class WoReceiptPosting(_PostingBase):
    type: Literal["wo_receipt"]
    lines: _lines(WoReceiptLine)


class ShipPosting(_PostingBase):
    type: Literal["ship"]
    lines: _lines(ShipLine)


PostingInput = Annotated[ReceiptMiscPosting | IssueMiscPosting | AdjustPosting | CountPosting | TransferPosting
                         | PoReceiptPosting | WoIssuePosting | WoReturnPosting | WoReceiptPosting | ShipPosting,
                         Field(discriminator="type")]
POSTING_MODELS: dict[str, type[MfgModel]] = {
    "receipt_misc": ReceiptMiscPosting, "issue_misc": IssueMiscPosting, "adjust": AdjustPosting,
    "count": CountPosting, "transfer": TransferPosting, "po_receipt": PoReceiptPosting, "wo_issue": WoIssuePosting,
    "wo_return": WoReturnPosting, "wo_receipt": WoReceiptPosting, "ship": ShipPosting}


# ---------------------------------------------------------------- purchase documents (3.5)

class ScheduleInput(MfgModel):
    id: EntityId | None = None
    seq: Annotated[int, Field(ge=1, le=999)] | None = None
    requested_date: PlanDate
    confirmed_date: PlanDate | None = None
    qty: Qty


class PurchaseLineInput(MfgModel):
    id: EntityId | None = None
    line_no: Annotated[int, Field(ge=1, le=9999)] | None = None
    item_id: EntityId
    unit_price: Money | None = None
    note: Text500 = ""
    schedules: Annotated[list[ScheduleInput], Field(min_length=1, max_length=MAX_SCHEDULES_PER_LINE)]

    @model_validator(mode="after")
    def _seqs(self) -> "PurchaseLineInput":
        _unique([s.seq for s in self.schedules if s.seq is not None], "schedule seq numbers of a line")
        _unique([s.id for s in self.schedules if s.id is not None], "schedule ids of a line")
        return self


class PurchaseDocInput(MfgModel):
    number: DocNumber | None = None
    supplier_id: EntityId | None = None
    currency: Currency | None = None          # None: the supplier's (or "")
    order_date: PlanDate | None = None
    note: Text500 = ""
    external_ref: ExtRef | None = None
    lines: Annotated[list[PurchaseLineInput], Field(min_length=1, max_length=MAX_DOC_LINES)]

    @model_validator(mode="after")
    def _nos(self) -> "PurchaseDocInput":
        _unique([ln.line_no for ln in self.lines if ln.line_no is not None], "line numbers")
        _unique([ln.id for ln in self.lines if ln.id is not None], "line ids")
        return self


class ScheduleRecord(MfgModel):
    id: str
    seq: int
    requested_date: date
    confirmed_date: date | None
    qty: float
    received_qty: float
    open_qty: float
    closed: bool
    dock_date: date
    available_date: date
    overdue: bool
    overdue_days: int


class DocLineRef(MfgModel):
    doc_id: str
    number: str
    line_no: int


class PurchaseLineRecord(MfgModel):
    id: str
    line_no: int
    item_id: str
    item: ItemRef
    unit_price: float | None
    note: str
    status: Literal["open", "converted", "cancelled", "closed"]
    qty: float
    received_qty: float
    open_qty: float
    converted_to: DocLineRef | None = None
    source_pr: DocLineRef | None = None
    schedules: list[ScheduleRecord] = Field(default_factory=list)


class UserRef(MfgModel):
    id: str
    name: str


class PurchaseDocRecord(MfgModel):
    id: str
    doc_type: Literal["pr", "po"]
    number: str
    status: str
    supplier_id: str | None
    supplier: Ref | None
    currency: str
    order_date: date | None
    note: str
    external_ref: str | None
    source: str
    source_run_no: int | None
    submitted_at: datetime | None
    submitted_by: UserRef | None
    approved_at: datetime | None
    approved_by: UserRef | None
    rejected_reason: str
    value: float | None
    open_value: float | None
    overdue_count: int
    row_version: int
    created_at: datetime
    updated_at: datetime
    lines: list[PurchaseLineRecord] = Field(default_factory=list)


class PurchaseDocSummary(MfgModel):
    id: str
    doc_type: Literal["pr", "po"]
    number: str
    status: str
    supplier: Ref | None
    currency: str
    order_date: date | None
    source: str
    source_run_no: int | None
    value: float | None
    open_value: float | None
    overdue_count: int
    line_count: int
    next_dock_date: date | None
    row_version: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- demand orders (3.6)

class DemandLineInput(MfgModel):
    id: EntityId | None = None
    line_no: Annotated[int, Field(ge=1, le=9999)] | None = None
    item_id: EntityId
    qty: Qty
    due_date: PlanDate
    serial_from: Serial | None = None
    serial_to: Serial | None = None
    priority: Priority | None = None
    note: Text500 = ""

    @model_validator(mode="after")
    def _serials(self) -> "DemandLineInput":
        _serial_pair(self, self.qty)
        return self


class DemandOrderInput(MfgModel):
    number: DocNumber | None = None
    demand_type: DemandType
    customer: _short(200) = ""
    program: Code | None = None
    priority: Priority = 5
    note: Text500 = ""
    external_ref: ExtRef | None = None
    lines: Annotated[list[DemandLineInput], Field(min_length=1, max_length=MAX_DOC_LINES)]

    @model_validator(mode="after")
    def _nos(self) -> "DemandOrderInput":
        _unique([ln.line_no for ln in self.lines if ln.line_no is not None], "line numbers")
        _unique([ln.id for ln in self.lines if ln.id is not None], "line ids")
        return self


class DemandProjection(MfgModel):
    run_id: str
    run_no: int
    projected_date: date | None
    late_days: int
    status: str


class DemandLineRecord(MfgModel):
    id: str
    line_no: int
    item_id: str
    item: ItemRef
    qty: float
    due_date: date
    serial_from: int | None
    serial_to: int | None
    priority: int | None
    note: str
    shipped_qty: float
    open_qty: float
    line_status: Literal["open", "shipped"]
    effective_priority: int
    projection: DemandProjection | None = None


class DemandOrderRecord(MfgModel):
    id: str
    number: str
    demand_type: str
    customer: str
    program: str | None
    priority: int
    note: str
    external_ref: str | None
    status: str
    row_version: int
    created_at: datetime
    updated_at: datetime
    lines: list[DemandLineRecord] = Field(default_factory=list)


class DemandOrderSummary(MfgModel):
    id: str
    number: str
    demand_type: str
    customer: str
    program: str | None
    priority: int
    status: str
    line_count: int
    open_qty: float
    next_due: date | None
    late_lines: int | None
    row_version: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- work orders (3.7)

class WoComponentInput(MfgModel):
    id: EntityId | None = None
    item_id: EntityId
    required_qty: NonNegQty
    operation_seq: Annotated[int, Field(ge=1, le=9999)] | None = None
    find_number: FindNumber | None = None
    note: Text500 = ""


class WorkOrderInput(MfgModel):
    number: DocNumber | None = None
    item_id: EntityId
    qty: Qty
    due_date: PlanDate
    start_date: PlanDate | None = None
    priority: Priority = 5
    serial_from: Serial | None = None
    serial_to: Serial | None = None
    demand_line_id: EntityId | None = None
    note: Text500 = ""
    external_ref: ExtRef | None = None
    components: Annotated[list[WoComponentInput], Field(max_length=MAX_WO_COMPONENTS)] | None = None
    #: M4-DESIGN 3.1: receipt location of the floor's automatic receipts (None = the plant's)
    receipt_location_id: EntityId | None = None

    @model_validator(mode="after")
    def _rules(self) -> "WorkOrderInput":
        _serial_pair(self, self.qty)
        if self.start_date is not None and self.start_date > self.due_date:
            raise ValueError("start_date must not be after due_date")
        if self.components is not None:
            _unique([c.id for c in self.components if c.id is not None], "component ids")
        return self


class WoComponentRecord(MfgModel):
    id: str
    item_id: str
    item: ItemRef
    required_qty: float
    issued_qty: float
    open_qty: float
    reserved_qty: float
    operation_seq: int | None
    find_number: str | None
    alt_group: str | None
    bom_line_id: str | None
    note: str


class DocVersionRef(MfgModel):
    id: str
    revision: str | None = None
    code: str | None = None
    version: int


class DemandLineLink(MfgModel):
    id: str
    order_id: str
    order_number: str
    line_no: int


class WorkOrderRecord(MfgModel):
    id: str
    number: str
    status: str
    item_id: str
    item: ItemRef
    qty: float
    qty_completed: float
    qty_scrapped: float
    open_qty: float
    due_date: date
    start_date: date
    priority: int
    serial_from: int | None
    serial_to: int | None
    demand_line_id: str | None
    demand_line: DemandLineLink | None
    note: str
    external_ref: str | None
    bom: DocVersionRef | None
    routing: DocVersionRef | None
    source: str
    source_run_no: int | None
    source_planned_no: int | None
    released_at: datetime | None
    completed_at: datetime | None
    closed_at: datetime | None
    shortage_count: int | None = None
    row_version: int
    created_at: datetime
    updated_at: datetime
    components: list[WoComponentRecord] = Field(default_factory=list)


# ---------------------------------------------------------------- workspace members (3.8)

class MemberInput(MfgModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    roles: Annotated[list[Role], Field(min_length=1, max_length=5)]
    active: bool = True

    @model_validator(mode="after")
    def _roles(self) -> "MemberInput":
        _unique(self.roles, "roles")
        return self


class MemberUpdate(MfgModel):
    roles: Annotated[list[Role], Field(min_length=1, max_length=5)]
    active: bool = True

    @model_validator(mode="after")
    def _roles(self) -> "MemberUpdate":
        _unique(self.roles, "roles")
        return self


class MemberUser(MfgModel):
    id: str
    email: str | None
    display_name: str | None


class MemberRecord(MfgModel):
    id: str
    user: MemberUser
    roles: list[str]
    active: bool
    row_version: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- MRP input snapshot rows (8.2, 9.5)

@dataclass(frozen=True, slots=True)
class BalanceSnap:
    """A balance with `qty_on_hand > EPS` (`kind` = its location's kind; `nettable` per 3.2)."""
    id: str
    item_id: str
    location_id: str
    kind: str
    lot_id: str | None
    expires_on: date | None
    hold: bool
    qty_on_hand: float
    qty_reserved: float
    last_receipt_on: date | None
    location_active: bool = True


@dataclass(frozen=True, slots=True)
class ReservationSnap:
    wo_component_id: str
    balance_id: str
    qty: float


@dataclass(frozen=True, slots=True)
class ScheduleSnap:
    """An open supply schedule (5.5): PR lines `open` in `draft`/`submitted`/`approved` PRs; PO schedules with open
    qty, not closed, in `draft`/`open`/`partially_received` POs."""
    doc_type: str
    doc_id: str
    number: str
    doc_status: str
    line_id: str
    line_no: int
    schedule_id: str
    seq: int
    item_id: str
    supplier_id: str | None
    open_qty: float
    requested_date: date
    confirmed_date: date | None


@dataclass(frozen=True, slots=True)
class DemandSnap:
    """An open line (`open_qty > EPS`) of an `open` demand order."""
    order_id: str
    number: str
    demand_type: str
    customer: str
    program: str | None
    line_id: str
    line_no: int
    item_id: str
    open_qty: float
    due_date: date
    effective_priority: int
    serial_from: int | None
    serial_to: int | None


class WoComponentSnap(NamedTuple):
    component_id: str
    item_id: str
    open_qty: float              # required - issued (>= 0)
    operation_seq: int | None


@dataclass(frozen=True, slots=True)
class WoSnap:
    """A WO in `planned` / `released` / `in_progress`."""
    id: str
    number: str
    status: str
    item_id: str
    open_qty: float
    start_date: date
    due_date: date
    priority: int
    serial_from: int | None
    serial_to: int | None
    routing_id: str | None
    components: tuple[WoComponentSnap, ...] = field(default_factory=tuple)


def _register_inputs() -> None:
    from .model import INPUT_OF

    INPUT_OF.update({LocationRecord: LocationInput, SupplierRecord: SupplierInput,
                     ItemSupplierRecord: ItemSupplierInput})


_register_inputs()

__all__ = [n for n in dir() if not n.startswith("_") and n[0].isupper()] + ["EPS"]
