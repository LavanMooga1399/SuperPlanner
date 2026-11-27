"""Network DRP engine and validator (M9-DESIGN 5.3; register M9-NET-01..06, 09, 10). Pure, no database."""

from __future__ import annotations

import copy
from datetime import date, timedelta

import pytest

from superplanner.mfg.network.engine import solve
from superplanner.mfg.network.model import (NetBomLine, NetCap, NetDemand, NetError, NetItem, NetLane, NetLoad,
                                            NetNode, NetProblem, NetRule, NetSupply)
from superplanner.mfg.network.validator import validate

AS_OF = date(2026, 11, 30)          # a Monday
W = [AS_OF + timedelta(days=7 * k) for k in range(8)]
DC, A, B = "usr_dc", "usr_a", "usr_b"
NODES = [NetNode(DC, "DCUS", "dc", "US"), NetNode(A, "QC", "plant", "CA"), NetNode(B, "US1", "plant", "US")]


def lane(i: str, src: str, dst: str, days: int = 0) -> NetLane:
    return NetLane(i, src, dst, "road", days)


def rule(i: str, src: str, prio: int = 1, quota: float | None = None, dest: str = DC, key: str | None = "K",
         family: str | None = None, lane_id: str | None = None) -> NetRule:
    return NetRule(i, dest, key, family, "plant", src, None, prio, quota, lane_id)


def problem(**kw) -> NetProblem:
    base = dict(as_of=AS_OF, horizon_weeks=8, constrained=True, prebuild_weeks=4, firm_days=14, nodes=NODES,
                items=[NetItem(DC, "K", "i_dc"), NetItem(A, "K", "i_a"), NetItem(B, "K", "i_b")],
                lanes=[lane("l_a", A, DC), lane("l_b", B, DC)])
    base.update(kw)
    return NetProblem(**base)


def weekly(node: str, qty: float, n: int = 5, start: int = 1, kind: str = "order") -> list[NetDemand]:
    return [NetDemand(node, "K", W[start + k], qty, kind, f"SO-{k + 1}") for k in range(n)]


def by_src(res) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in res.transfers:
        out[t.src] = out.get(t.src, 0.0) + t.qty
    return out


def ok(p, res):
    rep = validate(p, res)
    assert rep["ok"], rep["violations"]
    return res


@pytest.mark.req("M9-NET-01")
def test_quota_cumulative_arrangement():
    items = [NetItem(DC, "K", "i_dc", order_multiple=100), NetItem(A, "K", "i_a"), NetItem(B, "K", "i_b")]
    p = problem(items=items, demand=weekly(DC, 100), rules=[rule("r_a", A, 1, 60), rule("r_b", B, 2, 40)])
    res = ok(p, solve(p))
    seq = [t.src for t in sorted(res.transfers, key=lambda t: t.receive_date)]
    assert seq == [A, B, A, B, A]
    assert by_src(res) == {A: 300, B: 200}


def test_quota_sum_must_be_100():
    p = problem(demand=weekly(DC, 100), rules=[rule("r_a", A, 1, 60), rule("r_b", B, 2, 30)])
    with pytest.raises(NetError) as e:
        solve(p)
    assert e.value.code == "NET_QUOTA_SUM"


def _cap(node: str, hours: float, weeks=W) -> list[NetCap]:
    return [NetCap(node, "G", w, hours) for w in weeks]


@pytest.mark.req("M9-NET-02")
def test_priority_spill_to_secondary_on_capacity():
    p = problem(demand=weekly(DC, 200, n=3, start=2), rules=[rule("r_a", A, 1), rule("r_b", B, 2)],
                capacity=_cap(A, 150) + _cap(B, 1000), load=[NetLoad(A, "G", "K", 1.0), NetLoad(B, "G", "K", 1.0)],
                prebuild_weeks=0)
    res = ok(p, solve(p))
    assert by_src(res) == {A: 450, B: 150}
    assert all(t.spill for t in res.transfers if t.src == B)
    assert any(e["code"] == "NET_SPILL" for e in res.explanations)
    assert not [s for s in res.shortages if s.detail.get("final")]


@pytest.mark.req("M9-NET-03")
def test_peak_prebuilt_into_spare_weeks():
    dem = [NetDemand(DC, "K", W[5], 400, "order", "SO-PEAK")]
    p = problem(demand=dem, rules=[rule("r_a", A, 1)], capacity=_cap(A, 100), load=[NetLoad(A, "G", "K", 1.0)])
    res = ok(p, solve(p))
    made = sorted((pr.week, pr.qty, pr.prebuilt_from) for pr in res.production if pr.node == A)
    assert sum(q for _w, q, _p in made) == 400 and not res.shortages
    assert all(pb == W[5] for w, _q, pb in made if w != W[5]) and len(made) == 4
    assert all(u.used <= u.available + 1e-6 for u in res.utilisation)


@pytest.mark.req("M9-NET-04")
def test_overload_beyond_prebuild_and_spill_is_cut_and_pegged():
    dem = [NetDemand(DC, "K", W[2], 500, "order", "SO-000123/1")]
    p = problem(demand=dem, rules=[rule("r_a", A, 1)], capacity=_cap(A, 100), load=[NetLoad(A, "G", "K", 1.0)],
                prebuild_weeks=1)
    res = ok(p, solve(p))
    cut = [s for s in res.shortages if s.cause == "NET_CAPACITY_SHORT"]
    at_dc = [s for s in cut if s.node == DC]
    assert at_dc and at_dc[0].detail["final"] and at_dc[0].detail["at"] == A
    assert at_dc[0].detail["pegs"][0]["ref"] == "SO-000123/1"
    assert sum(s.qty for s in at_dc) == 500 - 200
    assert [s for s in cut if s.node == A and not s.detail["final"]]
    assert all(u.used <= u.available + 1e-6 for u in res.utilisation)


@pytest.mark.req("M9-NET-05")
def test_rule_loop_is_refused_with_path():
    rules = [rule("r1", A, 1, dest=DC), rule("r2", DC, 1, dest=A)]
    p = problem(demand=weekly(DC, 10), rules=rules, lanes=[lane("l1", A, DC), lane("l2", DC, A)])
    with pytest.raises(NetError) as e:
        solve(p)
    assert e.value.code == "NET_CYCLE"
    codes = [x["code"] for x in e.value.details["path"]]
    assert codes[0] == codes[-1] and set(codes) == {"DCUS", "QC"}


@pytest.mark.req("M9-NET-06")
def test_transit_working_days_ship_previous_wednesday():
    p = problem(demand=[NetDemand(DC, "K", W[2], 10, "order", "SO-1")], rules=[rule("r_a", A, 1)],
                lanes=[lane("l_a", A, DC, 3)])
    res = ok(p, solve(p))
    t = res.transfers[0]
    assert t.receive_date == W[2] and t.ship_date == W[2] - timedelta(days=5) and t.ship_date.weekday() == 2


def test_lead_time_and_no_source_and_firm_zone():
    p = problem(demand=[NetDemand(DC, "K", W[0], 10, "order", "SO-1"), NetDemand(DC, "K", W[4], 10, "order", "SO-2")],
                rules=[rule("r_a", A, 1)], lanes=[lane("l_a", A, DC, 7)])
    res = ok(p, solve(p))
    late = [s for s in res.shortages if s.cause == "NET_LEAD_TIME"]
    assert late and late[0].week == W[0]
    firm = {t.receive_date: t.firm for t in res.transfers}
    assert firm[W[4]] is False and any(firm.values())
    dc_only = problem(items=[NetItem(DC, "K", "i_dc")], demand=weekly(DC, 5), rules=[rule("r_x", A, 1)])
    res = solve(dc_only)          # rule source has no such item -> not networked there, DC without source
    assert {s.cause for s in res.shortages} == {"NET_NO_SOURCE"}


@pytest.mark.req("M9-NET-09")
def test_pegging_dc_order_through_qc_kit_to_us1_component():
    # DC sells KIT (from QC); QC builds KIT from NDL; NDL comes from US1 (B), which builds it from CAN
    items = [NetItem(DC, "KIT", "i1"), NetItem(A, "KIT", "i2", lead_days=7), NetItem(A, "NDL", "i3"),
             NetItem(B, "NDL", "i4", lead_days=7), NetItem(B, "CAN", "i5", make_buy="buy", lead_days=7)]
    rules = [rule("r1", A, 1, key="KIT"), rule("r2", B, 1, dest=A, key="NDL")]
    p = problem(items=items, rules=rules, lanes=[lane("l1", A, DC, 2), lane("l2", B, A, 4)],
                demand=[NetDemand(DC, "KIT", W[6], 100, "order", "SO-000123/1")],
                bom=[NetBomLine(A, "KIT", "NDL", 2.0), NetBomLine(B, "NDL", "CAN", 0.01)])
    res = ok(p, solve(p))
    kinds = {(x.node, x.key, x.kind) for x in res.production}
    assert {(A, "KIT", "make"), (B, "NDL", "make"), (B, "CAN", "buy")} <= kinds
    assert {(t.src, t.dst, t.key) for t in res.transfers} == {(A, DC, "KIT"), (B, A, "NDL")}
    for o in [*res.transfers, *res.production]:
        assert [pg.ref for pg in o.pegs] == ["SO-000123/1"], (o, o.pegs)
    can = [x for x in res.production if x.key == "CAN"][0]
    assert can.qty == pytest.approx(2.0)


@pytest.mark.req("M9-NET-10")
def test_validator_detects_mutations():
    p = problem(demand=weekly(DC, 200, n=3, start=2), rules=[rule("r_a", A, 1), rule("r_b", B, 2)],
                capacity=_cap(A, 150) + _cap(B, 1000), load=[NetLoad(A, "G", "K", 1.0), NetLoad(B, "G", "K", 1.0)],
                prebuild_weeks=0, supply=[NetSupply(DC, "K", W[0], 50, "stock", "BAL")])
    res = ok(p, solve(p))

    def bad(mut) -> set[str]:
        r = copy.deepcopy(res)
        mut(r)
        return {x["code"] for x in validate(p, r)["violations"]}

    def cap(r):
        pr = [x for x in r.production if x.node == A][0]
        pr.qty += 10
        for t in r.transfers:
            if t.src == A and t.receive_date >= pr.week:
                t.qty += 10
                for pg in t.pegs[:1]:
                    pg.qty += 10
                break
        pr.pegs[0].qty += 10

    def balance(r):
        r.projection[3].projected += 5

    def lane_(r):
        r.transfers[0].lane_id = "nope"

    def pegs(r):
        r.transfers[0].pegs[0].qty += 1

    def transit(r):
        r.transfers[0].receive_date += timedelta(days=1)

    assert "NET_V_CAPACITY" in bad(cap)
    assert "NET_V_BALANCE" in bad(balance)
    assert "NET_V_LANE" in bad(lane_)
    assert "NET_V_PEGS" in bad(pegs)
    assert "NET_V_TRANSIT" in bad(transit)


def test_unconstrained_reports_load_only_and_family_rule():
    items = [NetItem(DC, "K", "i_dc", family="F"), NetItem(A, "K", "i_a")]
    p = problem(items=items, constrained=False, demand=weekly(DC, 300, n=2, start=2),
                rules=[rule("r_f", A, 1, key=None, family="F")], capacity=_cap(A, 100),
                load=[NetLoad(A, "G", "K", 1.0)])
    res = ok(p, solve(p))
    assert by_src(res) == {A: 600} and not res.shortages
    assert max(u.used / u.available for u in res.utilisation) == pytest.approx(3.0)
    assert res.kpis["fill_rate"] == 1.0
