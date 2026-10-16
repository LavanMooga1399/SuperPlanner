"""Shared helpers for the F2 finance API tests (own `make_app`, see FINANCE.md 22)."""

from __future__ import annotations

import copy
import time
from typing import Any

from fastapi.testclient import TestClient

from superplanner.api.config import Settings
from superplanner.api.main import create_app

API = "/api/v1"
FIN = f"{API}/finance"
START = "2026-11"
# Fast run settings for tests (the engine itself is covered by tests/finance).
FAST: dict[str, Any] = {"time_limit_seconds": 10, "simulation": {"n_paths": 200}, "compute_fixes": False,
                        "calibration_rounds": 0}
# A run that takes several seconds, used for cancel / race tests.
SLOW: dict[str, Any] = {"time_limit_seconds": 120, "simulation": {"n_paths": 10000}, "compute_fixes": True,
                        "calibration_rounds": 4}


def make_app(db_url: str, **overrides: Any):
    return create_app(Settings(database_url=db_url, **overrides))


def minimal_plan(name: str = "Test plan", **extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "name": name, "start_month": START,
        "incomes": [{"id": "salary", "name": "Salary", "amount": 80000}],
        "expenses": [{"id": "living", "name": "Living", "amount": 30000}],
        "goals": [{"id": "car", "name": "Car", "target_amount": 300000, "target_month": "2030-11"}],
    }
    doc.update(extra)
    return doc


class FinApi:
    def __init__(self, client: TestClient):
        self.c = client

    @property
    def ctx(self):
        return self.c.app.state.ctx

    def instantiate(self, template: str = "young_professional", **body: Any) -> dict[str, Any]:
        body.setdefault("start_month", START)
        r = self.c.post(f"{FIN}/templates/{template}/instantiate", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    def create(self, doc: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self.c.post(f"{FIN}/plans", json=doc or minimal_plan())
        assert r.status_code == 201, r.text
        return r.json()

    def put(self, plan_id: str, doc: dict[str, Any], version: int | str | None) -> Any:
        headers = {} if version is None else {"If-Match": f'"{version}"' if isinstance(version, int) else version}
        return self.c.put(f"{FIN}/plans/{plan_id}", json=doc, headers=headers)

    def start_run(self, plan_id: str, req: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self.c.post(f"{FIN}/plans/{plan_id}/runs", json=copy.deepcopy(FAST if req is None else req))
        assert r.status_code == 202, r.text
        return r.json()

    def what_if(self, plan_id: str, changes: dict[str, Any], **extra: Any) -> Any:
        body = {"changes": changes, "run": copy.deepcopy(FAST)}
        body.update(extra)
        return self.c.post(f"{FIN}/plans/{plan_id}/what-if", json=body)

    def run(self, run_id: str) -> dict[str, Any]:
        r = self.c.get(f"{FIN}/runs/{run_id}")
        assert r.status_code == 200, r.text
        return r.json()

    def wait(self, run_id: str, timeout: float = 60.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = self.run(run_id)
            if run["status"] not in ("queued", "running"):
                return run
            if time.monotonic() > deadline:
                raise AssertionError(f"finance run {run_id} still {run['status']} after {timeout}s")
            time.sleep(0.05)

    def wait_status(self, run_id: str, status: str, timeout: float = 20.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = self.run(run_id)
            if run["status"] == status:
                return run
            if time.monotonic() > deadline:
                raise AssertionError(f"finance run {run_id} is {run['status']}, expected {status}")
            time.sleep(0.02)

    def wait_event(self, run_id: str, type_: str, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while not any(e["type"] == type_ for e in self.events(run_id)):
            if time.monotonic() > deadline:
                raise AssertionError(f"no {type_} event for {run_id}")
            time.sleep(0.02)

    def solve(self, plan_id: str, req: dict[str, Any] | None = None) -> dict[str, Any]:
        run = self.wait(self.start_run(plan_id, req)["run_id"])
        assert run["status"] == "completed", run
        return run

    def events(self, run_id: str) -> list[dict[str, Any]]:
        r = self.c.get(f"{FIN}/runs/{run_id}/events?stream=false")
        assert r.status_code == 200, r.text
        return r.json()["items"]

    def result(self, result_id: str) -> dict[str, Any]:
        r = self.c.get(f"{FIN}/results/{result_id}")
        assert r.status_code == 200, r.text
        return r.json()

    def worker_done(self, run_id: str, timeout: float = 30.0) -> None:
        """Wait until the executor no longer holds the run's job."""
        fut = self.ctx.executor.future(run_id)
        if fut is not None:
            fut.result(timeout=timeout)


def assert_error(resp, status: int, code: str | None = None) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"}, body
    err = body["error"]
    assert set(err) == {"code", "message", "details"}
    assert isinstance(err["message"], str) and err["message"]
    if code is not None:
        assert err["code"] == code, err
    return err


def sse_frames(text: str) -> list[dict[str, str]]:
    frames = []
    for block in text.strip().split("\n\n"):
        if not block or block.startswith(":"):
            continue
        f: dict[str, str] = {}
        for line in block.split("\n"):
            if ":" in line and not line.startswith(":"):
                k, v = line.split(":", 1)
                f[k] = v.strip()
        frames.append(f)
    return frames
