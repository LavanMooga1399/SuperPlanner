# SuperPlanner M2 - Inventory, purchasing, demand, plant-level MRP and work orders (design + plan + acceptance)

Status: design for build. Phase M2 of `docs/MANUFACTURING-GAP-ANALYSIS.md` ("GA n"). Builds on the M1 master data
as built (`docs/M1-DESIGN.md`, cited "M1 n", including the section 17 implementation notes) and on the
PostgreSQL-only, enterprise-default platform (`docs/ARCHITECTURE.md` 25 "2026-10-26", `docs/DEPLOY.md`).
Conventions not restated here come from M1 (9.1 API conventions, 6.1 DB conventions, 8 import pipeline) and
`docs/PHASE2B.md` (error envelope, If-Match, ownership). Where this document and those disagree for anything new in
M2, this document wins. Developers record interpretations only in section 22 (own subsection).

User intent (product owner, verbatim summary): before running the (capacity) planning, do **material planning**
based on the BOMs, inventory, purchase requests already placed and staggered deliveries; generate an **entire
manufacturing-plant-level plan**; there are **multiple demand orders for various items**; behave like a real plant
production planner. Scale: Kavach loco unit, multi-level BOMs with thousands of parts, many demand orders.

## Table of contents

0. Summary of decisions
1. Scope, principles, decisions on deferred review items
2. Package layout, dependency rules
3. Domain model (M1 changes, M2 entities)
4. Inventory ledger
5. Purchasing (PR / PO with delivery schedule lines)
6. Demand orders
7. Work orders, components, reservations, kitting
8. MRP engine (algorithm, rounding, lead times, alternates, pegging, exceptions, what-if, conversion, test vectors)
9. Database schema (migration `0004_mfg_m2`)
10. Workspaces, roles, permissions, audit
11. Import / export
12. REST API
13. Sample data
14. Frontend
15. Performance targets
16. Delivery plan (work packages, ownership, milestones)
17. Testing strategy (targeted during work, one full run at the end)
18. Acceptance criteria (Gate 2)
19. Changes to existing code and tests
20. Deferred items and plug-in points for M3
21. Open questions for the product owner
22. Implementation notes

---

## 0. Summary of decisions

1. **Master vs transactional data.** Locations, suppliers and item-suppliers are **master data** (M1 rules: plant
   lock, `data_version`, part of `MfgDataset` and `fingerprint`, health check). Inventory, purchase documents, demand
   orders, work orders and MRP runs are **transactional** (no plant lock; row locks in a fixed order; not in the
   fingerprint). Both live in the same `/api/v1/mfg` area and the same import wizard.
2. **Inventory is an append-only ledger.** Every stock change is a *posting* (header) with *transactions* (lines);
   `mfg_inv_balances` (item x location x lot) is maintained in the same transaction under `SELECT ... FOR UPDATE`
   row locks taken in a fixed key order; balances are never edited directly; on-hand and reserved can never go
   negative (service check + DB `CHECK` backstop). Corrections are reversals. Postings accept an `Idempotency-Key`.
3. **One purchase-document model for PRs and POs**: header -> lines -> **delivery schedule lines** (staggered
   deliveries, requested and confirmed dock dates, partial receipts). PR lifecycle `draft -> submitted -> approved
   -> ordered` (convert to PO) with reject/revise/cancel; PO lifecycle `draft -> open -> partially_received ->
   received -> closed` with cancel. "Overdue" is computed, never a status.
4. **Demand orders** (customer, internal, spares, project) with lines (item, qty, due date, priority, optional
   **unit serial range** that drives serial effectivity). Only `open` orders are planned.
5. **Work orders** with a frozen component list (snapshot of the effective BOM at creation, with scrap/yield
   inflation and integer rounding), status flow `planned (firm) -> released -> in_progress -> completed -> closed`
   (+ `cancelled`), hard reservations, a per-WO **kitting check** and a plant-wide **component shortage list**.
6. **MRP is a pure, deterministic function** `run_mrp(snapshot, params) -> MrpResult` over exact dates (no buckets
   in the computation; buckets only in views), processed by **low-level code**, with priority-aware allocation of
   existing supply, lot sizing (lot-for-lot, fixed, period) + MOQ + order multiple + purchase pack + integer rounding,
   purchase lead times in calendar days and **routing-derived manufacturing lead times in working days**, safety
   stock, lot expiry, reservations, alternates "when short" (two-pass, deterministic), **full pegging** stored per
   run (up and down), a **forward pass** that projects realistic dates for every order and demand line (the limiting
   path explains *why* a demand is late), and exception messages with plain-language explanations.
7. **An MRP run is a stored, immutable, versioned snapshot** (`live` or `what_if`) with KPIs, compare, export and a
   staleness indicator. It runs **synchronously** (target: Kavach-scale in seconds); one run at a time per plant.
   Planned orders are **firmed or released** only from the latest `live` run, into real WOs/PRs, exactly once.
8. **Roles are in M2** via **plant workspaces**: the data owner can add other accounts as members of the plant
   with roles `viewer`, `planner`, `purchaser`, `store_keeper`, `approver`; every mfg endpoint declares one
   permission; the audit actor is the real user. Scheduling and finance areas are unchanged (per user). See
   open question Q1 for the fallback.
9. **Rounding rule** (decided): explosion arithmetic stays continuous (M1 4.4); quantities are rounded **per order**:
   component requirements of each order are rounded up to whole units for count-UoM items, and planned order sizes
   go through lot rule -> MOQ -> multiple -> purchase pack -> integer (count UoM). Stored quantities of count-UoM
   items are integers everywhere (postings, documents).
10. **Migration `0004_mfg_m2`**: 22 new tables, new columns on `mfg_items` and `mfg_plant`. Head becomes
    `0004_mfg_m2`. Reset and `reassign-owner` cover every new table; workspace memberships survive a data reset.
11. **Delivery**: five packages (A domain+DB+samples, E MRP engine, B API, C UI, D QA). The contract (sections 3,
    8.2, 9, 12) is frozen at milestone A1/E0 so C and D start on day 0 against typed examples. Developers run only
    targeted tests; **one** full PostgreSQL backend suite + both Playwright configurations run once at the end (D).

---

## 1. Scope, principles, decisions on deferred review items

**In M2:** locations; lots (with expiry and hold); suppliers; item-supplier terms; item standard cost and external
references; inventory ledger (receipts, issues, adjustments, transfers, counts, WO issue/return/receipt, shipment,
reversal), reservations; purchase requests and purchase orders with staggered schedule lines and partial receipts;
demand orders with serial ranges; work orders with components, reservations and kitting; plant-level MRP with
pegging, exceptions, what-if and compare; planned order firm/release; shortage dashboard; import/export of all of it
through the M1 wizard; samples (`small`, `medium`, `kavach`) extended with stock, POs/PRs, demand and WOs; workspaces
and roles; audit of every write.

**Principles (binding, in addition to M1 P1-P6):**
- P7 **Feasibility first.** MRP never drops, nets away or silently shortens a requirement: every requirement is fully
  pegged (to existing supply, possibly late, or to a planned order); every lateness is reported with its cause.
  Stock never goes negative. Health-check errors (Gate 1) block MRP runs.
- P8 **Ledger, not state.** Stock is derived from postings; balances are a maintained cache under row locks;
  documents' received/issued/shipped quantities move only through postings.
- P9 **Explainability.** Every exception and every late demand carries a plain-language message, the numbers it is
  based on and a server-built link to the object to act on.
- P10 **Determinism.** Same inputs and params -> byte-identical `MrpResult` (sorted iteration everywhere, no set
  iteration, no clock reads inside the pure package; `as_of` is a parameter).
- P11 **Infinite capacity in M2.** MRP offsets by lead times only. Finite capacity, line choice, lot splitting and
  shift decisions are M3; M2 outputs are exactly what M3 consumes (WOs with quantities, dates, components).

**Decisions on recommendations deferred from M1:**

| Recommendation | Decision | Reason |
|---|---|---|
| Supplier master | **M2** (`mfg_suppliers`) | POs need a supplier; supplier lead time feeds MRP |
| Item-supplier (lead time, MOQ, multiple, price, preferred, purchase unit + conversion) | **M2** (`mfg_item_suppliers`) | MRP lot sizing and lead times come from the preferred source; PR/PO prices |
| Item costs | **M2: `standard_cost` per item** (stock UoM, plant currency) + `unit_price` on item-suppliers/PO lines. Cost roll-up, actual costing: **M5** | Inventory value and PR/PO value need a price; costing is an ERP concern |
| Warehouses/locations | **M2**, one level: locations with `kind` (`stores`, `line_side`, `inspection`, `quarantine`). Multi-warehouse hierarchy: M5 (with multi-plant) | One plant, a handful of stores areas is the real need now |
| Lots | **M2** (`lot_controlled` items; expiry; hold) | Shelf-life parts (coating, MSL ICs) must be netted by expiry |
| Serial-tracked stock | **M4/M5** (captured at WO completion, genealogy). M2 keeps **unit serial ranges on demand orders and WOs** for effectivity; serialized items are stocked as integer quantities | Serial capture is execution (M4); genealogy is M5 |
| Quantity rounding (MOQ/multiples/scrap/yield, integer for EA) | **M2**, rule in 8.6 | Needed for real order quantities and kits |
| Sample reset with M2 foreign keys | **M2** (9.4, test 17.3) | |
| IANA time zones instead of fixed `utc_offset` | **M3** | M2 is date-granular (business dates in the plant zone). DST only changes intra-day shift windows, which only M3 scheduling consumes; doing it with the M3 engine adapter changes `calendar.py` once, not twice. India (first customer) has no DST |
| Stable external references (ERP codes) | **M2**: `external_ref` (<= 64 chars, unique per owner when set) on items and every new M2 master/document table | ERP import/export matching from the start |
| `plant_id` for multi-plant readiness | **M5** | Invariant kept and documented: one owner = one plant (`mfg_plant` is unique per owner, workspaces address the plant by its owner). M5 adds `plant_id` to every `mfg_*` table with a mechanical backfill of the single plant id; an unused column now would be untested |
| Line-specific operation times, batching compatibility, operator absences | **M3** (scheduling) | Not used by infinite-capacity MRP. Noted in section 20 |

**Out of M2:** finite capacity and scheduling (M3); shop-floor operation actuals, backflush, rework routing (M4);
forecasts with consumption, distribution/multi-plant, ERP connectors, genealogy, costing (M5); supplier portals; PR
approval chains with amount limits (single approval step in M2).

---

## 2. Package layout, dependency rules

```
backend/superplanner/mfg/                      pure (as M1): no fastapi/sqlalchemy
  model.py           M1 + new fields on ItemInput / PlantInput (3.1)                          [A]
  model_m2.py        M2 Inputs/Records/refs/snapshots (3.2-3.9)                               [A]
  limits.py          + M2 constants (3.10)                                                    [A]
  dataset.py         MfgDataset + locations, suppliers, item_suppliers; fingerprint covers them  [A]
  bundle.py          SHEETS + M2 sheets (11)                                                  [A]
  health.py messages.py   + codes 44-47 (3.11)                                                [A]
  workdays.py        WorkCalendar: workday_add / workday_sub / is_workday (8.5)               [A, frozen at A1]
  inventory.py       pure posting rules: validate lines, FEFO pick, balance deltas, reservation effects (4)  [A]
  purchasing.py      status machines, receipt allocation, overdue/available-date rules (5)    [A]
  demand.py          status machine, serial-range rules (6)                                   [A]
  workorders.py      status machine, kitting computation, reservation planning (7)            [A]
  mrp/                                                                                         [E]
    __init__.py      run_mrp, order_components, manufacturing_lead_days, views exports
    model.py         MrpParams, MrpSnapshot, MrpResult and parts (8.2)   (frozen at E0)
    explode.py       order_components (8.7), phantom blow-through, alternates split
    leadtime.py      manufacturing_lead_days, purchase lead time resolution (8.5)
    llc.py           low-level codes (8.4)
    netting.py       requirement ordering, allocation of existing supply (8.8)
    lotsize.py       lot sizing + rounding (8.6)
    engine.py        run_mrp orchestration, alternates second pass (8.9)
    forward.py       projected dates, limiting path (8.10)
    exceptions.py    exception generation (8.12) ; messages.py texts
    views.py         timeline, buckets, pegging traversal, compare (8.13)
  io/                + M2 sheets in spec/plan/export (WP-B, as M1)                             [B]
  samples/           + kavach_m2.py, small_m2.py, medium_m2.py (13)                           [A]
backend/superplanner/api/mfg/
  db_models_m2.py    ORM rows of section 9; ALL_MFG_MODELS / ALL_MFG_TABLES                    [A]
  repo_m2.py         loaders, lockers (9.5)                                                   [A]
  access.py          workspace resolution, permission dependency, actor binding (10)          [B]
  schemas_m2.py      list/page/action wrappers                                                 [B]
  mrp_store.py       MrpResult -> rows, rows -> API views (12)                                 [B]
  services/          locations.py suppliers.py inventory.py purchasing.py demand.py workorders.py
                     mrp.py shortages.py members.py (+ edits: items.py, plant.py, imports.py, samples.py)   [B]
  router_m2.py       APIRouter(prefix="/mfg") for every M2 endpoint                           [B]
frontend/src/mfg/**  (+ new pages/components of section 14)                                   [C]
```

Rules: `superplanner.mfg.mrp` imports only `superplanner.mfg` (model, model_m2, dataset, bom, routing, units,
workdays). `superplanner.mfg` still never imports `api` or `engine`. `api/mfg` services call `mfg.*` pure functions
for every rule that is not a database concern (status transitions, posting validation, kitting arithmetic, MRP).

---

## 3. Domain model

Pydantic v2, `extra="forbid"`, `<Entity>Input` / `<Entity>Record` as M1 3. Common types from M1 3.1, plus:

```python
ExtRef     = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64,
                                              pattern=r"^[^\x00-\x1f\x7f]+$")]
DocNumber  = Code                                   # PO/PR/DO/WO numbers, 1..32, same pattern as Code
LotCode    = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64,
                                              pattern=r"^[^\x00-\x1f\x7f]+$")]
SignedQty  = Annotated[float, Field(ge=-1_000_000_000, le=1_000_000_000)]   # != 0 checked by the model
Priority   = Annotated[int, Field(ge=1, le=9)]      # 1 = most important
Role       = Literal["viewer", "planner", "purchaser", "store_keeper", "approver"]
LocationKind = Literal["stores", "line_side", "inspection", "quarantine"]
```

New id prefixes: `loc_` location, `sup_` supplier, `isu_` item-supplier, `lot_` lot, `bal_` balance, `pst_` posting,
`txn_` transaction, `rsv_` reservation, `pdc_` purchase document, `pln_` purchase line, `psc_` purchase schedule,
`dmo_` demand order, `dml_` demand line, `wko_` work order, `woc_` WO component, `nsr_` number series, `mrr_` MRP run,
`mpo_` planned order, `mex_` MRP exception, `mir_` MRP item result, `mdr_` MRP demand result, `mbr_` member.

**Quantities:** all M2 quantities are in the **item's stock UoM**. For count-UoM items (`units.is_count`) every
posted or document quantity must be an integer (422 `INV_FRACTIONAL_QTY`, `loc` to the field); others are rounded
to 6 decimals on write. Internal comparisons use `EPS = 1e-6`.

### 3.1 Changes to M1 models (additive)

`ItemInput` gains (columns in 9.2):

| Field | Type | Default | Rules |
|---|---|---|---|
| `external_ref` | ExtRef \| None | None | unique per owner when set (409 `MFG_DUPLICATE_KEY`) |
| `standard_cost` | float 0..10^9 \| None | None | per stock UoM, plant currency |
| `lot_controlled` | bool | false | stock carries lot codes; receipts need a lot code (4.3) |
| `lot_period_days` | int 1..365 \| None | None | required iff `lot_rule == "period"` (422) |
| `lot_rule` | `Literal["lot_for_lot","fixed","period"]` | `"lot_for_lot"` | `period` added (8.6) |

Item PUT rule added: `uom` cannot change while the item has balances, transactions, open documents or WOs (409
`MFG_IN_USE`, `details.references`). Item DELETE in-use counts add `item_suppliers` (cascade, not blocking),
`balances`, `transactions`, `purchase_lines`, `demand_lines`, `work_orders`, `wo_components`, `lots` (blocking).

`PlantInput` gains:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `mrp_workdays` | list[Weekday] 1..7 unique | `["mon","tue","wed","thu","fri","sat"]` | working days for manufacturing lead-time offsets |
| `mrp_day_minutes` | float 60..1440 | 480 | routing minutes counted as one manufacturing day (8.5) |
| `mrp_defer_tolerance_days` | int 0..90 | 7 | defer messages only beyond this slack |
| `mrp_release_window_days` | int 0..90 | 7 | planned orders starting within this window get "release now" |
| `over_receipt_pct` | float 0..100 | 0 | allowed receipt above a schedule line's open qty |

Clients must send these fields on `PUT /items/{id}` and `PUT /plant` (full replacement, M1 9.1); the M2 UI forms do.

### 3.2 Location

`LocationInput`: `code: Code` (unique), `name: Name`, `kind: LocationKind`, `receipt_default: bool = false`
(at most one active location has it; setting it clears it elsewhere in the same transaction), `active: bool = true`,
`external_ref: ExtRef | None`, `note: Text500 = ""`. Record: + `id, row_version, created_at, updated_at`.

Nettable (MRP and kitting): `stores` and `line_side` = available now; `inspection` = available at
`max(as_of, last_receipt_on + item.receiving_days)` (8.3); `quarantine` = never. Kitting (7.4) uses only `stores`
and `line_side`. Postings into an inactive location -> 422 `INV_LOCATION_INACTIVE`.

### 3.3 Supplier and item-supplier

`SupplierInput`: `code: Code` (unique), `name: Name`, `lead_time_days: int 0..730 | None` (supplier default),
`currency: str 0..8 = ""`, `contact_name: str 0..200 = ""`, `email: str 0..200 = ""`, `phone: str 0..50 = ""`,
`address: Text500 = ""`, `active: bool = true`, `external_ref`, `note`. Record + `item_count`.

`ItemSupplierInput`:

| Field | Type | Default | Rules |
|---|---|---|---|
| `item_id` | EntityId | required, immutable | buy item (422 `MFG_ITEM_NOT_BUY`) |
| `supplier_id` | EntityId | required, immutable | `(item, supplier)` unique (409) |
| `supplier_part_number` | str 0..64 | `""` | |
| `lead_time_days` | int 0..730 \| None | None | None = supplier's, else item's |
| `min_order_qty`, `order_multiple` | NonNegQty | 0 | 0 = use the item's value |
| `purchase_unit` | Code \| None | None | label only (e.g. `REEL`); None = the item UoM |
| `units_per_purchase_unit` | float (0, 10^6] | 1 | stock-UoM units per purchase unit (pack size); count items: integer (422) |
| `unit_price` | float 0..10^9 \| None | None | per **stock** unit |
| `currency` | str 0..8 | `""` | |
| `preferred` | bool | false | setting true clears `preferred` on the item's other rows (same transaction, their `row_version` bumps) |
| `active` | bool | true | |
| `note` | Text500 | `""` | |

Record: + `item: ItemRef`, `supplier: Ref`. **Source resolution** (MRP, PR defaults): the preferred active row whose
supplier is active; else the active row with the smallest effective lead time, then supplier code. Effective
values: lead time = row -> supplier -> item; MOQ/multiple = row if > 0 else item; pack = row's
`units_per_purchase_unit` (1 without a row).

### 3.4 Lot, balance, posting, transaction, reservation (records; inputs in 4)

- `LotRecord`: `id, item: ItemRef, lot_code, expires_on: date|None, received_on: date|None, supplier_lot: str 0..64,
  hold: bool, note, on_hand (sum over balances), row_version, created_at, updated_at`. `LotUpdate` (PUT):
  `expires_on, supplier_lot, hold, note`. A lot on hold is not nettable and not issuable (422 `INV_LOT_ON_HOLD`).
- `BalanceRow`: `id, item: ItemRef, location: LocationRef {id, code, name, kind}, lot: LotRef {id, lot_code,
  expires_on, hold} | None, qty_on_hand, qty_reserved, qty_available (= on_hand - reserved), nettable: bool,
  last_receipt_on, value (qty_on_hand x standard_cost | None), updated_at`.
- `TransactionRow`: `id, seq (int, global ascending), posting_id, posting_number, line_no, txn_type, txn_date, item:
  ItemRef, location: LocationRef, lot: LotRef | None, qty (signed), balance_after, unit_cost | None, ref: DocRef |
  None, actor: {id, name}, created_at`. `DocRef = {type: "po"|"pr"|"wo"|"demand", id, number, line_no: int|None,
  schedule_seq: int|None, label}`.
- `PostingRecord`: `id, number, type, txn_date, note, reason_code, actor, created_at, reversal_of: {id, number} |
  None, reversed_by: {id, number} | None, lines: [TransactionRow], warnings: [{code, message}]`.
- `ReservationRow`: `id, wo: {id, number}, component_id, item: ItemRef, balance_id, location: LocationRef, lot:
  LotRef | None, qty, created_at`.

### 3.5 Purchase documents (PR and PO share the model; `doc_type` comes from the path)

`PurchaseDocInput`:

| Field | Type | Default | Rules |
|---|---|---|---|
| `number` | DocNumber \| None | None = next from the series (`PR-000001` / `PO-000001`) | unique per owner and doc type |
| `supplier_id` | EntityId \| None | None | PO: required (422 `PUR_SUPPLIER_REQUIRED`); PR: optional suggestion |
| `currency` | str 0..8 | supplier's or `""` | |
| `order_date` | PlanDate \| None | None | PO date (informational) |
| `note` | Text500 | `""` | |
| `external_ref` | ExtRef \| None | None | unique per owner and doc type when set |
| `lines` | list[PurchaseLineInput] 1..500 | | |

`PurchaseLineInput`: `id: EntityId | None` (keep existing), `line_no: int 1..9999 | None` (None -> 10, 20, ... in
order), `item_id` (buy item, 422 `MFG_ITEM_NOT_BUY`), `unit_price: float 0..10^9 | None` (None -> item-supplier
price on create), `note`, `schedules: list[ScheduleInput] 1..100`.

`ScheduleInput`: `id | None`, `seq: int 1..999 | None` (None -> 1..n), `requested_date: PlanDate` (**dock date**
asked for), `confirmed_date: PlanDate | None` (supplier-confirmed dock date), `qty: Qty` (stock UoM).

Record (`PurchaseDocRecord`): input fields + `id, doc_type, status, supplier: Ref | None, source ("manual"|"mrp"|
"import"), source_run_no, submitted_at, submitted_by, approved_at, approved_by, rejected_reason, value (sum qty x
price, None if any price missing), open_value, overdue_count, row_version, created_at, updated_at`; lines add
`item: ItemRef, status ("open"|"converted"|"cancelled"|"closed"), qty (sum of schedules), received_qty, open_qty,
converted_to: {doc_id, number, line_no} | None, source_pr: {doc_id, number, line_no} | None`; schedules add
`received_qty, open_qty, closed: bool, dock_date (= confirmed_date or requested_date), available_date
(= dock_date + item.receiving_days), overdue: bool, overdue_days: int`. List rows (`PurchaseDocSummary`) omit
lines and add `line_count, next_dock_date`.

### 3.6 Demand order

`DemandOrderInput`: `number: DocNumber | None` (series `DO-000001`), `demand_type: Literal["customer","internal",
"spares","project"]`, `customer: str 0..200 = ""`, `program: Code | None` (e.g. loco programme), `priority:
Priority = 5`, `note`, `external_ref`, `lines: list[DemandLineInput] 1..500`.

`DemandLineInput`: `id | None`, `line_no | None`, `item_id` (active, not phantom: 422 `DEM_ITEM_NOT_PLANNABLE`),
`qty: Qty`, `due_date: PlanDate`, `serial_from: int 1..10^9 | None`, `serial_to: int | None` (both or neither;
item `serialized` else 422 `MFG_SERIAL_NOT_ALLOWED`; `serial_to - serial_from + 1 == qty`, else 422
`DEM_SERIAL_QTY_MISMATCH`), `priority: Priority | None` (overrides the header for this line), `note`.

Record: + `id, status ("draft"|"open"|"closed"|"cancelled"), row_version, ...`; lines add `item: ItemRef,
shipped_qty, open_qty, line_status ("open"|"shipped"), effective_priority, projection: {run_id, run_no,
projected_date, late_days, status} | None` (from the latest completed `live` MRP run, one extra query).

### 3.7 Work order

`WorkOrderInput`:

| Field | Type | Default | Rules |
|---|---|---|---|
| `number` | DocNumber \| None | series `WO-000001` | unique |
| `item_id` | EntityId | required, immutable | make item (422 `MFG_ITEM_NOT_MAKE`) |
| `qty` | Qty | required | **good** output quantity; count UoM integer |
| `due_date` | PlanDate | required | |
| `start_date` | PlanDate \| None | None -> `workday_sub(due_date, manufacturing_lead_days(qty))` | `start <= due` (422) |
| `priority` | Priority | 5 | |
| `serial_from`, `serial_to` | int \| None | None | unit serial range for effectivity; serialized item; `to - from + 1 == qty` |
| `demand_line_id` | EntityId \| None | None | informational link (pegging is computed by MRP) |
| `note`, `external_ref` | | | |
| `components` | list[WoComponentInput] \| None | None | POST None = generate (7.2); PUT None = keep |

`WoComponentInput`: `id | None`, `item_id` (not phantom), `required_qty: NonNegQty`, `operation_seq: int | None`,
`find_number: FindNumber | None`, `note`.

Record: + `id, status, item: ItemRef, qty_completed, qty_scrapped, open_qty (= max(0, qty - qty_completed)), bom:
{id, revision, version} | None, routing: {id, code, version} | None, demand_line: {id, order_id, order_number,
line_no} | None, source ("manual"|"mrp"|"import"), source_run_no, source_planned_no, released_at, completed_at,
closed_at, shortage_count (live, single GET only), components: [{id, item: ItemRef, required_qty, issued_qty,
open_qty, reserved_qty, operation_seq, find_number, alt_group, bom_line_id, note}], row_version, ...`.

### 3.8 Workspace member

`MemberInput`: `email: str 3..254` (POST only, an existing active account), `roles: list[Role] 1..5 unique`,
`active: bool = true`. `MemberRecord`: `id, user: {id, email, display_name}, roles, active, row_version,
created_at, updated_at`.

### 3.9 MRP API models

Defined in 8.2 (`MrpParams` = request body) and 12.4 (response shapes).

### 3.10 Limits (`limits.py` additions)

| Constant | Value | Meaning |
|---|---|---|
| `MAX_LOCATIONS` / `MAX_SUPPLIERS` / `MAX_ITEM_SUPPLIERS` | 1,000 / 20,000 / 200,000 | per owner |
| `MAX_DOC_LINES` | 500 | lines per PR/PO/demand order |
| `MAX_SCHEDULES_PER_LINE` | 100 | |
| `MAX_POSTING_LINES` | 500 | lines per posting |
| `MAX_WO_COMPONENTS` | 4,000 | per WO |
| `MAX_OPEN_DEMAND_LINES` / `MAX_OPEN_WORK_ORDERS` / `MAX_OPEN_SCHEDULES` | 20,000 / 20,000 / 100,000 | MRP input bounds (422 `MRP_TOO_LARGE`) |
| `MRP_MAX_REQUIREMENTS` | 2,000,000 | requirement nodes in one run (abort, 422 `MRP_TOO_LARGE`) |
| `MRP_RUNS_KEPT` / `MRP_PINNED_MAX` | 10 / 10 | unpinned runs kept per owner (oldest deleted on a new run) / pinned runs |
| `MRP_MAX_EXCEPTIONS_STORED` | 50,000 | beyond: lowest severity dropped first, counts stay complete, run `summary.exceptions_truncated` |
| `MRP_STALE_RUNNING_MINUTES` | 10 | a `running` row older than this is marked `failed` by the next run request |
| `MRP_MAX_EXTRA_DEMAND` / `MRP_MAX_OVERRIDES` | 200 / 1,000 | what-if inputs |
| `MRP_LIMITING_PATH_MAX` | 10 | steps in a demand's limiting path |
| `PEGGING_MAX_ROWS` | 2,000 | rows in one pegging response (truncated flag) |
| `COMPARE_MAX_ROWS` | 500 | changed rows per compare section |
| `INV_MAX_BACKDATE_DAYS` | 31 | posting `txn_date` not older than this, never in the future (422 `INV_BACKDATE_LIMIT`) |
| `KITTING_CHECK_MAX_WOS` | 500 | |
| `MAX_MEMBERS` | 200 | per workspace |

### 3.11 Health-check additions (Gate 1, master data only)

| # | Code | Sev. | Entity | Condition | Fix |
|---|---|---|---|---|---|
| 44 | `MFG_BUY_NO_SUPPLIER` | info | item | active in-use buy item without an active item-supplier row (MRP uses the item lead time and creates PRs without supplier) | Add a supplier for this part. |
| 45 | `MFG_PREFERRED_SUPPLIER_INACTIVE` | warning | item_supplier | preferred row whose supplier is inactive | Choose another preferred supplier or activate this one. |
| 46 | `MFG_NO_NETTABLE_LOCATION` | warning | plant | no active location of kind `stores`/`line_side` | Add a stores location. |
| 47 | `MFG_PACK_FRACTIONAL` | warning | item_supplier | count-UoM item with non-integer `units_per_purchase_unit` (stored before the rule) | Use a whole number of units per pack. |

Links: `item_supplier` -> `/mfg/purchasing/suppliers/{supplier_id}?item_supplier={id}`; `plant` as M1. The samples
raise none of 44-47 (the `kavach` intended `by_code` set of M1 10.4 stays exactly as pinned).

---

## 4. Inventory ledger

### 4.1 Posting types

`PostingInput` is a discriminated union on `type`. Common fields: `type`, `txn_date: PlanDate | None` (default
plant today; `today - INV_MAX_BACKDATE_DAYS <= txn_date <= today`), `note: Text500`, `reason_code: Code | None`,
`lines: 1..MAX_POSTING_LINES`. Line fields per type (all `qty` are `Qty` unless stated; `lot_code: LotCode | None`):

| `type` | Line fields | Effect | Reason |
|---|---|---|---|
| `receipt_misc` | `item_id, location_id, qty, lot_code, expires_on, supplier_lot, unit_cost` | + on hand | optional |
| `issue_misc` | `item_id, location_id, lot_code, qty` | - available | **required** (e.g. `SCRAP`, `RTV`, `SAMPLE`) |
| `adjust` | `item_id, location_id, lot_code, qty: SignedQty (!= 0), expires_on` | +/- | **required** |
| `count` | `item_id, location_id, lot_code, counted_qty: NonNegQty, expires_on` | sets on hand (delta posted as `adjust`, reason `COUNT`); a counted qty below reserved releases reservations (oldest first; `warnings` `INV_RESERVATION_REDUCED`) | optional |
| `transfer` | `item_id, from_location_id, to_location_id, lot_code, qty` | - available at from, + at to (two transactions); `from != to` (422 `INV_SAME_LOCATION`); destination `last_receipt_on` = source's | optional |
| `po_receipt` | `schedule_id, location_id, qty, lot_code, expires_on, supplier_lot, unit_cost` (`location_id` null -> the receipt-default location, else 422 `INV_LOCATION_REQUIRED`; `unit_cost` default = line price) | + on hand; schedule `received_qty += qty`; PO/line status update (5.3) | - |
| `wo_issue` | `wo_component_id, location_id, lot_code, qty, over_issue: bool = false` | - on hand; consumes this WO's reservation on that balance first; component `issued_qty += qty` | - |
| `wo_return` | `wo_component_id, location_id, lot_code, qty` (`<= issued_qty`) | + on hand; `issued_qty -= qty` | - |
| `wo_receipt` | `wo_id, location_id, qty: NonNegQty, scrap_qty: NonNegQty = 0 (qty + scrap > 0), lot_code, expires_on` | + on hand of the WO item; `qty_completed += qty`, `qty_scrapped += scrap_qty` | - |
| `ship` | `demand_line_id, location_id, lot_code, qty` (`<= open_qty`) | - available; `shipped_qty += qty` | - |

Rules (422 unless stated; `loc` = `["body","lines",i,field]`):
- Lot-controlled item: receipts need `lot_code` (`INV_LOT_REQUIRED`); a new lot is created with `expires_on` given,
  else `txn_date + shelf_life_days` when the item has a shelf life, `received_on = txn_date`. Issues/transfers/ships
  with `lot_code: null` on a lot-controlled item **auto-pick FEFO** (earliest `expires_on`, nulls last, then lot
  code) across that location's lots, producing one transaction per lot (response shows the picks).
- Non-lot item with a `lot_code` -> `INV_LOT_NOT_ALLOWED`.
- Expired lot (`expires_on <= txn_date`) cannot be issued, shipped or transferred except to `quarantine`
  (`INV_LOT_EXPIRED`); lot on hold: same rule (`INV_LOT_ON_HOLD`).
- Insufficient stock -> **409** `INV_INSUFFICIENT_STOCK` `details: {item, location, lot_code, on_hand, reserved,
  available, requested}`; nothing is posted (the whole posting is one transaction).
- `wo_issue` above `required_qty - issued_qty` needs `over_issue: true` (else 422 `WO_OVER_ISSUE`); WO must be
  `released` or `in_progress` (409 `MFG_INVALID_STATE`). The first `wo_issue`/`wo_receipt` moves `released ->
  in_progress`; `qty_completed >= qty` moves to `completed` and releases the WO's remaining reservations.
- `po_receipt`: PO status `open` or `partially_received` (409 `MFG_INVALID_STATE`); `qty <= open_qty x (1 +
  over_receipt_pct/100) + EPS` (409 `PUR_OVER_RECEIPT`, `details: {open_qty, requested, tolerance_pct}`); schedule
  not `closed`.
- `ship`: demand order `open`; `ship` of more than open -> 422 `DEM_OVER_SHIPMENT`.
- Count-UoM quantities integral (`INV_FRACTIONAL_QTY`).

Pure functions (`mfg/inventory.py`): `validate_posting(input, ctx_snapshot) -> list[error dict]`,
`pick_fefo(balances, qty, txn_date) -> list[(balance_key, qty)]`, `plan_posting(input, balances, docs) ->
PostingPlan(transactions, balance_deltas, reservation_deltas, document_deltas, warnings)`. The service only loads,
locks, calls `plan_posting` and applies.

### 4.2 Reversal

`POST /inventory/postings/{id}/reverse {"note": ""}` posts the exact inverse (same type, `reversal_of_id`, today's
`txn_date`), applying the same rules (stock may not go negative, received/issued/shipped/completed quantities are
decremented, statuses re-derived: a fully received PO becomes `partially_received`, a completed WO `in_progress`).
A posting is reversible once (409 `INV_ALREADY_REVERSED`); a reversal is not reversible (409 `MFG_INVALID_STATE`).
Reversal of a `count` reverses its `adjust` delta.

### 4.3 Balances and lots

Balance key = `(item_id, location_id, lot_key)` with `lot_key = lot_code` or `""` (non-lot items). A balance row is
created on the first posting to its key and kept (zero rows are hidden by default in lists: `only_nonzero=true`).
`last_receipt_on` = latest `txn_date` of a positive transaction of type `receipt_misc`, `po_receipt`, `wo_receipt`,
`transfer` (in) or positive `adjust` into that balance.

### 4.4 Reservations

Hard reservations tie stock to a WO component: `(wo_component_id, balance_id, qty)`. `qty_reserved` on the balance
is the sum of its reservations (maintained in the same transaction). Created by `POST /work-orders/{id}/reserve` or
`release {"reserve": true}` (7.3), consumed by `wo_issue`, released by `unreserve`, WO `close`/`cancel`/completion,
and by `count` below reserved. A reservation never exceeds the component's open qty (excess is released on
`PUT` of the WO). Reserved stock is available only to its component (issues of other kinds see `available`).

### 4.5 Concurrency (PostgreSQL)

- Transactional writes do **not** take the plant lock (so a long master-data import never blocks the stores).
  Master-data writes keep the M1 plant lock. A transaction that needs both (import with master + stock sheets)
  takes the plant lock first.
- **Lock order (binding for every service):** (1) plant row (master writes only) -> (2) MRP run row (conversion) ->
  (3) document headers: `mfg_purchase_docs`, then `mfg_demand_orders`, then `mfg_work_orders`, each sorted by id,
  `SELECT ... FOR NO KEY UPDATE` -> (4) document children (schedules, demand lines, WO components) sorted by id,
  `FOR UPDATE` -> (5) number series rows (`FOR UPDATE`) -> (6) lots sorted by `(item_id, lot_code)` -> (7) balances
  sorted by `(item_id, location_id, lot_key)`, `FOR UPDATE` -> (8) reservations.
- Rows that may not exist yet (balance, lot, number series) are created with the M1 savepoint pattern
  (`begin_nested`, insert, on unique violation roll back the savepoint and `SELECT ... FOR UPDATE` again).
- Any posting that changes a document bumps the document header's `row_version` (a purchaser's stale PUT then gets
  412, never overwrites a receipt).
- `lock_timeout` (55P03) -> 409 `MFG_BUSY` (M1). Deadlock (40P01) or serialization failure (40001): the service
  retries the whole transaction once, then 409 `MFG_BUSY`.
- DB backstops: `CHECK (qty_on_hand >= 0)`, `CHECK (qty_reserved >= 0)`, `CHECK (qty_reserved <= qty_on_hand +
  0.000001)` on balances; `CHECK (received_qty >= 0)` on schedules; `CHECK (issued_qty >= 0)` on components.

### 4.6 Idempotency

`POST /inventory/postings`, `POST /purchase-requests/{id}/convert` and `POST /mrp/runs/{id}/planned-orders/convert`
accept `Idempotency-Key` (pattern of `jobs.types.IDEMPOTENCY_KEY_RE`). Postings store `idempotency_key` and
`request_hash` (sha256 of the canonical JSON body); a repeat with the same key and hash returns the original record
with `200` and header `Idempotent-Replay: true`; same key with another body -> 409 `INV_IDEMPOTENCY_CONFLICT`. For
the two convert actions the key is stored on the created documents' audit event and checked the same way (24 h
window).

---

## 5. Purchasing

### 5.1 Status machines (`mfg/purchasing.py`)

PR (`doc_type = "pr"`):

| Action | From | To | Permission | Notes |
|---|---|---|---|---|
| create / PUT | - / `draft`, `rejected` | `draft` | `pr_edit` | |
| `submit` | `draft` | `submitted` | `pr_edit` | `submitted_by/at` |
| `approve` | `submitted` | `approved` | `pr_approve` | a member cannot approve a PR they submitted (409 `PUR_SELF_APPROVAL`); the workspace owner may |
| `reject` | `submitted` | `rejected` | `pr_approve` | body `{"reason": str 1..500}` |
| `revise` | `submitted`, `rejected` | `draft` | `pr_edit` | |
| `cancel` | `draft`, `submitted`, `approved`, `rejected` | `cancelled` | `pr_edit` | lines -> `cancelled` (converted lines stay) |
| `convert` | `approved` | `approved` or `ordered` | `po_edit` | 5.4 |
| DELETE | `draft` with `source != "mrp"` or any `cancelled` | - | `pr_edit` | |

PO (`doc_type = "po"`): `draft --issue--> open --(first receipt)--> partially_received --(all schedules fully
received or closed)--> received --close--> closed`; `close` also from `open`/`partially_received` (short-close: open
schedules become `closed`, open qty stops being supply); `cancel` from `draft`/`open` without receipts; DELETE only
`draft` without receipts. Edits (PUT): `draft`, `open`, `partially_received` (dates and quantities change all the
time in real purchasing): a schedule with receipts cannot be removed (422 `PUR_SCHEDULE_HAS_RECEIPTS`) or reduced
below `received_qty` (422 `PUR_QTY_BELOW_RECEIVED`); a line with receipts cannot be removed or change item.
`received`, `closed`, `cancelled` are read-only (409 `MFG_DOC_READONLY`). Status is re-derived after every posting
and PUT (reversal can move `received` back to `partially_received`).

Wrong-state actions -> 409 `MFG_INVALID_STATE` `details: {status, action, allowed_from: [...]}`.

### 5.2 Dates

`dock_date = confirmed_date or requested_date`; `available_date = dock_date + item.receiving_days` (calendar days);
`overdue = open_qty > EPS and not closed and dock_date < plant today`; `overdue_days = (today - dock_date).days`.

### 5.3 Receipts

Through `po_receipt` postings (4.1). Without an explicit schedule the UI picks schedules of the line in dock-date
order; the API always names `schedule_id`. Line `received_qty` = sum of its schedules; doc status per 5.1.

### 5.4 PR -> PO conversion

`POST /purchase-requests/{id}/convert {"line_ids": [..] | null, "supplier_id": id | null, "number": str | null,
"issue": false}` (If-Match on the PR). Supplier = body -> PR header -> common preferred supplier of all selected
lines' items, else 422 `PUR_SUPPLIER_REQUIRED`. Creates one PO (`draft`, or `open` if `issue`), one PO line per PR
line (same item, schedules copied, price from item-supplier), `source_pr_line_id` set; PR lines -> `converted`; PR
-> `ordered` when no line is `open`. Response `{"pr": PurchaseDocRecord, "po": PurchaseDocRecord}` (201).

### 5.5 What counts as supply in MRP

PR lines with status `open` in PRs `draft`, `submitted`, `approved` (firmed planned PRs are drafts: excluding them
would plan them twice); PO schedules with `open_qty > 0`, not closed, in POs `draft`, `open`, `partially_received`.

---

## 6. Demand orders

Status: `draft --open--> open --close--> closed`; `open` also re-opens `closed`; `cancel` from `draft`/`open` without
shipments; DELETE only `draft`/`cancelled` without shipments. Edits in `draft`/`open`: lines with shipments cannot be
removed (422 `DEM_LINE_HAS_SHIPMENTS`) or go below `shipped_qty` (422 `DEM_QTY_BELOW_SHIPPED`). When every line is
shipped, the order auto-closes. `closed`/`cancelled` read-only (409 `MFG_DOC_READONLY`).

Effective priority of a line = line `priority` or header `priority`. Serial ranges: within one order no two lines of
the same item may overlap (422); across orders overlap is an MRP warning `MRP_DEMAND_SERIAL_OVERLAP`. MRP plans lines
of `open` orders with `open_qty > EPS`.

---

## 7. Work orders

### 7.1 Status flow

| Action | From | To | Permission | Effects |
|---|---|---|---|---|
| create | - | `planned` | `wo_edit` | components generated unless given (7.2) |
| `release` `{"reserve": false}` | `planned` | `released` | `wo_edit` | optional reservation (7.3); `released_at` |
| (first issue/receipt) | `released` | `in_progress` | - | |
| (completed >= qty) | `in_progress` | `completed` | - | reservations released; `completed_at` |
| `complete` `{}` | `released`, `in_progress` | `completed` | `wo_edit` | short-close: remaining open qty no longer supply; reservations released |
| `close` | `completed` | `closed` | `wo_edit` | final |
| `cancel` | `planned`, `released` without issues/receipts | `cancelled` | `wo_edit` | else 409 `WO_HAS_TRANSACTIONS` (return material first) |
| `refresh-components` | `planned` | `planned` | `wo_edit` | regenerate from the effective BOM; components with issues -> 409 |
| PUT | `planned`: all fields; `released`/`in_progress`: qty (>= completed, 422 `WO_QTY_BELOW_COMPLETED`), dates, priority, note, components (required >= issued, 422 `WO_COMPONENT_BELOW_ISSUED`) | | `wo_edit` | `completed`/`closed`/`cancelled` -> 409 `MFG_DOC_READONLY` |
| DELETE | `planned`, `cancelled` without transactions | | `wo_edit` | |

MRP treats WOs `planned`, `released`, `in_progress` as supply of `open_qty` at `due_date`, and their components'
`required - issued` (minus nothing for reservations: reservations are pre-pegged, 8.8) as requirements at
`start_date`.

### 7.2 Components

Generated with `mrp.order_components(ds, item_id, qty, on=max(start_date, today), serial=serial_from)` (8.7): the
effective BOM and primary routing at that date (unit serial context), phantoms blown through, primary lines only,
quantities inflated by scrap and cumulative yield and rounded up for count-UoM components. `bom_id`/`routing_id` are
stored. No effective BOM -> no components and the response `warnings: [{code: "WO_NO_EFFECTIVE_BOM"}]`.

### 7.3 Reservation

`POST /work-orders/{id}/reserve {"component_ids": null}` reserves for each open component `min(open - reserved,
free)` from nettable `stores`/`line_side` balances, FEFO (lot expiry, then `line_side` before `stores`, then location
code), never expired or held lots. Response: the WO record + `reserved: [{component_id, qty, shortage}]`.
`unreserve {"component_ids": null}` releases. Both need `wo_edit`; WO status `planned`, `released`, `in_progress`.

### 7.4 Kitting

`GET /work-orders/{id}/kitting` (live, not MRP): per component `required, issued, open, reserved (this WO), free
(nettable stores/line_side available, not expired/held, all locations), shortage = max(0, open - reserved - free),
locations (top 5 balances with available qty), next_supply` (earliest open PO schedule/PR schedule/WO for the item:
`{type, label, date (available_date / due_date), qty, link}`), and `totals {components, short_components,
kit_complete}`.

`POST /work-orders/kitting-check {"wo_ids": null, "order": "priority", "horizon_days": 14}` simulates kitting in
sequence: WOs (`wo_ids`, else all `released` + `planned` with `start_date <= today + horizon_days`) sorted by
`(priority, start_date, number)` (`order: "start_date"` -> `(start_date, priority, number)`); each takes free stock in
turn (its own reservations first). Returns `rows: [{wo, start_date, priority, status, kit_complete, short_components,
shortages (top 20: {item, shortage, next_supply})}]` and the **component shortage list** `items_short: [{item,
total_shortage, wo_count, first_start_date, next_supply}]` sorted by first start date. Read-only (permission `view`).
Pure core: `workorders.simulate_kitting(wos, balances, supplies, order)`.

---

## 8. MRP engine (`superplanner/mfg/mrp`, WP-E)

### 8.1 What one run answers

For the whole plant, at once: for every open demand line, existing WO, safety stock and their exploded component
needs, **what to make and buy, how many, by when**, which existing POs/PRs/WOs to expedite, defer, reduce or cancel,
which demand lines will be late, by how much and **why** (the limiting path), and the projected stock of every item
over time. Components shared by many products and orders are netted once for the plant.

### 8.2 Contract types (`mrp/model.py`, frozen at E0)

```python
class MrpParams(MfgModel):                      # = POST /mrp/runs body
    label: str = ""                             # 0..100
    note: str = ""                              # Text500
    as_of: PlanDate | None = None               # None = plant today; any other date makes the run "what_if"
    horizon_days: int | None = None             # 7..730; None = plant.planning_horizon_days; demand due > as_of + horizon is excluded
    allocation: Literal["priority", "due_date"] = "priority"
    alternates: Literal["never", "when_short"] = "when_short"
    safety_stock: bool = True
    include_pr_supply: bool = True              # False = what-if "as if open PRs did not exist"
    protect_programs: list[Code] = []           # demand of these programmes ranks before all others (max 20)
    demand_filter: DemandFilter | None = None   # {order_ids: list[EntityId] | None, programs: list[Code] | None,
                                                #  types: list[demand_type] | None}  -> "what_if"
    exclude_demand_line_ids: list[EntityId] = []          # what-if
    extra_demand: list[ExtraDemand] = []                  # what-if: {item_id, qty, due_date, priority=5,
                                                          #  serial_from, serial_to, label}
    supply_date_overrides: list[SupplyDateOverride] = []  # what-if: {schedule_id | wo_id, date} (dock date / due date)
    lead_time_overrides: list[LeadTimeOverride] = []      # what-if: {item_id, lead_time_days}

@dataclass(frozen=True)
class MrpSnapshot:                              # built by repo_m2.load_mrp_snapshot in one REPEATABLE READ transaction
    as_of: date
    dataset: MfgDataset                         # M1 master data + locations, suppliers, item_suppliers
    lots: dict[str, LotRecord]
    balances: list[BalanceSnap]                 # item_id, location_id, kind, lot_id, expires_on, hold, qty_on_hand,
                                                # qty_reserved, last_receipt_on   (only qty_on_hand > EPS)
    reservations: list[ReservationSnap]         # wo_component_id, balance_id, qty
    schedules: list[ScheduleSnap]               # doc_type, doc_id, number, doc_status, line_id, line_no, schedule_id,
                                                # seq, item_id, supplier_id, open_qty, requested_date, confirmed_date
    demand: list[DemandSnap]                    # order_id, number, demand_type, customer, program, line_id, line_no,
                                                # item_id, open_qty, due_date, effective_priority, serial_from, serial_to
    work_orders: list[WoSnap]                   # id, number, status, item_id, open_qty, start_date, due_date, priority,
                                                # serial_from, serial_to, routing_id,
                                                # components: [(component_id, item_id, open_qty, operation_seq)]
    holidays: frozenset[date]                   # plant-scope holiday/shutdown exceptions covering a whole local day

class MrpResult:                                # pure output; persisted by api/mfg/mrp_store.py
    params: MrpParams; as_of: date; horizon_end: date; kind: Literal["live", "what_if"]
    summary: MrpSummary                         # 12.4
    items: list[ItemPlan]                       # one per item with any requirement or supply, sorted by (llc, part_number)
    planned_orders: list[PlannedOrder]          # sorted by planned_no
    exceptions: list[MrpException]              # sorted (8.12)
    demand: list[DemandProjection]              # one per planned demand line + extra demand
    iterations: int                             # 1 or 2 (alternates pass)

@dataclass
class ItemPlan:   item_id, part_number, llc, uom, make_buy, lead_time (LeadTimeInfo), lot (LotInfo),
                  requirements: list[Requirement], supplies: list[Supply], timeline: list[TimelineEvent], stats
@dataclass
class Requirement: node: int, kind: "demand"|"extra_demand"|"safety_stock"|"planned_component"|"wo_component",
                   need_date, qty, rank: tuple, rank_label: str, source: SourceRef, segment: SerialRange|None,
                   pegs: list[Peg], satisfied_date: date | None, late_days: int
@dataclass
class Supply:      node: int, kind: "stock"|"inspection"|"po"|"pr"|"wo"|"planned", qty, avail_date,
                   projected_date, expires_on, ref: SourceRef, pegged_qty, component_nodes: list[int] (make supplies),
                   planned_no: int | None
@dataclass
class Peg:         supply_item_id, supply_node, requirement_item_id, requirement_node, qty, late_days
```

Node numbers are unique within `(run, item)`; a node is addressed as `(item_id, node)`. A `planned_component` or
`wo_component` requirement's `source` points at its parent supply `(parent_item_id, supply_node)`, which is how
pegging walks up; a make supply's `component_nodes` point down.

### 8.3 Inputs -> requirements and supplies

**Requirements** (gross):
1. Demand lines of `open` orders, `open_qty > EPS`, `due_date <= horizon_end` (later ones are counted in
   `MRP_DEMAND_OUTSIDE_HORIZON` info), after `demand_filter` / `exclude_demand_line_ids`; past-due lines included.
   `need_date = due_date`. Plus `extra_demand` (what-if).
2. Safety stock: one requirement per item with `safety_stock > 0` (if `params.safety_stock`), `need_date = as_of`,
   lowest rank (8.8). Its residual is planned at the earliest feasible date and never reported late (8.6).
3. Existing WO components (`open_qty > EPS`), `need_date = wo.start_date`, rank inherited from the WO's pegs (8.8).
4. Planned-order components, generated during the run (8.7).

**Supplies** (existing):
1. Stock: one supply per nettable balance (3.2) with `qty_on_hand > EPS`; lots on hold excluded; lots with
   `expires_on <= as_of` excluded (`MRP_EXPIRED_STOCK`); `avail_date = as_of` (`inspection`: `max(as_of,
   last_receipt_on + receiving_days)`); reserved quantity split off as a separate supply bound to its reservation.
2. PO and PR schedules (5.5): `avail_date = max(dock_date', as_of) + receiving_days` where `dock_date'` is the
   override date if given, else 5.2. Past-due schedules are assumed to arrive today (`MRP_PAST_DUE_SUPPLY`).
3. WOs `planned`/`released`/`in_progress`: `open_qty` at `avail_date = max(due_date', as_of)` (override date if given).

### 8.4 Low-level codes

Graph = edges `parent -> child` of every **released** BOM whose effectivity window intersects `[as_of, horizon_end +
max lead time]` (generic and serial-specific; phantoms included, they are expanded in place) plus every existing WO
component edge `(wo.item -> component.item)`. `llc(item)` = longest path from any root (iterative DP over a
topological order; M1 guarantees no cycles in BOMs; a cycle introduced only through WO components is broken at the
WO edge and reported `MRP_WO_COMPONENT_CYCLE` warning, that WO's components are still requirements but processed at
the child's own level). Items are processed level by level, within a level by `part_number` (determinism). Every
requirement of an item is known before the item is processed because all its parents have smaller llc.

### 8.5 Calendars and lead times

`WorkCalendar(workdays=plant.mrp_workdays, holidays=snapshot.holidays)` (`mfg/workdays.py`, WP-A):
- `workday_add(d, n)`: `n = 0` -> `d` if working else the next working day; `n > 0` -> the n-th working day after `d`.
- `workday_sub(d, n)`: `n = 0` -> `d` if working else the previous working day; `n > 0` -> the n-th working day
  before `d`. Semantics: an order with lead time n started on `workday_sub(due, n)` works on n working days and is
  available at the start of `due`.

**Purchase lead time** (calendar days): `lead_time_overrides` -> item-supplier source (3.3) -> supplier -> item
`lead_time_days`. For a planned buy order with need date `N`: `dock = N - receiving_days`, `order_date (start) =
dock - lead_time`. Earliest new availability: `as_of + lead_time + receiving_days`.

**Manufacturing lead time** (working days), `mrp.manufacturing_lead_days(ds, item_id, qty, on, serial, day_minutes)`:
`lead_time_overrides` -> item `lead_time_days` (fixed, working days) -> primary effective routing at `on`:
```
inputs = routing.lot_inputs(ops, qty, count_uom)                    # M1 4.4 (yield-inflated per operation)
best_k = max speed_factor of the active eligible lines of op k's group (1.0 if none)
minutes = sum_k (queue_k + setup_k + run_k * loads(op_k, inputs_k) / best_k + move_k + wait_k)
days = ceil(minutes / day_minutes - 1e-9)                           # 0 when minutes == 0
```
This is an infinite-capacity planning approximation (one line per operation, no overlap); M3 replaces it with the
finite schedule. Make items without a routing (not possible for in-use items after Gate 1) get 0.

### 8.6 Lot sizing and rounding (the binding rounding decision)

Residual net requirements of an item (8.8 step 4) are sorted by `(need_date, rank)` and grouped by **segment**
(8.7): residuals of different non-null segments are never combined.

1. **Grouping by rule**: `lot_for_lot` - one order per distinct need date; `period` - one order for all residuals
   with need date in `[d, d + lot_period_days)`, `d` = first need date of the group; `fixed` - per residual, the
   smallest `k x fixed_lot_qty` covering the still uncovered quantity.
2. `q = max(q, MOQ)` (effective MOQ, 3.3).
3. `if multiple > 0: q = ceil(q / multiple - 1e-9) x multiple`.
4. Buy items with pack `p > 1`: `q = ceil(q / p - 1e-9) x p`.
5. Count UoM: `q = ceil(q - 1e-9)`; others `round(q, 6)`.

The surplus of an order (q minus the residuals it was formed for) is a supply available from the order's
availability date and is used by later residuals of the same segment before a new order is formed (pegged like any
supply). Planned order dates: make `due = need_date`, `start = workday_sub(due, manufacturing_lead_days(q, on =
max(need_date, as_of)))`; buy as 8.5. **Safety-stock residuals** get `need_date = max(as_of, earliest new
availability)` so they are never past due.

**Per-order component rounding** (8.7): dependent requirements of each order are rounded up to whole units for
count-UoM children; the explosion itself stays continuous (M1 4.4). Example (T-M4): M1 T-Q1 gives 429.2026 per 100
-> the planned WO of 100 requires **430**. Stored document quantities of count-UoM items are integers.

### 8.7 Explosion of an order (`mrp.order_components`, shared with WO creation)

```python
def order_components(ds: MfgDataset, item_id: str, qty: float, *, on: date, serial: int | None,
                     directives: Mapping[tuple[str, str], float] | None = None, order_key: str | None = None
                     ) -> OrderExplosion   # bom_id, routing_id, components: [ComponentNeed(item_id, qty, bom_line_id,
                                           #   find_number, operation_seq, alt_group, substitute_for)], warnings
```
- BOM = `effective_bom(ds, item, on, serial)`; routing = `primary_routing(ds, item, on, serial)` (M1 4.1); `on =
  max(order start, as_of)`.
- Per primary line: `need = qty / Y_k x qty_per x (1 + scrap_pct/100)` converted to the child UoM (M1 4.4); phantom
  children are expanded recursively in place (their lines' quantities multiplied, `Y` of the phantom = 1, the
  phantom's own effective BOM at the same `on`/`serial`); then count-UoM children `ceil(need - 1e-9)`.
- Same child on several lines: one `ComponentNeed` per line (kits keep positions); MRP sums them per child for the
  order (one requirement per (order, child)).
- `directives[(order_key, alt_group)] = primary-equivalent qty` moves that part of the primary's need to alternates
  in priority order: alternate need = moved qty x `alt.qty_per / primary.qty_per` x `(1 + alt.scrap)/(1 +
  primary.scrap)`, UoM-converted, rounded per child (8.9).

**Unit-serial context and segments.** A demand line with a serial range gives its requirement `segment =
(serial_from, serial_to)`. A planned make order of a **serialized** item keeps the segment of the residuals it covers
and passes it to its component requirements; buy items and non-serialized make items drop the segment (their
requirements combine freely). Before lot sizing, a segmented residual of item X is split at the serial boundaries of
X's serial-specific released BOMs/routings so that each piece selects one document set (`serial = piece.from`);
quantities split proportionally to range length (`qty x len(piece)/len(range)`, count UoM rounded so the pieces sum
to the original). Thus an ECO "effective from unit 126" splits a 121-135 order into 121-125 and 126-135 (T-M8), and
orders for different loco batches of a serialized product are never merged.

### 8.8 Netting and allocation (`mrp/netting.py`)

For each item, in llc order:

1. **Rank** of a requirement: `rank = (protected ? 0 : 1, effective_priority, demand due_date, order number,
   line_no)` from the demand line it ultimately serves; a dependent requirement takes the **best** (minimum) rank
   of the demands pegged to its parent order; safety stock `(2, 9, max_date, "", 0)`. `rank_label` e.g. `"P1 DO-KV-004/10"`.
2. **Reserved supply first**: each reservation supply is pegged to its WO-component requirement (excess over the
   requirement becomes free stock; `MRP_RESERVATION_EXCESS` info).
3. **Order of requirements** (`allocation`): `protect_until = earliest new availability` (8.5; make: `workday_add(as_of,
   manufacturing_lead_days(1))`). `priority`: requirements with `need_date < protect_until` first, by `(rank,
   need_date, node)`, then the rest by `(need_date, rank, node)`. `due_date`: all by `(need_date, rank, node)`.
4. **Allocation** of each requirement `r` (quantity `q`) from existing supplies with remaining quantity:
   - phase 1: supplies with `avail_date <= r.need_date` and (`expires_on is None or expires_on > r.need_date`),
     ordered by `(avail_date, expires_on or max, kind order stock < inspection < po < pr < wo, node)`; take greedily.
   - phase 2 (still short): supplies with `r.need_date < avail_date < protect_until` (existing supply that comes
     sooner than any new order could), same order; pegged **late** (`late_days = avail_date - need_date`).
   - the remainder is a **residual** -> lot sizing (8.6) creates/extends planned orders; residuals are pegged to
     planned orders (late if the planned order starts in the past, 8.10).
5. Make planned orders are exploded (8.7) into requirements on children, with `need_date = order start`.

Every peg records `qty` and `late_days`; a requirement is fully pegged when the loop ends (P7, asserted).

### 8.9 Alternates "when short" (deterministic second pass)

After pass 1, for every `planned_component` requirement on a **primary** component of an alternate group whose
coverage is late (`satisfied_date > need_date`), in rank order: for each alternate (priority order) compute its **free
existing supply** = unpegged remaining quantity of existing supplies with `avail_date <= need_date`, not expired,
minus what earlier directives took; take `min(late qty converted, free)`. Record directive `(order_key, alt_group) +=
primary-equivalent qty`. If any directive exists, run pass 2 with the directives (8.7). Order keys are `"<item_id>:
<segment>:<need_date>:<index>"`; levels above the alternates are identical in both passes, so keys are stable.
Alternates are never ordered new (only free existing stock/receipts are used) and existing WOs' components are never
substituted automatically (planners edit WO components). Each directive produces `MRP_ALTERNATE_USED`. `iterations
= 2` when pass 2 ran.

### 8.10 Forward pass: projected dates and the limiting path (`mrp/forward.py`)

Bottom-up (highest llc first), every supply gets `projected_date`:
- stock/inspection: `avail_date`; PO/PR schedule: `avail_date` (8.3); planned buy: `need_date` if `start >= as_of`,
  else `as_of + lead_time + receiving_days`.
- make supply (existing WO or planned): `comp_ready = max(satisfied_date of its component requirements)` (none ->
  `-inf`); `ready = max(start_date, as_of, comp_ready)`; `projected = due_date if ready == start_date else
  max(due_date, workday_add(ready, manufacturing_lead_days(open_qty)))`.
- requirement `satisfied_date = max(projected_date of its pegged supplies)`; `late_days = max(0, satisfied_date -
  need_date)` (calendar days).
- demand projection: `projected_date = satisfied_date`, `status = "late"` if `late_days > 0`, `"past_due"` if
  `due_date < as_of`, else `"on_time"`.
- **limiting path** of a late demand: from the demand requirement follow the peg with the latest projected supply; at
  a make supply, if `comp_ready` decided `ready`, follow its component requirement with the latest `satisfied_date`,
  else stop with reason `lead_time` (or `start_in_past`); at a buy/existing supply stop with reason `supply_date`.
  At most `MRP_LIMITING_PATH_MAX` steps: `[{item, supply_label, date, reason}]`, e.g. `KV-TPU-1000 (final
  assembly, 16 working days) <- KV-VCU-2000 <- KV-PCB-CPU <- KV-IC-FPGA-V1: PO-KV-0101/10/2 available 7 Jan 2027`.

Backward dates (`need_date`, `start_date`) are what the plan *requires*; projected dates are what the data makes
*possible*. Both are shown; exceptions compare them.

### 8.11 Planned orders

`PlannedOrder`: `planned_no` (1.. in creation order), `kind` (`make`|`buy`), `item_id`, `qty`, `need_date`,
`start_date` (make start / buy order date), `dock_date` (buy), `projected_start = max(start_date, as_of)`,
`projected_due`, `late_days`, `release_status` (`start_in_past` if `start < as_of`; `release_now` if `start <= as_of
+ release_window_days`; else `later`), `supplier_id` (buy, 3.3), `segment`, `bom_id`, `routing_id`, `lot_note`
(e.g. `"lot-for-lot; MOQ 5,000; multiple 5,000"`), `peg_summary` (top 5 demand lines by pegged qty: `{demand_line_id,
label, qty}`), `order_key`. Phantoms never get planned orders.

### 8.12 Exceptions (`mrp/exceptions.py`; codes stable, wording may improve)

`MrpException`: `code, severity ("critical"|"warning"|"info"), item_id, subject {type, id, label}, demand_line_id,
date, qty, days, message, action, suggested {date?, qty?}, related [{type, id, label}]`; the API adds `link` (14.3).
Sort: severity, code (table order), date, item part number, subject label.

| # | Code | Sev. | Subject | Condition | Message (example) / action |
|---|---|---|---|---|---|
| 1 | `MRP_DEMAND_LATE` | critical | demand_line | projected after due | "DO-KV-004/10: 2 x KV-TPU-1000 due 20 Nov 2026 is projected for 18 Dec 2026 (28 days late). Limiting: KV-TPU-1000 needs 16 working days; KV-IC-FPGA-V1 from PO-KV-0101/10/1 available 24 Nov." / "Expedite the parts on the limiting path, or agree a new date." |
| 2 | `MRP_DEMAND_PAST_DUE` | critical | demand_line | due < as_of, open qty | "... was due 15 Oct 2026, 40 open." / "Ship from stock or re-date the line." |
| 3 | `MRP_SHORTAGE` | warning | item | any requirement of the item is covered late (one per item) | "KV-MOD-GSM short 12 from 1 Jan 2027 (first need), for DO-KV-002/10; earliest new supply 3 May 2027." / "Expedite open orders or use an alternate." |
| 4 | `MRP_START_IN_PAST` | warning | planned_order | `start_date < as_of` | "Planned PR P-412 for 5,000 KV-CAP-0402-100N should have been ordered 12 days ago (needed 20 Nov)." / "Release now; expect 12 days delay." |
| 5 | `MRP_EXPEDITE` | warning | po_schedule / pr_schedule / work_order | `projected/avail date > earliest pegged need date` | "PO-KV-0101 line 10 schedule 2 (30 x KV-IC-FPGA-V1, confirmed 5 Jan 2027) is needed by 12 Dec 2026." / suggested date = need - receiving |
| 6 | `MRP_PAST_DUE_SUPPLY` | warning | po_schedule / pr_schedule | dock < as_of, open | "PO-KV-0102/10/1: 200 due 21 Oct 2026, not received." / "Chase the supplier or re-date." |
| 7 | `MRP_WO_LATE` | warning | work_order | projected > due | "WO-KV-0001 projected 13 Nov, due 9 Nov (components: KV-IC-...)" |
| 8 | `MRP_EXPIRED_STOCK` | warning | lot | nettable lot expired at as_of | "Lot L-2611 of KV-COAT-UR (1.5 L) expired 30 Oct 2026." / "Move to quarantine." |
| 9 | `MRP_EXPIRING_STOCK` | warning | lot | unpegged quantity of a lot expiring inside the horizon | "1.2 L of lot L-2611 expires 20 Nov unused." |
| 10 | `MRP_CANCEL` | warning | po_schedule / pr_schedule / work_order (planned status only) | nothing pegged | "Not needed in the horizon." / "Cancel or push out." |
| 11 | `MRP_REDUCE` | info | po_schedule / pr_schedule | pegged < open and the rounded pegged qty (MOQ/multiple/pack) < open | suggested qty |
| 12 | `MRP_DEFER` | info | po_schedule / pr_schedule / work_order | earliest need > avail + defer tolerance | suggested date = earliest need - receiving |
| 13 | `MRP_RELEASE_NOW` | info | planned_order | `release_status == release_now` | "Order by 6 Nov." |
| 14 | `MRP_BELOW_SAFETY_STOCK` | info | item | safety-stock requirement not covered by existing supply | |
| 15 | `MRP_ALTERNATE_USED` | info | planned_order | directive applied | "300 of KV-CAP-1206-10U (alternate) instead of KV-CAP-1206-10U-A for P-77 (KV-PCB-DCC), primary late." |
| 16 | `MRP_NO_SUPPLIER` | info | item | planned buy without supplier | |
| 17 | `MRP_MERGE_INTO_PR` | info | planned_order | a `draft` PR line for the same item and supplier exists with dock within `defer_tolerance` of the planned dock | "Add to PR-000031 instead of a new PR." (convert offers `add_to_pr_id`) |
| 18 | `MRP_DEMAND_SERIAL_OVERLAP` | warning | demand_line | serial ranges of open lines of the same item overlap across orders | |
| 19 | `MRP_RESERVATION_EXCESS` | info | work_order | reservation > component open qty | |
| 20 | `MRP_WO_COMPONENT_CYCLE` | warning | work_order | 8.4 | |
| 21 | `MRP_DEMAND_OUTSIDE_HORIZON` | info | plant | open lines due after horizon end (one exception with the count) | |

**Preflight (blocking, 422 `MRP_PREFLIGHT_FAILED`, `details.issues` in health-issue shape):** `MRP_DEMAND_ITEM_INACTIVE`
(open demand line on an inactive item), `MRP_DEMAND_ITEM_PHANTOM`, `MRP_OVERRIDE_UNKNOWN` (override/extra demand
references something that does not exist), plus Gate 1 (`run_health_check(ds, as_of, horizon).ok`, else 422
`MFG_DATA_HEALTH_FAILED` with the report, M1 7.1).

### 8.13 Views (`mrp/views.py`, pure over stored results)

- `item_timeline(plan)`: events by date: opening `on_hand` (nettable now), each requirement (-), each existing supply
  (+), each planned supply (+); two running balances: `balance_existing` (without planned orders: shows the
  shortage) and `balance_planned`.
- `bucketize(timeline, bucket: "day"|"week"|"month", start, end)`: weeks are ISO weeks starting Monday, months
  calendar months; per bucket `gross, existing_supply, planned, balance_existing_end, balance_planned_end, short`.
- `pegging(store, item_id, node, kind, direction, max_depth)`: up = supply -> pegged requirements -> parent supply ->
  ... -> demand; down = requirement -> pegged supplies -> (make) component requirements -> ... Rows depth-first,
  `PEGGING_MAX_ROWS`.
- `compare(a, b)`: 12.4 compare shape.

### 8.14 Runs, staleness, retention, conversion

- `POST /mrp/runs` (permission `mrp_run`): insert run `running` (partial unique index: one `running` per owner ->
  409 `MRP_RUN_IN_PROGRESS`; a `running` row older than `MRP_STALE_RUNNING_MINUTES` is first set `failed`), commit;
  load snapshot (REPEATABLE READ, read-only); Gate 1 + preflight; `run_mrp` in the threadpool; write results in one
  transaction (`add_all` per table, flush per table); status `completed`, `summary`; delete unpinned runs beyond
  `MRP_RUNS_KEPT`. Errors: health/preflight -> 422 and the run row is deleted; unexpected -> run `failed` with a
  generic message (logged), 500.
- `kind = "what_if"` iff `as_of` given and != today, or any of `demand_filter`, `exclude_demand_line_ids`,
  `extra_demand`, `supply_date_overrides`, `lead_time_overrides`, `include_pr_supply = false`.
- **Staleness** (computed on every GET of a run): `master_changed` = plant `data_version` differs; `transactions_changed`
  = `max(mfg_inv_transactions.seq)` or `max(updated_at)` of purchase docs/demand orders/work orders differs from the
  stored `inputs_token`. Shown as a banner; never blocks reading.
- **Conversion** (`POST /mrp/runs/{id}/planned-orders/convert`, permission `mrp_run`): only the **latest completed
  `live` run** (409 `MRP_RUN_NOT_LATEST`); each order converted once (409 `MRP_ALREADY_CONVERTED`, `details.ids`);
  all-or-nothing. Lock order: run row -> planned order rows (`FOR UPDATE`, sorted) -> new documents -> series.
  `mode: "firm"` -> make: WO `planned`; buy: PR `draft`. `mode: "release"` -> make: WO `released` (+ `reserve`
  option); buy: PR `submitted`. Per-order overrides `qty`, `start_date`/`need_date`, `supplier_id`. Buy orders are
  grouped into one PR per supplier (`pr_grouping: "per_supplier"`, default) or one PR per order (`"per_order"`);
  `add_to_pr_id` appends to an existing `draft` PR (same supplier or none, else 422). WO: `bom_id`/`routing_id`/
  serial range/components from the planned order (`order_components` again at the same date and serial). PR line:
  one schedule with `requested_date = dock_date`. Created documents carry `source = "mrp"`, `source_run_no`,
  `source_planned_no`; planned order rows record `converted_type/id/number/at/by`. Response 201 (12.4).
- Re-running after conversion shows the new WOs/PRs as existing supply; nothing is planned twice (acceptance 18 #6).

### 8.15 Test vectors (pure tests MUST include all; as_of Mon 2026-11-02, workdays Mon-Sat, no holidays unless stated)

| # | Setup | Expected |
|---|---|---|
| T-M1 | buy C: LT 10, receiving 2, lot-for-lot. Stock 100. PO schedule 50 dock 11-10. Requirements 120 @11-15, 80 @11-20 | pegs: R1 <- stock 100 + PO 20; R2 <- PO 30 + planned PR 50 (need 11-20, dock 11-18, order date 11-08, `release_now`); no expedite |
| T-M2 | T-M1 with MOQ 5,000, multiple 5,000 | planned PR 5,000; surplus 4,950 unpegged |
| T-M3 | buy D: LT 60. PO 200 dock 12-01. Requirement 150 @11-20 | phase-2 peg late 11 days; `MRP_EXPEDITE` to 11-20; `MRP_REDUCE` to 150; `MRP_SHORTAGE` D |
| T-M4 | M1 T-Q1 product, demand 100 P (lead time fixed 0) | planned WO 100; component requirement C = 430 |
| T-M5 | make P ops: 10 setup 60 run 3/unit; 20 run 1.2/unit wait 1440; yields 100; speed 1; day 480. Demand 100 due Fri 11-20 | MLT 4 days, start Mon 11-16; with plant holiday Tue 11-17: start Sat 11-14 |
| T-M6 | buy X: LT 90, stock 10. D1 prio 1 due 11-30 qty 8; D2 prio 5 due 11-20 qty 8 | `priority`: D1 <- 8; D2 <- 2 + planned 6 (`start_in_past`), D2 projected 2027-01-31, late 72. `due_date`: D2 <- 8; D1 late 62 |
| T-M7 | P (fixed LT 2) demand 300 due 11-20 -> WO start 11-18; BOM alt group: A1 (primary, qty 1, stock 0, LT 120), A2 (alt, qty 1, stock 500) | iterations 2; A2 requirement 300 from stock; A1 none; demand on time; `MRP_ALTERNATE_USED`. With A2 qty_per 2: directive 250, A2 500, A1 residual 50 late |
| T-M8 | serialized E: BOM v1 generic (child K1 x1), v2 serial 106..10^9 (child K2 x1); demand 10 E serials 101-110 | 2 planned WOs 101-105 (5, v1) and 106-110 (5, v2); K1 req 5, K2 req 5 |
| T-M9 | lot-controlled G: lot L1 100 expires 11-15; requirement 50 @11-20 | L1 not used; planned order 50; `MRP_EXPIRING_STOCK` L1 100. Requirement @11-10 instead: uses L1 |
| T-M10 | SS 20, stock 15, LT 5, no other requirement | planned 5 with need 11-07 (as_of + 5), not late; `MRP_BELOW_SAFETY_STOCK` |
| T-M11 | stock 50; WO1 component 40 @11-05 reserved 40; WO2 component 30 @11-04 | WO2 <- 10 free + residual 20 |
| T-M12 | buy J: PO A 100 dock 11-10, requirement 100 @12-20 (tolerance 7); PO B 50 dock 11-12 | `MRP_DEFER` A to 12-20; `MRP_CANCEL` B |
| T-M13 | make P fixed LT 5; demand 10 due Fri 12-04 -> start Sat 11-28; component C (LT 60) only on PO dock 12-03 | C peg late 5 days; P projected 12-09; demand late 5; limiting path P <- C (PO, `supply_date`) |
| T-M14 | determinism: Kavach sample run twice and under two `PYTHONHASHSEED`s | byte-identical canonical JSON of `MrpResult` |
| T-M15 | full pegging invariant on Kavach + randomized cases (seeded) | every requirement's peg sum == qty; every supply's pegged <= qty; planned qty >= residuals |

---
## 9. Database schema (`api/mfg/db_models_m2.py`, migration `0004_mfg_m2`)

### 9.1 Conventions

M1 6.1 applies (owned tables, `new_id` ids, ORM writes only, named constraints <= 63 chars, an `owner_id`-led index
on every table, an index led by every FK column, literal `op.create_table` in the frozen migration,
`down_revision = "0003_mfg"`, `HEAD = "0004_mfg_m2"`, `compare_metadata` empty). Additions:
- **Run result tables are snapshots**: `mfg_mrp_*` rows store `item_id`, `supplier_id`, `bom_id`... as plain strings
  **without FKs** (plus denormalised `part_number`), so deleting master data never touches or blocks old runs; only
  `run_id` is a FK (`ON DELETE CASCADE`).
- Self references use `ON DELETE SET NULL` (`reversal_of_id`, `source_pr_line_id`) so reset's bulk deletes never
  trip a RESTRICT inside one statement.
- `mfg_inv_transactions.seq` is `BigInteger` with `sa.Identity(always=True)` (global order, staleness token); ids stay
  `new_id("txn_")`.
- Partial unique indexes (`postgresql_where`) are declared identically in the model and the migration.
- New NOT NULL columns on existing tables are added with a `server_default` and the default is dropped in the same
  migration (no server defaults remain, M1 rule).

### 9.2 Columns added to M1 tables

| Table | Column | Migration default (then dropped) |
|---|---|---|
| `mfg_items` | `external_ref S64 N`, `standard_cost Dbl N`, `lot_controlled Bool`, `lot_period_days Int N` | `lot_controlled false` |
| `mfg_plant` | `mrp_workdays JSON`, `mrp_day_minutes Dbl`, `mrp_defer_tolerance_days Int`, `mrp_release_window_days Int`, `over_receipt_pct Dbl` | `'["mon","tue","wed","thu","fri","sat"]'`, 480, 7, 7, 0 |

Index: `uq_mfg_items_owner_extref (owner_id, external_ref) WHERE external_ref IS NOT NULL`.

### 9.3 New tables (besides id, owner_id; `E` = editable: `row_version`, `created_at`, `updated_at`)

| # | Table | Columns | Constraints / indexes |
|---|---|---|---|
| 1 | `mfg_locations` E | code S32, name S200, kind S16, receipt_default Bool, active Bool, external_ref S64 N, note S500 | `uq_mfg_locations_code (owner_id, code)`; partial uq extref |
| 2 | `mfg_suppliers` E | code S32, name S200, lead_time_days Int N, currency S8, contact_name S200, email S200, phone S50, address S500, active Bool, external_ref S64 N, note S500 | `uq_mfg_suppliers_code (owner_id, code)`; partial uq extref |
| 3 | `mfg_item_suppliers` E | item_id FK items CASCADE, supplier_id FK suppliers CASCADE, supplier_part_number S64, lead_time_days Int N, min_order_qty Dbl, order_multiple Dbl, purchase_unit S32 N, units_per_purchase_unit Dbl, unit_price Dbl N, currency S8, preferred Bool, active Bool, note S500 | `uq_mfg_item_suppliers_key (owner_id, item_id, supplier_id)`; ix item, ix supplier |
| 4 | `mfg_lots` E | item_id FK items RESTRICT, lot_code S64, expires_on Date N, received_on Date N, supplier_lot S64, hold Bool, note S500 | `uq_mfg_lots_key (owner_id, item_id, lot_code)`; ix (owner_id, expires_on) |
| 5 | `mfg_purchase_docs` E | doc_type S2, number S32, status S24, supplier_id FK suppliers RESTRICT N, currency S8, order_date Date N, note S500, source S8, source_run_no Int N, submitted_at DT N, submitted_by S64 N, approved_at DT N, approved_by S64 N, rejected_reason S500, external_ref S64 N, idempotency_key S128 N | `uq_mfg_purchase_docs_number (owner_id, doc_type, number)`; ix (owner_id, doc_type, status); ix supplier; partial uq (owner_id, doc_type, external_ref) |
| 6 | `mfg_purchase_lines` E | doc_id FK docs CASCADE, line_no Int, item_id FK items RESTRICT, unit_price Dbl N, status S16, source_pr_line_id FK purchase_lines SET NULL N, note S500 | `uq_mfg_purchase_lines_no (doc_id, line_no)`; ix item; ix source_pr_line; ix owner |
| 7 | `mfg_purchase_schedules` E | line_id FK lines CASCADE, seq Int, requested_date Date, confirmed_date Date N, qty Dbl, received_qty Dbl, closed Bool | `uq_mfg_purchase_schedules_seq (line_id, seq)`; ix (owner_id, requested_date); CHECK `received_qty >= 0` |
| 8 | `mfg_demand_orders` E | number S32, demand_type S16, customer S200, program S32 N, priority Int, status S16, note S500, external_ref S64 N | `uq_mfg_demand_orders_number (owner_id, number)`; ix (owner_id, status); partial uq extref |
| 9 | `mfg_demand_lines` E | order_id FK orders CASCADE, line_no Int, item_id FK items RESTRICT, qty Dbl, due_date Date, shipped_qty Dbl, serial_from BigInt N, serial_to BigInt N, priority Int N, note S500 | `uq_mfg_demand_lines_no (order_id, line_no)`; ix item; ix (owner_id, due_date) |
| 10 | `mfg_work_orders` E | number S32, item_id FK items RESTRICT, qty Dbl, qty_completed Dbl, qty_scrapped Dbl, start_date Date, due_date Date, status S16, priority Int, serial_from BigInt N, serial_to BigInt N, bom_id FK boms SET NULL N, routing_id FK routings SET NULL N, demand_line_id FK demand_lines SET NULL N, source S8, source_run_no Int N, source_planned_no Int N, released_at DT N, completed_at DT N, closed_at DT N, note S500, external_ref S64 N | `uq_mfg_work_orders_number (owner_id, number)`; ix (owner_id, status); ix item; ix bom; ix routing; ix demand_line; partial uq extref |
| 11 | `mfg_wo_components` E | wo_id FK work_orders CASCADE, item_id FK items RESTRICT, required_qty Dbl, issued_qty Dbl, operation_seq Int N, find_number S16 N, alt_group S16 N, bom_line_id S64 N (no FK), note S500 | ix wo; ix item; ix owner; CHECK `issued_qty >= 0` |
| 12 | `mfg_inv_balances` | item_id FK items RESTRICT, location_id FK locations RESTRICT, lot_id FK lots RESTRICT N, lot_key S64, qty_on_hand Dbl, qty_reserved Dbl, last_receipt_on Date N, updated_at DT | `uq_mfg_inv_balances_key (owner_id, item_id, location_id, lot_key)`; ix item; ix location; ix lot; CHECKs 4.5 |
| 13 | `mfg_inv_reservations` | wo_component_id FK wo_components CASCADE, balance_id FK balances RESTRICT, qty Dbl, created_at, updated_at | `uq_mfg_inv_reservations_key (wo_component_id, balance_id)`; ix balance; ix owner |
| 14 | `mfg_inv_postings` | number S32, type S16, txn_date Date, note S500, reason_code S32 N, idempotency_key S128 N, request_hash S64 N, actor_id S64, reversal_of_id FK postings SET NULL N, created_at | `uq_mfg_inv_postings_number (owner_id, number)`; `uq_mfg_inv_postings_idem (owner_id, idempotency_key) WHERE idempotency_key IS NOT NULL`; ix (owner_id, created_at); ix reversal_of |
| 15 | `mfg_inv_transactions` | seq BigInt Identity, posting_id FK postings CASCADE, line_no Int, txn_type S16, txn_date Date, item_id FK items RESTRICT, location_id FK locations RESTRICT, lot_id FK lots RESTRICT N, qty Dbl, balance_after Dbl, unit_cost Dbl N, schedule_id FK schedules RESTRICT N, wo_id FK work_orders RESTRICT N, wo_component_id FK wo_components RESTRICT N, demand_line_id FK demand_lines RESTRICT N, actor_id S64, created_at | `uq_mfg_inv_transactions_seq (seq)`; ix (owner_id, seq); ix (item_id, seq); ix location; ix lot; ix posting; ix schedule; ix wo; ix wo_component; ix demand_line |
| 16 | `mfg_number_series` | kind S8 (`PO`,`PR`,`DO`,`WO`,`TXN`), prefix S16, next_value BigInt | `uq_mfg_number_series_kind (owner_id, kind)` |
| 17 | `mfg_mrp_runs` E | run_no Int, kind S8, status S16, label S100, note S500, pinned Bool, params JSON, as_of Date, horizon_days Int, master_fingerprint S64, data_version Int, inputs_token JSON, started_at DT, finished_at DT N, duration_ms Int N, actor_id S64, summary JSON N, error JSON N | `uq_mfg_mrp_runs_no (owner_id, run_no)`; `uq_mfg_mrp_runs_running (owner_id) WHERE status = 'running'`; ix (owner_id, created_at) |
| 18 | `mfg_mrp_planned_orders` | run_id FK runs CASCADE, planned_no Int, kind S8, item_id S64, part_number S64, supplier_id S64 N, qty Dbl, need_date Date, start_date Date, dock_date Date N, projected_start Date, projected_due Date, late_days Int, release_status S16, segment JSON N, bom_id S64 N, routing_id S64 N, llc Int, lot_note S200, peg_summary JSON, order_key S200, status S16, converted_type S8 N, converted_id S64 N, converted_number S32 N, converted_at DT N, converted_by S64 N | `uq_mfg_mrp_planned_orders_no (run_id, planned_no)`; ix (run_id, kind, start_date); ix (run_id, item_id); ix owner |
| 19 | `mfg_mrp_exceptions` | run_id FK CASCADE, ex_no Int, code S40, severity S8, item_id S64 N, part_number S64 N, demand_line_id S64 N, subject JSON, ex_date Date N, qty Dbl N, days Int N, message S1000, action S500, suggested JSON N, related JSON | ix (run_id, severity, code); ix (run_id, item_id); ix owner |
| 20 | `mfg_mrp_item_results` | run_id FK CASCADE, item_id S64, part_number S64, description S500, make_buy S8, uom S8, llc Int, on_hand Dbl, gross_qty Dbl, existing_supply_qty Dbl, planned_qty Dbl, planned_count Int, first_short_date Date N, short_qty Dbl, late_qty Dbl, min_balance Dbl, exception_count Int, detail JSON | `uq_mfg_mrp_item_results_item (run_id, item_id)`; ix (run_id, part_number); ix owner |
| 21 | `mfg_mrp_demand_results` | run_id FK CASCADE, demand_line_id S64 N, order_id S64 N, order_number S32, line_no Int, extra Bool, item_id S64, part_number S64, qty Dbl, due_date Date, projected_date Date N, late_days Int, priority Int, status S16, program S32 N, segment JSON N, limiting JSON | ix (run_id, late_days); ix (run_id, demand_line_id); ix owner |
| 22 | `mfg_plant_members` E | user_id FK users RESTRICT, roles JSON, active Bool, invited_by S64 | `uq_mfg_plant_members_user (owner_id, user_id)`; ix user_id |

22 new tables (the test asserts this exact table list).

`detail` JSON of `mfg_mrp_item_results` holds the item's requirements, supplies, pegs and timeline in a compact,
versioned internal format (`{"v": 1, ...}`, owned by WP-B `mrp_store.py`); API shapes (12.4) are the contract, not
the storage format.

### 9.4 Model registries, reset, reassign-owner

`db_models_m2.ALL_MFG_MODELS` = M1 `MFG_MODELS` followed by M2 models in FK order (`locations, suppliers,
item_suppliers, lots, purchase_docs, purchase_lines, purchase_schedules, demand_orders, demand_lines, work_orders,
wo_components, inv_balances, inv_reservations, inv_postings, inv_transactions, number_series, mrp_runs,
mrp_planned_orders, mrp_exceptions, mrp_item_results, mrp_demand_results`); `mfg_plant_members` is **not** in it
(`MFG_ACCESS_MODELS`). Reset (`delete_all`) deletes `reversed(ALL_MFG_MODELS)` (memberships survive a data reset;
the owner removes members explicitly). `manage.py reassign-owner` counts every table of `ALL_MFG_MODELS +
MFG_ACCESS_MODELS` for its guard and moves them all.

### 9.5 Repository (`api/mfg/repo_m2.py`, WP-A)

```python
def load_dataset(s) -> MfgDataset                     # M1 loader + 3 tables (<= 22 statements)
def load_mrp_snapshot(s, as_of: date) -> MrpSnapshot  # caller opened REPEATABLE READ; <= 32 statements total, no N+1
def inputs_token(s) -> dict                           # max seq, max updated_at of docs/demand/WOs, data_version (<= 4 statements)
def lock_docs(s, model, ids: list[str]) -> list[Row]  # sorted, FOR NO KEY UPDATE
def lock_children(s, model, ids) -> list[Row]         # sorted, FOR UPDATE
def lock_or_create_lots(s, keys) -> dict              # savepoint pattern
def lock_or_create_balances(s, keys) -> dict          # sorted keys, savepoint pattern
def next_number(s, kind: str, taken: Callable[[str], bool]) -> str   # locks the series row; skips numbers already used
def load_kitting(s, wo_ids) -> KittingInput           # components, reservations, free balances, next supplies (<= 8 statements)
def snapshot_tx(db) -> ContextManager[Session]        # read session; first statement sets REPEATABLE READ READ ONLY
```

---

## 10. Workspaces, roles, permissions, audit

### 10.1 Workspaces

A **workspace** is one owner's plant (all `mfg_*` data of that owner). Every user has their own workspace. The owner
can add other accounts as **members** with roles. Requests to `/api/v1/mfg/**` may send `X-SP-Workspace: <owner user
id>`; absent or equal to the caller -> own workspace (role `owner`). Otherwise the router dependency
`access.mfg_principal` loads the membership in `system_scope()`; active membership -> `bind_owner(owner_id)` (the
central ownership filter then serves the owner's rows, unchanged) and `bind_actor(user_id)`; else 404 `NOT_FOUND`
("Workspace not found") for every mfg endpoint. Scheduling, finance and auth routes never read the header. In
`single_user` mode membership endpoints answer 422 `MBR_UNAVAILABLE`.

`mfg_principal` and `require_perm` must be `async def` dependencies (like `require_user`): a sync dependency runs
in the threadpool, and a contextvar re-bound there would not reach the handler. A test asserts that a member's
request lists the owner's items and that the audit actor is the member.

### 10.2 Roles and permissions

| Permission | owner | planner | purchaser | store_keeper | approver | viewer | Covers |
|---|---|---|---|---|---|---|---|
| `view` | x | x | x | x | x | x | every GET, kitting-check, MRP export |
| `master_edit` | x | x | | | | | M1 master writes (items, BOMs, routings, plant, groups, lines, shifts, exceptions, skills, operators, tooling), locations |
| `supplier_edit` | x | x | x | | | | suppliers, item-suppliers |
| `inventory` | x | | | x | | | postings (all types), reversal, lot PUT |
| `pr_edit` | x | x | x | | | | PR create/PUT/submit/revise/cancel/delete |
| `pr_approve` | x | | | | x | | PR approve/reject |
| `po_edit` | x | | x | | | | PO create/PUT/issue/close/cancel/delete, PR convert |
| `demand_edit` | x | x | | | | | demand orders |
| `wo_edit` | x | x | | | | | WO create/PUT/actions, reserve/unreserve |
| `mrp_run` | x | x | | | | | MRP run/PUT/DELETE/convert |
| `import` | x | x | | | | | imports; commit additionally needs the permission of every sheet kind present (master_edit, supplier_edit, inventory, po_edit/pr_edit, demand_edit, wo_edit) |
| `owner` | x | | | | | | members, reset, sample load |

Members may hold several roles (union). Missing permission -> 403 `MFG_FORBIDDEN` "Your role in this workspace does
not allow this (needs: Store keeper)." `details: {permission, roles_allowed}`. Every mfg route (M1 77 and M2)
declares exactly one permission (`dependencies=[require_perm("...")]`); the access table `MFG_PERMISSIONS` in
`tests/auth/route_table.py` lists all of them and a test asserts route set == table set.
`GET /me` returns `{user_id, workspace_owner_id, workspace_name, is_owner, roles, permissions}` for UI gating.

### 10.3 Audit

`ownership.bind_actor/current_actor` (new); `problem_service.audit` records `actor_id = current_actor() or
current_owner()`. Every M2 write transaction records one audit event (entity `mfg_<kind>`, actions `create|update|
delete|<action name>|post|reverse|run|convert|member_add|member_update|member_remove`, details: ids, numbers, counts,
idempotency key; never quantities lists over 50 entries). Postings additionally carry `actor_id` per transaction
(the ledger is the stock audit trail). The existing static test "every mfg write records audit" covers the new
services.

---

## 11. Import / export (M1 8 pipeline, extended)

New sheets in `bundle.SHEETS` (after the M1 sheets, in this order) and `io/spec.py`; key columns in **bold**:

| Sheet | Kind (permission) | Columns |
|---|---|---|
| `locations` | master (`master_edit`) | **code***, name*, kind*, receipt_default, active, external_ref, note |
| `suppliers` | master (`supplier_edit`) | **code***, name*, lead_time_days, currency, contact_name, email, phone, address, active, external_ref, note |
| `item_suppliers` | master (`supplier_edit`) | **part_number***, **supplier_code***, supplier_part_number, lead_time_days, min_order_qty, order_multiple, purchase_unit, units_per_purchase_unit, unit_price, currency, preferred, active, note |
| `stock` | inventory (`inventory`) | **part_number***, **location_code***, **lot_code**, qty*, expires_on, supplier_lot |
| `purchase_docs` | purchasing (`pr_edit` for pr, `po_edit` for po) | **doc_type*** (`pr`/`po`), **number***, status (create only), supplier_code, currency, order_date, note, external_ref |
| `purchase_lines` | purchasing | **doc_type***, **number***, **line_no***, part_number*, unit_price, note |
| `purchase_schedules` | purchasing | **doc_type***, **number***, **line_no***, **seq***, requested_date*, confirmed_date, qty*, received_qty (create only) |
| `demand_orders` | demand (`demand_edit`) | **number***, demand_type*, customer, program, priority, status (create only), note, external_ref |
| `demand_lines` | demand | **number***, **line_no***, part_number*, qty*, due_date*, serial_from, serial_to, priority, shipped_qty (create only), note |
| `work_orders` | WO (`wo_edit`) | **number***, part_number*, qty*, start_date, due_date*, status (create only: planned/released/in_progress), priority, serial_from, serial_to, qty_completed (create only), note, external_ref |
| `wo_components` | WO | **wo_number***, **part_number***, **find_number**, required_qty*, issued_qty (create only), operation_seq, note |

Semantics:
- Master sheets behave exactly like M1 sheets (plant lock, upsert by key, `unchanged` detection, `data_version`).
- `stock` (option `stock_mode`: `set` default | `add`): `set` makes the balance equal `qty` by posting one `count`
  posting (reason `IMPORT`) for all changed rows; `add` posts one `receipt_misc`. Balances not in the file are
  untouched. A `set` below reserved -> row error `IMP_BELOW_RESERVED`. Lots are created as needed.
- Documents (purchase, demand, WO) upsert by number. `status` and the create-only quantity columns (`received_qty`,
  `shipped_qty`, `qty_completed`, `issued_qty`) apply only when the document is created (opening data migrated from
  an ERP; no stock movement - stock comes from the `stock` sheet). Updating a document in a read-only status ->
  `IMP_READONLY_STATUS`. `replace_children` applies to lines/schedules/components as for BOM lines; children with
  receipts/shipments/issues cannot be removed (`IMP_IN_USE`). WOs without `wo_components` rows get generated
  components (7.2).
- Plan (`plan_import`) takes the M2 dataset (`repo_m2.load_import_dataset`), is pure, and reports row errors with the
  same API rule codes mapped to `IMP_BAD_VALUE` / `IMP_UNKNOWN_REFERENCE` / `IMP_READONLY_STATUS` / `IMP_IN_USE` /
  `IMP_BELOW_RESERVED`.
- Commit takes the plant lock only if master sheets are present, then document and balance locks (4.5 order), one
  transaction, audit with counts.
- Export: `GET /export?format=xlsx|zip&scope=master|transactions|all` (default `master` = M1 behaviour plus the three
  M2 master sheets). `transactions` = stock (current balances with lots), all purchase docs, demand orders, WOs and
  components with their current received/shipped/completed/issued quantities. Round trip (tested): export `all` ->
  import into an empty account -> export `all` -> byte-equal CSV zip. `GET /import-templates` gains `scope`.
- MRP results export: `GET /mrp/runs/{id}/export?format=xlsx|zip` -> sheets `planned_orders`, `exceptions`,
  `demand`, `items` (not importable; for purchasers and reporting).

---

## 12. REST API (`/api/v1/mfg`, `api/mfg/router_m2.py`)

### 12.1 Conventions

M1 9.1 applies (order of checks; plain-string path ids -> 404; If-Match on PUT/DELETE/actions with 428/412; ETag;
pagination `{"items", "total", "limit", "offset"}`; search `q`; UTC `Z` timestamps; plant-local dates). Additions:
the permission dependency runs after authentication and before body validation (so a viewer gets 403 for any
unsafe call regardless of body); workspace resolution runs first (unknown workspace -> 404). Paginated lists here:
balances, transactions, postings, purchase docs, schedule board, demand orders, work orders, MRP items, planned
orders, exceptions, demand results. Default sorts are listed per endpoint. Fixed paths are registered before
parameterised siblings (`/mrp/runs/latest` before `/mrp/runs/{run_id}`, `/work-orders/kitting-check` before
`/work-orders/{wo_id}`).

### 12.2 Error codes (in addition to M1 9.2)

| HTTP | Code | When |
|---|---|---|
| 403 | `MFG_FORBIDDEN` | permission missing (10.2) |
| 404 | `NOT_FOUND` | unknown/foreign id, unknown workspace |
| 409 | `MFG_INVALID_STATE` | action not allowed in the current status (`details.status, action, allowed_from`) |
| 409 | `MFG_DOC_READONLY` | edit of a document in a final status |
| 409 | `MFG_IN_USE` | delete blocked; item UoM change with stock/documents |
| 409 | `MFG_DUPLICATE_KEY` | numbers, codes, external refs, item-supplier pair, member |
| 409 | `MFG_BUSY` | lock timeout, or deadlock/serialization failure after one retry (`Retry-After: 5`) |
| 409 | `INV_INSUFFICIENT_STOCK` | 4.1 |
| 409 | `INV_IDEMPOTENCY_CONFLICT` / `INV_ALREADY_REVERSED` | 4.6 / 4.2 |
| 409 | `PUR_OVER_RECEIPT` / `PUR_SELF_APPROVAL` | 4.1 / 5.1 |
| 409 | `WO_HAS_TRANSACTIONS` | cancel/delete/refresh with issues or receipts |
| 409 | `MRP_RUN_IN_PROGRESS` / `MRP_RUN_NOT_LATEST` / `MRP_ALREADY_CONVERTED` / `MRP_RUN_NOT_COMPLETED` | 8.14 |
| 422 | `MFG_DATA_HEALTH_FAILED` / `MRP_PREFLIGHT_FAILED` / `MRP_TOO_LARGE` | 8.12 / 3.10 |
| 422 | `INV_LOT_REQUIRED` `INV_LOT_NOT_ALLOWED` `INV_LOT_EXPIRED` `INV_LOT_ON_HOLD` `INV_FRACTIONAL_QTY` `INV_BACKDATE_LIMIT` `INV_SAME_LOCATION` `INV_LOCATION_INACTIVE` `INV_LOCATION_REQUIRED` `INV_REASON_REQUIRED` | 4.1 |
| 422 | `MFG_ITEM_NOT_BUY` `PUR_SUPPLIER_REQUIRED` `PUR_SCHEDULE_HAS_RECEIPTS` `PUR_QTY_BELOW_RECEIVED` `PUR_LINE_CONVERTED` | 5 |
| 422 | `DEM_ITEM_NOT_PLANNABLE` `DEM_SERIAL_QTY_MISMATCH` `DEM_SERIAL_OVERLAP` `DEM_QTY_BELOW_SHIPPED` `DEM_LINE_HAS_SHIPMENTS` `DEM_OVER_SHIPMENT` | 6 |
| 422 | `WO_OVER_ISSUE` `WO_QTY_BELOW_COMPLETED` `WO_COMPONENT_BELOW_ISSUED` | 7 |
| 422 | `MBR_USER_NOT_FOUND` `MBR_SELF` `MBR_UNAVAILABLE` | 10 |
| 422 | `VALIDATION_ERROR` `MFG_UNKNOWN_REFERENCE` `MFG_LIMIT` `MFG_ITEM_NOT_MAKE` `MFG_SERIAL_NOT_ALLOWED` | as M1 |

### 12.3 Endpoint table (numbering continues M1's 1-77; perm = 10.2)

| # | Method and path | Body / query | Response | Perm | Errors |
|---|---|---|---|---|---|
| 78 | GET `/me` | - | `MeResponse` (10.2) | view | - |
| 79 | GET `/workspaces` | - | `{"items": [{owner_id, plant_name, is_owner, roles}]}` (own first) | view | - |
| 80 | GET `/members` | - | `{"items": [MemberRecord]}` | owner | 422 single_user |
| 81 | POST `/members` | `MemberInput` | 201 `MemberRecord` | owner | 409 422 |
| 82 | PUT `/members/{member_id}` | `{roles, active}`, If-Match | `MemberRecord` | owner | 404 412 428 422 |
| 83 | DELETE `/members/{member_id}` | If-Match | 204 | owner | 404 412 428 |
| 84 | GET `/locations` | `q, kind, active` | `{"items": [LocationRecord]}` by code | view | - |
| 85 | POST `/locations` | `LocationInput` | 201 | master_edit | 409 422 |
| 86 | PUT `/locations/{location_id}` | If-Match | record | master_edit | 404 412 428 409 422 |
| 87 | DELETE `/locations/{location_id}` | If-Match | 204 | master_edit | 409 in use (balances/transactions) |
| 88 | GET `/suppliers` | `q, active` | `{"items": [SupplierRecord]}` | view | - |
| 89 | POST `/suppliers` | `SupplierInput` | 201 | supplier_edit | 409 422 |
| 90 | GET `/suppliers/{supplier_id}` | - | record + `items: [ItemSupplierRecord]` | view | 404 |
| 91 | PUT `/suppliers/{supplier_id}` | If-Match | record | supplier_edit | 404 412 428 409 422 |
| 92 | DELETE `/suppliers/{supplier_id}` | If-Match | 204 (item links cascade) | supplier_edit | 409 in use (purchase docs) |
| 93 | GET `/item-suppliers` | `item_id, supplier_id` (one required) | `{"items": [ItemSupplierRecord]}` (preferred first) | view | 422 |
| 94 | POST `/item-suppliers` | `ItemSupplierInput` | 201 | supplier_edit | 409 422 |
| 95 | PUT `/item-suppliers/{item_supplier_id}` | If-Match | record | supplier_edit | 404 412 428 422 |
| 96 | DELETE `/item-suppliers/{item_supplier_id}` | If-Match | 204 | supplier_edit | 404 412 428 |
| 97 | GET `/lots` | `item_id, q, expiring_before, hold, limit, offset` | page of `LotRecord` by expires_on | view | - |
| 98 | PUT `/lots/{lot_id}` | `LotUpdate`, If-Match | `LotRecord` | inventory | 404 412 428 422 |
| 99 | GET `/inventory/balances` | `q, item_id, location_id, kind, nettable, lot_id, only_nonzero (true), sort (part_number\|location\|-qty), limit, offset` | page of `BalanceRow` + `totals {qty_on_hand, qty_reserved, value}` (when `item_id` given) | view | - |
| 100 | GET `/items/{item_id}/stock` | - | `{"item", "totals": {nettable, inspection, quarantine, reserved, available, value}, "balances": [BalanceRow], "open_supply": [{type, ref, date, qty}], "open_demand": [{type, ref, date, qty}], "latest_run": {run_id, run_no, first_short_date, short_qty} \| null}` | view | 404 |
| 101 | GET `/inventory/transactions` | `item_id, location_id, lot_id, txn_type, posting_id, ref_type, ref_id, from, to, limit, offset` | page of `TransactionRow` by seq desc | view | 422 |
| 102 | POST `/inventory/postings` | `PostingInput`, optional `Idempotency-Key` | 201 `PostingRecord` (200 on replay) | inventory | 409 422 |
| 103 | GET `/inventory/postings` | `type, from, to, q (number), limit, offset` | page of posting headers (`line_count`) | view | - |
| 104 | GET `/inventory/postings/{posting_id}` | - | `PostingRecord` | view | 404 |
| 105 | POST `/inventory/postings/{posting_id}/reverse` | `{"note": ""}` | 201 `PostingRecord` | inventory | 404 409 |
| 106 | GET `/purchase-requests` | `status (multi), supplier_id, item_id, overdue, q, source, sort (-created_at\|number\|next_dock_date), limit, offset` | page of `PurchaseDocSummary` | view | - |
| 107 | POST `/purchase-requests` | `PurchaseDocInput` | 201 `PurchaseDocRecord` (`draft`) | pr_edit | 409 422 |
| 108 | GET `/purchase-requests/{doc_id}` | - | record | view | 404 |
| 109 | PUT `/purchase-requests/{doc_id}` | If-Match | record | pr_edit | 404 412 428 409 422 |
| 110 | DELETE `/purchase-requests/{doc_id}` | If-Match | 204 | pr_edit | 409 |
| 111-115 | POST `/purchase-requests/{doc_id}/submit` \| `approve` \| `reject` \| `revise` \| `cancel` | `{}` (`reject`: `{"reason"}`; `approve`: `{"note": ""}`), If-Match | record | 5.1 | 404 412 428 409 422 |
| 116 | POST `/purchase-requests/{doc_id}/convert` | 5.4, If-Match, `Idempotency-Key` | 201 `{"pr", "po"}` | po_edit | 404 409 412 428 422 |
| 117 | GET `/purchase-orders` | as 106 | page | view | - |
| 118 | POST `/purchase-orders` | `PurchaseDocInput` | 201 (`draft`) | po_edit | 409 422 |
| 119 | GET `/purchase-orders/{doc_id}` | - | record + `receipts: [posting headers]` | view | 404 |
| 120 | PUT `/purchase-orders/{doc_id}` | If-Match | record | po_edit | 404 412 428 409 422 |
| 121 | DELETE `/purchase-orders/{doc_id}` | If-Match | 204 | po_edit | 409 |
| 122-124 | POST `/purchase-orders/{doc_id}/issue` \| `close` \| `cancel` | `{}`, If-Match | record | po_edit | 404 412 428 409 |
| 125 | GET `/purchasing/schedule` | `from, to (dock date), supplier_id, item_id, doc_type, overdue_only, limit, offset` | page of `ScheduleRow {schedule_id, seq, doc {id, doc_type, number, status}, line_no, item, supplier, requested_date, confirmed_date, dock_date, available_date, qty, received_qty, open_qty, overdue, overdue_days, link}` by dock_date | view | 422 |
| 126 | GET `/demand-orders` | `status, demand_type, program, item_id, due_from, due_to, late_only (latest run), q, limit, offset` | page of `DemandOrderSummary` (`line_count, open_qty, next_due, late_lines`) | view | - |
| 127 | POST `/demand-orders` | `DemandOrderInput` | 201 (`draft`) | demand_edit | 409 422 |
| 128 | GET `/demand-orders/{order_id}` | - | `DemandOrderRecord` | view | 404 |
| 129 | PUT `/demand-orders/{order_id}` | If-Match | record | demand_edit | 404 412 428 409 422 |
| 130 | DELETE `/demand-orders/{order_id}` | If-Match | 204 | demand_edit | 409 |
| 131-133 | POST `/demand-orders/{order_id}/open` \| `close` \| `cancel` | `{}`, If-Match | record | demand_edit | 409 |
| 134 | GET `/work-orders` | `status (multi), item_id, q, start_from, start_to, source, sort (start_date\|due_date\|number\|priority), limit, offset` | page of WO summaries (no components; `component_count`) | view | - |
| 135 | POST `/work-orders` | `WorkOrderInput` | 201 `WorkOrderRecord` (`planned`) + `warnings` | wo_edit | 409 422 |
| 136 | GET `/work-orders/{wo_id}` | - | record | view | 404 |
| 137 | PUT `/work-orders/{wo_id}` | If-Match | record | wo_edit | 404 412 428 409 422 |
| 138 | DELETE `/work-orders/{wo_id}` | If-Match | 204 | wo_edit | 409 |
| 139 | POST `/work-orders/{wo_id}/release` | `{"reserve": false}`, If-Match | record + `reserved` | wo_edit | 409 |
| 140-143 | POST `/work-orders/{wo_id}/complete` \| `close` \| `cancel` \| `refresh-components` | `{}`, If-Match | record | wo_edit | 409 |
| 144 | GET `/work-orders/{wo_id}/kitting` | - | 7.4 | view | 404 |
| 145 | POST `/work-orders/{wo_id}/reserve` | `{"component_ids": null}`, If-Match | record + `reserved` | wo_edit | 409 |
| 146 | POST `/work-orders/{wo_id}/unreserve` | `{"component_ids": null}`, If-Match | record | wo_edit | 409 |
| 147 | POST `/work-orders/kitting-check` | 7.4 | 7.4 | view | 422 |
| 148 | POST `/mrp/runs` | `MrpParams` | 201 `MrpRunRecord` | mrp_run | 409 422 |
| 149 | GET `/mrp/runs` | `kind, pinned, limit, offset` | page of `MrpRunRecord` (no params) by run_no desc | view | - |
| 150 | GET `/mrp/runs/latest` | `kind (live)` | `MrpRunRecord` or 404 | view | 404 |
| 151 | GET `/mrp/runs/{run_id}` | - | `MrpRunRecord` (+ `stale`) | view | 404 |
| 152 | PUT `/mrp/runs/{run_id}` | `{"label", "note", "pinned"}`, If-Match | record | mrp_run | 404 412 428 422 (`MFG_LIMIT` pinned) |
| 153 | DELETE `/mrp/runs/{run_id}` | If-Match | 204 | mrp_run | 404 412 428; 409 `MFG_IN_USE` for the latest live run |
| 154 | GET `/mrp/runs/{run_id}/items` | `q, make_buy, family, short_only, has_exceptions, planned_only, llc, sort (llc\|part_number\|first_short_date\|-short_qty), limit, offset` | page of `MrpItemRow` | view | 404 |
| 155 | GET `/mrp/runs/{run_id}/items/{item_id}` | `bucket (day\|week\|month, default week), from, to` | `MrpItemPlan` (12.4) | view | 404 |
| 156 | GET `/mrp/runs/{run_id}/planned-orders` | `kind, item_id, supplier_id, release_status, status, q, sort (start_date\|need_date\|part_number\|supplier), limit, offset` | page of `PlannedOrderRow` + `counts` | view | 404 |
| 157 | POST `/mrp/runs/{run_id}/planned-orders/convert` | 8.14 body, `Idempotency-Key` | 201 `{"converted": [...], "created": {...}}` | mrp_run | 404 409 422 |
| 158 | GET `/mrp/runs/{run_id}/exceptions` | `code (multi), severity (multi), item_id, demand_line_id, q, limit, offset` | page of `MrpExceptionRow` + `counts {by_severity, by_code}` | view | 404 |
| 159 | GET `/mrp/runs/{run_id}/demand` | `status, program, order_id, late_only, sort (-late_days\|due_date), limit, offset` | page of `DemandProjectionRow` | view | 404 |
| 160 | GET `/mrp/runs/{run_id}/pegging` | `item_id, node, kind (requirement\|supply), direction (up\|down), max_depth (1..20)` | `PeggingResponse` | view | 404 422 |
| 161 | GET `/mrp/runs/{run_id}/compare` | `with` (run id) | `CompareResponse` | view | 404 |
| 162 | GET `/mrp/runs/{run_id}/export` | `format=xlsx\|zip` | file | view | 404 422 |
| 163 | GET `/shortages` | `horizon_days (default 30)` | `ShortageDashboard` (12.4) | view | - |

86 new operations (163 in `/api/v1/mfg`). M1 #2 `GET /summary` gains additive counts `locations, suppliers,
open_purchase_orders, open_purchase_requests, overdue_schedules, open_demand_lines, open_work_orders` and
`latest_run: {id, run_no, finished_at, demand_late, stale} | null`. M1 #73/#74 gain `scope`. M1 #76 sample load body
gains `anchor: date | null` and `include_transactions: bool = true` (13.1). M1 #77 reset deletes M2 data (9.4).

### 12.4 Response shapes and JSON examples (contract for WP-C; mirrored in `frontend/src/mfg/api/typesM2.ts`)

Posting (#102), PO receipt with a lot and an auto location:
```json
POST /api/v1/mfg/inventory/postings      Idempotency-Key: grn-2026-11-02-0007
{"type": "po_receipt", "txn_date": "2026-11-02", "note": "GRN 7",
 "lines": [{"schedule_id": "psc_1a...", "location_id": null, "qty": 30, "lot_code": "FV1-2611-A",
            "expires_on": "2028-11-01", "supplier_lot": "AX99812"}]}
-> 201
{"id": "pst_7c...", "number": "TXN-000041", "type": "po_receipt", "txn_date": "2026-11-02", "note": "GRN 7",
 "reason_code": null, "actor": {"id": "usr_...", "name": "Store 1"}, "created_at": "2026-11-02T05:31:10Z",
 "reversal_of": null, "reversed_by": null, "warnings": [],
 "lines": [{"id": "txn_...", "seq": 90211, "posting_id": "pst_7c...", "posting_number": "TXN-000041", "line_no": 1,
            "txn_type": "po_receipt", "txn_date": "2026-11-02",
            "item": {"id": "itm_...", "part_number": "KV-IC-FPGA-V1", "revision": "A", "description": "...", "uom": "EA",
                     "make_buy": "buy", "active": true},
            "location": {"id": "loc_...", "code": "GOODS-IN", "name": "Goods-in inspection", "kind": "inspection"},
            "lot": {"id": "lot_...", "lot_code": "FV1-2611-A", "expires_on": "2028-11-01", "hold": false},
            "qty": 30, "balance_after": 30, "unit_cost": 412.5,
            "ref": {"type": "po", "id": "pdc_...", "number": "PO-KV-0101", "line_no": 10, "schedule_seq": 1,
                    "label": "PO-KV-0101 / 10 / 1"},
            "actor": {"id": "usr_...", "name": "Store 1"}, "created_at": "2026-11-02T05:31:10Z"}]}
```
Insufficient stock:
```json
409 {"error": {"code": "INV_INSUFFICIENT_STOCK", "message": "Only 12 of KV-CON-M12-8P are available in STORES-MAIN (20 on hand, 8 reserved); 15 requested.",
     "details": {"item_id": "itm_...", "location_id": "loc_...", "lot_code": null, "on_hand": 20, "reserved": 8, "available": 12, "requested": 15, "line": 0}}}
```
Purchase order with staggered deliveries (#118):
```json
POST /api/v1/mfg/purchase-orders
{"number": "PO-KV-0101", "supplier_id": "sup_...", "currency": "INR", "order_date": "2026-06-10", "note": "",
 "lines": [{"line_no": 10, "item_id": "itm_fpga_v1", "unit_price": 412.5,
            "schedules": [{"seq": 1, "requested_date": "2026-11-20", "qty": 30},
                          {"seq": 2, "requested_date": "2026-12-20", "confirmed_date": "2027-01-05", "qty": 30},
                          {"seq": 3, "requested_date": "2027-02-20", "qty": 30}]}]}
-> 201 ETag "1"  {"id": "pdc_...", "doc_type": "po", "number": "PO-KV-0101", "status": "draft", ...,
   "lines": [{"id": "pln_...", "line_no": 10, "item": {...}, "status": "open", "qty": 90, "received_qty": 0, "open_qty": 90,
              "schedules": [{"id": "psc_...", "seq": 2, "requested_date": "2026-12-20", "confirmed_date": "2027-01-05",
                             "qty": 30, "received_qty": 0, "open_qty": 30, "closed": false, "dock_date": "2027-01-05",
                             "available_date": "2027-01-07", "overdue": false, "overdue_days": 0}, ...]}],
   "value": 37125.0, "open_value": 37125.0, "overdue_count": 0, ...}
```
MRP run (#148):
```json
POST /api/v1/mfg/mrp/runs
{"label": "Weekly plan", "allocation": "priority", "alternates": "when_short"}
-> 201
{"id": "mrr_...", "run_no": 12, "kind": "live", "status": "completed", "label": "Weekly plan", "note": "", "pinned": false,
 "as_of": "2026-11-02", "horizon_days": 90, "params": {...}, "master_fingerprint": "6f1c...", "row_version": 1,
 "started_at": "2026-11-02T06:00:00Z", "finished_at": "2026-11-02T06:00:03Z", "duration_ms": 2870,
 "actor": {"id": "usr_...", "name": "Planner 1"},
 "summary": {"demand_lines": 8, "demand_on_time": 5, "demand_late": 2, "demand_past_due": 0, "max_late_days": 28,
             "items": 1173, "items_short": 41, "planned_make": 96, "planned_buy": 603, "release_now": 188,
             "start_in_past": 37, "alternates_used": 2, "iterations": 2, "exceptions_truncated": false,
             "exceptions": {"by_severity": {"critical": 2, "warning": 85, "info": 240}, "by_code": {"MRP_DEMAND_LATE": 2, "...": 0}},
             "timings_ms": {"load": 410, "compute": 1520, "store": 940}},
 "stale": {"is_stale": false, "master_changed": false, "transactions_changed": false}, "error": null}
```
(Numbers illustrative; the sample's real values are pinned at implementation.)

`MrpItemRow`: `item: ItemRef, llc, make_buy, uom, on_hand, gross_qty, existing_supply_qty, planned_qty,
planned_count, first_short_date, short_qty, late_qty, min_balance, exception_count, lead_time {source:
"override"|"item_supplier"|"supplier"|"item"|"routing"|"fixed", days, unit: "calendar"|"working"}, link`.

`MrpItemPlan` (#155): `{"run": {id, run_no, as_of, stale}, "row": MrpItemRow, "lot": {rule, moq, multiple, pack,
period_days, fixed_qty}, "supplier": Ref | null, "timeline": [{date, kind ("on_hand"|"requirement"|"supply"|
"planned"), node, label, qty (signed), balance_existing, balance_planned}], "buckets": [{start, end, gross,
existing_supply, planned, balance_existing_end, balance_planned_end, short}], "requirements": [{node, kind,
need_date, qty, rank_label, segment, source: {type ("demand_line"|"planned_order"|"work_order"|"extra"|
"safety_stock"), id, label, item_id, node, link}, satisfied_date, late_days, pegs: [{supply_node, supply_label,
qty, late_days}]}], "supplies": [{node, kind, label, avail_date, projected_date, qty, pegged_qty, expires_on, ref:
{type, id, number, link}, planned_no, exception_codes: [..]}]}`.

`PlannedOrderRow`: `id, planned_no, kind, item: ItemRef, supplier: Ref | null, qty, need_date, start_date, dock_date,
projected_start, projected_due, late_days, release_status, segment, lot_note, peg_summary, status, converted: {type,
id, number} | null, link`.

`MrpExceptionRow`: `id, ex_no, code, severity, item: ItemRef | null, subject {type, id, label}, demand_line_id, date,
qty, days, message, action, suggested, related, link`.

`DemandProjectionRow`: `demand_line_id, extra, order {id, number, demand_type, customer, program} | null, line_no,
item: ItemRef, qty, due_date, priority, segment, projected_date, late_days, status, limiting: [{item: ItemRef,
label, date, reason ("lead_time"|"start_in_past"|"supply_date"|"component")}], link`.

`PeggingResponse`: `{"root": {item_id, node, kind}, "direction", "rows": [{row, parent_row, level, item: ItemRef,
node, kind, label, qty (pegged on the edge), date, projected_date, late_days, link}], "truncated"}`.

Convert (#157):
```json
POST /api/v1/mfg/mrp/runs/mrr_.../planned-orders/convert
{"mode": "release", "orders": [{"id": "mpo_a"}, {"id": "mpo_b", "qty": 6000}], "pr_grouping": "per_supplier",
 "add_to_pr_id": null, "reserve": false}
-> 201 {"converted": [{"planned_order_id": "mpo_a", "type": "wo", "id": "wko_...", "number": "WO-000143"},
                      {"planned_order_id": "mpo_b", "type": "pr", "id": "pdc_...", "number": "PR-000088", "line_no": 10}],
        "created": {"work_orders": [{"id", "number"}], "purchase_requests": [{"id", "number", "supplier": Ref, "line_count": 1}]}}
```

`CompareResponse`: `{"a": MrpRunRecord, "b": MrpRunRecord, "demand": [{demand_line_id, label, due_date,
a_projected, b_projected, delta_days}], "planned": {"a": {make, buy, make_qty, buy_value}, "b": {...}},
"exceptions_by_code": [{code, a, b}], "items": [{item: ItemRef, a_planned_qty, b_planned_qty, a_short_qty,
b_short_qty}], "truncated": {demand, items}}` (changed rows only, `COMPARE_MAX_ROWS`).

`ShortageDashboard` (#163): `{"run": {id, run_no, as_of, stale} | null, "counts": {late_demand, short_items,
overdue_schedules, wo_short}, "late_demand": [DemandProjectionRow] (late, top 50 by late_days), "short_items":
[MrpItemRow] (short_qty > 0, by first_short_date, top 100), "overdue_supply": [ScheduleRow] (live, top 100 by
overdue_days), "wo_shortages": kitting-check `items_short` for released/in-progress WOs and planned WOs starting in
`horizon_days` (live, top 100)}`.

---
## 13. Sample data (`superplanner/mfg/samples`, WP-A)

### 13.1 Rules

- `build(sample_id, *, anchor: date = date(2026, 11, 2), include_transactions: bool = True) -> MfgBundle`: master
  sheets as M1 (+ locations, suppliers, item_suppliers, item lot fields) and transactional sheets (stock, purchase
  documents, demand, WOs) whose dates are **offsets from `anchor`** (a Monday; written `A+n` below). Deterministic
  (M1 10.1 rules); golden hashes and per-sheet counts are pinned for `anchor = 2026-11-02`; changing a generator
  means updating the golden values in the same change. The M1 golden values change once in M2 (new item columns
  and sheets), deliberately.
- `POST /samples/{id}/load {"replace": false, "anchor": null, "include_transactions": true}`: `anchor = null` ->
  the Monday on or before plant today, so the demo always looks current; tests pass `anchor` explicitly. Loading
  goes through `plan_import` + writer (opening stock via one `count` posting reason `IMPORT`; opening received/
  shipped/issued/completed quantities via the create-only columns). Members are never touched.
- Every sample passes Gate 1 with the M1 intended issue sets unchanged, and its MRP run (as_of = anchor, defaults)
  is pinned: `summary` counts, the set of `(code, subject label)` of critical/warning exceptions, late demand lines
  with late days (`tests/mfg_mrp/test_mrp_samples.py`, WP-E, after A3).
- Fictional: supplier names "Supplier A (fictional)"..., customers "Zonal Railway A (fictional)".

### 13.2 `small` (M2 part)

Locations `STORES` (stores), `GOODS-IN` (inspection, receipt default), `QUAR` (quarantine). Suppliers `SUP-A`, `SUP-B`; one item-supplier per buy item (MCU on both, `SUP-A` preferred,
lead time 84). Stock for 8 of the 9 components (MCU: 30). PO `PO-SM-0001` for the MCU: 40 at `A+10`, 40 at `A+40`.
Demand `DO-SM-001` (customer, priority 2): 50 x `SM-100` due `A+21`; `DO-SM-002` (spares, priority 5): 20 x `SM-100`
due `A+45`. Intended: `DO-SM-001` on time from stock + the first MCU delivery; `DO-SM-002` late (second delivery
lands after the WO start; `MRP_EXPEDITE` on schedule 2); one planned PR for the bare PCB with `release_now`. Small
enough to check by hand (acceptance 18 #3 uses it).

### 13.3 `kavach` (M2 part)

- **Locations**: `STORES-MAIN` (stores), `GOODS-IN` (inspection, receipt default), `LS-SMT`, `LS-HAR` (line side),
  `FG` (stores, finished goods), `QUAR` (quarantine).
- **Suppliers** (8, fictional): semiconductors x2, passives x2, connectors/wire, mechanical, displays/radio, print.
  Every buy item gets one preferred item-supplier (row lead time = the item's lead time; passives MOQ/multiple 5,000
  move from the item to the item-supplier row, purchase unit `REEL`, pack 5,000); ICs a second, non-preferred
  supplier with +28 days. Unit prices synthetic, deterministic; `standard_cost` = preferred price.
- **Item lot settings**: `lot_controlled` for `KV-COAT-UR`, the 6 FPGAs/processors and `KV-MOD-GSM`; library buy
  items `lot_rule: period`, `lot_period_days: 30`; ICs `receiving_days: 2`.
- **Serial ECO**: `KV-TPU-1000` gets BOM v2, serial-specific `126..1000000000`, identical to v1 except
  `KV-DOC-PACK` -> new buy item `KV-DOC-PACK-B` (lead time 14). (Requires `KV-TPU-1000` serialized: it is.)
- **Demand** (anchor A = Mon 2 Nov 2026 in the pinned build):

| Order | Type, programme, priority | Lines |
|---|---|---|
| `DO-KV-001` | customer "Zonal Railway A", `KVP-26`, 1 | 10: 10 x KV-TPU-1000 due A+43, serials 101-110; 20: 10 x due A+74, serials 111-120 |
| `DO-KV-002` | customer "Zonal Railway B", `KVP-27`, 2 | 10: 15 x KV-TPU-1000 due A+90, serials 121-135 (crosses the ECO at 126) |
| `DO-KV-003` | spares, 3 | 10: 4 x KV-PCB-CPU due A+29; 20: 6 x KV-HAR-L03 due A+23; 30: 2 x KV-PSU-6000 due A+69 |
| `DO-KV-004` | project (prototype), `KVP-PROTO`, 1 | 10: 2 x KV-TPU-1000 due A+18, serials 99-100 |
| `DO-KV-005` | customer, `KVP-27`, 2, **draft** | 10: 5 x KV-TPU-1000 due A+120 (not planned) |

- **Stock** (one opening count): per buy item a seeded "units of cover" `c` in {0 (5%), 20 (25%), 50 (70%)}: on hand
  = `ceil(c x qty per TPU)`, rounded up to the pack for reels; explicit exceptions: `KV-IC-FPGA-V1` 45 (`STORES-MAIN`,
  lot `FV1-2609`), `KV-MOD-GSM` 8, `KV-LCD-104` 20 + 6 in `GOODS-IN` (`last_receipt_on` A-1), `KV-COAT-UR` lots
  `L-2610` 1.5 L expiring A+18 and `L-2702` 4 L expiring A+200, a connector with 50 in `QUAR`, finished
  sub-assemblies `KV-HAR-L01` 6 and `KV-PCB-LED` 15 in `STORES-MAIN`, reels on `LS-SMT` for 20 passives.
- **Purchase orders** (staggered): `PO-KV-0101` FPGA-V1 30 dock A+20, 30 requested A+48 confirmed A+64, 30 A+110;
  `PO-KV-0103` GSM 40 as 10 at A+28, A+58, A+88, A+118; `PO-KV-0104` LCD 20 A+23, 20 requested A+48 confirmed A+63,
  20 A+78 (the first schedule already partly received: 6 of 20, the 6 in `GOODS-IN`); `PO-KV-0102` connectors 200
  dock A-12, open (overdue); `PO-KV-0105` `KV-DOC-PACK` 40 at A+30 (more than serials < 126 need: reduce/cancel
  messages); 6 further POs for passives/mechanics with 1-3 schedules.
- **Purchase requests**: `PR-KV-0201` (submitted) for two connectors, 2 schedules each; `PR-KV-0202` (draft, source
  mrp) for wire.
- **Work orders**: `WO-KV-0001` KV-PCB-CPU 30, released, start A-3, due A+7, 50% of components issued, rest reserved
  where stock allows; `WO-KV-0002` KV-HAR-L03 12, in progress, 4 completed; `WO-KV-0003` KV-VCU-2000 10, planned
  (firm), start A+20, due A+30.
- **Intended MRP outcomes** (pinned at implementation, LEAD checks they hold): `DO-KV-004/10` late
  (`MRP_DEMAND_LATE`, limiting path through the final-assembly lead time and the FPGA allocation); `DO-KV-002/10`
  late on part of its quantity because of `KV-MOD-GSM` (`MRP_SHORTAGE` GSM); `DO-KV-002/10` planned as two
  `KV-TPU-1000` WO segments 121-125 / 126-135 and `KV-DOC-PACK-B` planned only for the second; `MRP_EXPEDITE` on
  `PO-KV-0101` schedule 2 and `PO-KV-0104` schedule 2; `MRP_PAST_DUE_SUPPLY` on `PO-KV-0102`; `MRP_REDUCE` or
  `MRP_CANCEL` on `PO-KV-0105`; `MRP_EXPIRING_STOCK` on `L-2610`; at least one `MRP_ALTERNATE_USED` on the
  `KV-PCB-DCC` capacitor group; `MRP_RELEASE_NOW` for passives; `MRP_WO_LATE` on `WO-KV-0001` (if a reserved
  component is short). Volume targets: ~1,200 balances, 12 POs, 2 PRs, 5 demand orders, 3 WOs; MRP ~100 planned
  WOs, ~600 planned PRs.

### 13.4 `medium` (M2 part)

3 locations, 3 suppliers, stock for ~80% of items, 3 POs (one staggered), 2 demand orders (`MD-200` 20 and 30, two
priorities), 1 released WO. Intended: one late demand due to the 210-day MCU.

---

## 14. Frontend (`frontend/src/mfg/**`, WP-C; React 18 + TS, no new npm packages)

### 14.1 Navigation

`MfgLayout` sub-nav becomes two groups: **Setup** (Overview, Items, Plant, People & tooling, Data health,
Import/export) and **Planning & stores** (Demand, MRP, Shortages, Work orders, Purchasing, Inventory). Header: the
**workspace switcher** (`GET /workspaces`; shown only with more than one workspace; the selection is stored in
`sessionStorage` and sent as `X-SP-Workspace` by `mfgRaw` on every call; switching reloads the area) and the role
badge. `PermissionGate` hides actions the user lacks (`GET /me` permissions); the server still enforces (403 shows
a banner). Owner-only: `/mfg/settings/members`.

### 14.2 Routes

| Route | Page | Content |
|---|---|---|
| `/mfg/inventory` (`?item=&location=`) | `InventoryPage` (tabs) -> `BalancesTab` | virtual table of balances, filters, totals, "Post" menu |
| `/mfg/inventory/transactions` (`?item=&posting=`) | `TransactionsTab` | ledger (seq desc), filters, link to posting |
| `/mfg/inventory/postings/:postingId` | `PostingPage` | header, lines, Reverse |
| `/mfg/inventory/post` (`?type=&item=&location=`) | `PostingForm` | receipt / issue / adjust / transfer / count forms; line grid; lot pick (FEFO preview); Idempotency-Key per submit |
| `/mfg/inventory/lots` (`?lot=`) | `LotsTab` | expiry, hold toggle |
| `/mfg/inventory/locations` (`?location=`) | `LocationsTab` | CRUD |
| `/mfg/items/:itemId/stock` | `ItemStockTab` (new ItemShell tab) | totals, balances, open supply/demand, latest-run shortage |
| `/mfg/items/:itemId/suppliers` | `ItemSuppliersTab` | item-supplier rows, preferred |
| `/mfg/purchasing/orders` / `new` / `:docId` (`?line=&schedule=`) | `PurchaseDocList` / `PurchaseDocPage` | header, `DocLinesEditor` (lines with nested schedule rows, dock/available dates, overdue badges), status actions, **Receive** dialog (schedule rows with open qty, location, lot), receipts history |
| `/mfg/purchasing/requests` / `new` / `:docId` | `PurchaseDocList` / `PurchaseDocPage` | same components, PR actions (submit/approve/reject/revise/cancel/convert) |
| `/mfg/purchasing/schedule` (`?overdue=1&supplier=`) | `DeliveryBoard` | all open schedule lines by dock date, overdue first filter |
| `/mfg/purchasing/suppliers` / `:supplierId` (`?item_supplier=`) | `SuppliersPage` / `SupplierPage` | CRUD, item-supplier grid |
| `/mfg/demand` / `new` / `:orderId` (`?line=`) | `DemandList` / `DemandPage` | lines with serial ranges, projection column (latest run), open/close/cancel, Ship dialog |
| `/mfg/work-orders` / `new` / `:woId` (`?component=`) | `WorkOrderList` / `WorkOrderPage` | details, components grid with kitting columns (required, issued, reserved, free, shortage, next supply), actions release (+reserve), reserve/unreserve, Issue/Return/Complete dialogs (postings), transactions |
| `/mfg/work-orders/kitting` | `KittingCheckPage` | sequence options, per-WO rows, component shortage list |
| `/mfg/mrp` | `MrpRunsPage` | runs list (kind, status, KPIs, stale, pinned), `MrpRunForm` (params; "What-if" section: exclude demand, extra demand, supply date overrides, lead-time overrides) |
| `/mfg/mrp/runs/:runId` | `RunShell` (tabs) -> `RunSummaryTab` | KPI tiles, exceptions by code, late demand top 10, stale banner, export |
| `/mfg/mrp/runs/:runId/items` / `items/:itemId` | `RunItemsTab` / `ItemPlanPage` | plant material plan (virtual table); item plan: `ProjectedStockChart` (SVG step lines existing vs planned, shortage shading, bucket bars), bucket table, requirements and supplies with pegs, "Peg up/down" |
| `/mfg/mrp/runs/:runId/planned` (`?order=`) | `PlannedOrdersTab` | filters, multi-select (max 500), Firm / Release dialog (grouping, overrides) |
| `/mfg/mrp/runs/:runId/exceptions` (`?code=&severity=`) | `ExceptionsTab` | grouped by code, filter chips, action links |
| `/mfg/mrp/runs/:runId/demand` (`?line=`) | `DemandProjectionTab` | due vs projected, limiting path chips |
| `/mfg/mrp/runs/:runId/pegging` (`?item=&node=&kind=&direction=`) | `PeggingPage` | tree on `VirtualTable` (indent, late badges) |
| `/mfg/mrp/runs/:runId/compare` (`?with=`) | `CompareView` | run picker, deltas |
| `/mfg/shortages` | `ShortagesPage` | four panels of 12.4 with links |
| `/mfg/settings/members` | `MembersPage` | owner only |

`PlantSettingsPage` gains an "MRP" section (5 fields of 3.1); `ItemDetailsTab` gains external ref, standard cost,
lot controlled, lot rule `period` + days. Import wizard: sheet kinds shown per card, permission errors shown per
sheet, `scope` on export/template buttons.

### 14.3 Server-built links (exceptions, demand projections, schedule rows, health 44-47)

| Subject | Link |
|---|---|
| demand_line | `/mfg/demand/{order_id}?line={id}` |
| item (in a run) | `/mfg/mrp/runs/{run_id}/items/{item_id}` |
| planned_order | `/mfg/mrp/runs/{run_id}/planned?order={id}` |
| po_schedule / pr_schedule | `/mfg/purchasing/orders/{doc_id}?schedule={id}` / `/mfg/purchasing/requests/{doc_id}?schedule={id}` |
| work_order | `/mfg/work-orders/{id}` |
| lot | `/mfg/inventory/lots?lot={id}` |
| item_supplier | `/mfg/purchasing/suppliers/{supplier_id}?item_supplier={id}` |
| plant | `/mfg/plant/settings` |

### 14.4 Large data, files, test ids

- Reuse `VirtualTable`; every list above is paginated by 200 (infinite scroll); the run items table, pegging tree
  and planned orders never render more than ~80 DOM rows. `ProjectedStockChart` draws at most one point per event
  date (<= 5,000) with `polyline`s.
- New files under `frontend/src/mfg/`: `api/typesM2.ts`, `api/clientM2.ts`, `api/contractExamplesM2.ts` (typed
  examples of every 12.4 shape; type-checked by `npm run build`), `lib/workspace.ts`, `lib/permissions.ts`, pages and
  components named in 14.2 (+ `DocLinesEditor`, `ReceiveDialog`, `PostingForm`, `KittingTable`,
  `ProjectedStockChart`, `PeggingTree`, `ExceptionList`, `RunKpis`, `WorkspaceSwitcher`, `PermissionGate`).
- `data-testid` contract (C provides, D uses; C publishes additions in 22.WP-C): `nav-group-planning`,
  `workspace-switcher`, `role-badge`, `post-type-{receipt_misc|issue_misc|adjust|transfer|count}`, `post-line`,
  `post-submit`, `balance-row` (`data-item`, `data-location`, `data-qty`), `txn-row`, `doc-line`, `doc-schedule`
  (`data-overdue`), `doc-action-{submit|approve|reject|revise|cancel|convert|issue|close}`, `receive-open`,
  `receive-qty`, `receive-submit`, `demand-line` (`data-late-days`), `wo-action-{release|complete|close|cancel}`,
  `wo-reserve`, `kitting-row` (`data-shortage`), `mrp-new-run`, `mrp-run-submit`, `mrp-whatif-toggle`, `run-kpi-{late|short|planned_make|planned_buy|release_now}`,
  `run-stale-banner`, `run-tab-{summary|items|planned|exceptions|demand|compare}`, `item-plan-chart`,
  `item-plan-bucket` (`data-short`), `peg-row` (`data-level`), `planned-row` (`data-release-status`),
  `planned-select`, `convert-open`, `convert-mode-{firm|release}`, `convert-submit`, `exception-row`
  (`data-code`), `exception-link`, `limiting-step`, `compare-delta`, `shortage-panel-{demand|items|supply|wo}`,
  `member-add`, `member-row`, `forbidden-banner`.

---

## 15. Performance targets (PostgreSQL local, developer machine class of M1 17; `slow`-marked tests)

| # | Operation | Data | Target | Statements |
|---|---|---|---|---|
| MP1 | pure `run_mrp` | `kavach` sample (8 demand lines, 37 units + spares), incl. alternates pass | < 1.5 s | - |
| MP2 | pure `run_mrp` | `kavach` + 50 synthetic demand lines (2-10 units, distinct serial ranges, due dates over 180 days) | < 5 s | - |
| MP3 | pure `run_mrp` | `kavach x2` (4,938 BOM lines) + 100 demand lines | < 10 s | - |
| MP4 | `POST /mrp/runs` end-to-end | `kavach` sample / MP2 data | < 5 s / < 12 s (store < 4 s) | load <= 32 + chunks; store: one `add_all` per table, flush per table |
| MP5 | `GET /mrp/runs/{id}/items/{item_id}` (most shared capacitor) / items page / exceptions page / planned page | MP2 run | < 0.3 / 0.2 / 0.2 / 0.2 s | <= 4 each |
| MP6 | `GET .../pegging` up from a capacitor planned PR to all demands | MP2 run | < 0.5 s | <= depth + 3 |
| MP7 | posting, 1 line / 50 lines | kavach | p95 < 50 ms / < 0.3 s | <= 12 / bounded (no per-line SELECT loops: lines' keys loaded with IN) |
| MP8 | concurrency: 20 threads x 50 postings on 5 shared balances | | no lost update, no 500, total < 10 s | |
| MP9 | kitting one WO (280 components) / kitting-check 100 WOs | kavach | < 0.3 s / < 2 s | <= 8 |
| MP10 | import 20,000 stock rows: preview / commit | | < 5 s / < 15 s (balance locks held < 8 s) | bounded |
| MP11 | `POST /samples/kavach/load` incl. transactions | empty owner | < 15 s | |
| MP12 | compare two MP2 runs | | < 1 s | <= 10 |
| MP13 | UI: run items table (1,200 rows) interactive, item plan chart render, pegging tree 2,000 rows | Chromium | < 1 s / < 300 ms / < 1 s, <= 80 DOM rows | - |

---

## 16. Delivery plan

### 16.1 Packages and file ownership (authoritative; no file has two owners at once; `sp/` = `backend/superplanner/`)

| WP | Role | Owns (create/edit only these) |
|---|---|---|
| **A** Domain, DB, samples | backend-developer A | `sp/mfg/model.py` (3.1 additions), `model_m2.py`, `limits.py`, `dataset.py`, `bundle.py`, `health.py`, `messages.py`, `workdays.py`, `inventory.py`, `purchasing.py`, `demand.py`, `workorders.py`, `samples/**`; `sp/api/mfg/db_models.py` (columns), `db_models_m2.py`, `repo.py` (load_dataset additions), `repo_m2.py`; `sp/migrations/versions/0004_mfg_m2.py`; additive lines in `sp/migrate.py`, `sp/api/db/models.py`, `sp/api/db/__init__.py`; tests `backend/tests/mfg_m2/**`, `backend/tests/mfg_m2_db/**`; existing-test edits marked A in 19.2 |
| **E** MRP engine | backend-developer E | `sp/mfg/mrp/**`; tests `backend/tests/mfg_mrp/**` |
| **B** API, access, import/export | backend-developer B | `sp/mfg/io/**` (additions), `sp/api/mfg/access.py`, `schemas_m2.py`, `mrp_store.py`, `router_m2.py`, `services/**` (new files + the edits of 19.1), `writer.py`; additive lines in `sp/api/main.py`, `sp/api/db/ownership.py` (`bind_actor`, `current_actor`), `sp/api/services/problem_service.py` (`audit` actor), `sp/manage.py` (guard table list), `docs/DEPLOY.md` (one line: revision `0004_mfg_m2`); tests `backend/tests/api_mfg_m2/**`, `backend/tests/mfg_io_m2/**`; existing-test edits marked B in 19.2 |
| **C** UI | ui-developer | `frontend/src/mfg/**`, `frontend/e2e/mfg-helpers.ts` (additive helpers) |
| **D** QA | tester | `backend/tests/acceptance_m2/**` (incl. the independent MRP oracle `oracle_mrp.py`, which must not import `superplanner.mfg.mrp`), `frontend/e2e/m2-*.spec.ts`, `frontend/e2e/accounts/m2-*.spec.ts`, 22.WP-D |
| LEAD | team lead | this document (contract changes), reviews of A1/E0 and hand-ins |

Test helper module names unique across `backend/tests`: `mfgm2_helpers.py` (A), `mrp_helpers.py` (E),
`apimfgm2_helpers.py` (B), `accm2_helpers.py` (D). DB name factories: `"mfgm2db"`, `"apimfgm2"`, `"accm2"`.

### 16.2 Milestones and dependencies

```
A1+E0 contract freeze (day 1) ─┬─► A2 pure rules + repo/lockers ─► A3 dataset/health/samples ───────────────┐
                               ├─► E1 explode/leadtime/llc ─► E2 netting/lots/pegging ─► E3 forward/exceptions/alternates ─► E4 views + perf ─┤
                               └─► B1 access + master CRUD ─► B2 inventory ─► B3 purchasing/demand/WO ─► B4 MRP API + shortages ─► B5 import/export/samples/perf ─┤
C0 shell + types + examples (day 0-1) ─► C1 inventory (B2) ─► C2 purchasing (B3) ─► C3 demand/WO (B3) ─► C4 MRP + shortages (B4) ─► C5 members/import/polish ─┤
D oracle + acceptance + e2e writing (day 0) ──────────────────────────────────────────────────────► D final gate (once) ─► LEAD review
```

| Milestone | Deliverable | Accepted when |
|---|---|---|
| **A1** | `model_m2.py`, M1 model additions, `limits.py`, `workdays.py` (implemented + tests), `db_models_m2.py`, migration `0004` (+ up/down/compare test), `repo_m2.py` signatures, `bundle.SHEETS` M2 spec | LEAD review; `pytest tests/mfg_m2_db/test_m2_migration.py tests/db/test_db_migrations.py -q` green |
| **E0** | `mrp/model.py` frozen, signatures of `run_mrp`, `order_components`, `manufacturing_lead_days`, views; a hand-built `MrpResult` fixture (JSON) for B and C | LEAD review |
| A2 | `inventory.py`, `purchasing.py`, `demand.py`, `workorders.py` + tests; lockers and loaders implemented; balance/series/lot creation races tested on PG | targeted tests green |
| A3 | dataset/fingerprint/health 44-47; samples M2 + golden; reset-order test | targeted + `tests/mfg/test_mfg_samples.py`, `tests/mfg/test_mfg_health.py` |
| E1-E4 | per 8; T-M1..T-M15; MP1-MP3; sample pins after A3 | `pytest tests/mfg_mrp -q` |
| B1 | `/me`, workspaces, members, `require_perm` on all 163 routes, actor binding, locations/suppliers/item-suppliers/lots, `MFG_PROTECTED`/`MFG_PERMISSIONS`, sweep ids | targeted + `tests/auth/test_route_coverage.py` |
| B2 | postings (all types), reversal, idempotency, balances/ledger lists, concurrency tests | targeted |
| B3 | purchasing, schedule board, demand, WOs, kitting, reserve | targeted |
| B4 | MRP API (#148-#162), `mrp_store`, staleness, convert, shortages | targeted (uses E fixtures until E3) |
| B5 | import/export M2 sheets, samples load/reset, perf MP4-MP12 | targeted + `-m slow` of own folders |
| C0 | nav, workspace switcher, PermissionGate, `typesM2.ts`, `contractExamplesM2.ts`, item/plant fields | `npm run build` |
| C1-C5 | screens of 14.2 in order, against examples first, then the real API as B lands | `npm run build` + the one spec being worked on |
| D final | section 17.3 gate | all green, report in 22.WP-D |

**Contract rule (as M1 PLAN 0.2):** sections 3, 8.2, 9, 12 are the contract between A/E, B and C. A change is a
request to LEAD, who edits this document first and notifies B, C, D. Route and access-table entries land in the same
change as the route (B). C never edits backend files; D never edits product code or other packages' tests.

---

## 17. Testing strategy (cost-conscious)

### 17.1 During work: targeted tests only

- Pure tests first (no DB, seconds): `cd backend && .venv/bin/pytest tests/mfg_m2/test_inventory_rules.py -q`,
  `.venv/bin/pytest tests/mfg_mrp -q -k netting`.
- DB/API tests of the package's own files against the PostgreSQL dev cluster (`SP_TEST_PG_URL`, port 54329):
  `.venv/bin/pytest tests/api_mfg_m2/test_inventory_api.py -q -x`.
- Existing tests touched by a change (19.2) are run by name only, e.g. `pytest tests/mfg/test_mfg_samples.py
  tests/auth/test_route_coverage.py -q`.
- Frontend: `npm run build` (includes `tsc --noEmit` and the contract examples); one Playwright spec at a time
  (`npx playwright test e2e/m2-inventory.spec.ts`) only by D or C when that spec is being written.
- **Not run during work:** the full backend suite, the full Playwright suites, the `slow` marker of other packages.
- Each milestone hand-in lists the exact commands run and their counts in section 22.

### 17.2 Test content per package

- **A** (`tests/mfg_m2`, pure): every model rule of 3 (one valid, one invalid per rule); posting validation per
  type; FEFO picking; status machines (every allowed and one forbidden transition per action); serial-range rules;
  kitting simulation; `workdays` (T-M5 dates). (`tests/mfg_m2_db`): migration up/down/compare, names <= 63, owner-led
  and FK-led indexes, CHECK constraints fire, balance/lot/series create races with threads, lock-order helper sorts,
  `load_mrp_snapshot` statement count and equality with a pure snapshot built from the same bundle, reset order with
  every table populated.
- **E** (`tests/mfg_mrp`): T-M1..T-M15, each exception code positive + negative, both allocation policies, lot rules
  and rounding chain, segments/ECO split, phantom blow-through, reservations, expiry, overrides (what-if), limiting
  path, determinism (subprocess with two hash seeds), invariants (property tests, 500 seeded random plants), perf
  MP1-MP3, sample pins.
- **B** (`tests/api_mfg_m2`): CRUD/ETag/If-Match per entity; check order (foreign id -> 404 before 428; viewer -> 403
  before 422); every error code of 12.2 at least once; posting concurrency (MP8) and deadlock-free lock order;
  idempotent replay; reversal effects; PR/PO/demand/WO flows; conversion all-or-nothing and exactly-once under two
  concurrent requests; staleness; retention; members and the role matrix (one endpoint per permission x 6 roles);
  workspace isolation (member of A cannot see B; non-member 404 on every M2 path; scheduling/finance ignore the
  header); audit actor; import/export round trip and permission per sheet; sample load/reset; statement counts;
  perf MP4-MP12. (`tests/mfg_io_m2`): sheet specs, parsing, plan diffs for each new sheet.
- **D** (`tests/acceptance_m2` + e2e): section 18; the **independent MRP oracle** (`oracle_mrp.py`) is a deliberately
  naive re-implementation of section 8 written from this document only (day-by-day per item, no shared code), used
  for Gate 2 #2.

### 17.3 Once at the end: the full gate (D, after all hand-ins)

| # | Gate | Command / check |
|---|---|---|
| G1 | Full backend suite on PostgreSQL (queue + embedded workers), including `-m slow`: all existing tests pass, 0 failures | `cd backend && .venv/bin/pytest` then `.venv/bin/pytest -m slow` |
| G2 | Playwright single_user: existing specs unchanged + `m2-*.spec.ts` | `cd frontend && npm run e2e` |
| G3 | Playwright accounts: existing + `accounts/m2-*.spec.ts` | `npm run e2e:accounts` |
| G4 | `npm run build` clean, `npm audit` no high/moderate, `package.json`/lock unchanged | |
| G5 | Migration safety: populated `0003_mfg` database (kavach M1, problems, schedules, finance) upgrades to `0004_mfg_m2` with unchanged row counts; `migrate check` exits 0; `downgrade 0003_mfg` removes exactly the 22 tables and the 9 added columns | acceptance test |
| G6 | Existing-test diff touches only 19.2 entries (+ new files) | LEAD reads `git diff -U0 backend/tests frontend/e2e` |

D records the baseline counts of the last green full run before M2 work starts (no extra run: the release gate of
the PostgreSQL-only change is the baseline). **Fix round:** owners fix with targeted reruns; D reruns the failed
tests and the folders they touch; a second full G1-G3 run happens only if a fix touches shared code (`api/db/**`,
`api/auth/**`, `api/main.py`, migrations, `mfg/model.py`, `mfg/bundle.py`) or more than 10 files.

### 17.4 E2E specs (D, with C's helpers)

`m2-inventory.spec.ts` (post receipt/issue/transfer/count, insufficient-stock message, ledger and reversal);
`m2-purchasing.spec.ts` (PO with 3 schedules, partial receipt, overdue badge, PR submit -> approve (approver user in
the accounts spec) -> convert); `m2-mrp.spec.ts` (load kavach, run, late demand -> limiting path -> item plan chart
-> expedite link opens the PO schedule; release `release_now` planned PRs; re-run shows them as supply, stale banner
logic); `m2-workorders.spec.ts` (firm planned WO, release with reserve, kitting shortage, issue, partial complete);
`m2-whatif.spec.ts` (what-if with a 30-day delay on an FPGA schedule, compare deltas, convert disabled);
`m2-contract.spec.ts` (visit every route of 14.2 and every exception link of a kavach run, no unexpected 4xx/5xx);
`m2-scale.spec.ts` (MP13); `accounts/m2-roles.spec.ts` (owner adds store keeper + viewer; store keeper posts a
receipt but has no Run button and gets 403 by API; viewer sees no actions; non-member URL -> not found;
workspace switcher).

---

## 18. Acceptance criteria (Gate 2 exit, `backend/tests/acceptance_m2` + e2e)

1. `kavach` (master + transactions) loads into an empty account via the API: Gate 1 ok with the M1 intended issue
   set; pinned counts of balances, documents and lines; an MRP run completes within MP4.
2. **MRP equals the independent oracle** on `small`, `medium`, `kavach` and 200 seeded random plants (multi-level,
   shared components, staggered POs/PRs, lots with expiry, reservations, all lot rules, MOQ/multiple/pack, both
   allocation policies, alternates `never` and `when_short`, serial segments): identical planned orders (item, qty,
   need/start dates), identical peg quantities per (requirement, supply) pair, identical demand projected dates.
3. Hand-calculated checks through the API: T-M1, T-M3, T-M5, T-M6, T-M8, T-M13 set up by API calls on a fresh account
   reproduce the numbers of 8.15; `small` sample outcome of 13.2 matches a hand calculation in the test.
4. Kavach intended outcomes of 13.3 hold (exact set of late demand lines; the listed codes present on the listed
   subjects; `DO-KV-004/10` limiting path contains the `KV-TPU-1000` lead-time step).
5. Ledger integrity after a scripted plant day (receipts, partial receipts, issues, returns, transfers,
   inspection-to-stores, counts, reversals, WO issue/receipt, shipment): for every key `balance == sum(transactions)`;
   documents' received/issued/shipped/completed equal ledger sums; MP8 concurrency with exact final balances.
6. Firm/release loop: release every `release_now` planned order of the latest live run -> re-run -> no planned order
   duplicates converted supply (planned quantity of each affected item drops by the converted quantity modulo lot
   sizing); converting the same planned order again -> 409; converting from an older or what-if run -> 409.
7. Purchasing loop: PR by planner, approval by an `approver` member (self-approval refused), conversion to a PO,
   partial receipt on schedule 1, overdue flag on a past schedule; the next MRP run uses only the open remainder.
8. WO loop: release with reserve, kitting shortage list names exactly the items without free stock, issue,
   partial completion, auto status changes, shortage dashboard lists the WO shortages and overdue POs.
9. What-if: overriding one FPGA schedule by +30 days produces a `what_if` run; compare shows the expected demand
   deltas; the live run and live data are unchanged.
10. Roles and isolation: the 10.2 matrix holds for each role on one endpoint per permission; members see only the
    workspaces they belong to; non-members get 404; audit events of member actions carry the member as actor; the
    M1/2b authz sweep stays green.
11. Import/export: `scope=all` round trip byte-equal (CSV zip); a 20,000-row stock import meets MP10; permission per
    sheet enforced.
12. Reset with every M2 table populated (incl. runs, conversions, reversals) leaves zero `mfg_*` data rows for the
    owner, keeps memberships, leaves other users unchanged; `reassign-owner` guard and move cover the new tables.
13. Performance MP1-MP13 met; migration gate G5.
14. UI pilot journey (e2e): load sample -> run MRP -> late demand -> limiting path -> item plan shows the shortage ->
    exception link opens the PO schedule -> release planned PRs -> PRs listed -> re-run -> no duplicates.

---

## 19. Changes to existing code and tests

### 19.1 Existing code

| File | Change | WP |
|---|---|---|
| `sp/mfg/model.py` | `ItemInput` / `PlantInput` fields of 3.1, `lot_rule` literal | A |
| `sp/mfg/dataset.py`, `bundle.py`, `health.py`, `messages.py`, `limits.py`, `samples/*` | 3.10, 3.11, 11, 13 | A |
| `sp/api/mfg/db_models.py`, `repo.py` | new columns; `load_dataset` loads the 3 new master tables | A |
| `sp/migrate.py` | `HEAD = "0004_mfg_m2"` | A |
| `sp/api/db/models.py`, `sp/api/db/__init__.py` | register `db_models_m2` | A |
| `sp/api/db/ownership.py` | `bind_actor`, `current_actor` (contextvar, cleared with the owner binding) | B |
| `sp/api/services/problem_service.py` | `audit`: `actor_id = current_actor() or current_owner()` | B |
| `sp/api/mfg/router.py` | each M1 route gets its `require_perm` dependency (10.2), nothing else | B |
| `sp/api/mfg/services/items.py`, `plant.py`, `imports.py`, `samples.py` | item in-use and UoM rule (3.1); plant fields; M2 sheets + per-sheet permission; reset via `ALL_MFG_MODELS`, sample `anchor`/`include_transactions` | B |
| `sp/mfg/io/*` | M2 sheets | B |
| `sp/api/main.py` | include `router_m2` in `protected` | B |
| `sp/manage.py` | guard and move use `ALL_MFG_MODELS + MFG_ACCESS_MODELS` | B |
| `frontend/src/mfg/**` | 14 (incl. the item and plant forms sending the new fields) | C |

No change to engine, solvers, finance, intake, jobs, auth flows or configuration (no new settings).

### 19.2 Existing tests changed (only these)

| Test / file | Change | WP | Reason |
|---|---|---|---|
| `tests/mfg/test_mfg_samples.py` | golden hashes and counts | A | new item columns, new sheets, `KV-TPU-1000` BOM v2, `KV-DOC-PACK-B` |
| `tests/mfg_db/test_mfg_repo.py` | `load_dataset` statements 17 -> 20, bound 19 -> 22 | A | 3 new master tables |
| `tests/mfg/test_mfg_model.py` | item/plant field sets (if asserted as exact sets) | A | additive fields |
| `tests/db/test_db_migrations.py`, `tests/jobs/test_worker_process.py` | none expected (already use `migrate.HEAD`); if a literal `0003_mfg` remains, replace it with `migrate.HEAD` | A | new head |
| `tests/auth/route_table.py` | `MFG_PROTECTED` += 86 operations; new `MFG_PERMISSIONS` (163 entries) | B | access tables |
| `tests/auth/test_route_coverage.py` | `protected == PROTECTED \| MFG_PROTECTED` keeps working; new test permissions table == routes | B | |
| `tests/acceptance_phase2b/test_acc_authz_sweep.py` | `make_world` loads `small` with transactions and one MRP run; `id_map`/`body_for` for the new path parameters (`member_id, location_id, supplier_id, item_supplier_id, lot_id, posting_id, doc_id, order_id, wo_id, run_id`) | B | sweep must cover M2 paths |
| `tests/api_mfg/*` asserting exact `/summary` keys or item/plant record key sets | additive keys | B | |

Any other failing existing test is fixed in code, or recorded here first (LEAD).

---

## 20. Deferred items and plug-in points for M3

Deferred: IANA time zones (M3); async MRP as job kind `mrp_run` (M3, when MRP + scheduling run as one pipeline);
net-change MRP; forecasts and forecast consumption; ATP/CTP order promising; multi-level PR approval with amount
limits; supplier portal/EDI; cost roll-up and actual costing; serial capture and genealogy (M4/M5); MSL floor-life
tracking and bake cycles; backflush and operation-level material issue; cycle-count programmes (ABC); subcontracting
(make items bought from suppliers); multi-warehouse hierarchy and `plant_id` (M5); capacity-aware MRP. **M3
scheduling notes** (not M2): line-specific operation times, batching compatibility (oven/wash loads by family),
operator absences.

Plug-in points for M3:

| M3 need | M2 hook |
|---|---|
| Orders to schedule | WOs (`planned`/`released`/`in_progress`) and planned make orders of the latest live run, with qty, dates, routing id, serial segment |
| Material availability per operation | pegging: each component requirement's `satisfied_date` and pegged supplies (stock / PO schedule / child WO) -> earliest start of the consuming operation (`operation_seq` on components) |
| Replace infinite-capacity dates | M3 writes scheduled dates; MRP's forward pass can take WO dates from the schedule instead of lead times (`supply_date_overrides` is the same mechanism) |
| Explanations | MRP limiting path + M3 schedule explanations combined per demand line |

---

## 21. Open questions for the product owner

1. **Q1 Shared plant in the pilot.** Will different people (store keeper, purchaser, approver) work in the same
   plant during the M2 pilot? Default built: yes (workspaces + roles, 10). If one person runs everything, WP-B drops
   members/workspaces (about one milestone); the permission table stays.
2. **Q2 Working pattern and lead-time units.** Defaults: manufacturing lead times count Mon-Sat with 480 routing
   minutes per day; supplier lead times are calendar days. Please confirm for HBL (or give the real day length and
   working days), since these drive every planned date.
3. **Q3 PR approval.** One approval step by an `approver` member is built. Does HBL need value thresholds or a second
   approver for M2?
4. Data request (GA 8 items 4-5): an anonymised inventory snapshot and open-PO export with schedule lines, in
   whatever format the ERP produces, to tune the import header synonyms before the pilot.

---

## 22. Implementation notes

Developers write only to their own subsection (interpretations, measured numbers, commands run, deviations agreed
with LEAD).

### 22.WP-A Domain, DB, samples

### 22.WP-E MRP engine

Package `backend/superplanner/mfg/mrp/` (model, leadtime, llc, explode, netting, lotsize, engine, forward,
exceptions, views); imports only `superplanner.mfg` (asserted by `tests/mrp/test_mrp_properties.py::
test_engine_layering`). Tests live in `backend/tests/mrp/` (product-owner instruction; 16.1 said `tests/mfg_mrp`),
helpers `mrp_helpers.py`, `mrp_kavach_helpers.py`.

**Contract additions (additive, minimal; B/C/D please note):**
- E1 `MrpSnapshot` uses the snapshot rows of `mfg.model_m2` (`BalanceSnap` incl. `id`, `ReservationSnap`,
  `ScheduleSnap`, `DemandSnap`, `WoSnap`/`WoComponentSnap`) as built by WP-A; `lots` is any mapping id -> object
  with `lot_code` (labels only). The dataset is read with `getattr(ds, "locations"/"suppliers"/"item_suppliers",
  {})` and plant settings with defaults, so M1-shaped datasets also run.
- E2 `Supply.component_nodes` is `list[tuple[item_id, node]]` (8.2 said `list[int]`, which cannot address a node of
  another item). `Supply` adds `start_date`, `due_date` (make supplies; planned buys: order date).
- E3 `SourceRef(type, id, label, item_id, node, number, component_id)` is used for requirement sources and supply
  refs (types listed in its docstring). Planned-order ids in results and exception subjects are `str(planned_no)`;
  B maps them to the stored `mpo_` ids.
- E4 `PlannedOrder` adds `part_number`, `llc`, `supply_node` and `directives: {alt_key: primary-equivalent qty}`;
  conversion re-explodes with `order_components(ds, item, qty, on=max(start, as_of), serial=segment.serial_from,
  directives={(order_key, k): v for k, v in po.directives.items()}, order_key=po.order_key)`, which reproduces the
  alternate substitution of the run.
- E5 Directive keys: `(order_key, alt_key)` moves to the group's first alternate (8.9 as written);
  `(order_key, f"{alt_key}:{alt_priority}")` targets a later alternate (needed when the first alternate's free stock
  is not enough). `alt_key` = `alt_group`, or `"<phantom item id>>" + alt_group` for a group inside a phantom.
  `ComponentNeed` adds `alt_key`.
- E6 `ItemPlan` adds `supplier_id`, `ItemStats` (all `mfg_mrp_item_results` numbers), `LeadTimeInfo.receiving_days`;
  `MrpException` adds `part_number`; `DemandProjection` carries the order fields, `node`, `label`, `extra_index`;
  `MrpSummary` adds `requirements` and `demand_outside_horizon`. `timings_ms` is **not** in the engine summary (it
  would break byte-identical determinism); B adds load/compute/store timings when storing.
- E7 `TimelineEvent.kind` adds `"expiry"` (unpegged remainder of a lot leaves the projected stock on its expiry
  date).
- E8 `preflight(snapshot, params) -> list[issue dict]` is public; `run_mrp` raises `MrpPreflightError(issues)` /
  `MrpTooLarge(limit)`; Gate 1 stays with B. `item_plan_from_jsonable` rebuilds an `ItemPlan` from its JSON (for
  `mrp_store` detail JSON and the views).

**Interpretations:**
- I1 Effective need date `max(need_date, as_of)` is used for the allocation phases (phase 1 `avail <= need'`,
  expiry `expires_on > need'`, phase 2 `need' < avail < protect_until`), for "covered late" (MRP_SHORTAGE, item
  `short_qty`, alternates trigger, MRP_EXPEDITE). Without it a requirement due in the past (WO started last week,
  past-due demand) could not use stock on hand in phase 1 and, when `protect_until == as_of`, never at all.
  `Requirement.late_days`/`Peg.late_days` stay literal (`projected - need_date`).
- I2 Demand status: `past_due` if `due_date < as_of` (takes precedence), else `late` if `late_days > 0`, else
  `on_time`; a past-due line raises MRP_DEMAND_PAST_DUE only (not also MRP_DEMAND_LATE).
- I3 Rank of an existing WO's component requirement with no pegs on the WO: `(1, wo.priority, wo.due_date,
  wo.number, 0)`. Rank of a dependent requirement = the minimum rank of the requirements pegged to its parent order
  (ties: lowest node); planned orders formed only from safety stock pass the safety-stock rank down.
- I4 Safety stock: residual planned at `protect_until`; its requirement and pegs never late; MRP_BELOW_SAFETY_STOCK
  when the on-time existing coverage (`avail <= as_of`) is below the safety stock. Safety stock is a target level,
  not a timeline event.
- I5 Lot sizing: `lot_for_lot` is `period` with a 1-day window; each later residual first consumes surplus of
  earlier orders of its segment group (creation order), then forms a new group. Residual grouping is by segment key
  (None is its own group). Segment of a child requirement = parent order's segment only when the child is a
  serialized make item. Serial boundaries for the split come from all released serial-specific BOMs/routings of the
  item; count-UoM pieces use cumulative half-up rounding so the pieces sum to the residual.
- I6 Make supply forward pass uses the MLT computed for the order's start (planned) or for the WO's open qty at
  `max(start, as_of)` with the WO's `routing_id` (existing WOs).
- I7 Limiting path ties: latest projected supply, then lowest supply node; latest component `satisfied_date`, then
  larger late days, then part number. A planned buy whose order date is in the past stops with `start_in_past`.
- I8 Extra demand is planned regardless of the horizon. Demand outside the horizon is counted after the
  filters/exclusions.
- I9 MRP_EXPEDITE / MRP_DEFER ignore safety-stock pegs for the expedite date (DEFER uses all pegs); MRP_REDUCE
  rounds the pegged qty with the item's lot chain (MOQ -> multiple -> pack -> integer); MRP_MERGE_INTO_PR treats
  "no supplier" on both sides as the same supplier.
- I10 Phantoms are expanded inside `order_components` (structure cached per resolved BOM/routing/phantom BOMs). A
  phantom without an effective BOM stays a component (warning `WO_NO_EFFECTIVE_BOM`) so P7 still holds.

### 22.WP-B API, access, import/export

### 22.WP-C UI

### 22.WP-D QA and acceptance
