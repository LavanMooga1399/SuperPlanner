#!/usr/bin/env node
/**
 * Records the SuperPlanner demo video on the fictional `meddev` sample (see demo/README.md).
 *
 *   node demo/record-demo.mjs [--out ../docs/demo] [--only 1,2,5] [--keep-servers]
 *
 * Starts the API on a fresh PostgreSQL database (APP_ENV=development, ASSISTANT_AI_DEMO=true, single-user mode) and
 * the Vite dev server, loads the sample, then plays the scenes below in one recorded browser context. Each scene is
 * one async function in SCENES (add new scenes there); captions and title cards are injected DOM elements, so the
 * app itself is unchanged. The raw .webm is converted to H.264 .mp4 when ffmpeg with libx264 is available.
 */
import { chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { API, BASE, CAPTION_INIT, Session, api, caption, captionAtTop, card, frontendDir, glide, settle, startServers, uncard, useSession, waitRun } from "./lib.mjs";

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : dflt;
};
const OUT = path.resolve(frontendDir, opt("out", "../docs/demo"));
const ONLY = opt("only", "") ? new Set(opt("only", "").split(",").map((s) => s.trim())) : null;
const VIEW = { width: Number(opt("width", 1440)), height: Number(opt("height", 810)) };
// Playwright records at the viewport size (it never upscales); the .mp4 is scaled to OUT_SIZE by ffmpeg (lanczos),
// so the app renders at a readable 1440x810 and the delivered video is 1920x1080.
const VIDEO = VIEW;
const OUT_SIZE = opt("out-size", "1920x1080");
const PACE = Number(opt("pace", 1.7)); // multiply every hold

const hold = (page, ms) => page.waitForTimeout(ms * PACE);
const tid = (page, id) => page.getByTestId(id);

/** Data the scenes share (ids looked up through the API once the sample is loaded). */
const ctx = {};
const PASSWORD = "fictional demo passphrase 2026";
const PLANNER = { email: "claire.gagnon@example.com", name: "Claire Gagnon" };   // fictional person

async function lookup() {
  const item = async (pn) => (await api("GET", `/items?q=${encodeURIComponent(pn)}&limit=50`)).items.find((i) => i.part_number === pn);
  const doc = async (coll, no) => (await api("GET", `${coll}?q=${encodeURIComponent(no)}&limit=50`)).items.find((d) => d.number === no);
  ctx.ivs = await item("MDV-IVS-20");
  ctx.pp = await item("MDV-RES-PP");
  ctx.syr10 = await item("MDV-SYR-10");
  ctx.rush = await doc("/demand-orders", "DO-MDV-1003");
  ctx.wo1 = await doc("/work-orders", "WO-MDV-0001");
  ctx.lines = (await api("GET", "/lines?limit=200")).items;
  ctx.groups = (await api("GET", "/groups?limit=200")).items;
  ctx.ops = (await api("GET", `/work-orders/${ctx.wo1.id}/operations`)).items;
  const ils = (await api("GET", "/qa/inspection-lots?limit=100")).items;
  ctx.incoming = ils.find((l) => l.scope === "incoming" && l.status === "open") ?? ils.find((l) => l.status === "open");
  ctx.capa = (await api("GET", "/qa/capas?limit=20")).items[0];
  const stp = await item("MDV-SOLV");
  // bonding solvent is issued by lot scan at the line in this demo (the sample backflushes every component)
  const rec = await api("GET", `/items/${stp.id}`);
  const KEYS = ["part_number", "revision", "description", "uom", "make_buy", "family", "setup_family", "lead_time_days", "receiving_days", "lot_rule",
    "fixed_lot_qty", "min_order_qty", "order_multiple", "safety_stock", "serialized", "shelf_life_days", "handling_class", "handling_note",
    "attributes", "active", "external_ref", "standard_cost", "lot_controlled", "lot_period_days", "issue_method"];
  const body = Object.fromEntries(KEYS.filter((k) => k in rec).map((k) => [k, rec[k]]));
  await api("PUT", `/items/${stp.id}`, { ...body, issue_method: "manual" }, { "If-Match": `"${rec.row_version}"`, "X-SP-Change-Reason": "Demo%3A%20solvent%20issued%20by%20lot%20scan" });
  const lots = (await api("GET", `/lots?item_id=${stp.id}&limit=20`)).items.filter((l) => (l.on_hand ?? 0) > 0);
  ctx.stopperLot = lots[0]?.lot_code ?? null;
  ctx.wo3 = await doc("/work-orders", "WO-MDV-0003");
  ctx.ops3 = (await api("GET", `/work-orders/${ctx.wo3.id}/operations`)).items;
}

/** Navigate: client-side (history + popstate, no reload and no blank frame) once the app is open, else a page load. */
async function go(page, url) {
  await caption(page, "").catch(() => undefined);                 // no caption of the previous step on the new page
  if (page.url().startsWith(BASE) && !page.url().startsWith(`${BASE}/m/`)) {
    await page.evaluate((u) => {
      window.history.pushState({}, "", u);
      window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
    }, url);
    await page.waitForTimeout(150);
  } else {
    await page.goto(`${BASE}${url}`);
  }
  await settle(page);
}

// ---------------------------------------------------------------- scenes (one function each; add new ones to SCENES)

async function sceneTitle(page) {
  // the app loads under the card; the video is trimmed to start once the card is up (no blank frames)
  await page.goto(`${BASE}/mfg`);
  await card(page, "SuperPlanner", ["Production planning for regulated manufacturing.", "Demo with fictional data."],
    "Products modelled on a typical medical-device portfolio. All names, people, customers and suppliers are fictional.", 0);
  ctx.trimStart = (Date.now() - ctx.videoStart) / 1000;
  await settle(page, 0);
  await hold(page, 6500);
  await uncard(page);
}

async function sceneOverview(page) {
  await caption(page, "A fictional single-use medical-device plant: moulding, cleanroom assembly, EtO sterilisation and QC release.");
  await hold(page, 3000);
  await go(page, "/mfg/dashboard");
  await tid(page, "tile-otd").waitFor({ timeout: 30_000 });
  await settle(page, 800);
  await caption(page, "The plant dashboard: on-time delivery, load against capacity, material risk, execution and quality.");
  await glide(page, tid(page, "tile-otd").getByTestId("tile-status"), { scroll: false });
  await hold(page, 3000);
  await glide(page, tid(page, "tile-material_risk").getByTestId("tile-status"), { scroll: false });
  await hold(page, 3000);
}

async function sceneMasterData(page) {
  await go(page, `/mfg/items/${ctx.ivs.id}/bom`);
  await caption(page, "Master data: the IV administration set's BOM, from moulded parts and extruded tubing down to resin.");
  await hold(page, 4500);
  await go(page, `/mfg/items/${ctx.ivs.id}/routing`);
  await caption(page, "Its routing: cleanroom assembly, leak test, packaging and UDI labelling, EtO sterilisation, QC release.");
  await hold(page, 4500);
}

async function sceneForecast(page) {
  await go(page, "/mfg/forecast");
  await caption(page, "Demand forecasting: statistical models are fitted per item from 30 months of shipment history.");
  await hold(page, 2500);
  await glide(page, tid(page, "fc-run"), { click: true });
  await glide(page, tid(page, "fc-run-start"), { click: true });
  await page.waitForFunction(() => document.querySelector('[data-testid="fc-version-status"]')?.getAttribute("data-status") === "draft", null, { timeout: 120_000 });
  await settle(page, 800);
  await tid(page, "fc-search").fill(ctx.syr10.part_number);
  await hold(page, 600);
  await glide(page, tid(page, "fc-item-row").filter({ hasText: ctx.syr10.part_number }), { click: true });
  await tid(page, "fc-panel").waitFor();
  await settle(page, 800);
  await caption(page, "The workbench shows history, model fit and forecast; the planner overrides a month and gives the reason.");
  await hold(page, 3000);
  const cell = tid(page, "fc-final-cell").nth(2);
  await glide(page, cell, { click: true });
  await tid(page, "fc-ov-value").fill("3200000");
  await tid(page, "fc-ov-reason").click();
  await page.keyboard.type("Provincial tender awarded for Q1", { delay: 35 });
  await hold(page, 600);
  await glide(page, tid(page, "fc-override-save"), { click: true });
  await settle(page, 1500);
  await glide(page, tid(page, "fc-overrides"), { optional: true });
  await hold(page, 2500);
  await go(page, "/mfg/forecast/accuracy");
  await caption(page, "Forecast accuracy: error and bias by ABC class, and a backtest of each method on held-out periods.");
  await hold(page, 4500);
}

async function sceneSafetyStock(page) {
  await go(page, "/mfg/invopt");
  await tid(page, "ss-matrix").waitFor({ timeout: 30_000 });
  await caption(page, "Safety stock by ABC / XYZ class: proposals from forecast error, lead time and a service level per class.");
  await glide(page, tid(page, "ss-matrix"));
  await hold(page, 4000);
  const all = tid(page, "ss-page").getByTestId("vt-select-all");
  await glide(page, all, { click: true });
  await tid(page, "ss-bulk").waitFor();
  await caption(page, "Nothing changes until a manager approves; the approval and its reason are recorded.");
  await glide(page, tid(page, "ss-approve"), { click: true });
  await tid(page, "ss-reason").waitFor();
  await captionAtTop(page, true);
  await page.keyboard.type("Reviewed with materials team, weekly S&OP", { delay: 30 });
  await hold(page, 600);
  await glide(page, page.getByRole("dialog").getByRole("button", { name: "Approve" }), { click: true });
  await captionAtTop(page, false);
  await settle(page, 1500);
  await glide(page, tid(page, "ss-page").getByRole("button", { name: "Approved", exact: true }), { click: true, optional: true });
  await settle(page, 2500);
}

async function sceneMrp(page) {
  await go(page, "/mfg/mrp");
  await caption(page, "MRP nets the forecast and orders through the BOM against lots, open orders and lead times.");
  await glide(page, tid(page, "mrp-new-run"), { click: true });
  await tid(page, "mrp-run-form").waitFor();
  await tid(page, "mrp-label").fill("Weekly MRP");
  await glide(page, tid(page, "mrp-run-submit"), { click: true });
  await page.waitForURL(/\/mfg\/mrp\/runs\/[^/]+/, { timeout: 120_000 });
  await tid(page, "run-summary").waitFor({ timeout: 120_000 });
  await settle(page);
  await caption(page, "Late demand is listed with why: the limiting part and the reason, down the BOM.");
  await glide(page, tid(page, "run-late-demand"));
  await hold(page, 5500);
}

async function sceneRatePlan(page) {
  await go(page, "/mfg/rate");
  await caption(page, "Rate planning for flow lines: campaigns by size and gauge, with changeovers and cleanroom cleaning.");
  await hold(page, 2000);
  await glide(page, tid(page, "rate-new"), { click: true });
  await glide(page, tid(page, "rate-start"), { click: true });
  await tid(page, "rate-run-page").waitFor({ timeout: 60_000 });
  await page.waitForFunction(() => !/queued|running/.test(document.querySelector('[data-testid="rate-run-page"]')?.getAttribute("data-status") ?? "running"), null, { timeout: 180_000 });
  await settle(page, 1000);
  await caption(page, "Each new plan is checked by an independent validator: shift windows, changeovers, cleaning and rate holds.");
  await glide(page, tid(page, "rate-valid"), { optional: true });
  await hold(page, 3500);
  await caption(page, "The grid shows what each line makes each day against its rate.");
  await glide(page, tid(page, "rate-grid"), { optional: true });
  await hold(page, 4000);
  await glide(page, tid(page, "rate-tab-gantt"), { click: true });
  await tid(page, "rate-gantt").waitFor();
  await settle(page, 800);
  await caption(page, "The campaign Gantt: long runs of one size, changeovers and cleaning between them.");
  await hold(page, 4500);
  await caption(page, "Publishing makes the plan the supply that MRP and the lines work to; its firm days are work orders.");
  await glide(page, tid(page, "rate-publish"), { click: true });
  const dlg = page.getByRole("dialog");
  await dlg.waitFor();
  await captionAtTop(page, true);
  await hold(page, 1500);
  await glide(page, dlg.getByRole("button").last(), { click: true });
  await captionAtTop(page, false);
  await tid(page, "rate-publish-result").waitFor({ timeout: 60_000 });
  await settle(page, 1000);
  await glide(page, tid(page, "rate-publish-result"));
  await hold(page, 4000);
}

async function sceneSchedule(page) {
  await go(page, "/mfg/schedule");
  await caption(page, "Finite scheduling of moulding presses and assembly lines on their shifts, with overtime suggestions.");
  await glide(page, tid(page, "aps-new-run"), { click: true });
  await tid(page, "aps-run-form").waitFor();
  await tid(page, "aps-label").fill("Weekly schedule");
  await glide(page, tid(page, "aps-run-submit"), { click: true });
  await page.waitForURL(/\/mfg\/schedule\/runs\/[^/]+/, { timeout: 120_000 });
  await tid(page, "aps-summary").waitFor({ timeout: 120_000 });
  await settle(page);
  await glide(page, tid(page, "aps-tab-gantt"), { click: true });
  await tid(page, "gantt-canvas").waitFor();
  const grp = (code) => ctx.groups.find((g) => g.code === code)?.id;
  await tid(page, "gantt-group").selectOption(grp("MOULD"));
  await settle(page, 800);
  await caption(page, "Presses run on three shifts; mould changeover times depend on the mould family before.");
  await hold(page, 4500);
  const allow = tid(page, "aps-rerun-allow");
  if (await allow.count()) {
    await caption(page, "Re-run allowing overtime and compare: lateness saved against overtime hours and cost.");
    await glide(page, allow, { click: true });
    await page.waitForURL(/\/compare/, { timeout: 120_000 });
    await tid(page, "aps-tradeoff").waitFor({ timeout: 120_000 });
    await settle(page);
    await glide(page, tid(page, "aps-tradeoff"));
    await hold(page, 5000);
    await caption(page, "The planner publishes the plan without overtime; suggested shifts go to supervisors to approve.");
    await glide(page, tid(page, "aps-publish-base"), { click: true });
    await page.getByRole("dialog").waitFor();
    await captionAtTop(page, true);
    await glide(page, page.getByRole("dialog").getByRole("button", { name: "Publish" }), { click: true });
    await captionAtTop(page, false);
    await settle(page, 2000);
  }
}

async function sceneSterilisation(page) {
  await go(page, "/mfg/sterilisation");
  await tid(page, "ster-timeline").waitFor({ timeout: 30_000 });
  await caption(page, "EtO sterilisation: loads per chamber, the cycle, aeration and the wait for QA release.");
  await glide(page, tid(page, "ster-timeline"));
  await hold(page, 4500);
  const rel = tid(page, "ster-release").first();
  await caption(page, "Releasing a load is an electronic signature: the record, the meaning, and the signer's password.");
  await glide(page, rel, { click: true });
  const dlg = tid(page, "esig-dialog");
  await dlg.waitFor();
  await captionAtTop(page, true);
  await settle(page, 800);
  await glide(page, tid(page, "esig-meaning"), { optional: true });
  await hold(page, 2500);
  const early = tid(page, "ster-early-reason");
  if (await early.count()) {
    await early.click();
    await page.keyboard.type("Parametric release data reviewed; customer order due", { delay: 20 });
  }
  const user = tid(page, "esig-username");
  if ((await user.count()) && !(await user.inputValue())) await user.fill(PLANNER.email);
  await tid(page, "esig-password").click();
  await page.keyboard.type(PASSWORD, { delay: 25 });
  const comment = tid(page, "esig-comment");
  if (await comment.count()) {
    await comment.click();
    await page.keyboard.type("Biological indicators negative; cycle parameters within limits", { delay: 20 });
  }
  await hold(page, 1200);
  await glide(page, tid(page, "esig-submit"), { click: true });
  await dlg.waitFor({ state: "hidden", timeout: 30_000 });
  await captionAtTop(page, false);
  await settle(page, 1500);
  await caption(page, "The lots on the load come off hold; the signature is stored with the record and can be verified.");
  await hold(page, 3500);
}

async function sceneInspection(page) {
  const il = ctx.incoming;
  await go(page, `/mfg/qa/inspection-lots/${il.id}`);
  await tid(page, "qa-lot-page").waitFor({ timeout: 30_000 });
  await caption(page, `Incoming inspection of ${il.item?.part_number ?? "a supplier lot"}: the plan sets sample size and accept / reject numbers.`);
  await hold(page, 3500);
  const first = tid(page, "qa-char").first();
  for (let i = 0; i < 3; i++) {
    const verdict = await tid(page, "qa-verdict").getAttribute("data-verdict");
    if (verdict === "reject") break;
    if (await first.getByTestId("qa-fail").count()) await glide(page, first.getByTestId("qa-fail"), { click: true });
    else {
      await first.getByTestId("qa-value").fill("0.5");
      await glide(page, first.getByTestId("qa-save-result"), { click: true });
    }
    await settle(page, 700);
  }
  await caption(page, "Results are entered per sample; the verdict updates live and decides the next step.");
  await glide(page, tid(page, "qa-verdict"));
  await hold(page, 2500);
  await glide(page, tid(page, "qa-decision-reject"), { click: true });
  const dlg = tid(page, "esig-dialog");
  await dlg.waitFor();
  await captionAtTop(page, true);
  await tid(page, "qa-decision-note").fill("Chipped flanges above the reject number");
  const pw = tid(page, "esig-password");
  if (await pw.count()) {
    const user = tid(page, "esig-username");
    if ((await user.count()) && !(await user.inputValue())) await user.fill(PLANNER.email);
    await pw.fill(PASSWORD);
  }
  await hold(page, 1200);
  await glide(page, tid(page, "esig-submit"), { click: true });
  await dlg.waitFor({ state: "hidden", timeout: 30_000 });
  await captionAtTop(page, false);
  await settle(page, 1500);
  await caption(page, "Rejecting opens a nonconformance report and keeps the lot on hold.");
  const decided = await api("GET", `/qa/inspection-lots/${il.id}`);
  const open = page.locator(`main a[href$="/qa/ncrs/${decided.ncr_id}"]`).first();
  if (await open.count()) await glide(page, open, { click: true });
  else await go(page, `/mfg/qa/ncrs/${decided.ncr_id}`);
  await tid(page, "ncr-page").waitFor({ timeout: 30_000 });
  await settle(page, 1000);
  await glide(page, tid(page, "qa-tab-dispositions"), { click: true });
  await caption(page, "The material review proposes a disposition for the quantity: here, return to the supplier.");
  await glide(page, tid(page, "ncr-disposition-add"), { click: true });
  const row = tid(page, "ncr-disposition-row").first();
  const kind = row.locator("select").first();
  if (await kind.count()) await kind.selectOption("return_to_supplier").catch(() => undefined);
  const txt = row.locator('input[type="text"], input:not([type]), textarea').last();
  if (await txt.count()) {
    await txt.click();
    await page.keyboard.type("Supplier to replace the lot and send a corrective action", { delay: 25 });
  }
  await hold(page, 3500);
}

async function sceneCapa(page) {
  await go(page, "/mfg/qa/capas");
  await caption(page, "CAPA: root cause, actions with owners and due dates, and the effectiveness check, linked to the NCR.");
  const row = page.getByRole("link", { name: /^CAPA-/ }).first();
  await glide(page, row, { click: true });
  await tid(page, "capa-page").waitFor({ timeout: 30_000 });
  await settle(page, 800);
  await hold(page, 5000);
}

async function sceneFloor(page) {
  await go(page, "/mfg/floor");
  await caption(page, "The shop-floor tablet: pick the line, sign in with a badge scan, scan the traveller.");
  const tile = page.locator('[data-testid="floor-line-pick"][data-code="ASM-04"]');
  await glide(page, tile, { click: true });
  await tid(page, "floor-line-title").waitFor();
  await settle(page, 600);
  await tid(page, "floor-crew").click();
  await page.keyboard.type("OP:OP-010\n", { delay: 50 });
  await hold(page, 1200);
  const op = ctx.ops3[0];
  await tid(page, "floor-crew").click();
  await page.keyboard.type(`${ctx.wo3.number}/${op.seq}\n`, { delay: 50 });
  await tid(page, "floor-op").waitFor();
  await settle(page, 1500);
  await glide(page, tid(page, "floor-action-start"), { click: true });
  const running = () => page.waitForFunction(() => document.querySelector('[data-testid="floor-op"]')?.getAttribute("data-status") === "running", null, { timeout: 6000 });
  await running().catch(async () => {
    await tid(page, "floor-action-start").click();          // the layout moved under the pointer: click it directly
    await running();
  });
  await settle(page, 800);
  if (ctx.stopperLot) {
    await caption(page, "Issue a component lot by scanning its label: the bonding-solvent lot is booked to this work order.");
    await glide(page, tid(page, "floor-action-issue-lot"), { click: true });
    await tid(page, "floor-issue-panel").waitFor();
    await tid(page, "floor-issue-lot").click();
    await page.keyboard.type(ctx.stopperLot, { delay: 60 });
    await tid(page, "floor-issue-qty").fill("4");
    await hold(page, 1500);
    await glide(page, tid(page, "floor-issue-submit"), { click: true });
    await settle(page, 2500);
    await hold(page, 1500);
  }
  await caption(page, "Report good and nonconforming quantities as they are made; other parts are backflushed by lot.");
  await glide(page, tid(page, "floor-action-report"), { click: true });
  await tid(page, "floor-qty-good").fill("6000");
  await hold(page, 1500);
  await glide(page, tid(page, "floor-qty-submit"), { click: true });
  await settle(page, 2000);
}

async function sceneTrace(page) {
  await go(page, "/mfg/trace");
  await caption(page, "Traceability: a finished lot of IV sets traced back to its component and resin supplier lots.");
  await tid(page, "trace-code").fill("WO-MDV-H03");
  await glide(page, tid(page, "trace-find"), { click: true });
  await tid(page, "trace-tree").waitFor({ timeout: 30_000 });
  await settle(page);
  await glide(page, tid(page, "trace-tree"));
  await hold(page, 4500);
  await go(page, `/mfg/trace/where-used?item=${ctx.pp.id}&supplier_lot=RSN-PP-88412`);
  await caption(page, "Where used: one resin supplier lot reached IV sets and syringes, shipped to three customers; start a recall.");
  await hold(page, 3500);
  await glide(page, tid(page, "whereused-recall"), { click: true });
  await tid(page, "recall-new").waitFor();
  await glide(page, tid(page, "recall-create"), { click: true });
  await tid(page, "recall-page").waitFor({ timeout: 30_000 });
  await settle(page);
  await caption(page, "The recall report lists affected lots, quantities, shipments and customers; stock on hand goes to quarantine.");
  await hold(page, 5000);
}

async function sceneAudit(page) {
  await go(page, `/mfg/qa/inspection-lots/${ctx.incoming.id}`);
  await tid(page, "qa-lot-page").waitFor({ timeout: 30_000 });
  await glide(page, tid(page, "qa-tab-history"), { click: true });
  await tid(page, "qa-history-event").first().waitFor({ timeout: 30_000 });
  await settle(page, 800);
  await caption(page, "Each regulated record keeps its history: who, when, the reason, the signature, and old and new values.");
  await glide(page, page.locator("table.qa-changes").first(), { optional: true });
  await hold(page, 5000);
  await go(page, "/mfg/audit");
  await tid(page, "audit-page").waitFor();
  await settle(page, 800);
  await caption(page, "The plant-wide audit trail is hash-chained, so later tampering shows up, and can be exported.");
  await glide(page, tid(page, "audit-verify"), { optional: true });
  await hold(page, 3500);
}

async function sceneFrench(page) {
  await caption(page, "The interface is also available in Canadian French; numbers and dates follow the language.");
  await glide(page, tid(page, "display-menu"), { click: true });
  await tid(page, "lang-select").selectOption("fr-CA");
  await page.waitForLoadState("load");
  await settle(page, 1000);
  await go(page, "/mfg/sterilisation");
  await caption(page, "The interface is also available in Canadian French; numbers and dates follow the language.");
  await tid(page, "ster-timeline").waitFor({ timeout: 30_000 });
  await hold(page, 2500);
  await page.mouse.wheel(0, 380);
  await hold(page, 3500);
  await tid(page, "display-menu").click();
  await tid(page, "lang-select").selectOption("en");
  await page.waitForLoadState("load");
  await settle(page, 800);
}

async function sceneValidation(page) {
  await go(page, "/mfg/validation");
  await tid(page, "val-matrix").waitFor({ timeout: 30_000 });
  await caption(page, "A requirement trace matrix links each requirement to its scripted tests, as input to the customer's own validation.");
  await hold(page, 5000);
}

async function sceneAssistant(page) {
  await go(page, `/mfg/demand/${ctx.rush.id}`);
  await caption(page, "The planning assistant (scripted demo mode) answers from live plan records.");
  await glide(page, tid(page, "asst-open"), { click: true });
  const panel = tid(page, "asst-panel");
  await panel.waitFor();
  await glide(page, panel.getByTestId("asst-privacy-accept"), { click: true, optional: true });
  await panel.getByTestId("asst-input").click();
  await page.keyboard.type("Why is DO-MDV-1003 late and what can I do?", { delay: 40 });
  await glide(page, panel.getByTestId("asst-send"), { click: true });
  await page.waitForFunction(() => {
    const t = [...document.querySelectorAll('[data-testid="asst-turn"]')].pop();
    return t && /completed|failed/.test(t.getAttribute("data-status") ?? "");
  }, null, { timeout: 90_000 });
  await settle(page, 800);
  const turn = panel.getByTestId("asst-turn").last();
  await caption(page, "It cites the records it used, and proposes a draft action that the planner reviews; nothing is applied.");
  await glide(page, turn.getByTestId("asst-answer"));
  await hold(page, 3000);
  await glide(page, turn.getByTestId("asst-draft").first(), { optional: true });
  await hold(page, 4000);
  await page.keyboard.press("Escape").catch(() => undefined);
}

async function scenePhone(page) {
  await go(page, "/mfg");
  await caption(page, "Supervisors approve on the phone: purchase requests, suggested overtime and replan proposals.");
  await page.evaluate((base) => {
    const wrap = document.createElement("div");
    wrap.id = "sp-demo-phone";
    wrap.style.cssText = "position:fixed;inset:0;z-index:2147482000;background:var(--bg,#f3f4f6);display:flex;align-items:flex-start;justify-content:center;padding-top:28px";
    const f = document.createElement("iframe");
    f.src = `${base}/m/approvals`;
    f.style.cssText = "width:390px;height:640px;border:12px solid #161b26;border-radius:36px;background:#fff;box-shadow:0 20px 60px rgba(0,0,0,.25)";
    wrap.appendChild(f);
    document.body.appendChild(wrap);
  }, BASE);
  const phone = page.frameLocator("#sp-demo-phone iframe");
  await phone.getByTestId("m-approvals").waitFor({ timeout: 30_000 });
  await hold(page, 3000);
  const pr = phone.locator('[data-testid="m-approval"][data-kind="pr"]').first();
  if (await pr.count()) {
    await glide(page, pr.locator('[data-label="Approve"]'), { click: true });
    await hold(page, 3000);
  }
  await page.evaluate(() => document.getElementById("sp-demo-phone")?.remove());
}

async function sceneEnd(page) {
  await caption(page, "");
  await card(page, "SuperPlanner", ["Forecast, plan, schedule, release and trace production on one data model.", "Thank you for watching."],
    "Demo with fictional data. Features shown as implemented in the current build.", 7000 * PACE);
}

const SCENES = [
  ["title", sceneTitle],
  ["1-overview", sceneOverview],
  ["2-master-data", sceneMasterData],
  ["3-forecast", sceneForecast],
  ["4-safety-stock", sceneSafetyStock],
  ["5-mrp", sceneMrp],
  ["6-rate-plan", sceneRatePlan],
  ["7-schedule", sceneSchedule],
  ["8-sterilisation", sceneSterilisation],
  ["9-inspection-ncr", sceneInspection],
  ["10-capa", sceneCapa],
  ["11-floor", sceneFloor],
  ["12-trace-recall", sceneTrace],
  ["13-audit", sceneAudit],
  ["14-french", sceneFrench],
  ["15-validation", sceneValidation],
  ["16-assistant", sceneAssistant],
  ["17-phone", scenePhone],
  ["end", sceneEnd],
];

// ---------------------------------------------------------------- main

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const rawDir = path.join(OUT, ".raw");
  fs.rmSync(rawDir, { recursive: true, force: true });
  const servers = await startServers({ log: Boolean(process.env.DEMO_LOG), accounts: true });
  try {
    await setup();
    const browser = await chromium.launch();
    ctx.videoStart = Date.now();
    // sign in once (not recorded), then record in a context with that session and the plant workspace selected
    const login = await browser.newContext({ viewport: VIEW });
    const lp = await login.newPage();
    await lp.goto(`${BASE}/sign-in`);
    await lp.getByTestId("signin-email").fill(PLANNER.email);
    await lp.getByTestId("signin-password").fill(PASSWORD);
    await lp.getByTestId("signin-submit").click();
    await lp.getByTestId("account-menu").waitFor({ timeout: 30_000 });
    const state = await login.storageState();
    await login.close();
    const context = await browser.newContext({ viewport: VIEW, deviceScaleFactor: 1, storageState: state, recordVideo: { dir: rawDir, size: VIDEO } });
    await context.addInitScript(CAPTION_INIT);
    await context.addInitScript((ws) => {
      try {
        sessionStorage.setItem("sp.mfg.workspace", ws);
      } catch {
        /* ignore */
      }
    }, ctx.ownerId);
    const page = await context.newPage();
    const marks = [];
    const t0 = Date.now();
    for (const [name, fn] of SCENES) {
      if (ONLY && !ONLY.has(name) && !ONLY.has(name.split("-")[0])) continue;
      marks.push({ scene: name, at_s: (Date.now() - t0) / 1000 });
      console.log(`scene ${name} at ${((Date.now() - t0) / 1000).toFixed(1)} s`);
      try {
        await fn(page);
      } catch (e) {
        await page.screenshot({ path: path.join(OUT, `failed-${name}.png`) }).catch(() => undefined);
        throw e;
      }
    }
    marks.push({ scene: "end-of-video", at_s: (Date.now() - t0) / 1000 });
    const video = page.video();
    await context.close();
    await browser.close();
    const webm = path.join(OUT, "superplanner-demo.webm");
    fs.copyFileSync(await video.path(), webm);
    fs.writeFileSync(path.join(OUT, "scenes.json"), JSON.stringify(marks, null, 2));
    fs.rmSync(rawDir, { recursive: true, force: true });
    console.log(`video: ${webm}`);
    toMp4(webm, Math.max(0, (ctx.trimStart ?? 0) - 0.2));
  } finally {
    if (!args.includes("--keep-servers")) servers.stop();
  }
}

/**
 * Accounts mode (signatures need a person with a password): the plant owner signs up and loads the `meddev_m8` sample
 * (meddev + quality + planning layers); a fictional planner / QA approver is added as a member and enrols for
 * electronic signatures; a schedule is published so the dashboard has a plan. The video is recorded as that member.
 */
async function setup() {
  const owner = new Session();
  await owner.signUp("plant.owner@example.com", PASSWORD, "Plant owner");
  ctx.ownerId = owner.userId;
  useSession(owner);
  await api("POST", "/samples/meddev_m8/load", { replace: true, anchor: null });
  const me = new Session();
  await me.signUp(PLANNER.email, PASSWORD, PLANNER.name);
  await api("POST", "/members", { email: PLANNER.email, roles: ["plant_admin", "qa_approver", "qa_engineer"] });
  await me.raw("POST", `${API}/auth/esig/enroll`, { legal_name: PLANNER.name, password: PASSWORD, acknowledgement: true });
  me.workspace = owner.userId;
  useSession(me);
  const run = await api("POST", "/aps/runs", { label: "Overnight schedule" });
  const done = await waitRun("aps", run.id);
  await api("POST", `/aps/runs/${run.id}/publish`, {}, { "If-Match": `"${done.row_version}"` });
  await lookup();
}

function toMp4(webm, trim = 0) {
  try {
    const enc = execFileSync("ffmpeg", ["-hide_banner", "-encoders"], { encoding: "utf8" });
    if (!/libx264/.test(enc)) throw new Error("no libx264");
  } catch {
    console.log("ffmpeg with libx264 not found: keeping the .webm");
    return;
  }
  const mp4 = webm.replace(/\.webm$/, ".mp4");
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-ss", trim.toFixed(2), "-i", webm, "-vf", `scale=${OUT_SIZE.replace("x", ":")}:flags=lanczos`, "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4]);
  console.log(`video: ${mp4}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
