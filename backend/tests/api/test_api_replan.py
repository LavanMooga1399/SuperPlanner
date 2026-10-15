"""Replan (A.14.6; criterion 2.16) and the full API journey."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from api_helpers import API, assert_error


def _setup(api, client, jobs=3):
    rec = api.instantiate(jobs=jobs)
    run = api.solve(rec["id"], strategy="cpsat", time_limit_seconds=2)
    sch = api.schedule(run["primary_schedule_id"])
    return rec, run, sch


def _cutoff_after_first(sch) -> str:
    first = min(sch["placements"], key=lambda p: (p["start"], p["task_id"]))
    return first["end_at"]


def test_api_replan_freezes_started_work(api, client):
    rec, run, src = _setup(api, client)
    pid = rec["id"]
    cutoff = _cutoff_after_first(src)
    cut = datetime.fromisoformat(cutoff)
    frozen = {p["task_id"]: p for p in src["placements"] if datetime.fromisoformat(p["start_at"]) < cut}
    assert frozen and len(frozen) < len(src["placements"])
    target = next(t for t in rec["problem"]["tasks"] if t["id"] not in frozen)
    r = client.post(f"{API}/schedules/{src['id']}/replan", json={
        "cutoff": cutoff,
        "changes": {"task_updates": [{"id": target["id"], "duration_minutes": target["duration_minutes"] + 30}]},
        "run": {"strategy": "cpsat", "time_limit_seconds": 2},
        "expected_problem_version": 1})
    assert r.status_code == 202, r.text
    body = r.json()
    assert set(body) == {"run_id", "status", "problem_version_id", "status_url", "events_url",
                         "source_schedule_id", "problem_version"}
    assert body["source_schedule_id"] == src["id"] and body["problem_version"] == 2 and body["status"] == "queued"
    new_run = api.wait(body["run_id"])
    assert new_run["status"] == "completed" and new_run["source_schedule_id"] == src["id"]
    assert new_run["feasibility"] == "feasible"
    new = api.schedule(new_run["primary_schedule_id"])
    assert new["label"] == "Replan" and new["source_schedule_id"] == src["id"] and new["status"] == "candidate"
    assert new["base_problem_version"] == 2
    for p in new["placements"]:
        if p["task_id"] in frozen:
            assert p["start_at"] == frozen[p["task_id"]]["start_at"]
            assert p["resource_ids"] == frozen[p["task_id"]]["resource_ids"]
        else:
            assert datetime.fromisoformat(p["start_at"]) >= cut, p
    changed = next(p for p in new["placements"] if p["task_id"] == target["id"])
    assert changed["end"] - changed["start"] == target["duration_minutes"] + 30
    # the editable document got the change but no replan locks
    cur = client.get(f"{API}/problems/{pid}").json()
    assert cur["version"] == 2
    assert all(t["locked"] is None for t in cur["problem"]["tasks"])
    assert next(t for t in cur["problem"]["tasks"] if t["id"] == target["id"])["duration_minutes"] == \
        target["duration_minutes"] + 30
    assert all(t["earliest_start"] == o["earliest_start"]
               for t, o in zip(cur["problem"]["tasks"], rec["problem"]["tasks"]))
    # the derived snapshot is a separate, replan-kind version
    from superplanner.api.db import ProblemVersionRow
    with client.app.state.ctx.db.read() as s:
        pv = s.get(ProblemVersionRow, body["problem_version_id"])
        assert pv.kind == "replan" and pv.base_version == 2
        assert {t["id"] for t in pv.document["tasks"] if t["locked"]} == set(frozen)


def test_api_replan_without_changes_keeps_version(api, client):
    rec, run, src = _setup(api, client, jobs=2)
    r = client.post(f"{API}/schedules/{src['id']}/replan",
                    json={"cutoff": _cutoff_after_first(src), "run": {"strategy": "heuristic",
                                                                      "time_limit_seconds": 1}})
    assert r.status_code == 202, r.text
    assert r.json()["problem_version"] == 1
    api.wait(r.json()["run_id"])
    assert client.get(f"{API}/problems/{rec['id']}").json()["version"] == 1


def test_api_replan_errors_roll_back(api, client):
    rec, run, src = _setup(api, client, jobs=2)
    pid = rec["id"]
    sid = src["id"]
    change = {"task_updates": [{"id": rec["problem"]["tasks"][0]["id"], "duration_minutes": 999}]}
    cutoff = _cutoff_after_first(src)
    # stale expected version -> 412, nothing changes
    err = assert_error(client.post(f"{API}/schedules/{sid}/replan",
                                   json={"cutoff": cutoff, "changes": change, "expected_problem_version": 9}),
                       412, "VERSION_MISMATCH")
    assert err["details"]["current_version"] == 1
    # cutoff outside the horizon -> 422
    assert_error(client.post(f"{API}/schedules/{sid}/replan",
                             json={"cutoff": "2030-01-01T00:00:00+00:00", "changes": change}), 422)
    # changes that break preflight -> 422 PREFLIGHT_FAILED and step 1 is rolled back too
    t0, t1 = rec["problem"]["tasks"][0]["id"], rec["problem"]["tasks"][1]["id"]
    bad = {"task_updates": [{"id": t0, "requirements": [{"alternatives": ["NOPE"]}]}]}
    assert_error(client.post(f"{API}/schedules/{sid}/replan", json={"cutoff": cutoff, "changes": bad}),
                 422, "PREFLIGHT_FAILED")
    # unknown task / locked not accepted / naive datetime
    assert_error(client.post(f"{API}/schedules/{sid}/replan",
                             json={"cutoff": cutoff, "changes": {"task_updates": [{"id": "ghost"}]}}), 422)
    assert_error(client.post(f"{API}/schedules/{sid}/replan",
                             json={"cutoff": cutoff, "changes": {"task_updates": [
                                 {"id": t1, "locked": {"start": cutoff}}]}}), 422, "VALIDATION_ERROR")
    assert_error(client.post(f"{API}/schedules/{sid}/replan", json={"cutoff": "2026-10-19T10:00:00"}), 422)
    assert_error(client.post(f"{API}/schedules/sch_missing/replan", json={"cutoff": cutoff}), 404)
    cur = client.get(f"{API}/problems/{pid}").json()
    assert cur["version"] == 1 and cur["problem"] == rec["problem"]
    assert len(client.get(f"{API}/problems/{pid}/solver-runs").json()["items"]) == 1


def test_api_replan_resource_unavailable_and_add_remove(api, client):
    rec, run, src = _setup(api, client, jobs=2)
    cutoff = _cutoff_after_first(src)
    tasks = rec["problem"]["tasks"]
    last = max(src["placements"], key=lambda p: p["start"])
    new_task = {"id": "EXTRA", "name": "Extra inspection", "duration_minutes": 30,
                "requirements": [{"alternatives": ["ASM1"]}]}
    r = client.post(f"{API}/schedules/{src['id']}/replan", json={
        "cutoff": cutoff,
        "changes": {"add_tasks": [new_task], "remove_task_ids": [last["task_id"]],
                    "resource_unavailable": [{"resource_id": "MILL2", "start": cutoff,
                                              "end": "2026-10-21T06:00:00+05:30", "reason": "Breakdown"}]},
        "run": {"strategy": "heuristic", "time_limit_seconds": 1}})
    assert r.status_code == 202, r.text
    run2 = api.wait(r.json()["run_id"])
    assert run2["status"] == "completed"
    cur = client.get(f"{API}/problems/{rec['id']}").json()["problem"]
    ids = [t["id"] for t in cur["tasks"]]
    assert "EXTRA" in ids and last["task_id"] not in ids and len(ids) == len(tasks)
    assert all(last["task_id"] not in (d["predecessor"], d["successor"]) for d in cur["dependencies"])
    mill2 = next(x for x in cur["resources"] if x["id"] == "MILL2")
    assert mill2["calendar"]["blocked"][-1]["reason"] == "Breakdown"
    assert_error(client.post(f"{API}/schedules/{src['id']}/replan", json={
        "cutoff": cutoff, "changes": {"resource_unavailable": [{"resource_id": "GHOST", "start": cutoff,
                                                                 "end": cutoff}]}}), 422)


def test_api_replan_run_already_active(api, client):
    rec, run, src = _setup(api, client, jobs=2)
    busy = api.start_run(rec["id"], strategy="ga", time_limit_seconds=20,
                         ga={"max_generations": 10000, "stagnation_generations": 1000})
    assert_error(client.post(f"{API}/schedules/{src['id']}/replan", json={"cutoff": _cutoff_after_first(src)}),
                 409, "RUN_ALREADY_ACTIVE")
    client.post(f"{API}/solver-runs/{busy['run_id']}/cancel")
    api.wait(busy["run_id"])


def test_api_full_flow(api, client):
    """instantiate -> validate -> run cpsat and ga -> poll -> schedules -> compare -> approve -> replan."""
    rec = api.instantiate(jobs=4)
    pid = rec["id"]
    v = client.post(f"{API}/problems/{pid}/validate").json()
    assert v["ok"] is True and v["cpm"]["lower_bound_makespan_minutes"] > 0

    cp_run = api.solve(pid, strategy="cpsat", time_limit_seconds=3)
    ga_run = api.solve(pid, strategy="ga", time_limit_seconds=3)
    assert cp_run["selection"]["used"] == ["heuristic", "cpsat"]
    assert ga_run["selection"]["used"] == ["heuristic", "ga"]
    assert cp_run["feasibility"] == ga_run["feasibility"] == "feasible"

    items = client.get(f"{API}/problems/{pid}/schedules").json()["items"]
    assert {cp_run["primary_schedule_id"], ga_run["primary_schedule_id"]} <= {s["id"] for s in items}
    a, b = cp_run["primary_schedule_id"], ga_run["primary_schedule_id"]
    cmp_ = client.get(f"{API}/schedules/compare?a={a}&b={b}").json()
    assert cmp_["a"]["id"] == a and cmp_["b"]["id"] == b

    appr = client.post(f"{API}/schedules/{a}/approve", json={"note": "go"})
    assert appr.status_code == 200 and appr.json()["schedule"]["status"] == "approved"

    src = api.schedule(a)
    cutoff = _cutoff_after_first(src)
    task = src["placements"][-1]["task_id"]
    rp = client.post(f"{API}/schedules/{a}/replan", json={
        "cutoff": cutoff, "changes": {"task_updates": [{"id": task, "priority": 10}]},
        "run": {"strategy": "auto", "time_limit_seconds": 2}, "expected_problem_version": 1})
    assert rp.status_code == 202, rp.text
    rp_run = api.wait(rp.json()["run_id"])
    assert rp_run["status"] == "completed" and rp_run["feasibility"] == "feasible"
    new_id = rp_run["primary_schedule_id"]
    # the approved schedule is untouched until the new candidate is approved
    assert api.schedule(a)["status"] == "approved"
    cmp2 = client.get(f"{API}/schedules/compare?a={a}&b={new_id}").json()
    assert cmp2["b"]["source_schedule_id"] == a
    appr2 = client.post(f"{API}/schedules/{new_id}/approve", json={})
    assert appr2.status_code == 200 and appr2.json()["superseded_schedule_id"] == a
    assert appr2.json()["schedule"]["approved_problem_version"] == 2
    rows = list(csv.DictReader(io.StringIO(client.get(f"{API}/schedules/{new_id}/export.csv").text)))
    assert len(rows) == len(rec["problem"]["tasks"])
    summ = client.get(f"{API}/problems").json()["items"][0]
    assert summ["approved_schedule_id"] == new_id and summ["version"] == 2
    assert summ["latest_run"]["id"] == rp_run["id"]
