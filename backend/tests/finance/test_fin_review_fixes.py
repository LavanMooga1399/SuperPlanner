"""Regression tests for the review defects fixed after F4 (flooring headroom, joint caps, templates, result seed,
REDUCE_TARGET amount, validator holding/rebalance checks)."""

import pytest

from fin_helpers import expense, goal, hand_result, income, plan, run, zero_assumptions, zero_classes, zplan
from superplanner.finance import get_template, preflight, validate_result
from superplanner.finance.advisor.messages import format_money
from superplanner.finance.returns import active_caps


def hard_codes(p, r):
    return {v.code for v in validate_result(p, r) if v.severity == "hard"}


# ------------------------------------------------------------------ flooring headroom (defect 1)

def test_min_contribution_zero_surplus_plan_stays_feasible():
    classes = zero_classes(eq={"min_monthly_contribution": 2000})
    p = zplan(assumptions=zero_assumptions(classes), incomes=[income(amount=1000)], expenses=[expense(amount=1000)],
              goals=[goal(priority="must", target=50000, month="2030-11", allowed_asset_class_ids=["eq"])])
    r = run(p)
    assert r.diagnostics.cash_deficit_real <= 1.0
    assert r.feasibility == "feasible", [v.code for v in r.violations]
    assert not [ln for ln in r.contributions if ln.goal_id == "g1"]


def test_unfunded_nice_goal_gets_no_micro_contributions():
    # PHASE2 1.8 made the template affordable; a lower take-home pay keeps retirement short of cash
    p = get_template("near_retirement").build(name="x", start_month="2026-11",
                                              params={"wedding_in_years": 1, "take_home": 120000})
    r = run(p)
    goals = {g.goal_id: g for g in r.goals}
    assert goals["retirement"].shortfall_fraction > 0.1
    assert not [ln for ln in r.contributions if ln.goal_id == "wedding"]


# ------------------------------------------------------------------ joint caps (defect 2)

def test_active_caps_conflicting_caps_keep_equity_cap_and_drop_class_cap():
    p = zplan(goals=[goal(priority="must", month="2029-11", allowed_asset_class_ids=["safe", "eq"])],
              constraints={"max_equity_pct": 0, "max_class_pct": {"safe": 40}})
    act = active_caps(p, p.goals[0], 36, 0)
    assert act.equity is True and act.classes == frozenset()


def test_active_caps_independent_caps_both_bind_when_a_free_class_exists():
    p = zplan(goals=[goal(priority="must", month="2029-11", allowed_asset_class_ids=["safe", "eq", "cash"])],
              constraints={"max_equity_pct": 0, "max_class_pct": {"safe": 40}})
    act = active_caps(p, p.goals[0], 36, 0)
    assert act.equity is True and act.classes == frozenset({"safe"})


def test_conflicting_caps_give_a_clean_plan_without_bucket_churn():
    p = zplan(incomes=[income(amount=2000)], expenses=[expense(amount=1000)],
              goals=[goal(priority="must", target=20000, month="2029-11", allowed_asset_class_ids=["safe", "eq"])],
              constraints={"max_equity_pct": 0, "max_class_pct": {"safe": 40}})
    r = run(p)
    assert r.feasibility == "feasible"
    assert not [v for v in validate_result(p, r) if v.severity == "hard"]
    assert not [ln for ln in r.contributions if ln.asset_class_id == "eq"]
    assert all(sum(rb.buys.values()) > 0 for rb in r.rebalances)


# ------------------------------------------------------------------ templates (defects 3, 7)

@pytest.mark.parametrize("years", [3, 9])
def test_family_short_education_horizon_passes_preflight(years):
    p = get_template("family").build(name="x", start_month="2026-11", params={"education_in_years": years})
    rep = preflight(p)
    assert rep.ok, [i.message for i in rep.issues if i.severity == "error"]
    edu = next(g for g in p.goals if g.id == "education")
    assert edu.earmarked == []


def test_family_long_education_horizon_keeps_the_earmark():
    p = get_template("family").build(name="x", start_month="2026-11", params={"education_in_years": 10})
    assert preflight(p).ok
    assert [e.holding_id for e in next(g for g in p.goals if g.id == "education").earmarked] == ["h_ppf"]


@pytest.mark.parametrize("tid,age,ret", [("near_retirement", 65, 50), ("near_retirement", 55, 55),
                                         ("family", 50, 45)])
def test_retirement_age_not_after_age_is_rejected(tid, age, ret):
    with pytest.raises(ValueError, match="retirement_age"):
        get_template(tid).build(name="x", start_month="2026-11", params={"age": age, "retirement_age": ret})


def test_retirement_one_year_after_age_is_accepted():
    p = get_template("near_retirement").build(name="x", start_month="2026-11",
                                              params={"age": 59, "retirement_age": 60})
    assert next(g for g in p.goals if g.id == "retirement").target_month == "2027-11"


# ------------------------------------------------------------------ result seed (defect 4)

def test_simulation_settings_record_the_seed():
    p = zplan(incomes=[income(amount=2000)], expenses=[expense(amount=1000)], goals=[goal(priority="must")])
    r = run(p, seed=7)
    d = r.model_dump(mode="json")["simulation_settings"]
    assert d["seed"] == 7 and d["n_paths"] == 200 and "income_interruption" in d


# ------------------------------------------------------------------ REDUCE_TARGET amount (defect 5)

def test_reduce_target_amount_matches_new_target_with_goal_inflation():
    p = plan(incomes=[income(amount=20000)], expenses=[expense(amount=15000)],
             goals=[goal(priority="must", target=600000, month="2029-11", inflation_pct=12.0)])
    r = run(p, compute_fixes=True)
    gid = r.goals[0].goal_id
    gr = r.goals[0]
    assert gr.shortfall_real > 0 and abs(gr.target_real - 600000) > 1000
    fix = next(f for f in r.explanation.goals[gid].fixes if f.kind == "REDUCE_TARGET")
    new = fix.what_if.goal_overrides[0].target_amount
    assert fix.amount == pytest.approx(600000 - new, abs=0.01)
    assert format_money(fix.amount, p.profile.currency) in fix.message
    assert format_money(new, p.profile.currency) in fix.message


# ------------------------------------------------------------------ validator (defect 6)

def _vp(**kw):
    doc = dict(incomes=[income(amount=2000)], expenses=[expense(amount=1000)], goals=[goal(priority="must")])
    doc.update(kw)
    return zplan(**doc)


def test_assigned_row_locked_past_goal_and_class_not_allowed():
    p = _vp(holdings=[dict(id="h1", name="Shares", asset_class_id="eq", amount=12000,
                           locked_until_month="2030-11")],
            goals=[goal(priority="must", allowed_asset_class_ids=["safe"])])
    r = hand_result(p, rows=[("h1", "g1", 12000, "assigned")], goals={"g1": dict(planned_value_real=12000)})
    hc = hard_codes(p, r)
    assert {"LOCKIN_PAST_GOAL", "CLASS_NOT_ALLOWED"} <= hc


def test_assigned_row_from_non_pool_money_and_unknown_goal():
    # all of h_cash is the initial cash buffer, so it cannot also be assigned to the goal
    p = _vp(holdings=[dict(id="hc", name="Savings", asset_class_id="cash", amount=5000),
                      dict(id="hs", name="Deposit", asset_class_id="safe", amount=1000)])
    r = hand_result(p, rows=[("hc", "cash_buffer", 5000, "initial_cash"), ("hc", "g1", 3000, "assigned"),
                             ("hs", "nogoal", 1000, "assigned")],
                    goals={"g1": dict(planned_value_real=12000)})
    vs = [v for v in validate_result(p, r) if v.code == "HOLDING_NOT_ASSIGNABLE"]
    assert {v.details["holding_id"] for v in vs} == {"hc", "hs"}


def test_split_rows_must_match_the_validators_projection():
    p = _vp(holdings=[dict(id="hc", name="Savings", asset_class_id="cash", amount=5000)])
    ok = hand_result(p, lines=[("g1", "safe", "2026-11", "2027-10", 1000.0)],
                     rows=[("hc", "cash_buffer", 5000, "initial_cash")], goals={"g1": dict(planned_value_real=12000)})
    assert hard_codes(p, ok) == set()
    # claiming the cash as an earmark of g1 (the plan has no earmark) is caught
    bad = hand_result(p, lines=[("g1", "safe", "2026-11", "2027-10", 1000.0)],
                      rows=[("hc", "g1", 5000, "earmark")], goals={"g1": dict(planned_value_real=17000)})
    assert "HOLDING_SPLIT_MISMATCH" in hard_codes(p, bad)


def test_rebalances_off_schedule_or_for_unknown_goals_are_reported():
    p = _vp()
    r = hand_result(p, lines=[("g1", "safe", "2026-11", "2027-10", 1000.0)],
                    rebalances=[("2027-03", "g1", {"eq": 12000}, {"lock": 5000}),
                                ("2027-03", "nogoal", {"eq": 1}, {"eq": 5})],
                    goals={"g1": dict(planned_value_real=12000)})
    vs = [v for v in validate_result(p, r) if v.code == "REBALANCE_OFF_SCHEDULE"]
    assert sorted(v.goal_id for v in vs) == ["g1", "nogoal"]
    assert all(v.severity == "hard" for v in vs)


def test_rebalance_at_block_start_is_not_off_schedule():
    p = _vp(holdings=[dict(id="s", name="Deposit", asset_class_id="safe", amount=5000)],
            goals=[goal(priority="must", target=4999, month="2036-11", risk_tolerance=5,
                        earmarked=[dict(holding_id="s", amount=5000)])])
    r = hand_result(p, rows=[("s", "g1", 5000, "earmark")],
                    rebalances=[("2027-11", "g1", {"safe": 1000}, {"eq": 1000})],
                    goals={"g1": dict(planned_value_real=5000)})
    assert "REBALANCE_OFF_SCHEDULE" not in hard_codes(p, r)
