"""SAP S/4HANA adapter (M8-DESIGN 9; no SAP): recorded v2 / v4 payloads -> v1 batches equal the golden file,
paging, CSRF token fetch and retry, errors, outbound bodies."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sap_fake import BASE, FIX, FakeS4, load
from superplanner.integration.adapters.registry import get
from superplanner.integration.adapters.sap_s4 import SapS4
from superplanner.integration.contract import V1Event
from superplanner.integration.sap import mapping as M
from superplanner.integration.sap.odata import Client, ODataError
from superplanner.mfg.model_m8 import SapSettings

GOLDEN = FIX / "golden_v1.json"
PROFILE = SapSettings(plant="1000", location_map={"0001": "FG", "0002": "STORES"})


def _all() -> dict:
    out = {}
    for ent, files in (("product", ["product_v2_page1.json", "product_v2_page2.json"]),
                       ("supplier", ["supplier_v2.json"]), ("info_record", ["info_record_v2.json"]),
                       ("purchase_order", ["purchase_order_v2.json"]), ("sales_order", ["sales_order_v4.json"]),
                       ("billing", ["billing_v2.json"]), ("bom", ["bom_v2.json"])):
        ad = SapS4(PROFILE)
        batches = []
        for f in files:
            batches += ad.inbound({"entity": ent, **load(f)}, None)
        out[ent] = {"batches": [b.model_dump(mode="json", by_alias=True) for b in batches], "extras": ad.extras}
    return out


@pytest.mark.req("M8-SAP-01")
def test_recorded_payloads_map_to_golden_v1_batches():
    got = json.loads(json.dumps(_all(), sort_keys=True))
    if os.environ.get("SAP_WRITE_GOLDEN"):
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
    assert got == json.loads(GOLDEN.read_text())
    items = {r["ref"]: r for r in got["product"]["batches"][0]["records"] + got["product"]["batches"][1]["records"]}
    assert set(items) == {"SYR-3ML-LL", "100231", "NDL-21G-1"}                 # zero-strip, plant filter
    assert items["SYR-3ML-LL"]["make_buy"] == "make" and items["100231"]["uom"] == "EA"
    assert items["SYR-3ML-LL"]["standard_cost"] == pytest.approx(0.085)
    packs = {p["item_ref"]: p for p in got["product"]["extras"]["packaging"]}
    assert [lv["level"] for lv in packs["SYR-3ML-LL"]["levels"]] == ["each", "inner", "case", "pallet"]
    so = got["sales_order"]["batches"][0]["records"][0]                       # v4 shape
    assert [(ln["item_ref"], ln["qty"], ln["due_date"]) for ln in so["lines"]] == [
        ("SYR-3ML-LL", 60000.0, "2026-12-10"), ("SYR-3ML-LL", 60000.0, "2026-12-17"),
        ("NDL-21G-1", 50000.0, "2026-12-12")]
    po = got["purchase_order"]["batches"][0]["records"][0]
    assert [s["requested_date"] for s in po["lines"][0]["schedules"]] == ["2026-12-09", "2026-12-23"]
    hist = got["billing"]["extras"]["history"]
    assert {(h["item_ref"], h["period_start"]): h["qty"] for h in hist} == {
        ("SYR-3ML-LL", "2025-10-01"): 400000.0, ("SYR-3ML-LL", "2025-11-01"): 380000.0,
        ("NDL-21G-1", "2025-11-01"): 150000.0}
    assert get("sap_s4").name == "sap_s4"


def test_stock_mapping_unrestricted_and_location_map():
    out = M.stock(load("stock_v2.json")["d"]["results"], PROFILE)["stock_snapshot"]
    assert [(r["item_ref"], r["location_code"], r["lot_code"], r["qty"]) for r in out] == [
        ("100231", "STORES", None, 25000.0), ("SYR-3ML-LL", "FG", "L2611-01", 48000.0)]


@pytest.mark.req("M8-SAP-01")
def test_fake_server_paging_csrf_and_errors():
    fake = FakeS4()
    c = Client(BASE, transport=fake.transport(), username="u", password="p")
    pages = list(c.get_all(M.ENTITIES["product"][0], M.delta_filter("product", "2026-11-20T00:00:00Z", "v2")))
    assert [len(p) for p in pages] == [2, 2]
    assert "LastChangeDateTime+gt+datetimeoffset" in fake.gets[0] or "LastChangeDateTime%20gt" in fake.gets[0]
    assert M.max_cursor(pages[0] + pages[1], "product", None) == "2026-11-25T00:00:00Z"
    path, body = M.planned_order_out({"kind": "make", "part_number": "SYR-3ML-LL", "qty": 3000.0,
                                      "need_date": "2026-12-10", "start_date": "2026-12-08", "ref": "P-1"}, PROFILE)
    r = c.post(path, body)
    assert r["d"]["PlannedOrder"] and fake.posts[0][2]["x-csrf-token"] == "tok-1"
    assert fake.posts[0][2].get("cookie", "").startswith("SAP_SESSIONID")
    fake.expire_next_post = True                                   # token expired: fetch a new one, retry once
    c.post(*M.planned_order_out({"kind": "buy", "part_number": "100231", "qty": 5000.0, "need_date": "2026-12-10",
                                 "start_date": "2026-12-01", "ref": "P-2"}, PROFILE))
    assert len(fake.posts) == 2 and fake.posts[1][0].endswith("A_PurchaseRequisitionHeader")
    assert fake.posts[1][1]["to_PurchaseReqnItem"]["results"][0]["Plant"] == "1000"
    fake.fail["A_Supplier"] = 500
    with pytest.raises(ODataError) as e:
        list(c.get_all(M.ENTITIES["supplier"][0]))
    assert e.value.status == 500 and "Boom" in e.value.message


def test_outbound_events_and_v4_paging():
    ad = SapS4(PROFILE)
    ev = V1Event(id=1, type="work_order.created", occurred_at="2026-11-25T00:00:00Z", plant={"code": "P"},
                 data={"number": "WO-000001", "item": {"part_number": "SYR-3ML-LL"}, "qty": 1000,
                       "due_date": "2026-12-01", "start_date": "2026-11-28"})
    d = ad.outbound(ev)
    assert d[0].headers["X-SAP-Path"].startswith("API_PLANNED_ORDERS") and json.loads(d[0].body)["MRPPlant"] == "1000"
    assert ad.outbound(V1Event(id=2, type="inventory.posting", occurred_at="2026-11-25T00:00:00Z", plant={})) == []
    from superplanner.integration.sap.odata import page_of
    assert page_of({"value": [{"a": 1}], "@odata.nextLink": "x"}) == ([{"a": 1}], "x")
    assert M.to_date("/Date(1796774400000)/").isoformat() == "2026-12-09"
