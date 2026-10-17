"""Tiny polling helper for solver and finance runs (kept local so no other test package is imported)."""

from __future__ import annotations

import time
from typing import Any

API = "/api/v1"


def wait_run(client, run_id: str, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        run = client.get(f"{API}/solver-runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        if time.monotonic() > deadline:
            raise AssertionError(f"run {run_id} still {run['status']}")
        time.sleep(0.1)


def wait_finance_run(client, run_id: str, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        run = client.get(f"{API}/finance/runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        if time.monotonic() > deadline:
            raise AssertionError(f"finance run {run_id} still {run['status']}")
        time.sleep(0.2)
