"""S&OP demand review, curves, LP tiers, validator and finance (M9-DESIGN 6; register M9-SOP-01..06, 09, 10 and
M9-TRD-09). Pure, no database."""

from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from superplanner.mfg.sop import curves, demand, finance, lp
from superplanner.mfg.sop.model import SopBuy, SopLane, SopProblem
from superplanner.mfg.sop.validator import validate
from superplanner.mfg.trade.fx import FxTable

M = [date(2027, 1, 1), date(2027, 2, 1), date(2027, 3, 1)]


def problem(**kw) -> SopProblem:
    base = dict(months=M, nodes=["P"], families=["F"], demand={("P", "F", m): 1000.0 for m in M},
                priority_weight={}, init_inv={}, ss_target={}, hours={}, hpu={}, make_allowed=frozenset(),
                conv_cost={}, std_cost={("P", "F"): 2.0})
    base.update(kw)
    return SopProblem(**base)


def solve_ok(p: SopProblem):
    r = lp.solve(p)
    assert r.status == "optimal"
    rep = validate(p, r)
    assert rep["ok"], rep["violations"]
    return r


@pytest.mark.req("M9-SOP-01")
def test_overrides_all_nodes_pct_then_node_abs():
    jan = M[0]
    base = {("QC", "SYR", jan): 4000.0, ("DC", "SYR", jan): 6000.0}
    ovr = [{"node_owner_id": None, "family": "SYR", "month_from": jan, "month_to": jan, "mode": "pct", "value": 10,
            "seq": 1},
           {"node_owner_id": "QC", "family": "SYR", "month_from": jan, "month_to": jan, "mode": "abs", "value": 5000,
            "seq": 2}]
    assert demand.apply_overrides(base, ovr) == {("QC", "SYR", jan): 5000.0, ("DC", "SYR", jan): 6600.0}
    split = demand.apply_overrides(base, [{"node_owner_id": None, "family": "SYR", "month_from": jan,
                                           "month_to": jan, "mode": "abs", "value": 20000, "seq": 1}])
    assert split == {("QC", "SYR", jan): 8000.0, ("DC", "SYR", jan): 12000.0}
    rows = demand.aggregate([{"node": "QC", "family": "SYR", "item_key": "A", "month": jan, "stat": 100, "order": 150},
                             {"node": "QC", "family": "SYR", "item_key": "B", "month": jan, "stat": 80, "order": 20}])
    r = rows[("QC", "SYR", jan)]
    assert (r["stat_qty"], r["order_qty"], r["base_qty"]) == (180, 170, 230)


@pytest.mark.req("M9-SOP-02")
def test_two_sources_ample_capacity_cheaper_landed_wins():
    p = problem(nodes=["P", "DC"], demand={("DC", "F", m): 1000.0 for m in M}, std_cost={("P", "F"): 2.0,
                                                                                       ("DC", "F"): 2.0},
                make_allowed=frozenset({("P", "F")}), conv_cost={("P", "F"): 1.0},
                hours={("P", "G", m): 1e6 for m in M}, hpu={("P", "G", "F"): 0.01},
                lanes=[SopLane("L", "P", "DC", 0, 0.1)], buys=[SopBuy("DC", "F", "B", 0.5)])
    r = solve_ok(p)
    assert sum(r.unmet.values()) == 0
    assert sum(q for k, q in r.buy.items() if k[2] == "B") == 3000 and not r.make


@pytest.mark.req("M9-SOP-03")
def test_capacity_short_unmet_is_tier_one_never_traded_for_cost():
    p = problem(make_allowed=frozenset({("P", "F")}), conv_cost={("P", "F"): 1e6},
                hours={("P", "G", m): 600.0 for m in M}, hpu={("P", "G", "F"): 1.0})
    r = solve_ok(p)
    assert sum(r.make.values()) == 1800 and sum(r.unmet.values()) == pytest.approx(1200)
    assert {e["code"] for e in r.explanations} == {"SOP_CAPACITY"}


@pytest.mark.req("M9-SOP-04")
def test_ramp_curve_week_two_and_march_factor():
    pts = [{"week": 0, "rate_pct": 20, "yield_pct": 100}, {"week": 4, "rate_pct": 60, "yield_pct": 100},
           {"week": 8, "rate_pct": 100, "yield_pct": 100}]
    start = date(2027, 3, 1)
    assert curves.daily_factor(pts, start, start + timedelta(days=14))[0] == pytest.approx(0.40)

    def hand(d: date) -> float:      # the curve by hand: +10 % per week to week 4, then +10 % per week to week 8
        w = (d - start).days / 7
        return 0.2 + 0.1 * w if w <= 4 else min(0.6 + 0.1 * (w - 4), 1.0)
    days = [start + timedelta(days=k) for k in range(31) if (start + timedelta(days=k)).weekday() < 5]
    assert len(days) == 23
    assert curves.month_factor(pts, start, date(2027, 3, 1)) == pytest.approx(sum(hand(d) for d in days) / 23)
    assert curves.month_factor(pts, start, date(2027, 2, 1)) == 0.0
    assert curves.month_factor(pts, start, date(2027, 6, 1)) == 1.0


@pytest.mark.req("M9-SOP-05")
def test_yield_reduces_good_output():
    f = curves.month_factor([{"week": 0, "rate_pct": 100, "yield_pct": 90}], date(2026, 1, 5), M[0])
    assert f == pytest.approx(0.9)
    p = problem(make_allowed=frozenset({("P", "F")}), conv_cost={("P", "F"): 1.0},
                hours={("P", "G", m): 500.0 * f for m in M}, hpu={("P", "G", "F"): 1.0})
    r = solve_ok(p)
    assert r.make[("P", "F", M[0])] == 450


@pytest.mark.req("M9-SOP-06")
def test_revenue_in_report_currency():
    fx = FxTable([("CAD", "USD", M[0], 0.72)])
    rate, flags = fx.rate("CAD", "USD", M[0])
    p = problem(months=[M[0]], demand={("P", "F", M[0]): 1000.0}, init_inv={("P", "F"): 1000.0})
    r = solve_ok(p)
    rows = finance.cells(p, r, {("P", "F"): 2.00 * rate}, [])
    assert rows[0]["revenue"] == pytest.approx(1440.0) and not flags


@pytest.mark.req("M9-SOP-09")
def test_disaggregation_pro_rata_to_finals_else_history():
    q, err = demand.disaggregate(1200, {"A": 600, "B": 300, "C": 100})
    assert q == {"A": 720, "B": 360, "C": 120} and err is None
    q, err = demand.disaggregate(100, {"A": 0}, {"A": 30, "B": 10})
    assert q == {"A": 75, "B": 25}
    assert demand.disaggregate(100, {"A": 0}, {}) == ({}, "SOP_DISAGG_NONE")


@pytest.mark.req("M9-SOP-10")
def test_enforced_milestone_limits_supply_to_domestic():
    buys = [SopBuy("P", "F", "DOM", 2.0, 300.0, domestic=1.0), SopBuy("P", "F", "CN", 0.5, None, domestic=0.0)]
    p = problem(buys=buys, milestones=[{"family": "F", "min_share": 1.0}])
    r = solve_ok(p)
    assert sum(q for k, q in r.buy.items() if k[2] == "CN") == 0
    assert sum(r.unmet.values()) == pytest.approx(2100)
    assert {e["code"] for e in r.explanations} == {"SOP_MILESTONE"}
    free = solve_ok(problem(buys=buys))
    assert sum(free.unmet.values()) == 0


@pytest.mark.req("M9-TRD-09")
def test_make_vs_buy_buys_up_to_cap_and_makes_the_rest():
    p = problem(months=[M[0]], demand={("P", "F", M[0]): 1000.0}, make_allowed=frozenset({("P", "F")}),
                conv_cost={("P", "F"): 2.0}, hours={("P", "G", M[0]): 800.0}, hpu={("P", "G", "F"): 1.0},
                buys=[SopBuy("P", "F", "S", 1.0, 600.0)])
    r = solve_ok(p)
    assert r.buy[("P", "F", "S", M[0])] == 600 and r.make[("P", "F", M[0])] == 400


def test_lp_shares_safety_stock_tier_and_validator_mutations():
    buys = [SopBuy("P", "F", "A", 1.0, min_share=0.6, max_share=0.6), SopBuy("P", "F", "B", 0.8, min_share=0.4,
                                                                            max_share=0.4)]
    p = problem(buys=buys, ss_target={("P", "F"): 200.0})
    r = solve_ok(p)
    a = sum(q for k, q in r.buy.items() if k[2] == "A")
    b = sum(q for k, q in r.buy.items() if k[2] == "B")
    assert a == pytest.approx(0.6 * (a + b), abs=3) and sum(r.ss_short.values()) <= 1 and not r.unmet
    bad = copy.deepcopy(r)
    bad.inv[("P", "F", M[1])] += 10
    assert "SOP_V_BALANCE" in {x["code"] for x in validate(p, bad)["violations"]}
    p2 = problem(make_allowed=frozenset({("P", "F")}), conv_cost={("P", "F"): 1.0},
                 hours={("P", "G", m): 600.0 for m in M}, hpu={("P", "G", "F"): 1.0})
    r2 = solve_ok(p2)
    bad = copy.deepcopy(r2)
    bad.make[("P", "F", M[0])] += 50
    bad.inv[("P", "F", M[0])] += 50
    assert "SOP_V_CAPACITY" in {x["code"] for x in validate(p2, bad)["violations"]}
    # review m7: make where not allowed, an unknown supplier, an SS shortfall not reported
    bad = copy.deepcopy(r)
    bad.make[("P", "F", M[0])] = 5.0
    bad.buy[("P", "F", "ZZ", M[1])] = 5.0
    bad.ss_short = {}
    bad.inv = {k: 0.0 for k in bad.inv}
    codes = {x["code"] for x in validate(p, bad)["violations"]}
    assert {"SOP_V_MAKE", "SOP_V_BUY", "SOP_V_SS"} <= codes


def test_missing_fx_drops_make_and_lane_options():
    """Review m4: a cost that cannot be converted is never 0 - the option is dropped and reported."""
    from superplanner.mfg.sop.scenario import build_problem
    from superplanner.mfg.trade.fx import FxTable as FX

    m = [date(2027, 1, 1)]
    node = {"info": {"code": "JP1", "kind": "plant"}, "items": {"i1": {"id": "i1", "key": "K", "family": "F",
                                                                       "make_buy": "make", "std_cost": 5.0,
                                                                       "ss": 0.0, "part_number": "K"}},
            "stock": {}, "isp": [], "material": {}, "hours": {}, "hpu": {}, "currency": "JPY", "country": "JP",
            "workdays": (0, 1, 2, 3, 4)}
    dc = {"info": {"code": "DC", "kind": "dc"}, "items": {"i2": {"id": "i2", "key": "K", "family": "F",
                                                                 "make_buy": "buy", "std_cost": 5.0, "ss": 0.0,
                                                                 "part_number": "K"}},
          "stock": {}, "isp": [], "material": {}, "hours": {}, "hpu": {}, "currency": "USD", "country": "US",
          "workdays": (0, 1, 2, 3, 4)}
    p, meta = build_problem(months=m, nodes={"jp": node, "dc": dc}, demand={("dc", "F", m[0]): 10.0}, orders={},
                            lanes=[{"id": "L", "src": "jp", "dst": "dc", "transit_days": 5, "freight_per_unit": 1.0,
                                    "currency": "JPY", "active": True}],
                            rules=[{"id": "r", "dest": "dc", "key": None, "family": "F", "source_kind": "plant",
                                    "source": "jp", "supplier_code": None, "priority": 1}],
                            settings={"report_currency": "USD"}, fx=FX(), tariffs=[], curves_by_code={},
                            milestones=[], changes=[], enforce=False)
    codes = {w["code"] for w in meta["warnings"]}
    assert ("jp", "F") not in p.make_allowed and not p.lanes
    assert {"SOP_MAKE_DROPPED", "SOP_LANE_DROPPED", "FX_MISSING"} <= codes
