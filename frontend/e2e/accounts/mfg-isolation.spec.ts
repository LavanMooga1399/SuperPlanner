/**
 * WP-D (M1-DESIGN 15.4 accounts/mfg-isolation): user A's Manufacturing data is invisible to user B in the UI and
 * the API; B's own sample load, edits and import wizard upload work with the CSRF header; B's reset leaves A alone.
 */
import { expect, test } from "@playwright/test";
import { expectClean, watch } from "../helpers";
import { findItem, gotoMfg, loadSample, mfgCall, mfgJson, resetMfg, uploadImportFile } from "../mfg-helpers";
import { expect404, signUpUI, uniqueEmail } from "./accounts-helpers";

const ACC = { accounts: true } as const;

test("user B cannot see user A's manufacturing data; B's own work (incl. an import) is separate", async ({ page, browser }) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  await signUpUI(page, uniqueEmail("mfg-a"));
  await resetMfg(page.request, ACC);
  // A loads the small sample in the UI (POST with the CSRF header from the app)
  await gotoMfg(page, "");
  await page.getByTestId("sample-load-small").click();
  await expect(page.getByTestId("mfg-count-items")).toContainText("10");
  const top = await findItem(page.request, "SM-100", ACC);
  const boms = await mfgJson<{ items: { id: string }[] }>(page.request, `/items/${top.id}/boms`, ACC);
  const routings = await mfgJson<{ items: { id: string }[] }>(page.request, `/items/${top.id}/routings`, ACC);
  const groups = await mfgJson<{ items: { id: string }[] }>(page.request, "/groups", ACC);
  const exportA = await page.request.get("/api/v1/mfg/export?format=zip");
  expect(exportA.status()).toBe(200);
  const exportBytesA = await exportA.body();
  expectClean(problems);

  // user B in a separate browser context
  const ctxB = await browser.newContext();
  const pageB = await ctxB.newPage();
  const problemsB = watch(pageB, [/-> 404 /, /status of 404/]);
  await signUpUI(pageB, uniqueEmail("mfg-b"));
  await gotoMfg(pageB, "");
  await expect(pageB.getByTestId("mfg-count-items")).toContainText("0");
  await pageB.getByTestId("mfg-subnav-items").click();
  await expect(pageB.getByTestId("items-row")).toHaveCount(0);
  // A's item / BOM / routing / stage URLs are "not found" for B
  for (const url of [`/mfg/items/${top.id}`, `/mfg/items/${top.id}/bom?bom=${boms.items[0].id}`, `/mfg/items/${top.id}/routing?routing=${routings.items[0].id}`]) {
    await pageB.goto(url);
    await expect(pageB.getByTestId("mfg-not-found")).toBeVisible();
    await expect(pageB.getByText("SM-100")).toHaveCount(0);
  }
  await pageB.goto(`/mfg/plant/groups?group=${groups.items[0].id}`);
  await expect(pageB.getByTestId("group-row")).toHaveCount(0);
  // and 404 by direct API GET
  for (const p of [`/mfg/items/${top.id}`, `/mfg/boms/${boms.items[0].id}`, `/mfg/routings/${routings.items[0].id}`, `/mfg/groups/${groups.items[0].id}`, `/mfg/items/${top.id}/explosion`]) {
    await expect404(pageB.request, p);
  }

  // B: own sample (same part numbers, no clash), an import wizard upload through the UI (CSRF), a reset
  await loadSample(pageB.request, "small", false, ACC);
  const topB = await findItem(pageB.request, "SM-100", ACC);
  expect(topB.id).not.toBe(top.id);
  await uploadImportFile(pageB, "b-items.csv", "part_number,make_buy,lead_time_days,description\nB-ONLY-1,buy,3,Only for B\n", "items");
  await expect(pageB.getByTestId("import-stepper")).toHaveAttribute("data-step", "map");
  await pageB.getByTestId("import-preview-submit").click();
  await expect(pageB.getByTestId("import-preview")).toHaveAttribute("data-ok", "true");
  await pageB.getByTestId("import-commit").click();
  await expect(pageB.getByTestId("import-result")).toBeVisible();
  await expect.poll(async () => (await mfgJson<{ total: number }>(pageB.request, "/items?q=B-ONLY", ACC)).total).toBe(1);
  // an unsafe call without the CSRF header is refused
  const noCsrf = await pageB.request.post("/api/v1/mfg/reset", { data: { confirm: "DELETE ALL MANUFACTURING DATA" } });
  expect(noCsrf.status()).toBe(403);
  await mfgCall(pageB.request, "POST", "/reset", { data: { confirm: "DELETE ALL MANUFACTURING DATA" }, ...ACC });
  expect((await mfgJson<{ counts: { items: number } }>(pageB.request, "/summary", ACC)).counts.items).toBe(0);
  expectClean(problemsB);
  await ctxB.close();

  // A is untouched: nothing of B's, export byte-identical, and A never sees B's import
  expect((await mfgJson<{ total: number }>(page.request, "/items?q=B-ONLY", ACC)).total).toBe(0);
  const again = await page.request.get("/api/v1/mfg/export?format=zip");
  expect(Buffer.compare(await again.body(), exportBytesA)).toBe(0);
  await gotoMfg(page, "/health");
  await expect(page.getByTestId("health-status")).toHaveAttribute("data-ok", "true");
});

test("anonymous visitors are sent to sign-in and the mfg API answers 401", async ({ page }) => {
  const r = await page.request.get("/api/v1/mfg/summary");
  expect(r.status()).toBe(401);
  await page.goto("/mfg/items");
  await page.waitForURL(/\/sign-in/);
});
