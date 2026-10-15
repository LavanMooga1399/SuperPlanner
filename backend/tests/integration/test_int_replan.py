"""Replan protection (criterion 4.4) on every template."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest

from int_helpers import API, TEMPLATE_IDS, assert_error, independent_check


def _cutoff(sch: dict) -> str:
    """A cutoff strictly inside the second-earliest placement, so at least one task is in progress."""
    ps = sorted(sch["placements"], key=lambda p: (p["start"], p["task_id"]))
    hs = datetime.fromisoformat(sch["horizon_start"])
    p = ps[min(1, len(ps) - 1)]
    m = p["start"] + max(1, (p["end"] - p["start"]) // 2)
    return (hs + timedelta(minutes=m)).isoformat()


@pytest.mark.parametrize("template", TEMPLATE_IDS)
def test_int_replan_protection(api, client, template):
    rec = api.instantiate(template)
    pid = rec["id"]
    run = api.solve(pid, strategy="auto", time_limit_seconds=3)
    src = api.schedule(run["primary_schedule_id"])
    assert api.approve(src["id"]).status_code == 200
    cutoff = _cutoff(src)
    cut = datetime.fromisoformat(cutoff)
    frozen = {p["task_id"]: p for p in src["placements"] if datetime.fromisoformat(p["start_at"]) < cut}
    others = [p for p in src["placements"] if p["task_id"] not in frozen]
    assert frozen and others
    tasks = {t["id"]: t for t in rec["problem"]["tasks"]}
    target = next(p["task_id"] for p in others if tasks[p["task_id"]]["type"] == "activity")
    r = client.post(f"{API}/schedules/{src['id']}/replan", json={
        "cutoff": cutoff,
        "changes": {"task_updates": [{"id": target, "duration_minutes": tasks[target]["duration_minutes"] + 20}]},
        "run": {"strategy": "auto", "time_limit_seconds": 3}, "expected_problem_version": 1})
    assert r.status_code == 202, r.text
    assert r.json()["problem_version"] == 2
    # until the replan candidate is approved, the approved schedule is unchanged
    assert api.schedule(src["id"]) == {**src, "status": "approved",
                                       "approved_at": api.schedule(src["id"])["approved_at"],
                                       "approved_problem_version": 1}
    new_run = api.wait(r.json()["run_id"])
    assert new_run["status"] == "completed" and new_run["feasibility"] == "feasible", new_run
    assert api.schedule(src["id"])["status"] == "approved"
    assert [s["id"] for s in api.schedules(pid, "approved")] == [src["id"]]
    for sid in new_run["schedule_ids"]:
        new = api.schedule(sid)
        assert new["status"] == "candidate" and new["source_schedule_id"] == src["id"]
        for p in new["placements"]:
            if p["task_id"] in frozen:
                assert p["start_at"] == frozen[p["task_id"]]["start_at"], (sid, p)
                assert p["resource_ids"] == frozen[p["task_id"]]["resource_ids"], (sid, p)
            else:
                assert datetime.fromisoformat(p["start_at"]) >= cut, (sid, p)
        cur = api.get(pid)["problem"]
        assert independent_check(cur, [{k: p[k] for k in ("task_id", "start", "end", "resource_ids")}
                                       for p in new["placements"]], new["horizon_start"]) == []
    cur = api.get(pid)
    assert cur["version"] == 2 and all(t["locked"] is None for t in cur["problem"]["tasks"])
    # earliest_start of non-frozen tasks must not have been written back either
    assert [t["earliest_start"] for t in cur["problem"]["tasks"]] == \
        [t["earliest_start"] for t in rec["problem"]["tasks"]]
    # approving the replan candidate supersedes the source
    r = api.approve(new_run["primary_schedule_id"])
    assert r.status_code == 200, r.text
    assert r.json()["superseded_schedule_id"] == src["id"]


def test_int_replan_resource_breakdown(api, client):
    rec = api.instantiate("manufacturing", jobs=4)
    pid = rec["id"]
    src = api.schedule(api.solve(pid, strategy="cpsat", time_limit_seconds=3)["primary_schedule_id"])
    cutoff = _cutoff(src)
    cut = datetime.fromisoformat(cutoff)
    # the breakdown starts once the work frozen at the cutoff (possibly on MILL1) has finished
    frozen_end = max(datetime.fromisoformat(p["end_at"]) for p in src["placements"]
                     if datetime.fromisoformat(p["start_at"]) < cut)
    cut = max(cut, frozen_end)
    end = (cut + timedelta(days=1)).isoformat()
    r = client.post(f"{API}/schedules/{src['id']}/replan", json={
        "cutoff": cutoff, "changes": {"resource_unavailable": [
            {"resource_id": "MILL1", "start": cut.isoformat(), "end": end, "reason": "Breakdown"}]},
        "run": {"strategy": "cpsat", "time_limit_seconds": 3}})
    assert r.status_code == 202, r.text
    run = api.wait(r.json()["run_id"])
    assert run["feasibility"] == "feasible", run
    new = api.schedule(run["primary_schedule_id"])
    for p in new["placements"]:
        if "MILL1" in p["resource_ids"] and datetime.fromisoformat(p["start_at"]) >= cut:
            s, e = datetime.fromisoformat(p["start_at"]), datetime.fromisoformat(p["end_at"])
            assert e <= cut or s >= datetime.fromisoformat(end), p
    cur = api.get(pid)
    blocked = next(x for x in cur["problem"]["resources"] if x["id"] == "MILL1")["calendar"]["blocked"]
    assert blocked[-1]["reason"] == "Breakdown" and cur["version"] == 2


def test_int_replan_guards(api, client):
    rec = api.instantiate("manufacturing", jobs=2)
    pid = rec["id"]
    src = api.schedule(api.solve(pid, strategy="heuristic", time_limit_seconds=1)["primary_schedule_id"])
    cutoff = _cutoff(src)
    # stale expected version -> 412, nothing changes
    r = client.post(f"{API}/schedules/{src['id']}/replan", json={
        "cutoff": cutoff, "changes": {"task_updates": [{"id": "J1-1", "duration_minutes": 10}]},
        "expected_problem_version": 7})
    err = assert_error(r, 412, "VERSION_MISMATCH")
    assert err["details"]["current_version"] == 1
    assert api.get(pid)["version"] == 1
    # cutoff outside the horizon -> 422 and nothing changes
    r = client.post(f"{API}/schedules/{src['id']}/replan", json={
        "cutoff": "2030-01-01T00:00:00+05:30", "changes": {"task_updates": [{"id": "J1-1", "duration_minutes": 10}]}})
    assert r.status_code == 422, r.text
    assert api.get(pid)["version"] == 1
    # locked is not accepted in task_updates
    r = client.post(f"{API}/schedules/{src['id']}/replan", json={
        "cutoff": cutoff, "changes": {"task_updates": [{"id": "J1-1", "locked": {"start": cutoff}}]}})
    assert_error(r, 422, "VALIDATION_ERROR")
    # empty changes do not bump the version
    r = client.post(f"{API}/schedules/{src['id']}/replan", json={"cutoff": cutoff, "run": {"time_limit_seconds": 1}})
    assert r.status_code == 202 and r.json()["problem_version"] == 1
    # a second replan while that run is active -> 409, and the change is rolled back
    r2 = client.post(f"{API}/schedules/{src['id']}/replan", json={
        "cutoff": cutoff, "changes": {"task_updates": [{"id": "J1-1", "duration_minutes": 10}]}})
    if r2.status_code == 409:
        assert r2.json()["error"]["code"] == "RUN_ALREADY_ACTIVE"
        assert api.get(pid)["version"] == 1
    api.wait(r.json()["run_id"])
    # unknown schedule -> 404
    assert_error(client.post(f"{API}/schedules/sch_nope/replan", json={"cutoff": cutoff}), 404)


def test_int_replan_preflight_error_rolls_back(api, client):
    rec = api.instantiate("manufacturing", jobs=2)
    pid = rec["id"]
    src = api.schedule(api.solve(pid, strategy="heuristic", time_limit_seconds=1)["primary_schedule_id"])
    # make a task impossible: duration longer than the horizon
    r = client.post(f"{API}/schedules/{src['id']}/replan", json={
        "cutoff": _cutoff(src),
        "changes": {"task_updates": [{"id": "J2-3", "duration_minutes": rec["problem"]["horizon_days"] * 1440 + 10}]}})
    assert_error(r, 422, "PREFLIGHT_FAILED")
    cur = api.get(pid)
    assert cur["version"] == 1
    assert cur["problem"] == rec["problem"]
