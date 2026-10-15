"""Benchmarks (criterion 4.6, A.19): run with `pytest -q -s -m slow tests/integration/test_int_benchmarks.py`.

Prints one row per instance and strategy: feasibility, time to first feasible, makespan, score and
the score ratio against CP-SAT. Asserts only safety properties (feasible results validate; the
infeasible instance is never reported feasible; the nearly infeasible one is solved by cpsat).
"""

from __future__ import annotations

import json
import random
import time
from datetime import date, datetime, timedelta

import pytest

from int_helpers import FIXTURE_DIR, independent_check
from superplanner import engine
from superplanner.engine import OptimizeRequest, Problem
from superplanner.templates import get_template

pytestmark = pytest.mark.slow
HS = "2026-10-19T00:00:00+00:00"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())["problem"]


def _rcpsp(seed: int = 3, n: int = 30, k: int = 4) -> dict:
    rng = random.Random(seed)
    res = [{"id": f"R{i}", "name": f"Crew {i}", "capacity": rng.randint(2, 4)} for i in range(k)]
    tasks = []
    for i in range(n):
        reqs = [{"alternatives": [r["id"]], "units": rng.randint(1, r["capacity"])}
                for r in rng.sample(res, rng.randint(1, 2))]
        tasks.append({"id": f"A{i}", "name": f"Activity {i}", "duration_minutes": rng.randint(1, 10) * 30,
                      "requirements": reqs})
    deps = []
    for i in range(1, n):
        for j in rng.sample(range(i), min(i, rng.randint(0, 2))):
            deps.append({"predecessor": f"A{j}", "successor": f"A{i}"})
    return {"name": "RCPSP-like 30x4", "horizon_start": HS, "horizon_days": 30, "tasks": tasks, "resources": res,
            "dependencies": deps}


def _nearly_infeasible() -> dict:
    # 6 tasks of 100 min on two machines, all with a hard deadline at 300: only perfect packing works
    tasks = [{"id": f"N{i}", "name": f"Job {i}", "duration_minutes": 100, "deadline": "2026-10-19T05:00:00+00:00",
              "deadline_hard": True, "requirements": [{"alternatives": ["M1", "M2"]}]} for i in range(6)]
    return {"name": "Nearly infeasible", "horizon_start": HS, "horizon_days": 2, "tasks": tasks,
            "resources": [{"id": "M1", "name": "M1"}, {"id": "M2", "name": "M2"}], "dependencies": []}


def _study_plan() -> dict:
    p = get_template("exam_prep").build(name="Study", start_date=date(2026, 10, 19), utc_offset="+05:30",
                                        params={"subjects": ["Math", "Physics", "Chemistry", "Biology"],
                                                "topics_per_subject": 5, "exam_in_days": 45})
    return p.model_dump(mode="json")


INSTANCES = {
    "precedence_only": lambda: _fixture("precedence_only"),
    "rcpsp_30x4": _rcpsp,
    "flexible_jobshop_10x5": lambda: _fixture("flexible_jobshop_10x5"),
    "calendar_heavy_study": _study_plan,
    "calendar_heavy_fixture": lambda: _fixture("calendar_heavy"),
    "infeasible_hard_deadline": lambda: _fixture("infeasible_hard_deadline"),
    "nearly_infeasible": _nearly_infeasible,
}
RUNS = [("heuristic", 0), ("cpsat", 0), ("ga", 1), ("ga", 2), ("ga", 3), ("hybrid", 0), ("auto", 0)]


def _run(doc: dict, strategy: str, seed: int, limit: float = 5.0):
    problem = Problem.model_validate(doc)
    t0 = time.monotonic()
    first = [None]

    def cb(ev):
        if first[0] is None and ev.feasible_found:
            first[0] = time.monotonic() - t0

    out = engine.optimize(problem, OptimizeRequest(strategy=strategy, time_limit_seconds=limit, seed=seed), cb)
    return out, time.monotonic() - t0, first[0]


def test_int_benchmarks():
    rows = []
    for name, build in INSTANCES.items():
        doc = build()
        results = {}
        for strategy, seed in RUNS:
            out, wall, ttf = _run(doc, strategy, seed)
            r = out.result
            assert wall < 5.0 + 3.0, (name, strategy, wall)
            if r.feasibility == "feasible":
                assert independent_check(doc, [p.model_dump() for p in r.placements]) == [], (name, strategy)
            results[(strategy, seed)] = (r, wall, ttf)
        cp = results[("cpsat", 0)][0]
        for (strategy, seed), (r, wall, ttf) in results.items():
            score = r.objectives.score if r.objectives else None
            ratio = (score / cp.objectives.score) if (score is not None and cp.objectives and cp.objectives.score) else None
            rows.append((name, f"{strategy}#{seed}", r.feasibility, r.termination_reason, wall, ttf,
                         r.objectives.makespan_minutes if r.objectives else None, score, ratio))
        if name == "infeasible_hard_deadline":
            assert all(v[0].feasibility != "feasible" for v in results.values())
        if name == "nearly_infeasible":
            assert cp.feasibility == "feasible"
    hdr = ("instance", "strategy#seed", "feasibility", "termination", "wall_s", "first_feasible_s", "makespan",
           "score", "vs_cpsat")
    print()
    print(" | ".join(f"{h:>22}" if i == 0 else f"{h:>14}" for i, h in enumerate(hdr)))
    for row in rows:
        cells = []
        for i, v in enumerate(row):
            if isinstance(v, float):
                v = f"{v:.3f}"
            cells.append(f"{str(v):>22}" if i == 0 else f"{str(v):>14}")
        print(" | ".join(cells))
    feas = {}
    for row in rows:
        feas.setdefault(row[1].split("#")[0], []).append(row[2] == "feasible")
    print("feasibility rate:", {k: f"{sum(v)}/{len(v)}" for k, v in feas.items()})
