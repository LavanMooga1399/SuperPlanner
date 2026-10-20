"""Logging setup for API, worker, migrate and manage (PHASE2B 5.3). No dependency: the JSON formatter is hand-rolled.

`configure_logging(settings, service)`:
- `LOG_FORMAT=json` (production default): one JSON object per line on stderr with `ts`, `level`, `logger`,
  `service`, `msg`, the context fields (`request_id`, `user_id`, `job_id`, `run_id`, `kind`, `worker_id`,
  `attempt`, from `obs.request_context`), structured fields passed as `extra={"sp": {...}}`, and `exc` (traceback).
  Uvicorn's own loggers are routed through the same handler, so *every* line is JSON.
- `LOG_FORMAT=text` (development default): today's line format `<asctime> <LEVEL> <logger>: <msg>` plus the
  structured fields as ` key=value` and ` rid=<request id>`.

It only installs a handler if the root logger has none yet (or `force=True`), so pytest's log capture and an
embedding application's configuration are left alone. Calling it again with the same handler is a no-op.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from .request_context import context_fields

SERVICES = ("api", "worker", "migrate", "manage")
TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_MARK = "_superplanner_handler"
# Standard LogRecord attributes; anything else set via `extra=` that is not ours is ignored (no accidental leaks).
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _ts(record: logging.LogRecord) -> str:
    dt = datetime.fromtimestamp(record.created, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return str(value)
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def record_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Context fields + structured `extra={"sp": {...}}` fields of a record (structured fields win)."""
    fields = dict(getattr(record, "sp_context", None) or context_fields())
    extra = getattr(record, "sp", None)
    if isinstance(extra, dict):
        fields.update(extra)
    return fields


class ContextFilter(logging.Filter):
    """Captures the context fields at emit time in the emitting thread (handlers may format later)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "sp_context"):
            record.sp_context = context_fields()
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {"ts": _ts(record), "level": record.levelname, "logger": record.name,
                               "service": self.service, "msg": record.getMessage()}
        for k, v in record_fields(record).items():
            if k not in out:
                out[k] = _jsonable(v)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            out["exc"] = record.exc_text
        if record.stack_info:
            out["stack"] = self.formatStack(record.stack_info)
        return json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(TEXT_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = record_fields(record)
        rid = fields.pop("request_id", None)
        extra = getattr(record, "sp", None)
        # Only the structured fields of this record are appended (context fields like job_id would repeat what
        # the worker's messages already say); the request id is always appended when known.
        parts = [f"{k}={v}" for k, v in (extra.items() if isinstance(extra, dict) else [])]
        if rid:
            parts.append(f"rid={rid}")
        if not parts:
            return line
        head, sep, tail = line.partition("\n")   # keep tracebacks below the first line
        return head + " " + " ".join(parts) + (sep + tail if sep else "")


def make_handler(fmt: str, service: str, stream: Any = None) -> logging.Handler:
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter(service) if fmt == "json" else TextFormatter())
    handler.addFilter(ContextFilter())
    setattr(handler, _MARK, (fmt, service))
    return handler


def is_configured() -> bool:
    return any(getattr(h, _MARK, None) for h in logging.getLogger().handlers)


def configure_logging(settings: Any, service: str, *, force: bool = False, stream: Any = None) -> bool:
    """Install the SuperPlanner handler on the root logger. Returns True if it did."""
    if service not in SERVICES:
        raise ValueError(f"unknown service {service!r}")
    fmt = (getattr(settings, "log_format", None) or "text").lower()
    level = (getattr(settings, "log_level", None) or "INFO").upper()
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, _MARK, None)]
    if ours and not force:
        if getattr(ours[0], _MARK) == (fmt, service):
            return False
    elif root.handlers and not force:
        return False   # somebody else (pytest capture, an embedding app) configured logging
    for h in list(root.handlers):
        if force or getattr(h, _MARK, None):
            root.removeHandler(h)
    root.addHandler(make_handler(fmt, service, stream))
    root.setLevel(level)
    if fmt == "json":
        # uvicorn installs its own text handlers (propagate=False); route its lines through ours.
        for name in _UVICORN_LOGGERS:
            lg = logging.getLogger(name)
            for h in list(lg.handlers):
                lg.removeHandler(h)
            lg.propagate = True
    return True
