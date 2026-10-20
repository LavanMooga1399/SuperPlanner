"""Auth answers before body errors, also for unparseable JSON (fix round, PHASE2B 4.5).

FastAPI decodes a JSON body *before* it solves the route's dependencies, so a body like `{not json` on a protected
route used to answer 422 `json_invalid` instead of 401 `AUTH_REQUIRED` / 403 `CSRF_FAILED`. Bodies that parse
but are invalid were already fine (dependencies run before body validation).

`gate_unparsed_body(request)` is called by the `RequestValidationError` handler only when the error is
`json_invalid`. It runs the route's auth gates, in the order FastAPI would (sub-dependencies first), without the
body: `require_user` for data routers, and the auth router's own gates (mode, Origin, session + CSRF). If a gate
raises (`ApiError`), that error is the response; otherwise the original 422 stands. Nothing is bound or written
except what the gates themselves do (`require_user` may touch `last_seen_at`; the owner binding dies with the
request).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from fastapi import Request
from fastapi.concurrency import run_in_threadpool

from ..context import get_ctx
from . import router as auth_router
from .deps import require_user

Gate = Callable[[Request, Any], Any]

# dependency callable -> how to run it with (request, ctx)
_GATES: dict[Any, Gate] = {
    require_user: lambda request, ctx: require_user(request, ctx),
    auth_router._accounts_only: lambda request, ctx: auth_router._accounts_only(ctx),
    auth_router._public_gate: lambda request, ctx: auth_router._public_gate(request, ctx),
    auth_router._optional_session: lambda request, ctx: auth_router._optional_session(request, ctx),
    auth_router._required_session: lambda request, ctx: auth_router._required_session(request, ctx),
}


def _calls(dependant: Any) -> Iterator[Any]:
    """Dependency callables depth-first, sub-dependencies before their dependant (FastAPI's solving order)."""
    for dep in getattr(dependant, "dependencies", None) or []:
        yield from _calls(dep)
        yield dep.call


async def gate_unparsed_body(request: Request) -> None:
    """Raise the auth error the route would have answered with, if any (see module docstring)."""
    route = request.scope.get("route")
    if route is None:
        return
    calls: list[Any] = []
    # Include-level dependencies (`include_router(..., dependencies=[Depends(require_user)])`) are not on the
    # original APIRoute in this FastAPI version, so `install` records the routes of the protected routers.
    if id(route) in getattr(request.app.state, "require_user_routes", ()):
        calls.append(require_user)
    dependant = getattr(route, "dependant", None)
    if dependant is not None:
        calls.extend(_calls(dependant))
    seen: set[Any] = set()
    ctx = None
    for call in calls:
        gate = _GATES.get(call)
        if gate is None or call in seen:
            continue
        seen.add(call)
        if ctx is None:
            ctx = await run_in_threadpool(get_ctx, request)
        if inspect.iscoroutinefunction(call):
            await gate(request, ctx)
        else:
            await run_in_threadpool(gate, request, ctx)


def install(app: Any, protected_routers: Iterable[Any]) -> None:
    """Register the gate for the `RequestValidationError` handler; `protected_routers` are the routers included
    with `Depends(require_user)`."""
    # ids: APIRoute is unhashable; the router modules (and so the route objects) live for the whole process
    app.state.require_user_routes = frozenset(id(r) for router in protected_routers for r in _flat_routes(router))
    app.state.unparsed_body_gate = gate_unparsed_body


def _flat_routes(router: Any) -> Iterator[Any]:
    for r in getattr(router, "routes", []):
        inner = getattr(r, "original_router", None)
        if inner is not None:          # a nested include
            yield from _flat_routes(inner)
        else:
            yield r
