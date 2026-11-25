"""M7 `/api/v1/mfg` endpoints (M7-DESIGN 9: E1-E12, Q1-Q64; one permission each) and the platform routes
(`/auth/esig/*`, `/auth/oidc/stepup`, `/orgs/{org}/members/{member}/esig-revoke`, `/meta/time`) in
`platform_router`.

Signable actions take an optional `signature` in the body; an intermediate policy step answers 202
`{status: "pending_signatures", ...}` (4.2 (8)). Regulated updates accept `X-SP-Change-Reason` (bound by the mfg
principal dependency, `api/audit_diff.py`). Services: `services/esig.py`, `services/part11.py`, `services/qa_*.py`.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ...esig.model import EnrollInput, Part11ExportInput, Part11ModeInput, PolicyUpdate
from ...qa.model import (ApproveInput, CalibrationInput, CancelInput, CapaActionInput, CapaAdvanceInput, CapaInput,
                         CapaVerifyInput, ComplaintAdvanceInput, ComplaintInput, DecisionInput, EquipmentInput,
                         EquipmentStatusInput, FaCompleteInput, FieldActionInput, FieldActionUpdate, HoldInput,
                         HoldReleaseInput, InspectionLotInput, LinkInput, NcrInput, PlanInput, ProposeInput,
                         QaSettings, ResultsBatch, SchemeInput, UnitsBulkInput)
from ..auth.deps import Principal, require_user
from ..context import AppContext, get_ctx
from .router_m2 import P, Id, Limit, Offset, QText, _file, _if_match, _no_content, _ok
from .services.qa_common import Act, act

router = APIRouter(prefix="/mfg", tags=["mfg-m7"])
platform_router = APIRouter(tags=["m7"])


def _signed(result: Any, status: int = 200) -> JSONResponse:
    """A signable action's answer: the record, or 202 while further policy steps are pending."""
    if isinstance(result, dict) and result.get("status") == "pending_signatures":
        return _ok(result, 202)
    etag = result.get("row_version") if isinstance(result, dict) else None
    return _ok(result, status, etag=etag if isinstance(etag, int) else None)


def _rec(result: Any, status: int = 200) -> JSONResponse:
    etag = result.get("row_version") if isinstance(result, dict) else None
    return _ok(result, status, etag=etag if isinstance(etag, int) else None)


Sort = Query(default=None, max_length=40)


# ---------------------------------------------------------------- P1-P5 platform

@platform_router.get("/auth/esig/status")
def esig_status(request: Request, p: Principal = Depends(require_user), ctx: AppContext = Depends(get_ctx)
                ) -> JSONResponse:
    from .services import esig

    return _ok(esig.status(ctx, p))


@platform_router.post("/auth/esig/enroll")
def esig_enroll(body: EnrollInput, request: Request, p: Principal = Depends(require_user),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import esig

    return _ok(esig.enroll(ctx, p, body, request))


@platform_router.get("/auth/oidc/stepup")
def oidc_stepup(request: Request, purpose: Literal["esig"] = "esig", p: Principal = Depends(require_user),
                ctx: AppContext = Depends(get_ctx)) -> Response:
    from ...identity.service import OIDC_COOKIE
    from .services import esig

    url, binding = esig.stepup_start(ctx, p)
    r = RedirectResponse(url, status_code=302)
    r.set_cookie(OIDC_COOKIE, binding, max_age=600, httponly=True, samesite="lax",
                 secure=bool(ctx.settings.cookie_secure), path="/api/v1/auth/oidc")
    return r


@platform_router.post("/orgs/{org_id}/members/{member_id}/esig-revoke")
def esig_revoke(org_id: str, member_id: str, p: Principal = Depends(require_user),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import esig

    return _ok(esig.revoke(ctx, p, org_id, member_id))


@platform_router.get("/meta/time")
def meta_time(p: Principal = Depends(require_user), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import esig

    return _ok(esig.time_info(ctx))


# ---------------------------------------------------------------- E1-E12 signatures, audit, Part 11

@router.get("/esig/policies", dependencies=P("view"))
def list_policies(a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import esig

    return _ok(esig.list_policies(ctx, a))


@router.put("/esig/policies/{record_type}/{action}", dependencies=P("esig_policy_edit"))
def put_policy(record_type: str, action: str, body: PolicyUpdate, if_match: str | None = _if_match(),
               a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import esig

    return _signed(esig.update_policy(ctx, a, record_type, action, body, if_match))


@router.get("/esig/preview", dependencies=P("view"))
def esig_preview(record_type: str = Query(max_length=32), record_id: str = Query(max_length=64),
                 action: str = Query(max_length=32), decision: str | None = Query(default=None, max_length=16),
                 a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import esig

    return _ok(esig.preview(ctx, a, record_type, record_id, action, decision))


@router.get("/esig/signatures", dependencies=P("audit_view"))
def list_signatures(record_type: str | None = Query(default=None, max_length=32), record_id: str | None = Id(),
                    signer_id: str | None = Id(), from_: date | None = Query(default=None, alias="from"),
                    to: date | None = None, limit: int = Limit(), offset: int = Offset(),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import esig

    return _ok(esig.list_signatures(ctx, record_type, record_id, signer_id, from_, to, limit, offset))


@router.get("/esig/signatures/{signature_id}/verify", dependencies=P("audit_view"))
def verify_signature(signature_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import esig

    return _ok(esig.verify(ctx, signature_id))


@router.get("/audit/record", dependencies=P("audit_view"))
def audit_record(entity_type: str = Query(max_length=32), entity_id: str = Query(max_length=64),
                 limit: int = Query(default=200, ge=1, le=2000), offset: int = Offset(),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import part11

    return _ok(part11.record_audit(ctx, entity_type, entity_id, limit, offset))


@router.get("/part11/records/{record_type}/{record_id}", dependencies=P("audit_view"))
def part11_package(record_type: str, record_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                   ) -> JSONResponse:
    from .services import part11

    return _ok(part11.package(ctx, a, record_type, record_id))


@router.post("/part11/exports", status_code=202, dependencies=P("audit_view"))
def create_export(body: Part11ExportInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                  ) -> JSONResponse:
    from .services import part11

    return _ok(part11.create_export(ctx, a, body), 202)


@router.get("/part11/exports", dependencies=P("audit_view"))
def list_exports(limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import part11

    return _ok(part11.list_exports(ctx, limit, offset))


@router.get("/part11/exports/{export_id}/download", dependencies=P("audit_view"))
def download_export(export_id: str, ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import part11

    data, name = part11.download_export(ctx, export_id)
    return _file(data, name, "application/zip")


@router.get("/plant/part11", dependencies=P("view"))
def get_part11(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import part11

    return _ok(part11.get_mode(ctx))


@router.put("/plant/part11", dependencies=P("owner"))
def put_part11(body: Part11ModeInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import part11

    return _signed(part11.enable(ctx, a, body))


# ---------------------------------------------------------------- Q1-Q2 QA settings

@router.get("/plant/qa-settings", dependencies=P("view"))
def get_qa_settings(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_common

    return _rec(qa_common.get_settings(ctx))


@router.put("/plant/qa-settings", dependencies=P("qa_plan_edit"))
def put_qa_settings(body: QaSettings, if_match: str | None = _if_match(), a: Act = Depends(act),
                    ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_common

    return _rec(qa_common.put_settings(ctx, a, body, if_match))


# ---------------------------------------------------------------- Q3-Q7 sampling schemes

@router.get("/qa/schemes", dependencies=P("view"))
def list_schemes(q: str | None = QText(), status: Literal["draft", "approved", "obsolete"] | None = None,
                 limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _ok(svc.list_schemes(ctx, q, status, limit, offset))


@router.post("/qa/schemes", status_code=201, dependencies=P("qa_plan_edit"))
def create_scheme(body: SchemeInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.create_scheme(ctx, a, body), 201)


@router.get("/qa/schemes/{scheme_id}", dependencies=P("view"))
def get_scheme(scheme_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.get_scheme(ctx, scheme_id))


@router.get("/qa/schemes/{scheme_id}/preview", dependencies=P("view"))
def preview_scheme(scheme_id: str, lot_size: float = Query(gt=0, le=1_000_000_000),
                   level: str = Query(default="II", max_length=8), aql: str = Query(default="0.65", max_length=8),
                   state: Literal["normal", "tightened"] = "normal", ctx: AppContext = Depends(get_ctx)
                   ) -> JSONResponse:
    from .services import qa_inspection as svc

    return _ok(svc.preview_scheme(ctx, scheme_id, lot_size, level, aql, state))


@router.put("/qa/schemes/{scheme_id}", dependencies=P("qa_plan_edit"))
def put_scheme(scheme_id: str, body: SchemeInput, if_match: str | None = _if_match(), a: Act = Depends(act),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.update_scheme(ctx, a, scheme_id, body, if_match))


@router.delete("/qa/schemes/{scheme_id}", status_code=204, dependencies=P("qa_plan_edit"))
def delete_scheme(scheme_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
                  ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import qa_inspection as svc

    svc.delete_scheme(ctx, a, scheme_id, if_match)
    return _no_content()


@router.post("/qa/schemes/{scheme_id}/approve", dependencies=P("qa_plan_edit"))
def approve_scheme(scheme_id: str, body: ApproveInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                   ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _signed(svc.approve_scheme(ctx, a, scheme_id, body, if_match))


# ---------------------------------------------------------------- Q8-Q14 inspection plans

@router.get("/qa/plans", dependencies=P("view"))
def list_plans(q: str | None = QText(), item_id: str | None = Id(),
               scope: Literal["incoming", "in_process", "final"] | None = None,
               status: Literal["draft", "approved", "obsolete"] | None = None, sort: str | None = Sort,
               limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _ok(svc.list_plans(ctx, q, item_id, scope, status, sort, limit, offset))


@router.post("/qa/plans", status_code=201, dependencies=P("qa_plan_edit"))
def create_plan(body: PlanInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.create_plan(ctx, a, body), 201)


@router.get("/qa/plans/{plan_id}", dependencies=P("view"))
def get_plan(plan_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.get_plan(ctx, plan_id))


@router.put("/qa/plans/{plan_id}", dependencies=P("qa_plan_edit"))
def put_plan(plan_id: str, body: PlanInput, if_match: str | None = _if_match(), a: Act = Depends(act),
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.update_plan(ctx, a, plan_id, body, if_match))


@router.delete("/qa/plans/{plan_id}", status_code=204, dependencies=P("qa_plan_edit"))
def delete_plan(plan_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
                ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import qa_inspection as svc

    svc.delete_plan(ctx, a, plan_id, if_match)
    return _no_content()


@router.post("/qa/plans/{plan_id}/copy", status_code=201, dependencies=P("qa_plan_edit"))
def copy_plan(plan_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.copy_plan(ctx, a, plan_id), 201)


@router.post("/qa/plans/{plan_id}/approve", dependencies=P("qa_plan_edit"))
def approve_plan(plan_id: str, body: ApproveInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _signed(svc.approve_plan(ctx, a, plan_id, body, if_match))


@router.post("/qa/plans/{plan_id}/obsolete", dependencies=P("qa_plan_edit"))
def obsolete_plan(plan_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.obsolete_plan(ctx, a, plan_id, if_match))


# ---------------------------------------------------------------- Q15-Q20 inspection lots

@router.get("/qa/inspection-lots", dependencies=P("view"))
def list_lots(q: str | None = QText(), status: str | None = Query(default=None, max_length=64),
              scope: Literal["incoming", "in_process", "final"] | None = None, item_id: str | None = Id(),
              supplier_id: str | None = Id(), overdue: bool | None = None, sort: str | None = Sort,
              limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _ok(svc.list_lots(ctx, q, status, scope, item_id, supplier_id, overdue, sort, limit, offset))


@router.post("/qa/inspection-lots", status_code=201, dependencies=P("qa_inspect"))
def create_lot(body: InspectionLotInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.create_lot(ctx, a, body), 201)


@router.get("/qa/inspection-lots/{lot_id}", dependencies=P("view"))
def get_lot(lot_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.get_lot(ctx, lot_id))


@router.post("/qa/inspection-lots/{lot_id}/results", dependencies=P("qa_inspect"))
def post_results(lot_id: str, body: ResultsBatch, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                 ) -> JSONResponse:
    from .services import qa_inspection as svc

    return _ok(svc.post_results(ctx, a, lot_id, body))


@router.post("/qa/inspection-lots/{lot_id}/decision", dependencies=P("qa_decide"))
def decide_lot(lot_id: str, body: DecisionInput, if_match: str | None = _if_match(), a: Act = Depends(act),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _signed(svc.decide(ctx, a, lot_id, body, if_match))


@router.post("/qa/inspection-lots/{lot_id}/cancel", dependencies=P("qa_decide"))
def cancel_lot(lot_id: str, body: CancelInput, if_match: str | None = _if_match(), a: Act = Depends(act),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_inspection as svc

    return _rec(svc.cancel_lot(ctx, a, lot_id, body, if_match))


# ---------------------------------------------------------------- Q21-Q23 holds

@router.get("/qa/holds", dependencies=P("view"))
def list_holds(open: bool | None = True, source: str | None = Query(default=None, max_length=16),  # noqa: A002
               lot_id: str | None = Id(), item_id: str | None = Id(), limit: int = Limit(), offset: int = Offset(),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_holds as svc

    return _ok(svc.list_holds(ctx, open, source, lot_id, item_id, limit, offset))


@router.post("/qa/holds", status_code=201, dependencies=P("qa_decide"))
def place_hold(body: HoldInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_holds as svc

    return _rec(svc.place_manual(ctx, a, body), 201)


@router.post("/qa/holds/{hold_id}/release", dependencies=P("qa_decide"))
def release_hold(hold_id: str, body: HoldReleaseInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                 ) -> JSONResponse:
    from .services import qa_holds as svc

    return _signed(svc.release(ctx, a, hold_id, body))


# ---------------------------------------------------------------- Q24-Q31 NCR

@router.get("/qa/ncrs", dependencies=P("view"))
def list_ncrs(q: str | None = QText(), status: str | None = Query(default=None, max_length=64),
              item_id: str | None = Id(), place: Literal["stock", "wip"] | None = None, sort: str | None = Sort,
              limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_ncr as svc

    return _ok(svc.list_ncrs(ctx, q, status, item_id, place, sort, limit, offset))


@router.post("/qa/ncrs", status_code=201, dependencies=P("ncr_edit"))
def create_ncr(body: NcrInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_ncr as svc

    return _rec(svc.create_ncr(ctx, a, body), 201)


@router.get("/qa/ncrs/{ncr_id}", dependencies=P("view"))
def get_ncr(ncr_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_ncr as svc

    return _rec(svc.get_ncr(ctx, ncr_id))


@router.put("/qa/ncrs/{ncr_id}", dependencies=P("ncr_edit"))
def put_ncr(ncr_id: str, body: NcrInput, if_match: str | None = _if_match(), a: Act = Depends(act),
            ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_ncr as svc

    return _rec(svc.update_ncr(ctx, a, ncr_id, body, if_match))


@router.post("/qa/ncrs/{ncr_id}/open", dependencies=P("ncr_edit"))
def open_ncr(ncr_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_ncr as svc

    return _rec(svc.open_ncr(ctx, a, ncr_id, if_match))


@router.post("/qa/ncrs/{ncr_id}/propose", dependencies=P("ncr_edit"))
def propose_ncr(ncr_id: str, body: ProposeInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_ncr as svc

    return _rec(svc.propose(ctx, a, ncr_id, body, if_match))


@router.post("/qa/ncrs/{ncr_id}/approve", dependencies=P("ncr_approve"))
def approve_ncr(ncr_id: str, body: ApproveInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_ncr as svc

    return _signed(svc.approve(ctx, a, ncr_id, body, if_match))


@router.post("/qa/ncrs/{ncr_id}/implement", dependencies=P("ncr_edit"))
def implement_ncr(ncr_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_ncr as svc

    return _rec(svc.implement(ctx, a, ncr_id, if_match))


@router.post("/qa/ncrs/{ncr_id}/close", dependencies=P("ncr_approve"))
def close_ncr(ncr_id: str, body: ApproveInput, if_match: str | None = _if_match(), a: Act = Depends(act),
              ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_ncr as svc

    return _signed(svc.close(ctx, a, ncr_id, body, if_match))


@router.post("/qa/ncrs/{ncr_id}/cancel", dependencies=P("ncr_edit"))
def cancel_ncr(ncr_id: str, body: CancelInput, if_match: str | None = _if_match(), a: Act = Depends(act),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_ncr as svc

    return _rec(svc.cancel(ctx, a, ncr_id, body, if_match))


# ---------------------------------------------------------------- Q32-Q39 CAPA

@router.get("/qa/capas", dependencies=P("view"))
def list_capas(q: str | None = QText(), status: str | None = Query(default=None, max_length=64),
               owner_user_id: str | None = Id(), overdue: bool | None = None, sort: str | None = Sort,
               limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_capa as svc

    return _ok(svc.list_capas(ctx, q, status, owner_user_id, overdue, sort, limit, offset))


@router.post("/qa/capas", status_code=201, dependencies=P("capa_edit"))
def create_capa(body: CapaInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_capa as svc

    return _rec(svc.create_capa(ctx, a, body), 201)


@router.get("/qa/capas/{capa_id}", dependencies=P("view"))
def get_capa(capa_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_capa as svc

    return _rec(svc.get_capa(ctx, capa_id))


@router.put("/qa/capas/{capa_id}", dependencies=P("capa_edit"))
def put_capa(capa_id: str, body: CapaInput, if_match: str | None = _if_match(), a: Act = Depends(act),
             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_capa as svc

    return _rec(svc.update_capa(ctx, a, capa_id, body, if_match))


@router.post("/qa/capas/{capa_id}/actions", status_code=201, dependencies=P("capa_edit"))
def add_capa_action(capa_id: str, body: CapaActionInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                    ) -> JSONResponse:
    from .services import qa_capa as svc

    return _rec(svc.add_action(ctx, a, capa_id, body), 201)


@router.put("/qa/capas/{capa_id}/actions/{action_id}", dependencies=P("capa_edit"))
def put_capa_action(capa_id: str, action_id: str, body: CapaActionInput, if_match: str | None = _if_match(),
                    a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_capa as svc

    return _rec(svc.update_action(ctx, a, capa_id, action_id, body, if_match))


@router.delete("/qa/capas/{capa_id}/actions/{action_id}", status_code=204, dependencies=P("capa_edit"))
def delete_capa_action(capa_id: str, action_id: str, if_match: str | None = _if_match(), a: Act = Depends(act),
                       ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import qa_capa as svc

    svc.delete_action(ctx, a, capa_id, action_id, if_match)
    return _no_content()


@router.post("/qa/capas/{capa_id}/advance", dependencies=P("capa_edit"))
def advance_capa(capa_id: str, body: CapaAdvanceInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                 ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_capa as svc

    return _rec(svc.advance(ctx, a, capa_id, body, if_match))


@router.post("/qa/capas/{capa_id}/approve-plan", dependencies=P("capa_approve"))
def approve_capa_plan(capa_id: str, body: ApproveInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                      ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_capa as svc

    return _signed(svc.approve_plan(ctx, a, capa_id, body, if_match))


@router.post("/qa/capas/{capa_id}/verify", dependencies=P("capa_approve"))
def verify_capa(capa_id: str, body: CapaVerifyInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_capa as svc

    return _signed(svc.verify(ctx, a, capa_id, body, if_match))


@router.post("/qa/capas/{capa_id}/close", dependencies=P("capa_approve"))
def close_capa(capa_id: str, body: ApproveInput, if_match: str | None = _if_match(), a: Act = Depends(act),
               ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_capa as svc

    return _signed(svc.close(ctx, a, capa_id, body, if_match))


@router.post("/qa/capas/{capa_id}/cancel", dependencies=P("capa_edit"))
def cancel_capa(capa_id: str, body: CancelInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_capa as svc

    return _rec(svc.cancel(ctx, a, capa_id, body, if_match))


# ---------------------------------------------------------------- Q40-Q44 complaints

@router.get("/qa/complaints", dependencies=P("view"))
def list_complaints(q: str | None = QText(), status: str | None = Query(default=None, max_length=64),
                    item_id: str | None = Id(), sort: str | None = Sort, limit: int = Limit(),
                    offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_complaints as svc

    return _ok(svc.list_complaints(ctx, q, status, item_id, sort, limit, offset))


@router.post("/qa/complaints", status_code=201, dependencies=P("complaint_edit"))
def create_complaint(body: ComplaintInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                     ) -> JSONResponse:
    from .services import qa_complaints as svc

    return _rec(svc.create_complaint(ctx, a, body), 201)


@router.get("/qa/complaints/{complaint_id}", dependencies=P("view"))
def get_complaint(complaint_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_complaints as svc

    return _rec(svc.get_complaint(ctx, complaint_id))


@router.put("/qa/complaints/{complaint_id}", dependencies=P("complaint_edit"))
def put_complaint(complaint_id: str, body: ComplaintInput, if_match: str | None = _if_match(),
                  a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_complaints as svc

    return _rec(svc.update_complaint(ctx, a, complaint_id, body, if_match))


@router.post("/qa/complaints/{complaint_id}/advance", dependencies=P("complaint_edit"))
def advance_complaint(complaint_id: str, body: ComplaintAdvanceInput, if_match: str | None = _if_match(),
                      a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_complaints as svc

    return _rec(svc.advance(ctx, a, complaint_id, body, if_match))


@router.post("/qa/complaints/{complaint_id}/close", dependencies=P("complaint_edit"))
def close_complaint(complaint_id: str, body: ApproveInput, if_match: str | None = _if_match(),
                    a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_complaints as svc

    return _signed(svc.close(ctx, a, complaint_id, body, if_match))


# ---------------------------------------------------------------- Q45-Q52 field actions

@router.get("/qa/field-actions", dependencies=P("view"))
def list_field_actions(q: str | None = QText(), status: str | None = Query(default=None, max_length=64),
                       sort: str | None = Sort, limit: int = Limit(), offset: int = Offset(),
                       ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_field_actions as svc

    return _ok(svc.list_field_actions(ctx, q, status, sort, limit, offset))


@router.post("/qa/field-actions", status_code=201, dependencies=P("field_action_edit"))
def create_field_action(body: FieldActionInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                        ) -> JSONResponse:
    from .services import qa_field_actions as svc

    return _rec(svc.create_field_action(ctx, a, body), 201)


@router.get("/qa/field-actions/{fa_id}", dependencies=P("view"))
def get_field_action(fa_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_field_actions as svc

    return _rec(svc.get_field_action(ctx, fa_id))


@router.put("/qa/field-actions/{fa_id}", dependencies=P("field_action_edit"))
def put_field_action(fa_id: str, body: FieldActionUpdate, if_match: str | None = _if_match(), a: Act = Depends(act),
                     ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_field_actions as svc

    return _rec(svc.update_field_action(ctx, a, fa_id, body, if_match))


@router.post("/qa/field-actions/{fa_id}/approve", dependencies=P("capa_approve"))
def approve_field_action(fa_id: str, body: ApproveInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                         ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_field_actions as svc

    return _signed(svc.approve(ctx, a, fa_id, body, if_match))


@router.post("/qa/field-actions/{fa_id}/complete", dependencies=P("field_action_edit"))
def complete_field_action(fa_id: str, body: FaCompleteInput, if_match: str | None = _if_match(),
                          a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_field_actions as svc

    return _rec(svc.complete(ctx, a, fa_id, body, if_match))


@router.post("/qa/field-actions/{fa_id}/close", dependencies=P("capa_approve"))
def close_field_action(fa_id: str, body: ApproveInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                       ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_field_actions as svc

    return _signed(svc.close(ctx, a, fa_id, body, if_match))


@router.post("/qa/field-actions/{fa_id}/cancel", dependencies=P("field_action_edit"))
def cancel_field_action(fa_id: str, body: CancelInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                        ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_field_actions as svc

    return _rec(svc.cancel(ctx, a, fa_id, body, if_match))


@router.get("/qa/field-actions/{fa_id}/units", dependencies=P("view"))
def list_fa_units(fa_id: str, status: str | None = Query(default=None, max_length=16),
                  customer: str | None = QText(), limit: int = Query(default=200, ge=1, le=5000),
                  offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_field_actions as svc

    return _ok(svc.list_units(ctx, fa_id, status, customer, limit, offset))


@router.post("/qa/field-actions/{fa_id}/units/bulk", dependencies=P("field_action_edit"))
def bulk_fa_units(fa_id: str, body: UnitsBulkInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                  ) -> JSONResponse:
    from .services import qa_field_actions as svc

    return _ok(svc.bulk_units(ctx, a, fa_id, body))


@router.get("/qa/field-actions/{fa_id}/export", dependencies=P("view"))
def export_field_action(fa_id: str, format: Literal["json", "xlsx"] = "json",  # noqa: A002
                        ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import qa_field_actions as svc

    data, name, media = svc.export(ctx, fa_id, format)
    return _file(data, name, media)


# ---------------------------------------------------------------- Q53-Q59 equipment and calibration

@router.get("/qa/equipment", dependencies=P("view"))
def list_equipment(q: str | None = QText(), status: str | None = Query(default=None, max_length=16),
                   equipment_class: str | None = Query(default=None, max_length=32), line_id: str | None = Id(),
                   due_within_days: int | None = Query(default=None, ge=0, le=3650), sort: str | None = Sort,
                   limit: int = Limit(), offset: int = Offset(), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_equipment as svc

    return _ok(svc.list_equipment(ctx, q, status, equipment_class, line_id, due_within_days, sort, limit, offset))


@router.post("/qa/equipment", status_code=201, dependencies=P("equipment_edit"))
def create_equipment(body: EquipmentInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)
                     ) -> JSONResponse:
    from .services import qa_equipment as svc

    return _rec(svc.create_equipment(ctx, a, body), 201)


@router.get("/qa/equipment/{equipment_id}", dependencies=P("view"))
def get_equipment(equipment_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_equipment as svc

    return _rec(svc.get_equipment(ctx, equipment_id))


@router.put("/qa/equipment/{equipment_id}", dependencies=P("equipment_edit"))
def put_equipment(equipment_id: str, body: EquipmentInput, if_match: str | None = _if_match(), a: Act = Depends(act),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_equipment as svc

    return _rec(svc.update_equipment(ctx, a, equipment_id, body, if_match))


@router.post("/qa/equipment/{equipment_id}/status", dependencies=P("equipment_edit"))
def equipment_status(equipment_id: str, body: EquipmentStatusInput, if_match: str | None = _if_match(),
                     a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_equipment as svc

    return _signed(svc.set_status(ctx, a, equipment_id, body, if_match))


@router.get("/qa/equipment/{equipment_id}/impact", dependencies=P("view"))
def equipment_impact(equipment_id: str, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_equipment as svc

    return _ok(svc.impact(ctx, equipment_id))


@router.get("/qa/equipment/{equipment_id}/calibrations", dependencies=P("view"))
def list_calibrations(equipment_id: str, limit: int = Limit(), offset: int = Offset(),
                      ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_equipment as svc

    return _ok(svc.list_calibrations(ctx, equipment_id, limit, offset))


@router.post("/qa/equipment/{equipment_id}/calibrations", status_code=201, dependencies=P("equipment_edit"))
def record_calibration(equipment_id: str, body: CalibrationInput, a: Act = Depends(act),
                       ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_equipment as svc

    return _signed(svc.record_calibration(ctx, a, equipment_id, body), 201)


# ---------------------------------------------------------------- Q60-Q64 attachments and links

@router.post("/qa/attachments", status_code=201, dependencies=P("qa_inspect"))
async def upload_attachment(request: Request, entity_type: str = Query(max_length=32),
                            entity_id: str = Query(max_length=64), filename: str = Query(min_length=1, max_length=200),
                            a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    """Raw body upload (no multipart package, 14): the file bytes with their Content-Type."""
    from fastapi.concurrency import run_in_threadpool

    from .services import qa_common as svc

    data = await request.body()
    rec = await run_in_threadpool(svc.add_attachment, ctx, a, entity_type, entity_id, filename,
                                  request.headers.get("content-type") or "", data)
    return _ok(rec, 201)


@router.get("/qa/attachments/{attachment_id}", dependencies=P("view"))
def download_attachment(attachment_id: str, ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import qa_common as svc

    data, name, media = svc.get_attachment(ctx, attachment_id)
    r = _file(data, name, media)
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r


@router.delete("/qa/attachments/{attachment_id}", status_code=204, dependencies=P("qa_inspect"))
def delete_attachment(attachment_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import qa_common as svc

    svc.delete_attachment(ctx, a, attachment_id)
    return _no_content()


@router.post("/qa/links", status_code=201, dependencies=P("view"))
def create_link(body: LinkInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import qa_common as svc

    return _ok(svc.create_link(ctx, a, body), 201)


@router.delete("/qa/links/{link_id}", status_code=204, dependencies=P("view"))
def delete_link(link_id: str, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import qa_common as svc

    svc.delete_link(ctx, a, link_id)
    return _no_content()


# ---------------------------------------------------------------- floor: issue a component lot (demo finding)

from .services.floor_issue import IssueLotInput  # noqa: E402


@router.post("/floor/issue-lot", status_code=201, dependencies=P("floor_report"))
def floor_issue_lot(body: IssueLotInput, a: Act = Depends(act), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    """Scan lot -> component of the operation -> quantity (default: remaining requirement) -> `wo_issue` posting."""
    from .services import floor_issue

    return _ok(floor_issue.issue_lot(ctx, a.p, body), 201)


__all__ = ["platform_router", "router"]
