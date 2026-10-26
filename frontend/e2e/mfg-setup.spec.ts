/**
 * WP-D (M1-DESIGN 15.4 mfg-setup): Manufacturing area against the real API. Each test resets the mfg data first
 * (the e2e database is shared by all specs).
 */
import { test, expect, type Page } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import {
  bomTreeShown,
  expectActiveNav,
  findItem,
  gotoMfg,
  loadSample,
  mfgCall,
  mfgJson,
  resetMfg,
  routingNames,
  routingSeqs,
} from "./mfg-helpers";

interface Op { seq: number; name: string }
interface Routing { id: string; row_version: number; status: string; version: number; operations: Op[] }
interface BomSummary { id: string; version: number; status: string; row_version: number; effective_from: string | null; effective_to: string | null }

test.beforeEach(async ({ request }) => {
  await resetMfg(request);
});

test("navigate to Manufacturing, load the small sample in the UI, search items", async ({ page }) => {
  const problems = watch(page);
  await page.goto("/");
  await page.getByTestId("nav-mfg").click();
  await expect(page).toHaveURL(/\/mfg$/);
  await expectActiveNav(page, "nav-mfg");
  await expect(page.getByTestId("mfg-count-items")).toContainText("0");
  await page.getByTestId("sample-load-small").click();
  await expect(page.getByTestId("mfg-count-items")).toContainText("10");
  await expect(page.getByTestId("mfg-home-health")).toHaveAttribute("data-ok", "true");

  await page.getByTestId("mfg-subnav-items").click();
  await expect(page.getByTestId("items-row")).toHaveCount(10);
  await page.getByTestId("items-search").fill("res-1");
  await expect(page.getByTestId("items-row")).toHaveCount(2);
  const pns = await page.getByTestId("items-row").evaluateAll((rows) => rows.map((r) => r.getAttribute("data-part-number")));
  expect(pns.sort()).toEqual(["SM-RES-10K", "SM-RES-1K"]);
  await page.getByTestId("items-search").fill("board assembly");
  await expect(page.getByTestId("items-row")).toHaveCount(1);
  await page.getByTestId("items-row").first().click();
  await expect(page).toHaveURL(/\/mfg\/items\/itm_[0-9a-f]{32}$/);
  await expect(page.getByTestId("item-title")).toContainText("SM-100");
  await expectActiveNav(page, "nav-mfg");
  expectClean(problems);
});

test("item edit: a 412 from a second tab shows the conflict banner and keeps my edits until reload", async ({ page, context, request }) => {
  await loadSample(request, "small");
  const lbl = await findItem(request, "SM-LBL-01");
  const problems = watch(page, [/PUT \/mfg\/items\/itm_[0-9a-f]+ -> 412/, /status of 412/]);
  await gotoMfg(page, `/items/${lbl.id}`);
  const other = await context.newPage();
  await other.goto(`/mfg/items/${lbl.id}`);
  await other.getByTestId("item-description").fill("Changed in the other tab");
  await other.getByTestId("item-save").click();
  await expect.poll(async () => (await mfgJson<{ description: string }>(request, `/items/${lbl.id}`)).description).toBe("Changed in the other tab");

  await page.getByTestId("item-description").fill("My unsaved edit");
  await page.getByTestId("item-save").click();
  await expect(page.getByTestId("conflict-banner")).toBeVisible();
  await expect(page.getByTestId("item-description")).toHaveValue("My unsaved edit");
  expect((await mfgJson<{ description: string }>(request, `/items/${lbl.id}`)).description).toBe("Changed in the other tab");
  await page.getByTestId("conflict-reload").click();
  await expect(page.getByTestId("conflict-banner")).toHaveCount(0);
  await expect(page.getByTestId("item-description")).toHaveValue("Changed in the other tab");
  // saving after the reload works (new If-Match)
  await page.getByTestId("item-description").fill("Mine after reload");
  await page.getByTestId("item-save").click();
  await expect.poll(async () => (await mfgJson<{ description: string; row_version: number }>(request, `/items/${lbl.id}`)).row_version).toBe(lbl.row_version + 2);
  expect((await mfgJson<{ description: string }>(request, `/items/${lbl.id}`)).description).toBe("Mine after reload");
  await other.close();
  expectClean(problems);
});

test("BOM tree expand/collapse/search and where-used", async ({ page, request }) => {
  await loadSample(request, "small");
  const top = await findItem(request, "SM-100");
  const problems = watch(page);
  await gotoMfg(page, `/items/${top.id}/bom`);
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("bom-tree-row").first()).toBeVisible();
  expect(await bomTreeShown(page)).toEqual({ shown: 10, total: 10 });
  // "Collapse all" keeps the root open (its children are all leaves here), the root chevron folds everything
  await page.getByTestId("bom-collapse-all").click();
  await expect.poll(() => bomTreeShown(page)).toEqual({ shown: 10, total: 10 });
  await page.getByRole("button", { name: "Collapse SM-100" }).click();
  await expect.poll(() => bomTreeShown(page)).toEqual({ shown: 1, total: 10 });
  await expect(page.getByTestId("bom-tree-row")).toHaveCount(1);
  await page.getByRole("button", { name: "Expand SM-100" }).click();
  await expect.poll(() => bomTreeShown(page)).toEqual({ shown: 10, total: 10 });
  // keyboard: Left on the root collapses, Right expands
  await page.getByTestId("bom-tree-row").first().click();
  await page.keyboard.press("ArrowLeft");
  await expect.poll(() => bomTreeShown(page)).toEqual({ shown: 1, total: 10 });
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => bomTreeShown(page)).toEqual({ shown: 10, total: 10 });
  // total quantity of the 100k capacitor = 6 x 1.01 / 0.98 (scrap, FCT yield) as the API says
  const ex = await mfgJson<{ rows: { part_number: string; extended_qty: number }[] }>(request, `/items/${top.id}/explosion`);
  const cap = ex.rows.find((r) => r.part_number === "SM-CAP-100N");
  const row = page.locator('[data-testid="bom-tree-row"][data-part-number="SM-CAP-100N"]');
  await expect(row.locator("[data-value]")).toHaveAttribute("data-value", String(cap?.extended_qty));
  // search highlights the matches
  await page.getByRole("button", { name: "Collapse SM-100" }).click();
  await page.getByTestId("bom-search").fill("SM-CAP");
  await page.getByTestId("bom-search").press("Enter");
  await expect(page.locator(".mfg-match-row")).toHaveCount(2);
  await expect(page.getByText("1 of 2")).toBeVisible();

  const res = await findItem(request, "SM-RES-10K");
  await gotoMfg(page, `/items/${res.id}/where-used`);
  await expect(page.getByTestId("whereused-row")).toHaveCount(1);
  await expect(page.getByTestId("whereused-row").first()).toHaveAttribute("data-part-number", "SM-100");
  await page.getByTestId("whereused-mode-indented").click();
  await expect(page.getByTestId("whereused-row")).toHaveCount(1);
  await page.getByTestId("whereused-include-all").click();
  await expect(page.getByTestId("whereused-row")).toHaveCount(1);
  expectClean(problems);
});

async function openRoutingDraft(page: Page, itemId: string): Promise<void> {
  await gotoMfg(page, `/items/${itemId}/routing`);
  await expect(page.getByTestId("routing-readonly")).toBeVisible();
  await page.getByTestId("routing-copy-banner").click();
  await expect(page.getByTestId("routing-readonly")).toHaveCount(0);
  await expect(page.getByTestId("routing-save")).toBeVisible();
}

test("routing editor: keyboard move and drag reorder are saved; time preview equals the API", async ({ page, request }) => {
  await loadSample(request, "small");
  const top = await findItem(request, "SM-100");
  const problems = watch(page);
  await openRoutingDraft(page, top.id);
  expect(await routingNames(page)).toEqual(["SMT top", "AOI", "THT and coating", "Functional test"]);
  // keyboard only: focus "Move down" of op 10 and press Enter
  await page.getByRole("button", { name: "Move operation 10 down" }).focus();
  await page.keyboard.press("Enter");
  expect(await routingNames(page)).toEqual(["AOI", "SMT top", "THT and coating", "Functional test"]);
  expect(await routingSeqs(page)).toEqual([10, 20, 30, 40]);
  await page.keyboard.press("Space"); // focus stays on the moved op's button: SMT top moves down again
  expect(await routingNames(page)).toEqual(["AOI", "THT and coating", "SMT top", "Functional test"]);
  // HTML5 drag and drop: FCT onto the first row
  const rows = page.getByTestId("routing-op-row");
  await rows.nth(3).getByTestId("op-drag-handle").dragTo(rows.nth(0));
  expect(await routingNames(page)).toEqual(["Functional test", "AOI", "THT and coating", "SMT top"]);
  expect(await routingSeqs(page)).toEqual([10, 20, 30, 40]);
  await expect(page.getByTestId("routing-renumber-warning")).toBeVisible(); // BOM lines consume at 30 and 40
  await page.getByTestId("routing-save").click();
  const list = await mfgJson<{ items: { id: string; status: string; version: number }[] }>(request, `/items/${top.id}/routings`);
  const draft = list.items.find((r) => r.status === "draft");
  expect(draft).toBeTruthy();
  await expect
    .poll(async () => (await mfgJson<Routing>(request, `/routings/${draft!.id}`)).operations.map((o) => `${o.seq} ${o.name}`))
    .toEqual(["10 Functional test", "20 AOI", "30 THT and coating", "40 SMT top"]);
  await page.reload();
  await expect.poll(() => routingNames(page)).toEqual(["Functional test", "AOI", "THT and coating", "SMT top"]);

  // time preview for qty 100 equals the API, line by line
  await page.getByTestId("time-preview-qty").fill("100");
  const tp = await mfgJson<{
    operations: { seq: number; lines: { code: string; total_minutes: number }[] }[];
    totals: { fastest_minutes: number; slowest_minutes: number };
  }>(request, `/routings/${draft!.id}/time-preview?qty=100`);
  await expect(page.getByTestId("time-preview-total")).toHaveAttribute("data-fastest", String(tp.totals.fastest_minutes));
  await expect(page.getByTestId("time-preview-total")).toHaveAttribute("data-slowest", String(tp.totals.slowest_minutes));
  for (const op of tp.operations) {
    for (const l of op.lines) {
      const cell = page.locator(`[data-testid="time-preview-op"][data-seq="${op.seq}"] ~ [data-testid="time-preview-line"][data-line="${l.code}"] [data-value]`).first();
      await expect(cell).toHaveAttribute("data-value", String(l.total_minutes));
    }
  }
  await page.getByTestId("time-preview-qty").fill("250");
  const tp2 = await mfgJson<{ totals: { fastest_minutes: number } }>(request, `/routings/${draft!.id}/time-preview?qty=250`);
  await expect(page.getByTestId("time-preview-total")).toHaveAttribute("data-fastest", String(tp2.totals.fastest_minutes));
  expectClean(problems);
});

test("BOM versions: copy, edit the draft, release with supersede; released versions are read-only", async ({ page, request }) => {
  await loadSample(request, "small");
  const top = await findItem(request, "SM-100");
  const v1 = (await mfgJson<{ items: BomSummary[] }>(request, `/items/${top.id}/boms`)).items[0];
  const problems = watch(page);
  await gotoMfg(page, `/items/${top.id}/bom`);
  await page.getByTestId(`bom-version-${v1.id}`).getByTestId("bom-copy").click();
  await expect(page).toHaveURL(/\/bom\/bom_[0-9a-f]{32}\/edit$/);
  const draftId = page.url().match(/bom\/(bom_[0-9a-f]{32})\/edit/)![1];
  await expect(page.getByTestId("bom-readonly")).toHaveCount(0);
  await expect(page.getByTestId("bom-line-row")).toHaveCount(9);
  // change the quantity of find 20 and add a second label line
  const qty20 = page.locator('[data-testid="bom-line-row"]').filter({ has: page.locator('[data-testid="bom-line-find_number"][value="20"]') }).getByTestId("bom-line-qty_per");
  await qty20.fill("6");
  await page.getByTestId("bom-line-add").click();
  await expect(page.getByTestId("bom-line-row")).toHaveCount(10);
  const newRow = page.getByTestId("bom-line-row").last();
  const picker = newRow.getByTestId("bom-line-child");
  await picker.fill("SM-LBL");
  await page.getByRole("option", { name: /SM-LBL-01/ }).click();
  await newRow.getByTestId("bom-line-qty_per").fill("2");
  await page.getByTestId("bom-save").click();
  await expect.poll(async () => (await mfgJson<{ lines: unknown[] }>(request, `/boms/${draftId}`)).lines.length).toBe(10);
  const saved = await mfgJson<{ lines: { find_number: string; qty_per: number; child: { part_number: string } }[] }>(request, `/boms/${draftId}`);
  expect(saved.lines.find((l) => l.find_number === "20")?.qty_per).toBe(6);
  expect(saved.lines.filter((l) => l.child.part_number === "SM-LBL-01").map((l) => l.qty_per).sort()).toEqual([1, 2]);

  // release with supersede at a future date
  await page.getByTestId("bom-release").click();
  await page.getByTestId("release-from").fill("2027-01-04");
  await expect(page.getByTestId("release-supersede")).toBeChecked();
  await page.getByTestId("release-confirm").click();
  await expect.poll(async () => (await mfgJson<{ status: string }>(request, `/boms/${draftId}`)).status).toBe("released");
  const after = (await mfgJson<{ items: BomSummary[] }>(request, `/items/${top.id}/boms`)).items;
  expect(after.find((b) => b.id === v1.id)).toMatchObject({ status: "released", effective_to: "2027-01-04" });
  expect(after.find((b) => b.id === draftId)).toMatchObject({ status: "released", effective_from: "2027-01-04", effective_to: null });

  // explosion before / after the ECO date as shown in the tree
  await gotoMfg(page, `/items/${top.id}/bom?on=2027-01-04`);
  await expect(page.locator('[data-testid="bom-tree-row"][data-part-number="SM-LBL-01"]')).toHaveCount(2);
  await gotoMfg(page, `/items/${top.id}/bom?on=2027-01-03`);
  await expect(page.locator('[data-testid="bom-tree-row"][data-part-number="SM-LBL-01"]')).toHaveCount(1);

  // released documents are read-only in the editor
  for (const id of [v1.id, draftId]) {
    await gotoMfg(page, `/items/${top.id}/bom/${id}/edit`);
    await expect(page.getByTestId("bom-readonly")).toBeVisible();
    await expect(page.getByTestId("bom-save")).toHaveCount(0);
    await expect(page.getByTestId("bom-line-qty_per").first()).toHaveAttribute("readonly", "");
  }
  // the routing too
  await gotoMfg(page, `/items/${top.id}/routing`);
  await expect(page.getByTestId("routing-readonly")).toBeVisible();
  await expect(page.getByTestId("routing-save")).toHaveCount(0);
  // a PUT against the released BOM is refused by the API as well
  const rec = await mfgJson<{ row_version: number }>(request, `/boms/${v1.id}`);
  await mfgCall(request, "POST", `/boms/${v1.id}/release`, { data: {}, headers: { "If-Match": `"${rec.row_version}"` }, status: 409 });
  expectClean(problems);
});

test("load Kavach through 'Replace my data' (confirm dialog) and browse to the top item", async ({ page, request }) => {
  test.setTimeout(120_000);
  await loadSample(request, "small");
  const problems = watch(page);
  await gotoMfg(page, "");
  await page.getByTestId("sample-replace-kavach").click();
  const dlg = page.getByRole("dialog");
  await expect(dlg).toContainText("Replace your data");
  const t0 = Date.now();
  await dlg.getByRole("button", { name: "Delete my data and load the sample" }).click();
  await expect(page.getByTestId("mfg-count-items")).toContainText("1,199", { timeout: 60_000 });
  console.log(`[mfg-perf] Kavach load via the UI (replace): ${Date.now() - t0} ms`);
  await expect(page.getByTestId("mfg-home-health")).toHaveAttribute("data-ok", "true");
  const s = await mfgJson<{ counts: Record<string, number> }>(request, "/summary");
  expect(s.counts.items).toBe(1199);
  const sm = await mfgJson<{ items: { part_number: string }[] }>(request, "/items?q=SM-1&limit=200");
  expect(sm.items.filter((i) => i.part_number.startsWith("SM-"))).toEqual([]); // small was replaced
  await page.getByTestId("mfg-subnav-items").click();
  await page.getByTestId("items-search").fill("KV-TPU");
  await expect(page.getByTestId("items-row")).toHaveCount(1);
  await page.getByTestId("items-row").first().press("Enter");
  await expect(page.getByTestId("item-title")).toContainText("KV-TPU-1000");
  await page.getByTestId("item-tab-bom").click();
  await expect(page.getByTestId("bom-tree-row").first()).toBeVisible();
  expectClean(problems);
});

test("routing versions: release a draft with supersede in the UI; old version gets the end date", async ({ page, request }) => {
  await loadSample(request, "small");
  const top = await findItem(request, "SM-100");
  const before = (await mfgJson<{ items: { id: string; status: string }[] }>(request, `/items/${top.id}/routings`)).items;
  const v1 = before.find((r) => r.status === "released")!;
  const problems = watch(page);
  await openRoutingDraft(page, top.id);
  await page.getByRole("button", { name: "Move operation 20 down" }).click();
  await page.getByTestId("routing-save").click();
  const list = await mfgJson<{ items: { id: string; status: string; version: number }[] }>(request, `/items/${top.id}/routings`);
  const draft = list.items.find((r) => r.status === "draft")!;
  await expect.poll(async () => (await mfgJson<Routing>(request, `/routings/${draft.id}`)).operations.map((o) => o.name)).toEqual(["SMT top", "THT and coating", "AOI", "Functional test"]);
  await page.getByTestId(`routing-version-${draft.id}`).getByTestId("routing-release").click();
  await page.getByTestId("release-from").fill("2027-02-01");
  await expect(page.getByTestId("release-supersede")).toBeChecked();
  await page.getByTestId("release-confirm").click();
  await expect(page.getByTestId(`routing-version-${draft.id}`)).toHaveAttribute("data-status", "released");
  const v1After = await mfgJson<{ effective_to: string | null; status: string }>(request, `/routings/${v1.id}`);
  expect(v1After).toMatchObject({ status: "released", effective_to: "2027-02-01" });
  // both released versions are read-only in the editor
  await page.getByTestId(`routing-version-${draft.id}`).getByRole("button").first().click();
  await expect(page.getByTestId("routing-readonly")).toBeVisible();
  await expect(page.getByTestId("op-move-up")).toHaveCount(0);
  const h = await mfgJson<{ ok: boolean; by_code: Record<string, number> }>(request, "/health");
  expect(h.ok).toBe(true);
  expectClean(problems);
});

test("412 on the BOM and routing editors: conflict banner, my edits kept until reload", async ({ page, request }) => {
  await loadSample(request, "small");
  const top = await findItem(request, "SM-100");
  const v1 = (await mfgJson<{ items: BomSummary[] }>(request, `/items/${top.id}/boms`)).items[0];
  const draft = (await mfgCall(request, "POST", `/boms/${v1.id}/copy`, { data: { revision: null }, headers: { "If-Match": `"${v1.row_version}"` }, status: 201 })) as { id: string; row_version: number; note: string };
  const problems = watch(page, [/-> 412 /, /status of 412/]);
  await gotoMfg(page, `/items/${top.id}/bom/${draft.id}/edit`);
  await expect(page.getByTestId("bom-line-row")).toHaveCount(9);
  // someone else saves the draft (API) while the page is open
  const rec = (await mfgJson<Record<string, unknown> & { lines: Record<string, unknown>[] }>(request, `/boms/${draft.id}`));
  const body = {
    item_id: rec.item_id, revision: rec.revision, version: rec.version, effective_from: null, effective_to: null,
    serial_from: null, serial_to: null, note: "changed elsewhere",
    lines: rec.lines.map((l) => ({ id: l.id, find_number: l.find_number, child_item_id: l.child_item_id, qty_per: l.qty_per, uom: l.uom, scrap_pct: l.scrap_pct, ref_designators: l.ref_designators, alt_group: l.alt_group, alt_priority: l.alt_priority, operation_seq: l.operation_seq, note: l.note })),
  };
  await mfgCall(request, "PUT", `/boms/${draft.id}`, { data: body, headers: { "If-Match": `"${draft.row_version}"` } });
  const qty = page.getByTestId("bom-line-qty_per").first();
  await qty.fill("3");
  await page.getByTestId("bom-save").click();
  await expect(page.getByTestId("conflict-banner")).toBeVisible();
  await expect(qty).toHaveValue("3");
  await page.getByTestId("conflict-reload").click();
  await expect(page.getByTestId("conflict-banner")).toHaveCount(0);
  await expect(page.getByTestId("bom-line-qty_per").first()).toHaveValue("1");

  // routing editor
  await openRoutingDraft(page, top.id);
  const rd = (await mfgJson<{ items: { id: string; status: string; row_version: number }[] }>(request, `/items/${top.id}/routings`)).items.find((r) => r.status === "draft")!;
  const full = await mfgJson<Record<string, unknown> & { operations: Record<string, unknown>[] }>(request, `/routings/${rd.id}`);
  const rbody = {
    item_id: full.item_id, revision: full.revision, code: full.code, version: full.version, priority: full.priority,
    effective_from: null, effective_to: null, serial_from: null, serial_to: null, note: "elsewhere",
    operations: full.operations.map((o) => {
      const { group, skill, tools, ...rest } = o as Record<string, unknown> & { tools: { tool_pool_id: string; qty: number }[] };
      void group;
      void skill;
      return { ...rest, tools: tools.map((t) => ({ tool_pool_id: t.tool_pool_id, qty: t.qty })) };
    }),
  };
  delete (rbody.operations as Record<string, unknown>[])[0].row_version;
  for (const o of rbody.operations as Record<string, unknown>[]) for (const k of ["row_version", "created_at", "updated_at"]) delete o[k];
  await mfgCall(request, "PUT", `/routings/${rd.id}`, { data: rbody, headers: { "If-Match": `"${rd.row_version}"` } });
  await page.getByRole("button", { name: "Move operation 10 down" }).click();
  await page.getByTestId("routing-save").click();
  await expect(page.getByTestId("conflict-banner")).toBeVisible();
  expect(await routingNames(page)).toEqual(["AOI", "SMT top", "THT and coating", "Functional test"]);
  await page.getByTestId("conflict-reload").click();
  await expect(page.getByTestId("conflict-banner")).toHaveCount(0);
  await expect.poll(() => routingNames(page)).toEqual(["SMT top", "AOI", "THT and coating", "Functional test"]);
  expectClean(problems);
});
