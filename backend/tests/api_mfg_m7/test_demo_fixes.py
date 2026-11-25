"""Demo findings: OEE never above 100 % by default; floor "issue component lot" through the ledger with hold,
quarantine and component rules; recall report quantities for lot-controlled material."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api_mfg_m4"))

from apimfgm4_helpers import cid  # noqa: E402
from superplanner.mfg import kpi as K  # noqa: E402


def test_oee_capped():
    assert K.oee(1.0, 1.19, 1.0) == 1.0
    assert K.oee(0.9, 1.19, 0.95) == round(0.9 * 1.0 * 0.95, 6)
    assert K.oee(0.9, 1.19, 1.0, performance_cap=1.2) == round(0.9 * 1.19, 6)
    assert K.oee(None, 0.8, 1.0) is None


def _plant(api):
    st = api.location("ST")
    qr = api.location("QR", "quarantine")
    g = api.post("/groups", {"code": "G", "name": "G"})
    api.post("/lines", {"group_id": g["id"], "code": "L1", "name": "L1"})
    lc = api.item("LC", lot_controlled=True)
    fg = api.item("FG", "make")
    b = api.post("/boms", {"item_id": fg["id"], "lines": [{"find_number": "1", "child_item_id": lc["id"],
                                                           "qty_per": 2, "operation_seq": 10}]})
    api.post(f"/boms/{b['id']}/release", {}, status=200, version=b["row_version"])
    rt = api.post("/routings", {"item_id": fg["id"], "operations": [
        {"seq": 10, "name": "Asm", "group_id": g["id"], "run_minutes": 1, "labor": "unattended", "crew_size": 0}]})
    api.post(f"/routings/{rt['id']}/release", {}, status=200, version=rt["row_version"])
    for code, loc in (("A1", st), ("A2", st), ("A3", qr)):
        api.receive(lc["id"], loc["id"], 50, lot_code=code)
    wo = api.post("/work-orders", {"item_id": fg["id"], "qty": 10, "due_date": "2026-12-20",
                                   "start_date": "2026-11-20"})
    wo = api.post(f"/work-orders/{wo['id']}/release", {"override_reason": "t"}, status=200, version=wo["row_version"])
    op = api.get(f"/work-orders/{wo['id']}/operations")["items"][0]
    return {"lc": lc, "op": op, "wo": wo}


def test_floor_issue_component_lot(api):
    x = _plant(api)
    out = api.post("/floor/issue-lot", {"wo_operation_id": x["op"]["id"], "scan": "L:LC:A1", "qty": 5})
    assert out["qty"] == 5 and out["component"]["remaining"] == 15 and out["lot"]["lot_code"] == "A1"
    out = api.post("/floor/issue-lot", {"wo_operation_id": x["op"]["id"], "scan": "A1"})        # default qty
    assert out["qty"] == 15 and out["component"]["remaining"] == 0
    lot2 = next(l for l in api.get("/lots", item_id=x["lc"]["id"])["items"] if l["lot_code"] == "A2")
    api.post("/qa/holds", {"lot_id": lot2["id"], "reason": "inspection pending"})
    api.err("POST", "/floor/issue-lot", 422, "INV_LOT_ON_HOLD", json={"wo_operation_id": x["op"]["id"],
                                                                      "scan": "A2", "qty": 1,
                                                                      "over_issue": True, "reason": "t"})
    api.err("POST", "/floor/issue-lot", 409, "FLR_LOT_QUARANTINED", json={"wo_operation_id": x["op"]["id"],
                                                                          "scan": "A3", "qty": 1,
                                                                          "over_issue": True, "reason": "t"})
    other = api.item("OTHER", lot_controlled=True)
    api.receive(other["id"], api.get("/locations")["items"][0]["id"], 5, lot_code="Z9")
    api.err("POST", "/floor/issue-lot", 422, "FLR_LOT_NOT_A_COMPONENT", json={
        "wo_operation_id": x["op"]["id"], "scan": "L:OTHER:Z9", "client_event_id": cid()})


def test_recall_report_lot_quantities(api):
    from test_m7_capa_fa import _recall_world

    x = _recall_world(api)
    rc = api.post("/recalls", {"name": "L-1", "sources": [{"kind": "lot", "id": x["lot"]["id"]}]})
    rep = api.get(f"/recalls/{rc['id']}")["report"]
    c = rep["counts"]
    assert c["qty_shipped"] == 40 and c["qty_in_stock"] == 60 and c["qty_affected"] == 100 and c["customers"] == 2
    by = {b["customer"]: b for b in rep["by_customer"]}
    assert by["CHU A"]["qty"] == 20 and by["CHU A"]["lots"] == ["L-1"]
    assert all(sh["lots"] == ["L-1"] for sh in rep["shipments"])
