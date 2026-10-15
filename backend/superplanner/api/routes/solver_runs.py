"""Solver runs and SSE progress (A.14.5, A.15)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from ..context import AppContext, get_ctx
from ..errors import ApiError
from ..schemas import SolverRunRequest
from ..services import run_service

router = APIRouter(tags=["solver-runs"])


@router.post("/problems/{problem_id}/solver-runs", status_code=202)
def create_run(problem_id: str, req: SolverRunRequest = Body(default_factory=SolverRunRequest),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return JSONResponse(run_service.create_run(ctx, problem_id, req), status_code=202)


@router.get("/problems/{problem_id}/solver-runs")
def list_runs(problem_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    return {"items": run_service.list_runs(ctx, problem_id)}


@router.get("/solver-runs/{run_id}")
def get_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    return run_service.get_run(ctx, run_id)


@router.post("/solver-runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return JSONResponse(run_service.cancel_run(ctx, run_id), status_code=202)


def _cursor(last_event_id: str | None, after: int | None) -> int:
    raw = last_event_id if last_event_id not in (None, "") else after
    if raw in (None, ""):
        return 0
    try:
        return max(0, int(str(raw).strip()))
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", "Last-Event-ID must be an integer event sequence number.",
                       {"errors": [{"loc": ["header", "last-event-id"], "msg": "not an integer",
                                    "type": "int_parsing"}]})


def _frame(event: dict) -> str:
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


@router.get("/solver-runs/{run_id}/events")
async def run_events(run_id: str, request: Request, stream: bool = Query(default=True),
                     after: int | None = Query(default=None, ge=0),
                     last_event_id: str | None = Header(default=None),
                     ctx: AppContext = Depends(get_ctx)) -> Response:
    cursor = _cursor(last_event_id, after)
    events, status = await run_in_threadpool(run_service.list_events, ctx, run_id, cursor)  # 404 if unknown
    if not stream:
        return JSONResponse({"items": events})
    if status in run_service.TERMINAL_STATUSES and not events:
        return Response(status_code=204)
    poll = ctx.settings.sse_poll_seconds
    keepalive = ctx.settings.sse_keepalive_seconds

    async def gen() -> AsyncIterator[str]:
        nonlocal cursor, events, status
        last_sent = time.monotonic()
        while True:
            for ev in events:
                cursor = ev["seq"]
                yield _frame(ev)
                last_sent = time.monotonic()
                if ev["type"] in run_service.TERMINAL_EVENT_TYPES:
                    return
            if status in run_service.TERMINAL_STATUSES and not events:
                return  # terminal run without a terminal event (should not happen): end the stream anyway
            if await request.is_disconnected():
                return
            await asyncio.sleep(poll)
            if time.monotonic() - last_sent >= keepalive:
                yield ": keepalive\n\n"
                last_sent = time.monotonic()
            events, status = await run_in_threadpool(run_service.list_events, ctx, run_id, cursor)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
