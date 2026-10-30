/**
 * M3 WP-U (docs/M3-DESIGN.md 12, 14): the schedule UI end to end against the API.
 *
 * Data: sample `small` (anchor M2_ANCHOR) plus a rush demand line due tomorrow (so the run has late demand and the
 * "Re-run with automatic overtime (Allow)" escalation is offered) and an optional evening shift on every stage (so
 * overtime can be suggested/opened where it helps). Assertions are on behaviour, not on engine numbers.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { findItem, gotoMfg, loadSampleM2, M2_ANCHOR, mfgCall, mfgJson, resetMfg, runMrpApi } from "./mfg-helpers";

const runIdOf = (url: string) => /\/schedule\/runs\/([^/?#]+)/.exec(url)?.[1] ?? null;
const isoDay = (n: number) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);

interface OpLite {
  op_no: number;
  start: string;
  line_id: string;
  order: { type: string; id: string; number: string };
  frozen: boolean;
}

async function createRun(page: Page, label: string): Promise<string> {
  await gotoMfg(page, "/schedule");
  await page.getByTestId("aps-new-run").click();
  await expect(page.getByTestId("aps-run-form")).toBeVisible();
  // guided default: overtime "suggest"; expert settings stay hidden until asked for
  await expect(page.getByTestId("aps-policy-suggest")).toBeChecked();
  await expect(page.getByTestId("aps-expert")).toHaveCount(0);
  await page.getByTestId("aps-label").fill(label);
  await page.getByTestId("aps-run-submit").click();
  await expect(page).toHaveURL(/\/mfg\/schedule\/runs\/[^/]+/);
  await expect(page.getByTestId("aps-summary")).toBeVisible({ timeout: 90_000 });
  return runIdOf(page.url())!;
}

/** Plant-local calendar day of an instant (dispatch and Gantt dates are plant days). */
async function plantDay(request: APIRequestContext, iso: string): Promise<string> {
  const plant = await mfgJson<{ time_zone?: string | null; utc_offset_minutes?: number | null }>(request, "/plant");
  if (plant.time_zone) return new Intl.DateTimeFormat("en-CA", { timeZone: plant.time_zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
  return new Date(Date.parse(iso) + (plant.utc_offset_minutes ?? 0) * 60000).toISOString().slice(0, 10);
}

async function firstOps(request: APIRequestContext, runId: string): Promise<OpLite[]> {
  return (await mfgJson<{ items: OpLite[] }>(request, `/aps/runs/${runId}/operations?status=scheduled&sort=start&limit=20`)).items;
}

test.describe("M3 schedule UI", () => {
  test.beforeAll(async ({ request }) => {
    await resetMfg(request);
    await loadSampleM2(request, "small", { anchor: M2_ANCHOR });
    const it = await findItem(request, "SM-100");
    const d = (await mfgCall(request, "POST", "/demand-orders", {
      data: { number: "DO-RUSH", demand_type: "customer", customer: "Rush customer (fictional)", priority: 1, lines: [{ line_no: 10, item_id: it.id, qty: 25, due_date: isoDay(1) }] },
      status: 201,
    })) as { id: string; row_version: number };
    await mfgCall(request, "POST", `/demand-orders/${d.id}/open`, { data: {}, headers: { "If-Match": `"${d.row_version}"` } });
    const tpl = (await mfgCall(request, "POST", "/shift-templates", {
      data: { code: "OT-EVE", name: "Evening overtime", shifts: [{ name: "Evening", days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], start: "18:00", end: "23:00" }] },
      status: 201,
    })) as { id: string };
    const groups = await mfgJson<{ items: { id: string }[] }>(request, "/groups");
    for (const g of groups.items)
      await mfgCall(request, "POST", "/shift-assignments", {
        data: { shift_template_id: tpl.id, target_type: "group", group_id: g.id, kind: "optional", effective_from: isoDay(-7), cost_per_hour: 400, max_hours_per_week: 30 },
        status: 201,
      });
    // the schedule reads the planned orders and pegging of the latest completed MRP run
    await runMrpApi(request, { label: "e2e m3" });
  });

  test("run, Gantt by line, drag creates a validated child run or shows violations", async ({ page, request }) => {
    const runId = await createRun(page, "e2e weekly");
    await expect(page.getByTestId("aps-kpi-late")).toBeVisible();

    // default window from the run's start; if empty, the tab offers a jump to the first scheduled operation
    await page.getByTestId("aps-tab-gantt").click();
    await expect(page.getByTestId("gantt-canvas")).toBeVisible();
    const canvas = page.getByTestId("gantt-canvas");
    if ((await canvas.getAttribute("data-bars")) === "0") {
      await page.getByTestId("gantt-jump-first").click();
      await expect.poll(async () => Number(await canvas.getAttribute("data-bars"))).toBeGreaterThan(0);
    }

    // deep link to a movable operation, zoomed in so its bar is wide enough to grab
    const op = (await firstOps(request, runId)).find((o) => !o.frozen)!;
    const lines = await mfgJson<{ items: { id: string; code: string }[] }>(request, "/lines");
    const lineCode = lines.items.find((l) => l.id === op.line_id)!.code;
    await page.goto(`/mfg/schedule/runs/${runId}/gantt?from=${await plantDay(request, op.start)}&op=${op.op_no}`);
    await expect(page.getByTestId("gantt-op-panel")).toBeVisible();
    for (let i = 0; i < 3; i++) await page.getByTestId("gantt-zoom-in").click();
    await page.getByTestId("prod-gantt").evaluate((el) => el.scrollIntoView({ block: "start" }));

    const row = page.locator(`[data-testid="gantt-row"][data-row-kind="line"][data-label="${lineCode}"]`);
    const rb = (await row.boundingBox())!;
    const box = (await canvas.boundingBox())!;
    const y = rb.y + rb.height / 2;
    let x0: number | null = null;
    for (let x = box.x + 2; x < box.x + box.width - 2 && x0 === null; x += 4) {
      await page.mouse.move(x, y);
      const tip = page.getByTestId("gantt-tooltip");
      if ((await tip.count()) && (await tip.innerText()).includes(op.order.number)) x0 = x + 8;
    }
    expect(x0, "bar of the selected operation under the pointer").not.toBeNull();
    // the tooltip explains why it starts there (server reason, loaded on hover)
    await expect(page.getByTestId("gantt-tooltip")).not.toContainText("loading", { timeout: 10_000 });

    const others = page.locator('[data-testid="gantt-row"][data-row-kind="line"]');
    const n = await others.count();
    let ty = y + 2;
    for (let i = 0; i < n; i++) {
      if ((await others.nth(i).getAttribute("data-label")) === lineCode) continue;
      const ob = (await others.nth(i).boundingBox())!;
      ty = ob.y + ob.height / 2;
      break;
    }
    await page.mouse.move(x0!, y);
    await page.mouse.down();
    await page.mouse.move(x0! + 20, (y + ty) / 2, { steps: 5 });
    await page.mouse.move(x0! + 50, ty, { steps: 5 });
    await page.mouse.up();

    // preview first; nothing is posted until Apply
    await expect(page.getByTestId("gantt-drop-preview")).toBeVisible();
    const posted = page.waitForRequest((r) => r.method() === "POST" && /\/edits$/.test(new URL(r.url()).pathname));
    await page.getByTestId("gantt-drop-apply").click();
    const body = (await posted).postDataJSON() as { edits: { kind: string; op_no: number }[] };
    expect(body.edits[0].op_no).toBe(op.op_no);
    // either a validated child run opens, or the 422 violations are listed inline
    await expect
      .poll(async () => (runIdOf(page.url()) !== runId ? "child" : (await page.getByTestId("edit-violations").count()) ? "violations" : "pending"), { timeout: 60_000 })
      .not.toBe("pending");
    if (runIdOf(page.url()) !== runId) await expect(page.getByTestId("gantt-canvas")).toBeVisible({ timeout: 90_000 });
  });

  test("late demand offers the Allow re-run; compare shows the trade-off; publish from there", async ({ page }) => {
    const runId = await createRun(page, "e2e suggest");
    const action = page.getByTestId("aps-rerun-allow");
    await expect(action).toBeVisible();
    const posted = page.waitForRequest((r) => r.method() === "POST" && /\/aps\/runs$/.test(new URL(r.url()).pathname));
    await action.click();
    const body = (await posted).postDataJSON() as Record<string, unknown>;
    expect(body.copy_of).toBe(runId);
    expect(body.overtime).toBe("allow");

    await expect(page).toHaveURL(new RegExp(`/compare\\?with=${runId}`));
    const trade = page.getByTestId("aps-tradeoff");
    await expect(trade).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId("aps-tradeoff-late")).toContainText(/\d/);
    await expect(page.getByTestId("aps-tradeoff-overtime")).toContainText(/\d(\.\d)? h/);
    await expect(trade.getByTestId("aps-compare-run")).toHaveCount(2);
    await expect(trade.locator('[data-testid="aps-compare-run"][data-policy="allow"]')).toHaveCount(1);
    await expect(page.getByTestId("aps-compare-kpis")).toBeVisible();

    // both runs can be published from here; publish the Allow run
    await expect(page.getByTestId("aps-publish-base")).toBeEnabled();
    await page.getByTestId("aps-publish-allow").click();
    await page.getByRole("dialog").getByRole("button", { name: "Publish" }).click();
    await expect(trade.locator('[data-policy="allow"]').getByTestId("aps-published-badge")).toBeVisible();
  });

  test("overtime tab; dispatch list per line and day", async ({ page, request }) => {
    const runId = await createRun(page, "e2e dispatch");

    await page.getByTestId("aps-tab-overtime").click();
    const sug = page.getByTestId("overtime-suggested");
    await expect(sug).toBeVisible();
    const rows = sug.getByTestId("overtime-row");
    if (await rows.count()) {
      // each suggested shift states the lateness it saves (text, not colour); accept -> prefilled what-if run
      await expect(rows.first()).toContainText(/weighted/);
      await expect(page.getByTestId("overtime-rerun-accepted")).toBeDisabled();
      await rows.first().getByTestId("overtime-accept").check();
      await page.getByTestId("overtime-rerun-accepted").click();
      await expect(page).toHaveURL(/\/mfg\/schedule$/);
      await expect(page.getByTestId("aps-override-row")).toHaveCount(1);
    } else {
      await expect(sug).toContainText("No extra shift would reduce lateness");
    }

    const op = (await firstOps(request, runId))[0];
    await page.goto(`/mfg/schedule/runs/${runId}/dispatch?line=${op.line_id}&date=${await plantDay(request, op.start)}`);
    await expect(page.getByTestId("dispatch-table")).toBeVisible();
    const row = page.locator(`[data-testid="dispatch-row"][data-op="${op.op_no}"]`);
    await expect(row).toBeVisible();
    await expect(row).toContainText(op.order.number);
    await expect(page.getByTestId("dispatch-print")).toBeEnabled();
    await expect(row.getByTestId("dispatch-material")).toHaveText(/\w/);
  });
});
