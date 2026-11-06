"""Inter-plant transfer orders (M5-DESIGN 3.5; T-O3)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, acc_app, sign_up


def _two_plants(app):
    admin = sign_up(app, "admin@hbl.example")
    org = admin.post(f"{V1}/orgs", json={"name": "HBL", "slug": "hbl"}).json()
    a = admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "HYD", "name": "Hyderabad"}).json()
    b = admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "BLR", "name": "Bengaluru"}).json()
    return admin, org, Api(admin, a["plant_owner_id"]), Api(admin, b["plant_owner_id"]), a, b


def test_t_o3_transfer_end_to_end(db_url):
    app = acc_app(db_url, org_self_service=True)
    with TestClient(app):
        admin, _org, pa, pb, a, b = _two_plants(app)
        sa, sb = pa.location("ST"), pb.location("ST", receipt_default=True)
        ia = pa.item("CAP", lot_controlled=True, external_ref="ERP-CAP", lead_time_days=10)
        ib = pb.item("CAP", lot_controlled=True, external_ref="ERP-CAP", lead_time_days=10)
        pb.item("ONLY-B")
        pa.receive(ia["id"], sa["id"], 150, lot_code="L1", supplier_lot="SUP-77")
        pa.item("ONLY-A")
        bad = pa.err("POST", "/transfer-orders", 422, "TRF_ITEM_UNMATCHED", json={
            "dest_plant_owner_id": b["plant_owner_id"], "lines": [
                {"item_id": pa.by_pn("ONLY-A")["id"], "qty": 1, "ship_date": "2026-11-10",
                 "receive_date": "2026-11-12"}]})
        assert bad["details"]["lines"][0]["part_number"] == "ONLY-A"
        to = pa.post("/transfer-orders", {"dest_plant_owner_id": b["plant_owner_id"], "lines": [
            {"item_id": ia["id"], "qty": 100, "ship_date": "2026-11-10", "receive_date": "2026-11-12"}]})
        assert to["number"] == "TO-000001" and to["direction"] == "out" and to["dest_plant"]["code"] == "BLR"
        to = pa.post(f"/transfer-orders/{to['id']}/open", {}, status=200, version=to["row_version"])
        mirror = pb.get("/transfer-orders")["items"][0]
        assert mirror["direction"] == "in" and mirror["status"] == "open" and mirror["mirror_of"] == to["id"]
        assert mirror["lines"][0]["item_id"] == ib["id"]
        # MRP: demand in A, supply in B (before shipping)
        pa.post("/mrp/runs", {})
        pb.post("/mrp/runs", {})
        da = pa.get(f"/mrp/runs/{pa.get('/mrp/runs')['items'][0]['id']}/demand")["items"]
        assert "TO-000001" in str(da), da
        db_ = pb.get(f"/mrp/runs/{pb.get('/mrp/runs')['items'][0]['id']}/items/{ib['id']}")
        assert "TO-000001" in str(db_)
        # ship in A, receive in B
        ln = to["lines"][0]
        pa.post("/inventory/postings", {"type": "transfer_ship", "lines": [
            {"transfer_line_id": ln["id"], "item_id": ia["id"], "location_id": sa["id"], "qty": 100,
             "lot_code": "L1"}]})
        pa.err("POST", "/inventory/postings", 409, "TRF_OVER_QUANTITY", json={"type": "transfer_ship", "lines": [
            {"transfer_line_id": ln["id"], "item_id": ia["id"], "location_id": sa["id"], "qty": 1, "lot_code": "L1"}]})
        assert pa.get(f"/transfer-orders/{to['id']}")["status"] == "shipped"
        mirror = pb.get(f"/transfer-orders/{mirror['id']}")
        assert mirror["lines"][0]["in_transit"][0]["lot_code"] == "L1"
        mln = mirror["lines"][0]
        pb.err("POST", "/inventory/postings", 409, "TRF_OVER_QUANTITY", json={"type": "transfer_receipt", "lines": [
            {"transfer_line_id": mln["id"], "item_id": ib["id"], "location_id": sb["id"], "qty": 101,
             "lot_code": "L1"}]})
        pb.post("/inventory/postings", {"type": "transfer_receipt", "lines": [
            {"transfer_line_id": mln["id"], "item_id": ib["id"], "location_id": sb["id"], "qty": 100,
             "lot_code": "L1"}]})
        bal_a = pa.get("/inventory/balances", item_id=ia["id"])["items"]
        bal_b = pb.get("/inventory/balances", item_id=ib["id"])["items"]
        assert sum(x["qty_on_hand"] for x in bal_a) == 50 and sum(x["qty_on_hand"] for x in bal_b) == 100
        lot_b = pb.get("/lots", item_id=ib["id"])["items"][0]
        assert lot_b["lot_code"] == "L1" and lot_b["supplier_lot"] == "SUP-77"
        assert pb.get(f"/transfer-orders/{mirror['id']}")["status"] == "received"
        # genealogy across plants: A.L1 -> transfer -> B.L1 (the admin sees both plants)
        lot_a = pa.get("/lots", item_id=ia["id"])["items"][0]
        tr = pa.get("/trace", kind="lot", id=lot_a["id"], direction="forward")
        kids = tr["root"]["children"]
        assert kids[0]["kind"] == "transfer"
        far = kids[0]["children"][0]
        assert far["plant"]["code"] == "BLR" and far["children"][0]["id"] == lot_b["id"]
        back = pb.get("/trace", kind="lot", id=lot_b["id"], direction="backward")
        assert back["root"]["children"][0]["kind"] == "transfer"
        pa.post(f"/transfer-orders/{to['id']}/close", {}, status=200,
                version=pa.get(f"/transfer-orders/{to['id']}")["row_version"])
        # a user without access to B cannot create transfers into it
        u = sign_up(app, "solo@x.example")
        Api(u).err("POST", "/transfer-orders", 403, "TRF_PLANT_ACCESS", json={
            "dest_plant_owner_id": b["plant_owner_id"], "lines": [
                {"item_id": ia["id"], "qty": 1, "ship_date": "2026-11-10", "receive_date": "2026-11-12"}]})
