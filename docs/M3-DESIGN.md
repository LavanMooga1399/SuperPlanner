# SuperPlanner M3 - Finite-capacity production scheduling (APS) (design + plan + acceptance)

Status: design for build. Phase M3 of `docs/MANUFACTURING-GAP-ANALYSIS.md` ("GA"). Builds on M1 master data
(`docs/M1-DESIGN.md`, "M1 n") and M2 inventory/MRP/work orders as built (`docs/M2-DESIGN.md`, "M2 n", incl. 22).
M1/M2 conventions (pure package + thin API, owned tables, If-Match, error envelope, audit on every write, workspaces
and permissions, import pipeline, lock order, determinism) apply unchanged and are not restated. Interpretations go
to section 17 only.

User intent: parts have one or more stages per part type, some repeated (SMT top/bottom); item- and
quantity-dependent times; each stage has several lines loaded by urgency and load; shifts regular 09:00-18:00,
extended to 22:00, 24 h, some stages only in some shifts; overtime; one whole-plant plan across all demand orders,
"like a real production planner".

## 0. Decisions

1. **Dedicated manufacturing scheduler `superplanner/mfg/aps` (pure), not a bridge to `superplanner/engine`.**
   The generic engine cannot express what M3 needs: operations that pause at shift ends and resume
   (`interruptible`), sequence-dependent setups, optional (overtime) windows as decisions, lot splitting across
   lines, crews of individual operators with absences, tooling pools, cross-order material links. It also caps at
   2,000 tasks and uses CP-SAT only up to 300. Bending its core would put the scheduling area and its tests at risk.
   Reused: OR-Tools CP-SAT (already pinned), the engine's *design* (construct -> improve -> independent validator
   -> explanations), M1 `calendar.line_windows`/`operator_windows`, `routing.operation_minutes`/`lot_inputs`/
   `eligible_lines`, M2 pegging, the PostgreSQL job queue. The GA is not used (GA 3: little gain at this size).
2. **Algorithm:** deterministic priority-driven construction (serial schedule generation over real calendars, line
   choice by earliest finish incl. setup, lot splitting for critical operations, overtime opening by policy),
   then **LNS with CP-SAT** on bottleneck-group time windows under a deterministic time budget, accepting only
   validator-clean improvements. Objective is **lexicographic**: hard feasibility -> priority-weighted tardiness ->
   overtime cost -> WIP (order flow time) -> makespan -> setup minutes.
3. **Material is a hard constraint.** An operation that consumes components cannot start before they are
   available: stock now, PO/PR schedule `available_date`, or the scheduled end of the child work order that
   supplies them, taken from the **pegging of an M2 MRP run** (default: latest completed live run). No supply ->
   the operation is not scheduled and reported (never placed on an invented date).
4. **A schedule run is an immutable, versioned snapshot** (like MRP runs), run **asynchronously** as job kind
   `aps_run` on the existing PostgreSQL queue (progress by polling). One run may be **published** = the plant plan
   (dispatch lists, freeze, MRP feedback). Manual drags/resequencing create a **child run** (synchronous repair +
   full validation); nothing is edited in place.
5. **Overtime policy per run:** `off` (base shifts only), `suggest` (plan on base; report which optional windows
   would remove how much tardiness), `allow` (the scheduler opens optional shift instances when an operation would
   otherwise be late, within `max_hours_per_week`, cost counted). Planner overrides force-open or close capacity.
6. **Freeze window** (`plant.aps_freeze_hours`, default 48): operations of the published run starting before
   `as_of + freeze` stay where they are; operations in progress at `as_of` are fixed.
7. **Deferred items carried in:** IANA time zones (`plant.time_zone`, replaces the fixed offset for computation),
   line-specific operation times, sequence-dependent setup matrices, operator absences: **M3**. Cross-order batch
   merging (two WOs in one oven load): **M4** - parallel slots (`parallel_capacity`) already let several WOs'
   batches run in one oven/burn-in rack concurrently; physical load merging changes WO flow and needs actuals.
8. **Lean delivery:** two packages (WP-S backend, WP-U UI + e2e), contract frozen on day 1, tests written with the
   code, targeted runs only, one final full gate run (section 15).

## 1. Scope

**In M3:** IANA time zone; line-specific times; setup matrices; operator absences; WO operation progress markers
(done/open, the minimum needed until M4 actuals); scheduling of released/in-progress/firm WOs and MRP planned make
orders over a rolling horizon; line choice, lot splitting, overtime policy, crews, tooling, material constraints;
freeze, locks, manual edits; validator; explanations and bottlenecks; Gantt by line / WO / demand order; capacity
load (scheduled and MRP-required) per stage/line; dispatch lists per line and shift; KPIs; what-if and compare;
publish; MRP using the published schedule dates; Kavach M3 sample; roles; API; UI.

**Out (M4+):** shop-floor actuals (start/finish/qty/scrap), event-driven automatic replanning, cross-order batch
merging, rework loops, operator skill levels and preferences, tool maintenance calendars, multi-plant.

**Principles** (in addition to M1 P1-P6, M2 P7-P11): S1 hard constraints are never penalties - a plan with a
validator violation is `infeasible`, shown but not publishable; S2 every operation start has a recorded reason;
S3 deterministic: same inputs + params -> same schedule (CP-SAT with one worker and a *deterministic* time limit;
a wall-clock safety cap that cuts LNS short is recorded in the run summary).

## 2. Package layout (ownership in 14)

```
backend/superplanner/mfg/
  tz.py              plant_tz(plant) -> tzinfo; plant_today(plant); local <-> UTC helpers (5)
  calendar.py        line_windows / operator_windows take a tzinfo (5); absences subtracted from operator windows
  model.py           PlantInput + time_zone, aps_* settings (3.1)
  model_m3.py        OperationLineRate, SetupMatrixRow, OperatorAbsence, WoOpProgress inputs/records (3)
  aps/
    model.py         ApsParams, ApsSnapshot, ApsResult and parts (6.1)       [frozen at S0]
    build.py         snapshot -> jobs/operations/resources/release times (6.2-6.4)
    durations.py     operation duration on a line incl. line rates and setups (6.3)
    construct.py     priority-driven construction (7.1)
    lns.py           CP-SAT neighbourhoods (7.2)
    validator.py     independent validator (7.4)
    explain.py       start reasons, late chains, bottlenecks (8)
    views.py         gantt rows, load, dispatch, KPIs, compare (9)
backend/superplanner/api/mfg/
  db_models_m3.py repo_m3.py services/aps.py services/aps_master.py aps_store.py router_m3.py   (+ jobs handler)
frontend/src/mfg/  schedule pages and components (12)
```
`superplanner.mfg.aps` imports only `superplanner.mfg` and `ortools`; never `superplanner.engine` or `api`.

## 3. Master and transactional data additions

### 3.1 Plant (M1 3.3 + M2 3.1)

| Field | Type | Default | Meaning |
|---|---|---|---|
| `time_zone` | IANA name \| None | None | e.g. `Asia/Kolkata`; validated with `zoneinfo.ZoneInfo` (422 `MFG_TZ_INVALID`). When set it is used for **all** local-time computation and `utc_offset` becomes read-only display (the current offset); None keeps the M1 fixed offset |
| `aps_freeze_hours` | int 0..336 | 48 | freeze window (6.6) |
| `aps_horizon_days` | int 7..120 | 42 | default detailed horizon |
| `aps_overtime_policy` | `off` \| `suggest` \| `allow` | `suggest` | default for runs |

### 3.2 New master tables (master data: plant lock, `data_version`, fingerprint, import sheets)

| Entity | Fields | Rules |
|---|---|---|
| `OperationLineRate` (`olr_`) | `operation_id`, `line_id`, `setup_minutes: Minutes \| None`, `run_minutes: Minutes \| None`, `note` | line of the operation's group (422 `MFG_LINE_NOT_IN_GROUP`); unique per (operation, line); None = use the operation's value. An overriding `run_minutes` is that line's own rate: the line `speed_factor` is **not** applied to it |
| `SetupMatrixRow` (`stm_`) | `line_setup_family: Code` (a lines' `setup_family`), `from_family: Code \| "*"`, `to_family: Code \| "*"`, `setup_minutes: Minutes` | unique per (line family, from, to); most specific row wins: (from,to) > (from,*) > (*,to) > (*,*) |
| `OperatorAbsence` (`oab_`) | `operator_id`, `start`, `end` (aware, `start < end`, <= 366 days), `kind: leave\|training\|sick\|other`, `note` | removed from the operator's windows |

Import sheets (M1 8.2 style): `operation_line_rates` (**part_number, revision, code, version, seq, line_code**,
setup_minutes, run_minutes, note), `setup_matrix` (**line_setup_family, from_family, to_family**, setup_minutes),
`operator_absences` (**operator_code, start**, end, kind, note). Health additions: `MFG_RATE_LINE_INELIGIBLE`
(warning: rate for a line not eligible for the item), `MFG_TZ_NOT_SET` (info: plant without `time_zone`).

### 3.3 WO operation progress (transactional)

`mfg_wo_op_progress (wo_id, seq, done Bool, done_at, done_by)`: `POST /work-orders/{id}/operations/{seq}/done` and
`/reopen` (perm `wo_edit`, If-Match on the WO). WO operations are always derived from the WO's `routing_id` (M2 3.7)
at schedule time; progress rows only mark finished operations (actual times are M4). `GET /work-orders/{id}/
operations` returns the derived list with `done` and the published schedule placement.

## 4. Durations and setups (`aps/durations.py`)

For operation `o` of an order with good quantity `Q`, input quantity `q_o = lot_inputs(ops, Q)[o]` (M1 4.4); for a
split part, `q` is that part's share (integer for count UoM). On line `L`:
```
setup_o,L(prev) = matrix(L.setup_family, family(prev item), family(item))   if L.setup_family has a matching row
                = rate.setup_minutes ?? o.setup_minutes                     otherwise
                = 0 when prev is the same order's same operation (continuation of a split on the same line)
run_o,L(q)      = rate.run_minutes x loads(o, q)                           if a line rate overrides run_minutes
                = o.run_minutes x loads(o, q) / L.speed_factor             otherwise
```
`family(item) = item.setup_family or item.family or ""`; `prev` = the operation scheduled immediately before on that
line slot (none at the horizon start -> the matrix row `(*, to)` or the operation's setup). Durations are rounded up
to whole minutes (`to_engine_minutes`). Setup is always attended; run is attended unless `labor == unattended`.
Queue, move and wait minutes are elapsed (calendar) time, need no resource, and lie between operations (6.5).

## 5. Time model (IANA)

All instants are stored in UTC; internally the scheduler works in integer minutes from `as_of` (rounded up to the
minute). Local wall-clock rules (shift templates, exceptions given as local times, dates) are resolved in
`plant_tz`: a shift start that does not exist (spring-forward gap) moves forward by the gap; an ambiguous time
(fall-back) takes the first occurrence (`fold=0`); a shift spanning a DST change has its real elapsed length. Day
attribution of shifts stays M1 4.6. Business dates ("today", due dates) are local dates in `plant_tz`; a due date
means **available at local 00:00 of that date** (M2 8.5 semantics). M1/M2 code switches from `utc_offset` to
`tz.plant_tz(plant)` (one helper; with `time_zone` None it returns the fixed offset, so existing data behaves as
before). Calendar exceptions stay UTC instants (no rebase needed when switching to a zone). New pin: `tzdata`
(pure-Python wheel; Windows has no system zone database).

## 6. Scheduling model

### 6.1 Contract (`aps/model.py`, frozen at S0)

```python
class ApsParams(MfgModel):                        # = POST /aps/runs body
    label: str = ""; note: str = ""
    as_of: PlanDateTime | None = None             # None = now (rounded up to the minute); other -> what_if
    horizon_days: int | None = None               # 7..120, default plant.aps_horizon_days
    mrp_run_id: EntityId | None = None            # pegging + planned orders; None = latest completed live MRP run
    include_planned: bool = True                  # schedule MRP planned make orders starting before horizon end
    overtime: Literal["off", "suggest", "allow"] | None = None    # None = plant default
    split: bool = True                            # lot splitting across lines
    material: Literal["strict", "ignore"] = "strict"              # ignore -> what_if
    improve_seconds: int = 30                     # LNS deterministic budget, 0..300 (0 = construction only)
    capacity_overrides: list[CapacityOverride] = []   # what_if: {target_type: line|group, target_id,
                                                      #  start, end, mode: "open_optional"|"close"}
    edits: list[ScheduleEdit] = []                # only via POST .../edits (6.7); stored with the child run

@dataclass(frozen=True)
class ApsSnapshot:      # repo_m3.load_aps_snapshot, one REPEATABLE READ transaction
    as_of: datetime; tz: tzinfo; dataset: MfgDataset            # incl. M3 master tables
    work_orders: list[WoSnap]                                   # planned/released/in_progress + progress markers
    mrp: MrpPegView | None                                      # planned make orders, component pegs, demand ranks
    stock_now: dict[str, float]; open_supply: list[SupplySnap]  # live fallback for unpegged components (6.4)
    published: PublishedView | None                             # placements of the published run (freeze, 6.6)

class ApsResult:  params, kind, summary (KPIs 9.4), score (tuple 7.3), validation {ok, violations[]},
                  operations: list[ScheduledOp], overtime: list[OvertimeWindow], orders: list[OrderResult],
                  exceptions: list[ApsException], load: list[LoadRow], iterations, budget_used
class ScheduledOp:  op_no, order {type: wo|planned, id, number, planned_no, item_id}, seq, name, group_id,
                    qty, split {index, count}, line_id, start, end, setup_minutes, run_minutes,
                    pieces: [(start, end)], crew: [(operator_id, start, end)], tools: [(tool_pool_id, qty)],
                    release {material_at, predecessor_at, refs}, locked, frozen, status: scheduled|unscheduled,
                    reason {code, refs, text}, due, late_minutes
```

### 6.2 Orders and operations

- **Orders**: WOs `released`, `in_progress`, `planned` (firm) and, with `include_planned`, planned make orders of
  the MRP run whose `start_date <= horizon end` and that are not converted. Each order's operations come from its
  routing (WO `routing_id`; planned order `routing_id`), quantities from 4; `done` operations are skipped.
- **Due and priority**: order due = WO `due_date` / planned `need_date` (local 00:00). Rank = best rank of the M2
  demand lines pegged to the order (M2 8.8), else `(1, wo.priority, due, number, 0)`. Tardiness weight of an
  order = `2^(9 - p)` with `p` = the rank's priority (1..9), so one late minute of P1 outweighs 256 of P9.
- **Horizon**: operations that cannot start before `horizon end` are `unscheduled` with reason `beyond_horizon`
  (their MRP dates are shown); this is rolling-horizon planning, not an error.

### 6.3 Resources

- **Lines**: eligible active lines of the operation's group (`routing.eligible_lines`), capacity
  `parallel_capacity` units, one unit per operation (part). Windows = base, plus optional instances by policy (6.8),
  minus `close` overrides; computed by `line_windows` in `plant_tz`.
- **Operators**: attended time (setup always, run when attended) needs `crew_size` distinct active operators with
  the skill, inside their `operator_windows` minus absences, not booked elsewhere. Crews may change between pieces
  of an interruptible operation (shift handover). Unattended runs need no crew.
- **Tools**: `qty` units of each pool are held from the operation's start to its end (including pauses).

### 6.4 Precedence and material

- Within an order, with gap `g = move_k + wait_k + queue_{k+1}` (elapsed minutes): if op k has `transfer_batch b`
  and is not an `inspection_gate`, `start_{k+1} >= start_k + time_k(b) + g` and `end_{k+1} >= end_k + run_{k+1}(b)
  + g` (overlap); otherwise `start_{k+1} >= end_k + g`. (Split parts: `start_k` =
  earliest part start, `end_k` = latest part end.)
- **Material release** of operation `o` = max over its components (component `operation_seq == o.seq`; None or not
  found -> first operation) of the component's availability, using the MRP run's pegs (M2 8.2): stock -> `as_of`;
  PO/PR schedule -> `available_date` 00:00; child WO or planned make order -> that order's **scheduled** last-op end
  + `move` (a cross-order precedence, so children are scheduled first). Components without pegs (WO created after the
  MRP run): live fallback - free stock covers -> `as_of`; else the earliest open PO/PR schedule covering it; else
  `unscheduled`, reason `material_missing` (S1). `material: ignore` skips this (what-if).

### 6.5 Calendar semantics

An operation (part) occupies its line from start to end. `interruptible` operations run only inside open windows
and pause outside them (pieces); non-interruptible ones (`interruptible == false`) must fit one continuous open window
(base and opened optional windows merge when touching, M1 7.2 #9). Elapsed gaps (queue/move/wait) ignore calendars.

### 6.6 Freeze, locks, in-progress

With a published run P and `as_of`: P's operations that are still open and start before `as_of + freeze_hours` are
**frozen** (same line, start, crew); operations with `start < as_of < end` are fixed as in progress; operations of P
with `end < as_of` not marked done are rescheduled from `as_of` with exception `APS_PAST_OP_NOT_DONE`. Frozen
operations whose order disappeared or changed quantity are dropped (`APS_FROZEN_DROPPED`). Explicit locks come from
edits (6.7).

### 6.7 Manual edits

`POST /aps/runs/{id}/edits {"edits": [...], "override_freeze": false}` on a completed run creates a **child run**
(`parent_run_id`, same params + accumulated edits) by synchronous repair: edited operations are placed exactly as
requested and locked; every other non-frozen operation is re-placed by construction (no LNS) in its previous order
of priority; then full validation. Edit kinds: `move {op_no, line_id?, start?}` (a start inside a closed window is rejected, never
snapped), `lock {op_no}`, `unlock {op_no}`,
`resequence {line_id, op_nos[]}` (those operations in this order on that line, earliest feasible times). A requested
placement that breaks a hard constraint -> 422 `APS_EDIT_INFEASIBLE` with the validator violations; moving a frozen
operation needs `override_freeze: true`.

### 6.8 Overtime and capacity overrides

Optional capacity = optional shift instances (one per assignment window per day, M1 4.6) on a line. `allow`: during
construction, when the best placement of a **late or critical** operation (slack < 0) can finish earlier using
optional instances of its candidate line, those instances are opened (subject to `max_hours_per_week` of the
assignment and to qualified operators being on shift); after LNS, opened instances without work are closed. Cost of
an opened instance = its minutes x `cost_per_hour` / 60. `suggest`: the plan uses base only; a second internal
`allow` pass yields `OvertimeWindow(status="suggested", tardiness_saved_minutes)` rows, ranked by saved weighted
tardiness per cost. `capacity_overrides` force-open optional time (`open_optional`, counted as overtime) or close
a line/group (breakdown, maintenance what-if).

## 7. Algorithms

### 7.1 Construction (`aps/construct.py`)

Serial schedule generation in event order. An operation is *ready* when its predecessors and material providers are
placed. Selection key among ready operations: `(order rank, slack, order number, seq)` where `slack = latest start -
earliest start`, latest start = backward pass from the order due over the routing's minimum durations. For the
chosen operation, each eligible line is evaluated for the earliest feasible placement - insertion into an idle gap
is allowed if it delays nobody already placed - including setup from the preceding operation on that slot, crew and
tool availability, windows; pick minimum end, ties by smaller setup, then line code. Lot splitting (`split`): an
operation that is late or critical and has `q >= 2 x min_split` (`min_split = max(transfer_batch or 1,
ceil(0.1 q))`) is tried split into 2 or 3 parts on the earliest-free eligible lines (each part pays its setup); the
split is kept if the latest part ends earlier than the single placement by more than the extra setup time.
Overtime opening per 6.8. Complexity O(ops x eligible lines x windows touched).

### 7.2 Improvement (`aps/lns.py`)

Neighbourhoods, in a seeded deterministic order: (a) each bottleneck group (9.3) x consecutive 2-day windows,
(b) the operations of the 10 most tardy orders' critical chains within one week. Each is a CP-SAT model over the
operations that start in the window on that group (others fixed as boundary): optional intervals per eligible line,
`AddNoOverlap`/`AddCumulative` per line, setup transition costs via a precomputed matrix on circuit arcs, precedence
and material bounds from the fixed rest, crews and tools as cumulative constraints with the fixed rest's usage
subtracted. Time axis = working minutes of the window; a neighbourhood whose lines do not share the same open
windows is solved on the intersection or skipped. Objective = the 7.3 tuple scalarised with tier weights. A solution
is accepted only if the full validator stays clean and the tuple improves. Solver: 1 worker, fixed seed,
`max_deterministic_time` per neighbourhood; total budget `improve_seconds` (deterministic units) plus a wall-clock
cap of 2x that budget.

### 7.3 Objective (lexicographic tuple, smaller is better)

`(hard_violations, weighted_tardiness_minutes, overtime_cost, wip_minutes (sum of order flow time last end - first
start), makespan_minutes, setup_minutes)`. The construction result is the baseline; LNS never returns worse.

### 7.4 Validator (`aps/validator.py`, independent of construct/LNS code)

Checks every operation: eligibility; line capacity (concurrent parts <= `parallel_capacity`); only open windows
(base, opened optional, not closed); non-interruptible in one continuous window; duration = 4 formula incl. setups
w.r.t. the actual predecessor on the slot; precedence and elapsed gaps; material release; crew count, skill, shift,
absence, no double booking; tool quantities; optional hours <= `max_hours_per_week`; locks and frozen placements
respected. Output `{ok, violations: [{code, op_no, message, refs}]}`; a run with violations is `infeasible`
(shown, not publishable).

## 8. Explanations and bottlenecks (`aps/explain.py`)

- **Start reason** per operation (the binding constraint at placement, S2): `as_of`, `material` (ref: PO
  schedule / child order), `predecessor` (op), `line_busy` (op holding the slot), `no_window` (next window, e.g.
  "SMT-2 closed Sun; base shift starts Mon 06:00"), `crew` (skill, operators busy/absent), `tool` (pool),
  `setup` (changeover from family X), `frozen`, `locked`, `elapsed` (queue/move/wait).
- **Why late** (per late order): walk back from the last operation along binding reasons to a root:
  `material` (part + supply), `capacity` (group + competing orders), `calendar` (no shift/holiday),
  `lead_time` (pure processing time exceeds due - as_of), `frozen/locked`. Text, e.g. "WO-000143 (KV-TPU-1000 x10)
  ends 18 Dec, 3 days late: burn-in BI-1/BI-2 full 12-15 Dec with WO-000139 (P1); earlier: SMT-1 waits for
  KV-IC-FPGA-V1 (PO-KV-0101/10/2, 7 Jan)".
- **Bottleneck** per run: groups ranked by base-capacity utilisation over the horizon and by the number of late
  chains with `line_busy` on them; top 3 shown with "adding the EVE shift on THT saves 410 weighted late minutes"
  when `suggest` data exists.
- **Demand-order view**: a demand line's scheduled completion = the scheduled end of the top-level order(s) pegged
  to it (M2 pegging), compared with its due date.

## 9. Views and KPIs (`aps/views.py`)

1. **Gantt**: rows by line (grouped by stage), by order (operations of a WO/planned order, children nested by
   pegging) or by demand order; bars carry setup/run split, pieces, lateness, frozen/locked flags; windows (base,
   optional opened/suggested, closed) as background bands.
2. **Capacity load** per group/line per day or week: `scheduled` minutes vs base, optional and opened capacity
   (utilisation %), plus `required` minutes = the same operations at their MRP dates (rough-cut, shows overload
   before scheduling).
3. **Dispatch list** per line and shift instance (published run): ordered operations with start/end, WO, item, qty,
   setup from/to family, crew, tools, predecessor status, material status (live M2 kitting of the WO), done button.
4. **KPIs** (`summary`): demand lines on time / late (by 8 demand view), late WOs, weighted tardiness, max lateness,
   overtime hours and cost (opened; suggested separately), utilisation per group, bottleneck groups, setup minutes
   and changeovers, average WO flow days (WIP), makespan, unscheduled operations by reason, validation status,
   timings.
5. **Compare** two runs: KPI deltas, per order end delta (changed only, max 500), per group utilisation delta,
   overtime delta.

## 10. Runs, publish, persistence

- `POST /aps/runs` (perm `schedule_run`) -> 202 `ApsRunRecord` (`queued`); one queued/running run per plant (409
  `APS_RUN_IN_PROGRESS`, partial unique index); Gate 1 health + APS preflight run synchronously first (422
  `MFG_DATA_HEALTH_FAILED` / `APS_PREFLIGHT_FAILED`: WO without effective routing, operation group without eligible
  active line, no MRP run when `include_planned` or `material: strict` needs one -> `APS_NO_MRP_RUN`, more than
  `APS_MAX_OPERATIONS` = 50,000 -> `APS_TOO_LARGE`). The job (`aps_run` kind added to `jobs.types.JOB_KINDS`,
  worker default kinds = all) loads the snapshot, runs, validates, stores; progress (`phase`: load / construct /
  improve / validate / store, `percent`, best score) is written every <= 2 s to the run row. `POST .../cancel`
  stops at the next checkpoint (best valid schedule kept as `cancelled` with results if construction finished).
- `kind = what_if` iff `as_of` given, `material: ignore`, `capacity_overrides`, or `mrp_run_id` points to a what-if
  MRP run. Only `live`, `completed`, validator-ok runs can be **published** (`POST .../publish`, perm
  `schedule_publish`; replaces the previous published run; 409 `APS_NOT_PUBLISHABLE`).
- **MRP feedback**: MRP runs gain param `use_schedule: bool = true`: with a published run, existing WOs' and the
  scheduled planned orders' projected dates come from the schedule (the M2 `supply_date_overrides` mechanism).
- Staleness as M2 8.14 (master `data_version`, transactions token, plus the MRP run id used). Retention: 10
  unpinned runs (published and its parents kept).
- Tables (migration `0005_mfg_m3`, M1/M2 conventions; run tables store master ids without FKs, M2 9.1):

| Table | Key columns |
|---|---|
| `mfg_operation_line_rates` | operation_id FK CASCADE, line_id FK CASCADE, setup_minutes Dbl N, run_minutes Dbl N, note; uq (operation_id, line_id) |
| `mfg_setup_matrix` | line_setup_family S32, from_family S32, to_family S32, setup_minutes Dbl; uq (owner_id, line_setup_family, from_family, to_family) |
| `mfg_operator_absences` | operator_id FK CASCADE, start_at DT, end_at DT, kind S16, note; ix (operator_id, start_at) |
| `mfg_wo_op_progress` | wo_id FK CASCADE, seq Int, done Bool, done_at DT N, done_by S64 N; uq (wo_id, seq) |
| `mfg_aps_runs` | run_no, kind, status (queued/running/completed/failed/cancelled), label, note, pinned, is_published Bool, published_at, published_by, parent_run_id (FK self SET NULL), mrp_run_id S64 N, params JSON, as_of DT, horizon_end DT, master_fingerprint, inputs_token JSON, job_id S64 N, progress JSON, summary JSON, score JSON, validation JSON, error JSON, actor_id, started_at, finished_at, duration_ms; uq (owner_id, run_no); partial uq (owner_id) where status in (queued, running); partial uq (owner_id) where is_published |
| `mfg_aps_ops` | run_id FK CASCADE, op_no, order_type, order_id, order_number, planned_no N, item_id, part_number, seq, name, group_id, line_id N, split_index, split_count, qty, start_at N, end_at N, setup_minutes, run_minutes, pieces JSON, crew JSON, tools JSON, release JSON, locked, frozen, status, reason JSON, due_at N, late_minutes; ix (run_id, line_id, start_at), ix (run_id, order_id) |
| `mfg_aps_overtime` | run_id, line_id, assignment_id, start_at, end_at, minutes, cost, status (opened/suggested/forced), tardiness_saved_minutes N |
| `mfg_aps_orders` | run_id, order_type, order_id, number, item_id, part_number, qty, due_at, start_at, end_at, late_minutes, weight, priority, demand_refs JSON, late_chain JSON |
| `mfg_aps_exceptions` | as M2 `mfg_mrp_exceptions` |
| `mfg_aps_load` | run_id, group_id, line_id N, day Date, scheduled_minutes, required_minutes, base_minutes, optional_minutes, opened_minutes |

Reset/reassign registries include all ten tables (M2 9.4). Plant columns: `time_zone S64 N`, `aps_freeze_hours`,
`aps_horizon_days`, `aps_overtime_policy` (server defaults dropped after the add, M2 9.1).

**Exceptions** (`APS_*`, severity as M2): `APS_ORDER_LATE` (critical, with late chain), `APS_MATERIAL_MISSING`
(critical), `APS_BEYOND_HORIZON` (info, count), `APS_OVERTIME_SUGGESTED` (info), `APS_OVERTIME_LIMIT` (warning: allow
mode hit `max_hours_per_week`), `APS_NO_CREW` (warning: an operation waited > 1 shift for qualified operators),
`APS_PAST_OP_NOT_DONE` (warning), `APS_FROZEN_DROPPED` (warning), `APS_SPLIT` (info), `APS_BUDGET_CUT` (info:
wall-clock cap hit).

## 11. API (`/api/v1/mfg`, `router_m3.py`; numbering continues M2's 163)

| # | Method and path | Body / query | Response | Perm |
|---|---|---|---|---|
| 164-167 | GET/POST `/operation-line-rates` (`operation_id`, `line_id`); PUT/DELETE `/operation-line-rates/{rate_id}` | `OperationLineRateInput` | records | view / master_edit |
| 168-171 | GET/POST `/setup-matrix`; PUT/DELETE `/setup-matrix/{row_id}` | `SetupMatrixRowInput` | records | view / master_edit |
| 172-175 | GET/POST `/operator-absences` (`operator_id, from, to`); PUT/DELETE `/operator-absences/{absence_id}` | `OperatorAbsenceInput` | records | view / master_edit |
| 176 | GET `/work-orders/{wo_id}/operations` | - | derived operations + done + published placement | view |
| 177-178 | POST `/work-orders/{wo_id}/operations/{seq}/done` \| `/reopen` | `{}`, If-Match (WO) | WO operations | wo_edit |
| 179 | POST `/aps/runs` | `ApsParams` | 202 `ApsRunRecord` | schedule_run |
| 180 | GET `/aps/runs` | `kind, status, pinned, limit, offset` | page | view |
| 181 | GET `/aps/runs/published` | - | record or 404 | view |
| 182 | GET `/aps/runs/{run_id}` | - | `ApsRunRecord` (+ progress, stale) | view |
| 183 | PUT `/aps/runs/{run_id}` | `{label, note, pinned}`, If-Match | record | schedule_run |
| 184 | DELETE `/aps/runs/{run_id}` | If-Match | 204 (409 `MFG_IN_USE` if published) | schedule_run |
| 185 | POST `/aps/runs/{run_id}/cancel` | `{}` | record | schedule_run |
| 186 | POST `/aps/runs/{run_id}/publish` | `{}`, If-Match | record | schedule_publish |
| 187 | POST `/aps/runs/{run_id}/edits` | `{edits, override_freeze}` | 201 child `ApsRunRecord` (completed) | schedule_run |
| 188 | GET `/aps/runs/{run_id}/gantt` | `view (line\|order\|demand), from, to, group_id, line_id, order_id, demand_order_id` | `{rows: [{key, label, kind, parent_key}], bars: [...], bands: [...], truncated}` (max 5,000 bars) | view |
| 189 | GET `/aps/runs/{run_id}/operations` | `line_id, group_id, order_id, status, late_only, frozen, from, to, sort, limit, offset` | page of `ScheduledOpRow` | view |
| 190 | GET `/aps/runs/{run_id}/operations/{op_no}` | - | op + reason + release refs + neighbours on the line | view |
| 191 | GET `/aps/runs/{run_id}/orders` | `late_only, order_type, q, sort (-late_minutes\|due_at), limit, offset` | page of `OrderResultRow` (incl. late chain) | view |
| 192 | GET `/aps/runs/{run_id}/demand` | `late_only, program` | demand lines with scheduled completion | view |
| 193 | GET `/aps/runs/{run_id}/load` | `group_id, line_id, bucket (day\|week), from, to` | `LoadRow[]` | view |
| 194 | GET `/aps/runs/{run_id}/dispatch` | `line_id` (required), `date`, `shift` | dispatch rows (9.3) | view |
| 195 | GET `/aps/runs/{run_id}/overtime` | `status` | `OvertimeWindow[]` with totals | view |
| 196 | GET `/aps/runs/{run_id}/exceptions` | as M2 #158 | page + counts | view |
| 197 | GET `/aps/runs/{run_id}/bottlenecks` | - | top groups with utilisation, late chains, suggestions | view |
| 198 | GET `/aps/runs/{run_id}/compare` | `with` | compare (9.5) | view |
| 199 | GET `/aps/runs/{run_id}/export` | `format=xlsx\|zip` | operations, dispatch per line, orders, load | view |

Errors (in addition to M1/M2): 409 `APS_RUN_IN_PROGRESS`, `APS_RUN_NOT_COMPLETED`, `APS_NOT_PUBLISHABLE`; 422
`APS_PREFLIGHT_FAILED`, `APS_NO_MRP_RUN`, `APS_TOO_LARGE`, `APS_EDIT_INFEASIBLE` (`details.violations`),
`APS_EDIT_FROZEN`, `APS_UNKNOWN_OPERATION`, `MFG_TZ_INVALID`, `MFG_LINE_NOT_IN_GROUP`. `PUT /plant` accepts the 3.1
fields; `GET /summary` gains `published_schedule {id, run_no, published_at, late_orders, stale} | null`.

`ApsRunRecord`: M2 `MrpRunRecord` fields + `status` incl. `queued/running/cancelled`, `progress {phase, percent,
best_score, updated_at}`, `parent_run_id`, `mrp_run {id, run_no}`, `is_published`, `validation {ok, counts}`.
`ScheduledOpRow` = `ScheduledOp` with refs `{order, item: ItemRef, line: {id, code}, group: {id, code}}`, `link`.
Gantt bar: `{op_no, row_key, start, end, setup_end, pieces, label, order_number, item_part_number, qty, late_minutes,
frozen, locked, split, status_color}`; band: `{row_key, start, end, kind: base|optional_opened|optional_suggested|
closed|absence}`. Typed examples of every shape are delivered at S0 (`backend/.../aps/fixtures/example_run.json`,
`frontend/src/mfg/api/contractExamplesM3.ts`).

Permissions (M2 10.2 + two): `schedule_run` (owner, planner) - runs, edits, cancel, PUT/DELETE; `schedule_publish`
(owner, planner). Master rates/matrix/absences: `master_edit`; operation progress: `wo_edit`; everything GET: `view`
(viewers and store keepers see dispatch lists). `MFG_PERMISSIONS` gains the 36 routes (199 total).

## 12. UI (`frontend/src/mfg/**`, no new npm packages)

Planning group gets **Schedule**. Routes:

| Route | Content |
|---|---|
| `/mfg/schedule` | runs list (status, progress bar while running via polling every 2 s, KPIs, published badge), New run form (policy, horizon, MRP run, split, improve seconds; what-if: capacity overrides, material ignore) |
| `/mfg/schedule/runs/:runId` | summary: KPI tiles, validation, bottlenecks with suggestions, late orders top 10, stale banner, Publish, Export |
| `.../gantt` (`?view=line\|order\|demand&group=&from=&to=`) | `ProdGantt`: **canvas** rendering with windowed rows (<= 80 DOM rows), pan/zoom (hour..month), bands, bar tooltip with reason; drag to another line/time and drop -> edit preview -> "Apply" creates the child run (422 shows violations inline); lock toggle; resequence by dragging within a line |
| `.../load` | stacked bars per day/week per group (scheduled vs base/optional), required overlay, click -> Gantt filtered |
| `.../dispatch` (`?line=&date=&shift=`) | dispatch list, print view, "done" per operation |
| `.../orders`, `.../demand` | order/demand tables with late chain text and links |
| `.../overtime` | opened and suggested windows, cost and saved tardiness; "Re-run with these opened" (what-if form prefilled) |
| `.../exceptions`, `.../compare` (`?with=`) | as MRP equivalents |
| `/mfg/plant/setups` | setup matrix editor per line family |
| `/mfg/resources/operators?operator=` | + absences section |
| routing operation editor | + "Line rates" sub-table |
| `/mfg/plant/settings` | + time zone (searchable IANA list from `/meta`), APS defaults |
| `/mfg/work-orders/:woId` | + Operations tab (done/reopen, published placement) |

Test ids: `aps-new-run`, `aps-run-submit`, `aps-progress`, `aps-publish`, `aps-kpi-{late|overtime|util|setup}`,
`gantt-canvas` (`data-bars`, `data-rows`), `gantt-view-{line|order|demand}`, `gantt-drop-apply`,
`edit-violations`, `load-bar` (`data-group`, `data-util`), `dispatch-row` (`data-op`), `op-done`,
`overtime-row` (`data-status`), `bottleneck-row`, `setup-matrix-row`, `absence-row`, `tz-select`.

## 13. Kavach M3 sample, performance

**Sample** (`samples`, deterministic, anchor as M2 13.1): plant `time_zone: Asia/Kolkata`; setup matrix for SMT line
families: same family 20 min, PCBA-HDI <-> PCBA-STD 60 min, `(*,*)` 45; three line rates (SMT-3 slower on
`KV-PCB-BPL`, WAVE-1 rate for `KV-PCB-FLT`, FT-2 faster final test); absences: one COATING operator on leave A+7..A+11,
one SMT-OP A+14..A+20, one burn-in technician sick A+3; progress: `WO-KV-0001` operations 10-40 done. Intended
outcomes (pinned at implementation, LEAD checks): with `overtime: off` `DO-KV-004/10` late with a chain through SMT
and burn-in; `suggest` lists EVE windows on THT/FCT and Sunday SMT with positive saved tardiness; `allow` reduces
weighted tardiness vs `off`; SMT shows setups grouped by family; the COATING absence shows `crew` reasons on COAT-1;
no validator violations; no `material_missing` (all pegged).

**Performance** (PostgreSQL local, developer machine class of M1/M2):

| # | Case | Target |
|---|---|---|
| AP1 | construct, Kavach sample (~1,500 operations incl. planned WOs, 50 lines, 48 operators, 86 tool pools, 42 days) | < 5 s pure |
| AP2 | + LNS `improve_seconds = 30` | never worse than AP1; deterministic |
| AP3 | construct, Kavach + 50 demand lines (~10,000 operations) | < 30 s; with 60 s LNS < 100 s wall |
| AP4 | construct, 30,000 operations | < 120 s |
| AP5 | run end-to-end (queue -> completed) Kavach, default budget | < 45 s; store < 3 s |
| AP6 | edit repair -> child run, Kavach | < 5 s |
| AP7 | validator, Kavach | < 1 s |
| AP8 | gantt 2 weeks one stage / load 6 weeks / dispatch one shift | < 0.3 / 0.3 / 0.2 s |
| AP9 | UI Gantt 3,000 bars: first paint after data, pan/zoom | < 500 ms; no long task > 100 ms |

## 14. Delivery plan (lean)

| WP | Role | Owns |
|---|---|---|
| **S** backend | one backend developer | `sp/mfg/tz.py`, `calendar.py` (tz + absences), `model.py` (plant fields), `model_m3.py`, `bundle.py`/`io` (3 sheets), `health.py` (2 codes), `samples` (M3 part), `sp/mfg/aps/**`, `sp/mfg/mrp` (`use_schedule` only), `sp/api/mfg/db_models_m3.py`, `repo_m3.py`, `aps_store.py`, `services/aps*.py`, `router_m3.py`, plant/WO service edits, `jobs/types.py` + handler registration, migration `0005_mfg_m3`, `migrate.py` HEAD, registrations in `main.py`/`api/db`, requirements pin `tzdata`, `tests/aps/**`, `tests/api_mfg_m3/**`, existing-test edits of 14.1 |
| **U** UI + e2e | one ui-developer | `frontend/src/mfg/**`, `frontend/e2e/m3-*.spec.ts`, `frontend/e2e/mfg-helpers.ts` (additive) |
| LEAD | team lead | this document, S0 review, final gate and review |

Milestones: **S0 (day 1, contract freeze)** - `aps/model.py`, `model_m3.py`, plant fields, migration + up/down test,
endpoint/permission table entries as stubs returning the fixture, `example_run.json`; U starts against
`contractExamplesM3.ts`. **S1** tz + master tables + absences + progress + import + health. **S2** construction,
validator, explanations (vectors 15.1). **S3** jobs/API/storage/views/publish/edits. **S4** LNS, overtime
suggest/allow, MRP `use_schedule`, sample pins, performance. **U1** runs + summary + Gantt read-only (after S0),
**U2** load/dispatch/orders/overtime/compare, **U3** drag edits, master editors, e2e specs. Contract changes only
via LEAD editing this document.

### 14.1 Existing code and tests touched

`jobs/types.py` (`aps_run` kind), `calendar.py`/all `utc_offset` users via `tz.plant_tz` (M1 calendar vectors must
pass unchanged with `time_zone` None), M2 `mrp` param, `services/plant.py`, `services/workorders.py`; existing tests
changed only: golden sample hashes (`tests/mfg/test_mfg_samples.py`, M2 sample tests), `tests/auth/route_table.py`
(+36 routes) and its coverage test, the authz sweep `id_map` (`run_id` under `/mfg/aps/` -> APS run, `rate_id`,
`row_id`, `absence_id`, `op_no`, `seq`), `load_dataset` statement bound (+3), job-kind lists if asserted.

## 15. Testing and acceptance

**During work (targeted only):** tests are written with the code in the same change; run only the touched files and
the package folder at a milestone (`.venv/bin/pytest tests/aps -q`, `tests/api_mfg_m3 -q`, named existing tests of
14.1); UI: `npm run build` and one spec at a time. No full-suite runs during work.

**Final gate (once, LEAD):** full backend suite on PostgreSQL incl. `-m slow`, both Playwright configurations,
build/audit, migration 0004 -> 0005 on a populated database and downgrade. Failures are fixed with targeted reruns
of the failing tests and their folders; no second full run unless a fix touches `api/db`, `api/auth`, migrations or
`jobs`.

### 15.1 Test vectors (`tests/aps`, pure; times in plant time `Asia/Kolkata` unless stated)

| # | Setup | Expected |
|---|---|---|
| T-S1 | one line REG Mon-Sat 09:00-18:00 lunch 13:00-13:45; interruptible op 600 min starting Mon 09:00 | pieces Mon 09:00-13:00 (240), 13:45-18:00 (255), Tue 09:00-10:45 (105); end Tue 10:45 |
| T-S2 | same op non-interruptible | no window fits (longest continuous window 4 h 15 min) -> `unscheduled`, reason `no_window`; on a 24x7 line: Mon 09:00-19:00 |
| T-S3 | two eligible lines speed 1.0 / 0.7, both free | op goes to the faster line; with the faster line busy until +200 min and run 300 min: slower line (300/0.7 = 429 < 500) |
| T-S4 | SMT line family `SMT`; matrix same family 20, HDI<->STD 60; three ops HDI, STD, HDI ready together, equal priority | sequence HDI, HDI, STD (setups 45 (*,*), 20, 60) beats HDI, STD, HDI (45+60+60) after LNS |
| T-S5 | line rate override run 2.0 on SMT-3 for item X (speed 0.7) | run = 2.0 x loads (speed not applied) |
| T-S6 | attended op crew 1 skill S; only operator on leave Tue | op does not run Tue; reason `crew`; validator rejects a manual move to Tue (`APS_EDIT_INFEASIBLE`) |
| T-S7 | op consumes component C pegged to PO schedule available Wed | start >= Wed 00:00 local, reason `material`; with `material: ignore` starts Mon |
| T-S8 | parent op consumes child WO output; child last op ends Tue 15:00, move 30 | parent op start >= Tue 15:30 |
| T-S9 | transfer batch 10 of 100 units, op1 run 1/unit, op2 run 1/unit, no gate | op2 starts at op1 start + 10, ends >= op1 end + 10 |
| T-S10 | P1 and P9 orders compete for one line, both late if second | P1 placed first; weighted tardiness uses 2^(9-p) |
| T-S11 | `overtime: allow`, line REG + optional EVE (cost 400/h, max 12 h/wk), order late by 3 h on base | EVE opened on 1 day (cost 1,600), order on time; `off`: late 3 h; `suggest`: plan = `off`, one suggested window with 180 saved late minutes (x order weight) |
| T-S12 | split: op 400 units on 2 idle eligible lines, order critical | 2 parts 200/200, each with setup; end earlier than single placement |
| T-S13 | DST: plant `Europe/Berlin`, 3SHIFT across 2026-10-25 | night shift Sat->Sun is 9 h elapsed; windows contiguous; validator ok |
| T-S14 | freeze 48 h: published op at as_of + 10 h on line A | new run keeps it on A at the same time even if B would be better |
| T-S15 | determinism: Kavach sample twice and under two `PYTHONHASHSEED`s | byte-identical canonical `ApsResult` |
| T-S16 | validator mutation tests: shift an op into a closed window, double-book an operator, exceed tool qty, break precedence | each detected with the right code |

### 15.2 Acceptance (Gate 3: every plan passes the validator)

1. Kavach M3 sample: run completes within AP5; validator ok; intended outcomes of 13 hold.
2. Vectors T-S1..T-S16 pass; validator mutation tests catch every hard-constraint class.
3. Independent check: for the Kavach run, a test recomputes every operation's duration, windows, crew and tool
   usage from master data with plain formulas (not `aps` code) and finds no violation.
4. Overtime policies: `allow` weighted tardiness <= `off`; overtime only on late/critical work; weekly limits held;
   `suggest` windows, when forced open by a what-if, reduce tardiness by at least the reported amount (+-5%).
5. Material: no operation starts before its pegged supply; a deliberately unpegged component with no supply gives
   `APS_MATERIAL_MISSING` and the op unscheduled.
6. Freeze and edits: publish -> new run keeps frozen ops; a drag to another eligible line creates a valid child run;
   an infeasible drag returns 422 with violations; resequence respected.
7. MRP with `use_schedule` uses published dates (late demand in MRP equals late demand in the schedule's demand view).
8. Roles: planner runs/publishes; viewer and store keeper read Gantt/dispatch but get 403 on run/publish/edit.
9. Time zones: switching the Kavach plant from `+05:30` to `Asia/Kolkata` changes no window (vectors T-C1..T-C8 of M1
   still pass); T-S13 passes.
10. Performance AP1-AP9; migration up/down; UI journey e2e: run -> watch progress -> Gantt by line -> drag an SMT
    op to SMT-2 -> apply -> child run valid -> publish -> dispatch list for SMT-2 shows it -> mark done.

## 16. Questions for the product owner

1. **Q1 Overtime default.** Built default is `suggest` (the planner decides, the system quantifies). Should HBL
   instead let the scheduler open overtime automatically (`allow`) by default?
2. **Q2 Due-date meaning.** Schedules treat a due date as "available at 00:00 of that day" (same as MRP). If HBL's
   due dates mean "by end of shift that day", say so; it shifts every lateness figure by up to a day.
3. **Q3 Real setup data.** SMT changeover times by board family (and any other stages with real changeovers) are
   needed for a meaningful pilot; the sample uses 20/45/60 minutes.

## 17. Implementation notes

### 17.WP-S Backend

### 17.WP-U UI
