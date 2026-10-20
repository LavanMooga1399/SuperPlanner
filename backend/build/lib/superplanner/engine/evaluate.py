"""Candidate evaluation and ranking shared by solvers and the pipeline (ARCHITECTURE 8.0).

Fast path: decoder output + `compute_metrics`. Exact path: the independent `validate()`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .compiled import CompiledProblem
from .decoder import DecodeResult
from .graph import dep_lower_bound
from .model import Placement, Weights
from .objectives import ObjectiveRefs, ObjectiveValues, hard_violation_score, make_values, rank_key
from .validator import ValidationReport, compute_metrics, validate


@dataclass
class Evaluated:
    placements: list[Placement]
    complete: bool
    feasible: bool
    hvs: int
    values: ObjectiveValues
    key: tuple
    solver: str = ""
    report: ValidationReport | None = None


def evaluate_decode(problem: CompiledProblem, dr: DecodeResult, weights: Weights,
                    refs: ObjectiveRefs | None, solver: str = "") -> Evaluated:
    m = compute_metrics(problem, dr.placements)
    pos = {p.task_id: p for p in dr.placements}
    excess = 0
    for t in problem.tasks:
        p = pos.get(t.id)
        if p is not None and t.deadline_hard and t.deadline is not None and p.end > t.deadline:
            excess += p.end - t.deadline
    deficit = 0
    for d in problem.deps:
        a, b = pos.get(problem.tasks[d.pred].id), pos.get(problem.tasks[d.succ].id)
        if a is None or b is None:
            continue
        lb = dep_lower_bound(d.type, d.lag, a.start, a.end, b.end - b.start)
        if b.start < lb:
            deficit += lb - b.start
    unsched = len(dr.unscheduled)
    feasible = unsched == 0 and dr.lock_conflicts == 0 and excess == 0 and deficit == 0
    hvs = hard_violation_score(unsched, dr.lock_conflicts, excess, deficit)
    values = make_values(m.makespan_minutes, m.weighted_tardiness, m.cost, weights, refs)
    return Evaluated(dr.placements, unsched == 0, feasible, hvs, values, rank_key(feasible, hvs, values.score),
                     solver)


def evaluate_validated(problem: CompiledProblem, placements: list[Placement], weights: Weights,
                       refs: ObjectiveRefs | None, solver: str = "") -> Evaluated:
    rep = validate(problem, placements)
    unsched = excess = deficit = other = 0
    for v in rep.violations:
        if v.severity != "hard":
            continue
        if v.code == "TASK_MISSING":
            unsched += 1
        elif v.code == "HARD_DEADLINE_MISSED":
            excess += int(v.details.get("minutes_late", 0))
        elif v.code == "DEPENDENCY_VIOLATED":
            deficit += int(v.details.get("required_minute", 0)) - int(v.details.get("actual_minute", 0))
        elif v.code == "LOCK_VIOLATED":
            deficit += abs(int(v.details.get("start", 0)) - int(v.details.get("locked_start", 0)))
            other += 1
        else:
            other += 1
    feasible = rep.feasibility == "feasible"
    hvs = hard_violation_score(unsched, 0, excess, deficit, other)
    m = rep.metrics
    values = make_values(m.makespan_minutes, m.weighted_tardiness, m.cost, weights, refs)
    return Evaluated(placements, unsched == 0, feasible, hvs, values, rank_key(feasible, hvs, values.score),
                     solver, rep)
