"""Alembic migrations and the startup schema check (PHASE2B 3.2-3.4; Q1-2..Q1-6; PostgreSQL only).

The schema exists only through the migration chain: an app on an empty / behind database refuses to start unless
AUTO_MIGRATE is set, and `python -m superplanner.migrate upgrade` is the explicit step."""

from __future__ import annotations

import json
import threading

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from db_helpers import ALL_11, OWNED, SCHEDULING_6, build_0001_db, counts, make_app, schema_diffs
from superplanner import migrate
from superplanner.api.config import Settings

API = "/api/v1"
PARTIAL_INDEXES = {
    "uq_solver_runs_one_active": "status", "uq_schedules_one_approved": "status", "ix_jobs_claim": "status",
    "ix_jobs_running_lease": "status", "uq_jobs_solver_run": "solver_run_id IS NOT NULL",
    "uq_jobs_finance_run": "finance_run_id IS NOT NULL", "uq_jobs_idempotency": "idempotency_key IS NOT NULL",
}


def _revision(url: str) -> list[str]:
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            return [r[0] for r in c.execute(sa.text("SELECT version_num FROM alembic_version"))]
    finally:
        eng.dispose()


# ---------------------------------------------------------------- Q1-2 metadata == migrations

def test_upgrade_head_produces_the_model_schema(empty_db_factory):
    url = empty_db_factory()
    assert migrate.schema_state(url) == "empty"
    assert migrate.upgrade(url) == "empty"
    assert schema_diffs(url) == []
    assert _revision(url) == [migrate.HEAD]
    assert migrate.schema_state(url) == "current"
    assert migrate.upgrade(url) == "current"          # idempotent


def test_partial_indexes_keep_their_predicates_and_ids_are_bigint(empty_db_factory):
    url = empty_db_factory()
    migrate.run_alembic_upgrade(url)
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            defs = dict(c.execute(sa.text("SELECT indexname, indexdef FROM pg_indexes "
                                          "WHERE schemaname = 'public'")).all())
            types = dict(c.execute(sa.text(
                "SELECT table_name, data_type FROM information_schema.columns WHERE column_name = 'id' "
                "AND table_name IN ('solver_run_events', 'finance_run_events', 'audit_events')")).all())
    finally:
        eng.dispose()
    for name, predicate in PARTIAL_INDEXES.items():
        assert " WHERE " in defs[name] and predicate in defs[name], defs[name]
    assert "priority DESC" in defs["ix_jobs_claim"]
    assert set(types.values()) == {"bigint"}, types      # B 3.3


# ---------------------------------------------------------------- Q1-3 data survives the chain

@pytest.mark.parametrize("tables", [ALL_11, SCHEDULING_6], ids=["all-11-tables", "scheduling-only"])
def test_0001_database_upgrades_with_auto_migrate_and_keeps_all_rows(empty_db_factory, tables):
    url = empty_db_factory()
    before = build_0001_db(url, tables)
    assert all(before.values()), before
    assert migrate.schema_state(url) == "behind"
    with TestClient(make_app(url, db_auto_migrate=True)) as c:
        items = c.get(f"{API}/problems").json()["items"]
        assert [p["id"] for p in items] == ["p_1"]
        if "finance_plans" in tables:
            assert [p["id"] for p in c.get(f"{API}/finance/plans").json()["items"]] == ["fp_1"]
    assert migrate.schema_state(url) == "current"
    assert counts(url, tables) == before                       # nothing cascaded away
    assert schema_diffs(url) == []
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            for t in OWNED:
                if t in tables:
                    owners = {r[0] for r in c.execute(sa.text(f"SELECT DISTINCT owner_id FROM {t}"))}
                    assert owners == {"usr_local"}, (t, owners)
            assert c.execute(sa.text("SELECT display_name, is_local FROM users WHERE id = 'usr_local'")).one() \
                == ("Local user", True)
    finally:
        eng.dispose()


# ---------------------------------------------------------------- Q1-4 0002 de-duplication

def test_0002_duplicates_keep_the_newest(empty_db_factory):
    url = empty_db_factory()
    build_0001_db(url, ALL_11, extra=True)
    migrate.upgrade(url)
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            sch = dict(c.execute(sa.text("SELECT id, status FROM schedules")).all())
            assert sch["sch_1"] == "approved" and sch["sch_old"] == "superseded"
            assert c.execute(sa.text("SELECT superseded_at FROM schedules WHERE id = 'sch_old'")).scalar() is not None
            runs = {r[0]: (r[1], r[2]) for r in c.execute(sa.text("SELECT id, status, error FROM solver_runs"))}
            assert runs["run_new"] == ("running", None)
            assert runs["run_old"] == ("failed", "Server restarted before the run finished.")
            ev = c.execute(sa.text("SELECT seq, type, payload FROM solver_run_events WHERE run_id = 'run_old' "
                                   "ORDER BY seq")).all()
            assert [(e[0], e[1]) for e in ev] == [(1, "run_queued"), (2, "run_failed")]
            payload = ev[1][2] if isinstance(ev[1][2], dict) else json.loads(ev[1][2])
            assert payload["error"] == "Server restarted before the run finished." and payload["seq"] == 2
            assert payload["ts"].endswith("Z") and payload["run_id"] == "run_old"
    finally:
        eng.dispose()


# ---------------------------------------------------------------- Q1-5 round trip

def test_downgrade_base_then_upgrade_head(empty_db_factory):
    url = empty_db_factory()
    build_0001_db(url, ALL_11)
    migrate.upgrade(url)
    before = counts(url)
    migrate.run_alembic_downgrade(url, "0001_initial")
    assert counts(url) == before                     # 0002 downgrade keeps the data of the 11 tables
    eng = sa.create_engine(url)
    try:
        assert "owner_id" not in {c["name"] for c in sa.inspect(eng).get_columns("problems")}
        assert "users" not in sa.inspect(eng).get_table_names()
    finally:
        eng.dispose()
    migrate.run_alembic_downgrade(url, "base")
    eng = sa.create_engine(url)
    try:
        assert set(sa.inspect(eng).get_table_names()) <= {"alembic_version"}
    finally:
        eng.dispose()
    migrate.run_alembic_upgrade(url)
    assert schema_diffs(url) == []
    assert migrate.schema_state(url) == "current"


# ---------------------------------------------------------------- Q1-6 check / startup refusal / auto-migrate

def test_check_exits_3_on_a_database_behind_head(empty_db_factory, capsys):
    url = empty_db_factory()
    migrate.run_alembic_upgrade(url, "0001_initial")
    assert migrate.schema_state(url) == "behind"
    assert migrate.main(["check", "--url", url]) == 3
    err = capsys.readouterr().err
    assert f"Database schema is 0001_initial, code needs {migrate.HEAD}" in err
    assert "python -m superplanner.migrate upgrade" in err
    with pytest.raises(migrate.SchemaError, match=f"code needs {migrate.HEAD}"):
        migrate.ensure_schema(url, Settings(database_url=url, db_auto_migrate=False))
    with pytest.raises(migrate.SchemaError):
        with TestClient(make_app(url, db_auto_migrate=False)):
            pass
    assert migrate.main(["upgrade", "--url", url]) == 0
    assert migrate.main(["check", "--url", url]) == 0
    assert migrate.main(["current", "--url", url]) == 0
    assert capsys.readouterr().out.strip().endswith(f"current {migrate.HEAD}")


def test_empty_database_is_refused_without_auto_migrate(empty_db_factory):
    """No create_all at runtime: an empty database stays empty and the app says which command to run."""
    url = empty_db_factory()
    with pytest.raises(migrate.SchemaError, match="Run: python -m superplanner.migrate upgrade"):
        with TestClient(make_app(url)):
            pass
    assert migrate.schema_state(url) == "empty"
    eng = sa.create_engine(url)
    try:
        assert sa.inspect(eng).get_table_names() == []
    finally:
        eng.dispose()


def test_auto_migrate_creates_schema_and_local_user_idempotently(empty_db_factory):
    url = empty_db_factory()
    for _ in range(2):
        with TestClient(make_app(url, db_auto_migrate=True)) as c:
            assert c.get(f"{API}/health").status_code == 200
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            assert c.execute(sa.text("SELECT COUNT(*) FROM users")).scalar_one() == 1
    finally:
        eng.dispose()
    assert _revision(url) == [migrate.HEAD]
    assert schema_diffs(url) == []


def test_auto_migrate_env_and_legacy_alias(monkeypatch):
    pg = "postgresql+psycopg://u:p@127.0.0.1:1/x"
    assert Settings(database_url=pg).db_auto_migrate is False
    monkeypatch.setenv("AUTO_MIGRATE", "true")
    assert Settings(database_url=pg).db_auto_migrate is True
    monkeypatch.delenv("AUTO_MIGRATE")
    monkeypatch.setenv("DB_AUTO_MIGRATE", "true")
    assert Settings(database_url=pg).db_auto_migrate is True


def test_unknown_newer_revision_is_refused(empty_db_factory):
    url = empty_db_factory()
    migrate.upgrade(url)
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(sa.text("UPDATE alembic_version SET version_num = '0099_future'"))
    eng.dispose()
    assert migrate.schema_state(url) == "ahead"
    with pytest.raises(migrate.SchemaError, match="newer than this code"):
        migrate.ensure_schema(url, Settings(database_url=url, db_auto_migrate=True))
    with pytest.raises(migrate.SchemaError, match="newer than this code"):
        migrate.upgrade(url)
    assert migrate.main(["check", "--url", url]) == 3


def test_tables_without_revision_are_refused_untouched(empty_db_factory):
    url = empty_db_factory()
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE problems (id varchar(64) PRIMARY KEY)"))
    eng.dispose()
    assert migrate.schema_state(url) == "unknown"
    with pytest.raises(migrate.SchemaError, match="no Alembic revision"):
        migrate.upgrade(url)
    with pytest.raises(migrate.SchemaError, match="no Alembic revision"):
        migrate.ensure_schema(url, Settings(database_url=url, db_auto_migrate=True))
    assert migrate.schema_state(url) == "unknown"


def test_concurrent_upgrade_on_one_empty_database(empty_db_factory):
    url = empty_db_factory()
    results: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def go() -> None:
        try:
            barrier.wait()
            results.append(migrate.upgrade(url))
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors, errors
    assert sorted(results) == ["current", "empty"]
    assert _revision(url) == [migrate.HEAD]
    assert schema_diffs(url) == []


def test_cli_without_database_url_is_a_config_error(capsys):
    assert migrate.main(["check"]) == 2
    assert "DATABASE_URL is required" in capsys.readouterr().err
    assert migrate.main(["check", "--url", "sqlite:///x.db"]) == 2
    assert "must be a PostgreSQL URL" in capsys.readouterr().err


def test_cli_prefers_migration_database_url(empty_db_factory, monkeypatch, capsys):
    url = empty_db_factory()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:x@127.0.0.1:1/never")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    assert migrate.main(["upgrade"]) == 0
    assert migrate.schema_state(url) == "current"
