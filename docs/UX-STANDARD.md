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
- Strings of the shared components live in `lib/i18n.ts` (`t()`); page copy is still inline.
- All existing `data-testid`s are kept; new ones: `global-search`, `command-palette`, `command-input`,
  `help-button`, `display-menu`, `density-*`, `side-toggle`, `side-open`, `nav-group-overview`,
  `nav-group-supply`, `vt-columns`, `vt-export`, `sort-<column>`, `saved-views`, `toast`, `field-error`, `error-ref`.

## 9. Remaining gaps (prioritised)

1. Saved views and column layouts are per device; move them to a server-side user-preferences endpoint.
2. Bulk selection with bulk actions: no list has a bulk API today (e.g. firm/release several planned orders);
   add row checkboxes to `VirtualTable` when such endpoints exist.
3. Server-side sorting exists only where the API offers sort keys (items, work orders, purchase documents,
   MRP items/planned orders); demand, lots, transactions need API sort keys before headers become sortable.
4. Convert the remaining ~15 legacy filter toolbars and ~40 page headers to `FilterBar`/`PageHeader`
   components (they already inherit the compact styling through `.mfg-filters` / `.page-header`).
5. Gantt: bar-level keyboard navigation (`[` `]`) and announcements are in; keyboard move/resize of bars
   (today drag only) is not.
6. Unsaved-changes guard on work order, purchase document and plan-settings editors (they lack a dirty flag).
7. Page copy outside the shared components is not yet in `lib/i18n.ts`.
