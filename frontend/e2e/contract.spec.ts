import { test, expect } from "@playwright/test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { API, apiJson, createFromTemplate, expectClean, gotoTab, openSchedule, optimize, watch } from "./helpers";

// Exercises UI paths against the real API and fails on any unexpected 4xx/5xx (UI/API contract mismatches).

test("editing tasks, resources, calendars and plan settings saves without 422", async ({ page, request }) => {
  const problems = watch(page);
  const planId = await createFromTemplate(page, "manufacturing", "E2E editing");
  const save = page.getByTestId("save-state");
  await page.getByRole("button", { name: "Add Operation" }).first().click();
  await expect(save).toHaveAttribute("data-state", "saved", { timeout: 10_000 });
  await expect.poll(async () => (await apiJson(request, `/problems/${planId}`)).version).toBe(2);
  let rec = await apiJson(request, `/problems/${planId}`);
  const added = rec.problem.tasks.at(-1);
  expect(added.id).toBe("T1");
  expect(added.name).toBe("New Operation");

  await gotoTab(page, /^Machines/);
  await page.getByRole("button", { name: "Add Machine" }).first().click();
  await expect.poll(async () => (await apiJson(request, `/problems/${planId}`)).version).toBe(3);
  const r0 = rec.problem.resources[0];
  await page.getByRole("button", { name: `Show availability of ${r0.name}` }).click();
  await page.getByRole("button", { name: "Add blocked period" }).click();
  await expect.poll(async () => (await apiJson(request, `/problems/${planId}`)).version, { timeout: 10_000 }).toBe(4);
  rec = await apiJson(request, `/problems/${planId}`);
  expect(rec.problem.resources.find((r: { id: string }) => r.id === r0.id).calendar.blocked.length).toBeGreaterThan(0);
  expect(rec.problem.resources.at(-1).id).toBe("R1");

  // plan settings dialog
  await page.getByRole("button", { name: "Plan settings" }).click();
  const dlg = page.getByRole("dialog");
  await expect(dlg).toBeVisible();
  await dlg.getByRole("button", { name: /Apply|Save|OK/ }).click();
  await expect(save).toHaveAttribute("data-state", /saved|dirty|saving/);
  expectClean(problems);
});

test("expert settings and custom weights produce accepted run requests", async ({ page, request }) => {
  const problems = watch(page);
  const planId = await createFromTemplate(page, "manufacturing", "E2E expert");
  await gotoTab(page, "Optimize");
  await page.getByTestId("expert-toggle").check();
  await expect(page.getByTestId("expert-settings")).toBeVisible();
  for (const strategy of ["ga", "cpsat", "hybrid"]) {
    await page.locator("#ex-strategy").selectOption(strategy);
    await page.getByRole("radio", { name: "Custom weights" }).click();
    await page.getByRole("radio", { name: /Quick/ }).click();
    await page.getByTestId("start-run").click();
    const prog = page.getByTestId("run-progress");
    await expect(prog).toHaveAttribute("data-run-state", "completed", { timeout: 30_000 });
    const run = await apiJson(request, `/solver-runs/${await prog.getAttribute("data-run-id")}`);
    expect(run.request.strategy).toBe(strategy);
    expect(run.selection.used).toContain(strategy === "hybrid" ? "ga" : strategy);
    await page.getByRole("link", { name: "New run" }).click();
  }
  const rec = await apiJson(request, `/problems/${planId}`);
  expect(rec.problem.objectives.preset).toBe("custom");
  expectClean(problems);
});

test("live progress arrives over SSE through the dev proxy, and Cancel works", async ({ page, request }) => {
  const problems = watch(page);
  const planId = await createFromTemplate(page, "manufacturing", "E2E live");
  await gotoTab(page, "Optimize");
  await page.getByTestId("expert-toggle").check();
  await page.locator("#ex-strategy").selectOption("ga");
  await page.getByRole("radio", { name: /Thorough/ }).click();
  const sse = page.waitForResponse((r) => /\/solver-runs\/run_[0-9a-f]+\/events(\?|$)/.test(r.url()) && !r.url().includes("stream=false"));
  await page.getByTestId("start-run").click();
  const resp = await sse;
  expect(resp.status()).toBe(200);
  expect(resp.headers()["content-type"]).toContain("text/event-stream");
  const prog = page.getByTestId("run-progress");
  await expect(prog).toHaveAttribute("data-run-state", "running");
  await expect(prog).toContainText("Live");
  await expect(page.getByTestId("phase-ga")).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(prog).toHaveAttribute("data-run-state", "cancelled", { timeout: 5_000 });
  const run = await apiJson(request, `/solver-runs/${await prog.getAttribute("data-run-id")}`);
  expect(run.status).toBe("cancelled");
  expectClean(problems);
});

test("lock at this time, then replan from the schedule tab", async ({ page, request }) => {
  const problems = watch(page);
  const planId = await createFromTemplate(page, "manufacturing", "E2E lock");
  await optimize(page);
  const bars = await openSchedule(page);
  const taskId = (await bars.nth(2).getAttribute("data-task-id"))!;
  await bars.nth(2).click();
  await page.getByTestId("lock-at-time").click();
  await expect(page.getByTestId("task-drawer").getByRole("button", { name: "Unlock" })).toBeVisible();
  await expect.poll(async () => (await apiJson(request, `/problems/${planId}`)).version, { timeout: 10_000 }).toBe(2);
  const rec = await apiJson(request, `/problems/${planId}`);
  const sid = new URL(page.url()).searchParams.get("id")!;
  const sch = await apiJson(request, `/schedules/${sid}`);
  const pl = sch.placements.find((p: { task_id: string }) => p.task_id === taskId);
  const t = rec.problem.tasks.find((x: { id: string }) => x.id === taskId);
  expect(t.locked).not.toBeNull();
  expect(new Date(t.locked.start).getTime()).toBe(new Date(pl.start_at).getTime());
  expect(t.locked.resource_ids).toEqual(pl.resource_ids);
  await page.keyboard.press("Escape");

  // the stale-version warning appears (schedule made for v1, plan is v2)
  await expect(page.getByText(/was made for version 1; the plan is now version 2/)).toBeVisible();

  // Replan with no changes -> optimize?run=..., plan version unchanged
  await page.getByRole("button", { name: /Replan/ }).click();
  await page.getByTestId("replan-submit").click();
  await page.waitForURL(/\/optimize\?run=run_/);
  const prog = page.getByTestId("run-progress");
  await expect(prog).toHaveAttribute("data-run-state", "completed", { timeout: 30_000 });
  const run = await apiJson(request, `/solver-runs/${await prog.getAttribute("data-run-id")}`);
  expect(run.source_schedule_id).toBe(sid);
  expect(run.feasibility).toBe("feasible");
  expect((await apiJson(request, `/problems/${planId}`)).version).toBe(2);
  const nsch = await apiJson(request, `/schedules/${run.primary_schedule_id}`);
  expect(nsch.placements.find((p: { task_id: string }) => p.task_id === taskId).start_at).toBe(pl.start_at);
  expectClean(problems);
});

test("not-feasible schedule: badge, violations panel, approve disabled", async ({ page, request }) => {
  const problems = watch(page);
  const hs = "2026-10-19T00:00:00+00:00";
  const doc = {
    name: "E2E impossible", horizon_start: hs, horizon_days: 2,
    tasks: ["A", "B"].map((id) => ({ id, name: `Weld ${id}`, duration_minutes: 300, deadline: "2026-10-19T06:40:00+00:00",
      deadline_hard: true, requirements: [{ alternatives: ["M"] }] })),
    resources: [{ id: "M", name: "Welder" }], dependencies: [],
  };
  const created = await (await request.post(`${API}/problems`, { data: doc })).json();
  const r = await request.post(`${API}/problems/${created.id}/solver-runs`, { data: { strategy: "cpsat", time_limit_seconds: 2 } });
  expect(r.status()).toBe(202);
  const runId = (await r.json()).run_id;
  await expect.poll(async () => (await apiJson(request, `/solver-runs/${runId}`)).status, { timeout: 15_000 }).toBe("completed");
  const run = await apiJson(request, `/solver-runs/${runId}`);
  expect(run.feasibility).toBe("infeasible");
  expect(run.primary_schedule_id).toBeTruthy();
  await page.goto(`/plans/${created.id}/schedule?id=${run.primary_schedule_id}`);
  await expect(page.getByTestId("schedule-status")).toContainText("Not feasible");
  await expect(page.getByTestId("violations-panel")).toBeVisible();
  await expect(page.getByTestId("approve-button")).toBeDisabled();
  await expect(page.getByRole("status").filter({ hasText: "Cannot be approved" })).toBeVisible();
  // the run page shows the diagnostic
  await page.goto(`/plans/${created.id}/optimize?run=${runId}`);
  await expect(page.getByTestId("run-progress")).toContainText("relaxed");
  expectClean(problems);
});

test("preflight failure on Optimize shows the issues; import and delete from Home", async ({ page, request }) => {
  const problems = watch(page, [/PREFLIGHT_FAILED/, /422/]);
  const exp = {
    format: "superplanner.problem", format_version: 1, exported_at: "2026-10-15T09:30:00Z",
    problem: {
      name: "E2E imported loop", horizon_start: "2026-10-19T00:00:00+00:00", horizon_days: 3,
      tasks: [{ id: "A", name: "Alpha", duration_minutes: 60 }, { id: "B", name: "Beta", duration_minutes: 60 }],
      resources: [], dependencies: [{ predecessor: "A", successor: "B" }, { predecessor: "B", successor: "A" }],
    },
  };
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "sp-imp-")), "loop.json");
  fs.writeFileSync(file, JSON.stringify(exp));
  await page.goto("/");
  await page.locator("#import-file").setInputFiles(file);
  await page.waitForURL(/\/plans\/p_[0-9a-f]+\//);
  const planId = page.url().match(/\/plans\/(p_[0-9a-f]+)\//)![1];
  await gotoTab(page, "Optimize");
  await page.getByTestId("start-run").click();
  await expect(page.getByTestId("issue-DEPENDENCY_CYCLE")).toBeVisible();
  // delete it from the plan list
  await page.goto("/");
  await page.getByRole("button", { name: "Delete E2E imported loop" }).click();
  await page.getByRole("dialog").getByRole("button", { name: /Delete/ }).click();
  await expect(page.getByTestId(`plan-item-${planId}`)).toHaveCount(0);
  expect((await request.get(`${API}/problems/${planId}`)).status()).toBe(404);
  expectClean(problems);
});
