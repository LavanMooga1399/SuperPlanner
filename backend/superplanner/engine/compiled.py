"""Compiled (internal) model (ARCHITECTURE section 6)."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Mapping

from .model import Objectives, Problem, Terminology, Weights
from .objectives import effective_weights
from .timeutil import expand_windows, to_minute

if TYPE_CHECKING:
    from .preflight import Issue


class CompileError(Exception):
    """Raised when a problem with preflight errors is compiled."""

    def __init__(self, issues: "list[Issue]"):
        self.issues = issues
        msgs = "; ".join(i.message for i in issues[:5])
        super().__init__(f"Problem has {len(issues)} blocking issue(s): {msgs}")


@dataclass(frozen=True, slots=True)
class CRequirement:
    units: int
    alternatives: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CTask:
    idx: int
    id: str
    name: str
    is_milestone: bool
    duration: int
    release: int
    deadline: int | None
    deadline_hard: bool
    priority: int
    requirements: tuple[CRequirement, ...]
    locked_start: int | None
    locked_resources: tuple[int, ...] | None
    group: str | None = None
    estimate: tuple[int, int, int] | None = None   # (optimistic, likely, pessimistic) minutes, PHASE2 2.14


@dataclass(frozen=True, slots=True)
class CResource:
    idx: int
    id: str
    name: str
    capacity: int
    cost_per_hour: float
    windows: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class CDependency:
    pred: int
    succ: int
    type: Literal["FS", "SS", "FF", "SF"]
    lag: int


@dataclass(frozen=True, slots=True)
class CompiledProblem:
    problem_id: str
    horizon_start: datetime
    H: int
    tasks: tuple[CTask, ...]
    resources: tuple[CResource, ...]
    deps: tuple[CDependency, ...]
    preds: tuple[tuple[int, ...], ...]
    succs: tuple[tuple[int, ...], ...]
    topo_order: tuple[int, ...]
    weights: Weights
    task_index: Mapping[str, int]
    resource_index: Mapping[str, int]
    terminology: Terminology = field(default_factory=Terminology)


def kahn_order(n: int, edges: list[tuple[int, int]]) -> list[int] | None:
    """Kahn's algorithm with ties broken by index; None if a cycle exists."""
    indeg = [0] * n
    adj: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        adj[a].append(b)
        indeg[b] += 1
    heap = [i for i in range(n) if indeg[i] == 0]
    heapq.heapify(heap)
    order: list[int] = []
    while heap:
        v = heapq.heappop(heap)
        order.append(v)
        for w in adj[v]:
            indeg[w] -= 1
            if indeg[w] == 0:
                heapq.heappush(heap, w)
    return order if len(order) == n else None


def build_compiled(problem: Problem, objectives: Objectives | None = None) -> CompiledProblem:
    """Build the compiled model without running preflight (caller guarantees structure)."""
    hs = problem.horizon_start
    H = problem.horizon_days * 1440
    res_index = {r.id: i for i, r in enumerate(problem.resources)}
    resources = tuple(
        CResource(idx=i, id=r.id, name=r.name, capacity=r.capacity, cost_per_hour=float(r.cost_per_hour),
                  windows=tuple(expand_windows(r.calendar, hs, H)))
        for i, r in enumerate(problem.resources)
    )
    tasks: list[CTask] = []
    for i, t in enumerate(problem.tasks):
        reqs = []
        for rq in t.requirements:
            alts = tuple(res_index[a] for a in rq.alternatives
                         if a in res_index and resources[res_index[a]].capacity >= rq.units)
            reqs.append(CRequirement(units=rq.units, alternatives=alts))
        release = 0 if t.earliest_start is None else max(0, to_minute(t.earliest_start, hs))
        deadline = None if t.deadline is None else to_minute(t.deadline, hs)
        locked_start = locked_res = None
        if t.locked is not None:
            locked_start = to_minute(t.locked.start, hs)
            if t.locked.resource_ids is not None and t.type != "milestone":
                locked_res = tuple(res_index[r] for r in t.locked.resource_ids if r in res_index)
                if len(locked_res) != len(t.requirements):
                    locked_res = None
        tasks.append(CTask(
            idx=i, id=t.id, name=t.name, is_milestone=t.type == "milestone",
            duration=t.duration_minutes if t.type == "activity" else 0,
            release=release, deadline=deadline, deadline_hard=bool(t.deadline_hard and deadline is not None),
            priority=t.priority, requirements=tuple(reqs), locked_start=locked_start,
            locked_resources=locked_res, group=t.group,
            estimate=None if t.duration_estimate is None or t.type == "milestone" else (
                t.duration_estimate.optimistic_minutes, t.duration_estimate.likely_minutes,
                t.duration_estimate.pessimistic_minutes),
        ))
    task_index = {t.id: i for i, t in enumerate(problem.tasks)}
    deps = tuple(CDependency(pred=task_index[d.predecessor], succ=task_index[d.successor], type=d.type,
                             lag=d.lag_minutes) for d in problem.dependencies)
    n = len(tasks)
    preds: list[list[int]] = [[] for _ in range(n)]
    succs: list[list[int]] = [[] for _ in range(n)]
    for j, d in enumerate(deps):
        preds[d.succ].append(j)
        succs[d.pred].append(j)
    order = kahn_order(n, [(d.pred, d.succ) for d in deps])
    if order is None:
        raise ValueError("dependency graph has a cycle")
    w = effective_weights(objectives if objectives is not None else problem.objectives)
    return CompiledProblem(
        problem_id=problem.id, horizon_start=hs, H=H, tasks=tuple(tasks), resources=resources, deps=deps,
        preds=tuple(tuple(p) for p in preds), succs=tuple(tuple(s) for s in succs), topo_order=tuple(order),
        weights=w, task_index=MappingProxyType(task_index), resource_index=MappingProxyType(res_index),
        terminology=problem.terminology,
    )


def compile_problem(problem: Problem, objectives: Objectives | None = None) -> CompiledProblem:
    """Compile a problem; raises `CompileError(issues)` when preflight reports errors."""
    from .preflight import preflight  # local import: preflight builds on this module

    report = preflight(problem)
    errors = [i for i in report.issues if i.severity == "error"]
    if errors:
        raise CompileError(errors)
    return build_compiled(problem, objectives)
