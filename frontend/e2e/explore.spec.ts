import { test, expect } from "@playwright/test";
import { apiJson, approveCurrent, expectClean, gotoTab, openSchedule, optimize, validateReady, watch } from "./helpers";

// Browser in a non-UTC zone: the template card must send that offset and the UI must show plan-offset times.
test.use({ timezoneId: "America/New_York" });

const CASES = [
  { id: "exam_prep", fill: async (card: import("@playwright/test").Locator) => {
      await card.getByLabel("Days until the exam").fill("10");
      await card.getByLabel("Subjects").fill("Maths\n  \nPhysics\n");
      await card.getByLabel("Topics per subject").fill("2");
    }, check: (rec: any) => {
      const groups = new Set(rec.problem.tasks.map((t: any) => t.group).filter(Boolean));
      expect([...groups].filter((g) => g !== "All subjects").sort()).toEqual(["Maths", "Physics"]);
    } },
  { id: "project", fill: async (card: import("@playwright/test").Locator) => {
      await card.getByLabel("Team size").fill("5");
    }, check: (rec: any) => expect(rec.problem.resources.filter((r: any) => r.id !== undefined).length).toBeGreaterThan(0) },
  { id: "manufacturing", fill: async (card: import("@playwright/test").Locator) => {
      await card.getByLabel("Number of jobs").fill("4");
    }, check: (rec: any) => expect(new Set(rec.problem.tasks.map((t: any) => t.group)).size).toBe(4) },
];

for (const c of CASES) {
  test(`${c.id}: parameter form, resource view, zoom, compare tab, approve (America/New_York)`, async ({ page, request }) => {
    const problems = watch(page);
    await page.goto("/");
    const card = page.getByTestId(`template-card-${c.id}`);
    await card.getByLabel("Plan name").fill(`X ${c.id}`);
    const toggle = card.getByRole("button", { name: /parameters|options|customi[sz]e|settings/i });
    if (await toggle.count()) await toggle.first().click();
    await c.fill(card);
    await card.getByRole("button", { name: "Create plan" }).click();
    await page.waitForURL(/\/plans\/p_[0-9a-f]+\/tasks/);
    const planId = page.url().match(/\/plans\/(p_[0-9a-f]+)\//)![1];
    const rec = await apiJson(request, `/problems/${planId}`);
    // EDT on 2026-10-15
    expect(rec.problem.horizon_start).toMatch(/-04:00$/);
    c.check(rec);
    await expect(page.getByText("Times in UTC-04:00").first()).toBeVisible();

    await validateReady(page);
    const run1 = await optimize(page);
    await openSchedule(page);
    await expect(page.getByText("Times shown in UTC-04:00")).toBeVisible();
    // resource view shows one row per used resource; every bar still present
    await page.getByRole("group", { name: "Timeline view" }).getByRole("button").nth(1).click();
    const sch = await apiJson(request, `/schedules/${(await apiJson(request, `/solver-runs/${run1}`)).primary_schedule_id}`);
    const used = new Set(sch.placements.flatMap((p: any) => p.resource_ids));
    const bars = page.locator('[data-testid^="gantt-bar-"]');
    await expect(bars.first()).toBeVisible();
    expect(await bars.count()).toBeGreaterThanOrEqual(used.size > 0 ? sch.placements.filter((p: any) => p.resource_ids.length).length : 0);
    // zoom to both ends
    for (let i = 0; i < 5; i++) if (await page.getByLabel("Zoom in").isEnabled()) await page.getByLabel("Zoom in").click();
    await expect(page.getByLabel("Zoom in")).toBeDisabled();
    for (let i = 0; i < 5; i++) if (await page.getByLabel("Zoom out").isEnabled()) await page.getByLabel("Zoom out").click();
    await expect(page.getByLabel("Zoom out")).toBeDisabled();
    // drawer time equals the API start in plan offset
    await page.getByRole("group", { name: "Timeline view" }).getByRole("button").nth(0).click();
    const p0 = sch.placements[0];
    await page.getByTestId(`gantt-bar-${p0.task_id}`).click();
    await expect(page.getByTestId("task-drawer")).toContainText(p0.start_at.slice(11, 16));
    await page.keyboard.press("Escape");
    await approveCurrent(page);

    // second run with another goal, then compare through the tab pickers
    await gotoTab(page, "Optimize");
    await page.getByTestId("preset-finish_asap").click();
    const run2 = await optimize(page);
    const s1 = (await apiJson(request, `/solver-runs/${run1}`)).primary_schedule_id;
    const s2 = (await apiJson(request, `/solver-runs/${run2}`)).primary_schedule_id;
    await gotoTab(page, "Compare");
    await expect(page.getByTestId("compare-table")).toBeVisible();
    await page.locator("#cmp-a").selectOption(s1);
    await page.locator("#cmp-b").selectOption(s2);
    const cmp = await apiJson(request, `/schedules/compare?a=${s1}&b=${s2}`);
    await expect(page.getByTestId("compare-table")).toBeVisible();
    await expect(page.getByRole("heading", { name: `${cmp.changed_task_count} of ${cmp.task_deltas.length}`, exact: false })).toBeVisible();
    await page.getByLabel("Only changed").uncheck();
    for (const d of cmp.task_deltas.slice(0, 5)) await expect(page.getByTestId(`compare-row-${d.task_id}`)).toBeVisible();
    await page.getByLabel("Swap A and B").click();
    await expect(page.locator("#cmp-a")).toHaveValue(s2);
    await expect(page.locator("#cmp-b")).toHaveValue(s1);
    // approval of run 1 persisted, run 2 is a candidate
    expect((await apiJson(request, `/schedules/${s1}`)).status).toBe("approved");
    expect((await apiJson(request, `/schedules/${s2}`)).status).toBe("candidate");
    expectClean(problems);
  });
}
