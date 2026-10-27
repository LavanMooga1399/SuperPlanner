# SuperPlanner MVP - Delivery Plan

> **Historical note (PostgreSQL-only release):** "file-DB" below refers to the embedded file database of earlier
> releases. It was removed; SuperPlanner now runs on PostgreSQL only (see `docs/DEPLOY.md`, Changelog, and
> `docs/ARCHITECTURE.md` section 25). Statements about file-DB behaviour describe the past.

Owner: team-lead. Contract: `docs/ARCHITECTURE.md` (sections cited as "A.n"). If this plan and the
architecture disagree on behaviour, the architecture wins; on file ownership and ordering, this
plan wins. Ambiguities are resolved by the implementer and recorded in A.25 "Implementation notes".

## 0. Overview

| WP | Name | Owner role | Owns (only these paths) | Starts | Depends on |
|----|------|-----------|-------------------------|--------|------------|
| WP1 | Backend engine | backend-developer | `backend/superplanner/__init__.py`, `backend/superplanner/engine/**`, `backend/superplanner/templates/**`, `backend/tests/engine/**` | day 0 | contract only |
| WP2 | Backend API | backend-developer | `backend/superplanner/api/**` (incl. `api/db/**`), `backend/tests/api/**`, `backend/requirements.txt`, `backend/pyproject.toml`, `backend/run_api.sh` | after WP1 is accepted | WP1 public API (A.7.6) |
| WP3 | Frontend | ui-developer | `frontend/**` except `frontend/e2e/**` | day 0, parallel to WP1+WP2 | API contract (A.14, A.15, A.17) |
| WP4 | Testing | tester | `backend/tests/integration/**`, `frontend/e2e/**` | day 0 (writing), runs as WPs land | WP1 (engine-level checks), WP2 (API flows), WP3 (e2e) |

```
WP1 engine ──────────────► WP2 API ─────────────┐
WP3 frontend (against contract, all along) ─────┼─► WP4 final runs (integration + e2e) ─► LEAD review
WP4 test writing (against contract, all along) ─┘
```

Ownership rules:
- No file has two owners. `backend/superplanner/__init__.py` is WP1 because the engine imports
  `__version__` from it. `backend/superplanner/db/` is **not** created; persistence lives in
  `backend/superplanner/api/db/` (A.13).
- Nobody edits `docs/source/**`. Developers may append to A.25 only; LEAD owns A.23 and this file.
- Every Python dependency is already installed in `backend/.venv`. Adding one requires a change
  to this plan; WP2 then adds it to `requirements.txt`.
- `git commit`/`push` only when the user asks.

Global "done" gate (checked by LEAD before review):

```
cd backend && .venv/bin/pytest -q                         # all fast tests pass
cd frontend && npm run typecheck && npm run build         # exit 0
cd frontend && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test -c e2e/playwright.config.ts
```

---

## WP1 - Backend engine (backend-developer)

### Deliverables
- `superplanner/__init__.py` (`__version__ = "0.1.0"`).
- Engine modules of A.18: `model.py`, `timeutil.py`, `compiled.py`, `objectives.py`, `graph.py`,
  `preflight.py`, `validator.py`, `explain.py`, `decoder.py` (decode + left_shift),
  `solvers/{__init__,base,heuristic,cpsat,ga}.py`, `selector.py`, `pipeline.py`, and
  `engine/__init__.py` exporting exactly the A.7.6 public API plus `CompileError`, all public
  Pydantic models and `__version__`.
- Templates: `templates/{__init__,base,manufacturing,exam_prep,project,blank}.py` (A.12).
- Tests in `backend/tests/engine/` (subfolders `solvers/`, `templates/` allowed; own
  `conftest.py`; fixtures in `tests/engine/fixtures/*.json` in `ExportFile` format, at least:
  the A.3.11 example, a precedence-only network, a 10x5 flexible job shop, an infeasible
  problem (hard deadline impossible) and a calendar-heavy problem).

### Steps (in order)
1. **Contract stubs first (unblocks WP2/WP3/WP4 reading code):** `model.py` (all A.3 models with
   the A.3.0 layering), `solvers/base.py` (A.7.1-7.5, 7.7 models), `engine/__init__.py` with
   final signatures (bodies may raise `NotImplementedError`). Record the stub-complete moment in
   A.25.
2. `timeutil.py` (A.4: `to_minute`, `from_minute`, `expand_windows`, `fmt_minute`, duration
   formatting) and `compiled.py` (`compile_problem`, `CompileError`).
3. `graph.py` (Tarjan cycles, Kahn topo, CPM with all four dependency types) and `preflight.py`
   (every A.9.1 code, `PROVEN_INFEASIBLE_CODES`, terminology-based messages).
4. `objectives.py` (`PRESET_WEIGHTS`, `cost_of`, `compute_refs`, score, `rank_key`) and the
   **independent** `validator.py` (A.10; sweep-line capacity; all violation codes of A.7.5).
   Validator tests with hand-built placements are written and passing **before** step 5.
5. `decoder.py`: serial SGS (A.8.1, incl. `lock_conflicts`) and `left_shift` (A.8.2).
6. `solvers/heuristic.py` (five rules, CPM shortcut detection), then `solvers/cpsat.py` (A.8.4,
   start-domain calendars, hints, watchdog cancel), then `solvers/ga.py` (A.8.5) and the solver
   registry.
7. `selector.py` + `pipeline.py` (A.8.6, A.8.7: shortcut, baseline, refs, budget, fallback,
   final pick, left-shift, validation, probe, alternatives) and `explain.py` (A.11).
8. Templates (A.12) and their tests.
9. Import-boundary test and a performance smoke test; update A.25 with any interpretations.

### Acceptance criteria
Run from `backend/` unless noted. "Validated" means `validate()` reports zero hard violations.

| # | Criterion | Check |
|---|-----------|-------|
| 1.1 | Whole WP1 suite passes | `.venv/bin/python -m pytest --import-mode=importlib -q tests/engine` exits 0 |
| 1.2 | Public API importable with exact names | `.venv/bin/python -c "from superplanner.engine import preflight, analyze, optimize, validate_schedule, explain_schedule, CompileError, Problem, Placement, __version__; assert __version__=='0.1.0'"` exits 0 |
| 1.3 | Boundaries: engine imports no fastapi/sqlalchemy/api/templates; `validator.py` imports none of `decoder`, `graph`, `solvers` | a test in `tests/engine/test_engine_boundaries.py` parses imports with `ast` and passes; `grep -rE "fastapi|sqlalchemy|superplanner\.(api|templates)" superplanner/engine` prints nothing |
| 1.4 | Model layering (A.3.0) | tests: naive datetime -> `ValidationError`; milestone with duration 5 -> error; self-dependency and window `"10:00"-"09:00"` are **accepted** by the model and reported by `preflight` as `SELF_DEPENDENCY` / `INVALID_CALENDAR` |
| 1.5 | Every preflight code of A.9.1 fires | one parametrized test per code asserting code, severity and that the message contains the task/resource **name** and terminology word |
| 1.6 | Calendar expansion | tests: `+05:30` offset windows land on the right minutes; `22:00-24:00` + next-day `00:00-06:00` merge into one window; blocked interval subtraction; `weekly: null` + blocked |
| 1.7 | Validator catches every hard code | one test per A.7.5 code with a minimal hand-made schedule; touching intervals on a capacity-1 resource produce no violation; 3 overlapping tasks on capacity 2 produce exactly one `CAPACITY_EXCEEDED` with correct `from`/`to` |
| 1.8 | All solver output is validated | for each fixture x each strategy (`heuristic`, `cpsat`, `ga`, `hybrid`, `auto`): `optimize()` result with `feasibility=="feasible"` has `validate_schedule(...)` with zero hard violations (test asserts this independently of the result's own `violations`) |
| 1.9 | Honest status | infeasible fixture -> `feasibility=="infeasible"`, `termination_reason=="preflight_failed"`; a problem without preflight errors that CP-SAT proves infeasible (two tasks locked to overlapping times on one capacity-1 resource, strategy `cpsat`) -> `infeasible` with `cpsat` phase `termination_reason == "proven_infeasible"`; GA with `time_limit_seconds=1` on a hard instance never returns `infeasible` |
| 1.10 | CP-SAT optimality | on 20 random tiny instances (<= 5 tasks, 2 resources) CP-SAT's score equals a brute-force enumeration over orders and resource choices; `optimality_proven` true |
| 1.11 | Never worse than baseline | for every fixture and strategy, final `score <= ` baseline heuristic score of the same run (from `phases[0]`) |
| 1.12 | Resource-free shortcut | precedence-only fixture: `selection.used == ["cpm"]`, `optimality_proven == True`, makespan == CPM lower bound, for all five strategies |
| 1.13 | GA determinism and adaptation | same seed + `max_generations` stop -> identical placements twice; mutation rate never < 0.01 in emitted progress `extra` |
| 1.14 | Left-shift property | on 100 random schedules: no task's end increases, resources unchanged, valid input stays valid, score never increases |
| 1.15 | Cancel and budget | `cancel_event` set 0.5 s into a 30 s GA and CP-SAT run -> returns within 1.5 s with `status=="cancelled"`; any strategy with `time_limit_seconds=5` on the 10x5 fixture returns within 8 s |
| 1.16 | Selector rules | each row of the A.8.7 table produces the listed `used` and a non-empty reason sentence; CP-SAT `unknown` with >= 2 s left appends `ga` |
| 1.17 | Explanations | crafted schedules yield each `StartReason` code; the A.3.11 example gives `CALENDAR` for `J1-1` ("Saw 1") and `DEPENDENCY` naming "J1 Cutting" for `J1-2`; critical chain ordered start-to-end |
| 1.18 | Infeasibility probe | a problem whose hard deadline is missed only because of capacity yields a `diagnostics` string naming that task and its lateness |
| 1.19 | Templates | for each of `manufacturing`, `exam_prep`, `project`, `blank`: `build()` at defaults is deterministic (two builds equal), passes preflight with no errors, and (except `blank`) `optimize(strategy="auto", time_limit_seconds=10)` returns `feasible`; unknown param -> `ValueError` |
| 1.20 | Scale smoke | a generated 2000-task / 50-resource problem: `preflight` < 2 s, heuristic strategy completes within `time_limit + 3 s` and is validated (may be marked `slow`) |

---

## WP2 - Backend API (backend-developer, starts after WP1 is accepted)

### Deliverables
- `backend/pyproject.toml` (pytest config of A.18), `backend/requirements.txt` (pinned to the
  versions in `.venv`), `backend/run_api.sh` (executable).
- `superplanner/api/`: `main.py` (`create_app(settings)`, `app`, lifespan, CORS, error
  handlers), `config.py`, `errors.py`, `schemas.py`, `db/{__init__,models,session}.py`,
  `executor.py`, `services/{problem,run,schedule,replan}_service.py`,
  `routes/{health,templates,problems,solver_runs,schedules}.py`.
- Tests in `backend/tests/api/` using `TestClient` and a temp-file file-DB DB per test module.

### Steps (in order)
1. Packaging: `pyproject.toml`, `requirements.txt`, `run_api.sh`; confirm `.venv/bin/pytest -q`
   still runs WP1's tests unchanged.
2. `config.py`, `db/` (tables of A.13, PRAGMA listener, `create_all`), `errors.py` (error
   envelope, 422 mapping), `main.py` app factory; health endpoint.
3. Templates routes and problems CRUD with ETag/If-Match/412/428, export/import, audit events.
4. Validate endpoint (`engine.analyze`).
5. `executor.py` + `run_service.py`: snapshot, one-active-run lock, worker, progress throttle,
   event persistence, schedule creation (primary + alternatives via public engine API),
   cancel (queued and running), startup recovery.
6. SSE endpoint (A.15) incl. replay, keepalive, 204 for terminal runs, `?stream=false`.
7. Schedules: list/get, approve (check order, supersede, staleness), compare, CSV export.
8. Replan service (A.14.6) with rollback and derived snapshot.
9. API tests for every status code in A.14; record interpretations in A.25.

### Acceptance criteria

| # | Criterion | Check |
|---|-----------|-------|
| 2.1 | Full backend suite passes with the new config | `cd backend && .venv/bin/pytest -q` exits 0 (includes `tests/engine` and `tests/api`) |
| 2.2 | Server starts and is healthy | `cd backend && DATABASE_URL=<file-DB URL> ./run_api.sh &` then `curl -s localhost:8000/api/v1/health` returns `{"status":"ok","version":"0.1.0","ortools_version":"9.15.6755","database":"ok"}` |
| 2.3 | Requirements match the venv | `.venv/bin/pip install --dry-run -r requirements.txt` reports nothing to install |
| 2.4 | Error envelope | every non-2xx response in the tests has `{"error":{"code","message","details"}}`; a Problem with an unknown field -> 422 `VALIDATION_ERROR` with `details.errors[].loc` |
| 2.5 | Templates | `GET /templates` lists the 4 templates with parameters; instantiate -> 201, `ETag: "1"`, `Location`, `problem.id == id`; unknown id -> 404; bad parameter -> 422 |
| 2.6 | Optimistic concurrency | PUT without If-Match -> 428; stale If-Match -> 412 with `details.current_version`; `"3"`, `3`, `W/"3"` all accepted; success bumps `version` and `ETag`; body `problem.id` is overwritten |
| 2.7 | Drafts saveable | PUT of a document with a self-dependency and a dangling resource id -> 200; `POST /validate` then returns `ok:false` with `SELF_DEPENDENCY` and `UNKNOWN_RESOURCE` and `cpm:null` |
| 2.8 | Run lifecycle | POST run on a manufacturing template -> 202 with `run_id`; polling `GET /solver-runs/{id}` reaches `completed` within `time_limit + 5 s`; `primary_schedule_id` set; the stored `request` is fully defaulted; the schedule's placements re-validated by the test with `engine.validate_schedule` have zero hard violations |
| 2.9 | Run guards | run with preflight errors -> 422 `PREFLIGHT_FAILED` with `details.issues`; second run while one is active -> 409 `RUN_ALREADY_ACTIVE`; two concurrent POSTs from two threads -> exactly one 202 |
| 2.10 | Snapshot isolation | editing the problem (PUT) while a run is running does not change that run's `problem_version_id` document or result |
| 2.11 | Cancel | cancel queued run -> run `cancelled` and `run_cancelled` event; cancel a running 30 s GA run -> `cancelled` within 2 s with a candidate schedule if one was found; cancel terminal run -> 409 `RUN_NOT_ACTIVE` |
| 2.12 | SSE | stream yields `run_queued` (seq 1) ... terminal event, every frame has `id:` and `event:`; reconnect with `Last-Event-ID: 3` replays only seq > 3; request for a finished run with cursor at last seq -> 204; `?stream=false` returns all events as JSON; progress <= 2 per second per run |
| 2.13 | Approval | approve feasible candidate -> 200, `superseded_schedule_id: null`; approve a second -> first becomes `superseded`, response names it; at most one `approved` per problem (two concurrent approvals from two threads leave exactly one); re-approve -> idempotent 200; approve superseded -> 409 `SUPERSEDED`; approve `unknown` schedule -> 422 `NOT_FEASIBLE` |
| 2.14 | Stale approval | after a PUT that makes the schedule invalid (add a blocked interval on a used resource over a placed task) -> 409 `STALE_SCHEDULE` with `details.violations`; after a PUT that keeps it valid -> 200 with `approved_problem_version` = new version; after a PUT that adds a preflight error -> 409 with `details.issues` |
| 2.15 | Compare and CSV | compare two schedules of one problem returns deltas `b - a` with the A.14.6 shape; schedules of different problems -> 422 `DIFFERENT_PROBLEMS`; CSV has the exact header row of A.14.6 and one row per task |
| 2.16 | Replan | replan with a cutoff after the first operation: problem `version` +1 only if `changes` non-empty; tasks starting before the cutoff keep start and resources in the new primary schedule; all others start >= cutoff; the editable document contains no `locked` added by replan; stale `expected_problem_version` -> 412 and no version change |
| 2.17 | Recovery | a run row left `running` in the DB becomes `failed` with "Server restarted before the run finished." when a new app starts on that DB |
| 2.18 | Delete | delete with an active run -> 409; otherwise 204 and its runs/schedules are gone (FK cascade works on file-DB) |

---

## WP3 - Frontend (ui-developer, parallel to WP1 + WP2)

### Deliverables
- `frontend/` per A.17: `package.json` (scripts of A.17, `@playwright/test` pinned `1.56.1`),
  `tsconfig.json` (`include: ["src"]`), `vite.config.ts` (dev + preview proxy), `index.html`,
  all files of A.17.2 including `api/types.ts`, `api/client.ts`, `api/sse.ts`,
  `api/contractExamples.ts`, `ReplanDialog.tsx`, `RunHistory.tsx`.
- No files under `frontend/e2e/`.

### Steps (in order)
1. Scaffold Vite + React 18 + TS + react-router 6; theme CSS variables (light/dark, one accent);
   `npm install` succeeds.
2. `api/types.ts` transcribed from A.3, A.7, A.9, A.11, A.14, A.15 and
   `api/contractExamples.ts` containing the document's JSON examples typed as those types
   (this is the compile-time contract check).
3. `api/client.ts` (typed wrappers for every A.14 endpoint, `ApiError`, If-Match handling),
   `api/sse.ts` (named-event listeners, terminal close, 3-error polling fallback),
   `lib/time.ts`, `lib/terms.ts`.
4. Home (plan list, template cards with parameter forms incl. `string_list`, import JSON) and
   `PlanWorkspace` with `PlanContext` (draft, autosave 1.5 s, conflict banner).
5. Tasks, Resources (with `CalendarEditor`) and Dependencies tabs (`DependencyGraph` SVG with
   critical path and cycle highlighting); generated ids/names for new rows.
6. Validate tab (`IssueList` with links to offending rows, CPM summary).
7. Optimize tab: `GoalPresetPicker`, hidden `ExpertSettings`, `RunProgress` (live via SSE,
   cancel), `RunHistory`.
8. Schedule tab: `KpiCards`, `Gantt` (tasks/resources modes, zoom, arrows, deadlines, shading,
   critical chain, virtualization > 300 rows), `TaskDrawer` (reasons, "Lock at this time"),
   `ViolationsPanel`, candidate/approved banner, approve with confirmation, CSV export,
   `ReplanDialog`.
9. Compare tab (`ScheduleComparison`). Accessibility pass (labels, focus, text+icon status,
   hatched late bars) and `data-testid` hooks of A.17.2.
10. Once WP2 is available: run the app against the real backend and fix contract mismatches
    (record any in A.25).

### Acceptance criteria

| # | Criterion | Check |
|---|-----------|-------|
| 3.1 | Type check and build | `cd frontend && npm install && npm run typecheck && npm run build` exits 0 |
| 3.2 | Contract types | `api/contractExamples.ts` includes the A.3.11 Problem, a ProblemRecord, SolverRun, Schedule, Comparison, ValidateReport and one SSE event of each type, each annotated with its type from `types.ts` (no `any`/casts); covered by 3.1 |
| 3.3 | Dependencies are minimal | `package.json` runtime deps are exactly `react`, `react-dom`, `react-router-dom`; `@playwright/test` is `1.56.1` |
| 3.4 | Proxy works | with the backend on :8000, `npm run dev` then `curl -s localhost:5173/api/v1/health` returns the health JSON; same on :4173 after `npm run preview` |
| 3.5 | Guided flow observable in the browser | create a plan from the manufacturing template; labels read "Operations"/"Machines"; edit a duration and see the save state go "saving" -> "saved"; Validate shows no errors; Optimize with default "Balanced" shows live phase progress and ends with a link to the schedule; Gantt shows bars; approving asks for confirmation and the banner changes to "Approved" |
| 3.6 | Honest status in UI | an `unknown`/`infeasible` schedule shows a text+icon badge ("Unknown"/"Not feasible"), opens the violations panel, and the Approve button is disabled with the reason |
| 3.7 | Conflict handling | changing the plan in a second tab and then saving in the first shows the "changed elsewhere" banner (412), not a silent overwrite |
| 3.8 | Expert settings hidden | strategy, seed and GA parameters are only visible after toggling "Expert settings"; the toggle state survives reload (localStorage) |
| 3.9 | Accessibility basics | every input has a label; Gantt bars are reachable with Tab and Enter opens the drawer; status badges contain text; dark mode toggles via the theme switch |
| 3.10 | Test hooks | every `data-testid` listed in A.17.2 exists in the rendered DOM of its screen (verified by WP4 e2e) |

---

## WP4 - Testing (tester)

### Deliverables
- `backend/tests/integration/`: own `conftest.py` (live in-process app with temp DB via
  `create_app`, plus helpers), `fixtures/*.json`, and test modules:
  `test_int_flow.py`, `test_int_property.py`, `test_int_replan.py`, `test_int_concurrency.py`,
  `test_int_benchmarks.py` (`@pytest.mark.slow`).
- `frontend/e2e/`: `playwright.config.ts` (Chromium only, `webServer` entries that start the
  backend via `backend/run_api.sh` with a temp `DATABASE_URL` and the frontend via
  `npm run preview` or `npm run dev`, `reuseExistingServer: false`), `tsconfig.json`, specs.
- A defect report in the final message (not a file) for every failure: file:line if known,
  steps, expected vs actual, severity, owner WP.

### Steps (in order)
1. Write tests against the contract immediately (they may be `xfail(strict=False)` /
   `test.fixme` until the corresponding WP lands; remove those markers once it has).
2. Engine-level property tests (after WP1): 200 random small problems (stdlib `random`, seeded),
   all strategies, independent `validate_schedule` on every result.
3. API flow tests (after WP2): the full journey and replan/concurrency scenarios over HTTP.
4. Benchmarks (A.19 list) recorded to stdout: feasibility rate, time to first feasible,
   objective vs CP-SAT, several seeds for GA.
5. Playwright specs (after WP3 + WP2): the A.19 E2E journey.
6. Run everything, report defects to owners, re-run after fixes.

### Acceptance criteria

| # | Criterion | Check |
|---|-----------|-------|
| 4.1 | Integration suite passes | `cd backend && .venv/bin/pytest -q tests/integration` exits 0 with no remaining `xfail` markers |
| 4.2 | End-to-end API journey | one test does: instantiate template -> validate -> create run -> read SSE to terminal event -> get schedule -> approve -> replan with a duration change and cutoff -> run completes -> compare old vs new -> CSV download; every step asserts status code and key fields |
| 4.3 | Property test | 200 seeded random problems x strategies `heuristic`, `cpsat`, `ga`, `auto`: every `feasible` result has zero hard violations under an independent `validate_schedule` call; CP-SAT score <= heuristic score within the same run; no result claims `infeasible` unless preflight or CP-SAT proved it |
| 4.4 | Replan protection | frozen tasks keep start and resources; no other task starts before the cutoff; the approved schedule is unchanged until the new candidate is approved |
| 4.5 | Concurrency/recovery | two concurrent run creations -> one 202, one 409; two concurrent approvals -> exactly one approved; a killed server (process stopped mid-run) restarted on the same DB marks the run `failed` |
| 4.6 | Benchmarks run | `.venv/bin/pytest -q -m slow tests/integration/test_int_benchmarks.py` exits 0 and prints a table of results per instance and strategy |
| 4.7 | E2E | `cd frontend && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test -c e2e/playwright.config.ts` exits 0, covering: create from template, edit a task, validate shows a cycle (create one via the UI), optimize with live progress, Gantt renders bars, approve, compare two schedules, CSV download |
| 4.8 | Hygiene | servers started by tests are stopped (no process listening on :8000/:5173/:4173 afterwards: `ss -ltn` check); no `playwright install` invoked; temp DBs live outside the repo |
| 4.9 | Defect reporting | every failure is reported with steps, expected vs actual, severity and owner WP; no product code edited by WP4 |

---

## Review gate (LEAD, after WP1-WP4)

Code review per `.claude/agents/team-lead.md`: correctness first (scheduling semantics,
validator independence, nothing invalid reported feasible, run/cancel races, API/UI contract
mismatches), then security, then maintainability. Findings cite file:line and an owner WP.
