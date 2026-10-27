"""Engine and session factories (ARCHITECTURE 13, PHASE2B 3.1). PostgreSQL (psycopg 3) only.

QueuePool with configurable size/overflow/timeout/recycle and pre-ping, per-connection `statement_timeout`,
`lock_timeout`, `connect_timeout` and `application_name`; JSON serialised with `allow_nan=False` (JSONB rejects
NaN/Infinity; failing early gives a clear error instead of a driver error). TLS settings (`sslmode`,
`sslrootcert`, ...) are passed through untouched in the URL query string (docs/DEPLOY.md "TLS").
The schema is never created here: it comes from the Alembic chain (`python -m superplanner.migrate upgrade`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import validate_database_url


class Database:
    is_postgres = True     # PostgreSQL only (kept for callers that still ask)

    def __init__(self, url: str, *, pool_size: int = 10, max_overflow: int = 10, pool_timeout: float = 30.0,
                 statement_timeout_ms: int = 30000, lock_timeout_ms: int = 10000, connect_timeout_seconds: int = 10,
                 pool_recycle_seconds: int = 1800, pool_pre_ping: bool = True, service: str = "api"):
        url = validate_database_url(url)
        self.url = url
        options = f"-c statement_timeout={int(statement_timeout_ms)} -c lock_timeout={int(lock_timeout_ms)}"
        # hide_parameters: bound values (password hashes, session/CSRF tokens, emails) never reach the error log.
        self.engine: Engine = create_engine(
            url, hide_parameters=True, pool_size=pool_size, max_overflow=max_overflow, pool_timeout=pool_timeout,
            pool_pre_ping=pool_pre_ping, pool_recycle=pool_recycle_seconds,
            json_serializer=partial(json.dumps, allow_nan=False),
            connect_args={"options": options, "application_name": f"superplanner-{service}",
                          "connect_timeout": int(connect_timeout_seconds)})
        self._read = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._write = sessionmaker(bind=self.engine, expire_on_commit=False)

    @classmethod
    def from_settings(cls, settings: Any, service: str = "api") -> "Database":
        return cls(settings.database_url, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
                   pool_timeout=settings.db_pool_timeout_seconds,
                   statement_timeout_ms=settings.db_statement_timeout_ms,
                   lock_timeout_ms=getattr(settings, "db_lock_timeout_ms", 10000),
                   connect_timeout_seconds=getattr(settings, "db_connect_timeout_seconds", 10),
                   pool_recycle_seconds=getattr(settings, "db_pool_recycle_seconds", 1800),
                   pool_pre_ping=getattr(settings, "db_pool_pre_ping", True), service=service)

    @property
    def session_factories(self) -> tuple[sessionmaker, sessionmaker]:
        return self._read, self._write

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
