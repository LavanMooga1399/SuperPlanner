"""Auth endpoints under `/api/v1/auth` (PHASE2B 4.5).

Included without `require_user`: these routes resolve the session themselves. Gates run as dependencies so the
mode (409 `AUTH_DISABLED`), Origin/CSRF (403) and session (401) checks answer before body validation (422).
Rate limits (4.6) are committed in their own transaction before any password is verified. Every argon2 operation
holds a process-wide hash slot (`passwords`); when none frees up in time the endpoint answers 429 `RATE_LIMITED`
with `Retry-After` (fix round: bounded memory and request threads under parallel sign-in floods).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..context import AppContext, get_ctx
from ..db.models import new_id
from ..db.ownership import LOCAL_USER_ID, system_scope
from ..errors import ApiError
from . import csrf, passwords, ratelimit
from . import sessions as sess
from .deps import auth_required, resolve_session
from .models import UserRow
from .schemas import ChangePasswordIn, SessionInfo, SignInIn, SignUpIn

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS_MESSAGE = "The email or password is not correct."


# ---------------------------------------------------------------- errors

def auth_disabled() -> ApiError:
    return ApiError(409, "AUTH_DISABLED", "Sign-in is not used: this server runs in single-user mode.")


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(429, "RATE_LIMITED", "Too many attempts. Try again later.",
                    {"retry_after_seconds": retry_after}, headers={"Retry-After": str(retry_after)})


def hash_busy(exc: passwords.HashBusy) -> ApiError:
    log.warning("auth.hash_busy retry_after=%s", exc.retry_after)
    return rate_limited(exc.retry_after)


def weak_password(reasons: list[str]) -> ApiError:
    return ApiError(422, "WEAK_PASSWORD", "Choose a longer or less common password.", {"reasons": reasons})


# ---------------------------------------------------------------- helpers

def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None and request.client.host else "unknown"


def _rate(ctx: AppContext, buckets: list[tuple[str, int, Any]]) -> None:
    if not ctx.settings.auth_rate_limit_enabled:
        return
    with system_scope(), ctx.db.write() as s:
        allowed, retry = ratelimit.hit_all(s, buckets)
    if not allowed:
        log.info("auth.rate_limited bucket=%s", buckets[0][0].split(":", 2)[0])
        raise rate_limited(retry)


def _anonymous(ctx: AppContext) -> dict[str, Any]:
    return {"auth_mode": "accounts", "authenticated": False, "user": None, "csrf_token": None,
            "expires_at": None, "signup_enabled": bool(ctx.settings.signup_enabled)}


def _info(ctx: AppContext, v: sess.SessionView) -> dict[str, Any]:
    return {"auth_mode": "accounts", "authenticated": True, "user": v.user, "csrf_token": v.csrf_token,
            "expires_at": v.expires_at, "signup_enabled": bool(ctx.settings.signup_enabled)}


def _single_user_info(ctx: AppContext) -> dict[str, Any]:
    with system_scope(), ctx.db.read() as s:
        u = s.get(UserRow, LOCAL_USER_ID)
        created = sess.aware(u.created_at) if u is not None else None
    return {"auth_mode": "single_user", "authenticated": True,
            "user": {"id": LOCAL_USER_ID, "email": None, "display_name": "Local user", "is_local": True,
                     "created_at": created},
            "csrf_token": None, "expires_at": None, "signup_enabled": False}


def _start_session(ctx: AppContext, s: Any, user: UserRow, request: Request,
                   now: datetime) -> tuple[sess.SessionView, str]:
    """Revoke the caller's current session (if its cookie is valid) and create a new one (no fixation)."""
    old = sess.lookup(s, sess.read_cookie(request, ctx.settings), ctx.settings, now)
    if old is not None:
        sess.revoke(s, old[0].id, now)
    row, token = sess.create_session(s, user, ctx.settings, request, now)
    return sess.view(row, user), token


# ---------------------------------------------------------------- gates (dependencies)

async def _accounts_only(ctx: AppContext = Depends(get_ctx)) -> AppContext:
    if ctx.settings.single_user:
        raise auth_disabled()
    return ctx


async def _public_gate(request: Request, ctx: AppContext = Depends(_accounts_only)) -> AppContext:
    """Sign-in / sign-up: no session yet, so only the Origin check applies (plus SameSite=Lax)."""
    csrf.check_origin(request, ctx.settings)
    return ctx


def _optional_session(request: Request, ctx: AppContext = Depends(_accounts_only)) -> sess.SessionView | None:
    v = resolve_session(ctx, sess.read_cookie(request, ctx.settings), touch=False)
    if v is not None:
        csrf.check(request, ctx.settings, v.csrf_token)
    return v


def _required_session(request: Request, ctx: AppContext = Depends(_accounts_only)) -> sess.SessionView:
    token = sess.read_cookie(request, ctx.settings)
    v = resolve_session(ctx, token, touch=False)
    if v is None:
        raise auth_required(ctx.settings, clear_cookie=token is not None)
    csrf.check(request, ctx.settings, v.csrf_token)
    return v


# ---------------------------------------------------------------- endpoints

@router.get("/session", response_model=SessionInfo)
def get_session(request: Request, response: Response, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    if ctx.settings.single_user:
        return _single_user_info(ctx)
    token = sess.read_cookie(request, ctx.settings)
    v = resolve_session(ctx, token)
    if v is None:
        if token is not None:
            sess.clear_session_cookie(response, ctx.settings)
        return _anonymous(ctx)
    return _info(ctx, v)


@router.post("/sign-up", status_code=201, response_model=SessionInfo)
def sign_up(body: SignUpIn, request: Request, response: Response,
            ctx: AppContext = Depends(_public_gate)) -> dict[str, Any]:
    st = ctx.settings
    if not st.signup_enabled:
        raise ApiError(403, "SIGNUP_DISABLED", "Sign-up is disabled on this server. Ask an administrator.")
    _rate(ctx, [(f"signup:ip:{_client_ip(request)}", st.auth_signup_limit_per_ip, ratelimit.SIGNUP_WINDOW)])
    reasons = passwords.policy_reasons(body.password, body.email)
    if reasons:
        raise weak_password(reasons)
    email_taken = ApiError(409, "EMAIL_TAKEN", "An account with this email already exists.")
    with system_scope(), ctx.db.read() as s:   # cheap check first: no hash work for a taken email
        if s.scalar(select(UserRow.id).where(UserRow.email == body.email)) is not None:
            raise email_taken
    try:
        pw_hash = passwords.hash_password(body.password, st.password_hash_profile)
    except passwords.HashBusy as exc:
        raise hash_busy(exc) from None
    now = datetime.now(UTC)
    try:
        with system_scope(), ctx.db.write() as s:
            if s.scalar(select(UserRow.id).where(UserRow.email == body.email)) is not None:
                raise email_taken
            user = UserRow(id=new_id("usr_"), email=body.email, display_name=body.display_name,
                           password_hash=pw_hash, is_local=False, disabled=False, created_at=now, updated_at=now,
                           password_changed_at=now, last_login_at=now)
            s.add(user)
            s.flush()
            v, token = _start_session(ctx, s, user, request, now)
    except IntegrityError:   # concurrent sign-up with the same email
        raise email_taken from None
    log.info("auth.signed_up user_id=%s", v.user_id)
    sess.set_session_cookie(response, st, token, v.expires_at, now)
    return _info(ctx, v)


@router.post("/sign-in", response_model=SessionInfo)
def sign_in(body: SignInIn, request: Request, response: Response,
            ctx: AppContext = Depends(_public_gate)) -> dict[str, Any]:
    st = ctx.settings
    profile = st.password_hash_profile
    _rate(ctx, [(f"signin:ip:{_client_ip(request)}", st.auth_signin_limit_per_ip, ratelimit.SIGNIN_WINDOW),
                (f"signin:email:{ratelimit.email_key(body.email)}", st.auth_signin_limit_per_email,
                 ratelimit.SIGNIN_WINDOW)])
    with system_scope(), ctx.db.read() as s:
        found = s.execute(select(UserRow.id, UserRow.password_hash, UserRow.disabled, UserRow.is_local)
                          .where(UserRow.email == body.email)).first()
    try:
        if found is None or not found.password_hash or found.disabled or found.is_local:
            ok = passwords.verify_dummy(body.password, profile)   # same work as a real verification
        else:
            ok = passwords.verify_password(found.password_hash, body.password, profile)
        if not ok or found is None:
            log.info("auth.sign_in_failed")
            raise ApiError(401, "INVALID_CREDENTIALS", INVALID_CREDENTIALS_MESSAGE)
        new_hash = (passwords.hash_password(body.password, profile)
                    if passwords.needs_rehash(found.password_hash, profile) else None)
    except passwords.HashBusy as exc:
        raise hash_busy(exc) from None
    now = datetime.now(UTC)
    with system_scope(), ctx.db.write() as s:
        u = s.get(UserRow, found.id)
        if u is None or u.disabled or u.password_hash != found.password_hash:   # changed meanwhile
            raise ApiError(401, "INVALID_CREDENTIALS", INVALID_CREDENTIALS_MESSAGE)
        if new_hash is not None:
            u.password_hash = new_hash
            u.updated_at = now
        u.last_login_at = now
        v, token = _start_session(ctx, s, u, request, now)
    log.info("auth.signed_in user_id=%s", v.user_id)
    sess.set_session_cookie(response, st, token, v.expires_at, now)
    return _info(ctx, v)


@router.post("/sign-out", status_code=204)
def sign_out(request: Request, ctx: AppContext = Depends(_accounts_only),
             v: sess.SessionView | None = Depends(_optional_session)) -> Response:
    if v is not None:
        with system_scope(), ctx.db.write() as s:
            sess.revoke(s, v.session_id)
        log.info("auth.signed_out user_id=%s", v.user_id)
    out = Response(status_code=204)
    if sess.read_cookie(request, ctx.settings) is not None:
        sess.clear_session_cookie(out, ctx.settings)
    return out


@router.post("/change-password", response_model=SessionInfo)
def change_password(body: ChangePasswordIn, request: Request, response: Response,
                    ctx: AppContext = Depends(_accounts_only),
                    v: sess.SessionView = Depends(_required_session)) -> dict[str, Any]:
    st = ctx.settings
    profile = st.password_hash_profile
    _rate(ctx, [(f"chpw:user:{v.user_id}", st.auth_change_password_limit_per_user,
                 ratelimit.CHANGE_PASSWORD_WINDOW)])
    with system_scope(), ctx.db.read() as s:
        found = s.execute(select(UserRow.password_hash, UserRow.email).where(UserRow.id == v.user_id)).first()
    if found is None or not found.password_hash:
        raise auth_required()
    try:
        if not passwords.verify_password(found.password_hash, body.current_password, profile):
            raise ApiError(422, "WRONG_PASSWORD", "The current password is not correct.")
        reasons = passwords.policy_reasons(body.new_password, found.email)
        if reasons:
            raise weak_password(reasons)
        new_hash = passwords.hash_password(body.new_password, profile)
    except passwords.HashBusy as exc:
        raise hash_busy(exc) from None
    now = datetime.now(UTC)
    with system_scope(), ctx.db.write() as s:
        u = s.get(UserRow, v.user_id)
        if u is None or u.disabled:
            raise auth_required()
        u.password_hash = new_hash
        u.password_changed_at = now
        u.updated_at = now
        sess.revoke_all(s, u.id, now=now)          # every session, the current one included (rotation)
        row, token = sess.create_session(s, u, st, request, now)
        nv = sess.view(row, u)
    log.info("auth.password_changed user_id=%s", nv.user_id)
    sess.set_session_cookie(response, st, token, nv.expires_at, now)
    return _info(ctx, nv)
