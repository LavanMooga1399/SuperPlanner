# SuperPlanner - Deployment and operations runbook

PostgreSQL only. Covers local development, database roles, the Docker Compose deployment, configuration, connection
pooling and TLS, scaling, backups and restore, upgrades, day-to-day operations and troubleshooting.
Design background: `docs/PHASE2B.md` (sections 2-6).

Contents:
1. Local development
2. Database roles (least privilege)
3. Docker Compose deployment
4. Configuration reference and production checklist
5. Connection pooling
6. TLS to the database
7. Scaling workers
8. Backups and restore
9. Upgrades and rollback
10. Operations: logs, metrics, stuck jobs, cancelling, pruning
11. Windows notes
12. Troubleshooting
13. Changelog

---

## 1. Local development

The README "Quick start" is the short version (Windows PowerShell and Linux/macOS, Docker Desktop or a native
PostgreSQL). In short:

```bash
cp .env.example .env && docker compose up -d db       # or a native PostgreSQL + backend/scripts/pg_setup_roles.sql
cd backend
export APP_ENV=development
export MIGRATION_DATABASE_URL=postgresql+psycopg://superplanner_owner:change-me-owner@127.0.0.1:5432/superplanner
export DATABASE_URL=postgresql+psycopg://superplanner_app:change-me-app@127.0.0.1:5432/superplanner
.venv/bin/python -m superplanner.migrate upgrade      # explicit step; AUTO_MIGRATE=true does it at start (dev)
./run_api.sh                                          # API with embedded worker threads (WORKER_EMBEDDED=auto)
python -m superplanner.manage load-sample --email you@example.com   # optional: Kavach sample data
```

`APP_ENV` defaults to `production`; `development` must be set explicitly. It is the only environment that allows
`AUTH_MODE=single_user`, `JOB_BACKEND=inline`, `COOKIE_SECURE=false`, http origins, a missing `METRICS_TOKEN` and
placeholder database passwords.

**Separate worker** (the production shape on one machine): `WORKER_EMBEDDED=0 ./run_api.sh` in one terminal and
`./run_worker.sh --concurrency 2` in another (Ctrl+C / SIGTERM: graceful stop; a second Ctrl+C skips the grace).
Runs are rows in the `jobs` table: workers claim them with `FOR UPDATE SKIP LOCKED`, hold a lease and send
heartbeats. A killed worker's job is requeued once its lease expires (`JOB_LEASE_SECONDS=30`), and its run shows
"Restarting on another worker". `python -m superplanner.worker --once` drains the queue and exits.

**Throwaway cluster for tests** (Linux): `backend/scripts/pg_dev_cluster.sh init` creates a PostgreSQL 16 cluster in
`backend/.pgdata` (git-ignored) on 127.0.0.1:54329 with `trust` auth (development only!) and the role `sp_test`
(CREATEDB, password `sp_test`). As root it creates the OS user `spdb` and runs postgres as it.
- Backend suite: `cd backend && .venv/bin/pytest` (always PostgreSQL; `SP_TEST_PG_URL` overrides the admin URL,
  default `postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres`). A migrated template database is
  built once per session and cloned per test. The role tests connect as the superuser
  (`SP_TEST_PG_SUPERUSER_URL`, default user `postgres` on the same server) and run the app as a DML-only role.
- e2e: `cd frontend && npm run e2e` / `npm run e2e:accounts` create a fresh database per run on the same cluster
  (`SP_E2E_PG_URL` overrides it), migrate it, start the API on it and drop it at the end
  (`backend/scripts/e2e_db.py`, `backend/scripts/run_e2e_api.sh`).

Load sanity check (needs a disposable database):
```bash
psql -h 127.0.0.1 -p 54329 -U sp_test -d postgres -c "CREATE DATABASE sp_load"
DATABASE_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/sp_load \
  .venv/bin/python scripts/load_queue.py --runs 50 --workers 3 [--chaos-kill-after 5] [--json report.json]
```
The script exits 0 only if every run completed exactly once (see `docs/PHASE2B.md` section 6).

Large manufacturing JSON responses (BOM explosions) compress well: enable `gzip on; gzip_types application/json;`
at the reverse proxy.

## 2. Database roles (least privilege)

SuperPlanner uses two login roles per database; neither is a superuser:

| Role (default name) | Used by | Privileges |
|---|---|---|
| owner `superplanner_owner` | `python -m superplanner.migrate upgrade` / compose `migrate` (`MIGRATION_DATABASE_URL`) | owns the database and schema `public`; creates/alters tables (DDL) |
| app `superplanner_app` | API and workers (`DATABASE_URL`) | `CONNECT`, `TEMPORARY`; `USAGE` on `public`; `SELECT, INSERT, UPDATE, DELETE` on tables, `USAGE, SELECT, UPDATE` on sequences; no DDL, no `TRUNCATE` |

`backend/scripts/pg_setup_roles.sql` creates both roles and the database idempotently (re-running it resets the
passwords and re-applies the grants) and sets default privileges, so every table a later migration creates is
usable by the app role automatically. Run it as a superuser (or a role with CREATEROLE and CREATEDB):

```bash
psql -h db.internal -U postgres -d postgres -v ON_ERROR_STOP=1 \
     -v db=superplanner -v owner=superplanner_owner -v owner_password='<owner secret>' \
     -v app=superplanner_app -v app_password='<app secret>' -f backend/scripts/pg_setup_roles.sql
# or the wrapper (passwords from the environment, connection options passed to psql):
SP_OWNER_PASSWORD='<owner secret>' SP_APP_PASSWORD='<app secret>' backend/scripts/pg_setup_roles.sh -h db.internal -U postgres
```
Then:
```bash
MIGRATION_DATABASE_URL=postgresql+psycopg://superplanner_owner:<owner secret>@db.internal:5432/superplanner?sslmode=verify-full \
  python -m superplanner.migrate upgrade
DATABASE_URL=postgresql+psycopg://superplanner_app:<app secret>@db.internal:5432/superplanner?sslmode=verify-full  # API, workers
```
Rules:
- The API and workers never get the owner URL. `AUTO_MIGRATE=true` (development convenience) uses
  `MIGRATION_DATABASE_URL`; with only an app-role URL it fails with `permission denied`.
- `migrate` resolves its URL as `--url`, else `MIGRATION_DATABASE_URL`, else `DATABASE_URL`.
- The application never creates tables at runtime (no `create_all`). The API, worker and `manage` refuse to start
  unless the schema is at `migrate.HEAD`, with `schema error: ... Run: python -m superplanner.migrate upgrade`
  (exit code 3).
- Passwords inside URLs must be URL-encoded (or use URL-safe random strings, e.g. `secrets.token_urlsafe(24)`).
  Alternatively omit the password from the URL and use `~/.pgpass` / `PGPASSFILE` or client certificates.
- Managed PostgreSQL (RDS, Cloud SQL, Azure): run the script as the provider's admin role; it only needs
  CREATEROLE and CREATEDB (on PostgreSQL 16+ the script grants the owner role to the admin when that is needed).

## 3. Docker Compose deployment

```bash
cp .env.example .env        # set POSTGRES_PASSWORD, SP_DB_OWNER_PASSWORD, SP_DB_APP_PASSWORD,
                            # PUBLIC_BASE_URL and METRICS_TOKEN at least (placeholders are refused)
docker compose up -d --build
docker compose ps           # db healthy, migrate exited 0, api/worker healthy, frontend up
```

| Service | Image | Role |
|---|---|---|
| `db` | `postgres:16-alpine` | Database, volume `pgdata`, C.UTF-8 locale, healthcheck `pg_isready`; port published on `127.0.0.1:${DB_PORT:-5432}` only. Usable alone: `docker compose up -d db` |
| `migrate` | backend `api` target | One-shot `python -m superplanner.migrate upgrade` as the owner role, runs before api/worker |
| `api` | backend `api` target | uvicorn on :8000 (internal), `APP_ENV=production`, app role, no embedded workers |
| `worker` | backend `worker` target | `python -m superplanner.worker`, app role, `WORKER_REPLICAS` replicas (default 2), metrics :9101 |
| `frontend` | `frontend/Dockerfile` | nginx-unprivileged on :8080 (published as `HTTP_PORT`), serves the SPA, proxies `/api/` |

Roles in compose: `POSTGRES_USER` (default `postgres`) is the bootstrap superuser of the container and is never
used by the application. On the **first** start of an empty `pgdata` volume, `backend/scripts/docker-initdb-roles.sh`
runs `pg_setup_roles.sql` and creates `SP_DB_OWNER_USER` / `SP_DB_APP_USER` with the passwords from `.env`.
Changing the passwords later: re-run the script (section 2) through `docker compose exec db psql -U postgres ...`
and update `.env`. On a shared host remove the `ports` entry of `db` (the stack itself does not need it).

All images run as non-root users (backend uid 10001, nginx uid 101). The backend code under `/app` is owned by root,
so the runtime user cannot change it. The images install only the runtime dependencies (`backend/requirements-runtime.txt`,
the same pins as `pyproject.toml`); pytest and httpx are left out (`backend/requirements.txt` adds them for development).
The `migrate`, `api` and `worker` services run with `read_only: true`, `cap_drop: [ALL]`,
`no-new-privileges:true` and a 64 MiB tmpfs on `/tmp`. Nothing writes under `/app` at runtime, because the
database is PostgreSQL. If you build a derived image that needs a writable directory, mount a volume or tmpfs there.

**TLS** is terminated by your reverse proxy or load balancer in front of `HTTP_PORT`. `COOKIE_SECURE=true` (the
production default; `false` is refused outside development) means the browser only sends the session cookie over
https. If that proxy forwards client IPs, set `TRUSTED_PROXY_CIDRS` to its address range. nginx then takes the
client IP from its `X-Forwarded-For`, otherwise the proxy's IP is used for the per-IP rate limits. For TLS between
the application and the database see section 6.

**First user.** Production runs in accounts mode. Either sign up in the UI (`SIGNUP_ENABLED=true`, the default), or
create users from the command line and then set `SIGNUP_ENABLED=false`:
```bash
echo 'a long passphrase here' | docker compose run --rm -T api python -m superplanner.manage \
    create-user --email admin@example.com --name Admin --password-stdin
docker compose run --rm api python -m superplanner.manage list-users
```

**Moving data from a single-user installation.** Data created with `AUTH_MODE=single_user` (development) belongs
to `usr_local`. To hand it to a real account:
```bash
docker compose run --rm api python -m superplanner.manage reassign-owner --from usr_local \
    --to-email admin@example.com --dry-run      # prints counts per table
docker compose run --rm api python -m superplanner.manage reassign-owner --from usr_local \
    --to-email admin@example.com
```

Other admin commands: `set-password` (also signs the user out everywhere), `disable-user`, `enable-user`, `prune`,
`load-sample [--sample kavach|medium|small] [--email E] [--replace]` (manufacturing sample data for one user).
Exit codes: 0 ok, 1 command error, 2 configuration, 3 schema.

## 4. Configuration reference and production checklist

Every variable is listed with a comment in `.env.example`. `APP_ENV` defaults to `production`; the column shows
"development / production" where they differ.

| Variable | Default (dev / prod) | Meaning |
|---|---|---|
| `APP_ENV` (legacy alias `SP_ENV`) | `production` | `development` (explicit) or `production` |
| `DATABASE_URL` | required | `postgresql+psycopg://USER:PASSWORD@HOST:5432/DB[?sslmode=...]` (`postgres://` and `postgresql://` accepted); the app role |
| `MIGRATION_DATABASE_URL` | = `DATABASE_URL` | owner role for `migrate upgrade` and `AUTO_MIGRATE` |
| `AUTO_MIGRATE` (legacy alias `DB_AUTO_MIGRATE`) | false | upgrade the schema at startup (development convenience) |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS` | 10, 10, 30 | connection pool per process (section 5) |
| `DB_POOL_RECYCLE_SECONDS`, `DB_POOL_PRE_PING` | 1800, true | recycle connections older than this; test a pooled connection before use |
| `DB_CONNECT_TIMEOUT_SECONDS` | 10 | TCP/TLS connect timeout (libpq `connect_timeout`) |
| `DB_STATEMENT_TIMEOUT_MS`, `DB_LOCK_TIMEOUT_MS` | 30000, 10000 | per-connection `statement_timeout` / `lock_timeout` (migrations run with no statement timeout and a 60 s lock timeout) |
| `JOB_BACKEND` | `queue` | `inline` (thread pool in ONE API process) is allowed only in development |
| `RUN_WORKERS` | 2 | inline thread pool size; what `WORKER_EMBEDDED=auto` means |
| `WORKER_EMBEDDED` | `auto` / 0 | worker threads inside the API (`auto` = `RUN_WORKERS`) |
| `WORKER_CONCURRENCY`, `WORKER_KINDS`, `WORKER_ID`, `WORKER_METRICS_PORT` | 2, both kinds, generated, 9101 | worker process |
| `WORKER_POLL_SECONDS`, `WORKER_SHUTDOWN_GRACE_SECONDS` | 1.0, 30 | idle poll (NOTIFY usually wakes earlier); drain time on stop |
| `JOB_LEASE_SECONDS`, `JOB_HEARTBEAT_SECONDS`, `JOB_CANCEL_POLL_SECONDS`, `JOB_REAPER_SECONDS` | 30, 10, 1.0, 15 | leases and cancel latency |
| `JOB_MAX_ATTEMPTS`, `JOB_BACKOFF_BASE_SECONDS`, `JOB_BACKOFF_MAX_SECONDS` | 3, 5, 300 | retries after worker loss or transient errors |
| `JOB_RETENTION_DAYS`, `IDEMPOTENCY_TTL_HOURS` | 30, 24 | pruning of finished jobs; `Idempotency-Key` replay window |
| `AUTH_MODE` | `accounts` | `single_user` (no sign-in, built-in local user) only with `APP_ENV=development` |
| `SIGNUP_ENABLED` | true | self sign-up |
| `SESSION_MAX_AGE_DAYS`, `SESSION_IDLE_DAYS` | 30, 7 | session lifetime |
| `COOKIE_SECURE` | false / true | `Secure` cookie (`__Host-sp_session`); false is refused outside development |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:5173` / required, https | browser origin; used by the Origin check |
| `PASSWORD_HASH_PROFILE` | `default` | `fast` is for tests only and is refused outside development |
| `AUTH_RATE_LIMIT_ENABLED`, `AUTH_SIGNIN_LIMIT_PER_IP`, `AUTH_SIGNIN_LIMIT_PER_EMAIL`, `AUTH_SIGNUP_LIMIT_PER_IP`, `AUTH_CHANGE_PASSWORD_LIMIT_PER_USER` | true, 30, 10, 5, 10 | auth rate limits (per 5 min / hour / 15 min); the per-IP sign-in bucket is checked first, so a blocked IP does not touch per-email buckets |
| `AUTH_HASH_CONCURRENCY`, `AUTH_HASH_WAIT_SECONDS` | 0 (= max(1, CPUs / 2)), 1 | password hashes (argon2id, 64 MiB each with the `default` profile) running at once per API process; a request that waits longer than the wait time for a slot gets `429 RATE_LIMITED` with `Retry-After` |
| `AUTH_PRUNE_INTERVAL_SECONDS` | 600 | `JOB_BACKEND=inline` with accounts only: how often the API prunes sessions and rate-limit buckets |
| `CORS_ORIGINS` | four localhost dev origins / empty | comma list; outside development only explicit `https://host[:port]` origins (no `*`, `null`, wildcards, http) |
| `TRUSTED_PROXY_CIDRS` | unset | external load balancer addresses (nginx `set_real_ip_from`) |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` (compose: internal subnet) | who uvicorn trusts for `X-Forwarded-For`; never `*` |
| `MAX_BODY_BYTES` | 5 MiB | request body limit (413) |
| `LOG_LEVEL`, `LOG_FORMAT` | `INFO`, `text` / `INFO`, `json` | logging |
| `METRICS_ENABLED`, `METRICS_TOKEN` | true, unset / required | `/metrics` needs `Authorization: Bearer <token>` when set; outside development a random token of >= 24 characters is required unless `METRICS_ENABLED=false` |
| `INTAKE_AI_ENABLED`, `INTAKE_AI_TIMEOUT_SECONDS`, `ANTHROPIC_API_KEY` | false, 60, unset | optional AI assist for intake |
| `HOST`, `PORT` | 127.0.0.1, 8000 | `run_api.sh` / `run_api.ps1` bind address |
| compose only: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `SP_DB_OWNER_USER`, `SP_DB_OWNER_PASSWORD`, `SP_DB_APP_USER`, `SP_DB_APP_PASSWORD`, `DB_PORT`, `HTTP_PORT`, `WORKER_REPLICAS`, `SP_INTERNAL_SUBNET`, `SP_IMAGE_TAG` | see `.env.example` | |

Secure defaults: outside `APP_ENV=development` the processes refuse to start (exit code 2, one
`configuration error: ...` line) with `AUTH_MODE=single_user`, `JOB_BACKEND=inline`, `COOKIE_SECURE=false`,
`PASSWORD_HASH_PROFILE=fast`, a missing or non-https `PUBLIC_BASE_URL`, permissive `CORS_ORIGINS`, a missing or weak
`METRICS_TOKEN`, or a weak/placeholder password in `DATABASE_URL` / `MIGRATION_DATABASE_URL` (shorter than 12
characters or a known default such as `postgres`, `change-me`). Session and CSRF tokens need no configured secret:
each session gets its own random 256-bit token (only its SHA-256 is stored) and its own CSRF token.

**Production checklist**
- [ ] `APP_ENV=production` (the default), `AUTH_MODE=accounts` (the default).
- [ ] Owner and app roles created (section 2); `DATABASE_URL` = app role, `MIGRATION_DATABASE_URL` only on the
      migrate job; strong, distinct passwords (or certificates).
- [ ] `sslmode=verify-full` (or at least `require`) for a database on another host (section 6).
- [ ] TLS at the reverse proxy; `PUBLIC_BASE_URL=https://<your host>` exactly as users type it.
- [ ] `CORS_ORIGINS` empty (same-origin through nginx) unless another https origin must call the API.
- [ ] `TRUSTED_PROXY_CIDRS` set if a load balancer is in front; `FORWARDED_ALLOW_IPS` never `*`.
- [ ] `METRICS_TOKEN` set; ports 8000/9101 reachable only from your monitoring network (nginx never proxies
      `/metrics`).
- [ ] Pool sizes fit `max_connections` (section 5).
- [ ] `SIGNUP_ENABLED=false` after creating the accounts, if the instance is not meant to be public.
- [ ] Backups scheduled and a restore tested (section 8).
- [ ] Alerts on `/api/v1/health/ready`, `sp_jobs_oldest_queued_age_seconds` and `sp_workers_alive` (section 7).

**Accepted risks (by design, PHASE2B 4.6):**
- The per-email sign-in limit (10 per 5 min) lets an attacker who knows an email address keep it locked out of
  sign-in for a while. Other accounts and existing sessions are not affected.
- Sign-up answers `409 EMAIL_TAKEN` for registered emails, which reveals that an address has an account. This is
  limited to 5 sign-ups per hour per IP.
- There is no password reset by email. Admins use `manage set-password`.

## 5. Connection pooling

Each process (API replica, worker) has its own SQLAlchemy pool: at most `DB_POOL_SIZE + DB_MAX_OVERFLOW`
connections, waiting up to `DB_POOL_TIMEOUT_SECONDS` for a free one. `DB_POOL_PRE_PING=true` tests a pooled
connection before handing it out (survives database restarts and idle-connection reaping by firewalls);
`DB_POOL_RECYCLE_SECONDS` replaces connections older than that. Each worker additionally holds one `LISTEN`
connection, and each migration run one connection.

Budget: `(api_replicas + worker_replicas) * (DB_POOL_SIZE + DB_MAX_OVERFLOW) + worker_replicas + 1 <
max_connections - superuser_reserved_connections` (PostgreSQL default 100 - 3). Workers need few connections
(`DB_POOL_SIZE=4`, `DB_MAX_OVERFLOW=2` is plenty); the API needs roughly one per concurrent request plus one per
open SSE stream poll.

External poolers: PgBouncer in **session** mode works unchanged. Transaction mode is not supported, because
the queue uses `LISTEN/NOTIFY`, session advisory locks (migrations) and per-connection settings
(`statement_timeout`, `application_name`). With a pooler, keep `DB_POOL_PRE_PING=true` and set the pooler's
server idle timeout above `DB_POOL_RECYCLE_SECONDS`.

## 6. TLS to the database

libpq TLS parameters pass through unchanged in the URL query string:
```
DATABASE_URL=postgresql+psycopg://superplanner_app:<secret>@db.example.com:5432/superplanner?sslmode=verify-full&sslrootcert=/etc/superplanner/db-ca.pem
```
- `sslmode=verify-full`: encrypted, certificate chain AND host name verified. Use this for any database outside
  the local host or private container network (managed databases: download the provider's CA bundle).
- `sslmode=require`: encrypted but the server is not authenticated (protects against passive sniffing only).
  Acceptable only on a network you control.
- Client certificates: add `sslcert=...&sslkey=...` and drop the password from the URL.
- In containers mount the CA file read-only (the images have a read-only root filesystem).
- The compose `db` service talks to the other containers on the internal network only and does not enable TLS;
  enable it (server `ssl=on` with a certificate) if that network is not trusted.

## 7. Scaling workers

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

## 8. Backups and restore

Backups use `pg_dump` in custom format (`-Fc`: compressed, restorable selectively and in parallel). Run them as
the owner role (or a superuser); schedule them (e.g. daily from cron) and copy the files off the host.

Compose:
```bash
# backup
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > sp-$(date +%F).dump
# restore into the running database (stop api and worker first)
docker compose stop api worker
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
    --no-owner --role="$SP_DB_OWNER_USER"' < sp-2026-10-20.dump
docker compose run --rm migrate && docker compose up -d
```
Any server:
```bash
pg_dump -Fc -h db.internal -U superplanner_owner -d superplanner -f sp-$(date +%F).dump
pg_restore -h db.internal -U superplanner_owner -d superplanner --clean --if-exists --no-owner sp-2026-10-20.dump
```
`--no-owner` makes the restoring owner role own the objects; afterwards re-run `pg_setup_roles.sql` (section 2)
so the app role has its grants on the restored tables, then `python -m superplanner.migrate upgrade` (a no-op if
the dump is from the same version).

**Restore test** (do it after setting up backups and then regularly, e.g. monthly): restore the latest dump into
a scratch database and check it:
```bash
createdb -h db.internal -U postgres -O superplanner_owner sp_restore_test
pg_restore -h db.internal -U superplanner_owner -d sp_restore_test --no-owner --exit-on-error sp-2026-10-20.dump
MIGRATION_DATABASE_URL=postgresql+psycopg://superplanner_owner:<secret>@db.internal/sp_restore_test \
  python -m superplanner.migrate check                      # exit 0 = at the expected schema revision
psql -h db.internal -U superplanner_owner -d sp_restore_test \
  -c "SELECT (SELECT count(*) FROM users) users, (SELECT count(*) FROM problems) problems, (SELECT count(*) FROM mfg_items) items, (SELECT max(created_at) FROM audit_events) last_audit"
dropdb -h db.internal -U postgres sp_restore_test
```
Compare the counts and the newest audit timestamp with production; a dump that does not restore is not a backup.
For point-in-time recovery, add WAL archiving (`archive_mode`, or your provider's PITR) on top of the dumps.

## 9. Upgrades and rollback

**Pre-upgrade checklist**
- [ ] Read the release notes for new settings and migrations (`python -m superplanner.migrate current` shows the
      revision you are on; the new code's revision is `migrate.HEAD`).
- [ ] Take a fresh backup (section 8) and confirm it restores (at least `pg_restore --list` on the file).
- [ ] Check disk space for the migration (index builds) and plan a window: migrations take
      `ACCESS EXCLUSIVE` locks on the tables they change.
- [ ] Note the current image tag (`SP_IMAGE_TAG`) for a rollback.
- [ ] M2 (manufacturing inventory, purchasing, MRP): revision `0004_mfg_m2` adds 22 tables and new columns on
      `mfg_plant`/`mfg_items`; the app role's default privileges cover the new tables (no extra GRANT).
- [ ] Check the new `.env.example` for added variables.

**Upgrade**
1. `git pull` (or pull new image tags), then `docker compose build`.
2. `docker compose run --rm migrate` (`python -m superplanner.migrate upgrade` as the owner role). It applies
   the migrations under an advisory lock, so concurrent runs are safe. Exit 0 means the schema is at head.
   Until this has run, new API/worker processes refuse to start (exit 3) and `/health/ready` reports
   `"schema":"outdated"`.
3. `docker compose up -d`. Workers get SIGTERM, stop claiming, and finish running jobs within
   `WORKER_SHUTDOWN_GRACE_SECONDS` (30 s; compose waits 45 s). Jobs still running after that are requeued without
   using up an attempt, and new workers pick them up.
4. Check: `curl -fsS http://<host>:8080/api/v1/health/ready` shows `"status":"ready"` and
   `"schema_revision"` equal to `"schema_head"`.

Rollback: restore the backup taken before the upgrade and start the previous images (`SP_IMAGE_TAG=<old>`).
Migrations are forward-only in production. An older image against a newer schema exits with code 3 ("schema is
newer than this code").

## 10. Operations

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
- `GET /api/v1/health/ready`: database ping, schema revision found (`schema_revision`) and required
  (`schema_head`), job backend, `workers_alive`, queue counts. Returns 503 `not_ready` if the database is down or
  the schema is not at head. Use it as the readiness probe; `live` as the liveness probe.
- `GET /api/v1/health`: the original endpoint, unchanged; the UI uses it.

**Metrics.**
- `http://api:8000/metrics`: HTTP requests and durations by route template, SSE streams, queue depth, oldest
  queued age, workers alive, auth events.
- `http://worker:9101/metrics`: `sp_jobs_total{kind,outcome}`, job duration and queue wait histograms, failures
  by reason, worker slots.

Both are reachable only on the internal network. Scrape them with Prometheus on the compose network, sending the
`Bearer` token (`METRICS_TOKEN`, required outside development). With several API replicas, use `max(sp_jobs_queue_depth)`.

**Stuck jobs** (`docker compose exec db psql -U postgres superplanner`):
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

## 11. Windows notes

- Development setup with Docker Desktop or the EDB installer: README "Quick start" (PowerShell).
- Use the PowerShell scripts: `backend\run_api.ps1` and `backend\run_worker.ps1` (a separate worker is optional in
  development: the API runs embedded workers). They use `backend\.venv\Scripts\python.exe` and fall back to
  `python` on PATH. If scripts are blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
- Settings are environment variables: `$env:APP_ENV = "development"; $env:PORT = "8001"; .\run_api.ps1`.
- `psql.exe` and `pg_dump.exe` are in `C:\Program Files\PostgreSQL\16\bin` (native install); with Docker use
  `docker compose exec db psql -U postgres superplanner`.
- Ctrl+C stops the API. For the worker, Ctrl+C is a graceful stop (running jobs finish or are requeued); a second
  Ctrl+C skips the grace period.
- Line endings: `.gitattributes` keeps `*.sh` files LF, so Docker images (and the `db` init script) built from a
  Windows checkout still run their shell scripts.
- The backend tests need a PostgreSQL server: point `SP_TEST_PG_URL` at a role with CREATEDB, then run
  `.venv\Scripts\pytest`. Tests that need bash or Docker skip themselves with a reason.

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Process exits with code 2, `configuration error: ...` | An invalid or insecure setting: the line names the variable. Common ones: `DATABASE_URL` missing or not `postgresql+psycopg://`; outside `APP_ENV=development`: `AUTH_MODE=single_user`, `JOB_BACKEND=inline`, `PASSWORD_HASH_PROFILE=fast`, `COOKIE_SECURE=false`, a missing/weak `METRICS_TOKEN`, a weak database password, a non-https `PUBLIC_BASE_URL`, or `CORS_ORIGINS` with `*`, `null`, wildcards or http:// origins. For local work set `APP_ENV=development`. |
| Exit code 3, `schema error: ... Run: python -m superplanner.migrate upgrade` | The database is empty or behind the code; nothing is migrated implicitly. Run the `migrate` service / command as the owner role (`MIGRATION_DATABASE_URL`). "newer than this code" means the image is older than the database: deploy the matching version. "no Alembic revision" means the database was not created by the migrations: use an empty database or restore a backup. |
| `permission denied for schema public` / `for table ...` | A migration ran with the restricted app role (use `MIGRATION_DATABASE_URL` = owner), or tables were restored as another owner (re-run `pg_setup_roles.sql`, section 2). |
| `/health/ready` 503 `"database":"error"` | Database unreachable or wrong credentials. Check `docker compose logs db`, `DATABASE_URL`, `sslmode` and the server's `pg_hba.conf`. |
| `/health/ready` 503 `"schema":"outdated"` | Migrations not applied. Run `docker compose run --rm migrate`. |
| Runs stay "queued" | No live workers (`workers_alive: 0`), or `WORKER_KINDS` excludes that kind. Check `docker compose ps worker` and the worker logs. |
| Endless sign-in loop / `AUTH_REQUIRED` after signing in | `COOKIE_SECURE=true` but the site is served over plain http, so the browser drops the `Secure` cookie. Serve over https (`COOKIE_SECURE=false` is only accepted with `APP_ENV=development`). Also check that `PUBLIC_BASE_URL` matches the address in the browser. |
| `403 CSRF_FAILED` on every change | The page origin differs from `PUBLIC_BASE_URL` / `CORS_ORIGINS` (for example `localhost` vs `127.0.0.1`), or the page is stale. Reload. |
| Every client shares one rate-limit bucket | A load balancer is in front but `TRUSTED_PROXY_CIDRS` is not set. All requests then appear to come from the balancer's IP. |
| Live progress (SSE) arrives in bursts or not at all | A proxy is buffering. Our nginx sets `proxy_buffering off` and a 1 h read timeout. Do the same on your outer proxy (e.g. `X-Accel-Buffering: no`, disabled response buffering, idle timeout of at least 60 s). |
| `413 PAYLOAD_TOO_LARGE` | Body larger than `MAX_BODY_BYTES` (5 MiB). |

## 13. Changelog

- **PostgreSQL-only release.** SQLite support was removed: `DATABASE_URL` is required and must be PostgreSQL, the
  schema is created only by `python -m superplanner.migrate upgrade` (no automatic creation or file backups at
  start), `APP_ENV` defaults to `production`, `AUTH_MODE` defaults to `accounts`, and the least-privilege roles of
  section 2 are the recommended setup. Data in an old local file database is not migrated automatically: export
  plans from the old version (scheduling: Export JSON, finance: plan export) and import them into the new one.
