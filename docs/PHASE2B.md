# SuperPlanner Phase 2b - Scalable deployment: durable workers, PostgreSQL, accounts, operations (design)

> **Historical note (PostgreSQL-only release):** "file-DB" below refers to the embedded file database of earlier
> releases. It was removed; SuperPlanner now runs on PostgreSQL only (see `docs/DEPLOY.md`, Changelog, and
> `docs/ARCHITECTURE.md` section 25). Statements about file-DB behaviour describe the past.

Status: design for implementation. Builds on `docs/ARCHITECTURE.md` (A.x), `docs/FINANCE.md` (F.x) and
`docs/PHASE2.md` (P2.x). Product owner request: "make it scalable". Everything in this document is additive:
**file-DB + one process + no login stays the zero-setup default** (Windows: Python and Node only).

## Table of contents

- 0. Summary of decisions
- 1. Current state (what the code does today)
- 2. Part A - Durable background jobs
  - 2.1 Why a PostgreSQL queue and not Celery/Redis
  - 2.2 Backends and the `JobQueue` interface
  - 2.3 `jobs` table and `job_workers` table
  - 2.4 State machine (job and run)
  - 2.5 Claim, lease, heartbeat, fencing, reaper
  - 2.6 Retries and backoff
  - 2.7 Cancellation across processes
  - 2.8 Idempotency keys
  - 2.9 Worker process (`python -m superplanner.worker`)
  - 2.10 Changes to `run_service.py` / `finance/run_service.py`
  - 2.11 Progress events and SSE across processes
  - 2.12 Multi-process consistency (replacing `WRITE_LOCK`)
- 3. Part B - PostgreSQL as the production database
  - 3.1 Engine, driver, pooling
  - 3.2 Alembic layout and migrations
  - 3.3 Schema changes in `0002_phase2b` (complete list)
  - 3.4 Startup schema handling and the legacy file-DB upgrade path
  - 3.5 Dialect differences the code must respect
  - 3.6 Dual-database test strategy
- 4. Part C - User accounts and access control
  - 4.1 `AUTH_MODE`
  - 4.2 Tables `users`, `user_sessions`, `auth_rate_limits`
  - 4.3 Passwords
  - 4.4 Session cookie and CSRF design
  - 4.5 Auth endpoints (JSON, error codes)
  - 4.6 Rate limiting
  - 4.7 Ownership enforcement (one central mechanism)
  - 4.8 Endpoint access table (every endpoint)
  - 4.9 Admin CLI `python -m superplanner.manage`
  - 4.10 Frontend
- 5. Part D - Deployment and operations
  - 5.1 Configuration variables
  - 5.2 Health and readiness
  - 5.3 Structured logging and request ids
  - 5.4 Prometheus metrics
  - 5.5 Docker images and compose
  - 5.6 `docs/DEPLOY.md` runbook outline
- 6. Part E - Load sanity script
- 7. File ownership and work packages
- 8. Changes to existing behaviour and existing tests
- 9. Deferred items
- 10. Implementation notes (one subsection per work package, filled by implementers)

---

## 0. Summary of decisions

1. **Job queue = PostgreSQL table `jobs`** claimed with `SELECT ... FOR UPDATE SKIP LOCKED`, 30 s leases renewed
   by a heartbeat every 10 s, lease-token **fencing** on every worker write, retries with exponential backoff for
   infrastructure failures only (lease expiry, DB disconnects), idempotency keys, cancellation through a DB flag
   polled every second. Separate process `python -m superplanner.worker`. No Celery, no Redis (2.1).
2. Two job backends behind one interface: `inline` (today's thread pool, default with file-DB) and `queue`
   (default with PostgreSQL). Job rows are written in **both** modes so run code is identical.
3. Progress events stay in `solver_run_events` / `finance_run_events`; SSE keeps polling the DB, so any API
   instance can stream any run. Event `seq` allocation becomes safe across processes (row lock on the run).
4. The process-wide `WRITE_LOCK` is replaced by `ctx.write_guard()` (the old RLock on file-DB, no-op on Postgres)
   plus **row locks** (`SELECT ... FOR NO KEY UPDATE` on the parent plan; `FOR UPDATE` only for deletes) and
   **partial unique indexes** (one active solver run per problem, one approved schedule per problem) as the
   cross-process backstop. Finance relies on the plan row lock only (review note R5).
5. **Alembic**: `0001_initial` = today's schema exactly; `0002_phase2b` = everything new. Fresh empty databases use
   `create_all` + `stamp head` (fast; a test proves model metadata == migrations); existing databases are upgraded.
   Legacy file-DB databases (created by `create_all`, no `alembic_version`) are stamped `0001` then upgraded,
   with an automatic file backup.
6. psycopg 3 (`postgresql+psycopg://`), SQLAlchemy `QueuePool` with pre-ping, JSONB documents (already declared
   via `with_variant`), new indexes for list/derive queries and FK columns.
7. The whole backend suite runs on file-DB (default) and on PostgreSQL (`--db=postgres` or `SP_TEST_DB=postgres`),
   per-test databases cloned from a migrated template (`CREATE DATABASE ... TEMPLATE`).
8. **Auth**: `AUTH_MODE=single_user` (dev default, no login, identical to today, all data owned by the fixed
   user `usr_local`) or `accounts` (production default). argon2id (`argon2-cffi`). Opaque random session token in
   an httpOnly `SameSite=Lax` cookie (`__Host-` prefixed and `Secure` in production), stored as SHA-256 in
   `user_sessions`; synchronizer CSRF token per session sent as `X-CSRF-Token` on every unsafe method, plus an
   `Origin` check. DB-backed fixed-window rate limits on auth endpoints (work across instances). **No server secret
   is needed.**
9. **Ownership** is enforced centrally at the ORM layer: every owned table has `owner_id`; a SQLAlchemy
   `do_orm_execute` hook adds `owner_id = :current_user` to every ORM SELECT/UPDATE/DELETE touching an owned
   entity, and `before_flush` stamps `owner_id` on inserts. The current user comes from one FastAPI dependency
   (`require_user`) attached at router-include time. Inside an HTTP request a query on an owned table without a
   bound user **fails closed** (500). Existing `not_found` paths therefore return 404 for other users' objects
   with the same body as for unknown ids; ids are random UUID4 (no enumeration).
10. Operations: one backend image (targets `api`, `worker`), one frontend image (nginx-unprivileged serving the
    static build and proxying `/api`), `docker-compose.yml` (postgres, migrate, api, worker xN, frontend),
    `.env.example`, `/api/v1/health/live` and `/api/v1/health/ready` (existing `/api/v1/health` unchanged), JSON logs
    with request ids, Prometheus `/metrics` on the API and on each worker, `docs/DEPLOY.md`.
11. Load script `backend/scripts/load_queue.py`: 50 mixed runs, 2-3 worker processes, throughput report and
    exactly-once verification from the database (optional chaos: kill a worker).

---

## 1. Current state (what the code does today)

Facts the design depends on (read from the code, 2026-10-19):

- `api/main.py::create_app(settings)` builds an `AppContext` (`api/context.py`): `Database` (`api/db/session.py`),
  a `RunExecutor` (`api/executor.py`, `ThreadPoolExecutor(RUN_WORKERS=2)` + one `threading.Event` per run) and
  starts lazily or in the lifespan: `create_all()`, then `recover_interrupted_runs` for solver and finance runs
  (every `queued`/`running` run -> `failed`, `"Server restarted before the run finished."`).
- Run creation (`services/run_service.create_run`, `replan_service.replan`, `finance/run_service.create_run`,
  `create_what_if`): under the process-wide `WRITE_LOCK` and one write transaction: check one active run, preflight,
  snapshot, insert run + `run_queued` event, commit, then `submit(ctx, run_id)` -> `executor.submit`.
- Workers (`run_job`) mark `running` + `run_started`, call `engine.optimize(problem, req, progress_cb,
  cancel_event)` / `finance.run_plan(plan, req, writer, cancel_event)`, write schedules/results + run summary +
  terminal event in one transaction. Progress writers use a short write transaction per event; `seq` =
  `max(seq)+1` (safe today because only one writer per run exists in one process).
- Cancel: sets `cancel_requested`; a `queued` run becomes `cancelled` immediately with `run_cancelled`; then
  `executor.cancel(run_id)` sets the in-process event. Finance "active" excludes cancel-requested runs.
- SSE (`/solver-runs/{id}/events`, `/finance/runs/{id}/events`) polls the event table every 0.5 s through
  `run_in_threadpool`, keepalive 15 s, `Last-Event-ID` / `?after=` resume, 204 for finished runs without new events.
- file-DB: WAL, `foreign_keys=ON`, `BEGIN IMMEDIATE` for write sessions. JSON columns are `JSON` with a JSONB
  variant on Postgres already.
- Tables (11): `problems`, `problem_versions`, `solver_runs`, `solver_run_events`, `schedules`, `audit_events`
  (`api/db/models.py`); `finance_plans`, `finance_plan_versions`, `finance_runs`, `finance_run_events`,
  `finance_results` (`api/finance/db_models.py`). **Intake has no tables**: the intake API is stateless and drafts
  live in the browser's `sessionStorage` (`frontend/src/intake/state/IntakeContext.tsx`).
- Endpoints: 56 under `/api/v1` (listed in 4.8). No auth, CORS `allow_credentials=False`, body limit middleware.
- Tests: 7 conftests with a `db_url` fixture returning a temp file-DB database; a few tests hard-code `<file-DB URL>` URLs
  or use `ctx.executor` directly (listed in 8.2). `test_api_health` asserts the exact `/health` body.
- Frontend: same-origin `/api/v1` through the Vite proxy (target hard-coded `127.0.0.1:8000`); two `raw()` fetch
  helpers (`src/api/client.ts`, `src/finance/api/client.ts`; intake reuses the finance one); `EventSource` for SSE.

---

## 2. Part A - Durable background jobs

### 2.1 Why a PostgreSQL queue and not Celery/Redis

Chosen: PostgreSQL table + `FOR UPDATE SKIP LOCKED`. Reasons, specific to this code base:

1. **Transactional enqueue.** The run row, its snapshot, the `run_queued` event and the job are inserted in the
   *same* transaction that already exists in `create_run`. With a broker there is a dual write (commit, then
   publish): a crash between them leaves a queued run nobody executes, or a job for a rolled-back run.
2. **Exactly-once results.** The worker's final transaction (schedules/results + run summary + terminal event)
   also flips the job to terminal *with a lease-token check*. A zombie worker can never write a second result.
   Celery with `acks_late` + Redis visibility timeout redelivers long CPU jobs (solver runs are up to 300 s) and
   needs the same DB fencing anyway.
3. **Cancellation and progress already live in the DB** (`cancel_requested`, event tables, SSE polling). Celery's
   revoke/remote-control would be a second, weaker channel.
4. **Load profile.** Jobs take 1-300 s; expected volume is tens to a few thousand per hour. A SKIP LOCKED queue
   handles thousands of claims per second, far above need.
5. **Operations and Windows.** No Redis to run, back up or secure; Celery's prefork pool is unsupported on
   Windows. Postgres is already the system of record (blueprint).

Celery/Redis would only win for very high fan-out or many heterogeneous task types; revisit if that ever happens
(9). Redis is not used anywhere in 2b.

### 2.2 Backends and the `JobQueue` interface

Setting `JOB_BACKEND` (`Settings.job_backend`): `"inline"` | `"queue"`. Default: `"queue"` when the database is
PostgreSQL, else `"inline"`. `queue` on file-DB is rejected at startup (`ConfigError`, process exits 2) because file-DB
cannot serve several processes safely. `inline` on PostgreSQL is allowed only when `SP_ENV != production` (tests,
single-process dev) and logs a warning: inline startup recovery fails *every* queued/running run, so two API
processes in inline mode on one database would fail each other's runs (review note R7).

- **inline**: today's `RunExecutor` thread pool in the API process (`RUN_WORKERS` threads). `ctx.executor` stays
  available (tests use it). Startup recovery unchanged (interrupted runs -> `failed` + `RESTART_ERROR`).
- **queue**: the API only inserts job rows; worker processes execute them. The API never fails runs at startup.
  Optional embedded workers: `WORKER_EMBEDDED=<n>|auto` runs the same worker loop as `n` threads inside the API
  process (`auto` = `RUN_WORKERS`); default `auto` when `SP_ENV=development` (a developer who only points
  `DATABASE_URL` at Postgres and starts the API still gets runs executed), `0` in production. Used by the Postgres
  test run and single-container deployments.

New package `backend/superplanner/jobs/`:

```python
# superplanner/jobs/types.py
JobKind = Literal["solver_run", "finance_run"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TERMINAL_JOB_STATUSES = ("succeeded", "failed", "cancelled")

class LeaseLost(Exception): ...          # fencing failed: another worker owns the job, or the job row is gone
class RetryableJobError(Exception): ...   # infrastructure failure; the worker may retry (2.6)

class RuntimeContext(Protocol):           # AppContext and jobs.worker.WorkerContext both satisfy it
    settings: Settings
    db: Database
    def write_guard(self) -> ContextManager[None]: ...   # run_job uses it (2.12)

class Lease:
    job_id: str
    token: str                            # uuid4 hex, new per claim
    attempt: int                          # jobs.attempts after the claim (1-based)
    cancel_event: threading.Event         # passed to engine.optimize / finance.run_plan
    lost: threading.Event                 # set when a heartbeat or fence finds the lease gone
    def fence(self, s: Session) -> None:
        """In the caller's transaction: SELECT the job row FOR UPDATE; raise LeaseLost unless
        status='running' and lease_token == self.token. Call AFTER locking the run row (lock order 2.12)."""
    def finish(self, s: Session, status: Literal["succeeded", "failed", "cancelled"],
               error: str | None = None) -> None:
        """fence(s), then UPDATE jobs SET status, finished_at=now, last_error, lease_token = NULL,
        lease_expires_at = NULL. `lease_owner` is KEPT (last executor; the load script and the jobs-per-worker
        report read it). Same transaction as the run's terminal write."""

Handler = Callable[[RuntimeContext, str, Lease], None]    # (ctx, run_id, lease)
HANDLERS: dict[JobKind, Handler]   # {"solver_run": run_service.run_job, "finance_run": finance run_service.run_job}

class JobQueue(Protocol):
    backend: Literal["inline", "queue"]
    def enqueue(self, s: Session, kind: JobKind, run_id: str, owner_id: str, *,
                idempotency_key: str | None = None, request_hash: str | None = None) -> JobRow:
        """Inside the caller's transaction. Inserts the job (status queued). Postgres: also
        `SELECT pg_notify('sp_jobs', kind)` (delivered on commit). Never commits."""
    def dispatch(self, job: JobRow) -> None:
        """After commit. inline: claim the row with an inline lease and executor.submit(); queue: no-op."""
    def request_cancel(self, s: Session, kind: JobKind, run_id: str) -> str | None:
        """Inside the caller's transaction, after the run row is locked: job.cancel_requested = True;
        a `queued` job becomes `cancelled` (finished_at = now). Returns the job id (None if the run has no job:
        legacy rows)."""
    def notify_cancel(self, run_id: str) -> None:
        """After commit. inline: executor.cancel(run_id) (immediate). queue: no-op (workers poll, 2.7)."""
    def wait_idle(self, run_id: str, timeout: float = 30.0) -> None:
        """Test helper: returns when no worker holds the run's job (inline: future.result; queue: poll job row
        until terminal or queued-with-no-lease)."""
    def start(self) -> None: ...
    def stop(self, grace_seconds: float) -> None: ...
```

Implementations: `jobs/inline.py::InlineQueue(ctx)` (wraps `RunExecutor`), `jobs/pg.py::PgQueue(ctx)` (enqueue,
cancel, embedded worker threads via `jobs/worker.py::WorkerLoop`). `AppContext.jobs` is created in
`AppContext.start()`; `AppContext.executor` keeps returning the `RunExecutor` (inline only; in queue mode it raises
`RuntimeError("no in-process executor in queue mode")`).

The inline lease (`InlineQueue.dispatch`) does the same claim UPDATE as 2.5 (status `running`, new token,
`lease_owner = "inline:<pid>"`, `lease_expires_at = NULL`), conditional on `status = 'queued'`: 0 rows (cancelled
between commit and dispatch) -> nothing is submitted. If `executor.submit` returns None (executor closed) the job
is put back to `queued` in a new transaction (startup recovery then handles it). Inline jobs are never reaped, there
are no heartbeats, and `fence`/`finish` work unchanged. The submitted callable enters `system_scope()` explicitly
(do not rely on thread pools not inheriting context vars). Thus `run_job` has one code path for both backends.

### 2.3 `jobs` table and `job_workers` table

`jobs` (model `JobRow` in `superplanner/api/db/models.py`):

| Column | Type | Notes |
|---|---|---|
| `id` | `String(64)` PK | `job_<uuid4hex>` |
| `kind` | `String(32)` not null | `solver_run` \| `finance_run` |
| `solver_run_id` | `String(64)` FK `solver_runs.id` ON DELETE CASCADE, null | exactly one of the two run FKs is set |
| `finance_run_id` | `String(64)` FK `finance_runs.id` ON DELETE CASCADE, null | (CHECK constraint `ck_jobs_one_target`) |
| `owner_id` | `String(64)` FK `users.id` not null | copied from the run |
| `status` | `String(16)` not null | 2.4 |
| `priority` | `SmallInteger` not null default 0 | higher first; all jobs use 0 in 2b |
| `attempts` | `Integer` not null default 0 | incremented by each claim |
| `max_attempts` | `Integer` not null | `JOB_MAX_ATTEMPTS` (3) at enqueue |
| `run_after` | `DateTime(tz)` not null | earliest claim time (backoff); enqueue sets DB `now()` |
| `lease_owner` | `String(128)` null | worker id `host:pid:rand6` or `inline:<pid>` |
| `lease_token` | `String(32)` null | uuid4 hex per claim; fencing token |
| `lease_expires_at` | `DateTime(tz)` null | DB clock; null for inline |
| `heartbeat_at` | `DateTime(tz)` null | |
| `cancel_requested` | `Boolean` not null default false | |
| `idempotency_key` | `String(128)` null | 2.8 |
| `request_hash` | `String(64)` null | sha256 of canonical request JSON + route kind |
| `request_id` | `String(64)` null | HTTP request id that enqueued it (log correlation) |
| `last_error` | `Text` null | last failure / requeue reason |
| `created_at`, `updated_at` | `DateTime(tz)` not null | |
| `started_at` | `DateTime(tz)` null | first claim |
| `finished_at` | `DateTime(tz)` null | terminal |

Indexes / constraints:
- `ix_jobs_claim` on `(priority DESC, run_after, created_at, id)` **partial** `WHERE status = 'queued'`.
- `ix_jobs_running_lease` on `(lease_expires_at)` partial `WHERE status = 'running'` (reaper).
- `uq_jobs_solver_run` unique `(solver_run_id)` partial `WHERE solver_run_id IS NOT NULL`; `uq_jobs_finance_run`
  likewise: **one job per run** (enqueue is idempotent per run by construction).
- `uq_jobs_idempotency` unique `(owner_id, idempotency_key)` partial `WHERE idempotency_key IS NOT NULL`.
- `ix_jobs_status_finished` on `(status, finished_at)` (retention cleanup, metrics).
Partial indexes are declared with `postgresql_where=` (file-DB supported them too).

`job_workers` (model `JobWorkerRow`): `id String(128)` PK (worker id), `hostname String(255)`, `pid Integer`,
`kinds JSON` (list), `concurrency Integer`, `busy Integer`, `started_at`, `heartbeat_at` (DB clock),
`stopped_at` null. Upserted by the worker heartbeat; rows with `heartbeat_at < now() - 1 day` are deleted by
maintenance. "Alive" = `stopped_at IS NULL AND heartbeat_at > now() - 3 * JOB_HEARTBEAT_SECONDS`.

### 2.4 State machine (job and run)

```
             enqueue (API tx, run queued + run_queued)
                       |
                       v
     +------------> queued ----------- cancel (API) ------------> cancelled   [run: cancelled, run_cancelled]
     |                 |
     | requeue         | claim (worker tx; attempts += 1; new token; lease)
     | (2.6)           v
     +------------- running ---- final tx: run completed ------> succeeded   [run: completed, run_completed]
                       |  \----- final tx: run cancelled ------> cancelled   [run: cancelled, run_cancelled]
                       |  \----- engine exception -------------> failed      [run: failed, run_failed]
                       |  \----- lease expired / transient error / shutdown:
                       |            attempts <  max  -> queued (run: queued, run_requeued)
                       |            attempts >= max  -> failed (run: failed, run_failed, WORKER_LOST_ERROR)
```

Run status mapping (runs keep their existing statuses): job `queued`<->run `queued`; job `running`<->run `running`
(after the start transaction; between claim and start the run is still `queued`); terminal job status is always
written in the same transaction as the run's terminal status. Invariants (asserted by tests and the load script):
- I1: a run in a terminal status has exactly one terminal event, and it is its last event.
- I2: a solver run has schedules only if it is `completed` or `cancelled`; they were written in one transaction
  together with the job's terminal update (no duplicates, ranks `0..k` unique).
- I3: a finance run has at most one `finance_results` row (add unique index `uq_finance_results_run` on `run_id`).
- I4: a job in a terminal status never changes again.

Error strings (constants in `jobs/types.py`): `RESTART_ERROR = "Server restarted before the run finished."`
(inline, unchanged); `WORKER_LOST_ERROR = "The run was interrupted {n} times and was stopped."`.

### 2.5 Claim, lease, heartbeat, fencing, reaper

All lease times use the **database clock** (`now()`), never the worker's clock. Defaults:
`JOB_LEASE_SECONDS=30`, `JOB_HEARTBEAT_SECONDS=10`, `JOB_CANCEL_POLL_SECONDS=1.0`, `WORKER_POLL_SECONDS=1.0`,
`JOB_REAPER_SECONDS=15`.

**Claim** (worker, own short transaction, only when a slot is free; touches only the job row):
```sql
WITH next AS (
  SELECT id FROM jobs
   WHERE status = 'queued' AND run_after <= now() AND kind = ANY(:kinds)
   ORDER BY priority DESC, run_after, created_at, id
   LIMIT 1
   FOR UPDATE SKIP LOCKED)
UPDATE jobs AS j
   SET status = 'running', attempts = j.attempts + 1, lease_owner = :worker_id, lease_token = :token,
       lease_expires_at = now() + make_interval(secs => :lease_seconds), heartbeat_at = now(),
       started_at = COALESCE(j.started_at, now()), updated_at = now()
  FROM next WHERE j.id = next.id
RETURNING j.id, j.kind, j.solver_run_id, j.finance_run_id, j.attempts, j.max_attempts, j.request_id;
```

**Start** (inside `run_job`, new transaction): lock the run row (`with_for_update`), `lease.fence(s)`, then as
today: if run is not `queued` or `cancel_requested` -> `lease.finish(s, "cancelled")` and return; else run ->
`running`, `started_at = now`, `run_started` event.

**Heartbeat** (one thread per worker process, loop every `JOB_CANCEL_POLL_SECONDS`):
1. Every tick: `SELECT id, cancel_requested FROM jobs WHERE id IN (:active) AND lease_token = ...` (one query for
   all active leases; implemented as `WHERE (id, lease_token) IN (...)` or per-id OR). Missing row -> lease lost.
   `cancel_requested` -> `lease.cancel_event.set()`.
2. Every `JOB_HEARTBEAT_SECONDS`: per active lease
   `UPDATE jobs SET heartbeat_at = now(), lease_expires_at = now() + :lease, updated_at = now()
    WHERE id = :id AND lease_token = :token AND status = 'running' RETURNING cancel_requested`.
   0 rows -> `lease.lost.set()` and `lease.cancel_event.set()` (stop the engine quickly; output discarded).
   Also upsert the `job_workers` row.
3. A DB error in the heartbeat is logged and retried next tick; if no renewal succeeded for
   `JOB_LEASE_SECONDS - JOB_HEARTBEAT_SECONDS` the worker treats all its leases as lost (sets `lost` FIRST, then
   `cancel_event`; the reaper requeues them after expiry).

**Lost is not cancelled (mandatory).** `cancel_event` is shared by user cancellation and lease loss. Every terminal
write in `run_job`/`_finish` first checks `lease.lost.is_set()` and, if set, raises `LeaseLost` instead of writing
`cancelled`. The run's cancelled status is derived only from `run.cancel_requested` / `jobs.cancel_requested` read
under the row lock, or an engine `cancelled` status *while `lost` is not set*. Otherwise a worker that merely lost
its DB connection for 20 s (and whose lease was never taken over) would finalize a user's run as `cancelled`.

**Fencing**: every worker write for a job (start, each progress/stage event, final write, failure write) runs
`lease.fence(s)` inside the same transaction after locking the run row; `LeaseLost` aborts the transaction.
`run_job` catches `LeaseLost` at the top level, logs `job.lease_lost`, increments
`sp_jobs_total{outcome="lease_lost"}` and returns without any further write.

**Reaper** (every worker, every `JOB_REAPER_SECONDS`, and once at worker start):
1. `SELECT id FROM jobs WHERE status = 'running' AND lease_expires_at < now() LIMIT 100` (no lock).
2. For each id, one transaction: lock the run row `FOR UPDATE`, then
   `SELECT ... FROM jobs WHERE id = :id AND status = 'running' AND lease_expires_at < now() FOR UPDATE SKIP LOCKED`
   (skip if gone/renewed/locked), then apply the requeue-or-fail rule of 2.6 with reason `lease_expired`.
3. Orphan runs: runs `queued`/`running` that have **no** job row (legacy data, direct inserts) are failed with
   `RESTART_ERROR` + `run_failed` by `AppContext.start()` in queue mode (and by the worker at start). Inline mode
   keeps today's `recover_interrupted_runs` and additionally marks their jobs `failed`.

### 2.6 Retries and backoff

- Retried (requeue): lease expired (worker crashed/killed/partitioned), `RetryableJobError` (raised by `run_job`
  for `sqlalchemy.exc.OperationalError`, `InterfaceError`, or `DBAPIError` with `connection_invalidated`), worker
  graceful-shutdown timeout (2.9; does **not** consume an attempt: `attempts = attempts - 1`).
- Not retried: engine/finance exceptions (deterministic for the stored request and seed) -> run `failed` with
  `error = str(exc)` as today, job `failed`; preflight is never re-run.
- Requeue transaction (run row locked first, then job row): if `attempts < max_attempts`: job -> `queued`,
  `run_after = now() + backoff(attempts)`, `lease_* = NULL`, `last_error = reason`; run -> `queued`
  (`started_at` kept from the first attempt), event `run_requeued`
  `{"attempt": <next attempt>, "max_attempts": 3, "reason": "lease_expired"|"transient_error"|"worker_shutdown",
  "retry_at": "<iso Z>"}`. Else: job -> `failed`, run -> `failed`, `error = WORKER_LOST_ERROR`, event `run_failed`.
- `backoff(a) = min(JOB_BACKOFF_MAX_SECONDS=300, JOB_BACKOFF_BASE_SECONDS=5 * 2 ** (a - 1)) * uniform(1.0, 1.2)`;
  `worker_shutdown` uses 0 s.
- A retried run starts from scratch from the same snapshot; no partial output exists because results are only
  written in the fenced final transaction.

### 2.7 Cancellation across processes

`POST /solver-runs/{id}/cancel` and `POST /finance/runs/{id}/cancel` (and what-if `replace_active`):
1. API transaction: lock the run row; existing checks (409 `RUN_NOT_ACTIVE`); `run.cancel_requested = True`;
   `ctx.jobs.request_cancel(s, kind, run_id)`; a `queued` run becomes `cancelled` immediately with
   `run_cancelled` (unchanged behaviour; the job becomes `cancelled` too, so no worker ever claims it). If the job
   was already claimed but the run is still `queued` (claim/start window), the run is cancelled the same way and
   the worker's start transaction sees `status != queued` and finishes the job as `cancelled`.
2. After commit: `ctx.jobs.notify_cancel(run_id)` (inline: sets the event at once).
3. Queue mode: the worker heartbeat sees `jobs.cancel_requested` within `JOB_CANCEL_POLL_SECONDS` (1 s) and sets
   `lease.cancel_event`. The engine already polls that event (A.16). In addition the progress writers
   (`_ProgressWriter`, `ProgressWriter`) check `lease.cancel_event`/`lease.lost` before each write and skip writes
   once `lease.lost` is set. Expected end-to-end cancel latency: <= 1 s + engine reaction time.
4. The final transaction re-reads `run.cancel_requested` under the row lock (existing [R11] rule), so a cancel
   that races with completion still yields `cancelled` and no finance result.

### 2.8 Idempotency keys

Optional request header `Idempotency-Key` on the four run-creating endpoints:
`POST /problems/{id}/solver-runs`, `POST /schedules/{id}/replan`, `POST /finance/plans/{id}/runs`,
`POST /finance/plans/{id}/what-if`.
- Format `^[A-Za-z0-9._:-]{1,128}$`, else 422 `VALIDATION_ERROR` (`loc: ["header","idempotency-key"]`).
- `request_hash = sha256(route_kind + "\n" + canonical JSON of path params + body)`; `route_kind` in
  `solver_run|replan|finance_run|what_if`.
- Lookup order inside the creation transaction: **lock the plan/problem row first**, then the idempotency lookup,
  then the one-active-run check. (Looking up before the lock lets a concurrent duplicate pass the lookup, wait on
  the plan lock, then hit the active-run check and return 409 `RUN_ALREADY_ACTIVE` instead of a replay.)
  The lookup is filtered by the current owner: a job with the same
  `(owner_id, idempotency_key)` created within `IDEMPOTENCY_TTL_HOURS=24`:
  same hash -> **202 with the original creation body** (`created_dict` of that run, current `status`) and header
  `Idempotent-Replayed: true`; different hash -> 422 `IDEMPOTENCY_KEY_MISMATCH`
  (`{"error":{"code":"IDEMPOTENCY_KEY_MISMATCH","message":"This Idempotency-Key was used for a different request.","details":{}}}`).
  Older than the TTL: the key is ignored for lookup and the old job's key is set to NULL in the same transaction
  (so the unique index admits the new one).
- Race: two concurrent requests with the same key -> the second insert violates `uq_jobs_idempotency`; the service
  rolls back, re-runs the lookup in a new transaction and replays.
- Without the header behaviour is exactly as today. The 2b UI does not send the header.

### 2.9 Worker process (`python -m superplanner.worker`)

`backend/superplanner/worker/__main__.py` -> `jobs.worker.main(argv)`.

```
python -m superplanner.worker [--concurrency N] [--kinds solver_run,finance_run] [--id NAME] [--once]
                              [--metrics-port PORT]
```
Defaults from env: `WORKER_CONCURRENCY=2`, `WORKER_KINDS=solver_run,finance_run`, `WORKER_ID` (default
`<hostname>:<pid>:<6 hex>`), `WORKER_METRICS_PORT=9101` (0 disables). `--once`: process jobs until the queue is
empty, then exit 0 (tests, cron-style batch).

Startup: load `Settings`; refuse non-Postgres URLs or `JOB_BACKEND=inline` (exit 2, message); configure logging
(service `worker`); `Database(...)`; schema check (3.4: exit 3 if not at head and `DB_AUTO_MIGRATE` is false);
register `job_workers` row; run the reaper once; start heartbeat thread, metrics server, and the claim loop.

Claim loop (main thread): while not stopping: if a slot is free, claim (2.5); on a job, submit
`HANDLERS[kind](wctx, run_id, lease)` to a `ThreadPoolExecutor(concurrency)` with `system_scope()` (4.7) and the
job's `request_id` bound in the logging context. If nothing was claimed, wait for `LISTEN sp_jobs` notification
(dedicated psycopg connection, `conn.notifies(timeout=WORKER_POLL_SECONDS)`) or the poll timeout; if LISTEN fails
it falls back to plain polling. Reaper and maintenance (delete expired sessions, expired rate-limit buckets,
terminal jobs older than `JOB_RETENTION_DAYS=30` in batches of 1000, stale `job_workers`) run from this loop.

CPU note: the GA holds the GIL; for CPU-heavy deployments run more worker processes with `--concurrency 1`
rather than more threads (DEPLOY.md). Pool size per worker: `concurrency + 3` connections.

Graceful shutdown: SIGTERM/SIGINT (Windows: SIGINT/SIGBREAK) -> stop claiming; wait up to
`WORKER_SHUTDOWN_GRACE_SECONDS=30` for running jobs; for jobs still running, in this order: (1) requeue each in a
fenced transaction with reason `worker_shutdown` (attempt not consumed, `run_after = now()`; this clears
`lease_token`, so any later write by the handler fails its fence); (2) set `lost`; (3) set `cancel_event` so the
engine stops. If (1) raises `LeaseLost` the job already finished: skip it. Setting `cancel_event` before the
requeue would let the finance handler's `FinanceCancelled` path write `cancelled` first (race). Then mark
`job_workers.stopped_at`; exit 0. A second signal skips the
grace wait. Compose sets `stop_grace_period: 45s`. SIGKILL: leases expire and the reaper requeues (2.5).

`WorkerContext(settings, db)` implements `RuntimeContext`; handlers must not use `AppContext`-only members
(`executor`, `jobs.dispatch`).

### 2.10 Changes to `run_service.py` / `finance/run_service.py`

- `submit(ctx, run_id)` is removed. Creation paths call `job = ctx.jobs.enqueue(s, kind, run.id, run.owner_id, ...)`
  inside the existing transaction and `ctx.jobs.dispatch(job)` after commit (still outside the transaction, as
  A.16 requires).
- `run_job(ctx, run_id, cancel_event)` becomes `run_job(ctx: RuntimeContext, run_id: str, lease: Lease)`;
  `cancel_event` is `lease.cancel_event`. Start, progress and final transactions are fenced (2.5). Rows created by
  the worker set `owner_id=run.owner_id` explicitly (`ScheduleRow`, `FinanceResultRow`). The finance test seam
  `_before_final_write(run_id)` is kept.
- `cancel_run`, `create_what_if(replace_active)`: `request_cancel` in the transaction, `notify_cancel` after commit
  (replaces `ctx.executor.cancel`).
- `recover_interrupted_runs(ctx)`: only called in inline mode; also sets `jobs.status='failed'` for those runs.
  New `fail_orphan_runs(ctx)` for queue mode (2.5).
- `add_event(s, run_id, type_, fields, elapsed, *, lease: Lease | None = None)`: first
  `SELECT id FROM <runs> WHERE id = :run_id FOR UPDATE` (no-op on file-DB), then `lease.fence(s)` when given, then
  `max(seq)+1` and insert. This makes `seq` allocation safe with several writers (worker, reaper, API cancel).
- Progress writers: a `LeaseLost` raised inside `_write` sets `lease.lost` and `lease.cancel_event` and is not
  logged as an exception; once `lost` is set all further writes are skipped (no per-event stack traces).
- Engine-call exception handling: `except (OperationalError, InterfaceError, DBAPIError)` from DB access ->
  `raise RetryableJobError` (queue mode) / `failed` (inline, unchanged); `except LeaseLost` -> return silently;
  other exceptions -> `failed` as today.

### 2.11 Progress events and SSE across processes

- Events stay in the DB; SSE handlers are unchanged except for the ownership scope (4.7) and a new event type.
  Any API instance can stream any run because state is only in the DB. Reconnects with `Last-Event-ID` work
  across instances.
- New SSE event `run_requeued` (2.6), non-terminal. `TERMINAL_EVENT_TYPES` unchanged. The frontend shows
  "Restarting on another worker (attempt 2 of 3)" in `RunProgress` / finance progress; unknown events were already
  ignored, so old clients keep working.
- Poll cost: one indexed query per stream per 0.5 s (`uq_run_event_seq` covers `run_id, seq > :after`). The
  stream acquires a pooled connection only during each poll. LISTEN/NOTIFY push is deferred (9).
- Authorization is checked once when the stream opens; a stream ends with the run at the latest (max ~5 min).

### 2.12 Multi-process consistency (replacing `WRITE_LOCK`)

- `context.WRITE_LOCK` is replaced by `ctx.write_guard()` (context manager): file-DB -> the existing process-wide
  RLock (behaviour unchanged); Postgres -> `contextlib.nullcontext()`. Every `with WRITE_LOCK` site changes to
  `with ctx.write_guard()` (sites: `problem_service.update/delete`, `run_service.create_run/cancel_run/
  recover/run_job`, `replan_service.replan`, `schedule_service.approve`, `finance/service.update/delete`,
  `finance/run_service.create_run/create_what_if/cancel_run/recover/_finish/run_job`). `WRITE_LOCK` stays exported
  as an alias for one release for any test that imports it.
- Row locks (Postgres `SELECT ... FOR UPDATE`; ignored on file-DB where `BEGIN IMMEDIATE` already serialises):
  `get_problem_row(s, id, lock: bool = False)`, `get_plan_row(s, id, lock=False)`, and
  `lock_run(s, Model, id)`. `lock=True` at: problem update/delete, solver create_run, replan, schedule approve
  (lock the problem before reading approved schedules), finance update/delete/create_run/create_what_if; run
  row lock in cancel, start/progress/final transactions, reaper.
- **Lock order** (deadlock avoidance, mandatory): plan/problem row -> run row -> job row. The claim transaction
  locks only the job row and touches nothing else.
- **Lock strength** (mandatory, review note R4): plan/problem and run locks use `with_for_update(key_share=True)`
  (`FOR NO KEY UPDATE`); only `delete_problem` / `delete_plan` use plain `FOR UPDATE`. Reason: inserting a child row
  (schedule, finance result, event) takes an implicit `FOR KEY SHARE` on the referenced parent. With plain
  `FOR UPDATE` on the plan, this deadlocks: what-if `replace_active` holds the plan lock and waits for the active
  run's row, while that run's worker holds the run row in its final transaction and waits for `KEY SHARE` on the
  plan to insert `finance_results`. `FOR NO KEY UPDATE` does not conflict with `FOR KEY SHARE`. Worker final
  transactions that insert plan children additionally take `FOR KEY SHARE` on the plan row *before* locking the run
  row, so the implicit FK lock also follows the lock order.
- Partial unique indexes as backstop (both dialects):
  - `uq_solver_runs_one_active` on `solver_runs(problem_id)` WHERE `status IN ('queued','running')`.
  - `uq_schedules_one_approved` on `schedules(problem_id)` WHERE `status = 'approved'` (approve flushes the
    superseded rows before setting the new one, as it already does).
  - **No** `uq_finance_runs_one_active` (removed in review, R5): the existing test
    `test_startup_recovery_marks_runs_failed` inserts a `queued` and a `running` run for one plan, which such an
    index would reject. The finance one-active rule is enforced by the plan row lock taken by every run-creating path
    (`create_run`, `create_what_if`), which is sufficient on both dialects.
  An `IntegrityError` from these indexes is mapped by the services to the same 409 as the explicit check
  (`RUN_ALREADY_ACTIVE` / approval retried once).
- Event `seq` and SSE: because `add_event` holds the run row lock until commit, events of one run commit in `seq`
  order, so an SSE poll (`seq > cursor`) can never see seq n+1 before n and skip n permanently. Do not remove the lock.
- `If-Match`: the row is read with `lock=True`, so check-then-update is atomic on Postgres.
- Postgres isolation level: READ COMMITTED (default) everywhere.

---

## 3. Part B - PostgreSQL as the production database

### 3.1 Engine, driver, pooling

- Driver: psycopg 3 (`psycopg[binary]==3.3.6`). `Settings.database_url` normalisation: `postgres://` and
  `postgresql://` -> `postgresql+psycopg://`. `Database.is_postgres` added.
- Postgres engine: `create_engine(url, pool_size=DB_POOL_SIZE (10), max_overflow=DB_MAX_OVERFLOW (10),
  pool_timeout=DB_POOL_TIMEOUT_SECONDS (30), pool_pre_ping=True, pool_recycle=1800,
  connect_args={"options": f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS} -c lock_timeout=10000",
  "application_name": f"superplanner-{service}"})`, `DB_STATEMENT_TIMEOUT_MS` default 30000. Size the pool to
  `uvicorn threadpool (40) / 2 + SSE`: defaults are fine for one API instance; documented in DEPLOY.md.
- file-DB engine unchanged (WAL, FKs, `BEGIN IMMEDIATE`, `check_same_thread=False`).
- JSON documents: `JsonType` already maps to `JSONB` on Postgres; no GIN indexes in 2b (no JSON queries).

### 3.2 Alembic layout and migrations

```
backend/alembic.ini                         script_location = superplanner/migrations
backend/superplanner/migrations/env.py      target_metadata = Base.metadata (imports db.models and finance.db_models);
                                            URL from -x url=..., else DATABASE_URL, else Settings default;
                                            render_as_batch=True on file-DB; compare_type=True
backend/superplanner/migrations/script.py.mako
backend/superplanner/migrations/versions/0001_initial.py    revision "0001_initial": the 11 tables exactly as
                                            create_all builds them today (columns, FKs ON DELETE CASCADE, indexes
                                            ix_problem_versions_hash, ix_solver_runs_problem_created,
                                            ix_solver_runs_status, uq_run_event_seq, ix_schedules_problem_status,
                                            ix_finance_plan_versions_hash, ix_finance_runs_plan_created,
                                            ix_finance_runs_status, uq_finance_run_event_seq,
                                            ix_finance_results_plan_created)
backend/superplanner/migrations/versions/0002_phase2b.py    revision "0002_phase2b", down_revision "0001_initial"
backend/superplanner/migrate.py             CLI + ensure_schema() (3.4)
```
Pins: `alembic==1.20.0`, `psycopg[binary]==3.3.6`, `argon2-cffi==25.1.0`, `prometheus-client==0.26.0` (all have
Windows wheels; `psycopg` is imported lazily so file-DB dev never loads it). Migration files are **frozen**: they use
literal `op.create_table`/`op.add_column` definitions and never import the ORM models (models will keep changing).
After Q1 the schema is frozen for 2b; a later change needs a new revision `0003_*`, serialized by the lead (two
parallel revisions would create two Alembic heads).
Migrations live inside the package so the Docker image and `pip install` carry them. Every migration has a working
`downgrade()` (file-DB via `batch_alter_table`); the supported production rollback is still "restore the backup".

### 3.3 Schema changes in `0002_phase2b` (complete list)

New tables: `users`, `user_sessions`, `auth_rate_limits` (4.2), `jobs`, `job_workers` (2.3).

Data step (in this order): insert the local user
`("usr_local", email NULL, display_name "Local user", password_hash NULL, is_local true, now)`; add `owner_id`
nullable to owned tables, `UPDATE ... SET owner_id = 'usr_local'`, then set NOT NULL and add FK `users.id`
(ON DELETE RESTRICT). Active legacy runs are not touched by the migration (startup handles them, 2.5).

Owned tables and their new column `owner_id String(64) NOT NULL FK users.id`:
`problems`, `solver_runs`, `schedules`, `finance_plans`, `finance_runs`, `finance_results`, `jobs` (created with
it). Child tables reached only through an owned parent (`problem_versions`, `finance_plan_versions`,
`solver_run_events`, `finance_run_events`) get no `owner_id`. Children copy the owner of their root and it never
changes (sharing, when added, is resolved at the root: 9).

Other column changes:
- `audit_events.actor_id String(64) NULL` (user id; no FK, audit survives user deletion).
- `solver_run_events.id`, `finance_run_events.id`, `audit_events.id`: `BigInteger().with_variant(Integer, "file-DB")`
  (int8 on Postgres; file-DB keeps `INTEGER PRIMARY KEY` autoincrement).

New indexes (hot queries named):
| Index | Query |
|---|---|
| `ix_problems_owner_updated (owner_id, updated_at, id)` | `list_problems` |
| `ix_finance_plans_owner_updated (owner_id, updated_at, id)` | `finance list_plans` |
| `ix_schedules_run_rank (solver_run_id, rank)` | `schedule_ids_for` (called by every `run_dict`) |
| `ix_schedules_problem_version (problem_version_id)` | cascade deletes |
| `ix_solver_runs_problem_version (problem_version_id)` | cascade deletes |
| `ix_finance_runs_plan_version (plan_version_id)` | cascade deletes |
| `ix_finance_results_plan_version (plan_version_id)` | cascade deletes |
| `uq_finance_results_run (run_id)` unique | `_result_id_for`, invariant I3 |
| `ix_audit_entity (entity_type, entity_id, created_at)` | audit lookups |
| `uq_solver_runs_one_active`, `uq_schedules_one_approved` (partial) | 2.12 |
| `ix_solver_runs_status`, `ix_finance_runs_status` | kept (recovery, orphan scan) |
| jobs / sessions / rate-limit indexes | 2.3, 4.2 |

The ORM models are updated to declare exactly the same (including `OwnedMixin` in 4.7) so that
`compare_metadata(upgrade head) == Base.metadata` (test 3.6).

### 3.4 Startup schema handling and the legacy file-DB upgrade path

`superplanner/migrate.py`:
```python
HEAD = "0002_phase2b"
def schema_state(db) -> Literal["empty", "legacy", "behind", "current", "ahead"]
def ensure_schema(db, settings) -> None
def main(argv) -> int     # python -m superplanner.migrate {upgrade,current,check,stamp-legacy} [--url URL]
```
- `empty` (no tables): `Base.metadata.create_all()` + `alembic stamp head` + `ensure_local_user()`.
- `legacy` (has `problems`, no `alembic_version`): the table set must be a subset of the 0001 set that contains
  `problems` (a file last opened before the finance phase lacks the 5 finance tables: create the missing ones from
  the frozen 0001 definitions); unknown tables or missing columns of existing tables -> exit 3 with a message naming
  them. file-DB: back up first to `<db>.bak-0001-<UTC yyyymmddHHMMSS>` using the file-DB online backup API
  (its online backup API) or `VACUUM INTO` - **never a plain file copy**: in WAL mode committed pages may still
  be in `<db>-wal`, so a copy of the main file alone can be stale or corrupt (and on Windows the file may be
  locked). Then `stamp 0001_initial`; `upgrade head`.
- **file-DB migrations run with `PRAGMA foreign_keys=OFF`** (review note R1, reproduced): Alembic batch mode
  recreates a table (`CREATE _alembic_tmp_x`, copy, `DROP TABLE x`, rename). With foreign keys ON, `DROP TABLE
  problems` performs an implicit `DELETE` that fires `ON DELETE CASCADE` and **erases every problem version, run,
  event and schedule**. `migrate.py` therefore uses its own file-DB engine without the `Database` connect listener,
  executes `PRAGMA foreign_keys=OFF` outside any transaction, runs the upgrade in one transaction, runs `PRAGMA
  foreign_key_check` (any row -> roll back, exit 3, keep the backup), then re-enables FKs. The legacy-upgrade test
  asserts the row count of all 11 tables is unchanged.
- Postgres migrations run with `SET statement_timeout = 0` and `lock_timeout = '60s'` (the API's 30 s statement
  timeout would abort index builds on large tables).
- `behind`: `upgrade head` if `DB_AUTO_MIGRATE` (file-DB database backup first, as above), else exit 3:
  `"Database schema is at <rev>, code needs 0002_phase2b. Run: python -m superplanner.migrate upgrade"`.
- `ahead` (unknown newer revision): exit 3.
- Postgres: the whole function runs under `pg_advisory_lock(727001)` so concurrently starting instances migrate once.
- `DB_AUTO_MIGRATE` default: true for file-DB, false for Postgres. Compose runs a one-shot `migrate` service.
- `ensure_local_user()` (idempotent insert of `usr_local`) also runs on every start.
- `AppContext.start()` calls `ensure_schema` instead of `create_all`; `Database.create_all()` stays for tests.

Existing file-DB dev databases therefore upgrade automatically on the first start of the 2b code, keeping all data
(owned by `usr_local`). file-DB -> Postgres data copy is not automated in 2b: use the existing export/import
endpoints per plan (documented in DEPLOY.md, tool deferred).

### 3.5 Dialect differences the code must respect

1. `String(n)` is enforced on Postgres (ignored by file-DB). Every write of a free-text value into a bounded column
   must be bounded by the Pydantic model or truncated at write (`label[:100]` pattern). Known: `schedules.label`
   (64), `schedules.solver` (64), `solver_runs.termination_reason` (32), `audit_events.action` (64). The Postgres
   test run is the check.
2. JSONB does not preserve object key order or duplicate keys. Key order of stored documents is **not** part of
   the API contract; tests compare parsed dicts. (`result_summary` already orders keys explicitly.)
3. Timestamps come back timezone-aware on Postgres, naive on file-DB; always go through `as_utc` (existing).
4. Booleans: query with `.is_(False)` / `== False` both fine; partial-index predicates use `= false`.
5. Row locks: `with_for_update()` is a no-op on file-DB (serialised by `BEGIN IMMEDIATE`).
6. Never use raw SQL in services except `jobs/pg.py` (claim/heartbeat/reaper) and migrations; those are
   Postgres-only, inline mode uses ORM statements. Never insert owned rows with Core `insert()` (it bypasses the
   `before_flush` owner stamp); use `s.add`.
7. Postgres `TEXT`/`JSONB` cannot store U+0000; file-DB can. A JSON body containing `\u0000` anywhere is rejected
   with 422 `VALIDATION_ERROR` on **both** dialects (one check in the body-limit middleware path or a shared
   validator), so behaviour does not depend on the database. JSONB also rejects `NaN`/`Infinity`: the Postgres
   engine uses `json_serializer=partial(json.dumps, allow_nan=False)`; the Postgres test run is the check.
8. Text ordering: Postgres collations differ from file-DB's binary order. Test clusters are created with
   `initdb --locale=C --encoding=UTF8`; the compose database uses `POSTGRES_INITDB_ARGS=--locale=C.UTF-8`.

### 3.6 Dual-database test strategy

- New root `backend/tests/conftest.py`:
  - `pytest_addoption("--db", choices=["file-DB","postgres"], default=os.environ.get("SP_TEST_DB","file-DB"))`.
  - `SP_TEST_PG_URL` (admin URL to an existing server, e.g.
    `postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres`; the role needs CREATEDB).
  - Session fixture `pg_template`: creates `sp_tpl_<pid>`, runs `alembic upgrade head` into it, disposes engines.
  - Fixture `db_url_factory`: callable `new(name: str) -> str`. file-DB: `<file-DB URL>` (fresh
    file; app start does create_all + stamp). Postgres: `CREATE DATABASE sp_t_<uuid8> TEMPLATE sp_tpl_<pid>
    STRATEGY FILE_COPY`; finalizer `DROP DATABASE ... WITH (FORCE)`. Module-scoped variant
    `db_url_factory_module` for `shared_fin`.
  - Autouse fixture setting env per test (via `monkeypatch.setenv`): `PASSWORD_HASH_PROFILE=fast`; on Postgres
    `JOB_BACKEND=queue`, `WORKER_EMBEDDED=auto`, `JOB_CANCEL_POLL_SECONDS=0.2`, `WORKER_POLL_SECONDS=0.2`; tests
    marked `inline_jobs` get `JOB_BACKEND=inline`.
  - Markers: `postgres_only`, `file_db_only`, `inline_jobs`, `pg_load` (registered in `pyproject.toml`).
  - Embedded workers run in the test process (threads), never subprocesses, so existing tests that monkeypatch
    `run_service._before_final_write`, `run_service.finance.run_plan` or `validate_result` keep working on Postgres.
- Every folder conftest's `db_url` fixture becomes `return db_url_factory("<name>")` (names unchanged:
  `api`, `apifin`, `int`, `finint`, `p2int`, `intake`). Helper `make_app` functions are unchanged
  (`Settings` reads the env).
- Helper script `backend/scripts/pg_dev_cluster.sh {init|start|stop|url} [DIR] [PORT]`: `initdb` (as the non-root
  OS user `spdb`, created with `useradd -r -m spdb` if running as root; `runuser -u spdb --`), `trust` auth on
  127.0.0.1 only, port default 54329, creates role `sp_test` with CREATEDB and password `sp_test`. Default `DIR`:
  `backend/.pgdata` (git-ignored); CI/agents pass their scratch dir.
- Commands:
  ```
  cd backend && .venv/bin/pytest                                     # file-DB, inline (as today)
  SP_TEST_DB=postgres SP_TEST_PG_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres \
      .venv/bin/pytest                                               # PostgreSQL, queue + embedded workers
  ```
  Both must pass fully (engine/finance pure tests simply run twice). Pure-Postgres tests skip on file-DB and vice
  versa with a visible reason.
- New test folders: `backend/tests/db/` (migrations: empty->head equals metadata on both dialects via
  `alembic.autogenerate.compare_metadata`; legacy file-DB database created from frozen 0001 metadata with data upgrades
  and backfills `usr_local`; downgrade/upgrade round trip; partial unique indexes reject a second active run and a
  second approval under two threads/connections; `add_event` seq under concurrent writers on Postgres),
  `backend/tests/jobs/` (2.4-2.9: SKIP LOCKED with 3 concurrent claimers never double-claims; lease expiry ->
  requeue -> completes once; max attempts -> failed with `WORKER_LOST_ERROR`; stale lease cannot `finish`
  (LeaseLost) and writes no events; cancel running via DB flag ends within 3 s; shutdown requeues without
  consuming an attempt; idempotency replay/mismatch/race; NOTIFY wake-up latency < 1 s; `kill -9` of a worker
  subprocess -> another worker completes the run; two `TestClient` apps on one Postgres DB: create on A, SSE on B),
  `backend/tests/auth/` (4.x), `backend/tests/ops/` (5.x).

---

## 4. Part C - User accounts and access control

### 4.1 `AUTH_MODE`

`Settings.auth_mode: Literal["single_user","accounts"]`; env `AUTH_MODE`; default `accounts` when
`SP_ENV=production`, else `single_user`. `SP_ENV=production` with `single_user` refuses to start unless
`ALLOW_SINGLE_USER_IN_PRODUCTION=true`.

- **single_user**: no login screen, no cookies, no CSRF; every request runs as `usr_local`; auth mutation
  endpoints answer 409 `AUTH_DISABLED`; `GET /auth/session` reports the local user. API responses and behaviour are
  byte-for-byte as today (existing tests and e2e unchanged).
- **accounts**: every `/api/v1` endpoint except the public ones (4.8) requires a valid session; unauthenticated ->
  401 `AUTH_REQUIRED`. `usr_local` still owns legacy data but cannot sign in (no password); an admin can move its
  data to a real account with `manage reassign-owner` (4.9).

### 4.2 Tables `users`, `user_sessions`, `auth_rate_limits`

`users` (`UserRow`, `api/auth/models.py`, registered on the shared `Base`):
`id String(64)` PK (`usr_<hex>`; `usr_local` fixed), `email String(254)` NULL unique (stored trimmed + lower-cased;
unique index `uq_users_email`), `display_name String(100)` NULL, `password_hash Text` NULL, `is_local Boolean`
default false, `disabled Boolean` default false, `created_at`, `updated_at`, `password_changed_at` NULL,
`last_login_at` NULL.

`user_sessions` (`UserSessionRow`): `id String(64)` PK (`ses_<hex>`), `user_id` FK users ON DELETE CASCADE,
`token_hash String(64)` unique (sha256 hex of the cookie token), `csrf_token String(64)` not null,
`created_at`, `last_seen_at`, `expires_at` (absolute), `revoked_at` NULL, `user_agent String(200)` NULL,
`ip String(45)` NULL. Indexes: `uq_user_sessions_token`, `ix_user_sessions_user (user_id)`,
`ix_user_sessions_expires (expires_at)`.

`auth_rate_limits` (`AuthRateLimitRow`): `bucket String(160)` PK, `window_start DateTime(tz)`, `count Integer`.
Index `ix_auth_rate_limits_window (window_start)` for cleanup.

### 4.3 Passwords

- `argon2-cffi==25.1.0`, `PasswordHasher` argon2id with library defaults (t=3, m=64 MiB, p=4) for profile
  `default`; profile `fast` (t=1, m=8 MiB, p=1) for tests only (`PASSWORD_HASH_PROFILE`, refused when
  `SP_ENV=production`). `check_needs_rehash` on successful sign-in -> rehash in the same transaction.
- Policy (NIST-style): length 10..256 characters after NFKC normalisation, not equal to the email, not in a small
  bundled list of the 1000 most common passwords (`api/auth/common_passwords.txt`). No composition rules.
- Unknown email at sign-in: verify against a constant dummy hash so timing matches.
- Password reset by email is deferred; admins use `manage set-password`.

### 4.4 Session cookie and CSRF design

- Session token: `secrets.token_urlsafe(32)`; cookie value = token; DB stores `sha256(token)`.
- Cookie name: `__Host-sp_session` when `COOKIE_SECURE=true` (production default), else `sp_session` (dev over
  http). Attributes: `HttpOnly; Path=/; SameSite=Lax; Max-Age=<seconds to expires_at>`; `Secure` when
  `COOKIE_SECURE`; never a `Domain` attribute.
- Lifetime: absolute `SESSION_MAX_AGE_DAYS=30`, idle `SESSION_IDLE_DAYS=7` (`last_seen_at` older -> invalid);
  `last_seen_at` is updated at most every 5 minutes (avoids a write per request). Sign-in always creates a new
  session (no fixation). Change-password rotates the current session and revokes all others.
- CSRF (synchronizer token): each session has a random `csrf_token`, returned in the JSON of `GET /auth/session`,
  sign-in, sign-up and change-password. The SPA keeps it in memory and sends `X-CSRF-Token: <token>` on every
  `POST/PUT/PATCH/DELETE`. The `require_user` dependency compares it with `hmac.compare_digest`; missing/wrong ->
  403 `CSRF_FAILED`. Additionally, if an `Origin` header is present on an unsafe request it must be in
  `CORS_ORIGINS` or equal `PUBLIC_BASE_URL` origin, else 403 `CSRF_FAILED`. Sign-in and sign-up have no session
  yet: they are exempt from the token but subject to the Origin check (plus SameSite=Lax).
  Rationale vs double-submit: no server secret needed, token rotates with the session, works with
  `EventSource` (GET only, no token needed).
- CORS: `allow_credentials = (auth_mode == "accounts")`; origins must be explicit (never `*`). **Production
  default for `CORS_ORIGINS` is empty** (same-origin deployment); the four localhost origins are a dev default only.
  Otherwise any page served on a visitor's `localhost:5173` could read `GET /auth/session` (incl. `csrf_token`)
  with credentials from a production API. `ConfigError` if `CORS_ORIGINS` contains `*` while `allow_credentials`.
  Add `X-CSRF-Token`,
  `Idempotency-Key`, `X-Request-ID` to allowed headers (already `*`) and `X-Request-ID`, `Idempotent-Replayed`,
  `Retry-After` to exposed headers. The normal deployment is same-origin (nginx/Vite proxy).

### 4.5 Auth endpoints (JSON, error codes)

Router `api/auth/router.py`, prefix `/api/v1/auth`. All bodies `extra="forbid"`. User object:
```json
{"id": "usr_3f2a...", "email": "ana@example.com", "display_name": "Ana", "is_local": false,
 "created_at": "2026-10-19T08:00:00Z"}
```
Session object (`SessionInfo`):
```json
{"auth_mode": "accounts", "authenticated": true, "user": { ...user... },
 "csrf_token": "q8V...", "expires_at": "2026-11-18T08:00:00Z", "signup_enabled": true}
```

1. `GET /auth/session` (public) -> 200 always.
   - accounts, no/invalid session: `{"auth_mode":"accounts","authenticated":false,"user":null,"csrf_token":null,
     "expires_at":null,"signup_enabled":true}` (an invalid cookie is cleared with `Set-Cookie ...; Max-Age=0`).
   - single_user: `{"auth_mode":"single_user","authenticated":true,"user":{"id":"usr_local","email":null,
     "display_name":"Local user","is_local":true,"created_at":"..."},"csrf_token":null,"expires_at":null,
     "signup_enabled":false}`.
2. `POST /auth/sign-up` (public) body `{"email":"ana@example.com","password":"correct horse battery",
   "display_name":"Ana"}` (`display_name` optional, 1..100) -> **201** `SessionInfo` + `Set-Cookie`. If the
   request carries a valid session cookie, that session is revoked (same for sign-in).
   Errors: 422 `VALIDATION_ERROR` (bad email: must match `^[^@\s]+@[^@\s]+\.[^@\s]+$`, <= 254),
   422 `WEAK_PASSWORD` (`details: {"reasons": ["too_short"|"too_long"|"common"|"same_as_email"]}`),
   409 `EMAIL_TAKEN`, 403 `SIGNUP_DISABLED` (`SIGNUP_ENABLED=false`), 403 `CSRF_FAILED` (Origin), 429
   `RATE_LIMITED`, 409 `AUTH_DISABLED` (single_user).
3. `POST /auth/sign-in` (public) body `{"email":"ana@example.com","password":"..."}` -> 200 `SessionInfo` +
   `Set-Cookie`. Errors: 401 `INVALID_CREDENTIALS` ("The email or password is not correct.", also for disabled
   accounts and `usr_local`), 422 `VALIDATION_ERROR`, 403 `CSRF_FAILED` (Origin), 429 `RATE_LIMITED`,
   409 `AUTH_DISABLED`.
4. `POST /auth/sign-out` (session + CSRF token if a valid session exists) -> 204, revokes the session, clears the
   cookie. Without a valid session -> 204 (idempotent). Wrong/missing CSRF with a valid session -> 403.
   single_user -> 409 `AUTH_DISABLED`.
5. `POST /auth/change-password` (session + CSRF) body `{"current_password":"...","new_password":"..."}` ->
   200 `SessionInfo` (new cookie, new `csrf_token`; all other sessions revoked). Errors: 401 `AUTH_REQUIRED`,
   403 `CSRF_FAILED`, 422 `WRONG_PASSWORD` (current password wrong; deliberately not 401 so the UI does not treat it
   as an expired session), 422 `WEAK_PASSWORD`, 429 `RATE_LIMITED`, 409 `AUTH_DISABLED`.

Errors on all protected endpoints: 401 `AUTH_REQUIRED` ("Please sign in to continue.") and 403 `CSRF_FAILED`
("Your session could not be verified. Reload the page and try again."). Error envelope unchanged (A.14). 429
responses carry `Retry-After: <seconds>` and `details: {"retry_after_seconds": n}`. `errors._HTTP_CODES` gains
`401: "AUTH_REQUIRED"`, `403: "FORBIDDEN"`, `429: "RATE_LIMITED"`.

### 4.6 Rate limiting

DB-backed fixed windows (shared by all API instances), `api/auth/ratelimit.py::hit(s, bucket, limit, window) ->
(allowed, retry_after)`: one upsert
`INSERT ... ON CONFLICT (bucket) DO UPDATE SET window_start = CASE WHEN window_start < :now - :window THEN :now
ELSE window_start END, count = CASE WHEN window_start < :now - :window THEN 1 ELSE count + 1 END RETURNING ...`
(dialect `insert` of `sqlalchemy.dialects.postgresql` / `file-DB`). Counted **before** password verification.

| Endpoint | Buckets (all must allow) | Default |
|---|---|---|
| sign-in | `signin:ip:<ip>`; `signin:email:<sha256(email)>` | 30 / 5 min; 10 / 5 min |
| sign-up | `signup:ip:<ip>` | 5 / hour |
| change-password | `chpw:user:<id>` | 10 / 15 min |

Env: `AUTH_RATE_LIMIT_ENABLED` (true), `AUTH_SIGNIN_LIMIT_PER_IP` (30), `AUTH_SIGNIN_LIMIT_PER_EMAIL` (10),
`AUTH_SIGNUP_LIMIT_PER_IP` (5). Client IP = `request.client.host`; behind a proxy uvicorn runs with
`--proxy-headers --forwarded-allow-ips=$FORWARDED_ALLOW_IPS` so this is the real client. **Caveat (verified in
uvicorn 0.54 `ProxyHeadersMiddleware`): with `FORWARDED_ALLOW_IPS=*` uvicorn takes the *leftmost* `X-Forwarded-For`
entry**, which is client-controlled if the proxy appends (`$proxy_add_x_forwarded_for`); every request could then
claim a new IP and bypass the per-IP limits. Therefore nginx **overwrites** the header with one value
(`proxy_set_header X-Forwarded-For $remote_addr;`), using `set_real_ip_from ${TRUSTED_PROXY_CIDRS}` +
`real_ip_header X-Forwarded-For` + `real_ip_recursive on` when an external load balancer sits in front; compose gives
the internal network a fixed subnet and sets `FORWARDED_ALLOW_IPS` to it (not `*`). A test sends a spoofed
`X-Forwarded-For` through the nginx config (or asserts the config text) and checks the bucket key.
A successful sign-in does not reset counters (simple, predictable). Accepted risks (documented in DEPLOY.md): the
per-email bucket lets an attacker temporarily lock a known email out of sign-in; `409 EMAIL_TAKEN` reveals
registered emails (rate-limited to 5/hour/IP).

### 4.7 Ownership enforcement (one central mechanism)

Files: `api/db/ownership.py` (ORM layer, WP-1), `api/auth/deps.py` (principal resolution, WP-1 single_user form,
WP-3 accounts form).

```python
# api/db/ownership.py
class OwnedMixin:                       # mixed into ProblemRow, SolverRunRow, ScheduleRow, FinancePlanRow,
    owner_id: Mapped[str]               # FinanceRunRow, FinanceResultRow, JobRow
SYSTEM = object()
_owner: ContextVar[str | object | None]          # None = unbound
_in_request: ContextVar[bool]                     # set by OwnershipScopeMiddleware for every HTTP request
def current_owner() -> str | object | None
@contextmanager
def owner_scope(user_id: str)                     # binds a user (used by require_user and SSE polls)
@contextmanager
def system_scope()                                # workers, reaper, recovery, migrations, CLI
class OwnershipViolation(RuntimeError)            # -> 500 INTERNAL_ERROR, logged at ERROR with the statement
def install(db: Database, single_user: bool) -> None
class OwnershipScopeMiddleware                    # pure ASGI; sets _in_request=True for http scopes
```

`install` registers on the Database's session factories:
1. `do_orm_execute`: if the statement is a SELECT/UPDATE/DELETE whose `all_mappers` include an `OwnedMixin`
   subclass: owner = `current_owner()`; `SYSTEM` -> unchanged; a user id -> add
   `with_loader_criteria(OwnedMixin, lambda cls: cls.owner_id == owner, include_aliases=True)`; unbound -> if
   `_in_request` is true raise `OwnershipViolation` (**fail closed**), else treat as system (tests, CLI, inline
   worker threads, which do not inherit request context vars).
2. `before_flush`: for each new `OwnedMixin` instance with `owner_id is None`: bound user -> set it; unbound/system
   -> `usr_local` if `single_user` else raise `OwnershipViolation`. Workers always set `owner_id` explicitly.

Consequences, with **no per-route code**: `get_problem_row`, `get_plan_row`, `get_schedule_row`, `s.get(Run, id)`,
list queries, compare endpoints, `base_result_id` lookups and Core-style ORM `delete(ProblemRow)` are all filtered,
so another user's object raises the existing `not_found(...)` -> 404 with exactly the same body as an unknown id.
Inserts in request context (create, import, instantiate, send-to-planner, runs, schedules from approve/replan)
are stamped with the current user. Ids are UUID4 hex, so 404s give no enumeration signal.

`api/auth/deps.py`:
```python
@dataclass(frozen=True)
class Principal:
    user_id: str
    session_id: str | None        # None in single_user
    csrf_token: str | None
    is_local: bool

async def require_user(request: Request, ctx: AppContext = Depends(get_ctx)) -> Principal:
    """async on purpose: the ContextVar set here must be visible to sync endpoints (threadpool copies context).
    single_user: Principal('usr_local', None, None, True).
    accounts: read cookie -> session lookup joined with users (in run_in_threadpool, system scope) -> 401
    AUTH_REQUIRED if missing, revoked, expired, idle, or the user is disabled (`disable-user` also revokes all the
    user's sessions); unsafe method -> CSRF + Origin checks (403 CSRF_FAILED); touch last_seen_at
    (throttled). Then: set request.state.principal, bind owner (token = _owner.set(user_id); the var lives for
    the request task)."""
```
Wiring in `create_app`: `app.include_router(r, prefix=API_PREFIX, dependencies=[Depends(require_user)])` for
`templates, problems, solver_runs, schedules, finance_router, intake_router`; `health.router` and
`auth.router` without it (auth routes resolve the session themselves). SSE generators capture
`owner = request.state.principal.user_id` and wrap each `list_events` poll in `owner_scope(owner)`.
Audit rows get `actor_id` from `current_owner()` when it is a user id.

Mandatory `system_scope()` sites inside HTTP requests (otherwise the fail-closed rule turns them into 500s, review
note R9): `AppContext.start()` as a whole (it runs lazily from `get_ctx` on the first request when a `TestClient` is
used without `with`, i.e. with `_in_request=True` and before `require_user` bound a user - it runs
`recover_interrupted_runs` / `fail_orphan_runs` on owned tables); `/health/ready` queue counts; the Prometheus
queue-depth collector behind `/metrics`; the session lookup in `require_user`.

Verified facts this design relies on (FastAPI 0.143 / Starlette 1.8, checked with a probe app): a ContextVar set in
an **async** dependency attached via `include_router(dependencies=...)` is visible in sync endpoints, in a
`StreamingResponse` generator and in its `run_in_threadpool` calls; a **sync** dependency's ContextVar is NOT
visible. A unit test asserts `inspect.iscoroutinefunction(require_user)`. `with_loader_criteria` from
`do_orm_execute` filters `Session.get`, column-only selects, `count`, `exists()`, ORM `update()` and `delete()`
(SQLAlchemy 2.1.4, probe-verified); the test suite keeps one probe test per form.

Coverage tests (`tests/auth/test_route_coverage.py`): (a) **black-box**: in accounts mode, for every
(method, path) in `app.openapi()["paths"]` under `/api/v1` except the allowlist {`/health`, `/health/live`,
`/health/ready`, `/auth/session`, `/auth/sign-up`, `/auth/sign-in`, `/auth/sign-out`, `/auth/change-password`},
a request without a cookie (path params = random ids, body `{}` or an invalid body) returns 401 `AUTH_REQUIRED` -
never 404/422/2xx. (Walking `app.routes` for dependant trees does not work in this FastAPI version: included
routers appear as opaque `_IncludedRouter` objects.) A second assertion compares the enumerated set with the 4.8
table so new routes cannot be added silently; (b) cross-user matrix: user A creates one of
each object (problem, run, schedule, finance plan, run, result, what-if result); user B calls **every** endpoint of
4.8 with A's ids -> 404 `NOT_FOUND` (body equal to an unknown-id call), list endpoints omit A's objects,
`compare` with one foreign id -> 404, B's `send-to-planner` of A's result -> 404, A's objects unchanged afterwards.

Sharing later (9): add `plan_members(root_type, root_id, user_id, role)`; criteria becomes
`owner_id = :u OR <root> IN (memberships of :u)` in this one place.

### 4.8 Endpoint access table (every endpoint)

Legend: **Auth** P = public, U = `require_user`. **CSRF** = token required in accounts mode (all unsafe methods on
U routes). **Owned lookup** = which filtered row(s) produce 404 for other users. **Stamps** = rows inserted with the
caller as owner.

| # | Method and path (`/api/v1`) | Auth | CSRF | Owned lookup -> 404 | Stamps owner on |
|---|---|---|---|---|---|
| 1 | GET `/health` | P | - | - | - |
| 2 | GET `/health/live` (new) | P | - | - | - |
| 3 | GET `/health/ready` (new) | P | - | - | - |
| 4 | GET `/auth/session` (new) | P | - | - | - |
| 5 | POST `/auth/sign-up` (new) | P | Origin | - | users, user_sessions |
| 6 | POST `/auth/sign-in` (new) | P | Origin | - | user_sessions |
| 7 | POST `/auth/sign-out` (new) | session | yes | - | - |
| 8 | POST `/auth/change-password` (new) | session | yes | - | user_sessions |
| 9 | GET `/templates` | U | - | - | - |
| 10 | POST `/templates/{template_id}/instantiate` | U | yes | - | problems |
| 11 | GET `/problems` | U | - | list filtered | - |
| 12 | POST `/problems` | U | yes | - | problems |
| 13 | POST `/problems/import` | U | yes | - | problems |
| 14 | GET `/problems/{problem_id}` | U | - | problem | - |
| 15 | PUT `/problems/{problem_id}` | U | yes | problem (locked) | - |
| 16 | DELETE `/problems/{problem_id}` | U | yes | problem (locked) | - |
| 17 | GET `/problems/{problem_id}/export` | U | - | problem | - |
| 18 | POST `/problems/{problem_id}/validate` | U | yes | problem | - |
| 19 | POST `/problems/{problem_id}/solver-runs` | U | yes | problem (locked) | solver_runs, jobs |
| 20 | GET `/problems/{problem_id}/solver-runs` | U | - | problem; runs filtered | - |
| 21 | GET `/solver-runs/{run_id}` | U | - | solver run | - |
| 22 | POST `/solver-runs/{run_id}/cancel` | U | yes | solver run (locked) | - |
| 23 | GET `/solver-runs/{run_id}/events` (SSE / `stream=false`) | U | - | solver run (each poll) | - |
| 24 | GET `/problems/{problem_id}/schedules` | U | - | problem; schedules filtered | - |
| 25 | GET `/schedules/compare?a=&b=` | U | - | both schedules | - |
| 26 | GET `/schedules/{schedule_id}` | U | - | schedule | - |
| 27 | POST `/schedules/{schedule_id}/approve` | U | yes | schedule, problem (locked) | - |
| 28 | GET `/schedules/{schedule_id}/export.csv` | U | - | schedule | - |
| 29 | POST `/schedules/{schedule_id}/replan` | U | yes | schedule, problem (locked) | solver_runs, jobs |
| 30 | GET `/finance/defaults` | U | - | - | - |
| 31 | GET `/finance/templates` | U | - | - | - |
| 32 | POST `/finance/templates/{template_id}/instantiate` | U | yes | - | finance_plans |
| 33 | POST `/finance/preview` | U | yes | - (stateless) | - |
| 34 | GET `/finance/plans` | U | - | list filtered | - |
| 35 | POST `/finance/plans` | U | yes | - | finance_plans |
| 36 | POST `/finance/plans/import` | U | yes | - | finance_plans |
| 37 | GET `/finance/plans/{plan_id}` | U | - | plan | - |
| 38 | PUT `/finance/plans/{plan_id}` | U | yes | plan (locked) | - |
| 39 | DELETE `/finance/plans/{plan_id}` | U | yes | plan (locked) | - |
| 40 | GET `/finance/plans/{plan_id}/export` | U | - | plan | - |
| 41 | POST `/finance/plans/{plan_id}/validate` | U | yes | plan | - |
| 42 | POST `/finance/plans/{plan_id}/runs` | U | yes | plan (locked) | finance_runs, jobs |
| 43 | POST `/finance/plans/{plan_id}/what-if` | U | yes | plan (locked), `base_result_id` result | finance_runs, jobs |
| 44 | GET `/finance/plans/{plan_id}/runs` | U | - | plan; runs filtered | - |
| 45 | GET `/finance/runs/{run_id}` | U | - | finance run | - |
| 46 | POST `/finance/runs/{run_id}/cancel` | U | yes | finance run (locked) | - |
| 47 | GET `/finance/runs/{run_id}/events` | U | - | finance run (each poll) | - |
| 48 | GET `/finance/plans/{plan_id}/results` | U | - | plan; results filtered | - |
| 49 | GET `/finance/results/compare?a=&b=` | U | - | both results | - |
| 50 | GET `/finance/results/{result_id}` | U | - | result | - |
| 51 | GET `/finance/results/{result_id}/contributions.csv` | U | - | result | - |
| 52 | POST `/finance/results/{result_id}/send-to-planner` | U | yes | result | problems |
| 53 | GET `/intake/capabilities` | U | - | - | - |
| 54-63 | POST `/intake/{schedule,finance}/{describe,answer,build,table/parse,table/apply}` (10 routes) | U | yes | - (stateless) | - |
| 64 | GET `/metrics` (root path, not under `/api/v1`) | `METRICS_TOKEN` bearer if set | - | - | - |

Worker writes (system scope, explicit owner): `schedules`, `finance_results`, events, job updates.

Intake drafts are not stored server-side (P2.2.1); in accounts mode the intake endpoints require a session, and the
browser drafts are cleared on sign-out and when the signed-in user changes (4.10). Server-side drafts stay deferred.

### 4.9 Admin CLI `python -m superplanner.manage`

`superplanner/manage.py` (system scope; uses `DATABASE_URL`):
- `create-user --email E [--name N] --password-stdin` -> prints the user id.
- `set-password --email E --password-stdin` (revokes the user's sessions).
- `disable-user --email E` / `enable-user --email E`.
- `reassign-owner --from usr_local --to-email E [--dry-run]`: updates `owner_id` on all owned tables in one
  transaction (problems, solver_runs, schedules, finance_plans, finance_runs, finance_results, jobs); prints counts.
- `list-users`, `prune` (expired sessions, rate-limit rows, old jobs - same as worker maintenance).

### 4.10 Frontend

New `frontend/src/auth/`:
- `AuthContext.tsx`: `AuthProvider` loads `GET /auth/session` once at boot; exposes `{mode, user, csrfToken,
  status: "loading"|"anonymous"|"authenticated", expired: boolean, signIn, signUp, signOut, changePassword,
  refresh, markExpired}`. If the session request fails with a network error or 404, it assumes `single_user` and
  renders the app (the existing "Server not reachable" banner keeps working).
- `authFetch.ts`: `setCsrfToken(t)`, `authHeaders(method): Record<string,string>` (adds `X-CSRF-Token` for unsafe
  methods when a token is known), `onAuthError(status, code)` -> `markExpired()` for 401 `AUTH_REQUIRED`; on 403
  `CSRF_FAILED` the caller refreshes the session once and retries the request once.
  `src/api/client.ts::raw` and `src/finance/api/client.ts::raw` call these (two small edits; intake goes through
  the finance client). `fetch` uses `credentials: "same-origin"` (explicit); accounts mode requires the
  same-origin deployment (a cross-origin `VITE_API_BASE` is documented as single_user only).
- Pages (outside the guard): `SignInPage.tsx` (`/sign-in?next=`), `SignUpPage.tsx` (`/sign-up?next=`),
  `AccountPage.tsx` (`/account`, guarded; change password). In single_user mode these routes redirect to `/`.
- `RequireAuth.tsx`: wraps the existing route tree in `main.tsx`; accounts + anonymous -> `<Navigate
  to="/sign-in?next=<path+search>">`; loading -> spinner; single_user -> children.
- `AccountMenu.tsx` in the topbar (`App.tsx`), hidden in single_user: button showing display name or email ->
  "Account settings", "Sign out".
- Session expired: `SessionExpiredBanner` (role `alert`) at the top of `<main>`: "Your session has ended. Sign in
  again to continue." + button to `/sign-in?next=<current>`; shown when `expired` is true; SSE subscriptions fall
  back to polling, which then also reports 401.
- Sign-out and user change: clear every `sessionStorage` key starting with `sp.intake.`; reload route state by
  navigating to `/sign-in` with `replace`.
- Vite proxy target from env: `SP_API_TARGET` (default `http://127.0.0.1:8000`) in `vite.config.ts`.
- `RUN_EVENT_TYPES` gains `run_requeued`; `RunProgress` and the finance progress component show the requeue note.
- Test ids: `signin-email`, `signin-password`, `signin-submit`, `signin-error`, `signin-to-signup`,
  `signup-name`, `signup-email`, `signup-password`, `signup-submit`, `signup-error`, `account-menu`,
  `account-settings`, `sign-out`, `pw-current`, `pw-new`, `pw-submit`, `pw-success`, `pw-error`,
  `session-expired`, `session-expired-signin`.

E2E: existing config `frontend/e2e/playwright.config.ts` gets backend env `AUTH_MODE=single_user`,
`JOB_BACKEND=inline` (explicit) and `testIgnore: ["accounts/**"]`; no existing spec is edited. New
`frontend/e2e/playwright.accounts.config.ts` (API on 8001 with `AUTH_MODE=accounts`, `COOKIE_SECURE=false`,
`AUTH_SIGNIN_LIMIT_PER_IP=1000`, `AUTH_SIGNUP_LIMIT_PER_IP=1000`, `PUBLIC_BASE_URL=http://127.0.0.1:5174` and
`CORS_ORIGINS=http://127.0.0.1:5174` (the browser's `Origin` is the Vite origin - `changeOrigin` rewrites only
`Host` - so without this every sign-in fails the Origin check with 403), own temp file-DB DB; Vite started with
`npm run dev -- --host 127.0.0.1 --port 5174` (`vite.config.ts` has `strictPort: true, port: 5173`) and
`SP_API_TARGET=http://127.0.0.1:8001`), npm script `e2e:accounts`, specs in `frontend/e2e/accounts/`:
1. anonymous visit -> redirected to sign-in; sign-up -> lands on `/`, account menu shows the name.
2. sign-out -> sign-in page; wrong password -> `signin-error`; correct -> back to the `next` page.
3. user A creates a scheduling plan and a finance plan; user B (second browser context) sees neither in the lists;
   B opening A's `/plans/<id>/tasks` and `/finance/plans/<id>` gets the not-found state; B's direct API GET of
   A's ids returns 404.
4. change password -> old password fails, new one works; other context of the same user is signed out.
5. session expiry: clear cookies in the context, click an action -> `session-expired` banner -> sign in -> back.
6. a full solver run and a finance run complete with live progress while signed in (cookie on SSE).

---

## 5. Part D - Deployment and operations

### 5.1 Configuration variables

All read in `api/config.py::Settings` (dataclass fields with env default factories, as today; explicit test values
still win). Defaults "dev" apply unless `SP_ENV=production`.

| Variable | Default dev / production | Meaning |
|---|---|---|
| `SP_ENV` | `development` | `development` \| `production` (changes defaults below) |
| `DATABASE_URL` | `<file-DB URL>` / required | file-DB or `postgresql+psycopg://...` |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS` | 10, 10, 30 | Postgres pool |
| `DB_STATEMENT_TIMEOUT_MS` | 30000 | Postgres statement timeout |
| `DB_AUTO_MIGRATE` | true for file-DB, false for Postgres | 3.4 |
| `JOB_BACKEND` | `inline` (file-DB) / `queue` (Postgres); `inline`+Postgres refused in production | 2.2 |
| `RUN_WORKERS` | 2 | inline thread pool size (existing) |
| `WORKER_EMBEDDED` | `auto` / 0 | queue mode: worker threads inside the API (`auto` = RUN_WORKERS) |
| `WORKER_CONCURRENCY`, `WORKER_KINDS`, `WORKER_ID`, `WORKER_METRICS_PORT` | 2, both kinds, generated, 9101 | 2.9 |
| `WORKER_POLL_SECONDS`, `WORKER_SHUTDOWN_GRACE_SECONDS` | 1.0, 30 | 2.9 |
| `JOB_LEASE_SECONDS`, `JOB_HEARTBEAT_SECONDS`, `JOB_CANCEL_POLL_SECONDS`, `JOB_REAPER_SECONDS` | 30, 10, 1.0, 15 | 2.5 |
| `JOB_MAX_ATTEMPTS`, `JOB_BACKOFF_BASE_SECONDS`, `JOB_BACKOFF_MAX_SECONDS` | 3, 5, 300 | 2.6 |
| `JOB_RETENTION_DAYS`, `IDEMPOTENCY_TTL_HOURS` | 30, 24 | 2.8, 2.9 |
| `AUTH_MODE` | `single_user` / `accounts` | 4.1 |
| `ALLOW_SINGLE_USER_IN_PRODUCTION` | false | 4.1 |
| `SIGNUP_ENABLED` | true | 4.5 |
| `SESSION_MAX_AGE_DAYS`, `SESSION_IDLE_DAYS` | 30, 7 | 4.4 |
| `COOKIE_SECURE` | false / true | 4.4 |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:5173` / required in accounts+production | Origin check, logs |
| `PASSWORD_HASH_PROFILE` | `default` (`fast` only for tests) | 4.3 |
| `AUTH_RATE_LIMIT_ENABLED`, `AUTH_SIGNIN_LIMIT_PER_IP`, `AUTH_SIGNIN_LIMIT_PER_EMAIL`, `AUTH_SIGNUP_LIMIT_PER_IP` | true, 30, 10, 5 | 4.6 |
| `CORS_ORIGINS` | the four local dev origins / empty | existing (production default changed in review, 4.4) |
| `TRUSTED_PROXY_CIDRS` | unset | nginx `set_real_ip_from` for an external LB (4.6) |
| `MAX_BODY_BYTES` | 5 MiB | existing |
| `LOG_LEVEL`, `LOG_FORMAT` | `INFO`, `text` / `INFO`, `json` | 5.3 |
| `METRICS_ENABLED`, `METRICS_TOKEN` | true, unset | 5.4 |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` (compose: the fixed internal subnet, never `*`) | uvicorn proxy headers (4.6) |
| `INTAKE_AI_ENABLED`, `INTAKE_AI_TIMEOUT_SECONDS`, `ANTHROPIC_API_KEY` | existing | P2.2.12 |
| `HOST`, `PORT` | 127.0.0.1, 8000 | `run_api.sh` |

Validation at startup (`ConfigError`, exit 2, one clear line per problem): `queue` with file-DB; production with
`fast` hash profile; production accounts without `COOKIE_SECURE` (warning only, since TLS may terminate upstream
on plain-http internal networks - the warning says so); unknown enum values. No secret is required for sessions.
`.env.example` (repo root) documents every variable with dev-safe values and placeholders
(`POSTGRES_PASSWORD=change-me`); `.env` is git-ignored.

### 5.2 Health and readiness

- `GET /api/v1/health`: **unchanged** (body and 503 rule; `test_api_health` asserts the exact body). The frontend
  keeps using it.
- `GET /api/v1/health/live` -> 200 `{"status":"ok"}`; no DB access (process liveness).
- `GET /api/v1/health/ready` -> 200
  `{"status":"ready","database":"ok","schema":"ok","schema_revision":"0002_phase2b","job_backend":"queue",
  "workers_alive":2,"queue":{"queued":3,"running":2}}`; 503 with `"status":"not_ready"` when the DB ping fails
  (`"database":"error"`) or the schema is not at head (`"schema":"outdated"`). Missing workers do **not** make the
  API unready (it can still serve and enqueue); they are visible in the body and in metrics. Schema state is
  cached for 30 s. Inline mode: `"workers_alive"` = `RUN_WORKERS`, queue counts from the jobs table.
- Worker: `GET :9101/metrics` doubles as its liveness probe; compose healthcheck uses it.

### 5.3 Structured logging and request ids

`superplanner/obs/logging.py::configure_logging(settings, service: Literal["api","worker","migrate","manage"])`
replaces `logging.basicConfig` in `api/main.py` (called in `create_app` only if not configured yet, so tests keep
pytest's capture). JSON formatter is hand-rolled (no dependency): one line per record:
```json
{"ts":"2026-10-19T08:00:00.123Z","level":"INFO","logger":"superplanner.http","service":"api",
 "msg":"http.request","request_id":"6c1f...","user_id":"usr_3f2a...","method":"POST",
 "route":"/api/v1/problems/{problem_id}/solver-runs","status":202,"duration_ms":41.7}
```
Context fields from ContextVars (when set): `request_id`, `user_id`, `job_id`, `run_id`, `kind`, `worker_id`,
`attempt`; `exc` holds the formatted traceback. `text` format keeps today's line format plus ` rid=<id>`.

`superplanner/obs/request_context.py::RequestContextMiddleware` (pure ASGI, outermost, so 413 and CORS responses
also carry it): request id = incoming `X-Request-ID` if it matches `^[A-Za-z0-9._-]{1,64}$`, else `uuid4().hex`;
echoed in the `X-Request-ID` response header; one `http.request` access line per request at INFO (SSE: logged when
the stream ends, with `duration_ms`); records HTTP metrics (5.4). The enqueuing request id is stored in
`jobs.request_id` and bound by the worker, so API and worker lines of one run correlate. Uvicorn runs with
`--no-access-log` in the images.

Never logged: passwords, session/CSRF tokens, cookies, `Authorization` headers, plan/problem documents, intake
text/tables/AI prompts (existing P2.2.12 rule). Emails are logged only as `user_id`. Events: `auth.sign_in`
(`outcome` ok|invalid|rate_limited), `auth.sign_up`, `auth.sign_out`, `auth.password_changed`, `job.claimed`,
`job.started`, `job.finished` (`outcome`, `duration_ms`, `queue_wait_ms`), `job.requeued`, `job.lease_lost`,
`worker.started`, `worker.stopping`, `worker.stopped`, `schema.migrated`.

### 5.4 Prometheus metrics

`prometheus-client==0.26.0`. API: `GET /metrics` (mounted at the root, outside `/api/v1`; not proxied by the
frontend nginx; `METRICS_TOKEN` -> requires `Authorization: Bearer <token>`, else 401). One process per API
container (scale by replicas), so no multiprocess mode. Worker: `prometheus_client.start_http_server(port)`.

| Metric | Type | Labels | Where |
|---|---|---|---|
| `sp_http_requests_total` | counter | `method`, `route` (template, `unmatched` if none), `status` | API |
| `sp_http_request_duration_seconds` | histogram (5 ms .. 30 s) | `method`, `route` (SSE routes excluded) | API |
| `sp_sse_streams_active` | gauge | `kind` (`solver`,`finance`) | API |
| `sp_jobs_queue_depth` | gauge (collector, DB query cached 5 s) | `kind`, `status` (`queued`,`running`) | API |
| `sp_jobs_oldest_queued_age_seconds` | gauge (same collector) | `kind` | API |
| `sp_workers_alive` | gauge (same collector) | - | API |
| `sp_jobs_total` | counter | `kind`, `outcome` (`succeeded`,`failed`,`cancelled`,`requeued`,`lease_lost`) | worker (and API inline) |
| `sp_job_duration_seconds` | histogram (0.5 s .. 600 s) | `kind`, `outcome` | worker |
| `sp_job_queue_wait_seconds` | histogram (0.05 s .. 600 s) | `kind` | worker |
| `sp_job_failures_total` | counter | `kind`, `reason` (`engine_error`,`transient_error`,`lease_expired`,`max_attempts`) | worker/reaper |
| `sp_worker_slots`, `sp_worker_busy_slots` | gauge | - | worker |
| `sp_auth_events_total` | counter | `event` (`sign_in_ok`,`sign_in_failed`,`sign_up`,`rate_limited`,`csrf_failed`) | API |

Job metrics live in `superplanner/obs/job_metrics.py` (WP-2), HTTP/auth/collector metrics in
`superplanner/obs/http_metrics.py` (WP-4); both use the default registry. With several API replicas, dashboards use
`max(sp_jobs_queue_depth)` (every replica reports the same DB value).

### 5.5 Docker images and compose

Files (repo root unless noted):
```
backend/Dockerfile          multi-stage: base (python:3.13-slim, non-root uid 10001 "sp", pip install -r
                            requirements.txt, copy superplanner/ + alembic.ini + pyproject.toml);
                            target api:    CMD uvicorn superplanner.api.main:app --host 0.0.0.0 --port 8000
                                           --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS} --no-access-log
                            target worker: CMD python -m superplanner.worker
                            HEALTHCHECK via python -c urllib (no curl in slim)
backend/.dockerignore       .venv, tests, *.db, .pgdata, __pycache__
frontend/Dockerfile         build: node:22-alpine, npm ci, npm run build;
                            run: nginxinc/nginx-unprivileged:1.27-alpine, listens 8080, copies dist/ and nginx.conf
frontend/nginx.conf         SPA fallback (try_files $uri /index.html), long cache for /assets, no cache for
                            index.html; location /api/ -> proxy_pass http://api:8000 (resolver 127.0.0.11 valid=10s,
                            variable upstream so `--scale api=N` round-robins), proxy_buffering off,
                            proxy_read_timeout 3600s for SSE, X-Forwarded-For OVERWRITTEN with $remote_addr
                            (after real_ip processing; never $proxy_add_x_forwarded_for, 4.6), X-Forwarded-Proto,
                            X-Request-ID passthrough;
                            /metrics not exposed; security headers (X-Content-Type-Options, Referrer-Policy,
                            frame-ancestors 'none')
frontend/.dockerignore      node_modules, dist, e2e results
docker-compose.yml          services below
.env.example                5.1
.gitattributes              *.sh text eol=lf (Docker builds from Windows checkouts)
backend/run_worker.sh       exec .venv/bin/python -m superplanner.worker "$@"
backend/run_api.ps1, backend/run_worker.ps1   Windows equivalents
```
`docker-compose.yml`:
- `postgres`: `postgres:16-alpine`, env `POSTGRES_DB/USER/PASSWORD` from `.env`, volume `pgdata`, healthcheck
  `pg_isready`, no published port by default (commented `5432:5432` for debugging).
- `migrate`: backend `api` image, `command: python -m superplanner.migrate upgrade`, `restart: "no"`,
  depends on postgres healthy.
- `api`: backend `api` image, `env_file: .env`, `DATABASE_URL=postgresql+psycopg://${POSTGRES_USER}:
  ${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}`, `SP_ENV=production`, `JOB_BACKEND=queue`, depends on
  `migrate: service_completed_successfully`, healthcheck `/api/v1/health/ready`, port 8000 not published.
- `worker`: backend `worker` image, same env, `deploy.replicas: ${WORKER_REPLICAS:-2}`, `stop_grace_period: 45s`,
  healthcheck on `:9101/metrics`, depends on migrate.
- `frontend`: frontend image, `ports: ["${HTTP_PORT:-8080}:8080"]`, depends on api healthy.
- TLS is terminated by an external reverse proxy/load balancer (documented); `COOKIE_SECURE=true` assumes it.
Scaling: `docker compose up -d --scale worker=4 --scale api=2`.

### 5.6 `docs/DEPLOY.md` runbook outline

1. Local dev, zero setup (Linux/macOS/Windows): venv, `pip install -r requirements.txt`, `run_api.sh` /
   `run_api.ps1`, `npm run dev`; file-DB + inline + single_user; nothing else needed.
2. Local dev with Postgres and a separate worker (`pg_dev_cluster.sh`, `JOB_BACKEND=queue`, `run_worker.sh`).
3. Compose: `.env` from `.env.example`, `docker compose up -d --build`, first user (sign-up or
   `manage create-user`), moving legacy `usr_local` data (`manage reassign-owner`).
4. Configuration reference (5.1) and production checklist (accounts, COOKIE_SECURE, TLS proxy, METRICS_TOKEN,
   PUBLIC_BASE_URL, backups).
5. Scaling workers: replicas vs `WORKER_CONCURRENCY` (GIL note), `WORKER_KINDS` pools, DB pool sizing
   (`replicas * (pool_size + max_overflow) < max_connections`), what queue depth / oldest-queued-age alerts mean.
6. Backups and restore: `pg_dump -Fc` via `docker compose exec postgres`, schedule, restore with `pg_restore
   --clean --if-exists`; file-DB: stop the API or use the file-DB CLI online backup; automatic `.bak`
   files from migrations.
7. Upgrades: backup -> pull/build -> `docker compose run --rm migrate` -> `docker compose up -d` (workers drain
   gracefully, interrupted jobs requeue) -> verify `/health/ready`; rollback = restore backup + previous images.
8. Operations: logs (`docker compose logs -f api worker`, JSON fields, finding a run by `request_id`/`run_id`),
   metrics endpoints, stuck jobs (SQL snippets to inspect `jobs`), cancelling, pruning.
9. Windows notes: PowerShell scripts, `py -3.13`, no Docker needed for dev, Postgres optional (EDB installer),
   Ctrl+C stops the worker gracefully, line endings (`.gitattributes`), paths in `DATABASE_URL`
   (`<file-DB URL>`).
10. Troubleshooting: exit code 2 (config), 3 (schema), readiness 503 reasons, `AUTH_REQUIRED` loops (cookie
    Secure over http), SSE behind proxies (buffering).

---

## 6. Part E - Load sanity script

`backend/scripts/load_queue.py` (Q5 in `docs/PLAN-PHASE2B.md`), run with the backend venv:
```
DATABASE_URL=postgresql+psycopg://... .venv/bin/python scripts/load_queue.py \
    --runs 50 --solver-share 0.5 --workers 3 [--concurrency 1] [--api-url URL] [--chaos-kill-after 5] [--json out.json]
```
- Without `--api-url` it starts its own API (`uvicorn` subprocess, `JOB_BACKEND=queue`, `WORKER_EMBEDDED=0`,
  `AUTH_MODE=single_user`, free port) and `--workers` worker subprocesses (`python -m superplanner.worker
  --concurrency C --id load-w<i>`), on the given (empty or disposable) Postgres DB, after `migrate upgrade`.
- Setup: creates `ceil(runs*share)` scheduling plans (template `manufacturing`, jobs=6) and the rest finance plans
  (template `young_professional` or the first finance template), one run per plan (one-active-run rule).
  Solver runs use `{"strategy":"auto","time_limit_seconds":2}`; finance runs the defaults.
- Enqueues all runs concurrently (thread pool of 16 HTTP clients), each with an `Idempotency-Key`; 10% of the
  POSTs are sent twice with the same key to check replay.
- Waits until all runs are terminal (timeout `max(300, runs*10/workers)` s). `--chaos-kill-after N`: SIGKILLs one
  worker after N jobs finished, to exercise lease expiry and requeue.
- Verification from the database (system scope), failing with exit 1 on any violation:
  every run `completed`; exactly one job per run, job `succeeded`; replayed POSTs returned the same `run_id`;
  exactly one terminal event per run and it is the last; event `seq` contiguous from 1; solver runs: schedule ranks
  unique and contiguous; finance runs: exactly one result; `attempts == 1` for all jobs unless chaos (then
  requeued jobs have `attempts == 2` and a `run_requeued` event); every job's final `lease_owner` was a known worker.
- Report (stdout and optional JSON): runs, workers, concurrency, wall seconds, throughput (runs/min), queue wait
  p50/p95, job duration p50/p95 per kind, jobs per worker, requeues, duplicates (must be 0), lost (must be 0).
- `backend/tests/jobs/test_load_small.py` (marker `pg_load`, Postgres only, included in the Postgres run): 10 runs,
  2 workers, same checks via the script's `run(argv) -> Report` function.

---

## 7. File ownership and work packages

**Superseded by `docs/PLAN-PHASE2B.md`** (packages Q1-Q6, authoritative file ownership). Mapping: WP-1 = Q1,
WP-2 = Q2 (minus the load script, which moves to Q5), WP-3 = Q3, WP-5 = Q4, WP-4 = Q5, WP-6 = Q6. The table below is
kept for history; where it differs (shared files `api/config.py`, `api/main.py`, `api/context.py`, SSE route files,
existing-test edits), the plan wins: Q1 pre-creates all settings and app wiring so the parallel packages Q2/Q3/Q4
never edit the same file.

Order: **WP-1** first (alone). Then **WP-2** and **WP-3** in parallel. Then **WP-4** and **WP-5** in parallel
(WP-4 may start on Docker/compose files earlier). **WP-6** last. Each WP leaves both test runs (file-DB, and from
WP-1 on Postgres) green.

| WP | Scope | Owns (create/edit) | Explicit edits outside owned paths |
|---|---|---|---|
| WP-1 DB foundation (B + ownership plumbing) | 2.12, 3.x, 4.2 tables, 4.7 ORM layer, `require_user` single_user form | `api/db/**` (session.py, models.py incl. `JobRow`, `JobWorkerRow`, `OwnedMixin` use; new `ownership.py`), `api/finance/db_models.py`, `api/auth/models.py` (Users/Sessions/RateLimit rows only), `api/auth/deps.py` (initial), `superplanner/migrations/**`, `backend/alembic.ini`, `superplanner/migrate.py`, `api/context.py` (`write_guard`, `ensure_schema`, `jobs` attribute stub = inline wrapper of the executor), `backend/tests/conftest.py`, `backend/tests/db/**`, `backend/scripts/pg_dev_cluster.sh`, `backend/requirements.txt`, `backend/pyproject.toml` | all `with WRITE_LOCK` sites -> `with ctx.write_guard()` and `lock=True` lookups (2.12) in `services/*.py`, `finance/service.py`, `finance/run_service.py`; `api/main.py` (include routers with `require_user`, install `OwnershipScopeMiddleware`); worker-created rows set `owner_id` explicitly in both `run_job`s; the folder conftests' `db_url` fixtures and the hard-coded URLs of 8.2; `.gitignore` (`backend/.pgdata`) |
| WP-2 Job queue and worker (A, E) | 2.1-2.11, 6 | `superplanner/jobs/**`, `superplanner/worker/**`, `superplanner/obs/job_metrics.py`, `api/executor.py`, `backend/tests/jobs/**`, `backend/scripts/load_queue.py`, `backend/run_worker.sh`, `backend/run_worker.ps1` | `api/services/run_service.py`, `api/finance/run_service.py`, `api/services/replan_service.py` (enqueue/dispatch, fencing, `add_event` lock, cancel), `api/context.py` (`jobs` real implementation, startup per backend), route files `routes/solver_runs.py`, `routes/schedules.py` (replan), `api/finance/router.py` (`Idempotency-Key` header, `Idempotent-Replayed`), `api/config.py` (job/worker settings), `tests/api_finance/apifin_helpers.py` (`worker_done`), `inline_jobs` markers of 8.2 |
| WP-3 Accounts backend (C) | 4.1-4.6, 4.7 accounts form, 4.8 matrix, 4.9 | `api/auth/**` (router, passwords, sessions, csrf, ratelimit, schemas, common_passwords.txt; extends `deps.py`), `superplanner/manage.py`, `backend/tests/auth/**` | `api/main.py` (include `auth.router`, CORS credentials), `api/config.py` (auth settings), `api/errors.py` (`_HTTP_CODES` 401/403/429) |
| WP-4 Operations (D) | 5.x | `superplanner/obs/logging.py`, `obs/request_context.py`, `obs/http_metrics.py`, `api/routes/health.py` (live/ready), `api/routes/metrics.py`, `backend/Dockerfile`, `backend/.dockerignore`, `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore`, `docker-compose.yml`, `.env.example`, `.gitattributes`, `backend/run_api.ps1`, `docs/DEPLOY.md`, `backend/tests/ops/**` | `api/main.py` (middleware + `/metrics` mount + `configure_logging`), `api/config.py` (log/metrics settings), `superplanner/jobs/worker.py` (call `configure_logging(service="worker")`, bind log context - coordinate with WP-2), `backend/run_api.sh` (pass `--no-access-log` only if `LOG_FORMAT=json`) |
| WP-5 Frontend (C UI) | 4.10 | `frontend/src/auth/**`, `frontend/e2e/accounts/**`, `frontend/e2e/playwright.accounts.config.ts` | `src/api/client.ts`, `src/finance/api/client.ts` (authFetch hooks), `src/main.tsx` (routes + guard + provider), `src/App.tsx` (AccountMenu, expired banner), `src/intake/state/IntakeContext.tsx` (clear on sign-out), `src/api/types.ts` (`run_requeued`), `src/components/RunProgress.tsx` and the finance progress component (requeue note), `vite.config.ts` (`SP_API_TARGET`), `package.json` (`e2e:accounts` script), `e2e/playwright.config.ts` (env + `testIgnore` only) |
| WP-6 QA and verification | all | `backend/tests/acceptance_phase2b/**` (end-to-end API scenarios across modes, restart/kill tests), section 10 notes | none; files of other WPs only via their owners |

Shared-file rule: `api/main.py`, `api/config.py`, `api/context.py` are edited by several WPs; each WP adds only
its own block (settings fields grouped under a comment per WP) and rebases on the previous WP.

Definition of done: file-DB suite (existing 1794 + new) green; Postgres suite green; existing 65 Playwright tests
green unchanged (single_user); accounts e2e green; `load_queue.py --runs 50 --workers 3` green on a local Postgres
(report pasted into section 10); `docker compose config` validates (running Docker is not required); `npm audit`
no high/moderate.

---

## 8. Changes to existing behaviour and existing tests

### 8.1 Behaviour (all intended)

1. Schema is managed by Alembic; the first start upgrades an existing file-DB database in place (backup copy made);
   data becomes owned by `usr_local`.
2. Run creation enqueues a job row (both modes); in queue mode runs survive API restarts and execute in workers;
   in inline mode startup recovery is unchanged.
3. New SSE event `run_requeued` (queue mode only). New 202 replay behaviour only with `Idempotency-Key`.
4. Cross-process safety: `WRITE_LOCK` -> `write_guard` + row locks + partial unique indexes (file-DB behaviour
   identical). A legacy DB that somehow holds two approved schedules or two active runs for one plan fails the
   migration's index creation: `0002` first demotes extra approved schedules (older ones -> `superseded`) and
   fails extra active runs (`RESTART_ERROR`), keeping the newest.
5. Accounts mode adds 401/403/429 responses; single_user responses are unchanged. `/api/v1/health` unchanged;
   `/health/live`, `/health/ready`, `/metrics`, `/auth/*` added (OpenAPI path set grows; the existing
   `test_openapi_lists_existing_and_finance_paths` uses `<=`, so it keeps passing).
6. Every response carries `X-Request-ID`. Log format changes (JSON in production).
7. `audit_events.actor_id` filled; event/audit ids are BIGINT on Postgres.
8. CORS `allow_credentials` true in accounts mode.

### 8.2 Existing tests changed (only these)

| Test / file | Change | Reason |
|---|---|---|
| `tests/{api,api_finance,integration,integration_finance,integration_phase2,intake}/conftest.py` | `db_url` fixture -> `db_url_factory("<same name>")`; `integration_finance::shared_fin` -> module factory | dual DB (3.6) |
| `tests/api_finance/test_apifin_runs.py:143` (`test_cancel_queued_run_is_immediate`) | URL from `db_url_factory("q")`; marker `inline_jobs` (blocks `ctx.executor`) | 3.6 |
| `tests/api_finance/test_apifin_whatif.py::test_replace_active_cancels_queued_what_if` | marker `inline_jobs` (blocks `ctx.executor`) | 2.2 |
| `tests/api_finance/apifin_helpers.py::worker_done` | uses `self.ctx.jobs.wait_idle(run_id, timeout)` | 2.2 |
| `tests/api/test_api_runs.py::test_api_startup_recovery`, `tests/api_finance/test_apifin_runs.py::test_startup_recovery_marks_runs_failed` | marker `inline_jobs` (restart recovery is the inline contract; queue-mode equivalents live in `tests/jobs`) | 2.2, 2.5 |
| `tests/intake/test_api_intake.py:203` | URL from `db_url_factory("b")` | 3.6 |
| `tests/integration_phase2/test_p2int_templates.py:19` | URL from `db_url_factory` | 3.6 |
| `tests/integration/test_int_concurrency.py::_start_server` / `test_int_killed_server_recovery` | URL from the factory; env adds `JOB_BACKEND=inline`; marker `inline_jobs` | 2.2 |
| `frontend/e2e/playwright.config.ts` | backend env `AUTH_MODE=single_user`, `JOB_BACKEND=inline`; `testIgnore: ["accounts/**"]` | 4.10 |

Review check of this table: `test_startup_recovery_marks_runs_failed` inserts two active finance runs for one
plan, which is why no finance one-active index exists (2.12, R5). `test_api_problems.py:169` counts rows with raw
`SELECT COUNT(*)` on child tables through `ctx.db.engine` - unaffected (no owned-table filter on raw SQL; works on
both dialects). All markers and fixture edits in this table are made by Q1 (PLAN-PHASE2B).

No assertion of an existing test changes. Tests inserting rows directly (e.g. `FinanceRunRow(...)` without
`owner_id`) keep working because `before_flush` stamps `usr_local` outside requests in single_user mode (4.7).
If any other existing test fails, the implementer fixes the code, or documents the test change in this table
before changing the test.

---

## 9. Deferred items

- LISTEN/NOTIFY (or Redis) push for SSE instead of 0.5 s DB polling; per-user job quotas and fair scheduling;
  job priorities beyond 0; process-pool execution inside one worker.
- Celery/Redis (not needed, 2.1); object storage for large results.
- Multi-member workspaces and plan sharing (model prepared: root-level `owner_id`, central criteria, 4.7);
  roles/permissions; tenant/subscription.
- SSO/OAuth providers, email verification, password reset by email, account deletion/export, MFA,
  "sign out everywhere" button (change-password already revokes other sessions).
- Server-side intake drafts.
- Automated file-DB -> PostgreSQL data copy tool (manual path: export/import endpoints).
- Kubernetes manifests, TLS inside the stack, uvicorn multi-process with Prometheus multiprocess mode,
  OpenTelemetry tracing (an `opentelemetry-api` package is present in the venv but unused).
- Relational `schedule_placements` (A.20 deferral stands); GIN indexes on JSONB.

---

## Review notes (team lead, 2026-10-19)

Reviewed against the product-owner goals A-E, the code (`api/context.py`, `api/executor.py`, `api/db/*`,
`services/*`, `finance/*`, routes, tests, frontend clients and Playwright config) and probe scripts run in the
backend venv. Changes made in place in this document:

- **R1 (critical, migration data loss)** - 3.4: file-DB batch migrations with `foreign_keys=ON` delete all child
  rows through `ON DELETE CASCADE` when the parent table is recreated (reproduced with the file-DB CLI: 1 child row -> 0).
  The migration now runs with FKs off, then `foreign_key_check`; the legacy test asserts unchanged row counts.
- **R2 (data safety, Windows)** - 3.4: the pre-migration backup uses the file-DB backup API / `VACUUM INTO`, not a
  file copy (WAL contents would be missing; the file may be locked on Windows).
- **R3 (migration gap)** - 3.4: legacy files from before the finance phase (subset of the 11 tables) are upgraded
  instead of exiting 3; migrations are frozen (no ORM imports) and run without the 30 s statement timeout;
  `alembic==1.20.0` pinned (was missing).
- **R4 (deadlock)** - 2.12: plan/run locks are `FOR NO KEY UPDATE`; with `FOR UPDATE`, what-if `replace_active`
  deadlocks against the replaced run's worker inserting `finance_results` (implicit FK `KEY SHARE`). Worker final
  transactions take `KEY SHARE` on the plan before the run row.
- **R5 (existing test would break)** - 2.12/3.3/8.2: `uq_finance_runs_one_active` removed; the existing
  `test_startup_recovery_marks_runs_failed` inserts two active runs for one plan. The plan row lock enforces the rule.
- **R6 (wrong terminal status)** - 2.5/2.9/2.10: lease loss and shutdown set the same `cancel_event` as user
  cancel, so a worker could finalize a run as `cancelled` that nobody cancelled. Terminal writes now check
  `lease.lost` first; shutdown requeues (fenced) before setting events; writers treat `LeaseLost` quietly.
- **R7 (cross-instance)** - 2.2: `inline` on Postgres is refused in production (inline startup recovery would fail
  runs of other API instances). `WORKER_EMBEDDED` defaults to `auto` in development so a Postgres dev setup without a
  separate worker still executes runs.
- **R8 (idempotency race)** - 2.8: the lookup happens after the plan lock, otherwise a concurrent duplicate gets 409
  instead of a replay. `Lease.finish` keeps `lease_owner` (the load script's per-worker check needs it).
  Inline dispatch claims conditionally and enters `system_scope()` explicitly.
- **R9 (fail-closed 500s)** - 4.7: `AppContext.start()` (lazy, inside a request), `/health/ready` and the metrics
  collector must run in `system_scope()`. Disabled users are rejected per request. `require_user` must be async
  (probe-verified: a sync dependency's ContextVar does not reach the endpoint).
- **R10 (security)** - 4.4/4.6/5.1/5.5: production `CORS_ORIGINS` defaults to empty (dev localhost origins plus
  `allow_credentials` would expose `csrf_token`); nginx overwrites `X-Forwarded-For` and uvicorn trusts only the
  internal subnet (with `*`, uvicorn 0.54 takes the leftmost, client-supplied XFF entry -> per-IP rate limits
  bypassed); sign-in/sign-up revoke a session already presented; accepted risks documented.
- **R11 (test design)** - 4.7: the route-coverage test is black-box over `app.openapi()` (FastAPI 0.143 exposes
  included routers as `_IncludedRouter`, so walking `app.routes` finds nothing). 56 existing endpoints confirmed.
- **R12 (dialect parity)** - 3.5: U+0000 rejected with 422 on both dialects; `allow_nan=False` on Postgres; C
  collation for test clusters; owned rows only via `s.add`.
- **R13 (accounts e2e would fail)** - 4.10: Vite on 5174 needs `--port 5174` and `PUBLIC_BASE_URL`/`CORS_ORIGINS`
  for the Origin check.
- **R14 (plan)** - 7: work packages renumbered Q1-Q6 in `docs/PLAN-PHASE2B.md`; shared files are pre-created by Q1
  so parallel packages have disjoint files; the load script moves to Q5.

Checked and kept: PostgreSQL queue over Celery/Redis (transactional enqueue and DB fencing are the decisive
reasons); 2.5 claim/heartbeat/reaper with DB clock; `add_event` run-row lock (also guarantees SSE never skips a
seq); ORM-level ownership (probe-verified to filter `get`, column selects, counts, `exists`, ORM update/delete);
intake drafts stay browser-side; `/api/v1/health` body unchanged.

## 10. Implementation notes (one subsection per work package)

### 10.WP-1 DB foundation

Implemented by Q1 (database layer, Alembic, ownership plumbing, dual-DB harness). Nothing committed.

**How to run the backend suites**

```
# 1. file-DB (default; zero setup, also on Windows: .venv\Scripts\pytest)
cd backend && .venv/bin/pytest

# 2. PostgreSQL: a local dev/test cluster (never runs postgres as root; creates OS user `spdb` when run as root)
backend/scripts/pg_dev_cluster.sh init  [DIR] [PORT]     # DIR default backend/.pgdata (git-ignored), PORT 54329
backend/scripts/pg_dev_cluster.sh url   [DIR] [PORT]     # -> postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres
cd backend && SP_TEST_DB=postgres \
    SP_TEST_PG_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres .venv/bin/pytest
#    (equivalently: .venv/bin/pytest --db=postgres; SP_TEST_PG_URL defaults to the URL above)
backend/scripts/pg_dev_cluster.sh stop  [DIR]            # also: start, status
```
Postgres run: once per session the template `sp_tpl_<pid>` is built with the **real** Alembic chain
(`0001_initial` -> `0002_phase2b`); each `db_url_factory(name)` clones it (`CREATE DATABASE ... TEMPLATE ... STRATEGY
FILE_COPY`) and drops it `WITH (FORCE)` afterwards. Until Q2 the Postgres run uses `JOB_BACKEND=inline` (set by the
root conftest). Markers (registered in `pyproject.toml`): `postgres_only`, `file_db_only` (skipped with a visible
reason on the other dialect, `-rs` shows them), `inline_jobs`, `pg_load`. If PostgreSQL is unreachable the run stops
at once with exit code 4 and the hint to run `pg_dev_cluster.sh init`.

Migrations by hand: `python -m superplanner.migrate {upgrade,current,check,stamp-legacy} [--url URL]` (exit 3 =
schema problem, 2 = configuration problem). Plain Alembic also works:
`.venv/bin/alembic -c backend/alembic.ini -x url=<URL> upgrade head` (its env.py forces `foreign_keys=OFF` on file-DB).

**Results (2026-10-19, this machine; 1794 existing + 69 new tests in `tests/db/`)**
- file-DB (G1): `cd backend && .venv/bin/pytest -rs` -> `1858 passed, 5 skipped in 544.62s` (the 5 skips are the
  Postgres-only tests, each with the reason "PostgreSQL-only test (run with SP_TEST_DB=postgres)").
- PostgreSQL 16 (G2, inline jobs): `SP_TEST_DB=postgres SP_TEST_PG_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres
  .venv/bin/pytest -rs` -> `1862 passed, 1 skipped in 625.43s` (skip: the file-DB-only WAL backup test).

**Files** (all inside the Q1 ownership list): `backend/alembic.ini`, `superplanner/migrations/{env.py,
script.py.mako, versions/0001_initial.py, versions/0002_phase2b.py}`, `superplanner/migrate.py`,
`api/db/{session.py, models.py, ownership.py, locks.py (new), __init__.py}`, `api/finance/db_models.py`,
`api/auth/{__init__.py, models.py, deps.py, router.py, maintenance.py}`, `api/config.py`, `api/main.py`,
`api/limits.py`, `api/context.py`, the six service/route files of 0.1, `tests/conftest.py`, `tests/db/**`, the
8.2 test edits, `scripts/pg_dev_cluster.sh`, `requirements.txt`, `pyproject.toml`, `.gitignore`.

**Interpretations and deviations (for LEAD review)**

1. *Queue backend before Q2.* `Settings` resolves `JOB_BACKEND` exactly as 2.2/5.1 (default `queue` on Postgres,
   `queue`+file-DB and `inline`+Postgres+production refused with `ConfigError`). Until Q2 lands, `AppContext` runs
   the inline shim (`context.InlineJobs`) for both values and logs a warning for `queue`. The shim implements
   `enqueue/dispatch/request_cancel/notify_cancel/wait_idle/start/stop`; `dispatch` claims conditionally
   (`queued` -> `running`, `lease_owner="inline:<pid>"`, new token) and the submitted callable enters
   `system_scope()`; after the handler it mirrors the run's terminal status onto the job (completed -> succeeded,
   failed, cancelled; `lease_owner` kept, token cleared). `run_job(ctx, run_id, cancel_event)` keeps its signature
   (Q2 changes it to `lease`). `submit()` was removed from both run services (creation paths now enqueue inside the
   transaction and dispatch after commit).
2. *Empty databases* are always created (`create_all` + `stamp head` + `usr_local`) even with
   `DB_AUTO_MIGRATE=false`: there is nothing to lose, and a developer pointing `DATABASE_URL` at an empty Postgres DB
   gets a working API. `DB_AUTO_MIGRATE=false` only refuses `legacy`/`behind` (exit 3 with the command to run).
   A database containing some of our tables but no `problems` is treated as legacy and refused with a message.
3. *Legacy checks run before the backup*: unknown tables or missing 0001 columns -> `SchemaError` naming them, no
   backup written, nothing changed. Backups are named `<db>.bak-<rev prefix>-<UTC yyyymmddHHMMSS>` (`bak-0001-` for
   legacy and 0001 files), with a `-n` suffix on a same-second collision. `.gitignore` gets `*.db.bak-*`.
4. *file-DB migration engine*: own `NullPool` engine, driver autocommit (`isolation_level=None`), `PRAGMA
   foreign_keys=OFF` in the connect hook (i.e. outside any transaction), `BEGIN IMMEDIATE` per transaction, the whole
   upgrade (incl. stamping and `usr_local`) in one transaction, then `PRAGMA foreign_key_check` (rows -> rollback,
   `SchemaError`, backup kept). Alembic's `transactional_ddl=False` on file-DB does not matter because migrate owns
   the outer transaction (env.py's `begin_transaction()` is a no-op inside it).
5. *0002 data step* demotes extra approved schedules (newest `approved_at` wins) and fails extra active **solver**
   runs (newest `created_at` wins) with `RESTART_ERROR` + a `run_failed` event (`seq = max+1`, payload in the API
   format). Finance runs are not de-duplicated (no index, R5). Downgrade of 0002 keeps the data of the 11 tables
   (removes owner_id/actor_id, the new tables and indexes, reverts BIGINT + sequences on Postgres).
6. *FK names*: `Base.metadata` has a naming convention for foreign keys only
   (`fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`), so `create_all` and 0002 name the owner FKs
   identically (`fk_problems_owner_id_users`); all other constraint/index names are unchanged and autogenerate
   compares FKs by signature, so DBs migrated from 0001 (unnamed FKs) compare clean. `OwnedMixin.owner_id` is a
   plain mixin column (a `declared_attr` breaks `with_loader_criteria`'s lambda analysis on the mixin class).
7. *Ownership hook - probe gap found*: `ORMExecuteState.all_mappers` is **empty** for
   `select(func.count()).select_from(Model)` (SQLAlchemy 2.1.4), so a mapper-only check would have left such counts
   unfiltered. Therefore, with a bound user, `with_loader_criteria(OwnedMixin, ...)` is added to **every** ORM
   SELECT/UPDATE/DELETE (a no-op for statements without owned entities; verified to filter `select_from` counts and
   subqueries). The fail-closed check (unbound inside a request) uses `all_mappers` plus a structural scan for owned
   `Table`s. Column/relationship loads (refresh) are skipped (their parent load was filtered). Tests cover `get`,
   entity select, column select, `select_from` count, `exists()`, ORM update/delete, stamping, and fail-closed for
   entity, column and count queries.
8. *`require_user`* (async, single_user form): binds `usr_local` with `bind_owner()` (no reset; the var lives for the
   request task) and sets `request.state.principal`; accounts mode raises 401 `AUTH_REQUIRED` for every protected
   route until Q3. `auth/router.py` is an empty `APIRouter(prefix="/auth")` included without `require_user`.
   `deps.principal_user_id(request)` is the helper the SSE routes use to wrap each poll in `owner_scope`.
9. *Locks* (`api/db/locks.py`): `lock_row(s, Model, id)` (= the `lock_run` of 2.12, `FOR NO KEY UPDATE`),
   `lock_parent_key_share` (`FOR KEY SHARE`, used by both worker final transactions before the run row),
   `get_locked(..., for_delete)`; `get_problem_row/get_plan_row(s, id, lock=False, for_delete=False)`. `approve` now
   locks the problem first and re-reads the schedule under it; what-if re-reads the active run under its lock and
   ignores it if it finished meanwhile. On file-DB the worker's final/failure transactions now also take the write
   guard (same order everywhere: write guard -> file-DB write lock), which changes no behaviour.
10. *IntegrityError mapping*: `uq_solver_runs_one_active` -> 409 `RUN_ALREADY_ACTIVE` with the active run id (create
    and replan); `uq_schedules_one_approved` -> approval retried once, then 409 `CONFLICT`. Detection matches the
    index name (Postgres) or `UNIQUE constraint failed: <table>.<col>` (file-DB, which does not name partial
    indexes).
11. *NUL (U+0000)*: checked in `BodySizeLimitMiddleware` for `*json*` content types while the body streams; the
    scanner is escape-aware across chunk boundaries (`\\u0000` text is accepted and stored verbatim) and also rejects a
    raw 0x00 byte. Response: 422 envelope `VALIDATION_ERROR`, message "The request must not contain the NUL
    character (\u0000).", `details: {}` (FastAPI turns non-HTTP exceptions raised while reading the body into 400, so
    an `HTTPException(422)` is raised and rendered by the existing handler).
12. *Settings*: every B 5.1 variable exists; dependent defaults are `None` and resolved in `__post_init__`
    (explicit constructor values win). Additions: `auth_change_password_limit_per_user`
    (`AUTH_CHANGE_PASSWORD_LIMIT_PER_USER`, 10, B 4.6 table), `warnings` (collected, logged once at start),
    properties `is_production`, `is_postgres`, `single_user`, `cors_allow_credentials`, `embedded_workers`. Invalid
    values of the **new** variables raise `ConfigError`; the pre-2b ones keep their lenient fallbacks. Module-level
    `app` in `main.py` turns a `ConfigError` into one stderr line and exit 2. `PUBLIC_BASE_URL` is required only for
    production + accounts.
13. *Database* (`Database(url, *, pool_size, max_overflow, pool_timeout, statement_timeout_ms, service)` and
    `Database.from_settings(settings, service)`): URL normalised; Postgres pool/pre-ping/recycle 1800, `options=-c
    statement_timeout=... -c lock_timeout=10000`, `application_name=superplanner-<service>`,
    `json_serializer=partial(json.dumps, allow_nan=False)`; file-DB unchanged. `psycopg` is only imported by
    SQLAlchemy when a Postgres URL is used (test runs the file-DB app with `sys.modules["psycopg"] = None`).
14. *Alembic logging*: `migrate` sets the `alembic` logger to WARNING unless configured (it logs several INFO lines
    per connection); our own `schema.migrated` INFO line remains.
15. *pg_dev_cluster.sh*: also has `status`; runs the server with `fsync=off` and `max_connections=300` (dev/test
    speed; never use the script for real data). As root it makes the parents of DIR traversable (`o+x`); if
    something resets a parent to 0700 while the server runs, postgres PANICs at the next checkpoint ("could not open
    pg_control: Permission denied"). In this agent environment `/tmp/claude-0` is reset that way, so the scratchpad
    data dir was bind-mounted to `/srv/sp-pg-<session>` and the cluster started from there.
16. *Existing tests changed*: exactly the rows of 8.2 owned by Q1 - the six folder `db_url` fixtures and `shared_fin`
    (factory), `test_cancel_queued_run_is_immediate` (factory URL + `inline_jobs`),
    `test_replace_active_cancels_queued_what_if`, `test_api_startup_recovery`, `test_startup_recovery_marks_runs_failed`
    (`inline_jobs`), `test_api_intake.py::test_ai_slots_are_per_app` (factory "b"), `test_p2int_templates.py` module
    fixture (module factory), `test_int_concurrency._start_server`/`test_int_killed_server_recovery` (factory URL,
    `JOB_BACKEND=inline`, `inline_jobs`). Only imports (`import pytest`) were added otherwise; no assertion changed.
    `apifin_helpers.worker_done` is untouched (Q2).
17. *Pre-existing order dependency (not caused by Q1)*: `tests/intake/test_ai_extractor.py::
    test_sdk_loggers_capped_and_no_text_logged` fails when `tests/integration_phase2` runs immediately before
    `tests/intake` in one session (reproduced on the unmodified HEAD in a separate worktree); it passes in the default
    full-suite order on both dialects. Reported for the owner of the intake tests.

**Acceptance criteria -> tests** (`backend/tests/db/`)

| Criterion | Test(s) |
|---|---|
| Q1-1 | full runs below |
| Q1-2 | `test_db_migrations.py::test_upgrade_head_and_create_all_produce_the_model_schema`, `::test_both_paths_give_identical_indexes`, `::test_postgres_partial_indexes_keep_their_predicates` (also checks BIGINT ids and `priority DESC`) |
| Q1-3 | `::test_legacy_database_upgrades_on_first_start_and_keeps_all_rows[all-11-tables / pre-finance-6-tables]` (both dialects; backup + `foreign_key_check` on file-DB), `::test_legacy_backup_contains_uncheckpointed_wal_data`, `::test_legacy_with_unknown_table_is_refused_untouched`, `::test_legacy_with_missing_column_is_refused` |
| Q1-4 | `::test_legacy_duplicates_keep_the_newest` |
| Q1-5 | `::test_downgrade_base_then_upgrade_head` |
| Q1-6 | `::test_check_exits_3_on_a_database_behind_head`, `::test_concurrent_ensure_schema_on_one_empty_postgres_db`, `::test_unknown_newer_revision_is_refused`, `::test_stamp_legacy_cli` |
| Q1-7 | `test_db_concurrency.py::test_db_rejects_a_second_active_run_and_a_second_approval`, `::test_db_rejects_a_second_job_for_one_run`, `::test_active_run_index_violation_maps_to_409`, `::test_approve_retries_once_on_the_approved_index` |
| Q1-8 | `::test_concurrent_add_event_allocates_contiguous_seq` (Postgres) |
| Q1-9 | `test_db_ownership.py` (11 tests: probes per query form, stamping, fail-closed 500 + `OwnershipViolation` log, `iscoroutinefunction(require_user)`, lazy start without `with`, lazy start running recovery inside a request, accounts-mode 401, CORS credentials) |
| Q1-10 | `test_db_concurrency.py::test_plan_lock_is_no_key_update` (Postgres; verified to fail when the plan lock is plain `FOR UPDATE`) |
| Q1-11 | `test_db_nul_and_config.py::test_nul_in_any_json_body_is_422_on_both_dialects`, `::test_nul_scanner_*` |
| Q1-12 | `::test_file-DB_mode_works_without_psycopg` |
| Q1-13 | `test_db_pg_cluster.py::test_cluster_lifecycle` (Postgres run; skipped without the server binaries) |
| extra | config resolution/validation (`test_db_nul_and_config.py`), uvicorn import exit 2, `prune_auth_tables`, inline job rows + recovery of jobs (`test_db_concurrency.py`) |

### 10.WP-2 Job queue and worker

Implemented by Q2. Nothing committed.

**Running it**
```
# PostgreSQL (JOB_BACKEND=queue is the default there). API with embedded workers (dev default WORKER_EMBEDDED=auto):
DATABASE_URL=postgresql+psycopg://... backend/run_api.sh
# or API without workers + separate worker processes (production shape):
WORKER_EMBEDDED=0 DATABASE_URL=... backend/run_api.sh
DATABASE_URL=... backend/run_worker.sh --concurrency 1          # Windows: .\run_worker.ps1 --concurrency 1
python -m superplanner.worker --once                            # drain the queue, exit 0
```
file-DB stays inline (thread pool in the API, no worker process); `python -m superplanner.worker` with file-DB exits 2.

**Files**: `superplanner/jobs/{__init__,types,common,inline,pg,idempotency,worker}.py`, `superplanner/worker/{__init__,__main__}.py`,
`superplanner/obs/{__init__,job_metrics}.py`, `api/context.py`, `api/services/{run_service,replan_service}.py`,
`api/finance/run_service.py`, `api/routes/{solver_runs,schedules}.py`, `api/finance/router.py`,
`tests/jobs/**`, `tests/api_finance/apifin_helpers.py::worker_done`, `run_worker.sh`, `run_worker.ps1`.
`api/executor.py` is unchanged (InlineQueue wraps it).

**Interpretations and deviations (for LEAD review)**

1. *Shared job-row code* lives in `jobs/common.py` (enqueue row, `request_cancel`, `requeue_or_fail`, fenced
   `requeue_lease`, `mirror_finish` safety net, `fail_orphan_runs`, inline `mark_jobs_failed`); only claim, lease check,
   renewal, reaper scan, worker registry and retention are raw SQL (`jobs/pg.py`). `Lease` also carries `kind`, `run_id`,
   `max_attempts`, `request_id`, `outcome` (metrics/logging). `HANDLERS[kind]` resolves the run-service function at call
   time, so tests that monkeypatch module attributes keep working.
2. *requeue_or_fail* (reaper, transient error, shutdown) first looks at the locked run: a run that already finished
   mirrors its status onto the job; a run with `cancel_requested` (run or job) becomes `cancelled` + `run_cancelled`
   (the user asked for it; never for a lost lease without a cancel request, R6). `worker_shutdown` decrements `attempts`
   (attempt not consumed) and uses no delay; the `run_requeued.attempt` field is `attempts + 1` after that adjustment.
   `retry_at`/`run_after` use the DB clock.
3. *Start transaction*: a run that is no longer `queued` (cancelled in the claim window) finishes the job with the
   run's status mapped (`completed->succeeded`, else `cancelled`/`failed`) and the engine never runs; a gone run (plan
   deleted, job cascaded) is `LeaseLost`.
4. *Cancel latency*: queue mode reads `jobs.cancel_requested` in the heartbeat tick (`JOB_CANCEL_POLL_SECONDS`).
   `PgQueue.notify_cancel` additionally sets the event at once when the run executes on an embedded worker of the same
   process (same effect, lower latency; other processes rely on the DB flag - tested cross-instance, < 3 s).
5. *Lease loss detection*: the heartbeat's per-tick check (`status`/`lease_token` of all active jobs in one query) also
   marks a lease lost when another worker took the job over; renewal failures for `JOB_LEASE_SECONDS -
   JOB_HEARTBEAT_SECONDS` mark it lost (lost FIRST, then cancel). Progress writers skip writes once `lost` is set; a
   `LeaseLost` inside a writer marks the lease lost and is not logged as an error.
6. *Shutdown* (`WorkerLoop.stop`, also used by `AppContext.stop` for embedded workers): stop claiming, wait up to the
   grace period, then per remaining job (1) fenced requeue `worker_shutdown`, (2)+(3) `mark_lost()`; then wait up to 15 s
   for handler threads, mark `job_workers.stopped_at`. A second SIGTERM/SIGINT skips the grace wait. The root test
   conftest sets `WORKER_SHUTDOWN_GRACE_SECONDS=1` on Postgres so app teardown stays fast.
7. *Transient errors*: `OperationalError`/`InterfaceError`/invalidated `DBAPIError` in a handler become
   `RetryableJobError` only when `job_backend == "queue"` (inline keeps today's `failed`); the worker requeues with
   reason `transient_error` and backoff. If that requeue itself fails (DB still down) the lease is marked lost and the
   reaper requeues after expiry.
8. *Idempotency* (`jobs/idempotency.py`): header parsed in the route (`from_header`, 422 `VALIDATION_ERROR` with
   `loc ["header","idempotency-key"]`); `request_hash` = sha256 of `route_kind + "\n" + canonical JSON {path, body}` where
   body is the validated request model dumped in JSON mode (defaults filled in, so `{}` and the explicit defaults are the
   same request). The lookup row is locked `FOR UPDATE` after the plan/problem lock. Replay = `created_dict` of the run
   with its current status (+ `source_schedule_id`/`problem_version` for replans); a key whose job belongs to another
   run kind is a mismatch. The `uq_jobs_idempotency` race path re-runs the lookup in a new transaction.
9. *Orphans*: `AppContext.start()` in queue mode and the worker at start fail queued/running runs without a job row
   (`RESTART_ERROR`). Inline start keeps `recover_interrupted_runs` and also fails their jobs.
10. *Worker exits*: 2 = configuration (file-DB URL, `JOB_BACKEND=inline`, bad `--kinds`/`--concurrency`); 3 = schema not at
    head with `DB_AUTO_MIGRATE=false` (message names the revision and `python -m superplanner.migrate upgrade`) or the
    database is unreachable. Empty databases are created as in Q1 (interpretation 2 of 10.WP-1).
11. *Maintenance* runs from the claim loop: retention of terminal jobs (batches of 1000, at most 20 batches per pass),
    stale `job_workers` (> 1 day), `prune_auth_tables(s, now)`; every 10 minutes (first pass 5 s after start of a worker
    process; embedded workers wait the full interval).
12. *Metrics* (`obs/job_metrics.py`, default registry; no-op if `prometheus_client` were missing): `sp_jobs_total{kind,
    outcome}`, `sp_job_duration_seconds`, `sp_job_queue_wait_seconds`, `sp_job_failures_total{kind,reason}`,
    `sp_worker_slots`, `sp_worker_busy_slots`. The worker starts `prometheus_client.start_http_server(WORKER_METRICS_PORT)`
    (0 disables); Q5 owns the logging bind and may move the metrics server.
13. *Test edits outside `tests/jobs`*: the root conftest's Postgres env switched to `JOB_BACKEND=queue`,
    `WORKER_EMBEDDED=auto`, `WORKER_SHUTDOWN_GRACE_SECONDS=1` (B 3.6) and stops leftover app contexts before a test DB is
    dropped; `apifin_helpers.worker_done` -> `ctx.jobs.wait_idle` (B 8.2). Three Q1 tests in `tests/db/` that test the
    inline contract got the `inline_jobs` marker (no assertion changed): `test_inline_mode_writes_one_job_per_run_with_the_terminal_status`,
    `test_lazy_start_recovers_runs_inside_a_request` (queue-mode equivalent: `tests/jobs/test_queue_api.py::test_queue_start_fails_orphan_runs_without_a_job`,
    also a lazy start), and `test_file-DB_mode_works_without_psycopg` (its file-DB subprocess inherited `JOB_BACKEND=queue`).
14. *Load script*: `backend/scripts/load_queue.py` belongs to Q5 (PLAN 0.1); its report goes into 10.WP-4.
    `Lease.finish` keeps `lease_owner`, which that script's per-worker check needs.

**Results (2026-10-20, this machine; the trees also contained Q3's in-progress `tests/auth/`)**
- file-DB (G1): `cd backend && .venv/bin/pytest -rs` -> `1934 passed, 23 skipped in 550.04s` (skips: Postgres-only tests).
- PostgreSQL 16 (G2, queue + embedded workers): `SP_TEST_DB=postgres SP_TEST_PG_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres
  .venv/bin/pytest -rs` -> `1956 passed, 1 skipped in 771.89s` (skip: the file-DB-only WAL backup test).
- `tests/jobs` alone on PostgreSQL, three consecutive runs: `33 passed` each (~85 s); on file-DB `15 passed, 18 skipped`.

**Acceptance criteria -> tests** (`backend/tests/jobs/`)

| Criterion | Test(s) |
|---|---|
| Q2-1 | full runs below |
| Q2-2 | `test_queue_core.py::test_concurrent_claimers_claim_every_job_exactly_once` |
| Q2-3 | `::test_expired_lease_is_requeued_by_the_reaper_and_completes_once` |
| Q2-4 | `::test_max_attempts_of_expiries_fail_the_run_with_worker_lost` |
| Q2-5 | `::test_stale_lease_cannot_write_after_takeover` |
| Q2-6 | `::test_lost_heartbeat_is_not_a_cancel` |
| Q2-7 | `test_queue_api.py::test_cancel_running_solver_and_finance_runs_in_queue_mode`, `::test_finance_cancel_racing_the_final_write_stores_no_result` |
| Q2-8 | `test_queue_core.py::test_graceful_shutdown_requeues_without_consuming_an_attempt`, `test_worker_process.py::test_sigterm_requeues_and_once_mode_finishes_the_queue` (real process) |
| Q2-9 | `test_worker_process.py::test_kill_9_mid_run_another_worker_completes_it_exactly_once` (solver + finance run on worker 1, `SIGKILL`, worker 2 completes both: attempts 2, one `run_requeued lease_expired`, one terminal event, ranks `0..k`, one result) |
| Q2-10 | `test_idempotency.py` (all four endpoints, mismatch, invalid formats, 10 concurrent identical requests, per-owner keys, TTL release; both dialects) |
| Q2-11 | `test_queue_api.py::test_two_api_instances_share_runs_sse_and_cancel` |
| Q2-12 | `::test_idle_worker_wakes_on_notify` (`WORKER_POLL_SECONDS=5`, claim < 1 s, twice) |
| Q2-13 | `::test_api_restart_in_queue_mode_keeps_the_run`, `::test_api_restart_with_a_running_job_of_a_dead_worker`; inline: existing `test_api_startup_recovery` / `test_startup_recovery_marks_runs_failed` (file-DB) |
| Q2-14 | `test_worker_process.py::test_queue_backend_with_file-DB_is_refused`, `::test_inline_with_postgres_in_production_is_refused`, `::test_worker_with_file-DB_url_exits_2`, `::test_uvicorn_import_with_queue_on_file-DB_exits_2`, `::test_worker_with_schema_behind_head_exits_3` |
| Q2-15 | `test_inline_jobs.py` (succeeded / failed / cancelled-running / cancelled-queued, both kinds) |
| extra | `test_queue_core.py::test_transient_db_error_requeues_and_retries`, `::test_engine_error_is_not_retried`, `test_queue_api.py::test_queue_start_fails_orphan_runs_without_a_job` |

### 10.WP-3 Accounts backend

Files: `sp/api/auth/{deps,router,passwords,sessions,csrf,ratelimit,schemas}.py`, `common_passwords.txt`,
`sp/api/errors.py` (`_HTTP_CODES` 401/403/429), `sp/manage.py`, `backend/tests/auth/**` (61 tests, both dialects).
Run: `cd backend && .venv/bin/pytest tests/auth` (file-DB) or with `SP_TEST_DB=postgres` (Postgres).

Interpretations (contract gaps, most reasonable reading):
- **Common-password list**: the "1000 most common passwords" would be almost useless under a 10-character
  minimum (only ~12 of the classic top 1000 are that long). The bundled list is the 1000 most frequent passwords
  of length >= 10 from SecLists `100k-most-used-passwords-NCSC.txt` (MIT), lower-cased; comparison is
  case-insensitive after NFKC. Passwords are NFKC-normalised before hashing and verifying too.
- **Gate order**: the mode check (409 `AUTH_DISABLED`), Origin check (sign-in/up) and session/CSRF checks
  (sign-out, change-password) run as dependencies, i.e. before body validation; so single_user answers 409 even
  for an invalid body and change-password without a session answers 401 even for `{}`.
- **Malformed JSON** (not parseable at all) on a protected POST/PUT is rejected by FastAPI's body parser before any
  dependency runs -> 422 `VALIDATION_ERROR` (`json_invalid`), not 401. No lookup happens, nothing owned is revealed;
  schema-invalid bodies (`{}`, wrong types, extra fields) do get 401. Turning this into 401 too needs a pre-parse
  ASGI layer in `main.py` (frozen; change request for Q5/LEAD if wanted). The coverage test accepts either.
- **Origin check**: absent `Origin` passes (non-browser clients); `null` or any origin not in `CORS_ORIGINS` /
  the `PUBLIC_BASE_URL` origin -> 403. Comparison is scheme+host+port, case-insensitive.
- **Cookie**: header written by hand to get exact `SameSite=Lax` casing; clearing uses `Max-Age=0` with the same
  attributes. An invalid/expired cookie is cleared on the 401 of protected routes and on `GET /auth/session`.
  With `COOKIE_SECURE=true` only `__Host-sp_session` is read.
- **Sessions**: valid = not revoked, `expires_at` in the future, `last_seen_at` within `SESSION_IDLE_DAYS`, user
  not disabled, not `is_local`, has a password. `last_seen_at` is written only when older than 5 minutes (a separate
  short write after the read). Change-password revokes *all* sessions of the user (incl. the current one) and
  issues a new one (rotation); sign-in/up revoke the caller's current session if its cookie is valid.
- **Rate limits**: buckets counted in their own committed transaction before any hash verification; a hit is
  counted in every bucket even if an earlier one already refused; `Retry-After` = the longest remaining window
  (>= 1 s). `AUTH_RATE_LIMIT_ENABLED=false` disables all of them. Sign-in counts unknown emails too.
- **Unknown email / disabled / usr_local / no password**: one argon2 verification against a constant dummy hash
  of the configured profile, then 401 `INVALID_CREDENTIALS`.
- **WEAK_PASSWORD** order: reasons in the order too_short, too_long, common, same_as_email. Change-password checks
  the current password (422 `WRONG_PASSWORD`) before the policy of the new one.
- **manage**: runs `migrate.ensure_schema` like the API (file-DB auto-upgrade; Postgres behind head -> exit 3);
  exit codes 0/1 (command error)/2 (config)/3 (schema). `create-user`/`set-password` enforce the password policy.
  `reassign-owner` updates every table with an `owner_id` column (problems, solver_runs, schedules, finance_plans,
  finance_runs, finance_results, jobs) with Core UPDATEs in one transaction; `--dry-run` counts only. `prune`
  prunes the auth tables; the jobs part is Q5's (plan 0.1) - `superplanner.jobs.pg.maintenance` already exists.
- **Change request (LEAD)**: `backend/pyproject.toml` `[tool.setuptools.package-data]` should add
  `"superplanner.api.auth" = ["common_passwords.txt"]` so non-editable installs ship the list (source checkouts,
  the dev mode and the Docker image built from the source tree are unaffected). Not edited (Q1-owned file).

Acceptance -> tests (`backend/tests/auth/`):

| Criterion | Tests |
|---|---|
| Q3-1 | full G1/G2 runs; `test_auth_endpoints.py::test_single_user_session_body_and_disabled_mutations` |
| Q3-2 | `test_auth_endpoints.py` (flow, cookie attributes, `__Host-`/Secure, every error code of B 4.5) |
| Q3-3 | `test_auth_passwords.py` (argon2id prefix, profile parameters, `fast` refused in production, policy, rehash) |
| Q3-4 | `test_auth_csrf.py` (every unsafe protected operation: missing/wrong token, foreign/`null` Origin; GET/SSE without token; sign-in/up Origin) |
| Q3-5 | `test_route_coverage.py::test_enumerated_operations_equal_the_access_table`, `::test_every_protected_operation_requires_a_session` (OpenAPI-driven; `route_table.py` is B 4.8 as data) |
| Q3-6 | `test_route_coverage.py::test_user_b_gets_404_for_every_owned_endpoint` (every OpenAPI operation with an owned path parameter, for baseline and what-if run/result; body byte-equal to an unknown-id call; compare with one foreign id; `base_result_id`; lists; A's objects unchanged). Mutation check: disabling the ORM filter makes it fail (B's DELETE of A's problem returned 204). |
| Q3-7 | `test_auth_sessions.py` (expired/idle/revoked/disabled -> 401, touch throttle, fixation, hashed token, lazy start, async `require_user`); change-password rotation in `test_auth_endpoints.py::test_change_password` |
| Q3-8 | `test_auth_ratelimit.py` (11th sign-in 429 + `Retry-After` + details, before verification, two app instances, per-IP, sign-up, change-password, window roll-over, 40 concurrent hits counted exactly, concurrent same-email sign-ups -> one 201) |
| Q3-9 | `test_auth_passwords.py::test_unknown_email_verifies_the_dummy_hash` |
| Q3-10 | `test_manage.py` (all commands, `reassign-owner` makes legacy plans/runs visible to the account, subprocess entry point, exit 2) |
| Q3-11 | `test_auth_logs.py` (caplog at DEBUG over sign-up/in/out, change-password, rate limit, validation errors) |

Results (2026-10-20, working tree incl. the parallel Q2 files): file-DB `cd backend && .venv/bin/pytest -rs` ->
`1934 passed, 23 skipped` (skips: Postgres-only tests, each with the reason); PostgreSQL 16 (queue mode, embedded
workers) `SP_TEST_DB=postgres ... .venv/bin/pytest -rs` -> `1956 passed, 1 skipped` (file-DB-only WAL backup test).
`tests/auth` alone: 61 passed on each dialect.

### 10.WP-4 Operations

Implemented by Q5 (plan section 6). Nothing committed. The runbook is `docs/DEPLOY.md` (all 10 sections of B 5.6).

**Files.** New:
- `superplanner/obs/logging.py`, `obs/request_context.py`, `obs/http_metrics.py`, `api/routes/metrics.py`
- `scripts/load_queue.py`
- `backend/Dockerfile`, `backend/.dockerignore`, `backend/run_api.ps1`
- `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore`, `frontend/docker/40-sp-real-ip.sh`
- `docker-compose.yml`, `.env.example`, `.gitattributes`, `docs/DEPLOY.md`
- `tests/ops/**`, `tests/jobs/test_load_small.py`

Edited:
- `api/routes/health.py`: live/ready added; `/health` unchanged.
- `api/main.py`: `RequestContextMiddleware` outermost, `/metrics` mount, `configure_logging` instead of
  `basicConfig`.
- `jobs/worker.py`: log binding, `job.started` line, `queue_wait_ms` in `job.finished`, `configure_logging`.
- `manage.py`: the jobs part of `prune`.
- `run_api.sh`: `--no-access-log` only with `LOG_FORMAT=json`, `--proxy-headers`.
- `.gitignore`: adds `.env`.

`api/config.py` needed no change: Q1 had already declared every setting.

**Interpretations and deviations (for LEAD review)**
1. *Auth event metrics are derived in the middleware*, from route template + status: sign-in 200/401,
   sign-up 201, any 429, and any 403 whose body carries `CSRF_FAILED` (only 403 bodies are peeked, at most 512
   bytes). So the Q3 auth files needed no edit. The auth log event names stay as Q3 wrote them
   (`auth.signed_in`, `auth.sign_in_failed`, ...), not the `auth.sign_in outcome=` form of B 5.3.
2. *500 responses carry `X-Request-ID`*. Starlette's `ServerErrorMiddleware` sits outside every user
   middleware, so on an unhandled exception `RequestContextMiddleware` sends the same `INTERNAL_ERROR` envelope
   itself (with the header) and re-raises. The 500 handler still runs and logs; it does not send twice. The
   request id is not reset on that path, so the "unhandled error" line keeps it.
3. *Route templates*: FastAPI 0.143 puts the included router's prefix-less route in `scope["route"]`. The template
   is rebuilt as request-path prefix segments + the route's `path_format` (path parameters are single segments
   in this API). No match gives `unmatched`.
4. *The queue collector is refreshed at scrape time*. `/metrics` sets the queue gauges from its own app's
   database (5 s cache, `system_scope`) instead of a global `Collector`, because many apps (tests) share the
   default registry in one process. Inline mode reports `sp_workers_alive = RUN_WORKERS`.
5. *Readiness*: `/health/ready` does not use `get_ctx`. It tries `ctx.start()` itself, so a failing lazy start
   gives 503 instead of 500: `SchemaError` gives `"schema":"outdated"`, anything else
   `"database":"error"`. `schema` is `ok` only for state `current`; behind, empty, legacy and ahead all count as
   `outdated`. On a ping failure `schema` is `"unknown"`.
6. *`/metrics` is not in the OpenAPI schema* (`include_in_schema=False`), so the Q3 route-coverage table needs
   no root entry. 401 uses the standard envelope (`AUTH_REQUIRED`) plus `WWW-Authenticate: Bearer`.
   `METRICS_ENABLED=false` does not mount it (404).
7. *Logging setup* only installs a handler when the root logger has none (pytest capture and embedding apps are
   left alone). JSON mode routes uvicorn's own loggers through our handler, except a logger uvicorn disabled with
   `--no-access-log`. In text mode uvicorn keeps its own format, so dev shows uvicorn's access line plus our
   `http.request ... rid=` line. Context fields are captured by a handler filter in the emitting thread; extra
   fields are passed as `extra={"sp": {...}}`. `user_id` comes from `request.state.principal` (access line) or
   the bound owner (other lines).
8. *`migrate.py` keeps its `basicConfig`* (Q1 file, not in the Q5 list). The compose `migrate` one-shot
   therefore prints text lines. Change request: call `configure_logging(settings, "migrate")` in `migrate.main`.
9. *nginx real_ip*: nginx cannot read env vars in `conf.d`, so the image's entrypoint hook
   `frontend/docker/40-sp-real-ip.sh` writes `/etc/nginx/sp-real-ip.conf` from `TRUSTED_PROXY_CIDRS`. It accepts
   only address characters and is included with a glob, so a missing file is fine. `X-Forwarded-For` is always
   overwritten with `$remote_addr`, which after real_ip is the client.
10. *Compose*: `env_file: .env` is `required: false`, so `docker compose --env-file .env.example config -q`
    validates without a `.env`. The api service forces `HOST=0.0.0.0`/`PORT=8000`; otherwise the `.env.example`
    `HOST=127.0.0.1` (meant for `run_api.sh`) would make the container unreachable. The internal subnet is
    `SP_INTERNAL_SUBNET` (default `172.28.0.0/24`) and doubles as `FORWARDED_ALLOW_IPS`. The frontend image has
    its own `/healthz`.
11. *`manage prune` jobs part* uses ORM deletes, so it works on both dialects: terminal jobs with
    `finished_at` older than `JOB_RETENTION_DAYS`, and `job_workers` rows without a heartbeat for 1 day. The
    worker's own maintenance (`jobs.pg.maintenance`) is unchanged.
12. *Load script*:
    - Replay POSTs go out concurrently with their originals (exercises R8). Exactly one of the pair must carry
      `Idempotent-Replayed: true`.
    - Chaos mode kills a worker that holds a running job at the moment of the kill, so a requeue is
      guaranteed. It shortens the lease timings (6/2/2 s) unless they are set in the environment.
    - Wall time runs from the first job's `created_at` to the last `finished_at`. Queue wait is job
      `started_at - created_at`; duration is `finished_at - started_at` per kind.
    - `--database-url` and `--log-dir` are extra options; `--api-url` adds the external API's registered
      workers to the known set.
13. `tests/jobs/test_load_small.py` lives in the Q2 test directory, as B 6 names it.
14. Change request carried over from Q3: add `"superplanner.api.auth" = ["common_passwords.txt"]` to
    `pyproject.toml` package-data (Q1 file). The images copy the source tree, so Docker is unaffected.

**Acceptance criteria -> tests** (`tests/ops/` unless noted)

| Criterion | Tests / checks |
|---|---|
| Q5-1 | full suites (results below); `test_ops_health::test_ready_body` also asserts `/health` keys; existing `test_api_health` unchanged |
| Q5-2 | `test_ops_health`: live without DB (`start`/`ping` patched to raise), ready body, queued counts (PG), 503 ping down, 503 unreachable DB, 503 schema at 0001 with `DB_AUTO_MIGRATE=false`, accounts mode without cookie, lazy start inside the request |
| Q5-3 | `test_ops_request_id_logging`: 200/404/404/422/413/500/preflight all carry ids; 413 keeps CORS; echo/replace rules; `jobs.request_id` stored (both DBs); worker `job.started` + `job.finished` lines carry the enqueuing id (PG, embedded worker, real handler) |
| Q5-4 | `test_json_log_lines_and_no_secrets_during_a_full_flow` (accounts: sign-up, failed + ok sign-in, plan, solve, finance instantiate, change-password, sign-out; every line JSON with the 5 keys; no password/CSRF/cookie/plan name/email); formatter unit tests; `test_worker_metrics_server_and_json_logs` (worker stderr all JSON); manual uvicorn check (JSON lines incl. uvicorn's, no access duplicate with `--no-access-log`) |
| Q5-5 | `test_ops_metrics`: every B 5.4 metric present, route templates, no raw ids/paths, `unmatched`; token 401/200; disabled 404; not in OpenAPI; accounts mode without OwnershipViolation; auth events; SSE counted but no histogram, gauge back to 0; worker `:port/metrics` job metrics (PG subprocess) |
| Q5-6 | `tests/jobs/test_load_small.py` (10 runs, 2 workers, `pg_load`); G8 runs below |
| Q5-7 | `test_ops_deploy`: `.env.example` lists every `config.py` variable, no secret, `.env` git-ignored; nginx text checks (XFF overwrite, no `$proxy_add_x_forwarded_for`, `/metrics` 404, SSE settings); real-ip script; non-root Dockerfiles; compose structure; `docker compose --env-file .env.example config -q` exits 0 (CLI v5.6.0, no daemon needed) |
| Q5-8 | `test_production_defaults`, `test_production_cors_star_with_credentials_refused`, `test_production_cors_star_exits_2` |
| Q5-9 | DEPLOY.md sections 1 and 2; `test_run_api_sh_starts_zero_setup` (no config, file-DB, inline, `/problems` without login); section 2 commands used for the load runs |

**Load runs (G8)**: local PostgreSQL 16 (127.0.0.1:54329), a fresh database `sp_load` each time, 3 worker
processes at concurrency 1, API subprocess without embedded workers, 25 solver + 25 finance runs.
```
$ DATABASE_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/sp_load .venv/bin/python scripts/load_queue.py --runs 50 --workers 3
runs              50 (solver 25, finance 25)
workers           3 x concurrency 1
wall seconds      25.7
throughput        116.9 runs/min
queue wait        p50 1.62s  p95 19.60s
duration finance_run p50 2.62s  p95 2.77s  (n=25)
duration solver_run  p50 0.10s  p95 0.99s  (n=25)
jobs per worker   load-w0-c4f8=18, load-w1-904c=15, load-w2-9fff=17
replays           5/5 returned the same run id
requeues          0
duplicates        0
lost              0
result            OK                                                     (exit 0)

$ ... scripts/load_queue.py --runs 50 --workers 3 --chaos-kill-after 5
runs              50 (solver 25, finance 25)
workers           3 x concurrency 1  (chaos: killed load-w0-ee77)
wall seconds      36.2
throughput        82.8 runs/min
queue wait        p50 1.85s  p95 29.11s
duration finance_run p50 2.62s  p95 2.87s  (n=25)
duration solver_run  p50 0.09s  p95 1.04s  (n=25)
jobs per worker   load-w0-ee77=3, load-w1-3ce0=23, load-w2-3515=24
replays           5/5 returned the same run id
requeues          1
duplicates        0
lost              0
result            OK                                                     (exit 0)
```
Exactly once means:
- every run is `completed` with exactly one job, which `succeeded`;
- each run has exactly one terminal event, and it is the last; `seq` runs contiguously from 1;
- solver schedule ranks run 0..k; each finance run has exactly one result;
- `attempts` is 1, except the one requeued job, which has 2 and a `run_requeued` event;
- every final `lease_owner` is one of the three workers.

The p95 queue wait is long because all 50 runs are enqueued at once onto 3 slots. It is backlog, not claim
latency.

**Suite results** (2026-10-20, working tree incl. Q2/Q3):
- G1, file-DB: `cd backend && .venv/bin/pytest -rs` gives `1974 passed, 27 skipped`. The skips are PostgreSQL-only
  tests plus one that needs the queue backend, each with a reason.
- G2, PostgreSQL 16 (queue + embedded workers): `SP_TEST_DB=postgres ... .venv/bin/pytest -rs` gives
  `2000 passed, 1 skipped` (the file-DB-only WAL backup test).
- `tests/ops` alone: 41 tests (3 PostgreSQL-only skips on file-DB).
- G9: `docker compose --env-file .env.example config -q` exits 0. There is no Docker daemon here, so images were
  not built.


### 10.WP-5 Frontend
(to be filled)

### 10.WP-6 QA
(to be filled)
