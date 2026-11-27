"""S0 (M9-DESIGN 11): migration 0011 -> 0012 -> 0011 (ORM == schema), the frozen examples validate against the M9
contracts, roles and permissions of 9, the network workspace (O1) and its guards, every M9 list route answers."""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from superplanner import migrate
from superplanner.api.mfg.access import ROLE_PERMISSIONS, roles_allowed
from superplanner.api.mfg.db_models_m9 import M9_COLUMNS, M9_ID_PREFIXES, M9_TABLES
from superplanner.api.mfg.fixtures import build_example_m9

from m9_helpers import V1, app_for, make_world


def _tables(url: str) -> set[str]:
    eng = sa.create_engine(url)
    try:
        return set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _columns(url: str) -> set[tuple[str, str]]:
    eng = sa.create_engine(url)
    try:
        ins = sa.inspect(eng)
        return {(t, c["name"]) for t in ins.get_table_names() for c in ins.get_columns(t)}
    finally:
        eng.dispose()


def _diffs(url: str) -> list:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from superplanner.api.db import load_all_models

    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            return list(compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}),
                                         load_all_models()))
    finally:
        eng.dispose()


@pytest.mark.req("M9-S0-01")
def test_migration_0011_to_0012_and_back(empty_pg_db):
    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0011_m8")
    t11, c11 = _tables(url), _columns(url)
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:     # an existing plant and TO get the backfilled kinds
            migrate.ensure_local_user_conn(c)
            c.execute(sa.text("INSERT INTO mfg_transfer_orders (id, owner_id, number, direction, status, "
                              "source_owner_id, dest_owner_id, note, row_version, created_at, updated_at) VALUES "
                              "('tro_1', 'usr_local', 'TO-1', 'out', 'open', 'usr_local', 'usr_x', '', 1, now(), "
                              "now())"))
    finally:
        eng.dispose()
    migrate.run_alembic_upgrade(url)
    assert migrate.HEAD == "0012_m9" and migrate.schema_state(url) == "current"
    assert _tables(url) - t11 == set(M9_TABLES)
    assert {tc for tc in _columns(url) - c11 if tc[0] in t11} == set(M9_COLUMNS)
    assert _diffs(url) == []
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            assert c.execute(sa.text("SELECT source FROM mfg_transfer_orders")).scalar() == "manual"
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "0011_m8")
    assert _tables(url) == t11 and _columns(url) == c11


def test_examples_validate_and_are_current():
    built = build_example_m9.build()
    on_disk = json.loads(build_example_m9.OUT.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(built)), "run python -m superplanner.api.mfg.fixtures.build_example_m9"
    assert {"net_run", "net_transfer", "sop_cycle", "sop_scenario", "trade_report", "landed", "risk_row",
            "lot_content"} <= set(built)


def test_id_prefixes_match_entity_id():
    import re

    for prefix in M9_ID_PREFIXES.values():
        assert re.fullmatch(r"[a-z]{3}_", prefix), prefix
    assert len(set(M9_ID_PREFIXES.values())) == len(M9_ID_PREFIXES)


def test_roles_and_permissions():
    assert {"network_plan", "sop_edit"} <= ROLE_PERMISSIONS["planner"]
    assert {"network_edit", "network_publish", "sop_publish", "trade_admin"} <= ROLE_PERMISSIONS["plant_manager"]
    assert "network_publish" not in ROLE_PERMISSIONS["planner"]
    assert ROLE_PERMISSIONS["executive"] >= {"view"} and "sop_edit" not in ROLE_PERMISSIONS["executive"]
    assert "network_plan" not in ROLE_PERMISSIONS["auditor"]
    assert set(roles_allowed("trade_admin")) == {"owner", "plant_admin", "plant_manager"}


def test_network_workspace_guards_and_list_routes(db_url):
    app = app_for(db_url)
    with TestClient(app):
        w = make_world(app)
        a = w.admin
        r = a.post(f"{V1}/orgs/{w.org['id']}/network", json={})
        assert r.status_code == 409 and r.json()["error"]["code"] == "NET_EXISTS"
        kinds = {p["code"]: p["kind"] for p in a.get(f"{V1}/orgs/{w.org['id']}/plants").json()["items"]}
        assert kinds == {"QC": "plant", "US1": "plant", "DCUS": "dc", "NET": "network"}
        net, qc = w.net, w.api("QC")
        for path in ("/net/nodes", "/net/lanes", "/net/sourcing", "/net/runs", "/net/ramp-curves", "/sop/cycles",
                     "/sop/scenarios", "/trade/tariffs", "/trade/fx", "/trade/milestones", "/trade/country-risk",
                     "/trade/reports", "/trade/risk"):
            assert isinstance(net.get(path), dict), path
        # network routes need the network workspace; plant writes are refused inside it
        qc.err("GET", "/net/runs", 409, "NET_WORKSPACE_REQUIRED")
        qc.err("POST", "/sop/cycles", 409, "NET_WORKSPACE_REQUIRED", json={"period": "2026-12-01"})
        net.err("POST", "/locations", 409, "NET_WORKSPACE", json={"code": "X", "name": "X", "kind": "stores"})
        assert isinstance(qc.get("/trade/risk"), dict) and isinstance(qc.get("/mps/targets"), dict)
        # a DC with lines cannot exist: switching a plant with a line to dc is refused
        line_plant = w.api("US1")
        g = line_plant.post("/groups", {"code": "NA", "name": "Needle lines"})
        line_plant.post("/lines", {"group_id": g["id"], "code": "NA-01", "name": "Needle line 1"})
        r = a.put(f"{V1}/orgs/{w.org['id']}/plants/US1", json={"name": "US plant 1", "kind": "dc"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "NET_DC_HAS_LINES", r.text


def test_no_example_stub_is_left():
    from superplanner.api.mfg.services import m9_examples

    assert m9_examples.remaining() == []


def test_network_creation_is_one_transaction(db_url, monkeypatch):
    """Review m11: a failure while seeding leaves nothing behind; a retry then succeeds."""
    from superplanner.api.mfg.services import network as net_svc

    app = app_for(db_url)
    with TestClient(app):
        w = make_world(app, network=False)

        def boom(s):
            raise RuntimeError("seed failed")
        monkeypatch.setattr(net_svc, "seed_workspace", boom)
        with pytest.raises(RuntimeError):
            w.admin.post(f"{V1}/orgs/{w.org['id']}/network", json={})
        codes = {p["code"] for p in w.admin.get(f"{V1}/orgs/{w.org['id']}/plants").json()["items"]}
        assert "NET" not in codes
        monkeypatch.undo()
        r = w.admin.post(f"{V1}/orgs/{w.org['id']}/network", json={})
        assert r.status_code == 201, r.text
