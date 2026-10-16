# SuperPlanner Finance - Goal-based Financial Planning Module (design)

Status: design baseline for Finance v0.1. Owner: architect.
Source of intent: `docs/source/followups-finance-competitors-generalization.txt` (finance answer,
sections 1-8). Shared conventions come from `docs/ARCHITECTURE.md` (cited as "A.n").

This document is a contract with the same rules as A: where it says "must", two independent
implementations must behave identically. Interpretations go to section 24 "Implementation notes".

---

## Table of contents

1. Overview, scope and principles
2. Component diagram and dependency rules
3. Time model and units
4. Data model (`FinancePlan` document)
5. Default assumptions (asset classes, correlations, risk caps, glide path)
6. Validation layering and preflight
7. Cash-flow engine (`cashflow.py`)
8. Optimizer (`optimizer.py`): exact LP/MILP formulation
9. Monte Carlo and deterministic scenarios (`simulate.py`)
10. Calibration loop and pipeline (`pipeline.py`)
11. Independent validator (`validator.py`)
12. Explanations and fixes (`advisor/`)
13. What-if (`whatif.py`) and comparison
14. Result model (`FinanceResult`)
15. Templates
16. Send to planner (`bridge.py`) and CSV export
17. Persistence (DB tables)
18. REST API (`/api/v1/finance/...`)
19. Progress events (SSE)
20. Frontend (routes, components, state, charts)
21. Compliance and disclaimer rules
22. Repository layout, file ownership, edits to existing files
23. Testing strategy
24. Deferred items, deviations, implementation notes
25. Review notes (team lead)

---

## 1. Overview, scope and principles

The module answers: **where** (asset class), **when** (which months), **how much** (monthly amounts)
and **until when** (start/stop months) to invest so that the user's goals are funded. It produces
a goal-based, cash-flow-aware plan that is optimized (LP), stress-tested (Monte Carlo + scenarios),
independently validated and explained in plain language.

It is **educational decision support**, not regulated investment advice (section 21).

| # | Principle | Consequence |
|---|-----------|-------------|
| F1 | Separate domain package | `backend/superplanner/finance/` is pure Python (pydantic, numpy, ortools). No fastapi/sqlalchemy, no `superplanner.api` imports. Money allocation is **not** expressed as scheduler tasks. |
| F2 | Feasibility first | Hard rules (cash never below buffer, lock-ins, risk caps, EF before discretionary goals) are constraints, never objective terms. Goal shortfalls are objectives, ordered lexicographically by priority. |
| F3 | Honest uncertainty | Every goal shows a success probability and p10/p50/p90 range. No "guaranteed" language. The plan is solved with cautious (haircut) returns; Monte Carlo measures the result. |
| F4 | Asset classes only | No named products, funds, tickers or issuers in generated text, defaults or templates. Assumptions are user-editable, stored in the plan, shown with every result. |
| F5 | Computed explanations | Every sentence is generated from computed numbers by fixed templates. No LLM, no live market data, no remembered rates. |
| F6 | Reuse infrastructure | Same error envelope, If-Match versioning, immutable snapshots, thread-pool runs with persisted events and SSE framing, audit table, design system. |
| F7 | Simplest thing that works | Monthly time step, real (today's money) accounting, annual SIP blocks, GLOP LP, numpy Monte Carlo. MILP only when the user sets minimum contribution amounts. |
| F8 | Flexible input | Every list may be empty; every field has a default except the few marked required; drafts are saveable while incomplete (model 422 only for type/range errors). |

Pipeline of one finance run:

```
FinancePlan snapshot
  -> preflight (errors stop the run)
  -> cashflow projection (stage A: income, expenses, EMIs, one-offs, emergency-fund waterfall)
  -> optimizer (stage B: lexicographic LP over goals x asset classes x annual blocks)
  -> Monte Carlo + deterministic low/central/high scenarios
  -> calibration (raise caution for goals below their minimum probability; max N rounds)
  -> independent validator (feasibility decided here)
  -> explanations + fixes (re-solves of the LP)
  -> persist FinanceResult
```

---

## 2. Component diagram and dependency rules

```
+--------------------------------------------------------------------------------+
| React app: top nav "Scheduling" | "Finance"                                     |
|  frontend/src/finance/**  (wizard, results dashboard, what-if, compare, SVG)   |
+---------------------------|---------------------------|------------------------+
                            | /api/v1/finance/* JSON     | /api/v1/finance/runs/{id}/events (SSE)
+---------------------------v---------------------------v------------------------+
| backend/superplanner/api/finance/  router.py  service.py  run_service.py       |
|   schemas.py  db_models.py (tables on the shared Base)  planner_link.py         |
|   uses: api.context (ctx, WRITE_LOCK, executor), api.errors, api.db,           |
|         api.services.problem_service.create_problem (send-to-planner only)     |
+-----------------------------------------|--------------------------------------+
                                          v  superplanner.finance public API
+--------------------------------------------------------------------------------+
| backend/superplanner/finance/  (pure Python)                                   |
|  model.py defaults.py timegrid.py returns.py preflight.py cashflow.py         |
|  optimizer.py                                                                  |
|  simulate.py validator.py advisor/{explain,fixes}.py whatif.py compare.py      |
|  pipeline.py templates.py export.py bridge.py (-> superplanner.engine.model)   |
+--------------------------------------------------------------------------------+
```

Dependency rules (tested by an import-boundary test, section 23):
- `superplanner.finance` never imports `fastapi`, `starlette`, `sqlalchemy` or `superplanner.api`.
- Only `finance/bridge.py` imports from `superplanner.engine`, and only `superplanner.engine.model`.
- `finance/validator.py` imports only `finance.model`, `finance.defaults`, `finance.timegrid`,
  `finance.cashflow` and `finance.returns` (small shared return-math helpers, section 8.2). It must
  not import `optimizer`, `simulate`, `advisor`, `pipeline`.
- `superplanner.api.finance` uses the engine only through `superplanner.finance.__init__` public names
  (section 2.1) and `problem_service.create_problem`.

### 2.1 Public API (`superplanner/finance/__init__.py`)

```python
__version__ = "fin-0.1.0"                     # FINANCE_ENGINE_VERSION, stored on runs/results
from .model import *                          # all public models of section 4 and 14
def default_plan(*, name: str = "My financial plan", start_month: str) -> FinancePlan
def default_assumptions() -> Assumptions
def preflight(plan: FinancePlan) -> FinancePreflightReport
def project_cashflow(plan: FinancePlan) -> CashflowProjection          # section 7
def summarize_cashflow(proj: CashflowProjection) -> CashflowSummary    # preview endpoint
def run_plan(plan: FinancePlan, request: FinanceRunRequest,
             progress_cb: Callable[[FinanceProgress], None] | None = None,
             cancel_event: threading.Event | None = None) -> FinanceResult   # raises FinancePreflightError, FinanceCancelled
def validate_result(plan: FinancePlan, result: FinanceResult) -> list[FinanceViolation]
def apply_what_if(plan: FinancePlan, changes: WhatIfChanges) -> FinancePlan
def compare_results(a: FinanceResult, b: FinanceResult) -> FinanceComparison
def contributions_csv(plan: FinancePlan, result: FinanceResult) -> str
def to_planner_problem(plan: FinancePlan, result: FinanceResult, *, name: str, months: int,
                       utc_offset: str, review_every_months: int, include_rebalances: bool) -> tuple[Problem, int]
TEMPLATES: dict[str, FinanceTemplate]; def get_template(template_id: str) -> FinanceTemplate  # KeyError
DISCLAIMER: str; DISCLAIMER_VERSION: str
class FinancePreflightError(Exception): report: FinancePreflightReport
class FinanceCancelled(Exception): ...
```

---

## 3. Time model and units

- **Month**: string `"YYYY-MM"`, regex `^\d{4}-(0[1-9]|1[0-2])$`. No days, no time zones in finance
  documents (eliminates offset bugs). `timegrid.month_index(start_month, m)` = months between.
- **Plan start** `start_month` = month index `t = 0`. Services fill a missing/null `start_month`
  with the current **UTC** month on every write (create, PUT, import, instantiate), so stored
  documents and snapshots are always concrete and reproducible.
- **Horizon** `T` (months) = `max(12, max_g D_g + 1, last one-off index + 1)` (the `+ 1` keeps the
  goal-payment month `D_g` inside every length-`T` array), or `month_index(horizon_end_month) + 1` if set
  (must be >= the computed value, else preflight error `HORIZON_BEFORE_GOAL`). `T <= 600` (50 years), else `HORIZON_TOO_LONG`.
- **Within a month** (order is binding for cashflow, LP, simulator, validator):
  1. income, expenses, EMIs and one-offs of month `t` occur at the start of the month;
  2. emergency-fund (EF) contribution, then goal contributions, at the start of the month;
  3. returns accrue over the month; balances "at month t" are values at the start of month t
     before step 1.
- **Goal date** `D_g = month_index(goal.target_month)`. The goal is paid at the start of month
  `D_g`, before any contribution of that month. Contributions for `g` exist only for `t in [0, D_g-1]`.
  `D_g >= 1` required (`GOAL_TOO_SOON` error otherwise).
- **Blocks** (SIP levels): block length `L = constraints.contribution_block_months` (12 default, or 6).
  Block `k` covers months `[kL, (k+1)L)`; for goal `g` it is truncated at `D_g`:
  `n_{g,k} = min(L, D_g - kL)`, `K_g = ceil(D_g / L)`. Contributions are a level real amount per
  month within a block (a "step-up SIP"); rebalancing happens only at block starts. Blocks are
  aligned to the plan start for every goal, so global caps compare the same months.
- **Plan year** `y(t) = floor(t / 12)` (used for growth steps, inflation shocks, interruptions).
- **Money**: `float`, currency units of `profile.currency` (ISO 4217, default `"INR"`). Inputs are
  in **today's money** (value at `start_month`) unless the field says *nominal*. All engine
  accounting (cashflow, LP, validator, results) is in **real terms (today's money)**. Expected
  nominal values are derived as `real * P_t`, `P_t = (1 + pi)^(t/12)` with `pi = inflation_pct/100`.
- **Percent fields** end in `_pct` and hold percent numbers (`6.0` = 6 %). Probabilities are
  decimals `0..1`. Rates are annual unless named `monthly_*`.
- **Real return** of class `a` (annual): `R_a = (1 + mu_a - er_a - td_a) / (1 + pi) - 1` where
  `mu = expected_return_pct/100`, `er = expense_ratio_pct/100`, `td = tax_drag_pct/100`.
  Monthly: `r_a = (1 + R_a)^(1/12) - 1`. Monthly growth factor `gamma_a = 1 + r_a`.

---

## 4. Data model (`finance/model.py`)

Pydantic v2, every model `ConfigDict(extra="forbid")`. JSON names = attribute names (snake_case).
TS mirrors in `frontend/src/finance/api/types.ts`. Types:

| Name | Definition |
|------|------------|
| `Id` | `str`, regex `^[A-Za-z0-9_.:\-]{1,64}$` (same as A.3.1) |
| `Month` | `str`, regex `^\d{4}-(0[1-9]|1[0-2])$` |
| `Money` | `float`, `ge=0`, `le=1e12` |
| `SignedMoney` | `float`, `ge=-1e12`, `le=1e12` |
| `Pct` | `float` with the range given per field |
| `Frequency` | `Literal["monthly","quarterly","half_yearly","yearly","once"]` |
| `Priority` | `Literal["must","should","nice"]` |
| `Name` | `str`, `min_length=1`, `max_length=200` |

Reserved ids (preflight `RESERVED_ID` error if used by a user item): `emergency_fund`,
`cash_buffer`, `unallocated` (they share the namespace of `holdings_assignment.goal_id`).
The prefix `whatif_` is reserved for items added by `apply_what_if` (section 13). It is **not** a
preflight rule (derived what-if snapshots must pass preflight); instead the API services reject any
stored document containing an item id starting with `whatif_` on create, PUT, import and instantiate
with 422 `VALIDATION_ERROR` (`details.errors[].loc` = the item path). `apply_what_if` raises
`ValueError` if its input already contains such an id. [R12]

### 4.1 `FinancePlan` (stored document)

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id` | `Id` | `"draft"` | server sets to the record id |
| `name` | `Name` | required | |
| `description` | `str` <= 10000 | `""` | |
| `schema_version` | `Literal[1]` | `1` | |
| `start_month` | `Month \| None` | `None` | filled by services (section 3) |
| `horizon_end_month` | `Month \| None` | `None` | optional override |
| `profile` | `Profile` | defaults | |
| `incomes` | `list[IncomeStream]` <= 20 | `[]` | |
| `expenses` | `list[Expense]` <= 100 | `[]` | |
| `debts` | `list[Debt]` <= 20 | `[]` | |
| `holdings` | `list[Holding]` <= 50 | `[]` | |
| `one_offs` | `list[OneOff]` <= 200 | `[]` | |
| `goals` | `list[Goal]` <= 12 | `[]` | |
| `emergency_fund` | `EmergencyFundSettings` | defaults | |
| `assumptions` | `Assumptions` | `default_assumptions()` | |
| `constraints` | `PlanConstraints` | defaults | |
| `metadata` | `dict` <= 64 KiB JSON | `{}` | free-form (UI wizard progress lives here: `metadata.wizard = {"completed_steps": [...]}`) |

### 4.2 `Profile`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `currency` | `str` regex `^[A-Z]{3}$` | `"INR"` | display + CSV only (single currency) |
| `locale` | `str` <= 16 | `"en-IN"` | UI number formatting |
| `age` | `int \| None` 16..100 | `None` | used by templates, retirement presets, UI hints |
| `retirement_age` | `int` 40..80 | `60` | retirement goal preset (UI/template), not an LP input |
| `risk_tolerance` | `int` 1..5 | `3` | 1 = very cautious ... 5 = growth-seeking; selects base risky cap (5.3) |
| `tax_note` | `str` <= 1000 | `""` | free text shown in results; **no tax is computed** (incomes are take-home) |

### 4.3 `IncomeStream`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id` | `Id` | required | |
| `name` | `Name` | required | |
| `kind` | `Literal["salary","business","rental","pension","interest","other"]` | `"salary"` | |
| `amount` | `Money` | required | **nominal** take-home per occurrence, as of the stream's first month |
| `frequency` | `Frequency` | `"monthly"` | |
| `growth_pct` | `float` -50..50 | `0.0` | nominal annual step-up, applied on each anniversary of the stream start |
| `start_month` | `Month \| None` | `None` = plan start | a month before the plan start is treated as the plan start (occurrence phase and growth anniversaries count from `t0 = 0`; `amount` is then the current amount) |
| `end_month` | `Month \| None` | `None` = open-ended | inclusive; an item ending before the plan start never occurs |
| `interruptible` | `bool` | `true` | can be hit by the Monte Carlo income-interruption model |

### 4.4 `Expense`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id`, `name` | | required | |
| `category` | `str` <= 64 | `"other"` | free label (rent, food, school fees...) |
| `amount` | `Money` | required | per occurrence, **today's money** |
| `frequency` | `Frequency` | `"monthly"` | |
| `essential` | `bool` | `true` | essentials define the EF target; discretionary items are candidates for "spend less" fixes |
| `inflation_linked` | `bool` | `true` | false = fixed nominal amount (real value shrinks) |
| `inflation_pct` | `float \| None` -5..30 | `None` | item-specific inflation (e.g. school fees 9) |
| `start_month`, `end_month` | `Month \| None` | `None` | as 4.3 (same clamping) |

### 4.5 `Debt`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id`, `name` | | required | |
| `kind` | `Literal["home","vehicle","education","personal","credit_card","other"]` | `"other"` | |
| `balance` | `Money` | required | outstanding principal at plan start (nominal) |
| `interest_rate_pct` | `float` 0..60 | required | nominal annual |
| `emi` | `Money` | required | nominal monthly instalment, fixed |
| `remaining_months` | `int \| None` 1..600 | `None` | informational; warning if inconsistent with amortization by > 3 months |

### 4.6 `Holding`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id`, `name` | | required | e.g. "Savings account", "Equity investments" (user text) |
| `asset_class_id` | `Id` | required | must exist in `assumptions.asset_classes` |
| `amount` | `Money` | required | current value (today's money) |
| `locked_until_month` | `Month \| None` | `None` | cannot be sold before this month |

### 4.7 `OneOff`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id`, `name` | | required | |
| `kind` | `Literal["expense","inflow"]` | `"expense"` | inflow = bonus, inheritance, maturity |
| `month` | `Month` | required | |
| `amount` | `Money` | required | today's money if `inflation_linked`, else nominal |
| `inflation_linked` | `bool` | `true` | |

A one-off expense is a known commitment paid from cash flow (the LP saves ahead for it in the cash
buffer). Anything the user wants to *invest* towards is a `Goal`.

### 4.8 `Goal`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id`, `name` | | required | |
| `kind` | `Literal["retirement","education","home","vehicle","travel","wedding","business","other"]` | `"other"` | icon + preset only |
| `target_amount` | `Money`, `gt=0` | required | today's money |
| `target_month` | `Month` | required | money needed at the start of this month |
| `priority` | `Priority` | `"should"` | |
| `flexibility_months` | `int` 0..120 | `0` | acceptable delay; used by fixes |
| `min_success_probability` | `float \| None` 0.5..0.99 | `None` | default by priority: must 0.85, should 0.70, nice 0.50 |
| `inflation_pct` | `float \| None` -5..30 | `None` | goal-specific cost inflation (education 9) |
| `risk_tolerance` | `int \| None` 1..5 | `None` | overrides `profile.risk_tolerance` for this goal |
| `allowed_asset_class_ids` | `list[Id] \| None` | `None` = all classes | |
| `earmarked` | `list[Earmark]` <= 20 | `[]` | `Earmark = {holding_id: Id, amount: Money}` existing savings set aside for this goal |
| `enabled` | `bool` | `true` | disabled goals are ignored by every engine stage |

Real target: `TR_g = target_amount * ((1 + pi_g)/(1 + pi))^(D_g/12)` with `pi_g = inflation_pct/100`
(goal override or general). Expected nominal target `TN_g = TR_g * P_{D_g}`.

### 4.9 `EmergencyFundSettings`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `months_of_essentials` | `float` 0..24 | `6.0` | 0 disables the EF |
| `asset_class_id` | `Id` | `"fixed_deposit"` | must have `lock_in_months == 0` and `liquidity_days <= 7` |
| `build_share` | `float` 0.1..1.0 | `1.0` | share of positive surplus sent to the EF while below target |

### 4.10 `Assumptions`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `inflation_pct` | `float` -2..25 | `6.0` | general consumer inflation |
| `inflation_volatility_pct` | `float` 0..10 | `1.5` | std dev of annual inflation (Monte Carlo) |
| `cash_class_id` | `Id` | `"cash"` | class of the free cash buffer; lock 0, liquidity <= 1 day |
| `asset_classes` | `list[AssetClass]` 1..10 | defaults (5.1) | |
| `correlations` | `list[Correlation]` <= 45 | defaults (5.2) | missing pairs = 0, diagonal = 1 |
| `risky_cap_by_tolerance_pct` | `list[float]` length 5, each 0..100, non-decreasing | `[20, 40, 60, 75, 90]` | max growth-asset share for tolerance 1..5 |
| `glide_path` | `list[GlideStep]` 1..12 | defaults (5.4) | `GlideStep = {min_months_to_goal: int 0..600, multiplier: float 0..1}`; must contain `min_months_to_goal == 0` |
| `source_note` | `str` <= 1000 | `"Illustrative long-run assumptions, not forecasts. Edit them to match your own view."` | shown with results |

`AssetClass`:

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `id`, `name` | | required | |
| `category` | `Literal["cash","debt","equity","gold","other"]` | required | growth (risky) classes: `equity`, `gold`, `other` |
| `expected_return_pct` | `float` -20..40 | required | nominal, gross of costs |
| `volatility_pct` | `float` 0..80 | required | annual std dev of returns |
| `expense_ratio_pct` | `float` 0..5 | `0.0` | |
| `tax_drag_pct` | `float` 0..10 | `0.0` | optional user estimate; no tax rules applied |
| `liquidity_days` | `int` 0..365 | `0` | informational; EF/cash eligibility |
| `lock_in_months` | `int` 0..360 | `0` | each contribution is locked this long; never sold before its goal |
| `min_monthly_contribution` | `Money` | `0` | > 0 switches the optimizer to MILP (8.6) |
| `description` | `str` <= 500 | `""` | |

`Correlation = {a: Id, b: Id, rho: float -1..1}` (unordered pair, `a != b`).

### 4.11 `PlanConstraints`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `max_equity_pct` | `float \| None` 0..100 | `None` | global cap on `equity` category share of the invested goal portfolio at each block start |
| `max_class_pct` | `dict[Id, float 0..100]` | `{}` | global per-class share cap at each block start |
| `min_cash_buffer` | `Money` | `0` | real; free cash after contributions must stay >= this every month |
| `contribution_block_months` | `Literal[6, 12]` | `12` | |
| `rebalance_cost_pct` | `float` 0..2 | `0.1` | cost on amount sold when rebalancing |

---

## 5. Default assumptions (`finance/defaults.py`)

Illustrative, user-editable, labelled as such everywhere. Never fetched from the network.

### 5.1 Asset classes

| id | name | category | exp. return % | vol % | expense % | liquidity days | lock-in months |
|----|------|----------|---------------|-------|-----------|----------------|----------------|
| `cash` | Cash / savings account | cash | 3.0 | 0.5 | 0.0 | 0 | 0 |
| `fixed_deposit` | Fixed deposit | debt | 6.75 | 1.0 | 0.0 | 2 | 0 |
| `short_debt` | Short-term debt fund | debt | 7.0 | 2.0 | 0.35 | 2 | 0 |
| `govt_long` | Government long lock-in savings (PPF-like) | debt | 7.1 | 0.5 | 0.0 | 7 | 180 |
| `equity_index` | Diversified equity index fund | equity | 11.5 | 18.0 | 0.2 | 3 | 0 |
| `gold` | Gold | gold | 8.0 | 15.0 | 0.4 | 3 | 0 |

### 5.2 Correlations (non-listed pairs 0)

`cash-fixed_deposit 0.5`, `fixed_deposit-short_debt 0.5`, `short_debt-govt_long 0.3`,
`equity_index-short_debt 0.1`, `gold-short_debt 0.1`, `equity_index-gold 0.0`.

### 5.3 Risk caps

Base growth-asset cap `base_g = risky_cap_by_tolerance_pct[tol_g - 1] / 100`,
`tol_g = goal.risk_tolerance or profile.risk_tolerance`.

### 5.4 Glide path (default)

| `min_months_to_goal` | 120 | 84 | 60 | 36 | 24 | 12 | 0 |
|---|---|---|---|---|---|---|---|
| multiplier | 1.0 | 0.85 | 0.70 | 0.50 | 0.35 | 0.20 | 0.0 |

`glide(m)` = multiplier of the step with the largest `min_months_to_goal <= m`.
Cap for goal `g` in block `k`: `cap_{g,k} = base_g * glide(D_g - kL)`.

### 5.5 Other defaults

EF 6 months in `fixed_deposit`, build share 1.0; inflation 6.0 +- 1.5; `min_cash_buffer` 0;
block 12; rebalance cost 0.1 %. Run defaults in 10.1. Disclaimer in 21.

---

## 6. Validation layering and preflight (`finance/preflight.py`)

Same split as A.3.0:
- **Model layer (422 on POST/PUT):** types, ranges, regexes, list lengths, `extra="forbid"`,
  `Correlation.a != b`, `risky_cap_by_tolerance_pct` length 5 and non-decreasing, glide path has a
  `0` step and unique `min_months_to_goal`.
- **Preflight layer (`/validate`, `/preview`, run creation 422 `PREFLIGHT_FAILED`):** relational
  and horizon checks.

```python
class FinanceIssue(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str                      # plain language, uses item names
    field: str | None = None          # JSON path, e.g. "goals[2].target_month"
    item_ids: list[str] = []
class FinancePreflightReport(BaseModel):
    ok: bool                          # no errors
    issues: list[FinanceIssue]
```

| code | severity | rule |
|------|----------|------|
| `DUPLICATE_ID` | error | ids unique within each list, and across goals+holdings+incomes+expenses+debts+one_offs |
| `RESERVED_ID` | error | section 4 reserved ids |
| `UNKNOWN_ASSET_CLASS` | error | holding / EF / cash class / allowed list / `max_class_pct` key / correlation references a missing class |
| `UNKNOWN_HOLDING` | error | earmark references a missing holding |
| `EARMARK_EXCEEDS_HOLDING` | error | sum of earmarks on a holding > its amount + 0.01 |
| `EARMARK_LOCKED_PAST_GOAL` | error | earmarked holding `locked_until_month` > goal `target_month` |
| `END_BEFORE_START` | error | `end_month < start_month` on an income/expense |
| `GOAL_TOO_SOON` | error | `D_g < 1` (target month not after start) |
| `ONE_OFF_IN_PAST` | error | one-off month before `start_month` |
| `HORIZON_TOO_LONG` | error | `T > 600` |
| `HORIZON_BEFORE_GOAL` | error | `horizon_end_month` earlier than a goal or one-off |
| `CASH_CLASS_INVALID` | error | cash class lock > 0 or liquidity_days > 1 |
| `EF_CLASS_NOT_LIQUID` | error | EF class lock > 0 or liquidity_days > 7 |
| `DEBT_NEVER_REPAID` | error | `emi <= balance * rate/12` (instalment does not cover interest) |
| `NO_ALLOWED_CLASS` | error | a goal's allowed classes are all lock-in classes maturing after its date |
| `TOO_LARGE` | error | LP size estimate (8.7) > 60 000 variables |
| `NO_INCOME` | warning | no income streams |
| `NO_GOALS` | warning | no enabled goals (run still computes cash flow and EF) |
| `NEGATIVE_SURPLUS` | warning | some month has `S_t < 0` (lists first 6 months) |
| `DEBT_TERM_MISMATCH` | warning | `remaining_months` differs from amortization by > 3 |
| `CORRELATION_NOT_PSD` | warning | matrix not positive semi-definite; repaired (9.1) |
| `HIGH_INTEREST_DEBT` | warning | debt rate > highest class expected return (educational note) |
| `GOAL_TARGET_HUGE` | warning | target > 500 x average monthly surplus (skipped when the average surplus is <= 0; `NEGATIVE_SURPLUS` covers that) |

Messages example: `Goal "Car" is due in 2026-11, which is not after the plan start (2026-11). Pick a later month.`

---

## 7. Cash-flow engine (`finance/cashflow.py`)

Pure, deterministic, real terms. Stage A of every run; also used by the validator, preview and
Monte Carlo (nominal variants).

### 7.1 Occurrence rule

Item with first month `t0` (its `start_month` or 0), last `t1` (its `end_month` or `T-1`) occurs at
`t in [t0, t1]` when `(t - t0) mod p == 0` with `p` = 1 monthly, 3 quarterly, 6 half_yearly,
12 yearly; `once` occurs only at `t0`. Monthly-equivalent factor `q` = 1, 1/3, 1/6, 1/12, 0 (once).

### 7.2 Equations (month t, real)

- Income `i`: `I_{i,t} = amount * (1 + g_i)^floor((t - t0)/12) / P_t` when occurring.
- Expense `e`: `E_{e,t} = amount * f_e(t)` when occurring, where
  `f_e(t) = ((1+pi_e)/(1+pi))^(t/12)` if inflation-linked (`pi_e` = item override or `pi`, so
  `f = 1` without override) and `f_e(t) = 1/P_t` if not linked.
- Debt `d` (nominal amortization, monthly rate `j = rate/12`): `bal_0 = balance`; while
  `bal_t > 0`: payment `pay_t = min(emi, bal_t*(1+j))`, `bal_{t+1} = bal_t*(1+j) - pay_t`.
  Real `EMI_{d,t} = pay_t / P_t`. `payoff_month` recorded.
- One-off `o` at month `t_o`: real `amount` if inflation-linked else `amount / P_{t_o}`; sign
  `-` expense, `+` inflow.
- Surplus `S_t = sum I - sum E(essential) - sum E(discretionary) - sum EMI + sum one-off inflows - sum one-off expenses`.

### 7.3 Emergency fund waterfall

- Target (real, constant): `EF* = months_of_essentials * (sum_e essential amount * q_e * f_e(0) + sum_d EMI_{d,0})`,
  where the sum runs over essential expenses whose clamped `[t0, t1]` contains `t = 0` and whose id does
  not start with `whatif_` (what-if items never move the EF target), and over debts with `balance > 0`. [R3]
- Initial: holdings (free amounts after earmarks, not locked past start) in the EF class, then in
  the cash class, fill `EF_0 = min(EF*, ...)` in list order (cash-class money used for the EF is
  treated as moved into the EF class at `t = 0`, no cost). Remaining free cash-class amount
  becomes the fixed cash buffer start `B0_fixed`. Remaining free amounts of all other holdings
  (including locked ones) form the **assignable pool** (LP variables `y` and `w`, 8.3).
  Every split is reported in `holdings_assignment` (section 14). [R4]
- Monthly: `ef_t = min(build_share * max(S_t, 0), max(0, EF* - EF_t))`;
  `EF_{t+1} = (EF_t + ef_t) * gamma_EF`.
- `t_E` = first `t` with `EF_t >= EF* - 1.0` (`0` if already full, `T` if never). The EF is never
  drawn in the deterministic plan (it is drawn only in Monte Carlo shocks).
- Investable cash for the LP: `A_t = S_t - ef_t` (may be negative).

`CashflowProjection` fields: `start_month, T, months: list[Month], income, essential, discretionary,
debt_payments, one_off_net, surplus, ef_contribution, ef_balance, investable` (lists of length T,
real), `ef_target, ef_initial, ef_complete_index (int | None), cash_buffer_initial (= B0_fixed),
assignable: list[{holding_id, asset_class_id, amount, locked_until_index | None}],
debt_payoff: dict[debt_id, int | None], price_index: list[float]`.

`CashflowSummary` (preview/validate): `ef_target, ef_initial, ef_complete_month, avg_monthly_surplus_first_year,
min_monthly_surplus, negative_surplus_months (first 12), debts_paid_off [{debt_id, month}],
years: [{year, start_month, income, essential, discretionary, debt_payments, one_off_net, surplus}]` (real sums per plan year).

---

## 8. Optimizer (`finance/optimizer.py`): exact formulation

Solver: OR-Tools `pywraplp`, **GLOP** (pure LP) by default; **SCIP** when any class has
`min_monthly_contribution > 0` (8.6). Money is scaled internally by `1/1000` (coefficients near
1..1e5); outputs are rescaled and rounded to 2 decimals.

### 8.1 Sets and data

`G` enabled goals; tier `P(g) in {must, should, nice}`; `A` classes; `A_g` = allowed classes of g;
`Risky` = classes with category equity/gold/other; `Eq` = category equity; `Lock` = classes with
`lock_in_months > 0`, lock `Lk_a`; blocks `k = 0..K_g-1` with start `s_k = kL`, length `n_{g,k}`;
months `t = 0..T-1`, `k(t) = floor(t/L)`; `A_t`, `B0_fixed`, `t_E`, assignable pool items `h` from 7.3
(`free_h`, class, `locked_until_index`); earmarks `em_{g,h}`; bucket classes `BC_g = A_g ∪ {classes of
holdings earmarked to g}` (classes in `BC_g \ A_g` are **sell-only**: no `x`, no `b`) [R7]; `TR_g` (4.8); caps `cap_{g,k}` (5.4); `tau = rebalance_cost_pct/100`;
`m_buf = min_cash_buffer`.

### 8.2 Planning (cautious) returns - `finance/returns.py`

Per goal `g` and class `a`, with caution `z_g` (initially `Phi^-1(p_g)` via `statistics.NormalDist`,
`p_g` = goal minimum success probability), horizon years `Y_g = max(1, D_g/12)`:
`Rplan_{g,a} = max(-0.5, R_a - z_g * sigma_a / sqrt(Y_g))`,
`rho_{g,a} = (1 + Rplan_{g,a})^(1/12)`. Annuity-due factor for `n` months:
`Phi_{g,a}(n) = rho*(rho^n - 1)/(rho - 1)` (or `n` if `rho == 1`).
The approximation treats each class's p-quantile separately (ignores diversification), which is
conservative; Monte Carlo measures the true probability. Cash buffer growth `gamma_c` uses the
expected real return of the cash class (no caution).

### 8.3 Variables (all continuous, `>= 0`)

| Var | Index | Meaning |
|-----|-------|---------|
| `x_{g,a,k}` | `a in A_g`, block k, created only if lock rule holds: `a not in Lock` or `s_k + n_{g,k} - 1 + Lk_a <= D_g`; for `P(g) in {should, nice}` only blocks with `s_k + n_{g,k} > t_E`. If `s_k < t_E < s_k + n_{g,k}` the variable is a level amount paid only in months `[t_E, s_k + n_{g,k})` (`n' = s_k + n_{g,k} - t_E` months); there is **no** extra rebalance point at `t_E` [R6] | level monthly contribution |
| `y_{g,h}` | pool item h whose `locked_until_index <= D_g` (or none), class in `A_g` | amount of existing holding assigned to goal g at t=0 |
| `w_h` | pool item h not locked at t=0 (`locked_until_index` none or 0) | amount of existing holding sold into the cash buffer at t=0 (cost `tau`) [R5] |
| `H_{g,a,k}` | | bucket value right after the rebalance at block start k |
| `b_{g,a,k}`, `u_{g,a,k}` | `u` not created for `a in Lock`; `b` for `a in Lock` only if `s_k + Lk_a <= D_g` | rebalance buy / sell at block start |
| `F_{g,a,k}` | k = 0..K_g | value before rebalance at block start (`F_{g,a,K_g}` = value at D_g) |
| `short_g` | | shortfall vs real target |
| `B_t` | t = 0..T | free cash buffer at start of month |
| `d_t` | t = 0..T-1 | cash deficit slack (tier 0) |
| `c_{g,k}`, `delta_{g,k}` | | block total, abs change (smoothing) |
| `eta_P` | tier | minimax shortfall fraction per tier |

### 8.4 Hard constraints

1. Initial bucket (`a in BC_g`): `F_{g,a,0} = sum_h em_{g,h}[class a] + sum_{h: class a} y_{g,h}`.
2. Pool: `sum_g y_{g,h} + w_h <= free_h` for every pool item; the rest is `unallocated`.
   Cash start: `B_0 = B0_fixed + (1 - tau) * sum_h w_h` (variable).
3. Rebalance: `H_{g,a,k} = F_{g,a,k} + b_{g,a,k} - u_{g,a,k}`;
   `sum_a b_{g,a,k} = (1 - tau) * sum_a u_{g,a,k}`.
4. Locked holdings: `u_{g,a,k} <= F_{g,a,k} - sum_{h locked at s_k, class a} (em_{g,h} + y_{g,h}) * rho_{g,a}^{s_k}`.
5. Growth: `F_{g,a,k+1} = H_{g,a,k} * rho_{g,a}^{n_{g,k}} + x_{g,a,k} * Phi_{g,a}(n^x_{g,k})` with
   `n^x = n'` for a block split at `t_E` (6 above) and `n^x = n_{g,k}` otherwise (contributions in the
   last `n^x` months of a block grow to the block end by exactly `Phi(n^x)`).
6. Goal: `sum_a F_{g,a,K_g} + short_g >= TR_g`.
7. Bucket risk cap (glide): `sum_{a in Risky} H_{g,a,k} <= cap_{g,k} * sum_a H_{g,a,k} + LR_{g,k}`, where
   `LR_{g,k} = sum_{h locked at s_k, class in Risky} (em_{g,h} + y_{g,h}) * rho_{g,a(h)}^{s_k}` is the
   plan-basis value of risky positions that may not be sold yet, plus the value of risky lock-in-class
   positions bought earlier (`sum_{a in Risky ∩ Lock} F_{g,a,k}`) [R8]. Without this allowance a locked
   risky holding near its goal date makes the LP infeasible. The validator uses the same allowance.
8. Contribution risk cap: `sum_{a in Risky} x_{g,a,k} <= cap_{g,k} * sum_a x_{g,a,k}`.
9. Global equity cap (if set), every block k with any goal active (`D_g > s_k`):
   `sum_g sum_{a in Eq} H_{g,a,k} <= maxEq * sum_g sum_a H_{g,a,k} + sum_g LR^{Eq}_{g,k}` (allowance as in 7,
   restricted to equity); same form for each `max_class_pct`.
10. Cash balance, every month t: `X_t = sum_g sum_a x_{g,a,k(t)}` over goals with `D_g > t` (and, for
    split blocks, `t >= t_E`); `B_t + A_t - X_t + d_t >= m_buf`; `B_{t+1} = (B_t + A_t - X_t + d_t) * gamma_c`;
    `B_0` as in 2. The deterministic plan never draws the EF to cover a deficit (by design: the EF is
    for emergencies; planned one-offs must be saved for).
11. Smoothing helpers: `c_{g,k} = sum_a x_{g,a,k}`; `delta_{g,k} >= c_{g,k} - c_{g,k-1}`,
    `delta_{g,k} >= c_{g,k-1} - c_{g,k}` (k >= 1, blocks that both exist).
12. MILP only (8.6): `x_{g,a,k} >= min_a * z_{g,a,k}`, `x_{g,a,k} <= M * z_{g,a,k}`.

"EF before discretionary goals" holds by construction (8.3 `t_E` rule) and is re-checked by the validator.

### 8.5 Objective: preemptive lexicographic tiers

Solved in order; after tier j with optimum `v_j`, add `obj_j <= v_j + max(1e-4, 1e-6*|v_j|)`
(scaled units; 1e-4 scaled = 0.1 currency, above GLOP's feasibility tolerance) and continue. Tiers with
no goals are skipped. If a later tier returns `INFEASIBLE`/`ABNORMAL` (numerical), keep the previous
tier's solution, add diagnostic `TIER_NUMERIC_FALLBACK` and skip the remaining tiers (never `solver_error`
for this reason) [R9].

| Tier | Objective | Purpose |
|------|-----------|---------|
| T0 | `min sum_t d_t` | cash feasibility. `v_0 > 1.0` currency (`> 0.001` scaled) means **cash-infeasible**: with zero contributions and every unlocked holding sold into cash (`w`) the deficit is the same, so this is proven under the model rules; status `infeasible`, solve continues with `sum d <= v_0 + eps` so a plan is still shown |
| T1a / T1b | `min eta_must` s.t. `short_g/TR_g <= eta_must` for must goals; then `min sum_{must} short_g/TR_g` | must goals: fairest, then total |
| T2a / T2b | same for should | |
| T3a / T3b | same for nice | |
| T4 | `min sum_g sum_k delta_{g,k} / TR_g` (fixed afterwards with **5 %** relative tolerance) | SIP-like steady amounts |
| T5 | `min sum_t X_t / gamma_c^t` | maximize free liquid cash: least present-value contribution, no overfunding |

At most 9 solves. Each solve gets `time_limit = remaining run budget`. Status mapping: GLOP/SCIP
`OPTIMAL` -> continue; `FEASIBLE` (MILP gap) -> continue, `optimality_proven = false`;
`NOT_SOLVED`/time limit -> keep the last tier's solution, `termination_reason = "time_limit"`,
feasibility `unknown` unless the validator passes (then `feasible`, unproven); `INFEASIBLE`/`ABNORMAL`
-> `solver_error` (should not happen: `d` and `short` make the model always feasible).
Duals of constraints 10 from the last LP tier (GLOP only) are kept for explanations.
Cancellation inside a solve [R11]: while a solve runs, a watcher (`cancel_event.wait(0.1)` loop on a
helper thread, or the solver's time-limit slices) calls `solver.InterruptSolve()` (supported by GLOP and
SCIP in OR-Tools 9.15) when `cancel_event` is set; the optimizer then raises `FinanceCancelled`.

### 8.6 MILP mode

If any class has `min_monthly_contribution > 0`: binaries `z_{g,a,k}` for those classes,
`M = B0_fixed + sum_h free_h + sum_t max(A_t, 0)` (scaled; a valid bound because the cash buffer can
accumulate savings over many months). Solver SCIP, `relative_gap = 1e-4`. If the number of
binaries > 2000, mins are ignored with diagnostic `MIN_CONTRIBUTION_IGNORED` and GLOP is used.

### 8.7 Size limits

Variables `~ sum_g K_g * (5|A| + 3) + 2T + |pool|*|G|`; with caps (12 goals, 10 classes, 600 months,
50 blocks) about 34 000, constraints about 12 000. `TOO_LARGE` above 60 000 estimated variables.
Target: typical plan (5 goals, 6 classes, 30 years) <= 1 s for all tiers.

### 8.8 Output (`OptimizerSolution`, internal)

`x[g][a][k]`, `y[g][h]`, `F`, `H`, `b`, `u`, `short`, `B`, `d`, tier statuses/objectives/seconds,
`z` per goal, cash duals per month. Post-processing [R10]: each block amount is **floored** to 2 decimals
(never overspends cash; rounding up could accumulate a cash deficit through `B_{t+1}`), amounts that
floor to 0.00 are dropped, and consecutive blocks of the same (g,a) are merged into one
`ContributionLine` only when their floored amounts are **identical**. Lines are therefore the exact
decisions. The pipeline then recomputes `F`/`planned_value_real`/`shortfall_real` from the published
lines with `returns.py` (the same code path the validator uses), so `BUCKET_MISMATCH` can only fire on
a real bug. Display rounding (e.g. to ₹100) is UI-only.

---

## 9. Monte Carlo and scenarios (`finance/simulate.py`)

numpy only, vectorized over paths, `rng = np.random.default_rng(seed)`. The simulator executes the
**plan's policy**, not its outcome: planned real contribution amounts, the plan's rebalance target
weights per goal and block, EF rules, cash priority rules.

### 9.1 Return model

Per class: `s_a = sqrt(ln(1 + (sigma_a/(1+mu_a))^2))`, `m_a = (ln(1 + mu_a - er_a - td_a) - s_a^2/2)/12`,
monthly log return `l_{t,a} = m_a + (s_a/sqrt(12)) * (C eps_t)_a`, `eps ~ N(0, I)`, `C` = Cholesky of
the correlation matrix. If not PSD: eigenvalue clip at 1e-8, rescale diagonal to 1 (warning
`CORRELATION_NOT_PSD`). Inflation: per path and plan year `pi_{p,y} = max(-0.02, pi + sigma_pi * N(0,1))`,
`P_{p,t+1} = P_{p,t} * (1 + pi_{p,y(t)})^(1/12)`.

Draw order (fixed for reproducibility): inflation `(n, Y)`, interruption flags `(n, Y)`, interruption
start offsets `(n, Y)` integers 0..11, then per month `t` a `(n, |A|)` normal block.

Income interruption (if enabled): with probability `q` per path-year a spell starts at the drawn
offset and lasts `duration_months` (may cross years); interruptible incomes are 0 during spells.

### 9.2 Monthly policy per path (nominal)

1. `C = B + S^nom_t` where incomes are nominal (deterministic growth, zeroed in spells),
   inflation-linked expenses = real amount * `P_{p,t}` * item spread, fixed ones nominal, EMIs nominal.
2. If `C < 0`: draw `min(EF, -C)` from EF; if still negative: count a **cash shortfall month**, set `C = 0`.
3. EF build/rebuild: target `EF* * P_{p,t}`; `ef = min(build_share * max(C - m_buf*P, 0), target - EF)`.
4. Rebalance goals whose block starts at t to the plan weights `w_{g,a,k} = H_{g,a,k}/sum_a H` (if the
   plan bucket is 0, skip); lock-in classes are not sold (rebalance the others, renormalized);
   cost `tau * 0.5 * sum|target - current|`.
5. Contributions: planned `x_{g,a,k(t)} * P_{p,t}`. Should/nice only if EF >= target (per path).
   Pay tiers must -> should -> nice from `max(C - m_buf*P, 0)`; within a tier pro rata.
6. Returns: buckets, EF and `B` multiply by `exp(l_{t,a})` of their class.
7. At `D_g`: real value `V = sum_a H_{g,a} / P_{p,D_g}`; success if `V >= TR_g - 1.0`; any excess
   goes to `B` (nominal); the bucket closes.

### 9.3 Outputs

Per goal: `success_probability`, `p10/p50/p90` of real value at `D_g`, `expected_shortfall_real`
(mean of `max(0, TR_g - V)`). Plan: `liquidity_risk_probability` (share of paths with >= 1 cash
shortfall month), monthly total real wealth (goal buckets + EF + B + unallocated holdings) quantiles
p10/p50/p90. Unallocated holdings (7.3 pool remainder) are simulated buy-and-hold in their class.
Defaults: `n_paths = 2000` (100..10000). Cancel checked every 12 months of the loop.
Memory [R19]: per-month quantiles are computed inside the month loop (`np.quantile` over the path axis)
and only the 3 x T result is kept; full path x month matrices are never stored. The run time limit
does not truncate the simulation (bounded by `n_paths` and `T`); it applies to solves and fixes.

### 9.4 Deterministic scenarios

Same simulator with one path, no shocks, interruptions off, fixed annual returns per class:
`low: mu_a - 0.5*sigma_a` with inflation `pi + 1.0pp`; `central: mu_a` at `pi`; `high: mu_a + 0.5*sigma_a`
at `pi - 1.0pp`. The central scenario is the "projected" value shown on goal cards.

---

## 10. Calibration loop and pipeline (`finance/pipeline.py`)

### 10.1 `FinanceRunRequest` (all optional)

```json
{"time_limit_seconds": 30, "seed": 0,
 "simulation": {"n_paths": 2000,
                "income_interruption": {"enabled": false, "annual_probability": 0.05, "duration_months": 3}},
 "calibration_rounds": 2, "compute_fixes": true, "label": null}
```
Ranges: `time_limit_seconds` 5..120, `seed` 0..2^31-1, `n_paths` 100..10000, `annual_probability`
0..0.5, `duration_months` 1..24, `calibration_rounds` 0..4, `label` <= 100 chars.

### 10.2 Steps

1. `preflight` -> `FinancePreflightError` if errors.
2. `project_cashflow` (progress stage `cashflow`).
3. `optimize` with `z_g = Phi^-1(p_g)` (stage `optimize`, progress per tier).
4. `simulate` (stage `simulate`, progress every 12 months) + scenarios.
5. Calibration rounds (stage `calibrate`): goals with `short_g <= 1.0` and probability `< p_g - 0.02`
   get `z_g += 0.25` (max 3.0); re-run 3-4. Accept the round only if total must-tier shortfall did
   not grow by > 1.0; otherwise keep the previous round and stop. Stop early when no goal changed.
6. `validate_result` -> feasibility, decided in this order [R9]: `infeasible` if the T0 deficit > 1.0
   (the validator then also reports `CASH_NEGATIVE`); else `feasible` iff no hard violation; else
   `unknown` (logged as an engine bug). "Feasible" means every hard rule holds; goals may still be
   short (soft), which the UI shows separately ("Plan is valid; 1 goal is short").
7. Explanations and fixes (stage `fixes`, only if `compute_fixes` and time remains).
8. Assemble `FinanceResult`.

`FinanceProgress = {stage, fraction 0..1, message, detail: dict}`; stages `preflight, cashflow,
optimize, simulate, calibrate, validate, fixes`. Cancellation is checked between solves and stages;
it raises `FinanceCancelled` (cancelled runs store **no** result). Cancellation is also honoured
inside solves (8.5) and every 12 simulated months (9.3).

Performance target: young-professional template, 2000 paths, fixes on: < 5 s.

---

## 11. Independent validator (`finance/validator.py`)

Recomputes everything from the plan document and the result's decisions (contribution lines expanded
to months, `holdings_assignment`, `rebalances`, `goals[].planning_z`) using its own projection
(cashflow + returns helpers). Tolerance `tol = max(1.0, 1e-6 * max_g TR_g)`; shares `0.005`; goal
shortfall tolerance `tol_g = max(tol, 0.001 * TR_g)` (same 0.1 % as the `on_track` rule, covers the
flooring of 8.8) [R10]. The cash recomputation starts from `B0_fixed` plus `(1 - tau)` x the
`holdings_assignment` rows with `goal_id == "cash_buffer"` and `source == "sold_to_cash"`. Risk/equity/class caps use
the locked-position allowance of 8.4 rules 7 and 9 [R8].

```python
class FinanceViolation(BaseModel):
    code: str
    severity: Literal["hard", "soft"]
    message: str
    goal_id: str | None = None
    asset_class_id: str | None = None
    months: list[str] = []            # Month strings, maximal runs collapsed to first/last
    amount: float | None = None
    details: dict[str, Any] = {}
```

| code | sev | rule |
|------|-----|------|
| `CASH_NEGATIVE` | hard | `B_t + A_t - X_t < m_buf - tol` (one violation per maximal run of months) |
| `CONTRIBUTION_NEGATIVE` | hard | any amount < 0 |
| `CONTRIBUTION_AFTER_GOAL` | hard | contribution at `t >= D_g` |
| `CLASS_NOT_ALLOWED` | hard | contribution or rebalance buy in a class not in the goal's allowed list (sell-only earmarked classes may only be sold) |
| `LOCKIN_PAST_GOAL` | hard | contribution/buy in lock class with `t + Lk_a > D_g` |
| `LOCKED_SOLD` | hard | sell of a lock class or of a holding before `locked_until_month` |
| `RISK_CAP_EXCEEDED` | hard | bucket risky share after rebalance at a block start > cap + 0.005, or contribution mix > cap + 0.005 |
| `EQUITY_CAP_EXCEEDED` / `CLASS_CAP_EXCEEDED` | hard | global caps at block starts |
| `EF_BEFORE_DISCRETIONARY` | hard | should/nice contribution at `t < t_E` |
| `HOLDING_OVERASSIGNED` | hard | earmarks + assignments of a holding > amount + tol |
| `REBALANCE_UNBALANCED` | hard | `sum buys` differs from `(1-tau) sum sells` by > tol |
| `BUCKET_MISMATCH` | hard | reported plan-basis goal value differs from recomputed by > max(tol, 0.1 %) |
| `GOAL_SHORTFALL` | soft | plan-basis value < `TR_g - tol_g` (amount = shortfall) |
| `GOAL_PROBABILITY_LOW` | soft | success probability < `p_g` |
| `LIQUIDITY_RISK` | soft | `liquidity_risk_probability > 0.10` |

---

## 12. Explanations and fixes (`finance/advisor/`)

All text is produced by `advisor/explain.py` from fixed message templates in `advisor/messages.py`
(single catalog, tested for compliance wording, section 21). Money formatted with the plan currency
(`format_money(amount, currency)`: INR uses the ₹ symbol and lakh/crore grouping, e.g. `₹1,20,000`;
amounts are in today's money unless the sentence says otherwise).

### 12.1 Shapes

```python
class Reason(BaseModel):
    code: str; message: str
    months: list[str] = []; asset_class_ids: list[str] = []; values: dict[str, float | str] = {}
class Fix(BaseModel):
    kind: Literal["DELAY_GOAL","INCREASE_SAVINGS","SPEND_LESS","INCREASE_RISK","REDUCE_TARGET","LOWER_EF_BUILD_SHARE"]
    goal_id: str | None; message: str
    months: int | None = None; amount: float | None = None
    new_target_month: str | None = None; new_risk_tolerance: int | None = None
    resulting_shortfall_real: float | None = None
    resulting_success_probability: float | None = None     # quick MC, 500 paths, same seed
    relative_change: float                                  # see 12.3
    smallest: bool = False                                  # exactly one per goal with fixes
    what_if: WhatIfChanges                                  # ready to POST (section 13)
class GoalExplanation(BaseModel): reasons: list[Reason]; fixes: list[Fix]
class Binding(BaseModel): code: str; message: str; months: list[str] = []; goal_ids: list[str] = []
class Explanation(BaseModel):
    summary: list[str]; goals: dict[str, GoalExplanation]; binding_constraints: list[Binding]
    assumptions: list[str]; limitations: list[str]; replanning_triggers: list[str]
```

### 12.2 Reason codes (goal level) and when they fire

| code | condition | example message |
|------|-----------|-----------------|
| `ALLOCATION_SPLIT` | always (first contribution block) | `Car: ₹9,800/month from 2027-06 to 2030-09 - 35% Diversified equity index fund, 65% Short-term debt fund.` |
| `RISK_CAP` | risky share >= cap - 0.5pp in any block | `Growth assets are capped at 60%: your risk level 3 allows 60% and the goal is 12 years away.` |
| `GLIDE_DOWN` | a rebalance sells risky classes | `From 2034-11 the plan moves ₹4,10,000 from growth assets to safer classes as the goal gets closer (cap 21%).` |
| `LOCKIN_EXCLUDED` | a lock class is allowed but has no var | `Government long lock-in savings is not used: its 180-month lock-in would end after 2031-04.` |
| `EF_GATED` | should/nice goal, `t_E > 0` | `Contributions start in 2027-06, after your emergency fund of ₹1,80,000 is complete.` |
| `CASH_LIMITED` | goal has shortfall and cash constraint is binding (dual > 0 or slack <= tol) in some months before `D_g` | `Your savings are fully used in 14 months before this goal (2027-01 to 2028-02).` |
| `HOLDINGS_USED` | `y` or earmark > 0 | `Uses ₹2,00,000 of your existing Equity investments.` |
| `CAUTIOUS_RETURNS` | always | `Planned with cautious returns: Diversified equity index fund 1.9% a year after inflation instead of the expected 5.0%, so most outcomes beat the plan.` - values from `Rplan` vs `R` |
| `SHORTFALL` | `short_g > tol_g` (11) | `Even using all available cash, the plan reaches ₹6,20,000 of ₹8,00,000 (in today's money).` |
| `LOW_PROBABILITY` | probability < `p_g` | `Estimated chance of reaching the target on time: 62% (you asked for at least 70%).` |
| `ON_TRACK` | status on_track | `On track: estimated 88% chance; in a weak market (low scenario) ₹7,40,000.` |

Plan-level `binding_constraints`: `CASH_DEFICIT` (T0), `CASH_FULLY_USED` (months where cash
constraint binds), `EF_BUILD` (EF build months), `EQUITY_CAP`/`CLASS_CAP` (global caps binding),
`DEBT_PAYOFF` (surplus jumps when a debt ends). `summary` (<= 5 lines): status, monthly investable
now vs contributions now, EF completion, goals on track count, top risk.
`assumptions`: inflation, each used class's expected and cautious return, source note.
`limitations` (fixed list): no taxes computed; no specific products; returns are assumptions;
retirement modelled as a corpus at the retirement month (no withdrawal phase); goals paid only from
their own bucket. `replanning_triggers` (fixed list + computed): income change > 10 %, new debt,
goal change, 12 months elapsed, a goal turning at-risk, debt payoff month.

### 12.3 Fix search (`advisor/fixes.py`)

For at most 3 goals that are not on track (highest priority first, then earliest date). Criterion:
deterministic plan-basis shortfall `<= tol_g` using caution `z_g` (for LOW_PROBABILITY-only goals use
`z_g + 0.5`). All re-solves keep higher-priority tiers' optimal values as constraints **and** keep every
other goal of the same tier at or below its current shortfall (`short_h <= current short_h`), so a fix
for g never just moves the gap to a sibling goal [R13].

| kind | method | relative_change |
|------|--------|-----------------|
| `DELAY_GOAL` | candidates N in {1,2,3,6,9,12,18,24,36,48,60}; first N meeting the criterion; message notes whether N <= `flexibility_months` | `N / max(12, D_g)` |
| `INCREASE_SAVINGS` | one LP: extra variable `e >= 0` added to `A_t` for `t < D_g`, `short_g = 0`, `min e` | `e / max(1, avg positive surplus)` |
| `SPEND_LESS` | emitted only if discretionary monthly total >= `e`; same amount; `what_if = {extra_monthly_savings: e}` with label "Spend ₹e/month less" (same cash effect) | same as above |
| `INCREASE_RISK` | goal tolerance +1..5 per solve, first that meets the criterion (skip if none); `what_if.goal_overrides[{goal_id, risk_tolerance}]` (per goal, not the profile) | `0.2 * levels` |
| `REDUCE_TARGET` | amount = current shortfall (no solve) | `short_g / TR_g` |
| `LOWER_EF_BUILD_SHARE` | only for must goals with `EF_GATED`/cash-limited before `t_E`: try 0.75, 0.5 | `1 - share` |

What-if payloads of fixes are exact: `DELAY_GOAL` -> `goal_overrides[{goal_id, target_month}]`,
`INCREASE_SAVINGS` -> `extra_monthly_savings = ceil(e)`, `REDUCE_TARGET` -> `goal_overrides[{goal_id,
target_amount}]`, `LOWER_EF_BUILD_SHARE` -> `emergency_build_share`. Guarantee (tested): re-running the
pipeline on `apply_what_if(plan, fix.what_if)` with `calibration_rounds = 0` and the same `z` reduces the
goal's plan-basis shortfall to `<= tol_g` when g is the only short goal of its tier; otherwise it does
not increase it.
`smallest = true` on the minimal `relative_change` (ties: list order). Budget: min(10 s, remaining
time), at most 30 solves; skipped fixes are omitted, diagnostic `FIXES_TRUNCATED`.

---

## 13. What-if (`finance/whatif.py`) and comparison (`finance/compare.py`)

```python
class GoalOverride(BaseModel):
    goal_id: Id; target_month: Month | None = None; target_amount: Money | None = None
    priority: Priority | None = None; enabled: bool | None = None
    risk_tolerance: int | None = None            # 1..5, replaces goal.risk_tolerance [R13]
class IncomeDrop(BaseModel):
    start_month: Month; months: int = Field(ge=1, le=24); percent: float = Field(gt=0, le=100)
class WhatIfChanges(BaseModel):
    label: str | None = None                     # <= 100
    extra_monthly_savings: float = 0.0           # real, -1e9..1e9
    goal_overrides: list[GoalOverride] = []
    risk_tolerance: int | None = None            # 1..5
    return_shift_pct: float = 0.0                # -10..10, added to every non-cash class expected return
    inflation_pct: float | None = None
    income_drop: IncomeDrop | None = None
    emergency_build_share: float | None = None   # 0.1..1
```

`apply_what_if(plan, changes)` (pure, deterministic, returns a new validated plan):
- `extra_monthly_savings > 0`: add income `whatif_extra` (monthly, amount = value, `growth_pct = inflation_pct`
  so it stays constant in real terms, not interruptible). `< 0`: add expense `whatif_less` (discretionary,
  inflation-linked, amount = -value).
- Goal overrides patch fields; `enabled=false` disables the goal (earmarks then return to the pool).
  Unknown `goal_id` -> `ValueError` (API 422 `VALIDATION_ERROR`).
- `risk_tolerance` replaces `profile.risk_tolerance` (goal overrides untouched).
- `return_shift_pct`, `inflation_pct`, `emergency_build_share` replace/shift assumptions.
- `income_drop`: add essential, non-linked expense `whatif_income_drop`, monthly from `start_month`
  for `months`, amount = `percent/100 *` sum of nominal monthly-equivalent interruptible incomes in
  `start_month`. It does not change the EF target (7.3). The UI sends `income_drop: null` when its
  months control is 0 [R15].
- Base document [R14]: the API applies the changes to the snapshot of `base_result_id` when given (so the
  comparison with that baseline isolates the what-if effect even if the plan was edited since), else to
  the current stored document.
Default label (if none): joined short phrases, e.g. `"+₹10,000/month, Car 2031-06"`.

`FinanceComparison` (`compare_results(a, b)`; deltas are `b - a`):
```json
{"a": FinanceResultSummary, "b": FinanceResultSummary,
 "totals": {"monthly_contribution_now_a": 21000.0, "monthly_contribution_now_b": 31000.0, "monthly_contribution_now_delta": 10000.0,
            "ef_complete_month_a": "2027-05", "ef_complete_month_b": "2027-03",
            "goals_on_track_a": 2, "goals_on_track_b": 3, "liquidity_risk_a": 0.03, "liquidity_risk_b": 0.02},
 "goals": [{"goal_id": "car", "name": "Car", "in_a": true, "in_b": true,
            "target_month_a": "2030-10", "target_month_b": "2030-10",
            "success_a": 0.62, "success_b": 0.81, "success_delta": 0.19,
            "p50_a": 790000.0, "p50_b": 860000.0, "p50_delta": 70000.0,
            "shortfall_a": 0.0, "shortfall_b": 0.0,
            "monthly_now_a": 9800.0, "monthly_now_b": 12400.0,
            "status_a": "at_risk", "status_b": "on_track"}],
 "what_if_b": WhatIfChanges | null}
```
Goals are the union by id, ordered as in b then a; missing side fields `null`.

---

## 14. Result model (`FinanceResult`)

```json
{"engine_version": "fin-0.1.0", "disclaimer": "...", "disclaimer_version": "fin-disclaimer-1",
 "start_month": "2026-11", "horizon_months": 408, "end_month": "2060-10", "currency": "INR",
 "feasibility": "feasible", "termination_reason": "optimal", "optimality_proven": true,
 "summary": {"goals_total": 3, "goals_on_track": 2, "goals_at_risk": 1, "goals_off_track": 0,
             "monthly_investable_now": 25000.0, "monthly_contribution_now": 21000.0,
             "emergency_fund_target": 180000.0, "emergency_fund_now": 50000.0,
             "emergency_fund_complete_month": "2027-05", "liquidity_risk_probability": 0.03,
             "total_contributions_real": 9120000.0},
 "goals": [{"goal_id": "car", "name": "Car", "kind": "vehicle", "priority": "should",
            "target_month": "2030-10", "months_to_goal": 47, "target_amount": 800000.0,
            "target_real": 800000.0, "target_nominal_expected": 1004000.0,
            "planned_value_real": 800000.0, "projected_central_real": 861000.0,
            "shortfall_real": 0.0, "shortfall_fraction": 0.0,
            "success_probability": 0.74, "min_success_probability": 0.7,
            "p10_real": 712000.0, "p50_real": 852000.0, "p90_real": 1010000.0,
            "expected_shortfall_real": 21000.0, "scenario_low_real": 744000.0, "scenario_high_real": 952000.0,
            "status": "on_track", "contribution_start_month": "2027-06", "contribution_end_month": "2030-09",
            "monthly_contribution_now": 0.0, "total_contributions_real": 452000.0, "holdings_used_real": 0.0,
            "allocation_now_pct": {"equity_index": 35.0, "short_debt": 65.0}, "planning_z": 0.52}],
 "contributions": [{"goal_id": "car", "asset_class_id": "equity_index", "start_month": "2027-06",
                    "end_month": "2028-10", "monthly_amount_real": 3430.0,
                    "monthly_amount_nominal_start": 3690.0, "monthly_amount_nominal_end": 3880.0}],
 "holdings_assignment": [{"holding_id": "h1", "goal_id": "emergency_fund", "amount": 50000.0, "source": "initial_ef"}],
 "rebalances": [{"month": "2029-11", "goal_id": "car", "sells": {"equity_index": 120000.0},
                 "buys": {"short_debt": 119880.0}}],
 "glide_paths": {"car": [{"month": "2027-11", "months_to_goal": 35, "risky_cap_pct": 21.0,
                          "risky_share_pct": 21.0, "weights_pct": {"equity_index": 21.0, "short_debt": 79.0}}]},
 "series": {"months": ["2026-11", "..."], "corpus_by_class": {"equity_index": [0.0, "..."]},
            "emergency_fund": [], "cash_buffer": [], "unallocated": [], "goal_withdrawals": [],
            "total_p10": [], "total_p50": [], "total_p90": []},
 "cashflow": {"months": [], "income": [], "essential": [], "discretionary": [], "debt_payments": [],
              "one_off_net": [], "surplus": [], "emergency_fund_contribution": [],
              "goal_contribution": [], "cash_buffer_end": []},
 "scenarios": {"definitions": {"low": "returns -0.5 x volatility, inflation +1pp", "central": "expected returns",
                               "high": "returns +0.5 x volatility, inflation -1pp"},
               "goals": {"car": {"low": 744000.0, "central": 861000.0, "high": 952000.0}}},
 "explanation": {"summary": [], "goals": {}, "binding_constraints": [], "assumptions": [],
                 "limitations": [], "replanning_triggers": []},
 "violations": [],
 "assumptions_used": {"inflation_pct": 6.0, "asset_classes": [], "glide_path": [], "risky_cap_by_tolerance_pct": [],
                      "planning_returns_pct": {"car": {"equity_index": 1.9, "short_debt": 0.6}}},
 "simulation_settings": {"n_paths": 2000, "seed": 0, "income_interruption": {"enabled": false, "annual_probability": 0.05, "duration_months": 3}},
 "diagnostics": {"solver": "GLOP", "variables": 2140, "constraints": 1210,
                 "tiers": [{"tier": "T0", "status": "OPTIMAL", "objective": 0.0, "seconds": 0.02}],
                 "calibration_rounds": 1, "simulation_seconds": 0.8, "fix_solves": 6, "warnings": []}}
```

Rules: all `series`/`cashflow` arrays have length `horizon_months`, real terms, 2-decimal rounding.
`corpus_by_class` = central-scenario sum over goal buckets per class; EF, cash buffer and unallocated
holdings are separate series. The corpus chart stacks `corpus_by_class` + `emergency_fund` +
`cash_buffer` + `unallocated`, which is the same quantity as `total_p10/p50/p90` (9.3), so the band and
the stack are comparable [R20].
`holdings_assignment[].source` in `earmark | assigned | initial_ef | initial_cash | sold_to_cash | unallocated`;
rows partition every holding exactly (sum per holding == amount) [R26].
`goal_id` in contributions may be `"emergency_fund"` (EF lines from 7.3, class = EF class).
`holdings_assignment.goal_id` in goal ids or `"emergency_fund" | "cash_buffer" | "unallocated"`.
Status rule per goal: `on_track` iff `shortfall_fraction <= 0.001` and `success_probability >= min`;
`at_risk` iff not on track and (`success_probability >= min - 0.20` or `shortfall_fraction <= 0.10`);
else `off_track`. `monthly_contribution_now` = contribution in month 0.
`FinanceResultSummary` = `{id, plan_id, run_id, plan_version_id, base_plan_version, kind ("baseline"|"what_if"),
label, feasibility, goals_total, goals_on_track, goals_at_risk, goals_off_track,
monthly_contribution_now, created_at, what_if}`.

---

## 15. Templates (`finance/templates.py`)

```python
class FinanceTemplateParameter(BaseModel):
    name: str; label: str; type: Literal["int", "money", "month_offset_years"]
    default: float; min: float | None = None; max: float | None = None; help: str = ""
class FinanceTemplate(Protocol):
    id: str; name: str; description: str; parameters: list[FinanceTemplateParameter]
    def build(self, *, name: str, start_month: str, params: dict[str, float]) -> FinancePlan: ...
```
Rules (as A.12): deterministic, relative to `start_month`, unknown params -> `ValueError` (422),
missing -> defaults; at defaults every template passes preflight with **no errors** and runs
`feasible` (tested). Asset classes = defaults (5.1). Ids are short ASCII (`salary`, `rent`, `car`...).
Retirement target preset everywhere: `25 x annual (essential + discretionary) expenses at plan start`.

| id | params (default, range) | content |
|----|-------------------------|---------|
| `young_professional` | `age` 24 (18..40), `take_home` 60000 (10000..1e7), `essentials` 25000, `discretionary` 10000, `car_price` 600000, `car_in_years` 4 (1..15), `retirement_age` 60 (45..70) | salary growth 8 %; risk 4; holding `h_cash` cash 50000; EF 6 months; goals: `car` should, flex 12; `retirement` must at `start + (retirement_age-age)` years |
| `family` | `age` 35 (25..55), `take_home` 150000, `essentials` 70000, `discretionary` 20000, `home_down_payment` 1500000, `home_in_years` 3 (1..10), `education_cost` 2500000, `education_in_years` 15 (3..20), `retirement_age` 60 | salary growth 6 %; risk 3; holdings `h_cash` cash 200000, `h_eq` equity_index 500000, `h_ppf` govt_long 300000 locked 10 years; debt `car_loan` 300000 @ 9 % EMI 10000; expense `school_fees` essential yearly 60000 (inflation 9 %); goals: `home` must flex 6, `education` must (inflation 9 %, earmark `h_ppf` 300000), `retirement` must |
| `near_retirement` | `age` 52 (45..65), `take_home` 200000, `essentials` 80000, `discretionary` 30000, `retirement_age` 60, `wedding_cost` 1000000, `wedding_in_years` 3 | salary growth 4 %; risk 2; EF 9 months; holdings cash 500000, equity_index 4000000, short_debt 2000000, govt_long 1500000 (locked 3 years); goals: `retirement` must, `wedding` nice flex 12 |
| `blank` | none | profile defaults, no items; used by "Start from scratch" |

---

## 16. Send to planner (`finance/bridge.py`) and CSV export (`finance/export.py`)

### 16.1 `to_planner_problem`

Creates a regular SuperPlanner `Problem` (A.3) for the next `months` (1..12) starting at the
result's `start_month`, so it respects `horizon_days <= 366`:
- `horizon_start` = first day of `start_month` 00:00 at `utc_offset`; `horizon_days` = days until
  the same day `months` later (<= 366). `domain = "personal_finance"`, `currency` = plan currency,
  `terminology = {task: "Action", tasks: "Actions", resource: "Person", resources: "People",
  group: "Goal", milestone: "Milestone", schedule: "Money calendar", deadline: "Due date"}`.
- Resource `YOU` ("You", kind `person`, capacity 1, calendar `weekly` with **all seven days**
  `mon..sun` = `[["09:00","21:00"]]`, so every 1st-5th window has capacity).
- Tasks (ids ASCII, deterministic; every activity has `requirements = [{"alternatives": ["YOU"], "units": 1}]`;
  `group` = goal name (truncated to 200) or "Emergency fund"/"Reviews"; priority must 9, should 6, nice 3,
  EF 9, reviews 5; `deadline_hard = false`). Task ids use **indices**, not user ids, because the
  scheduler `Id` is limited to 64 characters: `<goal>` = `g<i>` (index in `plan.goals`, EF = `ef`),
  `<class>` = `a<j>` (index in `assumptions.asset_classes`) [R16]:

| Task | id | type | timing |
|------|----|------|--------|
| Start or change a monthly contribution (each ContributionLine start, and each amount change at a block boundary) | `C-<goal>-<class>-<YYYYMM>` | activity 30 min | earliest = 1st 09:00, soft deadline = 5th 21:00 |
| Stop a contribution (month after `end_month`) | `S-<goal>-<class>-<YYYYMM>` | activity 15 min | same |
| Rebalance (if `include_rebalances`) | `R-<goal>-<YYYYMM>` | activity 60 min | earliest 1st, soft deadline 10th |
| Periodic review every `review_every_months` (1..12, default 3), first at month `review_every_months` | `REV-<YYYYMM>` | activity 60 min | earliest 1st, soft deadline 7th |
| Goal due (target month in window) | `G-<goal>` | milestone | earliest = 1st 09:00 |
| Emergency fund complete (if `t_E` in window) | `EF-DONE` | milestone | earliest = 1st 09:00 |

Names e.g. `Start ₹3,430/month into Diversified equity index fund for "Car"` (today's money,
plus expected nominal in `description`), truncated to 200 characters with "..." (scheduler `name`
limit) [R16]. `metadata.finance = {goal_id, asset_class_id, month,
monthly_amount_real}`. No dependencies. Tasks whose earliest start is outside the horizon are
skipped and counted (`skipped`). The output must pass `engine.preflight` with no errors (tested).
`problem.metadata = {"source": "finance", "finance_plan_id", "finance_result_id"}`.
Returns `(problem, skipped)`.

### 16.2 CSV `contributions_csv`

First line `# <DISCLAIMER>` (parsers skip lines starting with `#`), then RFC 4180 header:
`month,action,goal_id,goal_name,priority,asset_class_id,asset_class_name,amount_today_money,amount_expected_nominal`
(text cells - ids and names - are neutralised against spreadsheet formula injection with the same rule
as the existing `schedule_service.csv_text`: prefix `'` when starting with `= + - @ TAB CR`; `export.py`
re-implements the 3-line rule because the finance package may not import `superplanner.api`) [R18]
`action in {contribute, emergency_fund, rebalance_sell, rebalance_buy, goal_withdrawal}`. One row per
month per (goal, class) with amount >= 1.0; `goal_withdrawal` rows use the central projection.
Sorted by month, then action order above, then goal order in the plan, then class order. Amounts 2 decimals.

---

## 17. Persistence (`backend/superplanner/api/finance/db_models.py`)

Tables live on the shared `api.db.models.Base` (so `create_all` creates them), same column
conventions as A.13. ID prefixes: `fp_`, `fpv_`, `frun_`, `fres_`.

| Table | Columns | Notes |
|-------|---------|-------|
| `finance_plans` | `id` PK, `name`, `template_id` null, `version` int (1..), `document` JSON, `created_at`, `updated_at` | name copied from document on every write |
| `finance_plan_versions` | `id` PK, `plan_id` FK cascade, `base_version` int, `kind` (`snapshot`\|`what_if`), `content_hash` str(64) (canonical JSON sha256 as A.13), `document` JSON, `created_at` | immutable; `snapshot` reused on identical `(plan_id, kind, content_hash, base_version)`; `what_if` never reused; index `(plan_id, content_hash)` |
| `finance_runs` | `id` PK, `plan_id` FK cascade, `plan_version_id` FK, `kind` (`baseline`\|`what_if`), `label` str null, `status` (`queued`\|`running`\|`completed`\|`failed`\|`cancelled`), `request` JSON (fully defaulted), `what_if` JSON null, `seed` int, `engine_version`, `feasibility` null, `error` text null, `cancel_requested` bool, `created_at`, `started_at` null, `finished_at` null | index `(plan_id, created_at)`, `(status)` |
| `finance_run_events` | `id` autoinc PK, `run_id` FK cascade, `seq`, `type`, `payload` JSON, `created_at` | unique `(run_id, seq)` |
| `finance_results` | `id` PK, `plan_id` FK cascade, `plan_version_id` FK, `run_id` FK cascade, `kind`, `label`, `feasibility`, `summary` JSON (`FinanceResultSummary` minus ids), `result` JSON (`FinanceResult`), `created_at` | index `(plan_id, created_at)`; immutable |

Audit (existing `audit_events`, action names follow the existing `<entity>.<verb>` style): `entity_type`
`finance_plan` (`finance_plan.created/updated/deleted/imported`), `finance_run` (`finance_run.created/cancelled`),
`finance_result` (`finance_result.sent_to_planner`, details `{problem_id}`) [R17]. All finance FKs use
`ondelete="CASCADE"` like A.13.
Audit details and logs never contain money amounts (ids and counts only).
Rules: snapshot before queuing (A.13 rule 1); If-Match on PUT; delete with active run -> 409;
check-then-write under `WRITE_LOCK` + one transaction; startup recovery marks `queued`/`running`
finance runs `failed` with `"Server restarted before the run finished."` and a `run_failed` event.

---

## 18. REST API (`/api/v1/finance`)

Conventions exactly as A.14 (error envelope, 422 `VALIDATION_ERROR`, If-Match `"3"`/`3`/`W/"3"`,
`{"items": [...]}` max 500 newest first, UTC `Z` timestamps). Fixed paths before parameterized ones:
`/finance/plans/import` before `/finance/plans/{id}`, `/finance/results/compare` before
`/finance/results/{id}`.

### 18.1 Shapes

`FinancePlanRecord`:
```json
{"id": "fp_1a2b", "version": 3, "template_id": "young_professional",
 "created_at": "2026-10-16T09:00:00Z", "updated_at": "2026-10-16T09:10:00Z",
 "plan": {"...": "FinancePlan, plan.id == id, start_month filled"}}
```
`FinancePlanSummary`:
```json
{"id": "fp_1a2b", "name": "My plan", "version": 3, "currency": "INR", "goal_count": 2,
 "template_id": "young_professional", "updated_at": "2026-10-16T09:10:00Z",
 "latest_run": {"id": "frun_9c", "status": "completed"},
 "latest_result": {"id": "fres_77", "feasibility": "feasible", "goals_on_track": 1, "goals_total": 2}}
```
`FinanceRun`:
```json
{"id": "frun_9c", "plan_id": "fp_1a2b", "plan_version_id": "fpv_3d", "kind": "baseline", "label": null,
 "status": "completed", "request": {"time_limit_seconds": 30, "...": "..."}, "what_if": null,
 "engine_version": "fin-0.1.0", "feasibility": "feasible", "result_id": "fres_77", "error": null,
 "cancel_requested": false, "created_at": "...Z", "started_at": "...Z", "finished_at": "...Z", "elapsed_seconds": 2.4}
```
`FinanceResultRecord` = `FinanceResultSummary` (section 14) + `{"result": FinanceResult, "plan": FinancePlan}`
(`plan` = the snapshot document the result was computed from).
`RunCreated` (202): `{"run_id", "status": "queued", "plan_version_id", "status_url": "/api/v1/finance/runs/<id>", "events_url": "/api/v1/finance/runs/<id>/events"}`.

### 18.2 Endpoints

| Method | Path | Request | Success | Errors |
|--------|------|---------|---------|--------|
| GET | `/finance/defaults` | - | 200 `{"plan": FinancePlan (default_plan, start_month = current UTC month), "disclaimer", "disclaimer_version", "limits": {"goals": 12, "incomes": 20, "expenses": 100, "debts": 20, "holdings": 50, "one_offs": 200, "asset_classes": 10, "horizon_months": 600}}` | |
| GET | `/finance/templates` | - | 200 `{"items": [{"id","name","description","parameters":[FinanceTemplateParameter]}]}` | |
| POST | `/finance/templates/{tid}/instantiate` | `{"name"?: str, "start_month"?: Month, "parameters"?: {}}` | 201 `FinancePlanRecord`, `ETag: "1"`, `Location` | 404, 422 |
| GET | `/finance/plans` | - | 200 `{"items": [FinancePlanSummary]}` by `updated_at` desc | |
| POST | `/finance/plans` | `FinancePlan` | 201 record, `ETag: "1"` | 422 |
| GET | `/finance/plans/{id}` | - | 200 record, `ETag` | 404 |
| PUT | `/finance/plans/{id}` | `FinancePlan`, `If-Match` | 200 record (version+1) | 404, 412 `VERSION_MISMATCH` (`details.current_version`), 428, 422 |
| DELETE | `/finance/plans/{id}` | - | 204 | 404, 409 `RUN_ACTIVE` |
| GET | `/finance/plans/{id}/export` | - | 200 `{"format": "superplanner.finance_plan", "format_version": 1, "exported_at", "plan"}`, `Content-Disposition: attachment; filename="<slug>.finance.json"` | 404 |
| POST | `/finance/plans/import` | export file | 201 record (new id) | 422 |
| POST | `/finance/preview` | `FinancePlan` (unsaved; null `start_month` filled with the current UTC month) | 200 `{"ok", "issues": [FinanceIssue], "cashflow": CashflowSummary \| null}` (`cashflow` null if errors) | 422 model |
| POST | `/finance/plans/{id}/validate` | - | 200 `{"plan_version": 3, "ok", "issues", "cashflow": CashflowSummary \| null}` | 404 |
| POST | `/finance/plans/{id}/runs` | `FinanceRunRequest` (optional body) | 202 `RunCreated` | 404; 422 `PREFLIGHT_FAILED` (`details.issues`); 422 `VALIDATION_ERROR`; 409 `RUN_ALREADY_ACTIVE` (`details.run_id`) |
| POST | `/finance/plans/{id}/what-if` | `{"changes": WhatIfChanges, "run"?: FinanceRunRequest, "replace_active"?: false, "expected_plan_version"?: int, "base_result_id"?: str}` | 202 `RunCreated` | 404 (plan, or `base_result_id` not a result of this plan); 412 if `expected_plan_version` stale; 422 (bad changes / preflight of derived plan); 409 `RUN_ALREADY_ACTIVE` |
| GET | `/finance/plans/{id}/runs` | - | 200 `{"items": [FinanceRun]}` | 404 |
| GET | `/finance/runs/{run_id}` | - | 200 `FinanceRun` | 404 |
| POST | `/finance/runs/{run_id}/cancel` | - | 202 `{"run_id", "status": "cancelled"\|"running", "cancel_requested": true}` | 404, 409 `RUN_NOT_ACTIVE` |
| GET | `/finance/runs/{run_id}/events` | `Last-Event-ID` / `?after=` / `?stream=false` | SSE (section 19) or 200 `{"items": [event]}`; 204 for terminal run with nothing new | 404 |
| GET | `/finance/plans/{id}/results` | `?kind=baseline\|what_if` | 200 `{"items": [FinanceResultSummary]}` | 404 |
| GET | `/finance/results/compare?a=&b=` | - | 200 `FinanceComparison` | 404, 422 missing params |
| GET | `/finance/results/{rid}` | - | 200 `FinanceResultRecord` | 404 |
| GET | `/finance/results/{rid}/contributions.csv` | - | 200 `text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="<plan-slug>-<rid>-contributions.csv"` | 404 |
| POST | `/finance/results/{rid}/send-to-planner` | `{"name"?: str, "months"?: 12, "utc_offset"?: "+00:00", "review_every_months"?: 3, "include_rebalances"?: true}` | 201 `{"problem_id", "record": ProblemRecord (A.14.3), "task_count", "skipped", "url": "/plans/<id>/tasks"}`, `Location: /api/v1/problems/<id>` | 404; 422 `NOT_FEASIBLE` if result feasibility != feasible; 422 validation |

Semantics:
- One active run per plan (`status in (queued, running)` and `cancel_requested = false`). For what-if
  with `replace_active = true`, an active **what-if** run is cancelled first (same transaction) and the
  new run queued; an active baseline run still gives 409. `executor.cancel(old_run_id)` is called after
  the commit (as A.16). Delete returns 409 `RUN_ACTIVE` under the same definition; a cancel-requested run
  still executing is deleted by the cascade and its worker discards its output.
- Cancel and the final write [R11]: cancelling a `queued` run sets `cancelled` + `run_cancelled`
  immediately (the worker then never starts it). The worker's final transaction (under `WRITE_LOCK`)
  re-reads the run: row gone -> return; `cancel_requested` true -> `cancelled`, **no result row**, even if
  `run_plan` already returned a result; otherwise write the result + `completed` + `run_completed` in that
  same transaction. So a cancelled run never exposes a result, and a completed run always has exactly one.
- What-if: derived plan = `apply_what_if(current document, changes)`; snapshot `kind="what_if"`; the
  editable plan is not changed. "Apply" in the UI = client applies the same changes to its draft and PUTs.
- Default request for what-if runs: `n_paths 1000`, `compute_fixes false`, `calibration_rounds 1`
  (explicit `run` fields override).
- Worker (`api/finance/run_service.py`) mirrors A.16: own session, `running` + `run_started`, load
  snapshot, call `finance.run_plan(plan, request, progress_cb, cancel_event)` on the shared
  `ctx.executor` (run ids `frun_*` cannot collide), write result + run summary + terminal event in one
  transaction. `FinanceCancelled` -> `cancelled`, no result. Exceptions -> `failed`, message only.
  The pool is shared with scheduling runs (`RUN_WORKERS`, default 2): a long scheduling run can delay a
  finance run (it stays `queued`); accepted for the MVP, no separate pool.
- `send-to-planner` (`api/finance/planner_link.py`) reads the result in a read session, builds the problem
  with `finance.to_planner_problem`, then calls `problem_service.create_problem(ctx, problem)` (existing
  public service; it opens its own write transaction, so it must **not** be called inside a finance write
  session), then writes the `finance_result.sent_to_planner` audit row in a second transaction. The new
  plan appears on the scheduling home page.

---

## 19. Progress events (SSE)

Endpoint and framing identical to A.15 (`id`, `event`, `data`; replay by `Last-Event-ID`/`after`;
DB polling 0.5 s; keepalive 15 s; close after terminal; 204 for finished runs; `progress` throttled to
2/s, latest flushed before `stage_completed`). Common fields `run_id, seq, type, ts, elapsed_seconds`.

| type | extra fields | when |
|------|--------------|------|
| `run_queued` | `plan_version_id`, `kind` | created |
| `run_started` | - | worker begins |
| `stage_started` | `stage`, `message` | each stage of 10.2 |
| `progress` | `stage`, `fraction`, `message`, `detail` (`{"tier": "T2a"}`, `{"paths": 2000, "month": 120}`, `{"round": 1}`) | throttled |
| `stage_completed` | `stage`, `seconds` | each stage |
| `run_completed` | `result_id`, `feasibility`, `goals_on_track`, `goals_total` | terminal |
| `run_cancelled` | - | terminal |
| `run_failed` | `error` | terminal |

---

## 20. Frontend (`frontend/src/finance/**`)

No new npm dependencies. Charts are hand-written SVG. Styles in `finance/finance.css` (imported by
`finance/routes.tsx`) using the existing CSS variables, plus chart palette `--fin-c1..--fin-c8`,
`--fin-band` defined for `:root` and `:root[data-theme="dark"]`.

### 20.1 Routes (children of the existing `App` layout)

| Path | Screen |
|------|--------|
| `/finance` | `FinanceHome`: plan list, template cards, "Start from scratch" (instantiates `blank`), import |
| `/finance/:planId` | redirect: to `results` if a result exists, else `setup/profile` |
| `/finance/:planId/setup/:step` | `WizardPage`, step in `profile, income, debts, savings, goals, assumptions, review` |
| `/finance/:planId/results` | `ResultsPage` (`?result=<id>`; `?run=<id>` shows live progress, then the result) |
| `/finance/:planId/what-if` | `WhatIfPage` (sliders; baseline = latest baseline result) |
| `/finance/:planId/compare` | `ComparePage` (`?a=&b=`) |
| `/finance/*` | NotFound |

Top bar (edit in `App.tsx`): `<nav aria-label="Main">` with links "Scheduling" (`/`,
`data-testid="nav-scheduling"`) and "Finance" (`/finance`, `data-testid="nav-finance"`). Active state
(`aria-current="page"`): Finance iff the path starts with `/finance`, Scheduling otherwise (every path
starts with `/`, so a plain prefix test would mark both). The scheduling UI is otherwise unchanged; the
existing e2e selectors (`navigation` "Plan sections", `theme-toggle`, brand link) must keep matching.

### 20.2 Files

```
frontend/src/finance/
  routes.tsx                    # export const financeRoutes: RouteObject[] (+ imports finance.css)
  finance.css
  api/types.ts                  # TS mirrors of sections 4, 6, 7, 10.1, 12-14, 18, 19
  api/client.ts                 # typed wrappers for every 18.2 endpoint. `src/api/client.ts` exports only
                                #   `ApiError`, `API_BASE`, `parseEtag`, `errorMessage`, `isAbort` (its `raw`/`request`
                                #   are private): import those, and implement a local `finRaw`/`finRequest` with the same
                                #   envelope parsing. Do not edit `src/api/**` [R21]
  api/sse.ts                    # subscribeFinanceRunEvents (same algorithm as src/api/sse.ts, finance event types)
  api/contractExamples.ts       # JSON examples of 14, 18, 19 typed against types.ts
  state/FinancePlanContext.tsx  # record, draft, dirty, saveState, update, save, reload (same rules as A.17.3: debounce 1.5 s, If-Match, 412 banner)
  lib/money.ts                  # formatMoney(amount, currency, locale, {compact}); INR lakh/crore compact ("₹12.5 L", "₹1.2 Cr")
  lib/months.ts                 # Month arithmetic, "in N years" <-> Month
  lib/ids.ts                    # next free id per list (inc1, exp1, debt1, h1, goal1, oo1)
  pages/FinanceHome.tsx  pages/WizardPage.tsx  pages/ResultsPage.tsx  pages/WhatIfPage.tsx  pages/ComparePage.tsx
  wizard/Stepper.tsx            # step list with done/current/issue marks; Back/Next/Skip
  wizard/ProfileStep.tsx  IncomeExpenseStep.tsx  DebtsStep.tsx  SavingsStep.tsx  GoalsStep.tsx
  wizard/AssumptionsStep.tsx  ReviewStep.tsx  HelpText.tsx  ListEditor.tsx (generic add/remove/edit rows)
  components/DisclaimerBanner.tsx  GoalCard.tsx  StatusPill.tsx  ContributionTable.tsx  ExplanationPanel.tsx
  components/FixList.tsx  FinRunProgress.tsx  ResultHeader.tsx  SendToPlannerDialog.tsx  RealNominalToggle.tsx
  components/AssetClassTable.tsx  WhatIfControls.tsx  ScenarioCompareTable.tsx  FinanceResultHistory.tsx
  charts/scales.ts              # linear/time scales, nice ticks, month axis
  charts/StackedAreaChart.tsx   # corpus by class + p10-p90 band + p50 line
  charts/LineChart.tsx          # glide path: cap (dashed) vs planned risky share, per goal selector
  charts/CashflowChart.tsx      # stacked bars per year (income vs outflows), surplus line, one-off markers
  charts/ChartTooltip.tsx  charts/Legend.tsx
```

### 20.3 Wizard (each step: plain-language help, defaults prefilled, "Skip - use defaults")

| Step | Edits | Help / defaults |
|------|-------|-----------------|
| profile ("Profile") | name, currency, age, start month, plan horizon (`horizon_end_month`, optional "plan until"), tax note | "Use take-home amounts; taxes are not calculated." Notice + "Move to this month" button when the start month is before the current month [R22] |
| income ("Income & expenses") | incomes, expenses (essential toggle, inflation-linked), one-offs (collapsible "Known future expenses or windfalls") | live "You can invest about ₹X/month" from `POST /finance/preview` (debounced 800 ms) |
| debts ("Debts") | debts | shows payoff month from preview |
| savings ("Savings & holdings") | holdings, EF months + class | "Your emergency fund target is ₹X (6 months of essentials + EMIs)." |
| goals ("Goals") | goals with presets (Retirement, Child education 9 % inflation, Home down payment, Car, Travel, Wedding, Other); target "in N years" or month; priority; flexibility; earmarks | priority meaning explained |
| assumptions ("Risk & assumptions") | risk tolerance (5 described levels), inflation, asset class table (with a read-only "after costs and inflation" real-return column computed by 3's formula), constraints, glide path (under "Expert") | "These are illustrative assumptions, not forecasts." Reset to defaults button |
| review ("Review") | summary, preflight issues (`/validate`, each linking to its step/field), cash-flow preview, "Build my plan" | button disabled while errors; saves, POSTs run, navigates `results?run=` |

Steps never block: Next saves and advances even with warnings; errors show only on review.
`metadata.wizard.completed_steps` updated by Next. New list rows are created with valid defaults
(amount 0, goal from a preset with a target month 5 years out) so the draft always passes the model
layer. Saves are single-flight [R23]: Next and "Build my plan" await any in-flight autosave, then save
with the latest version; two PUTs with the same If-Match are never in flight together.

### 20.4 Results dashboard

Order: `DisclaimerBanner` (always, not dismissible on results; compact elsewhere), `ResultHeader`
(feasibility pill, label, "made for version N" notice if stale, actions: What-if, Compare, Export CSV,
Send to planner, Re-run), summary KPIs (investable now, contributing now, EF target/complete month,
liquidity risk), goal cards (success % as bar with text, status pill text+icon, target, p10-p90,
monthly now, start/stop months), corpus stacked area, contribution table (rows goal x class, columns =
next 24 months then yearly; toggle today's money / expected future), glide-path chart, cash-flow chart,
explanation panel (summary, per-goal reasons, binding constraints, assumptions, limitations, triggers),
fix list ("Try this" POSTs `fix.what_if` and opens the what-if page with the run), result history.

### 20.5 What-if page

Controls: extra monthly savings slider (-50 % .. +100 % of average surplus, step 1000), per-goal date
shift (-24..+60 months) and target amount, risk tolerance 1-5, return shift (-3..+3 pp), income drop
(start, months 0-12, percent; 0 sends `income_drop: null`). Any change -> 800 ms debounce -> `POST what-if`
with `replace_active: true` and `base_result_id` = the baseline shown; only the run id returned by the
**latest** request is followed - events/results of older (replaced) runs are ignored [R23]. A 409 caused
by an active baseline run shows "Wait for the current plan run to finish". Shows progress inline, then a delta table vs baseline (via `/results/compare`)
and goal cards. "Apply to my plan" translates the changes into ordinary edits of the draft (extra savings
-> an income or discretionary expense with a normal id from `lib/ids.ts`, named "Extra savings"; goal
overrides -> goal fields; risk/return/inflation/EF share -> profile/assumptions; an income drop is not
applied) and saves, then re-runs the baseline. It never writes `whatif_*` ids (rejected by the API, 4) [R12].

### 20.6 State, accessibility, hooks

Server state via small hooks (`useFinancePlan`, `useFinanceResult`, `useFinanceRun`), no global cache.
Run progress per A.17.3 (resubscribe on reload, polling fallback after 3 errors, 409 navigates to the
active run). Charts: `role="img"` + `aria-label` summary + a visually hidden data table; status never by
color alone; keyboard-focusable points with tooltips. Preferences (real/nominal toggle, chart goal) in
`localStorage` keys `sp.fin.*`.

Stable `data-testid`s (QA contract): `nav-finance`, `nav-scheduling`, `fin-plan-list`,
`fin-template-card-<id>`, `fin-start-blank`, `wizard-step-<step>`, `wizard-next`, `wizard-back`,
`wizard-skip`, `income-row-<id>`, `expense-row-<id>`, `debt-row-<id>`, `holding-row-<id>`,
`goal-row-<id>`, `build-plan`, `fin-run-progress`, `fin-run-status`, `goal-card-<goalId>`,
`goal-success-<goalId>`, `goal-status-<goalId>`, `contribution-table`, `corpus-chart`, `glide-chart`,
`cashflow-chart`, `fin-explanations`, `fix-<goalId>-<kind>`, `whatif-savings`, `whatif-goal-shift-<goalId>`,
`whatif-risk`, `whatif-result`, `fin-compare-table`, `fin-export-csv`, `send-to-planner`,
`disclaimer-banner`, `fin-save-state`.

---

## 21. Compliance and disclaimer rules

`DISCLAIMER` (exact text, `DISCLAIMER_VERSION = "fin-disclaimer-1"`):

> SuperPlanner Finance is an educational planning tool. It is not investment, tax or legal advice and
> does not recommend specific financial products. Results are estimates based on the assumptions you
> entered; actual returns, inflation and income can differ, and you could end up with less than your
> goals need. Consider consulting a qualified, registered investment adviser before making investment
> decisions.

Rules (binding, tested):
1. Shown on every finance page (`DisclaimerBanner`), returned in every `FinanceResult` and
   `/finance/defaults`, first line of every CSV, and in the description of planner problems.
2. The first visit to **any** `/finance/**` route shows a dialog "I understand" (stored
   `sp.fin.disclaimerAck`); it does not gate the API. E2E tests dismiss it in every test (fresh browser
   context).
3. Asset **classes** only. Defaults, templates and message catalog contain no product, fund, issuer,
   index or ticker names (denylist test on `defaults.py`, `templates.py`, `advisor/messages.py`).
   User-entered names are echoed verbatim and never augmented. Generic category words ("fund",
   "index fund", "fixed deposit", "debt fund", "gold") are allowed. The one scheme-type descriptor taken
   from the product direction, `PPF-like`, may appear only in the `govt_long` class **name** of 5.1 and is
   allow-listed explicitly in the denylist test (the denylist itself contains named indices, AMCs, banks,
   issuers and tickers, e.g. Nifty, Sensex, S&P, SBI, HDFC, ICICI, LIC, Vanguard, SPY, QQQ, GOLDBEES; the list lives in
   `backend/tests/finance/fin_helpers.py` and the same list is reused by the API and e2e tests) [R25].
4. Wording: generated text never uses "guarantee", "guaranteed", "assured", "risk-free", "sure",
   "will earn", "will grow to", "you should buy"; it uses "the plan allocates", "estimated",
   "assumes", "in a weak market". Probabilities are labelled "estimated chance".
5. Every result carries `assumptions_used` and shows them; user assumptions are distinct from
   computed results (UI labels "Your assumption" vs "Calculated").
6. No network calls, no market data, no LLM in the finance path. All numbers come from the plan
   document and the engine.
7. Privacy: data stays in the local DB; logs and audit details contain ids/counts, never amounts or
   names; no telemetry.
8. Tax: not computed; `tax_note` is free text shown back to the user with a "not calculated" label.

---

## 22. Repository layout, ownership and edits to existing files

Work packages: **FWP1** finance engine (backend-developer), **FWP2** finance API (backend-developer),
**FWP3** finance UI (ui-developer), **FWP4** QA (tester), **ARCH** this document.
`docs/PLAN-FINANCE.md` calls them **F1-F4** (FWPn = Fn); on ownership and order that plan wins.

```
backend/superplanner/finance/__init__.py, model.py, defaults.py, timegrid.py, returns.py,
    preflight.py, cashflow.py, optimizer.py, simulate.py, validator.py, pipeline.py, whatif.py,
    compare.py, templates.py, export.py, bridge.py, advisor/{__init__,explain,fixes,messages}.py   FWP1
backend/requirements.txt, backend/pyproject.toml   FWP1 (numpy pin only) [R24]
backend/tests/finance/**            FWP1  (conftest.py, fin_helpers.py, fixtures/*.finance.json; files test_fin_*.py)
backend/superplanner/api/finance/{__init__,router,schemas,service,run_service,db_models,planner_link}.py  FWP2
backend/tests/api_finance/**        FWP2  (conftest.py, apifin_helpers.py; files test_apifin_*.py)
frontend/src/finance/**             FWP3
frontend/e2e/finance.spec.ts        FWP4  (new file; e2e helpers stay in their own file finance-helpers.ts)
backend/tests/integration/test_int_finance_*.py   FWP4 (optional property/benchmark tests)
docs/FINANCE.md                     ARCH (section 24 notes: any developer)
```

Minimal edits to existing files (exactly these):
- `backend/superplanner/api/main.py` (FWP2): `from .finance import router as finance_router` and add
  `finance_router.router` to the `include_router` loop with `API_PREFIX`.
- `backend/superplanner/api/context.py` (FWP2): in `start()`, import `.finance.db_models` before
  `self.db.create_all()`, and after `run_service.recover_interrupted_runs(self)` call
  `finance_run_service.recover_interrupted_runs(self)`.
- `backend/requirements.txt`, `backend/pyproject.toml` (**FWP1**, because the engine introduces the direct
  import; changed in review [R24]): add `numpy==2.5.4` (already installed in `.venv` as an OR-Tools
  dependency; now imported directly). No other dependency is added (no scipy: `statistics.NormalDist`
  provides `Phi^-1`).
- `frontend/src/main.tsx` (FWP3): spread `financeRoutes` into the `App` children before the `*` route.
- `frontend/src/App.tsx` (FWP3): the `Main` nav of 20.1.
- `README.md` (**FWP3**, changed in review [R24]): how to open Finance, the disclaimer, the finance test
  commands.

Helper module names are unique across test areas (`fin_helpers`, `apifin_helpers`) because each
conftest inserts its folder into `sys.path`; test file names stay unique (`--import-mode=importlib`).
`apifin_helpers` defines its own `make_app` (do not import `tests/api/api_helpers.py`: it is only on
`sys.path` when `tests/api` is collected). No existing file under `backend/tests/**` or
`frontend/e2e/*.spec.ts`/`helpers.ts` is edited.

---

## 23. Testing strategy

Principle: the dangerous failure is a plan shown as feasible that breaks a hard rule, so **every
optimizer/pipeline test asserts `validate_result` has no hard violations**, and the validator is tested
first against hand-built results.

| Layer | Owner | What |
|-------|-------|------|
| Model | FWP1 | ranges, regexes, reserved ids, extra fields rejected, defaults round-trip |
| Timegrid | FWP1 | month index, blocks truncated at goal dates, occurrence rule for each frequency |
| Cashflow | FWP1 | hand-calculated: growth step on anniversaries, inflation-linked vs fixed, amortization payoff month, EF waterfall and `t_E`, holdings split into EF / buffer / pool |
| Preflight | FWP1 | every code fires with the right severity and a readable message |
| Optimizer | FWP1 | single goal, one class, zero volatility: level contribution == `TR / Phi(n)` within 0.1 %; must beats nice when cash is short; minimax spreads shortfall across two must goals; EF gating; lock-in exclusion; glide cap binds and sells; global equity cap; holdings assignment; locked holding not sold; T0 cash-infeasible detected and equal to the zero-contribution deficit after selling every unlocked holding into cash (`w`); a negative-surplus month covered by selling an equity holding is **feasible**; a locked risky earmark inside the final glide block stays feasible (allowance `LR`); an earmark in a class outside the goal's allowed list is sold, never bought; a goal whose `t_E` falls mid-block gets contributions only from `t_E`; MILP mins respected; size-cap plan solves < 10 s |
| Validator | FWP1 | each code with a minimal hand-made result; boundaries at tolerance |
| Simulate | FWP1 | seeded determinism; zero volatility + zero inflation vol == central scenario; probability increases with contributions; sample correlation within 0.03 at 20 000 draws; interruption lowers probability |
| Pipeline | FWP1 | calibration raises probability or stops; cancel raises `FinanceCancelled` within 1 s (also when set during a solve); templates at defaults feasible; published lines are floored and the recomputed plan-basis value equals `planned_value_real` |
| Advisor | FWP1 | each reason code on crafted plans; applying a returned `INCREASE_SAVINGS`/`DELAY_GOAL` fix's `what_if` removes the shortfall under the 12.3 guarantee conditions; `INCREASE_RISK` uses a goal override; exactly one `smallest` |
| What-if / compare / CSV / bridge | FWP1 | pure function outputs; bridge problem passes `engine.preflight` with no errors and `horizon_days <= 366` |
| Compliance | FWP1 | denylist (products, tickers, issuers) on catalogs; forbidden words on all generated text of every template run; disclaimer present |
| Boundaries | FWP1 | import test of section 2 rules |
| Property | FWP1/FWP4 | 100 random small plans (stdlib `random`, fixed seeds): run -> no hard violations, or feasibility `infeasible` with T0 deficit > 0 |
| API | FWP2 | every endpoint and status in 18.2; If-Match 412/428; `whatif_` ids rejected on write; one active run; what-if `replace_active` and `base_result_id`; cancel racing completion stores no result; SSE replay with `Last-Event-ID` and 204; cancel; startup recovery; CSV headers; send-to-planner -> `/problems/{id}/validate` ok; delete with active run 409 |
| UI contract | FWP3 | `contractExamples.ts` type-checks; `npm run typecheck && npm run build` |
| E2E | FWP4 | create from template -> wizard Next through all steps -> build -> live progress -> goal cards and charts render -> what-if slider re-run shows deltas -> compare -> CSV download -> send to planner opens the new plan -> disclaimer visible -> dark mode renders charts |
| Regression | all | existing 551 backend tests and 23 Playwright tests unchanged and passing |

Commands unchanged (A.18): `cd backend && .venv/bin/pytest -q`; frontend typecheck/build; Playwright with
`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`.

---

## 24. Deferred items, deviations, implementation notes

### 24.1 Deferred (documented, not built)

| Item | Hook left |
|------|-----------|
| Tax calculation with versioned rules per financial year | `tax_drag_pct`, `tax_note` |
| Product data, eligibility, minimum investment by product, live/verified market data | asset-class table is the seam; `source_note` |
| Account aggregation, transaction import, planned-vs-actual tracking, drift alerts | results store planned calendar; send-to-planner reviews |
| Retirement decumulation (withdrawal phase, annuities), life expectancy modelling | retirement = corpus target at retirement month |
| Debt prepayment optimization, new loans for goals (home loan) | `HIGH_INTEREST_DEBT` warning |
| Mean-variance / CVaR / stochastic programming, GA or metaheuristics | caution `z_g` + Monte Carlo calibration |
| Monthly (non-block) SIP levels, contribution rounding to amounts like ₹500 | block length 6/12; UI shows rounded display values |
| Inflation-return correlation, regime models, fat tails | lognormal + annual inflation shocks |
| Multi-currency, couples with separate profiles, insurance needs | single `profile.currency` |
| Authentication, encryption at rest, consent records | same as A.20 |
| LLM explanations / chat | must sit on top of the computed explanation, never invent numbers |
| Rolling-horizon automatic replanning | what-if + re-run; `replanning_triggers` |

### 24.2 Deviations from the task text (with reasons)

| Direction | Design | Why |
|-----------|--------|-----|
| Monthly contributions per goal x class | Level monthly amount per **block** (12 or 6 months), per goal x class | 12x fewer variables, SIP-like plans users can follow, rebalancing at block starts |
| Emergency fund as a hard constraint in the LP | Deterministic EF waterfall in cashflow (stage A); should/nice variables exist only after `t_E` | Keeps the LP linear without binaries; the rule is satisfied by construction and re-checked by the validator |
| Risk via expected-return LP | Cautious per-goal planning returns (`z_g * sigma / sqrt(Y)`) plus glide caps, calibrated by Monte Carlo | An expected-value LP always fills the riskiest class; the haircut ties allocation to horizon and target probability while staying linear |
| Nominal accounting | Everything real (today's money); nominal shown as "expected future" | Goals are entered in today's money; avoids mixing inflation into every comparison |
| Cancelled run keeps best result | Cancelled finance runs store no result | Runs take seconds; a partial plan without simulation would be misleading |
| Send to planner for the whole horizon | Next 1-12 months | Scheduler `horizon_days <= 366`; reviews keep the plan current |

### 24.3 Implementation notes

_(developers: record interpretations here with date and owner)_

- 2026-10-16, FWP3 (ui-developer): `wizard-step-<step>` is on the stepper link of each step (always visible);
  the step content panel has `wizard-panel-<step>`. The template card button is "Create plan" (as on the
  scheduling home page); a successful send-to-planner navigates straight to the returned `url`
  (`/plans/<id>/tasks`); the dialog's confirm button is `send-to-planner-confirm`; the first-visit dialog
  button is `disclaimer-accept`.
- 2026-10-16, FWP3: "Apply to my plan" names a negative extra-savings change "Reduced savings" (a
  discretionary, inflation-linked expense) instead of "Extra savings", which would mislead; a positive
  change is the income "Extra savings" (20.5). `return_shift_pct` is applied to every non-`cash`
  category class, clamped to -20..40.
- 2026-10-16, FWP3: the what-if page shows its delta table with `data-testid="whatif-compare-table"`
  inside `whatif-result`; `fin-compare-table` is used only on the compare page.

- 2026-10-16, FWP1 (backend-developer): **stubs complete** and the engine is implemented (F1 steps 1-11);
  `pytest tests/finance` 178 passed, existing 551 unchanged.
- 2026-10-16, FWP1: **cautious returns (8.2)** use the z-quantile of the annualized *lognormal real* return:
  `Rplan = max(-0.5, (1+R) exp(-s^2/2 - z s/sqrt(Y)) - 1)`, `s = sqrt(ln(1 + (sigma_real/(1+R))^2))`,
  `sigma_real = sqrt(sigma_a^2 + sigma_pi^2)`. The literal `R - z sigma_a/sqrt(Y)` ignores inflation shocks
  (which hit every class's real return in 9.1) and the lognormal mean-median gap, so `z = Phi^-1(p)` gave far
  less than `p` (car goal of the young-professional template: 39 % for a 70 % target; now ~69 % stand-alone).
  Zero volatilities give exactly `R` (1.9 holds). Shared by LP and validator through `returns.py`.
- 2026-10-16, FWP1: **tier tolerance (8.5)**: currency tiers (T0, T5) use `max(1e-4, 1e-6|v|)` scaled as
  written; shortfall-fraction tiers (T1a..T3b) use the same 0.1 currency expressed as a fraction,
  `max(1e-4 / max TR_scaled of the tier, 1e-6|v|)` (a literal 1e-4 fraction let every goal stay 0.01 % of
  its target short, e.g. 1,050 on 10.5 M, which also blocked calibration's `short <= 1.0` test). T4 keeps 5 %
  relative (+1e-6). Fix-search bounds use the same per-tier slack.
- 2026-10-16, FWP1: **flooring headroom (8.8)**: the goal constraint is `sum F + short >= TR + h_g`, with
  `h_g = 0.01 x sum over contribution variables of Phi x rho^(months to D)` (an upper bound of the flooring
  loss). Without it every published plan sat a few currency units below `TR`, so zero-volatility goals got
  success 0 under 9.2's `V >= TR - 1`. `short` is bounded by `TR + h_g`; published shortfalls use `TR`.
- 2026-10-16, FWP1 (regression fix): the tier constraint is `short_g <= eta x (TR_g + h_g)` (homogeneous),
  so `eta = 1` still allows an unfunded goal's full shortfall. The first version, `short_g <= eta TR_g + h_g`
  (constant right-hand side), left GLOP on a degenerate face once `eta` was fixed at ~0: T4 ended `ABNORMAL`
  and the published T2b vertex carried pure churn (sell `u`, buy `(1 - tau) u` of the same class, which
  publishing nets to a sell without buy, `REBALANCE_UNBALANCED`). `T1b..T3b` still minimise `short_g / TR_g`.
- 2026-10-16, FWP1: **numerical fallback hardening (8.5 [R9])**: a tier that returns `INFEASIBLE`/`ABNORMAL` is
  first re-solved from scratch (`INCREMENTALITY_OFF`), then also with presolve off; only if that fails is
  `TIER_NUMERIC_FALLBACK` raised. The remaining tiers are then skipped except the cleanup tier T5, which is
  tried once on top of the tiers already fixed (its solution is used if it solves; otherwise the previous
  tier's). Publishing never emits a rebalance whose sells have no buys (it is dropped: it can only be LP churn).
- 2026-10-16, FWP1: **caps only bind where they can be met** (8.4 rules 7-9, validator 11): the bucket glide
  cap at block k applies only if the goal has an allowed class outside the risky set that can still be bought
  at `s_k` (lock-in rule); the contribution-mix cap only if a non-risky class can receive contributions in the
  block; for the global equity / class caps a goal that cannot move money out of the capped set at `s_k`
  has its capped positions counted as allowance (like [R8]). Otherwise the LP met caps by buying and selling
  the same class to burn value through `tau` (seen in the property test), or was infeasible with `tau = 0`.
  Helpers `can_dilute` / `mix_cap_applies` in `returns.py` are used by both LP and validator. Publishing also
  nets same-class buy/sell before clipping sells to the bucket value.
- 2026-10-16, FWP1: **published rebalances**: sells are `floor2(min(u, F_published - locked value))` and buys
  are scaled to `(1 - tau) x sells`, where `F_published` is the bucket recomputed from floored lines; values
  are replayed with `validator.replay_goal` (the validator's own code), so `BUCKET_MISMATCH` cannot fire on a
  correct plan. `planned_value_real` is rounded to 2 decimals.
- 2026-10-16, FWP1: LP details: the cash balance is one equality per month with `B_{t+1} >= m_buf gamma_c`
  as a variable bound (same constraint as rule 10); T5 adds `1e-3 sum w + 1e-4 sum u` (scaled) so selling to
  cash and churn are never chosen without need. `CASH_LIMITED` / `CASH_FULLY_USED` use slack (`B_{t+1}/gamma_c
  <= m_buf + 1`), not duals. Cancel: the watcher polls `cancel_event.wait(0.05)` and calls `InterruptSolve()`
  (measured: a 0.3 s GLOP solve stops in ~0.06 s); model building also checks the event per goal and every
  100 months. A T0 that is not solved at all (time limit) yields a zero-contribution fallback with greedy
  deficits (`termination_reason = "time_limit"`); an INFEASIBLE/ABNORMAL T0 raises `RuntimeError` (run
  `failed`). `termination_reason` is `optimal | time_limit | gap` (`gap` = MILP FEASIBLE).
- 2026-10-16, FWP1: MILP: `x >= (min + 0.005) z` (scaled) so the floored amount stays `>= min`; big-M as 8.6.
- 2026-10-16, FWP1: calibration accepts a round only if the must-tier shortfall did not grow by > 1.0 **and**
  no calibrated goal's probability dropped (1.14 "probability not lower"); otherwise it keeps the previous
  round and stops. Goals with `planning_z` at 3.0 are not raised further.
- 2026-10-16, FWP1: Monte Carlo: interruption flags/offsets are always drawn (fixed draw order whether or not
  interruptions are enabled); a cash shortfall month is `C < -1 x P` after the EF draw; the simulator keeps
  holding locks only for lock-in *classes* (a locked holding inside a non-lock class may be rebalanced in
  simulation). `series` values are recorded at the start of each month after that month's goal payments;
  `goal_withdrawals[t] = min(V, TR)` (central scenario).
- 2026-10-16, FWP1: preflight adds `START_MONTH_MISSING` (error) for `start_month = null` (services always
  fill it; the engine never guesses the current month). `DUPLICATE_ID` also checks asset class ids within
  `assumptions.asset_classes`. `NO_ALLOWED_CLASS` also fires for an explicit empty allowed list. Disabled
  goals are ignored by every goal rule except id checks. `GOAL_TARGET_HUGE` uses the average surplus over
  the horizon.
- 2026-10-16, FWP1: fixes: every candidate plan is `apply_what_if(plan, fix.what_if)` (the exact payload);
  the re-solve criterion is `short_g <= 0.5 tol_g` (headroom for flooring). `INCREASE_SAVINGS` solves `min e`
  with the extra income's real profile `(1+pi)^floor(t/12)/(1+pi)^(t/12)` counted only from `t_E` (before it
  the EF waterfall may absorb it; conservative), then verifies `ceil(e)` with one re-solve of the derived plan
  and drops the fix if it does not meet the criterion. `resulting_success_probability` = 500-path MC of the fix
  LP's solution (omitted when time is short); `REDUCE_TARGET` has no MC. `DELAY_GOAL` messages say whether N
  is within `flexibility_months`.
- 2026-10-16, FWP1: `compare_results(a, b, *, summary_a=None, summary_b=None, what_if_b=None)`: the
  optional keywords let the API pass the stored summaries (ids, kind, label, created_at) and the what-if
  changes; without them the summaries carry only result-derived fields.
- 2026-10-16, FWP1: "identical result JSON for the same seed" (1.13) excludes the wall-clock fields
  `diagnostics.tiers[].seconds`, `diagnostics.simulation_seconds` and `diagnostics.seconds_total`
  (new field). `diagnostics.cash_deficit_real` (new) is the T0 deficit in currency units.
- 2026-10-16, FWP1: CSV lines end with CRLF (RFC 4180), including the `# ` disclaimer line; `goal_withdrawal`
  amount is `min(central projection, TR)`; EF rows sort before goal rows of the same month and action.
- 2026-10-16, FWP1: bridge: a line start directly after a line of the same (goal, class) is named "Change to
  ..."; `REV-` tasks start at month `review_every_months`; `problem.metadata.finance_result_id` is `null`
  (the API sets it); invalid `months`, `review_every_months` or `utc_offset` raise `ValueError`.
- 2026-10-16, FWP1: templates accept numbers for every parameter (`int`/`month_offset_years` must be whole);
  the retirement preset counts every expense active at the plan start (so the family template includes the
  yearly school fees as 1/12 per month).

- 2026-10-16, FWP2 (backend-developer): the API imports `default_label` from `superplanner.finance.whatif`
  (the only non-`__init__` engine import in `api/finance`), because the default what-if label (13) uses the
  engine's message catalog and `__init__` does not export it; FWP1 may re-export it, then the import moves.
  Label precedence: `changes.label`, then `run.label`, then `default_label(base plan, changes)`.
- 2026-10-16, FWP2: the worker re-runs `finance.validate_result` on the snapshot before the final write; if the
  engine said `feasible` but a hard violation is found, the stored result becomes `unknown` with the
  validator's violations (logged with codes only). `send-to-planner` then answers 422 `NOT_FEASIBLE`
  (`details.feasibility`).
- 2026-10-16, FWP2: `stage_started` is written on the first progress callback of a new stage (its `message`);
  `stage_completed` when the next stage starts or `run_plan` returns, after flushing the pending throttled
  `progress`. A cancelled/failed run still closes its open stage before the terminal event.
- 2026-10-16, FWP2: what-if: `expected_plan_version` is compared with the current version even when
  `base_result_id` is given; `base_result_id` must be a **baseline** result of this plan (a what-if snapshot
  already contains `whatif_` items, which `apply_what_if` rejects) -> 422 `VALIDATION_ERROR`
  (`loc = ["body","base_result_id"]`); the what-if snapshot's `base_version` is that of the base document.
  A rejected request (412/422/409) rolls back the whole transaction, so `replace_active` never cancels the old
  run unless the new one is queued. What-if run defaults apply to every field not explicitly sent in `run`
  (`simulation.n_paths` counts as explicit only when sent inside `run.simulation`).
- 2026-10-16, FWP2: `RUN_ALREADY_ACTIVE` details carry `{run_id, kind}`; `finance_results.summary` stores
  `FinanceResultSummary` minus ids and `created_at`. `send-to-planner` defaults the name to
  `"<plan name> - money calendar"` and sets `problem.metadata.finance_plan_id/finance_result_id`; a
  `ValueError` from the bridge is 422 `VALIDATION_ERROR`. The engine's extra fields (`termination_reason =
  "gap"`, `diagnostics.cash_deficit_real`, `diagnostics.seconds_total`) are passed through unchanged; compare
  passes the stored summaries and `what_if_b` through the new `compare_results` keywords.
- 2026-10-16, FWP2: test seam `run_service._before_final_write(run_id)` is called after `run_plan` returned and
  before the final transaction (used by the 2.7 race test).
- 2026-10-16, review fixes (backend-developer): tier rows read `short_g <= eta * TR_g + head_g` (the goal row
  allows `short_g` up to `TR_g + head_g`), so an unfunded goal no longer gets `head_g` of forced value. The
  shortfall-fraction tiers (T1-T3 a/b) are fixed with a slack of 0.1 currency as a fraction of the tier's largest
  target only (the `1e-6 * v` relative term let a short must goal leak ~1e-6 TR into lower tiers).
- 2026-10-16, review fixes: caps for a goal's bucket are chosen by `returns.active_caps` (optimizer and validator):
  goal risky cap, then the global equity cap, then the class caps in plan order, each binding only when it can
  hold together with the caps already binding given the classes the goal can buy at the block start (exact
  check for the laminar cap sets). A cap that does not bind counts the goal's positions as allowance, as before.
- 2026-10-16, review fixes: `FinanceResult.simulation_settings` carries `seed` (`ResultSimulationSettings`).
  `REDUCE_TARGET`'s `amount` (and message) is `target_amount - new target`, in the goal's target-field units.
  Templates raise `ValueError` (422) when `retirement_age <= age`; the family template earmarks the 10-year
  locked holding to education only when `education_in_years >= 10`.
- 2026-10-16, review fixes: the validator recomputes earmark / initial EF / initial cash splits and the pool from
  its own projection (`HOLDING_SPLIT_MISMATCH` when rows differ), checks `assigned` rows (pool item and enabled
  goal, else `HOLDING_NOT_ASSIGNABLE`; class allowed, else `CLASS_NOT_ALLOWED`; unlocked by the goal date, else
  `LOCKIN_PAST_GOAL`) and reports rebalances that are not at a block start of an enabled goal
  (`REBALANCE_OFF_SCHEDULE`); goal buckets use the validator's own earmarks.

---

## 25. Review notes (team lead)

Review of this design against `docs/source/followups-finance-competitors-generalization.txt` (finance
answer, sections 1-8), the lead's product direction and the existing code (`backend/superplanner/api/**`,
`engine/model.py`, `frontend/src/{main,App}.tsx`, `src/api/client.ts`, test layout). The design matches
the direction (separate pure package, asset classes only, flexible optional inputs with defaults,
cashflow -> LP -> Monte Carlo -> validator -> computed explanations, `/api/v1/finance`, 7-step wizard,
SVG charts, disclaimer). Section 24.2 deviations are accepted. Fixes applied in place, tagged `[Rn]`:

| # | Where | Problem found | Change |
|---|-------|---------------|--------|
| R1 | 3 | `T = max(12, max D_g, ...)` put the payment month `D_g` outside length-`T` arrays (`goal_withdrawals`, `F_{K_g}`) | `T >= max D_g + 1` |
| R2 | 4.3/4.4 | income/expense starting before the plan start: growth and phase undefined | clamped to `t0 = 0` |
| R3 | 7.3 | EF target counted essentials that start years later and what-if items | only items active at `t = 0`, `whatif_*` excluded |
| R4 | 7.3 | cash-class money used for the EF had no defined class | moved into EF class at `t = 0`, reported |
| R5 | 8.3/8.4/8.5 | non-cash holdings could only go to goals, so a negative-surplus month was reported "proven infeasible" even when the user could sell investments | `w_h` sells unlocked pool items into the buffer; T0 proof stated under that rule; MILP big-M bound corrected (old `M` could cut off valid amounts once the buffer accumulates) |
| R6 | 8.3 | "split the block at `t_E`" was ambiguous (new rebalance point? growth factor?) | single variable paid only from `t_E`, growth `Phi(n')`, no extra rebalance |
| R7 | 8.1 | an earmarked holding in a class outside the goal's allowed list had no bucket variable | sell-only bucket classes |
| R8 | 8.4/11 | a locked risky holding (or a risky lock-in class bought earlier) near the goal date made glide/equity caps infeasible, contradicting "always feasible" | locked-position allowance `LR` in caps 7 and 9; validator uses the same |
| R9 | 8.5/10.2 | tier tolerance `1e-6` scaled is below GLOP feasibility tolerance (later tiers may turn INFEASIBLE); T0 threshold units unclear; feasibility rule order ambiguous | tolerance `1e-4` scaled, numeric fallback, ordered feasibility rule |
| R10 | 8.8/11/12.2 | merging blocks within 0.5 % (using the first amount) and dropping amounts < 1 changed the decisions after solving, which could make cash negative or trigger `BUCKET_MISMATCH` on correct plans; rounding up would accumulate cash deficits | floor to 2 decimals, merge only identical amounts, recompute plan values from published lines, goal tolerance 0.1 % |
| R11 | 8.5/18 | cancel only between solves (target "within 1 s" unreachable for large LPs); race between cancel and completion could store a result for a cancelled run | `InterruptSolve` watcher; final write re-checks `cancel_requested` |
| R12 | 4/13/20.5 | `whatif_` ids were a preflight error, but derived what-if plans are preflighted (every what-if would fail with 422), and "Apply to my plan" would store those ids | API write-level rule; Apply translates to ordinary edits |
| R13 | 12.3/13 | `INCREASE_RISK` changed the profile tolerance (no effect on goals with their own tolerance, side effects on others); fix guarantee could fail because same-tier siblings absorb cash | `GoalOverride.risk_tolerance`; siblings bounded; guarantee stated precisely; exact fix payloads |
| R14 | 13/18 | what-if applied to the current document but compared with an older baseline result, mixing edits with the what-if effect | `base_result_id` |
| R15 | 13/20.5 | income-drop expense raised the EF target; UI allowed `months = 0` but the model requires >= 1 | excluded from EF target; UI sends null |
| R16 | 16.1 | task ids `C-<goal>-<class>-<YYYYMM>` exceed the 64-char scheduler `Id`; names can exceed 200; calendar "weekday" ambiguous; requirement not stated | index-based ids, truncation, all 7 days, explicit requirement |
| R17 | 17 | audit action names differed from the existing `problem.created` style | aligned |
| R18 | 16.2 | CSV contained user text without formula-injection protection (existing schedule CSV has it) | same rule |
| R19 | 9.3 | storing all paths x months for quantiles is up to 10000 x 600 x 8 B per series; time limit vs simulation unclear | per-month quantiles in loop; simulation not truncated |
| R20 | 14/20.4 | stacked corpus (goal buckets only) and the p10-p90 band (buckets + EF + buffer) measured different things; existing unassigned holdings vanished from the chart | `unallocated` series; stack = band quantity |
| R21 | 20.2 | design said to reuse `raw` from `src/api/client.ts`, which is not exported; editing it is outside the allowed edits | local wrapper importing exported `ApiError` |
| R22 | 20.1/20.3/21 | "active by path prefix" marks Scheduling active everywhere; profile step lacked the horizon input asked for by the direction; real return not visible though the direction lists "expected real/nominal return"; dialog only on `/finance` (deep links skipped it); stale start month unflagged | explicit rules |
| R23 | 20.3/20.5 | autosave + Next could send two PUTs with the same If-Match (spurious 412); replaced what-if runs could overwrite the latest result on screen | single-flight saves; follow only the latest run id |
| R24 | 22 | numpy pin owned by FWP2 although FWP1 introduces the import; README owned by a non-existent role; `apifin_helpers` could not import `api_helpers` reliably | numpy -> FWP1, README -> FWP3, own `make_app` |
| R25 | 21 | denylist rule vs default class name containing "PPF-like" and the word "index fund" would make the compliance test ambiguous | explicit allow-list and denylist location |
| R26 | 14 | `holdings_assignment` could not express earmarks vs LP assignments vs sales; validator needs that to check `HOLDING_OVERASSIGNED` and the cash start | `source` field, rows partition each holding |
| R27 | 6 | `GOAL_TARGET_HUGE` divided by a non-positive surplus | skipped then |

Verified facts relied on: OR-Tools 9.15 in `.venv` provides GLOP, SCIP, CBC and `InterruptSolve()` for
GLOP/SCIP; numpy 2.5.4 is installed, scipy is not; `problem_service.create_problem(ctx, problem)` opens its
own write transaction; `engine.model.Problem` caps `horizon_days <= 366`, `Id` at 64 chars and names at
200; `src/api/client.ts` does not export `raw`/`request`; the baseline is 551 collected backend tests and
23 Playwright tests. Delivery plan: `docs/PLAN-FINANCE.md`.
