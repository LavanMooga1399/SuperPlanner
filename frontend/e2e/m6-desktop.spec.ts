/**
 * M6 WP-U desktop (docs/M6-DESIGN.md 1, 3, 9 Gate 6 items 1, 2, 4): the planning assistant panel with the scripted
 * development assistant (`ASSISTANT_AI_DEMO`: real read-only tools, no AI provider) - privacy notice, polled
 * progress, cited answer with internal links only, an overtime draft applied through the normal API; the plant
 * opt-out with the deterministic quick explanations still answering; the plant dashboard (tiles, drill-down, export,
 * print layout, targets, digest without SMTP).
 */
import { expect, test } from "@playwright/test";
import { gotoMfg, mfgCall, mfgJson } from "./mfg-helpers";
import { setAssistant, setupM6, type M6Data } from "./m6-helpers";

let data: M6Data;

/** A draft with the server's fields and a real endpoint (a what-if copy of the published schedule). */
const extraDraft = () => ({
  draft_id: "drf_e2e_whatif", kind: "whatif_run", summary: "Re-run the published schedule allowing overtime, to compare.",
  method: "POST", path: "/api/v1/mfg/aps/runs", body: { copy_of: data.publishedRunId, overtime: "allow", label: "Assistant what-if (e2e)" },
  if_match_of: null, required_permission: "schedule_run", allowed: true, applied_at: null, applied_status: null, response_ref: null,
});

test.describe("M6 assistant and dashboards (desktop)", () => {
  test.beforeAll(async ({ request }) => {
    test.setTimeout(300_000);
    data = await setupM6(request);
  });

  test("assistant: quick explanations, privacy notice, polled turn, citations as internal links, draft applied as the user", async ({ page }) => {
    await setAssistant(page.request, true);
    // The scripted assistant drafts overtime only when the published schedule suggests some (data-dependent). If
    // it drafted nothing, a server-shaped draft (same fields, a real endpoint) is added to the turn so Apply is
    // always exercised against the live API.
    await page.route(/\/api\/v1\/mfg\/assistant\/turns\/[^/]+$/, async (route) => {
      const r = await route.fetch();
      const t = (await r.json()) as { status: string; drafts: unknown[] };
      if (t.status === "completed" && !t.drafts.length)
        t.drafts = [extraDraft()];
      await route.fulfill({ response: r, json: t });
    });
    await page.goto(`/mfg/demand/${data.demandOrderId}?line=${data.demandLineId}`);
    await page.getByTestId("asst-open").click();
    const panel = page.getByTestId("asst-panel");
    await expect(panel).toBeVisible();

    // deterministic explanations (nothing sent to an AI provider)
    await panel.getByTestId("asst-quick-why_late").click();
    await expect(panel.getByTestId("asst-quick-result")).toBeVisible();
    await expect(panel.getByTestId("asst-quick-result")).toHaveAttribute("data-kind", "why_late");
    await panel.getByTestId("asst-quick-limits").click();
    await expect(panel.getByTestId("asst-quick-result")).toHaveAttribute("data-kind", "limits");

    // privacy notice before the first question
    await expect(panel.getByTestId("asst-privacy")).toContainText("Anthropic");
    await panel.getByTestId("asst-privacy-accept").click();

    const started = page.waitForResponse((r) => /\/assistant\/conversations\/[^/]+\/turns$/.test(new URL(r.url()).pathname) && r.request().method() === "POST");
    await panel.getByTestId("asst-input").fill("Why is DO-RUSH/10 late and what can I do?");
    await panel.getByTestId("asst-send").click();
    const res = await started;
    expect(res.status(), await res.text()).toBe(202);
    const sent = res.request().postDataJSON() as { context: { type: string; id: string } | null; allow_whatif: boolean };
    expect(sent.context).toEqual({ type: "demand_line", id: data.demandLineId });
    expect(sent.allow_whatif).toBe(false);

    const turn = panel.getByTestId("asst-turn").last();
    await expect(turn).toHaveAttribute("data-status", /completed|failed/, { timeout: 90_000 });
    await expect(turn).toHaveAttribute("data-status", "completed");
    await expect(turn.getByTestId("asst-answer")).toBeVisible();

    // citations: only server-issued refs, rendered as in-app links (never external URLs)
    const cites = turn.locator('a[data-testid="asst-cite"]');
    for (const href of await cites.evaluateAll((els) => els.map((e) => e.getAttribute("href") ?? ""))) expect(href).toMatch(/^\/(?!\/)/);
    await expect(turn.locator('a[href^="http"]')).toHaveCount(0);

    // a draft card: Apply sends the exact request as the user (session, CSRF, workspace, idempotency key)
    const draft = turn.getByTestId("asst-draft").first();
    await expect(draft).toBeVisible();
    await expect(draft.getByTestId("asst-draft-state")).toContainText("not applied");
    await draft.getByTestId("asst-draft-apply").click();
    const applied = page.waitForRequest((r) => r.method() === "POST" && new URL(r.url()).pathname === "/api/v1/mfg/aps/runs");
    const reported = page.waitForRequest((r) => /\/assistant\/drafts\/[^/]+\/applied$/.test(new URL(r.url()).pathname));
    await draft.getByTestId("asst-draft-confirm").click();
    const req = await applied;
    expect(req.headers()["idempotency-key"]).toMatch(/^asst-/);
    expect((req.postDataJSON() as { copy_of?: string }).copy_of).toBe(data.publishedRunId);
    const created = await req.response();
    expect(created?.status()).toBeLessThan(300);
    await expect(draft.getByTestId("asst-draft-done")).toBeVisible();
    expect(((await reported).postDataJSON() as { status: string }).status).toBe("succeeded");
  });

  test("viewer-style draft: Apply is disabled when the server says the user lacks the permission", async ({ page }) => {
    await setAssistant(page.request, true);
    // the server marks drafts `allowed: false` for users without the target permission (T-A1); simulate that answer
    await page.route(/\/api\/v1\/mfg\/assistant\/turns\/[^/]+$/, async (route) => {
      const r = await route.fetch();
      const t = (await r.json()) as { status: string; drafts: { allowed: boolean }[] };
      if (t.status === "completed" && !t.drafts.length) t.drafts = [extraDraft()];
      t.drafts = t.drafts.map((d) => ({ ...d, allowed: false }));
      await route.fulfill({ response: r, json: t });
    });
    await gotoMfg(page, "/schedule");
    await page.getByTestId("asst-open").click();
    const panel = page.getByTestId("asst-panel");
    // a fresh browser profile: the privacy notice comes first
    await panel.getByTestId("asst-privacy-accept").click();
    await panel.getByTestId("asst-more").click();
    await panel.getByTestId("asst-new").click();
    await panel.getByTestId("asst-input").fill("Why is DO-RUSH/10 late?");
    await panel.getByTestId("asst-send").click();
    const turn = panel.getByTestId("asst-turn").last();
    await expect(turn).toHaveAttribute("data-status", "completed", { timeout: 90_000 });
    const drafts = turn.getByTestId("asst-draft");
    await expect(drafts.first()).toBeVisible();
    for (let i = 0; i < (await drafts.count()); i++) {
      await expect(drafts.nth(i).getByTestId("asst-draft-apply")).toBeDisabled();
      await expect(drafts.nth(i).getByTestId("asst-draft-needs")).toBeVisible();
    }
  });

  test("plant opt-out: the reason is shown, quick explanations still answer; plant settings switch it back on", async ({ page }) => {
    await setAssistant(page.request, false);
    await gotoMfg(page, "/schedule");
    await page.getByTestId("asst-open").click();
    const panel = page.getByTestId("asst-panel");
    await expect(panel.getByTestId("asst-unavailable")).toHaveAttribute("data-code", "AI_PLANT_OPTED_OUT");
    await expect(panel.getByTestId("asst-code")).toHaveText("AI_PLANT_OPTED_OUT");
    await expect(panel.getByTestId("asst-input")).toHaveCount(0);
    await panel.getByTestId("asst-quick-changes").click();
    await expect(panel.getByTestId("asst-quick-result")).toHaveAttribute("data-kind", "changes");
    await panel.getByTestId("asst-close").click();

    await gotoMfg(page, "/plant/settings");
    const card = page.getByTestId("plant-assistant");
    await expect(card.getByTestId("plant-assistant-state")).toContainText("Off for this plant");
    await card.getByTestId("plant-assistant-enabled").check();
    await card.getByTestId("plant-assistant-save").click();
    await expect(card.getByText("Saved")).toBeVisible();
    const st = await mfgJson<{ available: boolean; plant: { assistant_enabled: boolean } }>(page.request, "/assistant/status");
    expect(st.plant.assistant_enabled).toBe(true);
    expect(st.available).toBe(true);
  });

  test("dashboard: tiles with status text, drill-down, export, print layout, targets, digest without SMTP", async ({ page }) => {
    await gotoMfg(page, "/dashboard");
    const tiles = page.getByTestId("dash-tiles");
    await expect(tiles).toBeVisible({ timeout: 30_000 });
    const api = await mfgJson<{ tiles: Record<string, { status: string }> }>(page.request, "/dashboard?period=13w");
    for (const [name, t] of Object.entries(api.tiles)) {
      const tile = page.getByTestId(`tile-${name}`);
      await expect(tile).toBeVisible();
      await expect(tile.getByTestId("tile-status")).toHaveAttribute("data-status", t.status);
      await expect(tile.getByTestId("tile-status")).not.toHaveText("");
    }

    // period switch reloads from the server
    const reload = page.waitForResponse((r) => /\/mfg\/dashboard\?period=4w/.test(r.url()));
    await page.getByTestId("dash-period").selectOption("4w");
    expect((await reload).status()).toBe(200);

    // drill-down opens an app page
    const drill = page.getByTestId("tile-otd").getByTestId("tile-drill").first();
    if (await drill.count()) {
      expect(await drill.getAttribute("href")).toMatch(/^\/mfg\//);
    }

    // export
    const dl = page.waitForEvent("download");
    await page.getByTestId("dash-export-csv").click();
    expect((await dl).suggestedFilename()).toMatch(/\.csv$/);

    // print layout: controls hidden, tiles kept
    await page.emulateMedia({ media: "print" });
    await expect(page.getByTestId("dash-export-xlsx")).toBeHidden();
    await expect(tiles).toBeVisible();
    await page.emulateMedia({ media: "screen" });

    // targets (owner)
    await page.getByTestId("dash-thresholds-toggle").click();
    await page.getByTestId("threshold-otd-watch").fill("93");
    const put = page.waitForRequest((r) => r.method() === "PUT" && /\/plant\/dashboard-thresholds$/.test(r.url()));
    await page.getByTestId("thresholds-save").click();
    const body = (await put).postDataJSON() as { thresholds: { otd: { watch_below: number } } };
    expect(body.thresholds.otd.watch_below).toBeCloseTo(0.93, 6);
    await expect(page.getByTestId("dash-thresholds").getByText("Saved")).toBeVisible();

    // digest: this server has no SMTP, so e-mail digests are explained as off (422 DIGEST_NO_SMTP otherwise)
    const digests = page.getByTestId("digest-settings");
    if (await digests.getByTestId("digest-add").count()) await digests.getByTestId("digest-add").click();
    await expect(digests.getByTestId("digest-no-smtp")).toBeVisible();
  });
});

test.afterAll(async ({ request }) => {
  await mfgCall(request, "PUT", "/plant/assistant", { data: { assistant_enabled: true, assistant_allow_whatif: true } }).catch(() => undefined);
});
