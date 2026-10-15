"""Transparent rule-based solver selection (ARCHITECTURE 8.7 step 5)."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from .compiled import CompiledProblem

CPSAT_MAX_TASKS = 300
CPSAT_MAX_OPTIONALS = 3000
MIN_BUDGET_FOR_SEARCH = 2.0

CPM_REASON = "No task needs a resource: the earliest-start (critical path) schedule is provably optimal."
FALLBACK_REASON = "Constraint solver found no solution in time; continuing with the genetic algorithm."


class Selection(BaseModel):
    requested: str
    used: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


@dataclass
class Plan:
    """Phases after the baseline, with their share of the remaining budget."""

    phases: list[tuple[str, float]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def size_measures(problem: CompiledProblem) -> tuple[int, int]:
    n = sum(1 for t in problem.tasks if t.locked_start is None)
    q = sum(len(r.alternatives) for t in problem.tasks for r in t.requirements)
    return n, q


def is_resource_free(problem: CompiledProblem) -> bool:
    return all(not t.requirements and t.locked_start is None for t in problem.tasks)


def plan_strategy(requested: str, problem: CompiledProblem, time_limit: float) -> Plan:
    n, q = size_measures(problem)
    if requested == "heuristic":
        return Plan([], ["Heuristic requested: fast priority rules only."])
    if requested == "cpsat":
        return Plan([("cpsat", 1.0)], ["Constraint solver requested, seeded with the best heuristic schedule."])
    if requested == "ga":
        return Plan([("ga", 1.0)], ["Genetic algorithm requested, seeded with heuristic schedules."])
    if requested == "hybrid":
        return Plan([("cpsat", 0.6), ("ga", 1.0)],
                    ["Hybrid requested: constraint solver (60% of the time), then the genetic algorithm seeded "
                     "with the best schedule so far."])
    if time_limit < MIN_BUDGET_FOR_SEARCH:
        return Plan([], ["Time budget under 2 s: using fast priority rules only."])
    if n <= CPSAT_MAX_TASKS and q <= CPSAT_MAX_OPTIONALS:
        return Plan([("cpsat", 1.0)],
                    [f"Small/medium problem ({n} tasks, {q} options): exact constraint solver seeded with the "
                     "best heuristic."])
    return Plan([("ga", 1.0)], ["Large problem: genetic algorithm seeded with heuristic schedules."])
