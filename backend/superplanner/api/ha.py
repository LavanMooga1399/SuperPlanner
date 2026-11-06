"""M6-DESIGN 4.2 application side of high availability.

- `ReadAfterWriteMiddleware` (only with a read replica): every unsafe request answers with cookie `sp_rw` and header
  `SP-Read-After` (epoch seconds) valid 15 s; while a request carries either, replica-routed reads use the primary
  (read-your-writes). API token clients send the header back.
- `classify(exc)`: a database error that means "the primary is gone or demoted" -> reason, else None. The error
  handler (errors.py) answers those with 503 `DB_UNAVAILABLE` + `Retry-After: 5` and invalidates the pool.
"""

from __future__ import annotations

import time
from http.cookies import SimpleCookie
from typing import Any

from .db.session import RW_COOKIE, RW_HEADER, RW_SECONDS, mark_recent_write

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
RETRY_AFTER_SECONDS = 5
SHUTDOWN_STATES = {"57P01": "admin_shutdown", "57P02": "crash_shutdown", "57P03": "cannot_connect_now"}


def classify(exc: BaseException) -> str | None:
    from sqlalchemy.exc import DBAPIError, OperationalError

    if not isinstance(exc, DBAPIError):
        return None
    orig = getattr(exc, "orig", None)
    state = getattr(orig, "sqlstate", None) or getattr(getattr(orig, "diag", None), "sqlstate", None)
    if state == "25006":
        return "read_only"
    if state in SHUTDOWN_STATES:
        return SHUTDOWN_STATES[state]
    if state and state.startswith("08"):
        return "connection"
    if getattr(exc, "connection_invalidated", False):
        return "connection"
    if isinstance(exc, OperationalError) and not state:
        return "connection"
    return None


def _recent(scope: dict[str, Any]) -> bool:
    now = time.time()
    for name, value in scope.get("headers") or []:
        if name == b"cookie":
            try:
                c = SimpleCookie()
                c.load(value.decode("latin-1"))
            except Exception:  # noqa: BLE001 - a bad cookie header is just "no marker"
                continue
            if RW_COOKIE in c:
                return True
        elif name == RW_HEADER.lower().encode():
            try:
                if float(value.decode("latin-1")) > now:
                    return True
            except ValueError:
                continue
    return False


class ReadAfterWriteMiddleware:
    """Pure ASGI (inside RequestContextMiddleware)."""

    def __init__(self, app: Any, cookie_secure: bool = True, path: str = "/") -> None:
        self.app = app
        self.secure = cookie_secure
        self.path = path

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = mark_recent_write(_recent(scope))
        unsafe = scope.get("method", "GET").upper() in UNSAFE

        async def send_wrapper(message: dict[str, Any]) -> None:
            if unsafe and message["type"] == "http.response.start":
                until = int(time.time()) + RW_SECONDS
                cookie = f"{RW_COOKIE}=1; Max-Age={RW_SECONDS}; Path={self.path}; HttpOnly; SameSite=Lax"
                if self.secure:
                    cookie += "; Secure"
                headers = list(message.get("headers", []))
                headers.append((b"set-cookie", cookie.encode("latin-1")))
                headers.append((RW_HEADER.lower().encode(), str(until).encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            from .db.session import _recent_write

            _recent_write.reset(token)
