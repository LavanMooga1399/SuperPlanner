/**
 * WP-C M2 inventory screens (M2-DESIGN 14.2, 4): receipt / issue / transfer / count through the posting form,
 * the insufficient-stock message (nothing posted), the ledger, reversal, lots and locations. Sample `small` with
 * transactions (SM-CON-01: 100 EA in STORES).
 */
import { test, expect, type Page } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { findItem, findLocation, gotoMfg, loadSampleM2, m2DomRows, onHand, resetMfg } from "./mfg-helpers";

test.beforeEach(async ({ request }) => {
  await resetMfg(request);
  await loadSampleM2(request, "small");
});

async function pickItem(page: Page, line: number, pn: string) {
  const row = page.getByTestId("post-line").nth(line);
  await row.getByTestId("post-line-item").fill(pn);
  await page.getByRole("option", { name: new RegExp(`^${pn}\\b`) }).first().click();
}

async function pickLocation(page: Page, line: number, code: string, testId = "post-line-location") {
  const sel = page.getByTestId("post-line").nth(line).getByTestId(testId);
  const value = await sel.locator("option", { hasText: new RegExp(`^${code} `) }).first().getAttribute("value");
  await sel.selectOption(value!);
}

test("post a receipt, refuse an over-issue with a clear message, transfer, count, ledger and reversal", async ({ page, request }) => {
  test.setTimeout(150_000);
  const problems = watch(page, [/POST \/mfg\/inventory\/postings -> 409 .*INV_INSUFFICIENT_STOCK/, /status of 409/]);
  const con = await findItem(request, "SM-CON-01");
  const stores = await findLocation(request, "STORES");
  const goodsIn = await findLocation(request, "GOODS-IN");
  const before = await onHand(request, con.id, stores.id);

  // --- receipt
  await gotoMfg(page, "/inventory/post?type=receipt_misc");
  await expect(page.getByTestId("post-type-receipt_misc")).toHaveAttribute("aria-pressed", "true");
  await pickItem(page, 0, "SM-CON-01");
  await pickLocation(page, 0, "STORES");
  await page.getByTestId("post-line").first().getByTestId("post-line-qty").fill("10");
  await page.getByTestId("post-note").fill("e2e receipt");
  await page.getByTestId("post-submit").click();
  await expect(page.getByTestId("posting-done")).toBeVisible();
  await expect(page.getByTestId("posting-lines").getByTestId("txn-row")).toHaveCount(1);
  expect(await onHand(request, con.id, stores.id)).toBeCloseTo(before + 10, 6);

  // --- issue more than available: refused, nothing posted, the message names the numbers
  await gotoMfg(page, "/inventory/post?type=issue_misc");
  await pickItem(page, 0, "SM-CON-01");
  await pickLocation(page, 0, "STORES");
  await expect(page.getByTestId("post-line-available")).toContainText(String(before + 10));
  await page.getByTestId("post-line").first().getByTestId("post-line-qty").fill("100000");
  await page.getByTestId("post-reason").fill("SCRAP");
  await page.getByTestId("post-submit").click();
  await expect(page.getByTestId("mfg-error")).toContainText(/available/i);
  expect(await onHand(request, con.id, stores.id)).toBeCloseTo(before + 10, 6);

  // reason is required for an issue
  await page.getByTestId("post-reason").fill("");
  await page.getByTestId("post-line").first().getByTestId("post-line-qty").fill("1");
  await page.getByTestId("post-submit").click();
  await expect(page.getByText("A reason is required for this movement.")).toBeVisible();

  // --- transfer 5 STORES -> GOODS-IN
  await page.getByTestId("post-type-transfer").click();
  await pickItem(page, 0, "SM-CON-01");
  await pickLocation(page, 0, "STORES");
  await pickLocation(page, 0, "GOODS-IN", "post-line-to-location");
  await page.getByTestId("post-line").first().getByTestId("post-line-qty").fill("5");
  await page.getByTestId("post-submit").click();
  await expect(page.getByTestId("posting-done")).toBeVisible();
  await expect(page.getByTestId("posting-lines").getByTestId("txn-row")).toHaveCount(2);
  expect(await onHand(request, con.id, goodsIn.id)).toBeCloseTo(5, 6);

  // --- count STORES to exactly 50: the difference preview, then the balance
  await gotoMfg(page, "/inventory/post?type=count");
  await pickItem(page, 0, "SM-CON-01");
  await pickLocation(page, 0, "STORES");
  await page.getByTestId("post-line").first().getByTestId("post-line-qty").fill("50");
  await expect(page.getByTestId("post-line-delta")).toBeVisible();
  await page.getByTestId("post-submit").click();
  await expect(page.getByTestId("posting-done")).toBeVisible();
  expect(await onHand(request, con.id, stores.id)).toBeCloseTo(50, 6);

  // --- reverse the count: back to before + 10 - 5
  const countUrl = page.url();
  await page.getByTestId("posting-reverse").click();
  await page.getByTestId("posting-reverse-confirm").click();
  await expect(page).not.toHaveURL(countUrl);
  await expect(page.getByTestId("posting-done")).toBeVisible();
  expect(await onHand(request, con.id, stores.id)).toBeCloseTo(before + 5, 6);

  // --- ledger and stock tables
  await gotoMfg(page, `/inventory/transactions?item=${con.id}`);
  await expect(page.getByTestId("txn-row").first()).toBeVisible();
  expect(await m2DomRows(page, "txn-row")).toBeGreaterThanOrEqual(5);
  await gotoMfg(page, `/inventory?item=${con.id}`);
  await expect(page.locator(`[data-testid="balance-row"][data-location="STORES"]`)).toHaveAttribute("data-qty", String(before + 5));
  await expect(page.getByTestId("balances-totals")).toBeVisible();
  expectClean(problems);
});

test("locations tab lists the sample locations; a new location becomes selectable in the posting form", async ({ page }) => {
  const problems = watch(page);
  await gotoMfg(page, "/inventory/locations");
  await expect(page.locator('[data-testid="location-row"][data-code="STORES"]')).toBeVisible();
  await page.getByTestId("location-new").click();
  await page.getByTestId("location-code").fill("LS-E2E");
  await page.getByTestId("location-name").fill("Line side e2e");
  await page.getByTestId("location-kind").selectOption("line_side");
  await page.getByTestId("location-form-submit").click();
  await expect(page.locator('[data-testid="location-row"][data-code="LS-E2E"]')).toBeVisible();
  await gotoMfg(page, "/inventory/post?type=receipt_misc");
  await expect(page.getByTestId("post-line-location").locator("option", { hasText: /^LS-E2E / })).toHaveCount(1);
  await gotoMfg(page, "/inventory/lots");
  await expect(page.getByTestId("lots-table")).toBeVisible();
  expectClean(problems);
});
