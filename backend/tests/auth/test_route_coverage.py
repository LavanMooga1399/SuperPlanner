"""Q3-5 route coverage and Q3-6 cross-user matrix (PHASE2B 4.7 a/b, 4.8).

Both tests enumerate the operations from `app.openapi()` (black-box; walking `app.routes` does not see into
included routers in this FastAPI version), so a new endpoint is covered automatically - and the coverage test fails
until it is added to the access table in `route_table.py`.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from auth_helpers import API, acc_app, error, second_client, sign_up
from route_table import (PROTECTED, PUBLIC_ALLOWLIST, PUBLIC_REQUIRED, UNSAFE, fill_path, openapi_operations,
                         path_params)

FIN = f"{API}/finance"
FAST_FIN: dict[str, Any] = {"time_limit_seconds": 10, "simulation": {"n_paths": 200}, "compute_fixes": False,
                            "calibration_rounds": 0}
SOLVE = {"strategy": "heuristic", "time_limit_seconds": 2}
PLAN = {"name": "Money", "start_month": "2026-11",
        "incomes": [{"id": "salary", "name": "Salary", "amount": 80000}],
        "expenses": [{"id": "living", "name": "Living", "amount": 30000}],
        "goals": [{"id": "car", "name": "Car", "target_amount": 300000, "target_month": "2030-11"}]}


# ---------------------------------------------------------------- (a) coverage

def test_enumerated_operations_equal_the_access_table(db_url):
    ops = openapi_operations(acc_app(db_url))
    public = ops & PUBLIC_ALLOWLIST
    protected = ops - PUBLIC_ALLOWLIST
    assert PUBLIC_REQUIRED <= public
    assert protected == PROTECTED, {"new (add to route_table.py)": sorted(protected - PROTECTED),
                                    "missing": sorted(PROTECTED - protected)}
    assert len(PROTECTED) == 55   # B 4.8 rows 9-63 (56 pre-2b endpoints = these + GET /health)


def test_every_protected_operation_requires_a_session(db_url):
    app = acc_app(db_url)
    with TestClient(app) as c:
        ops = sorted(openapi_operations(app) - PUBLIC_ALLOWLIST)
        assert ops
        for method, path in ops:
            url = API + fill_path(path)
            attempts: list[dict[str, Any]] = [{}, {"json": {}}, {"json": [1, "x"]}, {"json": "text"}]
            if method in UNSAFE:
                attempts.append({"json": {"unexpected": [1, 2, 3]}, "headers": {"X-CSRF-Token": "x"}})
            for kw in attempts:
                r = c.request(method, url, **kw)
                err = error(r, 401, "AUTH_REQUIRED")
                assert err == {"code": "AUTH_REQUIRED", "message": "Please sign in to continue.", "details": {}}
            # Malformed JSON is rejected by FastAPI's body parser before any dependency runs (no lookup happens,
            # nothing about owned data is revealed): 422 json_invalid, or 401 if a pre-parse auth layer is added.
            r = c.request(method, url, content=b"{not json", headers={"content-type": "application/json"})
            if r.status_code != 401 and method in UNSAFE:
                assert r.status_code == 422 and r.json()["error"]["details"]["errors"][0]["type"] == "json_invalid"
            # a forged cookie is also 401, and is cleared
            other = second_client(app)
            other.cookies.set("sp_session", "forged")
            r = other.request(method, url, json={})
            error(r, 401, "AUTH_REQUIRED")
            assert "Max-Age=0" in r.headers.get("set-cookie", "")
        # public ones answer without a session
        assert c.get(f"{API}/health").status_code == 200
        assert c.get(f"{API}/auth/session").status_code == 200


# ---------------------------------------------------------------- (b) cross-user matrix

def _wait(c: TestClient, url: str, timeout: float = 90.0) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + timeout
    while True:
        r = c.get(url)
        assert r.status_code == 200, r.text
        run = r.json()
        if run["status"] not in ("queued", "running"):
            assert run["status"] == "completed", run
            return run
        assert time.monotonic() < deadline, run
        time.sleep(0.05)


def _world(c: TestClient, tag: str) -> dict[str, Any]:
    """One of each object: problem, solver run, schedule, finance plan, baseline run/result, what-if run/result."""
    pid = c.post(f"{API}/templates/manufacturing/instantiate",
                 json={"name": f"Plan {tag}", "parameters": {"jobs": 2}}).json()["id"]
    srun = c.post(f"{API}/problems/{pid}/solver-runs", json=SOLVE).json()["run_id"]
    _wait(c, f"{API}/solver-runs/{srun}")
    sched = c.get(f"{API}/problems/{pid}/schedules").json()["items"][0]["id"]
    r = c.post(f"{FIN}/plans", json={**PLAN, "name": f"Money {tag}"})
    assert r.status_code == 201, r.text
    fpid = r.json()["id"]
    frun = c.post(f"{FIN}/plans/{fpid}/runs", json=FAST_FIN).json()["run_id"]
    fres = _wait(c, f"{FIN}/runs/{frun}")["result_id"]
    r = c.post(f"{FIN}/plans/{fpid}/what-if", json={"changes": {"extra_monthly_savings": 2000}, "run": FAST_FIN})
    assert r.status_code == 202, r.text
    wrun = r.json()["run_id"]
    wres = _wait(c, f"{FIN}/runs/{wrun}")["result_id"]
    return {"problem_id": pid, "solver_run": srun, "schedule_id": sched, "plan_id": fpid, "fin_runs": [frun, wrun],
            "results": [fres, wres]}


def _id_sets(w: dict[str, Any]) -> list[dict[str, str]]:
    """Path-parameter values; finance runs/results are tried for the baseline and the what-if object."""
    return [{"problem_id": w["problem_id"], "schedule_id": w["schedule_id"], "plan_id": w["plan_id"],
             "result_id": res, "fin_run_id": run, "solver_run_id": w["solver_run"]}
            for run, res in zip(w["fin_runs"], w["results"])]


def _url(path: str, ids: dict[str, str]) -> str:
    run_key = "fin_run_id" if path.startswith("/finance/") else "solver_run_id"
    return API + fill_path(path, {**ids, "run_id": ids[run_key]})


def _unknown(ids: dict[str, str]) -> dict[str, str]:
    return {k: f"{v[:4]}{uuid.uuid4().hex}" for k, v in ids.items()}


def _snapshot(c: TestClient, w: dict[str, Any]) -> dict[str, Any]:
    urls = [f"{API}/problems/{w['problem_id']}", f"{API}/problems/{w['problem_id']}/solver-runs",
            f"{API}/problems/{w['problem_id']}/schedules", f"{API}/solver-runs/{w['solver_run']}",
            f"{API}/schedules/{w['schedule_id']}", f"{FIN}/plans/{w['plan_id']}", f"{FIN}/plans/{w['plan_id']}/runs",
            f"{FIN}/plans/{w['plan_id']}/results", f"{API}/problems", f"{FIN}/plans",
            *[f"{FIN}/runs/{r}" for r in w["fin_runs"]], *[f"{FIN}/results/{r}" for r in w["results"]]]
    out = {}
    for u in urls:
        r = c.get(u)
        assert r.status_code == 200, (u, r.text)
        out[u] = r.json()
    return out


def _bodies(a: TestClient, w: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Valid request bodies, so B's calls reach the owned lookup instead of failing body validation."""
    prob = a.get(f"{API}/problems/{w['problem_id']}").json()
    plan = a.get(f"{FIN}/plans/{w['plan_id']}").json()
    return {
        ("PUT", "/problems/{problem_id}"): {"json": copy.deepcopy(prob["problem"]),
                                           "headers": {"If-Match": f'"{prob["version"]}"'}},
        ("POST", "/problems/{problem_id}/solver-runs"): {"json": SOLVE},
        ("POST", "/schedules/{schedule_id}/approve"): {"json": {}},
        ("POST", "/schedules/{schedule_id}/replan"): {"json": {"cutoff": "2026-10-19T00:00:00+05:30"}},
        ("PUT", "/finance/plans/{plan_id}"): {"json": copy.deepcopy(plan["plan"]),
                                              "headers": {"If-Match": f'"{plan["version"]}"'}},
        ("POST", "/finance/plans/{plan_id}/runs"): {"json": FAST_FIN},
        ("POST", "/finance/plans/{plan_id}/what-if"): {"json": {"changes": {"extra_monthly_savings": 1}}},
        ("POST", "/finance/results/{result_id}/send-to-planner"): {"json": {}},
    }


OWNED_PARAMS = {"problem_id", "run_id", "schedule_id", "plan_id", "result_id"}


def _owned_ops(app) -> list[tuple[str, str]]:
    return sorted(op for op in openapi_operations(app) - PUBLIC_ALLOWLIST
                  if set(path_params(op[1])) & OWNED_PARAMS)


def _assert_same_404(rb, ru, foreign: str, unknown: str, what: str) -> None:
    error(rb, 404, "NOT_FOUND")
    error(ru, 404, "NOT_FOUND")
    assert rb.content == ru.content.replace(unknown.encode(), foreign.encode()), (what, rb.text, ru.text)


def test_user_b_gets_404_for_every_owned_endpoint(db_url):
    app = acc_app(db_url)
    with TestClient(app) as a:
        sign_up(a, "ana@example.com")
        b = second_client(app)
        sign_up(b, "ben@example.com")
        wa = _world(a, "A")
        wb = _world(b, "B")
        before = _snapshot(a, wa)
        bodies = _bodies(a, wa)
        ops = _owned_ops(app)
        assert len(ops) >= 30
        openapi = app.openapi()["paths"]
        tried = 0
        for method, path in ops:
            needs_body = "requestBody" in openapi[API + path][method.lower()]
            kw = bodies.get((method, path))
            if needs_body and kw is None:
                required = openapi[API + path][method.lower()]["requestBody"].get("required", False)
                assert not required, f"add a valid body for {method} {path} to _bodies()"
                kw = {}
            kw = kw or {}
            variants = ["", "?stream=false"] if path.endswith("/events") else [""]
            for ids in _id_sets(wa):
                unknown = _unknown(ids)
                for q in variants:
                    rb = b.request(method, _url(path, ids) + q, **copy.deepcopy(kw))
                    ru = b.request(method, _url(path, unknown) + q, **copy.deepcopy(kw))
                    # the id in the message is the first owned path parameter that was looked up
                    pairs = [(ids[k], unknown[k]) for k in ids if ids[k] in _url(path, ids)]
                    expected = ru.content
                    for real, fake in pairs:
                        expected = expected.replace(fake.encode(), real.encode())
                    error(rb, 404, "NOT_FOUND")
                    error(ru, 404, "NOT_FOUND")
                    assert rb.content == expected, (method, path, rb.text, ru.text)
                    tried += 1
        assert tried >= len(ops)

        # compare endpoints with one foreign id
        for base, own, foreign in ((f"{API}/schedules/compare", wb["schedule_id"], wa["schedule_id"]),
                                   (f"{FIN}/results/compare", wb["results"][0], wa["results"][0])):
            assert b.get(f"{base}?a={own}&b={own}").status_code == 200
            fake = f"{foreign[:4]}{uuid.uuid4().hex}"
            for qa, qb, qfake in ((own, foreign, (own, fake)), (foreign, own, (fake, own))):
                rb = b.get(f"{base}?a={qa}&b={qb}")
                ru = b.get(f"{base}?a={qfake[0]}&b={qfake[1]}")
                _assert_same_404(rb, ru, foreign, fake, base)

        # what-if on B's own plan with A's result as the base -> 404
        for res in wa["results"]:
            r = b.post(f"{FIN}/plans/{wb['plan_id']}/what-if",
                       json={"changes": {"extra_monthly_savings": 1}, "base_result_id": res})
            error(r, 404, "NOT_FOUND")

        # lists show only B's objects
        assert [p["id"] for p in b.get(f"{API}/problems").json()["items"]] == [wb["problem_id"]]
        assert [p["id"] for p in b.get(f"{FIN}/plans").json()["items"]] == [wb["plan_id"]]
        assert wa["problem_id"] in json.dumps(a.get(f"{API}/problems").json())
        assert wb["problem_id"] not in json.dumps(a.get(f"{API}/problems").json())
        assert wb["plan_id"] not in json.dumps(a.get(f"{FIN}/plans").json())

        # A's objects are unchanged
        assert _snapshot(a, wa) == before
