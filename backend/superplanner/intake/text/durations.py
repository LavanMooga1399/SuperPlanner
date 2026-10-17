"""Durations and duration ranges (PHASE2 2.7.3). Linear-time patterns, applied in priority order."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .numbers import NUM, parse_number

UNIT_WORDS = {
    "minutes": "minutes", "minute": "minutes", "mins": "minutes", "min": "minutes", "m": "minutes",
    "hours": "hours", "hour": "hours", "hrs": "hours", "hr": "hours", "h": "hours",
    "days": "days", "day": "days", "d": "days",
    "weeks": "weeks", "week": "weeks", "wks": "weeks", "wk": "weeks", "w": "weeks",
    "months": "months", "month": "months",
}
_UNIT_ALT = "|".join(sorted((u for u in UNIT_WORDS if u != "m"), key=len, reverse=True))
UNIT = rf"(?P<unit>{_UNIT_ALT})\b"
_N = NUM

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("labelled", re.compile(
        rf"optimistic(?:ally)?\s*:?\s*(?P<a>{_N})\s*(?:{_UNIT_ALT})?\s*,?\s*(?:most\s+)?likely\s*:?\s*(?P<b>{_N})\s*"
        rf"(?:{_UNIT_ALT})?\s*,?\s*(?:and\s+)?pessimistic(?:ally)?\s*:?\s*(?P<c>{_N})\s*{UNIT}", re.I)),
    ("bestworst", re.compile(
        rf"best\s*(?:case)?\s*:?\s*(?P<a>{_N})\s*,?\s*worst\s*(?:case)?\s*:?\s*(?P<c>{_N})\s*{UNIT}\s*,?\s*"
        rf"(?:but\s+)?(?:probably|likely|most likely|expected)\s*:?\s*(?P<b>{_N})", re.I)),
    ("slash", re.compile(rf"(?P<a>{_N})\s*/\s*(?P<b>{_N})\s*/\s*(?P<c>{_N})\s*{UNIT}", re.I)),
    ("paren", re.compile(rf"(?P<b>{_N})\s*{UNIT}\s*\(\s*(?P<a>{_N})\s*(?:-|to)\s*(?P<c>{_N})\s*\)", re.I)),
    ("between", re.compile(rf"between\s+(?P<a>{_N})\s*(?:and|-)\s*(?P<c>{_N})\s*{UNIT}", re.I)),
    ("range", re.compile(rf"(?P<a>{_N})\s*(?:-|to)\s*(?P<c>{_N})\s*{UNIT}", re.I)),
    ("half_day", re.compile(r"\bhalf\s+a\s+day\b", re.I)),
    ("half_hour", re.compile(r"\bhalf\s+an\s+hour\b", re.I)),
    ("hour_half", re.compile(r"\ban?\s+hour\s+and\s+a\s+half\b", re.I)),
    ("single", re.compile(rf"(?P<b>{_N})\s*{UNIT}", re.I)),
]


@dataclass
class DurMatch:
    start: int
    end: int
    optimistic: float
    likely: float
    pessimistic: float
    unit: str
    confidence: float
    note: str | None = None
    ranged: bool = False


def _num(m: re.Match[str], g: str) -> tuple[float, float] | None:
    v = m.group(g)
    return parse_number(v) if v else None


def _make(kind: str, m: re.Match[str]) -> DurMatch | None:
    if kind == "half_day":
        return DurMatch(m.start(), m.end(), 0.5, 0.5, 0.5, "days", 0.95)
    if kind == "half_hour":
        return DurMatch(m.start(), m.end(), 30, 30, 30, "minutes", 0.95)
    if kind == "hour_half":
        return DurMatch(m.start(), m.end(), 1.5, 1.5, 1.5, "hours", 0.95)
    unit = UNIT_WORDS[m.group("unit").lower()]
    conf = 0.95
    if kind == "single":
        b = _num(m, "b")
        if b is None:
            return None
        o = l = p = b[0]
        conf = min(conf, b[1])
    elif kind in ("range", "between"):
        a, c = _num(m, "a"), _num(m, "c")
        if a is None or c is None:
            return None
        o, p = sorted((a[0], c[0]))
        l = (o + p) / 2
        conf = min(conf, a[1], c[1])
    else:
        a, b, c = _num(m, "a"), _num(m, "b"), _num(m, "c")
        if a is None or b is None or c is None:
            return None
        o, l, p = sorted((a[0], b[0], c[0]))
        conf = min(conf, a[1], b[1], c[1])
    if o <= 0:
        return None
    note = None
    if unit == "months":
        o, l, p = (round(v * 4.33, 2) for v in (o, l, p))
        unit, conf, note = "weeks", min(conf, 0.7), "MONTHS_AS_WEEKS"
    return DurMatch(m.start(), m.end(), o, l, p, unit, conf, note, ranged=o < p)


def find_durations(s: str) -> list[DurMatch]:
    """Non-overlapping duration expressions in `s`, sorted by position."""
    taken: list[tuple[int, int]] = []
    out: list[DurMatch] = []
    for kind, rx in _PATTERNS:
        for m in rx.finditer(s):
            if any(m.start() < b and a < m.end() for a, b in taken):
                continue
            # "a"/"an" only count as one when they stand alone ("a week", not "a 2 week")
            d = _make(kind, m)
            if d is None:
                continue
            taken.append((m.start(), m.end()))
            out.append(d)
    out.sort(key=lambda d: d.start)
    return out


def parse_duration_text(s: str, default_unit: str | None = None) -> DurMatch | None:
    """A whole answer or table cell. A bare number uses `default_unit`."""
    ds = find_durations(s)
    if ds:
        return ds[0]
    if default_unit:
        rng = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:(?:-|to)\s*(\d+(?:\.\d+)?)\s*)?", s)
        if rng:
            a = float(rng.group(1))
            c = float(rng.group(2)) if rng.group(2) else a
            o, p = sorted((a, c))
            if o > 0:
                return DurMatch(0, len(s), o, (o + p) / 2, p, default_unit, 0.95, ranged=o < p)
    return None
