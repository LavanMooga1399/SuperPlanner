"""M8 `/api/v1/mfg` endpoints (M8-DESIGN 11: F1-F17, I1-I7, R1-R9, S1-S7, K1-K6, N1-N2, V1-V4, X1-X2; one
permission each). Services: `services/{forecast,invopt,planning,rate,ster,kanban,valid,sap}.py`; until a service
function is implemented it answers from `api/mfg/fixtures/example_m8.json` (`services/m8_examples.py`).

Fixed paths precede parameterised siblings. Path ids are plain `str` (malformed / unknown / foreign -> 404).
`DELETE /forecast/overrides/{id}` takes its reason in `X-SP-Change-Reason` (bound by the mfg principal dependency).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from ...mfg.forecast.model import ForecastParams, HistoryUpdate, OverrideInput, VersionInput
from ...mfg.invopt.model import DecideInput, SsParams
from ...mfg.model_m8 import (BaselineInput, ChangeoverMatrixInput, ItemPlanningInput, KanbanLoopInput,
                             KanbanScanInput, LineRatesInput, PackagingInput, PlanningSettings, SapSettings,
                             SapSyncInput)
from ...mfg.rate.model import RateParams
from ...mfg.ster.model import AdvanceInput, FailInput, ReleaseInput, SterPlanInput
from ..context import AppContext, get_ctx
from .router_m2 import P, Id, Limit, Offset, QText, _if_match, _no_content, _ok
from .services.qa_common import Act, act

router = APIRouter(prefix="/mfg", tags=["mfg-m8"])


def _rec(result: Any, status: int = 200) -> JSONResponse:
    etag = result.get("row_version") if isinstance(result, dict) else None
    return _ok(result, status, etag=etag if isinstance(etag, int) else None)


def _signed(result: Any) -> JSONResponse:
    if isinstance(result, dict) and result.get("status") == "pending_signatures":
        return _ok(result, 202)
    return _rec(result)


Bucket = Literal["m", "w"]


# ---------------------------------------------------------------- F1-F3 demand history

@router.get("/forecast/history", dependencies=P("view"))
def list_history(item_id: str | None = Id(), bucket: Bucket | None = None, from_: date | None = Query(
                 default=None, alias="from"), to: date | None = None, limit: int = Query(default=200, ge=1, le=2000),
                 offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.list_history(ctx, item_id, bucket, from_, to, limit, offset))


@router.post("/forecast/history/refresh", dependencies=P("forecast_edit"))
def refresh_history(a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.refresh_history(ctx, a))


@router.put("/forecast/history/{history_id}", dependencies=P("forecast_edit"))
def put_history(history_id: str, body: HistoryUpdate, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                ) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.update_history(ctx, a, history_id, body))


# ---------------------------------------------------------------- F4-F6 runs

@router.get("/forecast/runs", dependencies=P("view"))
def list_forecast_runs(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)
                       ) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.list_runs(ctx, limit, offset))


@router.post("/forecast/runs", status_code=202, dependencies=P("forecast_edit"))
def create_forecast_run(body: ForecastParams, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                        ) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.create_run(ctx, a, body), 202)


@router.get("/forecast/runs/{run_id}", dependencies=P("view"))
def get_forecast_run(run_id: str, item_id: str | None = Id(), method: str | None = Query(default=None, max_length=16),
                     flag: str | None = Query(default=None, max_length=32), limit: int = Limit(),
                     offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.get_run(ctx, run_id, item_id, method, flag, limit, offset))


# ---------------------------------------------------------------- F7-F15 versions, lines, overrides

@router.get("/forecast/versions", dependencies=P("view"))
def list_versions(status: Literal["draft", "active", "archived"] | None = None, limit: int = Limit(),
                  offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.list_versions(ctx, status, limit, offset))


@router.post("/forecast/versions", status_code=201, dependencies=P("forecast_edit"))
def create_version(body: VersionInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import forecast

    return _rec(forecast.create_version(ctx, a, body), 201)


@router.get("/forecast/versions/{version_id}", dependencies=P("view"))
def get_version(version_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import forecast

    return _rec(forecast.get_version(ctx, version_id))


@router.get("/forecast/versions/{version_id}/lines", dependencies=P("view"))
def version_lines(version_id: str, item_id: str | None = Id(), family: str | None = Query(default=None,
                  max_length=32), abc: Literal["A", "B", "C"] | None = None, q: str | None = QText(),
                  limit: int = Query(default=100, ge=1, le=500), offset: int = Offset(),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.version_lines(ctx, version_id, item_id, family, abc, q, limit, offset))


@router.post("/forecast/versions/{version_id}/activate", dependencies=P("forecast_approve"))
def activate_version(version_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
                     ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import forecast

    return _rec(forecast.activate_version(ctx, a, version_id, if_match))


@router.delete("/forecast/versions/{version_id}", dependencies=P("forecast_edit"))
def delete_version(version_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
                   ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import forecast

    forecast.delete_version(ctx, a, version_id, if_match)
    return _no_content()


@router.get("/forecast/versions/{version_id}/overrides", dependencies=P("view"))
def list_overrides(version_id: str, include_removed: bool = False, ctx: AppContext = Depends(get_ctx)
                   ) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.list_overrides(ctx, version_id, include_removed))


@router.post("/forecast/versions/{version_id}/overrides", status_code=201, dependencies=P("forecast_edit"))
def create_override(version_id: str, body: OverrideInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                    ) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.create_override(ctx, a, version_id, body), 201)


@router.delete("/forecast/overrides/{override_id}", dependencies=P("forecast_edit"))
def delete_override(override_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.remove_override(ctx, a, override_id))


# ---------------------------------------------------------------- F16-F17 item view, accuracy

@router.get("/forecast/items/{item_id}", dependencies=P("view"))
def forecast_item(item_id: str, version_id: str | None = Id(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.item_view(ctx, item_id, version_id))


@router.get("/forecast/accuracy", dependencies=P("view"))
def forecast_accuracy(lag: int = Query(default=1, ge=1, le=12), group_by: Literal["item", "family", "abc", "all"] = "abc",
                      periods: int = Query(default=6, ge=1, le=36), ctx: AppContext = Depends(get_ctx)
                      ) -> JSONResponse:
    from .services import forecast

    return _ok(forecast.accuracy(ctx, lag, group_by, periods))


# ---------------------------------------------------------------- I1-I4 safety-stock proposals

@router.get("/invopt/runs", dependencies=P("view"))
def list_ss_runs(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import invopt

    return _ok(invopt.list_runs(ctx, limit, offset))


@router.post("/invopt/runs", status_code=202, dependencies=P("inventory_policy_edit"))
def create_ss_run(body: SsParams, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import invopt

    return _ok(invopt.create_run(ctx, a, body), 202)


@router.get("/invopt/runs/{run_id}", dependencies=P("view"))
def get_ss_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import invopt

    return _ok(invopt.get_run(ctx, run_id))


@router.get("/invopt/runs/{run_id}/lines", dependencies=P("view"))
def ss_lines(run_id: str, decision: Literal["pending", "approved", "rejected"] | None = None,
             abc: Literal["A", "B", "C"] | None = None, xyz: Literal["X", "Y", "Z"] | None = None,
             q: str | None = QText(), limit: int = Query(default=100, ge=1, le=1000), offset: int = Offset(),
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import invopt

    return _ok(invopt.list_lines(ctx, run_id, decision, abc, xyz, q, limit, offset))


@router.post("/invopt/runs/{run_id}/decide", dependencies=P("inventory_policy_approve"))
def ss_decide(run_id: str, body: DecideInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
              ) -> JSONResponse:
    from .services import invopt

    return _ok(invopt.decide(ctx, a, run_id, body))


# ---------------------------------------------------------------- I5-I7 item planning, packaging

@router.get("/items/{item_id}/planning", dependencies=P("view"))
def get_item_planning(item_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    return _rec(planning.get_item_planning(ctx, item_id))


@router.put("/items/{item_id}/planning", dependencies=P("master_edit"))
def put_item_planning(item_id: str, body: ItemPlanningInput, if_match: str | None = _if_match(),
                      a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    return _rec(planning.put_item_planning(ctx, a, item_id, body, if_match))


@router.get("/items/{item_id}/packaging", dependencies=P("view"))
def get_packaging(item_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    return _rec(planning.get_packaging(ctx, item_id))


@router.put("/items/{item_id}/packaging", dependencies=P("master_edit"))
def put_packaging(item_id: str, body: PackagingInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    return _rec(planning.put_packaging(ctx, a, item_id, body, if_match))


# ---------------------------------------------------------------- R1-R3 line rates, changeover matrix

@router.get("/lines/{line_id}/rates", dependencies=P("view"))
def get_line_rates(line_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    return _rec(planning.get_line_rates(ctx, line_id))


@router.put("/lines/{line_id}/rates", dependencies=P("master_edit"))
def put_line_rates(line_id: str, body: LineRatesInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    return _rec(planning.put_line_rates(ctx, a, line_id, body, if_match))


@router.get("/changeover-matrix", dependencies=P("view"))
def get_changeover_matrix(line_setup_family: str | None = Query(default=None, max_length=32),
                          ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    r = planning.get_changeover_matrix(ctx, line_setup_family)
    return _ok(r, etag=r.get("version") if isinstance(r, dict) else None)


@router.put("/changeover-matrix", dependencies=P("master_edit"))
def put_changeover_matrix(body: ChangeoverMatrixInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                          ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    r = planning.put_changeover_matrix(ctx, a, body, if_match)
    return _ok(r, etag=r.get("version") if isinstance(r, dict) else None)


# ---------------------------------------------------------------- R4-R9 rate runs

@router.get("/rate/runs", dependencies=P("view"))
def list_rate_runs(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import rate

    return _ok(rate.list_runs(ctx, limit, offset))


@router.post("/rate/runs", status_code=202, dependencies=P("rate_plan"))
def create_rate_run(body: RateParams, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import rate

    return _ok(rate.create_run(ctx, a, body), 202)


@router.get("/rate/compare", dependencies=P("view"))
def compare_rate_runs(a_id: str = Query(alias="a", max_length=64), b_id: str = Query(alias="b", max_length=64),
                      ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import rate

    return _ok(rate.compare(ctx, a_id, b_id))


@router.get("/rate/runs/{run_id}", dependencies=P("view"))
def get_rate_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import rate

    return _ok(rate.get_run(ctx, run_id))


@router.get("/rate/runs/{run_id}/blocks", dependencies=P("view"))
def rate_blocks(run_id: str, line_id: str | None = Id(), from_: date | None = Query(default=None, alias="from"),
                to: date | None = None, limit: int = Query(default=2000, ge=1, le=20_000), offset: int = Offset(),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import rate

    return _ok(rate.list_blocks(ctx, run_id, line_id, from_, to, limit, offset))


@router.get("/rate/runs/{run_id}/grid", dependencies=P("view"))
def rate_grid(run_id: str, bucket: Literal["shift", "day"] = "day", line_id: str | None = Id(),
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import rate

    return _ok(rate.grid(ctx, run_id, bucket, line_id))


@router.post("/rate/runs/{run_id}/publish", dependencies=P("rate_plan"))
def publish_rate_run(run_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import rate

    return _ok(rate.publish(ctx, a, run_id))


# ---------------------------------------------------------------- S1-S7 sterilisation

@router.post("/ster/plan", dependencies=P("ster_plan"))
def ster_plan(body: SterPlanInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import ster

    return _ok(ster.plan(ctx, a, body))


@router.get("/ster/loads", dependencies=P("view"))
def list_loads(status: str | None = Query(default=None, max_length=16), from_: date | None = Query(
               default=None, alias="from"), to: date | None = None, chamber_line_id: str | None = Id(),
               limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import ster

    return _ok(ster.list_loads(ctx, status, from_, to, chamber_line_id, limit, offset))


@router.get("/ster/loads/{load_id}", dependencies=P("view"))
def get_load(load_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import ster

    return _rec(ster.get_load(ctx, load_id))


@router.post("/ster/loads/{load_id}/load", dependencies=P("ster_plan"))
def load_load(load_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import ster

    return _rec(ster.load(ctx, a, load_id, if_match))


@router.post("/ster/loads/{load_id}/advance", dependencies=P("ster_plan"))
def advance_load(load_id: str, body: AdvanceInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import ster

    return _rec(ster.advance(ctx, a, load_id, body, if_match))


@router.post("/ster/loads/{load_id}/release", dependencies=P("ster_release"))
def release_load(load_id: str, body: ReleaseInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import ster

    return _signed(ster.release(ctx, a, load_id, body, if_match))


@router.post("/ster/loads/{load_id}/fail", dependencies=P("qa_decide"))
def fail_load(load_id: str, body: FailInput, if_match: str | None = _if_match(), a: Act = Depends(act),
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import ster

    return _rec(ster.fail(ctx, a, load_id, body, if_match))


# ---------------------------------------------------------------- K1-K6 kanban

@router.get("/kanban/loops", dependencies=P("view"))
def list_loops(item_id: str | None = Id(), limit: int = Limit(), offset: int = Offset(),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import kanban

    return _ok(kanban.list_loops(ctx, item_id, limit, offset))


@router.post("/kanban/loops", status_code=201, dependencies=P("kanban_edit"))
def create_loop(body: KanbanLoopInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import kanban

    return _rec(kanban.create_loop(ctx, a, body), 201)


@router.post("/kanban/scan", dependencies=P("kanban_scan"))
def kanban_scan(body: KanbanScanInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import kanban

    return _ok(kanban.scan(ctx, a, body))


@router.get("/kanban/loops/{loop_id}", dependencies=P("view"))
def get_loop(loop_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import kanban

    return _rec(kanban.get_loop(ctx, loop_id))


@router.put("/kanban/loops/{loop_id}", dependencies=P("kanban_edit"))
def put_loop(loop_id: str, body: KanbanLoopInput, if_match: str | None = _if_match(), a: Act = Depends(act),
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import kanban

    return _rec(kanban.update_loop(ctx, a, loop_id, body, if_match))


@router.get("/kanban/loops/{loop_id}/cards", dependencies=P("view"))
def loop_cards(loop_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import kanban

    return _ok(kanban.list_cards(ctx, loop_id))


# ---------------------------------------------------------------- N1-N2 planning settings, nightly chain

@router.get("/plant/planning-settings", dependencies=P("view"))
def get_planning_settings(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    return _rec(planning.get_settings(ctx))


@router.put("/plant/planning-settings", dependencies=P("owner"))
def put_planning_settings(body: PlanningSettings, if_match: str | None = _if_match(), a: Act = Depends(act),
                          ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    return _rec(planning.put_settings(ctx, a, body, if_match))


@router.post("/planning/nightly/run-now", status_code=202, dependencies=P("rate_plan"))
def nightly_run_now(a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import planning

    return _ok(planning.nightly_run_now(ctx, a), 202)


# ---------------------------------------------------------------- V1-V4 validation kit

@router.get("/validation/trace-matrix", dependencies=P("validation_view"))
def trace_matrix(format: Literal["json", "csv", "html"] = "json", ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import valid

    out = valid.trace_matrix(ctx, format)
    if format == "json":
        return _ok(out)
    data, name, media = out
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/validation/baselines", dependencies=P("validation_view"))
def list_baselines(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import valid

    return _ok(valid.list_baselines(ctx, limit, offset))


@router.post("/validation/baselines", status_code=201, dependencies=P("owner"))
def create_baseline(body: BaselineInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import valid

    return _ok(valid.create_baseline(ctx, a, body), 201)


@router.get("/validation/baselines/{baseline_id}", dependencies=P("validation_view"))
def get_baseline(baseline_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import valid

    return _ok(valid.get_baseline(ctx, baseline_id))


@router.get("/validation/baselines/{a_id}/diff/{b_id}", dependencies=P("validation_view"))
def diff_baselines(a_id: str, b_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import valid

    return _ok(valid.diff_baselines(ctx, a_id, b_id))


# ---------------------------------------------------------------- X1-X2 SAP S/4HANA

@router.get("/integration/sap-settings", dependencies=P("integration_admin"))
def get_sap_settings(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sap

    return _rec(sap.get_settings(ctx))


@router.put("/integration/sap-settings", dependencies=P("integration_admin"))
def put_sap_settings(body: SapSettings, if_match: str | None = _if_match(), a: Act = Depends(act),
                     ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sap

    return _rec(sap.put_settings(ctx, a, body, if_match))


@router.post("/integration/sap/sync", status_code=202, dependencies=P("integration_admin"))
def sap_sync(body: SapSyncInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sap

    return _ok(sap.sync(ctx, a, body), 202)
