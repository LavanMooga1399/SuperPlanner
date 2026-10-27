# SuperPlanner Phase 2b - Delivery Plan ("make it scalable")

> **Historical note (PostgreSQL-only release):** "file-DB" below refers to the embedded file database of earlier
> releases. It was removed; SuperPlanner now runs on PostgreSQL only (see `docs/DEPLOY.md`, Changelog, and
> `docs/ARCHITECTURE.md` section 25). Statements about file-DB behaviour describe the past.

Owner: team lead (LEAD). Contract: `docs/PHASE2B.md` (cited "B n", including its "Review notes" R1-R14), then
`docs/PHASE2.md`, `docs/FINANCE.md`, `docs/ARCHITECTURE.md` for everything B does not change. If this plan and B
disagree on behaviour, B wins; on file ownership, order and acceptance, this plan wins (it supersedes B 7).
Developers write only to their own subsection of B 10 (Q1 -> "10.WP-1", Q2 -> "10.WP-2", Q3 -> "10.WP-3",
Q4 -> "10.WP-5", Q5 -> "10.WP-4", Q6 -> "10.WP-6"). LEAD owns B 0-9, the review notes and this file.

Hard rules for everyone:
- No `git commit`, no `git push`.
- **file-DB + one process + `AUTH_MODE=single_user` stays the zero-setup default** and must work on Windows with only
  Python and Node (no Postgres, Docker, Redis, bash or WSL needed to run or test the product in this mode).
- Existing features keep working. An existing test may change only as listed in B 8.2; any other change is
  recorded in B 8.2 by LEAD *before* the test is edited. No existing assertion changes.
- Python packages go into `backend/.venv` and are pinned in `backend/requirements.txt` (and `pyproject.toml`).
  Allowed new packages: `alembic==1.20.0`, `psycopg[binary]==3.3.6`, `argon2-cffi==25.1.0`,
  `prometheus-client==0.26.0`. No Redis/Celery. No new npm packages.
- Local Postgres for development and tests: binaries in `/usr/lib/postgresql/16/bin`; never run `initdb`/`postgres`
  as root: `backend/scripts/pg_dev_cluster.sh` creates and uses the OS user `spdb`. Agents put the data dir under
  their session scratchpad (e.g. `/tmp/claude-0/-home-user-superplanner/<session>/scratchpad/pgdata`), port 54329.
  Docker files are written and validated with `docker compose config` only if the CLI works; running containers
  is not required.

## 0. Overview

| Q | Name | Owner role | Starts | Depends on |
|---|------|-----------|--------|------------|
| Q1 | Database layer, Alembic, ownership plumbing, dual-DB test harness | backend-developer (A) | day 0, alone | B 2.12, 3, 4.2, 4.7 |
| Q2 | Job queue, worker, cross-process SSE/cancel, idempotency | backend-developer (A) | after Q1 accepted | Q1 |
| Q3 | Accounts backend: auth endpoints, sessions, CSRF, rate limits, ownership enforcement in accounts mode, admin CLI | backend-developer (B) | after Q1 accepted, parallel to Q2 | Q1 |
| Q4 | Frontend auth UI | ui-developer | day 0 (against B 4.5/4.10 contract), parallel | B 4.5 contract; Q3 for integration |
| Q5 | Deployment, ops, logging, metrics, health/ready, load script, DEPLOY.md | backend-developer (A or B) | after Q2 **and** Q3 accepted | Q2, Q3 |
| Q6 | Testing: acceptance suite, accounts e2e, dual-DB and load verification | tester | day 0 (writing against B), final runs last | all |

```
Q1 (alone) ─► Q1 accepted ─┬─► Q2 queue/worker ─────────┐
                           └─► Q3 accounts backend ─────┴─► Q5 ops/metrics/load ─┐
Q4 frontend auth UI (day 0, mocks; integrate after Q3) ─────────────────────────┤
Q6 test writing (day 0) ─────────────────────────────────────────────────────────┴─► Q6 final runs ─► LEAD review
```

### 0.1 File ownership (authoritative; no file has two owners at the same time)

Paths are relative to the repo root; `sp/` = `backend/superplanner/`. "Handed to" = ownership moves at the
acceptance of the earlier package; the earlier owner never touches it again.

| Q | Owns (create/edit only these) |
|---|---|
| Q1 | `backend/requirements.txt`, `backend/pyproject.toml` (all four new pins, markers), `backend/alembic.ini`, `sp/migrations/**`, `sp/migrate.py`, `sp/api/db/**` (`session.py`, `models.py` incl. `JobRow`/`JobWorkerRow`, new `ownership.py`, `__init__.py`), `sp/api/finance/db_models.py`, `sp/api/auth/__init__.py`, `sp/api/auth/models.py`, `sp/api/auth/maintenance.py` (prune helpers for sessions/rate-limits), `sp/api/auth/deps.py` (single_user form; **handed to Q3**), `sp/api/auth/router.py` (empty `APIRouter(prefix="/auth")` stub; **handed to Q3**), `sp/api/config.py` (**every** 2b setting of B 5.1 and all startup validation; frozen afterwards, see 0.2), `sp/api/main.py` (frozen afterwards until Q5), `sp/api/limits.py` (U+0000 rejection, B 3.5.7), `sp/api/context.py` (**handed to Q2**), `sp/api/services/problem_service.py`, `sp/api/services/schedule_service.py`, `sp/api/finance/service.py`, `sp/api/services/run_service.py`, `sp/api/services/replan_service.py`, `sp/api/finance/run_service.py`, `sp/api/routes/solver_runs.py`, `sp/api/routes/schedules.py`, `sp/api/finance/router.py` (the last six **handed to Q2**), `backend/tests/conftest.py` (new root), `backend/tests/db/**`, every existing test edit of B 8.2 **except** `tests/api_finance/apifin_helpers.py`, `backend/scripts/pg_dev_cluster.sh`, `.gitignore` |
| Q2 | `sp/jobs/**`, `sp/worker/**`, `sp/obs/__init__.py`, `sp/obs/job_metrics.py`, `sp/api/executor.py`, and (from Q1) `sp/api/context.py`, `sp/api/services/run_service.py`, `sp/api/services/replan_service.py`, `sp/api/finance/run_service.py`, `sp/api/routes/solver_runs.py`, `sp/api/routes/schedules.py`, `sp/api/finance/router.py`; `backend/tests/jobs/**`, `backend/tests/api_finance/apifin_helpers.py` (`worker_done` only), `backend/run_worker.sh`, `backend/run_worker.ps1` |
| Q3 | `sp/api/auth/**` except `models.py` (incl. `deps.py`, `router.py`, `maintenance.py` from Q1; new `passwords.py`, `sessions.py`, `csrf.py`, `ratelimit.py`, `schemas.py`, `common_passwords.txt`), `sp/api/errors.py`, `sp/manage.py`, `backend/tests/auth/**` |
| Q4 | `frontend/src/auth/**` (incl. its own CSS file), `frontend/src/api/client.ts`, `frontend/src/finance/api/client.ts`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/intake/state/IntakeContext.tsx`, `frontend/src/api/types.ts`, `frontend/src/finance/api/types.ts`, `frontend/src/components/RunProgress.tsx`, `frontend/src/finance/components/FinRunProgress.tsx`, `frontend/vite.config.ts`, `frontend/package.json` (scripts only), `frontend/e2e/playwright.config.ts` (backend env + `testIgnore` only), `frontend/e2e/playwright.accounts.config.ts` |
| Q5 | `sp/obs/logging.py`, `sp/obs/request_context.py`, `sp/obs/http_metrics.py`, `sp/api/routes/health.py`, `sp/api/routes/metrics.py`, `backend/scripts/load_queue.py`, `backend/tests/ops/**`, `backend/Dockerfile`, `backend/.dockerignore`, `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore`, `docker-compose.yml`, `.env.example`, `.gitattributes`, `backend/run_api.ps1`, `backend/run_api.sh`, `docs/DEPLOY.md`; and (after Q2/Q3 acceptance, Q5 is then the only active backend package) `sp/api/main.py`, `sp/api/config.py`, `sp/jobs/worker.py` (logging bind + metrics server only), `sp/manage.py` (`prune` job part only) |
| Q6 | `backend/tests/acceptance_phase2b/**` (own `conftest.py`), `frontend/e2e/accounts/**` (specs + `accounts-helpers.ts`), B 10.WP-6 |

### 0.2 Ownership rules

- **Shared files are pre-built by Q1** so the parallel packages never meet: Q1 adds every setting of B 5.1 to
  `config.py` (job, auth, ops), wires `create_app` completely (OwnershipScopeMiddleware; routers included with
  `dependencies=[Depends(require_user)]`; `auth.router` stub included without it; CORS `allow_credentials` and the
  exposed/allowed headers of B 4.4), and wraps SSE polls in `owner_scope` (B 4.7) in the route files before
  handing them to Q2. After Q1, `config.py` and `main.py` are frozen until Q5; a missing setting is a change
  request to LEAD, who applies it (serialized, one editor).
- **Schema is frozen after Q1** (B 3.2). If Q2 or Q3 needs a column/index, LEAD decides and assigns one
  `0003_*` revision to one owner; never two parallel revisions.
- Q2 and Q3 overlap check: Q3 edits nothing under `sp/jobs`, `sp/api/services`, `sp/api/finance`, `sp/api/routes`,
  `sp/api/context.py`; Q2 edits nothing under `sp/api/auth`, `sp/api/errors.py`, `sp/manage.py`. Q2 calls
  `sp.api.auth.maintenance.prune_auth_tables(s, now)` (written by Q1, signature frozen) from worker maintenance.
- Q4 never edits backend files; it develops against B 4.5 with a mocked `/auth/*` (Vite proxy to a backend from Q3
  once available). Q4 edits no existing e2e spec; the only edit in `playwright.config.ts` is env + `testIgnore`.
- Q6 never edits product code or other packages' tests; defects go to the owner named in the failing criterion.
- Nobody edits `docs/source/**`, existing e2e specs/helpers, or the `/api/v1/health` body.

## 1. Regression gate (checked by LEAD before review; Q6 runs it, each package runs G1-G3 before handing in)

Baseline measured 2026-10-19: **1794** backend tests collected (`pytest --collect-only -q`), **65** Playwright tests
in 14 spec files, all green.

| # | Gate | Command / check |
|---|------|-----------------|
| G1 | Existing backend suite on file-DB, inline, single_user: 1794 existing tests pass, total = 1794 + new, 0 failures, skips only with a stated reason | `cd backend && .venv/bin/pytest` |
| G2 | Full backend suite on PostgreSQL (queue + embedded workers from Q2 on; inline before): 0 failures | `SP_TEST_DB=postgres SP_TEST_PG_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres .venv/bin/pytest` |
| G3 | No existing assertion changed: `git diff -U0 backend/tests frontend/e2e` touches only files/lines listed in B 8.2 | LEAD reads the diff |
| G4 | 65 existing Playwright tests pass unchanged (single_user, file-DB, inline) | `cd frontend && npm run e2e` |
| G5 | Accounts e2e pass | `cd frontend && npm run e2e:accounts` |
| G6 | `npm run build` (incl. `tsc --noEmit`) clean; `npm audit` no high/moderate | |
| G7 | Zero-setup check: fresh clone flow of DEPLOY.md section 1 with no `DATABASE_URL`, no Postgres, no env file: API starts, creates its local file database, UI works without login | Q6 scripted check |
| G8 | Load: `load_queue.py --runs 50 --workers 3` exit 0 on local Postgres; `--chaos-kill-after 5` exit 0 | report pasted in B 10.WP-4 |
| G9 | `docker compose config -q` exits 0 (only if the docker CLI works; else a YAML schema lint is recorded) | |

## 2. Q1 - Database layer, Alembic, ownership plumbing, dual-DB harness (backend-developer A, first, alone)

Steps:
1. Install and pin the four packages (0.1); register markers `postgres_only`, `file_db_only`, `inline_jobs`, `pg_load`.
2. `pg_dev_cluster.sh {init|start|stop|url} [DIR] [PORT]` (B 3.6): creates `spdb` with `useradd -r -m` when run as
   root, `runuser -u spdb --`, `initdb --locale=C --encoding=UTF8 -A trust` bound to 127.0.0.1, role `sp_test`
   CREATEDB. Idempotent.
3. `Database`: URL normalisation, `is_postgres`, Postgres pool/pre-ping/timeouts/`application_name`,
   `json_serializer(allow_nan=False)` on Postgres (B 3.1, 3.5); lazy psycopg import; file-DB path unchanged.
4. Models: `OwnedMixin` + `owner_id` on the 7 owned tables, `UserRow`/`UserSessionRow`/`AuthRateLimitRow`, `JobRow`,
   `JobWorkerRow`, BigInteger variants, all indexes of B 3.3 (no finance one-active index, R5).
5. Alembic: frozen `0001_initial` (11 tables exactly as today), `0002_phase2b` (B 3.3 incl. data step and the
   legacy de-duplication of B 8.1.4). `migrate.py` with `schema_state`/`ensure_schema`/CLI, file-DB FK-off upgrade +
   `foreign_key_check` (R1), backup API (R2), legacy subset handling (R3), Postgres advisory lock and
   `statement_timeout=0`.
6. `ownership.py` (B 4.7): `owner_scope`, `system_scope`, fail-closed `do_orm_execute`, `before_flush` stamping,
   `OwnershipScopeMiddleware`; `auth/deps.py::require_user` async, single_user form only (accounts mode returns 401
   `AUTH_REQUIRED` until Q3).
7. `context.py`: `write_guard()`, `ensure_schema` + `ensure_local_user` in `start()`, whole `start()` in
   `system_scope()` (R9); inline-only `jobs` attribute: an `InlineQueue`-compatible shim with `enqueue` (writes the
   job row), `dispatch` (conditional claim + submit), `request_cancel`, `notify_cancel`, `wait_idle`, so job rows
   exist in both modes from Q1 on. (Q2 replaces the shim with `sp/jobs/inline.py`.)
8. Services: every `with WRITE_LOCK` -> `with ctx.write_guard()`; `lock=True` lookups with `key_share=True`, plain
   `FOR UPDATE` for deletes (R4); `add_event` locks the run row; worker-created rows set `owner_id`; SSE polls in
   `owner_scope`; `WRITE_LOCK` alias kept.
9. Config (all of B 5.1 + validation), `main.py` wiring (0.2), `limits.py` NUL check.
10. Test harness: root `conftest.py` (B 3.6), per-folder `db_url` -> `db_url_factory(...)`, hard-coded URLs, the
    `inline_jobs` markers of B 8.2 (no-op until Q2). `tests/db/**`.

Acceptance criteria (each is a test in `tests/db/` unless stated):
- Q1-1 G1 green; G2 green with `JOB_BACKEND=inline` on Postgres.
- Q1-2 `alembic upgrade head` on an empty DB and `create_all + stamp head` produce the same schema: autogenerate
  `compare_metadata` reports no diffs on both dialects, and on Postgres every partial index's `pg_indexes.indexdef`
  contains its predicate.
- Q1-3 Legacy file-DB database built from the frozen 0001 definitions with data in all 11 tables (including
  `problem_versions`, `solver_run_events`, `schedules`, `finance_results`): first app start upgrades it, row counts of
  all 11 tables are unchanged, all owned rows have `owner_id='usr_local'`, a `.bak-0001-*` file exists and opens
  with the same row counts, `PRAGMA foreign_key_check` is empty. Same for a pre-finance file with only the 6
  scheduling tables (finance tables created).
- Q1-4 Legacy file with two approved schedules for one problem and two active solver runs: upgrade keeps the newest
  of each, the others are `superseded` / `failed` with `RESTART_ERROR` + a `run_failed` event.
- Q1-5 `downgrade base` then `upgrade head` round trip succeeds on both dialects.
- Q1-6 `migrate check` exits 3 on a DB behind head with `DB_AUTO_MIGRATE=false`; two concurrent `ensure_schema`
  calls on one empty Postgres DB both return and `alembic_version` has one row.
- Q1-7 Partial unique indexes: a second `queued` solver run for one problem and a second `approved` schedule are
  rejected by the DB on both dialects (direct inserts); the services map the `IntegrityError` to the documented 409.
- Q1-8 Postgres: 8 threads x 25 `add_event` calls on one run yield seq 1..200 with no gaps or duplicates.
- Q1-9 Ownership probes (B 4.7): with user B bound, `Session.get`, `select(Model)`, column-only select, `count`,
  `exists`, ORM `update`, ORM `delete` on A's rows see/affect nothing; an unbound query inside a request returns
  500 `INTERNAL_ERROR` and logs `OwnershipViolation`; `inspect.iscoroutinefunction(require_user)` is true; a
  `TestClient` used without `with` serves its first request (lazy start, R9).
- Q1-10 Lock-strength test (Postgres): while one connection holds the plan lock taken by `create_what_if`, another
  connection can insert a `finance_results` row for that plan (no wait) - proves `FOR NO KEY UPDATE`.
- Q1-11 A JSON body containing `\u0000` returns 422 `VALIDATION_ERROR` on both dialects.
- Q1-12 Windows: no new code path in file-DB mode imports psycopg (test: import `superplanner.api.main` with
  `sys.modules["psycopg"] = None` and create a file-DB app).
- Q1-13 `pg_dev_cluster.sh init/start/url/stop` works as root in a scratch dir; `postgres` never runs as uid 0.

## 3. Q2 - Job queue, worker, cross-process SSE and cancel (backend-developer A, after Q1)

Steps: `sp/jobs/types.py`, `inline.py`, `pg.py` (claim/heartbeat/reaper SQL, B 2.5), `worker.py` (`WorkerLoop`,
`WorkerContext`, LISTEN/NOTIFY with polling fallback, maintenance), `sp/worker/__main__.py`; `context.py` per backend
(B 2.2, inline+Postgres guard R7, embedded workers); `run_job(ctx, run_id, lease)` with fenced start/progress/final
writes, lost-vs-cancel rule (R6), `RetryableJobError` mapping, requeue/backoff (B 2.6), shutdown order (B 2.9);
cancel via `request_cancel`/`notify_cancel`; `Idempotency-Key` on the four create routes with lookup after the plan
lock (R8); `run_requeued` event; `obs/job_metrics.py`; `apifin_helpers.worker_done` -> `ctx.jobs.wait_idle`;
`run_worker.sh/.ps1`. Postgres test default becomes `JOB_BACKEND=queue`, `WORKER_EMBEDDED=auto`.

Acceptance criteria (tests in `tests/jobs/`, Postgres-only unless stated):
- Q2-1 G1 and G2 green (G2 now in queue mode with embedded workers).
- Q2-2 3 threads claiming from 30 queued jobs concurrently: every job claimed exactly once.
- Q2-3 Lease expiry: a claimed job whose heartbeat is stopped is requeued by the reaper after `JOB_LEASE_SECONDS`
  (test uses 2 s), gets a `run_requeued` event with `attempt: 2`, completes once; `attempts == 2`.
- Q2-4 After `max_attempts` expiries the run is `failed` with `WORKER_LOST_ERROR` and one `run_failed` event.
- Q2-5 Stale lease: a handler holding an old token cannot write progress or a terminal state (`LeaseLost`), and
  the run's events contain no event from it after the takeover.
- Q2-6 Lost is not cancelled (R6): simulate heartbeat failure past the threshold with a live lease -> the run is
  never `cancelled`; it is requeued after expiry and completes.
- Q2-7 Cancel a running solver run and a running finance run through the API: terminal `cancelled` within 3 s;
  a finance cancel racing the final write never stores a result ([R11] rule).
- Q2-8 Graceful shutdown with a running job: job requeued with `attempts` unchanged, run `queued` with
  `run_requeued` reason `worker_shutdown`, no `cancelled` status, completed by the next worker.
- Q2-9 `kill -9` of a worker subprocess mid-run: another worker subprocess completes the run; exactly one terminal
  event; solver schedule ranks `0..k` unique / finance exactly one result.
- Q2-10 Idempotency: same key + same body -> 202, same `run_id`, `Idempotent-Replayed: true`; same key + other body
  -> 422 `IDEMPOTENCY_KEY_MISMATCH`; 10 concurrent identical requests -> one run, all 202 with the same `run_id`
  (no 409); invalid key format -> 422 with `loc ["header","idempotency-key"]`; key of user A not visible to user B
  (bound owners). Runs on both dialects.
- Q2-11 Cross-instance: two `TestClient` apps on one Postgres DB (A with embedded workers, B without): create on
  A, stream SSE on B to `run_completed`; cancel on B stops a run executing on A within 3 s.
- Q2-12 NOTIFY wake-up: idle worker claims a new job in < 1 s with `WORKER_POLL_SECONDS=5`.
- Q2-13 API restart in queue mode: stopping app A (embedded workers) with a running job and starting app B on the
  same DB -> the run completes (not `failed`); in inline mode the existing recovery behaviour is unchanged (existing
  tests, file-DB).
- Q2-14 Config: `JOB_BACKEND=queue` with file-DB exits 2; `inline` + Postgres + `SP_ENV=production` exits 2;
  `python -m superplanner.worker` with a file-DB URL exits 2; with schema behind head exits 3.
- Q2-15 Inline mode on file-DB writes one job row per run, ending `succeeded`/`failed`/`cancelled` consistent with the
  run (sample of existing flows).

## 4. Q3 - Accounts backend and ownership enforcement (backend-developer B, after Q1, parallel to Q2)

Steps: passwords (argon2id profiles, policy, common list, dummy hash, rehash), sessions (token, hash, idle/absolute
expiry, throttled touch, rotation, revoke on sign-in/up with an existing session), CSRF + Origin (B 4.4), the five
endpoints (B 4.5) with the exact error codes, DB-backed rate limits (B 4.6), `require_user` accounts form (disabled
users, R9), `errors._HTTP_CODES`, `manage.py` (B 4.9 except the jobs part of `prune`).

Acceptance criteria (tests in `tests/auth/`, both dialects):
- Q3-1 G1 and G2 green; single_user responses unchanged (G1 is the proof); `GET /auth/session` in single_user
  returns the B 4.5 body; auth mutations -> 409 `AUTH_DISABLED`.
- Q3-2 Sign-up/sign-in/sign-out/change-password/session: every success and error case of B 4.5 with exact status,
  code and envelope; cookie attributes `HttpOnly`, `SameSite=Lax`, `Path=/`, no `Domain`, `Secure` + `__Host-` name
  when `COOKIE_SECURE=true`.
- Q3-3 Password storage: `password_hash` starts with `$argon2id$`; profile `default` parameters t=3, m=65536, p=4;
  `fast` refused with `SP_ENV=production`; weak-password reasons as specified.
- Q3-4 CSRF: in accounts mode every unsafe method on a protected route without/with a wrong `X-CSRF-Token` -> 403
  `CSRF_FAILED`; with a foreign `Origin` -> 403 even with a valid token; GET/SSE need no token.
- Q3-5 Route coverage (B 4.7 a, black-box over `app.openapi()`): every non-allowlisted `/api/v1` operation returns
  401 `AUTH_REQUIRED` without a cookie, including POSTs with invalid bodies (401, not 422); the enumerated set equals
  the B 4.8 table (56 existing + new).
- Q3-6 Cross-user matrix (B 4.7 b): user B calling every endpoint of B 4.8 with A's ids gets 404 `NOT_FOUND` with a
  body byte-equal to an unknown-id call; lists omit A's objects; `compare` with one foreign id -> 404;
  `base_result_id` of A's result -> 404; send-to-planner of A's result -> 404; A's objects unchanged afterwards
  (compare JSON before/after).
- Q3-7 Sessions: expired, idle, revoked and disabled-user sessions -> 401; change-password revokes all other
  sessions and rotates the current one (new cookie and csrf token); sign-in creates a new session id (fixation).
- Q3-8 Rate limits: 11th sign-in for one email within 5 min -> 429 `RATE_LIMITED` with `Retry-After` and
  `details.retry_after_seconds`; counted across two app instances on one DB; counted before password verification.
- Q3-9 Unknown-email and wrong-password sign-ins take comparable time (both verify a hash; assert the dummy hash is
  verified, not wall time).
- Q3-10 `manage create-user/set-password/disable-user/enable-user/reassign-owner --dry-run/reassign-owner/list-users`
  work; after `reassign-owner` the new account sees the legacy plans and runs.
- Q3-11 Logs never contain the password, session token or csrf token (capture logs during the auth tests and grep).

## 5. Q4 - Frontend auth UI (ui-developer, parallel)

Steps (B 4.10): `src/auth/` (`AuthContext`, `authFetch`, `RequireAuth`, `SignInPage`, `SignUpPage`, `AccountPage`,
`AccountMenu`, `SessionExpiredBanner`), the two `raw()` hooks (CSRF header, 401 -> expired, 403 `CSRF_FAILED` ->
refresh + one retry), routes and guard in `main.tsx`, menu/banner in `App.tsx`, intake draft clearing on sign-out and
user change, `run_requeued` in both type lists and progress components, `SP_API_TARGET` in `vite.config.ts`,
`playwright.config.ts` env (`AUTH_MODE=single_user`, `JOB_BACKEND=inline`) + `testIgnore: ["accounts/**"]`,
`playwright.accounts.config.ts` (B 4.10 incl. R13: port 5174, `PUBLIC_BASE_URL`, `CORS_ORIGINS`), `e2e:accounts`.

Acceptance criteria:
- Q4-1 G4 (65 existing tests) and G6 green; in single_user mode no auth page, menu or extra request blocks the UI
  (one `GET /auth/session` at boot; a 404/network error there falls back to single_user).
- Q4-2 All test ids of B 4.10 present; sign-in/sign-up forms are keyboard-usable with labels and `role="alert"` errors.
- Q4-3 Every unsafe request from both clients carries `X-CSRF-Token` in accounts mode (verified by Q6 e2e and by a
  request-interception check); no token in single_user mode.
- Q4-4 Session expiry shows the banner (`session-expired`) on the next action and returns to the original page
  after sign-in (`next` param, only same-origin relative paths accepted - no open redirect).
- Q4-5 Sign-out clears every `sessionStorage` key starting with `sp.intake.`.
- Q4-6 `run_requeued` renders "Restarting on another worker (attempt n of m)" in both progress components; unknown
  events still ignored.

## 6. Q5 - Deployment, operations, metrics, load script (backend-developer, after Q2 and Q3)

Steps: B 5.1-5.6 and B 6: JSON/text logging with request ids and context fields; `RequestContextMiddleware`;
`/health/live`, `/health/ready` (in `system_scope`, R9); `/metrics` (+ `METRICS_TOKEN`) and the queue collector;
worker metrics server and log binding; Dockerfiles, nginx (XFF overwrite and real_ip, R10), compose (fixed internal
subnet, `FORWARDED_ALLOW_IPS`, `POSTGRES_INITDB_ARGS=--locale=C.UTF-8`, migrate one-shot, `stop_grace_period`),
`.env.example`, `.gitattributes`, `run_api.ps1`, `run_api.sh` (`--no-access-log` only with `LOG_FORMAT=json`),
`load_queue.py` (B 6, `lease_owner` kept by `finish`), `manage prune` jobs part, `docs/DEPLOY.md` (all 10 sections of
B 5.6 incl. accepted auth risks and Windows notes).

Acceptance criteria (tests in `tests/ops/`):
- Q5-1 G1, G2 green; `/api/v1/health` body unchanged (existing test).
- Q5-2 `/health/live` 200 without DB access; `/health/ready` 200 with the B 5.2 body; 503 `not_ready` with
  `"schema":"outdated"` on a DB behind head and `"database":"error"` with the DB down; both in accounts mode without
  a cookie (public) and without `OwnershipViolation`.
- Q5-3 Every response (incl. 404, 413, 422, 500) carries `X-Request-ID`; a valid incoming id is echoed, an invalid
  one replaced; the enqueuing request id appears in the worker's `job.started` log line.
- Q5-4 With `LOG_FORMAT=json`, every log line is one JSON object with `ts`, `level`, `logger`, `service`, `msg`;
  no line contains a password, cookie, token or plan document (grep during a full flow).
- Q5-5 `/metrics` exposes every metric of B 5.4 with the listed labels; `route` uses templates (no ids); with
  `METRICS_TOKEN` set, missing/wrong bearer -> 401; worker `:9101/metrics` exposes job metrics.
- Q5-6 Load (G8): 50 mixed runs, 3 workers: exit 0; report shows throughput, wait/duration p50/p95, jobs per worker,
  duplicates 0, lost 0; chaos variant exit 0 with >= 1 requeued job. `tests/jobs/test_load_small.py` (10 runs, 2
  workers, marker `pg_load`) passes in G2.
- Q5-7 `docker compose config -q` passes (G9); images run as non-root; `.env.example` lists every B 5.1 variable and
  contains no real secret; `.env` is git-ignored; nginx config sets `X-Forwarded-For $remote_addr` and not
  `$proxy_add_x_forwarded_for` (config-text test); `/metrics` not proxied.
- Q5-8 Production config validation: `SP_ENV=production` + defaults -> accounts mode, empty `CORS_ORIGINS`,
  `COOKIE_SECURE=true`; `CORS_ORIGINS=*` with credentials exits 2.
- Q5-9 DEPLOY.md: LEAD follows section 1 on a clean checkout (G7) and section 2 with `pg_dev_cluster.sh` + one
  worker; both work as written.

## 7. Q6 - Testing (tester)

Writes from day 0 against B, runs final verification after Q1-Q5.
- `backend/tests/acceptance_phase2b/`: end-to-end API scenarios per mode - (a) file-DB/inline/single_user: full
  solver + finance + what-if + replan + approve flow, existing DB upgraded from a legacy file; (b) Postgres/queue/
  accounts with two users and two worker subprocesses: both users run solver and finance runs concurrently, each sees
  only own objects, all runs complete exactly once (job/run/event invariants I1-I4 of B 2.4 checked from the DB);
  (c) API restart and worker kill during runs; (d) cancel from another API instance.
- `frontend/e2e/accounts/`: the six specs of B 4.10 (redirect + sign-up; sign-out/wrong password/next; **user B
  cannot see user A's scheduling and finance plans in lists, by URL, or by direct API GET (404)**; change password
  signs out the other context; session expiry banner; live solver and finance progress while signed in).
- Final runs: G1-G9; results, counts and the load report into B 10.WP-6.

Acceptance criteria:
- Q6-1 Every Q1-Q5 criterion has at least one automated test or a recorded manual check (traceability table in
  B 10.WP-6).
- Q6-2 G1-G9 recorded green with test counts (backend file-DB total, backend Postgres total, 65 + accounts e2e).
- Q6-3 Each defect found is filed to the owning package (by the file ownership table) with a failing test name.

## 8. Review checklist for LEAD (code-review mode)

Run first: lost-vs-cancel (R6) and shutdown ordering; fencing on every worker write; lock order and lock strength
(R4); file-DB migration FK-off (R1) and backup API (R2); fail-closed ownership and every `system_scope` site (R9);
CSRF on all unsafe methods; XFF handling (R10); idempotency ordering (R8); SSE seq ordering; Windows zero-setup (G7).
