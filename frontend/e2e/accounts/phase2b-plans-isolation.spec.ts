/**
 * Q6 / B 4.10 specs 3 + 6: a signed-in user creates plans in both domains with live solver and finance progress;
 * a second user cannot see them in lists, by URL, or by direct API GET (404).
 */
import { expect, test } from "@playwright/test";
import { createFromTemplate, expectClean, openSchedule, optimize, validateReady, watch } from "../helpers";
import { STEPS, acceptDisclaimer } from "../finance-helpers";
import { expect404, signInUI, signOutUI, signUpUI, uniqueEmail, uniqueName, waitTerminal } from "./accounts-helpers";

test("user A plans in both domains; user B sees none of them anywhere", async ({ page, browser }) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const sse: string[] = [];
  page.on("request", (r) => {
    if (/\/events(\?|$)/.test(r.url())) sse.push(r.url());
  });
  const emailA = uniqueEmail("ana");
  await signUpUI(page, emailA);

  // scheduling: template -> validate -> optimize with live progress -> Gantt
  const schedName = uniqueName("sched A");
  const problemId = await createFromTemplate(page, "manufacturing", schedName);
  await validateReady(page);
  const runId = await optimize(page);
  await openSchedule(page);
  const scheduleId = new URL(page.url()).searchParams.get("id")!;
  expect(scheduleId).toMatch(/^sch_/);
  expect(sse.some((u) => u.includes(`/solver-runs/${runId}/events`))).toBe(true);

  // finance: example card -> wizard -> build -> results with live progress
  const finName = uniqueName("fin A");
  await page.goto("/finance");
  await acceptDisclaimer(page);
  const card = page.getByTestId("fin-template-card-young_professional");
  await card.getByLabel("Plan name").fill(finName);
  await card.getByRole("button", { name: "Create plan" }).click();
  await page.waitForURL(/\/finance\/fp_[0-9a-f]+\/setup\/profile/);
  const planId = page.url().match(/\/finance\/(fp_[0-9a-f]+)\//)![1];
  for (let i = 0; i < STEPS.length - 1; i++) {
    await page.getByTestId("wizard-next").click();
    await page.waitForURL(new RegExp(`/setup/${STEPS[i + 1]}$`));
  }
  await page.getByTestId("build-plan").click();
  await page.waitForURL(/\/results\?run=frun_/);
  const finRunId = new URL(page.url()).searchParams.get("run")!;
  await expect(page.getByTestId("fin-run-progress")).toBeVisible();
  const finRun = await waitTerminal(page.request, `/finance/runs/${finRunId}`);
  expect(finRun.status).toBe("completed");
  const resultId = finRun.result_id as string;
  await expect(page.getByTestId("goal-card-car")).toBeVisible({ timeout: 60_000 });
  expect(sse.some((u) => u.includes(`/finance/runs/${finRunId}/events`))).toBe(true);
  expectClean(problems);
  await signOutUI(page);

  // user B in a separate browser
  const ctxB = await browser.newContext();
  const pageB = await ctxB.newPage();
  const problemsB = watch(pageB, [/-> 404 /]);
  await signUpUI(pageB, uniqueEmail("ben"));
  await pageB.goto("/");
  await expect(pageB.getByTestId("plan-list")).toBeVisible();
  await expect(pageB.getByTestId(`plan-item-${problemId}`)).toHaveCount(0);
  await expect(pageB.getByText(schedName)).toHaveCount(0);
  await pageB.goto("/finance");
  await acceptDisclaimer(pageB);
  await expect(pageB.getByTestId(`fin-plan-${planId}`)).toHaveCount(0);
  await expect(pageB.getByText(finName)).toHaveCount(0);
  // by URL
  await pageB.goto(`/plans/${problemId}/tasks`);
  await expect(pageB.getByText(/not found/i).first()).toBeVisible();
  await expect(pageB.getByText(schedName)).toHaveCount(0);
  await pageB.goto(`/plans/${problemId}/schedule?id=${scheduleId}`);
  await expect(pageB.getByText(/not found/i).first()).toBeVisible();
  await pageB.goto(`/finance/${planId}/results`);
  await expect(pageB.getByRole("heading", { name: "Plan not found" })).toBeVisible();
  await expect(pageB.getByText(finName)).toHaveCount(0);
  // by direct API GET
  for (const p of [`/problems/${problemId}`, `/problems/${problemId}/export`, `/problems/${problemId}/schedules`,
    `/problems/${problemId}/solver-runs`, `/schedules/${scheduleId}`, `/schedules/${scheduleId}/export.csv`,
    `/solver-runs/${runId}`, `/solver-runs/${runId}/events?stream=false`, `/finance/plans/${planId}`,
    `/finance/plans/${planId}/runs`, `/finance/plans/${planId}/results`, `/finance/runs/${finRunId}`,
    `/finance/runs/${finRunId}/events?stream=false`, `/finance/results/${resultId}`,
    `/finance/results/${resultId}/contributions.csv`]) {
    await expect404(pageB.request, p);
  }
  expect(problemsB.pageErrors).toEqual([]);
  await ctxB.close();

  // A still has everything
  await signInUI(page, emailA);
  await page.goto("/");
  await expect(page.getByTestId(`plan-item-${problemId}`)).toBeVisible();
  await page.goto("/finance");
  await expect(page.getByTestId(`fin-plan-${planId}`)).toBeVisible();
});
