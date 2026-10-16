"""Pipeline: stages, calibration, cancellation, feasibility rule (F.10; acceptance 1.8, 1.14, 1.15)."""

import threading
import time

import pytest

from fin_helpers import assert_clean, expense, goal, income, load_fixture, quick_request, run, size_cap_plan, zplan
from superplanner.finance import (DISCLAIMER, FinanceCancelled, FinancePreflightError, FinanceRunRequest, get_template,
                                  run_plan)


def _yp():
    return get_template("young_professional").build(name="t", start_month="2026-11")


def test_preflight_errors_raise():
    p = zplan(goals=[goal(month="2026-10")])
    with pytest.raises(FinancePreflightError) as ei:
        run_plan(p)
    assert any(i.code == "GOAL_TOO_SOON" for i in ei.value.report.issues)


def test_progress_stages_in_order_and_result_shape():
    events = []
    p = load_fixture("typical.finance.json")
    r = run_plan(p, quick_request(calibration_rounds=1, compute_fixes=True), events.append)
    assert_clean(p, r)
    stages = []
    for e in events:
        if not stages or stages[-1] != e.stage:
            stages.append(e.stage)
    order = ["preflight", "cashflow", "optimize", "simulate", "calibrate", "validate", "fixes"]
    assert [s for s in order if s in stages] == [s for s in stages if s in order]
    assert stages[0] == "preflight" and "validate" in stages
    assert any(e.detail.get("tier") == "T0" for e in events)
    assert all(0.0 <= e.fraction <= 1.0 for e in events)
    assert r.disclaimer == DISCLAIMER and r.engine_version == "fin-0.1.0"
    assert r.horizon_months == len(r.series.months) and r.end_month == r.series.months[-1]
    assert {g.goal_id for g in r.goals} == {"car", "trip", "school", "wedding", "retirement"}
    assert r.feasibility == "feasible"


def test_calibration_raises_z_and_probability():
    p = _yp()
    r0 = run(p, simulation={"n_paths": 1000}, calibration_rounds=0)
    r2 = run(p, simulation={"n_paths": 1000}, calibration_rounds=2)
    assert_clean(p, r0)
    assert_clean(p, r2)
    g0 = {g.goal_id: g for g in r0.goals}
    g2 = {g.goal_id: g for g in r2.goals}
    low = [gid for gid, g in g0.items() if g.success_probability < g.min_success_probability - 0.02]
    assert low, "fixture must have a goal below its minimum after round 0"
    assert r2.diagnostics.calibration_rounds >= 1
    for gid in low:
        assert g2[gid].planning_z > g0[gid].planning_z
        assert g2[gid].success_probability >= g0[gid].success_probability


def test_calibration_stops_when_nothing_changes():
    p = zplan(incomes=[income(amount=5000)], expenses=[expense()], goals=[goal(priority="must")])
    r = run(p, calibration_rounds=3)
    assert_clean(p, r)
    assert r.goals[0].success_probability == 1.0
    assert r.diagnostics.calibration_rounds == 0


def test_calibration_never_grows_must_shortfall():
    p = get_template("family").build(name="t", start_month="2026-11")
    r0 = run(p, calibration_rounds=0)
    r3 = run(p, calibration_rounds=3)
    assert_clean(p, r3)
    s0 = sum(g.shortfall_real for g in r0.goals if g.priority == "must")
    s3 = sum(g.shortfall_real for g in r3.goals if g.priority == "must")
    assert s3 <= s0 + 1.0


def _cancel_after(event: threading.Event, delay: float) -> dict:
    stamp: dict = {}

    def fire():
        stamp["t"] = time.monotonic()
        event.set()
    threading.Timer(delay, fire).start()
    return stamp


@pytest.mark.slow
def test_cancel_within_one_second():
    p = size_cap_plan()
    ev = threading.Event()
    stamp = _cancel_after(ev, 0.3)
    with pytest.raises(FinanceCancelled):
        run_plan(p, FinanceRunRequest(), cancel_event=ev)
    assert time.monotonic() - stamp["t"] < 1.0


@pytest.mark.slow
def test_cancel_during_lp_solve():
    p = size_cap_plan()
    ev = threading.Event()
    stamp: dict = {}

    def fire():
        stamp["t"] = time.monotonic()
        ev.set()

    def cb(prog):
        if prog.stage == "optimize" and prog.detail.get("tier") == "T1a" and "armed" not in stamp:
            stamp["armed"] = True
            threading.Timer(0.02, fire).start()          # fires while the T1a solve runs
    t0 = time.monotonic()
    with pytest.raises(FinanceCancelled):
        run_plan(p, FinanceRunRequest(), cb, ev)
    assert "t" in stamp
    assert time.monotonic() - stamp["t"] < 1.0
    assert time.monotonic() - t0 < 30


def test_cancel_before_start_and_in_simulation():
    ev = threading.Event()
    ev.set()
    with pytest.raises(FinanceCancelled):
        run_plan(_yp(), quick_request(), cancel_event=ev)
    ev2 = threading.Event()

    def cb(prog):
        if prog.stage == "simulate":
            ev2.set()
    with pytest.raises(FinanceCancelled):
        run_plan(_yp(), quick_request(), cb, ev2)


def test_feasible_means_no_hard_violation_and_goals_may_be_short():
    p = zplan(incomes=[income(amount=1500)], expenses=[expense()], goals=[goal(priority="must")])
    r = run(p)
    assert_clean(p, r)
    assert r.feasibility == "feasible"
    assert r.goals[0].shortfall_real == pytest.approx(6000, abs=2)
    assert r.goals[0].status == "off_track"
    assert any(v.code == "GOAL_SHORTFALL" for v in r.violations)


def test_status_rule():
    from superplanner.finance.pipeline import goal_status

    assert goal_status(0.0005, 0.9, 0.85) == "on_track"
    assert goal_status(0.0005, 0.70, 0.85) == "at_risk"
    assert goal_status(0.08, 0.10, 0.85) == "at_risk"
    assert goal_status(0.2, 0.5, 0.85) == "off_track"


@pytest.mark.slow
def test_size_cap_plan_solves_clean():
    p = size_cap_plan()
    t = time.monotonic()
    r = run(p, simulation={"n_paths": 100})
    assert time.monotonic() - t < 10.0
    assert_clean(p, r)
    assert r.feasibility == "feasible"


def test_interrupt_solve_stops_a_running_lp():
    """[R11]: the watcher interrupts GLOP inside a solve, not only between solves."""
    from superplanner.finance import project_cashflow
    from superplanner.finance.optimizer import FinanceLP
    from superplanner.finance.returns import initial_z

    p = size_cap_plan(block=6)
    proj = project_cashflow(p)
    z = {g.id: initial_z(g) for g in p.goals}
    full = FinanceLP(p, proj, z)
    full._set_objective(full.tier_list()[1][1])
    t = time.monotonic()
    full._solve_once(time.monotonic() + 60, None)
    full_secs = time.monotonic() - t
    lp = FinanceLP(p, proj, z)
    lp._set_objective(lp.tier_list()[1][1])
    ev = threading.Event()
    threading.Timer(0.03, ev.set).start()
    t = time.monotonic()
    with pytest.raises(FinanceCancelled):
        lp._solve_once(time.monotonic() + 60, ev)
    secs = time.monotonic() - t
    assert secs < 1.0
    if full_secs > 0.2:
        assert secs < full_secs
