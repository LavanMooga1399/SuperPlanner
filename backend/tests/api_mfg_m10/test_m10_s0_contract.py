"""S0 (M10-DESIGN 12): migration 0012 -> 0013 -> 0012 (ORM == schema), the frozen examples validate against the M10
contracts, roles and permissions of 10, signature policies of 3, every M10 list route answers."""

from __future__ import annotations

import json
import re

import pytest
import sqlalchemy as sa

from superplanner import migrate
from superplanner.api.mfg.access import ROLE_PERMISSIONS, roles_allowed
from superplanner.api.mfg.db_models_m10 import M10_COLUMNS, M10_ID_PREFIXES, M10_TABLES
from superplanner.api.mfg.fixtures import build_example_m10
from superplanner.esig import policy as POL


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


@pytest.mark.req("M10-S0-01")
def test_migration_0012_to_0013_and_back(empty_pg_db):
    url = empty_pg_db()
    migrate.run_alembic_upgrade(url, "0012_m9")
    t12, c12 = _tables(url), _columns(url)
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:     # a Part 11 plant with the assistant on: the migration switches it off
            migrate.ensure_local_user_conn(c)
            c.execute(sa.text("UPDATE mfg_plant SET part11_mode = true, assistant_enabled = true"))
            n_plants = c.execute(sa.text("SELECT count(*) FROM mfg_plant")).scalar()
    finally:
        eng.dispose()
    migrate.run_alembic_upgrade(url)
    assert migrate.HEAD == "0013_m10" and migrate.schema_state(url) == "current"
    assert _tables(url) - t12 == set(M10_TABLES)
    assert {tc for tc in _columns(url) - c12 if tc[0] in t12} == set(M10_COLUMNS)
    assert _diffs(url) == []
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            on = c.execute(sa.text("SELECT count(*) FROM mfg_plant WHERE assistant_enabled")).scalar()
            assert on == 0 or n_plants == 0
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "0012_m9")
    assert _tables(url) == t12 and _columns(url) == c12


def test_examples_validate_and_are_current():
    built = build_example_m10.build()
    on_disk = json.loads(build_example_m10.OUT.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(built)), "run python -m superplanner.api.mfg.fixtures.build_example_m10"
    assert {"dhr_record", "dhr_live", "deviation", "agreement", "coa", "batch_pack", "udi_device", "udi_export",
            "label_template", "print_job", "verify_result", "val_package", "iq_result", "residency"} <= set(built)


def test_id_prefixes():
    for prefix in M10_ID_PREFIXES.values():
        assert re.fullmatch(r"[a-z]{3}_", prefix), prefix
    assert len(set(M10_ID_PREFIXES.values())) == len(M10_ID_PREFIXES)


def test_roles_permissions_and_policies():
    assert set(roles_allowed("dhr_review")) == {"owner", "plant_admin", "qa_engineer", "qa_approver"}
    assert set(roles_allowed("deviation_edit")) == {"owner", "plant_admin", "qa_engineer", "qa_approver",
                                                    "supervisor"}
    assert set(roles_allowed("udi_export")) == {"owner", "plant_admin", "regulatory", "qa_approver"}
    assert set(roles_allowed("label_admin")) == {"owner", "plant_admin", "labeling", "qa_engineer"}
    assert set(roles_allowed("label_print")) == {"owner", "plant_admin", "labeling", "supervisor", "operator"}
    assert set(roles_allowed("validation_admin")) == {"owner", "plant_admin", "qa_approver"}
    assert "dhr_review" not in ROLE_PERMISSIONS["auditor"]
    rel = POL.default("dhr", "release", final_release_role="qa_engineer")
    assert rel is not None and rel.auth == "password_totp" and rel.steps[-1]["roles"] == ["qa_engineer"]
    assert POL.expected_meanings("release", rel.steps[-1], "rejected") == ["rejected"]
    assert POL.validate("dhr", "release", [{"meaning": "reviewed", "roles": ["qa_engineer"]}], "password_totp")
    for key in (("deviation", "approve"), ("customer_agreement", "approve"), ("coa", "approve"),
                ("eco", "approve_label"), ("udi_device", "approve"), ("label_job", "reconcile"),
                ("validation_package", "approve"), ("plant", "assistant_on"), ("int_endpoint", "cross_region")):
        assert key in POL.DEFAULTS, key
    assert ("label_job", "reconcile") in POL.CONDITIONAL and ("plant", "assistant_on") in POL.FIXED


def test_every_m10_list_route_answers(api):
    for path in ("/dhr", "/dhr/review-queue", "/deviations", "/qa/agreements", "/coa", "/batch-packs",
                 "/udi/devices", "/udi/exports", "/labels/templates", "/labels/assignments", "/labels/printers",
                 "/labels/jobs", "/validation/packages"):
        out = api.get(path)
        assert isinstance(out, dict) and "items" in out, path
    assert api.get("/udi/parse", code="(01)09521234500018(17)281130(10)A2611QC07")["ok"] is True
