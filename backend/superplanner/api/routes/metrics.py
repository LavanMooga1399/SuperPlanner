"""`GET /metrics` (PHASE2B 5.4): Prometheus text format from the default registry.

Mounted at the root (outside `/api/v1`), not in the OpenAPI schema, not proxied by the frontend nginx. With
`METRICS_TOKEN` set, `Authorization: Bearer <token>` is required (401 otherwise). Not registered at all when
`METRICS_ENABLED=false` (404). Before rendering, the queue gauges are refreshed from this app's database
(cached 5 s, system scope).
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from ...obs import http_metrics
from ...obs import job_metrics as _job_metrics  # noqa: F401  (registers the job metrics in this process)
from ..errors import envelope

router = APIRouter(tags=["metrics"])


def _authorized(request: Request, token: str | None) -> bool:
    if not token:
        return True
    header = request.headers.get("authorization") or ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return False
    return hmac.compare_digest(value.strip().encode(), token.encode())


def _collect(ctx: object) -> bytes:
    from ..db.ownership import system_scope

    with system_scope():
        try:
            ctx.start()   # type: ignore[attr-defined]
        except Exception:
            pass   # the collector below reports nothing new; HTTP metrics still render
        else:
            http_metrics.refresh_queue_gauges(ctx)
    return generate_latest(REGISTRY)


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    settings = request.app.state.settings
    if not _authorized(request, settings.metrics_token):
        return JSONResponse(envelope("AUTH_REQUIRED", "A valid metrics token is required."), status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
    data = await run_in_threadpool(_collect, request.app.state.ctx)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
