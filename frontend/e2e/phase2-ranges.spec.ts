import { test, expect, type APIRequestContext } from "@playwright/test";
import { API, apiJson, expectClean, gotoTab, openSchedule, optimize, watch } from "./helpers";
import { INTAKE, SCHEDULE_TEXT } from "./phase2-helpers";

// PHASE2 2.14 / 3.5, plan P3a-5: range chips, the range editor writes the PERT value, an inline duration
// edit and the switch to milestone remove the range (no 422), and the schedule shows the range risk.

const CTX = { today: "2026-10-17", utc_offset: "+05:30", locale: "en-IN", currency: "INR", kind: "project" };
const ANSWERS = [
  { question_id: "SCHED_WHO:/tasks/t4/resources", value: ["r_ravi"] },
  { question_id: "SCHED_WORKING_TIME:/working_time", use_default: true },
  { question_id: "SCHED_SEQUENTIAL:-", value: true },
  { question_id: "SCHED_PEOPLE:-", skip: true },
];
const pert = (o: number, m: number, p: number) => Math.floor((o + 4 * m + p + 3) / 6);

async function intakePlan(request: APIRequestContext, name: string): Promise<string> {
  const d = await (await request.post(`${INTAKE}/schedule/describe`, { data: { text: SCHEDULE_TEXT, context: CTX } })).json();
  const a = await (await request.post(`${INTAKE}/schedule/answer`, { data: { draft: d.draft, answers: ANSWERS, context: CTX } })).json();
  const b = await (await request.post(`${INTAKE}/schedule/build`, { data: { draft: a.draft, context: CTX } })).json();
  expect(b.ready).toBe(true);
  const r = await request.post(`${API}/problems`, { data: { ...b.problem, name } });
  expect(r.status()).toBe(201);
  return (await r.json()).id;
}

const task = async (request: APIRequestContext, id: string, tid: string) =>
  (await apiJson(request, `/problems/${id}`)).problem.tasks.find((t: any) => t.id === tid);

test("task table: chip, range editor writes the PERT value, inline edit and milestone switch drop the range", async ({ page, request }) => {
  const problems = watch(page);
  const id = await intakePlan(request, `E2E ranges ${Date.now()}`);
  await page.goto(`/plans/${id}/tasks`);
  const chip = page.getByTestId("task-range-t1_1");
  await expect(chip).toContainText("5h 20m-8h");

  // range editor in the details row
  await chip.click();
  const editor = page.getByTestId("task-range-editor-t1_1");
  await expect(editor).toBeVisible();
  await expect(editor.getByRole("checkbox", { name: "Duration is uncertain" })).toBeChecked();
  const longest = editor.getByLabel(/Longest duration of/);
  await longest.fill("9h");
  await longest.blur();
  await expect(page.getByTestId("save-state")).toHaveAttribute("data-state", "saved", { timeout: 10_000 });
  await expect.poll(async () => (await task(request, id, "t1_1")).duration_estimate?.pessimistic_minutes, { timeout: 10_000 }).toBe(540);
  const t1 = await task(request, id, "t1_1");
  expect(t1.duration_minutes).toBe(pert(320, 400, 540));

  // most likely above longest is refused inline (no request with an invalid estimate)
  const likely = editor.getByLabel(/Most likely duration of/);
  await likely.fill("10h");
  await likely.blur();
  await expect(editor.getByRole("alert")).toContainText("Shortest must not be above most likely");

  // inline edit of the single duration removes the range and saves (no 422)
  const dur = page.getByTestId("task-row-t4_1").getByLabel(/^Duration of/);
  await dur.fill("7h");
  await dur.blur();
  await expect(page.getByTestId("task-range-removed-t4_1")).toHaveText("Range removed");
  await expect.poll(async () => (await task(request, id, "t4_1")).duration_minutes, { timeout: 10_000 }).toBe(420);
  expect((await task(request, id, "t4_1")).duration_estimate ?? null).toBeNull();

  // switching to milestone removes it too
  await page.getByTestId("task-row-t4_2").getByLabel(/^Type of/).selectOption("milestone");
  await expect.poll(async () => (await task(request, id, "t4_2")).type, { timeout: 10_000 }).toBe("milestone");
  expect((await task(request, id, "t4_2")).duration_estimate ?? null).toBeNull();
  await expect(page.getByTestId("save-state")).toHaveAttribute("data-state", "saved", { timeout: 10_000 });
  expectClean(problems);
});

test("schedule: range risk line, dashed range lines and the drawer range", async ({ page, request }) => {
  const problems = watch(page);
  const id = await intakePlan(request, `E2E range schedule ${Date.now()}`);
  await page.goto(`/plans/${id}/tasks`);
  const runId = await optimize(page);
  const run = await apiJson(request, `/solver-runs/${runId}`);
  expect(run.feasibility).toBe("feasible");
  await openSchedule(page);
  await expect(page.getByTestId("duration-risk")).toContainText("have a duration range; the plan uses the expected values");
  await expect(page.locator('[data-testid^="gantt-range-"]').first()).toBeAttached();
  await page.getByTestId("gantt-bar-t1_1").click();
  await expect(page.getByTestId("task-drawer")).toBeVisible();
  await expect(page.getByTestId("drawer-duration-range")).toContainText("5h 20m");
  expectClean(problems);
  await gotoTab(page, /^Tasks/);
});
