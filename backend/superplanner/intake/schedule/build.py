"""`ScheduleDraft` -> `Problem` (PHASE2 2.9.1). Deterministic; nothing is stored."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

from superplanner import engine
from superplanner.engine.model import (Calendar, Dependency, DurationEstimate, Objectives, Problem, Requirement,
                                       Resource, Task, Terminology, pert_minutes)
from superplanner.templates import exam_prep, manufacturing, project

from ..models import (DurationSummary, ExtractContext, ScheduleBuildResult, ScheduleDraft, TimeWindow,
                      WorkingTime)
from .extract import DEFAULT_RESOURCE, default_working_time
from .questions import next_working_day, questions

log = logging.getLogger(__name__)

DOMAIN_OF_KIND = {"project": "project", "study": "exam_prep", "production": "manufacturing", "generic": "generic"}
TERMS_OF_KIND = {"project": project.TERMS, "study": exam_prep.TERMS, "production": manufacturing.TERMS,
                 "generic": Terminology()}
WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class BuilderBug(Exception):
    """The builder produced an invalid Problem (a bug, never a user error: 500 + log)."""


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def weekly_of(wt: WorkingTime) -> dict[str, list[tuple[str, str]]]:
    weekly: dict[str, list[tuple[str, str]]] = {}
    for d in WEEK:
        if wt.weekend_windows is not None and d in ("sat", "sun"):
            weekly[d] = [(w.start, w.end) for w in wt.weekend_windows]
        elif d in wt.days:
            weekly[d] = [(w.start, w.end) for w in wt.windows]
    return weekly


def calendar_figures(weekly: dict[str, list[tuple[str, str]]]) -> tuple[float, int, int]:
    lengths = [_minutes(e) - _minutes(s) for ws in weekly.values() for s, e in ws]
    total = sum(lengths)
    days = sum(1 for ws in weekly.values() if ws)
    per_day = total / days if days else 480.0
    shortest = min(lengths) if lengths else 480
    max_part = shortest if shortest >= 30 else max(lengths)
    return per_day, total, max_part


def _tz(offset: str) -> timezone:
    sign = -1 if offset[0] == "-" else 1
    h, m = offset[1:].split(":")
    return timezone(sign * timedelta(hours=int(h), minutes=int(m)))


def _windows_on(day: date, weekly: dict[str, list[tuple[str, str]]]) -> list[tuple[str, str]]:
    return weekly.get(WEEK[day.weekday()], [])


def split_parts(o: int, m: int, p: int, max_part: int) -> list[tuple[int, int, int]]:
    """Step 6: smallest n >= ceil(E / max_part) with every part's PERT value <= max_part."""
    e = pert_minutes(o, m, p)
    n = max(1, math.ceil(e / max_part)) if e > max_part else 1
    while True:
        parts = []
        for i in range(n):
            parts.append(tuple(v // n + (1 if i < v % n else 0) for v in (o, m, p)))
        if n == 1 or all(pert_minutes(*pt) <= max_part for pt in parts) or n >= 1000:
            return [(max(1, a), max(1, b), max(1, c)) for a, b, c in parts]  # type: ignore[misc]
        n += 1


def build_schedule_problem(draft: ScheduleDraft, ctx: ExtractContext, *, source: str = "describe",
                           extractor: str = "rule") -> ScheduleBuildResult:
    blocking = [q for q in questions(draft, ctx) if q.required]
    if blocking:
        return ScheduleBuildResult(ready=False, problem=None, report=None, blocking=blocking, parts={},
                                   duration_summary=None)
    kind = draft.kind
    wt = draft.working_time or default_working_time(kind)
    start = draft.start_date or next_working_day(ctx.today, wt)
    tz = _tz(ctx.utc_offset)
    weekly = weekly_of(wt)
    per_day, per_week, max_part = calendar_figures(weekly)
    cal = Calendar(weekly=weekly)  # type: ignore[arg-type]
    # resources (step 4)
    resources: list[Resource] = []
    expanded: dict[str, list[str]] = {}
    kinds: dict[str, str] = {}
    for r in draft.resources:
        if r.count == 1:
            resources.append(Resource(id=r.key, name=r.name, kind=r.kind, capacity=1, calendar=cal))
            expanded[r.key] = [r.key]
        else:
            ids = [f"{r.key}_{i}" for i in range(1, r.count + 1)]
            for i, rid in enumerate(ids, start=1):
                resources.append(Resource(id=rid, name=f"{r.name} {i}"[:200], kind=r.kind, capacity=1, calendar=cal))
            expanded[r.key] = ids
        kinds[r.key] = r.kind
    if not resources:
        name, rkind = DEFAULT_RESOURCE[kind]
        resources.append(Resource(id="r_me", name=name, kind=rkind, capacity=1, calendar=cal))
        expanded["r_me"] = ["r_me"]
        kinds["r_me"] = rkind
    all_ids = [x for ids in expanded.values() for x in ids]
    worker_ids = [x for k, ids in expanded.items() if kinds[k] in ("person", "machine") for x in ids] or all_ids
    unit_minutes = {"minutes": 1.0, "hours": 60.0, "days": per_day, "weeks": float(per_week)}
    tasks: list[Task] = []
    deps: list[Dependency] = []
    parts_of: dict[str, list[str]] = {}
    with_range = expected = optimistic = pessimistic = 0
    deadlines: list[date] = []
    for dt in draft.tasks:
        group = dt.group or None
        if dt.milestone:
            parts_of[dt.key] = [dt.key]
            tasks.append(Task(id=dt.key, name=dt.name, type="milestone", duration_minutes=0,
                              priority=dt.priority or 5, group=group[:200] if group else None,
                              deadline=_deadline_at(dt.deadline, weekly, tz) if dt.deadline else None,
                              deadline_hard=bool(dt.deadline and dt.deadline_hard),
                              earliest_start=_start_at(dt.earliest_start, weekly, tz) if dt.earliest_start else None,
                              metadata={"intake_key": dt.key}))
            if dt.deadline:
                deadlines.append(dt.deadline)
            continue
        assert dt.duration is not None  # guaranteed by the blocking questions
        f = unit_minutes[dt.duration.unit]
        o, m, p = (max(1, int(round(v * f))) for v in (dt.duration.optimistic, dt.duration.likely,
                                                         dt.duration.pessimistic))
        m = max(o, m)
        p = max(m, p)
        e = pert_minutes(o, m, p)
        if o < p:
            with_range += 1
        expected += e
        optimistic += o
        pessimistic += p
        pieces = split_parts(o, m, p, max_part)
        n = len(pieces)
        reqs = _requirements(dt.resources, dt.resource_mode, expanded, worker_ids)
        ids = [dt.key] if n == 1 else [f"{dt.key}_{i}" for i in range(1, n + 1)]
        parts_of[dt.key] = ids
        for i, (po, pm, pp) in enumerate(pieces, start=1):
            est = DurationEstimate(optimistic_minutes=po, likely_minutes=pm, pessimistic_minutes=pp) if o < p else None
            name = dt.name if n == 1 else f"{dt.name} ({i}/{n})"
            md = {"intake_key": dt.key} if n == 1 else {"intake_key": dt.key, "part": i, "parts": n}
            tasks.append(Task(
                id=ids[i - 1], name=name[:200], group=(group or (dt.name if n > 1 else None)),
                duration_minutes=pert_minutes(po, pm, pp), duration_estimate=est, priority=dt.priority or 5,
                requirements=reqs,
                deadline=_deadline_at(dt.deadline, weekly, tz) if (dt.deadline and i == n) else None,
                deadline_hard=bool(dt.deadline and dt.deadline_hard and i == n),
                earliest_start=_start_at(dt.earliest_start, weekly, tz) if (dt.earliest_start and i == 1) else None,
                metadata=md))
        if dt.deadline:
            deadlines.append(dt.deadline)
        for a, b in zip(ids, ids[1:]):
            deps.append(Dependency(predecessor=a, successor=b, type="FS", lag_minutes=0))
    for dt in draft.tasks:
        for pred in dt.after:
            deps.append(Dependency(predecessor=parts_of[pred][-1], successor=parts_of[dt.key][0], type="FS",
                                   lag_minutes=0))
    # horizon (step 10)
    if draft.horizon_days is not None:
        horizon = draft.horizon_days
    else:
        d_last = max(((d - start).days for d in deadlines), default=0)
        r_count = len(all_ids)
        work = math.ceil(1.5 * 7 * expected / (per_week * max(1, r_count))) + 7 if per_week else 30
        horizon = max(7, min(366, max(d_last + 7, work)))
    objective = draft.objective or {"project": "meet_deadlines" if deadlines else "finish_asap", "study": "meet_deadlines",
                                    "production": "meet_deadlines", "generic": "balanced"}[kind]
    try:
        problem = Problem(id="draft", name=draft.name, domain=DOMAIN_OF_KIND[kind], currency=ctx.currency,
                          horizon_start=datetime(start.year, start.month, start.day, tzinfo=tz), horizon_days=horizon,
                          terminology=TERMS_OF_KIND[kind], tasks=tasks, resources=resources, dependencies=deps,
                          objectives=Objectives(preset=objective),  # type: ignore[arg-type]
                          metadata={"intake": {"version": 1, "source": source, "extractor": extractor}})
    except ValueError as exc:
        log.error("intake schedule builder produced an invalid problem: %s", type(exc).__name__)
        raise BuilderBug("invalid problem from the intake builder") from None
    report = engine.analyze(problem)
    summary = DurationSummary(tasks_with_range=with_range, expected_work_minutes=expected,
                              optimistic_work_minutes=optimistic, pessimistic_work_minutes=pessimistic)
    return ScheduleBuildResult(ready=report.ok, problem=problem, report=report, blocking=[], parts=parts_of,
                               duration_summary=summary)


def _requirements(keys: list[str], mode: str, expanded: dict[str, list[str]], workers: list[str]) -> list[Requirement]:
    if not keys:
        if len(expanded) == 1:
            only = next(iter(expanded.values()))
            return [Requirement(alternatives=only)]
        return [Requirement(alternatives=workers)]
    if mode == "all":
        return [Requirement(alternatives=expanded[k]) for k in keys]
    alts: list[str] = []
    for k in keys:
        for x in expanded[k]:
            if x not in alts:
                alts.append(x)
    return [Requirement(alternatives=alts)]


def _deadline_at(d: date, weekly, tz) -> datetime:
    ws = _windows_on(d, weekly)
    if ws:
        end = max(_minutes(e) for _, e in ws)
        return datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(minutes=end)
    return datetime(d.year, d.month, d.day, 23, 59, tzinfo=tz)


def _start_at(d: date, weekly, tz) -> datetime:
    ws = _windows_on(d, weekly)
    first = min((_minutes(s) for s, _ in ws), default=0)
    return datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(minutes=first)


_ = TimeWindow
