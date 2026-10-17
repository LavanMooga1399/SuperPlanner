"""PHASE2 2.14 engine edits: PERT, DurationEstimate, Task rule, DurationRisk, replan write path, compatibility."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from intake_helpers import API, CTX, EXAMPLE_ANSWERS, SCHEDULE_TEXT
from superplanner import engine, intake
from superplanner.engine import DurationEstimate, Placement, Problem, Task, pert_minutes
from superplanner.engine.compiled import build_compiled
from superplanner.engine.explain import explain, fmt_work
from superplanner.templates import get_template

HS = datetime(2026, 10, 19, tzinfo=timezone.utc)


def est(o, m, p):
    return {"optimistic_minutes": o, "likely_minutes": m, "pessimistic_minutes": p}


@pytest.mark.parametrize("o,m,p,e", [(1, 1, 1, 1), (320, 400, 480, 400), (360, 480, 600, 480), (60, 90, 180, 100),
                                     (1, 2, 4, 2), (10, 10, 13, 11), (1, 1, 2, 1), (2, 2, 3, 2)])
def test_pert_minutes_half_up(o, m, p, e):
    assert pert_minutes(o, m, p) == e
    assert pert_minutes(o, m, p) == math.floor((o + 4 * m + p) / 6 + 0.5)


def test_duration_estimate_validation():
    assert DurationEstimate(**est(1, 2, 3)).expected_minutes == 2
    for bad in (est(3, 2, 4), est(1, 5, 4), est(0, 1, 2)):
        with pytest.raises(ValidationError):
            DurationEstimate(**bad)


def test_task_rule_and_milestone():
    Task(id="a", name="A", duration_minutes=100, duration_estimate=est(60, 90, 180))
    with pytest.raises(ValidationError, match="duration_minutes must be 100, the expected value of duration_estimate"):
        Task(id="a", name="A", duration_minutes=90, duration_estimate=est(60, 90, 180))
    with pytest.raises(ValidationError, match="milestone must not have duration_estimate"):
        Task(id="m", name="M", type="milestone", duration_minutes=0, duration_estimate=est(1, 1, 1))


def test_documents_without_estimate_serialise_unchanged():
    t = Task(id="a", name="A", duration_minutes=30)
    assert "duration_estimate" not in t.model_dump(mode="json")
    assert "duration_estimate" not in t.model_dump_json()
    for tid in ("manufacturing", "project", "exam_prep"):
        tpl = get_template(tid)
        p = tpl.build(name="x", start_date=HS.date(), utc_offset="+00:00", params={})
        doc = p.model_dump(mode="json")
        again = Problem.model_validate(json.loads(json.dumps(doc))).model_dump(mode="json")
        assert again == doc
        assert all("duration_estimate" not in t for t in doc["tasks"])
        assert engine.explain_schedule(p, []).model_dump(mode="json").get("duration_risk", "absent") == "absent"


def test_estimate_round_trip_and_compiled():
    p = Problem(name="x", horizon_start=HS, tasks=[Task(id="a", name="A", duration_minutes=100,
                                                        duration_estimate=est(60, 90, 180))])
    doc = p.model_dump(mode="json")
    assert doc["tasks"][0]["duration_estimate"] == est(60, 90, 180)
    assert Problem.model_validate(doc) == p
    c = build_compiled(p)
    assert c.tasks[0].estimate == (60, 90, 180) and c.tasks[0].duration == 100


def test_duration_risk_numbers_and_summary():
    tasks = [Task(id="a", name="Alpha", duration_minutes=pert_minutes(360, 480, 720), duration_estimate=est(360, 480, 720)),
             Task(id="b", name="Beta", duration_minutes=240),
             Task(id="c", name="Gamma", duration_minutes=pert_minutes(60, 120, 300), duration_estimate=est(60, 120, 300))]
    p = Problem(name="x", horizon_start=HS, tasks=tasks,
                dependencies=[{"predecessor": "a", "successor": "b"}, {"predecessor": "b", "successor": "c"}])
    ea, ec = tasks[0].duration_minutes, tasks[2].duration_minutes
    pl = [Placement(task_id="a", start=0, end=ea), Placement(task_id="b", start=ea, end=ea + 240),
          Placement(task_id="c", start=ea + 240, end=ea + 240 + ec)]
    ex = explain(build_compiled(p), pl)
    r = ex.duration_risk
    assert r is not None
    assert r.tasks_with_range == 2 and r.chain_task_ids == ["a", "b", "c"]
    assert r.chain_expected_minutes == ea + 240 + ec
    assert r.chain_optimistic_minutes == 360 + 240 + 60
    assert r.chain_pessimistic_minutes == 720 + 240 + 300
    sigma = math.sqrt(((720 - 360) / 6) ** 2 + ((300 - 60) / 6) ** 2)
    assert r.chain_sigma_minutes == pytest.approx(sigma, abs=1e-3)
    assert r.buffer_85_minutes == round(1.04 * sigma)
    extra = r.chain_pessimistic_minutes - r.chain_expected_minutes
    assert r.message == (f"2 tasks have a duration range; the plan uses the expected values. If the tasks on the "
                         f"critical chain take their longest estimates, the work runs about {fmt_work(extra)} longer; "
                         f"keeping about {fmt_work(r.buffer_85_minutes)} spare gives roughly an 85% chance of "
                         "finishing on time.")
    assert ex.summary[-1] == r.message
    assert ex.model_dump(mode="json")["duration_risk"]["tasks_with_range"] == 2


def test_fmt_work():
    assert fmt_work(0) == "0 min" and fmt_work(45) == "45 min" and fmt_work(120) == "2 h"
    assert fmt_work(480 + 120) == "1 d 2 h" and fmt_work(530) == "1 d 50 min"


def test_post_problem_with_wrong_pert_is_422_and_right_one_201(client):
    doc = {"name": "x", "horizon_start": "2026-10-19T00:00:00+00:00",
           "tasks": [{"id": "a", "name": "A", "duration_minutes": 90, "duration_estimate": est(60, 90, 180)}]}
    r = client.post(f"{API}/problems", json=doc)
    assert r.status_code == 422, r.text
    assert "duration_minutes must be 100" in r.text
    doc["tasks"][0]["duration_minutes"] = 100
    assert client.post(f"{API}/problems", json=doc).status_code == 201
    ms = {"name": "y", "horizon_start": "2026-10-19T00:00:00+00:00",
          "tasks": [{"id": "m", "name": "M", "type": "milestone", "duration_estimate": est(1, 1, 1)}]}
    assert client.post(f"{API}/problems", json=ms).status_code == 422


def _built_problem() -> dict:
    d = intake.describe_schedule(SCHEDULE_TEXT, CTX).draft
    d = intake.answer_schedule(d, [intake.Answer(**a) for a in EXAMPLE_ANSWERS], CTX).draft
    b = intake.build_schedule(d, CTX)
    assert b.ready
    return b.problem.model_dump(mode="json")


def test_replan_duration_update_drops_estimate(client):
    from api_helpers_shim import wait_run

    r = client.post(f"{API}/problems", json=_built_problem())
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    run = client.post(f"{API}/problems/{pid}/solver-runs", json={"strategy": "heuristic", "time_limit_seconds": 3})
    assert run.status_code == 202, run.text
    done = wait_run(client, run.json()["run_id"])
    assert done["status"] == "completed" and done["feasibility"] == "feasible"
    sch_id = done["primary_schedule_id"]
    sch = client.get(f"{API}/schedules/{sch_id}").json()
    hs = datetime.fromisoformat(r.json()["problem"]["horizon_start"])
    cutoff = (hs + timedelta(days=1)).isoformat()
    r2 = client.post(f"{API}/schedules/{sch['id']}/replan", json={
        "cutoff": cutoff, "changes": {"task_updates": [{"id": "t4_2", "duration_minutes": 420}]},
        "run": {"strategy": "heuristic", "time_limit_seconds": 3}})
    assert r2.status_code == 202, r2.text[:2000]
    cur = client.get(f"{API}/problems/{pid}").json()["problem"]
    t = next(x for x in cur["tasks"] if x["id"] == "t4_2")
    assert t["duration_minutes"] == 420 and "duration_estimate" not in t
    other = next(x for x in cur["tasks"] if x["id"] == "t4_1")
    assert other["duration_estimate"] == est(360, 480, 600)
    wait_run(client, r2.json()["run_id"])
