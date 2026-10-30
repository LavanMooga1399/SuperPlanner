"""B4 (M2-DESIGN 8.14, 12.3 #148-163): runs, staleness, views, pegging, compare, export, conversion exactly once
(firm / release, idempotent replay C17), not-latest / what-if refusal, retention guard, shortages."""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta

from apimfgm2_helpers import A, Api, im


def _small_run(api: Api, **params) -> dict:
    api.load("small", anchor=None)
    return api.post("/mrp/runs", {"label": "Weekly", **params})


def test_run_views_and_staleness(api: Api):
    run = _small_run(api)
    assert run["status"] == "completed" and run["kind"] == "live" and run["run_no"] == 1
    assert set(run["summary"]["timings_ms"]) == {"load", "compute", "store"}
    assert run["stale"] == {"is_stale": False, "master_changed": False, "transactions_changed": False}
    rid = run["id"]
    assert api.get("/mrp/runs/latest")["id"] == rid
    assert api.get("/mrp/runs")["items"][0]["id"] == rid and "params" not in api.get("/mrp/runs")["items"][0]
    items = api.get(f"/mrp/runs/{rid}/items", sort="part_number")
    assert items["total"] == 10 and items["items"][0]["link"].startswith(f"/mfg/mrp/runs/{rid}/items/")
    mcu = api.by_pn("SM-MCU-01")
    plan = api.get(f"/mrp/runs/{rid}/items/{mcu['id']}", bucket="week")
    assert plan["row"]["item"]["part_number"] == "SM-MCU-01" and plan["supplier"]["code"] == "SUP-A"
    assert plan["timeline"][0]["kind"] == "on_hand" and plan["buckets"]
    req = plan["requirements"][0]
    peg = api.get(f"/mrp/runs/{rid}/pegging", item_id=mcu["id"], node=req["node"], kind="requirement",
                  direction="up")
    assert peg["rows"][0]["level"] == 0 and peg["rows"][-1]["item"]["part_number"] == "SM-100"
    api.err("GET", f"/mrp/runs/{rid}/pegging", 404, "NOT_FOUND", params={"item_id": mcu["id"], "node": 999})
    ex = api.get(f"/mrp/runs/{rid}/exceptions", severity=["critical"])
    assert ex["counts"]["by_severity"]["critical"] >= 0 and all(e["severity"] == "critical" for e in ex["items"])
    for e in api.get(f"/mrp/runs/{rid}/exceptions", limit=200)["items"]:
        assert e["link"] is None or e["link"].startswith("/mfg/"), e
    dem = api.get(f"/mrp/runs/{rid}/demand")
    assert dem["total"] == 2 and dem["items"][0]["link"].startswith("/mfg/demand/")
    pl = api.get(f"/mrp/runs/{rid}/planned-orders")
    assert pl["total"] == pl["counts"]["by_kind"]["buy"] + pl["counts"]["by_kind"]["make"]
    data = api.req("GET", f"/mrp/runs/{rid}/export", 200, params={"format": "zip"}).content
    assert sorted(zipfile.ZipFile(io.BytesIO(data)).namelist()) == ["demand.csv", "exceptions.csv", "items.csv",
                                                                   "planned_orders.csv"]
    api.post("/locations", {"code": "NEW", "name": "New", "kind": "stores"})
    assert api.get(f"/mrp/runs/{rid}")["stale"]["master_changed"]
    loc = next(x for x in api.get("/locations")["items"] if x["code"] == "STORES")
    api.receive(mcu["id"], loc["id"], 1)
    assert api.get(f"/mrp/runs/{rid}")["stale"]["transactions_changed"]
    shortages = api.get("/shortages")
    assert shortages["run"]["id"] == rid and set(shortages["counts"]) == {"late_demand", "short_items",
                                                                          "overdue_schedules", "wo_short"}
    s = api.get("/summary")
    assert s["latest_run"]["id"] == rid and s["counts"]["suppliers"] == 2


def test_convert_firm_release_exactly_once_and_replay(api: Api):
    run = _small_run(api)
    rid = run["id"]
    pl = api.get(f"/mrp/runs/{rid}/planned-orders", limit=200)["items"]
    make = next(p for p in pl if p["kind"] == "make")
    buys = [p for p in pl if p["kind"] == "buy"]
    h = {"Idempotency-Key": "cv-1"}
    body = {"mode": "firm", "orders": [{"id": make["id"]}] + [{"id": b["id"]} for b in buys]}
    out = api.post(f"/mrp/runs/{rid}/planned-orders/convert", body, headers=h)
    assert len(out["converted"]) == 1 + len(buys) and len(out["created"]["work_orders"]) == 1
    prs = out["created"]["purchase_requests"]
    assert sum(p["line_count"] for p in prs) == len(buys)
    r = api.req("POST", f"/mrp/runs/{rid}/planned-orders/convert", 200, json=body, headers=h)
    assert r.headers["Idempotent-Replay"] == "true" and r.json() == out
    e = api.err("POST", f"/mrp/runs/{rid}/planned-orders/convert", 409, "MRP_ALREADY_CONVERTED",
                json={"mode": "firm", "orders": [{"id": make["id"]}]})
    assert e["details"]["ids"] == [make["id"]]
    wo = api.get(f"/work-orders/{out['created']['work_orders'][0]['id']}")
    assert wo["status"] == "planned" and wo["source"] == "mrp" and wo["source_run_no"] == 1
    pr = api.get(f"/purchase-requests/{prs[0]['id']}")
    assert pr["status"] == "draft" and pr["source"] == "mrp"
    api.err("DELETE", f"/purchase-requests/{pr['id']}", 409, "MFG_INVALID_STATE", headers=im(pr["row_version"]))
    planned = api.get(f"/mrp/runs/{rid}/planned-orders", status="converted")
    assert planned["total"] == len(body["orders"]) and planned["items"][0]["converted"]["id"]
    # re-run: the converted supply is existing supply now; nothing is planned twice
    run2 = api.post("/mrp/runs", {})
    assert run2["run_no"] == 2
    pl2 = api.get(f"/mrp/runs/{run2['id']}/planned-orders", limit=200)["items"]
    assert sum(p["qty"] for p in pl2 if p["kind"] == "make") <= sum(p["qty"] for p in pl if p["kind"] == "make") - \
        make["qty"] + 1e-6
    api.err("POST", f"/mrp/runs/{rid}/planned-orders/convert", 409, "MRP_RUN_NOT_LATEST",
            json={"mode": "release", "orders": [{"id": pl2[0]["id"]}]})
    rel = [p for p in pl2 if p["kind"] == "make"]
    if rel:
        out2 = api.post(f"/mrp/runs/{run2['id']}/planned-orders/convert",
                        {"mode": "release", "reserve": True, "orders": [{"id": rel[0]["id"]}]})
        assert api.get(f"/work-orders/{out2['created']['work_orders'][0]['id']}")["status"] == "released"
    api.err("DELETE", f"/mrp/runs/{run2['id']}", 409, "MFG_IN_USE", headers=im(api.get(f"/mrp/runs/{run2['id']}")
                                                                             ["row_version"]))
    old = api.get(f"/mrp/runs/{rid}")
    api.delete(f"/mrp/runs/{rid}", old["row_version"])


def test_what_if_compare_pin_and_preflight(api: Api):
    live = _small_run(api)
    po = api.doc("/purchase-orders", "PO-SM-0001")
    s1 = po["lines"][0]["schedules"][0]
    later = (date.fromisoformat(s1["dock_date"]) + timedelta(days=30)).isoformat()
    wi = api.post("/mrp/runs", {"supply_date_overrides": [{"schedule_id": s1["id"], "date": later}]})
    assert wi["kind"] == "what_if"
    api.err("POST", f"/mrp/runs/{wi['id']}/planned-orders/convert", 409, "MRP_RUN_NOT_LATEST", json={
        "mode": "firm", "orders": [{"id": api.get(f"/mrp/runs/{wi['id']}/planned-orders")["items"][0]["id"]}]})
    cmp = api.get(f"/mrp/runs/{live['id']}/compare", **{"with": wi["id"]})
    assert cmp["a"]["id"] == live["id"] and cmp["demand"] and cmp["demand"][0]["delta_days"] > 0
    pinned = api.put(f"/mrp/runs/{wi['id']}", {"label": "Late FPGA", "pinned": True}, wi["row_version"])
    assert pinned["pinned"] and pinned["label"] == "Late FPGA"
    assert api.get("/mrp/runs/latest")["id"] == live["id"]
    e = api.err("POST", "/mrp/runs", 422, "MRP_PREFLIGHT_FAILED", json={
        "extra_demand": [{"item_id": "itm_" + "0" * 32, "qty": 1, "due_date": A}]})
    assert e["details"]["issues"]
    assert api.get("/mrp/runs")["total"] == 2


def test_health_gate_blocks_run(api: Api):
    api.item("NOLEAD", lead_time_days=None)
    p = api.item("TOP", "make")
    e = api.err("POST", "/mrp/runs", 422, "MFG_DATA_HEALTH_FAILED", json={})
    assert e["details"]["report"]["ok"] is False
    assert api.get("/mrp/runs")["total"] == 0
    del p
