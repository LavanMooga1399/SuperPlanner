"""GET /health (A.14.1)."""

from __future__ import annotations

import ortools
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from superplanner import engine

from ..context import AppContext, get_ctx

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    ok = await run_in_threadpool(ctx.db.ping)
    body = {"status": "ok" if ok else "degraded", "version": engine.__version__,
            "ortools_version": ortools.__version__, "database": "ok" if ok else "error"}
    return JSONResponse(body, status_code=200 if ok else 503)
