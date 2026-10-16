"""Explanations and fixes (F.12; acceptance 1.16)."""

import pytest

from fin_helpers import (assert_clean, expense, goal, income, plan, run, zero_assumptions, zero_classes, zplan)
from superplanner.finance import apply_what_if, get_template
from superplanner.finance.advisor.messages import contains_forbidden, format_money, matching_codes
from superplanner.finance.validator import tolerances


def all_texts(r):
    e = r.explanation
    out = list(e.summary) + list(e.assumptions) + list(e.limitations) + list(e.replanning_triggers)
    out += [b.message for b in e.binding_constraints]
    for ge in e.goals.values():
        out += [x.message for x in ge.reasons] + [f.message for f in ge.fixes]
    return out


def reasons(r, gid):
    return {x.code for x in r.explanation.goals[gid].reasons}


def _short_plan(**kw):
    doc = dict(incomes=[income(amount=1500)], expenses=[expense()], goals=[goal(priority="must")])
    doc.update(kw)
    return zplan(**doc)


def _growth_plan(**kw):
    classes = [dict(id="cash", name="Cash", category="cash", expected_return_pct=6.0, volatility_pct=0.0),
               dict(id="safe", name="Safe", category="debt", expected_return_pct=6.0, volatility_pct=0.0,
                    liquidity_days=2),
               dict(id="eq", name="Equity", category="equity", expected_return_pct=14.0, volatility_pct=0.0)]
    doc = dict(assumptions=dict(inflation_pct=6.0, inflation_volatility_pct=0.0, cash_class_id="cash",
                                asset_classes=classes, correlations=[]),
               emergency_fund=dict(months_of_essentials=0, asset_class_id="safe"),
               incomes=[income(amount=60000)], expenses=[expense(amount=20000)], profile=dict(risk_tolerance=5),
               goals=[goal("g", 2_000_000, "2036-11", priority="must")])
    doc.update(kw)
    return plan(**doc)


def test_reason_codes_on_crafted_plans():
    r = run(_growth_plan())
    assert {"ALLOCATION_SPLIT", "RISK_CAP", "GLIDE_DOWN", "CAUTIOUS_RETURNS", "ON_TRACK"} <= reasons(r, "g")
    lock = zplan(assumptions=zero_assumptions(zero_classes(lock={"expected_return_pct": 5.0})),
                 incomes=[income(amount=3000)], expenses=[expense()], goals=[goal(priority="must")])
    assert "LOCKIN_EXCLUDED" in reasons(run(lock), "g1")
    ef = zplan(emergency_fund=dict(months_of_essentials=3, asset_class_id="safe"), incomes=[income(amount=3000)],
               expenses=[expense()], goals=[goal("car", 6000, "2028-11", priority="should")])
    rf = run(ef)
    assert "EF_GATED" in reasons(rf, "car")
    assert any(b.code == "EF_BUILD" for b in rf.explanation.binding_constraints)
    short = run(_short_plan())
    assert {"SHORTFALL", "CASH_LIMITED"} <= reasons(short, "g1")
    assert any(b.code == "CASH_FULLY_USED" for b in short.explanation.binding_constraints)
    held = zplan(incomes=[income(amount=3000)], expenses=[expense()],
                 holdings=[dict(id="h", name="Old deposit", asset_class_id="safe", amount=4000)],
                 goals=[goal(priority="must", earmarked=[dict(holding_id="h", amount=4000)])])
    rh = run(held)
    hu = [x for x in rh.explanation.goals["g1"].reasons if x.code == "HOLDINGS_USED"]
    assert hu and "Old deposit" in hu[0].message and format_money(4000, "INR") in hu[0].message
    yp = run(get_template("young_professional").build(name="t", start_month="2026-11"))
    assert any("LOW_PROBABILITY" in reasons(yp, g.goal_id) for g in yp.goals
               if g.success_probability < g.min_success_probability)


def test_debt_payoff_and_caps_binding():
    p = _growth_plan(constraints=dict(max_equity_pct=30),
                     debts=[dict(id="d", name="Bike loan", balance=50000, interest_rate_pct=10, emi=5000)])
    r = run(p)
    codes = {b.code for b in r.explanation.binding_constraints}
    assert {"EQUITY_CAP", "DEBT_PAYOFF"} <= codes


def test_every_sentence_from_catalog_and_compliant():
    for p in (_growth_plan(), _short_plan(), get_template("family").build(name="t", start_month="2026-11")):
        r = run(p, compute_fixes=True)
        for text in all_texts(r):
            assert matching_codes(text), text
            assert not contains_forbidden(text), text


def test_money_format():
    assert format_money(120000, "INR") == "₹1,20,000"
    assert format_money(12345678.4, "INR") == "₹1,23,45,678"
    assert format_money(999, "INR") == "₹999"
    assert format_money(-5000, "INR") == "-₹5,000"
    assert format_money(1234567, "USD") == "$1,234,567"
    assert format_money(1500, "CHF") == "CHF 1,500"


def _check_guarantee(p, kinds):
    r = run(p, compute_fixes=True)
    gid = r.goals[0].goal_id
    fixes = r.explanation.goals[gid].fixes
    by_kind = {f.kind: f for f in fixes}
    assert set(kinds) <= set(by_kind), [f.kind for f in fixes]
    assert sum(1 for f in fixes if f.smallest) == 1
    for kind in kinds:
        derived = apply_what_if(p, by_kind[kind].what_if)
        rr = run(derived, calibration_rounds=0)
        assert_clean(derived, rr)
        _, tol_g = tolerances(derived)
        g = next(x for x in rr.goals if x.goal_id == gid)
        assert g.shortfall_real <= tol_g[gid], (kind, g.shortfall_real, tol_g[gid])
    return r, by_kind


def test_fix_guarantee_zero_returns():
    r, by = _check_guarantee(_short_plan(), ["INCREASE_SAVINGS", "DELAY_GOAL", "REDUCE_TARGET"])
    assert by["INCREASE_SAVINGS"].what_if.extra_monthly_savings in (500, 501)      # + flooring headroom
    assert by["DELAY_GOAL"].months == 12
    assert by["REDUCE_TARGET"].what_if.goal_overrides[0].target_amount == pytest.approx(6000, abs=1)


def test_fix_guarantee_with_returns_ef_and_inflation():
    p = plan(incomes=[income(amount=40000, growth_pct=6)], expenses=[expense(amount=28000)],
             holdings=[dict(id="h", name="Savings", asset_class_id="cash", amount=60000)],
             emergency_fund=dict(months_of_essentials=3),
             goals=[goal("car", 700000, "2029-11", priority="should", flexibility_months=12)])
    r, by = _check_guarantee(p, ["INCREASE_SAVINGS", "DELAY_GOAL"])
    assert r.goals[0].status != "on_track"


def test_increase_risk_is_a_goal_override():
    p = _growth_plan(profile=dict(risk_tolerance=1), incomes=[income(amount=45000)],
                     goals=[goal("g", 2_000_000, "2036-11", priority="must")])
    r = run(p, compute_fixes=True)
    fx = [f for f in r.explanation.goals["g"].fixes if f.kind == "INCREASE_RISK"]
    assert fx, [f.kind for f in r.explanation.goals["g"].fixes]
    w = fx[0].what_if
    assert w.risk_tolerance is None and w.goal_overrides[0].goal_id == "g"
    assert w.goal_overrides[0].risk_tolerance == fx[0].new_risk_tolerance > 1
    for ge in r.explanation.goals.values():
        if ge.fixes:
            assert sum(1 for f in ge.fixes if f.smallest) == 1


def test_lower_ef_build_share_for_must_goal():
    p = zplan(emergency_fund=dict(months_of_essentials=6, asset_class_id="safe"), incomes=[income(amount=2000)],
              expenses=[expense()], goals=[goal("g", 6000, "2027-11", priority="must")])
    r = run(p, compute_fixes=True)
    kinds = {f.kind for f in r.explanation.goals["g"].fixes}
    assert "LOWER_EF_BUILD_SHARE" in kinds
