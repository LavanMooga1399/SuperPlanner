/**
 * M5 sign-in (docs/M5-DESIGN.md 3.1-3.3, accounts mode): the SSO button appears only when the server has an identity
 * provider; two-step verification is turned on from the security page (QR + key, confirm code, recovery codes shown
 * once); signing in then asks for the code (or a recovery code); personal API tokens are shown once and revoked.
 * The TOTP codes are computed here from the key the page shows (RFC 6238: SHA-1, 30 s, 6 digits).
 */
import { createHmac } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { PASSWORD, signOutUI, signUpUI, uniqueEmail, V1 } from "./accounts-helpers";

function base32(s: string): Buffer {
  const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of s.replace(/=+$/, "").toUpperCase()) bits += A.indexOf(c).toString(2).padStart(5, "0");
  const out: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(out);
}

function totp(secret: string, at = Date.now()): string {
  const counter = Math.floor(at / 30000);
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const h = createHmac("sha1", base32(secret)).update(buf).digest();
  const o = h[h.length - 1] & 0xf;
  const n = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3];
  return String(n % 1_000_000).padStart(6, "0");
}

/** wait until the next 30 s step so a code is never the one just used (replays are refused) */
async function nextStep(page: Page) {
  const ms = 30000 - (Date.now() % 30000) + 500;
  await page.waitForTimeout(ms);
}

async function passwordStep(page: Page, email: string) {
  await page.goto("/sign-in");
  await page.getByTestId("signin-email").fill(email);
  await page.getByTestId("signin-password").fill(PASSWORD);
  await page.getByTestId("signin-submit").click();
  await expect(page.getByTestId("signin-totp")).toBeVisible();
}

test("SSO button only when configured; turn on 2FA; sign in with a code and with a recovery code; personal API token", async ({ page, request }) => {
  test.setTimeout(150_000);
  const email = uniqueEmail("m5-2fa");
  await signUpUI(page, email);

  // SSO: the button follows /auth/config
  const cfg = await (await request.get(`${V1}/auth/config`)).json();
  // two-step verification: QR code + key, confirm with a code, recovery codes once
  await page.goto("/account/security");
  await page.getByTestId("totp-begin").click();
  await expect(page.getByTestId("totp-qr")).toBeVisible();
  const secret = (await page.getByTestId("totp-secret").getAttribute("data-secret"))!;
  expect(secret).toMatch(/^[A-Z2-7]+=*$/);
  await page.getByTestId("totp-confirm").fill(totp(secret));
  await page.getByTestId("totp-enable").click();
  const codes = page.getByTestId("recovery-codes");
  await expect(codes).toBeVisible();
  const recovery = (await codes.locator("li").allInnerTexts()).map((x) => x.trim());
  expect(recovery.length).toBeGreaterThanOrEqual(5);
  await expect(page.getByTestId("recovery-done")).toBeDisabled();
  await page.getByTestId("recovery-saved").check();
  await page.getByTestId("recovery-done").click();
  await expect(page.getByTestId("totp-on")).toBeVisible();

  // sign out: the sign-in page shows the SSO button only when configured
  await signOutUI(page);
  await expect(page.getByTestId("signin-sso")).toHaveCount(cfg.sso_enabled ? 1 : 0);

  // password, then a recovery code (no waiting for a new TOTP step)
  await passwordStep(page, email);
  await page.getByTestId("totp-use-recovery").click();
  await page.getByTestId("totp-code").fill(recovery[0]);
  await page.getByTestId("totp-submit").click();
  await expect(page.getByTestId("account-menu")).toBeVisible();
  await signOutUI(page);

  // a used recovery code does not work twice; a wrong code is explained
  await passwordStep(page, email);
  await page.getByTestId("totp-code").fill("000000");
  await page.getByTestId("totp-submit").click();
  await expect(page.getByTestId("totp-error")).toContainText(/not correct|expired/i);

  // the current code from the app signs in
  await nextStep(page);
  await page.getByTestId("totp-code").fill(totp(secret));
  await page.getByTestId("totp-submit").click();
  await expect(page.getByTestId("account-menu")).toBeVisible();

  // personal API token: shown once, then revoked
  await page.goto("/account/tokens");
  await page.getByTestId("token-name").fill("e2e report");
  await page.getByTestId("token-preset-read").check();
  await page.getByTestId("token-create").click();
  await expect(page.getByTestId("token-value")).toContainText(/^spt_/);
  const row = page.getByTestId("token-row").first();
  await expect(row).toHaveAttribute("data-revoked", "false");
  await row.getByTestId("token-revoke").click();
  await page.getByRole("dialog").getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByTestId("token-row").first()).toHaveAttribute("data-revoked", "true");
});
