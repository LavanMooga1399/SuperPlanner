# SuperPlanner UX standard

Scope: the whole frontend (`frontend/src`), with the Manufacturing area (`/mfg`) as the reference
implementation. Benchmarks: SAP Fiori Horizon, Oracle Redwood, Kinaxis Maestro, Siemens Opcenter APS; Linear
and Stripe for polish. Principle: quiet, dense, predictable. Neutral greys, one restrained accent, status colour
only where it carries meaning, always paired with text and an icon.

## 1. Audit (before), evidence from screenshots at 1440x900, 1024x768, 390x844

Screens captured: Manufacturing overview, Items, Work orders, Purchasing, Demand, MRP, Schedule runs, Gantt,
Inventory, Shop floor, Dashboard, KPIs, Data health, Work order detail, Scheduling plans home, phone app `/m`.
Before/after pairs of the key screens are in `docs/ux-screens/`.

| # | Gap (before) | Severity |
|---|---|---|
| G1 | Manufacturing navigation is four stacked horizontal tab strips (26 links) above every page: 330 px of the 900 px viewport at 1440, 400 px at 1024; on phones the strips scroll sideways and hide most sections. Content starts below the fold on tablets (Gantt). | Critical |
| G2 | No global search or quick navigation; reaching a work order or serial takes 3-4 clicks. No keyboard shortcuts besides table arrows. | High |
| G3 | Plant context, notifications, assistant and role sit in a loose row between nav and page, not in the header. No help entry point, no user/display menu in single-user mode. | High |
| G4 | Tables: no column sorting from headers, no column show/hide/reorder/resize, no saved views, no filter chips, no export of the visible list; fixed 32 px rows regardless of preference. | High |
| G5 | Filter bars use full-width labelled fields (search box 940 px wide), wasting a row of height per filter group; on phones filters take a full screen. | Medium |
| G6 | Loading states are a centred spinner with "Loading…" (layout shift when data arrives). | Medium |
| G7 | Success feedback is inconsistent (inline text, sometimes nothing); error banners do not show the server request id, so support cannot correlate. | Medium |
| G8 | Numbers and dates use the browser locale (`toLocaleString(undefined)`), so the same screen shows different formats on different PCs; timestamps use 12 h AM/PM. | Medium |
| G9 | Breadcrumbs only on 10 of ~60 Manufacturing pages; page headers vary (actions wrap under the title on some pages, page description sentences are long). | Medium |
| G10 | Theme toggle only light/dark (no "follow system" after first click); no density control; tokens limited to colour (no spacing, type, elevation or z-index scale); ~50 hard-coded hex colours in TSX. | Medium |
| G11 | No skip-to-content link; focus ring is a box-shadow that disappears on elements with their own shadow; some icon-only buttons rely on `title`. | Medium |
| G12 | Shop floor (tablet) and phone app `/m` are already purpose-built (48 px targets, large type); keep, align tokens only. | Low |

## 2. Design system decisions

Tokens live in `frontend/src/styles/theme.css` (single source). Old names (`--accent`, `--surface`, `--ok`, ...)
remain as the semantic layer so existing screens inherit the new values; new code uses the scales below.

- Colour: neutral slate greys; accent `--accent` (blue, light #1f5fbf / dark #6ea8fe) used for primary actions,
  selection and focus only. Semantic status pairs `--ok|--warn|--danger|--info` each with `-soft` background
  and `-border`; all text pairs meet WCAG AA 4.5:1 in both themes (checked with a contrast script, section 6).
- Typography: `Inter, "Segoe UI", system-ui` (no web font download: Inter is used when installed, otherwise
  the OS UI font). Scale `--fs-xs 11 / sm 12 / base 13 (compact) or 14 (comfortable) / md 15 / lg 18 / xl 22`.
  `font-variant-numeric: tabular-nums` on tables, KPIs and all numeric cells. IDs and part numbers in mono.
- Spacing: 4 px grid, `--sp-1..8` = 4, 8, 12, 16, 20, 24, 32, 40.
- Radius: `--radius-sm 4`, `--radius 6`, `--radius-lg 8`. Elevation: `--shadow-1` (cards, flat), `--shadow-2`
  (popovers), `--shadow-3` (dialogs). Z-index: header 30, sidebar 25, popover 40, drawer 45, modal 50, toast 60,
  palette 70.
- Focus: 2 px solid outline in `--focus-color` with 2 px offset (`:focus-visible` only); never removed.
- Density: `data-density="compact|comfortable"` on `<html>`; compact is the default for data screens
  (row 28 px, control 28 px), comfortable 36/32. Shop floor and phone app keep their own large targets.
- Theme: light / dark / system, persisted (`sp.theme`), system follows `prefers-color-scheme` live.
- Icons: the single inline icon set in `components/Icon.tsx`, 16 px in controls, 14 px in dense rows; no emoji.
- Motion: 120-160 ms fades only; `prefers-reduced-motion` disables all.

## 3. Screen anatomy (every page)

Shell header → left navigation (area pages) → breadcrumb → page header (title, key facts, primary action right,
secondary actions as default buttons) → filter bar (search, quick filters, chips, saved views) → content →
table footer (count, columns, export). One primary button per page header.

- Header (48 px): product mark, area switch (Scheduling / Finance / Manufacturing), global search
  (Ctrl/Cmd+K), plant switcher, assistant, notifications, help (shortcuts), display menu (theme, density),
  account menu.
- Manufacturing navigation: left sidebar, six role-oriented groups (Planning, Supply and stores, Production,
  Performance, Master data, Control), active state with accent bar and `aria-current`; collapsible to an icon
  rail (persisted), automatic rail below 1200 px, off-canvas drawer below 760 px.
- Breadcrumbs: generated from the route for every Manufacturing page (hidden where the page has its own
  record-level breadcrumb).

## 4. Components (shared)

| Need | Component | Notes |
|---|---|---|
| Data table | `mfg/components/VirtualTable.tsx` (extended) | sticky header, header sorting (server or client), column show/hide/reorder/resize persisted per table (`sp.table.<id>`), density-aware rows, CSV export of loaded rows, skeleton rows while loading, keyboard grid navigation |
| Filters | `components/FilterBar.tsx` | compact inline search + selects, active-filter chips with clear, saved views per page (`sp.views.<page>`) |
| Page header | `components/PageHeader.tsx` | title, facts, actions; breadcrumbs from `components/Breadcrumbs.tsx` |
| Command palette | `components/CommandPalette.tsx` | Ctrl/Cmd+K: pages, items, work orders, purchase orders, demand orders, serials via existing list endpoints with `q` |
| Shortcuts | `components/ShortcutsDialog.tsx` | `?` opens; `g` then a letter navigates; `/` focuses the page search |
| Toasts | `components/Toast.tsx` | polite live region, 5 s, success/info; errors stay as banners |
| Errors | `Banner`, `MfgError` | title says what happened, body what to do, plus "Reference" request id from `X-Request-ID` |
| Loading | `Skeleton` in `components/Skeleton.tsx` | page and table skeletons replace spinners for page loads |
| Formatting | `lib/locale.ts` | `en-IN`, 24 h, grouping; plant time zone for plant times |

## 5. Copy rules

Sentence case, short, domain terms (Work order, Purchase order, Demand order, MRP run, Schedule run, Line,
Operation). No exclamation marks, no "Oops". Errors: what happened + what to do. Empty states: what the list
holds + the one action that fills it.

## 6. Accessibility (WCAG 2.1 AA)

Skip link to `#main`; landmarks (`header`, `nav` "Main", `nav` "Manufacturing sections", `main`); every icon-only
button has `aria-label`; status chips carry icon + text; tables are ARIA grids with roving focus; Gantt bars are
focusable with arrow navigation; dialogs trap focus and restore it; live regions for toasts and save state;
contrast checked for text, status text on soft backgrounds and accent buttons in both themes.

## 7. Dependencies

No new npm packages. Everything above is built on React, react-router and CSS.

## 8. Implementation notes

- Unsaved-changes guard (`components/UnsavedChangesGuard.tsx`) is on the item, BOM, routing and demand-order
  editors. It does not prompt in automated browsers (`navigator.webdriver`), so scripted e2e runs behave as before.
- Inline server validation: wrap a form in `<FormErrors error={err}>`; every `Field`/`TextField`/`SelectField`
  with `name` (or a label matching the API field) shows its 422 message under the control with `aria-invalid`.
- Table column layout is per browser (`localStorage`), not per server account, because no preferences API
  exists and backend APIs were out of scope.
- Strings live in one dictionary, `lib/i18n.ts` (`t()`): shared components inline, navigation labels in
  `lib/strings/nav.ts` (read through getters, so a translation set with `setStrings()` applies), and page copy per
  area in `lib/strings/<area>.ts` (`mfg`, `floor`, `mobile`, `assistant`, `studio`, `finance`, `account`), keyed
  `<area>.<screen>.<kind>.<name>` (kinds: `title`, `desc`, `head`, `text`, `btn`, `label`, `hint`, `aria`, `empty`,
  `ph`, `toast`). Values go in as placeholders: `t("common.runNo", { n })` -> "Run #3", `common.scheduleNo`,
  `common.mrpRunNo`, `common.nOfM` ("{n} of {m}"); counts with a noun use `plural()`. Keys are typed (`StringKey`),
  so a missing key fails `tsc`. Where a local variable is called `t`, the function is imported as `tr`.
- Dates in UI text never show ISO: `formatDay()` (calendar date, no time-zone shift), `formatDateRange()`
  ("24 Oct – 22 Nov 2026", "1–22 Nov 2026"), `formatDate/DateTime` and the plant clock for instants. The sweep
  script fails a screen whose text contains `YYYY-MM-DD`.
- Narrow screens: a column with `drop: <rank>` leaves the default set, lowest rank first, while the default set
  is wider than the table (demand and work orders fit at 1024 px with the selection column); Columns shows it as
  "(narrow screen)" and an explicit choice wins (`shown` in the saved layout).
- The table styles (`.vt*`, `.card-table`) are global (`styles/shell.css`), so scheduling, finance and account
  screens use the same `DataTable`/`VirtualTable`.
- All existing `data-testid`s are kept; new ones: `global-search`, `command-palette`, `command-input`,
  `help-button`, `display-menu`, `density-*`, `side-toggle`, `side-open`, `nav-group-overview`,
  `nav-group-supply`, `vt-columns`, `vt-export`, `sort-<column>`, `saved-views`, `toast`, `field-error`, `error-ref`.

- Phone widths (< 768 px): lists render rows as cards through `VirtualTable card={{ title, status, actions,
  fields }}` (items, work orders, purchase orders, demand, stock, lots, ledger, planned orders, MRP items and
  messages, delivery schedule and every `DataTable`); tables return at 768 px and up. Empty card fields are
  left out.
- Short lists use `mfg/components/DataTable.tsx`: the same `VirtualTable` with `virtual={false}` (every row in
  the DOM, rows grow with `Column.wrap` text, no inner scroll, cards derived from the columns when `card` is
  omitted, `rowDetail` for a full-width explanation line such as why an order is late, `ShowMore` footer for
  paged lists). A data table that is the body of a card uses `section.card.card-table` (the card draws the
  frame).
- Default column widths must fit the content area at 1440 px including the selection column (about 1170 px
  with the sidebar); wider sets scroll horizontally at 1024 px.
- `DateInput` shows dates as en-IN ("21 Nov 2026") over the native picker; `plural()` in `lib/i18n.ts`.

## 9. Remaining gaps (prioritised)

Done in round 3: server-side preferences (tables, saved views, display) with local cache and one-time
migration (`lib/serverPrefs.ts`, one index request per load); row selection and bulk actions on work orders,
purchase requests/orders and demand (`mfg/components/BulkActions.tsx`); sorting on demand, lots and
transactions; `PageHeader`/`FilterBar` on all list and area pages incl. finance, landing, intake, orgs and
account; Gantt keyboard move (Alt+Left/Right by zoom step, Shift+Alt+Up/Down to another line) through the
drag preview; unsaved-changes guard on work order, purchase document and plan editors; shared `DateInput`.

Done in round 4: plain tables moved onto the shared table (column settings, client sorting, CSV, skeleton and
empty states, phone cards): audit trail, MRP runs, KPI by line / stage, adherence, top scrap and downtime,
recalls (list, affected stock, per customer, per programme, units), transfers (list, lines), suppliers, item
suppliers, members, locations, serials, schedule runs, schedule orders and demand, shop-floor events, change
requests, risk checks, calendar exceptions, skill holders, shortages (short parts, overdue deliveries),
kitting check, work-order stock movements, item stock and open supply/demand, ERP deliveries, batches, events,
reconciliation list and results. Status quick filters (KPI period, transfers direction, change-request status,
delivery status) sit in the `FilterBar` as segmented `btn-group`s. Manufacturing copy and navigation keyed in
`lib/i18n.ts`.

Done in round 5: the remaining read-only tables are on the shared table: change-request impact (structure
changes, open orders, purchases, phased-out parts, date moves), replanning changes and proposals, shop-floor
overview, work-order operations (both variants), ERP integration (who owns what, webhooks, batch records, file-drop
inbox / recent files / mappings), scheduling run history and the per-task comparison, finance result history,
explanation assumptions and the review cash flow, API tokens. Row sub-lines use `.vt-sub`; in-page tabs rendered
as buttons look like link tabs. Copy of the floor, phone app, assistant, scheduling studio, finance and account
areas is keyed; "Run #", "Schedule #", "N of M" and hand-written plurals are interpolated. Demand and work-order
lists fit at 1024 px. ISO dates removed from UI text (KPI period, floor queue, phone work order, recall units).
The two failing specs are fixed (see 9.2).

1. Plain tables kept on purpose: editable grids (routing operations, document and posting lines, BOM lines,
   line rates, import / intake column mapping, shift assignments, scheduling tasks, resources and dependencies,
   finance asset classes and glide path, code mappings, dashboard targets, change-request documents with their
   disposition selects, transfer and receive dialogs), print layouts (dispatch list, traveller, labels, org
   dashboard matrix), pivot and compare matrices (setup matrix, MRP item plan buckets, demand projection, MRP and
   schedule compare, overtime, A/B schedule measures, scenario compare, contribution per month), confirm-dialog
   summaries, the shop-floor tablet (`floor-table`) and the screen-reader tables behind charts.
2. Organisation pages (org overview, plants, org members) still use plain tables; next candidates.
3. Copy built from several values in one sentence (e.g. "since 10:20, back 12:00") and strings in `.ts` helper
   modules (status labels in `floorText`, `formatM2`) are inline; the per-area maps cover JSX copy.
4. Gantt keyboard resize (change duration) is not offered: the edit API moves operations, it has no
   duration edit.
5. The trace and dispatch toolbars stay plain forms (submit-based search, print layout); styled alike.
6. Record headers (work order, item, purchase document, demand order, plan workspace, finance result) use the
   `ws-header` record anatomy rather than `PageHeader` by design (editable title, status chips).

### 9.1 Consistency sweep log (round 4)

Screens: every Manufacturing area page plus the Scheduling and Finance landing pages at 1440, 1024 and 390,
light and dark (kavach sample, MRP run and a schedule run loaded). Fixed:

- KPIs at 1024: period buttons and plant scope were header actions; the scope select wrapped onto its own
  full-width row. Both are now labelled fields in the filter bar (segmented period, scope select).
- Work orders at 1440 with selection: the Source column was clipped; default widths now total about 1110 px
  including the checkbox, and the status column fits "Planned (firm)".
- MRP runs: the Keep column fell off the right edge at 1440 and the run link collapsed to "R" next to the
  Latest / Out of date badges; widths rebalanced, badges no longer shrink inside table cells.
- Phones: the overview's planning card header ("Schedule production", "MRP run #1 ...") and the plant split
  pane pushed the page 85 px / 23 px wider than the screen; card headers wrap and split panes may shrink.
- Schedule run and MRP run headers: "Export CSV (zip)" was a borderless small text button next to bordered
  buttons of another size; both exports are now default buttons with the download icon.
- Floor event log: the When cell wrapped to three lines and "by" lines started with a stray separator; the
  recorded time is a sub-line and the people column joins only present parts.
- Titles: "People & tooling" and "Import / export" now match the navigation ("People and tooling",
  "Import and export"); the row counter says "1 row", not "1 rows"; top scrap says "1 unit".
- Inventory stock, lots, ledger, planned orders, MRP items and messages and the delivery schedule had no
  phone cards (tables scrolled sideways at 390); they now render cards; planned-order cards keep the select
  box.
- Dark theme: no unreadable colours found on the swept screens (status badges, links and the accent buttons
  keep contrast).

### 9.2 Test data fixes (round 5)

- `mfg-m2-mrp` "pilot journey": the sample was anchored to this week's Monday, so on late weekdays the first buy
  order's release date had already passed ("start in past" instead of "release now"). The test now loads the
  sample anchored to today; product behaviour unchanged.
- `m5-integration` "trace tree ...": a test issue, not a product bug. It traced the S0 fixture serial `srl_x`,
  which the real trace API (correctly) answers with 404. The test now makes its own data: the sample's finished
  good becomes lot-controlled, a released work order receives its output into a fresh lot (trace: lot -> work
  order, exact), a recall is built from that lot, and a change request with a draft BOM copy is created for the
  impact view. Transfers need a second plant of an organisation (not available in single-user mode), so that
  step checks the list and its empty state. The whole spec now runs through recall, ECO, transfers and audit.
- `explore` (three tests) expected the New York summer offset (-04:00) for a plan created today; it now accepts
  EDT or EST and checks the screen shows the same offset as the API.

### 9.3 Sweep log (round 5)

Screens: KPIs, demand, work orders, replanning, shop-floor overview, work order detail, ERP integration (overview,
webhooks, file drop), change requests, shortages, Scheduling and Finance landing pages at 1440 / 1024 / 390, light
and dark; script checks for page overflow and ISO dates found none. Fixed on the way: change-request tabs drew
button borders (now link-style tabs); KPI period shows "24 Oct – 22 Nov 2026"; demand list scrolled sideways at
1024 (programme, type, lines and priority leave the default set there); batch-record result filters moved into the
filter bar as a segmented control.

## 10. Backend support (API contract for the UI)

All paths under `/api/v1`; errors use the usual envelope `{"error": {"code", "message", "details"}}`; responses
carry `X-Request-ID`. Session users only where noted (API tokens get 403 `TOKEN_SCOPE`).

### 10.1 Per-user preferences (closes gap 1)

Personal, not per workspace (`X-SP-Workspace` is ignored): the same layout follows the person across browsers and
plants. Session users only (403 `TOKEN_SCOPE` for API tokens). Not audited, not touched by the data reset.

| Call | Result |
|---|---|
| `GET /me/preferences?prefix=table.` | `{"items": [{"key", "row_version", "size_bytes", "updated_at"}], "total", "limits": {"max_keys": 200, "max_bytes": 32768}}` (no values; sorted by key) |
| `GET /me/preferences/{key}` | `{"key", "value", "row_version", "size_bytes", "updated_at"}` + `ETag: "<row_version>"`; 404 `NOT_FOUND` if unset |
| `PUT /me/preferences/{key}` body `{"value": <any JSON>}` | create: no `If-Match` (or `If-Match: "0"`) -> 201; replace: `If-Match: "<row_version>"` -> 200. Existing key without If-Match -> 428 `PRECONDITION_REQUIRED`, stale -> 412 `VERSION_MISMATCH`; both carry `details.current_version` |
| `DELETE /me/preferences/{key}` + `If-Match` | 204; 404 if unset; 428 / 412 as above |

- Key: 1-128 chars `A-Z a-z 0-9 . _ : -`, starting with a letter or digit (else 422 `VALIDATION_ERROR`).
  Suggested keys: `table.<tableId>` (columns, widths, order, sort), `views.<page>` (saved filter views),
  `display` (theme, density, sidebar rail).
- Limits: a value is at most 32 KB as compact UTF-8 JSON (413 `PREF_TOO_LARGE`, `details.max_bytes`); at most 200
  keys per person (409 `PREF_TOO_MANY` on a new key; updating an existing key always works).
- Suggested client pattern: read on first use, keep `localStorage` as a cache/fallback, debounce writes (~1 s),
  on 412 re-read and re-apply the local change.

### 10.2 Bulk actions (closes gap 2)

`POST /mfg/bulk/<collection>/<action>` with exactly the permission of the single call:

| Path | Permission | Extra body fields |
|---|---|---|
| `/mfg/bulk/work-orders/release` | `wo_edit` | `reserve` (bool), `override_reason` (<= 200, applied to each short WO) |
| `/mfg/bulk/work-orders/close`, `/cancel` | `wo_edit` | - |
| `/mfg/bulk/purchase-requests/submit` | `pr_edit` | - |
| `/mfg/bulk/purchase-requests/approve` | `pr_approve` | - |
| `/mfg/bulk/purchase-requests/reject` | `pr_approve` | `reason` (required, 1-500) |
| `/mfg/bulk/purchase-orders/cancel` | `po_edit` | - |
| `/mfg/bulk/demand-orders/close`, `/cancel` | `demand_edit` | - |

- Body: `{"items": [{"id": "wko_...", "row_version": 3}, ...], ...extra}`; 1-200 items, ids distinct (else 422).
  `row_version` is the If-Match of each record.
- Each record runs the single-record service call in its own transaction (same state rules, shortage override,
  self-approval, integration ownership, audit event and outbox message). One failure never rolls back others.
- Response 200 (also when every record failed), results in request order:
  `{"action": "work-orders/release", "total", "succeeded", "failed", "results": [{"id", "ok", "status", "code",
  "message", "row_version", "record_status", "details"}]}`. On success `status` 200, `code`/`message`/`details`
  null, `row_version` the new version, `record_status` the record's new status. On failure `status`/`code`/
  `message`/`details` are what the single call would have returned (e.g. 412 `VERSION_MISMATCH` with
  `row_version` = current version, 409 `MFG_INVALID_STATE`, 409 `WO_KIT_INCOMPLETE` -> offer `override_reason`,
  409 `PUR_SELF_APPROVAL`, 404 `NOT_FOUND`).
- Whole-request errors: 403 `MFG_FORBIDDEN` (permission), 422 `VALIDATION_ERROR` (body / key), 401 / CSRF.
- `Idempotency-Key` (optional, 1-128 `A-Z a-z 0-9 . _ : -`, per plant and person, 24 h): a retry with the same key
  and body returns the stored response with `Idempotent-Replay: true`; another body -> 409
  `INV_IDEMPOTENCY_CONFLICT`; while the first request still runs -> 409 `MFG_BULK_IN_PROGRESS` (`Retry-After: 5`).
  Send a fresh key per user click.

### 10.3 Sort keys (closes gap 3)

`sort` query parameter, `-` prefix = descending, unknown value -> 422:

| List | Keys (default first) |
|---|---|
| `GET /mfg/demand-orders` | `number`, `-number`, `customer`, `priority`, `status`, `-created_at`, `due_date`, `-due_date` (earliest line due date) |
| `GET /mfg/lots` | `expires_on` (nulls last), `-expires_on`, `lot_code`, `-lot_code`, `received_on`, `-received_on`, `part_number`, `-created_at` |
| `GET /mfg/inventory/transactions` | `-seq` (newest first), `seq`, `-txn_date`, `txn_date`, `part_number`, `txn_type`, `-qty`, `qty` |

Existing: items (`part_number`, `-updated_at`, `description`), work orders (`start_date`, `due_date`, `number`,
`priority`), purchase documents (`-created_at`, `number`, `next_dock_date`), balances, MRP lists.
