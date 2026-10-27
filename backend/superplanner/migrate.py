"""Schema management (PHASE2B 3.4, PostgreSQL only): the startup schema check and the explicit migration CLI.

    python -m superplanner.migrate upgrade  [--url URL]   bring the database to head (the real Alembic chain)
    python -m superplanner.migrate current  [--url URL]   print the schema state and revision
    python -m superplanner.migrate check    [--url URL]   exit 0 if at head, else 3

URL: `--url`, else MIGRATION_DATABASE_URL (owner role), else DATABASE_URL.

The schema is created and changed ONLY by the Alembic chain (`migrations/versions`); nothing calls `create_all` at
runtime. API, worker and admin CLI call `ensure_schema` at startup, which refuses (SchemaError, exit code 3) unless
the database is at `HEAD` - or, with AUTO_MIGRATE=true, first runs `upgrade` on the owner URL.

States: `empty` (none of our tables), `unknown` (our tables but no Alembic revision), `behind`, `current`, `ahead`.
All schema work runs under `pg_advisory_lock(727001)` (concurrently starting instances migrate once) with
`statement_timeout = 0` and `lock_timeout = '60s'` (the API's 30 s statement timeout would abort index builds).
Exit codes: 3 = schema problem (`SchemaError`) or database unreachable, 2 = configuration problem.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy import Connection, Engine, create_engine, inspect, pool, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .api.config import ConfigError, Settings, normalize_database_url, resolve_migration_url, validate_database_url

log = logging.getLogger("superplanner.migrate")
# Alembic logs several INFO lines per connection ("Context impl ...", plugin setup); our own `schema.migrated`
# line is the one that matters. Only applied if nobody configured the alembic logger explicitly.
if logging.getLogger("alembic").level == logging.NOTSET:
    logging.getLogger("alembic").setLevel(logging.WARNING)

HEAD = "0003_mfg"
BASE_REVISION = "0001_initial"
ADVISORY_LOCK_KEY = 727001
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
UPGRADE_COMMAND = "python -m superplanner.migrate upgrade"
SchemaState = Literal["empty", "unknown", "behind", "current", "ahead"]


class SchemaError(RuntimeError):
    """The database schema cannot be used (exit code 3)."""

    exit_code = 3


# ---------------------------------------------------------------- alembic plumbing

@lru_cache(maxsize=1)
def _script():
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(_alembic_config())


def _alembic_config(connection: Connection | None = None):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def known_revisions() -> set[str]:
    return {r.revision for r in _script().walk_revisions()}


def _current_revision(conn: Connection) -> str | None:
    from alembic.migration import MigrationContext

    return MigrationContext.configure(conn).get_current_revision()


def _upgrade(conn: Connection, target: str = "head") -> None:
    from alembic import command

    command.upgrade(_alembic_config(conn), target)


def _downgrade(conn: Connection, target: str) -> None:
    from alembic import command

    command.downgrade(_alembic_config(conn), target)


# ---------------------------------------------------------------- engines

def _migration_engine(url: str) -> Engine:
    url = validate_database_url(url)
    return create_engine(url, poolclass=pool.NullPool, hide_parameters=True,
                         connect_args={"options": "-c statement_timeout=0 -c lock_timeout=60s",
                                       "application_name": "superplanner-migrate", "connect_timeout": 10})


@contextmanager
def _locked_connection(url: str) -> Iterator[Connection]:
    """A connection for schema work holding the session advisory lock for its lifetime."""
    eng = _migration_engine(url)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
            conn.commit()
            try:
                yield conn
            finally:
                try:
                    conn.rollback()
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
                    conn.commit()
                except Exception:  # pragma: no cover - the lock dies with the connection anyway
                    log.warning("could not release the migration advisory lock", exc_info=True)
    finally:
        eng.dispose()


# ---------------------------------------------------------------- state

def _our_tables() -> set[str]:
    from .api.db import load_all_models

    return set(load_all_models().tables)


def _state(conn: Connection) -> tuple[SchemaState, str | None]:
    names = set(inspect(conn).get_table_names())
    if "alembic_version" in names:
        rev = _current_revision(conn)
        if rev is not None:
            if rev == HEAD:
                return "current", rev
            if rev in known_revisions():
                return "behind", rev
            return "ahead", rev
    if names & _our_tables():
        return "unknown", None
    return "empty", None


def _url_of(obj: Any) -> str:
    if isinstance(obj, str):
        return normalize_database_url(obj)
    if hasattr(obj, "database_url"):
        return obj.database_url
    return obj.url


def schema_state(db_or_url: Any) -> SchemaState:
    """State of a database (`Database`, `Settings` or URL)."""
    eng = _migration_engine(_url_of(db_or_url))
    try:
        with eng.connect() as conn:
            return _state(conn)[0]
    finally:
        eng.dispose()


def current_revision(db_or_url: Any) -> str | None:
    eng = _migration_engine(_url_of(db_or_url))
    try:
        with eng.connect() as conn:
            names = set(inspect(conn).get_table_names())
            return _current_revision(conn) if "alembic_version" in names else None
    finally:
        eng.dispose()


def _not_at_head(state: SchemaState, rev: str | None) -> SchemaError:
    if state == "ahead":
        return SchemaError(f"Database schema is at {rev}, which is newer than this code ({HEAD}). "
                           "Upgrade the application or restore a matching backup.")
    if state == "unknown":
        return SchemaError("The database has SuperPlanner tables but no Alembic revision; it was not created by "
                           f"`{UPGRADE_COMMAND}`. Restore a backup or use an empty database.")
    at = "empty (no schema)" if state == "empty" else rev
    return SchemaError(f"Database schema is {at}, code needs {HEAD}. Run: {UPGRADE_COMMAND} "
                       "(as the owner role, MIGRATION_DATABASE_URL or DATABASE_URL), or set AUTO_MIGRATE=true "
                       "for local development.")


# ---------------------------------------------------------------- local user

def ensure_local_user_conn(conn: Connection) -> None:
    """Idempotent, race-free insert of `usr_local` (DML only: works with the restricted app role)."""
    users = sa.table("users", sa.column("id", sa.String), sa.column("email", sa.String),
                     sa.column("display_name", sa.String), sa.column("password_hash", sa.Text),
                     sa.column("is_local", sa.Boolean), sa.column("disabled", sa.Boolean),
                     sa.column("created_at", sa.DateTime(timezone=True)),
                     sa.column("updated_at", sa.DateTime(timezone=True)))
    if conn.execute(sa.select(users.c.id).where(users.c.id == "usr_local")).first() is not None:
        return
    now = datetime.now(UTC)
    conn.execute(pg_insert(users).values(id="usr_local", email=None, display_name="Local user", password_hash=None,
                                         is_local=True, disabled=False, created_at=now, updated_at=now)
                 .on_conflict_do_nothing(index_elements=["id"]))


# ---------------------------------------------------------------- startup check / upgrade

def ensure_schema(db_or_url: Any, settings: Settings | None = None) -> SchemaState:
    """Startup schema check. Returns the state found *before* any change.

    current                      -> local user ensured (DML on the app connection)
    anything else, AUTO_MIGRATE  -> `upgrade` on the owner URL (settings.schema_url), then as `current`
    anything else                -> SchemaError naming `python -m superplanner.migrate upgrade`
    """
    url = _url_of(db_or_url)
    eng = _migration_engine(url)
    try:
        with eng.connect() as conn:
            state, rev = _state(conn)
            conn.rollback()
            if state != "current":
                if settings is None or not settings.db_auto_migrate or state in ("ahead", "unknown"):
                    raise _not_at_head(state, rev)
                upgrade(settings.schema_url)
                state_after, rev_after = _state(conn)
                conn.rollback()
                if state_after != "current":   # pragma: no cover - MIGRATION_DATABASE_URL names another database
                    raise _not_at_head(state_after, rev_after)
            with conn.begin():
                ensure_local_user_conn(conn)
            return state
    finally:
        eng.dispose()


def upgrade(db_or_url: Any) -> SchemaState:
    """Bring a database to head with the real Alembic chain (the CLI `upgrade`). Returns the state before."""
    url = _url_of(db_or_url)
    with _locked_connection(url) as conn:
        state, rev = _state(conn)
        conn.rollback()
        if state in ("ahead", "unknown"):
            raise _not_at_head(state, rev)
        with conn.begin():
            if state != "current":
                _upgrade(conn, "head")
            ensure_local_user_conn(conn)
        if state != "current":
            log.info("schema.migrated: %s -> %s", rev or "empty", HEAD)
        return state


def run_alembic_upgrade(url: str, target: str = "head") -> None:
    """Run the migration chain to `target` (tests and the Postgres test template use it)."""
    with _locked_connection(url) as conn:
        with conn.begin():
            _upgrade(conn, target)


def run_alembic_downgrade(url: str, target: str = "base") -> None:
    with _locked_connection(url) as conn:
        with conn.begin():
            _downgrade(conn, target)


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m superplanner.migrate", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["upgrade", "current", "check"])
    parser.add_argument("--url", help="database URL (default: MIGRATION_DATABASE_URL, else DATABASE_URL)")
    args = parser.parse_args(argv)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        url = resolve_migration_url(args.url)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "upgrade":
            before = upgrade(url)
            print(f"schema at {HEAD} (was {before})")
            return 0
        if args.command == "current":
            print(f"{schema_state(url)} {current_revision(url) or '-'}")
            return 0
        state = schema_state(url)
        if state == "current":
            print(f"current {HEAD}")
            return 0
        print(str(_not_at_head(state, current_revision(url))), file=sys.stderr)
        return 3
    except SchemaError as exc:
        print(f"schema error: {exc}", file=sys.stderr)
        return 3
    except sa.exc.OperationalError as exc:
        print(f"cannot reach the database: {str(exc.orig or exc).splitlines()[0]}", file=sys.stderr)
        return 3


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
