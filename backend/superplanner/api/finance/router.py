"""Finance REST API under `/api/v1/finance` (FINANCE.md 18.2) and SSE progress (19).

Fixed paths precede parameterized ones (`/finance/plans/import` before `/finance/plans/{plan_id}`,
`/finance/results/compare` before `/finance/results/{result_id}`). SSE framing mirrors A.15 with local helpers.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from superplanner import finance
from superplanner.jobs import idempotency

from ..auth.deps import principal_user_id
from ..context import AppContext, get_ctx
from ..db.ownership import owner_scope
from ..errors import ApiError
from . import planner_link, run_service, service
from .schemas import FinanceExportFile, FinanceInstantiateRequest, SendToPlannerRequest, WhatIfRequest

router = APIRouter(prefix="/finance", tags=["finance"])
PLAN_URL = "/api/v1/finance/plans"


def _record_response(rec: dict, status: int = 200, location: bool = False) -> JSONResponse:
    headers = {"ETag": f'"{rec["version"]}"'}
    if location:
        headers["Location"] = f"{PLAN_URL}/{rec['id']}"
    return JSONResponse(rec, status_code=status, headers=headers)


# ---------------------------------------------------------------- defaults, templates, preview

@router.get("/defaults")
def get_defaults() -> dict:
    return service.defaults()


@router.get("/templates")
def list_templates() -> dict:
    return {"items": service.list_templates()}


@router.post("/templates/{template_id}/instantiate", status_code=201)
def instantiate(template_id: str, req: FinanceInstantiateRequest = Body(default_factory=FinanceInstantiateRequest),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _record_response(service.instantiate_template(ctx, template_id, req), 201, location=True)


@router.post("/preview")
def preview(plan: finance.FinancePlan) -> dict:
    return service.preview(plan)


# ---------------------------------------------------------------- plans

@router.get("/plans")
def list_plans(ctx: AppContext = Depends(get_ctx)) -> dict:
    return {"items": service.list_plans(ctx)}


@router.post("/plans", status_code=201)
def create_plan(plan: finance.FinancePlan, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _record_response(service.create_plan(ctx, plan), 201, location=True)


@router.post("/plans/import", status_code=201)
def import_plan(payload: FinanceExportFile, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _record_response(service.import_plan(ctx, payload), 201, location=True)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _record_response(service.get_plan(ctx, plan_id))


@router.put("/plans/{plan_id}")
def put_plan(plan_id: str, plan: finance.FinancePlan, if_match: str | None = Header(default=None),
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _record_response(service.update_plan(ctx, plan_id, plan, if_match))


@router.delete("/plans/{plan_id}", status_code=204)
def delete_plan(plan_id: str, ctx: AppContext = Depends(get_ctx)) -> Response:
    service.delete_plan(ctx, plan_id)
    return Response(status_code=204)


@router.get("/plans/{plan_id}/export")
def export_plan(plan_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    body, filename = service.export_plan(ctx, plan_id)
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/plans/{plan_id}/validate")
def validate_plan(plan_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    return service.validate_plan(ctx, plan_id)


# ---------------------------------------------------------------- runs

@router.post("/plans/{plan_id}/runs", status_code=202)
def create_run(plan_id: str, req: finance.FinanceRunRequest = Body(default_factory=finance.FinanceRunRequest),
               idempotency_key: str | None = Header(default=None),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    idem = idempotency.from_header(idempotency_key, "finance_run", {"plan_id": plan_id}, req.model_dump(mode="json"))
    return idempotency.accepted(lambda: run_service.create_run(ctx, plan_id, req, idem))


@router.post("/plans/{plan_id}/what-if", status_code=202)
def create_what_if(plan_id: str, body: WhatIfRequest, idempotency_key: str | None = Header(default=None),
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    idem = idempotency.from_header(idempotency_key, "what_if", {"plan_id": plan_id}, body.model_dump(mode="json"))
    return idempotency.accepted(lambda: run_service.create_what_if(ctx, plan_id, body, idem))


@router.get("/plans/{plan_id}/runs")
def list_runs(plan_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    return {"items": run_service.list_runs(ctx, plan_id)}


@router.get("/runs/{run_id}")
def get_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    return run_service.get_run(ctx, run_id)


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return JSONResponse(run_service.cancel_run(ctx, run_id), status_code=202)


def _poll_events(ctx: AppContext, run_id: str, cursor: int, owner: str | None) -> tuple[list[dict], str]:
    """One SSE poll in the stream owner's scope (the generator may outlive the dependency's context)."""
    if owner is None:
        return run_service.list_events(ctx, run_id, cursor)
    with owner_scope(owner):
        return run_service.list_events(ctx, run_id, cursor)


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


def _sse_frame(event: dict) -> str:
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, stream: bool = Query(default=True),
                     after: int | None = Query(default=None, ge=0),
                     last_event_id: str | None = Header(default=None),
                     ctx: AppContext = Depends(get_ctx)) -> Response:
    cursor = _cursor(last_event_id, after)
    owner = principal_user_id(request)   # every poll runs in owner_scope (PHASE2B 4.7)
    events, status = await run_in_threadpool(_poll_events, ctx, run_id, cursor, owner)  # 404 if unknown
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
                yield _sse_frame(ev)
                last_sent = time.monotonic()
                if ev["type"] in run_service.TERMINAL_EVENT_TYPES:
                    return
            if status in run_service.TERMINAL_STATUSES and not events:
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(poll)
            if time.monotonic() - last_sent >= keepalive:
                yield ": keepalive\n\n"
                last_sent = time.monotonic()
            try:
                events, status = await run_in_threadpool(_poll_events, ctx, run_id, cursor, owner)
            except ApiError:
                return  # run deleted with its plan while streaming

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- results

@router.get("/plans/{plan_id}/results")
def list_results(plan_id: str, kind: Literal["baseline", "what_if"] | None = Query(default=None),
                 ctx: AppContext = Depends(get_ctx)) -> dict:
    return {"items": run_service.list_results(ctx, plan_id, kind)}


@router.get("/results/compare")
def compare_results(a: str = Query(min_length=1), b: str = Query(min_length=1),
                    ctx: AppContext = Depends(get_ctx)) -> dict:
    return run_service.compare(ctx, a, b)


@router.get("/results/{result_id}")
def get_result(result_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    return run_service.get_result(ctx, result_id)


@router.get("/results/{result_id}/contributions.csv")
def contributions_csv(result_id: str, ctx: AppContext = Depends(get_ctx)) -> Response:
    text, filename = run_service.contributions_csv(ctx, result_id)
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/results/{result_id}/send-to-planner", status_code=201)
def send_to_planner(result_id: str, req: SendToPlannerRequest = Body(default_factory=SendToPlannerRequest),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    out = planner_link.send_to_planner(ctx, result_id, req)
    return JSONResponse(out, status_code=201, headers={"Location": f"/api/v1/problems/{out['problem_id']}"})
