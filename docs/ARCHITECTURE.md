# SuperPlanner MVP - Architecture

Status: design baseline for the MVP (v0.1). Owner: architect.
Source of intent: `docs/source/blueprint.txt` sections 4-12, 16, 19-24, plus
`docs/source/followups-finance-competitors-generalization.txt` for the generalization roadmap.

This document is a contract. Where it says "must", two independent implementations must behave
identically. Where an implementer has to interpret something, record it under
[Implementation notes](#25-implementation-notes) instead of silently diverging.

---

## Table of contents

1. Overview and principles
2. Component diagram
3. Engine data model (external `Problem` document)
4. Time model
5. Constraint semantics
6. Compiled (internal) model
7. Solver protocol, `SolveResult`, violations, metrics
8. Algorithm designs (decoder, left-shift, heuristic, CP-SAT, GA, selector)
9. Preflight and CPM
10. Independent validator
11. Explanation logic
12. Templates / domain adapter contract
13. Persistence (DB tables, versioning rules)
14. REST API
15. SSE events
16. Background run orchestration
17. Frontend (routes, components, state)
18. Repository layout and file ownership
19. Testing strategy
20. Deferred items
21. Deviations from the lead engineer's direction
22. Glossary
23. Review notes (team lead)
24. Open questions
25. Implementation notes

---

## 1. Overview and principles

SuperPlanner is a universal planning and optimization platform. A user describes **what** must be
done (tasks), **with what** (resources with capacity, cost and calendars), **in which order**
(dependencies), **by when** (earliest starts, deadlines) and **what "good" means** (objective
preset). The engine returns an executable schedule, proves it valid with an independent checker,
and explains every placement in plain language.

The MVP is a modular monolith: one FastAPI process that hosts the REST API and runs solver jobs in
a background thread pool, a pure-Python engine package with no web or DB imports, and a React
Planning Studio.

### Principles (binding for every module)

| # | Principle | Concrete consequence in the MVP |
|---|-----------|---------------------------------|
| P1 | Domain-neutral core, domain-specific UX | Engine knows only tasks/resources/dependencies/calendars. Manufacturing, exam prep and project vocabulary lives in templates and the `terminology` map. |
| P2 | Feasibility before optimality | Hard constraints are never weighted against objectives. A schedule is reported `feasible` only after the independent validator finds zero hard violations. |
| P3 | Honest status | `infeasible` only when proven (preflight or CP-SAT). "Nothing found in time" is `unknown`. `optimality_proven` is true only when CP-SAT returns OPTIMAL (or the resource-free CPM shortcut applies). |
| P4 | Solver portfolio, not "the GA" | Heuristic, CP-SAT and GA implement one protocol; a transparent rule-based selector chooses and explains. |
| P5 | Human control | Users can lock tasks (start and optionally resources). Approved schedules are never overwritten; approval supersedes explicitly. |
| P6 | Reproducibility | Every run references an immutable problem snapshot, the full effective config, the seed and the engine version. |
| P7 | Explainability | Every placed task carries a reason code ("waiting for Machine M2, busy with Op J1-2 until 10:00"). Preflight issues are plain language using the plan's terminology. |
| P8 | Simplest thing that works | SQLite + thread pool + SSE polling of persisted events. No Celery/Redis/auth in the MVP. |

### Pipeline (every optimization request)

```
Problem document
  -> preflight (structure + obvious infeasibility)        [stop if any error]
  -> compile (ISO datetimes -> integer minutes, calendars -> windows)
  -> CPM analysis (lower bounds, slack)
  -> baseline heuristic (always; gives references + hint/seeds)
  -> selected solver(s) (cpsat / ga / hybrid)
  -> left-shift compaction (never worsens objectives)
  -> independent validation (feasibility decided here)
  -> explanation
  -> persist schedules (primary + alternatives) as candidates
```

---

## 2. Component diagram

```
+----------------------------------------------------------------------------------+
|  Browser: React Planning Studio (frontend/, Vite dev server :5173)               |
|                                                                                  |
|  Home  |  Plan workspace tabs: Tasks Resources Dependencies Validate Optimize   |
|        |                          Schedule Compare                               |
|  src/api/client.ts (fetch)   src/api/sse.ts (EventSource)   PlanContext (draft) |
+---------------------------|-------------------------|----------------------------+
                            | /api/v1 (JSON)          | /api/v1/solver-runs/{id}/events (SSE)
                            v  Vite proxy -> :8000    v
+----------------------------------------------------------------------------------+
|  FastAPI app  backend/superplanner/api  (uvicorn :8000)                          |
|                                                                                  |
|  routes/  templates  problems  validate  solver_runs  schedules  health         |
|     |                                     |                                      |
|     v                                     v                                      |
|  services/  problem_service   run_service ---------> RunExecutor (ThreadPool, 2) |
|     |       schedule_service     |   persists events      |                      |
|     v                            v                        | calls                |
|  db/ SQLAlchemy 2 (SQLite default, DATABASE_URL)          v                      |
|     problems  problem_versions  solver_runs           superplanner.engine        |
|     solver_run_events  schedules  audit_events        (pure Python, no web/DB)   |
+-----------------------------------------------------------|----------------------+
                                                            v
+----------------------------------------------------------------------------------+
|  Engine  backend/superplanner/engine                                              |
|                                                                                  |
|  model.py (Pydantic Problem)  ->  timeutil.py / compiled.py (CompiledProblem)    |
|                                                                                  |
|  graph.py (cycles, topo, CPM)   preflight.py (issues)                            |
|                                                                                  |
|  pipeline.py: optimize(problem, request, progress_cb, cancel_event)              |
|     |-> selector.py (rules + explanation)                                        |
|     |-> solvers/heuristic.py  solvers/cpsat.py (OR-Tools)  solvers/ga.py         |
|     |        \______ all use decoder.py (serial SGS + left_shift) ______/         |
|     |-> validator.py (INDEPENDENT: does not import decoder or solvers)           |
|     |-> explain.py (solver-agnostic)                                             |
|     '-> objectives.py (weights, presets, normalized score)                       |
|                                                                                  |
|  superplanner/templates: manufacturing exam_prep project blank -> Problem        |
+----------------------------------------------------------------------------------+
```

Dependency rules (enforced by review, testable with an import-linter style test):
- `superplanner.engine` imports nothing from `superplanner.api` or `superplanner.templates`,
  and never imports fastapi/sqlalchemy.
- `engine/validator.py` imports only `model`, `compiled`, `timeutil`, `objectives`. It must not
  import `decoder`, `graph` scheduling helpers or any solver.
- `superplanner.templates` imports only `superplanner.engine.model`.
- `superplanner.api` uses the engine only through `superplanner.engine` public functions listed
  in section 7.6.

---

## 3. Engine data model (external `Problem` document)

File: `backend/superplanner/engine/model.py`. Pydantic v2, `model_config = ConfigDict(extra="forbid")`
on every model (unknown fields are a 422, which catches typos). This document is what the API
stores, what the UI edits and what import/export files contain. JSON field names are exactly the
Python attribute names (snake_case). TypeScript mirrors are in `frontend/src/api/types.ts`.

### 3.0 Validation layering (model 422 vs preflight)

Drafts must be saveable while incomplete (the UI autosaves), so checks are split in two layers.
Implementations must not move a check from one layer to the other.

- **Model layer (Pydantic, HTTP 422 on POST/PUT):** only types, ranges and regexes declared on a
  single field, plus these local rules: naive datetimes rejected; activity `duration_minutes >= 1`;
  milestone `duration_minutes == 0` and `requirements == []`; `Requirement.alternatives` non-empty
  and duplicate-free; `custom` weights not all zero; unknown fields rejected.
- **Preflight layer (`/validate`, run creation 422 `PREFLIGHT_FAILED`):** everything relational or
  horizon-dependent: unknown/duplicate ids, self-dependency, duplicate dependency pairs, cycles,
  `duration > H`, `abs(lag) > H`, window/blocked ordering and `"24:00"` used as a start, lock
  length/eligibility, deadlines vs horizon, capacity and CPM checks (section 9.1).

### 3.1 Common types

| Name | Definition |
|------|------------|
| `Id` | `str`, regex `^[A-Za-z0-9_.:\-]{1,64}$` |
| `AwareDatetime` | ISO-8601 datetime **with** UTC offset, e.g. `"2026-10-19T08:00:00+05:30"`. Naive datetimes are rejected (422). Seconds/microseconds are floored to the minute at compile time. |
| `HHMM` | `str`, regex `^([01]\d|2[0-3]):[0-5]\d$|^24:00$` |
| `Weekday` | `Literal["mon","tue","wed","thu","fri","sat","sun"]` |

### 3.2 `Problem`

| Field | Type | Default | Units / rules |
|-------|------|---------|---------------|
| `id` | `Id` | `"draft"` | The API always overwrites it with the record id (POST, PUT, import, instantiate), so clients may omit it. |
| `name` | `str` (1..200) | required | |
| `description` | `str` | `""` | |
| `domain` | `str` | `"generic"` | Template id that produced it: `manufacturing`, `exam_prep`, `project`, `generic`. Informational only; the engine never branches on it. |
| `horizon_start` | `AwareDatetime` | required | Minute 0 of the engine time axis. Its UTC offset is the plan's wall-clock offset (section 4). |
| `horizon_days` | `int` 1..366 | `30` | Horizon end `H = horizon_days * 1440` minutes. |
| `time_unit` | `Literal["minutes"]` | `"minutes"` | Fixed in the MVP; present for forward compatibility. |
| `currency` | `str` (0..8) | `"USD"` | Display only for `cost`. |
| `terminology` | `Terminology` | defaults below | UI vocabulary. |
| `tasks` | `list[Task]` | `[]` | Max 2000 (preflight error above). |
| `resources` | `list[Resource]` | `[]` | Max 200. |
| `dependencies` | `list[Dependency]` | `[]` | Max 10000. |
| `objectives` | `Objectives` | `Objectives()` | |
| `metadata` | `dict[str, Any]` | `{}` | Adapter-specific data; ignored by the engine. |

### 3.3 `Terminology`

All `str`, used by UI labels and by preflight/explanation messages.

| Field | Default | manufacturing | exam_prep | project |
|-------|---------|---------------|-----------|---------|
| `task` | `"Task"` | `"Operation"` | `"Study session"` | `"Task"` |
| `tasks` | `"Tasks"` | `"Operations"` | `"Study sessions"` | `"Tasks"` |
| `resource` | `"Resource"` | `"Machine"` | `"Study time"` | `"Team member"` |
| `resources` | `"Resources"` | `"Machines"` | `"Study time"` | `"Team"` |
| `group` | `"Group"` | `"Job"` | `"Subject"` | `"Workstream"` |
| `milestone` | `"Milestone"` | `"Milestone"` | `"Exam"` | `"Milestone"` |
| `schedule` | `"Schedule"` | `"Production schedule"` | `"Study plan"` | `"Project schedule"` |
| `deadline` | `"Deadline"` | `"Due date"` | `"Target date"` | `"Deadline"` |

### 3.4 `Task`

| Field | Type | Default | Units / rules |
|-------|------|---------|---------------|
| `id` | `Id` | required | Unique within the problem. |
| `name` | `str` (1..200) | required | |
| `description` | `str` | `""` | |
| `group` | `str \| None` | `None` | Free-text grouping (job, subject, workstream). Not schedulable. |
| `type` | `Literal["activity","milestone"]` | `"activity"` | |
| `duration_minutes` | `int` | `0` | activity: `>= 1` (422), `<= H` checked by preflight (`EARLIEST_AFTER_HORIZON`); milestone: must be `0` (model validator, 422 otherwise). Elapsed minutes, non-preemptive. |
| `priority` | `int` 1..10 | `5` | 10 = most important. Weights tardiness and drives the `priority` rule. |
| `earliest_start` | `AwareDatetime \| None` | `None` | Release time. `None` = horizon start. |
| `deadline` | `AwareDatetime \| None` | `None` | Target finish time (applies to the task **end**). |
| `deadline_hard` | `bool` | `False` | `True`: end > deadline is a hard violation. `False`: lateness is tardiness (soft). Ignored when `deadline` is `None`. |
| `requirements` | `list[Requirement]` | `[]` | Milestones must have `[]` (422). An activity with `[]` needs no resource and has no calendar. |
| `locked` | `Lock \| None` | `None` | User or replan freeze. |
| `metadata` | `dict[str, Any]` | `{}` | e.g. `{"difficulty": 3}` for exam prep, `{"skills": ["backend"]}`. Ignored by the engine. |
| `duration_estimate` | `DurationEstimate \| None` | `None` | Phase 2a, see `docs/PHASE2.md` 2.14: optional three-point estimate; when set, `duration_minutes` must equal `pert_minutes(o, m, p)` and milestones may not have one (422). Omitted from dumps when absent. Engines use `duration_minutes` only. |

### 3.5 `Requirement`

A task needs **all** of its requirements simultaneously for its whole duration. Each requirement
is satisfied by exactly **one** of its alternatives.

| Field | Type | Default | Rules |
|-------|------|---------|-------|
| `alternatives` | `list[Id]` (resource ids) | required | length >= 1, no duplicates (422). Order = user preference order (tie-break). |
| `units` | `int` | `1` | `>= 1`; consumes this many units of the chosen resource's capacity. |

Rule: the resources chosen for the requirements of one task must be pairwise distinct
(a task cannot use the same machine twice).

### 3.6 `Lock`

| Field | Type | Default | Rules |
|-------|------|---------|-------|
| `start` | `AwareDatetime` | required | Fixed start. End = start + duration. |
| `resource_ids` | `list[Id] \| None` | `None` | `None`: only the start is fixed; solvers choose resources. Otherwise length must equal `len(task.requirements)`; element `i` must be in `requirements[i].alternatives` (preflight `LOCK_INVALID`, not 422). |

### 3.7 `Dependency`

| Field | Type | Default | Units / rules |
|-------|------|---------|---------------|
| `predecessor` | `Id` (task) | required | |
| `successor` | `Id` (task) | required | `!= predecessor` (preflight `SELF_DEPENDENCY`, not 422) |
| `type` | `Literal["FS","SS","FF","SF"]` | `"FS"` | |
| `lag_minutes` | `int` | `0` | Elapsed minutes, may be negative (lead). `abs(lag) <= H` (preflight `LAG_OUT_OF_RANGE`). |

At most one dependency per ordered `(predecessor, successor)` pair (preflight error). The pair is
the dependency's identity in the UI.

### 3.8 `Resource`

| Field | Type | Default | Units / rules |
|-------|------|---------|---------------|
| `id` | `Id` | required | Unique. May not collide with a task id (preflight error, keeps explanations unambiguous). |
| `name` | `str` (1..200) | required | |
| `kind` | `str` | `"generic"` | Suggested: `person`, `machine`, `room`, `team`, `time`, `generic`. Informational. |
| `capacity` | `int` 1..1000 | `1` | Units available simultaneously. |
| `cost_per_hour` | `float >= 0` | `0.0` | Per **unit** per hour of occupation. |
| `calendar` | `Calendar \| None` | `None` | `None` = available for the whole horizon. |
| `metadata` | `dict[str, Any]` | `{}` | e.g. `{"skills": ["backend","qa"]}`. |

### 3.9 `Calendar`

| Field | Type | Default | Rules |
|-------|------|---------|-------|
| `weekly` | `dict[Weekday, list[tuple[HHMM, HHMM]]] \| None` | `None` | `None` = 24/7. A dict = only listed windows are open; a missing weekday key or `[]` = closed that day. Each window `[start, end)` needs `start < end`; `"24:00"` is valid only as an end (both checked by preflight `INVALID_CALENDAR`; the model only checks the `HHMM` regex). JSON shape of a window: a 2-element array `["06:00","14:00"]`. Windows crossing midnight must be split (`22:00-24:00` + next day `00:00-06:00`); contiguous windows are merged at compile time, so a night shift remains one window. |
| `blocked` | `list[BlockedInterval]` | `[]` | Removed from availability (maintenance, holidays). |

`BlockedInterval`: `{ "start": AwareDatetime, "end": AwareDatetime, "reason": str = "" }`, `start < end` (preflight `INVALID_CALENDAR`).

### 3.10 `Objectives`

| Field | Type | Default | Rules |
|-------|------|---------|-------|
| `preset` | `Literal["balanced","finish_asap","meet_deadlines","lowest_cost","custom"]` | `"balanced"` | |
| `weights` | `Weights` | `Weights()` | Used only when `preset == "custom"`; otherwise the preset table applies. |

`Weights`: `makespan: float >= 0 = 1.0`, `tardiness: float >= 0 = 1.0`, `cost: float >= 0 = 0.2`.
For `custom`, at least one weight must be > 0 (422).

Preset table (`engine/objectives.py`, constant `PRESET_WEIGHTS`):

| preset | makespan | tardiness | cost | UI label |
|--------|----------|-----------|------|----------|
| `balanced` | 1.0 | 1.0 | 0.2 | Balanced |
| `finish_asap` | 1.0 | 0.3 | 0.0 | Finish ASAP |
| `meet_deadlines` | 0.2 | 1.0 | 0.0 | Meet deadlines |
| `lowest_cost` | 0.2 | 0.5 | 1.0 | Lowest cost |

### 3.11 Example `Problem` (used by later examples)

```json
{
  "id": "p_7f3a",
  "name": "Workshop week 43",
  "description": "",
  "domain": "manufacturing",
  "horizon_start": "2026-10-19T00:00:00+05:30",
  "horizon_days": 14,
  "time_unit": "minutes",
  "currency": "INR",
  "terminology": {"task": "Operation", "tasks": "Operations", "resource": "Machine",
                  "resources": "Machines", "group": "Job", "milestone": "Milestone",
                  "schedule": "Production schedule", "deadline": "Due date"},
  "tasks": [
    {"id": "J1-1", "name": "J1 Cutting", "description": "", "group": "J1", "type": "activity",
     "duration_minutes": 90, "priority": 7, "earliest_start": null,
     "deadline": null, "deadline_hard": false,
     "requirements": [{"alternatives": ["CUT1"], "units": 1}], "locked": null, "metadata": {}},
    {"id": "J1-2", "name": "J1 Milling", "description": "", "group": "J1", "type": "activity",
     "duration_minutes": 120, "priority": 7, "earliest_start": null,
     "deadline": "2026-10-21T18:00:00+05:30", "deadline_hard": false,
     "requirements": [{"alternatives": ["MILL1", "MILL2"], "units": 1}], "locked": null, "metadata": {}}
  ],
  "resources": [
    {"id": "CUT1", "name": "Saw 1", "kind": "machine", "capacity": 1, "cost_per_hour": 900.0,
     "calendar": {"weekly": {"mon": [["06:00","14:00"],["14:00","22:00"]],
                             "tue": [["06:00","22:00"]], "wed": [["06:00","22:00"]],
                             "thu": [["06:00","22:00"]], "fri": [["06:00","22:00"]],
                             "sat": [["06:00","14:00"]]},
                  "blocked": []}, "metadata": {}},
    {"id": "MILL1", "name": "Mill 1", "kind": "machine", "capacity": 1, "cost_per_hour": 1200.0,
     "calendar": {"weekly": {"mon": [["06:00","22:00"]], "tue": [["06:00","22:00"]]},
                  "blocked": [{"start": "2026-10-20T10:00:00+05:30",
                               "end": "2026-10-20T12:00:00+05:30", "reason": "Maintenance"}]},
     "metadata": {}},
    {"id": "MILL2", "name": "Mill 2", "kind": "machine", "capacity": 1, "cost_per_hour": 1500.0,
     "calendar": null, "metadata": {}}
  ],
  "dependencies": [{"predecessor": "J1-1", "successor": "J1-2", "type": "FS", "lag_minutes": 0}],
  "objectives": {"preset": "balanced", "weights": {"makespan": 1.0, "tardiness": 1.0, "cost": 0.2}},
  "metadata": {}
}
```

---

## 4. Time model

- **Axis.** Engine time is an integer number of minutes since `horizon_start` (minute 0).
  Valid placements satisfy `0 <= start` and `end <= H` where `H = horizon_days * 1440`.
- **Intervals are half-open** `[start, end)`. A task ending at 10:00 and another starting at
  10:00 on the same capacity-1 resource do not overlap.
- **Conversion** (`engine/timeutil.py`):
  - `to_minute(dt, horizon_start) = floor((dt - horizon_start).total_seconds() / 60)`.
  - `from_minute(m, horizon_start) = horizon_start + timedelta(minutes=m)`, rendered with
    `horizon_start`'s UTC offset (`isoformat()`), so all API timestamps share the plan's offset.
  - Datetimes before `horizon_start` map to negative minutes; `earliest_start` is clamped to 0;
    a `deadline` before the horizon is a preflight error; a lock before the horizon is a preflight
    error.
- **Wall clock.** Weekly calendar `HH:MM` values are local times in the **fixed UTC offset of
  `horizon_start`**. Weekday of a minute `m` = weekday of `from_minute(m)` in that offset. No DST
  or IANA zones in the MVP (deferred). Rationale: one deterministic offset makes calendars and
  tests reproducible; DST would silently shift windows.
- **Calendar expansion** `expand_windows(resource, horizon_start, H) -> list[tuple[int,int]]`:
  1. If `calendar is None` -> `[(0, H)]`.
  2. If `weekly is None` -> start from `[(0, H)]`; else for every calendar day intersecting
     `[0, H)` (start from the local midnight at or before `horizon_start`), add each window of
     that weekday as absolute minutes; clip to `[0, H)`.
  3. Sort and merge overlapping **or touching** windows (`a.end >= b.start`).
  4. Subtract every blocked interval (converted to minutes, clipped).
  5. Drop empty windows. Result: sorted, disjoint, non-touching list of `(start, end)`.
- **Durations and lags** are elapsed minutes, independent of calendars. A FS lag of 1440 means
  "24 hours later", not "one working day later" (working-time lags deferred).

---

## 5. Constraint semantics

Notation: for task `t`, `S_t` start, `E_t = S_t + d_t` end, `d_t = duration_minutes`,
`r_t = max(0, to_minute(earliest_start))` (0 if `None`), `D_t = to_minute(deadline)`.

### 5.1 Hard constraints (must hold for `feasible`; never traded against objectives)

| ID | Constraint | Formula |
|----|-----------|---------|
| H1 | Every task placed exactly once | one placement per task id; no unknown ids |
| H2 | Duration consistency | `E_t - S_t = d_t` |
| H3 | Horizon | `0 <= S_t` and `E_t <= H` |
| H4 | Earliest start | `S_t >= r_t` |
| H5 | Dependencies | see 5.3 |
| H6 | Eligibility | `len(resource_ids) == len(requirements)`; `resource_ids[i] in requirements[i].alternatives`; resource ids pairwise distinct |
| H7 | Capacity | for every resource `k` and every minute `m`: `sum(units of requirements assigned to k of tasks with S_t <= m < E_t) <= capacity_k` |
| H8 | Calendar (non-preemptive) | for every assigned resource `k`, `[S_t, E_t)` lies inside a **single** window of `expand_windows(k)` (`w.start <= S_t` and `E_t <= w.end`). Milestones and tasks without requirements are exempt. |
| H9 | Locks | `S_t == to_minute(locked.start)`; if `locked.resource_ids` is set, `resource_ids == locked.resource_ids` |
| H10 | Hard deadlines | if `deadline_hard` and `deadline` set: `E_t <= D_t` |

Milestones (`d = 0`) occupy no resource and need no window; they still obey H3-H5, H9, H10.

### 5.2 Soft constraints / objectives

| ID | Name | Definition | Unit |
|----|------|-----------|------|
| S1 | Tardiness | `T_t = max(0, E_t - D_t)` for tasks with a deadline and `deadline_hard == false` | minutes |
| O1 | Makespan | `max_t E_t` (minutes from horizon start; 0 if no tasks) | minutes |
| O2 | Weighted tardiness | `sum_t priority_t * T_t` | priority-minutes |
| O3 | Cost | `sum_t sum_i cost_per_hour(resource_ids[i]) * units_i * d_t / 60` | currency |

A soft deadline miss is reported as a `soft` violation `DEADLINE_MISSED`; it never makes a
schedule infeasible.

### 5.3 Dependency types (predecessor `a`, successor `b`, lag `L`)

| Type | Meaning | Constraint | Lower bound on `S_b` given `a` placed |
|------|---------|------------|----------------------------------------|
| FS | b starts after a finishes | `S_b >= E_a + L` | `E_a + L` |
| SS | b starts after a starts | `S_b >= S_a + L` | `S_a + L` |
| FF | b finishes after a finishes | `E_b >= E_a + L` | `E_a + L - d_b` |
| SF | b finishes after a starts | `E_b >= S_a + L` | `S_a + L - d_b` |

All four are lower bounds on the successor, so any topological order of the dependency graph is
a valid placement order for constructive algorithms. Moving a predecessor earlier never violates
a dependency (used by left-shift, 8.2). Any directed cycle is an error regardless of lag signs
(MVP rule: positive cycles are infeasible, zero/negative cycles are rare and confusing to users).

### 5.4 Calendar semantics summary

- Availability windows are per resource; the task must fit wholly inside one window of **every**
  assigned resource (no splitting across shifts, nights or maintenance).
- Capacity applies only inside windows; outside windows a resource has effective capacity 0.
- A resource with `calendar: null` is available `[0, H)`.
- Tasks with no requirements and milestones are not calendar-bound.

### 5.5 Feasibility vocabulary

| `feasibility` | Meaning |
|---------------|---------|
| `feasible` | A complete schedule exists and the validator found **zero hard violations**. |
| `infeasible` | **Proven**: preflight found a blocking error, or CP-SAT returned INFEASIBLE. |
| `unknown` | No feasible schedule was found, but infeasibility was not proven (time limit, heuristic/GA failed). A best-effort schedule may be returned with its hard violations listed; it cannot be approved. |

---

## 6. Compiled (internal) model

File: `backend/superplanner/engine/compiled.py`. Plain `@dataclass(frozen=True, slots=True)`.
Built by `compile_problem(problem: Problem) -> CompiledProblem`; requires a problem without
preflight errors (raises `CompileError(issues)` otherwise). Solvers, decoder, validator and
explain operate on this form. Indices are positions in the lists below.

```python
@dataclass(frozen=True, slots=True)
class CRequirement:
    units: int
    alternatives: tuple[int, ...]          # resource indices, user order

@dataclass(frozen=True, slots=True)
class CTask:
    idx: int
    id: str
    name: str
    is_milestone: bool
    duration: int                          # minutes
    release: int                           # r_t >= 0
    deadline: int | None                   # D_t
    deadline_hard: bool
    priority: int                          # 1..10
    requirements: tuple[CRequirement, ...]
    locked_start: int | None
    locked_resources: tuple[int, ...] | None   # aligned with requirements

@dataclass(frozen=True, slots=True)
class CResource:
    idx: int
    id: str
    name: str
    capacity: int
    cost_per_hour: float
    windows: tuple[tuple[int, int], ...]   # expand_windows result

@dataclass(frozen=True, slots=True)
class CDependency:
    pred: int
    succ: int
    type: Literal["FS", "SS", "FF", "SF"]
    lag: int

@dataclass(frozen=True, slots=True)
class CompiledProblem:
    problem_id: str
    horizon_start: datetime
    H: int
    tasks: tuple[CTask, ...]
    resources: tuple[CResource, ...]
    deps: tuple[CDependency, ...]
    preds: tuple[tuple[int, ...], ...]     # per task: indices into deps where task is succ
    succs: tuple[tuple[int, ...], ...]     # per task: indices into deps where task is pred
    topo_order: tuple[int, ...]            # Kahn's algorithm, ties broken by task list order
    weights: Weights                       # effective weights (preset resolved)
    task_index: Mapping[str, int]
    resource_index: Mapping[str, int]
```

`assignment cost` helper (in `objectives.py`): `cost_of(task, resource, units) =
resource.cost_per_hour * units * task.duration / 60`.

---

## 7. Solver protocol, `SolveResult`, violations, metrics

All in `backend/superplanner/engine/solvers/base.py` (protocol + config + result) and
`engine/validator.py` (violation + metrics). Pydantic models so the API can serialize them
directly.

### 7.1 Placement

```python
class Placement(BaseModel):
    task_id: str
    start: int                 # minutes from horizon_start
    end: int                   # minutes from horizon_start
    resource_ids: list[str]    # aligned with task.requirements; [] when none
```

### 7.2 Solver protocol

```python
ProgressCallback = Callable[[ProgressEvent], None]

class Solver(Protocol):
    name: ClassVar[str]                       # "heuristic" | "cpsat" | "ga"
    capabilities: ClassVar[SolverCapabilities]

    def solve(
        self,
        problem: CompiledProblem,
        config: SolverConfig,
        progress_cb: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> SolveResult: ...
```

Rules:
- `solve` must return within `config.time_limit_seconds + 2 s` and must poll `cancel_event`
  at least every 0.5 s of wall time (GA: per individual batch; CP-SAT: solution callback plus a
  watchdog thread that calls `StopSearch()`; heuristic: between rules).
- On cancel, return the best solution found so far with `status="cancelled"`,
  `termination_reason="cancelled"`.
- Solvers never raise for "no solution"; they return `feasibility="unknown"` (or `infeasible`
  if proven). They raise only on programming errors; the pipeline converts exceptions into a
  failed run.
- Solvers return their raw `placements`; the **pipeline** applies left-shift, validation and
  explanation. A solver's own `feasibility` claim is advisory and is overwritten by the
  validator result (exception: proven `infeasible` with no placements).

`SolverCapabilities`: `alternative_resources: bool, calendars: bool, multi_objective: bool,
proves_optimality: bool, proves_infeasibility: bool, uses_hint: bool, deterministic_with_seed: bool`.
Values: heuristic `(T,T,F,F,F,F,T)`, cpsat `(T,T,F,T,T,T,F)` (multi-worker CP-SAT is not
bit-reproducible), ga `(T,T,T,F,F,T,T)` (deterministic only when stopped by generation limit).

### 7.3 `SolverConfig` (engine-side, fully resolved)

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `time_limit_seconds` | `float` 0.5..300 | `10.0` | Budget for this solver call. |
| `seed` | `int` | `0` | |
| `weights` | `Weights` | from problem | |
| `refs` | `ObjectiveRefs \| None` | `None` | `{makespan: float, weighted_tardiness: float, cost: float}`, each `>= 1.0`. `None` only for the baseline heuristic call, which derives refs itself (8.0); the pipeline always passes refs to cpsat/ga. |
| `initial_solution` | `list[Placement] \| None` | `None` | CP-SAT hint / GA seed. |
| `heuristic_rules` | `list[str]` | all five | `edf, slack, spt, lpt, priority` |
| `cpsat` | `CpSatParams` | | `num_workers: int = 8`, `relative_gap: float = 0.0` |
| `ga` | `GaParams` | | see 8.5 |
| `max_alternatives` | `int` 0..5 | `2` | |

### 7.4 `SolveResult`

```python
class ObjectiveValues(BaseModel):
    makespan_minutes: int
    weighted_tardiness: int        # priority-minutes
    cost: float                    # currency, rounded to 2 decimals
    score: float                   # normalized weighted sum, lower is better (8.0)

class SolveResult(BaseModel):
    solver: str                                        # "heuristic:edf", "cpsat", "ga", "cpm" (detailed name; see note)
    status: Literal["completed", "cancelled", "failed"]
    feasibility: Literal["feasible", "infeasible", "unknown"]
    termination_reason: Literal["optimal", "proven_infeasible", "time_limit",
                                "generation_limit", "stagnation", "completed",
                                "cancelled", "preflight_failed", "no_solution", "error"]
    optimality_proven: bool
    objectives: ObjectiveValues | None                 # None when no placements
    placements: list[Placement]                        # [] when none
    violations: list[Violation]                        # filled by validator
    metrics: Metrics | None                            # filled by validator
    iterations: int                                    # rules tried / CP-SAT solutions / GA generations
    elapsed_seconds: float
    best_bound: float | None = None                    # CP-SAT objective bound (scaled score), else None
    alternatives: list["Alternative"] = []
    diagnostics: list[str] = []                        # plain-language notes (e.g. infeasibility probe)

class Alternative(BaseModel):
    label: str                                         # "Fastest", "Fewest late", "Cheapest", "Alternative 2"
    solver: str
    objectives: ObjectiveValues
    placements: list[Placement]
```

Solver naming (binding for engine, API and UI): **phase names** are exactly
`"heuristic" | "cpsat" | "ga" | "cpm"` and are used in `Selection.used`, `PhaseSummary.solver`,
`ProgressEvent.solver` and SSE `solver` fields. **Detailed names** (`SolveResult.solver`,
`Alternative.solver`, schedule `solver` column) may add a suffix after a colon
(`"heuristic:edf"`); the UI displays the part before the colon as the method and the full string
as a tooltip.

### 7.5 Violation and metrics

```python
class Violation(BaseModel):
    code: str                                  # table below
    severity: Literal["hard", "soft"]
    task_ids: list[str]
    resource_ids: list[str]
    message: str                               # plain language, uses terminology
    details: dict[str, Any] = {}

class Metrics(BaseModel):
    makespan_minutes: int
    total_tardiness_minutes: int               # unweighted sum of T_t
    weighted_tardiness: int
    late_tasks: int                            # tasks with T_t > 0 (soft deadlines)
    hard_deadline_misses: int
    cost: float
    scheduled_tasks: int
    total_tasks: int
    utilization: dict[str, float]              # resource_id -> 0..1
```

Utilization of resource `k` = `busy_unit_minutes_k / (capacity_k * available_minutes_k)` where
both are measured inside `[0, makespan)` and `available_minutes_k` is the total length of
`windows_k` intersected with `[0, makespan)`. 0.0 if the denominator is 0. Rounded to 4 decimals.

Violation codes (validator):

| code | severity | details |
|------|----------|---------|
| `TASK_MISSING` | hard | `{}` |
| `TASK_DUPLICATE` | hard | `{"count": n}` |
| `UNKNOWN_TASK` | hard | `{}` |
| `DURATION_MISMATCH` | hard | `{"expected": d, "actual": e-s}` |
| `OUTSIDE_HORIZON` | hard | `{"start": s, "end": e, "horizon_end": H}` |
| `EARLIEST_START_VIOLATED` | hard | `{"earliest": r, "start": s}` |
| `DEPENDENCY_VIOLATED` | hard | `{"predecessor": a, "successor": b, "type": "FS", "lag_minutes": L, "required_minute": x, "actual_minute": y}` |
| `RESOURCE_COUNT_MISMATCH` | hard | `{"expected": n, "actual": m}` |
| `RESOURCE_NOT_ELIGIBLE` | hard | `{"requirement_index": i}` |
| `RESOURCE_DUPLICATE` | hard | `{}` |
| `CAPACITY_EXCEEDED` | hard | `{"from": m1, "to": m2, "usage": u, "capacity": c}` one per maximal overload interval per resource |
| `CALENDAR_VIOLATED` | hard | `{"start": s, "end": e}` |
| `LOCK_VIOLATED` | hard | `{"locked_start": s0, "start": s, "locked_resource_ids": [...]}` |
| `HARD_DEADLINE_MISSED` | hard | `{"deadline": D, "end": e, "minutes_late": e-D}` |
| `DEADLINE_MISSED` | soft | `{"deadline": D, "end": e, "minutes_late": e-D}` |

Message examples (terminology `task="Operation"`, `resource="Machine"`):
- `Operation "J1 Milling" must start after "J1 Cutting" finishes (finish-to-start), but starts 30 minutes too early.`
- `Machine "Mill 1" is overbooked from Tue 20 Oct 10:00 to 10:30 (2 of 1 in use).`
- `Operation "J3 Assembly" finishes 2h 15m after its due date (Wed 21 Oct 18:00).`

### 7.6 Engine public API (`superplanner/engine/__init__.py`)

```python
def preflight(problem: Problem) -> PreflightReport                    # 9.1
def analyze(problem: Problem) -> ValidateReport                       # preflight + CPM (9.2)
def optimize(problem: Problem, request: OptimizeRequest,
             progress_cb: ProgressCallback | None = None,
             cancel_event: threading.Event | None = None) -> OptimizeOutcome
def validate_schedule(problem: Problem, placements: list[Placement]) -> ValidationReport
def explain_schedule(problem: Problem, placements: list[Placement]) -> ScheduleExplanation
__version__: str  # "0.1.0"
```

`OptimizeRequest` (mirrors the API `SolverRunRequest`, section 14.5):
`strategy: Literal["auto","heuristic","cpsat","ga","hybrid"] = "auto"`,
`time_limit_seconds: float = 10` (1..300), `seed: int = 0`,
`objectives: Objectives | None = None` (overrides the problem's),
`ga: GaParams = GaParams()`, `cpsat: CpSatParams = CpSatParams()`,
`max_alternatives: int = 2`, `initial_solution: list[Placement] | None = None`.

`OptimizeOutcome`: `{ selection: Selection, result: SolveResult, explanation: ScheduleExplanation | None,
preflight: PreflightReport, refs: ObjectiveRefs, phases: list[PhaseSummary] }` where
`Selection = {requested: str, used: list[str], reasons: list[str]}` and
`PhaseSummary = {solver, status, feasibility, termination_reason, objectives, elapsed_seconds}`.

`ValidationReport = {feasibility: "feasible"|"unknown", violations: list[Violation], metrics: Metrics}`
(the validator alone never claims `infeasible`). Do not confuse it with `ValidateReport` (9.2,
preflight + CPM of a problem).

`validate_schedule` and `explain_schedule` compile the problem first and raise
`CompileError(issues: list[Issue])` (exported from `superplanner.engine`) when the problem has
preflight errors. `optimize` never raises for invalid input (8.7 step 1). All public functions
are synchronous and thread-safe (no module-level mutable state).

### 7.7 Progress events (engine -> orchestrator)

```python
class ProgressEvent(BaseModel):
    type: Literal["phase_started", "progress", "phase_completed"]
    solver: str
    elapsed_seconds: float                 # since optimize() started
    iteration: int | None = None           # generation (GA), solution count (CP-SAT), rule index (heuristic)
    best_score: float | None = None
    best_objectives: ObjectiveValues | None = None
    feasible_found: bool = False
    extra: dict[str, Any] = {}             # GA: {"feasible_fraction", "mutation_rate", "diversity"};
                                           # CP-SAT: {"best_bound"}
                                           # phase_started: {"reason": selector sentence}
                                           # phase_completed: {"status", "termination_reason", "feasibility"}
```

Only the pipeline emits `phase_started`/`phase_completed` (solvers emit only `progress`). For
`phase_completed`, `best_objectives` carries the phase result's objectives (or `None`). The API
maps these to SSE events (section 15) by lifting `extra.reason`, `extra.status`,
`extra.termination_reason`, `extra.feasibility` to top-level fields and renaming
`best_objectives` to `objectives`; `progress` events keep `extra` as is. The baseline phase and
the infeasibility probe (8.7 step 7) do not emit phase events for the probe; the probe only adds
`diagnostics`.

---

## 8. Algorithm designs

### 8.0 Objective score (feasibility first, normalized weights)

Minutes, priority-minutes and money must not be added raw. Each run computes reference values
`refs` from the baseline heuristic's rule results (ranking needs refs, so refs cannot come from
the "best" schedule): `refs.k = max(1.0, min over complete rule results of objective k)`, where
"complete" means every task placed (hard-deadline misses allowed). If no rule result is complete,
`refs.makespan = max(1, CPM lower bound)`,
`refs.weighted_tardiness = max(1, sum(priority_t * d_t))`, `refs.cost = max(1, sum of min-cost
assignment per task)`.

```
score = w_m * makespan / refs.makespan + w_t * weighted_tardiness / refs.weighted_tardiness
      + w_c * cost / refs.cost
```

Score is only comparable **within one run**. The UI compares schedules across runs by raw
metrics, never by score.

Ranking key for any candidate (heuristic rule results, GA individuals, final pick):

```
rank_key = (0 if complete and no hard violations else 1,
            hard_violation_score,          # 0 for feasible
            score)
hard_violation_score = 1_000_000 * unscheduled_tasks + 10_000 * lock_conflicts
                     + sum(minutes of hard-deadline excess)
                     + sum(minutes of dependency/lock deficit)
```

`lock_conflicts` = locked tasks that the decoder had to force into an overloaded or closed slot
(`DecodeResult.lock_conflicts`). The fast GA/heuristic ranking uses decoder output plus
`compute_metrics`; the **final pick and every reported feasibility** use the full `validate()`.

### 8.1 Decoder: serial schedule generation scheme (`engine/decoder.py`)

```python
@dataclass
class DecodeResult:
    placements: list[Placement]          # only placed tasks
    unscheduled: list[int]               # task indices that could not be placed
    reasons: dict[int, str]              # task idx -> binding reason code (diagnostic only)
    repairs: int                         # resource-gene fallbacks used
    lock_conflicts: int                  # locked tasks forced into an overloaded/closed slot (step 2)

def decode(problem: CompiledProblem,
           priority: Sequence[float],                    # per task; lower value = scheduled first
           resource_choice: Mapping[tuple[int, int], int] | None = None,  # (task, req) -> alternative position
           ) -> DecodeResult
```

Algorithm:
1. Initialize an empty **resource profile** per resource: a sorted list of `(start, end, units)`.
2. Place every locked task first at `locked_start`. Resources: `locked_resources` if given,
   else greedy choice (step 5) evaluated only at `t = locked_start`; if no choice fits, use the
   first alternative of each requirement anyway (the validator will flag it). Locked tasks are
   reserved in the profile even if this overloads it.
3. Repeat until all tasks are placed or unschedulable: eligible set = unplaced tasks whose
   predecessors are all placed (or unschedulable). Pick the eligible task with the smallest
   `priority[t]`, ties broken by `topo_order` position.
4. If any predecessor is unschedulable, mark the task unschedulable (reason `PREDECESSOR_UNSCHEDULED`).
   Else compute `ES = max(release, max over predecessor deps of the 5.3 lower bound, 0)`.
5. Find the smallest `t >= ES` with `t + d <= H` such that, for every requirement `i`, a resource
   `k` exists that is (a) the fixed choice `alternatives[resource_choice[(t,i)]]` when given,
   otherwise any alternative; (b) distinct from the resources chosen for other requirements;
   (c) has a window `w` with `w.start <= t` and `t + d <= w.end`; (d) has
   `max usage over [t, t+d) + units <= capacity`.
   - Candidate times: `{ES} ∪ {window starts >= ES} ∪ {profile interval ends >= ES}` over the
     relevant resources (fixed choices only, or all alternatives in greedy mode), ascending. The
     earliest feasible start is always in this set.
   - Greedy tie-break among feasible alternatives at the same `t`: lowest `cost_per_hour`, then
     lowest busy unit-minutes so far, then alternatives order. Requirements are assigned in index
     order.
   - If a fixed choice has no window of length `>= d` at all (structurally impossible), fall back
     to greedy for that requirement and increment `repairs`.
   - Milestones and tasks without requirements: `t = ES` (if `ES <= H - d`).
6. If no `t` exists, mark unschedulable (reason `NO_SLOT`). Otherwise place and record a reason
   (`DEPENDENCY`, `EARLIEST_START`, `HORIZON_START`, `RESOURCE_BUSY`, `CALENDAR`) by the same rule
   as explain.py (section 11).
7. Hard deadlines are not enforced by the decoder (earliest placement is already the best it can
   do); misses appear as hard violations and lower the GA rank.

Complexity: `O(n * c * q)` where `c` = candidate times per task and `q` = profile checks; adequate
for 2000 tasks in Python (benchmark in tests; profile list is per resource, bisect for lookup).

### 8.2 Left-shift compaction (`decoder.left_shift`)

```python
def left_shift(problem: CompiledProblem, placements: list[Placement]) -> list[Placement]
```

Applied by the pipeline to **every** solver result before validation. Repeat passes until no task
moves: for each non-locked task in ascending current start, keep its resources, compute
`lb = max(release, 0, predecessor bounds using current placements)` and move it to the earliest
`t in [lb, current_start)` that satisfies calendars and capacity against all other tasks at their
current positions (same candidate-time rule as 8.1). Because every dependency is a lower bound on
the successor (5.3), moving a task earlier never breaks a dependency where it is the predecessor;
capacity/calendar are checked explicitly. Makespan and tardiness can only decrease, cost is
unchanged, so the score never worsens. Purpose: CP-SAT may return tasks later than necessary;
compaction gives users intuitive schedules and makes explanations meaningful. If a pass finds an
input that is already infeasible (e.g. GA best-effort), it still only performs moves that are
locally valid.

### 8.3 Heuristic solver (`solvers/heuristic.py`)

Runs `decode` once per priority rule (greedy resources) and returns the best by `rank_key`;
other complete feasible rule results become alternative candidates. Rules (lower = first):

| rule | priority value for task t |
|------|---------------------------|
| `edf` | `(D_t if deadline else +inf, LS_t, -priority_t)` |
| `slack` | `(LS_t, -priority_t)` where `LS` from CPM (9.2) |
| `spt` | `(d_t, LS_t)` |
| `lpt` | `(-d_t, LS_t)` |
| `priority` | `(-priority_t, LS_t)` |

Tuple keys are converted into a float order by sorting (rank position / n). `iterations` = rules
run. `termination_reason = "completed"`. If `config.refs is None` (baseline phase), the
heuristic computes refs from its own rule results exactly as in 8.0 before ranking. Both the
heuristic and the pipeline use the single function
`objectives.compute_refs(rule_objectives: list[ObjectiveValues | None], problem, cpm) -> ObjectiveRefs`
so the two always agree.

**Resource-free shortcut:** if the problem has no requirements on any task and no locks, the
`slack` rule schedule is the CPM early-start schedule, which minimizes every end time at once and
therefore every objective. The pipeline returns it with `solver="cpm"`,
`optimality_proven=true`, `termination_reason="optimal"`.

### 8.4 CP-SAT solver (`solvers/cpsat.py`, OR-Tools 9.15)

Variables per task `t` (domain `[r_t, H - d_t]`; locked: fixed to `locked_start`):
- `S_t` IntVar, `E_t = S_t + d_t` (affine expression; create an IntVar only if needed),
  interval `I_t = NewFixedSizeIntervalVar(S_t, d_t)` (not added to any resource constraint itself).
- For each requirement `i` and alternative position `j` (resource `k`):
  - BoolVar `x[t,i,j]`; `AddExactlyOne(x[t,i,*])`.
  - Optional interval `O[t,i,j] = NewOptionalFixedSizeIntervalVar(S_t, d_t, x[t,i,j])` (skip for
    milestones; requirements are empty there anyway).
  - **Calendar:** let `F = [(w.start, w.end - d_t) for w in windows_k if w.end - w.start >= d_t]`.
    If `F` empty: `x[t,i,j] == 0`. Else
    `AddLinearExpressionInDomain(S_t, Domain.FromIntervals(F)).OnlyEnforceIf(x[t,i,j])`.
- Distinct resources per task: for each resource `k` appearing in several requirements of `t`,
  `sum(x[t,i,j] for those) <= 1`.
- Locked resources: fix `x[t,i,j] = 1` for `locked_resources[i]`.

Global constraints:
- Capacity per resource `k`: if `capacity_k == 1` and all demands are 1,
  `AddNoOverlap(O[...] on k)`; else `AddCumulative(O[...] on k, demands=units, capacity_k)`.
- Dependencies (5.3): `S_b >= E_a + L` (FS), `S_b >= S_a + L` (SS), `E_b >= E_a + L` (FF),
  `E_b >= S_a + L` (SF).
- Hard deadlines: `E_t <= D_t` (domain tightening).
- Tardiness: `T_t ∈ [0, H]`, `T_t >= E_t - D_t` for soft deadlines.
- Makespan: `M ∈ [0, H]`, `AddMaxEquality(M, [E_t...])` (or `M >= E_t` for all t).

Objective (integer "points", `POINTS = 10_000_000`, i.e. score * 10^7):
`minimize  cm * M + ct * sum(priority_t * T_t) + sum(cpts[t,i,j] * x[t,i,j])` where
`cm = round(POINTS * w_m / refs.makespan)`, `ct = round(POINTS * w_t / refs.weighted_tardiness)`,
`cpts[t,i,j] = round(POINTS * w_c * cost_of(t, k, units_i) / refs.cost)`. A coefficient of a
weight > 0 that rounds to 0 becomes 1; weights of 0 drop the term (and the `T`/`M` variables if
unused, except `M` is still created for reporting). Worst-case magnitudes stay far below int64
(`M <= 527040`, coefficients `<= 10^7 * w`). Costs therefore need no separate cents variable.
`best_bound` is reported in score units (`bound / POINTS`).

Search configuration: `max_time_in_seconds = time_limit`, `num_workers = cpsat.num_workers`,
`random_seed = seed`, `relative_gap_limit = cpsat.relative_gap` (0 = prove optimal). Hints:
`AddHint(S_t, start)` and `AddHint(x, 1/0)` from `config.initial_solution` (pipeline passes the
baseline or a replan source schedule). Progress: a `CpSolverSolutionCallback` extracts the
incumbent placements on every solution, emits `progress` (throttled by orchestrator), and calls
`StopSearch()` when `cancel_event` is set; a watchdog thread also checks `cancel_event` every
0.2 s for the case where no solutions arrive.

Status mapping:

| CP-SAT status | feasibility | termination_reason | optimality_proven |
|---------------|-------------|--------------------|-------------------|
| OPTIMAL | feasible | optimal | true (w.r.t. the weighted model) |
| FEASIBLE, cancelled | feasible | cancelled | false |
| FEASIBLE | feasible | time_limit | false |
| INFEASIBLE | infeasible | proven_infeasible | false |
| UNKNOWN | unknown | time_limit (or cancelled) | false |
| MODEL_INVALID | raises `SolverError` (programming bug) | | |

### 8.5 Genetic algorithm (`solvers/ga.py`)

Representation (random keys, indirect):
- `keys`: `list[float]` in `[0,1)`, one per task (locked tasks ignored by the decoder).
- `genes`: `list[float]` in `[0,1)`, one per `(task, requirement)` with >= 2 alternatives and not
  locked; alternative position = `min(floor(g * n_alt), n_alt - 1)`.
- Decode: `decode(problem, keys, {(t,i): pos})`; the decoder enforces deps/capacity/calendars;
  infeasibility can only come from unschedulable tasks, hard deadlines or locks.

`GaParams` (defaults; all exposed in expert mode):

| param | type | default | bounds |
|-------|------|---------|--------|
| `population_size` | int | `min(80, max(20, n_tasks // 2))` when `None` | 10..300 |
| `max_generations` | int | 300 | 1..10000 |
| `stagnation_generations` | int | 40 | 5..1000 |
| `crossover_rate` | float | 0.9 | 0..1 |
| `mutation_rate` | float | 0.1 (per gene, initial) | 0.01..0.5 (never 0) |
| `mutation_sigma` | float | 0.1 | 0.01..0.5 |
| `swap_rate` | float | 0.2 (per child) | 0..1 |
| `elite_count` | int | 2 | 0..10 |
| `tournament_size` | int | 3 | 2..10 |
| `archive_size` | int | 10 | 1..50 |

Population initialization (never fully random):
1. One individual per heuristic rule (encode its order as `keys = rank/n`, its resource choices
   as `genes = (pos + 0.5)/n_alt`), plus `initial_solution` if given (keys from start order).
   Seeds are capped at 20% of the population.
2. 30%: mutated copies of seeds (mutation applied at 2x the initial rate).
3. Remainder: uniform random keys and genes.

Generation loop:
1. Evaluate each new individual: decode -> placements -> `validator.compute_metrics` (the fast,
   shared metrics function) + decoder's unscheduled list + hard-deadline/lock checks -> `rank_key`.
2. Elitism: copy the `elite_count` best (by `rank_key`) unchanged.
3. Fill the rest: tournament selection (`tournament_size`, best `rank_key` wins) of two parents;
   with probability `crossover_rate` **uniform crossover** (each key/gene from either parent with
   p=0.5), else clone parent 1.
4. Mutation: each key/gene with probability `mutation_rate` gets `+ N(0, mutation_sigma)` and is
   wrapped into `[0,1)` (`x % 1.0`); resource genes may instead be reset uniformly (p=0.5 of a
   mutation event). With probability `swap_rate` swap two random task keys.
5. Adaptation: if the best `rank_key` did not improve for 10 generations or diversity (mean
   per-key standard deviation across the population) < 0.05, multiply `mutation_rate` and
   `mutation_sigma` by 1.5 (capped at bounds); reset both to initial values on improvement.
   The rate never goes below 0.01.
6. Archive: every evaluated **feasible** individual is offered to a Pareto archive over
   `(makespan_minutes, weighted_tardiness, cost)`; dominated entries are dropped; identical
   objective vectors are deduplicated; if over `archive_size`, keep the lowest scores.
7. Emit `progress` with `iteration = generation`, `best_score`, `best_objectives`,
   `extra = {feasible_fraction, mutation_rate, diversity}`.

Stopping (first that applies): `cancel_event` -> `cancelled`; time limit -> `time_limit`;
`max_generations` -> `generation_limit`; no improvement for `stagnation_generations` ->
`stagnation`. Randomness: a single `random.Random(seed)` instance; no global RNG, no
time-dependent behaviour other than the time limit. Same seed + same params + a stop by
generations or stagnation must produce identical results (tested).

Result: best individual by `rank_key`; `alternatives` from the archive (8.6).

### 8.6 Alternatives

The pipeline collects every complete, validated-feasible candidate from all phases (heuristic
rules, CP-SAT incumbent, GA archive), removes those with the same objective vector as the
primary, keeps the non-dominated set on `(makespan, weighted_tardiness, cost)`, and chooses up to
`max_alternatives`: first the best-makespan ("Fastest"), best-weighted-tardiness ("Fewest late"),
best-cost ("Cheapest") candidates if they differ from the primary and each other, then the
remaining by score ("Alternative N"). Each alternative is left-shifted and validated; only
feasible ones are kept.

### 8.7 Selector and pipeline (`engine/selector.py`, `engine/pipeline.py`)

Size measures: `n` = non-locked tasks, `q` = total `(task, requirement, alternative)` triples.
Constants: `CPSAT_MAX_TASKS = 300`, `CPSAT_MAX_OPTIONALS = 3000`, `MIN_BUDGET_FOR_SEARCH = 2.0 s`.

Pipeline steps:
1. `preflight`; any error -> result `feasibility="infeasible"` if any error code is in
   `PROVEN_INFEASIBLE_CODES = {DEPENDENCY_CYCLE, UNITS_EXCEED_CAPACITY, NO_FITTING_WINDOW,
   EARLIEST_AFTER_HORIZON, DEADLINE_BEFORE_EARLIEST, HARD_DEADLINE_IMPOSSIBLE, HORIZON_TOO_SHORT}`
   (constant in `preflight.py`), otherwise `unknown` (malformed input is not "proven infeasible"); `termination_reason="preflight_failed"`; issues are copied
   into `diagnostics`. (The API rejects runs with preflight errors before queuing, 14.5; this
   path covers direct engine calls.)
2. Compile; run CPM.
3. Resource-free shortcut (8.3) -> done, for **every** requested strategy:
   `Selection.used = ["cpm"]`, reason "No task needs a resource: the earliest-start (critical
   path) schedule is provably optimal."
4. Baseline: heuristic with all rules. Budget accounting: `deadline = t0 + time_limit_seconds`
   where `t0` is when `optimize()` starts; the baseline is not given its own limit (it is fast) and
   its time is consumed from the budget; each later phase gets `time_limit_seconds = remaining`
   (hybrid: cpsat `0.6 * remaining`, then ga gets what is left). A phase is skipped if less than
   0.5 s remains. `optimize()` must return within `time_limit_seconds + 3 s` for problems within
   the limits of 3.2 (tested). Compute `refs` (8.0).
5. Strategy resolution (`Selection.reasons` must contain one sentence per rule applied):

| requested | rule | used |
|-----------|------|------|
| `heuristic` | always | `[heuristic]` |
| `cpsat` | always | `[heuristic, cpsat]` (baseline as hint) |
| `ga` | always | `[heuristic, ga]` (baseline as seeds) |
| `hybrid` | always | `[heuristic, cpsat (60% budget), ga (40%, seeded with best so far)]` |
| `auto` | `time_limit < 2 s` | `[heuristic]` - "Time budget under 2 s: using fast priority rules only." |
| `auto` | `n <= 300 and q <= 3000` | `[heuristic, cpsat]` - "Small/medium problem (n tasks, q options): exact constraint solver seeded with the best heuristic." |
| `auto` | otherwise | `[heuristic, ga]` - "Large problem: genetic algorithm seeded with heuristic schedules." |
| `auto` | after cpsat returns `unknown` with budget left >= 2 s | append `ga` - "Constraint solver found no solution in time; continuing with the genetic algorithm." |

6. Final pick: best `rank_key` across all phase results (so a strategy can never return worse
   than the baseline), left-shift, validate, set final `feasibility`:
   - validator clean and complete -> `feasible`;
   - else if any phase proved infeasibility (CP-SAT INFEASIBLE) -> `infeasible` (placements of the
     best-effort schedule are still returned, flagged);
   - else `unknown`.
   `optimality_proven` is true only if the chosen result came from CP-SAT OPTIMAL (or CPM
   shortcut) and left-shift did not change the score.
7. **Infeasibility probe** (only when final is not `feasible`, the problem has hard deadlines or
   locks, and >= 1 s budget remains, capped at 25% of the budget): re-run the heuristic with all
   hard deadlines treated as soft and, if that produces a feasible schedule, add to
   `diagnostics`: "If the hard deadlines of X, Y were relaxed, a schedule exists; they would be
   late by 3h 10m and 45m." Similarly for locks: if locks exist, re-run the heuristic with all
   locks removed; if that is feasible, name the locked tasks that appear in hard violations of
   the best-effort schedule ("Unlocking Z would remove the conflict"). The probe never replaces
   the result; it only appends `diagnostics` strings.
8. Alternatives (8.6), explanation (11).

---

## 9. Preflight and CPM

### 9.1 Preflight (`engine/preflight.py`)

```python
class Issue(BaseModel):
    code: str
    severity: Literal["error", "warning"]      # error blocks solving
    message: str                               # plain language with terminology
    task_ids: list[str] = []
    resource_ids: list[str] = []
    field: str | None = None                   # JSON-pointer-ish path, e.g. "tasks[3].requirements[0]"

class PreflightReport(BaseModel):
    ok: bool                                   # no errors
    issues: list[Issue]
```

Checks (in this order; all run, results concatenated):

| code | severity | condition |
|------|----------|-----------|
| `NO_TASKS` | warning | `tasks == []` |
| `TOO_LARGE` | error | > 2000 tasks or > 200 resources or > 10000 deps |
| `DUPLICATE_ID` | error | duplicate task id, resource id, or task/resource id collision |
| `UNKNOWN_RESOURCE` | error | requirement alternative or lock resource not found |
| `UNKNOWN_TASK` | error | dependency endpoint not found |
| `SELF_DEPENDENCY` | error | predecessor == successor |
| `DUPLICATE_DEPENDENCY` | error | repeated ordered pair |
| `DEPENDENCY_CYCLE` | error | one issue per cycle found; `task_ids` = the cycle in order; message "A -> B -> C -> A form a loop; at least one of these dependencies must be removed." |
| `UNITS_EXCEED_CAPACITY` | error | `units > capacity` for **every** alternative of a requirement (warning if only some; those alternatives are effectively ineligible and the compiler drops them) |
| `NO_FITTING_WINDOW` | error | for some requirement, no alternative has a window of length `>= duration` (message names the longest available window) |
| `INVALID_CALENDAR` | error | window start >= end (after HH:MM parse), `"24:00"` used as a window start, blocked start >= end |
| `EMPTY_CALENDAR` | warning | resource has no availability in the horizon |
| `EARLIEST_AFTER_HORIZON` | error | `r_t + d_t > H` |
| `DEADLINE_BEFORE_EARLIEST` | error (hard) / warning (soft) | `D_t < r_t + d_t` |
| `DEADLINE_BEFORE_HORIZON` | error | deadline < horizon_start |
| `LOCK_INVALID` | error | lock outside horizon, before release, resource_ids length/eligibility mismatch |
| `HARD_DEADLINE_IMPOSSIBLE` | error | CPM `EF_t > D_t` for a hard deadline: "Even with unlimited resources, X cannot finish before ... (earliest possible finish ...)." |
| `HORIZON_TOO_SHORT` | error | CPM lower-bound makespan > H |
| `SOFT_DEADLINE_UNREACHABLE` | warning | CPM `EF_t > D_t` for a soft deadline: "will be at least 2h late" |
| `UNUSED_RESOURCE` | warning | resource referenced by no requirement |
| `MILESTONE_WITH_LOCKED_RESOURCES` | error | milestone lock with non-empty resource_ids (reported instead of `LOCK_INVALID` for milestones) |
| `LAG_OUT_OF_RANGE` | error | `abs(lag_minutes) > H` |

CPM-based checks run only when there are no structural errors (unknown refs, cycles).
Messages use `terminology.task`/`terminology.resource` and names (not only ids), and format times
as `Tue 20 Oct 10:00` in the plan offset (helper `timeutil.fmt_minute`).

### 9.2 CPM and graph (`engine/graph.py`)

```python
def find_cycles(n: int, edges: list[tuple[int,int]]) -> list[list[int]]   # Tarjan SCC; for each SCC of size>1, one simple cycle via DFS
def topological_order(n, edges) -> list[int]                              # Kahn, ties by index; raises CycleError
def cpm(problem: CompiledProblem) -> CpmResult
```

Forward pass in topological order: `ES_b = max(r_b, 0, bound_FS/SS/FF/SF over preds)` with the
5.3 lower bounds using `ES`/`EF` of predecessors; `EF = ES + d`. Locked tasks: `ES = EF - d =
locked_start` (if a predecessor bound exceeds it, preflight reports `LOCK_INVALID` with the
reason "conflicts with dependency"). Project end `PE = max EF` (0 if none).

Backward pass in reverse topological order: `LF_a = min(PE, min over succ deps)` with
FS: `LS_b - L`; SS: `LS_b - L + d_a`; FF: `LF_b - L`; SF: `LF_b - L + d_a`; `LS = LF - d`.
`slack = LS - ES` (>= 0). Critical tasks: `slack == 0`. `critical_path`: one chain from a task
with `EF == PE` back through predecessors whose bound equals the successor's `ES`, ordered
start-to-end. Calendars and capacities are ignored (the result is a lower bound).

```python
class CpmTask(BaseModel):
    es: int; ef: int; ls: int; lf: int; slack: int; critical: bool
class CpmResult(BaseModel):
    lower_bound_makespan_minutes: int
    tasks: dict[str, CpmTask]
    critical_path: list[str]
class ValidateReport(BaseModel):   # returned by analyze() and the /validate endpoint
    ok: bool
    issues: list[Issue]
    cpm: CpmResult | None          # None if structural errors prevent it
```

---

## 10. Independent validator (`engine/validator.py`)

```python
def validate(problem: CompiledProblem, placements: list[Placement]) -> ValidationReport
def compute_metrics(problem: CompiledProblem, placements: list[Placement]) -> Metrics
```

Independence rules: written against section 5 only; does not import `decoder`, solvers or
`graph`. Uses its own sweep-line for capacity: for each resource, events `(start, +units)` and
`(end, -units)` sorted by time with `-` before `+` at equal times; report maximal intervals where
running usage > capacity. Calendar check: binary search in `windows`. Every check H1-H10 runs and
all violations are reported (not fail-fast), sorted by `(severity hard first, code, first task id)`.
Placements for unknown tasks are reported and excluded from other checks. Metrics are computed
over placed, known tasks. `feasibility = "feasible"` iff there are no hard violations, else
`"unknown"`. The API also uses it to check stale schedules on approval (14.6).

---

## 11. Explanation logic (`engine/explain.py`)

Solver-agnostic: input is only `(CompiledProblem, placements)`.

```python
class StartReason(BaseModel):
    code: Literal["LOCKED", "HORIZON_START", "EARLIEST_START", "DEPENDENCY",
                  "RESOURCE_BUSY", "CALENDAR", "OPTIMIZER_CHOICE", "NOT_SCHEDULED"]
    message: str
    related_task_ids: list[str] = []
    resource_ids: list[str] = []

class TaskExplanation(BaseModel):
    task_id: str
    reasons: list[StartReason]           # primary first
    on_critical_chain: bool              # schedule critical chain (below)
    cpm_critical: bool
    cpm_slack_minutes: int
    lateness_minutes: int                # max(0, end - deadline), 0 if no deadline
    deadline_status: Literal["none", "on_time", "late_soft", "late_hard"]

class ScheduleExplanation(BaseModel):
    tasks: dict[str, TaskExplanation]
    critical_chain: list[str]            # ordered start-to-end
    cpm_critical_path: list[str]
    summary: list[str]                   # e.g. "3 of 24 Operations finish late; the chain J2-1 -> J2-2 -> J2-3 determines completion."
```

Primary reason for a placed task `t` with start `s` (first rule that matches; ties add extra
reasons):
1. `locked_start` set -> `LOCKED` ("Fixed by you" / "Frozen by replanning").
2. Compute `lb_dep` = max dependency bound (5.3) using actual predecessor placements, and `r_t`.
   If `s == lb_dep` (and some dependency exists) -> `DEPENDENCY` naming every predecessor whose
   bound equals `s` ("Starts as soon as J1 Cutting finishes").
3. If `s == r_t > 0` -> `EARLIEST_START`. If `s == 0` -> `HORIZON_START`.
4. Otherwise examine `t' = s - 1` with the assigned resources: if for some resource `k`,
   `[t', t'+d)` is not inside one window -> `CALENDAR` ("Waits for Mill 1 to become available
   at Tue 06:00"); else if capacity is exceeded at `t'` by other tasks -> `RESOURCE_BUSY`, with
   `related_task_ids` = tasks on `k` overlapping `[t', t'+d)` ("Waits for Mill 1, busy with J2
   Milling until 10:00").
5. If none applies (only possible for solver output that could legitimately start earlier, e.g.
   left-shift was skipped) -> `OPTIMIZER_CHOICE` ("Could start at X; placed later to improve the
   overall plan").
Unplaced tasks -> `NOT_SCHEDULED`.

Schedule critical chain: start from the placed task with `end == makespan` (ties: highest
priority, then lowest index); repeatedly follow the primary reason: `DEPENDENCY` -> the binding
predecessor; `RESOURCE_BUSY` -> the blocking task with the latest end; stop at `CALENDAR`,
`EARLIEST_START`, `HORIZON_START`, `LOCKED`. Reverse to start-to-end order.

Phase 2a (`docs/PHASE2.md` 2.14): `ScheduleExplanation.duration_risk` (`DurationRisk`, optional, omitted when no
task has a `duration_estimate`) sums the critical chain's estimates and appends a PERT note to `summary`.

---

## 12. Templates / domain adapter contract (`backend/superplanner/templates`)

```python
class TemplateParameter(BaseModel):
    name: str
    label: str
    type: Literal["int", "date", "string", "string_list"]
    default: Any
    min: int | None = None
    max: int | None = None
    help: str = ""

class DomainTemplate(Protocol):
    id: str                       # "manufacturing" | "exam_prep" | "project" | "blank"
    name: str
    description: str
    domain: str
    terminology: Terminology
    parameters: list[TemplateParameter]
    def build(self, *, name: str, start_date: date, utc_offset: str,
              params: dict[str, Any]) -> Problem: ...

TEMPLATES: dict[str, DomainTemplate]        # registry in templates/__init__.py
def get_template(template_id: str) -> DomainTemplate          # KeyError -> 404 in API
```

Contract rules:
- `build` is deterministic (no randomness; or `random.Random(42)`), relative to `start_date`
  (`horizon_start = start_date 00:00` at `utc_offset`, e.g. `"+05:30"`), and returns a Problem
  that passes preflight with **no errors** at default parameters (tested).
- Unknown params -> `ValueError` (API 422). Missing params -> defaults.
- Adapters may put domain data in `metadata` (task and problem) but must express every
  scheduling rule through the core model. Adapters never bypass preflight/validator.
- Adding a domain = adding a module + registry entry; no engine change.

Templates:

**manufacturing** - params: `jobs` int 1..20 (default 5), `due_in_days` int 2..30 (default 5).
Machines: `CUT1` (Saw), `MILL1`, `MILL2` (alternatives), `ASM1` (Assembly bench), plus `OPS`
"Operators" kind person capacity 2. Calendar Mon-Fri `06:00-14:00` + `14:00-22:00` (two shifts,
merged), Sat `06:00-14:00`; maintenance block on `MILL1` day 2 10:00-12:00. Each job `Jk` has
operations cut -> mill -> assemble (FS chain; assemble also requires `OPS` x1, demonstrating
multi-resource requirements), deterministic durations (e.g. `60 + 15*(k%4)` min), soft due date
`start + min(due_in_days, 1 + k)` days at 18:00, priority `10 - k%5`. Terminology per 3.3.

**exam_prep** - params: `exam_in_days` int 7..180 (default 30), `subjects` string_list
(default `["Polity","History","Geography"]`), `topics_per_subject` int 1..10 (default 3).
Resource `STUDENT` kind `time`, capacity 1, calendar weekdays `06:00-08:00`, `18:00-21:00`,
weekends `09:00-13:00`, `15:00-19:00`. Per topic: `Study` (90 min, chained FS within a subject
as prerequisites), `Revision 1` (45 min, FS lag 2 days after study), `Revision 2` (30 min, FS
lag 7 days after revision 1, soft deadline = exam - 2 days). Per subject: `Mock test` (120 min)
after all its Revision 1 sessions. `Full mock` (180 min) after all subject mocks, hard deadline
exam - 1 day. Milestone `EXAM` with `earliest_start` = exam day 10:00, hard deadline same time,
FS from the full mock. `metadata.difficulty` 1..5 on topics (editable). Lag sizes shrink
automatically if `exam_in_days` is small (`revision2_lag = min(7, exam_in_days // 4)` days).

**project** - params: `team_size` int 3..8 (default 4). Team members with
`metadata.skills`, Mon-Fri `09:00-17:00`, cost 40-70/h. Tasks require one member whose skills
include the task's `metadata.skill` (alternatives computed at build time). Because tasks are
non-preemptive within one window, work longer than a day is split into parts of <= 480 min
chained FS ("Build API (1/2)", "(2/2)"). Milestones "Design approved" and "Release" (hard
deadline, `start + 20` days 17:00).

**blank** - no tasks/resources, `horizon_days = 30`, generic terminology.

**Later domain adapter: financial planning** (deferred, see 20). Per the follow-up document the
financial module is an *allocation/portfolio* problem class (contributions, allocations, cash
reserves, rebalancing under uncertainty) rather than a scheduling problem. It will need the
layered universal model (goal, decision, state, rule, uncertainty models) and a problem compiler
targeting MILP/simulation, so it must not be forced into the task/resource schema. The MVP keeps
the door open by (a) leaving `domain` and `metadata` free-form, (b) the solver protocol taking a
compiled model, (c) the template registry.

---

## 13. Persistence (`backend/superplanner/api/db`)

SQLAlchemy 2.x ORM (sync), `DATABASE_URL` env var, default
`sqlite:///<repo>/backend/superplanner.db`. SQLite: `connect_args={"check_same_thread": False}`,
`PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`. Tables are created with
`Base.metadata.create_all()` at startup (Alembic deferred). JSON columns use `sqlalchemy.JSON`
(JSONB on Postgres via `with_variant`). IDs are `str` prefixed UUID4 hex
(`p_`, `pv_`, `run_`, `sch_`) generated by the API. Timestamps are UTC `DateTime(timezone=True)`.

| Table | Columns | Notes |
|-------|---------|-------|
| `problems` | `id` PK, `name` str, `domain` str, `template_id` str null, `version` int (starts 1), `document` JSON (Problem), `created_at`, `updated_at` | Editable document. `version` increments on every successful PUT/replan-changes. |
| `problem_versions` | `id` PK, `problem_id` FK cascade, `base_version` int, `kind` str (`snapshot`\|`replan`), `content_hash` str(64) sha256 of canonical JSON (`json.dumps(doc, sort_keys=True, separators=(",",":"))`), `document` JSON, `created_at` | Immutable. A `snapshot` row is reused only if `(problem_id, kind="snapshot", content_hash, base_version)` all match; `replan` rows are never reused. Index `(problem_id, content_hash)`. |
| `solver_runs` | `id` PK, `problem_id` FK cascade, `problem_version_id` FK, `status` str (`queued`\|`running`\|`completed`\|`failed`\|`cancelled`), `request` JSON (effective `SolverRunRequest`), `seed` int, `engine_version` str, `selection` JSON null, `phases` JSON null, `feasibility` str null, `termination_reason` str null, `optimality_proven` bool null, `objectives` JSON null, `metrics` JSON null, `diagnostics` JSON (list), `error` str null, `cancel_requested` bool default false, `source_schedule_id` str null (replan), `created_at`, `started_at` null, `finished_at` null | Index `(problem_id, created_at)`, `(status)`. |
| `solver_run_events` | `id` int autoincrement PK, `run_id` FK cascade, `seq` int, `type` str, `payload` JSON, `created_at` | Unique `(run_id, seq)`. `seq` is the SSE id. |
| `schedules` | `id` PK, `problem_id` FK cascade, `problem_version_id` FK, `solver_run_id` FK null, `source_schedule_id` str null, `status` str (`candidate`\|`approved`\|`superseded`), `rank` int (0 primary, 1.. alternatives), `label` str, `solver` str, `feasibility` str, `objectives` JSON, `metrics` JSON, `violations` JSON, `placements` JSON, `explanation` JSON, `created_at`, `approved_at` null, `superseded_at` null, `approved_problem_version` int null | Index `(problem_id, status)`. At most one `approved` per problem (enforced in a transaction; partial unique index on Postgres). |
| `audit_events` | `id` int PK, `entity_type` str, `entity_id` str, `action` str, `details` JSON, `created_at` | Actions: `problem.created/updated/deleted/imported`, `run.created/cancelled`, `schedule.approved/superseded`. |

Versioning rules:
1. Creating a solver run snapshots the current document into `problem_versions` **before**
   queuing. The worker reads only the snapshot; later edits cannot affect the run.
2. Optimistic concurrency on `problems`: `PUT` requires `If-Match: "<version>"`; mismatch -> 412.
3. Schedules are immutable except for `status`, `approved_at`, `superseded_at`,
   `approved_problem_version`.
4. Approving schedule X (single transaction): any currently approved schedule of the same problem
   becomes `superseded` (`superseded_at = now`); X becomes `approved`. Never silent: the
   response reports `superseded_schedule_id`, the UI asks for confirmation when one exists.
5. Placements are stored as JSON in `schedules` (relational `schedule_placements` deferred).
6. Deleting a problem with a `queued`/`running` run -> 409.
7. Concurrency: the MVP is a single process. Check-then-write sequences (one active run per
   problem, one approved schedule per problem, If-Match version check + update) run under one
   process-wide `threading.Lock` in the service layer **and** inside one DB transaction, so two
   simultaneous requests cannot both succeed (tested with two threads).
8. SQLite `PRAGMA foreign_keys=ON` and `journal_mode=WAL` are set in a `connect` event listener
   (per connection), otherwise cascades silently do nothing.
9. `solver_runs` has no `primary_schedule_id`/`schedule_ids` columns; the API derives them from
   `schedules` (`solver_run_id`, ordered by `rank`).

---

## 14. REST API (`backend/superplanner/api`, prefix `/api/v1`)

Conventions:
- JSON, UTF-8. Datetimes ISO-8601 with offset.
- Errors (all non-2xx except FastAPI's 405) use:
  `{"error": {"code": "STRING_CODE", "message": "Plain language", "details": {}}}`.
  `RequestValidationError` and Pydantic errors are mapped to 422 with
  `code = "VALIDATION_ERROR"`, `details = {"errors": [{"loc": [...], "msg": "...", "type": "..."}]}`.
- `404 NOT_FOUND`, `409 CONFLICT` (state), `412 VERSION_MISMATCH`, `428 PRECONDITION_REQUIRED`,
  `422` validation/business-rule failures.
- List endpoints return `{"items": [...]}` (no pagination in the MVP; max 500 items, newest first).
- CORS: allow origins `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:4173`,
  `http://127.0.0.1:4173` (env `CORS_ORIGINS`, comma-separated); expose header `ETag`. The UI
  normally goes through the Vite proxy (same origin), so CORS is a fallback.
- Fixed-path routes are registered before parameterized siblings: `POST /problems/import`
  before anything under `/problems/{id}`, `GET /schedules/compare` before `GET /schedules/{id}`.
- Every timestamp the API generates (`created_at`, ...) is UTC with a `Z` suffix; every
  plan-time value (`start_at`, `end_at`, problem datetimes) uses the plan's offset.
- App factory: `create_app(settings: Settings | None = None) -> FastAPI` in `api/main.py`
  (`Settings` from `api/config.py`: `database_url`, `cors_origins`, `run_workers`), plus
  module-level `app = create_app()`. Tests build isolated apps with a temp-file SQLite URL.

### 14.1 Health

`GET /api/v1/health` -> 200
```json
{"status": "ok", "version": "0.1.0", "ortools_version": "9.15.6755", "database": "ok"}
```
If the DB ping fails: 503 with `"status": "degraded", "database": "error"`.

### 14.2 Templates

`GET /api/v1/templates` -> 200
```json
{"items": [
  {"id": "manufacturing", "name": "Manufacturing", "domain": "manufacturing",
   "description": "Jobs with operations on machines, alternative machines, shifts and due dates.",
   "terminology": {"task": "Operation", "tasks": "Operations", "resource": "Machine", "resources": "Machines",
                   "group": "Job", "milestone": "Milestone", "schedule": "Production schedule", "deadline": "Due date"},
   "parameters": [
     {"name": "jobs", "label": "Number of jobs", "type": "int", "default": 5, "min": 1, "max": 20, "help": ""},
     {"name": "due_in_days", "label": "Latest due date (days)", "type": "int", "default": 5, "min": 2, "max": 30, "help": ""}
   ]}
]}
```

`POST /api/v1/templates/{template_id}/instantiate`
Request:
```json
{"name": "Workshop week 43", "start_date": "2026-10-19", "utc_offset": "+05:30", "parameters": {"jobs": 4}}
```
`name` optional (default template name), `start_date` optional (default today in `utc_offset`),
`utc_offset` optional (`"+00:00"`), regex `^[+-]\d{2}:\d{2}$`.
Responses: 201 `ProblemRecord` (14.3) with header `ETag: "1"` and `Location`; 404 unknown
template; 422 invalid parameters.

### 14.3 Problems

`ProblemRecord`:
```json
{"id": "p_7f3a", "version": 3, "template_id": "manufacturing",
 "created_at": "2026-10-15T09:00:00Z", "updated_at": "2026-10-15T09:12:00Z",
 "problem": { "...": "full Problem document (3.11), problem.id == id" }}
```

`ProblemSummary`:
```json
{"id": "p_7f3a", "name": "Workshop week 43", "domain": "manufacturing", "version": 3,
 "task_count": 12, "resource_count": 5, "updated_at": "2026-10-15T09:12:00Z",
 "approved_schedule_id": "sch_91c2", "latest_run": {"id": "run_4d1e", "status": "completed"}}
```
(`approved_schedule_id` and `latest_run` nullable.)

| Method | Path | Request | Success | Errors |
|--------|------|---------|---------|--------|
| GET | `/problems` | - | 200 `{"items": [ProblemSummary]}` ordered by `updated_at` desc | |
| POST | `/problems` | `Problem` (any `id` is replaced) | 201 `ProblemRecord`, `ETag: "1"` | 422 |
| GET | `/problems/{id}` | - | 200 `ProblemRecord`, `ETag: "<version>"` | 404 |
| PUT | `/problems/{id}` | `Problem` (full replacement), header `If-Match: "3"` | 200 `ProblemRecord` with version 4, new `ETag` | 404, 412 `{"error":{"code":"VERSION_MISMATCH","details":{"current_version":5}}}`, 428 missing If-Match, 422 |
| DELETE | `/problems/{id}` | - | 204 | 404, 409 run active |
| GET | `/problems/{id}/export` | - | 200 `ExportFile`, `Content-Disposition: attachment; filename="<slug>.superplanner.json"` | 404 |
| POST | `/problems/import` | `ExportFile` | 201 `ProblemRecord` (new id; task/resource ids kept) | 422 (bad format or version) |

`If-Match` accepts `"3"`, `3` or `W/"3"`. PUT only checks Pydantic structure (section 3.0);
referential problems are allowed in drafts and reported by `/validate`. On POST, PUT, import and
instantiate the server sets `problem.id` to the record id regardless of the body. `ProblemSummary.name`
and `problems.name`/`domain` columns are copied from the document on every write.

`ExportFile`:
```json
{"format": "superplanner.problem", "format_version": 1, "exported_at": "2026-10-15T09:30:00Z",
 "problem": { "...": "Problem" }}
```

### 14.4 Validate

`POST /api/v1/problems/{id}/validate` (no body; validates the stored current document) -> 200
```json
{"problem_version": 3, "ok": false,
 "issues": [
   {"code": "DEPENDENCY_CYCLE", "severity": "error",
    "message": "Operations \"J1 Cutting\" -> \"J1 Milling\" -> \"J1 Cutting\" form a loop; remove at least one of these dependencies.",
    "task_ids": ["J1-1", "J1-2"], "resource_ids": [], "field": "dependencies"},
   {"code": "UNUSED_RESOURCE", "severity": "warning",
    "message": "Machine \"Mill 2\" is not used by any operation.", "task_ids": [], "resource_ids": ["MILL2"], "field": null}
 ],
 "cpm": null}
```
When structural checks pass, `cpm` is a `CpmResult`:
```json
{"lower_bound_makespan_minutes": 570,
 "tasks": {"J1-1": {"es": 0, "ef": 90, "ls": 0, "lf": 90, "slack": 0, "critical": true}},
 "critical_path": ["J1-1", "J1-2"]}
```
Errors: 404.

### 14.5 Solver runs

`SolverRunRequest` (all optional):
```json
{"strategy": "auto", "time_limit_seconds": 10, "seed": 0,
 "objectives": {"preset": "meet_deadlines", "weights": {"makespan": 1.0, "tardiness": 1.0, "cost": 0.2}},
 "max_alternatives": 2,
 "ga": {"population_size": null, "max_generations": 300, "stagnation_generations": 40,
        "crossover_rate": 0.9, "mutation_rate": 0.1, "mutation_sigma": 0.1, "swap_rate": 0.2,
        "elite_count": 2, "tournament_size": 3, "archive_size": 10},
 "cpsat": {"num_workers": 8, "relative_gap": 0.0}}
```
`objectives` null = use the problem's. The server stores the fully defaulted request in
`solver_runs.request` (reproducibility).

`POST /api/v1/problems/{id}/solver-runs` -> 202
```json
{"run_id": "run_4d1e", "status": "queued", "problem_version_id": "pv_88aa",
 "status_url": "/api/v1/solver-runs/run_4d1e", "events_url": "/api/v1/solver-runs/run_4d1e/events"}
```
Errors: 404; 422 `{"error": {"code": "PREFLIGHT_FAILED", "message": "Fix 2 problems before optimizing.", "details": {"issues": [Issue]}}}`;
422 `VALIDATION_ERROR` for bad params; 409 `RUN_ALREADY_ACTIVE` if this problem already has a
queued/running run (one active run per problem keeps the MVP simple).

`GET /api/v1/problems/{id}/solver-runs` -> 200 `{"items": [SolverRun]}` (without events).

`GET /api/v1/solver-runs/{run_id}` -> 200 `SolverRun`:
```json
{"id": "run_4d1e", "problem_id": "p_7f3a", "problem_version_id": "pv_88aa", "status": "completed",
 "request": {"strategy": "auto", "time_limit_seconds": 10, "seed": 0, "...": "..."},
 "engine_version": "0.1.0",
 "selection": {"requested": "auto", "used": ["heuristic", "cpsat"],
               "reasons": ["Small/medium problem (12 tasks, 16 options): exact constraint solver seeded with the best heuristic."]},
 "phases": [
   {"solver": "heuristic", "status": "completed", "feasibility": "feasible", "termination_reason": "completed",
    "objectives": {"makespan_minutes": 2280, "weighted_tardiness": 0, "cost": 21450.0, "score": 1.2},
    "elapsed_seconds": 0.04},
   {"solver": "cpsat", "status": "completed", "feasibility": "feasible", "termination_reason": "optimal",
    "objectives": {"makespan_minutes": 1980, "weighted_tardiness": 0, "cost": 20100.0, "score": 1.06},
    "elapsed_seconds": 1.9}],
 "feasibility": "feasible", "termination_reason": "optimal", "optimality_proven": true,
 "objectives": {"makespan_minutes": 1980, "weighted_tardiness": 0, "cost": 20100.0, "score": 1.06},
 "metrics": {"makespan_minutes": 1980, "total_tardiness_minutes": 0, "weighted_tardiness": 0, "late_tasks": 0,
             "hard_deadline_misses": 0, "cost": 20100.0, "scheduled_tasks": 12, "total_tasks": 12,
             "utilization": {"CUT1": 0.31, "MILL1": 0.42, "MILL2": 0.12, "ASM1": 0.38, "OPS": 0.19}},
 "diagnostics": [],
 "error": null,
 "primary_schedule_id": "sch_91c2", "schedule_ids": ["sch_91c2", "sch_91c3"],
 "source_schedule_id": null,
 "created_at": "2026-10-15T09:20:00Z", "started_at": "2026-10-15T09:20:00Z", "finished_at": "2026-10-15T09:20:02Z",
 "elapsed_seconds": 2.0}
```
Fields from `selection` to `objectives`/`metrics` are null while queued/running.
Errors: 404.

`POST /api/v1/solver-runs/{run_id}/cancel` -> 202 `{"run_id": "run_4d1e", "status": "cancelled"|"running", "cancel_requested": true}`.
Queued runs become `cancelled` immediately (with a `run_cancelled` event; the worker checks the
status when it starts and exits without running the engine); running runs stop at the next check
and keep their best-so-far schedule as a candidate (run status `cancelled`). Terminal runs -> 409
`RUN_NOT_ACTIVE`. 404.

`GET /api/v1/solver-runs/{run_id}/events` -> SSE stream (section 15). With `?stream=false` ->
200 `{"items": [RunEvent]}` (all persisted events). Supports `Last-Event-ID` header or
`?after=<seq>` (header wins). `RunEvent` = the JSON `data` object of section 15.

### 14.6 Schedules

`ScheduleSummary`:
```json
{"id": "sch_91c2", "problem_id": "p_7f3a", "problem_version_id": "pv_88aa", "solver_run_id": "run_4d1e",
 "source_schedule_id": null, "status": "candidate", "rank": 0, "label": "Recommended", "solver": "cpsat",
 "feasibility": "feasible",
 "objectives": {"makespan_minutes": 1980, "weighted_tardiness": 0, "cost": 20100.0, "score": 1.06},
 "metrics": {"...": "Metrics"}, "hard_violation_count": 0, "soft_violation_count": 0,
 "base_problem_version": 3, "approved_problem_version": null,
 "created_at": "2026-10-15T09:20:02Z", "approved_at": null, "superseded_at": null}
```
`base_problem_version` = `problem_versions.base_version` of the schedule's snapshot; the UI
compares it with `ProblemRecord.version` to warn "This schedule was made for version 3; the plan
is now version 5" before approval. `objectives` and `metrics` are `null` only when the schedule
has no placements (not stored in that case, see 16).

`Schedule` = `ScheduleSummary` + :
```json
{"horizon_start": "2026-10-19T00:00:00+05:30",
 "placements": [
   {"task_id": "J1-1", "start": 360, "end": 450, "resource_ids": ["CUT1"],
    "start_at": "2026-10-19T06:00:00+05:30", "end_at": "2026-10-19T07:30:00+05:30"}],
 "violations": [Violation],
 "explanation": {
   "tasks": {"J1-1": {"task_id": "J1-1",
                      "reasons": [{"code": "CALENDAR", "message": "Waits for Saw 1 to open at Mon 19 Oct 06:00.",
                                   "related_task_ids": [], "resource_ids": ["CUT1"]}],
                      "on_critical_chain": true, "cpm_critical": true, "cpm_slack_minutes": 0,
                      "lateness_minutes": 0, "deadline_status": "none"}},
   "critical_chain": ["J1-1", "J1-2"], "cpm_critical_path": ["J1-1", "J1-2"],
   "summary": ["All 12 Operations finish on time.", "Completion is driven by the chain J1 Cutting -> J1 Milling."]}}
```
`label` values: `"Recommended"` (rank 0), alternative labels from 8.6, `"Replan"` for rank 0 of a
replan run. `horizon_start` is the snapshot's (not the current document's) and is the base of
every minute value in this schedule. Placements are the API model `PlacementOut` =
engine `Placement` + `start_at`/`end_at` (ISO, plan offset), computed from the snapshot.

| Method | Path | Request | Success | Errors |
|--------|------|---------|---------|--------|
| GET | `/problems/{id}/schedules` | `?status=candidate\|approved\|superseded` optional | 200 `{"items": [ScheduleSummary]}` newest first | 404 |
| GET | `/schedules/{id}` | - | 200 `Schedule` | 404 |
| POST | `/schedules/{id}/approve` | `{}` or `{"note": "string"}` | 200 `{"schedule": ScheduleSummary, "superseded_schedule_id": "sch_..."\|null}` | 404; 422 `NOT_FEASIBLE`; 409 `STALE_SCHEDULE` with `details.violations` (see below); idempotent 200 if already approved; 409 `SUPERSEDED` if superseded |
| GET | `/schedules/compare?a={id}&b={id}` | - | 200 `Comparison` | 404; 422 `DIFFERENT_PROBLEMS` |
| GET | `/schedules/{id}/export.csv` | - | 200 `text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="<problem-slug>-<schedule id>.csv"` | 404 |
| POST | `/schedules/{id}/replan` | `ReplanRequest` | 202 same shape as run creation + `"source_schedule_id"` | 404; 422 `PREFLIGHT_FAILED`/`VALIDATION_ERROR`; 409 `RUN_ALREADY_ACTIVE`; 412 if `expected_problem_version` given and stale |

Approval staleness: if `problems.version` differs from the schedule's snapshot `base_version`,
the server re-validates the schedule's placements against the **current** document. Hard
violations -> 409 `STALE_SCHEDULE` ("The plan changed since this schedule was created: ...")
with `details = {"violations": [Violation], "issues": []}`. If the current document has preflight
errors (`CompileError`), also 409 `STALE_SCHEDULE` with `details = {"violations": [], "issues":
[Issue]}`. Otherwise approve and set `approved_problem_version = current version`. The optional
`note` is stored in the `schedule.approved` audit event `details`. Check order: 404, then 409
`SUPERSEDED`, then idempotent 200 (already approved), then 422 `NOT_FEASIBLE`
(`feasibility != "feasible"`), then staleness.

`Comparison`:
```json
{"a": ScheduleSummary, "b": ScheduleSummary,
 "metric_deltas": {"makespan_minutes": -300, "total_tardiness_minutes": 0, "weighted_tardiness": 0,
                   "late_tasks": 0, "cost": -1350.0},
 "task_deltas": [
   {"task_id": "J1-2", "name": "J1 Milling", "in_a": true, "in_b": true,
    "start_a": 450, "start_b": 450, "end_a": 570, "end_b": 570, "start_delta_minutes": 0,
    "end_delta_minutes": 0, "resources_a": ["MILL1"], "resources_b": ["MILL2"], "resource_changed": true}],
 "changed_task_count": 5}
```
Deltas are `b - a`. `task_deltas` covers the union of task ids, sorted by `abs(end_delta)` desc
then id; utilization deltas omitted. All minute values in a comparison (`start_a`, `start_b`,
`end_a`, `end_b`) are relative to **schedule a's** `horizon_start` (b's are converted via absolute
time), so schedules made from snapshots with different horizons compare correctly. For a task
missing on one side, its `*_a`/`*_b` fields and the deltas are `null`, `resources_x` is `[]`, and
`resource_changed` is `false`. `name` comes from b's snapshot if present, else a's.
`changed_task_count` = tasks whose start, end or resources differ, or that exist on one side only.

CSV columns (header row, RFC 4180, ISO times in plan offset):
`task_id,task_name,group,type,start,end,duration_minutes,resource_ids,resource_names,deadline,deadline_hard,lateness_minutes,on_critical_chain`
(multi-values joined with `;`).

`ReplanRequest`:
```json
{"cutoff": "2026-10-20T12:00:00+05:30",
 "changes": {
   "task_updates": [{"id": "J2-2", "duration_minutes": 180}],
   "add_tasks": [],
   "remove_task_ids": [],
   "resource_unavailable": [{"resource_id": "MILL1", "start": "2026-10-20T12:00:00+05:30",
                             "end": "2026-10-21T06:00:00+05:30", "reason": "Breakdown"}]},
 "run": {"strategy": "auto", "time_limit_seconds": 10},
 "expected_problem_version": 3}
```
`task_updates[*]`: `id` (required, existing task) plus any subset of `name, duration_minutes,
priority, earliest_start, deadline, deadline_hard, requirements` (partial update; `locked` is not
accepted). `add_tasks`: full `Task` objects with new ids. `remove_task_ids`: also removes their
dependencies. `resource_unavailable`: appended to the resource's `calendar.blocked` (a `null`
calendar becomes `{"weekly": null, "blocked": [...]}`). All four lists default to `[]`.
Semantics (replan service, single transaction; any 4xx rolls back everything, including step 1):
0. Checks in order: 404 schedule; 412 `VERSION_MISMATCH` if `expected_problem_version` is given
   and differs from `problems.version`; 409 `RUN_ALREADY_ACTIVE`; 422 if `cutoff` is not inside
   `[horizon_start, horizon_end)` of the current document. Any schedule status may be the source.
1. If `changes` is non-empty, apply it to the current problem document (validated as a whole),
   increment `problems.version`, audit `problem.updated` (these are real-world facts).
2. Build a **derived** document (not written back to `problems`): for each placement of the
   source schedule with `start_at < cutoff` whose task still exists, set
   `task.locked = {start: start_at, resource_ids: placement.resource_ids}` (tasks started before
   the cutoff are frozen, including ones in progress). Source placements are converted to
   absolute times with the **source schedule's** `horizon_start`. For every other task set
   `earliest_start = max(earliest_start or horizon_start, cutoff)`. If a frozen task's
   `requirements` changed so the old `resource_ids` no longer align, lock only the start
   (`resource_ids = None`).
3. Snapshot the derived doc as `problem_versions.kind = "replan"`, run preflight (422 on error),
   create the run with `source_schedule_id` and `initial_solution` = source placements of
   unlocked tasks (CP-SAT hint / GA seed, which keeps the plan close to the approved one).
4. Resulting schedules are candidates with `source_schedule_id`; approving one follows normal rules.
5. `run` is a `SolverRunRequest` (all optional). The replan `initial_solution` is not part of
   the stored `request`; it is reproducible from `source_schedule_id` + the snapshot.
6. Response 202: `{"run_id", "status", "problem_version_id", "status_url", "events_url",
   "source_schedule_id", "problem_version": <int, after step 1>}`.

---

## 15. SSE events

`GET /api/v1/solver-runs/{run_id}/events`, `Content-Type: text/event-stream`,
`Cache-Control: no-cache`, `X-Accel-Buffering: no`. The handler first replays persisted events
with `seq > Last-Event-ID` (or `after`), then polls the DB every 0.5 s for new rows; sends a
comment line `: keepalive` every 15 s; closes after sending a terminal event. A client reconnecting
with `Last-Event-ID` never misses events. Frame format:

```
id: 7
event: progress
data: {"run_id":"run_4d1e","seq":7,"type":"progress","ts":"2026-10-15T09:20:01.200Z","elapsed_seconds":1.2,
       "solver":"cpsat","iteration":4,"best_score":1.08,
       "best_objectives":{"makespan_minutes":2010,"weighted_tardiness":0,"cost":20100.0,"score":1.08},
       "feasible_found":true,"extra":{"best_bound":0.97}}

```
(`data` is a single line in practice.) Common fields on every event: `run_id`, `seq`, `type`,
`ts` (UTC), `elapsed_seconds` (since run start; 0 for `run_queued`). `seq` starts at 1 (the
`run_queued` event) and increases by 1 per run.

Client/server rules that keep the UI and API compatible:
- Every frame has `event: <type>`, so browser clients **must** use
  `es.addEventListener(type, ...)` for each type in the table; `onmessage` receives nothing.
- After a terminal event the server closes the stream. If a request arrives for a terminal run
  and no persisted event has `seq > cursor`, the server answers `204 No Content` (which stops
  `EventSource` auto-reconnect). The client also calls `close()` itself on a terminal event.
- Unknown `run_id` -> 404 JSON error (not a stream).
- Implementation: an async generator polling the DB via `run_in_threadpool`; no extra SSE library
  (only what `requirements.txt` lists).

| type | extra fields | when |
|------|--------------|------|
| `run_queued` | `problem_version_id` | run created |
| `run_started` | `strategy_requested` | worker begins |
| `phase_started` | `solver`, `reason` (selector sentence) | each phase |
| `progress` | `solver`, `iteration`, `best_score`, `best_objectives`, `feasible_found`, `extra` | throttled to max 2/s per run; the latest is always flushed before `phase_completed` |
| `phase_completed` | `solver`, `status`, `feasibility`, `termination_reason`, `objectives` | each phase |
| `run_completed` | `feasibility`, `termination_reason`, `optimality_proven`, `objectives`, `primary_schedule_id`, `schedule_ids` | terminal |
| `run_cancelled` | `primary_schedule_id` (nullable), `schedule_ids` | terminal |
| `run_failed` | `error` (message, no stack trace) | terminal |

---

## 16. Background run orchestration (`api/services/run_service.py`, `api/executor.py`)

- `RunExecutor`: process-wide `ThreadPoolExecutor(max_workers=int(env RUN_WORKERS or 2))`,
  created on app startup (lifespan), shut down on exit (`cancel_futures=True`, set all cancel
  events). Holds `dict[run_id, threading.Event]` for cancellation.
- Creation (request thread): preflight current doc (422 on errors) -> snapshot -> insert run
  (`queued`) + `run_queued` event -> commit -> submit job. Commit happens before submit so the
  worker always finds the row.
- Worker: own DB session; mark `running` + `run_started`; load the snapshot; call
  `engine.optimize(problem, request, progress_cb, cancel_event)`. `progress_cb` maps
  `ProgressEvent` -> DB event rows (throttle `progress` to 2/s; phase events always) using a
  short-lived session per write; `seq` is allocated by the worker (one writer per run).
  If the run is already `cancelled` when the worker starts, it returns immediately.
  The engine `OptimizeRequest` is built from the stored `SolverRunRequest` (same field names)
  plus `initial_solution` for replans.
  On return: for each `Alternative` call `engine.validate_schedule` and
  `engine.explain_schedule` on the snapshot to obtain its violations, metrics and explanation
  (alternatives that are not `feasible` are dropped). Create schedules (rank 0 primary + alternatives; a
  primary is stored even when `unknown`/`infeasible` if placements exist, so users can inspect
  violations), update run summary, emit terminal event; status `cancelled` if the cancel event
  was set, else `completed`. Any exception -> `failed`, `error = str(exc)`, `run_failed`, traceback
  to the log only. Schedule writes + run update happen in one transaction so a crash cannot
  leave a half-written result; the approved schedule is never touched by workers.
- Startup recovery: runs left `queued`/`running` from a previous process become `failed` with
  `error = "Server restarted before the run finished."`.
- The GA holds the GIL; with 2 workers API latency stays acceptable for the MVP. Process pool is
  deferred.

---

## 17. Frontend (`frontend/`, React 18 + TypeScript + Vite)

Dependencies: `react@18`, `react-dom@18`, `react-router-dom@6`. Dev: `vite`, `@vitejs/plugin-react`,
`typescript`, `@types/react`, `@types/react-dom`, and `@playwright/test` pinned to **exactly
`1.56.1`** (the preinstalled Chromium in `/opt/pw-browsers` is build 1194, which matches 1.56.x;
a newer version would try to download browsers). No UI kit, no state library, no chart/Gantt
library: Gantt and dependency graph are custom SVG.

Vite: dev server port 5173, preview port 4173; both `server.proxy` and `preview.proxy` =
`{"/api": "http://127.0.0.1:8000"}` (SSE passes through the proxy). API base is the relative
`/api/v1` (env `VITE_API_BASE` optional). `tsconfig.json` `include` is `["src"]` only, so
`frontend/e2e/**` (QA) never breaks the UI type check.

Package scripts (UI owns `package.json`): `dev`, `build` (`tsc --noEmit && vite build`),
`preview`, `typecheck` (`tsc --noEmit`), `e2e` (`playwright test -c e2e/playwright.config.ts`).

### 17.1 Routes

| Path | Screen |
|------|--------|
| `/` | Home: plans list + "Create from template" cards + import JSON |
| `/plans/:planId` | redirect to `/plans/:planId/tasks` |
| `/plans/:planId/tasks` | Tasks tab |
| `/plans/:planId/resources` | Resources tab |
| `/plans/:planId/dependencies` | Dependencies tab |
| `/plans/:planId/validate` | Validate tab |
| `/plans/:planId/optimize` | Optimize tab (`?run=<runId>` shows a run's live progress) |
| `/plans/:planId/schedule` | Schedule tab (`?id=<scheduleId>`; default = approved, else newest primary candidate) |
| `/plans/:planId/compare` | Compare tab (`?a=<id>&b=<id>`) |
| `*` | Not found |

### 17.2 Files and components

```
frontend/
  index.html  package.json  tsconfig.json  vite.config.ts
  e2e/playwright.config.ts               # QA (moved from frontend root so frontend/e2e/** is QA-only)
  src/
    main.tsx                     # router setup
    App.tsx                      # layout shell, theme toggle
    styles/theme.css             # CSS variables (light/dark), one accent color
    api/types.ts                 # TS mirrors of every contract in sections 3, 7, 9, 11, 14, 15
    api/client.ts                # typed fetch wrappers; ApiError {status, code, message, details}
    api/sse.ts                   # subscribeRunEvents(runId, onEvent, onEnd): EventSource wrapper
    lib/time.ts                  # minute<->Date, format in plan offset, duration "2h 15m"
    lib/terms.ts                 # useTerms(): terminology helpers (plural, capitalized)
    lib/graphLayout.ts           # longest-path layering + barycenter ordering
    state/PlanContext.tsx        # see 17.3
    pages/HomePage.tsx
    pages/PlanWorkspace.tsx      # header (name, version, save state), tab nav, <Outlet/>
    pages/tabs/TasksTab.tsx
    pages/tabs/ResourcesTab.tsx
    pages/tabs/DependenciesTab.tsx
    pages/tabs/ValidateTab.tsx
    pages/tabs/OptimizeTab.tsx
    pages/tabs/ScheduleTab.tsx
    pages/tabs/CompareTab.tsx
    components/TemplateCard.tsx          # params form + create
    components/PlanList.tsx
    components/TaskTable.tsx             # inline-editable rows: name, group, type, duration, priority,
                                         # earliest start, deadline (+hard toggle), predecessors (multi-select
                                         # with type/lag), requirements editor, lock toggle
    components/RequirementEditor.tsx     # alternatives multi-select + units, per requirement
    components/ResourceTable.tsx         # name, kind, capacity, cost/h
    components/CalendarEditor.tsx        # weekly grid of windows per weekday + blocked intervals list; "always available" toggle
    components/DependencyGraph.tsx       # layered SVG; critical path highlighted; cycle edges red + label
    components/IssueList.tsx             # preflight issues grouped by severity, link to offending row
    components/GoalPresetPicker.tsx      # Balanced / Finish ASAP / Meet deadlines / Lowest cost (+custom weights in expert)
    components/ExpertSettings.tsx        # strategy, GA params, seed, CP-SAT workers
    components/RunProgress.tsx           # phase list, live best objectives, elapsed, cancel button
    components/KpiCards.tsx              # completion date, makespan, late tasks, cost, utilization avg
    components/Gantt.tsx                 # SVG timeline; mode "tasks" | "resources"; zoom; arrows; deadlines
    components/TaskDrawer.tsx            # placement details + explanation reasons + deadline status
    components/ViolationsPanel.tsx
    components/StatusBadge.tsx           # icon + text: Feasible / Not feasible / Unknown / Running / Cancelled / Failed;
                                         # Candidate / Approved / Superseded
    components/ScheduleComparison.tsx    # side-by-side KPIs + task delta table + two stacked mini-Gantts
    components/ConfirmDialog.tsx
    components/ReplanDialog.tsx          # Schedule tab: cutoff, duration updates, resource unavailable -> POST replan
    components/RunHistory.tsx            # Optimize tab: GET /problems/{id}/solver-runs list with status badges
    api/contractExamples.ts              # the JSON examples of sections 3.11, 14 and 15 typed against types.ts
  e2e/                                   # Playwright tests (tester)
```

Stable test hooks (UI must provide, QA relies on them; any change needs both owners):
`data-testid` on `plan-list`, `template-card-<id>`, `task-row-<taskId>`, `issue-list`,
`issue-<code>`, `run-progress`, `run-status`, `gantt`, `gantt-bar-<taskId>`, `task-drawer`,
`approve-button`, `schedule-status`, `compare-table`, `export-csv`, `save-state`. Primary buttons
also have accessible names (`getByRole("button", {name: ...})`) matching their visible text.

Additional UI behaviour required by the contract:
- New task/resource rows get generated ids (`T1`, `T2`, ... / `R1`, ...; first unused) and a
  default name ("New Operation" via terminology) so autosave never sends an invalid document;
  ids are shown but not editable.
- Template instantiation sends the browser's current UTC offset as `utc_offset`.
- `TaskDrawer` offers "Lock at this time": sets `locked = {start: start_at, resource_ids}` on
  the draft and saves (Schedule tab must therefore load `PlanContext`).
- `ReplanDialog` is available for any feasible schedule; on 202 it navigates to
  `optimize?run=<run_id>`.

### 17.3 State handling

- **Server state** via small hooks in `api/client.ts` consumers (`useProblem`, `useSchedules`,
  `useRun`): `fetch` + `useEffect` + `AbortController`; no global cache.
- **PlanContext** holds `record: ProblemRecord`, `draft: Problem`, `dirty: boolean`,
  `saveState: "saved"|"saving"|"error"|"conflict"`, `update(fn: (p: Problem) => Problem)`,
  `save()`, `reload()`. Edits mutate only `draft` (immutable updates). Save = `PUT` with
  `If-Match: "<record.version>"`; on 412 set `conflict` and show a banner "This plan was changed
  elsewhere. Reload (discard your edits) / Keep editing". Autosave: debounce 1.5 s after the
  last edit; explicit "Save" button too; `beforeunload` warning while dirty.
- Validate/Optimize tabs save the draft first if dirty, then call the endpoint.
- **Run progress:** `OptimizeTab` POSTs the run, navigates to `?run=<id>`, subscribes with
  `EventSource` (one `addEventListener` per event type, section 15); on terminal event it closes
  and links to the schedule. On reload it fetches `GET /solver-runs/{id}` and resubscribes (the
  server replays). Polling fallback (`GET /solver-runs/{id}` every 2 s) if `EventSource` errors
  3 times. A 409 `RUN_ALREADY_ACTIVE` on POST navigates to the active run (latest_run).
- **UI preferences** (Gantt mode/zoom, expert toggle, theme) in `localStorage` with try/catch.
- Times: placements carry minute offsets plus `start_at`; the UI renders in the plan's offset
  (from the **schedule's** `horizon_start`), not the browser's zone, and labels it ("Times shown
  in UTC+05:30"). Datetime inputs in editors are entered in the plan offset and serialized with it.
- Terminology: every label for tasks/resources/groups/schedule comes from `useTerms()`.
- Candidate vs approved: a persistent banner on the Schedule tab ("Candidate - not yet approved"
  vs "Approved on ..."), plus `StatusBadge`; Approve asks for confirmation naming the schedule
  it will supersede.
- Non-feasible schedules: Approve disabled with the reason; violations panel opened.
- Accessibility: all controls labelled, keyboard focus visible, Gantt bars focusable
  (`tabindex=0`, Enter opens drawer), status never by color alone; late tasks get a hatched
  pattern and "Late" text.

### 17.4 Gantt specifics

Time scale `pxPerHour` (zoom levels 4, 8, 16, 32, 64), x = `(minute / 60) * pxPerHour`. Day grid
and labels in the plan offset. Mode "tasks": one row per task grouped by `group` (collapsible);
mode "resources": one lane per resource, tasks drawn in each assigned resource's lane; capacity >
1 lanes stack overlapping bars in sub-rows; non-working time (outside windows) shaded. Dependency
arrows from the predecessor's end (FS/FF) or start (SS/SF) to the successor's start (FS/SS) or
end (FF/SF). Deadline markers: a vertical tick + diamond at the deadline on the task's row (red
dashed for hard). Milestones as diamonds. Critical chain bars outlined. Virtualize rows when >
300 (render only visible rows).

---

## 18. Repository layout and file ownership

Owners are the work packages of `docs/PLAN.md` (the authoritative split; this section was
aligned with it in the team-lead review): **WP1** (backend-developer: engine + templates),
**WP2** (backend-developer: API, DB, packaging), **WP3** (ui-developer: frontend), **WP4**
(tester: integration + e2e tests), **ARCH** (architect), **LEAD** (team-lead). One owner per
file; others request changes through the owner (or record an Implementation note).

```
superplanner/
  .gitignore                                   LEAD
  README.md                                    LEAD (how to run: backend, frontend, tests)
  docs/ARCHITECTURE.md                         ARCH (Implementation notes: any dev; Review notes: LEAD)
  docs/PLAN.md                                 LEAD
  docs/source/*                                read-only
  backend/
    .venv/                                     preinstalled; not committed
    pyproject.toml                             WP2 (package metadata; [tool.pytest.ini_options]:
                                                    pythonpath=["."], testpaths=["tests"],
                                                    addopts="--import-mode=importlib",
                                                    markers=["slow: long benchmarks"])
    requirements.txt                           WP2 (fastapi, uvicorn, pydantic, sqlalchemy, ortools, httpx, pytest;
                                                    pinned to the versions installed in .venv)
    run_api.sh                                 WP2 (starts uvicorn on :8000; honours DATABASE_URL, PORT)
    superplanner/__init__.py                   WP1 (__version__ = "0.1.0")
    superplanner/engine/__init__.py            WP1 (public API 7.6; re-exports __version__)
    superplanner/engine/model.py               WP1
    superplanner/engine/timeutil.py            WP1
    superplanner/engine/compiled.py            WP1
    superplanner/engine/objectives.py          WP1
    superplanner/engine/graph.py               WP1
    superplanner/engine/preflight.py           WP1
    superplanner/engine/validator.py           WP1
    superplanner/engine/explain.py             WP1
    superplanner/engine/decoder.py             WP1 (decode + left_shift)
    superplanner/engine/solvers/__init__.py    WP1 (registry: {"heuristic":..., "cpsat":..., "ga":...})
    superplanner/engine/solvers/base.py        WP1 (protocol, SolverConfig, SolveResult, ProgressEvent, params) - frozen early
    superplanner/engine/solvers/heuristic.py   WP1
    superplanner/engine/solvers/cpsat.py       WP1
    superplanner/engine/solvers/ga.py          WP1
    superplanner/engine/selector.py            WP1
    superplanner/engine/pipeline.py            WP1 (optimize())
    superplanner/templates/__init__.py         WP1 (registry)
    superplanner/templates/base.py             WP1
    superplanner/templates/manufacturing.py    WP1
    superplanner/templates/exam_prep.py        WP1
    superplanner/templates/project.py          WP1
    superplanner/templates/blank.py            WP1
    superplanner/api/__init__.py               WP2
    superplanner/api/main.py                   WP2 (create_app(), lifespan, CORS, error handlers, `app`)
    superplanner/api/config.py                 WP2 (Settings: DATABASE_URL, CORS_ORIGINS, RUN_WORKERS)
    superplanner/api/errors.py                 WP2
    superplanner/api/schemas.py                WP2 (API-only models: ProblemRecord, SolverRunRequest, PlacementOut, ...)
    superplanner/api/db/__init__.py            WP2
    superplanner/api/db/models.py              WP2
    superplanner/api/db/session.py             WP2
    superplanner/api/executor.py               WP2
    superplanner/api/services/*.py             WP2 (problem_service, run_service, schedule_service, replan_service)
    superplanner/api/routes/*.py               WP2 (health, templates, problems, solver_runs, schedules)
    tests/engine/**                            WP1 (unit tests incl. tests/engine/solvers/, tests/engine/templates/,
                                                    own conftest.py and tests/engine/fixtures/*.json)
    tests/api/**                               WP2 (own conftest.py with temp-DB app fixture)
    tests/integration/**                       WP4 (end-to-end API flows, property tests, benchmarks,
                                                    own conftest.py and tests/integration/fixtures/*.json)
    (no tests/conftest.py and no __init__.py under tests/: each area is self-contained;
     test file names are unique across areas, e.g. test_engine_*.py / test_api_*.py / test_int_*.py)
  frontend/**                                  WP3 (except frontend/e2e/**)
  frontend/e2e/**                              WP4 (incl. e2e/playwright.config.ts, e2e/tsconfig.json)
```

Rules that keep parallel packages from colliding:
- Before WP2 creates `pyproject.toml`, WP1 runs its tests with
  `cd backend && .venv/bin/python -m pytest --import-mode=importlib tests/engine`
  (`python -m` puts `backend/` on `sys.path`). The same command keeps working afterwards.
- All Python dependencies are already installed in `backend/.venv` (fastapi 0.143, pydantic 2.14,
  SQLAlchemy 2.1, ortools 9.15.6755, httpx, pytest 9). No package may need anything else; a new
  dependency requires a PLAN change and is added only by WP2 to `requirements.txt`.
- Fixtures are `ExportFile` JSON. WP4 may copy WP1 fixtures into its own folder; nobody edits
  another package's fixture files.
- `frontend/package.json` (WP3) must list `@playwright/test@1.56.1` as a devDependency and the
  `e2e` script; WP4 adds nothing outside `frontend/e2e/`.

Run commands:
- Backend: `cd backend && ./run_api.sh` (= `.venv/bin/uvicorn superplanner.api.main:app --port ${PORT:-8000}`)
- Tests: `cd backend && .venv/bin/pytest -q` (fast suite; `-m slow` for benchmarks)
- Frontend: `cd frontend && npm install && npm run dev`; checks `npm run typecheck && npm run build`
- E2E: `cd frontend && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test -c e2e/playwright.config.ts`
  (never `playwright install`)

Parallelization: WP1 lands `model.py`, `compiled.py`, `solvers/base.py` and the public API
signatures in `engine/__init__.py` first (stubs allowed); WP3 transcribes `frontend/src/api/types.ts`
from this document at the same time. WP2 starts once WP1 is complete; WP3 runs throughout against
the contract; WP4 writes tests against the contract from day one and runs them as WP1/WP2/WP3 land.

---

## 19. Testing strategy

Principle: the most dangerous failure is an invalid schedule shown as feasible, so **every
solver test asserts `validate(...)` independently**, and the validator itself is tested against
hand-built schedules first.

| Layer | Owner | What | Examples |
|-------|-------|------|----------|
| Model | WP1 | Pydantic rules | naive datetime rejected; milestone with duration 5 -> 422; custom weights all zero rejected |
| Time/calendar | WP1 | expansion and offsets | windows in `+05:30`; `22:00-24:00` + `00:00-06:00` merge; blocked subtraction; weekly None + blocked |
| Graph/CPM | WP1 | cycles, topo, all 4 dep types with positive/negative lag | ES/LS on textbook network; cycle reported in order |
| Preflight | WP1 | each code in 9.1 fires with the right severity and readable message | |
| Validator | WP1 | each violation code with minimal hand-made placements; sweep boundaries (touching intervals OK) | capacity 2 with three overlapping tasks -> exactly one `CAPACITY_EXCEEDED` with correct interval |
| Decoder | WP1 | earliest placement, calendars, multi-requirement, locks, alternatives, unschedulable cascade | |
| Left-shift | WP1 | never increases any end; never changes resources; output valid when input valid | property test |
| Heuristic/CP-SAT/GA | WP1 | valid results on fixtures; CP-SAT optimal on tiny instances equals brute force; GA deterministic with seed and generation stop; mutation never 0; cancel returns within 1 s | |
| Selector | WP1 | rule table 8.7 (each row), reasons text present, never worse than baseline | |
| Explain | WP1 | each reason code on a crafted schedule; critical chain | |
| Templates | WP1 | each template at defaults: preflight ok, optimize -> feasible | |
| API | WP2 | each endpoint status code in section 14; If-Match/412/428; approve supersedes; stale approval; cancel; SSE replay with Last-Event-ID | FastAPI `TestClient` with temp SQLite file |
| Integration | WP4 | template -> validate -> run -> SSE -> schedule -> approve -> replan -> compare -> CSV; property-based random small problems (stdlib `random`, 200 seeds): every strategy's result validated, CP-SAT score <= heuristic score | |
| Benchmarks | WP4 | `tests/integration/test_int_benchmarks.py` marked `slow`: precedence-only, RCPSP-like (30 tasks, 4 resources), flexible job shop (10x5 with alternatives), calendar-heavy study plan, infeasible and nearly infeasible; record feasibility rate, time to first feasible, objective vs CP-SAT | |
| UI contract | WP3 | `api/contractExamples.ts` type-checks the JSON examples of sections 3.11/14/15 against `types.ts` | `npm run typecheck` |
| E2E | WP4 | Playwright: create from template, edit a task, validate shows a cycle, optimize with live progress, Gantt renders, approve, compare two schedules, CSV download | |

Fixtures (`tests/engine/fixtures/`, `tests/integration/fixtures/`) are `ExportFile` JSON so the
same files work for engine and API tests and can be imported in the UI. Engine-level tests call
the engine directly; API and integration tests go through HTTP (`TestClient` or a live server).

---

## 20. Deferred items (documented, not built)

| Item | Why deferred / hook left in the MVP |
|------|-------------------------------------|
| Authentication, users, organizations, multi-tenancy, RBAC | Single-user local MVP. Every table can gain `workspace_id` later; services take a context object. |
| Celery/Redis/durable queue, separate worker processes, retries | Thread pool + persisted events + startup recovery are enough locally. `RunExecutor` is the seam. |
| Monte Carlo simulation, robust optimization, uncertain durations | Needs scenario model; blueprint section 14. |
| Scenarios/branches as first-class objects | Compare works on any two schedules of a plan. |
| Preemptive tasks, minimum chunk size, effort vs elapsed duration | Requires splitting variables; templates split long work instead. |
| Working-time lags, DST/IANA time zones, holidays calendar library | Fixed offset; holidays via blocked intervals. |
| Sequence-dependent setups, materials/inventory, budgets | Manufacturing adapter extensions. |
| Recurring and conditional tasks, summary tasks | Templates generate expanded tasks. |
| Constraint registry with pluggable constraints and per-solver compile/unsupported reporting | MVP has a fixed constraint set (H1-H10, S1) implemented in every solver. |
| MILP (HiGHS), local search/LNS, NSGA-II proper | GA keeps a Pareto archive instead. |
| Disruption-minimizing objective for replanning, freeze horizon policies, execution events | Replan locks started work and hints the source schedule. |
| Cross-plan resource reservations (shared machines across plans) | Single plan scope. |
| Relational `schedule_placements`, Alembic migrations, object storage for traces | JSON columns in MVP. |
| Financial planning module (allocation/portfolio problem class) | Later domain adapter needing a layered universal model and MILP/simulation compiler (followups doc sections 1-5). Must not be shoehorned into tasks. |
| LLM planning copilot (draft tasks from text, explain in chat) | Must sit on top of the engine and validator, never replace them. |
| Drag-to-reschedule with validation and repair, undo/redo of schedule edits | Needs incremental repair; users can lock + replan instead. |
| Six-step wizard | Template cards + tabs cover the flow; wizard can wrap the same components later. |
| Resource heatmap, Pareto frontier chart, audit history UI | Data already stored. |
| Machine-learned solver selection | Rule-based selector with explained reasons first. |

---

## 21. Deviations from the lead engineer's direction

| Direction | Change | Why |
|-----------|--------|-----|
| CP-SAT calendars as blocking intervals in `AddCumulative` | Per-alternative **start domains** (`AddLinearExpressionInDomain(...).OnlyEnforceIf(x)`) | Exact for non-preemptive "fits one window", far fewer intervals for long horizons, stronger propagation, and alternatives with no fitting window are fixed to 0 up front. Blocking intervals are also correct but heavier. |
| Explanation from decoder binding reasons | Added **left-shift compaction** applied to all solver output; explain recomputes reasons solver-agnostically | CP-SAT solutions are often not left-justified, which would make "why does it start here" unanswerable. Compaction never worsens any objective (all dependencies are successor lower bounds). |
| `feasibility: infeasible` for any non-feasible result | `infeasible` only when proven; otherwise `unknown`; best-effort schedules stored but not approvable | Blueprint 5.3 requires distinguishing proven infeasibility from timeouts. |
| Weighted objective `{makespan, tardiness, cost}` | Weights applied to values **normalized by per-run references** from the baseline; tardiness weighted by priority | Raw minutes and money cannot be added (blueprint 23.2, followups 5.2). Priority otherwise has no effect on optimizers. |
| `locked{start, resource_ids}` | `resource_ids` optional, and both lock and placement `resource_ids` are **aligned with requirements by index** | Unambiguous mapping when a task has several requirements; allows "fix the time, let the solver pick the machine". |
| Replan locks placements in the problem | Locks are applied to a **derived snapshot**, not written to the editable document; only `changes` are written | Avoids polluting the user's plan with replan artifacts; snapshot keeps the run reproducible. |
| Approve supersedes previous | Added stale-input check by **re-validating** against the current document | Blueprint 9.2: verify inputs are still compatible on approval. |
| Selector auto/hybrid | Added the resource-free CPM shortcut (proven optimal), the `<2 s` heuristic-only rule, CP-SAT->GA fallback, and an infeasibility probe | Avoids expensive pipelines for trivial problems (blueprint 7) and gives actionable infeasibility explanations (5.3). |
| Pareto archive from GA only | Alternatives drawn from all phases | CP-SAT-only runs can still offer "Cheapest" vs "Fastest" from heuristic rules. |
| One active run per problem | Added (409) | Keeps progress UI and approval semantics simple. |
| Blueprint 9.3 "store task dependencies relationally" | Whole `Problem` document (incl. dependencies) stored as JSON per problem/version (added by team-lead review) | The document is edited and snapshotted as a unit; relational tables add sync code with no MVP query that needs them. Revisit with Postgres and cross-plan queries. |

---

## 22. Glossary

- **Makespan**: minutes from horizon start to the end of the last task.
- **Tardiness**: minutes a task ends after its (soft) deadline.
- **Window**: a contiguous availability interval of a resource after calendar expansion.
- **Candidate / Approved / Superseded**: lifecycle of a schedule; only one approved per plan.
- **Baseline**: the best heuristic schedule of a run; source of `refs`, CP-SAT hint, GA seeds.
- **Critical chain**: the sequence of tasks and resource handoffs that determines completion in a
  given schedule; **CPM critical path** ignores resources.

## 23. Review notes (team lead)

Review of 2026-10-15 against `docs/source/blueprint.txt` and the work-package split in
`docs/PLAN.md`. All fixes below were applied in place in the sections named; this list is the
change log. Where an earlier draft and these fixes disagree, the fixed section text is binding.

Contradictions fixed:
1. **Model vs preflight layer** (new 3.0; 3.4, 3.6, 3.7, 3.9, 9.1). The draft made
   `successor != predecessor`, window ordering, `duration <= H`, `abs(lag) <= H` and lock alignment
   Pydantic (422) rules while 14.3 said drafts with referential problems must be saveable and 9.1
   listed `SELF_DEPENDENCY`/`INVALID_CALENDAR`/`LOCK_INVALID` as preflight codes that could then
   never fire. All relational/horizon checks are now preflight-only; new code `LAG_OUT_OF_RANGE`.
2. **`Problem.id` required vs "any id is replaced"** (3.2, 14.3). Now defaults to `"draft"`; the
   server always overwrites it.
3. **Reference values were circular** (8.0, 8.3, 7.3). `refs` came from the "best" baseline
   schedule, but "best" needs `refs` to rank. Now per-objective minimum over complete rule
   results via one shared `objectives.compute_refs`; `SolverConfig.refs` is optional for the
   baseline call only.
4. **Locked-task overloads ranked as feasible** (8.0, 8.1). The decoder reserves locked tasks
   even when they overload a resource, but `rank_key` did not count that. Added
   `DecodeResult.lock_conflicts` to `hard_violation_score`; final feasibility always from
   `validate()`.
5. **"Proven infeasible" preflight set was vague** (8.7 step 1). Now the explicit
   `PROVEN_INFEASIBLE_CODES`; malformed input yields `unknown`.
6. **Time budget** (8.7 step 4). "Not counted beyond 10%" was not implementable; replaced by a
   single deadline with remaining-budget hand-off and a testable bound
   (`time_limit_seconds + 3 s`).
7. **Phase/solver naming mismatch** (7.4, 7.7, 15). `SolveResult.solver` is `"heuristic:edf"`
   while SSE/phases use `"heuristic"`; the CPM shortcut had no selector row; SSE fields
   `reason`/`status` had no engine source. Defined phase vs detailed names, the `cpm` selection
   reason, and the exact `ProgressEvent -> SSE` mapping.
8. **File ownership did not match the delivery plan** (18, 19). Templates moved from API owner to
   WP1; `tests/solvers/` folded into `tests/engine/`; root `tests/conftest.py` and
   `tests/fixtures/` (QA) removed because WP1 tests run before WP4 exists; `playwright.config.ts`
   moved into `frontend/e2e/` so `frontend/**` (WP3) and `frontend/e2e/**` (WP4) do not overlap.

Gaps closed (would have made parallel engine/API/UI work incompatible):
9. SSE with named events: browser clients must use `addEventListener` per type (`onmessage`
   gets nothing); terminal runs answer `204` so `EventSource` does not reconnect forever; `seq`
   starts at 1 (15, 17.3).
10. Approval: check order defined; current document with preflight errors -> 409
    `STALE_SCHEDULE` with `issues` (engine `CompileError`); note stored in audit (14.6, 7.6).
11. `ScheduleSummary.base_problem_version`/`approved_problem_version` added so the UI can show
    staleness before approving (14.6).
12. Schedules carry their snapshot `horizon_start`; Compare normalizes minutes to schedule a's
    horizon and defines null handling for one-sided tasks (14.6).
13. Replan: check order, full rollback on 4xx, cutoff range, conversion via the source
    schedule's horizon, lock alignment when requirements changed, response shape (14.6).
14. Cancel of a queued run: event emitted and the worker skips the engine (14.5, 16).
15. Alternatives need violations/metrics/explanation for storage; the worker obtains them via
    the public `validate_schedule`/`explain_schedule` (16).
16. Concurrency: one process-wide lock + transaction around check-then-write (one active run,
    one approved schedule, If-Match); SQLite PRAGMAs per connection (13).
17. App factory `create_app(settings)` so API and integration tests use isolated temp DBs;
    route ordering for `/problems/import` and `/schedules/compare` (14).
18. Tooling facts verified in this environment: Python 3.13 venv already contains every backend
    dependency (no SSE library, so SSE is hand-rolled); Node 22; preinstalled Chromium build 1194
    => `@playwright/test` pinned to `1.56.1`; Vite `preview.proxy` added for e2e (17, 18).
19. UI gaps vs blueprint 11/13: replan dialog, run history, "Lock at this time" from the task
    drawer, generated ids/names for new rows (autosave never sends invalid documents), plan-offset
    datetime inputs, stable `data-testid` hooks for e2e (17.2, 17.3).
20. Accepted deviation recorded in 21: dependencies stored inside the JSON document rather than
    relationally (blueprint 9.3).

Not changed (reviewed and accepted): CP-SAT start-domain calendars, left-shift before
validation, normalized objective, derived replan snapshots, deferred list in section 20.

## 24. Open questions

1. Should approval of a schedule whose problem changed (but still validates) be allowed without
   user confirmation? Current answer: allowed, UI shows a notice "approved against version N".
2. Currency per resource? Current answer: single plan currency.

## 25. Implementation notes

_(developers: record interpretations of ambiguous contracts here, with date and owner)_

### 2026-10-15 - WP1 engine (backend-developer)

WP1 was delivered in one pass (contract stubs and implementation landed together), so there is no
separate stub-complete moment. Interpretations and small deviations:

1. **Model placement for validator independence.** `Placement` lives in `engine/model.py`,
   `ObjectiveValues`/`ObjectiveRefs` in `engine/objectives.py`, `Violation`/`Metrics`/
   `ValidationReport` in `engine/validator.py`. `solvers/base.py` and `superplanner.engine`
   re-export them, so import paths in 7.x still work. Reason: `validator.py` may import only
   `model`, `compiled`, `timeutil`, `objectives`.
2. **Extra module `engine/evaluate.py`** (not in 18): shared candidate ranking. A fast path
   (decoder output + `compute_metrics`) for heuristic/GA and an exact path (full `validate()`) for
   the final pick, both producing the 8.0 `rank_key`.
3. **`CompiledProblem` extras:** `terminology` (validator/explain messages) and `CTask.group`.
   `compile_problem(problem, objectives=None)` takes the optional `OptimizeRequest.objectives`
   override. `build_compiled()` is the internal builder without preflight (used by preflight's CPM,
   `analyze`, and tests).
4. **`compute_refs(rule_objectives, problem, cpm)`** accepts a `CpmResult` or the bare lower-bound
   int (duck-typed, so `objectives.py` does not import `graph`).
5. **`ValidateReport` and `analyze()`** live in `preflight.py`; `OptimizeRequest`, `PhaseSummary`,
   `OptimizeOutcome` in `pipeline.py`; `Selection` in `selector.py`.
6. **Preflight details.** Structural codes that suppress CPM checks: `TOO_LARGE`, `DUPLICATE_ID`,
   `UNKNOWN_TASK`, `SELF_DEPENDENCY`, `DUPLICATE_DEPENDENCY`, `DEPENDENCY_CYCLE`.
   `DEADLINE_BEFORE_HORIZON` replaces `DEADLINE_BEFORE_EARLIEST` for the same task; CPM deadline
   codes are not repeated for a task that already has `DEADLINE_BEFORE_EARLIEST`. `LOCK_INVALID`
   also covers a locked resource listed twice or without enough capacity. Issues are emitted in
   the 9.1 table order.
7. **Final pick (8.7 step 6).** Every phase result is left-shifted and fully validated before
   ranking (stronger than "rank, then left-shift the winner"). On equal `rank_key` a CP-SAT OPTIMAL
   result wins, so `optimality_proven` is not lost to an equally good heuristic schedule. Final
   `termination_reason`: `cancelled` > `proven_infeasible` > `optimal` > the last phase's reason
   if the baseline was kept, otherwise the reason of the phase that produced the pick.
   `PhaseSummary.objectives` are the phase's raw (pre-left-shift) values.
8. **Preflight-failed outcome:** `SolveResult.solver = "preflight"`, `Selection.used = []`,
   `phases = []`, `refs` all 1.0.
9. **Phase errors:** an exception in a cpsat/ga phase is caught, recorded as a phase with
   `status="failed"`, `termination_reason="error"` and a diagnostics line; the pipeline continues
   with the other phases. An exception in the baseline propagates (the API marks the run failed).
10. **CP-SAT tuning.** Makespan is `M >= E_t` for every task (no `AddMaxEquality`). Hints are
    completed with `M` and the tardiness variables. Presolve probing is limited to
    `min(1.0, 0.05 * time_limit)` deterministic seconds. Without this, a 300-task model spent
    about 2.5 s in presolve and found no solution within a 3 s budget. CP-SAT result
    `status="cancelled"` only when cancelled and not OPTIMAL.
11. **Decoder.** Locked tasks with fixed resources are reserved before start-only locks, so a
    start-only lock does not grab a machine another lock needs. When two fixed GA resource
    choices of one task collide, the later requirement falls back to greedy and `repairs` is
    incremented. Assignment across several requirements backtracks over the sorted feasible
    alternatives, instead of failing when the cheapest choice blocks a later requirement.
12. **GA.** Seeds: `initial_solution` first, then one individual per rule; seeds are capped at 20%.
    Mutation and sigma adaptation fires at every 10th non-improving generation, or when
    diversity < 0.05. Heuristic progress events carry `extra={"rule": ...}`.
13. **Alternatives (8.6).** Computed only when the primary is feasible. The pool has at most 12
    validated candidates. Candidates dominated by the primary are dropped. "Fastest", "Fewest
    late" and "Cheapest" are used only when strictly better than the primary on that objective.
    Other alternatives are labelled `"Alternative N"`, with N = their position + 1.
14. **Probe (8.7 step 7)** runs only if >= 1 s of the budget remains; its budget is
    `min(remaining, 0.25 * time_limit)`. Messages: `If the hard deadlines of "X" were relaxed, a
    schedule exists; it would be late by 50m.` and `Unlocking "A", "B" would remove the conflict:
    ...`.
15. **Explain.** `LOCKED` always says "Fixed by you at ..." (the engine cannot tell user locks
    from replan locks). DEPENDENCY messages name the binding predecessors and the type ("Starts as
    soon as X finishes", "30m after X starts", "Timed so it finishes when X finishes").
16. **Templates.** `build()` returns `id="draft"` and `metadata={"template", "parameters"}`.
    Manufacturing: every machine uses the two-shift calendar; `horizon_days = max(14,
    due_in_days + 7)`. Exam prep: the revision-1 lag is 2 days (1 day if `exam_in_days < 14`); the
    full mock's hard deadline is exam day - 1 at 10:00; the objective preset is `meet_deadlines`.
    Project: a fixed roster of 8 members (the first `team_size` are used) and 11 work items.
    Parameter type and range errors raise `ValueError`, like unknown names.
17. **Test layout.** `tests/engine/conftest.py` puts `backend/` (and the test folder, for
    `engine_helpers.py`) on `sys.path`. So `backend/.venv/bin/pytest backend/tests/engine -q`
    works from the repo root before WP2's `pyproject.toml` exists, and still works afterwards.
    The test registers a `slow` marker, but no WP1 test uses it: the 2000-task smoke test takes
    about 3 s. The CP-SAT vs brute-force test (1.10) uses only FS/SS dependencies with lags
    >= 0. With FF/SF a successor may start before its predecessor, so serial SGS enumeration is
    not complete; FF/SF are covered by the validator, decoder and CPM tests instead.

**WP3 (ui-developer), 2026-10-15** - frontend interpretations:
1. `api/types.ts`: `Violation.code` and `Issue.code` are typed `string` (the known codes are exported
   as `ViolationCode`/`IssueCode` unions) so a new server code never breaks the build.
   `SolverRun.elapsed_seconds` is treated as nullable (null while queued/running).
2. `api/contractExamples.ts` expands the document's `{"...": ...}` placeholders with values
   consistent with the surrounding example (e.g. a full `Metrics` object in `ScheduleSummary`).
3. The goal preset picked on the Optimize tab is stored in the plan (`Problem.objectives`, saved
   with PUT); runs are created with `objectives: null`. Strategy, seed, alternatives, GA and
   CP-SAT parameters are sent only while "Expert settings" is on; otherwise the request is
   `{"time_limit_seconds": <budget>, "objectives": null}` and the server fills defaults.
4. Conflict banner (412): "Reload" discards local edits; "Keep editing" fetches the current
   version number and the next autosave replaces the other change (explicit user choice).
   Autosave is paused while the conflict banner is unresolved.
5. SSE: one `addEventListener` per type of section 15; events are de-duplicated by `seq`. On an
   `EventSource` error with `readyState == CLOSED` (e.g. the 204 for a finished run) the client
   reads `GET /solver-runs/{id}`; after 3 errors it polls `GET /solver-runs/{id}/events?stream=false&after=<seq>`
   plus `GET /solver-runs/{id}` every 2 s.
6. "Lock at this time" sets `locked.resource_ids` to the placement's resources only when their
   count equals the task's current `requirements` length; otherwise only the start is locked.
7. `ReplanDialog` sends `task_updates` (duration changes) and `resource_unavailable` only;
   adding/removing tasks is done in the editor. `expected_problem_version` is the version after
   saving pending edits.
8. Compare tab defaults: `a` = approved schedule (else the second newest), `b` = newest other.
   CSV export is a plain link to `/schedules/{id}/export.csv` (relies on `Content-Disposition`).
9. Template instantiation sends `start_date` = the browser's local date and `utc_offset` = the
   browser's current offset.
10. Gantt closed-time shading mirrors section 4 calendar expansion client-side for display only;
    the engine remains authoritative. Rows are virtualized above 300.

### 2026-10-15 - WP2 API (backend-developer)

Paths and field names are exactly those of sections 13-16. Interpretations and small deviations:

1. **Extra module `api/context.py`** (not in 18): `AppContext` (settings, `Database`, `RunExecutor`)
   and the process-wide `WRITE_LOCK` (an `RLock`, so replan can reuse run-creation helpers while
   holding it). `create_app()` has no side effects: tables, startup recovery and the executor
   start in the lifespan, or lazily on the first request (a `TestClient` used without `with`).
   So importing `superplanner.api.main` never creates `backend/superplanner.db`.
2. **SQLite transactions.** Write sessions start with `BEGIN IMMEDIATE` (pysqlite autobegin
   turned off, `BEGIN` sent from an engine `begin` listener); readers use deferred `BEGIN`.
   In WAL mode a deferred read-then-write transaction fails at once with `SQLITE_BUSY` when
   another thread commits in between, and busy-waiting does not help. `busy_timeout=30000` is
   set per connection with the two PRAGMAs of 13.
3. **Check order for run creation:** 404 -> 409 `RUN_ALREADY_ACTIVE` -> 422 `PREFLIGHT_FAILED`
   (same order as replan). `details.issues` of `PREFLIGHT_FAILED` and of `STALE_SCHEDULE` hold
   only `error`-severity issues, and the message counts them ("Fix 2 problems before optimizing.").
   `DELETE /problems/{id}` with an active run -> 409 `RUN_ALREADY_ACTIVE` with `details.run_id`.
4. **Strict request bodies:** `SolverRunRequest`, `InstantiateRequest`, `ApproveRequest`,
   `ReplanRequest` (and `task_updates` items) reject unknown fields with 422 `VALIDATION_ERROR`,
   so `locked` in a `task_update` is a 422. A missing body is allowed for instantiate, solver-runs
   and approve. Template parameter errors (`ValueError`) -> 422 `VALIDATION_ERROR` with
   `details.errors[0].loc == ["body", "parameters"]`. `template_id` is `null` for `POST /problems`
   and import.
5. **Events.** Every event row's `payload` is the full SSE `data` object (common fields included),
   so `?stream=false` returns the stored payloads verbatim. `?after` also applies with
   `?stream=false` (the UI uses it). `elapsed_seconds` is measured by the worker from when it
   picked the run up (engine events are re-timed on that clock; it starts ~1 ms before
   `optimize()`). `run_cancelled` for a queued run is written by the request thread (seq 2). Startup
   recovery also appends a `run_failed` event so open streams and reconnecting clients terminate.
   Progress throttle: a `progress` event is written only if >= 0.5 s passed since the previous one;
   otherwise it is held, and the latest held one is written just before `phase_completed` (so at
   most one extra event per phase).
6. **Shutdown:** `RunExecutor.shutdown()` sets every cancel event and waits, so runs interrupted by a
   normal shutdown end as `cancelled` with their best-so-far schedule. Only a crash leaves rows for
   startup recovery.
7. **Schedules from a run** are stored only if the result has placements. A zero-task problem
   therefore completes with `primary_schedule_id: null`. `objectives`/`metrics` of stored
   schedules are never null.
8. **Approve:** `approved_problem_version` is always set to the current `problems.version`, even
   when it equals `base_problem_version`. When the version differs, placements are shifted by the
   difference between the snapshot's and the current `horizon_start` before re-validation. Two
   concurrent approvals both return 200 (serialized: the second supersedes the first); exactly one
   schedule ends `approved`.
9. **Compare:** `metric_deltas` are raw `b.metrics - a.metrics` (makespan is measured from each
   schedule's own horizon; only `task_deltas` minutes are re-based on a's horizon). `cost` delta is
   rounded to 2 decimals. In `task_deltas`, one-sided tasks (null `end_delta_minutes`) sort first,
   as the largest change. The union only covers placed task ids.
10. **CSV:** one row per task of the schedule's snapshot, in document order. An unplaced task has
    empty `start`, `end` and `lateness_minutes`. Booleans are `true`/`false`, `deadline` is the
    stored ISO string or empty, line endings are CRLF.
11. **Replan:** the cutoff is checked against the current document **before** `changes` are applied.
    An unknown task in `task_updates`, a duplicate id in `add_tasks` or an unknown `resource_id` in
    `resource_unavailable` -> 422 `VALIDATION_ERROR` (with `details.errors[].loc`). A frozen task
    without requirements (e.g. a milestone) is locked start-only (`resource_ids: null`). Tasks that
    are not frozen keep any user lock they already had. The replan `initial_solution` is computed
    by the worker from `source_schedule_id`: placements of the tasks that are unlocked in the
    snapshot, converted through absolute time, with `end = start + current duration`.
12. **Timestamps** generated by the API are UTC `...Z`, with milliseconds only when non-zero
    (`2026-10-15T09:20:01.200Z`, `2026-10-15T09:00:00Z`).
13. **Packaging.** `requirements.txt` pins the direct dependencies (fastapi, starlette, uvicorn,
    pydantic, SQLAlchemy, ortools, httpx, pytest) to the `.venv` versions; `pip install --dry-run`
    installs nothing. `run_api.sh` also honours `HOST` (default `127.0.0.1`) and passes extra
    arguments through to uvicorn. `tests/api/conftest.py` puts `backend/` and `tests/api/` on
    `sys.path` (shared helpers live in `tests/api/api_helpers.py`). It also hides Starlette's
    "use httpx2" deprecation warning, which `fastapi.testclient` triggers with the pinned httpx.
14. **Size limits.** Request bodies over `Settings.max_body_bytes` (env `MAX_BODY_BYTES`, default
    5 MiB) get 413 `PAYLOAD_TOO_LARGE` in the error envelope (`details.max_bytes`). A declared
    `Content-Length` is checked before reading, and a chunked body is counted while it streams.
    The `Problem` model caps documents (the 422 `loc` names the field): tasks 5000, resources 1000,
    dependencies 20000, requirements per task 50, alternatives/lock resource_ids 1000, blocked
    intervals 2000, weekly slots per day 48. Free text is capped too: `description` 10000 chars;
    group, kind, domain and terminology 200; reason 1000. Serialised `metadata` is capped at 16 KiB
    per task or resource and 64 KiB per problem. These caps are looser than the preflight solve
    limits (2000/200/10000), so a draft between the two can still be saved and preflight returns
    `TOO_LARGE` for it. Replan `changes` lists have the same caps.
15. **Replan nulls.** In `task_updates`, a field that is left out means "unchanged". An explicit
    `null` is accepted only for `earliest_start` and `deadline`, where it clears the value. For
    `name`, `duration_minutes`, `priority`, `deadline_hard` and `requirements`, a `null` gets 422
    `VALIDATION_ERROR` with `loc` `["body","changes","task_updates",i,<field>]`.
16. **CSV export.** Text cells (task id, name, group, resource ids and names) that start with
    `= + - @ TAB CR` get a leading `'` (OWASP CSV injection). `deadline` is converted to the plan's
    UTC offset, the same as `start` and `end`. Header and column order are unchanged.
17. **Explanations across closed time (phase 2 fix round).** The schedule critical chain follows a `CALENDAR` start
    to its binding dependency when the task starts at the first minute after it at which all its resources have a
    window holding the whole task. `DurationRisk.chain_sigma_minutes` adds the spreads of parts of one split
    estimate before squaring (`CTask.estimate_key` from `metadata.intake_key` with `parts > 1`). See PHASE2
    9.P2-fix item 3.

### 2026-10-19 - Phase 2 fix round 3: rule-based reader (backend-developer)

Interpretations of PHASE2 2.7.2 / 2.7.8 / 2.7.9 made while fixing four silent wrong-number defects (tests:
`backend/tests/integration_phase2/test_p2int_fixround3.py`):

1. **Clock windows vs duration ranges.** `CLOCK_RE` hours are whole 1-2 digit numbers (possessive, never the "10-1"
   of "10-15 hours"), and a range followed by a duration unit (hours/hrs/h, days/d, weeks/w, minutes, months) is a
   duration, never a working-time window. Bare windows without am/pm or ":" ("We work 9 to 5") are still read
   when the segment has a working-time word, as 2.7.8 requires.
2. **Bare 4-digit numbers** (no currency, multiplier, comma or decimal), in order: a frequency right after it is
   money; in a date-like position (in/by/of/since/from/until/before/after/during/year/born/joined/... or a
   month name, without a money word just before) a 1900-9999 number is a year, so an out-of-range year is never
   money; a 1900-2100 number is money when a frequency phrase is anywhere in the same clause ("I give 2000 to my
   parents each month"), asked (confidence 0.45) right after a money word (list extended with maintenance,
   charges, donation, subscription, tuition, electricity, ... and an optional "is/are/about"), and otherwise a
   year. `find_money` reports that last case through `years_skipped`; a clause that yields nothing else gets the
   new info note `YEAR_OR_AMOUNT` ("Water can 2000"). `find_money("2027")` is still `[]`.
3. **Far-future goal years.** A year in a date-like position more than 100 years after `today` (the existing
   goal-date limit) gets a `DATE_OUT_OF_RANGE` note and no target month, so the goal keeps the stated amount and
   asks `FIN_GOAL_DATE`. Years within 100 years (e.g. "by 2101") and full dates up to 2200 ("December 2140") are
   still used as goal months.
4. **Past payments.** Bare "paid" is no longer an income cue (only "get/gets/getting/am/is/are/being paid").
   A clause with a past one-off cue (bought, purchased, spent, paid, last week/month/year, ... ago, yesterday), no
   frequency, no forward goal cue (want, need, save, plan to, will, next, ...), no loan or holding words and no
   future date gets only `PAST_PURCHASE`; this check now runs before the income branch. A recurring amount with
   a spending cue and no forward goal cue is an expense, not a goal ("I pay 5k a month for the gym").
