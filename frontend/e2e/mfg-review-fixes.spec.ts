/**
 * M1 review fixes (tester D4, lead review F8-F10, F2 follow-up): BOM tab loads the explosion once per input, a
 * replaced BOM component takes its own unit, unsaved routing edits block Release / Copy / Obsolete, a commit
 * refused because the data changed after the preview shows the row errors, and the health page renders an
 * unfamiliar issue code with the server's link.
 */
import { test, expect, type Page } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { findItem, gotoMfg, loadSample, mfgCall, mfgJson, resetMfg, uploadImportFile } from "./mfg-helpers";

test.beforeEach(async ({ request }) => {
  await resetMfg(request);
});

/** Completed GET /explosion responses of this page (aborted requests never produce a response). */
function countExplosions(page: Page): { n: number; urls: string[] } {
  const c = { n: 0, urls: [] as string[] };
  page.on("response", (r) => {
    if (r.request().method() === "GET" && /\/mfg\/items\/[^/]+\/explosion/.test(r.url())) {
      c.n++;
      c.urls.push(r.url());
    }
  });
  return c;
}

test("D4: the BOM tab fetches the explosion once per input change", async ({ page, request }) => {
  await loadSample(request, "small");
  const top = await findItem(request, "SM-100");
  const problems = watch(page);
  const ex = countExplosions(page);
  await gotoMfg(page, `/items/${top.id}/bom`);
  await expect(page.getByTestId("bom-totals")).toBeVisible();
  await page.waitForTimeout(1_000);
  expect(ex.n, ex.urls.join("\n")).toBe(1);
  // switching the mode is one more request, not two or three
  await page.getByTestId("bom-mode-summarized").click();
  await expect.poll(() => ex.n).toBe(2);
  await page.waitForTimeout(1_000);
  expect(ex.n, ex.urls.join("\n")).toBe(2);
  expectClean(problems);
});

test("F8: replacing a BOM line's component takes the new component's unit unless an explicit unit fits", async ({ page, request }) => {
  await loadSample(request, "small");
  const top = await findItem(request, "SM-100");
  await mfgCall(request, "POST", "/items", { data: { part_number: "E2E-CABLE", make_buy: "buy", uom: "M", lead_time_days: 7, description: "E2E cable" }, status: 201 });
  await mfgCall(request, "POST", "/items", { data: { part_number: "E2E-CABLE2", make_buy: "buy", uom: "M", lead_time_days: 7, description: "E2E cable 2" }, status: 201 });
  const boms = await mfgJson<{ items: { id: string; status: string; row_version: number }[] }>(request, `/items/${top.id}/boms`);
  const rel = boms.items.find((b) => b.status === "released")!;
  const draft = (await mfgCall(request, "POST", `/boms/${rel.id}/copy`, { data: { revision: null }, headers: { "If-Match": `"${rel.row_version}"` }, status: 201 })) as { id: string };
  const problems = watch(page);
  await gotoMfg(page, `/items/${top.id}/bom/${draft.id}/edit`);
  const row = page.getByTestId("bom-line-row").first();
  const unit = row.locator('select[aria-label="Unit, line 1"]');
  await expect(unit).toHaveValue("EA");

  // EA part replaced by a cable in M: the line follows the cable's unit
  const pick = async (pn: string) => {
    await row.getByTestId("bom-line-child").fill(pn);
    await page.getByRole("option", { name: new RegExp(`^${pn}\\b`) }).first().click();
    await expect(row.getByTestId("bom-line-child")).toHaveValue(pn);
  };
  await pick("E2E-CABLE");
  await expect(unit).toHaveValue("M");
  // an explicit unit of the same dimension (MM) survives a switch to another cable in M ...
  await unit.selectOption("MM");
  await pick("E2E-CABLE2");
  await expect(unit).toHaveValue("MM");
  // ... but not a switch to a part counted in EA
  await pick("SM-BPCB-100");
  await expect(unit).toHaveValue("EA");
  await pick("E2E-CABLE");
  await expect(unit).toHaveValue("M");
  await page.getByTestId("bom-save").click();
  await expect.poll(async () => (await mfgJson<{ lines: { child: { part_number: string }; uom: string }[] }>(request, `/boms/${draft.id}`)).lines.map((l) => `${l.child.part_number} ${l.uom}`)).toContain("E2E-CABLE M");
  expectClean(problems);
});

test("F9: unsaved operation edits disable Release / Copy / Obsolete and ask before switching routing", async ({ page, request }) => {
  await loadSample(request, "small");
  const top = await findItem(request, "SM-100");
  const problems = watch(page);
  await gotoMfg(page, `/items/${top.id}/routing`);
  await page.getByTestId("routing-copy-banner").click();
  await expect(page.getByTestId("routing-save")).toBeVisible();
  const list = (await mfgJson<{ items: { id: string; status: string }[] }>(request, `/items/${top.id}/routings`)).items;
  const draft = list.find((r) => r.status === "draft")!;
  const released = list.find((r) => r.status === "released")!;
  const draftRow = page.getByTestId(`routing-version-${draft.id}`);
  const relRow = page.getByTestId(`routing-version-${released.id}`);
  await expect(draftRow.getByTestId("routing-release")).toBeEnabled();

  const name = page.getByTestId("op-name").first();
  const original = await name.inputValue();
  await name.fill(`${original} (edited)`);
  await expect(page.getByTestId("routing-unsaved-hint")).toBeVisible();
  await expect(draftRow.getByTestId("routing-release")).toBeDisabled();
  await expect(draftRow.getByTestId("routing-copy")).toBeDisabled();
  await expect(draftRow.getByTestId("routing-delete")).toBeDisabled();
  await expect(relRow.getByTestId("routing-copy")).toBeDisabled();
  await expect(relRow.getByTestId("routing-obsolete")).toBeDisabled();
  await expect(page.getByTestId("routing-new")).toBeDisabled();

  // picking another routing asks first; Cancel keeps the edits
  await relRow.getByRole("button").first().click();
  const dlg = page.getByRole("dialog", { name: "Discard unsaved changes?" });
  await expect(dlg).toBeVisible();
  await dlg.getByRole("button", { name: "Cancel" }).click();
  await expect(name).toHaveValue(`${original} (edited)`);
  await expect(page.getByTestId("routing-readonly")).toHaveCount(0);

  // saving re-enables the actions and the saved name stays
  await page.getByTestId("routing-save").click();
  await expect(page.getByTestId("routing-unsaved-hint")).toHaveCount(0);
  await expect(draftRow.getByTestId("routing-release")).toBeEnabled();
  await expect.poll(async () => (await mfgJson<{ operations: { name: string }[] }>(request, `/routings/${draft.id}`)).operations[0].name).toBe(`${original} (edited)`);
  await expect(page.getByTestId("op-name").first()).toHaveValue(`${original} (edited)`);

  // edit again, discard by switching: the released routing opens, the draft keeps its saved state
  await page.getByTestId("op-name").first().fill("Throwaway");
  await relRow.getByRole("button").first().click();
  await page.getByRole("dialog", { name: "Discard unsaved changes?" }).getByRole("button", { name: "Discard changes" }).click();
  await expect(page.getByTestId("routing-readonly")).toBeVisible();
  await expect(page.getByTestId("routing-unsaved-hint")).toHaveCount(0);
  await expect(relRow.getByTestId("routing-copy")).toBeEnabled();
  expectClean(problems);
});

test("F10: a commit refused because the data changed after the preview shows the row errors and keeps commit disabled", async ({ page, request }) => {
  await mfgCall(request, "POST", "/items", { data: { part_number: "E2E-PAR", make_buy: "make", uom: "EA", description: "E2E parent" }, status: 201 });
  const child = (await mfgCall(request, "POST", "/items", { data: { part_number: "E2E-EXT", make_buy: "buy", uom: "EA", lead_time_days: 5, description: "E2E external part" }, status: 201 })) as { id: string; row_version: number };
  const problems = watch(page, [/\/commit -> 409 .*MFG_IMPORT_HAS_ERRORS/, /status of 409/]);
  await uploadImportFile(page, "bom.csv", "parent_part_number,find_number,child_part_number,qty_per\nE2E-PAR,10,E2E-EXT,2\n", "bom_lines");
  await expect(page.getByTestId("import-stepper")).toHaveAttribute("data-step", "map");
  await page.getByTestId("import-preview-submit").click();
  await expect(page.getByTestId("import-preview")).toHaveAttribute("data-ok", "true");
  await expect(page.getByText("Ready to import")).toBeVisible();
  await expect(page.getByTestId("import-commit")).toBeEnabled();

  // the component disappears between preview and commit
  await mfgCall(request, "DELETE", `/items/${child.id}`, { headers: { "If-Match": `"${child.row_version}"` } });
  const commit = page.waitForResponse((r) => r.url().endsWith("/commit") && r.request().method() === "POST");
  await page.getByTestId("import-commit").click();
  expect((await commit).status()).toBe(409);
  await expect(page.getByTestId("import-has-errors")).toBeVisible();
  await expect(page.getByTestId("import-has-errors")).toContainText("The data changed after the preview");
  await expect(page.getByText("Ready to import")).toHaveCount(0);
  await expect(page.getByTestId("import-preview")).toHaveAttribute("data-ok", "false");
  await expect(page.getByTestId("import-row-error").first()).toBeVisible();
  const codes = await page.getByTestId("import-row-error").evaluateAll((rs) => rs.map((r) => r.getAttribute("data-code")));
  expect(codes).toContain("IMP_UNKNOWN_REFERENCE");
  await expect(page.getByTestId("import-commit")).toBeDisabled();
  await expect(page.getByTestId("import-stepper")).toHaveAttribute("data-step", "preview");
  // nothing was imported
  expect((await mfgJson<{ items: unknown[] }>(request, `/items/${(await findItem(request, "E2E-PAR")).id}/boms`)).items).toHaveLength(0);
  expectClean(problems);
});

test("health page renders an unfamiliar issue code and severity with the server's link (F2 follow-up)", async ({ page, request }) => {
  await loadSample(request, "small");
  const asg = (await mfgJson<{ items: { id: string; target: { code: string } }[] }>(request, "/shift-assignments")).items[0];
  const link = `/mfg/plant/shifts?assignment=${asg.id}`;
  const problems = watch(page);
  await page.route(/\/api\/v1\/mfg\/health(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: false,
        as_of: "2026-11-02",
        horizon_days: 90,
        fingerprint: "0123456789abcdef0123456789abcdef",
        counts: { error: 1, warning: 0, info: 1 },
        by_code: { MFG_ASSIGNMENT_UNKNOWN_SHIFT: 1, MFG_SOMETHING_NEWER: 1 },
        truncated: false,
        data_version: 1,
        issues: [
          {
            code: "MFG_ASSIGNMENT_UNKNOWN_SHIFT",
            severity: "error",
            message: `An assignment of ${asg.target.code} names a shift "Night" that its template does not have.`,
            fix: "Untick the unknown shift or rename it in the template.",
            entity: { type: "shift_assignment", id: asg.id, label: asg.target.code },
            related: [],
            link,
            field: "shift_names",
          },
          { code: "MFG_SOMETHING_NEWER", severity: "notice", message: "A check this UI does not know yet.", fix: "", entity: { type: "future_thing", id: null, label: "x" }, related: [], link: null, field: null },
        ],
      }),
    });
  });
  await gotoMfg(page, "/health");
  await expect(page.getByTestId("health-status")).toHaveAttribute("data-ok", "false");
  const issue = page.locator('[data-testid="health-issue"][data-code="MFG_ASSIGNMENT_UNKNOWN_SHIFT"]');
  await expect(issue).toContainText('names a shift "Night"');
  await expect(page.locator('[data-testid="health-issue"][data-code="MFG_SOMETHING_NEWER"]')).toBeVisible();
  await expect(page.locator('[data-testid="health-code-chip"][data-code="MFG_ASSIGNMENT_UNKNOWN_SHIFT"]')).toBeVisible();
  await expect(issue.getByTestId("health-fix-link")).toHaveAttribute("href", link);
  await issue.getByTestId("health-fix-link").click();
  await expect(page).toHaveURL(new RegExp(`/mfg/plant/shifts\\?assignment=${asg.id}$`));
  await expect(page.getByRole("dialog", { name: "Edit shift assignment" })).toBeVisible();
  await expect(page.locator(`[data-testid="assignment-row"][data-assignment-id="${asg.id}"]`)).toHaveClass(/mfg-selected/);
  expectClean(problems);
});
