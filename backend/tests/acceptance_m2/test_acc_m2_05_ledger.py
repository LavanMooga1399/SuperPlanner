"""Gate 2 #5 (ledger integrity) + 4.5/4.6: a scripted plant day through the API (staggered PO with partial
receipts into inspection, inspection-to-stores transfer, lots with FEFO auto-pick, issues, adjustments, a count,
WO issue/return/receipt with automatic status changes, a shipment, reversals), then for every balance key
`balance == sum(transactions)`, running `balance_after` is consistent, and document quantities equal ledger sums.
Idempotency keys (replay / conflict), insufficient stock (nothing posted) and the DB backstops are checked too.
The PostgreSQL concurrency gate (MP8) lives in `test_acc_m2_05b_ledger_concurrency.py`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import pytest

from accm2_helpers import Api

ENDPOINTS = ("POST /locations", "POST /suppliers", "POST /inventory/postings", "GET /inventory/transactions",
             "GET /inventory/balances", "POST /inventory/postings/{posting_id}/reverse", "POST /purchase-orders",
             "POST /purchase-orders/{doc_id}/issue", "GET /purchase-orders/{doc_id}", "POST /work-orders",
             "POST /work-orders/{wo_id}/release", "GET /work-orders/{wo_id}", "POST /demand-orders",
             "POST /demand-orders/{order_id}/open", "GET /demand-orders/{order_id}")


def stores_world(api: Api) -> dict:
    api.need(*ENDPOINTS)
    w: dict = {}
    w["A"] = api.post("/items", {"part_number": "ACC-A", "make_buy": "buy", "lead_time_days": 10,
                                 "receiving_days": 1})
    w["L"] = api.post("/items", {"part_number": "ACC-LOT", "make_buy": "buy", "lead_time_days": 5,
                                 "lot_controlled": True})
    w["K"] = api.post("/items", {"part_number": "ACC-KG", "make_buy": "buy", "lead_time_days": 5, "uom": "KG"})
    w["P"] = api.post("/items", {"part_number": "ACC-P", "make_buy": "make", "lead_time_days": 2})
    for code, kind in (("STORES", "stores"), ("LS", "line_side"), ("GOODS-IN", "inspection"),
                       ("QUAR", "quarantine")):
        w[code] = api.post("/locations", {"code": code, "name": code, "kind": kind,
                                          "receipt_default": code == "GOODS-IN"})
    w["SUP"] = api.post("/suppliers", {"code": "SUP1", "name": "Supplier A (fictional)", "lead_time_days": 10})
    return w


def post(api: Api, type_: str, lines: list, status: int = 201, **kw) -> dict:
    return api.post("/inventory/postings", {"type": type_, "lines": lines, **kw}, status=status)


def ledger(api: Api) -> list[dict]:
    return sorted(api.all_pages("/inventory/transactions"), key=lambda t: t["seq"])


def balances(api: Api) -> list[dict]:
    return api.all_pages("/inventory/balances", only_nonzero="false")


def bkey(row: dict) -> tuple:
    return (row["item"]["id"], row["location"]["id"], (row["lot"] or {}).get("lot_code"))


def assert_ledger_integrity(api: Api) -> None:
    txns = ledger(api)
    sums: dict = defaultdict(float)
    for t in txns:
        sums[bkey(t)] += t["qty"]
        assert abs(t["balance_after"] - sums[bkey(t)]) < 1e-6, ("balance_after", t)
    rows = balances(api)
    have = {bkey(b): b for b in rows}
    assert set(have) == set(sums), (set(have) ^ set(sums))
    for k, b in have.items():
        assert abs(b["qty_on_hand"] - sums[k]) < 1e-6, (k, b["qty_on_hand"], sums[k])
        assert b["qty_on_hand"] >= -1e-9 and 0 <= b["qty_reserved"] <= b["qty_on_hand"] + 1e-6, b
        assert abs(b["qty_available"] - (b["qty_on_hand"] - b["qty_reserved"])) < 1e-6, b


def test_scripted_plant_day_keeps_the_ledger_consistent(api):
    w = stores_world(api)
    a, lot_item, kg, p = w["A"]["id"], w["L"]["id"], w["K"]["id"], w["P"]["id"]
    stores, ls, gin, quar = (w[c]["id"] for c in ("STORES", "LS", "GOODS-IN", "QUAR"))
    today = date.today()
    # --- staggered PO, partial receipts (one with an auto receipt-default location)
    po = api.post("/purchase-orders", {"number": "PO-ACC-1", "supplier_id": w["SUP"]["id"], "lines": [
        {"line_no": 10, "item_id": a, "unit_price": 2.5, "schedules": [
            {"seq": 1, "requested_date": (today - timedelta(days=3)).isoformat(), "qty": 50},
            {"seq": 2, "requested_date": (today + timedelta(days=20)).isoformat(), "qty": 50},
            {"seq": 3, "requested_date": (today + timedelta(days=40)).isoformat(), "qty": 50}]}]})
    assert po["status"] == "draft" and po["lines"][0]["qty"] == 150
    po = api.post(f"/purchase-orders/{po['id']}/issue", {}, status=200, version=po["row_version"])
    s1, s2, s3 = (sc["id"] for sc in sorted(po["lines"][0]["schedules"], key=lambda s: s["seq"]))
    assert po["lines"][0]["schedules"][0]["overdue"] in (True, False)
    overdue = {sc["seq"]: (sc["overdue"], sc["overdue_days"]) for sc in po["lines"][0]["schedules"]}
    assert overdue[1] == (True, 3) and overdue[2] == (False, 0)
    rec = post(api, "po_receipt", [{"schedule_id": s1, "location_id": None, "qty": 30}], note="GRN 1")
    assert rec["lines"][0]["location"]["id"] == gin and rec["lines"][0]["unit_cost"] == 2.5
    assert rec["lines"][0]["ref"]["type"] == "po" and rec["lines"][0]["ref"]["schedule_seq"] == 1
    po = api.get(f"/purchase-orders/{po['id']}")
    sc = {x["seq"]: x for x in po["lines"][0]["schedules"]}
    assert po["status"] == "partially_received"
    assert (sc[1]["received_qty"], sc[1]["open_qty"], sc[1]["overdue"]) == (30, 20, True)
    post(api, "po_receipt", [{"schedule_id": s1, "location_id": gin, "qty": 20},
                             {"schedule_id": s2, "location_id": stores, "qty": 10}])
    po = api.get(f"/purchase-orders/{po['id']}")
    sc = {x["seq"]: x for x in po["lines"][0]["schedules"]}
    assert (sc[1]["open_qty"], sc[1]["overdue"], sc[2]["received_qty"], po["lines"][0]["open_qty"]) == \
        (0, False, 10, 90)
    assert po["status"] == "partially_received"
    # --- inspection -> stores, transfer to line side
    post(api, "transfer", [{"item_id": a, "from_location_id": gin, "to_location_id": stores, "qty": 50}])
    post(api, "transfer", [{"item_id": a, "from_location_id": stores, "to_location_id": ls, "qty": 5}])
    err = api.error("POST", "/inventory/postings", 422, "INV_SAME_LOCATION", json={"type": "transfer", "lines": [
        {"item_id": a, "from_location_id": stores, "to_location_id": stores, "qty": 1}]})
    assert err
    # --- lots, FEFO auto-pick across lots
    post(api, "receipt_misc", [
        {"item_id": lot_item, "location_id": stores, "qty": 10, "lot_code": "LATE",
         "expires_on": (today + timedelta(days=300)).isoformat()},
        {"item_id": lot_item, "location_id": stores, "qty": 4, "lot_code": "EARLY",
         "expires_on": (today + timedelta(days=30)).isoformat()}])
    iss = post(api, "issue_misc", [{"item_id": lot_item, "location_id": stores, "qty": 6, "lot_code": None}],
               reason_code="SAMPLE")
    picks = [(ln["lot"]["lot_code"], ln["qty"]) for ln in iss["lines"]]
    assert picks == [("EARLY", -4), ("LATE", -2)], picks            # FEFO, one transaction per lot
    api.error("POST", "/inventory/postings", 422, "INV_LOT_REQUIRED", json={"type": "receipt_misc", "lines": [
        {"item_id": lot_item, "location_id": stores, "qty": 1, "lot_code": None}]})
    api.error("POST", "/inventory/postings", 422, "INV_LOT_NOT_ALLOWED", json={"type": "receipt_misc", "lines": [
        {"item_id": a, "location_id": stores, "qty": 1, "lot_code": "X"}]})
    api.error("POST", "/inventory/postings", 422, "INV_REASON_REQUIRED", json={"type": "issue_misc", "lines": [
        {"item_id": a, "location_id": stores, "qty": 1}]})
    # --- adjustments, count, non-count UoM
    adj = post(api, "adjust", [{"item_id": a, "location_id": stores, "qty": -2}], reason_code="DAMAGE")
    post(api, "adjust", [{"item_id": a, "location_id": stores, "qty": 3}], reason_code="FOUND")
    post(api, "receipt_misc", [{"item_id": kg, "location_id": stores, "qty": 1.2345674}])
    cnt = post(api, "count", [{"item_id": a, "location_id": stores, "counted_qty": 40}])
    assert [ln["txn_type"] for ln in cnt["lines"]] == ["adjust"] and cnt["lines"][0]["balance_after"] == 40
    assert api.balance(a, stores) == 40
    # --- WO issue / return / partial receipt, automatic status changes
    wo = api.post("/work-orders", {"number": "WO-ACC-1", "item_id": p, "qty": 10,
                                   "start_date": today.isoformat(), "due_date": (today + timedelta(days=3)).isoformat(),
                                   "components": [{"item_id": a, "required_qty": 20}]})
    comp = wo["components"][0]["id"]
    api.error("POST", "/inventory/postings", 409, "MFG_INVALID_STATE", json={"type": "wo_issue", "lines": [
        {"wo_component_id": comp, "location_id": stores, "qty": 1}]})          # planned WO: not issuable
    wo = api.post(f"/work-orders/{wo['id']}/release", {"reserve": True}, status=200, version=wo["row_version"])
    assert wo["status"] == "released" and wo["components"][0]["reserved_qty"] == 20
    post(api, "wo_issue", [{"wo_component_id": comp, "location_id": stores, "qty": 15}])
    wo = api.get(f"/work-orders/{wo['id']}")
    assert wo["status"] == "in_progress"
    c = wo["components"][0]
    assert (c["issued_qty"], c["reserved_qty"], c["open_qty"]) == (15, 5, 5)
    api.error("POST", "/inventory/postings", 422, "WO_OVER_ISSUE", json={"type": "wo_issue", "lines": [
        {"wo_component_id": comp, "location_id": stores, "qty": 6}]})
    post(api, "wo_return", [{"wo_component_id": comp, "location_id": stores, "qty": 3}])
    post(api, "wo_receipt", [{"wo_id": wo["id"], "location_id": stores, "qty": 4, "scrap_qty": 1}])
    wo = api.get(f"/work-orders/{wo['id']}")
    assert (wo["status"], wo["qty_completed"], wo["qty_scrapped"], wo["open_qty"]) == ("in_progress", 4, 1, 6)
    assert wo["components"][0]["issued_qty"] == 12
    # --- shipment against a demand line
    do = api.post("/demand-orders", {"number": "DO-ACC-1", "demand_type": "customer", "lines": [
        {"line_no": 10, "item_id": p, "qty": 3, "due_date": (today + timedelta(days=5)).isoformat()}]})
    do = api.post(f"/demand-orders/{do['id']}/open", {}, status=200, version=do["row_version"])
    line = do["lines"][0]["id"]
    api.error("POST", "/inventory/postings", 422, "DEM_OVER_SHIPMENT", json={"type": "ship", "lines": [
        {"demand_line_id": line, "location_id": stores, "qty": 4}]})
    post(api, "ship", [{"demand_line_id": line, "location_id": stores, "qty": 2}])
    do = api.get(f"/demand-orders/{do['id']}")
    assert (do["lines"][0]["shipped_qty"], do["lines"][0]["open_qty"], do["status"]) == (2, 1, "open")
    # --- reversal rules
    rev = api.post(f"/inventory/postings/{adj['id']}/reverse", {"note": "wrong"})
    assert rev["reversal_of"]["id"] == adj["id"] and rev["lines"][0]["qty"] == 2
    assert api.get(f"/inventory/postings/{adj['id']}")["reversed_by"]["id"] == rev["id"]
    api.error("POST", f"/inventory/postings/{adj['id']}/reverse", 409, "INV_ALREADY_REVERSED", json={"note": ""})
    api.error("POST", f"/inventory/postings/{rev['id']}/reverse", 409, "MFG_INVALID_STATE", json={"note": ""})
    # --- insufficient stock: 409, nothing posted (the whole multi-line posting is one transaction)
    before = len(ledger(api))
    row = [b for b in balances(api) if b["item"]["id"] == a and b["location"]["id"] == ls][0]
    have = row["qty_available"]
    e = api.error("POST", "/inventory/postings", 409, "INV_INSUFFICIENT_STOCK", json={"type": "issue_misc",
                  "reason_code": "SCRAP", "lines": [{"item_id": kg, "location_id": stores, "qty": 0.5},
                                                    {"item_id": a, "location_id": ls, "qty": have + 1}]})
    assert e["details"]["requested"] == have + 1 and e["details"]["available"] == have
    assert len(ledger(api)) == before and api.balance(kg, stores) == pytest.approx(1.234567)
    # --- integrity: balances == ledger sums; documents == ledger sums
    assert_ledger_integrity(api)
    txns = ledger(api)
    po = api.get(f"/purchase-orders/{po['id']}")
    for sc in po["lines"][0]["schedules"]:
        got = sum(t["qty"] for t in txns if t["txn_type"] == "po_receipt" and t["ref"]
                  and t["ref"]["schedule_seq"] == sc["seq"] and t["ref"]["id"] == po["id"])
        assert got == sc["received_qty"], sc
    wo = api.get(f"/work-orders/{wo['id']}")
    issued = -sum(t["qty"] for t in txns if t["txn_type"] in ("wo_issue", "wo_return") and t["item"]["id"] == a)
    assert issued == wo["components"][0]["issued_qty"]
    assert sum(t["qty"] for t in txns if t["txn_type"] == "wo_receipt") == wo["qty_completed"]
    assert -sum(t["qty"] for t in txns if t["txn_type"] == "ship") == 2
    assert all(t["actor"]["id"] for t in txns)


def test_fractional_backdate_and_inactive_location_rules(api):
    w = stores_world(api)
    stores = w["STORES"]["id"]
    api.error("POST", "/inventory/postings", 422, "INV_FRACTIONAL_QTY", json={"type": "receipt_misc", "lines": [
        {"item_id": w["A"]["id"], "location_id": stores, "qty": 1.5}]})
    old = (date.today() - timedelta(days=40)).isoformat()
    api.error("POST", "/inventory/postings", 422, "INV_BACKDATE_LIMIT", json={"type": "receipt_misc",
              "txn_date": old, "lines": [{"item_id": w["A"]["id"], "location_id": stores, "qty": 1}]})
    future = (date.today() + timedelta(days=2)).isoformat()
    api.error("POST", "/inventory/postings", 422, "INV_BACKDATE_LIMIT", json={"type": "receipt_misc",
              "txn_date": future, "lines": [{"item_id": w["A"]["id"], "location_id": stores, "qty": 1}]})
    q = w["QUAR"]
    q = api.put(f"/locations/{q['id']}", {"code": "QUAR", "name": "QUAR", "kind": "quarantine",
                                          "receipt_default": False, "active": False, "external_ref": None,
                                          "note": ""}, q["row_version"])
    api.error("POST", "/inventory/postings", 422, "INV_LOCATION_INACTIVE", json={"type": "receipt_misc", "lines": [
        {"item_id": w["A"]["id"], "location_id": q["id"], "qty": 1}]})
    assert ledger(api) == []


def test_idempotency_key_replay_and_conflict(api):
    w = stores_world(api)
    body = {"type": "receipt_misc", "lines": [{"item_id": w["A"]["id"], "location_id": w["STORES"]["id"],
                                               "qty": 7}]}
    h = {"Idempotency-Key": "grn-acc-0001"}
    first = api.raw("POST", "/inventory/postings", json=body, headers=h)
    assert first.status_code == 201, first.text
    again = api.raw("POST", "/inventory/postings", json=body, headers=h)
    assert again.status_code == 200 and again.headers.get("Idempotent-Replay") == "true", again.text
    assert again.json()["id"] == first.json()["id"]
    other = dict(body, lines=[dict(body["lines"][0], qty=8)])
    r = api.raw("POST", "/inventory/postings", json=other, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INV_IDEMPOTENCY_CONFLICT", r.text
    assert api.balance(w["A"]["id"], w["STORES"]["id"]) == 7 and len(ledger(api)) == 1
    bad = api.raw("POST", "/inventory/postings", json=body, headers={"Idempotency-Key": "x" * 300})
    assert bad.status_code == 422, bad.text


def test_db_backstops_reject_negative_stock(api, app):
    """4.5: CHECK (qty_on_hand >= 0), (qty_reserved >= 0), (qty_reserved <= qty_on_hand) fire even for raw SQL."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    w = stores_world(api)
    api.post_stock(w["A"]["id"], w["STORES"]["id"], 5)
    from superplanner.api.db.ownership import system_scope

    for sql in ("UPDATE mfg_inv_balances SET qty_on_hand = -1",
                "UPDATE mfg_inv_balances SET qty_reserved = -1",
                "UPDATE mfg_inv_balances SET qty_reserved = qty_on_hand + 1"):
        with pytest.raises(IntegrityError):
            with system_scope(), app.state.ctx.db.write() as s:
                s.execute(text(sql))
    assert_ledger_integrity(api)
