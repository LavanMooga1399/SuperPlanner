"""`/api/v1/mfg` M2 endpoints (M2-DESIGN 12.3 #78-163): 86 operations. Included next to the M1 router with
`Depends(require_user)`; every route declares exactly one permission (`require_perm`, 10.2), which first resolves the
workspace (`X-SP-Workspace`). Fixed paths precede parameterised siblings (`/mrp/runs/latest`,
`/work-orders/kitting-check`). Path ids are plain `str` (malformed / unknown / foreign -> 404).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from ...jobs.types import IDEMPOTENCY_KEY_RE
from ...mfg import limits as L
from ...mfg.model import PlanDate
from ...mfg.model_m2 import (DemandOrderInput, ItemSupplierInput, LocationInput, LotUpdate, MemberInput, MemberUpdate,
                             PostingInput, PurchaseDocInput, SupplierInput, WorkOrderInput)
from ...mfg.mrp.model import MrpParams
from ..context import AppContext, get_ctx
from ..errors import ApiError
from .access import MfgPrincipal, mfg_principal, require_perm
from .schemas_m2 import (ComponentIdsRequest, ConvertPlannedRequest, ConvertPrRequest, KittingCheckRequest, NoteRequest,
                         RejectRequest, ReleaseWoRequest, RunUpdate)
from .services import demand, inventory, locations, members, mrp, purchasing, suppliers, workorders
from .services.common import jsonable, respond

router = APIRouter(prefix="/mfg", tags=["mfg-m2"])


def _if_match() -> Any:
    return Header(default=None, alias="If-Match")


def _idem_key() -> Any:
    return Header(default=None, alias="Idempotency-Key")
# factories: a Query() object must not be shared between parameters (FastAPI would mix their names up)


def Limit() -> Any:
    return Query(default=L.PAGE_DEFAULT, ge=1, le=L.PAGE_MAX)


def Offset() -> Any:
    return Query(default=0, ge=0)


def Id() -> Any:
    return Query(default=None, max_length=64)


def QText() -> Any:
    return Query(default=None, max_length=200)


def P(perm: str) -> list[Any]:
    return [require_perm(perm)]


def _ok(body: object, status: int = 200, etag: int | None = None, headers: dict[str, str] | None = None
        ) -> JSONResponse:
    h = dict(headers or {})
    if etag is not None:
        h["ETag"] = f'"{etag}"'
    return JSONResponse(jsonable(body), status_code=status, headers=h or None)


def _no_content() -> Response:
    return Response(status_code=204)


def _idem(key: str | None) -> str | None:
    if key is None:
        return None
    k = key.strip()
    if not IDEMPOTENCY_KEY_RE.match(k):
        raise ApiError(422, "VALIDATION_ERROR", "Idempotency-Key must be 1-128 characters of A-Z a-z 0-9 . _ : -.",
                       {"errors": [{"loc": ["header", "Idempotency-Key"], "msg": "invalid key", "type": "value_error"}]})
    return k


def _file(data: bytes, name: str, media: str) -> Response:
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- 78-83 me, workspaces, members

@router.get("/me", dependencies=P("view"))
def get_me(p: MfgPrincipal = Depends(mfg_principal), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(members.me(ctx, p))


@router.get("/workspaces", dependencies=P("view"))
def get_workspaces(p: MfgPrincipal = Depends(mfg_principal), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(members.workspaces(ctx, p.user_id))


@router.get("/members", dependencies=P("owner"))
def list_members(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(members.list_members(ctx))


@router.post("/members", status_code=201, dependencies=P("owner"))
def add_member(body: MemberInput, p: MfgPrincipal = Depends(mfg_principal),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = members.add_member(ctx, body, p.owner_id)
    return respond(rec, 201, f"/members/{rec.id}")


@router.put("/members/{member_id}", dependencies=P("owner"))
def put_member(member_id: str, body: MemberUpdate, if_match: str | None = _if_match(),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(members.update_member(ctx, member_id, body, if_match))


@router.delete("/members/{member_id}", status_code=204, dependencies=P("owner"))
def delete_member(member_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    members.remove_member(ctx, member_id, if_match)
    return _no_content()


# ---------------------------------------------------------------- 84-87 locations

@router.get("/locations", dependencies=P("view"))
def list_locations(q: str | None = QText(), kind: Literal["stores", "line_side", "inspection", "quarantine"] | None = None,
                   active: bool | None = None, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(locations.list_locations(ctx, q, kind, active))


@router.post("/locations", status_code=201, dependencies=P("master_edit"))
def create_location(body: LocationInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = locations.create_location(ctx, body)
    return respond(rec, 201, f"/locations/{rec.id}")


@router.put("/locations/{location_id}", dependencies=P("master_edit"))
def put_location(location_id: str, body: LocationInput, if_match: str | None = _if_match(),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(locations.update_location(ctx, location_id, body, if_match))


@router.delete("/locations/{location_id}", status_code=204, dependencies=P("master_edit"))
def delete_location(location_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    locations.delete_location(ctx, location_id, if_match)
    return _no_content()


# ---------------------------------------------------------------- 88-96 suppliers, item-suppliers

@router.get("/suppliers", dependencies=P("view"))
def list_suppliers(q: str | None = QText(), active: bool | None = None,
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(suppliers.list_suppliers(ctx, q, active))


@router.post("/suppliers", status_code=201, dependencies=P("supplier_edit"))
def create_supplier(body: SupplierInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = suppliers.create_supplier(ctx, body)
    return respond(rec, 201, f"/suppliers/{rec.id}")


@router.get("/suppliers/{supplier_id}", dependencies=P("view"))
def get_supplier(supplier_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(suppliers.get_supplier(ctx, supplier_id))


@router.put("/suppliers/{supplier_id}", dependencies=P("supplier_edit"))
def put_supplier(supplier_id: str, body: SupplierInput, if_match: str | None = _if_match(),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(suppliers.update_supplier(ctx, supplier_id, body, if_match))


@router.delete("/suppliers/{supplier_id}", status_code=204, dependencies=P("supplier_edit"))
def delete_supplier(supplier_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    suppliers.delete_supplier(ctx, supplier_id, if_match)
    return _no_content()


@router.get("/item-suppliers", dependencies=P("view"))
def list_item_suppliers(item_id: str | None = Id(), supplier_id: str | None = Id(),
                        ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(suppliers.list_item_suppliers(ctx, item_id, supplier_id))


@router.post("/item-suppliers", status_code=201, dependencies=P("supplier_edit"))
def create_item_supplier(body: ItemSupplierInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = suppliers.create_item_supplier(ctx, body)
    return respond(rec, 201, f"/item-suppliers/{rec.id}")


@router.put("/item-suppliers/{item_supplier_id}", dependencies=P("supplier_edit"))
def put_item_supplier(item_supplier_id: str, body: ItemSupplierInput, if_match: str | None = _if_match(),
                      ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(suppliers.update_item_supplier(ctx, item_supplier_id, body, if_match))


@router.delete("/item-suppliers/{item_supplier_id}", status_code=204, dependencies=P("supplier_edit"))
def delete_item_supplier(item_supplier_id: str, if_match: str | None = _if_match(),
                         ctx: AppContext = Depends(get_ctx)) -> Response:
    suppliers.delete_item_supplier(ctx, item_supplier_id, if_match)
    return _no_content()


# ---------------------------------------------------------------- 97-105 lots, inventory

@router.get("/lots", dependencies=P("view"))
def list_lots(item_id: str | None = Id(), q: str | None = QText(), expiring_before: PlanDate | None = None,
              hold: bool | None = None, limit: int = Limit(), offset: int = Offset(),
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(inventory.list_lots(ctx, item_id=item_id, q=q, expiring_before=expiring_before, hold=hold, limit=limit,
                                   offset=offset))


@router.put("/lots/{lot_id}", dependencies=P("inventory"))
def put_lot(lot_id: str, body: LotUpdate, if_match: str | None = _if_match(),
            ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(inventory.update_lot(ctx, lot_id, body, if_match))


@router.get("/inventory/balances", dependencies=P("view"))
def list_balances(q: str | None = QText(), item_id: str | None = Id(), location_id: str | None = Id(),
                  kind: Literal["stores", "line_side", "inspection", "quarantine"] | None = None,
                  nettable: bool | None = None, lot_id: str | None = Id(), only_nonzero: bool = True,
                  sort: Literal["part_number", "location", "-qty"] = "part_number", limit: int = Limit(),
                  offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(inventory.list_balances(ctx, q=q, item_id=item_id, location_id=location_id, kind=kind,
                                       nettable=nettable, lot_id=lot_id, only_nonzero=only_nonzero, sort=sort,
                                       limit=limit, offset=offset))


@router.get("/items/{item_id}/stock", dependencies=P("view"))
def item_stock(item_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(inventory.item_stock(ctx, item_id))


@router.get("/inventory/transactions", dependencies=P("view"))
def list_transactions(item_id: str | None = Id(), location_id: str | None = Id(), lot_id: str | None = Id(),
                      txn_type: str | None = Query(default=None, max_length=16), posting_id: str | None = Id(),
                      ref_type: str | None = Query(default=None, max_length=8), ref_id: str | None = Id(),
                      d0: Annotated[PlanDate | None, Query(alias="from")] = None,
                      d1: Annotated[PlanDate | None, Query(alias="to")] = None, limit: int = Limit(),
                      offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(inventory.list_transactions(ctx, item_id=item_id, location_id=location_id, lot_id=lot_id,
                                           txn_type=txn_type, posting_id=posting_id, ref_type=ref_type,
                                           ref_id=ref_id, d0=d0, d1=d1, limit=limit, offset=offset))


@router.post("/inventory/postings", status_code=201, dependencies=P("inventory"))
def create_posting(body: PostingInput, idempotency_key: str | None = _idem_key(),
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    key = _idem(idempotency_key)
    rec, replay = inventory.create_posting(ctx, body, body.model_dump(mode="json"), key)
    if replay:
        return _ok(rec, 200, headers={"Idempotent-Replay": "true"})
    return _ok(rec, 201, headers={"Location": f"/api/v1/mfg/inventory/postings/{rec['id']}"})


@router.get("/inventory/postings", dependencies=P("view"))
def list_postings(type: str | None = Query(default=None, max_length=16),
                  d0: Annotated[PlanDate | None, Query(alias="from")] = None,
                  d1: Annotated[PlanDate | None, Query(alias="to")] = None, q: str | None = QText(),
                  limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(inventory.list_postings(ctx, type_=type, d0=d0, d1=d1, q=q, limit=limit, offset=offset))


@router.get("/inventory/postings/{posting_id}", dependencies=P("view"))
def get_posting(posting_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(inventory.get_posting(ctx, posting_id))


@router.post("/inventory/postings/{posting_id}/reverse", status_code=201, dependencies=P("inventory"))
def reverse_posting(posting_id: str, body: NoteRequest = Body(default_factory=NoteRequest),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(inventory.reverse_posting(ctx, posting_id, body.note), 201)


# ---------------------------------------------------------------- 106-125 purchasing

def _doc_list(doc_type: str) -> Any:
    def handler(status: list[str] | None = Query(default=None), supplier_id: str | None = Id(),
                item_id: str | None = Id(), overdue: bool | None = None, q: str | None = QText(),
                source: Literal["manual", "mrp", "import"] | None = None,
                sort: Literal["-created_at", "number", "next_dock_date"] = "-created_at", limit: int = Limit(),
                offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
        return _ok(purchasing.list_docs(ctx, doc_type, status=status, supplier_id=supplier_id, item_id=item_id,
                                        overdue=overdue, q=q, source=source, sort=sort, limit=limit, offset=offset))
    return handler


router.add_api_route("/purchase-requests", _doc_list("pr"), methods=["GET"], dependencies=P("view"),
                     name="list_purchase_requests")


@router.post("/purchase-requests", status_code=201, dependencies=P("pr_edit"))
def create_pr(body: PurchaseDocInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = purchasing.create_doc(ctx, "pr", body)
    return respond(rec, 201, f"/purchase-requests/{rec['id']}")


@router.get("/purchase-requests/{doc_id}", dependencies=P("view"))
def get_pr(doc_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.get_doc(ctx, "pr", doc_id))


@router.put("/purchase-requests/{doc_id}", dependencies=P("pr_edit"))
def put_pr(doc_id: str, body: PurchaseDocInput, if_match: str | None = _if_match(),
           ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.update_doc(ctx, "pr", doc_id, body, if_match))


@router.delete("/purchase-requests/{doc_id}", status_code=204, dependencies=P("pr_edit"))
def delete_pr(doc_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    purchasing.delete_doc(ctx, "pr", doc_id, if_match)
    return _no_content()


@router.post("/purchase-requests/{doc_id}/submit", dependencies=P("pr_edit"))
def submit_pr(doc_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.action(ctx, "pr", doc_id, "submit", if_match))


@router.post("/purchase-requests/{doc_id}/approve", dependencies=P("pr_approve"))
def approve_pr(doc_id: str, body: NoteRequest = Body(default_factory=NoteRequest), if_match: str | None = _if_match(),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.action(ctx, "pr", doc_id, "approve", if_match))


@router.post("/purchase-requests/{doc_id}/reject", dependencies=P("pr_approve"))
def reject_pr(doc_id: str, body: RejectRequest, if_match: str | None = _if_match(),
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.action(ctx, "pr", doc_id, "reject", if_match, reason=body.reason))


@router.post("/purchase-requests/{doc_id}/revise", dependencies=P("pr_edit"))
def revise_pr(doc_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.action(ctx, "pr", doc_id, "revise", if_match))


@router.post("/purchase-requests/{doc_id}/cancel", dependencies=P("pr_edit"))
def cancel_pr(doc_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.action(ctx, "pr", doc_id, "cancel", if_match))


@router.post("/purchase-requests/{doc_id}/convert", status_code=201, dependencies=P("po_edit"))
def convert_pr(doc_id: str, body: ConvertPrRequest = Body(default_factory=ConvertPrRequest),
               if_match: str | None = _if_match(), idempotency_key: str | None = _idem_key(),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    out, replay = purchasing.convert_pr(ctx, doc_id, body, if_match, _idem(idempotency_key))
    if replay:
        return _ok(out, 200, headers={"Idempotent-Replay": "true"})
    return _ok(out, 201)


router.add_api_route("/purchase-orders", _doc_list("po"), methods=["GET"], dependencies=P("view"),
                     name="list_purchase_orders")


@router.post("/purchase-orders", status_code=201, dependencies=P("po_edit"))
def create_po(body: PurchaseDocInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = purchasing.create_doc(ctx, "po", body)
    return respond(rec, 201, f"/purchase-orders/{rec['id']}")


@router.get("/purchase-orders/{doc_id}", dependencies=P("view"))
def get_po(doc_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.get_doc(ctx, "po", doc_id))


@router.put("/purchase-orders/{doc_id}", dependencies=P("po_edit"))
def put_po(doc_id: str, body: PurchaseDocInput, if_match: str | None = _if_match(),
           ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.update_doc(ctx, "po", doc_id, body, if_match))


@router.delete("/purchase-orders/{doc_id}", status_code=204, dependencies=P("po_edit"))
def delete_po(doc_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    purchasing.delete_doc(ctx, "po", doc_id, if_match)
    return _no_content()


@router.post("/purchase-orders/{doc_id}/issue", dependencies=P("po_edit"))
def issue_po(doc_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.action(ctx, "po", doc_id, "issue", if_match))


@router.post("/purchase-orders/{doc_id}/close", dependencies=P("po_edit"))
def close_po(doc_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.action(ctx, "po", doc_id, "close", if_match))


@router.post("/purchase-orders/{doc_id}/cancel", dependencies=P("po_edit"))
def cancel_po(doc_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(purchasing.action(ctx, "po", doc_id, "cancel", if_match))


@router.get("/purchasing/schedule", dependencies=P("view"))
def schedule_board(d0: Annotated[PlanDate | None, Query(alias="from")] = None,
                   d1: Annotated[PlanDate | None, Query(alias="to")] = None, supplier_id: str | None = Id(),
                   item_id: str | None = Id(), doc_type: Literal["pr", "po"] | None = None, overdue_only: bool = False,
                   limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(purchasing.schedule_board(ctx, d0=d0, d1=d1, supplier_id=supplier_id, item_id=item_id,
                                         doc_type=doc_type, overdue_only=overdue_only, limit=limit, offset=offset))


# ---------------------------------------------------------------- 126-133 demand

@router.get("/demand-orders", dependencies=P("view"))
def list_demand(status: Literal["draft", "open", "closed", "cancelled"] | None = None,
                demand_type: Literal["customer", "internal", "spares", "project"] | None = None,
                program: str | None = Query(default=None, max_length=32), item_id: str | None = Id(),
                due_from: PlanDate | None = None, due_to: PlanDate | None = None, late_only: bool = False,
                q: str | None = QText(), limit: int = Limit(), offset: int = Offset(),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(demand.list_orders(ctx, status=status, demand_type=demand_type, program=program, item_id=item_id,
                                  due_from=due_from, due_to=due_to, late_only=late_only, q=q, limit=limit,
                                  offset=offset))


@router.post("/demand-orders", status_code=201, dependencies=P("demand_edit"))
def create_demand(body: DemandOrderInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = demand.create_order(ctx, body)
    return respond(rec, 201, f"/demand-orders/{rec['id']}")


@router.get("/demand-orders/{order_id}", dependencies=P("view"))
def get_demand(order_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(demand.get_order(ctx, order_id))


@router.put("/demand-orders/{order_id}", dependencies=P("demand_edit"))
def put_demand(order_id: str, body: DemandOrderInput, if_match: str | None = _if_match(),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(demand.update_order(ctx, order_id, body, if_match))


@router.delete("/demand-orders/{order_id}", status_code=204, dependencies=P("demand_edit"))
def delete_demand(order_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    demand.delete_order(ctx, order_id, if_match)
    return _no_content()


@router.post("/demand-orders/{order_id}/open", dependencies=P("demand_edit"))
def open_demand(order_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(demand.action(ctx, order_id, "open", if_match))


@router.post("/demand-orders/{order_id}/close", dependencies=P("demand_edit"))
def close_demand(order_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(demand.action(ctx, order_id, "close", if_match))


@router.post("/demand-orders/{order_id}/cancel", dependencies=P("demand_edit"))
def cancel_demand(order_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(demand.action(ctx, order_id, "cancel", if_match))


# ---------------------------------------------------------------- 134-147 work orders

@router.get("/work-orders", dependencies=P("view"))
def list_wos(status: list[str] | None = Query(default=None), item_id: str | None = Id(), q: str | None = QText(),
             start_from: PlanDate | None = None, start_to: PlanDate | None = None,
             source: Literal["manual", "mrp", "import"] | None = None,
             sort: Literal["start_date", "due_date", "number", "priority"] = "start_date", limit: int = Limit(),
             offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(workorders.list_wos(ctx, status=status, item_id=item_id, q=q, start_from=start_from, start_to=start_to,
                                   source=source, sort=sort, limit=limit, offset=offset))


@router.post("/work-orders/kitting-check", dependencies=P("view"))
def kitting_check(body: KittingCheckRequest = Body(default_factory=KittingCheckRequest),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(workorders.kitting_check(ctx, body.wo_ids, body.order, body.horizon_days))


@router.post("/work-orders", status_code=201, dependencies=P("wo_edit"))
def create_wo(body: WorkOrderInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = workorders.create_wo(ctx, body)
    return respond(rec, 201, f"/work-orders/{rec['id']}")


@router.get("/work-orders/{wo_id}", dependencies=P("view"))
def get_wo(wo_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(workorders.get_wo(ctx, wo_id))


@router.put("/work-orders/{wo_id}", dependencies=P("wo_edit"))
def put_wo(wo_id: str, body: WorkOrderInput, if_match: str | None = _if_match(),
           ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(workorders.update_wo(ctx, wo_id, body, if_match))


@router.delete("/work-orders/{wo_id}", status_code=204, dependencies=P("wo_edit"))
def delete_wo(wo_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    workorders.delete_wo(ctx, wo_id, if_match)
    return _no_content()


@router.post("/work-orders/{wo_id}/release", dependencies=P("wo_edit"))
def release_wo(wo_id: str, body: ReleaseWoRequest = Body(default_factory=ReleaseWoRequest),
               if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(workorders.action(ctx, wo_id, "release", if_match, reserve=body.reserve,
                                     override_reason=body.override_reason))


def _wo_action(act: str) -> Any:
    def handler(wo_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
        return respond(workorders.action(ctx, wo_id, act, if_match))
    return handler


for _act in ("complete", "close", "cancel", "refresh-components"):
    router.add_api_route(f"/work-orders/{{wo_id}}/{_act}", _wo_action(_act), methods=["POST"],
                         dependencies=P("wo_edit"), name=f"wo_{_act.replace('-', '_')}")


@router.get("/work-orders/{wo_id}/kitting", dependencies=P("view"))
def wo_kitting(wo_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(workorders.kitting(ctx, wo_id))


@router.post("/work-orders/{wo_id}/reserve", dependencies=P("wo_edit"))
def wo_reserve(wo_id: str, body: ComponentIdsRequest = Body(default_factory=ComponentIdsRequest),
               if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(workorders.reserve(ctx, wo_id, body.component_ids, if_match))


@router.post("/work-orders/{wo_id}/unreserve", dependencies=P("wo_edit"))
def wo_unreserve(wo_id: str, body: ComponentIdsRequest = Body(default_factory=ComponentIdsRequest),
                 if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(workorders.reserve(ctx, wo_id, body.component_ids, if_match, release=True))


# ---------------------------------------------------------------- 148-163 MRP, shortages

@router.post("/mrp/runs", status_code=201, dependencies=P("mrp_run"))
def create_run(body: MrpParams = Body(default_factory=MrpParams), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(mrp.create_run(ctx, body), 201)


@router.get("/mrp/runs", dependencies=P("view"))
def list_runs(kind: Literal["live", "what_if"] | None = None, pinned: bool | None = None, limit: int = Limit(),
              offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(mrp.list_runs(ctx, kind, pinned, limit, offset))


@router.get("/mrp/runs/latest", dependencies=P("view"))
def latest_run(kind: Literal["live", "what_if"] = "live", ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(mrp.get_latest(ctx, kind))


@router.get("/mrp/runs/{run_id}", dependencies=P("view"))
def get_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(mrp.get_run(ctx, run_id))


@router.put("/mrp/runs/{run_id}", dependencies=P("mrp_run"))
def put_run(run_id: str, body: RunUpdate, if_match: str | None = _if_match(),
            ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(mrp.update_run(ctx, run_id, body.label, body.note, body.pinned, if_match))


@router.delete("/mrp/runs/{run_id}", status_code=204, dependencies=P("mrp_run"))
def delete_run(run_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    mrp.delete_run(ctx, run_id, if_match)
    return _no_content()


@router.get("/mrp/runs/{run_id}/items", dependencies=P("view"))
def run_items(run_id: str, q: str | None = QText(), make_buy: Literal["make", "buy", "phantom"] | None = None,
              family: str | None = Query(default=None, max_length=32), short_only: bool = False,
              has_exceptions: bool = False, planned_only: bool = False, llc: int | None = Query(default=None, ge=0,
                                                                                                   le=100),
              sort: Literal["llc", "part_number", "first_short_date", "-short_qty"] = "llc", limit: int = Limit(),
              offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(mrp.list_items(ctx, run_id, q=q, make_buy=make_buy, family=family, short_only=short_only,
                              has_exceptions=has_exceptions, planned_only=planned_only, llc=llc, sort=sort,
                              limit=limit, offset=offset))


@router.get("/mrp/runs/{run_id}/items/{item_id}", dependencies=P("view"))
def run_item(run_id: str, item_id: str, bucket: Literal["day", "week", "month"] = "week",
             d0: Annotated[PlanDate | None, Query(alias="from")] = None,
             d1: Annotated[PlanDate | None, Query(alias="to")] = None,
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(mrp.item_plan(ctx, run_id, item_id, bucket, d0, d1))


@router.get("/mrp/runs/{run_id}/planned-orders", dependencies=P("view"))
def run_planned(run_id: str, kind: Literal["make", "buy"] | None = None, item_id: str | None = Id(),
                supplier_id: str | None = Id(),
                release_status: Literal["start_in_past", "release_now", "later"] | None = None,
                status: Literal["open", "converted"] | None = None, q: str | None = QText(),
                sort: Literal["start_date", "need_date", "part_number", "supplier"] = "start_date",
                limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(mrp.list_planned(ctx, run_id, kind=kind, item_id=item_id, supplier_id=supplier_id,
                                release_status=release_status, status=status, q=q, sort=sort, limit=limit,
                                offset=offset))


@router.post("/mrp/runs/{run_id}/planned-orders/convert", status_code=201, dependencies=P("mrp_run"))
def run_convert(run_id: str, body: ConvertPlannedRequest, idempotency_key: str | None = _idem_key(),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    out, replay = mrp.convert(ctx, run_id, body, _idem(idempotency_key))
    if replay:
        return _ok(out, 200, headers={"Idempotent-Replay": "true"})
    return _ok(out, 201)


@router.get("/mrp/runs/{run_id}/exceptions", dependencies=P("view"))
def run_exceptions(run_id: str, code: list[str] | None = Query(default=None),
                   severity: list[Literal["critical", "warning", "info"]] | None = Query(default=None),
                   item_id: str | None = Id(), demand_line_id: str | None = Id(), q: str | None = QText(),
                   limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(mrp.list_exceptions(ctx, run_id, code=code, severity=severity, item_id=item_id,
                                   demand_line_id=demand_line_id, q=q, limit=limit, offset=offset))


@router.get("/mrp/runs/{run_id}/demand", dependencies=P("view"))
def run_demand(run_id: str, status: Literal["on_time", "late", "past_due"] | None = None,
               program: str | None = Query(default=None, max_length=32), order_id: str | None = Id(),
               late_only: bool = False, sort: Literal["-late_days", "due_date"] = "-late_days", limit: int = Limit(),
               offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(mrp.list_demand(ctx, run_id, status=status, program=program, order_id=order_id, late_only=late_only,
                               sort=sort, limit=limit, offset=offset))


@router.get("/mrp/runs/{run_id}/pegging", dependencies=P("view"))
def run_pegging(run_id: str, item_id: str = Query(max_length=64), node: int = Query(ge=0),
                kind: Literal["requirement", "supply"] = "requirement", direction: Literal["up", "down"] = "up",
                max_depth: int = Query(default=10, ge=1, le=20), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(mrp.pegging(ctx, run_id, item_id, node, kind, direction, max_depth))


@router.get("/mrp/runs/{run_id}/compare", dependencies=P("view"))
def run_compare(run_id: str, other: str = Query(alias="with", max_length=64),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(mrp.compare(ctx, run_id, other))


@router.get("/mrp/runs/{run_id}/export", dependencies=P("view"))
def run_export(run_id: str, format: Literal["xlsx", "zip"] = "xlsx", ctx: AppContext = Depends(get_ctx)) -> Response:
    return _file(*mrp.export(ctx, run_id, format))


@router.get("/shortages", dependencies=P("view"))
def shortages(horizon_days: int = Query(default=30, ge=0, le=365), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(mrp.shortages(ctx, horizon_days))


def _unused(request: Request) -> None:  # pragma: no cover
    del request
