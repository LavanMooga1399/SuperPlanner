"""M8 MRP additions (M8-DESIGN 6): forecast requirements in time zones, packaging multiples, kanban pseudo
supplies, rate supplies and pass 1 / pass 2."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from mrp_helpers import AS_OF, D, Plant, Snap, codes, planned, reqs
from superplanner.mfg.forecast.consume import consume
from superplanner.mfg.forecast.model import ForecastSnap
from superplanner.mfg.mrp import MrpParams, run_mrp
from superplanner.mfg.mrp.model import PlanningSnap, RateSupplySnap
from superplanner.mfg.workdays import WorkCalendar


def _run(snap, **params):
    return run_mrp(snap, MrpParams(**params))


@pytest.mark.req("M8-MRP-01")
def test_forecast_requirements_zones_and_ranks():
    p = Plant(horizon=400)
    p.item("SYR", "make", lead_time_days=2, safety_stock=50)
    ds = p.dataset()
    s = Snap(ds)
    iid = s.iid("SYR")
    s.dem("SYR", 100, D("11-04"))
    cal = WorkCalendar(["mon", "tue", "wed", "thu", "fri"])
    lines = {iid: [(date(2026, 11, 1), 2100.0), (date(2026, 12, 1), 2200.0), (date(2027, 1, 1), 2000.0),
                   (date(2027, 6, 1), 2100.0)]}
    res = consume(lines, [], bucket="m", as_of=AS_OF, is_workday=cal.is_workday, version_id="fcv_x", daily_days=28,
                  weekly_weeks=26)
    snap = replace(s.snapshot(), forecasts=res.snaps, forecast_priority=7, zones=(28, 26))
    out = _run(snap, alternates="never")
    rs = reqs(out, ds, "SYR")
    fc = [r for r in rs if r.kind == "forecast"]
    assert fc and fc[0].rank_label == "P7 Forecast Nov 2026"
    daily_end = date(2026, 11, 30)
    weekly_end = daily_end + timedelta(weeks=26)
    for r in fc:
        if r.need_date < daily_end:
            assert r.need_date.weekday() < 5
        elif r.need_date < weekly_end:
            assert r.need_date.weekday() == 0 or r.need_date == daily_end
        else:
            assert r.need_date.day == 1 or r.need_date == weekly_end
    # ranks: order < forecast (same date) < safety stock
    order = next(r for r in rs if r.kind == "demand")
    fc_same = next(r for r in fc if r.need_date == order.need_date)
    ss = next(r for r in rs if r.kind == "safety_stock")
    assert order.rank < fc_same.rank < ss.rank
    assert sum(r.qty for r in fc) == pytest.approx(sum(x.qty for x in res.snaps))
    # "none" -> no forecast: the run without forecasts has no forecast requirements
    assert not [r for r in reqs(_run(s.snapshot(), alternates="never"), ds, "SYR") if r.kind == "forecast"]


@pytest.mark.req("M8-MRP-02")
def test_pack_rounding_case_multiple():
    p = Plant()
    p.item("NDL", "make", lead_time_days=1)
    ds = p.dataset()
    s = Snap(ds)
    s.dem("NDL", 2300, D("11-20"))
    snap = replace(s.snapshot(), planning={s.iid("NDL"): PlanningSnap(s.iid("NDL"), "mrp", pack_multiple=1000,
                                                                      case_qty=1000, pallet_qty=40000)})
    out = _run(snap, alternates="never")
    assert [po.qty for po in planned(out, ds, "NDL")] == [3000]
    ex = codes(out, "MRP_PACK_ROUNDING")
    assert len(ex) == 1 and ex[0].severity == "info"
    assert out.summary.exceptions["by_code"]["MRP_PACK_ROUNDING"] == 1
    # without M8 inputs no M8 code is listed (M2 results unchanged)
    base = Snap(ds)
    base.dem("NDL", 2300, D("11-20"))
    assert "MRP_PACK_ROUNDING" not in _run(base.snapshot(), alternates="never").summary.exceptions["by_code"]


@pytest.mark.req("M8-MRP-03")
def test_kanban_item_no_planned_order_components_exploded_undersized():
    p = Plant()
    p.item("CLAMP", "make", lead_time_days=2).item("RESIN", "buy", lead_time_days=10)
    p.bom("CLAMP", [("RESIN", 2)])
    ds = p.dataset()
    s = Snap(ds)
    for k in range(20):
        s.dem("CLAMP", 500, D("11-03") + timedelta(days=k), number=f"DO-{k:03d}")
    iid = s.iid("CLAMP")
    snap = replace(s.snapshot(), planning={iid: PlanningSnap(iid, "kanban", kanban_cards=3, kanban_container=1000,
                                                             kanban_lead_days=5)})
    out = _run(snap, alternates="never")
    assert planned(out, ds, "CLAMP") == []
    kinds = {x.kind for x in out.item(iid).supplies}
    assert kinds == {"kanban"}
    assert sum(r.qty for r in reqs(out, ds, "RESIN")) == pytest.approx(2 * 10_000)
    assert planned(out, ds, "RESIN")                   # components are planned from the kanban supply
    assert not codes(out, "MRP_RELEASE_NOW", item="CLAMP") and not codes(out, "MRP_START_IN_PAST", item="CLAMP")
    ex = codes(out, "MRP_KANBAN_UNDERSIZED")
    assert len(ex) == 1 and ex[0].suggested["cards"] > 3
    big = replace(snap, planning={iid: PlanningSnap(iid, "kanban", kanban_cards=20, kanban_container=1000,
                                                    kanban_lead_days=5)})
    assert not codes(_run(big, alternates="never"), "MRP_KANBAN_UNDERSIZED")


@pytest.mark.req("M8-MRP-04")
def test_rate_pass1_buckets_and_pass2_rate_supplies():
    p = Plant()
    p.item("SYR", "make", lead_time_days=1).item("BARREL", "buy", lead_time_days=5)
    p.bom("SYR", [("BARREL", 1)])
    ds = p.dataset()
    s = Snap(ds)
    iid = s.iid("SYR")
    for d in ("11-04", "11-04", "11-05", "12-10", "12-11"):
        s.dem("SYR", 1000, D(d))
    pl = {iid: PlanningSnap(iid, "rate", pack_multiple=None)}
    snap = replace(s.snapshot(), planning=pl)
    p1 = _run(snap, alternates="never", rate_supply=False)
    pos = planned(p1, ds, "SYR")
    # daily zone: one order per day; weekly zone (Dec 10/11, same week bucket from Dec 10): one order
    assert [(po.need_date, po.qty) for po in pos] == [(D("11-04"), 2000), (D("11-05"), 1000), (D("12-10"), 2000)]
    assert not codes(p1, "MRP_RATE_SHORT")
    rs = [RateSupplySnap(iid, D("11-04"), 3000, "rbk_1", "RR-000001 ASM-01", D("11-03")),
          RateSupplySnap(iid, D("12-09"), 1500, "rbk_2", "RR-000001 ASM-01", D("12-08"))]
    p2 = _run(replace(snap, rate_supplies=rs), alternates="never")
    pos2 = planned(p2, ds, "SYR")
    assert [(po.need_date, po.qty) for po in pos2] == [(D("12-11"), 500)]          # rate supplies replace orders
    ex = codes(p2, "MRP_RATE_SHORT")
    assert len(ex) == 1 and ex[0].severity == "critical" and ex[0].qty == 500
    barrel = reqs(p2, ds, "BARREL")
    assert sum(r.qty for r in barrel) == pytest.approx(3000 + 1500 + 500)      # components exploded from rate supplies
