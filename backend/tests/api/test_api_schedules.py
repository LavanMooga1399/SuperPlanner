"""Schedules: approve/supersede/staleness, compare, CSV (A.14.6; criteria 2.13-2.15)."""

from __future__ import annotations

import copy
import csv
import io
import threading

from api_helpers import API, assert_error, small_problem


def _two_candidates(api, client):
    """Two feasible candidate schedules of one problem (from two runs)."""
    rec = api.instantiate(jobs=3)
    pid = rec["id"]
    r1 = api.solve(pid, strategy="heuristic", time_limit_seconds=1)
    r2 = api.solve(pid, strategy="cpsat", time_limit_seconds=2)
    return rec, r1["primary_schedule_id"], r2["primary_schedule_id"]


# ---------------------------------------------------------------- approve (2.13)

def test_api_approve_supersede_idempotent(api, client):
    rec, s1, s2 = _two_candidates(api, client)
    r = client.post(f"{API}/schedules/{s1}/approve", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["superseded_schedule_id"] is None
    assert body["schedule"]["status"] == "approved" and body["schedule"]["approved_problem_version"] == 1
    assert body["schedule"]["approved_at"].endswith("Z")
    again = client.post(f"{API}/schedules/{s1}/approve")
    assert again.status_code == 200 and again.json()["superseded_schedule_id"] is None
    r = client.post(f"{API}/schedules/{s2}/approve", json={"note": "better"})
    assert r.status_code == 200 and r.json()["superseded_schedule_id"] == s1
    old = api.schedule(s1)
    assert old["status"] == "superseded" and old["superseded_at"].endswith("Z")
    assert_error(client.post(f"{API}/schedules/{s1}/approve", json={}), 409, "SUPERSEDED")
    approved = client.get(f"{API}/problems/{rec['id']}/schedules?status=approved").json()["items"]
    assert [s["id"] for s in approved] == [s2]
    assert client.get(f"{API}/problems").json()["items"][0]["approved_schedule_id"] == s2
    assert_error(client.post(f"{API}/schedules/sch_missing/approve", json={}), 404, "NOT_FOUND")
    # the note is in the audit trail
    from sqlalchemy import select
    from superplanner.api.db import AuditEventRow
    with client.app.state.ctx.db.read() as s:
        rows = s.scalars(select(AuditEventRow).where(AuditEventRow.entity_id == s2,
                                                     AuditEventRow.action == "schedule.approved")).all()
        assert rows and rows[0].details["note"] == "better"


def test_api_list_schedules(api, client):
    rec, s1, s2 = _two_candidates(api, client)
    items = client.get(f"{API}/problems/{rec['id']}/schedules").json()["items"]
    assert {s1, s2} <= {s["id"] for s in items}
    assert items[0]["created_at"] >= items[-1]["created_at"]
    keys = {"id", "problem_id", "problem_version_id", "solver_run_id", "source_schedule_id", "status", "rank",
            "label", "solver", "feasibility", "objectives", "metrics", "hard_violation_count",
            "soft_violation_count", "base_problem_version", "approved_problem_version", "created_at",
            "approved_at", "superseded_at"}
    assert set(items[0]) == keys
    assert client.get(f"{API}/problems/{rec['id']}/schedules?status=approved").json()["items"] == []
    assert_error(client.get(f"{API}/problems/{rec['id']}/schedules?status=bogus"), 422, "VALIDATION_ERROR")
    assert_error(client.get(f"{API}/problems/p_missing/schedules"), 404, "NOT_FOUND")
    assert_error(client.get(f"{API}/schedules/sch_missing"), 404, "NOT_FOUND")


def test_api_concurrent_approvals_leave_one(api, client):
    rec, s1, s2 = _two_candidates(api, client)
    barrier = threading.Barrier(2)
    codes = []

    def go(sid):
        barrier.wait()
        codes.append(client.post(f"{API}/schedules/{sid}/approve", json={}).status_code)

    ts = [threading.Thread(target=go, args=(sid,)) for sid in (s1, s2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(c in (200, 409) for c in codes), codes
    approved = client.get(f"{API}/problems/{rec['id']}/schedules?status=approved").json()["items"]
    assert len(approved) == 1


def test_api_approve_not_feasible(api, client):
    doc = small_problem()
    doc["dependencies"] = []
    doc["tasks"][0]["locked"] = {"start": "2026-10-19T10:00:00+05:30"}
    doc["tasks"][1]["locked"] = {"start": "2026-10-19T10:15:00+05:30"}
    rec = client.post(f"{API}/problems", json=doc).json()
    run = api.solve(rec["id"], strategy="heuristic", time_limit_seconds=1)
    assert run["feasibility"] != "feasible"
    sid = run["primary_schedule_id"]
    assert sid, "a best-effort primary is stored even when not feasible"
    sch = api.schedule(sid)
    assert sch["hard_violation_count"] >= 1
    assert any(v["code"] == "CAPACITY_EXCEEDED" for v in sch["violations"])
    assert_error(client.post(f"{API}/schedules/{sid}/approve", json={}), 422, "NOT_FEASIBLE")


# ---------------------------------------------------------------- staleness (2.14)

def test_api_stale_approval(api, client):
    rec = api.instantiate(jobs=2)
    pid = rec["id"]
    run = api.solve(pid, strategy="heuristic", time_limit_seconds=1)
    sid = run["primary_schedule_id"]
    sch = api.schedule(sid)
    victim = sch["placements"][0]
    rid = victim["resource_ids"][0]

    # 1. harmless change -> approve with the new version
    doc = copy.deepcopy(rec["problem"])
    doc["description"] = "edited"
    assert api.put(pid, doc, 1).status_code == 200
    # 2. a preflight error -> 409 with issues
    bad = copy.deepcopy(doc)
    bad["dependencies"].append({"predecessor": bad["tasks"][0]["id"], "successor": bad["tasks"][0]["id"]})
    assert api.put(pid, bad, 2).status_code == 200
    err = assert_error(client.post(f"{API}/schedules/{sid}/approve", json={}), 409, "STALE_SCHEDULE")
    assert err["details"]["violations"] == [] and err["details"]["issues"]
    assert err["details"]["issues"][0]["code"] == "SELF_DEPENDENCY"
    # 3. block the machine over a placed task -> 409 with violations
    blocked = copy.deepcopy(doc)
    for r in blocked["resources"]:
        if r["id"] == rid:
            cal = r.get("calendar") or {"weekly": None, "blocked": []}
            cal.setdefault("blocked", []).append({"start": victim["start_at"], "end": victim["end_at"],
                                                  "reason": "Breakdown"})
            r["calendar"] = cal
    assert api.put(pid, blocked, 3).status_code == 200
    err = assert_error(client.post(f"{API}/schedules/{sid}/approve", json={}), 409, "STALE_SCHEDULE")
    assert err["details"]["issues"] == []
    assert any(v["code"] == "CALENDAR_VIOLATED" and victim["task_id"] in v["task_ids"]
               for v in err["details"]["violations"])
    assert api.schedule(sid)["status"] == "candidate"
    # back to a compatible document -> approve, recorded against version 5
    assert api.put(pid, doc, 4).status_code == 200
    r = client.post(f"{API}/schedules/{sid}/approve", json={})
    assert r.status_code == 200
    assert r.json()["schedule"]["approved_problem_version"] == 5
    assert r.json()["schedule"]["base_problem_version"] == 1


# ---------------------------------------------------------------- compare + CSV (2.15)

def test_api_compare(api, client):
    rec, s1, s2 = _two_candidates(api, client)
    r = client.get(f"{API}/schedules/compare?a={s1}&b={s2}")
    assert r.status_code == 200
    cmp_ = r.json()
    assert set(cmp_) == {"a", "b", "metric_deltas", "task_deltas", "changed_task_count"}
    a, b = api.schedule(s1), api.schedule(s2)
    md = cmp_["metric_deltas"]
    assert set(md) == {"makespan_minutes", "total_tardiness_minutes", "weighted_tardiness", "late_tasks", "cost"}
    assert md["makespan_minutes"] == b["metrics"]["makespan_minutes"] - a["metrics"]["makespan_minutes"]
    assert md["cost"] == round(b["metrics"]["cost"] - a["metrics"]["cost"], 2)
    assert len(cmp_["task_deltas"]) == len(rec["problem"]["tasks"])
    pa = {p["task_id"]: p for p in a["placements"]}
    pb = {p["task_id"]: p for p in b["placements"]}
    changed = 0
    for d in cmp_["task_deltas"]:
        x, y = pa[d["task_id"]], pb[d["task_id"]]
        assert d["start_a"] == x["start"] and d["start_b"] == y["start"]
        assert d["end_delta_minutes"] == y["end"] - x["end"]
        assert d["resource_changed"] == (x["resource_ids"] != y["resource_ids"])
        changed += int(x["start"] != y["start"] or x["end"] != y["end"] or x["resource_ids"] != y["resource_ids"])
    assert cmp_["changed_task_count"] == changed
    ends = [abs(d["end_delta_minutes"]) for d in cmp_["task_deltas"]]
    assert ends == sorted(ends, reverse=True)
    other = api.instantiate(jobs=1)
    s3 = api.solve(other["id"], strategy="heuristic", time_limit_seconds=1)["primary_schedule_id"]
    assert_error(client.get(f"{API}/schedules/compare?a={s1}&b={s3}"), 422, "DIFFERENT_PROBLEMS")
    assert_error(client.get(f"{API}/schedules/compare?a={s1}&b=sch_missing"), 404, "NOT_FOUND")
    assert_error(client.get(f"{API}/schedules/compare?a={s1}"), 422, "VALIDATION_ERROR")


def test_api_compare_different_horizons_and_one_sided(api, client):
    rec = client.post(f"{API}/problems", json=small_problem()).json()
    pid = rec["id"]
    s1 = api.solve(pid, strategy="heuristic", time_limit_seconds=1)["primary_schedule_id"]
    doc = copy.deepcopy(rec["problem"])
    doc["horizon_start"] = "2026-10-18T00:00:00+05:30"   # one day earlier: minutes shift by 1440
    doc["tasks"][0]["earliest_start"] = "2026-10-19T00:00:00+05:30"
    doc["tasks"].append({"id": "C", "name": "Task C", "duration_minutes": 15,
                         "requirements": [{"alternatives": ["M1"]}], "earliest_start": "2026-10-20T00:00:00+05:30"})
    assert api.put(pid, doc, 1).status_code == 200
    s2 = api.solve(pid, strategy="heuristic", time_limit_seconds=1)["primary_schedule_id"]
    cmp_ = client.get(f"{API}/schedules/compare?a={s1}&b={s2}").json()
    by = {d["task_id"]: d for d in cmp_["task_deltas"]}
    assert by["A"]["start_a"] == 0 and by["A"]["start_b"] == 0 and by["A"]["start_delta_minutes"] == 0
    assert by["C"]["in_a"] is False and by["C"]["in_b"] is True
    assert by["C"]["start_a"] is None and by["C"]["start_delta_minutes"] is None
    assert by["C"]["start_b"] == 1440 and by["C"]["resources_a"] == [] and by["C"]["resource_changed"] is False
    assert cmp_["task_deltas"][0]["task_id"] == "C"
    assert cmp_["changed_task_count"] == 1


def test_api_csv_export(api, client):
    rec = api.instantiate(jobs=2)
    sid = api.solve(rec["id"], strategy="heuristic", time_limit_seconds=1)["primary_schedule_id"]
    r = client.get(f"{API}/schedules/{sid}/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    slug = rec["problem"]["name"].lower().replace(" ", "-")
    assert r.headers["content-disposition"] == f'attachment; filename="{slug}-{sid}.csv"'
    assert r.text.split("\r\n")[0] == ("task_id,task_name,group,type,start,end,duration_minutes,resource_ids,"
                                       "resource_names,deadline,deadline_hard,lateness_minutes,on_critical_chain")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == len(rec["problem"]["tasks"])
    sch = api.schedule(sid)
    first = next(p for p in sch["placements"] if p["task_id"] == rows[0]["task_id"])
    assert rows[0]["start"] == first["start_at"] and rows[0]["end"] == first["end_at"]
    assert rows[0]["resource_ids"] == ";".join(first["resource_ids"])
    assert rows[0]["deadline_hard"] in ("true", "false") and rows[0]["on_critical_chain"] in ("true", "false")
    asm = next(r_ for r_ in rows if ";" in r_["resource_ids"])  # assembly needs bench + operator
    assert len(asm["resource_names"].split(";")) == 2
    assert_error(client.get(f"{API}/schedules/sch_missing/export.csv"), 404, "NOT_FOUND")
