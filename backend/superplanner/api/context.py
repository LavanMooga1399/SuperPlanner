"""Per-app runtime context: settings, database, executor and the process-wide write lock (A.13 rule 7)."""

from __future__ import annotations

import threading

from fastapi import Request

from .config import Settings
from .db import Database
from .executor import RunExecutor

# Check-then-write sequences (one active run, one approved schedule, If-Match) run under this lock
# AND inside one DB transaction. Process-wide on purpose (the MVP is a single process).
WRITE_LOCK = threading.RLock()


class AppContext:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.database_url)
        self._executor: RunExecutor | None = None
        self._started = False
        self._start_lock = threading.Lock()

    def start(self) -> None:
        """Idempotent: create tables, recover interrupted runs, start the executor."""
        with self._start_lock:
            if self._started:
                return
            from .finance import db_models as _finance_db_models  # noqa: F401  (registers finance tables)

            self.db.create_all()
            from .finance import run_service as finance_run_service
            from .services import run_service

            run_service.recover_interrupted_runs(self)
            finance_run_service.recover_interrupted_runs(self)
            self._executor = RunExecutor(self.settings.run_workers)
            self._started = True

    @property
    def executor(self) -> RunExecutor:
        self.start()
        assert self._executor is not None
        return self._executor

    def stop(self) -> None:
        with self._start_lock:
            if self._executor is not None:
                self._executor.shutdown()
                self._executor = None
            self._started = False
            self.db.dispose()


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    ctx.start()
    return ctx
