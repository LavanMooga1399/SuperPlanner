# SuperPlanner Phase 2a - Realistic finance, flexible inputs, usability (design)

Status: design for implementation. Authority: this document, then `docs/ARCHITECTURE.md` (scheduling) and
`docs/FINANCE.md` (finance) for everything it does not change. Where this document changes an earlier
contract it says so explicitly (section 5 lists every behaviour change and every existing test that is
updated). Nothing here may weaken a hard rule: feasibility first, hard constraints never traded against
soft objectives, every AI output is untrusted input.

Deferred to phase 2b (do not build): background job workers, PostgreSQL as default, user accounts/auth
(full list in section 6).

## Table of contents

- 0. Summary of decisions
- 1. Part A - Realistic finance
  - 1.1 Method
  - 1.2 Observed behaviour at the current defaults (numbers)
  - 1.3 Root causes
  - 1.4 Recalibrated default assumptions
  - 1.5 Cautious-planning margin (new formula)
  - 1.6 Calibration aim
  - 1.7 Inflation-linked incomes
  - 1.8 Templates (new figures)
  - 1.9 Results of the new design (prototype run)
  - 1.10 Growth-asset decision, explained per goal
  - 1.11 "You can invest" vs "Plan invests": funding split
  - 1.12 Amount ranges in the finance model
  - 1.13 Compatibility, engine version
  - 1.14 Tests (finance)
- 2. Part B - Flexible inputs before planning (`intake`)
  - 2.1 Flow and principles
  - 2.2 Package layout
  - 2.3 Common models: provenance, spans, questions, notes
  - 2.4 `ScheduleDraft`
  - 2.5 `FinanceDraft`
  - 2.6 Extractor interface and orchestration
  - 2.7 Rule-based extractor: grammar
  - 2.8 Questions and answers
  - 2.9 Builders (draft -> `Problem` / `FinancePlan`)
  - 2.10 AI extractor (Anthropic) - exact contract
  - 2.11 Merge policy (rule-based + AI)
  - 2.12 Settings, privacy, logging
  - 2.13 Table import (paste / CSV) with column mapping
  - 2.14 Duration ranges and PERT in the scheduling model
  - 2.15 REST API `/api/v1/intake`
  - 2.16 Tests (intake)
- 3. Part C - Usability pass (frontend)
  - 3.1 Routes
  - 3.2 Landing page
  - 3.3 Intake UI
  - 3.4 Finance UI changes
  - 3.5 Scheduling UI changes (ranges)
  - 3.6 General usability rules
  - 3.7 react-router 6 -> 7 upgrade and npm audit
  - 3.8 Frontend tests
- 4. File ownership and explicit edits to shared files
- 5. Changes to existing behaviour and to existing tests
- 6. Deferred items
- 7. Work packages and order
- 8. Review notes (team lead)
- 9. Implementation notes (one subsection per work package)

---

## 0. Summary of decisions

1. The "0 of 3 goals on track" outcome has two dominant causes, both measured: the example templates are
   unaffordable (family needs about 3x its surplus) and the per-class cautious return ranks equity
   *below* fixed deposits and the lock-in class for every horizon up to 25 years at must-have caution, so
   the LP never uses growth assets. Secondary causes: nominal salaries against inflation-linked expenses,
   a calibration target 2 pp below the status threshold, and a month-0 summary that includes a yearly fee.
2. New cautious return: the existing lognormal quantile, plus a horizon-scaled floor at a share of the
   class's median real return (0 below 3 years, 50 % from 10 years), lowered 0.5 pp per calibration step.
   Short goals behave exactly as today; goals 10+ years away keep growth assets up to the risk cap and the
   glide path. Parameters are editable (`Assumptions.caution`), `floor_share = 0` restores the old rule.
3. Defaults recalibrated to commonly cited long-run ranges (equity 12 %, FD 7 %, inflation 5.5 %), new
   persona figures, inflation-linked salaries (`IncomeStream.inflation_linked`), calibration aims at the
   minimum probability + 1 pp. Measured: family 3/3 on track (was 0/3), near retirement 2/2 (was 0/2), young
   professional 1/2 with the car deliberately at risk (needed by the existing "Try this" e2e test).
4. Every goal gets one plain-language "why this mix" reason (`GROWTH_*` codes) and the dashboard shows where
   the invested money comes from (monthly surplus vs savings already held), averaged over the first year.
5. New pure package `superplanner.intake` turns free text or pasted/CSV tables into a structured **draft**
   (scheduling `ScheduleDraft` or `FinanceDraft`) with per-field provenance (confidence + source span),
   plus follow-up questions. All intake endpoints are stateless; nothing is stored until the user presses
   "Create plan", which calls the existing create endpoints.
6. Two extractors behind one interface: deterministic rule-based (always) and optional Claude via the
   official `anthropic` SDK 1.15.0 (only if `INTAKE_AI_ENABLED` and credentials resolve and the user opted in
   for that request). AI output is validated by Pydantic, merged with the rule-based result (typed numbers
   win) and goes through the same builders and preflight as manual input. Every AI failure falls back to
   rule-based with a user-facing reason.
7. Scheduling `Task` gains an optional `duration_estimate` (optimistic/likely/pessimistic minutes);
   `duration_minutes` must equal the PERT expected value `(o + 4m + p) / 6`; the schedule explanation gains a
   duration-risk note. Fully backward compatible (field optional).
8. Frontend: a landing page "What do you want to plan?" with four kinds x four ways to start, the intake
   flow (describe -> questions -> side-by-side review -> create), table import with column mapping, less
   jargon, and the upgrade from `react-router-dom` 6.30.6 to `react-router` 7.18.4 (latest 7.x; clears
   GHSA-wrjc-x8rr-h8h6 and GHSA-337j-9hxr-rhxg; the only advisories `npm audit` reports today).

---

## 1. Part A - Realistic finance

### 1.1 Method

All numbers in 1.2, 1.3 and 1.9 come from running the engine in `backend/.venv` (Python 3.13, OR-Tools
9.15) with `start_month = "2026-11"` and `finance.run_plan(plan, FinanceRunRequest(seed=1))` (default
2000 paths, 2 calibration rounds) unless stated. The screenshot figures (-10,000 / 30,479) are seed 0 and
match the observed dashboard. The new design was prototyped by monkeypatching `defaults`, `returns.
planning_return`, the calibration threshold and `cashflow.flow_components` (inflation-linked incomes) in a
scratch script, not in the repository; implementers must reproduce the *bands* in 1.14, not the exact
digits. Seeds 0, 1 and 7 gave the same statuses.

### 1.2 Observed behaviour at the current defaults

Current defaults: equity 11.5 % (vol 18 %), FD 6.75 % (1 %), lock-in `govt_long` 7.1 % (0.5 %, 180 months),
cash 3 %, inflation 6 % (vol 1.5 %), must-have minimum probability 0.85 (`z = 1.036`).

| Template | Goal | Months | Target (real) | Planned shortfall | Chance | Status | Mix now |
|---|---|---|---|---|---|---|---|
| young_professional | car (should) | 48 | 6,00,000 | 0 | 53 % | at risk | 100 % fixed deposit |
| | retirement (must) | 432 | 1,05,00,000 | 0 | 87 % | on track | 100 % govt_long |
| family | home (must) | 36 | 15,00,000 | 8,02,967 (53.5 %) | 0 % | off track | 100 % fixed deposit |
| | education (must) | 180 | 37,99,702 | 20,34,022 (53.5 %) | 0 % | off track | 100 % fixed deposit |
| | retirement (must) | 300 | 2,85,00,000 | 1,52,56,384 (53.5 %) | 0 % | off track | 100 % govt_long |
| near_retirement | retirement (must) | 96 | 3,30,00,000 | 1,87,00,592 (57 %) | 0 % | off track | 100 % fixed deposit |
| | wedding (nice) | 36 | 10,00,000 | 10,00,000 | 0 % | off track | none |

Family summary at seed 0: `monthly_investable_now = -10,000`, `monthly_contribution_now = 30,479`, 0 of 3 on
track; `holdings_assignment` shows the whole 5,00,000 equity holding `sold_to_cash`.

Planning (cautious) real returns at must caution (`z = 1.036`), current formula and defaults:

| Years to goal | FD | govt_long | equity_index |
|---|---|---|---|
| 3 | -0.38 % | 0.08 % | -6.57 % |
| 5 | -0.14 % | 0.30 % | -4.39 % |
| 10 | 0.10 % | 0.51 % | -2.15 % |
| 15 | 0.21 % | 0.60 % | -1.14 % |
| 25 | 0.32 % | 0.70 % | -0.12 % |
| 35 | 0.38 % | 0.75 % | 0.43 % |

(Expected real returns: FD 0.71 %, govt_long 1.04 %, equity 5.00 %; equity median real 3.48 %.)

### 1.3 Root causes

R1 **Unaffordable templates (dominant for family and near retirement).** Family: take-home 1,50,000,
essentials 70,000, lifestyle 20,000, EMI 10,000, school fees 60,000 once a year -> first-year average real
surplus 41,330/month (`summarize_cashflow`). Needs at the plan's own safe returns (about 0.2-0.7 % real):
retirement 2.85 Cr in 25 years about 87,000/month, home (15 L in 3 years, minus the 5 L equity holding) about
28,000/month, education (38 L real in 15 years) about 20,000/month: about 1,35,000/month, 3.3x the surplus.
Near retirement: target 3.3 Cr (25 x 1,10,000 x 12) in 8 years against 80 L of holdings and 85,000/month.
The retirement preset (25 x all current expenses, including school fees that stop long before retirement)
inflates targets further.

R2 **Per-class cautious quantile collapses equity.** `planning_return` (FINANCE 8.2 as amended in F.24.3)
values each class at its own `z`-quantile of the annualised lognormal real return. For a single volatile
class the must-have quantile is near zero or negative at every horizon below about 30 years (table in 1.2),
while low-volatility classes keep almost their full return. The LP is linear, so each bucket goes 100 % to
the class with the highest planning return: `govt_long` for long goals, FD for short ones. The quantile is
statistically honest for a *single* class but ignores diversification and the user's risk choice: a 60/40
mix has a far better 15th percentile than 100 % equity, and Monte Carlo measures the true probability
anyway. Result: risk tolerance has no effect; long goals hold no growth assets.

R3 **Strict must-have probability on top of R2.** `must = 0.85` is reasonable, but combined with R2 it
forces the full `z = 1.036` quantile on equity, which is what removes it; the calibration loop can only
raise `z` further.

R4 **Nominal salaries vs inflation-linked expenses.** `IncomeStream.growth_pct` is nominal and applied once a
year; inflation-linked expenses rise every month. Family: growth 6 % = inflation 6 %, so real income is flat
for 25 years and falls about 0.5 %/month inside each year (first-year real income about 1,46,000, not
1,50,000). In Monte Carlo, inflation shocks lower the real surplus and the lowest-priority contributions are
cut first: the young professional's car is planned to exactly its target yet has 53 %; with inflation
volatility 0 the same plan has 72 %.

R5 **Minimax fairness spreads an unavoidable shortfall over every must goal.** Tier T1a minimises the
largest shortfall *fraction*; when the money cannot cover all must goals the optimum equalises them (53.5 %
each), so every must goal shows 0 % instead of some being funded. This is the documented FINANCE 8.5
design and stays; it is only visible because of R1. Phase 2a adds an explanation (`SHARED_SHORTFALL`, 1.10).

R6 **Month-0 summary and its wording.** `monthly_investable_now = investable[0]`; yearly items occur in the
start month (FINANCE 7.1), so the family's 60,000 school fee makes month 0 negative (-10,000). The plan still
invests 30,479 in month 0 because it sells the equity holding into the cash buffer (`w_h`, 8.4 rule 2) and
drip-feeds it. "You can invest now -10,000" next to "Plan invests now 30,500" is correct arithmetic but reads
as a contradiction: the funding source is not shown.

R7 **Calibration aims below the status threshold.** Calibration raises `z` only while
`prob < min_probability - 0.02`, but `on_track` needs `prob >= min_probability`. Planned-to-target goals end at
0.83-0.84 and show "at risk" (prototype before the fix: education 0.82, retirement 0.84).

R8 **The lock-in class wins the safe ranking.** `govt_long` has the highest safe return and the lowest
volatility, so every long safe position goes there (100 % for retirement). There is no annual deposit cap in
the model. Accepted for 2a (safe share only, once R2 is fixed); a per-class yearly contribution cap is
deferred (section 6).

### 1.4 Recalibrated default assumptions (`finance/defaults.py`)

Long-run, illustrative, editable; no live data, no product names. Ranges are those commonly cited for India
(equity index long-run nominal 10-13 %, bank FD 6.5-7.5 %, government small-savings lock-in about 7-7.5 %,
gold 8-10 %, CPI inflation 4-6 % around a 4 % target).

| id | name (unchanged) | category | expected % | volatility % | expense ratio % | liquidity days | lock-in months |
|---|---|---|---|---|---|---|---|
| cash | Cash / savings account | cash | **3.5** | 0.5 | 0 | 0 | 0 |
| fixed_deposit | Fixed deposit | debt | **7.0** | 1.0 | 0 | 2 | 0 |
| short_debt | Short-term debt fund | debt | **7.25** | **2.5** | **0.3** | 2 | 0 |
| govt_long | Government long lock-in savings (PPF-like) | debt | 7.1 | 0.5 | 0 | 7 | 180 |
| equity_index | Diversified equity index fund | equity | **12.0** | 18.0 | 0.2 | 3 | 0 |
| gold | Gold | gold | **8.5** | 15.0 | 0.4 | 3 | 0 |

- `INFLATION_PCT = 5.5` (was 6.0), `INFLATION_VOLATILITY_PCT = 1.5` (unchanged).
- Correlations, `RISKY_CAP_BY_TOLERANCE_PCT = (20, 40, 60, 75, 90)`, `GLIDE_PATH`, EF defaults and
  `DEFAULT_MIN_PROBABILITY = {must 0.85, should 0.70, nice 0.50}` are unchanged.
- `SOURCE_NOTE = "Illustrative long-run assumptions, not forecasts: equity 12%, fixed deposit 7%, inflation
  5.5% a year are within commonly cited long-run ranges. Edit them to match your own view."`
- Real expected returns at 5.5 % inflation: cash -1.90 %, FD 1.42 %, short debt 1.42 %, govt_long 1.52 %,
  equity 5.97 % (median 4.46 %), gold 2.46 % (median 1.37 %).

### 1.5 Cautious-planning margin (`finance/returns.py`)

New settings on `Assumptions` (model, defaults in `defaults.py`):

```python
class CautionSettings(_Strict):
    floor_share: float = Field(default=0.5, ge=0, le=1)          # share of the median real return kept
    floor_start_years: float = Field(default=3.0, ge=0, le=50)   # no floor up to here
    floor_full_years: float = Field(default=10.0, ge=0.5, le=50) # full floor from here
    floor_step_pct_per_z: float = Field(default=2.0, ge=0, le=10)  # pp removed per unit of extra caution
    # model_validator: floor_full_years > floor_start_years

class Assumptions(_Strict):
    ...  # existing fields unchanged
    caution: CautionSettings = Field(default_factory=CautionSettings)
```

Formula for goal `g`, class `a` (all rates annual, real; `R`, `sigma_real` exactly as today):

```
Y      = max(1, D_g / 12)
s      = sqrt(ln(1 + (sigma_real / (1 + R))^2))
q      = (1 + R) * exp(-s^2/2 - z * s / sqrt(Y)) - 1          # unchanged honest z-quantile
med    = (1 + R) * exp(-s^2/2) - 1                             # median real return
ramp(Y) = clamp((Y - floor_start_years) / (floor_full_years - floor_start_years), 0, 1)
phi(Y)  = floor_share * ramp(Y)
delta   = floor_step_pct_per_z / 100 * max(0, z - z0)          # z0 = initial_z(goal) = Phi^-1(p_g)
Rplan   = R                                   if sigma_real == 0
        = max(-0.5, q)                        if phi(Y) == 0
        = max(-0.5, max(q, phi(Y) * max(med, 0)) - ramp(Y) * delta)   otherwise
```

Review fix (LEAD): the calibration penalty `ramp(Y) * delta` is subtracted from **every** class's value
(not only from the growth floor). The architect's version lowered only the floor, so after three
calibration steps (`calibration_rounds` allows up to 4, `z` up to `z0 + 1.0`) equity at 25 years fell to
0.73 % vs 0.94 % for `govt_long` at must caution (0.73 % vs 1.10 % at should), and the LP went back to
100 % safe: exactly the collapse Part A must remove. With a common shift the class ranking at any `z`
equals the ranking of the unshifted values, so growth keeps its place at every calibration step, and
calibration still raises contributions (it lowers the sizing return of the whole bucket). `ramp(Y)` keeps
the value continuous at `Y = floor_start_years`.

Signature: `planning_return(ac, pi, z, D_g, inflation_vol, *, z0: float, caution: CautionSettings) -> float`
and `planning_rho(...)` likewise (keyword-only, required: every caller passes them; optimizer, validator,
pipeline `assumptions_used.planning_returns_pct`, advisor, the integration test checker and
`tests/finance/test_fin_optimizer.py:217-225`, see section 5).

Properties (unit-tested): zero volatility returns exactly `R` (FINANCE F.24.3 property kept); `Y <= 3`
gives exactly today's value; non-increasing in `z`; continuous in `Y`; non-decreasing in `Y` at `z = z0`;
at `z = z0` and `Y >= 10`, `Rplan >= 0.5 * med`; for every `z >= z0` and `Y >= 10`, equity's value minus
the best safe class's value is at least that difference at `z = z0` (ranking preserved). With the defaults
equity (2.23 % at `z0`) is above every safe class (<= 1.41 %) for any `p` in [0.5, 0.99] and any `z` in
[`z0`, `z0 + 1`] (checked by LEAD: 0 failures over p in {0.5, 0.7, 0.85, 0.95, 0.99}, Y in {10, 15, 25,
35}, 5 calibration levels), so long goals use growth assets up to the cap; the glide path then lowers the
cap near the goal date. Each calibration step (+0.25 z) lowers every class's value by up to 0.5 pp, which
raises contributions instead of stalling. Why: probability is measured by Monte Carlo and enforced by
calibration; the LP's planning return only has to rank classes sensibly and size contributions
conservatively.

Because the safe part of a bucket now also gets cheaper after calibration, contributions after
calibration are somewhat higher than in the architect's prototype. P1 must re-measure the 1.9 table with
the real code and record it there. If a 1.14 band fails only because of this, P1 may lower the default
`floor_step_pct_per_z` (not below 1.0) and record the value and the reason in 1.9; the ranking property
does not depend on the step size.

New planning returns, must caution (`z = z0 = 1.036`) and after two calibration steps (`z = 1.536`),
recomputed by LEAD with the formula above:

| Years | FD (z0) | govt_long (z0) | equity (z0) | FD (z0 + 0.5) | govt_long (z0 + 0.5) | equity (z0 + 0.5) | gold (z0) |
|---|---|---|---|---|---|---|---|
| 3 | 0.33 % | 0.56 % | -5.60 % | -0.18 % | 0.11 % | -10.10 % | -7.13 % |
| 5 | 0.57 % | 0.77 % | 0.64 % | -0.08 % | 0.14 % | 0.35 % | 0.20 % |
| 7 | 0.70 % | 0.89 % | 1.28 % | -0.17 % | 0.02 % | 0.70 % | 0.39 % |
| 10 | 0.82 % | 0.99 % | 2.23 % | -0.30 % | -0.25 % | 1.23 % | 0.69 % |
| 25 | 1.03 % | 1.18 % | 2.23 % | -0.15 % | 0.02 % | 1.23 % | 0.69 % |

### 1.6 Calibration aim (`finance/pipeline.py`)

Replace the trigger `prob < min_probability(g) - 0.02` with `prob < min_probability(g) + CALIBRATION_AIM`,
`CALIBRATION_AIM = 0.01`. Everything else (`Z_STEP = 0.25`, `Z_MAX = 3.0`, the must-shortfall and
probability-drop guards, `calibration_rounds` default 2) is unchanged. `goal_status` thresholds are
unchanged.

### 1.7 Inflation-linked incomes (`model.py`, `cashflow.py`, `simulate.py`, `whatif.py`)

```python
class IncomeStream(_Strict):
    ...  # existing fields
    inflation_linked: bool = False
```

- `False` (default, old documents): unchanged; `amount` nominal, `growth_pct` nominal yearly raise.
- `True`: `amount` is in today's money; `growth_pct` is the yearly raise **above** inflation. Real amount in
  month `m` = `amount * (1 + g)^((m - t0) // 12)`; nominal = real x price index.
- `FlowComponents` gains `inc_int_linked: np.ndarray` (real, interruptible linked incomes); non-interruptible
  linked incomes are added to `real_linked`. `income` (real breakdown) includes both.
- Simulator 9.2 step 1: `inc = fc.inc_nonint[t] + where(in_spell, 0, fc.inc_int[t] + fc.inc_int_linked[t] * P)`
  (without spells: no `where`); `real_linked` already scales by `P`.
- `interruptible_monthly_income` (what-if income drop) keeps nominal streams as today; linked interruptible
  streams add a second expense `whatif_income_drop_linked` (inflation-linked, `percent` x real amount at the
  drop start). Existing `whatif_income_drop` semantics and test unchanged.
- Wizard default for new income rows stays `false` (keeps e2e "4[89],xxx"); templates and intake drafts use
  `true`. UI label (3.4).

### 1.8 Templates (`finance/templates.py`)

Retirement preset (all templates and intake):
`retirement_target = 25 x 12 x max(0, E_rec - I_rec)` where `E_rec` = monthly equivalent of expenses with
`start_month is None and end_month is None and category != "education"`, `I_rec` = monthly equivalent of
`rental`/`pension` incomes with `end_month is None`. Helper `retirement_target(expenses, incomes) -> float`
(public in `templates.py`, used by intake).

Goal ids, holding ids, parameter names and the earmark rule (education earmark only if
`education_in_years >= 10`) are unchanged so the e2e and template tests keep their ids.

**young_professional** - "First job: build an emergency fund, a car in three years (a stretch) and
retirement saving."

| item | value |
|---|---|
| params (default, range) | `age` 25 (18..40), `take_home` 60,000, `essentials` 26,000, `discretionary` 12,000, `car_price` 9,00,000, `car_in_years` 3 (1..15), `retirement_age` 60 (45..70) |
| income | `salary` 60,000, inflation-linked, real raise 3 % |
| holdings | `h_cash` cash 1,00,000; `h_eq` equity_index 50,000 |
| profile / EF | risk 4, EF 6 months |
| goals | `car` should, flex 12; `retirement` must, target 1,14,00,000 (25 x 12 x 38,000) |

**family** - "Two earners with a car loan and school fees, saving for a home, a child's education and
retirement."

| item | value |
|---|---|
| params | `age` 35 (25..55), `take_home` 1,80,000 (label "Household take-home pay (all earners)"), `essentials` 75,000, `discretionary` 20,000, `home_down_payment` 15,00,000, `home_in_years` 3 (1..10), `education_cost` 25,00,000, `education_in_years` 15 (3..20), `retirement_age` 60 |
| income | `salary` inflation-linked, real raise 2.5 % |
| expenses | `living` essential; `school_fees` essential, **18,000 quarterly**, inflation 9 %, `end_month` = month before the education goal; `lifestyle` discretionary |
| debt | `car_loan` 3,00,000 at 9 %, EMI 10,000 (unchanged) |
| holdings | `h_cash` cash **6,00,000**; `h_eq` equity_index **8,00,000**; `h_ppf` govt_long **4,00,000** locked 10 years (earmark 3,00,000 to education as today) |
| profile / EF | risk 3, EF 6 months |
| goals | `home` must flex 6; `education` must, inflation 9 %; `retirement` must, target 2,85,00,000 (25 x 12 x 95,000) |

Quarterly fees keep month 0 positive (57,000) so "no negative surplus at defaults" holds.

**near_retirement** - "Eight years from retirement with substantial savings and rent from a second flat,
planning a family wedding."

| item | value |
|---|---|
| params | `age` 52 (45..65), `take_home` 2,00,000, `essentials` 70,000, `discretionary` 25,000, `retirement_age` 60 (50..75), `wedding_cost` 15,00,000, `wedding_in_years` 3 (1..10) |
| incomes | `salary` inflation-linked, real raise 1.5 %, `end_month` = month before retirement; `rent_in` "Rent from second flat" kind rental 20,000, inflation-linked, 0 %, not interruptible |
| expenses | `living` essential; `work_costs` "Work-related costs" 10,000 essential, `end_month` = month before retirement; `lifestyle` discretionary |
| holdings | `h_cash` cash 6,00,000; `h_eq` equity_index 55,00,000; `h_debt` short_debt 25,00,000; `h_lock` govt_long 45,00,000 locked 3 years |
| profile / EF | risk 2, EF 9 months |
| goals | `retirement` must, target 2,25,00,000 (25 x 12 x (95,000 - 20,000)); `wedding` nice flex 12 |

### 1.9 Results of the new design (measured with the real code by P1, 2026-10-17)

Re-measured by P1 with the repository code (`finance.run_plan(plan, FinanceRunRequest(seed=s))`, 2000 paths,
2 calibration rounds, `start_month = "2026-11"`, default `floor_step_pct_per_z = 2.0`: no band of 1.14 failed,
so the step size was not tuned). Chance is given for seeds 0 / 1 / 7; the other columns are identical for the
three seeds except where shown. All runs `feasible`, no hard violations.

| Template | Goal | Chance (seed 0 / 1 / 7) | Status | Shortfall | Growth share now / cap | z after calibration |
|---|---|---|---|---|---|---|
| young_professional | car | 2.2 / 1.7 / 1.5 % | at risk | 37,468 (4.2 %); median outcome 97 % of target | 0 % / 37.5 % (3 years: growth below FD after the margin) | 0.52 |
| | retirement | 88.6 / 89.5 / 88.3 % | on track | 0 | 75 % / 75 % (rest govt_long) | 1.29 |
| family | home | 89.7 / 86.2 / 87.0 % | on track | 0 | 0 % / 30 % (3 years) | 1.29 / 1.04 / 1.04 |
| | education | 88.0 / 88.3 / 89.1 % | on track | 0 | 60 % / 60 % (rest FD) | 1.29 |
| | retirement | 88.6 / 89.4 / 88.2 % | on track | 0 | 60 % / 60 % (rest govt_long/FD) | 1.29 |
| near_retirement | retirement | 90.7 / 90.5 / 90.6 % | on track | 0 | 34 % / 34 % (40 % x glide 0.85) | 1.29 |
| | wedding | 52.0 / 51.7 / 55.6 % | on track (nice, min 50 %) | 0 | 20 % / 20 % | 0.00 |

Fixes for the car: `DELAY_GOAL` (within flexibility), `INCREASE_SAVINGS`, `SPEND_LESS`, `REDUCE_TARGET`.
Funding (first year, seed 1): family surplus 69,167/month, plan invests 72,865/month: 67,569 from surplus,
5,297 from savings already held (EF already complete at the start); young professional surplus 22,000, of which
4,641 builds the EF, plan invests 17,353 (16,500 from surplus, 853 from savings); near retirement surplus
1,15,000, plan invests 1,14,538 (1,05,070 from surplus, 9,468 from savings); month-0 contribution 1,12,227 with
`investable[0] = 0` (EF still building). With `calibration_rounds = 4` the statuses and growth shares are the
same (calibration stops when every goal reaches its aim). Run times 0.25-1.6 s per template (default request).

Stress checks (architect's prototype, not re-measured): family with a 30 L home in 2 years -> home off track with fixes, education
and retirement on track; family home in 1 year -> 3/3; young with risk 2 -> retirement 40 % equity, on track.

### 1.10 Growth-asset decision, explained per goal (`advisor/explain.py`, `advisor/messages.py`)

New `GoalResult` fields: `growth_share_now_pct: float = 0.0` (risky share of `allocation_now_pct`),
`growth_cap_now_pct: float = 0.0` (`goal_cap` at the goal's first contribution block, else block 0, x 100).
New reason, always the **first** reason of every goal, chosen by the first matching rule:

| # | Condition | code | message template |
|---|---|---|---|
| 1 | no risky class in the goal's allowed classes | `GROWTH_NONE_RESTRICTED` | "{goal}: safer classes only, because you limited this goal to {names}." |
| 2 | growth share >= 1 % and a global equity cap or class cap binds in the first block | `GROWTH_LIMITED_GLOBAL` | "{goal}: about {share}% in growth assets, limited by your overall equity limit of {pct}%." |
| 3 | growth share >= 1 % and `D >= 120` | `GROWTH_HIGH` | "{goal}: about {share}% in growth assets ({names}) for now, because the goal is {years} away and your risk level {level} of 5 allows up to {base}%. The share steps down from {glide_month} as the goal gets closer." |
| 4 | growth share >= 1 % and `D < 120` | `GROWTH_LIMITED_TIME` | "{goal}: about {share}% in growth assets ({names}), because the goal is {years} away; at that distance the plan allows at most {cap}% (your risk level {level} of 5 allows {base}% for distant goals)." |
| 5 | growth cap now == 0, or `D < 84` | `GROWTH_NONE_SHORT` | "{goal}: safer classes only, because the goal is {years} away; growth assets can fall sharply over a few years." |
| 6 | otherwise | `GROWTH_NONE_RETURNS` | "{goal}: safer classes only, because under your return assumptions growth assets do not beat {safe} once the cautious margin is applied." |

`{years}`: "25 years", "3 years 6 months", "8 months". `{glide_month}`: first block month with cap < base
cap (`D - 120` months for the default glide). `{names}`: risky class names in the mix (", "-joined).
`{safe}`: name and planning return of the best safe class ("Fixed deposit at 0.8% after inflation").
Example (family retirement): "Retirement: about 60% in growth assets (Diversified equity index fund) for
now, because the goal is 25 years away and your risk level 3 of 5 allows up to 60%. The share steps down from
2041-11 as the goal gets closer."

Also new: binding `SHARED_SHORTFALL` when >= 2 goals of one tier have shortfall fraction > 0.001 within 0.01
of each other: "{count} {tier} goals are each short by about {pct}% because the plan spreads an unavoidable
shortfall fairly across them; to fund one fully, lower the priority of another." (`tier`: "must-have",
"should-have", "nice-to-have").

All new templates go into `MESSAGES`; compliance tests (forbidden words, every sentence matches a template)
cover them automatically.

### 1.11 "You can invest" vs "Plan invests": funding split (`pipeline.py`, `explain.py`, UI)

New `ResultSummary` fields (real, rounded 2 dp, `n = min(12, T)`, `X_t = pub.X_total[t]`):

| field | definition |
|---|---|
| `monthly_surplus_avg_12m` | `mean(proj.surplus[0:n])` |
| `monthly_ef_contribution_avg_12m` | `mean(proj.ef_contribution[0:n])` |
| `monthly_investable_avg_12m` | `mean(proj.investable[0:n])` |
| `monthly_contribution_avg_12m` | `mean(X[0:n])` |
| `monthly_from_surplus_avg_12m` | `mean(min(X_t, max(investable_t, 0)))` |
| `monthly_from_savings_avg_12m` | `monthly_contribution_avg_12m - monthly_from_surplus_avg_12m` |
| `savings_to_cash_at_start` | `proj.cash_buffer_initial + (1 - tau) * pub.sold_to_cash` (the same opening buffer `B` as `pipeline.py` uses, after the transaction cost `tau`) |

`monthly_investable_now` and `monthly_contribution_now` keep their month-0 meaning (API compatibility,
compare tables). Summary lines (replacing `SUMMARY_INVEST`, which stays in the catalog but is no longer
emitted), order: feasibility, surplus, funding, EF, top risk, then liquidity if fewer than 5 lines:

- `SUMMARY_SURPLUS`: "In the first year you have about {surplus}/month left after expenses and loans."
- `SUMMARY_SURPLUS_EF`: "In the first year you have about {surplus}/month left after expenses and loans; about {ef}/month of it first builds your emergency fund." (when `ef >= 1`)
- `SUMMARY_SURPLUS_NEGATIVE`: "In the first year your spending and loan payments are about {amount}/month more than your income." (when surplus avg < 0)
- `SUMMARY_FUNDING`: "The plan invests about {contributing}/month on average in the first year: {from_surplus} from your monthly surplus and {from_savings} from savings you already have." (when `from_savings >= 1`)
- `SUMMARY_FUNDING_SURPLUS`: "The plan invests about {contributing}/month on average in the first year, all from your monthly surplus."
- `SUMMARY_FUNDING_NONE`: "The plan needs no new monthly investments in the first year."

UI copy is in 3.4.

### 1.12 Amount ranges in the finance model (`model.py`, `preflight.py`, `explain.py`)

```python
class AmountRange(_Strict):
    low: Money
    high: Money        # model_validator: low <= high

IncomeStream.amount_range: AmountRange | None = None
Expense.amount_range: AmountRange | None = None
Goal.target_range: AmountRange | None = None
```

Informational only: the engine uses `amount` / `target_amount`. Intake sets them to the midpoint
`round((low + high) / 2, 2)`. Preflight warning `AMOUNT_OUTSIDE_RANGE` ("{name}: the amount {amount} is
outside the range you gave ({low} to {high})"), field path of the item. Explanation assumption line per item
with a range: `ASSUMPTION_RANGE` "{item}: you gave a range of {low} to {high}; the plan uses {used}."

### 1.13 Compatibility, engine version

- `FINANCE_ENGINE_VERSION = "fin-0.2.0"`.
- Stored plans keep their stored `assumptions` (asset returns, inflation): only new plans get the new
  defaults. Stored documents have no `caution` field and receive the default `CautionSettings`, so their
  next run uses the new margin (documented behaviour change, section 5). The Assumptions wizard step gets a
  "Reset to current defaults" button (3.4).
- Every new field is optional with a default; `schema_version` stays 1; export/import format unchanged.
- Mixed engine versions (review fix): a what-if built on a stored baseline from `fin-0.1.0` runs on
  `fin-0.2.0`, so its deltas would mix the engine change with the user's lever. `FinanceComparison`
  (`finance/compare.py`) gains `engine_versions_differ: bool` (true when `a.engine_version !=
  b.engine_version`). The what-if and compare screens show "These results come from different versions of
  the planner, so part of the difference is due to the update. Re-run your plan for a like-for-like
  comparison." with a "Re-run plan" button.

### 1.14 Tests (finance)

New, in `backend/tests/finance/`:

- `test_fin_realism_templates.py` (parametrised over the three templates, `seed` in {0, 1}, default request
  except `n_paths=1000`):
  - `min(proj.surplus[0:12]) >= 0` and `summary.monthly_surplus_avg_12m > 0` and
    `summary.monthly_investable_now >= 0`.
  - family: >= 2 of 3 goals with `success_probability >= 0.5`, and every must goal `status != "off_track"`.
  - near_retirement: retirement `status == "on_track"`; >= 1 of 2 goals with chance >= 0.5.
  - young_professional: retirement chance >= 0.5; car `status == "at_risk"`, `shortfall_fraction <= 0.10`
    and >= 1 fix (this is the fix the "Try this" e2e test clicks).
  - feasibility `feasible`, no hard violations, `assert_clean`.
- `test_fin_growth_assets.py`: for every template goal with `months_to_goal >= 120` and tolerance >= 3:
  `growth_share_now_pct >= 0.8 * growth_cap_now_pct` and max `risky_share_pct` over glide points with
  `months_to_goal >= 120` >= `0.8 * risky_cap_pct`; for goals < 36 months the risky share is <= the glide cap;
  the first reason code starts with `GROWTH_` and its message contains the goal name and the risk level.
- `test_fin_caution.py`: the properties of 1.5; equity > best safe class by >= 0.25 pp for
  `Y in {10, 15, 25, 35}`, `p in {0.5, 0.7, 0.85, 0.95, 0.99}` and `z - z0 in {0, 0.25, 0.5, 0.75, 1.0}`
  with default assumptions; the 1.5 table to 0.01 pp; `floor_share = 0` reproduces the old formula to
  1e-12; `CautionSettings` validation.
- Calibration keeps growth (review fix): family run with `calibration_rounds = 4` -> retirement
  `growth_share_now_pct >= 0.8 * growth_cap_now_pct`.
- Mixed versions: `compare_results` of a result with `engine_version = "fin-0.1.0"` and a current one ->
  `engine_versions_differ is True`; same version -> `False`.
- Compliance: the new `MESSAGES` entries contain none of `FORBIDDEN_WORDS` (note: "sure" is forbidden, so
  no "make sure") and no denylisted product names.
- `test_fin_linked_income.py`: linked income real amount flat at `growth 0`, interruptions zero it,
  simulator re-prices it, what-if income drop adds `whatif_income_drop_linked`.
- `test_fin_funding_split.py`: the definitions of 1.11, `from_surplus + from_savings == contribution` to 0.01,
  summary line selection.
- `test_fin_ranges.py`: `AmountRange` validation, `AMOUNT_OUTSIDE_RANGE`, `ASSUMPTION_RANGE` text.
- Calibration: a fixture with a goal at `min - 0.005` after round 0 gets `z` raised (aim test).

---

## 2. Part B - Flexible inputs before planning (`intake`)

### 2.1 Flow and principles

```
text / pasted table / CSV file
   -> extractor(s) -> Draft (+ provenance per field) -> questions
   -> user answers / accepts defaults / edits the draft (repeat: stateless POSTs)
   -> build: Draft -> Problem | FinancePlan  (+ preflight / cash-flow preview, nothing stored)
   -> user presses "Create plan" -> existing POST /api/v1/problems | /api/v1/finance/plans
```

- Stateless server: every intake request carries the whole draft; no DB table, no server session.
- A draft is never a plan: it may be incomplete; only `build` produces a document, and that document passes
  the normal Pydantic model and preflight checks, exactly like manual input.
- Deterministic rule-based extraction always runs. AI is optional, per request, and only adds or refines.
- Numbers the user typed win over AI guesses (2.11). The system never auto-runs an optimization.
- If something cannot be represented, say so (`UNSUPPORTED_RULE` note with the span); never drop silently.
- The original text is never stored by the server, never logged, and is not put into plan metadata.

### 2.2 Package layout

Pure engine-side package (no FastAPI, no DB); may import `superplanner.engine`, `superplanner.finance`,
`superplanner.templates`.

```
backend/superplanner/intake/
  __init__.py          public API (below)
  models.py            common models, drafts, questions, responses (2.3-2.5)
  text/
    segment.py         normalisation, lines/bullets/sentences with code-point offsets
    numbers.py         numbers, money, percent, frequency, ranges
    durations.py       durations and duration ranges
    dates.py           absolute and relative dates, months
    names.py           people/resource detection, fuzzy name matching
  schedule/
    extract.py         rule-based ScheduleDraft extraction
    questions.py       question generation
    answers.py         answer application
    build.py           ScheduleDraft -> Problem
  money/
    extract.py, questions.py, answers.py, build.py   (FinanceDraft equivalents)
  tables/
    parse.py           delimiter/header detection, CSV parsing
    mapping.py         header synonyms, column suggestions
    apply.py           rows -> draft items (both domains)
  extractors.py        Extractor protocol, RuleBasedExtractor, describe orchestration
  ai/
    client.py          AnthropicExtractor (the only module importing `anthropic`, lazily)
    schemas.py         AI output models (Pydantic)
    json_schema.py     strict_json_schema(model)
    prompts.py         system prompts
    merge.py           rule-based + AI merge
  messages.py          fallback reasons, question prompts, privacy notice (single catalog)

backend/superplanner/api/intake/
  __init__.py
  router.py            /api/v1/intake endpoints (2.15)
  schemas.py           request models
  service.py           settings -> options, AI client factory, concurrency slots
```

Public API (`superplanner/intake/__init__.py`):

```python
def describe_schedule(text: str, ctx: ExtractContext, *, ai: AiOptions | None = None) -> ScheduleIntakeResponse
def describe_finance(text: str, ctx: ExtractContext, *, ai: AiOptions | None = None) -> FinanceIntakeResponse
def answer_schedule(draft: ScheduleDraft, answers: list[Answer], ctx: ExtractContext) -> ScheduleIntakeResponse
def answer_finance(draft: FinanceDraft, answers: list[Answer], ctx: ExtractContext) -> FinanceIntakeResponse
def build_schedule(draft: ScheduleDraft, ctx: ExtractContext) -> ScheduleBuildResult
def build_finance(draft: FinanceDraft, ctx: ExtractContext) -> FinanceBuildResult
def parse_table(text: str, domain: Domain, *, delimiter: str = "auto", has_header: bool | None = None) -> TableParseResult
def apply_schedule_table(req: TableApply, ctx: ExtractContext, base: ScheduleDraft | None) -> ScheduleIntakeResponse
def apply_finance_table(req: TableApply, ctx: ExtractContext, base: FinanceDraft | None) -> FinanceIntakeResponse
```

All functions are synchronous, deterministic for the rule-based path, thread-safe (no module state).

### 2.3 Common models (`intake/models.py`)

All models `extra="forbid"` (shared `_Strict` base) unless marked as response-only.

```python
Domain = Literal["schedule", "finance"]
ScheduleKind = Literal["project", "study", "production", "generic"]

class ExtractContext(_Strict):
    today: date                                   # client's local date
    utc_offset: str = "+00:00"                    # ^[+-]\d{2}:\d{2}$
    locale: str = "en-IN"                         # en-IN | en-GB | en-US | other (date order, grouping)
    currency: str = "INR"                         # ^[A-Z]{3}$, finance default and money without marker
    kind: ScheduleKind | None = None              # schedule only; None = detect

class SourceSpan(_Strict):
    start: int = Field(ge=0)                      # offsets in Unicode code points of the submitted text
    end: int = Field(ge=0)                        # exclusive; end >= start
    text: str = Field(max_length=300)             # the covered text (for display / checks)

class CellRef(_Strict):
    row: int = Field(ge=0)                        # 0-based data row (header excluded)
    column: int = Field(ge=0)

class Provenance(_Strict):
    source: Literal["text", "table", "ai", "default", "answer", "edit", "derived"]
    confidence: float = Field(ge=0, le=1)
    span: SourceSpan | None = None
    cell: CellRef | None = None
    note: str = Field(default="", max_length=300)

class QuestionOption(_Strict):
    value: str
    label: str

class Question(_Strict):
    id: str                                       # f"{code}:{path or '-'}", stable across requests
    code: str                                     # catalog code, 2.8
    path: str | None                              # field the answer writes (provenance path syntax)
    kind: Literal["number", "money", "percent", "duration", "date", "month", "choice",
                  "multi_choice", "text", "confirm", "people", "working_time"]
    prompt: str
    help: str = ""
    options: list[QuestionOption] = []
    default: Any | None = None                    # JSON value in the answer format of `kind`
    default_label: str = ""                       # "Mon-Fri 09:00-17:00"
    required: bool                                # needed for `build` to succeed
    reason: Literal["missing", "ambiguous", "low_confidence", "conflict", "confirm_default"]
    span: SourceSpan | None = None
    error: str | None = None                      # set when a previous answer could not be used

class Answer(_Strict):
    question_id: str
    value: Any | None = None                      # answer format of the question kind (2.8)
    use_default: bool = False
    skip: bool = False                            # optional questions only; recorded in draft.dismissed

class IntakeNote(_Strict):
    code: str                                     # UNSUPPORTED_RULE, AI_NOTE, KEPT_TYPED_NUMBER, ...
    severity: Literal["info", "warning"]
    message: str
    span: SourceSpan | None = None

class ExtractorInfo(_Strict):
    requested: Literal["rule", "ai"]
    used: Literal["rule", "ai+rule"]
    ai_available: bool
    fallback_code: str | None = None              # 2.10 table
    fallback_message: str | None = None           # user-facing
    model: str | None = None                      # "claude-opus-5-5" when AI was used
```

**Provenance paths**: `/<collection>/<item key>/<field>` or `/<field>` / `/<group>/<field>`, using item
`key`s (not indexes) so client edits and deletions do not shift them. Examples: `/start_date`,
`/working_time`, `/tasks/t3/duration`, `/tasks/t3/after`, `/resources/r_ravi/name`, `/profile/age`,
`/incomes/i1/amount`, `/goals/g2/target_month`. Item keys match `^[a-z][a-z0-9_]{0,31}$`; rule-based keys
are `t1..tn`, `r_<slug>`, `i1..`, `e1..`, `d1..`, `h1..`, `g1..`; table rows use `row<k>`. Each draft keeps
`provenance: dict[str, Provenance]`; a missing entry means `edit` (user-entered in the review editor; the UI
sets `{"source": "edit", "confidence": 1}` when it changes a field).

Confidence levels (UI): high >= 0.8, medium 0.5-0.8, low < 0.5. Rule-based assignment: explicit pattern
with unit 0.95; number with inferred unit or frequency 0.7; "about/around" 0.8; detected person name 0.7;
dependency from wording ("after", "once") 0.9; implied by list order 0.6; fuzzy-resolved reference 0.8;
derived (e.g. retirement target) 0.5; default 0.3. AI: `min(ai_confidence, 0.8)`, and 0.5 when its source
quote is not found in the text.

### 2.4 `ScheduleDraft`

```python
DurationUnit = Literal["minutes", "hours", "days", "weeks"]

class DraftDuration(_Strict):
    optimistic: float = Field(gt=0, le=10000)
    likely: float = Field(gt=0, le=10000)
    pessimistic: float = Field(gt=0, le=10000)
    unit: DurationUnit
    # validator: optimistic <= likely <= pessimistic. A single value: all three equal.
    # A two-value range "a-b": optimistic=a, pessimistic=b, likely=(a+b)/2.

class TimeWindow(_Strict):
    start: HHMM
    end: HHMM                                      # start < end, "24:00" allowed as end

class WorkingTime(_Strict):
    days: list[Weekday] = Field(min_length=1)      # days using `windows`
    windows: list[TimeWindow] = Field(min_length=1, max_length=4)
    weekend_windows: list[TimeWindow] | None = None   # if set, used on sat/sun (study plans)

class DraftResource(_Strict):
    key: DraftKey
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["person", "machine", "room", "equipment", "generic"] = "generic"
    count: int = Field(default=1, ge=1, le=50)     # "2 machines" -> one draft resource, count 2

class DraftTask(_Strict):
    key: DraftKey
    name: str = Field(min_length=1, max_length=200)
    milestone: bool = False
    duration: DraftDuration | None = None          # None on an activity -> required question
    after: list[DraftKey] = []                     # finish-to-start predecessors (task keys)
    resources: list[DraftKey] = []                 # resource keys
    resource_mode: Literal["any", "all"] = "any"   # any = one requirement over all of them; all = each
    deadline: date | None = None
    deadline_hard: bool = False
    earliest_start: date | None = None
    priority: int | None = Field(default=None, ge=1, le=10)
    group: str | None = Field(default=None, max_length=200)
    notes: str = Field(default="", max_length=2000)

class ScheduleDraft(_Strict):
    domain: Literal["schedule"] = "schedule"
    kind: ScheduleKind = "generic"
    name: str = Field(default="My plan", min_length=1, max_length=200)
    start_date: date | None = None
    horizon_days: int | None = Field(default=None, ge=1, le=366)   # None = derived at build
    working_time: WorkingTime | None = None                        # None = default of kind
    objective: Literal["balanced", "finish_asap", "meet_deadlines", "lowest_cost"] | None = None
    tasks: list[DraftTask] = Field(default_factory=list, max_length=500)
    resources: list[DraftResource] = Field(default_factory=list, max_length=100)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    dismissed: list[str] = Field(default_factory=list, max_length=500)  # skipped optional question ids
```

`DraftKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")]`. Validators (model level):
keys unique per collection; `after`/`resources` reference existing keys (else 422 on intake endpoints:
the client edited inconsistently); no self-dependency. Cycles are allowed in a draft and reported by build
preflight (`DEPENDENCY_CYCLE`).

Kind defaults (also used by questions as defaults):

| kind | terminology | working time | default unit | default resource | objective |
|---|---|---|---|---|---|
| project | `templates.project.TERMS` | Mon-Fri 09:00-17:00 | days | "Me" (person) | meet_deadlines if any deadline else finish_asap |
| study | `templates.exam_prep.TERMS` | Mon-Fri 18:00-21:00; Sat-Sun 09:00-13:00, 14:00-18:00 | hours | "Study time" (generic) | meet_deadlines |
| production | `templates.manufacturing.TERMS` | Mon-Sat 06:00-14:00, 14:00-22:00 | hours | "Machine" (machine) | meet_deadlines |
| generic | `Terminology()` | Mon-Fri 09:00-17:00 | days | "Me" (person) | balanced |

Kind detection when `ctx.kind is None`: count cue words (study: exam, study, revise, syllabus, chapter,
mock, subject; production: machine, order, batch, job, shift, operation, assembly; project: launch,
release, client, sprint, design, build, deploy, milestone); highest count >= 2 wins, else `generic`.

### 2.5 `FinanceDraft`

```python
class DraftAmount(_Strict):
    low: float = Field(ge=0, le=1e12)
    high: float = Field(ge=0, le=1e12)            # low <= high; exact amount: low == high

class DraftProfile(_Strict):
    age: int | None = Field(default=None, ge=16, le=100)
    retirement_age: int | None = Field(default=None, ge=40, le=80)
    risk_tolerance: int | None = Field(default=None, ge=1, le=5)
    currency: str = "INR"
    locale: str = "en-IN"

class DraftIncome(_Strict):
    key: DraftKey; name: str
    kind: Literal["salary", "business", "rental", "pension", "interest", "other"] = "salary"
    amount: DraftAmount | None = None
    frequency: Frequency = "monthly"
    growth_pct: float | None = None               # yearly raise above inflation (linked)
    inflation_linked: bool = True
    interruptible: bool = True
    end_month: Month | None = None

class DraftExpense(_Strict):
    key: DraftKey; name: str
    category: str = "other"
    amount: DraftAmount | None = None
    frequency: Frequency = "monthly"
    essential: bool | None = None                 # None -> optional question, default True
    inflation_pct: float | None = None
    end_month: Month | None = None

class DraftDebt(_Strict):
    key: DraftKey; name: str
    kind: Literal["home", "vehicle", "education", "personal", "credit_card", "other"] = "other"
    balance: DraftAmount | None = None
    interest_rate_pct: float | None = Field(default=None, ge=0, le=60)
    emi: DraftAmount | None = None
    remaining_months: int | None = Field(default=None, ge=1, le=600)

class DraftHolding(_Strict):
    key: DraftKey; name: str
    asset_class_id: str | None = None             # default class ids (1.4); None -> question
    amount: DraftAmount | None = None
    locked_until_month: Month | None = None

class DraftGoal(_Strict):
    key: DraftKey; name: str
    kind: Literal["retirement", "education", "home", "vehicle", "travel", "wedding", "business", "other"] = "other"
    target: DraftAmount | None = None             # None for retirement -> derived at build
    target_month: Month | None = None
    priority: Priority | None = None
    flexibility_months: int = Field(default=0, ge=0, le=120)
    inflation_pct: float | None = None

class FinanceDraft(_Strict):
    domain: Literal["finance"] = "finance"
    name: str = "My financial plan"
    start_month: Month | None = None              # None -> month of ctx.today
    profile: DraftProfile = Field(default_factory=DraftProfile)
    incomes: list[DraftIncome] = Field(default_factory=list, max_length=20)
    expenses: list[DraftExpense] = Field(default_factory=list, max_length=100)
    debts: list[DraftDebt] = Field(default_factory=list, max_length=20)
    holdings: list[DraftHolding] = Field(default_factory=list, max_length=50)
    goals: list[DraftGoal] = Field(default_factory=list, max_length=12)
    emergency_fund_months: float | None = Field(default=None, ge=0, le=24)
    provenance: dict[str, Provenance] = Field(default_factory=dict)
    dismissed: list[str] = Field(default_factory=list, max_length=500)
```

### 2.6 Extractor interface and orchestration (`intake/extractors.py`)

```python
@dataclass
class ScheduleExtraction:
    draft: ScheduleDraft
    notes: list[IntakeNote]

@dataclass
class FinanceExtraction:
    draft: FinanceDraft
    notes: list[IntakeNote]

class Extractor(Protocol):
    name: Literal["rule", "ai"]
    def extract_schedule(self, text: str, ctx: ExtractContext) -> ScheduleExtraction: ...
    def extract_finance(self, text: str, ctx: ExtractContext) -> FinanceExtraction: ...

class AiFallback(Exception):
    def __init__(self, code: str, message: str): ...      # raised by the AI extractor only

@dataclass(frozen=True)
class AiOptions:
    requested: bool                                # the user's per-request opt-in
    enabled: bool                                  # settings.intake_ai_enabled
    client_factory: Callable[[], Any] | None       # returns an anthropic.Anthropic-compatible client
    timeout_seconds: float = 60.0
    max_retries: int = 2
    acquire_slot: Callable[[], bool] | None = None # concurrency limiter (api/intake/service.py)
    release_slot: Callable[[], None] | None = None
```

`describe_<domain>(text, ctx, ai)`:
1. Validate `len(text) <= 20000` code points and non-blank (else `IntakeTextError` -> 422 `TEXT_TOO_LONG` /
   `TEXT_EMPTY`).
2. `R = RuleBasedExtractor().extract_<domain>(text, ctx)` (always).
3. If `ai and ai.requested`: availability check (2.10); if available, `A = AnthropicExtractor(...)
   .extract_<domain>(text, ctx)`; `AiFallback` -> `ExtractorInfo(used="rule", fallback_code, fallback_message)`;
   success -> `draft = merge(R, A)` (2.11), `used="ai+rule"`.
4. Questions from the final draft (2.8); `ready = no required questions and build succeeds`.

### 2.7 Rule-based extractor: grammar

Implementation: regular expressions over a normalised copy of the text with a code-point offset map back
to the original (normalisation: Unicode NFKC, curly quotes to straight, en/em dash to "-", non-breaking
space to space, "₹" kept). Matching is case-insensitive unless stated. Every extracted value records the
span of the phrase it came from.

Safety (review fix): every pattern must run in linear time on 20,000 code points (no nested unbounded
quantifiers such as `(\w+\s?)+`; candidate names and lists are bounded, e.g. `{1,80}`); a 20,000-character
adversarial text (repeated digits, commas, capitalised words, bullets) is processed in < 2 s. Cue lists in
`money/extract.py` may contain product words such as `ppf`; user-facing text in `intake/messages.py` and
`ai/prompts.py` must not (the finance denylist and `FORBIDDEN_WORDS` checks are applied to both files, with
the finance `ALLOWLIST`).

**2.7.1 Segmentation** (`text/segment.py`)
- Lines; a bullet line matches `^\s*([-*•·]|\d{1,3}[.)]|[a-zA-Z][.)])\s+`; numbered bullets set
  `numbered = True`.
- Non-bullet lines split into sentences at `[.!?;]` followed by space or end, not inside numbers
  (`1.5`), abbreviations (`Rs.`, `p.a.`, `e.g.`, `i.e.`) or times (`9.30`).
- Inline lists: after a colon, items separated by `,` / ` and ` (`"Steps: design, build and test"`).
- Then-chains: items joined by `then` / `->` / `→` / `>` form an ordered list (`A, then B, then C`).

**2.7.2 Numbers and money** (`text/numbers.py`)
- Digits: Indian grouping `\d{1,2}(,\d{2})*,\d{3}` (`12,50,000`), Western `\d{1,3}(,\d{3})+`, plain `\d+`,
  optional `.\d+`. Commas are removed.
- Words: one..twenty, thirty..ninety, hundred, a/an (= 1 before a unit), half (0.5), a couple of (2,
  confidence 0.6), a few (3, confidence 0.4), dozen (12).
- Multipliers: `k|K|thousand` 1e3; `L|l|lakh|lakhs|lac|lacs|lk` 1e5; `cr|crore|crores` 1e7;
  `m|mn|million` 1e6 (money context only); `b|bn|billion` 1e9.
- Currency markers: `₹`, `Rs`, `Rs.`, `INR`, `rupee(s)` -> INR; `$`, `USD` -> USD; `€`, `EUR` -> EUR.
  Prefix or suffix. Money without marker uses `ctx.currency`. Mixed currencies -> note `MIXED_CURRENCY`.
- Ranges: `X - Y`, `X to Y`, `between X and Y`, `X–Y`; a multiplier or currency on only one side applies to
  both (`40-50k` = 40,000-50,000; `1.2 to 1.5 lakh`). Produces `DraftAmount(low, high)`.
- Approximation words `about|around|approx(imately)?|roughly|nearly|~` lower confidence to 0.8.
- Percent: `X %`, `X percent`, `X pc`; `p.a.` ignored.
- Frequency (`Frequency`): monthly `per month|a month|each month|every month|monthly|/month|/mo|pm|p\.m\.`;
  yearly `per year|a year|annually|yearly|per annum|p\.a\.|/yr|/year|every year`; quarterly
  `per quarter|quarterly|every quarter|every 3 months`; half_yearly `half-yearly|every 6 months|twice a year`;
  once `one-time|once|lump sum`. Absent: incomes/expenses monthly (confidence 0.7), goals/holdings once.

**2.7.3 Durations** (`text/durations.py`)
- `NUM [range] UNIT`: minutes `min|mins|minute(s)`; hours `h|hr|hrs|hour(s)`; days `d|day(s)`; weeks
  `w|wk|wks|week(s)`; months `month(s)` -> weeks x 4.33 (confidence 0.7, note).
- Phrases: "half a day" 0.5 days, "half an hour" 30 min, "an hour and a half" 1.5 h, "a day", "a week".
- Ranges: `2-3 weeks`, `2 to 3 days`, `between 2 and 3 days`. Three-point: `2/3/5 days`,
  `optimistic 2, likely 3, pessimistic 5 days`, `3 days (2-5)`, `best 2 worst 5 days, probably 3`.
- `90 min` -> 90 minutes; `1.5h` -> 1.5 hours.

**2.7.4 Dates** (`text/dates.py`, reference `ctx.today`, `ctx.locale`)
- ISO `YYYY-MM-DD`; `DD/MM/YYYY` (en-IN, en-GB, other) or `MM/DD/YYYY` (en-US); if both parts <= 12 and the
  locale is not one of those three -> question `DATE_AMBIGUOUS`.
- `12 Nov 2026`, `Nov 12, 2026`, `12th November`; missing year = next occurrence on or after today.
- Month-year `March 2027`, `Mar '27`: deadline = last day of that month; finance = that month.
- Relative: today, tomorrow, `next <weekday>` = first such weekday strictly after today, `this <weekday>` =
  on or after today within 7 days, `in N days|weeks|months|years`, `within N weeks` (deadline),
  `end of (this|next) (week|month|year)`, `N years from now`, `next year` (finance: start + 12 months).
- Role words: `by|before|no later than|latest|due` -> deadline (hard if `no later than|must|hard|latest|
  at the latest|strict`); `after <date>|from|not before|starting|start(s|ing)? on` -> earliest_start / start.
- Finance age phrases: `retire at N`, `when I'm N`, `at age N` -> month from `profile.age` (question if age
  unknown).

**2.7.5 Tasks** (schedule)
- Every bullet/list item is a task; in prose, a sentence with a task verb (`build|write|design|test|prepare|
  study|revise|review|cut|assemble|paint|pack|deliver|install|plan|launch|finish|complete|do|make`) or a
  duration is a task. The name is the item text with recognised duration/date/resource/dependency phrases
  and leading filler (`we need to`, `I have to`, `then`) removed, trimmed to 80 characters, first letter
  upper-case; empty -> "Task N".
- Milestone: no duration and name matches `launch|release|go-live|deadline|exam|delivery|handover|
  milestone|submission|demo day` -> `milestone = True` (confidence 0.7).
- Counts: `N <noun>s` with a task-like noun (`mock tests?|chapters?|modules?|units?|lessons?|orders?|jobs?|
  batches?|episodes?|interviews?`) -> N tasks "<Noun> 1..N" sharing the item's duration (note
  `EXPANDED_COUNT`).
- Study specifics: `exam (on|in|by) <date>` / `N days to prepare` -> milestone "Exam" with hard deadline;
  `subjects?: a, b, c` -> groups; `revise (everything|it all|each) twice|N times` -> per study task, N
  revision tasks "Revise <x> (k/N)" after it (confidence 0.6); missing study durations default 6 hours
  (question).
- Production specifics: `N (orders|jobs|batches)` + `each (needs|goes through|is) A, B and C` -> N groups
  with operation chains A -> B -> C (confidence 0.6).

**2.7.6 Dependencies** (schedule)
- Within an item: `after X`, `once X (is )?(done|finished|complete|completed|ready|approved)`,
  `when X is (done|...)`, `following X`, `depends on X`, `requires X`, `needs X (first|done)` -> item after X;
  `before X` -> X after item.
- Across sentences: `X before Y`, `Y after X`, `X then Y`, `X -> Y`, `X must be done before Y`,
  `Y can start when X ends` -> `Y.after += X`.
- `after everything else|after all of the above|at the end` -> after every task without a successor.
- `in parallel with X|at the same time as X` -> no dependency (note `PARALLEL`).
- Numbered lists: items with no explicit predecessor get the previous item as predecessor (confidence 0.6)
  and one `SCHED_SEQUENTIAL` confirm question (default yes; "no" removes the implied links).
- Reference resolution: normalise (lower-case, drop stop words, strip plural s / -ing / -ed); exact
  substring of a task name -> 0.95; else best token-Jaccard >= 0.5 and >= 0.15 above the runner-up -> 0.8;
  else question `SCHED_DEP_REFERENCE` (choice: top 3 + "None of these").

**2.7.7 Resources** (schedule)
- Counted nouns: `(N|two|...) (machines|people|developers|designers|testers|operators|workers|teachers|
  ovens|lathes|printers|rooms|trucks|cnc machines)` -> `DraftResource(count=N, kind)` (noun table: machine,
  equipment, room, person).
- `team of N` -> person resource "Team member" count N.
- Names: capitalised tokens (not sentence-initial unless followed by `will|can|does|is|should|to|has`)
  that are not month/day names, stop words, known nouns or task-name tokens, joined by `,`/`and`
  (`Ravi and Priya`) -> person resources (confidence 0.7, one `SCHED_PEOPLE` confirm question listing them).
  `I`/`me` -> resource "Me".
- Assignment: `(by|with|assign(ed)? to|owner:?) NAME`, `NAME (will|can|should|does) <task words>`, trailing
  `(NAME)` or `, NAME` on an item, `A: NAME` -> `task.resources += [NAME]`. `NAME and NAME together|both` ->
  `resource_mode = "all"`.

**2.7.8 Working time** (schedule)
- `N hours (on|every) weekdays|a day` -> weekday window starting at the kind's start (study 18:00, else
  09:00), `N hours on weekends` -> weekend windows from 09:00; N > 4 splits into two windows with a 1 h
  break at 13:00. `9 to 5|9am-5pm|09:00-17:00` -> window. `Monday to Friday|weekdays|Mon-Sat|every day` ->
  days. `no weekends` -> Mon-Fri. Shifts: `two shifts` -> production default windows.

**2.7.9 Finance phrases** (`money/extract.py`), per sentence, first matching class wins:

| class | cues (with a money expression) | result |
|---|---|---|
| income | `earn|salary|take[- ]?home|income|get paid|stipend|pension|freelance|business income|rent (income|from)|tenant pays` | `DraftIncome`; kind: pension / rental (`rent from|rental|tenant`) / business (`business|freelance|consult`) / salary; `my (wife|husband|partner|spouse) earns` -> separate income "Partner's salary" |
| gross pay | `ctc|gross|cost to company|before tax|lpa` | note `GROSS_INCOME` + required `FIN_TAKE_HOME` question (tax is not modelled) |
| debt | `loan|emi|mortgage|credit card|outstanding|borrowed` | `DraftDebt`: `EMI X` -> emi; `X (left|outstanding|balance|remaining|pending)` -> balance; `at X%`/`X% interest` -> rate; `N (months|years) left` -> remaining_months; kind by noun (home/car->vehicle/education/personal/credit card) |
| holding | `have|saved|savings|invested|in (fd|fixed deposits?|mutual funds?|sip|stocks?|shares|equity|index funds?|ppf|epf|provident fund|nps|gold|bank|savings account|debt funds?|bonds?)` | `DraftHolding`; class: fd/fixed deposit -> fixed_deposit; mutual fund/sip/stocks/shares/equity/index -> equity_index; ppf/epf/provident/nps -> govt_long (+ `FIN_HOLDING_LOCK` question); gold -> gold; bank/savings/cash -> cash; debt fund/bond -> short_debt |
| goal | `save|need|want|goal|target|plan(ning)? to|buy|for (a|my|our|the)|retire|retirement` | `DraftGoal`; kind: house/home/flat/apartment/down payment -> home; car/bike/vehicle -> vehicle; education/college/school/university/mba/degree -> education; wedding/marriage -> wedding; trip/travel/vacation/holiday -> travel; retire -> retirement; business/startup/shop -> business; else other. Priority: `must|need|have to|essential|non-negotiable` -> must; `would like|nice|maybe|if possible|dream` -> nice; else retirement/education must, others should |
| expense | `spend|expenses?|costs?|pay|rent|groceries|bills|fees|insurance|premium|household|living|tuition|utilities|maid|fuel|petrol|school` | `DraftExpense`; category and essential from the table below |
| emergency fund | `emergency fund` + `N months` or money | `emergency_fund_months` (money -> months = amount / essential monthly, derived 0.5) |

Expense categories: rent/housing/household/living/groceries/food/utilities/bills/electricity -> essential
"living"; school/tuition/fees/education -> essential "education", `inflation_pct` 9 (note
`EDUCATION_INFLATION`); insurance/premium/medical -> essential "insurance"/"health"; transport/fuel/petrol ->
essential "transport"; eating out/shopping/entertainment/subscriptions/travel/fun/lifestyle -> discretionary
"lifestyle"; otherwise `essential = None` (question, default essential).

Profile: `I'm N|I am N|N years old|age N|aged N` -> age; risk words `conservative|low risk|safe|cautious`
-> 2, `moderate|balanced|medium` -> 3, `growth|aggressive|high risk` -> 4, `very aggressive` -> 5,
`risk N/5|N out of 5` -> N.

**2.7.10 Unsupported rules.** A sentence containing a rule cue (`only|never|not on|no more than|at most|
at least|maximum|minimum|every other|alternate|unless|except|budget|cost limit`) that produced no
extraction becomes `IntakeNote(code="UNSUPPORTED_RULE", severity="warning", message="I could not turn this
into a plan rule: \"...\". Add it by hand after creating the plan, or rephrase it.", span=...)`.

### 2.8 Questions and answers

Questions are a pure function `questions(draft, ctx) -> list[Question]` recomputed after every request.
A question is not generated when its path has provenance `answer` or `edit`, or its id is in
`draft.dismissed`. Order: required first, then in document order. The UI shows them one at a time.

Answer formats: `number`/`percent` float; `money` float or `{"low": f, "high": f}`; `duration`
`DraftDuration` JSON; `date` "YYYY-MM-DD"; `month` "YYYY-MM"; `choice` option value; `multi_choice` list of
values; `text` string; `confirm` bool; `people` list of names; `working_time` `WorkingTime` JSON. Any kind
also accepts `{"text": "..."}`, parsed with the same grammar ("2-3 days", "40-50k", "March 2027"); if it
cannot be parsed the question is returned again with `error`. `use_default` writes `question.default`;
`skip` (optional only) appends the id to `dismissed`. Applied answers set provenance
`{"source": "answer", "confidence": 1.0}`. Unknown `question_id` -> 422 `UNKNOWN_QUESTION`.

Schedule questions:

| code | kind | required | when | default |
|---|---|---|---|---|
| `SCHED_NO_TASKS` | text | yes | no tasks | - ("List the tasks, one per line") |
| `SCHED_TASK_DURATION` | duration | yes | activity without duration | 1 day (project/generic), 2 h (study), 1 h (production) |
| `SCHED_DEP_REFERENCE` | choice | yes | unresolved dependency reference | - |
| `SCHED_DATE_AMBIGUOUS` | choice | yes | ambiguous numeric date | locale order |
| `SCHED_START_DATE` | date | no | no start date | next working day on or after today |
| `SCHED_SEQUENTIAL` | confirm | no | implied list-order dependencies | true |
| `SCHED_PEOPLE` | confirm | no | detected names | true |
| `SCHED_WHO` | multi_choice | no | an activity without resources while the draft has >= 2 resources | all resources, mode any |
| `SCHED_WORKING_TIME` | working_time | no | working time not given | kind default (2.4) |
| `SCHED_LOW_CONFIDENCE` | confirm | no | a value with confidence < 0.5 that is not a default | true |

Finance questions:

| code | kind | required | when | default |
|---|---|---|---|---|
| `FIN_INCOME` | money | yes | no income with amount | - |
| `FIN_TAKE_HOME` | money | yes | gross pay mentioned | - |
| `FIN_GOAL_TARGET` | money | yes | non-retirement goal without target | - |
| `FIN_GOAL_DATE` | month | yes | goal without date | start + 5 years |
| `FIN_AGE` | number | yes if any date depends on age or a retirement goal exists | age unknown | - |
| `FIN_RETIREMENT_TARGET` | money | no | retirement target derived | 1.8 retirement preset |
| `FIN_ESSENTIALS` | money | no | no expenses | 50 % of income |
| `FIN_DISCRETIONARY` | money | no | no discretionary expense | 0 ("None") |
| `FIN_EXPENSE_ESSENTIAL` | confirm | no | `essential is None` | true |
| `FIN_DEBT_BALANCE` | money | yes | debt without balance | - |
| `FIN_DEBT_RATE` | percent | no | debt without rate | home 8.5, vehicle 9.5, education 10, personal 13, credit card 36, other 12 |
| `FIN_HOLDING_CLASS` | choice | no | holding without class | cash |
| `FIN_HOLDING_LOCK` | month | no | govt_long holding without lock date | start + 15 years |
| `FIN_GOAL_PRIORITY` | choice | no | priority not stated | per 2.7.9 |
| `FIN_RISK` | choice | no | risk unknown | 3 |
| `FIN_EF_MONTHS` | number | no | not stated | 6 |
| `FIN_LOW_CONFIDENCE` | confirm | no | as for schedule | true |

Prompts are plain language from `intake/messages.py`, e.g. `SCHED_TASK_DURATION`: "How long will
\"{task}\" take? A range like \"2-3 days\" is fine."; `FIN_RETIREMENT_TARGET`: "For retirement we suggest
saving {amount} (25 years of your regular spending, in today's money). Keep it or enter your own amount.".

### 2.9 Builders

**2.9.1 `build_schedule(draft, ctx) -> ScheduleBuildResult`**

```python
class ScheduleBuildResult(BaseModel):            # response-only
    ready: bool                                  # problem built and report.ok
    problem: Problem | None
    report: ValidateReport | None                # engine.analyze(problem): preflight + CPM
    blocking: list[Question]                     # required questions still open (problem None if any)
    parts: dict[str, list[str]]                  # draft task key -> problem task ids (split parts)
    duration_summary: DurationSummary | None
```

Steps (deterministic):
1. Required questions open -> `problem = None`, `blocking`.
2. Defaults: `start_date` (next working day), `working_time` and terminology by kind, objective (2.4).
3. Calendar: `weekly` from `working_time` (weekend windows on sat/sun). `minutes_per_day` = total weekly
   window minutes / number of days with windows; `minutes_per_week` = total weekly window minutes;
   `max_part` = shortest window length in the week (>= 30, else the longest).
4. Resources: `count == 1` -> `Resource(id=key, name, kind, capacity=1, calendar)`; `count = n` -> ids
   `f"{key}_{i}"`, names `f"{name} {i}"`. No resource at all -> the kind's default resource with id `r_me`.
5. Durations: unit minutes x 1, hours x 60, days x `minutes_per_day`, weeks x `minutes_per_week`; each of
   o/m/p rounded to whole minutes (>= 1); `E = pert_minutes(o, m, p)` (2.14).
6. Splitting: an activity with `E > max_part` becomes `n` parts, `n` = smallest integer >= `ceil(E / max_part)`
   for which every part's PERT value <= `max_part`; part `i` gets `o_i, m_i, p_i` = integer division of o, m,
   p by `n` with the remainder minutes on the first parts; `duration_minutes = pert_minutes(o_i, m_i, p_i)`;
   `duration_estimate` only when `o < p`. Parts chained FS; ids `f"{key}_{i}"`, names `"{name} ({i}/{n})"`,
   `group` = draft group or task name; `metadata = {"intake_key": key, "part": i, "parts": n}`.
7. Requirements: `resource_mode any` -> one `Requirement(alternatives=all expanded ids)`; `all` -> one
   requirement per draft resource; empty `resources` -> if exactly one resource exists, that one; else all
   person/machine resources as alternatives (mode any). Milestones have none.
8. Dependencies: `after` edges FS from the predecessor's last part to the successor's first part.
9. Dates: deadline -> end of the last window on that date (local, `utc_offset`), or 23:59 if none, on the
   last part; earliest_start -> start of the first window that day, or 00:00, on the first part.
10. Horizon: `horizon_start` = `start_date 00:00` at `utc_offset`; `horizon_days` = draft value or
    `clamp(max(d_last + 7, ceil(1.5 * 7 * W / (minutes_per_week * max(1, R))) + 7), 7, 366)` with `d_last` =
    days from start to the latest deadline, `W` total work minutes, `R` number of expanded resources.
11. `Problem(id="draft", name, domain=DOMAIN_OF_KIND[kind], currency=ctx.currency, terminology,
    tasks, resources, dependencies, objectives=Objectives(preset=objective), metadata={"intake": {"version":
    1, "source": "describe"|"table", "extractor": "rule"|"ai+rule"}})`. Pydantic errors here are a bug in
    the builder (500 + log), never shown as user errors.
12. `report = engine.analyze(problem)`; `ready = report.ok`.

`DOMAIN_OF_KIND = {"project": "project", "study": "exam_prep", "production": "manufacturing", "generic":
"generic"}` (review fix): existing documents and the plan list (`PlanList.tsx` `DOMAIN_LABEL`) use the
template domains `exam_prep` / `manufacturing`; `"study"` / `"production"` would show as raw words. The
same mapping is used by "Build step by step" (3.1).

`DurationSummary`: `{tasks_with_range: int, expected_work_minutes: int, optimistic_work_minutes: int,
pessimistic_work_minutes: int}` (sums over activities).

**2.9.2 `build_finance(draft, ctx) -> FinanceBuildResult`**

```python
class FinanceBuildResult(BaseModel):             # response-only
    ready: bool
    plan: FinancePlan | None
    preflight: FinancePreflightReport | None
    cashflow: CashflowSummary | None             # finance.summarize_cashflow when preflight ok
    blocking: list[Question]
```

Mapping: ids = draft keys; `amount = round((low + high) / 2, 2)` and `amount_range` when `low < high`
(1.12); incomes `inflation_linked` and `growth_pct` (None -> 0); expenses `essential` None -> True;
debts: EMI missing but balance, rate and remaining months known -> EMI from the annuity formula (note),
otherwise required question; holdings class None -> cash; retirement goal without target ->
`templates.retirement_target(...)` (provenance derived); goal date from age when given as an age;
`profile` defaults (risk 3, retirement_age 60); `emergency_fund.months_of_essentials` (default 6);
`start_month` (default month of `ctx.today`); assumptions = current defaults;
`metadata = {"intake": {...}}` as for scheduling. Then `finance.preflight(plan)` and, if ok,
`summarize_cashflow(project_cashflow(plan))`.

### 2.10 AI extractor (Anthropic) - exact contract (`intake/ai/client.py`)

Dependency: `anthropic==1.15.0` in `backend/requirements.txt` and `pyproject.toml` `dependencies`, and
installed into `backend/.venv` (`.venv/bin/pip install anthropic==1.15.0`; it is not installed today; LEAD
dry-run: no conflict with the pinned pydantic/httpx; it pulls `httpx2`, `httpcore2`, `jiter`,
`docstring_parser`, `sniffio`, `truststore`). Imported lazily inside `client.py` only; `ImportError` ->
unavailable (`AI_SDK_MISSING`).

Availability (`ai_status(options) -> (available: bool, code: str | None)`), evaluated per request:
`not options.enabled` -> `AI_DISABLED`; SDK import fails -> `AI_SDK_MISSING`; client creation fails or
`not (getattr(client, "api_key", None) or getattr(client, "auth_token", None) or getattr(client,
"credentials", None))` -> `AI_NO_CREDENTIALS`. Review fix: SDK 1.15.0 also resolves credentials from
`ANTHROPIC_PROFILE`, workload-identity variables and the on-disk active profile into `client.credentials`
(with `api_key`/`auth_token` left `None`); checking only the two static attributes would report "no
credentials" on a correctly configured server. Tests cover all three attributes with fake clients.
The default factory is `lambda: anthropic.Anthropic(timeout=settings.intake_ai_timeout_seconds,
max_retries=settings.intake_ai_max_retries)` (credentials resolved by the SDK from the environment,
`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`). Tests inject `client_factory`.

The call (no other SDK APIs are used):

```python
client = options.client_factory()        # default: anthropic.Anthropic(timeout=60.0, max_retries=2)
resp = client.beta.messages.create(
    model="claude-opus-5-5", max_tokens=16000,
    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    system=SYSTEM_PROMPT, messages=[{"role": "user", "content": text}])
```

- Never pass `thinking`, `temperature`, `top_p`, `top_k`, `tool_choice`, tools, or an assistant prefill.
- `SCHEMA = strict_json_schema(AiScheduleOutput | AiFinanceOutput)`; `SYSTEM_PROMPT =
  prompts.schedule_prompt(ctx)` / `prompts.finance_prompt(ctx)` (a string; includes today's date, locale,
  currency, kind and the rules below). `text` is exactly the user's text.
- Response handling, in order:
  1. `resp.stop_reason == "refusal"` -> `AiFallback("AI_REFUSED")`; `== "max_tokens"` -> `AI_TRUNCATED`.
  2. First block in `resp.content` with `block.type == "text"`; none -> `AI_NO_TEXT`.
  3. `json.loads(block.text)`; `JSONDecodeError` -> `AI_BAD_JSON`.
  4. `AiScheduleOutput.model_validate(obj)` / `AiFinanceOutput...`; `ValidationError` -> `AI_SCHEMA_MISMATCH`.
  5. Convert to a draft (`ai_to_schedule_draft` / `ai_to_finance_draft`): same key scheme, provenance
     `source="ai"`, span found by locating `source_quote` in the text (exact, then case-insensitive;
     not found -> span None, confidence 0.5), values clipped to model limits.
- Exceptions, caught most specific first:
  ```python
  except anthropic.RateLimitError:        -> AI_RATE_LIMITED
  except anthropic.AuthenticationError:   -> AI_AUTH_FAILED
  except anthropic.APIStatusError as e:   -> AI_API_ERROR (message includes e.status_code)
  except anthropic.APIConnectionError:    -> AI_CONNECTION_ERROR   (includes timeouts)
  except Exception:                       -> AI_UNEXPECTED (logged with type name only)
  ```
- Concurrency: at most `settings.intake_ai_max_concurrent` (2) calls in flight per app; a request that cannot
  get a slot within 5 s -> `AI_BUSY`. The semaphore lives on the app (`app.state.intake_ai_slots`, created
  in `create_app` next to the router registration), not in a module global, so test apps do not share
  slots; the slot is released in `finally`.
- Worst-case latency is about `timeout x (1 + max_retries)` = 180 s. The UI shows a progress line and a
  "Cancel" button (aborts the fetch and keeps the text); the client fetch timeout for `describe` with AI
  is 200 s.
- Logging: `client.py` sets the `anthropic`, `httpx2` and `httpcore2` loggers to `WARNING` at import, so
  `ANTHROPIC_LOG=debug` or a root DEBUG level cannot write request or response bodies to the server log.

Fallback catalog (`intake/messages.py`; every message ends with "We used the built-in reader instead."):

| code | user message (prefix) |
|---|---|
| `AI_NOT_REQUESTED` | (no banner) |
| `AI_DISABLED` | "AI assist is turned off on this server." |
| `AI_SDK_MISSING` | "AI assist is not installed on this server." |
| `AI_NO_CREDENTIALS` | "AI assist is not set up on this server (no credentials)." |
| `AI_RATE_LIMITED` | "AI assist is busy right now (rate limit); try again in a minute." |
| `AI_AUTH_FAILED` | "AI assist is not set up correctly (the credentials were rejected)." |
| `AI_API_ERROR` | "AI assist returned an error (status {status})." |
| `AI_CONNECTION_ERROR` | "AI assist could not be reached." |
| `AI_REFUSED` | "AI assist declined to process this text." |
| `AI_TRUNCATED` | "The answer from AI assist was cut off; try a shorter description." |
| `AI_NO_TEXT`, `AI_BAD_JSON`, `AI_SCHEMA_MISMATCH` | "AI assist returned something we could not use." |
| `AI_BUSY` | "AI assist is handling other requests." |
| `AI_UNEXPECTED` | "AI assist failed unexpectedly." |

**Strict schema** (`ai/json_schema.py`): `strict_json_schema(model) -> dict` = `model.model_json_schema()`
with every `$ref` inlined (AI models are not recursive), `$defs` removed, and for every object node
`additionalProperties: false` and `required` = all property names. Keys kept: `type`, `properties`,
`required`, `additionalProperties`, `items`, `enum`, `anyOf`, `const`, `description`; everything else
(`title`, `default`, `minimum`, `maximum`, `minLength`, `maxLength`, `pattern`, `format`, `minItems`,
`maxItems`, `examples`) is dropped; constraints are enforced afterwards by Pydantic. Because every field is
required, AI models declare no defaults: optional values are `X | None` and must be sent as `null`.

AI output models (`ai/schemas.py`, all `extra="forbid"`, no defaults):

```python
class AiWindow(BaseModel):   start: str; end: str                     # "HH:MM"
class AiWorkingTime(BaseModel):
    days: list[Weekday]; windows: list[AiWindow]; weekend_windows: list[AiWindow]; source_quote: str
class AiDuration(BaseModel):
    low: float | None; likely: float | None; high: float | None
    unit: Literal["minutes", "hours", "days", "weeks"] | None
class AiTask(BaseModel):
    name: str; milestone: bool; duration: AiDuration
    after: list[str]                     # names of other tasks in this output
    resources: list[str]                 # names of resources in this output
    resource_mode: Literal["any", "all"]
    deadline: str | None                 # "YYYY-MM-DD"
    deadline_hard: bool; earliest_start: str | None; group: str | None
    source_quote: str                    # exact short quote from the user's text
    confidence: float                    # 0..1 (clamped by a before-validator)
class AiResource(BaseModel):
    name: str; kind: Literal["person", "machine", "room", "equipment", "generic"]; count: int
    source_quote: str; confidence: float
class AiScheduleOutput(BaseModel):
    kind: Literal["project", "study", "production", "generic"]
    name: str | None; start_date: str | None
    working_time: AiWorkingTime | None
    tasks: list[AiTask] = Field(max_length=200)        # max_length kept in Pydantic only
    resources: list[AiResource] = Field(max_length=50)
    notes: list[str] = Field(max_length=5)              # shown as AI_NOTE notes

class AiAmount(BaseModel):   low: float | None; high: float | None
class AiIncome(BaseModel):
    name: str; kind: Literal["salary", "business", "rental", "pension", "interest", "other"]
    amount: AiAmount; frequency: Literal["monthly", "quarterly", "half_yearly", "yearly", "once"]
    is_gross: bool; source_quote: str; confidence: float
class AiExpense(BaseModel):
    name: str; category: str; amount: AiAmount; frequency: Literal[...same...]
    essential: bool | None; source_quote: str; confidence: float
class AiDebt(BaseModel):
    name: str; kind: Literal["home", "vehicle", "education", "personal", "credit_card", "other"]
    balance: AiAmount; emi: AiAmount; interest_rate_pct: float | None; remaining_months: int | None
    source_quote: str; confidence: float
class AiHolding(BaseModel):
    name: str
    asset_class: Literal["cash", "fixed_deposit", "short_debt", "govt_long", "equity_index", "gold", "unknown"]
    amount: AiAmount; locked_until: str | None          # "YYYY-MM"
    source_quote: str; confidence: float
class AiGoal(BaseModel):
    name: str; kind: Literal["retirement", "education", "home", "vehicle", "travel", "wedding", "business", "other"]
    target: AiAmount; target_month: str | None; in_years: float | None; at_age: int | None
    priority: Literal["must", "should", "nice"] | None
    source_quote: str; confidence: float
class AiProfile(BaseModel):
    age: int | None; retirement_age: int | None; risk_tolerance: int | None; source_quote: str
class AiFinanceOutput(BaseModel):
    profile: AiProfile; incomes: list[AiIncome]; expenses: list[AiExpense]; debts: list[AiDebt]
    holdings: list[AiHolding]; goals: list[AiGoal]; emergency_fund_months: float | None
    notes: list[str] = Field(max_length=5)
```

System prompt rules (both domains; `prompts.py`): "You convert a user's description into structured
planning input. Extract only what the text states or clearly implies. Use null when something is not
stated; never invent amounts, durations or dates. Copy a short exact quote from the text into
source_quote for every item. Convert relative dates using today's date {today}. Amounts are in {currency};
'lakh' = 100000, 'crore' = 10000000, 'k' = 1000. For ranges give low and high. Do not give financial,
legal or investment advice, do not recommend products, and do not add commentary outside the JSON."
Plus domain specifics (schedule: tasks/dependencies/resources/working time; finance: take-home vs gross,
holdings classes).

### 2.11 Merge policy (`ai/merge.py`)

`merge(R, A) -> (draft, notes)`, R = rule-based, A = AI:
1. Items are matched by kind of collection and normalised name (token-Jaccard >= 0.6; incomes/expenses
   also by amount within 10 %); unmatched A items are appended (keys continue the sequence).
2. For a matched field: R value with `source="text"` and a span containing a digit wins over A ("typed
   numbers win"); if A differs, note `KEPT_TYPED_NUMBER` ("AI assist read {a}; we kept the {r} you typed.").
   Otherwise the value with the higher confidence wins; ties keep R.
3. Fields only A has are taken with AI provenance (confidence <= 0.8).
4. A dependency or resource reference from A that does not resolve to a merged item is dropped with note
   `AI_REFERENCE_DROPPED`.
5. A's `notes` become `AI_NOTE` info notes (max 5, 300 chars each).
6. Result passes the same draft validators; any failure -> discard A entirely, fallback
   `AI_SCHEMA_MISMATCH`.

### 2.12 Settings, privacy, logging

`api/config.py` `Settings` additions:

| field | env | default |
|---|---|---|
| `intake_ai_enabled: bool` | `INTAKE_AI_ENABLED` (`1|true|yes|on`, case-insensitive) | `False` |
| `intake_ai_timeout_seconds: float` | `INTAKE_AI_TIMEOUT_SECONDS` | `60.0` |
| `intake_ai_max_retries: int` | - | `2` |
| `intake_ai_max_concurrent: int` | - | `2` |
| `intake_max_text_chars: int` | - | `20000` |
| `intake_max_table_chars: int` | - | `1000000` |
| `intake_ai_client_factory: Callable[[], Any] | None` | - (tests only) | `None` |

Privacy notice (constant `PRIVACY_NOTICE`, returned by `/intake/capabilities`, shown next to the toggle):
"AI assist sends the text in this box to Anthropic, an AI provider, to turn it into a draft. Nothing else
from your plans is sent. Do not include account numbers, ID numbers, passwords or anything you do not want
to share. Without AI assist your text is read only on this server."

Logging: intake code never logs request text, table content, AI prompts or AI responses; it logs extractor
used, fallback code, text length, item counts and elapsed time. Tests assert the user text does not appear
in captured logs.

### 2.13 Table import (paste / CSV) with column mapping

Files are read in the browser (`File.text()`, max 1 MB, `.csv`, `.tsv`, `.txt`) and sent as JSON text: no
multipart dependency. XLSX is not parsed (users copy cells, which pastes as TSV).

`parse_table(text, domain, delimiter="auto", has_header=None) -> TableParseResult`:
- Delimiter auto: candidates tab, `,`, `;`, `|`; choose the one whose per-line field count over the first 20
  non-empty lines has the highest share of the modal count (> 1 field), ties in that order. Parsing uses
  Python `csv` (RFC 4180 quotes). Max 2000 data rows, 30 columns (else 422 `TABLE_TOO_LARGE`).
- Header auto: first row has no cell that parses as a number/duration/date and >= 1 cell matches a synonym.
- Suggestions: each header normalised (lower-case, punctuation removed) and matched against the synonym
  table; without header, by content (durations -> duration, dates -> deadline, money -> amount, the
  longest text column -> name). Each column gets `suggested_field` (or None) and `confidence`.

```python
class TableColumn(BaseModel):    index: int; header: str | None; samples: list[str]; suggested_field: str | None; confidence: float
class TableParseResult(BaseModel):
    delimiter: str; has_header: bool; row_count: int; columns: list[TableColumn]
    preview: list[list[str]]          # first 10 data rows
    warnings: list[str]               # ragged rows, empty columns
class ColumnMapping(_Strict): column: int = Field(ge=0); field: str | None
class TableOptions(_Strict):
    duration_unit: DurationUnit = "days"              # cells with bare numbers
    default_row_kind: Literal["income", "expense", "goal", "debt", "holding"] = "expense"  # finance
    amount_frequency: Frequency = "monthly"           # finance, bare amounts
    predecessor_ref: Literal["auto", "id", "name", "row"] = "auto"
class TableParseRequest(_Strict):
    text: str = Field(max_length=1_000_000)          # settings.intake_max_table_chars
    delimiter: Literal["auto", "\t", ",", ";", "|"] = "auto"
    has_header: bool | None = None
class TableApply(_Strict):
    text: str = Field(max_length=1_000_000); delimiter: Literal["\t", ",", ";", "|"]; has_header: bool
    mapping: list[ColumnMapping]; options: TableOptions = TableOptions()
```

Schedule fields and header synonyms:

| field | synonyms | cell format |
|---|---|---|
| `id` | id, #, no, number, key, wbs | any; used for predecessor references |
| `name` (required) | task, name, activity, item, title, step, operation, description | text |
| `duration` | duration, time, effort, estimate, length, est, hours, days | duration grammar incl. ranges; bare number = `options.duration_unit` (header "hours"/"days" overrides) |
| `optimistic` / `likely` / `pessimistic` | optimistic, min, best case / likely, most likely, expected / pessimistic, max, worst case | numbers in the duration unit; override `duration` |
| `predecessors` | predecessors, depends on, dependencies, after, prereqs, requires | list split on `,` `;` `/`; each by id, then name, then row number (`predecessor_ref`) |
| `resources` | resources, assignee, owner, who, person, machine, team | list; resources created by name |
| `deadline` | deadline, due, due date, finish by, end date | date grammar |
| `earliest_start` | start, start date, earliest start, not before | date grammar |
| `priority` | priority, importance | 1..10, or high/medium/low -> 8/5/3 |
| `group` | group, phase, workstream, job, subject, category | text |
| `notes` | notes, comments | text |

Finance fields: `row_kind` (type, kind, row type; values income/expense/goal/debt/loan/holding/
investment/savings; else inferred from the name with the 2.7.9 cues, else `default_row_kind`), `name`,
`amount` (amount, value, monthly, rs, inr, ₹, cost, target), `frequency`, `category`, `essential` (essential,
need, must; yes/no/true/false/y/n), `date` (date, when, by, target date, year; goal date), `priority`,
`asset_class` (asset, held in, account type; 2.7.9 class words), `interest_rate`, `emi`, `balance`.

`apply_*_table`: every data row becomes one item with provenance `source="table"`, `cell` set, confidence
0.95 for parsed cells and 0.6 for inferred row kinds; an unparseable optional cell is left empty and
produces a row note; a row without a name is skipped with a row note. Notes for rows use code
`TABLE_ROW` and the message "Row {n}: ...". If `base` is given, items are appended to it (keys continue).
Then questions are generated as for `describe`.

### 2.14 Duration ranges and PERT in the scheduling model (engine edits)

`engine/model.py`:

```python
def pert_minutes(optimistic: int, likely: int, pessimistic: int) -> int:
    """PERT expected value (o + 4m + p) / 6 rounded half up to whole minutes."""
    return (optimistic + 4 * likely + pessimistic + 3) // 6

class DurationEstimate(_Strict):
    optimistic_minutes: int = Field(ge=1)
    likely_minutes: int = Field(ge=1)
    pessimistic_minutes: int = Field(ge=1)
    # model_validator: optimistic <= likely <= pessimistic

class Task(_Strict):
    ...  # unchanged fields
    duration_estimate: DurationEstimate | None = None
    # _type_rules additionally: a milestone must not have duration_estimate;
    # if set: duration_minutes == pert_minutes(o, m, p), else
    # ValueError(f"duration_minutes must be {e}, the expected value of duration_estimate")
```

Write paths that change a duration (review fix: with the strict equality rule above every one of them
would otherwise fail with 422):
- Replan (`api/services/replan_service.py` `_apply_changes`): a `task_updates` entry that sets
  `duration_minutes` on a task with `duration_estimate` removes the estimate (a real-world duration replaces
  the estimate). A `TaskUpdate` cannot set an estimate. Test: replan of a built intake problem with a
  duration update returns 202 and the stored document has no estimate on that task.
- UI inline edit (`TaskTable` duration cell) and the type switch to milestone remove `duration_estimate`
  (3.5); `TaskDrawer` keeps both consistent.
- `PUT /problems/{id}` with a mismatch keeps returning 422 with the message above (client bug, not user
  input).

Exported from `superplanner.engine` (`pert_minutes`, `DurationEstimate`). Solvers, decoder, validator and
preflight keep using `duration_minutes` only (backward compatible: documents without the field are
unchanged; export/import format version stays 1). `compiled.py` carries `estimate: tuple[int, int, int] |
None` per task for explanations.

`engine/explain.py` adds to `ScheduleExplanation`:

```python
class DurationRisk(BaseModel):
    tasks_with_range: int
    chain_task_ids: list[str]               # activities on the schedule critical chain
    chain_expected_minutes: int             # sum of duration_minutes
    chain_optimistic_minutes: int           # sum of o (duration if no estimate)
    chain_pessimistic_minutes: int          # sum of p
    chain_sigma_minutes: float              # sqrt(sum(((p - o) / 6)^2))
    buffer_85_minutes: int                  # round(1.04 * sigma)
    message: str

ScheduleExplanation.duration_risk: DurationRisk | None = None   # None when no task has a range
```

Message (also appended to `summary` when present): "{n} {tasks} have a duration range; the plan uses the
expected values. If the {tasks} on the critical chain take their longest estimates, the work runs about
{extra} longer; keeping about {buffer} spare gives roughly an 85% chance of finishing on time."
(`{extra}` = pessimistic - expected, `{buffer}` = `buffer_85_minutes`, formatted as working time "1 d 2 h"
with 8-hour days; `{tasks}` from terminology, lower-case plural.)

### 2.15 REST API `/api/v1/intake`

Conventions as ARCHITECTURE 14 (error envelope, 422 `VALIDATION_ERROR`). All endpoints are sync handlers
(threadpool), never write to the DB, and return 200 on success. Router registered in `api/main.py` after
`finance_router`.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/intake/capabilities` | - | `Capabilities` |
| POST | `/intake/schedule/describe` | `DescribeRequest` | `ScheduleIntakeResponse` |
| POST | `/intake/schedule/answer` | `{draft: ScheduleDraft, answers: [Answer], context: ExtractContext}` | `ScheduleIntakeResponse` |
| POST | `/intake/schedule/build` | `{draft: ScheduleDraft, context: ExtractContext}` | `ScheduleBuildResult` |
| POST | `/intake/schedule/table/parse` | `TableParseRequest` (2.13) | `TableParseResult` |
| POST | `/intake/schedule/table/apply` | `TableApply` + `{context, base?: ScheduleDraft}` | `ScheduleIntakeResponse` + `row_notes` |
| POST | `/intake/finance/describe` | `DescribeRequest` | `FinanceIntakeResponse` |
| POST | `/intake/finance/answer` | `{draft: FinanceDraft, answers, context}` | `FinanceIntakeResponse` |
| POST | `/intake/finance/build` | `{draft: FinanceDraft, context}` | `FinanceBuildResult` |
| POST | `/intake/finance/table/parse` | as schedule | `TableParseResult` |
| POST | `/intake/finance/table/apply` | `TableApply` + `{context, base?: FinanceDraft}` | `FinanceIntakeResponse` + `row_notes` |

```python
class DescribeRequest(_Strict):
    text: str = Field(max_length=20000)
    context: ExtractContext
    use_ai: bool = False                          # per-request opt-in

class ScheduleIntakeResponse(BaseModel):          # FinanceIntakeResponse: same with FinanceDraft
    draft: ScheduleDraft
    questions: list[Question]
    notes: list[IntakeNote]
    row_notes: list[IntakeNote] = []
    extractor: ExtractorInfo
    ready: bool
```

Errors: 422 `TEXT_EMPTY`, `TEXT_TOO_LONG` (`details.max_chars`), `TABLE_EMPTY`, `TABLE_TOO_LARGE`
(`details.max_rows|max_columns|max_chars`), `UNKNOWN_QUESTION` (`details.question_id`), `BAD_MAPPING`
(column index out of range, duplicate field, no `name` column), `VALIDATION_ERROR` (draft invalid). AI
problems are never errors (200 with `extractor.fallback_*`). 413 from the existing body limit (5 MB).

`GET /api/v1/intake/capabilities` -> 200
```json
{"ai_available": false, "ai_reason": "AI_DISABLED", "provider": "Anthropic", "model": "claude-opus-5-5",
 "privacy_notice": "AI assist sends the text in this box to Anthropic, an AI provider, ...",
 "limits": {"max_text_chars": 20000, "max_table_chars": 1000000, "max_table_rows": 2000, "max_table_columns": 30},
 "schedule_kinds": ["project", "study", "production", "generic"]}
```

`POST /api/v1/intake/schedule/describe`
```json
{"text": "Website relaunch starting next Monday. Ravi and Priya are on the team.\n1. Gather requirements - 2-3 days (Priya)\n2. Design 1 week, after requirements, Priya\n3. Build the site: 2 weeks, Ravi\n4. Testing 3-5 days once the build is done\n5. Launch by 15 Dec 2026",
 "context": {"today": "2026-10-17", "utc_offset": "+05:30", "locale": "en-IN", "currency": "INR", "kind": "project"},
 "use_ai": false}
```
-> 200 (abridged; spans are code-point offsets into `text`)
```json
{"draft": {
   "domain": "schedule", "kind": "project", "name": "Website relaunch", "start_date": "2026-10-19",
   "horizon_days": null, "working_time": null, "objective": null,
   "resources": [{"key": "r_ravi", "name": "Ravi", "kind": "person", "count": 1},
                 {"key": "r_priya", "name": "Priya", "kind": "person", "count": 1}],
   "tasks": [
     {"key": "t1", "name": "Gather requirements", "milestone": false,
      "duration": {"optimistic": 2, "likely": 2.5, "pessimistic": 3, "unit": "days"},
      "after": [], "resources": ["r_priya"], "resource_mode": "any", "deadline": null, "deadline_hard": false,
      "earliest_start": null, "priority": null, "group": null, "notes": ""},
     {"key": "t2", "name": "Design", "duration": {"optimistic": 1, "likely": 1, "pessimistic": 1, "unit": "weeks"},
      "after": ["t1"], "resources": ["r_priya"], "...": "..."},
     {"key": "t3", "name": "Build the site", "duration": {"optimistic": 2, "likely": 2, "pessimistic": 2, "unit": "weeks"},
      "after": ["t2"], "resources": ["r_ravi"], "...": "..."},
     {"key": "t4", "name": "Testing", "duration": {"optimistic": 3, "likely": 4, "pessimistic": 5, "unit": "days"},
      "after": ["t3"], "resources": [], "...": "..."},
     {"key": "t5", "name": "Launch", "milestone": true, "duration": null, "after": ["t4"],
      "deadline": "2026-12-15", "deadline_hard": false, "...": "..."}],
   "provenance": {
     "/start_date": {"source": "text", "confidence": 0.8, "span": {"start": 26, "end": 37, "text": "next Monday"}},
     "/resources/r_ravi/name": {"source": "text", "confidence": 0.7, "span": {"start": 39, "end": 43, "text": "Ravi"}},
     "/tasks/t1/duration": {"source": "text", "confidence": 0.95, "span": {"start": 96, "end": 104, "text": "2-3 days"}},
     "/tasks/t1/resources": {"source": "text", "confidence": 0.7, "span": {"start": 105, "end": 112, "text": "(Priya)"}},
     "/tasks/t2/after": {"source": "text", "confidence": 0.95, "span": {"start": 131, "end": 149, "text": "after requirements"}},
     "/tasks/t3/after": {"source": "derived", "confidence": 0.6, "note": "From the order of the list"},
     "/tasks/t4/after": {"source": "text", "confidence": 0.9, "span": {"start": 210, "end": 232, "text": "once the build is done"}},
     "/tasks/t5/deadline": {"source": "text", "confidence": 0.95, "span": {"start": 243, "end": 257, "text": "by 15 Dec 2026"}},
     "/tasks/t5/milestone": {"source": "derived", "confidence": 0.7, "note": "No duration and the name looks like a milestone"}},
   "dismissed": []},
 "questions": [
   {"id": "SCHED_SEQUENTIAL:-", "code": "SCHED_SEQUENTIAL", "path": null, "kind": "confirm",
    "prompt": "Should the numbered steps happen one after another?", "default": true, "default_label": "Yes",
    "required": false, "reason": "confirm_default", "options": [], "help": "", "span": null, "error": null},
   {"id": "SCHED_PEOPLE:-", "code": "SCHED_PEOPLE", "path": null, "kind": "confirm",
    "prompt": "Are Ravi and Priya the people doing the work?", "default": true, "required": false, "reason": "confirm_default", "...": "..."},
   {"id": "SCHED_WHO:/tasks/t4/resources", "code": "SCHED_WHO", "path": "/tasks/t4/resources", "kind": "multi_choice",
    "prompt": "Who does \"Testing\"?", "options": [{"value": "r_ravi", "label": "Ravi"}, {"value": "r_priya", "label": "Priya"}],
    "default": ["r_ravi", "r_priya"], "default_label": "Either Ravi or Priya", "required": false, "reason": "missing", "...": "..."},
   {"id": "SCHED_WORKING_TIME:/working_time", "code": "SCHED_WORKING_TIME", "path": "/working_time", "kind": "working_time",
    "prompt": "When does the team work?", "default": {"days": ["mon", "tue", "wed", "thu", "fri"], "windows": [{"start": "09:00", "end": "17:00"}], "weekend_windows": null},
    "default_label": "Mon-Fri 09:00-17:00", "required": false, "reason": "confirm_default", "...": "..."}],
 "notes": [],
 "extractor": {"requested": "rule", "used": "rule", "ai_available": false, "fallback_code": null, "fallback_message": null, "model": null},
 "ready": true}
```

`POST /api/v1/intake/schedule/answer`
```json
{"draft": {"...": "draft from above"},
 "answers": [{"question_id": "SCHED_WHO:/tasks/t4/resources", "value": ["r_ravi"]},
             {"question_id": "SCHED_WORKING_TIME:/working_time", "use_default": true},
             {"question_id": "SCHED_SEQUENTIAL:-", "value": true},
             {"question_id": "SCHED_PEOPLE:-", "skip": true}],
 "context": {"today": "2026-10-17", "utc_offset": "+05:30", "locale": "en-IN", "currency": "INR", "kind": "project"}}
```
-> 200 `ScheduleIntakeResponse` with `t4.resources = ["r_ravi"]`, `working_time` set, `dismissed =
["SCHED_PEOPLE:-"]`, `questions: []`.

`POST /api/v1/intake/schedule/build` (same draft) -> 200, abridged:
```json
{"ready": true,
 "parts": {"t1": ["t1_1", "t1_2", "t1_3"], "t2": ["t2_1", "t2_2", "t2_3", "t2_4", "t2_5"], "t3": ["t3_1", "...", "t3_10"],
           "t4": ["t4_1", "t4_2", "t4_3", "t4_4"], "t5": ["t5"]},
 "problem": {"id": "draft", "name": "Website relaunch", "domain": "project", "horizon_start": "2026-10-19T00:00:00+05:30",
   "horizon_days": 64, "currency": "INR",
   "tasks": [{"id": "t1_1", "name": "Gather requirements (1/3)", "group": "Gather requirements", "duration_minutes": 400,
              "duration_estimate": {"optimistic_minutes": 320, "likely_minutes": 400, "pessimistic_minutes": 480},
              "requirements": [{"alternatives": ["r_priya"], "units": 1}],
              "metadata": {"intake_key": "t1", "part": 1, "parts": 3}},
             {"id": "t4_1", "name": "Testing (1/4)", "duration_minutes": 480,
              "duration_estimate": {"optimistic_minutes": 360, "likely_minutes": 480, "pessimistic_minutes": 600}},
             {"id": "t5", "name": "Launch", "type": "milestone", "duration_minutes": 0,
              "deadline": "2026-12-15T17:00:00+05:30", "deadline_hard": false}],
   "dependencies": [{"predecessor": "t1_1", "successor": "t1_2", "type": "FS", "lag_minutes": 0},
                    {"predecessor": "t1_3", "successor": "t2_1", "type": "FS", "lag_minutes": 0}],
   "objectives": {"preset": "meet_deadlines"},
   "metadata": {"intake": {"version": 1, "source": "describe", "extractor": "rule"}}},
 "report": {"ok": true, "issues": [], "cpm": {"lower_bound_makespan_minutes": 10320, "...": "..."}},
 "blocking": [],
 "duration_summary": {"tasks_with_range": 2, "expected_work_minutes": 10320, "optimistic_work_minutes": 9600, "pessimistic_work_minutes": 11040}}
```
(Derivation: 1 day = 480 min, 1 week = 2400; t1 o/m/p = 960/1200/1440, E = 1200 -> 3 parts of
320/400/480; t4 1440/1920/2400 -> 4 parts of 360/480/600; horizon = max(57 + 7, 30) = 64.) The client then
calls `POST /api/v1/problems` with `problem` and navigates to `/plans/<id>/tasks`.

`POST /api/v1/intake/finance/describe`
```json
{"text": "I'm 34, take home about 1.2 lakh a month and my wife earns 60k. Household costs are 70-80k a month, school fees 18k every quarter. Car loan EMI 10k, about 3 lakh left at 9%. We have 6 lakh in savings and 8L in mutual funds. We want 15 lakh for a flat down payment in 3 years and to retire at 60. Moderate risk.",
 "context": {"today": "2026-10-17", "locale": "en-IN", "currency": "INR"}, "use_ai": false}
```
-> 200 (abridged)
```json
{"draft": {"domain": "finance", "name": "My financial plan", "start_month": "2026-10",
   "profile": {"age": 34, "retirement_age": 60, "risk_tolerance": 3, "currency": "INR", "locale": "en-IN"},
   "incomes": [{"key": "i1", "name": "Salary", "kind": "salary", "amount": {"low": 120000, "high": 120000}, "frequency": "monthly", "inflation_linked": true, "growth_pct": null},
               {"key": "i2", "name": "Partner's salary", "kind": "salary", "amount": {"low": 60000, "high": 60000}, "frequency": "monthly", "inflation_linked": true, "growth_pct": null}],
   "expenses": [{"key": "e1", "name": "Household costs", "category": "living", "amount": {"low": 70000, "high": 80000}, "frequency": "monthly", "essential": true},
                {"key": "e2", "name": "School fees", "category": "education", "amount": {"low": 18000, "high": 18000}, "frequency": "quarterly", "essential": true, "inflation_pct": 9.0}],
   "debts": [{"key": "d1", "name": "Car loan", "kind": "vehicle", "balance": {"low": 300000, "high": 300000}, "interest_rate_pct": 9.0, "emi": {"low": 10000, "high": 10000}}],
   "holdings": [{"key": "h1", "name": "Savings", "asset_class_id": "cash", "amount": {"low": 600000, "high": 600000}},
                {"key": "h2", "name": "Mutual funds", "asset_class_id": "equity_index", "amount": {"low": 800000, "high": 800000}}],
   "goals": [{"key": "g1", "name": "Flat down payment", "kind": "home", "target": {"low": 1500000, "high": 1500000}, "target_month": "2029-10", "priority": null},
             {"key": "g2", "name": "Retirement", "kind": "retirement", "target": null, "target_month": "2052-10", "priority": "must"}],
   "provenance": {"/profile/age": {"source": "text", "confidence": 0.95, "span": {"start": 0, "end": 6, "text": "I'm 34"}},
                  "/incomes/i1/amount": {"source": "text", "confidence": 0.8, "span": {"start": 18, "end": 40, "text": "about 1.2 lakh a month"}},
                  "/expenses/e1/amount": {"source": "text", "confidence": 0.95, "span": {"start": 84, "end": 98, "text": "70-80k a month"}},
                  "/goals/g2/target_month": {"source": "derived", "confidence": 0.9, "span": {"start": 282, "end": 294, "text": "retire at 60"}, "note": "Age 34 + 26 years"}}},
 "questions": [
   {"id": "FIN_RETIREMENT_TARGET:/goals/g2/target", "kind": "money", "required": false, "reason": "confirm_default",
    "prompt": "For retirement we suggest saving ₹2,25,00,000 (25 years of your regular spending, in today's money). Keep it or enter your own amount.",
    "default": 22500000, "...": "..."},
   {"id": "FIN_DISCRETIONARY:-", "kind": "money", "required": false, "default": 0, "default_label": "None",
    "prompt": "Anything else you spend each month, such as eating out, shopping or trips?", "...": "..."},
   {"id": "FIN_GOAL_PRIORITY:/goals/g1/priority", "kind": "choice", "required": false, "default": "should", "...": "..."},
   {"id": "FIN_EF_MONTHS:/emergency_fund_months", "kind": "number", "required": false, "default": 6, "...": "..."}],
 "notes": [{"code": "EDUCATION_INFLATION", "severity": "info", "message": "School fees are assumed to rise 9% a year; you can change this."}],
 "extractor": {"requested": "rule", "used": "rule", "ai_available": false, "fallback_code": null, "fallback_message": null, "model": null},
 "ready": true}
```
`build` maps `e1.amount` to 75,000 with `amount_range {low 70000, high 80000}` and the retirement target to
25 x 12 x 75,000 (education category excluded) unless answered.

`POST /api/v1/intake/schedule/table/parse`
```json
{"text": "Task\tDuration\tAfter\tOwner\tDue\nRequirements\t2-3 d\t\tPriya\t\nDesign\t1 w\tRequirements\tPriya\t\nBuild\t2 w\tDesign\tRavi\t15/12/2026", "delimiter": "auto"}
```
-> 200
```json
{"delimiter": "\t", "has_header": true, "row_count": 3,
 "columns": [{"index": 0, "header": "Task", "samples": ["Requirements", "Design", "Build"], "suggested_field": "name", "confidence": 0.95},
             {"index": 1, "header": "Duration", "samples": ["2-3 d", "1 w", "2 w"], "suggested_field": "duration", "confidence": 0.95},
             {"index": 2, "header": "After", "samples": ["", "Requirements", "Design"], "suggested_field": "predecessors", "confidence": 0.9},
             {"index": 3, "header": "Owner", "samples": ["Priya", "Priya", "Ravi"], "suggested_field": "resources", "confidence": 0.9},
             {"index": 4, "header": "Due", "samples": ["", "", "15/12/2026"], "suggested_field": "deadline", "confidence": 0.9}],
 "preview": [["Requirements", "2-3 d", "", "Priya", ""], ["Design", "1 w", "Requirements", "Priya", ""], ["Build", "2 w", "Design", "Ravi", "15/12/2026"]],
 "warnings": []}
```
`table/apply` takes the same text plus `mapping` (`[{"column": 0, "field": "name"}, ...]`), `options`,
`context` and optional `base`, and returns an intake response whose draft has tasks `row0..row2`.

### 2.16 Tests (intake) - `backend/tests/intake/`

No test touches the network: the AI extractor is always given a fake `client_factory`.

- `test_numbers.py`, `test_durations.py`, `test_dates.py`: table-driven grammar cases (Indian/Western
  grouping, lakh/crore/k/L/Cr, ranges with shared units, currency markers, frequencies, percent, duration
  ranges and three-point estimates, "half a day", ISO/DMY/MDY/ambiguous dates, relative dates against a
  fixed `today`, month-year deadlines).
- `test_schedule_extract.py`: the 2.15 example produces exactly the draft shown (keys, values, spans);
  dependency phrases (after/once/before/then/->), list-order chains, fuzzy references and the
  `SCHED_DEP_REFERENCE` question, counted resources and named people, study example from the blueprint
  ("90 days to prepare ... three hours on weekdays and eight hours on weekends ... revise everything twice,
  ten mock tests") -> exam milestone, windows, 10 mock tests, revision tasks; `UNSUPPORTED_RULE` notes.
- `test_finance_extract.py`: the 2.15 finance example; gross pay -> `FIN_TAKE_HOME`; holdings class mapping;
  debts with EMI/balance/rate; goal kinds/priorities; ranges -> `DraftAmount`.
- `test_questions_answers.py`: question generation per code, defaults, `use_default`, `skip` ->
  `dismissed`, `{"text": ...}` parsing, `error` on unparseable answers, `UNKNOWN_QUESTION`.
- `test_schedule_build.py`: unit conversion, splitting (every part <= `max_part`, PERT per part, ids),
  requirements modes, deadlines at window end, horizon formula, `engine.analyze` ok, cycles reported,
  built problem accepted by `POST /api/v1/problems`.
- `test_finance_build.py`: midpoint + `amount_range`, linked incomes, retirement preset, preflight ok,
  plan accepted by `POST /api/v1/finance/plans` and runs `feasible`.
- `test_tables.py`: delimiter/header detection (TSV paste, CSV with quotes, semicolons), synonyms,
  content-based suggestions, `BAD_MAPPING`, limits, row notes, finance row-kind inference.
- `test_ai_extractor.py` (fake client): exact kwargs passed to `beta.messages.create` (model, max_tokens,
  betas, fallbacks, output_config with the strict schema, system, messages) and absence of `thinking`,
  `temperature`, `top_p`, `top_k`, `tool_choice`, `tools`; each fallback code (refusal, max_tokens, no text
  block, bad JSON, schema mismatch, `RateLimitError`, `AuthenticationError`, other `APIStatusError`,
  `APIConnectionError`, generic exception; exceptions built with `httpx2.Request`/`httpx2.Response`:
  SDK 1.15.0 is built on `httpx2`, not `httpx`, see its `_exceptions.py`);
  disabled / no credentials / SDK missing (monkeypatched import); busy slot.
- `test_json_schema.py`: every object node of both schemas has `additionalProperties: false` and
  `required` == its property names; no `$ref`, no dropped keywords.
- `test_merge.py`: typed numbers win with `KEPT_TYPED_NUMBER`, AI-only fields added with capped confidence,
  unresolved AI references dropped, invalid merged draft -> discarded.
- `test_api_intake.py`: all endpoints, status codes and error codes, `capabilities` with and without AI,
  no DB rows written (table counts unchanged), user text absent from logs (`caplog`).
- `test_engine_pert.py` (engine edits): `pert_minutes`, `DurationEstimate` validation, Task rule
  (mismatch -> 422 on `POST /problems`), milestone with estimate rejected, `DurationRisk` numbers and summary
  line, old documents unchanged (round trip of an existing template).

---

## 3. Part C - Usability pass (frontend)

### 3.1 Routes (all existing URLs unchanged)

| Path | Element | Notes |
|---|---|---|
| `/` | `HomePage` | now starts with `PlanChooser` ("What do you want to plan?"), then "Your plans" (h2) and "Start from an example" (existing template cards, ids unchanged) |
| `/new/:kind` | `StartPage` | kind in `project|study|production|money`; the four ways to start as large buttons; unknown kind -> `NotFound` |
| `/new/:kind/describe` | `DescribePage` | intake flow (3.3) |
| `/new/:kind/import` | `ImportPage` | paste/CSV import (3.3) |
| `/new/:kind/example` | `ExamplePage` | scheduling: the matching template card (project -> `project`, study -> `exam_prep`, production -> `manufacturing`); money: the finance template cards (`FinanceTemplateCards` extracted from `FinanceHome`, same test ids) |
| existing `/plans/:planId/*`, `/finance/*` | unchanged | |

"Build step by step": scheduling kinds -> `POST /problems` with an empty problem using the kind's
terminology, working calendar resource and name "My <kind> plan", then `/plans/<id>/tasks`; money -> the
existing blank-plan flow (`fin-start-blank` behaviour) -> `/finance/<id>/setup/profile`. `MainNav` marks
Finance active for `/finance*` and `/new/money*`.

### 3.2 Landing page (`frontend/src/landing/`)

- `PlanChooser.tsx`: heading h1 "What do you want to plan?", one sentence of help, four cards (role
  `group`, `aria-labelledby`): Project or schedule ("Tasks, people and deadlines"), Study plan ("Subjects,
  revision and an exam date"), Production ("Orders, machines and shifts"), Money goals ("Income, savings
  and goals like a home or retirement"). Each card has four buttons: "Describe it", "Start from an example",
  "Import a table", "Build step by step". Test ids `landing-kind-<kind>`, `landing-action-<kind>-<describe|
  example|import|steps>`.
- `kinds.ts`: kind -> label, description, icon, schedule kind or finance, template id, default terminology.
- `HomePage.tsx`: `PlanChooser` on top; the existing "Your plans" list (h2) and template grid unchanged
  below (Import JSON button stays). Finance plans list stays on `/finance`.

### 3.3 Intake UI (`frontend/src/intake/`)

```
intake/
  api/client.ts            typed fetch wrappers for 2.15
  api/types.ts             TS mirrors of 2.3-2.5, 2.9, 2.13 (hand-written like the existing api/types.ts)
  state/IntakeContext.tsx  draft, questions, notes, extractor, step; persisted in sessionStorage
                           ("sp.intake.<kind>"), cleared on create/cancel
  pages/DescribePage.tsx   write -> questions -> review -> create, one page with a step indicator
  pages/ImportPage.tsx     paste/upload -> map columns -> questions -> review -> create
  pages/StartPage.tsx, pages/ExamplePage.tsx
  components/AiAssistToggle.tsx   switch "Use AI assist for this request" + privacy notice
  components/ExtractorBanner.tsx  "Read with the built-in reader" / "Read with AI assist" / fallback message
  components/QuestionPanel.tsx    chat-like list: question bubble, input, "Use suggestion", "Skip", "Use
                                  suggestions for all remaining"; live region announces the next question
  components/QuestionInput.tsx    one input per question kind (duration accepts "2-3 days")
  components/SourceText.tsx       the original text with highlighted spans; hover/focus a span highlights
                                  the field and vice versa
  components/ScheduleDraftEditor.tsx  tasks table (name, duration range o/likely/p + unit, after, who,
                                      deadline, hard), resources list, working time
  components/FinanceDraftEditor.tsx   sections: about you, income, spending, loans, savings, goals; ranges as
                                      "from - to" pair
  components/ConfidenceBadge.tsx  High / Medium / Low with tooltip "Read from: \"2-3 days\"" or "Default" /
                                  "Suggested by AI assist"
  components/ColumnMapper.tsx     one select per column (field list per domain, "Ignore"), preview of 10 rows,
                                  row notes, options (duration unit, default row type)
  components/CreatePlanBar.tsx    build preview (issues list with plain messages), "Create plan" (disabled
                                  until ready), "Start over"
  lib/codepoints.ts               code-point slicing for spans (Array.from)
  lib/pert.ts                     pertMinutes, formatRange ("2-3 days, expected 2.5 days")
```

Flow details:
- Write step: textarea with a kind-specific placeholder example, character counter (max 20,000),
  `AiAssistToggle` shown only when `capabilities.ai_available`; when unavailable, a muted line "AI assist is
  not available on this server; the built-in reader is used." The toggle defaults off on every visit; turning
  it on shows the privacy notice inline (not only a tooltip) and the button label changes to "Send to AI
  assist and make a draft". Without it: "Make a draft".
- Questions + review: two columns >= 1024 px (left `SourceText` + `QuestionPanel`, right draft editor),
  stacked below. Edits call nothing until "Check draft" or until a question is answered (debounced 600 ms
  `answer` with an empty answers list to refresh questions). Every edited field sets provenance `edit`.
- Review: `build` result: counts ("12 tasks in 5 steps, 2 people"), PERT note, preflight issues (errors
  block "Create plan"), finance cash-flow preview ("About ₹69,000 left each month in the first year").
- Create: scheduling `POST /problems` with `problem` -> `/plans/<id>/tasks`; finance `POST /finance/plans`
  -> `/finance/<id>/setup/review`. Then clear the session state. Text shown on the button: "Create plan".
- Test ids: `intake-text`, `intake-ai-toggle`, `intake-ai-notice`, `intake-submit`, `intake-extractor`,
  `intake-question-<code>`, `intake-answer`, `intake-use-default`, `intake-skip`, `intake-use-all-defaults`,
  `intake-draft`, `intake-source`, `intake-field-<path>`, `intake-confidence-<path>`, `intake-build`,
  `intake-issues`, `intake-create`; import: `import-paste`, `import-file`, `import-parse`,
  `import-map-<index>`, `import-apply`, `import-row-notes`.

### 3.4 Finance UI changes (`frontend/src/finance/**`)

- `ResultKpis.tsx`: card 1 "Left over each month" = `monthly_surplus_avg_12m`, sub "first-year average after
  expenses and loans" (+ "₹X of it builds your emergency fund" when > 0); card 2 "Plan invests" =
  `monthly_contribution_avg_12m`, sub "₹A from your monthly surplus + ₹B from savings you already have"
  (or "all from your monthly surplus"); month-0 values in the card's `title`. Same `data-testid`s.
- `GoalCard.tsx`: "Why this mix" line = the goal's first reason (`GROWTH_*`); "Likely outcome: about N% of
  the target" from `p50_real / target_real` (helps when the chance is low but the gap is small); growth share
  bar "Growth assets now: 60% (limit 60%)".
- Wizard `IncomeExpenseStep`: toggle "Rises with inflation" (default off for new rows); when on, growth label
  "Yearly raise above inflation (%)", else "Yearly raise (%)". Ranges: items with `amount_range` show a chip
  "range 70,000-80,000, using 75,000".
- `AssumptionsStep`: "Reset to current defaults" (asks for confirmation; replaces asset classes, inflation,
  caution), the caution settings under "Advanced" with plain labels ("Keep at least this share of growth
  for goals 10+ years away").
- `api/types.ts`: new fields of 1.5, 1.7, 1.10-1.12.

### 3.5 Scheduling UI changes (ranges)

- `api/types.ts`: `DurationEstimate`, `Task.duration_estimate?`, `ScheduleExplanation.duration_risk?`.
- `TaskTable`: duration cell shows "2.5 d" and, with a range, a chip "2-3 d" with a `Term` tooltip.
  Editing the inline duration of a task with a range removes `duration_estimate` (inline note "Range
  removed"); switching the type to milestone removes it too (2.14 write paths).
- `TaskDrawer`: "Duration is uncertain" toggle reveals optimistic / likely / pessimistic inputs; the
  expected value is computed with `pertMinutes` and written to `duration_minutes`; editing the single
  duration while a range exists asks "Remove the range?" (removes `duration_estimate`).
- `ScheduleTab`: shows `duration_risk.message` in the explanation panel.

### 3.6 General usability rules (apply to every touched screen)

- Inline validation next to the field on blur and on submit, with `aria-invalid` and `aria-describedby`;
  errors summarised at the top on submit with links to fields.
- Empty states for every list: one sentence of what goes here and the primary action button.
- Friendlier errors: `errorMessage()` maps `VALIDATION_ERROR` loc paths to field labels; network errors ->
  "Cannot reach the server. Check that it is running and try again." with a Retry button.
- Terms explained on hover and focus: `components/Term.tsx` (button with `aria-describedby` tooltip) +
  `lib/glossary.ts` entries: critical chain, makespan, hard/soft deadline, dependency, resource, calendar
  window, PERT/expected duration, duration range, real vs nominal, today's money, cautious return, glide
  path, risk level, growth assets, emergency fund, shortfall, chance of success, lock-in.
- Consistent buttons: primary verb first ("Create plan", "Make a draft", "Check draft", "Use suggestion",
  "Skip", "Start over"); destructive actions use `ConfirmDialog`.
- Keyboard and screen reader: all new controls reachable by Tab, visible focus, Enter/Space activate,
  `QuestionPanel` uses `aria-live="polite"`, highlighted spans are focusable `mark` elements with labels.

### 3.7 react-router 6 -> 7 upgrade and npm audit

- `package.json`: remove `"react-router-dom": "6.30.6"`, add `"react-router": "7.18.4"` (latest 7.x on npm
  today; peer `react >= 18`, Node >= 20; Node 22 is installed). Regenerate `package-lock.json` with
  `npm install`.
- Imports: every `from "react-router-dom"` -> `from "react-router"` (33 files); `main.tsx`: `RouterProvider`
  from `"react-router/dom"`, `createBrowserRouter`, `Navigate` from `"react-router"`; `RouteObject` type from
  `"react-router"`.
- Behaviour checks: no splat routes with relative links (`../schedule` etc. are in non-splat children, so
  v7 relative-path resolution is unchanged); no `json`/`defer`/`unstable_*` APIs used; v7 wraps navigation
  state updates in `startTransition` (React 18 supported). Same routes and URLs.
- Acceptance: `npm audit --omit=dev` and `npm audit` report 0 high and 0 moderate (today only
  `react-router` (advisory range `>=6.0.0 <7.18.0`) and `react-router-dom` (via it) are flagged, both moderate); `npm run build` and all 39
  existing Playwright tests pass.

### 3.8 Frontend tests (Playwright, `frontend/e2e/`)

New: `landing.spec.ts` (four kinds x four actions navigate correctly, keyboard only), `intake.spec.ts`
(schedule describe with the 2.15 text -> questions -> "Use suggestions for all remaining" -> review ->
create -> tasks tab shows "Gather requirements (1/3)" and the range chip; finance describe -> create ->
wizard review; AI toggle hidden when `ai_available` is false and the "built-in reader" line shown;
sessionStorage cleared after create), `import.spec.ts` (paste TSV, mapping suggestions, change one mapping,
apply, create; CSV file upload via `setInputFiles`). Existing 39 tests must pass unchanged.

---

## 4. File ownership and explicit edits to shared files

| Owner | Owns | Explicit edits outside the owned paths |
|---|---|---|
| Finance realism (backend) | `backend/superplanner/finance/**`, `backend/tests/finance/**` | `backend/tests/integration_finance/finint_helpers.py` (`plan_rho` -> 1.5 formula; `_cashflow` -> linked incomes 1.7); `backend/tests/integration_finance/test_finint_whatif.py` line 95 (`11.5` -> `12.0`); `backend/tests/api_finance/test_apifin_runs.py` lines 47 and 284 (`"fin-0.1.0"` -> `"fin-0.2.0"`, review fix); `docs/FINANCE.md` (one-line pointers to PHASE2 in sections 5, 8.2, 10.2, 12, 14, 15) |
| Intake backend | `backend/superplanner/intake/**`, `backend/superplanner/api/intake/**`, `backend/tests/intake/**` | `backend/superplanner/api/main.py` (import and include `intake.router`), `backend/superplanner/api/config.py` (settings of 2.12), `backend/requirements.txt` and `backend/pyproject.toml` (`anthropic==1.15.0`), `backend/superplanner/engine/model.py` (2.14), `backend/superplanner/engine/compiled.py` (estimate), `backend/superplanner/engine/explain.py` (`DurationRisk`), `backend/superplanner/engine/__init__.py` (exports), `backend/superplanner/api/services/replan_service.py` (2.14 write paths, review fix), `backend/superplanner/finance/templates.py` read-only use of `retirement_target` (no edit), `docs/ARCHITECTURE.md` (pointer in 3.4 and 11) |
| UI | `frontend/**` (incl. `package.json`, `package-lock.json`) except the test files below | none |
| Testing (review fix) | new `frontend/e2e/landing.spec.ts`, `intake.spec.ts`, `import.spec.ts`, `phase2-helpers.ts`; new `backend/tests/acceptance_phase2/**` | none; existing e2e files are not edited by anyone |

Cross-team contracts: intake builds `FinancePlan` with `inflation_linked` and `amount_range` (1.7, 1.12)
and imports `retirement_target` from `finance.templates` -> finance WP-A1 lands first. The UI depends on
the JSON shapes of 1.10, 1.11, 2.3-2.15 only.

---

## 5. Changes to existing behaviour and to existing tests

Behaviour (all intended):
1. Finance cautious return (1.5) applies to every run, including stored plans (they get default
   `caution`). Long-horizon goals now hold growth assets up to the risk cap; short goals are unchanged.
2. New default asset assumptions and inflation for new plans and templates (1.4); stored plans keep theirs.
3. Calibration aims at minimum + 1 pp (1.6): more calibration rounds are used, `planning_z` is often 0.25-0.5
   higher, contributions slightly higher, more goals `on_track`.
4. Template figures, holdings, incomes and retirement preset change (1.8); ids and parameter names do not.
5. Summary sentences: `SUMMARY_INVEST` replaced by `SUMMARY_SURPLUS*` / `SUMMARY_FUNDING*`; new first goal
   reason `GROWTH_*`; new binding `SHARED_SHORTFALL`; `FINANCE_ENGINE_VERSION` "fin-0.2.0".
6. KPI cards show first-year averages and the funding split (same test ids).
7. Scheduling `Task.duration_estimate` (optional) and `ScheduleExplanation.duration_risk` (optional);
   existing documents and results unchanged.
8. Landing page: `/` starts with "What do you want to plan?" (h1); "Your plans" becomes h2.
9. `react-router-dom` replaced by `react-router` 7.18.4.
10. Replan: updating the duration of a task that has a duration range removes the range (2.14).
11. Finance compare / what-if: `engine_versions_differ` flag and banner (1.13).

Existing tests updated (only these; each because of a numbered behaviour above):

| Test | Change | Reason |
|---|---|---|
| `backend/tests/finance/test_fin_templates.py::test_parameters_and_relative_dates` | retirement target `25 * 12 * (26000 + 12000)` | 4 |
| `backend/tests/finance/test_fin_pipeline.py` (engine version assertion) | `"fin-0.2.0"` | 5 |
| `backend/tests/finance/test_fin_boundaries.py:59` (`f.__version__`) | `"fin-0.2.0"` | 5 (review fix: missing from the architect's list) |
| `backend/tests/api_finance/test_apifin_runs.py:47` and `:284` | `"fin-0.2.0"` | 5 (review fix; finance owner edits these, section 4) |
| `backend/tests/finance/test_fin_optimizer.py:217-225` | pass `z0=initial_z(goal)` and `caution=p.assumptions.caution` to `planning_rho` | 1 (review fix: the new keyword-only arguments are required) |
| `backend/tests/finance/test_fin_whatif_compare.py` (return shift) | equity `11.0`, cash `3.5` if the fixture uses default classes | 2 |
| `backend/tests/integration_finance/test_finint_whatif.py` line 95 | `12.0 + shift` | 2 |
| `backend/tests/integration_finance/finint_helpers.py` | independent checker uses the 1.5 formula and linked incomes | 1, 4 |
| any test asserting `SUMMARY_INVEST` text or the summary line order | new codes | 5 |

`test_family_contents` (holding ids, earmark, EMI 10,000, risk 3) and all e2e tests are kept as they are;
the young professional's car stays not-on-track at defaults so `fix 'Try this'` keeps a fix to click. If a
further existing test fails, the implementer must either fix the code or document the test change here
before changing the test.

---

## 6. Deferred items

Phase 2b: background job workers, PostgreSQL as default, user accounts/auth. Also deferred:
- Per-class yearly contribution caps (real-world deposit limits for lock-in schemes), taxes.
- XLSX parsing (paste from Excel works as TSV), Google Sheets links, multi-sheet imports.
- AI-generated follow-up questions (only deterministic questions in 2a), AI in what-if or explanations,
  streaming AI responses, caching AI results.
- Working-time lags, resource cost extraction from text, DST/IANA time zones.
- Monte Carlo over duration ranges for schedules (2a shows the PERT note only).
- Server-side draft storage or sharing; drafts live in the browser session only.

---

## 7. Work packages and order

Superseded for delivery by `docs/PLAN-PHASE2.md` (P1, P2, P3a, P3b, P4); the list below is the architect's original order.

1. **WP-A1 finance model + defaults** (finance owner): `CautionSettings`, `inflation_linked`, `AmountRange`,
   new `ResultSummary`/`GoalResult` fields, defaults, `retirement_target` helper. Unblocks intake WP-B3.
2. **WP-A2 finance engine**: returns, optimizer/validator/advisor call sites, cash flow + simulator, calibration
   aim, funding split, growth reasons, templates; tests 1.14; test updates of section 5; independent checker.
3. **WP-B1 engine PERT** (intake owner): 2.14 and `test_engine_pert.py`.
4. **WP-B2 intake core**: models, text grammar, schedule/money extract, questions, answers, tables.
5. **WP-B3 builders + API**: 2.9, 2.15, settings, router registration.
6. **WP-B4 AI extractor**: 2.10, 2.11, `anthropic` dependency, fake-client tests.
7. **WP-C1 router upgrade** (UI): first, alone, all 39 e2e green, `npm audit` clean.
8. **WP-C2 landing + intake UI + import**, **WP-C3 finance/scheduling UI copy**, then e2e of 3.8.

Definition of done: all backend tests (existing 928, adjusted only per section 5, plus new) and all
Playwright tests pass; `npm audit` shows no high/moderate issues; the three finance templates meet the bands
of 1.14 at defaults.

---

## 8. Review notes (team lead)

Reviewed 2026-10-17 against the product-owner direction (Phase 2a A/B/C) and the code. LEAD reproduced:
the 1.2 planning-return table and the 1.5 table at `z0` (exact), the real returns of 1.4, the span offsets
of both 2.15 examples, the 2.15 build arithmetic (10,320 / 9,600 / 11,040 minutes, horizon 64), the
current test baseline (928 backend tests collected, 39 Playwright tests in 9 files), `npm audit` (2
moderate: `react-router` advisories GHSA-wrjc-x8rr-h8h6 and GHSA-337j-9hxr-rhxg, range `<7.18.0`), and that
7.18.4 is the `version-7` dist-tag (8.x exists but is out of scope). LEAD did not re-run the template
prototype of 1.9; P1 re-measures it.

Changes made in this document:
1. 1.5: the calibration penalty now lowers every class (scaled by `ramp(Y)`), not only the growth floor.
   Before: at `calibration_rounds` 3-4 (allowed, `le=4`) equity fell below `govt_long` again (must: 0.73 %
   vs 0.94 % at +0.75 z) and the LP went back to 100 % safe, against the direction "never collapses
   long-horizon growth assets". Table recomputed; properties adjusted (monotone in `Y` at `z0`, ranking
   preserved for all `z`); P1 may tune `floor_step_pct_per_z` within [1.0, 2.0] if a band fails.
2. 1.5 / section 5: `tests/finance/test_fin_optimizer.py:217-225` calls `planning_rho` positionally and
   breaks with the required keyword-only arguments; added to the test-change list.
3. Section 5: `fin-0.2.0` is also asserted in `tests/finance/test_fin_boundaries.py:59` and
   `tests/api_finance/test_apifin_runs.py:47,284` (the latter outside the finance folder); added, with
   ownership in section 4.
4. 1.11: `savings_to_cash_at_start` uses `(1 - tau) * sold_to_cash` as the pipeline does (`pipeline.py:206`).
5. 1.13: what-if/compare across `fin-0.1.0` and `fin-0.2.0` results mixed engine changes into the deltas;
   added `engine_versions_differ` and a UI banner.
6. 2.9.1 / 3.1: intake and "Build step by step" set `Problem.domain` through `DOMAIN_OF_KIND`
   (`study` -> `exam_prep`, `production` -> `manufacturing`) to match existing documents and `PlanList`.
7. 2.10: the availability check also accepts `client.credentials` (SDK 1.15.0 resolves profiles and
   workload identity there); without it a correctly configured server reports `AI_NO_CREDENTIALS`.
8. 2.10 / 2.16: SDK 1.15.0 is built on `httpx2`; test exceptions use `httpx2.Request`/`Response`. The SDK
   must be installed into `backend/.venv` (it is not today; dry run is clean).
9. 2.10: AI slots stored per app (`app.state`), SDK loggers capped at WARNING (no text in logs even at DEBUG),
   UI cancel and a 200 s client timeout for the 180 s worst case.
10. 2.13 / 2.15: table text had no size limit in the request models; added `TableParseRequest` and
   `max_length=1_000_000` (`TABLE_TOO_LARGE` stays for rows/columns), delimiter restricted to the four
   candidates.
11. 2.7: linear-time regex rule and a 20,000-character timing test (ReDoS); intake messages and prompts
   pass the finance denylist and `FORBIDDEN_WORDS`.
12. 2.14 / 3.5: the strict `duration_minutes == PERT` rule broke replan duration updates
   (`replan_service._apply_changes` revalidates the whole document -> 422) and the `TaskTable` inline edit
   and milestone switch; those paths now drop the estimate. `replan_service.py` added to the intake owner's
   explicit edits.
13. Section 4: the e2e specs of 3.8 and the cross-package acceptance tests belong to the tester, not the UI
   owner, so no file has two owners; existing e2e files are edited by nobody.
14. 3.7: advisory range corrected to `<7.18.0`.

Accepted as designed (checked, no change): the root-cause analysis R1-R8; equity 12 % / FD 7 % /
inflation 5.5 % within the cited ranges; template figures and the retirement preset; the young
professional's car at risk on purpose (chance about 2 % but about 97 % of target as the median: the
GoalCard "Likely outcome" line is required so this does not read as broken); the e2e preview check
`₹4[89],xxx` still holds at 5.5 % inflation (50,000 nominal -> first-year real average about 48,700); no
splat route renders relative links, so the v7 relative-path change does not apply; the stateless intake
API with no DB writes; the exact SDK call and the fallback catalog.

---

## 9. Implementation notes (one subsection per work package)

Each work package of `docs/PLAN-PHASE2.md` appends only to its own subsection (date, what, why). Test
changes beyond section 5 must be recorded here before the test is changed. P1 also owns the figures of
the 1.9 table (re-measured with the real code).

### 9.P1 Finance realism

2026-10-17 (P1, backend-developer A).

Done: P2D 1.4-1.14 in `backend/superplanner/finance/**`: `CautionSettings` + `Assumptions.caution`,
`IncomeStream.inflation_linked`, `AmountRange` (+ `IncomeStream.amount_range`, `Expense.amount_range`,
`Goal.target_range`), `GoalResult.growth_share_now_pct` / `growth_cap_now_pct`, the seven `ResultSummary`
fields of 1.11, `FinanceComparison.engine_versions_differ`, `templates.retirement_target(expenses, incomes)`,
defaults and `SOURCE_NOTE`, `FINANCE_ENGINE_VERSION = "fin-0.2.0"`, `defaults.CALIBRATION_AIM = 0.01`,
`returns.planning_return/planning_rho(..., *, z0, caution)` (all callers: optimizer, validator, advisor; the
pipeline's `planning_returns_pct` reads the optimizer's rho), linked incomes in `cashflow.py` (new
`FlowComponents.inc_int_linked`, default `None` so hand-built components still work), `simulate.py` and
`whatif.py`, templates (1.8), growth reasons, `SHARED_SHORTFALL`, the summary lines, `AMOUNT_OUTSIDE_RANGE`,
`ASSUMPTION_RANGE`, the independent checker in `finint_helpers.py`. Model contract (step 1) field names and
types are exactly those of 1.5, 1.7, 1.10-1.13; all exported from `superplanner.finance`
(`retirement_target` from `superplanner.finance.templates`).

Interpretations and corrections (the formula and the 1.5 table are implemented exactly; the table matches to
0.01 pp):
1. 1.5 properties that do not hold for the 1.5 formula, tests written against what holds:
   - "continuous in `Y`" holds only for `Y > floor_start_years`. At `floor_start_years` a class whose honest
     quantile `q` is negative steps up to about 0 (`max(q, phi * max(med, 0))` with `phi > 0`): equity at 37
     months is about 0.0 % instead of -5.6 %, cash 0 % instead of -1.9 %. No continuous variant keeps the 1.5
     table. The LP choice is unaffected with the defaults: from 37 to 60 months equity and gold stay below the
     best safe class (`test_step_at_floor_start_is_upwards_and_keeps_short_goals_on_safe_classes`).
   - "equity's lead at `z >= z0` is at least its lead at `z0`" holds only where equity sits on its floor at
     `z0` (p >= 0.85). For p = 0.5 / 0.7 equity's honest quantile is above its floor at `z0` and falls faster
     than the safe classes' as `z` rises. The ranking still holds: equity beats the best safe class by
     >= 0.25 pp over the whole 1.14 grid.
   - "each step lowers every class by up to 0.5 pp": the *common* shift is 0.5 pp x `ramp(Y)` per step, but the
     honest quantile of a class can fall further (FD at 10 years: 0.82 % -> 0.20 %, 0.62 pp). Tested: every step
     lowers every volatile class by at least the common shift.
2. `floor_step_pct_per_z` stays 2.0: all 1.14 bands pass at seeds 0, 1 and 7 (table in 1.9).
3. Growth reasons (1.10): P1-5 requires the risk level in every message when a risky class is allowed, but the
   1.10 templates of rules 2, 5 and 6 have none. Rules 1, 3, 4 use the 1.10 text unchanged; rules 2, 5, 6 get a
   risk-level clause: `GROWTH_LIMITED_GLOBAL` "... limited by your overall equity limit of {pct}% (your risk
   level {level} of 5 would allow more).", `GROWTH_NONE_SHORT` "...over a few years; your risk level {level} of
   5 matters for goals further away.", `GROWTH_NONE_RETURNS` "...once the cautious margin is applied, even at
   your risk level {level} of 5." `{safe}` uses the new catalog entry `SAFE_RETURN` ("{name} at {pct}% after
   inflation"). Rule 2 fires only for the global equity cap (its message names that limit), when it binds in
   the goal's first contribution block and is below the goal's own cap; class caps fall through to rules 3/4.
   `{years}` uses the new `messages.duration_text` ("25 years", "3 years 6 months", "8 months").
4. `{glide_month}` is the first block whose cap is below the base cap. With 12-month blocks the cap is still
   full at `D - 120` (glide multiplier 1.0 at 120 months), so the family retirement message says "2042-11"
   (the 1.10 example's "2041-11" is `D - 120`). Otherwise the message is word for word the 1.10 example.
5. `growth_cap_now_pct` is the cap of the goal's first contribution block, so short goals show their real cap
   (car 37.5 %, home 30 %), not the "0 %" of the architect's prototype table; their share stays 0 % because
   the LP prefers the safe classes there.
6. Summary: `SUMMARY_FUNDING_NONE` when `monthly_contribution_avg_12m < 0.5`; `monthly_from_savings_avg_12m =
   round(contribution_avg, 2) - round(from_surplus_avg, 2)` (never negative), so the identity holds to 0.01.
7. `AMOUNT_OUTSIDE_RANGE` is a warning in `preflight.WARNING_CODES` (0.005 tolerance at the bounds); the
   message uses `format_money` in the plan currency. `whatif_income_drop_linked` is named "Income drop
   (inflation-linked income)"; `interruptible_monthly_income(plan, month, *, linked=False)` keeps the old
   result for nominal streams.

Existing tests changed beyond section 5 (each because of the behaviour named):
- `tests/finance/test_fin_optimizer.py:29`: the single-goal fixture stores no inflation, so the expected
  annuity uses `p.assumptions.inflation_pct` instead of the hard-coded 0.06 (behaviour 2, default 5.5 %).
- `tests/finance/test_fin_export_bridge.py:42`: the family's emergency fund is complete at the start with the
  new holdings (behaviour 4), so the CSV `emergency_fund` row is asserted on the young professional.
- `tests/finance/test_fin_pipeline.py::test_calibration_raises_z_and_probability`: the "below minimum" set uses
  the new aim (`+ CALIBRATION_AIM`) and only goals planned to their target (the calibration precondition); the
  car is short by design now (behaviours 3, 4).
- `tests/finance/test_fin_preflight.py` `CASES`: one `AMOUNT_OUTSIDE_RANGE` case (the coverage test requires a
  case for every code; behaviour 1.12).
- `tests/finance/test_fin_review_fixes.py::test_unfunded_nice_goal_gets_no_micro_contributions` and
  `tests/integration_finance/test_finint_infeasible.py::test_unfunded_lower_priority_goal_gets_no_forced_micro_contributions`:
  near retirement is affordable now (behaviour 4); `take_home = 120000` restores the "retirement is short"
  precondition (retirement 22 % short, wedding unfunded).
- `tests/integration_finance/test_finint_whatif.py` `family` fixture: `take_home = 120000` keeps every family
  goal short (33 % each), the precondition of the monotonicity tests (behaviour 4).
- `tests/api_finance/test_apifin_results.py::test_compare_shape_and_route_order`: the compare key set includes
  `engine_versions_differ` (false for two current results; behaviour 11).
- `tests/api_finance/test_apifin_flow.py` step 6: month-0 contribution of the what-if (+10,000 savings) may be
  up to 0.5 % below the baseline's. Measured: 21,364.61 vs 21,382.86; the retirement goal is on track in both and
  the LP moves 18 rupees of its month-0 level between blocks, while the first-year average rises (44,724 vs
  43,249). Month 0 alone is not monotone in extra savings.

New tests (`backend/tests/finance/`): `test_fin_caution.py` (1.5 table, properties, grid, settings),
`test_fin_linked_income.py`, `test_fin_realism_templates.py` (bands at seeds 0/1, seed 7 statuses, run time,
template figures and `retirement_target`), `test_fin_growth_assets.py` (growth bands, first reason,
calibration with 4 rounds and with a 0.99 minimum, restricted / global-cap rules, `SHARED_SHORTFALL`, message
compliance), `test_fin_funding_split.py`, `test_fin_ranges.py`, `test_fin_calibration_aim.py` (aim, stored
document compatibility, mixed engine versions).

### 9.P2 Intake backend and duration ranges

### 9.P3a Router upgrade, usability, landing

### 9.P3b Intake UI

### 9.P4 Testing

