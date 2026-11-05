"""Engineering changes (M5-DESIGN 5; T-E1, T-E2, self-approval, document locks, ERP-sourced ECO)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apimfgm2_helpers import Api, acc_app, sign_up


def _plant(api: Api) -> dict:
    st = api.location("ST")
    old = api.item("CAP-A", standard_cost=3.0)
    new = api.item("CAP-B", standard_cost=4.0)
    pcb = api.item("PCB", "make")
    b1 = api.post("/boms", {"item_id": pcb["id"], "lines": [{"find_number": "1", "child_item_id": old["id"],
                                                             "qty_per": 2}]})
    b1 = api.post(f"/boms/{b1['id']}/release", {"effective_from": "2026-01-01"}, status=200,
                  version=b1["row_version"])["bom"]
    api.receive(old["id"], st["id"], 380)
    sup = api.supplier("SUP")
    po = api.post("/purchase-orders", {"supplier_id": sup["id"], "lines": [
        {"item_id": old["id"], "schedules": [{"requested_date": "2026-12-01", "qty": 1000}]}]})
    wo = api.post("/work-orders", {"item_id": pcb["id"], "qty": 15, "due_date": "2026-12-10",
                                   "start_date": "2026-12-01"})
    api.post("/work-orders", {"item_id": pcb["id"], "qty": 5, "due_date": "2027-02-15", "start_date": "2027-02-01"})
    do = api.post("/demand-orders", {"number": "DO-1", "demand_type": "customer", "customer": "C",
                                     "lines": [{"line_no": 1, "item_id": pcb["id"], "qty": 800,
                                                "due_date": "2026-12-20"}]})
    if do["status"] == "draft":
        api.post(f"/demand-orders/{do['id']}/open", {}, status=200, version=do["row_version"])
    draft = api.post(f"/boms/{b1['id']}/copy", {}, version=b1["row_version"])
    draft = api.put(f"/boms/{draft['id']}", {"item_id": pcb["id"], "lines": [
        {"find_number": "1", "child_item_id": new["id"], "qty_per": 2}]}, draft["row_version"])
    return {"st": st, "old": old, "new": new, "pcb": pcb, "b1": b1, "draft": draft, "po": po, "wo": wo}


def test_t_e1_impact_approval_implement_and_locks(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        oc = sign_up(app, "owner@x.example")
        owner = Api(oc)
        oid = oc.get("/api/v1/auth/session").json()["user"]["id"]
        d = _plant(owner)
        pc = sign_up(app, "pa@x.example")
        owner.post("/members", {"email": "pa@x.example", "roles": ["planner", "approver"]})
        ap = sign_up(app, "ap@x.example")
        owner.post("/members", {"email": "ap@x.example", "roles": ["approver"]})
        planner, approver = Api(pc, oid), Api(ap, oid)
        cr = planner.post("/eco", {"title": "Replace C14", "effectivity": {"mode": "date", "date": "2027-01-01"}})
        assert cr["number"] == "ECO-000001" and cr["status"] == "draft"
        cr = planner.post(f"/eco/{cr['id']}/items", {"doc_type": "bom", "doc_id": d["draft"]["id"]})
        assert cr["items"][0]["supersedes_doc_id"] == d["b1"]["id"]
        bom = owner.get(f"/boms/{d['draft']['id']}")
        assert bom["locked_by_cr"]["number"] == "ECO-000001"
        owner.err("POST", f"/boms/{bom['id']}/release", 409, "ECO_DOC_LOCKED", json={},
                  headers={"If-Match": f'"{bom["row_version"]}"'})
        imp = planner.get(f"/eco/{cr['id']}/impact")
        delta = imp["explosion_delta"][0]
        assert delta["added"] == ["CAP-B"] and delta["removed"] == ["CAP-A"]
        assert [w["number"] for w in imp["open_wos"]] == [d["wo"]["number"], "WO-000002"]
        st = imp["phase_out_stock"][0]
        assert st["on_hand"] == 380 and st["on_order"] == 1000 and st["value"] == 4140.0
        assert imp["use_up_date"] is not None and imp["open_purchases"][0]["open_qty"] == 1000
        assert isinstance(imp["mrp_delta"], list) and not any("error" in x for x in imp["mrp_delta"]), imp
        cr = planner.get(f"/eco/{cr['id']}")
        cr = planner.post(f"/eco/{cr['id']}/submit", {}, status=200, version=cr["row_version"])
        e = planner.err("POST", f"/eco/{cr['id']}/approve", 409, "ECO_SELF_APPROVAL", json={},
                        headers={"If-Match": f'"{cr["row_version"]}"'})
        assert e["details"]["submitted_by"]
        cr = approver.post(f"/eco/{cr['id']}/approve", {}, status=200, version=cr["row_version"])
        assert cr["status"] == "approved" and cr["approved_by"]["id"]
        approver.err("POST", f"/eco/{cr['id']}/implement", 403, "MFG_FORBIDDEN", json={})
        cr = planner.post(f"/eco/{cr['id']}/implement", {}, status=200, version=cr["row_version"])
        assert cr["status"] == "implemented" and cr["implemented_at"]
        new = owner.get(f"/boms/{d['draft']['id']}")
        old = owner.get(f"/boms/{d['b1']['id']}")
        assert new["status"] == "released" and new["effective_from"] == "2027-01-01"
        assert old["effective_to"] == "2027-01-01"          # M1: effective_to is exclusive
        ex0 = owner.get(f"/items/{d['pcb']['id']}/explosion", on="2026-12-15")
        ex1 = owner.get(f"/items/{d['pcb']['id']}/explosion", on="2027-01-15")
        assert str(ex0).count("CAP-A") and not str(ex0).count("CAP-B")
        assert str(ex1).count("CAP-B") and not str(ex1).count("CAP-A")
        notes = owner.get("/notifications")["items"]
        assert {n["kind"] for n in notes} >= {"ECO_WO_DIFFERS", "ECO_PO_NOT_NEEDED"}


def test_t_e2_release_blocked_nothing_released(api):
    d = _plant(api)
    other = api.item("PCB2", "make")
    empty = api.post("/boms", {"item_id": other["id"], "lines": []})
    cr = api.post("/eco", {"title": "Two docs", "effectivity": {"mode": "date", "date": "2027-01-01"}})
    api.post(f"/eco/{cr['id']}/items", {"doc_type": "bom", "doc_id": d["draft"]["id"]})
    cr = api.post(f"/eco/{cr['id']}/items", {"doc_type": "bom", "doc_id": empty["id"]})
    for a in ("submit", "approve"):
        cr = api.post(f"/eco/{cr['id']}/{a}", {}, status=200, version=cr["row_version"])
    e = api.err("POST", f"/eco/{cr['id']}/implement", 422, "ECO_RELEASE_BLOCKED", json={},
                headers={"If-Match": f'"{cr["row_version"]}"'})
    assert any(i["code"] == "MFG_BOM_EMPTY" for i in e["details"]["issues"])
    assert api.get(f"/boms/{d['draft']['id']}")["status"] == "draft"
    assert api.get(f"/eco/{cr['id']}")["status"] == "approved"
    cr = api.post(f"/eco/{cr['id']}/cancel", {}, status=200, version=cr["row_version"])
    assert api.get(f"/boms/{d['draft']['id']}")["locked_by_cr_id"] is None
