"""Gate 2 #3: hand-calculated checks through the API. T-M1, T-M3, T-M5, T-M6, T-M8, T-M13 are set up by API calls
on a fresh account (`push_plant`), planned with `POST /mrp/runs` at as_of 2026-11-02 (a `what_if` run, since the
date is explicit), and the numbers of M2-DESIGN 8.15 are read back from the run endpoints. Each run is also
compared with the oracle (planned orders + demand projections) so a set-up difference shows immediately.
"""

from __future__ import annotations

import pytest

from accm2_helpers import (assert_run_matches_oracle, demand_req_of, demand_row, mrp_demand, mrp_exceptions,
                           mrp_item, mrp_planned, req_pegs, run_plant, seg)
from oracle import vectors as V


def _setup(api, v):
    maps, run = run_plant(api, v.plant)
    assert run["kind"] == "what_if" and run["as_of"] == "2026-11-02"
    assert_run_matches_oracle(api, run, v.plant, maps)
    return maps, run


def test_tm1_through_the_api(api):
    v = V.tm1()
    maps, run = _setup(api, v)
    c = maps["items"][v.c.id]["id"]
    (p,) = mrp_planned(api, run["id"], item_id=c)
    assert (p["kind"], p["qty"], p["need_date"], p["dock_date"], p["start_date"], p["release_status"]) == \
        ("buy", 50, "2026-11-20", "2026-11-18", "2026-11-08", "release_now")
    plan = mrp_item(api, run["id"], c)
    assert req_pegs(plan, demand_req_of(plan, maps["demand_lines"][v.r1.line_id])) == [("stock", 100), ("po", 20)]
    assert req_pegs(plan, demand_req_of(plan, maps["demand_lines"][v.r2.line_id])) == [("po", 30), ("planned", 50)]
    assert not mrp_exceptions(api, run["id"], code="MRP_EXPEDITE")


def test_tm3_through_the_api(api):
    v = V.tm3()
    maps, run = _setup(api, v)
    item = maps["items"][v.d.id]["id"]
    plan = mrp_item(api, run["id"], item)
    r = demand_req_of(plan, maps["demand_lines"][v.r.line_id])
    assert req_pegs(plan, r) == [("po", 150)] and r["late_days"] == 11
    sched = maps["schedules"][v.po.schedule_id]
    (ex,) = mrp_exceptions(api, run["id"], code="MRP_EXPEDITE")
    assert ex["subject"]["id"] == sched and ex["suggested"]["date"] == "2026-11-20"
    (red,) = mrp_exceptions(api, run["id"], code="MRP_REDUCE")
    assert red["subject"]["id"] == sched and red["suggested"]["qty"] == 150
    (sh,) = mrp_exceptions(api, run["id"], code="MRP_SHORTAGE")
    assert sh["item"]["id"] == item


@pytest.mark.parametrize("holiday,start", [(False, "2026-11-16"), (True, "2026-11-14")])
def test_tm5_through_the_api(api, holiday, start):
    v = V.tm5(holiday=holiday)
    maps, run = _setup(api, v)
    (p,) = mrp_planned(api, run["id"])
    assert (p["kind"], p["need_date"], p["start_date"]) == ("make", "2026-11-20", start)


@pytest.mark.parametrize("allocation", ["priority", "due_date"])
def test_tm6_through_the_api(api, allocation):
    v = V.tm6(allocation)
    maps, run = _setup(api, v)
    rows = mrp_demand(api, run["id"])
    d1 = demand_row(rows, maps["demand_lines"][v.d1.line_id])
    d2 = demand_row(rows, maps["demand_lines"][v.d2.line_id])
    if allocation == "priority":
        assert (d1["late_days"], d2["projected_date"], d2["late_days"]) == (0, "2027-01-31", 72)
        (p,) = mrp_planned(api, run["id"])
        assert (p["qty"], p["release_status"]) == (6, "start_in_past")
    else:
        assert (d2["late_days"], d1["late_days"]) == (0, 62)


def test_tm8_through_the_api(api):
    v = V.tm8()
    maps, run = _setup(api, v)
    e = maps["items"][v.e.id]["id"]
    ps = sorted(mrp_planned(api, run["id"], item_id=e), key=lambda p: seg(p["segment"]))
    assert [(seg(p["segment"]), p["qty"]) for p in ps] == [((101, 105), 5), ((106, 110), 5)]
    for item, qty in ((v.k1, 5), (v.k2, 5)):
        plan = mrp_item(api, run["id"], maps["items"][item.id]["id"])
        assert [r["qty"] for r in plan["requirements"]] == [qty]


def test_tm13_through_the_api(api):
    v = V.tm13()
    maps, run = _setup(api, v)
    row = demand_row(mrp_demand(api, run["id"]), maps["demand_lines"][v.dm.line_id])
    assert (row["projected_date"], row["late_days"], row["status"]) == ("2026-12-09", 5, "late")
    steps = row["limiting"]
    assert [s["item"]["part_number"] for s in steps] == ["P", "C"]
    assert steps[-1]["reason"] == "supply_date"
    (ex,) = [x for x in mrp_exceptions(api, run["id"], code="MRP_DEMAND_LATE")]
    assert ex["days"] == 5 and ex["message"] and ex["link"]


@pytest.mark.parametrize("name", ["T-M2", "T-M4", "T-M7", "T-M7b", "T-M9", "T-M9b", "T-M10", "T-M11", "T-M12"])
def test_other_vectors_through_the_api_match_the_oracle(api, name):
    _setup(api, V.ALL[name]())
