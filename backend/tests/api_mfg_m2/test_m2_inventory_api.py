"""B2 (M2-DESIGN 4, 12.3 #97-105): postings of every type, idempotent replay, reversal, insufficient stock, lots,
balances, ledger filters, concurrency without lost updates."""

from __future__ import annotations

import threading
from datetime import date, timedelta

from fastapi.testclient import TestClient

from apimfgm2_helpers import Api, im, make_app


def _plant(api: Api) -> dict:
    p = {"res": api.item("R-1", standard_cost=2.0), "coat": api.item("COAT", uom="L", lot_controlled=True,
                                                                         shelf_life_days=100),
         "st": api.location("ST"), "ls": api.location("LS", "line_side"), "qu": api.location("QU", "quarantine"),
         "gi": api.location("GI", "inspection", receipt_default=True)}
    return p


def test_receipt_issue_transfer_count_adjust_and_ledger(api: Api):
    p = _plant(api)
    r = api.receive(p["res"]["id"], p["st"]["id"], 10, unit_cost=1.5)
    assert r["number"].startswith("TXN-") and r["lines"][0]["balance_after"] == 10 and r["lines"][0]["unit_cost"] == 1.5
    e = api.err("POST", "/inventory/postings", 409, "INV_INSUFFICIENT_STOCK", json={
        "type": "issue_misc", "reason_code": "SCRAP", "lines": [{"item_id": p["res"]["id"], "location_id": p["st"]["id"],
                                                                 "qty": 11}]})
    assert e["details"]["available"] == 10 and e["details"]["requested"] == 11 and "R-1" in e["message"]
    api.err("POST", "/inventory/postings", 422, "INV_REASON_REQUIRED", json={
        "type": "issue_misc", "lines": [{"item_id": p["res"]["id"], "location_id": p["st"]["id"], "qty": 1}]})
    api.err("POST", "/inventory/postings", 422, "INV_FRACTIONAL_QTY", json={
        "type": "receipt_misc", "lines": [{"item_id": p["res"]["id"], "location_id": p["st"]["id"], "qty": 1.5}]})
    api.post("/inventory/postings", {"type": "transfer", "lines": [
        {"item_id": p["res"]["id"], "from_location_id": p["st"]["id"], "to_location_id": p["ls"]["id"], "qty": 4}]})
    api.post("/inventory/postings", {"type": "count", "lines": [
        {"item_id": p["res"]["id"], "location_id": p["st"]["id"], "counted_qty": 5}]})
    api.post("/inventory/postings", {"type": "adjust", "reason_code": "FOUND", "lines": [
        {"item_id": p["res"]["id"], "location_id": p["ls"]["id"], "qty": -1}]})
    bal = api.get("/inventory/balances", item_id=p["res"]["id"])
    assert {b["location"]["code"]: b["qty_on_hand"] for b in bal["items"]} == {"ST": 5, "LS": 3}
    assert bal["totals"]["qty_on_hand"] == 8 and bal["totals"]["value"] == 16
    led = api.get("/inventory/transactions", item_id=p["res"]["id"])
    assert led["total"] == 5 and [t["seq"] for t in led["items"]] == sorted((t["seq"] for t in led["items"]),
                                                                              reverse=True)
    assert api.get("/inventory/transactions", location_id=p["ls"]["id"])["total"] == 2
    assert api.get("/inventory/postings", type="count")["total"] == 1
    stock = api.get(f"/items/{p['res']['id']}/stock")
    assert stock["totals"]["nettable"] == 8 and stock["latest_run"] is None


def test_lots_fefo_hold_and_expiry(api: Api):
    p = _plant(api)
    d = date.today()
    for code, exp in (("A", d + timedelta(days=30)), ("B", d + timedelta(days=5)), ("C", None)):
        body = {"item_id": p["coat"]["id"], "location_id": p["st"]["id"], "qty": 2, "lot_code": code}
        if exp:
            body["expires_on"] = exp.isoformat()
        api.post("/inventory/postings", {"type": "receipt_misc", "lines": [body]})
    api.err("POST", "/inventory/postings", 422, "INV_LOT_REQUIRED", json={"type": "receipt_misc", "lines": [
        {"item_id": p["coat"]["id"], "location_id": p["st"]["id"], "qty": 1}]})
    out = api.post("/inventory/postings", {"type": "issue_misc", "reason_code": "USE", "lines": [
        {"item_id": p["coat"]["id"], "location_id": p["st"]["id"], "qty": 3}]})
    assert [(t["lot"]["lot_code"], t["qty"]) for t in out["lines"]] == [("B", -2), ("A", -1)]
    lots = api.get("/lots", item_id=p["coat"]["id"])["items"]
    assert [x["lot_code"] for x in lots] == ["B", "A", "C"]
    c = next(x for x in lots if x["lot_code"] == "C")
    assert c["expires_on"] == (d + timedelta(days=100)).isoformat()           # shelf life
    upd = api.put(f"/lots/{c['id']}", {"expires_on": c["expires_on"], "hold": True}, c["row_version"])
    assert upd["hold"] and upd["row_version"] == 2
    api.err("POST", "/inventory/postings", 422, "INV_LOT_ON_HOLD", json={"type": "issue_misc", "reason_code": "X",
                                                                          "lines": [{"item_id": p["coat"]["id"],
                                                                                     "location_id": p["st"]["id"],
                                                                                     "qty": 1, "lot_code": "C"}]})
    api.post("/inventory/postings", {"type": "transfer", "lines": [
        {"item_id": p["coat"]["id"], "from_location_id": p["st"]["id"], "to_location_id": p["qu"]["id"], "qty": 2,
         "lot_code": "C"}]})


def test_idempotent_replay_conflict_and_reversal(api: Api):
    p = _plant(api)
    body = {"type": "receipt_misc", "lines": [{"item_id": p["res"]["id"], "location_id": p["st"]["id"], "qty": 5}]}
    a = api.post("/inventory/postings", body, headers={"Idempotency-Key": "grn-1"})
    r = api.req("POST", "/inventory/postings", 200, json=body, headers={"Idempotency-Key": "grn-1"})
    assert r.headers["Idempotent-Replay"] == "true" and r.json()["id"] == a["id"]
    api.err("POST", "/inventory/postings", 409, "INV_IDEMPOTENCY_CONFLICT",
            json={**body, "note": "other"}, headers={"Idempotency-Key": "grn-1"})
    api.err("POST", "/inventory/postings", 422, "VALIDATION_ERROR", json=body, headers={"Idempotency-Key": "bad key!"})
    assert api.get("/inventory/balances", item_id=p["res"]["id"])["totals"]["qty_on_hand"] == 5
    rev = api.post(f"/inventory/postings/{a['id']}/reverse", {"note": "wrong item"})
    assert rev["reversal_of"]["id"] == a["id"] and rev["lines"][0]["qty"] == -5
    assert api.get(f"/inventory/postings/{a['id']}")["reversed_by"]["id"] == rev["id"]
    api.err("POST", f"/inventory/postings/{a['id']}/reverse", 409, "INV_ALREADY_REVERSED", json={})
    api.err("POST", f"/inventory/postings/{rev['id']}/reverse", 409, "MFG_INVALID_STATE", json={})
    b = api.receive(p["res"]["id"], p["st"]["id"], 3)
    api.post("/inventory/postings", {"type": "issue_misc", "reason_code": "S", "lines": [
        {"item_id": p["res"]["id"], "location_id": p["st"]["id"], "qty": 2}]})
    api.err("POST", f"/inventory/postings/{b['id']}/reverse", 409, "INV_INSUFFICIENT_STOCK", json={})
    api.err("GET", f"/inventory/postings/pst_{'0' * 32}", 404, "NOT_FOUND")


def test_concurrent_postings_have_no_lost_update(db_url):
    app = make_app(db_url)
    with TestClient(app) as c:
        api = Api(c)
        p = _plant(api)
        api.receive(p["res"]["id"], p["st"]["id"], 1000)
        errors: list[str] = []

        def work(k: int) -> None:
            with TestClient(app) as cc:
                a = Api(cc)
                for j in range(10):
                    if (k + j) % 2:
                        r = a.req("POST", "/inventory/postings", json={"type": "receipt_misc", "lines": [
                            {"item_id": p["res"]["id"], "location_id": p["st"]["id"], "qty": 3}]})
                    else:
                        r = a.req("POST", "/inventory/postings", json={"type": "issue_misc", "reason_code": "S",
                                                                       "lines": [{"item_id": p["res"]["id"],
                                                                                  "location_id": p["st"]["id"],
                                                                                  "qty": 1}]})
                    if r.status_code != 201:
                        errors.append(r.text)

        ts = [threading.Thread(target=work, args=(k,)) for k in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert not errors, errors[:3]
        tot = api.get("/inventory/balances", item_id=p["res"]["id"])["totals"]["qty_on_hand"]
        assert tot == 1000 + 30 * 3 - 30 * 1
        led = api.get("/inventory/transactions", item_id=p["res"]["id"], limit=200)["items"]
        assert sum(t["qty"] for t in led) == tot


def test_if_match_and_lot_errors(api: Api):
    p = _plant(api)
    api.post("/inventory/postings", {"type": "receipt_misc", "lines": [
        {"item_id": p["coat"]["id"], "location_id": p["st"]["id"], "qty": 1, "lot_code": "Z"}]})
    lot = api.get("/lots", item_id=p["coat"]["id"])["items"][0]
    api.req("PUT", f"/lots/{lot['id']}", 428, json={"hold": True})
    api.req("PUT", f"/lots/{lot['id']}", 412, json={"hold": True}, headers=im(9))
