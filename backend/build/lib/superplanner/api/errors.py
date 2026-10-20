"""Error envelope and exception handlers (ARCHITECTURE 14 conventions)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    412: "VERSION_MISMATCH",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    428: "PRECONDITION_REQUIRED",
    429: "RATE_LIMITED",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers


def not_found(what: str, ident: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} {ident!r} was not found.", {"id": ident})


def envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _clean_loc(loc: Any) -> list[Any]:
    return [x if isinstance(x, (str, int)) else str(x) for x in (loc or [])]


def validation_details(errors: list[dict[str, Any]], prefix: tuple[Any, ...] = ()) -> dict[str, Any]:
    return {"errors": [{"loc": list(prefix) + _clean_loc(e.get("loc")), "msg": str(e.get("msg", "")),
                        "type": str(e.get("type", ""))} for e in errors]}


def validation_error(errors: list[dict[str, Any]], prefix: tuple[Any, ...] = (),
                     message: str = "The request is not valid.") -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", message, validation_details(errors, prefix))


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(envelope(exc.code, exc.message, exc.details), status_code=exc.status,
                            headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(envelope("VALIDATION_ERROR", "The request is not valid.",
                                     validation_details(list(exc.errors()))), status_code=422)

    @app.exception_handler(ValidationError)
    async def _pydantic_validation(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(envelope("VALIDATION_ERROR", "The request is not valid.",
                                     validation_details(list(exc.errors()))), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 405:  # FastAPI's own 405 keeps its default body (A.14)
            return JSONResponse({"detail": exc.detail}, status_code=405, headers=getattr(exc, "headers", None))
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(envelope(code, message), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(envelope("INTERNAL_ERROR", "An unexpected server error occurred."), status_code=500)
