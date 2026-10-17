"""PHASE2 1.11 / P1-6: first-year averages, the funding split and the summary lines."""

from __future__ import annotations

import pytest

from fin_helpers import expense, goal, income, load_fixture, plan, run, zplan
from superplanner.finance import get_template
from superplanner.finance.advisor.messages import matching_codes

TEMPLATE_IDS = ("young_professional", "family", "near_retirement")
_CACHE: dict = {}


def _res(tid):
    if tid not in _CACHE:
        p = get_template(tid).build(name=tid, start_month="2026-11")
        _CACHE[tid] = (p, run(p))
    return _CACHE[tid]


def _check_definitions(p, r):
    s = r.summary
    n = min(12, r.horizon_months)
    X = r.cashflow.goal_contribution[:n]
    sur = r.cashflow.surplus[:n]
    ef = r.cashflow.emergency_fund_contribution[:n]
    inv = [a - b for a, b in zip(sur, ef)]
    assert s.monthly_surplus_avg_12m == pytest.approx(sum(sur) / n, abs=0.01)
    assert s.monthly_ef_contribution_avg_12m == pytest.approx(sum(ef) / n, abs=0.01)
    assert s.monthly_investable_avg_12m == pytest.approx(sum(inv) / n, abs=0.02)
    assert s.monthly_contribution_avg_12m == pytest.approx(sum(X) / n, abs=0.01)
    assert s.monthly_from_surplus_avg_12m == pytest.approx(sum(min(x, max(i, 0)) for x, i in zip(X, inv)) / n,
                                                           abs=0.02)
    assert s.monthly_from_surplus_avg_12m + s.monthly_from_savings_avg_12m == pytest.approx(
        s.monthly_contribution_avg_12m, abs=0.01)
    assert s.monthly_from_savings_avg_12m >= 0
    # month-0 fields keep their meaning (API compatibility)
    assert s.monthly_investable_now == pytest.approx(round(inv[0], 2), abs=0.01)
    assert s.monthly_contribution_now == pytest.approx(X[0], abs=0.01)
    sold = sum(a.amount for a in r.holdings_assignment if a.source == "sold_to_cash")
    tau = p.constraints.rebalance_cost_pct / 100
    initial = sum(a.amount for a in r.holdings_assignment if a.source == "initial_cash")
    assert s.savings_to_cash_at_start == pytest.approx(initial + (1 - tau) * sold, abs=0.05)


@pytest.mark.parametrize("tid", TEMPLATE_IDS)
def test_definitions_on_templates(tid):
    _check_definitions(*_res(tid))


@pytest.mark.parametrize("name", ["typical.finance.json", "single_goal.finance.json"])
def test_definitions_on_fixtures(name):
    p = load_fixture(name)
    _check_definitions(p, run(p))


def test_definitions_when_holdings_are_sold_to_cash():
    p = zplan(incomes=[income(amount=1000)], expenses=[expense(amount=900)],
              holdings=[dict(id="h", name="Shares", asset_class_id="eq", amount=20000)],
              goals=[goal("a", 15000, "2027-05", priority="must", allowed_asset_class_ids=["safe"])])
    r = run(p)
    _check_definitions(p, r)


def _codes(r):
    return [matching_codes(line)[0] for line in r.explanation.summary]


def test_summary_line_order_and_selection():
    _, r = _res("family")
    codes = _codes(r)
    assert codes[:4] == ["SUMMARY_FEASIBLE", "SUMMARY_SURPLUS", "SUMMARY_FUNDING", "SUMMARY_EF_DONE"]
    assert "SUMMARY_INVEST" not in codes
    _, y = _res("young_professional")
    assert _codes(y)[1:3] == ["SUMMARY_SURPLUS_EF", "SUMMARY_FUNDING"]
    assert len(y.explanation.summary) <= 5


def test_summary_funding_surplus_only_and_none():
    p = plan(incomes=[income(amount=60000)], expenses=[expense(amount=20000)],
             goals=[goal("g", 300000, "2029-11", priority="must")], emergency_fund={"months_of_essentials": 0})
    codes = _codes(run(p))
    assert codes[2] == "SUMMARY_FUNDING_SURPLUS"
    p2 = plan(incomes=[income(amount=60000)], expenses=[expense(amount=20000)],
              emergency_fund={"months_of_essentials": 0})
    assert _codes(run(p2))[2] == "SUMMARY_FUNDING_NONE"


def test_summary_negative_surplus():
    p = plan(incomes=[income(amount=20000)], expenses=[expense(amount=30000)],
             holdings=[dict(id="h", name="Savings", asset_class_id="cash", amount=2000000)],
             emergency_fund={"months_of_essentials": 0})
    r = run(p)
    assert r.summary.monthly_surplus_avg_12m < 0
    assert _codes(r)[1] == "SUMMARY_SURPLUS_NEGATIVE"
    assert "are about ₹10," in r.explanation.summary[1]


def test_family_numbers_read_consistently():
    """The screenshot case of PHASE2 1.2: no negative 'left over', and the funding split explains the gap."""
    _, r = _res("family")
    s = r.summary
    assert s.monthly_surplus_avg_12m > 0 and s.monthly_investable_now >= 0
    assert s.monthly_contribution_avg_12m > s.monthly_from_surplus_avg_12m > 0
