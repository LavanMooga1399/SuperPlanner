/**
 * M8 WP-U (docs/M8-DESIGN.md 12, 13): planning at volume on the meddev sample - forecast workbench (run, override a
 * period with a reason, activate), item planning and packaging tabs, safety stock proposals, kanban loop with a card
 * scan, rate plan run and its views, sterilisation loads and the validation kit. Titles carry `@req` tags for the
 * trace matrix (M8 10).
 */
import { expect, test, type APIRequestContext } from "@playwright/test";
import { gotoMfg, mfgCall, mfgJson, resetMfg } from "./mfg-helpers";

interface Page<T> {
  items: T[];
}
interface Item {
  id: string;
  part_number: string;
  make_buy: string;
}

async function seed(request: APIRequestContext): Promise<{ fg: Item; buy: Item }> {
  await resetMfg(request);
  await mfgCall(request, "POST", "/samples/meddev/load", { data: { replace: true } });
  const items = await mfgJson<Page<Item>>(request, "/items?limit=200");
  const fg = items.items.find((i) => i.make_buy === "make")!;
  const buy = items.items.find((i) => i.make_buy === "buy")!;
  return { fg, buy };
}

async function setPlanning(request: APIRequestContext, itemId: string, patch: Record<string, unknown>) {
  const cur = (await mfgJson<Record<string, unknown> & { row_version: number }>(request, `/items/${itemId}/planning`)) as Record<string, unknown> & { row_version: number };
  const { id: _id, item_id: _i, abc: _a, xyz: _x, row_version, ...body } = cur;
  await mfgCall(request, "PUT", `/items/${itemId}/planning`, { data: { ...body, ...patch }, headers: { "If-Match": `"${row_version}"` } });
}

test.describe("M8 planning", () => {
  test("forecast workbench: run, override with a reason, activate @req:M8-FC-05 @req:M8-FC-06", async ({ page, request }) => {
    const { fg } = await seed(request);
    await setPlanning(request, fg.id, { forecast: true });
    await gotoMfg(page, "/forecast");
    await page.getByTestId("fc-run").click();
    await page.getByTestId("fc-run-start").click();
    // the run creates a draft version; the page opens it when the run completes
    await expect(page.getByTestId("fc-version-status")).toHaveAttribute("data-status", "draft", { timeout: 60_000 });
    await page.getByTestId("fc-search").fill(fg.part_number);
    await page.getByTestId("fc-item-row").filter({ hasText: fg.part_number }).first().click();
    await expect(page.getByTestId("fc-panel")).toHaveAttribute("data-item", fg.part_number);
    const cell = page.getByTestId("fc-final-cell").first();
    await cell.click();
    await page.getByTestId("fc-ov-value").fill("5000");
    await page.getByTestId("fc-ov-reason").fill("Tender for a regional hospital group");
    await page.getByTestId("fc-override-save").click();
    await expect(page.getByTestId("fc-final-cell").first()).toContainText(/5[,.  ]?000/);
    await expect(page.locator('[data-testid="fc-grid"] td[data-overridden="true"]')).toHaveCount(1);
    await expect(page.getByTestId("fc-overrides")).toContainText("Tender for a regional hospital group");
    await page.getByTestId("fc-activate").click();
    await page.getByRole("dialog").getByRole("button", { name: "Activate" }).click();
    await expect(page.getByTestId("fc-version-status")).toHaveAttribute("data-status", "active");
    await page.getByTestId("fc-accuracy-link").click();
    await expect(page.getByTestId("fc-accuracy-page")).toBeVisible();
  });

  test("item planning and packaging tabs @req:M8-MRP-02", async ({ page, request }) => {
    const { fg } = await seed(request);
    await gotoMfg(page, `/items/${fg.id}/packaging`);
    await page.getByTestId("pack-use-inner").check();
    await page.getByLabel("Inner code").fill("BX");
    await page.getByTestId("pack-qty-inner").fill("100");
    await page.getByTestId("pack-use-case").check();
    await page.getByLabel("Case code").fill("CS");
    await page.getByTestId("pack-qty-case").fill("250");
    await expect(page.getByRole("alert").filter({ hasText: "whole multiple" })).toBeVisible();
    await page.getByTestId("pack-qty-case").fill("1000");
    await page.getByTestId("pack-save").click();
    await expect.poll(async () => ((await mfgJson<{ levels: { level: string }[] }>(request, `/items/${fg.id}/packaging`)).levels.map((l) => l.level).join(","))).toBe("each,inner,case");
    await page.getByTestId("item-tab-planning").click();
    await page.getByTestId("ip-pack-level").selectOption("case");
    await page.getByTestId("ip-repl-rate").check();
    await page.getByTestId("ip-save").click();
    await expect.poll(async () => (await mfgJson<{ order_pack_level: string; replenishment: string }>(request, `/items/${fg.id}/planning`)).order_pack_level).toBe("case");
  });

  test("safety stock proposals and kanban loop with a card scan @req:M8-SS-03 @req:M8-KB-01", async ({ page, request }) => {
    const { buy } = await seed(request);
    await gotoMfg(page, "/invopt");
    await expect(page.getByTestId("ss-page")).toBeVisible();
    await page.getByTestId("ss-run").click();
    await expect(page.getByTestId("ss-run-status")).toBeVisible({ timeout: 60_000 });

    await gotoMfg(page, "/kanban");
    await page.getByTestId("kb-new").click();
    await page.getByTestId("kb-item").fill(buy.part_number);
    await expect(page.getByRole("option", { name: new RegExp(`^${buy.part_number}\\b`) }).first()).toBeAttached();
    await page.getByTestId("kb-item").press("Enter");
    await page.getByTestId("kb-location").selectOption({ index: 1 });
    await page.getByTestId("kb-cards-n").fill("3");
    await page.getByTestId("kb-container").fill("500");
    await page.getByTestId("kb-save").click();
    await expect(page.getByTestId("kb-panel")).toBeVisible();
    const loops = await mfgJson<Page<{ id: string; item_id: string }>>(request, "/kanban/loops");
    const loop = loops.items.find((l) => l.item_id === buy.id)!;
    const cards = await mfgJson<{ items: { code: string; state: string }[] }>(request, `/kanban/loops/${loop.id}/cards`);
    const full = cards.items.find((c) => c.state === "full")!;
    await page.getByTestId("kb-scan").fill(full.code);
    await page.getByTestId("kb-scan").press("Enter");
    await expect(page.getByTestId("toast")).toBeVisible();
    await expect(page.getByTestId("kb-card-state").filter({ hasText: "Empty" }).first()).toBeVisible();
  });

  test("rate plan, sterilisation and validation views @req:M8-RATE-02 @req:M8-STER-02 @req:M8-VAL-01", async ({ page, request }) => {
    await seed(request);
    await gotoMfg(page, "/rate");
    await page.getByTestId("rate-new").click();
    await page.getByTestId("rate-start").click();
    await expect(page.getByTestId("rate-run-page")).toBeVisible();
    await expect(page.getByTestId("rate-run-page")).not.toHaveAttribute("data-status", /queued|running/, { timeout: 120_000 });
    await page.getByTestId("rate-tab-shortages").click();
    await expect(page.getByTestId("rate-shortages")).toBeVisible();
    await page.getByTestId("rate-tab-gantt").click();
    await expect(page.getByTestId("rate-gantt")).toBeVisible();

    await gotoMfg(page, "/sterilisation");
    await expect(page.getByTestId("ster-page")).toBeVisible();
    await page.getByTestId("ster-view").getByRole("button", { name: "All" }).click();
    await expect(page.getByTestId("ster-loads")).toBeVisible();

    await gotoMfg(page, "/validation");
    await expect(page.getByTestId("val-matrix")).toBeVisible();
    await expect(page.getByTestId("val-baselines")).toBeVisible();
  });
});
