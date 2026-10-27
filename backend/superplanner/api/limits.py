"""Request body guards (ARCHITECTURE 14, Implementation notes; PHASE2B 3.5.7).

A pure ASGI middleware: a declared `Content-Length` over the limit is answered with 413 before the body is
read; a body without one (chunked) is counted while it streams and the request fails with 413 as soon as it
passes the limit. Either way the response uses the standard error envelope.

JSON bodies containing the escape `\u0000` (U+0000) anywhere are rejected with 422 `VALIDATION_ERROR` on every
database: PostgreSQL `TEXT`/`JSONB` cannot store NUL, so the request fails early with a clear error.
The scan is streaming and escape-aware (`\\u0000`, an escaped backslash followed by "u0000", is ordinary text).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .errors import envelope

DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024


NUL_MESSAGE = "The request must not contain the NUL character (\\u0000)."
_NUL_ESCAPE = b"u0000"


def _too_large_message(limit: int) -> str:
    return f"The request body is too large (max {limit} bytes)."


def _is_json(scope: dict[str, Any]) -> bool:
    for name, value in scope.get("headers", []):
        if name == b"content-type":
            return b"json" in value.lower()
    return False


class NulScanner:
    """Finds a JSON `\u0000` escape across chunk boundaries (keeps the tail: last 5 bytes + preceding backslashes)."""

    def __init__(self) -> None:
        self.tail = b""

    def feed(self, chunk: bytes) -> bool:
        if not chunk:
            return False
        data = self.tail + chunk
        if b"\x00" in chunk:
            return True
        start = 0
        while True:
            i = data.find(_NUL_ESCAPE, start)
            if i < 0:
                break
            j = i
            while j > 0 and data[j - 1] == 0x5C:   # backslash
                j -= 1
            if (i - j) % 2 == 1:
                return True
            start = i + 1
        k = max(0, len(data) - len(_NUL_ESCAPE))
        while k > 0 and data[k - 1] == 0x5C:
            k -= 1
        self.tail = data[k:]
        return False


class BodySizeLimitMiddleware:
    def __init__(self, app: Any, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.max_body_bytes
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                if declared > limit:
                    response = JSONResponse(envelope("PAYLOAD_TOO_LARGE", _too_large_message(limit),
                                                     {"max_bytes": limit}), status_code=413)
                    await response(scope, receive, send)
                    return
                break

        received = 0
        scanner = NulScanner() if _is_json(scope) else None

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                received += len(body)
                if received > limit:
                    # FastAPI re-raises HTTPException from body parsing; the app's handler renders the envelope.
                    raise HTTPException(status_code=413, detail=_too_large_message(limit))
                if scanner is not None and scanner.feed(body):
                    raise HTTPException(status_code=422, detail=NUL_MESSAGE)
            return message

        await self.app(scope, limited_receive, send)
