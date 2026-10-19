"""`FinanceDraft` -> `FinancePlan` (PHASE2 2.9.2; plan P2-3)."""

from __future__ import annotations

from api_helpers_shim import wait_finance_run
from intake_helpers import API, FIN_CTX, FINANCE_TEXT
from superplanner import finance, intake
from superplanner.finance.templates import retirement_target
from superplanner.intake.models import (Answer, DraftAmount, DraftDebt, DraftExpense, DraftGoal, DraftHolding,
                                        DraftIncome, DraftProfile, FinanceDraft)

FAST = {"time_limit_seconds": 20, "simulation": {"n_paths": 200}, "compute_fixes": False}


def example_build():
    d = intake.describe_finance(FINANCE_TEXT, FIN_CTX).draft
    return intake.build_finance(d, FIN_CTX)


def test_example_build():
    b = example_build()
    assert b.ready and b.blocking == [] and b.preflight.ok
    p = b.plan
    e1 = next(e for e in p.expenses if e.id == "e1")
    assert e1.amount == 75000 and e1.amount_range.low == 70000 and e1.amount_range.high == 80000
    e2 = next(e for e in p.expenses if e.id == "e2")
    assert e2.amount_range is None and e2.inflation_pct == 9.0
    ret = next(g for g in p.goals if g.id == "g2")
    assert ret.target_amount == 22500000 == 25 * 12 * 75000
    assert ret.target_amount == retirement_target(p.expenses, p.incomes)
    assert ret.target_month == "2052-10"
    assert all(i.inflation_linked for i in p.incomes)
    assert p.start_month == "2026-10" and p.profile.risk_tolerance == 3
    assert p.metadata.get("intake") == {"version": 1, "source": "describe", "extractor": "rule"}
    assert b.cashflow is not None and b.cashflow.avg_monthly_surplus_first_year > 0
    assert finance.preflight(p).ok


def test_plan_accepted_and_runs_feasible(client):
    b = example_build()
    r = client.post(f"{API}/finance/plans", json=b.plan.model_dump(mode="json"))
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    run = client.post(f"{API}/finance/plans/{pid}/runs", json=FAST)
    assert run.status_code == 202, run.text
    done = wait_finance_run(client, run.json()["run_id"])
    assert done["status"] == "completed" and done["feasibility"] == "feasible", done


def _draft(**kw) -> FinanceDraft:
    base = dict(start_month="2026-10", profile=DraftProfile(age=30),
                incomes=[DraftIncome(key="i1", name="Salary", amount=DraftAmount(low=100000, high=120000))])
    base.update(kw)
    return FinanceDraft(**base)


def test_midpoint_range_linked_income_and_defaults():
    d = _draft(expenses=[DraftExpense(key="e1", name="Rent", amount=DraftAmount(low=20000, high=20000))],
               holdings=[DraftHolding(key="h1", name="Money", amount=DraftAmount(low=1000, high=1000))])
    b = intake.build_finance(d, FIN_CTX)
    assert b.ready, b
    i1 = b.plan.incomes[0]
    assert i1.amount == 110000 and i1.amount_range.low == 100000 and i1.amount_range.high == 120000
    assert i1.inflation_linked and i1.growth_pct == 0
    assert b.plan.expenses[0].essential is True and b.plan.expenses[0].amount_range is None
    assert b.plan.holdings[0].asset_class_id == "cash"
    assert b.plan.profile.retirement_age == 60 and b.plan.profile.risk_tolerance == 3
    assert b.plan.emergency_fund.months_of_essentials == 6


def test_emi_from_annuity_and_missing_emi_blocks():
    d = _draft(debts=[DraftDebt(key="d1", name="Home loan", kind="home", balance=DraftAmount(low=4000000, high=4000000),
                                interest_rate_pct=8.5, remaining_months=180)])
    b = intake.build_finance(d, FIN_CTX)
    assert b.ready
    r = 0.085 / 12
    expected = 4000000 * r / (1 - (1 + r) ** -180)
    assert abs(b.plan.debts[0].emi - expected) < 1.0
    d = _draft(debts=[DraftDebt(key="d1", name="Loan", balance=DraftAmount(low=50000, high=50000))])
    b = intake.build_finance(d, FIN_CTX)
    assert not b.ready and b.plan is None and [q.code for q in b.blocking] == ["FIN_DEBT_EMI"]


def test_retirement_target_answer_wins_and_goal_month_from_age():
    d = _draft(goals=[DraftGoal(key="g1", name="Retirement", kind="retirement")],
               expenses=[DraftExpense(key="e1", name="Living", amount=DraftAmount(low=40000, high=40000))])
    d.profile.retirement_age = 55
    r = intake.answer_finance(d, [], FIN_CTX)
    a = intake.answer_finance(r.draft, [Answer(question_id="FIN_RETIREMENT_TARGET:/goals/g1/target",
                                               value=9000000)], FIN_CTX)
    b = intake.build_finance(a.draft, FIN_CTX)
    g = b.plan.goals[0]
    assert g.target_amount == 9000000 and g.target_month == "2051-10"
    b2 = intake.build_finance(r.draft, FIN_CTX)
    assert b2.plan.goals[0].target_amount == 25 * 12 * 40000


def test_blocking_without_income():
    d = FinanceDraft(expenses=[DraftExpense(key="e1", name="Rent", amount=DraftAmount(low=1, high=1))])
    b = intake.build_finance(d, FIN_CTX)
    assert not b.ready and b.plan is None and b.blocking[0].code == "FIN_INCOME"
    assert b.preflight is None and b.cashflow is None


def test_preflight_errors_make_not_ready():
    d = _draft(goals=[DraftGoal(key="g1", name="Car", kind="vehicle", target=DraftAmount(low=500000, high=500000),
                                target_month="2020-01")])
    b = intake.build_finance(d, FIN_CTX)
    assert b.plan is not None and b.preflight is not None
    assert b.ready == b.preflight.ok
    if not b.preflight.ok:
        assert b.cashflow is None
