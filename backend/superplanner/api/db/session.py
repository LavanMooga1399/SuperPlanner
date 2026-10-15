"""Engine and session factories (ARCHITECTURE 13).

SQLite: WAL + foreign keys per connection. Write sessions start with `BEGIN IMMEDIATE`, so a
read-then-write sequence never fails with SQLITE_BUSY when another thread committed in between
(deferred transactions cannot wait for the write lock in WAL mode); readers stay lock-free.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


class Database:
    def __init__(self, url: str):
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        kwargs: dict = {}
        if self.is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        self.engine: Engine = create_engine(url, **kwargs)
        if self.is_sqlite:
            self._install_sqlite_listeners(self.engine)
            write_bind = self.engine.execution_options(sqlite_begin="IMMEDIATE")
        else:
            write_bind = self.engine
        self._read = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._write = sessionmaker(bind=write_bind, expire_on_commit=False)

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
