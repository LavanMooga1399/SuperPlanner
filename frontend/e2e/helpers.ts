import { expect, type Page, type APIRequestContext } from "@playwright/test";

export const API = "http://127.0.0.1:8000/api/v1";

export type Problems = { apiErrors: string[]; pageErrors: string[]; consoleErrors: string[] };

/** Records every non-2xx /api response, uncaught page error and console error (contract mismatch detector). */
export function watch(page: Page, allowed: RegExp[] = []): Problems {
  const p: Problems = { apiErrors: [], pageErrors: [], consoleErrors: [] };
  page.on("response", async (r) => {
    const url = r.url();
    if (!url.includes("/api/v1/")) return;
    if (r.status() >= 400) {
      let body = "";
      try {
        body = (await r.text()).slice(0, 300);
      } catch {
        /* stream */
      }
      const line = `${r.request().method()} ${url.replace(/^.*\/api\/v1/, "")} -> ${r.status()} ${body}`;
      if (!allowed.some((re) => re.test(line))) p.apiErrors.push(line);
    }
  });
  page.on("pageerror", (e) => p.pageErrors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error" && !allowed.some((re) => re.test(m.text()))) p.consoleErrors.push(m.text());
  });
  return p;
}

export function expectClean(p: Problems) {
  expect(p.pageErrors, "uncaught page errors").toEqual([]);
  expect(p.apiErrors, "unexpected API errors").toEqual([]);
  expect(p.consoleErrors, "console errors").toEqual([]);
}

/** Create a plan from a template card on the Home page; returns the plan id. */
export async function createFromTemplate(page: Page, templateId: string, name: string): Promise<string> {
  await page.goto("/");
  const card = page.getByTestId(`template-card-${templateId}`);
  await expect(card).toBeVisible();
  await card.getByLabel("Plan name").fill(name);
  await card.getByRole("button", { name: "Create plan" }).click();
  await page.waitForURL(/\/plans\/p_[0-9a-f]+\/tasks/);
  const id = page.url().match(/\/plans\/(p_[0-9a-f]+)\//)![1];
  return id;
}

export async function gotoTab(page: Page, label: string | RegExp) {
  await page.getByRole("navigation", { name: "Plan sections" }).getByRole("link", { name: label }).click();
}

export async function validateReady(page: Page) {
  await gotoTab(page, "Validate");
  const st = page.getByTestId("validate-status");
  await expect(st).toBeVisible();
  await expect(st).toContainText(/Ready/);
  await expect(page.getByTestId("issue-list")).toBeVisible();
}

/** Start an optimization with the Quick budget and wait for the run to complete. Returns the run id. */
export async function optimize(page: Page): Promise<string> {
  await gotoTab(page, "Optimize");
  await page.getByRole("radio", { name: /Quick/ }).click();
  await page.getByTestId("start-run").click();
  const prog = page.getByTestId("run-progress");
  await expect(prog).toBeVisible();
  const runId = (await prog.getAttribute("data-run-id"))!;
  await expect(page.getByTestId("run-status")).toBeVisible();
  await expect(prog).toHaveAttribute("data-run-state", "completed", { timeout: 30_000 });
  await expect(page.getByTestId("run-status")).toContainText(/Completed|Done|Finished/i);
  return runId;
}

export async function openSchedule(page: Page) {
  await page.getByTestId("view-schedule").click();
  await page.waitForURL(/\/schedule\?id=sch_/);
  await expect(page.getByTestId("gantt")).toBeVisible();
  const bars = page.locator('[data-testid^="gantt-bar-"]');
  await expect(bars.first()).toBeVisible();
  return bars;
}

export async function approveCurrent(page: Page) {
  const btn = page.getByTestId("approve-button");
  await expect(btn).toBeEnabled();
  await btn.click();
  const dlg = page.getByRole("dialog");
  await expect(dlg).toBeVisible();
  await dlg.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByTestId("approval-banner")).toContainText("Approved on");
  await expect(page.getByTestId("schedule-status")).toHaveAttribute("data-status", "approved");
}

export async function apiJson(request: APIRequestContext, path: string) {
  const r = await request.get(`${API}${path}`);
  expect(r.ok(), `${path} -> ${r.status()}`).toBeTruthy();
  return r.json();
}
