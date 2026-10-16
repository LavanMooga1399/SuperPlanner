import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { API } from "./helpers";

export const FIN = `${API}/finance`;
export const DISCLAIMER_START = "SuperPlanner Finance is an educational planning tool.";
export const STEPS = ["profile", "income", "debts", "savings", "goals", "assumptions", "review"] as const;
export const STEP_LABELS = ["Profile", "Income & expenses", "Debts", "Savings & holdings", "Goals", "Risk & assumptions", "Review"];

/** Unique plan names per test (criterion 4.6). */
export function uniqueName(tag: string): string {
  return `E2E fin ${tag} ${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
}

/** The first-visit dialog appears on any /finance route in a fresh context; accept it (F.21 rule 2). */
export async function acceptDisclaimer(page: Page) {
  const btn = page.getByTestId("disclaimer-accept");
  await expect(btn).toBeVisible();
  await btn.click();
  await expect(btn).toBeHidden();
}

export function currentUtcMonth(): string {
  const d = new Date();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export async function apiPost(request: APIRequestContext, path: string, body: unknown, status = 201) {
  const r = await request.post(`${FIN}${path}`, { data: body });
  expect(r.status(), `${path} -> ${r.status()} ${await r.text()}`).toBe(status);
  return r.json();
}

export async function finJson(request: APIRequestContext, path: string) {
  const r = await request.get(`${FIN}${path}`);
  expect(r.ok(), `${path} -> ${r.status()}`).toBeTruthy();
  return r.json();
}

/** Instantiate a template through the API (fast setup for tests that start on the results page). */
export async function instantiate(request: APIRequestContext, templateId: string, name: string, parameters: Record<string, number> = {}) {
  return apiPost(request, `/templates/${templateId}/instantiate`, { name, start_month: currentUtcMonth(), parameters });
}

export async function waitRun(request: APIRequestContext, runId: string, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const run = await finJson(request, `/runs/${runId}`);
    if (run.status !== "queued" && run.status !== "running") return run;
    if (Date.now() > deadline) throw new Error(`finance run ${runId} still ${run.status}`);
    await new Promise((r) => setTimeout(r, 200));
  }
}

/** Template plan with a completed baseline result, created through the API. */
export async function planWithResult(request: APIRequestContext, templateId: string, name: string) {
  const rec = await instantiate(request, templateId, name);
  const created = await apiPost(request, `/plans/${rec.id}/runs`, { seed: 1 }, 202);
  const run = await waitRun(request, created.run_id);
  expect(run.status).toBe("completed");
  return { planId: rec.id as string, resultId: run.result_id as string, run };
}

/** Results page with charts and goal cards rendered. */
export async function expectDashboard(page: Page, goalIds: string[]) {
  for (const g of goalIds) {
    const card = page.getByTestId(`goal-card-${g}`);
    await expect(card).toBeVisible();
    await expect(page.getByTestId(`goal-success-${g}`)).toContainText(/\d+\s?%/);
    await expect(page.getByTestId(`goal-status-${g}`)).toHaveText(/On track|At risk|Off track/i);
  }
  for (const id of ["corpus-chart", "glide-chart", "cashflow-chart", "contribution-table", "fin-explanations"]) {
    await expect(page.getByTestId(id)).toBeVisible();
  }
  await expect(page.getByTestId("disclaimer-banner")).toContainText(DISCLAIMER_START);
}
