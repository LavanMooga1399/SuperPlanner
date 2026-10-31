/**
 * Offline tolerance of the floor pages (M4 12, principle F4): every action carries a `client_event_id` made on the
 * device. When the server cannot be reached, the action is kept in `localStorage` and replayed in order once the
 * network returns. Replays are safe because the server de-duplicates on `client_event_id` (#203 answers 200
 * `Idempotent-Replay`). While anything is waiting, new actions queue behind it so the order on the floor is kept.
 * An action the server rejects (4xx) moves to "needs attention" with the server's message; it is never retried
 * automatically (it would fail the same way) and the operator can discard it or retry it after fixing the cause.
 */
import { useEffect, useState, useSyncExternalStore } from "react";
import { ApiError, isNetworkError } from "../../api/client";
import { createDowntime, postFloorEvent, updateDowntime } from "../api/clientM4";
import type { DowntimeInput, DowntimeUpdate, FloorEventInput, FloorEventResult } from "../api/typesM4";
import { currentWorkspace } from "../lib/workspace";

export type QueuedAction =
  | { kind: "event"; id: string; body: FloorEventInput; label: string; created_at: string; attempts: number; error?: QueuedError | null }
  | { kind: "downtime_open"; id: string; body: DowntimeInput; label: string; created_at: string; attempts: number; error?: QueuedError | null }
  | { kind: "downtime_update"; id: string; downtimeId: string; version: number; body: DowntimeUpdate; label: string; created_at: string; attempts: number; error?: QueuedError | null };

export interface QueuedError {
  status: number;
  code: string;
  message: string;
}

interface State {
  pending: QueuedAction[];
  failed: QueuedAction[];
  syncing: boolean;
  lastSyncAt: string | null;
}

const storageKey = () => `sp.floor.queue.${currentWorkspace() ?? "own"}`;
let state: State = load();
const listeners = new Set<() => void>();

function load(): State {
  try {
    const raw = localStorage.getItem(storageKey());
    if (raw) {
      const x = JSON.parse(raw) as Partial<State>;
      return { pending: x.pending ?? [], failed: x.failed ?? [], syncing: false, lastSyncAt: x.lastSyncAt ?? null };
    }
  } catch {
    /* corrupted or unavailable storage: start empty */
  }
  return { pending: [], failed: [], syncing: false, lastSyncAt: null };
}

function save(next: State) {
  state = next;
  try {
    localStorage.setItem(storageKey(), JSON.stringify({ pending: next.pending, failed: next.failed, lastSyncAt: next.lastSyncAt }));
  } catch {
    /* quota or private mode: the queue still works for this page session */
  }
  for (const l of listeners) l();
}

/** A device-unique id (8..64 chars, #203). */
export function newClientEventId(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c?.randomUUID) return `fe-${c.randomUUID()}`;
  return `fe-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function toQueuedError(e: unknown): QueuedError {
  if (e instanceof ApiError) return { status: e.status, code: e.code, message: e.message };
  return { status: 0, code: "UNKNOWN", message: e instanceof Error ? e.message : String(e) };
}

async function send(a: QueuedAction): Promise<unknown> {
  if (a.kind === "event") return postFloorEvent(a.body);
  if (a.kind === "downtime_open") return createDowntime(a.body, a.id);
  return updateDowntime(a.downtimeId, a.body, a.version);
}

export type SubmitOutcome<T> = { status: "sent"; result: T } | { status: "queued" };

/**
 * Send now when nothing is waiting and the server answers; keep it for later when the network is down.
 * A server rejection (4xx/5xx with an error envelope) is thrown to the caller, who shows it on the screen.
 */
async function submit<T>(a: QueuedAction): Promise<SubmitOutcome<T>> {
  if (state.pending.length) {
    save({ ...state, pending: [...state.pending, a] });
    void syncNow();
    return { status: "queued" };
  }
  try {
    return { status: "sent", result: (await send(a)) as T };
  } catch (e) {
    if (isNetworkError(e)) {
      save({ ...state, pending: [...state.pending, { ...a, attempts: 1 }] });
      return { status: "queued" };
    }
    throw e;
  }
}

export function submitFloorEvent(body: FloorEventInput, label: string) {
  return submit<FloorEventResult & { replayed: boolean }>({ kind: "event", id: body.client_event_id, body, label, created_at: new Date().toISOString(), attempts: 0 });
}

export function submitDowntimeOpen(body: DowntimeInput, label: string) {
  return submit({ kind: "downtime_open", id: newClientEventId(), body, label, created_at: new Date().toISOString(), attempts: 0 });
}

export function submitDowntimeUpdate(downtimeId: string, version: number, body: DowntimeUpdate, label: string) {
  return submit({ kind: "downtime_update", id: newClientEventId(), downtimeId, version, body, label, created_at: new Date().toISOString(), attempts: 0 });
}

let running: Promise<void> | null = null;

/** Replay waiting actions in order; stops at the first network failure (the rest stay in order). */
export function syncNow(): Promise<void> {
  if (running) return running;
  running = (async () => {
    save({ ...state, syncing: true });
    try {
      while (state.pending.length) {
        const a = state.pending[0];
        try {
          await send(a);
          save({ ...state, pending: state.pending.slice(1), lastSyncAt: new Date().toISOString() });
        } catch (e) {
          if (isNetworkError(e)) {
            save({ ...state, pending: [{ ...a, attempts: a.attempts + 1 }, ...state.pending.slice(1)] });
            break;
          }
          save({ ...state, pending: state.pending.slice(1), failed: [...state.failed, { ...a, attempts: a.attempts + 1, error: toQueuedError(e) }] });
        }
      }
    } finally {
      save({ ...state, syncing: false });
      running = null;
    }
  })();
  return running;
}

/** Put a rejected action back at the end of the queue (after the cause was fixed). */
export function retryFailed(id: string) {
  const a = state.failed.find((x) => x.id === id);
  if (!a) return;
  save({ ...state, failed: state.failed.filter((x) => x.id !== id), pending: [...state.pending, { ...a, error: null }] });
  void syncNow();
}

export function discardFailed(id: string) {
  save({ ...state, failed: state.failed.filter((x) => x.id !== id) });
}

function subscribe(l: () => void) {
  listeners.add(l);
  const onStorage = (e: StorageEvent) => {
    if (e.key === storageKey()) {
      state = { ...load(), syncing: state.syncing };
      l();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(l);
    window.removeEventListener("storage", onStorage);
  };
}

export function useFloorQueue(): State {
  return useSyncExternalStore(subscribe, () => state);
}

/** Mount once per floor layout: syncs when the browser comes back online and every 15 s while actions wait. */
export function useAutoSync(): { online: boolean } {
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  const q = useFloorQueue();
  useEffect(() => {
    const on = () => {
      setOnline(true);
      void syncNow();
    };
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    if (state.pending.length) void syncNow();
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  useEffect(() => {
    if (!q.pending.length) return;
    const t = window.setInterval(() => void syncNow(), 15000);
    return () => window.clearInterval(t);
  }, [q.pending.length]);
  return { online };
}

/** Test seam / workspace switch. */
export function reloadQueueFromStorage() {
  save(load());
}
