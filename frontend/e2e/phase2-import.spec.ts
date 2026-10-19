import { test, expect } from "@playwright/test";
import { expectClean, watch } from "./helpers";
import { TSV, acceptAllSuggestions, apiGet, intakeKeys, watchIntake, watchSaves } from "./phase2-helpers";

// PHASE2 2.13 / 3.3, plan P3b-6, P4-2: paste a TSV, check suggestions, change one mapping, apply, create;
// CSV upload via setInputFiles; a file over 1 MB is refused in the browser without a request.

test("paste TSV: suggested mapping, ignore one column, apply, review, create", async ({ page, request }) => {
  const problems = watch(page);
  const saves = watchSaves(page);
  const intake = watchIntake(page);
  await page.goto("/new/project/import");
  await page.getByTestId("import-paste").fill(TSV);
  await page.getByTestId("import-parse").click();
  const expected = ["name", "duration", "predecessors", "resources", "deadline"];
  for (let i = 0; i < expected.length; i++) await expect(page.getByTestId(`import-map-${i}`)).toHaveValue(expected[i]);
  await page.getByTestId("import-map-3").selectOption("");                        // Owner -> Ignore
  await page.getByTestId("import-apply").click();
  await expect(page.getByTestId("intake-draft")).toBeVisible();
  await expect(page.getByTestId("import-row-notes")).toBeVisible();
  const apply = intake.find((r) => r.url.endsWith("/intake/schedule/table/apply"))!;
  expect(apply.body.mapping.find((m: any) => m.column === 3).field).toBeNull();
  await acceptAllSuggestions(page);
  await expect(page.getByTestId("intake-create")).toBeEnabled();
  expect(saves).toHaveLength(0);
  await page.getByTestId("intake-create").click();
  await page.waitForURL(/\/plans\/p_[0-9a-f]+\/tasks/);
  const id = page.url().match(/\/plans\/(p_[0-9a-f]+)\//)![1];
  const rec = await apiGet(request, `/problems/${id}`);
  expect(rec.problem.metadata.intake.source).toBe("table");
  const names = rec.problem.tasks.map((t: any) => t.name);
  expect(names.some((n: string) => n.startsWith("Requirements"))).toBe(true);
  expect(rec.problem.resources.map((r: any) => r.name)).not.toContain("Priya");      // ignored column
  const lastBuild = rec.problem.tasks.filter((t: any) => t.name.startsWith("Build")).at(-1);
  expect(lastBuild.deadline).toContain("2026-12-15");
  expect(await intakeKeys(page)).toEqual([]);
  expectClean(problems);
});

test("CSV upload with quoted cells, then money table upload", async ({ page, request }) => {
  const problems = watch(page);
  await page.goto("/new/project/import");
  const csv = 'Task,Duration,Predecessors,Owner\n"Design, phase 1",2 days,,Asha\nBuild,"3-5 days","Design, phase 1",Ravi\n';
  await page.getByTestId("import-file").setInputFiles({ name: "plan.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(page.getByTestId("import-file-name")).toContainText("plan.csv");
  await page.getByTestId("import-parse").click();
  await expect(page.getByTestId("import-map-0")).toHaveValue("name");
  await expect(page.getByTestId("import-map-2")).toHaveValue("predecessors");
  await page.getByTestId("import-apply").click();
  await expect(page.getByTestId("intake-draft")).toBeVisible();
  await expect(page.getByTestId("import-row-notes")).toContainText("Every row was read without problems.");
  await acceptAllSuggestions(page);
  await page.getByTestId("intake-create").click();
  await page.waitForURL(/\/plans\/p_[0-9a-f]+\/tasks/);
  const id = page.url().match(/\/plans\/(p_[0-9a-f]+)\//)![1];
  const rec = await apiGet(request, `/problems/${id}`);
  expect(rec.problem.tasks.some((t: any) => t.name.startsWith("Design, phase 1"))).toBe(true);
  const dep = rec.problem.dependencies.find((d: any) => d.successor.startsWith("row1") && !d.predecessor.startsWith("row1"));
  expect(dep?.predecessor.startsWith("row0")).toBe(true);

  await page.goto("/new/money/import");
  const accept = page.getByTestId("disclaimer-accept");
  if (await accept.isVisible().catch(() => false)) await accept.click();
  const money = "Type,Item,Amount,Frequency,Essential\nincome,Salary,\"1,20,000\",monthly,\nexpense,Rent,25000,monthly,yes\n" +
    "goal,House down payment,15 lakh,,\n";
  await page.getByTestId("import-file").setInputFiles({ name: "money.csv", mimeType: "text/csv", buffer: Buffer.from(money) });
  await page.getByTestId("import-parse").click();
  await expect(page.getByTestId("import-map-0")).toHaveValue("row_kind");
  await page.getByTestId("import-apply").click();
  await expect(page.getByTestId("intake-draft")).toBeVisible();
  expectClean(problems);
});

test("a file over 1 MB or of the wrong type is refused in the browser with no request", async ({ page }) => {
  const problems = watch(page);
  const intake = watchIntake(page);
  await page.goto("/new/project/import");
  const big = Buffer.alloc(1024 * 1024 + 1, "a");
  await page.getByTestId("import-file").setInputFiles({ name: "big.csv", mimeType: "text/csv", buffer: big });
  await expect(page.getByTestId("import-file-error")).toBeVisible();
  await expect(page.getByTestId("import-file-error")).toContainText(/1 MB/);
  await page.getByTestId("import-file").setInputFiles({ name: "sheet.xlsx", mimeType: "application/octet-stream", buffer: Buffer.from("PK") });
  await expect(page.getByTestId("import-file-error")).toBeVisible();
  expect(intake).toHaveLength(0);
  expectClean(problems);
});

test("paste with a wrong mapping (two name columns) is stopped in the browser", async ({ page }) => {
  const problems = watch(page);
  const intake = watchIntake(page);
  await page.goto("/new/project/import");
  await page.getByTestId("import-paste").fill(TSV);
  await page.getByTestId("import-parse").click();
  await page.getByTestId("import-map-1").selectOption("name");
  await page.getByTestId("import-apply").click();
  await expect(page.getByTestId("import-map-errors")).toBeVisible();
  expect(intake.filter((r) => r.url.endsWith("/table/apply"))).toHaveLength(0);
  expectClean(problems);
});
