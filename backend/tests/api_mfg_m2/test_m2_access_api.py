"""B1 (M2-DESIGN 10): members, `/me`, `/workspaces`, the role x permission matrix on one endpoint per permission,
workspace isolation (non-member 404), audit actor = the member, single_user (C16), self-approval."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from apimfgm2_helpers import Api, acc_app, im, sign_up
from superplanner.api.db.models import AuditEventRow
from superplanner.api.db.ownership import system_scope

ROLES = ("planner", "purchaser", "store_keeper", "approver", "viewer")
#: permission -> (method, path, body) that passes the permission check and fails later with 4xx != 403
PROBES = {
    "view": ("GET", "/locations", None),
    "master_edit": ("POST", "/locations", {"code": "X1", "name": "X", "kind": "stores"}),
    "supplier_edit": ("POST", "/suppliers", {"code": "SX", "name": "S"}),
    "inventory": ("POST", "/inventory/postings", {"type": "receipt_misc", "lines": [
        {"item_id": "itm_" + "0" * 32, "location_id": "loc_" + "0" * 32, "qty": 1}]}),
    "pr_edit": ("POST", "/purchase-requests", {"lines": [{"item_id": "itm_" + "0" * 32,
                                                          "schedules": [{"requested_date": "2026-12-01", "qty": 1}]}]}),
    "pr_approve": ("POST", "/purchase-requests/pdc_" + "0" * 32 + "/approve", {}),
    "po_edit": ("POST", "/purchase-orders/pdc_" + "0" * 32 + "/issue", {}),
    "demand_edit": ("POST", "/demand-orders/dmo_" + "0" * 32 + "/open", {}),
    "wo_edit": ("POST", "/work-orders/wko_" + "0" * 32 + "/close", {}),
    "mrp_run": ("PUT", "/mrp/runs/mrr_" + "0" * 32, {"label": "x"}),
    "import": ("DELETE", "/imports/imp_" + "0" * 32, None),
    "owner": ("GET", "/members", None),
}
ALLOWED = {
    "view": set(ROLES), "master_edit": {"planner"}, "supplier_edit": {"planner", "purchaser"},
    "inventory": {"store_keeper"}, "pr_edit": {"planner", "purchaser"}, "pr_approve": {"approver"},
    "po_edit": {"purchaser"}, "demand_edit": {"planner"}, "wo_edit": {"planner"}, "mrp_run": {"planner"},
    "import": {"planner"}, "owner": set(),
}


def test_members_roles_matrix_isolation_and_audit_actor(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        owner_c = sign_up(app, "owner@example.com")
        owner = Api(owner_c)
        oid = owner_c.get("/api/v1/auth/session").json()["user"]["id"]
        owner.location("ST")
        users = {}
        for role in ROLES:
            c = sign_up(app, f"{role}@example.com")
            users[role] = (Api(c, oid), c.get("/api/v1/auth/session").json()["user"]["id"])
            m = owner.post("/members", {"email": f"{role}@example.com", "roles": [role]})
            assert m["roles"] == [role] and m["user"]["email"] == f"{role}@example.com"
        owner.err("POST", "/members", 409, "MFG_DUPLICATE_KEY", json={"email": "viewer@example.com",
                                                                        "roles": ["viewer"]})
        owner.err("POST", "/members", 422, "MBR_USER_NOT_FOUND", json={"email": "nobody@example.com",
                                                                         "roles": ["viewer"]})
        owner.err("POST", "/members", 422, "MBR_SELF", json={"email": "owner@example.com", "roles": ["viewer"]})
        assert len(owner.get("/members")["items"]) == 5
        # /me and /workspaces
        me = users["store_keeper"][0].get("/me")
        assert me["workspace_owner_id"] == oid and not me["is_owner"] and me["roles"] == ["store_keeper"]
        assert me["permissions"] == ["view", "inventory"]
        ws = users["viewer"][0].at(None).get("/workspaces")["items"]
        assert [w["is_owner"] for w in ws] == [True, False] and ws[1]["owner_id"] == oid
        # a member sees the owner's data
        assert [x["code"] for x in users["viewer"][0].get("/locations")["items"]] == ["ST"]
        # role matrix: one endpoint per permission
        for perm, (method, path, body) in PROBES.items():
            for role in ROLES:
                api = users[role][0]
                r = api.req(method, path, json=body) if body is not None else api.req(method, path)
                if role in ALLOWED[perm]:
                    assert r.status_code != 403, (perm, role, r.text)
                else:
                    assert r.status_code == 403, (perm, role, r.status_code, r.text)
                    e = r.json()["error"]
                    assert e["code"] == "MFG_FORBIDDEN" and e["details"]["permission"] == perm
        # viewer: 403 before body validation
        users["viewer"][0].err("POST", "/locations", 403, "MFG_FORBIDDEN", json={"bad": 1})
        # audit actor is the member
        planner, planner_id = users["planner"]
        loc = planner.location("PL")
        with system_scope(), app.state.ctx.db.read() as s:
            actor = s.execute(select(AuditEventRow.actor_id).where(AuditEventRow.entity_type == "mfg_location",
                                                                   AuditEventRow.entity_id == loc["id"])).scalar_one()
        assert actor == planner_id
        # self-approval refused for a member; approval by an approver works
        it = owner.item("C-1")
        pr = planner.post("/purchase-requests", {"lines": [{"item_id": it["id"], "schedules": [
            {"requested_date": "2026-12-01", "qty": 1}]}]})
        pr = planner.post(f"/purchase-requests/{pr['id']}/submit", version=pr["row_version"], status=200)
        both = sign_up(app, "both@example.com")
        owner.post("/members", {"email": "both@example.com", "roles": ["planner", "approver"]})
        b = Api(both, oid)
        pr2 = b.post("/purchase-requests", {"lines": [{"item_id": it["id"], "schedules": [
            {"requested_date": "2026-12-01", "qty": 1}]}]})
        pr2 = b.post(f"/purchase-requests/{pr2['id']}/submit", version=pr2["row_version"], status=200)
        b.err("POST", f"/purchase-requests/{pr2['id']}/approve", 409, "PUR_SELF_APPROVAL", json={},
              headers=im(pr2["row_version"]))
        ok = users["approver"][0].post(f"/purchase-requests/{pr['id']}/approve", version=pr["row_version"],
                                       status=200)
        assert ok["status"] == "approved" and ok["approved_by"]["id"] == users["approver"][1]
        # non-member / removed member -> 404 for every mfg path; the own workspace still works
        stranger = Api(sign_up(app, "stranger@example.com"), oid)
        stranger.err("GET", "/locations", 404, "NOT_FOUND")
        stranger.err("GET", "/items", 404, "NOT_FOUND")
        assert stranger.at(None).get("/locations")["items"] == []
        mem = next(m for m in owner.get("/members")["items"] if m["user"]["email"] == "viewer@example.com")
        owner.put(f"/members/{mem['id']}", {"roles": ["viewer"], "active": False}, mem["row_version"])
        users["viewer"][0].err("GET", "/locations", 404, "NOT_FOUND")
        owner.delete(f"/members/{mem['id']}", mem["row_version"] + 1)
        # scheduling/finance ignore the header
        r = owner_c.get("/api/v1/problems", headers={"X-SP-Workspace": "usr_" + "0" * 32})
        assert r.status_code == 200


def test_single_user_members_unavailable_and_foreign_header_404(api: Api):
    api.err("GET", "/members", 422, "MBR_UNAVAILABLE")
    api.at("usr_" + "1" * 32).err("GET", "/locations", 404, "NOT_FOUND")
    assert api.get("/me")["is_owner"]
