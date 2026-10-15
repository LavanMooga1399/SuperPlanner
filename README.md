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

Requirements: Python 3.13, Node 22.

```bash
# Backend (http://127.0.0.1:8000, API under /api/v1)
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run_api.sh

# Frontend (http://localhost:5173, proxies /api to the backend)
cd frontend
npm install
npm run dev
```

Open the UI, pick a template (Manufacturing, Exam preparation, Project, or Blank), then
Validate → Optimize → review the Gantt → Approve.

## Tests

```bash
cd backend && .venv/bin/pytest -q          # engine, API and integration tests
cd frontend && npm run build               # type-check + production build
cd frontend && npm run e2e                 # Playwright end-to-end (starts both servers itself)
```

## Repository layout

| Path | Contents |
|---|---|
| `backend/superplanner/engine` | Pure-Python core: model, preflight checks, graph/CPM, decoder, validator, explanations, solver selector |
| `backend/superplanner/engine/solvers` | Heuristic, CP-SAT and Genetic Algorithm solvers behind one interface |
| `backend/superplanner/templates` | Domain templates (manufacturing, exam prep, project, blank) |
| `backend/superplanner/api` | FastAPI service: plans, versions, background solver runs with SSE progress, schedules, approve/compare/export/replan |
| `frontend/` | React + TypeScript Planning Studio (Vite) |
| `docs/ARCHITECTURE.md` | Full design and API contract |
| `docs/PLAN.md` | Delivery plan and acceptance criteria |
| `docs/source/` | Original product blueprint text |
| `.claude/agents/` | Agent team roles used to build this (architect, team lead, backend, UI, tester) |

Configuration: `DATABASE_URL` (SQLite by default; PostgreSQL supported), `PORT`, `HOST`,
`CORS_ORIGINS`, `MAX_BODY_BYTES`.

Not yet built (see `docs/ARCHITECTURE.md` §20): authentication/multi-tenancy, Celery/Redis workers,
Monte Carlo simulation, the financial-planning module, an LLM planning copilot, drag-to-reschedule.
