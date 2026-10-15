"""Acceptance 1.20: a 2000-task / 50-resource problem stays within budget."""

import random
import time
from datetime import timedelta

from engine_helpers import HS, dep, problem, res, task
from superplanner.engine import OptimizeRequest, optimize, preflight, validate_schedule
from superplanner.engine.model import Calendar


def _big(seed: int = 1):
    rng = random.Random(seed)
    cal = Calendar(weekly={d: [("06:00", "22:00")] for d in ("mon", "tue", "wed", "thu", "fri")})
    resources = [res(f"R{i}", cap=rng.choice([1, 1, 2, 3]), cost=float(rng.randint(10, 100)),
                     calendar=cal if i % 2 else None) for i in range(50)]
    tasks = []
    for i in range(2000):
        alts = rng.sample([r.id for r in resources], rng.choice([1, 2, 3]))
        kw = {"deadline": HS + timedelta(days=rng.randint(5, 60))} if rng.random() < 0.3 else {}
        tasks.append(task(f"T{i}", rng.randint(15, 240), alts, priority=rng.randint(1, 10), **kw))
    deps, seen = [], set()
    for i in range(1, 2000):
        for _ in range(rng.choice([0, 1, 1, 2])):
            j = rng.randrange(max(0, i - 50), i)
            if (j, i) not in seen:
                seen.add((j, i))
                deps.append(dep(f"T{j}", f"T{i}", rng.choice(["FS", "FS", "SS", "FF", "SF"]), rng.choice([0, 30, -15])))
    return problem(tasks, resources, deps, days=120)


def test_scale_smoke():
    p = _big()
    t0 = time.monotonic()
    rep = preflight(p)
    assert time.monotonic() - t0 < 2.0 and rep.ok
    t0 = time.monotonic()
    out = optimize(p, OptimizeRequest(strategy="heuristic", time_limit_seconds=10))
    assert time.monotonic() - t0 < 10 + 3
    assert out.result.feasibility == "feasible"
    assert validate_schedule(p, out.result.placements).feasibility == "feasible"
