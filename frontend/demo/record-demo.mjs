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
import { BASE, CAPTION_INIT, api, caption, card, frontendDir, glide, settle, startServers, uncard, waitRun } from "./lib.mjs";

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
const PACE = Number(opt("pace", 1.2)); // multiply every hold

const hold = (page, ms) => page.waitForTimeout(ms * PACE);
const tid = (page, id) => page.getByTestId(id);

/** Data the scenes share (ids looked up through the API once the sample is loaded). */
const ctx = {};

async function lookup() {
  const item = async (pn) => (await api("GET", `/items?q=${encodeURIComponent(pn)}&limit=50`)).items.find((i) => i.part_number === pn);
  const doc = async (coll, no) => (await api("GET", `${coll}?q=${encodeURIComponent(no)}&limit=50`)).items.find((d) => d.number === no);
  ctx.ivs = await item("MDV-IVS-20");
  ctx.pp = await item("MDV-RES-PP");
  ctx.rush = await doc("/demand-orders", "DO-MDV-1003");
  ctx.wo1 = await doc("/work-orders", "WO-MDV-0001");
  ctx.lines = (await api("GET", "/lines?limit=200")).items;
  ctx.groups = (await api("GET", "/groups?limit=200")).items;
  ctx.ops = (await api("GET", `/work-orders/${ctx.wo1.id}/operations`)).items;
}

/** Navigate: client-side (history + popstate, no reload and no blank frame) once the app is open, else a page load. */
async function go(page, url) {
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
    "Products modelled on a typical medical-device portfolio. All names, customers and suppliers are fictional.", 0);
  ctx.trimStart = (Date.now() - ctx.videoStart) / 1000;
  await settle(page, 0);
  await hold(page, 7000);
  await uncard(page);
}

async function sceneOverview(page) {
  await caption(page, "The plant: a fictional single-use medical-device site with moulding, cleanroom assembly, EtO sterilisation and QC release.");
  await hold(page, 2500);
  await glide(page, tid(page, "mfg-count-items"), { optional: true });
  await hold(page, 2500);
  await go(page, "/mfg/dashboard");
  await tid(page, "tile-otd").waitFor({ timeout: 30_000 });
  await settle(page, 800);
  await caption(page, "The plant dashboard: on-time delivery, load against capacity, material risk and execution in one view.");
  await glide(page, tid(page, "tile-otd").getByTestId("tile-status"), { scroll: false });
  await hold(page, 3500);
  await glide(page, tid(page, "tile-material_risk").getByTestId("tile-status"), { scroll: false });
  await caption(page, "Material risk lists the items short within four weeks and the demand lines they make late.");
  await hold(page, 3500);
  await glide(page, tid(page, "tile-execution").getByTestId("tile-status"), { scroll: false });
  await caption(page, "Execution figures come from shop-floor reporting: first-pass yield, scrap rate and equipment use.");
  await hold(page, 3500);
}

async function sceneMasterData(page) {
  await go(page, `/mfg/items/${ctx.ivs.id}/bom`);
  await caption(page, "Master data: the IV administration set's BOM, with moulded drip chamber and spike, extruded tubing and bought-in parts.");
  await hold(page, 2000);
  await page.mouse.wheel(0, 260);
  await hold(page, 4000);
  await go(page, `/mfg/items/${ctx.ivs.id}/routing`);
  await caption(page, "Its routing: cleanroom assembly, leak test, packaging and labelling, EtO sterilisation with aeration, then a QC release hold.");
  await hold(page, 6000);
  await go(page, "/mfg/plant/setups");
  await caption(page, "Mould changeovers: press setup times depend on the mould family that ran before.");
  await hold(page, 4500);
}

async function sceneMrp(page) {
  await go(page, "/mfg/demand");
  await caption(page, "Demand from fictional provincial purchasing groups, hospitals and distributors, in units.");
  await hold(page, 4000);
  await go(page, "/mfg/mrp");
  await caption(page, "Run MRP: net requirements through the BOM against stock lots, open orders and lead times.");
  await glide(page, tid(page, "mrp-new-run"), { click: true });
  await tid(page, "mrp-run-form").waitFor();
  await page.getByTestId("mrp-label").fill("Weekly MRP");
  await hold(page, 800);
  await glide(page, tid(page, "mrp-run-submit"), { click: true });
  await page.waitForURL(/\/mfg\/mrp\/runs\/[^/]+/, { timeout: 120_000 });
  await tid(page, "run-summary").waitFor({ timeout: 120_000 });
  await settle(page);
  ctx.mrpRunId = /runs\/([^/?#]+)/.exec(page.url())[1];
  await caption(page, "Late demand is listed with why it is late: the limiting part and the reason, down the BOM.");
  await glide(page, tid(page, "run-late-demand"));
  await hold(page, 6000);
  await glide(page, tid(page, "run-exception-codes"));
  await caption(page, "Exceptions: expedite and defer messages for purchase orders, expiring lots, past-due supply.");
  await hold(page, 4500);
  await go(page, `/mfg/mrp/runs/${ctx.mrpRunId}/planned`);
  await caption(page, "Planned work orders and purchase requests, with release dates, ready to convert.");
  await hold(page, 4500);
  await go(page, "/mfg/shortages");
  await caption(page, "Shortages across the plan, with the supply that would cover them.");
  await hold(page, 4000);
}

async function sceneSchedule(page) {
  await go(page, "/mfg/schedule");
  await caption(page, "Finite-capacity scheduling on shifts: three shifts on the presses, two in assembly, EtO around the clock.");
  await glide(page, tid(page, "aps-new-run"), { click: true });
  await tid(page, "aps-run-form").waitFor();
  await tid(page, "aps-label").fill("Weekly schedule");
  await hold(page, 800);
  await glide(page, tid(page, "aps-run-submit"), { click: true });
  await page.waitForURL(/\/mfg\/schedule\/runs\/[^/]+/, { timeout: 120_000 });
  await tid(page, "aps-summary").waitFor({ timeout: 120_000 });
  await settle(page);
  ctx.apsRunId = /runs\/([^/?#]+)/.exec(page.url())[1];
  await hold(page, 2500);
  await glide(page, tid(page, "aps-tab-gantt"), { click: true });
  await tid(page, "gantt-canvas").waitFor();
  await settle(page);
  await caption(page, "The Gantt by line: assembly lines, presses with mould changeovers, EtO chambers running batch loads.");
  await hold(page, 4500);
  const grp = (code) => ctx.groups.find((g) => g.code === code)?.id;
  await glide(page, tid(page, "gantt-group"));
  await tid(page, "gantt-group").selectOption(grp("MOULD"));
  await settle(page, 600);
  await caption(page, "Injection moulding: six presses on three shifts; changeovers depend on the mould family before.");
  await hold(page, 5000);
  await tid(page, "gantt-group").selectOption(grp("STER"));
  await settle(page, 600);
  await caption(page, "EtO sterilisation: batch loads per chamber, followed by aeration before QC release.");
  await hold(page, 5000);
  await tid(page, "gantt-group").selectOption(grp("ASSY"));
  await settle(page, 600);
  await caption(page, "Dashed outlines are overtime the scheduler suggests where work would otherwise be late.");
  await hold(page, 4000);
  await glide(page, tid(page, "aps-tab-overtime"), { click: true });
  await settle(page);
  await caption(page, "Each suggested shift states its cost and the lateness it saves.");
  await hold(page, 5000);
  const allow = tid(page, "aps-rerun-allow");
  if (await allow.count()) {
    await caption(page, "Re-run allowing overtime, then compare the two plans side by side.");
    await glide(page, allow, { click: true });
    await page.waitForURL(/\/compare/, { timeout: 120_000 });
    await tid(page, "aps-tradeoff").waitFor({ timeout: 120_000 });
    await settle(page);
    await caption(page, "The trade-off: late demand and priority-weighted lateness against overtime hours and cost.");
    await glide(page, tid(page, "aps-tradeoff"));
    await hold(page, 6000);
    await caption(page, "Here the planner publishes the plan without overtime; the suggested shifts go to supervisors to approve.");
    await glide(page, tid(page, "aps-publish-base"), { click: true });
    await page.getByRole("dialog").waitFor();
    await hold(page, 1200);
    await glide(page, page.getByRole("dialog").getByRole("button", { name: "Publish" }), { click: true });
    await settle(page);
    await caption(page, "Published: this plan now drives dispatch lists, the shop-floor queues and the phone app.");
    await hold(page, 3500);
  }
}

async function sceneFloor(page) {
  const asmLine = ctx.lines.find((l) => l.code === "ASM-01");
  await go(page, "/mfg/floor");
  await caption(page, "The shop-floor tablet: the operator picks the line and signs in with a badge scan.");
  await hold(page, 1500);
  const tile = page.locator('[data-testid="floor-line-pick"][data-code="ASM-01"]');
  await glide(page, tile, { click: true });
  await tid(page, "floor-line-title").waitFor();
  await settle(page, 800);
  await tid(page, "floor-crew").click();
  await page.keyboard.type("OP:OP-010\n", { delay: 60 });
  await hold(page, 2000);
  const op = ctx.ops.find((o) => o.seq === 20);
  await caption(page, "Scanning the traveller opens the operation: 10 mL syringe assembly, with its components and lots.");
  await tid(page, "floor-crew").click();
  await page.keyboard.type(`${ctx.wo1.number}/${op.seq}\n`, { delay: 60 });
  await tid(page, "floor-op").waitFor();
  await settle(page, 1500);
  await glide(page, tid(page, "floor-action-start"), { click: true });
  await page.waitForFunction(() => document.querySelector('[data-testid="floor-op"]')?.getAttribute("data-status") === "running", null, { timeout: 20_000 });
  await caption(page, "Start, report quantities as they are made, and complete; components are backflushed first-expiry-first by lot.");
  await hold(page, 1500);
  await glide(page, tid(page, "floor-action-report"), { click: true });
  await tid(page, "floor-qty-good").fill("24000");
  await hold(page, 1200);
  await glide(page, tid(page, "floor-qty-submit"), { click: true });
  await settle(page, 1500);
  await glide(page, tid(page, "floor-action-complete"), { click: true });
  await hold(page, 1500);
  await glide(page, tid(page, "floor-qty-submit"), { click: true });
  await settle(page, 1500);
  await caption(page, "A line stop is reported in two taps; the planner sees it and can replan.");
  await go(page, `/mfg/floor/lines/${asmLine.id}/downtime`);
  await glide(page, tid(page, "downtime-kind-breakdown"), { click: true });
  await tid(page, "downtime-reason").fill("Heat-sealer temperature alarm");
  await hold(page, 1200);
  await glide(page, tid(page, "downtime-submit"), { click: true });
  await settle(page, 2500);
}

async function sceneTrace(page) {
  await go(page, "/mfg/trace");
  await caption(page, "Traceability: enter a finished lot of IV sets and trace it back.");
  await tid(page, "trace-code").fill("WO-MDV-H03");
  await hold(page, 800);
  await glide(page, tid(page, "trace-find"), { click: true });
  await tid(page, "trace-tree").waitFor({ timeout: 30_000 });
  await settle(page);
  await caption(page, "Back to the drip-chamber and tubing lots, and to the resin, solvent and label supplier lots.");
  await glide(page, tid(page, "trace-tree"));
  await hold(page, 6000);
  await go(page, `/mfg/trace/where-used?item=${ctx.pp.id}&supplier_lot=RSN-PP-88412`);
  await caption(page, "Where used: one resin supplier lot went into IV sets and 10 mL syringes, shipped to three customers.");
  await hold(page, 5000);
  await glide(page, tid(page, "whereused-recall"), { click: true });
  await tid(page, "recall-new").waitFor();
  await hold(page, 1200);
  await glide(page, tid(page, "recall-create"), { click: true });
  await tid(page, "recall-page").waitFor({ timeout: 30_000 });
  await settle(page);
  await caption(page, "The recall report: affected work orders, lots, shipments and customers, exportable.");
  await hold(page, 5000);
  await glide(page, tid(page, "recall-quarantine"));
  await caption(page, "Stock still on hand is moved to quarantine and put on hold in one step.");
  await glide(page, tid(page, "quarantine-run"), { click: true });
  await page.getByRole("dialog").waitFor();
  await hold(page, 1200);
  await glide(page, page.getByRole("dialog").getByRole("button").last(), { click: true });
  await settle(page, 3000);
}

async function sceneEco(page) {
  // a change request with a draft copy of the IV set's BOM (made through the API for brevity)
  const eco = await api("POST", "/eco", { title: "IV set: switch roller clamp supplier part", reason: "Second source for the roller clamp", kind: "eco", priority: 2, effectivity: { mode: "date", date: null }, note: "" });
  const boms = (await api("GET", `/items/${ctx.ivs.id}/boms`)).items;
  const rel = boms.find((b) => b.status === "released") ?? boms[0];
  const draft = await api("POST", `/boms/${rel.id}/copy`, { revision: null }, { "If-Match": `"${rel.row_version}"` });
  await api("POST", `/eco/${eco.id}/items`, { doc_type: "bom", doc_id: draft.id, disposition: { open_wos: "flag", open_pos: "flag_cancel", stock: "use_up" } });
  await go(page, `/mfg/eco/${eco.id}`);
  await caption(page, "Engineering change: the draft BOM is held by the change request until it is approved and implemented.");
  await hold(page, 4000);
  await glide(page, tid(page, "eco-tab-impact"), { click: true });
  await tid(page, "eco-impact").waitFor({ timeout: 60_000 });
  await settle(page);
  await caption(page, "Impact analysis: the orders that use the old structure, purchases no longer needed and parts being phased out.");
  await hold(page, 5500);
  await go(page, "/mfg/audit");
  await caption(page, "Every change is recorded in the audit trail, with who, when and what, and can be exported.");
  await hold(page, 5000);
}

async function sceneAssistant(page) {
  await go(page, `/mfg/demand/${ctx.rush.id}`);
  await caption(page, "The planning assistant (scripted demo mode) answers from live plan data.");
  await glide(page, tid(page, "asst-open"), { click: true });
  const panel = tid(page, "asst-panel");
  await panel.waitFor();
  await hold(page, 1000);
  const accept = panel.getByTestId("asst-privacy-accept");
  if (await accept.count()) {
    await glide(page, accept, { click: true });
    await hold(page, 600);
  }
  await panel.getByTestId("asst-input").click();
  await page.keyboard.type("Why is DO-MDV-1003 late and what can I do?", { delay: 45 });
  await hold(page, 600);
  await glide(page, panel.getByTestId("asst-send"), { click: true });
  const turn = panel.getByTestId("asst-turn").last();
  await page.waitForFunction(() => {
    const t = [...document.querySelectorAll('[data-testid="asst-turn"]')].pop();
    return t && /completed|failed/.test(t.getAttribute("data-status") ?? "");
  }, null, { timeout: 90_000 });
  await settle(page, 800);
  await caption(page, "The answer is built from live plan records, with a draft action the planner reviews and applies; nothing changes on its own.");
  await glide(page, turn.getByTestId("asst-answer"));
  await hold(page, 5000);
  const draft = turn.getByTestId("asst-draft").first();
  if (await draft.count()) {
    await glide(page, draft);
    await hold(page, 4000);
  }
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
  await hold(page, 3500);
  const pr = phone.locator('[data-testid="m-approval"][data-kind="pr"]').first();
  if (await pr.count()) {
    await glide(page, pr.locator('[data-label="Approve"]'), { click: true });
    await hold(page, 3000);
  }
  const ot = phone.locator('[data-testid="m-approval"][data-kind="overtime"]').first();
  if (await ot.count()) {
    await caption(page, "Accepting a suggested shift re-runs the schedule with it, for the planner to compare and publish.");
    await glide(page, ot, { optional: true });
    await hold(page, 3500);
  }
  await page.evaluate(() => document.getElementById("sp-demo-phone")?.remove());
}

async function sceneEnd(page) {
  await caption(page, "");
  await card(page, "SuperPlanner", ["Plan, schedule, run and trace production on one data model.", "Thank you for watching."],
    "Demo with fictional data. Features shown as implemented in the current build.", 7000 * PACE);
}

const SCENES = [
  ["title", sceneTitle],
  ["1-overview", sceneOverview],
  ["2-master-data", sceneMasterData],
  ["3-mrp", sceneMrp],
  ["4-schedule", sceneSchedule],
  ["5-floor", sceneFloor],
  ["6-trace", sceneTrace],
  ["7-eco-audit", sceneEco],
  ["8-assistant", sceneAssistant],
  ["9-phone", scenePhone],
  ["end", sceneEnd],
];

// ---------------------------------------------------------------- main

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const rawDir = path.join(OUT, ".raw");
  fs.rmSync(rawDir, { recursive: true, force: true });
  const servers = await startServers({ log: Boolean(process.env.DEMO_LOG) });
  try {
    // fresh database: load the sample, then the plan the dashboard reads (MRP + a published schedule)
    await api("POST", "/samples/meddev/load", { replace: true, anchor: null });
    const mrp = await api("POST", "/mrp/runs", { label: "Overnight MRP" });
    await waitRun("mrp", mrp.id);
    const run = await api("POST", "/aps/runs", { label: "Overnight schedule" });
    const done = await waitRun("aps", run.id);
    await api("POST", `/aps/runs/${run.id}/publish`, {}, { "If-Match": `"${done.row_version}"` });
    await lookup();

    const browser = await chromium.launch();
    ctx.videoStart = Date.now();
    const context = await browser.newContext({ viewport: VIEW, deviceScaleFactor: 1, recordVideo: { dir: rawDir, size: VIDEO } });
    await context.addInitScript(CAPTION_INIT);
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
