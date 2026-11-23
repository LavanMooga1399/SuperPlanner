"""S0 (M7-DESIGN 11): migration 0009 -> 0010 -> 0009 (held lots keep their hold as a `manual` hold row), the frozen
examples validate against `esig.model` / `qa.model`, roles and permissions of 9.1, every M7 GET route answers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import sqlalchemy as sa

from superplanner import migrate
from superplanner.api.mfg.access import ROLE_PERMISSIONS
from superplanner.api.mfg.db_models_m7 import M7_COLUMNS, M7_TABLES
from superplanner.qa.fixtures import build_example

NOW = datetime(2026, 11, 23, 8, 0, tzinfo=UTC)


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


def _ins(c: sa.Connection, table: str, **vals: object) -> None:
    """INSERT with every other NOT NULL column filled by a neutral value of its type (literal schema, no ORM)."""
    cols = c.execute(sa.text("SELECT column_name, data_type, is_nullable, column_default FROM "
                             "information_schema.columns WHERE table_name = :t"), {"t": table}).all()
    neutral = {"integer": 0, "bigint": 0, "double precision": 0.0, "boolean": False, "jsonb": "{}", "date": "2026-11-02",
               "timestamp with time zone": NOW}
    row = dict(vals)
    row.setdefault("owner_id", "usr_local")
    for name, typ, nullable, default in cols:
        if name not in row and nullable == "NO" and default is None:
            row[name] = neutral.get(typ, "")
    c.execute(sa.text(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})"),
              {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()})


def test_migration_0009_to_0010_and_back(empty_pg_db):
    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0009_ux")
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            migrate.ensure_local_user_conn(c)
            _ins(c, "mfg_items", id="itm_1", part_number="P", revision="A", uom="EA", make_buy="buy",
                 lot_rule="lot_for_lot", lot_controlled=True, active=True, attributes={})
            _ins(c, "mfg_lots", id="lot_1", item_id="itm_1", lot_code="L1", hold=True)
            _ins(c, "mfg_lots", id="lot_2", item_id="itm_1", lot_code="L2", hold=False)
    finally:
        eng.dispose()
    t9, c9 = _tables(url), _columns(url)
    migrate.run_alembic_upgrade(url)
    assert migrate.HEAD == "0010_m7" and migrate.schema_state(url) == "current"
    assert _tables(url) - t9 == set(M7_TABLES)
    assert _columns(url) - c9 >= set(M7_COLUMNS)
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            holds = c.execute(sa.text("SELECT lot_id, source, released_at FROM mfg_lot_holds")).all()
            assert holds == [("lot_1", "manual", None)]
            assert c.execute(sa.text("SELECT column_default FROM information_schema.columns WHERE table_name = "
                                     "'mfg_plant' AND column_name = 'part11_mode'")).scalar() is None
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "0009_ux")
    assert _tables(url) == t9 and _columns(url) == c9


def test_examples_validate_and_are_current():
    built = build_example.build()
    on_disk = json.loads(build_example.OUT.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(built)), "run python -m superplanner.qa.fixtures.build_example"
    assert {"signature_input", "preview", "pending", "inspection_lot", "ncr", "capa", "complaint", "field_action",
            "equipment", "calibration", "package", "audit_record"} <= set(built)


def test_roles_and_permissions():
    qa = {"qa_inspect", "qa_decide", "qa_plan_edit", "ncr_edit", "ncr_approve", "capa_edit", "complaint_edit",
          "field_action_edit", "capa_approve", "equipment_edit", "audit_view", "esig_policy_edit"}
    assert qa <= ROLE_PERMISSIONS["owner"] and qa <= ROLE_PERMISSIONS["plant_admin"]
    assert "capa_approve" in ROLE_PERMISSIONS["qa_approver"] and "capa_approve" not in ROLE_PERMISSIONS["qa_engineer"]
    assert ROLE_PERMISSIONS["metrology"] >= {"equipment_edit", "view"} and "qa_decide" not in ROLE_PERMISSIONS[
        "metrology"]
    assert "qa_inspect" in ROLE_PERMISSIONS["operator"] and "qa_decide" not in ROLE_PERMISSIONS["operator"]
    assert "esig_policy_edit" in ROLE_PERMISSIONS["qa_approver"] and "audit_view" in ROLE_PERMISSIONS["qa_engineer"]


def test_every_m7_list_route_answers(api):
    for path in ("/qa/schemes", "/qa/plans", "/qa/inspection-lots", "/qa/holds", "/qa/ncrs", "/qa/capas",
                 "/qa/complaints", "/qa/field-actions", "/qa/equipment", "/esig/policies", "/plant/part11",
                 "/plant/qa-settings", "/part11/exports"):
        body = api.get(path)
        assert isinstance(body, dict), path
    assert api.c.get("/api/v1/meta/time").status_code == 200
    assert api.c.get("/api/v1/auth/esig/status").status_code == 200
