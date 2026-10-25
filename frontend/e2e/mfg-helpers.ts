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
