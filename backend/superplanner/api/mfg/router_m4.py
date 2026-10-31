"""`/api/v1/mfg` M4 endpoints (M4-DESIGN 11 #200-226; #206 is M3's #176 extended and stays in `router_m3`):
26 new operations, one permission each (`require_perm`). Fixed paths precede parameterised siblings. Path ids are
plain `str` (malformed / unknown / foreign -> 404). Supervisor-only event types / force flags of #203 are checked in
the service against the principal (`floor_supervise`)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ...mfg.model_m4 import (BackflushRetryInput, BatchLoadInput, DowntimeInput, DowntimeUpdate, FloorEventInput,
                             ReplanRunInput, SimulationInput, TriggerNote)
from ...mfg.model import PlanDateTime
from ..context import AppContext, get_ctx
from .access import MfgPrincipal, mfg_principal
from .router_m2 import P, Id, Limit, Offset, QText, _idem, _idem_key, _if_match, _ok
from .services import downtime, floor, kpi, replan, serials, simulation

router = APIRouter(prefix="/mfg", tags=["mfg-m4"])

EventTypeQ = Literal["setup_start", "start", "pause", "resume", "report", "complete", "reopen", "correct", "skip"]


# ---------------------------------------------------------------- 200-205 floor

@router.get("/floor/scan", dependencies=P("floor_view"))
def floor_scan(code: str = Query(min_length=1, max_length=100), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(floor.scan(ctx, code))


@router.get("/floor/queue", dependencies=P("floor_view"))
def floor_queue(line_id: str = Query(max_length=64), shift: str | None = Query(default=None, max_length=32),
                date_: date | None = Query(default=None, alias="date"),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(floor.queue(ctx, line_id, shift, date_))


@router.get("/floor/operations/{wo_op_id}", dependencies=P("floor_view"))
def floor_operation(wo_op_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(floor.operation_detail(ctx, wo_op_id))


@router.post("/floor/events", status_code=201, dependencies=P("floor_report"))
def floor_event(body: FloorEventInput, p: MfgPrincipal = Depends(mfg_principal),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    out, replayed = floor.post_event(ctx, body, p)
    if replayed:
        return _ok(out, 200, headers={"Idempotent-Replay": "true"})
    return _ok(out, 201)


@router.get("/floor/events", dependencies=P("floor_view"))
def floor_events(wo_id: str | None = Id(), line_id: str | None = Id(), operator_id: str | None = Id(),
                 wo_operation_id: str | None = Id(), type: EventTypeQ | None = None,  # noqa: A002
                 from_: PlanDateTime | None = Query(default=None, alias="from"),
                 to: PlanDateTime | None = None, limit: int = Limit(), offset: int = Offset(),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(floor.list_events(ctx, wo_id=wo_id, line_id=line_id, operator_id=operator_id,
                                 wo_operation_id=wo_operation_id, event_type=type, from_=from_, to=to, limit=limit,
                                 offset=offset))


@router.post("/floor/backflush/retry", dependencies=P("inventory"))
def backflush_retry(body: BackflushRetryInput | None = None, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(floor.retry_backflush(ctx, (body or BackflushRetryInput()).wo_id))


# ---------------------------------------------------------------- 207 WO operations refresh (206 = M3 #176)

@router.post("/work-orders/{wo_id}/operations/refresh", dependencies=P("wo_edit"))
def wo_operations_refresh(wo_id: str, if_match: str | None = _if_match(),
                          ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    out = floor.refresh_operations(ctx, wo_id, if_match)
    return _ok(out, etag=out["wo"]["row_version"])


# ---------------------------------------------------------------- 208-210 downtime

@router.get("/downtime", dependencies=P("view"))
def list_downtime(line_id: str | None = Id(), open: bool | None = None,  # noqa: A002
                  from_: PlanDateTime | None = Query(default=None, alias="from"), to: PlanDateTime | None = None,
                  limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(downtime.list_downtime(ctx, line_id=line_id, open_=open, from_=from_, to=to, limit=limit,
                                      offset=offset))


@router.post("/downtime", status_code=201, dependencies=P("downtime_report"))
def create_downtime(body: DowntimeInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = downtime.create_downtime(ctx, body)
    return _ok(rec, 201, etag=rec["row_version"], headers={"Location": f"/api/v1/mfg/downtime/{rec['id']}"})


@router.put("/downtime/{downtime_id}", dependencies=P("downtime_report"))
def update_downtime(downtime_id: str, body: DowntimeUpdate, if_match: str | None = _if_match(),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = downtime.update_downtime(ctx, downtime_id, body, if_match)
    return _ok(rec, etag=rec["row_version"])


# ---------------------------------------------------------------- 211-213 batch loads

@router.get("/batch-loads", dependencies=P("floor_view"))
def list_batch_loads(line_id: str | None = Id(),
                     status: Literal["open", "running", "completed", "cancelled"] | None = None,
                     limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(floor.list_loads(ctx, line_id=line_id, status=status, limit=limit, offset=offset))


@router.post("/batch-loads", status_code=201, dependencies=P("floor_report"))
def create_batch_load(body: BatchLoadInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = floor.create_load(ctx, body)
    return _ok(rec, 201, etag=rec["row_version"], headers={"Location": f"/api/v1/mfg/batch-loads/{rec['id']}"})


@router.get("/batch-loads/{load_id}", dependencies=P("floor_view"))
def get_batch_load(load_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = floor.get_load(ctx, load_id)
    return _ok(rec, etag=rec["row_version"])


# ---------------------------------------------------------------- 214-215 serials

@router.get("/serials", dependencies=P("view"))
def list_serials(item_id: str | None = Id(), q: str | None = QText(),
                 status: Literal["wip", "in_stock", "consumed", "shipped", "scrapped"] | None = None,
                 wo_id: str | None = Id(), limit: int = Limit(), offset: int = Offset(),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(serials.list_serials(ctx, item_id=item_id, q=q, status=status, wo_id=wo_id, limit=limit,
                                    offset=offset))


@router.get("/serials/{serial_id}", dependencies=P("view"))
def get_serial(serial_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(serials.get_serial(ctx, serial_id))


# ---------------------------------------------------------------- 216-221 replan, notifications

@router.get("/replan/triggers", dependencies=P("view"))
def list_triggers(status: Literal["open", "attached", "handled", "ignored"] | None = None,
                  kind: Literal["line_down", "late_receipt", "scrap_shortfall", "overrun", "rush_order",
                                "not_started", "start_short"] | None = None,
                  limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(replan.list_triggers(ctx, status=status, kind=kind, limit=limit, offset=offset))


@router.post("/replan/triggers/{trigger_id}/ignore", dependencies=P("replan_manage"))
def ignore_trigger(trigger_id: str, body: TriggerNote | None = None,
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(replan.close_trigger(ctx, trigger_id, "ignored", (body or TriggerNote()).note))


@router.post("/replan/triggers/{trigger_id}/handle", dependencies=P("replan_manage"))
def handle_trigger(trigger_id: str, body: TriggerNote | None = None,
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(replan.close_trigger(ctx, trigger_id, "handled", (body or TriggerNote()).note))


@router.post("/replan/run", status_code=202, dependencies=P("schedule_run"))
def replan_run(body: ReplanRunInput | None = None, idem_key: str | None = _idem_key(),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec, replayed = replan.run_replan(ctx, (body or ReplanRunInput()).trigger_ids, _idem(idem_key))
    if replayed:
        return _ok(rec, 202, etag=rec["row_version"], headers={"Idempotent-Replay": "true"})
    return _ok(rec, 202, etag=rec["row_version"], headers={"Location": f"/api/v1/mfg/aps/runs/{rec['id']}"})


@router.get("/notifications", dependencies=P("view"))
def list_notifications(unacked: bool | None = None, limit: int = Limit(), offset: int = Offset(),
                       ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(replan.list_notifications(ctx, unacked=unacked, limit=limit, offset=offset))


@router.post("/notifications/{notification_id}/ack", dependencies=P("view"))
def ack_notification(notification_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(replan.ack_notification(ctx, notification_id))


# ---------------------------------------------------------------- 222-223 KPIs

@router.get("/kpis", dependencies=P("view"))
def get_kpis(from_: date | None = Query(default=None, alias="from"), to: date | None = None,
             dim: Literal["plant", "group", "line"] = "plant", dim_id: str | None = Id(),
             bucket: Literal["day", "week"] = "day", ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(kpi.kpis(ctx, from_, to, dim, dim_id, bucket))


@router.get("/kpis/adherence", dependencies=P("view"))
def get_adherence(from_: date | None = Query(default=None, alias="from"), to: date | None = None,
                  line_id: str | None = Id(), limit: int = Query(default=200, ge=1, le=1000), offset: int = Offset(),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(kpi.adherence(ctx, from_, to, line_id, limit, offset))


# ---------------------------------------------------------------- 224-226 risk simulations

@router.post("/aps/simulations", status_code=202, dependencies=P("schedule_run"))
def create_simulation(body: SimulationInput, idem_key: str | None = _idem_key(),
                      ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec, replayed = simulation.create_simulation(ctx, body, _idem(idem_key))
    if replayed:
        return _ok(rec, 202, etag=rec["row_version"], headers={"Idempotent-Replay": "true"})
    return _ok(rec, 202, etag=rec["row_version"],
               headers={"Location": f"/api/v1/mfg/aps/simulations/{rec['id']}"})


@router.get("/aps/simulations", dependencies=P("view"))
def list_simulations(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    return _ok(simulation.list_simulations(ctx, limit=limit, offset=offset))


@router.get("/aps/simulations/{simulation_id}", dependencies=P("view"))
def get_simulation(simulation_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    rec = simulation.get_simulation(ctx, simulation_id)
    return _ok(rec, etag=rec["row_version"])
