"""Solver-agnostic explanations (ARCHITECTURE section 11)."""

from __future__ import annotations

import bisect
import math
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


class DurationRisk(BaseModel):
    """PERT note for tasks with a duration range (PHASE2 2.14)."""

    tasks_with_range: int
    chain_task_ids: list[str]               # activities on the schedule critical chain
    chain_expected_minutes: int             # sum of duration_minutes
    chain_optimistic_minutes: int           # sum of o (duration if no estimate)
    chain_pessimistic_minutes: int          # sum of p
    chain_sigma_minutes: float              # sqrt(sum(((p - o) / 6)^2))
    buffer_85_minutes: int                  # round(1.04 * sigma)
    message: str


class ScheduleExplanation(BaseModel):
    tasks: dict[str, TaskExplanation]
    critical_chain: list[str]
    cpm_critical_path: list[str]
    summary: list[str]
    # None when no task has a range; omitted from dumps then, so existing results serialise unchanged.
    duration_risk: DurationRisk | None = Field(default=None, exclude_if=lambda v: v is None)


def fmt_work(minutes: int | float) -> str:
    """Working time with 8-hour days: `1 d 2 h`, `3 h 30 min`, `45 min`, `0 min`."""
    m = max(0, int(round(minutes)))
    days, rem = divmod(m, 480)
    hours, mins = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} d")
    if hours:
        parts.append(f"{hours} h")
    if mins or not parts:
        parts.append(f"{mins} min")
    return " ".join(parts)


def duration_risk(problem: CompiledProblem, chain: list[int]) -> DurationRisk | None:
    tasks = problem.tasks
    # split parts of one user task share an estimate key and count once ("1 task has a duration range")
    n = len({t.estimate_key or t.id for t in tasks if t.estimate is not None})
    if n == 0:
        return None
    acts = [tasks[i] for i in chain if not tasks[i].is_milestone]
    exp = sum(t.duration for t in acts)
    opt = sum(t.estimate[0] if t.estimate else t.duration for t in acts)
    pes = sum(t.estimate[2] if t.estimate else t.duration for t in acts)
    # Parts of one split estimate are one uncertainty: their spreads add up before squaring.
    spread: dict[str, float] = {}
    for t in acts:
        if t.estimate:
            k = t.estimate_key or t.id
            spread[k] = spread.get(k, 0.0) + (t.estimate[2] - t.estimate[0]) / 6
    sigma = math.sqrt(sum(v * v for v in spread.values()))
    buffer = int(round(1.04 * sigma))
    term = problem.terminology
    plural = term.tasks.lower()
    subject = f"1 {term.task.lower()} has" if n == 1 else f"{n} {plural} have"
    message = (f"{subject} a duration range; the plan uses the expected values. If the {plural} on the critical "
               f"chain take their longest estimates, the work runs about {fmt_work(pes - exp)} longer; keeping about "
               f"{fmt_work(buffer)} spare gives roughly an 85% chance of finishing on time.")
    return DurationRisk(tasks_with_range=n, chain_task_ids=[t.id for t in acts], chain_expected_minutes=exp,
                        chain_optimistic_minutes=opt, chain_pessimistic_minutes=pes,
                        chain_sigma_minutes=round(sigma, 3), buffer_85_minutes=buffer, message=message)


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

    win_starts: dict[int, list[int]] = {}

    def first_fit(t, rids: list[str], frm: int) -> int | None:
        """Earliest minute >= frm at which every assigned resource has a window holding the whole task."""
        d = t.duration
        cand = frm
        for _ in range(64):
            moved = False
            for i, rid in enumerate(rids):
                k = problem.resource_index.get(rid)
                if k is None or i >= len(t.requirements):
                    continue
                ws = problem.resources[k].windows
                if k not in win_starts:
                    win_starts[k] = [w[0] for w in ws]
                j = max(0, bisect.bisect_right(win_starts[k], cand) - 1) if ws else 0
                while j < len(ws) and ws[j][1] - max(ws[j][0], cand) < d:
                    j += 1
                if j >= len(ws):
                    return None
                nxt = max(ws[j][0], cand)
                if nxt != cand:
                    cand, moved = nxt, True
            if not moved:
                return cand
        return None

    primary: dict[int, StartReason] = {}
    binding: dict[int, int | None] = {}
    # CALENDAR starts that are the first possible working minute after a dependency: the chain runs through it.
    calendar_dep: dict[int, int] = {}
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
                        if lb_dep is not None and bind and lb_dep < s and first_fit(t, p.resource_ids, lb_dep) == s:
                            calendar_dep[t.idx] = max(bind, key=lambda x: (pos[x[0]].end, -x[0]))[0]
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
            elif code == "CALENDAR" and cur in calendar_dep:
                cur = calendar_dep[cur]
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
    risk = duration_risk(problem, chain)
    if risk is not None:
        summary.append(risk.message)
    return ScheduleExplanation(tasks=out, critical_chain=[tasks[i].id for i in chain],
                               cpm_critical_path=list(cpm_result.critical_path), summary=summary,
                               duration_risk=risk)
