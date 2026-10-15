"""A.9.1: every preflight code fires with its severity and a readable, terminology-based message."""

from datetime import timedelta

import pytest

from engine_helpers import HS, at, dep, lock, problem, res, task
from superplanner.engine import PROVEN_INFEASIBLE_CODES, analyze, preflight
from superplanner.engine.model import BlockedInterval, Calendar, Requirement

DAY = Calendar(weekly={d: [("08:00", "16:00")] for d in ("mon", "tue", "wed", "thu", "fri")})


def _cases():
    yield "NO_TASKS", "warning", problem([], []), ["operations"]
    yield "TOO_LARGE", "error", problem([task(f"T{i}", 1) for i in range(2001)]), ["operations"]
    yield "DUPLICATE_ID", "error", problem([task("A", 10, name="Cutting"), task("A", 10, name="Milling")]), \
        ["Milling", "operation"]
    yield "UNKNOWN_RESOURCE", "error", problem([task("A", 10, ["GHOST"], name="Cutting")]), ["Cutting", "machine"]
    yield "UNKNOWN_TASK", "error", problem([task("A", 10, name="Cutting")], [], [dep("A", "GHOST")]), \
        ["GHOST", "operation"]
    yield "SELF_DEPENDENCY", "error", problem([task("A", 10, name="Cutting")], [], [dep("A", "A")]), \
        ["Cutting", "Operation"]
    yield "DUPLICATE_DEPENDENCY", "error", problem([task("A", 10, name="Cutting"), task("B", 10, name="Milling")],
                                                   [], [dep("A", "B"), dep("A", "B", "SS")]), \
        ["Cutting", "Milling", "Operation"]
    yield "DEPENDENCY_CYCLE", "error", problem([task("A", 10, name="Cutting"), task("B", 10, name="Milling"),
                                                task("C", 10, name="Assembly")], [],
                                               [dep("A", "B"), dep("B", "C"), dep("C", "A")]), \
        ['"Cutting" -> "Milling" -> "Assembly" -> "Cutting"', "Operations"]
    yield "UNITS_EXCEED_CAPACITY", "error", problem(
        [task("A", 10, requirements=[Requirement(alternatives=["R"], units=3)], name="Cutting")],
        [res("R", cap=2)]), ["Cutting", "machine"]
    yield "NO_FITTING_WINDOW", "error", problem([task("A", 600, ["R"], name="Cutting")],
                                                [res("R", calendar=DAY, name="Saw")]), ["Cutting", "Saw", "8h"]
    yield "INVALID_CALENDAR", "error", problem([task("A", 10, ["R"])], [res("R", name="Saw", calendar=Calendar(
        weekly={"mon": [("10:00", "09:00")]}))]), ["Saw", "Machine"]
    yield "EMPTY_CALENDAR", "warning", problem([], [res("R", name="Saw", calendar=Calendar(weekly={}))]), \
        ["Saw", "Machine"]
    yield "EARLIEST_AFTER_HORIZON", "error", problem([task("A", 120, name="Cutting", earliest_start=at(7 * 1440 - 60))]), \
        ["Cutting", "Operation"]
    yield "DEADLINE_BEFORE_EARLIEST", "error", problem(
        [task("A", 120, name="Cutting", earliest_start=at(100), deadline=at(150), deadline_hard=True)]), \
        ["Cutting", "Operation"]
    yield "DEADLINE_BEFORE_HORIZON", "error", problem([task("A", 10, name="Cutting", deadline=at(-60))]), \
        ["Cutting", "Operation"]
    yield "LOCK_INVALID", "error", problem([task("A", 10, ["R"], name="Cutting", locked=lock(0, ["S"]))],
                                           [res("R"), res("S")]), ["Cutting", "Operation"]
    yield "HARD_DEADLINE_IMPOSSIBLE", "error", problem(
        [task("A", 120, name="Cutting"), task("B", 120, name="Milling", deadline=at(200), deadline_hard=True)],
        [], [dep("A", "B")]), ["Milling", "Operation", "unlimited machines"]
    yield "HORIZON_TOO_SHORT", "error", problem([task("A", 1000, name="Cutting"), task("B", 1000, name="Milling")],
                                                [], [dep("A", "B")], days=1), ["horizon", "1d 9h 20m"]
    yield "SOFT_DEADLINE_UNREACHABLE", "warning", problem(
        [task("A", 120, name="Cutting"), task("B", 120, name="Milling", deadline=at(200))], [], [dep("A", "B")]), \
        ["Milling", "Operation", "40m"]
    yield "UNUSED_RESOURCE", "warning", problem([task("A", 10)], [res("R", name="Saw")]), ["Saw", "Machine",
                                                                                            "operation"]
    yield "MILESTONE_WITH_LOCKED_RESOURCES", "error", problem(
        [task("M", 0, type="milestone", name="Ship", locked=lock(10, ["R"])), task("A", 10, ["R"])], [res("R")]), \
        ["Ship", "machines"]
    yield "LAG_OUT_OF_RANGE", "error", problem([task("A", 10, name="Cutting"), task("B", 10, name="Milling")], [],
                                               [dep("A", "B", lag=8 * 1440)]), ["Cutting", "Milling", "operation"]


CASES = list(_cases())


@pytest.mark.parametrize("code,severity,prob,words", CASES, ids=[c[0] for c in CASES])
def test_every_code_fires(code, severity, prob, words):
    issues = [i for i in preflight(prob).issues if i.code == code]
    assert issues, f"{code} not reported: {[i.code for i in preflight(prob).issues]}"
    issue = issues[0]
    assert issue.severity == severity
    for w in words:
        assert w.lower() in issue.message.lower(), (w, issue.message)


def test_all_contract_codes_are_covered():
    from superplanner.engine.preflight import CHECK_ORDER
    assert {c[0] for c in CASES} == set(CHECK_ORDER)


def test_soft_deadline_before_earliest_is_warning():
    p = problem([task("A", 120, earliest_start=at(100), deadline=at(150))])
    issue = next(i for i in preflight(p).issues if i.code == "DEADLINE_BEFORE_EARLIEST")
    assert issue.severity == "warning"


def test_units_partially_exceed_capacity_is_warning():
    p = problem([task("A", 10, requirements=[Requirement(alternatives=["R", "S"], units=2)])],
                [res("R", cap=1), res("S", cap=2)])
    issue = next(i for i in preflight(p).issues if i.code == "UNITS_EXCEED_CAPACITY")
    assert issue.severity == "warning" and issue.resource_ids == ["R"]
    assert preflight(p).ok


def test_invalid_calendar_variants():
    for cal in (Calendar(weekly={"mon": [("24:00", "24:00")]}),
                Calendar(blocked=[BlockedInterval(start=at(100), end=at(50))])):
        p = problem([task("A", 10, ["R"])], [res("R", calendar=cal)])
        assert "INVALID_CALENDAR" in {i.code for i in preflight(p).issues}


def test_lock_conflicting_with_dependency():
    p = problem([task("A", 120, name="Cutting"), task("B", 30, name="Milling", locked=lock(60))], [], [dep("A", "B")])
    issue = next(i for i in preflight(p).issues if i.code == "LOCK_INVALID")
    assert "conflicts with its dependency" in issue.message and "Cutting" in issue.message


def test_lock_before_release_and_outside_horizon():
    p = problem([task("A", 30, earliest_start=at(100), locked=lock(50)), task("B", 30, locked=lock(-10))])
    assert [i.task_ids for i in preflight(p).issues if i.code == "LOCK_INVALID"] == [["A"], ["B"]]


def test_order_of_checks_and_ok_flag():
    p = problem([task("A", 10, ["GHOST"])], [res("R")], [dep("A", "A")])
    rep = preflight(p)
    assert not rep.ok
    codes = [i.code for i in rep.issues]
    assert codes == sorted(codes, key=["UNKNOWN_RESOURCE", "SELF_DEPENDENCY", "UNUSED_RESOURCE"].index)


def test_cpm_checks_skipped_on_structural_errors():
    p = problem([task("A", 120), task("B", 120, deadline=at(10), deadline_hard=True)], [],
                [dep("A", "B"), dep("B", "A")])
    rep = analyze(p)
    codes = {i.code for i in rep.issues}
    assert "DEPENDENCY_CYCLE" in codes and "HARD_DEADLINE_IMPOSSIBLE" not in codes
    assert rep.cpm is None


def test_analyze_returns_cpm_when_structure_ok():
    p = problem([task("A", 90, ["R"]), task("B", 120, ["R"])], [res("R"), res("U")], [dep("A", "B")])
    rep = analyze(p)
    assert rep.ok and rep.cpm is not None
    assert rep.cpm.lower_bound_makespan_minutes == 210 and rep.cpm.critical_path == ["A", "B"]


def test_proven_infeasible_codes_constant():
    assert PROVEN_INFEASIBLE_CODES == {"DEPENDENCY_CYCLE", "UNITS_EXCEED_CAPACITY", "NO_FITTING_WINDOW",
                                       "EARLIEST_AFTER_HORIZON", "DEADLINE_BEFORE_EARLIEST",
                                       "HARD_DEADLINE_IMPOSSIBLE", "HORIZON_TOO_SHORT"}


def test_fields_point_at_offending_rows():
    p = problem([task("A", 10), task("B", 10, ["GHOST"])], [])
    issue = next(i for i in preflight(p).issues if i.code == "UNKNOWN_RESOURCE")
    assert issue.field == "tasks[1].requirements[0]" and issue.task_ids == ["B"]
