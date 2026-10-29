"""Gate 2 #7: purchasing loop across roles (one approval step, user decision Q3). A planner raises and submits a
PR with two staggered schedules (one already past), the planner cannot approve (403), a member who submitted
cannot approve their own PR (409 `PUR_SELF_APPROVAL`), the `approver` member approves, the purchaser converts to
a PO and issues it, the store keeper receives part of schedule 1; the past schedule stays overdue with its open
remainder, and the next MRP run uses only the open remainder as supply.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from accm2_helpers import MEMBER_ENDPOINTS, MRP_ENDPOINTS, add_member, mrp_item

OWNER = "owner@pur-m2.example.com"


@pytest.fixture
def team(acc):
    owner = acc.user(OWNER)
    owner.need(*MEMBER_ENDPOINTS, *MRP_ENDPOINTS, "POST /purchase-requests", "POST /purchase-requests/{doc_id}/submit",
               "POST /purchase-requests/{doc_id}/approve", "POST /purchase-requests/{doc_id}/convert",
               "POST /purchase-orders/{doc_id}/issue", "POST /inventory/postings")
    t = {r: add_member(acc, OWNER, f"{r}@pur-m2.example.com", [r])
         for r in ("planner", "approver", "purchaser", "store_keeper")}
    t["planner_approver"] = add_member(acc, OWNER, "pa@pur-m2.example.com", ["planner", "approver"])
    item = owner.post("/items", {"part_number": "PUR-A", "make_buy": "buy", "lead_time_days": 20})
    loc = owner.post("/locations", {"code": "STORES", "name": "Stores", "kind": "stores", "receipt_default": True})
    sup = owner.post("/suppliers", {"code": "SUP-P", "name": "Supplier P (fictional)"})
    owner.post("/item-suppliers", {"item_id": item["id"], "supplier_id": sup["id"], "preferred": True,
                                   "unit_price": 4.0})
    return acc, owner, t, item, loc, sup


def _pr_body(item_id: str, today: date) -> dict:
    return {"lines": [{"item_id": item_id, "schedules": [
        {"requested_date": (today - timedelta(days=4)).isoformat(), "qty": 40},
        {"requested_date": (today + timedelta(days=30)).isoformat(), "qty": 60}]}]}


def test_pr_approval_conversion_partial_receipt_and_mrp_remainder(team):
    acc, owner, t, item, loc, sup = team
    today = date.today()
    pr = t["planner"].post("/purchase-requests", _pr_body(item["id"], today))
    assert pr["status"] == "draft" and pr["number"].startswith("PR-")
    assert pr["lines"][0]["unit_price"] == 4.0                      # item-supplier price on create
    pr = t["planner"].post(f"/purchase-requests/{pr['id']}/submit", {}, status=200, version=pr["row_version"])
    assert pr["status"] == "submitted" and pr["submitted_by"] == acc.uid("planner@pur-m2.example.com")
    r = t["planner"].raw("POST", f"/purchase-requests/{pr['id']}/approve", json={"note": ""},
                         headers={"If-Match": f'"{pr["row_version"]}"'})
    assert r.status_code == 403 and r.json()["error"]["code"] == "MFG_FORBIDDEN"
    # self-approval refused for a member holding both roles
    own = t["planner_approver"].post("/purchase-requests", _pr_body(item["id"], today))
    own = t["planner_approver"].post(f"/purchase-requests/{own['id']}/submit", {}, status=200,
                                     version=own["row_version"])
    r = t["planner_approver"].raw("POST", f"/purchase-requests/{own['id']}/approve", json={"note": ""},
                                  headers={"If-Match": f'"{own["row_version"]}"'})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PUR_SELF_APPROVAL", r.text
    # stale If-Match -> 412, missing -> 428
    assert t["approver"].raw("POST", f"/purchase-requests/{pr['id']}/approve", json={"note": ""},
                             headers={"If-Match": '"999"'}).status_code == 412
    assert t["approver"].raw("POST", f"/purchase-requests/{pr['id']}/approve", json={"note": ""}).status_code == 428
    pr = t["approver"].post(f"/purchase-requests/{pr['id']}/approve", {"note": "ok"}, status=200,
                            version=pr["row_version"])
    assert pr["status"] == "approved" and pr["approved_by"] == acc.uid("approver@pur-m2.example.com")
    # wrong-state action carries allowed_from
    r = t["planner"].raw("POST", f"/purchase-requests/{pr['id']}/submit", json={},
                         headers={"If-Match": f'"{pr["row_version"]}"'})
    assert r.status_code == 409 and r.json()["error"]["details"]["allowed_from"] == ["draft"]
    conv = t["purchaser"].post(f"/purchase-requests/{pr['id']}/convert",
                               {"line_ids": None, "supplier_id": None, "number": None, "issue": True},
                               version=pr["row_version"], headers={"Idempotency-Key": "pr-conv-1"})
    po, pr = conv["po"], conv["pr"]
    assert pr["status"] == "ordered" and pr["lines"][0]["status"] == "converted"
    assert po["status"] == "open" and po["supplier"]["id"] == sup["id"]
    assert po["lines"][0]["source_pr"]["doc_id"] == pr["id"]
    assert [s["qty"] for s in sorted(po["lines"][0]["schedules"], key=lambda s: s["seq"])] == [40, 60]
    s1 = min(po["lines"][0]["schedules"], key=lambda s: s["seq"])
    # store keeper: partial receipt of schedule 1 (location null -> receipt default)
    t["store_keeper"].post("/inventory/postings", {"type": "po_receipt", "lines": [
        {"schedule_id": s1["id"], "location_id": None, "qty": 15}]})
    po = owner.get(f"/purchase-orders/{po['id']}")
    sc = {s["seq"]: s for s in po["lines"][0]["schedules"]}
    assert po["status"] == "partially_received"
    assert (sc[1]["received_qty"], sc[1]["open_qty"], sc[1]["overdue"], sc[1]["overdue_days"]) == (15, 25, True, 4)
    assert po["overdue_count"] == 1 and po["receipts"]
    board = owner.get("/purchasing/schedule", overdue_only="true")["items"]
    assert [b["schedule_id"] for b in board] == [s1["id"]]
    # over-receipt above tolerance (0 %) -> 409 with details
    r = t["store_keeper"].raw("POST", "/inventory/postings", json={"type": "po_receipt", "lines": [
        {"schedule_id": s1["id"], "location_id": loc["id"], "qty": 26}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PUR_OVER_RECEIPT"
    assert r.json()["error"]["details"]["open_qty"] == 25
    # purchaser's stale PUT after the receipt gets 412 (receipt bumped row_version, 4.5)
    r = t["purchaser"].raw("PUT", f"/purchase-orders/{po['id']}", json={}, headers={"If-Match": '"1"'})
    assert r.status_code in (412, 422)
    # the next MRP run uses only the open remainder
    run = owner.run_mrp()
    plan = mrp_item(owner, run["id"], item["id"])
    po_sup = sorted((s["qty"] for s in plan["supplies"] if s["kind"] == "po"))
    assert po_sup == [25, 60], plan["supplies"]
    stock = [s for s in plan["supplies"] if s["kind"] == "stock"]
    assert sum(s["qty"] for s in stock) == 15
    # the submitted own PR is supply too (5.5), the ordered PR is not
    pr_sup = [s for s in plan["supplies"] if s["kind"] == "pr"]
    assert sorted(s["qty"] for s in pr_sup) == [40, 60]
