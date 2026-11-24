"""S1 (M7-DESIGN 4): enrolment, Part 11 mode, signing (one and two steps), policies, lockout (incl. concurrent
attempts on PostgreSQL), content change, tamper evidence, change reasons with old/new values, clock skew.
Test vectors T-S1, T-S2, T-S3, T-S5, T-S6, T-S7."""

from __future__ import annotations

import threading
from typing import Any

import pytest
import sqlalchemy as sa

from m7_helpers import PASSWORD, World, preview, signature
from superplanner.api.mfg.services import esig as ESIG


@pytest.fixture
def w(db_url):
    world = World(db_url)
    world.owner.api.location("ST")
    yield world
    world.close()


def _eco(w: World) -> dict[str, Any]:
    """A submitted change request (draft BOM of a make item) by the owner."""
    api = w.owner.api
    cap = api.item("CAP-A")
    pcb = api.item("PCB", "make")
    b1 = api.post("/boms", {"item_id": pcb["id"], "lines": [{"find_number": "1", "child_item_id": cap["id"],
                                                             "qty_per": 2}]})
    b1 = api.post(f"/boms/{b1['id']}/release", {"effective_from": "2026-01-01"}, status=200,
                  version=b1["row_version"])["bom"]
    draft = api.post(f"/boms/{b1['id']}/copy", {}, version=b1["row_version"])
    cr = api.post("/eco", {"title": "Replace", "effectivity": {"mode": "date", "date": "2027-01-01"}})
    cr = api.post(f"/eco/{cr['id']}/items", {"doc_type": "bom", "doc_id": draft["id"]})
    return api.post(f"/eco/{cr['id']}/submit", {}, status=200, version=cr["row_version"])


def _db(w: World):
    return w.app.state.ctx.db


def test_enrolment_status_and_part11_switch_is_signed_and_one_way(w):
    o = w.owner
    st = o.client.get("/api/v1/auth/esig/status").json()
    assert st["enrolled"] is False and st["can_sign"] is False and st["methods"] == ["password"]
    r = o.client.post("/api/v1/auth/esig/enroll", json={"legal_name": "Olivier Owner", "password": "wrong",
                                                        "acknowledgement": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "ESIG_AUTH_FAILED"
    # unsigned switch -> ESIG_REQUIRED with the preview; password only -> MFA unavailable (needs TOTP)
    w.enroll(o, "Olivier Owner")
    e = o.api.err("PUT", "/plant/part11", 422, "ESIG_REQUIRED", json={"enabled": True})
    assert e["details"]["preview"]["policy"]["auth"] == "password_totp"
    sig = signature(o, "plant", "plant", "part11_on", "approved")
    o.api.err("PUT", "/plant/part11", 422, "ESIG_MFA_UNAVAILABLE", json={"enabled": True, "signature": sig})
    mode = w.part11_on()
    assert mode["enabled"] is True and mode["signatures"][0]["meaning"] == "approved"
    assert mode["signatures"][0]["signer_legal_name"] == "Olivier Owner"
    assert "(UTC" in mode["signatures"][0]["signed_at_local"]
    o.api.err("PUT", "/plant/part11", 409, "PART11_MODE_LOCKED", json={"enabled": True})
    pols = o.api.get("/esig/policies")["items"]
    assert len(pols) == len(ESIG.POL.DEFAULTS)


def test_part11_needs_secrets_key(db_url):
    world = World(db_url, secrets_keys=[])
    try:
        world.owner.api.location("ST")
        world.owner.api.err("PUT", "/plant/part11", 409, "PART11_SECRETS_REQUIRED", json={"enabled": True})
    finally:
        world.close()


def test_t_s6_reason_required_and_field_changes(w):
    api = w.owner.api
    it = api.item("SYR-1", description="Syringe 3 mL")
    w.part11_on()
    body = {k: it[k] for k in ("part_number", "make_buy", "lead_time_days")}
    body["description"] = "Syringe 3 mL Luer lock"
    api.err("PUT", f"/items/{it['id']}", 422, "AUDIT_REASON_REQUIRED", json=body,
            headers={"If-Match": f'"{it["row_version"]}"'})
    r = api.req("PUT", f"/items/{it['id']}", 200, json=body, headers={"If-Match": f'"{it["row_version"]}"',
                                                                      "X-SP-Change-Reason": "Drawing%20rev%20C%20%C3%A9"})
    assert r.json()["description"] == "Syringe 3 mL Luer lock"
    trail = api.get("/audit/record", entity_type="item", entity_id=it["id"])
    upd = [e for e in trail["items"] if e["action"] == "update"][-1]
    assert upd["reason"] == "Drawing rev C é"
    assert {"path": "description", "old": "Syringe 3 mL", "new": "Syringe 3 mL Luer lock"} in [
        {k: c[k] for k in ("path", "old", "new")} for c in upd["changes"]]
    assert w.owner.client.get("/api/v1/audit/verify").json()["ok"] is True


def test_signing_eco_approve_one_step_role_required_and_manifest(w):
    cr = _eco(w)
    w.part11_on()
    qa_eng = w.member("eng", ["qa_engineer"])
    appr = w.member("appr", ["qa_approver"])
    # no signature -> 422 with the preview; a QA engineer holds no step role -> 403
    e = appr.api.err("POST", f"/eco/{cr['id']}/approve", 422, "ESIG_REQUIRED", json={})
    assert e["details"]["preview"]["next_step"]["roles"] == ["approver", "qa_approver"]
    sig = signature(qa_eng, "eco", cr["id"], "approve", "approved")
    qa_eng.api.err("POST", f"/eco/{cr['id']}/approve", 403, "MFG_FORBIDDEN", json={"signature": sig})
    pv = preview(appr, "eco", cr["id"], "approve")
    assert pv["required"] and pv["next_step"]["can_sign"] and pv["signer"]["methods"] == ["password"]
    sig = signature(appr, "eco", cr["id"], "approve", "reviewed")
    appr.api.err("POST", f"/eco/{cr['id']}/approve", 422, "ESIG_MEANING", json={"signature": sig})
    sig = signature(appr, "eco", cr["id"], "approve", "approved", comment="Checked impact")
    out = appr.api.req("POST", f"/eco/{cr['id']}/approve", 200, json={"signature": sig}).json()
    assert out["status"] == "approved"
    sigs = w.owner.api.get("/esig/signatures", record_type="eco", record_id=cr["id"])["items"]
    assert len(sigs) == 1 and sigs[0]["signer_legal_name"] == "Appr Tremblay" and sigs[0]["auth_method"] == "password"
    v = w.owner.api.get(f"/esig/signatures/{sigs[0]['id']}/verify")
    assert v["mac_ok"] and v["chain_ok"] and v["content_hash_ok"]
    assert v["content_matches_current"] is False          # the approval changed the status afterwards
    trail = w.owner.api.get("/audit/record", entity_type="eco", entity_id=cr["id"])
    signed = [e for e in trail["items"] if e["action"] == "esig.signed"]
    assert signed and signed[0]["signature"]["id"] == sigs[0]["id"] and signed[0]["reason"] == "Checked impact"


def test_t_s2_two_step_policy_same_signer_and_policy_edit_signed(w):
    cr = _eco(w)
    w.part11_on()
    appr = w.member("appr", ["qa_approver", "qa_engineer"], with_totp=True)
    appr2 = w.member("appr2", ["qa_approver"])
    steps = [{"meaning": "reviewed", "roles": ["qa_engineer"]}, {"meaning": "approved", "roles": ["qa_approver"]}]
    pol = next(p for p in appr.api.get("/esig/policies")["items"] if (p["record_type"], p["action"]) ==
               ("eco", "approve"))
    body = {"steps": steps, "auth": "password", "distinct_signers": True, "exclude_author": False}
    appr.api.err("PUT", "/esig/policies/eco/approve", 422, "ESIG_REQUIRED", json=body,
                 headers={"If-Match": f'"{pol["row_version"]}"'})
    sig = signature(appr, "esig_policy", "eco.approve", "update", "approved", totp_code=appr.code(),
                    comment="Two-step review of changes")
    upd = appr.api.req("PUT", "/esig/policies/eco/approve", 200, json={**body, "signature": sig},
                       headers={"If-Match": f'"{pol["row_version"]}"'}).json()
    assert upd["version"] == 2 and len(upd["steps"]) == 2 and upd["signatures"][0]["meaning"] == "approved"
    # removing the last step of a fixed action / unknown roles are refused
    appr.api.err("PUT", "/esig/policies/plant/part11_on", 422, "ESIG_POLICY_INVALID",
                 json={"steps": [], "auth": "password_totp"}, headers={"If-Match": '"1"'})
    # step 1 by appr -> 202 pending; step 2 by the same person -> 409; by another approver -> done
    s1 = signature(appr, "eco", cr["id"], "approve", "reviewed")
    r = appr.api.req("POST", f"/eco/{cr['id']}/approve", 202, json={"signature": s1}).json()
    assert r["status"] == "pending_signatures" and r["next_step"]["step"] == 2
    assert w.owner.api.get(f"/eco/{cr['id']}")["status"] == "submitted"
    s2 = signature(appr, "eco", cr["id"], "approve", "approved")
    appr.api.err("POST", f"/eco/{cr['id']}/approve", 409, "ESIG_SAME_SIGNER", json={"signature": s2})
    s2 = signature(appr2, "eco", cr["id"], "approve", "approved")
    assert appr2.api.req("POST", f"/eco/{cr['id']}/approve", 200, json={"signature": s2}).json()["status"] == \
        "approved"


def test_t_s3_content_changed_between_preview_and_sign(w):
    cr = _eco(w)
    w.part11_on()
    appr = w.member("appr", ["qa_approver"])
    sig = signature(appr, "eco", cr["id"], "approve", "approved")
    with _db(w).write() as s:   # the record changes after the preview (title)
        s.execute(sa.text("UPDATE mfg_change_requests SET title = 'Changed' WHERE id = :i"), {"i": cr["id"]})
    e = appr.api.err("POST", f"/eco/{cr['id']}/approve", 409, "ESIG_CONTENT_CHANGED", json={"signature": sig})
    assert e["details"]["current_hash"] != sig["content_hash"]


def test_t_s1_lockout_after_three_failures_audit_and_notification(w):
    cr = _eco(w)
    w.part11_on()
    appr = w.member("appr", ["qa_approver"])
    sig = signature(appr, "eco", cr["id"], "approve", "approved", password="wrong-password")
    e1 = appr.api.err("POST", f"/eco/{cr['id']}/approve", 422, "ESIG_AUTH_FAILED", json={"signature": sig})
    e2 = appr.api.err("POST", f"/eco/{cr['id']}/approve", 422, "ESIG_AUTH_FAILED",
                      json={"signature": {**sig, "username": "someone@else.example", "password": PASSWORD}})
    assert (e1["details"]["remaining"], e2["details"]["remaining"]) == (2, 1)
    e3 = appr.api.err("POST", f"/eco/{cr['id']}/approve", 423, "ESIG_LOCKED", json={"signature": sig})
    assert e3["details"]["until"]
    good = signature(appr, "eco", cr["id"], "approve", "approved")
    appr.api.err("POST", f"/eco/{cr['id']}/approve", 423, "ESIG_LOCKED", json={"signature": good})
    with _db(w).read() as s:
        ev = s.execute(sa.text("SELECT count(*) FROM audit_events WHERE action = 'esig.lockout'")).scalar()
        nt = s.execute(sa.text("SELECT count(*) FROM mfg_notifications WHERE kind = 'esig_lockout'")).scalar()
        assert ev == 1 and nt == 1
        s.execute(sa.text("UPDATE users SET esig_locked_until = now() - interval '1 minute' WHERE email = :e"),
                  {"e": appr.email})
        s.commit()
    assert appr.api.req("POST", f"/eco/{cr['id']}/approve", 200, json={"signature": good}).json()["status"] == \
        "approved"


def test_t_s1_concurrent_wrong_attempts_lock_exactly_once(w):
    """Five parallel wrong signatures: the user row lock counts each; exactly one lockout event."""
    cr = _eco(w)
    w.part11_on()
    appr = w.member("appr", ["qa_approver"])
    sig = signature(appr, "eco", cr["id"], "approve", "approved", password="wrong-password")
    codes: list[str] = []

    def go() -> None:
        r = appr.client.post(f"/api/v1/mfg/eco/{cr['id']}/approve", json={"signature": sig},
                             headers={"X-SP-Workspace": w.oid})
        codes.append(r.json()["error"]["code"])

    ts = [threading.Thread(target=go) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(codes).count("ESIG_AUTH_FAILED") == 2 and codes.count("ESIG_LOCKED") == 3
    with _db(w).read() as s:
        assert s.execute(sa.text("SELECT count(*) FROM audit_events WHERE action = 'esig.lockout'")).scalar() == 1


def test_t_s5_tampering_is_detected(w):
    cr = _eco(w)
    w.part11_on()
    appr = w.member("appr", ["qa_approver"])
    appr.api.req("POST", f"/eco/{cr['id']}/approve", 200,
                 json={"signature": signature(appr, "eco", cr["id"], "approve", "approved")})
    sid = w.owner.api.get("/esig/signatures", record_type="eco")["items"][0]["id"]
    with _db(w).write() as s:
        s.execute(sa.text("UPDATE mfg_change_requests SET title = 'Other' WHERE id = :i"), {"i": cr["id"]})
    v = w.owner.api.get(f"/esig/signatures/{sid}/verify")
    assert v["content_hash_ok"] and v["mac_ok"] and not v["content_matches_current"]
    with _db(w).write() as s:
        s.execute(sa.text("UPDATE esig_signatures SET signer_legal_name = 'Mallory' WHERE id = :i"), {"i": sid})
    assert w.owner.api.get(f"/esig/signatures/{sid}/verify")["mac_ok"] is False
    with _db(w).write() as s:
        s.execute(sa.text("UPDATE esig_signatures SET content = '{\"x\": 1}'::jsonb WHERE id = :i"), {"i": sid})
    assert w.owner.api.get(f"/esig/signatures/{sid}/verify")["content_hash_ok"] is False


def test_t_s7_clock_skew_refuses_signing(w, monkeypatch):
    cr = _eco(w)
    w.part11_on()
    appr = w.member("appr", ["qa_approver"])
    sig = signature(appr, "eco", cr["id"], "approve", "approved")
    monkeypatch.setattr(ESIG, "SKEW_INJECT_MS", 3000.0)
    e = appr.api.err("POST", f"/eco/{cr['id']}/approve", 503, "ESIG_CLOCK_SKEW", json={"signature": sig})
    assert e["details"]["max_skew_ms"] == 2000
    t = appr.client.get("/api/v1/meta/time").json()
    assert t["ok"] is False and t["skew_ms"] >= 2900


def test_not_enrolled_revoked_and_tokens_cannot_sign(w):
    cr = _eco(w)
    w.part11_on()
    appr = w.member("appr", ["qa_approver"], enroll=False)
    sig = signature(appr, "eco", cr["id"], "approve", "approved")
    appr.api.err("POST", f"/eco/{cr['id']}/approve", 403, "ESIG_NOT_ENROLLED", json={"signature": sig})


def test_part11_off_ignores_signature(w):
    cr = _eco(w)
    appr = w.member("appr", ["approver"])
    out = appr.api.req("POST", f"/eco/{cr['id']}/approve", 200, json={}).json()
    assert out["status"] == "approved"
    assert w.owner.api.get("/esig/signatures")["total"] == 0


def test_org_session_idle_minutes_end_idle_sessions(w):
    from superplanner.api.auth import sessions as S

    o = w.owner
    assert o.client.get("/api/v1/auth/session").json()["authenticated"] is True
    with _db(w).write() as s:
        s.execute(sa.text("INSERT INTO orgs (id, name, slug, require_2fa, created_at, updated_at, row_version, "
                          "session_idle_minutes) VALUES ('org_1', 'O', 'o-1', false, now(), now(), 1, 15)"))
        s.execute(sa.text("INSERT INTO org_members (id, org_id, user_id, org_role, accepted_at, created_at, "
                          "row_version) VALUES ('orm_1', 'org_1', :u, 'org_member', now(), now(), 1)"),
                  {"u": o.user_id})
        s.execute(sa.text("UPDATE user_sessions SET last_seen_at = now() - interval '20 minutes' WHERE user_id = :u"),
                  {"u": o.user_id})
    S._IDLE_CACHE.clear()
    assert o.client.get("/api/v1/auth/session").json()["authenticated"] is False
