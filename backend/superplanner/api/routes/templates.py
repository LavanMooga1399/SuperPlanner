"""Templates (A.14.2)."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from ..context import AppContext, get_ctx
from ..schemas import InstantiateRequest
from ..services import problem_service

router = APIRouter(tags=["templates"])


@router.get("/templates")
def list_templates() -> dict:
    return {"items": problem_service.list_templates()}


@router.post("/templates/{template_id}/instantiate", status_code=201)
def instantiate(template_id: str, req: InstantiateRequest = Body(default_factory=InstantiateRequest),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = problem_service.instantiate_template(ctx, template_id, req)
    return JSONResponse(rec, status_code=201, headers={"ETag": f'"{rec["version"]}"',
                                                       "Location": f"/api/v1/problems/{rec['id']}"})
