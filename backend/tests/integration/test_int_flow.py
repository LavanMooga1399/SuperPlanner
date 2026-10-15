"""End-to-end API flows (criteria 4.2, 4.3 over HTTP) and edge cases.

Every schedule returned by the API is re-checked with `engine.validate_schedule` and with the
independent checker of int_helpers.
"""

from __future__ import annotations

import copy
import csv
import io
import time
from datetime import datetime, timedelta

import pytest

from int_helpers import (API, STRATEGIES, TEMPLATE_IDS, assert_error, independent_check, load_export,
                         objective_check, parse_sse)
from superplanner import engine
from superplanner.engine import Placement, Problem

CSV_HEADER = ("task_id,task_name,group,type,start,end,duration_minutes,resource_ids,resource_names,deadline,"
              "deadline_hard,lateness_minutes,on_critical_chain").split(",")


def recheck(doc: dict, sch: dict) -> None:
    """Independent re-validation of a feasible stored schedule against the document it was made for."""
    pls = [{k: p[k] for k in ("task_id", "start", "end", "resource_ids")} for p in sch["placements"]]
    rep = engine.validate_schedule(Problem.model_validate(doc), [Placement(**p) for p in pls])
    assert rep.feasibility == "feasible", rep.violations
    assert independent_check(doc, pls, sch["horizon_start"]) == []
    assert objective_check(doc, pls, sch["metrics"], sch["horizon_start"]) == []
    assert sch["hard_violation_count"] == 0
    assert len(pls) == len(doc["tasks"])
    hs = datetime.fromisoformat(sch["horizon_start"])
    for p in sch["placements"]:
        assert datetime.fromisoformat(p["start_at"]) == hs + timedelta(minutes=p["start"])
        assert datetime.fromisoformat(p["end_at"]) == hs + timedelta(minutes=p["end"])
        assert p["start_at"].endswith(doc["horizon_start"][-6:])


def read_sse(client, run_id: str, headers: dict | None = None, timeout: float = 40) -> list[dict]:
    t0 = time.monotonic()
    with client.stream("GET", f"{API}/solver-runs/{run_id}/events", headers=headers or {}) as r:
        assert r.status_code == 200, r.read()
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(chunk for chunk in r.iter_text())
    assert time.monotonic() - t0 < timeout
    return parse_sse(body)


# --------------------------------------------------------------------------- 4.2 full journey

def test_int_full_journey(api, client):
    # instantiate -> validate
    rec = api.instantiate("manufacturing", jobs=4)
    pid = rec["id"]
    assert rec["problem"]["id"] == pid and rec["version"] == 1 and rec["template_id"] == "manufacturing"
    val = api.validate(pid)
    assert val["ok"] is True and val["problem_version"] == 1 and val["cpm"]["lower_bound_makespan_minutes"] > 0
    # create run -> read SSE to the terminal event
    created = api.start_run(pid, strategy="auto", time_limit_seconds=3)
    assert created["status"] == "queued"
    assert created["status_url"] == f"/api/v1/solver-runs/{created['run_id']}"
    assert created["events_url"] == f"/api/v1/solver-runs/{created['run_id']}/events"
    frames = read_sse(client, created["run_id"])
    types = [f["event"] for f in frames]
    assert types[0] == "run_queued" and types[-1] == "run_completed", types
    assert "run_started" in types and "phase_started" in types and "phase_completed" in types
    assert [int(f["id"]) for f in frames] == list(range(1, len(frames) + 1))
    for f in frames:
        assert f["data"]["seq"] == int(f["id"]) and f["data"]["type"] == f["event"]
        assert f["data"]["run_id"] == created["run_id"] and f["data"]["ts"].endswith("Z")
    term = frames[-1]["data"]
    assert term["feasibility"] == "feasible" and term["primary_schedule_id"]
    # replay after a cursor
    replay = read_sse(client, created["run_id"], headers={"Last-Event-ID": "3"})
    assert [int(f["id"]) for f in replay] == list(range(4, len(frames) + 1))
    r = client.get(f"{API}/solver-runs/{created['run_id']}/events",
                   headers={"Last-Event-ID": str(len(frames))})
    assert r.status_code == 204
    # schedule -> approve
    run = api.run(created["run_id"])
    assert run["status"] == "completed" and run["primary_schedule_id"] == term["primary_schedule_id"]
    assert run["request"]["strategy"] == "auto" and run["request"]["ga"]["max_generations"] == 300
    sch = api.schedule(run["primary_schedule_id"])
    assert sch["status"] == "candidate" and sch["label"] == "Recommended" and sch["base_problem_version"] == 1
    recheck(rec["problem"], sch)
    r = api.approve(sch["id"], note="go")
    assert r.status_code == 200, r.text
    assert r.json()["superseded_schedule_id"] is None and r.json()["schedule"]["status"] == "approved"
    # replan with a duration change and cutoff
    first = min(sch["placements"], key=lambda p: (p["start"], p["task_id"]))
    cutoff = first["end_at"]
    target = max(sch["placements"], key=lambda p: p["start"])["task_id"]
    dur = next(t for t in rec["problem"]["tasks"] if t["id"] == target)["duration_minutes"]
    r = client.post(f"{API}/schedules/{sch['id']}/replan", json={
        "cutoff": cutoff, "changes": {"task_updates": [{"id": target, "duration_minutes": dur + 45}]},
        "run": {"strategy": "cpsat", "time_limit_seconds": 3}, "expected_problem_version": 1})
    assert r.status_code == 202, r.text
    rp = r.json()
    assert rp["problem_version"] == 2 and rp["source_schedule_id"] == sch["id"]
    run2 = api.wait(rp["run_id"])
    assert run2["status"] == "completed" and run2["feasibility"] == "feasible"
    new = api.schedule(run2["primary_schedule_id"])
    assert new["label"] == "Replan" and new["status"] == "candidate" and new["base_problem_version"] == 2
    assert next(p for p in new["placements"] if p["task_id"] == target)["end"] - \
        next(p for p in new["placements"] if p["task_id"] == target)["start"] == dur + 45
    cur = api.get(pid)
    recheck(cur["problem"], new)
    # old approved schedule untouched until the new one is approved
    assert api.schedule(sch["id"])["status"] == "approved"
    # compare old vs new
    r = client.get(f"{API}/schedules/compare", params={"a": sch["id"], "b": new["id"]})
    assert r.status_code == 200, r.text
    cmp = r.json()
    assert cmp["a"]["id"] == sch["id"] and cmp["b"]["id"] == new["id"]
    assert cmp["metric_deltas"]["makespan_minutes"] == new["metrics"]["makespan_minutes"] - sch["metrics"]["makespan_minutes"]
    td = {d["task_id"]: d for d in cmp["task_deltas"]}
    assert set(td) == {t["id"] for t in cur["problem"]["tasks"]}
    assert td[target]["end_delta_minutes"] == td[target]["end_b"] - td[target]["end_a"]
    assert cmp["changed_task_count"] >= 1
    # CSV download
    r = client.get(f"{API}/schedules/{new['id']}/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and new["id"] in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == CSV_HEADER and len(rows) == 1 + len(cur["problem"]["tasks"])
    # approve the replan -> the first becomes superseded
    r = api.approve(new["id"])
    assert r.status_code == 200 and r.json()["superseded_schedule_id"] == sch["id"]
    assert api.schedule(sch["id"])["status"] == "superseded"
    assert_error(api.approve(sch["id"]), 409, "SUPERSEDED")


# --------------------------------------------------------------------------- templates x strategies

@pytest.mark.parametrize("template", TEMPLATE_IDS)
def test_int_templates_all_strategies(api, client, template):
    rec = api.instantiate(template)
    pid = rec["id"]
    assert api.validate(pid)["ok"] is True
    for strategy in STRATEGIES:
        run = api.solve(pid, strategy=strategy, time_limit_seconds=3, seed=7)
        assert run["feasibility"] == "feasible", (template, strategy, run)
        used = run["selection"]["used"]
        if strategy in ("heuristic", "cpsat", "ga"):
            assert strategy in used, (strategy, used)
        for sid in run["schedule_ids"]:
            recheck(rec["problem"], api.schedule(sid))
    # run history lists all five runs, newest first
    items = client.get(f"{API}/problems/{pid}/solver-runs").json()["items"]
    assert [i["request"]["strategy"] for i in items] == list(reversed(STRATEGIES))


def test_int_fixtures_import_and_solve(api):
    for name in ["precedence_only", "flexible_jobshop_10x5", "calendar_heavy", "example_3_11"]:
        rec = api.import_file(load_export(name))
        run = api.solve(rec["id"], strategy="auto", time_limit_seconds=3)
        assert run["feasibility"] == "feasible", (name, run)
        recheck(rec["problem"], api.schedule(run["primary_schedule_id"]))


# --------------------------------------------------------------------------- edge cases

def _two_task_doc(**kw):
    doc = {"name": "Edge", "horizon_start": "2026-10-19T00:00:00+05:30", "horizon_days": 3,
           "tasks": [{"id": "A", "name": "Cutting", "duration_minutes": 300, "requirements": [{"alternatives": ["M"]}]},
                     {"id": "B", "name": "Milling", "duration_minutes": 300, "requirements": [{"alternatives": ["M"]}]}],
           "resources": [{"id": "M", "name": "Saw"}], "dependencies": []}
    doc.update(kw)
    return doc


def test_int_cycle_blocks_run(api, client):
    doc = _two_task_doc(dependencies=[{"predecessor": "A", "successor": "B"}, {"predecessor": "B", "successor": "A"}])
    rec = api.create(doc)
    val = api.validate(rec["id"])
    assert val["ok"] is False and val["cpm"] is None
    cyc = [i for i in val["issues"] if i["code"] == "DEPENDENCY_CYCLE"]
    assert len(cyc) == 1 and set(cyc[0]["task_ids"]) == {"A", "B"} and "Cutting" in cyc[0]["message"]
    err = assert_error(api.post_run(rec["id"], time_limit_seconds=1), 422, "PREFLIGHT_FAILED")
    assert any(i["code"] == "DEPENDENCY_CYCLE" for i in err["details"]["issues"])
    assert client.get(f"{API}/problems/{rec['id']}/solver-runs").json()["items"] == []


def test_int_impossible_hard_deadline_preflight(api):
    rec = api.import_file(load_export("infeasible_hard_deadline"))
    val = api.validate(rec["id"])
    assert any(i["code"] == "HARD_DEADLINE_IMPOSSIBLE" and i["severity"] == "error" for i in val["issues"])
    err = assert_error(api.post_run(rec["id"]), 422, "PREFLIGHT_FAILED")
    assert "Weld" in err["details"]["issues"][0]["message"]


def test_int_hard_deadline_resource_conflict_proven_infeasible(api, client):
    # each task alone meets the deadline (preflight ok); both on one machine cannot
    dl = "2026-10-19T06:40:00+05:30"
    doc = _two_task_doc()
    for t in doc["tasks"]:
        t["deadline"], t["deadline_hard"] = dl, True
    rec = api.create(doc)
    assert api.validate(rec["id"])["ok"] is True
    run = api.solve(rec["id"], strategy="cpsat", time_limit_seconds=3)
    assert run["feasibility"] == "infeasible" and run["termination_reason"] == "proven_infeasible", run
    assert any("relaxed" in d for d in run["diagnostics"]), run["diagnostics"]
    if run["primary_schedule_id"]:
        sch = api.schedule(run["primary_schedule_id"])
        assert sch["feasibility"] == "infeasible" and sch["hard_violation_count"] > 0
        assert_error(api.approve(sch["id"]), 422, "NOT_FEASIBLE")
    # heuristic-only cannot prove it: must say unknown, never infeasible or feasible
    run = api.solve(rec["id"], strategy="heuristic", time_limit_seconds=1)
    assert run["feasibility"] == "unknown", run


def test_int_zero_capacity_and_units(api, client):
    doc = _two_task_doc()
    doc["resources"][0]["capacity"] = 0
    err = assert_error(client.post(f"{API}/problems", json=doc), 422, "VALIDATION_ERROR")
    assert any("capacity" in [str(x) for x in e["loc"]] for e in err["details"]["errors"])
    doc = _two_task_doc()
    doc["tasks"][0]["requirements"][0]["units"] = 2
    rec = api.create(doc)
    val = api.validate(rec["id"])
    assert [i["code"] for i in val["issues"] if i["severity"] == "error"] == ["UNITS_EXCEED_CAPACITY"]
    assert_error(api.post_run(rec["id"]), 422, "PREFLIGHT_FAILED")
    # a resource with no availability at all (closed every day)
    doc = _two_task_doc()
    doc["resources"][0]["calendar"] = {"weekly": {}, "blocked": []}
    rec = api.create(doc)
    codes = {(i["code"], i["severity"]) for i in api.validate(rec["id"])["issues"]}
    assert ("EMPTY_CALENDAR", "warning") in codes and ("NO_FITTING_WINDOW", "error") in codes
    assert_error(api.post_run(rec["id"]), 422, "PREFLIGHT_FAILED")


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_int_locked_tasks_kept(api, strategy):
    rec = api.instantiate("manufacturing", jobs=3)
    doc = copy.deepcopy(rec["problem"])
    t = next(t for t in doc["tasks"] if t["id"].endswith("-2") or "MILL2" in str(t["requirements"]))
    alt = [a for a in t["requirements"][0]["alternatives"]][-1]
    lock_at = "2026-10-20T15:00:00+05:30"  # Tue, inside the second shift
    t["locked"] = {"start": lock_at, "resource_ids": [alt] + [rq["alternatives"][0] for rq in t["requirements"][1:]]}
    r = api.put(rec["id"], doc, 1)
    assert r.status_code == 200, r.text
    run = api.solve(rec["id"], strategy=strategy, time_limit_seconds=3)
    assert run["feasibility"] == "feasible", run
    sch = api.schedule(run["primary_schedule_id"])
    p = next(p for p in sch["placements"] if p["task_id"] == t["id"])
    assert datetime.fromisoformat(p["start_at"]) == datetime.fromisoformat(lock_at)
    assert p["resource_ids"] == t["locked"]["resource_ids"]
    recheck(r.json()["problem"], sch)
    reasons = sch["explanation"]["tasks"][t["id"]]["reasons"]
    assert any(x["code"] == "LOCKED" for x in reasons), reasons


def test_int_conflicting_locks_infeasible(api):
    doc = _two_task_doc()
    doc["tasks"][0]["locked"] = {"start": "2026-10-19T10:00:00+05:30", "resource_ids": ["M"]}
    doc["tasks"][1]["locked"] = {"start": "2026-10-19T11:00:00+05:30", "resource_ids": ["M"]}
    rec = api.create(doc)
    run = api.solve(rec["id"], strategy="cpsat", time_limit_seconds=3)
    assert run["feasibility"] == "infeasible", run
    assert any("Unlocking" in d for d in run["diagnostics"]), run["diagnostics"]


# --------------------------------------------------------------------------- cancellation

def test_int_cancel_running_ga(api, client):
    rec = api.instantiate("manufacturing", jobs=12)
    created = api.start_run(rec["id"], strategy="ga", time_limit_seconds=30,
                            ga={"max_generations": 10000, "stagnation_generations": 1000})
    api.wait_status(created["run_id"], "running")
    time.sleep(1.5)
    t0 = time.monotonic()
    r = client.post(f"{API}/solver-runs/{created['run_id']}/cancel")
    assert r.status_code == 202 and r.json()["cancel_requested"] is True
    run = api.wait(created["run_id"], timeout=5)
    assert time.monotonic() - t0 < 2.5
    assert run["status"] == "cancelled" and run["termination_reason"] == "cancelled", run
    assert run["primary_schedule_id"], run
    sch = api.schedule(run["primary_schedule_id"])
    assert sch["status"] == "candidate"
    if sch["feasibility"] == "feasible":
        recheck(rec["problem"], sch)
    ev = api.events(created["run_id"])
    assert ev[-1]["type"] == "run_cancelled" and ev[-1]["primary_schedule_id"] == run["primary_schedule_id"]
    assert_error(client.post(f"{API}/solver-runs/{created['run_id']}/cancel"), 409, "RUN_NOT_ACTIVE")


def test_int_cancel_queued(db_url):
    from fastapi.testclient import TestClient
    from int_helpers import Api, make_app
    with TestClient(make_app(db_url, run_workers=1)) as c:
        api = Api(c)
        a = api.instantiate(jobs=10)
        b = api.instantiate(jobs=2)
        busy = api.start_run(a["id"], strategy="ga", time_limit_seconds=10)
        api.wait_status(busy["run_id"], "running")
        q = api.start_run(b["id"])
        assert api.run(q["run_id"])["status"] == "queued"
        r = c.post(f"{API}/solver-runs/{q['run_id']}/cancel")
        assert r.status_code == 202 and r.json()["status"] == "cancelled"
        assert [e["type"] for e in api.events(q["run_id"])] == ["run_queued", "run_cancelled"]
        c.post(f"{API}/solver-runs/{busy['run_id']}/cancel")
        api.wait(busy["run_id"])
        time.sleep(0.5)
        assert api.run(q["run_id"])["status"] == "cancelled"  # worker never ran it
        assert [e["type"] for e in api.events(q["run_id"])] == ["run_queued", "run_cancelled"]


# --------------------------------------------------------------------------- approve never overwrites

def test_int_approve_does_not_overwrite(api, client):
    rec = api.instantiate("project")
    pid = rec["id"]
    r1 = api.solve(pid, strategy="heuristic", time_limit_seconds=1)
    s1 = api.schedule(r1["primary_schedule_id"])
    assert api.approve(s1["id"]).status_code == 200
    # a new run produces candidates only; the approved schedule is untouched
    r2 = api.solve(pid, strategy="cpsat", time_limit_seconds=3)
    assert api.schedule(s1["id"]) == {**s1, "status": "approved",
                                      "approved_at": api.schedule(s1["id"])["approved_at"],
                                      "approved_problem_version": 1}
    approved = api.schedules(pid, "approved")
    assert [s["id"] for s in approved] == [s1["id"]]
    assert all(s["status"] == "candidate" for s in api.schedules(pid) if s["solver_run_id"] == r2["id"])
    # re-approve is idempotent and does not change approved_at
    again = api.approve(s1["id"])
    assert again.status_code == 200 and again.json()["schedule"]["approved_at"] == approved[0]["approved_at"]
    # approving the second reports the superseded one, placements of the first are unchanged
    s2 = r2["primary_schedule_id"]
    r = api.approve(s2)
    assert r.status_code == 200 and r.json()["superseded_schedule_id"] == s1["id"]
    old = api.schedule(s1["id"])
    assert old["status"] == "superseded" and old["placements"] == s1["placements"]
    assert [s["id"] for s in api.schedules(pid, "approved")] == [s2]
    # summary reflects it
    summ = next(p for p in client.get(f"{API}/problems").json()["items"] if p["id"] == pid)
    assert summ["approved_schedule_id"] == s2


def test_int_stale_schedule_approval(api, client):
    rec = api.instantiate("manufacturing", jobs=2)
    pid = rec["id"]
    run = api.solve(pid, strategy="heuristic", time_limit_seconds=1)
    sch = api.schedule(run["primary_schedule_id"])
    p = sch["placements"][0]
    doc = copy.deepcopy(rec["problem"])
    res = next(r for r in doc["resources"] if r["id"] == p["resource_ids"][0])
    res["calendar"]["blocked"].append({"start": p["start_at"], "end": p["end_at"], "reason": "Breakdown"})
    assert api.put(pid, doc, 1).status_code == 200
    err = assert_error(api.approve(sch["id"]), 409, "STALE_SCHEDULE")
    assert err["details"]["violations"] and err["details"]["issues"] == []
    assert api.schedules(pid, "approved") == []
