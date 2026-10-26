"""`/api/v1/mfg` (M1-DESIGN 9.3): 77 operations. Included in `create_app` with `Depends(require_user)` and
registered with `body_gate`. Fixed paths precede parameterised siblings (`/shift-templates/preview`). Path ids are
plain `str` (malformed / unknown / foreign -> 404). Sync handlers run in the threadpool; the raw upload reads the
body after `require_user` and parses it in the threadpool.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ...mfg import limits as L
from ...mfg.model import (BomInput, CalendarExceptionInput, GroupInput, ItemInput, LineInput, OperatorInput, PlanDate,
                          PlantInput, RoutingInput, ShiftAssignmentInput, ShiftTemplateInput, SkillInput,
                          ToolPoolInput)
from ..context import AppContext, get_ctx
from ..errors import ApiError
from .schemas import (BomCopyRequest, EmptyRequest, ImportMappingRequest, ReleaseRequest, ResetRequest,
                      RoutingCopyRequest, SampleLoadRequest)
from .services import boms, health, imports, items, plant, resources, routings, samples
from .services.common import jsonable, respond

router = APIRouter(prefix="/mfg", tags=["mfg"])
IfMatch = Header(default=None, alias="If-Match")


def _ok(body: object, status: int = 200, etag: int | None = None) -> JSONResponse:
    headers = {"ETag": f'"{etag}"'} if etag is not None else None
    return JSONResponse(jsonable(body), status_code=status, headers=headers)


def _no_content() -> Response:
    return Response(status_code=204)


# ---------------------------------------------------------------- 1-4 meta, summary, plant

@router.get("/meta")
def get_meta(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(health.meta(ctx))


@router.get("/summary")
def get_summary(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(health.summary(ctx))


@router.get("/plant")
def get_plant(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(plant.get_plant(ctx))


@router.put("/plant")
def put_plant(body: PlantInput, if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(plant.put_plant(ctx, body, if_match))


# ---------------------------------------------------------------- 5-13 items

@router.get("/items")
def list_items(q: str | None = Query(default=None, max_length=200),
               make_buy: Literal["make", "buy", "phantom"] | None = None, family: str | None = Query(None, max_length=32),
               active: bool | None = None, has_bom: bool | None = None, has_routing: bool | None = None,
               sort: Literal["part_number", "-updated_at", "description"] = "part_number",
               limit: int = Query(default=L.PAGE_DEFAULT, ge=1, le=L.PAGE_MAX), offset: int = Query(default=0, ge=0),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(items.list_items(ctx, q=q, make_buy=make_buy, family=family, active=active, has_bom=has_bom,
                                has_routing=has_routing, sort=sort, limit=limit, offset=offset))


@router.post("/items", status_code=201)
def create_item(body: ItemInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = items.create_item(ctx, body)
    return respond(rec, 201, f"/items/{rec.id}")


@router.get("/items/{item_id}")
def get_item(item_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(items.get_item(ctx, item_id))


@router.put("/items/{item_id}")
def put_item(item_id: str, body: ItemInput, if_match: str | None = IfMatch,
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(items.update_item(ctx, item_id, body, if_match))


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: str, if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> Response:
    items.delete_item(ctx, item_id, if_match)
    return _no_content()


@router.get("/items/{item_id}/explosion")
def get_explosion(item_id: str, on: PlanDate | None = None, serial: int | None = Query(default=None, ge=1, le=10**9),
                  qty: float = Query(default=1.0, gt=0, le=1_000_000_000),
                  mode: Literal["indented", "summarized"] = "indented", include_scrap: bool = True,
                  include_yield: bool = True, max_depth: int | None = Query(default=None, ge=0, le=L.MAX_BOM_DEPTH),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(boms.explosion(ctx, item_id, on=on, serial=serial, qty=qty, mode=mode, include_scrap=include_scrap,
                              include_yield=include_yield, max_depth=max_depth))


@router.get("/items/{item_id}/where-used")
def get_where_used(item_id: str, on: PlanDate | None = None, include: Literal["effective", "all"] = "effective",
                   mode: Literal["single", "indented"] = "single", ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(boms.where_used_view(ctx, item_id, on=on, include=include, mode=mode))


@router.get("/items/{item_id}/boms")
def get_item_boms(item_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(boms.list_item_boms(ctx, item_id))


@router.get("/items/{item_id}/routings")
def get_item_routings(item_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(routings.list_item_routings(ctx, item_id))


# ---------------------------------------------------------------- 14-20 BOMs

@router.post("/boms", status_code=201)
def create_bom(body: BomInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = boms.create_bom(ctx, body)
    return respond(rec, 201, f"/boms/{rec.id}")


@router.get("/boms/{bom_id}")
def get_bom(bom_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(boms.get_bom(ctx, bom_id))


@router.put("/boms/{bom_id}")
def put_bom(bom_id: str, body: BomInput, if_match: str | None = IfMatch,
            ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(boms.update_bom(ctx, bom_id, body, if_match))


@router.delete("/boms/{bom_id}", status_code=204)
def delete_bom(bom_id: str, if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> Response:
    boms.delete_bom(ctx, bom_id, if_match)
    return _no_content()


@router.post("/boms/{bom_id}/release")
def release_bom(bom_id: str, body: ReleaseRequest = Body(default_factory=ReleaseRequest),
                if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    out = boms.release_bom(ctx, bom_id, body.effective_from, body.supersede_previous, if_match)
    return _ok(out, etag=out["bom"].row_version)


@router.post("/boms/{bom_id}/obsolete")
def obsolete_bom(bom_id: str, body: EmptyRequest = Body(default_factory=EmptyRequest),
                 if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(boms.obsolete_bom(ctx, bom_id, if_match))


@router.post("/boms/{bom_id}/copy", status_code=201)
def copy_bom(bom_id: str, body: BomCopyRequest = Body(default_factory=BomCopyRequest),
             if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = boms.copy_bom(ctx, bom_id, body.revision, if_match)
    return respond(rec, 201, f"/boms/{rec.id}")


# ---------------------------------------------------------------- 21-28 routings

@router.post("/routings", status_code=201)
def create_routing(body: RoutingInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = routings.create_routing(ctx, body)
    return respond(rec, 201, f"/routings/{rec.id}")


@router.get("/routings/{routing_id}")
def get_routing(routing_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(routings.get_routing(ctx, routing_id))


@router.put("/routings/{routing_id}")
def put_routing(routing_id: str, body: RoutingInput, if_match: str | None = IfMatch,
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(routings.update_routing(ctx, routing_id, body, if_match))


@router.delete("/routings/{routing_id}", status_code=204)
def delete_routing(routing_id: str, if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> Response:
    routings.delete_routing(ctx, routing_id, if_match)
    return _no_content()


@router.post("/routings/{routing_id}/release")
def release_routing(routing_id: str, body: ReleaseRequest = Body(default_factory=ReleaseRequest),
                    if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    out = routings.release_routing(ctx, routing_id, body.effective_from, body.supersede_previous, if_match)
    return _ok(out, etag=out["routing"].row_version)


@router.post("/routings/{routing_id}/obsolete")
def obsolete_routing(routing_id: str, body: EmptyRequest = Body(default_factory=EmptyRequest),
                     if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(routings.obsolete_routing(ctx, routing_id, if_match))


@router.post("/routings/{routing_id}/copy", status_code=201)
def copy_routing(routing_id: str, body: RoutingCopyRequest = Body(default_factory=RoutingCopyRequest),
                 if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = routings.copy_routing(ctx, routing_id, body.revision, body.code, if_match)
    return respond(rec, 201, f"/routings/{rec.id}")


@router.get("/routings/{routing_id}/time-preview")
def time_preview(routing_id: str, qty: float = Query(default=1.0, gt=0, le=1_000_000_000),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(routings.time_preview(ctx, routing_id, qty))


# ---------------------------------------------------------------- 29-39 groups and lines

@router.get("/groups")
def list_groups(q: str | None = Query(None, max_length=200), active: bool | None = None,
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(plant.list_groups(ctx, q, active))


@router.post("/groups", status_code=201)
def create_group(body: GroupInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = plant.create_group(ctx, body)
    return respond(rec, 201, f"/groups/{rec.id}")


@router.get("/groups/{group_id}")
def get_group(group_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(plant.get_group(ctx, group_id))


@router.put("/groups/{group_id}")
def put_group(group_id: str, body: GroupInput, if_match: str | None = IfMatch,
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(plant.update_group(ctx, group_id, body, if_match))


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: str, if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> Response:
    plant.delete_group(ctx, group_id, if_match)
    return _no_content()


@router.get("/lines")
def list_lines(group_id: str | None = Query(None, max_length=64), q: str | None = Query(None, max_length=200),
               active: bool | None = None, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(plant.list_lines(ctx, group_id, q, active))


@router.post("/lines", status_code=201)
def create_line(body: LineInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = plant.create_line(ctx, body)
    return respond(rec, 201, f"/lines/{rec.id}")


@router.get("/lines/{line_id}")
def get_line(line_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(plant.get_line(ctx, line_id))


@router.put("/lines/{line_id}")
def put_line(line_id: str, body: LineInput, if_match: str | None = IfMatch,
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(plant.update_line(ctx, line_id, body, if_match))


@router.delete("/lines/{line_id}", status_code=204)
def delete_line(line_id: str, if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> Response:
    plant.delete_line(ctx, line_id, if_match)
    return _no_content()


@router.get("/lines/{line_id}/windows")
def line_windows(line_id: str, d0: Annotated[PlanDate, Query(alias="from")], d1: Annotated[PlanDate, Query(alias="to")],
                 kinds: str = Query(default="base,optional", max_length=40),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    ks = [k.strip() for k in kinds.split(",") if k.strip()]
    if not ks or any(k not in ("base", "optional") for k in ks):
        raise ApiError(422, "VALIDATION_ERROR", "kinds must be 'base', 'optional' or 'base,optional'.",
                       {"errors": [{"loc": ["query", "kinds"], "msg": "unknown kind", "type": "enum"}]})
    return _ok(plant.windows(ctx, line_id, d0, d1, ks))


# ---------------------------------------------------------------- 40-53 shifts and calendar

@router.get("/shift-templates")
def list_templates(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(plant.list_templates(ctx))


@router.post("/shift-templates", status_code=201)
def create_template(body: ShiftTemplateInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = plant.create_template(ctx, body)
    return respond(rec, 201, f"/shift-templates/{rec.id}")


@router.post("/shift-templates/preview")
def preview_template(body: ShiftTemplateInput) -> JSONResponse:
    return _ok(plant.preview_template(body))


@router.get("/shift-templates/{shift_template_id}")
def get_template(shift_template_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(plant.get_template(ctx, shift_template_id))


@router.put("/shift-templates/{shift_template_id}")
def put_template(shift_template_id: str, body: ShiftTemplateInput, if_match: str | None = IfMatch,
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(plant.update_template(ctx, shift_template_id, body, if_match))


@router.delete("/shift-templates/{shift_template_id}", status_code=204)
def delete_template(shift_template_id: str, if_match: str | None = IfMatch,
                    ctx: AppContext = Depends(get_ctx)) -> Response:
    plant.delete_template(ctx, shift_template_id, if_match)
    return _no_content()


@router.get("/shift-assignments")
def list_assignments(group_id: str | None = Query(None, max_length=64), line_id: str | None = Query(None, max_length=64),
                     shift_template_id: str | None = Query(None, max_length=64),
                     ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(plant.list_assignments(ctx, group_id, line_id, shift_template_id))


@router.post("/shift-assignments", status_code=201)
def create_assignment(body: ShiftAssignmentInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = plant.create_assignment(ctx, body)
    return respond(rec, 201, f"/shift-assignments/{rec.id}")


@router.put("/shift-assignments/{assignment_id}")
def put_assignment(assignment_id: str, body: ShiftAssignmentInput, if_match: str | None = IfMatch,
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(plant.update_assignment(ctx, assignment_id, body, if_match))


@router.delete("/shift-assignments/{assignment_id}", status_code=204)
def delete_assignment(assignment_id: str, if_match: str | None = IfMatch,
                      ctx: AppContext = Depends(get_ctx)) -> Response:
    plant.delete_assignment(ctx, assignment_id, if_match)
    return _no_content()


@router.get("/calendar-exceptions")
def list_exceptions(d0: Annotated[PlanDate | None, Query(alias="from")] = None,
                    d1: Annotated[PlanDate | None, Query(alias="to")] = None,
                    scope: Literal["plant", "group", "line"] | None = None,
                    group_id: str | None = Query(None, max_length=64), line_id: str | None = Query(None, max_length=64),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(plant.list_exceptions(ctx, d0, d1, scope, group_id, line_id))


@router.post("/calendar-exceptions", status_code=201)
def create_exception(body: CalendarExceptionInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = plant.create_exception(ctx, body)
    return respond(rec, 201, f"/calendar-exceptions/{rec.id}")


@router.put("/calendar-exceptions/{exception_id}")
def put_exception(exception_id: str, body: CalendarExceptionInput, if_match: str | None = IfMatch,
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(plant.update_exception(ctx, exception_id, body, if_match))


@router.delete("/calendar-exceptions/{exception_id}", status_code=204)
def delete_exception(exception_id: str, if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> Response:
    plant.delete_exception(ctx, exception_id, if_match)
    return _no_content()


# ---------------------------------------------------------------- 54-66 skills, operators, tool pools

@router.get("/skills")
def list_skills(q: str | None = Query(None, max_length=200), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(resources.list_skills(ctx, q))


@router.post("/skills", status_code=201)
def create_skill(body: SkillInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = resources.create_skill(ctx, body)
    return respond(rec, 201, f"/skills/{rec.id}")


@router.put("/skills/{skill_id}")
def put_skill(skill_id: str, body: SkillInput, if_match: str | None = IfMatch,
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(resources.update_skill(ctx, skill_id, body, if_match))


@router.delete("/skills/{skill_id}", status_code=204)
def delete_skill(skill_id: str, if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> Response:
    resources.delete_skill(ctx, skill_id, if_match)
    return _no_content()


@router.get("/operators")
def list_operators(q: str | None = Query(None, max_length=200), active: bool | None = None,
                   skill_id: str | None = Query(None, max_length=64), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(resources.list_operators(ctx, q, active, skill_id))


@router.post("/operators", status_code=201)
def create_operator(body: OperatorInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = resources.create_operator(ctx, body)
    return respond(rec, 201, f"/operators/{rec.id}")


@router.get("/operators/{operator_id}")
def get_operator(operator_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(resources.get_operator(ctx, operator_id))


@router.put("/operators/{operator_id}")
def put_operator(operator_id: str, body: OperatorInput, if_match: str | None = IfMatch,
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(resources.update_operator(ctx, operator_id, body, if_match))


@router.delete("/operators/{operator_id}", status_code=204)
def delete_operator(operator_id: str, if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> Response:
    resources.delete_operator(ctx, operator_id, if_match)
    return _no_content()


@router.get("/tool-pools")
def list_tool_pools(q: str | None = Query(None, max_length=200), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(resources.list_tool_pools(ctx, q))


@router.post("/tool-pools", status_code=201)
def create_tool_pool(body: ToolPoolInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = resources.create_tool_pool(ctx, body)
    return respond(rec, 201, f"/tool-pools/{rec.id}")


@router.put("/tool-pools/{tool_pool_id}")
def put_tool_pool(tool_pool_id: str, body: ToolPoolInput, if_match: str | None = IfMatch,
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(resources.update_tool_pool(ctx, tool_pool_id, body, if_match))


@router.delete("/tool-pools/{tool_pool_id}", status_code=204)
def delete_tool_pool(tool_pool_id: str, if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> Response:
    resources.delete_tool_pool(ctx, tool_pool_id, if_match)
    return _no_content()


# ---------------------------------------------------------------- 67 health

@router.get("/health")
def get_health(as_of: PlanDate | None = None, horizon_days: int | None = Query(default=None, ge=7, le=730),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(health.health(ctx, as_of, horizon_days))


# ---------------------------------------------------------------- 68-74 imports, export, templates

@router.post("/imports", status_code=201)
async def upload_import(request: Request, filename: str = Query(min_length=1, max_length=200),
                        sheet: str | None = Query(default=None, min_length=1, max_length=64),
                        ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    data = await request.body()
    rec = await run_in_threadpool(imports.upload, ctx, data, filename, sheet)
    return respond(rec, 201, f"/imports/{rec['id']}")


@router.get("/imports/{import_id}")
def get_import(import_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(imports.get_import(ctx, import_id))


@router.put("/imports/{import_id}/mapping")
def put_import_mapping(import_id: str, body: ImportMappingRequest, if_match: str | None = IfMatch,
                       ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(imports.put_mapping(ctx, import_id, body.model_dump(mode="json"), if_match))


@router.post("/imports/{import_id}/commit")
def commit_import(import_id: str, body: EmptyRequest = Body(default_factory=EmptyRequest),
                  if_match: str | None = IfMatch, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(imports.commit(ctx, import_id, if_match))


@router.delete("/imports/{import_id}", status_code=204)
def delete_import(import_id: str, ctx: AppContext = Depends(get_ctx)) -> Response:
    imports.delete_import(ctx, import_id)
    return _no_content()


def _file(data: bytes, name: str, media: str) -> Response:
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/export")
def export(format: Literal["xlsx", "zip"] = "xlsx", ctx: AppContext = Depends(get_ctx)) -> Response:
    return _file(*imports.export_file(ctx, format))


@router.get("/import-templates")
def import_templates(format: Literal["xlsx", "zip"] = "xlsx") -> Response:
    return _file(*imports.template_file(format))


# ---------------------------------------------------------------- 75-77 samples, reset

@router.get("/samples")
def list_samples() -> JSONResponse:
    return _ok(samples.list_samples())


@router.post("/samples/{sample_id}/load")
def load_sample(sample_id: str, body: SampleLoadRequest = Body(default_factory=SampleLoadRequest),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(samples.load(ctx, sample_id, body.replace))


@router.post("/reset")
def reset(body: ResetRequest, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(samples.reset(ctx, body.confirm))
