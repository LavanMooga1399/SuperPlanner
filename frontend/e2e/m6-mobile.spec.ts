/**
 * M6 WP-U phone viewport (docs/M6-DESIGN.md 2, 9 Gate 6 item 3): the installable shell (manifest, service worker),
 * home, the approvals inbox (purchase request approve; suggested overtime accept and a replan proposal compare +
 * publish when the data offers them), downtime acknowledgement offline that syncs exactly once, and push: opt-in
 * (the browser's push service and permission prompt are stubbed, the subscription is registered with the real API)
 * and a push message delivered to the service worker (Chromium DevTools protocol) that reaches the open app.
 */
import { createECDH, randomBytes } from "node:crypto";
import { devices, expect, test } from "@playwright/test";
import { findItem, mfgCall, mfgJson } from "./mfg-helpers";
import { isoDay, setupM6, waitRun, type M6Data } from "./m6-helpers";

test.use({ ...devices["Pixel 7"] });

let data: M6Data;
let lineId = "";
let downtimeId = "";

const b64u = (b: Buffer) => b.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

test.describe("M6 mobile (phone)", () => {
  test.beforeAll(async ({ request }) => {
    test.setTimeout(300_000);
    data = await setupM6(request);
    // a purchase request waiting for approval (created and submitted)
    const sups = await mfgJson<{ items: { id: string }[] }>(request, "/suppliers");
    const mcu = await findItem(request, "SM-MCU-01");
    const pr = (await mfgCall(request, "POST", "/purchase-requests", {
      data: { supplier_id: sups.items[0]?.id ?? null, note: "e2e m6 approval", lines: [{ line_no: 10, item_id: mcu.id, schedules: [{ requested_date: isoDay(14), qty: 20 }] }] },
      status: 201,
    })) as { id: string; row_version: number };
    await mfgCall(request, "POST", `/purchase-requests/${pr.id}/submit`, { data: {}, headers: { "If-Match": `"${pr.row_version}"` } });
    // a line down (open downtime) -> replanning trigger -> a replan proposal
    const lines = await mfgJson<{ items: { id: string; code: string }[] }>(request, "/lines?active=true");
    lineId = lines.items[0].id;
    const dt = (await mfgCall(request, "POST", "/downtime", { data: { line_id: lineId, kind: "breakdown", reason: "Feeder jam (e2e)" } })) as { id: string };
    downtimeId = dt.id;
    const rr = await request.post("http://127.0.0.1:8000/api/v1/mfg/replan/run", { data: {} });
    if (rr.ok()) {
      const run = (await rr.json()) as { id: string };
      await waitRun(request, "/aps/runs", run.id).catch(() => undefined);
    }
  });

  test("shell: manifest, service worker, home with my plant", async ({ page }) => {
    await page.goto("/m");
    await expect(page.getByTestId("m-shell")).toBeVisible();
    await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", "/manifest.webmanifest");
    const manifest = await (await page.request.get("/manifest.webmanifest")).json();
    expect(manifest.start_url).toBe("/m");
    expect(manifest.display).toBe("standalone");
    const sw = await page.evaluate(async () => (await navigator.serviceWorker.ready).active?.scriptURL ?? "");
    expect(sw).toMatch(/\/sw\.js$/);
    await expect(page.getByTestId("m-plant-card").first()).toBeVisible();
    await expect(page.getByTestId("m-stat-down").first()).not.toContainText("–", { timeout: 30_000 });
    // bottom navigation, large targets
    const tab = page.getByTestId("m-tab-approvals");
    expect((await tab.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  });

  test("approvals inbox: approve a purchase request; accept overtime and publish a replan proposal when offered", async ({ page }) => {
    await page.goto("/m/approvals");
    await expect(page.getByTestId("m-approvals")).toBeVisible();
    const api = await mfgJson<{ items: { kind: string; id: string }[] }>(page.request, "/approvals");
    console.log(`m6 approvals offered: ${api.items.map((x) => x.kind).join(",")}`);

    const pr = api.items.find((x) => x.kind === "pr");
    expect(pr, "a submitted purchase request waits for approval").toBeTruthy();
    const card = page.locator(`[data-testid="m-approval"][data-kind="pr"][data-id="${pr!.id}"]`);
    await expect(card).toBeVisible();
    const approve = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith(`/purchase-requests/${pr!.id}/approve`));
    await card.locator('[data-label="Approve"]').click();
    expect((await approve).headers()["if-match"]).toMatch(/^"\d+"$/);
    await expect(card.getByTestId("m-approval-result")).toContainText("done");
    const doc = await mfgJson<{ status: string }>(page.request, `/purchase-requests/${pr!.id}`);
    expect(doc.status).toBe("approved");

    const ot = api.items.find((x) => x.kind === "overtime");
    if (ot) {
      const c = page.locator(`[data-testid="m-approval"][data-kind="overtime"][data-id="${ot.id}"]`);
      const created = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/mfg/aps/runs");
      await c.getByTestId("m-approval-action-0").click();
      expect((await created).status()).toBeLessThan(300);
      await expect(c.getByTestId("m-approval-result")).toContainText("Accepted");
    }

    const prop = api.items.find((x) => x.kind === "replan_proposal");
    if (prop) {
      const c = page.locator(`[data-testid="m-approval"][data-kind="replan_proposal"][data-id="${prop.id}"]`);
      await c.getByTestId("m-proposal-compare-btn").click();
      await expect(c.getByTestId("m-proposal-compare")).toBeVisible();
      await c.getByTestId("m-approval-action-0").click();
      if (await c.getByTestId("m-approval-stale-confirm").count()) await c.getByTestId("m-approval-stale-confirm").click();
      await expect(c.getByTestId("m-approval-result")).toContainText("done", { timeout: 30_000 });
      const run = await mfgJson<{ is_published: boolean }>(page.request, `/aps/runs/${prop.id}`);
      expect(run.is_published).toBe(true);
    }
  });

  test("downtime acknowledged offline is sent once when back online", async ({ page, context }) => {
    await page.goto(`/m/lines/${lineId}`);
    const card = page.getByTestId("m-downtime");
    await expect(card).toBeVisible();
    await expect(card.getByTestId("m-downtime-ack")).toContainText("Not yet acknowledged");

    const acks: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().endsWith(`/downtime/${downtimeId}/acknowledge`)) acks.push(r.headers()["idempotency-key"] ?? "");
    });
    await context.setOffline(true);
    await expect(page.getByTestId("m-online")).toHaveAttribute("data-online", "false");
    await card.getByTestId("m-downtime-ack-btn").click();
    await expect(card.getByTestId("m-downtime-msg")).toContainText("sent when you are back online");
    await expect(card.getByTestId("m-downtime-ack")).toContainText("waiting to sync");
    await expect(page.getByTestId("m-queue")).toContainText("1 waiting to sync");

    await context.setOffline(false);
    await expect(page.getByTestId("m-queue")).toHaveCount(0, { timeout: 30_000 });
    const dts = await mfgJson<{ items: { id: string; acknowledged_at: string | null }[] }>(page.request, `/downtime?line_id=${lineId}&open=true`);
    expect(dts.items.find((d) => d.id === downtimeId)?.acknowledged_at).toBeTruthy();
    // offline attempts never reach the server; the replay is one request (one key)
    expect(new Set(acks.filter(Boolean)).size).toBe(1);
  });

  test("push: opt in on this phone, then a push message reaches the service worker and the app", async ({ page, context }) => {
    await context.grantPermissions(["notifications"], { origin: "http://127.0.0.1:5173" });
    // headless Chromium has no push service: stub the browser's subscription with a real P-256 key
    const ecdh = createECDH("prime256v1");
    ecdh.generateKeys();
    const keys = { p256dh: b64u(ecdh.getPublicKey()), auth: b64u(randomBytes(16)) };
    await page.addInitScript((k) => {
      // headless Chromium always reports notifications as blocked; a real phone asks the user here
      Object.defineProperty(Notification, "permission", { get: () => "granted" });
      Notification.requestPermission = async () => "granted";
      const sub = {
        endpoint: "https://push.e2e.example/send/abc123",
        toJSON: () => ({ endpoint: "https://push.e2e.example/send/abc123", keys: k }),
        unsubscribe: async () => true,
      };
      let active: typeof sub | null = null;
      PushManager.prototype.subscribe = async function () {
        active = sub;
        return sub as unknown as PushSubscription;
      };
      PushManager.prototype.getSubscription = async function () {
        return active as unknown as PushSubscription | null;
      };
    }, keys);

    await page.goto("/m/more");
    const push = page.getByTestId("m-push");
    await expect(push).toBeVisible();
    await expect(push.getByTestId("m-push-state")).toHaveAttribute("data-on", "false");
    await push.getByTestId("m-push-topic-digest_ready").check();
    const created = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/push/subscriptions");
    await push.getByTestId("m-push-save").click();
    const res = await created;
    expect(res.status(), await res.text()).toBe(201);
    expect((res.request().postDataJSON() as { topics: string[] }).topics.sort()).toEqual(["approvals", "critical_alerts", "digest_ready"]);
    await expect(push.getByTestId("m-push-state")).toHaveAttribute("data-on", "true");
    const mine = await (await page.request.get("/api/v1/push/subscriptions")).json();
    expect(mine.items.length).toBeGreaterThanOrEqual(1);

    // deliver a push message to the registered service worker (as the push service would); headless Chromium
    // cannot show notifications, so the check is that the worker handled it and told the open app
    await page.evaluate(() => {
      (window as unknown as { __push: unknown[] }).__push = [];
      window.addEventListener("sp-push", (e) => (window as unknown as { __push: unknown[] }).__push.push((e as CustomEvent).detail));
    });
    const cdp = await context.newCDPSession(page);
    const regId = new Promise<string>((resolve) => {
      cdp.on("ServiceWorker.workerRegistrationUpdated", (e: { registrations: { registrationId: string; scopeURL: string; isDeleted: boolean }[] }) => {
        const r = e.registrations.find((x) => !x.isDeleted && x.scopeURL.startsWith("http://127.0.0.1:5173/"));
        if (r) resolve(r.registrationId);
      });
    });
    await cdp.send("ServiceWorker.enable");
    await cdp.send("ServiceWorker.deliverPushMessage", {
      origin: "http://127.0.0.1:5173",
      registrationId: await regId,
      data: JSON.stringify({ title: "SMT line down", body: "Feeder jam", link: `/m/lines/${lineId}`, topic: "critical_alerts", tag: "e2e" }),
    });
    await expect
      .poll(async () => page.evaluate(() => (window as unknown as { __push: { title: string; link: string; topic: string }[] }).__push), { timeout: 15_000 })
      .toContainEqual({ type: "push", title: "SMT line down", link: `/m/lines/${lineId}`, topic: "critical_alerts" });
  });
});
