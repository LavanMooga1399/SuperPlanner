"""Background run executor (ARCHITECTURE 16): a thread pool plus one cancel event per run."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

log = logging.getLogger(__name__)


class RunExecutor:
    def __init__(self, max_workers: int = 2):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sp-run")
        self._events: dict[str, threading.Event] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()
        self._closed = False

    def cancel_event(self, run_id: str) -> threading.Event:
        with self._lock:
            ev = self._events.get(run_id)
            if ev is None:
                ev = self._events[run_id] = threading.Event()
            return ev

    def submit(self, run_id: str, job: Callable[[str, threading.Event], None]) -> Future | None:
        ev = self.cancel_event(run_id)
        with self._lock:
            if self._closed:
                return None

            def _run() -> None:
                try:
                    job(run_id, ev)
                except Exception:  # the job records failures itself; this is a last resort
                    log.exception("run %s crashed", run_id)
                finally:
                    with self._lock:
                        self._events.pop(run_id, None)
                        self._futures.pop(run_id, None)

            fut = self._pool.submit(_run)
            self._futures[run_id] = fut
            return fut

    def cancel(self, run_id: str) -> None:
        self.cancel_event(run_id).set()

    def future(self, run_id: str) -> Future | None:
        with self._lock:
            return self._futures.get(run_id)

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            for ev in self._events.values():
                ev.set()
        self._pool.shutdown(wait=True, cancel_futures=True)
