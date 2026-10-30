/**
 * WP-D (M2-DESIGN 17.4 accounts/m2-roles, 18 #10): the owner adds a member with a role on the Members page; the
 * member switches to the owner's plant with the workspace switcher and sees the role badge; an action the role
 * allows is shown, the server's 403 (role changed meanwhile) shows the forbidden banner, and after the downgrade
 * the action is hidden; the API answers 403 MFG_FORBIDDEN with `details.permission`.
 */
import { expect, test } from "@playwright/test";
import { expectClean, watch } from "../helpers";
import { gotoMfg, loadSample, mfgCall, mfgJson, mfgPut, resetMfg } from "../mfg-helpers";
import { session, signUpUI, uniqueEmail } from "./accounts-helpers";

const ACC = { accounts: true } as const;

type Member = { id: string; row_version: number; roles: string[]; user: { email: string } };

test("owner adds a planner; member switches workspace; downgrade to viewer gives the 403 banner and hides Run", async ({ page, browser }) => {
  test.setTimeout(240_000);
  // the member needs an existing account first
  const ctxM = await browser.newContext();
  const pageM = await ctxM.newPage();
  const memberEmail = uniqueEmail("m2-member");
  await signUpUI(pageM, memberEmail);

  const problems = watch(page);
  await signUpUI(page, uniqueEmail("m2-owner"));
  const ownerId = (await session(page.request)).user!.id;
  await resetMfg(page.request, ACC);
  await loadSample(page.request, "small", false, ACC);

  // --- owner: Members page -> add the member as planner
  await gotoMfg(page, "/settings/members");
  await expect(page.getByTestId("members-page")).toBeVisible();
  await page.getByTestId("member-add").click();
  await page.getByTestId("member-email").fill(memberEmail);
  await page.getByTestId("member-role-planner").check();
  await page.getByTestId("member-role-viewer").uncheck();
  await page.getByTestId("member-form-submit").click();
  const row = page.locator(`[data-testid="member-row"][data-email="${memberEmail}"]`);
  await expect(row).toBeVisible();
  await expect(row).toHaveAttribute("data-roles", "planner");
  expectClean(problems);

  // --- member: switch to the owner's plant
  const problemsM = watch(pageM, [/-> 403 /, /status of 403/]);
  await gotoMfg(pageM, "");
  const switcher = pageM.getByTestId("workspace-switcher");
  await expect(switcher).toBeVisible();
  await switcher.selectOption(ownerId);
  await pageM.waitForURL(/\/mfg$/);
  await expect(pageM.getByTestId("role-badge")).toHaveAttribute("data-roles", "planner");
  await expect(pageM.getByTestId("workspace-switcher")).toHaveValue(ownerId);
  // the owner's sample data is what the member sees (API with the workspace header; the UI sends it itself)
  const items = (await mfgCall(pageM.request, "GET", "/items?q=SM-100&limit=5", {
    headers: { "X-SP-Workspace": ownerId }, ...ACC,
  })) as { items: { part_number: string }[] };
  expect(items.items.map((i) => i.part_number)).toContain("SM-100");

  // a planner may run MRP: the action is shown; open the form
  await gotoMfg(pageM, "/mrp");
  await expect(pageM.getByTestId("mrp-new-run")).toBeVisible();
  await pageM.getByTestId("mrp-new-run").click();
  await expect(pageM.getByTestId("mrp-run-submit")).toBeVisible();

  // owner downgrades the member to viewer while the form is open
  const members = await mfgJson<{ items: Member[] }>(page.request, "/members", ACC);
  const m = members.items.find((x) => x.user.email === memberEmail)!;
  await mfgPut(page.request, `/members/${m.id}`, { roles: ["viewer"], active: true }, m.row_version, ACC);

  // member submits: the server refuses (403) and the UI shows the forbidden banner
  await pageM.getByTestId("mrp-run-submit").click();
  await expect(pageM.getByTestId("forbidden-banner")).toBeVisible();
  await expect(pageM.getByTestId("forbidden-banner")).toContainText(/role|allow/i);

  // after a reload the action is hidden, the badge says viewer, Members is owner-only
  await pageM.reload();
  await expect(pageM.getByTestId("role-badge")).toHaveAttribute("data-roles", "viewer");
  await expect(pageM.getByTestId("mrp-new-run")).toHaveCount(0);
  await gotoMfg(pageM, "/settings/members");
  await expect(pageM.getByTestId("forbidden-banner")).toBeVisible();
  await expect(pageM.getByTestId("member-add")).toHaveCount(0);

  // the API enforces it as well: 403 MFG_FORBIDDEN naming the permission
  const err = (await mfgCall(pageM.request, "POST", "/mrp/runs", {
    data: {}, headers: { "X-SP-Workspace": ownerId }, status: 403, ...ACC,
  })) as { error: { code: string; details: { permission: string; roles_allowed: string[] } } };
  expect(err.error.code).toBe("MFG_FORBIDDEN");
  expect(err.error.details.permission).toBe("mrp_run");
  expect(err.error.details.roles_allowed).not.toContain("viewer");
  // only the expected 403s happened on the member's side
  expect(problemsM.pageErrors).toEqual([]);
  expect(problemsM.consoleErrors.filter((c) => !/403/.test(c))).toEqual([]);
  await ctxM.close();
});
