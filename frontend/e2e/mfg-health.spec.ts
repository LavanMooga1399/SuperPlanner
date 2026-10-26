/**
 * WP-D (M1-DESIGN 15.4 mfg-health): break the data in the UI, the health page shows the error with a "Fix" link
 * (server-built `issue.link`) that opens the right page with the entity selected; fixing it turns health green.
 */
import { test, expect } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { findByCode, findItem, gotoMfg, loadSample, mfgJson, resetMfg } from "./mfg-helpers";

test.beforeEach(async ({ request }) => {
  await resetMfg(request);
});

test("deactivate the only FCT line and drop a lead time -> errors with Fix links -> fix in the UI -> green", async ({ page, request }) => {
  await loadSample(request, "small");
  const fct1 = await findByCode(request, "/lines", "FCT-1");
  const top = await findItem(request, "SM-100");
  const lbl = await findItem(request, "SM-LBL-01");
  const problems = watch(page);

  // break 1: the only line of stage FCT made inactive, in the line editor
  await gotoMfg(page, `/plant/groups?line=${fct1.id}`);
  await expect(page.getByTestId("line-panel")).toHaveAttribute("data-line-id", fct1.id);
  await page.getByTestId("line-active").uncheck();
  await page.getByTestId("line-save").click();
  await expect.poll(async () => (await mfgJson<{ active: boolean }>(request, `/lines/${fct1.id}`)).active).toBe(false);
  // break 2: bought label without a lead time, in the item form
  await gotoMfg(page, `/items/${lbl.id}`);
  await page.getByTestId("item-lead-time").fill("");
  await page.getByTestId("item-save").click();
  await expect.poll(async () => (await mfgJson<{ lead_time_days: number | null }>(request, `/items/${lbl.id}`)).lead_time_days).toBeNull();

  await page.getByTestId("mfg-subnav-health").click();
  await expect(page.getByTestId("health-status")).toHaveAttribute("data-ok", "false");
  const api = await mfgJson<{ by_code: Record<string, number>; issues: { code: string; link: string }[] }>(request, "/health");
  expect(Object.keys(api.by_code).sort()).toEqual(["MFG_BUY_NO_LEAD_TIME", "MFG_GROUP_NO_LINE"]);
  await expect(page.getByTestId("health-issue")).toHaveCount(api.issues.length);
  await expect(page.locator('[data-testid="health-issue"][data-code="MFG_GROUP_NO_LINE"]')).toHaveCount(1);
  await expect(page.getByTestId("health-status")).toHaveAttribute("data-errors", "2");
  // the UI renders the server's link unchanged
  const ui = await page.getByTestId("health-fix-link").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  expect(ui.sort()).toEqual(api.issues.map((i) => i.link).sort());
  // filter chips
  await page.getByTestId("health-filter-warning").click();
  await expect(page.getByTestId("health-issue")).toHaveCount(0);
  await page.getByTestId("health-filter-warning").click();
  await page.locator('[data-testid="health-code-chip"][data-code="MFG_BUY_NO_LEAD_TIME"]').click();
  await expect(page.getByTestId("health-issue")).toHaveCount(1);
  await page.locator('[data-testid="health-code-chip"][data-code="MFG_BUY_NO_LEAD_TIME"]').click();

  // Fix link 1: the FCT operation of SM-100's routing, selected
  await page.locator('[data-testid="health-issue"][data-code="MFG_GROUP_NO_LINE"]').getByTestId("health-fix-link").click();
  await expect(page).toHaveURL(new RegExp(`/mfg/items/${top.id}/routing\\?routing=rtg_[0-9a-f]{32}&op=40$`));
  const opRow = page.locator('[data-testid="routing-op-row"][data-seq="40"]');
  await expect(opRow).toBeVisible();
  await expect(opRow).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("routing-readonly")).toBeVisible(); // released routing: read-only banner + Copy

  // Fix link 2: the item details form; enter the lead time there
  await page.goBack();
  await page.locator('[data-testid="health-issue"][data-code="MFG_BUY_NO_LEAD_TIME"]').getByTestId("health-fix-link").click();
  await expect(page).toHaveURL(new RegExp(`/mfg/items/${lbl.id}$`));
  await page.getByTestId("item-lead-time").fill("7");
  await page.getByTestId("item-save").click();
  await expect.poll(async () => (await mfgJson<{ lead_time_days: number | null }>(request, `/items/${lbl.id}`)).lead_time_days).toBe(7);

  // fix the line from the stage page and re-check health
  await gotoMfg(page, `/plant/groups?line=${fct1.id}`);
  await page.getByTestId("line-active").check();
  await page.getByTestId("line-save").click();
  await expect.poll(async () => (await mfgJson<{ active: boolean }>(request, `/lines/${fct1.id}`)).active).toBe(true);
  await page.getByTestId("mfg-subnav-health").click();
  await expect(page.getByTestId("health-status")).toHaveAttribute("data-ok", "true");
  await expect(page.getByTestId("health-issue")).toHaveCount(0);
  await gotoMfg(page, "");
  await expect(page.getByTestId("mfg-home-health")).toHaveAttribute("data-ok", "true");
  expectClean(problems);
});

test("Kavach health: every Fix link opens a page that shows the entity", async ({ page, request }) => {
  test.setTimeout(150_000);
  await loadSample(request, "kavach");
  const problems = watch(page);
  await gotoMfg(page, "/health");
  await expect(page.getByTestId("health-status")).toHaveAttribute("data-ok", "true");
  const report = await mfgJson<{ issues: { code: string; link: string; entity: { type: string; id: string } }[] }>(request, "/health");
  expect(report.issues.length).toBe(9);
  for (const issue of report.issues) {
    await page.goto(issue.link);
    await expect(page.getByTestId("mfg-subnav-overview")).toBeVisible();
    await expect(page.getByTestId("mfg-not-found")).toHaveCount(0);
    if (issue.entity.type === "skill") {
      await expect(page.getByTestId("skill-panel")).toHaveAttribute("data-skill-id", issue.entity.id);
      await expect(page.getByTestId("skill-holder").first()).toBeVisible();
    } else if (issue.entity.type === "bom_line") {
      await expect(page.getByTestId("bom-selected-lines")).toBeVisible();
      await expect(page.locator(`[data-testid="bom-line-row"][data-line-id="${issue.entity.id}"]`)).toHaveClass(/mfg-selected/);
      await expect(page.locator(`[data-testid="bom-tree-row"][data-line-id="${issue.entity.id}"]`)).toHaveClass(/mfg-selected/);
    } else if (issue.entity.type === "item") {
      await expect(page.getByTestId("item-form")).toBeVisible();
      await expect(page.getByTestId("item-lead-time")).not.toHaveValue("");
    }
  }
  expectClean(problems);
});
