"""Forecast engine (M8-DESIGN 4): methods, selection, cleaning, overrides, consumption, accuracy (pure)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from superplanner.mfg.forecast import accuracy, consume, history, methods, overrides, select
from superplanner.mfg.workdays import WorkCalendar


def seasonal_trend(n: int = 36, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    season = 1 + 0.35 * np.cos(2 * np.pi * (t % 12) / 12)        # winter (flu) peak
    return (10_000 + 120 * t) * season + rng.normal(0, 150, n)


@pytest.mark.req("M8-FC-01")
def test_seasonal_trend_series_selects_holt_winters():
    res = select.select({"itm_a": seasonal_trend()}, "m", 18)["itm_a"]
    assert res["demand_class"] == "smooth"
    assert res["method"] in ("hw_add", "hw_mul")
    assert res["holdout_wape"] < 0.15
    assert len(res["forecast"]) == 18 and min(res["forecast"]) >= 0
    # the forecast keeps the seasonal shape: the peak month is a winter month
    assert int(np.argmax(res["forecast"][:12])) in (0, 1, 10, 11, 12) or res["forecast"][0] > res["forecast"][6]


@pytest.mark.req("M8-FC-02")
def test_intermittent_series_uses_croston_family_and_sba_factor():
    y = np.zeros(30)
    y[[0, 3, 5, 8, 10, 13, 15, 18, 20, 23, 25, 28]] = [40, 55, 38, 61, 47, 52, 44, 58, 41, 50, 49, 53]
    res = select.select({"itm_i": y}, "m", 6)["itm_i"]
    assert res["demand_class"] in ("intermittent", "lumpy") and res["adi"] == pytest.approx(2.5)
    assert res["method"] in ("ma", "croston", "sba")
    assert set(res["candidates"]) == {"ma", "croston", "sba"}
    Y = y[None, :]
    cro = methods.run_fixed("croston", Y, 3, 12, {"alpha": 0.1})
    sba = methods.run_fixed("sba", Y, 3, 12, {"alpha": 0.1})
    assert sba.forecast[0, 0] == pytest.approx(0.95 * cro.forecast[0, 0])
    assert np.allclose(sba.forecast, sba.forecast[0, 0])


@pytest.mark.req("M8-FC-03")
def test_two_periods_history_gives_zero_forecast_and_flag():
    res = select.select({"itm_s": [120.0, 80.0]}, "m", 18)["itm_s"]
    assert res["method"] == "zero" and res["forecast"] == [0.0] * 18
    assert res["flags"] == ["FC_HISTORY_SHORT"] and res["demand_class"] == "short"


@pytest.mark.req("M8-FC-04")
def test_outlier_ten_times_median_is_clipped_and_reset_restores():
    raw = [100, 104, 98, 101, 97, 103, 1000, 99, 102, 100, 96, 105.0]
    cleaned, mask = history.clean(np.array(raw))
    assert mask.tolist() == [i == 6 for i in range(12)]
    assert cleaned[6] < 200 and cleaned[6] == pytest.approx(np.median(raw) + 5 * np.median(np.abs(
        np.array(raw) - np.median(raw))))
    pts = {date(2025, m, 1): history.HistPoint("i", date(2025, m, 1), raw[m - 1], "ledger") for m in range(1, 13)}
    s = history.build_series({"i": pts}, ["i"], date(2025, 12, 1), "m")["i"]
    assert s.outliers[6] and s.values[6] < 200
    pts[date(2025, 7, 1)] = history.HistPoint("i", date(2025, 7, 1), 1000.0, "ledger", manual_qty=1000.0)
    s = history.build_series({"i": pts}, ["i"], date(2025, 12, 1), "m")["i"]
    assert s.values[6] == 1000.0 and not s.outliers[6]


def test_source_precedence_and_like_item():
    p = date(2026, 1, 1)
    merged = history.merge_sources([history.HistPoint("i", p, 5, "ledger"), history.HistPoint("i", p, 7, "import"),
                                    history.HistPoint("i", p, 6, "sap")])
    assert merged["i"][p].qty == 7 and merged["i"][p].source == "import"
    pts = {"old": {history.add_periods(date(2024, 1, 1), k, "m"): history.HistPoint(
        "old", history.add_periods(date(2024, 1, 1), k, "m"), 100.0, "ledger") for k in range(24)},
           "new": {date(2025, 12, 1): history.HistPoint("new", date(2025, 12, 1), 10.0, "ledger")}}
    out = history.build_series(pts, ["old", "new"], date(2025, 12, 1), "m", like={"new": ("old", 0.5)})
    assert out["new"].like_item_id == "old" and out["new"].values[0] == 50.0 and len(out["new"].values) == 24


def test_selection_is_deterministic_and_vectorised_groups():
    rng = np.random.default_rng(1)
    series = {f"itm_{k}": rng.gamma(4, 50, 30 - (k % 3)).tolist() for k in range(30)}
    a = select.select(series, "m", 12)
    b = select.select(dict(reversed(list(series.items()))), "m", 12)
    assert a == b


@pytest.mark.req("M8-FC-05")
def test_family_pct_then_item_abs_override():
    p1, p2 = date(2027, 1, 1), date(2027, 2, 1)
    stat = {("a", p1): 1000.0, ("a", p2): 1000.0, ("b", p1): 3000.0, ("b", p2): 3000.0, ("c", p1): 500.0}
    fam = {"a": "SYR", "b": "SYR", "c": "NDL"}
    ovs = [overrides.Override("o1", 1, None, "SYR", p1, p2, "pct", 10.0),
           overrides.Override("o2", 2, "b", None, p1, p1, "abs", 5000.0)]
    final, ch = overrides.apply(stat, ovs, fam)
    assert final[("a", p1)] == pytest.approx(1100) and final[("a", p2)] == pytest.approx(1100)
    assert final[("b", p1)] == 5000 and final[("b", p2)] == pytest.approx(3300)
    assert final[("c", p1)] == 500
    assert {"item_id": "b", "period_start": p1, "old": 3300.0, "new": 5000.0} in ch["o2"]
    assert len(ch["o1"]) == 4
    # family absolute: split proportionally
    final2, _ = overrides.apply(stat, [overrides.Override("o3", 1, None, "SYR", p1, p1, "abs", 8000.0)], fam)
    assert final2[("a", p1)] == pytest.approx(2000) and final2[("b", p1)] == pytest.approx(6000)


CAL = WorkCalendar(["mon", "tue", "wed", "thu", "fri"])


@pytest.mark.req("M8-FC-07")
def test_order_consumes_daily_spread_backward_requirement_total():
    p = date(2027, 3, 1)                                      # March 2027: 23 working days (Mon-Fri)
    days = [d for d in (p + timedelta(k) for k in range(31)) if CAL.is_workday(d)]
    res = consume.consume({"i": [(p, 3000.0)]}, [consume.OrderDemand("i", date(2027, 3, 10), 1000.0, "SO-1")],
                          bucket="m", as_of=date(2027, 3, 1), is_workday=CAL.is_workday, version_id="v",
                          daily_days=60)
    per_day = 3000 / len(days)
    remaining = {s.date: s.qty for s in res.snaps}
    # backward from the 10th: 10, 9, 8, ... (working days) until 1,000 are consumed
    assert remaining.get(date(2027, 3, 10), 0.0) == pytest.approx(0.0)
    # 8 working days (Mar 1-5, 8-10) x 130.43 = 1,043.5 >= 1,000: Mar 1 keeps the 43.5 left over
    assert remaining.get(date(2027, 3, 1), 0.0) == pytest.approx(8 * per_day - 1000, abs=1e-4)
    assert remaining.get(date(2027, 3, 11), 0.0) == pytest.approx(per_day, abs=1e-4)
    assert sum(s.qty for s in res.snaps) + 1000 == pytest.approx(3000)
    assert res.overconsumed == []
    v = res.view[0]
    assert v["consumed"] == pytest.approx(1000) and v["open"] == pytest.approx(2000) and v["orders"] == 1000


@pytest.mark.req("M8-FC-08")
def test_order_larger_than_forecast_in_window_is_overconsumption():
    p = date(2027, 3, 1)
    res = consume.consume({"i": [(p, 3000.0)]}, [consume.OrderDemand("i", date(2027, 3, 15), 5000.0, "SO-2")],
                          bucket="m", as_of=date(2027, 3, 1), is_workday=CAL.is_workday, version_id="v",
                          back_days=30, fwd_days=30)
    assert sum(s.qty for s in res.snaps) == pytest.approx(0.0)
    assert res.overconsumed == [{"item_id": "i", "ref": "SO-2", "due": date(2027, 3, 15), "qty": pytest.approx(2000)}]
    # MRP requirement = order 5,000 + unconsumed 0 = 5,000


def test_time_zones_and_past_days_dropped():
    as_of = date(2027, 1, 13)
    lines = {"i": [(history.add_periods(date(2027, 1, 1), k, "m"), 2100.0) for k in range(12)]}
    res = consume.consume(lines, [], bucket="m", as_of=as_of, is_workday=CAL.is_workday, version_id="v",
                          daily_days=28, weekly_weeks=26)
    dates = sorted({s.date for s in res.snaps})
    assert dates[0] == as_of
    daily_end, weekly_end = as_of + timedelta(28), as_of + timedelta(28 + 26 * 7)
    for d in dates:
        if daily_end <= d < weekly_end:
            assert d.weekday() == 0 or d == daily_end
        elif d >= weekly_end:
            assert d.day == 1 or d == weekly_end
    total_jan_left = sum(s.qty for s in res.snaps if s.period_start == date(2027, 1, 1))
    left_days = sum(1 for k in range(13, 32) if CAL.is_workday(date(2027, 1, k)))
    jan_days = sum(1 for k in range(1, 32) if CAL.is_workday(date(2027, 1, k)))
    assert total_jan_left == pytest.approx(2100 * left_days / jan_days)


@pytest.mark.req("M8-FC-09")
def test_lag1_uses_version_active_before_period_start():
    vs = [accuracy.VersionSpan("v1", datetime(2026, 12, 15), datetime(2027, 2, 10)),
          accuracy.VersionSpan("v2", datetime(2027, 2, 10), None)]
    final = {("v1", "i", date(2027, 2, 1)): 100.0, ("v2", "i", date(2027, 2, 1)): 140.0,
             ("v1", "i", date(2027, 3, 1)): 100.0, ("v2", "i", date(2027, 3, 1)): 150.0}
    f = accuracy.lag_forecasts(vs, final, ["i"], [date(2027, 2, 1), date(2027, 3, 1)], 1, "m")
    assert f[("i", date(2027, 2, 1))] == 100.0           # v1 was active on Jan 1 (latest is v2)
    assert f[("i", date(2027, 3, 1))] == 100.0           # Feb 1: still v1 (v2 activated Feb 10)
    rows = accuracy.report({("i", date(2027, 2, 1)): 120.0, ("i", date(2027, 3, 1)): 80.0}, f, {"i": "A"})
    assert rows == [{"key": "A", "label": "A", "periods": 2, "actual": 200.0, "forecast": 200.0, "wape": 0.2,
                     "bias": 0.0}]
