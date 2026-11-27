"""Trade tables, item trade data, landed cost, receipt COO capture, lot content, risk, milestone report
(M9-DESIGN 8; M9-TRD-01, M9-TRD-04, M9-TRD-06 through the API)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from m8_helpers import wait_for
from m9_helpers import app_for, make_world

MONTH = date.today().replace(day=1)


def _tables(net) -> None:
    net.req("PUT", "/trade/tariffs", 200, json={"rows": [
        {"dest_country": "CA", "hts_prefix": "9018", "coo": "*", "layer": "mfn", "rate_pct": 0,
         "valid_from": "2020-01-01"},
        {"dest_country": "CA", "hts_prefix": "9018", "coo": "CN", "layer": "surtax", "rate_pct": 25,
         "valid_from": "2020-01-01"}]})
    net.req("PUT", "/trade/fx", 200, json={"rows": [{"from_ccy": "USD", "to_ccy": "CAD", "month": MONTH.isoformat(),
                                                     "rate": 1.40}]})
    net.req("PUT", "/trade/country-risk", 200, json={"rows": [{"country": "CN", "score": 20}]})
    net.req("PUT", "/trade/milestones", 200, json={"rows": [{
        "code": "NDL-US-STEEL", "name": "Needles: US steel", "dest_country": "US", "family": "NDL",
        "rule": {"domestic_country": "US", "basis": "value", "material_classes": ["steel"], "min_pct": 100},
        "effective": "2027-07-01"}]})


@pytest.mark.req("M9-TRD-01")
@pytest.mark.req("M9-TRD-06")
def test_tables_landed_cost_and_receipt_coo(db_url):
    app = app_for(db_url)
    with TestClient(app):
        w = make_world(app)
        net, qc = w.net, w.api("QC")
        _tables(net)
        again = net.req("PUT", "/trade/tariffs", 200, json={"rows": [
            {"dest_country": "CA", "hts_prefix": "9018", "coo": "CN", "layer": "surtax", "rate_pct": 25,
             "valid_from": "2020-01-01"}], "replace": True}).json()
        assert again == {"inserted": 0, "updated": 0, "deleted": 1}
        net.req("PUT", "/trade/tariffs", 200, json={"rows": [
            {"dest_country": "CA", "hts_prefix": "9018", "coo": "*", "layer": "mfn", "rate_pct": 0,
             "valid_from": "2020-01-01"}]})
        assert len(net.get("/trade/tariffs")["items"]) == 2 and net.get("/trade/milestones")["items"][0]["code"]
        qc.err("PUT", "/trade/fx", 409, "NET_WORKSPACE_REQUIRED", json={"rows": []})
        # plant: item trade + item-supplier trade fields -> landed cost (hand example 8.4)
        loc = qc.location("RCV", receipt_default=True)
        it = qc.item("CAN-STEEL", family="CAN", lead_time_days=75, lot_controlled=True)
        tr = qc.req("PUT", f"/items/{it['id']}/trade", 200, json={"hts_code": "901832", "coo": "JP",
                                                                   "material_class": "steel"}).json()
        assert tr["row_version"] == 1 and qc.get(f"/items/{it['id']}/trade")["coo"] == "JP"
        cn = qc.supplier("ATUBE", currency="USD")
        us = qc.supplier("KTUBE", currency="USD")
        isu = qc.post("/item-suppliers", {"item_id": it["id"], "supplier_id": cn["id"], "unit_price": 100,
                                          "currency": "USD", "units_per_purchase_unit": 1000, "coo": "CN",
                                          "hts_code": "901832", "freight_per_unit": 0.005, "preferred": True})
        assert isu["coo"] == "CN" and isu["hts_code"] == "901832"
        qc.post("/item-suppliers", {"item_id": it["id"], "supplier_id": us["id"], "unit_price": 1, "currency": "JPY"})
        rows = {r["supplier_code"]: r for r in qc.get("/trade/landed", item_id=it["id"])["items"]}
        lc = rows["ATUBE"]["landed"]
        assert lc["total"] == pytest.approx(0.1807) and lc["currency"] == "CAD" and lc["fx_rate"] == 1.4
        assert {d["layer"]: d["amount"] for d in lc["duty"]} == {"mfn": 0, "surtax": pytest.approx(0.035)}
        assert rows["KTUBE"]["landed"]["total"] is None and "FX_MISSING" in rows["KTUBE"]["landed"]["flags"]
        listed = qc.get("/item-suppliers", item_id=it["id"])["items"]
        assert any(x.get("landed", {}).get("total") == pytest.approx(0.1807) for x in listed)
        # receipt COO precedence (8.1): request > item-supplier > item; FX to plant currency for unit value
        po = qc.post("/purchase-orders", {"supplier_id": cn["id"], "lines": [{"item_id": it["id"], "unit_price": 0.1,
                                                                            "schedules": [
            {"requested_date": (date.today() + timedelta(days=5)).isoformat(), "qty": 30}]}]})
        po = qc.post(f"/purchase-orders/{po['id']}/issue", version=po["row_version"], status=200)
        sid = po["lines"][0]["schedules"][0]["id"]
        sources = []
        for code, coo in (("R1", "MX"), ("R2", None)):
            ln = {"schedule_id": sid, "qty": 10, "lot_code": code, "location_id": loc["id"]}
            if coo:
                ln["coo"] = coo
            qc.post("/inventory/postings", {"type": "po_receipt", "lines": [ln]})
            lot = [x for x in qc.get("/lots", item_id=it["id"])["items"] if x["lot_code"] == code][0]
            sources.append((lot["coo"], lot["coo_source"], lot["unit_value"]))
        assert sources[0][:2] == ("MX", "receipt") and sources[1][:2] == ("CN", "supplier")
        assert sources[0][2] == pytest.approx(0.14)
        # review m10: two lines of one schedule keep their own COO; a later receipt with another COO only warns
        rec = qc.post("/inventory/postings", {"type": "po_receipt", "lines": [
            {"schedule_id": sid, "qty": 2, "lot_code": "R3", "location_id": loc["id"], "coo": "DE"},
            {"schedule_id": sid, "qty": 2, "lot_code": "R4", "location_id": loc["id"], "coo": "FR"}]})
        lots = {x["lot_code"]: x["coo"] for x in qc.get("/lots", item_id=it["id"])["items"]}
        assert (lots["R3"], lots["R4"]) == ("DE", "FR") and "trade_warnings" not in rec
        rec = qc.post("/inventory/postings", {"type": "po_receipt", "lines": [
            {"schedule_id": sid, "qty": 1, "lot_code": "R3", "location_id": loc["id"], "coo": "IT"}]})
        assert rec["trade_warnings"][0]["code"] == "TRADE_COO_CONFLICT"
        assert {x["lot_code"]: x["coo"] for x in qc.get("/lots", item_id=it["id"])["items"]}["R3"] == "DE"
        # regulated COO correction after receipt: reason required, audited with it
        r1 = [x for x in qc.get("/lots", item_id=it["id"])["items"] if x["lot_code"] == "R1"][0]
        qc.err("PUT", f"/lots/{r1['id']}/coo", 422, "VALIDATION_ERROR", json={"coo": "US"})
        fixed = qc.put(f"/lots/{r1['id']}/coo", {"coo": "US", "reason": "Mill certificate says US"},
                       r1["row_version"])
        assert fixed["coo"] == "US" and fixed["coo_source"] == "receipt"
        from m8_helpers import audit_rows
        rows = audit_rows(w.admin, "lot", r1["id"], owner=w.owner("QC"))
        assert rows[-1]["action"] == "coo_change" and rows[-1]["reason"] == "Mill certificate says US"
        # supplier risk: CN single-source-like row scores country 20 + tariff
        risk = {(r["supplier_code"]): r for r in qc.get("/trade/risk")["items"]}
        assert risk["ATUBE"]["parts"]["country"] == 20 and risk["ATUBE"]["parts"]["tariff"] == 10
        assert risk["ATUBE"]["parts"]["lead_time"] == 15


@pytest.mark.req("M9-TRD-04")
def test_made_lot_content_transfer_carries_coo_and_shares_and_report(db_url, monkeypatch):
    from superplanner.api.mfg.services import trade as TRADE

    monkeypatch.setattr(TRADE, "ROLLUP_DEBOUNCE_S", 0)           # the queue claims the debounced run at once
    app = app_for(db_url)
    with TestClient(app):
        w = make_world(app)
        net, us, qc = w.net, w.api("US1"), w.api("QC")
        _tables(net)
        loc = us.location("ST", receipt_default=True)
        steel = us.item("STEEL", lead_time_days=10, external_ref="STEEL", standard_cost=10, lot_controlled=True,
                        family="STL")
        for code, coo in (("KT", "US"), ("AT", "CN")):
            sup = us.supplier(code, currency="USD")
            us.post("/item-suppliers", {"item_id": steel["id"], "supplier_id": sup["id"], "unit_price": 10,
                                        "currency": "USD", "coo": coo})
        us.req("PUT", f"/items/{steel['id']}/trade", 200, json={"coo": "US", "material_class": "steel",
                                                                 "unit_weight_kg": 1.0})
        ndl = us.item("NDL", "make", external_ref="NDL", family="NDL", standard_cost=30, lot_controlled=True)
        bom = us.post("/boms", {"item_id": ndl["id"], "lines": [{"find_number": "10", "child_item_id": steel["id"],
                                                                 "qty_per": 1}]})
        us.post(f"/boms/{bom['id']}/release", {"effective_from": "2026-01-01"}, version=bom["row_version"],
                status=200)
        us.receive(steel["id"], loc["id"], 100, lot_code="S1")
        wo = us.post("/work-orders", {"item_id": ndl["id"], "qty": 10,
                                      "due_date": (date.today() + timedelta(days=3)).isoformat()})
        wo = us.post(f"/work-orders/{wo['id']}/release", version=wo["row_version"], status=200)
        comp = wo["components"][0]
        us.post("/inventory/postings", {"type": "wo_issue", "lines": [
            {"wo_component_id": comp["id"], "location_id": loc["id"], "qty": 10, "lot_code": "S1"}]})
        us.post("/inventory/postings", {"type": "wo_receipt", "lines": [
            {"wo_id": wo["id"], "location_id": loc["id"], "qty": 10, "lot_code": "N1"}]})
        lot = [x for x in us.get("/lots", item_id=ndl["id"])["items"] if x["lot_code"] == "N1"][0]
        assert lot["coo"] == "US" and lot["coo_source"] == "plant"
        # the receipt queued the (debounced) roll-up; the inline executor runs it at once
        done = wait_for(lambda: [x for x in us.get("/lots", item_id=ndl["id"])["items"] if x["lot_code"] == "N1"][0],
                        lambda x: x["dom_share_value"] is not None, timeout=30)
        assert done["dom_share_value"] == 1.0
        from sqlalchemy import event
        seen: list[str] = []
        eng = app.state.ctx.db.engine
        grab = lambda conn, cur, stmt, *a: seen.append(stmt)   # noqa: E731
        event.listen(eng, "before_cursor_execute", grab)
        try:
            c = us.get(f"/lots/{lot['id']}/content")
        finally:
            event.remove(eng, "before_cursor_execute", grab)
        assert not [x for x in seen if x.lstrip().upper().startswith("UPDATE MFG_LOTS")]   # review m9: no write
        assert c["share_value"] == 1.0 and c["tree"]["children"][0]["lot_code"] == "S1"
        ms = net.get("/trade/milestones")["items"][0]
        c2 = net.get(f"/trade/lots/{w.owner('US1')}/{lot['id']}/content", milestone_id=ms["id"])
        assert c2["share_value"] == 1.0 and c2["milestone_id"] == ms["id"]
        # transfer US1 -> QC carries COO, value (FX) and shares
        qc_loc = qc.location("RCV", receipt_default=True)
        qc.item("NDL", "make", external_ref="NDL", family="NDL", lot_controlled=True)
        qndl = qc.by_pn("NDL")
        to = us.post("/transfer-orders", {"dest_plant_owner_id": w.owner("QC"), "lines": [
            {"item_id": ndl["id"], "qty": 5, "ship_date": date.today().isoformat(),
             "receive_date": date.today().isoformat()}]})
        to = us.post(f"/transfer-orders/{to['id']}/open", {}, status=200, version=to["row_version"])
        us.post("/inventory/postings", {"type": "transfer_ship", "lines": [
            {"transfer_line_id": to["lines"][0]["id"], "item_id": ndl["id"], "location_id": loc["id"], "qty": 5,
             "lot_code": "N1"}]})
        mirror = [t for t in qc.get("/transfer-orders")["items"] if t["direction"] == "in"][0]
        qc.post("/inventory/postings", {"type": "transfer_receipt", "lines": [
            {"transfer_line_id": mirror["lines"][0]["id"], "item_id": qndl["id"], "location_id": qc_loc["id"],
             "qty": 5, "lot_code": "N1"}]})
        ql = [x for x in qc.get("/lots", item_id=qndl["id"])["items"] if x["lot_code"] == "N1"][0]
        assert ql["coo"] == "US" and ql["coo_source"] == "transfer" and ql["dom_share_value"] == 1.0
        assert ql["unit_value"] == pytest.approx(30 * 1.40)
        # milestone report over the produced lot
        rep = net.post("/trade/reports", {"milestone_ids": [ms["id"]], "from": MONTH.isoformat(),
                                          "to": MONTH.isoformat(), "group_by": "family"}, status=202)
        rep = wait_for(lambda: net.get(f"/trade/reports/{rep['id']}"), lambda x: x["status"] in ("completed",
                                                                                                "failed"))
        assert rep["status"] == "completed", rep["error"]
        cell = rep["result"]["milestones"][0]["groups"][0]["cells"][0]
        assert cell["share_pct"] == 100.0 and cell["lots"] == 1
        # projection (next month): BOM share with every active supplier (50 / 50), then the scenario's 60 / 40 split
        nxt = date(MONTH.year + (MONTH.month == 12), MONTH.month % 12 + 1, 1)
        sc = net.post("/sop/scenarios", {"name": "Dual source", "changes": [
            {"kind": "supplier_allocation", "id": "c1", "node": "US1", "family": "STL",
             "suppliers": [{"code": "KT", "min_share": 0.6, "max_share": 0.6}, {"code": "AT", "min_share": 0.4,
                                                                                 "max_share": 0.4}]}]})
        shares = []
        for proj in (None, {"scenario_id": sc["id"]}):
            rp = net.post("/trade/reports", {"milestone_ids": [ms["id"]], "from": MONTH.isoformat(),
                                             "to": nxt.isoformat(), "projection": proj}, status=202)
            rp = wait_for(lambda: net.get(f"/trade/reports/{rp['id']}"), lambda x: x["status"] in ("completed",
                                                                                                  "failed"))
            cells = rp["result"]["milestones"][0]["groups"][0]["cells"]
            shares.append([c["share_pct"] for c in cells if c["projected"]])
        assert shares == [[50.0], [60.0]]
        x = net.req("GET", f"/trade/reports/{rep['id']}", 200, params={"format": "xlsx"})
        assert x.content[:2] == b"PK"
