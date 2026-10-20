"""Root test configuration: dual-database harness (PHASE2B 3.6).

    cd backend && .venv/bin/pytest                                   # SQLite (default), inline jobs
    SP_TEST_DB=postgres SP_TEST_PG_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres \\
        .venv/bin/pytest                                             # PostgreSQL (or: pytest --db=postgres)

PostgreSQL: once per session a template database `sp_tpl_<pid>` is built by running the real Alembic chain
(`0001_initial` -> head); every `db_url_factory(name)` call clones it with
`CREATE DATABASE sp_t_<uuid8> TEMPLATE ... STRATEGY FILE_COPY` and drops it (`WITH (FORCE)`) after the test.
SQLite: a fresh temp file per call (app start does create_all + stamp head).

Markers: `postgres_only`, `sqlite_only` (skipped on the other dialect with a visible reason), `inline_jobs`
(forces JOB_BACKEND=inline), `pg_load` (load tests; Postgres only).
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

DEFAULT_PG_URL = "postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--db", choices=["sqlite", "postgres"], default=os.environ.get("SP_TEST_DB", "sqlite"),
                     help="database for the backend tests (default: SP_TEST_DB or sqlite)")


def selected_db(config: pytest.Config) -> str:
    return str(config.getoption("--db"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    db = selected_db(config)
    skip_pg = pytest.mark.skip(reason="PostgreSQL-only test (run with SP_TEST_DB=postgres)")
    skip_sqlite = pytest.mark.skip(reason="SQLite-only test (this run uses PostgreSQL)")
    for item in items:
        if db == "sqlite" and (item.get_closest_marker("postgres_only") or item.get_closest_marker("pg_load")):
            item.add_marker(skip_pg)
        if db == "postgres" and item.get_closest_marker("sqlite_only"):
            item.add_marker(skip_sqlite)


def pytest_report_header(config: pytest.Config) -> str:
    db = selected_db(config)
    if db == "postgres":
        return f"superplanner test database: postgres ({_pg_admin_url_display()})"
    return "superplanner test database: sqlite"


def _pg_admin_url() -> str:
    from superplanner.api.config import normalize_database_url

    return normalize_database_url(os.environ.get("SP_TEST_PG_URL") or DEFAULT_PG_URL)


def _pg_admin_url_display() -> str:
    from sqlalchemy.engine import make_url

    return make_url(_pg_admin_url()).render_as_string(hide_password=True)


def _with_database(url: str, name: str) -> str:
    from sqlalchemy.engine import make_url

    return make_url(url).set(database=name).render_as_string(hide_password=False)


class PgAdmin:
    """AUTOCOMMIT connection to the admin database for CREATE/DROP DATABASE."""

    def __init__(self, url: str):
        from sqlalchemy import create_engine, pool

        self.url = url
        self.engine = create_engine(url, poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")

    def execute(self, sql: str) -> None:
        from sqlalchemy import text

        with self.engine.connect() as c:
            c.execute(text(sql))

    def create_from_template(self, template: str) -> str:
        name = f"sp_t_{uuid.uuid4().hex[:8]}"
        self.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}" STRATEGY FILE_COPY')
        return name

    def drop(self, name: str) -> None:
        self.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def url_for(self, name: str) -> str:
        return _with_database(self.url, name)


@pytest.fixture(scope="session")
def db_kind(request: pytest.FixtureRequest) -> str:
    return selected_db(request.config)


@pytest.fixture(scope="session")
def pg_admin(db_kind: str) -> Iterator[PgAdmin]:
    if db_kind != "postgres":
        pytest.skip("PostgreSQL-only fixture")
    admin = PgAdmin(_pg_admin_url())
    try:
        admin.execute("SELECT 1")
    except Exception as exc:  # pragma: no cover - environment problem
        pytest.exit(f"cannot reach PostgreSQL at {_pg_admin_url_display()}: {exc}. "
                    "Start it with backend/scripts/pg_dev_cluster.sh init", returncode=4)
    yield admin
    admin.engine.dispose()


@pytest.fixture(scope="session")
def pg_template(pg_admin: PgAdmin) -> Iterator[str]:
    """`sp_tpl_<pid>`: an empty database migrated with the real Alembic chain to head."""
    from superplanner import migrate

    name = f"sp_tpl_{os.getpid()}"
    pg_admin.drop(name)
    pg_admin.execute(f'CREATE DATABASE "{name}"')
    migrate.run_alembic_upgrade(pg_admin.url_for(name))
    with_local = migrate._migration_engine(pg_admin.url_for(name))
    try:
        with with_local.begin() as c:
            migrate.ensure_local_user_conn(c)
    finally:
        with_local.dispose()
    yield name
    pg_admin.drop(name)


def _factory(request: pytest.FixtureRequest, base_dir: Callable[[], Path]) -> Callable[[str], str]:
    db = selected_db(request.config)
    created: list[str] = []
    if db == "postgres":
        admin: PgAdmin = request.getfixturevalue("pg_admin")
        template: str = request.getfixturevalue("pg_template")

        def new_pg(_name: str = "db") -> str:
            dbname = admin.create_from_template(template)
            created.append(dbname)
            return admin.url_for(dbname)

        def _cleanup() -> None:
            for n in created:
                try:
                    admin.drop(n)
                except Exception:  # pragma: no cover - best effort
                    pass

        request.addfinalizer(_cleanup)
        return new_pg

    def new_sqlite(name: str = "db") -> str:
        return f"sqlite:///{base_dir() / f'{name}.db'}"

    return new_sqlite


@pytest.fixture
def db_url_factory(request: pytest.FixtureRequest, tmp_path: Path) -> Callable[[str], str]:
    """`new(name) -> url`: a fresh, empty database for this test (SQLite file or cloned Postgres DB)."""
    return _factory(request, lambda: tmp_path)


@pytest.fixture(scope="module")
def db_url_factory_module(request: pytest.FixtureRequest,
                          tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], str]:
    """Module-scoped variant (`shared_fin` and other expensive per-module apps)."""
    holder: list[Path] = []

    def base() -> Path:
        if not holder:
            holder.append(tmp_path_factory.mktemp("dbmod"))
        return holder[0]

    return _factory(request, base)


@pytest.fixture(autouse=True)
def _phase2b_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-test environment (PHASE2B 3.6). Q1: inline jobs on both dialects (Q2 switches Postgres to the queue)."""
    monkeypatch.setenv("PASSWORD_HASH_PROFILE", "fast")
    if selected_db(request.config) == "postgres":
        monkeypatch.setenv("JOB_BACKEND", "inline")
        monkeypatch.setenv("JOB_CANCEL_POLL_SECONDS", "0.2")
        monkeypatch.setenv("WORKER_POLL_SECONDS", "0.2")
    if request.node.get_closest_marker("inline_jobs"):
        monkeypatch.setenv("JOB_BACKEND", "inline")
