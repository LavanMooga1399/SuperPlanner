"""WP-D adversarial inputs against the M2 API (M2-DESIGN 3, 4.1, 5, 6, 7, 8.2, 10, 12.1-12.2): out-of-range and
malformed values, limits, cross-tenant ids, header abuse, wrong states, combined-line stock checks, and the check
order (workspace -> auth -> permission -> body -> lookup -> If-Match -> state -> rules). Nothing may answer 5xx;
every rejection uses the error envelope with the documented code.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from accm2_helpers import Api

TODAY = date.today()
FAKE = "loc_" + "0" * 32


def _err(r, status: int, code: str | None = None) -> dict:
    assert r.status_code == status, (r.status_code, r.text[:1500])
    body = r.json()
    assert "error" in body and body["error"]["code"], body
    if code:
        assert body["error"]["code"] == code, body
    return body["error"]


@pytest.fixture
def w(api: Api):
    api.need("POST /locations", "POST /inventory/postings", "POST /purchase-orders", "POST /demand-orders",
             "POST /work-orders", "POST /mrp/runs", "POST /suppliers")
    out = {"api": api}
    out["loc"] = api.post("/locations", {"code": "STORES", "name": "Stores", "kind": "stores"})
    out["A"] = api.post("/items", {"part_number": "ADV-A", "make_buy": "buy", "lead_time_days": 3})
    out["S"] = api.post("/items", {"part_number": "ADV-S", "make_buy": "make", "serialized": True,
                                   "lead_time_days": 1})
    out["PH"] = api.post("/items", {"part_number": "ADV-PH", "make_buy": "phantom"})
    out["sup"] = api.post("/suppliers", {"code": "ADV", "name": "Adversary (fictional)"})
    api.post_stock(out["A"]["id"], out["loc"]["id"], 10)
    return out


def _receipt(w, **line) -> dict:
    base = {"item_id": w["A"]["id"], "location_id": w["loc"]["id"], "qty": 1}
    base.update(line)
    return {"type": "receipt_misc", "lines": [base]}


@pytest.mark.parametrize("qty", [0, -1, 1_000_001, "1e309", "ten", None, 1e-12, [1]])
def test_posting_quantities_out_of_range(w, qty):
    r = w["api"].raw("POST", "/inventory/postings", json=_receipt(w, qty=qty))
    if r.status_code < 300:
        pytest.fail(f"qty {qty!r} accepted on a count-UoM item: posted line qty "
                    f"{[ln['qty'] for ln in r.json()['lines']]}, balance after "
                    f"{[ln['balance_after'] for ln in r.json()['lines']]}")
    _err(r, 422)


@pytest.mark.parametrize("body", [
    {"type": "teleport", "lines": [{}]},
    {"type": "receipt_misc", "lines": []},
    {"type": "receipt_misc"},
    {"type": "adjust", "reason_code": "X", "lines": [{"item_id": None, "location_id": None, "qty": 0}]},
    {"type": "receipt_misc", "lines": [{"item_id": "itm_bad", "location_id": "loc_bad", "qty": 1}]},
    {"type": "receipt_misc", "txn_date": "2026-13-45", "lines": [{}]},
    {"type": "receipt_misc", "note": "x" * 501, "lines": [{}]},
    {"type": "receipt_misc", "lines": [{}], "unexpected": 1},
    [],
    "receipt_misc",
])
def test_malformed_posting_bodies(w, body):
    _err(w["api"].raw("POST", "/inventory/postings", json=body), 422)


def test_posting_limits_and_combined_stock_check(w):
    api = w["api"]
    lines = [{"item_id": w["A"]["id"], "location_id": w["loc"]["id"], "qty": 1}] * 501
    _err(api.raw("POST", "/inventory/postings", json={"type": "receipt_misc", "lines": lines}), 422)
    # two lines on the same balance, each within stock but together above it -> 409, nothing posted
    two = [{"item_id": w["A"]["id"], "location_id": w["loc"]["id"], "qty": 6}] * 2
    _err(api.raw("POST", "/inventory/postings", json={"type": "issue_misc", "reason_code": "SCRAP", "lines": two}),
         409, "INV_INSUFFICIENT_STOCK")
    assert api.balance(w["A"]["id"], w["loc"]["id"]) == 10
    # well-formed but unknown ids inside a body -> 422 MFG_UNKNOWN_REFERENCE; unknown path ids -> 404
    _err(api.raw("POST", "/inventory/postings", json=_receipt(w, location_id=FAKE)), 422, "MFG_UNKNOWN_REFERENCE")
    for path in ("/inventory/postings/pst_nope", "/purchase-orders/../../items",
                 "/mrp/runs/' OR 1=1 --", "/demand-orders/" + "a" * 500):
        r = api.raw("GET", path)
        assert r.status_code == 404, (path, r.status_code, r.text[:300])


@pytest.mark.parametrize("key", [" ", "k" * 300, "bad key with spaces", "semi;colon"])
def test_bad_idempotency_keys(w, key):
    r = w["api"].raw("POST", "/inventory/postings", json=_receipt(w), headers={"Idempotency-Key": key})
    assert r.status_code in (400, 422), (key, r.status_code, r.text[:300])
    assert w["api"].balance(w["A"]["id"], w["loc"]["id"]) == 10


def test_search_and_filter_parameters_are_inert(w):
    api = w["api"]
    for q in ("%", "_", "\\", "' OR '1'='1", "x" * 2000):
        r = api.raw("GET", "/inventory/balances", params={"q": q})
        assert r.status_code in (200, 422), (q, r.status_code)
        if r.status_code == 200:
            assert r.json()["items"] == [], q          # wildcards are escaped (M1 9.1)
    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"sort": "drop table"}, {"from": "yesterday"}):
        _err(api.raw("GET", "/inventory/transactions", params=params), 422)


@pytest.mark.parametrize("method,path,params", [
    ("GET", "/work-orders/%00", None), ("GET", "/inventory/postings/%00", None), ("GET", "/items/%00", None),
    ("GET", "/inventory/balances", {"q": "\u0000"}), ("GET", "/purchase-orders", {"q": "a\u0000b"}),
])
def test_nul_bytes_never_reach_the_database(w, method, path, params):
    """PostgreSQL rejects NUL in text: ids/search terms with U+0000 must answer 404/422 (or an empty page), not 500."""
    r = w["api"].raw(method, path, params=params)
    assert r.status_code in (200, 404, 422), (path, params, r.status_code, r.text[:300])
    if r.status_code == 200:
        assert r.json()["items"] == []


def test_purchase_document_validation(w):
    api = w["api"]
    sched = {"requested_date": (TODAY + timedelta(days=5)).isoformat(), "qty": 5}
    line = {"item_id": w["A"]["id"], "schedules": [sched]}
    _err(api.raw("POST", "/purchase-orders", json={"lines": [line]}), 422, "PUR_SUPPLIER_REQUIRED")
    po = {"supplier_id": w["sup"]["id"]}
    _err(api.raw("POST", "/purchase-orders", json={**po, "lines": []}), 422)
    _err(api.raw("POST", "/purchase-orders", json={**po, "lines": [{**line, "schedules": [sched] * 101}]}), 422)
    _err(api.raw("POST", "/purchase-orders", json={**po, "lines": [{**line, "schedules": [{**sched, "qty": 0}]}]}),
         422)
    _err(api.raw("POST", "/purchase-orders", json={**po, "lines": [{**line, "schedules": [
        {**sched, "requested_date": "9999-12-31"}]}]}), 422)
    _err(api.raw("POST", "/purchase-orders", json={**po, "lines": [{**line, "item_id": w["S"]["id"]}]}), 422,
         "MFG_ITEM_NOT_BUY")
    _err(api.raw("POST", "/purchase-orders", json={**po, "lines": [{**line, "schedules": [{**sched, "qty": 2.5}]}]}),
         422, "INV_FRACTIONAL_QTY")
    _err(api.raw("POST", "/purchase-orders", json={**po, "number": "bad number!", "lines": [line]}), 422)
    a = api.post("/purchase-orders", {**po, "number": "PO-ADV-1", "lines": [line]})
    _err(api.raw("POST", "/purchase-orders", json={**po, "number": "PO-ADV-1", "lines": [line]}), 409,
         "MFG_DUPLICATE_KEY")
    # receipts against a draft PO -> 409 state; If-Match rules on actions
    sid = a["lines"][0]["schedules"][0]["id"]
    _err(api.raw("POST", "/inventory/postings", json={"type": "po_receipt", "lines": [
        {"schedule_id": sid, "location_id": w["loc"]["id"], "qty": 1}]}), 409, "MFG_INVALID_STATE")
    _err(api.raw("POST", f"/purchase-orders/{a['id']}/issue", json={}), 428)
    _err(api.raw("POST", f"/purchase-orders/{a['id']}/issue", json={}, headers={"If-Match": '"77"'}), 412)
    a = api.post(f"/purchase-orders/{a['id']}/issue", {}, status=200, version=a["row_version"])
    api.post("/inventory/postings", {"type": "po_receipt", "lines": [
        {"schedule_id": sid, "location_id": w["loc"]["id"], "qty": 2}]})
    a = api.get(f"/purchase-orders/{a['id']}")
    body = {"supplier_id": w["sup"]["id"], "number": "PO-ADV-1", "lines": [
        {"id": a["lines"][0]["id"], "line_no": 10, "item_id": w["A"]["id"], "schedules": [
            {"id": sid, "seq": 1, "requested_date": sched["requested_date"], "qty": 1}]}]}
    _err(api.raw("PUT", f"/purchase-orders/{a['id']}", json=body, headers={"If-Match": f'"{a["row_version"]}"'}),
         422, "PUR_QTY_BELOW_RECEIVED")
    body["lines"][0]["schedules"] = [{"seq": 2, "requested_date": sched["requested_date"], "qty": 5}]
    _err(api.raw("PUT", f"/purchase-orders/{a['id']}", json=body, headers={"If-Match": f'"{a["row_version"]}"'}),
         422, "PUR_SCHEDULE_HAS_RECEIPTS")
    _err(api.raw("POST", f"/purchase-orders/{a['id']}/cancel", json={},
                 headers={"If-Match": f'"{a["row_version"]}"'}), 409)
    _err(api.raw("DELETE", f"/purchase-orders/{a['id']}", headers={"If-Match": f'"{a["row_version"]}"'}), 409)


def test_demand_and_work_order_validation(w):
    api = w["api"]
    due = (TODAY + timedelta(days=20)).isoformat()

    def do(**line):
        return api.raw("POST", "/demand-orders", json={"demand_type": "customer", "lines": [
            {"item_id": w["S"]["id"], "qty": 3, "due_date": due, **line}]})

    _err(do(serial_from=1, serial_to=5), 422, "DEM_SERIAL_QTY_MISMATCH")
    _err(do(serial_from=5), 422)
    _err(do(serial_from=5, serial_to=3), 422)
    _err(do(item_id=w["A"]["id"], serial_from=1, serial_to=3), 422, "MFG_SERIAL_NOT_ALLOWED")
    _err(do(item_id=w["PH"]["id"]), 422, "DEM_ITEM_NOT_PLANNABLE")
    _err(do(priority=0), 422)
    _err(do(priority=10), 422)
    r = api.raw("POST", "/demand-orders", json={"demand_type": "customer", "lines": [
        {"item_id": w["S"]["id"], "qty": 3, "due_date": due, "serial_from": 1, "serial_to": 3},
        {"item_id": w["S"]["id"], "qty": 3, "due_date": due, "serial_from": 3, "serial_to": 5}]})
    _err(r, 422, "DEM_SERIAL_OVERLAP")
    _err(api.raw("POST", "/demand-orders", json={"demand_type": "gift", "lines": [
        {"item_id": w["A"]["id"], "qty": 1, "due_date": due}]}), 422)
    _err(api.raw("POST", "/work-orders", json={"item_id": w["A"]["id"], "qty": 1, "due_date": due}), 422,
         "MFG_ITEM_NOT_MAKE")
    _err(api.raw("POST", "/work-orders", json={"item_id": w["S"]["id"], "qty": 1, "due_date": due,
                                               "start_date": (TODAY + timedelta(days=30)).isoformat()}), 422)
    _err(api.raw("POST", "/work-orders", json={"item_id": w["S"]["id"], "qty": 1.5, "due_date": due}), 422)
    _err(api.raw("POST", "/work-orders", json={"item_id": w["S"]["id"], "qty": 2, "due_date": due,
                                               "serial_from": 1, "serial_to": 5}), 422)
    _err(api.raw("POST", "/work-orders", json={"item_id": w["S"]["id"], "qty": 1, "due_date": due,
                                               "components": [{"item_id": w["PH"]["id"], "required_qty": 1}]}), 422)


@pytest.mark.parametrize("params", [
    {"horizon_days": 6}, {"horizon_days": 731}, {"allocation": "random"}, {"alternates": "always"},
    {"label": "x" * 101}, {"protect_programs": [f"P{i}" for i in range(21)]},
    {"extra_demand": [{"item_id": "itm_" + "0" * 32, "qty": 1, "due_date": "2026-12-01"}] * 201},
    {"lead_time_overrides": [{"item_id": "itm_" + "0" * 32, "lead_time_days": 1}] * 1001},
    {"as_of": "not-a-date"}, {"unknown_param": True}, {"extra_demand": [{"qty": -1}]},
])
def test_mrp_params_validation(w, params):
    _err(w["api"].raw("POST", "/mrp/runs", json=params), 422)
    assert w["api"].get("/mrp/runs")["items"] == []


def test_mrp_preflight_unknown_override(w):
    api = w["api"]
    r = api.raw("POST", "/mrp/runs", json={"extra_demand": [{"item_id": "itm_" + "f" * 32, "qty": 1,
                                                             "due_date": (TODAY + timedelta(days=9)).isoformat()}]})
    err = _err(r, 422)
    assert err["code"] in ("MRP_PREFLIGHT_FAILED", "MFG_UNKNOWN_REFERENCE", "MFG_DATA_HEALTH_FAILED"), err
    assert api.get("/mrp/runs")["items"] == []                 # failed run rows are deleted (8.14)


def test_cross_tenant_ids_are_invisible(acc):
    """Ids of another user's plant: in a body -> 422 MFG_UNKNOWN_REFERENCE; in a path -> 404; never 403/5xx."""
    a, b = acc.user("adv-a@acc-m2.example.com"), acc.user("adv-b@acc-m2.example.com")
    a.need("POST /locations", "POST /inventory/postings", "GET /inventory/postings/{posting_id}",
           "POST /inventory/postings/{posting_id}/reverse")
    loc = a.post("/locations", {"code": "A-ST", "name": "A stores", "kind": "stores"})
    item = a.post("/items", {"part_number": "A-PART", "make_buy": "buy", "lead_time_days": 1})
    pst = a.post_stock(item["id"], loc["id"], 3)
    b_item = b.post("/items", {"part_number": "B-PART", "make_buy": "buy", "lead_time_days": 1})
    _err(b.raw("POST", "/inventory/postings", json={"type": "receipt_misc", "lines": [
        {"item_id": b_item["id"], "location_id": loc["id"], "qty": 1}]}), 422, "MFG_UNKNOWN_REFERENCE")
    for method, path in (("GET", f"/inventory/postings/{pst['id']}"),
                         ("POST", f"/inventory/postings/{pst['id']}/reverse"),
                         ("PUT", f"/locations/{loc['id']}"), ("DELETE", f"/locations/{loc['id']}")):
        body = {"code": "A-ST", "name": "x", "kind": "stores"} if method == "PUT" else ({"note": ""} if method ==
                                                                                       "POST" else None)
        r = b.raw(method, path, json=body, headers={"If-Match": '"1"'})
        _err(r, 404, "NOT_FOUND")
    assert b.get("/inventory/balances")["items"] == []
    assert a.balance(item["id"], loc["id"]) == 3


def test_workspace_header_abuse(w):
    api = w["api"]
    r = api.raw("GET", "/locations", headers={"X-SP-Workspace": "usr_local"})   # equal to the caller: own
    assert r.status_code == 200, r.text
    for value in ("usr_" + "0" * 32, "../../etc", "' OR 1=1 --"):
        _err(api.raw("GET", "/locations", headers={"X-SP-Workspace": value}), 404, "NOT_FOUND")
    r = api.raw("GET", "/locations", headers={"X-SP-Workspace": "x" * 5000})
    assert r.status_code in (400, 404, 431), r.status_code
