import { test, expect } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { FINANCE_TEXT, SCHEDULE_TEXT, acceptAllSuggestions, apiGet, intakeKeys, watchIntake, watchSaves } from "./phase2-helpers";

// PHASE2 3.3, plan P3b-2 .. P3b-5, P3b-7, P4-2: describe -> questions -> draft -> create, AI off on this server.

test("schedule: describe the 2.15 text, use all suggestions, review, create, tasks tab shows parts and range chips", async ({ page, request }) => {
  const problems = watch(page);
  const saves = watchSaves(page);
  const intake = watchIntake(page);
  await page.goto("/new/project/describe");
  // AI is not offered on this server: no toggle, the built-in reader line instead (P3b-2)
  await expect(page.getByTestId("intake-ai-unavailable")).toHaveText("AI assist is not available on this server; the built-in reader is used.");
  await expect(page.getByTestId("intake-ai-toggle")).toHaveCount(0);
  await page.getByTestId("intake-text").fill(SCHEDULE_TEXT);
  await expect(page.getByTestId("intake-count")).toContainText(`${[...SCHEDULE_TEXT].length} /`);
  await page.getByTestId("intake-submit").click();

  // one question at a time
  await expect(page.locator(".bubble.ask.current")).toHaveCount(1);
  await expect(page.getByTestId("intake-question-SCHED_SEQUENTIAL")).toBeVisible();
  await expect(page.getByTestId("intake-live")).toContainText("Question:");
  const describeReq = intake.find((r) => r.url.endsWith("/intake/schedule/describe"))!;
  expect(describeReq.body.use_ai).toBe(false);
  expect(describeReq.body.text).toBe(SCHEDULE_TEXT);

  // the draft shows what was read, with confidence badges
  await expect(page.getByTestId("intake-draft")).toBeVisible();
  await expect(page.getByTestId("intake-field-/tasks/t1/duration")).toBeVisible();
  await expect(page.getByTestId("intake-confidence-/tasks/t1/duration")).toHaveText(/High/);

  // two-way highlight (P3b-5): hover a mark -> field active; hover the field -> mark active
  const mark = page.getByTestId("intake-source").locator('mark[data-path="/tasks/t1/duration"]');
  await expect(mark).toHaveText("2-3 days");
  await mark.hover();
  await expect(page.getByTestId("intake-field-/tasks/t1/duration")).toHaveClass(/active/);
  await page.getByTestId("intake-field-/tasks/t5/deadline").hover();
  await expect(page.getByTestId("intake-source").locator('mark[data-path="/tasks/t5/deadline"]')).toHaveClass(/active/);

  await page.getByTestId("intake-use-all-defaults").click();
  await expect(page.getByTestId("intake-no-questions")).toBeVisible();
  await expect(page.getByTestId("intake-questions-left")).toHaveText("All done");

  // review: counts and the PERT note (built automatically when nothing required is open)
  await expect(page.getByTestId("intake-build-summary")).toContainText(/23 tasks in 5 steps, 2 people/);
  await expect(page.getByTestId("intake-pert-note")).toBeVisible();
  await expect(page.getByTestId("intake-create")).toBeEnabled();
  expect(saves, "nothing saved before Create plan").toHaveLength(0);

  await page.getByTestId("intake-create").click();
  await page.waitForURL(/\/plans\/p_[0-9a-f]+\/tasks/);
  expect(saves).toHaveLength(1);
  const id = page.url().match(/\/plans\/(p_[0-9a-f]+)\//)![1];
  const rec = await apiGet(request, `/problems/${id}`);
  expect(rec.problem.metadata.intake).toMatchObject({ version: 1, source: "describe", extractor: "rule" });
  expect(rec.problem.tasks.find((t: any) => t.id === "t1_1").duration_estimate).toEqual({ optimistic_minutes: 320, likely_minutes: 400, pessimistic_minutes: 480 });
  await expect(page.getByLabel("Name of t1_1")).toHaveValue("Gather requirements (1/3)");
  await expect(page.getByTestId("task-range-t1_1")).toBeVisible();
  await expect(page.locator('button[data-testid^="task-range-"]')).toHaveCount(7);
  expect(await intakeKeys(page)).toEqual([]);
  expectClean(problems);
});

test("schedule: required question blocks Create plan until answered; typed answer with a range works", async ({ page }) => {
  const problems = watch(page);
  const saves = watchSaves(page);
  await page.goto("/new/project/describe");
  await page.getByTestId("intake-text").fill("- Write the brief 2 days\n- Review the brief after writing the brief\n- Publish by 30 Nov 2026");
  await page.getByTestId("intake-submit").click();
  const q = page.getByTestId("intake-question-SCHED_TASK_DURATION");
  await expect(q).toBeVisible();
  await expect(q).toContainText("Needed");
  await expect(page.getByTestId("intake-create")).toBeDisabled();
  await expect(page.getByTestId("intake-skip")).toHaveCount(0);           // required: no Skip
  // two tasks have no duration: answer both by typing (a range is fine)
  for (const typed of ["1-2 days", "3 hours"]) {
    const cur = page.getByTestId("intake-question-SCHED_TASK_DURATION");
    const qid = await cur.getAttribute("data-question-id");
    await cur.getByTestId("intake-question-input").locator("input, textarea").first().fill(typed);
    await page.getByTestId("intake-answer").click();
    await expect(page.locator(`[data-question-id="${qid}"]`)).toHaveCount(0, { timeout: 15_000 });
  }
  await expect(page.getByTestId("intake-question-SCHED_TASK_DURATION")).toHaveCount(0);
  await expect(page.getByTestId("intake-field-/tasks/t2/duration")).toBeVisible();
  await acceptAllSuggestions(page);
  await expect(page.getByTestId("intake-create")).toBeEnabled();
  expect(saves).toHaveLength(0);
  expectClean(problems);
});

test("schedule: Start over asks first and keeps the text; Cancel clears the session", async ({ page }) => {
  const problems = watch(page);
  await page.goto("/new/project/describe");
  await page.getByTestId("intake-text").fill(SCHEDULE_TEXT);
  await page.getByTestId("intake-submit").click();
  await expect(page.getByTestId("intake-draft")).toBeVisible();
  expect(await intakeKeys(page)).toEqual(["sp.intake.project"]);
  // survives a reload (sessionStorage)
  await page.reload();
  await expect(page.getByTestId("intake-draft")).toBeVisible();
  await page.getByTestId("intake-start-over").click();
  const dlg = page.getByRole("dialog");
  await expect(dlg).toContainText("Start over?");
  await dlg.getByRole("button", { name: "Start over" }).click();
  await expect(page.getByTestId("intake-text")).toHaveValue(SCHEDULE_TEXT);
  await page.getByTestId("intake-cancel").click();
  const leave = page.getByRole("dialog");
  await expect(leave).toContainText("Leave without creating a plan?");
  await leave.getByRole("button", { name: "Leave" }).click();
  await expect.poll(() => intakeKeys(page)).toEqual([]);
  expectClean(problems);
});

test("money: describe the 2.15 text, review shows the cash-flow line, create opens the wizard review", async ({ page, request }) => {
  const problems = watch(page);
  const saves = watchSaves(page);
  const intake = watchIntake(page);
  await page.goto("/new/money/describe");
  const accept = page.getByTestId("disclaimer-accept");
  if (await accept.isVisible().catch(() => false)) await accept.click();
  await expect(page.getByTestId("intake-ai-unavailable")).toBeVisible();
  await page.getByTestId("intake-text").fill(FINANCE_TEXT);
  await page.getByTestId("intake-submit").click();
  await expect(page.getByTestId("intake-draft")).toBeVisible();
  expect(intake.find((r) => r.url.endsWith("/intake/finance/describe"))!.body.use_ai).toBe(false);
  // the range is shown as from-to in the draft
  await expect(page.getByTestId("intake-field-/expenses/e1/amount")).toBeVisible();
  await acceptAllSuggestions(page);
  await expect(page.getByTestId("intake-cashflow")).toContainText(/About ₹[\d,]+ left each month in the first year/);
  const line = (await page.getByTestId("intake-cashflow").textContent())!;
  const left = Number(line.match(/₹([\d,]+)/)![1].replace(/,/g, ""));
  expect(left).toBeGreaterThan(0);
  expect(saves).toHaveLength(0);
  await page.getByTestId("intake-create").click();
  await page.waitForURL(/\/finance\/fp_[0-9a-f]+\/setup\/review/, { timeout: 15_000 });
  const id = page.url().match(/\/finance\/(fp_[0-9a-f]+)\//)![1];
  const rec = await apiGet(request, `/finance/plans/${id}`);
  const e1 = rec.plan.expenses.find((e: any) => e.id === "e1");
  expect(e1.amount).toBe(75000);
  expect(e1.amount_range).toEqual({ low: 70000, high: 80000 });
  expect(rec.plan.incomes.every((i: any) => i.inflation_linked)).toBe(true);
  expect(rec.plan.goals.find((g: any) => g.kind === "retirement").target_amount).toBe(22500000);
  expect(await intakeKeys(page)).toEqual([]);
  expectClean(problems);
});

test("spans are sliced by code point: a text with ₹ and an emoji highlights the right characters", async ({ page }) => {
  const problems = watch(page);
  await page.goto("/new/money/describe");
  const accept = page.getByTestId("disclaimer-accept");
  if (await accept.isVisible().catch(() => false)) await accept.click();
  const text = "🙂🙂 I'm 30. I take home ₹90,000 a month. 🚀 Rent ₹25,000 a month.";
  await page.getByTestId("intake-text").fill(text);
  await page.getByTestId("intake-submit").click();
  await expect(page.getByTestId("intake-draft")).toBeVisible();
  const marks = page.getByTestId("intake-source").locator("mark");
  const texts = await marks.allTextContents();
  // nested spans: each character goes to the shortest covering span, so the amounts are their own marks
  expect(texts).toContain("₹90,000 a month");
  expect(texts).toContain("₹25,000 a month");
  expect(texts).toContain("I'm 30");
  expect(texts.every((t) => !t.includes("🙂"))).toBe(true);
  expect(await page.getByTestId("intake-source").textContent()).toBe(text);
  expectClean(problems);
});

test("text over 20,000 characters is refused in the browser", async ({ page }) => {
  const problems = watch(page);
  const intake = watchIntake(page);
  await page.goto("/new/study/describe");
  await page.getByTestId("intake-text").fill("a".repeat(20_001));
  await expect(page.getByTestId("intake-count")).toHaveClass(/field-error/);
  await page.getByTestId("intake-submit").click();
  await expect(page.getByText("The text is too long: at most 20,000 characters.")).toBeVisible();
  expect(intake.filter((r) => r.url.includes("/describe"))).toHaveLength(0);
  expectClean(problems);
});

test("study: the page's own example text gives an exam, subjects and revisions, and creates an exam_prep plan", async ({ page, request }) => {
  const problems = watch(page);
  await page.goto("/new/study/describe");
  const placeholder = (await page.getByTestId("intake-text").getAttribute("placeholder"))!;
  const example = placeholder.replace(/^For example:\n/, "");
  await page.getByTestId("intake-text").fill(example);
  await page.getByTestId("intake-submit").click();
  await expect(page.getByTestId("intake-draft")).toBeVisible();
  // subjects are not people; the exam is a milestone called "Exam"
  await expect(page.getByTestId("intake-question-SCHED_PEOPLE")).toHaveCount(0);
  await expect(page.getByTestId("intake-draft")).not.toContainText(/Physics.*person|My exam is/);
  await acceptAllSuggestions(page);
  await expect(page.getByTestId("intake-create")).toBeEnabled();
  await page.getByTestId("intake-create").click();
  await page.waitForURL(/\/plans\/p_[0-9a-f]+\/tasks/);
  const id = page.url().match(/\/plans\/(p_[0-9a-f]+)\//)![1];
  const rec = await apiGet(request, `/problems/${id}`);
  expect(rec.problem.domain).toBe("exam_prep");
  const exam = rec.problem.tasks.filter((t: any) => t.type === "milestone");
  expect(exam.map((t: any) => t.name)).toEqual(["Exam"]);
  expect(exam[0].deadline_hard).toBe(true);
  expect(rec.problem.resources.map((r: any) => r.name)).not.toContain("Physics");
  expect(rec.problem.tasks.some((t: any) => /^Revise/.test(t.name))).toBe(true);
  expectClean(problems);
});

test("AI toggle (capabilities mocked as available): off on every visit, notice inline, use_ai sent, fallback shown", async ({ page }) => {
  const problems = watch(page);
  const intake = watchIntake(page);
  const notice = "AI assist sends the text in this box to Anthropic, an AI provider, to turn it into a draft. Test notice.";
  await page.route("**/api/v1/intake/capabilities", async (route) => {
    const real = await (await route.fetch()).json();
    await route.fulfill({ json: { ...real, ai_available: true, ai_reason: null, privacy_notice: notice } });
  });
  await page.goto("/new/project/describe");
  const toggle = page.getByTestId("intake-ai-toggle");
  await expect(toggle).toBeVisible();
  await expect(toggle).not.toBeChecked();
  await expect(page.getByTestId("intake-ai-notice")).toHaveCount(0);
  await expect(page.getByTestId("intake-submit")).toHaveText(/Make a draft/);
  await toggle.check();
  await expect(page.getByTestId("intake-ai-notice")).toContainText(notice);
  await expect(page.getByTestId("intake-submit")).toHaveText(/Send to AI assist and make a draft/);
  await page.getByTestId("intake-text").fill(SCHEDULE_TEXT);
  await page.getByTestId("intake-submit").click();
  // the real server has AI turned off: the draft comes from the built-in reader with the fallback message
  await expect(page.getByTestId("intake-extractor")).toContainText("AI assist is turned off on this server. We used the built-in reader instead.");
  expect(intake.find((r) => r.url.endsWith("/intake/schedule/describe"))!.body.use_ai).toBe(true);
  // a new visit starts with the toggle off again
  await page.getByTestId("intake-edit-text").click();
  await page.goto("/");
  await page.goto("/new/project/describe");
  await expect(page.getByTestId("intake-ai-toggle")).not.toBeChecked();
  expect(JSON.stringify(await page.evaluate(() => ({ ...sessionStorage })))).not.toContain('"use_ai":true');
  expectClean(problems);
});
