"""Engine and session factories (ARCHITECTURE 13, PHASE2B 3.1). PostgreSQL (psycopg 3) only.

QueuePool with configurable size/overflow/timeout/recycle and pre-ping, per-connection `statement_timeout`,
`lock_timeout`, `connect_timeout` and `application_name`; JSON serialised with `allow_nan=False` (JSONB rejects
NaN/Infinity; failing early gives a clear error instead of a driver error). TLS settings (`sslmode`,
`sslrootcert`, ...) are passed through untouched in the URL query string (docs/DEPLOY.md "TLS").
The schema is never created here: it comes from the Alembic chain (`python -m superplanner.migrate upgrade`).

M6-DESIGN 4.2 (optional read replica, `DATABASE_READ_URL`): `read()` serves from the replica only inside
`replica_reads(ctx)` (dashboards, digests, KPI / trace / export reads, assistant read tools) and only when (a) the
replica's lag (checked at most every 2 s) is <= `REPLICA_MAX_LAG_SECONDS`, (b) the request carries no recent-write
marker (`sp_rw` cookie / `SP-Read-After` header, set for 15 s after every unsafe request by
`ReadAfterWriteMiddleware`) and (c) the replica answers; else the primary (a replica failure is logged at most once
per minute). `write()` and everything outside `replica_reads` always use the primary. Without `DATABASE_READ_URL`
nothing changes.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
from typing import Any, Callable

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import validate_database_url

log = logging.getLogger("superplanner.db")
RW_COOKIE = "sp_rw"
RW_HEADER = "SP-Read-After"
RW_SECONDS = 15
LAG_CACHE_SECONDS = 2.0
_replica_ok: ContextVar[bool] = ContextVar("sp_replica_ok", default=False)
_recent_write: ContextVar[bool] = ContextVar("sp_recent_write", default=False)
_read_source: ContextVar[list[str] | None] = ContextVar("sp_read_source", default=None)
#: M6 review M4: lag in seconds, NULL = unknown (-> primary). A standby whose WAL receiver is not streaming is
#: unknown; caught up (receive = replay) counts as 0 only while the primary's keepalives arrive (the walsender's
#: messages are the heartbeat, `last_msg_receipt_time` within :hb seconds); else the replay timestamp's age.
LAG_SQL = ("SELECT CASE WHEN NOT pg_is_in_recovery() THEN 0::float8 "
           "WHEN NOT EXISTS (SELECT 1 FROM pg_stat_wal_receiver WHERE status = 'streaming') THEN NULL "
           "WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() AND (SELECT max(now() - last_msg_receipt_time) "
           "FROM pg_stat_wal_receiver) <= make_interval(secs => :hb) THEN 0::float8 "
           "ELSE EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp())::float8 END")
HEARTBEAT_SECONDS = 30.0


@contextmanager
def replica_reads(ctx: Any = None) -> Iterator[list[str]]:
    """Mark the block as replica-safe (4.2 list). Yields a list that collects the sources used (`replica`/`primary`)."""
    sources: list[str] = []
    t1, t2 = _replica_ok.set(True), _read_source.set(sources)
    try:
        yield sources
    finally:
        _replica_ok.reset(t1)
        _read_source.reset(t2)


@contextmanager
def primary_only() -> Iterator[None]:
    """Inside a replica-safe block: reads that must see the primary (staleness / If-Match)."""
    t = _replica_ok.set(False)
    try:
        yield
    finally:
        _replica_ok.reset(t)


def mark_recent_write(value: bool = True) -> Any:
    return _recent_write.set(value)


class Replica:
    """The read replica of a `Database`: its engine, the cached lag and the fallback log throttle."""

    def __init__(self, url: str, max_lag_seconds: float, engine_kw: dict[str, Any]):
        self.engine: Engine = create_engine(url, **engine_kw)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.max_lag = float(max_lag_seconds)
        self._lag: tuple[float, float | None] = (0.0, None)      # (checked monotonic, lag seconds | None = error)
        self._lock = threading.Lock()
        self._last_error_log = 0.0
        #: tests: replaces the lag query (returns seconds)
        self.lag_probe: Callable[[], float] | None = None

    def lag(self) -> float | None:
        now = time.monotonic()
        checked, value = self._lag
        if now - checked < LAG_CACHE_SECONDS and checked > 0:
            return value
        with self._lock:
            checked, value = self._lag
            if now - checked < LAG_CACHE_SECONDS and checked > 0:
                return value
            try:
                if self.lag_probe is not None:
                    raw = self.lag_probe()
                else:
                    with self.engine.connect() as c:
                        raw = c.execute(text(LAG_SQL), {"hb": HEARTBEAT_SECONDS}).scalar()
                value = None if raw is None else max(0.0, float(raw))
            except Exception as exc:  # noqa: BLE001 - any replica failure means "use the primary"
                self.log_failure(exc)
                value = None
            self._lag = (now, value)
            return value

    def reset(self) -> None:
        self._lag = (0.0, None)

    def log_failure(self, exc: BaseException) -> None:
        now = time.monotonic()
        if now - self._last_error_log >= 60.0:
            self._last_error_log = now
            log.warning("replica unavailable, reading from the primary (%s)", exc.__class__.__name__)


def _count(result: str) -> None:
    try:
        from ...obs.http_metrics import REPLICA_READS

        REPLICA_READS.labels(result=result).inc()
    except Exception:  # pragma: no cover - metrics never break reads
        pass


class Database:
    is_postgres = True     # PostgreSQL only (kept for callers that still ask)

    def __init__(self, url: str, *, pool_size: int = 10, max_overflow: int = 10, pool_timeout: float = 30.0,
                 statement_timeout_ms: int = 30000, lock_timeout_ms: int = 10000, connect_timeout_seconds: int = 10,
                 pool_recycle_seconds: int = 1800, pool_pre_ping: bool = True, service: str = "api",
                 read_url: str | None = None, replica_max_lag_seconds: float = 5.0):
        url = validate_database_url(url)
        self.url = url
        options = f"-c statement_timeout={int(statement_timeout_ms)} -c lock_timeout={int(lock_timeout_ms)}"
        # hide_parameters: bound values (password hashes, session/CSRF tokens, emails) never reach the error log.
        kw: dict[str, Any] = dict(
            hide_parameters=True, pool_size=pool_size, max_overflow=max_overflow, pool_timeout=pool_timeout,
            pool_pre_ping=pool_pre_ping, pool_recycle=pool_recycle_seconds,
            json_serializer=partial(json.dumps, allow_nan=False),
            connect_args={"options": options, "application_name": f"superplanner-{service}",
                          "connect_timeout": int(connect_timeout_seconds)})
        self.engine: Engine = create_engine(url, **kw)
        self._read = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._write = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.replica: Replica | None = None
        if read_url:
            rkw = dict(kw, connect_args=dict(kw["connect_args"], application_name=f"superplanner-{service}-ro",
                                             connect_timeout=min(5, int(connect_timeout_seconds))))
            self.replica = Replica(validate_database_url(read_url, "DATABASE_READ_URL"), replica_max_lag_seconds,
                                   rkw)

    @classmethod
    def from_settings(cls, settings: Any, service: str = "api") -> "Database":
        db = cls._from(settings, service)
        from ..audit_chain import configure                    # keyed audit chain (M5-DESIGN 7, 15.WP-S)

        configure(db.engine, list(getattr(settings, "secrets_keys", None) or []))
        return db

    @classmethod
    def _from(cls, settings: Any, service: str) -> "Database":
        return cls(settings.database_url, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
                   pool_timeout=settings.db_pool_timeout_seconds,
                   statement_timeout_ms=settings.db_statement_timeout_ms,
                   lock_timeout_ms=getattr(settings, "db_lock_timeout_ms", 10000),
                   connect_timeout_seconds=getattr(settings, "db_connect_timeout_seconds", 10),
                   pool_recycle_seconds=getattr(settings, "db_pool_recycle_seconds", 1800),
                   pool_pre_ping=getattr(settings, "db_pool_pre_ping", True), service=service,
                   read_url=getattr(settings, "database_read_url", None),
                   replica_max_lag_seconds=getattr(settings, "replica_max_lag_seconds", 5.0))

    @property
    def session_factories(self) -> tuple[sessionmaker, ...]:
        if self.replica is not None:
            return self._read, self._write, self.replica.factory
        return self._read, self._write

    def _replica_session(self) -> Session | None:
        """A replica session when this read may and can use it (4.2 a-c), else None (-> primary)."""
        rep = self.replica
        sources = _read_source.get()
        if rep is None or not _replica_ok.get():
            return None
        if _recent_write.get():
            _count("primary_recent_write")
            if sources is not None:
                sources.append("primary")
            return None
        lag = rep.lag()
        if lag is None or lag > rep.max_lag:
            _count("primary_lag" if lag is not None else "primary_error")
            if sources is not None:
                sources.append("primary")
            return None
        s = rep.factory()
        try:
            s.connection()
        except Exception as exc:  # noqa: BLE001 - replica failure -> primary
            s.close()
            rep.log_failure(exc)
            rep.reset()
            _count("primary_error")
            if sources is not None:
                sources.append("primary")
            return None
        _count("replica")
        if sources is not None:
            sources.append("replica")
        return s

    @contextmanager
    def read(self) -> Iterator[Session]:
        rs = self._replica_session() if self.replica is not None else None
        with (rs if rs is not None else self._read()) as s:
            try:
                yield s
            finally:
                s.rollback()

    @contextmanager
    def primary_read(self) -> Iterator[Session]:
        with self._read() as s:
            try:
                yield s
            finally:
                s.rollback()

    def in_recovery(self) -> bool:
        """4.2 item 3: the write pool points at a standby (read-only) server."""
        with self.engine.connect() as c:
            return bool(c.execute(text("SELECT pg_is_in_recovery()")).scalar())

    def invalidate(self) -> None:
        """4.2 item 2 (failover): drop pooled connections so the next checkout reconnects (to the new leader)."""
        try:
            self.engine.dispose(close=False)
        except Exception:  # pragma: no cover
            pass
        if self.replica is not None:
            self.replica.reset()

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
        if self.replica is not None:
            self.replica.engine.dispose()
