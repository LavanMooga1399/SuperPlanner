# SuperPlanner M8 - Make-to-stock planning at volume (design + plan + acceptance)

Status: design for build, 25 November 2026. Milestone M8 of `docs/MEDDEV-GAP-PLAN.md` (size 1.3). Builds on M1-M7 as
built (`docs/M1-DESIGN.md` .. `docs/M7-DESIGN.md`, cited "M2 8.3" etc., incl. implementation notes) and the UX
standard. Their conventions apply unchanged and are not restated (ids, `row_version` + If-Match, error envelope,
`owner_id` = one plant, one permission per route, audit on every write, outbox events, jobs on the PostgreSQL queue,
immutable runs, independent validators, expand migrations). Interpretations go to section 15 only.

Scope: statistical demand forecasting with consumption and overrides; ABC/XYZ and safety stock by service level;
MRP for volume (forecast demand, time zones of daily/weekly/monthly buckets, packaging units, kanban, rate supplies);
a rate/campaign engine for flow lines; EtO sterilisation load planning with release holds; SAP S/4HANA adapter;
validation kit v1; load test at BD-like scale. Sample: `meddev` (+ `meddev_m8.py`).

## 0. Decisions

1. **Three planning layers, coupled through MRP, run as one nightly chain.** Forecast -> MRP pass 1 (net
   requirements of rate items) -> rate engine (campaigns on flow lines) -> sterilisation load plan -> MRP pass 2
   (rate supplies replace planned orders of rate items; components and bought items are planned from them). Stages
   (moulding -> assembly -> packaging -> EtO) are coupled through MRP dependent demand, not inside one solver. M3 APS
   keeps discrete/batch work centers; flow and sterilisation lines are invisible to APS.
2. **Forecasting is a pure numpy package** (`mfg/forecast`), vectorised across items, no new packages. Grain item x
   period (month default, week option), plant level (no customer/location split; DC/customer level is M9).
   Candidates: seasonal naive, moving average (3/6/12), SES, Holt damped, Holt-Winters additive and multiplicative,
   Croston and SBA. **Selection by holdout WAPE** (ties: lower |bias|, then simpler model). Demand class
   (Syntetos-Boylan: ADI 1.32, CV^2 0.49) restricts candidates.
3. **Forecast versions are immutable after activation; overrides are lines, not edits.** One `active` version per
   plant feeds MRP. Overrides (absolute or %, item or family) always carry a reason and are audited old/new. No
   e-signature in M8 (signed consensus = M9 S&OP).
4. **Consumption** (per item, in the daily-spread forecast): each open customer order line consumes forecast
   backward `consume_back_days` (30) then forward `consume_fwd_days` (30); requirement = orders + unconsumed
   forecast. Past unconsumed forecast is dropped. Done in a pure function before MRP; MRP gets `forecast`
   requirements ranked after customer orders and before safety stock.
5. **Safety stock = z(SL) x sqrt(LT x sigma_d^2 + d^2 x sigma_LT^2)** per item (plant level), sigma_d from the
   chosen model's 1-step errors, sigma_LT from PO receipt history (>= 5 receipts) else 0. Service level from an
   ABC x XYZ matrix. Results are **proposals**; approval writes M1 `safety_stock` with audit reason. Never automatic.
6. **MRP stays exact-date** (M2 0.6); "daily buckets" = demand time zones: forecast enters MRP spread per working day
   for `daily_days` (28), per week (Monday) up to `weekly_weeks` (26), per month after. Packaging hierarchy per item
   (each/inner/case/pallet) drives order multiples and display. `replenishment` per item: `mrp` | `rate` | `kanban`.
   Kanban items get no planned orders: their residual is a `kanban` pseudo-supply that still explodes components.
7. **Rate engine = greedy run-out construction + CP-SAT window improvement per line**, lines in parallel. Hard:
   shift windows, eligibility, rates x OEE, sequence-dependent changeover/cleaning/clearance, periodic cleaning,
   min/max campaign length, case rounding. Objective lexicographic: shortage unit-days (priority-weighted) ->
   changeover cost -> excess cover -> overtime cost. Material is a **warning** (`RATE_MATERIAL_SHORT`), not hard:
   MRP pass 2 plans components from the rate plan (contrast M3 0.3, which schedules against existing supply).
8. **Publish turns the firm zone into repetitive WOs** (`kind repetitive`, one per campaign per production day =
   one lot per line-day, configurable `campaign`); later blocks stay `rate` supplies. Execution is M4 unchanged.
9. **EtO is a load planner, not a solver**: greedy first-fit by ready time per cycle code, chamber capacity in
   pallets, aeration as cumulative pallet-positions over time, release wait as an automatic M7 hold (new source
   `sterility`) with a planned release date; release is a signed QA action (M7 policy `ster_load.release`).
10. **SAP S/4HANA = adapter `sap_s4` on M5 `generic_v1`** (OData v4/v2 JSON, no IDoc, no RFC) plus a pull client
    job; tested against recorded payloads and a fake OData server; no SAP in CI.
11. **Validation kit v1 lives in the repo**: requirement register YAML, pytest/e2e markers, `manage.py trace-matrix`,
    CSA risk per requirement, configuration baseline with hash and diff. The M8 test vectors (14.3) are the M8
    requirement register.
12. **Lean delivery**: WP-S (one backend developer), WP-U (one UI developer), S0 contract freeze (day 1-2), targeted
    tests, one full suite at the end. Migration `0011_m8` (expand). No new Python or npm packages; k6 is an external
    binary used only by `scripts/load`.

## 1. Scope and principles

**Principles** (in addition to M1-M7): V1 a plan never hides a shortfall (unmet demand is shown with its cause);
V2 statistics propose, planners decide (overrides, SS approvals, publish are explicit and audited); V3 every
engine output passes an independent validator before it can be published; V4 units are aggregated, never tasks.

**Out of M8 (deferred):** customer/location-level forecasts, DRP, consensus/S&OP signing, ramp-up curves (M9);
forecast by causal drivers/ML, promotions, multi-echelon SS (later); joint multi-stage rate optimisation, crew
planning on flow lines (later); `move` kanban loops (supermarket from warehouse), electronic kanban to suppliers
(later); IDoc/RFC, SAP PP-DS and IBP integration (on request); IQ/OQ/PQ, full validation package, signed BD-scale
load sign-off (M10); GS1 labels on packaging levels (M10, levels prepared here).

## 2. Package layout (ownership in 13)

```
backend/superplanner/
  mfg/forecast/   model.py history.py (build, clean) methods.py (vectorised models) select.py (holdout, classes)
                  consume.py (spread + consumption) accuracy.py
  mfg/invopt/     model.py classify.py (ABC/XYZ) safety.py (z, formula, rounding)
  mfg/rate/       model.py build.py (snapshot -> lines, demand) construct.py improve.py (CP-SAT windows)
                  validator.py explain.py publish.py views.py
  mfg/ster/       model.py loads.py (first-fit, aeration) validator.py
  mfg/kanban.py   loop sizing, card state machine, signal -> PR/WO
  mfg/mrp/        (edits) model.py, engine.py, lotsize.py, views.py: forecast reqs, kanban/rate supplies, packs
  integration/adapters/sap_s4.py  integration/sap/{odata.py (client), mapping.py, fixtures/*.json}
  validation/     register.py trace.py (scan + junit merge) baseline.py; docs/validation/requirements.yaml
  api/mfg/        db_models_m8.py repo_m8.py router_m8.py services/{forecast,invopt,rate,ster,kanban,valid}.py
  mfg/samples/meddev_m8.py   scripts/load/{seed.py, k6/*.js, README.md}
frontend/src/mfg/{forecast,invopt,rate,ster,kanban,validation}/**  frontend/src/lib/strings/planning.ts (+ fr-CA)
```

## 3. Data (migration `0011_m8`, expand, additive; downgrade drops)

IDs: `dh_` history, `fcr_` forecast run, `fcv_` version, `fcl_` line, `fco_` override, `ssp_` SS proposal run, `ssl_`
SS line, `pkg_` packaging, `ipl8_` item planning, `lrt_` line rate, `chg_` changeover row, `rr_` rate run, `rb_`
rate block, `sl_` ster load, `kbl_` kanban loop, `kbc_` card, `vb_` baseline. Numbers: `FC-000001`, `SSP-000001`,
`RR-000001`, `SL-000001`, `KB-000001`.

| Table | Columns (all plant-owned) |
|---|---|
| `mfg_item_planning` (master, 1:1 item) | item_id uq, replenishment S8 (`mrp`,`rate`,`kanban`), forecast Bool, like_item_id N, like_factor Dbl (1.0), service_level Dbl N (override), order_pack_level S8 N, campaign_key S32 N, campaign_min_hours Dbl (0), campaign_max_hours Dbl N, target_cover_days Int (10), ster_cycle_code S16 N, aeration_hours Dbl N, release_mode S12 (`none`,`bi`,`parametric`), release_days Dbl (0), post_days Int N (production end -> available; None = derived from ster), abc S1 N, xyz S1 N (computed, read-only) |
| `mfg_item_packaging` (master) | item_id, level S8 (`each`,`inner`,`case`,`pallet`), seq Int, code S32, qty_base Dbl (base units per level; strictly increasing by seq, integer multiple of the previous level), gtin S14 N, weight_kg Dbl N; uq (item_id, level) |
| `mfg_line_rates` (master) | line_id, item_id N, item_family S32 N (exactly one), units_per_hour Dbl, oee Dbl N (None = line oee); uq |
| `mfg_changeover_rows` (master) | line_setup_family S32, from_key S32 or `*`, to_key S32 or `*`, minutes Int, cost Dbl, kind S10 (`changeover`,`cleaning`,`clearance`); uq; most specific wins (M3 3.2 rule); key = item `campaign_key`, else item `setup_family` |
| `mfg_demand_history` | item_id, period_start Date, bucket S1 (`m`,`w`), qty Dbl, cleaned_qty Dbl N, source S8 (`ledger`,`import`,`sap`), updated_at; uq (owner_id, item_id, bucket, period_start) |
| `mfg_forecast_runs` | number, params JSON, status, as_of Date, item_count Int, summary JSON (WAPE/bias by ABC class, method mix), results JSON (per item: class, method, params, holdout_wape, bias, rmse1, fitted tail, flags), started/finished, actor |
| `mfg_forecast_versions` | number, name, run_id N, status S10 (`draft`,`active`,`archived`), bucket S1, start Date, periods Int, activated_by/at N, note |
| `mfg_forecast_lines` | version_id FK CASCADE, item_id, period_start Date, stat_qty Dbl, final_qty Dbl; uq (version_id, item_id, period_start); ix (owner_id, item_id) |
| `mfg_forecast_overrides` | version_id FK, item_id N, item_family S32 N, period_from Date, period_to Date, mode S4 (`abs`,`pct`), value Dbl, reason S500 (required), seq Int, created_by/at, removed_at N |
| `mfg_ss_runs` / `mfg_ss_lines` | run: number, params JSON, status, forecast_version_id, summary JSON; line: run_id FK, item_id, abc, xyz, service_level, z, d_day, sigma_d_day, lt_days, sigma_lt_days, current_ss, proposed_ss, delta_value, decision S10 (`pending`,`approved`,`rejected`), decided_by/at N |
| `mfg_rate_runs` | number, params JSON, status, mrp_run_id, as_of, horizon_days, published Bool, published_at/by N, objective JSON, summary JSON, explanations JSON, validator JSON, duration_ms |
| `mfg_rate_blocks` | run_id FK CASCADE, line_id, kind S10 (`production`,`changeover`,`cleaning`,`clearance`,`down`), item_id N, campaign_no Int, start DT, end DT, qty Dbl, cases Int N, prod_date Date (plant-local), wo_id N; ix (run_id, line_id, start) |
| `mfg_ster_loads` | number, run_id N (plan) or N (ad hoc), chamber_line_id, cycle_code, status S12 (`planned`,`loaded`,`cycling`,`aerating`,`awaiting_release`,`released`,`failed`,`cancelled`), pallets Int, planned_start/end DT, aeration_end DT, release_due Date, actual_* DT N, batch_load_id N (M4), release_signature_id N, ncr_id N |
| `mfg_ster_load_members` | load_id FK CASCADE, wo_id N, rate_block_id N, lot_id N, item_id, qty, pallets Dbl |
| `mfg_kanban_loops` / `mfg_kanban_cards` | loop: number, item_id, location_id, source S4 (`buy`,`make`), supplier_id N, line_id N, cards Int, container_qty Dbl, lead_time_days Int, trigger S12 (`scan`,`consumption`), status; card: loop_id FK, card_no Int, state S12 (`full`,`empty`,`in_process`), doc_type/doc_id N, changed_at |
| `val_baselines` | label, created_by/at, sha256 S64, content JSON |

Columns: `mfg_lines.planning` S16 (`discrete`; `flow`, `sterilisation`), `oee` Dbl (0.85), `clearance_minutes` Int
(0), `clean_every_hours` Dbl N, `clean_minutes` Int N, `chamber_pallets` Int N, `cycle_hours` Dbl N;
`mfg_plant.planning_settings` JSON (4.6); `mfg_work_orders.kind` gains `repetitive`, `kanban`, + `rate_run_id` N;
`mfg_lot_holds.source` gains `sterility`, + `planned_release` Date N. Aeration rooms are lines of a group with
`kind aeration` (`chamber_pallets` = pallet positions; no new table).
Jobs: `forecast_run`, `ss_run`, `rate_run`, `ster_plan`, `nightly_plan` (chain, 6), `history_refresh` (daily),
`sap_sync`. Retention: runs keep the last 90 + published/active ones; versions, overrides, loads indefinite.

## 4. Forecasting (`mfg/forecast`)

### 4.1 History
`history_refresh` (daily, incremental) aggregates `ship` postings (M2 4.1) by item x period into `source ledger`
rows; `history_basis` `shipments` (default) or `orders` (demand lines by original due date, for supply-constrained
periods). Import sheet `demand_history` (**part_number, period_start**, qty) and SAP (9) write `import`/`sap` rows;
for one (item, period) the precedence is import > sap > ledger. Cleaning (default on): values outside median +/- 5 x
MAD of the item's series are clipped into `cleaned_qty` (flag `FC_OUTLIER`); the planner can reset per row. Items
with `like_item_id` and < 12 periods use the like item's history x `like_factor`.

### 4.2 Methods and selection (`methods.py`, `select.py`)
Input matrix `Y[items, periods]` (cleaned, zero-filled from the first non-zero period). Season length m = 12
(monthly) / 52 (weekly). Grids: alpha {0.05,0.1,0.2,0.3,0.5}, beta {0.02,0.05,0.1,0.2}, phi {0.9,0.95,0.98},
gamma {0.05,0.1,0.2}; MA n {3,6,12}; Croston/SBA alpha {0.05,0.1,0.2}. Fit = grid minimum of in-sample 1-step SSE
over the training part, vectorised over items per grid point.

| Class (ADI, CV^2) | Candidates | Min history |
|---|---|---|
| smooth / erratic (ADI < 1.32) | snaive, MA, SES, Holt damped, HW add, HW mul (only if all > 0) | HW: 2m + holdout; Holt: 8; else 3 |
| intermittent / lumpy (ADI >= 1.32) | MA, Croston, SBA | 6 |
| < 3 non-zero periods | none: zero stat forecast, `FC_HISTORY_SHORT` (manual only) | - |

Holdout h = min(6, n // 4) periods (weekly: min(13, n // 4)); each candidate is fitted on the first n - h periods,
forecast h steps from that origin, scored WAPE = sum|e| / sum(y) (bias = sum e / sum y). Winner refitted on all n;
forecast `horizon_periods` (18 months / 78 weeks). Outputs per item: method, params, wape, bias, rmse1 (1-step
in-sample, for SS), class, flags (`FC_HIGH_ERROR` when WAPE > 0.5 for A items). Negative forecasts clipped at 0.
Determinism: fixed grid order, no randomness. Run report: weighted WAPE (by volume) overall and per ABC class.

### 4.3 Versions and overrides
A forecast run creates a `draft` version (`stat_qty` = model, `final_qty` = stat). Overrides apply in `seq` order:
`abs` sets the item-period value, `pct` multiplies; a family override applies to each item of the family (split
proportionally to stat). `final_qty` is recomputed on every override change (draft only). `POST /activate` archives
the previous active version. A draft can copy overrides from the active version (overrides whose periods are still
in the horizon). Audit: override create/remove with old/new final values and reason.

### 4.4 Consumption and MRP feed (`consume.py`)
1. Spread `final_qty` of the active version to working days of the plant calendar (M2 `workdays`), proportional.
2. Customer orders (`demand_type customer`, open, per item, by due date ascending) consume daily forecast from due
   date backward `consume_back_days`, then forward `consume_fwd_days`; leftovers = over-consumption (info
   `FC_OVERCONSUMED`, the order still counts fully).
3. Days before `as_of` dropped; remaining forecast aggregated into time zones (0.6) -> `ForecastSnap(item_id, date,
   qty, version_id, period_start)`. Output also a consumption view per item x period (forecast, consumed, open).

### 4.5 Accuracy (`accuracy.py`)
Backtest report per run (4.2). Tracking: for each closed period, lag-1 and lag-3 forecast = the `final_qty` of the
version active 1 / 3 periods before period start (versions are immutable) vs history; WAPE, bias by item, family,
ABC; computed on read, cached per period.

### 4.6 `planning_settings` (defaults)
`forecast_bucket m`, `horizon_periods 18`, `history_basis shipments`, `outlier_clean true`, `consume_back_days 30`,
`consume_fwd_days 30`, `forecast_priority 7`, `daily_days 28`, `weekly_weeks 26`, `abc_cutoffs [0.8, 0.95]`,
`xyz_cutoffs [0.5, 1.0]`, `sl_matrix {AX .99, AY .98, AZ .95, BX .98, BY .97, BZ .95, CX .97, CY .95, CZ .90}`,
`ss_max_cover_days 60`, `rate_horizon_days 30`, `rate_firm_days 3`, `rate_wo_split day`, `rate_time_budget_s 240`,
`ster_max_wait_hours 8`, `nightly_at "02:00"`.

## 5. Inventory optimisation (`mfg/invopt`)

- **ABC**: items with `forecast true` (and their history-only peers) ranked by 12-month value = forecast (else
  history) x `standard_cost` (missing cost -> volume, flag); cumulative share <= 0.8 A, <= 0.95 B, else C.
- **XYZ**: CV = rmse1 / mean period demand of the chosen model (intermittent: CV of non-zero sizes x sqrt(ADI));
  < 0.5 X, < 1.0 Y, else Z.
- **SS**: SL = item override, else matrix; z = inverse normal (Acklam rational approximation, no scipy); d = mean
  daily forecast next 90 days; sigma_d = rmse1 / sqrt(working days per period); LT = working days (buy: preferred
  item-supplier lead + receiving days; make: `lead_time_days` + `post_days`); sigma_LT = std of (actual receipt
  date - confirmed date) of the last 20 PO receipts if >= 5, else 0. Proposed SS rounded up to the order pack level,
  capped at `ss_max_cover_days` x d (`SS_CAPPED`). Dependent-only items (no forecast, no history) are skipped.
- Approve (bulk or per line) writes `mfg_items.safety_stock` with audit reason `SSP-000123 approved`.

## 6. MRP changes (M2 8, `mfg/mrp`)

- `MrpParams` += `forecast_version_id: EntityId | None` (None = active; `"none"` = no forecast -> what-if),
  `rate_supply: bool = True`, `rate_run_id: EntityId | None` (None = published).
- `Requirement.kind` += `forecast` (rank: by `forecast_priority`, after customer orders of the same date, before
  safety stock; `source` = version + period; never `late` beyond its zone date, reported as `MRP_FORECAST_SHORT`).
- `Supply.kind` += `kanban` (pseudo, 6.2), `rate` (published rate blocks not converted to WOs; qty at `avail_date`
  = block `prod_date` + `post_days`, or the planned ster load release date when the item is sterilised).
- **Packaging**: when `order_pack_level` is set, the effective order multiple = that level's `qty_base` (replaces
  item `order_multiple`; MOQ rounded up to it). Views and the API add `packs: {case, pallet}` to quantities of items
  with packaging (`views.bucketize` unchanged otherwise).
- **Rate items**: in pass 1 (`rate_supply false`) residuals become planned orders (lot rule forced to `period` 1 day
  in the daily zone, 7 in weekly, month in monthly) = demand to the rate engine. In pass 2 residuals after rate
  supplies are still planned (components explode) and flagged `MRP_RATE_SHORT` (error) - V1.
- **Kanban items**: residual becomes a `kanban` supply on the need date (no planned order, no action message);
  components explode from it. Check `MRP_KANBAN_UNDERSIZED` (warning) when average daily requirement over 28 days x
  lead time x 1.2 > (cards - 1) x container_qty.
- Exceptions added: `MRP_FORECAST_SHORT`, `MRP_RATE_SHORT`, `MRP_KANBAN_UNDERSIZED`, `MRP_PACK_ROUNDING` (info).

### 6.1 Nightly chain (`nightly_plan` job, per plant, at `nightly_at`)
`history_refresh` -> (monthly, first working day: `forecast_run` + `ss_run`, drafts only) -> MRP pass 1 (live,
`rate_supply false`, label `nightly-1`) -> `rate_run` (auto-publish only if `planning_settings.auto_publish`
(false); else stays a proposal) -> `ster_plan` -> MRP pass 2 (live). Each step is its own job; a failure stops the
chain and notifies planners. M2 "one running MRP per plant" holds (steps are sequential).

### 6.2 Kanban (`mfg/kanban.py`)
Card scan code `KB:<card id>` (M4 scan). Trigger `scan`: scanning a full card sets it `empty` and creates the signal;
`consumption`: issues/backflush from the loop location decrement a counter; every `container_qty` issued empties
one card. Signal: `buy` -> PR line (submitted, preferred supplier, qty = container); `make` -> WO `kind kanban`
(`planned`, qty = container, due = today + lead). Receipt of that PR/WO at the loop location sets the card `full`.
Sizing suggestion: cards = ceil(d x LT x 1.2 / container) + 1.

## 7. Rate engine (`mfg/rate`)

### 7.1 Contract (`rate/model.py`, frozen at S0)
```python
class RateParams(MfgModel):            # POST /mfg/rate/runs
    label: str = ""; mrp_run_id: EntityId | None = None     # None = latest live pass-1 run
    horizon_days: int | None = None                         # 7..60; None = planning_settings
    line_ids: list[EntityId] | None = None                  # None = all flow lines
    overtime: Literal["off", "suggest", "allow"] = "suggest"
    time_budget_s: int | None = None                        # 10..900
    keep_firm: bool = True                                  # blocks of the published run inside firm zone fixed
class RateDemand: item_id; due: date; qty: float; priority: int; source: Literal["order","forecast","ss","dependent"]
class RateBlock:  line_id; kind; item_id | None; campaign_no; start; end; qty; cases | None; prod_date
class RateResult: params; blocks: list[RateBlock]; shortages: list[{item_id, due, qty, cause}]
                  objective: {shortage_unit_days, changeover_cost, changeover_hours, excess_cover_unit_days,
                  overtime_cost}; explanations; validator: {ok, violations: [{code, line_id, block_ix, detail}]}
```
Demand = pass-1 planned orders of `rate` items (due = need date - `post_days`), keyed by the source of their pegs.

### 7.2 Algorithm
1. **Capacity**: per flow line, shift windows from M1 `calendar.line_windows` (+ optional windows per `overtime`
   policy as M3 0.5), minus exceptions. Effective rate = `units_per_hour` x OEE (item row > family row; no row ->
   item not eligible on that line).
2. **Assignment**: items with several eligible lines go to the line with the lowest load ratio (cumulative demand
   hours / available hours over the horizon), deterministic ties by line code; an item may split across lines only
   when a single line cannot cover it (`RATE_SPLIT` info).
3. **Construction per line** (run-out): from the current state (stock + firm blocks), repeatedly pick the item with
   the earliest projected run-out (priority-weighted), insert changeover (matrix; `clearance_minutes` between any two
   items), produce until cover reaches `target_cover_days` or `campaign_max_hours`, at least `campaign_min_hours`,
   quantity rounded up to cases; insert cleaning when cumulative run hours reach `clean_every_hours`.
4. **Improvement**: CP-SAT per line over rolling 7-day windows (<= 30 campaigns): intervals + `AddNoOverlap`,
   sequence via `AddCircuit` with matrix changeovers, campaign quantities as integer cases, run-out shortage as
   piecewise penalties; lexicographic objective by weighted stages; accept only validator-clean improvements; LNS
   rounds until budget. Lines run in a process pool (`RATE_WORKERS`, default 4). Fallback when CP-SAT finds nothing:
   construction result.
5. **Validator** (`validator.py`, independent code): blocks inside windows, no overlap per line, correct changeover
   / clearance / cleaning blocks between consecutive productions, qty = rate x hours (+-1 case), min/max campaign,
   eligibility, firm blocks unchanged. Any violation -> run `failed_validation`, never publishable.
6. **Explanations** per shortage: `RATE_CAPACITY` (line hours short in window, with load %), `RATE_NO_LINE`,
   `RATE_MIN_CAMPAIGN`, `RATE_CHANGEOVER_BOUND` (changeovers > 25 % of hours); warnings `RATE_MATERIAL_SHORT` (block
   start before the pass-1 projected availability of a component, from pegging).

### 7.3 Publish (`publish.py`)
`POST /rate/runs/{id}/publish` (validator ok): blocks with `prod_date <= today + rate_firm_days` become WOs `kind
repetitive` (one per line x item x prod_date, or per campaign), status `released`, routing = item routing, the
flow-line operation pinned to the block line, `rate_run_id` set; unstarted repetitive WOs of the previous run in
the zone that no longer match are cancelled (started ones kept and fixed). Later blocks become `rate` supplies.

## 8. Sterilisation (`mfg/ster`)

- Pallets per member = ceil(qty / pallet `qty_base`) (no pallet level -> `STER_NO_PALLET`, item skipped).
- **Plan** (`ster_plan` job / on demand): candidates = repetitive and discrete WOs plus `rate` blocks of items with
  `ster_cycle_code`, ready at block end + packaging offset 0; sorted by ready time; first-fit into an open load of
  the same cycle code on the chamber with the earliest feasible start; a load closes when full or the oldest
  member waited `ster_max_wait_hours`; load duration = `cycle_hours`; aeration = max member `aeration_hours`,
  needs pallet positions in an `aeration` group for that duration (cumulative check over time; full -> load start
  delayed, `STER_AERATION_BOUND`). Release date = aeration end + `release_days` (BI: e.g. 7; parametric: 1).
- Output loads feed MRP pass 2 `avail_date` (6) and the floor: `POST /ster/loads/{id}/load` creates the M4 batch
  load with the member WOs (M4 6.3) and marks `loaded`; floor events move `cycling` -> `aerating`.
- At cycle complete: holds `source sterility` with `planned_release` on every member lot. `POST /release`
  (permission `ster_release`, M7 signature policy `ster_load.release`, default `approved` by `qa_approver`) lifts
  them; `POST /fail` keeps holds and creates one M7 NCR with all lots. M5 trace gains edge kind `ster_load`
  (lot -> load -> lot, "co-sterilised") so a recall query shows load siblings.

## 9. SAP S/4HANA adapter (`integration/adapters/sap_s4.py`)

| Entity | SAP API (OData) | Direction |
|---|---|---|
| item, item planning extras | `API_PRODUCT_SRV` (`A_Product`, `A_ProductPlant`, `A_ProductUnitsOfMeasure` -> packaging levels) | in |
| BOM / routing | `API_BILL_OF_MATERIAL_SRV;v=0002`, `API_PRODUCTION_ROUTING` (via ECO auto-approve, M5 4.4) | in |
| supplier, item-supplier | `API_BUSINESS_PARTNER`, `API_INFORECORD_PROCESS_SRV` | in |
| stock snapshot | `API_MATERIAL_STOCK_SRV` (`A_MatlStkInAcctMod`) | in (reconcile) |
| purchase orders | `API_PURCHASEORDER_PROCESS_SRV` (incl. schedule lines) | in |
| demand orders | `API_SALES_ORDER_SRV` (items + schedule lines) | in |
| demand history | `API_BILLING_DOCUMENT_SRV` or flat extract file (`demand_history` sheet) | in |
| planned orders / PRs | `API_PLANNED_ORDERS`, `API_PURCHASEREQ_PROCESS_SRV` | out |
| forecast (optional) | `API_PLND_INDEP_RQMT_SRV` (PIRs from the active version) | out |
| production confirmations, goods movements | `API_PROD_ORDER_CONFIRMATION_2_SRV`, `API_MATERIAL_DOCUMENT_SRV` | out |
| QM usage decision (optional) | `API_INSPECTIONLOT_SRV` | in/out per M7 SoR |

- `inbound` maps OData JSON (v2 `d.results` and v4 `value`) to `superplanner.v1` batches; `outbound` maps v1 events
  to POST deliveries (CSRF token fetch `x-csrf-token: fetch`, then POST; M5 4.6 retry/order).
- `sap_sync` job (per entity, schedule in `int_settings.sap.schedule`): GET with `$filter=LastChangeDateTime gt
  <cursor>`, paging by `__next` / `@odata.nextLink`, cursor stored after each committed chunk; auth basic or OAuth2
  client credentials (secrets encrypted, M5). `INTEGRATION_ALLOW_PRIVATE_TARGETS` applies.
- Mapping profile `int_settings.sap`: base_url, plant (WERKS), storage location -> location map, MRP controller
  filter, ISO unit map (`PCE->EA`, `KGM->KG`, `MTR->M`, `LTR->L`), material number zero-strip, order types.
- Tests: recorded payloads in `integration/sap/fixtures/` (fictional, shaped like S/4HANA 2023 responses) and a fake
  OData server (httpx MockTransport) for paging, CSRF and errors; round trip = in -> plan -> out -> reconcile.

## 10. Validation kit v1 (`validation/`)

- **Register** `docs/validation/requirements.yaml`: `[{id, title, source ("M8-DESIGN 7.2"), risk (high|medium|low),
  assurance (scripted|unscripted|ad_hoc), intended_use (gxp|non_gxp)}]`. M8 adds its test-vector IDs (14.3) and
  back-fills M7 Part 11/quality (from M7 12 test vectors, `M7-ESIG-nn`, `M7-QA-nn`). CSA rule: high = feature
  directly affects product quality/patient safety or record integrity -> scripted test required.
- **Markers**: pytest `@pytest.mark.req("M8-RATE-03")` (registered marker, multiple allowed); Playwright titles
  carry `@req:M8-FC-02`.
- `manage.py trace-matrix [--junit file.xml ...] [--out dir]`: AST scan of `backend/tests` and regex scan of
  `frontend/e2e` -> requirement x test, merged with JUnit results; outputs `trace-matrix.csv` and `.html` (per
  requirement: tests, last result, risk, gaps). Exit 1 when a `high` requirement has no test.
- **Configuration baseline**: `manage.py config-baseline --plant CODE` and `POST /mfg/validation/baselines`: app
  version, git sha, migration head, plant + planning + qa settings, esig policies, role -> permission matrix,
  integration settings (secrets redacted), job schedules; canonical JSON sha256; stored in `val_baselines`;
  `GET /mfg/validation/baselines/{a}/diff/{b}` lists changed paths.

## 11. API (`/api/v1/mfg`, `router_m8.py`; route table at S0)

| # | Method and path | Perm |
|---|---|---|
| F1-F3 | GET `/forecast/history?item_id&bucket`; PUT `/forecast/history/{id}` (cleaned_qty reset/override, reason); POST `/forecast/history/refresh` | view / forecast_edit |
| F4-F6 | GET, POST `/forecast/runs`; GET `/forecast/runs/{id}` (summary + per-item results, paged) | view / forecast_edit |
| F7-F12 | GET, POST `/forecast/versions` (from run, copy overrides); GET `/{id}`; GET `/{id}/lines?item_id&family&abc&page`; POST `/{id}/activate`; DELETE `/{id}` (draft) | view / forecast_edit (activate: forecast_approve) |
| F13-F15 | GET, POST `/forecast/versions/{id}/overrides`; DELETE `/forecast/overrides/{id}` (reason header) | view / forecast_edit |
| F16-F17 | GET `/forecast/items/{item_id}` (history, fitted, versions, consumption, method, accuracy); GET `/forecast/accuracy?lag&group_by` | view |
| I1-I4 | GET, POST `/invopt/runs`; GET `/invopt/runs/{id}/lines`; POST `/invopt/runs/{id}/decide {line_ids, decision, reason}` | view / inventory_policy_edit (decide: inventory_policy_approve) |
| I5-I7 | GET, PUT `/items/{id}/planning`; GET, PUT `/items/{id}/packaging` (levels inline) | view / master edit |
| R1-R3 | GET, PUT `/lines/{id}/rates`; GET, PUT `/changeover-matrix` | view / master edit |
| R4-R9 | GET, POST `/rate/runs`; GET `/rate/runs/{id}` (summary, objective, explanations, validator); GET `/{id}/blocks?line_id&from&to`; GET `/{id}/grid?bucket=shift\|day` (line x bucket x item x qty); POST `/{id}/publish`; GET `/rate/compare?a&b` | view / rate_plan |
| S1-S7 | POST `/ster/plan`; GET `/ster/loads?status&from&to`; GET `/{id}`; POST `/{id}/load`, `/advance {to}`, `/release` (signed), `/fail {reason}` | view / ster_plan (release: ster_release; fail: qa_decide) |
| K1-K6 | GET, POST `/kanban/loops`; GET, PUT `/{id}`; GET `/{id}/cards` (print sheet); POST `/kanban/scan {code}` | view / kanban_edit (scan: kanban_scan) |
| N1-N2 | GET, PUT `/plant/planning-settings`; POST `/planning/nightly/run-now` | view / plant_admin / rate_plan |
| V1-V4 | GET `/validation/trace-matrix` (latest generated file); GET, POST `/validation/baselines`; GET `/validation/baselines/{a}/diff/{b}` | validation_view / plant_admin |
| X1-X2 | GET, PUT `/integration/sap-settings`; POST `/integration/sap/sync {entities}` | integration_admin |

Permissions -> roles: planner: `forecast_edit`, `inventory_policy_edit`, `rate_plan`, `ster_plan`, `kanban_edit`;
plant_manager: + `forecast_approve`, `inventory_policy_approve`; qa_approver: `ster_release`, `validation_view`;
operator: `kanban_scan`; auditor: `validation_view`. MRP endpoints unchanged except params/new kinds.

## 12. UI (UX standard; strings `lib/strings/planning.ts` + fr-CA)

| Route | Screen |
|---|---|
| `/mfg/forecast` | Workbench: version picker, filters (family, ABC/XYZ, method, flags), item list with WAPE/bias badges; item panel = chart (history, cleaned, fitted, stat, final, orders consumed) reusing `ProjectedStockChart`-style SVG + finance `LineChart`; period grid with editable override cells (reason prompt), family % override dialog; run + activate actions |
| `/mfg/forecast/accuracy` | Lag-1/lag-3 WAPE and bias by family/ABC, backtest of the latest run |
| `/mfg/invopt` | Proposal table (class, SL, current -> proposed SS, delta value, cover days), ABC/XYZ 3x3 matrix count/value, bulk approve with reason |
| `/mfg/rate` | Run list; run-rate grid (lines x days, cells = item colour + qty in cases, utilisation bar); campaign Gantt per line reusing the M3 Gantt (production/changeover/cleaning colours); shortages with explanations; compare two runs; publish |
| `/mfg/sterilisation` | Chamber timeline (loads, cycle + aeration), aeration utilisation chart, awaiting-release list with planned dates, release (SignatureDialog) and fail |
| `/mfg/kanban` | Loops, card states, sizing suggestion, printable card sheet (QR of `KB:` code); floor scanner accepts `KB:` |
| item editor tabs | Planning (replenishment, campaign, ster), Packaging levels |
| `/mfg/validation` | Trace-matrix download + gap counts, baselines list and diff |
| integration console | SAP settings card, sync now, last cursor per entity (extends M5 console) |

MRP item view shows forecast requirements (label "Forecast Mar 2027"), packs (`12 cases / 0.5 pallet`) and rate/
kanban supplies. Dashboard tiles: forecast accuracy (lag 1), rate plan shortages, loads awaiting release.

## 13. Delivery plan (lean)

| WP | Role | Owns |
|---|---|---|
| **S** backend | one backend developer | `mfg/{forecast,invopt,rate,ster}/**`, `mfg/kanban.py`, MRP edits, `integration/adapters/sap_s4.py`, `integration/sap/**`, `validation/**`, `api/mfg/{db_models_m8,repo_m8,router_m8}.py`, `services/{forecast,invopt,rate,ster,kanban,valid}.py`, hooks in 13.1, jobs, migration `0011_m8`, `migrate.py`, `manage.py trace-matrix|config-baseline|load-seed`, sample `meddev_m8`, `scripts/load/**`, `docs/validation/requirements.yaml`, DEPLOY (nightly chain, SAP setup), tests `tests/{forecast,invopt,rate,ster,sap,validation,api_mfg_m8}/**` |
| **U** UI | one UI developer | `frontend/src/mfg/{forecast,invopt,rate,ster,kanban,validation}/**`, item editor tabs, integration console card, dashboard tiles, strings + fr-CA keys, `frontend/e2e/m8-planning.spec.ts` (one spec, `@req` tags) |
| LEAD | team lead | this document, S0 review, load test run, final gate |

**S0 (day 1-2)**: pydantic contracts (`forecast/model.py`, `invopt/model.py`, `rate/model.py`, `ster/model.py`,
MRP param/kind additions), migration + up/down test, all routes live with permissions answering from
`api/mfg/fixtures/example_m8.json` (built and validated by `build_example.py`, M7 14 pattern); U writes
`contractExamplesM8.ts`. **S1 (5 d)** history, methods, selection, versions, overrides, consumption, accuracy.
**S2 (5 d)** ABC/XYZ + SS proposals; MRP forecast requirements, zones, packaging, kanban (incl. scan/signals), rate
supply kinds. **S3 (7 d)** rate engine: build, construction, CP-SAT improvement, validator, explanations, publish,
nightly chain. **S4 (3 d)** sterilisation plan, loads/holds/release/fail, trace edge. **S5 (5 d)** SAP adapter + sync
+ fixtures; validation kit; load seed and k6 scripts; `meddev_m8`; performance. **U1** forecast workbench +
accuracy. **U2** invopt, item planning/packaging tabs, kanban. **U3** rate grid, Gantt, compare, publish. **U4**
sterilisation, SAP card, validation page, dashboard tiles, fr-CA keys, e2e spec.

### 13.1 Existing code and tests touched
M2 MRP model/engine/lotsize/views/snapshot loader (forecast requirements, `kanban`/`rate` supplies, pack multiples,
new exceptions), demand-type filters; M1 items/lines models and import sheets (`item_planning`, `item_packaging`,
`line_rates`, `changeover_matrix`, `demand_history`), health registry (`MFG_RATE_NO_RATE`, `MFG_PACK_INVALID`,
`MFG_STER_NO_CHAMBER`); M3 APS snapshot (skip `flow`/`sterilisation` lines and `repetitive` WOs on them); M4 scan
codes (`KB:`), batch loads (link from ster load), WO kinds; M5 adapter registry, trace edge kinds, int settings; M7
hold sources, esig policy defaults (`ster_load.release`), NCR creation hook; route/permission tables and authz
sweep, migration head/table sets, job-kind lists, retention, reset/reassign registries, sample registry. Existing
tests change only in those tables and in MRP golden outputs where new exception codes appear (none for M2 samples).

## 14. Sample, performance, load test, testing, acceptance

### 14.1 Sample `meddev_m8.py` (no change to M1-M7 content or health expectations)
Flow lines: moulding presses, ASM-01..04, PKG-01..02 (`planning flow`, rates per family, OEE 0.80-0.88); ETO-01..02
`sterilisation` (24 pallets, 14 h cycle), group `AER` with 96 pallet positions; changeover matrix on assembly by
`campaign_key` (gauge/size: same 30 min, size change 90 min, syringe <-> needle 240 min cleaning + 45 min
clearance); cleaning every 72 h (120 min) on cleanroom lines. Packaging levels on all finished items (each, inner
100, case 1,000-2,000, pallet 40-60 cases). 30 months of monthly history for finished items built by a seeded
generator: trend, 12-month seasonality (flu season peak for syringes/needles), two intermittent SKUs (Croston),
one new item with `like_item_id`, two outliers. Forecast run + active version with 3 overrides; SS run with
pending proposals; one published rate run (30 days); planned loads with one awaiting release; two kanban loops
(tip caps `buy`, roller clamps `buy`, one empty card). SAP fixtures map to the same items.

### 14.2 Performance and load targets
Bench (local PostgreSQL 16, developer machine as M7 12) on the **BD-like seed** (`manage.py load-seed --profile bd`):
40 flow lines + 6 chambers, 3,000 SKUs (1,800 finished, 1,200 components/raw), 5M units/day, 24 months history,
6,000 open order lines, 26-week forecast, 300 users.

| # | Case | Target |
|---|---|---|
| P1 | forecast run 3,000 items x 30 months, all candidates + selection | < 60 s, < 1.5 GB RSS |
| P2 | consumption + MRP pass with forecasts, 3,000 items, 180 days | < 90 s |
| P3 | SS run 3,000 items | < 10 s |
| P4 | rate run 40 lines x 30 days, validator-clean (Gate) | < 5 min (construction alone < 30 s) |
| P5 | ster plan 30 days, 6 chambers | < 10 s |
| P6 | nightly chain end to end | < 20 min |
| P7 | forecast workbench item panel / grid page of 100 items | p95 < 300 ms / < 500 ms |
| P8 | rate grid 40 lines x 30 days | < 800 ms |
| P9 | SAP inbound 50,000 product records (chunks of 2,000) | < 10 min |
| L1 | k6: 300 virtual users, read-heavy mix (dashboards, MRP item, rate grid, forecast item, lists), 30 min | p95 < 800 ms, errors < 0.1 % |
| L2 | k6: 2,000 floor events/h (start/complete/report/scan) concurrent with L1 | p95 < 300 ms |
| L3 | nightly chain while L1 runs at 50 users | P6 holds; API p95 < 1.5 s |

`scripts/load/README.md` documents how to run (k6 binary, seed, env, report). The report (M8 Gate) records machine,
data size and results; the BD-scale sign-off on production-class hardware is M10.

### 14.3 Test vectors = M8 requirement register (`@pytest.mark.req`)
| ID | Case | Expected |
|---|---|---|
| M8-FC-01 | series with 12-month season + trend, 36 months | HW chosen; holdout WAPE < 0.15 |
| M8-FC-02 | intermittent series (ADI 2.5) | Croston/SBA/MA only; SBA (alpha 0.1) = 0.95 x z/p |
| M8-FC-03 | 2 periods history | zero stat, `FC_HISTORY_SHORT` |
| M8-FC-04 | outlier 10x median | clipped, flagged; planner reset restores |
| M8-FC-05 | override family +10 % then item abs 5,000 | family items x1.1; item = 5,000; audit old/new + reason |
| M8-FC-06 | activate while another active | previous archived; MRP uses new |
| M8-FC-07 | forecast 3,000/month, order 1,000 due day 10 | daily spread; order consumes backward; requirement total 3,000 |
| M8-FC-08 | order 5,000 > forecast in window | over-consumption info; requirement = 5,000 |
| M8-FC-09 | lag-1 accuracy | uses version active before period start, not the latest |
| M8-SS-01 | d 1,000/day, sigma_d 200, LT 10, sigma_LT 2, SL .98 | SS = 2.054 x sqrt(10 x 200^2 + 1000^2 x 2^2) = 4,308 -> case 1,000 -> 5,000 |
| M8-SS-02 | ABC/XYZ cutoffs on 10 items | classes as hand table |
| M8-SS-03 | approve proposal | item SS updated, audit reason `SSP-...` |
| M8-MRP-01 | forecast + orders + SS, daily/weekly/monthly zones | requirement dates as zones; ranks order > forecast > SS |
| M8-MRP-02 | case 1,000, need 2,300 | planned 3,000; `MRP_PACK_ROUNDING` |
| M8-MRP-03 | kanban item with residual | no planned order; components exploded; undersized warning when 3 cards too few |
| M8-MRP-04 | pass 2 with published rate run | rate supplies replace planned orders; shortfall -> `MRP_RATE_SHORT` |
| M8-KB-01 | scan empty card `buy` / receipt | PR line container qty / card full |
| M8-RATE-01 | 1 line, 3 items, matrix | sequence minimises changeover; changeover blocks match matrix |
| M8-RATE-02 | demand > capacity | shortage with `RATE_CAPACITY`, load % |
| M8-RATE-03 | min campaign 8 h, small demand | campaign 8 h, excess cover reported |
| M8-RATE-04 | cleaning every 72 h | cleaning block inserted, validator ok |
| M8-RATE-05 | validator mutation tests (overlap, missing changeover, qty > rate) | each detected |
| M8-RATE-06 | publish twice with changes | firm WOs created/cancelled as rule; started WOs untouched |
| M8-STER-01 | 30 pallets, chamber 24 | 2 loads; aeration full -> second load delayed `STER_AERATION_BOUND` |
| M8-STER-02 | cycle complete -> release signed | `sterility` holds with planned date; release lifts; MRP avail = release date |
| M8-STER-03 | load fails | holds kept, one NCR with all lots; trace shows co-sterilised lots |
| M8-SAP-01 | recorded payloads v2 + v4, paging, CSRF | v1 batches equal golden; deliveries POST with token |
| M8-SAP-02 | round trip in -> MRP -> planned orders out -> stock reconcile | reconciliation clean |
| M8-VAL-01 | trace matrix on repo | CSV/HTML; high-risk gap -> exit 1 |
| M8-VAL-02 | baseline twice with a policy change | diff shows the path; hashes differ |

### 14.4 Testing during work
Tests with the code; only touched packages (`.venv/bin/pytest tests/forecast -q`, `tests/rate -q`, ..., named MRP
tests). Rate and forecast performance tests marked `slow`. UI: `npm run build`, `npm run i18n:check`, the m8 spec.
**Final gate (once, LEAD):** full backend suite on PostgreSQL incl. `-m slow`; `m8-planning.spec.ts`,
`mfg-m2-mrp.spec.ts`, `m3-schedule.spec.ts`; migration 0010 -> 0011 on a populated database and downgrade;
`trace-matrix` run; load test L1-L3 report.

### 14.5 Acceptance (Gate 8)
1. Forecast accuracy report on the `meddev_m8` and BD-like seed histories: backtest WAPE per ABC class (A <= 0.25 on
   the seeded series), method mix, lag-1 tracking; overrides audited.
2. MRP with forecasts + consumption + kanban + packaging matches the hand cases M8-MRP-01..04 and M8-SS-01.
3. Rate plan for 40 lines x 30 days validator-clean in < 5 min; publish creates repetitive WOs executed on the M4
   floor; EtO loads with aeration and signed release on the sample.
4. SAP round trip on recorded payloads (M8-SAP-01/02).
5. Trace matrix and configuration baseline produced from the repo; no high-risk M7/M8 requirement without a test.
6. Load test report L1-L3 and P1-P9; full backend suite green once; m8 spec green.

### 14.6 What the demo video can show after M8 (new scenes after storyboard 10)
11. Forecast workbench: flu-season syringe history, Holt-Winters chosen by holdout, planner overrides a family +8 %
    with a reason. 12. ABC/XYZ matrix and safety-stock proposals approved in bulk. 13. MRP item: orders consuming
    forecast, quantities in cases/pallets, kanban loop for tip caps. 14. Rate grid for assembly and packaging lines
    with campaigns, cleaning and changeovers; a shortage explained by capacity; publish -> WOs on the floor tablet.
    15. EtO chamber timeline with aeration and a signed sterility release. 16. SAP settings and a sync log; trace
    matrix download. Coverage after M8: 22 of 31 expectations (gap plan 2).

## 15. Questions and implementation notes

No blocking questions. Defaults decided by LEAD 2026-11-25 (all per-plant configurable): monthly forecast grain;
history basis shipments; consumption 30/30 days; SS service matrix 4.6; firm zone 3 days with one repetitive WO per
line-item-day (= lot per day); auto-publish off; EtO release by `qa_approver` signature; SAP via OData pull +
POST (middleware alternative documented). To confirm with BD when available (does not block build): whether BD's
plant lot definition is per shift (switch `rate_wo_split`), BI vs parametric release, and which SAP APIs are
released in their tenant (adapter maps one entity per module, so a missing API is a mapping profile change).

Implementation notes: (S0 and later phases append here.)

**S0 frozen (2026-11-25).** Contract: `backend/superplanner/mfg/forecast/model.py`, `mfg/invopt/model.py`,
`mfg/rate/model.py`, `mfg/ster/model.py`, `mfg/model_m8.py` (shared: planning settings, item planning, packaging,
line rates, changeover matrix, kanban, SAP settings, validation baselines) and the MRP additions in
`mfg/mrp/model.py` (`MrpParams.forecast_version_id | rate_supply | rate_run_id`, requirement kind `forecast`,
supply kinds `kanban`, `rate`). Typed examples `backend/superplanner/api/mfg/fixtures/example_m8.json` (built and
validated by `build_example.py`, test `tests/api_mfg_m8/test_m8_s0_contract.py`); migration `0011_m8`
(`migrate.HEAD`, ORM == schema by `compare_metadata`); all 61 M8 operations live with their permissions
(`router_m8.py`, route table `tests/auth/route_table.py` `MFG_PERMISSIONS_M8`). Until a service function is
implemented it answers from the example file (`services/m8_examples.py`, PEP 562 fallback per service module).

S0 interpretations and deviations:
- ID prefixes are three letters so ids match `EntityId` (`^[a-z]{3}_[0-9a-f]{32}$`): `dhi_` (history), `ipn_` (item
  planning), `rrn_` (rate run), `rbk_` (rate block), `stl_` (ster load), `slm_` (load member), `vbl_` (baseline);
  the others as designed.
- Roles: there was no `plant_manager` or `auditor` role; both are added (`plant_manager` = planner + `forecast_approve`,
  `inventory_policy_approve`; `auditor` = view, floor_view, trace_view, audit_view, validation_view, assistant_use;
  M6 rule "every plant role except operator has assistant_use" kept). "plant_admin" permissions of 11 (N1 PUT, V2
  POST) map to the `owner` permission (held by owner and plant_admin). `qa_approver` also gets `validation_view`.
  UI: role pickers need the two new roles.
- `mfg_demand_history` unique key includes `source` (one row per source per item-period; precedence import > sap >
  ledger applied on read), so a ledger refresh never overwrites imported history. Extra column `manual_qty`
  (planner-set cleaned value).
- Extra columns: `mfg_forecast_runs.first_period, results, error`; `mfg_forecast_versions.archived_at`;
  `mfg_ss_runs.error, actor_id, finished_at`; `mfg_ss_lines.flags`; `mfg_rate_runs.label, shortages, error,
  actor_id, finished_at`; `mfg_ster_loads.aeration_line_id, flags`; `mfg_kanban_loops.consumed` (consumption
  counter); `mfg_work_orders.kind` widened to String(12) (`repetitive`); `int_settings.sap` JSON (SAP profile,
  encrypted secrets, cursors, last sync).
- All M8 job kinds are duty runs on `maintenance_runs` (`services/m8jobs.py`), so `ck_jobs_one_target` is unchanged.
- Extra routes: `GET /invopt/runs/{id}`, `GET /validation/baselines/{id}`; `GET /validation/trace-matrix?format=
  json|csv|html`. Item planning/packaging, line rates, changeover matrix, planning settings and the nightly chain are
  served by `services/planning.py`; SAP settings/sync by `services/sap.py`.
- `ster_load.release` is an M7 default policy (qa_approver, `approved`, password) and is always signed (also
  outside Part 11 mode), record type `ster_load`.

S1 notes (forecasting, as built):
- `mfg/forecast/{history,methods,select,consume,overrides,accuracy}.py` (pure, numpy). Selection groups items by
  series length so every model runs vectorised; measured P1 (selection, 3,000 items x 30 months, all candidates):
  1.2 s, 65 MB RSS.
- Holt-Winters is undamped (alpha x beta x gamma grid); Holt damped uses alpha x beta x phi. MA compares grid points
  by mean (not total) squared one-step error, as the number of fitted points differs per window. When the holdout
  has no demand, candidates rank by absolute error and WAPE/bias are reported as null.
- Outlier cleaning: MAD = 0 (constant series with a spike) falls back to the scaled mean absolute deviation;
  intermittent series (> 30 % zeros) use non-zero statistics and only clip large values. The cleaned value is
  stored on every source row of the item-period by the refresh; a planner value (`manual_qty`) wins.
  `PUT /forecast/history/{id}` with `cleaned_qty: null` restores the raw value (no clipping) - that is "reset".
- History refresh recomputes the `ledger` rows of the bucket from all `ship` transactions (or customer demand
  lines by due date) with one grouped query; ledger rows whose postings are gone are deleted unless the planner set a
  value. Imports/SAP rows are never touched except for their cleaned value.
- ABC in a forecast run: 12 periods of forecast (else history) x standard cost (missing -> volume, `FC_NO_COST`);
  cumulative share including the item; the top item is always A. Run summary weights WAPE/bias by mean volume.
- Version numbers use their own series `FCV-000001` (runs `FC-000001`). A run creates a draft version named
  "<run> statistical" and copies the active version's overrides that still overlap the horizon.
- Overrides are allowed on drafts only (409 `FC_VERSION_LOCKED`), each change re-applies all overrides of the
  affected items (family overrides: the whole family) and bumps the version's `row_version` (If-Match of
  activate). Removal reason comes from `X-SP-Change-Reason` (422 without). Audit rows carry `reason` and the
  old/new values in `details.changes` (the common `audit()` gained an optional `reason`).
- Accuracy lag: any 1..12 is accepted (UI uses 1 and 3); computed on read (no per-period cache yet).

S2 notes (inventory optimisation, MRP, kanban; as built):
- `mfg/invopt/safety.py`: Acklam inverse normal; proposal = round up to the order pack, then capped at
  `ss_max_cover_days` x d (largest pack multiple within the cap, `SS_CAPPED`). d = forecast of the next 90 calendar
  days / working days in them (items without forecast: last 12 periods of history); sigma_d = rmse1 / sqrt(average
  working days per period of the next 12 periods); sigma_LT from `po_receipt` transactions vs schedule confirmed
  (else requested) date, calendar days. An SS run writes `abc`/`xyz` to item planning (created when missing).
- MRP (`mfg/mrp`): `MrpSnapshot` gained `forecasts`, `planning` (`PlanningSnap`), `rate_supplies`
  (`RateSupplySnap`), `forecast_priority`, `zones`; all default empty, so M2-M7 runs and goldens are unchanged. The
  new params are left out of dumps at their defaults (canonical JSON unchanged) and the M8 exception codes appear in
  `summary.exceptions.by_code` only when they occur. Forecast rank `(1, forecast_priority, date, "~FORECAST", 0)`
  (after orders of the same priority and date, before safety stock). Rate supplies explode their components from
  the block's production day (they are make supplies), kanban pseudo supplies explode from need date minus the loop
  lead time; neither creates planned orders or action messages. `MRP_RATE_SHORT` is `critical` (the severity scale
  has no "error"). Supply sort order: stock, inspection, po, pr, wo, rate, planned, kanban.
- MRP service: `services/m8mrp.add_inputs` adds the M8 inputs after the snapshot load; a bad
  `forecast_version_id` / `rate_run_id` drops the run with 422 `MFG_UNKNOWN_REFERENCE`.
- Kanban: a scan empties a full card (409 `KANBAN_CARD_STATE` otherwise) and creates a submitted PR (source
  `kanban`) or a planned WO `kind kanban`; receipts (PO / WO / misc / transfer) of the item at the loop location
  refill the oldest non-full cards (one per container received, at least one) - matched by item and location, not
  by document. Consumption trigger counts issues at the loop location (`mfg_kanban_loops.consumed`). Hook:
  `inventory.post_in_session`. Floor scan resolves `KB:<card id>` (type `kanban_card`). Loop sizing uses the latest
  live MRP run's gross requirement / horizon days.

S3 notes (rate engine, as built):
- `mfg/rate/{construct,improve,validator,explain,engine,build,publish}.py`; `engine.py` (orchestration: assignment,
  per-line construction + improvement in a spawn process pool of `RATE_WORKERS`, validator, objective,
  explanations) is an extra module. The validator is independent code (own matrix lookup and arithmetic).
- Blocks never cross a window end or plant-local midnight (one `prod_date` per block); a campaign may span several
  blocks (same `campaign_no`). Setup blocks between two items: matrix `changeover` and `cleaning` rows (most
  specific per kind; wildcards only between different keys) plus clearance = max(matrix clearance row, line
  `clearance_minutes`). A matrix cleaning resets the periodic-cleaning counter only if it is at least
  `clean_minutes` long. Campaigns cut by the horizon end keep whole cases and are exempt from the minimum.
- Improvement: CP-SAT re-sequences the constructed campaigns (quantities fixed) per rolling 7-day window (<= 30
  campaigns): `AddCircuit` with a depot node (previous / next item), setup minutes and costs from the matrix, same-item
  order kept, lateness vs run-out as unit-minute penalty (weights shortage 1000 : cost 10); the candidate is laid out
  through the real windows and accepted only if the exact lexicographic objective improves and the validator is
  clean; up to 3 rounds within the budget. Quantities are not re-optimised by CP-SAT (the construction sizes them).
- Objective at daily resolution: production counts on the plant date its block ends; shortage unit-days = summed
  daily backlog (weighted by demand priority for comparison, reported unweighted); excess cover = stock beyond the
  next `target_cover_days` of demand; overtime cost = hours in `optional` windows x half the line cost per hour.
- Build: pass-1 demand = planned orders of rate items in the latest live MRP run with `rate_supply false` (else
  the latest live run); they are net of stock and existing WOs, so initial stock is 0 and firm blocks (already
  WOs) add no supply (`RateProblem.firm_netted`, additive contract field). `RATE_MATERIAL_SHORT`: components short
  in the pass-1 run get availability = as_of + their lead time (earliest new supply); earlier blocks are warned.
- Publish: one run published at a time (the previous one is unpublished); WOs `kind repetitive`, status released,
  `source rate`, operations derived and the operation of the line's group pinned to the block line; previous
  repetitive WOs due in the firm zone: matching (item, due, qty) unstarted WOs are kept and re-linked, others
  cancelled, started ones kept. 409 `RATE_NOT_PUBLISHABLE` for non-completed / validator-failed runs.
- APS: flow / sterilisation lines and open repetitive WOs are removed from the APS snapshot (`repo_m3`).
- Nightly chain (`services/nightly.py`) runs all steps in one `nightly_plan` duty run (step results in its
  `results.steps`); the scheduler enqueues it per plant when `planning_settings.nightly_enabled` (new setting,
  default false) and the local time passed `nightly_at`; 409 `PLANNING_CHAIN_RUNNING` for a second start.
- Measured P4 (synthetic 40 lines x 15 items x 30 days, 4 workers, 60 s budget): construction 0.2 s, full run
  61 s, validator clean.

S4 notes (sterilisation, as built):
- `mfg/ster/loads.py` (greedy planner) and `mfg/ster/validator.py` (independent: capacity, cycle code, duration,
  ready time, chamber overlap incl. loads in work, aeration positions over time). Aeration rooms are assigned per
  load (one room); a candidate larger than every chamber is split into chamber-sized parts.
- Candidates include completed WOs (sterilisation follows packaging, so the usual candidate is a finished WO with
  received lots; ready = completion time) besides open WOs and unconverted published rate blocks; WOs already in a
  load past `planned` (or released / failed loads) are not planned again. Re-planning replaces `planned` loads only.
- Lots: a member's lots are its WO's `wo_receipt` lots (when the member has no lot). Holds `source sterility`
  (`source_id` = load, `planned_release`) are placed at cycle complete (`advance to aerating`, or `fail` during the
  cycle); they are owned by the load (`POST /qa/holds/{id}/release` answers 409 `QA_HOLD_OWNED`). The planned
  release is recomputed from the actual cycle end. `HoldRecord.planned_release` added (optional).
- Load flow adds `cycling|aerating -> failed`; `fail` opens one critical NCR (draft, first lot as `lot_id`, all lot
  codes in the description) and keeps the holds.
- Trace: edges lot -> `ster_load` -> lot (precision exact) at cycle complete, so forward traces / recalls show the
  co-sterilised lots.
- MRP: WOs in a planned or running load are available at the load's `release_due` (their due date in the snapshot
  is moved), rate blocks in a load likewise (`m8mrp`).
- Nightly chain: the sterilisation step is skipped (`ref_id "skipped"`) when the plant has no chamber.

**WP-U (UI, U1-U4) notes.** Screens: `/mfg/forecast` (+ `/accuracy`), `/mfg/invopt`, `/mfg/rate` (+ `/runs/:id/
grid|gantt|shortages|compare`), `/mfg/sterilisation`, `/mfg/kanban` (+ print sheet `/mfg/print/kanban/:loopId`),
`/mfg/validation`, item tabs Planning and Packaging, SAP card on the integration overview, floor scanner `KB:` codes
(`POST /kanban/scan`), MRP item view (requirement kind `forecast`, supply kinds `kanban`/`rate`, optional `packs`,
new exception labels). Types `frontend/src/mfg/api/typesM8.ts` mirror the S0 models; `contractExamplesM8.ts` is the
fixture typed against them. Strings `lib/strings/planning.ts` + `fr-CA/planning.ts` (`plan.*`). E2E
`frontend/e2e/m8-planning.spec.ts` (4 tests, `@req` tags). Roles `plant_manager` and `auditor` added to the role
pickers and permission tooltips.
- Forecast lines (F10) carry no item name, WAPE, bias or flags; the item list therefore shows part number, family,
  class, method, next-3-period total and the override effect (final vs statistical), and the item panel shows WAPE,
  bias, flags and lag accuracy from F16. Filters offered are those F10 supports (search, family, ABC). Optional
  additive fields `name`, `holdout_wape`, `bias`, `flags` on F10 lines would let the list show the accuracy badges.
- F16 has no overrides; the panel reads F13 (version overrides) and keeps those of the item or its family.
- Accuracy (F17) has no per-period trend; the page shows WAPE bars per group (worst first), the overall figure from
  `group_by=all`, and the backtest summary; a `periods` selector (3/6/12) is passed through.
- Rate shortages carry only `item_id`; item names come from the item cache. The rate Gantt reuses the M3 `ProdGantt`:
  a production block preceded by a changeover becomes one bar whose striped start is the changeover; cleaning /
  clearance are hatched bands, `down` is the downtime band; firm blocks (with a WO) draw as frozen ("F").
- Aeration capacity is not in the API; the sterilisation page charts pallets in aeration over time with the peak.
  Loads are read from a week back in pages of 200 (`PAGE_MAX`).
- Dashboard tile names are ready for `forecast_accuracy`, `rate_shortages`, `ster_release` (values from the M6 tile
  API once the backend adds them).

S5 notes (SAP, UI contract additions, sample; as built):
- SAP: `integration/sap/odata.py` (httpx client: v2/v4 paging, basic / OAuth2, CSRF fetch + one retry on 403
  `Required`), `integration/sap/mapping.py` (pure OData -> v1 per entity, outbound planned order / PR bodies),
  `integration/adapters/sap_s4.py` (registered; `int_settings.adapter` accepts `sap_s4`). Sync = duty run `sap_sync`
  in `services/sap.py`: inbound entities go through the M5 `process` path (SoR and value maps apply); extras
  (packaging levels from units of measure, monthly `sap` demand history from billing items) are applied directly;
  the cursor is saved after each page; `planned_order_out` posts the open planned orders of the latest live MRP run
  once per run. Saving SAP settings with `enabled` switches the plant integration on with adapter `sap_s4`.
  Planning fields (lead times) from SAP apply only when the item SoR is `shared` (M5 4.4 rule unchanged).
  Fixtures and `golden_v1.json` in `integration/sap/fixtures` (fictional); fake server `tests/sap/sap_fake.py`.
- UI contract gaps closed (additive): F10 lines carry `name`, `holdout_wape`, `bias`, `flags` (latest run of the
  version); F17 returns `trend` (per closed period: actual, lag forecast, WAPE, bias; all items); `GET /ster/loads`
  returns `chambers` and `aeration {positions, rooms}`; the plant dashboard (D1) has tiles `forecast_accuracy`
  (lag-1 WAPE, 6-period trend; watch > 25 %, alert > 50 %), `rate_shortages` (published, else latest completed run)
  and `ster_release` (awaiting release; alert when overdue). The M8 tiles are not part of the organisation totals.
- Sample: `meddev_m8` (registered next to `meddev`, same M1-M7 content + the M8 layer) - deviation from "M8 data
  inside meddev": putting the existing ASM / ETO lines under rate / load planning would remove them from APS and the
  forecast would change the meddev MRP, breaking the M1-M7 sample expectations. The layer adds its own flow lines
  (`FLA-01/02`, `FLP-01`), planned chambers `EOS-01/02` and aeration room `AER-01`, history, forecast (active version
  with 3 overrides), SS proposals, kanban loops (tip caps, roller clamps; one empty card); after the load: MRP pass
  1, a published 30-day rate run, the sterilisation plan (one load awaiting release), MRP pass 2.
- Rate blocks carry whole units (cumulative rounding inside a campaign; campaign totals unchanged), so repetitive
  WOs of count items get integer quantities.

S5 notes (validation kit, load test, health):
- Register `docs/validation/requirements.yaml` is a list of YAML flow mappings, one per line, parsed without a YAML
  package (`validation/register.py`); optional `match` maps back-filled M7 requirements (`M7-ESIG-01..07`,
  `M7-QA-01..11`) to existing tests by test-name substring instead of editing M7 tests. Marker `req` is registered
  in `pyproject.toml`.
- `manage.py trace-matrix [--junit ...] [--out DIR] [--register FILE]` runs without a database; `GET
  /validation/trace-matrix` serves `ARCHIVE_DIR/validation/trace-matrix.json` when written with `--out` there, else a
  live scan (no results). `manage.py config-baseline --plant` accepts an organisation plant code, the integration
  plant code or the owner id. Baselines redact keys containing password / secret / token / `_enc`.
- Load test: `superplanner/loadseed.py` (+ `manage.py load-seed`, `scripts/load/seed.py`) builds the BD-like data
  through the sample import path (bundle -> `plan_import` -> `writer.apply`, replacing the plant's data) plus bulk
  M8 rows; k6 scripts L1-L3 and `scripts/load/README.md`. Timings: `pytest -m slow
  tests/api_mfg_m8/test_m8_perf.py -s`.
- Rate validator: the minimum campaign length is not enforced for a line's last campaign when the window time left
  before the horizon end could not have reached it (sound rule; replaces the earlier "ends at the last window").
- Health (`GET /health`): warnings `MFG_RATE_NO_RATE`, `MFG_PACK_INVALID`, `MFG_STER_NO_CHAMBER` from the M8 tables
  (added by the health service like the M7 QA codes; the pure M1 check is unchanged, so they never block MRP).
- Not done in M8 backend: import sheets `item_planning`, `item_packaging`, `line_rates`, `changeover_matrix`,
  `demand_history` (the APIs, SAP sync and the sample cover the data entry); the authorisation sweep
  (`acceptance_phase2b/test_acc_authz_sweep.py`) does not yet build M8 objects for its cross-plant IDOR checks (all
  M8 lookups go through the owner-filtered `repo.get_row`).
