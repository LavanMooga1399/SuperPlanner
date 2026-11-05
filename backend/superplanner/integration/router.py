"""`/api/v1/integration` (M5-DESIGN 4, 9): console (`integration_admin`) and machine endpoints (API token scopes
`integration.read` / `integration.write`). Workspace = the M2 `X-SP-Workspace` header (tokens: their own)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Query
from fastapi.responses import JSONResponse, Response

from ..api.context import AppContext, get_ctx
from ..api.mfg.access import require_integration
from ..api.mfg.router_m2 import Id, Limit, Offset, _if_match, _ok
from ..api.mfg.services import integration as svc
from .model import EndpointIn, MappingProfileIn, ReconciliationIn, SettingsIn, ValueMapsIn

router = APIRouter(prefix="/integration", tags=["integration"])
ADMIN = [require_integration("integration_admin")]
READ = [require_integration("integration.read")]
WRITE = [require_integration("integration.write")]


@router.get("/settings", dependencies=ADMIN)
def get_settings(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.get_settings(ctx))


@router.put("/settings", dependencies=ADMIN)
def put_settings(body: SettingsIn, if_match: str | None = _if_match(),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = svc.put_settings(ctx, body, if_match)
    return _ok(rec, etag=rec["row_version"])


@router.get("/endpoints", dependencies=ADMIN)
def list_endpoints(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.list_endpoints(ctx))


@router.post("/endpoints", status_code=201, dependencies=ADMIN)
def create_endpoint(body: EndpointIn, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.create_endpoint(ctx, body), 201)


@router.put("/endpoints/{endpoint_id}", dependencies=ADMIN)
def update_endpoint(endpoint_id: str, body: EndpointIn, if_match: str | None = _if_match(),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.update_endpoint(ctx, endpoint_id, body, if_match))


@router.delete("/endpoints/{endpoint_id}", status_code=204, dependencies=ADMIN)
def delete_endpoint(endpoint_id: str, if_match: str | None = _if_match(),
                    ctx: AppContext = Depends(get_ctx)) -> Response:
    svc.delete_endpoint(ctx, endpoint_id, if_match)
    return Response(status_code=204)


@router.post("/endpoints/{endpoint_id}/test", dependencies=ADMIN)
def test_endpoint(endpoint_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.deliver_now(ctx, endpoint_id))


@router.get("/value-maps", dependencies=ADMIN)
def get_value_maps(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.get_value_maps(ctx))


@router.put("/value-maps", dependencies=ADMIN)
def put_value_maps(body: ValueMapsIn, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.put_value_maps(ctx, body))


@router.post("/batches", dependencies=WRITE)
def post_batch(body: dict[str, Any] = Body(...), idem: str | None = Header(default=None, alias="Idempotency-Key",
                                                                           max_length=128),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec, replayed, status = svc.post_batch(ctx, body, idem)
    return _ok(rec, status, headers={"Idempotent-Replay": "true"} if replayed else None)


@router.get("/batches", dependencies=READ)
def list_batches(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.list_batches(ctx, limit, offset))


@router.get("/batches/{batch_id}", dependencies=READ)
def get_batch(batch_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.get_batch(ctx, batch_id))


@router.get("/events", dependencies=READ)
def pull_events(after: int = Query(default=0, ge=0), limit: int = Query(default=1000, ge=1, le=1000),
                types: str | None = Query(default=None, max_length=1000),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.pull_events(ctx, after, limit, [t for t in (types or "").split(",") if t] or None))


@router.get("/deliveries", dependencies=ADMIN)
def list_deliveries(status: str | None = Query(default=None, pattern="^(pending|delivered|dead)$"),
                    endpoint_id: str | None = Id(), limit: int = Limit(), offset: int = Offset(),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.list_deliveries(ctx, status, endpoint_id, limit, offset))


@router.post("/deliveries/{delivery_id}/retry", dependencies=ADMIN)
def retry_delivery(delivery_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.retry_delivery(ctx, delivery_id))


@router.get("/mapping-profiles", dependencies=ADMIN)
def list_profiles(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.list_profiles(ctx))


@router.post("/mapping-profiles", status_code=201, dependencies=ADMIN)
def create_profile(body: MappingProfileIn, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.create_profile(ctx, body), 201)


@router.get("/filedrop/status", dependencies=ADMIN)
def filedrop_status(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.filedrop_status(ctx))


@router.post("/reconciliations", status_code=201, dependencies=ADMIN)
def create_reconciliation(body: ReconciliationIn, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.reconcile(ctx, body), 201)


@router.get("/reconciliations", dependencies=ADMIN)
def list_reconciliations(limit: int = Limit(), offset: int = Offset(),
                         ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.list_reconciliations(ctx, limit, offset))


@router.get("/reconciliations/{rec_id}", dependencies=ADMIN)
def get_reconciliation(rec_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(svc.get_reconciliation(ctx, rec_id))
