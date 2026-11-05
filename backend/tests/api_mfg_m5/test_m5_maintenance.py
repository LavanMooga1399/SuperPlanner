"""Retention / archive (7), audit-verify endpoint and CLI (T-R1), convert-plant (T-O2), master-data publish,
org member disable, `/workspaces` organisation fields (M5-DESIGN 3.4, 7; 15.WP-S)."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import time
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi.testclient import TestClient

from apimfgm2_helpers import V1, Api, acc_app, make_app, sign_up
from superplanner import manage
from superplanner.api.db.ownership import system_scope


def test_archive_purge_retention_and_audit_verify(db_url, tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path))
    app = make_app(db_url, archive_dir=str(tmp_path))
    with TestClient(app) as c:
        api = Api(c)
        st = api.location("ST")
        it = api.item("A1")
        api.receive(it["id"], st["id"], 5)
        ctx = app.state.ctx
        from superplanner.api.mfg.db_models_m4 import MfgNotificationRow
        from superplanner.api.mfg.services import maintenance as M
        from superplanner.api.mfg.services.replan import notify

        old = datetime.now(UTC) - timedelta(days=400)
        with system_scope(), ctx.db.write() as s:
            from superplanner.api.db.ownership import owner_scope

            with owner_scope("usr_local"):
                notify(s, "TEST", "info", "old", "old", now=old)
                notify(s, "TEST", "info", "new", "new")
        with system_scope(), ctx.db.write() as s:
            r = M.retention(s, "usr_local", str(tmp_path))
        assert r["notifications"]["rows"] == 1 and r["notifications"]["purged"] == 1
        f = tmp_path / "usr_local" / "notifications" / r["notifications"]["files"][0]["file"]
        assert hashlib.sha256(f.read_bytes()).hexdigest() == r["notifications"]["files"][0]["sha256"]
        assert json.loads(gzip.decompress(f.read_bytes()).splitlines()[0])["title"] == "old"
        with system_scope(), ctx.db.read() as s:
            assert [n.title for n in s.execute(sa.select(MfgNotificationRow)).scalars()] == ["new"]
        # indefinite classes are exported, never purged
        out = io.StringIO()
        assert manage.main(["--url", db_url, "archive", "--before", "2100-01-01", "--classes", "ledger,audit",
                            "--purge"], out=out, err=out) == 0, out.getvalue()
        assert "ledger: 1 archived" in out.getvalue() and api.get("/inventory/postings")["total"] == 1
        manifests = list((tmp_path / "usr_local").glob("manifest-*.json"))
        assert len(manifests) == 6                         # 5 retention classes + the CLI run
        # audit verify: endpoint and CLI, before and after tampering
        v = c.get(f"{V1}/audit/verify").json()
        assert v["ok"] and v["checked"] > 0 and v["first_broken"] is None
        out = io.StringIO()
        assert manage.main(["--url", db_url, "audit-verify"], out=out, err=out) == 0
        eng = sa.create_engine(db_url)
        with eng.begin() as conn:
            rid = conn.execute(sa.text("SELECT id FROM audit_events WHERE owner_id = 'usr_local' AND chain_hash IS "
                                       "NOT NULL ORDER BY id LIMIT 1")).scalar()
            conn.execute(sa.text("UPDATE audit_events SET details = '{}' WHERE id = :i"), {"i": rid})
        eng.dispose()
        v = c.get(f"{V1}/audit/verify").json()
        assert not v["ok"] and v["first_broken"]["id"] == rid
        out = io.StringIO()
        assert manage.main(["--url", db_url, "audit-verify", "--owner", "usr_local"], out=out, err=out) == 1
        assert f"BROKEN at audit row {rid}" in out.getvalue()
        # trace-backfill CLI is idempotent
        out = io.StringIO()
        assert manage.main(["--url", db_url, "trace-backfill"], out=out, err=out) == 0
        assert "0 edge(s) added" in out.getvalue(), out.getvalue()


def _wait_publish(admin, org_id, pid):
    for _ in range(100):
        r = admin.get(f"{V1}/orgs/{org_id}/publish/{pid}").json()
        if r["status"] not in ("queued", "running"):
            return r
        time.sleep(0.1)
    raise AssertionError(r)


def test_t_o2_convert_plant_publish_and_member_disable(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        person = sign_up(app, "kavach@hbl.example")
        pid = person.get(f"{V1}/auth/session").json()["user"]["id"]
        mine = Api(person)
        mine.item("KV-1", description="first")
        mine.item("KV-2")
        mine.location("ST")
        helper = sign_up(app, "helper@hbl.example")
        mine.post("/members", {"email": "helper@hbl.example", "roles": ["viewer"]})
        assert Api(helper, pid).get("/items")["total"] == 2
        admin = sign_up(app, "admin@hbl.example")
        org = admin.post(f"{V1}/orgs", json={"name": "HBL", "slug": "hbl"}).json()
        out = io.StringIO()
        assert manage.main(["--url", db_url, "convert-plant", "--from-user", "kavach@hbl.example", "--org", "hbl",
                            "--code", "HYD"], out=out, err=out) == 0, out.getvalue()
        assert "mfg_items: 2" in out.getvalue()
        ws = Api(person).get("/workspaces")["items"]
        plant = next(w for w in ws if w.get("plant_code") == "HYD")
        assert plant["roles"] == ["plant_admin"] and plant["org"]["slug"] == "hbl"
        pa = Api(person, plant["owner_id"])
        assert pa.get("/items")["total"] == 2 and Api(person).get("/items")["total"] == 0
        assert helper.get(f"{V1}/mfg/items", headers={"X-SP-Workspace": pid}).status_code == 404
        assert Api(helper, plant["owner_id"]).get("/items")["total"] == 2           # members kept
        # publish items into a second plant (idempotent)
        b = admin.post(f"{V1}/orgs/{org['id']}/plants", json={"code": "BLR", "name": "Bengaluru"}).json()
        body = {"source_plant": "HYD", "target_plants": ["BLR"], "scope": "items", "part_number_prefix": "KV-"}
        r = _wait_publish(admin, org["id"], admin.post(f"{V1}/orgs/{org['id']}/publish", json=body).json()["id"])
        assert r["status"] == "completed" and r["results"][b["plant_owner_id"]]["ok"], r
        assert Api(admin, b["plant_owner_id"]).get("/items")["total"] == 2
        r2 = _wait_publish(admin, org["id"], admin.post(f"{V1}/orgs/{org['id']}/publish", json=body).json()["id"])
        assert r2["results"][b["plant_owner_id"]]["counts"]["items"]["unchanged"] == 2, r2   # idempotent
        # org admin disables / enables a member
        m = admin.post(f"{V1}/orgs/{org['id']}/members", json={"email": "helper@hbl.example"}).json()
        r = admin.put(f"{V1}/orgs/{org['id']}/members/{m['id']}", json={"disabled": True})
        assert r.status_code == 200 and r.json()["user"]["disabled"] is True
        assert helper.get(f"{V1}/mfg/items", headers={"X-SP-Workspace": plant["owner_id"]}).status_code == 401
        r = admin.put(f"{V1}/orgs/{org['id']}/members/{m['id']}", json={"disabled": False})
        assert r.json()["user"]["disabled"] is False
