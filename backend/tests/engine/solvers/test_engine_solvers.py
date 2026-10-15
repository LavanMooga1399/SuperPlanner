"""A.8.3-8.5: heuristic, CP-SAT and GA solvers; every result is checked by the independent validator."""

import itertools
import random
import threading
import time

import pytest

from engine_helpers import at, compiled, dep, load_fixture, lock, problem, random_problem, res, task
from superplanner.engine.compiled import build_compiled
from superplanner.engine.decoder import decode
from superplanner.engine.evaluate import evaluate_decode
from superplanner.engine.graph import cpm
from superplanner.engine.model import Calendar, Requirement
from superplanner.engine.solvers import SOLVERS, get_solver
from superplanner.engine.solvers.base import GaParams, SolverConfig
from superplanner.engine.solvers.cpsat import CpSatSolver
from superplanner.engine.solvers.ga import GaSolver
from superplanner.engine.solvers.heuristic import HeuristicSolver, rule_priorities
from superplanner.engine.validator import compute_metrics, validate
from superplanner.engine.objectives import make_values


def _refs(cp):
    _, refs, _ = HeuristicSolver().solve_with_refs(cp, SolverConfig(weights=cp.weights))
    return refs


def test_registry():
    assert set(SOLVERS) == {"heuristic", "cpsat", "ga"}
    for name in SOLVERS:
        assert get_solver(name).name == name
    assert HeuristicSolver.capabilities.deterministic_with_seed and not HeuristicSolver.capabilities.proves_optimality
    assert CpSatSolver.capabilities.proves_infeasibility and not CpSatSolver.capabilities.deterministic_with_seed
    assert GaSolver.capabilities.multi_objective


@pytest.mark.parametrize("fixture", ["example_3_11", "flexible_jobshop_10x5", "calendar_heavy"])
@pytest.mark.parametrize("solver", ["heuristic", "cpsat", "ga"])
def test_solvers_feasible_on_fixtures(fixture, solver):
    cp = compiled(load_fixture(fixture))
    refs = _refs(cp)
    cfg = SolverConfig(time_limit_seconds=2, weights=cp.weights, refs=refs,
                       ga=GaParams(max_generations=30))
    r = get_solver(solver).solve(cp, cfg)
    assert r.feasibility == "feasible"
    rep = validate(cp, r.placements)
    assert rep.feasibility == "feasible", rep.violations
    assert r.solver.split(":")[0] == solver


def test_heuristic_rules_and_names():
    cp = compiled(load_fixture("flexible_jobshop_10x5"))
    r = HeuristicSolver().solve(cp, SolverConfig(weights=cp.weights))
    assert r.iterations == 5 and r.termination_reason == "completed"
    assert r.solver in {f"heuristic:{x}" for x in ("edf", "slack", "spt", "lpt", "priority")}
    c = cpm(cp)
    for rule in ("edf", "slack", "spt", "lpt", "priority"):
        pri = rule_priorities(cp, rule, c)
        assert sorted(pri) == [i / len(cp.tasks) for i in range(len(cp.tasks))]


def test_spt_lpt_order():
    cp = compiled(problem([task("A", 30, ["R"]), task("B", 90, ["R"]), task("C", 60, ["R"])], [res("R")]))
    c = cpm(cp)
    spt = rule_priorities(cp, "spt", c)
    lpt = rule_priorities(cp, "lpt", c)
    assert spt.index(min(spt)) == 0 and lpt.index(min(lpt)) == 1


def _tiny(seed):
    rng = random.Random(seed)
    cal = Calendar(weekly={d: [("02:00", "10:00"), ("12:00", "20:00")] for d in ("mon", "tue", "wed", "thu", "fri",
                                                                                "sat", "sun")})
    resources = [res("R0", cap=1, cost=float(rng.randint(0, 60)), calendar=cal if rng.random() < 0.5 else None),
                 res("R1", cap=rng.choice([1, 2]), cost=float(rng.randint(0, 60)))]
    tasks = []
    for i in range(rng.randint(3, 5)):
        alts = rng.choice([["R0"], ["R1"], ["R0", "R1"], ["R1", "R0"]])
        kw = {"deadline": at(rng.randint(100, 600))} if rng.random() < 0.5 else {}
        if rng.random() < 0.3:
            kw["earliest_start"] = at(rng.randint(0, 200))
        tasks.append(task(f"T{i}", rng.randint(20, 150), alts, priority=rng.randint(1, 10), **kw))
    deps = []
    for i in range(1, len(tasks)):
        if rng.random() < 0.5:
            # FS/SS with non-negative lags keep the start-time order topological, so the serial SGS over
            # all lists and resource choices provably contains an optimum (FF/SF are covered elsewhere).
            deps.append(dep(f"T{rng.randrange(i)}", f"T{i}", rng.choice(["FS", "SS"]),
                            rng.choice([0, 15])))
    return problem(tasks, resources, deps, days=3)


def _brute_force(cp, refs):
    n = len(cp.tasks)
    slots = [(t.idx, i, len(r.alternatives)) for t in cp.tasks for i, r in enumerate(t.requirements)
             if len(r.alternatives) > 1]
    best = None
    for perm in itertools.permutations(range(n)):
        pri = [0.0] * n
        for pos, i in enumerate(perm):
            pri[i] = float(pos)
        for choice in itertools.product(*[range(k) for _, _, k in slots]):
            rc = {(ti, ri): c for (ti, ri, _), c in zip(slots, choice)}
            ev = evaluate_decode(cp, decode(cp, pri, rc), cp.weights, refs)
            if ev.feasible and (best is None or ev.values.score < best):
                best = ev.values.score
    return best


@pytest.mark.parametrize("seed", range(20))
def test_cpsat_optimal_equals_brute_force(seed):
    cp = compiled(_tiny(seed))
    refs = _refs(cp)
    r = CpSatSolver().solve(cp, SolverConfig(time_limit_seconds=20, weights=cp.weights, refs=refs))
    assert r.optimality_proven and r.termination_reason == "optimal"
    assert validate(cp, r.placements).feasibility == "feasible"
    met = compute_metrics(cp, r.placements)
    score = make_values(met.makespan_minutes, met.weighted_tardiness, met.cost, cp.weights, refs).score
    assert score == pytest.approx(_brute_force(cp, refs), abs=1e-5)


def test_cpsat_proves_infeasible_overlapping_locks():
    cp = compiled(problem([task("A", 60, ["R"], locked=lock(0)), task("B", 60, ["R"], locked=lock(30))],
                          [res("R")]))
    r = CpSatSolver().solve(cp, SolverConfig(time_limit_seconds=5, weights=cp.weights, refs=_refs(cp)))
    assert r.feasibility == "infeasible" and r.termination_reason == "proven_infeasible"
    assert r.placements == []


def test_cpsat_hint_and_calendars_and_multi_units():
    cp = compiled(problem([task("A", 120, requirements=[Requirement(alternatives=["OVEN"], units=2)]),
                           task("B", 120, requirements=[Requirement(alternatives=["OVEN"], units=2)]),
                           task("C", 60, [["X", "Y"], ["X", "Y"]])],
                          [res("OVEN", cap=3, calendar=Calendar(weekly={"mon": [("08:00", "12:00")]})),
                           res("X"), res("Y")], days=2))
    h = HeuristicSolver().solve(cp, SolverConfig(weights=cp.weights))
    r = CpSatSolver().solve(cp, SolverConfig(time_limit_seconds=5, weights=cp.weights, refs=_refs(cp),
                                             initial_solution=h.placements))
    assert r.feasibility == "feasible" and validate(cp, r.placements).feasibility == "feasible"
    p = {x.task_id: x for x in r.placements}
    assert {p["A"].start, p["B"].start} == {480, 600}
    assert sorted(p["C"].resource_ids) == ["X", "Y"]


def test_ga_deterministic_with_generation_stop():
    cp = compiled(load_fixture("flexible_jobshop_10x5"))
    refs = _refs(cp)
    cfg = SolverConfig(time_limit_seconds=60, seed=7, weights=cp.weights, refs=refs,
                       ga=GaParams(max_generations=15, stagnation_generations=1000, population_size=20))
    rates = []

    def cb(ev):
        rates.append(ev.extra["mutation_rate"])
        assert set(ev.extra) >= {"feasible_fraction", "mutation_rate", "diversity"}

    a = GaSolver().solve(cp, cfg, cb)
    b = GaSolver().solve(cp, cfg)
    assert a.termination_reason == b.termination_reason == "generation_limit"
    assert a.iterations == 15
    assert a.placements == b.placements
    assert rates and min(rates) >= 0.01
    assert validate(cp, a.placements).feasibility == "feasible"


def test_ga_never_infeasible_on_hard_instance():
    p = problem([task("A", 60, ["R"], deadline=at(70), deadline_hard=True),
                 task("B", 60, ["R"], deadline=at(70), deadline_hard=True)], [res("R")])
    cp = compiled(p)
    r = GaSolver().solve(cp, SolverConfig(time_limit_seconds=1, weights=cp.weights, refs=_refs(cp)))
    assert r.feasibility == "unknown"
    assert validate(cp, r.placements).feasibility == "unknown"


def test_ga_mutation_rate_adapts_but_stays_bounded():
    cp = compiled(load_fixture("example_3_11"))
    rates = []
    GaSolver().solve(cp, SolverConfig(time_limit_seconds=30, weights=cp.weights, refs=_refs(cp),
                                      ga=GaParams(max_generations=60, stagnation_generations=1000,
                                                  mutation_rate=0.01)),
                     lambda ev: rates.append(ev.extra["mutation_rate"]))
    assert min(rates) >= 0.01 and max(rates) > 0.01 and max(rates) <= 0.5


@pytest.mark.parametrize("solver", ["ga", "cpsat"])
def test_solver_cancel(solver):
    cp = compiled(load_fixture("flexible_jobshop_10x5"))
    cancel = threading.Event()
    cfg = SolverConfig(time_limit_seconds=30, weights=cp.weights, refs=_refs(cp),
                       ga=GaParams(max_generations=10000, stagnation_generations=1000))
    threading.Timer(0.5, cancel.set).start()
    t0 = time.monotonic()
    r = get_solver(solver).solve(cp, cfg, None, cancel)
    assert time.monotonic() - t0 < 2.0
    assert r.status == "cancelled" and r.termination_reason == "cancelled"
