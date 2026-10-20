"""Independent schedule validator (ARCHITECTURE section 10).

Written against section 5 only. Must not import the decoder, graph helpers or any solver.
"""

from __future__ import annotations

import bisect
from typing import Any, Literal

from pydantic import BaseModel, Field

from .compiled import CompiledProblem
from .model import Placement
from .objectives import cost_of
from .timeutil import fmt_duration, fmt_minute

_DEP_WORDS = {"FS": "finish-to-start", "SS": "start-to-start", "FF": "finish-to-finish", "SF": "start-to-finish"}


class Violation(BaseModel):
    code: str
    severity: Literal["hard", "soft"]
    task_ids: list[str]
    resource_ids: list[str]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Metrics(BaseModel):
    makespan_minutes: int
    total_tardiness_minutes: int
    weighted_tardiness: int
    late_tasks: int
    hard_deadline_misses: int
    cost: float
    scheduled_tasks: int
    total_tasks: int
    utilization: dict[str, float]


class ValidationReport(BaseModel):
    feasibility: Literal["feasible", "unknown"]
    violations: list[Violation]
    metrics: Metrics


def _known_unique(problem: CompiledProblem, placements: list[Placement]) -> dict[int, Placement]:
    out: dict[int, Placement] = {}
    for p in placements:
        idx = problem.task_index.get(p.task_id)
        if idx is not None and idx not in out:
            out[idx] = p
    return out


def compute_metrics(problem: CompiledProblem, placements: list[Placement]) -> Metrics:
    placed = _known_unique(problem, placements)
    makespan = max((p.end for p in placed.values()), default=0)
    tard = wtard = late = hard_miss = 0
    cost = 0.0
    busy = [0] * len(problem.resources)
    for idx, p in placed.items():
        t = problem.tasks[idx]
        if t.deadline is not None and p.end > t.deadline:
            if t.deadline_hard:
                hard_miss += 1
            else:
                lt = p.end - t.deadline
                tard += lt
                wtard += t.priority * lt
                late += 1
        for i, rid in enumerate(p.resource_ids):
            k = problem.resource_index.get(rid)
            if k is None or i >= len(t.requirements):
                continue
            units = t.requirements[i].units
            cost += cost_of(t, problem.resources[k], units)
            busy[k] += units * max(0, min(p.end, makespan) - max(p.start, 0))
    util: dict[str, float] = {}
    for r in problem.resources:
        avail = sum(max(0, min(e, makespan) - max(s, 0)) for s, e in r.windows)
        denom = r.capacity * avail
        util[r.id] = round(busy[r.idx] / denom, 4) if denom > 0 else 0.0
    return Metrics(makespan_minutes=makespan, total_tardiness_minutes=tard, weighted_tardiness=wtard,
                   late_tasks=late, hard_deadline_misses=hard_miss, cost=round(cost, 2),
                   scheduled_tasks=len(placed), total_tasks=len(problem.tasks), utilization=util)


def _in_one_window(windows: tuple[tuple[int, int], ...], starts: list[int], s: int, e: int) -> bool:
    pos = bisect.bisect_right(starts, s) - 1
    return pos >= 0 and windows[pos][0] <= s and e <= windows[pos][1]


def validate(problem: CompiledProblem, placements: list[Placement]) -> ValidationReport:
    term = problem.terminology
    hs = problem.horizon_start
    H = problem.H
    v: list[Violation] = []

    def tn(idx: int) -> str:
        return f'{term.task} "{problem.tasks[idx].name}"'

    def add(code: str, severity: str, task_ids: list[str], resource_ids: list[str], message: str, **details):
        v.append(Violation(code=code, severity=severity, task_ids=task_ids, resource_ids=resource_ids,
                           message=message, details=details))

    # H1: placed exactly once, no unknown ids
    counts: dict[str, int] = {}
    for p in placements:
        counts[p.task_id] = counts.get(p.task_id, 0) + 1
    for tid, c in counts.items():
        if tid not in problem.task_index:
            add("UNKNOWN_TASK", "hard", [tid], [], f'The schedule contains an unknown {term.task.lower()} "{tid}".')
        elif c > 1:
            add("TASK_DUPLICATE", "hard", [tid], [],
                f"{tn(problem.task_index[tid])} is scheduled {c} times.", count=c)
    placed = _known_unique(problem, placements)
    for t in problem.tasks:
        if t.idx not in placed:
            add("TASK_MISSING", "hard", [t.id], [], f"{tn(t.idx)} is not scheduled.")

    usage: dict[int, list[tuple[int, int, str, int]]] = {}
    for idx, p in placed.items():
        t = problem.tasks[idx]
        s, e = p.start, p.end
        # H2
        if e - s != t.duration:
            add("DURATION_MISMATCH", "hard", [t.id], [],
                f"{tn(idx)} is scheduled for {fmt_duration(e - s)} but takes {fmt_duration(t.duration)}.",
                expected=t.duration, actual=e - s)
        # H3
        if s < 0 or e > H:
            add("OUTSIDE_HORIZON", "hard", [t.id], [],
                f"{tn(idx)} is scheduled outside the planning horizon.", start=s, end=e, horizon_end=H)
        # H4
        if s < t.release:
            add("EARLIEST_START_VIOLATED", "hard", [t.id], [],
                f"{tn(idx)} starts {fmt_duration(t.release - s)} before its earliest start "
                f"{fmt_minute(t.release, hs)}.", earliest=t.release, start=s)
        # H6
        rids = list(p.resource_ids)
        if len(rids) != len(t.requirements):
            add("RESOURCE_COUNT_MISMATCH", "hard", [t.id], rids,
                f"{tn(idx)} needs {len(t.requirements)} {term.resources.lower()} but {len(rids)} are assigned.",
                expected=len(t.requirements), actual=len(rids))
        if len(set(rids)) != len(rids):
            add("RESOURCE_DUPLICATE", "hard", [t.id], rids,
                f"{tn(idx)} uses the same {term.resource.lower()} for more than one requirement.")
        for i, rid in enumerate(rids):
            if i >= len(t.requirements):
                break
            k = problem.resource_index.get(rid)
            req = t.requirements[i]
            if k is None or k not in req.alternatives:
                rname = problem.resources[k].name if k is not None else rid
                add("RESOURCE_NOT_ELIGIBLE", "hard", [t.id], [rid],
                    f'{term.resource} "{rname}" cannot be used for {tn(idx)}.', requirement_index=i)
                if k is None:
                    continue
            usage.setdefault(k, []).append((s, e, t.id, req.units))
            # H8 calendar (milestones / zero duration exempt)
            if t.duration > 0 and not t.is_milestone:
                r = problem.resources[k]
                starts = [w[0] for w in r.windows]
                if not _in_one_window(r.windows, starts, s, e):
                    add("CALENDAR_VIOLATED", "hard", [t.id], [rid],
                        f'{tn(idx)} is scheduled when {term.resource.lower()} "{r.name}" is not available '
                        f"({fmt_minute(s, hs)} - {fmt_minute(e, hs)}).", start=s, end=e)
        # H9 locks
        if t.locked_start is not None:
            locked_ids = ([problem.resources[k].id for k in t.locked_resources]
                          if t.locked_resources is not None else None)
            if s != t.locked_start or (locked_ids is not None and rids != locked_ids):
                add("LOCK_VIOLATED", "hard", [t.id], rids,
                    f"{tn(idx)} is locked at {fmt_minute(t.locked_start, hs)}"
                    + (f" on {', '.join(locked_ids)}" if locked_ids else "")
                    + f" but is scheduled at {fmt_minute(s, hs)}" + (f" on {', '.join(rids)}" if rids else "") + ".",
                    locked_start=t.locked_start, start=s, locked_resource_ids=locked_ids or [])
        # H10 / S1
        if t.deadline is not None and e > t.deadline:
            late = e - t.deadline
            msg = (f"{tn(idx)} finishes {fmt_duration(late)} after its {term.deadline.lower()} "
                   f"({fmt_minute(t.deadline, hs)}).")
            if t.deadline_hard:
                add("HARD_DEADLINE_MISSED", "hard", [t.id], [], msg, deadline=t.deadline, end=e, minutes_late=late)
            else:
                add("DEADLINE_MISSED", "soft", [t.id], [], msg, deadline=t.deadline, end=e, minutes_late=late)

    # H5 dependencies
    for d in problem.deps:
        a, b = placed.get(d.pred), placed.get(d.succ)
        if a is None or b is None:
            continue
        if d.type == "FS":
            req, act, what = a.end + d.lag, b.start, "start"
        elif d.type == "SS":
            req, act, what = a.start + d.lag, b.start, "start"
        elif d.type == "FF":
            req, act, what = a.end + d.lag, b.end, "finish"
        else:
            req, act, what = a.start + d.lag, b.end, "finish"
        if act < req:
            pa, pb = problem.tasks[d.pred], problem.tasks[d.succ]
            rel = {"FS": "finishes", "SS": "starts", "FF": "finishes", "SF": "starts"}[d.type]
            lag_txt = f" + {fmt_duration(d.lag)}" if d.lag > 0 else (f" - {fmt_duration(-d.lag)}" if d.lag < 0 else "")
            add("DEPENDENCY_VIOLATED", "hard", [pa.id, pb.id], [],
                f'{tn(d.succ)} must {what} after "{pa.name}" {rel}{lag_txt} ({_DEP_WORDS[d.type]}), '
                f"but {what}s {fmt_duration(req - act)} too early.",
                predecessor=pa.id, successor=pb.id, type=d.type, lag_minutes=d.lag, required_minute=req,
                actual_minute=act)

    # H7 capacity: sweep-line per resource, '-' before '+' at equal times
    for k, items in sorted(usage.items()):
        r = problem.resources[k]
        events: list[tuple[int, int, int, str]] = []
        for s, e, tid, u in items:
            if e <= s:
                continue
            events.append((s, 1, u, tid))
            events.append((e, 0, -u, tid))
        events.sort(key=lambda x: (x[0], x[1]))
        level = 0
        active: set[str] = set()
        over_from: int | None = None
        over_peak = 0
        over_tasks: set[str] = set()
        i = 0
        while i < len(events):
            tm = events[i][0]
            while i < len(events) and events[i][0] == tm:
                _, kind, du, tid = events[i]
                level += du
                if kind == 1:
                    active.add(tid)
                else:
                    active.discard(tid)
                i += 1
            if level > r.capacity:
                if over_from is None:
                    over_from, over_peak, over_tasks = tm, level, set(active)
                else:
                    over_peak = max(over_peak, level)
                    over_tasks |= active
            elif over_from is not None:
                add("CAPACITY_EXCEEDED", "hard", sorted(over_tasks), [r.id],
                    f'{term.resource} "{r.name}" is overbooked from {fmt_minute(over_from, hs)} to '
                    f"{fmt_minute(tm, hs)} ({over_peak} of {r.capacity} in use).",
                    **{"from": over_from, "to": tm, "usage": over_peak, "capacity": r.capacity})
                over_from = None

    v.sort(key=lambda x: (0 if x.severity == "hard" else 1, x.code, x.task_ids[0] if x.task_ids else ""))
    hard = any(x.severity == "hard" for x in v)
    return ValidationReport(feasibility="unknown" if hard else "feasible", violations=v,
                            metrics=compute_metrics(problem, placements))
