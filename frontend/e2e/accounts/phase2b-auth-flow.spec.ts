/** Q6 / B 4.10 specs 1-2: redirect + sign-up; sign-out, wrong password, `next`. */
import { expect, test } from "@playwright/test";
import { expectClean, watch } from "../helpers";
import { PASSWORD, V1, session, signInUI, signOutUI, signUpUI, uniqueEmail } from "./accounts-helpers";

test("anonymous visitor is sent to sign-in with next, signs up and lands on the page asked for", async ({ page }) => {
  const problems = watch(page);
  await page.goto("/finance");
  await page.waitForURL(/\/sign-in\?next=%2Ffinance$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  // no section links for an anonymous visitor
  await expect(page.getByTestId("nav-finance")).toHaveCount(0);
  await page.getByTestId("signin-to-signup").click();
  await page.waitForURL(/\/sign-up\?next=%2Ffinance$/);
  const email = uniqueEmail("signup");
  await signUpUI(page, email, PASSWORD, "Ana Tester");
  await page.waitForURL(/\/finance$/);
  const s = await session(page.request);
  expect(s.auth_mode).toBe("accounts");
  expect(s.authenticated).toBe(true);
  expect(s.user?.email).toBe(email);
  expect(s.csrf_token).toBeTruthy();
  // the session cookie is HttpOnly (not readable by page scripts)
  expect(await page.evaluate(() => document.cookie)).not.toContain("sp_session");
  const cookies = await page.context().cookies();
  const c = cookies.find((k) => k.name === "sp_session");
  expect(c?.httpOnly).toBe(true);
  expect(c?.sameSite).toBe("Lax");
  expectClean(problems);
});

test("sign-out revokes the session; wrong password is refused; sign-in returns to next", async ({ page, browser }) => {
  const problems = watch(page, [/POST \/auth\/sign-in -> 401/, /status of 401/]);
  const email = uniqueEmail("signout");
  await signUpUI(page, email);
  const before = (await page.context().cookies()).find((k) => k.name === "sp_session")!;
  await signOutUI(page);
  expect((await session(page.request)).authenticated).toBe(false);
  // the old cookie is dead server-side, not only deleted in this browser
  const other = await browser.newContext();
  await other.addCookies([{ ...before }]);
  const r = await other.request.get(`${V1}/auth/session`);
  expect((await r.json()).authenticated).toBe(false);
  const reuse = await other.request.get(`${V1}/problems`);
  expect(reuse.status()).toBe(401);
  await other.close();

  // protected page -> sign-in with next; wrong password -> alert, stays; right password -> next
  await page.goto("/new/project");
  await page.waitForURL(/\/sign-in\?next=%2Fnew%2Fproject$/);
  await page.getByTestId("signin-email").fill(email);
  await page.getByTestId("signin-password").fill("not the right password");
  await page.getByTestId("signin-submit").click();
  await expect(page.getByTestId("signin-error")).toBeVisible();
  await expect(page.getByTestId("signin-error")).toContainText(/email or password/i);
  expect(page.url()).toMatch(/\/sign-in\?next=%2Fnew%2Fproject$/);
  await signInUI(page, email);
  await page.waitForURL(/\/new\/project$/);
  expectClean(problems);
});

test("an off-site next is ignored after sign-in", async ({ page }) => {
  const email = uniqueEmail("next");
  await signUpUI(page, email);
  await signOutUI(page);
  await page.goto("/sign-in?next=%2F%2Fevil.example%2Fx");
  await signInUI(page, email);
  await expect(page).toHaveURL(/^http:\/\/127\.0\.0\.1:5174\/$/);
});
