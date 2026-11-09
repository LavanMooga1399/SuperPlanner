/**
 * PWA helpers (M6 2): service worker registration and Web Push opt-in. The server answers `PUSH_DISABLED` when no
 * VAPID key is configured; the UI then hides push. iOS delivers push only to an installed app (16.4+).
 */
import { ApiError } from "../api/client";
import { createPushSubscription, deletePushSubscription, getVapidKey } from "../mfg/api/clientM6";
import type { PushTopic } from "../mfg/api/typesM6";

export const ALL_TOPICS: PushTopic[] = ["critical_alerts", "approvals", "digest_ready"];

export const TOPIC_TEXT: Record<PushTopic, { label: string; help: string }> = {
  critical_alerts: { label: "Critical alerts", help: "A line is down or a critical replanning warning came in." },
  approvals: { label: "Approvals waiting for me", help: "Purchase requests, change requests, schedule proposals and overtime." },
  digest_ready: { label: "Digest ready", help: "The daily or weekly summary is ready; opens the dashboard." },
};

/** Registers `/sw.js` once (scope `/`). Safe to call repeatedly; resolves null where unsupported. */
let registering: Promise<ServiceWorkerRegistration | null> | null = null;
export function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (registering) return registering;
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator) || !window.isSecureContext) return Promise.resolve(null);
  registering = navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => null);
  return registering;
}

export function isIos(): boolean {
  const ua = navigator.userAgent;
  return /iPad|iPhone|iPod/.test(ua) || (ua.includes("Macintosh") && navigator.maxTouchPoints > 1);
}

export function isStandalone(): boolean {
  try {
    return window.matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone === true;
  } catch {
    return false;
  }
}

export type PushSupport = { ok: true } | { ok: false; reason: "no_sw" | "no_push" | "ios_install" | "denied" };

export function pushSupport(): PushSupport {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return { ok: false, reason: "no_sw" };
  if (isIos() && !isStandalone()) return { ok: false, reason: "ios_install" };
  if (!("PushManager" in window) || !("Notification" in window)) return { ok: false, reason: "no_push" };
  if (Notification.permission === "denied") return { ok: false, reason: "denied" };
  return { ok: true };
}

export const PUSH_SUPPORT_TEXT: Record<Exclude<PushSupport, { ok: true }>["reason"], string> = {
  no_sw: "This browser cannot receive notifications from SuperPlanner.",
  no_push: "This browser does not support push notifications.",
  ios_install: "On iPhone and iPad, notifications need the app on the home screen (iOS 16.4 or later): tap Share, then \"Add to Home Screen\", and open SuperPlanner from there.",
  denied: "Notifications are blocked for this site. Allow them in the browser's site settings, then come back here.",
};

function urlBase64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/**
 * The device's subscription is remembered per signed-in user (`sp.push.subscription.<user id>`), so on a shared
 * phone user B never sees or inherits user A's subscription; sign-out removes it (`pushSignOut`).
 */
const LEGACY_STORE = "sp.push.subscription";
const storeKey = (userId: string) => `${LEGACY_STORE}.${userId || "local"}`;
export interface StoredPush {
  id: string;
  topics: PushTopic[];
  endpoint: string;
}

export function storedPush(userId: string): StoredPush | null {
  try {
    localStorage.removeItem(LEGACY_STORE); // pre-review builds kept one unkeyed entry
    const raw = localStorage.getItem(storeKey(userId));
    return raw ? (JSON.parse(raw) as StoredPush) : null;
  } catch {
    return null;
  }
}
function savePush(userId: string, v: StoredPush | null) {
  try {
    if (v) localStorage.setItem(storeKey(userId), JSON.stringify(v));
    else localStorage.removeItem(storeKey(userId));
  } catch {
    /* ignore */
  }
}

/** The server no longer knows this phone's subscription (removed after 404/410 from the push service). */
export function forgetPush(userId: string): void {
  savePush(userId, null);
}

async function browserSubscription(): Promise<PushSubscription | null> {
  try {
    const reg = await navigator.serviceWorker.getRegistration("/");
    return (await reg?.pushManager.getSubscription()) ?? null;
  } catch {
    return null;
  }
}

/** True when the server has push configured; false for `PUSH_DISABLED` (or no M6 server). */
export async function pushAvailableOnServer(signal?: AbortSignal): Promise<{ available: boolean; key: string | null }> {
  try {
    const r = await getVapidKey(signal);
    return { available: Boolean(r.enabled && r.public_key), key: r.enabled ? r.public_key || null : null };
  } catch (e) {
    if (e instanceof ApiError && (e.code === "PUSH_DISABLED" || e.details?.code === "PUSH_DISABLED" || e.status === 404)) return { available: false, key: null };
    throw e;
  }
}

/**
 * Ask for permission, subscribe with the server's VAPID key and register the subscription with these topics.
 * A browser subscription this user did not create (another user on a shared device) is dropped first, so each
 * user gets a fresh endpoint.
 */
export async function subscribePush(userId: string, topics: PushTopic[], vapidKey: string): Promise<StoredPush> {
  const reg = await registerServiceWorker();
  if (!reg) throw new Error(PUSH_SUPPORT_TEXT.no_sw);
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error(PUSH_SUPPORT_TEXT.denied);
  const ready = await navigator.serviceWorker.ready;
  const old = storedPush(userId);
  let sub = await ready.pushManager.getSubscription();
  if (sub && (!old || old.endpoint !== sub.endpoint)) {
    await sub.unsubscribe().catch(() => false);
    sub = null;
  }
  if (!sub) sub = await ready.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToBytes(vapidKey) });
  const json = sub.toJSON() as { endpoint?: string; keys?: { p256dh?: string; auth?: string } };
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) throw new Error("The browser returned an incomplete push subscription.");
  if (old) await deletePushSubscription(old.id).catch(() => undefined);
  const rec = await createPushSubscription({ endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth }, topics });
  const v = { id: rec.id, topics: rec.topics ?? topics, endpoint: json.endpoint };
  savePush(userId, v);
  return v;
}

/** Turn push off for this user on this device: server record, browser subscription, stored entry. */
export async function unsubscribePush(userId: string): Promise<void> {
  const old = storedPush(userId);
  if (old)
    await deletePushSubscription(old.id).catch((e: unknown) => {
      if (!(e instanceof ApiError && e.status === 404)) throw e;
    });
  savePush(userId, null);
  await (await browserSubscription())?.unsubscribe().catch(() => false);
}

/**
 * Sign-out (called while the session is still valid): the device stops receiving this user's pushes. Never
 * throws; a failed server delete leaves a record whose endpoint no longer exists (the push service answers 410
 * and the server removes it).
 */
export async function pushSignOut(userId: string): Promise<void> {
  try {
    const old = storedPush(userId);
    if (old) await deletePushSubscription(old.id).catch(() => undefined);
    savePush(userId, null);
    if (typeof navigator !== "undefined" && "serviceWorker" in navigator) await (await browserSubscription())?.unsubscribe().catch(() => false);
  } catch {
    /* sign-out goes on */
  }
}
