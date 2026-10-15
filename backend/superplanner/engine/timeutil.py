"""Time model (ARCHITECTURE section 4): integer minutes since `horizon_start`."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Calendar

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def to_minute(dt: datetime, horizon_start: datetime) -> int:
    return math.floor((dt - horizon_start).total_seconds() / 60)


def from_minute(m: int, horizon_start: datetime) -> datetime:
    return horizon_start + timedelta(minutes=m)


def parse_hhmm(value: str) -> int:
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def fmt_minute(m: int, horizon_start: datetime) -> str:
    """`Tue 20 Oct 10:00` in the plan's offset."""
    dt = from_minute(m, horizon_start)
    return f"{_DAY_ABBR[dt.weekday()]} {dt.day} {_MONTH_ABBR[dt.month - 1]} {dt.hour:02d}:{dt.minute:02d}"


def fmt_clock(m: int, horizon_start: datetime) -> str:
    dt = from_minute(m, horizon_start)
    return f"{dt.hour:02d}:{dt.minute:02d}"


def fmt_duration(minutes: int | float) -> str:
    """`2h 15m`, `45m`, `3d 2h`."""
    minutes = int(round(minutes))
    if minutes < 0:
        return "-" + fmt_duration(-minutes)
    if minutes < 60:
        return f"{minutes}m"
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    return " ".join(parts)


def _merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    intervals = sorted(i for i in intervals if i[1] > i[0])
    out: list[list[int]] = []
    for s, e in intervals:
        if out and out[-1][1] >= s:
            if e > out[-1][1]:
                out[-1][1] = e
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def expand_windows(calendar: "Calendar | None", horizon_start: datetime, H: int) -> list[tuple[int, int]]:
    """Availability windows of a resource as sorted, disjoint, non-touching minute intervals.

    Invalid windows (start >= end, "24:00" as start) and invalid blocked intervals are skipped
    here; preflight reports them as `INVALID_CALENDAR`.
    """
    if H <= 0:
        return []
    if calendar is None:
        return [(0, H)]
    if calendar.weekly is None:
        base = [(0, H)]
    else:
        base = []
        local_midnight = horizon_start.replace(hour=0, minute=0, second=0, microsecond=0)
        day_offset = to_minute(local_midnight, horizon_start)  # <= 0
        day = 0
        while day_offset + day * 1440 < H:
            day_start = day_offset + day * 1440
            weekday = _WEEKDAY_KEYS[(local_midnight + timedelta(days=day)).weekday()]
            for start_s, end_s in calendar.weekly.get(weekday, []) or []:  # type: ignore[call-overload]
                if start_s == "24:00":
                    continue
                ws, we = parse_hhmm(start_s), parse_hhmm(end_s)
                if ws >= we:
                    continue
                s, e = max(0, day_start + ws), min(H, day_start + we)
                if s < e:
                    base.append((s, e))
            day += 1
    windows = _merge(base)
    for b in calendar.blocked:
        bs = max(0, to_minute(b.start, horizon_start))
        be = min(H, to_minute(b.end, horizon_start))
        if bs >= be:
            continue
        nxt: list[tuple[int, int]] = []
        for s, e in windows:
            if e <= bs or s >= be:
                nxt.append((s, e))
                continue
            if s < bs:
                nxt.append((s, bs))
            if be < e:
                nxt.append((be, e))
        windows = nxt
    return [(s, e) for s, e in windows if e > s]
