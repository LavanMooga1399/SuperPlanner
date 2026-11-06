"""Organisations and cross-plant isolation (M5-DESIGN 3.4; T-O1)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apimfgm2_helpers import MFG, V1, Api, acc_app, sign_up


def test_t_o1_user_across_two_plants_isolated(db_url):
    app = acc_app(db_url, org_self_service=True)
    with TestClient(app):
        admin = sign_up(app, "admin@hbl.example")
        org = admin.post(f"{V1}/orgs", json={"name": "HBL", "slug": "hbl"}).json()
        a = admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "HYD", "name": "Hyderabad"}).json()
        b = admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "BLR", "name": "Bengaluru"}).json()
        assert a["my_roles"] == ["plant_admin"] and a["plant_owner_id"] != b["plant_owner_id"]
        pa, pb = Api(admin, a["plant_owner_id"]), Api(admin, b["plant_owner_id"])
        pa.item("HYD-ONLY")
        assert pb.get("/items")["total"] == 0 and pa.get("/items")["total"] == 1
        u = sign_up(app, "ravi@hbl.example")
        uid = u.get(f"{V1}/auth/session").json()["user"]["id"]
        r = admin.post(f"{V1}/orgs/{org['id']}/plants/{a['code']}/roles", json={"user_id": uid, "roles": ["viewer"]})
        assert r.status_code == 422                                          # must be an org member first
        admin.post(f"{V1}/orgs/{org['id']}/members", json={"email": "ravi@hbl.example"})
        for p in (a, b):
            assert admin.post(f"{V1}/orgs/{org['id']}/plants/{p['code']}/roles",
                              json={"user_id": uid, "roles": ["viewer"]}).status_code == 200
        ws = Api(u).get("/workspaces")["items"]
        assert {w["owner_id"] for w in ws} >= {a["plant_owner_id"], b["plant_owner_id"]}
        ua, ub = Api(u, a["plant_owner_id"]), Api(u, b["plant_owner_id"])
        assert [i["part_number"] for i in ua.get("/items")["items"]] == ["HYD-ONLY"]
        assert ub.get("/items")["items"] == []
        ua.err("POST", "/items", 403, "MFG_FORBIDDEN", json={"part_number": "X", "make_buy": "buy"})
        admin.post(f"{V1}/orgs/{org['id']}/plants/{b['code']}/roles", json={"user_id": uid, "roles": []})
        assert u.get(f"{MFG}/items", headers={"X-SP-Workspace": b["plant_owner_id"]}).status_code == 404
        # members see only their plants; non-members do not see the organisation; plants cannot sign in
        assert [p["code"] for p in Api(u).c.get(f"{V1}/orgs/{org['id']}/plants").json()["items"]] == ["HYD"]
        out = sign_up(app, "out@other.example")
        assert out.get(f"{V1}/orgs/{org['id']}").status_code == 404
        assert out.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "X", "name": "X"}).status_code == 404
        assert u.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "X", "name": "X"}).status_code == 403
        ov = u.get(f"{V1}/orgs/{org['id']}/overview").json()
        assert {p["plant"]["code"]: p["visible"] for p in ov["plants"]} == {"BLR": False, "HYD": True}
        hyd = next(p for p in ov["plants"] if p["plant"]["code"] == "HYD")
        blr = next(p for p in ov["plants"] if p["plant"]["code"] == "BLR")
        assert "otd" in hyd["kpis"] and hyd["late_demand"] == 0 and hyd["open_triggers"] == 0
        assert hyd["integration"]["status"] == "off" and blr["kpis"] == {} and blr["late_demand"] is None
        tok = admin.post(f"{V1}/tokens", json={"name": "p", "kind": "plant", "scopes": ["view"],
                                               "workspace_owner_id": a["plant_owner_id"]}).json()
        bt = TestClient(app)
        bt.headers["Authorization"] = f"Bearer {tok['token']}"
        assert bt.get(f"{MFG}/items").json()["total"] == 1                  # plant token: plant A only
        assert bt.get(f"{MFG}/items", headers={"X-SP-Workspace": b["plant_owner_id"]}).status_code == 404
        assert bt.get(f"{V1}/orgs").status_code == 403


def test_plant_codes_are_unique_across_plants(db_url):
    app = acc_app(db_url, org_self_service=True)
    with TestClient(app):
        admin = sign_up(app, "pc@hbl.example")
        org = admin.post(f"{V1}/orgs", json={"name": "HBL", "slug": "hbl-pc"}).json()
        a = admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "HYD", "name": "H"}).json()
        b = admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "BLR", "name": "B"}).json()
        body = {"enabled": True, "plant_code": "HBL1", "sor": {}}
        r = admin.put(f"{V1}/integration/settings", json=body,
                      headers={"If-Match": '"0"', "X-SP-Workspace": a["plant_owner_id"]})
        assert r.status_code == 200, r.text
        r = admin.put(f"{V1}/integration/settings", json={**body, "plant_code": "hbl1"},
                      headers={"If-Match": '"0"', "X-SP-Workspace": b["plant_owner_id"]})
        assert r.status_code == 409 and r.json()["error"]["code"] == "INT_PLANT_CODE_TAKEN"


def test_plant_tokens_need_a_plant_and_follow_their_creator(db_url):
    app = acc_app(db_url, org_self_service=True)
    with TestClient(app):
        admin = sign_up(app, "t1@hbl.example")
        org = admin.post(f"{V1}/orgs", json={"name": "HBL", "slug": "hbl-tok"}).json()
        a = admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "HYD", "name": "H"}).json()
        pa = a["plant_owner_id"]
        # a personal workspace is not a plant
        person = sign_up(app, "t2@hbl.example")
        pid = person.get(f"{V1}/auth/session").json()["user"]["id"]
        Api(person).post("/members", {"email": "t1@hbl.example", "roles": ["plant_admin"]})
        r = admin.post(f"{V1}/tokens", json={"name": "x", "kind": "plant", "scopes": ["view"],
                                             "workspace_owner_id": pid})
        assert r.status_code == 403
        tok = admin.post(f"{V1}/tokens", json={"name": "p", "kind": "plant", "scopes": ["view"],
                                               "workspace_owner_id": pa}).json()
        other = sign_up(app, "t3@hbl.example")
        oid = other.get(f"{V1}/auth/session").json()["user"]["id"]
        admin.post(f"{V1}/orgs/{org['id']}/members", json={"email": "t3@hbl.example", "org_role": "org_admin"})
        admin.post(f"{V1}/orgs/{org['id']}/plants/HYD/roles", json={"user_id": oid, "roles": ["plant_admin"]})
        assert tok["id"] in {x["id"] for x in other.get(f"{V1}/tokens").json()["items"]}   # co-admin sees it
        b = TestClient(app)
        b.headers["Authorization"] = f"Bearer {tok['token']}"
        assert b.get(f"{MFG}/items").status_code == 200
        uid = admin.get(f"{V1}/auth/session").json()["user"]["id"]
        r = other.post(f"{V1}/orgs/{org['id']}/plants/HYD/roles", json={"user_id": uid, "roles": ["viewer"]})
        assert r.status_code == 200, r.text
        assert b.get(f"{MFG}/items").status_code == 401                       # creator lost plant_admin
        assert other.delete(f"{V1}/tokens/{tok['id']}").status_code == 204    # any plant_admin can revoke


def test_orgs_manage_only_their_own_users(db_url):
    from superplanner.api.db.ownership import system_scope
    from superplanner.identity.service import org_requires_2fa

    app = acc_app(db_url, org_self_service=True)
    with TestClient(app):
        a = sign_up(app, "a@one.example")
        b = sign_up(app, "b@two.example")
        sign_up(app, "victim@x.example")
        oa = a.post(f"{V1}/orgs", json={"name": "One", "slug": "org-one"}).json()
        ob = b.post(f"{V1}/orgs", json={"name": "Two", "slug": "org-two", "require_2fa": True}).json()
        ma = a.post(f"{V1}/orgs/{oa['id']}/members", json={"email": "victim@x.example"}).json()
        mb = b.post(f"{V1}/orgs/{ob['id']}/members", json={"email": "victim@x.example"}).json()
        r = b.put(f"{V1}/orgs/{ob['id']}/members/{mb['id']}", json={"disabled": True})
        assert r.status_code == 403 and r.json()["error"]["code"] == "ORG_USER_NOT_MANAGED"
        vid = ma["user"]["id"]
        with system_scope(), app.state.ctx.db.read() as s:
            assert org_requires_2fa(s, vid) is False          # org Two does not manage the victim
        a.delete(f"{V1}/orgs/{oa['id']}/members/{ma['id']}")
        with system_scope(), app.state.ctx.db.read() as s:
            assert org_requires_2fa(s, vid) is True           # now its only organisation
        assert b.put(f"{V1}/orgs/{ob['id']}/members/{mb['id']}", json={"disabled": True}).status_code == 200


def test_operator_created_orgs_and_invitations(db_url):
    import io

    from superplanner import manage

    app = acc_app(db_url)                                       # ORG_SELF_SERVICE=false (default)
    with TestClient(app):
        admin = sign_up(app, "op-admin@hbl.example")
        r = admin.post(f"{V1}/orgs", json={"name": "HBL", "slug": "hbl-op"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "ORG_CREATE_DISABLED"
        out = io.StringIO()
        assert manage.main(["--url", db_url, "create-org", "--name", "HBL", "--slug", "hbl-op",
                            "--admin-email", "op-admin@hbl.example"], out=out, err=out) == 0, out.getvalue()
        org = admin.get(f"{V1}/orgs").json()["items"][0]
        other = sign_up(app, "elsewhere@x.example")
        assert manage.main(["--url", db_url, "create-org", "--name", "Other", "--slug", "other-op",
                            "--admin-email", "elsewhere@x.example"], out=io.StringIO(), err=io.StringIO()) == 0
        e = admin.post(f"{V1}/orgs/{org['id']}/members", json={"email": "elsewhere@x.example"})
        assert e.status_code == 409 and e.json()["error"]["code"] == "ORG_USER_IN_OTHER_ORG"
        new = sign_up(app, "new@hbl.example")
        m = admin.post(f"{V1}/orgs/{org['id']}/members", json={"email": "new@hbl.example"}).json()
        assert m["invited"] is True
        r = admin.put(f"{V1}/orgs/{org['id']}/members/{m['id']}", json={"disabled": True})
        assert r.status_code == 403 and r.json()["error"]["code"] == "ORG_USER_NOT_MANAGED"   # not accepted yet
        assert new.get(f"{V1}/orgs/{org['id']}").status_code == 404                         # no rights yet
        acc = new.post(f"{V1}/orgs/{org['id']}/accept")
        assert acc.status_code == 200 and acc.json()["invited"] is False
        assert new.get(f"{V1}/orgs/{org['id']}").status_code == 200
        assert admin.put(f"{V1}/orgs/{org['id']}/members/{m['id']}", json={"disabled": True}).status_code == 200
        assert other.post(f"{V1}/orgs/{org['id']}/accept").status_code == 404               # not invited
