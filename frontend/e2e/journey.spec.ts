import { test, expect } from "@playwright/test";
import * as fs from "node:fs";
import { API, apiJson, approveCurrent, createFromTemplate, expectClean, gotoTab, openSchedule, optimize, validateReady, watch } from "./helpers";

test("manufacturing journey: edit, cycle, optimize live, Gantt, approve, compare, CSV", async ({ page, request }) => {
  // the deliberate cycle makes run creation impossible; nothing else may fail
  const problems = watch(page);
  await page.goto("/");
  await expect(page.getByTestId("plan-list")).toBeVisible();
  for (const id of ["manufacturing", "exam_prep", "project", "blank"]) await expect(page.getByTestId(`template-card-${id}`)).toBeVisible();
  const planId = await createFromTemplate(page, "manufacturing", "E2E journey");
  const rec = await apiJson(request, `/problems/${planId}`);
  const first = rec.problem.tasks[0];

  // edit a task duration -> saving -> saved, version bumps
  const save = page.getByTestId("save-state");
  await expect(save).toHaveAttribute("data-state", "saved");
  const dur = page.getByTestId(`task-row-${first.id}`).getByLabel(`Duration of ${first.name}`);
  await dur.fill("2h 30m");
  await dur.press("Enter");
  await dur.blur();
  await expect(save).toHaveAttribute("data-state", /dirty|saving/);
  await expect(save).toHaveAttribute("data-state", "saved", { timeout: 10_000 });
  await expect.poll(async () => (await apiJson(request, `/problems/${planId}`)).version).toBe(2);
  const after = await apiJson(request, `/problems/${planId}`);
  expect(after.problem.tasks[0].duration_minutes).toBe(150);

  // create a loop via the UI: J1-3 -> J1-1 (J1-1 -> J1-2 -> J1-3 already exists)
  const succ = rec.problem.tasks.find((t: { id: string }) => t.id === "J1-1");
  const pred = rec.problem.tasks.find((t: { id: string }) => t.id === "J1-3");
  await gotoTab(page, "Dependencies");
  await page.locator("#dep-succ").selectOption(succ.id);
  await page.locator("#dep-pred").selectOption(pred.id);
  await page.getByTestId("add-dependency").click();
  await expect(page.getByText("These dependencies form a loop.")).toBeVisible();
  await gotoTab(page, "Validate");
  await expect(page.getByTestId("issue-DEPENDENCY_CYCLE")).toBeVisible();
  await expect(page.getByTestId("validate-status")).toContainText(/error/);
  // remove the loop again
  await gotoTab(page, "Dependencies");
  await page.getByRole("button", { name: "List" }).click();
  await page.getByRole("button", { name: `Remove dependency ${pred.id} to ${succ.id}` }).click();
  await validateReady(page);
  await expect(page.getByTestId("issue-DEPENDENCY_CYCLE")).toHaveCount(0);

  // optimize with live progress (events observed while running)
  await gotoTab(page, "Optimize");
  await page.getByRole("radio", { name: /Quick/ }).click();
  await page.getByTestId("start-run").click();
  const prog = page.getByTestId("run-progress");
  await expect(prog).toHaveAttribute("data-run-state", /queued|running/);
  await expect(page.locator('[data-testid^="phase-"]').first()).toBeVisible();
  await expect(prog).toHaveAttribute("data-run-state", "completed", { timeout: 30_000 });
  const run1 = (await prog.getAttribute("data-run-id"))!;
  let bars = await openSchedule(page);
  // keyboard: Tab to a bar, Enter opens the drawer
  await bars.first().focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("task-drawer")).toBeVisible();
  await page.keyboard.press("Escape");
  await approveCurrent(page);

  // CSV download
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-csv").click()]);
  const file = await dl.path();
  const csv = fs.readFileSync(file!, "utf8").split(/\r?\n/).filter(Boolean);
  expect(csv[0]).toBe("task_id,task_name,group,type,start,end,duration_minutes,resource_ids,resource_names,deadline,deadline_hard,lateness_minutes,on_critical_chain");
  expect(csv.length).toBe(1 + rec.problem.tasks.length);
  expect(dl.suggestedFilename()).toMatch(/\.csv$/);

  // a second run with a different goal, then compare the two
  await gotoTab(page, "Optimize");
  await page.getByTestId("preset-finish_asap").click();
  const run2 = await optimize(page);
  expect(run2).not.toBe(run1);
  bars = await openSchedule(page);
  await expect(page.getByTestId("approval-banner")).toContainText("Candidate");
  // approving the second names the one it supersedes
  await page.getByTestId("approve-button").click();
  await expect(page.getByRole("dialog")).toContainText("superseded");
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();

  await gotoTab(page, "Compare");
  const table = page.getByTestId("compare-table");
  await expect(table).toBeVisible();
  const r1 = await apiJson(request, `/solver-runs/${run1}`);
  const r2 = await apiJson(request, `/solver-runs/${run2}`);
  await expect(page.locator("#cmp-a")).toHaveValue(r1.primary_schedule_id); // default A = approved
  await page.locator("#cmp-b").selectOption(r2.primary_schedule_id);
  await expect(page).toHaveURL(new RegExp(`b=${r2.primary_schedule_id}`));
  const cmp = await apiJson(request, `/schedules/compare?a=${r1.primary_schedule_id}&b=${r2.primary_schedule_id}`);
  for (const d of cmp.task_deltas.slice(0, 3)) await expect(page.getByTestId(`compare-row-${d.task_id}`)).toBeVisible();

  // approve B from the schedule tab -> A becomes superseded
  await page.goto(`/plans/${planId}/schedule?id=${r2.primary_schedule_id}`);
  await approveCurrent(page);
  const a = await apiJson(request, `/schedules/${r1.primary_schedule_id}`);
  expect(a.status).toBe("superseded");
  expectClean({ ...problems, apiErrors: problems.apiErrors.filter((l) => !/PREFLIGHT_FAILED/.test(l)) });
});

test("all A.17.2 test hooks render", async ({ page, request }) => {
  const problems = watch(page);
  const planId = await createFromTemplate(page, "project", "E2E hooks");
  const rec = await apiJson(request, `/problems/${planId}`);
  await expect(page.getByTestId("save-state")).toBeVisible();
  await expect(page.getByTestId(`task-row-${rec.problem.tasks[0].id}`)).toBeVisible();
  await validateReady(page);
  const runId = await optimize(page);
  await expect(page.getByTestId("run-status")).toBeVisible();
  await openSchedule(page);
  const run = await apiJson(request, `/solver-runs/${runId}`);
  for (const id of ["gantt", "approve-button", "schedule-status", "export-csv", `gantt-bar-${rec.problem.tasks[0].id}`]) {
    await expect(page.getByTestId(id)).toHaveCount(1);
  }
  await page.getByTestId(`gantt-bar-${rec.problem.tasks[0].id}`).click();
  await expect(page.getByTestId("task-drawer")).toBeVisible();
  const href = await page.getByTestId("export-csv").getAttribute("href");
  const r = await request.get(new URL(href!, page.url()).toString());
  expect(r.status()).toBe(200);
  expect(r.headers()["content-type"]).toContain("text/csv");
  // a second run so there are two schedules to compare
  const run2 = await apiJson(request, `/solver-runs/${await optimize(page)}`);
  await page.goto(`/plans/${planId}/compare?a=${run.primary_schedule_id}&b=${run2.primary_schedule_id}`);
  await expect(page.getByTestId("compare-table")).toBeVisible();
  await page.goto("/");
  await expect(page.getByTestId("plan-list")).toBeVisible();
  await expect(page.getByTestId("template-card-project")).toBeVisible();
  expectClean(problems);
});

test("412 conflict banner on a concurrent edit", async ({ page, request }) => {
  const problems = watch(page, [/-> 412/, /412/]);
  const planId = await createFromTemplate(page, "manufacturing", "E2E conflict");
  const rec = await apiJson(request, `/problems/${planId}`);
  // someone else saves version 2
  const doc = { ...rec.problem, name: "Changed elsewhere" };
  const put = await request.put(`${API}/problems/${planId}`, { data: doc, headers: { "If-Match": '"1"' } });
  expect(put.status()).toBe(200);
  const t = rec.problem.tasks[1];
  const dur = page.getByTestId(`task-row-${t.id}`).getByLabel(`Duration of ${t.name}`);
  await dur.fill("3h");
  await dur.press("Enter");
  await expect(page.getByTestId("conflict-banner")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("save-state")).toHaveAttribute("data-state", "conflict");
  const cur = await apiJson(request, `/problems/${planId}`);
  expect(cur.problem.name).toBe("Changed elsewhere");
  expect(cur.version).toBe(2);
  expectClean(problems);
});
