"""M9 `/api/v1/mfg` endpoints (M9-DESIGN 9: N1-N16, S1-S23, T1-T8, P1-P5; one permission each). Services:
`services/{network,sop,trade}.py`; until a service function is implemented it answers from
`api/mfg/fixtures/example_m9.json` (`services/m9_examples.py`, PEP 562 fallback as M8).

N/S/T routes answer only in the organisation's network workspace (409 `NET_WORKSPACE_REQUIRED` elsewhere,
`access.workspace_guard`); P routes are plant routes (`GET /trade/risk` serves both: org-wide in the network
workspace, the plant's own item-suppliers in a plant). Fixed paths precede parameterised siblings; path ids are
plain `str` (malformed / unknown / foreign -> 404). The approval route needs only `view`: who may sign is decided by
the signature policy `sop_cycle.approve` (reviewed: plant manager, approved: executive).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from ...mfg.network.model import LaneInput, NetParams, RampCurvesInput, SourcingInput
from ...mfg.sop.model import (AdvanceInput, ApproveInput, AspInput, CancelInput, CopyInput, CycleInput,
                              OverrideInput, RecommendInput, ReopenInput, ScenarioInput)
from ...mfg.trade.model import (CountryRiskListInput, FxInput, ItemTradeInput, MilestonesInput, ReportInput,
                                TariffsInput)
from ..context import AppContext, get_ctx
from .router_m2 import P, Id, Limit, Offset, _if_match, _no_content, _ok
from .services.qa_common import Act, act

router = APIRouter(prefix="/mfg", tags=["mfg-m9"])
Key = Query(default=None, max_length=64)


def _rec(result: Any, status: int = 200) -> JSONResponse:
    etag = result.get("row_version") if isinstance(result, dict) else None
    return _ok(result, status, etag=etag if isinstance(etag, int) else None)


def _signed(result: Any) -> JSONResponse:
    if isinstance(result, dict) and result.get("status") == "pending_signatures":
        return _ok(result, 202)
    return _rec(result)


# ---------------------------------------------------------------- N1-N7 topology

@router.get("/net/nodes", dependencies=P("view"))
def list_nodes(a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.list_nodes(ctx, a))


@router.get("/net/lanes", dependencies=P("view"))
def list_lanes(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.list_lanes(ctx))


@router.post("/net/lanes", status_code=201, dependencies=P("network_edit"))
def create_lane(body: LaneInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _rec(network.create_lane(ctx, a, body), 201)


@router.put("/net/lanes/{lane_id}", dependencies=P("network_edit"))
def update_lane(lane_id: str, body: LaneInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _rec(network.update_lane(ctx, a, lane_id, body, if_match))


@router.delete("/net/lanes/{lane_id}", status_code=204, dependencies=P("network_edit"))
def delete_lane(lane_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
                ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import network

    network.delete_lane(ctx, a, lane_id, if_match)
    return _no_content()


@router.get("/net/sourcing", dependencies=P("view"))
def list_sourcing(dest: str | None = Id(), key: str | None = Key, family: str | None = Query(default=None,
                  max_length=32), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.list_sourcing(ctx, dest, key, family))


@router.post("/net/sourcing", status_code=201, dependencies=P("network_edit"))
def create_sourcing(body: SourcingInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _rec(network.create_sourcing(ctx, a, body), 201)


@router.get("/net/sourcing/resolve", dependencies=P("view"))
def resolve_sourcing(dest: str = Query(max_length=64), key: str = Query(max_length=64), date_: date | None = Query(
                     default=None, alias="date"), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.resolve(ctx, dest, key, date_))


@router.put("/net/sourcing/{rule_id}", dependencies=P("network_edit"))
def update_sourcing(rule_id: str, body: SourcingInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _rec(network.update_sourcing(ctx, a, rule_id, body, if_match))


@router.delete("/net/sourcing/{rule_id}", status_code=204, dependencies=P("network_edit"))
def delete_sourcing(rule_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
                    ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import network

    network.delete_sourcing(ctx, a, rule_id, if_match)
    return _no_content()


# ---------------------------------------------------------------- N8-N15 runs

@router.get("/net/runs", dependencies=P("view"))
def list_net_runs(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.list_runs(ctx, limit, offset))


@router.post("/net/runs", status_code=202, dependencies=P("network_plan"))
def create_net_run(body: NetParams, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.create_run(ctx, a, body), 202)


@router.get("/net/runs/{run_id}", dependencies=P("view"))
def get_net_run(run_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.get_run(ctx, run_id))


@router.get("/net/runs/{run_id}/grid", dependencies=P("view"))
def net_grid(run_id: str, node: str | None = Id(), key: str | None = Key, family: str | None = Query(
             default=None, max_length=32), page: int = Query(default=1, ge=1, le=10_000), limit: int = Query(
             default=50, ge=1, le=500), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.grid(ctx, run_id, node, key, family, page, limit))


@router.get("/net/runs/{run_id}/transfers", dependencies=P("view"))
def net_transfers(run_id: str, src: str | None = Id(), dst: str | None = Id(), limit: int = Limit(),
                  offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.transfers(ctx, run_id, src, dst, limit, offset))


@router.get("/net/runs/{run_id}/shortages", dependencies=P("view"))
def net_shortages(run_id: str, limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)
                  ) -> JSONResponse:
    from .services import network

    return _ok(network.shortages(ctx, run_id, limit, offset))


@router.get("/net/runs/{run_id}/utilisation", dependencies=P("view"))
def net_utilisation(run_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.utilisation(ctx, run_id))


@router.get("/net/runs/{run_id}/pegging", dependencies=P("view"))
def net_pegging(run_id: str, node: str | None = Id(), key: str | None = Key, week: date | None = None,
                supply_id: str | None = Id(), a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                ) -> JSONResponse:
    from .services import network

    return _ok(network.pegging(ctx, a, run_id, node, key, week, supply_id))


@router.post("/net/runs/{run_id}/publish", dependencies=P("network_publish"))
def net_publish(run_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.publish(ctx, a, run_id))


@router.get("/net/ramp-curves", dependencies=P("view"))
def get_curves(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.get_curves(ctx))


@router.put("/net/ramp-curves", dependencies=P("network_edit"))
def put_curves(body: RampCurvesInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import network

    return _ok(network.put_curves(ctx, a, body))


# ---------------------------------------------------------------- S1-S10 cycles and demand review

@router.get("/sop/cycles", dependencies=P("view"))
def list_cycles(status: str | None = Query(default=None, max_length=64), limit: int = Limit(),
                offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.list_cycles(ctx, status, limit, offset))


@router.post("/sop/cycles", status_code=201, dependencies=P("sop_edit"))
def create_cycle(body: CycleInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _rec(sop.create_cycle(ctx, a, body), 201)


@router.get("/sop/cycles/{cycle_id}", dependencies=P("view"))
def get_cycle(cycle_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _rec(sop.get_cycle(ctx, cycle_id))


@router.post("/sop/cycles/{cycle_id}/advance", dependencies=P("sop_edit"))
def advance_cycle(cycle_id: str, body: AdvanceInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _rec(sop.advance(ctx, a, cycle_id, body, if_match))


@router.post("/sop/cycles/{cycle_id}/reopen", dependencies=P("sop_edit"))
def reopen_cycle(cycle_id: str, body: ReopenInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _rec(sop.reopen(ctx, a, cycle_id, body, if_match))


@router.post("/sop/cycles/{cycle_id}/cancel", dependencies=P("sop_edit"))
def cancel_cycle(cycle_id: str, body: CancelInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _rec(sop.cancel(ctx, a, cycle_id, body, if_match))


@router.get("/sop/cycles/{cycle_id}/demand", dependencies=P("view"))
def cycle_demand(cycle_id: str, node: str | None = Id(), family: str | None = Query(default=None, max_length=32),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.demand(ctx, cycle_id, node, family))


@router.get("/sop/cycles/{cycle_id}/demand/overrides", dependencies=P("view"))
def list_demand_overrides(cycle_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.list_overrides(ctx, cycle_id))


@router.post("/sop/cycles/{cycle_id}/demand/overrides", status_code=201, dependencies=P("sop_edit"))
def create_demand_override(cycle_id: str, body: OverrideInput, a: Act = Depends(act),
                           ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.create_override(ctx, a, cycle_id, body), 201)


@router.put("/sop/cycles/{cycle_id}/demand/asp", dependencies=P("sop_edit"))
def put_asp(cycle_id: str, body: AspInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
            ) -> JSONResponse:
    from .services import sop

    return _ok(sop.put_asp(ctx, a, cycle_id, body))


@router.delete("/sop/demand-overrides/{override_id}", dependencies=P("sop_edit"))
def remove_demand_override(override_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                           ) -> JSONResponse:
    from .services import sop

    return _ok(sop.remove_override(ctx, a, override_id))


@router.post("/sop/cycles/{cycle_id}/recommend", dependencies=P("sop_edit"))
def recommend(cycle_id: str, body: RecommendInput, if_match: str | None = _if_match(), a: Act = Depends(act),
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _rec(sop.recommend(ctx, a, cycle_id, body, if_match))


@router.post("/sop/cycles/{cycle_id}/approve", dependencies=P("view"))
def approve_cycle(cycle_id: str, body: ApproveInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                  ) -> JSONResponse:
    from .services import sop

    return _signed(sop.approve(ctx, a, cycle_id, body))


@router.post("/sop/cycles/{cycle_id}/publish", status_code=202, dependencies=P("sop_publish"))
def publish_cycle(cycle_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.publish(ctx, a, cycle_id), 202)


# ---------------------------------------------------------------- S11-S21 scenarios

@router.get("/sop/scenarios", dependencies=P("view"))
def list_scenarios(cycle_id: str | None = Id(), limit: int = Limit(), offset: int = Offset(),
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.list_scenarios(ctx, cycle_id, limit, offset))


@router.post("/sop/scenarios", status_code=201, dependencies=P("sop_edit"))
def create_scenario(body: ScenarioInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _rec(sop.create_scenario(ctx, a, body), 201)


@router.get("/sop/compare", dependencies=P("view"))
def compare(ids: str = Query(max_length=400), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.compare(ctx, ids))


@router.get("/sop/scenarios/{scenario_id}", dependencies=P("view"))
def get_scenario(scenario_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _rec(sop.get_scenario(ctx, scenario_id))


@router.put("/sop/scenarios/{scenario_id}", dependencies=P("sop_edit"))
def update_scenario(scenario_id: str, body: ScenarioInput, if_match: str | None = _if_match(),
                    a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _rec(sop.update_scenario(ctx, a, scenario_id, body, if_match))


@router.delete("/sop/scenarios/{scenario_id}", status_code=204, dependencies=P("sop_edit"))
def delete_scenario(scenario_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
                    ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import sop

    sop.delete_scenario(ctx, a, scenario_id, if_match)
    return _no_content()


@router.post("/sop/scenarios/{scenario_id}/run", status_code=202, dependencies=P("sop_edit"))
def run_scenario(scenario_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.run_scenario(ctx, a, scenario_id), 202)


@router.post("/sop/scenarios/{scenario_id}/copy", status_code=201, dependencies=P("sop_edit"))
def copy_scenario(scenario_id: str, body: CopyInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                  ) -> JSONResponse:
    from .services import sop

    return _rec(sop.copy_scenario(ctx, a, scenario_id, body), 201)


@router.get("/sop/scenarios/{scenario_id}/plan", dependencies=P("view"))
def scenario_plan(scenario_id: str, node: str | None = Id(), family: str | None = Query(default=None, max_length=32),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.plan(ctx, scenario_id, node, family))


@router.get("/sop/scenarios/{scenario_id}/rough-cut", dependencies=P("view"))
def scenario_rough_cut(scenario_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.rough_cut(ctx, scenario_id))


@router.get("/sop/scenarios/{scenario_id}/financial", dependencies=P("view"))
def scenario_financial(scenario_id: str, group_by: Literal["total", "node", "family"] = "total",
                       ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.financial(ctx, scenario_id, group_by))


@router.get("/sop/scenarios/{scenario_id}/make-buy", dependencies=P("view"))
def scenario_make_buy(scenario_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import sop

    return _ok(sop.make_buy(ctx, scenario_id))


# ---------------------------------------------------------------- T1-T8 trade (network)

@router.get("/trade/tariffs", dependencies=P("view"))
def get_tariffs(dest: str | None = Query(default=None, max_length=2), ctx: AppContext = Depends(get_ctx)
                ) -> JSONResponse:
    from .services import trade

    return _ok(trade.get_tariffs(ctx, dest))


@router.put("/trade/tariffs", dependencies=P("trade_admin"))
def put_tariffs(body: TariffsInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _ok(trade.put_tariffs(ctx, a, body))


@router.get("/trade/fx", dependencies=P("view"))
def get_fx(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _ok(trade.get_fx(ctx))


@router.put("/trade/fx", dependencies=P("trade_admin"))
def put_fx(body: FxInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _ok(trade.put_fx(ctx, a, body))


@router.get("/trade/milestones", dependencies=P("view"))
def get_milestones(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _ok(trade.get_milestones(ctx))


@router.put("/trade/milestones", dependencies=P("trade_admin"))
def put_milestones(body: MilestonesInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                   ) -> JSONResponse:
    from .services import trade

    return _ok(trade.put_milestones(ctx, a, body))


@router.get("/trade/country-risk", dependencies=P("view"))
def get_country_risk(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _ok(trade.get_country_risk(ctx))


@router.put("/trade/country-risk", dependencies=P("trade_admin"))
def put_country_risk(body: CountryRiskListInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                     ) -> JSONResponse:
    from .services import trade

    return _ok(trade.put_country_risk(ctx, a, body))


@router.get("/trade/reports", dependencies=P("view"))
def list_reports(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _ok(trade.list_reports(ctx, limit, offset))


@router.post("/trade/reports", status_code=202, dependencies=P("view"))
def create_report(body: ReportInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _ok(trade.create_report(ctx, a, body), 202)


@router.get("/trade/reports/{report_id}", dependencies=P("view"))
def get_report(report_id: str, format: Literal["json", "xlsx"] = "json", ctx: AppContext = Depends(get_ctx)
               ) -> Response:
    from .services import trade

    out = trade.get_report(ctx, report_id, format)
    if format == "xlsx" and isinstance(out, tuple):
        content, name = out
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return _ok(out)


@router.get("/trade/lots/{plant}/{lot_id}/content", dependencies=P("view"))
def network_lot_content(plant: str, lot_id: str, milestone_id: str | None = Id(), a: Act = Depends(act),
                        ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _ok(trade.network_lot_content(ctx, a, plant, lot_id, milestone_id))


@router.get("/trade/risk", dependencies=P("view"))
def risk(node: str | None = Id(), min_score: int = Query(default=0, ge=0, le=100), a: Act = Depends(act),
         ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _ok(trade.risk(ctx, a, node, min_score))


# ---------------------------------------------------------------- P1-P5 plant routes

@router.get("/trade/landed", dependencies=P("view"))
def landed(item_id: str = Query(max_length=64), month: date | None = None, ctx: AppContext = Depends(get_ctx)
           ) -> JSONResponse:
    from .services import trade

    return _ok(trade.landed_rows(ctx, item_id, month))


@router.get("/items/{item_id}/trade", dependencies=P("view"))
def get_item_trade(item_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _rec(trade.get_item_trade(ctx, item_id))


@router.put("/items/{item_id}/trade", dependencies=P("master_edit"))
def put_item_trade(item_id: str, body: ItemTradeInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _rec(trade.put_item_trade(ctx, a, item_id, body, if_match))


@router.get("/lots/{lot_id}/content", dependencies=P("view"))
def lot_content(lot_id: str, milestone_id: str | None = Id(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import trade

    return _ok(trade.lot_content(ctx, lot_id, milestone_id))


@router.get("/mps/targets", dependencies=P("view"))
def mps_targets(family: str | None = Query(default=None, max_length=32), from_: date | None = Query(
                default=None, alias="from"), to: date | None = None, ctx: AppContext = Depends(get_ctx)
                ) -> JSONResponse:
    from .services import trade

    return _ok(trade.mps_targets(ctx, family, from_, to))
