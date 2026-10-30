/**
 * WP-C M2 navigation and route contract (M2-DESIGN 14.1, 14.2): the two nav groups, every M2 route renders
 * without unexpected API errors or page errors on `small` with one MRP run, and the owner sees Members.
 */
import { test, expect } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { findItem, gotoMfg, loadSampleM2, mfgCall, mfgJson, resetMfg, runMrpApi } from "./mfg-helpers";

test("two navigation groups and every M2 screen renders cleanly", async ({ page, request }) => {
  test.setTimeout(240_000);
  await resetMfg(request);
  await loadSampleM2(request, "small");
  const mcu = await findItem(request, "SM-MCU-01");
  const top = await findItem(request, "SM-100");
  const sups = await mfgJson<{ items: { id: string }[] }>(request, "/suppliers");
  if (!sups.items.length) sups.items.push((await mfgCall(request, "POST", "/suppliers", { status: 201, data: { code: "SUP-NAV", name: "Supplier nav (fictional)" } })) as { id: string });
  // own documents (independent of the sample's transactional sheets)
  const day = (o: number) => new Date(Date.now() + o * 86400000).toISOString().slice(0, 10);
  const po = (await mfgCall(request, "POST", "/purchase-orders", {
    status: 201,
    data: { number: "PO-NAV-1", supplier_id: sups.items[0].id, lines: [{ item_id: mcu.id, schedules: [{ requested_date: day(10), qty: 40 }, { requested_date: day(40), qty: 40 }] }] },
  })) as { id: string };
  const dmo = (await mfgCall(request, "POST", "/demand-orders", {
    status: 201,
    data: { number: "DO-NAV-1", demand_type: "customer", lines: [{ item_id: top.id, qty: 10, due_date: day(30) }] },
  })) as { id: string; row_version: number };
  await mfgCall(request, "POST", `/demand-orders/${dmo.id}/open`, { data: {}, headers: { "If-Match": `"${dmo.row_version}"` } });
  const run = await runMrpApi(request, { label: "nav" });
  // members are 422 MBR_UNAVAILABLE in single_user mode (shown as a note, not an error)
  const problems = watch(page, [/GET \/mfg\/members -> 422 .*MBR_UNAVAILABLE/, /status of 422/]);

  await gotoMfg(page);
  await expect(page.getByTestId("nav-group-planning")).toBeVisible();
  for (const k of ["demand", "mrp", "shortages", "work-orders", "purchasing", "inventory"]) await expect(page.getByTestId(`mfg-subnav-${k}`)).toBeVisible();

  const routes = [
    "/inventory",
    "/inventory/transactions",
    "/inventory/post",
    "/inventory/lots",
    "/inventory/locations",
    `/items/${mcu.id}/stock`,
    `/items/${mcu.id}/suppliers`,
    "/purchasing/orders",
    `/purchasing/orders/${po.id}`,
    "/purchasing/requests",
    "/purchasing/requests/new",
    "/purchasing/schedule",
    "/purchasing/suppliers",
    `/purchasing/suppliers/${sups.items[0].id}`,
    "/demand",
    `/demand/${dmo.id}`,
    "/work-orders",
    "/work-orders/new",
    "/work-orders/kitting",
    "/mrp",
    `/mrp/runs/${run.id}`,
    `/mrp/runs/${run.id}/items`,
    `/mrp/runs/${run.id}/items/${mcu.id}`,
    `/mrp/runs/${run.id}/planned`,
    `/mrp/runs/${run.id}/exceptions`,
    `/mrp/runs/${run.id}/demand`,
    `/mrp/runs/${run.id}/compare`,
    "/shortages",
    "/settings/members",
    "/plant/settings",
  ];
  for (const r of routes) {
    await gotoMfg(page, r);
    await expect(page.getByTestId("mfg-not-found"), r).toHaveCount(0);
    await page.waitForLoadState("networkidle");
  }
  // the MRP fields of the plant settings (3.1)
  await gotoMfg(page, "/plant/settings");
  await expect(page.getByTestId("plant-mrp")).toBeVisible();
  expectClean(problems);
});
