"""Owner isolation of /api/v1/mfg (M1-DESIGN 9.5, 15.2 `test_mfg_isolation.py`), accounts mode."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from apimfg_helpers import MFG, Mfg, acc_app, err, etag, row_counts, sign_up, to_input
from superplanner.api.db.ownership import system_scope
from superplanner.api.mfg.db_models import MfgItemRow
from superplanner.mfg import model as mm


def _ids(m: Mfg) -> dict[str, str]:
    item = m.by_pn("SM-100")
    return {"item": item["id"], "bom": m.get(f"/items/{item['id']}/boms")["items"][0]["id"],
            "routing": m.get(f"/items/{item['id']}/routings")["items"][0]["id"],
            "group": m.get("/groups")["items"][0]["id"], "line": m.get("/lines")["items"][0]["id"],
            "template": m.get("/shift-templates")["items"][0]["id"],
            "assignment": m.get("/shift-assignments")["items"][0]["id"],
            "exception": m.get("/calendar-exceptions")["items"][0]["id"],
            "skill": m.get("/skills")["items"][0]["id"], "operator": m.get("/operators")["items"][0]["id"],
            "pool": m.get("/tool-pools")["items"][0]["id"]}


def test_two_users_are_isolated(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        a, b = Mfg(sign_up(app, "ana@example.com")), Mfg(sign_up(app, "ben@example.com"))
        a.load("small")
        b.load("small")                                    # same sample: no key or id collisions
        ia, ib = _ids(a), _ids(b)
        assert set(ia.values()).isdisjoint(ib.values())
        imp = a.req("POST", "/imports", 201, params={"filename": "x.csv", "sheet": "items"},
                    content=b"part_number,make_buy\nZ,buy\n", headers={"content-type": "application/octet-stream"})
        imp_id = imp.json()["id"]
        before = row_counts(app)
        gets = [f"/items/{ia['item']}", f"/items/{ia['item']}/explosion", f"/items/{ia['item']}/where-used",
                f"/items/{ia['item']}/boms", f"/items/{ia['item']}/routings", f"/boms/{ia['bom']}",
                f"/routings/{ia['routing']}", f"/routings/{ia['routing']}/time-preview", f"/groups/{ia['group']}",
                f"/lines/{ia['line']}", f"/shift-templates/{ia['template']}", f"/operators/{ia['operator']}",
                f"/imports/{imp_id}"]
        for path in gets:
            fake = path
            for v in ia.values():
                fake = fake.replace(v, v[:4] + uuid.uuid4().hex)
            fake = fake.replace(imp_id, "imp_" + uuid.uuid4().hex)
            rb, ru = b.req("GET", path), b.req("GET", fake)
            err(rb, 404, "NOT_FOUND")
            err(ru, 404, "NOT_FOUND")
        err(b.req("GET", f"/lines/{ia['line']}/windows", params={"from": "2026-11-02", "to": "2026-11-03"}), 404,
            "NOT_FOUND")
        for path in (f"/items/{ia['item']}", f"/boms/{ia['bom']}", f"/skills/{ia['skill']}",
                     f"/tool-pools/{ia['pool']}", f"/shift-assignments/{ia['assignment']}",
                     f"/calendar-exceptions/{ia['exception']}"):
            err(b.req("DELETE", path), 404, "NOT_FOUND")            # 404 before 428
            err(b.req("DELETE", path, headers=etag(1)), 404, "NOT_FOUND")
        for path in (f"/boms/{ia['bom']}/release", f"/boms/{ia['bom']}/copy", f"/routings/{ia['routing']}/obsolete",
                     f"/imports/{imp_id}/commit"):
            err(b.req("POST", path, json={}), 404, "NOT_FOUND")
        err(b.req("DELETE", f"/imports/{imp_id}"), 404, "NOT_FOUND")
        # lists exclude A's rows
        assert {i["id"] for i in b.get("/items", params={"limit": 200})["items"]}.isdisjoint(ia.values())
        assert {g["id"] for g in b.get("/groups")["items"]}.isdisjoint(ia.values())
        # body references to A's ids -> 422 MFG_UNKNOWN_REFERENCE, never a cross-owner link
        e = err(b.req("POST", "/boms", json={"item_id": ia["item"]}), 422, "MFG_UNKNOWN_REFERENCE")
        assert e["details"]["loc"] == ["body", "item_id"]
        mine = b.by_pn("SM-100")
        bom_b = b.post("/boms", {"item_id": mine["id"]})
        body = {**to_input(mm.BomInput, bom_b), "lines": [{"find_number": "10", "child_item_id": ia["item"],
                                                           "qty_per": 1}]}
        err(b.req("PUT", f"/boms/{bom_b['id']}", json=body, headers=etag(1)), 422, "MFG_UNKNOWN_REFERENCE")
        g = b.get("/groups")["items"][0]
        err(b.req("POST", "/lines", json={"code": "NEW", "name": "n", "group_id": ia["group"]}), 422,
            "MFG_UNKNOWN_REFERENCE")
        err(b.req("POST", "/shift-assignments", json={"shift_template_id": ia["template"], "target_type": "group",
                                                      "group_id": g["id"], "effective_from": "2026-01-01"}), 422,
            "MFG_UNKNOWN_REFERENCE")
        # where-used of B's item never shows A's parents
        child_b = b.by_pn("SM-BPCB-100")
        wu = b.get(f"/items/{child_b['id']}/where-used", params={"include": "all"})
        assert {r["item_id"] for r in wu["rows"]} == {mine["id"]}
        # B's reset and B's sample replace leave A's rows untouched
        a_items = len(a.get("/items", params={"limit": 200})["items"])
        b.load("small", replace=True)
        b.post("/reset", {"confirm": "DELETE ALL MANUFACTURING DATA"}, status=200)
        assert len(a.get("/items", params={"limit": 200})["items"]) == a_items
        assert a.get(f"/imports/{imp_id}")["id"] == imp_id
        with system_scope(), app.state.ctx.db.read() as s:
            from sqlalchemy import func, select

            assert s.execute(select(func.count()).select_from(MfgItemRow)).scalar() == a_items
        assert row_counts(app)["mfg_items"] < before["mfg_items"]
        assert MFG


def test_accounts_mode_csrf_on_mfg_unsafe_routes(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        c = sign_up(app, "csrf@example.com")
        token = c.headers.pop("X-CSRF-Token")
        r = c.post(f"{MFG}/items", json={"part_number": "X", "make_buy": "buy"})
        err(r, 403, "CSRF_FAILED")
        r = c.post(f"{MFG}/imports", params={"filename": "x.csv"}, content=b"a\n1\n",
                   headers={"content-type": "application/octet-stream"})
        err(r, 403, "CSRF_FAILED")
        c.headers["X-CSRF-Token"] = token
        assert c.post(f"{MFG}/items", json={"part_number": "X", "make_buy": "buy"}).status_code == 201
        anon = TestClient(app)
        err(anon.get(f"{MFG}/summary"), 401, "AUTH_REQUIRED")
