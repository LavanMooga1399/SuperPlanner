import { test, expect } from "@playwright/test";
import { API, apiJson, expectClean, gotoTab, openSchedule, watch } from "./helpers";

async function instantiate(request: import("@playwright/test").APIRequestContext, name: string, params: object = { jobs: 3 }) {
  const r = await request.post(`${API}/templates/manufacturing/instantiate`, {
    data: { name, start_date: "2026-10-19", utc_offset: "+05:30", parameters: params },
  });
  expect(r.status()).toBe(201);
  return r.json();
}

async function runVia(request: import("@playwright/test").APIRequestContext, planId: string, body: object) {
  const r = await request.post(`${API}/problems/${planId}/solver-runs`, { data: body });
  expect(r.status(), await r.text()).toBe(202);
  const runId = (await r.json()).run_id;
  await expect.poll(async () => (await apiJson(request, `/solver-runs/${runId}`)).status, { timeout: 30_000 }).toMatch(/completed|cancelled|failed/);
  return apiJson(request, `/solver-runs/${runId}`);
}

test("plan offset +05:30: editor datetimes, drawer times and replan dialog round-trip", async ({ page, request }) => {
  const problems = watch(page);
  const rec = await instantiate(request, "E2E offset");
  const planId = rec.id;
  await page.goto(`/plans/${planId}/tasks`);
  await expect(page.getByText("Times in UTC+05:30").first()).toBeVisible();
  const t = rec.problem.tasks[0];
  const dl = page.getByTestId(`task-row-${t.id}`).getByLabel(`Due date of ${t.name}`);
  await dl.fill("2026-10-20T18:00");
  await dl.press("Enter");
  await expect.poll(async () => (await apiJson(request, `/problems/${planId}`)).version, { timeout: 10_000 }).toBe(2);
  const saved = (await apiJson(request, `/problems/${planId}`)).problem.tasks[0];
  expect(new Date(saved.deadline).toISOString()).toBe(new Date("2026-10-20T18:00:00+05:30").toISOString());

  const run = await runVia(request, planId, { strategy: "cpsat", time_limit_seconds: 2 });
  const sch = await apiJson(request, `/schedules/${run.primary_schedule_id}`);
  await page.goto(`/plans/${planId}/schedule?id=${sch.id}`);
  await expect(page.getByTestId("gantt")).toBeVisible();
  const pl = sch.placements.find((p: { task_id: string }) => p.task_id === t.id);
  await page.getByTestId(`gantt-bar-${t.id}`).click();
  const drawer = page.getByTestId("task-drawer");
  await expect(drawer).toBeVisible();
  const hhmm = pl.start_at.slice(11, 16);
  await expect(drawer).toContainText(hhmm);
  await page.keyboard.press("Escape");

  // replan via the dialog with a duration change and a machine outage
  await page.getByRole("button", { name: /Replan/ }).click();
  const dlg = page.getByRole("dialog");
  const cut = dlg.locator("#replan-cutoff");
  await cut.fill("2026-10-19T12:00");
  await cut.press("Enter");
  await dlg.getByRole("button", { name: "Changed duration" }).click();
  const target = rec.problem.tasks.at(-1);
  await dlg.getByLabel("Operation for change 1").selectOption(target.id);
  const nd = dlg.getByLabel(`New duration for ${target.name}`);
  await nd.fill(`${target.duration_minutes + 30}`);
  await nd.press("Enter");
  await dlg.getByRole("button", { name: "Unavailable machine" }).click();
  await dlg.locator("#replan-budget").fill("3");
  await page.getByTestId("replan-submit").click();
  await page.waitForURL(/\/optimize\?run=run_/);
  const prog = page.getByTestId("run-progress");
  await expect(prog).toHaveAttribute("data-run-state", "completed", { timeout: 30_000 });
  const rrun = await apiJson(request, `/solver-runs/${await prog.getAttribute("data-run-id")}`);
  expect(rrun.source_schedule_id).toBe(sch.id);
  const cur = await apiJson(request, `/problems/${planId}`);
  expect(cur.version).toBe(3);
  expect(cur.problem.tasks.at(-1).duration_minutes).toBe(target.duration_minutes + 30);
  const blocked = cur.problem.resources[0].calendar.blocked.at(-1);
  expect(new Date(blocked.start).toISOString()).toBe(new Date("2026-10-19T12:00:00+05:30").toISOString());
  expect(rrun.status).toBe("completed");
  expectClean(problems);
});

test("reloading during a run resubscribes; a second start goes to the active run", async ({ page, request }) => {
  const problems = watch(page, [/RUN_ALREADY_ACTIVE/, /409/]);
  const rec = await instantiate(request, "E2E reload", { jobs: 10 });
  const planId = rec.id;
  const r = await request.post(`${API}/problems/${planId}/solver-runs`, {
    data: { strategy: "ga", time_limit_seconds: 8, ga: { max_generations: 10000, stagnation_generations: 1000 } },
  });
  const runId = (await r.json()).run_id;
  await page.goto(`/plans/${planId}/optimize`);
  await page.getByTestId("start-run").click(); // 409 -> navigates to the active run
  await page.waitForURL(new RegExp(`run=${runId}`));
  const prog = page.getByTestId("run-progress");
  await expect(prog).toHaveAttribute("data-run-state", "running");
  await page.reload();
  await expect(prog).toHaveAttribute("data-run-state", "running");
  await expect(prog).toHaveAttribute("data-run-state", "completed", { timeout: 20_000 });
  await expect(page.getByTestId("view-schedule")).toBeVisible();
  expectClean(problems);
});

test("approval of a schedule broken by a later edit is refused with the reason", async ({ page, request }) => {
  const problems = watch(page, [/STALE_SCHEDULE/, /409/]);
  const rec = await instantiate(request, "E2E stale", { jobs: 2 });
  const planId = rec.id;
  const run = await runVia(request, planId, { strategy: "heuristic", time_limit_seconds: 1 });
  const sch = await apiJson(request, `/schedules/${run.primary_schedule_id}`);
  const p = sch.placements[0];
  const doc = structuredClone(rec.problem);
  const res = doc.resources.find((x: { id: string }) => x.id === p.resource_ids[0]);
  res.calendar.blocked.push({ start: p.start_at, end: p.end_at, reason: "Breakdown" });
  const put = await request.put(`${API}/problems/${planId}`, { data: doc, headers: { "If-Match": '"1"' } });
  expect(put.status()).toBe(200);
  await page.goto(`/plans/${planId}/schedule?id=${sch.id}`);
  await expect(page.getByText(/was made for version 1; the plan is now version 2/)).toBeVisible();
  await page.getByTestId("approve-button").click();
  await page.getByRole("dialog").getByRole("button", { name: "Approve", exact: true }).click();
  const refused = page.getByRole("alert").filter({ hasText: "Approval refused" });
  await expect(refused).toBeVisible();
  await expect(refused).toContainText("not available");
  await expect(page.getByTestId("schedule-status")).toHaveAttribute("data-status", "candidate");
  expectClean(problems);
});
