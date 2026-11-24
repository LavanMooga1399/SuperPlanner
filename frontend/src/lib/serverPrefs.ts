/**
 * Per-user preferences on the server (`GET|PUT /api/v1/me/preferences/{key}`, docs/UX-STANDARD.md "Backend
 * support"), with localStorage as the offline cache and fallback.
 *
 * - Read: the local copy answers immediately; `syncPref` then fetches the server copy once per page load and,
 *   when it differs, replaces the local copy and notifies the owner (server wins: it follows the person).
 * - Write: `savePref` writes locally at once and PUTs after a short pause (column drags send one request).
 *   412/428 (changed elsewhere) retries once with the server's version: the latest action of this person wins.
 * - Migration: when the server has no copy (404) but this browser has one, it is uploaded once.
 * - Offline / no server support / signed out: everything keeps working on the local copy.
 */
import { ApiError } from "../api/client";
import { v1Request } from "../mfg/api/client";

const versions = new Map<string, number>();
const synced = new Set<string>();
const timers = new Map<string, number>();
let disabled = false; // e.g. API tokens or a server without the endpoint

function readLocal<T>(localKey: string): T | undefined {
  try {
    const raw = window.localStorage.getItem(localKey);
    return raw === null ? undefined : (JSON.parse(raw) as T);
  } catch {
    return undefined;
  }
}

function writeLocal(localKey: string, v: unknown): void {
  try {
    if (v === undefined || v === null) window.localStorage.removeItem(localKey);
    else window.localStorage.setItem(localKey, JSON.stringify(v));
  } catch {
    /* storage unavailable */
  }
}

const path = (key: string) => `/me/preferences/${encodeURIComponent(key)}`;

async function put(key: string, value: unknown, retry = true): Promise<void> {
  // know the current version first, so a normal save never needs a 428 round trip
  const idx = await loadIndex();
  if (!idx) return;
  if (!versions.has(key) && idx.has(key)) versions.set(key, idx.get(key)!);
  const v = versions.get(key);
  try {
    const rec = await v1Request<{ row_version: number }>(path(key), {
      method: "PUT",
      body: { value },
      headers: v ? { "If-Match": `"${v}"` } : {},
    });
    versions.set(key, rec.row_version);
    idx.set(key, rec.row_version);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 412 || e.status === 428) && retry) {
      const cur = Number((e.details as { current_version?: unknown }).current_version);
      if (Number.isFinite(cur)) {
        if (cur > 0) versions.set(key, cur);
        else versions.delete(key);
        return put(key, value, false);
      }
    }
    if (e instanceof ApiError && (e.status === 401 || e.status === 403 || e.status === 404 || e.status === 405)) disabled = true;
    /* otherwise offline or refused: the local copy stays the source until the next sync */
  }
}

/** One index request per page load (keys and versions, no values): existing keys are fetched, missing ones are
 *  never requested (no 404s), and local-only ones are uploaded once (migration). */
let index: Promise<Map<string, number> | null> | null = null;
function loadIndex(): Promise<Map<string, number> | null> {
  index ??= v1Request<{ items: { key: string; row_version: number }[] }>("/me/preferences")
    .then((r) => new Map(r.items.map((i) => [i.key, i.row_version])))
    .catch((e) => {
      if (e instanceof ApiError && e.status !== 0) disabled = true; // signed out, token, or no endpoint
      return null;
    });
  return index;
}

/** Fetch the server copy once per load; `onServer` gets it when it differs from the local copy. */
export function syncPref<T>(key: string, localKey: string, onServer: (v: T) => void): void {
  if (disabled || synced.has(key)) return;
  synced.add(key);
  void loadIndex().then((idx) => {
    if (!idx) return;
    const v = idx.get(key);
    if (v === undefined) {
      // one-time migration of what this browser stored before preferences moved to the server
      const local = readLocal<T>(localKey);
      if (local !== undefined) void put(key, local);
      return;
    }
    versions.set(key, v);
    void v1Request<{ value: T; row_version: number }>(path(key))
      .then((rec) => {
        versions.set(key, rec.row_version);
        if (JSON.stringify(readLocal<T>(localKey)) !== JSON.stringify(rec.value)) {
          writeLocal(localKey, rec.value);
          onServer(rec.value);
        }
      })
      .catch(() => undefined);
  });
}

/** Save locally now and on the server shortly after (debounced per key). `undefined` resets to default. */
export function savePref(key: string, localKey: string, value: unknown): void {
  writeLocal(localKey, value);
  if (disabled) return;
  const t = timers.get(key);
  if (t) window.clearTimeout(t);
  timers.set(
    key,
    window.setTimeout(() => {
      timers.delete(key);
      if (value === undefined || value === null) {
        const v = versions.get(key);
        if (v)
          void v1Request(path(key), { method: "DELETE", headers: { "If-Match": `"${v}"` } })
            .then(() => versions.delete(key))
            .catch(() => undefined);
        return;
      }
      void put(key, value);
    }, 600),
  );
}

/** Save locally and on the server now (no debounce), e.g. before a page reload (language switch). */
export async function savePrefNow(key: string, localKey: string, value: unknown): Promise<void> {
  writeLocal(localKey, value);
  const t = timers.get(key);
  if (t) {
    window.clearTimeout(t);
    timers.delete(key);
  }
  if (disabled) return;
  await put(key, value);
}
