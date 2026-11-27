"""Network topology, DRP runs, pegging and cross-plant / cross-organisation isolation (M9-DESIGN 4, 5, 9)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from m9_helpers import V1, Api, app_for, make_world
from m8_helpers import wait_for

TODAY = date.today()


def _due(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def network_setup(w) -> dict:
    qc, dc, us = w.api("QC"), w.api("DCUS"), w.api("US1")
    out = {"dc_item": dc.item("SYR-3ML", make_buy="buy", external_ref="SYR", family="SYR"),
           "qc_item": qc.item("SYR-3ML", make_buy="make", external_ref="SYR", family="SYR", lead_time_days=7),
           "us_item": us.item("SYR-3ML-US", make_buy="make", external_ref="SYR", family="SYR", lead_time_days=7)}
    net = w.net
    out["lane_qc"] = net.post("/net/lanes", {"from_owner_id": w.owner("QC"), "to_owner_id": w.owner("DCUS"),
                                             "mode": "road", "transit_days": 3, "freight_per_unit": 0.004})
    out["lane_us"] = net.post("/net/lanes", {"from_owner_id": w.owner("US1"), "to_owner_id": w.owner("DCUS"),
                                             "mode": "road", "transit_days": 2})
    out["rule"] = net.post("/net/sourcing", {"dest_owner_id": w.owner("DCUS"), "family": "SYR", "source_kind": "plant",
                                             "source_owner_id": w.owner("QC"), "priority": 1})
    o = dc.post("/demand-orders", {"demand_type": "customer", "priority": 2, "lines": [
        {"item_id": out["dc_item"]["id"], "qty": 4800, "due_date": _due(30)}]})
    out["order"] = dc.post(f"/demand-orders/{o['id']}/open", version=o["row_version"], status=200)
    return out


def run(net: Api, **params) -> dict:
    r = net.post("/net/runs", params, status=202)
    return wait_for(lambda: net.get(f"/net/runs/{r['id']}"), lambda x: x["status"] not in ("queued", "running"))


def test_topology_run_grid_pegging(db_url):
    app = app_for(db_url)
    with TestClient(app):
        w = make_world(app)
        s = network_setup(w)
        net = w.net
        nodes = {n["code"]: n for n in net.get("/net/nodes")["items"]}
        assert set(nodes) == {"QC", "US1", "DCUS"} and nodes["DCUS"]["kind"] == "dc" and nodes["QC"]["country"] == "CA"
        assert nodes["QC"]["member"] is True
        res = net.get("/net/sourcing/resolve", dest=w.owner("DCUS"), key="SYR")
        assert res["mode"] == "priority" and res["matched_by"] == "family"
        assert res["sources"][0]["source_owner_id"] == w.owner("QC") and res["sources"][0]["transit_days"] == 3
        # quota rules that do not sum to 100 are refused at run start
        q = net.post("/net/sourcing", {"dest_owner_id": w.owner("DCUS"), "family": "SYR", "source_kind": "plant",
                                       "source_owner_id": w.owner("US1"), "priority": 2, "quota_pct": 30})
        net.err("POST", "/net/runs", 422, "NET_QUOTA_SUM", json={})
        net.delete(f"/net/sourcing/{q['id']}", version=q["row_version"])
        r = run(net, label="Weekly")
        assert r["status"] == "completed" and r["validator"]["ok"], r
        assert r["number"] == "NR-000001" and r["input_hash"] and r["summary"]["transfers"] >= 1, (r, w.api("DCUS").get("/demand-orders"))
        trs = net.get(f"/net/runs/{r['id']}/transfers")["items"]
        assert trs and all(t["src_owner_id"] == w.owner("QC") for t in trs)
        assert sum(t["qty"] for t in trs) == 4800 and trs[0]["pegs"][0]["ref"].startswith("DO-")
        grid = net.get(f"/net/runs/{r['id']}/grid", node=w.owner("DCUS"))
        assert grid["total"] == 1 and grid["items"][0]["uom"] == "EA" and len(grid["items"][0]["cells"]) == 26
        peg = net.get(f"/net/runs/{r['id']}/pegging", node=w.owner("DCUS"), key="SYR")
        root = peg["root"]
        assert root["kind"] == "demand" and root["children"][0]["kind"] == "transfer"
        assert root["children"][0]["children"][0]["kind"] == "production"
        up = net.get(f"/net/runs/{r['id']}/pegging", supply_id=trs[0]["id"])
        assert up["direction"] == "up" and up["root"]["children"][0]["kind"] == "demand"
        # loops are refused synchronously with the path
        net.post("/net/lanes", {"from_owner_id": w.owner("DCUS"), "to_owner_id": w.owner("QC"), "transit_days": 3})
        loop = net.post("/net/sourcing", {"dest_owner_id": w.owner("QC"), "family": "SYR", "source_kind": "plant",
                                          "source_owner_id": w.owner("DCUS")})
        e = net.err("POST", "/net/runs", 422, "NET_CYCLE", json={})
        assert {x["code"] for x in e["details"]["path"]} == {"QC", "DCUS"}
        net.delete(f"/net/sourcing/{loop['id']}", version=loop["row_version"])
        curves = net.get("/net/ramp-curves")["items"]
        assert [c["code"] for c in curves] == ["STD26"] and curves[0]["points"][-1]["rate_pct"] == 100


def test_cross_plant_and_cross_org_isolation(db_url):
    app = app_for(db_url)
    with TestClient(app):
        wa = make_world(app, "alpha", "admin@alpha.example")
        network_setup(wa)
        r = run(wa.net)
        assert r["status"] == "completed"
        wb = make_world(app, "beta", "admin@beta.example")
        # org B's network cannot see or use org A's run, lanes or nodes
        assert wb.net.get("/net/runs")["total"] == 0 and wb.net.get("/net/lanes")["items"] == []
        wb.net.err("GET", f"/net/runs/{r['id']}", 404, "NOT_FOUND")
        wb.net.err("GET", f"/net/runs/{r['id']}/pegging", 404, "NOT_FOUND", params={"supply_id": "x"})
        wb.net.err("POST", "/net/lanes", 422, "NET_UNKNOWN_NODE", json={
            "from_owner_id": wa.owner("QC"), "to_owner_id": wb.owner("DCUS"), "transit_days": 1})
        assert {n["owner_id"] for n in wb.net.get("/net/nodes")["items"]}.isdisjoint(
            {wa.owner(c) for c in ("QC", "US1", "DCUS")})
        # org B's admin cannot open org A's network workspace at all
        Api(wb.admin, wa.net_owner).err("GET", "/net/runs", 404, "NOT_FOUND")
        # a network planner who is not a member of QC sees no link into QC records
        pl = wa.person("planner@alpha.example", {"NET": ["planner"]})
        api = Api(pl, wa.net_owner)
        nodes = {n["code"]: n for n in api.get("/net/nodes")["items"]}
        assert nodes["QC"]["member"] is False
        trs = api.get(f"/net/runs/{r['id']}/transfers")["items"]
        assert trs
        peg = api.get(f"/net/runs/{r['id']}/pegging", supply_id=trs[0]["id"])
        assert peg["root"]["link"] is None
        api.err("POST", "/net/lanes", 403, "MFG_FORBIDDEN", json={
            "from_owner_id": wa.owner("QC"), "to_owner_id": wa.owner("DCUS"), "transit_days": 1, "mode": "air"})
        Api(pl, wa.owner("QC")).err("GET", "/items", 404, "NOT_FOUND")
