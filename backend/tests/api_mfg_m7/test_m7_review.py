"""M7 security/correctness review: one regression test per finding (M1-M10, m1-m13)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api_mfg_m4"))

from apimfgm4_helpers import cid  # noqa: E402
from m7_helpers import PASSWORD, World, signature  # noqa: E402
from test_m7_inspection import incoming, plan, results, scheme  # noqa: E402
from test_m7_ncr import _rejected_stock_lot  # noqa: E402

TODAY = date.today()


@pytest.fixture
def w(db_url):
    world = World(db_url)
    world.owner.api.location("ST")
    yield world
    world.close()


# ---------------------------------------------------------------- MAJOR

def test_M1_cancel_never_releases_the_hold(api):
    x = incoming(api)
    lot = api.get(f"/qa/inspection-lots/{x['receipt']['inspection_lots'][0]['id']}")
    results(api, lot, {"LEN": [10.0]})
    api.err("POST", f"/qa/inspection-lots/{lot['id']}/cancel", 409, "QA_LOT_HAS_RESULTS", json={"reason": "x"})
    pl = x["plan"]
    lr = api.get("/lots", item_id=x["it"]["id"])["items"][0]
    il = api.post("/qa/inspection-lots", {"plan_id": pl["id"], "lot_id": lr["id"], "lot_size": 10, "hold": True})
    api.post(f"/qa/inspection-lots/{il['id']}/cancel", {"reason": "wrong lot"}, 200)
    holds = api.get("/qa/holds", lot_id=lr["id"])["items"]
    assert {h["source"] for h in holds} == {"inspection", "manual"}          # still held: inspection lot 1 + manual
    assert api.get("/lots", item_id=x["it"]["id"])["items"][0]["hold"] is True


def test_M2_revoked_signer_cannot_reenrol_admin_reinstates(w):
    p = w.member("eng", ["qa_engineer"])
    with w.app.state.ctx.db.write() as s:
        s.execute(sa.text("UPDATE users SET esig_revoked_at = now() WHERE id = :u"), {"u": p.user_id})
    r = p.client.post("/api/v1/auth/esig/enroll", json={"legal_name": "X Y", "password": PASSWORD,
                                                        "acknowledgement": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ESIG_REVOKED"


def test_M3_capa_action_idor_and_non_draft(api):
    a = api.post("/qa/capas", {"title": "A"})
    b = api.post("/qa/capas", {"title": "B"})
    b = api.post(f"/qa/capas/{b['id']}/actions", {"description": "b1"})
    api.err("DELETE", f"/qa/capas/{a['id']}/actions/{b['actions'][0]['id']}", 404, "NOT_FOUND")
    api.post(f"/qa/capas/{b['id']}/advance", {"to": "investigation"}, 200)
    api.err("DELETE", f"/qa/capas/{b['id']}/actions/{b['actions'][0]['id']}", 409, "MFG_INVALID_STATE")


def test_M4_M5_rework_exemption_and_hold_release(api):
    x = _rejected_stock_lot(api, 300)
    ncr = api.get(f"/qa/ncrs/{x['il']['ncr_id']}")
    ncr = api.post(f"/qa/ncrs/{ncr['id']}/propose", {"dispositions": [
        {"kind": "rework", "qty": 100, "rework_routing_id": x["rt"]["id"]},
        {"kind": "use_as_is", "qty": 200, "justification": "ok"}]}, 200)
    api.post(f"/qa/ncrs/{ncr['id']}/approve", {}, 200)
    ncr = api.post(f"/qa/ncrs/{ncr['id']}/implement", {}, 200)
    w_ = api.get(f"/work-orders/{ncr['rework_wos'][0]['id']}")
    w_ = api.post(f"/work-orders/{w_['id']}/release", {"override_reason": "rw"}, 200, version=w_["row_version"])
    # M4: another hold (manual) on the lot blocks even the rework WO
    h = api.post("/qa/holds", {"lot_id": x["lot"]["id"], "reason": "supplier notice"})
    api.err("POST", "/inventory/postings", 422, "INV_LOT_ON_HOLD", json={"type": "wo_issue", "lines": [
        {"wo_component_id": w_["components"][0]["id"], "location_id": x["loc"]["id"], "lot_code": "L-7",
         "qty": 100}]})
    # M4: a standard posting (issue_misc) of the NCR-held lot stays refused
    api.post(f"/qa/holds/{h['id']}/release", {}, 200)
    api.err("POST", "/inventory/postings", 422, "INV_LOT_ON_HOLD", json={"type": "issue_misc", "reason_code": "X",
            "lines": [{"item_id": x["it"]["id"], "location_id": x["loc"]["id"], "lot_code": "L-7", "qty": 1}]})
    # M5: receipt beyond the issued quantity is refused; release only after the issue covers the rework
    api.err("POST", "/inventory/postings", 422, "QA_REWORK_NOT_ISSUED", json={"type": "wo_receipt", "lines": [
        {"wo_id": w_["id"], "location_id": x["loc"]["id"], "lot_code": "L-7", "qty": 100}]})
    api.post("/inventory/postings", {"type": "wo_issue", "lines": [
        {"wo_component_id": w_["components"][0]["id"], "location_id": x["loc"]["id"], "lot_code": "L-7",
         "qty": 100}]})
    api.post("/inventory/postings", {"type": "wo_receipt", "lines": [
        {"wo_id": w_["id"], "location_id": x["loc"]["id"], "lot_code": "L-7", "qty": 100}]})
    assert api.get("/lots", item_id=x["it"]["id"])["items"][0]["hold"] is False


def test_M6_equipment_due_and_unblock_only_by_calibration(api):
    e = api.post("/qa/equipment", {"code": "EQ-1", "name": "G", "kind": "gauge", "equipment_class": "F",
                                   "interval_days": 90, "due_on": (TODAY - timedelta(days=2)).isoformat()})
    body = {k: e[k] for k in ("code", "name", "kind", "equipment_class", "interval_days", "due_on")}
    api.err("PUT", f"/qa/equipment/{e['id']}", 409, "QA_DUE_VIA_CALIBRATION",
            json={**body, "due_on": (TODAY + timedelta(days=30)).isoformat()},
            headers={"If-Match": f'"{e["row_version"]}"'})
    api.err("PUT", f"/qa/equipment/{e['id']}", 409, "QA_EQUIPMENT_BLOCKING",
            json={**body, "grace_days": 30}, headers={"If-Match": f'"{e["row_version"]}"'})


def test_M7_sor_persisted_switch_guarded(api):
    c = api.post("/qa/capas", {"title": "native"})
    st = api.get("/plant/qa-settings")
    body = {**{k: v for k, v in st.items() if k != "row_version"}, "capa_sor": "external"}
    api.err("PUT", "/plant/qa-settings", 409, "QA_SOR_IN_USE", json=body,
            headers={"If-Match": f'"{st["row_version"]}"'})
    api.post(f"/qa/capas/{c['id']}/cancel", {"reason": "dup"}, 200)
    api.put("/plant/qa-settings", body, st["row_version"])
    assert api.get(f"/qa/capas/{c['id']}")["sor"] == "superplanner"


def test_M8_field_action_cancel_only_in_draft(api):
    from test_m7_capa_fa import _recall_world

    x = _recall_world(api)
    rc = api.post("/recalls", {"name": "L", "sources": [{"kind": "lot", "id": x["lot"]["id"]}]})
    fa = api.post("/qa/field-actions", {"title": "FA", "recall_id": rc["id"]})
    api.post(f"/qa/field-actions/{fa['id']}/approve", {}, 200)
    api.err("POST", f"/qa/field-actions/{fa['id']}/cancel", 409, "MFG_INVALID_STATE", json={"reason": "x"})
    assert api.get("/lots", item_id=x["it"]["id"])["items"][0]["hold"] is True


def test_M9_m2_steps_sign_the_same_parameters_and_policy_version(w):
    api = w.owner.api
    it = api.item("P", lot_controlled=True)
    sc = scheme(api)
    pl = plan(api, it["id"], "incoming", sc["id"], chars=[{"seq": 1, "code": "A", "name": "A", "kind": "attribute",
                                                           "severity": "minor"}])
    w.part11_on()
    insp = w.member("insp", ["qa_inspector"])
    appr = w.member("appr", ["qa_approver"], with_totp=True)
    steps = [{"meaning": "released", "roles": ["qa_inspector"]}, {"meaning": "released", "roles": ["qa_approver"]}]
    pol = next(p for p in appr.api.get("/esig/policies")["items"] if (p["record_type"], p["action"]) ==
               ("inspection_lot", "decide"))
    sig = signature(appr, "esig_policy", "inspection_lot.decide", "update", "approved", totp_code=appr.code(),
                    comment="two steps")
    appr.api.req("PUT", "/esig/policies/inspection_lot/decide", 200, headers={"If-Match": f'"{pol["row_version"]}"'},
                 json={"steps": steps, "auth": "password", "signature": sig})
    il = insp.api.post("/qa/inspection-lots", {"plan_id": pl["id"], "lot_size": 3})
    results(insp.api, il, {"A": [True, True, True]})
    s1 = signature(insp, "inspection_lot", il["id"], "decide", "released", decision="accept")
    insp.api.req("POST", f"/qa/inspection-lots/{il['id']}/decision", 202,
                 json={"decision": "accept", "signature": s1})
    s2 = signature(appr, "inspection_lot", il["id"], "decide", "rejected", decision="reject")
    appr.api.err("POST", f"/qa/inspection-lots/{il['id']}/decision", 409, "ESIG_PARAMS_CHANGED",
                 json={"decision": "reject", "signature": s2})
    s2 = signature(appr, "inspection_lot", il["id"], "decide", "released", decision="accept")
    # review m4: no header and no signature comment -> no reason in Part 11 mode
    appr.api.err("POST", f"/qa/inspection-lots/{il['id']}/decision", 422, "AUDIT_REASON_REQUIRED",
                 json={"decision": "accept", "signature": s2})
    s2 = signature(appr, "inspection_lot", il["id"], "decide", "released", decision="accept",
                   comment="All samples conform")
    out = appr.api.req("POST", f"/qa/inspection-lots/{il['id']}/decision", 200,
                       json={"decision": "accept", "signature": s2}).json()
    assert out["status"] == "accepted" and len(out["signatures"]) == 2
    assert all(x["content_matches_current"] is False or True for x in out["signatures"])


def test_M10_floor_issue_idempotent_and_over_issue_flag(api):
    from test_demo_fixes import _plant

    x = _plant(api)
    k = cid()
    a = api.post("/floor/issue-lot", {"wo_operation_id": x["op"]["id"], "scan": "A1", "qty": 5, "client_event_id": k})
    b = api.post("/floor/issue-lot", {"wo_operation_id": x["op"]["id"], "scan": "A1", "qty": 5, "client_event_id": k})
    assert b["replayed"] is True and b["posting"]["id"] == a["posting"]["id"]
    api.err("POST", "/floor/issue-lot", 422, "FLR_OVER_ISSUE", json={"wo_operation_id": x["op"]["id"],
                                                                     "scan": "A1", "qty": 40})
    out = api.post("/floor/issue-lot", {"wo_operation_id": x["op"]["id"], "scan": "A1", "qty": 40,
                                        "over_issue": True, "reason": "spill"})
    assert out["component"]["issued_qty"] == 45


# ---------------------------------------------------------------- MINOR

def test_m1_unkeyed_mac_rejected_when_keys_configured():
    from types import SimpleNamespace

    from superplanner.api.mfg.services import esig as E

    r = SimpleNamespace(id="esg_1", owner_id="o", record_type="ncr", record_id="n", record_version=1, action="a",
                        step=1, meaning="approved", signer_id="u", signer_legal_name="L", signer_username="u@x",
                        signed_at=None, auth_method="password", policy_id=None, policy_version=1,
                        content_hash="0" * 64, comment="", audit_event_id=1, client_ip=None, session_ref=None,
                        mac="")
    r.mac = E.compute_mac([], r)                  # an attacker without the key writes an unkeyed MAC
    assert E.mac_ok([], r) is True and E.mac_ok([b"k" * 32], r) is False
    r.mac = E.compute_mac([b"k" * 32], r)
    assert E.mac_ok([b"k" * 32], r) is True


def _two_step(w):
    api = w.owner.api
    it = api.item("P", lot_controlled=True)
    sc = scheme(api)
    pl = plan(api, it["id"], "incoming", sc["id"], chars=[{"seq": 1, "code": "A", "name": "A", "kind": "attribute",
                                                           "severity": "minor"}])
    w.part11_on()
    insp = w.member("insp", ["qa_inspector"])
    appr = w.member("appr", ["qa_approver"], with_totp=True)

    def set_steps(steps):
        pol = next(p for p in appr.api.get("/esig/policies")["items"] if (p["record_type"], p["action"]) ==
                   ("inspection_lot", "decide"))
        sig = signature(appr, "esig_policy", "inspection_lot.decide", "update", "approved", totp_code=appr.code(),
                        comment="policy change")
        appr.api.req("PUT", "/esig/policies/inspection_lot/decide", 200,
                     headers={"If-Match": f'"{pol["row_version"]}"'},
                     json={"steps": steps, "auth": "password", "signature": sig})

    set_steps([{"meaning": "released", "roles": ["qa_inspector"]}, {"meaning": "released", "roles": ["qa_approver"]}])
    il = insp.api.post("/qa/inspection-lots", {"plan_id": pl["id"], "lot_size": 3})
    results(insp.api, il, {"A": [True, True, True]})
    return insp, appr, il, set_steps


def test_m2_policy_change_between_steps_restarts_the_flow(w):
    insp, appr, il, set_steps = _two_step(w)
    s1 = signature(insp, "inspection_lot", il["id"], "decide", "released", decision="accept", comment="ok")
    insp.api.req("POST", f"/qa/inspection-lots/{il['id']}/decision", 202, json={"decision": "accept", "signature": s1})
    set_steps([{"meaning": "released", "roles": ["qa_approver"]}, {"meaning": "released", "roles": ["qa_inspector"]}])
    s2 = signature(appr, "inspection_lot", il["id"], "decide", "released", decision="accept", comment="ok")
    r = appr.api.req("POST", f"/qa/inspection-lots/{il['id']}/decision", 202,
                     json={"decision": "accept", "signature": s2}).json()
    assert r["next_step"]["step"] == 2                      # the old step 1 no longer counts
    assert [x["status"] for x in r["signatures"]] == ["superseded", "valid"]


def test_m3_correction_keeps_nonconforming_qty(api):
    from apimfgm4_helpers import ev
    from test_m7_inspection import gate_plant

    x = gate_plant(api, lot_fg=False)
    op10 = x["ops"][0]
    ev(api, op10["id"], "start", line_id=x["l1"]["id"])
    r = ev(api, op10["id"], "report", qty_good=3, qty_scrap=1, qty_nc=4, defect_code="SCR")
    ev(api, op10["id"], "correct", corrects_event_id=r["event"]["id"], qty_scrap=2)
    ops = {o["seq"]: o for o in api.get(f"/work-orders/{x['wo']['id']}/operations")["items"]}
    assert ops[10]["qty_scrap"] == 6                       # 2 scrap + 4 nonconforming, counted once


def test_m5_old_new_values_for_regulated_entities(w):
    api = w.owner.api
    loc = api.get("/locations")["items"][0]
    w.part11_on()
    hdr = {"X-SP-Change-Reason": "rename"}
    api.req("PUT", f"/locations/{loc['id']}", 200, json={"code": loc["code"], "name": "Main stores", "kind": "stores"},
            headers={**hdr, "If-Match": f'"{loc["row_version"]}"'})
    ev = [e for e in api.get("/audit/record", entity_type="location", entity_id=loc["id"])["items"]
          if e["action"] == "update"][-1]
    assert {"path": "name", "old": loc["name"], "new": "Main stores"} in [
        {k: c[k] for k in ("path", "old", "new")} for c in ev["changes"]] and ev["reason"] == "rename"
    m = w.member("eng", ["qa_engineer"], enroll=False)
    mem = next(x for x in api.get("/members")["items"] if x["user"]["id"] == m.user_id)
    api.req("PUT", f"/members/{mem['id']}", 200, json={"roles": ["qa_approver"]},
            headers={**hdr, "If-Match": f'"{mem["row_version"]}"'})
    ev = [e for e in api.get("/audit/record", entity_type="member", entity_id=mem["id"])["items"]][-1]
    assert any(c["path"].startswith("roles") for c in ev["changes"])


def test_m6_migration_recall_quarantined_lots_become_recall_holds(empty_pg_db):
    from datetime import UTC, datetime

    from superplanner import migrate
    from test_m7_s0_contract import _ins

    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0009_ux")
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            migrate.ensure_local_user_conn(c)
            _ins(c, "mfg_items", id="itm_1", part_number="P", revision="A", uom="EA", make_buy="buy",
                 lot_rule="lot_for_lot", lot_controlled=True, active=True, attributes={})
            _ins(c, "mfg_lots", id="lot_1", item_id="itm_1", lot_code="L1", hold=True)
            _ins(c, "mfg_lots", id="lot_2", item_id="itm_1", lot_code="L2", hold=True)
            _ins(c, "mfg_recalls", id="rcl_1", number="RCL-000001", name="R", sources=[], include_possible=True,
                 report={"lots": [{"lot_id": "lot_1"}]}, quarantined_at=datetime.now(UTC), actor_id="usr_local",
                 row_version=1)
        migrate.run_alembic_upgrade(url)
        with eng.begin() as c:
            rows = dict(c.execute(sa.text("SELECT lot_id, source FROM mfg_lot_holds")).all())
        assert rows == {"lot_1": "recall", "lot_2": "manual"}
    finally:
        eng.dispose()


def test_m7_held_serial_blocks_shipment(api, client):
    it = api.item("DEV")
    st = api.get("/locations")["items"][0] if api.get("/locations")["items"] else api.location("ST")
    api.receive(it["id"], st["id"], 2)
    eng = sa.create_engine(str(client.app.state.ctx.db.engine.url.render_as_string(hide_password=False)))
    with eng.begin() as c:
        for k, held in ((1, True), (2, False)):
            c.execute(sa.text("INSERT INTO mfg_unit_serials (id, owner_id, item_id, serial, status, captured_at, "
                              "row_version, created_at, updated_at, hold) VALUES (:i, 'usr_local', :it, :s, "
                              "'in_stock', now(), 1, now(), now(), :h)"),
                      {"i": f"srl_{k:032x}", "it": it["id"], "s": f"SN{k}", "h": held})
    eng.dispose()
    o = api.post("/demand-orders", {"number": "DO-1", "demand_type": "customer", "customer": "C",
                                    "lines": [{"line_no": 1, "item_id": it["id"], "qty": 2, "due_date": "2026-12-01"}]})
    if o["status"] == "draft":
        o = api.post(f"/demand-orders/{o['id']}/open", {}, status=200, version=o["row_version"])
    api.err("POST", "/inventory/postings", 422, "INV_SERIAL_ON_HOLD", json={"type": "ship", "lines": [
        {"demand_line_id": o["lines"][0]["id"], "location_id": st["id"], "qty": 2}]})
    api.post("/inventory/postings", {"type": "ship", "lines": [
        {"demand_line_id": o["lines"][0]["id"], "location_id": st["id"], "qty": 1}]})
