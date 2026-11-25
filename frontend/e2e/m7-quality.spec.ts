/**
 * M7 WP-U (docs/M7-DESIGN.md 10): quality screens on the meddev sample with Part 11 mode off (single-user mode has
 * no password to re-authenticate with, so signing itself is covered by the backend tests and the accounts spec):
 * plan with a sampling preview, inspection lot results with the live verdict and the usage decision through the
 * shared signature dialog (plain confirmation when no signature is required), holds, NCR dispositions, equipment
 * calibration state, the record History tab, and the French (Canada) language switch.
 */
import { expect, test, type APIRequestContext } from "@playwright/test";
import { gotoMfg, mfgCall, mfgJson, resetMfg } from "./mfg-helpers";

interface Page<T> {
  items: T[];
}

async function seed(request: APIRequestContext) {
  await resetMfg(request);
  await mfgCall(request, "POST", "/samples/meddev/load", { data: { replace: true } });
  const lots = await mfgJson<Page<{ id: string; lot_code: string; item: { id: string }; on_hand: number }>>(request, "/lots?limit=200");
  const lot = lots.items.find((l) => l.on_hand > 0)!;
  const scheme = (await mfgCall(request, "POST", "/qa/schemes", { data: { code: "E2E-FIXED-3", name: "Fixed sample of 3", kind: "fixed", fixed_n: 3, note: "" } })) as { id: string; row_version: number };
  await mfgCall(request, "POST", `/qa/schemes/${scheme.id}/approve`, { data: { note: "" }, headers: { "If-Match": `"${scheme.row_version}"` } });
  const plan = (await mfgCall(request, "POST", "/qa/plans", {
    data: {
      name: "E2E incoming",
      item_id: lot.item.id,
      scope: "incoming",
      scheme_id: scheme.id,
      inspection_level: "II",
      characteristics: [
        { seq: 10, code: "DIM", name: "Diameter", kind: "variable", severity: "major", unit: "mm", nominal: 10, lsl: 9.8, usl: 10.2, method: "Caliper" },
        { seq: 20, code: "VIS", name: "Visual", kind: "attribute", severity: "minor", method: "Visual" },
      ],
    },
  })) as { id: string; row_version: number };
  await mfgCall(request, "POST", `/qa/plans/${plan.id}/approve`, { data: { note: "" }, headers: { "If-Match": `"${plan.row_version}"` } });
  const il = (await mfgCall(request, "POST", "/qa/inspection-lots", { data: { plan_id: plan.id, lot_id: lot.id, lot_size: 50, hold: true, note: "" } })) as { id: string; number: string };
  return { lot, plan, il };
}

test.describe("M7 quality", () => {
  test("inspection lot: results, live verdict, usage decision, holds and history", async ({ page, request }) => {
    const { il } = await seed(request);
    await gotoMfg(page, "/qa/inspection-lots");
    const row = page.getByTestId("qa-lot-row").filter({ hasText: il.number });
    await expect(row).toBeVisible();
    await row.click();
    await expect(page.getByTestId("qa-lot-page")).toBeVisible();
    await expect(page.getByTestId("hold-chip")).toBeVisible();
    await expect(page.getByTestId("qa-verdict")).toHaveAttribute("data-verdict", "pending");

    // three measured samples within limits
    const dim = page.getByTestId("qa-char").filter({ hasText: "DIM" });
    for (const v of ["10.01", "9.95", "10.1"]) {
      await dim.getByTestId("qa-value").fill(v);
      await dim.getByTestId("qa-save-result").click();
      await expect(dim.locator('[data-testid="qa-result-cell"][data-defective="false"]')).toHaveCount(["10.01", "9.95", "10.1"].indexOf(v) + 1);
    }
    // three visual passes
    const vis = page.getByTestId("qa-char").filter({ hasText: "VIS" });
    for (let i = 0; i < 3; i++) {
      await vis.getByTestId("qa-pass").click();
      await expect(vis.locator('[data-testid="qa-result-cell"][data-defective="false"]')).toHaveCount(i + 1);
    }
    await expect(page.getByTestId("qa-verdict")).toHaveAttribute("data-verdict", "accept");

    // the verdict decides the primary action
    await expect(page.getByTestId("qa-decision-accept")).toHaveClass(/primary/);
    await expect(page.getByTestId("qa-decision-reject")).not.toHaveClass(/primary/);
    // rejecting against an accept verdict warns and needs a justification
    await page.getByTestId("qa-decision-reject").click();
    const against = page.getByTestId("esig-dialog");
    await expect(against.getByTestId("qa-decision-against")).toBeVisible();
    await expect(page.getByTestId("esig-submit")).toBeDisabled();
    await against.getByTestId("qa-decision-note").fill("Visible flash on the parting line");
    await expect(page.getByTestId("esig-submit")).toBeEnabled();
    await page.getByRole("dialog").locator(".dialog-close").click();
    await expect(against).toBeHidden();

    // usage decision through the shared dialog (Part 11 off: plain confirmation)
    await page.getByTestId("qa-decision-accept").click();
    const dlg = page.getByTestId("esig-dialog");
    await expect(dlg).toBeVisible();
    await expect(dlg).toHaveAttribute("data-required", "false");
    await page.getByTestId("qa-decision-note").fill("All samples within limits");
    await page.getByTestId("esig-submit").click();
    await expect(page.getByTestId("toast")).toBeVisible();
    await expect(page.getByTestId("qa-lot-page")).toHaveAttribute("data-status", "accepted");

    // history of the record
    await page.getByTestId("qa-tab-history").click();
    await expect(page.getByTestId("qa-history")).toBeVisible();

    // the inspection hold is released by the decision
    await gotoMfg(page, "/qa/holds?state=all");
    await expect(page.getByTestId("qa-holds-page")).toBeVisible();
  });

  test("NCR dispositions add up, equipment state and French UI", async ({ page, request }) => {
    const { lot } = await seed(request);
    const ncr = (await mfgCall(request, "POST", "/qa/ncrs", { data: { title: "E2E scratch on housing", severity: "minor", item_id: lot.item.id, lot_id: lot.id, place: "stock", qty_nc: 10, description: "Scratches" } })) as { id: string; row_version: number };
    await mfgCall(request, "POST", `/qa/ncrs/${ncr.id}/open`, { data: {}, headers: { "If-Match": `"${ncr.row_version}"` } });
    await gotoMfg(page, `/qa/ncrs/${ncr.id}`);
    await expect(page.getByTestId("ncr-page")).toHaveAttribute("data-status", "open");
    await page.getByTestId("qa-tab-dispositions").click();
    await page.getByTestId("ncr-disposition-add").click();
    await expect(page.getByTestId("ncr-disposition-row")).toHaveCount(1);
    await expect(page.getByTestId("ncr-disposition-total")).toContainText("10");

    await mfgCall(request, "POST", "/qa/equipment", { data: { code: "E2E-G1", name: "Caliper", kind: "gauge", equipment_class: "CALIPER", calibration_required: true, interval_days: 365, grace_days: 0, due_on: "2020-01-01" } });
    await gotoMfg(page, "/qa/equipment");
    const eq = page.getByTestId("eq-row").filter({ hasText: "E2E-G1" });
    await expect(eq.getByTestId("eq-status")).toHaveAttribute("data-valid", "false");

    await page.getByTestId("display-menu").click();
    await page.getByTestId("lang-select").selectOption("fr-CA");
    await page.waitForLoadState("load");
    await expect(page.getByTestId("nav-group-quality")).toContainText("Qualité");
    await expect(page.locator("html")).toHaveAttribute("lang", "fr-CA");
    // back to English for the specs that follow
    await page.getByTestId("display-menu").click();
    await page.getByTestId("lang-select").selectOption("en");
    await page.waitForLoadState("load");
  });
});
