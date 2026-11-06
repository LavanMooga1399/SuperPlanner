"""Audit chain and export (M5-DESIGN 7; T-R1)."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, make_app
from superplanner.api import audit_chain
from superplanner.api.db.ownership import system_scope


def test_t_r1_chain_detects_a_changed_row_and_export(db_url):
    app = make_app(db_url)
    with TestClient(app) as c:
        api = Api(c)
        for k in range(3):
            api.item(f"A{k}")
        ctx = app.state.ctx
        with system_scope(), ctx.db.read() as s:
            v = audit_chain.verify(s, "usr_local")
        assert v["ok"] and v["checked"] >= 3
        ev = c.get(f"{V1}/audit/events", params={"entity_type": "mfg_item"}).json()
        assert ev["total"] >= 3 and all(e["chain_hash"] for e in ev["items"])
        exp = c.get(f"{V1}/audit/export", params={"format": "jsonl"})
        assert exp.status_code == 200 and len(exp.text.strip().splitlines()) >= 3
        csv = c.get(f"{V1}/audit/export", params={"format": "csv"})
        assert csv.text.splitlines()[0].startswith("id,")
        eng = sa.create_engine(db_url)
        with eng.begin() as conn:
            rid = conn.execute(sa.text("SELECT id FROM audit_events WHERE owner_id = 'usr_local' AND chain_hash IS "
                                       "NOT NULL ORDER BY id OFFSET 1 LIMIT 1")).scalar()
            conn.execute(sa.text("UPDATE audit_events SET action = 'tampered' WHERE id = :i"), {"i": rid})
        eng.dispose()
        with system_scope(), ctx.db.read() as s:
            v = audit_chain.verify(s, "usr_local")
        assert not v["ok"] and v["first_broken_id"] == rid


def test_org_wide_audit_for_org_admins(db_url):
    from apimfgm2_helpers import acc_app, sign_up

    app = acc_app(db_url)
    with TestClient(app):
        admin = sign_up(app, "admin@o.example")
        org = admin.post(f"{V1}/orgs", json={"name": "Org O", "slug": "org-o"}).json()
        a = admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "A", "name": "A"}).json()
        b = admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "B", "name": "B"}).json()
        Api(admin, a["plant_owner_id"]).item("IN-A")
        Api(admin, b["plant_owner_id"]).item("IN-B")
        ev = admin.get(f"{V1}/audit/events", params={"org_id": org["id"], "entity_type": "mfg_item"}).json()
        assert {e["owner_id"] for e in ev["items"]} == {a["plant_owner_id"], b["plant_owner_id"]}
        v = admin.get(f"{V1}/audit/verify", params={"org_id": org["id"]}).json()
        assert v["ok"] and len(v["plants"]) == 2
        exp = admin.get(f"{V1}/audit/export", params={"org_id": org["id"]})
        assert exp.status_code == 200 and "IN-B" in exp.text or "mfg_item" in exp.text
        m = sign_up(app, "m@o.example")
        admin.post(f"{V1}/orgs/{org['id']}/members", json={"email": "m@o.example"})
        assert m.get(f"{V1}/audit/events", params={"org_id": org["id"]}).status_code == 403
        assert sign_up(app, "x@o.example").get(f"{V1}/audit/events", params={"org_id": org["id"]}).status_code == 404


def test_keyed_chain_detects_recompute_and_truncation(db_url):
    from superplanner.identity import crypto

    app = make_app(db_url, secrets_keys=[crypto.new_key()])
    with TestClient(app) as c:
        api = Api(c)
        for k in range(4):
            api.item(f"K{k}")
        ctx = app.state.ctx
        with system_scope(), ctx.db.read() as s:
            v = audit_chain.verify(s, "usr_local")
        assert v["ok"] and v["checked"] >= 4
        eng = sa.create_engine(db_url)
        with eng.begin() as conn:
            rows = conn.execute(sa.text("SELECT id, chain_hash FROM audit_events WHERE owner_id = 'usr_local' "
                                        "ORDER BY id")).all()
            assert all(h.startswith("k1:") for _i, h in rows)
        # recompute with the plain hash after a change (no key): detected
        with system_scope(), ctx.db.write() as s:
            from superplanner.api.db.models import AuditEventRow

            r = s.get(AuditEventRow, rows[1][0])
            r.action = "tampered"
            r.chain_hash = audit_chain._hash(rows[0][1], r)
            prev = r.chain_hash
            for rid, _h in rows[2:]:
                x = s.get(AuditEventRow, rid)
                x.chain_hash = audit_chain._hash(prev, x)
                prev = x.chain_hash
        with system_scope(), ctx.db.read() as s:
            v = audit_chain.verify(s, "usr_local")
        assert not v["ok"] and v["first_broken_id"] == rows[1][0]
    app = make_app(db_url, secrets_keys=[crypto.new_key()])
    with TestClient(app) as c:
        Api(c).item("T1")
        Api(c).item("T2")
        eng = sa.create_engine(db_url)
        with eng.begin() as conn:
            conn.execute(sa.text("DELETE FROM audit_events WHERE owner_id = 'usr_local'"))
            conn.execute(sa.text("UPDATE audit_chain_heads SET mac = mac"))
        with system_scope(), app.state.ctx.db.write() as s:
            pass
        Api(c).item("T3")
        Api(c).item("T4")
        with eng.begin() as conn:                    # drop the newest row (truncation)
            conn.execute(sa.text("DELETE FROM audit_events WHERE id = (SELECT max(id) FROM audit_events "
                                 "WHERE owner_id = 'usr_local')"))
        eng.dispose()
        with system_scope(), app.state.ctx.db.read() as s:
            v = audit_chain.verify(s, "usr_local")
        assert not v["ok"] and "truncated" in v["reason"]
