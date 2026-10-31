"""API-only request bodies of the M2 endpoints (M2-DESIGN 12.3); entity bodies are the `mfg.model_m2` Inputs and
`mfg.mrp.model.MrpParams`."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ...mfg.limits import KITTING_CHECK_MAX_WOS, MAX_CONVERT_ORDERS
from ...mfg.model import Code, EntityId, PlanDate, Qty, Text500


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteRequest(_Strict):
    note: Text500 = ""


class RejectRequest(_Strict):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ConvertPrRequest(_Strict):
    line_ids: Annotated[list[EntityId], Field(max_length=500)] | None = None
    supplier_id: EntityId | None = None
    number: Code | None = None
    issue: bool = False


class ReleaseWoRequest(_Strict):
    reserve: bool = False
    #: M4-DESIGN 4.1: release despite a component shortage of the first operation (stored in `release_override`)
    override_reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class ComponentIdsRequest(_Strict):
    component_ids: Annotated[list[EntityId], Field(max_length=4000)] | None = None


class KittingCheckRequest(_Strict):
    wo_ids: Annotated[list[EntityId], Field(max_length=KITTING_CHECK_MAX_WOS)] | None = None
    order: Literal["priority", "start_date"] = "priority"
    horizon_days: Annotated[int, Field(ge=0, le=365)] = 14


class RunUpdate(_Strict):
    label: Annotated[str, StringConstraints(max_length=100)] = ""
    note: Text500 = ""
    pinned: bool = False


class ConvertOrder(_Strict):
    id: EntityId
    qty: Qty | None = None
    start_date: PlanDate | None = None
    need_date: PlanDate | None = None
    supplier_id: EntityId | None = None


class ConvertPlannedRequest(_Strict):
    mode: Literal["firm", "release"] = "firm"
    orders: Annotated[list[ConvertOrder], Field(min_length=1, max_length=MAX_CONVERT_ORDERS)]
    pr_grouping: Literal["per_supplier", "per_order"] = "per_supplier"
    add_to_pr_id: EntityId | None = None
    reserve: bool = False


class SampleLoadRequestM2(_Strict):
    replace: bool = False
    anchor: date | None = None
    include_transactions: bool = True


__all__ = ["ComponentIdsRequest", "ConvertOrder", "ConvertPlannedRequest", "ConvertPrRequest", "KittingCheckRequest",
           "NoteRequest", "RejectRequest", "ReleaseWoRequest", "RunUpdate", "SampleLoadRequestM2"]
