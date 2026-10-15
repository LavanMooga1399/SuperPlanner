"""Builders shared by the engine tests (imported as a plain module; see conftest.py)."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from superplanner.engine.compiled import compile_problem
from superplanner.engine.model import (Calendar, Dependency, Lock, Placement, Problem, Requirement, Resource, Task,
                                       Terminology)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURES = ["example_3_11", "precedence_only", "flexible_jobshop_10x5", "infeasible_hard_deadline", "calendar_heavy"]
FEASIBLE_FIXTURES = [f for f in FIXTURES if f != "infeasible_hard_deadline"]
HS = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)  # a Monday
TERMS = Terminology(task="Operation", tasks="Operations", resource="Machine", resources="Machines")


def at(minutes: int) -> datetime:
    return HS + timedelta(minutes=minutes)


def load_fixture(name: str) -> Problem:
    doc = json.loads((FIXTURE_DIR / f"{name}.json").read_text())
    assert doc["format"] == "superplanner.problem" and doc["format_version"] == 1
    return Problem.model_validate(doc["problem"])


def task(tid: str, d: int = 60, alts=None, name: str | None = None, **kw) -> Task:
    reqs = []
    if alts:
        groups = alts if isinstance(alts[0], (list, tuple)) else [alts]
        reqs = [Requirement(alternatives=list(g)) for g in groups]
    if "requirements" in kw:
        reqs = kw.pop("requirements")
    if kw.get("type") == "milestone":
        d = 0
    return Task(id=tid, name=name or f"Op {tid}", duration_minutes=d, requirements=reqs, **kw)


def res(rid: str, cap: int = 1, cost: float = 0.0, calendar: Calendar | None = None, name: str | None = None,
        **kw) -> Resource:
    return Resource(id=rid, name=name or f"Mach {rid}", capacity=cap, cost_per_hour=cost, calendar=calendar, **kw)


def dep(a: str, b: str, t: str = "FS", lag: int = 0) -> Dependency:
    return Dependency(predecessor=a, successor=b, type=t, lag_minutes=lag)


def lock(minute: int, rids=None) -> Lock:
    return Lock(start=at(minute), resource_ids=rids)


def problem(tasks=(), resources=(), deps=(), days: int = 7, terms: Terminology | None = TERMS, **kw) -> Problem:
    return Problem(name="Test plan", horizon_start=kw.pop("horizon_start", HS), horizon_days=days,
                   terminology=terms or Terminology(), tasks=list(tasks), resources=list(resources),
                   dependencies=list(deps), **kw)


def compiled(p: Problem):
    return compile_problem(p)


def pl(tid: str, s: int, e: int, rids=()) -> Placement:
    return Placement(task_id=tid, start=s, end=e, resource_ids=list(rids))


def random_problem(seed: int, n_tasks: int = 8, n_res: int = 3, calendars: bool = True, deadlines: bool = True,
                   days: int = 10) -> Problem:
    """A random small problem without preflight errors (DAG by index, all dependency types)."""
    rng = random.Random(seed)
    cal = Calendar(weekly={d: [("06:00", "14:00"), ("15:00", "22:00")] for d in ("mon", "tue", "wed", "thu", "fri",
                                                                                     "sat", "sun")})
    resources = [res(f"R{i}", cap=rng.choice([1, 1, 2]), cost=float(rng.randint(0, 50)),
                     calendar=cal if (calendars and rng.random() < 0.5) else None) for i in range(n_res)]
    tasks = []
    for i in range(n_tasks):
        k = rng.choice([1, 1, 2])
        alts = rng.sample([r.id for r in resources], k)
        kw = {}
        if deadlines and rng.random() < 0.4:
            kw["deadline"] = at(rng.randint(300, 3000))
        if rng.random() < 0.2:
            kw["earliest_start"] = at(rng.randint(0, 600))
        tasks.append(task(f"T{i}", rng.randint(10, 300), alts if rng.random() < 0.9 else None,
                          priority=rng.randint(1, 10), **kw))
    deps, seen = [], set()
    for i in range(1, n_tasks):
        for _ in range(rng.choice([0, 1, 1, 2])):
            j = rng.randrange(0, i)
            if (j, i) in seen:
                continue
            seen.add((j, i))
            deps.append(dep(f"T{j}", f"T{i}", rng.choice(["FS", "FS", "SS", "FF", "SF"]), rng.choice([0, 0, 20, -10])))
    return problem(tasks, resources, deps, days=days)
