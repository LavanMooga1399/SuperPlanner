"""A.8.1 serial SGS decoder and A.8.2 left-shift compaction."""

import dataclasses
import random

import pytest

from engine_helpers import at, compiled, dep, lock, pl, problem, random_problem, res, task
from superplanner.engine.compiled import build_compiled
from superplanner.engine.decoder import decode, left_shift
from superplanner.engine.model import Calendar, Requirement
from superplanner.engine.objectives import ObjectiveRefs, make_values
from superplanner.engine.validator import validate

DAY = Calendar(weekly={d: [("08:00", "16:00")] for d in ("mon", "tue", "wed", "thu", "fri")})


def by_id(dr):
    return {p.task_id: p for p in dr.placements}


def flat(cp):
    return [0.0] * len(cp.tasks)


def test_earliest_placement_and_capacity():
    cp = compiled(problem([task("A", 60, ["R"]), task("B", 60, ["R"]), task("C", 60, ["R"])], [res("R", cap=2)]))
    dr = decode(cp, [0.0, 0.1, 0.2])
    p = by_id(dr)
    assert (p["A"].start, p["B"].start, p["C"].start) == (0, 0, 60)
    assert validate(cp, dr.placements).feasibility == "feasible"


def test_calendar_no_straddle():
    cp = compiled(problem([task("A", 400, ["R"]), task("B", 120, ["R"])], [res("R", calendar=DAY)]))
    p = by_id(decode(cp, [0.0, 0.1]))
    assert p["A"].start == 480 and p["A"].end == 880
    # B (2h) no longer fits before 16:00 (880 + 120 > 960) -> next day 08:00
    assert p["B"].start == 1440 + 480


def test_priority_order_and_greedy_cheapest():
    cp = compiled(problem([task("A", 60, ["X", "Y"]), task("B", 60, ["X", "Y"])],
                          [res("X", cost=100), res("Y", cost=10)]))
    p = by_id(decode(cp, [0.5, 0.1]))
    assert p["B"].resource_ids == ["Y"] and p["B"].start == 0
    assert p["A"].resource_ids == ["X"] and p["A"].start == 0  # Y busy, X free at 0


def test_resource_choice_fixed_and_repair():
    cp = compiled(problem([task("A", 60, ["X", "Y"])], [res("X", cost=1), res("Y", cost=99, calendar=DAY)]))
    p = by_id(decode(cp, [0.0], {(0, 0): 1}))
    assert p["A"].resource_ids == ["Y"] and p["A"].start == 480
    cp2 = compiled(problem([task("A", 600, ["X", "Y"])], [res("X"), res("Y", calendar=DAY)]))
    dr = decode(cp2, [0.0], {(0, 0): 1})  # Y has no 10h window -> greedy fallback
    assert dr.repairs == 1 and by_id(dr)["A"].resource_ids == ["X"]


def test_multi_requirement_distinct():
    cp = compiled(problem([task("A", 60, [["R", "S"], ["R", "S"]]), task("B", 60, ["R"])], [res("R"), res("S")]))
    dr = decode(cp, [0.0, 0.1])
    p = by_id(dr)
    assert sorted(p["A"].resource_ids) == ["R", "S"] and p["B"].start == 60
    assert validate(cp, dr.placements).feasibility == "feasible"


def test_multi_requirement_backtracking():
    # greedy (cheapest) choice for requirement 0 would steal the only option of requirement 1
    cp = compiled(problem([task("A", 60, [["R", "S"], ["R"]])], [res("R", cost=1), res("S", cost=5)]))
    p = by_id(decode(cp, [0.0]))
    assert p["A"].resource_ids == ["S", "R"] and p["A"].start == 0


@pytest.mark.parametrize("dtype,lag", [("FS", 0), ("FS", 30), ("SS", 15), ("FF", 0), ("SF", 90), ("FS", -20)])
def test_dependencies_honoured(dtype, lag):
    cp = compiled(problem([task("A", 60, ["R"]), task("B", 45, ["S"])], [res("R"), res("S")],
                          [dep("A", "B", dtype, lag)]))
    dr = decode(cp, [0.0, 0.1])
    assert validate(cp, dr.placements).feasibility == "feasible"
    p = by_id(dr)
    expected = {"FS": 60 + lag, "SS": lag, "FF": 60 + lag - 45, "SF": lag - 45}[dtype]
    assert p["B"].start == max(0, expected)


def test_locked_first_and_conflict_counted():
    cp = compiled(problem([task("A", 60, ["R"]), task("B", 60, ["R"], locked=lock(30, ["R"]))], [res("R")]))
    dr = decode(cp, [0.0, 0.0])
    p = by_id(dr)
    assert p["B"].start == 30 and p["A"].start == 90 and dr.lock_conflicts == 0
    cp2 = build_compiled(problem([task("A", 60, ["R"], locked=lock(0, ["R"])),
                                  task("B", 60, ["R"], locked=lock(30, ["R"]))], [res("R")]))
    dr2 = decode(cp2, [0.0, 0.0])
    assert dr2.lock_conflicts == 1 and len(dr2.placements) == 2  # reserved even though overloaded


def test_lock_without_resources_picks_one():
    cp = compiled(problem([task("A", 60, ["R", "S"], locked=lock(0)), task("B", 60, ["R"], locked=lock(0, ["R"]))],
                          [res("R"), res("S")]))
    p = by_id(decode(cp, [0.0, 0.0]))
    assert p["A"].resource_ids == ["S"] and p["A"].start == 0


def test_unschedulable_cascade():
    cp = build_compiled(problem([task("A", 600, ["R"]), task("B", 30, ["S"])], [res("R", calendar=DAY), res("S")],
                                [dep("A", "B")]))
    dr = decode(cp, [0.0, 0.1])
    assert dr.unscheduled == [0, 1]
    assert dr.reasons[0] == "NO_SLOT" and dr.reasons[1] == "PREDECESSOR_UNSCHEDULED"


def test_milestone_and_no_requirement_tasks():
    cp = compiled(problem([task("A", 60, ["R"]), task("M", 0, type="milestone"), task("F", 30)], [res("R")],
                          [dep("A", "M"), dep("M", "F", "FS", 15)]))
    p = by_id(decode(cp, flat(cp)))
    assert (p["M"].start, p["M"].end, p["F"].start) == (60, 60, 75)


def _spread(cp, seed):
    """A valid but non-compact schedule: decode with extra random releases."""
    rng = random.Random(seed)
    delayed = dataclasses.replace(cp, tasks=tuple(dataclasses.replace(t, release=t.release + rng.randint(0, 600))
                                                  for t in cp.tasks))
    return decode(delayed, [rng.random() for _ in cp.tasks]).placements


def test_left_shift_property_100_random():
    checked_valid = 0
    for seed in range(100):
        cp = build_compiled(random_problem(seed, n_tasks=8, n_res=3))
        if seed % 4 == 3:  # sometimes an arbitrary (likely invalid) schedule
            rng = random.Random(seed)
            pls = []
            for t in cp.tasks:
                s = rng.randint(0, 2000)
                rids = [cp.resources[rng.choice(r.alternatives)].id for r in t.requirements if r.alternatives]
                pls.append(pl(t.id, s, s + t.duration, rids))
        else:
            pls = _spread(cp, seed)
        before = validate(cp, pls)
        out = left_shift(cp, pls)
        after = validate(cp, out)
        ob = {p.task_id: p for p in pls}
        for p in out:
            assert p.end <= ob[p.task_id].end
            assert p.end - p.start == ob[p.task_id].end - ob[p.task_id].start
            assert p.resource_ids == ob[p.task_id].resource_ids
        if before.feasibility == "feasible":
            checked_valid += 1
            assert after.feasibility == "feasible", after.violations
        w = cp.weights
        refs = ObjectiveRefs()
        sb = make_values(before.metrics.makespan_minutes, before.metrics.weighted_tardiness, before.metrics.cost, w, refs)
        sa = make_values(after.metrics.makespan_minutes, after.metrics.weighted_tardiness, after.metrics.cost, w, refs)
        assert sa.score <= sb.score + 1e-9
    assert checked_valid >= 60


def test_left_shift_keeps_locks_and_compacts():
    cp = compiled(problem([task("A", 60, ["R"]), task("B", 60, ["R"], locked=lock(500, ["R"])), task("C", 30, ["R"])],
                          [res("R")], [dep("A", "C")]))
    out = {p.task_id: p for p in left_shift(cp, [pl("A", 200, 260, ["R"]), pl("B", 500, 560, ["R"]),
                                                  pl("C", 900, 930, ["R"])])}
    assert out["A"].start == 0 and out["B"].start == 500 and out["C"].start == 60
