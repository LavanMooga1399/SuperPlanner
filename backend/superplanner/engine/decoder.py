"""Serial schedule generation scheme and left-shift compaction (ARCHITECTURE 8.1, 8.2)."""

from __future__ import annotations

import bisect
import heapq
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .compiled import CompiledProblem, CTask
from .graph import dep_lower_bound
from .model import Placement

INF = 1 << 60


class Profile:
    """Occupied intervals of one resource, sorted by start."""

    __slots__ = ("cap", "starts", "items", "maxdur", "wins", "wstarts")

    def __init__(self, cap: int, windows: Sequence[tuple[int, int]]):
        self.cap = cap
        self.starts: list[int] = []
        self.items: list[tuple[int, int, int]] = []
        self.maxdur = 0
        self.wins = windows
        self.wstarts = [w[0] for w in windows]

    def add(self, s: int, e: int, u: int) -> None:
        if e <= s:
            return
        pos = bisect.bisect_right(self.starts, s)
        self.starts.insert(pos, s)
        self.items.insert(pos, (s, e, u))
        if e - s > self.maxdur:
            self.maxdur = e - s

    def remove(self, s: int, e: int, u: int) -> None:
        if e <= s:
            return
        pos = bisect.bisect_left(self.starts, s)
        while pos < len(self.items):
            if self.items[pos] == (s, e, u):
                del self.items[pos]
                del self.starts[pos]
                return
            pos += 1

    def window_next(self, t: int, d: int) -> int:
        """t if [t, t+d) fits in one window, else the next window start > t that can hold d."""
        pos = bisect.bisect_right(self.wstarts, t) - 1
        if pos >= 0 and self.wins[pos][1] >= t + d:
            return t
        pos += 1
        while pos < len(self.wins):
            ws, we = self.wins[pos]
            if we - ws >= d:
                return ws
            pos += 1
        return INF

    def in_window(self, t: int, d: int) -> bool:
        pos = bisect.bisect_right(self.wstarts, t) - 1
        return pos >= 0 and self.wins[pos][1] >= t + d

    def cap_next(self, t: int, d: int, u: int) -> int:
        """t if capacity allows [t, t+d) with u more units, else a safe lower bound on the next time."""
        if u > self.cap:
            return INF
        e = t + d
        lo = bisect.bisect_left(self.starts, t - self.maxdur)
        hi = bisect.bisect_left(self.starts, e)
        ov = [it for it in self.items[lo:hi] if it[1] > t]
        if not ov:
            return t
        total = sum(it[2] for it in ov)
        if total + u <= self.cap:
            return t
        if self.cap == 1:
            return max(it[1] for it in ov)
        # exact max usage over [t, e)
        pts = sorted([(max(it[0], t), it[2]) for it in ov] + [(it[1], -it[2]) for it in ov if it[1] < e],
                     key=lambda x: (x[0], x[1]))
        level = peak = 0
        for _, du in pts:
            level += du
            peak = max(peak, level)
        if peak + u <= self.cap:
            return t
        return min(it[1] for it in ov)

    def usage_over(self, s: int, e: int) -> int:
        lo = bisect.bisect_left(self.starts, s - self.maxdur)
        hi = bisect.bisect_left(self.starts, e)
        ov = [it for it in self.items[lo:hi] if it[1] > s]
        if not ov:
            return 0
        pts = sorted([(max(it[0], s), it[2]) for it in ov] + [(it[1], -it[2]) for it in ov if it[1] < e],
                     key=lambda x: (x[0], x[1]))
        level = peak = 0
        for _, du in pts:
            level += du
            peak = max(peak, level)
        return peak


@dataclass
class DecodeResult:
    placements: list[Placement]
    unscheduled: list[int]
    reasons: dict[int, str] = field(default_factory=dict)
    repairs: int = 0
    lock_conflicts: int = 0


def make_profiles(problem: CompiledProblem) -> list[Profile]:
    return [Profile(r.capacity, r.windows) for r in problem.resources]


def _fits(prof: Profile, t: int, d: int, u: int) -> bool:
    return prof.in_window(t, d) and prof.cap_next(t, d, u) == t


def _assign_at(problem: CompiledProblem, profiles: list[Profile], busy: list[int], task: CTask, t: int,
               options: list[list[int]]) -> tuple[list[int] | None, int]:
    """Try to assign one resource per requirement at time t.

    Returns (resources, next_candidate). next_candidate is a safe lower bound on the next time
    worth trying when no assignment exists.
    """
    d = task.duration
    feasible: list[list[int]] = []
    fail_next = -1
    for i, req in enumerate(task.requirements):
        ok: list[int] = []
        nxt = INF
        for k in options[i]:
            prof = profiles[k]
            w = prof.window_next(t, d)
            if w != t:
                nxt = min(nxt, w)
                continue
            c = prof.cap_next(t, d, req.units)
            if c != t:
                nxt = min(nxt, c)
                continue
            ok.append(k)
        if not ok:
            fail_next = max(fail_next, nxt)
        feasible.append(ok)
    if fail_next >= 0:
        return None, fail_next
    res = problem.resources
    for ok in feasible:
        if len(ok) > 1:
            order = {k: p for p, k in enumerate(ok)}
            ok.sort(key=lambda k: (res[k].cost_per_hour, busy[k], order[k]))
    chosen: list[int] = []
    used: set[int] = set()

    def bt(i: int) -> bool:
        if i == len(feasible):
            return True
        for k in feasible[i]:
            if k in used:
                continue
            used.add(k)
            chosen.append(k)
            if bt(i + 1):
                return True
            chosen.pop()
            used.discard(k)
        return False

    if bt(0):
        return chosen, t
    return None, t + 1


def _reason(task: CTask, t: int, es: int, dep_bound: int, has_deps: bool) -> str:
    if t == es:
        if has_deps and dep_bound == es and es > 0:
            return "DEPENDENCY"
        if task.release == es and es > 0:
            return "EARLIEST_START"
        if es == 0:
            return "HORIZON_START"
        return "DEPENDENCY"
    return "RESOURCE_BUSY"


def decode(problem: CompiledProblem, priority: Sequence[float],
           resource_choice: Mapping[tuple[int, int], int] | None = None) -> DecodeResult:
    tasks = problem.tasks
    n = len(tasks)
    H = problem.H
    profiles = make_profiles(problem)
    busy = [0] * len(problem.resources)
    start = [0] * n
    end = [0] * n
    rids: list[list[int] | None] = [None] * n
    state = [0] * n  # 0 = open, 1 = placed, 2 = unschedulable
    reasons: dict[int, str] = {}
    repairs = 0
    lock_conflicts = 0

    def reserve(i: int, s: int, ks: list[int]) -> None:
        task = tasks[i]
        start[i], end[i], rids[i], state[i] = s, s + task.duration, ks, 1
        for req, k in zip(task.requirements, ks):
            profiles[k].add(s, s + task.duration, req.units)
            busy[k] += req.units * task.duration

    # 2. locked tasks first (those with fixed resources before those that only fix the start)
    for task in sorted((t for t in tasks if t.locked_start is not None),
                       key=lambda t: (t.locked_resources is None, t.idx)):
        s = task.locked_start
        d = task.duration
        if task.locked_resources is not None:
            ks = list(task.locked_resources)
            ok = all(_fits(profiles[k], s, d, rq.units) for k, rq in zip(ks, task.requirements)) if d > 0 else True
        else:
            opts = [list(rq.alternatives) for rq in task.requirements]
            got, _ = _assign_at(problem, profiles, busy, task, s, opts) if task.requirements else ([], s)
            ok = got is not None
            if got is None:
                ks = []
                for rq in task.requirements:
                    alts = [k for k in rq.alternatives if k not in ks] or list(rq.alternatives)
                    ks.append(alts[0] if alts else -1)
            else:
                ks = got
        if any(k < 0 for k in ks):
            state[task.idx] = 2
            reasons[task.idx] = "NO_SLOT"
            lock_conflicts += 1
            continue
        if not ok or s < 0 or s + d > H:
            lock_conflicts += 1
        reserve(task.idx, s, ks)
        reasons[task.idx] = "LOCKED"

    # 3. serial SGS over the rest
    topo_pos = [0] * n
    for p, i in enumerate(problem.topo_order):
        topo_pos[i] = p
    remaining = [0] * n
    for dep in problem.deps:
        if tasks[dep.succ].locked_start is None:
            remaining[dep.succ] += 1
    heap = [(priority[i], topo_pos[i], i) for i in range(n) if tasks[i].locked_start is None and remaining[i] == 0]
    heapq.heapify(heap)

    def release_succs(i: int) -> None:
        for j in problem.succs[i]:
            b = problem.deps[j].succ
            if tasks[b].locked_start is not None:
                continue
            remaining[b] -= 1
            if remaining[b] == 0:
                heapq.heappush(heap, (priority[b], topo_pos[b], b))

    # Locked tasks count as placed for their successors.
    for task in tasks:
        if task.locked_start is not None:
            release_succs(task.idx)
    # (release_succs above may have pushed tasks; heap stays valid)

    while heap:
        _, _, i = heapq.heappop(heap)
        task = tasks[i]
        d = task.duration
        dep_bound = 0
        bad_pred = False
        for j in problem.preds[i]:
            dep = problem.deps[j]
            a = dep.pred
            if state[a] != 1:
                bad_pred = True
                break
            dep_bound = max(dep_bound, dep_lower_bound(dep.type, dep.lag, start[a], end[a], d))
        if bad_pred:
            state[i] = 2
            reasons[i] = "PREDECESSOR_UNSCHEDULED"
            release_succs(i)
            continue
        es = max(task.release, dep_bound, 0)
        if not task.requirements:
            if es + d <= H:
                reserve(i, es, [])
                reasons[i] = _reason(task, es, es, dep_bound, bool(problem.preds[i]))
            else:
                state[i] = 2
                reasons[i] = "NO_SLOT"
            release_succs(i)
            continue
        options: list[list[int]] = []
        for r_i, req in enumerate(task.requirements):
            alts = list(req.alternatives)
            if resource_choice is not None and len(alts) > 1 and (i, r_i) in resource_choice:
                pos = min(max(resource_choice[(i, r_i)], 0), len(alts) - 1)
                k = alts[pos]
                if profiles[k].window_next(0, d) < INF and req.units <= profiles[k].cap:
                    alts = [k]
                else:
                    repairs += 1
            options.append(alts)
        # Fixed choices that collide fall back to greedy for the later requirement.
        seen_fixed: set[int] = set()
        for r_i, alts in enumerate(options):
            if len(alts) == 1 and len(task.requirements[r_i].alternatives) > 1:
                if alts[0] in seen_fixed:
                    options[r_i] = list(task.requirements[r_i].alternatives)
                    repairs += 1
                else:
                    seen_fixed.add(alts[0])
        t = es
        placed = False
        while t + d <= H:
            ks, nxt = _assign_at(problem, profiles, busy, task, t, options)
            if ks is not None:
                reserve(i, t, ks)
                reasons[i] = _reason(task, t, es, dep_bound, bool(problem.preds[i]))
                placed = True
                break
            if nxt <= t:
                nxt = t + 1
            t = nxt
        if not placed:
            state[i] = 2
            reasons[i] = "NO_SLOT"
        release_succs(i)

    placements: list[Placement] = []
    unscheduled: list[int] = []
    for i, task in enumerate(tasks):
        if state[i] == 1:
            placements.append(Placement(task_id=task.id, start=start[i], end=end[i],
                                        resource_ids=[problem.resources[k].id for k in rids[i] or []]))
        else:
            unscheduled.append(i)
            reasons.setdefault(i, "NO_SLOT")
    return DecodeResult(placements=placements, unscheduled=unscheduled, reasons=reasons, repairs=repairs,
                        lock_conflicts=lock_conflicts)


def left_shift(problem: CompiledProblem, placements: list[Placement]) -> list[Placement]:
    """Move every non-locked task to its earliest locally valid start; never moves a task later."""
    tasks = problem.tasks
    cur: dict[int, list] = {}
    order_ids: list[str] = []
    passthrough: dict[int, Placement] = {}
    for pos, p in enumerate(placements):
        idx = problem.task_index.get(p.task_id)
        if idx is None or idx in cur:
            passthrough[pos] = p
            continue
        ks = [problem.resource_index.get(r) for r in p.resource_ids]
        cur[idx] = [p.start, p.end, ks, pos]
    profiles = make_profiles(problem)
    for idx, (s, e, ks, _) in cur.items():
        t = tasks[idx]
        for i, k in enumerate(ks):
            if k is not None and i < len(t.requirements):
                profiles[k].add(s, e, t.requirements[i].units)

    for _pass in range(100):
        moved = False
        for idx in sorted(cur, key=lambda x: (cur[x][0], x)):
            task = tasks[idx]
            if task.locked_start is not None:
                continue
            s, e, ks, _ = cur[idx]
            d = task.duration
            if e - s != d or len(ks) != len(task.requirements) or any(k is None for k in ks):
                continue
            lb = max(task.release, 0)
            ok_preds = True
            for j in problem.preds[idx]:
                dep = problem.deps[j]
                if dep.pred not in cur:
                    ok_preds = False
                    break
                ps, pe = cur[dep.pred][0], cur[dep.pred][1]
                lb = max(lb, dep_lower_bound(dep.type, dep.lag, ps, pe, d))
            if not ok_preds or lb >= s:
                continue
            reqs = task.requirements
            for k, rq in zip(ks, reqs):
                profiles[k].remove(s, e, rq.units)
            new_t = None
            if not reqs:
                new_t = lb
            else:
                t = lb
                while t < s:
                    nxt = t
                    for k, rq in zip(ks, reqs):
                        w = profiles[k].window_next(t, d)
                        if w != t:
                            nxt = max(nxt, w)
                            continue
                        c = profiles[k].cap_next(t, d, rq.units)
                        if c != t:
                            nxt = max(nxt, c)
                    if nxt == t:
                        new_t = t
                        break
                    t = nxt
            if new_t is not None and new_t < s:
                s, e = new_t, new_t + d
                cur[idx][0], cur[idx][1] = s, e
                moved = True
            for k, rq in zip(ks, reqs):
                profiles[k].add(s, e, rq.units)
        if not moved:
            break

    out: list[Placement | None] = [None] * len(placements)
    for idx, (s, e, ks, pos) in cur.items():
        p = placements[pos]
        out[pos] = Placement(task_id=p.task_id, start=s, end=e, resource_ids=list(p.resource_ids))
    for pos, p in passthrough.items():
        out[pos] = p
    return [p for p in out if p is not None]
