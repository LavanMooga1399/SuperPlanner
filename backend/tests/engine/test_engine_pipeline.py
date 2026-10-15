"""A.8.6/8.7 pipeline: selection, budget, honest status, never worse than baseline, probe, alternatives."""

import threading
import time

import pytest

from engine_helpers import FEASIBLE_FIXTURES, FIXTURES, at, compiled, dep, load_fixture, lock, problem, res, task
from superplanner.engine import OptimizeRequest, analyze, optimize, validate_schedule
from superplanner.engine.solvers.base import GaParams, SolveResult
from superplanner.engine.solvers.cpsat import CpSatSolver

STRATEGIES = ["heuristic", "cpsat", "ga", "hybrid", "auto"]
_CACHE: dict = {}


def run(fixture, strategy, tl=2.0):
    key = (fixture, strategy, tl)
    if key not in _CACHE:
        events = []
        out = optimize(load_fixture(fixture), OptimizeRequest(strategy=strategy, time_limit_seconds=tl),
                       events.append)
        _CACHE[key] = (out, events)
    return _CACHE[key]


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("fixture", FIXTURES)
def test_all_output_validated(fixture, strategy):
    out, _ = run(fixture, strategy)
    p = load_fixture(fixture)
    if fixture == "infeasible_hard_deadline":
        assert out.result.feasibility == "infeasible"
        assert out.result.termination_reason == "preflight_failed"
        assert out.result.diagnostics and "Weld" in out.result.diagnostics[0]
        return
    assert out.result.feasibility == "feasible"
    rep = validate_schedule(p, out.result.placements)  # independent of the result's own violations
    assert [v for v in rep.violations if v.severity == "hard"] == []
    assert {pl.task_id for pl in out.result.placements} == {t.id for t in p.tasks}
    for alt in out.result.alternatives:
        assert validate_schedule(p, alt.placements).feasibility == "feasible"
        assert alt.label


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("fixture", FEASIBLE_FIXTURES)
def test_never_worse_than_baseline(fixture, strategy):
    out, _ = run(fixture, strategy)
    base = out.phases[0]
    assert out.result.objectives.score <= base.objectives.score + 1e-9


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_resource_free_shortcut(strategy):
    out, events = run("precedence_only", strategy)
    lb = analyze(load_fixture("precedence_only")).cpm.lower_bound_makespan_minutes
    assert out.selection.used == ["cpm"]
    assert out.result.optimality_proven and out.result.termination_reason == "optimal"
    assert out.result.solver == "cpm"
    assert out.result.objectives.makespan_minutes == lb
    assert "provably optimal" in out.selection.reasons[0]
    assert [e.type for e in events] == ["phase_started", "phase_completed"]


def test_progress_events_phase_names_and_mapping():
    out, events = run("flexible_jobshop_10x5", "hybrid")
    assert {e.solver for e in events} <= {"heuristic", "cpsat", "ga"}
    started = [e for e in events if e.type == "phase_started"]
    completed = [e for e in events if e.type == "phase_completed"]
    assert [e.solver for e in started] == out.selection.used == ["heuristic", "cpsat", "ga"]
    assert all(e.extra.get("reason") for e in started)
    assert all({"status", "termination_reason", "feasibility"} <= set(e.extra) for e in completed)
    assert [p.solver for p in out.phases] == out.selection.used
    elapsed = [e.elapsed_seconds for e in events]
    assert elapsed == sorted(elapsed)


def test_selector_rows():
    small = load_fixture("example_3_11")
    for strategy, used in [("heuristic", ["heuristic"]), ("cpsat", ["heuristic", "cpsat"]),
                           ("ga", ["heuristic", "ga"]), ("hybrid", ["heuristic", "cpsat", "ga"])]:
        out = optimize(small, OptimizeRequest(strategy=strategy, time_limit_seconds=2))
        assert out.selection.used == used and out.selection.reasons and all(out.selection.reasons)
    out = optimize(small, OptimizeRequest(strategy="auto", time_limit_seconds=1.5))
    assert out.selection.used == ["heuristic"]
    assert out.selection.reasons == ["Time budget under 2 s: using fast priority rules only."]
    out = optimize(small, OptimizeRequest(strategy="auto", time_limit_seconds=3))
    assert out.selection.used == ["heuristic", "cpsat"]
    assert out.selection.reasons[0].startswith("Small/medium problem (2 tasks, 3 options)")


def test_selector_large_problem_uses_ga():
    tasks = [task(f"T{i}", 10, ["R", "S"]) for i in range(301)]
    p = problem(tasks, [res("R", cap=50), res("S", cap=50)], days=3)
    out = optimize(p, OptimizeRequest(strategy="auto", time_limit_seconds=2,
                                      ga=GaParams(max_generations=2)))
    assert out.selection.used == ["heuristic", "ga"]
    assert out.selection.reasons[0].startswith("Large problem")
    assert out.result.feasibility == "feasible"


def test_auto_falls_back_to_ga_when_cpsat_unknown(monkeypatch):
    def fake_solve(self, problem, config, progress_cb=None, cancel_event=None):
        return SolveResult(solver="cpsat", status="completed", feasibility="unknown", termination_reason="time_limit",
                           optimality_proven=False, objectives=None, placements=[], elapsed_seconds=0.0)

    monkeypatch.setattr(CpSatSolver, "solve", fake_solve)
    out = optimize(load_fixture("example_3_11"), OptimizeRequest(strategy="auto", time_limit_seconds=4,
                                                                 ga=GaParams(max_generations=5)))
    assert out.selection.used == ["heuristic", "cpsat", "ga"]
    assert out.selection.reasons[-1] == ("Constraint solver found no solution in time; continuing with the genetic "
                                         "algorithm.")
    assert out.result.feasibility == "feasible"


def test_cpsat_proves_infeasible_without_preflight_error():
    p = problem([task("A", 60, ["R"], name="Cutting", locked=lock(0)),
                 task("B", 60, ["R"], name="Milling", locked=lock(30))], [res("R")])
    assert analyze(p).ok
    out = optimize(p, OptimizeRequest(strategy="cpsat", time_limit_seconds=3))
    assert out.result.feasibility == "infeasible"
    cps = next(ph for ph in out.phases if ph.solver == "cpsat")
    assert cps.termination_reason == "proven_infeasible"
    assert out.result.placements  # best-effort schedule still returned, flagged
    assert any(v.code == "CAPACITY_EXCEEDED" for v in out.result.violations)
    assert any("Unlocking" in d and "Cutting" in d for d in out.result.diagnostics)


def test_heuristic_alone_never_claims_infeasible():
    p = problem([task("A", 60, ["R"], deadline=at(70), deadline_hard=True),
                 task("B", 60, ["R"], deadline=at(70), deadline_hard=True)], [res("R")])
    for s in ("heuristic", "ga"):
        out = optimize(p, OptimizeRequest(strategy=s, time_limit_seconds=1))
        assert out.result.feasibility == "unknown"


def test_infeasibility_probe_names_task_and_lateness():
    # each deadline is reachable alone (preflight ok); only the shared machine makes one of them late
    p = problem([task("A", 60, ["R"], name="Cutting", priority=9, deadline=at(60), deadline_hard=True),
                 task("B", 90, ["R"], name="Milling", deadline=at(100), deadline_hard=True)], [res("R")])
    assert analyze(p).ok
    out = optimize(p, OptimizeRequest(strategy="heuristic", time_limit_seconds=4))
    assert out.result.feasibility == "unknown"
    assert any('"Milling"' in d and "late by 50m" in d for d in out.result.diagnostics), out.result.diagnostics
    out2 = optimize(p, OptimizeRequest(strategy="cpsat", time_limit_seconds=4))
    assert out2.result.feasibility == "infeasible"
    assert any('"Milling"' in d for d in out2.result.diagnostics)


@pytest.mark.parametrize("strategy", ["ga", "cpsat"])
def test_cancel_returns_quickly(strategy):
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    t0 = time.monotonic()
    out = optimize(load_fixture("flexible_jobshop_10x5"),
                   OptimizeRequest(strategy=strategy, time_limit_seconds=30,
                                   ga=GaParams(max_generations=10000, stagnation_generations=1000)),
                   None, cancel)
    assert time.monotonic() - t0 < 2.0
    assert out.result.status == "cancelled" and out.result.termination_reason == "cancelled"
    assert out.result.placements  # best-so-far is kept


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_budget_respected(strategy):
    t0 = time.monotonic()
    optimize(load_fixture("flexible_jobshop_10x5"), OptimizeRequest(strategy=strategy, time_limit_seconds=5))
    assert time.monotonic() - t0 < 8.0


def test_preflight_failure_unknown_for_malformed_input():
    p = problem([task("A", 10, ["GHOST"])], [])
    out = optimize(p)
    assert out.result.feasibility == "unknown" and out.result.termination_reason == "preflight_failed"
    cyc = problem([task("A", 10), task("B", 10)], [], [dep("A", "B"), dep("B", "A")])
    assert optimize(cyc).result.feasibility == "infeasible"


def test_locks_respected_in_final_schedule():
    p = load_fixture("calendar_heavy")
    for strategy in ("heuristic", "cpsat", "ga"):
        out, _ = run("calendar_heavy", strategy)
        c1 = next(x for x in out.result.placements if x.task_id == "C1")
        assert c1.start == 480 and c1.resource_ids == ["DAY"]
        assert out.explanation.tasks["C1"].reasons[0].code == "LOCKED"
    assert p


def test_objective_override_and_metrics():
    p = load_fixture("flexible_jobshop_10x5")
    from superplanner.engine.model import Objectives
    out = optimize(p, OptimizeRequest(strategy="heuristic", time_limit_seconds=1,
                                      objectives=Objectives(preset="lowest_cost")))
    m = out.result.metrics
    assert m.scheduled_tasks == m.total_tasks == 50
    assert out.result.objectives.cost == m.cost
    assert out.refs.makespan >= 1 and out.refs.cost >= 1


def test_alternatives_labels_and_distinct():
    out, _ = run("calendar_heavy", "hybrid")
    prim = (out.result.objectives.makespan_minutes, out.result.objectives.weighted_tardiness, out.result.objectives.cost)
    vecs = [(a.objectives.makespan_minutes, a.objectives.weighted_tardiness, a.objectives.cost)
            for a in out.result.alternatives]
    assert prim not in vecs and len(set(vecs)) == len(vecs)
    assert len(vecs) <= 2


def test_empty_problem():
    out = optimize(problem([], []))
    assert out.result.feasibility == "feasible" and out.result.placements == []


@pytest.mark.parametrize("seed", range(12))
def test_random_problems_all_strategies_validated(seed):
    from engine_helpers import random_problem
    p = random_problem(1000 + seed, n_tasks=10, n_res=3)
    if not analyze(p).ok:
        pytest.skip("random instance has preflight errors")
    for strategy in ("heuristic", "cpsat", "ga", "auto"):
        out = optimize(p, OptimizeRequest(strategy=strategy, time_limit_seconds=1, seed=seed,
                                          ga=GaParams(max_generations=10)))
        assert out.result.feasibility in ("feasible", "unknown", "infeasible")
        rep = validate_schedule(p, out.result.placements)
        assert (rep.feasibility == "feasible") == (out.result.feasibility == "feasible")
        if out.result.feasibility == "infeasible":
            assert any(ph.termination_reason == "proven_infeasible" for ph in out.phases)
        assert out.result.objectives.score <= out.phases[0].objectives.score + 1e-9
