"""B5 (M2-DESIGN 11, 13, 9.4): sample load with transactions (+ reload unchanged), `scope=all` export -> import into
an empty account -> export byte-equal, stock import modes, per-sheet import permission, reset with M2 data."""

from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apimfgm2_helpers import Api, acc_app, sign_up
from superplanner.api.db.ownership import system_scope
from superplanner.api.mfg.db_models_m2 import ALL_MFG_MODELS, MfgPlantMemberRow
from superplanner.mfg import samples

OCTET = {"content-type": "application/octet-stream"}


def _import(api: Api, data: bytes, filename: str, options: dict | None = None, status: int = 200) -> dict:
    r = api.req("POST", "/imports", 201, params={"filename": filename}, content=data, headers=OCTET).json()
    mapping = {"sheets": {s["name"]: s["suggested"] for s in r["sheets"]}, "options": options or {}}
    m = api.put(f"/imports/{r['id']}/mapping", mapping, r["row_version"])
    assert m["preview"]["ok"], m["preview"]["row_errors"][:5]
    return api.req("POST", f"/imports/{r['id']}/commit", status, json={},
                   headers={"If-Match": f'"{m["row_version"]}"'}).json()


def test_kavach_load_reload_and_counts(api: Api):
    out = api.load("kavach")
    exp = samples.counts("kavach")
    c = out["result"]["counts"]
    assert c["stock"]["create"] == exp["stock"] and c["purchase_docs"]["create"] == 13
    assert c["work_orders"]["create"] == 3 and out["health"]["ok"]
    wo = api.doc("/work-orders", "WO-KV-0001")
    assert wo["status"] == "released" and any(x["reserved_qty"] > 0 for x in wo["components"])
    assert any(x["issued_qty"] > 0 for x in wo["components"])
    assert api.get("/inventory/balances", limit=1)["total"] == exp["stock"]
    again = api.load("kavach")
    assert all(v["create"] == v["update"] == v["delete"] == 0 for v in again["result"]["counts"].values())
    run = api.post("/mrp/runs", {"as_of": "2026-11-02"})
    assert run["kind"] == "what_if" and run["summary"]["demand_late"] == 5


def test_export_all_round_trip_byte_equal(db_url_factory):
    from apimfgm2_helpers import make_app

    with TestClient(make_app(db_url_factory("apimfgm2"))) as c1, TestClient(make_app(db_url_factory("apimfgm2"))) as c2:
        a, b = Api(c1), Api(c2)
        a.load("medium")
        data = a.req("GET", "/export", 200, params={"format": "zip", "scope": "all"}).content
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        assert "stock.csv" in names and "wo_components.csv" in names
        res = _import(b, data, "all.zip")
        assert res["status"] == "committed"
        data2 = b.req("GET", "/export", 200, params={"format": "zip", "scope": "all"}).content
        assert data2 == data
        master = a.req("GET", "/export", 200, params={"format": "zip"}).content
        assert "stock.csv" not in zipfile.ZipFile(io.BytesIO(master)).namelist()
        tx = a.req("GET", "/export", 200, params={"format": "zip", "scope": "transactions"}).content
        assert "items.csv" not in zipfile.ZipFile(io.BytesIO(tx)).namelist()
        tpl = a.req("GET", "/import-templates", 200, params={"format": "zip", "scope": "transactions"}).content
        assert "purchase_docs.csv" in zipfile.ZipFile(io.BytesIO(tpl)).namelist()


def test_stock_import_set_add_and_below_reserved(api: Api):
    api.load("small")
    csv = b"part_number,location_code,qty\nSM-MCU-01,STORES,40\n"
    _import(api, csv, "stock.csv")
    mcu = api.by_pn("SM-MCU-01")
    assert api.get("/inventory/balances", item_id=mcu["id"])["totals"]["qty_on_hand"] == 40
    _import(api, csv, "stock.csv", {"stock_mode": "add"})
    assert api.get("/inventory/balances", item_id=mcu["id"])["totals"]["qty_on_hand"] == 80
    assert api.get("/inventory/postings", type="count")["total"] >= 2


def test_import_needs_the_permission_of_every_sheet(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        oc = sign_up(app, "own@example.com")
        owner = Api(oc)
        oid = oc.get("/api/v1/auth/session").json()["user"]["id"]
        owner.load("small")
        sign_up_c = sign_up(app, "plan@example.com")
        owner.post("/members", {"email": "plan@example.com", "roles": ["planner"]})
        planner = Api(sign_up_c, oid)
        csv = b"part_number,location_code,qty\nSM-MCU-01,STORES,40\n"
        r = planner.req("POST", "/imports", 201, params={"filename": "stock.csv"}, content=csv, headers=OCTET).json()
        m = planner.put(f"/imports/{r['id']}/mapping", {"sheets": {s["name"]: s["suggested"] for s in r["sheets"]},
                                                        "options": {}}, r["row_version"])
        e = planner.err("POST", f"/imports/{r['id']}/commit", 403, "MFG_FORBIDDEN", json={},
                        headers={"If-Match": f'"{m["row_version"]}"'})
        assert e["details"]["permission"] == "inventory" and e["details"]["sheet"] == "stock"


def test_reset_deletes_all_m2_data_and_keeps_members(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        oc = sign_up(app, "own@example.com")
        owner = Api(oc)
        sign_up(app, "v@example.com")
        owner.load("small")
        owner.post("/members", {"email": "v@example.com", "roles": ["viewer"]})
        owner.post("/mrp/runs", {})
        owner.post("/reset", {"confirm": "DELETE ALL MANUFACTURING DATA"}, status=200)
        uid = oc.get("/api/v1/auth/session").json()["user"]["id"]
        with system_scope(), app.state.ctx.db.read() as s:
            for m in ALL_MFG_MODELS:
                n = s.execute(select(func.count()).select_from(m).where(m.owner_id == uid)).scalar()
                assert n == 0, m.__tablename__
            assert s.execute(select(func.count()).select_from(MfgPlantMemberRow)).scalar() == 1
