# SuperPlanner M4 - Execution and replanning (design + plan + acceptance)

Status: design for build. Phase M4 of `docs/MANUFACTURING-GAP-ANALYSIS.md`. Builds on M1 (`docs/M1-DESIGN.md`,
"M1 n"), M2 (`docs/M2-DESIGN.md`, "M2 n": ledger, WOs, MRP, workspaces/permissions) and M3 as built
(`docs/M3-DESIGN.md`, "M3 n", incl. 17: APS runs, publish, freeze basis, `copy_of`, `open_shifts`, job kind
`aps_run`). Their conventions apply unchanged and are not restated. Interpretations go to section 16 only.

Scope (roadmap): release WOs to the floor; shop-floor actuals per operation; barcode-friendly screens; scrap,
rework and yield into the ledger and MRP; event-driven replanning within the frozen horizon; line downtime;
oven/rack batching; supply-delay and breakdown simulation; KPIs and dashboard; serial capture; operator and
supervisor roles. Replaces M3's minimal "operation done" marker.

## 0. Decisions

1. **WO operations become real records** (`mfg_wo_operations`), created when a WO is released (lazily for older
   WOs), with a status machine and actual quantities/times. Their state is maintained from an **append-only floor
   event log** (`mfg_floor_events`), exactly like M2 balances are maintained from the ledger: events are never
   edited; corrections are correction events by a supervisor. M3's `mfg_wo_op_progress` is migrated and dropped;
   M3 `/done` and `/reopen` remain as supervisor shortcuts mapped to events.
2. **Material and output move through the M2 ledger, never beside it**: the last operation's good quantity posts a
   `wo_receipt` automatically; scrap is recorded on the WO; components are issued as in M2 (manual) or, for items
   with `issue_method = backflush`, posted automatically from the line's location at operation completion. A
   backflush that would make stock negative is **not** posted; it becomes a pending backflush exception for the store
   keeper (M2 P7/P8 hold: stock never negative).
3. **Barcodes without special hardware**: keyboard-wedge scanners type into a focused scan field; one resolver
   endpoint maps a scanned string to WO, operation, lot, serial, location, line or operator badge. Travellers and
   labels are printable HTML with Code 128 drawn as SVG in the browser (no new packages, no printer drivers).
4. **Operators**: M1 operators gain an optional `user_id`. Tablets may use personal logins or a shared **station
   account** (role `operator`) with a badge scan per action; events record both the authenticated actor and the
   operator(s) who did the work. New roles `operator` and `supervisor`; tablet-first pages under `/mfg/floor`.
5. **Replanning is event-driven and conservative**: rules turn events into **replan triggers** (line down, late
   receipt, scrap shortfall, overrun, rush order, start short, not started). Plant policy `replan_policy`:
   `notify` (**default**), `auto_whatif` (debounced proposal run, copy of the published run at `as_of = now`), or
   `auto_publish` (proposal published only when validator-clean, the freeze is untouched except where downtime
   forces a move, and weighted tardiness is not worse than the published plan). Debounce uses the queue's
   `run_after`; triggers arriving meanwhile coalesce into the queued run.
6. **APS uses actuals**: completed operations drop out, running ones are fixed at their actual start with the
   remaining quantity's time, paused ones must resume first, open downtime closes the line until its expected end.
7. **Batching** (deferred from M3): lines with `batch_merge` combine compatible `run_per = batch` operations of
   different WOs into shared loads (same group, same `setup_family`, same `units_per_batch` and run minutes per
   batch); the floor starts/completes a load as one action for all members.
8. **Simulation**: deterministic what-if (M3 + supply delays + line breakdowns) and a **risk run**: N sampled
   scenarios (default 20) of supplier delays and breakdowns drawn from the plant's own history, construction only,
   giving each demand line an on-time probability and P50/P90 completion.
9. **Serial boundary**: M4 **captures** unit serials of serialized items at the operation flagged
   `capture_serial` and records **one-level as-built links** (which child serials went into which parent serial at
   the consuming operation), with a lookup screen. Multi-level genealogy views, lot-level traceability, recall
   reports and ERP export are **M5**.
10. **KPIs** computed from events, ledger and the published plan (definitions in 9), closed days cached in
    `mfg_kpi_daily`; dashboard with OTD, utilisation, OEE-lite, WIP, setup time, schedule adherence and first-pass
    yield.
11. **Lean delivery**: WP-S (one backend developer) and WP-U (one UI developer), contract frozen at S0, tests with
    the code, targeted runs only, one full backend suite at the end, browser e2e only for the floor journey.

## 1. Scope and principles

**In:** WO operations and floor events; release-to-floor checks; actuals (setup/run start, pause, resume,
complete, partial reports of good/scrap/rework, operators, line, times); rework loops to an earlier operation of
the same WO; backflush; auto WO receipt; downtime; batching; serial capture + one-level links; replan triggers,
policy, notifications; APS with actuals; simulation (deterministic + risk run); KPIs; floor and supervisor screens;
roles; import of downtime history and operator user links.

**Out (M5+):** genealogy beyond one level, lot traceability reports, ERP connectors, email/SMS notifications,
machine/PLC data capture (IoT), labour costing and payroll, separate rework routings, statistical process control.

**Principles** (in addition to M1-M3): F1 the event log is the truth for execution, like the ledger for stock;
F2 the floor is never blocked by planning: an operator can always start, report and finish real work (deviations
become exceptions, not refusals), except where data would be invalid (wrong WO/line eligibility, negative
quantities, completed operation); F3 nothing republishes the plan silently: auto-publish is opt-in and audited;
F4 every floor action works with a scanner and a large-touch screen and survives a dropped network (idempotent
client event ids).

## 2. Package layout (ownership in 13)

```
backend/superplanner/mfg/
  model_m4.py        WoOperation, FloorEvent, Downtime, BatchLoad, UnitSerial, ReplanTrigger, KPI shapes (3-10)
  floor.py           pure event rules: op state machine, quantity checks, effects (postings, statuses) (4)
  scan.py            barcode grammar and resolution plan (5)
  replan.py          trigger rules over (event, published plan, ledger) (7)
  kpi.py             KPI formulas over loaded rows (9)
  aps/actuals.py     snapshot of execution state for APS (6); aps/batching.py loads (6.3); aps/simulate.py (8)
backend/superplanner/api/mfg/
  db_models_m4.py repo_m4.py services/floor.py services/downtime.py services/replan.py services/kpi.py
  services/serials.py router_m4.py   (+ edits: workorders.py, aps.py, items/lines/operations/plant services)
frontend/src/mfg/floor/**  (tablet pages)   frontend/src/mfg/pages/... (supervisor, replan, KPIs, serials)
```

## 3. Data additions

### 3.1 Columns on existing tables (all with defaults; migration drops server defaults after the add)

| Table | Column | Default | Meaning |
|---|---|---|---|
| `mfg_items` | `issue_method` S8 | `manual` | `manual` (M2 issues) or `backflush` (4.4) |
| `mfg_operations` | `capture_serial` Bool | false | serials of the WO item are captured when this operation completes (10) |
| `mfg_lines` | `location_id` FK locations SET NULL N | null | line-side location for backflush (else the plant default) |
| `mfg_lines` | `batch_merge` Bool, `batch_wait_minutes` Int | false, 0 | 6.3 |
| `mfg_operators` | `user_id` FK users SET NULL N | null | the account of this operator (personal login) |
| `mfg_plant` | `replan_policy` S16, `replan_debounce_minutes` Int, `overrun_tolerance_pct` Dbl, `adherence_tolerance_minutes` Int, `wo_receipt_location_id` FK N, `backflush_location_id` FK N | `notify`, 15, 20, 120, null, null | 4, 7, 9 |
| `mfg_work_orders` | `receipt_location_id` FK N, `released_to_floor_at` DT N, `release_override` S200 N | null | 4.1 |

Plant/line/item/operation/operator fields are master data (M1 rules, import columns added to the existing sheets).

### 3.2 New tables (migration `0006_mfg_m4`, M1-M3 conventions)

| Table | Key columns |
|---|---|
| `mfg_wo_operations` E | wo_id FK CASCADE, seq, name, group_id S64, status (`pending, ready, setup, running, paused, completed, skipped`), qty_planned Dbl (yield-inflated input, M1 4.4), qty_good, qty_scrap, qty_rework_out, qty_rework_in, line_id FK SET NULL N (current/last), setup_minutes_actual, run_minutes_actual, labour_minutes, actual_start, actual_end, started_short Bool, source (`release`/`lazy`/`migrated`); uq (wo_id, seq) |
| `mfg_floor_events` | wo_operation_id FK RESTRICT, wo_id FK RESTRICT, seq BigInt Identity, event_type S16, event_at DT, recorded_at DT, line_id S64 N, operator_ids JSON, qty_good/qty_scrap/qty_rework Dbl N, rework_to_seq Int N, reason_code S32 N, note S500, client_event_id S64 N, batch_load_id FK N, serials JSON N, corrects_event_id FK SET NULL N, actor_id S64; partial uq (owner_id, client_event_id); ix (wo_operation_id, seq), (owner_id, event_at), (line_id, event_at) |
| `mfg_downtime` E | line_id FK RESTRICT, kind (`breakdown, maintenance, no_crew, no_material, other`), planned Bool, start_at, end_at N (open), expected_end_at N, reason S200, note, reported_by, closed_by; ix (line_id, start_at) |
| `mfg_batch_loads` E | line_id FK RESTRICT, status (`open, running, completed, cancelled`), started_at N, ended_at N, aps_run_id S64 N; `mfg_batch_load_members` (load_id FK CASCADE, wo_operation_id FK RESTRICT, qty Dbl; uq (load_id, wo_operation_id)) |
| `mfg_unit_serials` E | item_id FK RESTRICT, serial S64, wo_id FK SET NULL N, status (`wip, in_stock, consumed, shipped, scrapped`), captured_at, captured_op_seq, parent_serial_id FK SET NULL N, consumed_at N, consumed_wo_id S64 N; uq (owner_id, item_id, serial); ix parent_serial_id |
| `mfg_replan_triggers` | kind, severity, ref_type, ref_id, detected_at, dedupe_key S200, details JSON, status (`open, attached, handled, ignored`), aps_run_id S64 N, handled_by S64 N, handled_at N; partial uq (owner_id, dedupe_key) where status in (open, attached) |
| `mfg_notifications` | kind, severity, title S200, body S1000, link S300, trigger_id N, created_at, acknowledged_at N, acknowledged_by N; ix (owner_id, created_at) |
| `mfg_aps_simulations` E | base_run_id S64, status (queued/running/completed/failed), samples Int, params JSON, results JSON, job_id S64 N; one queued/running per owner |
| `mfg_kpi_daily` | day Date, metric S32, dim_type S8 (`plant, group, line`), dim_id S64 N, num Dbl, den Dbl, value Dbl N; uq (owner_id, day, metric, dim_type, dim_id) |

`mfg_wo_op_progress` (M3): rows with `done` become `mfg_wo_operations` (`status completed`, name/group from the
WO routing's operation of that `seq` by SQL join, actual fields null, `source migrated`); then the table is dropped.
Jobs: `jobs.aps_simulation_id` (FK CASCADE), kind `aps_simulation`; `ck_jobs_one_target` becomes "exactly one of
four". Reset/reassign registries include all new tables (M2 9.4).

## 4. Execution model (`mfg/floor.py`)

### 4.1 Release to the floor

`POST /work-orders/{id}/release` (M2) additionally creates the operation rows (from `routing_id`, else the primary
routing at the start date, M3 17) and runs the kitting check (M2 7.4). With a component shortage on the first
operation the release still succeeds only with `{"override_reason": "..."}` (stored in `release_override`), else
409 `WO_KIT_INCOMPLETE` with the shortage list. `released_to_floor_at` is set. Operations of older released WOs are
created on first access (`source lazy`). A WO's operations are editable only by re-deriving while no event exists
(`refresh-components` analogue: `POST /work-orders/{id}/operations/refresh`).

### 4.2 Operation state machine

| Event | From | To | Rules |
|---|---|---|---|
| `setup_start` | pending, ready, paused | setup | line: eligible active line of the group (422 `FLR_LINE_NOT_ELIGIBLE`); line not down (409 `FLR_LINE_DOWN` unless supervisor) |
| `start` (run) | pending, ready, setup, paused | running | first start sets `actual_start`; predecessor not completed -> allowed only with transfer batch overlap or by supervisor (`FLR_PREDECESSOR_OPEN` warning recorded, F2) |
| `pause` | setup, running | paused | `reason_code` required |
| `resume` | paused | the state before the pause | |
| `report` | setup, running, paused | unchanged | partial quantities `qty_good`, `qty_scrap`, `qty_rework` (+ `rework_to_seq` <= current seq) |
| `complete` | setup, running, paused | completed | final quantities of this event; `actual_end` |
| `reopen` | completed | paused | supervisor; reverses the auto postings of this operation's completion (reversal postings, M2 4.2) |
| `correct` | any | recomputed | supervisor; references the corrected event; replaces its quantities/times |
| `skip` | pending, ready | skipped | supervisor, reason required |

`ready` = predecessors completed (or transfer batch reached) and kit not short; computed on read. State and
counters are recomputed from the event log of the operation in seq order (pure function, also used by tests).
Times: `event_at` defaults to now; backdating up to 24 h by the operator, unlimited by a supervisor (not before
`actual_start` of the WO, never in the future: 422 `FLR_TIME_INVALID`). Durations: setup = time in `setup`, run =
time in `running`, minus pauses; labour minutes = run/setup time x operators on the event.

Quantities (count UoM integral, M2 3): `qty_good + qty_scrap <= available input + EPS` where available input =
predecessor's good qty (first op: WO `qty_planned` of op 1) + `qty_rework_in`; over -> 422 `FLR_QTY_EXCEEDS_INPUT`
(supervisor may force with reason). Rework of `n` units from op k to op j (<= k) adds `n` to op j's
`qty_rework_in` and re-opens op j if completed (status `paused`). Yield of an operation = good / (good + scrap).

### 4.3 Effects (same transaction, M2 lock order: WO header -> operations -> postings)

- **Last operation** `report`/`complete` with `qty_good > 0` -> `wo_receipt` posting of that quantity to
  `wo.receipt_location_id` -> `plant.wo_receipt_location_id` (else 422 `FLR_NO_RECEIPT_LOCATION`), with scrap of
  the last operation as `scrap_qty`; serialized items need the serials (10). WO statuses follow M2 7.1.
- Scrap on earlier operations is added to `work_orders.qty_scrapped` (no stock movement; consumed components stay
  issued).
- **WO shortfall**: when completed good output + open input can no longer reach `qty`, the WO keeps its quantity and
  trigger `scrap_shortfall` is raised (7); the planner decides (increase a child WO, new WO, or short-close).

### 4.4 Backflush

Components of the operation (component `operation_seq` = seq, None -> first op) whose item has `issue_method =
backflush` are issued at `report`/`complete` for `(good + scrap) x per-unit requirement` (M2 7.2 rounding, cumulative
per operation so partial reports never over-issue) from `line.location_id` -> `plant.backflush_location_id`, lots
FEFO (M2 4.1). Insufficient available stock -> nothing is posted for that component, the event is still accepted
and an exception `FLR_BACKFLUSH_PENDING` (+ notification to store keepers) lists it; `POST /floor/backflush/retry`
re-attempts all pending ones. Pending backflush is shown in kitting and counted in MRP as open component need.

## 5. Barcodes (`mfg/scan.py`)

Grammar (case-insensitive prefixes; raw document numbers also accepted):

| Scan | Meaning |
|---|---|
| `WO-000143` or any WO number | work order |
| `WO-000143/30` | operation seq 30 of that WO |
| `L:<part>:<lot>` | lot |
| `S:<part>:<serial>` | unit serial |
| `LOC:<code>`, `LIN:<code>` | location, line |
| `OP:<code>` | operator badge (M1 operator code) |
| `BL:<id-suffix>` | batch load |

`GET /floor/scan?code=` -> `{type, id, label, link, context}` or 404 `FLR_SCAN_UNKNOWN`. Travellers (WO header +
operation barcodes), lot labels, serial labels and badges are printable pages rendered by the UI (Code 128 SVG,
`@media print`). Scanner input = a focused text field that submits on Enter; every floor page keeps it focused.

## 6. APS with actuals and batching

### 6.1 Snapshot (`aps/actuals.py`)

`completed`/`skipped` operations are dropped. `running`/`setup`: fixed on their line from `actual_start`; remaining
time = remaining quantity (`qty_planned - good - scrap + rework_in`) x run rate (+ remaining setup if in setup),
ending no earlier than `as_of`. `paused`: must resume first on its line (remaining as above). Pending backflush and
open component needs act as M3 material constraints. Open downtime closes the line from `start_at` to
`expected_end_at` (missing -> `as_of + 4 h`, exception `FLR_DOWNTIME_NO_END`); planned future downtime closes its
window. Frozen operations (M3 6.6) on a line that is down are moved anyway (`moved_by_downtime` flag) - feasibility
first.

### 6.2 Adherence basis

The published run's planned start/end per WO operation is the adherence baseline (9). Runs keep their M3 freeze
basis rules.

### 6.3 Batching (`aps/batching.py`)

On a line with `batch_merge`, operations with `run_per = batch` are *compatible* when they share group,
`setup_family` of the item, `units_per_batch` and `run_minutes`. Construction fills loads: an operation's units go
into loads of `units_per_batch`; the last partial load may be topped up with units of compatible ready operations
(priority order), waiting at most `batch_wait_minutes` for them. A load occupies one capacity unit for one
`run_minutes`; every member operation ends when its last load ends. Loads are part of the run result
(`batches: [{load_no, line_id, start, end, members: [{op_no, qty}]}]`), drawn as one Gantt bar with member markers.
On the floor `POST /batch-loads` creates a load (from the published plan's proposal or ad hoc); `start`/`complete`
events with `batch_load_id` apply to every member (quantities per member in `details.members`).

## 7. Replan triggers and policy (`mfg/replan.py`)

Rules run after each relevant write (event, downtime, posting, document change) within the same request (cheap,
indexed lookups against the published run); each yields at most one open trigger per `dedupe_key`.

| Kind | Condition | Severity | dedupe_key |
|---|---|---|---|
| `line_down` | downtime opened on a line with published operations in `[now, now + 24 h]` | critical | `line_down:<downtime id>` |
| `late_receipt` | a PO/PR schedule pegged by the published run's MRP run is overdue, or its confirmed date moved later than the planned start of the consuming operation | warning (critical if it delays a frozen op) | `late_receipt:<schedule id>` |
| `scrap_shortfall` | WO can no longer reach its quantity (4.3) | warning (critical if pegged to P1-P2 demand) | `scrap:<wo id>` |
| `overrun` | running op's projected end > planned end + max(`overrun_tolerance_pct` x planned duration, 30 min) | warning | `overrun:<wo op id>` |
| `rush_order` | demand line or WO created/re-prioritised to priority <= 2 due inside the published horizon | warning | `rush:<line or wo id>` |
| `not_started` | planned start + `adherence_tolerance_minutes` passed, op not started | info | `late_start:<wo op id>` |
| `start_short` | op started with component shortage | info | `short:<wo op id>` |

Every trigger creates a notification (workspace-wide, acknowledged once). Policy:
- `notify`: triggers wait for the planner (`POST /replan/run` makes a proposal run from them on demand).
- `auto_whatif`: the first open warning/critical trigger enqueues an APS run `copy_of = published`, `as_of` taken
  at execution, job `run_after = now + replan_debounce_minutes`; later triggers attach to that queued run; if a
  manual run is queued/running, triggers attach after it completes (the job handler re-checks open triggers). The
  proposal is a normal live run labelled `Replan <time>` with `trigger_ids`.
- `auto_publish`: as `auto_whatif`, then the proposal is published if the validator is clean, no frozen operation
  moved except `moved_by_downtime`, and its weighted tardiness <= the published run's (else it stays a proposal
  and a notification says why). Audit action `auto_publish`.

## 8. Simulation (`aps/simulate.py`)

- **Deterministic what-if**: `ApsParams` gains `supply_delays [{schedule_id | wo_id | item_id, days}]` (shifts
  pegged availability) and `line_breakdowns [{line_id, start, hours}]` (as `capacity_overrides close`); kind
  `what_if` (M3 10).
- **Risk run** `POST /aps/simulations {base_run_id, samples (1..50, default 20), seed, horizon_days}`: job kind
  `aps_simulation`. Each sample perturbs the base snapshot: per open PO/PR schedule a delay drawn from that
  supplier's empirical lateness (receipt date - dock date of the last 12 months of `po_receipt` postings; fewer than 5
  receipts -> plant-wide distribution; none -> no delay); per line breakdowns drawn from its downtime history
  (exponential inter-arrival with the observed MTBF, duration resampled from history; no history -> none). Each
  sample runs construction only (M3 7.1, no LNS). Results per demand line: on-time probability, P50/P90 completion;
  per line: expected lost hours; per supplier: contribution to late lines. Deterministic for a given seed.

## 9. KPIs (`mfg/kpi.py`)

Over a period (local days) and dimension (plant / group / line):

| KPI | Definition |
|---|---|
| OTD | demand lines whose full quantity shipped (M2 `ship` postings) on/before due / demand lines due in the period |
| WO on-time | WOs completed (last receipt) on/before due / WOs due in the period |
| Utilisation | (setup + run actual minutes) / base window minutes (M1 `line_windows` base, minus planned downtime) |
| Availability | (window minutes - unplanned downtime minutes) / window minutes |
| Performance | standard minutes of (good + scrap) at the line's rates (M3 4) / actual run minutes |
| First-pass yield | per inspection-gate operation: units good without rework / units entering; plant FPY = product over the gate operations of each routing, weighted by output |
| OEE-lite | availability x performance x FPY |
| WIP | open released/in-progress WOs: count, value (standard cost of issued components + completed output), average age days |
| Setup time | actual setup minutes and changeovers per line; vs planned (published run) |
| Schedule adherence | operations started within `adherence_tolerance_minutes` of planned start **and** completed by planned end + tolerance / operations planned to start in the period (published run at period start) |
| Scrap rate | scrap / (good + scrap) per item family and operation |

Closed days are cached in `mfg_kpi_daily` on first request (`num`/`den` so periods aggregate exactly); today is
always computed live. Dashboard: tiles with trend sparklines (last 8 weeks), drill-down to line/group, top scrap
reasons, top downtime reasons, worst adherence lines.

## 10. Serial capture (boundary with M5)

At `complete` (or `report`) of an operation with `capture_serial` on a serialized item, the event must carry exactly
`qty_good` new serials (scanned `S:` codes or typed; unique per item, 409 `FLR_SERIAL_DUPLICATE`), creating
`mfg_unit_serials` (`wip`, then `in_stock` at the WO receipt). When an operation of a parent WO consumes a
serialized component (its component lines with that `operation_seq`), the event may list the consumed child
serials (`serials.consumed`), which must be `in_stock`/`wip` of that item: they become `consumed` with
`parent_serial_id` set when the parent serial is captured (or the parent WO's id if the parent is not serialized).
`ship` postings of serialized items may list serials (`shipped`). If no operation of a serialized item's routing has
`capture_serial`, serials are captured at the last operation. Unit serial ranges of demand/WOs (M2) are checked
against captured serials (warning `FLR_SERIAL_OUT_OF_RANGE`). `GET /serials/{id}` shows the unit, its WO, its
parent and its direct children (one level). M5: multi-level genealogy, lot genealogy, recall/where-used reports.

## 11. API (`/api/v1/mfg`, `router_m4.py`; numbering continues M3's 199)

| # | Method and path | Body / query | Response | Perm |
|---|---|---|---|---|
| 200 | GET `/floor/scan` | `code` | resolved entity | floor_view |
| 201 | GET `/floor/queue` | `line_id` (required), `shift`, `date` | published dispatch rows + live status, kit status, next actions | floor_view |
| 202 | GET `/floor/operations/{wo_op_id}` | - | operation, WO, instructions (op description), components with kit/backflush status, tools, expected input, events, allowed actions | floor_view |
| 203 | POST `/floor/events` | `FloorEventInput` (`client_event_id` required; replay -> 200 `Idempotent-Replay`) | 201 `{operation, wo, postings[], warnings[], triggers[]}` | floor_report (supervisor-only types: `reopen, correct, skip`, force flags -> floor_supervise) |
| 204 | GET `/floor/events` | `wo_id, line_id, operator_id, type, from, to, limit, offset` | page | floor_view |
| 205 | POST `/floor/backflush/retry` | `{wo_id?}` | results | inventory |
| 206 | GET `/work-orders/{wo_id}/operations` (M3 #176, extended) | - | full operation records | view |
| 207 | POST `/work-orders/{wo_id}/operations/refresh` | If-Match | operations | wo_edit |
| 208-210 | GET/POST `/downtime` (`line_id, open, from, to`); PUT `/downtime/{downtime_id}` (close, expected end, reason) | | records | view / downtime_report |
| 211-213 | GET/POST `/batch-loads`; GET `/batch-loads/{load_id}` | `{line_id, members[{wo_operation_id, qty}]}` | records | floor_view / floor_report |
| 214-215 | GET `/serials` (`item_id, q, status, wo_id`); GET `/serials/{serial_id}` | | page / unit with one-level links | view |
| 216-218 | GET `/replan/triggers` (`status, kind`); POST `/replan/triggers/{trigger_id}/ignore` \| `/handle` | `{note}` | page / record | view / replan_manage |
| 219 | POST `/replan/run` | `{trigger_ids?}` | 202 APS run (copy of published) | schedule_run |
| 220-221 | GET `/notifications` (`unacked`, `limit`); POST `/notifications/{notification_id}/ack` | | page / record | view |
| 222 | GET `/kpis` | `from, to, dim (plant\|group\|line), dim_id, bucket (day\|week)` | `{metrics: {otd, wo_on_time, ...}, series, top_scrap, top_downtime}` | view |
| 223 | GET `/kpis/adherence` | `from, to, line_id` | per-operation planned vs actual rows | view |
| 224-226 | POST `/aps/simulations`; GET `/aps/simulations/{simulation_id}`; GET `/aps/simulations` | | 202 / record with results / page | schedule_run / view |

M3 #177/#178 (`done`/`reopen`) become supervisor shortcuts (perm `floor_supervise`): `done` = `complete` with
`qty_good = available input`. `PUT /plant`, lines, items, operations, operators accept the 3.1 fields. `ApsParams`
gains `supply_delays`, `line_breakdowns`; run results gain `batches` and per-operation `actual` (status, actual
start). `GET /summary` gains `floor {running_ops, lines_down, open_triggers, pending_backflush}`.

`FloorEventInput`: `{client_event_id: str 8..64, wo_operation_id | scan, event_type, event_at?, line_id?,
operator_ids? (or operator_codes from badge scans), qty_good?, qty_scrap?, qty_rework?, rework_to_seq?,
reason_code?, note?, batch_load_id?, serials? {produced: [str], consumed: [{item_id, serial}]}, force?:
{reason}}`.

Errors (in addition to M1-M3): 409 `FLR_INVALID_TRANSITION` (`details.status, event, allowed`),
`FLR_LINE_DOWN`, `WO_KIT_INCOMPLETE`, `FLR_SERIAL_DUPLICATE`, `APS_SIMULATION_IN_PROGRESS`; 422
`FLR_LINE_NOT_ELIGIBLE`, `FLR_QTY_EXCEEDS_INPUT`, `FLR_TIME_INVALID`, `FLR_SERIALS_REQUIRED` (count != good qty),
`FLR_SERIAL_NOT_AVAILABLE`, `FLR_NO_RECEIPT_LOCATION`, `FLR_REASON_REQUIRED`, `FLR_OPERATOR_UNKNOWN`; 404
`FLR_SCAN_UNKNOWN`.

**Roles and permissions** (M2 10.2 + M3): new roles `operator` and `supervisor`. New permissions:
`floor_view` (all roles), `floor_report` (operator, supervisor, owner, planner), `floor_supervise` (supervisor,
owner), `downtime_report` (operator, supervisor, owner, planner), `replan_manage` (owner, planner). Operators see
only `/mfg/floor/**` and read pages; station accounts are ordinary `operator` members. `MFG_PERMISSIONS` gains the
27 routes (226 total).

## 12. UI

**Floor (`/mfg/floor`, tablet-first: >= 48 px targets, one column, scan field always focused, works at 1024x768):**
line picker (remembered per device) -> **queue** of the line (current shift, published order, live status, kit
light) -> **operation screen** (big Start/Pause/Resume/Complete, quantity pad for good/scrap/rework with reason
codes, operator badges on the event, serial capture list, components/backflush status, instructions, tools) ->
**downtime** button (kind, reason, expected end) -> **batch load** screen for batch lines. Offline tolerance: actions
are queued in `localStorage` with their `client_event_id` and retried in order when the network returns (replay is
idempotent); the screen shows "3 actions waiting to sync".

**Supervisor/planner pages:** `/mfg/floor/overview` (all lines: running/paused/down, current op, delay vs plan),
`/mfg/floor/events` (log with correct/reopen/skip), `/mfg/replan` (triggers, notifications, proposals vs published
compare, publish), `/mfg/kpis` (dashboard), `/mfg/serials` and `/mfg/serials/:id`, `/mfg/schedule/simulations` and
`/:id` (risk table, histogram per demand line), traveller/label print pages `/mfg/print/traveller/:woId`,
`/mfg/print/labels?...`. Gantt (M3) shows actual bars under planned bars, downtime bands and batch loads. Header
bell with unacknowledged notifications.

Test ids (C publishes the rest in 16): `floor-scan`, `floor-line-pick`, `floor-queue-row` (`data-status`),
`floor-action-{setup_start|start|pause|resume|complete}`, `floor-qty-{good|scrap|rework}`, `floor-reason`,
`floor-serial-input`, `floor-sync-pending`, `downtime-open`, `downtime-close`, `trigger-row` (`data-kind`),
`notif-bell` (`data-count`), `kpi-tile-{otd|util|oee|wip|setup|adherence|fpy}`, `sim-row` (`data-p-on-time`).

## 13. Delivery plan (lean)

| WP | Role | Owns |
|---|---|---|
| **S** backend | one backend developer | `sp/mfg/model_m4.py`, `floor.py`, `scan.py`, `replan.py`, `kpi.py`, `aps/actuals.py`, `aps/batching.py`, `aps/simulate.py` (+ hooks in `aps/build.py`, `construct.py`, `validator.py` for actuals and loads), master-field changes (`model.py`, `bundle.py`/`io`), `samples` (M4 part), `sp/api/mfg/db_models_m4.py`, `repo_m4.py`, `services/{floor,downtime,replan,kpi,serials}.py`, `router_m4.py`, edits to `services/{workorders,aps,items,plant,resources,routings}.py`, `jobs/*` (kind `aps_simulation`), migration `0006_mfg_m4`, `migrate.py`, registrations, `tests/floor/**`, `tests/api_mfg_m4/**`, the existing-test edits of 13.1 |
| **U** UI | one ui-developer | `frontend/src/mfg/**` (incl. `floor/**`), `frontend/e2e/m4-floor.spec.ts` (+ helper additions) |
| LEAD | team lead | this document, S0 review, final gate |

Milestones: **S0 (day 1, contract freeze)** - `model_m4.py`, field additions, migration + up/down test, all 27
routes live with permissions, answering from `backend/superplanner/mfg/floor/fixtures/example_floor.json` where not
yet real; U writes `contractExamplesM4.ts` from it and starts. **S1** operations + event engine + effects (receipt,
backflush, rework, serials) + scan. **S2** downtime, APS actuals, batching, replan triggers/policy/notifications.
**S3** KPIs, simulation, sample, performance. **U1** floor pages (queue, operation, downtime, scan, offline queue),
**U2** supervisor overview/events, replan, notifications, Gantt actuals, **U3** KPIs, serials, simulation, print pages,
master fields, the e2e spec.

### 13.1 Existing code and tests touched

M2 `services/workorders.py` (release, operations), M3 #176-178 behaviour, APS snapshot/construct/validator hooks,
`jobs/*` + `api/db` (new kind and target column: the final gate needs the full backend run), item/line/operation/
operator/plant services and import sheets. Existing tests changed only: golden sample hashes and counts, statement
bounds where `load_dataset` grows, route/permission tables (+27) and the authz sweep `id_map` (`wo_op_id`,
`downtime_id`, `load_id`, `serial_id`, `trigger_id`, `notification_id`, `simulation_id`), M3 progress tests rewritten
against the event-backed shortcuts, migration head/table-set tests, job-kind lists.

## 14. Sample, performance, testing, acceptance

**Kavach M4 sample** (deterministic, anchor as M2/M3): no operator-user links (station accounts are created by
the customer); `capture_serial` on KV-TPU-1000 final
test and on each PCB's ICT; passives `issue_method backflush` from `LS-SMT`; BURNIN and CURE lines `batch_merge`;
event history for 10 working days before the anchor (generated from the M3 schedule with seeded deviations:
overruns on SMT, 3% scrap at ICT, two rework loops, one SMT-2 breakdown of 5 h, two late PO receipts) so KPIs,
adherence, risk-run distributions and triggers have content. Intended: dashboard OTD < 100% with DO-KV-003, SMT-2
availability visibly lower, ICT FPY ~97%, one open `late_receipt` trigger, risk run shows the FPGA supplier as top
contributor. Pinned at implementation.

| # | Case | Target |
|---|---|---|
| FP1 | `POST /floor/events` (start/report/complete incl. auto receipt, backflush of 30 components, trigger rules) | p95 < 150 ms; simple start/pause < 60 ms |
| FP2 | 60 tablets x 1 event / 10 s for 10 min (mixed lines) | no errors, p95 < 250 ms, no lock timeouts |
| FP3 | `GET /floor/queue` / `scan` | < 100 ms / < 50 ms |
| FP4 | replan proposal run, Kavach with actuals | as M3 AP5 (< 45 s) |
| FP5 | APS construction with batching on, Kavach | <= 1.2 x M3 AP1 |
| FP6 | risk run 20 samples, Kavach | < 120 s |
| FP7 | `GET /kpis` 30 days plant + per line (cached days) / first uncached 30 days | < 0.5 s / < 3 s |
| FP8 | event log 1,000,000 events: op state recompute | < 20 ms per operation (index `wo_operation_id, seq`) |

**Testing during work:** tests are written with the code; only touched tests and the package folders run
(`.venv/bin/pytest tests/floor -q`, `tests/api_mfg_m4 -q`, named existing tests of 13.1); UI `npm run build` and the
single `m4-floor.spec.ts` when it is being written. **Final gate (once, LEAD):** full backend suite on PostgreSQL incl.
`-m slow`; `m4-floor.spec.ts` plus the M3 Gantt spec (no other browser suites unless a shared frontend file
changed); build/audit; migration 0005 -> 0006 on a populated database (incl. M3 progress rows) and downgrade. Fixes
use targeted reruns only, unless they touch `api/db`, `api/auth`, migrations or `jobs`.

**Test vectors (`tests/floor`, pure):**

| # | Case | Expected |
|---|---|---|
| T-F1 | op qty_planned 100: start, report good 40 scrap 2, pause 30 min, resume, complete good 55 scrap 3 | good 95, scrap 5, yield 0.95, run minutes exclude the pause |
| T-F2 | good 96 + scrap 5 on input 100 | 422 `FLR_QTY_EXCEEDS_INPUT`; supervisor force accepted with reason |
| T-F3 | rework 4 from op 40 to op 20 (op 20 completed) | op 20 paused with `rework_in 4`; op 30/40 inputs follow |
| T-F4 | last op complete good 10 | one `wo_receipt` 10 to the WO receipt location; WO completed at qty 10 |
| T-F5 | backflush 4 x 10 units, only 30 available | event accepted, no posting, `FLR_BACKFLUSH_PENDING`; after a receipt, retry posts 40 |
| T-F6 | same `client_event_id` twice | second is a replay, no duplicate posting |
| T-F7 | serialized op capture: good 3 with 2 serials | 422 `FLR_SERIALS_REQUIRED`; with 3 -> serials `wip`, `in_stock` after receipt; parent consumes one -> `consumed` + parent link |
| T-F8 | reopen completed last op | reversal of the receipt; WO back to in_progress |
| T-F9 | downtime open on SMT-2 with frozen ops in the next 6 h | APS proposal moves them (`moved_by_downtime`), validator clean |
| T-F10 | running op, planned 300 min, started 280 min ago, reported 50% | remaining 150 min from as_of; overrun trigger when projected end > plan + max(20%, 30 min) |
| T-F11 | batching: two TPU WOs of 5 and 3 units, burn-in batch 8 | one load of 8 at the later ready time (wait <= `batch_wait_minutes`), else two loads |
| T-F12 | `auto_whatif`: 3 triggers within 10 min, debounce 15 | one queued APS run with all 3 attached |
| T-F13 | `auto_publish` proposal worse than published | not published; notification explains |
| T-F14 | KPI: 10 ops, 7 started within tolerance and done by plan end | adherence 0.7; FPY and OEE match hand values |
| T-F15 | risk run with a supplier history of +0/+7/+14 days, seed fixed | identical results on rerun; on-time probabilities as hand-computed for a 1-op plant |

**Acceptance (Gate 4):**
1. Floor journey (browser, tablet viewport): scan traveller -> start -> report scrap -> pause/resume -> complete
   with serials -> stock and WO status updated; offline actions sync once.
2. Ledger integrity after a scripted shift with backflush, receipts, rework, reversals: M2 acceptance #5 invariants
   still hold; no negative stock; pending backflush listed and cleared on retry.
3. Event log rebuild: recomputing every operation from events equals stored state for the whole sample history.
4. Replanning: line-down, late receipt, scrap shortfall, overrun and rush order each raise exactly one trigger and a
   notification; `notify` creates no run; `auto_whatif` creates one debounced proposal; `auto_publish` publishes only
   under 7's conditions; frozen operations stay except downtime moves; every proposal passes the validator.
5. APS with actuals: completed work absent, running fixed, downtime respected, batches valid (validator checks load
   compatibility and capacity).
6. KPIs equal hand calculations on a 2-day fixture; dashboard numbers equal the API.
7. Simulation deterministic per seed; risk run of the sample identifies the intended top supplier.
8. Roles: operator can only use floor endpoints and reads; supervisor corrections audited with actor and operator;
   station account + badge scan records both.
9. Migration of M3 progress rows; performance FP1-FP8; full backend suite green once.

## 15. Questions for the product owner

Decided by LEAD 2026-10-31 (product owner delegated these; all are configuration, changeable per plant without code):

1. **Q1 Floor devices and logins — both supported.** Default: shared station login per line + operator badge scan
   per action (badge cards printable from M4). Personal sign-in works as well (an operator linked to a user needs no
   badge scan).
2. **Q2 Backflush — per-item flag, default off.** The Kavach sample marks SMT passives on line-side reels, wire,
   sleeving and labels as backflushed; everything else is issued by stores. HBL sets the flag per item (UI or import).
3. **Q3 Serial points and labels — per-routing-operation flag.** Kavach sample: PCB serial at ICT, TPU/unit serial at
   final test. Labels print from the browser; an existing labelling system can keep printing and its serials are
   scanned in instead (manual/scan entry is always allowed).

## 16. Implementation notes

### 16.WP-S Backend

**S0 frozen (2026-10-31).** Contract: `backend/superplanner/mfg/model_m4.py` (all request/response shapes of 11),
`ApsParams.supply_delays / line_breakdowns` (`mfg/aps/model.py`), the 3.1 master fields on `mfg/model.py`
(`PlantInput`, `ItemInput.issue_method`, `OperationInput.capture_serial`, `LineInput.location_id / batch_merge /
batch_wait_minutes`, `OperatorInput.user_id`), `WorkOrderInput.receipt_location_id`, `ReleaseWoRequest.override_reason`.
Typed examples: `backend/superplanner/mfg/floor/fixtures/example_floor.json` (built and validated by
`build_example.py` next to it; `tests/api_mfg_m4/test_m4_s0_contract.py` re-validates every example). Migration
`0006_mfg_m4` (`migrate.HEAD`), up/down tested incl. M3 progress rows. All routes are live with their permissions;
routes not yet real answer from the fixture (marked in the services as S0 stubs).

S0 interpretations / deviations:
1. **Route count: 26 new operations, 225 in total** (not 27 / 226): #206 is M3's #176 extended and stays the same
   operation (`GET /work-orders/{wo_id}/operations`), so 200-226 minus #206 = 26 new. `MFG_PERMISSIONS` = 225.
2. `mfg/floor.py` became the package `mfg/floor/` (`engine.py` = the pure rules of 4.2) because 13 places the fixture
   at `mfg/floor/fixtures/`; `mfg/scan.py` as designed.
3. `GET /work-orders/{id}/operations` items are `WoOperationRecord` (`model_m4`): every M3 field is kept
   (`seq, name, group, setup_minutes, run_minutes, labor, done, done_at, done_by, placement`; `done` = completed or
   skipped) plus the full record (`id, status, qty_*, line, actual_*`, ...). A WO without operation rows (planned)
   lists its routing operations as `pending` with `id = ""`.
4. Floor event replay returns 200 with `Idempotent-Replay: true` (the event and the current operation state); a new
   event returns 201.
5. `FloorEventInput` also takes `corrects_event_id` (needed by `correct`; it alone identifies the operation).
   `operator_codes` accept `OP:<code>` or the bare code.
6. Extra error codes: 409 `WO_HAS_FLOOR_EVENTS` (refresh after events), 422 `FLR_LOAD_INCOMPATIBLE`,
   `FLR_LOAD_OVER_CAPACITY`, 409 `FLR_LOAD_MEMBER_BUSY`; warnings `FLR_PREDECESSOR_OPEN`, `FLR_STARTED_SHORT`.
7. `mfg_kpi_daily.dim_id` is `""` for the plant (not NULL) so the unique key holds; `mfg_wo_operations` has two extra
   columns: `effects` JSON (cumulative receipts / backflush / scrap booked per operation, so partial reports never
   double-post and reopen/corrections can reverse) and `completed_at/completed_by` (M3 `done_at/done_by`);
   `mfg_floor_events` has `forced` (S200) and `details` (JSON); `mfg_unit_serials.event_id`;
   `mfg_replan_triggers.note`; `mfg_aps_simulations` has `error, cancel_requested, actor_id, started_at,
   finished_at, duration_ms` (run conventions).
8. Migration of M3 progress: completed rows get `qty_planned = qty_good =` the WO quantity, `actual_end = done_at`,
   and one synthetic `complete` event each (`details.migrated`) so the event log stays the only truth (F1,
   acceptance 3). The routing is the WO's own, else the item's released routing effective at the start date
   (lowest priority, newest version; serial effectivity ignored in SQL). Downgrade writes completed/skipped
   operations back as progress rows.


**S1-S3 implementation notes (WP-S).**
9. `mfg_items.issue_method` is S16 (not S8): `backflush` has 9 characters. New NOT NULL ORM columns carry Python-side
   defaults (no server defaults) so older ORM writers keep working.
10. Event rules: `event_at` never in the future (2 min slack); operators backdate <= 24 h; nothing earlier than the
    WO's first actual start. `FLR_PREDECESSOR_OPEN` is a warning (F2), never a refusal; the quantity check is
    consumed (good + scrap + rework sent back) <= input (predecessor good, first op `qty_planned`, + rework received);
    supervisors force it with `force.reason`. A skipped operation passes its input through. `correct` replaces the
    fields it carries on the referenced event (`event_at` only when given); `ready` is computed (`pending` with the
    predecessor completed or its transfer batch reached). Labour minutes = interval minutes x operators recorded on
    the event that opened the interval; a station login without badge scans records 0 operators, a personal login
    the linked operator.
11. Effects: scrap of every operation is booked on `work_orders.qty_scrapped` directly (the receipt line carries no
    `scrap_qty`); the receipt of lot-controlled output goes into the lot named after the WO number; `reopen` of the
    last operation reverses its receipts (WO back to in progress) - backflush issues are not reversed (the material
    was consumed); a correction below the received quantity reverses all receipts of the operation and re-posts the
    new total. A pending backflush of a WO that completed meanwhile is still posted by the retry. Effects run only for
    report / complete / correct / reopen.
12. Release (4.1): the first-operation kit check runs inside the M2 release action. **This changes M2 behaviour**:
    releasing with a shortage now needs `override_reason`; `tests/api_mfg_m2/test_m2_documents_api.py` was updated;
    `tests/acceptance_m2/test_acc_m2_08_wo_loop.py` (two tests, tester-owned) still release short WOs without a
    reason and fail until LEAD/the tester adopt 4.1.
13. M3 `/done` = `start` (if pending) + `complete` with the available input; one WO version step per shortcut.
    Sample progress (M3 `PROGRESS`) is written as `complete` events marked `details.sample`.
14. APS actuals (6.1): running / setup / paused operations replace their published placement and are placed first
    on their line from as_of with the remaining quantity (`frozen = true`, reason `in_progress`, `actual` on the op);
    open downtime without an end closes the line until as_of + 4 h; the validator re-derives closures,
    superseded and downtime-moved placements from the snapshot. The `FLR_DOWNTIME_NO_END` exception is not emitted
    as an APS exception (only the 4 h rule applies). Summary gains `actual_ops, moved_by_downtime, frozen_moved,
    batches`; ops gain `actual`, `moved_by_downtime` (`mfg_aps_ops` columns in 0006).
15. Batching (6.3): only single-load operations (qty <= units per batch) without crew/tools share loads; a member
    joins a load that starts within its earliest start + the line's `batch_wait_minutes`; a partial load waits (same
    limit) for compatible operations whose predecessors are placed. Shared-load placements are fixed for LNS
    (`fixed = batch`). Loads are derived from the result (same line / start / end on a `batch_merge` line) and
    stored in `run.extras.batches`; the validator counts a compatible load once for line capacity.
16. Replan: the proposal is a live run of the published run's parameters (not `copy_of`, so `as_of` is taken when
    it executes); debounce = the job's `run_after` (inline backend: a timer before dispatch). The time-based rules
    (`not_started`, `late_receipt` via the published ops' release refs) run at most once a minute per workspace, in
    the background for `GET /notifications` (the bell polls every page) and inline for `GET /replan/triggers`.
    `overrun` uses the APS projection (remaining quantity at the planned rate) on `report` events; `rush_order`
    runs on WO create / priority change and demand order create / update. `after_run` re-checks open triggers
    after every APS run.
17. KPIs: work intervals come from the event log; availability counts unplanned downtime inside base windows
    (planned downtime is removed from the window); performance = standard minutes of reported units / running
    minutes; FPY of inspection-gate operations = good / (good + scrap + rework sent back) of their reports; OTD and
    WO on-time are plant-level only. Days are cached once closed (a `_computed` marker row per day).
18. Risk run: one unperturbed base construction gives `base_end`; results carry per demand line
    `samples_late_minutes` (histogram) and per supplier `late_lines` (late demand lines of samples in which one of
    its delayed schedules is pegged to the line's orders, one level).
19. UI gaps closed: `POST /downtime` honours `Idempotency-Key` (`mfg_downtime.idempotency_key`, replay 200 +
    `Idempotent-Replay`); Gantt bars carry `actual` (live floor state), `load_no`, `moved_by_downtime`, bands kind
    `downtime`, response `batches`; `GET /floor/operations/{id}` carries `reason_codes` {pause, scrap, rework}
    (defaults in `model_m4.DEFAULT_REASON_CODES`, plant attribute `floor_reasons_<kind>` = "CODE:Label,..."
    overrides); batch-load scans carry `context.line_id`.
20. Not done in WP-S: the Kavach M4 sample (flags + 10-day event history) and FP2 (60-tablet load) / FP8 (1 M events)
    measurements.

### 16.WP-U UI

**Built (2026-10-31), types aligned to the S0 fixture, journey verified against the S1 engine.**

Screens:
- **U1 floor (tablet, `/mfg/floor`, own shell without the planning nav):**
  - Scan field always focused. Keys typed outside a text field go to it; focus returns after button presses.
  - Pages can claim scans first (the quantity panel takes `S:` / unknown codes as serials); otherwise #200
    opens the operation, work order, line or batch load, or signs in an operator badge.
  - Station login: badges (`OP:<code>`) are kept on the device for one long shift and sent as `operator_ids` /
    `operator_codes` with every action. A personal login linked to an operator needs none (15 Q1).
  - Line picker, remembered per device and workspace.
  - Queue with status and kit shown as icon + text, plan times and "behind" minutes. Rows without a WO
    operation (`wo_operation_id = null`, not released) are not tappable.
  - Operation screen:
    - 72 px Start setup / Start / Pause / Resume / Report / Complete from `allowed_actions`.
    - Glove-size quantity steppers with reason and rework-to selectors.
    - Serial capture: one per good unit, enforced before submit; child serials scanned as `consumed`.
    - Components with backflush status, instructions, tools, the event list, and "it happened earlier" backdating.
    - Supervisor force reason on `FLR_QTY_EXCEEDS_INPUT`.
  - Downtime in three taps (kind, reason, expected back: quick picks / not known / a time); "Line back up"
    uses `close: true`.
  - Batch loads: build from waiting operations; start/complete with `batch_load_id` only.
  - Offline queue (`floor/offlineQueue.ts`, localStorage per workspace):
    - Actions keep their `client_event_id` and replay in order.
    - Rejections move to "needs attention" with the server's message.
    - The header shows "N actions waiting to sync".
- **U2 supervisor and planning:**
  - `/mfg/floor/overview`: all lines, state, current operation, behind/on plan, next operation's kit; one #201
    per active line every 30 s.
  - `/mfg/floor/events`: filters; correct (a `correct` event, original kept) and reopen.
  - WO operations section (M4 records): Done / Skip for supervisors, re-derive while nothing is recorded,
    traveller and event-log links. It falls back to the M3 `done` view on M3 servers.
  - `/mfg/replan`: plant policy explained, triggers (select, handled / ignore with a note), "Make a proposal" =
    #219, then compare with the published run. Also proposals and notifications.
  - Header bell (`notif-bell`, count also as text), polled every minute.
  - Gantt: an actual bar under the planned one (arrow = still running), "DOWN" bands, and batch brackets
    "B3 (2)". Zooming keeps the selected bar in view.
- **U3:**
  - `/mfg/kpis`: seven tiles, each with a plain definition and an 8-week sparkline (`bucket=week`). Drill-down
    by stage/line, top scrap and downtime, lines furthest from the plan, and the per-operation adherence list
    for a line.
  - `/mfg/serials` and `/:id`: one level, parent / children / `consumed_by_wo`, print label.
  - `/mfg/schedule/simulations` and `/:id`: guided defaults (published plan, 20 replays), seed/horizon as
    expert settings. Risk table (`sim-row data-p-on-time`), "spread" per line, suppliers and lines.
  - Print pages: `/mfg/print/traveller/:woId` (WO + `WO-n/seq` per operation) and
    `/mfg/print/labels?type=lot|serial|badge|line&ids=`.
  - Code 128 is our own encoder (`lib/code128.ts`, B with C for digit runs), drawn as SVG and checked against
    the published example (`PJJ123C` checksum 55).
- **Master fields:** item "Backflush from the line", routing operation "Capture serial numbers here", line
  "Line-side stock location" / "Combine orders into batch loads" / wait, operator "Personal login" (members
  list), plant "Shop floor and replanning" (policy; receipt and backflush locations; tolerances under expert
  settings). Fields are sent back only when the server returned them.
- **Release with kit check:** on 409 `WO_KIT_INCOMPLETE` the shortage list is shown and "Release anyway" needs a
  reason (`override_reason`).
- **Home:** "Shop floor" card from `summary.floor`. The schedule page links "Delivery risk".

Interpretations:
- The server's scan `link` for operations is `/mfg/floor/operations/:id`; both that and `/mfg/floor/ops/:id`
  route to the operation screen.
- Planned-WO operations with `id = ""` (16.WP-S 3) are shown without floor actions.
- `ConfirmDialog` gained an optional `confirmDisabled` (shared component, additive).

Requested from WP-S (none blocking):
1. Idempotency on `POST /downtime`. An offline "line down" replays from the device, and without a key a lost
   response could create a second downtime. The UI already sends `Idempotency-Key`.
2. #202 `reason_codes` (pause/scrap/rework lists of the plant). The UI uses sensible defaults until then.
3. Gantt bars with `actual`, downtime bands and `batches` (11, "run results gain"). The UI draws them as soon
   as `gantt` returns them, accepting `start/end` or `actual_start/actual_end`.
4. Optional `samples_late_minutes` per demand line in simulation results, for a true histogram. The UI shows a
   due / plan / P50 / P90 strip without it.
5. A `line_id` in the batch-load scan context. Otherwise the tablet's current line is used.

Test ids added (beyond 12):
- `floor-shell`, `floor-crew` (data-count), `floor-flash`, `floor-line-title`, `floor-queue`, `floor-op`
  (data-status, data-seq), `floor-op-good` (data-good / data-scrap), `floor-qty-panel`, `floor-qty-submit`,
  `floor-serial-count`, `floor-pause-submit`, `floor-force-reason`, `floor-sync-list`, `floor-sync-failed`,
  `downtime-kind-*`, `downtime-submit`, `floor-batch-*`.
- `overview-line`, `floor-event-row`, `event-correct`, `event-reopen`, `trigger-handle/ignore`, `replan-run`,
  `notif-item`, `notif-ack`, `kpi-scope`, `serial-row`, `sim-start`, `traveller-op`, `label`,
  `wo-kit-incomplete`, `wo-release-override`, `op-skip`, `wo-print-traveller`, `print-badges`,
  `item-backflush`, `op-capture-serial`, `line-batch-merge`, `plant-replan-policy`, `gantt-tooltip-actual`.

e2e: `frontend/e2e/m4-floor.spec.ts` (tablet 1024x768, acceptance 1).
- Setup through the API: `small`, SM-100 made serialized, one WO of 4 with a receipt location, released.
- Covers line pick, badge scan, traveller scan, start, report with scrap and reason, pause/resume, complete,
  then an offline start that syncs once (one `start` event on the server). The last operation completes with
  one serial per good unit; the WO's `qty_completed` and the captured serials are checked.
