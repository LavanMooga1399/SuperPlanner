"""S0 (M8-DESIGN 13): migration 0010 -> 0011 -> 0010 (ORM == schema), the frozen examples validate against the
M8 contracts, roles and permissions of 11, every M8 list route answers."""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from superplanner import migrate
from superplanner.api.mfg.access import ROLE_PERMISSIONS, roles_allowed
from superplanner.api.mfg.db_models_m8 import M8_COLUMNS, M8_ID_PREFIXES, M8_TABLES
from superplanner.api.mfg.fixtures import build_example


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


@pytest.mark.req("M8-S0-01")
def test_migration_0010_to_0011_and_back(empty_pg_db):
    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0010_m7")
    t10, c10 = _tables(url), _columns(url)
    migrate.run_alembic_upgrade(url)
    assert migrate.HEAD == "0011_m8" and migrate.schema_state(url) == "current"
    assert _tables(url) - t10 == set(M8_TABLES)
    assert {tc for tc in _columns(url) - c10 if tc[0] in t10} == set(M8_COLUMNS)
    assert _diffs(url) == []
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            width = c.execute(sa.text("SELECT character_maximum_length FROM information_schema.columns WHERE "
                                      "table_name = 'mfg_work_orders' AND column_name = 'kind'")).scalar()
            assert width == 12
    finally:
        eng.dispose()
    eng = sa.create_engine(url)       # review 11: a sterility hold survives the downgrade as a manual hold
    try:
        with eng.begin() as c:
            migrate.ensure_local_user_conn(c)
            c.execute(sa.text("INSERT INTO mfg_items (id, owner_id, part_number, revision, description, uom, make_buy, "
                              "receiving_days, lot_rule, min_order_qty, order_multiple, safety_stock, serialized, "
                              "handling_note, attributes, active, lot_controlled, issue_method, row_version, "
                              "created_at, updated_at) VALUES ('itm_1', 'usr_local', 'P', 'A', '', 'EA', 'make', 0, "
                              "'lot_for_lot', 0, 0, 0, false, '', '{}', true, true, 'manual', 1, now(), now())"))
            c.execute(sa.text("INSERT INTO mfg_lots (id, owner_id, item_id, lot_code, supplier_lot, hold, note, row_version, "
                              "created_at, updated_at) VALUES ('lot_1', 'usr_local', 'itm_1', 'L1', '', true, '', 1, now(), "
                              "now())"))
            c.execute(sa.text("INSERT INTO mfg_lot_holds (id, owner_id, lot_id, item_id, source, reason, placed_by, "
                              "placed_at, release_note, row_version, created_at, updated_at) VALUES ('hld_1', "
                              "'usr_local', 'lot_1', 'itm_1', 'sterility', 'Awaiting sterilisation', 'usr_local', "
                              "now(), '', 1, now(), now())"))
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "0010_m7")
    assert _tables(url) == t10 and _columns(url) == c10
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            assert c.execute(sa.text("SELECT source FROM mfg_lot_holds")).scalar() == "manual"
    finally:
        eng.dispose()


def test_examples_validate_and_are_current():
    built = build_example.build()
    on_disk = json.loads(build_example.OUT.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(built)), "run python -m superplanner.api.mfg.fixtures.build_example"
    assert {"forecast_run", "forecast_version", "forecast_override", "ss_line", "rate_run", "rate_block",
            "ster_load", "kanban_loop", "baseline_diff", "sap_settings"} <= set(built)


def test_id_prefixes_match_entity_id():
    import re

    for prefix in M8_ID_PREFIXES.values():
        assert re.fullmatch(r"[a-z]{3}_", prefix), prefix


def test_roles_and_permissions():
    planner = {"forecast_edit", "inventory_policy_edit", "rate_plan", "ster_plan", "kanban_edit"}
    assert planner <= ROLE_PERMISSIONS["planner"] and planner <= ROLE_PERMISSIONS["plant_manager"]
    assert {"forecast_approve", "inventory_policy_approve"} <= ROLE_PERMISSIONS["plant_manager"]
    assert "forecast_approve" not in ROLE_PERMISSIONS["planner"]
    assert {"ster_release", "validation_view"} <= ROLE_PERMISSIONS["qa_approver"]
    assert "kanban_scan" in ROLE_PERMISSIONS["operator"] and "kanban_edit" not in ROLE_PERMISSIONS["operator"]
    assert "validation_view" in ROLE_PERMISSIONS["auditor"] and "master_edit" not in ROLE_PERMISSIONS["auditor"]
    assert set(roles_allowed("ster_release")) == {"owner", "plant_admin", "qa_approver"}


def test_every_m8_list_route_answers(api):
    for path in ("/forecast/history", "/forecast/runs", "/forecast/versions", "/forecast/accuracy", "/invopt/runs",
                 "/changeover-matrix", "/rate/runs", "/ster/loads", "/kanban/loops", "/plant/planning-settings",
                 "/validation/baselines", "/validation/trace-matrix", "/integration/sap-settings"):
        body = api.get(path)
        assert isinstance(body, dict), path


def test_no_example_stub_is_left():
    from superplanner.api.mfg.services import m8_examples

    assert m8_examples.remaining() == []
