"""Q5-5 Prometheus metrics (PHASE2B 5.4): API /metrics and the worker's metrics server."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from fastapi.testclient import TestClient

from ops_helpers import API, AUTH, BACKEND, PASSWORD, app_for, problem
from superplanner.obs import http_metrics

API_METRICS = ["sp_http_requests_total", "sp_http_request_duration_seconds", "sp_sse_streams_active",
               "sp_jobs_queue_depth", "sp_jobs_oldest_queued_age_seconds", "sp_workers_alive",
               "sp_auth_events_total"]
JOB_METRICS = ["sp_jobs_total", "sp_job_duration_seconds", "sp_job_queue_wait_seconds", "sp_job_failures_total",
               "sp_worker_slots", "sp_worker_busy_slots"]


def _sample(text: str, name: str, **labels: str) -> float | None:
    for line in text.splitlines():
        if line.startswith("#") or not line.startswith(name):
            continue
        head, _, value = line.rpartition(" ")
        if head.split("{", 1)[0] != name:
            continue
        if all(f'{k}="{v}"' in head for k, v in labels.items()):
            return float(value)
    return None


def test_metrics_exposes_every_metric_with_templates(db_url):
    http_metrics._cache.clear()
    app = app_for(db_url)
    with TestClient(app) as c:
        pid = problem(c)
        assert c.get(f"{API}/problems/{pid}").status_code == 200
        c.get(f"{API}/problems/prb_does_not_exist")
        c.get("/totally/unknown")
        r = c.get("/metrics")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
        text = r.text
    for name in API_METRICS + JOB_METRICS:
        assert f"# TYPE {name}" in text or f"# HELP {name}" in text, name
    assert _sample(text, "sp_http_requests_total", method="GET", route=f"{API}/problems/{{problem_id}}",
                   status="200") >= 1
    assert _sample(text, "sp_http_requests_total", method="GET", route=f"{API}/problems/{{problem_id}}",
                   status="404") >= 1
    assert _sample(text, "sp_http_requests_total", method="GET", route="unmatched", status="404") >= 1
    assert _sample(text, "sp_http_request_duration_seconds_count", method="POST",
                   route=f"{API}/templates/{{template_id}}/instantiate") >= 1
    assert pid not in text and "prb_does_not_exist" not in text and "/totally/unknown" not in text
    for kind in ("solver_run", "finance_run"):
        for st in ("queued", "running"):
            assert _sample(text, "sp_jobs_queue_depth", kind=kind, status=st) is not None
        assert _sample(text, "sp_jobs_oldest_queued_age_seconds", kind=kind) is not None
    assert _sample(text, "sp_workers_alive") is not None
    assert _sample(text, "sp_sse_streams_active", kind="solver") is not None


def test_metrics_not_in_openapi_and_disabled_switch(db_url):
    app = app_for(db_url)
    assert "/metrics" not in app.openapi()["paths"]
    with TestClient(app_for(db_url, metrics_enabled=False)) as c:
        assert c.get("/metrics").status_code == 404


def test_metrics_token(db_url):
    with TestClient(app_for(db_url, metrics_token="s3cret-token")) as c:
        r = c.get("/metrics")
        assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_REQUIRED"
        assert r.headers["www-authenticate"] == "Bearer"
        assert c.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/metrics", headers={"Authorization": "Basic s3cret-token"}).status_code == 401
        r = c.get("/metrics", headers={"Authorization": "Bearer s3cret-token"})
        assert r.status_code == 200 and "sp_http_requests_total" in r.text


def test_metrics_in_accounts_mode_no_ownership_violation(db_url):
    """The queue collector runs in system scope inside a request without a user (R9)."""
    http_metrics._cache.clear()
    with TestClient(app_for(db_url, auth_mode="accounts")) as c:
        r = c.get("/metrics")
        assert r.status_code == 200, r.text
        assert _sample(r.text, "sp_jobs_queue_depth", kind="solver_run", status="queued") is not None


def test_auth_event_metrics(db_url):
    def val(text: str, ev: str) -> float:
        return _sample(text, "sp_auth_events_total", event=ev) or 0.0

    with TestClient(app_for(db_url, auth_mode="accounts")) as c:
        before = c.get("/metrics").text
        assert c.post(f"{AUTH}/sign-up", json={"email": "m@example.com", "password": PASSWORD}).status_code == 201
        assert c.post(f"{AUTH}/sign-in", json={"email": "m@example.com", "password": "nope nope nope"}
                      ).status_code == 401
        r = c.post(f"{AUTH}/sign-in", json={"email": "m@example.com", "password": PASSWORD})
        assert r.status_code == 200
        # unsafe request without the CSRF token -> 403 CSRF_FAILED
        assert c.post(f"{API}/problems", json={}).status_code == 403
        after = c.get("/metrics").text
    assert val(after, "sign_up") - val(before, "sign_up") == 1
    assert val(after, "sign_in_failed") - val(before, "sign_in_failed") == 1
    assert val(after, "sign_in_ok") - val(before, "sign_in_ok") == 1
    assert val(after, "csrf_failed") - val(before, "csrf_failed") == 1


def test_auth_event_mapping():
    ev = http_metrics.auth_event
    assert ev("POST", f"{API}/auth/sign-in", 429) == "rate_limited"
    assert ev("POST", f"{API}/auth/sign-up", 201) == "sign_up"
    assert ev("POST", f"{API}/auth/sign-up", 409) is None
    assert ev("POST", f"{API}/problems", 403, b'{"error":{"code":"FORBIDDEN"}}') is None
    assert ev("DELETE", f"{API}/problems/{{problem_id}}", 403, b'{"error":{"code":"CSRF_FAILED"}}') == "csrf_failed"


def test_sse_gauge_and_duration_exclusion(db_url, db_kind):
    """An SSE stream is counted in sp_http_requests_total but not in the duration histogram."""
    http_metrics._cache.clear()
    with TestClient(app_for(db_url)) as c:
        pid = problem(c)
        r = c.post(f"{API}/problems/{pid}/solver-runs", json={"strategy": "heuristic", "time_limit_seconds": 1})
        run_id = r.json()["run_id"]
        deadline = time.monotonic() + 30
        while c.get(f"{API}/solver-runs/{run_id}").json()["status"] in ("queued", "running"):
            assert time.monotonic() < deadline
            time.sleep(0.1)
        with c.stream("GET", f"{API}/solver-runs/{run_id}/events") as s:
            assert s.headers["content-type"].startswith("text/event-stream")
            for _ in s.iter_lines():
                pass
        text = c.get("/metrics").text
    route = f"{API}/solver-runs/{{run_id}}/events"
    assert _sample(text, "sp_http_requests_total", method="GET", route=route, status="200") >= 1
    assert _sample(text, "sp_http_request_duration_seconds_count", method="GET", route=route) is None
    assert _sample(text, "sp_sse_streams_active", kind="solver") == 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.postgres_only
def test_worker_metrics_server_and_json_logs(db_url):
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": db_url, "JOB_BACKEND": "queue", "LOG_FORMAT": "json",
           "WORKER_SHUTDOWN_GRACE_SECONDS": "1"}
    p = subprocess.Popen([sys.executable, "-m", "superplanner.worker", "--concurrency", "1", "--id", "ops-metrics-w",
                          "--metrics-port", str(port)], cwd=BACKEND, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 30
        text = None
        while time.monotonic() < deadline:
            try:
                text = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2).read().decode()
                break
            except Exception:
                assert p.poll() is None, p.stderr.read() if p.stderr else ""
                time.sleep(0.2)
        assert text is not None
        for name in JOB_METRICS:
            assert f"# HELP {name}" in text, name
        assert _sample(text, "sp_worker_slots") == 1.0
    finally:
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=30)
    assert p.returncode == 0, err
    lines = [l for l in err.splitlines() if l.strip()]
    assert lines
    for line in lines:
        obj = json.loads(line)
        assert obj["service"] == "worker" and {"ts", "level", "logger", "msg"} <= set(obj)
    msgs = [json.loads(l)["msg"] for l in lines]
    assert any(m.startswith("worker.started") for m in msgs) and any(m.startswith("worker.stopped") for m in msgs)
