"""A.11 solver-agnostic explanations."""

import pytest

from engine_helpers import at, compiled, dep, load_fixture, lock, pl, problem, res, task
from superplanner.engine import explain_schedule, optimize, OptimizeRequest
from superplanner.engine.explain import explain
from superplanner.engine.model import Calendar

DAY = Calendar(weekly={d: [("08:00", "16:00")] for d in ("mon", "tue", "wed", "thu", "fri")})


def reasons(p, placements):
    ex = explain(compiled(p), placements)
    return ex, {tid: te.reasons[0] for tid, te in ex.tasks.items()}


def test_every_reason_code():
    p = problem([task("L", 30, ["Q"], locked=lock(200, ["Q"]), name="Locked op"),
                 task("H", 30, ["Q"], name="First op"),
                 task("E", 30, ["F"], earliest_start=at(100), name="Released op"),
                 task("D", 30, ["F"], name="Follower"),
                 task("B", 30, ["Q"], name="Waiter"),
                 task("C", 60, ["DAYR"], name="Day op"),
                 task("O", 30, ["G"], name="Idle op"),
                 task("N", 30, ["G"], name="Missing op")],
                [res("Q", name="Mill 1"), res("F", name="Saw"), res("DAYR", name="Day press", calendar=DAY),
                 res("G", name="Spare")],
                [dep("E", "D")])
    placements = [pl("L", 200, 230, ["Q"]), pl("H", 0, 30, ["Q"]), pl("E", 100, 130, ["F"]),
                  pl("D", 130, 160, ["F"]), pl("B", 30, 60, ["Q"]), pl("C", 480, 540, ["DAYR"]),
                  pl("O", 100, 130, ["G"])]
    ex, r = reasons(p, placements)
    assert {k: v.code for k, v in r.items()} == {
        "L": "LOCKED", "H": "HORIZON_START", "E": "EARLIEST_START", "D": "DEPENDENCY", "B": "RESOURCE_BUSY",
        "C": "CALENDAR", "O": "OPTIMIZER_CHOICE", "N": "NOT_SCHEDULED"}
    assert r["D"].message == "Starts as soon as Released op finishes." and r["D"].related_task_ids == ["E"]
    assert r["B"].related_task_ids == ["H"] and "busy with First op until 00:30" in r["B"].message
    assert r["B"].resource_ids == ["Q"]
    assert "Day press" in r["C"].message and "Mon 19 Oct 08:00" in r["C"].message
    assert ex.tasks["N"].deadline_status == "none"
    assert any("could not be scheduled" in s for s in ex.summary)


def test_example_3_11():
    p = load_fixture("example_3_11")
    out = optimize(p, OptimizeRequest(strategy="heuristic", time_limit_seconds=2))
    ex = explain_schedule(p, out.result.placements)
    j11, j12 = ex.tasks["J1-1"].reasons[0], ex.tasks["J1-2"].reasons[0]
    assert j11.code == "CALENDAR" and "Saw 1" in j11.message and j11.resource_ids == ["CUT1"]
    assert j12.code == "DEPENDENCY" and "J1 Cutting" in j12.message
    assert ex.critical_chain == ["J1-1", "J1-2"]
    assert ex.cpm_critical_path == ["J1-1", "J1-2"]
    assert ex.tasks["J1-2"].deadline_status == "on_time" and ex.tasks["J1-1"].on_critical_chain


def test_critical_chain_through_resource_handoff_ordered():
    p = problem([task("A", 60, ["R"], name="Alpha"), task("B", 60, ["R"], name="Beta"),
                 task("C", 30, ["S"], name="Gamma")], [res("R"), res("S")], [dep("B", "C")])
    ex, r = reasons(p, [pl("A", 0, 60, ["R"]), pl("B", 60, 120, ["R"]), pl("C", 120, 150, ["S"])])
    assert ex.critical_chain == ["A", "B", "C"]
    assert ex.summary[-1] == "Completion is driven by the chain Alpha -> Beta -> Gamma."


def test_lateness_and_deadline_status():
    p = problem([task("A", 60, deadline=at(30)), task("B", 60, deadline=at(100), deadline_hard=True),
                 task("C", 60, deadline=at(500))])
    from superplanner.engine.compiled import build_compiled
    ex = explain(build_compiled(p), [pl("A", 0, 60), pl("B", 50, 110), pl("C", 0, 60)])
    t = ex.tasks
    assert (t["A"].deadline_status, t["A"].lateness_minutes) == ("late_soft", 30)
    assert (t["B"].deadline_status, t["B"].lateness_minutes) == ("late_hard", 10)
    assert t["C"].deadline_status == "on_time"
    assert any("finish late" in s for s in ex.summary)


@pytest.mark.parametrize("dtype,lag,start,text", [
    ("SS", 30, 30, "30m after Alpha starts"), ("FF", 0, 30, "Alpha finishes"), ("FS", -15, 45, "15m before Alpha")])
def test_dependency_messages(dtype, lag, start, text):
    p = problem([task("A", 60, name="Alpha"), task("B", 30, name="Beta")], [], [dep("A", "B", dtype, lag)])
    _, r = reasons(p, [pl("A", 0, 60), pl("B", start, start + 30)])
    assert r["B"].code == "DEPENDENCY" and text in r["B"].message
