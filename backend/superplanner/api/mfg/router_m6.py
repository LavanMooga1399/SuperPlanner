"""M6 `/api/v1/mfg` endpoints (M6-DESIGN 5: A1-A10, M4-M5, D1-D2, D7; one permission each) and the platform routes
(`/push`, `/digests`, `/orgs/{org}/dashboard`) in `platform_router`.

Services: `assistant/service.py` (status, conversations, turns, drafts), `assistant/quick.py`, `services/dashboard.py`,
`services/approvals.py`, `services/downtime.py` (ack), `push/service.py`, `notify/digests.py`.
Replica-routed reads (4.2): dashboards, exports and quick explanations run through `replica_call()` (replica when fresh,
retried once on the primary after a replica fault)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from ...assistant.model import AssistantPlantSettings, ConversationInput, DraftApplied, TurnInput
from ...mfg.model_m6 import DigestInput, DowntimeAck, ThresholdsInput
from ...push.model import PushSubscriptionInput
from ..context import AppContext, get_ctx
from ..db.session import replica_call
from .access import MfgPrincipal, mfg_principal
from .router_m2 import P, Id, Limit, Offset, _file, _idem, _idem_key, _ok

router = APIRouter(prefix="/mfg", tags=["mfg-m6"])


async def _session_only(p: MfgPrincipal = Depends(mfg_principal)) -> None:
    """M6 review M1: assistant routes refuse API token principals (403 TOKEN_SCOPE)."""
    if p.scopes is not None:
        from ..errors import ApiError

        raise ApiError(403, "TOKEN_SCOPE", "API tokens cannot use the assistant.", {"permission": "assistant_use"})


def PA(perm: str) -> list:
    return P(perm) + [Depends(_session_only)]
platform_router = APIRouter(tags=["m6"])


# ---------------------------------------------------------------- A1-A10 assistant (1)

@router.get("/assistant/status", dependencies=PA("assistant_use"))
def assistant_status(request: Request, p: MfgPrincipal = Depends(mfg_principal),
                     ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...assistant import service as svc

    return _ok(svc.status(ctx, request.app, p))


@router.get("/assistant/quick", dependencies=PA("view"))
def assistant_quick(kind: Literal["why_late", "limits", "changes"], type: str | None = Query(  # noqa: A002
        default=None, max_length=32), id: str | None = Id(), p: MfgPrincipal = Depends(mfg_principal),  # noqa: A002
        ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...assistant import quick

    return _ok(replica_call(lambda: quick.explain(ctx, p, kind, type, id), ctx))


@router.get("/assistant/conversations", dependencies=PA("assistant_use"))
def list_conversations(limit: int = Limit(), offset: int = Offset(), p: MfgPrincipal = Depends(mfg_principal),
                       ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...assistant import service as svc

    return _ok(svc.list_conversations(ctx, p, limit, offset))


@router.post("/assistant/conversations", status_code=201, dependencies=PA("assistant_use"))
def create_conversation(request: Request, body: ConversationInput | None = None,
                        p: MfgPrincipal = Depends(mfg_principal), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...assistant import service as svc

    return _ok(svc.create_conversation(ctx, request.app, p, body or ConversationInput()), 201)


@router.get("/assistant/conversations/{conversation_id}", dependencies=PA("assistant_use"))
def get_conversation(conversation_id: str, p: MfgPrincipal = Depends(mfg_principal),
                     ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...assistant import service as svc

    return _ok(svc.get_conversation(ctx, p, conversation_id))


@router.delete("/assistant/conversations/{conversation_id}", status_code=204, dependencies=PA("assistant_use"))
def delete_conversation(conversation_id: str, p: MfgPrincipal = Depends(mfg_principal),
                        ctx: AppContext = Depends(get_ctx)) -> Response:
    from ...assistant import service as svc

    svc.delete_conversation(ctx, p, conversation_id)
    return Response(status_code=204)


@router.post("/assistant/conversations/{conversation_id}/turns", status_code=202, dependencies=PA("assistant_use"))
def create_turn(conversation_id: str, body: TurnInput, request: Request, p: MfgPrincipal = Depends(mfg_principal),
                ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...assistant import service as svc

    out = svc.start_turn(ctx, request.app, p, conversation_id, body)
    return _ok(out, 202, headers={"Location": f"/api/v1/mfg/assistant/turns/{out['turn_id']}"})


@router.get("/assistant/turns/{turn_id}", dependencies=PA("assistant_use"))
def get_turn(turn_id: str, p: MfgPrincipal = Depends(mfg_principal), ctx: AppContext = Depends(get_ctx)
             ) -> JSONResponse:
    from ...assistant import service as svc

    return _ok(svc.get_turn(ctx, p, turn_id))


@router.post("/assistant/turns/{turn_id}/cancel", dependencies=PA("assistant_use"))
def cancel_turn(turn_id: str, p: MfgPrincipal = Depends(mfg_principal), ctx: AppContext = Depends(get_ctx)
                ) -> JSONResponse:
    from ...assistant import service as svc

    return _ok(svc.cancel_turn(ctx, p, turn_id))


@router.post("/assistant/drafts/{draft_id}/applied", dependencies=PA("assistant_use"))
def draft_applied(draft_id: str, body: DraftApplied, p: MfgPrincipal = Depends(mfg_principal),
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...assistant import service as svc

    return _ok(svc.draft_applied(ctx, p, draft_id, body))


@router.put("/plant/assistant", dependencies=PA("owner"))
def put_assistant_settings(body: AssistantPlantSettings, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...assistant import service as svc

    return _ok(svc.put_plant_settings(ctx, body))


# ---------------------------------------------------------------- M4-M5 mobile

@router.post("/downtime/{downtime_id}/acknowledge", dependencies=P("floor_view"))
def acknowledge_downtime(downtime_id: str, body: DowntimeAck | None = None, idem_key: str | None = _idem_key(),
                         ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import downtime

    rec = downtime.acknowledge(ctx, downtime_id, _idem(idem_key) or (body.client_id if body else None))
    return _ok(rec, etag=rec["row_version"])


@router.get("/approvals", dependencies=P("view"))
def approvals(p: MfgPrincipal = Depends(mfg_principal), ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import approvals as svc

    return _ok(svc.approvals(ctx, p))


# ---------------------------------------------------------------- D1-D2, D7 dashboards (3)

@router.get("/dashboard", dependencies=P("view"))
def dashboard(period: Literal["4w", "13w", "52w"] = "13w", ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import dashboard as svc

    return _ok(replica_call(lambda: svc.plant_dashboard(ctx, period), ctx))


@router.get("/dashboard/export", dependencies=P("view"))
def dashboard_export(period: Literal["4w", "13w", "52w"] = "13w",
                     format: Literal["xlsx", "csv"] = "xlsx",  # noqa: A002
                     ctx: AppContext = Depends(get_ctx)) -> Response:
    from .services import dashboard as svc

    data, name, media = replica_call(lambda: svc.export(ctx, period, format), ctx)
    return _file(data, name, media)


@router.put("/plant/dashboard-thresholds", dependencies=P("owner"))
def put_thresholds(body: ThresholdsInput, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import dashboard as svc

    return _ok(svc.put_thresholds(ctx, body))


# ---------------------------------------------------------------- platform: push (M1-M3), digests (D4-D6), org (D3)

@platform_router.get("/push/vapid-public-key")
def vapid_public_key(ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...push import service as svc

    return _ok(svc.vapid_public_key(ctx))


@platform_router.get("/push/subscriptions")
def list_push_subscriptions(request: Request, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...push import service as svc

    return _ok(svc.list_subscriptions(ctx, _user(request)))


@platform_router.post("/push/subscriptions", status_code=201)
def create_push_subscription(body: PushSubscriptionInput, request: Request,
                             ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...push import service as svc

    return _ok(svc.subscribe(ctx, _user(request), body, request.headers.get("user-agent", "")), 201)


@platform_router.delete("/push/subscriptions/{subscription_id}", status_code=204)
def delete_push_subscription(subscription_id: str, request: Request, ctx: AppContext = Depends(get_ctx)) -> Response:
    from ...push import service as svc

    svc.unsubscribe(ctx, _user(request), subscription_id)
    return Response(status_code=204)


@platform_router.get("/digests")
def list_digests(request: Request, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...notify import digests as svc

    return _ok(svc.list_digests(ctx, _user(request)))


@platform_router.post("/digests", status_code=201)
def create_digest(body: DigestInput, request: Request, ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from ...notify import digests as svc

    return _ok(svc.create_digest(ctx, _user(request), body), 201)


@platform_router.delete("/digests/{digest_id}", status_code=204)
def delete_digest(digest_id: str, request: Request, ctx: AppContext = Depends(get_ctx)) -> Response:
    from ...notify import digests as svc

    svc.delete_digest(ctx, _user(request), digest_id)
    return Response(status_code=204)


@platform_router.get("/orgs/{org_id}/dashboard")
def org_dashboard(org_id: str, request: Request, period: Literal["4w", "13w", "52w"] = "13w",
                  ctx: AppContext = Depends(get_ctx)) -> JSONResponse:
    from .services import dashboard as svc

    uid = _user(request)
    return _ok(replica_call(lambda: svc.org_dashboard(ctx, uid, org_id, period), ctx))


def _user(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if principal is None:  # pragma: no cover - require_user runs first
        from ..errors import ApiError

        raise ApiError(401, "AUTH_REQUIRED", "Please sign in to continue.")
    if getattr(principal, "scopes", None) is not None:      # M5 3.3: these routes are for people's sessions
        from ..errors import ApiError

        raise ApiError(403, "TOKEN_SCOPE", "API tokens cannot use this endpoint.", {})
    return principal.user_id


__all__ = ["platform_router", "router"]
