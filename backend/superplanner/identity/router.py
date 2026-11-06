"""`/api/v1/auth` additions (M5-DESIGN 3.1-3.2) and `/api/v1/tokens` (3.3).

`auth_router` resolves sessions itself like the M2 auth router (public config, OIDC redirect / callback, the TOTP
login step with a pending-login token; setup / enable / disable need a session, or - when an organisation forces
2FA - the pending-login token in `X-SP-Pending-Login`). `tokens_router` is a protected router (session or bearer).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from ..api.auth import csrf
from ..api.auth import sessions as sess
from ..api.auth.deps import Principal, auth_required, require_user, resolve_session
from ..api.context import AppContext, get_ctx
from ..api.errors import ApiError
from . import service as ids
from .schemas import TokenIn, TotpCodeIn, TotpLoginIn

auth_router = APIRouter(prefix="/auth", tags=["auth-m5"])
tokens_router = APIRouter(prefix="/tokens", tags=["tokens"])
PENDING_HEADER = "X-SP-Pending-Login"


def _accounts(ctx: AppContext) -> None:
    if ctx.settings.single_user:
        raise ApiError(404, "NOT_FOUND", "Accounts are not enabled.", {})


def _session_user(request: Request, ctx: AppContext, *, allow_pending: bool = False) -> str:
    """The signed-in user (cookie session + CSRF), or with `allow_pending` the user of a valid pending login."""
    _accounts(ctx)
    pending = request.headers.get(PENDING_HEADER)
    if allow_pending and pending:
        csrf.check_origin(request, ctx.settings)
        return ids.pending_user(ctx, pending)
    token = sess.read_cookie(request, ctx.settings)
    v = resolve_session(ctx, token, touch=False)
    if v is None:
        raise auth_required(ctx.settings, clear_cookie=token is not None)
    csrf.check(request, ctx.settings, v.csrf_token)
    return v.user_id


def _session_info(ctx: AppContext, v: sess.SessionView) -> dict[str, Any]:
    return {"auth_mode": "accounts", "authenticated": True, "user": v.user, "csrf_token": v.csrf_token,
            "expires_at": v.expires_at, "signup_enabled": bool(ctx.settings.signup_enabled)}


@auth_router.get("/config")
def auth_config(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return ids.config(ctx)


@auth_router.get("/oidc/login")
def oidc_login(next: str | None = Query(default=None, max_length=500),  # noqa: A002
               ctx: AppContext = Depends(get_ctx)) -> Response:
    _accounts(ctx)
    url, binding = ids.oidc_login(ctx, next)
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(ids.OIDC_COOKIE, binding, max_age=ids.STATE_MINUTES * 60, httponly=True, samesite="lax",
                    secure=bool(ctx.settings.cookie_secure), path="/api/v1/auth/oidc")
    return resp


@auth_router.get("/oidc/callback")
def oidc_callback(request: Request, code: str | None = Query(default=None, max_length=4000),
                  state: str | None = Query(default=None, max_length=200),
                  error: str | None = Query(default=None, max_length=200),
                  ctx: AppContext = Depends(get_ctx)) -> Response:
    _accounts(ctx)
    v, token, nxt = ids.oidc_callback(ctx, request, code, state, error)
    resp = RedirectResponse(nxt, status_code=302)
    sess.set_session_cookie(resp, ctx.settings, token, v.expires_at)
    resp.delete_cookie(ids.OIDC_COOKIE, path="/api/v1/auth/oidc")
    return resp


@auth_router.get("/totp")
def totp_status(request: Request, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return ids.totp_status(ctx, _session_user(request, ctx))


@auth_router.post("/totp/setup")
def totp_setup(request: Request, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return ids.totp_setup(ctx, _session_user(request, ctx, allow_pending=True))


@auth_router.post("/totp/enable")
def totp_enable(body: TotpCodeIn, request: Request, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return ids.totp_enable(ctx, _session_user(request, ctx, allow_pending=True), body.code)


@auth_router.post("/totp/disable", status_code=204)
def totp_disable(body: TotpCodeIn, request: Request, ctx: AppContext = Depends(get_ctx)) -> Response:
    ids.totp_disable(ctx, _session_user(request, ctx), body.code)
    return Response(status_code=204)


@auth_router.post("/totp/recovery-codes")
def totp_recovery(body: TotpCodeIn, request: Request, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return ids.totp_new_recovery(ctx, _session_user(request, ctx), body.code)


@auth_router.post("/login/totp")
def login_totp(body: TotpLoginIn, request: Request, response: Response,
               ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    _accounts(ctx)
    csrf.check_origin(request, ctx.settings)
    v, token = ids.login_totp(ctx, request, body.pending_token, body.code, body.recovery_code)
    sess.set_session_cookie(response, ctx.settings, token, v.expires_at)
    return _session_info(ctx, v)


# ---------------------------------------------------------------- tokens (protected)

def _person(p: Principal) -> str:
    if p.token_id is not None:
        raise ApiError(403, "TOKEN_SCOPE", "API tokens cannot manage API tokens.", {"permission": "session"})
    return p.user_id


@tokens_router.get("")
def list_tokens(p: Principal = Depends(require_user), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return ids.list_tokens(ctx, _person(p))


@tokens_router.post("", status_code=201)
def create_token(body: TokenIn, p: Principal = Depends(require_user), ctx: AppContext = Depends(get_ctx)
                 ) -> JSONResponse:
    from ..api.mfg.services.common import jsonable

    _accounts(ctx)
    return JSONResponse(jsonable(ids.create_token(ctx, _person(p), body)), status_code=201)


@tokens_router.delete("/{token_id}", status_code=204)
def delete_token(token_id: str, p: Principal = Depends(require_user), ctx: AppContext = Depends(get_ctx)) -> Response:
    ids.revoke_token(ctx, _person(p), token_id)
    return Response(status_code=204)
