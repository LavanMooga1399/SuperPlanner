/** Q6: CSRF in accounts mode - every SPA write carries the session's token; writes without it are rejected. */
import { expect, test, type Request } from "@playwright/test";
import { createFromTemplate, expectClean, watch } from "../helpers";
import { V1, session, signUpUI, uniqueEmail, uniqueName } from "./accounts-helpers";

test("SPA writes carry X-CSRF-Token; writes without it or from a foreign Origin get 403 and change nothing", async ({ page }) => {
  // only the deliberate in-page forged fetch below may fail
  const problems = watch(page, [/POST \/templates\/project\/instantiate -> 403/, /status of 403/]);
  const writes: Request[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/v1/") && ["POST", "PUT", "PATCH", "DELETE"].includes(r.method())) writes.push(r);
  });
  await signUpUI(page, uniqueEmail("csrf"));
  const s = await session(page.request);
  const token = s.csrf_token!;
  const planId = await createFromTemplate(page, "manufacturing", uniqueName("csrf"));
  // a scheduling write from the editor and a finance write
  await page.goto("/finance");
  await page.getByTestId("disclaimer-accept").click();
  const card = page.getByTestId("fin-template-card-family");
  await card.getByLabel("Plan name").fill(uniqueName("csrf fin"));
  await card.getByRole("button", { name: "Create plan" }).click();
  await page.waitForURL(/\/finance\/fp_[0-9a-f]+\/setup\/profile/);
  const appWrites = writes.filter((r) => !/\/auth\/sign-(in|up)$/.test(r.url()));
  expect(appWrites.length).toBeGreaterThanOrEqual(2);
  for (const r of appWrites) expect(r.headers()["x-csrf-token"], `${r.method()} ${r.url()}`).toBe(token);

  const count = async () => (await (await page.request.get(`${V1}/problems`)).json()).items.length;
  const before = await count();
  const body = { name: "forged", start_date: "2026-10-19" };
  const url = `${V1}/templates/project/instantiate`;
  const forged = [
    await page.request.post(url, { data: body }),
    await page.request.post(url, { data: body, headers: { "X-CSRF-Token": "wrong" } }),
    await page.request.post(url, { data: body, headers: { "X-CSRF-Token": token, Origin: "https://evil.example" } }),
    await page.request.delete(`${V1}/problems/${planId}`),
  ];
  for (const r of forged) {
    expect(r.status()).toBe(403);
    expect((await r.json()).error.code).toBe("CSRF_FAILED");
  }
  // same from page script (fetch with the cookie, no token)
  const status = await page.evaluate(async (u) => (await fetch(u, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" })).status, url);
  expect(status).toBe(403);
  expect(await count()).toBe(before);
  expect((await page.request.get(`${V1}/problems/${planId}`)).status()).toBe(200);
  // with the token it works
  const ok = await page.request.post(url, { data: body, headers: { "X-CSRF-Token": token } });
  expect(ok.status()).toBe(201);
  expect(await count()).toBe(before + 1);
  expectClean(problems);
});
