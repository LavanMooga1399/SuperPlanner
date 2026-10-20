"""Per-app runtime context: settings, database, executor, job queue and the write guard (A.13 rule 7, PHASE2B 2.12).

`write_guard()` replaces the process-wide `WRITE_LOCK`: on SQLite it is that RLock (behaviour unchanged), on
PostgreSQL a no-op - there, row locks (`FOR NO KEY UPDATE` on the parent plan/problem and the run) and partial
unique indexes give the cross-process guarantees. `WRITE_LOCK` stays exported as an alias for one release.

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

# Check-then-write sequences (one active run, one approved schedule, If-Match) run under this lock AND inside one DB
# transaction on SQLite. Kept as an alias; new code uses `ctx.write_guard()`.
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

    def write_guard(self) -> ContextManager[Any]:
        """SQLite: the process-wide RLock (unchanged behaviour). PostgreSQL: no-op (row locks + indexes)."""
        return WRITE_LOCK if self.db.is_sqlite else contextlib.nullcontext()

    def start(self) -> None:
        """Idempotent: schema (create/upgrade), local user, recovery, job backend (PHASE2B 2.2).

        inline: interrupted runs -> failed (+ their jobs), executor + `InlineQueue`.
        queue:  the API never fails runs that have a job (workers own them); only orphan runs without a job row
                are failed. `PgQueue` with optional embedded worker threads (`WORKER_EMBEDDED`)."""
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

                    common.fail_orphan_runs(self)
                    jobs: Any = PgQueue(self)
                else:
                    from superplanner.jobs.inline import InlineQueue

                    from .finance import run_service as finance_run_service
                    from .services import run_service

                    run_service.recover_interrupted_runs(self)
                    finance_run_service.recover_interrupted_runs(self)
                    self._executor = RunExecutor(self.settings.run_workers)
                    jobs = InlineQueue(self)
                self._jobs = jobs
                self._started = True
                _LIVE.add(self)
                jobs.start()

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
