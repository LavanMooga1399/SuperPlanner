"""PHASE2 1.12: amount ranges are informational; preflight warns when the amount is outside the range."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fin_helpers import expense, goal, income, plan, run
from superplanner.finance import AmountRange, preflight
from superplanner.finance.advisor.messages import matching_codes


def test_amount_range_validation():
    assert AmountRange(low=70000, high=80000).high == 80000
    assert AmountRange(low=5, high=5).low == 5
    for bad in (dict(low=10, high=5), dict(low=-1, high=5), dict(low=1), dict(low=1, high=2, x=3)):
        with pytest.raises(ValidationError):
            AmountRange(**bad)


def _p(**kw):
    doc = dict(incomes=[income(amount=75000, amount_range=dict(low=70000, high=80000))],
               expenses=[expense(amount=30000, name="Rent", amount_range=dict(low=25000, high=35000))],
               goals=[goal("g", 500000, "2030-11", name="Car", target_range=dict(low=400000, high=600000))])
    doc.update(kw)
    return plan(**doc)


def test_inside_range_has_no_warning_and_round_trips():
    p = _p()
    assert not [i for i in preflight(p).issues if i.code == "AMOUNT_OUTSIDE_RANGE"]
    again = type(p).model_validate_json(p.model_dump_json())
    assert again == p and again.incomes[0].amount_range.low == 70000


def test_outside_range_warns_with_field_path():
    p = _p(goals=[goal("g", 700000, "2030-11", name="Car", target_range=dict(low=400000, high=600000))])
    issues = [i for i in preflight(p).issues if i.code == "AMOUNT_OUTSIDE_RANGE"]
    assert len(issues) == 1
    i = issues[0]
    assert i.severity == "warning" and i.field == "goals[0].target_amount" and i.item_ids == ["g"]
    assert i.message == "Car: the amount ₹7,00,000 is outside the range you gave (₹4,00,000 to ₹6,00,000)"
    assert preflight(p).ok


def test_engine_uses_the_amount_and_explains_the_range():
    p = _p()
    r = run(p)
    assert r.feasibility == "feasible"
    lines = [a for a in r.explanation.assumptions if "ASSUMPTION_RANGE" in matching_codes(a)]
    assert "Salary: you gave a range of ₹70,000 to ₹80,000; the plan uses ₹75,000." in lines
    assert "Rent: you gave a range of ₹25,000 to ₹35,000; the plan uses ₹30,000." in lines
    assert "Car: you gave a range of ₹4,00,000 to ₹6,00,000; the plan uses ₹5,00,000." in lines
    # same plan without ranges -> same numbers
    q = plan(incomes=[income(amount=75000)], expenses=[expense(amount=30000, name="Rent")],
             goals=[goal("g", 500000, "2030-11", name="Car")])
    r2 = run(q)
    assert r2.goals[0].planned_value_real == r.goals[0].planned_value_real
    assert r2.summary.monthly_contribution_now == r.summary.monthly_contribution_now
