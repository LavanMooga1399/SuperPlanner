/**
 * WP-C M2 MRP screens (M2-DESIGN 14.2, 8, 18 #14 pilot journey on `small`): run from the UI, KPI tiles, late
 * demand with its limiting path, item plan chart and buckets, exceptions with server links (expedite -> PO
 * schedule), pegging, release of planned orders, re-run (no duplicates, the old run is not the latest any more),
 * a what-if run and compare. Plus the MP13 DOM bound on `kavach`.
 */
import { test, expect } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { gotoMfg, loadSampleM2, m2DomRows, M2_ANCHOR, mfgJson, resetMfg, runMrpApi, runMrpUi, type RunLite } from "./mfg-helpers";

test.beforeEach(async ({ request }) => {
  await resetMfg(request);
});

test("pilot journey on small: run, late demand and why, item plan, expedite link, release, re-run", async ({ page, request }) => {
  test.setTimeout(180_000);
  await loadSampleM2(request, "small");
  const problems = watch(page);
  const runId = await runMrpUi(page, "e2e weekly");
  await expect(page.getByTestId("run-kpi-late")).toBeVisible();
  await expect(page.getByTestId("run-kpi-planned_buy")).toBeVisible();

  // late demand: DO-SM-002 is late (13.2) and explains why
  await page.getByTestId("run-tab-demand").click();
  const late = page.locator('[data-testid="demand-line"][data-line="DO-SM-002/10"]');
  await expect(late).toBeVisible();
  expect(Number(await late.getAttribute("data-late-days"))).toBeGreaterThan(0);
  await expect(page.getByTestId("limiting-step").first()).toBeVisible();

  // item plan of the MCU: chart and buckets
  await page.getByTestId("run-tab-items").click();
  await page.getByTestId("run-items-search").fill("SM-MCU-01");
  await page.locator('[data-testid="run-item-row"][data-item="SM-MCU-01"]').click();
  await expect(page.getByTestId("item-plan-chart")).toBeVisible();
  await expect(page.getByTestId("item-plan-bucket").first()).toBeVisible();

  // expedite message on the second MCU delivery opens the PO with the schedule highlighted
  await page.getByTestId("run-tab-exceptions").click();
  await page.locator('[data-testid="exception-code-chip"][data-code="MRP_EXPEDITE"]').click();
  const ex = page.locator('[data-testid="exception-row"][data-code="MRP_EXPEDITE"]').first();
  await expect(ex).toBeVisible();
  await ex.getByTestId("exception-link").click();
  await expect(page).toHaveURL(/\/mfg\/purchasing\/orders\/pdc_[^?]+\?schedule=psc_/);
  await expect(page.locator('[data-testid="doc-schedule"].mfg-highlight')).toHaveCount(1);

  // release the planned orders that should be released now
  await gotoMfg(page, `/mrp/runs/${runId}/planned?release=release_now`);
  const rows = page.locator('[data-testid="planned-row"][data-release-status="release_now"]');
  await expect(rows.first()).toBeVisible();
  const n = await rows.count();
  for (let i = 0; i < n; i++) await rows.nth(i).getByTestId("planned-select").check();
  await page.getByTestId("convert-open").click();
  await page.getByTestId("convert-mode-release").check();
  await page.getByTestId("convert-submit").click();
  await expect(page.getByTestId("convert-result")).toBeVisible();
  const prs = await mfgJson<{ items: { source: string }[] }>(request, "/purchase-requests?source=mrp&limit=200");
  expect(prs.items.length).toBeGreaterThan(0);

  // re-run: the old run is no longer the latest live plan (convert disabled) and planned orders are not duplicated
  const second = await runMrpApi(request, { label: "after release" });
  await gotoMfg(page, `/mrp/runs/${runId}/planned`);
  await expect(page.getByTestId("convert-open")).toBeDisabled();
  const old = await mfgJson<{ items: { item: { part_number: string }; release_status: string }[] }>(request, `/mrp/runs/${runId}/planned-orders?release_status=release_now&limit=200`);
  const fresh = await mfgJson<{ items: { item: { part_number: string }; release_status: string }[] }>(request, `/mrp/runs/${second.id}/planned-orders?release_status=release_now&status=open&limit=200`);
  for (const o of old.items) expect(fresh.items.map((x) => x.item.part_number)).not.toContain(o.item.part_number);
  expectClean(problems);
});

test("what-if run and compare with the live plan", async ({ page, request }) => {
  test.setTimeout(150_000);
  await loadSampleM2(request, "small", { anchor: M2_ANCHOR });
  const problems = watch(page);
  const live = await runMrpApi(request, { label: "live" });
  await gotoMfg(page, "/mrp");
  await page.getByTestId("mrp-new-run").click();
  await page.getByTestId("mrp-whatif-toggle").click();
  await page.getByTestId("whatif-no-pr").check();
  await page.getByTestId("mrp-label").fill("without requests");
  await page.getByTestId("mrp-run-submit").click();
  await expect(page.getByTestId("run-shell")).toHaveAttribute("data-kind", "what_if");
  await page.getByTestId("run-tab-planned").click();
  await expect(page.getByTestId("convert-open")).toBeDisabled();
  await page.getByTestId("run-tab-compare").click();
  await page.getByTestId("compare-with").selectOption(live.id);
  await expect(page.getByTestId("compare-demand")).toBeVisible();
  expectClean(problems);
});

test("kavach scale: material plan and planned orders stay virtual (<= 80 DOM rows); pegging tree", async ({ page, request }) => {
  test.setTimeout(240_000);
  await loadSampleM2(request, "kavach");
  const run: RunLite = await runMrpApi(request, { label: "scale" });
  const problems = watch(page);
  await gotoMfg(page, `/mrp/runs/${run.id}/items`);
  await expect(page.getByTestId("run-item-row").first()).toBeVisible();
  expect(await m2DomRows(page, "run-item-row")).toBeLessThanOrEqual(80);
  await gotoMfg(page, `/mrp/runs/${run.id}/planned`);
  await expect(page.getByTestId("planned-row").first()).toBeVisible();
  expect(await m2DomRows(page, "planned-row")).toBeLessThanOrEqual(80);
  // peg up from the first planned buy order
  const planned = await mfgJson<{ items: { item: { id: string }; kind: string; planned_no: number }[] }>(request, `/mrp/runs/${run.id}/planned-orders?kind=buy&limit=1`);
  const plan = await mfgJson<{ supplies: { node: number; planned_no: number | null }[] }>(request, `/mrp/runs/${run.id}/items/${planned.items[0].item.id}`);
  const node = plan.supplies.find((s) => s.planned_no === planned.items[0].planned_no)!.node;
  await gotoMfg(page, `/mrp/runs/${run.id}/pegging?item=${planned.items[0].item.id}&node=${node}&kind=supply&direction=up`);
  await expect(page.locator('[data-testid="peg-row"][data-level="0"]')).toHaveCount(1);
  expect(await m2DomRows(page, "peg-row")).toBeLessThanOrEqual(80);
  await gotoMfg(page, "/shortages");
  for (const p of ["demand", "items", "supply", "wo"]) await expect(page.getByTestId(`shortage-panel-${p}`)).toBeVisible();
  expectClean(problems);
});
