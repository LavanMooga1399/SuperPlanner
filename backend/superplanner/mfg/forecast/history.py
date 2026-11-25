"""Demand history (M8-DESIGN 4.1): period arithmetic, source precedence, outlier cleaning, series building.

Pure functions. A period is identified by its start date (`m`: first of month, `w`: Monday).

- `merge_sources(rows)`: one value per (item, period): import > sap > ledger; a planner value (`manual_qty`) wins
  over automatic cleaning.
- `clean(values)`: values outside median +/- 5 x MAD are clipped to the bound (`FC_OUTLIER`). Series with many
  zeros (> 30 %, intermittent) use the statistics of the non-zero values and only clip non-zero values.
- `build_series(...)`: per item the cleaned values from the first non-zero period to the last closed period
  (zero-filled); MAD = 0 (constant series with a spike) falls back to the scaled mean absolute deviation; items with a like item and < 12 periods use the like item's series x `like_factor`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

import numpy as np

PRECEDENCE = {"import": 3, "sap": 2, "ledger": 1}
MAD_K = 5.0
LIKE_MIN_PERIODS = 12


def period_start(d: date, bucket: str) -> date:
    if bucket == "w":
        return d - timedelta(days=d.weekday())
    return d.replace(day=1)


def add_periods(p: date, k: int, bucket: str) -> date:
    if bucket == "w":
        return p + timedelta(weeks=k)
    y, m = divmod(p.month - 1 + k, 12)
    return date(p.year + y, m + 1, 1)


def period_end(p: date, bucket: str) -> date:
    """Last day of the period starting at `p`."""
    return add_periods(p, 1, bucket) - timedelta(days=1)


def periods_between(a: date, b: date, bucket: str) -> int:
    """Number of whole periods from period `a` to period `b` (b - a)."""
    if bucket == "w":
        return (b - a).days // 7
    return (b.year - a.year) * 12 + (b.month - a.month)


def last_closed_period(as_of: date, bucket: str) -> date:
    return add_periods(period_start(as_of, bucket), -1, bucket)


@dataclass(frozen=True)
class HistPoint:
    item_id: str
    period_start: date
    qty: float
    source: str
    manual_qty: float | None = None
    row_id: str | None = None


def merge_sources(rows: Iterable[HistPoint]) -> dict[str, dict[date, HistPoint]]:
    out: dict[str, dict[date, HistPoint]] = {}
    for r in rows:
        cur = out.setdefault(r.item_id, {}).get(r.period_start)
        if cur is None or PRECEDENCE.get(r.source, 0) > PRECEDENCE.get(cur.source, 0):
            out[r.item_id][r.period_start] = r
    return out


def clean(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """-> (cleaned values, outlier mask)."""
    y = np.asarray(values, dtype=float)
    if y.size < 3:
        return y.copy(), np.zeros(y.shape, dtype=bool)
    zeros = float((y <= 0).mean())
    base = y[y > 0] if zeros > 0.3 else y
    if base.size < 3:
        return y.copy(), np.zeros(y.shape, dtype=bool)
    med = float(np.median(base))
    mad = float(np.median(np.abs(base - med)))
    if mad <= 0:                         # (nearly) constant series: mean absolute deviation, scaled like a MAD
        mad = float(np.mean(np.abs(base - med))) * 1.2533
    if mad <= 0:
        return y.copy(), np.zeros(y.shape, dtype=bool)
    lo, hi = med - MAD_K * mad, med + MAD_K * mad
    if zeros > 0.3:                      # intermittent: only unusually large non-zero demands are clipped
        mask = y > hi
        out = np.where(mask, hi, y)
    else:
        mask = (y > hi) | (y < lo)
        out = np.clip(y, max(lo, 0.0), hi)
    return out, mask


@dataclass
class ItemSeries:
    item_id: str
    start: date | None                 # first non-zero period (None = no demand)
    raw: list[float]
    values: list[float]                # cleaned (or planner-set) values used for the model
    outliers: list[bool]
    like_item_id: str | None = None


def build_series(points: dict[str, dict[date, HistPoint]], item_ids: Iterable[str], last_period: date, bucket: str,
                 clean_outliers: bool = True, like: dict[str, tuple[str, float]] | None = None
                 ) -> dict[str, ItemSeries]:
    like = like or {}
    out: dict[str, ItemSeries] = {}
    for item_id in item_ids:
        out[item_id] = _one(points.get(item_id, {}), item_id, last_period, bucket, clean_outliers)
    for item_id, (like_id, factor) in like.items():
        cur = out.get(item_id)
        if cur is None or len(cur.values) >= LIKE_MIN_PERIODS:
            continue
        src = out.get(like_id) or _one(points.get(like_id, {}), like_id, last_period, bucket, clean_outliers)
        if not src.values:
            continue
        out[item_id] = ItemSeries(item_id, src.start, [v * factor for v in src.raw],
                                  [v * factor for v in src.values], list(src.outliers), like_item_id=like_id)
    return out


def _one(pts: dict[date, HistPoint], item_id: str, last_period: date, bucket: str, clean_outliers: bool
         ) -> ItemSeries:
    nonzero = sorted(p for p, h in pts.items() if p <= last_period and h.qty > 0)
    if not nonzero:
        return ItemSeries(item_id, None, [], [], [])
    start = nonzero[0]
    n = periods_between(start, last_period, bucket) + 1
    raw = np.zeros(n)
    manual: dict[int, float] = {}
    for p, h in pts.items():
        if start <= p <= last_period:
            k = periods_between(start, p, bucket)
            raw[k] = max(h.qty, 0.0)
            if h.manual_qty is not None:
                manual[k] = max(h.manual_qty, 0.0)
    if clean_outliers:
        vals, mask = clean(raw)
    else:
        vals, mask = raw.copy(), np.zeros(n, dtype=bool)
    for k, v in manual.items():
        vals[k] = v
        mask[k] = False
    return ItemSeries(item_id, start, [float(v) for v in raw], [float(v) for v in vals], [bool(x) for x in mask])


def aggregate(rows: Iterable[tuple[str, date, float]], bucket: str) -> dict[tuple[str, date], float]:
    """(item_id, day, qty) -> {(item_id, period_start): qty} (history refresh from ledger postings / orders)."""
    out: dict[tuple[str, date], float] = {}
    for item_id, d, q in rows:
        key = (item_id, period_start(d, bucket))
        out[key] = out.get(key, 0.0) + float(q)
    return out


def cleaned_values(points: dict[date, HistPoint], bucket: str, last_period: date) -> dict[date, tuple[float | None,
                                                                                                      bool]]:
    """period -> (cleaned value if it differs from the raw value else None, outlier flag) for storing in
    `mfg_demand_history.cleaned_qty` by the refresh."""
    s = _one(points, "_", last_period, bucket, True)
    out: dict[date, tuple[float | None, bool]] = {}
    if s.start is None:
        return out
    for k, (r, v, o) in enumerate(zip(s.raw, s.values, s.outliers)):
        p = add_periods(s.start, k, bucket)
        out[p] = (v if abs(v - r) > 1e-9 else None, o)
    return out


def as_points(rows: Iterable[Any]) -> list[HistPoint]:
    """ORM rows (`MfgDemandHistoryRow`) -> HistPoint."""
    return [HistPoint(r.item_id, r.period_start, float(r.qty), r.source, r.manual_qty, r.id) for r in rows]
