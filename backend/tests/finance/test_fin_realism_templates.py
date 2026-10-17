"""PHASE2 1.9 / 1.14 / PLAN-PHASE2 P1-2: the three templates meet the realism bands at default settings."""

from __future__ import annotations

import time

import pytest

from fin_helpers import assert_clean
from superplanner.finance import FinanceRunRequest, get_template, run_plan

TEMPLATE_IDS = ("young_professional", "family", "near_retirement")
_CACHE: dict = {}


def result(tid: str, seed: int):
    key = (tid, seed)
    if key not in _CACHE:
        p = get_template(tid).build(name=tid, start_month="2026-11")
        t0 = time.monotonic()
        r = run_plan(p, FinanceRunRequest(seed=seed, simulation={"n_paths": 1000}))
        _CACHE[key] = (p, r, time.monotonic() - t0)
    return _CACHE[key]


@pytest.mark.parametrize("seed", [0, 1])
@pytest.mark.parametrize("tid", TEMPLATE_IDS)
def test_common_bands(tid, seed):
    p, r, _ = result(tid, seed)
    assert r.feasibility == "feasible"
    assert not [v for v in r.violations if v.severity == "hard"]
    assert_clean(p, r)
    assert min(r.cashflow.surplus[:12]) >= 0
    assert r.summary.monthly_surplus_avg_12m > 0
    assert r.summary.monthly_investable_now >= 0


@pytest.mark.parametrize("seed", [0, 1])
def test_family_bands(seed):
    _, r, _ = result("family", seed)
    assert sum(1 for g in r.goals if g.success_probability >= 0.5) >= 2
    assert all(g.status != "off_track" for g in r.goals if g.priority == "must")


@pytest.mark.parametrize("seed", [0, 1])
def test_near_retirement_bands(seed):
    _, r, _ = result("near_retirement", seed)
    g = {x.goal_id: x for x in r.goals}
    assert g["retirement"].status == "on_track"
    assert sum(1 for x in r.goals if x.success_probability >= 0.5) >= 1


@pytest.mark.parametrize("seed", [0, 1])
def test_young_professional_bands(seed):
    _, r, _ = result("young_professional", seed)
    g = {x.goal_id: x for x in r.goals}
    assert g["retirement"].success_probability >= 0.5
    car = g["car"]
    assert car.status == "at_risk" and car.shortfall_fraction <= 0.10
    assert len(r.explanation.goals["car"].fixes) >= 1        # the fix the "Try this" e2e test clicks


def test_seed_seven_gives_the_same_statuses():
    for tid in TEMPLATE_IDS:
        a = {g.goal_id: g.status for g in result(tid, 1)[1].goals}
        b = {g.goal_id: g.status for g in result(tid, 7)[1].goals}
        assert a == b, tid


@pytest.mark.parametrize("tid", TEMPLATE_IDS)
def test_default_run_time(tid):
    p = get_template(tid).build(name=tid, start_month="2026-11")
    t0 = time.monotonic()
    run_plan(p, FinanceRunRequest())
    assert time.monotonic() - t0 <= 5.0


def test_template_figures_and_retirement_preset():
    from superplanner.finance.templates import retirement_target
    y = get_template("young_professional").build(name="y", start_month="2026-11")
    f = get_template("family").build(name="f", start_month="2026-11")
    n = get_template("near_retirement").build(name="n", start_month="2026-11")
    goal = lambda p, i: next(g for g in p.goals if g.id == i)  # noqa: E731
    assert goal(y, "retirement").target_amount == 1_14_00_000
    assert goal(f, "retirement").target_amount == 2_85_00_000
    assert goal(n, "retirement").target_amount == 2_25_00_000
    assert all(i.inflation_linked for p in (y, f, n) for i in p.incomes)
    fees = next(e for e in f.expenses if e.id == "school_fees")
    assert (fees.amount, fees.frequency, fees.end_month) == (18000, "quarterly", "2041-10")
    assert goal(f, "education").target_month == "2041-11"
    rent = next(i for i in n.incomes if i.id == "rent_in")
    assert rent.kind == "rental" and not rent.interruptible and rent.end_month is None
    assert next(i for i in n.incomes if i.id == "salary").end_month == "2034-10"
    assert {h.id: h.amount for h in f.holdings} == {"h_cash": 600000, "h_eq": 800000, "h_ppf": 400000}
    # the helper: open-ended non-education expenses minus open-ended rent/pension, never negative
    assert retirement_target(n.expenses, n.incomes) == 25 * 12 * (95000 - 20000)
    assert retirement_target(n.expenses, n.incomes + n.incomes) == 25 * 12 * (95000 - 40000)
    assert retirement_target([], n.incomes) == 0.0
