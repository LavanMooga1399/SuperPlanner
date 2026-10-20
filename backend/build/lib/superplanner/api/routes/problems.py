"""Problems CRUD, export/import and validate (A.14.3, A.14.4). `/problems/import` precedes `/problems/{id}`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import JSONResponse

from superplanner.engine import Problem

from ..context import AppContext, get_ctx
from ..schemas import ExportFile
from ..services import problem_service

router = APIRouter(tags=["problems"])


def _record_response(rec: dict, status: int = 200, location: bool = False) -> JSONResponse:
    headers = {"ETag": f'"{rec["version"]}"'}
    if location:
        headers["Location"] = f"/api/v1/problems/{rec['id']}"
    return JSONResponse(rec, status_code=status, headers=headers)


@router.get("/problems")
def list_problems(ctx: AppContext = Depends(get_ctx)) -> dict:
    return {"items": problem_service.list_problems(ctx)}


@router.post("/problems", status_code=201)
def create_problem(problem: Problem, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _record_response(problem_service.create_problem(ctx, problem), 201, location=True)


@router.post("/problems/import", status_code=201)
def import_problem(payload: ExportFile, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _record_response(problem_service.import_problem(ctx, payload), 201, location=True)


@router.get("/problems/{problem_id}")
def get_problem(problem_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _record_response(problem_service.get_problem(ctx, problem_id))


@router.put("/problems/{problem_id}")
def put_problem(problem_id: str, problem: Problem, if_match: str | None = Header(default=None),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _record_response(problem_service.update_problem(ctx, problem_id, problem, if_match))


@router.delete("/problems/{problem_id}", status_code=204)
def delete_problem(problem_id: str, ctx: AppContext = Depends(get_ctx)) -> Response:
    problem_service.delete_problem(ctx, problem_id)
    return Response(status_code=204)


@router.get("/problems/{problem_id}/export")
def export_problem(problem_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    body, filename = problem_service.export_problem(ctx, problem_id)
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/problems/{problem_id}/validate")
def validate_problem(problem_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    return problem_service.validate_problem(ctx, problem_id)
