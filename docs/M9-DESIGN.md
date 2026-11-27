# SuperPlanner M9 - Network, S&OP/IBP and sourcing (design + plan + acceptance)

Status: design for build, 27 November 2026. Milestone M9 of `docs/MEDDEV-GAP-PLAN.md` (size 1.1). Builds on M1-M8 as
built (`docs/M1-DESIGN.md` .. `docs/M8-DESIGN.md`, cited "M5 3.5" etc., incl. their implementation notes) and the
UX standard. Their conventions apply unchanged and are not restated (ids `^[a-z]{3}_[0-9a-f]{32}$`, `row_version` +
If-Match, error envelope, `owner_id` = one workspace, one permission per route, audit on every write, Part 11
reasons, outbox events, duty runs on `maintenance_runs`, immutable runs, independent validators, expand migrations).
Interpretations go to section 13 only.

Scope: a network of plants and distribution centres in one organisation; DRP with sourcing rules, quotas and transit
lanes that creates M5 transfer orders and pegs demand across plants; a monthly S&OP/IBP cycle (demand review,
supply review, financial view, scenario comparison, signed executive approval, publish to plants); capacity
expansion what-if with ramp-up and yield curves; make-vs-buy, supplier allocation and dual sourcing with a risk
score; country of origin (COO) and HTS per item, item-supplier and lot, domestic-content roll-up through genealogy,
tariff-milestone report; landed cost (price, freight, duty by HTS/COO, other, FX). Sample `meddev_m9` (an org).

## 0. Decisions

1. **The network is a workspace.** Each organisation gets at most one `network` workspace (a plant principal with
   `mfg_plant.kind = network`, code `NET`) that owns every org-level M9 record (lanes, sourcing, network runs, S&OP
   cycles, scenarios, tariff/FX tables, milestones, reports). M2 roles/permissions, M7 signature policies, number
   series, audit chain and Part 11 mode therefore apply unchanged. Plant data is read under `system_scope` limited
   to the org's plants; links into plant records are shown only to members of that plant.
2. **DC = plant of `kind dc`** (locations, stock, customer orders, forecasts, no lines). M8 `replenishment` gains
   `transfer`: plant MRP creates no planned orders for such items; the network run supplies them.
3. **Two grains, two engines, no new packages.** DRP (`mfg/network`): item x node x week, 26 weeks, deterministic
   low-level-code netting across the network with a rough-cut capacity pass; creates transfers and pegging. S&OP
   (`mfg/sop`): family x node x month, 18 months, an LP solved with OR-Tools GLOP (`pywraplp`, already used by
   `finance/optimizer.py`) in three lexicographic solves: unmet demand -> safety-stock shortfall -> cost. Capacity,
   lanes, ramp and supplier caps are hard constraints, never traded against cost; unmet demand is an explicit,
   reported variable (feasibility first).
4. **Items match across plants by key** = `external_ref`, else part number (M5 3.5). No network item master. A key
   with different UoM at two nodes is excluded (health warning `NET_UOM_MISMATCH`).
5. **DRP publish firms only the firm zone**: planned transfers shipping within `net_firm_days` (14) become M5 TOs
   (`source network`); later ones reach plant MRP as additive snapshot inputs (`network` demand at the source,
   `network` supply at the destination; the M8 `rate_supplies` pattern). Keep/cancel rule as M8 rate publish.
6. **S&OP cycle = record with fixed steps** `draft -> demand_review -> supply_review -> pre_sop -> executive ->
   approved -> published` (+ `cancelled`). Approval is always signed (also outside Part 11 mode), policy
   `sop_cycle.approve` = `reviewed: plant_manager` then `approved: executive`, distinct signers, password. After the
   first signature the cycle is frozen (409 `SOP_CYCLE_LOCKED`); reopen needs a reason and supersedes signatures.
7. **Publish of an approved cycle** (a) writes and activates per node a forecast version disaggregating consensus
   demand to items (M8 activate), (b) replaces the node's `mfg_mps_targets` (family x month qty + load hours), (c)
   lists the scenario's structural changes (new lines, rules, suppliers) as follow-ups - never applied
   automatically; master data stays planner-owned.
8. **Scenarios are typed change lists on the baseline network** (add line/node, capacity change, sourcing,
   make-vs-buy, supplier allocation, demand change, cost/tariff/FX change). Ramp-up and yield are piecewise-linear
   curves by week since start, folded into a monthly effective-capacity factor. Capex is reported, not optimised.
9. **COO is captured, not inferred, for bought lots** (receipt input > item-supplier > item; missing -> warning
   `TRADE_COO_MISSING`, never blocking); a made lot takes the plant country (substantial-transformation default).
   Domestic share of made lots is rolled up through M5 genealogy by value and weight, optionally restricted to
   material classes (e.g. `steel` for needles); `possible` edges use item defaults and mark the result `estimated`.
10. **Landed cost is one pure function** (`mfg/trade/landed.py`) used by item-supplier lists, make-vs-buy and the
    S&OP LP. Duty = sum of tariff layers (longest HTS prefix per layer, COO exact before `*`, effective-dated) on
    the customs value (FOB default, CIF per destination). FX monthly: direct, inverse, via USD; missing -> total
    `null` + `FX_MISSING`, never a silent 1. Only fictional example rates ship; the customer owns its tariff data.
11. **Lean delivery**: WP-S (one backend developer), WP-U (one UI developer), S0 contract freeze (days 1-2), targeted
    tests, one full suite at the end. Migration `0012_m9` (expand). No new Python or npm packages.

## 1. Scope and principles

Principles (beyond M1-M8): N1 feasibility first - hard constraints are constraints, shortfalls are explicit with a
cause; N2 the network proposes, plants execute - only firm-zone TOs and approved S&OP publishes write into plants,
audited there as `via network <run/cycle>`; N3 every engine output passes an independent validator before publish
or approval; N4 runs store input hash and parameters (reproducible).

**Out of M9 (deferred):** multi-echelon SS optimisation, stochastic S&OP, MILP lot sizing in S&OP (later);
automatic application of scenario changes (never); customs filing, rules-of-origin certificates, CUSMA
qualification, duty drawback (integrate); map view (node/lane diagram suffices); transport planning, warehouse
management (out of product); SAP IBP integration (on request); org-wide audit, data residency (M10).

## 2. Package layout (ownership in 11)

```
backend/superplanner/
  mfg/network/  model.py build.py (org snapshot, replica reads) capacity.py (rough-cut hours) engine.py validator.py
                peg.py publish.py
  mfg/sop/      model.py cycle.py demand.py (aggregate, overrides, disaggregation) curves.py scenario.py lp.py
                finance.py validator.py compare.py publish.py
  mfg/trade/    model.py landed.py fx.py content.py (lot roll-up, BOM share) milestones.py risk.py
  mfg/mrp/      (edits) network demands/supplies, `transfer` replenishment, MRP_NETWORK_SHORT
  api/mfg/      db_models_m9.py repo_m9.py router_m9.py services/{network,sop,trade,m9jobs}.py
  orgs/service.py (edits: network workspace, plant kind)   mfg/samples/meddev_m9.py   loadseed.py (`bd-network`)
frontend/src/mfg/{network,sop,trade}/**   frontend/src/lib/strings/network.ts (+ fr-CA)
```

## 3. Data (migration `0012_m9`, expand, additive; downgrade drops)

IDs: `nln_` lane, `nsr_` sourcing rule, `nrn_` net run, `npt_` transfer, `npp_` production, `nsh_` shortage, `npj_`
projection, `scy_` cycle, `sdm_` demand row, `sdo_` override, `ssc_` scenario, `rmp_` curve, `mps_` target, `itr_`
item trade, `trf_` tariff, `fxr_` FX, `tms_` milestone, `trp_` report, `ckr_` country risk. Numbers `NR-000001`,
`SOP-2027-01` (by period, unique per org), `SC-000001`, `TR-000001`. Owner "net" = network workspace.

| Table | Owner | Columns |
|---|---|---|
| `mfg_net_lanes` | net | from_owner_id, to_owner_id, mode S8 (`road`,`rail`,`sea`,`air`), transit_days Int, freight_per_unit Dbl (0), freight_per_kg Dbl N, currency S8, active; uq (from, to, mode) |
| `mfg_net_sourcing` | net | dest_owner_id, item_key S64 N, family S32 N (exactly one), source_kind S8 (`plant`,`supplier`), source_owner_id N, supplier_code S32 N, priority Int (1 = primary), quota_pct Dbl N, lane_id N, valid_from/valid_to Date N, active |
| `mfg_net_runs` | net | number, params JSON, status, as_of, input_hash S64, summary JSON (KPIs), validator JSON, explanations JSON, published Bool, published_at/by N, error, actor_id, started/finished, duration_ms |
| `mfg_net_transfers` | net | run_id FK CASCADE, src_owner_id, dst_owner_id, item_key, lane_id, ship_date, receive_date, qty, firm Bool, to_id N, pegs JSON; ix (run_id, dst_owner_id, item_key) |
| `mfg_net_production` | net | run_id FK CASCADE, node_owner_id, item_key, week Date, qty, kind S4 (`make`,`buy`), cap_group S32 N, hours, prebuilt_from Date N, pegs JSON |
| `mfg_net_shortages` | net | run_id FK CASCADE, node_owner_id, item_key, week, qty, cause S24 (`NET_CAPACITY_SHORT`,`NET_NO_SOURCE`,`NET_LEAD_TIME`,`NET_SUPPLIER_CAP`), detail JSON |
| `mfg_net_projection` | net | run_id FK CASCADE, node_owner_id, item_key, week, gross, receipts, planned_in, planned_out, projected, ss; uq |
| `mfg_sop_cycles` | net | number, period Date (1st of month), horizon_months Int (18), status S16, steps JSON `[{step, due, owner_id, done_at, done_by, note}]`, demand_sources JSON (node -> forecast version id), recommended_scenario_id N, recommend_note, approved_scenario_id N, content_hash S64 N, publish_result JSON N, reopen_reason S500 N |
| `mfg_sop_demand` | net | cycle_id FK CASCADE, node_owner_id, family, month, stat_qty, order_qty, base_qty, prior_consensus N, consensus_qty, asp Dbl N, asp_currency S8, asp_source S8 (`history`,`cost`,`manual`); uq (cycle, node, family, month) |
| `mfg_sop_demand_overrides` | net | cycle_id FK, node_owner_id N (null = all nodes), family, month_from, month_to, mode S4 (`abs`,`pct`), value, reason S500, seq, created_by/at, removed_at N |
| `mfg_sop_scenarios` | net | number, cycle_id N (null = template), name, changes JSON (`ScenarioChange[]`, 7), capex_note S2000, status S12 (`draft`,`running`,`completed`,`failed`), input_hash, result JSON, kpis JSON, validator JSON, error, run_at |
| `mfg_net_ramp_curves` | net | code S16 uq, name, points JSON `[{week, rate_pct, yield_pct}]` (week strictly ascending, pct 0..100) |
| `mfg_mps_targets` | plant | cycle_id S64, family, month, qty_target, hours JSON (cap_group -> hours); uq (owner_id, family, month) |
| `mfg_item_trade` (master, 1:1 item) | plant | item_id uq, hts_code S10 N (6-10 digits), coo S2 N, material_class S16 N, unit_weight_kg Dbl N |
| `mfg_tariff_rates` | net | dest_country S2, hts_prefix S10, coo S2 or `*`, layer S16 (`mfn`,`s232`,`s301`,`surtax`,`reciprocal`, free), rate_pct, per_unit N, per_unit_currency S8 N, valid_from, valid_to N, note |
| `mfg_fx_rates` | net | from_ccy S3, to_ccy S3, month Date, rate Dbl (> 0), source S16; uq (from, to, month) |
| `mfg_tariff_milestones` | net | code S32 uq, name, dest_country S2, family S32 N, hts_prefix S10 N, rule JSON `{domestic_country, basis: value\|weight, material_classes: [], include_conversion: false, min_pct}`, effective Date, note |
| `mfg_tariff_reports` | net | number, params JSON, status, result JSON, error, actor_id, started/finished |
| `mfg_country_risk` | net | country S2 uq, score Int (0..25), note |

Columns: `mfg_plant.kind` S8 (`plant` default, `dc`, `network`); `mfg_item_suppliers` + `coo` S2 N, `hts_code` S10 N,
`incoterm` S3 N, `freight_per_unit` Dbl N, `cap_per_month` Dbl N; `mfg_lots` + `coo` S2 N, `coo_source` S8 N
(`receipt`,`supplier`,`item`,`plant`,`transfer`), `unit_value` Dbl N (plant currency at receipt), `dom_share_value`
Dbl N, `dom_share_weight` Dbl N, `dom_estimated` Bool N, `dom_computed_at` DT N; `mfg_transfer_orders` + `source`
S8 (`manual`, `network`), `net_run_id` N. `planning_settings` (network workspace): `net_horizon_weeks` 26,
`net_firm_days` 14, `net_prebuild_weeks` 4, `net_constrained` true, `report_currency` USD, `domestic_country` US,
`duty_base {"*": "fob"}`, `other_cost_pct` 0.5, `holding_rate_pct` 20, `sop_calendar {demand_review: 5,
supply_review: 8, pre_sop: 10, executive: 12}` (working day of the period month).
Jobs (duty runs): `net_run`, `net_publish`, `sop_scenario_run`, `sop_publish`, `content_rollup` (debounced 5 min
after `wo_receipt` + nightly), `tariff_report`. Retention: last 60 net runs + published; cycles, scenarios, reports
indefinite.

## 4. Network workspace and topology

`POST /orgs/{org}/network` (org_admin) creates the workspace (409 `NET_EXISTS`); org admins become `plant_admin`
there. Plants/DCs are created as in M5 3.4 with a `kind`; a plant switches to `dc` only without lines (409
`NET_DC_HAS_LINES`). In a `network` workspace every M1-M8 write route answers 409 `NET_WORKSPACE` (one guard in
`access.mfg_principal`). **Nodes** = the org's `plant` and `dc` workspaces with country (`PlantRecord.country`),
currency, time zone. **Sourcing resolution** for (dest, key, date): active item-key rules win over family rules;
**quota mode** if any rule of the winning set has `quota_pct` (sum must be 100, 422 `NET_QUOTA_SUM`), else
**priority mode** (primary, then next on capacity spill). `source_kind supplier` = buy at the destination from that
supplier (how make-vs-buy and dual sourcing appear in DRP). A key without rule at a node is not networked there (its
plant MRP covers it as today). A rule without lane uses the active lane with fewest transit days (else 422
`NET_NO_LANE`).

## 5. Network planning (`mfg/network`)

### 5.1 Contract (`network/model.py`, frozen at S0)
`NetParams {as_of, horizon_weeks, constrained, prebuild_weeks, firm_days, node_ids?, forecast_versions?: {node:
version_id}}`. `NetProblem {nodes: [NetNode {id, code, kind, country, currency, tz}], items: [NetItem {node, key,
item_id, family, uom, std_cost, ss, lead_days, make_buy, order_multiple, min_qty, replenishment}], demand:
[NetDemand {node, key, week, qty, kind: order|forecast|transfer_open, ref, priority}], supply: [NetSupply {node, key,
week, qty, kind: stock|po|wo|rate|transfer_in, ref}], rules, lanes, bom: [NetBomLine {node, parent_key,
component_key, qty_per}] (networked components only), capacity: [NetCap {node, cap_group, week, hours}], load:
[NetLoad {node, cap_group, key, hours_per_unit}]}`. `NetResult {transfers, production, shortages, projection,
utilisation: [{node, cap_group, week, available, used}], kpis {fill_rate, shortage_units, inventory_value,
transfer_units}, explanations, validator}`. `NetPeg {node, kind: order|forecast|ss|dependent|transfer, ref, qty}`.
Weeks are Monday dates in the destination's time zone; money in report currency.

### 5.2 Build
One snapshot per run through `db.replica_reads()` (M6) when `DATABASE_READ_URL` is set, else one REPEATABLE READ
transaction per node. Demand: open customer order lines + unconsumed forecast of the node's active version (M8
consumption, spread to weeks); open TO lines are `transfer_open` demand at the source and `transfer_in` supply at
the destination. Supply: free stock (holds excluded; sterility supplies as M8 R1), open POs, WOs, published rate
supplies. Capacity (`capacity.py`): cap groups = M1 line/work-center groups; available hours per week from M1
calendar shift windows x active lines; hours/unit = 1 / (units_per_hour x OEE) from M8 line rates for flow lines,
routing run time + setup / fixed lot for discrete groups. Groups without rate or routing are unconstrained and
reported (`NET_CAP_UNKNOWN`).

### 5.3 Algorithm (`engine.py`, deterministic; ties by node code, key, week)
1. Graph on (key, node): sourcing edges dest -> source, BOM edges parent -> component at the same node; low-level
   codes by DFS; a cycle -> 422 `NET_CYCLE` with the path.
2. Netting by LLC ascending. Gross per week = independent demand + dependent (planned transfers out + BOM explosion
   of planned production); net requirement where projected < ss; lot sizing max(`min_qty`), multiple of
   `order_multiple`. Source per 4; **quota mode** = cumulative quota arrangement: the requirement goes to the source
   with the largest `quota x (assigned_total + req) - assigned_source` (ties by priority). Transfer ship = receive -
   `transit_days` (source working days); make/buy start = due - `lead_days`. Starts before `as_of` move to the
   earliest feasible week with `NET_LEAD_TIME` lateness on the pegs.
3. Capacity pass (`constrained`): before a vertex's production is exploded, its hours are booked per node x cap
   group x week in rank order (order > forecast > ss, earlier week first). Overload is resolved by (a) pre-build up
   to `prebuild_weeks` earlier into spare weeks (not before `as_of`), (b) spill to the next-priority source with
   spare capacity (also in quota mode once a quota source is full; deviation reported), (c) cut: `NET_CAPACITY_SHORT`
   at the vertex, unmet propagated to the pegged destination demand. Capacity is never exceeded; with `constrained
   false` load is only reported.
4. Pegging (`peg.py`): every planned transfer/production carries its pegs (FIFO by rank). `GET /net/runs/{id}/
   pegging` walks from a demand down through transfers, source supplies and network components across plants, or
   up from a supply.
5. Validator (independent code): flow balance per vertex-week (projected >= 0 except recorded shortages), capacity
   <= available, ship + transit = receive (source calendar), transfers only on allowed rules/lanes, quota share
   within one order multiple of target over the horizon (spill excepted), pegs sum to supply qty.

### 5.4 Publish and plant MRP (`publish.py`, perm `network_publish`)
One published run per org; 409 `NET_NOT_PUBLISHABLE` (not completed / validator failed), 409 `NET_RUN_STALE` (as_of
before today in the network time zone). Firm transfers (ship <= today + `firm_days`) group by (src, dst, lane, ship
date) into one M5 TO (status `open`, `source network`; M5 service writes both plants). Existing unshipped `open`
network TO lines matching (key, ship date, qty) are kept and re-linked, others cancelled with system reason
"Superseded by network plan NR-..."; shipped TOs are never touched. Later transfers enter plant MRP as
`MrpSnapshot.network_demands` at the source (kind `network`, ranked as `transfer`, priority 5, `ref {net_run, dst,
pegs[:5]}`) and `network_supplies` at the destination (supply kind `network`, sorted after transfers); both default
empty, so M2-M8 goldens are unchanged. A `transfer` item with residual requirement gets no planned order and raises
critical `MRP_NETWORK_SHORT`. The M2 pegging view shows the refs ("Transfer to DCUS for SO-000123"). Only
`network_publish` is needed; plant audit rows carry actor = the human and `via` = `network:NR-...`.

## 6. S&OP / IBP cycle (`mfg/sop`)

### 6.1 Cycle and calendar
`POST /sop/cycles {period}`: one non-cancelled cycle per period (409 `SOP_CYCLE_EXISTS`); due dates from
`sop_calendar`, step owners; the cycle pins the forecast version per node (active by default). `POST .../advance
{note}` steps in order; leaving `supply_review` needs a completed baseline scenario (409 `SOP_NO_BASELINE`), leaving
`pre_sop` a recommended scenario. `POST .../reopen {to_step, reason}` from `executive`/`approved` (not after
publish) supersedes signatures (M7 `superseded`). Overdue steps notify the owner (M6).

### 6.2 Demand review (`demand.py`)
Rows node x family x month: `stat_qty` = sum of final forecast lines of the pinned version, `order_qty` = open
customer orders, `base_qty` = sum over items of max(order, stat) per item-month (M8 consumption result),
`prior_consensus` from the last published cycle. External demand only (inter-node demand is derived). Overrides
abs/pct with reason, applied in `seq`; all-nodes pct scales each node, all-nodes abs splits by base share; result =
`consensus_qty`. `asp` = 12-month average `unit_price` of shipped demand lines of the family at the node, else
`std_cost` (flag `ASP_FROM_COST`), else manual. Item drill-down is read-only.

### 6.3 Constrained supply plan (`scenario.py`, `lp.py`)
`scenario.py` applies `changes` to an `SopProblem` (nodes, families, months; lanes with `transit_months` =
round(transit_days / 30); rules; effective hours per node x cap group x month (6.4); family hours/unit = demand-
weighted mean of item hours/unit; supplier options with landed cost; consensus demand; initial stock and SS target =
summed item stock/SS by node x family). Variables per (node n, family f, month t): `make` (where n has hours for f),
`buy[s]` (supplier options), `ship[lane]` (allowed lanes), `inv >= 0`, `unmet >= 0` (lost, not backlogged),
`ss_short >= 0`. Constraints: `inv[t-1] + make + Σbuy + Σship_in(t - transit) - Σship_out - consensus + unmet =
inv[t]`; `inv + ss_short >= ss_target`; `Σ_f make x hpu <= eff_hours[n,g,t]`; `buy <= cap_per_month`; allocation
`min_share x Σsupply <= supply_s <= max_share x Σsupply`; optional `enforce_milestones`: `Σ dom_s x supply_s >=
min_pct x Σ supply_s` per milestone family (shares from 8.3). Objective in three solves: (1) min Σ unmet x priority
weight (orders before forecast); (2) fix (1) <= opt + 0.5 unit, min Σ ss_short; (3) fix (2), min cost = make x
conversion cost (std_cost - material roll-up, else std_cost) + buy x landed (8.4) + ship x lane freight + inv x
std_cost x holding_rate / 12 + fixed cost of added lines, all in report currency (8.5). Non-optimal status -> scenario
`failed`, `SOP_LP_<status>`. Results rounded to whole units with cumulative rounding per series. Validator
(independent): balance, capacity, caps, shares, lanes, non-negativity, unmet = consensus - delivered (0.5 unit).

### 6.4 Rough-cut, ramp-up, yield (`curves.py`)
`eff_hours[n,g,t] = Σ_lines hours_in_month x mean over working days d of (rate(line, d) x yield(line, d))`. For a
virtual line rate/yield are piecewise-linear in weeks since `start` (0 before start, last point held); existing lines
1.0. Seeded curve `STD26` (week, rate %, yield %): (0,25,85) (4,50,90) (8,75,94) (13,90,97) (26,100,98). Rough-cut
view per node x cap group x month: available, required (unconstrained, consensus routed by primary rules), planned
(LP), utilisation % (watch > 85 %, alert > 100 % required).

### 6.5 Financial view (`finance.py`) and comparison
Per scenario x month x node x family in report currency: revenue = delivered x asp; COGS = make x std_cost + buy x
landed + freight; gross margin and GM %; inventory value (inv x std_cost) and days of cover; capex by change start
month. KPIs: service % (delivered / consensus), unmet units, max/avg utilisation per cap group, domestic share per
milestone family (8.3 projection); totals for horizon, calendar year and next 3 months. `GET /sop/compare?ids=` (<= 5)
returns KPIs and deltas versus the first (baseline).

### 6.6 Approval and publish
Content hash (M7 linking): cycle number and period, hash of the consensus table, scenario number + result hash + KPI
totals, validator status. `POST /sop/cycles/{id}/approve {scenario_id, signature}`: first step needs status
`executive`; M7 202 `pending_signatures` between steps; last step -> `approved`, `approved_scenario_id`; 409
`SOP_SCENARIO_INVALID` for validator-failed scenarios. `POST .../publish` (job, idempotent per cycle), per node: copy
the pinned version as "SOP-2027-01 consensus" (`source sop`), scale each family-month to consensus pro rata to item
`final_qty` (stat 0: by 12-month history share; neither: `SOP_DISAGG_NONE`, skipped), activate with reason
"Published from SOP-... (approved)"; replace `mfg_mps_targets` for months >= period from the scenario's make plan.
Result `{nodes: [{node, forecast_version_id, targets, warnings}], follow_ups}`. Plants show MPS attainment (actual
`wo_receipt` vs target per family-month) on `/mfg/mps` and a tile.

## 7. Scenarios: expansion, make-vs-buy, sourcing, risk

`ScenarioChange` = union on `kind`; every change has `id`, `label`, `note`.

| kind | fields |
|---|---|
| `add_line` | node, cap_group, name, start, hours_per_week, `hpu_by_family {family: h}` or `uph_by_family` + oee, curve code or points, capex, capex_currency, fixed_cost_per_month |
| `add_node` | code, name, kind `plant`/`dc`, country, currency, start, lanes [{from\|to, mode, transit_days, freight_per_unit}] (virtual; `add_line` may target it) |
| `capacity_change` | node, cap_group, from, to N, pct (-100 = closed, +20 = extra shift) |
| `sourcing` | dest_node, family, sources [{source_node\|supplier_code, min_share, max_share}] |
| `make_vs_buy` | node, family, option `make`\|`buy`\|`both`, supplier {code, unit_price, currency, coo, hts_code, freight_per_unit, cap_per_month} |
| `supplier_allocation` | node, family, suppliers [{code, min_share, max_share, cap_per_month}] |
| `demand_change` | node N, family N, from, to N, pct |
| `cost_change` | `tariff` (rows as `mfg_tariff_rates`, replacing by dest/prefix/coo/layer) \| `fx` {from, to, rate, from_month} \| `freight` {lane, pct} |

Make-vs-buy report (`GET /sop/scenarios/{id}/make-buy`) per node x family: make unit cost, buy landed unit cost per
supplier, LP split, hours freed, duty share. **Supplier risk** (`trade/risk.py`, on read, per plant item-supplier),
score 0-100: single source (only active supplier of an item with 12-month spend) 35; country risk table 0-25; lead
time > 60 d 15; on-time delivery (PO receipts vs confirmed date, 12 months) < 90 % 15, < 95 % 8; tariff exposure
(duty >= 10 % or non-domestic COO in a milestone family) 10; flags `single_source`, `sole_country`. **Dual-sourcing
suggestions** for score >= 50 within the top 80 % of spend: org suppliers (any plant) already supplying the same
family or HTS heading (4 digits), ranked by landed-cost delta then own score; "Create scenario" builds a
`supplier_allocation` change (default 60/40).

## 8. Country of origin, domestic content, landed cost (`mfg/trade`)

### 8.1 Capture
PO receipt: lot `coo` = request `coo` > item-supplier `coo` > item trade `coo` > null + `TRADE_COO_MISSING`;
`coo_source` records which; later change is a regulated edit (reason). `unit_value` = PO price / units per purchase
unit x FX (receipt month). `wo_receipt` lots: coo = plant country (`plant`). Transfer receipt copies coo,
unit_value (FX to destination currency) and shares (`transfer`).

### 8.2 Lot roll-up (`content.py`, pure over a genealogy subgraph; job `content_rollup`)
Inputs of made lot L = trace edges into its WO: lot -> WO (`exact`, qty) and item_stock -> WO (`possible`; item
trade coo and std_cost; sets `estimated`), attributed pro rata to L's share of the WO output. Per input: value v =
qty x unit_value (else std_cost), weight = qty x unit_weight_kg; domestic indicator = the input's own share if it is
a made lot (recursion, memoised, depth <= 30), else 1 if coo == `domestic_country`, else 0. `material_classes` keeps
only inputs of those classes (recursing under the same filter); `include_conversion` adds output std_cost x qty -
material value at the plant country (value basis only). Share = Σ dom x v / Σ v (null if Σ v = 0). The default rule
(no filter) is stored on the lot; milestone rules are computed in the report (memo per run).

### 8.3 Tariff-milestone report (`milestones.py`, job `tariff_report`)
`POST /trade/reports {milestone_ids, from, to, nodes?, group_by: family|item, projection: {scenario_id?}}`. Actuals:
finished lots in the milestone scope (family or HTS prefix, produced at nodes supplying `dest_country`) by production
month, share = Σ share_l x denom_l / Σ denom_l; status for months >= effective: `met` (>= min), `at_risk` (within 5
points below), `missed`; lots below minimum (count, qty, % of volume), % estimated, drill-down to a lot's input tree.
Projection (future months): per finished item a BOM share (multi-level M1 BOM, bought components weighted by
preferred item-supplier or the scenario's allocation shares and their COO), weighted by the scenario's (else the
approved cycle's) make plan; first missed month highlighted. Export xlsx + print view.

### 8.4 Landed cost (`landed.py`)
`landed(item_supplier, item_trade, dest_plant, month, tables) -> LandedCost {unit_price, freight, customs_value,
duty: [{layer, rate_pct, per_unit, amount}], other, total, currency, fx_rate, flags}`, per base unit in plant
currency: price = unit_price / units_per_purchase_unit x fx; freight = `freight_per_unit` (else 0 +
`FREIGHT_MISSING`); customs value = price (FOB) or price + freight (CIF per `duty_base[dest]`); duty per layer =
longest `hts_prefix` match, coo exact before `*`, valid in the month: rate_pct x customs value + per_unit x fx; coo ==
dest country -> no duty; no HTS -> 0 + `HTS_MISSING`; other = `other_cost_pct` x customs value; total = sum.
Served by `GET /trade/landed?item_id=` and as additive `landed` on item-supplier rows.
**FX** (`fx.py`): identity; direct row; inverse; via USD; else latest earlier month within 3 months (`FX_STALE`);
else `None` (`FX_MISSING`).

## 9. API (`/api/v1/mfg`, `router_m9.py`; route table at S0)

N/S/T routes answer only in the network workspace (409 `NET_WORKSPACE_REQUIRED` elsewhere); P routes are plant
routes.

| # | Method and path | Perm |
|---|---|---|
| O1 | POST `/orgs/{org}/network` (orgs router) | org_admin |
| N1-N4 | GET `/net/nodes`; GET, POST `/net/lanes`; PUT, DELETE `/net/lanes/{id}` | view / network_edit |
| N5-N7 | GET, POST `/net/sourcing?dest&key&family`; PUT, DELETE `/net/sourcing/{id}`; GET `/net/sourcing/resolve?dest&key&date` | view / network_edit |
| N8-N13 | GET, POST `/net/runs`; GET `/net/runs/{id}`; GET `/{id}/grid?node&key&family&page`; `/{id}/transfers?src&dst`; `/{id}/shortages`; `/{id}/utilisation` | view / network_plan |
| N14-N15 | GET `/net/runs/{id}/pegging?node&key&week` or `?supply_id`; POST `/net/runs/{id}/publish` | view / network_publish |
| N16 | GET, PUT `/net/ramp-curves` (list replace) | view / network_edit |
| S1-S6 | GET, POST `/sop/cycles`; GET `/sop/cycles/{id}`; POST `/{id}/advance`, `/{id}/reopen`, `/{id}/cancel` | view / sop_edit |
| S7-S10 | GET `/sop/cycles/{id}/demand?node&family`; GET, POST `/{id}/demand/overrides`; DELETE `/sop/demand-overrides/{id}` (reason header); PUT `/sop/cycles/{id}/demand/asp` | view / sop_edit |
| S11-S16 | GET, POST `/sop/scenarios?cycle_id`; GET, PUT, DELETE `/sop/scenarios/{id}` (draft); POST `/{id}/run`; POST `/{id}/copy {cycle_id}`; POST `/sop/cycles/{id}/recommend {scenario_id, note}` | view / sop_edit |
| S17-S21 | GET `/sop/scenarios/{id}/plan?node&family`; `/rough-cut`; `/financial?group_by`; `/make-buy`; GET `/sop/compare?ids` | view |
| S22-S23 | POST `/sop/cycles/{id}/approve` (signed); POST `/sop/cycles/{id}/publish` | sop_edit + policy roles / sop_publish |
| T1-T4 | GET, PUT `/trade/tariffs` (bulk upsert); GET, PUT `/trade/fx`; GET, PUT `/trade/milestones`; GET, PUT `/trade/country-risk` | view / trade_admin |
| T5-T8 | GET, POST `/trade/reports`; GET `/trade/reports/{id}` (`?format=xlsx`); GET `/trade/lots/{plant}/{lot_id}/content?milestone_id`; GET `/trade/risk?node&min_score` | view |
| P1-P5 | GET, PUT `/items/{id}/trade`; GET `/trade/landed?item_id`; GET `/trade/risk`; GET `/lots/{id}/content`; GET `/mps/targets?family&from&to` | view / master edit (PUT) |

Additive fields: item-supplier rows `coo`, `hts_code`, `incoterm`, `freight_per_unit`, `cap_per_month`, read-only
`landed`; PO receipt lines accept `coo`; lots carry the trade fields; TOs `source`, `net_run_id`. Network workspace
roles: planner `network_plan`, `sop_edit`; plant_manager + `network_edit`, `network_publish`, `sop_publish`,
`trade_admin`; new role `executive` = view + signer of `sop_cycle.approve`; auditor view. Plant item trade edit =
M1 master edit (planner, purchaser). Policy `sop_cycle.approve` is seeded in the network workspace (0.6), editable
under M7 rules, never below one `approved` step.

## 10. UI (UX standard; strings `lib/strings/network.ts` + fr-CA)

| Route | Screen |
|---|---|
| `/mfg/network` | Node/lane diagram (SVG, nodes by kind and country, lanes with transit days), latest run KPIs, shortages, cycle status |
| `/mfg/network/sourcing` | Rules by destination and key/family, quota bar per set, resolve tester; lanes editor |
| `/mfg/network/runs/:id` | Tabs: grid (node x week projection per key), transfers (firm marked), shortages with cause, capacity heatmap (node x cap group x week), pegging tree with cross-plant links, publish result (created / kept / cancelled TOs) |
| `/mfg/sop` | Cycles list and calendar strip (steps, due dates, owners, overdue) |
| `/mfg/sop/cycles/:id` | Stepper: Demand (family x month grid by node: stat / prior / consensus, override cells with reason, chart); Supply (rough-cut heatmap, scenarios, run); Financial (P&L table, charts via finance `LineChart`); Compare (KPI cards + deltas, <= 5); Approve (SignatureDialog with content summary and steps); Publish (per-node result, follow-ups) |
| `/mfg/sop/scenarios/:id` | Change list editor (form per kind), ramp/yield curve editor with chart and `STD26` template, capex note, make-buy report |
| `/mfg/trade` | Tabs: tariffs (bulk paste grid), FX (month x pair grid), milestones, country risk; reports `/mfg/trade/reports/:id`: status chips per family x month, projection band, lots below minimum, lot content tree, xlsx |
| `/mfg/sourcing-risk` | Risk table with flags and suggestions, "Create scenario" (plant and network) |
| plant screens | Item tab Trade (HTS, COO, material class, weight); item-supplier columns + landed breakdown popover; receipt dialog COO (prefilled; Part 11 reason on change); lot detail domestic share (value / weight, estimated badge); MRP labels `network` demand/supply, `MRP_NETWORK_SHORT`; `/mfg/mps` attainment |

Tiles: network `sop_cycle` (step, overdue), `net_shortages`, `tariff_milestones`; plant `mps_attainment`. The
workspace switcher marks the network workspace; plant-only menus are hidden there.

## 11. Delivery plan (lean)

| WP | Role | Owns |
|---|---|---|
| **S** backend | one backend developer | `mfg/{network,sop,trade}/**`, MRP edits, `orgs/service.py` edits, `api/mfg/{db_models_m9,repo_m9,router_m9}.py`, `services/{network,sop,trade,m9jobs}.py`, hooks in 11.1, migration `0012_m9`, `migrate.py`, seeded policy and curve, sample `meddev_m9`, load-seed `bd-network`, register rows, `docs/validation/m9-coo-reconciliation.md`, tests `tests/{network,sop,trade,api_mfg_m9}/**` |
| **U** UI | one UI developer | `frontend/src/mfg/{network,sop,trade}/**`, plant tabs/columns/fields of 10, tiles, role pickers (`executive`), strings + fr-CA, `frontend/e2e/m9-network.spec.ts` (one spec, `@req` tags) |
| LEAD | team lead | this document, S0 review, Gate 9 |

**S0 (days 1-2)**: pydantic contracts (`network/model.py`, `sop/model.py` incl. `ScenarioChange`, `trade/model.py`,
MRP additions), migration + up/down test, all routes live with permissions answering from `api/mfg/fixtures/
example_m9.json` (`build_example.py`, M8 PEP 562 fallback); U writes `typesM9.ts` + `contractExamplesM9.ts`.
**S1 (5 d)** topology, sourcing, build, capacity, engine, validator, pegging. **S2 (3 d)** publish, MRP inputs,
`transfer` replenishment. **S3 (6 d)** cycle, demand review, curves, scenarios, LP, validator, financial, compare,
approval, publish. **S4 (5 d)** trade capture, landed, FX, roll-up, milestone report, risk. **S5 (3 d)** sample,
load seed, performance, notes. **U1** network home, sourcing, run tabs. **U2** S&OP stepper (demand, supply,
financial, compare). **U3** scenario editor and curves, approve/publish, MPS page. **U4** trade tabs, report, risk,
plant trade fields, tiles, fr-CA, e2e.

### 11.1 Existing code and tests touched
M2 MRP snapshot/engine/views (network kinds, `transfer` replenishment, exception code); M5 transfers (`source`,
`net_run_id`, system-reason cancel, trade fields on receipt), org service (network workspace, plant kind), trace
queries (content drill-down); M2 receipts (COO, unit_value), item-supplier schemas, M1 item editor; M7 policy
registry and `sop_cycle` content; M6 tiles and notifications; `access.py` (`NET_WORKSPACE` guard, permissions, role
`executive`); route/permission tables and authz sweep (`make_mfg_m9_world`), migration head/table sets, job kinds,
retention, reset/reassign and sample registries. Existing tests change only in those tables; M2-M8 goldens unchanged.

## 12. Sample, performance, testing, acceptance

### 12.1 Sample `meddev_m9` (`manage.py load-org-sample meddev_m9 --org demo-meddev`)
Org "Demo Meddev": `QC` Quebec City (CA, CAD; the `meddev_m8` content: syringes, IV catheters), `US1` (US, USD;
needles on flow lines `NA-01/02`, cannula steel from `KTUBE` (US) and `ATUBE` (CN), illustrative), DC `DCUS` (US;
customer orders and forecasts for syringes and needles), `NET`. Lanes QC -> DCUS road 3 d, US1 -> DCUS road 2 d, US1
-> QC road 4 d (kit needles). Sourcing: DCUS syringes QC; DCUS needles US1; QC kit needles US1 70 % / external 30 %.
HTS on all items (9018.31 syringes, 9018.32 needles; fictional rates incl. one `s301` CN layer and one `surtax` CA
layer), 24 months USD/CAD FX, risk table. Milestone `NDL-US-STEEL` (dest US, family NDL, steel only, value basis,
min 100 %, effective 2027-07-01); finished needle lots mix KTUBE and ATUBE steel, so some miss. One published net
run; cycle `SOP-2026-11` published; cycle `SOP-2026-12` at `pre_sop` with baseline, "US1 line NA-03 (STD26, start
2027-03-01, capex 45 M USD)" and "Dual-source cannula 60/40 KTUBE".

### 12.2 Performance targets (local PostgreSQL 16, M8 machine class; `load-seed --profile bd-network`: 3 plants + 2 DCs, 3,000 keys, 60 families)
| # | Case | Target |
|---|---|---|
| P1 | net run 5 nodes x 3,000 keys x 26 weeks, constrained, incl. snapshot | < 90 s (engine < 30 s), < 1.5 GB RSS |
| P2 | net validator | < 10 s |
| P3 | S&OP scenario LP 5 nodes x 60 families x 18 months, 3 solves + validator | < 30 s |
| P4 | compare 5 scenarios / financial view | < 1 s |
| P5 | content roll-up, 30 days of finished lots (1,500 lots, depth 4) | < 30 s |
| P6 | tariff report 12 months + 18-month projection, 2 milestones | < 20 s |
| P7 | landed list 3,000 item-suppliers; risk table | < 2 s each |
| P8 | pegging query for any demand | p95 < 500 ms |
| P9 | net publish (14 days, 5 nodes); S&OP publish (5 nodes) | < 60 s each |
| P10 | S&OP demand grid 60 families x 18 months x 5 nodes | < 800 ms |

### 12.3 Test vectors = M9 requirement register (`@pytest.mark.req`)
| ID | Case | Expected |
|---|---|---|
| M9-NET-01 | DC needs 100/week x 5, quota A 60 / B 40, multiple 100 | weeks to A, B, A, B, A; A 300, B 200 |
| M9-NET-02 | primary capacity 150/week, need 200/week, secondary free | 150 primary, 50 spill, explained |
| M9-NET-03 | week-5 peak over capacity, spare weeks 2-4 | pre-built within 4 weeks; no shortage |
| M9-NET-04 | overload beyond pre-build and spill | `NET_CAPACITY_SHORT`; unmet pegged to the DC order line |
| M9-NET-05 | rule loop DC -> QC -> DC | 422 `NET_CYCLE` with path |
| M9-NET-06 | transit 3 working days, receive Monday | ship previous Wednesday (source calendar) |
| M9-NET-07 | publish, change demand, publish again | TO lines kept / cancelled / created per rule; shipped untouched |
| M9-NET-08 | plant MRP after publish | `network` demand at source, supply at DC; residual -> `MRP_NETWORK_SHORT`; M2-M8 goldens unchanged |
| M9-NET-09 | needles from US1 into QC kits | pegging DC order -> QC kit -> transfer -> US1 production -> cannula |
| M9-NET-10 | validator mutations (capacity, balance, lane, peg sum) | each detected |
| M9-SOP-01 | all-node +10 % then QC abs 5,000 | consensus as hand table; audit reason |
| M9-SOP-02 | two sources, ample capacity, B cheaper landed | unmet 0; all on B |
| M9-SOP-03 | capacity < demand | unmet = demand - capacity (tier 1); never traded for cost |
| M9-SOP-04 | add line Mon 2027-03-01, points (0,20,100) (4,60,100) (8,100,100) | week 2 rate 40 %; March factor = mean daily factor (hand) |
| M9-SOP-05 | yield 90 % | good output = hours / hpu x 0.9 |
| M9-SOP-06 | 1,000 delivered x 2.00 CAD, FX CAD->USD 0.72 | revenue 1,440 USD |
| M9-SOP-07 | reviewed (plant_manager), approved (executive); same person twice | 422 distinct signers; then `approved`; edits 409 `SOP_CYCLE_LOCKED` |
| M9-SOP-08 | reopen with reason | signatures `superseded`; content hash changes after edit |
| M9-SOP-09 | publish: family consensus 1,200, item finals 600/300/100 | 720/360/120; version active; MPS targets written |
| M9-SOP-10 | `enforce_milestones` with too little domestic supply | share >= min, else unmet with cause |
| M9-TRD-01 | receipt COO precedence | `coo_source` per rule; warning when missing |
| M9-TRD-02 | needle lot: steel A 2.0 kg US v 30; steel B 1.0 kg CN v 10; resin 0.5 kg CA v 5; cap (non-lot) 0.4 kg JP v 8 | value 30/53 = 0.566, weight 2/3.9 = 0.513, estimated; steel-only value 0.75, weight 0.667 |
| M9-TRD-03 | made sub-assembly lot (share 0.5) in a finished lot | recursion uses 0.5, value-weighted |
| M9-TRD-04 | transfer US1 -> QC | coo, unit_value (FX), shares carried |
| M9-TRD-05 | milestone min 100 %, months at 100 / 97 / 80 | met / at_risk / missed |
| M9-TRD-06 | 100 USD per 1,000, USD->CAD 1.40, freight 0.005 CAD, CN, mfn 0 + surtax 25 %, FOB, other 0.5 % | price 0.14, duty 0.035, other 0.0007, total 0.1807 CAD |
| M9-TRD-07 | FX inverse, via USD, 2 months stale, missing | rate / `FX_STALE` / null + `FX_MISSING` |
| M9-TRD-08 | single-source CN item, OTD 88 %, lead 75 d, duty 25 % | 35 + country + 15 + 15 + 10; suggestion lists a same-heading supplier |
| M9-TRD-09 | make-vs-buy, landed < make cost, tight capacity | LP buys up to cap, makes the rest |

### 12.4 Testing during work
Tests ship with the code; only touched packages run (`.venv/bin/pytest tests/network -q`, `tests/sop -q`,
`tests/trade -q`, named MRP and transfer tests); performance tests marked `slow`. UI: `npm run build`, `npm run
i18n:check`, the m9 spec. **Final gate (once, LEAD):** full backend suite on PostgreSQL incl. `-m slow`;
`m9-network.spec.ts`, `m8-planning.spec.ts`, `mfg-m2-mrp.spec.ts`; migration 0011 -> 0012 on a populated database and
downgrade (network TOs become `manual`; `sop_cycle` signatures and policies deleted as M8 R11); `trace-matrix` with
the M9 register.

### 12.5 Acceptance (Gate 9)
1. `meddev_m9` network (two plants + one DC): net run validator-clean and published; TOs in both plants; plant MRP
   shows network demand/supply; pegging from a DC order to a US1 component.
2. Signed S&OP cycle end to end: demand review with overrides, baseline + expansion + dual-source scenarios,
   financial comparison, two-step signature with manifestation in the M7 record package, publish to forecast
   versions and MPS targets.
3. Expansion scenario with ramp-up: capacity and KPIs change from the start month along the curve (M9-SOP-04).
4. COO report reconciled by hand for the sample milestone (M9-TRD-02/05 + sample hand sheet
   `docs/validation/m9-coo-reconciliation.md`); landed cost matches M9-TRD-06.
5. P1-P10 met on `bd-network` and recorded in 13; full suite green once; m9 spec green; no high-risk M9 requirement
   without a test.

### 12.6 Demo video scenes (after storyboard 16)
17. Network diagram and DRP run; a DC shortage pegged back to a US1 capacity cut. 18. Demand review with a consensus
override. 19. Supply review heatmap; expansion scenario with `STD26` ramp; financial compare. 20. Executive signs;
publish updates plant forecasts. 21. Needle tariff milestone: lots missing US steel, dual-source scenario projecting
"met" from September 2027, landed-cost breakdown. Coverage after M9: 27 of 31 expectations (gap plan 2).

## 13. Questions and implementation notes

No blocking questions. Defaults decided by LEAD 2026-11-27 (all configurable): weekly DRP, 26 weeks, 14-day firm zone;
monthly S&OP by family, 18 months, lost-sales LP; two-step approval (plant_manager reviewed, executive approved); FOB
duty base; substantial transformation = plant country; report currency USD; domestic country US; `STD26` ramp. To
confirm with BD (does not block): S&OP grain (family vs product line); whether milestones count value or weight and
which materials ("melted and poured" steel origin is captured as supplier COO); reporting currency; whether DCs run
SAP EWM (DC stock would then come through the M8 adapter).

Implementation notes: (S0 and later phases append here.)

**S0 frozen (2026-11-27, WP-S).** Contracts `mfg/network/model.py`, `mfg/sop/model.py` (incl. `ScenarioChange`, a
union discriminated on `kind`), `mfg/trade/model.py`, MRP additions (`MrpSnapshot.network_demands` /
`network_supplies`, `NetworkDemandSnap`, requirement / supply kind `network`, replenishment `transfer`); migration
`0012_m9` (+ `migrate.HEAD`); all routes of 9 live in `api/mfg/router_m9.py` answering from
`api/mfg/fixtures/example_m9.json` (`build_example_m9.py`; `services/m9_examples.py`, PEP 562 fallback as M8);
permissions `network_edit`, `network_plan`, `network_publish`, `sop_edit`, `sop_publish`, `trade_admin`, role
`executive`; O1 `POST /orgs/{org}/network`. Field names follow the UI draft `frontend/src/mfg/api/typesM9.ts`.
S0 interpretations:
- Workspace guards live in `access.mfg_principal` (`workspace_guard`): N/S/T paths outside the network workspace ->
  409 `NET_WORKSPACE_REQUIRED`; writes in the network workspace -> 409 `NET_WORKSPACE` except N/S/T, `/esig/`,
  `/part11/`, `/plant/part11` and `/plant/planning-settings` (the network settings of 3 are additive keys of
  `planning_settings` there). Reads answer (plant reads return empty data). The guard runs before the permission
  check (409 before 403). `GET /trade/risk` serves both P3 (plant) and T8 (network, org-wide).
- S22 approve declares permission `view`: the signers are decided by the policy `sop_cycle.approve` (plant manager
  `reviewed`, executive `approved`); requiring `sop_edit` would exclude the executive role of 9.
- Bulk tables: `PUT /trade/tariffs` / `/trade/fx` take `{rows, replace}` (upsert by natural key; `replace` deletes
  rows not given); `PUT /trade/milestones` / `/trade/country-risk` / `/net/ramp-curves` are list replaces
  (`{rows}` / `{curves}`); results `BulkResult {inserted, updated, deleted}`.
- Plants are created with `kind` (`plant` | `dc`), `country` (plant attribute, read by `PlantRecord.country`) and
  `currency` (`OrgPlantIn`, additive); `PUT /orgs/{org}/plants/{plant}` accepts `kind` (409 `NET_DC_HAS_LINES`).
- Additive columns beyond 3: `mfg_net_runs.label`, `publish_result`; `mfg_sop_demand.items` (per-item basis for the
  drill-down and disaggregation); `mfg_sop_scenarios.baseline`, `enforce_milestones`, `warnings`;
  `mfg_mps_targets.cycle_number`, `created_at`. Report-currency KPIs and records carry `currency`.
- M8 follow-up (M8 15 request): `SterLoadRecord.lots [{lot_id, lot_code}]` = the load's open sterility holds, else
  its members' lots; the signature preview's "Lots" row lists those lot codes.

S1 notes (network planning, as built):
- `mfg/network/{model,calendar,capacity,build,engine,validator,peg}.py`. The engine processes vertices (node, key)
  from a work queue ordered by (low-level code, node code, key); a vertex re-plans when its dependent requirements
  change (spill targets), retracting what it emitted before (bounded; `NET_NOT_CONVERGED` guard). Safety stock is a
  requirement in the first week ranked after that week's orders; lot excess is pegged `ss`. One receipt (one source
  decision) per vertex-week; quota mode applies the cumulative formula per receipt (M9-NET-01 hand table).
- Capacity: rank order inside a vertex (orders, forecast, safety stock, lot excess last); across vertices the
  booking order is the processing order. Pre-built receipts are separate production rows with `prebuilt_from`.
  A spilled part becomes a transfer from the destination's next source (`spill true`, exempt from the quota check)
  or a buy from a supplier rule; without a further source the cut is a `NET_CAPACITY_SHORT` at the cause vertex
  (`final false`) and at the pegged destination demand (`final true`). A capacity cut of a BOM component is
  recorded at the component (no cascade to the parent's production) - simplification.
- Lateness: a receipt that cannot arrive in its need week (start / ship before `as_of`) keeps its later date; the
  covered demand gets a `NET_LEAD_TIME` shortage (`late_weeks`) in the need week. KPI `fill_rate` = 1 - final
  non-lead-time shortages / independent demand (orders + forecast in the horizon).
- Build: per node `repo_m2.load_mrp_snapshot` + `m8mrp.add_inputs` inside the node's owner scope and a REPEATABLE
  READ snapshot transaction (`snapshot_tx`; replica reads follow `DATABASE_READ_URL` through it). Stock in
  inspection is supply one week out; quarantine / scrap locations and expired lots are excluded. Item master values
  (std cost, lead time, SS, multiples) are the node's own; money is not FX-converted in DRP (KPIs are informative).
- Capacity: `base` shift windows of active lines x parallel capacity per Monday week (plant time zone); hours /
  unit from M8 line rates (item, else family; mean over the group's lines) else the first released routing
  (run + setup / max(fixed lot, MOQ, 1)), all groups of the item booked.
- `POST /net/runs` checks synchronously (422): quota sums (`NET_QUOTA_SUM`), lanes of plant rules
  (`NET_NO_LANE`), rule loops per key / family (`NET_CYCLE` with the path); loops through BOMs fail the run with
  `NET_CYCLE`. Lanes / rules referencing a node outside the organisation: 422 `NET_UNKNOWN_NODE`.
- The run stores item names / UoM per node and the utilisation in `summary` (stripped from the record's summary),
  timings (`snapshot_s`, `engine_s`, `validator_s`) and the input hash; retention keeps the last 60 runs plus
  published ones. Pegging without a single demand ref at (node, key, week) returns a root grouping one subtree per
  ref (<= 50); links (`/mfg/transfer-orders/{id}`) only for nodes the caller is a member of.
- Sourcing rule ids use `nsg_` (`nsr_` is already the M2 number-series prefix).

