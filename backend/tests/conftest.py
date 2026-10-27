"""Root test configuration: PostgreSQL test harness (PHASE2B 3.6; PostgreSQL only).

    cd backend && .venv/bin/pytest          # needs the dev cluster: scripts/pg_dev_cluster.sh init

`SP_TEST_PG_URL` (default: the dev cluster on 127.0.0.1:54329, role sp_test with CREATEDB) is the admin URL used
to create/drop databases. Once per session a template database `sp_tpl_<pid>` is built by running the real
Alembic chain (`0001_initial` -> head); every `db_url_factory(name)` call clones it with
`CREATE DATABASE sp_t_<uuid8> TEMPLATE ... STRATEGY FILE_COPY` and drops it (`WITH (FORCE)`) after the test.
`SP_TEST_PG_SUPERUSER_URL` (default: user `postgres` on the same server) is only used by the least-privilege role
tests (they skip with a visible reason if it is not reachable).

Every test runs with APP_ENV=development and AUTH_MODE=single_user unless it sets its own values (constructor
arguments always win over the environment). Markers: `inline_jobs` (forces JOB_BACKEND=inline), `pg_load`.
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


# Baseline for the whole session (module/session-scoped apps are built before the per-test autouse fixture runs).
SESSION_ENV = {"APP_ENV": "development", "AUTH_MODE": "single_user", "PASSWORD_HASH_PROFILE": "fast",
               "JOB_BACKEND": "queue", "WORKER_EMBEDDED": "auto", "JOB_CANCEL_POLL_SECONDS": "0.2",
               "WORKER_POLL_SECONDS": "0.2", "WORKER_SHUTDOWN_GRACE_SECONDS": "1"}
CLEARED_ENV = ("DATABASE_URL", "MIGRATION_DATABASE_URL", "SP_ENV", "AUTO_MIGRATE", "DB_AUTO_MIGRATE", "METRICS_TOKEN",
               "CORS_ORIGINS", "PUBLIC_BASE_URL", "COOKIE_SECURE")


def pytest_configure(config: pytest.Config) -> None:
    for name in CLEARED_ENV:
        os.environ.pop(name, None)
    os.environ.update(SESSION_ENV)


def pytest_report_header(config: pytest.Config) -> str:
    return f"superplanner test database: postgres ({_pg_admin_url_display()})"


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
def db_kind() -> str:
    """Always "postgres" (kept for tests that label their output with it)."""
    return "postgres"


@pytest.fixture(scope="session")
def pg_admin() -> Iterator[PgAdmin]:
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


def _stop_live_contexts(dbnames: list[str]) -> None:
    """Stop app contexts still running on these databases (TestClient used without `with`, abandoned apps), so
    their embedded worker threads end before the database is dropped."""
    if not dbnames:
        return
    from sqlalchemy.engine import make_url

    from superplanner.api.context import live_contexts

    names = set(dbnames)
    for ctx in live_contexts():
        try:
            if make_url(ctx.db.url).database in names:
                ctx.stop()
        except Exception:  # pragma: no cover - best effort
            pass


def _factory(request: pytest.FixtureRequest) -> Callable[[str], str]:
    created: list[str] = []
    admin: PgAdmin = request.getfixturevalue("pg_admin")
    template: str = request.getfixturevalue("pg_template")

    def new_pg(_name: str = "db") -> str:
        dbname = admin.create_from_template(template)
        created.append(dbname)
        return admin.url_for(dbname)

    def _cleanup() -> None:
        _stop_live_contexts(created)
        for n in created:
            try:
                admin.drop(n)
            except Exception:  # pragma: no cover - best effort
                pass

    request.addfinalizer(_cleanup)
    return new_pg


@pytest.fixture
def db_url_factory(request: pytest.FixtureRequest) -> Callable[[str], str]:
    """`new(name) -> url`: a fresh database at migrate.HEAD for this test (a clone of the template)."""
    return _factory(request)


@pytest.fixture(scope="module")
def db_url_factory_module(request: pytest.FixtureRequest) -> Callable[[str], str]:
    """Module-scoped variant (`shared_fin` and other expensive per-module apps)."""
    return _factory(request)


@pytest.fixture
def empty_pg_db(pg_admin: PgAdmin) -> Iterator[Callable[[], str]]:
    """`new() -> url` of a truly empty database (no schema at all; `CREATE DATABASE` without our template)."""
    created: list[str] = []

    def new() -> str:
        name = f"sp_e_{uuid.uuid4().hex[:8]}"
        pg_admin.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        return pg_admin.url_for(name)

    yield new
    _stop_live_contexts(created)
    for n in created:
        try:
            pg_admin.drop(n)
        except Exception:  # pragma: no cover - best effort
            pass


@pytest.fixture(autouse=True)
def _phase2b_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-test environment (PHASE2B 3.6): development + single_user defaults (tests that need accounts or production
    pass them explicitly), the durable queue with embedded worker threads in the test process (so monkeypatched
    run-service internals still apply), and a short shutdown grace (running jobs are requeued, B 2.9).
    DATABASE_URL / MIGRATION_DATABASE_URL from the caller's shell never leak into a test."""
    for name in CLEARED_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in SESSION_ENV.items():
        monkeypatch.setenv(name, value)
    if request.node.get_closest_marker("inline_jobs"):
        monkeypatch.setenv("JOB_BACKEND", "inline")
