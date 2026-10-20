"""Principal resolution (PHASE2B 4.7): `require_user` for single_user and accounts mode.

`require_user` is attached at router-include time (`include_router(..., dependencies=[Depends(require_user)])`).
It is **async on purpose**: a ContextVar set in an async dependency is visible to sync endpoints (the threadpool
copies the context), to `StreamingResponse` generators and their `run_in_threadpool` calls; a sync dependency's
ContextVar is not (probe-verified, review R9).

accounts mode: cookie -> session lookup joined with users (threadpool, system scope) -> 401 `AUTH_REQUIRED` if the
cookie is missing or the session is unknown, revoked, expired, idle, or its user is disabled (checked on every
request); unsafe methods then need the Origin check and the session's `X-CSRF-Token` (403 `CSRF_FAILED`);
`last_seen_at` is touched at most every 5 minutes. A bad cookie is cleared on the 401.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool

from ..context import AppContext, get_ctx
from ..db.ownership import LOCAL_USER_ID, bind_owner, system_scope
from ..errors import ApiError
from . import csrf
from . import sessions as sess

log = logging.getLogger(__name__)

AUTH_REQUIRED_MESSAGE = "Please sign in to continue."


@dataclass(frozen=True)
class Principal:
    user_id: str
    session_id: str | None        # None in single_user
    csrf_token: str | None
    is_local: bool


LOCAL_PRINCIPAL = Principal(LOCAL_USER_ID, None, None, True)


def auth_required(settings: object | None = None, clear_cookie: bool = False) -> ApiError:
    headers = None
    if clear_cookie and settings is not None:
        headers = {"set-cookie": sess.clear_cookie_header(settings)}
    return ApiError(401, "AUTH_REQUIRED", AUTH_REQUIRED_MESSAGE, headers=headers)


def resolve_session(ctx: AppContext, token: str | None, *, touch: bool = True) -> sess.SessionView | None:
    """Blocking: the valid session for a cookie token, else None. Runs in system scope (users/sessions are not
    owned tables, but this may run inside a request before any user is bound)."""
    if not token:
        return None
    now = datetime.now(UTC)
    with system_scope():
        with ctx.db.read() as s:
            found = sess.lookup(s, token, ctx.settings, now)
            if found is None:
                return None
            row, user = found
            result = sess.view(row, user)
            stale = touch and sess.needs_touch(row, now)
        if stale:
            with ctx.db.write() as s:
                sess.touch(s, result.session_id, now)
    return result


async def require_user(request: Request, ctx: AppContext = Depends(get_ctx)) -> Principal:
    settings = ctx.settings
    if settings.single_user:
        principal = LOCAL_PRINCIPAL
    else:
        token = sess.read_cookie(request, settings)
        if token is None:
            raise auth_required()
        found = await run_in_threadpool(resolve_session, ctx, token)
        if found is None:
            raise auth_required(settings, clear_cookie=True)
        csrf.check(request, settings, found.csrf_token)
        principal = Principal(found.user_id, found.session_id, found.csrf_token, False)
    request.state.principal = principal
    bind_owner(principal.user_id)   # lives for the request task
    return principal


def principal_user_id(request: Request) -> str | None:
    principal = getattr(request.state, "principal", None)
    return principal.user_id if principal is not None else None
