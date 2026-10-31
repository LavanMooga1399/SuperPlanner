"""M4 performance (M4-DESIGN 14 FP1, FP3, FP5-FP8) on the Kavach sample. `-m slow`; prints the measurements."""

from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime, timedelta

import pytest

from apimfgm3_helpers import wait_run
from apimfgm4_helpers import cid

pytestmark = pytest.mark.slow


def _t(fn):
    t = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t) * 1000


def p95(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.95 * len(xs)))]


def test_m4_perf_kavach(api, capsys):
    api.load("kavach")
    pl = api.get("/plant")
    loc = next(x for x in api.get("/locations")["items"] if x["kind"] == "stores")
    body = {k: v for k, v in pl.items() if k in __import__("apimfgm4_helpers").PLANT_FIELDS}
    body["wo_receipt_location_id"] = loc["id"]
    api.put("/plant", body, pl["row_version"])
    api.post("/mrp/runs", {})
    run, ms_run = _t(lambda: wait_run(api, api.post("/aps/runs", {"improve_seconds": 0}, status=202)["id"]))
    assert run["status"] == "completed"
    api.post(f"/aps/runs/{run['id']}/publish", {}, status=200, version=run["row_version"], headers={})
    out = {"FP5_construct_ms": ms_run}
    wos = [w for w in api.get("/work-orders", limit=200)["items"] if w["status"] in ("released", "in_progress")]
    # FP1: start / pause / resume / report / complete on operations of released WOs
    simple, full = [], []
    t0 = datetime.now(UTC) - timedelta(hours=20)
    n = 0
    for w in wos:
        ops = api.get(f"/work-orders/{w['id']}/operations")["items"]
        for o in ops:
            if o["status"] not in ("ready", "pending") or n >= 25:
                continue
            d = api.get(f"/floor/operations/{o['id']}")
            if not d["eligible_lines"]:
                continue
            line = d["eligible_lines"][0]["id"]
            at = (t0 + timedelta(minutes=n * 10)).isoformat()

            def post(et, **kw):
                return api.req("POST", "/floor/events", None, json={"client_event_id": cid(), "wo_operation_id":
                                                                      o["id"], "event_type": et, **kw})
            r, ms = _t(lambda: post("start", line_id=line, event_at=at))
            if r.status_code != 201:
                continue
            simple.append(ms)
            _r, ms = _t(lambda: post("pause", reason_code="BREAK"))
            simple.append(ms)
            _r, ms = _t(lambda: post("resume"))
            simple.append(ms)
            q = max(0, d["operation"]["qty_available"])
            _r, ms = _t(lambda: post("complete", qty_good=q, force={"reason": "perf"}))
            full.append(ms)
            n += 1
    out["FP1_simple_p95_ms"], out["FP1_complete_p95_ms"], out["FP1_n"] = p95(simple), p95(full), len(full)
    out["FP1_complete_median_ms"] = statistics.median(full)
    out["FP1_all"] = [round(x) for x in full]
    line = api.get("/lines", limit=200)["items"][0]["id"]
    qs = [_t(lambda: api.get("/floor/queue", line_id=line))[1] for _ in range(10)]
    sc = [_t(lambda: api.get("/floor/scan", code=wos[0]["number"]))[1] for _ in range(10)]
    out["FP3_queue_p95_ms"], out["FP3_scan_p95_ms"] = p95(qs), p95(sc)
    _k, ms1 = _t(lambda: api.get("/kpis"))
    _k, ms2 = _t(lambda: api.get("/kpis"))
    lines = api.get("/lines", limit=200)["items"]
    per_line = [_t(lambda ln=ln: api.get("/kpis", dim="line", dim_id=ln["id"]))[1] for ln in lines[:5]]
    out["FP7_first_ms"], out["FP7_cached_ms"], out["FP7_line_cached_ms"] = ms1, ms2, statistics.mean(per_line)
    nt = [_t(lambda: api.get("/notifications", unacked=True))[1] for _ in range(10)]
    out["notifications_p95_ms"] = p95(nt)
    sim = api.post("/aps/simulations", {"base_run_id": run["id"], "samples": 20, "seed": 3}, status=202)
    t = time.perf_counter()
    while api.get(f"/aps/simulations/{sim['id']}")["status"] in ("queued", "running"):
        time.sleep(0.5)
    out["FP6_risk_20_s"] = time.perf_counter() - t
    assert api.get(f"/aps/simulations/{sim['id']}")["status"] == "completed"
    rp, ms = _t(lambda: wait_run(api, api.post("/replan/run", {}, status=202)["id"]))
    out["FP4_replan_s"] = ms / 1000
    assert rp["status"] == "completed" and rp["validation"]["ok"], rp.get("validation")
    with capsys.disabled():
        print("\nM4 perf:", {k: round(v, 1) if isinstance(v, float) else v for k, v in out.items()})
