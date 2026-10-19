"""PERT durations from intake are scheduled correctly (PHASE2 2.9.1, 2.14; plan P2-2, P2-9; P4 (a), (e)).

Every returned schedule is checked with the independent checker of `tests/integration/int_helpers.py`.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from p2_helpers import API, CTX_JSON, IN, ctx, sched_checker, solve_and_check, wait_run
from superplanner.engine import pert_minutes
from superplanner.intake import Answer, answer_schedule, build_schedule, describe_schedule

SPEC_TEXT = ("Website relaunch starting next Monday. Ravi and Priya are on the team.\n"
             "1. Gather requirements - 2-3 days (Priya)\n2. Design 1 week, after requirements, Priya\n"
             "3. Build the site: 2 weeks, Ravi\n4. Testing 3-5 days once the build is done\n5. Launch by 15 Dec 2026")
SPEC_ANSWERS = [{"question_id": "SCHED_WHO:/tasks/t4/resources", "value": ["r_ravi"]},
                {"question_id": "SCHED_WORKING_TIME:/working_time", "use_default": True},
                {"question_id": "SCHED_SEQUENTIAL:-", "value": True},
                {"question_id": "SCHED_PEOPLE:-", "skip": True}]
STUDY_TEXT = ("I have 90 days to prepare for an exam. I can study three hours on weekdays and eight hours on "
              "weekends. I need to finish the syllabus, revise everything twice, and complete ten mock tests.")
RANGE_TEXT = ("Office fit-out starting 2 Nov 2026. Anil and Meena do the work.\n"
              "1. Strip out 1-3 days (Anil)\n2. Wiring 2/4/7 days (Meena)\n3. Plastering optimistic 1, likely 2, "
              "pessimistic 4 days (Anil)\n4. Painting 3 days (2-5)\n5. Handover by 31 Dec 2026")


def built(text: str, answers=None, kind="project", default_all=True):
    c = ctx(kind=kind)
    r = describe_schedule(text, c)
    d = r.draft
    if answers:
        d = answer_schedule(d, [Answer(**a) for a in answers], c).draft
    elif default_all:
        r2 = answer_schedule(d, [Answer(question_id=q.id, use_default=True) for q in r.questions
                                 if q.default is not None], c)
        d = r2.draft
    b = build_schedule(d, c)
    assert b.ready, (b.blocking, b.report and b.report.issues)
    return d, b


def check_parts(draft, b):
    """Every part of a split task: PERT value per part, parts chained FS, totals equal the task's minutes."""
    prob = b.problem
    tasks = {t.id: t for t in prob.tasks}
    deps = {(d.predecessor, d.successor) for d in prob.dependencies}
    mpd = 480
    for dt in draft.tasks:
        ids = b.parts[dt.key]
        if dt.milestone:
            assert ids == [dt.key] and tasks[dt.key].duration_minutes == 0
            assert tasks[dt.key].duration_estimate is None
            continue
        parts = [tasks[i] for i in ids]
        for a, z in zip(ids, ids[1:]):
            assert (a, z) in deps, (a, z)
        for p in parts:
            est = p.duration_estimate
            if est is None:
                continue
            assert est.optimistic_minutes <= est.likely_minutes <= est.pessimistic_minutes
            assert p.duration_minutes == pert_minutes(est.optimistic_minutes, est.likely_minutes,
                                                      est.pessimistic_minutes)
        if all(p.duration_estimate for p in parts) and dt.duration.unit == "days":
            o = sum(p.duration_estimate.optimistic_minutes for p in parts)
            m = sum(p.duration_estimate.likely_minutes for p in parts)
            pp = sum(p.duration_estimate.pessimistic_minutes for p in parts)
            assert (o, m, pp) == (round(dt.duration.optimistic * mpd), round(dt.duration.likely * mpd),
                                  round(dt.duration.pessimistic * mpd))


def test_spec_example_builds_exact_parts_and_solves_with_every_strategy(client):
    d, b = built(SPEC_TEXT, SPEC_ANSWERS)
    assert {k: len(v) for k, v in b.parts.items()} == {"t1": 3, "t2": 5, "t3": 10, "t4": 4, "t5": 1}
    t = {x.id: x for x in b.problem.tasks}
    assert [t[f"t1_{i}"].duration_minutes for i in (1, 2, 3)] == [400, 400, 400]
    assert t["t1_1"].duration_estimate.model_dump() == {"optimistic_minutes": 320, "likely_minutes": 400,
                                                         "pessimistic_minutes": 480}
    assert b.duration_summary.model_dump() == {"tasks_with_range": 2, "expected_work_minutes": 10320,
                                               "optimistic_work_minutes": 9600, "pessimistic_work_minutes": 11040}
    assert b.problem.horizon_days == 64
    check_parts(d, b)
    doc = b.problem.model_dump(mode="json")
    for strategy in ("heuristic", "cpsat", "ga", "auto"):
        rec, run, sch = solve_and_check(client, doc, strategy=strategy, time_limit_seconds=3)
        by = {p["task_id"]: p for p in sch["placements"]}
        for tid, task in t.items():
            assert by[tid]["end"] - by[tid]["start"] == task.duration_minutes
        # milestone after the last testing part
        assert by["t5"]["start"] >= by["t4_4"]["end"]


def test_duration_risk_reported_on_schedule(client):
    d, b = built(SPEC_TEXT, SPEC_ANSWERS)
    _, _, sch = solve_and_check(client, b.problem.model_dump(mode="json"), strategy="heuristic")
    risk = sch["explanation"]["duration_risk"]
    assert risk["tasks_with_range"] == 2                     # 2 user tasks (split into 3 + 4 parts) have a range
    tasks = {x.id: x for x in b.problem.tasks}
    chain = risk["chain_task_ids"]
    assert chain and all(not tasks[i].type == "milestone" for i in chain)
    assert risk["chain_expected_minutes"] == sum(tasks[i].duration_minutes for i in chain)
    pes = sum((tasks[i].duration_estimate.pessimistic_minutes if tasks[i].duration_estimate
               else tasks[i].duration_minutes) for i in chain)
    assert risk["chain_pessimistic_minutes"] == pes
    assert risk["buffer_85_minutes"] == round(1.04 * risk["chain_sigma_minutes"])
    assert risk["message"] in " ".join(sch["explanation"]["summary"]) if isinstance(sch["explanation"]["summary"], list) \
        else risk["message"] in sch["explanation"]["summary"]


def test_duration_risk_chain_follows_split_parts_across_closed_time(client):
    """Parts of a split task are separated by nights/weekends; the critical chain must still run back through
    them (and through the FS chain t1 -> t2 -> t3 -> t4), otherwise the range warning only covers the last part."""
    d, b = built(SPEC_TEXT, SPEC_ANSWERS)
    _, _, sch = solve_and_check(client, b.problem.model_dump(mode="json"), strategy="heuristic")
    risk = sch["explanation"]["duration_risk"]
    assert set(b.parts["t4"]) <= set(risk["chain_task_ids"]), risk["chain_task_ids"]
    assert set(b.parts["t1"]) <= set(risk["chain_task_ids"]), risk["chain_task_ids"]
    # pessimistic - expected over the chain = (1440 - 1200) + (2400 - 1920) = 720 min
    assert risk["chain_pessimistic_minutes"] - risk["chain_expected_minutes"] == 720, risk


def test_duration_risk_treats_parts_of_one_estimate_as_one_uncertainty(client):
    """A task split into parts has ONE uncertain duration; its sigma is (p - o) / 6 of the whole task, not
    sqrt(n) times smaller. With the spec example on the critical chain: t1 (960..1440) and t4 (1440..2400)
    give sigma = sqrt(80^2 + 160^2) = 178.9 min, buffer = round(1.04 * 178.9) = 186 min."""
    d, b = built(SPEC_TEXT, SPEC_ANSWERS)
    _, _, sch = solve_and_check(client, b.problem.model_dump(mode="json"), strategy="heuristic")
    risk = sch["explanation"]["duration_risk"]
    whole = math.sqrt(((1440 - 960) / 6) ** 2 + ((2400 - 1440) / 6) ** 2)
    assert set(b.parts["t1"] + b.parts["t4"]) <= set(risk["chain_task_ids"])
    assert abs(risk["chain_sigma_minutes"] - whole) < 1.0, (risk["chain_sigma_minutes"], whole)


def test_mixed_three_point_ranges_build_and_solve(client):
    d, b = built(RANGE_TEXT)
    durs = {t.name: (t.duration.optimistic, t.duration.likely, t.duration.pessimistic) for t in d.tasks
            if t.duration}
    assert durs["Strip out"] == (1, 2, 3) and durs["Wiring"] == (2, 4, 7)
    assert durs["Plastering"] == (1, 2, 4) and durs["Painting"] == (2, 3, 5)
    check_parts(d, b)
    assert b.duration_summary.tasks_with_range == 4
    exp = sum(t.duration_minutes for t in b.problem.tasks)
    # whole-task PERT vs the sum of per-part PERT values may differ by rounding (<= 1 min per part)
    assert abs(b.duration_summary.expected_work_minutes - exp) <= len(b.problem.tasks)
    solve_and_check(client, b.problem.model_dump(mode="json"), strategy="auto")


def test_study_blueprint_solves_inside_study_windows(client):
    d, b = built(STUDY_TEXT, kind="study")
    assert b.problem.domain == "exam_prep"
    # every part fits the shortest study window (3 h weekday evenings)
    assert max(t.duration_minutes for t in b.problem.tasks) <= 180
    _, _, sch = solve_and_check(client, b.problem.model_dump(mode="json"), strategy="heuristic",
                                time_limit_seconds=5)
    exam = next(t for t in b.problem.tasks if t.type == "milestone")
    by = {p["task_id"]: p for p in sch["placements"]}
    assert all(by[t.id]["end"] <= by[exam.id]["start"] for t in b.problem.tasks if t.id != exam.id
               and any(dp.successor == exam.id for dp in b.problem.dependencies if dp.predecessor == t.id))


def test_production_counted_machines_solve(client):
    d, b = built("Two machines run two shifts. 3 orders, each goes through cutting, welding and painting. "
                 "Cutting 3 hours, welding 2 hours, painting 4 hours.", kind="production")
    assert b.problem.domain == "manufacturing"
    machines = [r for r in b.problem.resources if r.kind == "machine"]
    assert len(machines) == 2
    solve_and_check(client, b.problem.model_dump(mode="json"), strategy="auto")


def test_replan_of_intake_plan_drops_estimate_and_new_schedule_is_valid(client):
    _, b = built(SPEC_TEXT, SPEC_ANSWERS)
    rec, run, sch = solve_and_check(client, b.problem.model_dump(mode="json"), strategy="heuristic")
    hs = datetime.fromisoformat(rec["problem"]["horizon_start"])
    r = client.post(f"{API}/schedules/{sch['id']}/replan", json={
        "cutoff": (hs + timedelta(days=1)).isoformat(),
        "changes": {"task_updates": [{"id": "t1_3", "duration_minutes": 450}]},
        "run": {"strategy": "heuristic", "time_limit_seconds": 3}})
    assert r.status_code == 202, r.text
    cur = client.get(f"{API}/problems/{rec['id']}").json()
    t = next(x for x in cur["problem"]["tasks"] if x["id"] == "t1_3")
    assert t["duration_minutes"] == 450 and "duration_estimate" not in t
    done = wait_run(client, r.json()["run_id"])
    assert done["status"] == "completed" and done["feasibility"] == "feasible", done
    new = client.get(f"{API}/schedules/{done['primary_schedule_id']}").json()
    pls = [{k: p[k] for k in ("task_id", "start", "end", "resource_ids")} for p in new["placements"]]
    assert sched_checker().independent_check(cur["problem"], pls, new["horizon_start"]) == []


def test_put_with_wrong_expected_duration_is_rejected(client):
    _, b = built(SPEC_TEXT, SPEC_ANSWERS)
    r = client.post(f"{API}/problems", json=b.problem.model_dump(mode="json"))
    assert r.status_code == 201
    rec = r.json()
    doc = rec["problem"]
    next(x for x in doc["tasks"] if x["id"] == "t1_1")["duration_minutes"] = 401
    r = client.put(f"{API}/problems/{rec['id']}", json=doc, headers={"If-Match": f'"{rec["version"]}"'})
    assert r.status_code == 422, r.text
    assert "expected value of duration_estimate" in r.text


@pytest.mark.parametrize("n_tasks,days", [(1, 6000), (300, 20)])
def test_build_with_many_split_parts_never_returns_500(client, n_tasks, days):
    """A valid draft (DraftDuration <= 10000, <= 500 tasks) whose split parts exceed the document task limit
    must come back as a normal build result or 422, never as 500 INTERNAL_ERROR."""
    draft = {"tasks": [{"key": f"t{i}", "name": f"Task {i}",
                        "duration": {"optimistic": days, "likely": days, "pessimistic": days, "unit": "days"}}
                       for i in range(1, n_tasks + 1)]}
    r = client.post(f"{IN}/schedule/build", json={"draft": draft, "context": CTX_JSON})
    assert r.status_code in (200, 422), r.text[:300]
    if r.status_code == 200:
        assert r.json()["ready"] is False
