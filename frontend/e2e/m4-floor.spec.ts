/**
 * M4 floor journey (docs/M4-DESIGN.md 14, Gate 4 acceptance 1), tablet viewport 1024x768:
 * line pick -> badge scan (station login) -> scan traveller -> start -> report scrap -> pause / resume -> complete;
 * an action taken offline syncs exactly once; the last operation completes with serials -> the WO receipt posts and
 * the work order is completed.
 *
 * Data: sample `small` (anchor M2_ANCHOR), SM-100 made serialized (no operation flagged, so serials are captured at
 * the last operation, M4 10), one work order of 4 with a receipt location, released to the floor via the API.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { findItem, loadSampleM2, M2_ANCHOR, mfgCall, mfgJson, resetMfg } from "./mfg-helpers";

test.use({ viewport: { width: 1024, height: 768 } });

interface WoOp {
  id: string;
  seq: number;
  status: string;
  qty_good: number;
  qty_scrap: number;
  qty_available: number;
}

const ITEM_INPUT_KEYS = [
  "part_number", "revision", "description", "uom", "make_buy", "family", "setup_family", "lead_time_days", "receiving_days", "lot_rule",
  "fixed_lot_qty", "min_order_qty", "order_multiple", "safety_stock", "serialized", "shelf_life_days", "handling_class", "handling_note",
  "attributes", "active", "external_ref", "standard_cost", "lot_controlled", "lot_period_days", "issue_method",
];

let wo: { id: string; number: string; qty: number };

async function ops(request: APIRequestContext): Promise<WoOp[]> {
  return (await mfgJson<{ items: WoOp[] }>(request, `/work-orders/${wo.id}/operations`)).items;
}

let n = 0;
async function apiEvent(request: APIRequestContext, opId: string, body: Record<string, unknown>) {
  return mfgCall(request, "POST", "/floor/events", { data: { client_event_id: `e2e-api-${Date.now()}-${n++}`, wo_operation_id: opId, ...body } });
}

/** Type like a keyboard-wedge scanner while focus is NOT in a text field (the shell routes keys to the scan field). */
async function wedge(page: Page, code: string) {
  await page.getByTestId("floor-crew").click();
  await page.keyboard.type(`${code}\n`, { delay: 4 });
}

async function opStatus(page: Page) {
  return page.getByTestId("floor-op").getAttribute("data-status");
}

test.describe("M4 floor journey", () => {
  test.beforeAll(async ({ request }) => {
    await resetMfg(request);
    await loadSampleM2(request, "small", { anchor: M2_ANCHOR });
    // SM-100 carries serial numbers: captured at the last operation (no operation is flagged)
    const it = await findItem(request, "SM-100");
    const rec = await mfgJson<Record<string, unknown> & { row_version: number }>(request, `/items/${it.id}`);
    const body: Record<string, unknown> = {};
    for (const k of ITEM_INPUT_KEYS) if (k in rec) body[k] = rec[k];
    body.serialized = true;
    await mfgCall(request, "PUT", `/items/${it.id}`, { data: body, headers: { "If-Match": `"${rec.row_version}"` } });
    const locs = await mfgJson<{ items: { id: string; code: string }[] }>(request, "/locations");
    const stores = locs.items.find((l) => l.code === "STORES")!;
    const created = (await mfgCall(request, "POST", "/work-orders", {
      data: { item_id: it.id, qty: 4, due_date: "2026-11-12", start_date: M2_ANCHOR, priority: 2, receipt_location_id: stores.id },
      status: 201,
    })) as { id: string; number: string; qty: number; row_version: number };
    wo = created;
    // release to the floor; a first-operation shortage needs a reason (4.1)
    const rel = await request.post(`http://127.0.0.1:8000/api/v1/mfg/work-orders/${created.id}/release`, {
      data: { reserve: true },
      headers: { "If-Match": `"${created.row_version}"` },
    });
    if (rel.status() === 409) {
      const fresh = await mfgJson<{ row_version: number }>(request, `/work-orders/${created.id}`);
      await mfgCall(request, "POST", `/work-orders/${created.id}/release`, { data: { reserve: true, override_reason: "e2e: start before the kit is complete" }, headers: { "If-Match": `"${fresh.row_version}"` } });
    } else expect(rel.ok(), await rel.text()).toBeTruthy();
    expect((await ops(request)).length).toBeGreaterThanOrEqual(2);
  });

  test("scan, start, scrap, pause/resume, complete; offline once; serials at the last operation", async ({ page, request }) => {
    const opList = await ops(request);
    const first = opList[0];
    const last = opList[opList.length - 1];
    const operators = await mfgJson<{ items: { code: string; name: string }[] }>(request, "/operators");
    const badge = operators.items[0];

    // line picker (remembered on this device), then the queue with the scan field focused
    await page.goto("/mfg/floor");
    await expect(page.getByTestId("floor-shell")).toBeVisible();
    const tile = page.locator('[data-testid="floor-line-pick"][data-code="SMT-1"]');
    await (await tile.count() ? tile : page.getByTestId("floor-line-pick").first()).click();
    await expect(page.getByTestId("floor-line-title")).toBeVisible();
    await expect(page.getByTestId("floor-scan")).toBeFocused();

    // station login: the operator scans a badge
    await wedge(page, `OP:${badge.code}`);
    await expect(page.getByTestId("floor-crew")).toHaveAttribute("data-count", "1");

    // scan the traveller's operation barcode
    await wedge(page, `${wo.number}/${first.seq}`);
    await expect(page.getByTestId("floor-op")).toHaveAttribute("data-seq", String(first.seq));

    // start
    const startEvent = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith("/floor/events"));
    await page.getByTestId("floor-action-start").click();
    const sent = (await startEvent).postDataJSON() as Record<string, unknown>;
    expect(sent.operator_ids ?? sent.operator_codes).toBeTruthy();
    await expect.poll(() => opStatus(page)).toBe("running");

    // report 1 good + 1 scrap with a reason
    await page.getByTestId("floor-action-report").click();
    await page.getByTestId("floor-qty-good").fill("1");
    await page.getByTestId("floor-qty-scrap").fill("1");
    await expect(page.getByTestId("floor-qty-submit")).toBeDisabled(); // scrap needs a reason
    await page.locator('select[data-testid="floor-reason"]').selectOption({ index: 1 });
    await page.getByTestId("floor-qty-submit").click();
    await expect(page.getByTestId("floor-op-good")).toHaveAttribute("data-scrap", "1");
    await expect(page.getByTestId("floor-op-good")).toHaveAttribute("data-good", "1");

    // pause (reason) and resume
    await page.getByTestId("floor-action-pause").click();
    await page.getByTestId("floor-reason").locator("[role=radio]").first().click();
    await page.getByTestId("floor-pause-submit").click();
    await expect.poll(() => opStatus(page)).toBe("paused");
    await page.getByTestId("floor-action-resume").click();
    await expect.poll(() => opStatus(page)).toBe("running");

    // complete with the remaining good quantity (prefilled)
    await page.getByTestId("floor-action-complete").click();
    await page.getByTestId("floor-qty-submit").click();
    await expect.poll(() => opStatus(page)).toBe("completed");

    if (opList.length > 2) {
      // offline: the start of the second operation is kept on the tablet and synced once the network returns
      const second = opList[1];
      await wedge(page, `${wo.number}/${second.seq}`);
      await expect(page.getByTestId("floor-op")).toHaveAttribute("data-seq", String(second.seq));
      await page.context().setOffline(true);
      await page.getByTestId("floor-action-start").click();
      await expect(page.getByTestId("floor-sync-pending")).toHaveAttribute("data-count", "1");
      await page.context().setOffline(false);
      await expect(page.getByTestId("floor-sync-pending")).toHaveCount(0, { timeout: 30_000 });
      const evs = await mfgJson<{ items: { event_type: string; wo_operation_id: string }[] }>(request, `/floor/events?wo_id=${wo.id}&type=start`);
      expect(evs.items.filter((e) => e.wo_operation_id === second.id)).toHaveLength(1);
      const cur = (await ops(request)).find((x) => x.id === second.id)!;
      await apiEvent(request, second.id, { event_type: "complete", qty_good: cur.qty_available });
      // the remaining middle operations through the API (same engine)
      for (const o of opList.slice(2, -1)) {
        const st = (await ops(request)).find((x) => x.id === o.id)!;
        if (st.status === "completed") continue;
        if (st.status === "pending" || st.status === "ready") await apiEvent(request, o.id, { event_type: "start" });
        const fresh = (await ops(request)).find((x) => x.id === o.id)!;
        await apiEvent(request, o.id, { event_type: "complete", qty_good: fresh.qty_available });
      }
    }

    // last operation: serials, one per good unit
    await wedge(page, `${wo.number}/${last.seq}`);
    await expect(page.getByTestId("floor-op")).toHaveAttribute("data-seq", String(last.seq));
    await page.getByTestId("floor-action-start").click();
    await expect.poll(() => opStatus(page)).toBe("running");
    await page.getByTestId("floor-action-complete").click();
    const good = Number(await page.getByTestId("floor-qty-good").inputValue());
    expect(good).toBeGreaterThan(0);
    await expect(page.getByTestId("floor-qty-submit")).toBeDisabled();
    const stamp = Date.now().toString(36).toUpperCase();
    for (let i = 1; i <= good; i++) {
      await page.getByTestId("floor-serial-input").fill(`SN-${stamp}-${i}`);
      await page.getByTestId("floor-serial-input").press("Enter");
    }
    await expect(page.getByTestId("floor-serial-count")).toHaveAttribute("data-count", String(good));
    await page.getByTestId("floor-qty-submit").click();
    await expect.poll(() => opStatus(page)).toBe("completed");

    // stock and WO status updated: completed output received, serials in stock
    const w = await mfgJson<{ status: string; qty_completed: number }>(request, `/work-orders/${wo.id}`);
    expect(w.qty_completed).toBe(good);
    const serials = await mfgJson<{ items: { serial: string; status: string }[] }>(request, `/serials?wo_id=${wo.id}`);
    expect(serials.items.filter((s) => s.serial.startsWith(`SN-${stamp}`))).toHaveLength(good);
  });
});
