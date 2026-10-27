"""Audit trail of manufacturing master data: every mutating mfg service records who (`actor_id`), what
(`entity_type` mfg_*, `entity_id`, `action`, `details`) and when (`created_at`) in the same transaction."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from apimfg_helpers import Mfg, acc_app, etag, sign_up
from superplanner.api.db.models import AuditEventRow
from superplanner.api.db.ownership import system_scope

SERVICES = Path(__file__).resolve().parents[2] / "superplanner" / "api" / "mfg" / "services"
OCTET = {"content-type": "application/octet-stream"}


def test_every_mutating_mfg_service_records_an_audit_event():
    """Static guard: each function that opens an mfg write transaction calls `audit(...)`."""
    missing: list[str] = []
    checked = 0
    for path in sorted(SERVICES.glob("*.py")):
        if path.name == "common.py":
            continue
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef):
                src = ast.unparse(node)
                if "write_tx(" in src:
                    checked += 1
                    if "audit(" not in src:
                        missing.append(f"{path.name}:{node.name}")
    assert checked >= 45, checked
    assert not missing, missing


def _audit(app, entity_type: str) -> list:
    t = AuditEventRow
    with system_scope(), app.state.ctx.db.read() as s:
        return list(s.execute(select(t.action, t.entity_id, t.actor_id, t.created_at, t.details)
                              .where(t.entity_type == entity_type).order_by(t.id)).all())


def test_audit_events_carry_actor_action_and_time(db_url):
    app = acc_app(db_url)
    with TestClient(app):
        c = sign_up(app, "auditor@example.com")
        uid = c.get("/api/v1/auth/session").json()["user"]["id"]
        m = Mfg(c)
        item = m.post("/items", {"part_number": "AUD-1", "description": "Audited", "make_buy": "buy"})
        m.put(f"/items/{item['id']}", {"part_number": "AUD-1", "description": "Audited 2", "make_buy": "buy"},
              item["row_version"])
        r = m.req("POST", "/imports", 201, params={"filename": "items.csv", "sheet": "items"},
                  content=b"part_number,make_buy\nAUD-2,buy\n", headers=OCTET).json()
        mapping = {"sheets": {s["name"]: s["suggested"] for s in r["sheets"]}, "options": {}}
        mapped = m.put(f"/imports/{r['id']}/mapping", mapping, r["row_version"])
        m.req("DELETE", f"/imports/{r['id']}", 204, headers=etag(mapped["row_version"]))
        items = _audit(app, "mfg_item")
        assert [(e.action, e.entity_id) for e in items] == [("create", item["id"]), ("update", item["id"])]
        assert all(e.actor_id == uid and e.created_at is not None for e in items)
        assert items[1].details == {"version": 2}
        imports = _audit(app, "mfg_import")
        assert [e.action for e in imports] == ["create", "map", "delete"]
        assert imports[1].details["targets"] == ["items"] and all(e.actor_id == uid for e in imports)
