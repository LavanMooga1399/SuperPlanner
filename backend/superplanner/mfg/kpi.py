"""KPI formulas (M4-DESIGN 9) over loaded rows. Pure; every ratio is returned as `(num, den)` so closed days can be
cached per day (`mfg_kpi_daily`) and periods aggregate exactly (sum of nums / sum of dens).

Interpretations (16.WP-S): work intervals come from the event log (setup / running between transitions, the line of
the operation); the standard minutes of `performance` are the reported units at the operation's run rate on that
line (run minutes per unit / speed factor, batch and panel loads rounded up); first-pass yield of an inspection-gate
operation = (good - rework received) / (good + scrap + rework sent back) of its reports; plant FPY weights the gate
operations by their units.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .floor import engine as E

Ratio = tuple[float, float]


@dataclass(frozen=True)
class Interval:
    wo_operation_id: str
    line_id: str | None
    kind: str            # setup | running
    start: datetime
    end: datetime
    crew: int = 0


def work_intervals(events: Iterable[E.Ev], line_of: dict[str, str | None] | None = None, *,
                   op_id: str = "", until: datetime | None = None) -> list[Interval]:
    """The setup / running intervals of one operation's (corrected) events; an open interval ends at `until`."""
    out: list[Interval] = []
    st = E.OpState()
    for e in sorted(E.corrected(events), key=lambda x: x.seq):
        prev_status, prev_since, prev_line = st.status, st.since, st.line_id
        try:
            st = E.apply(st, e)
        except E.FloorRuleError:
            continue
        if prev_since is not None and prev_status in E.ACTIVE and (st.since != prev_since or st.status != prev_status):
            if e.event_at > prev_since:
                out.append(Interval(op_id, prev_line, prev_status, prev_since, e.event_at))
    if st.since is not None and st.status in E.ACTIVE and until is not None and until > st.since:
        out.append(Interval(op_id, st.line_id, st.status, st.since, until))
    return out


def clip_minutes(a: datetime, b: datetime, lo: datetime, hi: datetime) -> float:
    s, e = max(a, lo), min(b, hi)
    return max(0.0, (e - s).total_seconds() / 60.0)


def day_bounds(d: date, tz: tzinfo) -> tuple[datetime, datetime]:
    lo = datetime(d.year, d.month, d.day, tzinfo=tz)
    return lo, lo + timedelta(days=1)


def ratio(num: float, den: float) -> float | None:
    return round(num / den, 6) if den > 1e-9 else None


def adherence(rows: Iterable[tuple[datetime, datetime, datetime | None, datetime | None]], tol_minutes: float
              ) -> Ratio:
    """(planned_start, planned_end, actual_start, actual_end): started within the tolerance of the planned start
    and completed by planned end + tolerance."""
    tol = timedelta(minutes=tol_minutes)
    num = den = 0.0
    for ps, pe, a_s, a_e in rows:
        den += 1
        if a_s is not None and abs(a_s - ps) <= tol and a_e is not None and a_e <= pe + tol:
            num += 1
    return num, den


def fpy(good: float, rework_in: float, scrap: float, rework_out: float) -> Ratio:
    return max(0.0, good - rework_in), good + scrap + rework_out


def standard_minutes(units: float, run_minutes: float, run_per: str, units_per_panel: int | None,
                     units_per_batch: int | None, speed_factor: float = 1.0) -> float:
    if run_per == "panel" and units_per_panel:
        n = math.ceil(units / units_per_panel - 1e-9)
    elif run_per == "batch" and units_per_batch:
        n = math.ceil(units / units_per_batch - 1e-9)
    else:
        n = units
    return float(run_minutes) * n / (speed_factor or 1.0)


def oee(availability: float | None, performance: float | None, fpy_: float | None) -> float | None:
    if availability is None or performance is None:
        return None
    return round(availability * min(performance, 1.5) * (fpy_ if fpy_ is not None else 1.0), 6)


def sum_ratios(rs: Iterable[Ratio]) -> Ratio:
    n = d = 0.0
    for a, b in rs:
        n += a
        d += b
    return n, d


__all__ = ["Interval", "adherence", "clip_minutes", "day_bounds", "fpy", "oee", "ratio", "standard_minutes",
           "sum_ratios", "work_intervals"]
_ = Any
