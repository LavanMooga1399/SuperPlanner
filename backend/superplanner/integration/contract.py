"""`superplanner.v1` - the vendor-neutral integration contract (M5-DESIGN 4.2; frozen at S0).

Records carry `ref` (the stable external key; it becomes `external_ref` where the entity has one) and reference other
records by external keys (`*_ref`, falling back to natural keys: part numbers, codes). Fields otherwise mirror the
M1-M4 inputs. A batch is `{schema, entity, mode, records}`; an outbound event is `{schema, id, type, occurred_at,
plant, actor, data}`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SCHEMA = "superplanner.v1"
MAX_BATCH_RECORDS = 50_000
SYNC_LIMIT = 500                    # > SYNC_LIMIT records -> 202 + job (4.3)
CHUNK = 2_000

Ref = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64,
                                       pattern=r"^[^\x00-\x1f\x7f]+$")]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
Text = Annotated[str, StringConstraints(max_length=500)]
Qty = Annotated[float, Field(ge=0, le=1_000_000_000)]

ENTITIES: tuple[str, ...] = ("item", "bom", "routing", "supplier", "item_supplier", "stock_snapshot",
                             "purchase_order", "po_receipt", "demand_order", "work_order")
Entity = Literal["item", "bom", "routing", "supplier", "item_supplier", "stock_snapshot", "purchase_order",
                 "po_receipt", "demand_order", "work_order", "purchase_request"]
EVENT_TYPES: tuple[str, ...] = (
    "work_order.created", "work_order.released", "work_order.completed", "work_order.closed",
    "work_order.cancelled", "purchase_request.submitted", "purchase_request.approved", "inventory.posting",
    "floor.operation_completed", "schedule.published", "eco.implemented", "transfer_order.shipped",
    "transfer_order.received")


class V1(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemV1(V1):
    ref: Ref
    part_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    revision: Annotated[str, StringConstraints(max_length=16)] = "A"
    description: Text = ""
    uom: Code = "EA"
    make_buy: Literal["make", "buy", "phantom"] = "buy"
    active: bool = True
    standard_cost: Annotated[float, Field(ge=0)] | None = None
    # planning fields are SuperPlanner-owned (4.4) and ignored when the item SoR is `erp`
    lead_time_days: Annotated[int, Field(ge=0, le=3650)] | None = None
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


class BomLineV1(V1):
    child_ref: Ref
    find_number: Annotated[str, StringConstraints(max_length=16)]
    qty_per: Annotated[float, Field(gt=0)]
    uom: Code | None = None
    scrap_pct: Annotated[float, Field(ge=0, lt=100)] = 0
    ref_designators: Annotated[str, StringConstraints(max_length=2000)] = ""
    operation_seq: Annotated[int, Field(ge=1)] | None = None


class BomV1(V1):
    ref: Ref
    parent_ref: Ref
    revision: Annotated[str, StringConstraints(max_length=16)] | None = None
    version: Annotated[int, Field(ge=1)] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status: Literal["draft", "released", "obsolete"] = "released"
    lines: list[BomLineV1] = Field(default_factory=list)


class OperationV1(V1):
    seq: Annotated[int, Field(ge=1, le=9999)]
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    group_code: Code
    setup_minutes: Annotated[float, Field(ge=0)] = 0
    run_minutes: Annotated[float, Field(ge=0)] = 0
    run_per: Literal["unit", "panel", "batch"] = "unit"
    units_per_batch: Annotated[int, Field(ge=1)] | None = None
    labor: Literal["attended", "unattended"] = "attended"
    crew_size: Annotated[int, Field(ge=0, le=50)] = 1


class RoutingV1(V1):
    ref: Ref
    item_ref: Ref
    code: Code = "STD"
    revision: Annotated[str, StringConstraints(max_length=16)] | None = None
    version: Annotated[int, Field(ge=1)] | None = None
    status: Literal["draft", "released", "obsolete"] = "released"
    operations: list[OperationV1] = Field(default_factory=list)


class SupplierV1(V1):
    ref: Ref
    code: Code
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    lead_time_days: Annotated[int, Field(ge=0)] | None = None
    active: bool = True


class ItemSupplierV1(V1):
    ref: Ref
    item_ref: Ref
    supplier_ref: Ref
    supplier_part_number: Annotated[str, StringConstraints(max_length=64)] = ""
    lead_time_days: Annotated[int, Field(ge=0)] | None = None
    moq: Qty | None = None
    order_multiple: Qty | None = None
    price: Qty | None = None
    preferred: bool | None = None          # SuperPlanner-owned (4.4)


class StockSnapshotV1(V1):
    ref: Ref
    item_ref: Ref
    location_code: Code
    lot_code: Annotated[str, StringConstraints(max_length=40)] | None = None
    qty: Annotated[float, Field(ge=-1_000_000_000, le=1_000_000_000)]
    as_at: datetime


class PoScheduleV1(V1):
    seq: Annotated[int, Field(ge=1)]
    requested_date: date
    confirmed_date: date | None = None
    qty: Annotated[float, Field(gt=0)]
    received_qty: Qty | None = None        # read-only (ignored inbound)


class PoLineV1(V1):
    line_no: Annotated[int, Field(ge=1)]
    item_ref: Ref
    unit_price: Qty | None = None
    schedules: list[PoScheduleV1] = Field(min_length=1)


class PurchaseOrderV1(V1):
    ref: Ref
    number: Code
    supplier_ref: Ref
    status: Literal["draft", "open", "closed", "cancelled"] = "open"
    order_date: date | None = None
    currency: Annotated[str, StringConstraints(max_length=8)] = ""
    lines: list[PoLineV1] = Field(min_length=1)


class PoReceiptV1(V1):
    ref: Ref                               # the ERP receipt document line key (idempotency per record)
    po_ref: Ref
    line_no: Annotated[int, Field(ge=1)]
    schedule_seq: Annotated[int, Field(ge=1)]
    location_code: Code
    qty: Annotated[float, Field(gt=0)]
    lot_code: Annotated[str, StringConstraints(max_length=40)] | None = None
    received_on: date


class DemandLineV1(V1):
    line_no: Annotated[int, Field(ge=1)]
    item_ref: Ref
    qty: Annotated[float, Field(gt=0)]
    due_date: date
    priority: Annotated[int, Field(ge=1, le=9)] | None = None   # SuperPlanner-owned (4.4)


class DemandOrderV1(V1):
    ref: Ref
    number: Code
    demand_type: Literal["customer", "forecast", "program", "safety"] = "customer"
    customer: Annotated[str, StringConstraints(max_length=200)] = ""
    program: Code | None = None
    lines: list[DemandLineV1] = Field(min_length=1)


class WorkOrderV1(V1):
    ref: Ref
    number: Code
    item_ref: Ref
    qty: Annotated[float, Field(gt=0)]
    due_date: date
    start_date: date | None = None
    priority: Annotated[int, Field(ge=1, le=9)] = 5


RECORD_MODELS: dict[str, type[V1]] = {
    "item": ItemV1, "bom": BomV1, "routing": RoutingV1, "supplier": SupplierV1, "item_supplier": ItemSupplierV1,
    "stock_snapshot": StockSnapshotV1, "purchase_order": PurchaseOrderV1, "po_receipt": PoReceiptV1,
    "demand_order": DemandOrderV1, "work_order": WorkOrderV1}


class V1Batch(V1):
    schema_: Literal["superplanner.v1"] = Field(alias="schema")
    entity: Entity
    mode: Literal["upsert", "replace_children", "delete"] = "upsert"
    records: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=MAX_BATCH_RECORDS)]

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RecordResult(V1):
    ref: str
    status: Literal["created", "updated", "unchanged", "rejected"]
    id: str | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)


class BatchResult(V1):
    id: str
    entity: str
    mode: str
    status: Literal["queued", "running", "completed", "failed"]
    counts: dict[str, int] = Field(default_factory=dict)        # created / updated / unchanged / rejected
    results: list[RecordResult] | None = None
    received_at: datetime
    finished_at: datetime | None = None


class V1Event(V1):
    schema_: Literal["superplanner.v1"] = Field(default="superplanner.v1", alias="schema")
    id: int                                 # outbox seq
    type: str
    occurred_at: datetime
    plant: dict[str, Any]                   # {code, owner_id}
    actor: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def parse_record(entity: str, raw: dict[str, Any]) -> V1:
    return RECORD_MODELS[entity].model_validate(raw)


__all__ = ["CHUNK", "ENTITIES", "EVENT_TYPES", "RECORD_MODELS", "SCHEMA", "SYNC_LIMIT", "BatchResult",
           "RecordResult", "V1Batch", "V1Event", "parse_record"] + [m.__name__ for m in RECORD_MODELS.values()]
