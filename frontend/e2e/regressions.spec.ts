import { test, expect } from "@playwright/test";
import { apiJson, createFromTemplate, expectClean, gotoTab, openSchedule, optimize, watch } from "./helpers";

// Re-checks for previously reported defects (replan version drift, double autosave PUT).

test("after a replan with changes the UI adopts the new version; the next edit saves without a conflict", async ({ page, request }) => {
  const problems = watch(page);
  const planId = await createFromTemplate(page, "manufacturing", "E2E replan version");
  await optimize(page);
  await openSchedule(page);
  await expect(page.getByTitle("Server version of this plan")).toHaveText("v1");
  const rec = await apiJson(request, `/problems/${planId}`);
  const acts = rec.problem.tasks.filter((t: any) => t.type === "activity");
  const target = acts[0];

  await page.getByRole("button", { name: /Replan/ }).click();
  const dlg = page.getByRole("dialog");
  // cut-off at the horizon start so nothing is frozen and the change is always applicable
  const cut = dlg.locator("#replan-cutoff");
  await cut.fill(rec.problem.horizon_start.slice(0, 16));
  await cut.press("Enter");
  await dlg.getByRole("button", { name: "Changed duration" }).click();
  const nd = dlg.getByLabel(`New duration for ${target.name}`);
  await nd.fill(`${target.duration_minutes + 30}`);
  await nd.press("Enter");
  await dlg.locator("#replan-budget").fill("2");
  await page.getByTestId("replan-submit").click();
  await page.waitForURL(/\/optimize\?run=run_/);
  // version chip reflects the replan immediately
  await expect(page.getByTitle("Server version of this plan")).toHaveText("v2");
  const prog = page.getByTestId("run-progress");
  await expect(prog).toHaveAttribute("data-run-state", "completed", { timeout: 30_000 });
  expect((await apiJson(request, `/problems/${planId}`)).version).toBe(2);

  // edit another task: must save as v3 and keep the replan's duration change
  await gotoTab(page, /^Operations/);
  const other = acts[1];
  const dur = page.getByTestId(`task-row-${other.id}`).getByLabel(`Duration of ${other.name}`);
  await dur.fill("3h");
  await dur.press("Enter");
  await expect.poll(async () => (await apiJson(request, `/problems/${planId}`)).version, { timeout: 10_000 }).toBe(3);
  await expect(page.getByTestId("save-state")).toHaveAttribute("data-state", "saved", { timeout: 10_000 });
  await expect(page.getByTestId("conflict-banner")).toHaveCount(0);
  const cur = (await apiJson(request, `/problems/${planId}`)).problem;
  expect(cur.tasks.find((t: any) => t.id === target.id).duration_minutes).toBe(target.duration_minutes + 30);
  expect(cur.tasks.find((t: any) => t.id === other.id).duration_minutes).toBe(180);
  expectClean(problems);
});

test("two callers waiting on one in-flight autosave do not send two PUTs with the same If-Match", async ({ page, request }) => {
  const problems = watch(page);
  const planId = await createFromTemplate(page, "manufacturing", "E2E double save");
  const rec = await apiJson(request, `/problems/${planId}`);
  await expect(page.getByTitle("Server version of this plan")).toHaveText("v1");
  const puts: string[] = [];
  const statuses: number[] = [];
  await page.route(`**/api/v1/problems/${planId}`, async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    puts.push(route.request().headers()["if-match"] ?? "");
    await new Promise((r) => setTimeout(r, 2500));
    const resp = await route.fetch();
    statuses.push(resp.status());
    await route.fulfill({ response: resp });
  });
  const [t1, t2] = rec.problem.tasks.filter((t: any) => t.type === "activity");
  const d1 = page.getByTestId(`task-row-${t1.id}`).getByLabel(`Duration of ${t1.name}`);
  await d1.fill("3h");
  await d1.press("Enter");
  // wait until the autosave PUT is in flight
  await expect.poll(() => puts.length, { timeout: 10_000 }).toBe(1);
  const d2 = page.getByTestId(`task-row-${t2.id}`).getByLabel(`Duration of ${t2.name}`);
  await d2.fill("4h");
  await d2.press("Enter");
  // two explicit save() callers while the first PUT is still in flight
  const exportBtn = page.getByRole("button", { name: "Export" });
  await exportBtn.click();
  await exportBtn.click();
  await expect.poll(async () => (await apiJson(request, `/problems/${planId}`)).version, { timeout: 20_000 }).toBe(3);
  await page.waitForTimeout(4000);
  await expect(page.getByTestId("save-state")).toHaveAttribute("data-state", "saved");
  expect(statuses.every((s) => s === 200), `PUT statuses ${statuses}`).toBeTruthy();
  expect(new Set(puts).size, `If-Match values ${puts}`).toBe(puts.length);
  expect(puts.length).toBe(2);
  const cur = (await apiJson(request, `/problems/${planId}`)).problem;
  expect(cur.tasks.find((t: any) => t.id === t1.id).duration_minutes).toBe(180);
  expect(cur.tasks.find((t: any) => t.id === t2.id).duration_minutes).toBe(240);
  expectClean(problems);
});
