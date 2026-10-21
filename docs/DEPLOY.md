# SuperPlanner - Deployment and operations runbook

Covers local development (zero setup, also on Windows), development with PostgreSQL and separate workers, the
Docker Compose deployment, configuration, scaling, backups, upgrades, day-to-day operations and troubleshooting.
Design background: `docs/PHASE2B.md` (sections 2-6).

Contents:
1. Local development, zero setup
2. Local development with PostgreSQL and a separate worker
3. Docker Compose deployment
4. Configuration reference and production checklist
5. Scaling workers
6. Backups and restore
7. Upgrades and rollback
8. Operations: logs, metrics, stuck jobs, cancelling, pruning
9. Windows notes
10. Troubleshooting

---

## 1. Local development, zero setup (Linux, macOS, Windows)

Needs only Python 3.12 or 3.13 and Node 22. You do not need PostgreSQL, Docker, Redis, bash or WSL, and you do not need
an `.env` file.

Linux / macOS:
```bash
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run_api.sh                      # http://127.0.0.1:8000, API under /api/v1

cd ../frontend
npm install
npm run dev                       # http://localhost:5173 (proxies /api to :8000)
```

Windows (PowerShell) — use two windows, the backend keeps running in the first:
```powershell
# Window 1
cd backend
py -3.12 -m venv .venv            # Python 3.12 or 3.13
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run_api.ps1                     # if scripts are blocked: .\.venv\Scripts\python.exe -m uvicorn superplanner.api.main:app --host 127.0.0.1 --port 8000

# Window 2
cd frontend
npm install                       # npm.cmd install if PowerShell blocks npm.ps1
npm run dev
```

What you get without any configuration:
- **SQLite** database `backend/superplanner.db`. It is created on first start; older files are upgraded
  automatically, and a backup `superplanner.db.bak-<revision>-<timestamp>` is written first.
- **Inline jobs**: solver and finance runs execute in a thread pool inside the API process (`RUN_WORKERS=2`).
  No worker process is needed.
- **Single-user mode**: no sign-in; all data belongs to the built-in local user.

Tests: `cd backend && .venv/bin/pytest` (Windows: `.venv\Scripts\pytest`). They run on SQLite and need nothing
else. Frontend: `npm run build`, `npm run e2e`.

## 2. Local development with PostgreSQL and a separate worker

This is the production shape on one machine. `backend/scripts/pg_dev_cluster.sh` creates a throwaway cluster.
It listens on 127.0.0.1 only and uses `trust` auth, so use it for development only. Its role `sp_test` has
password `sp_test`.

```bash
cd backend
scripts/pg_dev_cluster.sh init                 # data in backend/.pgdata (git-ignored), port 54329
                                               # as root it creates the OS user `spdb` and runs postgres as it
export DATABASE_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres
.venv/bin/python -m superplanner.migrate upgrade   # PostgreSQL is never migrated implicitly (DB_AUTO_MIGRATE=false)

# API without embedded workers + one separate worker (two terminals):
WORKER_EMBEDDED=0 ./run_api.sh
./run_worker.sh --concurrency 2                # Ctrl+C / SIGTERM: graceful stop; a second Ctrl+C skips the grace

# or: API with embedded worker threads (the development default WORKER_EMBEDDED=auto), no worker process needed:
./run_api.sh
```

With PostgreSQL, `JOB_BACKEND` defaults to `queue`. Runs are rows in the `jobs` table: workers claim them with
`FOR UPDATE SKIP LOCKED`, hold a lease, and send heartbeats. A killed worker's job is requeued once its lease
expires (`JOB_LEASE_SECONDS=30`), and its run shows "Restarting on another worker". `python -m superplanner.worker
--once` drains the queue and exits.

Full backend suite on PostgreSQL:
`SP_TEST_DB=postgres SP_TEST_PG_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres .venv/bin/pytest`.

Load sanity check (needs a disposable database):
```bash
psql -h 127.0.0.1 -p 54329 -U sp_test -d postgres -c "CREATE DATABASE sp_load"
DATABASE_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/sp_load \
  .venv/bin/python scripts/load_queue.py --runs 50 --workers 3 [--chaos-kill-after 5] [--json report.json]
```
The script exits 0 only if every run completed exactly once (see `docs/PHASE2B.md` section 6).

## 3. Docker Compose deployment

```bash
cp .env.example .env        # set POSTGRES_PASSWORD, PUBLIC_BASE_URL, METRICS_TOKEN at least
docker compose up -d --build
docker compose ps           # postgres healthy, migrate exited 0, api/worker healthy, frontend up
```

| Service | Image | Role |
|---|---|---|
| `postgres` | `postgres:16-alpine` | Database, volume `pgdata`, C.UTF-8 locale, no published port |
| `migrate` | backend `api` target | One-shot `python -m superplanner.migrate upgrade`, runs before api/worker |
| `api` | backend `api` target | uvicorn on :8000 (internal), `SP_ENV=production`, no embedded workers |
| `worker` | backend `worker` target | `python -m superplanner.worker`, `WORKER_REPLICAS` replicas (default 2), metrics :9101 |
| `frontend` | `frontend/Dockerfile` | nginx-unprivileged on :8080 (published as `HTTP_PORT`), serves the SPA, proxies `/api/` |

All images run as non-root users (backend uid 10001, nginx uid 101). The backend code under `/app` is owned by root,
so the runtime user cannot change it. The images install only the runtime dependencies (`backend/requirements-runtime.txt`,
the same pins as `pyproject.toml`); pytest and httpx are left out (`backend/requirements.txt` adds them for development).
The `migrate`, `api` and `worker` services run with `read_only: true`, `cap_drop: [ALL]`,
`no-new-privileges:true` and a 64 MiB tmpfs on `/tmp`. Nothing writes under `/app` at runtime, because the
database is PostgreSQL. If you build a derived image that needs a writable directory, mount a volume or tmpfs there.

**TLS** is terminated by your reverse proxy or load balancer in front of `HTTP_PORT`. `COOKIE_SECURE=true` (the
production default) means the browser only sends the session cookie over https. If that proxy forwards client IPs,
set `TRUSTED_PROXY_CIDRS` to its address range. nginx then takes the client IP from its `X-Forwarded-For`,
otherwise the proxy's IP is used for the per-IP rate limits.

**First user.** Production runs in accounts mode. Either sign up in the UI (`SIGNUP_ENABLED=true`, the default), or
create users from the command line and then set `SIGNUP_ENABLED=false`:
```bash
echo 'a long passphrase here' | docker compose run --rm -T api python -m superplanner.manage \
    create-user --email admin@example.com --name Admin --password-stdin
docker compose run --rm api python -m superplanner.manage list-users
```

**Moving data from a single-user installation.** Data created in single-user mode belongs to `usr_local`. To hand
it to a real account, restore or migrate it into the PostgreSQL database first, then run:
```bash
docker compose run --rm api python -m superplanner.manage reassign-owner --from usr_local \
    --to-email admin@example.com --dry-run      # prints counts per table
docker compose run --rm api python -m superplanner.manage reassign-owner --from usr_local \
    --to-email admin@example.com
```
To move a SQLite file to PostgreSQL, export plans from the old installation (scheduling: Export JSON, finance:
plan export) and import them while signed in. There is no automatic SQLite-to-PostgreSQL copy.

Other admin commands: `set-password` (also signs the user out everywhere), `disable-user`, `enable-user`, `prune`.
Exit codes: 0 ok, 1 command error, 2 configuration, 3 schema.

## 4. Configuration reference and production checklist

Every variable is listed with a comment in `.env.example`. Set `SP_ENV=production` to switch to the production
defaults (shown as "dev / prod" below).

| Variable | Default (dev / prod) | Meaning |
|---|---|---|
| `SP_ENV` | `development` | `development` or `production` |
| `DATABASE_URL` | `sqlite:///backend/superplanner.db` / required | `sqlite:///...` or `postgresql+psycopg://...` (`postgres://` accepted) |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS` | 10, 10, 30 | PostgreSQL connection pool per process |
| `DB_STATEMENT_TIMEOUT_MS` | 30000 | PostgreSQL statement timeout (migrations run without it) |
| `DB_AUTO_MIGRATE` | true for SQLite, false for PostgreSQL | migrate at startup |
| `JOB_BACKEND` | `inline` (SQLite) / `queue` (PostgreSQL) | `queue` with SQLite is refused; `inline` with PostgreSQL is refused in production |
| `RUN_WORKERS` | 2 | inline thread pool size |
| `WORKER_EMBEDDED` | `auto` / 0 | queue mode: worker threads inside the API (`auto` = `RUN_WORKERS`) |
| `WORKER_CONCURRENCY`, `WORKER_KINDS`, `WORKER_ID`, `WORKER_METRICS_PORT` | 2, both kinds, generated, 9101 | worker process |
| `WORKER_POLL_SECONDS`, `WORKER_SHUTDOWN_GRACE_SECONDS` | 1.0, 30 | idle poll (NOTIFY usually wakes earlier); drain time on stop |
| `JOB_LEASE_SECONDS`, `JOB_HEARTBEAT_SECONDS`, `JOB_CANCEL_POLL_SECONDS`, `JOB_REAPER_SECONDS` | 30, 10, 1.0, 15 | leases and cancel latency |
| `JOB_MAX_ATTEMPTS`, `JOB_BACKOFF_BASE_SECONDS`, `JOB_BACKOFF_MAX_SECONDS` | 3, 5, 300 | retries after worker loss or transient errors |
| `JOB_RETENTION_DAYS`, `IDEMPOTENCY_TTL_HOURS` | 30, 24 | pruning of finished jobs; `Idempotency-Key` replay window |
| `AUTH_MODE` | `single_user` / `accounts` | single_user is refused in production unless `ALLOW_SINGLE_USER_IN_PRODUCTION=true` |
| `SIGNUP_ENABLED` | true | self sign-up |
| `SESSION_MAX_AGE_DAYS`, `SESSION_IDLE_DAYS` | 30, 7 | session lifetime |
| `COOKIE_SECURE` | false / true | `Secure` cookie (`__Host-sp_session`) |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:5173` / required with accounts | browser origin; used by the Origin check |
| `PASSWORD_HASH_PROFILE` | `default` | `fast` is for tests only and is refused in production |
| `AUTH_RATE_LIMIT_ENABLED`, `AUTH_SIGNIN_LIMIT_PER_IP`, `AUTH_SIGNIN_LIMIT_PER_EMAIL`, `AUTH_SIGNUP_LIMIT_PER_IP`, `AUTH_CHANGE_PASSWORD_LIMIT_PER_USER` | true, 30, 10, 5, 10 | auth rate limits (per 5 min / hour / 15 min); the per-IP sign-in bucket is checked first, so a blocked IP does not touch per-email buckets |
| `AUTH_HASH_CONCURRENCY`, `AUTH_HASH_WAIT_SECONDS` | 0 (= max(1, CPUs / 2)), 1 | password hashes (argon2id, 64 MiB each with the `default` profile) running at once per API process; a request that waits longer than the wait time for a slot gets `429 RATE_LIMITED` with `Retry-After`. Peak hashing memory per process is about `AUTH_HASH_CONCURRENCY` x 64 MiB |
| `AUTH_PRUNE_INTERVAL_SECONDS` | 600 | `JOB_BACKEND=inline` with accounts only: how often the API deletes expired sessions and stale rate-limit buckets (in queue mode the workers' maintenance does it) |
| `CORS_ORIGINS` | four localhost dev origins / empty | comma list; `*` is refused in accounts mode |
| `TRUSTED_PROXY_CIDRS` | unset | external load balancer addresses (nginx `set_real_ip_from`) |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` (compose: internal subnet) | who uvicorn trusts for `X-Forwarded-For`; never `*` |
| `MAX_BODY_BYTES` | 5 MiB | request body limit (413) |
| `LOG_LEVEL`, `LOG_FORMAT` | `INFO`, `text` / `INFO`, `json` | logging |
| `METRICS_ENABLED`, `METRICS_TOKEN` | true, unset | `/metrics`; a set token requires `Authorization: Bearer <token>` |
| `INTAKE_AI_ENABLED`, `INTAKE_AI_TIMEOUT_SECONDS`, `ANTHROPIC_API_KEY` | false, 60, unset | optional AI assist for intake |
| `HOST`, `PORT` | 127.0.0.1, 8000 | `run_api.sh` / `run_api.ps1` bind address |
| compose only: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `HTTP_PORT`, `WORKER_REPLICAS`, `SP_INTERNAL_SUBNET`, `SP_IMAGE_TAG` | see `.env.example` | |

Invalid combinations stop the process with exit code 2 and one `configuration error: ...` line.

**Production checklist**
- [ ] `SP_ENV=production`, `AUTH_MODE=accounts` (the default), a strong `POSTGRES_PASSWORD`.
- [ ] TLS at the reverse proxy; `COOKIE_SECURE=true`; `PUBLIC_BASE_URL=https://<your host>` exactly as users type it.
- [ ] `CORS_ORIGINS` empty (same-origin through nginx) unless another origin must call the API.
- [ ] `TRUSTED_PROXY_CIDRS` set if a load balancer is in front; `FORWARDED_ALLOW_IPS` never `*`.
- [ ] `METRICS_TOKEN` set, or port 8000/9101 reachable only from your monitoring network (nginx never proxies
      `/metrics`).
- [ ] `SIGNUP_ENABLED=false` after creating the accounts, if the instance is not meant to be public.
- [ ] Backups scheduled (section 6) and a restore tested.
- [ ] Alerts on `/api/v1/health/ready`, `sp_jobs_oldest_queued_age_seconds` and `sp_workers_alive` (section 5).

**Accepted risks (by design, PHASE2B 4.6):**
- The per-email sign-in limit (10 per 5 min) lets an attacker who knows an email address keep it locked out of
  sign-in for a while. Other accounts and existing sessions are not affected.
- Sign-up answers `409 EMAIL_TAKEN` for registered emails, which reveals that an address has an account. This is
  limited to 5 sign-ups per hour per IP.
- There is no password reset by email. Admins use `manage set-password`.

## 5. Scaling workers

- **Replicas, not threads, for CPU.** The solver and the finance simulation are CPU-bound Python (CP-SAT releases
  the GIL, the rest mostly does not). One worker process with `WORKER_CONCURRENCY=2` is fine for I/O and short
  jobs. For more throughput, add processes: `docker compose up -d --scale worker=4`. A good starting point is one
  replica per CPU core with `WORKER_CONCURRENCY=1` or 2.
- **Dedicated pools.** `WORKER_KINDS=solver_run` or `finance_run` on separate worker services (copy the
  `worker` service in a compose override), so long finance simulations do not starve solver runs.
- **API replicas.** `--scale api=2`. nginx re-resolves `api` every 10 s and round-robins. SSE streams and cancels
  work across instances, because both go through the database.
- **Database connections.** Each process holds up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` connections, and each worker
  also holds one `LISTEN` connection. Keep
  `(api_replicas + worker_replicas) * (DB_POOL_SIZE + DB_MAX_OVERFLOW) + worker_replicas < max_connections`
  (PostgreSQL default 100). Workers need few connections, so `DB_POOL_SIZE=4`, `DB_MAX_OVERFLOW=2` is fine.
- **What the queue metrics mean.**
  - `sp_jobs_queue_depth{status="queued"}` above zero for a long time means not enough worker slots.
  - `sp_jobs_oldest_queued_age_seconds` is the wait users feel. Alert when it stays above about 60 s.
  - `sp_workers_alive == 0` with queued jobs means runs are not processed at all. The API stays "ready" and keeps
    accepting runs; `/health/ready` shows `workers_alive`.
  - `sp_job_failures_total{reason="lease_expired"}` going up means workers are dying, for example from OOM
    kills.

Measured on the development machine (local PostgreSQL 16, 3 worker processes, concurrency 1, 25 solver + 25
finance runs): about 117 runs/min. With one worker SIGKILLed after 5 jobs: about 83 runs/min, 1 job requeued,
0 lost, 0 duplicates. See `docs/PHASE2B.md` 10.WP-4.

## 6. Backups and restore

PostgreSQL (compose):
```bash
# backup (custom format, compressed); schedule it, e.g. daily from cron, and copy it off the host
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > sp-$(date +%F).dump
# restore into the running database (stop api and worker first)
docker compose stop api worker
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' \
    < sp-2026-10-20.dump
docker compose run --rm migrate && docker compose up -d
```
SQLite (development):
- Stop the API and copy `backend/superplanner.db`. Or, while it is running, use
  `sqlite3 backend/superplanner.db ".backup backup.db"`. A plain file copy of a running database can miss data
  still in the `-wal` file.
- Before every schema migration the API writes `superplanner.db.bak-<revision>-<timestamp>` next to the database,
  using SQLite's backup API. Delete old ones when you no longer need them.

## 7. Upgrades and rollback

1. Back up the database (section 6).
2. `git pull` (or pull new image tags), then `docker compose build`.
3. `docker compose run --rm migrate`. This applies the schema migrations under an advisory lock. Exit 0 means the
   schema is at head.
4. `docker compose up -d`. Workers get SIGTERM, stop claiming, and finish running jobs within
   `WORKER_SHUTDOWN_GRACE_SECONDS` (30 s; compose waits 45 s). Jobs still running after that are requeued without
   using up an attempt, and new workers pick them up.
5. Check: `curl -fsS http://<host>:8080/api/v1/health/ready` shows `"status":"ready"` and the expected
   `schema_revision`.

Rollback: restore the backup taken in step 1 and start the previous images (`SP_IMAGE_TAG=<old>`). Migrations are
forward-only in production. An older image against a newer schema exits with code 3 ("schema is newer than this
code").

## 8. Operations

**Logs.** `docker compose logs -f api worker`. In production every line is one JSON object:
```json
{"ts":"2026-10-20T08:00:00.123Z","level":"INFO","logger":"superplanner.http","service":"api","msg":"http.request",
 "request_id":"6c1f...","user_id":"usr_3f2a...","method":"POST","route":"/api/v1/problems/{problem_id}/solver-runs",
 "status":202,"duration_ms":41.7}
```
- Every response carries `X-Request-ID`. A client-sent value matching `[A-Za-z0-9._-]{1,64}` is kept; nginx
  generates one otherwise. The id is stored on the job, and the worker binds it to its lines (`job.claimed`,
  `job.started`, `job.finished`, `job.requeued`), so you can follow one run from the API into the worker:
  `docker compose logs api worker | grep '"request_id":"6c1f'`, or by run:
  `... | grep '"run_id":"run_...'` (worker lines carry `job_id`, `run_id`, `kind`, `worker_id`, `attempt`).
- Passwords, cookies, session/CSRF tokens, `Authorization` headers and plan/intake contents are never logged.
  Users appear only as `user_id`.
- Development (`LOG_FORMAT=text`): `<time> INFO superplanner.http: http.request method=GET ... rid=<id>`.

**Health.**
- `GET /api/v1/health/live`: process liveness, no database access.
- `GET /api/v1/health/ready`: database ping, schema revision, job backend, `workers_alive`, queue counts. Returns
  503 `not_ready` if the database is down or the schema is not at head.
- `GET /api/v1/health`: the original endpoint, unchanged; the UI uses it.

**Metrics.**
- `http://api:8000/metrics`: HTTP requests and durations by route template, SSE streams, queue depth, oldest
  queued age, workers alive, auth events.
- `http://worker:9101/metrics`: `sp_jobs_total{kind,outcome}`, job duration and queue wait histograms, failures
  by reason, worker slots.

Both are reachable only on the internal network. Scrape them with Prometheus on the compose network, sending the
`Bearer` token when `METRICS_TOKEN` is set. With several API replicas, use `max(sp_jobs_queue_depth)`.

**Stuck jobs** (`docker compose exec postgres psql -U superplanner superplanner`):
```sql
-- what is queued / running, oldest first
SELECT id, kind, status, attempts, max_attempts, lease_owner, lease_expires_at, run_after, last_error
  FROM jobs WHERE status IN ('queued','running') ORDER BY created_at LIMIT 50;
-- running jobs whose lease expired (the reaper requeues them within JOB_REAPER_SECONDS)
SELECT id, lease_owner, now() - lease_expires_at AS overdue FROM jobs
 WHERE status = 'running' AND lease_expires_at < now();
-- workers and their heartbeats
SELECT id, hostname, pid, concurrency, busy, heartbeat_at, stopped_at FROM job_workers ORDER BY heartbeat_at DESC;
```
Do not edit `jobs` rows by hand while workers run. Use cancel instead.

**Cancelling.** Use the UI's Cancel button or `POST /api/v1/solver-runs/{id}/cancel` /
`POST /api/v1/finance/runs/{id}/cancel`. A queued job is cancelled at once. A running job stops within about
`JOB_CANCEL_POLL_SECONDS`, on whichever worker holds it.

**Pruning.** Workers prune finished jobs older than `JOB_RETENTION_DAYS`, stale worker rows, expired sessions and
old rate-limit buckets every 10 minutes. To run it by hand:
`docker compose run --rm api python -m superplanner.manage prune`.

## 9. Windows notes

- Use the PowerShell scripts: `backend\run_api.ps1` and `backend\run_worker.ps1` (the worker is only needed with
  PostgreSQL). They use `backend\.venv\Scripts\python.exe` and fall back to `python` on PATH. If scripts are
  blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
- Create the venv with `py -3.13 -m venv .venv`. Docker is not needed for development. PostgreSQL is optional: the
  EDB installer works; then set
  `$env:DATABASE_URL = "postgresql+psycopg://user:pass@127.0.0.1:5432/superplanner"` and run
  `.venv\Scripts\python -m superplanner.migrate upgrade` once.
- Settings are environment variables: `$env:PORT = "8001"; .\run_api.ps1`. A SQLite path with a drive letter:
  `$env:DATABASE_URL = "sqlite:///C:/Users/me/superplanner.db"` (forward slashes, three slashes after `sqlite:`).
- Ctrl+C stops the API. For the worker, Ctrl+C is a graceful stop (running jobs finish or are requeued); a second
  Ctrl+C skips the grace period.
- Line endings: `.gitattributes` keeps `*.sh` files LF, so Docker images built from a Windows checkout still run
  their shell scripts.
- The backend tests run on Windows with `.venv\Scripts\pytest`. Tests that need bash, PostgreSQL or Docker skip
  themselves with a reason.

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Process exits with code 2, `configuration error: ...` | An invalid setting combination: the line names the variable. Common ones: `JOB_BACKEND=queue` with SQLite, `CORS_ORIGINS=*` in accounts mode, `PASSWORD_HASH_PROFILE=fast` or `AUTH_MODE=single_user` in production, missing `PUBLIC_BASE_URL` or `DATABASE_URL` in production. |
| Exit code 3, `schema error: ... Run: python -m superplanner.migrate upgrade` | The PostgreSQL schema is behind the code (PostgreSQL is not migrated implicitly). Run the `migrate` service. "newer than this code" means the image is older than the database: deploy the matching version. |
| `/health/ready` 503 `"database":"error"` | Database unreachable or wrong credentials. Check `docker compose logs postgres` and `DATABASE_URL`. |
| `/health/ready` 503 `"schema":"outdated"` | Migrations not applied. Run `docker compose run --rm migrate`. |
| Runs stay "queued" | No live workers (`workers_alive: 0`), or `WORKER_KINDS` excludes that kind. Check `docker compose ps worker` and the worker logs. |
| Endless sign-in loop / `AUTH_REQUIRED` after signing in | `COOKIE_SECURE=true` but the site is served over plain http, so the browser drops the `Secure` cookie. Serve over https, or set `COOKIE_SECURE=false` only on a trusted internal network. Also check that `PUBLIC_BASE_URL` matches the address in the browser. |
| `403 CSRF_FAILED` on every change | The page origin differs from `PUBLIC_BASE_URL` / `CORS_ORIGINS` (for example `localhost` vs `127.0.0.1`), or the page is stale. Reload. |
| Every client shares one rate-limit bucket | A load balancer is in front but `TRUSTED_PROXY_CIDRS` is not set. All requests then appear to come from the balancer's IP. |
| Live progress (SSE) arrives in bursts or not at all | A proxy is buffering. Our nginx sets `proxy_buffering off` and a 1 h read timeout. Do the same on your outer proxy (e.g. `X-Accel-Buffering: no`, disabled response buffering, idle timeout of at least 60 s). |
| `413 PAYLOAD_TOO_LARGE` | Body larger than `MAX_BODY_BYTES` (5 MiB). |
