"""Rough-cut ramp-up and yield (M9-DESIGN 6.4). Rate and yield of a new line are piecewise-linear in weeks since its
start (0 before start, first point held until it, last point held after); existing lines are 1.0. The monthly
factor = mean over the month's working days of rate x yield, so effective hours = hours in month x factor."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Iterable

WORKDAYS = (0, 1, 2, 3, 4)


def interp(points: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear through sorted (x, y); y held outside."""
    if not points:
        return 1.0
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def _pts(points: Iterable[Any]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    rate, yld = [], []
    for p in points:
        w = float(p["week"] if isinstance(p, dict) else p.week)
        r = float(p["rate_pct"] if isinstance(p, dict) else p.rate_pct) / 100.0
        y = float(p["yield_pct"] if isinstance(p, dict) else p.yield_pct) / 100.0
        rate.append((w, r))
        yld.append((w, y))
    return rate, yld


def daily_factor(points: Iterable[Any], start: date, d: date) -> tuple[float, float]:
    """(rate, yield) on day `d` for a line starting on `start`."""
    if d < start:
        return 0.0, 0.0
    rate, yld = _pts(points)
    w = (d - start).days / 7.0
    return interp(rate, w), interp(yld, w)


def working_days(month: date, workdays: Iterable[int] = WORKDAYS, holidays: Iterable[date] = ()) -> list[date]:
    wd, hol = set(workdays), set(holidays)
    n = monthrange(month.year, month.month)[1]
    return [month + timedelta(days=k) for k in range(n) if (month + timedelta(days=k)).weekday() in wd
            and (month + timedelta(days=k)) not in hol]


def month_factor(points: Iterable[Any] | None, start: date, month: date, workdays: Iterable[int] = WORKDAYS
                 ) -> float:
    """Mean over the month's working days of rate x yield (1.0 for an existing line: `points` None)."""
    days = working_days(month, workdays)
    if not days:
        return 0.0
    if points is None:
        return 1.0
    pts = list(points)
    tot = 0.0
    for d in days:
        r, y = daily_factor(pts, start, d)
        tot += r * y
    return tot / len(days)


def month_hours(hours_per_week: float, month: date, workdays: Iterable[int] = WORKDAYS) -> float:
    """Calendar hours of a weekly pattern in a month (working days / working days per week)."""
    wd = list(workdays)
    return hours_per_week * len(working_days(month, wd)) / max(len(wd), 1)
