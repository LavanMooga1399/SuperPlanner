"""A.10 independent validator, tested with hand-built schedules before any solver (A.19)."""

import pytest

from engine_helpers import at, compiled, dep, lock, pl, problem, res, task
from superplanner.engine.compiled import build_compiled
from superplanner.engine.model import Calendar, Requirement
from superplanner.engine.validator import compute_metrics, validate

DAY = Calendar(weekly={d: [("08:00", "16:00")] for d in ("mon", "tue", "wed", "thu", "fri")})


def codes(rep):
    return [v.code for v in rep.violations]


def base():
    return problem([task("A", 60, ["R"], name="Cutting"), task("B", 30, ["R", "S"], name="Milling")],
                   [res("R", name="Saw", cost=60), res("S", name="Mill", cost=120)], [dep("A", "B")])


def test_valid_schedule():
    cp = compiled(base())
    rep = validate(cp, [pl("A", 0, 60, ["R"]), pl("B", 60, 90, ["S"])])
    assert rep.feasibility == "feasible" and rep.violations == []
    m = rep.metrics
    assert (m.makespan_minutes, m.cost, m.scheduled_tasks, m.total_tasks) == (90, 120.0, 2, 2)
    assert m.utilization == {"R": round(60 / 90, 4), "S": round(30 / 90, 4)}


@pytest.mark.parametrize("placements,code", [
    ([pl("A", 0, 60, ["R"])], "TASK_MISSING"),
    ([pl("A", 0, 60, ["R"]), pl("A", 0, 60, ["R"]), pl("B", 60, 90, ["S"])], "TASK_DUPLICATE"),
    ([pl("A", 0, 60, ["R"]), pl("B", 60, 90, ["S"]), pl("Z", 0, 1)], "UNKNOWN_TASK"),
    ([pl("A", 0, 50, ["R"]), pl("B", 60, 90, ["S"])], "DURATION_MISMATCH"),
    ([pl("A", 0, 60, ["R"]), pl("B", 7 * 1440 - 10, 7 * 1440 + 20, ["S"])], "OUTSIDE_HORIZON"),
    ([pl("A", 0, 60, ["R"]), pl("B", 30, 60, ["S"])], "DEPENDENCY_VIOLATED"),
    ([pl("A", 0, 60, []), pl("B", 60, 90, ["S"])], "RESOURCE_COUNT_MISMATCH"),
    ([pl("A", 0, 60, ["S"]), pl("B", 60, 90, ["S"])], "RESOURCE_NOT_ELIGIBLE"),
    ([pl("A", 0, 60, ["R"]), pl("B", 30, 90, ["R"])], "CAPACITY_EXCEEDED"),
])
def test_hard_codes(placements, code):
    rep = validate(compiled(base()), placements)
    assert code in codes(rep), codes(rep)
    assert rep.feasibility == "unknown"
    v = next(v for v in rep.violations if v.code == code)
    assert v.severity == "hard" and v.message


def test_earliest_start_violated():
    cp = compiled(problem([task("A", 60, earliest_start=at(100))]))
    rep = validate(cp, [pl("A", 50, 110)])
    v = next(v for v in rep.violations if v.code == "EARLIEST_START_VIOLATED")
    assert v.details == {"earliest": 100, "start": 50}


def test_resource_duplicate():
    cp = compiled(problem([task("A", 60, [["R", "S"], ["R", "S"]])], [res("R"), res("S")]))
    assert "RESOURCE_DUPLICATE" in codes(validate(cp, [pl("A", 0, 60, ["R", "R"])]))
    assert validate(cp, [pl("A", 0, 60, ["S", "R"])]).feasibility == "feasible"


def test_calendar_violated_and_single_window_rule():
    cp = compiled(problem([task("A", 120, ["R"])], [res("R", calendar=DAY)]))
    assert validate(cp, [pl("A", 480, 600, ["R"])]).feasibility == "feasible"
    rep = validate(cp, [pl("A", 900, 1020, ["R"])])  # 15:00-17:00, window ends 16:00
    v = next(v for v in rep.violations if v.code == "CALENDAR_VIOLATED")
    assert v.details == {"start": 900, "end": 1020}
    # spanning two windows (overnight) is not allowed even if both ends are inside windows
    rep2 = validate(cp, [pl("A", 1440 * 0 + 900, 1440 + 480 + 60, ["R"])])
    assert "CALENDAR_VIOLATED" in codes(rep2)


def test_lock_violated():
    cp = compiled(problem([task("A", 60, ["R", "S"], locked=lock(100, ["S"]))], [res("R"), res("S")]))
    assert validate(cp, [pl("A", 100, 160, ["S"])]).feasibility == "feasible"
    rep = validate(cp, [pl("A", 100, 160, ["R"])])
    v = next(v for v in rep.violations if v.code == "LOCK_VIOLATED")
    assert v.details["locked_resource_ids"] == ["S"]
    assert "LOCK_VIOLATED" in codes(validate(cp, [pl("A", 90, 150, ["S"])]))


def test_hard_and_soft_deadlines():
    # build without preflight: this hand-made case is deliberately impossible
    cp = build_compiled(problem([task("A", 60, deadline=at(50), deadline_hard=True),
                                 task("B", 60, deadline=at(30), priority=3)]))
    rep = validate(cp, [pl("A", 0, 60), pl("B", 0, 60)])
    hard = next(v for v in rep.violations if v.code == "HARD_DEADLINE_MISSED")
    soft = next(v for v in rep.violations if v.code == "DEADLINE_MISSED")
    assert hard.severity == "hard" and hard.details == {"deadline": 50, "end": 60, "minutes_late": 10}
    assert soft.severity == "soft" and soft.details["minutes_late"] == 30
    assert rep.metrics.weighted_tardiness == 90 and rep.metrics.late_tasks == 1
    assert rep.metrics.hard_deadline_misses == 1
    # soft only -> still feasible
    cp2 = compiled(problem([task("B", 60, deadline=at(30))]))
    assert validate(cp2, [pl("B", 0, 60)]).feasibility == "feasible"


def test_touching_intervals_ok():
    cp = compiled(problem([task("A", 60, ["R"]), task("B", 60, ["R"])], [res("R")]))
    assert validate(cp, [pl("A", 0, 60, ["R"]), pl("B", 60, 120, ["R"])]).feasibility == "feasible"


def test_three_overlapping_on_capacity_two():
    cp = compiled(problem([task("A", 100, ["R"]), task("B", 100, ["R"]), task("C", 100, ["R"])], [res("R", cap=2)]))
    rep = validate(cp, [pl("A", 0, 100, ["R"]), pl("B", 50, 150, ["R"]), pl("C", 80, 180, ["R"])])
    caps = [v for v in rep.violations if v.code == "CAPACITY_EXCEEDED"]
    assert len(caps) == 1
    assert caps[0].details == {"from": 80, "to": 100, "usage": 3, "capacity": 2}
    assert caps[0].task_ids == ["A", "B", "C"]


def test_units_count_toward_capacity():
    cp = compiled(problem([task("A", 60, requirements=[Requirement(alternatives=["R"], units=2)]),
                           task("B", 60, ["R"])], [res("R", cap=2)]))
    assert "CAPACITY_EXCEEDED" in codes(validate(cp, [pl("A", 0, 60, ["R"]), pl("B", 30, 90, ["R"])]))
    assert validate(cp, [pl("A", 0, 60, ["R"]), pl("B", 60, 120, ["R"])]).feasibility == "feasible"


@pytest.mark.parametrize("dtype,lag,a,b,ok", [
    ("FS", 10, (0, 60), (70, 100), True), ("FS", 10, (0, 60), (69, 99), False),
    ("SS", 30, (0, 60), (30, 60), True), ("SS", 30, (0, 60), (29, 59), False),
    ("FF", 0, (0, 60), (30, 60), True), ("FF", 0, (0, 60), (29, 59), False),
    ("SF", 45, (0, 60), (15, 45), True), ("SF", 45, (0, 60), (14, 44), False),
    ("FS", -20, (0, 60), (40, 70), True),
])
def test_dependency_types(dtype, lag, a, b, ok):
    cp = compiled(problem([task("A", 60), task("B", 30)], [], [dep("A", "B", dtype, lag)]))
    rep = validate(cp, [pl("A", *a), pl("B", *b)])
    assert (rep.feasibility == "feasible") is ok
    if not ok:
        v = rep.violations[0]
        assert v.code == "DEPENDENCY_VIOLATED" and v.details["type"] == dtype
        assert v.details["required_minute"] - v.details["actual_minute"] == 1


def test_milestones_exempt_from_calendar():
    cp = compiled(problem([task("M", 0, type="milestone")], []))
    assert validate(cp, [pl("M", 500, 500)]).feasibility == "feasible"


def test_violations_sorted_and_not_fail_fast():
    cp = compiled(base())
    rep = validate(cp, [pl("A", -5, 50, ["S"])])
    cs = codes(rep)
    assert {"TASK_MISSING", "DURATION_MISMATCH", "OUTSIDE_HORIZON", "RESOURCE_NOT_ELIGIBLE"} <= set(cs)
    assert cs == sorted(cs)


def test_message_uses_terminology_and_names():
    cp = compiled(base())
    rep = validate(cp, [pl("A", 0, 60, ["R"]), pl("B", 30, 60, ["R"])])
    dv = next(v for v in rep.violations if v.code == "DEPENDENCY_VIOLATED")
    assert dv.message.startswith('Operation "Milling" must start after "Cutting" finishes (finish-to-start)')
    assert "30m too early" in dv.message
    cv = next(v for v in rep.violations if v.code == "CAPACITY_EXCEEDED")
    assert cv.message == 'Machine "Saw" is overbooked from Mon 19 Oct 00:30 to Mon 19 Oct 01:00 (2 of 1 in use).'


def test_compute_metrics_matches_validate():
    cp = compiled(base())
    pls = [pl("A", 0, 60, ["R"]), pl("B", 60, 90, ["R"])]
    assert compute_metrics(cp, pls) == validate(cp, pls).metrics
