import { test, expect } from "@playwright/test";
import { acceptDisclaimer, apiPost, finJson, planWithResult, uniqueName, waitRun } from "./finance-helpers";

// QA re-checks of the review defects that had no e2e coverage (what-if slider range, Re-run after a failed save).

const roundTo = (v: number, step: number) => Math.round(v / step) * step;

for (const tid of ["young_professional", "family", "near_retirement"]) {
  test(`what-if savings slider range follows the first-year average surplus (${tid})`, async ({ page, request }) => {
    const { planId, resultId } = await planWithResult(request, tid, uniqueName(`slider ${tid}`));
    const res = (await finJson(request, `/results/${resultId}`)).result;
    const first: number[] = res.cashflow.surplus.slice(0, 12);
    const avg = first.reduce((a, b) => a + b, 0) / first.length;
    const base = Math.max(10000, avg);
    await page.goto(`/finance/${planId}/what-if`);
    await acceptDisclaimer(page);
    const slider = page.getByTestId("whatif-savings");
    await expect(slider).toBeVisible();
    expect(Number(await slider.getAttribute("max"))).toBe(Math.max(1000, roundTo(base, 1000)));
    expect(Number(await slider.getAttribute("min"))).toBe(Math.min(-1000, roundTo(-0.5 * base, 1000)));
    expect(await slider.getAttribute("step")).toBe("1000");
    if (avg > 20000) expect(Number(await slider.getAttribute("max"))).toBeGreaterThan(10000);
  });
}

test("what-if savings slider keeps step 1000 for an off-grid 'Try this' amount and snaps on the first move", async ({ page, request }) => {
  const { planId, resultId } = await planWithResult(request, "young_professional", uniqueName("slider offgrid"));
  const created = await apiPost(
    request,
    `/plans/${planId}/what-if`,
    { changes: { extra_monthly_savings: 2345 }, replace_active: true, base_result_id: resultId },
    202,
  );
  await waitRun(request, created.run_id);
  await page.goto(`/finance/${planId}/what-if?base=${resultId}&run=${created.run_id}`);
  await acceptDisclaimer(page);
  const slider = page.getByTestId("whatif-savings");
  await expect(slider).toHaveAttribute("aria-valuenow", "2345");
  await expect(slider).toHaveAttribute("aria-valuetext", /2,?345/);
  expect(await slider.getAttribute("step")).toBe("1000");
  expect(Number(await slider.getAttribute("min")) % 1000 === 0).toBe(true);
  expect(Number(await slider.getAttribute("max")) % 1000 === 0).toBe(true);
  await slider.focus();
  await page.keyboard.press("ArrowRight");
  await expect(slider).toHaveAttribute("aria-valuenow", "3000");
  await page.keyboard.press("ArrowRight");
  await expect(slider).toHaveAttribute("aria-valuenow", "4000");
  await page.keyboard.press("ArrowLeft");
  await expect(slider).toHaveAttribute("aria-valuenow", "3000");
  await expect(slider).toHaveValue("3000");
});

test("Results 'Re-run' does not start a run when the pending save fails", async ({ page, request }) => {
  const { planId } = await planWithResult(request, "young_professional", uniqueName("rerun save"));
  await page.route(`**/api/v1/finance/plans/${planId}`, (route) =>
    route.request().method() === "PUT"
      ? route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "INTERNAL", message: "boom" } }) })
      : route.continue(),
  );
  await page.goto(`/finance/${planId}/setup/profile`);
  await acceptDisclaimer(page);
  const name = page.getByLabel("Plan name");
  await name.fill("Changed name that cannot be saved");
  await expect(page.getByTestId("fin-save-state")).toHaveAttribute("data-state", "error", { timeout: 20_000 });
  await page.getByRole("link", { name: "Results" }).click();
  await page.waitForURL(/\/results/);
  const before = (await finJson(request, `/plans/${planId}/runs`)).items.length;
  await page.getByTestId("fin-rerun").click();
  await expect(page.getByText(/could not be saved, so the plan was not re-run/)).toBeVisible();
  await page.waitForTimeout(1500);
  const after = (await finJson(request, `/plans/${planId}/runs`)).items.length;
  expect(after).toBe(before);
  expect(new URL(page.url()).searchParams.get("run")).toBeNull();
});
