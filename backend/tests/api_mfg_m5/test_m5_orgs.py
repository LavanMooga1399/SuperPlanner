"""Organisations and cross-plant isolation (M5-DESIGN 3.4; T-O1)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apimfgm2_helpers import MFG, V1, Api, acc_app, sign_up


def test_t_o1_user_across_two_plants_isolated(db_url):
    app = acc_app(db_url)
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
    app = acc_app(db_url)
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
    app = acc_app(db_url)
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
