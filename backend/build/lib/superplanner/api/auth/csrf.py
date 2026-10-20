"""CSRF protection (PHASE2B 4.4): synchronizer token per session plus an Origin check on unsafe methods.

- Every POST/PUT/PATCH/DELETE on a session-protected route must carry `X-CSRF-Token` equal to the session's
  token (`hmac.compare_digest`); missing or wrong -> 403 `CSRF_FAILED`.
- If an unsafe request carries an `Origin` header it must be one of `CORS_ORIGINS` or the origin of
  `PUBLIC_BASE_URL`; anything else (including the opaque `null` origin) -> 403 `CSRF_FAILED`. Requests without
  an `Origin` (non-browser clients) pass this check; browsers always send it on cross-site POSTs.
- Sign-in and sign-up have no session yet: Origin check only (plus SameSite=Lax on the cookie).
"""

from __future__ import annotations

import hmac
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request

from ..errors import ApiError

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_HEADER = "X-CSRF-Token"
CSRF_FAILED_MESSAGE = "Your session could not be verified. Reload the page and try again."


def csrf_failed() -> ApiError:
    return ApiError(403, "CSRF_FAILED", CSRF_FAILED_MESSAGE)


def is_unsafe(method: str) -> bool:
    return method.upper() not in SAFE_METHODS


def origin_of(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def allowed_origins(settings: Any) -> frozenset[str]:
    out = {o for o in (origin_of(x) for x in (settings.cors_origins or [])) if o}
    base = origin_of(settings.public_base_url)
    if base:
        out.add(base)
    return frozenset(out)


def check_origin(request: Request, settings: Any) -> None:
    """Unsafe methods only. Absent Origin passes; a present Origin must be allowed."""
    if not is_unsafe(request.method):
        return
    origin = request.headers.get("origin")
    if origin is None:
        return
    normalized = origin_of(origin)
    if normalized is None or normalized not in allowed_origins(settings):
        raise csrf_failed()


def check_token(request: Request, expected: str | None) -> None:
    """Unsafe methods only: `X-CSRF-Token` must equal the session's token."""
    if not is_unsafe(request.method):
        return
    sent = request.headers.get(CSRF_HEADER)
    if not sent or not expected or not hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8")):
        raise csrf_failed()


def check(request: Request, settings: Any, expected: str | None) -> None:
    check_origin(request, settings)
    check_token(request, expected)
