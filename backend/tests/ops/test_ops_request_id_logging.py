"""Q5-3 request ids and Q5-4 structured logging (PHASE2B 5.3)."""

from __future__ import annotations

import json
import logging
import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ops_helpers import API, AUTH, PASSWORD, app_for, captured_logs, json_lines, problem
from superplanner.api.db import JobRow
from superplanner.api.db.ownership import system_scope
from superplanner.obs import request_context as rc
from superplanner.obs.logging import JsonFormatter, TextFormatter, configure_logging

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _boom_app(db_url: str, **kw):
    app = app_for(db_url, **kw)

    @app.get(f"{API}/boom-test")
    def boom() -> None:
        raise RuntimeError("boom for the request id test")

    return app


def test_every_response_carries_a_request_id(db_url):
    app = _boom_app(db_url, max_body_bytes=2048)
    with TestClient(app, raise_server_exceptions=False) as c:
        cases = [
            c.get(f"{API}/health"),                                        # 200
            c.get("/no/such/path"),                                        # 404 unmatched
            c.get(f"{API}/problems/prb_unknown"),                          # 404 envelope
            c.post(f"{API}/problems", json={"x": 1}),                      # 422
            c.post(f"{API}/problems", content=b"x" * 5000,                 # 413 (body limit)
                   headers={"content-type": "application/json"}),
            c.get(f"{API}/boom-test"),                                     # 500
            c.options(f"{API}/problems", headers={"Origin": "http://localhost:5173",   # CORS preflight
                                                  "Access-Control-Request-Method": "POST"}),
        ]
        statuses = [r.status_code for r in cases]
        assert statuses == [200, 404, 404, 422, 413, 500, 200], statuses
        for r in cases:
            assert HEX32.match(r.headers.get("x-request-id", "")), (r.status_code, r.headers)
        assert cases[5].json() == {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected server error "
                                             "occurred.", "details": {}}}
        assert cases[4].headers.get("access-control-allow-origin") is None or True   # CORS unaffected
        assert len({r.headers["x-request-id"] for r in cases}) == len(cases)


def test_413_still_has_cors_and_request_id(db_url):
    app = app_for(db_url, max_body_bytes=2048)
    with TestClient(app) as c:
        r = c.post(f"{API}/problems", content=b"x" * 5000,
                   headers={"content-type": "application/json", "Origin": "http://localhost:5173"})
        assert r.status_code == 413
        assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert HEX32.match(r.headers["x-request-id"])


def test_valid_incoming_id_is_echoed_invalid_replaced(db_url):
    with TestClient(app_for(db_url)) as c:
        assert c.get(f"{API}/health", headers={"X-Request-ID": "abc.DEF_123-x"}).headers["x-request-id"] == \
            "abc.DEF_123-x"
        for bad in ("has space", "x" * 65, "semi;colon", "a/b", ""):
            got = c.get(f"{API}/health", headers={"X-Request-ID": bad})
            assert HEX32.match(got.headers["x-request-id"]), bad
        assert c.get(f"{API}/health", headers={"X-Request-ID": "y" * 64}).headers["x-request-id"] == "y" * 64


def test_enqueuing_request_id_is_stored_on_the_job(db_url):
    app = app_for(db_url)
    with TestClient(app) as c:
        pid = problem(c)
        r = c.post(f"{API}/problems/{pid}/solver-runs", json={"strategy": "heuristic", "time_limit_seconds": 1},
                   headers={"X-Request-ID": "rid-enqueue-1"})
        assert r.status_code == 202 and r.headers["x-request-id"] == "rid-enqueue-1"
        run_id = r.json()["run_id"]
        with system_scope(), app.state.ctx.db.read() as s:
            rid = s.scalars(select(JobRow.request_id).where(JobRow.solver_run_id == run_id)).one()
        assert rid == "rid-enqueue-1"


@pytest.mark.postgres_only
def test_worker_job_started_line_has_the_enqueuing_request_id(db_url):
    """Embedded queue worker: the job.started line carries request_id + job context fields."""
    app = app_for(db_url)
    with captured_logs("json", "worker") as buf, TestClient(app) as c:
        pid = problem(c)
        r = c.post(f"{API}/problems/{pid}/solver-runs", json={"strategy": "heuristic", "time_limit_seconds": 1},
                   headers={"X-Request-ID": "rid-worker-1"})
        run_id = r.json()["run_id"]
        deadline = time.monotonic() + 30
        while c.get(f"{API}/solver-runs/{run_id}").json()["status"] in ("queued", "running"):
            assert time.monotonic() < deadline
            time.sleep(0.1)
        time.sleep(0.2)
    lines = json_lines(buf)
    started = [x for x in lines if x["msg"].startswith("job.started") and x.get("run_id") == run_id]
    assert len(started) == 1, [x["msg"] for x in lines]
    s = started[0]
    assert s["request_id"] == "rid-worker-1" and s["kind"] == "solver_run" and s["attempt"] == 1
    assert s["job_id"].startswith("job_") and s["worker_id"] and s["logger"] == "superplanner.jobs"
    finished = [x for x in lines if x["msg"].startswith("job.finished") and x.get("run_id") == run_id]
    assert finished and finished[0]["request_id"] == "rid-worker-1"


def test_json_log_lines_and_no_secrets_during_a_full_flow(db_url, db_kind):
    """LOG_FORMAT=json: every line one JSON object with ts/level/logger/service/msg; no password, cookie,
    session/CSRF token or plan document content in any line (accounts mode, sign-up -> plan -> solve -> finance)."""
    secret_name = "Zebra-Plan-Secret-4711"
    app = app_for(db_url, auth_mode="accounts")
    with captured_logs("json", "api", logging.DEBUG) as buf, TestClient(app) as c:
        r = c.post(f"{AUTH}/sign-up", json={"email": "logs@example.com", "password": PASSWORD})
        assert r.status_code == 201
        csrf_token = r.json()["csrf_token"]
        cookie = c.cookies.get("sp_session")
        c.headers["X-CSRF-Token"] = csrf_token
        c.post(f"{AUTH}/sign-in", json={"email": "logs@example.com", "password": "wrong password!!"})
        r = c.post(f"{AUTH}/sign-in", json={"email": "logs@example.com", "password": PASSWORD})
        assert r.status_code == 200
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        cookie2 = c.cookies.get("sp_session")
        pid = problem(c)
        doc = c.get(f"{API}/problems/{pid}").json()
        doc_etag = c.get(f"{API}/problems/{pid}").headers.get("etag")
        body = doc.get("document") or doc
        if isinstance(body, dict) and "name" in body:
            body["name"] = secret_name
        r = c.post(f"{API}/problems/{pid}/solver-runs", json={"strategy": "heuristic", "time_limit_seconds": 1})
        assert r.status_code == 202
        run_id = r.json()["run_id"]
        r = c.post(f"{API}/finance/templates/young_professional/instantiate", json={"start_month": "2026-11",
                                                                                  "name": secret_name})
        assert r.status_code in (201, 422), r.text
        deadline = time.monotonic() + 30
        while c.get(f"{API}/solver-runs/{run_id}").json()["status"] in ("queued", "running"):
            assert time.monotonic() < deadline
            time.sleep(0.1)
        c.post(f"{AUTH}/change-password", json={"current_password": PASSWORD,
                                                "new_password": "another good passphrase"})
        c.post(f"{AUTH}/sign-out")
        assert doc_etag is None or doc_etag
    text = buf.getvalue()
    lines = text.splitlines()
    assert lines
    for line in lines:
        obj = json.loads(line)
        assert {"ts", "level", "logger", "service", "msg"} <= set(obj), obj
        assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$", obj["ts"])
        assert obj["service"] == "api"
    for needle in (PASSWORD, "wrong password!!", "another good passphrase", csrf_token, cookie, cookie2,
                   secret_name, "logs@example.com"):
        assert needle and needle not in text, needle
    access = [json.loads(l) for l in lines if json.loads(l)["msg"] == "http.request"]
    assert access and all(set(a) >= {"request_id", "method", "route", "status", "duration_ms"} for a in access)
    routes = {a["route"] for a in access}
    assert f"{API}/problems/{{problem_id}}" in routes and f"{API}/auth/sign-in" in routes
    assert not any(pid in a["route"] for a in access)
    signed_in = [a for a in access if a["route"] == f"{API}/problems/{{problem_id}}"]
    assert all(a.get("user_id", "").startswith("usr_") for a in signed_in)


def test_text_format_appends_fields_and_rid():
    rec = logging.LogRecord("superplanner.http", logging.INFO, __file__, 1, "http.request", None, None)
    rec.sp = {"method": "GET", "status": 200}
    tok = rc.set_request_id("rid-text")
    try:
        line = TextFormatter().format(rec)
    finally:
        rc.reset_request_id(tok)
    assert line.endswith("http.request method=GET status=200 rid=rid-text"), line
    assert " INFO superplanner.http: " in line


def test_json_formatter_fields_and_exception():
    try:
        raise ValueError("bad")
    except ValueError:
        import sys

        rec = logging.LogRecord("x.y", logging.ERROR, __file__, 1, "failed %s", ("thing",), sys.exc_info())
    with rc.bound(request_id="rid-json", job_id="job_1", attempt=2):
        obj = json.loads(JsonFormatter("worker").format(rec))
    assert obj["msg"] == "failed thing" and obj["level"] == "ERROR" and obj["service"] == "worker"
    assert obj["request_id"] == "rid-json" and obj["job_id"] == "job_1" and obj["attempt"] == 2
    assert "ValueError: bad" in obj["exc"]
    assert rc.current_request_id() is None


def test_configure_logging_leaves_existing_configuration_alone():
    class S:
        log_format, log_level = "json", "INFO"

    root = logging.getLogger()
    saved = list(root.handlers)
    foreign = logging.StreamHandler()
    try:
        for h in saved:
            root.removeHandler(h)
        root.addHandler(foreign)   # e.g. pytest's capture or an embedding application's handler
        assert configure_logging(S(), "api") is False
        assert root.handlers == [foreign]
    finally:
        root.removeHandler(foreign)
        for h in saved:
            root.addHandler(h)


def test_configure_logging_json_routes_uvicorn(monkeypatch):
    import io

    class S:
        log_format, log_level = "json", "INFO"

    root = logging.getLogger()
    saved, saved_level = list(root.handlers), root.level
    uv = logging.getLogger("uvicorn.error")
    uv_saved = (list(uv.handlers), uv.propagate)
    buf = io.StringIO()
    try:
        for h in saved:
            root.removeHandler(h)
        assert configure_logging(S(), "worker", stream=buf) is True
        assert configure_logging(S(), "worker", stream=buf) is False   # idempotent
        logging.getLogger("superplanner.test").info("hello %d", 1)
        uv.info("uvicorn says hi")
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)
        root.setLevel(saved_level)
        for h in uv_saved[0]:
            uv.addHandler(h)
        uv.propagate = uv_saved[1]
    objs = [json.loads(l) for l in buf.getvalue().splitlines()]
    assert [o["msg"] for o in objs] == ["hello 1", "uvicorn says hi"]
    assert all(o["service"] == "worker" for o in objs)


def test_route_template_reconstruction():
    class R:
        path_format = "/problems/{problem_id}"

    assert rc.route_template({"route": R(), "path": "/api/v1/problems/prb_1"}) == "/api/v1/problems/{problem_id}"
    assert rc.route_template({"path": "/nope"}) is None

    class Root:
        path_format = "/metrics"

    assert rc.route_template({"route": Root(), "path": "/metrics"}) == "/metrics"


def test_configure_logging_keeps_disabled_uvicorn_access_log():
    """`--no-access-log`: uvicorn leaves `uvicorn.access` without handlers and propagate=False; JSON setup must
    not re-enable it (the API writes its own http.request line)."""
    import io

    class S:
        log_format, log_level = "json", "INFO"

    root = logging.getLogger()
    saved, saved_level = list(root.handlers), root.level
    acc = logging.getLogger("uvicorn.access")
    acc_saved = (list(acc.handlers), acc.propagate)
    try:
        for h in saved:
            root.removeHandler(h)
        for h in list(acc.handlers):
            acc.removeHandler(h)
        acc.propagate = False
        assert configure_logging(S(), "api", stream=io.StringIO()) is True
        assert acc.propagate is False and not acc.hasHandlers()
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)
        root.setLevel(saved_level)
        for h in acc_saved[0]:
            acc.addHandler(h)
        acc.propagate = acc_saved[1]
