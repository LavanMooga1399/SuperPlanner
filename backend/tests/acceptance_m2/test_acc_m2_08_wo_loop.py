"""Gate 2 #8: WO loop. Create a WO (components generated from the effective BOM with scrap/yield inflation and
integer rounding, 7.2), release with reserve, kitting shortage list names exactly the items without free stock,
issue, partial completion, automatic status changes (released -> in_progress -> completed, reservations released),
and the shortage dashboard lists the WO shortages and the overdue PO.
"""

from __future__ import annotations

from datetime import date, timedelta

from accm2_helpers import Api

ENDPOINTS = ("POST /work-orders", "POST /work-orders/{wo_id}/release", "GET /work-orders/{wo_id}/kitting",
             "POST /work-orders/kitting-check", "POST /work-orders/{wo_id}/reserve", "GET /shortages",
             "POST /inventory/postings", "POST /purchase-orders", "POST /work-orders/{wo_id}/close")


def world(api: Api) -> dict:
    api.need(*ENDPOINTS)
    w = {"STORES": api.post("/locations", {"code": "STORES", "name": "Stores", "kind": "stores"}),
         "QUAR": api.post("/locations", {"code": "QUAR", "name": "Quarantine", "kind": "quarantine"})}
    g = api.post("/groups", {"code": "ASM", "name": "Assembly"})
    api.post("/lines", {"group_id": g["id"], "code": "ASM-1", "name": "Assembly 1"})
    w["P"] = api.post("/items", {"part_number": "WO-P", "make_buy": "make", "lead_time_days": 2})
    for pn in ("WO-C1", "WO-C2", "WO-C3", "WO-C4"):
        w[pn] = api.post("/items", {"part_number": pn, "make_buy": "buy", "lead_time_days": 10})
    rt = api.post("/routings", {"item_id": w["P"]["id"], "operations": [
        {"seq": 10, "name": "Assemble", "group_id": g["id"], "run_minutes": 5, "yield_pct": 100}]})
    api.post(f"/routings/{rt['id']}/release", {"effective_from": None}, status=200, version=rt["row_version"])
    bom = api.post("/boms", {"item_id": w["P"]["id"], "lines": [
        {"find_number": "10", "child_item_id": w["WO-C1"]["id"], "qty_per": 2},
        {"find_number": "20", "child_item_id": w["WO-C2"]["id"], "qty_per": 1},
        {"find_number": "30", "child_item_id": w["WO-C3"]["id"], "qty_per": 1, "scrap_pct": 5},
        {"find_number": "40", "child_item_id": w["WO-C4"]["id"], "qty_per": 1}]})
    api.post(f"/boms/{bom['id']}/release", {"effective_from": None}, status=200, version=bom["row_version"])
    st, q = w["STORES"]["id"], w["QUAR"]["id"]
    api.post("/inventory/postings", {"type": "receipt_misc", "lines": [
        {"item_id": w["WO-C1"]["id"], "location_id": st, "qty": 100},
        {"item_id": w["WO-C3"]["id"], "location_id": st, "qty": 5},
        {"item_id": w["WO-C4"]["id"], "location_id": st, "qty": 10},
        {"item_id": w["WO-C2"]["id"], "location_id": q, "qty": 50}]})     # quarantine is never free
    sup = api.post("/suppliers", {"code": "SUP-W", "name": "Supplier W (fictional)"})
    today = date.today()
    w["PO"] = api.post("/purchase-orders", {"supplier_id": sup["id"], "lines": [
        {"item_id": w["WO-C2"]["id"], "schedules": [
            {"requested_date": (today - timedelta(days=2)).isoformat(), "qty": 10},
            {"requested_date": (today + timedelta(days=9)).isoformat(), "qty": 10}]}]})
    w["PO"] = api.post(f"/purchase-orders/{w['PO']['id']}/issue", {}, status=200, version=w["PO"]["row_version"])
    return w


def test_wo_release_kitting_issue_partial_completion(api):
    w = world(api)
    today = date.today()
    wo = api.post("/work-orders", {"item_id": w["P"]["id"], "qty": 10, "due_date": (today + timedelta(days=5))
                                   .isoformat(), "start_date": (today + timedelta(days=1)).isoformat()})
    assert wo["status"] == "planned" and wo["number"].startswith("WO-") and wo["bom"]["id"]
    req = {c["item"]["part_number"]: c["required_qty"] for c in wo["components"]}
    assert req == {"WO-C1": 20, "WO-C2": 10, "WO-C3": 11, "WO-C4": 10}      # 10 x 1.05 = 10.5 -> 11
    wo = api.post(f"/work-orders/{wo['id']}/release", {"reserve": True}, status=200, version=wo["row_version"])
    assert wo["status"] == "released" and wo["released_at"]
    rsv = {c["item"]["part_number"]: c["reserved_qty"] for c in wo["components"]}
    assert rsv == {"WO-C1": 20, "WO-C2": 0, "WO-C3": 5, "WO-C4": 10}
    kit = api.get(f"/work-orders/{wo['id']}/kitting")
    short = {r["item"]["part_number"]: r["shortage"] for r in kit["rows"] if r["shortage"] > 0}
    assert short == {"WO-C2": 10, "WO-C3": 6}
    assert kit["totals"]["kit_complete"] is False and kit["totals"]["short_components"] == 2
    c2 = next(r for r in kit["rows"] if r["item"]["part_number"] == "WO-C2")
    assert c2["next_supply"]["type"] in ("po", "po_schedule") and c2["next_supply"]["qty"] == 10
    check = api.post("/work-orders/kitting-check", {"wo_ids": None, "order": "priority", "horizon_days": 14},
                     status=200)
    assert {x["item"]["part_number"] for x in check["items_short"]} == {"WO-C2", "WO-C3"}
    dash = api.get("/shortages", horizon_days=30)
    assert {x["item"]["part_number"] for x in dash["wo_shortages"]} == {"WO-C2", "WO-C3"}
    po_scheds = {s["id"] for s in w["PO"]["lines"][0]["schedules"]}
    overdue = [x for x in dash["overdue_supply"] if x["schedule_id"] in po_scheds]
    assert len(overdue) == 1 and overdue[0]["overdue_days"] == 2
    assert dash["counts"]["overdue_schedules"] >= 1
    # issue what is there; status moves to in_progress
    comps = {c["item"]["part_number"]: c["id"] for c in wo["components"]}
    st = w["STORES"]["id"]
    api.post("/inventory/postings", {"type": "wo_issue", "lines": [
        {"wo_component_id": comps["WO-C1"], "location_id": st, "qty": 20},
        {"wo_component_id": comps["WO-C4"], "location_id": st, "qty": 10}]})
    wo = api.get(f"/work-orders/{wo['id']}")
    assert wo["status"] == "in_progress"
    # partial completion, then the rest -> completed, remaining reservations (C3) released
    api.post("/inventory/postings", {"type": "wo_receipt", "lines": [{"wo_id": wo["id"], "location_id": st,
                                                                       "qty": 4}]})
    wo = api.get(f"/work-orders/{wo['id']}")
    assert (wo["status"], wo["qty_completed"], wo["open_qty"]) == ("in_progress", 4, 6)
    api.post("/inventory/postings", {"type": "wo_receipt", "lines": [{"wo_id": wo["id"], "location_id": st,
                                                                       "qty": 6}]})
    wo = api.get(f"/work-orders/{wo['id']}")
    assert wo["status"] == "completed" and wo["completed_at"]
    assert all(c["reserved_qty"] == 0 for c in wo["components"])
    c3 = api.get("/inventory/balances", item_id=w["WO-C3"]["id"])["items"][0]
    assert (c3["qty_on_hand"], c3["qty_reserved"]) == (5, 0)
    # completed WO is read-only; close is final
    r = api.raw("PUT", f"/work-orders/{wo['id']}", json={}, headers={"If-Match": f'"{wo["row_version"]}"'})
    assert r.status_code in (409, 422)
    wo = api.post(f"/work-orders/{wo['id']}/close", {}, status=200, version=wo["row_version"])
    assert wo["status"] == "closed"
    r = api.raw("POST", f"/work-orders/{wo['id']}/cancel", json={}, headers={"If-Match": f'"{wo["row_version"]}"'})
    assert r.status_code == 409 and r.json()["error"]["code"] in ("MFG_INVALID_STATE", "WO_HAS_TRANSACTIONS")


def test_wo_cancel_with_transactions_is_refused(api):
    w = world(api)
    today = date.today()
    wo = api.post("/work-orders", {"item_id": w["P"]["id"], "qty": 2, "due_date": (today + timedelta(days=3))
                                   .isoformat()})
    assert wo["start_date"] <= wo["due_date"]
    wo = api.post(f"/work-orders/{wo['id']}/release", {"reserve": False}, status=200, version=wo["row_version"])
    c1 = next(c["id"] for c in wo["components"] if c["item"]["part_number"] == "WO-C1")
    api.post("/inventory/postings", {"type": "wo_issue", "lines": [{"wo_component_id": c1,
                                                                     "location_id": w["STORES"]["id"], "qty": 1}]})
    wo = api.get(f"/work-orders/{wo['id']}")
    r = api.raw("POST", f"/work-orders/{wo['id']}/cancel", json={}, headers={"If-Match": f'"{wo["row_version"]}"'})
    # 7.1: the first issue moves the WO to in_progress, so the state check answers first (MFG_INVALID_STATE);
    # WO_HAS_TRANSACTIONS is only reachable for a released WO with transactions (spec ambiguity, reported)
    assert r.status_code == 409 and r.json()["error"]["code"] in ("WO_HAS_TRANSACTIONS", "MFG_INVALID_STATE"), r.text
    r = api.raw("PUT", f"/work-orders/{wo['id']}", json={
        "item_id": w["P"]["id"], "qty": 2, "due_date": wo["due_date"], "start_date": wo["start_date"],
        "priority": 5, "components": [{"id": c1, "item_id": w["WO-C1"]["id"], "required_qty": 0.0}]},
        headers={"If-Match": f'"{wo["row_version"]}"'})
    assert r.status_code == 422 and r.json()["error"]["code"] == "WO_COMPONENT_BELOW_ISSUED", r.text
