"""`Idempotency-Key` on the four run-creating endpoints (PHASE2B 2.8; plan Q2-10). Both dialects."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from jobs_helpers import API, FAST_FIN, FIN, fin_plan, make_app, problem, wait_fin, wait_solver
from superplanner import finance as finance_module
from superplanner.api.auth.models import UserRow
from superplanner.api.db import JobRow
from superplanner.api.db.ownership import owner_scope, system_scope
from superplanner.api.finance import run_service as finance_run_service
from superplanner.api.finance import service as finance_service
from superplanner.jobs import idempotency

HEADER = "Idempotency-Key"


def _post(c, url, body, key):
    return c.post(url, json=body, headers={HEADER: key})


def test_replay_and_mismatch_on_all_four_endpoints(db_url):
    with TestClient(make_app(db_url)) as c:
        pid = problem(c)
        plan = fin_plan(c)
        solver_body = {"strategy": "heuristic", "time_limit_seconds": 1}
        cases = [(f"{API}/problems/{pid}/solver-runs", solver_body, {**solver_body, "seed": 7}),
                 (f"{FIN}/plans/{plan}/runs", FAST_FIN, {**FAST_FIN, "seed": 9}),
                 (f"{FIN}/plans/{plan}/what-if", {"changes": {"label": "Raise", "extra_monthly_savings": 1000},
                                                  "run": FAST_FIN},
                  {"changes": {"label": "Other", "extra_monthly_savings": 2000}, "run": FAST_FIN})]
        first_solver = None
        for i, (url, body, other) in enumerate(cases):
            key = f"key-{i}.a:b_c"
            r1 = _post(c, url, body, key)
            assert r1.status_code == 202, r1.text
            assert "idempotent-replayed" not in {k.lower() for k in r1.headers}
            rid = r1.json()["run_id"]
            r2 = _post(c, url, body, key)                      # same key + same body
            assert r2.status_code == 202, r2.text
            assert r2.headers["Idempotent-Replayed"] == "true"
            assert r2.json()["run_id"] == rid
            assert set(r2.json()) == set(r1.json())
            r3 = _post(c, url, other, key)                     # same key + other body
            assert r3.status_code == 422, r3.text
            assert r3.json() == {"error": {"code": "IDEMPOTENCY_KEY_MISMATCH",
                                           "message": "This Idempotency-Key was used for a different request.",
                                           "details": {}}}
            if "solver-runs" in url:
                first_solver = rid
                wait_solver(c, rid)
            else:
                wait_fin(c, rid)
            # a replay after completion still answers with the original run (current status)
            r4 = _post(c, url, body, key)
            assert r4.status_code == 202 and r4.json()["run_id"] == rid and r4.json()["status"] == "completed"
        # replan
        sched = c.get(f"{API}/solver-runs/{first_solver}").json()["primary_schedule_id"]
        body = {"cutoff": "2026-10-20T08:00:00+05:30", "run": {"strategy": "heuristic", "time_limit_seconds": 1}}
        r1 = _post(c, f"{API}/schedules/{sched}/replan", body, "replan-1")
        assert r1.status_code == 202, r1.text
        r2 = _post(c, f"{API}/schedules/{sched}/replan", body, "replan-1")
        assert r2.status_code == 202 and r2.headers["Idempotent-Replayed"] == "true"
        assert r2.json()["run_id"] == r1.json()["run_id"]
        assert r2.json()["source_schedule_id"] == sched and "problem_version" in r2.json()
        # the same key on another endpoint is another request
        r3 = _post(c, f"{API}/problems/{pid}/solver-runs", body["run"], "replan-1")
        assert r3.status_code == 422 and r3.json()["error"]["code"] == "IDEMPOTENCY_KEY_MISMATCH"
        wait_solver(c, r1.json()["run_id"])
        # without the header: unchanged behaviour (a new run each time)
        a = c.post(f"{FIN}/plans/{plan}/runs", json=FAST_FIN).json()["run_id"]
        wait_fin(c, a)
        b = c.post(f"{FIN}/plans/{plan}/runs", json=FAST_FIN).json()["run_id"]
        assert a != b
        wait_fin(c, b)


@pytest.mark.parametrize("key", ["", "has space", "x" * 129, "bad/slash", "ünï"])
def test_invalid_key_format_is_422(db_url, key):
    with TestClient(make_app(db_url)) as c:
        plan = fin_plan(c)
        r = c.post(f"{FIN}/plans/{plan}/runs", json=FAST_FIN, headers={HEADER: key.encode("utf-8")})
        assert r.status_code == 422, r.text
        err = r.json()["error"]
        assert err["code"] == "VALIDATION_ERROR"
        assert err["details"]["errors"][0]["loc"] == ["header", "idempotency-key"]
        assert c.get(f"{FIN}/plans/{plan}/runs").json()["items"] == []


def test_concurrent_identical_requests_create_one_run(db_url, monkeypatch):
    with TestClient(make_app(db_url)) as c:
        plan = fin_plan(c)
        url = f"{FIN}/plans/{plan}/runs"
        results: list = []
        lock = threading.Lock()
        barrier = threading.Barrier(10)

        def call():
            barrier.wait()
            r = c.post(url, json=FAST_FIN, headers={HEADER: "same-key"})
            with lock:
                results.append((r.status_code, r.json().get("run_id"), r.headers.get("Idempotent-Replayed")))

        threads = [threading.Thread(target=call) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        assert len(results) == 10
        assert {s for s, _, _ in results} == {202}, results
        assert len({rid for _, rid, _ in results}) == 1
        assert sum(1 for _, _, h in results if h == "true") == 9
        rid = results[0][1]
        wait_fin(c, rid)
        items = c.get(url).json()["items"]
        assert [i["id"] for i in items] == [rid]


def test_keys_are_per_owner(db_url):
    with TestClient(make_app(db_url)) as c:
        ctx = c.app.state.ctx
        plan = fin_plan(c)
        r = c.post(f"{FIN}/plans/{plan}/runs", json=FAST_FIN, headers={HEADER: "shared"})
        assert r.status_code == 202
        rid_a = r.json()["run_id"]
        wait_fin(c, rid_a)
        with system_scope(), ctx.db.write() as s:
            s.add(UserRow(id="usr_b", email="b@example.com", display_name="B"))
        req = finance_module.FinanceRunRequest.model_validate(FAST_FIN)
        idem = idempotency.Idempotency("shared", idempotency.request_hash("finance_run", {"plan_id": plan},
                                                                          req.model_dump(mode="json")))
        with owner_scope("usr_b"):
            with ctx.db.read() as s:   # B's lookup does not see A's key
                idempotency.lookup(s, idem, 24, finance_run_service.created_from_job)
            doc = finance_module.FinancePlan.model_validate(
                {"name": "B plan", "start_month": "2026-11",
                 "incomes": [{"id": "salary", "name": "Salary", "amount": 80000}],
                 "expenses": [{"id": "living", "name": "Living", "amount": 30000}],
                 "goals": [{"id": "car", "name": "Car", "target_amount": 300000, "target_month": "2030-11"}]})
            plan_b = finance_service.create_plan(ctx, doc)["id"]
            out = finance_run_service.create_run(ctx, plan_b, req, idempotency.Idempotency("shared", "h" * 64))
            rid_b = out["run_id"]
            assert rid_b != rid_a
        ctx.jobs.wait_idle(rid_b)
        with system_scope(), ctx.db.read() as s:
            owners = sorted((j.owner_id, j.idempotency_key) for j in s.scalars(select(JobRow)).all())
        assert owners == [("usr_b", "shared"), ("usr_local", "shared")]


def test_expired_key_is_released(db_url):
    with TestClient(make_app(db_url)) as c:
        ctx = c.app.state.ctx
        plan = fin_plan(c)
        url = f"{FIN}/plans/{plan}/runs"
        first = c.post(url, json=FAST_FIN, headers={HEADER: "old"}).json()["run_id"]
        wait_fin(c, first)
        from datetime import timedelta

        from superplanner.api.db import utcnow

        with system_scope(), ctx.db.write() as s:
            job = s.scalars(select(JobRow).where(JobRow.finance_run_id == first)).one()
            job.created_at = utcnow() - timedelta(hours=25)
        r = c.post(url, json={**FAST_FIN, "seed": 3}, headers={HEADER: "old"})   # other body, but key expired
        assert r.status_code == 202, r.text
        assert r.json()["run_id"] != first and "Idempotent-Replayed" not in r.headers
        wait_fin(c, r.json()["run_id"])
        with system_scope(), ctx.db.read() as s:
            assert s.scalars(select(JobRow).where(JobRow.finance_run_id == first)).one().idempotency_key is None
