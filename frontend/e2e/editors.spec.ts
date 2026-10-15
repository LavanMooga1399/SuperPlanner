import { test, expect } from "@playwright/test";
import { API, apiJson, createFromTemplate, expectClean, gotoTab, optimize, validateReady, watch } from "./helpers";

// Editors that build Problem documents in the browser; every save must be accepted by the real API.

test("dependency rule + negative lag and milestone type are saved and honoured by the solver", async ({ page, request }) => {
  const problems = watch(page);
  const planId = await createFromTemplate(page, "project", "E2E editors");
  const rec = await apiJson(request, `/problems/${planId}`);
  const acts = rec.problem.tasks.filter((t: any) => t.type === "activity");
  const [a, b] = [acts[0], acts.at(-1)];
  await gotoTab(page, "Dependencies");
  await page.locator("#dep-succ").selectOption(b.id);
  await page.locator("#dep-type").selectOption("SS");
  await page.locator("#dep-pred").selectOption(a.id);
  const lag = page.getByLabel("Lag in minutes");
  await lag.fill("-30");
  await lag.blur();
  await page.getByTestId("add-dependency").click();
  await expect(page.getByTestId("save-state")).toHaveAttribute("data-state", "saved", { timeout: 10_000 });
  await expect.poll(async () => (await apiJson(request, `/problems/${planId}`)).version, { timeout: 10_000 }).toBeGreaterThan(1);
  const doc = (await apiJson(request, `/problems/${planId}`)).problem;
  const dep = doc.dependencies.find((d: any) => d.predecessor === a.id && d.successor === b.id);
  expect(dep).toMatchObject({ type: "SS", lag_minutes: -30 });

  // turn an activity into a milestone in the task table
  await gotoTab(page, /^Tasks/);
  const m = acts[1];
  await page.getByTestId(`task-row-${m.id}`).getByLabel(`Type of ${m.name}`).selectOption("milestone");
  await expect.poll(async () => (await apiJson(request, `/problems/${planId}`)).problem.tasks.find((t: any) => t.id === m.id).type, { timeout: 10_000 }).toBe("milestone");
  await expect(page.getByTestId("save-state")).toHaveAttribute("data-state", "saved", { timeout: 10_000 });

  await validateReady(page);
  const run = await apiJson(request, `/solver-runs/${await optimize(page)}`);
  expect(run.feasibility).toBe("feasible");
  const sch = await apiJson(request, `/schedules/${run.primary_schedule_id}`);
  const pa = sch.placements.find((p: any) => p.task_id === a.id);
  const pb = sch.placements.find((p: any) => p.task_id === b.id);
  expect(pb.start).toBeGreaterThanOrEqual(pa.start - 30);
  const pm = sch.placements.find((p: any) => p.task_id === m.id);
  expect(pm.end).toBe(pm.start);
  expectClean(problems);
});

test("plan settings: a fractional horizon is not sent to the API as-is", async ({ page, request }) => {
  const problems = watch(page);
  const planId = await createFromTemplate(page, "manufacturing", "E2E settings");
  await page.getByRole("button", { name: "Plan settings" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.locator("#ps-days").fill("20.5");
  const apply = dlg.getByRole("button", { name: "Apply" });
  if (await apply.isEnabled()) {
    await apply.click();
    await expect(page.getByTestId("save-state")).toHaveAttribute("data-state", /saved|error/, { timeout: 10_000 });
  }
  expect(problems.apiErrors, "PUT rejected").toEqual([]);
  expectClean(problems);
});

test("plan settings: an out-of-range UTC offset is not accepted by the dialog", async ({ page, request }) => {
  const problems = watch(page);
  const planId = await createFromTemplate(page, "manufacturing", "E2E offset range");
  await page.getByRole("button", { name: "Plan settings" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.locator("#ps-offset").fill("+25:00");
  const apply = dlg.getByRole("button", { name: "Apply" });
  if (await apply.isEnabled()) {
    await apply.click();
    await page.waitForTimeout(3000);
  }
  const rec = await apiJson(request, `/problems/${planId}`);
  expect(rec.problem.horizon_start).not.toContain("+25:00");
  expectClean(problems);
});
