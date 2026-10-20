"""Request ids, log context and the HTTP access line (PHASE2B 5.3).

`RequestContextMiddleware` is a pure ASGI middleware installed **outermost**, so every response - including 413 from
the body limit, CORS preflights, 404 for unknown paths, 422 and 500 - carries `X-Request-ID`:

- the request id is the incoming `X-Request-ID` if it matches `^[A-Za-z0-9._-]{1,64}$`, else `uuid4().hex`;
- it is bound in a ContextVar for the request task (`current_request_id()`), which the job queue stores in
  `jobs.request_id` so the worker can bind it again (API and worker log lines of one run correlate);
- one `http.request` line per request at INFO (`superplanner.http`), with method, route template, status,
  `duration_ms` and `user_id` (SSE streams: logged when the stream ends);
- HTTP metrics are recorded through `obs.http_metrics` (route templates only, never raw paths).

`bind(**fields)` / `bound(**fields)` add context fields (`job_id`, `run_id`, `kind`, `worker_id`, `attempt`, ...)
that the log formatters of `obs.logging` include in every line of the current context.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
import uuid
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_request_id: ContextVar[str | None] = ContextVar("sp_request_id", default=None)
_fields: ContextVar[dict[str, Any]] = ContextVar("sp_log_fields", default={})

access_log = logging.getLogger("superplanner.http")


def current_request_id() -> str | None:
    """The request id of the current HTTP request (or the job's enqueuing request inside a worker)."""
    return _request_id.get()


def set_request_id(value: str | None) -> Any:
    return _request_id.set(value)


def reset_request_id(token: Any) -> None:
    _request_id.reset(token)


def valid_request_id(value: str | None) -> bool:
    return bool(value) and _VALID_ID.match(value or "") is not None


def new_request_id() -> str:
    return uuid.uuid4().hex


def context_fields() -> dict[str, Any]:
    """Context fields of the current context (request id first)."""
    out: dict[str, Any] = {}
    rid = _request_id.get()
    if rid:
        out["request_id"] = rid
    out.update(_fields.get())
    if "user_id" not in out:
        uid = _bound_user()
        if uid:
            out["user_id"] = uid
    return out


def _bound_user() -> str | None:
    try:
        from ..api.db.ownership import current_owner
    except Exception:  # pragma: no cover - import cycle during startup
        return None
    owner = current_owner()
    return owner if isinstance(owner, str) else None


def bind(**fields: Any) -> Any:
    """Add context fields (None values are ignored); returns a token for `unbind`."""
    merged = dict(_fields.get())
    merged.update({k: v for k, v in fields.items() if v is not None})
    return _fields.set(merged)


def unbind(token: Any) -> None:
    with contextlib.suppress(ValueError, LookupError):
        _fields.reset(token)


@contextlib.contextmanager
def bound(request_id: str | None = None, **fields: Any) -> Iterator[None]:
    """Bind a request id and context fields for the duration of the block (worker job execution)."""
    rtok = _request_id.set(request_id) if request_id is not None else None
    ftok = bind(**fields)
    try:
        yield
    finally:
        unbind(ftok)
        if rtok is not None:
            with contextlib.suppress(ValueError, LookupError):
                _request_id.reset(rtok)


# ---------------------------------------------------------------- route templates

def route_template(scope: dict[str, Any]) -> str | None:
    """The matched route's path template incl. the include prefix (e.g. `/api/v1/problems/{problem_id}`).

    FastAPI stores the matched route of an included router with its own (prefix-less) path in `scope["route"]`;
    the prefix is the leading part of the request path with as many segments as are left after removing the
    route's segments (path parameters are single segments in this API)."""
    route = scope.get("route")
    fmt = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not fmt:
        return None
    path = scope.get("path") or ""
    if fmt == path:
        return fmt
    tpl_segments = fmt.strip("/").split("/") if fmt.strip("/") else []
    path_segments = path.strip("/").split("/") if path.strip("/") else []
    n_prefix = len(path_segments) - len(tpl_segments)
    if n_prefix <= 0:
        return fmt
    return "/" + "/".join(path_segments[:n_prefix] + tpl_segments)


# ---------------------------------------------------------------- middleware

class RequestContextMiddleware:
    """Pure ASGI, outermost (see module docstring)."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from . import http_metrics

        incoming = None
        for name, value in scope.get("headers") or []:
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        rid = incoming if valid_request_id(incoming) else new_request_id()
        token = _request_id.set(rid)
        ftoken = _fields.set({})
        t0 = time.perf_counter()
        info: dict[str, Any] = {"status": 500, "sse": False, "started": False, "body403": b""}
        sse_kind: list[str | None] = [None]
        rid_bytes = rid.encode("latin-1")

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                info["started"] = True
                info["status"] = int(message.get("status", 500))
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", rid_bytes))
                message = {**message, "headers": headers}
                for k, v in headers:
                    if k.lower() == b"content-type" and v.startswith(b"text/event-stream"):
                        info["sse"] = True
                        kind = http_metrics.sse_kind(route_template(scope) or scope.get("path", ""))
                        sse_kind[0] = kind
                        http_metrics.sse_started(kind)
                        break
            elif message["type"] == "http.response.body" and info["status"] == 403 and len(info["body403"]) < 512:
                info["body403"] += message.get("body", b"")[:512]
            await send(message)

        failed = False
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Starlette's ServerErrorMiddleware (outside us) runs the 500 handler and re-raises; it only sends its
            # response if none was started. Send the same envelope here so the 500 carries X-Request-ID too. The
            # request id stays bound (not reset) so the handler's "unhandled error" line still has it.
            failed = True
            if not info["started"]:
                await _send_500(send_wrapper)
            info["status"] = 500
            raise
        finally:
            duration = time.perf_counter() - t0
            if sse_kind[0] is not None:
                http_metrics.sse_finished(sse_kind[0])
            route = route_template(scope)
            user_id = _user_of(scope)
            method = scope.get("method", "GET")
            status = int(info["status"])
            try:
                http_metrics.observe_request(method, route, status, duration, sse=bool(info["sse"]))
                http_metrics.observe_auth(method, route, status, bytes(info["body403"]))
            except Exception:  # pragma: no cover - metrics must never break a request
                pass
            extra: dict[str, Any] = {"method": method, "route": route or "unmatched", "status": status,
                                     "duration_ms": round(duration * 1000.0, 1)}
            if user_id:
                extra["user_id"] = user_id
            access_log.info("http.request", extra={"sp": extra})
            if not failed:
                _fields.reset(ftoken)
                _request_id.reset(token)


async def _send_500(send: Any) -> None:
    import json

    body = json.dumps({"error": {"code": "INTERNAL_ERROR", "message": "An unexpected server error occurred.",
                                 "details": {}}}).encode()
    await send({"type": "http.response.start", "status": 500,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _user_of(scope: dict[str, Any]) -> str | None:
    state = scope.get("state")
    principal = state.get("principal") if isinstance(state, dict) else None
    uid = getattr(principal, "user_id", None)
    return uid if isinstance(uid, str) else None
