"""Solver runs: lifecycle, guards, snapshot isolation, cancel, SSE, recovery (A.14.5, A.15, A.16)."""

from __future__ import annotations

import copy
import threading
import time
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from api_helpers import API, Api, assert_error, make_app, small_problem
from superplanner import engine
from superplanner.engine import Placement, Problem

LONG_GA = {"strategy": "ga", "time_limit_seconds": 30,
           "ga": {"max_generations": 10000, "stagnation_generations": 1000}}


def _parse_sse(text: str) -> list[dict]:
    frames = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln and not ln.startswith(":")]
        if not lines:
            continue
        f = {}
        for ln in lines:
            k, _, v = ln.partition(": ")
            f[k] = v
        frames.append(f)
    return frames


# ---------------------------------------------------------------- lifecycle (2.8)

def test_api_run_lifecycle(api, client):
    rec = api.instantiate(jobs=4)
    pid = rec["id"]
    t0 = time.monotonic()
    created = api.start_run(pid, time_limit_seconds=3)
    assert created["status"] == "queued"
    assert created["status_url"] == f"{API}/solver-runs/{created['run_id']}"
    assert created["events_url"] == f"{API}/solver-runs/{created['run_id']}/events"
    assert created["problem_version_id"].startswith("pv_")
    run = api.wait(created["run_id"], timeout=3 + 5)
    assert time.monotonic() - t0 < 3 + 5
    assert run["status"] == "completed"
    assert run["feasibility"] == "feasible"
    assert run["selection"]["requested"] == "auto" and run["selection"]["used"][0] == "heuristic"
    assert run["phases"][0]["solver"] == "heuristic"
    assert run["engine_version"] == "0.1.0" and run["error"] is None
    assert run["created_at"].endswith("Z") and run["finished_at"].endswith("Z")
    assert run["elapsed_seconds"] is not None and run["elapsed_seconds"] >= 0
    # stored request is fully defaulted
    req = run["request"]
    assert req["strategy"] == "auto" and req["time_limit_seconds"] == 3 and req["seed"] == 0
    assert req["max_alternatives"] == 2 and req["objectives"] is None
    assert req["ga"]["max_generations"] == 300 and req["cpsat"]["num_workers"] == 8
    assert run["primary_schedule_id"] == run["schedule_ids"][0]
    # independent re-validation of the stored placements
    sch = api.schedule(run["primary_schedule_id"])
    problem = Problem.model_validate(rec["problem"])
    report = engine.validate_schedule(problem, [Placement(**{k: p[k] for k in ("task_id", "start", "end",
                                                                                "resource_ids")})
                                                for p in sch["placements"]])
    assert not [v for v in report.violations if v.severity == "hard"]
    assert sch["feasibility"] == "feasible" and sch["rank"] == 0 and sch["label"] == "Recommended"
    assert sch["solver_run_id"] == run["id"] and sch["status"] == "candidate"
    assert sch["base_problem_version"] == 1 and sch["horizon_start"] == "2026-10-19T00:00:00+05:30"
    p0 = sch["placements"][0]
    assert datetime.fromisoformat(p0["start_at"]) == datetime.fromisoformat(sch["horizon_start"]) + timedelta(minutes=p0["start"])
    assert p0["start_at"].endswith("+05:30")
    assert set(sch["explanation"]["tasks"]) == {t["id"] for t in rec["problem"]["tasks"]}
    # list endpoints
    runs = client.get(f"{API}/problems/{pid}/solver-runs").json()["items"]
    assert [r["id"] for r in runs] == [run["id"]]
    summ = client.get(f"{API}/problems").json()["items"][0]
    assert summ["latest_run"] == {"id": run["id"], "status": "completed"}
    assert_error(client.get(f"{API}/solver-runs/run_missing"), 404, "NOT_FOUND")
    assert_error(client.get(f"{API}/problems/p_missing/solver-runs"), 404, "NOT_FOUND")


def test_api_run_bad_params(api, client):
    pid = api.instantiate(jobs=2)["id"]
    for body in ({"strategy": "magic"}, {"time_limit_seconds": 0}, {"time_limit_seconds": 301},
                 {"ga": {"mutation_rate": 0}}, {"unknown": 1}):
        assert_error(client.post(f"{API}/problems/{pid}/solver-runs", json=body), 422, "VALIDATION_ERROR")
    assert_error(client.post(f"{API}/problems/p_missing/solver-runs", json={}), 404, "NOT_FOUND")


def test_api_run_no_body_defaults(api, client):
    pid = api.instantiate(jobs=1)["id"]
    r = client.post(f"{API}/problems/{pid}/solver-runs")
    assert r.status_code == 202, r.text
    client.post(f"{API}/solver-runs/{r.json()['run_id']}/cancel")
    api.wait(r.json()["run_id"])


# ---------------------------------------------------------------- guards (2.9)

def test_api_run_preflight_failed(api, client):
    rec = client.post(f"{API}/problems", json=small_problem()).json()
    doc = copy.deepcopy(rec["problem"])
    doc["dependencies"].append({"predecessor": "B", "successor": "A"})
    api.put(rec["id"], doc, 1)
    err = assert_error(client.post(f"{API}/problems/{rec['id']}/solver-runs", json={}), 422, "PREFLIGHT_FAILED")
    assert err["message"].startswith("Fix 1 problem")
    assert [i["code"] for i in err["details"]["issues"]] == ["DEPENDENCY_CYCLE"]
    assert client.get(f"{API}/problems/{rec['id']}/solver-runs").json()["items"] == []


def test_api_run_already_active(api, client):
    pid = api.instantiate(jobs=20)["id"]
    first = api.start_run(pid, **LONG_GA)
    err = assert_error(client.post(f"{API}/problems/{pid}/solver-runs", json={}), 409, "RUN_ALREADY_ACTIVE")
    assert err["details"]["run_id"] == first["run_id"]
    client.post(f"{API}/solver-runs/{first['run_id']}/cancel")
    api.wait(first["run_id"])


def test_api_run_concurrent_creation_one_wins(api, client):
    pid = api.instantiate(jobs=20)["id"]
    barrier = threading.Barrier(2)
    codes: list[int] = []
    bodies: list[dict] = []

    def go():
        barrier.wait()
        r = client.post(f"{API}/problems/{pid}/solver-runs", json=LONG_GA)
        codes.append(r.status_code)
        bodies.append(r.json())

    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(codes) == [202, 409], codes
    run_id = next(b["run_id"] for b in bodies if "run_id" in b)
    client.post(f"{API}/solver-runs/{run_id}/cancel")
    api.wait(run_id)


# ---------------------------------------------------------------- snapshot isolation (2.10)

def test_api_snapshot_isolation(api, client):
    rec = api.instantiate(jobs=6)
    pid = rec["id"]
    created = api.start_run(pid, strategy="cpsat", time_limit_seconds=2)
    pv_id = created["problem_version_id"]
    doc = copy.deepcopy(rec["problem"])
    doc["tasks"][0]["duration_minutes"] += 100
    assert api.put(pid, doc, 1).status_code == 200
    run = api.wait(created["run_id"])
    assert run["problem_version_id"] == pv_id
    from superplanner.api.db import ProblemVersionRow
    with client.app.state.ctx.db.read() as s:
        snap = s.get(ProblemVersionRow, pv_id)
        assert snap.document == rec["problem"] and snap.base_version == 1 and snap.kind == "snapshot"
    sch = api.schedule(run["primary_schedule_id"])
    first = next(p for p in sch["placements"] if p["task_id"] == doc["tasks"][0]["id"])
    assert first["end"] - first["start"] == rec["problem"]["tasks"][0]["duration_minutes"]


def test_api_snapshot_reused_for_same_version(api, client):
    pid = api.instantiate(jobs=1)["id"]
    a = api.solve(pid, strategy="heuristic", time_limit_seconds=1)
    b = api.solve(pid, strategy="heuristic", time_limit_seconds=1)
    assert a["problem_version_id"] == b["problem_version_id"]


# ---------------------------------------------------------------- cancel (2.11)

def test_api_cancel_running(api, client):
    pid = api.instantiate(jobs=20)["id"]
    created = api.start_run(pid, **LONG_GA)
    rid = created["run_id"]
    api.wait_status(rid, "running")
    time.sleep(1.0)
    t0 = time.monotonic()
    r = client.post(f"{API}/solver-runs/{rid}/cancel")
    assert r.status_code == 202
    assert r.json() == {"run_id": rid, "status": "running", "cancel_requested": True}
    run = api.wait(rid, timeout=5)
    assert time.monotonic() - t0 < 2.0
    assert run["status"] == "cancelled"
    assert run["primary_schedule_id"] is not None  # best-so-far kept as a candidate
    ev = api.events(rid)
    assert ev[-1]["type"] == "run_cancelled"
    assert ev[-1]["primary_schedule_id"] == run["primary_schedule_id"]
    assert_error(client.post(f"{API}/solver-runs/{rid}/cancel"), 409, "RUN_NOT_ACTIVE")
    assert_error(client.post(f"{API}/solver-runs/run_missing/cancel"), 404, "NOT_FOUND")


def test_api_cancel_queued(db_url):
    with TestClient(make_app(db_url, run_workers=1)) as client:
        api = Api(client)
        busy = api.instantiate(jobs=20)["id"]
        other = api.instantiate(jobs=2)["id"]
        blocker = api.start_run(busy, **LONG_GA)
        api.wait_status(blocker["run_id"], "running")
        queued = api.start_run(other, strategy="heuristic", time_limit_seconds=1)
        rid = queued["run_id"]
        assert client.get(f"{API}/solver-runs/{rid}").json()["status"] == "queued"
        r = client.post(f"{API}/solver-runs/{rid}/cancel")
        assert r.status_code == 202
        assert r.json() == {"run_id": rid, "status": "cancelled", "cancel_requested": True}
        client.post(f"{API}/solver-runs/{blocker['run_id']}/cancel")
        api.wait(blocker["run_id"])
        time.sleep(0.3)  # give the single worker time to pick up (and skip) the cancelled job
        run = client.get(f"{API}/solver-runs/{rid}").json()
        assert run["status"] == "cancelled" and run["started_at"] is None and run["schedule_ids"] == []
        types = [e["type"] for e in api.events(rid)]
        assert types == ["run_queued", "run_cancelled"]


# ---------------------------------------------------------------- SSE (2.12)

def test_api_sse_replay_and_terminal(api, client):
    pid = api.instantiate(jobs=3)["id"]
    run = api.solve(pid, strategy="cpsat", time_limit_seconds=2)
    rid = run["id"]
    with client.stream("GET", f"{API}/solver-runs/{rid}/events") as s:
        assert s.status_code == 200
        assert s.headers["content-type"].startswith("text/event-stream")
        assert s.headers["cache-control"] == "no-cache" and s.headers["x-accel-buffering"] == "no"
        frames = _parse_sse(s.read().decode())
    data = [json.loads(f["data"]) for f in frames]
    assert all("id" in f and "event" in f for f in frames)
    assert [d["seq"] for d in data] == list(range(1, len(data) + 1))
    assert all(f["event"] == d["type"] and int(f["id"]) == d["seq"] for f, d in zip(frames, data))
    assert data[0]["type"] == "run_queued" and data[0]["elapsed_seconds"] == 0
    assert data[0]["problem_version_id"] == run["problem_version_id"]
    assert data[1]["type"] == "run_started" and data[1]["strategy_requested"] == "cpsat"
    assert data[-1]["type"] == "run_completed"
    term = data[-1]
    assert term["primary_schedule_id"] == run["primary_schedule_id"] and term["schedule_ids"] == run["schedule_ids"]
    assert term["feasibility"] == "feasible" and term["optimality_proven"] == run["optimality_proven"]
    for d in data:
        assert d["run_id"] == rid and d["ts"].endswith("Z") and "elapsed_seconds" in d
    ps = [d for d in data if d["type"] == "phase_started"]
    pc = [d for d in data if d["type"] == "phase_completed"]
    assert [d["solver"] for d in ps] == [d["solver"] for d in pc] == run["selection"]["used"]
    assert all(d["reason"] for d in ps)
    assert all({"status", "feasibility", "termination_reason", "objectives"} <= set(d) for d in pc)
    prog = [d for d in data if d["type"] == "progress"]
    assert all({"solver", "iteration", "best_score", "best_objectives", "feasible_found", "extra"} <= set(d)
               for d in prog)
    # replay after a cursor: header wins over ?after
    with client.stream("GET", f"{API}/solver-runs/{rid}/events?after=1", headers={"Last-Event-ID": "3"}) as s:
        replay = [json.loads(f["data"]) for f in _parse_sse(s.read().decode())]
    assert [d["seq"] for d in replay] == [d["seq"] for d in data if d["seq"] > 3]
    with client.stream("GET", f"{API}/solver-runs/{rid}/events?after=2") as s:
        replay = [json.loads(f["data"]) for f in _parse_sse(s.read().decode())]
    assert replay[0]["seq"] == 3
    # cursor at the last event of a finished run -> 204 (stops EventSource reconnects)
    r = client.get(f"{API}/solver-runs/{rid}/events", headers={"Last-Event-ID": str(data[-1]["seq"])})
    assert r.status_code == 204
    # JSON variant
    items = client.get(f"{API}/solver-runs/{rid}/events?stream=false").json()["items"]
    assert items == data
    items = client.get(f"{API}/solver-runs/{rid}/events?stream=false&after=4").json()["items"]
    assert items == data[4:]
    assert_error(client.get(f"{API}/solver-runs/run_missing/events"), 404, "NOT_FOUND")


def test_api_sse_live_stream_and_throttle(api, client):
    pid = api.instantiate(jobs=12)["id"]
    created = api.start_run(pid, strategy="ga", time_limit_seconds=3,
                            ga={"max_generations": 10000, "stagnation_generations": 1000})
    with client.stream("GET", created["events_url"]) as s:
        assert s.status_code == 200
        frames = _parse_sse(s.read().decode())
    data = [json.loads(f["data"]) for f in frames]
    assert data[0]["seq"] == 1 and data[-1]["type"] == "run_completed"
    prog = [d for d in data if d["type"] == "progress"]
    assert prog, "GA should report progress"
    # max 2 progress events per second (one extra flush allowed right before each phase_completed)
    phases = sum(1 for d in data if d["type"] == "phase_completed")
    span = max(d["elapsed_seconds"] for d in data)
    assert len(prog) <= 2 * span + phases + 1, (len(prog), span)
    by_phase: dict[str, list[float]] = {}
    for d in prog:
        by_phase.setdefault(d["solver"], []).append(d["elapsed_seconds"])
    for times in by_phase.values():
        gaps = [b - a for a, b in zip(times, times[1:])]
        assert sum(1 for g in gaps if g < 0.45) <= 1, gaps


# ---------------------------------------------------------------- recovery (2.17)

@pytest.mark.inline_jobs
def test_api_startup_recovery(db_url):
    with TestClient(make_app(db_url)) as client:
        api = Api(client)
        pid = api.instantiate(jobs=1)["id"]
        run = api.solve(pid, strategy="heuristic", time_limit_seconds=1)
        from superplanner.api.db import SolverRunRow
        with client.app.state.ctx.db.write() as s:
            row = s.get(SolverRunRow, run["id"])
            row.status = "running"
            row.finished_at = None
    with TestClient(make_app(db_url)) as client:
        r = client.get(f"{API}/solver-runs/{run['id']}").json()
        assert r["status"] == "failed"
        assert r["error"] == "Server restarted before the run finished."
        ev = Api(client).events(run["id"])
        assert ev[-1]["type"] == "run_failed" and ev[-1]["error"] == r["error"]
        assert [e["seq"] for e in ev] == list(range(1, len(ev) + 1))


@pytest.mark.parametrize("strategy", ["heuristic", "cpsat", "ga", "hybrid"])
def test_api_run_each_strategy(api, strategy):
    pid = api.instantiate(jobs=3)["id"]
    run = api.solve(pid, strategy=strategy, time_limit_seconds=2)
    assert run["feasibility"] == "feasible"
    assert run["selection"]["requested"] == strategy
