"""S3 (M7-DESIGN 7): CAPA workflow, complaints with reportability, field actions from recalls (T-Q10), links,
attachments, external SoR switch."""

from __future__ import annotations

from typing import Any

from apimfgm2_helpers import Api


def test_capa_workflow(api):
    c = api.post("/qa/capas", {"title": "Drift", "risk": {"severity": 4, "occurrence": 4}})
    assert c["number"] == "CAPA-000001" and c["status"] == "draft" and c["risk"]["level"] == "high"
    api.post(f"/qa/capas/{c['id']}/advance", {"to": "investigation"}, 200)
    api.post(f"/qa/capas/{c['id']}/advance", {"to": "plan_approval"}, 200)
    e = api.err("POST", f"/qa/capas/{c['id']}/approve-plan", 409, "QA_CAPA_INCOMPLETE", json={})
    assert set(e["details"]["missing"]) == {"root_cause", "actions"}
    c = api.get(f"/qa/capas/{c['id']}")
    c = api.put(f"/qa/capas/{c['id']}", {"title": "Drift", "root_cause": {"method": "5_why", "text": "Lamp"}},
                c["row_version"])
    c = api.post(f"/qa/capas/{c['id']}/actions", {"description": "Add start-up check"})
    c = api.post(f"/qa/capas/{c['id']}/approve-plan", {}, 200)
    assert c["status"] == "implementation"
    api.err("POST", f"/qa/capas/{c['id']}/advance", 409, "QA_CAPA_ACTIONS_OPEN", json={"to": "effectiveness_check"})
    act = c["actions"][0]
    api.put(f"/qa/capas/{c['id']}/actions/{act['id']}", {"description": act["description"], "status": "done",
                                                          "evidence": "SOP rev 4"}, act["row_version"])
    api.post(f"/qa/capas/{c['id']}/advance", {"to": "effectiveness_check"}, 200)
    c = api.post(f"/qa/capas/{c['id']}/verify", {"result": "not_effective"}, 200)
    assert c["status"] == "investigation"
    api.post(f"/qa/capas/{c['id']}/advance", {"to": "plan_approval"}, 200)
    api.post(f"/qa/capas/{c['id']}/approve-plan", {}, 200)
    api.post(f"/qa/capas/{c['id']}/advance", {"to": "effectiveness_check"}, 200)
    api.post(f"/qa/capas/{c['id']}/verify", {"result": "effective"}, 200)
    c = api.post(f"/qa/capas/{c['id']}/close", {}, 200)
    assert c["status"] == "closed" and c["closed_at"]
    trail = api.get("/audit/record", entity_type="capa", entity_id=c["id"])
    assert [e["action"] for e in trail["items"]][:3] == ["create", "advance", "advance"]


def _recall_world(api: Api) -> dict[str, Any]:
    it = api.item("SYR", lot_controlled=True)
    st = api.location("ST")
    api.location("QR", "quarantine")
    api.receive(it["id"], st["id"], 100, lot_code="L-1")
    out = []
    for k, cust in enumerate(("CHU A", "CHU B")):
        o = api.post("/demand-orders", {"number": f"DO-{k + 1}", "demand_type": "customer", "customer": cust,
                                        "lines": [{"line_no": 1, "item_id": it["id"], "qty": 20,
                                                   "due_date": "2026-12-01"}]})
        if o["status"] == "draft":
            o = api.post(f"/demand-orders/{o['id']}/open", {}, status=200, version=o["row_version"])
        api.post("/inventory/postings", {"type": "ship", "lines": [
            {"demand_line_id": o["lines"][0]["id"], "location_id": st["id"], "qty": 20, "lot_code": "L-1"}]})
        out.append(o)
    lot = api.get("/lots", item_id=it["id"])["items"][0]
    return {"it": it, "st": st, "lot": lot, "orders": out}


def test_t_q10_complaint_recall_field_action(api):
    x = _recall_world(api)
    cmp_ = api.post("/qa/complaints", {"received_on": "2026-11-20", "aware_on": "2026-11-21", "customer": "CHU A",
                                       "item_id": x["it"]["id"], "lots": ["L-1", "NOPE"],
                                       "event_type": "serious_injury"})
    assert cmp_["lots"][0]["lot_id"] == x["lot"]["id"] and cmp_["lots"][1]["lot_id"] is None
    assert any("NOPE" in w for w in cmp_["warnings"])
    due = {d["regime"]: d for d in cmp_["reporting_due"]}
    assert due["hc_mdpr"]["days"] == 10 and due["hc_mdpr"]["due_on"] == "2026-12-01"
    assert due["fda_mdr"]["days"] == 30
    api.err("POST", f"/qa/complaints/{cmp_['id']}/close", 409, "QA_COMPLAINT_NOT_ASSESSED", json={})
    rc = api.post("/recalls", {"name": "Lot L-1", "sources": [{"kind": "lot", "id": x["lot"]["id"]}]})
    fa = api.post("/qa/field-actions", {"title": "Recall L-1", "recall_id": rc["id"], "class": "II"})
    api.post("/qa/links", {"from_type": "complaint", "from_id": cmp_["id"], "to_type": "field_action",
                           "to_id": fa["id"]})
    units = api.get(f"/qa/field-actions/{fa['id']}/units")["items"]
    shipped = [u for u in units if not u["in_stock"]]
    assert {u["customer"] for u in shipped} == {"CHU A", "CHU B"}
    assert [u for u in units if u["in_stock"]][0]["qty"] == 60
    fa = api.post(f"/qa/field-actions/{fa['id']}/approve", {}, 200)
    assert fa["status"] == "in_progress"
    assert api.get("/lots", item_id=x["it"]["id"])["items"][0]["hold"] is True
    a_unit = next(u for u in shipped if u["customer"] == "CHU A")
    fa = api.post(f"/qa/field-actions/{fa['id']}/units/bulk", {"items": [
        {"unit_id": a_unit["id"], "status": "returned", "note": "RMA 1"}]}, 200)
    eff = {b["customer"]: b for b in fa["effectiveness"]["by_customer"]}
    assert eff["CHU A"]["pct"] == 100.0 and eff["CHU B"]["pct"] == 0.0 and fa["effectiveness"]["overall"]["pct"] == 50
    api.err("POST", f"/qa/field-actions/{fa['id']}/complete", 409, "QA_UNITS_OPEN", json={})
    api.post(f"/qa/field-actions/{fa['id']}/complete", {"reason": "B unreachable, notified by registered mail"}, 200)
    r = api.req("GET", f"/qa/field-actions/{fa['id']}/export", 200, params={"format": "xlsx"})
    assert r.content[:2] == b"PK"
    fa = api.post(f"/qa/field-actions/{fa['id']}/close", {}, 200)
    assert fa["status"] == "closed" and fa["links"][0]["from_type"] == "complaint"
    assert api.get("/lots", item_id=x["it"]["id"])["items"][0]["hold"] is False
    c2 = api.put(f"/qa/complaints/{cmp_['id']}", {"received_on": "2026-11-20", "aware_on": "2026-11-21",
                                                  "customer": "CHU A", "event_type": "serious_injury",
                                                  "reportability": {"assessed": True, "reportable": True,
                                                                    "regimes": ["hc_mdpr"], "report_ref": "MDPR-1"}},
                 cmp_["row_version"])
    assert api.post(f"/qa/complaints/{c2['id']}/close", {}, 200)["status"] == "closed"


def test_attachments_sniffing_limits_and_lock(api):
    ncr = api.post("/qa/ncrs", {"title": "Scratch", "qty_nc": 1})
    url = "/qa/attachments"
    r = api.req("POST", url, 201, params={"entity_type": "ncr", "entity_id": ncr["id"], "filename": "a.png"},
                content=b"\x89PNG\r\n\x1a\n" + b"0" * 100, headers={"content-type": "image/png"})
    att = r.json()
    assert att["content_type"] == "image/png" and att["size"] == 108
    api.req("POST", url, 415, params={"entity_type": "ncr", "entity_id": ncr["id"], "filename": "x.exe"},
            content=b"MZ\x00\x00\x90", headers={"content-type": "application/octet-stream"})
    d = api.req("GET", f"/qa/attachments/{att['id']}", 200)
    assert d.headers["x-content-type-options"] == "nosniff" and "attachment" in d.headers["content-disposition"]
    assert api.get(f"/qa/ncrs/{ncr['id']}")["attachments"][0]["sha256"] == att["sha256"]
    api.post(f"/qa/ncrs/{ncr['id']}/cancel", {"reason": "dup"}, 200)
    api.req("DELETE", f"/qa/attachments/{att['id']}", 409)


def test_external_capa_sor(api):
    st = api.get("/plant/qa-settings")
    api.put("/plant/qa-settings", {**{k: v for k, v in st.items() if k != "row_version"}, "capa_sor": "external"},
            st["row_version"])
    api.err("POST", "/qa/capas", 422, "VALIDATION_ERROR", json={"title": "x"})
    c = api.post("/qa/capas", {"title": "In eQMS", "external_ref": "EQ-CAPA-77", "external_status": "open"})
    assert c["sor"] == "external" and c["status"] == "open"
    api.err("POST", f"/qa/capas/{c['id']}/advance", 409, "QA_EXTERNAL_SOR", json={"to": "investigation"})
