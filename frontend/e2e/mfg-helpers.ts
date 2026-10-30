/**
 * Manufacturing (M1) e2e helpers, provided by WP-C for the WP-D specs (PLAN-M1 4.3, M1-DESIGN 15.4).
 * Every mfg spec should start with `resetMfg(request)` because the e2e database is shared by all specs.
 *
 * single_user config: the API is called directly on :8000 (no CSRF).
 * accounts config: pass `{ accounts: true }`; calls go through the Vite origin (session cookie of the
 * browser context) and unsafe methods carry the current `X-CSRF-Token`.
 */
import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";

export const MFG_DIRECT = "http://127.0.0.1:8000/api/v1/mfg";
export const MFG_RELATIVE = "/api/v1/mfg";
export const RESET_PHRASE = "DELETE ALL MANUFACTURING DATA";

/** The 4.3 data-testid contract, for reference in specs. */
export const MFG_TESTIDS = {
  nav: "nav-mfg",
  subnav: (s: "overview" | "items" | "plant" | "resources" | "health" | "import") => `mfg-subnav-${s}`,
  sampleLoad: (id: string) => `sample-load-${id}`,
  sampleReplace: (id: string) => `sample-replace-${id}`,
  bomVersion: (id: string) => `bom-version-${id}`,
} as const;

export interface MfgOptions {
  accounts?: boolean;
}

function base(opts?: MfgOptions): string {
  return opts?.accounts ? MFG_RELATIVE : MFG_DIRECT;
}

async function csrfHeaders(request: APIRequestContext, opts?: MfgOptions): Promise<Record<string, string>> {
  if (!opts?.accounts) return {};
  const r = await request.get("/api/v1/auth/session");
  const s = (await r.json()) as { csrf_token: string | null };
  return s.csrf_token ? { "X-CSRF-Token": s.csrf_token } : {};
}

/** Any mfg call; asserts the status when `status` is given and returns the parsed JSON (or null for 204). */
export async function mfgCall(
  request: APIRequestContext,
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  init: { data?: unknown; headers?: Record<string, string>; status?: number } & MfgOptions = {},
): Promise<unknown> {
  const headers = { ...(method === "GET" ? {} : await csrfHeaders(request, init)), ...(init.headers ?? {}) };
  const r = await request.fetch(`${base(init)}${path}`, { method, data: init.data, headers });
  const text = await r.text();
  if (init.status !== undefined) expect(r.status(), `${method} ${path} -> ${r.status()} ${text.slice(0, 300)}`).toBe(init.status);
  else expect(r.ok(), `${method} ${path} -> ${r.status()} ${text.slice(0, 300)}`).toBeTruthy();
  return text ? JSON.parse(text) : null;
}

export async function mfgJson<T = unknown>(request: APIRequestContext, path: string, opts?: MfgOptions): Promise<T> {
  return (await mfgCall(request, "GET", path, opts)) as T;
}

/** `POST /mfg/reset` (9.3 #77). */
export async function resetMfg(request: APIRequestContext, opts?: MfgOptions): Promise<void> {
  await mfgCall(request, "POST", "/reset", { data: { confirm: RESET_PHRASE }, ...opts });
}

/** `POST /mfg/samples/{id}/load` (9.3 #76); returns `{sample_id, result, health}`. */
export async function loadSample(
  request: APIRequestContext,
  sampleId: "small" | "medium" | "kavach",
  replace = true,
  opts?: MfgOptions,
): Promise<{ sample_id: string; health: { ok: boolean; counts: { error: number; warning: number; info: number } } }> {
  return (await mfgCall(request, "POST", `/samples/${sampleId}/load`, { data: { replace }, ...opts })) as {
    sample_id: string;
    health: { ok: boolean; counts: { error: number; warning: number; info: number } };
  };
}

export interface ItemLite {
  id: string;
  part_number: string;
  row_version: number;
  make_buy: string;
}

/** The item with exactly this part number (search + exact match). */
export async function findItem(request: APIRequestContext, partNumber: string, opts?: MfgOptions): Promise<ItemLite> {
  const page = await mfgJson<{ items: ItemLite[] }>(request, `/items?q=${encodeURIComponent(partNumber)}&limit=200`, opts);
  const it = page.items.find((x) => x.part_number === partNumber);
  expect(it, `item ${partNumber} exists`).toBeTruthy();
  return it as ItemLite;
}

export interface CodeLite {
  id: string;
  code: string;
  row_version: number;
}

/** A group / line / skill / tool pool / shift template by code. */
export async function findByCode(
  request: APIRequestContext,
  list: "/groups" | "/lines" | "/skills" | "/tool-pools" | "/shift-templates" | "/operators",
  code: string,
  opts?: MfgOptions,
): Promise<CodeLite> {
  const r = await mfgJson<{ items: CodeLite[] }>(request, list, opts);
  const x = r.items.find((i) => i.code === code);
  expect(x, `${list} ${code} exists`).toBeTruthy();
  return x as CodeLite;
}

/** A PUT with If-Match from the record's own row_version (`body` must be the full Input model). */
export async function mfgPut(request: APIRequestContext, path: string, body: unknown, version: number, opts?: MfgOptions): Promise<unknown> {
  return mfgCall(request, "PUT", path, { data: body, headers: { "If-Match": `"${version}"` }, ...opts });
}

// ---------------------------------------------------------------- UI helpers
/** Open a Manufacturing page and wait for the sub-navigation. */
export async function gotoMfg(page: Page, path = ""): Promise<void> {
  await page.goto(`/mfg${path}`);
  await expect(page.getByTestId("mfg-subnav-overview")).toBeVisible();
}

/** Exactly one main-nav item carries `aria-current="page"`, and it is `testId`. */
export async function expectActiveNav(page: Page, testId: "nav-scheduling" | "nav-finance" | "nav-mfg"): Promise<void> {
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
  await expect(page.getByTestId(testId)).toHaveAttribute("aria-current", "page");
}

/** Rows currently in the DOM for a virtual table (never more than ~80, M 11.4). */
export async function domRowCount(page: Page, rowTestId: "items-row" | "bom-tree-row" | "whereused-row" | "import-row-error"): Promise<number> {
  return page.getByTestId(rowTestId).count();
}

/** Scroll a virtual table (by its container test id) to the end. */
export async function scrollVirtualToEnd(page: Page, tableTestId: "items-table" | "bom-tree" | "whereused-table"): Promise<void> {
  await page.getByTestId(tableTestId).locator(".vt-scroll").evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
}

/** Footer text "N of M rows shown" of the BOM tree, parsed. */
export async function bomTreeShown(page: Page): Promise<{ shown: number; total: number }> {
  const t = await page.getByTestId("bom-tree").locator(".vt-footer").innerText();
  const m = t.replace(/,/g, "").match(/(\d+) of (\d+)/);
  return { shown: m ? Number(m[1]) : 0, total: m ? Number(m[2]) : 0 };
}

/** Upload a file in the import wizard (step 1) and continue; for CSV pass the target sheet. */
export async function uploadImportFile(page: Page, name: string, content: string | Buffer, csvSheet?: string): Promise<void> {
  await gotoMfg(page, "/import");
  await page.getByTestId("import-file-input").setInputFiles({ name, mimeType: "application/octet-stream", buffer: typeof content === "string" ? Buffer.from(content, "utf-8") : content });
  if (csvSheet) await page.getByTestId("import-csv-sheet").selectOption(csvSheet);
  await page.getByTestId("import-upload-submit").click();
}

/** The routing operation rows in display order, as their `data-seq` values. */
export async function routingSeqs(page: Page): Promise<number[]> {
  return page.getByTestId("routing-op-row").evaluateAll((rows) => rows.map((r) => Number(r.getAttribute("data-seq"))));
}

/** Operation names in display order. */
export async function routingNames(page: Page): Promise<string[]> {
  return page.getByTestId("routing-op-row").evaluateAll((rows) => rows.map((r) => (r.querySelector('[data-testid="op-name"]') as HTMLInputElement | null)?.value ?? ""));
}

/** A shift-week-preview segment locator (`data-split`: start = runs past midnight, end = continued). */
export function weekSegments(page: Page, shift: string, split?: "start" | "end" | "both" | "none"): Locator {
  return page.locator(`[data-testid="week-segment"][data-shift="${shift}"]${split ? `[data-split="${split}"]` : ""}`);
}

/** The month-view day cell of the line calendar (`data-base-minutes`, `data-optional-minutes`). */
export function calendarDay(page: Page, date: string): Locator {
  return page.locator(`[data-testid="calendar-day"][data-date="${date}"]`);
}

// ---------------------------------------------------------------- M2 helpers (WP-C, additive; M2-DESIGN 14.4, 17.4)
/** M2 data-testid contract (14.4) for reference in specs. */
export const M2_TESTIDS = {
  navPlanning: "nav-group-planning",
  postType: (t: "receipt_misc" | "issue_misc" | "adjust" | "transfer" | "count") => `post-type-${t}`,
  docAction: (a: "submit" | "approve" | "reject" | "revise" | "cancel" | "convert" | "issue" | "close") => `doc-action-${a}`,
  woAction: (a: "release" | "complete" | "close" | "cancel") => `wo-action-${a}`,
  runKpi: (k: "late" | "short" | "planned_make" | "planned_buy" | "release_now") => `run-kpi-${k}`,
  runTab: (t: "summary" | "items" | "planned" | "exceptions" | "demand" | "compare") => `run-tab-${t}`,
  convertMode: (m: "firm" | "release") => `convert-mode-${m}`,
  shortagePanel: (p: "demand" | "items" | "supply" | "wo") => `shortage-panel-${p}`,
} as const;

/** Default anchor of the pinned sample builds (M2 13.1): Monday 2 Nov 2026. */
export const M2_ANCHOR = "2026-11-02";

/** `POST /samples/{id}/load` with the M2 body (`anchor`, `include_transactions`). `anchor: null` = this week's Monday. */
export async function loadSampleM2(
  request: APIRequestContext,
  sampleId: "small" | "medium" | "kavach",
  o: { anchor?: string | null; includeTransactions?: boolean; replace?: boolean } & MfgOptions = {},
): Promise<{ sample_id: string; health: { ok: boolean } }> {
  const res = (await mfgCall(request, "POST", `/samples/${sampleId}/load`, {
    data: { replace: o.replace ?? true, anchor: o.anchor === undefined ? null : o.anchor, include_transactions: o.includeTransactions ?? true },
    accounts: o.accounts,
  })) as { sample_id: string; health: { ok: boolean } };
  if (sampleId === "small" && (o.includeTransactions ?? true)) await ensureSmallM2(request, o.anchor ?? null, o);
  return res;
}

/**
 * The M2 part of `small` (13.2) through the API, only when the sample load did not create it (servers whose
 * sample loader predates the M2 sheets). Same codes and quantities, so specs behave the same either way.
 */
export async function ensureSmallM2(request: APIRequestContext, anchor: string | null, opts?: MfgOptions): Promise<void> {
  const locs = await mfgJson<{ items: unknown[] }>(request, "/locations", opts);
  if (locs.items.length) return;
  const base = anchor ? Date.parse(`${anchor}T00:00:00Z`) : Date.now();
  const a = (n: number) => new Date(base + n * 86400000).toISOString().slice(0, 10);
  const post = (path: string, data: unknown) => mfgCall(request, "POST", path, { data, status: 201, ...opts }) as Promise<{ id: string; row_version: number }>;
  const stores = await post("/locations", { code: "STORES", name: "Main stores", kind: "stores" });
  await post("/locations", { code: "GOODS-IN", name: "Goods-in inspection", kind: "inspection", receipt_default: true });
  await post("/locations", { code: "QUAR", name: "Quarantine", kind: "quarantine" });
  const supA = await post("/suppliers", { code: "SUP-A", name: "Supplier A (fictional)" });
  await post("/suppliers", { code: "SUP-B", name: "Supplier B (fictional)" });
  const stock: Record<string, number> = { "SM-RES-10K": 5000, "SM-RES-1K": 5000, "SM-CAP-100N": 5000, "SM-CAP-10U": 4000, "SM-MCU-01": 30, "SM-CON-01": 100, "SM-COAT-01": 2, "SM-LBL-01": 200 };
  const ids: Record<string, string> = {};
  for (const pn of [...Object.keys(stock), "SM-100"]) ids[pn] = (await findItem(request, pn, opts)).id;
  await mfgCall(request, "POST", "/inventory/postings", {
    data: { type: "receipt_misc", note: "e2e opening stock", lines: Object.entries(stock).map(([pn, qty]) => ({ item_id: ids[pn], location_id: stores.id, qty })) },
    headers: { "Idempotency-Key": `e2e-open-${Date.now()}` },
    status: 201,
    ...opts,
  });
  const po = await post("/purchase-orders", {
    number: "PO-SM-0001",
    supplier_id: supA.id,
    lines: [{ line_no: 10, item_id: ids["SM-MCU-01"], schedules: [{ requested_date: a(10), qty: 40 }, { requested_date: a(50), qty: 40 }] }],
  });
  await mfgCall(request, "POST", `/purchase-orders/${po.id}/issue`, { data: {}, headers: { "If-Match": `"${po.row_version}"` }, ...opts });
  for (const [no, prio, type, qty, due] of [["DO-SM-001", 2, "customer", 50, 21], ["DO-SM-002", 5, "spares", 20, 45]] as const) {
    const d = await post("/demand-orders", { number: no, demand_type: type, customer: "Customer A (fictional)", priority: prio, lines: [{ line_no: 10, item_id: ids["SM-100"], qty, due_date: a(due) }] });
    await mfgCall(request, "POST", `/demand-orders/${d.id}/open`, { data: {}, headers: { "If-Match": `"${d.row_version}"` }, ...opts });
  }
}

export interface LocationLite {
  id: string;
  code: string;
  kind: string;
  row_version: number;
}

export async function findLocation(request: APIRequestContext, code: string, opts?: MfgOptions): Promise<LocationLite> {
  const r = await mfgJson<{ items: LocationLite[] }>(request, "/locations", opts);
  const x = r.items.find((l) => l.code === code);
  expect(x, `location ${code} exists`).toBeTruthy();
  return x as LocationLite;
}

export interface DocLite {
  id: string;
  number: string;
  status: string;
  row_version: number;
}

/** A purchase order / request, demand order or work order by number (`q` search + exact match). */
export async function findDoc(
  request: APIRequestContext,
  list: "/purchase-orders" | "/purchase-requests" | "/demand-orders" | "/work-orders",
  number: string,
  opts?: MfgOptions,
): Promise<DocLite> {
  const r = await mfgJson<{ items: DocLite[] }>(request, `${list}?q=${encodeURIComponent(number)}&limit=200`, opts);
  const x = r.items.find((d) => d.number === number);
  expect(x, `${list} ${number} exists`).toBeTruthy();
  return x as DocLite;
}

/** On-hand quantity of an item at a location (sum over lots). */
export async function onHand(request: APIRequestContext, itemId: string, locationId: string, opts?: MfgOptions): Promise<number> {
  const r = await mfgJson<{ balances: { qty_on_hand: number; location: { id: string } }[] }>(request, `/items/${itemId}/stock`, opts);
  return r.balances.filter((b) => b.location.id === locationId).reduce((s, b) => s + b.qty_on_hand, 0);
}

export interface RunLite {
  id: string;
  run_no: number;
  kind: "live" | "what_if";
  status: string;
  summary: { demand_late: number; items_short: number; planned_make: number; planned_buy: number; release_now: number } | null;
}

/** `POST /mrp/runs` through the API (`params` = MrpParams). */
export async function runMrpApi(request: APIRequestContext, params: Record<string, unknown> = {}, opts?: MfgOptions): Promise<RunLite> {
  return (await mfgCall(request, "POST", "/mrp/runs", { data: params, status: 201, ...opts })) as RunLite;
}

/** Run MRP from the UI (MRP page -> Run MRP -> submit) and wait for the run summary. Returns the run id. */
export async function runMrpUi(page: Page, label = "e2e run"): Promise<string> {
  await gotoMfg(page, "/mrp");
  await page.getByTestId("mrp-new-run").click();
  await page.getByTestId("mrp-label").fill(label);
  const created = page.waitForResponse((r) => /\/mfg\/mrp\/runs$/.test(r.url()) && r.request().method() === "POST");
  await page.getByTestId("mrp-run-submit").click();
  const res = await created;
  expect(res.status(), await res.text()).toBe(201);
  const run = (await res.json()) as { id: string };
  await expect(page.getByTestId("run-shell")).toBeVisible();
  return run.id;
}

/** Rows currently in the DOM for an M2 virtual table (never more than ~80, 14.4). */
export async function m2DomRows(page: Page, rowTestId: "balance-row" | "txn-row" | "run-item-row" | "planned-row" | "peg-row" | "exception-row" | "kitting-row"): Promise<number> {
  return page.getByTestId(rowTestId).count();
}
