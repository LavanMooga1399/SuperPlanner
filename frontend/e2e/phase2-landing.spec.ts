import { test, expect } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { apiGet, tabTo } from "./phase2-helpers";

// PHASE2 3.1 / 3.2, plan P3a-2, P3a-3, P4-2: four kinds x four actions, reached and activated with the keyboard only.

const KINDS = ["project", "study", "production", "money"] as const;
const TEMPLATE: Record<string, string> = { project: "project", study: "exam_prep", production: "manufacturing" };
const DOMAIN: Record<string, string> = { project: "project", study: "exam_prep", production: "manufacturing" };
const DOMAIN_LABEL: Record<string, RegExp> = { project: /Project/i, study: /Exam preparation/i, production: /Manufacturing/i };

test("landing: heading, four kinds with four actions each", async ({ page }) => {
  const problems = watch(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "What do you want to plan?" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Your plans" })).toBeVisible();
  for (const k of KINDS) {
    const group = page.getByTestId(`landing-kind-${k}`);
    await expect(group).toHaveAttribute("role", "group");
    for (const a of ["describe", "example", "import", "steps"]) await expect(group.getByTestId(`landing-action-${k}-${a}`)).toBeVisible();
    await expect(group.getByRole("button")).toHaveCount(4);
  }
  await expect(page.getByTestId("template-card-project")).toBeVisible();
  await expect(page.locator("#import-file")).toBeAttached();
  expectClean(problems);
});

for (const kind of KINDS) {
  test(`landing ${kind}: describe, import and example by keyboard`, async ({ page }) => {
    const problems = watch(page);
    for (const action of ["describe", "import", "example"] as const) {
      await page.goto("/");
      await tabTo(page, `landing-action-${kind}-${action}`);
      await page.keyboard.press("Enter");
      await page.waitForURL(new RegExp(`/new/${kind}/${action}$`));
      if (action === "describe") {
        await expect(page.getByTestId("intake-text")).toBeVisible();
        await expect(page.getByTestId("intake-submit")).toHaveText(/Make a draft/);
      } else if (action === "import") {
        await expect(page.getByTestId("import-paste")).toBeVisible();
        await expect(page.getByTestId("import-file")).toBeAttached();
      } else if (kind === "money") {
        const accept = page.getByTestId("disclaimer-accept");
        if (await accept.isVisible().catch(() => false)) {
          await accept.focus();
          await page.keyboard.press("Enter");
        }
        for (const t of ["young_professional", "family", "near_retirement"]) await expect(page.getByTestId(`fin-template-card-${t}`)).toBeVisible();
      } else {
        await expect(page.getByTestId(`template-card-${TEMPLATE[kind]}`)).toBeVisible();
      }
    }
    expectClean(problems);
  });

  test(`landing ${kind}: "Build step by step" by keyboard (Space)`, async ({ page, request }) => {
    const problems = watch(page);
    await page.goto("/");
    await tabTo(page, `landing-action-${kind}-steps`);
    await page.keyboard.press("Space");
    if (kind === "money") {
      await page.waitForURL(/\/finance\/fp_[0-9a-f]+\/setup\/profile/, { timeout: 15_000 });
      const id = page.url().match(/\/finance\/(fp_[0-9a-f]+)\//)![1];
      const rec = await apiGet(request, `/finance/plans/${id}`);
      expect(rec.id).toBe(id);
      await expect(page.getByTestId("nav-finance")).toHaveAttribute("aria-current", "page");
    } else {
      await page.waitForURL(/\/plans\/p_[0-9a-f]+\/tasks/, { timeout: 15_000 });
      const id = page.url().match(/\/plans\/(p_[0-9a-f]+)\//)![1];
      const rec = await apiGet(request, `/problems/${id}`);
      expect(rec.problem.domain).toBe(DOMAIN[kind]);
      expect(rec.problem.tasks).toEqual([]);
      expect(rec.problem.resources).toHaveLength(1);
      await page.goto("/");
      await expect(page.getByTestId(`plan-item-${id}`)).toContainText(DOMAIN_LABEL[kind]);
    }
    expectClean(problems);
  });
}

test("start page /new/:kind shows the four ways; unknown kind is NotFound; Finance nav active on /new/money", async ({ page }) => {
  const problems = watch(page);
  for (const k of KINDS) {
    await page.goto(`/new/${k}`);
    await expect(page.getByTestId(`landing-kind-${k}`)).toBeVisible();
    await expect(page.getByTestId(`landing-kind-${k}`).getByRole("button")).toHaveCount(4);
  }
  await expect(page.getByTestId("nav-finance")).toHaveAttribute("aria-current", "page");
  for (const p of ["/new/unknown", "/new/unknown/describe", "/new/unknown/import", "/new/unknown/example"]) {
    await page.goto(p);
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  }
  expectClean(problems);
});
