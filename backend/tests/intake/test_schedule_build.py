"""`ScheduleDraft` -> `Problem` (PHASE2 2.9.1, 2.15 build example; plan P2-2)."""

from __future__ import annotations

from datetime import date

from api_helpers_shim import wait_run
from intake_helpers import API, CTX, EXAMPLE_ANSWERS, SCHEDULE_TEXT
from superplanner import intake
from superplanner.engine.model import pert_minutes
from superplanner.intake.models import (Answer, DraftDuration, DraftResource, DraftTask, ScheduleDraft, TimeWindow,
                                        WorkingTime)
from superplanner.intake.schedule.build import DOMAIN_OF_KIND, calendar_figures, weekly_of

G = CTX.model_copy(update={"kind": None})
WT = WorkingTime(days=["mon", "tue", "wed", "thu", "fri"], windows=[TimeWindow(start="09:00", end="17:00")])


def example_draft() -> ScheduleDraft:
    d = intake.describe_schedule(SCHEDULE_TEXT, CTX).draft
    return intake.answer_schedule(d, [Answer.model_validate(a) for a in EXAMPLE_ANSWERS], CTX).draft


def dur(o, m=None, p=None, unit="days"):
    m = o if m is None else m
    p = m if p is None else p
    return DraftDuration(optimistic=o, likely=m, pessimistic=p, unit=unit)


def draft(**kw) -> ScheduleDraft:
    base = dict(kind="generic", name="T", start_date=date(2026, 10, 19), working_time=WT)
    base.update(kw)
    return ScheduleDraft(**base)


def test_example_build_exact():
    b = intake.build_schedule(example_draft(), CTX)
    assert b.ready and b.blocking == []
    assert b.parts == {"t1": ["t1_1", "t1_2", "t1_3"], "t2": [f"t2_{i}" for i in range(1, 6)],
                       "t3": [f"t3_{i}" for i in range(1, 11)], "t4": ["t4_1", "t4_2", "t4_3", "t4_4"], "t5": ["t5"]}
    p = b.problem.model_dump(mode="json")
    assert (p["id"], p["name"], p["domain"], p["horizon_start"], p["horizon_days"], p["currency"]) == (
        "draft", "Website relaunch", "project", "2026-10-19T00:00:00+05:30", 64, "INR")
    t = {x["id"]: x for x in p["tasks"]}
    assert t["t1_1"]["name"] == "Gather requirements (1/3)" and t["t1_1"]["group"] == "Gather requirements"
    assert t["t1_1"]["duration_minutes"] == 400
    assert t["t1_1"]["duration_estimate"] == {"optimistic_minutes": 320, "likely_minutes": 400,
                                              "pessimistic_minutes": 480}
    assert t["t1_1"]["requirements"] == [{"alternatives": ["r_priya"], "units": 1}]
    assert t["t1_1"]["metadata"] == {"intake_key": "t1", "part": 1, "parts": 3}
    assert t["t4_1"]["name"] == "Testing (1/4)" and t["t4_1"]["duration_minutes"] == 480
    assert t["t4_1"]["duration_estimate"] == {"optimistic_minutes": 360, "likely_minutes": 480,
                                              "pessimistic_minutes": 600}
    assert "duration_estimate" not in t["t2_1"]          # o == p: no range
    assert (t["t5"]["type"], t["t5"]["duration_minutes"], t["t5"]["deadline"], t["t5"]["deadline_hard"]) == (
        "milestone", 0, "2026-12-15T17:00:00+05:30", False)
    deps = [(d["predecessor"], d["successor"], d["type"], d["lag_minutes"]) for d in p["dependencies"]]
    assert ("t1_1", "t1_2", "FS", 0) in deps and ("t1_3", "t2_1", "FS", 0) in deps
    assert ("t4_4", "t5", "FS", 0) in deps
    assert p["objectives"]["preset"] == "meet_deadlines"
    assert p["metadata"] == {"intake": {"version": 1, "source": "describe", "extractor": "rule"}}
    assert b.report.ok and b.report.cpm.lower_bound_makespan_minutes == 10320
    assert b.duration_summary.model_dump() == {"tasks_with_range": 2, "expected_work_minutes": 10320,
                                               "optimistic_work_minutes": 9600, "pessimistic_work_minutes": 11040}


def test_built_problem_accepted_and_solved_feasible(client):
    b = intake.build_schedule(example_draft(), CTX)
    r = client.post(f"{API}/problems", json=b.problem.model_dump(mode="json"))
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    run = client.post(f"{API}/problems/{pid}/solver-runs", json={"time_limit_seconds": 5})
    assert run.status_code == 202, run.text
    done = wait_run(client, run.json()["run_id"])
    assert done["status"] == "completed" and done["feasibility"] == "feasible", done
    sch = client.get(f"{API}/schedules/{done['primary_schedule_id']}").json()
    expl = client.get(f"{API}/schedules/{sch['id']}").json()
    assert expl["id"] == sch["id"]


def test_split_parts_respect_max_part_and_pert():
    d = draft(tasks=[DraftTask(key="t1", name="Big", duration=dur(3, 4, 8))])
    b = intake.build_schedule(d, G)
    parts = b.parts["t1"]
    o, m, p = 3 * 480, 4 * 480, 8 * 480
    n = len(parts)
    tasks = {t.id: t for t in b.problem.tasks}
    assert all(tasks[x].duration_minutes <= 480 for x in parts)
    assert sum(tasks[x].duration_estimate.optimistic_minutes for x in parts) == o
    assert sum(tasks[x].duration_estimate.likely_minutes for x in parts) == m
    assert sum(tasks[x].duration_estimate.pessimistic_minutes for x in parts) == p
    for x in parts:
        e = tasks[x].duration_estimate
        assert tasks[x].duration_minutes == pert_minutes(e.optimistic_minutes, e.likely_minutes, e.pessimistic_minutes)
    assert n >= -(-pert_minutes(o, m, p) // 480)
    assert [t.name for t in b.problem.tasks] == [f"Big ({i}/{n})" for i in range(1, n + 1)]


def test_unit_conversion_and_calendar_figures():
    study = WorkingTime(days=["mon", "tue", "wed", "thu", "fri"], windows=[TimeWindow(start="18:00", end="21:00")],
                        weekend_windows=[TimeWindow(start="09:00", end="13:00"), TimeWindow(start="14:00", end="18:00")])
    per_day, per_week, max_part = calendar_figures(weekly_of(study))
    assert per_week == 5 * 180 + 2 * 480 and max_part == 180
    assert per_day == per_week / 7
    d = draft(working_time=study, tasks=[DraftTask(key="t1", name="Read", duration=dur(90, unit="minutes")),
                                         DraftTask(key="t2", name="Write", duration=dur(1, unit="weeks"))])
    b = intake.build_schedule(d, G)
    tasks = {t.id: t for t in b.problem.tasks}
    assert tasks["t1"].duration_minutes == 90
    assert sum(tasks[x].duration_minutes for x in b.parts["t2"]) == per_week
    cal = b.problem.resources[0].calendar
    assert cal is not None


def test_requirement_modes_and_counts():
    res = [DraftResource(key="r_a", name="Ann", kind="person"), DraftResource(key="r_b", name="Bob", kind="person"),
           DraftResource(key="r_m", name="Lathe", kind="machine", count=2)]
    d = draft(resources=res, tasks=[
        DraftTask(key="t1", name="Any", duration=dur(1, unit="hours"), resources=["r_a", "r_b"]),
        DraftTask(key="t2", name="All", duration=dur(1, unit="hours"), resources=["r_a", "r_m"], resource_mode="all"),
        DraftTask(key="t3", name="None", duration=dur(1, unit="hours")),
        DraftTask(key="t4", name="Done", milestone=True)])
    b = intake.build_schedule(d, G)
    assert [r.id for r in b.problem.resources] == ["r_a", "r_b", "r_m_1", "r_m_2"]
    assert [r.name for r in b.problem.resources][2:] == ["Lathe 1", "Lathe 2"]
    t = {x.id: x for x in b.problem.tasks}
    assert [r.alternatives for r in t["t1"].requirements] == [["r_a", "r_b"]]
    assert [r.alternatives for r in t["t2"].requirements] == [["r_a"], ["r_m_1", "r_m_2"]]
    assert [r.alternatives for r in t["t3"].requirements] == [["r_a", "r_b", "r_m_1", "r_m_2"]]
    assert t["t4"].requirements == []


def test_default_resource_and_kinds():
    for kind, domain in DOMAIN_OF_KIND.items():
        d = draft(kind=kind, working_time=None, tasks=[DraftTask(key="t1", name="Job", duration=dur(1, unit="hours"))])
        b = intake.build_schedule(d, G)
        assert b.problem.domain == domain
        assert [r.id for r in b.problem.resources] == ["r_me"]
    assert DOMAIN_OF_KIND == {"project": "project", "study": "exam_prep", "production": "manufacturing",
                              "generic": "generic"}


def test_deadlines_and_earliest_start_on_window_edges():
    d = draft(tasks=[DraftTask(key="t1", name="A", duration=dur(1, unit="hours"), deadline=date(2026, 10, 21),
                               deadline_hard=True, earliest_start=date(2026, 10, 20))])
    b = intake.build_schedule(d, CTX)
    t = b.problem.tasks[0]
    assert t.deadline.isoformat() == "2026-10-21T17:00:00+05:30" and t.deadline_hard
    assert t.earliest_start.isoformat() == "2026-10-20T09:00:00+05:30"
    # a deadline on a day without windows -> 23:59
    d = draft(tasks=[DraftTask(key="t1", name="A", duration=dur(1, unit="hours"), deadline=date(2026, 10, 25))])
    assert intake.build_schedule(d, CTX).problem.tasks[0].deadline.isoformat() == "2026-10-25T23:59:00+05:30"


def test_horizon_formula():
    d = draft(tasks=[DraftTask(key="t1", name="A", duration=dur(10))])          # 4800 work minutes, 1 resource
    b = intake.build_schedule(d, G)
    assert b.problem.horizon_days == max(7, -(-15 * 7 * 4800 // (2400 * 10)) + 7)
    d = draft(horizon_days=100, tasks=[DraftTask(key="t1", name="A", duration=dur(1))])
    assert intake.build_schedule(d, G).problem.horizon_days == 100


def test_blocking_questions_and_cycles():
    d = draft(tasks=[DraftTask(key="t1", name="A")])
    b = intake.build_schedule(d, G)
    assert not b.ready and b.problem is None and [q.code for q in b.blocking] == ["SCHED_TASK_DURATION"]
    d = draft(tasks=[DraftTask(key="t1", name="A", duration=dur(1), after=["t2"]),
                     DraftTask(key="t2", name="B", duration=dur(1), after=["t1"])])
    b = intake.build_schedule(d, G)
    assert b.problem is not None and not b.ready
    assert any(i.code == "DEPENDENCY_CYCLE" for i in b.report.issues)


def test_start_date_default_next_working_day():
    d = draft(start_date=None, tasks=[DraftTask(key="t1", name="A", duration=dur(1))])
    ctx = CTX.model_copy(update={"today": date(2026, 10, 17)})     # a Saturday
    assert intake.build_schedule(d, ctx).problem.horizon_start.date() == date(2026, 10, 19)


def test_study_build_ready_after_defaults():
    r = intake.describe_schedule("I have 90 days to prepare for an exam. I can study three hours on weekdays and "
                                 "eight hours on weekends. I need to finish the syllabus, revise everything twice, "
                                 "and complete ten mock tests.", G)
    answers = [Answer(question_id=q.id, use_default=True) for q in r.questions if q.required]
    a = intake.answer_schedule(r.draft, answers, G)
    assert a.ready
    b = intake.build_schedule(a.draft, G)
    assert b.ready and b.problem.domain == "exam_prep"
    exam = next(t for t in b.problem.tasks if t.type == "milestone")
    assert exam.deadline_hard and exam.deadline.date() == date(2027, 1, 15)
    assert all(t.duration_minutes <= 240 for t in b.problem.tasks)
