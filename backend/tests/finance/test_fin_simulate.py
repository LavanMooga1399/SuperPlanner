"""Monte Carlo and deterministic scenarios (F.9; acceptance 1.13)."""

import resource
import time

import numpy as np
import pytest

from fin_helpers import assert_clean, expense, goal, income, plan, run
from superplanner.finance import FinancePlan, get_template, project_cashflow
from superplanner.finance.cashflow import flow_components
from superplanner.finance.model import IncomeInterruption
from superplanner.finance.optimizer import FinanceLP
from superplanner.finance.pipeline import publish
from superplanner.finance.returns import initial_z
from superplanner.finance.simulate import (repair_correlation, sample_monthly_log_returns, scenario_inputs,
                                           simulate)

TIMING = {"seconds", "simulation_seconds", "seconds_total"}


def _strip_timing(obj):
    if isinstance(obj, dict):
        return {k: _strip_timing(v) for k, v in obj.items() if k not in TIMING}
    if isinstance(obj, list):
        return [_strip_timing(v) for v in obj]
    return obj


def _yp(**changes) -> FinancePlan:
    p = get_template("young_professional").build(name="t", start_month="2026-11")
    if not changes:
        return p
    doc = p.model_dump()
    for fn in changes.values():
        fn(doc)
    return FinancePlan.model_validate(doc)


def _zero_vol(doc):
    for ac in doc["assumptions"]["asset_classes"]:
        ac["volatility_pct"] = 0.0
    doc["assumptions"]["inflation_volatility_pct"] = 0.0


def _policy(p):
    proj = project_cashflow(p)
    z = {g.id: initial_z(g) for g in p.goals if g.enabled}
    sol = FinanceLP(p, proj, z).lexicographic(time.monotonic() + 30)
    return proj, flow_components(p), publish(p, proj, sol, z)


def test_same_seed_gives_identical_result_json():
    p = _yp()
    a = run(p, seed=7, simulation={"n_paths": 300}, calibration_rounds=1, compute_fixes=True)
    b = run(p, seed=7, simulation={"n_paths": 300}, calibration_rounds=1, compute_fixes=True)
    assert _strip_timing(a.model_dump(mode="json")) == _strip_timing(b.model_dump(mode="json"))
    c = run(p, seed=8, simulation={"n_paths": 300})
    assert c.series.total_p50 != a.series.total_p50


def test_zero_volatility_matches_central_scenario():
    p = _yp(z=_zero_vol)
    r = run(p, simulation={"n_paths": 200})
    assert_clean(p, r)
    for g in r.goals:
        assert g.success_probability in (0.0, 1.0)
        assert g.p50_real == pytest.approx(g.projected_central_real, rel=1e-3)
        assert g.p10_real == pytest.approx(g.p90_real, rel=1e-9)
    assert r.series.total_p50 == pytest.approx(r.series.total_p10)


def test_doubling_contributions_never_lowers_success():
    p = plan(incomes=[income(amount=200000)], expenses=[expense(amount=50000)],
             goals=[goal("car", 900000, "2030-11", priority="must"), goal("trip", 300000, "2028-11", priority="nice")])
    proj, fc, pub = _policy(p)
    pol = pub.policy
    base = simulate(p, fc, proj, pol, n_paths=1500, seed=3)
    pol.X = pol.X * 2.0
    more = simulate(p, fc, proj, pol, n_paths=1500, seed=3)
    assert np.all(more.success >= base.success)
    assert np.all(more.p50 >= base.p50)


def test_sample_correlation():
    classes = [dict(id="cash", name="Cash", category="cash", expected_return_pct=3, volatility_pct=1),
               dict(id="a", name="A", category="equity", expected_return_pct=10, volatility_pct=20),
               dict(id="b", name="B", category="equity", expected_return_pct=8, volatility_pct=15)]
    p = plan(assumptions=dict(asset_classes=classes, correlations=[dict(a="a", b="b", rho=0.5)]),
             emergency_fund=dict(asset_class_id="cash"))
    x = sample_monthly_log_returns(p, 20000, seed=11)
    rho = np.corrcoef(x[:, 1], x[:, 2])[0, 1]
    assert abs(rho - 0.5) < 0.03
    assert abs(np.corrcoef(x[:, 0], x[:, 1])[0, 1]) < 0.03


def test_correlation_repair():
    C = np.array([[1, 0.99, -0.99], [0.99, 1, 0.99], [-0.99, 0.99, 1]])
    R, repaired = repair_correlation(C)
    assert repaired and np.allclose(np.diag(R), 1) and np.linalg.eigvalsh(R).min() > -1e-9


def test_income_interruption_lowers_probability():
    p = _yp()
    proj, fc, pub = _policy(p)
    off = simulate(p, fc, proj, pub.policy, n_paths=1500, seed=5)
    on = simulate(p, fc, proj, pub.policy, n_paths=1500, seed=5,
                  interruption=IncomeInterruption(enabled=True, annual_probability=0.5, duration_months=12))
    assert on.success.sum() < off.success.sum()
    assert on.liquidity_risk >= off.liquidity_risk


def test_scenarios_order_low_central_high():
    p = _yp()
    r = run(p)
    for g in r.goals:
        sc = r.scenarios.goals[g.goal_id]
        assert sc["low"] <= sc["central"] <= sc["high"]
        assert g.projected_central_real == pytest.approx(sc["central"])
    lo, pi_lo = scenario_inputs(p, "low")
    hi, pi_hi = scenario_inputs(p, "high")
    assert np.all(lo <= hi) and pi_lo > pi_hi


def test_series_lengths_and_stack_equals_band_quantity():
    p = _yp()
    r = run(p)
    T = r.horizon_months
    s = r.series
    for arr in [s.emergency_fund, s.cash_buffer, s.unallocated, s.goal_withdrawals, s.total_p10, s.total_p50,
                s.total_p90, *s.corpus_by_class.values()]:
        assert len(arr) == T
    for arr in r.cashflow.model_dump().values():
        assert len(arr) == T
    # the central stack (classes + EF + buffer + unallocated) is the same quantity as the p10-p90 band [R20]
    z = _yp(z=_zero_vol)
    rz = run(z)
    stack = [sum(v[t] for v in rz.series.corpus_by_class.values()) + rz.series.emergency_fund[t]
             + rz.series.cash_buffer[t] + rz.series.unallocated[t] for t in range(rz.horizon_months)]
    assert stack == pytest.approx(rz.series.total_p50, abs=0.05)


def test_memory_bounded_10000_paths_600_months():
    p = plan(incomes=[income(amount=100000, growth_pct=5)], expenses=[expense(amount=40000)],
             holdings=[dict(id="h", name="Shares", asset_class_id="equity_index", amount=100000)],
             goals=[goal("ret", 20_000_000, "2076-09", priority="must"), goal("car", 800000, "2031-11")])
    proj, fc, pub = _policy(p)
    assert proj.T == 599
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    out = simulate(p, fc, proj, pub.policy, n_paths=10000, seed=1)
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert out.total_q.shape == (3, 599)
    assert (after - before) / 1024 < 300
