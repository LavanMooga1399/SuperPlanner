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
