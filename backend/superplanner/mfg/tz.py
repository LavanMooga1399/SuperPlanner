"""Plant time (M3-DESIGN 5). `plant_tz(plant)` is the one helper every local-time computation uses: the IANA zone
when `plant.time_zone` is set (validated with `zoneinfo`; `tzdata` provides the database on every platform), else
the M1 fixed `utc_offset`. Wall-clock -> instant: a non-existent local time (spring-forward gap) moves forward by
the gap and an ambiguous one (fall-back) takes the first occurrence - exactly what `datetime(..., tzinfo=zone,
fold=0)` does, so callers build aware datetimes with fold 0 and convert to UTC before doing arithmetic.

Note: subtracting two aware datetimes that share one `ZoneInfo` object is wall-clock arithmetic in Python; always
use `elapsed_minutes` (UTC) for durations."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


def offset_tz(utc_offset: str) -> timezone:
    sign = -1 if utc_offset[0] == "-" else 1
    h, m = utc_offset[1:].split(":")
    return timezone(sign * timedelta(hours=int(h), minutes=int(m)))


@lru_cache(maxsize=256)
def zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def valid_zone(name: str | None) -> bool:
    return name is None or (bool(name) and "/" in name or name == "UTC") and zone(name) is not None


@lru_cache(maxsize=1)
def zone_names() -> tuple[str, ...]:
    """Sorted IANA names offered by the UI's time-zone picker (`/meta`)."""
    return tuple(sorted(n for n in available_timezones() if "/" in n and not n.startswith(("Etc/", "SystemV/"))))


def plant_tz(plant: Any) -> tzinfo:
    """`plant.time_zone` (IANA) if set and known, else the fixed `plant.utc_offset`."""
    name = getattr(plant, "time_zone", None)
    if name:
        z = zone(name)
        if z is not None:
            return z
    return offset_tz(getattr(plant, "utc_offset", None) or "+00:00")


def plant_now(plant: Any) -> datetime:
    return datetime.now(UTC).astimezone(plant_tz(plant))


def plant_today(plant: Any) -> date:
    return plant_now(plant).date()


def current_offset(plant: Any, at: datetime | None = None) -> str:
    """The plant's UTC offset at `at` (default now) as `+HH:MM` (display value of `utc_offset` with a zone)."""
    off = (at or datetime.now(UTC)).astimezone(plant_tz(plant)).utcoffset() or timedelta(0)
    mins = int(off.total_seconds() // 60)
    sign = "-" if mins < 0 else "+"
    mins = abs(mins)
    return f"{sign}{mins // 60:02d}:{mins % 60:02d}"


def local(d: date, minute: int, tz: tzinfo) -> datetime:
    """Aware instant of local wall-clock `d + minute` (minute may exceed 1440), fold 0 (5)."""
    dd = d + timedelta(days=minute // 1440)
    m = minute % 1440
    return datetime(dd.year, dd.month, dd.day, m // 60, m % 60, tzinfo=tz)


def local_midnight(d: date, tz: tzinfo) -> datetime:
    """Due-date semantics (M2 8.5, M3 Q2): available at local 00:00 of `d`."""
    return datetime(d.year, d.month, d.day, tzinfo=tz)


def to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC)


def elapsed_minutes(a: datetime, b: datetime) -> float:
    return (b.astimezone(UTC) - a.astimezone(UTC)).total_seconds() / 60.0


__all__ = ["current_offset", "elapsed_minutes", "local", "local_midnight", "offset_tz", "plant_now", "plant_today",
           "plant_tz", "to_utc", "valid_zone", "zone", "zone_names"]
