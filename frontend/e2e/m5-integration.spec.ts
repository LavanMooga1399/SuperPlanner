/**
 * M5 WP-U (docs/M5-DESIGN.md 4-7, 13): the integration console, ERP-owned fields, inbound batches with per-record
 * results and code mappings, the webhook address guard, stock reconciliation from an uploaded ERP list; trace (tree,
 * graph, exact vs possible), where-used -> recall, ECO with impact, transfers and the audit trail.
 * Trace, recall, ECO and transfer routes answer from the S0 fixture until S3/S4, so those checks are about the
 * screens, not about data computed from the sample.
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

  test("trace tree and graph, where-used to recall, ECO impact, transfers, audit trail", async ({ page }) => {
    // trace (fixture tree until S3): exact and possible links are told apart in text, the graph view draws
    await gotoMfg(page, "/trace?kind=serial&id=srl_x&dir=backward&label=TPU-000123");
    await expect(page.getByTestId("trace-tree")).toBeVisible();
    await expect(page.locator('[data-testid="trace-node"]').first()).toBeVisible();
    await expect(page.locator('[data-testid="trace-node"][data-precision="exact"], [data-testid="trace-node"][data-precision="possible"]').first()).toBeVisible();
    await page.getByTestId("trace-forward").click();
    await expect(page).toHaveURL(/dir=forward/);
    await page.getByTestId("trace-view-graph").click();
    await expect(page.getByTestId("trace-graph").locator("svg")).toBeVisible();

    // a recall from a trace node -> the report
    await page.goto(`/mfg/recalls?new=1&kind=lot&id=lot_${"0".repeat(31)}1&label=R-2611`);
    await expect(page.getByTestId("recall-new")).toBeVisible();
    await page.getByTestId("recall-create").click();
    await expect(page.getByTestId("recall-page")).toBeVisible();
    await expect(page.getByTestId("recall-units")).toBeVisible();
    await expect(page.getByTestId("recall-quarantine")).toBeVisible();

    // ECO: list -> detail -> impact (use-up date suggestion)
    await gotoMfg(page, "/eco");
    await page.getByTestId("eco-row").first().getByRole("link").click();
    await expect(page.getByTestId("eco-page")).toBeVisible();
    await page.getByTestId("eco-tab-impact").click();
    await expect(page.getByTestId("eco-impact")).toBeVisible();
    await expect(page.getByTestId("eco-useup")).toBeVisible();

    // transfers
    await gotoMfg(page, "/transfers");
    await expect(page.getByTestId("transfer-row").first()).toBeVisible();
    await page.getByTestId("transfer-row").first().getByRole("link").click();
    await expect(page.getByTestId("transfer-lines")).toBeVisible();

    // audit trail: rows from the first test, CSV export downloads
    await gotoMfg(page, "/audit");
    await expect(page.getByTestId("audit-row").first()).toBeVisible();
    const dl = page.waitForEvent("download");
    await page.getByTestId("audit-export-csv").click();
    expect((await dl).suggestedFilename()).toMatch(/\.csv$/);
  });
});
