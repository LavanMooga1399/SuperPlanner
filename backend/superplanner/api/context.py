"""Per-app runtime context: settings, database, executor, job queue and the write guard (A.13 rule 7, PHASE2B 2.12).

`write_guard()` is a no-op kept for call sites: row locks (`FOR NO KEY UPDATE` on the parent plan/problem and the
run) and partial unique indexes give the cross-process guarantees on PostgreSQL. `WRITE_LOCK` stays exported (unused)
for old imports.

Schema: `start()` never creates tables. It verifies the database is at `migrate.HEAD` and raises `SchemaError`
("Run: python -m superplanner.migrate upgrade") otherwise, unless AUTO_MIGRATE=true, in which case it upgrades first
using MIGRATION_DATABASE_URL (owner role; fallback DATABASE_URL).

`AppContext.start()` runs as a whole in `system_scope()` (review R9): it may run lazily inside the first request
(TestClient without `with`), where the fail-closed ownership rule would otherwise reject its recovery queries.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import weakref
from typing import Any, ContextManager

from fastapi import Request

from .config import Settings
from .db import Database
from .db.ownership import install as install_ownership
from .db.ownership import system_scope
from .executor import RunExecutor

log = logging.getLogger(__name__)

# Unused since PostgreSQL-only (row locks + unique indexes); exported for old imports.
WRITE_LOCK = threading.RLock()

JOB_KINDS = ("solver_run", "finance_run")
_LIVE: "weakref.WeakSet[AppContext]" = weakref.WeakSet()   # started contexts (test harness: stop leftovers)


class AppContext:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database.from_settings(settings, service="api")
        install_ownership(self.db, single_user=settings.single_user)
        self._executor: RunExecutor | None = None
        self._jobs: Any = None
        self._started = False
        self._start_lock = threading.Lock()
        self._prune_thread: threading.Thread | None = None
        self._prune_stop = threading.Event()

    def write_guard(self) -> ContextManager[Any]:
        """No-op: PostgreSQL row locks + partial unique indexes serialise check-then-write sequences."""
        return contextlib.nullcontext()

    def start(self) -> None:
        """Idempotent: schema check (or AUTO_MIGRATE upgrade), local user, recovery, job backend (PHASE2B 2.2).

        inline: interrupted runs -> failed (+ their jobs), executor + `InlineQueue`.
        queue:  the API never fails runs whose job holds a queue lease (workers own them); orphan runs without a
                job row, and jobs left `running` with no lease expiry by a dead inline-backend process, are failed
                (`common.queue_start_recovery`). `PgQueue` with optional embedded worker threads (`WORKER_EMBEDDED`)."""
        with self._start_lock:
            if self._started:
                return
            with system_scope():
                from superplanner import migrate

                self.settings.log_warnings()
                migrate.ensure_schema(self.db, self.settings)
                if self.settings.job_backend == "queue":
                    from superplanner.jobs import common
                    from superplanner.jobs.pg import PgQueue

                    common.queue_start_recovery(self)
                    jobs: Any = PgQueue(self)
                else:
                    from superplanner.jobs.inline import InlineQueue

                    from .finance import run_service as finance_run_service
                    from .services import run_service

                    run_service.recover_interrupted_runs(self)
                    finance_run_service.recover_interrupted_runs(self)
                    self._executor = RunExecutor(self.settings.run_workers)
                    jobs = InlineQueue(self)
                    if self.settings.auth_mode == "accounts":
                        self._start_auth_prune()
                self._jobs = jobs
                self._started = True
                _LIVE.add(self)
                jobs.start()

    def _start_auth_prune(self) -> None:
        """Inline backend + accounts: nothing else prunes sessions / rate-limit buckets (queue mode: worker
        maintenance), so a daemon thread does it every AUTH_PRUNE_INTERVAL_SECONDS (fix round)."""
        self._prune_stop = threading.Event()
        t = threading.Thread(target=self._auth_prune_loop, args=(self._prune_stop,), name="sp-auth-prune",
                             daemon=True)
        self._prune_thread = t
        t.start()

    def _auth_prune_loop(self, stop: threading.Event) -> None:
        from datetime import UTC, datetime

        from .auth.maintenance import prune_auth_tables

        interval = float(self.settings.auth_prune_interval_seconds)
        while not stop.wait(interval):
            try:
                with system_scope(), self.db.write() as s:
                    counts = prune_auth_tables(s, datetime.now(UTC))
                if any(counts.values()):
                    log.info("auth prune: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
            except Exception:
                if stop.is_set():
                    return
                log.warning("auth prune failed; retrying in %.0f s", interval, exc_info=True)

    def _stop_auth_prune(self) -> None:
        t, self._prune_thread = self._prune_thread, None
        self._prune_stop.set()
        if t is not None:
            t.join(timeout=10)

    @property
    def is_queue(self) -> bool:
        return self.settings.job_backend == "queue"

    @property
    def executor(self) -> RunExecutor:
        """The in-process executor (inline backend only)."""
        self.start()
        if self._executor is None:
            raise RuntimeError("no in-process executor in queue mode")
        return self._executor

    @property
    def jobs(self) -> Any:
        """The `JobQueue` (`InlineQueue` or `PgQueue`)."""
        self.start()
        assert self._jobs is not None
        return self._jobs

    def stop(self) -> None:
        # Stop the backend outside the start lock: handlers still running during the grace period may use
        # `ctx.jobs` (cancel paths), which must not block on `start()`.
        with self._start_lock:
            jobs, executor = self._jobs, self._executor
        if jobs is not None:
            jobs.stop(self.settings.worker_shutdown_grace_seconds)
        if executor is not None:
            executor.shutdown()
        self._stop_auth_prune()
        with self._start_lock:
            self._jobs = None
            self._executor = None
            self._started = False
            _LIVE.discard(self)
            self.db.dispose()


def live_contexts() -> list["AppContext"]:
    """Started, not yet stopped contexts of this process (the test harness stops leftovers before dropping DBs)."""
    return list(_LIVE)


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    ctx.start()
    return ctx
