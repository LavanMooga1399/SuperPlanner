"""A1-3 / G8 (M1-DESIGN 6.1): 0002 -> 0003 keeps all data (SQLite: backup first), `check` passes after upgrade,
and `downgrade 0002_phase2b` removes exactly the 18 mfg tables, on both dialects."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from superplanner import migrate
from superplanner.api.db import load_all_models
from superplanner.api.mfg.db_models import MFG_TABLES

NOW = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
DATA_TABLES = ("users", "problems", "problem_versions", "finance_plans", "finance_plan_versions", "audit_events")


@pytest.fixture
def empty_url(request, db_kind, tmp_path):
    created = []

    def new() -> str:
        if db_kind == "sqlite":
            return f"sqlite:///{tmp_path / f'm_{uuid.uuid4().hex[:6]}.db'}"
        admin = request.getfixturevalue("pg_admin")
        name = f"sp_m_{uuid.uuid4().hex[:8]}"
        admin.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        return admin.url_for(name)

    yield new
    if created:
        admin = request.getfixturevalue("pg_admin")
        for n in created:
            admin.drop(n)


def _seed_2b(url: str) -> dict[str, int]:
    """A database at 0002_phase2b with problems, finance plans and audit data (Core inserts on the 0002 tables,
    which are unchanged by 0003)."""
    migrate.run_alembic_upgrade(url, "0002_phase2b")
    md = load_all_models()
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:
            migrate.ensure_local_user_conn(c)
            doc = {"name": "Legacy", "domain": "generic", "tasks": []}
            for i in range(3):
                c.execute(md.tables["problems"].insert().values(
                    id=f"p_{i}", name="P", domain="generic", template_id=None, version=1, document=doc,
                    created_at=NOW, updated_at=NOW, owner_id="usr_local"))
                c.execute(md.tables["problem_versions"].insert().values(
                    id=f"pv_{i}", problem_id=f"p_{i}", base_version=1, kind="snapshot", content_hash="h",
                    document=doc, created_at=NOW))
            c.execute(md.tables["finance_plans"].insert().values(
                id="fp_1", name="Money", template_id=None, version=1, document={"name": "Money"}, created_at=NOW,
                updated_at=NOW, owner_id="usr_local"))
            c.execute(md.tables["finance_plan_versions"].insert().values(
                id="fpv_1", plan_id="fp_1", base_version=1, kind="snapshot", content_hash="f",
                document={"name": "Money"}, created_at=NOW))
            c.execute(md.tables["audit_events"].insert().values(entity_type="problem", entity_id="p_0",
                                                                action="problem.created", details={},
                                                                created_at=NOW, actor_id="usr_local"))
    finally:
        eng.dispose()
    return _counts(url)


def _counts(url: str, tables=DATA_TABLES) -> dict[str, int]:
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            return {t: int(c.execute(sa.text(f'SELECT COUNT(*) FROM "{t}"')).scalar_one()) for t in tables}
    finally:
        eng.dispose()


def _tables(url: str) -> set[str]:
    eng = sa.create_engine(url)
    try:
        return set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _diffs(url: str) -> list:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            return list(compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}),
                                         load_all_models()))
    finally:
        eng.dispose()


@pytest.mark.sqlite_only
def test_sqlite_upgrade_on_start_backs_up_and_keeps_rows(empty_url):
    url = empty_url()
    before = _seed_2b(url)
    assert migrate.schema_state(url) == "behind"
    assert migrate.ensure_schema(url) == "behind"            # SQLite auto-migrates on start
    assert migrate.current_revision(url) == migrate.HEAD == "0003_mfg"
    assert _counts(url) == before
    assert set(MFG_TABLES) <= _tables(url) and _diffs(url) == []
    path = migrate.sqlite_path(url)
    backups = sorted(path.parent.glob(f"{path.name}.bak-0002-*"))
    assert len(backups) == 1
    con = sqlite3.connect(str(backups[0]))
    try:
        assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002_phase2b"
        assert con.execute("SELECT COUNT(*) FROM problems").fetchone()[0] == before["problems"]
        assert con.execute("SELECT name FROM sqlite_master WHERE name = 'mfg_items'").fetchone() is None
    finally:
        con.close()


def test_upgrade_check_and_downgrade_remove_exactly_the_mfg_tables(empty_url):
    url = empty_url()
    before = _seed_2b(url)
    tables_0002 = _tables(url)
    assert migrate.main(["upgrade", "--url", url]) == 0
    assert migrate.main(["check", "--url", url]) == 0
    assert _counts(url) == before and _diffs(url) == []
    assert _tables(url) - tables_0002 == set(MFG_TABLES)
    eng = sa.create_engine(url)
    try:
        with eng.begin() as c:                       # some mfg data must not block the downgrade
            c.execute(sa.text("INSERT INTO mfg_skills (id, owner_id, code, name, description, row_version, "
                              "created_at, updated_at) VALUES ('skl_x', 'usr_local', 'S', 'S', '', 1, :t, :t)"),
                      {"t": NOW})
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "0002_phase2b")
    assert _tables(url) == tables_0002
    assert _counts(url) == before
    assert migrate.current_revision(url) == "0002_phase2b"
    migrate.run_alembic_upgrade(url)
    assert _diffs(url) == [] and migrate.schema_state(url) == "current"
