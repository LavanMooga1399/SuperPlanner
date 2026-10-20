"""Principal resolution (PHASE2B 4.7). Q1: single_user form; the accounts form (sessions, CSRF, Origin) is Q3's.

`require_user` is attached at router-include time (`include_router(..., dependencies=[Depends(require_user)])`).
It is **async on purpose**: a ContextVar set in an async dependency is visible to sync endpoints (the threadpool
copies the context), to `StreamingResponse` generators and their `run_in_threadpool` calls; a sync dependency's
ContextVar is not (probe-verified, review R9).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from ..context import AppContext, get_ctx
from ..db.ownership import LOCAL_USER_ID, bind_owner
from ..errors import ApiError

AUTH_REQUIRED_MESSAGE = "Please sign in to continue."


@dataclass(frozen=True)
class Principal:
    user_id: str
    session_id: str | None        # None in single_user
    csrf_token: str | None
    is_local: bool


LOCAL_PRINCIPAL = Principal(LOCAL_USER_ID, None, None, True)


def auth_required() -> ApiError:
    return ApiError(401, "AUTH_REQUIRED", AUTH_REQUIRED_MESSAGE)


async def require_user(request: Request, ctx: AppContext = Depends(get_ctx)) -> Principal:
    """single_user: every request runs as `usr_local`. accounts: 401 AUTH_REQUIRED until Q3 adds sessions."""
    if ctx.settings.single_user:
        principal = LOCAL_PRINCIPAL
    else:
        raise auth_required()
    request.state.principal = principal
    bind_owner(principal.user_id)   # lives for the request task
    return principal


def principal_user_id(request: Request) -> str | None:
    principal = getattr(request.state, "principal", None)
    return principal.user_id if principal is not None else None
