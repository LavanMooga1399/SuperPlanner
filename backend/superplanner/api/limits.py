"""Request body size guard (ARCHITECTURE 14, Implementation notes).

A pure ASGI middleware: a declared `Content-Length` over the limit is answered with 413 before the body is
read; a body without one (chunked) is counted while it streams and the request fails with 413 as soon as it
passes the limit. Either way the response uses the standard error envelope.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .errors import envelope

DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024


def _too_large_message(limit: int) -> str:
    return f"The request body is too large (max {limit} bytes)."


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

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # FastAPI re-raises HTTPException from body parsing; the app's handler renders the envelope.
                    raise HTTPException(status_code=413, detail=_too_large_message(limit))
            return message

        await self.app(scope, limited_receive, send)
