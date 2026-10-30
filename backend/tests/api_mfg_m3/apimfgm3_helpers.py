"""M3 API test helpers on top of the M2 ones."""

from __future__ import annotations

import time
from typing import Any

from apimfgm2_helpers import A, Api, acc_app, im, make_app, sign_up  # noqa: F401


def wait_run(api: Api, run_id: str, timeout: float = 120) -> dict[str, Any]:
    t = time.monotonic()
    while True:
        r = api.get(f"/aps/runs/{run_id}")
        if r["status"] not in ("queued", "running"):
            return r
        if time.monotonic() - t > timeout:
            raise AssertionError(f"run {run_id} still {r['status']}")
        time.sleep(0.2)


def kavach_run(api: Api, **body: Any) -> dict[str, Any]:
    api.load("kavach")
    api.post("/mrp/runs", {"as_of": A}) if False else api.post("/mrp/runs", {})
    body.setdefault("improve_seconds", 0)
    run = api.post("/aps/runs", body, status=202)
    return wait_run(api, run["id"])
