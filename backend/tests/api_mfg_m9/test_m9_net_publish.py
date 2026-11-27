"""Network publish into M5 transfer orders and plant MRP inputs (M9-DESIGN 5.4; M9-NET-07, M9-NET-08)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from m9_helpers import app_for, make_world
from test_m9_network_api import network_setup, run

TODAY = date.today()


def _due(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def _order(api, item_id: str, qty: float, days: int) -> dict:
    o = api.post("/demand-orders", {"demand_type": "customer", "priority": 2, "lines": [
        {"item_id": item_id, "qty": qty, "due_date": _due(days)}]})
    return api.post(f"/demand-orders/{o['id']}/open", version=o["row_version"], status=200)


def _network_tos(api) -> list[dict]:
    return [t for t in api.get("/transfer-orders", limit=200)["items"] if t.get("source") == "network"]


@pytest.mark.req("M9-NET-07")
def test_publish_keep_cancel_create_and_shipped_untouched(db_url):
    app = app_for(db_url)
    with TestClient(app):
        w = make_world(app)
        s = network_setup(w)                         # 4,800 due in 30 days (later than the firm zone)
        qc, dc, net = w.api("QC"), w.api("DCUS"), w.net
        _order(dc, s["dc_item"]["id"], 1000, 12)     # inside the 14-day firm zone (ship ~ 3 working days earlier)
        r1 = run(net)
        assert r1["status"] == "completed" and r1["validator"]["ok"]
        p1 = net.post(f"/net/runs/{r1['id']}/publish", None, status=200)
        res = p1["publish_result"]
        assert p1["published"] and len(res["created"]) == 1 and res["network_demands"] >= 1
        tos = _network_tos(qc)
        assert len(tos) == 1 and tos[0]["status"] == "open" and tos[0]["net_run_id"] == r1["id"]
        assert tos[0]["lines"][0]["qty"] == 1000
        mirror = _network_tos(dc)
        assert len(mirror) == 1 and mirror[0]["direction"] == "in"
        trs = net.get(f"/net/runs/{r1['id']}/transfers")["items"]
        assert any(t["to_number"] == tos[0]["number"] for t in trs)
        # unchanged plan -> the TO is kept and re-linked
        r2 = run(net)
        p2 = net.post(f"/net/runs/{r2['id']}/publish", None, status=200)["publish_result"]
        assert len(p2["kept"]) == 1 and not p2["created"] and not p2["cancelled"]
        assert net.get(f"/net/runs/{r1['id']}")["published"] is False
        # demand changes inside the firm zone -> the old TO is cancelled, a new one created
        _order(dc, s["dc_item"]["id"], 500, 12)
        r3 = run(net)
        from sqlalchemy import event
        seen: list[str] = []
        eng = app.state.ctx.db.engine

        def grab(conn, cursor, statement, *a):            # review M1: candidates are locked before the decision
            seen.append(statement)
        event.listen(eng, "before_cursor_execute", grab)
        try:
            p3 = net.post(f"/net/runs/{r3['id']}/publish", None, status=200)["publish_result"]
        finally:
            event.remove(eng, "before_cursor_execute", grab)
        assert any("FROM mfg_transfer_orders" in x and "FOR UPDATE" in x for x in seen)
        assert any("FROM mfg_transfer_lines" in x and "FOR UPDATE" in x for x in seen)
        assert len(p3["cancelled"]) == 1 and len(p3["created"]) == 1, p3
        from m8_helpers import audit_rows                  # review m1: the mirror's cancel is audited in the DC
        dst_rows = audit_rows(w.admin, "transfer_order", owner=w.owner("DCUS"))
        assert any(x["action"] == "cancel" and x["reason"].startswith("Superseded by network plan") for x in dst_rows)
        live = [t for t in _network_tos(qc) if t["status"] == "open"]
        assert len(live) == 1 and live[0]["lines"][0]["qty"] == 1500
        # a shipped network TO is never touched
        loc = qc.location("ST")
        qc.receive(s["qc_item"]["id"], loc["id"], 2000)
        qc.post("/inventory/postings", {"type": "transfer_ship", "lines": [
            {"transfer_line_id": live[0]["lines"][0]["id"], "item_id": s["qc_item"]["id"], "location_id": loc["id"],
             "qty": 100}]})
        _order(dc, s["dc_item"]["id"], 700, 12)
        r4 = run(net)
        p4 = net.post(f"/net/runs/{r4['id']}/publish", None, status=200)["publish_result"]
        assert live[0]["id"] not in json.dumps(p4["cancelled"])
        assert qc.get(f"/transfer-orders/{live[0]['id']}")["status"] in ("open", "shipped")
        # a stale or failed run cannot be published
        bad = net.post("/net/runs", {"as_of": (TODAY - timedelta(days=1)).isoformat()}, status=202)
        from m8_helpers import wait_for
        wait_for(lambda: net.get(f"/net/runs/{bad['id']}"), lambda x: x["status"] == "completed")
        net.err("POST", f"/net/runs/{bad['id']}/publish", 409, "NET_RUN_STALE")


@pytest.mark.req("M9-NET-08")
def test_plant_mrp_sees_network_demand_supply_and_network_short(db_url):
    app = app_for(db_url)
    with TestClient(app):
        w = make_world(app)
        s = network_setup(w)
        qc, dc, net = w.api("QC"), w.api("DCUS"), w.net
        r = run(net)
        net.post(f"/net/runs/{r['id']}/publish", None, status=200)
        qc.post("/mrp/runs", {})
        qrun = qc.get("/mrp/runs")["items"][0]
        dem = json.dumps(qc.get(f"/mrp/runs/{qrun['id']}/items/{s['qc_item']['id']}"))
        assert "Transfer to DCUS" in dem and "DO-000001" in dem
        dc.put(f"/items/{s['dc_item']['id']}/planning", {"replenishment": "transfer"}, version=0)
        dc.post("/mrp/runs", {})
        drun = dc.get("/mrp/runs")["items"][0]
        view = json.dumps(dc.get(f"/mrp/runs/{drun['id']}/items/{s['dc_item']['id']}"))
        assert '"network"' in view and "Transfer from QC" in view
        assert not dc.get(f"/mrp/runs/{drun['id']}/planned-orders")["items"]
        _order(dc, s["dc_item"]["id"], 300, 40)          # not in the published network plan
        dc.post("/mrp/runs", {})
        drun = dc.get("/mrp/runs")["items"][0]
        ex = dc.get(f"/mrp/runs/{drun['id']}/exceptions")["items"]
        short = [e for e in ex if e["code"] == "MRP_NETWORK_SHORT"]
        assert short and short[0]["severity"] == "critical" and short[0]["qty"] == 300
        assert not dc.get(f"/mrp/runs/{drun['id']}/planned-orders")["items"]
