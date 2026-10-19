import { expect, type APIRequestContext, type Page, type Request } from "@playwright/test";
import { API } from "./helpers";

export const INTAKE = `${API}/intake`;

/** PHASE2 2.15 example texts (also the Describe page placeholders for project and money). */
export const SCHEDULE_TEXT =
  "Website relaunch starting next Monday. Ravi and Priya are on the team.\n" +
  "1. Gather requirements - 2-3 days (Priya)\n2. Design 1 week, after requirements, Priya\n" +
  "3. Build the site: 2 weeks, Ravi\n4. Testing 3-5 days once the build is done\n5. Launch by 15 Dec 2026";
export const FINANCE_TEXT =
  "I'm 34, take home about 1.2 lakh a month and my wife earns 60k. Household costs are 70-80k a month, " +
  "school fees 18k every quarter. Car loan EMI 10k, about 3 lakh left at 9%. We have 6 lakh in savings " +
  "and 8L in mutual funds. We want 15 lakh for a flat down payment in 3 years and to retire at 60. Moderate risk.";
export const TSV =
  "Task\tDuration\tAfter\tOwner\tDue\nRequirements\t2-3 d\t\tPriya\t\nDesign\t1 w\tRequirements\tPriya\t\n" +
  "Build\t2 w\tDesign\tRavi\t15/12/2026";

/** Records every POST that would save a plan (nothing may be saved before "Create plan", P3b-7). */
export function watchSaves(page: Page): Request[] {
  const saves: Request[] = [];
  page.on("request", (r) => {
    if (r.method() !== "POST") return;
    const u = r.url();
    if (/\/api\/v1\/problems$/.test(u) || /\/api\/v1\/finance\/plans$/.test(u)) saves.push(r);
  });
  return saves;
}

/** Bodies of intake requests (to check `use_ai`). */
export function watchIntake(page: Page): { url: string; body: any }[] {
  const out: { url: string; body: any }[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/api/v1/intake/")) {
      let body: any = null;
      try {
        body = r.postDataJSON();
      } catch {
        body = r.postData();
      }
      out.push({ url: r.url(), body });
    }
  });
  return out;
}

export async function intakeKeys(page: Page): Promise<string[]> {
  return page.evaluate(() => Object.keys(sessionStorage).filter((k) => k.startsWith("sp.intake.")));
}

/** Answer every open question with its suggestion ("Use suggestions for all remaining", then one by one). */
export async function acceptAllSuggestions(page: Page) {
  const all = page.getByTestId("intake-use-all-defaults");
  if (await all.isVisible().catch(() => false)) await all.click();
  for (let i = 0; i < 30; i++) {
    if (await page.getByTestId("intake-no-questions").isVisible().catch(() => false)) return;
    const use = page.getByTestId("intake-use-default");
    if (await use.isVisible().catch(() => false)) {
      await use.click();
      await page.waitForTimeout(300);
      continue;
    }
    await page.waitForTimeout(300);
  }
  await expect(page.getByTestId("intake-no-questions")).toBeVisible();
}

/** Press Tab until the element with `testId` has focus (keyboard-only navigation). */
export async function tabTo(page: Page, testId: string, max = 250) {
  for (let i = 0; i < max; i++) {
    const cur = await page.evaluate(() => document.activeElement?.getAttribute("data-testid") ?? "");
    if (cur === testId) return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`could not reach ${testId} with Tab`);
}

export async function apiGet(request: APIRequestContext, path: string) {
  const r = await request.get(`${API}${path}`);
  expect(r.ok(), `${path} -> ${r.status()}`).toBeTruthy();
  return r.json();
}
