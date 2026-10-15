"""Shared helpers for the WP2 API tests (imported by conftest and the test modules)."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from superplanner.api.config import Settings
from superplanner.api.main import create_app

API = "/api/v1"
START = "2026-10-19"
OFFSET = "+05:30"


def make_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, **overrides))


class Api:
    """Small helpers shared by the API tests."""

    def __init__(self, client: TestClient):
        self.c = client

    def instantiate(self, template: str = "manufacturing", **params: Any) -> dict[str, Any]:
        r = self.c.post(f"{API}/templates/{template}/instantiate",
                        json={"start_date": START, "utc_offset": OFFSET, "parameters": params})
        assert r.status_code == 201, r.text
        return r.json()

    def put(self, problem_id: str, doc: dict[str, Any], version: int | str | None) -> Any:
        headers = {} if version is None else {"If-Match": f'"{version}"' if isinstance(version, int) else version}
        return self.c.put(f"{API}/problems/{problem_id}", json=doc, headers=headers)

    def start_run(self, problem_id: str, **req: Any) -> dict[str, Any]:
        req.setdefault("time_limit_seconds", 2)
        r = self.c.post(f"{API}/problems/{problem_id}/solver-runs", json=req)
        assert r.status_code == 202, r.text
        return r.json()

    def wait(self, run_id: str, timeout: float = 30.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = self.c.get(f"{API}/solver-runs/{run_id}").json()
            if run["status"] not in ("queued", "running"):
                return run
            if time.monotonic() > deadline:
                raise AssertionError(f"run {run_id} still {run['status']} after {timeout}s")
            time.sleep(0.1)

    def wait_status(self, run_id: str, status: str, timeout: float = 10.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = self.c.get(f"{API}/solver-runs/{run_id}").json()
            if run["status"] == status:
                return run
            if time.monotonic() > deadline:
                raise AssertionError(f"run {run_id} is {run['status']}, expected {status}")
            time.sleep(0.05)

    def solve(self, problem_id: str, **req: Any) -> dict[str, Any]:
        run = self.wait(self.start_run(problem_id, **req)["run_id"])
        assert run["status"] == "completed", run
        return run

    def schedule(self, schedule_id: str) -> dict[str, Any]:
        r = self.c.get(f"{API}/schedules/{schedule_id}")
        assert r.status_code == 200, r.text
        return r.json()

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return self.c.get(f"{API}/solver-runs/{run_id}/events?stream=false").json()["items"]


def assert_error(resp, status: int, code: str | None = None) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message", "details"}, body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    if code is not None:
        assert body["error"]["code"] == code, body
    return body["error"]


def small_problem(**extra: Any) -> dict[str, Any]:
    """Two tasks on one machine, 24/7 calendar."""
    doc = {
        "name": "Small", "horizon_start": "2026-10-19T00:00:00+05:30", "horizon_days": 7,
        "tasks": [
            {"id": "A", "name": "Task A", "duration_minutes": 60, "requirements": [{"alternatives": ["M1"]}]},
            {"id": "B", "name": "Task B", "duration_minutes": 30, "requirements": [{"alternatives": ["M1"]}]},
        ],
        "resources": [{"id": "M1", "name": "Machine 1"}],
        "dependencies": [{"predecessor": "A", "successor": "B"}],
    }
    doc.update(extra)
    return doc
