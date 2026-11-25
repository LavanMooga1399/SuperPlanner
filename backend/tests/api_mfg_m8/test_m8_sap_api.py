"""S5 API (M8-DESIGN 9, 11 X1-X2): SAP settings (secrets never returned), sync job against the fake OData server:
in (products with packaging, suppliers, info records, sales orders, purchase orders, billing history) -> MRP ->
planned orders out (CSRF) -> stock reconciliation clean."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sap"))

from apimfgm2_helpers import Api, make_app  # noqa: E402
from m8_helpers import owner_db, wait_for  # noqa: E402
from sap_fake import BASE, FakeS4  # noqa: E402


@pytest.fixture
def sap_api(db_url, monkeypatch):
    from superplanner.api.mfg.services import sap

    fake = FakeS4()
    monkeypatch.setattr(sap, "TRANSPORT", fake.transport)
    with TestClient(make_app(db_url, integration_allow_private_targets=True,
                             secrets_keys=[Fernet.generate_key().decode()])) as c:
        yield Api(c), c, fake


def _run(api, client, entities):
    from superplanner.api.db.ownership import system_scope
    from superplanner.api.mfg.db_models_m5 import MaintenanceRunRow

    out = api.post("/integration/sap/sync", {"entities": entities}, 202)

    def get():
        with system_scope(), owner_db(client).read() as s:
            r = s.get(MaintenanceRunRow, out["run_id"])
            return {"status": r.status, "results": r.results}
    r = wait_for(get, lambda x: x["status"] in ("completed", "failed"), timeout=60)
    assert r["status"] == "completed", r
    return r["results"]


@pytest.mark.req("M8-SAP-01", "M8-SAP-02")
def test_sap_round_trip(sap_api):
    api, client, fake = sap_api
    api.err("POST", "/integration/sap/sync", 409, "SAP_NOT_CONFIGURED", json={"entities": ["product"]})
    for code in ("FG", "STORES"):
        api.location(code)
    st = api.put("/integration/sap-settings", {"enabled": True, "base_url": BASE, "plant": "1000",
                                               "username": "SP_TECH", "password": "s3cret",
                                               "location_map": {"0001": "FG", "0002": "STORES"}}, 0)
    assert st["password"] is None and st["password_set"] is True and st["plant"] == "1000"
    res = _run(api, client, ["supplier", "product", "info_record", "billing", "purchase_order", "sales_order"])
    assert res["product"]["pages"] == 2 and res["product"]["results"].get("created") == 3, res
    assert res["product"]["results"]["packaging"] == 3 and res["billing"]["results"]["history"] == 3
    st = api.get("/integration/sap-settings")
    assert st["cursors"]["product"] == "2026-11-25T00:00:00Z" and st["last_sync"]["product"]["status"] == "completed"
    syr = api.by_pn("SYR-3ML-LL")
    assert syr["make_buy"] == "make"
    pk = api.get(f"/items/{syr['id']}/packaging")
    assert [lv["level"] for lv in pk["levels"]] == ["each", "inner", "case", "pallet"]
    assert api.get("/forecast/history", item_id=syr["id"])["items"][0]["source"] == "sap"
    so = [o for o in api.get("/demand-orders", limit=50)["items"] if o["number"] == "1000456"]
    assert so, "sales order imported"
    # a second sync sends the cursor in $filter
    n = len(fake.gets)
    _run(api, client, ["product"])
    assert "LastChangeDateTime" in fake.gets[n]
    # MRP -> planned orders out
    if so[0]["status"] == "draft":
        api.post(f"/demand-orders/{so[0]['id']}/open", {}, status=200, version=so[0]["row_version"])
    mrp = api.post("/mrp/runs", {"label": "sap", "horizon_days": 120})
    pos = api.get(f"/mrp/runs/{mrp['id']}/planned-orders", limit=200)["items"]
    assert pos
    out = _run(api, client, ["planned_order_out"])
    assert out["planned_order_out"]["posted"] == len(pos) == len(fake.posts)
    assert all(p[2]["x-csrf-token"] for p in fake.posts)
    again = _run(api, client, ["planned_order_out"])
    assert again["planned_order_out"]["posted"] == 0                  # once per run
    # stock reconciliation: SuperPlanner holds the same stock as SAP -> clean
    fg = api.by_code("/locations", "FG") if hasattr(api, "by_code") else None
    locs = {x["code"]: x["id"] for x in api.get("/locations")["items"]}
    tip = api.by_pn("100231")
    api.receive(syr["id"], locs["FG"], 48000, lot_code="L2611-01")
    api.receive(tip["id"], locs["STORES"], 25000)
    _run(api, client, ["stock"])
    rec = api.get("/integration/reconciliations")["items"][0]
    assert rec["summary"]["stock"]["different"] == 0 and rec["summary"]["stock"]["missing_in_sp"] == 0, rec
    _ = fg
