"""Alembic migrations, legacy upgrade path and startup schema handling (PHASE2B 3.2-3.4; Q1-2..Q1-6)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from db_helpers import (ALL_11, OWNED, SCHEDULING_6, build_legacy_db, counts, make_app, schema_diffs,
                        sqlite_counts)
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

def test_upgrade_head_and_create_all_produce_the_model_schema(empty_db_factory):
    migrated, fresh = empty_db_factory(), empty_db_factory()
    migrate.run_alembic_upgrade(migrated)
    assert migrate.ensure_schema(fresh) == "empty"            # create_all + stamp head
    assert schema_diffs(migrated) == []
    assert schema_diffs(fresh) == []
    assert _revision(migrated) == _revision(fresh) == [migrate.HEAD]
    assert migrate.schema_state(migrated) == migrate.schema_state(fresh) == "current"


@pytest.mark.postgres_only
def test_postgres_partial_indexes_keep_their_predicates(empty_db_factory):
    migrated, fresh = empty_db_factory(), empty_db_factory()
    migrate.run_alembic_upgrade(migrated)
    migrate.ensure_schema(fresh)
    for url in (migrated, fresh):
        eng = sa.create_engine(url)
        try:
            with eng.connect() as c:
                defs = dict(c.execute(sa.text("SELECT indexname, indexdef FROM pg_indexes "
                                              "WHERE schemaname = 'public'")).all())
        finally:
            eng.dispose()
        for name, predicate in PARTIAL_INDEXES.items():
            assert " WHERE " in defs[name] and predicate in defs[name], defs[name]
        assert "priority DESC" in defs["ix_jobs_claim"]
        # BIGINT event/audit ids (B 3.3)
        eng = sa.create_engine(url)
        try:
            with eng.connect() as c:
                types = dict(c.execute(sa.text(
                    "SELECT table_name, data_type FROM information_schema.columns WHERE column_name = 'id' "
                    "AND table_name IN ('solver_run_events', 'finance_run_events', 'audit_events')")).all())
        finally:
            eng.dispose()
        assert set(types.values()) == {"bigint"}, types


def test_both_paths_give_identical_indexes(empty_db_factory):
    a, b = empty_db_factory(), empty_db_factory()
    migrate.run_alembic_upgrade(a)
    migrate.ensure_schema(b)

    def index_set(url: str) -> set[tuple]:
        eng = sa.create_engine(url)
        try:
            insp = sa.inspect(eng)
            out = set()
            for t in insp.get_table_names():
                for ix in insp.get_indexes(t):
                    out.add((t, ix["name"], tuple(str(c) for c in ix["column_names"]), bool(ix["unique"])))
            return out
        finally:
            eng.dispose()

    assert index_set(a) == index_set(b)


# ---------------------------------------------------------------- Q1-3 legacy upgrade

@pytest.mark.parametrize("tables", [ALL_11, SCHEDULING_6], ids=["all-11-tables", "pre-finance-6-tables"])
def test_legacy_database_upgrades_on_first_start_and_keeps_all_rows(empty_db_factory, db_kind, tables):
    url = empty_db_factory()
    before = build_legacy_db(url, tables)
    assert all(before.values()), before
    assert migrate.schema_state(url) == "legacy"
    settings = {} if db_kind == "sqlite" else {"db_auto_migrate": True}
    with TestClient(make_app(url, **settings)) as c:
        assert c.get(f"{API}/problems").status_code == 200
        items = c.get(f"{API}/problems").json()["items"]
        assert [p["id"] for p in items] == ["p_1"]
        if "finance_plans" in tables:
            assert [p["id"] for p in c.get(f"{API}/finance/plans").json()["items"]] == ["fp_1"]
    assert migrate.schema_state(url) == "current"
    assert counts(url, tables) == before                       # R1: nothing cascaded away
    assert schema_diffs(url) == []
    if "finance_plans" not in tables:
        assert counts(url, ALL_11[6:]) == {t: 0 for t in ALL_11[6:]}   # finance tables created (R3)
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            for t in OWNED:
                if t in tables:
                    owners = {r[0] for r in c.execute(sa.text(f"SELECT DISTINCT owner_id FROM {t}"))}
                    assert owners == {"usr_local"}, (t, owners)
            assert c.execute(sa.text("SELECT display_name, is_local FROM users WHERE id = 'usr_local'")).one() \
                == ("Local user", True)
            if db_kind == "sqlite":
                assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    finally:
        eng.dispose()
    if db_kind == "sqlite":
        path = migrate.sqlite_path(url)
        backups = sorted(path.parent.glob(f"{path.name}.bak-0001-*"))
        assert len(backups) == 1
        assert sqlite_counts(backups[0], tables) == before    # R2: the backup opens and has every row
        con = sqlite3.connect(str(backups[0]))
        try:
            assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert con.execute("SELECT name FROM sqlite_master WHERE name = 'alembic_version'").fetchone() is None
        finally:
            con.close()


@pytest.mark.sqlite_only
def test_legacy_backup_contains_uncheckpointed_wal_data(tmp_path):
    """R2: committed rows that are still only in `<db>-wal` must be in the backup (a file copy would miss them)."""
    url = f"sqlite:///{tmp_path / 'wal.db'}"
    build_legacy_db(url, SCHEDULING_6)
    path = tmp_path / "wal.db"
    holder = sqlite3.connect(str(path))          # keeps the WAL from being checkpointed into the main file
    holder.execute("PRAGMA wal_autocheckpoint=0")
    holder.execute("INSERT INTO audit_events (entity_type, entity_id, action, details, created_at) "
                   "VALUES ('x', 'y', 'z', '{}', '2026-10-01 00:00:00')")
    holder.commit()
    try:
        assert (tmp_path / "wal.db-wal").stat().st_size > 0
        dest = migrate.backup_sqlite(url, None)
        assert dest is not None and dest.name.startswith("wal.db.bak-0001-")
        assert sqlite_counts(dest, ("audit_events",)) == {"audit_events": 2}
    finally:
        holder.close()


def test_legacy_with_unknown_table_is_refused_untouched(empty_db_factory, db_kind):
    url = empty_db_factory()
    build_legacy_db(url, SCHEDULING_6)
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE mystery (id INTEGER PRIMARY KEY)"))
    eng.dispose()
    with pytest.raises(migrate.SchemaError, match="unknown tables: mystery"):
        migrate.upgrade(url)
    assert migrate.schema_state(url) == "legacy"
    if db_kind == "sqlite":
        path = migrate.sqlite_path(url)
        assert not list(path.parent.glob(f"{path.name}.bak-*"))


def test_legacy_with_missing_column_is_refused(empty_db_factory):
    url = empty_db_factory()
    build_legacy_db(url, SCHEDULING_6)
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(sa.text("ALTER TABLE audit_events DROP COLUMN details"))
    eng.dispose()
    with pytest.raises(migrate.SchemaError, match="'audit_events' lacks columns: details"):
        migrate.upgrade(url)


# ---------------------------------------------------------------- Q1-4 legacy de-duplication

def test_legacy_duplicates_keep_the_newest(empty_db_factory):
    url = empty_db_factory()
    build_legacy_db(url, ALL_11, extra=True)
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
            payload = ev[1][2] if isinstance(ev[1][2], dict) else __import__("json").loads(ev[1][2])
            assert payload["error"] == "Server restarted before the run finished." and payload["seq"] == 2
            assert payload["ts"].endswith("Z") and payload["run_id"] == "run_old"
    finally:
        eng.dispose()


# ---------------------------------------------------------------- Q1-5 round trip

def test_downgrade_base_then_upgrade_head(empty_db_factory):
    url = empty_db_factory()
    build_legacy_db(url, ALL_11)
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


# ---------------------------------------------------------------- Q1-6 check / auto-migrate / concurrency

def test_check_exits_3_on_a_database_behind_head(empty_db_factory, capsys):
    url = empty_db_factory()
    migrate.run_alembic_upgrade(url, "0001_initial")
    assert migrate.schema_state(url) == "behind"
    assert migrate.main(["check", "--url", url]) == 3
    err = capsys.readouterr().err
    assert "Database schema is at 0001_initial, code needs 0002_phase2b" in err
    assert "python -m superplanner.migrate upgrade" in err
    with pytest.raises(migrate.SchemaError, match="code needs 0002_phase2b"):
        migrate.ensure_schema(url, Settings(database_url=url, db_auto_migrate=False))
    with pytest.raises(migrate.SchemaError):
        with TestClient(make_app(url, db_auto_migrate=False)):
            pass
    assert migrate.main(["upgrade", "--url", url]) == 0
    assert migrate.main(["check", "--url", url]) == 0
    assert migrate.main(["current", "--url", url]) == 0
    assert capsys.readouterr().out.strip().endswith(f"current {migrate.HEAD}")


def test_unknown_newer_revision_is_refused(empty_db_factory):
    url = empty_db_factory()
    migrate.ensure_schema(url)
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(sa.text("UPDATE alembic_version SET version_num = '0099_future'"))
    eng.dispose()
    assert migrate.schema_state(url) == "ahead"
    with pytest.raises(migrate.SchemaError, match="newer than this code"):
        migrate.ensure_schema(url)
    assert migrate.main(["check", "--url", url]) == 3


def test_stamp_legacy_cli(empty_db_factory):
    url = empty_db_factory()
    build_legacy_db(url, SCHEDULING_6)
    assert migrate.main(["stamp-legacy", "--url", url]) == 0
    assert migrate.schema_state(url) == "behind"
    assert migrate.main(["stamp-legacy", "--url", url]) == 3


@pytest.mark.postgres_only
def test_concurrent_ensure_schema_on_one_empty_postgres_db(empty_db_factory):
    url = empty_db_factory()
    results: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def go() -> None:
        try:
            barrier.wait()
            results.append(migrate.ensure_schema(url))
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


def test_fresh_start_creates_local_user_and_is_idempotent(empty_db_factory):
    url = empty_db_factory()
    for _ in range(2):
        with TestClient(make_app(url)) as c:
            assert c.get(f"{API}/health").status_code == 200
    eng = sa.create_engine(url)
    try:
        with eng.connect() as c:
            assert c.execute(sa.text("SELECT COUNT(*) FROM users")).scalar_one() == 1
            assert _revision(url) == [migrate.HEAD]
    finally:
        eng.dispose()


def test_sqlite_path_helper(tmp_path: Path):
    assert migrate.sqlite_path(f"sqlite:///{tmp_path / 'a.db'}") == tmp_path / "a.db"
    assert migrate.sqlite_path("sqlite://") is None
    assert migrate.sqlite_path("postgresql+psycopg://u:p@h/db") is None
