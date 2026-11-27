/**
 * M9 WP-U (docs/M9-DESIGN.md 10, 12): the network, S&OP and trade screens against the frozen contract. The network
 * workspace needs an organisation (not available in the single-user e2e server), so `/me` is marked as the network
 * workspace and the N/S/T routes answer from the S0 fixture (`api/mfg/fixtures/example_m9.json`), extended to three
 * nodes. Writes are captured and checked for the contract shape. Titles carry `@req` tags for the trace matrix.
 * `SP_M9_SHOTS=1` also stores the three review screenshots in docs/ux-screens.
 */
import { expect, test, type Page, type Route } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const FX = JSON.parse(fs.readFileSync(path.resolve(here, "../../backend/superplanner/api/mfg/fixtures/example_m9.json"), "utf8")) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const SHOTS = process.env.SP_M9_SHOTS ? path.resolve(here, "../../docs/ux-screens") : null;

const QC = "usr_0000000000000000000000000000000b";
const US1 = "usr_0000000000000000000000000000000c";
const DC = FX.net_node.owner_id as string;
const NODES = [
  { ...FX.net_node, owner_id: QC, code: "QC", name: "Quebec City", kind: "plant", country: "CA", currency: "CAD", tz: "America/Toronto", lines: 4 },
  { ...FX.net_node, owner_id: US1, code: "US1", name: "Needles US", kind: "plant", country: "US", currency: "USD", tz: "America/Chicago", lines: 2 },
  FX.net_node,
];
const LANES = [FX.net_lane, { ...FX.net_lane, id: "nln_2", from_owner_id: US1, to_owner_id: DC, transit_days: 2 }, { ...FX.net_lane, id: "nln_3", from_owner_id: US1, to_owner_id: QC, transit_days: 4 }];
const baseline = { ...FX.sop_scenario, id: "ssc_base", number: "SC-000001", name: "Baseline", baseline: true, changes: [] };
const expansion = { ...FX.sop_scenario };
const COMPARE = {
  currency: "USD",
  items: [
    { scenario: { id: baseline.id, number: baseline.number, name: baseline.name, status: "completed", baseline: true, validator_ok: true }, kpis: FX.sop_compare.items[0].kpis, delta: null },
    {
      scenario: { id: expansion.id, number: expansion.number, name: expansion.name, status: "completed", baseline: false, validator_ok: true },
      kpis: expansion.kpis,
      delta: {
        horizon: { service_pct: 0.8, unmet_units: -180000, revenue: 380000, gross_margin: 210000, capex: 45000000 },
        year: { service_pct: 0.4, gross_margin: 90000 },
        next3: { service_pct: 0, gross_margin: 0 },
      },
    },
  ],
};

interface Captured {
  method: string;
  path: string;
  body: unknown;
}

/** Network workspace + fixture answers for every M9 route; returns the captured writes. */
async function mockNetwork(page: Page, cycleStatus = "pre_sop"): Promise<Captured[]> {
  const writes: Captured[] = [];
  let cycle = { ...FX.sop_cycle, status: cycleStatus, recommended_scenario_id: expansion.id, recommend_note: "Expansion keeps service above 99 %." };
  await page.route(/\/api\/v1\/mfg\/me$/, async (route) => {
    const res = await route.fetch();
    const me = await res.json();
    await route.fulfill({ response: res, json: { ...me, workspace_kind: "network" } });
  });
  await page.route(/\/api\/v1\/mfg\/esig\/preview/, (route) =>
    route.fulfill({ json: { record_type: "sop_cycle", record_id: cycle.id, action: "approve", record_version: 1, content_hash: "abc", content: {}, summary: [], required: false, part11_mode: false, policy: null, next_step: null, signatures: [], signer: { enrolled: false, legal_name: null, locked_until: null, methods: [], username: "" }, legal_statement: "" } }),
  );
  await page.route(/\/api\/v1\/mfg\/(net|sop|trade|mps)\//, async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname.replace(/^.*\/api\/v1\/mfg/, "");
    const m = req.method();
    if (m !== "GET") writes.push({ method: m, path: p, body: req.postDataJSON?.() ?? null });
    const json = (j: unknown, status = 200) => route.fulfill({ status, json: j });
    if (p === "/net/nodes") return json({ items: NODES });
    if (p === "/net/lanes") return json({ items: LANES });
    if (p === "/net/sourcing") return json({ items: [FX.net_sourcing, { ...FX.net_sourcing, id: "nsr_2", dest_owner_id: QC, source_owner_id: US1, family: "NDL", quota_pct: 70 }, { ...FX.net_sourcing, id: "nsr_3", dest_owner_id: QC, source_kind: "supplier", source_owner_id: null, supplier_code: "EXT", family: "NDL", priority: 2, quota_pct: 30, lane_id: null }] });
    if (p === "/net/sourcing/resolve") return json(FX.net_resolve);
    if (p === "/net/runs") return m === "POST" ? json({ ...FX.net_run, status: "queued" }, 202) : json({ items: [FX.net_run], total: 1, limit: 30, offset: 0 });
    if (/^\/net\/runs\/[^/]+$/.test(p)) return json({ ...FX.net_run, published: false, publish_result: null });
    if (p.endsWith("/grid")) return json(FX.net_grid);
    if (p.endsWith("/transfers")) return json({ items: [FX.net_transfer, { ...FX.net_transfer, id: "npt_2", firm: false, to_id: null, to_number: null, ship_date: "2027-01-18", receive_date: "2027-01-20" }] });
    if (p.endsWith("/shortages")) return json({ items: [FX.net_shortage] });
    if (p.endsWith("/utilisation")) return json({ items: [FX.net_utilisation, { ...FX.net_utilisation, used: FX.net_utilisation.available * 0.9, week: "2027-01-11" }] });
    if (p.endsWith("/pegging")) return json(FX.net_pegging);
    if (p.endsWith("/publish") && p.startsWith("/net/")) return json(FX.net_publish);
    if (p === "/net/ramp-curves") return json({ items: [FX.ramp_curve] });
    if (p === "/sop/cycles") return m === "POST" ? json(cycle, 201) : json({ items: [cycle], total: 1, limit: 36, offset: 0 });
    if (/^\/sop\/cycles\/[^/]+$/.test(p)) return json(cycle);
    if (p.endsWith("/demand/overrides")) return json(FX.sop_override, 201);
    if (p.endsWith("/demand")) return json(FX.sop_demand);
    if (p.endsWith("/approve")) {
      cycle = { ...cycle, status: "approved", approved_scenario_id: expansion.id };
      return json(cycle);
    }
    if (p === "/sop/scenarios") return m === "POST" ? json({ ...expansion, id: "ssc_new", number: "SC-000009", status: "draft" }, 201) : json({ items: [baseline, expansion] });
    if (p === "/sop/compare") return json(COMPARE);
    if (p.endsWith("/rough-cut")) return json(FX.sop_rough_cut);
    if (p.endsWith("/financial")) return json(FX.sop_financial);
    if (p.endsWith("/make-buy")) return json({ items: [FX.sop_make_buy] });
    if (/^\/sop\/scenarios\/[^/]+$/.test(p)) return json(p.endsWith(baseline.id) ? baseline : expansion);
    if (p === "/trade/tariffs") return m === "PUT" ? json(FX.bulk_result) : json({ items: [FX.tariff] });
    if (p === "/trade/fx") return json({ items: [FX.fx] });
    if (p === "/trade/milestones") return json({ items: [FX.milestone] });
    if (p === "/trade/country-risk") return json({ items: [FX.country_risk] });
    if (p === "/trade/reports") return json({ items: [FX.trade_report], total: 1, limit: 50, offset: 0 });
    if (/^\/trade\/reports\/[^/]+$/.test(p)) return json(FX.trade_report);
    if (p.includes("/content")) return json(FX.lot_content);
    if (p === "/trade/risk") return json({ items: [FX.risk_row] });
    return json({ error: { code: "NOT_FOUND", message: `no mock for ${m} ${p}`, details: {} } }, 404);
  });
  return writes;
}

async function goto(page: Page, p: string) {
  await page.goto(`/mfg${p}`);
  await expect(page.getByTestId("nav-group-network")).toBeVisible();
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: path.join(SHOTS, name), fullPage: false });
}

test.describe("M9 network, S&OP and trade", () => {
  test("network home, run views and publish @req:M9-NET-04 @req:M9-NET-07 @req:M9-NET-09", async ({ page }) => {
    const writes = await mockNetwork(page);
    await goto(page, "");
    await expect(page).toHaveURL(/\/mfg\/network$/);
    // plant-only menus are hidden in the network workspace
    await expect(page.getByTestId("nav-group-execution")).toHaveCount(0);
    await expect(page.getByTestId("net-diagram")).toBeVisible();
    await expect(page.getByTestId("net-node-QC")).toBeVisible();
    await expect(page.getByTestId("net-lane")).toHaveCount(3);
    await page.getByTestId("net-node-US1").click();
    await expect(page.getByTestId("net-node-detail")).toContainText("Needles US");
    await expect(page.getByTestId("kpi-fill")).toContainText("98.7");
    await shot(page, "m9-network-home.png");
    await page.getByTestId("net-run-row").first().click();
    await expect(page.getByTestId("net-valid")).toBeVisible();
    await expect(page.getByTestId("net-grid")).toBeVisible();
    await page.getByTestId("net-tab-transfers").click();
    await expect(page.getByTestId("net-transfer-row")).toHaveCount(2);
    await expect(page.getByTestId("net-firm")).toHaveCount(1);
    await page.getByTestId("net-tab-shortages").click();
    await expect(page.getByTestId("net-cause").first()).toHaveAttribute("data-cause", "NET_CAPACITY_SHORT");
    await page.getByTestId("net-sh-peg").first().click();
    await expect(page.getByTestId("net-pegging")).toBeVisible();
    expect(await page.getByTestId("net-peg-node").count()).toBeGreaterThan(1);
    await page.getByTestId("net-tab-capacity").click();
    await expect(page.getByTestId("net-heatmap")).toBeVisible();
    await page.getByTestId("net-publish").click();
    await page.getByRole("dialog").getByRole("button", { name: /Publish/ }).click();
    await expect.poll(() => writes.some((w) => w.method === "POST" && /\/net\/runs\/[^/]+\/publish$/.test(w.path))).toBe(true);
  });

  test("sourcing rules: quota bar, resolve tester, new rule @req:M9-NET-01", async ({ page }) => {
    const writes = await mockNetwork(page);
    await goto(page, "/network/sourcing");
    await expect(page.getByTestId("net-rule-row")).toHaveCount(3);
    await expect(page.getByTestId("net-quota-bar").first()).toBeVisible();
    await page.locator("#rs-dest").selectOption(DC);
    await page.locator("#rs-key").fill("SYR-3ML");
    await page.getByTestId("net-resolve-go").click();
    await expect(page.getByTestId("net-resolve-result")).toHaveAttribute("data-mode", "priority");
    await page.getByTestId("net-rule-new").click();
    await page.locator("#sr-dest").selectOption(DC);
    await page.locator("#sr-scope-v").fill("NDL-21G");
    await page.locator("#sr-src").selectOption(US1);
    await page.getByTestId("net-rule-save").click();
    await expect.poll(() => writes.find((w) => w.path === "/net/sourcing")?.body).toMatchObject({ dest_owner_id: DC, item_key: "NDL-21G", source_kind: "plant", source_owner_id: US1, family: null });
  });

  test("S&OP: demand override with reason, compare with deltas, signed approval @req:M9-SOP-01 @req:M9-SOP-07", async ({ page }) => {
    const writes = await mockNetwork(page, "executive");
    await goto(page, "/sop");
    await page.getByTestId("sop-cycle-row").first().click();
    await page.getByTestId("sop-view-demand").click();
    await page.getByTestId("sop-cons-cell").first().click();
    await page.getByTestId("sop-ovr-value").fill("10");
    await expect(page.getByTestId("sop-ovr-save")).toBeDisabled();
    await page.getByTestId("sop-ovr-reason").fill("Tender won in Ontario");
    await page.getByTestId("sop-ovr-save").click();
    await expect.poll(() => writes.find((w) => w.path.endsWith("/demand/overrides"))?.body).toMatchObject({ mode: "pct", value: 10, reason: "Tender won in Ontario", node_owner_id: null });
    await page.getByTestId("sop-view-compare").click();
    await expect(page.getByTestId("sop-compare-table")).toBeVisible();
    await expect(page.getByTestId("kpi-delta").first()).toHaveAttribute("data-dir", /better|worse|flat/);
    await shot(page, "m9-sop-compare.png");
    await page.getByTestId("sop-view-approve").click();
    await page.getByTestId("sop-sign").click();
    await page.getByRole("dialog").getByRole("button", { name: /Approve/ }).click();
    await expect.poll(() => writes.find((w) => w.path.endsWith("/approve"))?.body).toMatchObject({ scenario_id: expansion.id });
  });

  test("scenario editor: add line with STD26 ramp-up @req:M9-SOP-04", async ({ page }) => {
    await mockNetwork(page);
    await goto(page, `/sop/scenarios/${expansion.id}`);
    await expect(page.getByTestId("scn-change")).toHaveCount(expansion.changes.length);
    await expect(page.getByTestId("curve-chart").first()).toBeVisible();
    await page.getByTestId("scn-add-kind").selectOption("supplier_allocation");
    await page.getByTestId("scn-add").click();
    await expect(page.getByTestId("scn-change")).toHaveCount(expansion.changes.length + 1);
    await expect(page.getByTestId("scn-save")).toBeEnabled();
  });

  test("trade: tariff paste, milestone report, lot content, sourcing risk @req:M9-TRD-02 @req:M9-TRD-05 @req:M9-TRD-08", async ({ page }) => {
    const writes = await mockNetwork(page);
    await goto(page, "/trade");
    await page.getByTestId("trd-tariff-paste").click();
    await page.getByTestId("trd-paste").fill("US\t901832\tCN\ts301\t25\t\t\t2026-01-01\t\tExample");
    await page.getByTestId("trd-paste-save").click();
    await expect.poll(() => writes.find((w) => w.path === "/trade/tariffs")?.body).toMatchObject({ items: [{ dest_country: "US", hts_prefix: "901832", coo: "CN", layer: "s301", rate_pct: 25 }] });
    await page.goto(`/mfg/trade/reports/${FX.trade_report.id}`);
    await expect(page.getByTestId("trd-grid").first()).toBeVisible();
    await expect(page.locator('[data-testid="trd-grid"] [data-status="at_risk"]').first()).toBeVisible();
    await expect(page.getByTestId("trd-at-risk")).toBeVisible();
    await shot(page, "m9-tariff-report.png");
    const open = page.getByTestId("trd-lot-open");
    if (await open.count()) {
      await open.first().click();
      await expect(page.getByTestId("lot-dom-value")).toContainText("56.6");
      await page.keyboard.press("Escape");
    }
    await goto(page, "/sourcing-risk");
    await page.getByTestId("risk-min").getByRole("button", { name: "All" }).click();
    await expect(page.getByTestId("risk-row").first()).toBeVisible();
    await expect(page.getByTestId("risk-score").first()).toHaveAttribute("data-tone", "danger");
  });
});
