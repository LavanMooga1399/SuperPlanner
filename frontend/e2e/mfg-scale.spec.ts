/**
 * WP-D (M1-DESIGN 15.4 mfg-scale, 12 P12/P13): Kavach BOM tree (~2,470 rows) and a 10,000-item list on the real
 * API. Asserts the DOM stays windowed (<= 80 rows) and records the timings ([mfg-perf] lines in the output).
 */
import { test, expect, type Page } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { bomTreeShown, domRowCount, findItem, gotoMfg, loadSample, mfgCall, resetMfg, scrollVirtualToEnd, MFG_DIRECT } from "./mfg-helpers";

test.beforeEach(async ({ request }) => {
  await resetMfg(request);
});

async function startLongTaskObserver(page: Page): Promise<void> {
  await page.evaluate(() => {
    const w = window as unknown as { __long: number[] };
    w.__long = [];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) w.__long.push(e.duration);
    }).observe({ type: "longtask", buffered: false });
  });
}

async function longTasks(page: Page): Promise<number[]> {
  return page.evaluate(() => (window as unknown as { __long: number[] }).__long);
}

test("Kavach BOM tree: interactive after data arrives, expand all, scroll to the end, <= 80 DOM rows (P12)", async ({ page, request }) => {
  test.setTimeout(180_000);
  await loadSample(request, "kavach");
  const top = await findItem(request, "KV-TPU-1000");
  const problems = watch(page);
  const explosionCalls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/explosion")) explosionCalls.push(r.url());
  });
  await gotoMfg(page, "");
  const responded = page.waitForResponse((r) => r.url().includes(`/items/${top.id}/explosion`) && r.status() === 200);
  await page.goto(`/mfg/items/${top.id}/bom`);
  await responded;
  const tData = await page.evaluate(() => performance.now());
  await expect(page.getByTestId("bom-tree-row").first()).toBeVisible();
  const tInteractive = await page.evaluate(() => performance.now());
  await page.waitForLoadState("networkidle");
  const { total } = await bomTreeShown(page);
  expect(total).toBeGreaterThanOrEqual(2300);
  expect(await domRowCount(page, "bom-tree-row")).toBeLessThanOrEqual(80);

  // Expand all: time from click to the footer showing every row
  await startLongTaskObserver(page);
  const tExpand = await page.evaluate(() => {
    const t0 = performance.now();
    (document.querySelector('[data-testid="bom-expand-all"]') as HTMLButtonElement).click();
    return new Promise<number>((resolve) => {
      const check = () => {
        const f = document.querySelector('[data-testid="bom-tree"] .vt-footer')?.textContent ?? "";
        const m = f.replace(/,/g, "").match(/(\d+) of (\d+)/);
        if (m && m[1] === m[2]) resolve(performance.now() - t0);
        else requestAnimationFrame(check);
      };
      check();
    });
  });
  expect(await bomTreeShown(page)).toEqual({ shown: total, total });
  expect(await domRowCount(page, "bom-tree-row")).toBeLessThanOrEqual(80);

  // Scroll through the whole tree in steps; never more than 80 DOM rows, no long task > 100 ms
  const scroller = page.getByTestId("bom-tree").locator(".vt-scroll");
  let maxDom = 0;
  for (let i = 0; i <= 40; i++) {
    await scroller.evaluate((el, k) => {
      el.scrollTop = (el.scrollHeight * k) / 40;
    }, i);
    await page.waitForTimeout(16);
    maxDom = Math.max(maxDom, await domRowCount(page, "bom-tree-row"));
  }
  await scrollVirtualToEnd(page, "bom-tree");
  const last = page.locator(`[data-testid="bom-tree-row"][data-row="${total - 1}"]`);
  await expect(last).toBeVisible();
  maxDom = Math.max(maxDom, await domRowCount(page, "bom-tree-row"));
  const lt = await longTasks(page);
  const longest = lt.length ? Math.max(...lt) : 0;
  console.log(
    `[mfg-perf] P12 Kavach tree: ${total} rows; data->first row ${(tInteractive - tData).toFixed(0)} ms; ` +
      `expand all ${tExpand.toFixed(1)} ms; max DOM rows ${maxDom}; long tasks while expanding/scrolling ${lt.length} (max ${longest.toFixed(0)} ms); ` +
      `explosion requests on open ${explosionCalls.length}`,
  );
  expect(maxDom).toBeLessThanOrEqual(80);
  expect(tInteractive - tData).toBeLessThan(1000);
  expect(tExpand).toBeLessThan(100);
  expect(longest).toBeLessThanOrEqual(100);

  // collapse all -> the root and its direct children; expand to level 2 via the level select
  await page.getByTestId("bom-collapse-all").click();
  const lvl1 = (await mfgCall(request, "GET", `/items/${top.id}/explosion`)) as { rows: { level: number }[] };
  const direct = lvl1.rows.filter((r) => r.level <= 1).length;
  await expect.poll(() => bomTreeShown(page)).toEqual({ shown: direct, total });
  await page.getByTestId("bom-expand-level").selectOption("2");
  const upTo2 = lvl1.rows.filter((r) => r.level <= 2).length;
  await expect.poll(() => bomTreeShown(page)).toEqual({ shown: upTo2, total });

  // search reveals a deep match: the programmed CPU MCU blank (level 4)
  const deep = (lvl1.rows as { level: number; part_number: string }[]).find((r) => r.level === 4)!;
  await page.getByTestId("bom-search").fill(deep.part_number);
  await page.getByTestId("bom-search").press("Enter");
  await expect(page.locator(`[data-testid="bom-tree-row"][data-part-number="${deep.part_number}"]`).first()).toBeVisible();
  expect(await domRowCount(page, "bom-tree-row")).toBeLessThanOrEqual(80);
  expectClean(problems);
});

test("Kavach where-used of the most shared capacitor and the items list (10+ parents, windowed)", async ({ page, request }) => {
  await loadSample(request, "kavach");
  const cap = await findItem(request, "KV-CAP-0402-100N");
  const problems = watch(page);
  await gotoMfg(page, `/items/${cap.id}/where-used`);
  await expect(page.getByTestId("whereused-row").first()).toBeVisible();
  expect(await domRowCount(page, "whereused-row")).toBeGreaterThanOrEqual(10);
  await page.getByTestId("whereused-mode-indented").click();
  await expect(page.locator('[data-testid="whereused-row"][data-part-number="KV-TPU-1000"]').first()).toBeAttached({ timeout: 20_000 });
  expect(await domRowCount(page, "whereused-row")).toBeLessThanOrEqual(80);
  expectClean(problems);
});

test("items list with 10,000 items: first page < 1 s, paging by 200, <= 80 DOM rows (P13)", async ({ page, request }) => {
  test.setTimeout(180_000);
  const rows = Array.from({ length: 10_000 }, (_, i) => `P13-${String(i).padStart(5, "0")},buy,${i % 90},Part number ${i}`).join("\n");
  const r = await request.post(`${MFG_DIRECT}/imports?filename=items.csv&sheet=items`, {
    data: Buffer.from(`part_number,make_buy,lead_time_days,description\n${rows}\n`),
    headers: { "content-type": "application/octet-stream" },
  });
  expect(r.status()).toBe(201);
  const rec = (await r.json()) as { id: string; sheets: { suggested: unknown }[] };
  const mapped = (await mfgCall(request, "PUT", `/imports/${rec.id}/mapping`, {
    data: { sheets: { items: rec.sheets[0].suggested }, options: {} },
    headers: { "If-Match": '"1"' },
  })) as { row_version: number };
  await mfgCall(request, "POST", `/imports/${rec.id}/commit`, { data: {}, headers: { "If-Match": `"${mapped.row_version}"` } });

  const problems = watch(page);
  await gotoMfg(page, "");
  await page.waitForLoadState("networkidle"); // the overview runs /health on open; measure the list alone
  const t0 = Date.now();
  await page.getByTestId("mfg-subnav-items").click();
  await expect(page.getByTestId("items-row").first()).toBeVisible();
  const firstPage = Date.now() - t0;
  await expect(page.getByTestId("items-count")).toContainText("10,000");
  expect(await domRowCount(page, "items-row")).toBeLessThanOrEqual(80);
  // a full page load straight to the URL (dev server: unbundled modules, so informational only)
  const t1 = Date.now();
  await page.goto("/mfg/items");
  await expect(page.getByTestId("items-row").first()).toBeVisible();
  const cold = Date.now() - t1;

  const pages: string[] = [];
  page.on("request", (q) => {
    if (/\/mfg\/items\?/.test(q.url())) pages.push(q.url());
  });
  let maxDom = 0;
  for (let i = 0; i < 6; i++) {
    await scrollVirtualToEnd(page, "items-table");
    await page.waitForTimeout(250);
    maxDom = Math.max(maxDom, await domRowCount(page, "items-row"));
  }
  const offsets = pages.map((u) => new URL(u).searchParams.get("offset"));
  console.log(`[mfg-perf] P13 items list 10,000: first page via nav ${firstPage} ms, cold load ${cold} ms; page requests ${offsets.join(",")}; max DOM rows ${maxDom}`);
  expect(firstPage).toBeLessThan(1000);
  expect(maxDom).toBeLessThanOrEqual(80);
  expect(offsets.length).toBeGreaterThanOrEqual(3);
  expect(offsets.every((o) => Number(o) % 200 === 0)).toBeTruthy();
  for (const u of pages) expect(new URL(u).searchParams.get("limit")).toBe("200");
  expectClean(problems);
});
