"""Solver-agnostic explanations (ARCHITECTURE section 11)."""

from __future__ import annotations

import bisect
from typing import Literal

from pydantic import BaseModel, Field

from .compiled import CompiledProblem
from .graph import CpmResult, cpm, dep_lower_bound
from .model import Placement
from .timeutil import fmt_clock, fmt_duration, fmt_minute


class StartReason(BaseModel):
    code: Literal["LOCKED", "HORIZON_START", "EARLIEST_START", "DEPENDENCY", "RESOURCE_BUSY", "CALENDAR",
                  "OPTIMIZER_CHOICE", "NOT_SCHEDULED"]
    message: str
    related_task_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)


class TaskExplanation(BaseModel):
    task_id: str
    reasons: list[StartReason]
    on_critical_chain: bool
    cpm_critical: bool
    cpm_slack_minutes: int
    lateness_minutes: int
    deadline_status: Literal["none", "on_time", "late_soft", "late_hard"]


class ScheduleExplanation(BaseModel):
    tasks: dict[str, TaskExplanation]
    critical_chain: list[str]
    cpm_critical_path: list[str]
    summary: list[str]


_DEP_PHRASE = {"FS": "finishes", "SS": "starts", "FF": "finishes", "SF": "starts"}


def explain(problem: CompiledProblem, placements: list[Placement], cpm_result: CpmResult | None = None) -> ScheduleExplanation:
    term = problem.terminology
    hs = problem.horizon_start
    tasks = problem.tasks
    cpm_result = cpm_result or cpm(problem)
    pos: dict[int, Placement] = {}
    for p in placements:
        idx = problem.task_index.get(p.task_id)
        if idx is not None and idx not in pos:
            pos[idx] = p
    # per-resource occupation: list of (start, end, units, task idx) sorted by start
    occ: dict[int, list[tuple[int, int, int, int]]] = {}
    for idx, p in pos.items():
        t = tasks[idx]
        for i, rid in enumerate(p.resource_ids):
            k = problem.resource_index.get(rid)
            if k is not None and i < len(t.requirements) and p.end > p.start:
                occ.setdefault(k, []).append((p.start, p.end, t.requirements[i].units, idx))
    for v in occ.values():
        v.sort()
    occ_starts = {k: [x[0] for x in v] for k, v in occ.items()}
    maxdur = {k: max((x[1] - x[0] for x in v), default=0) for k, v in occ.items()}

    def overlapping(k: int, s: int, e: int, exclude: int) -> list[tuple[int, int, int, int]]:
        if k not in occ:
            return []
        lo = bisect.bisect_left(occ_starts[k], s - maxdur[k])
        hi = bisect.bisect_left(occ_starts[k], e)
        return [x for x in occ[k][lo:hi] if x[1] > s and x[3] != exclude]

    def peak(items, s: int, e: int) -> int:
        pts = sorted([(max(x[0], s), x[2]) for x in items] + [(x[1], -x[2]) for x in items if x[1] < e],
                     key=lambda z: (z[0], z[1]))
        lvl = pk = 0
        for _, du in pts:
            lvl += du
            pk = max(pk, lvl)
        return pk

    primary: dict[int, StartReason] = {}
    binding: dict[int, int | None] = {}
    out: dict[str, TaskExplanation] = {}
    for t in tasks:
        p = pos.get(t.idx)
        reasons: list[StartReason] = []
        if p is None:
            reasons.append(StartReason(code="NOT_SCHEDULED", message=f"This {term.task.lower()} could not be scheduled."))
        else:
            s, d = p.start, t.duration
            if t.locked_start is not None:
                reasons.append(StartReason(code="LOCKED", message=f"Fixed by you at {fmt_minute(t.locked_start, hs)}."))
                binding[t.idx] = None
            lb_dep = None
            bind: list[tuple[int, str, int]] = []
            for j in problem.preds[t.idx]:
                dep = problem.deps[j]
                pp = pos.get(dep.pred)
                if pp is None:
                    continue
                b = dep_lower_bound(dep.type, dep.lag, pp.start, pp.end, d)
                if lb_dep is None or b > lb_dep:
                    lb_dep, bind = b, [(dep.pred, dep.type, dep.lag)]
                elif b == lb_dep:
                    bind.append((dep.pred, dep.type, dep.lag))
            if lb_dep is not None and s == lb_dep:
                parts = []
                for a, typ, lag in bind:
                    nm = tasks[a].name
                    if typ == "FS" and lag == 0:
                        parts.append(f"{nm} finishes")
                    elif lag > 0:
                        parts.append(f"{fmt_duration(lag)} after {nm} {_DEP_PHRASE[typ]}")
                    elif lag < 0:
                        parts.append(f"{fmt_duration(-lag)} before {nm} {_DEP_PHRASE[typ]}")
                    else:
                        parts.append(f"{nm} {_DEP_PHRASE[typ]}")
                verb = "Starts as soon as " if all(x[1] in ("FS", "SS") for x in bind) else "Timed so it finishes when "
                reasons.append(StartReason(code="DEPENDENCY", message=verb + " and ".join(parts) + ".",
                                           related_task_ids=[tasks[a].id for a, _, _ in bind]))
                binding.setdefault(t.idx, max(bind, key=lambda x: (pos[x[0]].end, -x[0]))[0])
            if s == t.release and t.release > 0:
                reasons.append(StartReason(code="EARLIEST_START",
                                           message=f"Starts at its earliest allowed start {fmt_minute(s, hs)}."))
            elif s == 0:
                reasons.append(StartReason(code="HORIZON_START", message="Starts at the beginning of the plan."))
            if not reasons:
                tp = s - 1
                found = None
                for i, rid in enumerate(p.resource_ids):
                    k = problem.resource_index.get(rid)
                    if k is None or i >= len(t.requirements) or d == 0:
                        continue
                    r = problem.resources[k]
                    starts = [w[0] for w in r.windows]
                    wp = bisect.bisect_right(starts, tp) - 1
                    if not (wp >= 0 and r.windows[wp][1] >= tp + d):
                        found = StartReason(code="CALENDAR", resource_ids=[rid],
                                            message=f'Waits for {r.name} to become available at {fmt_minute(s, hs)}.')
                        binding[t.idx] = None
                        break
                if found is None:
                    for i, rid in enumerate(p.resource_ids):
                        k = problem.resource_index.get(rid)
                        if k is None or i >= len(t.requirements) or d == 0:
                            continue
                        r = problem.resources[k]
                        items = overlapping(k, tp, tp + d, t.idx)
                        if items and peak(items, tp, tp + d) + t.requirements[i].units > r.capacity:
                            blockers = sorted(items, key=lambda x: (-x[1], x[3]))
                            names = ", ".join(tasks[x[3]].name for x in blockers[:3])
                            found = StartReason(
                                code="RESOURCE_BUSY", resource_ids=[rid],
                                related_task_ids=[tasks[x[3]].id for x in blockers],
                                message=f"Waits for {r.name}, busy with {names} until "
                                        f"{fmt_clock(blockers[0][1], hs)}.")
                            binding[t.idx] = blockers[0][3]
                            break
                if found is None:
                    found = StartReason(code="OPTIMIZER_CHOICE",
                                        message=f"Could start at {fmt_minute(tp, hs)}; placed later to improve the "
                                                "overall plan.")
                    binding[t.idx] = None
                reasons.append(found)
        primary[t.idx] = reasons[0]
        lateness = 0
        status = "none"
        if t.deadline is not None:
            if p is not None and p.end > t.deadline:
                lateness = p.end - t.deadline
                status = "late_hard" if t.deadline_hard else "late_soft"
            elif p is not None:
                status = "on_time"
        ct = cpm_result.tasks.get(t.id)
        out[t.id] = TaskExplanation(task_id=t.id, reasons=reasons, on_critical_chain=False,
                                    cpm_critical=bool(ct and ct.critical), cpm_slack_minutes=ct.slack if ct else 0,
                                    lateness_minutes=lateness, deadline_status=status)  # type: ignore[arg-type]

    # schedule critical chain
    chain: list[int] = []
    if pos:
        makespan = max(p.end for p in pos.values())
        ends = [i for i, p in pos.items() if p.end == makespan]
        cur: int | None = min(ends, key=lambda i: (-tasks[i].priority, i))
        seen: set[int] = set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            code = primary[cur].code
            if code in ("DEPENDENCY", "RESOURCE_BUSY"):
                cur = binding.get(cur)
            else:
                cur = None
        chain.reverse()
    for i in chain:
        out[tasks[i].id].on_critical_chain = True

    summary: list[str] = []
    late = [t for t in tasks if out[t.id].lateness_minutes > 0]
    unplaced = [t for t in tasks if t.idx not in pos]
    if unplaced:
        summary.append(f"{len(unplaced)} of {len(tasks)} {term.tasks} could not be scheduled.")
    if tasks:
        if late:
            summary.append(f"{len(late)} of {len(tasks)} {term.tasks} finish late.")
        elif not unplaced:
            summary.append(f"All {len(tasks)} {term.tasks} finish on time.")
    if chain:
        summary.append("Completion is driven by the chain " + " -> ".join(tasks[i].name for i in chain) + ".")
    return ScheduleExplanation(tasks=out, critical_chain=[tasks[i].id for i in chain],
                               cpm_critical_path=list(cpm_result.critical_path), summary=summary)
