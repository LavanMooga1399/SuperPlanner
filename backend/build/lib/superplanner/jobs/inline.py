"""`inline` backend (PHASE2B 2.2): the API's own `RunExecutor` thread pool, as before Phase 2b, plus job rows.

`dispatch` claims the job row conditionally (`queued` -> `running`, inline lease: `lease_owner = "inline:<pid>"`,
new token, no expiry, no heartbeat) and submits the handler; the submitted callable enters `system_scope()`. The
handler finishes the job itself in its terminal transaction (`Lease.finish`), so `run_job` has one code path for
both backends. Inline jobs are never reaped; startup recovery (`recover_interrupted_runs`) fails them.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from ..obs import job_metrics
from . import common
from .types import Lease, LeaseLost, handler_for

if TYPE_CHECKING:  # pragma: no cover
    from ..api.context import AppContext

log = logging.getLogger("superplanner.jobs")


class InlineQueue:
    backend = "inline"

    def __init__(self, ctx: "AppContext"):
        self.ctx = ctx
        self.owner = f"inline:{os.getpid()}"

    # -- inside the caller's transaction
    def enqueue(self, s: Session, kind: str, run_id: str, owner_id: str, *, idempotency_key: str | None = None,
                request_hash: str | None = None, request_id: str | None = None) -> Any:
        return common.new_job(s, kind, run_id, owner_id, self.ctx.settings.job_max_attempts,
                              idempotency_key=idempotency_key, request_hash=request_hash,
                              request_id=request_id or common.current_request_id())

    def request_cancel(self, s: Session, kind: str, run_id: str) -> str | None:
        return common.request_cancel(s, kind, run_id)

    # -- after commit
    def dispatch(self, job: Any) -> None:
        from ..api.db import JobRow, utcnow
        from ..api.db.ownership import system_scope

        ctx = self.ctx
        kind = job.kind
        run_id = common.run_id_of(job)
        token = uuid.uuid4().hex
        now = utcnow()
        with system_scope(), ctx.write_guard(), ctx.db.write() as s:
            res = s.execute(update(JobRow).where(JobRow.id == job.id, JobRow.status == "queued").values(
                status="running", attempts=JobRow.attempts + 1, lease_owner=self.owner, lease_token=token,
                lease_expires_at=None, heartbeat_at=None, started_at=func.coalesce(JobRow.started_at, now),
                updated_at=now).execution_options(synchronize_session=False))
            claimed = res.rowcount == 1
        if not claimed:
            return   # cancelled between commit and dispatch: nothing to run
        job_id = job.id
        attempt = int(job.attempts or 0) + 1

        def _run(rid: str, ev: threading.Event) -> None:
            lease = Lease(job_id, token, attempt, kind, rid, cancel_event=ev, max_attempts=int(job.max_attempts))
            t0 = time.monotonic()
            with system_scope():
                try:
                    handler_for(kind)(ctx, rid, lease)
                except LeaseLost:
                    lease.outcome = "lease_lost"
                except Exception as exc:  # run_job records its own failures; this is a last resort
                    log.exception("inline job %s of run %s crashed", job_id, rid)
                    _safe_mirror(ctx, lease, str(exc) or exc.__class__.__name__)
                else:
                    if lease.outcome is None and not lease.lost.is_set():
                        _safe_mirror(ctx, lease, "The run ended without a result.")
                job_metrics.job_finished(kind, lease.outcome or "lease_lost", time.monotonic() - t0)

        if ctx.executor.submit(run_id, _run) is None:   # executor closed: put the job back (recovery handles it)
            with system_scope(), ctx.write_guard(), ctx.db.write() as s:
                s.execute(update(JobRow).where(JobRow.id == job_id, JobRow.lease_token == token).values(
                    status="queued", lease_owner=None, lease_token=None, updated_at=utcnow())
                    .execution_options(synchronize_session=False))

    def notify_cancel(self, run_id: str) -> None:
        self.ctx.executor.cancel(run_id)

    def wait_idle(self, run_id: str, timeout: float = 30.0) -> None:
        """Returns when the executor no longer holds the run's job; TimeoutError after `timeout`."""
        fut = self.ctx.executor.future(run_id)
        if fut is None:
            return
        try:
            fut.result(timeout=timeout)
        except TimeoutError:
            raise
        except Exception:  # the job records its own failures
            pass

    def start(self) -> None:
        pass

    def stop(self, grace_seconds: float = 0.0) -> None:
        pass   # the executor is shut down by AppContext.stop (cancels running jobs, as before)


def _safe_mirror(ctx: Any, lease: Lease, error: str) -> None:
    try:
        common.mirror_finish(ctx, lease, error)
    except Exception:  # never let bookkeeping crash the executor thread
        log.exception("could not finish job %s of run %s", lease.job_id, lease.run_id)
