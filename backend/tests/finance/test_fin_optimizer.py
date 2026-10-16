"""LP semantics, honest infeasibility, exact published lines and MILP mode (acceptance 1.8-1.12).

Every test checks the result with the independent validator (`assert_clean`), regardless of `result.violations`.
"""

import time

import pytest

from fin_helpers import (assert_clean, expense, goal, income, load_fixture, plan, run, zero_assumptions, zero_classes,
                         zplan)
from superplanner.finance import get_template, project_cashflow, validate_result
from superplanner.finance.optimizer import FinanceLP
from superplanner.finance.pipeline import publish
from superplanner.finance.returns import annuity_due, initial_z, real_annual
from superplanner.finance.model import AssetClass


def _lines(r, gid, cls=None):
    return [ln for ln in r.contributions if ln.goal_id == gid and (cls is None or ln.asset_class_id == cls)]


def test_single_goal_level_amount_equals_target_over_phi():
    p = load_fixture("single_goal.finance.json")
    r = run(p)
    assert_clean(p, r)
    assert r.feasibility == "feasible"
    ac = AssetClass(id="debt", name="Debt", category="debt", expected_return_pct=8.0, volatility_pct=0.0)
    rho = (1 + real_annual(ac, 0.06)) ** (1 / 12)
    expected = 100000 / annuity_due(rho, 24)
    lines = _lines(r, "g1")
    assert lines and all(ln.asset_class_id == "debt" for ln in lines)
    for ln in lines:
        assert ln.monthly_amount_real == pytest.approx(expected, rel=1e-3)
    assert lines[0].start_month == "2026-11" and lines[-1].end_month == "2028-10"
    assert r.goals[0].shortfall_real <= 1.0


def _cash_short(prio2: str):
    return zplan(incomes=[income(amount=2000)], expenses=[expense(amount=1000)],
                 goals=[goal("a", 12000, "2027-11", priority="must"), goal("b", 12000, "2027-11", priority=prio2)])


def test_must_beats_nice_when_cash_is_short():
    p = _cash_short("nice")
    r = run(p)
    assert_clean(p, r)
    g = {x.goal_id: x for x in r.goals}
    assert g["a"].shortfall_real <= 1.0
    assert g["b"].shortfall_real == pytest.approx(12000, abs=2.0)


def test_minimax_splits_shortfall_between_equal_must_goals():
    p = _cash_short("must")
    r = run(p)
    assert_clean(p, r)
    g = {x.goal_id: x for x in r.goals}
    assert g["a"].shortfall_fraction == pytest.approx(0.5, abs=0.01)
    assert g["a"].shortfall_fraction == pytest.approx(g["b"].shortfall_fraction, abs=0.01)


def test_ef_gating_and_block_split_at_t_E():
    p = zplan(emergency_fund=dict(months_of_essentials=5, asset_class_id="safe"), incomes=[income(amount=2000)],
              expenses=[expense(amount=1000)], goals=[goal("car", 7000, "2027-11", priority="should")])
    proj = project_cashflow(p)
    assert proj.ef_complete_index == 5
    r = run(p)
    assert_clean(p, r)
    lines = _lines(r, "car")
    assert lines and min(ln.start_month for ln in lines) == "2027-04"          # paid from t_E = 5 inside block 0
    assert r.goals[0].shortfall_real <= 1.0
    must = zplan(emergency_fund=dict(months_of_essentials=5, asset_class_id="safe"), incomes=[income(amount=2000)],
                 expenses=[expense(amount=1000)], goals=[goal("car", 1000, "2027-11", priority="must")])
    rm = run(must)
    assert_clean(must, rm)


def test_lockin_class_never_used_when_it_matures_after_goal():
    classes = zero_classes(lock={"expected_return_pct": 10.0})
    for months, month, used in ((12, "2027-11", False), (60, "2031-11", True)):
        p = zplan(assumptions=zero_assumptions(classes), incomes=[income(amount=3000)], expenses=[expense()],
                  goals=[goal("g", 20000, month, priority="must")])
        r = run(p)
        assert_clean(p, r)
        lock_lines = _lines(r, "g", "lock")
        assert bool(lock_lines) is used
        from superplanner.finance import timegrid as tg
        for ln in lock_lines:
            assert tg.month_index(p.start_month, ln.end_month) + 24 <= months


def _growth_plan(**kw):
    classes = [dict(id="cash", name="Cash", category="cash", expected_return_pct=6.0, volatility_pct=0.0),
               dict(id="safe", name="Safe", category="debt", expected_return_pct=6.0, volatility_pct=0.0,
                    liquidity_days=2),
               dict(id="eq", name="Equity", category="equity", expected_return_pct=14.0, volatility_pct=0.0)]
    a = dict(inflation_pct=6.0, inflation_volatility_pct=0.0, cash_class_id="cash", asset_classes=classes,
             correlations=[])
    doc = dict(assumptions=a, emergency_fund=dict(months_of_essentials=0, asset_class_id="safe"),
               incomes=[income(amount=60000)], expenses=[expense(amount=20000)],
               profile=dict(risk_tolerance=5), goals=[goal("g", 2_000_000, "2036-11", priority="must")])
    doc.update(kw)
    return plan(**doc)


def test_glide_cap_binds_and_rebalance_sells_risky():
    p = _growth_plan()
    r = run(p)
    assert_clean(p, r)
    sells = [rb for rb in r.rebalances if rb.sells.get("eq", 0) > 0]
    assert sells, "the glide path must sell equity as the goal approaches"
    pts = r.glide_paths["g"]
    assert any(pt.risky_share_pct >= pt.risky_cap_pct - 0.5 and pt.risky_cap_pct > 0 for pt in pts)
    for pt in pts:
        assert pt.risky_share_pct <= pt.risky_cap_pct + 0.5
    assert pts[-1].months_to_goal == 12 and pts[-1].risky_cap_pct == pytest.approx(18.0)   # 90 % x glide(12) 0.2
    assert any(rs.code == "GLIDE_DOWN" for rs in r.explanation.goals["g"].reasons)


def test_global_equity_cap_respected():
    p = _growth_plan(constraints=dict(max_equity_pct=30))
    r = run(p)
    assert_clean(p, r)
    for pt in r.glide_paths["g"]:
        assert pt.weights_pct.get("eq", 0.0) <= 30.5


def test_locked_holding_never_sold_and_locked_risky_earmark_in_final_block():
    """The earmarked equity is sell-only (goal allows only safe classes) and locked: never sold while locked.
    With the lock ending inside the final glide block (cap 0) the plan still solves [R8]."""
    for lock, sold_at in (("2030-11", "2030-11"), ("2031-05", None)):
        p = _growth_plan(profile=dict(risk_tolerance=1),
                         holdings=[dict(id="h", name="Shares", asset_class_id="eq", amount=300000,
                                        locked_until_month=lock)],
                         goals=[goal("g", 1_000_000, "2031-11", priority="must", allowed_asset_class_ids=["safe"],
                                     earmarked=[dict(holding_id="h", amount=300000)])])
        r = run(p)
        assert_clean(p, r)
        assert r.feasibility == "feasible"
        eq_sells = [rb.month for rb in r.rebalances if rb.sells.get("eq", 0.0) > 0]
        assert all(m >= lock for m in eq_sells)
        assert eq_sells[:1] == ([sold_at] if sold_at else [])


def test_earmark_in_non_allowed_class_is_sold_never_bought():
    p = _growth_plan(holdings=[dict(id="h", name="Shares", asset_class_id="eq", amount=50000)],
                     goals=[goal("g", 500000, "2031-11", priority="must", allowed_asset_class_ids=["safe"],
                                 earmarked=[dict(holding_id="h", amount=50000)])])
    r = run(p)
    assert_clean(p, r)
    assert sum(rb.sells.get("eq", 0.0) for rb in r.rebalances) > 0
    assert all("eq" not in rb.buys for rb in r.rebalances)
    assert not _lines(r, "g", "eq")
    last = r.glide_paths["g"][-1]
    assert last.weights_pct.get("eq", 0.0) <= last.risky_cap_pct + 0.5


def _deficit_plan(**kw):
    doc = dict(incomes=[income(amount=1000)], expenses=[expense(amount=1000)],
               one_offs=[dict(id="o", name="Repair", month="2027-03", amount=5000)],
               goals=[goal("g", 1000, "2027-11", priority="must")])
    doc.update(kw)
    return zplan(**doc)


def test_honest_infeasibility_and_selling_holdings_fixes_it():
    p = _deficit_plan()
    r = run(p)
    assert r.feasibility == "infeasible"
    assert r.diagnostics.cash_deficit_real == pytest.approx(5000.0, abs=1.0)     # zero-contribution deficit
    assert {v.code for v in validate_result(p, r) if v.severity == "hard"} == {"CASH_NEGATIVE"}
    assert any(b.code == "CASH_DEFICIT" for b in r.explanation.binding_constraints)
    p2 = _deficit_plan(holdings=[dict(id="h", name="Shares", asset_class_id="eq", amount=20000)])
    r2 = run(p2)
    assert_clean(p2, r2)
    assert r2.feasibility == "feasible"
    sold = [a for a in r2.holdings_assignment if a.source == "sold_to_cash"]
    assert sold and sum(a.amount for a in sold) >= 5000
    per = {}
    for a in r2.holdings_assignment:
        per[a.holding_id] = per.get(a.holding_id, 0) + a.amount
    assert per == {"h": pytest.approx(20000)}                                  # rows partition the holding [R26]


def test_locked_holding_cannot_rescue_cash():
    p = _deficit_plan(holdings=[dict(id="h", name="Shares", asset_class_id="eq", amount=20000,
                                     locked_until_month="2028-01")])
    r = run(p)
    assert r.feasibility == "infeasible"
    assert {v.code for v in validate_result(p, r) if v.severity == "hard"} == {"CASH_NEGATIVE"}
    assert not [a for a in r.holdings_assignment if a.source == "sold_to_cash"]


@pytest.mark.parametrize("tid", ["young_professional", "family", "near_retirement"])
def test_published_lines_are_exact(tid):
    p = get_template(tid).build(name="t", start_month="2026-11")
    proj = project_cashflow(p)
    z = {g.id: initial_z(g) for g in p.goals if g.enabled}
    sol = FinanceLP(p, proj, z).lexicographic(time.monotonic() + 30)
    pub = publish(p, proj, sol, z)
    for ln in pub.lines:
        assert round(ln.monthly_amount_real, 2) == ln.monthly_amount_real
        if ln.goal_id != "emergency_fund":
            assert ln.monthly_amount_real > 0
    for (g, a, k), v in sol.x.items():
        p0, _ = sol.x_pay[(g, a, k)]
        published = pub.x_month[g].get(a, {}).get(p0, 0.0)
        assert published <= v + 1e-9
    # recompute plan-basis values month by month from the published lines (independent of the pipeline)
    r = run(p)
    assert_clean(p, r)
    _recompute_matches(p, r)


def _recompute_matches(p, r):
    from superplanner.finance import timegrid as tg
    from superplanner.finance.returns import inflation_vol, pi_general, planning_rho

    classes = {a.id: a for a in p.assumptions.asset_classes}
    holdings = {h.id: h for h in p.holdings}
    L = p.constraints.contribution_block_months
    for gr in r.goals:
        g = next(x for x in p.goals if x.id == gr.goal_id)
        D = tg.month_index(p.start_month, g.target_month)
        rho = {a: planning_rho(ac, pi_general(p), gr.planning_z, D, inflation_vol(p)) for a, ac in classes.items()}
        val = {a: 0.0 for a in classes}
        for row in r.holdings_assignment:
            if row.goal_id == g.id and row.source in ("earmark", "assigned"):
                val[holdings[row.holding_id].asset_class_id] += row.amount
        for t in range(D):
            if t % L == 0:
                for rb in r.rebalances:
                    if rb.goal_id == g.id and rb.month == tg.add_months(p.start_month, t):
                        for a, v in rb.sells.items():
                            val[a] -= v
                        for a, v in rb.buys.items():
                            val[a] += v
            for ln in r.contributions:
                if ln.goal_id == g.id and ln.start_month <= tg.add_months(p.start_month, t) <= ln.end_month:
                    val[ln.asset_class_id] += ln.monthly_amount_real
            for a in val:
                val[a] *= rho[a]
        assert sum(val.values()) == pytest.approx(gr.planned_value_real, abs=0.01 + 1e-9 * gr.target_real)


def test_milp_minimum_contribution():
    classes = zero_classes(safe={"min_monthly_contribution": 5000})
    p = zplan(assumptions=zero_assumptions(classes), incomes=[income(amount=20000)], expenses=[expense(amount=10000)],
              goals=[goal("g", 60000, "2028-11", priority="must", allowed_asset_class_ids=["safe", "eq"])])
    r = run(p)
    assert_clean(p, r)
    assert r.diagnostics.solver == "SCIP"
    safe = _lines(r, "g", "safe")
    assert safe
    for ln in safe:
        assert ln.monthly_amount_real == 0 or ln.monthly_amount_real >= 5000
    assert r.goals[0].shortfall_real <= 60.0


@pytest.mark.slow
def test_milp_too_many_binaries_falls_back_to_glop():
    classes = zero_classes(safe={"min_monthly_contribution": 100}, eq={"min_monthly_contribution": 100})
    goals = []
    for i in range(12):
        goals.append(goal(f"g{i}", 100000 + i, "2076-09", priority="must"))
    p = zplan(assumptions=zero_assumptions(classes), incomes=[income(amount=20000)], expenses=[expense(amount=10000)],
              goals=goals, constraints=dict(contribution_block_months=6))
    r = run(p)
    assert_clean(p, r)
    assert r.diagnostics.solver == "GLOP"
    assert "MIN_CONTRIBUTION_IGNORED" in r.diagnostics.warnings
