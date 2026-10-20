"""API-side Prometheus metrics (PHASE2B 5.4): HTTP, SSE, auth events and the queue collector. Default registry.

Recorded by `obs.request_context.RequestContextMiddleware` (one place for every request, so routes need no
instrumentation). `route` is always a template (`/api/v1/problems/{problem_id}`) or `unmatched`, never a raw path.
SSE routes are counted in `sp_http_requests_total` but excluded from the duration histogram (they last minutes).

Auth events are derived from the auth endpoints' responses (route + status; for 403 the error code in the body),
so the auth package needs no metrics code:
`sign_in_ok` (POST sign-in 200), `sign_in_failed` (POST sign-in 401), `sign_up` (POST sign-up 201),
`rate_limited` (any 429), `csrf_failed` (any 403 whose error code is `CSRF_FAILED`).

The queue gauges (`sp_jobs_queue_depth`, `sp_jobs_oldest_queued_age_seconds`, `sp_workers_alive`) are refreshed
by `refresh_queue_gauges(ctx)` when `/metrics` is scraped: one grouped query on `jobs` (system scope, review R9),
cached 5 s per app. Every API replica reports the same DB values; dashboards use `max()`.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

log = logging.getLogger(__name__)

JOB_KINDS = ("solver_run", "finance_run")
QUEUE_STATUSES = ("queued", "running")
AUTH_EVENTS = ("sign_in_ok", "sign_in_failed", "sign_up", "rate_limited", "csrf_failed")
COLLECTOR_TTL_SECONDS = 5.0

HTTP_REQUESTS = Counter("sp_http_requests_total", "HTTP requests by method, route template and status.",
                        ["method", "route", "status"])
HTTP_DURATION = Histogram("sp_http_request_duration_seconds", "HTTP request duration (SSE routes excluded).",
                          ["method", "route"],
                          buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))
SSE_ACTIVE = Gauge("sp_sse_streams_active", "Open SSE progress streams.", ["kind"])
QUEUE_DEPTH = Gauge("sp_jobs_queue_depth", "Jobs by kind and status (queued, running).", ["kind", "status"])
OLDEST_QUEUED = Gauge("sp_jobs_oldest_queued_age_seconds", "Age of the oldest queued job (0 if none).", ["kind"])
WORKERS_ALIVE = Gauge("sp_workers_alive", "Workers with a recent heartbeat (inline: RUN_WORKERS).")
AUTH_EVENTS_TOTAL = Counter("sp_auth_events_total", "Authentication events.", ["event"])

for _k in ("solver", "finance"):
    SSE_ACTIVE.labels(kind=_k)
for _e in AUTH_EVENTS:
    AUTH_EVENTS_TOTAL.labels(event=_e)
for _k in JOB_KINDS:
    OLDEST_QUEUED.labels(kind=_k)
    for _s in QUEUE_STATUSES:
        QUEUE_DEPTH.labels(kind=_k, status=_s)

_SIGN_IN = "/api/v1/auth/sign-in"
_SIGN_UP = "/api/v1/auth/sign-up"


# ---------------------------------------------------------------- HTTP / SSE / auth (middleware)

def sse_kind(route: str) -> str:
    return "finance" if "/finance/" in route else "solver"


def sse_started(kind: str) -> None:
    SSE_ACTIVE.labels(kind=kind).inc()


def sse_finished(kind: str) -> None:
    SSE_ACTIVE.labels(kind=kind).dec()


def observe_request(method: str, route: str | None, status: int, duration_seconds: float, *, sse: bool) -> None:
    r = route or "unmatched"
    HTTP_REQUESTS.labels(method=method, route=r, status=str(status)).inc()
    if not sse:
        HTTP_DURATION.labels(method=method, route=r).observe(max(0.0, duration_seconds))


def auth_event(method: str, route: str | None, status: int, body_403: bytes = b"") -> str | None:
    if status == 429:
        return "rate_limited"
    if status == 403 and b'"CSRF_FAILED"' in body_403:
        return "csrf_failed"
    if method == "POST" and route == _SIGN_IN:
        return "sign_in_ok" if status == 200 else ("sign_in_failed" if status == 401 else None)
    if method == "POST" and route == _SIGN_UP and status == 201:
        return "sign_up"
    return None


def observe_auth(method: str, route: str | None, status: int, body_403: bytes = b"") -> None:
    ev = auth_event(method, route, status, body_403)
    if ev is not None:
        AUTH_EVENTS_TOTAL.labels(event=ev).inc()


# ---------------------------------------------------------------- queue collector (scrape time)

_cache_lock = threading.Lock()
_cache: dict[int, tuple[float, dict[str, Any]]] = {}


def queue_snapshot(ctx: Any) -> dict[str, Any]:
    """`{"depth": {(kind, status): n}, "oldest": {kind: seconds}, "workers_alive": n}` from the database.

    Runs in system scope: `jobs` is an owned table and this runs inside a request without a bound user (R9)."""
    from sqlalchemy import func, select

    from ..api.db import JobRow
    from ..api.db.ownership import system_scope
    from ..jobs.types import db_now

    depth = {(k, st): 0 for k in JOB_KINDS for st in QUEUE_STATUSES}
    oldest = {k: 0.0 for k in JOB_KINDS}
    with system_scope(), ctx.db.read() as s:
        rows = s.execute(select(JobRow.kind, JobRow.status, func.count(), func.min(JobRow.run_after))
                         .where(JobRow.status.in_(QUEUE_STATUSES))
                         .group_by(JobRow.kind, JobRow.status)).all()
        now = db_now(s)
        for kind, status, n, first in rows:
            depth[(kind, status)] = int(n)
            if status == "queued" and first is not None:
                if first.tzinfo is None:
                    first = first.replace(tzinfo=UTC)
                oldest[kind] = max(0.0, (now - first).total_seconds())
        if ctx.settings.job_backend == "queue" and ctx.db.is_postgres:
            from ..jobs import pg

            alive = pg.alive_workers(s, ctx.settings.job_heartbeat_seconds)
        else:
            alive = int(ctx.settings.run_workers)
    return {"depth": depth, "oldest": oldest, "workers_alive": alive}


def cached_queue_snapshot(ctx: Any, ttl: float = COLLECTOR_TTL_SECONDS) -> dict[str, Any]:
    key = id(ctx)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
    snap = queue_snapshot(ctx)
    with _cache_lock:
        _cache[key] = (time.monotonic(), snap)
    return snap


def refresh_queue_gauges(ctx: Any) -> bool:
    """Set the queue gauges from this app's database. False (gauges unchanged) if the DB query failed."""
    try:
        snap = cached_queue_snapshot(ctx)
    except Exception as exc:
        log.warning("metrics: queue collector failed (%s)", exc.__class__.__name__)
        return False
    for (kind, status), n in snap["depth"].items():
        QUEUE_DEPTH.labels(kind=kind, status=status).set(n)
    for kind, age in snap["oldest"].items():
        OLDEST_QUEUED.labels(kind=kind).set(age)
    WORKERS_ALIVE.set(snap["workers_alive"])
    return True
