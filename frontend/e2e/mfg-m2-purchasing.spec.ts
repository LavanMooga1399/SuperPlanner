/**
 * WP-C M2 purchasing screens (M2-DESIGN 14.2, 5): PO with staggered deliveries and a partial receipt through the
 * Receive dialog, an overdue delivery (badge on the document and the delivery board), and the PR flow
 * create -> submit -> approve (owner may approve own) -> convert to a PO. Sample `small` with transactions.
 */
import { test, expect, type Page } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { findDoc, findItem, gotoMfg, loadSampleM2, mfgCall, mfgJson, resetMfg } from "./mfg-helpers";

test.beforeEach(async ({ request }) => {
  await resetMfg(request);
  await loadSampleM2(request, "small");
});

const day = (offset: number) => new Date(Date.now() + offset * 86400000).toISOString().slice(0, 10);

async function pickInRow(page: Page, scope: ReturnType<Page["getByTestId"]>, testId: string, pn: string) {
  await scope.getByTestId(testId).fill(pn);
  await page.getByRole("option", { name: new RegExp(`^${pn}\\b`) }).first().click();
}

test("purchase order: staggered deliveries, partial receipt of delivery 1, receipts history", async ({ page, request }) => {
  const problems = watch(page);
  const po = await findDoc(request, "/purchase-orders", "PO-SM-0001");
  await gotoMfg(page, `/purchasing/orders/${po.id}`);
  await expect(page.getByTestId("doc-status")).toHaveAttribute("data-status", "open");
  await expect(page.getByTestId("doc-schedule")).toHaveCount(2);

  await page.getByTestId("receive-open").click();
  const first = page.getByTestId("receive-row").first();
  await first.getByTestId("receive-qty").fill("10");
  await page.getByTestId("receive-submit").click();
  await expect(page.getByTestId("receive-dialog")).toHaveCount(0);
  await expect(page.getByTestId("doc-status")).toHaveAttribute("data-status", "partially_received");
  await expect(page.getByTestId("doc-receipts")).toBeVisible();
  const rec = await mfgJson<{ lines: { received_qty: number; schedules: { seq: number; received_qty: number }[] }[] }>(request, `/purchase-orders/${po.id}`);
  expect(rec.lines[0].schedules.find((s) => s.seq === 1)!.received_qty).toBe(10);
  expect(rec.lines[0].received_qty).toBe(10);
  expectClean(problems);
});

test("an overdue delivery is flagged on the order and on the delivery board", async ({ page, request }) => {
  const problems = watch(page);
  const con = await findItem(request, "SM-CON-01");
  const sups = await mfgJson<{ items: { id: string; code: string }[] }>(request, "/suppliers");
  const supB = sups.items.find((s) => s.code === "SUP-B")!;
  const created = (await mfgCall(request, "POST", "/purchase-orders", {
    status: 201,
    data: { number: "PO-E2E-OD", supplier_id: supB.id, lines: [{ item_id: con.id, schedules: [{ requested_date: day(-6), qty: 20 }, { requested_date: day(20), qty: 20 }] }] },
  })) as { id: string; row_version: number };
  await mfgCall(request, "POST", `/purchase-orders/${created.id}/issue`, { data: {}, headers: { "If-Match": `"${created.row_version}"` } });

  await gotoMfg(page, `/purchasing/orders/${created.id}`);
  await expect(page.locator('[data-testid="doc-schedule"][data-overdue="true"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="doc-schedule"][data-overdue="false"]')).toHaveCount(1);
  await gotoMfg(page, "/purchasing/schedule?overdue=1");
  await expect(page.locator('[data-testid="board-row"][data-doc="PO-E2E-OD"][data-overdue="true"]')).toBeVisible();
  expectClean(problems);
});

test("purchase request: create with two deliveries, submit, approve, convert to a purchase order", async ({ page }) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  await gotoMfg(page, "/purchasing/requests/new");
  const line = page.getByTestId("doc-line").first();
  await pickInRow(page, line, "doc-line-item", "SM-CON-01");
  await page.getByTestId("doc-schedule-requested").first().fill(day(30));
  await page.getByTestId("doc-schedule-qty").first().fill("50");
  await page.getByTestId("doc-add-schedule").click();
  await page.getByTestId("doc-schedule-qty").nth(1).fill("50");
  await page.getByTestId("doc-save").click();
  await expect(page).toHaveURL(/\/mfg\/purchasing\/requests\/pdc_/);
  await expect(page.getByTestId("doc-status")).toHaveAttribute("data-status", "draft");
  await expect(page.getByTestId("doc-schedule")).toHaveCount(2);

  await page.getByTestId("doc-action-submit").click();
  await expect(page.getByTestId("doc-status")).toHaveAttribute("data-status", "submitted");
  await page.getByTestId("doc-action-approve").click();
  await expect(page.getByTestId("doc-status")).toHaveAttribute("data-status", "approved");

  await page.getByTestId("doc-action-convert").click();
  await page.getByTestId("convert-pr-supplier").fill("SUP-B");
  await page.getByRole("option", { name: /^SUP-B/ }).first().click();
  await page.getByTestId("convert-pr-submit").click();
  await expect(page).toHaveURL(/\/mfg\/purchasing\/orders\/pdc_/);
  await expect(page.getByTestId("doc-status")).toHaveAttribute("data-status", "draft");
  await expect(page.getByTestId("doc-schedule")).toHaveCount(2);
  await page.getByTestId("doc-action-issue").click();
  await page.getByRole("dialog").getByRole("button", { name: "Issue to supplier" }).click();
  await expect(page.getByTestId("doc-status")).toHaveAttribute("data-status", "open");
  expectClean(problems);
});
