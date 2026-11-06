"""Inbound mappers for every v1 entity, field-level SoR on both sides (M5-DESIGN 4.3, 4.4, 4.8, 5)."""

from __future__ import annotations

from test_integration import ITEMS, _enable, env  # noqa: F401


def test_master_documents_and_eco_from_erp(env):  # noqa: F811
    it, api, _app, _r = env
    _enable(it)
    api.post("/groups", {"code": "SMT", "name": "SMT"})
    items = ITEMS[:1] + [{"ref": "ERP-PCB", "part_number": "PCB-1", "uom": "EA", "make_buy": "make"},
                         {"ref": "ERP-C2", "part_number": "C-2", "uom": "EA"}]
    assert {r["status"] for r in it.batch("item", items, "i1")["results"]} == {"created"}
    sup = it.batch("supplier", [{"ref": "S-1", "code": "SUP1", "name": "Supplier one", "lead_time_days": 7}], "s1")
    assert sup["results"][0]["status"] == "created"
    assert it.batch("supplier", [{"ref": "S-1", "code": "SUP1", "name": "Supplier one", "lead_time_days": 7}],
                    "s2")["results"][0]["status"] == "unchanged"
    isu = it.batch("item_supplier", [{"ref": "IS-1", "item_ref": "ERP-1", "supplier_ref": "S-1", "price": 1.5,
                                      "preferred": True}], "is1")["results"][0]
    assert isu["status"] == "created", isu
    bad = it.batch("item_supplier", [{"ref": "IS-2", "item_ref": "NOPE", "supplier_ref": "S-1"}], "is2")
    assert bad["results"][0]["errors"][0]["code"] == "INT_UNMAPPED_VALUE"
    # local writes of ERP-owned suppliers -> 409; `preferred` stays local
    s = api.get("/suppliers")["items"][0]
    api.err("PUT", f"/suppliers/{s['id']}", 409, "INT_ERP_OWNED", json={"code": "SUP1", "name": "Renamed"},
            headers={"If-Match": f'"{s["row_version"]}"'})
    link = api.get("/item-suppliers", supplier_id=s["id"])["items"][0]
    body = {k: link[k] for k in ("item_id", "supplier_id", "supplier_part_number", "lead_time_days",
                                 "min_order_qty", "order_multiple", "unit_price", "currency", "active", "note")}
    assert api.put(f"/item-suppliers/{link['id']}", {**body, "preferred": False},
                   link["row_version"])["preferred"] is False
    api.err("PUT", f"/item-suppliers/{link['id']}", 409, "INT_ERP_OWNED", json={**body, "unit_price": 9.0},
            headers={"If-Match": f'"{link["row_version"] + 1}"'})
    # BOM from the ERP: released through an auto-approved ECO; the same structure again is unchanged
    bom = {"ref": "B-1", "parent_ref": "ERP-PCB", "lines": [{"child_ref": "ERP-1", "find_number": "1", "qty_per": 2}]}
    r1 = it.batch("bom", [bom], "b1")["results"][0]
    assert r1["status"] == "created" and r1["eco"]["number"] == "ECO-000001", r1
    assert it.batch("bom", [bom], "b2")["results"][0]["status"] == "unchanged"
    bom2 = {**bom, "effective_from": "2027-01-01",
            "lines": [{"child_ref": "ERP-C2", "find_number": "1", "qty_per": 2}]}
    r2 = it.batch("bom", [bom2], "b3")["results"][0]
    assert r2["status"] == "created" and r2["eco"]["number"] == "ECO-000002"
    eco = api.get("/eco", status="implemented")["items"]
    assert {e["source"] for e in eco} == {"erp"} and len(eco) == 2
    boms = api.get(f"/items/{api.by_pn('PCB-1')['id']}/boms")["items"]
    assert sorted((b["version"], b["status"]) for b in boms) == [(1, "released"), (2, "released")]
    b1 = next(b for b in boms if b["version"] == 1)
    api.err("POST", f"/boms/{b1['id']}/copy", 409, "INT_ERP_OWNED", json={},
            headers={"If-Match": f'"{b1["row_version"]}"'})
    rt = it.batch("routing", [{"ref": "R-1", "item_ref": "ERP-PCB", "operations": [
        {"seq": 10, "name": "Place", "group_code": "SMT", "run_minutes": 1}]}], "r1")["results"][0]
    assert rt["status"] == "created" and rt["eco"]
    bad = it.batch("routing", [{"ref": "R-2", "item_ref": "ERP-PCB", "code": "ALT", "operations": [
        {"seq": 10, "name": "X", "group_code": "NOPE"}]}], "r2")["results"][0]
    assert bad["errors"][0]["code"] == "INT_UNMAPPED_VALUE"


def test_orders_stock_and_local_guards(env):  # noqa: F811
    it, api, _app, _r = env
    _enable(it)
    it.batch("item", ITEMS[:1] + [ITEMS[2]], "i1")
    it.batch("supplier", [{"ref": "S-1", "code": "SUP1", "name": "Supplier one"}], "s1")
    st = api.location("ST")
    po = {"ref": "PO-ERP-1", "number": "4500001", "supplier_ref": "S-1", "lines": [
        {"line_no": 1, "item_ref": "ERP-1", "unit_price": 2,
         "schedules": [{"seq": 1, "requested_date": "2026-12-01", "qty": 100}]}]}
    r = it.batch("purchase_order", [po], "p1")["results"][0]
    assert r["status"] == "created", r
    assert it.batch("purchase_order", [po], "p2")["results"][0]["status"] == "unchanged"
    po2 = {**po, "lines": [{**po["lines"][0], "schedules": [{"seq": 1, "requested_date": "2026-12-05", "qty": 120}]}]}
    assert it.batch("purchase_order", [po2], "p3")["results"][0]["status"] == "updated"
    doc = api.doc("/purchase-orders", "4500001")
    assert doc["lines"][0]["schedules"][0]["qty"] == 120
    api.err("DELETE", f"/purchase-orders/{doc['id']}", 409, "INT_ERP_OWNED",
            headers={"If-Match": f'"{doc["row_version"]}"'})
    dem = {"ref": "SO-1", "number": "SO-1", "customer": "Rail", "lines": [
        {"line_no": 1, "item_ref": "ERP-1", "qty": 5, "due_date": "2026-12-10", "priority": 3}]}
    assert it.batch("demand_order", [dem], "d1")["results"][0]["status"] == "created"
    o = api.doc("/demand-orders", "SO-1")
    assert o["status"] == "open" and o["lines"][0]["priority"] == 3
    body = {"number": "SO-1", "demand_type": o["demand_type"], "customer": "Rail", "program": None,
            "priority": 2, "note": "", "external_ref": "SO-1",
            "lines": [{"id": o["lines"][0]["id"], "line_no": 1, "item_id": o["lines"][0]["item"]["id"], "qty": 5,
                       "due_date": "2026-12-10", "priority": 1}]}
    assert api.put(f"/demand-orders/{o['id']}", body, o["row_version"])["priority"] == 2     # priority: local
    o = api.doc("/demand-orders", "SO-1")
    api.err("PUT", f"/demand-orders/{o['id']}", 409, "INT_ERP_OWNED", json={**body, "customer": "Other"},
            headers={"If-Match": f'"{o["row_version"]}"'})
    again = it.batch("demand_order", [dem], "d2")["results"][0]
    assert again["status"] == "unchanged" and api.doc("/demand-orders", "SO-1")["lines"][0]["priority"] == 1
    wo = it.batch("work_order", [{"ref": "W1", "number": "W1", "item_ref": "ERP-1", "qty": 1,
                                  "due_date": "2026-12-01"}], "w1")["results"][0]
    assert wo["errors"][0]["code"] == "INT_SOR_CONFLICT"
    # stock snapshots: reconciliation (SP-owned stock), then count postings when stock SoR is erp
    api.receive(api.by_pn("R-10K")["id"], st["id"], 98)
    snap = [{"ref": "x1", "item_ref": "ERP-1", "location_code": "ST", "qty": 100, "as_at": "2026-11-05T00:00:00Z"}]
    r = it.batch("stock_snapshot", snap, "st1")["results"][0]
    rec = it.req("GET", f"/reconciliations/{r['id']}", 200).json()
    assert rec["results"]["stock"]["different"][0]["delta"] == 2
    assert api.get("/inventory/balances", item_id=api.by_pn("R-10K")["id"])["items"][0]["qty_on_hand"] == 98
    x = it.req("GET", f"/reconciliations/{r['id']}/export", 200)
    assert x.content[:2] == b"PK"
    csv = it.req("GET", f"/reconciliations/{r['id']}/export", 200, params={"format": "csv"}).text
    assert csv.startswith("entity,kind") and "different" in csv
    _enable(it, sor={"stock": "erp"})
    r = it.batch("stock_snapshot", snap, "st2")["results"][0]
    assert r["status"] == "updated"
    assert api.get("/inventory/balances", item_id=api.by_pn("R-10K")["id"])["items"][0]["qty_on_hand"] == 100
    post = api.get("/inventory/postings", type="count")["items"][0]
    assert post["reason_code"] == "ERP_SYNC"
    # items and purchase orders reconciliation
    rec = it.req("POST", "/reconciliations", 201, json={"entities": ["items", "purchase_orders"], "records": {
        "items": [{**ITEMS[0], "description": "Changed in ERP"}],
        "purchase_orders": [{**po2, "lines": [{**po2["lines"][0], "schedules": [
            {"seq": 1, "requested_date": "2026-12-05", "qty": 120, "received_qty": 10}]}]}]}}).json()
    assert rec["summary"]["items"]["different"] == 1 and rec["results"]["items"]["different"][0]["fields"][
        "description"]["erp"] == "Changed in ERP"
    assert rec["results"]["purchase_orders"]["different"][0]["schedules"][0]["fields"]["received_qty"]["erp"] == 10


def test_large_batch_is_queued(env):  # noqa: F811
    it, api, _app, _r = env
    _enable(it)
    recs = [{"ref": f"E-{i}", "part_number": f"P-{i:04d}"} for i in range(501)]
    out = it.req("POST", "/batches", 202, json={"schema": "superplanner.v1", "entity": "item", "records": recs},
                 headers={"Idempotency-Key": "big"}).json()
    import time

    for _ in range(100):
        b = it.req("GET", f"/batches/{out['id']}", 200).json()
        if b["status"] in ("completed", "failed"):
            break
        time.sleep(0.2)
    assert b["status"] == "completed" and b["counts"] == {"created": 501}, b["counts"]


def test_shared_sor_logs_conflicts(env):  # noqa: F811
    it, api, _app, _r = env
    _enable(it, sor={"items": "shared"})
    it.batch("item", ITEMS[:1], "c1")
    item = api.by_pn("R-10K")
    body = {k: item[k] for k in ("part_number", "revision", "description", "uom", "make_buy", "active",
                                 "external_ref")}
    api.put(f"/items/{item['id']}", {**body, "description": "Local"}, item["row_version"])   # shared: allowed
    it.batch("item", [{**ITEMS[0], "description": "From ERP"}], "c2")                      # both changed
    assert api.by_pn("R-10K")["description"] == "From ERP"                                   # last writer wins
    it.batch("item", [{**ITEMS[0], "description": "ERP again"}], "c3")                     # no local change
    rec = it.req("POST", "/reconciliations", 201, json={"entities": ["items"], "records": {"items": []}}).json()
    conf = rec["results"]["items"]["sor_conflicts"]
    assert len(conf) == 1 and conf[0]["ref"] == "ERP-1" and conf[0]["entity"] == "items"


def test_m1_import_obeys_sor_and_eco_locks(env):  # noqa: F811
    it, api, _app, _r = env
    _enable(it)

    def imp(data: bytes, name: str):
        r = api.req("POST", "/imports", 201, params={"filename": name}, content=data,
                    headers={"content-type": "application/octet-stream"}).json()
        m = {"sheets": {s["name"]: s["suggested"] for s in r["sheets"]}, "options": {}}
        p = api.put(f"/imports/{r['id']}/mapping", m, r["row_version"])
        return api.req("POST", f"/imports/{r['id']}/commit", None, json={},
                       headers={"If-Match": f'"{p["row_version"]}"'})

    r = imp(b"part_number,make_buy\nNEW-1,buy\n", "items.csv")
    assert r.status_code == 409 and r.json()["error"]["details"]["fields"] == ["part_number"]
    r = imp(b"code,name\nS1,Sup\n", "suppliers.csv")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INT_ERP_OWNED"
    it.batch("item", ITEMS[:1], "lk")
    item = api.by_pn("R-10K")
    r = imp(b"part_number,safety_stock\nR-10K,5\n", "items.csv")          # planning fields import fine
    assert r.status_code == 200, r.text
    api.err("DELETE", f"/items/{item['id']}", 409, "INT_ERP_OWNED",
            headers={"If-Match": f'"{api.by_pn("R-10K")["row_version"]}"'})


def test_failed_batch_is_recorded_and_retryable(env, monkeypatch):  # noqa: F811
    from superplanner.api.mfg.services import integration as svc

    it, _api, _app, _r = env
    _enable(it)
    real = svc.process
    monkeypatch.setattr(svc, "process", lambda ctx, b: (_ for _ in ()).throw(RuntimeError("boom")))
    import pytest

    with pytest.raises(RuntimeError):                                       # TestClient re-raises the 500
        it.c.post("/api/v1/integration/batches", json={"schema": "superplanner.v1", "entity": "item",
                                                       "records": ITEMS[:1]}, headers={"Idempotency-Key": "f1"})
    b = it.req("GET", "/batches", 200).json()["items"][0]
    assert b["status"] == "failed"
    monkeypatch.setattr(svc, "process", real)
    out = it.batch("item", ITEMS[:1], "f1")                                  # same key, same body: runs again
    assert out["status"] == "completed" and out["results"][0]["status"] == "created"
