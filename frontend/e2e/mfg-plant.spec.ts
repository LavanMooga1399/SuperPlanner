/**
 * WP-D (M1-DESIGN 15.4 mfg-plant): stages and lines, a 3-shift template whose night shift crosses midnight with its
 * weekly preview, base vs optional assignments (group vs line override), calendar exception and the month view.
 * Plant offset of the `small` sample: +05:30.
 */
import { test, expect, type Page } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { calendarDay, findByCode, gotoMfg, loadSample, mfgJson, resetMfg, weekSegments } from "./mfg-helpers";

test.beforeEach(async ({ request }) => {
  await resetMfg(request);
});

async function createStageAndLines(page: Page): Promise<void> {
  await gotoMfg(page, "/plant/groups");
  await page.getByTestId("group-new").click();
  await page.getByTestId("group-code").fill("E2E-G");
  await page.getByTestId("group-name").fill("E2E stage");
  await page.getByTestId("group-save").click();
  await expect(page.locator('[data-testid="group-row"][data-code="E2E-G"]')).toBeVisible();
  for (const code of ["E2E-L1", "E2E-L2"]) {
    await page.locator('[data-testid="group-row"][data-code="E2E-G"]').click();
    await page.getByTestId("line-new").click();
    await page.getByTestId("line-code").fill(code);
    await page.getByTestId("line-name").fill(`Line ${code}`);
    await page.getByTestId("line-save").click();
    await expect(page.locator(`[data-testid="line-row"][data-code="${code}"]`)).toBeVisible();
  }
}

async function assign(page: Page, o: { template: string; target: "group" | "line"; id: string; kind: "base" | "optional"; from: string; cost?: string }) {
  await page.getByTestId("assignment-new").click();
  const form = page.getByTestId("assignment-form");
  await form.getByTestId("assignment-template").selectOption(o.template);
  await form.getByTestId("assignment-target-type").selectOption(o.target);
  await form.getByTestId(o.target === "group" ? "assignment-group" : "assignment-line").selectOption(o.id);
  await form.getByTestId("assignment-kind").selectOption(o.kind);
  await form.getByTestId("assignment-from").fill(o.from);
  if (o.cost) await form.getByTestId("assignment-cost").fill(o.cost);
  const created = page.waitForResponse((r) => r.url().endsWith("/mfg/shift-assignments") && r.request().method() === "POST");
  await page.getByTestId("assignment-form-submit").click();
  const rec = (await (await created).json()) as { id: string };
  expect((await created).status()).toBe(201);
  // D2: the dialog closes and the new row is highlighted (not reopened for editing)
  await expect(form).toHaveCount(0);
  await expect(page.locator(`[data-testid="assignment-row"][data-assignment-id="${rec.id}"]`)).toHaveClass(/mfg-selected/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

test("3-shift template: night shift split across midnight in the weekly preview; assignments; month view; holiday", async ({ page, request }) => {
  test.setTimeout(150_000);
  await loadSample(request, "small");
  // only the deliberate overlap below may be refused; a 422 about the (still empty) code / name must not happen (D3)
  const problems = watch(page, [/POST \/mfg\/shift-templates\/preview -> 422 (?!.*"(code|name)")/, /status of 422/]);
  await createStageAndLines(page);

  // --- shift template from the "three shifts" pattern
  await gotoMfg(page, "/plant/shifts");
  await page.getByTestId("template-new").click();
  // the pattern first: the live preview works before Code and Name are filled in (D3)
  await page.getByTestId("template-pattern").selectOption("three");
  await expect(page.getByTestId("shift-def")).toHaveCount(3);
  const preview = page.getByTestId("shift-week-preview");
  await expect(preview).toHaveAttribute("data-loading", "false");
  await expect(weekSegments(page, "C", "start")).toHaveCount(6);
  await expect(weekSegments(page, "C", "end")).toHaveCount(6);
  const startDays = await weekSegments(page, "C", "start").evaluateAll((els) => els.map((e) => e.getAttribute("data-day")));
  const endDays = await weekSegments(page, "C", "end").evaluateAll((els) => els.map((e) => e.getAttribute("data-day")));
  expect(startDays).toEqual(["mon", "tue", "wed", "thu", "fri", "sat"]);
  expect(endDays.sort()).toEqual(["fri", "sat", "sun", "thu", "tue", "wed"]);
  // the part before midnight ends at 24:00, the continuation starts at 00:00 (minutes of the day)
  for (const seg of await weekSegments(page, "C", "start").all()) await expect(seg).toHaveAttribute("data-to", "1440");
  for (const seg of await weekSegments(page, "C", "end").all()) await expect(seg).toHaveAttribute("data-from", "0");
  await expect(weekSegments(page, "A", "none")).toHaveCount(12); // A is split by its meal break: 2 pieces x 6 days
  // the totals equal the server's preview (8,100 min = 135 h)
  await expect(page.getByTestId("shift-week-totals")).toContainText("135 h");
  await expect(page.getByText("These shifts do not fit together")).toHaveCount(0);
  await page.getByTestId("template-code").fill("3S-E2E");
  await page.getByTestId("template-name").fill("Three shifts (e2e)");
  // editing a shift updates the preview: C ends at 07:00 overlaps A (06:00) -> server error shown, then fix
  await page.getByTestId("shift-def").nth(2).getByTestId("shift-end").fill("07:00");
  await expect(preview.or(page.getByTestId("mfg-error"))).toBeVisible();
  await page.getByTestId("shift-def").nth(2).getByTestId("shift-end").fill("06:00");
  await expect(weekSegments(page, "C", "end")).toHaveCount(6);
  await page.getByTestId("template-save").click();
  await expect(page.locator('[data-testid="template-row"]', { hasText: "3S-E2E" })).toBeVisible();
  const tpl = await findByCode(request, "/shift-templates", "3S-E2E");
  const tplRec = await mfgJson<{ shifts: { name: string; start: string; end: string; days: string[] }[] }>(request, `/shift-templates/${tpl.id}`);
  expect(tplRec.shifts.map((s) => `${s.name} ${s.start}-${s.end}`)).toEqual(["A 06:00-14:00", "B 14:00-22:00", "C 22:00-06:00"]);

  // --- assignments: base REG on the stage, optional EVE on line 1, base 3S-E2E on line 2 (line overrides stage)
  const g = await findByCode(request, "/groups", "E2E-G");
  const l1 = await findByCode(request, "/lines", "E2E-L1");
  const l2 = await findByCode(request, "/lines", "E2E-L2");
  const reg = await findByCode(request, "/shift-templates", "REG");
  const eve = await findByCode(request, "/shift-templates", "EVE");
  await assign(page, { template: reg.id, target: "group", id: g.id, kind: "base", from: "2026-11-01" });
  await assign(page, { template: eve.id, target: "line", id: l1.id, kind: "optional", from: "2026-11-01", cost: "300" });
  await assign(page, { template: tpl.id, target: "line", id: l2.id, kind: "base", from: "2026-11-01" });
  const asg = await mfgJson<{ items: { kind: string; target: { code: string }; template: { code: string }; cost_per_hour: number | null }[] }>(request, "/shift-assignments");
  const mine = asg.items.filter((a) => a.target.code.startsWith("E2E-")).map((a) => `${a.target.code} ${a.template.code} ${a.kind} ${a.cost_per_hour}`);
  expect(mine.sort()).toEqual(["E2E-G REG base null", "E2E-L1 EVE optional 300", "E2E-L2 3S-E2E base null"]);
  await expect(page.locator('[data-testid="assignment-row"]', { hasText: "E2E-L1" })).toContainText(/optional/i);

  // --- month view (Nov 2026): line 1 = REG base 09:00-18:00 - lunch 45 min = 495 min, EVE optional 18-22 - 15 = 225
  await gotoMfg(page, `/plant/calendar?line=${l1.id}`);
  await page.getByTestId("calendar-month").fill("2026-11");
  const cal = page.getByTestId("line-calendar");
  await expect(cal).toHaveAttribute("data-month", "2026-11");
  await expect(cal).toHaveAttribute("data-loading", "false");
  const w = await mfgJson<{ windows: { start: string; kind: string }[] }>(request, `/lines/${l1.id}/windows?from=2026-11-01&to=2026-12-01`);
  expect(w.windows.length).toBeGreaterThan(0);
  await expect(calendarDay(page, "2026-11-03")).toHaveAttribute("data-base-minutes", "495");
  await expect(calendarDay(page, "2026-11-03")).toHaveAttribute("data-optional-minutes", "225");
  await expect(calendarDay(page, "2026-11-08")).toHaveAttribute("data-base-minutes", "0"); // Sunday
  // line 2: Mon 06:00-24:00 = 1,020; Tue includes Monday night's tail 00:00-06:00 - meal = 330 + 1,020; Sun = Sat night tail
  await page.getByTestId("calendar-line").selectOption(l2.id);
  await expect(page.getByTestId("line-calendar")).toHaveAttribute("data-line-id", l2.id);
  await expect(calendarDay(page, "2026-11-02")).toHaveAttribute("data-base-minutes", "1020");
  await expect(calendarDay(page, "2026-11-03")).toHaveAttribute("data-base-minutes", "1350");
  await expect(calendarDay(page, "2026-11-08")).toHaveAttribute("data-base-minutes", "330");

  // --- plant holiday on Tue 3 Nov: removes Tuesday on both lines, incl. Monday night's tail; Wed keeps Tue night's tail
  await page.getByTestId("exception-new").click();
  const form = page.getByTestId("exception-form");
  await form.getByTestId("exception-kind").selectOption("holiday");
  await form.getByTestId("exception-scope").selectOption("plant");
  await form.getByTestId("exception-label").fill("E2E holiday");
  await form.getByTestId("exception-from").fill("2026-11-03");
  await form.getByTestId("exception-to").fill("2026-11-03");
  await page.getByTestId("exception-save").click();
  await expect(page.locator('[data-testid="exception-row"]', { hasText: "E2E holiday" })).toBeVisible();
  await expect(calendarDay(page, "2026-11-03")).toHaveAttribute("data-base-minutes", "0");
  await expect(calendarDay(page, "2026-11-04")).toHaveAttribute("data-base-minutes", "1350");
  await expect(calendarDay(page, "2026-11-02")).toHaveAttribute("data-base-minutes", "1020");
  await page.getByTestId("calendar-line").selectOption(l1.id);
  await expect(calendarDay(page, "2026-11-03")).toHaveAttribute("data-base-minutes", "0");
  await expect(calendarDay(page, "2026-11-03")).toHaveAttribute("data-optional-minutes", "0");
  await expect(calendarDay(page, "2026-11-04")).toHaveAttribute("data-base-minutes", "495");
  const ex = await mfgJson<{ items: { label: string; start: string; end: string; scope: string }[] }>(request, "/calendar-exceptions");
  const hol = ex.items.find((x) => x.label === "E2E holiday");
  expect(hol).toMatchObject({ scope: "plant", start: "2026-11-03T00:00:00+05:30", end: "2026-11-04T00:00:00+05:30" });
  // the API agrees: no window of line 1 starts on 3 Nov
  const w2 = await mfgJson<{ windows: { start: string }[] }>(request, `/lines/${l1.id}/windows?from=2026-11-03&to=2026-11-04`);
  expect(w2.windows).toEqual([]);
  expectClean(problems);
});

test("stage and line selection from ?group= / ?line= and line edits (speed, eligibility, active)", async ({ page, request }) => {
  await loadSample(request, "small");
  const fct = await findByCode(request, "/groups", "FCT");
  const line = await findByCode(request, "/lines", "FCT-1");
  const problems = watch(page);
  await gotoMfg(page, `/plant/groups?group=${fct.id}`);
  await expect(page.locator(`[data-testid="group-row"][data-group-id="${fct.id}"]`)).toHaveClass(/mfg-selected/);
  await expect(page.getByTestId("group-panel")).toHaveAttribute("data-group-id", fct.id);
  await gotoMfg(page, `/plant/groups?line=${line.id}`);
  await expect(page.locator(`[data-testid="line-row"][data-line-id="${line.id}"]`)).toHaveClass(/mfg-selected/);
  await expect(page.getByTestId("line-panel")).toHaveAttribute("data-line-id", line.id);
  const form = page.getByTestId("line-form");
  await expect(form).toBeVisible();
  await form.getByTestId("line-speed").fill("0.8");
  await form.getByTestId("line-families").fill("PCBA-STD, HARNESS");
  await page.getByTestId("line-save").click();
  await expect.poll(async () => (await mfgJson<{ speed_factor: number }>(request, `/lines/${line.id}`)).speed_factor).toBe(0.8);
  const rec = await mfgJson<{ eligible_families: string[] }>(request, `/lines/${line.id}`);
  expect([...rec.eligible_families].sort()).toEqual(["HARNESS", "PCBA-STD"]);
  expectClean(problems);
});

test("after Assign / Save the shift-assignment dialog closes and highlights the row; a ?assignment= deep link still opens the editor", async ({ page, request }) => {
  await loadSample(request, "small");
  const reg = await findByCode(request, "/shift-templates", "REG");
  const aoi = await findByCode(request, "/groups", "AOI");
  await gotoMfg(page, "/plant/shifts");
  await page.getByTestId("assignment-new").click();
  const form = page.getByTestId("assignment-form");
  await form.getByTestId("assignment-template").selectOption(reg.id);
  await form.getByTestId("assignment-target-type").selectOption("group");
  await form.getByTestId("assignment-group").selectOption(aoi.id);
  await form.getByTestId("assignment-kind").selectOption("optional");
  await form.getByTestId("assignment-from").fill("2027-02-01");
  await form.getByTestId("assignment-cost").fill("100");
  const created = page.waitForResponse((r) => r.url().endsWith("/mfg/shift-assignments") && r.request().method() === "POST");
  await page.getByTestId("assignment-form-submit").click();
  const rec = (await (await created).json()) as { id: string };
  const row = page.locator(`[data-testid="assignment-row"][data-assignment-id="${rec.id}"]`);
  await expect(row).toContainText(/optional/i);
  await expect(row).toHaveClass(/mfg-selected/);
  await expect(page).toHaveURL(new RegExp(`assignment=${rec.id}`));
  await page.waitForTimeout(500);
  await expect(page.getByRole("dialog")).toHaveCount(0, { timeout: 2_000 });

  // editing and saving also closes the dialog and keeps the row highlighted
  await row.getByTestId("assignment-edit").click();
  const edit = page.getByRole("dialog", { name: "Edit shift assignment" });
  await expect(edit).toBeVisible();
  await edit.getByTestId("assignment-cost").fill("150");
  const saved = page.waitForResponse((r) => r.url().endsWith(`/mfg/shift-assignments/${rec.id}`) && r.request().method() === "PUT");
  await page.getByTestId("assignment-form-submit").click();
  expect((await saved).status()).toBe(200);
  await expect(row).toContainText("150");
  await expect(row).toHaveClass(/mfg-selected/);
  await page.waitForTimeout(500);
  await expect(page.getByRole("dialog")).toHaveCount(0, { timeout: 2_000 });

  // a deep link (as built by the health page's Fix link) opens the editor of that assignment
  await gotoMfg(page, `/plant/shifts?assignment=${rec.id}`);
  await expect(page.getByRole("dialog", { name: "Edit shift assignment" })).toBeVisible();
  await expect(page.getByTestId("assignment-cost")).toHaveValue("150");
});

test("new shift template: the week preview works before Code and Name are filled in", async ({ page, request }) => {
  await loadSample(request, "small");
  const problems = watch(page);
  await gotoMfg(page, "/plant/shifts");
  const previews: { code: unknown; name: unknown }[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/mfg/shift-templates/preview") && r.method() === "POST") previews.push(r.postDataJSON() as { code: unknown; name: unknown });
  });
  await page.getByTestId("template-new").click();
  await page.getByTestId("template-pattern").selectOption("two");
  await expect(page.getByTestId("week-segment").first()).toBeVisible({ timeout: 5_000 });
  await expect(page.getByTestId("shift-week-preview")).toHaveAttribute("data-loading", "false");
  await expect(page.getByText("These shifts do not fit together")).toHaveCount(0);
  expect(previews.length).toBeGreaterThan(0);
  for (const b of previews) expect(b.code && b.name, "preview carries placeholder code / name").toBeTruthy();
  // a code with a character the server refuses does not break the preview either (it is never sent)
  await page.getByTestId("template-code").fill("bad code!");
  await page.getByTestId("shift-def").first().getByTestId("shift-end").fill("13:30");
  await expect(page.getByTestId("shift-week-preview")).toHaveAttribute("data-loading", "false");
  await expect(page.getByText("These shifts do not fit together")).toHaveCount(0);
  expectClean(problems);
});
