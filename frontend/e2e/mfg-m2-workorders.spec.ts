/**
 * WP-C M2 demand and work-order screens (M2-DESIGN 14.2, 6, 7): a demand order created and opened in the UI, a
 * work order created from its line, released with reservation, kitting columns, issue of components, partial
 * output, the kitting check and the shortage dashboard. Sample `small` with transactions.
 */
import { test, expect } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { gotoMfg, loadSampleM2, mfgJson, resetMfg } from "./mfg-helpers";

test.beforeEach(async ({ request }) => {
  await resetMfg(request);
  await loadSampleM2(request, "small");
});

const day = (offset: number) => new Date(Date.now() + offset * 86400000).toISOString().slice(0, 10);

test("demand order -> work order -> release with reserve -> issue -> partial output", async ({ page, request }) => {
  test.setTimeout(150_000);
  const problems = watch(page);

  // --- demand order
  await gotoMfg(page, "/demand/new");
  await page.getByTestId("demand-customer").fill("Customer e2e (fictional)");
  await page.getByTestId("demand-line-item").fill("SM-100");
  await page.getByRole("option", { name: /^SM-100\b/ }).first().click();
  await page.getByTestId("demand-line-qty").fill("5");
  await page.getByTestId("demand-line-due").fill(day(40));
  await page.getByTestId("demand-save").click();
  await expect(page).toHaveURL(/\/mfg\/demand\/dmo_/);
  await expect(page.getByTestId("demand-page")).toHaveAttribute("data-status", "draft");
  await page.getByTestId("demand-action-open").click();
  await expect(page.getByTestId("demand-page")).toHaveAttribute("data-status", "open");
  await expect(page.getByTestId("demand-line")).toHaveCount(1);

  // --- work order from the demand line
  await page.getByTestId("demand-line").getByRole("link", { name: "WO" }).click();
  await expect(page.getByTestId("wo-item")).toHaveValue("SM-100");
  await expect(page.getByTestId("wo-qty")).toHaveValue("5");
  await page.getByTestId("wo-save").click();
  await expect(page).toHaveURL(/\/mfg\/work-orders\/wko_/);
  await expect(page.getByTestId("wo-status")).toHaveAttribute("data-status", "planned");
  await expect(page.getByTestId("kitting-row").first()).toBeVisible();

  await page.getByTestId("wo-action-release").click();
  await page.getByTestId("wo-release-reserve").check();
  await page.getByRole("dialog").getByRole("button", { name: "Release" }).click();
  await expect(page.getByTestId("wo-status")).toHaveAttribute("data-status", "released");
  // the bare PCB has no stock in `small`: it is short; the MCU is covered
  await expect(page.locator('[data-testid="kitting-row"][data-item="SM-BPCB-100"]')).toHaveAttribute("data-shortage", /^[1-9]/);
  await expect(page.locator('[data-testid="kitting-row"][data-item="SM-MCU-01"]')).toHaveAttribute("data-shortage", "0");

  // --- issue components (fill from what is available) then report 2 of 5
  await page.getByTestId("wo-issue-open").click();
  await page.getByTestId("wo-issue-fill").click();
  // nothing of the PCB in stock: clear it so the posting succeeds
  await page.locator('[data-testid="wo-issue-row"][data-item="SM-BPCB-100"]').getByTestId("wo-issue-qty").fill("");
  await page.getByTestId("wo-issue-submit").click();
  await expect(page.getByTestId("wo-status")).toHaveAttribute("data-status", "in_progress");
  await page.getByTestId("wo-receipt-open").click();
  await page.getByTestId("wo-receipt-qty").fill("2");
  const loc = page.getByTestId("wo-receipt-location");
  await loc.selectOption((await loc.locator("option", { hasText: /^STORES / }).first().getAttribute("value"))!);
  await page.getByTestId("wo-receipt-submit").click();
  await expect(page.getByText(/Output posted/)).toBeVisible();
  const woId = page.url().match(/work-orders\/(wko_[^/?]+)/)![1];
  await expect.poll(async () => (await mfgJson<{ qty_completed: number }>(request, `/work-orders/${woId}`)).qty_completed).toBe(2);
  expect((await mfgJson<{ status: string }>(request, `/work-orders/${woId}`)).status).toBe("in_progress");

  // --- kitting check page; the shortage dashboard (released / in-progress WOs) names the bare PCB
  await gotoMfg(page, "/work-orders/kitting");
  // 7.4: the check covers released and planned WOs; this one is in progress now, so it is not listed
  await expect(page.getByTestId("kitting-check-rows")).toBeVisible();
  await expect(page.getByTestId("kitting-items-short")).toBeVisible();
  await gotoMfg(page, "/shortages");
  await expect(page.getByTestId("shortage-panel-wo")).toContainText("SM-BPCB-100");
  expectClean(problems);
});
