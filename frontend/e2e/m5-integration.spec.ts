/**
 * M5 WP-U (docs/M5-DESIGN.md 4-7, 13): the integration console, ERP-owned fields, inbound batches with per-record
 * results and code mappings, the webhook address guard, stock reconciliation from an uploaded ERP list; trace (tree,
 * graph, exact vs possible), where-used -> recall, ECO with impact, transfers and the audit trail.
 * Trace, recall, ECO and transfer routes answer from the real plant data (the S0 fixture ids are gone): the trace
 * test makes its own lot (an unused sample item becomes lot-controlled and is received with a lot code) and its own
 * change request. Transfers need a second plant of an organisation, which single-user mode does not have, so that
 * step checks the list and its empty state.
 */
import { expect, test, type APIRequestContext } from "@playwright/test";
import { findItem, gotoMfg, loadSampleM2, M2_ANCHOR, mfgCall, mfgJson, resetMfg } from "./mfg-helpers";

const V1 = "http://127.0.0.1:8000/api/v1";
const ITEM_INPUT_KEYS = [
  "part_number", "revision", "description", "uom", "make_buy", "family", "setup_family", "lead_time_days", "receiving_days", "lot_rule",
  "fixed_lot_qty", "min_order_qty", "order_multiple", "safety_stock", "serialized", "shelf_life_days", "handling_class", "handling_note",
  "attributes", "active", "external_ref", "standard_cost", "lot_controlled", "lot_period_days", "issue_method",
];

async function itemBody(request: APIRequestContext, id: string, patch: Record<string, unknown>) {
  const rec = await mfgJson<Record<string, unknown> & { row_version: number }>(request, `/items/${id}`);
  const body: Record<string, unknown> = {};
  for (const k of ITEM_INPUT_KEYS) if (k in rec) body[k] = rec[k];
  return { body: { ...body, ...patch }, version: rec.row_version };
}

async function postBatch(request: APIRequestContext, key: string, records: Record<string, unknown>[]) {
  const r = await request.post(`${V1}/integration/batches`, { data: { schema: "superplanner.v1", entity: "item", mode: "upsert", records }, headers: { "Idempotency-Key": key } });
  expect(r.status(), await r.text()).toBeLessThan(300);
  return (await r.json()) as { id: string; results: { ref: string; status: string; errors: { code: string }[] }[] };
}

test.describe("M5 integration and traceability", () => {
  test.beforeAll(async ({ request }) => {
    await resetMfg(request);
    await loadSampleM2(request, "small", { anchor: M2_ANCHOR });
  });

  test("console: who owns what, ERP-owned item fields, data in with per-record results, code mappings, webhook guard, reconciliation", async ({ page, request }) => {
    // settings: connect, plant code, items owned by the ERP, goods receipts booked in the ERP
    await gotoMfg(page, "/integration/settings");
    await expect(page.getByTestId("int-settings")).toBeVisible();
    await page.getByTestId("int-enabled").check();
    await page.getByTestId("int-plant-code").fill("SM1");
    await page.getByTestId("sor-items").selectOption("erp");
    await page.getByTestId("gr-erp").check();
    await page.getByTestId("int-settings-save").click();
    await expect(page.getByText("Saved")).toBeVisible();
    const st = await (await request.get(`${V1}/integration/settings`)).json();
    expect(st.enabled).toBe(true);
    expect(st.sor.items).toBe("erp");
    expect(st.goods_receipts_owner).toBe("erp");

    // ERP-owned item fields: read-only with an indicator; the server refuses a local change (409 INT_ERP_OWNED)
    const it = await findItem(request, "SM-100");
    await page.goto(`/mfg/items/${it.id}`);
    await expect(page.getByTestId("erp-owned-banner")).toBeVisible();
    await expect(page.getByTestId("item-description")).toBeDisabled();
    await expect(page.getByTestId("erp-owned-description")).toBeVisible();
    const { body, version } = await itemBody(request, it.id, { description: "changed locally" });
    const put = await request.put(`http://127.0.0.1:8000/api/v1/mfg/items/${it.id}`, { data: body, headers: { "If-Match": `"${version}"` } });
    expect(put.status()).toBe(409);
    expect((await put.json()).error.code).toBe("INT_ERP_OWNED");

    // data in: one record with an unmapped unit is rejected on its own; the other is applied
    const b1 = await postBatch(request, `e2e-m5-${Date.now()}-1`, [
      { ref: "ERP-SM-100", part_number: "SM-100", revision: "A", description: "Sensor interface board (ERP)", uom: "EA", make_buy: "make", active: true },
      { ref: "ERP-NEW-1", part_number: "SM-ERP-NEW", revision: "A", description: "New from ERP", uom: "NOS", make_buy: "buy", active: true },
    ]);
    expect(b1.results.find((r) => r.ref === "ERP-NEW-1")?.status).toBe("rejected");
    await gotoMfg(page, "/integration/batches");
    await page.getByTestId("batch-row").first().getByRole("link").click();
    await expect(page.getByTestId("batch-page")).toBeVisible();
    await page.getByTestId("batch-filter-rejected").click();
    const rejected = page.locator('[data-testid="batch-record"][data-status="rejected"]');
    await expect(rejected).toHaveCount(1);
    await expect(rejected).toContainText("INT_UNMAPPED_VALUE");
    await expect(rejected.getByRole("link", { name: "Add a code mapping" })).toBeVisible();

    // code mapping NOS -> EA, then the same record is accepted
    await rejected.getByRole("link", { name: "Add a code mapping" }).click();
    await expect(page.getByTestId("int-value-maps")).toBeVisible();
    await page.getByTestId("value-map-add").click();
    const row = page.getByTestId("value-map-row").last();
    await row.getByLabel("ERP code").fill("NOS");
    await row.getByLabel("Code here").fill("EA");
    await page.getByTestId("value-map-save").click();
    await expect(page.getByText("Saved")).toBeVisible();
    const b2 = await postBatch(request, `e2e-m5-${Date.now()}-2`, [{ ref: "ERP-NEW-1", part_number: "SM-ERP-NEW", revision: "A", description: "New from ERP", uom: "NOS", make_buy: "buy", active: true }]);
    expect(b2.results[0].status).toBe("created");

    // webhooks: private addresses are refused with a clear message (SSRF guard)
    await gotoMfg(page, "/integration/endpoints");
    await page.getByTestId("endpoint-new").click();
    await page.getByTestId("endpoint-name").fill("Middleware");
    await page.getByTestId("endpoint-url").fill("https://127.0.0.1/hook");
    await page.getByTestId("endpoint-save").click();
    await expect(page.getByRole("dialog")).toContainText(/private|local|not allowed|secret/i);
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();

    // reconciliation: upload the ERP's stock list; differences are listed, nothing is posted
    const bal = await mfgJson<{ items: { item: { part_number: string }; location: { code: string }; qty_on_hand: number }[] }>(request, "/inventory/balances?limit=1");
    const b = bal.items[0];
    const csv = `item_ref,location_code,lot_code,qty\n${b.item.part_number},${b.location.code},,${b.qty_on_hand + 2}\n`;
    await gotoMfg(page, "/integration/reconciliation");
    await page.getByTestId("recon-file").setInputFiles({ name: "erp-stock.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
    await page.getByTestId("recon-start").click();
    await expect(page.getByTestId("recon-page")).toHaveAttribute("data-status", "completed");
    await expect(page.getByTestId("recon-kind-different")).toHaveAttribute("data-count", "1");
    await expect(page.locator('[data-testid="recon-row"][data-kind="different"]')).toContainText(b.item.part_number);

    // switch the items back so the other tests can edit
    const st2 = await (await request.get(`${V1}/integration/settings`)).json();
    await request.put(`${V1}/integration/settings`, { data: { ...st2, enabled: false, row_version: undefined, adapters: undefined }, headers: { "If-Match": `"${st2.row_version}"` } });
  });

  test("trace tree and graph, where-used to recall, ECO impact, transfers, audit trail", async ({ page, request }) => {
    // a traceable lot: the first sample item without stock history (the finished good) becomes lot-controlled, and a
    // work order for it receives its output into lot LOT-E2E-<stamp>, so the lot traces back to the work order
    const lotCode = `LOT-E2E-${Date.now()}`;
    const items = await mfgJson<{ items: { id: string; part_number: string }[] }>(request, "/items?limit=50");
    let itemId = "";
    for (const it of items.items) {
      const { body, version } = await itemBody(request, it.id, { lot_controlled: true });
      const r = await request.put(`${V1}/mfg/items/${it.id}`, { data: body, headers: { "If-Match": `"${version}"` } });
      if (r.ok()) {
        itemId = it.id;
        break;
      }
    }
    expect(itemId, "a sample item without stock history can become lot-controlled").not.toBe("");
    const locs = await mfgJson<{ items: { id: string; code: string; kind: string }[] }>(request, "/locations");
    const stores = locs.items.find((l) => l.kind === "stores") ?? locs.items[0];
    const today = new Date().toISOString().slice(0, 10);
    const wo = (await mfgCall(request, "POST", "/work-orders", {
      data: { item_id: itemId, qty: 4, due_date: today, start_date: today, priority: 2, receipt_location_id: stores.id },
      status: 201,
    })) as { id: string; row_version: number };
    await mfgCall(request, "POST", `/work-orders/${wo.id}/release`, { data: { reserve: false, override_reason: "e2e: trace lot" }, headers: { "If-Match": `"${wo.row_version}"` } });
    await mfgCall(request, "POST", "/inventory/postings", {
      data: { type: "wo_receipt", note: "e2e trace lot", lines: [{ wo_id: wo.id, location_id: stores.id, qty: 2, lot_code: lotCode }] },
      headers: { "Idempotency-Key": `e2e-${lotCode}` },
    });
    const lots = await mfgJson<{ items: { id: string; lot_code: string }[] }>(request, `/lots?q=${lotCode}`);
    const lot = lots.items.find((l) => l.lot_code === lotCode)!;
    expect(lot).toBeTruthy();

    // trace: the tree shows the lot with its exact/possible marking, both directions, the graph view draws
    await gotoMfg(page, `/trace?kind=lot&id=${lot.id}&dir=backward&label=${lotCode}`);
    await expect(page.getByTestId("trace-tree")).toBeVisible();
    await expect(page.locator('[data-testid="trace-node"]').first()).toBeVisible();
    await expect(page.locator('[data-testid="trace-node"][data-precision="exact"], [data-testid="trace-node"][data-precision="possible"]').first()).toBeVisible();
    await page.getByTestId("trace-forward").click();
    await expect(page).toHaveURL(/dir=forward/);
    await page.getByTestId("trace-view-graph").click();
    await expect(page.getByTestId("trace-graph").locator("svg")).toBeVisible();

    // a recall from that lot -> the report
    await page.goto(`/mfg/recalls?new=1&kind=lot&id=${lot.id}&label=${lotCode}`);
    await expect(page.getByTestId("recall-new")).toBeVisible();
    await page.getByTestId("recall-create").click();
    await expect(page.getByTestId("recall-page")).toBeVisible();
    await expect(page.getByTestId("recall-units")).toBeVisible();
    await expect(page.getByTestId("recall-quarantine")).toBeVisible();

    // ECO: list -> detail -> impact (the use-up suggestion shows when the server computes a date)
    const eco = (await mfgCall(request, "POST", "/eco", {
      data: { title: `E2E change ${lotCode}`, reason: "e2e", kind: "eco", priority: 3, effectivity: { mode: "date", date: null }, note: "" },
    })) as { id: string };
    // the change carries a draft copy of the item's released BOM (the impact needs at least one draft)
    const boms = await mfgJson<{ items: { id: string; status: string; row_version: number }[] }>(request, `/items/${itemId}/boms`);
    const released = boms.items.find((b) => b.status === "released") ?? boms.items[0];
    const draft = (await mfgCall(request, "POST", `/boms/${released.id}/copy`, { data: { revision: null }, headers: { "If-Match": `"${released.row_version}"` } })) as { id: string };
    await mfgCall(request, "POST", `/eco/${eco.id}/items`, { data: { doc_type: "bom", doc_id: draft.id, disposition: { open_wos: "flag", open_pos: "flag_cancel", stock: "use_up" } } });
    await gotoMfg(page, "/eco");
    await page.getByTestId("eco-row").first().getByRole("link").click();
    await expect(page.getByTestId("eco-page")).toBeVisible();
    await page.getByTestId("eco-tab-impact").click();
    await expect(page.getByTestId("eco-impact")).toBeVisible({ timeout: 60_000 });
    const impact = await mfgJson<{ use_up_date?: string | null }>(request, `/eco/${eco.id}/impact`);
    if (impact.use_up_date) await expect(page.getByTestId("eco-useup")).toBeVisible();

    // transfers: single-user mode has no second plant, so the list shows its empty state
    await gotoMfg(page, "/transfers");
    await expect(page.getByTestId("transfer-table")).toBeVisible();
    await expect(page.getByTestId("transfer-table")).toContainText(/No outgoing transfers/);

    // audit trail: rows from the first test, CSV export downloads
    await gotoMfg(page, "/audit");
    await expect(page.getByTestId("audit-row").first()).toBeVisible();
    const dl = page.waitForEvent("download");
    await page.getByTestId("audit-export-csv").click();
    expect((await dl).suggestedFilename()).toMatch(/\.csv$/);
  });
});
