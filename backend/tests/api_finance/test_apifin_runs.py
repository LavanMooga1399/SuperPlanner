"""F2: run lifecycle, SSE, one active run, preflight 422, cancel and races, delete during runs, recovery,
snapshot reuse and audit (FINANCE.md 17-19)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from apifin_helpers import FAST, FIN, SLOW, FinApi, assert_error, make_app, minimal_plan, sse_frames
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from superplanner.api.db import AuditEventRow
from superplanner.api.finance import run_service
from superplanner.api.finance.db_models import (FinancePlanVersionRow, FinanceResultRow, FinanceRunEventRow,
                                                FinanceRunRow)

STAGES = ["preflight", "cashflow", "optimize", "simulate", "validate"]


def _count(fin: FinApi, model, **where) -> int:
    with fin.ctx.db.read() as s:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return int(s.scalar(q))


def test_run_lifecycle_and_events(fin):
    plan = fin.instantiate()
    r = fin.c.post(f"{FIN}/plans/{plan['id']}/runs", json=FAST)
    assert r.status_code == 202
    created = r.json()
    rid = created["run_id"]
    assert set(created) == {"run_id", "status", "plan_version_id", "status_url", "events_url"}
    assert rid.startswith("frun_") and created["status"] == "queued"
    assert created["plan_version_id"].startswith("fpv_")
    assert created["status_url"] == f"{FIN}/runs/{rid}" and created["events_url"] == f"{FIN}/runs/{rid}/events"

    run = fin.wait(rid)
    assert run["status"] == "completed" and run["feasibility"] == "feasible"
    assert run["result_id"].startswith("fres_") and run["error"] is None and run["kind"] == "baseline"
    assert set(run) == {"id", "plan_id", "plan_version_id", "kind", "label", "status", "request", "what_if",
                        "engine_version", "feasibility", "result_id", "error", "cancel_requested", "created_at",
                        "started_at", "finished_at", "elapsed_seconds"}
    assert run["engine_version"] == "fin-0.2.0" and run["what_if"] is None
    assert run["request"]["simulation"]["n_paths"] == 200 and run["request"]["seed"] == 0  # fully defaulted
    assert "income_interruption" in run["request"]["simulation"]
    assert run["elapsed_seconds"] >= 0 and run["finished_at"].endswith("Z")

    events = fin.events(rid)
    types = [e["type"] for e in events]
    assert types[:3] == ["run_queued", "run_started", "stage_started"]
    assert types[-1] == "run_completed"
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(events) + 1))
    for e in events:
        assert {"run_id", "seq", "type", "ts", "elapsed_seconds"} <= set(e) and e["run_id"] == rid
    assert events[0]["plan_version_id"] == created["plan_version_id"] and events[0]["kind"] == "baseline"
    started = [e["stage"] for e in events if e["type"] == "stage_started"]
    completed = [e["stage"] for e in events if e["type"] == "stage_completed"]
    assert started == completed == STAGES
    for e in events:
        if e["type"] == "stage_started":
            assert isinstance(e["message"], str)
        if e["type"] == "stage_completed":
            assert e["seconds"] >= 0
        if e["type"] == "progress":
            assert 0 <= e["fraction"] <= 1 and e["stage"] in STAGES and isinstance(e["detail"], dict)
    # every stage's events lie between its stage_started and stage_completed
    cur = None
    for e in events:
        if e["type"] == "stage_started":
            cur = e["stage"]
        elif e["type"] == "progress":
            assert e["stage"] == cur
        elif e["type"] == "stage_completed":
            assert e["stage"] == cur
            cur = None
    done = events[-1]
    assert done["result_id"] == run["result_id"] and done["feasibility"] == "feasible"
    assert done["goals_total"] == 2 and 0 <= done["goals_on_track"] <= 2

    runs = fin.c.get(f"{FIN}/plans/{plan['id']}/runs").json()["items"]
    assert [x["id"] for x in runs] == [rid]
    summary = fin.c.get(f"{FIN}/plans").json()["items"][0]
    assert summary["latest_run"] == {"id": rid, "status": "completed"}
    assert summary["latest_result"]["id"] == run["result_id"] and summary["latest_result"]["goals_total"] == 2


def test_run_body_optional_and_validation(fin):
    plan = fin.create()
    r = fin.c.post(f"{FIN}/plans/{plan['id']}/runs")
    assert r.status_code == 202
    run = fin.wait(r.json()["run_id"])
    assert run["status"] == "completed"
    assert run["request"]["simulation"]["n_paths"] == 2000 and run["request"]["compute_fixes"] is True
    assert_error(fin.c.post(f"{FIN}/plans/{plan['id']}/runs", json={"bogus": 1}), 422, "VALIDATION_ERROR")
    assert_error(fin.c.post(f"{FIN}/plans/{plan['id']}/runs", json={"time_limit_seconds": 1}), 422,
                 "VALIDATION_ERROR")
    assert_error(fin.c.post(f"{FIN}/plans/fp_nope/runs", json=FAST), 404, "NOT_FOUND")
    assert_error(fin.c.get(f"{FIN}/plans/fp_nope/runs"), 404, "NOT_FOUND")
    assert_error(fin.c.get(f"{FIN}/runs/frun_nope"), 404, "NOT_FOUND")
    assert_error(fin.c.get(f"{FIN}/runs/frun_nope/events"), 404, "NOT_FOUND")
    assert_error(fin.c.post(f"{FIN}/runs/frun_nope/cancel"), 404, "NOT_FOUND")


def test_preflight_failed_422(fin):
    doc = minimal_plan()
    doc["goals"][0]["target_month"] = "2020-01"
    plan = fin.create(doc)
    err = assert_error(fin.c.post(f"{FIN}/plans/{plan['id']}/runs", json=FAST), 422, "PREFLIGHT_FAILED")
    issues = err["details"]["issues"]
    assert issues and all(i["severity"] == "error" for i in issues)
    assert any(i["code"] == "GOAL_TOO_SOON" and "Car" in i["message"] for i in issues)
    assert _count(fin, FinanceRunRow) == 0 and _count(fin, FinancePlanVersionRow) == 0


def test_second_run_409_then_cancel_running_stores_no_result(fin):
    plan = fin.instantiate()
    rid = fin.start_run(plan["id"], SLOW)["run_id"]
    err = assert_error(fin.c.post(f"{FIN}/plans/{plan['id']}/runs", json=FAST), 409, "RUN_ALREADY_ACTIVE")
    assert err["details"]["run_id"] == rid
    # delete is refused while the run is active
    err = assert_error(fin.c.delete(f"{FIN}/plans/{plan['id']}"), 409, "RUN_ACTIVE")
    assert err["details"]["run_id"] == rid
    fin.wait_event(rid, "stage_started")
    fin.wait_status(rid, "running")
    r = fin.c.post(f"{FIN}/runs/{rid}/cancel")
    assert r.status_code == 202
    assert r.json() == {"run_id": rid, "status": "running", "cancel_requested": True}
    run = fin.wait(rid, timeout=10)
    assert run["status"] == "cancelled" and run["result_id"] is None and run["cancel_requested"] is True
    assert fin.events(rid)[-1]["type"] == "run_cancelled"
    assert _count(fin, FinanceResultRow, run_id=rid) == 0
    assert_error(fin.c.post(f"{FIN}/runs/{rid}/cancel"), 409, "RUN_NOT_ACTIVE")
    # a cancel-requested run is no longer active: a new run may start
    fin.solve(plan["id"])


def test_cancel_queued_run_is_immediate(tmp_path):
    with TestClient(make_app(f"sqlite:///{tmp_path / 'q.db'}", run_workers=1)) as c:
        fin = FinApi(c)
        gate = threading.Event()
        fin.ctx.executor.submit("block_the_pool", lambda _rid, _ev: gate.wait(20))
        try:
            plan = fin.create()
            rid = fin.start_run(plan["id"])["run_id"]
            assert fin.run(rid)["status"] == "queued"
            r = c.post(f"{FIN}/runs/{rid}/cancel")
            assert r.status_code == 202
            assert r.json() == {"run_id": rid, "status": "cancelled", "cancel_requested": True}
            run = fin.run(rid)
            assert run["status"] == "cancelled" and run["finished_at"] is not None
            assert [e["type"] for e in fin.events(rid)] == ["run_queued", "run_cancelled"]
        finally:
            gate.set()
        fin.worker_done(rid)
        # the worker never started it
        assert [e["type"] for e in fin.events(rid)] == ["run_queued", "run_cancelled"]
        assert fin.run(rid)["started_at"] is None


def test_cancel_after_run_plan_returned_but_before_final_write(fin, monkeypatch):
    """[R11]: cancel_requested set after `run_plan` returned -> cancelled, no result row."""
    calls = []

    def hook(run_id: str) -> None:
        calls.append(run_id)
        run_service.cancel_run(fin.ctx, run_id)

    monkeypatch.setattr(run_service, "_before_final_write", hook)
    plan = fin.instantiate()
    rid = fin.start_run(plan["id"])["run_id"]
    run = fin.wait(rid)
    assert calls == [rid]
    assert run["status"] == "cancelled" and run["result_id"] is None
    assert fin.events(rid)[-1]["type"] == "run_cancelled"
    assert _count(fin, FinanceResultRow) == 0
    assert fin.c.get(f"{FIN}/plans/{plan['id']}/results").json()["items"] == []


def test_completed_run_has_exactly_one_result(fin):
    plan = fin.instantiate()
    run = fin.solve(plan["id"])
    assert _count(fin, FinanceResultRow, run_id=run["id"]) == 1
    assert_error(fin.c.post(f"{FIN}/runs/{run['id']}/cancel"), 409, "RUN_NOT_ACTIVE")


def test_delete_plan_while_cancel_requested_run_executes(fin, caplog):
    plan = fin.instantiate()
    rid = fin.start_run(plan["id"], SLOW)["run_id"]
    fin.wait_status(rid, "running")
    fin.wait_event(rid, "stage_started")
    assert fin.c.post(f"{FIN}/runs/{rid}/cancel").status_code == 202
    with caplog.at_level(logging.WARNING, logger="superplanner.api.finance"):
        r = fin.c.delete(f"{FIN}/plans/{plan['id']}")
        assert r.status_code == 204, r.text
        fin.worker_done(rid)
    assert not [rec for rec in caplog.records if rec.levelno >= logging.WARNING], caplog.text
    assert_error(fin.c.get(f"{FIN}/runs/{rid}"), 404)
    for model in (FinanceRunRow, FinanceRunEventRow, FinanceResultRow, FinancePlanVersionRow):
        assert _count(fin, model) == 0, model


def test_delete_plan_with_history_cascades(fin):
    plan = fin.instantiate()
    fin.solve(plan["id"])
    assert fin.c.delete(f"{FIN}/plans/{plan['id']}").status_code == 204
    for model in (FinanceRunRow, FinanceRunEventRow, FinanceResultRow, FinancePlanVersionRow):
        assert _count(fin, model) == 0, model


def test_sse_replay_resume_and_204(fin):
    plan = fin.instantiate()
    run = fin.solve(plan["id"])
    rid = run["id"]
    events = fin.events(rid)
    last = events[-1]["seq"]

    r = fin.c.get(f"{FIN}/runs/{rid}/events")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    frames = sse_frames(r.text)
    assert [int(f["id"]) for f in frames] == [e["seq"] for e in events]
    assert [f["event"] for f in frames] == [e["type"] for e in events]

    r = fin.c.get(f"{FIN}/runs/{rid}/events", headers={"Last-Event-ID": "2"})
    frames = sse_frames(r.text)
    assert int(frames[0]["id"]) == 3 and frames[-1]["event"] == "run_completed"
    r = fin.c.get(f"{FIN}/runs/{rid}/events?after=2")
    assert int(sse_frames(r.text)[0]["id"]) == 3
    assert fin.c.get(f"{FIN}/runs/{rid}/events?after=2&stream=false").json()["items"][0]["seq"] == 3

    r = fin.c.get(f"{FIN}/runs/{rid}/events", headers={"Last-Event-ID": str(last)})
    assert r.status_code == 204
    assert fin.c.get(f"{FIN}/runs/{rid}/events?after={last}").status_code == 204
    assert fin.c.get(f"{FIN}/runs/{rid}/events?after={last}&stream=false").json() == {"items": []}
    assert_error(fin.c.get(f"{FIN}/runs/{rid}/events", headers={"Last-Event-ID": "x"}), 422, "VALIDATION_ERROR")


def test_sse_live_stream_until_terminal(fin):
    plan = fin.instantiate("family")
    rid = fin.start_run(plan["id"])["run_id"]
    with fin.c.stream("GET", f"{FIN}/runs/{rid}/events") as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    frames = sse_frames(text)
    assert frames[0]["event"] == "run_queued" and frames[-1]["event"] == "run_completed"
    assert [int(f["id"]) for f in frames] == list(range(1, len(frames) + 1))


def _ts(e: dict) -> float:
    return datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).timestamp()


def test_progress_is_throttled(fin):
    plan = fin.instantiate()
    req = {"time_limit_seconds": 60, "simulation": {"n_paths": 4000}, "compute_fixes": True, "calibration_rounds": 2}
    run = fin.solve(plan["id"], req)
    events = fin.events(run["id"])
    # progress events written by the throttle (not the flush right before a stage_completed) are >= 0.5 s apart
    throttled = [e for i, e in enumerate(events) if e["type"] == "progress"
                 and not (i + 1 < len(events) and events[i + 1]["type"] == "stage_completed")]
    for a, b in zip(throttled, throttled[1:]):
        assert _ts(b) - _ts(a) >= 0.4, (a, b)
    progress = [e for e in events if e["type"] == "progress"]
    span = max(1.0, _ts(events[-1]) - _ts(events[1]))
    flushes = len(progress) - len(throttled)
    assert len(throttled) <= 2 * span + 1
    assert flushes <= len([e for e in events if e["type"] == "stage_completed"])


def test_startup_recovery_marks_runs_failed(db_url):
    with TestClient(make_app(db_url)) as c:
        fin = FinApi(c)
        plan = fin.create()
        with fin.ctx.db.write() as s:
            row = s.get(run_service.FinancePlanRow, plan["id"])
            pv = run_service.snapshot(s, row)
            ids = []
            for status in ("queued", "running"):
                run = FinanceRunRow(id=f"frun_{status}", plan_id=plan["id"], plan_version_id=pv.id, kind="baseline",
                                    status=status, request=FAST, seed=0, engine_version="fin-0.2.0")
                s.add(run)
                s.flush()
                run_service.add_event(s, run.id, "run_queued", {"plan_version_id": pv.id, "kind": "baseline"}, 0)
                ids.append(run.id)
    with TestClient(make_app(db_url)) as c:
        fin = FinApi(c)
        for rid in ids:
            run = fin.run(rid)
            assert run["status"] == "failed" and run["error"] == "Server restarted before the run finished."
            last = fin.events(rid)[-1]
            assert last["type"] == "run_failed" and last["error"] == run["error"]
        # the plan accepts new runs afterwards
        fin.solve(plan["id"])


def test_snapshot_reuse(fin):
    plan = fin.create()
    r1 = fin.solve(plan["id"])
    r2 = fin.solve(plan["id"])
    assert r1["plan_version_id"] == r2["plan_version_id"]
    doc = plan["plan"]
    doc["name"] = "Changed"
    fin.put(plan["id"], doc, 1)
    r3 = fin.solve(plan["id"])
    assert r3["plan_version_id"] != r1["plan_version_id"]
    assert _count(fin, FinancePlanVersionRow) == 2


def test_run_audit_has_ids_only(fin):
    plan = fin.instantiate(name="Very private")
    rid = fin.start_run(plan["id"], SLOW)["run_id"]
    fin.c.post(f"{FIN}/runs/{rid}/cancel")
    fin.wait(rid)
    with fin.ctx.db.read() as s:
        rows = s.scalars(select(AuditEventRow).where(AuditEventRow.entity_type == "finance_run")).all()
        got = {(r.action, tuple(sorted(r.details))) for r in rows}
        texts = [str(r.details) for r in rows]
    assert got == {("finance_run.created", ("kind", "plan_id", "plan_version_id")),
                   ("finance_run.cancelled", ("status_at_cancel",))}
    assert all("private" not in t for t in texts)


def test_engine_exception_marks_run_failed(fin, monkeypatch):
    def boom(plan, request, progress_cb=None, cancel_event=None):
        progress_cb(run_service.finance.FinanceProgress(stage="optimize", fraction=0.1, message="Optimizing"))
        raise RuntimeError("solver exploded")

    monkeypatch.setattr(run_service.finance, "run_plan", boom)
    plan = fin.create()
    run = fin.wait(fin.start_run(plan["id"])["run_id"])
    assert run["status"] == "failed" and run["error"] == "solver exploded" and run["result_id"] is None
    types = [e["type"] for e in fin.events(run["id"])]
    assert types[-3:] == ["progress", "stage_completed", "run_failed"] or types[-2:] == ["stage_completed",
                                                                                          "run_failed"]
    assert fin.events(run["id"])[-1]["error"] == "solver exploded"
    assert _count(fin, FinanceResultRow) == 0
    # the plan is free for a new run afterwards
    assert fin.c.post(f"{FIN}/plans/{plan['id']}/runs", json=FAST).status_code == 202
