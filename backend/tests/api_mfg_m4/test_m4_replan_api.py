"""S2 over the API: downtime, replan triggers / notifications, policies (M4-DESIGN 7; T-F12), APS with actuals."""

from __future__ import annotations

import pytest
from apimfgm3_helpers import wait_run
from apimfgm4_helpers import PLANT_FIELDS, ev, plant


def _published(api, p):
    api.post("/mrp/runs", {})
    run = api.post("/aps/runs", {"improve_seconds": 0}, status=202)
    run = wait_run(api, run["id"])
    assert run["status"] == "completed", run
    api.post(f"/aps/runs/{run['id']}/publish", {}, status=200, version=run["row_version"])
    return run


def _policy(api, policy, debounce=15):
    pl = api.get("/plant")
    body = {k: v for k, v in pl.items() if k in PLANT_FIELDS}
    body.update(replan_policy=policy, replan_debounce_minutes=debounce)
    api.put("/plant", body, pl["row_version"])


def test_downtime_line_down_trigger_notification_and_dedupe(api):
    p = plant(api, ops=2, wo_qty=5)
    run = _published(api, p)
    ops = api.get(f"/aps/runs/{run['id']}/operations")["items"]
    line = next(o["line_id"] for o in ops if o["status"] == "scheduled")
    d = api.post("/downtime", {"line_id": line, "kind": "breakdown", "reason": "fan"})
    assert d["open"] and [t["kind"] for t in d["triggers"]] == ["line_down"]
    assert api.err("POST", "/downtime", 409, "FLR_LINE_DOWN", json={"line_id": line})
    trig = api.get("/replan/triggers", status="open")
    assert trig["total"] == 1 and trig["items"][0]["severity"] == "critical"
    n = api.get("/notifications", unacked=True)
    assert n["unacked"] == 1 and n["items"][0]["trigger_id"] == trig["items"][0]["id"]
    api.post(f"/notifications/{n['items'][0]['id']}/ack", {}, status=200)
    assert api.get("/notifications")["unacked"] == 0
    assert api.get("/summary")["floor"]["lines_down"] == 1
    # the floor refuses to start on a down line for an operator, the proposal moves its work away
    closed = api.put(f"/downtime/{d['id']}", {"close": True}, d["row_version"])
    assert not closed["open"] and closed["minutes"] is not None
    h = api.post(f"/replan/triggers/{trig['items'][0]['id']}/handle", {"note": "moved"}, status=200)
    assert h["status"] == "handled" and h["handled_by"]["id"]
    api.err("POST", f"/replan/triggers/{h['id']}/ignore", 409, "MFG_INVALID_STATE", json={})


def test_t_f12_auto_whatif_debounce_attaches_triggers(api):
    p = plant(api, ops=2, wo_qty=5)
    _published(api, p)
    _policy(api, "auto_whatif", 15)
    lines = [p["l1"]["id"], p["l2"]["id"]]
    ds = [api.post("/downtime", {"line_id": ln, "kind": "breakdown"}) for ln in lines]
    raised = [t for d in ds for t in d["triggers"]]
    runs = api.get("/aps/runs", status="queued")["items"]
    assert len(raised) >= 1 and len(runs) == 1 and runs[0]["label"].startswith("Replan")
    att = api.get("/replan/triggers", status="attached")["items"]
    assert len(att) == len(raised) and {t["aps_run_id"] for t in att} == {runs[0]["id"]}


def test_aps_run_uses_floor_actuals(api):
    p = plant(api, ops=2, wo_qty=10)
    op = p["ops"][0]["id"]
    ev(api, op, "start", line_id=p["l2"]["id"])
    ev(api, op, "report", qty_good=4)
    api.post("/mrp/runs", {})
    run = wait_run(api, api.post("/aps/runs", {"improve_seconds": 0}, status=202)["id"])
    assert run["status"] == "completed" and run["validation"]["ok"], run
    ops = [o for o in api.get(f"/aps/runs/{run['id']}/operations")["items"] if o["order"]["id"] == p["wo"]["id"]]
    first = next(o for o in ops if o["seq"] == 10)
    assert first["line_id"] == p["l2"]["id"] and first["qty"] == 6 and first["actual"]["status"] == "running"
    ev(api, op, "complete", qty_good=6)
    run = wait_run(api, api.post("/aps/runs", {"improve_seconds": 0}, status=202)["id"])
    ops = [o for o in api.get(f"/aps/runs/{run['id']}/operations")["items"] if o["order"]["id"] == p["wo"]["id"]]
    assert [o["seq"] for o in ops] == [20]


def test_kpis_and_adherence_api(api):
    from datetime import UTC, datetime, timedelta

    p = plant(api, ops=1, wo_qty=10)
    _published(api, p)
    op = p["ops"][0]["id"]
    t0 = datetime.now(UTC) - timedelta(hours=2)
    ev(api, op, "start", line_id=p["l1"]["id"], event_at=t0.isoformat())
    ev(api, op, "complete", qty_good=9, qty_scrap=1, reason_code="BRIDGE", event_at=(t0 + timedelta(minutes=60))
       .isoformat())
    k = api.get("/kpis")
    m = k["metrics"]
    assert m["scrap_rate"]["value"] == 0.1 and m["utilisation"]["num"] == pytest.approx(60, abs=1e-6)
    assert m["wip"]["count"] == 1 and m["availability"]["value"] == 1.0      # 9 of 10 received
    assert k["top_scrap"][0] == {"reason_code": "BRIDGE", "qty": 1.0}
    assert {x["ref"]["code"] for x in k["by_dim"]} >= {"L1"}
    line = api.get("/kpis", dim="line", dim_id=p["l1"]["id"], bucket="week")
    assert line["metrics"]["utilisation"]["num"] == pytest.approx(60, abs=1e-6)
    assert api.get("/kpis", dim="line", _status=422)["error"]["code"] == "VALIDATION_ERROR"
    adh = api.get("/kpis/adherence")
    assert adh["run_id"] and adh["tolerance_minutes"] == 120
    again = api.get("/kpis")
    assert again["metrics"] == k["metrics"]


def test_t_f15_risk_simulation_job_is_deterministic(api):
    import time

    p = plant(api, ops=1, wo_qty=5)
    run = _published(api, p)

    def sim(seed):
        r = api.post("/aps/simulations", {"base_run_id": run["id"], "samples": 3, "seed": seed}, status=202)
        assert api.err("POST", "/aps/simulations", 409, "APS_SIMULATION_IN_PROGRESS",
                       json={"base_run_id": run["id"]}) if r["status"] == "queued" else True
        t = time.monotonic()
        while True:
            x = api.get(f"/aps/simulations/{r['id']}")
            if x["status"] not in ("queued", "running"):
                return x
            assert time.monotonic() - t < 120
            time.sleep(0.2)

    a, b = sim(7), sim(7)
    assert a["status"] == "completed", a
    assert a["results"]["samples_done"] == 3 and a["results"] == b["results"]
    assert api.get("/aps/simulations")["total"] == 2
