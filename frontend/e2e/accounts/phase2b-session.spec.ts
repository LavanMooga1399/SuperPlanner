/** Q6 / B 4.10 specs 4 + 5: change password signs out the other context; session-expiry banner and return. */
import { expect, test } from "@playwright/test";
import { createFromTemplate, watch } from "../helpers";
import { NEW_PASSWORD, PASSWORD, V1, session, signInUI, signUpUI, uniqueEmail, uniqueName } from "./accounts-helpers";

test("changing the password in one browser ends the session in the other; banner; sign in returns", async ({ page, browser }) => {
  const problems = watch(page, [/-> 401 /, /status of 401/]);
  const email = uniqueEmail("chpw");
  await signUpUI(page, email);
  const planId = await createFromTemplate(page, "project", uniqueName("chpw"));
  const here = `/plans/${planId}/tasks`;
  await expect(page).toHaveURL(new RegExp(`${here}$`));

  const ctx2 = await browser.newContext();
  const page2 = await ctx2.newPage();
  await signInUI(page2, email);
  await page2.goto("/account");
  await page2.getByTestId("pw-current").fill(PASSWORD);
  await page2.getByTestId("pw-new").fill(NEW_PASSWORD);
  await page2.getByTestId("pw-submit").click();
  await expect(page2.getByTestId("pw-success")).toBeVisible();
  // the browser that changed it stays signed in, with a new CSRF token that works
  const s2 = await session(page2.request);
  expect(s2.authenticated).toBe(true);
  const w = await page2.request.post(`${V1}/problems/${planId}/validate`, { headers: { "X-CSRF-Token": s2.csrf_token! } });
  expect(w.status()).toBe(200);
  await ctx2.close();

  // first browser: next action hits 401 -> banner, the page and its content stay
  await page.getByTestId("nav-scheduling").click();
  await expect(page.getByTestId("session-expired")).toBeVisible();
  await expect(page.getByTestId("session-expired")).toContainText(/Session ended/);
  await page.goto(here);
  await expect(page.getByTestId("session-expired").or(page.getByTestId("signin-email"))).toBeVisible();
  if (await page.getByTestId("session-expired").isVisible()) await page.getByTestId("session-expired-signin").click();
  await page.waitForURL(/\/sign-in\?next=/);
  expect(decodeURIComponent(new URL(page.url()).searchParams.get("next")!)).toBe(here);
  // old password no longer works; new one does and returns to the same page
  await page.getByTestId("signin-email").fill(email);
  await page.getByTestId("signin-password").fill(PASSWORD);
  await page.getByTestId("signin-submit").click();
  await expect(page.getByTestId("signin-error")).toBeVisible();
  await signInUI(page, email, NEW_PASSWORD);
  await page.waitForURL(new RegExp(`${here}$`));
  await expect(page.getByTestId("session-expired")).toHaveCount(0);
  expect(problems.pageErrors).toEqual([]);
});

test("a session that disappears while the page is open shows the banner on the next action", async ({ page }) => {
  const problems = watch(page, [/-> 401 /, /status of 401/]);
  const email = uniqueEmail("expire");
  await signUpUI(page, email);
  await page.goto("/finance");
  await page.getByTestId("disclaimer-accept").click();
  // server-side expiry is simulated by dropping the cookie (the server then sees no session at all)
  await page.context().clearCookies();
  await page.getByTestId("nav-scheduling").click();
  await expect(page.getByTestId("session-expired")).toBeVisible();
  await page.getByTestId("session-expired-signin").click();
  await page.waitForURL(/\/sign-in(\?next=%2F)?$/);
  await signInUI(page, email);
  await page.waitForURL(/127\.0\.0\.1:5174\/$/);
  await expect(page.getByTestId("plan-list")).toBeVisible();
  expect(problems.pageErrors).toEqual([]);
});
