"""Forecast spread, consumption by customer orders and time zones for MRP (M8-DESIGN 4.4, 0.6).

`consume(...)` (pure):

1. `final_qty` of every period is spread over the working days of the period (equal shares; a period without a
   working day keeps its quantity on its first day).
2. Open customer orders per item, by due date ascending, consume the daily forecast from the due date backward
   `back_days`, then forward `fwd_days` (day after due date onward). What an order cannot consume is
   over-consumption (`FC_OVERCONSUMED`, info; the order still counts fully in MRP).
3. Days before `as_of` are dropped; the rest is aggregated into time zones: per day for `daily_days`, per week
   (Monday, not before the zone start) for `weekly_weeks`, per month (first day, not before the zone start) after.

Returns `ForecastSnap`s (MRP requirements of kind `forecast`), a consumption view per item x period and the
over-consumed orders.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Iterable

from .history import add_periods, period_start
from .model import ForecastSnap

EPS = 1e-9
_DAY = timedelta(days=1)


@dataclass(frozen=True)
class OrderDemand:
    item_id: str
    due: date
    qty: float
    ref: str = ""


@dataclass
class ConsumeResult:
    snaps: list[ForecastSnap]
    view: list[dict[str, Any]]                           # ConsumptionRow dicts
    overconsumed: list[dict[str, Any]] = field(default_factory=list)   # [{item_id, ref, due, qty}]


def spread(period: date, qty: float, bucket: str, is_workday: Callable[[date], bool]) -> dict[date, float]:
    end = add_periods(period, 1, bucket)
    days = []
    d = period
    while d < end:
        if is_workday(d):
            days.append(d)
        d += _DAY
    if not days:
        return {period: qty}
    share = qty / len(days)
    return {d: share for d in days}


def zone_date(d: date, as_of: date, daily_days: int, weekly_weeks: int) -> date:
    daily_end = as_of + timedelta(days=daily_days)
    if d < daily_end:
        return d
    weekly_end = daily_end + timedelta(weeks=weekly_weeks)
    if d < weekly_end:
        return max(d - timedelta(days=d.weekday()), daily_end)
    return max(d.replace(day=1), weekly_end)


def consume(lines: dict[str, list[tuple[date, float]]], orders: Iterable[OrderDemand], *, bucket: str,
            as_of: date, is_workday: Callable[[date], bool], version_id: str, back_days: int = 30,
            fwd_days: int = 30, daily_days: int = 28, weekly_weeks: int = 26) -> ConsumeResult:
    by_item: dict[str, list[OrderDemand]] = defaultdict(list)
    for o in orders:
        if o.qty > EPS:
            by_item[o.item_id].append(o)
    snaps: list[ForecastSnap] = []
    view: list[dict[str, Any]] = []
    over: list[dict[str, Any]] = []
    for item_id in sorted(lines):
        daily: dict[date, float] = {}
        period_of: dict[date, date] = {}
        period_total: dict[date, float] = {}
        for p, q in sorted(lines[item_id]):
            period_total[p] = period_total.get(p, 0.0) + max(q, 0.0)
            for d, v in spread(p, max(q, 0.0), bucket, is_workday).items():
                daily[d] = daily.get(d, 0.0) + v
                period_of[d] = p
        consumed_by_period: dict[date, float] = defaultdict(float)
        orders_by_period: dict[date, float] = defaultdict(float)
        over_by_period: dict[date, float] = defaultdict(float)
        for o in sorted(by_item.get(item_id, []), key=lambda x: (x.due, x.ref)):
            need = o.qty
            orders_by_period[period_start(o.due, bucket)] += o.qty
            order_days = [o.due - timedelta(days=k) for k in range(0, back_days + 1)] + \
                         [o.due + timedelta(days=k) for k in range(1, fwd_days + 1)]
            for d in order_days:
                if need <= EPS:
                    break
                avail = daily.get(d, 0.0)
                if avail <= EPS:
                    continue
                take = min(avail, need)
                daily[d] = avail - take
                need -= take
                consumed_by_period[period_of[d]] += take
            if need > EPS:
                over.append({"item_id": item_id, "ref": o.ref, "due": o.due, "qty": need})
                over_by_period[period_start(o.due, bucket)] += need
        open_by_period: dict[date, float] = defaultdict(float)
        zoned: dict[tuple[date, date], float] = defaultdict(float)
        for d in sorted(daily):
            q = daily[d]
            if d < as_of or q <= EPS:
                continue
            p = period_of[d]
            open_by_period[p] += q
            zoned[(zone_date(d, as_of, daily_days, weekly_weeks), p)] += q
        for (zd, p), q in sorted(zoned.items()):
            snaps.append(ForecastSnap(item_id, zd, round(q, 6), version_id, p))
        for p in sorted(set(period_total) | set(orders_by_period)):
            view.append({"item_id": item_id, "period_start": p, "forecast": round(period_total.get(p, 0.0), 6),
                         "consumed": round(consumed_by_period.get(p, 0.0), 6),
                         "open": round(open_by_period.get(p, 0.0), 6),
                         "orders": round(orders_by_period.get(p, 0.0), 6),
                         "overconsumed": round(over_by_period.get(p, 0.0), 6)})
    return ConsumeResult(snaps, view, over)
