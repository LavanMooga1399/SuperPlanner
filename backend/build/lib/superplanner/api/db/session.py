"""Engine and session factories (ARCHITECTURE 13, PHASE2B 3.1).

SQLite: WAL + foreign keys per connection. Write sessions start with `BEGIN IMMEDIATE`, so a
read-then-write sequence never fails with SQLITE_BUSY when another thread committed in between
(deferred transactions cannot wait for the write lock in WAL mode); readers stay lock-free.

PostgreSQL (psycopg 3, imported lazily by SQLAlchemy only when such a URL is used): QueuePool with pre-ping,
statement/lock timeouts and `application_name` per connection, JSON serialised with `allow_nan=False` (JSONB
rejects NaN/Infinity; failing early gives a clear error instead of a driver error).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import is_postgres_url, normalize_database_url
from .models import Base


class Database:
    def __init__(self, url: str, *, pool_size: int = 10, max_overflow: int = 10, pool_timeout: float = 30.0,
                 statement_timeout_ms: int = 30000, service: str = "api"):
        url = normalize_database_url(url)
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        self.is_postgres = is_postgres_url(url)
        kwargs: dict[str, Any] = {}
        if self.is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        elif self.is_postgres:
            options = f"-c statement_timeout={int(statement_timeout_ms)} -c lock_timeout=10000"
            kwargs.update(pool_size=pool_size, max_overflow=max_overflow, pool_timeout=pool_timeout,
                          pool_pre_ping=True, pool_recycle=1800,
                          json_serializer=partial(json.dumps, allow_nan=False),
                          connect_args={"options": options, "application_name": f"superplanner-{service}"})
        self.engine: Engine = create_engine(url, **kwargs)
        if self.is_sqlite:
            self._install_sqlite_listeners(self.engine)
            write_bind = self.engine.execution_options(sqlite_begin="IMMEDIATE")
        else:
            write_bind = self.engine
        self._read = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._write = sessionmaker(bind=write_bind, expire_on_commit=False)

    @classmethod
    def from_settings(cls, settings: Any, service: str = "api") -> "Database":
        return cls(settings.database_url, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
                   pool_timeout=settings.db_pool_timeout_seconds,
                   statement_timeout_ms=settings.db_statement_timeout_ms, service=service)

    @property
    def session_factories(self) -> tuple[sessionmaker, sessionmaker]:
        return self._read, self._write

    @staticmethod
    def _install_sqlite_listeners(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn, _record):  # noqa: ANN001
            dbapi_conn.isolation_level = None  # we emit BEGIN ourselves (below)
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        @event.listens_for(engine, "begin")
        def _on_begin(conn):  # noqa: ANN001
            mode = conn.get_execution_options().get("sqlite_begin", "DEFERRED")
            conn.exec_driver_sql(f"BEGIN {mode}")

    def create_all(self) -> None:
        """Tests and `migrate.ensure_schema` (empty databases) only; normal starts go through `ensure_schema`."""
        from . import load_all_models

        load_all_models()
        Base.metadata.create_all(self.engine)

    @contextmanager
    def read(self) -> Iterator[Session]:
        with self._read() as s:
            try:
                yield s
            finally:
                s.rollback()

    @contextmanager
    def write(self) -> Iterator[Session]:
        """One transaction: commit on success, roll back everything on any exception."""
        with self._write() as s:
            try:
                yield s
                s.commit()
            except BaseException:
                s.rollback()
                raise

    def ping(self) -> bool:
        try:
            with self.engine.connect() as c:
                c.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def dispose(self) -> None:
        self.engine.dispose()
