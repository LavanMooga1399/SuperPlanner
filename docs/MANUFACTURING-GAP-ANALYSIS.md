# Manufacturing production planning: gap analysis and roadmap

Target use case: electronics and electro-mechanical manufacturing at the level of a railway Kavach loco unit —
multi-level BOMs with thousands of component lines, PCBs (SMT top/bottom, THT, wash, coating, test),
wire harnesses, sub-assemblies and final assembly/test, driven by inventory, purchase requests and work orders.

This document is based on reading the current code and on a scale benchmark run against it (October 2026).

## 1. Verdict

**SuperPlanner is not yet a manufacturing production planning tool.** Today it is a good *generic
finite-capacity scheduler*: a list of tasks, each with one fixed duration, resource requirements, dependencies,
calendars and deadlines, solved by heuristics, CP-SAT or a GA, independently validated and explained. That is
one layer (detailed scheduling) of what a factory needs, and even that layer is missing manufacturing basics
such as setup times, quantities and material constraints.

What HBL describes needs three layers working together:

| Layer | What it answers | Status |
|---|---|---|
| **Master data** (items, multi-level BOMs, routings, work centers) | *What* do we make and *how*? | Missing |
| **Material planning (MRP)** — demand, inventory, BOM explosion, netting, lead times, purchase requests, planned work orders | *What* must be made or bought, *how many*, by *when*? | Missing |
| **Capacity planning and detailed scheduling (APS)** — operations on work centers with setups, batches, shifts, material availability | *When* and *where* does each operation run? | Partial (generic scheduler) |
| **Execution feedback** — work order release, actuals, scrap, rework, re-planning | What actually happened, and what changes now? | Partial (replan with locks only) |

The good news: the scheduling core, validator, explanations, job queue, accounts, PostgreSQL, intake and UI shell
are reusable. The work is mostly *new domain modelling and a new planning layer on top*, not a rewrite.

## 2. Capability check against HBL's needs

| Need | Today | Gap |
|---|---|---|
| Item master (part numbers, revisions, make/buy, UoM) | None — tasks are free text | New `Item` model |
| Multi-level BOM (thousands of lines, quantities per parent, alternates, phantoms, scrap %) | None | New `BOM` model + explosion |
| Routing per item: ordered operations, work center, **setup time + run time per unit**, repeated operations (SMT top, SMT bottom), alternate routings | None. A task has one fixed `duration_minutes` | New `Routing`/`Operation` model; durations computed from quantity |
| Time varies by item passing through a stage | Not modelled (you'd hand-type each task) | Run time per item per operation, from routing |
| Inventory (on-hand, locations, lots/serials, reservations, safety stock) | None | New inventory model |
| Purchase requests / purchase orders, supplier lead times, MOQ, lot sizing | None | MRP output + PO tracking |
| Work orders (planned → firmed → released → in progress → done), parent/child links | None (a "plan" is a scenario snapshot) | New work-order lifecycle |
| Demand (sales orders, project milestones, forecasts) | Task deadlines only | Demand model + pegging |
| Material constraint: an operation can't start until its components are on hand or arrive | Not modelled | Material-aware scheduling |
| Sequence-dependent setup / changeover (SMT stencil and feeder changes by product family) | Not modelled | Setup matrix in solvers |
| Batching / lot splitting / transfer batches (overlap consecutive operations) | Not modelled | Lot sizing + overlap |
| Secondary resources (operators with skills, stencils, fixtures, test jigs) | Partially: multiple requirements with alternatives | Skills, tooling pools, calendars per person |
| Shifts, holidays, maintenance | Fixed weekly windows per resource + blocked intervals | Named shift patterns, overtime/extra shifts as optional paid capacity, stage-specific shifts |
| Several parallel lines/machines per stage, choose by urgency and load | Partly: a task can pick one of several alternative resources | Work-center groups, line activation, lot splitting across lines, line-specific speeds |
| Operations longer than one shift (pause at shift end, resume next shift) | No: a task must fit inside one open window | Resumable operations across shift breaks (non-resumable for e.g. reflow/cure) |
| Rework loops, yield, scrap, test failures | None | Yield per operation, rework routings |
| Serial numbers and traceability (railway/RDSO style) | None | Lot/serial genealogy |
| Capacity load view per work center (RCCP/CRP) | None (Gantt by resource only) | Load charts, bottleneck detection |
| Replanning on reality (breakdowns, late POs, rush orders) with frozen horizon | Replan with locked tasks | Event-driven replan using MRP + schedule |
| ERP integration (import items/BOM/routings/stock/POs, export WOs/PRs) | CSV/paste import of tasks only | ERP connectors + bulk import |
| Scale: thousands of operations over months | See benchmark below | Decomposition, new limits |

## 3. Scale benchmark (measured on the current code)

A synthetic Kavach-like product: per unit, N PCBs each going through SMT-top → AOI → SMT-bottom → AOI → THT →
wash → ICT, M harnesses (crimp → assemble), sub-assemblies of 4 parents each, final assembly, final test.
11 work centers, 6-day 06:00–22:00 shifts.

| Problem | Operations | Heuristic | Auto (GA) | Result |
|---|---|---|---|---|
| 8 PCBs, 6 harnesses, 5 units | 370 | 0.2 s | 44 s | feasible, 2.6–2.9 days |
| 20 PCBs, 15 harnesses, 10 units | 1,810 | 1.5 s | 61 s (GA only ~8% better) | feasible, 10.5–11.4 days |
| 20 PCBs, 15 harnesses, 25 units | 4,525 | — | — | **refused: `TOO_LARGE` (max 2,000 tasks per solve)** |

Findings:
- Hard limits: **2,000 tasks / 200 resources / 10,000 dependencies per solve**; CP-SAT is only used up to
  **300 tasks**. A realistic month of Kavach production (several units, many PCBs, harnesses, sub-assemblies)
  exceeds these.
- Above 300 tasks the GA spends its full time budget for a small gain. That is not the right tool at this size.
- Important framing: thousands of **BOM lines** do not mean thousands of **scheduled operations**. Purchased
  components (resistors, connectors, ICs) are *material*, handled by MRP; only *make* items (PCBs, harnesses,
  sub-assemblies, assemblies) have routings and become scheduled operations. The planner must separate the two —
  today it cannot.

## 4. Target design

### 4.1 Domain model

```
Item (part no, rev, description, UoM, make|buy|phantom, lead time, lot sizing rule, MOQ, safety stock,
      shelf life / MSL for moisture-sensitive parts, serialized?)
 └─ BOM (parent item rev → child item, qty per, scrap %, find number/ref designators, alternates,
         effectivity dates/serials, phantom)
 └─ Routing (item rev → ordered Operations; alternate routings)
      Operation: sequence no, work center, setup minutes, run minutes PER UNIT (or per panel with
                 units-per-panel), queue/move/wait times (e.g. coating cure, burn-in 24 h), transfer batch,
                 yield %, required tooling (stencil, fixture, test jig), required skill, inspection gate.
                 "SMT top" and "SMT bottom" are two operations on the same work center.
WorkCenter (lines/machines/benches, capacity, efficiency, calendar/shifts, setup families)
Resource pools: operators (skills, shifts, leave), tooling (stencils, jigs, fixtures — finite quantities)
Inventory: on-hand by item/location/lot/serial, reservations, in-inspection, WIP
Supply: purchase orders (supplier, qty, due, confirmed), purchase requests, open work orders
Demand: sales orders / project milestones (e.g. N loco units by date), forecasts, spares
WorkOrder: item, qty, due, status lifecycle, parent/child links (pegging), operations with actuals
```

### 4.1a Define first, then run

All of the above is set up once as **master data** in dedicated screens (and by Excel/CSV import or ERP sync),
validated, and versioned. Planning runs always read from that data; nothing is re-typed per run.

1. **Plant setup**: stages / work-center groups → lines and machines (speed, eligible items, setup families) →
   shift templates (regular 09:00–18:00, extended to 22:00, 24 h) → which shifts each stage or line runs, base vs
   optional (overtime) with cost and limits → holidays and maintenance → operators, skills, tooling.
2. **Product setup**: items → multi-level BOMs → routings (operations per part type, repeated stages such as SMT
   top/bottom, setup + run time per unit, waits, yields, tooling/skill needs).
3. **Stock and supply**: inventory snapshot, open purchase orders, open work orders.
4. **Demand**: orders / programme milestones with quantities, due dates and priorities.
5. **Check**: a data-health check before any run (items without routings, BOM cycles, operations with no
   eligible line, stages with no shift, missing lead times) with plain-language fixes.
6. **Run**: MRP → capacity check → detailed schedule, with chosen options (horizon, allow overtime, allow lot
   splitting, frozen period). Results are saved as a plan version that can be compared, approved and released.

### 4.2 Planning pipeline

1. **Demand & MRP** (fast, deterministic, explainable):
   multi-level BOM explosion → gross requirements → net against on-hand, reservations, open POs/WOs and
   safety stock → lot sizing (lot-for-lot, fixed, min/max, MOQ) → lead-time offsetting → **planned work
   orders** for make items and **purchase requests** for buy items, each **pegged** to the demand it serves.
   Exceptions: shortages, expedite/defer/cancel messages, long-lead items (chips can be 20–52 weeks).

   Plant-level material planning, in detail:
   - **All demand together.** Every open demand order (customer/programme orders, internal orders, spares,
     forecasts) for every finished item is planned in one run, not product by product. Components shared
     across products (the same IC, connector, PCB or harness used in several assemblies) are netted once for
     the whole plant.
   - **Staggered deliveries.** Purchase orders and already-raised purchase requests carry **multiple delivery
     schedule lines** (e.g. 10,000 pcs as 2,000/month from Jan to May), each with its own date and quantity,
     confirmed vs. requested, partial receipts, and goods-in inspection time before stock is usable. Work orders
     can also deliver in partial lots. Supply is a **dated timeline per item**, not a single number.
   - **Projected stock per item over time** (on-hand + scheduled receipts − requirements), showing exactly
     when an item goes short, for which demand, and by how much.
   - **Allocation of scarce material.** When supply cannot cover every order on time, components are allocated
     by demand priority and due date (configurable rules: priority first, earliest due first, or protect
     specific programmes), and the shortfall is reported per demand order with the parts that cause it.
   - **Existing purchase requests and POs are respected**: no duplicate requests; suggestions are expedite /
     postpone / increase / cancel messages on the existing ones, plus new PRs only for the uncovered remainder.
   - **Material feeds the schedule.** Each work-order operation that consumes a component can only start after
     the quantity it needs is available on that date (from stock, a delivery line, or a child work order).
     Capacity and material are planned together, so the plant plan is feasible on both.
   - **Plant plan outputs**: master production schedule (what finished items, how many, when), planned and
     firmed work orders for every level, purchase requests and PO change suggestions, the detailed operation
     schedule per stage and line, shortage and late-order lists with causes, and capacity load per stage.
2. **Rough-cut and capacity requirements planning**: load per work center per week vs. capacity; bottleneck
   (typically SMT, test, or skilled harness labour) highlighted before detailed scheduling.
3. **Detailed finite scheduling (APS)** of the *operations* of firmed/planned work orders:
   - durations = setup + run time × quantity (÷ efficiency), split into transfer batches so the next
     operation can start before the whole lot finishes;
   - **material availability**: an operation consuming components cannot start before they are on hand or
     due from an open PO / child work order;
   - **sequence-dependent setups** on SMT lines (product family changeovers), tooling and skilled-operator
     constraints, shifts, maintenance;
   - objectives: on-time delivery of top-level demand first, then setup time, WIP, overtime cost.
4. **Release and execution**: release WOs within a frozen window, capture actuals (start/finish, qty good,
   scrap, rework), and replan from events (late PO, machine down, test failure, rush order) without
   disturbing the frozen horizon.

### 4.3 Parallel lines, shifts and overtime

Requirements from HBL: each stage has several lines or machines; more lines are loaded when orders are urgent;
shifts are a regular 09:00–18:00, extended hours to 22:00, or 24-hour working; some stages run only in certain
shifts.

- **Work-center groups.** A stage (e.g. "SMT", "Harness assembly", "Functional test") is a group of lines or
  machines. Each line has its own speed factor (an older SMT line may be 30% slower), setup families, eligible
  items and calendar. Routings point at the *group*; the scheduler picks the line.
- **Load more lines when urgent.** The scheduler may (a) assign a work order's operation to any eligible line,
  and (b) **split a lot across several lines** (e.g. 400 boards → 250 on line 1, 150 on line 2), with a minimum
  split size and an extra setup per split. Urgency (due date, priority, demand being late) decides when extra
  lines and splits are worth their setup cost.
- **Shift patterns as named templates**, assigned per line or per stage, with effective dates:
  - *Regular*: 09:00–18:00 (with breaks, e.g. lunch 13:00–13:45), Mon–Sat.
  - *Extended*: regular + 18:00–22:00 **overtime**.
  - *24 hours*: three shifts (e.g. 06–14, 14–22, 22–06, the night shift crossing midnight).
  - Holidays, plant shutdowns and maintenance windows on top.
- **Stage-specific shifts.** e.g. SMT and reflow run 24 h, manual harness assembly and final test only in the
  regular shift, coating cure continues unattended overnight. Each stage/line has its own allowed shifts.
- **Overtime and extra shifts as a decision, not just a fixed calendar.** Each line has *base* shifts (always
  available) and *optional* shifts (overtime to 22:00, a weekend shift, a night shift) with a cost per hour and
  limits (max overtime hours per week). The planner opens optional capacity only when it is needed to meet due
  dates, and the plan explains why ("overtime on SMT-2 Tue–Thu to make the 30 Nov loco milestone"). Planners
  can also force a pattern for a period ("run 24 h on SMT from 1–15 Dec").
- **People follow shifts.** Operators and skills belong to shifts; a line is only usable when a qualified crew
  is on shift. Unattended operations (cure, burn-in, ovens) need the machine but not the crew.
- **Operations across shift boundaries.** Long operations may pause at the end of a shift and resume next shift
  (resumable), except ones that must not be interrupted (reflow profile, cure, burn-in), which must fit inside
  one continuous window or run on a 24 h line.
- **What-if on capacity.** Compare "regular only", "regular + overtime" and "24 h on bottlenecks": completion
  dates, late orders, overtime hours and cost side by side.

### 4.4 Algorithms at this scale

- **Decompose** instead of one giant solve: MRP first (lot-level), then schedule operations; schedule the
  **bottleneck work centers** first, then subordinate stations; **rolling horizon** (e.g. detailed 2–4 weeks,
  rough beyond).
- **CP-SAT** per bottleneck / per time window with interval variables, `AddNoOverlap`/`AddCumulative`,
  setup transition costs (circuit or precomputed setup matrix), optional intervals for alternate machines.
- **Fast dispatching heuristics** for the full horizon: ATC / setup-aware rules, material-aware list
  scheduling (reusing the current decoder).
- **Large Neighbourhood Search** (re-optimise a window or a work center while fixing the rest) to improve
  quality at thousands of operations; GA only as an optional improver on small sub-problems.
- Keep the **independent validator** (extended with material, setup and tooling checks) and the
  **explanations** ("WO-123 starts Tue 14:00 because stencil S-7 is in use until then" / "waiting for PO-881").

## 5. Kavach / railway electronics specifics to plan for

- Serialized units with **genealogy** (which PCB serials and component lots went into which loco unit) for
  traceability and field failures.
- **Test and certification gates** (ICT, functional test, burn-in, environmental/EMC sampling) with failure
  and **rework loops** and realistic yield.
- **Moisture-sensitive components** (floor-life / baking), ESD handling, conformal coating cure times.
- **Long-lead and obsolescence-prone components**; alternates in the BOM; allocation of scarce parts to the
  highest-priority demand.
- **Engineering changes** (BOM/routing revisions with effectivity by date or serial).
- Project-style demand: N units per loco programme with milestones and penalties.

## 6. What we can reuse

Engine core (decoder, validator, explanations, CP-SAT and GA solvers), the solver selector, the PostgreSQL job
queue and workers (long MRP/scheduling runs), accounts and per-user data separation (extend to organisations),
Alembic migrations, the intake layer (CSV/paste import → extend to BOM/routing/stock import), the Gantt and
dependency views, what-if/compare, and the deployment setup.

## 7. Roadmap

| Phase | Scope | Outcome |
|---|---|---|
| **M1 — Manufacturing master data** | Items, multi-level BOMs, routings with setup + per-unit run times and repeated operations, work-center groups with parallel lines (speed, eligibility), shift templates (regular / extended / 24 h, stage-specific), tooling and skills; bulk import (CSV/Excel) and a BOM tree + routing editor | A Kavach-like product and plant can be described faithfully |
| **M2 — Inventory, demand and MRP** | On-hand/lots, open POs and PRs with staggered delivery schedule lines, open WOs, multiple demand orders across all products (plant level), shared-component netting, projected stock timeline, scarce-material allocation by priority; BOM explosion, netting, lot sizing, lead-time offset, pegging; planned WOs and purchase requests; shortage and exception dashboard | "What to make, what to buy, by when" for thousands of BOM lines |
| **M3 — Manufacturing APS** | Operation-level scheduling from WOs: quantities, transfer batches, line selection and lot splitting across parallel lines, optional overtime/extra shifts with cost, resumable operations across shift breaks, setup matrices, tooling/skills, material availability; decomposition, bottleneck-first, rolling horizon, LNS; capacity load charts per work center; validator + explanations extended | Feasible, explainable schedules for thousands of operations in minutes |
| **M4 — Execution and replanning** | WO release, shop-floor actuals (barcode-friendly), scrap/rework/yield, event-driven replanning with frozen horizon, KPIs (OTD, utilisation, WIP, setup time) | Closed loop with the shop floor |
| **M5 — Integration and traceability** | ERP connectors (items, BOMs, stock, POs in; WOs, PRs out), serial/lot genealogy, ECO handling, multi-plant/organisation accounts | Production use alongside HBL's ERP |

Each phase follows the same agent-team process used so far (design → plan → build → test → security review →
fix → verify), with acceptance tests built from a realistic anonymised Kavach-like dataset.

## 8. Data to request from HBL (anonymised is fine to start)

1. One product's **indented BOM** (all levels, qty per, make/buy, alternates).
2. **Routings** for its make items: operations, work centers, setup and run times per unit/panel, waits
   (cure, burn-in), yields.
3. **Work centers, lines and shifts**: how many parallel lines/machines per stage and their speeds, which shifts each stage runs (regular, overtime to 22:00, 24 h), overtime rules and cost; SMT lines, AOI, THT, wave/selective solder, wash, coating, ICT/FCT, harness
   benches, assembly and test stations; operator skills; key tooling counts.
4. **Inventory snapshot** and **open purchase orders** with supplier lead times.
5. **Demand**: units required by date (loco programme milestones), plus spares.
6. The current planning process and pain points (how plans are made today, what goes wrong).
7. ERP in use and how data can be exported (CSV/Excel/API).
