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
  const v = versions.get(key);
  try {
    const rec = await v1Request<{ row_version: number }>(path(key), {
      method: "PUT",
      body: { value },
      headers: v ? { "If-Match": `"${v}"` } : {},
    });
    versions.set(key, rec.row_version);
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

/** Fetch the server copy once per load; `onServer` gets it when it differs from the local copy. */
export function syncPref<T>(key: string, localKey: string, onServer: (v: T) => void): void {
  if (disabled || synced.has(key)) return;
  synced.add(key);
  void v1Request<{ value: T; row_version: number }>(path(key))
    .then((rec) => {
      versions.set(key, rec.row_version);
      const local = readLocal<T>(localKey);
      if (JSON.stringify(local) !== JSON.stringify(rec.value)) {
        writeLocal(localKey, rec.value);
        onServer(rec.value);
      }
    })
    .catch((e) => {
      if (e instanceof ApiError && e.status === 404 && e.code === "NOT_FOUND" && (e.details as { key?: string }).key === key) {
        // one-time migration of what this browser stored before preferences moved to the server
        const local = readLocal<T>(localKey);
        if (local !== undefined) void put(key, local);
        return;
      }
      if (e instanceof ApiError && (e.status === 401 || e.status === 403 || e.status === 404 || e.status === 405)) disabled = true;
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
