"""PHASE2 1.7: inflation-linked incomes in the cash flow, the simulator and the what-if income drop."""

from __future__ import annotations

import numpy as np
import pytest

from fin_helpers import expense, goal, income, plan, run
from superplanner.finance import WhatIfChanges, apply_what_if, project_cashflow
from superplanner.finance.cashflow import flow_components
from superplanner.finance.model import IncomeStream
from superplanner.finance.simulate import Policy, simulate


def _p(**inc):
    return plan(incomes=[income(amount=100000, **inc)], expenses=[expense(amount=40000)],
                goals=[goal("g", 500000, "2031-11", priority="must")])


def test_default_is_not_linked_and_old_documents_load():
    assert IncomeStream(id="s", name="S", amount=1).inflation_linked is False
    p = _p()
    assert p.incomes[0].inflation_linked is False


def test_linked_income_is_flat_in_real_terms_at_zero_growth():
    p = _p(inflation_linked=True, growth_pct=0)
    proj = project_cashflow(p)
    assert np.allclose(proj.income, 100000.0)
    fc = flow_components(p)
    assert np.allclose(fc.inc_int_linked, 100000.0) and not fc.inc_int.any() and not fc.inc_nonint.any()


def test_nominal_income_loses_real_value_but_linked_with_real_raise_grows():
    nominal = project_cashflow(_p(growth_pct=0)).income
    assert nominal[11] < nominal[0] and nominal[0] == pytest.approx(100000.0)
    linked = project_cashflow(_p(inflation_linked=True, growth_pct=3)).income
    assert linked[0] == pytest.approx(100000.0) and linked[11] == pytest.approx(100000.0)
    assert linked[12] == pytest.approx(103000.0) and linked[24] == pytest.approx(100000 * 1.03 ** 2)


def test_non_interruptible_linked_income_goes_to_real_linked():
    p = _p(inflation_linked=True, interruptible=False)
    fc = flow_components(p)
    assert not fc.inc_int_linked.any()
    assert fc.real_linked[0] == pytest.approx(100000.0 - 40000.0)
    assert np.allclose(project_cashflow(p).income, 100000.0)


def _sim(p, interruption=None, n=200):
    proj = project_cashflow(p)
    fc = flow_components(p)
    T = proj.T
    pol = Policy(goal_ids=[], D=np.zeros(0, dtype=int), TR=np.zeros(0), tier=np.zeros(0, dtype=int),
                 X=np.zeros((0, len(p.assumptions.asset_classes), T)), F0=np.zeros((0, len(p.assumptions.asset_classes))),
                 rebalance={}, ef0=proj.ef_initial, b0=proj.cash_buffer_initial,
                 U0=np.zeros(len(p.assumptions.asset_classes)))
    kw = {} if interruption is None else {"interruption": interruption}
    return simulate(p, fc, proj, pol, n_paths=n, seed=3, **kw)


def test_simulator_reprices_linked_income_with_the_path_inflation():
    """With inflation volatility, linked income keeps real wealth tighter than the same nominal income."""
    def spread(p):
        out = _sim(p)
        return float(out.total_q[2, -1] - out.total_q[0, -1])
    doc = dict(assumptions=dict(inflation_volatility_pct=3.0))
    lin = plan(incomes=[income(amount=100000, inflation_linked=True)], expenses=[expense(amount=40000)], **doc)
    nom = plan(incomes=[income(amount=100000)], expenses=[expense(amount=40000)], **doc)
    assert spread(lin) < spread(nom)


def test_interruptions_zero_linked_income():
    from superplanner.finance.model import IncomeInterruption
    p = plan(incomes=[income(amount=100000, inflation_linked=True)], expenses=[expense(amount=40000)])
    base = _sim(p)
    cut = _sim(p, IncomeInterruption(enabled=True, annual_probability=0.5, duration_months=12))
    assert float(cut.total_q[1, -1]) < float(base.total_q[1, -1])


def test_whatif_income_drop_adds_a_linked_expense_for_linked_streams():
    p = plan(incomes=[income(amount=100000, inflation_linked=True, growth_pct=2),
                      income(id="side", name="Side job", amount=20000)],
             expenses=[expense(amount=40000)])
    d = apply_what_if(p, WhatIfChanges(income_drop=dict(start_month="2028-01", months=6, percent=50)))
    ex = {e.id: e for e in d.expenses}
    assert ex["whatif_income_drop"].inflation_linked is False
    assert ex["whatif_income_drop"].amount == pytest.approx(0.5 * 20000)     # nominal stream, unchanged rule
    lk = ex["whatif_income_drop_linked"]
    assert lk.inflation_linked is True and lk.essential is True
    assert lk.amount == pytest.approx(0.5 * 100000 * 1.02)                  # real amount at the drop start
    assert (lk.start_month, lk.end_month) == ("2028-01", "2028-06")


def test_whatif_income_drop_without_linked_streams_is_unchanged():
    p = plan(incomes=[income(amount=50000)], expenses=[expense(amount=20000)])
    d = apply_what_if(p, WhatIfChanges(income_drop=dict(start_month="2027-01", months=3, percent=20)))
    assert [e.id for e in d.expenses if e.id.startswith("whatif_")] == ["whatif_income_drop"]


def test_linked_income_plan_runs_clean():
    from fin_helpers import assert_clean
    p = _p(inflation_linked=True, growth_pct=2)
    r = run(p)
    assert r.feasibility == "feasible"
    assert_clean(p, r)
