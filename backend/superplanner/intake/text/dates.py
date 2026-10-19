"""Absolute and relative dates, months and date roles (PHASE2 2.7.4). Linear-time patterns."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from .numbers import NUM, parse_number

MONTHS = {"january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
          "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
          "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12}
WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2, "wed": 2, "thursday": 3,
            "thurs": 3, "thur": 3, "thu": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
DAY_FIRST_LOCALES = ("en-IN", "en-GB")
KNOWN_LOCALES = ("en-IN", "en-GB", "en-US")

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("iso", re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")),
    ("numeric", re.compile(r"\b(?P<p1>\d{1,2})[/.](?P<p2>\d{1,2})[/.](?P<y>\d{4}|\d{2})\b")),
    ("dmy", re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MON})\.?(?:,?\s+(?P<y>\d{{4}}))?\b",
                       re.I)),
    ("mdy", re.compile(rf"\b(?P<mon>{_MON})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<y>\d{{4}})\b)?", re.I)),
    ("monyear", re.compile(rf"\b(?P<mon>{_MON})\.?\s*(?:'(?P<yy>\d{{2}})|(?P<y>\d{{4}}))\b", re.I)),
    ("today", re.compile(r"\b(?P<w>today|tomorrow)\b", re.I)),
    ("nextwd", re.compile(rf"\b(?P<which>next|this|coming)\s+(?P<wd>{_WD})\b", re.I)),
    ("in", re.compile(rf"\bin\s+(?P<n>{NUM})\s+(?P<u>days?|weeks?|months?|years?)\b", re.I)),
    ("within", re.compile(rf"\bwithin\s+(?P<n>{NUM})\s+(?P<u>days?|weeks?|months?)\b", re.I)),
    ("fromnow", re.compile(rf"\b(?P<n>{NUM})\s+(?P<u>days?|weeks?|months?|years?)\s+from\s+(?:now|today)\b", re.I)),
    ("endof", re.compile(r"\b(?:the\s+)?end\s+of\s+(?:the\s+)?(?P<which>this|next)\s+(?P<u>week|month|year)\b", re.I)),
    ("nextunit", re.compile(r"\bnext\s+(?P<u>week|month|year)\b", re.I)),
    # a bare weekday counts only right after a deadline word ("due Friday", "by Monday"); checked in find_dates
    ("barewd", re.compile(rf"\b(?P<wd>{_WD})\b", re.I)),
]
_BAREWD_ROLE_RE = re.compile(r"\b(?:due|by|before|until|till|deadline|no later than)\s*(?:on\s+)?(?::\s*)?$", re.I)

DEADLINE_RE = re.compile(r"(?:\b(?:no later than|at the latest by|latest by|due(?:\s+(?:on|by))?|by|before|until|"
                         r"till|deadline(?:\s+is)?|finish(?:ed)? by|due date)\s*:?\s*)$", re.I)
START_RE = re.compile(r"(?:\b(?:not before|starting(?:\s+(?:on|from))?|starts?(?:\s+on)?|start(?:ing)? on|"
                      r"beginning(?:\s+on)?|begins?(?:\s+on)?|from|after)\s*:?\s*)$", re.I)
HARD_RE = re.compile(r"\b(?:no later than|must|hard|latest|at the latest|strict|strictly|absolutely)\b", re.I)


# Dates outside this range are not read (they would overflow date arithmetic later; PHASE2 2.7 robustness).
MIN_YEAR, MAX_YEAR = 1900, 2200


def in_range(d: date | None) -> bool:
    return d is not None and MIN_YEAR <= d.year <= MAX_YEAR


@dataclass
class DateMatch:
    start: int
    end: int
    value: date
    granularity: str            # "day" | "month"
    confidence: float
    relative: bool = False
    alternative: date | None = None   # set when DD/MM vs MM/DD is ambiguous
    kind: str = ""
    deadline_like: bool = False       # "within N weeks"


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _next_on_or_after(today: date, m: int, d: int) -> date | None:
    for y in (today.year, today.year + 1):
        v = _safe(y, m, d)
        if v is not None and v >= today:
            return v
    return _safe(today.year + 1, m, d)


def _make(kind: str, mt: re.Match[str], today: date, locale: str) -> DateMatch | None:
    g = mt.groupdict()
    s, e = mt.start(), mt.end()
    if kind == "iso":
        v = _safe(int(g["y"]), int(g["m"]), int(g["d"]))
        return DateMatch(s, e, v, "day", 0.95, kind=kind) if v else None
    if kind == "numeric":
        p1, p2 = int(g["p1"]), int(g["p2"])
        y = int(g["y"])
        if y < 100:
            y += 2000
        day_first = locale != "en-US"
        d, m = (p1, p2) if day_first else (p2, p1)
        v = _safe(y, m, d)
        alt = None
        if p1 <= 12 and p2 <= 12 and p1 != p2 and locale not in KNOWN_LOCALES:
            alt = _safe(y, d, m)
        if v is None:
            v, alt = _safe(y, d, m), None
        return DateMatch(s, e, v, "day", 0.95 if alt is None else 0.4, alternative=alt, kind=kind) if v else None
    if kind in ("dmy", "mdy"):
        m = MONTHS[g["mon"].lower().rstrip(".")]
        d = int(g["d"])
        if g.get("y"):
            v = _safe(int(g["y"]), m, d)
        else:
            if g["mon"].lower() == "may" and kind == "mdy":
                return None
            v = _next_on_or_after(today, m, d)
        return DateMatch(s, e, v, "day", 0.95, kind=kind) if v else None
    if kind == "monyear":
        m = MONTHS[g["mon"].lower().rstrip(".")]
        y = int(g["y"]) if g.get("y") else 2000 + int(g["yy"])
        return DateMatch(s, e, month_end(y, m), "month", 0.95, kind=kind)
    if kind == "today":
        v = today if g["w"].lower() == "today" else today + timedelta(days=1)
        return DateMatch(s, e, v, "day", 0.8, relative=True, kind=kind)
    if kind == "nextwd":
        wd = WEEKDAYS[g["wd"].lower()]
        ahead = (wd - today.weekday()) % 7
        if g["which"].lower() in ("next", "coming"):
            ahead = ahead or 7
        return DateMatch(s, e, today + timedelta(days=ahead), "day", 0.8, relative=True, kind=kind)
    if kind in ("in", "within", "fromnow"):
        n = parse_number(g["n"])
        if n is None:
            return None
        k = int(round(n[0]))
        u = g["u"].lower().rstrip("s")
        if u == "day":
            v = today + timedelta(days=k)
        elif u == "week":
            v = today + timedelta(weeks=k)
        elif u == "month":
            v = add_months(today, k)
        else:
            v = add_months(today, 12 * k)
        return DateMatch(s, e, v, "day", 0.8, relative=True, kind=kind, deadline_like=kind == "within")
    if kind == "endof":
        u = g["u"].lower()
        nxt = g["which"].lower() == "next"
        if u == "week":
            v = today + timedelta(days=(6 - today.weekday()) % 7 + (7 if nxt else 0))
        elif u == "month":
            base = add_months(today.replace(day=1), 1 if nxt else 0)
            v = month_end(base.year, base.month)
        else:
            v = date(today.year + (1 if nxt else 0), 12, 31)
        return DateMatch(s, e, v, "day", 0.8, relative=True, kind=kind, deadline_like=True)
    if kind == "barewd":     # "due Friday": the next such weekday on or after today (like "this Friday")
        wd = WEEKDAYS[g["wd"].lower()]
        return DateMatch(s, e, today + timedelta(days=(wd - today.weekday()) % 7), "day", 0.7, relative=True,
                         kind=kind)
    if kind == "nextunit":
        u = g["u"].lower()
        if u == "week":
            v = today + timedelta(days=7 - today.weekday())
        elif u == "month":
            v = add_months(today.replace(day=1), 1)
        else:
            v = add_months(today, 12)
        return DateMatch(s, e, v, "day", 0.7, relative=True, kind=kind)
    return None  # pragma: no cover


def find_dates(s: str, today: date, locale: str = "en-IN") -> list[DateMatch]:
    taken: list[tuple[int, int]] = []
    out: list[DateMatch] = []
    for kind, rx in _PATTERNS:
        for mt in rx.finditer(s):
            if any(mt.start() < b and a < mt.end() for a, b in taken):
                continue
            if kind == "barewd" and not _BAREWD_ROLE_RE.search(s[max(0, mt.start() - 30):mt.start()]):
                continue
            try:
                d = _make(kind, mt, today, locale)
            except (ValueError, OverflowError):     # "in 9999 years", "in 99999999 months": not a usable date
                d = None
            if d is None or not in_range(d.value):
                continue
            if d.alternative is not None and not in_range(d.alternative):
                d.alternative = None
            taken.append((mt.start(), mt.end()))
            out.append(d)
    out.sort(key=lambda d: d.start)
    return out


def out_of_range_dates(s: str, today: date, locale: str = "en-IN") -> list[tuple[int, int]]:
    """Spans of date phrases that look like dates but are outside MIN_YEAR..MAX_YEAR (or overflow); the readers
    add a note for them instead of dropping them silently."""
    out: list[tuple[int, int]] = []
    taken: list[tuple[int, int]] = []        # a phrase read by an earlier pattern ("31 Dec 9999") is reported once
    for kind, rx in _PATTERNS:
        for mt in rx.finditer(s):
            if any(mt.start() < b and a < mt.end() for a, b in taken):
                continue
            if kind == "barewd":
                continue
            try:
                d = _make(kind, mt, today, locale)
            except (ValueError, OverflowError):
                d, bad = None, True
            else:
                bad = d is not None and not in_range(d.value)
            if d is not None or bad:
                taken.append((mt.start(), mt.end()))
            if bad:
                out.append((mt.start(), mt.end()))
            if len(out) >= 20:
                break
        if len(out) >= 20 or len(taken) > 2000:
            break
    out.sort()
    return out


def role_of(s: str, start: int) -> tuple[str | None, int]:
    """("deadline" | "start" | None, role-word start) for a date starting at `start` in `s`."""
    window_start = max(0, start - 30)
    before = s[window_start:start]
    m = DEADLINE_RE.search(before)
    if m:
        return "deadline", window_start + m.start()
    m = START_RE.search(before)
    if m:
        return "start", window_start + m.start()
    return None, start


def parse_date_text(s: str, today: date, locale: str = "en-IN") -> date | None:
    ds = find_dates(s, today, locale)
    return ds[0].value if ds else None


def parse_month_text(s: str, today: date, locale: str = "en-IN") -> str | None:
    m = re.fullmatch(r"\s*(\d{4})-(0[1-9]|1[0-2])\s*", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.fullmatch(r"\s*(\d{4})\s*", s)
    if m:
        return f"{m.group(1)}-{today.month:02d}"
    d = parse_date_text(s, today, locale)
    return f"{d.year:04d}-{d.month:02d}" if d else None
