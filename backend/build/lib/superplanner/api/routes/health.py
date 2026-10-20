"""Health endpoints (A.14.1, PHASE2B 5.2).

- `GET /health`: unchanged body and 503 rule (the frontend and `test_api_health` rely on it).
- `GET /health/live`: 200 `{"status":"ok"}`, no database access (process liveness).
- `GET /health/ready`: 200 `{"status":"ready", ...}` or 503 `{"status":"not_ready", ...}` when the database ping
  fails (`"database":"error"`) or the schema is not at head (`"schema":"outdated"`). Missing workers do not make
  the API unready (shown in `workers_alive`). Schema state is cached 30 s per app. Public in every auth mode and
  runs in `system_scope()` (it counts rows of the owned `jobs` table inside a request without a user, review R9).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import ortools
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from superplanner import engine

from ..context import AppContext, get_ctx

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)

SCHEMA_CACHE_SECONDS = 30.0


@router.get("/health")
async def health(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    ok = await run_in_threadpool(ctx.db.ping)
    body = {"status": "ok" if ok else "degraded", "version": engine.__version__,
            "ortools_version": ortools.__version__, "database": "ok" if ok else "error"}
    return JSONResponse(body, status_code=200 if ok else 503)


@router.get("/health/live")
async def health_live() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/health/ready")
async def health_ready(request: Request) -> JSONResponse:
    body = await run_in_threadpool(readiness, request.app.state.ctx, request.app.state)
    return JSONResponse(body, status_code=200 if body["status"] == "ready" else 503)


def _schema(ctx: AppContext, state: Any) -> tuple[str, str | None]:
    """("ok"|"outdated", revision), cached SCHEMA_CACHE_SECONDS on the app state."""
    from superplanner import migrate

    cached = getattr(state, "sp_ready_schema", None)
    now = time.monotonic()
    if cached is not None and now - cached[0] < SCHEMA_CACHE_SECONDS:
        return cached[1], cached[2]
    st = migrate.schema_state(ctx.db)
    rev = migrate.current_revision(ctx.db)
    result = "ok" if st == "current" else "outdated"
    state.sp_ready_schema = (now, result, rev)
    return result, rev


def readiness(ctx: AppContext, state: Any) -> dict[str, Any]:
    """Blocking readiness check (threadpool)."""
    from superplanner import migrate

    from ...obs import http_metrics
    from ..db.ownership import system_scope

    body: dict[str, Any] = {"status": "ready", "database": "ok", "schema": "ok", "schema_revision": None,
                            "job_backend": ctx.settings.job_backend, "workers_alive": 0,
                            "queue": {"queued": 0, "running": 0}}
    started = True
    with system_scope():
        try:
            ctx.start()
        except migrate.SchemaError:
            started = False
            body["schema"] = "outdated"
        except Exception as exc:
            started = False
            log.warning("readiness: app start failed (%s)", exc.__class__.__name__)
        if not ctx.db.ping():
            body.update(status="not_ready", database="error", schema="unknown")
            return body
        try:
            schema, rev = _schema(ctx, state)
        except Exception as exc:
            log.warning("readiness: schema check failed (%s)", exc.__class__.__name__)
            body.update(status="not_ready", database="error", schema="unknown")
            return body
        body["schema_revision"] = rev
        if schema != "ok":
            body["schema"] = "outdated"
        if body["schema"] != "ok":
            body["status"] = "not_ready"
            return body
        if not started:
            body.update(status="not_ready", database="error")
            return body
        try:
            snap = http_metrics.cached_queue_snapshot(ctx)
        except Exception as exc:
            log.warning("readiness: queue counts failed (%s)", exc.__class__.__name__)
            body.update(status="not_ready", database="error")
            return body
    body["workers_alive"] = snap["workers_alive"]
    body["queue"] = {st: sum(n for (_, s), n in snap["depth"].items() if s == st) for st in ("queued", "running")}
    return body
