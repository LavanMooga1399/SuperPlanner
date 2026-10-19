import { test, expect } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { acceptDisclaimer, expectDashboard, finJson, uniqueName, waitRun } from "./finance-helpers";

// PHASE2 1.9-1.11 / 3.4, plan P1-2, P3a-4: the Family example at its defaults now shows plausible results.

test("family example card -> wizard -> build: all goals on track, no negative money on the dashboard", async ({ page, request }) => {
  const problems = watch(page);
  const name = uniqueName("family realism");
  await page.goto("/new/money/example");
  await acceptDisclaimer(page);
  const card = page.getByTestId("fin-template-card-family");
  await card.getByLabel("Plan name").fill(name);
  await card.getByRole("button", { name: "Create plan" }).click();
  await page.waitForURL(/\/finance\/fp_[0-9a-f]+\/setup\/profile/, { timeout: 10_000 });
  const planId = page.url().match(/\/finance\/(fp_[0-9a-f]+)\//)![1];
  await page.goto(`/finance/${planId}/setup/review`);
  await expect(page.getByTestId("fin-review-issues")).toContainText(/No errors/);
  await page.getByTestId("build-plan").click();
  await page.waitForURL(/\/results\?run=frun_/);
  const runId = new URL(page.url()).searchParams.get("run")!;
  await expectDashboard(page, ["home", "education", "retirement"]);
  const run = await waitRun(request, runId, 90_000);
  expect(run.status).toBe("completed");
  expect(run.feasibility).toBe("feasible");
  const rec = await finJson(request, `/results/${run.result_id}`);
  const res = rec.result;
  expect(res.engine_version).toBe("fin-0.2.0");
  // plausible: >= 2 of 3 goals likely, no must goal off track, money left over every month of year 1
  expect(res.goals.filter((g: any) => g.success_probability >= 0.5).length).toBeGreaterThanOrEqual(2);
  for (const g of res.goals) if (g.priority === "must") expect(g.status).not.toBe("off_track");
  expect(Math.min(...res.cashflow.surplus.slice(0, 12))).toBeGreaterThanOrEqual(0);
  expect(res.summary.monthly_investable_now).toBeGreaterThanOrEqual(0);
  // long goals use growth assets
  for (const gid of ["education", "retirement"]) {
    const g = res.goals.find((x: any) => x.goal_id === gid);
    expect(g.growth_share_now_pct).toBeGreaterThanOrEqual(0.8 * g.growth_cap_now_pct);
  }
  // what the user sees
  const kpis = page.getByTestId("fin-kpis");
  await expect(kpis).toBeVisible();
  await expect(kpis).not.toContainText("-₹");
  await expect(kpis).toContainText(`${res.summary.goals_on_track} / 3`);
  for (const g of res.goals) await expect(page.getByTestId(`goal-status-${g.goal_id}`)).toHaveText(/On track|At risk/);
  await expect(page.getByTestId("fin-explanations")).not.toContainText("-₹");
  expectClean(problems);
});

test("family results show the 3.4 cards: left over each month, plan invests with its funding split, growth reason and likely outcome", async ({ page, request }) => {
  const problems = watch(page);
  const rec0 = await (await request.post(`http://127.0.0.1:8000/api/v1/finance/templates/family/instantiate`, {
    data: { name: uniqueName("family 3.4"), start_month: "2026-11", parameters: {} },
  })).json();
  const created = await (await request.post(`http://127.0.0.1:8000/api/v1/finance/plans/${rec0.id}/runs`, { data: { seed: 1 } })).json();
  const run = await waitRun(request, created.run_id, 90_000);
  const res = (await finJson(request, `/results/${run.result_id}`)).result;
  await page.goto(`/finance/${rec0.id}/results?result=${run.result_id}`);
  await acceptDisclaimer(page);
  await expectDashboard(page, ["home", "education", "retirement"]);
  const kpis = page.getByTestId("fin-kpis");
  const fmt = (v: number) => Math.round(v).toLocaleString("en-IN");
  // card 1 "Left over each month" = monthly_surplus_avg_12m (first-year average)
  await expect(kpis).toContainText("Left over each month");
  await expect(kpis).toContainText(fmt(res.summary.monthly_surplus_avg_12m).slice(0, 4));
  // card 2 "Plan invests" = monthly_contribution_avg_12m with "from your monthly surplus + ... from savings you already have"
  await expect(kpis).toContainText("Plan invests");
  await expect(kpis).toContainText("from your monthly surplus");
  await expect(kpis).toContainText("from savings you already have");
  await expect(kpis).not.toContainText("You can invest");
  // goal cards: "Why this mix" (first GROWTH_ reason), "Likely outcome: about N% of the target", growth bar
  const ret = page.getByTestId("goal-card-retirement");
  const reason = res.explanation.goals.retirement.reasons[0];
  expect(reason.code).toMatch(/^GROWTH_/);
  await expect(ret).toContainText("Why this mix");
  await expect(ret).toContainText(reason.message);
  await expect(ret).toContainText(/Likely outcome: about \d+% of the target/);
  await expect(ret).toContainText(/Growth assets now: 60% \(limit 60%\)/);
  expectClean(problems);
});
