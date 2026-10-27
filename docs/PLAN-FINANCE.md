# SuperPlanner Finance - Delivery Plan

> **Historical note (PostgreSQL-only release):** "file-DB" below refers to the embedded file database of earlier
> releases. It was removed; SuperPlanner now runs on PostgreSQL only (see `docs/DEPLOY.md`, Changelog, and
> `docs/ARCHITECTURE.md` section 25). Statements about file-DB behaviour describe the past.

Owner: team-lead. Contract: `docs/FINANCE.md` (cited as "F.n"; shared conventions "A.n" from
`docs/ARCHITECTURE.md`). If this plan and F disagree on behaviour, F wins; on file ownership and
order, this plan wins. Interpretations go to F.24.3 (date + owner). Review fixes are tagged `[Rn]` in F
and listed in F.25.

Scope: Finance v0.1 = goal-based, cash-flow-aware planning (F.1). Educational decision support only:
asset classes, user-editable assumptions, no market data, no LLM, disclaimer everywhere (F.21).

## 0. Overview

| WP | Name | Owner role | Owns (only these paths) | Starts | Depends on |
|----|------|-----------|-------------------------|--------|------------|
| F1 | Finance engine | backend-developer | `backend/superplanner/finance/**`, `backend/tests/finance/**`, `backend/requirements.txt` + `backend/pyproject.toml` (numpy pin only) | day 0 | F only |
| F2 | Finance API | backend-developer | `backend/superplanner/api/finance/**`, `backend/tests/api_finance/**`, the two-line edits in `backend/superplanner/api/main.py` and `backend/superplanner/api/context.py` (F.22) | after F1 is accepted | F1 public API (F.2.1) |
| F3 | Finance UI | ui-developer | `frontend/src/finance/**`, the edits in `frontend/src/main.tsx` and `frontend/src/App.tsx` (F.20.1, F.22), `README.md` (Finance section) | day 0, parallel to F1+F2 | API contract (F.13, F.14, F.18, F.19) |
| F4 | Finance testing | tester | `frontend/e2e/finance.spec.ts`, `frontend/e2e/finance-helpers.ts`, `backend/tests/integration/test_int_finance_*.py`, `backend/tests/integration/fin_int_helpers.py` | day 0 (writing), runs as WPs land | F1 (property), F2 (API flows), F3 (e2e) |

```
F1 engine ─────────────► F2 API ───────────────┐
F3 UI (against contract, all along) ───────────┼─► F4 final runs (integration + e2e) ─► LEAD review
F4 test writing (against contract, all along) ─┘
```

Ownership rules:
- No file has two owners. F1 and F2 are the same role but run sequentially, so they never edit at the
  same time; F2 never edits `superplanner/finance/**` (it asks F1, who records the change in F.24.3).
- Existing files that may change are exactly: `backend/superplanner/api/main.py`,
  `backend/superplanner/api/context.py` (F2), `backend/requirements.txt`, `backend/pyproject.toml` (F1),
  `frontend/src/main.tsx`, `frontend/src/App.tsx`, `README.md` (F3). Nothing else that exists today is
  edited: not `superplanner/engine/**`, `superplanner/templates/**`, `superplanner/api/{routes,services,db}/**`,
  `frontend/src/{api,components,pages,state,lib,styles}/**`, any existing test or e2e file, or `docs/source/**`.
- `superplanner/finance` never imports fastapi/starlette/sqlalchemy/`superplanner.api`; only
  `finance/bridge.py` imports `superplanner.engine.model` (F.2).
- `backend/tests/integration/conftest.py` already exists and is not edited; it already puts its folder
  on `sys.path`, so F4 integration files import their helper `fin_int_helpers.py` from there and reuse the
  existing fixtures read-only.
- No new npm dependency; the only new Python dependency is the `numpy==2.5.4` pin (already installed).
- Developers append to F.24.3 only; LEAD owns F.25 and this file. No `git commit`/`push` unless the user asks.

## 1. Regression gate (all WPs, checked by LEAD before review)

Baseline today: **551** backend tests collected, **23** Playwright tests in 7 files.

| # | Gate | Check |
|---|------|-------|
| G1 | Existing backend tests unchanged and green | `cd backend && .venv/bin/pytest -q tests/engine tests/api tests/integration --ignore-glob='*finance*'` -> 551 passed (count unchanged; slow-marked tests per A.18) |
| G2 | Whole backend suite green | `cd backend && .venv/bin/pytest -q` exits 0 |
| G3 | No existing test file modified | `git status --porcelain backend/tests frontend/e2e` lists only new paths (`tests/finance/`, `tests/api_finance/`, `tests/integration/test_int_finance_*`, `fin_int_helpers.py`, `e2e/finance*.ts`) |
| G4 | Only the allowed existing files changed | `git diff --name-only` is a subset of the 7 files listed in section 0 |
| G5 | Frontend type-checks and builds | `cd frontend && npm run typecheck && npm run build` exits 0 |
| G6 | Existing Playwright tests green | `cd frontend && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test -c e2e/playwright.config.ts contract editors explore journey offset regressions templates` -> 23 passed |
| G7 | Full Playwright run green | same command without file filters -> 23 + finance tests passed |
| G8 | Scheduling API untouched | `GET /api/v1/problems`, `/templates`, `/health` responses unchanged in shape (covered by G1); `/openapi.json` still lists every existing path |

---

## F1 - Finance engine (backend-developer)

### Deliverables
- `backend/superplanner/finance/`: `__init__.py` (exactly the F.2.1 names, `__all__` set),
  `model.py`, `defaults.py`, `timegrid.py`, `returns.py`, `preflight.py`, `cashflow.py`,
  `optimizer.py`, `simulate.py`, `validator.py`, `pipeline.py`, `whatif.py`, `compare.py`,
  `templates.py`, `export.py`, `bridge.py`, `advisor/{__init__,explain,fixes,messages}.py`.
- `numpy==2.5.4` added to `backend/requirements.txt` and `backend/pyproject.toml` dependencies.
- Tests in `backend/tests/finance/` (`conftest.py`, `fin_helpers.py` incl. the compliance denylist,
  `fixtures/*.finance.json`, files `test_fin_*.py`).

### Steps (in order)
1. **Contract stubs first** (unblocks F2/F3/F4): `model.py` with every model of F.4, F.6, F.7 (projection
   and summary), F.10.1, F.11, F.12.1, F.13, F.14 (incl. `holdings_assignment.source`, `unallocated`
   series), `__init__.py` with final signatures (bodies may raise `NotImplementedError`),
   `DISCLAIMER`/`DISCLAIMER_VERSION`. Record "stubs complete" in F.24.3.
2. `timegrid.py` (month index, occurrence rule with clamping [R2], blocks truncated at `D_g`, horizon with
   `max D_g + 1` [R1]) and `defaults.py` (F.5).
3. `preflight.py`: every F.6 code (no `whatif_` rule there [R12]); PSD check with numpy.
4. `cashflow.py` (F.7, EF target over active items [R3], EF waterfall, `t_E`, holdings split into EF /
   buffer / pool [R4]) and `returns.py` (real returns, cautious returns, annuity factors).
5. **Independent `validator.py`** (F.11, tolerances incl. `tol_g`, cap allowance [R8], cash start with
   `sold_to_cash` rows [R5]). Validator tests on hand-built results written and passing **before** step 6.
6. `optimizer.py` (F.8: variables incl. `w_h` and sell-only classes, constraints 1-12, tiers T0-T5 with
   tolerance and numeric fallback [R9], MILP mode with the corrected big-M, `InterruptSolve` cancel
   watcher [R11], flooring/merging post-processing [R10]).
7. `simulate.py` (F.9: seeded draw order, correlated lognormal returns, inflation shocks, interruption,
   policy execution, per-month quantiles [R19], unallocated buy-and-hold, deterministic scenarios).
8. `pipeline.py` (F.10: stages, progress callback, calibration, ordered feasibility rule, cancellation).
9. `advisor/` (F.12: message catalog, reason codes, binding constraints, fix search with sibling bounds
   and exact what-if payloads [R13]) and `whatif.py` / `compare.py` (F.13 incl. `GoalOverride.risk_tolerance`,
   income drop excluded from the EF target).
10. `templates.py` (F.15), `export.py` (F.16.2 with formula-injection rule [R18]), `bridge.py` (F.16.1 with
    index ids, truncation, 7-day calendar [R16]).
11. Boundary test, compliance tests, property test, performance smoke; F.24.3 notes.

### Acceptance criteria
Run from `backend/`. "Clean" = `validate_result(plan, result)` returns no `hard` violation.

| # | Criterion | Check |
|---|-----------|-------|
| 1.1 | Whole F1 suite passes | `.venv/bin/pytest -q tests/finance` exits 0 |
| 1.2 | Public API exact | `.venv/bin/python -c "import superplanner.finance as f; [getattr(f,n) for n in ['default_plan','default_assumptions','preflight','project_cashflow','summarize_cashflow','run_plan','validate_result','apply_what_if','compare_results','contributions_csv','to_planner_problem','TEMPLATES','get_template','DISCLAIMER','DISCLAIMER_VERSION','FinancePreflightError','FinanceCancelled','FinancePlan','FinanceResult']]; assert f.__version__=='fin-0.1.0'"` exits 0 |
| 1.3 | Boundaries | `test_fin_boundaries.py` (ast, like `tests/engine/test_engine_boundaries.py`): no fastapi/starlette/sqlalchemy/`superplanner.api` import in `finance/**`; only `bridge.py` imports `superplanner.engine`, and only `.model`; `validator.py` imports only `finance.{model,defaults,timegrid,cashflow,returns}` + stdlib/pydantic/numpy |
| 1.4 | Model layering | out-of-range values, bad month strings, extra fields -> `ValidationError`; a plan with only `name` validates; every list may be empty; `FinancePlan` JSON round-trips unchanged |
| 1.5 | Every preflight code fires | one parametrized test per F.6 code: code, severity, message contains the item **name**; a derived plan containing `whatif_extra` passes preflight |
| 1.6 | Cash-flow arithmetic | hand-calculated fixtures: growth step only on anniversaries; inflation-linked vs fixed nominal; quarterly/yearly/once occurrence; item starting before plan start clamped; amortization payoff month; EF target counts only items active at t=0; `t_E`; holdings split EF / buffer / pool sums to the holdings total |
| 1.7 | Validator catches every code | one test per F.11 code with a minimal hand-made result; values exactly at tolerance pass, just beyond fail |
| 1.8 | Every optimizer/pipeline output is clean | every test in `test_fin_optimizer*.py` and `test_fin_pipeline*.py` asserts no hard violations independently of `result.violations` |
| 1.9 | LP semantics | single goal, one class, zero vol: level amount == `TR / Phi(n)` within 0.1 %; must beats nice when cash is short; minimax splits shortfall between two equal must goals within 1 %; should/nice contribute nothing before `t_E` and do contribute in a block split at `t_E`; lock-in class never used when it would mature after the goal; glide cap binds and a rebalance sells risky classes; global equity cap respected; locked holding never sold; locked risky earmark in the final block -> still solves, clean; earmark in a non-allowed class is sold, never bought |
| 1.10 | Honest infeasibility | negative surplus with no holdings -> `feasibility == "infeasible"`, T0 deficit equals the zero-contribution deficit within 1.0; same plan plus an unlocked equity holding large enough -> `feasible` with a `sold_to_cash` row |
| 1.11 | Published lines are exact | all `monthly_amount_real` have <= 2 decimals and are <= the LP amount; recomputing plan-basis values from the lines equals `planned_value_real` within 0.01; no `BUCKET_MISMATCH` on any template |
| 1.12 | MILP mode | a class with `min_monthly_contribution = 5000`: every contribution in that class is 0 or >= 5000; `diagnostics.solver == "SCIP"`; > 2000 binaries -> `MIN_CONTRIBUTION_IGNORED` and GLOP |
| 1.13 | Monte Carlo | same seed -> identical result JSON; zero volatility + zero inflation vol + interruptions off -> success probability 0 or 1 and p50 == central scenario within 0.1 %; doubling contributions never lowers success probability; sample correlation of two classes with rho 0.5 within 0.03 at 20 000 draws; interruption on lowers probability; `n_paths=10000`, `T=600` completes with peak RSS increase < 300 MB |
| 1.14 | Calibration | a goal below its minimum probability after round 0 gets a larger `planning_z` and a probability that is not lower; rounds stop early when nothing changes; must-tier shortfall never grows by > 1.0 |
| 1.15 | Cancel | `cancel_event` set 0.3 s into a run of the size-cap plan (also while an LP solve is running) -> `FinanceCancelled` within 1 s |
| 1.16 | Explanations and fixes | each F.12.2 reason code on a crafted plan; every generated sentence comes from `advisor/messages.py`; for a single short goal in its tier, re-running on `apply_what_if(plan, fix.what_if)` (`calibration_rounds=0`) gives shortfall `<= tol_g` for `INCREASE_SAVINGS` and `DELAY_GOAL`; `INCREASE_RISK` payload is a goal override; exactly one `smallest` per goal with fixes |
| 1.17 | What-if / compare | `apply_what_if` is pure (input unchanged) and deterministic; unknown goal id -> `ValueError`; income drop does not change `ef_target`; `compare_results` deltas are `b - a`, goals are the union ordered b then a |
| 1.18 | Templates | `young_professional`, `family`, `near_retirement`, `blank`: two builds equal; preflight has no errors; all but `blank` run `feasible` and clean at defaults; unknown parameter -> `ValueError` |
| 1.19 | CSV | first line `# ` + `DISCLAIMER`; header exactly F.16.2; rows sorted as specified; a goal named `=SUM(A1)` appears as `'=SUM(A1)` |
| 1.20 | Bridge | for each template result: the problem passes `superplanner.engine.preflight` with no errors, `horizon_days <= 366`, every task id matches `^[A-Za-z0-9_.:\-]{1,64}$` even with 64-char goal and class ids, every name <= 200 chars, description contains `DISCLAIMER` |
| 1.21 | Compliance | denylist (from `fin_helpers.py`) finds nothing in `defaults.py`, `templates.py`, `advisor/messages.py` except the allow-listed `PPF-like`; no forbidden word (F.21 rule 4) in any generated text of any template run; every `FinanceResult` has the exact `DISCLAIMER` |
| 1.22 | Property | 100 random small plans (stdlib `random`, fixed seeds): `run_plan` returns clean results, or `infeasible` with T0 deficit > 1.0; never an exception |
| 1.23 | Performance | young-professional template, 2000 paths, fixes on: `run_plan` < 5 s; typical plan (5 goals, 6 classes, 30 years) optimizer tiers < 1 s; size-cap plan solves < 10 s (may be marked `slow`) |
| 1.24 | Regression | G1, G2, G3 hold |

---

## F2 - Finance API (backend-developer, starts after F1 is accepted)

### Deliverables
- `backend/superplanner/api/finance/`: `__init__.py`, `router.py`, `schemas.py`, `service.py`,
  `run_service.py`, `db_models.py`, `planner_link.py`.
- Edits: `api/main.py` (import and include `finance_router.router` with `API_PREFIX`), `api/context.py`
  (import `.finance.db_models` before `create_all()`, call `finance_run_service.recover_interrupted_runs`
  after the existing recovery).
- Tests in `backend/tests/api_finance/` (`conftest.py`, `apifin_helpers.py` with its own `make_app`,
  files `test_apifin_*.py`), temp-file file-DB DB per test.

### Steps (in order)
1. `db_models.py` (five `finance_*` tables on the shared `Base`, FKs `CASCADE`, indexes of F.17) and the
   `context.py` edit; confirm the existing suite still passes (G1).
2. `schemas.py` (request/response models of F.18.1/F.18.2, utc_offset pattern reused from the existing
   schemas) and `service.py`: plans CRUD with If-Match (reuse `problem_service.parse_if_match`,
   `canonical_hash`, `slugify`, `audit`), start-month filling, `whatif_` id rejection [R12], export/import,
   templates, defaults, preview, validate.
3. `run_service.py`: snapshots, one active run per plan, run creation (preflight 422), what-if with
   `replace_active` and `base_result_id` [R14], worker on the shared `ctx.executor`, progress writer
   (2/s throttle, flush before `stage_completed`), final transaction re-checking `cancel_requested` [R11],
   cancel, startup recovery.
4. `router.py`: every F.18.2 endpoint, fixed paths before parameterized ones, SSE identical to A.15 (own
   cursor/frame helpers; do not import private names from `api/routes/solver_runs.py`), CSV and export
   headers; `main.py` edit.
5. `planner_link.py`: send-to-planner via `finance.to_planner_problem` + `problem_service.create_problem`
   outside any finance write session, audit afterwards.
6. Tests; F.24.3 notes.

### Acceptance criteria
Run from `backend/`.

| # | Criterion | Check |
|---|-----------|-------|
| 2.1 | Whole F2 suite passes | `.venv/bin/pytest -q tests/api_finance` exits 0 |
| 2.2 | Every endpoint and status of F.18.2 | one test per row and listed error (404, 409, 412, 422, 428); error bodies use the A.14 envelope |
| 2.3 | Versioning | PUT without If-Match -> 428; stale -> 412 with `details.current_version`; `"3"`, `3`, `W/"3"` accepted; ETag header on GET/POST/PUT |
| 2.4 | Drafts and ids | POST with only `name` -> 201 with `start_month` = current UTC month; item id `whatif_x` on POST/PUT/import/instantiate -> 422 `VALIDATION_ERROR` with the item path in `loc` |
| 2.5 | Run lifecycle | POST run -> 202; events replay `run_queued, run_started, stage_started..., run_completed` with increasing `seq`; `GET /finance/runs/{id}` ends `completed` with `result_id`; a second POST while active -> 409 `RUN_ALREADY_ACTIVE` with `details.run_id`; plan with preflight errors -> 422 `PREFLIGHT_FAILED` with `details.issues` |
| 2.6 | SSE | `Last-Event-ID: 2` and `?after=2` resume after seq 2; finished run with nothing new -> 204; `?stream=false` returns `{"items"}`; `progress` events <= 2/s |
| 2.7 | Cancel and races | cancel queued -> `cancelled` immediately with `run_cancelled`; cancel running -> terminal `cancelled` and **no** row in `finance_results`; a test that sets `cancel_requested` after `run_plan` returned but before the final write (monkeypatched hook) still ends `cancelled` without a result; deleting a plan while a cancel-requested run executes leaves no orphan rows and no worker error |
| 2.8 | What-if | `replace_active: true` cancels the active what-if run and queues the new one; an active baseline -> 409; derived plan from `base_result_id` snapshot (verified by editing the plan between baseline and what-if: the what-if result's `plan` equals snapshot + changes, not current + changes); the stored plan document is unchanged |
| 2.9 | Results and compare | list by `kind`; `GET /results/{id}` has `result` + `plan`; compare returns F.13 shape; `/results/compare` is not shadowed by `/results/{rid}` |
| 2.10 | CSV and export | `text/csv; charset=utf-8`, `Content-Disposition` attachment with slug; first line is the disclaimer; export -> import round-trip creates a new id with an equal document |
| 2.11 | Send to planner | 201; `GET /api/v1/problems/{problem_id}` exists; `POST /api/v1/problems/{id}/validate` reports no errors; `Location` header; non-feasible result -> 422 `NOT_FEASIBLE`; audit row `finance_result.sent_to_planner` |
| 2.12 | Persistence | snapshot reused for identical `(plan_id, kind, hash, base_version)`; what-if snapshots never reused; startup recovery marks `queued`/`running` finance runs `failed` with the A.16 message and a `run_failed` event; audit details contain no money amounts or names |
| 2.13 | Defaults and templates | `/finance/defaults` has `plan`, `disclaimer`, `disclaimer_version`, `limits`; `/finance/templates` lists 4 templates; instantiate each -> 201, run -> `feasible` |
| 2.14 | Regression | G1, G2, G3, G4, G8 hold (`/openapi.json` contains all pre-existing paths plus `/api/v1/finance/...`) |

---

## F3 - Finance UI (ui-developer, parallel to F1+F2)

Works against the contract: `finance/api/types.ts` and `finance/api/contractExamples.ts` are written
first from F.4-F.19; once F2 lands, the UI is checked against the live API (dev server + backend).

### Deliverables
- `frontend/src/finance/**` per F.20.2 (routes, css, api client/types/sse/contract examples, state,
  lib, pages, wizard, components, charts).
- Edits: `frontend/src/main.tsx` (spread `financeRoutes` into the `App` children before `*`),
  `frontend/src/App.tsx` (`<nav aria-label="Main">`, active rules of F.20.1), `README.md` (Finance section).

### Steps (in order)
1. `api/types.ts`, `api/contractExamples.ts` (typed examples of F.14, F.18, F.19), `api/client.ts`
   (local `finRequest` importing only exported names from `src/api/client.ts` [R21]), `api/sse.ts`.
2. `routes.tsx`, `finance.css` (palette vars for light and `:root[data-theme="dark"]`), `main.tsx` and
   `App.tsx` edits, `DisclaimerBanner` + first-visit dialog on every finance route.
3. `state/FinancePlanContext.tsx` (A.17.3 rules, single-flight saves [R23]), `lib/{money,months,ids}.ts`.
4. `FinanceHome` (plan list, template cards with parameters, start from scratch, import).
5. Wizard: `Stepper`, seven steps with the labels of F.20.3, help text, defaults, live preview of
   "You can invest about ₹X/month", horizon input, stale-start notice, review with linked issues.
6. Results: header, KPIs, goal cards, contribution table (real/nominal toggle), charts
   (`StackedAreaChart` with band, `LineChart` glide, `CashflowChart`), explanation panel, fix list,
   result history, CSV link, send-to-planner dialog, live run progress.
7. What-if page (debounced sliders, `base_result_id`, follow only the latest run id) and compare page.
8. Accessibility pass (chart `role="img"` + hidden tables, keyboard tooltips, status text+icon), dark
   mode pass, README section.

### Acceptance criteria
Run from `frontend/` unless noted.

| # | Criterion | Check |
|---|-----------|-------|
| 3.1 | Builds | `npm run typecheck && npm run build` exit 0; `contractExamples.ts` compiles against `types.ts` |
| 3.2 | No new dependencies, no edits outside ownership | `git diff --name-only frontend` shows only `src/main.tsx`, `src/App.tsx` among existing files; `package.json` unchanged |
| 3.3 | Contract fidelity | every endpoint of F.18.2 has a typed wrapper in `finance/api/client.ts`; field names match F.14/F.18 (checked by LEAD against a live response from F2: `curl` a result and type-check it by pasting into a scratch `satisfies FinanceResult`) |
| 3.4 | Navigation | top bar shows "Scheduling" and "Finance"; exactly one has `aria-current="page"` on `/`, `/plans/x/tasks` (Scheduling) and `/finance/...` (Finance); unknown `/finance/foo/bar/baz` shows NotFound |
| 3.5 | Disclaimer | exact F.21 text visible (`disclaimer-banner`) on every finance route; first-visit dialog on any finance route, stored in `sp.fin.disclaimerAck` |
| 3.6 | Wizard | seven steps with the labels Profile, Income & expenses, Debts, Savings & holdings, Goals, Risk & assumptions, Review; each has help text and "Skip - use defaults"; Next never blocks on warnings; preview figure updates within ~1 s of an income change; horizon field present; review disables "Build my plan" while preflight errors exist and links each issue to its step |
| 3.7 | Saving | edits autosave after 1.5 s; fast Next clicks during an autosave produce no 412 banner (single-flight); a real 412 (edit in another tab) shows the conflict banner with reload |
| 3.8 | Results | goal cards show estimated chance (text + bar), status pill with text and icon, p10-p90, monthly now, start/stop; corpus chart stacks classes + EF + cash buffer + unallocated with the p10-p90 band; glide and cash-flow charts render; contribution table toggles today's money / expected future |
| 3.9 | What-if | moving the savings slider triggers one run after 800 ms; moving it 3 times quickly shows only the last run's result; delta table vs baseline renders; "Apply to my plan" saves ordinary ids (no `whatif_` in the PUT body) |
| 3.10 | Compare, export, send | compare page shows the F.13 table for `?a=&b=`; CSV link downloads; send-to-planner dialog creates a plan and links to `/plans/<id>/tasks` |
| 3.11 | Dark mode and a11y | all charts readable in dark mode (palette vars only, no hard-coded colors); charts have `role="img"` + `aria-label` + hidden data table; every `data-testid` of F.20.6 present |
| 3.12 | Compliance | no product/fund/ticker names in `frontend/src/finance/**` (same denylist as 1.21, checked by F4); probabilities labelled "estimated chance"; assumptions labelled "Your assumption" vs "Calculated" |
| 3.13 | Regression | G5, G6 hold; existing pages look and behave unchanged |

---

## F4 - Finance testing (tester)

### Deliverables
- `frontend/e2e/finance.spec.ts` and `frontend/e2e/finance-helpers.ts` (disclaimer ack, template
  instantiate via API, wait for run).
- Optional `backend/tests/integration/test_int_finance_*.py` + `fin_int_helpers.py`: API-level property
  and benchmark tests across F1+F2.
- A short findings list returned to LEAD (no report files).

### Steps
1. Day 0: write e2e and integration tests against F (testids F.20.6, endpoints F.18.2); mark tests that
   need unfinished WPs with `test.fixme` / `pytest.skip` reasons that name the WP.
2. When F1 lands: run integration property tests through the engine (100 random plans).
3. When F2 lands: API flows (template -> run -> result -> what-if -> compare -> CSV -> send to planner).
4. When F3 lands: e2e journeys; remove `fixme`s; run G1-G7.
5. Report defects to the owning WP with file:line and a reproduction.

### Acceptance criteria

| # | Criterion | Check |
|---|-----------|-------|
| 4.1 | Finance e2e journey | `cd frontend && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test -c e2e/playwright.config.ts finance` passes: Finance nav -> dismiss disclaimer -> template `young_professional` -> Next through all 7 steps -> Build my plan -> live progress (`fin-run-progress`) -> goal cards (`goal-card-car`, `goal-card-retirement`) with success text -> `corpus-chart`, `glide-chart`, `cashflow-chart`, `contribution-table`, `fin-explanations` visible |
| 4.2 | What-if and compare e2e | change `whatif-savings` -> `whatif-result` shows deltas; open compare -> `fin-compare-table` lists both scenarios |
| 4.3 | Export and planner e2e | `fin-export-csv` download starts with `# SuperPlanner Finance is an educational planning tool.`; `send-to-planner` opens `/plans/<id>/tasks` with tasks visible |
| 4.4 | Flexible input e2e | "Start from scratch" -> fill only one income and one goal -> build -> result renders (defaults fill the rest); a goal date in the past shows a review error and the button is disabled |
| 4.5 | Dark mode e2e | toggle theme -> charts render, disclaimer visible |
| 4.6 | Isolation | finance e2e uses unique plan names (`E2E fin <timestamp>`), never deletes or renames other plans, and does not depend on test order; G6 still passes when run after it |
| 4.7 | Integration (if written) | `cd backend && .venv/bin/pytest -q tests/integration -k finance` passes: 100 random plans via API -> every completed result has no hard violation or is `infeasible` with a T0 deficit; two concurrent what-if requests with `replace_active` end with exactly one `completed` result for the latest run |
| 4.8 | Compliance sweep | a test scans `frontend/src/finance/**` and API responses of all templates with the 1.21 denylist and forbidden-word list: no hits |
| 4.9 | Full gate | G1-G7 green; final counts reported (551 + new backend, 23 + new e2e) |

---

## 5. LEAD review (after F4 4.9)

Code review per the team-lead brief: correctness first (constraint violations reported as feasible,
EF gating, lock-ins, glide caps, cash never below the buffer, cancel/complete races, what-if
replacement races, API/UI contract mismatches), then security (CSV injection, input caps, no amounts in
logs/audit, no network calls in the finance path), then maintainability. Findings cite file:line and the
owning WP.
