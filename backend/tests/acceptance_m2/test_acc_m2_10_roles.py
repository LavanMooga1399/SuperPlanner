"""Gate 2 #10: roles and isolation (M2-DESIGN 10). The 10.2 matrix holds for each role on one endpoint per
permission (permission is checked after authentication and before body validation, so an empty/invalid body
answers 403 for a role without the permission and something else - 4xx validation/404 - for one with it); members
see only workspaces they belong to; non-members and removed members get 404 on M2 paths; scheduling routes ignore
`X-SP-Workspace`; audit events of member actions carry the member as actor; `GET /me` reports roles/permissions;
single_user mode answers `MBR_UNAVAILABLE`.
"""

from __future__ import annotations

import pytest

from accm2_helpers import MEMBER_ENDPOINTS, V1, add_member, audit_events

OWNER = "owner@acc-m2.example.com"
ROLES = ("planner", "purchaser", "store_keeper", "approver", "viewer")
FAKE = "zzz_" + "0" * 32

# permission -> (method, path, body) of one representative unsafe endpoint (12.3)
PROBES = {
    "view": ("GET", "/locations", None),
    "master_edit": ("POST", "/locations", {}),
    "supplier_edit": ("POST", "/suppliers", {}),
    "inventory": ("POST", "/inventory/postings", {}),
    "pr_edit": ("POST", "/purchase-requests", {}),
    "pr_approve": ("POST", f"/purchase-requests/{FAKE}/approve", {"note": ""}),
    "po_edit": ("POST", "/purchase-orders", {}),
    "demand_edit": ("POST", "/demand-orders", {}),
    "wo_edit": ("POST", "/work-orders", {}),
    "mrp_run": ("POST", "/mrp/runs", {"allocation": "not-a-policy"}),
    "import": ("POST", "/imports", None),
    "owner": ("GET", "/members", None),
}
# 10.2 matrix
ALLOWED = {
    "view": {"owner", *ROLES},
    "master_edit": {"owner", "planner"},
    "supplier_edit": {"owner", "planner", "purchaser"},
    "inventory": {"owner", "store_keeper"},
    "pr_edit": {"owner", "planner", "purchaser"},
    "pr_approve": {"owner", "approver"},
    "po_edit": {"owner", "purchaser"},
    "demand_edit": {"owner", "planner"},
    "wo_edit": {"owner", "planner"},
    "mrp_run": {"owner", "planner"},
    "import": {"owner", "planner"},
    "owner": {"owner"},
}
PROBE_ENDPOINTS = ("GET /locations", "POST /locations", "POST /suppliers", "POST /inventory/postings",
                   "POST /purchase-requests", "POST /purchase-requests/{doc_id}/approve", "POST /purchase-orders",
                   "POST /demand-orders", "POST /work-orders", "POST /mrp/runs", "GET /members")


@pytest.fixture
def team(acc):
    owner = acc.user(OWNER)
    owner.need(*MEMBER_ENDPOINTS, *PROBE_ENDPOINTS)
    members = {r: add_member(acc, OWNER, f"{r}@acc-m2.example.com", [r]) for r in ROLES}
    return acc, owner, members


def _probe(api, perm: str):
    method, path, body = PROBES[perm]
    if perm == "import":
        return api.raw("POST", path, params={"filename": "x.csv", "sheet": "items"}, content=b"\x00\x01",
                       headers={"content-type": "application/octet-stream"})
    return api.raw(method, path, json=body) if body is not None else api.raw(method, path)


def test_permission_matrix_one_endpoint_per_permission(team):
    acc, owner, members = team
    who = {"owner": owner, **members}
    failures = []
    for perm in PROBES:
        for role, client in who.items():
            r = _probe(client, perm)
            if role in ALLOWED[perm]:
                if r.status_code == 403:
                    failures.append(f"{role} denied {perm}: {r.text[:200]}")
                elif r.status_code >= 500:
                    failures.append(f"{role} {perm}: {r.status_code}")
            else:
                if r.status_code != 403:
                    failures.append(f"{role} allowed {perm}: {r.status_code} {r.text[:200]}")
                    continue
                err = r.json()["error"]
                if err["code"] != "MFG_FORBIDDEN" or err["details"]["permission"] != perm or \
                        role in err["details"]["roles_allowed"]:
                    failures.append(f"{role} {perm}: bad 403 body {err}")
    assert not failures, "\n".join(failures)


def test_multiple_roles_are_a_union_and_me_reports_them(team):
    acc, owner, _ = team
    both = add_member(acc, OWNER, "both@acc-m2.example.com", ["store_keeper", "purchaser"])
    me = both.get("/me")
    assert me["workspace_owner_id"] == acc.uid(OWNER) and me["is_owner"] is False
    assert set(me["roles"]) == {"store_keeper", "purchaser"}
    assert {"inventory", "po_edit", "pr_edit", "supplier_edit", "view"} <= set(me["permissions"])
    assert "mrp_run" not in me["permissions"]
    assert _probe(both, "inventory").status_code != 403 and _probe(both, "po_edit").status_code != 403
    assert _probe(both, "mrp_run").status_code == 403
    own = owner.get("/me")
    assert own["is_owner"] is True and own["workspace_owner_id"] == acc.uid(OWNER)


def test_member_reads_owner_data_and_audit_actor_is_the_member(team):
    acc, owner, members = team
    loc = owner.post("/locations", {"code": "OWN-1", "name": "Owner stores", "kind": "stores"})
    planner = members["planner"]
    assert [x["id"] for x in planner.get("/locations")["items"]] == [loc["id"]]
    created = planner.post("/locations", {"code": "PLN-1", "name": "By planner", "kind": "line_side"})
    assert {x["code"] for x in owner.get("/locations")["items"]} == {"OWN-1", "PLN-1"}
    ev = [e for e in audit_events(acc.app, "mfg_location") if e.entity_id == created["id"]]
    assert ev and ev[0].action == "create" and ev[0].actor_id == acc.uid("planner@acc-m2.example.com")
    # the member's own workspace is separate and empty
    mine = acc.user("planner@acc-m2.example.com")
    assert mine.get("/locations")["items"] == []
    ws = mine.get("/workspaces")["items"]
    assert ws[0]["is_owner"] is True
    assert {w["owner_id"] for w in ws} == {acc.uid("planner@acc-m2.example.com"), acc.uid(OWNER)}
    assert next(w for w in ws if w["owner_id"] == acc.uid(OWNER))["roles"] == ["planner"]


def test_non_members_and_removed_members_get_404(team):
    acc, owner, members = team
    stranger = acc.user("stranger@acc-m2.example.com").in_workspace(acc.uid(OWNER))
    for path in ("/locations", "/me", "/inventory/balances", "/purchase-orders", "/mrp/runs", "/items",
                 "/shortages"):
        r = stranger.raw("GET", path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND", (path, r.status_code, r.text)
    r = stranger.raw("POST", "/locations", json={"code": "X", "name": "X", "kind": "stores"})
    assert r.status_code == 404
    junk = acc.user("stranger@acc-m2.example.com").in_workspace("not-a-user-id")
    assert junk.raw("GET", "/locations").status_code == 404
    # scheduling ignores the header: the stranger sees their own (empty) problems, not 404
    r = acc.clients["stranger@acc-m2.example.com"].get(f"{V1}/problems",
                                                       headers={"X-SP-Workspace": acc.uid(OWNER)})
    assert r.status_code == 200, r.text
    # remove the viewer -> 404 from then on; deactivated member too
    mem = {m["user"]["email"]: m for m in owner.get("/members")["items"]}
    v = mem["viewer@acc-m2.example.com"]
    owner.delete(f"/members/{v['id']}", v["row_version"])
    assert members["viewer"].raw("GET", "/locations").status_code == 404
    s = mem["store_keeper@acc-m2.example.com"]
    owner.put(f"/members/{s['id']}", {"roles": ["store_keeper"], "active": False}, s["row_version"])
    assert members["store_keeper"].raw("GET", "/locations").status_code == 404
    ev = [e.action for e in audit_events(acc.app) if e.entity_type.startswith("mfg_member")]
    assert {"member_add", "member_update", "member_remove"} <= set(ev), ev


def test_member_management_errors(team):
    acc, owner, members = team
    assert owner.raw("POST", "/members", json={"email": OWNER, "roles": ["viewer"]}).json()["error"]["code"] == \
        "MBR_SELF"
    r = owner.raw("POST", "/members", json={"email": "nobody@acc-m2.example.com", "roles": ["viewer"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "MBR_USER_NOT_FOUND"
    r = owner.raw("POST", "/members", json={"email": "planner@acc-m2.example.com", "roles": ["viewer"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "MFG_DUPLICATE_KEY"
    for roles in ([], ["root"], ["viewer", "viewer"]):
        r = owner.raw("POST", "/members", json={"email": "x@acc-m2.example.com", "roles": roles})
        assert r.status_code == 422, (roles, r.text)
    # a member cannot manage members of the owner's plant
    assert members["planner"].raw("POST", "/members", json={"email": "x@y.z", "roles": ["viewer"]}).status_code \
        == 403


def test_single_user_mode_has_no_members(api):
    api.need("GET /members")
    r = api.raw("GET", "/members")
    assert r.status_code == 422 and r.json()["error"]["code"] == "MBR_UNAVAILABLE", r.text
