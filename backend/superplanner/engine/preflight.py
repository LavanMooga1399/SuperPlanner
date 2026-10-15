"""Preflight checks (ARCHITECTURE section 9.1): structure and obvious infeasibility."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .compiled import kahn_order
from .graph import CpmResult, cpm_core, dep_lower_bound, find_cycles
from .model import Problem, Task
from .timeutil import expand_windows, fmt_duration, fmt_minute, parse_hhmm, to_minute

MAX_TASKS = 2000
MAX_RESOURCES = 200
MAX_DEPENDENCIES = 10000

PROVEN_INFEASIBLE_CODES: frozenset[str] = frozenset({
    "DEPENDENCY_CYCLE", "UNITS_EXCEED_CAPACITY", "NO_FITTING_WINDOW", "EARLIEST_AFTER_HORIZON",
    "DEADLINE_BEFORE_EARLIEST", "HARD_DEADLINE_IMPOSSIBLE", "HORIZON_TOO_SHORT",
})

CHECK_ORDER = (
    "NO_TASKS", "TOO_LARGE", "DUPLICATE_ID", "UNKNOWN_RESOURCE", "UNKNOWN_TASK", "SELF_DEPENDENCY",
    "DUPLICATE_DEPENDENCY", "DEPENDENCY_CYCLE", "UNITS_EXCEED_CAPACITY", "NO_FITTING_WINDOW",
    "INVALID_CALENDAR", "EMPTY_CALENDAR", "EARLIEST_AFTER_HORIZON", "DEADLINE_BEFORE_EARLIEST",
    "DEADLINE_BEFORE_HORIZON", "LOCK_INVALID", "HARD_DEADLINE_IMPOSSIBLE", "HORIZON_TOO_SHORT",
    "SOFT_DEADLINE_UNREACHABLE", "UNUSED_RESOURCE", "MILESTONE_WITH_LOCKED_RESOURCES", "LAG_OUT_OF_RANGE",
)
STRUCTURAL_CODES = frozenset({"TOO_LARGE", "DUPLICATE_ID", "UNKNOWN_TASK", "SELF_DEPENDENCY",
                              "DUPLICATE_DEPENDENCY", "DEPENDENCY_CYCLE"})
_DEP_WORDS = {"FS": "finish-to-start", "SS": "start-to-start", "FF": "finish-to-finish", "SF": "start-to-finish"}


class Issue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str
    task_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    field: str | None = None


class PreflightReport(BaseModel):
    ok: bool
    issues: list[Issue]


def _q(name: str) -> str:
    return f'"{name}"'


def preflight(problem: Problem) -> PreflightReport:
    issues, _ = run_preflight(problem)
    return PreflightReport(ok=not any(i.severity == "error" for i in issues), issues=issues)


def run_preflight(problem: Problem):
    """Returns (issues, cpm tuple or None). The CPM tuple is reused by `analyze`."""
    term = problem.terminology
    T, Ts, R = term.task, term.tasks, term.resource
    hs = problem.horizon_start
    H = problem.horizon_days * 1440
    buckets: dict[str, list[Issue]] = {c: [] for c in CHECK_ORDER}

    def add(code: str, severity: str, message: str, task_ids=(), resource_ids=(), field=None):
        buckets[code].append(Issue(code=code, severity=severity, message=message, task_ids=list(task_ids),
                                   resource_ids=list(resource_ids), field=field))

    tasks, resources, deps = problem.tasks, problem.resources, problem.dependencies

    def tn(t: Task) -> str:
        return f"{T} {_q(t.name)}"

    # NO_TASKS / TOO_LARGE
    if not tasks:
        add("NO_TASKS", "warning", f"The plan has no {Ts.lower()} yet.")
    if len(tasks) > MAX_TASKS or len(resources) > MAX_RESOURCES or len(deps) > MAX_DEPENDENCIES:
        add("TOO_LARGE", "error",
            f"The plan is too large: {len(tasks)} {Ts.lower()} (max {MAX_TASKS}), {len(resources)} "
            f"{term.resources.lower()} (max {MAX_RESOURCES}), {len(deps)} dependencies (max {MAX_DEPENDENCIES}).")

    # DUPLICATE_ID
    task_idx: dict[str, int] = {}
    for i, t in enumerate(tasks):
        if t.id in task_idx:
            add("DUPLICATE_ID", "error", f"{T} id {_q(t.id)} is used more than once ({tn(t)}).",
                task_ids=[t.id], field=f"tasks[{i}].id")
        else:
            task_idx[t.id] = i
    res_idx: dict[str, int] = {}
    for i, r in enumerate(resources):
        if r.id in res_idx:
            add("DUPLICATE_ID", "error", f"{R} id {_q(r.id)} is used more than once ({R} {_q(r.name)}).",
                resource_ids=[r.id], field=f"resources[{i}].id")
        else:
            res_idx[r.id] = i
        if r.id in task_idx:
            add("DUPLICATE_ID", "error",
                f"{R} {_q(r.name)} has the same id {_q(r.id)} as {tn(tasks[task_idx[r.id]])}; ids must be unique.",
                task_ids=[r.id], resource_ids=[r.id], field=f"resources[{i}].id")

    # UNKNOWN_RESOURCE
    for i, t in enumerate(tasks):
        for j, rq in enumerate(t.requirements):
            for a in rq.alternatives:
                if a not in res_idx:
                    add("UNKNOWN_RESOURCE", "error", f"{tn(t)} needs {R.lower()} {_q(a)}, which does not exist.",
                        task_ids=[t.id], resource_ids=[a], field=f"tasks[{i}].requirements[{j}]")
        if t.locked is not None and t.locked.resource_ids:
            for a in t.locked.resource_ids:
                if a not in res_idx:
                    add("UNKNOWN_RESOURCE", "error", f"{tn(t)} is locked to {R.lower()} {_q(a)}, which does not exist.",
                        task_ids=[t.id], resource_ids=[a], field=f"tasks[{i}].locked.resource_ids")

    # UNKNOWN_TASK / SELF_DEPENDENCY / DUPLICATE_DEPENDENCY / LAG_OUT_OF_RANGE
    def nm(tid: str) -> str:
        return _q(tasks[task_idx[tid]].name) if tid in task_idx else _q(tid)

    seen_pairs: set[tuple[str, str]] = set()
    edges: list[tuple[int, int]] = []
    good_deps: list[tuple[int, int, str, int]] = []
    for k, d in enumerate(deps):
        fld = f"dependencies[{k}]"
        missing = [x for x in (d.predecessor, d.successor) if x not in task_idx]
        for x in dict.fromkeys(missing):
            add("UNKNOWN_TASK", "error", f"A dependency refers to {T.lower()} {_q(x)}, which does not exist.",
                task_ids=[x], field=fld)
        if abs(d.lag_minutes) > H:
            add("LAG_OUT_OF_RANGE", "error",
                f"The dependency of {T.lower()} {nm(d.successor)} on {nm(d.predecessor)} has a lag of {fmt_duration(d.lag_minutes)}, "
                f"longer than the whole planning horizon ({fmt_duration(H)}).",
                task_ids=[d.predecessor, d.successor], field=fld)
        if d.predecessor == d.successor:
            name = tasks[task_idx[d.predecessor]].name if d.predecessor in task_idx else d.predecessor
            add("SELF_DEPENDENCY", "error", f"{T} {_q(name)} cannot depend on itself.",
                task_ids=[d.predecessor], field=fld)
            continue
        pair = (d.predecessor, d.successor)
        if pair in seen_pairs:
            add("DUPLICATE_DEPENDENCY", "error",
                f"{T} {nm(d.successor)} depends on {nm(d.predecessor)} more than once; keep only one dependency.",
                task_ids=list(pair), field=fld)
            continue
        seen_pairs.add(pair)
        if not missing:
            a, b = task_idx[d.predecessor], task_idx[d.successor]
            edges.append((a, b))
            good_deps.append((a, b, d.type, d.lag_minutes))

    # DEPENDENCY_CYCLE
    for cyc in find_cycles(len(tasks), edges):
        names = [tasks[i].name for i in cyc] + [tasks[cyc[0]].name]
        add("DEPENDENCY_CYCLE", "error",
            f"{Ts} " + " -> ".join(_q(n) for n in names)
            + " form a loop; at least one of these dependencies must be removed.",
            task_ids=[tasks[i].id for i in cyc], field="dependencies")

    # Calendars: INVALID_CALENDAR / EMPTY_CALENDAR, and windows per resource
    windows: dict[str, list[tuple[int, int]]] = {}
    for i, r in enumerate(resources):
        cal = r.calendar
        if cal is not None:
            if cal.weekly is not None:
                for day, wins in cal.weekly.items():
                    for w_i, (ws, we) in enumerate(wins):
                        if ws == "24:00" or parse_hhmm(ws) >= parse_hhmm(we):
                            add("INVALID_CALENDAR", "error",
                                f"{R} {_q(r.name)} has an invalid {day} window {ws}-{we}: the start must be "
                                f"before the end (windows over midnight must be split at 24:00).",
                                resource_ids=[r.id], field=f"resources[{i}].calendar.weekly.{day}[{w_i}]")
            for b_i, b in enumerate(cal.blocked):
                if b.start >= b.end:
                    add("INVALID_CALENDAR", "error",
                        f"{R} {_q(r.name)} has a blocked period that ends before it starts.",
                        resource_ids=[r.id], field=f"resources[{i}].calendar.blocked[{b_i}]")
        wins_r = expand_windows(cal, hs, H)
        if r.id not in windows:
            windows[r.id] = wins_r
        if not wins_r:
            add("EMPTY_CALENDAR", "warning", f"{R} {_q(r.name)} is never available within the planning horizon.",
                resource_ids=[r.id], field=f"resources[{i}].calendar")

    # UNITS_EXCEED_CAPACITY / NO_FITTING_WINDOW
    cap = {r.id: r.capacity for r in resources if r.id in res_idx and resources[res_idx[r.id]] is r}
    rname = {r.id: r.name for r in reversed(resources)}
    for i, t in enumerate(tasks):
        for j, rq in enumerate(t.requirements):
            known = [a for a in rq.alternatives if a in cap]
            if not known:
                continue
            too_small = [a for a in known if rq.units > cap[a]]
            fld = f"tasks[{i}].requirements[{j}]"
            if too_small and len(too_small) == len(known):
                add("UNITS_EXCEED_CAPACITY", "error",
                    f"{tn(t)} needs {rq.units} units, but no eligible {R.lower()} has that many "
                    f"(largest: {max(cap[a] for a in known)}).",
                    task_ids=[t.id], resource_ids=too_small, field=fld)
                continue
            if too_small:
                add("UNITS_EXCEED_CAPACITY", "warning",
                    f"{tn(t)} needs {rq.units} units, which " + ", ".join(_q(rname[a]) for a in too_small)
                    + " cannot provide; they will not be used for it.",
                    task_ids=[t.id], resource_ids=too_small, field=fld)
            usable = [a for a in known if rq.units <= cap[a]]
            if t.type == "activity" and t.duration_minutes > 0:
                longest = max((e - s for a in usable for s, e in windows.get(a, [])), default=0)
                if longest < t.duration_minutes:
                    add("NO_FITTING_WINDOW", "error",
                        f"{tn(t)} takes {fmt_duration(t.duration_minutes)}, but the longest available window of "
                        + ", ".join(_q(rname[a]) for a in usable)
                        + (f" is {fmt_duration(longest)}." if longest else " is empty (never available)."),
                        task_ids=[t.id], resource_ids=usable, field=fld)

    # Time checks per task
    releases: list[int] = []
    locked_starts: list[int | None] = []
    for i, t in enumerate(tasks):
        d = t.duration_minutes if t.type == "activity" else 0
        r = 0 if t.earliest_start is None else max(0, to_minute(t.earliest_start, hs))
        releases.append(r)
        if r + d > H:
            add("EARLIEST_AFTER_HORIZON", "error",
                f"{tn(t)} cannot finish within the planning horizon: it can start at the earliest "
                f"{fmt_minute(r, hs)} and takes {fmt_duration(d)}, but the horizon ends {fmt_minute(H, hs)}.",
                task_ids=[t.id], field=f"tasks[{i}]")
        if t.deadline is not None:
            dl = to_minute(t.deadline, hs)
            if dl < 0:
                add("DEADLINE_BEFORE_HORIZON", "error",
                    f"The {term.deadline.lower()} of {tn(t)} ({fmt_minute(dl, hs)}) is before the plan starts.",
                    task_ids=[t.id], field=f"tasks[{i}].deadline")
            elif dl < r + d:
                add("DEADLINE_BEFORE_EARLIEST", "error" if t.deadline_hard else "warning",
                    f"{tn(t)} cannot meet its {term.deadline.lower()} {fmt_minute(dl, hs)}: it can start at the "
                    f"earliest {fmt_minute(r, hs)} and takes {fmt_duration(d)}.",
                    task_ids=[t.id], field=f"tasks[{i}].deadline")
        lk = t.locked
        ls_val: int | None = None
        if lk is not None:
            ls_val = to_minute(lk.start, hs)
            fld = f"tasks[{i}].locked"
            problems: list[str] = []
            if ls_val < 0 or ls_val + d > H:
                problems.append("it lies outside the planning horizon")
            elif ls_val < r:
                problems.append(f"it is before the earliest start {fmt_minute(r, hs)}")
            if t.type == "milestone":
                if lk.resource_ids:
                    add("MILESTONE_WITH_LOCKED_RESOURCES", "error",
                        f"{term.milestone} {_q(t.name)} uses no {term.resources.lower()}, so it cannot be locked to any.",
                        task_ids=[t.id], resource_ids=list(lk.resource_ids), field=fld)
            elif lk.resource_ids is not None:
                if len(lk.resource_ids) != len(t.requirements):
                    problems.append(f"it names {len(lk.resource_ids)} {term.resources.lower()} but the "
                                    f"{T.lower()} has {len(t.requirements)} requirement(s)")
                else:
                    if len(set(lk.resource_ids)) != len(lk.resource_ids):
                        problems.append(f"it uses the same {R.lower()} twice")
                    for j, (rid, rq) in enumerate(zip(lk.resource_ids, t.requirements)):
                        if rid not in rq.alternatives:
                            problems.append(f"{_q(rname.get(rid, rid))} is not an option for requirement {j + 1}")
                        elif rid in cap and cap[rid] < rq.units:
                            problems.append(f"{_q(rname[rid])} has too little capacity")
            if problems:
                add("LOCK_INVALID", "error",
                    f"The lock of {tn(t)} at {fmt_minute(ls_val, hs)} is invalid: " + "; ".join(problems) + ".",
                    task_ids=[t.id], field=fld)
        locked_starts.append(ls_val)

    structural = any(buckets[c] for c in STRUCTURAL_CODES)
    cpm_data = None
    if not structural and tasks:
        n = len(tasks)
        durations = [t.duration_minutes if t.type == "activity" else 0 for t in tasks]
        order = kahn_order(n, edges)
        if order is not None:
            es, ef, ls, lf, pe, preds = cpm_core(durations, releases, locked_starts, good_deps, order)
            cpm_data = (es, ef, ls, lf, pe, preds, durations, order)
            for v, t in enumerate(tasks):
                if locked_starts[v] is not None:
                    worst = None
                    for a, typ, lag in preds[v]:
                        b = dep_lower_bound(typ, lag, es[a], ef[a], durations[v])
                        if b > es[v] and (worst is None or b > worst[0]):
                            worst = (b, a, typ)
                    if worst is not None:
                        add("LOCK_INVALID", "error",
                            f"The lock of {tn(t)} at {fmt_minute(es[v], hs)} conflicts with its dependency on "
                            f"{_q(tasks[worst[1]].name)} ({_DEP_WORDS[worst[2]]}): it cannot start before "
                            f"{fmt_minute(worst[0], hs)}.",
                            task_ids=[t.id, tasks[worst[1]].id], field=f"tasks[{v}].locked")
                if t.deadline is None:
                    continue
                dl = to_minute(t.deadline, hs)
                if dl < 0 or ef[v] <= dl:
                    continue
                if t.deadline_hard:
                    if dl >= releases[v] + durations[v]:
                        add("HARD_DEADLINE_IMPOSSIBLE", "error",
                            f"Even with unlimited {term.resources.lower()}, {tn(t)} cannot finish before its "
                            f"{term.deadline.lower()} {fmt_minute(dl, hs)} (earliest possible finish "
                            f"{fmt_minute(ef[v], hs)}).",
                            task_ids=[t.id], field=f"tasks[{v}].deadline")
                elif dl >= releases[v] + durations[v]:
                    add("SOFT_DEADLINE_UNREACHABLE", "warning",
                        f"{tn(t)} will be at least {fmt_duration(ef[v] - dl)} late for its {term.deadline.lower()} "
                        f"{fmt_minute(dl, hs)}, even with unlimited {term.resources.lower()}.",
                        task_ids=[t.id], field=f"tasks[{v}].deadline")
            if pe > H:
                add("HORIZON_TOO_SHORT", "error",
                    f"The planning horizon of {problem.horizon_days} days is too short: the dependency chain alone "
                    f"needs {fmt_duration(pe)} (until {fmt_minute(pe, hs)}).", field="horizon_days")

    # UNUSED_RESOURCE
    used = {a for t in tasks for rq in t.requirements for a in rq.alternatives}
    for i, r in enumerate(resources):
        if r.id not in used:
            add("UNUSED_RESOURCE", "warning", f"{R} {_q(r.name)} is not used by any {T.lower()}.",
                resource_ids=[r.id], field=f"resources[{i}]")

    issues = [i for c in CHECK_ORDER for i in buckets[c]]
    return issues, cpm_data


class ValidateReport(BaseModel):
    """Returned by `analyze()` and the /validate endpoint (section 9.2)."""

    ok: bool
    issues: list[Issue]
    cpm: CpmResult | None


def analyze(problem: Problem) -> ValidateReport:
    from .compiled import build_compiled
    from .graph import cpm as run_cpm

    issues, cpm_data = run_preflight(problem)
    ok = not any(i.severity == "error" for i in issues)
    structural = any(i.code in STRUCTURAL_CODES for i in issues)
    result = None
    if not structural:
        try:
            result = run_cpm(build_compiled(problem))
        except ValueError:
            result = None
    return ValidateReport(ok=ok, issues=issues, cpm=result)

