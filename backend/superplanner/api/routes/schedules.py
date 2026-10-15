"""Schedules (A.14.6). `/schedules/compare` is registered before `/schedules/{id}`."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, Response

from ..context import AppContext, get_ctx
from ..schemas import ApproveRequest, ReplanRequest
from ..services import replan_service, schedule_service

router = APIRouter(tags=["schedules"])


@router.get("/problems/{problem_id}/schedules")
def list_schedules(problem_id: str, status: Literal["candidate", "approved", "superseded"] | None = Query(None),
                   ctx: AppContext = Depends(get_ctx)) -> dict:
    return {"items": schedule_service.list_schedules(ctx, problem_id, status)}


@router.get("/schedules/compare")
def compare(a: str = Query(...), b: str = Query(...), ctx: AppContext = Depends(get_ctx)) -> dict:
    return schedule_service.compare(ctx, a, b)


@router.get("/schedules/{schedule_id}")
def get_schedule(schedule_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    return schedule_service.get_schedule(ctx, schedule_id)


@router.post("/schedules/{schedule_id}/approve")
def approve(schedule_id: str, req: ApproveRequest = Body(default_factory=ApproveRequest),
            ctx: AppContext = Depends(get_ctx)) -> dict:
    return schedule_service.approve(ctx, schedule_id, req.note)


@router.get("/schedules/{schedule_id}/export.csv")
def export_csv(schedule_id: str, ctx: AppContext = Depends(get_ctx)) -> Response:
    text, filename = schedule_service.export_csv(ctx, schedule_id)
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/schedules/{schedule_id}/replan", status_code=202)
def replan(schedule_id: str, req: ReplanRequest, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return JSONResponse(replan_service.replan(ctx, schedule_id, req), status_code=202)
