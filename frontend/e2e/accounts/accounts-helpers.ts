/**
 * Q6 accounts-mode e2e helpers (PHASE2B 4.10). Run with `npm run e2e:accounts` (API :8001 AUTH_MODE=accounts,
 * Vite :5174). Every API call goes through the Vite origin so it carries the browser context's session cookie.
 */
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const V1 = "/api/v1";
export const PASSWORD = "correct horse battery staple";
export const NEW_PASSWORD = "another quite long passphrase";

export function uniqueEmail(tag: string): string {
  return `e2e-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

export function uniqueName(tag: string): string {
  return `E2E 2b ${tag} ${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
}

export async function signUpUI(page: Page, email: string, password = PASSWORD, displayName?: string) {
  if (!/\/sign-up/.test(page.url())) await page.goto("/sign-up");
  if (displayName) await page.getByTestId("signup-name").fill(displayName);
  await page.getByTestId("signup-email").fill(email);
  await page.getByTestId("signup-password").fill(password);
  await page.getByTestId("signup-submit").click();
  await expect(page.getByTestId("account-menu")).toBeVisible();
}

export async function signInUI(page: Page, email: string, password = PASSWORD) {
  if (!/\/sign-in/.test(page.url())) await page.goto("/sign-in");
  await page.getByTestId("signin-email").fill(email);
  await page.getByTestId("signin-password").fill(password);
  await page.getByTestId("signin-submit").click();
  await expect(page.getByTestId("account-menu")).toBeVisible();
}

export async function signOutUI(page: Page) {
  await page.getByTestId("account-menu").click();
  await page.getByTestId("sign-out").click();
  await page.waitForURL(/\/sign-in$/);
}

export type SessionInfo = {
  auth_mode: string;
  authenticated: boolean;
  user: { id: string; email: string | null; display_name: string | null } | null;
  csrf_token: string | null;
};

export async function session(request: APIRequestContext): Promise<SessionInfo> {
  const r = await request.get(`${V1}/auth/session`);
  expect(r.status()).toBe(200);
  return r.json();
}

/** A write through the context's cookie jar with the current CSRF token. */
export async function authedPost(request: APIRequestContext, path: string, data: unknown) {
  const s = await session(request);
  return request.post(`${V1}${path}`, { data, headers: { "X-CSRF-Token": s.csrf_token ?? "" } });
}

export async function waitTerminal(request: APIRequestContext, path: string, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const r = await request.get(`${V1}${path}`);
    expect(r.status(), `${path} -> ${r.status()}`).toBe(200);
    const run = await r.json();
    if (run.status !== "queued" && run.status !== "running") return run;
    if (Date.now() > deadline) throw new Error(`${path} still ${run.status}`);
    await new Promise((res) => setTimeout(res, 250));
  }
}

/** Expect the reply of a stranger's GET to be the plain 404 NOT_FOUND envelope. */
export async function expect404(request: APIRequestContext, path: string) {
  const r = await request.get(`${V1}${path}`);
  expect(r.status(), `${path} -> ${r.status()} ${await r.text()}`).toBe(404);
  const body = await r.json();
  expect(body.error.code).toBe("NOT_FOUND");
}
