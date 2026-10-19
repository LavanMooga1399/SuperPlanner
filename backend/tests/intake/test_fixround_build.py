"""Fix round: build horizon covers chains and resource load; oversized drafts never raise (PHASE2 2.9.1)."""

from __future__ import annotations

from datetime import date

import pytest

from api_helpers_shim import wait_run
from intake_helpers import API, CTX
from superplanner import intake
from superplanner.intake.models import (Answer, DraftDuration, DraftResource, DraftTask, ScheduleDraft, TimeWindow,
                                        WorkingTime)

WT = WorkingTime(days=["mon", "tue", "wed", "thu", "fri"], windows=[TimeWindow(start="09:00", end="17:00")])
RELAUNCH = ("Website relaunch starting next Monday. Ravi, Priya, Arjun and Meena are on the team.\n"
            "1. Gather requirements - 2-3 days\n2. Design 1 week\n3. Build the site: 3 weeks\n"
            "4. Testing 3-5 days\n5. Launch")


def answer_defaults(d: ScheduleDraft) -> ScheduleDraft:
    for _ in range(20):
        qs = intake.answer_schedule(d, [], CTX).questions
        if not qs:
            break
        d = intake.answer_schedule(d, [Answer(question_id=q.id, use_default=True) for q in qs if q.default is not None
                                       or not q.required], CTX).draft
    return d


def solve(client, problem) -> dict:
    r = client.post(f"{API}/problems", json=problem.model_dump(mode="json"))
    assert r.status_code == 201, r.text
    run = client.post(f"{API}/problems/{r.json()['id']}/solver-runs", json={"time_limit_seconds": 10})
    assert run.status_code == 202, run.text
    return wait_run(client, run.json()["run_id"], timeout=120)


def three_day(n: int, chained: bool, people: int, assign_one: bool = False) -> ScheduleDraft:
    res = [DraftResource(key=f"r{i}", name=f"P{i}", kind="person", count=1) for i in range(people)]
    tasks = [DraftTask(key=f"t{i}", name=f"Task {i}", duration=DraftDuration(optimistic=3, likely=3, pessimistic=3,
                                                                           unit="days"),
                       after=[f"t{i - 1}"] if chained and i else [], resources=["r0"] if assign_one else [])
             for i in range(n)]
    return ScheduleDraft(kind="generic", name="T", start_date=date(2026, 10, 19), working_time=WT, tasks=tasks,
                         resources=res)


def test_numbered_list_with_four_people_solves_feasible(client):
    d = answer_defaults(intake.describe_schedule(RELAUNCH, CTX).draft)
    b = intake.build_schedule(d, CTX)
    assert b.ready, b.report
    lb = b.report.cpm.lower_bound_makespan_minutes
    assert b.problem.horizon_days * 5 / 7 * 480 >= lb   # horizon covers the chain in working time
    done = solve(client, b.problem)
    assert done["status"] == "completed" and done["feasibility"] == "feasible", done


@pytest.mark.parametrize("chained,assign_one", [(True, False), (False, True)])
def test_chain_or_single_resource_load_sets_horizon(client, chained, assign_one):
    b = intake.build_schedule(three_day(20, chained, 10, assign_one), CTX)
    assert b.ready, b.report
    assert b.problem.horizon_days >= 84
    done = solve(client, b.problem)
    assert done["status"] == "completed" and done["feasibility"] == "feasible", done


def test_user_horizon_too_short_for_chain_is_not_ready():
    d = three_day(20, True, 10).model_copy(update={"horizon_days": 20})
    b = intake.build_schedule(d, CTX)
    assert not b.ready
    assert any(i.code == "HORIZON_TOO_SHORT" and i.severity == "error" for i in b.report.issues)


@pytest.mark.parametrize("n,days", [(1, 6000), (300, 20), (1, 10000)])
def test_oversized_split_draft_is_a_plain_issue(n, days):
    d = ScheduleDraft(kind="generic", name="T", start_date=date(2026, 10, 19), working_time=WT, tasks=[
        DraftTask(key=f"t{i}", name=f"T{i}", duration=DraftDuration(optimistic=days, likely=days, pessimistic=days,
                                                                    unit="days")) for i in range(n)])
    b = intake.build_schedule(d, CTX)
    assert b.ready is False and b.problem is None
    assert [i.code for i in b.report.issues] == ["DRAFT_TOO_LARGE"]


def test_oversized_build_endpoint_200(client):
    draft = {"tasks": [{"key": "t1", "name": "Long", "duration": {"optimistic": 6000, "likely": 6000,
                                                                   "pessimistic": 6000, "unit": "days"}}]}
    r = client.post(f"{API}/intake/schedule/build", json={"draft": draft, "context": CTX.model_dump(mode="json")})
    assert r.status_code == 200, r.text[:300]
    assert r.json()["ready"] is False
