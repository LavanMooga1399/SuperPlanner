# SuperPlanner M1 - Manufacturing plant and product setup (design)

> **Historical note (PostgreSQL-only release):** "file-DB" below refers to the embedded file database of earlier
> releases. It was removed; SuperPlanner now runs on PostgreSQL only (see `docs/DEPLOY.md`, Changelog, and
> `docs/ARCHITECTURE.md` section 25). Statements about file-DB behaviour describe the past.

Status: design for build. Phase M1 of `docs/MANUFACTURING-GAP-ANALYSIS.md` (cited "GA n"): the "define first, then
run" master data (GA 4.1, 4.1a steps 1, 2 and 5, 4.3) that MRP (M2) and manufacturing scheduling (M3) will read.
Conventions not restated here come from `docs/ARCHITECTURE.md` ("A n") and `docs/PHASE2B.md` ("B n"): error
envelope (A 14), If-Match/ETag (A 14.3), central ownership (B 4.7), Alembic rules (B 3.2-3.6), dual-database tests
(B 3.6). Where this document and those disagree for anything under `/api/v1/mfg`, `superplanner/mfg` or
`frontend/src/mfg`, this document wins. Developers record interpretations only in section 17 (own subsection).

## Table of contents

0. Summary of decisions
1. Scope, principles, out of scope
2. Package layout and dependency rules
3. Domain model (Pydantic) - common types, units, entities
4. Semantics: effectivity, versions, alternates, phantoms, quantities, operation time, shift windows
5. Pure computations (function signatures)
6. Database schema (migration `0003_mfg`)
7. Data-health check ("Gate 1") - code list
8. Import / export (templates, column specs, flow, limits)
9. REST API (`/api/v1/mfg`)
10. Sample datasets (small, medium, Kavach-like)
11. Frontend (routes, components, virtualisation)
12. Performance targets
13. Work packages and file ownership
14. Changes to existing code and existing tests
15. Test strategy and acceptance (Gate 1 exit criteria)
16. Deferred items and plug-in points for M2/M3
Review notes (team lead)
17. Implementation notes (one subsection per work package)

---

## 0. Summary of decisions

1. **New pure package `superplanner/mfg`** (no FastAPI/SQLAlchemy imports) holds models, units, BOM/routing/calendar
   computations, the health check, import/export logic and sample generators. Everything operates on an in-memory
   snapshot `MfgDataset` (or a level-wise `BomIndex`); the DB layer (`api/mfg`) only loads snapshots and writes rows.
2. **Relational tables, not JSON documents**, for master data (18 tables `mfg_*`, Alembic revision `0003_mfg`):
   where-used, natural-key upserts and 5,000+ line BOMs need indexes and row-level edits. JSON columns only for
   small embedded values (shift patterns, eligible families, attributes, shift-name lists) and import staging.
3. **Every `mfg_*` table is owned** (`OwnedMixin`, `owner_id`), including child/link tables. This deviates from B 3.3
   ("children carry no owner_id") on purpose: where-used and import queries hit child tables directly, and the
   central `with_loader_criteria` filter then protects them with no per-query code. Natural keys are unique per
   owner (`(owner_id, part_number)` etc.).
4. **Optimistic concurrency** with `row_version` on every editable row (ETag `"<row_version>"`, If-Match required on
   PUT/DELETE/actions, 428/412 as A 14). BOMs and routings are edited as **documents** (header + all lines / all
   operations in one PUT), so a 300-line BOM is validated and versioned atomically.
5. **Versioned BOMs/routings with effectivity**: status `draft -> released -> obsolete`; released documents are
   read-only, changes go through "copy to new version" and "release (supersede previous)". Effectivity by date
   (`[from, to)`, plant-local dates) and optional unit-serial range; serial-specific documents override generic ones.
6. **Cycles are rejected on every write** (draft or released, import or UI); all other relational rules follow
   the engine's layering (A 3.0): drafts may be incomplete, **release** enforces document rules, and the
   **health check** reports everything with stable `MFG_*` codes, severities and plain-language fixes; errors block
   M2/M3 runs (`report.ok == false`).
7. **One interchange format, `MfgBundle`** (sheets of rows keyed by natural keys/codes): xlsx/CSV/zip import,
   export, and the sample loaders all go through the same `plan_import -> apply` path, so upserts are idempotent and
   samples are guaranteed importable. Import is staged in the DB (`mfg_imports`): upload -> mapping -> preview ->
   commit in one transaction (all-or-nothing, zero row errors required).
8. **xlsx library: `openpyxl==3.1.5` + `et-xmlfile==2.0.0` + `defusedxml==0.7.1`** (pure Python, Python 3.12/3.13,
   Windows; defusedxml is picked up by openpyxl automatically against XML bombs). Measured here: 5,000-row write
   0.57 s, read 0.65 s. Uploads are raw request bodies (no `python-multipart`), bounded by `MAX_BODY_BYTES` plus
   our own zip/row limits.
9. **Time model = the engine's** (A 4): plant has a fixed `utc_offset`, shift templates use wall-clock `HH:MM`,
   night shifts cross midnight and belong to the day they start, no DST. Line windows per kind (`base`, `optional`)
   come from line-level assignments if the line has any of that kind on that date, else from its group; optional
   time never overlaps base; exceptions remove time from both.
10. **Frontend: new area `/mfg`** (`frontend/src/mfg/**`) with an in-house fixed-row-height virtual table (no new npm
   packages) used by the items list, the BOM tree (server supplies `subtree_end` per row so collapse is O(1) per
   row) and BOM line editing. Sample datasets small (~10 parts), medium (~200 parts) and a fictional "Kavach-like"
   loco train-protection unit (~2,400 BOM lines, 5 levels, 20 stages, ~45 lines) are deterministic and loadable via
   API/UI. No existing behaviour changes; existing tests change only for route registration and the schema head.

---

## 1. Scope, principles, out of scope

**In M1:** items; versioned multi-level BOMs (alternates, phantoms, scrap, ref designators, effectivity);
versioned routings (alternate routings, repeated stages, setup/run/queue/move/wait, attended/unattended,
transfer batch, yield, skill, tooling, inspection gate, interruptible); plant (settings, work-center groups, lines
with speed/capacity/eligibility/setup family, shift templates, shift assignments base/optional with cost and limits,
calendar exceptions); skills, operators, tooling pools; utilities (operation time, rolled-up quantities, effective
BOM/routing, line windows); data-health check; xlsx/CSV/zip import and export; REST API; UI; sample data.

**Principles (binding):**
- P1 Domain-neutral core: `mfg` models discrete manufacturing generically (items, structures, stages, shifts).
  Electronics specifics (SMT, MSL, reference designators semantics, stencils) are data: codes, families, free
  `attributes`, sample content. No branch in core code on a family or group name.
- P2 Feasibility first: health-check errors are hard blockers for later runs; they are never down-graded into
  warnings or penalties. Warnings never block.
- P3 Pure core, thin DB/API: every computation is a pure function over a snapshot, unit-tested without a database.
- P4 No N+1: every read endpoint has a fixed or depth-bounded number of SQL statements (section 12).
- P5 Determinism: same data -> same explosion order, same health report order, same export bytes (except the xlsx
  zip timestamps, see 8.7), same sample bundles.
- P6 Units: quantities are floats in the item's unit of measure; times are float minutes in master data,
  converted to integer engine minutes only by M3 (helper provided: `to_engine_minutes = ceil(x - 1e-9)`).

**Out of M1 (M2/M3+):** inventory, lots/serial genealogy, demand, MRP/netting/pegging, purchase requests/orders,
work orders, scheduling, capacity load charts, setup matrices, operator leave, organisations/roles, ERP connectors.
Section 16 shows where each plugs in.

---

## 2. Package layout and dependency rules

```
backend/superplanner/mfg/                 pure; may import pydantic, stdlib, openpyxl (io only). Never fastapi/sqlalchemy.
  __init__.py        public API re-exports (section 5)
  limits.py          all numeric limits (no new Settings fields)
  model.py           common types + entity input/record models (section 3)
  units.py           UoM table, aliases, convert()
  dataset.py         MfgDataset snapshot, BomIndex, ParentIndex, canonical ordering helpers, fingerprint()
  bom.py             effective_bom, explode, where_used, find_cycles, would_create_cycle, refdes parsing
  routing.py         effective_routings, primary_routing, operation_minutes, lot_inputs, cumulative_yield
  calendar.py        expand_template_week, line_windows, group_capacity, validate_template
  health.py          run_health_check (Gate 1), CODES table
  release.py         bom_release_issues / routing_release_issues / validate_bom_document / validate_routing_document
                     (pure; used by the API services AND by io.plan for `release: true`) (review R3)
  bundle.py          MfgBundle type, SHEETS spec (names, columns, key columns, order of 8.2), dataset_to_bundle,
                     bundle_to_dataset (strict, for canonical bundles: samples, tests), canonical_json
  messages.py        message + fix templates for health codes (WP-A)
  io/
    messages.py      import row-error messages (WP-B; split from messages.py so the two owners never share a file)
    spec.py          header synonyms, cell parsers per column type (uses bundle.SHEETS)
    read.py          xlsx/csv/zip -> RawSheets (with limits)
    mapping.py       suggest_mapping(raw, spec)
    plan.py          plan_import(bundle, dataset, options) -> ImportPlan (pure diff by natural keys)
    export.py        bundle.dataset_to_bundle -> xlsx/zip bytes; blank templates
  samples/
    __init__.py      SAMPLES registry, build(sample_id) -> MfgBundle
    common.py        deterministic helpers (seeded random.Random, never iterates sets)
    small.py  medium.py  kavach.py
backend/superplanner/api/mfg/
  __init__.py
  db_models.py       ORM rows (section 6)                                   [WP-A]
  repo.py            snapshot loaders, row getters, plant lock (section 6.4) [WP-A]
  schemas.py         API wrappers (pagination, actions, import)              [WP-B]
  services/          items.py boms.py routings.py plant.py resources.py health.py imports.py samples.py  [WP-B]
  writer.py          apply ImportPlan with ORM add/update/delete             [WP-B]
  router.py          APIRouter(prefix="/mfg") (section 9)                   [WP-B]
frontend/src/mfg/**                                                         [WP-C]
```

Rules: `superplanner.mfg` never imports `superplanner.api` or `superplanner.engine` (M3 will add an adapter
`mfg -> engine`); `api/mfg` imports `superplanner.mfg` and existing `api` helpers (`errors`, `db`, `context`,
`services.problem_service.audit/parse_if_match`, `db.locks`). Frontend `src/mfg` imports only exported names from
`src/api/client.ts` (`API_BASE`, `ApiError`, `looksLikeProxyFailure`, `networkError`, `parseEtag`) and
`src/auth/authFetch.ts`, plus shared presentational components (`components/Banner`, `Icon`, `Dialog`,
`ConfirmDialog`, `StatusBadge`, `Inputs`) without editing them.

`superplanner/mfg/limits.py` (constants; referenced by tests):

| Constant | Value | Meaning |
|---|---|---|
| `MAX_ITEMS` | 50,000 | items per owner (create beyond -> 422 `MFG_LIMIT`) |
| `MAX_BOMS` / `MAX_ROUTINGS` | 20,000 / 20,000 | documents per owner (all statuses) |
| `MAX_BOM_LINES_TOTAL` / `MAX_OPERATIONS_TOTAL` | 500,000 / 200,000 | per owner |
| `MAX_GROUPS` / `MAX_LINES` | 500 / 2,000 | per owner |
| `MAX_SHIFT_TEMPLATES` / `MAX_SHIFT_ASSIGNMENTS` / `MAX_CALENDAR_EXCEPTIONS` | 200 / 5,000 / 10,000 | per owner |
| `MAX_SKILLS` / `MAX_OPERATORS` / `MAX_TOOL_POOLS` | 500 / 5,000 / 10,000 | per owner |
| `MAX_BOM_LINES_PER_BOM` | 2,000 | lines in one BOM document |
| `MAX_OPERATIONS_PER_ROUTING` | 200 | |
| `MAX_BOM_DEPTH` | 20 | explosion/where-used levels (deeper -> `MFG_BOM_TOO_DEEP`) |
| `MAX_EXPLOSION_ROWS` | 20,000 | indented rows in one explosion or indented where-used response (generation stops at the first row over the limit) |
| `REFDES_MAX_RANGE` | 10,000 | a designator range wider than this is an invalid token (never expanded) |
| `SQL_IN_CHUNK` | 2,000 | ids per `IN (...)` list in level-wise loaders |
| `SKILL_COVERAGE_TOLERANCE_MINUTES` | 15 | uncovered pieces shorter than this are ignored by `MFG_SKILL_NOT_ON_SHIFT` |
| `MAX_WINDOW_RANGE_DAYS` | 62 | `/lines/{id}/windows` range |
| `MAX_HEALTH_ISSUES` | 1,000 | issues returned (counts stay complete) |
| `PAGE_DEFAULT` / `PAGE_MAX` | 50 / 200 | list pagination |
| `IMPORT_MAX_ROWS_PER_SHEET` | 50,000 | non-empty data rows |
| `IMPORT_MAX_SCANNED_ROWS` | 60,000 | rows iterated per sheet incl. empty filler rows (openpyxl pads row gaps); `iter_rows(max_row=..., max_col=IMPORT_MAX_COLUMNS + 1)` |
| `IMPORT_MAX_ROWS_TOTAL` | 100,000 | |
| `IMPORT_MAX_COLUMNS` | 100 | |
| `IMPORT_MAX_CELL_CHARS` | 4,000 | |
| `IMPORT_MAX_UNCOMPRESSED_BYTES` | 64 MiB | sum of declared zip member sizes (xlsx and zip); `zipfile` never returns more than the declared size of a member, so the declared sum bounds decompression |
| `IMPORT_MAX_ZIP_MEMBERS` | 200 | |
| `IMPORT_MAX_COMPRESSION_RATIO` | 200 | per member |
| `IMPORT_MAX_STAGED_BYTES` | 32 MiB | `len(json.dumps(sheets))` stored in `mfg_imports.sheets` |
| `IMPORT_TTL_HOURS` | 24 | staged import lifetime |
| `IMPORT_MAX_OPEN_PER_OWNER` | 5 | oldest uncommitted session deleted beyond this |
| `MAX_ROW_ERRORS_RETURNED` | 500 | preview row errors returned (count complete) |
| `MAX_ATTR_INT` | 2^53 - 1 | integer `attributes` values (fix round, D1) |
| `MIN_DATE` / `MAX_DATE` | 1900-01-01 / 2199-12-31 | every date/datetime input (bodies, query parameters, import cells); dates, so not in `/meta` `limits` (fix round, F6) |

---

## 3. Domain model (`superplanner/mfg/model.py`)

Pydantic v2, `model_config = ConfigDict(extra="forbid")` on every model. JSON field names = attribute names. Two
model kinds per entity: `<Entity>Input` (what POST/PUT accept) and `<Entity>Record` (Input fields + `id`,
`row_version`, `created_at`, `updated_at` + read-only denormalised fields). TypeScript mirrors in
`frontend/src/mfg/api/types.ts`.

### 3.1 Common types

```python
EntityId    = Annotated[str, StringConstraints(pattern=r"^[a-z]{3}_[0-9a-f]{32}$")]   # new_id("itm_") etc.
Code        = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,31}$")]
PartNumber  = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64,
                                               pattern=r"^[^\x00-\x1f\x7f]+$")]        # case-sensitive, exact
Revision    = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_.\-]{1,16}$")]
FindNumber  = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_.\-]{1,16}$")]
Name        = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text500     = Annotated[str, StringConstraints(max_length=500)]          # default ""
HHMM        = engine HHMM (A 3.1): "00:00".."23:59" or "24:00"
Weekday     = Literal["mon","tue","wed","thu","fri","sat","sun"]
UtcOffset   = Annotated[str, StringConstraints(pattern=r"^[+-](0\d|1[0-4]):[0-5]\d$")]
Qty         = Annotated[float, Field(gt=0, le=1_000_000)]
NonNegQty   = Annotated[float, Field(ge=0, le=1_000_000_000)]
Minutes     = Annotated[float, Field(ge=0, le=100_000)]                    # float minutes
Pct         = Annotated[float, Field(ge=0, lt=100)]                        # scrap
YieldPct    = Annotated[float, Field(gt=0, le=100)]
Status      = Literal["draft","released","obsolete"]
MakeBuy     = Literal["make","buy","phantom"]
AttrValue   = str | int | float | bool                                     # str max 500; float finite (no NaN/inf),
                                                                           # |int| <= MAX_ATTR_INT (fix round D1)
Attributes  = dict[Code, AttrValue]                                        # max 50 keys
PlanDate    = date in MIN_DATE..MAX_DATE; PlanDateTime = aware datetime, local and UTC date in range (fix round F6)
```
Id prefixes: `itm_` item, `bom_` BOM, `bml_` BOM line, `rtg_` routing, `opr_` operation, `wcg_` group, `lin_` line,
`sht_` shift template, `sha_` shift assignment, `cex_` calendar exception, `skl_` skill, `emp_` operator,
`tlp_` tool pool, `imp_` import, `plt_` plant. Text fields reject control characters U+0000-U+001F except in
`Text500`/`note`/`description` where `\n` and `\t` are allowed.

### 3.2 Units of measure (`units.py`)

Fixed table (user-defined units deferred). Base unit per dimension has factor 1.

| Code | Dimension | Factor to base | Import aliases (case-insensitive, trimmed, trailing "." ignored) |
|---|---|---|---|
| `EA` | count | 1 | EA, EACH, PC, PCS, PCE, NO, NOS, NUM, UNIT, UNITS |
| `M` | length | 1 | M, MTR, MTRS, METER, METRE, METERS, METRES |
| `CM` | length | 0.01 | CM |
| `MM` | length | 0.001 | MM |
| `KG` | mass | 1 | KG, KGS |
| `G` | mass | 0.001 | G, GM, GMS, GRAM |
| `L` | volume | 1 | L, LT, LTR, LITRE, LITER |
| `ML` | volume | 0.001 | ML |
| `M2` | area | 1 | M2, SQM, SQ.M |

```python
UOM_CODES: tuple[str, ...]                         # order above
def dimension(code: str) -> str
def normalize_uom(text: str) -> str | None         # alias -> code (import only; API accepts codes only)
def convert(qty: float, from_uom: str, to_uom: str) -> float   # raises UnitMismatch if dimensions differ
def is_count(code: str) -> bool
```

### 3.3 Plant settings

One row per owner, created lazily by the first mfg **write** (`repo.lock_plant`, 6.1). Reads never insert
(review R6): `GET /plant`, `load_dataset` and health use `repo.plant_or_default(s)`, which returns the stored row or
an unsaved default record with `id = null` and `row_version = 0` (ETag `"0"`); `PUT /plant` with `If-Match: "0"`
creates it. So a user who only looked at the Manufacturing area owns no mfg rows (needed by `reassign-owner`, 14.1).

Non-input column `data_version` (int, starts 0): incremented once by every committed mfg write transaction (any
table), under the plant lock. It is a cheap "has anything changed" token: import commit uses it to skip re-planning
inside the lock (8.1), and `GET /summary` and `GET /health` return it.

| Field | Type | Default | Rules |
|---|---|---|---|
| `name` | Name | `"Plant"` | |
| `utc_offset` | UtcOffset | `"+00:00"` | wall-clock offset of all shift times, exceptions and effectivity dates |
| `planning_horizon_days` | int 7..730 | 90 | default horizon for health-check capacity/effectivity checks |
| `currency` | str 0..8 | `""` | display only (optional-shift and line costs) |
| `attributes` | Attributes | `{}` | |

### 3.4 Item

| Field | Type | Default | Rules / meaning |
|---|---|---|---|
| `part_number` | PartNumber | required | unique per owner (409 `MFG_DUPLICATE_KEY`) |
| `revision` | Revision | `"A"` | current engineering revision (informational; BOM/routing carry their own `revision`) |
| `description` | str 0..500 | `""` | |
| `uom` | UoM code | `"EA"` | stocking unit; all item quantities are in it |
| `make_buy` | MakeBuy | required | `phantom` = transient make item, blown through by explosion, never stocked, no routing |
| `family` | Code \| None | None | grouping for line eligibility and filters (e.g. `PCBA-HDI`, `HARNESS`) |
| `setup_family` | Code \| None | None | changeover class for M3 setup matrices; None = `family` |
| `lead_time_days` | int 0..730 \| None | None | procurement lead time (buy). `None` on a buy item = health error. Optional fixed planning lead time on make items (M2 uses routing time when None) |
| `receiving_days` | int 0..60 | 0 | goods-in inspection before stock is usable (M2) |
| `lot_rule` | `Literal["lot_for_lot","fixed"]` | `"lot_for_lot"` | |
| `fixed_lot_qty` | Qty \| None | None | required iff `lot_rule == "fixed"` (422) |
| `min_order_qty` | NonNegQty | 0 | 0 = none |
| `order_multiple` | NonNegQty | 0 | 0 = none |
| `safety_stock` | NonNegQty | 0 | |
| `serialized` | bool | false | units carry serial numbers (enables serial effectivity on this item's documents) |
| `shelf_life_days` | int 1..36500 \| None | None | |
| `handling_class` | Code \| None | None | free code, e.g. `MSL3`, `ESD`, `HAZ` |
| `handling_note` | Text500 | `""` | e.g. "bake 24 h at 125 C if floor life exceeded" |
| `attributes` | Attributes | `{}` | e.g. `{"manufacturer": "...", "mpn": "..."}` |
| `active` | bool | true | inactive items stay referenced but are flagged when used in effective documents |

Record extras (read-only): `has_bom` (any non-obsolete BOM), `has_routing`, `used_in_count` (distinct parent items
over non-obsolete BOMs).

Model-level rules (422): `fixed_lot_qty` iff `lot_rule == "fixed"`; `uom` in `UOM_CODES`.

### 3.5 BOM (header) and BOM line

`BomInput`:

| Field | Type | Default | Rules |
|---|---|---|---|
| `item_id` | EntityId | required (POST only; immutable) | must be a `make` or `phantom` item (422 `MFG_ITEM_NOT_MAKE`) |
| `revision` | Revision | item's `revision` at create | |
| `version` | int 1..9999 | max existing for (item, revision) + 1 | natural key `(item, revision, version)` unique (409 `MFG_DUPLICATE_KEY`) |
| `effective_from` | date \| None | None | inclusive, plant-local; None = unbounded past |
| `effective_to` | date \| None | None | exclusive; None = open-ended; `from < to` (422) |
| `serial_from` | int 1..10^9 \| None | None | unit-serial effectivity, inclusive; both or neither (422); only if item `serialized` (422 `MFG_SERIAL_NOT_ALLOWED`) |
| `serial_to` | int \| None | None | `serial_from <= serial_to` |
| `note` | Text500 | `""` | |
| `lines` | list[BomLineInput] | `[]` | max `MAX_BOM_LINES_PER_BOM` |

`status` is not an input; it changes only through the actions in 9.5.

`BomLineInput`:

| Field | Type | Default | Rules |
|---|---|---|---|
| `id` | EntityId \| None | None | PUT: existing line of this BOM to keep (else 422); omitted = new line |
| `find_number` | FindNumber | required | position number |
| `child_item_id` | EntityId | required | `!= parent` and no cycle (422 `MFG_BOM_CYCLE`) |
| `qty_per` | Qty | required | per 1 unit of the parent, in `uom` |
| `uom` | UoM code | child's `uom` (filled by service when omitted) | must have the same dimension as the child's uom at release / health (`MFG_UOM_MISMATCH`) |
| `scrap_pct` | Pct | 0 | component scrap factor, additive: required = qty_per x (1 + scrap/100) |
| `ref_designators` | str 0..4000 | `""` | e.g. `"R1, R2, R5-R9"` (comma/space separated, ranges `X5-X9` or `X5-9`) |
| `alt_group` | FindNumber \| None | None | lines with the same `alt_group` in one BOM are alternatives for one position |
| `alt_priority` | int 1..99 | 1 | 1 = primary; higher = less preferred |
| `operation_seq` | int 1..9999 \| None | None | routing operation of the parent that consumes this component; None = first operation |
| `note` | Text500 | `""` | |

Document rules checked on every write (422 `VALIDATION_ERROR`, `loc` = `["body","lines",i,field]`): duplicate
`(find_number, child_item_id)`; within an `alt_group` duplicate child; `alt_group` set but only one line in the group
is allowed in drafts (warning in health). Unknown `child_item_id` -> 422 `MFG_UNKNOWN_REFERENCE`.

`BomRecord` = BomInput fields + `id`, `status`, `row_version`, `released_at`, `obsoleted_at`, `created_at`,
`updated_at`, `item: ItemRef`, and lines as `BomLineRecord` = line fields + `id`, `child: ItemRef`, where
`ItemRef = {id, part_number, revision, description, uom, make_buy, active}`. Lines are returned sorted by
`(natural(find_number), alt_group or "", alt_priority, child part_number)`; `natural(fn)` = `(0, int(fn), "")` if
`fn` is all digits else `(1, 0, fn)`.

### 3.6 Routing and operation

`RoutingInput`:

| Field | Type | Default | Rules |
|---|---|---|---|
| `item_id` | EntityId | required (immutable) | `make` item only (422 `MFG_ITEM_NOT_MAKE`) |
| `revision` | Revision | item's revision | |
| `code` | Code | `"STD"` | distinguishes alternate routings |
| `version` | int 1..9999 | max for (item, revision, code) + 1 | key `(item, revision, code, version)` unique |
| `priority` | int 1..9 | 1 | 1 = primary; alternates 2..9 (M3 may choose them) |
| `effective_from`, `effective_to`, `serial_from`, `serial_to` | as BOM | | |
| `note` | Text500 | `""` | |
| `operations` | list[OperationInput] | `[]` | max 200; `seq` unique (422) |

`OperationInput`:

| Field | Type | Default | Rules / meaning |
|---|---|---|---|
| `id` | EntityId \| None | None | as BOM lines |
| `seq` | int 1..9999 | required | order of execution (ascending) |
| `name` | str 1..100 | required | e.g. "SMT top", "SMT bottom" (repeated stage = same `group_id`, different `seq`) |
| `description` | Text500 | `""` | |
| `group_id` | EntityId | required | work-center group (stage); the scheduler picks the line |
| `setup_minutes` | Minutes | 0 | per lot per line (once per split in M3) |
| `run_minutes` | Minutes | 0 | per `run_per` load at speed factor 1.0 |
| `run_per` | `Literal["unit","panel","batch"]` | `"unit"` | |
| `units_per_panel` | int 1..10,000 \| None | None | required iff `run_per == "panel"` |
| `units_per_batch` | int 1..100,000 \| None | None | required iff `run_per == "batch"` (oven/rack load) |
| `queue_minutes` | Minutes | 0 | passive wait before the operation (no resource) |
| `move_minutes` | Minutes | 0 | passive transfer after the operation (no resource) |
| `wait_minutes` | Minutes | 0 | passive wait after the operation, e.g. cool-down (no resource) |
| `labor` | `Literal["attended","unattended"]` | `"attended"` | unattended = line busy, no crew during run (cure, burn-in); setup is always attended |
| `crew_size` | int 0..50 | 1 | operators needed while attended; 0 allowed only if `labor == "unattended"` (422) |
| `skill_id` | EntityId \| None | None | required skill of the crew |
| `tools` | list[{`tool_pool_id`: EntityId, `qty`: int 1..100}] | `[]` | tooling held for the whole operation; unique pool (422) |
| `transfer_batch` | int 1..100,000 \| None | None | units moved on to the next operation before the lot finishes (M3 overlap) |
| `yield_pct` | YieldPct | 100 | good output / input |
| `inspection_gate` | bool | false | quality gate (M4 actuals; M3 may not overlap across a gate) |
| `interruptible` | bool | true | may pause at shift ends/breaks and resume; false = must fit one continuous window (reflow profile, cure, burn-in) |

`RoutingRecord`: + `id`, `status`, `row_version`, timestamps, `item: ItemRef`; `OperationRecord` adds `id`,
`group: {id, code, name}`, `skill: {id, code, name} | None`, `tools[i].tool_pool: {id, code, name}`. Operations
sorted by `seq`.

### 3.7 Work-center group (stage) and line

`GroupInput`: `code: Code` (unique per owner), `name: Name`, `description: Text500 = ""`, `kind: Code | None`
(informational, e.g. `machine`, `bench`, `test`, `oven`), `active: bool = true`.

`LineInput`:

| Field | Type | Default | Rules |
|---|---|---|---|
| `group_id` | EntityId | required | |
| `code` | Code | required | unique per owner (across groups) |
| `name` | Name | required | |
| `speed_factor` | float 0.05..20 | 1.0 | run time is divided by it (0.7 = 30% slower line) |
| `parallel_capacity` | int 1..100 | 1 | operations it can run at once (oven holding 4 batches, rack of 8) |
| `setup_family` | Code \| None | None | lines with the same value share one changeover matrix in M3 |
| `eligible_families` | list[Code] (unique, max 50) | `[]` | |
| `eligible_item_ids` | list[EntityId] (unique, max 500) | `[]` | eligible iff both lists empty, or item.family in families, or item id in items |
| `cost_per_hour` | float 0..10^6 | 0 | base running cost (M3) |
| `active` | bool | true | |

`LineRecord` adds `group: {id, code, name}` and `eligible_items: list[ItemRef]`.

### 3.8 Shift template, assignment, calendar exception

`ShiftTemplateInput`: `code: Code` (unique), `name: Name`, `description: Text500 = ""`,
`shifts: list[ShiftDef]` (1..10).

`ShiftDef`:

| Field | Type | Rules |
|---|---|---|
| `name` | str 1..32, unique in template | e.g. `"Day"`, `"A"`, `"Night"` |
| `days` | list[Weekday], 1..7, unique | days the shift **starts** on |
| `start` | HHMM, not `"24:00"` | |
| `end` | HHMM | `end > start`: same day; `end <= start` or `"24:00"`: ends next day / at midnight; `end == start`: 24 h shift |
| `breaks` | list[{`name`: str 0..32, `start`: HHMM, `end`: HHMM}] max 10 | inside the shift span (a break time earlier than `start` on a midnight-crossing shift is on the next day); no overlaps; length > 0 |

Template rules (422 `MFG_SHIFT_INVALID`, `loc` names the shift): shifts of one template must not overlap on a
reference week (Mon 00:00 .. Mon 00:00 + 7 days, with wrap-around: a Sunday night shift overlaps Monday morning
shifts); breaks inside their shift. Touching shifts (A 06-14, B 14-22) are fine and merge into one window.

`ShiftAssignmentInput`:

| Field | Type | Default | Rules |
|---|---|---|---|
| `shift_template_id` | EntityId | required | |
| `target_type` | `Literal["group","line"]` | required | |
| `group_id` / `line_id` | EntityId \| None | | exactly the one matching `target_type` (422) |
| `kind` | `Literal["base","optional"]` | `"base"` | base = always available; optional = overtime / extra shift opened by the planner |
| `shift_names` | list[str] | `[]` | subset of the template's shift names (422 if unknown); empty = all |
| `effective_from` | date | required | inclusive (shift start date) |
| `effective_to` | date \| None | None | exclusive |
| `cost_per_hour` | float 0..10^6 \| None | None | optional only (422 on base); extra cost per open hour |
| `max_hours_per_week` | float 0..168 \| None | None | optional only; ISO week Mon-Sun |
| `note` | Text500 | `""` | |

`CalendarExceptionInput`: `scope: Literal["plant","group","line"]`, `group_id`/`line_id` (matching scope, none for
plant), `kind: Literal["holiday","shutdown","maintenance"]`, `start: AwareDatetime`, `end: AwareDatetime`
(`start < end`, max 366 days), `label: str 0..100 = ""`. Datetimes are stored as given (UTC on write) and returned
in the plant offset. All three kinds remove time (base and optional); `kind` is informational in M1.

### 3.9 Skill, operator, tool pool

- `SkillInput`: `code: Code` (unique), `name: Name`, `description: Text500 = ""`.
- `OperatorInput`: `code: Code` (unique, e.g. badge number), `name: Name`, `skill_ids: list[EntityId]` (unique),
  `shift_template_id: EntityId | None`, `shift_names: list[str] = []` (subset of that template's shifts; empty =
  all), `home_group_id: EntityId | None`, `active: bool = true`. Anonymised names in samples.
- `ToolPoolInput`: `code: Code` (unique), `name: Name`, `kind: Code | None` (e.g. `stencil`, `fixture`, `jig`,
  `applicator`), `quantity: int 0..10,000` (identical units available), `note: Text500 = ""`.

Records add `id`, `row_version`, timestamps; operator records add `skills: list[{id, code, name}]`.

---

## 4. Semantics

### 4.1 Effectivity and the "effective document"

A document (BOM or routing) is **effective** for `(on: date, serial: int | None)` iff `status == "released"` and
`(effective_from is None or effective_from <= on) and (effective_to is None or on < effective_to)` and
(`serial_from is None` (generic) **or** (`serial is not None and serial_from <= serial <= serial_to`)).

- `effective_bom(item, on, serial)`: among effective BOMs of the item, serial-specific ones win over generic ones;
  if still more than one -> the one with the highest `(effective_from or date.min, version)` and the health issue
  `MFG_BOM_EFFECTIVITY_OVERLAP` exists. Returns None when nothing is effective.
- `effective_routings(item, on, serial)`: same per `priority`; result sorted by `priority`; `primary_routing` =
  first. Overlap = two effective routings with the same priority and the same specificity.
- Overlap definition (both kinds): two released documents of the same item (and for routings the same `priority`)
  overlap iff their date windows intersect and either both are generic or both are serial-specific with
  intersecting serial ranges. Generic + serial-specific never overlap (override by design).
- Revisions: a BOM's `revision` is a label for engineering traceability; effectivity is decided by dates/serials
  across all revisions of the item (rev B normally starts where rev A ends).

### 4.2 Versions and statuses

- `draft`: editable by PUT; never effective; included in cycle checks and where-used (`include=all`).
- `released`: read-only (PUT/DELETE -> 409 `MFG_RELEASED_READONLY`). Only `effective_to` can change, and only via
  the release action of a successor (`supersede_previous`) or `POST .../obsolete`.
- `obsolete`: read-only, not effective, excluded from cycle checks and where-used. Can be deleted.
- `copy`: creates a new draft with `version = max + 1` (same item/revision/code unless overridden) and copies of
  all lines/operations (new ids), `effective_from = None`, `effective_to = None`.
- Release (BOM): 422 `MFG_RELEASE_BLOCKED` with `details.issues` (same shape as health issues, section 7) if the
  document has: no lines (`MFG_BOM_EMPTY`), a cycle, uom mismatch, alternates without exactly one primary,
  duplicate priorities, inactive components, serial range on a non-serialized item, or an overlap with another
  released BOM after applying `supersede_previous`. Supersede: every other released BOM of the item that overlaps
  (per 4.1) and starts before the new `effective_from` gets `effective_to = new.effective_from`; one that starts on
  or after it is not touched and therefore blocks with `MFG_BOM_EFFECTIVITY_OVERLAP`. Release requires a non-null
  `effective_from` when `supersede_previous` is true (422).
- Release (routing): blocked by no operations (`MFG_ROUTING_NO_OPERATIONS`), `operation_seq` references from the
  item's effective BOM lines to missing seqs (warning only, not blocking), overlap (same priority).
- Every write to header or lines/operations increments the header's `row_version`.

### 4.3 Alternates and phantoms

- Alternate group = lines in one BOM sharing `alt_group`. Exactly one line with `alt_priority == 1` (primary), all
  priorities distinct. Explosion and roll-ups use the **primary** only; alternates are attached to the primary row
  as `alternates[]` (sorted by priority). Auto-selection when the primary is short is M2.
- Alternate routings = routings with `priority > 1`; M1 shows them and computes their time previews; M3 chooses.
- Phantom item (`make_buy == "phantom"`): has a BOM, never a routing (health warning if it has one; it is ignored),
  yield 1. Indented explosion shows the phantom row (`is_phantom: true`) with its children below; summarized
  explosion omits phantom rows (their children roll up into the phantom's parent).

### 4.4 Quantities: rolled-up BOM quantities with scrap and yield

Notation for a parent `P` with primary effective routing operations `o_1..o_n` (ascending seq) and yields
`y_i = yield_pct_i / 100` (no routing, buy, phantom: n = 0):

- Cumulative yield from operation k to the end: `Y_k = prod_{i >= k} y_i` (`Y_{n+1} = 1`).
- To deliver `Q` good units of `P`, operation k must process `Q / Y_k` units (continuous form).
- A BOM line of `P` consumed at operation `k` (`operation_seq`, None or not found -> k = 1):
  `required(line) = (Q / Y_k) x qty_per x (1 + scrap_pct / 100)`, converted from `line.uom` to the child's uom.
- Explosion applies this recursively: a child's `Q` is its `required` quantity. `include_scrap=false` /
  `include_yield=false` drop the respective factors. **No rounding** inside explosions (rounding is lot sizing,
  M2); outputs are rounded to 6 decimals for display only (`round(x, 6)`), computations keep full floats.
- Integer lot inputs (time preview, M3): for count-uom items, `lot_inputs(ops, Q)` walks backwards
  `in_n = ceil(Q / y_n - 1e-9)`, `in_{k} = ceil(in_{k+1} / y_k - 1e-9)`; for other uoms the continuous form.
  Output of operation k = input of k+1 (last: `Q`).

Worked example (test vector T-Q1): PCB `P` with ops 10 SMT (y 100%), 20 ICT (y 97%), 30 FCT (y 98%); line
`C` qty_per 4, scrap 2%, consumed at op 10; `Q = 100`. `Y_1 = 0.97 x 0.98 = 0.9506`;
`required = 100 / 0.9506 x 4 x 1.02 = 429.2026...` -> displayed `429.202609`. `lot_inputs`: FCT
`ceil(100/0.98) = 103`, ICT `ceil(103/0.97) = 107`, SMT `ceil(107/1.0) = 107`.

### 4.5 Operation time

```
loads(op, qty) = qty                               if run_per == "unit"
               = ceil(qty / units_per_panel - 1e-9) if run_per == "panel"
               = ceil(qty / units_per_batch - 1e-9) if run_per == "batch"
setup = op.setup_minutes                           (not scaled by speed)
run   = op.run_minutes x loads(op, qty) / line.speed_factor
total = setup + run                                 (queue/move/wait are reported separately, never added)
```
`operation_minutes(op, qty, speed_factor=1.0) -> OpTime(setup, run, total, loads)`; float minutes; M3 converts with
`to_engine_minutes`. Worked example (T-T1): SMT top, setup 45, run 1.2 per panel, 4 units/panel, qty 250 on a line
with speed 0.7: loads = 63, run = 1.2 x 63 / 0.7 = 108.0, total = 153.0.

### 4.6 Shift windows of a line

Input: plant `utc_offset`; templates; assignments; exceptions; a line; local date range `[d0, d1)`.

1. Day attribution: a shift instance belongs to the local date `d` on which it starts (`d.weekday()` in
   `ShiftDef.days`). Instances of dates `d0 - 1` .. `d1 - 1` are generated (to catch night shifts running into `d0`),
   then clipped to `[d0 00:00, d1 00:00)` local.
2. Instance interval: `[d + start, d + end)`, with `end` on `d + 1` when `end <= start` or `end == "24:00"`; 24 h
   when `start == end`. Breaks are subtracted (break times before `start` lie on `d + 1`).
3. Source per kind and date: for `kind` in (`base`, `optional`), if the line has at least one assignment of that kind
   effective on `d` (`effective_from <= d < effective_to`), only the line's assignments of that kind are used for
   `d`; else the group's assignments of that kind. `shift_names` filters the template's shifts.
4. Base windows = union of base instances. Optional windows = union of optional instances **minus base**; where two
   optional assignments overlap, the time is attributed to the lower `cost_per_hour` (None counts as 0), ties by
   assignment `effective_from`, then id.
5. Exceptions with scope `plant`, the line's group, or the line are subtracted from both kinds.
6. Merge touching windows of the same kind and same attributed assignment (so a 3-shift pattern or a 24 h template
   is one continuous window across midnight). Sort by start.

Output `Window(start: datetime (aware, plant offset), end, kind, assignment_id, shift_label: "REG/Day",
cost_per_hour: float | None)`. Operators use the same expansion for their template/shift names (M3).
`group_capacity(ds, group_id, d0, d1) -> {"base_minutes", "optional_minutes", "lines": {line_id: {...}}}` =
sum over active lines of window minutes x `parallel_capacity`.

Test vectors (calendar tests must include all): T-C1 regular Mon-Sat 09:00-18:00 lunch 13:00-13:45 -> 8 h 15 min
per weekday, Sun empty; T-C2 extended = base REG + optional EVE 18:00-22:00 -> optional 4 h touching base, not
merged across kinds; T-C3 three shifts 06-14, 14-22, 22-06 Mon-Sat -> one window Mon 06:00 .. Sun 06:00; T-C4
line has its own optional assignment, group base still applies (per-kind rule); T-C5 holiday on Tue removes
Tue 00:00-24:00 incl. the Mon night shift's tail after midnight; T-C6 optional overlapping base is cut; T-C7 two
optional assignments with costs 400 and 300 overlapping -> overlap attributed to 300; T-C8 range starting on a
Tuesday includes Monday night's 00:00-06:00 tail.

---

## 5. Pure computations (`superplanner/mfg/__init__.py` exports)

```python
# dataset.py
@dataclass
class MfgDataset:                       # full snapshot of one owner, built by api.mfg.repo or from a bundle
    plant: PlantRecord
    items: dict[str, ItemRecord]
    boms: dict[str, BomRecord]          # with lines
    routings: dict[str, RoutingRecord]  # with operations
    groups: dict[str, GroupRecord]
    lines: dict[str, LineRecord]
    shift_templates: dict[str, ShiftTemplateRecord]
    shift_assignments: dict[str, ShiftAssignmentRecord]
    calendar_exceptions: dict[str, CalendarExceptionRecord]
    skills: dict[str, SkillRecord]
    operators: dict[str, OperatorRecord]
    tool_pools: dict[str, ToolPoolRecord]
    # derived, built lazily: boms_by_item, routings_by_item, lines_by_group, parents_of (child -> bom line refs)

class BomIndex:                         # what explode needs; built from a dataset or level-wise by the repo
    def __init__(self, items: dict[str, ItemRecord], effective: dict[str, BomRecord | None],
                 primary_ops: dict[str, list[OperationRecord]]): ...
    @classmethod
    def from_dataset(cls, ds: MfgDataset, on: date, serial: int | None = None) -> "BomIndex"

class ParentIndex:                      # what where_used needs
    def __init__(self, items: dict[str, ItemRecord], parent_lines: dict[str, list[tuple[BomRecord, BomLineRecord]]]): ...
    @classmethod
    def from_dataset(cls, ds: MfgDataset, on: date | None, include: Literal["effective","all"]) -> "ParentIndex"

def fingerprint(ds: MfgDataset) -> str  # sha256(canonical_json(dataset_to_bundle(ds))): natural keys, no ids,
                                        # timestamps or row_version -> M2/M3 runs record which master data they used

# bundle.py
def dataset_to_bundle(ds: MfgDataset) -> MfgBundle          # every sheet, rows sorted by natural key
def bundle_to_dataset(bundle: MfgBundle) -> MfgDataset      # strict (raises BundleError on any invalid row);
                                                            # ids derived deterministically from natural keys
def canonical_json(bundle: MfgBundle) -> bytes              # sort_keys, separators (',', ':'), floats repr

# bom.py
def effective_bom(ds: MfgDataset, item_id: str, on: date, serial: int | None = None) -> BomRecord | None
def explode(index: BomIndex, item_id: str, *, qty: float = 1.0, mode: Literal["indented","summarized"] = "indented",
            include_scrap: bool = True, include_yield: bool = True, max_depth: int | None = None) -> Explosion
def where_used(index: ParentIndex, item_id: str, *, mode: Literal["single","indented"] = "single") -> WhereUsed
def bom_edges(ds: MfgDataset) -> list[tuple[str, str]]     # (parent_item, child_item) over draft+released BOMs
def find_cycles(edges: Iterable[tuple[str, str]]) -> list[list[str]]      # iterative Tarjan; each SCC rotated to
                                                                          # start at its smallest part number
def would_create_cycle(edges, new_edges) -> list[str] | None             # path parent -> ... -> parent
def refdes_count(text: str) -> tuple[int, list[str]]                     # "R1, R2, R5-R9" -> (7, []); ranges are
                                                                          # counted arithmetically, never expanded;
                                                                          # a range wider than REFDES_MAX_RANGE or a
                                                                          # bad token goes to the invalid list
def validate_bom_document(ds, item_id: str, lines: list[BomLineInput]) -> list[dict]   # (release.py) the 3.5
                                                                          # document rules, A 14 error dicts with loc

# routing.py
def effective_routings(ds, item_id, on, serial=None) -> list[RoutingRecord]
def primary_routing(ds, item_id, on, serial=None) -> RoutingRecord | None
def operation_minutes(op: OperationRecord, qty: float, speed_factor: float = 1.0) -> OpTime
def lot_inputs(ops: list[OperationRecord], qty: float, count_uom: bool) -> list[float]   # input per op
def cumulative_yield(ops: list[OperationRecord], from_seq: int | None = None) -> float
def eligible_lines(ds, group_id: str, item: ItemRecord) -> list[LineRecord]             # active, eligible, by code
def to_engine_minutes(x: float) -> int

# calendar.py
def validate_template(t: ShiftTemplateInput) -> list[dict]      # pydantic-style error dicts (empty = ok)
def expand_template_week(t: ShiftTemplateInput) -> list[WeekWindow]   # minutes from Mon 00:00, may exceed 10080
def line_windows(ds, line_id, d0: date, d1: date, *, kinds=("base","optional")) -> list[Window]
def operator_windows(ds, operator_id, d0: date, d1: date) -> list[Window]   # shift SPANS of the operator's template
                                                                # / shift names (breaks NOT removed: crews stagger
                                                                # breaks), clipped to [d0, d1); no exceptions applied
def group_capacity(ds, group_id, d0, d1) -> dict

# release.py (review R3)
def bom_release_issues(ds, bom_id: str, effective_from: date | None, supersede_previous: bool
                       ) -> tuple[list[HealthIssue], list[dict]]      # (blocking issues, superseded [{id, version,
                                                                      # effective_to}]); 4.2 rules
def routing_release_issues(ds, routing_id: str, effective_from: date | None, supersede_previous: bool
                           ) -> tuple[list[HealthIssue], list[dict]]

# health.py
def run_health_check(ds: MfgDataset, as_of: date, horizon_days: int) -> HealthReport
```

Complexity rules (review R8, binding for WP-A): `explode(mode="indented")` raises `ExplosionTooLarge` as soon as
row `MAX_EXPLOSION_ROWS + 1` would be produced (never builds the full path list first; a 20-level "diamond" BOM has
2^20 paths). `explode(mode="summarized")` never enumerates paths: it propagates quantities over the effective
BOM DAG in topological order (O(items + edges)), and computes `min_level`/`max_level` (shortest/longest path) and
`occurrences` (path count, Python int) by the same DP, so `mode=summarized` is always a working fallback.
`where_used(mode="indented")` has the same row limit. Health reachability and depth checks use DAG traversal /
DP, never path enumeration.

`Explosion` (also the API response body, section 9.4): `item_id, part_number, on, serial, qty, mode, rows, totals,
warnings`. Indented `rows` are depth-first in BOM line order (3.5 sort), each row:

| Field | Meaning |
|---|---|
| `row` | 0-based index; `parent_row` (None for root); `subtree_end` = first row index after this row's subtree |
| `level` | 0 = root |
| `line_id`, `bom_id` | the line that brought the item in (None at root); `bom_id` = this item's own effective BOM (None if none) |
| `item_id`, `part_number`, `revision`, `description`, `make_buy`, `uom`, `family`, `lead_time_days`, `active` | of the item |
| `find_number`, `ref_designators`, `qty_per`, `line_uom`, `scrap_pct`, `operation_seq` | of the line |
| `extended_qty` | required quantity for the requested root `qty` (4.4), item uom |
| `alternates` | `[{line_id, item_id, part_number, qty_per, line_uom, alt_priority}]` |
| `is_phantom`, `has_children`, `is_shared` | `is_shared`: item occurs under more than one distinct parent in this explosion |
| `routing_id` | primary effective routing (make items) or None |

Summarized `rows`: one per distinct non-phantom item except the root: `item_id, part_number, description,
make_buy, uom, total_qty, min_level, max_level, occurrences, lead_time_days`, sorted by `(min_level, part_number)`.
`totals = {rows, distinct_items, max_level, make_items, buy_items, phantom_items}`. `warnings`: `[{code, message,
item_id}]` with `MFG_NO_EFFECTIVE_BOM` (make/phantom item without an effective BOM at `on`), `MFG_BOM_CYCLE`
(defensive: branch cut), `MFG_BOM_TOO_DEEP`. More than `MAX_EXPLOSION_ROWS` rows -> `ExplosionTooLarge` (API 422
`MFG_EXPLOSION_TOO_LARGE`, suggest `mode=summarized` or `max_depth`).

`WhereUsed`: `rows: [{row, level (1 = direct parent), parent_row, item_id, part_number, revision, description,
make_buy, bom_id, bom_revision, bom_version, bom_status, line_id, find_number, qty_per, line_uom, is_top}]`,
depth-first, parents sorted by part number; `is_top` = the parent is used nowhere. `totals = {rows, top_items}`.
`mode=single` returns only level-1 rows (`parent_row` null). Over `MAX_EXPLOSION_ROWS` indented rows -> 422
`MFG_EXPLOSION_TOO_LARGE` (suggest `mode=single`).

---

## 6. Database schema (`api/mfg/db_models.py`, migration `0003_mfg`)

### 6.1 Conventions

- All 18 tables are prefixed `mfg_`, mix in `OwnedMixin` (`owner_id String(64) NOT NULL`, FK
  `fk_<table>_owner_id_users` -> `users.id` ON DELETE RESTRICT) and live on the shared `Base`. Primary keys
  `id String(64)` (`new_id(prefix)`), except the two link tables (composite PK).
- Common columns on editable rows: `row_version Integer NOT NULL` (starts 1), `created_at`, `updated_at`
  (`DateTime(timezone=True)`, UTC). No server defaults (all values set by the ORM), so migration and metadata
  compare without `server_default` noise.
- Types: quantities and minutes `sa.Double()`; dates `sa.Date()`; booleans `sa.Boolean()`; JSON via the existing
  `JsonType` (JSONB on Postgres) only for `mfg_shift_templates.shifts`, `mfg_lines.eligible_families`,
  `*.attributes`, `mfg_operators.shift_names`, `mfg_shift_assignments.shift_names` and the `mfg_imports` payloads.
  Strings bounded as in section 3 (`part_number` 64, codes 32, `description` 500, `ref_designators` 4000).
- FKs are named by the metadata naming convention (`fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`);
  unique constraints and indexes are named explicitly as below. Migration `0003_mfg` (down_revision
  `0002_phase2b`) uses literal `op.create_table` definitions (B 3.2 frozen-migration rule) and drops all 18 tables in
  reverse order in `downgrade()`. `superplanner/migrate.py` `HEAD = "0003_mfg"`. The existing test
  `compare_metadata(upgrade head) == Base.metadata` must stay empty on both dialects.
- Writes use ORM `s.add`/attribute updates only (B 3.5.6: no Core `insert()`, which would bypass the owner stamp).
  Bulk import uses `s.add_all` (SQLAlchemy 2.1.4 batches these as `insertmanyvalues`). The writer adds rows **per
  sheet in dependency order with an explicit `s.flush()` after each sheet** (relationships are `lazy="raise"` and
  the unit of work must not be relied on to order FK-dependent inserts without relationship cascades).
- Deletes: single rows via `s.delete(row)`; many rows (replace_children, reset, sample `replace`) via ORM-enabled
  `s.execute(delete(Model).where(...).execution_options(synchronize_session=False))`, children before parents.
  ORM `delete()` statements pass `do_orm_execute` and get the owner criteria (proven by the 2b ownership probes,
  PLAN-PHASE2B Q1-9; re-proven for mfg by `test_mfg_isolation.py`). All mfg relationships declare
  `passive_deletes=True` so ON DELETE CASCADE / SET NULL is done by the database, never by lazy loads.
- **Ids are always `new_id(prefix)`** when rows are written. The deterministic ids of `bundle_to_dataset` (prefix +
  first 32 hex of sha256 of the natural key) exist only in pure in-memory datasets and are never written: ids are
  global primary keys, so two users loading the same sample would otherwise collide (review R5).
- Every mfg write transaction first locks the owner's plant row (`repo.lock_plant(s)`), then bumps
  `mfg_plant.data_version`. `lock_plant`: `SELECT ... FOR NO KEY UPDATE` on the owner's plant row; if absent,
  insert the default row inside a savepoint (`s.begin_nested()`); on a unique violation of `uq_mfg_plant_owner`
  (a concurrent first write, Postgres) roll back the savepoint and select again with the lock. On file-DB the write
  guard serialises. This is the per-owner mutex that keeps cycle checks, natural-key checks and imports consistent
  across processes. Lock order: plant -> document header -> children. Runs inside `ctx.write_guard()` like
  existing services.
- Lock waits: Postgres sessions run with `lock_timeout=10000` (B 3.1). A write that waits longer for the plant lock
  (e.g. behind a large import commit) fails with `LockNotAvailable` (SQLSTATE 55P03); the mfg services map it to
  409 `MFG_BUSY` "Another change to your manufacturing data is still being saved. Try again in a moment." with
  `Retry-After: 5`, never 500. Long pure work (file parsing, `plan_import`) is done **outside** the write
  transaction wherever possible (8.1), so the lock is held only for the writes. On file-DB the process-wide write
  guard and `busy_timeout=30000` make other writers wait instead.

### 6.2 Tables

| Table | Columns (besides id, owner_id, row_version, created_at, updated_at) | Constraints / indexes |
|---|---|---|
| `mfg_plant` | name S200, utc_offset S6, planning_horizon_days Int, currency S8, attributes JSON, data_version Int | `uq_mfg_plant_owner (owner_id)` |
| `mfg_items` | part_number S64, revision S16, description S500, uom S8, make_buy S8, family S32 N, setup_family S32 N, lead_time_days Int N, receiving_days Int, lot_rule S16, fixed_lot_qty Dbl N, min_order_qty Dbl, order_multiple Dbl, safety_stock Dbl, serialized Bool, shelf_life_days Int N, handling_class S32 N, handling_note S500, attributes JSON, active Bool | `uq_mfg_items_owner_pn (owner_id, part_number)`; `ix_mfg_items_owner_family (owner_id, family)`; `ix_mfg_items_owner_updated (owner_id, updated_at, id)` |
| `mfg_boms` | item_id FK mfg_items RESTRICT, revision S16, version Int, status S16, effective_from Date N, effective_to Date N, serial_from BigInt N, serial_to BigInt N, note S500, released_at DT N, obsoleted_at DT N | `uq_mfg_boms_key (owner_id, item_id, revision, version)`; `ix_mfg_boms_item_status (item_id, status)` |
| `mfg_bom_lines` | bom_id FK mfg_boms CASCADE, find_number S16, child_item_id FK mfg_items RESTRICT, qty_per Dbl, uom S8, scrap_pct Dbl, ref_designators S4000, alt_group S16 N, alt_priority Int, operation_seq Int N, note S500 | `uq_mfg_bom_lines_key (bom_id, find_number, child_item_id)`; `ix_mfg_bom_lines_child (child_item_id)` (where-used and the FK RESTRICT check on item delete, which Postgres runs without `owner_id`) |
| `mfg_routings` | item_id FK mfg_items RESTRICT, revision S16, code S32, version Int, priority Int, status S16, effective_from/to Date N, serial_from/to BigInt N, note S500, released_at, obsoleted_at | `uq_mfg_routings_key (owner_id, item_id, revision, code, version)`; `ix_mfg_routings_item_status (item_id, status)` |
| `mfg_operations` | routing_id FK mfg_routings CASCADE, seq Int, name S100, description S500, group_id FK mfg_groups RESTRICT, setup_minutes Dbl, run_minutes Dbl, run_per S8, units_per_panel Int N, units_per_batch Int N, queue_minutes Dbl, move_minutes Dbl, wait_minutes Dbl, labor S16, crew_size Int, skill_id FK mfg_skills RESTRICT N, transfer_batch Int N, yield_pct Dbl, inspection_gate Bool, interruptible Bool | `uq_mfg_operations_seq (routing_id, seq)`; `ix_mfg_operations_group (group_id)`; `ix_mfg_operations_skill (skill_id)`; `ix_mfg_operations_owner (owner_id)` |
| `mfg_operation_tools` | operation_id FK mfg_operations CASCADE, tool_pool_id FK mfg_tool_pools RESTRICT, qty Int | `uq_mfg_operation_tools (operation_id, tool_pool_id)`; `ix_mfg_operation_tools_pool (tool_pool_id)`; `ix_mfg_operation_tools_owner (owner_id)` |
| `mfg_groups` | code S32, name S200, description S500, kind S32 N, active Bool | `uq_mfg_groups_code (owner_id, code)` |
| `mfg_lines` | group_id FK mfg_groups RESTRICT, code S32, name S200, speed_factor Dbl, parallel_capacity Int, setup_family S32 N, eligible_families JSON, cost_per_hour Dbl, active Bool | `uq_mfg_lines_code (owner_id, code)`; `ix_mfg_lines_group (group_id)` |
| `mfg_line_items` | PK (line_id FK mfg_lines CASCADE, item_id FK mfg_items CASCADE), owner_id | `ix_mfg_line_items_item (item_id)`; `ix_mfg_line_items_owner (owner_id)` |
| `mfg_shift_templates` | code S32, name S200, description S500, shifts JSON | `uq_mfg_shift_templates_code (owner_id, code)` |
| `mfg_shift_assignments` | shift_template_id FK RESTRICT, target_type S8, group_id FK mfg_groups CASCADE N, line_id FK mfg_lines CASCADE N, kind S16, shift_names JSON, effective_from Date, effective_to Date N, cost_per_hour Dbl N, max_hours_per_week Dbl N, note S500 | CHECK `ck_mfg_shift_assignments_target ((group_id IS NULL) <> (line_id IS NULL))`; `ix_mfg_shift_assignments_group (group_id)`, `_line (line_id)`, `_template (shift_template_id)`, `_owner (owner_id)` |
| `mfg_calendar_exceptions` | scope S8, group_id FK CASCADE N, line_id FK CASCADE N, kind S16, start_at DT, end_at DT, label S100 | `ix_mfg_calendar_exceptions_owner_start (owner_id, start_at)`; `_group`, `_line` |
| `mfg_skills` | code S32, name S200, description S500 | `uq_mfg_skills_code (owner_id, code)` |
| `mfg_operators` | code S32, name S200, shift_template_id FK RESTRICT N, shift_names JSON, home_group_id FK mfg_groups SET NULL N, active Bool | `uq_mfg_operators_code (owner_id, code)`; `ix_mfg_operators_template (shift_template_id)`; `ix_mfg_operators_home_group (home_group_id)` |
| `mfg_operator_skills` | PK (operator_id FK mfg_operators CASCADE, skill_id FK mfg_skills CASCADE), owner_id | `ix_mfg_operator_skills_skill (skill_id)`; `ix_mfg_operator_skills_owner (owner_id)` |
| `mfg_tool_pools` | code S32, name S200, kind S32 N, quantity Int, note S500 | `uq_mfg_tool_pools_code (owner_id, code)` |
| `mfg_imports` | filename S200, format S8 (`xlsx`/`csv`/`zip`), status S16 (`uploaded`/`mapped`/`committed`), sheets JSON, mapping JSON N, preview JSON N, result JSON N, expires_at DT, committed_at DT N | `ix_mfg_imports_owner_created (owner_id, created_at)`; `ix_mfg_imports_expires (expires_at)` |

(S = String(n), N = nullable, Dbl = Double, DT = DateTime(timezone=True), JSON = `JsonType`; link tables have no
`row_version`/timestamps.)

Index rules (review R7): every mfg table has an index whose **leading** column is `owner_id` (unique key or
`ix_<table>_owner`), because `load_dataset`, reset and `manage.py reassign-owner` filter by owner only; every FK
column has an index whose leading column is that FK (Postgres runs the RESTRICT / CASCADE / SET NULL checks without
the owner). Every constraint and index name is <= 63 characters (Postgres truncates silently; the longest generated
FK name, `fk_mfg_shift_assignments_shift_template_id_mfg_shift_templates`, is 62) - asserted by a WP-A test.
Tables are created in FK order: plant, items, groups, skills, tool_pools, shift_templates, lines, line_items, boms,
bom_lines, routings, operations, operation_tools, shift_assignments, calendar_exceptions, operators,
operator_skills, imports; `downgrade()` drops them in reverse. `0003_mfg` only creates tables (no batch rebuild of
existing tables), so it is safe on file-DB with `foreign_keys=OFF` and on Postgres needs only a brief lock on
`users` for the owner FKs.

`effective_to`/`serial_*` invariants are enforced in services and models, not by CHECK constraints (except the
assignment target check above), so error messages stay in the API envelope.

### 6.3 Delete behaviour (services check first and answer 409 `MFG_IN_USE` with counts; FKs are the backstop)

| Delete | Blocked by (409 `MFG_IN_USE`, `details.references` = `{"bom_lines": n, ...}`) | Cascades |
|---|---|---|
| item | used as child in any BOM line; has any BOM or routing | line eligibility rows |
| BOM | status `released` (409 `MFG_RELEASED_READONLY`) | lines |
| routing | status `released` | operations, operation tools |
| group | has lines; used by operations | assignments, exceptions of the group |
| line | - | eligibility, assignments, exceptions of the line |
| shift template | used by assignments or operators | - |
| skill | used by operations | operator skill links |
| operator | - | skill links |
| tool pool | used by operations | - |

### 6.4 Repository (`api/mfg/repo.py`, WP-A) - the only DB reads used by services

```python
def plant_or_default(s: Session) -> PlantRecord               # read path: stored row or unsaved default (3.3)
def lock_plant(s: Session) -> MfgPlantRow                     # write path: lock, create in a savepoint if absent,
                                                              # bump data_version (6.1)
def get_row(s, model, row_id: str, *, what: str, lock=False) -> Any        # not_found(what, id) -> 404
def load_dataset(s: Session) -> MfgDataset                     # <= 18 SELECTs, one per table, no lazy loads
def load_bom_index_down(s, root_item_id: str, on: date, serial: int | None) -> BomIndex
    # level-wise BFS over levels 0..L: per level <= 3 SELECTs (items IN (...) incl. alternate children, which are
    # loaded but not descended into; released BOM headers of the make/phantom items of the level; lines of the
    # effective BOMs only), plus 2 SELECTs (released routings of all make items seen; operations of their primary
    # routings) and 1 for the plant. Items already loaded are never re-selected. IN lists chunked by SQL_IN_CHUNK.
    # Statement count <= 3 x (L + 1) + 3 + (extra chunks).
def load_parent_index(s, item_id: str, on: date | None, include: str) -> ParentIndex   # level-wise up, <= 3 x levels + 1
def bom_edge_list(s) -> list[tuple[str, str]]                  # one SELECT (join headers status != obsolete)
def to_record(row) -> <Entity>Record                            # model_construct (rows were validated on write);
                                                                # datetimes through `as_utc` (file-DB returns naive)
```
Relationships are declared with `lazy="raise"` on all mfg ORM rows so an accidental N+1 fails tests instead of
silently issuing queries.

---

## 7. Data-health check ("Gate 1", `mfg/health.py`)

### 7.1 Report shape

```json
{
  "ok": false,
  "as_of": "2026-11-02", "horizon_days": 90, "fingerprint": "6f1c...e2",
  "counts": {"error": 7, "warning": 0, "info": 1},
  "by_code": {"MFG_MAKE_NO_ROUTING": 1, "MFG_GROUP_NO_SHIFT": 1, "MFG_BUY_NO_LEAD_TIME": 5, "MFG_LONG_LEAD_TIME": 1},
  "truncated": false,
  "issues": [
    {"code": "MFG_MAKE_NO_ROUTING", "severity": "error",
     "message": "Make item KV-HAR-L03 \"Brake interface harness\" has no released routing effective on 2 Nov 2026 (it has a draft routing STD v1).",
     "fix": "Open the routing STD v1 and release it, or add a routing for this item.",
     "entity": {"type": "item", "id": "itm_9c...", "label": "KV-HAR-L03"},
     "related": [{"type": "routing", "id": "rtg_41...", "label": "STD v1 (draft)"}],
     "link": "/mfg/items/itm_9c.../routing?routing=rtg_41...",
     "field": null}
  ]
}
```
- `ok` = no issue with severity `error`. Order: severity (error, warning, info), then code (table order below),
  then entity label, then entity id (deterministic). At most `MAX_HEALTH_ISSUES` issues returned; `counts`/`by_code`
  are always complete; `truncated` tells whether issues were cut.
- `link` is computed by the server from `entity` (table 11.3), so the UI never derives routes itself.
- Inactive items and inactive groups/lines are skipped as subjects (except the explicit inactive-use codes).
- "In use" means: reachable from an end item over the **union graph** of the released BOMs whose effectivity
  window intersects `[as_of, as_of + horizon_days)` (one DAG traversal, review R8). This over-approximates exact
  per-date reachability only when two documents that are never effective at the same time chain together; the
  error then asks for data that is not strictly needed, which is the safe direction (a missing routing is never
  missed). Checks of an item's own documents (overlap, gap, "has an effective routing") evaluate that item's
  effective set at `as_of` and at each of its own effectivity boundaries inside the horizon (so a routing ending in
  3 weeks is caught); cost O(documents), not O(dates x graph).
- The report also carries `data_version` (3.3) so the UI can tell whether a shown report is stale.
- Gate 1 for M2/M3: `run_health_check(...).ok` must be true before a run is created (M2 enforces it with 422
  `MFG_DATA_HEALTH_FAILED` and the report in `details`).

### 7.2 Code list (stable; messages/fixes in `mfg/messages.py`, wording may improve, codes may not change)

| # | Code | Sev. | Entity | Condition | Fix (plain language) |
|---|---|---|---|---|---|
| 1 | `MFG_BOM_CYCLE` | error | item (first of cycle) | SCC of size > 1 or self-loop in draft+released BOM edges; message lists `A -> B -> C -> A` | Remove one of these BOM lines so no item contains itself. |
| 2 | `MFG_BOM_TOO_DEEP` | error | item | explosion depth > `MAX_BOM_DEPTH` | Check the structure for unintended nesting. |
| 3 | `MFG_MAKE_NO_ROUTING` | error | item | active make item in use (or end item) without a released primary routing effective at some date of the horizon; message says if a draft exists | Release the draft routing, or add a routing. |
| 4 | `MFG_ROUTING_NO_OPERATIONS` | error | routing | released routing with zero operations | Add operations, or make it obsolete. |
| 5 | `MFG_GROUP_NO_LINE` | error | operation | operation's group has no active line | Add a line to the stage or activate one. |
| 6 | `MFG_NO_ELIGIBLE_LINE` | error | operation | no active line of the group is eligible for the routing's item (family/item lists) | Add the item or its family to a line's eligibility, or clear the lists. |
| 7 | `MFG_GROUP_NO_SHIFT` | error | group | group used by an effective operation has zero base and zero optional minutes in the horizon over its eligible lines | Assign a shift template to the stage or its lines. |
| 8 | `MFG_GROUP_OPTIONAL_ONLY` | warning | group | used group has optional but no base capacity | Add a base shift; optional shifts are only opened when needed. |
| 9 | `MFG_UNINTERRUPTIBLE_TOO_LONG` | error | operation | `interruptible == false` and, for **every** active eligible line L of the group, setup + run for one load (qty = 1) at L's speed exceeds L's longest continuous window in the horizon (base and optional windows merged when touching, regardless of kind/assignment) | Run it on a line with a longer shift (e.g. 24 h), shorten it, or allow interruption. |
| 10 | `MFG_UNINTERRUPTIBLE_LOT_TOO_LONG` | warning | operation | same, for qty = the item's `min_order_qty` or `fixed_lot_qty` (when > 1) | Lots this size will need splitting or a longer window. |
| 11 | `MFG_BUY_NO_LEAD_TIME` | error | item | any active buy item with `lead_time_days is None` | Enter the supplier lead time (0 if stocked locally). |
| 12 | `MFG_UOM_MISMATCH` | error | bom_line | line uom dimension differs from the child item's uom dimension (e.g. M vs EA) | Use a unit of the same kind as the item's unit (EA, or M/CM/MM ...). |
| 13 | `MFG_FRACTIONAL_SERIALIZED` | error | bom_line | serialized child with non-integer `qty_per` | Serialized parts must be used in whole numbers. |
| 14 | `MFG_BOM_EFFECTIVITY_OVERLAP` | error | bom | two released BOMs of an item overlap (4.1) | Set an end date on the older BOM or release the new one with "supersede". |
| 15 | `MFG_ROUTING_EFFECTIVITY_OVERLAP` | error | routing | two released routings, same item and priority, overlap | As above, or give the alternate a different priority. |
| 16 | `MFG_ALT_NO_PRIMARY` | error | bom_line | alternate group without a priority-1 line | Mark one alternative as priority 1. |
| 17 | `MFG_ALT_DUPLICATE_PRIORITY` | error | bom_line | two lines of a group share a priority | Give each alternative its own priority. |
| 18 | `MFG_INACTIVE_COMPONENT` | error | bom_line | effective released BOM uses an inactive item | Activate the item, replace it, or release a new BOM version. |
| 19 | `MFG_PHANTOM_NO_BOM` | error | item | phantom item in use without an effective BOM | Add and release a BOM, or change the item to make/buy. |
| 20 | `MFG_SKILL_NO_OPERATOR` | error | operation | required skill held by no active operator | Add the skill to an operator. |
| 21 | `MFG_TOOL_SHORT` | error | operation | tool pool `quantity` < required `qty` (incl. 0) | Increase the tool quantity or reduce the need. |
| 22 | `MFG_ASSIGNMENT_INACTIVE_TARGET` | warning | shift_assignment | assignment targets an inactive line or group (no effect) | Delete the assignment or activate the target. |
| 23 | `MFG_OPERATION_SEQ_REF` | warning | bom_line | `operation_seq` not found in the parent's primary routing (first operation used) | Pick an existing operation number. |
| 24 | `MFG_SKILL_NOT_ON_SHIFT` | warning | skill (related: line, group) | coverage by **time subtraction over the real horizon dates** (decision in Review notes R1): for each (skill, line) where the skill is required by an in-use operation with `crew_size > 0` on the line's group and the line is active and eligible for at least one of those operations' items: `uncovered = line_windows(base + optional) - union(operator_windows of active operators holding the skill)` over `[as_of, as_of + horizon_days)`; pieces shorter than `SKILL_COVERAGE_TOLERANCE_MINUTES` are dropped; one issue per (skill, line) if anything remains. Message groups the uncovered pieces by (shift label, kind, local start-end) with their weekdays, at most 3 patterns + "and n more", e.g. "No operator with skill COATING is on shift for line COAT-1 during EVE/Evening (optional) Mon-Sat 18:00-22:00." | Put a qualified operator on that shift (or on a template covering it, e.g. an extended-hours template for overtime crews). |
| 25 | `MFG_LINE_NO_SHIFT` | warning | line | active line of a used group has no windows in the horizon (others have) | Assign a shift to the line or its stage. |
| 26 | `MFG_OPTIONAL_NO_COST` | warning | shift_assignment | optional assignment without `cost_per_hour` | Enter the overtime cost so the planner can weigh it. |
| 27 | `MFG_OPTIONAL_OVERLAPS_BASE` | warning | shift_assignment | optional windows fully covered by base windows | Remove it or change its shifts. |
| 28 | `MFG_MAKE_NO_BOM` | warning | item | active make item in use without an effective BOM | Add a BOM if the item consumes materials. |
| 29 | `MFG_BOM_EFFECTIVITY_GAP` | warning | item | generic released BOMs of the item leave a gap between consecutive windows inside the horizon | Extend the earlier BOM or start the later one earlier. |
| 30 | `MFG_ROUTING_EFFECTIVITY_GAP` | warning | item | as above for primary routings | |
| 31 | `MFG_BUY_WITH_BOM` | warning | item | buy item has non-obsolete BOMs (ignored) | Change it to make, or make the BOM obsolete. |
| 32 | `MFG_BUY_WITH_ROUTING` | warning | item | buy/phantom item has non-obsolete routings (ignored) | |
| 33 | `MFG_ALT_SINGLE` | warning | bom_line | alternate group with one line | Add the alternative or clear the group. |
| 34 | `MFG_REFDES_COUNT` | warning | bom_line | count-uom line with non-empty `ref_designators` whose parsed count != `qty_per` | Correct the quantity or the reference designators. |
| 35 | `MFG_ZERO_TIME_OPERATION` | warning | operation | `setup_minutes == 0 and run_minutes == 0` | Enter setup/run times. |
| 36 | `MFG_LOW_YIELD` | warning | routing | cumulative yield < 50% | Check yield percentages. |
| 37 | `MFG_ORPHAN_ITEM` | warning | item | active item neither used in any non-obsolete BOM nor parent of one, and not a make item with a routing (i.e. not an end item) | Use it in a BOM or deactivate it. |
| 38 | `MFG_DUPLICATE_COMPONENT` | info | bom_line | same child on several lines (different find numbers) of one BOM, not alternates | Fine if intended (different positions). |
| 39 | `MFG_LONG_LEAD_TIME` | info | item | buy item `lead_time_days > 180` | Long-lead part: order early (M2 will flag it). |
| 40 | `MFG_DRAFT_ONLY` | info | item | item has draft documents but nothing released | Release when ready. |
| 41 | `MFG_ASSIGNMENT_UNKNOWN_SHIFT` | error | shift_assignment (related: template) | not expired assignment whose `shift_names` name a shift its template does not have (fix round F2) | Pick shifts of the template, or add the shifts back to the template. |
| 42 | `MFG_OPERATOR_UNKNOWN_SHIFT` | error | operator (related: template) | active operator whose `shift_names` name a shift its template does not have (fix round F2) | As above. |
| 43 | `MFG_SERIAL_NOT_ALLOWED` | error | item (related + link: the document) | released, not expired BOM/routing with a serial range on an active, non-serialized item (fix round F5; was release-only) | Remove the serial range or mark the item as serialized. |

Codes 41-43 are listed in `messages.CODES` after `MFG_TOOL_SHORT` (errors before warnings); `HEALTH_CODES` = every
code except the release-only `MFG_BOM_EMPTY`. Their entity types already have server links (11.3), no UI mapping
change is needed.

`end item` = active make item with a released BOM or routing that is not a child in any non-obsolete BOM. Every
code has one positive and one negative unit test (section 15).

---

## 8. Import / export

### 8.1 Interchange format and flow

`MfgBundle = dict[SheetName, list[dict[str, Any]]]` (`mfg/bundle.py`, WP-A): rows keyed by template field names,
referencing other entities by natural keys/codes (never ids). Sheet order = dependency order (table 8.2).
Producers: `io.read` + mapping (files), `bundle.dataset_to_bundle` (export, fingerprint), `samples.build`.
Consumers: `io.plan.plan_import` (tolerant, diffs against the DB snapshot, WP-B) and `bundle.bundle_to_dataset`
(strict, pure tests and samples, WP-A). Acceptance 15.3 #2 and the sample-load API tests prove both agree.

```
POST /mfg/imports (raw file) -> read.py -> RawSheets {name, headers, rows (cells as str|float|int|bool|date|None)}
     -> stored in mfg_imports.sheets, mapping.suggest_mapping -> response (status uploaded)
PUT  /mfg/imports/{id}/mapping {sheets: {...}, options} -> apply mapping -> MfgBundle (+ source row numbers)
     -> plan_import(bundle, load_dataset(s)) -> preview (counts, row errors, sample changes) (status mapped)
POST /mfg/imports/{id}/commit (If-Match) -> (read tx) load_dataset + plan_import, remember data_version;
     (write tx) lock_plant; if data_version changed: reload dataset and plan again inside the lock;
     zero errors required; writer.apply(plan) in ONE transaction; audit; status committed; result = counts;
     `sheets` rows are cleared (headers and row counts kept) so committed sessions hold no bulk data
```

Upload rules (review R4): every staged cell is a JSON-safe scalar: strings with C0 control characters other than
tab/CR/LF are stored with those characters removed and produce `IMP_CONTROL_CHAR` at mapping time; non-finite
numbers (openpyxl returns `inf` for `1E999`) are stored as `null` and produce `IMP_BAD_NUMBER` (Postgres JSONB and
the engine's `allow_nan=False` serializer would otherwise fail with 500). Any exception raised while reading the
file (openpyxl raises e.g. `ValueError` for a numeric cell `NaN`, `zipfile.BadZipFile`, `KeyError` for missing
parts) is answered with 422 `MFG_IMPORT_FILE_INVALID` (`details.reason` generic, the exception is logged at INFO),
never 500. Staged JSON over `IMPORT_MAX_STAGED_BYTES` -> 422 `MFG_IMPORT_TOO_LARGE`. On upload the owner's expired
sessions (any status) are deleted and at most `IMPORT_MAX_OPEN_PER_OWNER` uncommitted sessions are kept.

`plan_import(bundle, ds, options) -> ImportPlan` (pure): resolves natural keys against the dataset and against rows
earlier in the bundle, builds `creates`, `updates` (with field diffs), `unchanged`, `deletes` (children replaced,
see options) per sheet, runs the same model validation as the API (Pydantic input models; errors mapped to row
errors), cycle check over existing + new edges, released-document protection, and returns `row_errors` and
`warnings`. Options (`ImportOptions`):

| Option | Default | Meaning |
|---|---|---|
| `replace_children` | true | for each BOM/routing present in the file, its lines/operations are exactly the file's rows (missing ones deleted); false = upsert only |
| `release` | false | BOMs/routings created by this import are released (each must pass release rules, else row errors) |
| `default_effective_from` | null | used for created documents without `effective_from` |

Upsert semantics: a row whose natural key exists updates the entity's mapped columns only (unmapped columns keep
current values); creating requires all required fields. A row identical to the stored entity counts `unchanged`.
Re-importing the same file is a no-op (all `unchanged`, `row_version`s unchanged). Released BOM/routing headers
whose lines/operations or fields would change -> row error `IMP_RELEASED_READONLY` ("copy to a new version");
unchanged released documents are fine. Imports never delete master entities (only children under
`replace_children`). List-valued and nested fields of an entity present in the file are replaced as a whole
when their column is mapped: a template's `shifts` (all rows of that template in `shifts`), `operators.skills`,
`operators.shift_names`, `lines.eligible_families`, `lines.eligible_part_numbers`, `operations.tools`.

`status` column of `boms`/`routings` (only applied on create; an existing document's status is never changed by an
import): `draft` (default), `released` (must pass `release.py` rules, else `IMP_RELEASE_BLOCKED`), `obsolete`
(created directly obsolete, no release rules; needed so export -> import round-trips). Option `release: true`
turns a blank status into `released`. Documents released by one import are checked for overlap against each other
and the stored ones, in file order.

### 8.2 Templates and column specs (`io/spec.py`)

One xlsx workbook with one sheet per entity (names below, case-insensitive match; unknown sheets ignored with a
warning) plus a `README` sheet (field descriptions, enums, units). CSV: one file per sheet, file name
`<sheet>.csv` inside a zip, or a single CSV with `?sheet=<name>`. Header row = first non-empty row. Key columns in
**bold** (they identify the row; `*` = required on create).

| Sheet | Columns (field: type) |
|---|---|
| `plant` | name, utc_offset, planning_horizon_days, currency (max 1 row) |
| `items` | **part_number***, revision, description, uom, make_buy*, family, setup_family, lead_time_days, receiving_days, lot_rule, fixed_lot_qty, min_order_qty, order_multiple, safety_stock, serialized, shelf_life_days, handling_class, handling_note, active, `attr:<name>` (any number) |
| `skills` | **code***, name*, description |
| `tool_pools` | **code***, name*, kind, quantity*, note |
| `groups` | **code***, name*, description, kind, active |
| `lines` | **code***, group_code*, name*, speed_factor, parallel_capacity, setup_family, eligible_families (list), eligible_part_numbers (list), cost_per_hour, active |
| `shift_templates` | **code***, name*, description |
| `shifts` | **template_code***, **shift_name***, days* (list of mon..sun, or ranges `mon-sat`), start*, end*, breaks (list `HH:MM-HH:MM` or `name=HH:MM-HH:MM`) |
| `shift_assignments` | **template_code***, **target_type***, **target_code***, **kind***, **effective_from***, effective_to, shift_names (list), cost_per_hour, max_hours_per_week, note |
| `calendar_exceptions` | **scope***, **target_code** (blank for plant), **kind***, **start***, end*, label (start/end: `YYYY-MM-DD` = local midnight, or `YYYY-MM-DD HH:MM` local, or ISO with offset; a date-only `end` is inclusive: end of that day) |
| `operators` | **code***, name*, skills (list of codes), shift_template_code, shift_names (list), home_group_code, active |
| `boms` | **parent_part_number***, **revision**, **version**, effective_from, effective_to, serial_from, serial_to, note, status (`draft`/`released`; only applied on create) |
| `bom_lines` | **parent_part_number***, **revision**, **version**, **find_number**, **child_part_number***, qty_per*, uom, scrap_pct, ref_designators, alt_group, alt_priority, operation_seq, note |
| `routings` | **part_number***, **revision**, **code**, **version**, priority, effective_from, effective_to, serial_from, serial_to, note, status |
| `operations` | **part_number***, **revision**, **code**, **version**, **seq***, name*, group_code*, setup_minutes, run_minutes, run_per, units_per_panel, units_per_batch, queue_minutes, move_minutes, wait_minutes, labor, crew_size, skill_code, tools (list `CODE` or `CODE:QTY`), transfer_batch, yield_pct, inspection_gate, interruptible |

Key defaults when blank: `revision` = the item's current revision; `version` = 1 for a new document, else the
highest existing **draft** version, else 1 + highest (a new draft); routing `code` = `STD`. `find_number` blank ->
`10, 20, 30, ...` in file order within the BOM (deterministic, so re-import is idempotent). BOM/routing header rows
are optional: a `bom_lines`/`operations` key without a header row creates the header with defaults.

Cell parsing (`io/read.py` + `plan.py`): lists separated by `;` or `,` (`|` also accepted); booleans `true/false,
yes/no, y/n, 1/0` (case-insensitive); numbers with `.` decimal point (thousands separators are an error
`IMP_BAD_NUMBER`); Excel numeric cells in text fields are rendered without `.0` when integral (part numbers);
Excel dates/datetimes -> `date`/local datetime; `uom` through `normalize_uom` aliases; `make_buy` also accepts
`M/B/P`, `manufactured`, `purchased`; `days` accepts `mon-sat`, `mon,wed,fri`, `daily`. Formula cells use the cached
value (`data_only=True`); a formula without a cached value -> `IMP_FORMULA_NO_VALUE`. Leading/trailing spaces are
trimmed; empty rows skipped.

Mapping suggestion: header normalisation (lowercase, strip, collapse non-alphanumerics to `_`) + synonyms, e.g.
`part_number`: part no, part number, pn, item, item code, material; `qty_per`: qty, quantity, qty per, quantity
per, usage; `child_part_number`: component, child, component part; `parent_part_number`: parent, assembly;
`ref_designators`: ref des, reference, designators, refdes; `find_number`: find no, item no, pos, position;
`description`: desc, name (items only); `lead_time_days`: lead time, lt, lead time days. Sheet suggestion by sheet
name, else by header overlap (best spec with >= 2 key columns matched).

Row error format (preview and 409 details):
`{"sheet": "bom_lines", "row": 17, "column": "qty_per", "code": "IMP_REQUIRED", "message": "Quantity per is required."}`
(`row` = 1-based row number in the source sheet as Excel shows it). Row error codes: `IMP_REQUIRED`,
`IMP_BAD_NUMBER`, `IMP_BAD_BOOLEAN`, `IMP_BAD_DATE`, `IMP_BAD_ENUM`, `IMP_BAD_UOM`, `IMP_BAD_VALUE` (Pydantic
message), `IMP_UNKNOWN_REFERENCE` (part number/code not in data or file), `IMP_DUPLICATE_KEY` (same key twice in the
file), `IMP_RELEASED_READONLY`, `IMP_BOM_CYCLE`, `IMP_FORMULA_NO_VALUE`, `IMP_TOO_LONG`, `IMP_CONTROL_CHAR`,
`IMP_RELEASE_BLOCKED` (with the health code in the message), `IMP_IN_USE` (fix round: a template drops/renames a
shift still named by an assignment or operator, or an item stops being serialized while documents keep serial ranges).

### 8.3 Limits and file safety

- Body: `MAX_BODY_BYTES` (5 MiB default) via the existing middleware (413 `PAYLOAD_TOO_LARGE`).
- Format detection by magic bytes, not by name: `PK\x03\x04` -> zip; zip containing `[Content_Types].xml` and
  `xl/workbook.xml` -> xlsx; else text -> csv. `.xls` (OLE `D0 CF 11 E0`) -> 422 `MFG_IMPORT_FILE_INVALID`
  ("save as .xlsx").
- Zip/xlsx: before opening, `zipfile.ZipFile.infolist()` checks member count <= 200, total `file_size` <= `IMPORT_MAX_UNCOMPRESSED_BYTES` (64 MiB),
  per-member ratio `file_size / max(compress_size, 1)` <= 200, no absolute paths or `..` (members are never
  extracted to disk). openpyxl with `read_only=True, data_only=True, keep_links=False`; `defusedxml` installed
  (openpyxl uses it automatically; a startup assertion in a test checks `openpyxl.DEFUSEDXML is True`; verified
  with 3.1.5: the read-only worksheet parser's `iterparse` comes from `defusedxml`). Macros (`.xlsm`) are read as
  data only. Rows are read with `ws.iter_rows(values_only=True, max_row=IMPORT_MAX_SCANNED_ROWS,
  max_col=IMPORT_MAX_COLUMNS + 1)`: openpyxl yields an empty row for every gap (a single cell in row 1,000,000
  yields a million rows), so filler rows count toward the scan limit, and a non-empty cell in column 101 or a
  non-empty row after the scan limit -> 422 `MFG_IMPORT_TOO_LARGE`.
- CSV: decode UTF-8 (BOM stripped); on failure cp1252 with warning `IMP_ENCODING_FALLBACK`; delimiter sniffed from
  the header line among `,` `;` `\t`; NUL or other control characters (except tab) -> `IMP_CONTROL_CHAR`.
- Row/column/cell limits from 2. Exceeding any -> 422 `MFG_IMPORT_TOO_LARGE` with `details.limit`.
- Formula injection (review R4): **xlsx** text cells are written as `WriteOnlyCell` with `data_type = "s"` and no
  prefix (openpyxl otherwise turns any string starting with `=` into a formula - verified with 3.1.5); string cells
  can never be evaluated, and the value round-trips unchanged. **CSV**: text values starting with `=`, `+`, `-`,
  `@`, tab or CR are written with a leading `'`; the CSV reader strips exactly one leading `'` when the next
  character is one of those, so CSV export -> import also round-trips.
- Upload `Content-Type` must not be JSON: the body-limit middleware scans JSON bodies for NUL and would reject
  binary files with 422. The UI sends `application/octet-stream`; the server ignores the type (magic bytes decide).
- `Content-Disposition` file names are built from a slug of the plant name (`[A-Za-z0-9_-]`, max 40 chars, empty ->
  `plant`), never the raw name (quotes, CR/LF or non-Latin-1 characters would break the header or raise in
  Starlette's latin-1 header encoding).

### 8.4 Export

`GET /mfg/export?format=xlsx|zip` -> the complete dataset as a bundle in template format (every sheet, all
columns, sorted by natural key), `Content-Disposition: attachment; filename="superplanner-mfg-<plant-slug>-<YYYYMMDD>.xlsx"` (8.3).
Round-trip property (tested): export -> import into an empty owner -> export again gives identical bundles (byte-equal
CSV zip). `GET /mfg/templates/import?format=xlsx|zip` -> blank templates with header rows, one example row per
sheet (from the small sample) and the README sheet. xlsx export uses openpyxl `write_only=True`; part numbers and
codes as text cells; the zip uses fixed member timestamps (1980-01-01) so zip exports are byte-deterministic (xlsx
contains openpyxl's own timestamps; compare the parsed bundle).

---

## 9. REST API (`/api/v1/mfg`, `api/mfg/router.py`)

### 9.1 Conventions

- Router `APIRouter(prefix="/mfg", tags=["mfg"])`, included in `create_app` with `dependencies=[Depends(require_user)]`
  and added to the `protected` tuple passed to `body_gate.install` (B 4.7). Ownership is entirely the central
  mechanism: every lookup is a filtered ORM query; a foreign or unknown id -> 404 `NOT_FOUND` with the same body
  (`not_found("Item", id)` etc.). Rows are stamped by `before_flush`.
- **Order of checks** in every handler: (1) auth/CSRF (dependency), (2) body validation (FastAPI), (3) owned lookup
  -> 404, (4) If-Match -> 428/412, (5) state -> 409, (6) business rules -> 422. Lookup before precondition is
  required so foreign ids answer 404, never 428 (authz sweep, 14.2).
- Path parameters are plain `str` (no id regex), so a malformed, unknown or foreign id is always 404 `NOT_FOUND`,
  never 422. Ids inside bodies are `EntityId` (format 422; well-formed but unknown/foreign -> 422
  `MFG_UNKNOWN_REFERENCE`).
- Records carry `row_version`; GET/POST/PUT responses of single records send `ETag: "<row_version>"`; POST sends
  `Location`. PUT, DELETE and actions (`release`, `obsolete`, `copy`, import `commit`) require `If-Match`
  (`parse_if_match`, accepts `"3"`, `3`, `W/"3"`); mismatch -> 412 `VERSION_MISMATCH`
  `details: {"current_version": n}`. PUT is a full replacement of the Input model.
- Paginated lists (items only): `?limit=50&offset=0` -> `{"items": [...], "total": 1234, "limit": 50, "offset": 0}`;
  `limit` 1..200. Other lists are unpaginated `{"items": [...]}` (bounded by entity limits) sorted by `code`.
- Search `q`: case-insensitive substring on `part_number` and `description` (items), `code` and `name` (others);
  implemented as `lower(col) LIKE lower(:pattern) ESCAPE '\'` with `%`/`_`/`\` escaped (both dialects).
- Datetimes generated by the API are UTC `Z` (A 14); plant-time values (windows, exception start/end) use the plant
  offset; dates are `YYYY-MM-DD`.
- Default `on`/`as_of` date = today in the plant offset.
- Audit (`problem_service.audit`): `entity_type` `mfg_<entity>`, actions `create|update|delete|release|obsolete|
  copy|import_commit|sample_load|reset` (details: ids, versions, counts only).
- All endpoints are synchronous (no jobs, no SSE in M1). Writes run in `ctx.write_guard()` + one transaction +
  `repo.lock_plant(s)` (6.1).

### 9.2 Error codes (in addition to A 14 / B 4.5)

| HTTP | Code | When |
|---|---|---|
| 404 | `NOT_FOUND` | unknown or foreign id (also expired import sessions) |
| 409 | `MFG_DUPLICATE_KEY` | natural key exists (`details: {"key": {...}, "existing_id": "..."}`) |
| 409 | `MFG_IN_USE` | delete blocked (`details.references`); fix round: also a shift-template PUT that drops/renames a shift still named by assignments/operators, and an item PUT `serialized: false` while draft/released documents keep a serial range (`details.references` + `details.used_by` `[{type, id, label, ...}]`, templates also `details.shift_names`) |
| 409 | `MFG_RELEASED_READONLY` | edit/delete of a released (or obsolete for PUT) document |
| 409 | `MFG_INVALID_STATE` | action not allowed in the current status (e.g. release an obsolete BOM) |
| 409 | `MFG_IMPORT_HAS_ERRORS` | commit with row errors (`details: {"row_errors": [...], "error_count": n}`) |
| 409 | `MFG_IMPORT_ALREADY_COMMITTED` | second commit (`details.result` = first result) |
| 409 | `MFG_IMPORT_NOT_MAPPED` | commit before a mapping/preview exists |
| 409 | `MFG_BUSY` | plant lock not obtained within the Postgres `lock_timeout` (6.1); `Retry-After: 5` |
| 412 | `VERSION_MISMATCH` | If-Match stale |
| 413 | `PAYLOAD_TOO_LARGE` | body over `MAX_BODY_BYTES` (existing middleware) |
| 422 | `VALIDATION_ERROR` | model errors (A 14 shape) |
| 422 | `MFG_UNKNOWN_REFERENCE` | referenced id not found for this owner (`details: {"loc": [...], "id": "..."}`) |
| 422 | `MFG_ITEM_NOT_MAKE` | BOM for a buy item, routing for a buy/phantom item |
| 422 | `MFG_SERIAL_NOT_ALLOWED` | serial effectivity on a non-serialized item |
| 422 | `MFG_BOM_CYCLE` | write would create a cycle (`details: {"cycle": ["KV-A", "KV-B", "KV-A"]}`) |
| 422 | `MFG_SHIFT_INVALID` | template overlaps/breaks invalid (`details.errors` A 14 shape) |
| 422 | `MFG_RELEASE_BLOCKED` | release rules failed (`details.issues` in health issue shape) |
| 422 | `MFG_EXPLOSION_TOO_LARGE` / `MFG_BOM_TOO_DEEP` | 5 |
| 422 | `MFG_RANGE_TOO_LONG` | windows range > 62 days or `to <= from` |
| 422 | `MFG_IMPORT_FILE_INVALID` | unreadable/unsupported file (`details.reason`) |
| 422 | `MFG_IMPORT_TOO_LARGE` | import limits (`details.limit`, `details.value`) |
| 422 | `MFG_LIMIT` | entity count limits (2) |
| 422 | `MFG_RESET_CONFIRM` | reset without the confirmation phrase |
| 404 | `NOT_FOUND` (sample) | unknown sample id |

### 9.3 Endpoint table (all `U` = `require_user`; unsafe methods need CSRF in accounts mode)

Fixed paths are registered before parameterised siblings (`/shift-templates/preview` before
`/shift-templates/{shift_template_id}`).

| # | Method and path (`/api/v1/mfg`) | Body / query | Response | Errors |
|---|---|---|---|---|
| 1 | GET `/meta` | - | units, enums, limits, import spec (sheets/columns/synonyms), sample list | - |
| 2 | GET `/summary` | - | `{"counts": {"items": n, "make": n, "buy": n, "phantom": n, "boms": n, "bom_lines": n, "routings": n, "operations": n, "groups": n, "lines": n, "shift_templates": n, "operators": n, "tool_pools": n}, "end_items": [ItemRef] (max 50)}` (health is computed on demand, never stored) | - |
| 3 | GET `/plant` | - | `PlantRecord` + ETag (unsaved default: `id: null`, `row_version: 0`, ETag `"0"`; nothing inserted) | - |
| 4 | PUT `/plant` | `PlantInput`, If-Match (`"0"` creates the row) | `PlantRecord` | 412 428 422 |
| 5 | GET `/items` | `q, make_buy, family, active, has_bom, has_routing, sort (part_number\|-updated_at\|description), limit, offset` | page of `ItemRecord` | 422 |
| 6 | POST `/items` | `ItemInput` | 201 `ItemRecord` | 409 dup, 422 |
| 7 | GET `/items/{item_id}` | - | `ItemRecord` | 404 |
| 8 | PUT `/items/{item_id}` | `ItemInput`, If-Match | `ItemRecord` | 404 412 428 409 422 |
| 9 | DELETE `/items/{item_id}` | If-Match | 204 | 404 412 428 409 in use |
| 10 | GET `/items/{item_id}/explosion` | `on, serial, qty (default 1), mode (indented\|summarized), include_scrap, include_yield, max_depth` | `Explosion` | 404 422 |
| 11 | GET `/items/{item_id}/where-used` | `on` (omit = any date), `include (effective\|all, default effective)`, `mode (single\|indented)` | `WhereUsed` | 404 422 too large |
| 12 | GET `/items/{item_id}/boms` | - | `{"items": [BomSummary]}` (header fields, no lines, `line_count`) by revision, version | 404 |
| 13 | GET `/items/{item_id}/routings` | - | `{"items": [RoutingSummary]}` (`operation_count`) | 404 |
| 14 | POST `/boms` | `BomInput` | 201 `BomRecord` (draft) | 409 422 |
| 15 | GET `/boms/{bom_id}` | - | `BomRecord` | 404 |
| 16 | PUT `/boms/{bom_id}` | `BomInput` (item_id must equal stored), If-Match | `BomRecord` | 404 412 428 409 readonly 422 |
| 17 | DELETE `/boms/{bom_id}` | If-Match | 204 | 404 412 428 409 |
| 18 | POST `/boms/{bom_id}/release` | `{"effective_from": date\|null, "supersede_previous": bool=false}`, If-Match | `{"bom": BomRecord, "superseded": [{"id", "version", "effective_to"}]}` | 404 412 428 409 422 blocked |
| 19 | POST `/boms/{bom_id}/obsolete` | `{}`, If-Match | `BomRecord` | 404 412 428 409 |
| 20 | POST `/boms/{bom_id}/copy` | `{"revision": str\|null}`, If-Match | 201 `BomRecord` (new draft) | 404 412 428 |
| 21-27 | same seven for `/routings`, `/routings/{routing_id}` (+ `/release`, `/obsolete`, `/copy` with `{"revision", "code"}`) | `RoutingInput` | `RoutingRecord` | as BOMs |
| 28 | GET `/routings/{routing_id}/time-preview` | `qty` (default 1, > 0) | `TimePreview` (9.4) | 404 422 |
| 29 | GET `/groups` | `q, active` | list `GroupRecord` (+ `line_count`) | - |
| 30 | POST `/groups` | `GroupInput` | 201 | 409 422 |
| 31 | GET `/groups/{group_id}` | - | `GroupRecord` + `lines: [LineRecord]` + `assignments` | 404 |
| 32 | PUT `/groups/{group_id}` | If-Match | `GroupRecord` | 404 412 428 409 422 |
| 33 | DELETE `/groups/{group_id}` | If-Match | 204 | 404 412 428 409 |
| 34 | GET `/lines` | `group_id, q, active` | list `LineRecord` | - |
| 35 | POST `/lines` | `LineInput` | 201 | 409 422 |
| 36 | GET `/lines/{line_id}` | - | `LineRecord` | 404 |
| 37 | PUT `/lines/{line_id}` | If-Match | `LineRecord` | 404 412 428 409 422 |
| 38 | DELETE `/lines/{line_id}` | If-Match | 204 | 404 412 428 |
| 39 | GET `/lines/{line_id}/windows` | `from` (date, required), `to` (date, exclusive, required), `kinds` (`base,optional`) | `{"line_id", "from", "to", "utc_offset", "windows": [Window], "totals": {"base_minutes", "optional_minutes"}}` | 404 422 range |
| 40 | GET `/shift-templates` | - | list | - |
| 41 | POST `/shift-templates` | `ShiftTemplateInput` | 201 | 409 422 |
| 42 | POST `/shift-templates/preview` | `ShiftTemplateInput` (stateless, nothing stored) | `{"week_windows": [WeekWindow], "minutes_per_day": {...}, "total_minutes"}` | 422 |
| 43 | GET `/shift-templates/{shift_template_id}` | - | record | 404 |
| 44 | PUT `/shift-templates/{shift_template_id}` | If-Match | record | 404 412 428 409 422 |
| 45 | DELETE `/shift-templates/{shift_template_id}` | If-Match | 204 | 404 412 428 409 |
| 46 | GET `/shift-assignments` | `group_id, line_id, shift_template_id` | list | - |
| 47 | POST `/shift-assignments` | `ShiftAssignmentInput` | 201 | 422 |
| 48 | PUT `/shift-assignments/{assignment_id}` | If-Match | record | 404 412 428 422 |
| 49 | DELETE `/shift-assignments/{assignment_id}` | If-Match | 204 | 404 412 428 |
| 50-53 | GET, POST `/calendar-exceptions` (`from, to, scope, group_id, line_id`); PUT, DELETE `/calendar-exceptions/{exception_id}` | | | as 46-49 |
| 54-57 | GET, POST `/skills`; PUT, DELETE `/skills/{skill_id}` | | | 409 dup/in use |
| 58-62 | GET (`q, active, skill_id`), POST `/operators`; GET, PUT, DELETE `/operators/{operator_id}` | | | |
| 63-66 | GET, POST `/tool-pools`; PUT, DELETE `/tool-pools/{tool_pool_id}` | | | |
| 67 | GET `/health` | `as_of`, `horizon_days` (7..730, default plant) | `HealthReport` (7.1) | 422 |
| 68 | POST `/imports` | raw body (xlsx, zip or csv), query `filename` (1..200), `sheet` (csv only) | 201 `ImportRecord` | 413 422 |
| 69 | GET `/imports/{import_id}` | - | `ImportRecord` | 404 |
| 70 | PUT `/imports/{import_id}/mapping` | `ImportMappingRequest`, If-Match | `ImportRecord` with `preview` | 404 412 428 409 committed 422 |
| 71 | POST `/imports/{import_id}/commit` | `{}`, If-Match | `ImportRecord` with `result` | 404 412 428 409 |
| 72 | DELETE `/imports/{import_id}` | - (no If-Match) | 204 | 404 |
| 73 | GET `/export` | `format=xlsx\|zip` | file | 422 |
| 74 | GET `/import-templates` | `format=xlsx\|zip` | file | 422 |
| 75 | GET `/samples` | - | `{"items": [{"id", "name", "description", "counts"}]}` | - |
| 76 | POST `/samples/{sample_id}/load` | `{"replace": false}` | `{"sample_id", "result": ImportResult, "health": {"ok", "counts"}}` | 404 409 (sample keys clash with released docs of the user: `MFG_IMPORT_HAS_ERRORS`) |
| 77 | POST `/reset` | `{"confirm": "DELETE ALL MANUFACTURING DATA"}` | `{"deleted": {"items": n, ...}}` | 422 |

77 operations. Raw-body upload (#68) reads `await request.body()` inside the handler (after `require_user`), so no
`python-multipart` dependency and auth still answers first. `Content-Type` is ignored (magic bytes decide), but a
JSON content type makes the body-limit middleware reject binary bodies (8.3), so clients send
`application/octet-stream`. The handler does the parsing in the threadpool (`run_in_threadpool`), never on the
event loop.

### 9.4 JSON examples

Item create (#6):
```json
POST /api/v1/mfg/items
{"part_number": "KV-PCB-CPU", "revision": "C", "description": "Vital CPU board assembly", "uom": "EA",
 "make_buy": "make", "family": "PCBA-HDI", "serialized": true, "lot_rule": "lot_for_lot"}
-> 201, ETag: "1", Location: /api/v1/mfg/items/itm_3f...
{"id": "itm_3f...", "row_version": 1, "part_number": "KV-PCB-CPU", "revision": "C",
 "description": "Vital CPU board assembly", "uom": "EA", "make_buy": "make", "family": "PCBA-HDI",
 "setup_family": null, "lead_time_days": null, "receiving_days": 0, "lot_rule": "lot_for_lot",
 "fixed_lot_qty": null, "min_order_qty": 0, "order_multiple": 0, "safety_stock": 0, "serialized": true,
 "shelf_life_days": null, "handling_class": null, "handling_note": "", "attributes": {}, "active": true,
 "has_bom": false, "has_routing": false, "used_in_count": 0,
 "created_at": "2026-11-02T06:10:00Z", "updated_at": "2026-11-02T06:10:00Z"}
```
Duplicate -> 409 `{"error": {"code": "MFG_DUPLICATE_KEY", "message": "An item with part number 'KV-PCB-CPU' already exists.", "details": {"key": {"part_number": "KV-PCB-CPU"}, "existing_id": "itm_3f..."}}}`.

BOM document PUT (#16):
```json
PUT /api/v1/mfg/boms/bom_8a...   If-Match: "4"
{"item_id": "itm_3f...", "revision": "C", "version": 2, "effective_from": null, "effective_to": null,
 "serial_from": null, "serial_to": null, "note": "",
 "lines": [
  {"id": "bml_01...", "find_number": "10", "child_item_id": "itm_pcb...", "qty_per": 1, "uom": "EA"},
  {"find_number": "20", "child_item_id": "itm_c100n...", "qty_per": 48, "uom": "EA", "scrap_pct": 1,
   "ref_designators": "C1-C48"},
  {"find_number": "30", "child_item_id": "itm_conA...", "qty_per": 2, "alt_group": "30", "alt_priority": 1},
  {"find_number": "30", "child_item_id": "itm_conB...", "qty_per": 2, "alt_group": "30", "alt_priority": 2},
  {"find_number": "90", "child_item_id": "itm_coat...", "qty_per": 4, "uom": "ML", "operation_seq": 80}
 ]}
-> 200, ETag: "5"  (BomRecord, lines sorted, line ids assigned)
```

Release with supersede (#18): `POST /boms/bom_8a.../release` `If-Match: "5"`
`{"effective_from": "2026-12-01", "supersede_previous": true}` -> 200
`{"bom": {... "status": "released", "effective_from": "2026-12-01", "row_version": 6 ...},
"superseded": [{"id": "bom_77...", "version": 1, "effective_to": "2026-12-01"}]}`.
Blocked -> 422 `{"error": {"code": "MFG_RELEASE_BLOCKED", "message": "This BOM cannot be released yet (2 problems).",
"details": {"issues": [{"code": "MFG_UOM_MISMATCH", "severity": "error", "message": "...", "fix": "...",
"entity": {"type": "bom_line", "id": "bml_..", "label": "find 90"}, "related": [], "link": "...", "field": "uom"}]}}}`.

Explosion (#10): `GET /items/itm_tpu.../explosion?on=2026-11-02&qty=2`
```json
{"item_id": "itm_tpu...", "part_number": "KV-TPU-1000", "on": "2026-11-02", "serial": null, "qty": 2,
 "mode": "indented",
 "rows": [
  {"row": 0, "parent_row": null, "subtree_end": 2431, "level": 0, "line_id": null, "bom_id": "bom_t1...",
   "item_id": "itm_tpu...", "part_number": "KV-TPU-1000", "revision": "B", "description": "Loco TPU unit (fictional)",
   "make_buy": "make", "uom": "EA", "family": "FINAL", "lead_time_days": null, "active": true,
   "find_number": null, "ref_designators": "", "qty_per": null, "line_uom": null, "scrap_pct": null,
   "operation_seq": null, "extended_qty": 2.0, "alternates": [], "is_phantom": false, "has_children": true,
   "is_shared": false, "routing_id": "rtg_t1..."},
  {"row": 1, "parent_row": 0, "subtree_end": 1203, "level": 1, "line_id": "bml_..", "bom_id": "bom_vcu..",
   "item_id": "itm_vcu..", "part_number": "KV-VCU-2000", "make_buy": "make", "find_number": "10",
   "qty_per": 1, "line_uom": "EA", "scrap_pct": 0, "extended_qty": 2.083333, "...": "..."}
 ],
 "totals": {"rows": 2431, "distinct_items": 1312, "max_level": 4, "make_items": 61, "buy_items": 1243, "phantom_items": 8},
 "warnings": []}
```
(`extended_qty` 2.083333 = 2 / 0.96 final-test yield, consumed at the first operation of the top unit.)

Where-used (#11) `?mode=indented`:
```json
{"item_id": "itm_c100n..", "part_number": "KV-CAP-0402-100N", "mode": "indented", "include": "effective", "on": "2026-11-02",
 "rows": [{"row": 0, "parent_row": null, "level": 1, "item_id": "itm_cpu..", "part_number": "KV-PCB-CPU",
           "bom_id": "bom_..", "bom_revision": "C", "bom_version": 2, "bom_status": "released", "line_id": "bml_..",
           "find_number": "20", "qty_per": 48, "line_uom": "EA", "is_top": false},
          {"row": 1, "parent_row": 0, "level": 2, "part_number": "KV-VCU-2000", "...": "..."}],
 "totals": {"rows": 37, "top_items": 1}}
```

Time preview (#28) `?qty=250`:
```json
{"routing_id": "rtg_..", "item_id": "itm_..", "qty": 250, "uom": "EA",
 "operations": [
  {"seq": 10, "name": "SMT top", "group": {"id": "wcg_..", "code": "SMT"}, "input_qty": 264, "output_qty": 264,
   "run_per": "panel", "loads": 66, "queue_minutes": 0, "move_minutes": 5, "wait_minutes": 0, "labor": "attended",
   "lines": [{"line_id": "lin_..", "code": "SMT-1", "speed_factor": 1.0, "eligible": true,
              "setup_minutes": 45, "run_minutes": 79.2, "total_minutes": 124.2},
             {"line_id": "lin_..", "code": "SMT-3", "speed_factor": 0.7, "eligible": false, "reason": "family PCBA-HDI not eligible",
              "setup_minutes": 45, "run_minutes": 113.142857, "total_minutes": 158.142857}]}
 ],
 "totals": {"fastest_minutes": 2210.4, "slowest_minutes": 2731.0, "passive_minutes": 260, "cumulative_yield": 0.9506}}
```
(`fastest`/`slowest` sum the per-operation min/max over eligible lines; `passive` = queue + move + wait.)

Shift template + preview (#41/#42):
```json
{"code": "3SHIFT", "name": "24 hours, three shifts (Mon-Sat)",
 "shifts": [
  {"name": "A", "days": ["mon","tue","wed","thu","fri","sat"], "start": "06:00", "end": "14:00", "breaks": [{"name": "Meal", "start": "10:00", "end": "10:30"}]},
  {"name": "B", "days": ["mon","tue","wed","thu","fri","sat"], "start": "14:00", "end": "22:00", "breaks": [{"name": "Meal", "start": "18:00", "end": "18:30"}]},
  {"name": "C", "days": ["mon","tue","wed","thu","fri","sat"], "start": "22:00", "end": "06:00", "breaks": [{"name": "Meal", "start": "02:00", "end": "02:30"}]}]}
preview -> {"week_windows": [{"shift": "A", "day": "mon", "start_minute": 360, "end_minute": 600},
                             {"shift": "A", "day": "mon", "start_minute": 630, "end_minute": 840}, "..."],
            "minutes_per_day": {"mon": 1350, "...": 0, "sun": 0}, "total_minutes": 8100}
```
(`start_minute` from Monday 00:00 of the reference week; Saturday's C shift runs 8,520-9,000, i.e. ends Sunday
06:00; a Sunday-night shift would end after minute 10,080 and wraps onto Monday for the overlap check;
`minutes_per_day` attributes minutes to the shift's start day; breaks removed.)

Line windows (#39) `?from=2026-11-02&to=2026-11-04`:
```json
{"line_id": "lin_..", "from": "2026-11-02", "to": "2026-11-04", "utc_offset": "+05:30",
 "windows": [
  {"start": "2026-11-02T09:00:00+05:30", "end": "2026-11-02T13:00:00+05:30", "kind": "base", "assignment_id": "sha_..", "shift_label": "REG/Day", "cost_per_hour": null},
  {"start": "2026-11-02T13:45:00+05:30", "end": "2026-11-02T18:00:00+05:30", "kind": "base", "assignment_id": "sha_..", "shift_label": "REG/Day", "cost_per_hour": null},
  {"start": "2026-11-02T18:00:00+05:30", "end": "2026-11-02T19:30:00+05:30", "kind": "optional", "assignment_id": "sha_..", "shift_label": "EVE/Evening", "cost_per_hour": 450.0}],
 "totals": {"base_minutes": 990, "optional_minutes": 450}}
```

Import (#68 -> #70 -> #71):
```json
POST /api/v1/mfg/imports?filename=kavach-bom.xlsx   (body: file bytes)
-> 201 ETag: "1"
{"id": "imp_..", "row_version": 1, "status": "uploaded", "filename": "kavach-bom.xlsx", "format": "xlsx",
 "expires_at": "2026-11-03T06:10:00Z",
 "sheets": [{"name": "BOM", "row_count": 2431, "headers": ["Parent", "Find No", "Component", "Qty", "UoM", "Ref Des"],
             "sample_rows": [["KV-PCB-CPU", "10", "KV-BPCB-CPU", 1, "Nos", ""]],
             "suggested": {"target": "bom_lines", "columns": {"Parent": "parent_part_number", "Find No": "find_number",
                           "Component": "child_part_number", "Qty": "qty_per", "UoM": "uom", "Ref Des": "ref_designators"}}}],
 "mapping": null, "preview": null, "result": null}

PUT /api/v1/mfg/imports/imp_../mapping   If-Match: "1"
{"sheets": {"BOM": {"target": "bom_lines", "columns": {"Parent": "parent_part_number", "Find No": "find_number",
             "Component": "child_part_number", "Qty": "qty_per", "UoM": "uom", "Ref Des": "ref_designators"}}},
 "options": {"replace_children": true, "release": false, "default_effective_from": null}}
-> 200 ETag: "2"
{"...": "...", "status": "mapped",
 "preview": {"ok": false,
   "counts": {"bom_lines": {"create": 2390, "update": 12, "unchanged": 28, "delete": 0, "error": 1},
              "boms": {"create": 3, "update": 0, "unchanged": 58, "delete": 0, "error": 0}},
   "error_count": 1,
   "row_errors": [{"sheet": "BOM", "row": 1207, "column": "Component", "code": "IMP_UNKNOWN_REFERENCE",
                   "message": "Part number 'KV-IC-XC7A35T' is not in your items or in this file."}],
   "warnings": [],
   "changes_sample": [{"sheet": "bom_lines", "key": {"parent_part_number": "KV-PCB-VIO", "revision": "B", "version": 1,
                       "find_number": "40", "child_part_number": "KV-RES-0603-10K"},
                       "action": "update", "fields": {"qty_per": [6, 8]}}]}}

POST /api/v1/mfg/imports/imp_../commit   If-Match: "2"  ->  409 MFG_IMPORT_HAS_ERRORS (until fixed)
after a corrected re-upload + mapping -> 200
{"...": "...", "status": "committed", "committed_at": "2026-11-02T06:14:02Z",
 "result": {"counts": {"bom_lines": {"create": 2391, "update": 12, "unchanged": 28, "delete": 0}, "...": {}},
            "duration_ms": 2140}}
```
`ImportMappingRequest.sheets` keys = source sheet names; `target: null` ignores the sheet; column value `null`
ignores the column; mapping two source columns to one field -> 422. `changes_sample` holds the first 50 changes.

Sample load (#76): `POST /samples/kavach/load {"replace": true}` -> `replace: true` first runs reset (#77 semantics);
then (both modes) the bundle is imported through `plan_import` + writer with `release: true`, as one transaction;
`replace: false` upserts (a second load is all `unchanged`). Response `{"sample_id": "kavach",
"result": {...counts, "duration_ms"}, "health": {"ok": true, "counts": {"error": 0, "warning": 3, "info": 9}}}`.

### 9.5 Endpoint access additions (B 4.8 style)

All 77 rows: Auth `U`; CSRF on POST/PUT/DELETE; owned lookup -> 404 for every path id (`item_id`, `bom_id`,
`routing_id`, `group_id`, `line_id`, `shift_template_id`, `assignment_id`, `exception_id`, `skill_id`,
`operator_id`, `tool_pool_id`, `import_id`); body ids (`item_id` in BOM input, `child_item_id`, `group_id`,
`skill_id`, `tool_pool_id`, `eligible_item_ids`, template/line/group ids in assignments/operators) are resolved
through filtered queries -> 422 `MFG_UNKNOWN_REFERENCE` for foreign ids (never a cross-owner link); `sample_id` is
not owned. Stamps owner on all `mfg_*` inserts.

### 9.6 Response shapes not fully shown above (contract for the parallel frontend, review R10)

Every record has `id`, `row_version`, `created_at`, `updated_at` (UTC `Z`) plus its Input fields; refs are
`{id, code, name}` unless stated. Field sets below are frozen at WP-A milestone A1; any change goes through LEAD as
an edit of this section before code changes (WP-B and WP-C both build against it).

| Shape | Fields |
|---|---|
| `Meta` (#1) | `uoms: [{code, dimension, factor, aliases}]`; `enums: {make_buy, lot_rule, status, run_per, labor, assignment_kind, target_type, exception_scope, exception_kind, weekday}` (lists of strings); `limits: {<every limits.py constant>: number, max_body_bytes: number}` (the latter from Settings); `import_spec: {sheets: [{name, columns: [{field, type ("str"\|"int"\|"float"\|"bool"\|"date"\|"datetime"\|"list"\|"enum"), required_on_create, key, enum_values \| null, synonyms}]}]}`; `samples: [{id, name, description, counts}]`; `health_codes: [{code, severity}]` |
| `Summary` (#2) | `counts` as in 9.3, `end_items: [ItemRef]`, `data_version` |
| `BomSummary` (#12) | header fields of `BomRecord` (no `lines`) + `line_count` |
| `RoutingSummary` (#13) | header fields of `RoutingRecord` (no `operations`) + `operation_count` |
| `GroupRecord` (#29-32) | + `line_count`; `GET /groups/{id}` adds `lines: [LineRecord]` and `assignments: [ShiftAssignmentRecord]` (targeting the group or any of its lines) |
| `ShiftTemplateRecord` | + `assignment_count`, `operator_count` |
| `ShiftAssignmentRecord` | + `template: ref`, `target: {type, id, code, name}` |
| `CalendarExceptionRecord` | `start`/`end` in the plant offset; + `target: {type, id, code, name} \| null` (plant scope) |
| `SkillRecord` | + `operator_count`, `operation_count` (the skills page lists holders via `GET /operators?skill_id=`) |
| `OperatorRecord` | + `skills: [ref]`, `shift_template: ref \| null`, `home_group: ref \| null` |
| `ToolPoolRecord` | + `operation_count` |
| `WeekWindow` (#42) | `{shift, day, start_minute, end_minute}` (minutes from Monday 00:00, may exceed 10,080) |
| `Window` (#39) | as in the example; merged windows of several shifts of one assignment get `shift_label` `"<template>/<name>+<name>..."` in first-appearance order |
| `ImportRecord` (#68-71) | `id, row_version, status, filename, format, created_at, expires_at, committed_at, sheets: [{name, row_count, headers, sample_rows (first 5), suggested: {target, columns} \| null}], mapping: ImportMappingRequest \| null, preview: ImportPreview \| null, result: ImportResult \| null` |
| `ImportPreview` | `{ok, counts: {<sheet>: {create, update, unchanged, delete, error}}, error_count, row_errors (<= 500), warnings: [{code, message, sheet \| null}], changes_sample (<= 50)}` |
| `ImportResult` | `{counts: {<sheet>: {create, update, unchanged, delete}}, duration_ms, data_version}` |
| `SampleLoadResponse` (#76) | `{sample_id, result: ImportResult, health: {ok, counts}}` |
| `ResetResponse` (#77) | `{deleted: {<table without mfg_ prefix>: n}}` |
| `HealthReport` (#67) | 7.1 (+ `data_version`) |

---

## 10. Sample datasets (`superplanner/mfg/samples`)

### 10.1 Rules

- `build(sample_id) -> MfgBundle`, pure and **deterministic**: `random.Random(<fixed seed per sample>)`; only
  `random()`, `randrange()`, `choice()`, `shuffle()` on lists in a fixed order; never iterate a `set` or rely on
  `hash()` of strings (PYTHONHASHSEED varies); no clock reads (all dates fixed). A golden test pins
  `sha256(canonical_json(bundle))` and the counts per sheet for each sample; changing a generator means updating
  the golden values in the same change, deliberately.
- All BOMs/routings are loaded with `release: true`, effective from `2026-01-01`. Plant `utc_offset "+05:30"`.
- Part numbers are prefixed per sample (`SM-`, `MD-`, `KV-`) so samples can coexist with each other and with user data.
- Every sample passes the health check with **zero errors** on `as_of = 2026-11-02`, horizon 90 (test). Each sample
  deliberately contains a few warnings/infos so the health page has content (listed below).
- Descriptions say: "Fictional sample data. Structure inspired by a loco-mounted train-protection unit; not real
  HBL or Kavach data." (Kavach sample) / "Fictional sample data." (others). No real supplier part numbers: MPN-like
  attributes are synthetic (`"mpn": "SYN-..."`).

### 10.2 `small` (~10 parts) - "SM-100 Sensor interface board"

Items: `SM-100` PCB assembly (make, EA), `SM-BPCB-100` bare PCB (buy, 21 d), 6 components (2 resistors, 2
capacitors, 1 MCU (lead 84 d, handling `MSL3`), 1 connector), `SM-COAT-01` conformal coating (buy, `L`, line uom
`ML`), `SM-LBL-01` label = 10 items. One BOM (8 lines), one routing: 10 SMT top (SMT, panel of 4), 20 AOI, 30 THT
(connector), 40 FCT (jig `SM-JIG-FCT`, inspection gate, yield 98%). Plant: groups SMT (line SMT-1), AOI (AOI-1), THT
(THT-1), FCT (FCT-1); templates REG (Mon-Sat 09:00-18:00, lunch 13:00-13:45) and EVE (Mon-Sat 18:00-22:00,
optional, cost 300/h, max 12 h/week on THT and FCT); skills SMT-OP, TEST; 3 operators (`SM-OP-1` SMT-OP on REG,
`SM-OP-2` TEST on EXT 09:00-22:00 so the FCT overtime is covered, `SM-OP-3` SMT-OP + TEST on REG; the template set
is REG, EVE, EXT); tools stencil `SM-STN-T` (1), `SM-JIG-FCT` (1). `small` has **zero issues** (the clean baseline
for tests).

### 10.3 `medium` (~200 parts, 4 levels) - "MD-200 Industrial I/O controller"

`MD-200` top (make) -> `MD-CTL` controller assembly (make), `MD-ENC` enclosure (make: 5 mech lines), `MD-HAR-1`,
`MD-HAR-2` harnesses (make, ~10 lines each), hardware kit `MD-KIT-HW` (phantom, 6 lines) -> `MD-CTL` contains
`MD-PCB-MAIN` (~70 lines), `MD-PCB-IO` (~45), `MD-PCB-PWR` (~30), and a programmed MCU `MD-PRG-MCU` (make, 1 line:
blank MCU, routing PROG). ~185 buy items from a shared component library (passives shared across the 3 PCBs).
BOM lines ~220, 4 levels (0..3). Plant: 10 groups (SMT with 2 lines speed 1.0/0.8 on 3SHIFT, AOI, THT 2 benches,
COAT, CURE oven unattended, FCT 2 stations, PROG, HAR-ASSY 2 benches, ASSY, TEST); templates REG, EVE, 3SHIFT; 6
skills, 12 operators, 12 tool pools. Intended issues: 1 alternate group on `MD-PCB-PWR` (connector A/B), 1 long-lead
MCU (210 d, info), `MD-PCB-IO` has an alternate routing (priority 2, wave instead of selective solder), one draft
BOM v2 of `MD-PCB-MAIN` (info `MFG_DRAFT_ONLY` not raised because v1 is released; it shows in the BOM version list).

### 10.4 `kavach` (~2,400 BOM lines, 5 levels) - "KV-TPU-1000 Loco train-protection unit (fictional)"

Structure (levels 0..4; `x n` = qty per; families in brackets):

```
L0 KV-TPU-1000 Loco TPU unit [FINAL]  routing: final assembly 240, burn-in 1440/batch 8 (unattended, non-interruptible),
   |                                   final test 180 (gate, yield 96%), pack 20
   |-- KV-VCU-2000 Vital computer unit [SUBASSY] x1
   |     |-- KV-PCB-CPU  Vital CPU board [PCBA-HDI] x3   (~280 lines; programmed KV-PRG-CPU-MCU, KV-PRG-CPU-CFG)
   |     |-- KV-PCB-VIO  Vital I/O board [PCBA-HDI] x2   (~220)
   |     |-- KV-PCB-COM  Comms controller board [PCBA-STD] x1 (~180; KV-PRG-COM-MCU)
   |     |-- KV-PCB-EVR  Event recorder board [PCBA-STD] x1 (~150; KV-PRG-EVR-MCU)
   |     |-- KV-PCB-BPL  VCU backplane [PCBA-STD] x1 (~60, mostly press-fit connectors)
   |     |-- KV-HAR-VCU1, KV-HAR-VCU2 internal harnesses [HARNESS] x1 each
   |     |-- KV-MEC-VCU  VCU chassis [MECH] x1;  KV-KIT-HW-A hardware kit (phantom) x1
   |-- KV-RCU-3000 Radio communication unit [SUBASSY] x1
   |     |-- KV-PCB-RMD Radio modem board [PCBA-HDI] (~240; KV-PRG-RMD-MCU), KV-PCB-RFE RF front-end board (~120),
   |     |   KV-PCB-GNS GNSS/GSM interface board (~90), KV-MOD-GSM radio module (buy, 182 d), KV-HAR-RF1, KV-MEC-RCU
   |-- KV-DMI-4000 Driver display unit [SUBASSY] x2 (two cabs)
   |     |-- KV-PCB-DSC Display controller board [PCBA-HDI] (~200; KV-PRG-DSC-MCU), KV-PCB-KPD keypad board (~50),
   |     |   KV-LCD-104 10.4" TFT panel (buy, 120 d), KV-HAR-DMI, KV-MEC-BZL bezel
   |-- KV-RIU-5000 RFID reader interface unit [SUBASSY] x1
   |     |-- KV-PCB-RFI RFID interface board (~160; KV-PRG-RFI-MCU), KV-HAR-RIU, KV-MEC-RIU
   |-- KV-PSU-6000 Power supply unit [SUBASSY] x1
   |     |-- KV-PCB-DCC DC-DC converter board x2 (~110), KV-PCB-FLT input filter board (~45), KV-MEC-HSK heat sink, KV-HAR-PSU
   |-- KV-CHS-7000 Loco cable/harness set [SUBASSY] x1
   |     |-- KV-HAR-L01..L08 loco harnesses (speed sensor, brake interface, cab radio, power input, DMI cab 1/2,
   |         RFID antenna front/rear), each 12-30 lines (wire in M with line uom MM, terminals, housings, backshells,
   |         heat-shrink in M, labels, ties)
   |-- KV-ENC-8000 Enclosure / rack assembly [MECH] x1  (frame, panels, gaskets, KV-PCB-LED status LED board ~25)
   |-- KV-KIT-HW-T top hardware kit (phantom), KV-DOC-PACK documentation pack (buy), labels
L3/L4: each PCB -> bare PCB (buy, 21-35 d) + components (buy) + KV-COAT-UR conformal coating (L, line uom ML,
       operation_seq = coating op) + KV-PRG-* programmed ICs (make, routing PROG) -> blank IC (buy, L4)
```

- Component library ~900 buy items: resistors/capacitors in 0402/0603/0805 (E-series values, reel MOQ 5,000,
  multiple 5,000, lead 28-56 d), inductors, diodes, transistors, ICs (lead 56-182 d; 6 FPGAs/processors 210-364 d,
  `handling_class` `MSL3`/`MSL4`, shelf life notes), crystals, connectors (42-84 d), relays, wire (M, MOQ 100,
  14 d), terminals, housings, hardware, sheet-metal blanks, gaskets, coating (L, shelf life 365 d). Library items
  are drawn with a skewed distribution so common decoupling capacitors, pull-up resistors and connectors are shared
  by most boards (`is_shared` rows in the explosion; where-used of `KV-CAP-0402-100N` returns 10+ parents).
- Counts (targets, golden-pinned at implementation): items 1,150-1,500; BOM documents ~70; BOM lines 2,200-2,700;
  indented explosion rows of `KV-TPU-1000` 2,300-3,000; make items ~60; routings ~63 (incl. 3 alternates);
  operations 450-650; groups 20; lines ~45; shift templates 6; assignments ~45; exceptions ~8; skills 14; operators
  ~48; tool pools ~85.
- PCB routing (double-sided boards; ops repeat on the same groups): 10 SMT top (SMT, setup 45, run 1.0-2.4 per
  panel, 2-6 units/panel, tool stencil `KV-STN-<board>-T`), 20 AOI top (AOI, 0.8-1.5 per panel), 30 SMT bottom (SMT,
  stencil `-B`), 40 AOI bottom, 50 THT (THT, attended, 6-25 per unit, skill THT-SOLDER), 60 selective solder (SEL, 2-5
  per unit) - `KV-PCB-FLT` and `KV-PCB-BPL` alternate routing priority 2 with wave solder (WAVE), 70 wash (WASH,
  batch 20, 30 per batch), 80 conformal coat (COAT, 2-4 per unit, skill COATING), 90 cure (CURE, batch 50, 120 per
  batch, unattended, crew 0, non-interruptible), 100 ICT (ICT, 3-6 per unit, fixture `KV-ICT-<board>`, gate,
  yield 97-99%), 110 FCT (FCT, 8-20 per unit, jig `KV-FCT-<board>`, gate, yield 97-99%). Single-sided keypad/LED
  boards skip 30/40.
- Harness routing: 10 cut & strip (HAR-CUT, setup 20, run 2-6 per unit), 20 crimp (HAR-CRIMP, applicator tool by
  terminal family, run 3-10), 30 assemble (HAR-ASSY, skill HARNESS-ASSY, run 25-120, transfer batch 5), 40
  continuity test (HAR-TEST, adapter `KV-HTA-<harness>`, gate, yield 99%). One harness has an alternate routing
  (manual hand-crimp on HAR-ASSY, priority 2).
- Mechanical make parts: 10 mechanical assembly (MECH, 10-40), 20 inspection (MECH, gate). Programmed ICs: 10
  program (PROG, setup 15, run 1.5, adapter tool, skill PROG-OP). Sub-assemblies: 10 assembly (SUBASSY, 60-180, skill
  ELEC-ASSY), 20 sub-assembly test (SUBTEST, jig, gate, yield 98%). Top: see L0.
- Plant (groups -> lines (speed); base / optional shifts):

| Group | Lines | Base | Optional |
|---|---|---|---|
| SMT | SMT-1 (1.0), SMT-2 (1.0), SMT-3 (0.7, eligible families `PCBA-STD` only) | 3SHIFT Mon-Sat | SUN (Sunday 06-22) cost 1,200/h, max 16 h/wk |
| AOI | AOI-1, AOI-2 | 3SHIFT | - |
| THT | THT-B1..B4 | REG | EVE (to 22:00) 450/h, max 12 h/wk |
| SEL | SEL-1, SEL-2 | REG | EVE 500/h |
| WAVE | WAVE-1 | REG | - |
| WASH | WASH-1 | REG | EVE 300/h |
| COAT | COAT-1 | REG | EVE 400/h |
| CURE | OVEN-1, OVEN-2 (parallel capacity 4) | 24x7 | - |
| ICT | ICT-1, ICT-2 | REG | EVE 450/h, max 12 h/wk |
| FCT | FCT-1..3 | REG | EVE 450/h, max 12 h/wk |
| PROG | PROG-1 | REG | - |
| HAR-CUT | CUT-1, CUT-2 | REG | EVE 350/h |
| HAR-CRIMP | CRIMP-1..3 | REG | EVE 350/h |
| HAR-ASSY | HB-1..HB-6 | REG | EVE (to 22:00) 400/h, max 12 h/wk |
| HAR-TEST | CT-1, CT-2 | REG | EVE 350/h |
| MECH | MB-1, MB-2 | REG | - |
| SUBASSY | SA-1..SA-4 | REG | EVE 450/h |
| SUBTEST | ST-1, ST-2 | REG | EVE 450/h |
| BURNIN | BI-1, BI-2 (parallel capacity 8, unattended) | 24x7 | - |
| FINAL | FA-1..FA-3 (assembly), FT-1, FT-2 as separate group FINAL-TEST | REG | EVE 500/h |

  (FINAL-TEST is the 20th group.) Templates: `REG` Mon-Sat 09:00-18:00 lunch 13:00-13:45; `EVE` Mon-Sat
  18:00-22:00 break 19:30-19:45; `EXT` Mon-Sat 09:00-22:00 (for forcing extended hours in M3); `3SHIFT` (9.4);
  `24x7` Mon-Sun 00:00-00:00 (24 h); `SUN` Sunday 06:00-22:00. SMT-3 additionally has a line-level `EVE`-only
  base override for Jan-Mar 2026 (shows the per-line rule in the UI; expired by `as_of`). Exceptions: plant
  holidays on 2026-11-09 and 2026-12-25 ("Plant holiday"), shutdown 2026-12-28..2026-12-31 ("Annual shutdown"),
  maintenance SMT-2 2026-11-14 06:00-18:00, OVEN-1 2026-11-21 08:00-16:00.
- Skills (14): SMT-OP, AOI-OP, THT-SOLDER, SEL-SOLDER, WASH-OP, COATING, ICT-TECH, FCT-TECH, PROG-OP, HARNESS-CRIMP,
  HARNESS-ASSY, HARNESS-TEST, ELEC-ASSY, TEST-ENG. Operators `OP-001`..`OP-046` ("Operator 001"), on REG, EXT (covers the
  EVE overtime) or 3SHIFT A/B/C, plus a weekend crew `OP-047`, `OP-048` on `SUN` with SMT-OP (covers the optional
  SMT Sunday shift), 1-3 skills each, so every skill is covered (rule 7.2 #24) on every base and optional window of
  every eligible line its groups run, except one intended gap: COATING operators are all on REG (EVE on COAT-1
  uncovered -> exactly one `MFG_SKILL_NOT_ON_SHIFT` issue, skill COATING, line COAT-1). Unattended crew-0
  operations (CURE, BURNIN) need no operator.
- Tooling (~85): stencils top/bottom per SMT board (qty 1; CPU qty 2), ICT fixtures per board (1), FCT jigs per board
  (1-2), crimp applicators per terminal family (1-2), harness test adapters (1), programming adapters (2), burn-in
  harness `KV-BIH` (8).
- Intended non-error issues (asserted by the sample test as the **exact** `by_code` key set): `MFG_LONG_LEAD_TIME`
  (info, the FPGAs/processors and the radio module), `MFG_SKILL_NOT_ON_SHIFT` (warning, count 1: COATING has no
  operator on EVE), `MFG_DUPLICATE_COMPONENT` (info: the backplane uses the same connector at two find numbers). Alternate groups on `KV-PCB-DCC` (two
  capacitor alternates) are complete; reference designators are generated to match quantities, so
  `MFG_REFDES_COUNT` does not occur.

### 10.5 Benchmark use

`samples.SAMPLES` also exposes `scale(sample_id, factor)` for tests only (e.g. `kavach x2` = two product variants
with distinct part-number prefixes `KV2-` sharing the component library), used by the 5,000-line performance tests.

---

## 11. Frontend (`frontend/src/mfg/**`, React 18 + TypeScript, no new npm packages)

### 11.1 Navigation and routes

`App.tsx` `MainNav` gains a third link **Manufacturing** (`data-testid="nav-mfg"`, to `/mfg`), active for
`isMfgPath(pathname) = /^\/mfg(\/|$)/`; Scheduling is active only when neither finance nor mfg is active (exactly one
`aria-current="page"`, as asserted by the existing finance e2e). `main.tsx` spreads `mfgRoutes` next to
`financeRoutes` inside `RequireAuth`.

| Route | Page component | Content |
|---|---|---|
| `/mfg` | `MfgHome` | counts (`/summary`), health status card (runs `/health` on open), sample loader (3 cards, "Load" / "Replace my data"), quick links, export button |
| `/mfg/items` | `ItemsPage` | virtual table, search (debounced 250 ms, `q`), filters make/buy/phantom, family, active, has BOM/routing; infinite paging by 200; "New item" dialog |
| `/mfg/items/:itemId` | `ItemShell` (tabs) -> index = `ItemDetailsTab` | edit form (If-Match), attributes editor, delete/deactivate |
| `/mfg/items/:itemId/bom` (`?bom=&line=&on=&serial=&qty=`) | `BomTab` | BOM version list (status chips, effectivity, release/obsolete/copy actions), indented tree `BomTree` of the explosion at `on` |
| `/mfg/items/:itemId/bom/:bomId/edit` (`?line=`) | `BomEditPage` | single-level line grid (`BomLinesGrid`) of a draft BOM, item picker, alternates, save (PUT) |
| `/mfg/items/:itemId/where-used` | `WhereUsedTab` | single / indented toggle, effective / all |
| `/mfg/items/:itemId/routing` (`?routing=&op=`) | `RoutingTab` | routing list (priority, status), `RoutingEditor`, `OperationTimePreview` |
| `/mfg/plant` -> `/mfg/plant/groups` | `PlantLayout` + `GroupsPage` | groups with nested lines (`?group=`, `?line=` select and scroll), line form (speed, capacity, eligibility, setup family) |
| `/mfg/plant/shifts` (`?template=`, `?assignment=`) | `ShiftsPage` | templates list + `ShiftTemplateEditor` with live `ShiftWeekPreview`; assignments table per group/line |
| `/mfg/plant/calendar` (`?line=`, `?exception=`) | `CalendarPage` | exceptions list/form; `LineCalendar` month view of a line's windows (base solid, optional hatched, exceptions red) |
| `/mfg/plant/settings` | `PlantSettingsPage` | name, utc offset, horizon, currency |
| `/mfg/resources/skills` (`?skill=`) | `SkillsPage` | skills; the selected skill lists its operators and their shift templates (target of `MFG_SKILL_NOT_ON_SHIFT` links) |
| `/mfg/resources/operators` (`?operator=`) | `OperatorsPage` | skills multi-select, shift template + shift names |
| `/mfg/resources/tooling` (`?tool=`) | `ToolingPage` | |
| `/mfg/health` | `HealthPage` | as-of date + horizon, counts by severity/code, filter chips, `HealthIssueList` with "Fix" links (`issue.link`) |
| `/mfg/import` and `/mfg/import/:importId` | `ImportWizard` | steps Upload -> Map columns -> Preview -> Done (11.5) |
| `/mfg/*` | `NotFound` | |

### 11.2 Files (all new under `frontend/src/mfg/`)

```
routes.tsx  mfg.css
api/client.ts      mfgRaw/mfgRequest (same envelope parsing as finance client), mfgUpload(path, file: Blob, query),
                   mfgDownload(path) (blob + filename from Content-Disposition), one typed function per endpoint
api/types.ts       mirrors of section 3/5/7/9 shapes
lib/useMfg.ts      useAsync-style hooks with AbortController; version-conflict helper (412 -> reload banner)
lib/links.ts       none: links come from the server (issue.link); only route builders for own navigation
lib/tree.ts        visibleRows(rows, collapsed) using subtree_end; expandToLevel; search match + reveal ancestors
pages/             MfgLayout (sub-nav: Overview, Items, Plant, People & tooling, Data health, Import/export) and the
                   pages of 11.1
components/
  VirtualTable.tsx       generic windowed table (11.4)
  BomTree.tsx            tree on VirtualTable: indent by level, chevrons, expand/collapse all, expand to level N,
                         columns (find no, part no, description, qty per, line uom, scrap, extended qty, make/buy,
                         lead time, ref des), shared-item badge, alternates popover, row click -> item
  BomLinesGrid.tsx       editable grid (virtualised when > 100 lines), keyboard entry, add/delete/duplicate rows
  ItemPicker.tsx         combobox over GET /items?q= (limit 20)
  RoutingEditor.tsx      operations table: drag handle (HTML5 drag and drop) + "Move up/down" buttons (keyboard),
                         inline edit, add/remove, renumber 10,20,.. on reorder (warns when BOM lines reference seqs)
  OperationTimePreview.tsx  qty input -> GET time-preview; per-operation per-line minutes, eligible marks, totals
  ShiftTemplateEditor.tsx   shifts with day toggles, start/end, breaks
  ShiftWeekPreview.tsx      SVG 7 columns x 24 h from POST /shift-templates/preview (debounced 300 ms); night
                            shifts drawn split across midnight; breaks as gaps; per-day totals
  LineCalendar.tsx          month grid of GET /lines/{id}/windows (<= 62 days per call)
  HealthIssueList.tsx       grouped by code; severity icons; Fix link
  ImportUpload.tsx  ImportMapping.tsx  ImportPreview.tsx  ImportResult.tsx
  SampleLoader.tsx  StatusChip.tsx  EffectivityBadge.tsx  EntityFormDialog.tsx
```

### 11.3 Jump-to-fix link table (server builds `issue.link`; the UI routes must exist exactly)

| Entity type | Link |
|---|---|
| item | `/mfg/items/{id}` |
| bom | `/mfg/items/{item_id}/bom?bom={id}` |
| bom_line (BOM is `draft`) | `/mfg/items/{item_id}/bom/{bom_id}/edit?line={id}` |
| bom_line (BOM `released`/`obsolete`) | `/mfg/items/{item_id}/bom?bom={bom_id}&line={id}` |
| routing | `/mfg/items/{item_id}/routing?routing={id}` |
| operation | `/mfg/items/{item_id}/routing?routing={routing_id}&op={seq}` |
| group | `/mfg/plant/groups?group={id}` |
| line | `/mfg/plant/groups?line={id}` |
| shift_template | `/mfg/plant/shifts?template={id}` |
| shift_assignment | `/mfg/plant/shifts?assignment={id}` |
| calendar_exception | `/mfg/plant/calendar?exception={id}` |
| skill / operator / tool_pool | `/mfg/resources/skills?skill={id}` / `/mfg/resources/operators?operator={id}` / `/mfg/resources/tooling?tool={id}` |
| (operation in a released routing) | same as operation; the routing tab shows the read-only banner with Copy |
| plant | `/mfg/plant/settings` |

Released BOM lines link to the BOM view (not edit), which selects and scrolls to `?line=`; if a user opens the
edit route of a released BOM anyway, the edit page shows a "Released - copy to a new version to edit" banner with a
Copy button.

### 11.4 Large data handling

- `VirtualTable<T>`: fixed row height 32 px (CSS variable), container height from layout, renders
  `visible + 2 x overscan (10)` rows positioned with a top spacer, sticky header, `role="treegrid"`/`"grid"` with
  `aria-rowcount`/`aria-rowindex`, keyboard up/down/left/right (collapse/expand), Home/End. DOM rows never exceed
  ~80 regardless of data size (e2e assertion).
- BOM tree: the full explosion is fetched once (one request), stored as an array; collapse state is a
  `Set<number>` of row indices; `visibleRows` walks rows and jumps to `subtree_end` for collapsed rows (O(visible
  rows + collapsed count)). Default: expanded to level 2. Search highlights matches and expands their ancestors.
  "Expand all" on 3,000 rows < 100 ms.
- Items list pages of 200 via `offset` when scrolling near the end; total from the response.
- No virtualization library, no new dependencies (PLAN-PHASE2B rule). Drag and drop is native HTML5 with a keyboard
  alternative (accessibility).

### 11.5 Import wizard

1. Upload: file input / drop zone (xlsx, csv, zip; size shown; > `MAX_BODY_BYTES` refused client-side with the
   server's limit from `/meta`); for CSV a target sheet select. POST raw bytes.
2. Map columns: one card per source sheet: target sheet select (suggested preselected), per column a select of
   target fields (required fields marked; unmapped required -> inline hint); options (replace children, release,
   default effective from). "Preview" = PUT mapping.
3. Preview: counts table per target sheet (create/update/unchanged/delete/error), row errors table (virtualised; sheet,
   row, column, message) with "Download errors as CSV" (client-side), changes sample. Commit disabled while
   `error_count > 0`; "Fix the file and upload again" returns to step 1 keeping the mapping (re-applied by header
   names).
4. Done: result counts, link to Data health and Items.

Wizard state lives in the URL (`/mfg/import/:importId?step=map|preview|done`) and the server record, so reload works.

---

## 12. Performance targets

Measured on the developer machine class used so far (single process, file-DB database DB unless noted; PostgreSQL local
must meet the same targets x 1.5). Performance tests are marked `slow` where they take > 5 s and run in both suites.

| # | Operation | Data | Target | SQL statements |
|---|---|---|---|---|
| P1 | pure `explode` (indented) | Kavach (~2,600 rows) / `kavach x2` (~5,200 rows) | < 0.15 s / < 0.3 s | - |
| P2 | `GET /items/{id}/explosion` end-to-end | Kavach / `kavach x2` with 4,000+ lines | < 1.0 s / < 1.5 s | <= 3 x (L + 1) + 3 (6.4; L = deepest level) |
| P3 | `GET /items/{id}/where-used?mode=indented` | most shared capacitor | < 0.3 s | <= 3 x L + 2 |
| P4 | `GET /items` page of 50 with `q` | 10,000 items | < 0.15 s | <= 5 (page, count, 3 flag aggregates over the page ids) |
| P5 | `GET /health` | Kavach | < 2.0 s | <= 20 |
| P6 | import preview (PUT mapping) | 5,000 BOM-line rows | < 4 s | <= 25 |
| P7 | import commit | 5,000 rows (items + BOM lines) into an empty owner | < 10 s end-to-end; plant lock / write transaction held < 6 s (below the 10 s Postgres `lock_timeout`) | bounded (batched inserts, one flush per sheet) |
| P8 | re-import same 5,000 rows (all unchanged) | | < 5 s, zero writes except the import row | |
| P9 | `POST /samples/kavach/load` | empty owner | < 10 s | |
| P10 | `GET /export?format=xlsx` | Kavach | < 5 s | <= 20 |
| P11 | `GET /lines/{id}/windows` 62 days | 3SHIFT + exceptions | < 0.1 s | <= 6 |
| P12 | UI: BOM tree of Kavach top item interactive after data arrives | Chromium | < 1 s; scroll without long tasks > 100 ms; <= 80 DOM rows | - |
| P13 | UI: items list first page | 10,000 items | < 1 s | - |

Statement counts are asserted with a SQLAlchemy `before_cursor_execute` counter fixture (`tests/api_mfg`), which is
the "no N+1" proof. The counter wraps the service call only (auth/session statements of `require_user` and the
file-DB `BEGIN` are excluded), so the bounds are the same in single_user and accounts mode.

---

## 13. Work packages and file ownership

**Superseded by `docs/PLAN-M1.md`** (authoritative for ownership, order, milestones and acceptance; this section
keeps only the package scopes). Changes from the draft (review R3, R11): io tests move from `backend/tests/mfg/` to
`backend/tests/mfg_io/` (WP-B), import messages move to `sp/mfg/io/messages.py` (WP-B), release/document rules are
pure functions in `sp/mfg/release.py` (WP-A), `sp/manage.py` gets one guard in `cmd_reassign_owner` (WP-B, 14.1),
and WP-D also owns `frontend/e2e/accounts/mfg-*.spec.ts`.

| WP | Scope | Role |
|---|---|---|
| **WP-A** Backend domain + DB + samples | 3, 4, 5, 6, 7, 10 | backend-developer A, first |
| **WP-B** Backend API + import/export | 8, 9 | backend-developer B, after WP-A milestone A1 |
| **WP-C** Frontend Manufacturing area | 11 | ui-developer, parallel to A + B against 9.3-9.6 |
| **WP-D** QA and acceptance | 12, 15 | tester, writes from day 0, final runs last |

---

## 14. Changes to existing code and existing tests

### 14.1 Existing code (additive registration only)

| File | Change |
|---|---|
| `sp/api/main.py` | `from .mfg import router as mfg_router`; add `mfg_router.router` to `protected` (included with `require_user`, registered with `body_gate`) |
| `sp/api/db/models.py` | bottom: `from ..mfg import db_models as _mfg_db_models  # noqa` |
| `sp/api/db/__init__.py` | `load_all_models` imports `..mfg.db_models` |
| `sp/migrate.py` | `HEAD = "0003_mfg"` |
| `sp/manage.py` | `cmd_reassign_owner`: before moving anything, if the target user owns any row in an `mfg_*` table -> `CommandError` "the target user already has manufacturing data (<table>: n, ...); reset it in the app first" (exit 1, nothing moved, also in `--dry-run`). Without it the per-owner unique keys (`uq_mfg_plant_owner`, part numbers, codes) raise an `IntegrityError` traceback mid-command. Reads never create the plant row (3.3), so a target that only looked at the Manufacturing area is not blocked. |
| `backend/requirements*.txt`, `pyproject.toml` | three pins |
| `frontend/src/main.tsx`, `frontend/src/App.tsx` | route spread; nav link |

No change to engine, finance, intake, jobs, auth, config (no new settings: limits are constants), context, or
existing routes. The one behaviour change of existing code is the `reassign-owner` guard above (it can only trigger
when the target already owns mfg data, which cannot exist before M1); `test_manage.py` is unaffected (its target
has no mfg data) and the guard is tested in `backend/tests/api_mfg/test_mfg_manage.py`. Existing file-DB dev databases upgrade automatically (`behind` -> `upgrade head`, backup first, B
3.4); Postgres deployments run `python -m superplanner.migrate upgrade` (DEPLOY.md note: "M1 adds revision
0003_mfg"; WP-B adds one line to `docs/DEPLOY.md`).

### 14.2 Existing tests changed (only these; no existing assertion about existing behaviour changes)

| Test / file | Change | WP | Reason |
|---|---|---|---|
| `backend/tests/db/test_db_migrations.py:246,248` | `"code needs 0002_phase2b"` -> `f"code needs {migrate.HEAD}"` | A | new head |
| `backend/tests/jobs/test_worker_process.py:152` | `"0002_phase2b" in r.stderr` -> `migrate.HEAD in r.stderr` | A | new head |
| `backend/tests/auth/route_table.py` | add `MFG_PROTECTED` frozenset with the 77 operations of 9.3 | B | access table |
| `backend/tests/auth/test_route_coverage.py::test_enumerated_operations_equal_the_access_table` | `protected == PROTECTED` -> `protected == PROTECTED \| MFG_PROTECTED` (the `len(PROTECTED) == 55` assertion stays) | B | access table |
| `backend/tests/acceptance_phase2b/test_acc_authz_sweep.py` | `make_world` also loads sample `small` and creates one import session; `id_map` adds `item_id, bom_id, routing_id, group_id, line_id, shift_template_id, assignment_id, exception_id, skill_id, operator_id, tool_pool_id, import_id`; `body_for` returns valid mfg bodies (PUTs with `If-Match: "1"`, release/copy/commit `{}` + If-Match, mapping body); `/mfg/samples/` paths skipped like `/templates/` (not owned) and filled with `small` in the CSRF test; `snapshot` adds `GET /mfg/summary` | B | without this, `fill()` raises `KeyError` on the new path parameters; the sweep then proves mfg isolation too |

`OWNED_PARAMS` in `test_route_coverage.py` stays unchanged (mfg param names are not in it; the mfg cross-user matrix
lives in the extended acceptance sweep and in `tests/api_mfg/test_mfg_isolation.py`). If any other existing test
fails, the code is fixed, or the change is recorded in this table first (B 8.2 rule).

Frontend e2e: existing 65 + 7 specs unchanged; the finance spec's "exactly one nav item active" keeps holding.

---

## 15. Test strategy and acceptance

### 15.1 Backend pure (`backend/tests/mfg`, WP-A; run in both suites, no DB)

- `test_mfg_model.py`: every field constraint and model rule of section 3 (one valid + one invalid case per rule).
- `test_mfg_units.py`: aliases, conversion, mismatch.
- `test_mfg_bom.py`: effectivity selection (date boundaries inclusive/exclusive, serial override, overlap
  tie-break), explosion order/indent/`subtree_end`/`is_shared`, roll-up vectors T-Q1 and scrap/yield on/off,
  operation_seq consumption, uom conversion (wire MM -> M), alternates attached not counted, phantom indented vs
  summarized, cycle detection (self-loop, 2-cycle, long cycle, multiple SCCs, 5,000-node chain without recursion
  error), `would_create_cycle`, `refdes_count` (`R1-R5`, `R1-5`, `C1, C2 C3`, invalid tokens reported, `R1-R999999999`
  is one invalid token and returns in < 10 ms), explosion row limit hit on a 20-level diamond BOM in < 1 s without
  building the path list, summarized mode of the same BOM succeeds (path count 2^20 in `occurrences`).
- `test_mfg_routing.py`: `operation_minutes` (unit/panel/batch, speed), T-T1, `lot_inputs` rounding, eligibility.
- `test_mfg_calendar.py`: T-C1..T-C8, template validation (overlap with Sunday-night wrap, break outside shift,
  24 h shift), `expand_template_week`, `group_capacity` with parallel capacity, `operator_windows` (spans without
  breaks, night tail of the previous day).
- Skill-coverage vectors for `MFG_SKILL_NOT_ON_SHIFT` (T-S1..T-S6): S1 REG operators, REG line -> no issue (the
  operator's lunch differs from the line's: still covered, breaks ignored); S2 REG operators, line REG + optional EVE
  -> issue naming EVE Mon-Sat 18:00-22:00; S3 S2 plus one operator on EXT 09:00-22:00 -> no issue (overtime crew
  counts); S4 REG operators on a line with three break-free shifts 06-14, 14-22, 22-06 -> issue whose uncovered pieces
  are Mon 06:00-09:00, 18:00-09:00 (next day) starting Mon-Fri, and Sat 18:00-Sun 06:00 (a partial overlap no
  longer counts as covered); S5 handover gap of 10 min -> no issue (tolerance 15); S6 an
  assignment effective only from day 30 of the horizon -> issue found (real dates, not one reference week).
- `test_mfg_db_names.py`: every constraint/index name in `Base.metadata` for `mfg_*` tables <= 63 characters; every
  mfg table has an index led by `owner_id`; every FK column leads an index.
- `test_mfg_health.py`: each of the 40 codes: one fixture that raises it and one minimal change that clears it;
  ordering/truncation/counts; `small` = 0 issues; `medium`/`kavach` = 0 errors and the intended warnings.
- `backend/tests/mfg_io/test_mfg_io.py` (**WP-B**, pure): xlsx/csv/zip reading, magic detection, `.xls` refusal, zip limits (synthetic zip bomb: 1 KB
  compressed -> 1 GB declared is refused before decompression), `openpyxl.DEFUSEDXML is True`, Excel numeric part
  numbers, dates, booleans, lists, aliases, formula without cached value, mapping suggestions for typical ERP
  headers, `plan_import` create/update/unchanged/delete diff, idempotency (plan of an applied plan is all
  unchanged), released protection, cycle via file, duplicate keys, auto find numbers, export formula escaping
  (xlsx cell `=HYPERLINK(...)` stored as a string cell and read back unchanged; CSV `'` prefix stripped on read),
  xlsx with a cell at row 1,000,000 or column 200 refused, `1E999` -> `IMP_BAD_NUMBER`, `<v>NaN</v>` -> 422
  `MFG_IMPORT_FILE_INVALID` (not 500), `_x0000_`/control characters never reach staging, billion-laughs XML in a
  sheet refused, staged size limit.
- `test_mfg_samples.py`: golden hashes and counts; determinism under two different `PYTHONHASHSEED` values
  (subprocess); bundle -> dataset -> bundle round trip.
- `test_mfg_perf.py` (P1).

### 15.2 Backend API (`backend/tests/api_mfg`, WP-B; file-DB and PostgreSQL)

CRUD + ETag/If-Match/428/412 for every entity; check order (foreign id + missing If-Match -> 404); natural-key 409;
delete-in-use 409 matrix (6.3); BOM/routing document PUT (line id kept/new/removed; foreign line id -> 422);
release/supersede/obsolete/copy; released read-only; explosion/where-used/time-preview/windows endpoints against
the pure results; pagination and search (escaping `%`, `_`); import flow for xlsx, csv, zip (row errors, mapping
errors, expiry -> 404, second commit 409, If-Match on commit, transaction atomicity: a fault injected in
`writer.apply` after half the rows leaves zero mfg rows and the session `mapped`); export -> import into a second
user -> export equality; sample load (both modes, idempotent second load); reset; statement-count tests (12);
isolation (`test_mfg_isolation.py`: user B gets 404 for each of A's ids on every endpoint, lists exclude A's rows,
B's BOM referencing A's item id -> 422 `MFG_UNKNOWN_REFERENCE`, where-used of B's item never shows A's parents, A's
import session invisible to B, B's `reset` and B's sample `replace` leave A's row counts unchanged, A and B load the
same sample without key or id collisions); accounts mode CSRF on mfg unsafe routes; perf P2-P11. Also: GET
`/plant`, `/summary`, `/health`, `/items` on a fresh owner insert nothing (row counts of all `mfg_*` tables stay 0);
two concurrent first writes of one owner on Postgres both succeed (plant savepoint race, 6.1); a write waiting
behind a held plant lock with `lock_timeout` lowered to 200 ms answers 409 `MFG_BUSY` with `Retry-After`; export
`Content-Disposition` for a plant named `Werk "Süd"\r\nX` is a valid Latin-1 header with a slug name; upload with
`Content-Type: application/json` and a binary body is 422 from the middleware while `application/octet-stream`
works; `test_mfg_manage.py`: `reassign-owner` refuses a target with mfg data (exit 1, nothing moved) and moves
all `mfg_*` rows to an empty target.

### 15.3 Acceptance (`backend/tests/acceptance_m1`, WP-D) - Gate 1 exit criteria

1. Load `kavach` via API in an empty account -> health `ok == true`, 0 errors, intended warnings present.
2. Export xlsx -> import into a fresh account through the full wizard API (upload, mapping from suggestions without
   edits, preview 0 errors, commit) -> exports equal; explosion of `KV-TPU-1000` identical (rows, quantities).
3. Introduce each blocking defect class through the API (cycle attempt rejected 422; make item without routing;
   group without shift; buy item without lead time; unit mismatch; overlap; alternate without primary;
   uninterruptible burn-in on a REG-only group) -> health `ok == false` with exactly the expected codes and working
   `link`s (each link path matches a frontend route pattern of 11.1).
4. ECO flow: copy released BOM -> edit -> release with supersede at a future date -> explosion before/after that
   date differs as expected; where-used `include=all` shows both versions.
5. Hand-calculated checks: 10 explosion quantities and 10 operation times of the Kavach sample computed in the test
   by hand formulas (not by the library) match within 1e-9.
6. Performance P2, P5, P7, P9 on both databases.
7. Restart: data survives; migrations `0002 -> 0003` upgrade an existing 2b database (file-DB database with problems and
   finance data) without data loss and `downgrade 0002_phase2b` removes only `mfg_*` tables.

### 15.4 Frontend e2e (`frontend/e2e/mfg-*.spec.ts`, WP-D with WP-C helpers)

- `mfg-setup.spec.ts`: nav to Manufacturing (one active nav item); load `small` sample; items list search; item
  detail edit with 412 conflict banner (second tab edit); BOM tree expand/collapse; where-used; routing editor drag
  reorder (and keyboard move) -> saved order; time preview numbers for qty 100 match the API.
- `mfg-plant.spec.ts`: create template 3SHIFT in the editor, preview shows the night shift split across midnight;
  assign base/optional; calendar month shows windows; add holiday -> window disappears.
- `mfg-health.spec.ts`: break data (deactivate the only FCT line) -> health page shows `MFG_GROUP_NO_LINE`; "Fix"
  link opens the groups page with the line selected; fix -> health green.
- `mfg-import.spec.ts`: upload CSV with an unknown part number -> preview row error; upload corrected file ->
  commit; re-upload -> all unchanged.
- `mfg-scale.spec.ts`: load `kavach`; open `KV-TPU-1000` BOM tree; expand all; scroll to the end; assert DOM rows
  <= 80 and interaction timings (P12).
- `mfg-contract.spec.ts`: with `kavach` loaded, visit every page of 11.1 and every health `link`, fail on any
  unexpected 4xx/5xx (as the existing `contract.spec.ts`).
- `accounts/mfg-isolation.spec.ts` (accounts config): user A loads `small`; user B sees an empty Manufacturing
  overview, A's item URL shows "not found", B's import wizard upload works with the CSRF header.
- The e2e database is shared by all specs of a run: every mfg spec starts with `POST /mfg/reset` through the API
  helper, and no existing spec is affected by mfg data.

---

## 16. Deferred items and plug-in points

Deferred (documented, not built in M1): user-defined units and item-specific conversions; BOM `base_qty`;
line-level phantom override; component-to-operation consumption by routing alternates (only the primary routing is
used for `operation_seq`); setup matrices (only `setup_family` fields); operator leave/absence calendars, skill
levels; tooling calendars/maintenance; per-tool location; DST/IANA time zones; working-time lags; pg_trgm search
indexes; gzip of large JSON responses (enable at the reverse proxy: `gzip on; gzip_types application/json;`
suggested in DEPLOY.md); ECO approval workflow, roles and change audit UI (M2-M4); multi-plant; ERP connectors
(M5); `.xls` import; server-side prune of expired imports for inactive users (lazy per-owner prune on upload only);
mfg data in `manage.py`.

Plug-in points (designed now so M2/M3 add, not change):

| Later need | M1 hook |
|---|---|
| Inventory, POs, WOs, demand reference items | FK to `mfg_items.id` (owned); part number unique per owner |
| MRP explosion with dates | `BomIndex` per date, `explode(mode="summarized")`, `effective_bom(..., serial)` |
| Yield-inflated requirements, scrap | 4.4 formulas (`cumulative_yield`, `lot_inputs`) |
| Lot sizing | item `lot_rule`, `fixed_lot_qty`, `min_order_qty`, `order_multiple`, `safety_stock`, `lead_time_days`, `receiving_days` |
| Alternate components when short | `alternates[]` on explosion rows (priority order) |
| Gate 1 before runs | `run_health_check(...).ok`, `fingerprint(ds)` stored on M2/M3 runs |
| APS operation durations | `operation_minutes`, `to_engine_minutes`, `transfer_batch`, `interruptible`, `labor`, `crew_size` |
| Line selection and lot splitting | `eligible_lines`, `speed_factor`, `parallel_capacity`, `setup_family` |
| Optional overtime as a decision | `line_windows(kinds=...)` with `kind`, `cost_per_hour`, `max_hours_per_week` |
| Crews follow shifts | operators' template + shift names expanded with the same calendar code |
| Tooling constraints | `mfg_operation_tools` + `mfg_tool_pools.quantity` |
| Engine adapter | new module `sp/mfg/to_engine.py` (M3) maps a dataset + work orders to `engine.Problem`; `mfg` keeps no engine import until then |

---

## Review notes (team lead, 2026-10-25)

Reviewed against `docs/MANUFACTURING-GAP-ANALYSIS.md` (M1 scope, 4.1, 4.1a, 4.3, section 9 additions), `docs/PHASE2B.md`
(3.2-3.6, 4.7, 4.8) and the code (`api/db/ownership.py`, `api/db/models.py`, `api/db/session.py`, `api/limits.py`,
`api/context.py`, `api/main.py`, `api/auth/body_gate.py`, `manage.py`, `migrate.py`, `tests/auth/*`,
`tests/acceptance_phase2b/test_acc_authz_sweep.py`, `tests/db/test_db_migrations.py`). openpyxl 3.1.5 /
et-xmlfile 2.0.0 / defusedxml 0.7.1 were installed in a scratch directory (not the project venv) to check the
import-safety claims. The direction (relational master data, pure `mfg` core, versioned documents with effectivity,
Gate 1 health check, one bundle format for import/export/samples, no new npm packages) is right and is kept. The
changes below are applied in place in the sections named.

**R1 - Decision on the open item `MFG_SKILL_NOT_ON_SHIFT` (7.2 #24): intent accepted, mechanism replaced.** The
intent is right and needed: operators are matched to line shifts by time, so overtime crews (operators on an
extended template) count and no "crew belongs to shift X" link has to be maintained. The draft's mechanism
(a reference week; covered if *any* operator window overlaps a shift instance) is replaced, because:
(a) "the reference week" is undefined when assignments are effective-dated, lines override groups (the Kavach
SMT-3 override) and exceptions remove time; a single week also misses an optional shift that starts later in the
horizon. Now: the real dates `[as_of, as_of + horizon_days)`, the same `line_windows` the scheduler will use.
(b) "Any overlap" reports a REG 09:00-18:00 crew as covering a 06:00-14:00 and a 14:00-22:00 shift. Now:
uncovered time = line windows minus the union of qualified operators' windows.
(c) Operator windows are shift spans without breaks (crews stagger breaks); otherwise every lunch break that
differs from the line's break would be a false warning.
(d) A 15-minute tolerance absorbs handover gaps. (e) One issue per (skill, line), entity `skill`, instead of per
operation: in the Kavach sample one gap (COATING on EVE) would otherwise be reported for ~40 operations.
(f) Applies to operations with `crew_size > 0` (setup is always attended), so crew-0 unattended work is excluded.
It stays a **warning** (P2): presence is checked, crew counts and simultaneous use are M3 capacity constraints.
Checking the samples against the rule showed two gaps in the draft: the Kavach optional SMT Sunday shift had no
SMT operator (weekend crew added) and the `small` sample's FCT overtime had none (an EXT operator added, so
`small` stays issue-free). Test vectors T-S1..T-S6 in 15.1.

**R2 - Owned child tables (deviation from B 3.3): accepted.** The central `with_loader_criteria` filter then also
protects direct queries on child tables (where-used, import diffs) with no per-query code. Cost: index rules (R7).

**R3 - File ownership conflicts in the draft.** `tests/mfg/test_mfg_io.py` sat in WP-A's folder but tested
WP-B's `io` code; `messages.py` held messages of both packages; release rules were needed by the WP-B services, by
WP-B's `plan_import(release=true)` and by WP-A's sample golden tests. Fixed: `backend/tests/mfg_io/**` and
`sp/mfg/io/messages.py` belong to WP-B, the rules are pure functions in `sp/mfg/release.py` (WP-A). Section 13 now
defers to `docs/PLAN-M1.md`.

**R4 - Import/export security (verified, not assumed).** With openpyxl 3.1.5: `DEFUSEDXML` is true and the read-only
sheet parser's `iterparse` comes from defusedxml (XML bombs covered). But: (a) openpyxl writes any string starting
with `=` as a formula, so the draft's "prefix `'`" rule would either corrupt xlsx values or not protect; now explicit
string cells in xlsx and a stripped `'` prefix in CSV (8.3); (b) gaps in row numbers are yielded as empty rows (one
cell at row 200,000 gave 200,000 rows), so the row limit must count scanned rows and `iter_rows` is bounded;
(c) `<v>1E999</v>` comes back as `inf` (Postgres JSONB staging would fail with 500) and `<v>NaN</v>` raises
`ValueError` inside openpyxl (500 without a catch-all); both now map to row errors / 422; (d) uncompressed limit
lowered from 100 MiB to 64 MiB and a 32 MiB staged-JSON cap added; committed sessions drop their rows;
(e) `Content-Disposition` used the raw plant name (quotes/CRLF/non-Latin-1 break the header or raise); now a slug;
(f) an upload sent with a JSON content type is rejected by the existing NUL scanner in `api/limits.py` for any
binary file; the contract now says `application/octet-stream`.

**R5 - Primary-key collision.** `bundle_to_dataset` derives ids from natural keys; if those ids reached the DB, a
second user loading the same sample would hit a duplicate primary key (ids are global). The writer always uses
`new_id`.

**R6 - Plant row creation and `reassign-owner`.** "Created lazily on first access" meant GETs insert rows, two
concurrent first writes race on `uq_mfg_plant_owner` (Postgres), and `manage.py reassign-owner` (which moves
every owned table, `manage.owned_tables()`) would crash with an `IntegrityError` once the target owns a plant row
or a clashing part number. Now: reads never insert (default record with `row_version 0`), `lock_plant` creates the
row in a savepoint with retry, and `reassign-owner` refuses a target with mfg data (14.1, WP-B, tested).

**R7 - Indexes.** Five tables (`operations`, `operation_tools`, `line_items`, `shift_assignments`,
`operator_skills`) had no index led by `owner_id`, so `load_dataset`, reset and reassign would scan the whole table
across all users in accounts mode. `ix_mfg_bom_lines_child (owner_id, child_item_id)` cannot serve Postgres' FK
RESTRICT check on item delete (it has no owner predicate): changed to `(child_item_id)`, which also serves
where-used. `home_group_id` (SET NULL) got an index. Constraint names checked against the 63-character limit (the
longest generated FK name is 62).

**R8 - Performance at 5,000+ lines.** Path enumeration is exponential on shared sub-assemblies (a 20-level diamond
has 2^20 paths): indented explosion now stops at the row limit while generating, and `summarized` mode, the
documented fallback, is a DAG DP that never enumerates paths. `ref_designators` ranges like `R1-R999999999` would
have been expanded in `parse_refdes` (memory/CPU DoS through a 20-character field): counting is now arithmetic. The
health "in use" check evaluated reachability per effectivity date (dates x graph); it is now one union-graph
traversal plus per-item document checks. `MAX_EXPLOSION_ROWS` lowered from 50,000 (~30 MB JSON) to 20,000 (4x the
`kavach x2` size), also applied to indented where-used. Statement-count bounds corrected (routings and operations
are 2 SELECTs; IN chunks of 2,000; auth statements excluded from the counter).

**R9 - Locking and long writes.** Postgres sessions use `lock_timeout=10000`, but the draft's P7 import commit was
allowed 10 s while holding the plant lock: a concurrent write of the same user would have failed with an unmapped
`LockNotAvailable` (500). Now: parsing and planning run before the write transaction (re-planned under the lock only
if `data_version` changed), the lock is held < 6 s for 5,000 rows, and a lock timeout is 409 `MFG_BUSY` with
`Retry-After`. The writer flushes per sheet instead of relying on unit-of-work ordering without relationships, and
bulk deletes are ORM `delete()` statements (owner-filtered) with `passive_deletes`.

**R10 - Contract for parallel backend/frontend work.** `/meta`, `/summary`, import records/previews/results,
summaries, group detail, assignment/exception targets and window labels were only sketched; WP-C could not have
typed them. Section 9.6 fixes every shape and freezes them at milestone A1. The link table sent released BOM lines
to the edit route; they now go to the BOM view (`?line=`), which got that parameter. The skills page lists holders
(target of the R1 issue).

**R11 - Semantics fixes.** Health #9 compared "the fastest line" against "every line's window" (inconsistent); now
per line. The `status` column and the `release` option overlapped and obsolete documents could not be imported, so
the export -> import round trip (15.3 #2) was impossible for data with an obsolete version; defined in 8.1. List
fields replace as a whole on import. "Other lists are unpaginated (bounded by entity limits)" referred to limits
that did not exist: per-owner limits added for every entity.

**R12 - Tests.** Added: io safety cases (R4), skill-coverage vectors (R1), name/index rules (R7), reads-insert-nothing,
plant race, `MFG_BUSY`, reassign guard, two users loading one sample, reset isolation, an mfg contract e2e spec, an
accounts-mode mfg isolation spec, and a reset at the start of every mfg e2e spec (the e2e database is shared).

Checked and unchanged: the 77-operation count of 9.3; the existing-test edits of 14.2 match the code
(`tests/db/test_db_migrations.py:246,248`, `tests/jobs/test_worker_process.py:152`, `len(PROTECTED) == 55` stays,
the sweep's `fill()` would raise `KeyError` on mfg path parameters); other migration tests already use
`migrate.HEAD`; `test_manage.py` passes unchanged with the R6 guard; the new pins are pure-Python wheels
(Windows-compatible); `frontend/nginx.conf` allows 8 MB bodies (above the 5 MiB API limit).

---

## 17. Implementation notes

Developers write only to their own subsection (interpretations, measured numbers, deviations agreed with the lead).

### 17.WP-A Backend domain + DB

**A1 contract frozen (2026-10-25).** WP-B and WP-C can build against these files: `sp/mfg/model.py` (every
Input/Record, refs, `HealthIssue`/`HealthReport`, `Explosion`/`ExplosionRow`/`SummarizedRow`, `WhereUsed`, `OpTime`,
`Window`, `WeekWindow`, `TimePreview`), `sp/mfg/limits.py`, `sp/mfg/units.py`, `sp/mfg/bundle.py` (`SHEETS`,
`MfgBundle`, `BundleError`), `sp/api/mfg/db_models.py` (18 tables, `MFG_MODELS`/`MFG_TABLES` in FK order),
migration `0003_mfg` (`migrate.HEAD = "0003_mfg"`), and the signatures in `sp/api/mfg/repo.py`. The pins are
`openpyxl==3.1.5`, `et-xmlfile==2.0.0` and `defusedxml==0.7.1`. Record field sets follow M 3 / 9.6 with the
additions listed below. Every computation and loader of A2-A4 is implemented, not stubbed.

Deviations and interpretations (WP-A):
- **Schema.** `mfg_bom_lines` also has `ix_mfg_bom_lines_owner (owner_id)`. R7 moved `ix_mfg_bom_lines_child` to
  `(child_item_id)`, which left the table without an owner-led index, against the R7 rule that A1-2 asserts.
  `mfg_bom_lines`, `mfg_operations` and `mfg_operation_tools` carry `row_version`/`created_at`/`updated_at` like
  every non-link table (6.2 header). `mfg_operation_tools` has its own `id` PK; only the two link tables have
  composite PKs.
- **Text fields.** `Text500`, `note`, `description` and `ref_designators` allow tab, LF and CR. CR is added to
  the M 3.1 list so pasted Windows text and CSV cells round-trip; all other C0 characters are rejected.
- **Model optionals.** `BomInput.revision`/`version`, `RoutingInput.revision`/`version` and `BomLineInput.uom`
  are optional in Input and filled by the service (M 3.5/3.6 defaults). The Record overrides make them required.
  `PlantRecord.created_at`/`updated_at` are null for the unsaved default plant.
- **`TimePreviewOperation.group`** is the standard `{id, code, name}` ref (the 9.4 example shows `{id, code}`).
  `TimePreviewLine.reason` is null for eligible lines. Pure `routing.time_preview(ds, routing_id, qty)` builds the
  whole response.
- **`BomIndex(...)` / `ParentIndex(...)`** take extra keyword-only arguments (`routing_ids`, `on`, `serial` /
  `on`, `include`), which the explosion and where-used responses echo.
- **`find_cycles(edges, key=None)`** returns one closed cycle path `[a, ..., a]` per SCC (self-loop `[a, a]`).
  The path starts at the smallest node by `key` (health passes the part number). `would_create_cycle` returns
  the closed path `parent -> child -> ... -> parent`.
- **Where-used `include=effective`** keeps released BOMs whose date window contains `on`. `on` omitted means
  every released BOM; serial ranges are not filtered. `include=all` keeps draft + released BOMs.
- **Release.** `effective_from=None` in the release body keeps the document's own `effective_from`.
  `release.ReleaseError` (map to 422 `VALIDATION_ERROR`) is raised for `supersede_previous` without a date, or a
  date not before `effective_to`. Release-only issue codes `MFG_BOM_EMPTY` and `MFG_SERIAL_NOT_ALLOWED` use the
  health issue shape. `validate_*_document` error dicts carry a `type` that the service maps: `mfg_unknown_reference`
  goes to `MFG_UNKNOWN_REFERENCE`, `mfg_bom_cycle` to `MFG_BOM_CYCLE`, anything else to `VALIDATION_ERROR`.
- **Bundle value types.** Dates are `date`, datetimes are aware `datetime` in the plant offset, list columns are
  `list[str]` (`[]` when empty), breaks are `"name=HH:MM-HH:MM"` and tools are `"CODE:QTY"`. Item attributes are
  `attr:<name>` columns. The plant sheet does not carry plant `attributes`, so they are not exported and are not
  part of the fingerprint. The canonical order puts shifts in template order (not alphabetical), BOM lines in 3.5
  line order and operations by seq. Set-like lists (eligible families/part numbers, operator skills, shift names,
  tools) are sorted, so `dataset_to_bundle(bundle_to_dataset(b)) == b` for canonical bundles.
- **Health scope** (7.1 left these open):
  - *Relevant routings* are released routings of active, in-use make items whose window intersects the horizon.
    Their operations are the subjects of #5, #6, #7, #9, #10, #20, #21 and #24.
  - BOM-line errors #12, #13, #16 and #17 apply to released BOMs not ended before `as_of`. #18 applies to BOMs
    effective inside the horizon. #23, #33, #34 and #38 apply to those plus drafts.
  - #3, #19 and #28 are checked at `as_of` and at the item's own boundaries in the horizon. Their link goes to
    the routing/BOM tab, with `?routing=`/`?bom=` of the draft when one exists.
  - Overlaps (#14, #15) count only when the common window intersects the horizon.
  - #27 compares the assignment's raw optional minutes with the minutes left after base time, per affected line.
  - #22, #26 and #27 skip assignments that ended before `as_of`.
  - The #24 entity label is `"<skill> / <line>"`. One issue is raised per (skill, line).
- **Samples.** `small`'s BOM has 9 lines, one per component (M 10.2 says 8 lines but lists 9 components, and an
  unused component would be `MFG_ORPHAN_ITEM`). The Kavach group table lists 20 groups plus FINAL-TEST, which
  makes 21. To keep the 20 stages of A3-3, SUBTEST is folded into FINAL-TEST ("Test bay": FT-1, FT-2, ST-1, ST-2),
  so sub-assembly tests run there. With the routing structure described in 10.4, Kavach has 287 operations
  (target 450-650). The described PCB, harness, mechanical, programming and sub-assembly routings for 58 make
  items cannot reach 450 without inventing extra steps.

**A2-A4 delivered (2026-10-25).** Pinned sample values (`tests/mfg/test_mfg_samples.py`; identical under
`PYTHONHASHSEED=0` and `12345`; as_of 2026-11-02, horizon 90):

| Sample | Items | BOM lines | Other counts | Health (`by_code`) |
|---|---|---|---|---|
| `small` | 10 | 9 | - | none |
| `medium` | 171 (target ~200) | 260 (incl. the 70-line draft v2) | levels 0..3 | `MFG_LONG_LEAD_TIME` 1 |
| `kavach` | 1,199 | 2,469 | 63 BOMs, 61 routings (3 alternates), 287 operations, 20 groups, 50 lines, 35 assignments, 8 exceptions, 48 operators, 86 tool pools; explosion of KV-TPU-1000: 2,468 rows, levels 0..4, no warnings | `MFG_SKILL_NOT_ON_SHIFT` 1 (COATING / COAT-1), `MFG_DUPLICATE_COMPONENT` 1, `MFG_LONG_LEAD_TIME` 7 |
| `kavach x2` | - | 4,938 | - | - |

Measured on the development machine (pure, best of three):
- `explode` Kavach ~0.03 s; both TPU roots of `kavach x2` together ~0.05 s.
- `run_health_check` Kavach ~0.26 s.
- `build("kavach")` ~0.4 s (cached per process; `build` returns a deep copy).

Statement counts on both dialects (`tests/mfg_db/test_mfg_repo.py`):

| Loader | Statements | Bound |
|---|---|---|
| `load_dataset` | 17 | 19 |
| `load_bom_index_down` (Kavach, L = 4) | 15 | 18 |
| `load_parent_index` (KV-CAP-0402-100N, 3 levels up) | <= 8 | 11 |
| `bom_edge_list` | 1 | 1 |

Explosion rows from the loaders equal `BomIndex.from_dataset` at three dates.

Implementation details:
- Explosion rows are built with `model.construct_fast` (`model_construct` without default processing).
- WP-B: `repo.to_record(row, **extra)` needs the refs (`item`, `child`, `group`, ...) passed by the caller;
  counts default to 0. `load_dataset` fills everything through `dataset.link`.
### 17.WP-B Backend API + import/export

Status (2026-10-26): B1-B4 implemented. All 77 operations of 9.3 under `/api/v1/mfg` (`sp/api/mfg/router.py`,
registered in `main.py` with `require_user` and `body_gate`); services in `sp/api/mfg/services/` (common, items,
boms, routings, plant, resources, health, imports, samples), `writer.py`, `schemas.py`; pure import/export in
`sp/mfg/io/` (read, spec, mapping, plan, export, messages). `MFG_PROTECTED` (77 rows) and the extended authz sweep
are in the same change. Tests: `backend/tests/api_mfg/**`, `backend/tests/mfg_io/**`.

Interpretations and deviations (no path or field name of 9.3-9.6 changed):
- **Routing release response** is `{"routing": RoutingRecord, "superseded": [...]}` (as WP-C assumed); release
  responses carry the ETag of the released document.
- **Obsolete** is allowed only from `released` (draft -> 409 `MFG_INVALID_STATE`; drafts are deleted instead).
  Release of a non-draft -> 409 `MFG_INVALID_STATE`. DELETE of an obsolete document is allowed.
- **Copy** keeps the serial range and note, clears the dates, version = max for the (item, revision[, code]) + 1.
- **Document PUT**: a line/operation `id` that is not a child of this document (or listed twice) is 422
  `VALIDATION_ERROR` with `loc` `["body","lines",i,"id"]`. Kept children whose unique key changes (find-number or
  seq swaps from a drag reorder) are moved to placeholders first, so swaps never violate the unique keys.
  `MFG_BOM_CYCLE` details are `{"cycle": [part numbers, closed]}`; the self-loop is `["A","A"]`.
- **Plant PUT** with `If-Match: "0"` creates the row (`row_version` 1); a plant created implicitly by another
  write starts at `row_version` 1.
- **Import staging writes** (upload, mapping, delete of a session) do not lock the plant and do not bump
  `data_version` (not master data). Commit and sample load compare `(plant id, data_version)` with the read
  transaction and re-plan inside the lock only if it changed. A commit or sample load that changes nothing
  leaves `data_version` unchanged (re-import is a no-op apart from the import row and its audit event).
- **Commit re-plans from the staged rows** (the preview is informational); errors at commit time -> 409
  `MFG_IMPORT_HAS_ERRORS`. A row with a cell error (bad number/date/enum, control character, formula without
  value) is reported once and left out of the plan, so it does not also produce `IMP_REQUIRED`.
- **Blank version on import** (8.2): highest existing draft, else 1 if none, else - only when the file's content
  differs from the highest released/obsolete version - max + 1. This keeps a re-import of a version-less file
  with `release: true` idempotent instead of creating a new draft each time.
- **Blank cells** in mapped columns: a nullable field becomes null, a non-nullable one keeps its value (on create:
  the model default). Item `attr:<name>` columns: blank removes that attribute. Set-like lists (operator skills,
  line eligible part numbers) compare as sets.
- **replace_children** applies only when the child sheet (`bom_lines` / `operations`) is part of the import.
- **Release rules on import** (`status: released` or `release: true` on create) run on the planned dataset in
  file order with `supersede_previous = false`; failures are `IMP_RELEASE_BLOCKED` naming the health codes.
- **Cycle check on import** uses the final edge set (documents replaced by the file use their file lines). A BOM
  whose own rows have errors is left out of that edge set.
- **xlsx reading** uses openpyxl's worksheet parser directly (`ReadOnlyWorksheet._get_source` +
  `WorkSheetParser`, openpyxl 3.1.5 pinned): it yields only rows present in the XML, so a cell in row 1,000,000
  or column 200 is refused without iterating filler rows, and formulas without a cached value are detected.
  Excel date cells at midnight are staged as `YYYY-MM-DD`, others as `YYYY-MM-DD HH:MM:SS`; for exception
  start/end a date-only value is local midnight and a date-only end is inclusive. Cells over
  `IMPORT_MAX_CELL_CHARS` -> 422 `MFG_IMPORT_TOO_LARGE`; `IMP_TOO_LONG` is a field longer than its model allows.
- **CSV export escape**: a leading `'` is also added to values that start with `'` (and stripped once on read),
  so `'=x` round-trips. Lists are written `;`-separated. Exception datetimes are ISO text with offset in both
  formats; dates are date cells in xlsx. The zip has no README member; xlsx exports and templates have a README
  sheet (ignored on import with an `IMP_SHEET_IGNORED` warning). Single-CSV uploads use `?sheet=` (else the file
  stem) as the source sheet name.
- **Header suggestion by overlap** needs at least `min(2, number of key columns)` key columns and 2 mapped columns
  (the `items` sheet has a single key column).
- **Reset** deletes all 18 tables of the owner including `mfg_plant` and `mfg_imports` (so `reassign-owner` is
  not blocked afterwards). Sample `replace` resets in the same transaction and keeps `data_version` monotonic.
- **Lists** without a code (`/shift-assignments`) are sorted by target code, kind, effective_from;
  `/calendar-exceptions` by start. `/skills` and `/tool-pools` accept `q` as well.
- **MFG_BUSY** maps SQLSTATE 55P03 raised anywhere in a write transaction (also on reads that wait).
- **Repository**: the services only add small owned ORM queries next to `repo` (record refs, counts, the
  windows/time-preview mini snapshots); no change to WP-A files was needed.

Measured (developer machine, file-DB / PostgreSQL local): P2 Kavach explosion 0.36 / 0.26 s, 15 statements
(bound 18); `kavach x2` 0.35 / 0.25 s, 15-16 statements; P3 where-used indented 0.02 s, 8 statements; P4 items page
with `q` over 10,000 items 0.03 s, 5 statements; P5 health 0.44 / 0.46 s, 17-18 statements; P6 preview of 5,000
rows 0.20 / 0.21 s, 20-21 statements; P7 commit of 5,000 rows 0.83 / 1.26 s (write transaction 0.68 / 1.05 s);
P8 re-import 0.37 / 0.59 s with no master-data writes; P9 Kavach sample load 2.0 / 2.4 s; P10 xlsx export
1.2 / 1.1 s, 17-18 statements; P11 62-day windows 0.02 s, 6 statements.

**Fix round (2026-10-26; tester D1, team-lead review F1-F7).** Each fix has a regression test that failed on the
code before it (`backend/tests/api_mfg/test_mfg_review_fixes.py`, `backend/tests/mfg_db/test_mfg_repo_bfs.py`, the
D1 xfails of `acceptance_m1/test_acc_m1_adversarial_io.py` are now normal tests, new health cases in
`tests/mfg/test_mfg_health.py`). Interpretations:
- **D1 non-finite numbers.** `AttrValue` floats are `allow_inf_nan=False` (JSON `NaN`, `Infinity`, `-Infinity`,
  `1e999` -> 422 `VALIDATION_ERROR`, nothing stored) and integer attributes are bounded to +-`MAX_ATTR_INT`
  (2^53 - 1: larger integers would silently become rounded floats in JSON/JavaScript; previously `10**400` was
  accepted). Every other float of the Inputs and the float query parameters already has finite bounds (NaN fails
  every bound); import cells already turn non-finite numbers into `IMP_BAD_NUMBER`.
- **F1 explosion loader.** `load_bom_index_down` keeps an `expanded` set and expands every primary of a level not
  expanded yet (also one first loaded as an alternate); "primary" is now the row line of `split_alternates` (the
  same rule as `explode`: priority 1, defensively the lowest priority), so the loader and `BomIndex.from_dataset`
  agree also for groups without a priority-1 line. Statement bound unchanged (one level per BFS step).
- **F2 shift names.** A template PUT that removes or renames a shift still named by an assignment or an operator ->
  409 `MFG_IN_USE` (`details.references` counts, `details.shift_names` the missing names, `details.used_by`
  `[{type, id, label, shift_names}]`); assignments/operators with empty `shift_names` (= all shifts) never block.
  Import: the same final-state check (existing rows with the file's updates applied, so renaming the template and
  the assignment in one file works) gives row error `IMP_IN_USE` on the `shift_templates` row (or the first
  `shifts` row when the file has no template row); a commit with it is 409 `MFG_IMPORT_HAS_ERRORS` like every row
  error. New health errors `MFG_ASSIGNMENT_UNKNOWN_SHIFT` / `MFG_OPERATOR_UNKNOWN_SHIFT` (7.2 #41-42) catch data
  that predates the check; their entities (`shift_assignment`, `operator`) already have server links, so the UI
  needs no new link mapping.
- **F3 copy.** `copy_bom` runs `would_create_cycle` against the draft+released edge list for every source (an
  obsolete source is not in that list) -> 422 `MFG_BOM_CYCLE` with `details.cycle`, nothing inserted.
- **F4 first PUT /plant.** `repo.lock_plant_created(s) -> (row, created)` (`lock_plant` wraps it); `put_plant`
  compares `If-Match` with 0 only when this transaction inserted the row, else with the locked row's
  `row_version`. Two concurrent first-time `If-Match: "0"` PUTs on PostgreSQL: one 200, one 412 (tested with
  threads).
- **F5 serialized.** Item PUT `serialized: false` while draft or released BOMs/routings of it have a serial range ->
  409 `MFG_IN_USE` (`details.references` `{boms, routings}`, `details.used_by`); obsolete documents never block.
  Import: row error `IMP_IN_USE` on the item row for documents not in the file (documents in the file keep the
  existing `IMP_BAD_VALUE` check). `MFG_SERIAL_NOT_ALLOWED` is now also a health error (7.2 #43; released, not
  expired documents; entity item, link to the document) besides blocking release.
- **F6 date bounds.** `PlanDate` / `PlanDateTime` (`mfg/model.py`, bounds `MIN_DATE`..`MAX_DATE` in `limits.py`) on
  every date/datetime of the Inputs (`effective_from/to`, exception `start/end`), the release body
  `effective_from`, import option `default_effective_from` and the query parameters `on`, `as_of`, `from`, `to`
  -> 422 `VALIDATION_ERROR`. A datetime is checked on its own local date first and then its UTC date (so the check
  itself cannot overflow). Import datetime cells outside the range (or overflowing) -> `IMP_BAD_DATE`; date cells
  of document/assignment fields -> the Pydantic row error of the field. Internal day arithmetic in
  `calendar.py`/`health.py` uses `calendar.add_days`, which saturates at `date.min`/`date.max` instead of raising.
- **F7 plant offset.** Chosen: keep storing exceptions as UTC instants (no schema or API change; `start`/`end` are
  still returned in the plant offset) and **re-base** them when the offset changes: `PUT /plant` with a new
  `utc_offset` moves every exception by (old - new offset) in the same transaction, bumping their `row_version`
  (the audit event of the plant carries `rebased_exceptions`). Storing local wall-clock instead would have changed
  the column semantics, the repository, the import keys and every consumer for no gain at the API. Import: when
  the plant sheet changes the offset, existing exceptions are matched and diffed at their re-based instants (so a
  file that also lists them in local time creates no duplicates) and written with the re-based `start_at`/`end_at`;
  the preview carries warning `IMP_EXCEPTIONS_REBASED`.

### 17.WP-C Frontend

Status (2026-10-25): C0-C4 built against 9.3-9.6 (no backend router existed yet); cross-checked against WP-A's
`sp/mfg/model.py`. Files: `frontend/src/mfg/**`, `frontend/e2e/mfg-helpers.ts`, additive lines in `App.tsx` /
`main.tsx`. No new npm packages; `npm run build`, `npm audit` (0 vulnerabilities) and the existing Playwright suites
are the gate.

Interpretations (to confirm when B lands; none changes a documented field):
- Routing release (#25 "as BOMs") is typed as `{routing: RoutingRecord, superseded: [...]}`. The UI never reads
  the body of release/obsolete/copy beyond the new copy's `id`; it reloads the version list afterwards.
- Nullable per `model.py`: `Explosion.on`, `ExplosionWarning.item_id`, `Window.assignment_id`,
  `HealthIssue.link`, `HealthIssue.entity.id` (plant). `PlantRecord.data_version` is read when present.
- `TimePreviewOperation.group` is a full ref in `model.py`; the TS type keeps `name` optional because 9.4 shows
  `{id, code}`.
- `ImportRecord.created_at`/`committed_at` are optional in TS because the 9.4 example omits them;
  `ImportResult.counts[sheet]` is partial because the example shows `{}`.
- CSV upload: the `sheet` query value is a template sheet name from `meta.import_spec.sheets[].name`.
- "Fix the file and upload again": the wizard re-applies the previous mapping client-side by sheet name (else
  best header overlap) and exact header text, PUTs it right away, and opens the preview step.
- `/mfg/plant` -> `/mfg/plant/groups`, `/mfg/resources` -> `/mfg/resources/skills` (index redirects).
- BOM tree default "expanded to level 2" = levels 0-2 visible (rows at level >= 2 with children collapsed).
- Health "Fix" links render only `issue.link`; own navigation uses the builders in `src/mfg/lib/paths.ts`.
- The time preview shows the API numbers rounded to 6 decimals without thousands separators; the totals element
  also carries `data-fastest` / `data-slowest` with the raw values.

`data-testid`s: all of PLAN-M1 4.3 exist as named. Additional ones that D may use: `mfg-home-health` (`data-ok`),
`items-table`, `items-count`, `item-tab-{details|bom|where-used|routing}`, `conflict-reload`, `bom-search`,
`bom-mode-{indented|summarized}`, `bom-line-row`, `bom-line-add`, `bom-save`, `bom-release`, `bom-readonly`,
`bom-copy-banner`, `release-confirm`, `release-from`, `release-supersede`, `release-blocked`, `whereused-table`,
`whereused-mode-{single|indented}`, `whereused-include-{effective|all}`, `op-add`, `op-name`, `op-drag-handle`,
`routing-renumber-warning`, `routing-readonly`, `time-preview-op`/`time-preview-line`, `group-row`/`line-row`
(`data-group-id`/`data-line-id`, `.mfg-selected`), `line-form`, `line-active`, `template-new`, `template-pattern`,
`template-code`, `template-name`, `template-save`, `week-segment` (`data-day`, `data-shift`,
`data-split` = `start` (runs past midnight) / `end` (continued) / `both` / `none`), `assignment-new`,
`assignment-row`, `assignment-kind`, `calendar-line`, `calendar-month`, `calendar-day` (`data-date`,
`data-base-minutes`, `data-optional-minutes`), `exception-new`, `exception-from`/`exception-to`, `exception-label`,
`skill-holder`, `operator-row`, `tool-row`, `health-run`, `health-code-chip`, `health-filter-{error|warning|info}`,
`import-csv-sheet`, `import-upload-submit`, `import-preview-submit`, `import-reupload`, `import-errors-csv`,
`import-expired`, `mfg-reset`, `mfg-not-found`. `frontend/e2e/mfg-helpers.ts` wraps reset, sample load, lookups and
the common UI waits (single_user and accounts mode).

Measured against a contract-shaped mock API (Chromium, dev build): BOM tree with 2,409 rows - "Expand all" to all
rows rendered ~85 ms including Playwright round trips, at most 39 DOM rows while scrolled; items list with 10,001
items - first page and 200-row paging, at most 39 DOM rows. To be re-measured on the real backend by D (P12/P13).
The production bundle is 891 kB (673 kB before M1); the > 500 kB chunk warning predates M1.

### 17.WP-D QA and acceptance
