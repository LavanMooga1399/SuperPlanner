"""Forecast accuracy (M8-DESIGN 4.5): backtest summary of a run and lag-k tracking (pure).

Lag-k tracking: for a closed period P the lag-k forecast is the `final_qty` of the version that was active at the
start of period P - k (versions are immutable after activation, so the value is exactly what planning used), not
the latest version. Compared with the actual history (source precedence applied): WAPE = sum|f - a| / sum(a),
bias = sum(f - a) / sum(a), grouped by item, family, ABC class or all.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from .history import add_periods


@dataclass(frozen=True)
class VersionSpan:
    id: str
    activated_at: datetime | date
    archived_at: datetime | date | None


def _d(x: datetime | date) -> date:
    return x.date() if isinstance(x, datetime) else x


def version_active_on(versions: Iterable[VersionSpan], day: date) -> str | None:
    """The version active at the start of `day` (activated on an earlier day or that day, not yet archived)."""
    best: tuple[date, str] | None = None
    for v in versions:
        a = _d(v.activated_at)
        if a > day:
            continue
        if v.archived_at is not None and _d(v.archived_at) <= day:
            continue
        if best is None or a >= best[0]:
            best = (a, v.id)
    return best[1] if best else None


def lag_forecasts(versions: list[VersionSpan], final: dict[tuple[str, str, date], float], items: Iterable[str],
                  periods: Iterable[date], lag: int, bucket: str) -> dict[tuple[str, date], float | None]:
    """(item, period) -> lag-k forecast (None when no version was active then)."""
    out: dict[tuple[str, date], float | None] = {}
    items = list(items)
    for p in periods:
        vid = version_active_on(versions, add_periods(p, -lag, bucket))
        for i in items:
            out[(i, p)] = None if vid is None else final.get((vid, i, p), 0.0)
    return out


def report(actual: dict[tuple[str, date], float], forecast: dict[tuple[str, date], float | None],
           group_of: dict[str, str], labels: dict[str, str] | None = None) -> list[dict[str, Any]]:
    acc: dict[str, dict[str, Any]] = defaultdict(lambda: {"a": 0.0, "f": 0.0, "abs": 0.0, "periods": set()})
    for (item, p), f in forecast.items():
        if f is None:
            continue
        a = actual.get((item, p), 0.0)
        g = group_of.get(item, "all")
        r = acc[g]
        r["a"] += a
        r["f"] += f
        r["abs"] += abs(f - a)
        r["periods"].add(p)
    rows = []
    for g in sorted(acc):
        r = acc[g]
        rows.append({"key": g, "label": (labels or {}).get(g, g), "periods": len(r["periods"]),
                     "actual": round(r["a"], 6), "forecast": round(r["f"], 6),
                     "wape": round(r["abs"] / r["a"], 6) if r["a"] > 0 else None,
                     "bias": round((r["f"] - r["a"]) / r["a"], 6) if r["a"] > 0 else None})
    return rows


def backtest_summary(results: dict[str, dict[str, Any]], abc: dict[str, str]) -> dict[str, Any]:
    """Volume-weighted holdout WAPE and bias overall and per ABC class; method mix; flag counts (4.2)."""
    def agg(rows: list[dict[str, Any]]) -> dict[str, Any]:
        w = sum(r["mean"] for r in rows if r["holdout_wape"] is not None)
        wape = sum(r["holdout_wape"] * r["mean"] for r in rows if r["holdout_wape"] is not None)
        bias = sum((r["bias"] or 0.0) * r["mean"] for r in rows if r["holdout_wape"] is not None)
        return {"wape": round(wape / w, 6) if w > 0 else None, "bias": round(bias / w, 6) if w > 0 else None,
                "items": len(rows)}

    allr = list(results.values())
    by_abc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mix: dict[str, int] = defaultdict(int)
    flags: dict[str, int] = defaultdict(int)
    for r in allr:
        by_abc[abc.get(r["item_id"], "C")].append(r)
        mix[r["method"]] += 1
        for f in r["flags"]:
            flags[f] += 1
    return {**{k: v for k, v in agg(allr).items() if k != "items"},
            "by_abc": {k: agg(v) for k, v in sorted(by_abc.items())},
            "method_mix": dict(sorted(mix.items())), "flags": dict(sorted(flags.items()))}
