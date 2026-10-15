"""Property test (criterion 4.3): 200 seeded random small problems x strategies.

Every `feasible` result must have zero hard violations under the engine validator AND under the
WP4 independent checker (int_helpers.independent_check); reported metrics must match a
recomputation; the cpsat result may not score worse than the heuristic baseline of the same run;
`infeasible` is only claimed when preflight or CP-SAT proved it.
"""

from __future__ import annotations

import pytest

from int_helpers import independent_check, objective_check, random_doc
from superplanner import engine
from superplanner.engine import OptimizeRequest, Problem

SEEDS = range(200)
STRATEGIES = ["heuristic", "cpsat", "ga", "auto"]


def _proven(out, pf) -> bool:
    if any(i.severity == "error" and i.code in engine.PROVEN_INFEASIBLE_CODES for i in pf.issues):
        return True
    return any(ph.solver == "cpsat" and ph.termination_reason == "proven_infeasible" for ph in out.phases)


@pytest.mark.parametrize("seed", SEEDS)
def test_int_property_random_problem(seed):
    doc = random_doc(seed)
    problem = Problem.model_validate(doc)
    pf = engine.preflight(problem)
    feas = {}
    for strategy in STRATEGIES:
        out = engine.optimize(problem, OptimizeRequest(strategy=strategy, time_limit_seconds=2, seed=seed))
        r = out.result
        feas[strategy] = r.feasibility
        pls = [p.model_dump() for p in r.placements]
        if r.feasibility == "feasible":
            assert pf.ok, (seed, strategy, "feasible despite preflight errors")
            rep = engine.validate_schedule(problem, r.placements)
            assert rep.feasibility == "feasible", (seed, strategy, rep.violations)
            assert [v for v in rep.violations if v.severity == "hard"] == []
            assert independent_check(doc, pls) == [], (seed, strategy)
            assert objective_check(doc, pls, r.metrics.model_dump()) == [], (seed, strategy)
            assert len(pls) == len(doc["tasks"])
        elif r.feasibility == "infeasible":
            assert _proven(out, pf), (seed, strategy, [ph.model_dump() for ph in out.phases])
        if strategy == "cpsat" and r.feasibility == "feasible":
            base = next(ph for ph in out.phases if ph.solver == "heuristic")
            if base.feasibility == "feasible" and base.objectives is not None:
                assert r.objectives.score <= base.objectives.score + 1e-9, (seed, r.objectives, base.objectives)
    # an exact solver must not miss a schedule the heuristic found
    if feas["heuristic"] == "feasible":
        assert feas["cpsat"] == "feasible", (seed, feas)
