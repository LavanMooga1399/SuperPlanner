# SuperPlanner Phase 2a - Delivery Plan

Owner: team lead (LEAD). Contract: `docs/PHASE2.md` (cited as "P2D n"), then `docs/ARCHITECTURE.md` ("A.n")
and `docs/FINANCE.md` ("F.n") for everything P2D does not change. If this plan and P2D disagree on behaviour,
P2D wins; on file ownership, order and acceptance, this plan wins. Developers write only to their own
subsection of P2D section 9 (implementation notes). LEAD owns P2D sections 0-8 and this file.

Scope (product owner): "more user friendly and realistic, take more flexible inputs before planning":
A realistic finance, B flexible inputs (describe / paste / CSV, rule-based and optional AI extraction,
duration and amount ranges), C usability pass and react-router 7. Not in scope (phase 2b, do not build):
background job workers, PostgreSQL as default, user accounts/auth, plus the items of P2D section 6.

No `git commit` or `git push` by anyone. Existing features and tests keep working; an existing test may be
changed only if P2D section 5 lists it, or after the change is recorded in P2D 9.Px with the behaviour
change it follows from.

## 0. Overview

| WP | Name | Owner role | Owns (only these paths) | Starts | Depends on |
|----|------|-----------|-------------------------|--------|------------|
| P1 | Finance realism | backend-developer (instance A) | `backend/superplanner/finance/**`, `backend/tests/finance/**`; explicit edits: `backend/tests/integration_finance/finint_helpers.py`, `backend/tests/integration_finance/test_finint_whatif.py` (line 95), `backend/tests/api_finance/test_apifin_runs.py` (lines 47, 284), `docs/FINANCE.md` (one-line pointers only), P2D 1.9 table and 9.P1 | day 0 | P2D Part A |
| P2 | Intake backend + scheduling duration ranges | backend-developer (instance B), parallel to P1 | `backend/superplanner/intake/**`, `backend/superplanner/api/intake/**`, `backend/tests/intake/**`; explicit edits: `backend/superplanner/api/main.py`, `backend/superplanner/api/config.py`, `backend/requirements.txt`, `backend/pyproject.toml`, `backend/superplanner/engine/{model,compiled,explain,__init__}.py`, `backend/superplanner/api/services/replan_service.py`, `docs/ARCHITECTURE.md` (pointers in 3.4 and 11 only), P2D 9.P2; installs `anthropic==1.15.0` into `backend/.venv` | day 0 | P2D Part B; P1 step 1 (model contract) before P2 step 7 |
| P3a | Router upgrade + usability pass + landing page (+ finance and scheduling UI changes) | ui-developer | `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/**` except `frontend/src/intake/**` (it creates only `frontend/src/intake/routes.tsx` as an empty stub, then hands it to P3b), P2D 9.P3a | day 0 (step 1) | P2D Part C; P1 step 1 for 3.4 fields; P2 step 2 for 3.5 fields |
| P3b | Intake UI for both domains | ui-developer, after P3a is accepted | `frontend/src/intake/**` (incl. `routes.tsx` from then on), P2D 9.P3b | after P3a acceptance | P3a; P2 API (P2 step 8) for integration |
| P4 | Testing | tester | new `frontend/e2e/landing.spec.ts`, `frontend/e2e/intake.spec.ts`, `frontend/e2e/import.spec.ts`, `frontend/e2e/phase2-helpers.ts`; new `backend/tests/acceptance_phase2/**` (incl. its own `conftest.py`); P2D 9.P4 | day 0 (writing against the contract) | final runs after P1, P2, P3a, P3b |

```
P1 finance realism ──(step 1 model contract)──┬──────────────────────────────┐
P2 intake backend (steps 1-6) ────────────────┴─► P2 steps 7-9 ──────────────┤
P3a step 1 router (alone, gate) ─► P3a steps 2-5 ─► P3a accepted ─► P3b ─────┼─► P4 final runs ─► LEAD review
P4 test writing against P2D (all along) ─────────────────────────────────────┘
```

Ownership rules:
- No file has two owners. P1 and P2 run at the same time as two backend-developer instances, and their
  path sets do not overlap (checked: P2 never edits `superplanner/finance/**`, P1 never edits
  `superplanner/engine/**`, `superplanner/api/**`, `superplanner/intake/**`, `requirements.txt` or
  `pyproject.toml`). If P2 needs a finance change it asks P1, and P1 records it in 9.P1.
- P3a and P3b are the same role in sequence; `frontend/src/intake/routes.tsx` moves from P3a to P3b at
  P3a acceptance. `frontend/src/main.tsx` stays with P3a: it spreads `intakeRoutes`, so P3b does not need
  to edit it.
- P2D 3.3 places `StartPage.tsx` and `ExamplePage.tsx` under `intake/pages/`. In this plan they live in
  `frontend/src/landing/` (P3a), so the landing flow is complete without the intake UI. P2D 3.3 is otherwise
  unchanged.
- Nobody edits existing e2e files (`frontend/e2e/{contract,editors,explore,finance,journey,offset,
  qa-review-fixes,regressions,templates}.spec.ts`, `helpers.ts`, `finance-helpers.ts`,
  `playwright.config.ts`) or `docs/source/**`.
- `superplanner.intake` imports no fastapi/starlette/sqlalchemy/`superplanner.api`; `anthropic` is
  imported only in `superplanner/intake/ai/client.py` (lazily). `superplanner.finance` keeps its existing
  import boundary.
- New dependencies: Python `anthropic==1.15.0` only (P2). npm: `react-router@7.18.4` replaces
  `react-router-dom` (P3a); no other npm package.

## 1. Regression gate (checked by LEAD before review; P4 runs it)

Baseline measured 2026-10-17: **928** backend tests collected; **39** Playwright tests in 9 files; `npm
audit`: 2 moderate (`react-router`, `react-router-dom`), 0 high, 0 critical.

| # | Gate | Check |
|---|------|-------|
| G1 | Whole backend suite green | `cd backend && .venv/bin/pytest -q` exits 0; collected >= 928 + new tests; no test deleted (`git diff --stat backend/tests` shows no removed test functions except renames recorded in P2D 9.Px) |
| G2 | Existing tests changed only as allowed | `git diff --name-only -- backend/tests frontend/e2e` is a subset of: `tests/finance/test_fin_templates.py`, `tests/finance/test_fin_pipeline.py`, `tests/finance/test_fin_whatif_compare.py`, `tests/finance/test_fin_boundaries.py`, `tests/finance/test_fin_optimizer.py`, `tests/integration_finance/finint_helpers.py`, `tests/integration_finance/test_finint_whatif.py`, `tests/api_finance/test_apifin_runs.py`, plus files recorded in P2D 9.Px with a reason; every diff hunk matches P2D section 5 or a 9.Px entry |
| G3 | Only allowed existing files changed | `git status --porcelain` shows modified (`M`) entries only inside the owned paths of section 0 plus `docs/PHASE2.md`, `docs/PLAN-PHASE2.md` (new); no change in `backend/superplanner/templates/**`, `backend/superplanner/api/{routes,db}/**`, `backend/superplanner/api/finance/**`, `docs/source/**` |
| G4 | Frontend type-checks and builds | `cd frontend && npm run typecheck && npm run build` exits 0 |
| G5 | Existing Playwright tests unchanged and green | `cd frontend && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test -c e2e/playwright.config.ts contract editors explore journey offset qa-review-fixes regressions templates finance` -> 39 passed |
| G6 | Full Playwright run green | same command without file filters -> 39 + new tests passed, 0 flaky on a second run |
| G7 | npm audit clean | `cd frontend && npm audit --omit=dev` and `npm audit` report 0 critical, 0 high, 0 moderate |
| G8 | No network in tests | `cd backend && INTAKE_AI_ENABLED=1 ANTHROPIC_API_KEY=sk-test-dummy HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 .venv/bin/pytest -q tests/intake tests/acceptance_phase2` exits 0 (any real API call would fail) |
| G9 | Template realism bands | `cd backend && .venv/bin/pytest -q tests/finance/test_fin_realism_templates.py tests/finance/test_fin_growth_assets.py` exits 0; P1's 1.9 table in P2D is filled for seeds 0, 1, 7 |
| G10 | SDK usage boundary | `grep -rnE "^\s*(import anthropic|from anthropic)" backend/superplanner` lists only `intake/ai/client.py`; `grep -rnE "thinking|temperature|top_p|top_k|tool_choice" backend/superplanner/intake` finds nothing |
| G11 | Router dependency replaced | `grep -rn "react-router-dom" frontend/src frontend/package.json` finds nothing; `npm ls react-router` shows `7.18.4` |
| G12 | Existing APIs unchanged | `/openapi.json` still lists every existing path with the same methods; `GET /api/v1/problems`, `/templates`, `/finance/templates`, `/health` response shapes unchanged (covered by G1); new paths only under `/api/v1/intake/` |
| G13 | Nothing committed | `git log -1` is the same commit as at the start; `git status` shows the work uncommitted |

---

## P1 - Finance realism (backend-developer A)

### Deliverables
P2D 1.4-1.14 and the finance rows of P2D 4 and 5: caution settings and the new planning return, new
defaults, calibration aim, inflation-linked incomes, new template figures and the `retirement_target`
helper, growth-asset reasons and `SHARED_SHORTFALL`, funding split and new summary lines, amount ranges,
`engine_versions_differ`, engine version `fin-0.2.0`, the independent checker update, and the new tests
of 1.14.

### Steps (in order)
1. **Model contract (hand-off to P2 and P3a, target day 1).** `CautionSettings` + `Assumptions.caution`,
   `IncomeStream.inflation_linked`, `AmountRange` and the three `*_range` fields, new `GoalResult` and
   `ResultSummary` fields (defaults only, not computed yet), `FinanceComparison.engine_versions_differ`,
   `templates.retirement_target(expenses, incomes)`, all exported where P2D says. Tell LEAD; LEAD notifies
   P2 and P3a. After this step the field names and types are frozen; any later change goes through LEAD.
2. Defaults (1.4), `SOURCE_NOTE`, `FINANCE_ENGINE_VERSION = "fin-0.2.0"`. Keep exactly one "PPF-like" in
   `defaults.py` (existing compliance test).
3. `returns.planning_return` / `planning_rho` per 1.5 **as amended in P2D 8 item 1** (shared ramped
   penalty). Update every caller: optimizer, validator, pipeline `planning_returns_pct`, advisor explain;
   update `tests/finance/test_fin_optimizer.py:217-225`. Add `test_fin_caution.py`.
4. Calibration aim (1.6).
5. Inflation-linked incomes in `cashflow.py`, `simulate.py`, `whatif.py` (1.7); `test_fin_linked_income.py`.
6. Templates (1.8), keeping ids, parameter names and the earmark rule.
7. Funding split and summary lines (1.11), growth reasons and `SHARED_SHORTFALL` (1.10), amount ranges in
   preflight and explanations (1.12), `engine_versions_differ` in `compare.py` (1.13).
8. Independent checker `finint_helpers.py` (1.5 formula, linked incomes) and the other test changes of
   P2D 5.
9. Run every template at seeds 0, 1 and 7 and write the measured 1.9 table into P2D. If a band fails only
   because of the shared penalty, tune `floor_step_pct_per_z` within [1.0, 2.0] and record it in 9.P1.
10. `test_fin_realism_templates.py`, `test_fin_growth_assets.py`, `test_fin_funding_split.py`,
   `test_fin_ranges.py`, calibration-aim and mixed-version tests (1.14).

### Acceptance criteria
- P1-1 `cd backend && .venv/bin/pytest -q tests/finance tests/integration_finance tests/api_finance`
  exits 0. Only the P2D 5 tests (and 9.P1 entries) are changed.
- P1-2 Bands, for each template at seeds {0, 1} with `n_paths=1000` (seed 7 spot check, same statuses):
  `min(proj.surplus[0:12]) >= 0`, `summary.monthly_surplus_avg_12m > 0`, `summary.monthly_investable_now
  >= 0`; family >= 2 of 3 goals with chance >= 0.5 and no must goal `off_track`; near_retirement
  retirement `on_track`; young_professional retirement chance >= 0.5 and car `at_risk` with
  `shortfall_fraction <= 0.10` and >= 1 fix; all `feasible`, no hard violations, `assert_clean`.
- P1-3 Growth: every template goal with `months_to_goal >= 120` and tolerance >= 3 has
  `growth_share_now_pct >= 0.8 * growth_cap_now_pct`. This also holds for the family retirement goal at
  `calibration_rounds = 4`. Goals under 36 months stay within the glide cap.
- P1-4 Caution: unit tests show the 1.5 properties. The 1.5 table matches to 0.01 pp. Equity beats the
  best safe class by >= 0.25 pp over the p x Y x (z - z0) grid of 1.14. `floor_share = 0` gives the old
  values to 1e-12. Zero volatility gives exactly `R`.
- P1-5 Reasons: every goal's first reason code starts with `GROWTH_`. Its message names the goal, and the
  risk level when a risky class is allowed. Family retirement reads like the P2D 1.10 example.
  `SHARED_SHORTFALL` appears when >= 2 same-tier goals share a shortfall.
- P1-6 Funding: `from_surplus + from_savings == monthly_contribution_avg_12m` to 0.01 for every template
  and `fin_helpers` plan. `monthly_investable_now` and `monthly_contribution_now` keep their month-0
  values (an old result compared field by field). `SUMMARY_INVEST` is no longer emitted.
- P1-7 Compatibility: `tests/finance/fixtures/typical.finance.json` (no `caution`, no `inflation_linked`)
  loads, runs `feasible` and keeps its stored assumptions. Export then import round-trips the new fields.
- P1-8 Compliance: `test_fin_compliance.py` and `test_fin_advisor.py::test_every_sentence_from_catalog_and_compliant`
  pass with the new messages. No new message contains a `FORBIDDEN_WORDS` entry or a denylisted name.
- P1-9 Performance: `test_fin_performance.py` passes, and each template's default run takes <= 5 s on
  this machine.
- P1-10 Every e2e test that depends on finance still passes: the "Try this" fix exists for the car, and
  "₹4[89],xxx" still shows in the blank-plan preview (verified in G5).

---

## P2 - Intake backend + scheduling duration ranges (backend-developer B, parallel to P1)

### Deliverables
P2D 2.1-2.16 and the engine edits of 2.14 (with P2D 8 items 6-12): package `superplanner.intake`, API
`/api/v1/intake/*`, settings, the AI extractor, table import, `Task.duration_estimate` and `DurationRisk`,
and the replan write path.

### Steps (in order)
1. `.venv/bin/pip install anthropic==1.15.0`; pin it in `requirements.txt` and `pyproject.toml`
   `dependencies`. Confirm the 928 existing tests still pass.
2. Engine PERT (2.14): `pert_minutes`, `DurationEstimate`, the `Task` rule, `compiled.py` estimate,
   `DurationRisk` in `explain.py`, exports, and the replan write path in `replan_service.py`.
   `tests/intake/test_engine_pert.py`. (This unblocks P3a step 5.)
3. Models (2.3-2.5) and the text grammar (2.7.1-2.7.4) with table-driven tests and the linear-time
   regex rule.
4. Schedule extract, questions, answers and build (2.7.5-2.7.8, 2.8, 2.9.1 with `DOMAIN_OF_KIND`).
5. Tables (2.13): parse, mapping and apply, for both domains.
6. Money extract, questions and answers (2.7.9-2.7.10, 2.8).
7. Money build (2.9.2), after P1 step 1. It uses `finance.templates.retirement_target` read-only.
8. API (2.15), settings (2.12), the router in `api/main.py`, and AI slots on `app.state`.
9. AI extractor (2.10, with P2D 8 items 7-9), strict schema, prompts, merge (2.11), fake-client tests.

### Acceptance criteria
- P2-1 `cd backend && .venv/bin/pytest -q tests/intake` exits 0. The full suite stays green (G1), and G8
  passes.
- P2-2 Describing the 2.15 schedule text gives exactly the draft shown: keys, values, provenance spans
  (code-point offsets) and question ids. Building it gives `parts`, durations (t1 parts 320/400/480,
  E 400), `horizon_days = 64`, the `duration_summary` 10,320 / 9,600 / 11,040, and `report.ok`. The built
  `problem` is accepted by `POST /api/v1/problems` (201). A solver run on it ends with `feasibility == "feasible"`.
- P2-3 The 2.15 finance text gives the draft shown. Its build has `e1.amount = 75,000` with
  `amount_range` 70,000-80,000, a retirement target of 2,25,00,000, and preflight ok. The plan is
  accepted by `POST /api/v1/finance/plans` and a default run is `feasible`.
- P2-4 Grammar: the cases of 2.16 pass (Indian/Western grouping, lakh/crore/k/L/Cr, shared-unit ranges,
  currencies, frequencies, three-point durations, DMY/MDY/ambiguous dates, relative dates against a
  fixed `today`). The blueprint study example yields the exam milestone, windows, 10 mock tests and the
  revision tasks. A 20,000-character adversarial text finishes in < 2 s.
- P2-5 AI: the fake client receives exactly `model="claude-opus-5-5"`, `max_tokens=16000`,
  `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`, `output_config={"effort":
  "medium", "format": {"type": "json_schema", "schema": SCHEMA}}`, `system`, and `messages` (one user
  message with exactly the text). None of `thinking`, `temperature`, `top_p`, `top_k`, `tool_choice`,
  `tools` is passed, and there is no assistant prefill. The default factory passes `timeout=60.0` and
  `max_retries=2`. Every fallback code of 2.10 is produced by its trigger, and exceptions are caught most
  specific first (a `RateLimitError` maps to `AI_RATE_LIMITED`, not `AI_API_ERROR`). Exceptions are built
  with `httpx2`. Availability covers `api_key`, `auth_token` and `credentials`.
- P2-6 Strict schema: every object node has `additionalProperties: false` and
  `required == list(properties)`, with no `$ref`/`$defs` and no dropped keywords. Parsed JSON is
  validated with Pydantic, and any failure falls back with a reason.
- P2-7 Merge: typed numbers win (`KEPT_TYPED_NUMBER`), AI-only fields have confidence <= 0.8, unresolved
  AI references are dropped with a note, and an invalid merged draft discards the AI result.
- P2-8 API: every endpoint returns the status and error codes of 2.15. `capabilities` reports the AI
  state with and without the setting. Table text over 1,000,000 characters gives 422 (`TABLE_TOO_LARGE`
  or `VALIDATION_ERROR` with `max_length`). AI problems never cause a non-200 response. DB row counts of
  every table are unchanged after a full describe -> answer -> build sequence. `caplog` never contains
  the user text, table cells, or AI prompt/response text.
- P2-9 PERT: a `Task` with an estimate whose duration is not the PERT value gives 422 on
  `POST /problems`, and a milestone with an estimate is rejected. A replan that updates the duration of
  an estimated task returns 202 and drops the estimate. Documents without the field round-trip
  unchanged. `test_engine_explain.py` still passes unchanged (no `duration_risk` without ranges).
- P2-10 Boundaries: G10 holds, `superplanner.intake` imports no fastapi/sqlalchemy/`superplanner.api`
  (a test like the existing finance boundary test), and `intake/messages.py` and `ai/prompts.py` pass the
  finance denylist and `FORBIDDEN_WORDS`.

---

## P3a - Router upgrade + usability pass + landing page (ui-developer)

### Deliverables
P2D 3.1, 3.2, 3.4-3.7 and the UI parts of P2D 1.13 (mixed-version banner) and 2.14 (TaskTable write
paths).

### Steps (in order)
1. **Router upgrade alone (gate before step 2).** In `package.json`, replace `react-router-dom` 6.30.6
   with `react-router` 7.18.4 and regenerate `package-lock.json` with `npm install`. Change the imports
   in all 33 files to `react-router`, and in `main.tsx` take `RouterProvider` from `react-router/dom`.
   Change nothing else. Run G4, G5, G7 and G11 and report the results to LEAD.
2. Landing: `src/landing/` (`PlanChooser`, `kinds.ts`, `StartPage`, `ExamplePage`), the
   `FinanceTemplateCards` extraction (same test ids), `HomePage` (h1 "What do you want to plan?", h2 "Your
   plans"), `MainNav` active for `/new/money*`, "Build step by step" with `DOMAIN_OF_KIND`, and the routes
   of 3.1 in `main.tsx`, spreading `intakeRoutes` from the empty stub `src/intake/routes.tsx`.
3. Usability rules (3.6) on every screen P3a touches: `Term` + `glossary`, `errorMessage()` field
   mapping, the network error with Retry, empty states, inline validation with
   `aria-invalid`/`aria-describedby`, and `ConfirmDialog` for destructive actions.
4. Finance UI (3.4, after P1 step 1): `ResultKpis` (same test ids), `GoalCard` "Why this mix" + "Likely
   outcome" + growth bar, the wizard "Rises with inflation" toggle (off for new rows), range chips,
   `AssumptionsStep` reset + caution settings, the mixed-version banner on the what-if and compare
   screens, and `finance/api/types.ts`.
5. Scheduling ranges (3.5, after P2 step 2): `api/types.ts`, the `TaskTable` chip and its inline edit /
   milestone switch dropping the estimate, the `TaskDrawer` range inputs with `pertMinutes`, and the
   `ScheduleTab` risk note.

### Acceptance criteria
- P3a-1 After step 1: G4, G5 (39 passed), G7 and G11 pass, and `git diff --stat` touches only
  `package.json`, `package-lock.json`, the 33 importing files and `main.tsx`. Every existing URL still
  resolves to the same page (`/`, `/plans/:id/{tasks,...,compare}`, `/finance/...`, unknown paths ->
  NotFound).
- P3a-2 Landing: `/` shows h1 "What do you want to plan?" and four `landing-kind-<kind>` groups with four
  `landing-action-*` buttons each. Example and steps navigate as P2D 3.1 says; describe and import go to
  `/new/<kind>/describe|import`. `/new/unknown` shows NotFound. Existing `template-card-*` ids and
  `#import-file` still work. Every action can be reached and activated with the keyboard alone.
- P3a-3 "Build step by step" for study creates a problem with `domain == "exam_prep"`, and the plan list
  shows "Exam preparation". For money it reaches `/finance/<id>/setup/profile`.
- P3a-4 Finance: the KPI card "Left over each month" shows `monthly_surplus_avg_12m`, and "Plan invests"
  shows the funding split text of 3.4. The family example at defaults shows no negative "left over"
  amount and no "You can invest -₹…". Each goal card shows its `GROWTH_*` sentence and "Likely outcome:
  about N% of the target". A compare whose `engine_versions_differ` is true shows the banner and
  "Re-run plan".
- P3a-5 Scheduling: a task with an estimate shows the range chip. Editing its inline duration removes the
  range and the save succeeds (no 422). `TaskDrawer` writes `duration_minutes == pertMinutes(o, m, p)`.
- P3a-6 Usability: every new or touched form field with an error has `aria-invalid="true"` and an
  `aria-describedby` message. Every glossary term of 3.6 has a `Term` that shows on hover and on focus.
  Stopping the backend shows the friendly network message with Retry.
- P3a-7 G4, G5 and G7 still pass at the end of P3a. No npm dependency is added beyond `react-router`.

---

## P3b - Intake UI for both domains (ui-developer, after P3a is accepted)

### Deliverables
P2D 3.3: `frontend/src/intake/**` (api client and types, `IntakeContext`, `DescribePage`, `ImportPage`,
all components and libs listed there) and the `intakeRoutes` for `/new/:kind/describe` and
`/new/:kind/import`.

### Steps (in order)
1. `api/types.ts` and `api/client.ts` mirroring P2D 2.3-2.5, 2.9, 2.13 and 2.15 (hand-written).
2. `IntakeContext`, kept in `sessionStorage` under `sp.intake.<kind>` and cleared on create and on
   cancel. The AI toggle is never stored.
3. `DescribePage`: write, then questions, review and create. Includes `AiAssistToggle`,
   `ExtractorBanner`, `QuestionPanel`, `QuestionInput`, `SourceText`, both draft editors,
   `ConfidenceBadge`, `CreatePlanBar`, and a Cancel button during an AI request.
4. `ImportPage`: paste or file (`File.text()`, at most 1 MB, `.csv`/`.tsv`/`.txt`), then
   `ColumnMapper`, apply, questions, review and create.
5. `lib/codepoints.ts`, `lib/pert.ts`, then a keyboard and screen-reader pass.

### Acceptance criteria
- P3b-1 G4 and G5 pass. `package.json` is not changed by P3b. Every test id listed in P2D 3.3 exists.
- P3b-2 When `capabilities.ai_available` is false, the toggle is absent and the line "AI assist is not
  available on this server; the built-in reader is used." is shown. When it is true, the toggle is off
  on every visit. Turning it on shows the privacy notice inline (`intake-ai-notice`, text from
  `capabilities.privacy_notice`) and the submit label "Send to AI assist and make a draft". With the
  toggle off, `use_ai` is false in the request body.
- P3b-3 The schedule describe flow with the 2.15 text works: questions appear one at a time,
  "Use suggestions for all remaining" ends with no open questions, the review shows the counts and the
  PERT note, and "Create plan" leads to `/plans/<id>/tasks` showing "Gather requirements (1/3)" with a
  range chip. `sessionStorage` has no `sp.intake.*` key after create.
- P3b-4 The finance describe flow with the 2.15 text works: the review shows "About ₹… left each month
  in the first year", and "Create plan" leads to `/finance/<id>/setup/review`.
- P3b-5 Spans: hovering or focusing a highlighted `mark` highlights the matching field, and the reverse
  also works. Spans are sliced by code point (a text with "₹" and an emoji highlights the right
  characters).
- P3b-6 Import: a pasted TSV shows the suggested mapping. Changing one mapping and applying gives the
  draft rows. A file over 1 MB is refused in the browser with a plain message, without a request. A CSV
  file upload works.
- P3b-7 "Create plan" is disabled while required questions or preflight errors remain, and the issues
  are listed in plain words. Nothing is saved before "Create plan" (no `POST /problems` or
  `/finance/plans` request before the click).

---

## P4 - Testing (tester)

### Deliverables
- `frontend/e2e/landing.spec.ts`, `intake.spec.ts`, `import.spec.ts`, `phase2-helpers.ts` (P2D 3.8 and
  the P3a/P3b criteria above).
- `backend/tests/acceptance_phase2/` with its own `conftest.py`. These are cross-package API tests:
  (a) schedule describe -> answer -> build -> `POST /problems` -> solver run with `feasibility == "feasible"`; (b) finance
  describe -> build -> `POST /finance/plans` -> run feasible with the funding split identity; (c) AI path
  end to end through `Settings.intake_ai_client_factory` with a fake client (success, typed numbers win,
  refusal fallback); (d) template bands via the API (instantiate -> run) for all three templates;
  (e) replan of an intake-built plan with a duration update; (f) mixed-version compare flag; (g) no DB
  writes and no user text in logs across the intake endpoints.
- The gate report: G1-G13 with command output summaries, written as the P4 entry in P2D 9.P4.

### Steps
1. From day 0, write the tests against P2D. Mark tests whose WP has not landed with
   `pytest.mark.skip(reason="waiting for Pn")` and remove the marks as WPs land (no skips may remain at
   the end).
2. After P1 and P2: run `tests/acceptance_phase2` and G1, G8, G9, G10 and G12.
3. After P3a step 1: run G4, G5, G7 and G11 (router gate).
4. After P3b: run the new e2e specs, G6 twice, and G2, G3 and G13.
5. Report every failure to the owning WP, citing file:line and the failing check. The tester does not
   fix product code.

### Acceptance criteria
- P4-1 Every new test runs without network (G8) and without `anthropic` network calls (a fake client
  everywhere).
- P4-2 `landing.spec.ts` covers all 4 x 4 actions, keyboard only. `intake.spec.ts` covers P3b-2,
  P3b-3, P3b-4 and the cleared `sessionStorage`. `import.spec.ts` covers P3b-6.
- P4-3 `tests/acceptance_phase2` items (a)-(g) pass.
- P4-4 G1-G13 all pass. The report lists counts (backend collected/passed, Playwright passed) and the
  `npm audit` summary.
- P4-5 No existing test or e2e file is modified by P4.

---

## 5. LEAD review (after P4 step 4)

LEAD reviews against P2D, this plan and the acceptance criteria, in this order: correctness first
(scheduling semantics of split parts and PERT, constraint violations reported as feasible, finance bands
and growth decisions, API/UI contract matches, AI fallbacks and untrusted-data handling), then security
(no text in logs, privacy notice and per-request opt-in, size limits, ReDoS), then maintainability.
Findings name file:line, the failure scenario and the owning WP. A WP is done when its criteria and the
gate pass and LEAD's findings for it are closed.
