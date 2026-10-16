import { test, expect } from "@playwright/test";
import * as fs from "node:fs";
import { API, apiJson, expectClean, watch } from "./helpers";
import {
  acceptDisclaimer,
  DISCLAIMER_START,
  expectDashboard,
  finJson,
  instantiate,
  planWithResult,
  STEP_LABELS,
  STEPS,
  uniqueName,
  waitRun,
} from "./finance-helpers";

test("finance journey: template young_professional -> wizard -> build -> live progress -> dashboard", async ({ page, request }) => {
  const problems = watch(page);
  const name = uniqueName("journey");
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(page.getByTestId("nav-scheduling")).toHaveAttribute("aria-current", "page");
  await page.getByTestId("nav-finance").click();
  await page.waitForURL(/\/finance$/);
  await acceptDisclaimer(page);
  await expect(page.getByTestId("nav-finance")).toHaveAttribute("aria-current", "page");
  await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
  await expect(page.getByTestId("disclaimer-banner")).toContainText(DISCLAIMER_START);

  // The example card itself is covered by the next test; here the plan comes from the same template via the
  // API (finance-helpers), then the user opens it from the plan list.
  const rec = await instantiate(request, "young_professional", name);
  const planId = rec.id as string;
  await page.reload();
  await page.getByTestId(`fin-plan-${planId}`).getByRole("link", { name }).click();
  await page.waitForURL(new RegExp(`/finance/${planId}/setup/profile$`));

  // Next through all seven steps; each has its label, help text and a skip button
  for (let i = 0; i < STEPS.length; i++) {
    const step = STEPS[i];
    const panel = page.getByTestId(`wizard-panel-${step}`);
    await expect(panel).toBeVisible();
    await expect(panel.getByRole("heading", { level: 1 })).toHaveText(STEP_LABELS[i]);
    await expect(page.getByTestId(`wizard-step-${step}`)).toBeVisible();
    await expect(page.getByTestId("disclaimer-banner")).toBeVisible();
    if (i < STEPS.length - 1) {
      await expect(page.getByTestId("wizard-skip")).toHaveText(/Skip - use defaults/);
      await page.getByTestId("wizard-next").click();
      await page.waitForURL(new RegExp(`/setup/${STEPS[i + 1]}$`));
    }
  }
  await expect(page.getByTestId("fin-review-issues")).toContainText(/No errors/);
  const build = page.getByTestId("build-plan");
  await expect(build).toBeEnabled();
  await build.click();
  await page.waitForURL(/\/results\?run=frun_/);
  const runId = new URL(page.url()).searchParams.get("run")!;
  await expect(page.getByTestId("fin-run-progress")).toBeVisible();
  await expect(page.getByTestId("fin-run-status")).toBeVisible();
  await expectDashboard(page, ["car", "retirement"]);
  const run = await waitRun(request, runId);
  expect(run.status).toBe("completed");
  expect(run.feasibility).toBe("feasible");
  // the wizard stored its progress and the plan list shows the plan
  const stored = await finJson(request, `/plans/${planId}`);
  expect(stored.plan.metadata.wizard.completed_steps).toEqual(expect.arrayContaining(STEPS.slice(0, 6) as unknown as string[]));
  await page.getByTestId("nav-finance").click();
  await expect(page.getByTestId("fin-plan-list")).toContainText(name);
  expectClean(problems);
});

for (const tpl of [
  { id: "young_professional", goals: ["car", "retirement"] },
  { id: "family", goals: ["home", "education", "retirement"] },
  { id: "near_retirement", goals: ["retirement", "wedding"] },
]) {
  test(`example card ${tpl.id}: "Create plan" at the default values opens the wizard`, async ({ page, request }) => {
    const problems = watch(page);
    const name = uniqueName(`card ${tpl.id}`);
    await page.goto("/finance");
    await acceptDisclaimer(page);
    const card = page.getByTestId(`fin-template-card-${tpl.id}`);
    await card.getByLabel("Plan name").fill(name);
    await card.getByRole("button", { name: "Create plan" }).click();
    await page.waitForURL(/\/finance\/fp_[0-9a-f]+\/setup\/profile/, { timeout: 10_000 });
    const planId = page.url().match(/\/finance\/(fp_[0-9a-f]+)\//)![1];
    const rec = await finJson(request, `/plans/${planId}`);
    expect(rec.template_id).toBe(tpl.id);
    expect(rec.plan.name).toBe(name);
    expect(rec.plan.goals.map((g: { id: string }) => g.id)).toEqual(tpl.goals);
    expectClean(problems);
  });
}

test("what-if slider re-runs once after quick moves, shows deltas; compare lists both scenarios", async ({ page, request }) => {
  const problems = watch(page);
  const { planId, resultId } = await planWithResult(request, "young_professional", uniqueName("whatif"));
  await page.goto(`/finance/${planId}/results`);
  await acceptDisclaimer(page);
  await expectDashboard(page, ["car", "retirement"]);
  await page.getByTestId("open-what-if").click();
  await page.waitForURL(/\/what-if/);
  const slider = page.getByTestId("whatif-savings");
  await expect(slider).toBeVisible();
  await slider.focus();
  // three quick moves (step 1000 each) inside the 800 ms debounce -> one run
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
  const result = page.getByTestId("whatif-result");
  await expect(result).toBeVisible({ timeout: 60_000 });
  await expect(result.getByTestId("whatif-compare-table")).toBeVisible({ timeout: 60_000 });
  await expect(result.getByTestId("goal-card-car")).toBeVisible();
  const runs = (await finJson(request, `/plans/${planId}/runs`)).items.filter((r: { kind: string }) => r.kind === "what_if");
  expect(runs).toHaveLength(1);
  expect(runs[0].what_if.extra_monthly_savings).toBe(3000);
  expect(runs[0].status).toBe("completed");
  const whatIfResult = runs[0].result_id as string;
  await expect(result.getByTestId("whatif-compare-table")).toContainText(/Car/);

  // compare page shows the F.13 table for ?a=&b=
  await page.goto(`/finance/${planId}/compare?a=${resultId}&b=${whatIfResult}`);
  const table = page.getByTestId("fin-compare-table");
  await expect(table).toBeVisible();
  await expect(table).toContainText("Car");
  await expect(table).toContainText("Retirement");
  await expect(table).toContainText(/A:/);
  await expect(table).toContainText(/B:/);
  await expect(page.getByTestId("disclaimer-banner")).toBeVisible();
  expectClean(problems);
});

test("fix 'Try this' opens the what-if with that run; Apply to my plan saves ordinary ids and re-runs", async ({ page, request }) => {
  const problems = watch(page);
  const { planId, resultId } = await planWithResult(request, "young_professional", uniqueName("fix"));
  const before = await finJson(request, `/plans/${planId}`);
  await page.goto(`/finance/${planId}/results?result=${resultId}`);
  await acceptDisclaimer(page);
  await expectDashboard(page, ["car", "retirement"]);
  const fix = page.locator('[data-testid^="fix-car-"]').first();
  await expect(fix).toBeVisible();
  const kind = (await fix.getAttribute("data-testid"))!.replace("fix-car-", "");
  await fix.getByRole("button", { name: /Try this/ }).click();
  await page.waitForURL(/\/what-if\?.*run=frun_/);
  const runId = new URL(page.url()).searchParams.get("run")!;
  await expect(page.getByTestId("whatif-result")).toBeVisible({ timeout: 60_000 });
  const run = await finJson(request, `/runs/${runId}`);
  expect(run.kind).toBe("what_if");
  const res = await finJson(request, `/results/${resultId}`);
  const sent = res.result.explanation.goals.car.fixes.find((f: { kind: string }) => f.kind === kind);
  expect(run.what_if).toMatchObject(sent.what_if);

  const puts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "PUT" && r.url().includes(`/finance/plans/${planId}`)) puts.push(r.postData() ?? "");
  });
  await page.getByTestId("whatif-apply").click();
  await page.waitForURL(/\/results\?run=frun_/);
  await expectDashboard(page, ["car", "retirement"]);
  expect(puts.length).toBeGreaterThan(0);
  for (const body of puts) expect(body).not.toContain("whatif_");
  const after = await finJson(request, `/plans/${planId}`);
  expect(after.version).toBeGreaterThan(before.version);
  expect(JSON.stringify(after.plan)).not.toContain("whatif_");
  expect(JSON.stringify(after.plan)).not.toEqual(JSON.stringify(before.plan));
  expectClean(problems);
});

test("export CSV starts with the disclaimer; send to planner opens the new plan with tasks", async ({ page, request }) => {
  const problems = watch(page);
  const { planId, resultId } = await planWithResult(request, "young_professional", uniqueName("export"));
  await page.goto(`/finance/${planId}/results?result=${resultId}`);
  await acceptDisclaimer(page);
  await expectDashboard(page, ["car", "retirement"]);

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("fin-export-csv").click()]);
  expect(download.suggestedFilename()).toMatch(/-contributions\.csv$/);
  const text = fs.readFileSync((await download.path())!, "utf8");
  expect(text.startsWith(`# ${DISCLAIMER_START}`)).toBeTruthy();
  const lines = text.split(/\r?\n/);
  expect(lines[1]).toBe("month,action,goal_id,goal_name,priority,asset_class_id,asset_class_name,amount_today_money,amount_expected_nominal");
  expect(lines.length).toBeGreaterThan(10);

  await page.getByTestId("send-to-planner").click();
  const dlg = page.getByRole("dialog");
  await expect(dlg).toBeVisible();
  await dlg.getByTestId("send-to-planner-confirm").click();
  await page.waitForURL(/\/plans\/p_[0-9a-f]+\/tasks/);
  const problemId = page.url().match(/\/plans\/(p_[0-9a-f]+)\//)![1];
  const prob = await apiJson(request, `/problems/${problemId}`);
  expect(prob.problem.metadata.finance_result_id).toBe(resultId);
  expect(prob.problem.tasks.length).toBeGreaterThan(3);
  for (const t of prob.problem.tasks.slice(0, 3)) await expect(page.getByTestId(`task-row-${t.id}`)).toBeVisible();
  // the scheduling area is active again
  await expect(page.getByTestId("nav-scheduling")).toHaveAttribute("aria-current", "page");
  expectClean(problems);
});

test("start from scratch: one income and one goal are enough; a past goal date blocks the build", async ({ page, request }) => {
  const problems = watch(page);
  await page.goto("/finance");
  await acceptDisclaimer(page);
  await page.getByTestId("fin-start-blank").click();
  await page.waitForURL(/\/finance\/fp_[0-9a-f]+\/setup\/profile/);
  const planId = page.url().match(/\/finance\/(fp_[0-9a-f]+)\//)![1];
  await page.getByTestId("wizard-panel-profile").getByLabel(/plan name/i).first().fill(uniqueName("scratch"));
  await page.getByTestId("wizard-next").click();
  await page.waitForURL(/\/setup\/income$/);

  // one income; the live preview updates within about a second
  await page.getByTestId("add-income").click();
  const incomeRow = page.locator('[data-testid^="income-row-"]').first();
  await expect(incomeRow).toBeVisible();
  const incomeId = (await incomeRow.getAttribute("data-testid"))!.replace("income-row-", "");
  await page.getByTestId(`income-amount-${incomeId}`).fill("50000");
  await expect(page.getByTestId("fin-preview-investable")).toContainText(/You can invest about/, { timeout: 5_000 });
  // 50,000 nominal a month, no expenses: the first-year average in today's money is a little below 50,000
  await expect(page.getByTestId("fin-preview-investable")).toContainText(/₹4[89],\d{3}/);

  // skip debts and savings, add one goal
  await page.getByTestId("wizard-next").click();
  await page.waitForURL(/\/setup\/debts$/);
  await page.getByTestId("wizard-skip").click();
  await page.waitForURL(/\/setup\/savings$/);
  await page.getByTestId("wizard-skip").click();
  await page.waitForURL(/\/setup\/goals$/);
  await page.getByTestId("goal-preset-vehicle").click();
  const goalRow = page.locator('[data-testid^="goal-row-"]').first();
  await expect(goalRow).toBeVisible();
  const goalId = (await goalRow.getAttribute("data-testid"))!.replace("goal-row-", "");

  // a goal date in the past -> review error, build disabled, link back to Goals
  await page.getByTestId(`goal-month-${goalId}`).fill("2020-01");
  await page.getByTestId("wizard-next").click();
  await page.waitForURL(/\/setup\/assumptions$/);
  await page.getByTestId("wizard-step-review").click();
  await page.waitForURL(/\/setup\/review$/);
  const issue = page.getByTestId("fin-issue-GOAL_TOO_SOON");
  await expect(issue).toBeVisible();
  await expect(issue).toHaveAttribute("data-severity", "error");
  await expect(page.getByTestId("build-plan")).toBeDisabled();
  await issue.getByRole("link", { name: /Fix in Goals/ }).click();
  await page.waitForURL(/\/setup\/goals$/);

  // fix it: 3 years from now -> build works with defaults for everything else
  await page.getByTestId(`goal-years-${goalId}`).fill("3");
  await page.getByTestId("wizard-step-review").click();
  await page.waitForURL(/\/setup\/review$/);
  await expect(page.getByTestId("fin-issue-GOAL_TOO_SOON")).toHaveCount(0);
  const build = page.getByTestId("build-plan");
  await expect(build).toBeEnabled({ timeout: 20_000 });
  await build.click();
  await page.waitForURL(/\/results\?run=frun_/);
  await expectDashboard(page, [goalId]);
  const rec = await finJson(request, `/plans/${planId}`);
  expect(rec.plan.incomes).toHaveLength(1);
  expect(rec.plan.goals).toHaveLength(1);
  expect(rec.plan.expenses).toHaveLength(0);
  expect(JSON.stringify(rec.plan)).not.toContain("whatif_");
  // the review error was a real GOAL_TOO_SOON, not a client-side message (any 4xx is unexpected here)
  expectClean(problems);
});

test("autosave: fast Next clicks give no conflict; an edit made elsewhere shows the conflict banner", async ({ page, request }) => {
  const problems = watch(page, [/PUT \/finance\/plans\/fp_[0-9a-f]+ -> 412/, /412/]);
  const rec = await instantiate(request, "young_professional", uniqueName("autosave"));
  const planId = rec.id as string;
  await page.goto(`/finance/${planId}/setup/income`);
  await acceptDisclaimer(page);
  // edit, then click Next immediately, twice in a row (single-flight saves, no spurious 412)
  await page.getByTestId("income-amount-salary").fill("61000");
  await page.getByTestId("wizard-next").click();
  await page.waitForURL(/\/setup\/debts$/);
  await page.getByTestId("wizard-next").click();
  await page.waitForURL(/\/setup\/savings$/);
  await expect(page.getByTestId("fin-conflict-banner")).toHaveCount(0);
  await expect(page.getByTestId("fin-save-state")).toHaveAttribute("data-state", "saved");
  let stored = await finJson(request, `/plans/${planId}`);
  expect(stored.plan.incomes[0].amount).toBe(61000);
  // another tab changes the plan
  const other = { ...stored.plan, description: "changed elsewhere" };
  const put = await request.put(`${API}/finance/plans/${planId}`, { data: other, headers: { "If-Match": `"${stored.version}"` } });
  expect(put.status()).toBe(200);
  // this tab edits and autosaves after 1.5 s -> 412 -> conflict banner
  await page.getByTestId("wizard-back").click();
  await page.waitForURL(/\/setup\/debts$/);
  await page.getByTestId("wizard-back").click();
  await page.waitForURL(/\/setup\/income$/);
  await page.getByTestId("income-amount-salary").fill("62000");
  await expect(page.getByTestId("fin-conflict-banner")).toBeVisible({ timeout: 10_000 });
  stored = await finJson(request, `/plans/${planId}`);
  expect(stored.plan.description).toBe("changed elsewhere");
  expect(stored.plan.incomes[0].amount).toBe(61000);
  expect(problems.pageErrors).toEqual([]);
});

test("dark mode: charts and disclaimer render", async ({ page, request }) => {
  const problems = watch(page);
  const { planId } = await planWithResult(request, "family", uniqueName("dark"));
  await page.goto(`/finance/${planId}/results`);
  await acceptDisclaimer(page);
  await expectDashboard(page, ["home", "education", "retirement"]);
  const html = page.locator("html");
  const before = (await html.getAttribute("data-theme")) ?? "light";
  await page.getByTestId("theme-toggle").click();
  await expect(html).not.toHaveAttribute("data-theme", before);
  const theme = await html.getAttribute("data-theme");
  if (theme !== "dark") {
    await page.getByTestId("theme-toggle").click();
    await expect(html).toHaveAttribute("data-theme", "dark");
  }
  await expectDashboard(page, ["home", "education", "retirement"]);
  for (const id of ["corpus-chart", "glide-chart", "cashflow-chart"]) {
    const chart = page.getByTestId(id);
    await expect(chart.locator("svg").first()).toBeVisible();
    const box = await chart.locator("svg").first().boundingBox();
    expect(box && box.width > 100 && box.height > 50, `${id} has a size`).toBeTruthy();
    await expect(chart.locator('[role="img"]').first()).toHaveAttribute("aria-label", /.+/);
  }
  // series colours come from the palette variables, which differ in dark mode
  const c1 = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--fin-c1").trim());
  expect(c1).not.toBe("");
  expectClean(problems);
});

test("navigation: exactly one main nav item is active; unknown finance paths show NotFound", async ({ page }) => {
  await page.goto("/finance/fp_doesnotexist/setup/nope/extra");
  await acceptDisclaimer(page);
  await expect(page.getByText(/not found/i).first()).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
  await expect(page.getByTestId("nav-finance")).toHaveAttribute("aria-current", "page");
  await page.getByTestId("nav-scheduling").click();
  await expect(page.getByTestId("nav-scheduling")).toHaveAttribute("aria-current", "page");
  await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
});
