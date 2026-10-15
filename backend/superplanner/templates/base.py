"""Domain adapter contract (ARCHITECTURE section 12)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from superplanner.engine.model import Problem, Terminology


class TemplateParameter(BaseModel):
    name: str
    label: str
    type: Literal["int", "date", "string", "string_list"]
    default: Any
    min: int | None = None
    max: int | None = None
    help: str = ""


class DomainTemplate(Protocol):
    id: str
    name: str
    description: str
    domain: str
    terminology: Terminology
    parameters: list[TemplateParameter]

    def build(self, *, name: str, start_date: date, utc_offset: str, params: dict[str, Any]) -> Problem: ...


_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def parse_offset(utc_offset: str) -> timezone:
    m = _OFFSET_RE.match(utc_offset or "+00:00")
    if not m:
        raise ValueError(f"invalid utc_offset {utc_offset!r}; expected e.g. '+05:30'")
    sign = 1 if m.group(1) == "+" else -1
    hours, minutes = int(m.group(2)), int(m.group(3))
    if hours > 14 or minutes > 59:
        raise ValueError(f"invalid utc_offset {utc_offset!r}")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def at(start_date: date, tz: timezone, days: int = 0, hhmm: str = "00:00") -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    d = start_date + timedelta(days=days)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=tz)


def resolve_params(parameters: list[TemplateParameter], params: dict[str, Any] | None) -> dict[str, Any]:
    """Defaults for missing params; ValueError for unknown names or invalid values."""
    params = dict(params or {})
    known = {p.name: p for p in parameters}
    unknown = sorted(set(params) - set(known))
    if unknown:
        raise ValueError(f"unknown template parameter(s): {', '.join(unknown)}")
    out: dict[str, Any] = {}
    for p in parameters:
        value = params.get(p.name, p.default)
        if p.type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"parameter {p.name!r} must be an integer")
            if p.min is not None and value < p.min or p.max is not None and value > p.max:
                raise ValueError(f"parameter {p.name!r} must be between {p.min} and {p.max}")
        elif p.type == "string_list":
            if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
                raise ValueError(f"parameter {p.name!r} must be a list of non-empty strings")
            if p.min is not None and len(value) < p.min or p.max is not None and len(value) > p.max:
                raise ValueError(f"parameter {p.name!r} must have between {p.min} and {p.max} entries")
            value = [v.strip() for v in value]
        elif p.type == "string":
            if not isinstance(value, str):
                raise ValueError(f"parameter {p.name!r} must be a string")
        elif p.type == "date":
            if isinstance(value, str):
                value = date.fromisoformat(value)
            if not isinstance(value, date):
                raise ValueError(f"parameter {p.name!r} must be a date")
        out[p.name] = value
    return out


def slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    return (s or "X")[:24]
