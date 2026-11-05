"""M5 mfg contract (M5-DESIGN 3.5, 5, 6; frozen at S0): genealogy, recalls, engineering changes, transfer orders."""

from __future__ import annotations

import datetime as _dtm
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, model_validator

from .model import EntityId, MfgModel, Qty

TraceKind = Literal["lot", "serial", "wo", "item_stock", "transfer", "demand_line"]
Precision = Literal["exact", "possible"]
MAX_TRACE_ROWS = 20_000
MAX_TRACE_DEPTH = 30
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(max_length=1000)]


# ---------------------------------------------------------------- genealogy (6)

class TraceNode(MfgModel):
    kind: TraceKind
    id: str
    item: dict[str, Any] | None = None          # ItemRef
    label: str
    qty: float | None = None
    precision: Precision = "exact"
    at: datetime | None = None
    status: str | None = None                   # serial status / WO status / location code
    plant: dict[str, Any] | None = None         # cross-plant node: {owner_id, code, visible}
    link: str = ""
    depth: int = 0
    children: list["TraceNode"] = Field(default_factory=list)


class TraceResult(MfgModel):
    root: TraceNode
    direction: Literal["backward", "forward"]
    depth: int
    nodes: int
    truncated: bool = False


class RecallSource(MfgModel):
    kind: Literal["lot", "serial", "wo"] | None = None
    id: EntityId | None = None
    item_id: EntityId | None = None
    supplier_lot: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None

    @model_validator(mode="after")
    def _one(self) -> "RecallSource":
        if (self.kind is None) != (self.id is None) or ((self.id is None) == (self.supplier_lot is None)):
            raise ValueError("give {kind, id} or {item_id, supplier_lot}")
        if self.supplier_lot is not None and self.item_id is None:
            raise ValueError("supplier_lot needs item_id")
        return self


class RecallInput(MfgModel):
    name: Title
    sources: Annotated[list[RecallSource], Field(min_length=1, max_length=50)]
    include_possible: bool = True


class RecallRecord(MfgModel):
    id: str
    number: str
    name: str
    sources: list[dict[str, Any]]
    include_possible: bool
    report: dict[str, Any] | None = None        # {units, lots, wos, shipments, by_customer, by_program, stock, ...}
    quarantined_at: datetime | None = None
    row_version: int
    created_at: datetime
    updated_at: datetime


class QuarantineInput(MfgModel):
    location_id: EntityId | None = None         # None: the plant's quarantine location (M2 kind quarantine)
    note: Annotated[str, StringConstraints(max_length=500)] = ""


# ---------------------------------------------------------------- engineering changes (5)

class Effectivity(MfgModel):
    mode: Literal["date", "serial", "use_up"] = "date"
    date: _dtm.date | None = None
    serial_from: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def _rule(self) -> "Effectivity":
        if self.mode == "serial" and self.serial_from is None:
            raise ValueError("serial effectivity needs serial_from")
        return self


class ChangeRequestInput(MfgModel):
    title: Title
    reason: Note = ""
    kind: Literal["eco", "ecn"] = "eco"
    priority: Annotated[int, Field(ge=1, le=9)] = 5
    effectivity: Effectivity = Field(default_factory=Effectivity)
    note: Note = ""


class Disposition(MfgModel):
    open_wos: Literal["keep", "refresh_planned", "flag"] = "flag"
    open_pos: Literal["keep", "flag_cancel"] = "flag_cancel"
    stock: Literal["use_up", "scrap", "rework"] = "use_up"


class ChangeRequestItemInput(MfgModel):
    doc_type: Literal["bom", "routing"]
    doc_id: EntityId                                # a draft
    supersedes_doc_id: EntityId | None = None
    disposition: Disposition = Field(default_factory=Disposition)


class ChangeRequestRecord(MfgModel):
    id: str
    number: str
    title: str
    reason: str
    kind: str
    source: Literal["manual", "erp"]
    status: Literal["draft", "submitted", "approved", "rejected", "implemented", "cancelled"]
    priority: int
    effectivity: dict[str, Any]
    note: str
    requested_by: dict[str, Any] | None = None
    approved_by: dict[str, Any] | None = None
    approved_at: datetime | None = None
    implemented_at: datetime | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)
    row_version: int
    created_at: datetime
    updated_at: datetime


class EcoActionInput(MfgModel):
    note: Note = ""


class ImpactResult(MfgModel):
    cr_id: str
    effectivity: dict[str, Any]
    explosion_delta: list[dict[str, Any]] = Field(default_factory=list)   # per parent: added/removed/changed
    open_wos: list[dict[str, Any]] = Field(default_factory=list)
    planned_orders: list[dict[str, Any]] = Field(default_factory=list)
    open_purchases: list[dict[str, Any]] = Field(default_factory=list)
    phase_out_stock: list[dict[str, Any]] = Field(default_factory=list)   # on hand / on order with value
    mrp_delta: list[dict[str, Any]] = Field(default_factory=list)         # demand lines whose projected date moves
    use_up_date: date | None = None
    computed_ms: int = 0


# ---------------------------------------------------------------- transfer orders (3.5)

class TransferLineInput(MfgModel):
    id: EntityId | None = None
    line_no: Annotated[int, Field(ge=1, le=9999)] | None = None
    item_id: EntityId
    qty: Qty
    ship_date: date
    receive_date: date

    @model_validator(mode="after")
    def _dates(self) -> "TransferLineInput":
        if self.receive_date < self.ship_date:
            raise ValueError("receive_date must not be before ship_date")
        return self


class TransferOrderInput(MfgModel):
    number: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None
    dest_plant_owner_id: Annotated[str, StringConstraints(pattern=r"^usr_[0-9a-z_]{1,60}$")]
    from_location_id: EntityId | None = None
    to_location_code: Annotated[str, StringConstraints(max_length=32)] | None = None
    note: Annotated[str, StringConstraints(max_length=500)] = ""
    lines: Annotated[list[TransferLineInput], Field(min_length=1, max_length=500)]


class TransferOrderRecord(MfgModel):
    id: str
    number: str
    direction: Literal["out", "in"]
    status: Literal["draft", "open", "shipped", "received", "closed", "cancelled"]
    source_plant: dict[str, Any]
    dest_plant: dict[str, Any]
    mirror_of: str | None = None
    from_location_id: str | None = None
    to_location_id: str | None = None
    note: str = ""
    lines: list[dict[str, Any]] = Field(default_factory=list)
    row_version: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- audit (7)

class AuditEventRecord(MfgModel):
    id: int
    entity_type: str
    entity_id: str
    action: str
    details: dict[str, Any]
    actor_id: str | None
    owner_id: str | None
    created_at: datetime
    chain_hash: str | None = None


__all__ = ["AuditEventRecord", "ChangeRequestInput", "ChangeRequestItemInput", "ChangeRequestRecord", "Disposition",
           "EcoActionInput", "Effectivity", "ImpactResult", "MAX_TRACE_DEPTH", "MAX_TRACE_ROWS", "QuarantineInput",
           "RecallInput", "RecallRecord", "RecallSource", "TraceNode", "TraceResult", "TransferLineInput",
           "TransferOrderInput", "TransferOrderRecord"]
