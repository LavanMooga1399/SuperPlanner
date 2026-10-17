"""What-if derivation and comparison (F.13; acceptance 1.17)."""

import pytest

from fin_helpers import expense, goal, income, load_fixture, plan, run
from superplanner.finance import WhatIfChanges, apply_what_if, compare_results, project_cashflow
from superplanner.finance.whatif import default_label


def test_apply_what_if_is_pure_and_deterministic():
    p = load_fixture("typical.finance.json")
    before = p.model_dump_json()
    ch = WhatIfChanges(extra_monthly_savings=10000, risk_tolerance=4, return_shift_pct=-1, inflation_pct=7,
                       emergency_build_share=0.5,
                       goal_overrides=[dict(goal_id="car", target_month="2031-06", target_amount=900000,
                                            priority="must", risk_tolerance=5),
                                       dict(goal_id="trip", enabled=False)],
                       income_drop=dict(start_month="2027-06", months=6, percent=50))
    a = apply_what_if(p, ch)
    b = apply_what_if(p, ch)
    assert p.model_dump_json() == before
    assert a == b
    car = next(g for g in a.goals if g.id == "car")
    assert (car.target_month, car.target_amount, car.priority, car.risk_tolerance) == ("2031-06", 900000, "must", 5)
    assert not next(g for g in a.goals if g.id == "trip").enabled
    assert a.profile.risk_tolerance == 4 and a.assumptions.inflation_pct == 7
    assert a.emergency_fund.build_share == 0.5
    eq = next(c for c in a.assumptions.asset_classes if c.id == "equity_index")
    cash = next(c for c in a.assumptions.asset_classes if c.id == "cash")
    assert eq.expected_return_pct == pytest.approx(11.0) and cash.expected_return_pct == 3.5
    extra = next(i for i in a.incomes if i.id == "whatif_extra")
    assert extra.amount == 10000 and extra.growth_pct == 7 and not extra.interruptible
    drop = next(e for e in a.expenses if e.id == "whatif_income_drop")
    assert drop.amount == pytest.approx(0.5 * 120000)        # interruptible salary only (rent is not)
    assert drop.start_month == "2027-06" and drop.end_month == "2027-11" and drop.essential


def test_negative_savings_and_unknown_goal():
    p = load_fixture("typical.finance.json")
    a = apply_what_if(p, WhatIfChanges(extra_monthly_savings=-2000))
    less = next(e for e in a.expenses if e.id == "whatif_less")
    assert less.amount == 2000 and not less.essential and less.inflation_linked
    with pytest.raises(ValueError):
        apply_what_if(p, WhatIfChanges(goal_overrides=[dict(goal_id="ghost", target_amount=1)]))
    with pytest.raises(ValueError):
        apply_what_if(a, WhatIfChanges())                       # input already has whatif_ ids


def test_income_drop_does_not_change_ef_target():
    p = plan(incomes=[income(amount=50000)], expenses=[expense(amount=20000)], goals=[goal(month="2029-11")])
    d = apply_what_if(p, WhatIfChanges(income_drop=dict(start_month="2026-11", months=3, percent=40)))
    assert project_cashflow(d).ef_target == project_cashflow(p).ef_target
    assert project_cashflow(d).surplus[0] == pytest.approx(project_cashflow(p).surplus[0] - 20000)


def test_default_label():
    p = load_fixture("typical.finance.json")
    lbl = default_label(p, WhatIfChanges(extra_monthly_savings=10000, goal_overrides=[dict(goal_id="car",
                                                                                          target_month="2031-06")]))
    assert lbl == "+₹10,000/month, Car 2031-06"
    assert default_label(p, WhatIfChanges()) == "What-if"


def test_compare_results_deltas_and_goal_union():
    p = plan(incomes=[income(amount=60000)], expenses=[expense(amount=30000)],
             goals=[goal("car", 500000, "2029-11"), goal("trip", 100000, "2028-11", priority="nice")])
    a = run(p)
    ch = WhatIfChanges(extra_monthly_savings=5000, goal_overrides=[dict(goal_id="trip", enabled=False)])
    b = run(apply_what_if(p, ch))
    c = compare_results(a, b, what_if_b=ch)
    assert [g.goal_id for g in c.goals] == ["car", "trip"]
    car, trip = c.goals
    assert car.in_a and car.in_b and car.success_delta == pytest.approx(car.success_b - car.success_a)
    assert car.p50_delta == pytest.approx(car.p50_b - car.p50_a)
    assert trip.in_a and not trip.in_b and trip.success_b is None and trip.success_delta is None
    t = c.totals
    assert t.monthly_contribution_now_delta == pytest.approx(t.monthly_contribution_now_b
                                                             - t.monthly_contribution_now_a)
    assert c.what_if_b == ch and c.a.goals_total == 2 and c.b.goals_total == 1
