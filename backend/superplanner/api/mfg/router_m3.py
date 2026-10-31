"""`/api/v1/mfg` M3 endpoints (M3-DESIGN 11 #164-199): 36 operations, one permission each (`require_perm`).
Fixed paths precede parameterised siblings (`/aps/runs/published`). Path ids are plain `str` (malformed / unknown /
foreign -> 404)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from ...mfg.aps.model import ApsParams, EditsRequest, PublishRequest, RunUpdate
from ...mfg.model import PlanDateTime
from ...mfg.model_m3 import OperationLineRateInput, OperatorAbsenceInput, SetupMatrixRowInput
from ..context import AppContext, get_ctx
from .access import MfgPrincipal, mfg_principal
from .router_m2 import P, Id, Limit, Offset, QText, _file, _if_match, _idem, _idem_key, _no_content, _ok
from .services import aps, aps_master
from .services.common import respond

router = APIRouter(prefix="/mfg", tags=["mfg-m3"])


def _int(v: str, what: str) -> int:
    """Path numbers are plain strings like ids: malformed -> 404 (as unknown)."""
    if not v.isdigit() or len(v) > 9:
        from ..errors import not_found

        raise not_found(what, v)
    return int(v)


# ---------------------------------------------------------------- 164-167 operation line rates

@router.get("/operation-line-rates", dependencies=P("view"))
def list_rates(operation_id: str | None = Id(), line_id: str | None = Id(), routing_id: str | None = Id(),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps_master.list_rates(ctx, operation_id, line_id, routing_id))


@router.post("/operation-line-rates", status_code=201, dependencies=P("master_edit"))
def create_rate(body: OperationLineRateInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = aps_master.create_rate(ctx, body)
    return respond(rec, 201, f"/operation-line-rates/{rec.id}")


@router.put("/operation-line-rates/{rate_id}", dependencies=P("master_edit"))
def put_rate(rate_id: str, body: OperationLineRateInput, if_match: str | None = _if_match(),
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(aps_master.update_rate(ctx, rate_id, body, if_match))


@router.delete("/operation-line-rates/{rate_id}", status_code=204, dependencies=P("master_edit"))
def delete_rate(rate_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    aps_master.delete_rate(ctx, rate_id, if_match)
    return _no_content()


# ---------------------------------------------------------------- 168-171 setup matrix

@router.get("/setup-matrix", dependencies=P("view"))
def list_matrix(line_setup_family: str | None = Query(default=None, max_length=32),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps_master.list_matrix(ctx, line_setup_family))


@router.post("/setup-matrix", status_code=201, dependencies=P("master_edit"))
def create_matrix_row(body: SetupMatrixRowInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = aps_master.create_matrix_row(ctx, body)
    return respond(rec, 201, f"/setup-matrix/{rec.id}")


@router.put("/setup-matrix/{row_id}", dependencies=P("master_edit"))
def put_matrix_row(row_id: str, body: SetupMatrixRowInput, if_match: str | None = _if_match(),
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(aps_master.update_matrix_row(ctx, row_id, body, if_match))


@router.delete("/setup-matrix/{row_id}", status_code=204, dependencies=P("master_edit"))
def delete_matrix_row(row_id: str, if_match: str | None = _if_match(),
                      ctx: AppContext = Depends(get_ctx)) -> Response:
    aps_master.delete_matrix_row(ctx, row_id, if_match)
    return _no_content()


# ---------------------------------------------------------------- 172-175 operator absences

@router.get("/operator-absences", dependencies=P("view"))
def list_absences(operator_id: str | None = Id(), frm: PlanDateTime | None = Query(default=None, alias="from"),
                  to: PlanDateTime | None = Query(default=None), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps_master.list_absences(ctx, operator_id, frm, to))


@router.post("/operator-absences", status_code=201, dependencies=P("master_edit"))
def create_absence(body: OperatorAbsenceInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = aps_master.create_absence(ctx, body)
    return respond(rec, 201, f"/operator-absences/{rec.id}")


@router.put("/operator-absences/{absence_id}", dependencies=P("master_edit"))
def put_absence(absence_id: str, body: OperatorAbsenceInput, if_match: str | None = _if_match(),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return respond(aps_master.update_absence(ctx, absence_id, body, if_match))


@router.delete("/operator-absences/{absence_id}", status_code=204, dependencies=P("master_edit"))
def delete_absence(absence_id: str, if_match: str | None = _if_match(),
                   ctx: AppContext = Depends(get_ctx)) -> Response:
    aps_master.delete_absence(ctx, absence_id, if_match)
    return _no_content()


# ---------------------------------------------------------------- 176-178 WO operations

@router.get("/work-orders/{wo_id}/operations", dependencies=P("view"))
def wo_operations(wo_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps_master.wo_operations(ctx, wo_id))


@router.post("/work-orders/{wo_id}/operations/{seq}/done", dependencies=P("floor_supervise"))   # M4 11
def wo_operation_done(wo_id: str, seq: str, if_match: str | None = _if_match(),
                      ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    out = aps_master.set_done(ctx, wo_id, seq, True, if_match)
    return _ok(out, etag=out["wo"]["row_version"])


@router.post("/work-orders/{wo_id}/operations/{seq}/reopen", dependencies=P("floor_supervise"))   # M4 11
def wo_operation_reopen(wo_id: str, seq: str, if_match: str | None = _if_match(),
                        ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    out = aps_master.set_done(ctx, wo_id, seq, False, if_match)
    return _ok(out, etag=out["wo"]["row_version"])


# ---------------------------------------------------------------- 179-187 APS runs

@router.post("/aps/runs", status_code=202, dependencies=P("schedule_run"))
def create_run(body: ApsParams, idem_key: str | None = _idem_key(), p: MfgPrincipal = Depends(mfg_principal),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec, replayed = aps.create_run(ctx, body, _idem(idem_key))
    if replayed:
        return _ok(rec, 202, etag=rec["row_version"], headers={"Idempotent-Replay": "true"})
    return _ok(rec, 202, etag=rec["row_version"], headers={"Location": f"/api/v1/mfg/aps/runs/{rec['id']}"})


@router.get("/aps/runs", dependencies=P("view"))
def list_runs(kind: Literal["live", "what_if"] | None = None,
              status: Literal["queued", "running", "completed", "failed", "cancelled"] | None = None,
              pinned: bool | None = None, limit: int = Limit(), offset: int = Offset(),
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.list_runs(ctx, kind=kind, status=status, pinned=pinned, limit=limit, offset=offset))


@router.get("/aps/runs/published", dependencies=P("view"))
def published_run(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = aps.published_run(ctx)
    return _ok(rec, etag=rec["row_version"])


@router.get("/aps/runs/{run_id}", dependencies=P("view"))
def get_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = aps.get_run(ctx, run_id)
    return _ok(rec, etag=rec["row_version"])


@router.put("/aps/runs/{run_id}", dependencies=P("schedule_run"))
def put_run(run_id: str, body: RunUpdate, if_match: str | None = _if_match(),
            ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = aps.update_run(ctx, run_id, body, if_match)
    return _ok(rec, etag=rec["row_version"])


@router.delete("/aps/runs/{run_id}", status_code=204, dependencies=P("schedule_run"))
def delete_run(run_id: str, if_match: str | None = _if_match(), ctx: AppContext = Depends(get_ctx)) -> Response:
    aps.delete_run(ctx, run_id, if_match)
    return _no_content()


@router.post("/aps/runs/{run_id}/cancel", dependencies=P("schedule_run"))
def cancel_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = aps.cancel_run(ctx, run_id)
    return _ok(rec, etag=rec["row_version"])


@router.post("/aps/runs/{run_id}/publish", dependencies=P("schedule_publish"))
def publish_run(run_id: str, body: PublishRequest | None = None, if_match: str | None = _if_match(),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = aps.publish_run(ctx, run_id, if_match, bool(body and body.confirm_stale_basis))
    return _ok(rec, etag=rec["row_version"])


@router.post("/aps/runs/{run_id}/edits", status_code=201, dependencies=P("schedule_run"))
def create_edits(run_id: str, body: EditsRequest, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = aps.create_edits(ctx, run_id, body)
    return _ok(rec, 201, etag=rec["row_version"], headers={"Location": f"/api/v1/mfg/aps/runs/{rec['id']}"})


# ---------------------------------------------------------------- 188-199 views

@router.get("/aps/runs/{run_id}/gantt", dependencies=P("view"))
def run_gantt(run_id: str, view: Literal["line", "order", "demand"] = "line",
              frm: PlanDateTime | None = Query(default=None, alias="from"), to: PlanDateTime | None = None,
              group_id: str | None = Id(), line_id: str | None = Id(), order_id: str | None = Id(),
              demand_order_id: str | None = Id(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.gantt(ctx, run_id, view=view, frm=frm, to=to, group_id=group_id, line_id=line_id,
                         order_id=order_id, demand_order_id=demand_order_id))


@router.get("/aps/runs/{run_id}/operations", dependencies=P("view"))
def run_operations(run_id: str, line_id: str | None = Id(), group_id: str | None = Id(), order_id: str | None = Id(),
                   status: Literal["scheduled", "unscheduled"] | None = None, late_only: bool = False,
                   frozen: bool | None = None, frm: PlanDateTime | None = Query(default=None, alias="from"),
                   to: PlanDateTime | None = None,
                   sort: Literal["start", "-late_minutes", "op_no", "line"] = "start", limit: int = Limit(),
                   offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.operations(ctx, run_id, line_id=line_id, group_id=group_id, order_id=order_id, status=status,
                              late_only=late_only, frozen=frozen, frm=frm, to=to, sort=sort, limit=limit,
                              offset=offset))


@router.get("/aps/runs/{run_id}/operations/{op_no}", dependencies=P("view"))
def run_operation(run_id: str, op_no: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.operation(ctx, run_id, op_no))


@router.get("/aps/runs/{run_id}/orders", dependencies=P("view"))
def run_orders(run_id: str, late_only: bool = False, order_type: Literal["wo", "planned"] | None = None,
               q: str | None = QText(), sort: Literal["-late_minutes", "due_at"] = "-late_minutes",
               limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.orders(ctx, run_id, late_only=late_only, order_type=order_type, q=q, sort=sort, limit=limit,
                          offset=offset))


@router.get("/aps/runs/{run_id}/demand", dependencies=P("view"))
def run_demand(run_id: str, late_only: bool = False, program: str | None = Query(default=None, max_length=32),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.demand(ctx, run_id, late_only=late_only, program=program))


@router.get("/aps/runs/{run_id}/load", dependencies=P("view"))
def run_load(run_id: str, group_id: str | None = Id(), line_id: str | None = Id(),
             bucket: Literal["day", "week"] = "day", frm: date | None = Query(default=None, alias="from"),
             to: date | None = None, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.load(ctx, run_id, group_id=group_id, line_id=line_id, bucket=bucket, frm=frm, to=to))


@router.get("/aps/runs/{run_id}/dispatch", dependencies=P("view"))
def run_dispatch(run_id: str, line_id: str = Query(max_length=64), day: date | None = Query(default=None, alias="date"),
                 shift: str | None = Query(default=None, max_length=32),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.dispatch(ctx, run_id, line_id=line_id, day=day, shift=shift))


@router.get("/aps/runs/{run_id}/overtime", dependencies=P("view"))
def run_overtime(run_id: str, status: Literal["opened", "suggested", "forced"] | None = None,
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.overtime(ctx, run_id, status=status))


@router.get("/aps/runs/{run_id}/exceptions", dependencies=P("view"))
def run_exceptions(run_id: str, code: list[str] | None = Query(default=None),
                   severity: list[Literal["critical", "warning", "info"]] | None = Query(default=None),
                   order_id: str | None = Id(), q: str | None = QText(), limit: int = Limit(),
                   offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.exceptions(ctx, run_id, code=code, severity=severity, order_id=order_id, q=q, limit=limit,
                              offset=offset))


@router.get("/aps/runs/{run_id}/bottlenecks", dependencies=P("view"))
def run_bottlenecks(run_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.bottlenecks(ctx, run_id))


@router.get("/aps/runs/{run_id}/compare", dependencies=P("view"))
def run_compare(run_id: str, with_: str = Query(alias="with", max_length=64),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(aps.compare(ctx, run_id, with_))


@router.get("/aps/runs/{run_id}/export", dependencies=P("view"))
def run_export(run_id: str, fmt: Literal["xlsx", "zip"] = Query(default="xlsx", alias="format"),
               ctx: AppContext = Depends(get_ctx)) -> Response:
    data, name, media = aps.export(ctx, run_id, fmt)
    return _file(data, name, media)


__all__ = ["router"]
_unused: tuple[Any, ...] = (datetime,)
