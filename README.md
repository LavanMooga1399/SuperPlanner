# SuperPlanner

A universal planning and optimization tool. Describe any goal as tasks, dependencies, resources,
calendars and deadlines — a factory production run, an exam-preparation plan, a multi-team project —
and SuperPlanner builds a validated, explainable schedule.

- **Solver portfolio:** priority-rule heuristics, Google OR-Tools CP-SAT, and a Genetic Algorithm,
  chosen automatically with stated reasons (or picked manually).
- **Feasibility first:** every schedule is re-checked by an independent validator; a plan is never
  reported feasible while it breaks a hard rule.
- **Explainable:** each task says why it starts when it does (dependency, resource, calendar, lock),
  plus critical path and plain-language infeasibility messages.
- **Planning Studio UI:** task/resource editors, dependency graph, live solver progress, Gantt
  (task and resource views), schedule comparison, approval and replanning.

## Quick start

Requirements: Python 3.12 or 3.13, Node 22 and **PostgreSQL 16** (Docker Desktop or a native install).
SuperPlanner stores everything in PostgreSQL; there is no file-database mode. Steps: start PostgreSQL with two
roles (an *owner* that runs migrations and a restricted *app* role the API uses), migrate, run the backend with
`APP_ENV=development`, run the frontend. Use two terminals — the backend keeps running in the first one.

### Windows (PowerShell)

**1. PostgreSQL — option (a): Docker Desktop** (from the repository root)
```powershell
Copy-Item .env.example .env      # placeholder passwords are fine for local development
docker compose up -d db          # PostgreSQL 16 on 127.0.0.1:5432, data in the volume "pgdata"
docker compose ps db             # wait until it shows "healthy"
```
On the first start the container creates the database `superplanner` with the roles `superplanner_owner`
(password `change-me-owner`) and `superplanner_app` (password `change-me-app`), as set in `.env`.

**1. PostgreSQL — option (b): native installer.** Install PostgreSQL 16 from https://www.postgresql.org/download/windows/
(remember the `postgres` password you choose), then create the roles and the database with `psql`
(from the repository root):
```powershell
$psql = "C:\Program Files\PostgreSQL\16\bin\psql.exe"
& $psql -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 `
  -v db=superplanner -v owner=superplanner_owner -v owner_password=change-me-owner `
  -v app=superplanner_app -v app_password=change-me-app -f backend\scripts\pg_setup_roles.sql
```
(`pg_setup_roles.sql` runs `CREATE ROLE ... LOGIN`, `CREATE DATABASE superplanner OWNER superplanner_owner` and the
DML-only grants for `superplanner_app`; it is safe to re-run.)

**2. Backend** — Terminal 1 (http://127.0.0.1:8000):
```powershell
cd backend
py -3.13 -m venv .venv          # first time only (or py -3.12)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:APP_ENV = "development"
$env:MIGRATION_DATABASE_URL = "postgresql+psycopg://superplanner_owner:change-me-owner@127.0.0.1:5432/superplanner"
$env:DATABASE_URL = "postgresql+psycopg://superplanner_app:change-me-app@127.0.0.1:5432/superplanner"
.\.venv\Scripts\python.exe -m superplanner.migrate upgrade
.\.venv\Scripts\python.exe -m uvicorn superplanner.api.main:app --host 127.0.0.1 --port 8000
```

**3. Frontend** — Terminal 2 (http://localhost:5173), unchanged:
```powershell
cd frontend
npm install
npm run dev
```

If PowerShell says "running scripts is disabled", use `npm.cmd install` / `npm.cmd run dev`. In `cmd.exe`, do
not add `# comments` after commands — `cmd` passes them on as arguments.

### Linux / macOS

```bash
# 1. PostgreSQL: either Docker ...
cp .env.example .env && docker compose up -d db
# ... or a native PostgreSQL 16 (as a superuser; add -h/-U as needed):
psql -d postgres -v ON_ERROR_STOP=1 -v db=superplanner -v owner=superplanner_owner -v owner_password=change-me-owner \
     -v app=superplanner_app -v app_password=change-me-app -f backend/scripts/pg_setup_roles.sql

# 2. backend (terminal 1)
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export APP_ENV=development
export MIGRATION_DATABASE_URL=postgresql+psycopg://superplanner_owner:change-me-owner@127.0.0.1:5432/superplanner
export DATABASE_URL=postgresql+psycopg://superplanner_app:change-me-app@127.0.0.1:5432/superplanner
.venv/bin/python -m superplanner.migrate upgrade
./run_api.sh

# 3. frontend (terminal 2)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173, **sign up** (user accounts are the default; each user sees only their own data), then
choose what you want to plan or pick a template: Validate → Optimize → review the Gantt → Approve.
For a single-person local setup without sign-in, also set `APP_ENV=development` **and** `AUTH_MODE=single_user`
(refused in any other environment).

**Kavach sample data** (manufacturing master data: items, BOMs, routings, plant, shifts), one line in the backend
terminal with the same `DATABASE_URL`:
```bash
python -m superplanner.manage load-sample --email you@example.com      # the account you signed up with
python -m superplanner.manage load-sample                               # AUTH_MODE=single_user: the local user
```
(Windows: `.\.venv\Scripts\python.exe -m superplanner.manage load-sample --email you@example.com`. Add
`--replace` to replace that user's manufacturing data, `--sample small|medium` for the other samples. The
Manufacturing area of the UI has the same "Load sample" action.)

The backend refuses to start with a one-line message when `DATABASE_URL` is missing or not PostgreSQL, or when the
database is not at the current schema revision ("Run: python -m superplanner.migrate upgrade"). After `git pull`,
re-run the `pip install`, `migrate upgrade` and `npm install` lines. For local development only, `AUTO_MIGRATE=true`
upgrades the schema at start (using `MIGRATION_DATABASE_URL`). In development the API runs the job workers
in-process; production setups (separate workers, TLS, backups, roles) are in `docs/DEPLOY.md`.

## Tests

The backend tests run against PostgreSQL only; the local test cluster (127.0.0.1:54329, data in
`backend/.pgdata`, git-ignored) is created once with a script:

```bash
cd backend && scripts/pg_dev_cluster.sh init   # once (Linux; PostgreSQL 16 server binaries)
cd backend && .venv/bin/pytest -q              # engine, API, database and integration tests
cd frontend && npm run build                   # type-check + production build
cd frontend && npm run e2e                     # Playwright end-to-end: fresh PostgreSQL database per run
cd frontend && npm run e2e:accounts            # Playwright, accounts mode
```

Other servers: `SP_TEST_PG_URL` (a role with CREATEDB) for pytest and `SP_E2E_PG_URL` for the e2e runs;
`SP_TEST_PG_SUPERUSER_URL` enables the least-privilege role tests (default: user `postgres` on the test cluster).

## Finance (goal-based financial planning)

SuperPlanner Finance plans **where** (asset class), **when** and **how much** to save for each goal,
cash-flow aware, with an estimated chance of reaching every goal. Open it from the **Finance** link in
the top bar (`http://localhost:5173/finance`), then either pick an example (Young professional,
Family, Near retirement) or **Start from scratch**. A 7-step guide (Profile, Income & expenses, Debts,
Savings & holdings, Goals, Risk & assumptions, Review) prefills sensible defaults; every step can be
skipped, and expert settings are behind a toggle. **Build my plan** shows goal cards, charts, monthly
contributions, plain-language explanations and suggested fixes. From the results you can test
**What-if** changes, **Compare** scenarios, **Export CSV**, or **Send to planner** to turn the next
months into a scheduling plan (money calendar).

> SuperPlanner Finance is an educational planning tool. It is not investment, tax or legal advice and
> does not recommend specific financial products. Results are estimates based on the assumptions you
> entered; actual returns, inflation and income can differ, and you could end up with less than your
> goals need. Consider consulting a qualified, registered investment adviser before making investment
> decisions.

Asset classes only (no product names), user-editable assumptions, no market data, no network calls.
Design: `docs/FINANCE.md`; delivery plan: `docs/PLAN-FINANCE.md`.

Finance tests:

```bash
cd backend && .venv/bin/pytest -q tests/finance tests/api_finance   # engine and API
cd frontend && npm run typecheck && npm run build                   # UI type-check + build
cd frontend && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test -c e2e/playwright.config.ts finance
```

## Repository layout

| Path | Contents |
|---|---|
| `backend/superplanner/engine` | Pure-Python core: model, preflight checks, graph/CPM, decoder, validator, explanations, solver selector |
| `backend/superplanner/engine/solvers` | Heuristic, CP-SAT and Genetic Algorithm solvers behind one interface |
| `backend/superplanner/templates` | Domain templates (manufacturing, exam prep, project, blank) |
| `backend/superplanner/api` | FastAPI service: plans, versions, background solver runs with SSE progress, schedules, approve/compare/export/replan |
| `frontend/` | React + TypeScript Planning Studio (Vite); `frontend/src/finance` is the Finance UI |
| `docs/ARCHITECTURE.md` | Full design and API contract |
| `docs/PLAN.md` | Delivery plan and acceptance criteria |
| `docs/source/` | Original product blueprint text |
| `.claude/agents/` | Agent team roles used to build this (architect, team lead, backend, UI, tester) |

Configuration (all settings: `.env.example`, `docs/DEPLOY.md`): `DATABASE_URL` (required, PostgreSQL),
`MIGRATION_DATABASE_URL`, `APP_ENV`, `AUTH_MODE`, `PUBLIC_BASE_URL`, `CORS_ORIGINS`, `PORT`, `HOST`, `DB_POOL_SIZE`, ...

Changelog: since the PostgreSQL-only release, SQLite is no longer supported (no file database, no automatic
schema creation); see the changelog at the end of `docs/DEPLOY.md`.

Not yet built (see `docs/ARCHITECTURE.md` §20): authentication/multi-tenancy, Celery/Redis workers,
Monte Carlo simulation, the financial-planning module, an LLM planning copilot, drag-to-reschedule.
