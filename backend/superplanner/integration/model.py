"""Integration console contract (M5-DESIGN 4; frozen at S0)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SOR_ENTITIES = ("items", "boms", "routings", "suppliers", "item_suppliers", "purchase_orders", "po_receipts",
                "demand_orders", "purchase_requests", "work_orders", "floor", "transfers", "stock")
SOR_DEFAULTS: dict[str, str] = {
    "items": "erp", "boms": "erp", "routings": "erp", "suppliers": "erp", "item_suppliers": "erp",
    "purchase_orders": "erp", "po_receipts": "superplanner", "demand_orders": "erp", "purchase_requests": "superplanner",
    "work_orders": "superplanner", "floor": "superplanner", "transfers": "superplanner", "stock": "superplanner"}
SHARED_ALLOWED = ("items", "suppliers")
SorValue = Literal["erp", "superplanner", "shared"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SettingsIn(_In):
    enabled: bool = False
    adapter: Literal["generic_v1"] = "generic_v1"
    plant_code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,31}$")]
    sor: dict[Literal["items", "boms", "routings", "suppliers", "item_suppliers", "purchase_orders", "po_receipts",
                      "demand_orders", "purchase_requests", "work_orders", "floor", "transfers", "stock"],
              SorValue] = Field(default_factory=dict)
    #: 14 Q2: who books goods receipts against POs (`erp` = ERP-owned, inbound `po_receipt` records post them)
    goods_receipts_owner: Literal["erp", "superplanner"] = "superplanner"
    filedrop_enabled: bool = False
    export_enabled: bool = False
    export_interval_minutes: Annotated[int, Field(ge=5, le=1440)] = 15


class SettingsRecord(BaseModel):
    enabled: bool
    adapter: str
    plant_code: str
    sor: dict[str, str]
    goods_receipts_owner: str
    filedrop_enabled: bool
    export_enabled: bool
    export_interval_minutes: int
    row_version: int
    adapters: list[str] = Field(default_factory=lambda: ["generic_v1"])


class EndpointIn(_In):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=500)]
    event_types: Annotated[list[Annotated[str, StringConstraints(max_length=48)]], Field(max_length=20)] = \
        Field(default_factory=list)                       # [] = all
    secret: Annotated[str, StringConstraints(min_length=16, max_length=200)] | None = None   # None on PUT: keep
    active: bool = True


class EndpointRecord(BaseModel):
    id: str
    name: str
    url: str
    event_types: list[str]
    active: bool
    cursor: int
    secret_set: bool = True
    pending: int = 0
    dead: int = 0
    row_version: int
    created_at: datetime


class ValueMapRow(_In):
    domain: Literal["uom", "location", "reason", "status"]
    external_value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    internal_value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class ValueMapsIn(_In):
    rows: Annotated[list[ValueMapRow], Field(max_length=5000)]


class MappingProfileIn(_In):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    file_pattern: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    mapping: dict[str, Any]


class DeliveryRecord(BaseModel):
    id: str
    endpoint_id: str
    event_seq: int
    event_type: str | None = None
    status: Literal["pending", "delivered", "dead", "parked", "retry"]   # parked: skipped by FIFO; retry: un-parked
    attempts: int
    next_attempt_at: datetime | None = None
    last_error: str | None = None
    last_status_code: int | None = None
    delivered_at: datetime | None = None
    created_at: datetime


class ReconciliationIn(_In):
    entities: Annotated[list[Literal["stock", "purchase_orders", "items"]], Field(min_length=1, max_length=3)]
    snapshot: Literal["inline", "file", "adapter"] = "inline"
    records: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)   # inline: entity -> v1 records
    file_name: Annotated[str, StringConstraints(max_length=200)] | None = None


class ReconciliationRecord(BaseModel):
    id: str
    entities: list[str]
    status: Literal["queued", "running", "completed", "failed"]
    summary: dict[str, Any] | None = None     # per entity: {missing_in_sp, missing_in_erp, different, sor_conflicts}
    results: dict[str, Any] | None = None
    created_at: datetime
    finished_at: datetime | None = None


class FiledropStatus(BaseModel):
    enabled: bool
    root: str | None
    inbox: list[dict[str, Any]] = Field(default_factory=list)
    recent: list[dict[str, Any]] = Field(default_factory=list)   # processed files with result counts
    last_poll_at: datetime | None = None
