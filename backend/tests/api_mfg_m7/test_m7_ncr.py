"""S3 (M7-DESIGN 6): inspection reject -> NCR with dispositions through the ledger (T-Q6), WIP nonconformance
through the floor log (T-Q7), holds owned by the NCR (T-Q8), close rules."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api_mfg_m4"))

from apimfgm2_helpers import Api  # noqa: E402
from apimfgm4_helpers import ev  # noqa: E402
from test_m7_inspection import gate_plant, plan, results, scheme  # noqa: E402


def _rejected_stock_lot(api: Api, qty: float = 3200) -> dict[str, Any]:
    g = api.post("/groups", {"code": "RW", "name": "Rework"})
    it = api.item("PART", "make", lot_controlled=True)
    rt = api.post("/routings", {"item_id": it["id"], "operations": [
        {"seq": 10, "name": "Rework", "group_id": g["id"], "run_minutes": 1, "labor": "unattended",
         "crew_size": 0}]})
    rt = api.post(f"/routings/{rt['id']}/release", {}, status=200, version=rt["row_version"])
    rt = rt.get("routing", rt)
    loc = api.location("ST")
    api.receive(it["id"], loc["id"], qty, lot_code="L-7")
    sc = scheme(api)
    pl = plan(api, it["id"], "final", sc["id"])
    lot = api.get("/lots", item_id=it["id"])["items"][0]
    il = api.post("/qa/inspection-lots", {"plan_id": pl["id"], "lot_id": lot["id"], "lot_size": qty, "hold": True})
    results(api, il, {"LEN": [12.0]})                              # one defective at ac 0 / re 1 -> reject
    out = api.post(f"/qa/inspection-lots/{il['id']}/decision", {"decision": "reject"}, 200)
    return {"it": it, "rt": rt, "loc": loc, "lot": lot, "il": out}


def test_t_q6_stock_ncr_scrap_rework_use_as_is(api):
    x = _rejected_stock_lot(api)
    assert x["il"]["status"] == "rejected" and x["il"]["ncr_id"]
    ncr = api.get(f"/qa/ncrs/{x['il']['ncr_id']}")
    assert ncr["status"] == "open" and ncr["qty_nc"] == 3200 and ncr["place"] == "stock"
    holds = api.get("/qa/holds", lot_id=x["lot"]["id"])["items"]
    assert [h["source"] for h in holds] == ["ncr"]                  # the inspection hold moved to the NCR
    lot = api.get("/lots", item_id=x["it"]["id"])["items"][0]
    api.err("PUT", f"/lots/{lot['id']}", 409, "QA_HOLD_ACTIVE", json={                      # T-Q8
        "expires_on": None, "supplier_lot": "", "hold": False, "note": ""},
        headers={"If-Match": f'"{lot["row_version"]}"'})
    api.err("POST", f"/qa/ncrs/{ncr['id']}/propose", 422, "QA_DISPOSITION_QTY", json={"dispositions": [
        {"kind": "scrap", "qty": 100}]})
    api.err("POST", f"/qa/ncrs/{ncr['id']}/propose", 422, "QA_JUSTIFICATION_REQUIRED", json={"dispositions": [
        {"kind": "scrap", "qty": 100}, {"kind": "use_as_is", "qty": 3100}]})
    body = {"dispositions": [{"kind": "scrap", "qty": 100},
                             {"kind": "rework", "qty": 200, "rework_routing_id": x["rt"]["id"]},
                             {"kind": "use_as_is", "qty": 2900, "justification": "Tested 100 %"}]}
    ncr = api.post(f"/qa/ncrs/{ncr['id']}/propose", body, 200)
    ncr = api.put(f"/qa/ncrs/{ncr['id']}", {"title": "Pull force", "capa_required": True, "severity": "critical",
                                            "qty_nc": 3200, "place": "stock"}, ncr["row_version"])
    ncr = api.post(f"/qa/ncrs/{ncr['id']}/approve", {}, 200)
    assert ncr["status"] == "approved"
    ncr = api.post(f"/qa/ncrs/{ncr['id']}/implement", {}, 200)
    assert ncr["status"] == "implemented"
    scrap = next(d for d in ncr["dispositions"] if d["kind"] == "scrap")
    txns = api.get("/inventory/transactions", item_id=x["it"]["id"])["items"]
    pst = [t for t in txns if t["posting"]["id"] == scrap["refs"]["posting_id"]] if "posting" in txns[0] else txns
    assert any(abs(t["qty"] + 100) < 1e-6 for t in pst)
    assert api.get("/lots", item_id=x["it"]["id"])["items"][0]["hold"] is True   # rework still open
    wo = ncr["rework_wos"][0]
    w = api.get(f"/work-orders/{wo['id']}")
    assert w["kind"] == "rework" and w["ncr_id"] == ncr["id"] and w["qty"] == 200
    w = api.post(f"/work-orders/{w['id']}/release", {"override_reason": "rework"}, 200, version=w["row_version"])
    comp = w["components"][0]
    api.post("/inventory/postings", {"type": "wo_issue", "lines": [                    # the held lot, to this WO
        {"wo_component_id": comp["id"], "location_id": x["loc"]["id"], "lot_code": "L-7", "qty": 200}]})
    api.post("/inventory/postings", {"type": "wo_receipt", "lines": [
        {"wo_id": w["id"], "location_id": x["loc"]["id"], "lot_code": "L-7", "qty": 200}]})
    assert api.get(f"/work-orders/{w['id']}")["status"] == "completed"
    assert api.get("/lots", item_id=x["it"]["id"])["items"][0]["hold"] is False  # released after rework
    e = api.err("POST", f"/qa/ncrs/{ncr['id']}/close", 409, "QA_NCR_NOT_CLOSABLE", json={})
    assert e["details"]["missing"] == ["capa"]
    cap = api.post("/qa/capas", {"title": "Bonding drift"})
    api.post("/qa/links", {"from_type": "ncr", "from_id": ncr["id"], "to_type": "capa", "to_id": cap["id"]})
    assert api.post(f"/qa/ncrs/{ncr['id']}/close", {}, 200)["status"] == "closed"


def test_t_q7_wip_nc_scrap_and_rework_balance(api):
    x = gate_plant(api, lot_fg=False)
    op10, op20 = x["ops"]
    ev(api, op10["id"], "start", line_id=x["l1"]["id"])
    ev(api, op10["id"], "complete", qty_good=10)
    ev(api, op20["id"], "start", line_id=x["l1"]["id"])
    r = ev(api, op20["id"], "report", qty_good=5, qty_nc=4, defect_code="SCRATCH")
    assert r["event"]["qty_nc"] == 4 and r["event"]["ncr_id"]
    ncr = api.get(f"/qa/ncrs/{r['event']['ncr_id']}")
    assert ncr["place"] == "wip" and ncr["qty_nc"] == 4 and ncr["operation_seq"] == 20
    ev(api, op20["id"], "report", 422, qty_good=2)                      # 5 + 4 + 2 > 10 input
    api.post(f"/qa/ncrs/{ncr['id']}/propose", {"dispositions": [
        {"kind": "scrap", "qty": 1}, {"kind": "rework", "qty": 3, "rework_to_seq": 10}]}, 200)
    api.post(f"/qa/ncrs/{ncr['id']}/approve", {}, 200)
    ncr = api.post(f"/qa/ncrs/{ncr['id']}/implement", {}, 200)
    assert ncr["status"] == "implemented" and all(d["refs"].get("floor_event_id") for d in ncr["dispositions"])
    ops = {o["seq"]: o for o in api.get(f"/work-orders/{x['wo']['id']}/operations")["items"]}
    assert ops[20]["qty_scrap"] == 1 and ops[20]["qty_rework_out"] == 3 and ops[10]["qty_rework_in"] == 3
    assert ops[20]["qty_good"] == 5
