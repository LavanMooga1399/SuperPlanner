/**
 * M6 e2e data (docs/M6-DESIGN.md 9): sample `small` plus a rush demand line due tomorrow (late demand) and an
 * optional evening shift on every stage (so the schedule suggests overtime), an MRP run and a published schedule.
 * The API runs the development-only scripted assistant (`ASSISTANT_AI_DEMO`, playwright.config.ts).
 */
import { expect, type APIRequestContext } from "@playwright/test";
import { findItem, loadSampleM2, mfgCall, mfgJson, resetMfg, runMrpApi } from "./mfg-helpers";

export const isoDay = (n: number) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);

interface RunLite {
  id: string;
  status: string;
  row_version: number;
  is_published?: boolean;
}

export async function waitRun(request: APIRequestContext, path: string, id: string, timeoutMs = 120_000): Promise<RunLite> {
  let run: RunLite | null = null;
  await expect
    .poll(
      async () => {
        run = await mfgJson<RunLite>(request, `${path}/${id}`);
        return run.status;
      },
      { timeout: timeoutMs, intervals: [500, 1000, 2000] },
    )
    .toMatch(/^(completed|failed|cancelled)$/);
  expect(run!.status).toBe("completed");
  return run!;
}

export interface M6Data {
  demandOrderId: string;
  demandLineId: string;
  publishedRunId: string;
}

export async function setupM6(request: APIRequestContext): Promise<M6Data> {
  await resetMfg(request);
  // anchored at today so the rush line is late against the current calendar (the schedule then suggests overtime)
  await loadSampleM2(request, "small", { anchor: null });
  const it = await findItem(request, "SM-100");
  const d = (await mfgCall(request, "POST", "/demand-orders", {
    data: { number: "DO-RUSH", demand_type: "customer", customer: "Rush customer (fictional)", priority: 1, lines: [{ line_no: 10, item_id: it.id, qty: 400, due_date: isoDay(2) }] },
    status: 201,
  })) as { id: string; row_version: number; lines: { id: string }[] };
  await mfgCall(request, "POST", `/demand-orders/${d.id}/open`, { data: {}, headers: { "If-Match": `"${d.row_version}"` } });
  const tpl = (await mfgCall(request, "POST", "/shift-templates", {
    data: { code: "OT-EVE", name: "Evening overtime", shifts: [{ name: "Evening", days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], start: "18:00", end: "23:00" }] },
    status: 201,
  })) as { id: string };
  const groups = await mfgJson<{ items: { id: string }[] }>(request, "/groups");
  for (const g of groups.items)
    await mfgCall(request, "POST", "/shift-assignments", {
      data: { shift_template_id: tpl.id, target_type: "group", group_id: g.id, kind: "optional", effective_from: isoDay(-7), cost_per_hour: 400, max_hours_per_week: 30 },
      status: 201,
    });
  const mrp = await runMrpApi(request, { label: "e2e m6" });
  await waitRun(request, "/mrp/runs", mrp.id);
  const run = (await mfgCall(request, "POST", "/aps/runs", { data: { label: "e2e m6 base" } })) as RunLite;
  const done = await waitRun(request, "/aps/runs", run.id);
  await mfgCall(request, "POST", `/aps/runs/${run.id}/publish`, { data: {}, headers: { "If-Match": `"${done.row_version}"` } });
  return { demandOrderId: d.id, demandLineId: d.lines[0].id, publishedRunId: run.id };
}

/** PUT /mfg/plant/assistant (owner). */
export async function setAssistant(request: APIRequestContext, enabled: boolean, allowWhatif = true): Promise<void> {
  await mfgCall(request, "PUT", "/plant/assistant", { data: { assistant_enabled: enabled, assistant_allow_whatif: allowWhatif } });
}
