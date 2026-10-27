# SuperPlanner M1 - Delivery Plan ("describe the plant and the product")

> **Historical note (PostgreSQL-only release):** "file-DB" below refers to the embedded file database of earlier
> releases. It was removed; SuperPlanner now runs on PostgreSQL only (see `docs/DEPLOY.md`, Changelog, and
> `docs/ARCHITECTURE.md` section 25). Statements about file-DB behaviour describe the past.

Owner: team lead (LEAD). Contract: `docs/M1-DESIGN.md` (cited "M n", including its "Review notes" R1-R12), then
`docs/PHASE2B.md` ("B n") and `docs/ARCHITECTURE.md` ("A n") for everything M does not change. Product direction:
`docs/MANUFACTURING-GAP-ANALYSIS.md` (phase M1, acceptance gate 1 "master data valid"). If this plan and M disagree on
behaviour, M wins; on file ownership, order and acceptance, this plan wins (it supersedes M 13). Developers write
only to their own subsection of M 17 (WP-A -> "17.WP-A", WP-B -> "17.WP-B", WP-C -> "17.WP-C", WP-D -> "17.WP-D").
LEAD owns M 0-16, the review notes and this file.

Hard rules for everyone:
- No `git commit`, no `git push`.
- **file-DB + one process + `AUTH_MODE=single_user` stays the zero-setup default** and must work on Windows with only
  Python and Node. The Manufacturing area works there with no extra setup.
- Existing features keep working. An existing test may change only as listed in M 14.2; any other change is
  recorded in M 14.2 by LEAD *before* the test is edited. No existing assertion changes.
- New Python packages: only `openpyxl==3.1.5`, `et-xmlfile==2.0.0`, `defusedxml==0.7.1` (pinned by WP-A in
  `backend/requirements.txt`, `backend/requirements-runtime.txt`, `backend/pyproject.toml`), installed into
  `backend/.venv`. **No new npm packages** (no virtualisation, grid, drag-and-drop or date library).
- One schema revision, `0003_mfg` (down_revision `0002_phase2b`), written by WP-A only. After milestone A1 the
  schema is frozen; a needed column/index is a change request to LEAD, who updates M 6 first and then has WP-A
  edit `0003_mfg` (still unreleased, so it is edited in place; never a second parallel revision).
- Local PostgreSQL for development and tests: never run `initdb`/`postgres` as root; the script creates and uses the
  OS user `spdb`. Agents put the data directory under their session scratchpad:
  ```
  backend/scripts/pg_dev_cluster.sh init  <scratchpad>/pgdata 54329    # create (idempotent) + start + role sp_test
  backend/scripts/pg_dev_cluster.sh start <scratchpad>/pgdata 54329    # after a restart
  export SP_TEST_PG_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres
  ```
  (`docs/DEPLOY.md` section 2.)
- Nobody edits `docs/source/**`, existing e2e specs/helpers, or the shared presentational components under
  `frontend/src/components/**`.

## 0. Overview

| WP | Name | Owner role | Starts | Depends on |
|----|------|-----------|--------|------------|
| A | Domain model, pure computations, health check, DB schema + migration + repository, sample generators | backend-developer (A) | day 0, first | M 3-7, 10 |
| B | REST API, import/export, sample load/reset endpoints, registration, `manage.py` guard | backend-developer (B) | after milestone **A1** (contract frozen) | A1; A2/A3/A4 per milestone below |
| C | Frontend Manufacturing area `/mfg` | ui-developer | day 0, parallel to A + B against M 9.3-9.6 | contract only; integrates per B milestone |
| D | Testing: acceptance suite (Gate 1 exit criteria), e2e specs, performance, final gates | tester | day 0 (writing), final runs last | all |

```
A1 contract freeze ─┬─► A2 pure core ─► A3 health + samples ─► A4 repository loaders ──────────────┐
                    └─► B1 CRUD + registration ─► B2 documents + views ─► B3 import/export/samples ─► B4 perf ─┤
C0 shell + types (day 0) ─► C1 items (needs B1) ─► C2 BOM/routing (B2) ─► C3 plant/resources (B1/B2) ─► C4 health/import (B2/B3) ─┤
D test writing (day 0) ───────────────────────────────────────────────────────────────────────────────► D final runs ─► LEAD review
```

B2 needs A2 (computations) and A4 (loaders); B3 needs A3 (samples) and the `bundle.py` SHEETS spec from A1. Where
B needs a WP-A function that is not yet implemented, B works against the frozen signature and its acceptance waits.

### 0.1 File ownership (authoritative; no file has two owners at the same time)

Paths relative to the repo root; `sp/` = `backend/superplanner/`.

| WP | Owns (create/edit only these) |
|----|-------------------------------|
| A | `sp/mfg/**` **except** `sp/mfg/io/**`; `sp/api/mfg/__init__.py`, `sp/api/mfg/db_models.py`, `sp/api/mfg/repo.py`; `sp/migrations/versions/0003_mfg.py`; `backend/tests/mfg/**` (pure, no DB), `backend/tests/mfg_db/**` (migration, schema rules, repository, lock/race tests; own `conftest.py` with `db_url_factory("mfgdb")`); additive lines only: `sp/migrate.py` (`HEAD = "0003_mfg"`), `sp/api/db/models.py` (registration import at the bottom), `sp/api/db/__init__.py` (`load_all_models` import + docstring table count); `backend/requirements.txt`, `backend/requirements-runtime.txt`, `backend/pyproject.toml` (the three pins); existing-test edits marked A in M 14.2 (`tests/db/test_db_migrations.py:246,248`, `tests/jobs/test_worker_process.py:152`) |
| B | `sp/mfg/io/**` (incl. `io/messages.py`); `sp/api/mfg/schemas.py`, `sp/api/mfg/services/**`, `sp/api/mfg/writer.py`, `sp/api/mfg/router.py`; `backend/tests/api_mfg/**` (own `conftest.py`, `db_url_factory("apimfg")`), `backend/tests/mfg_io/**` (pure io tests); additive lines only: `sp/api/main.py` (import router, add to `protected`), `sp/manage.py` (the `cmd_reassign_owner` guard of M 14.1), `docs/DEPLOY.md` (one line about revision `0003_mfg` and one line suggesting proxy gzip for JSON); existing-test edits marked B in M 14.2 (`tests/auth/route_table.py`, `tests/auth/test_route_coverage.py::test_enumerated_operations_equal_the_access_table`, `tests/acceptance_phase2b/test_acc_authz_sweep.py`) |
| C | `frontend/src/mfg/**` (incl. `mfg.css`, `api/contractExamples.ts`); `frontend/e2e/mfg-helpers.ts`; additive lines only: `frontend/src/main.tsx` (spread `mfgRoutes`), `frontend/src/App.tsx` (`MainNav` link + `isMfgPath`, Scheduling active only when neither finance nor mfg is) |
| D | `backend/tests/acceptance_m1/**` (own `conftest.py`, `db_url_factory("accm1")`), `frontend/e2e/mfg-*.spec.ts`, `frontend/e2e/accounts/mfg-*.spec.ts`, M 17.WP-D |

### 0.2 Ownership and contract rules

- **Contract freeze at A1.** The models of M 3, the response shapes of M 9.6, the endpoint table M 9.3 and the
  error codes M 9.2 are the contract between B and C. A change is a request to LEAD, who edits M first and tells
  B, C and D; nobody adds, renames or removes a response field on their own.
- Shared files get only the additive lines listed in 0.1; nothing else in them changes. `sp/api/main.py` and
  `sp/manage.py` are touched by B only; `sp/migrate.py` and `sp/api/db/*` by A only; `App.tsx`/`main.tsx` by C only.
- Test helper module names are unique across `backend/tests` (`--import-mode=importlib` with folder `sys.path`
  inserts): `mfgdb_helpers.py` (A), `apimfg_helpers.py` (B), `accm1_helpers.py` (D). WP-D imports nothing from
  other packages' test folders.
- **Route and access table move together** (B): every mfg route lands in the same change as its entry in
  `MFG_PROTECTED` and, if it has a path parameter, its id in the authz sweep's `id_map` / `body_for`; otherwise
  `test_enumerated_operations_equal_the_access_table` or the sweep's `fill()` fails and G1 is red.
- C never edits backend files and develops against M 9.3-9.6 (typed examples in `contractExamples.ts`, then the
  real backend as B milestones land). C publishes the `data-testid` list of 4.3 for D; renaming one needs D's
  agreement.
- D never edits product code or other packages' tests; defects go to the owner named in the failing criterion.
- Every package keeps G1-G3 green at every hand-over (section 1).

## 1. Regression gate (each package runs G1-G3 before handing in a milestone; D runs all at the end; LEAD checks)

Baseline (2026-10-25, given): **2005** backend tests pass on file-DB, **2044** on PostgreSQL, **65** Playwright
tests (single_user) and **7** (accounts), all green.

| # | Gate | Command / check |
|---|------|-----------------|
| G1 | Full backend suite on file-DB, inline, single_user: the 2005 existing tests pass, total = 2005 + new, 0 failures, skips only with a stated reason | `cd backend && .venv/bin/pytest` |
| G2 | Full backend suite on PostgreSQL (queue + embedded workers): the 2044 existing tests pass, 0 failures | `cd backend && SP_TEST_DB=postgres SP_TEST_PG_URL=postgresql+psycopg://sp_test:sp_test@127.0.0.1:54329/postgres .venv/bin/pytest` |
| G3 | No existing assertion changed: `git diff -U0 backend/tests frontend/e2e` touches only the files/lines of M 14.2 (plus new files) | LEAD reads the diff |
| G4 | Playwright single_user: the 65 existing tests pass unchanged, plus the new `mfg-*.spec.ts` | `cd frontend && npm run e2e` |
| G5 | Playwright accounts: the 7 existing tests pass, plus `accounts/mfg-*.spec.ts` | `cd frontend && npm run e2e:accounts` |
| G6 | `npm run build` (incl. `tsc --noEmit`, which also type-checks `src/mfg/api/contractExamples.ts`) clean; `npm audit` reports no high/moderate; `git diff frontend/package.json frontend/package-lock.json` empty | `cd frontend && npm run build && npm audit` |
| G7 | Zero-setup: fresh checkout flow of DEPLOY.md section 1 (no `DATABASE_URL`, no Postgres): API starts, `/mfg` works without login, sample `small` loads | D scripted check |
| G8 | Migration safety: an existing 0002 file-DB database with problems, schedules and finance data upgrades on first start to `0003_mfg` with a `.bak-0002-*` backup (online backup API) and unchanged row counts; `python -m superplanner.migrate check --url <pg>` exits 0 after `upgrade`; `downgrade 0002_phase2b` removes exactly the 18 `mfg_*` tables on both dialects | `backend/tests/mfg_db/test_mfg_migration.py` (A) + acceptance 15.3 #7 (D) |
| G9 | Pins: `pip install -r backend/requirements.txt` into a fresh venv succeeds, `pip check` clean, the three new packages are pure-Python wheels (`py3-none-any`) | D records the output |

## 2. WP-A - Domain, DB, repository, samples (backend-developer A, first)

### A1 - Contract freeze (first milestone; B starts when LEAD accepts it)

Steps:
1. Pins (0.1) and `pip install` into `backend/.venv`.
2. `sp/mfg/limits.py` (every constant of M 2), `units.py` (M 3.2), `model.py` (all common types and every
   `<Entity>Input`/`<Entity>Record` of M 3, `HealthIssue`, `HealthReport`, `Explosion`, `WhereUsed`, `OpTime`,
   `Window`, `WeekWindow`, `TimePreview` row types), `dataset.py` (dataclasses; `BomIndex`/`ParentIndex`
   constructors), `bundle.py` (`MfgBundle`, `SHEETS` spec of M 8.2 with key columns and dependency order).
3. `sp/api/mfg/db_models.py`: the 18 tables of M 6.2 with the index rules of M 6.2/R7, `OwnedMixin` on every table,
   relationships `lazy="raise"` + `passive_deletes=True`, `mfg_plant.data_version`. Registration lines in
   `api/db/models.py` and `api/db/__init__.py`.
4. `sp/migrations/versions/0003_mfg.py`: literal `op.create_table` definitions in the FK order of M 6.2, reverse
   drops in `downgrade()`; `migrate.HEAD = "0003_mfg"`; the two existing-test edits marked A.
5. `sp/api/mfg/repo.py`: implemented now: `plant_or_default`, `lock_plant` (savepoint race handling, `data_version`
   bump), `get_row`; the loaders (`load_dataset`, `load_bom_index_down`, `load_parent_index`, `bom_edge_list`,
   `to_record`) with final signatures and `NotImplementedError` bodies.
6. `samples.build("small")` (deterministic; M 10.2 incl. the R1 operator set).

Acceptance (tests in `backend/tests/mfg_db/` unless stated):
- A1-1 G1 and G2 green. The existing `tests/db/test_db_migrations.py::test_upgrade_head_and_create_all_produce_the_model_schema`
  and `::test_both_paths_give_identical_indexes` pass unchanged on both dialects (migration == metadata, no
  `compare_metadata` diffs).
- A1-2 `test_mfg_db_names.py`: all mfg constraint/index names <= 63 characters; each `mfg_*` table has an index led
  by `owner_id`; each FK column leads an index (M 6.2 index rules).
- A1-3 `test_mfg_migration.py`: upgrade 0002 -> 0003 of a file-DB database with 2b data keeps all row counts and writes a
  backup; `downgrade 0002_phase2b` drops exactly the 18 mfg tables and keeps everything else; both dialects.
- A1-4 `lock_plant`: on Postgres two threads doing the first write of one owner concurrently both commit, exactly one
  plant row exists, `data_version` = 2; `plant_or_default` on a fresh owner inserts nothing.
- A1-5 `python -c "import superplanner.mfg"` imports neither `fastapi`, `sqlalchemy` nor `superplanner.api` /
  `superplanner.engine` (test in `tests/mfg/test_mfg_layering.py` via `sys.modules` in a subprocess).
- A1-6 `bundle_to_dataset(build("small"))` succeeds; every Input model round-trips `model_validate(record.model_dump())`.

### A2 - Pure computations

Steps: `bom.py` (effectivity, `explode` indented/summarized with the R8 complexity rules, `where_used`, `bom_edges`,
`find_cycles` iterative Tarjan, `would_create_cycle`, `refdes_count`), `routing.py`, `calendar.py` (incl.
`operator_windows`), `release.py` (M 4.2 rules, `validate_bom_document`/`validate_routing_document`), `fingerprint`.

Acceptance (`backend/tests/mfg/`, run in both suites):
- A2-1 Vectors pass exactly: T-Q1 (`429.202609`, lot inputs 107/107/103), T-T1 (`153.0`), T-C1..T-C8 (M 4.6),
  T-S1..T-S6 (M 15.1).
- A2-2 Cycles: self-loop, 2-cycle, long cycle, multiple SCCs, 5,000-node chain without `RecursionError`.
- A2-3 R8: a 20-level diamond BOM: `explode(indented)` raises `ExplosionTooLarge` in < 1 s; `explode(summarized)`
  returns `occurrences == 2**20` for the leaf in < 1 s; `refdes_count("R1-R999999999")` returns in < 10 ms with
  one invalid token.
- A2-4 Release rules: every blocking condition of M 4.2 has one blocked and one passing case; supersede sets
  `effective_to` only on earlier-starting overlapping documents.
- A2-5 P1: pure `explode` of Kavach / `kavach x2` < 0.15 s / < 0.3 s (`test_mfg_perf.py`, marked `slow` if > 5 s).

### A3 - Health check and samples

Steps: `health.py` (all 40 codes of M 7.2 incl. the R1 rule for #24, ordering, truncation, `link` per M 11.3 incl.
the released-BOM-line rule), `messages.py`; samples `medium`, `kavach`, `scale()`; golden values.

Acceptance:
- A3-1 `test_mfg_health.py`: for each of the 40 codes one fixture raises it and one minimal change clears it;
  order, truncation at `MAX_HEALTH_ISSUES`, complete `counts`/`by_code`; every `link` matches a route pattern of
  M 11.1.
- A3-2 Samples on `as_of=2026-11-02`, horizon 90: `small` has zero issues; `medium` and `kavach` have zero errors
  and **exactly** the intended `by_code` key sets of M 10.3/10.4 (Kavach: `MFG_LONG_LEAD_TIME`,
  `MFG_SKILL_NOT_ON_SHIFT` (count 1, skill COATING, line COAT-1), `MFG_DUPLICATE_COMPONENT`).
- A3-3 Kavach counts inside the M 10.4 ranges (items 1,150-1,500, BOM lines 2,200-2,700, explosion rows
  2,300-3,000, 20 groups, 5 levels); `kavach x2` has >= 4,000 BOM lines.
- A3-4 Golden `sha256(canonical_json(bundle))` and per-sheet counts pinned for each sample; identical under
  `PYTHONHASHSEED=0` and `=12345` (subprocess); `dataset_to_bundle(bundle_to_dataset(b)) == b`.
- A3-5 `run_health_check` on Kavach < 1.0 s pure (the API target P5 is 2 s).

### A4 - Repository loaders

Steps: `load_dataset` (<= 18 SELECTs + plant), level-wise `load_bom_index_down` / `load_parent_index` (M 6.4),
`bom_edge_list`, `to_record` with `as_utc`.

Acceptance (`backend/tests/mfg_db/`, both dialects, data written through ORM rows in a test helper):
- A4-1 `BomIndex`/`ParentIndex` from the loaders equal `BomIndex.from_dataset` / `ParentIndex.from_dataset` for Kavach
  at three dates (explosion rows identical).
- A4-2 Statement counter: `load_bom_index_down` for Kavach <= 3 x (L + 1) + 3; `load_parent_index` for the most shared
  capacitor <= 3 x L + 2; `load_dataset` <= 19; accidental lazy load raises (relationships `lazy="raise"`).
- A4-3 Owner isolation at repository level: with user B bound, every loader returns nothing of A's data.

## 3. WP-B - API, import/export (backend-developer B, after A1)

### B1 - Router, registration, simple CRUD

Steps: `router.py` + `schemas.py` + services for `meta`, `summary`, `plant`, `items` (list/search/filters/paging),
`groups`, `lines` (incl. eligibility), `shift-templates` (+ `preview`), `shift-assignments`, `calendar-exceptions`,
`skills`, `operators`, `tool-pools`; check order of M 9.1; ETag/If-Match; natural-key 409; delete-in-use 409
(M 6.3); per-owner limits (`MFG_LIMIT`); `MFG_BUSY` mapping; audit. Register in `main.py` (`protected` + `body_gate`).
Route table and authz sweep edits for these routes (0.2).

Acceptance (`backend/tests/api_mfg/`, both dialects):
- B1-1 G1-G3 green, including `test_enumerated_operations_equal_the_access_table` with `PROTECTED | MFG_PROTECTED`
  and the extended authz sweep (anonymous 401 on every mfg route, other user 404 with identical bodies for every
  path id, CSRF/Origin 403 on every unsafe mfg route).
- B1-2 For each entity: create/get/put/delete with ETag; missing If-Match -> 428; stale -> 412 with
  `current_version`; foreign id + missing If-Match -> 404 (lookup before precondition); malformed path id -> 404.
- B1-3 GET `/plant`, `/summary`, `/items`, `/meta` on a fresh owner insert no rows in any `mfg_*` table; PUT `/plant`
  with `If-Match: "0"` creates it.
- B1-4 Search escaping: `q="%"`, `q="_"`, `q="\\"` match literally on both dialects; `limit` 201 -> 422.
- B1-5 `MFG_BUSY`: on Postgres, with a test-lowered `lock_timeout` (200 ms) and another session holding the plant
  lock, a write answers 409 `MFG_BUSY` with `Retry-After: 5`.
- B1-6 `/meta` contains every field of M 9.6 `Meta`, including `limits.max_body_bytes`.

### B2 - BOM/routing documents and computed views

Steps: BOM and routing document CRUD (line/operation ids kept/new/removed), `release`/`obsolete`/`copy` via
`release.py`, cycle rejection on every write, `explosion`, `where-used`, `time-preview`, `lines/{id}/windows`,
`health`.

Acceptance:
- B2-1 Document PUT: kept line ids keep their ids, omitted ones are deleted, a line id of another BOM (or another
  user's) -> 422; released -> 409 `MFG_RELEASED_READONLY`; any write that would create a cycle -> 422
  `MFG_BOM_CYCLE` with the cycle path, also for drafts.
- B2-2 ECO flow: copy -> edit -> release with supersede at a future date -> explosion before/after differs;
  where-used `include=all` shows both versions.
- B2-3 API results equal the pure results (explosion, where-used, time preview, windows, health) for Kavach.
- B2-4 Statement counts (counter around the service call): explosion <= 3 x (L + 1) + 3; where-used indented
  <= 3 x L + 2; items page <= 5; health <= 20; windows <= 6.
- B2-5 `MFG_EXPLOSION_TOO_LARGE` for indented explosion and indented where-used over 20,000 rows; `summarized`
  works on the same data.

### B3 - Import/export, samples, reset, manage.py guard

Steps: `sp/mfg/io/**` (read, spec, mapping, plan, export, messages) per M 8 incl. R4; import endpoints (upload,
mapping/preview, commit with plan-outside-lock + `data_version`, delete, expiry, prune); `export`,
`import-templates`; `samples` list/load (`replace`), `reset`; `writer.py` (per-sheet flush, ORM deletes,
`new_id` always); `manage.py` guard; DEPLOY.md lines.

Acceptance:
- B3-1 `backend/tests/mfg_io/`: every case of M 15.1 `test_mfg_io.py` (zip bomb refused before decompression, row
  1,000,000 / column 200 refused, `1E999` -> `IMP_BAD_NUMBER`, `<v>NaN</v>` -> `MFG_IMPORT_FILE_INVALID`, NUL never
  staged, billion-laughs refused, `.xls` refused, `openpyxl.DEFUSEDXML is True`, xlsx string `=HYPERLINK(..)`
  round-trips as a string cell, CSV `'` prefix round-trips).
- B3-2 Import flow for xlsx, csv and zip: row errors with sheet/row/column; mapping two columns to one field -> 422;
  commit with errors -> 409; second commit -> 409 `MFG_IMPORT_ALREADY_COMMITTED`; expired -> 404; committed session
  has no staged rows; re-import of the same file -> all `unchanged`, no `row_version` changes.
- B3-3 Atomicity: a fault injected in `writer.apply` after half the rows leaves zero new mfg rows and the session
  `mapped`.
- B3-4 Round trip: export of Kavach -> import into a second user -> export equal (CSV zip byte-equal; xlsx compared
  as parsed bundles); includes an obsolete and a draft document.
- B3-5 Samples: `small`, `medium`, `kavach` load into an empty user with health `ok`; second load all `unchanged`;
  `replace: true` resets first; two users load the same sample without collisions; B's reset leaves A's counts
  unchanged.
- B3-6 `Content-Disposition` for plant name `Werk "Süd"\r\nX` is a valid Latin-1 header with a slug; upload with
  `Content-Type: application/json` and a binary body -> 422 from the middleware, `application/octet-stream` works;
  body over `MAX_BODY_BYTES` -> 413.
- B3-7 `test_mfg_manage.py`: `reassign-owner` to a target with mfg rows -> exit 1, message names the tables,
  nothing moved (also `--dry-run`); to an empty target -> all `mfg_*` rows moved, the target sees the data in the API.
  The existing `tests/auth/test_manage.py` passes unchanged.

### B4 - Performance

Acceptance (`backend/tests/api_mfg/test_mfg_perf.py`, both dialects; Postgres limits x 1.5 except P7): P2-P11 of M 12;
P7 asserts both the end-to-end time and the write-transaction time (< 6 s). Measured numbers go to M 17.WP-B.

## 4. WP-C - Frontend Manufacturing area (ui-developer, day 0, parallel)

### C0 - Shell and contract (day 0, no backend needed)

Steps: `src/mfg/routes.tsx` with every route of M 11.1 (placeholders allowed), `MfgLayout` sub-nav, `App.tsx` nav
link + `isMfgPath`, `main.tsx` spread; `api/types.ts` (M 3, 5, 7, 9.6), `api/client.ts` (`mfgRequest` with the
existing envelope parsing, `mfgUpload` with `application/octet-stream`, `mfgDownload` with the
Content-Disposition file name, one function per endpoint of M 9.3); `api/contractExamples.ts` typing every JSON
example of M 7.1 and 9.4 and one example per shape of M 9.6 (no `any`, no casts).

Acceptance: G6 green; exactly one `aria-current="page"` nav item on `/`, `/finance` and `/mfg` (the existing finance
e2e keeps passing); G4 existing 65 tests unchanged and green.

### C1 - Items (after B1)

Steps: `VirtualTable` (M 11.4: fixed rows, overscan 10, sticky header, `aria-rowcount`/`aria-rowindex`, keyboard),
`ItemsPage` (debounced search, filters, paging by 200), `ItemShell` + `ItemDetailsTab` (edit with If-Match, 412 ->
conflict banner with reload), `MfgHome` (summary, sample loader, export), `ItemPicker`.

Acceptance: with 10,000 items the list shows the first page < 1 s (P13) and never renders more than 80 DOM rows;
a 412 shows the conflict banner and does not lose the user's edits until they choose reload.

### C2 - BOM and routing (after B2)

Steps: `BomTab` (versions, actions, `BomTree` with `subtree_end` collapse, expand all / to level N, search reveal,
`?line=` select), `BomEditPage` + `BomLinesGrid` (released banner + Copy), `WhereUsedTab`, `RoutingTab` +
`RoutingEditor` (HTML5 drag and drop **and** Move up/down buttons, renumber, warning when BOM lines reference seqs),
`OperationTimePreview`.

Acceptance: Kavach tree "Expand all" < 100 ms after data arrives, interactive < 1 s, <= 80 DOM rows, no long task
> 100 ms while scrolling (P12); keyboard-only reorder of operations saves the new order; time-preview numbers equal
the API response.

### C3 - Plant and resources (after B1; windows after B2)

Steps: `GroupsPage` (groups with nested lines, `?group=`/`?line=` select and scroll), line form (speed, capacity,
eligibility, setup family), `ShiftsPage` + `ShiftTemplateEditor` + `ShiftWeekPreview` (debounced POST preview,
night shifts split across midnight), assignments table, `CalendarPage` + `LineCalendar` (<= 62 days per call),
`PlantSettingsPage`, `SkillsPage` (holders of the selected skill), `OperatorsPage`, `ToolingPage`.

Acceptance: every jump-to-fix link of M 11.3 opens the page with the entity selected and visible; a 3-shift
template preview shows the night shift split across midnight; adding a holiday removes that day's windows in the
month view.

### C4 - Health and import (after B2/B3)

Steps: `HealthPage` (as-of, horizon, counts, filter chips, `HealthIssueList`, Fix links from `issue.link` only),
`ImportWizard` steps Upload -> Map -> Preview -> Done (state in the URL and the server record; client-side size
check from `/meta`; virtualised row-error table; "Download errors as CSV"; commit disabled while `error_count > 0`;
"Fix the file and upload again" keeps the mapping by header names), template and export downloads.

Acceptance: reloading the browser at each wizard step restores it; commit is impossible with errors; the UI never
builds a health link itself (code review by LEAD: no route strings for health entities outside `routes.tsx` /
route builders).

### 4.3 `data-testid` contract (C provides, D uses)

`nav-mfg`; `mfg-subnav-{overview|items|plant|resources|health|import}`; `sample-load-{id}`, `sample-replace-{id}`;
`items-search`, `items-row` (with `data-part-number`); `item-save`, `conflict-banner`; `bom-tree`, `bom-tree-row`
(with `data-row`, `data-level`), `bom-expand-all`, `bom-collapse-all`, `bom-version-{id}`; `whereused-row`;
`routing-op-row` (with `data-seq`), `op-move-up`, `op-move-down`, `routing-save`; `time-preview-qty`,
`time-preview-total`; `shift-week-preview`, `line-calendar`, `exception-save`; `health-status` (`data-ok`),
`health-issue` (with `data-code`), `health-fix-link`; `import-file-input`, `import-preview`, `import-row-error`,
`import-commit`, `import-result`; `mfg-export`.

## 5. WP-D - Testing (tester, day 0 writing, final runs last)

Steps:
1. Day 0: `backend/tests/acceptance_m1/` with own conftest; modules whose target milestone is not yet accepted are
   skipped with a visible reason (`pytest.importorskip("superplanner.api.mfg.router")` or a milestone marker), so
   G1/G2 stay green while writing. Hand formulas for 15.3 #5 written independently of the library.
2. Acceptance tests M 15.3 #1-#7 (one module each, both dialects).
3. e2e specs M 15.4 (`mfg-setup`, `mfg-plant`, `mfg-health`, `mfg-import`, `mfg-scale`, `mfg-contract`) and
   `accounts/mfg-isolation.spec.ts`, using `mfg-helpers.ts` (C) and the testids of 4.3; each spec starts with
   `POST /mfg/reset` (shared e2e database).
4. Final runs: G1-G9 on a clean tree; performance numbers P1-P13 and the gate outputs recorded in M 17.WP-D; each
   failure reported to the owning WP with file:line and the failing command.

Acceptance (LEAD checks):
- D-1 Gate 1 exit criteria (M 15.3): #1 Kavach loads with health ok and the exact intended warnings; #2 export ->
  full wizard import into a fresh account with suggested mapping unedited -> equal exports and identical explosion;
  #3 each blocking defect class gives `ok == false` with exactly the expected codes and links that match frontend
  route patterns; #4 ECO flow; #5 ten explosion quantities and ten operation times equal hand formulas within 1e-9;
  #6 P2, P5, P7, P9 on both dialects; #7 restart and 0002 -> 0003 upgrade without data loss, downgrade removes only
  `mfg_*`.
- D-2 All new e2e specs green in G4/G5; the existing 65 + 7 unchanged and green.
- D-3 A UI/API contract run (`mfg-contract.spec.ts`) with zero unexpected 4xx/5xx over every page and every health
  link of the Kavach sample.
- D-4 G1-G9 green and recorded.

## 6. Hand-over and review

- Each milestone hand-in: the package's acceptance tests named above, G1-G3 results (counts), and notes in its M 17
  subsection (interpretations, measured numbers). LEAD accepts or returns with findings.
- A1 acceptance unblocks B; LEAD announces the contract freeze to B, C and D.
- Final LEAD code review (code-review mode) after D-4: correctness first (effectivity, quantities, windows, health
  codes reported as ok when data is invalid, cycle checks, concurrency under the plant lock), then security
  (ownership of every table and route, import limits), then maintainability.
