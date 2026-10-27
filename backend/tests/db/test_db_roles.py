"""Least-privilege database roles (docs/DEPLOY.md "Database roles"): `scripts/pg_setup_roles.sh` / `.sql` create an
owner role (migrations) and a restricted app role (DML only). The application runs end to end as the app role;
the app role cannot change the schema; AUTO_MIGRATE uses MIGRATION_DATABASE_URL (owner).

Needs a superuser connection (`SP_TEST_PG_SUPERUSER_URL`, default user `postgres` on the test cluster, which the
dev cluster allows via trust auth on 127.0.0.1) and the `psql` binary; skipped with a visible reason otherwise."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from db_helpers import make_app
from superplanner import migrate

API = "/api/v1"
BACKEND = Path(__file__).resolve().parents[2]
SCRIPTS = BACKEND / "scripts"
PG_BIN = Path(os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin"))
OWNER_PW = "owner-" + uuid.uuid4().hex
APP_PW = "app-" + uuid.uuid4().hex


def _psql() -> str | None:
    if (PG_BIN / "psql").exists():
        return str(PG_BIN / "psql")
    return shutil.which("psql")


def _superuser_url() -> str:
    from superplanner.api.config import normalize_database_url

    raw = os.environ.get("SP_TEST_PG_SUPERUSER_URL")
    if raw:
        return normalize_database_url(raw)
    admin = make_url(normalize_database_url(os.environ.get("SP_TEST_PG_URL")
                                            or "postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres"))
    return admin.set(username="postgres", password=None, database="postgres").render_as_string(hide_password=False)


@dataclass
class RoleDb:
    name: str
    owner: str
    app: str
    owner_url: str
    app_url: str


def _psql_env(su: sa.engine.URL) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"PGHOST": su.host or "127.0.0.1", "PGPORT": str(su.port or 5432), "PGUSER": su.username or "postgres"})
    if su.password:
        env["PGPASSWORD"] = str(su.password)
    env["PATH"] = f"{Path(_psql() or 'psql').parent}{os.pathsep}{env.get('PATH', '')}"
    return env


@pytest.fixture
def role_db() -> Iterator[RoleDb]:
    psql = _psql()
    if psql is None or shutil.which("bash") is None:
        pytest.skip("needs bash and psql")
    su_url = _superuser_url()
    su = make_url(su_url)
    eng = sa.create_engine(su_url, poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as c:
            if not c.execute(sa.text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar():
                pytest.skip("SP_TEST_PG_SUPERUSER_URL is not a superuser")
    except sa.exc.OperationalError as exc:
        eng.dispose()
        pytest.skip(f"no superuser connection for the role tests: {str(exc.orig).splitlines()[0]}")
    tag = uuid.uuid4().hex[:8]
    rd = RoleDb(name=f"sp_r_{tag}", owner=f"sp_r_{tag}_owner", app=f"sp_r_{tag}_app", owner_url="", app_url="")
    env = _psql_env(su)
    env.update({"SP_DB": rd.name, "SP_OWNER_ROLE": rd.owner, "SP_APP_ROLE": rd.app,
                "SP_OWNER_PASSWORD": OWNER_PW, "SP_APP_PASSWORD": APP_PW, "PSQL": psql})
    try:
        for _ in range(2):   # idempotent
            p = subprocess.run(["bash", str(SCRIPTS / "pg_setup_roles.sh")], env=env, capture_output=True,
                               text=True, timeout=60)
            assert p.returncode == 0, p.stderr
            assert "DATABASE_URL=postgresql+psycopg://" in p.stdout and APP_PW not in p.stdout
        base = su.set(database=rd.name)
        rd.owner_url = base.set(username=rd.owner, password=OWNER_PW).render_as_string(hide_password=False)
        rd.app_url = base.set(username=rd.app, password=APP_PW).render_as_string(hide_password=False)
        yield rd
    finally:
        from superplanner.api.context import live_contexts

        for ctx in live_contexts():
            if make_url(ctx.db.url).database == rd.name:
                ctx.stop()
        with eng.connect() as c:
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{rd.name}" WITH (FORCE)'))
            for r in (rd.app, rd.owner):
                c.execute(sa.text(f'DROP ROLE IF EXISTS "{r}"'))
        eng.dispose()


def _scalar(url: str, sql: str) -> object:
    eng = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with eng.begin() as c:
            return c.execute(sa.text(sql)).scalar()
    finally:
        eng.dispose()


def _wait_run(c: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        st = c.get(f"{API}/solver-runs/{run_id}").json()
        if st["status"] not in ("queued", "running"):
            return st
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def test_app_runs_as_the_restricted_role_after_owner_migration(role_db: RoleDb, monkeypatch):
    # roles: neither is a superuser or may create databases/roles; the owner owns the database
    assert _scalar(role_db.owner_url, "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles "
                                      "WHERE rolname = current_user") is False
    assert _scalar(role_db.app_url, "SELECT pg_get_userbyid(datdba) FROM pg_database "
                                    "WHERE datname = current_database()") == role_db.owner

    # the app role cannot migrate (no DDL); the owner can, through MIGRATION_DATABASE_URL
    with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
        migrate.upgrade(role_db.app_url)
    assert migrate.schema_state(role_db.app_url) == "empty"
    monkeypatch.setenv("DATABASE_URL", role_db.app_url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", role_db.owner_url)
    assert migrate.main(["upgrade"]) == 0
    assert migrate.schema_state(role_db.app_url) == "current"
    assert _scalar(role_db.app_url, "SELECT tableowner FROM pg_tables WHERE tablename = 'problems'") == role_db.owner

    # the full flow as the app role: plan, solver run through the queue (embedded worker), approve, mfg data
    with TestClient(make_app(role_db.app_url)) as c:
        assert c.get(f"{API}/health/ready").json()["status"] == "ready"
        r = c.post(f"{API}/templates/manufacturing/instantiate",
                   json={"start_date": "2026-10-19", "utc_offset": "+05:30", "parameters": {"jobs": 3}})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        run = c.post(f"{API}/problems/{pid}/solver-runs", json={"strategy": "heuristic", "time_limit_seconds": 2})
        assert run.status_code == 202, run.text
        st = _wait_run(c, run.json()["run_id"])
        assert st["status"] == "completed", st
        assert c.post(f"{API}/schedules/{st['primary_schedule_id']}/approve", json={}).status_code == 200
        r = c.post(f"{API}/mfg/skills", json={"code": "WELD", "name": "Welding"})
        assert r.status_code == 201, r.text
        assert c.post(f"{API}/mfg/samples/small/load", json={"replace": True}).status_code == 200

    # and it still cannot change the schema
    for ddl in ("CREATE TABLE intruder (id int)", "DROP TABLE mfg_skills", "TRUNCATE audit_events",
                "ALTER TABLE problems ADD COLUMN x int", "CREATE INDEX ix_x ON problems (name)"):
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied|must be owner"):
            _scalar(role_db.app_url, ddl)
    assert _scalar(role_db.app_url, "SELECT COUNT(*) FROM audit_events") >= 2


def test_auto_migrate_uses_the_owner_url(role_db: RoleDb):
    with TestClient(make_app(role_db.app_url, db_auto_migrate=True,
                             migration_database_url=role_db.owner_url)) as c:
        assert c.get(f"{API}/health/ready").json()["schema"] == "ok"
    assert migrate.schema_state(role_db.app_url) == "current"
    with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
        _scalar(role_db.app_url, "CREATE TABLE intruder (id int)")


def test_docker_initdb_script_creates_the_same_roles(tmp_path):
    """backend/scripts/docker-initdb-roles.sh (compose `db` first start) on the test cluster."""
    psql = _psql()
    if psql is None or shutil.which("sh") is None:
        pytest.skip("needs sh and psql")
    su_url = _superuser_url()
    su = make_url(su_url)
    eng = sa.create_engine(su_url, poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as c:
            c.execute(sa.text("SELECT 1"))
    except sa.exc.OperationalError:
        eng.dispose()
        pytest.skip("no superuser connection")
    tag = uuid.uuid4().hex[:8]
    db, owner, app = f"sp_d_{tag}", f"sp_d_{tag}_owner", f"sp_d_{tag}_app"
    script = tmp_path / "init.sh"
    script.write_text((SCRIPTS / "docker-initdb-roles.sh").read_text()
                      .replace("/sp/pg_setup_roles.sql", str(SCRIPTS / "pg_setup_roles.sql")))
    env = _psql_env(su)
    env.update({"POSTGRES_USER": su.username or "postgres", "POSTGRES_DB": db, "SP_DB_OWNER_USER": owner,
                "SP_DB_OWNER_PASSWORD": OWNER_PW, "SP_DB_APP_USER": app, "SP_DB_APP_PASSWORD": APP_PW})
    try:
        p = subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        owner_url = su.set(database=db, username=owner, password=OWNER_PW).render_as_string(hide_password=False)
        app_url = su.set(database=db, username=app, password=APP_PW).render_as_string(hide_password=False)
        migrate.upgrade(owner_url)
        assert _scalar(app_url, "SELECT COUNT(*) FROM users") == 1
        with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
            _scalar(app_url, "CREATE TABLE intruder (id int)")
    finally:
        with eng.connect() as c:
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
            for r in (app, owner):
                c.execute(sa.text(f'DROP ROLE IF EXISTS "{r}"'))
        eng.dispose()
