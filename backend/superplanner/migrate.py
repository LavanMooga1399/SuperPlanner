"""Schema management (PHASE2B 3.4): startup `ensure_schema`, the legacy SQLite upgrade path and a small CLI.

    python -m superplanner.migrate upgrade      [--url URL]   bring the database to head (backup first on SQLite)
    python -m superplanner.migrate current      [--url URL]   print the schema state and revision
    python -m superplanner.migrate check        [--url URL]   exit 0 if at head, else 3
    python -m superplanner.migrate stamp-legacy [--url URL]   mark a legacy (pre-Alembic) database as 0001_initial

States: `empty` (none of our tables), `legacy` (our tables, no Alembic revision), `behind`, `current`, `ahead`.

Safety rules:
- SQLite migrations run on their own engine (no `Database` connect listener) with `PRAGMA foreign_keys=OFF` set
  outside any transaction, inside ONE explicit transaction, followed by `PRAGMA foreign_key_check`: Alembic batch
  mode rebuilds tables, and with foreign keys ON `DROP TABLE problems` would cascade-delete every child row (R1).
- Before upgrading an existing SQLite file it is copied with the SQLite online backup API to
  `<db>.bak-<rev>-<UTC yyyymmddHHMMSS>` - never a plain file copy, which can miss WAL content (R2).
- PostgreSQL: everything runs under `pg_advisory_lock(727001)` (concurrently starting instances migrate once) with
  `statement_timeout = 0` and `lock_timeout = '60s'` (the API's 30 s statement timeout would abort index builds).
Exit codes: 3 = schema problem (`SchemaError`), 2 = configuration problem.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy import Connection, Engine, create_engine, event, inspect, pool, text
from sqlalchemy.engine import make_url

from .api.config import ConfigError, Settings, normalize_database_url

log = logging.getLogger("superplanner.migrate")
# Alembic logs several INFO lines per connection ("Context impl ...", plugin setup); our own `schema.migrated`
# line is the one that matters. Only applied if nobody configured the alembic logger explicitly.
if logging.getLogger("alembic").level == logging.NOTSET:
    logging.getLogger("alembic").setLevel(logging.WARNING)

HEAD = "0003_mfg"
BASE_REVISION = "0001_initial"
ADVISORY_LOCK_KEY = 727001
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
SchemaState = Literal["empty", "legacy", "behind", "current", "ahead"]


class SchemaError(RuntimeError):
    """The database schema cannot be used or upgraded automatically (exit code 3)."""

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


@lru_cache(maxsize=1)
def initial_module() -> Any:
    """The frozen 0001 revision module (its `build_metadata()` defines the legacy tables)."""
    path = MIGRATIONS_DIR / "versions" / "0001_initial.py"
    spec = importlib.util.spec_from_file_location("superplanner_migration_0001", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def known_revisions() -> set[str]:
    return {r.revision for r in _script().walk_revisions()}


def _current_revision(conn: Connection) -> str | None:
    from alembic.migration import MigrationContext

    return MigrationContext.configure(conn).get_current_revision()


def _stamp(conn: Connection, revision: str) -> None:
    from alembic.migration import MigrationContext

    mc = MigrationContext.configure(conn)
    mc.stamp(_script(), revision)


def _upgrade(conn: Connection, target: str = "head") -> None:
    from alembic import command

    command.upgrade(_alembic_config(conn), target)


def _downgrade(conn: Connection, target: str) -> None:
    from alembic import command

    command.downgrade(_alembic_config(conn), target)


# ---------------------------------------------------------------- engines

def _migration_engine(url: str) -> Engine:
    url = normalize_database_url(url)
    if url.startswith("sqlite"):
        eng = create_engine(url, poolclass=pool.NullPool, hide_parameters=True, connect_args={"timeout": 60})

        @event.listens_for(eng, "connect")
        def _on_connect(dbapi_conn, _rec):  # noqa: ANN001
            dbapi_conn.isolation_level = None          # autocommit at driver level: we emit BEGIN ourselves
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=OFF")     # outside any transaction (inside one it is a no-op)
            cur.execute("PRAGMA busy_timeout=60000")
            cur.close()

        @event.listens_for(eng, "begin")
        def _on_begin(conn):  # noqa: ANN001
            conn.exec_driver_sql("BEGIN IMMEDIATE")

        return eng
    return create_engine(url, poolclass=pool.NullPool, hide_parameters=True,
                         connect_args={"options": "-c statement_timeout=0 -c lock_timeout=60s",
                                       "application_name": "superplanner-migrate"})


@contextmanager
def _locked_connection(url: str) -> Iterator[Connection]:
    """A connection for schema work; on PostgreSQL holding the session advisory lock for its lifetime."""
    eng = _migration_engine(url)
    try:
        with eng.connect() as conn:
            pg = conn.dialect.name == "postgresql"
            if pg:
                conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
                conn.commit()
            try:
                yield conn
            finally:
                if pg:
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
    if "problems" in names:
        return "legacy", None
    if names & _our_tables():
        return "legacy", None   # some of our tables but no `problems`: _check_legacy explains the problem
    return "empty", None


def schema_state(db_or_url: Any) -> SchemaState:
    """State of a database (`Database`, `Settings` or URL)."""
    url = _url_of(db_or_url)
    eng = _migration_engine(url)
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


def _url_of(obj: Any) -> str:
    if isinstance(obj, str):
        return normalize_database_url(obj)
    if hasattr(obj, "database_url"):
        return obj.database_url
    return obj.url


# ---------------------------------------------------------------- legacy handling

def _check_legacy(conn: Connection) -> list[str]:
    """Validate a legacy database against the frozen 0001 tables; returns the missing 0001 tables."""
    md = initial_module().build_metadata()
    expected = set(md.tables)
    insp = inspect(conn)
    names = set(insp.get_table_names()) - {"alembic_version"}
    unknown = sorted(n for n in names if n not in expected and not n.startswith("_alembic_tmp_"))
    problems: list[str] = []
    if "problems" not in names:
        problems.append("the table 'problems' is missing")
    if unknown:
        problems.append(f"unknown tables: {', '.join(unknown)}")
    for name in sorted(names & expected):
        have = {c["name"] for c in insp.get_columns(name)}
        missing = [c.name for c in md.tables[name].columns if c.name not in have]
        if missing:
            problems.append(f"table {name!r} lacks columns: {', '.join(missing)}")
    if problems:
        raise SchemaError("The database does not look like a SuperPlanner database that can be upgraded: "
                          + "; ".join(problems) + ".")
    return sorted(expected - names)


def _create_missing_legacy_tables(conn: Connection, missing: list[str]) -> None:
    if not missing:
        return
    md = initial_module().build_metadata()
    md.create_all(conn, tables=[md.tables[n] for n in missing])
    log.info("created %d missing legacy table(s): %s", len(missing), ", ".join(missing))


# ---------------------------------------------------------------- backups

def sqlite_path(url: str) -> Path | None:
    u = make_url(normalize_database_url(url))
    if u.get_backend_name() != "sqlite":
        return None
    db = u.database
    if not db or db == ":memory:" or db.startswith("file:"):
        return None
    return Path(db)


def backup_sqlite(url: str, revision: str | None) -> Path | None:
    """Online backup (sqlite3 backup API) to `<db>.bak-<rev>-<UTC stamp>`; includes committed WAL content."""
    path = sqlite_path(url)
    if path is None or not path.exists():
        return None
    tag = (revision or BASE_REVISION).split("_")[0]
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    dest = path.with_name(f"{path.name}.bak-{tag}-{stamp}")
    n = 1
    while dest.exists():
        dest = path.with_name(f"{path.name}.bak-{tag}-{stamp}-{n}")
        n += 1
    src = sqlite3.connect(str(path), timeout=60)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    log.info("backed up %s to %s", path, dest)
    return dest


# ---------------------------------------------------------------- upgrade steps

def _fk_check(conn: Connection) -> None:
    if conn.dialect.name != "sqlite":
        return
    rows = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if rows:
        sample = ", ".join(f"{r[0]}(rowid {r[1]}) -> {r[2]}" for r in rows[:5])
        raise SchemaError(f"Foreign key check failed after the migration ({len(rows)} row(s): {sample}); "
                          "nothing was changed.")


def _create_fresh(conn: Connection) -> None:
    from .api.db import load_all_models

    load_all_models().create_all(conn)
    _stamp(conn, HEAD)
    ensure_local_user_conn(conn)


def _run_upgrade(conn: Connection, state: SchemaState, rev: str | None) -> None:
    """Inside the caller's transaction: legacy -> stamp 0001 (+ missing tables) -> upgrade head; behind -> head."""
    if state == "legacy":
        missing = _check_legacy(conn)
        _create_missing_legacy_tables(conn, missing)
        _stamp(conn, BASE_REVISION)
    _upgrade(conn, "head")
    _fk_check(conn)
    ensure_local_user_conn(conn)


def ensure_local_user_conn(conn: Connection) -> None:
    """Idempotent insert of `usr_local` (Core, so it works without ORM sessions or ownership hooks)."""
    users = sa.table("users", sa.column("id", sa.String), sa.column("email", sa.String),
                     sa.column("display_name", sa.String), sa.column("password_hash", sa.Text),
                     sa.column("is_local", sa.Boolean), sa.column("disabled", sa.Boolean),
                     sa.column("created_at", sa.DateTime(timezone=True)),
                     sa.column("updated_at", sa.DateTime(timezone=True)))
    if conn.execute(sa.select(users.c.id).where(users.c.id == "usr_local")).first() is None:
        now = datetime.now(UTC)
        conn.execute(users.insert().values(id="usr_local", email=None, display_name="Local user",
                                           password_hash=None, is_local=True, disabled=False, created_at=now,
                                           updated_at=now))


def ensure_schema(db_or_url: Any, settings: Settings | None = None) -> SchemaState:
    """Startup schema handling (B 3.4). Returns the state found *before* any change.

    empty   -> create_all + stamp head + local user (always; nothing to lose)
    legacy  -> (DB_AUTO_MIGRATE) SQLite backup, create missing 0001 tables, stamp 0001, upgrade head
    behind  -> (DB_AUTO_MIGRATE) SQLite backup, upgrade head
    current -> local user ensured
    ahead   -> SchemaError
    Without DB_AUTO_MIGRATE a legacy/behind database raises SchemaError naming the command to run.
    """
    url = _url_of(db_or_url)
    auto = settings.db_auto_migrate if settings is not None else not url.startswith("postgresql")
    with _locked_connection(url) as conn:
        state, rev = _state(conn)
        conn.rollback()
        if state == "current":
            with conn.begin():
                ensure_local_user_conn(conn)
            return state
        if state == "ahead":
            raise SchemaError(f"Database schema is at {rev}, which is newer than this code ({HEAD}). "
                              "Upgrade the application or restore a matching backup.")
        if state == "empty":
            with conn.begin():
                _create_fresh(conn)
            log.info("schema.migrated: created a fresh schema at %s", HEAD)
            return state
        if not auto:
            at = rev or "legacy (no revision)"
            raise SchemaError(f"Database schema is at {at}, code needs {HEAD}. "
                              "Run: python -m superplanner.migrate upgrade")
        if conn.dialect.name == "sqlite":
            if state == "legacy":
                _check_legacy(conn)   # refuse foreign files before writing a backup or touching anything
            conn.rollback()
            backup_sqlite(url, rev)
        with conn.begin():
            _run_upgrade(conn, state, rev)
        log.info("schema.migrated: %s -> %s", rev or "legacy", HEAD)
        return state


def upgrade(db_or_url: Any) -> SchemaState:
    """Bring a database to head regardless of DB_AUTO_MIGRATE (the CLI `upgrade`)."""
    url = _url_of(db_or_url)
    return ensure_schema(url, _AutoMigrate())


class _AutoMigrate:
    db_auto_migrate = True


def run_alembic_upgrade(url: str, target: str = "head") -> None:
    """Run the real migration chain (no create_all shortcut). Tests and the Postgres test template use it."""
    with _locked_connection(url) as conn:
        with conn.begin():
            _upgrade(conn, target)
            _fk_check(conn)


def run_alembic_downgrade(url: str, target: str = "base") -> None:
    with _locked_connection(url) as conn:
        with conn.begin():
            _downgrade(conn, target)
            _fk_check(conn)


def stamp_legacy(url: str) -> None:
    with _locked_connection(url) as conn:
        state, _ = _state(conn)
        conn.rollback()
        if state != "legacy":
            raise SchemaError(f"stamp-legacy needs a legacy database (state is {state}).")
        with conn.begin():
            missing = _check_legacy(conn)
            _create_missing_legacy_tables(conn, missing)
            _stamp(conn, BASE_REVISION)


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m superplanner.migrate", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["upgrade", "current", "check", "stamp-legacy"])
    parser.add_argument("--url", help="database URL (default: DATABASE_URL / Settings default)")
    args = parser.parse_args(argv)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings(database_url=args.url) if args.url else Settings()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    url = settings.database_url
    try:
        if args.command == "upgrade":
            before = upgrade(url)
            print(f"schema at {HEAD} (was {before})")
            return 0
        if args.command == "current":
            print(f"{schema_state(url)} {current_revision(url) or '-'}")
            return 0
        if args.command == "check":
            state = schema_state(url)
            if state == "current":
                print(f"current {HEAD}")
                return 0
            rev = "empty" if state == "empty" else (current_revision(url) or "legacy (no revision)")
            print(f"Database schema is at {rev}, code needs {HEAD}. Run: python -m superplanner.migrate upgrade",
                  file=sys.stderr)
            return 3
        stamp_legacy(url)
        print(f"stamped {BASE_REVISION}")
        return 0
    except SchemaError as exc:
        print(f"schema error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
