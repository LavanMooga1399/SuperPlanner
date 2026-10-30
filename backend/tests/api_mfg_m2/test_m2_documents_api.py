"""B1/B3 (M2-DESIGN 3.2-3.7, 5-7, 12.3): locations, suppliers, item-suppliers; POs with staggered schedules and
partial receipts; the PR flow and conversion (with idempotent replay, C17); demand orders; work orders with
reservations, kitting, issues and receipts."""

from __future__ import annotations

from datetime import date, timedelta

from apimfgm2_helpers import Api, im


def _sched(days: int, qty: float, **kw) -> dict:
    return {"requested_date": (date.today() + timedelta(days=days)).isoformat(), "qty": qty, **kw}


def test_master_crud_and_rules(api: Api):
    a = api.location("A", receipt_default=True)
    b = api.location("B", receipt_default=True)
    assert [x["receipt_default"] for x in api.get("/locations")["items"]] == [False, True]
    api.err("POST", "/locations", 409, "MFG_DUPLICATE_KEY", json={"code": "A", "name": "x", "kind": "stores"})
    api.put(f"/locations/{a['id']}", {"code": "A", "name": "Alpha", "kind": "stores"}, 2)
    api.delete(f"/locations/{b['id']}", b["row_version"])
    sup = api.supplier("S1", lead_time_days=20, currency="INR")
    s2 = api.supplier("S2")
    it = api.item("C-1", lead_time_days=30)
    mk = api.item("M-1", "make")
    api.err("POST", "/item-suppliers", 422, "MFG_ITEM_NOT_BUY", json={"item_id": mk["id"], "supplier_id": sup["id"]})
    r1 = api.post("/item-suppliers", {"item_id": it["id"], "supplier_id": sup["id"], "preferred": True,
                                      "unit_price": 3})
    r2 = api.post("/item-suppliers", {"item_id": it["id"], "supplier_id": s2["id"], "preferred": True})
    api.err("POST", "/item-suppliers", 409, "MFG_DUPLICATE_KEY", json={"item_id": it["id"], "supplier_id": sup["id"]})
    rows = api.get("/item-suppliers", item_id=it["id"])["items"]
    assert [(r["id"], r["preferred"]) for r in rows] == [(r2["id"], True), (r1["id"], False)]
    api.err("GET", "/item-suppliers", 422, "VALIDATION_ERROR")
    got = api.get(f"/suppliers/{sup['id']}")
    assert got["item_count"] == 1 and got["items"][0]["item"]["part_number"] == "C-1"
    assert api.get("/suppliers")["items"][0]["item_count"] == 1


def _po_setup(api: Api) -> dict:
    sup = api.supplier("S1", currency="INR")
    it = api.item("FPGA", receiving_days=2)
    api.post("/item-suppliers", {"item_id": it["id"], "supplier_id": sup["id"], "preferred": True, "unit_price": 10})
    loc = api.location("GI", "inspection", receipt_default=True)
    return {"sup": sup, "it": it, "loc": loc}


def test_po_staggered_receipts_status_and_board(api: Api):
    x = _po_setup(api)
    api.err("POST", "/purchase-orders", 422, "PUR_SUPPLIER_REQUIRED",
            json={"lines": [{"item_id": x["it"]["id"], "schedules": [_sched(5, 1)]}]})
    po = api.post("/purchase-orders", {"supplier_id": x["sup"]["id"], "lines": [{"item_id": x["it"]["id"], "schedules": [
        _sched(-3, 30), _sched(20, 30, confirmed_date=(date.today() + timedelta(days=30)).isoformat()),
        _sched(40, 30)]}]})
    assert po["number"] == "PO-000001" and po["status"] == "draft" and po["currency"] == "INR"
    ln = po["lines"][0]
    assert ln["line_no"] == 10 and ln["unit_price"] == 10 and ln["qty"] == 90 and po["value"] == 900
    s1, s2 = ln["schedules"][0], ln["schedules"][1]
    assert s1["overdue"] and s1["overdue_days"] == 3 and po["overdue_count"] == 1
    assert s2["dock_date"] == (date.today() + timedelta(days=30)).isoformat()
    assert s2["available_date"] == (date.today() + timedelta(days=32)).isoformat()
    body = {"type": "po_receipt", "lines": [{"schedule_id": s1["id"], "qty": 12}]}
    api.err("POST", "/inventory/postings", 409, "MFG_INVALID_STATE", json=body)
    po = api.post(f"/purchase-orders/{po['id']}/issue", version=po["row_version"], status=200)
    rec = api.post("/inventory/postings", body)
    assert rec["lines"][0]["location"]["code"] == "GI" and rec["lines"][0]["ref"]["label"] == f"{po['number']} / 10 / 1"
    po = api.get(f"/purchase-orders/{po['id']}")
    assert po["status"] == "partially_received" and po["lines"][0]["received_qty"] == 12 and len(po["receipts"]) == 1
    api.err("POST", "/inventory/postings", 409, "PUR_OVER_RECEIPT",
            json={"type": "po_receipt", "lines": [{"schedule_id": s1["id"], "qty": 19}]})
    board = api.get("/purchasing/schedule", overdue_only="true")
    assert board["total"] == 1 and board["items"][0]["open_qty"] == 18
    # PUT: cannot reduce below received; stale If-Match after the receipt
    put = {"supplier_id": x["sup"]["id"], "lines": [{"id": ln["id"], "item_id": x["it"]["id"], "schedules": [
        {"id": s["id"], "seq": s["seq"], "requested_date": s["requested_date"], "qty": s["qty"]}
        for s in po["lines"][0]["schedules"]]}]}
    put["lines"][0]["schedules"][0]["qty"] = 10
    api.err("PUT", f"/purchase-orders/{po['id']}", 422, "PUR_QTY_BELOW_RECEIVED", json=put,
            headers=im(po["row_version"]))
    put["lines"][0]["schedules"][0]["qty"] = 12
    api.req("PUT", f"/purchase-orders/{po['id']}", 412, json=put, headers=im(po["row_version"] - 1))
    po2 = api.put(f"/purchase-orders/{po['id']}", put, po["row_version"])
    assert po2["lines"][0]["schedules"][0]["open_qty"] == 0
    put["lines"][0]["schedules"] = put["lines"][0]["schedules"][1:]
    api.err("PUT", f"/purchase-orders/{po['id']}", 422, "PUR_SCHEDULE_HAS_RECEIPTS", json=put,
            headers=im(po2["row_version"]))
    api.err("POST", f"/purchase-orders/{po['id']}/cancel", 409, "MFG_INVALID_STATE", json={},
            headers=im(po2["row_version"]))
    closed = api.post(f"/purchase-orders/{po['id']}/close", version=po2["row_version"], status=200)
    assert closed["status"] == "closed" and closed["lines"][0]["open_qty"] == 0
    api.err("PUT", f"/purchase-orders/{po['id']}", 409, "MFG_DOC_READONLY", json=put,
            headers=im(closed["row_version"]))
    lst = api.get("/purchase-orders", status="closed")
    assert lst["total"] == 1 and lst["items"][0]["line_count"] == 1


def test_pr_flow_self_approval_reject_convert_and_replay(api: Api):
    x = _po_setup(api)
    pr = api.post("/purchase-requests", {"lines": [{"item_id": x["it"]["id"], "schedules": [_sched(30, 5),
                                                                                             _sched(60, 5)]}]})
    assert pr["number"] == "PR-000001" and pr["supplier"] is None
    pr = api.post(f"/purchase-requests/{pr['id']}/submit", version=pr["row_version"], status=200)
    assert pr["status"] == "submitted" and pr["submitted_by"]["id"] == "usr_local"
    pr = api.post(f"/purchase-requests/{pr['id']}/reject", {"reason": "too early"}, version=pr["row_version"],
                  status=200)
    assert pr["status"] == "rejected" and pr["rejected_reason"] == "too early"
    pr = api.post(f"/purchase-requests/{pr['id']}/revise", version=pr["row_version"], status=200)
    pr = api.post(f"/purchase-requests/{pr['id']}/submit", version=pr["row_version"], status=200)
    pr = api.post(f"/purchase-requests/{pr['id']}/approve", version=pr["row_version"], status=200)   # owner may
    api.err("POST", f"/purchase-requests/{pr['id']}/submit", 409, "MFG_INVALID_STATE", json={},
            headers=im(pr["row_version"]))
    h = {"Idempotency-Key": "conv-1", **im(pr["row_version"])}
    out = api.post(f"/purchase-requests/{pr['id']}/convert", {"issue": True}, headers=h)
    assert out["pr"]["status"] == "ordered" and out["po"]["status"] == "open"
    assert out["po"]["supplier"]["code"] == "S1" and out["po"]["lines"][0]["source_pr"]["number"] == pr["number"]
    assert len(out["po"]["lines"][0]["schedules"]) == 2
    assert out["pr"]["lines"][0]["converted_to"]["number"] == out["po"]["number"]
    r = api.req("POST", f"/purchase-requests/{pr['id']}/convert", 200, json={"issue": True}, headers=h)
    assert r.headers["Idempotent-Replay"] == "true" and r.json()["po"]["id"] == out["po"]["id"]
    api.err("POST", f"/purchase-requests/{pr['id']}/convert", 409, "INV_IDEMPOTENCY_CONFLICT", json={"issue": False},
            headers=h)
    api.err("POST", f"/purchase-requests/{pr['id']}/convert", 409, "MFG_INVALID_STATE", json={},
            headers=im(out["pr"]["row_version"]))
    api.err("DELETE", f"/purchase-requests/{pr['id']}", 409, "MFG_INVALID_STATE",
            headers=im(out["pr"]["row_version"]))


def test_demand_orders(api: Api):
    tpu = api.item("TPU", "make", serialized=True)
    ph = api.item("PH", "phantom")
    api.err("POST", "/demand-orders", 422, "DEM_ITEM_NOT_PLANNABLE", json={
        "demand_type": "customer", "lines": [{"item_id": ph["id"], "qty": 1, "due_date": "2026-12-01"}]})
    api.err("POST", "/demand-orders", 422, "DEM_SERIAL_QTY_MISMATCH", json={
        "demand_type": "customer", "lines": [{"item_id": tpu["id"], "qty": 2, "due_date": "2026-12-01",
                                              "serial_from": 1, "serial_to": 3}]})
    api.err("POST", "/demand-orders", 422, "DEM_SERIAL_OVERLAP", json={
        "demand_type": "customer", "lines": [{"item_id": tpu["id"], "qty": 2, "due_date": "2026-12-01",
                                              "serial_from": 1, "serial_to": 2},
                                             {"item_id": tpu["id"], "qty": 2, "due_date": "2026-12-02",
                                              "serial_from": 2, "serial_to": 3}]})
    o = api.post("/demand-orders", {"demand_type": "customer", "priority": 2, "lines": [
        {"item_id": tpu["id"], "qty": 2, "due_date": "2026-12-01", "serial_from": 1, "serial_to": 2},
        {"item_id": tpu["id"], "qty": 1, "due_date": "2026-12-10", "priority": 1}]})
    assert o["number"] == "DO-000001" and [x["line_no"] for x in o["lines"]] == [10, 20]
    assert [x["effective_priority"] for x in o["lines"]] == [2, 1] and o["lines"][0]["projection"] is None
    o = api.post(f"/demand-orders/{o['id']}/open", version=o["row_version"], status=200)
    put = {"demand_type": "customer", "priority": 3, "lines": [
        {"id": o["lines"][1]["id"], "line_no": 10, "item_id": tpu["id"], "qty": 4, "due_date": "2026-12-10"},
        {"id": o["lines"][0]["id"], "line_no": 20, "item_id": tpu["id"], "qty": 2, "due_date": "2026-12-01",
         "serial_from": 1, "serial_to": 2}]}
    o2 = api.put(f"/demand-orders/{o['id']}", put, o["row_version"])          # line numbers swapped
    assert [(x["line_no"], x["qty"]) for x in o2["lines"]] == [(10, 4), (20, 2)]
    lst = api.get("/demand-orders", status="open")
    assert lst["items"][0]["open_qty"] == 6 and lst["items"][0]["next_due"] == "2026-12-01"
    o3 = api.post(f"/demand-orders/{o['id']}/close", version=o2["row_version"], status=200)
    api.err("PUT", f"/demand-orders/{o['id']}", 409, "MFG_DOC_READONLY", json=put, headers=im(o3["row_version"]))
    api.err("DELETE", f"/demand-orders/{o['id']}", 409, "MFG_INVALID_STATE", headers=im(o3["row_version"]))


def _wo_plant(api: Api) -> dict:
    g = api.post("/groups", {"code": "G", "name": "G"})
    api.post("/lines", {"code": "L", "name": "L", "group_id": g["id"]})
    c1 = api.item("C1")
    c2 = api.item("C2")
    p = api.item("P", "make", lead_time_days=2)
    bom = api.post("/boms", {"item_id": p["id"], "lines": [{"find_number": "10", "child_item_id": c1["id"],
                                                             "qty_per": 2},
                                                            {"find_number": "20", "child_item_id": c2["id"],
                                                             "qty_per": 1}]})
    api.post(f"/boms/{bom['id']}/release", {"effective_from": "2026-01-01"}, version=bom["row_version"], status=200)
    rt = api.post("/routings", {"item_id": p["id"], "operations": [{"seq": 10, "name": "A", "group_id": g["id"],
                                                                     "run_minutes": 1}]})
    api.post(f"/routings/{rt['id']}/release", {"effective_from": "2026-01-01"}, version=rt["row_version"], status=200)
    st = api.location("ST")
    api.receive(c1["id"], st["id"], 15)
    return {"c1": c1, "c2": c2, "p": p, "st": st, "fg": api.location("FG")}


def test_work_order_flow_reserve_kitting_issue_receipt(api: Api):
    x = _wo_plant(api)
    due = (date.today() + timedelta(days=14)).isoformat()
    w = api.post("/work-orders", {"item_id": x["p"]["id"], "qty": 10, "due_date": due})
    assert w["status"] == "planned" and w["number"] == "WO-000001" and w["warnings"] == []
    assert {c["item"]["part_number"]: c["required_qty"] for c in w["components"]} == {"C1": 20, "C2": 10}
    assert w["bom"] is not None and w["start_date"] < due
    api.err("POST", "/work-orders", 422, "MFG_ITEM_NOT_MAKE", json={"item_id": x["c1"]["id"], "qty": 1,
                                                                     "due_date": due})
    w = api.post(f"/work-orders/{w['id']}/release", {"reserve": True}, version=w["row_version"], status=200)
    assert w["status"] == "released"
    res = {r["component_id"]: r for r in w["reserved"]}
    c1 = next(c for c in w["components"] if c["item"]["part_number"] == "C1")
    assert res[c1["id"]]["qty"] == 15 and res[c1["id"]]["shortage"] == 5
    kit = api.get(f"/work-orders/{w['id']}/kitting")
    assert kit["totals"] == {"components": 2, "short_components": 2, "kit_complete": False}
    chk = api.post("/work-orders/kitting-check", {}, status=200)
    assert {s["item"]["part_number"] for s in chk["items_short"]} == {"C1", "C2"}
    api.err("POST", "/inventory/postings", 409, "INV_INSUFFICIENT_STOCK", json={
        "type": "issue_misc", "reason_code": "S", "lines": [{"item_id": x["c1"]["id"], "location_id": x["st"]["id"],
                                                             "qty": 1}]})
    iss = api.post("/inventory/postings", {"type": "wo_issue", "lines": [
        {"wo_component_id": c1["id"], "location_id": x["st"]["id"], "qty": 15}]})
    assert iss["lines"][0]["ref"]["type"] == "wo"
    w = api.get(f"/work-orders/{w['id']}")
    assert w["status"] == "in_progress" and next(c for c in w["components"] if c["id"] == c1["id"])["issued_qty"] == 15
    api.post("/inventory/postings", {"type": "wo_receipt", "lines": [
        {"wo_id": w["id"], "location_id": x["fg"]["id"], "qty": 4, "scrap_qty": 1}]})
    w = api.get(f"/work-orders/{w['id']}")
    assert (w["qty_completed"], w["qty_scrapped"], w["open_qty"]) == (4, 1, 6)
    api.err("POST", f"/work-orders/{w['id']}/cancel", 409, "MFG_INVALID_STATE", json={}, headers=im(w["row_version"]))
    w = api.post(f"/work-orders/{w['id']}/complete", version=w["row_version"], status=200)
    assert w["status"] == "completed" and all(c["reserved_qty"] == 0 for c in w["components"])
    w = api.post(f"/work-orders/{w['id']}/close", version=w["row_version"], status=200)
    assert w["status"] == "closed" and w["closed_at"]
    lst = api.get("/work-orders", status=["closed"])
    assert lst["total"] == 1 and lst["items"][0]["component_count"] == 2


def test_wo_put_refresh_and_delete(api: Api):
    x = _wo_plant(api)
    due = (date.today() + timedelta(days=14)).isoformat()
    w = api.post("/work-orders", {"item_id": x["p"]["id"], "qty": 10, "due_date": due, "components": [
        {"item_id": x["c1"]["id"], "required_qty": 3}]})
    assert len(w["components"]) == 1
    w = api.post(f"/work-orders/{w['id']}/refresh-components", version=w["row_version"], status=200)
    assert len(w["components"]) == 2
    body = {"item_id": x["p"]["id"], "qty": 12, "due_date": due, "components": None}
    w = api.put(f"/work-orders/{w['id']}", body, w["row_version"])
    assert w["qty"] == 12
    api.err("PUT", f"/work-orders/{w['id']}", 422, "VALIDATION_ERROR", json={**body, "item_id": x["c1"]["id"]},
            headers=im(w["row_version"]))
    api.delete(f"/work-orders/{w['id']}", w["row_version"])
