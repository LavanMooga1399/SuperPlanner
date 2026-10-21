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

Requirements: Python 3.12 or 3.13, Node 22. Nothing else (no PostgreSQL, Docker or `.env` needed): the
backend uses a local SQLite file, runs jobs in-process and has no sign-in. Use two terminals — the backend
keeps running in the first one.

**Windows (PowerShell)**

Terminal 1 — backend (http://127.0.0.1:8000):
```powershell
cd backend
py -3.12 -m venv .venv          # first time only (or py -3.13)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn superplanner.api.main:app --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend (http://localhost:5173):
```powershell
cd frontend
npm install
npm run dev
```

If PowerShell says "running scripts is disabled", use `npm.cmd install` / `npm.cmd run dev`. In `cmd.exe`, do
not add `# comments` after commands — `cmd` passes them on as arguments.

**Linux / macOS**
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && ./run_api.sh
cd frontend && npm install && npm run dev        # in a second terminal
```

Open http://localhost:5173 and choose what you want to plan, or pick a template, then
Validate → Optimize → review the Gantt → Approve.

After `git pull`, re-run the `pip install` and `npm install` lines (new dependencies may have been added).
Your existing `backend/superplanner.db` is upgraded automatically on start, after writing a backup copy.

**Optional — user accounts:** start the backend with `$env:AUTH_MODE="accounts"` (PowerShell) or
`AUTH_MODE=accounts` (Linux/macOS) to get sign-up / sign-in, with each user seeing only their own plans.
PostgreSQL, separate workers and Docker Compose are described in `docs/DEPLOY.md`.

## Tests

```bash
cd backend && .venv/bin/pytest -q          # engine, API and integration tests
cd frontend && npm run build               # type-check + production build
cd frontend && npm run e2e                 # Playwright end-to-end (starts both servers itself)
```

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

Configuration: `DATABASE_URL` (SQLite by default; PostgreSQL supported), `PORT`, `HOST`,
`CORS_ORIGINS`, `MAX_BODY_BYTES`.

Not yet built (see `docs/ARCHITECTURE.md` §20): authentication/multi-tenancy, Celery/Redis workers,
Monte Carlo simulation, the financial-planning module, an LLM planning copilot, drag-to-reschedule.
