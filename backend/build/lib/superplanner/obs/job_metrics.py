"""Prometheus job metrics (PHASE2B 5.4), default registry. Recorded by worker processes, embedded workers and the
inline backend. `prometheus_client` is imported lazily-safe: if it is missing, every call is a no-op (the zero-setup
dev mode never needs it, but it is pinned in requirements.txt)."""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - the dependency is pinned; the fallback keeps a broken install usable
    from prometheus_client import Counter, Gauge, Histogram
except Exception:  # pragma: no cover
    Counter = Gauge = Histogram = None  # type: ignore[assignment,misc]

OUTCOMES = ("succeeded", "failed", "cancelled", "requeued", "lease_lost")
FAILURE_REASONS = ("engine_error", "transient_error", "lease_expired", "max_attempts")


class _Noop:
    def labels(self, *a: Any, **k: Any) -> "_Noop":
        return self

    def inc(self, *a: Any, **k: Any) -> None:
        pass

    def dec(self, *a: Any, **k: Any) -> None:
        pass

    def set(self, *a: Any, **k: Any) -> None:
        pass

    def observe(self, *a: Any, **k: Any) -> None:
        pass


def _make(factory: Any, *args: Any, **kwargs: Any) -> Any:
    if factory is None:
        return _Noop()
    return factory(*args, **kwargs)


JOBS_TOTAL = _make(Counter, "sp_jobs_total", "Jobs finished by outcome.", ["kind", "outcome"])
JOB_DURATION = _make(Histogram, "sp_job_duration_seconds", "Handler wall time per claim.", ["kind", "outcome"],
                     buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600))
JOB_QUEUE_WAIT = _make(Histogram, "sp_job_queue_wait_seconds", "Time from enqueue (or retry time) to claim.",
                       ["kind"], buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600))
JOB_FAILURES = _make(Counter, "sp_job_failures_total", "Job failures and interruptions by reason.",
                     ["kind", "reason"])
WORKER_SLOTS = _make(Gauge, "sp_worker_slots", "Worker slots (concurrency) in this process.")
WORKER_BUSY = _make(Gauge, "sp_worker_busy_slots", "Busy worker slots in this process.")


def job_finished(kind: str, outcome: str, duration_seconds: float | None = None) -> None:
    JOBS_TOTAL.labels(kind=kind, outcome=outcome).inc()
    if duration_seconds is not None:
        JOB_DURATION.labels(kind=kind, outcome=outcome).observe(max(0.0, duration_seconds))


def job_failure(kind: str, reason: str) -> None:
    JOB_FAILURES.labels(kind=kind, reason=reason).inc()


def job_claimed(kind: str, queue_wait_seconds: float | None) -> None:
    if queue_wait_seconds is not None:
        JOB_QUEUE_WAIT.labels(kind=kind).observe(max(0.0, queue_wait_seconds))


def slots(total: int, busy: int) -> None:
    WORKER_SLOTS.set(total)
    WORKER_BUSY.set(busy)
