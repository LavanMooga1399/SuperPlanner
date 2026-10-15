import { test, expect } from "@playwright/test";
import { apiJson, approveCurrent, createFromTemplate, expectClean, gotoTab, openSchedule, optimize, validateReady, watch } from "./helpers";

const TEMPLATES = [
  { id: "manufacturing", tasks: "Operations", resources: "Machines", schedule: "Production schedule" },
  { id: "exam_prep", tasks: "Study sessions", resources: "Study time", schedule: "Study plan" },
  { id: "project", tasks: "Tasks", resources: "Team", schedule: "Project schedule" },
];

for (const tpl of TEMPLATES) {
  test(`template ${tpl.id}: create, validate, optimize, Gantt, approve`, async ({ page, request }) => {
    const problems = watch(page);
    const planId = await createFromTemplate(page, tpl.id, `E2E ${tpl.id}`);
    const nav = page.getByRole("navigation", { name: "Plan sections" });
    await expect(nav.getByRole("link", { name: new RegExp(`^${tpl.tasks}`) })).toBeVisible();
    await expect(nav.getByRole("link", { name: new RegExp(`^${tpl.resources}`) })).toBeVisible();
    await expect(nav.getByRole("link", { name: tpl.schedule })).toBeVisible();
    const rec = await apiJson(request, `/problems/${planId}`);
    expect(rec.template_id).toBe(tpl.id);
    for (const t of rec.problem.tasks.slice(0, 3)) await expect(page.getByTestId(`task-row-${t.id}`)).toBeVisible();

    await validateReady(page);
    const runId = await optimize(page);
    const run = await apiJson(request, `/solver-runs/${runId}`);
    expect(run.status).toBe("completed");
    expect(run.feasibility).toBe("feasible");
    const bars = await openSchedule(page);
    // one bar per task in the task view (virtualization only above 300 rows)
    await expect(bars).toHaveCount(rec.problem.tasks.length);
    await expect(page.getByTestId("kpi-cards")).toBeVisible();
    await expect(page.getByTestId("approval-banner")).toContainText("Candidate");
    await approveCurrent(page);
    const approved = await apiJson(request, `/problems/${planId}/schedules?status=approved`);
    expect(approved.items.map((s: { id: string }) => s.id)).toEqual([run.primary_schedule_id]);
    // the plan list on Home shows it
    await page.goto("/");
    await expect(page.getByTestId("plan-list")).toContainText(`E2E ${tpl.id}`);
    expectClean(problems);
  });
}
