"""Performance smoke (acceptance 1.23)."""

import time

from fin_helpers import assert_clean, load_fixture
from superplanner.finance import FinanceRunRequest, get_template, project_cashflow, run_plan
from superplanner.finance.optimizer import FinanceLP
from superplanner.finance.returns import initial_z


def test_young_professional_full_run_under_5_seconds():
    p = get_template("young_professional").build(name="t", start_month="2026-11")
    t = time.monotonic()
    r = run_plan(p, FinanceRunRequest(simulation={"n_paths": 2000}, compute_fixes=True))
    assert time.monotonic() - t < 5.0
    assert_clean(p, r)


def test_typical_plan_optimizer_tiers_under_1_second():
    p = load_fixture("typical.finance.json")
    assert len(p.goals) == 5 and len(p.assumptions.asset_classes) == 6
    proj = project_cashflow(p)
    assert proj.T >= 360
    z = {g.id: initial_z(g) for g in p.goals}
    t = time.monotonic()
    sol = FinanceLP(p, proj, z).lexicographic(time.monotonic() + 30)
    assert time.monotonic() - t < 1.0
    assert sol.termination_reason == "optimal"
