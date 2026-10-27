"""Worker loop and process (PHASE2B 2.5, 2.9): `python -m superplanner.worker`.

`WorkerLoop` is used by the worker process (claim loop in the main thread) and by the API's embedded workers
(`WORKER_EMBEDDED`, claim loop in a daemon thread). Per loop:

- claim loop: claims while a slot is free (`FOR UPDATE SKIP LOCKED`, one short transaction touching only the job
  row), submits `HANDLERS[kind](ctx, run_id, lease)` to a thread pool in `system_scope()`; when idle it waits for a
  `LISTEN sp_jobs` notification (dedicated psycopg connection) or `WORKER_POLL_SECONDS` (plain polling fallback if
  LISTEN fails); it also runs the reaper every `JOB_REAPER_SECONDS` and maintenance every 10 minutes;
- heartbeat thread: every `JOB_CANCEL_POLL_SECONDS` one query for all active leases (lost? cancel requested?),
  every `JOB_HEARTBEAT_SECONDS` lease renewal + `job_workers` upsert; a lease that could not be renewed for
  `JOB_LEASE_SECONDS - JOB_HEARTBEAT_SECONDS` is treated as lost (lost FIRST, then cancel, R6);
- graceful stop: stop claiming, wait up to the grace period, then for each job still running: (1) fenced requeue
  (`worker_shutdown`, attempt not consumed), (2) `lost`, (3) `cancel_event`; then `job_workers.stopped_at`.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import signal
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, ContextManager

from ..obs import job_metrics
from . import common, pg
from .types import Lease, LeaseLost, RetryableJobError, handler_for

log = logging.getLogger("superplanner.jobs")

MAINTENANCE_SECONDS = 600.0
STOP_JOIN_SECONDS = 15.0


def default_worker_id(tag: str | None = None) -> str:
    host = socket.gethostname() or "host"
    rand = uuid.uuid4().hex[:6]
    mid = f"{tag}-{rand}" if tag else rand
    return f"{host}:{os.getpid()}:{mid}"[:128]


class WorkerContext:
    """`RuntimeContext` of a worker process (handlers must not use AppContext-only members)."""

    def __init__(self, settings: Any, db: Any):
        self.settings = settings
        self.db = db

    def write_guard(self) -> ContextManager[Any]:
        return contextlib.nullcontext()


class _Active:
    __slots__ = ("lease", "future", "renewed_at", "started")

    def __init__(self, lease: Lease):
        self.lease = lease
        self.future: Future | None = None
        self.renewed_at = time.monotonic()
        self.started = time.monotonic()


class _Listener:
    """LISTEN sp_jobs on a dedicated autocommit psycopg connection; falls back to plain sleeping if unavailable."""

    RETRY_SECONDS = 30.0

    def __init__(self, url: str, stop: threading.Event):
        self.url = url
        self.stop = stop
        self.conn: Any = None
        self.retry_at = 0.0
        self.listening = False

    def _connect(self) -> bool:
        if self.conn is not None:
            return True
        if time.monotonic() < self.retry_at:
            return False
        try:
            import psycopg

            self.conn = psycopg.connect(pg.psycopg_conninfo(self.url), autocommit=True,
                                        application_name="superplanner-listen", connect_timeout=5)
            self.conn.execute(f"LISTEN {pg.NOTIFY_CHANNEL}")
            self.listening = True
            return True
        except Exception as exc:
            log.warning("LISTEN %s unavailable (%s); polling only", pg.NOTIFY_CHANNEL, exc.__class__.__name__)
            self.close()
            self.retry_at = time.monotonic() + self.RETRY_SECONDS
            return False

    def wait(self, timeout: float, wake: threading.Event) -> bool:
        """Block up to `timeout`; True on a notification. Returns early when `stop` or `wake` is set."""
        deadline = time.monotonic() + timeout
        if not self._connect():
            wake.wait(timeout)
            return False
        while not self.stop.is_set() and not wake.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                for _ in self.conn.notifies(timeout=min(0.25, remaining), stop_after=1):
                    return True
            except Exception as exc:
                log.warning("LISTEN connection lost (%s); reconnecting later", exc.__class__.__name__)
                self.close()
                self.retry_at = time.monotonic() + 1.0
                wake.wait(max(0.0, deadline - time.monotonic()))
                return False
        return False

    def close(self) -> None:
        conn, self.conn = self.conn, None
        self.listening = False
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


class WorkerLoop:
    def __init__(self, ctx: Any, *, concurrency: int, kinds: list[str], worker_id: str | None = None,
                 embedded: bool = False, once: bool = False):
        self.ctx = ctx
        self.settings = ctx.settings
        self.concurrency = max(1, int(concurrency))
        self.kinds = list(kinds)
        self.worker_id = worker_id or default_worker_id()
        self.embedded = embedded
        self.once = once
        self.hostname = socket.gethostname() or "host"
        self._lock = threading.Lock()
        self._active: dict[str, _Active] = {}       # job_id -> active claim
        self._stopping = threading.Event()          # stop claiming
        self._force = threading.Event()             # second signal: skip the grace wait
        self._hb_stop = threading.Event()
        self._wake = threading.Event()              # slot freed / stop requested
        self._pool = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="sp-job")
        self._listener = _Listener(ctx.db.url, self._stopping)
        self._loop_thread: threading.Thread | None = None
        self._hb_thread: threading.Thread | None = None
        self._last_upsert = 0.0
        self._claim_errors = 0
        self._stopped = False
        self.claimed_total = 0

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Embedded mode: claim loop and heartbeat in daemon threads."""
        self._startup()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, name="sp-heartbeat", daemon=True)
        self._hb_thread.start()
        self._loop_thread = threading.Thread(target=self._claim_loop, name="sp-claim", daemon=True)
        self._loop_thread.start()

    def run(self) -> None:
        """Process mode: heartbeat thread + claim loop in the calling thread until stopped (or idle with --once)."""
        self._startup()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, name="sp-heartbeat", daemon=True)
        self._hb_thread.start()
        self._claim_loop()

    def _startup(self) -> None:
        job_metrics.slots(self.concurrency, 0)
        self._upsert_worker(force=True)
        with contextlib.suppress(Exception):
            pg.reap_expired(self.ctx)
        log.info("worker.started id=%s concurrency=%d kinds=%s embedded=%s", self.worker_id, self.concurrency,
                 ",".join(self.kinds), self.embedded)

    def request_stop(self, force: bool = False) -> None:
        if self._stopping.is_set() or force:
            self._force.set()
        self._stopping.set()
        self._wake.set()

    def stop(self, grace_seconds: float | None = None) -> None:
        """Graceful stop (B 2.9). Idempotent."""
        if self._stopped:
            return
        self._stopped = True
        grace = self.settings.worker_shutdown_grace_seconds if grace_seconds is None else grace_seconds
        log.info("worker.stopping id=%s active=%d grace=%.1fs", self.worker_id, len(self._active), grace)
        self.request_stop()
        if self._loop_thread is not None and self._loop_thread is not threading.current_thread():
            self._loop_thread.join(timeout=STOP_JOIN_SECONDS)
        deadline = time.monotonic() + max(0.0, grace)
        while self._active and time.monotonic() < deadline and not self._force.is_set():
            time.sleep(0.05)
        for act in list(self._active.values()):
            lease = act.lease
            try:
                common.requeue_lease(self.ctx, lease, "worker_shutdown")       # (1) fenced requeue
                job_metrics.job_finished(lease.kind, "requeued")
            except LeaseLost:
                pass                                                         # finished meanwhile
            except Exception:
                log.exception("could not requeue job %s at shutdown (the reaper will after expiry)", lease.job_id)
            lease.mark_lost()                                                # (2) lost, (3) cancel
        futures = [a.future for a in list(self._active.values()) if a.future is not None]
        end = time.monotonic() + STOP_JOIN_SECONDS
        for f in futures:
            with contextlib.suppress(Exception):
                f.result(timeout=max(0.0, end - time.monotonic()))
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._hb_stop.set()
        if self._hb_thread is not None:
            self._hb_thread.join(timeout=5)
        self._listener.close()
        try:
            from ..api.db.ownership import system_scope

            with system_scope(), self.ctx.db.write() as s:
                pg.stop_worker(s, self.worker_id)
        except Exception:
            log.warning("could not mark worker %s stopped", self.worker_id)
        job_metrics.slots(self.concurrency, 0)
        log.info("worker.stopped id=%s", self.worker_id)

    # ---------------------------------------------------------------- introspection (tests, wait_idle)

    def busy(self) -> int:
        with self._lock:
            return len(self._active)

    def holds_run(self, run_id: str) -> bool:
        with self._lock:
            return any(a.lease.run_id == run_id for a in self._active.values())

    def wait_run(self, run_id: str, timeout: float) -> bool:
        with self._lock:
            futs = [a.future for a in self._active.values() if a.lease.run_id == run_id and a.future is not None]
        for f in futs:
            with contextlib.suppress(Exception):
                f.result(timeout=timeout)
        return bool(futs)

    def local_cancel(self, run_id: str) -> None:
        with self._lock:
            for a in self._active.values():
                if a.lease.run_id == run_id:
                    a.lease.cancel_event.set()

    def leases(self) -> list[Lease]:
        with self._lock:
            return [a.lease for a in self._active.values()]

    # ---------------------------------------------------------------- claim loop

    def _claim_loop(self) -> None:
        from ..api.db.ownership import system_scope

        next_reap = time.monotonic() + self.settings.job_reaper_seconds
        next_maint = time.monotonic() + (5.0 if not self.embedded else MAINTENANCE_SECONDS)
        poll = self.settings.worker_poll_seconds
        with system_scope():
            while not self._stopping.is_set():
                now = time.monotonic()
                if now >= next_reap:
                    next_reap = now + self.settings.job_reaper_seconds
                    try:
                        pg.reap_expired(self.ctx)
                    except Exception:
                        log.exception("reaper failed")
                if now >= next_maint:
                    next_maint = now + MAINTENANCE_SECONDS
                    try:
                        pg.maintenance(self.ctx)
                    except Exception:
                        log.exception("maintenance failed")
                claimed = 0
                while self.busy() < self.concurrency and not self._stopping.is_set():
                    lease = self._claim_one()
                    if lease is None:
                        break
                    claimed += 1
                if self.once and claimed == 0 and self.busy() == 0:
                    try:
                        if not self._has_claimable():
                            break
                    except Exception:
                        log.warning("queue check failed; retrying")
                self._wake.clear()
                if self.busy() < self.concurrency and self._claim_errors == 0:
                    self._listener.wait(poll, self._wake)
                else:
                    self._wake.wait(min(5.0, poll * (1 + self._claim_errors)) if self._claim_errors else poll)

    def _has_claimable(self) -> bool:
        from sqlalchemy import select

        from ..api.db import JobRow

        with self.ctx.db.read() as s:   # queued jobs incl. ones waiting for their backoff (`run_after`)
            return s.execute(select(JobRow.id).where(JobRow.status == "queued",
                                                     JobRow.kind.in_(self.kinds)).limit(1)).first() is not None

    def _claim_one(self) -> Lease | None:
        token = pg.new_token()
        try:
            with self.ctx.db.write() as s:
                c = pg.claim(s, self.kinds, self.worker_id, token, self.settings.job_lease_seconds)
        except Exception as exc:
            self._claim_errors = min(self._claim_errors + 1, 10)
            if self._claim_errors <= 3 or self._claim_errors % 10 == 0:
                log.warning("claim failed (%s: %s)", exc.__class__.__name__, str(exc).splitlines()[0][:200])
            return None
        self._claim_errors = 0
        if c is None:
            return None
        lease = pg.lease_from_claim(c, token)
        lease.queue_wait_seconds = c.queue_wait
        act = _Active(lease)
        with self._lock:
            self._active[lease.job_id] = act
        self.claimed_total += 1
        job_metrics.job_claimed(c.kind, c.queue_wait)
        job_metrics.slots(self.concurrency, self.busy())
        log.info("job.claimed job=%s run=%s kind=%s attempt=%d worker=%s queue_wait_ms=%d", c.job_id, c.run_id,
                 c.kind, c.attempts, self.worker_id, int(c.queue_wait * 1000))
        try:
            act.future = self._pool.submit(self._execute, act)
        except RuntimeError:   # pool shut down: give the job back
            with contextlib.suppress(Exception):
                common.requeue_lease(self.ctx, lease, "worker_shutdown")
            with self._lock:
                self._active.pop(lease.job_id, None)
            return None
        return lease

    # ---------------------------------------------------------------- job execution (pool thread)

    def _execute(self, act: _Active) -> None:
        from ..api.db.ownership import system_scope

        from ..obs.request_context import bound

        lease = act.lease
        kind, run_id = lease.kind, lease.run_id
        t0 = time.monotonic()
        # Log context for every line of this job (B 5.3): the enqueuing request id plus job fields.
        with bound(request_id=lease.request_id, job_id=lease.job_id, run_id=run_id, kind=kind,
                   worker_id=self.worker_id, attempt=lease.attempt):
            self._execute_bound(act, t0)

    def _execute_bound(self, act: _Active, t0: float) -> None:
        from ..api.db.ownership import system_scope

        lease = act.lease
        kind, run_id = lease.kind, lease.run_id
        log.info("job.started job=%s run=%s kind=%s attempt=%d worker=%s", lease.job_id, run_id, kind,
                 lease.attempt, self.worker_id)
        try:
            with system_scope():
                try:
                    handler_for(kind)(self.ctx, run_id, lease)
                except LeaseLost:
                    lease.outcome = "lease_lost"
                except RetryableJobError as exc:
                    self._requeue_transient(lease, exc)
                except Exception as exc:
                    log.exception("job %s of run %s crashed", lease.job_id, run_id)
                    self._mirror(lease, str(exc) or exc.__class__.__name__)
                else:
                    if lease.outcome is None and not lease.lost.is_set():
                        self._mirror(lease, "The run ended without a result.")
        finally:
            outcome = lease.outcome or "lease_lost"
            if outcome == "lease_lost":
                log.info("job.lease_lost job=%s run=%s attempt=%d", lease.job_id, run_id, lease.attempt)
            else:
                log.info("job.finished job=%s run=%s outcome=%s duration_ms=%d queue_wait_ms=%d", lease.job_id,
                         run_id, outcome, int((time.monotonic() - t0) * 1000),
                         int((getattr(lease, "queue_wait_seconds", None) or 0.0) * 1000))
            if outcome != "requeued":
                job_metrics.job_finished(kind, outcome, time.monotonic() - t0)
            if outcome == "failed":
                job_metrics.job_failure(kind, "engine_error")
            with self._lock:
                self._active.pop(lease.job_id, None)
            job_metrics.slots(self.concurrency, self.busy())
            self._wake.set()

    def _requeue_transient(self, lease: Lease, exc: BaseException) -> None:
        job_metrics.job_failure(lease.kind, "transient_error")
        log.warning("job %s of run %s hit a transient error (%s); requeueing", lease.job_id, lease.run_id,
                    exc.__cause__.__class__.__name__ if exc.__cause__ else exc)
        if lease.lost.is_set():
            lease.outcome = "lease_lost"
            return
        try:
            common.requeue_lease(self.ctx, lease, "transient_error")
            job_metrics.job_finished(lease.kind, "requeued")
        except LeaseLost:
            lease.outcome = "lease_lost"
        except Exception:
            # DB still unavailable: stop renewing, the lease expires and the reaper requeues the job
            log.warning("requeue of job %s failed; it is requeued after its lease expires", lease.job_id)
            lease.mark_lost()
            lease.outcome = "lease_lost"

    def _mirror(self, lease: Lease, error: str) -> None:
        try:
            common.mirror_finish(self.ctx, lease, error)
        except LeaseLost:
            lease.outcome = "lease_lost"
        except Exception:
            log.exception("could not finish job %s", lease.job_id)
            lease.mark_lost()

    # ---------------------------------------------------------------- heartbeat thread

    def _upsert_worker(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_upsert < self.settings.job_heartbeat_seconds:
            return
        try:
            from ..api.db.ownership import system_scope

            with system_scope(), self.ctx.db.write() as s:
                pg.upsert_worker(s, self.worker_id, self.hostname, os.getpid(), self.kinds, self.concurrency,
                                 self.busy())
            self._last_upsert = now
        except Exception as exc:
            log.warning("could not register worker %s (%s)", self.worker_id, exc.__class__.__name__)

    def _renew_one(self, lease: Lease) -> bool | None:
        """Renew one lease; None = lease gone. Separate method so tests can simulate DB failures."""
        with self.ctx.db.write() as s:
            return pg.renew(s, lease.job_id, lease.token, self.settings.job_lease_seconds)

    def _check(self, leases: list[Lease]) -> dict[str, Any]:
        with self.ctx.db.read() as s:
            return pg.check_leases(s, [l.job_id for l in leases])

    def _heartbeat_loop(self) -> None:
        from ..api.db.ownership import system_scope

        st = self.settings
        tick = st.job_cancel_poll_seconds
        lost_after = max(st.job_lease_seconds - st.job_heartbeat_seconds, tick)
        last_renew = time.monotonic()
        with system_scope():
            while not self._hb_stop.wait(tick):
                with self._lock:
                    acts = [a for a in self._active.values() if not a.lease.lost.is_set()]
                if acts:
                    try:
                        rows = self._check([a.lease for a in acts])
                        for a in acts:
                            r = rows.get(a.lease.job_id)
                            if r is None or r.status != "running" or r.lease_token != a.lease.token:
                                a.lease.mark_lost()
                            elif r.cancel_requested:
                                a.lease.cancel_event.set()
                    except Exception as exc:
                        log.debug("lease check failed: %s", exc)
                now = time.monotonic()
                if now - last_renew >= st.job_heartbeat_seconds:
                    last_renew = now
                    for a in acts:
                        if a.lease.lost.is_set():
                            continue
                        try:
                            res = self._renew_one(a.lease)
                        except Exception as exc:
                            log.warning("lease renewal of job %s failed (%s)", a.lease.job_id,
                                        exc.__class__.__name__)
                            continue
                        if res is None:
                            a.lease.mark_lost()
                        else:
                            a.renewed_at = time.monotonic()
                            if res:
                                a.lease.cancel_event.set()
                    self._upsert_worker()
                for a in acts:
                    if not a.lease.lost.is_set() and time.monotonic() - a.renewed_at > lost_after:
                        log.warning("lease of job %s not renewed for %.1fs: treating it as lost", a.lease.job_id,
                                    time.monotonic() - a.renewed_at)
                        a.lease.mark_lost()


# ---------------------------------------------------------------- process entry point

def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m superplanner.worker",
                                description="SuperPlanner job worker (PostgreSQL queue).")
    p.add_argument("--concurrency", type=int, default=None, help="job slots (default WORKER_CONCURRENCY=2)")
    p.add_argument("--kinds", default=None, help="comma list of solver_run,finance_run (default WORKER_KINDS)")
    p.add_argument("--id", dest="worker_id", default=None, help="worker id (default <hostname>:<pid>:<6 hex>)")
    p.add_argument("--once", action="store_true", help="process jobs until the queue is empty, then exit 0")
    p.add_argument("--metrics-port", type=int, default=None, help="Prometheus port (default 9101, 0 disables)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    from ..api.config import ConfigError, Settings
    from ..obs.logging import configure_logging

    try:
        settings = Settings()
        configure_logging(settings, "worker")
        if args.kinds is not None:
            settings.worker_kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
            bad = [k for k in settings.worker_kinds if k not in ("solver_run", "finance_run")]
            if bad or not settings.worker_kinds:
                raise ConfigError(f"--kinds must be a comma list of solver_run,finance_run (got {args.kinds!r}).")
        if settings.job_backend != "queue":
            raise ConfigError("the worker needs JOB_BACKEND=queue (JOB_BACKEND=inline runs jobs inside the API).")
        if args.concurrency is not None and args.concurrency < 1:
            raise ConfigError("--concurrency must be >= 1.")
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    settings.log_warnings()

    from superplanner import migrate

    from ..api.db import Database
    from ..api.db.ownership import install as install_ownership
    from ..api.db.ownership import system_scope

    db = Database.from_settings(settings, service="worker")
    try:
        with system_scope():
            migrate.ensure_schema(db, settings)
    except migrate.SchemaError as exc:
        print(f"schema error: {exc}", file=sys.stderr)
        db.dispose()
        return 3
    except Exception as exc:
        print(f"cannot reach the database: {exc.__class__.__name__}: {str(exc).splitlines()[0]}", file=sys.stderr)
        db.dispose()
        return 3
    install_ownership(db, single_user=settings.single_user)
    wctx = WorkerContext(settings, db)
    with system_scope():
        common.queue_start_recovery(wctx)

    port = settings.worker_metrics_port if args.metrics_port is None else args.metrics_port
    if port:
        try:
            from prometheus_client import start_http_server

            start_http_server(port)   # also the worker's liveness probe (compose healthcheck, B 5.2)
            log.info("worker metrics on :%d/metrics", port)
        except Exception as exc:
            log.warning("metrics server on :%d not started (%s)", port, exc)

    loop = WorkerLoop(wctx, concurrency=args.concurrency or settings.worker_concurrency, kinds=settings.worker_kinds,
                      worker_id=args.worker_id or settings.worker_id, once=args.once)

    def _on_signal(signum: int, _frame: Any) -> None:
        log.info("worker: signal %s received%s", signum, " again: skipping the grace period"
                 if loop._stopping.is_set() else "")
        loop.request_stop()

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            with contextlib.suppress(Exception):
                signal.signal(sig, _on_signal)
    try:
        loop.run()
    finally:
        loop.stop()
        db.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
