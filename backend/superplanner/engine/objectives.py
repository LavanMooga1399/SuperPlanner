"""Objective weights, normalized score and ranking (ARCHITECTURE section 8.0)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Sequence

from pydantic import BaseModel

from .model import Objectives, Weights

if TYPE_CHECKING:
    from .compiled import CompiledProblem, CResource, CTask

PRESET_WEIGHTS: dict[str, Weights] = {
    "balanced": Weights(makespan=1.0, tardiness=1.0, cost=0.2),
    "finish_asap": Weights(makespan=1.0, tardiness=0.3, cost=0.0),
    "meet_deadlines": Weights(makespan=0.2, tardiness=1.0, cost=0.0),
    "lowest_cost": Weights(makespan=0.2, tardiness=0.5, cost=1.0),
}

HARD_UNSCHEDULED = 1_000_000
HARD_LOCK_CONFLICT = 10_000


class ObjectiveValues(BaseModel):
    makespan_minutes: int
    weighted_tardiness: int
    cost: float
    score: float


class ObjectiveRefs(BaseModel):
    makespan: float = 1.0
    weighted_tardiness: float = 1.0
    cost: float = 1.0


def effective_weights(objectives: Objectives) -> Weights:
    if objectives.preset == "custom":
        return objectives.weights
    return PRESET_WEIGHTS[objectives.preset]


def cost_of(task: "CTask", resource: "CResource", units: int) -> float:
    return resource.cost_per_hour * units * task.duration / 60.0


def score_of(makespan: float, weighted_tardiness: float, cost: float, weights: Weights, refs: ObjectiveRefs) -> float:
    return (
        weights.makespan * makespan / refs.makespan
        + weights.tardiness * weighted_tardiness / refs.weighted_tardiness
        + weights.cost * cost / refs.cost
    )


def make_values(makespan: int, weighted_tardiness: int, cost: float, weights: Weights,
                refs: ObjectiveRefs | None) -> ObjectiveValues:
    cost = round(cost, 2)
    sc = score_of(makespan, weighted_tardiness, cost, weights, refs) if refs is not None else 0.0
    return ObjectiveValues(makespan_minutes=makespan, weighted_tardiness=weighted_tardiness, cost=cost,
                           score=round(sc, 6))


def rescore(values: ObjectiveValues, weights: Weights, refs: ObjectiveRefs) -> ObjectiveValues:
    return make_values(values.makespan_minutes, values.weighted_tardiness, values.cost, weights, refs)


def compute_refs(rule_objectives: Sequence[ObjectiveValues | None], problem: "CompiledProblem",
                 cpm: Any) -> ObjectiveRefs:
    """Per-objective minimum over complete rule results (None = incomplete), floored at 1.

    `cpm` is a `CpmResult` (duck-typed so this module does not import `graph`) or the CPM
    lower-bound makespan as an int.
    """
    lower_bound_makespan = int(getattr(cpm, "lower_bound_makespan_minutes", cpm) or 0)
    complete = [o for o in rule_objectives if o is not None]
    if complete:
        return ObjectiveRefs(
            makespan=max(1.0, float(min(o.makespan_minutes for o in complete))),
            weighted_tardiness=max(1.0, float(min(o.weighted_tardiness for o in complete))),
            cost=max(1.0, float(min(o.cost for o in complete))),
        )
    wt = sum(t.priority * t.duration for t in problem.tasks)
    cost = 0.0
    for t in problem.tasks:
        for req in t.requirements:
            if req.alternatives:
                cost += min(cost_of(t, problem.resources[k], req.units) for k in req.alternatives)
    return ObjectiveRefs(makespan=max(1.0, float(lower_bound_makespan)),
                         weighted_tardiness=max(1.0, float(wt)), cost=max(1.0, cost))


def hard_violation_score(unscheduled: int, lock_conflicts: int, deadline_excess: int, deficit: int,
                         other_hard: int = 0) -> int:
    return (HARD_UNSCHEDULED * unscheduled + HARD_LOCK_CONFLICT * (lock_conflicts + other_hard)
            + deadline_excess + deficit)


def rank_key(feasible: bool, hvs: int, score: float) -> tuple[int, int, float]:
    return (0 if feasible else 1, 0 if feasible else hvs, score)


def dominates(a: Iterable[float], b: Iterable[float]) -> bool:
    a, b = list(a), list(b)
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))
