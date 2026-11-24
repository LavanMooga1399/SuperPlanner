/**
 * Inspection results helpers (M7 5.2): the live state of each characteristic of a lot (sampling, entered samples,
 * defectives, verdict) and an offline queue for result batches (keyed by `client_batch_id`, so a replay returns
 * the stored response; floor tablets keep entering when the network drops, as the M4 floor queue).
 */
import { useEffect, useSyncExternalStore } from "react";
import { isNetworkError } from "../../api/client";
import { postResults } from "../api/clientM7";
import type { Characteristic, CharVerdict, InspectionLot, InspectionResult, ResultEntry, ResultsBatchResponse, Verdict } from "../api/typesM7";
import { currentWorkspace } from "../lib/workspace";

export interface CharState {
  c: Characteristic;
  n: number;
  ac: number;
  re: number;
  aql: string | null;
  tightened: boolean;
  /** current (not superseded) result per sample number */
  bySample: Map<number, InspectionResult>;
  entered: number;
  defective: number;
  verdict: Verdict;
}

export function isDefective(c: Characteristic, r: Pick<InspectionResult, "value" | "passed">): boolean {
  if (c.kind === "attribute") return !r.passed;
  if (r.value === null || r.value === undefined) return !r.passed;
  return (c.lsl !== null && r.value < c.lsl) || (c.usl !== null && r.value > c.usl);
}

export function charStates(lot: InspectionLot): CharState[] {
  const v = new Map<string, CharVerdict>((lot.verdict?.characteristics ?? []).map((x) => [x.characteristic_id, x]));
  return [...lot.characteristics]
    .sort((a, b) => a.seq - b.seq)
    .map((c) => {
      const s = lot.sampling[c.id] ?? { n: v.get(c.id)?.n ?? 0, ac: v.get(c.id)?.ac ?? 0, re: v.get(c.id)?.re ?? 1 };
      const bySample = new Map<number, InspectionResult>();
      for (const r of lot.results) if (r.characteristic_id === c.id && !r.superseded) bySample.set(r.sample_no, r);
      let defective = 0;
      bySample.forEach((r) => {
        if (isDefective(c, r)) defective += 1;
      });
      const sv = v.get(c.id);
      const entered = sv?.entered ?? bySample.size;
      const def = sv?.defective ?? defective;
      const verdict: Verdict = sv?.verdict ?? (def >= s.re ? "reject" : bySample.size >= s.n && def <= s.ac ? "accept" : "pending");
      return { c, n: s.n, ac: s.ac, re: s.re, aql: s.aql ?? null, tightened: s.severity_state === "tightened", bySample, entered, defective: def, verdict };
    });
}

/** First sample number without a result (1-based), or null when all n are entered. */
export function nextOpenSample(s: CharState): number | null {
  for (let i = 1; i <= s.n; i++) if (!s.bySample.has(i)) return i;
  return null;
}

// ---------------------------------------------------------------- offline queue
interface QueuedBatch {
  lotId: string;
  client_batch_id: string;
  results: ResultEntry[];
  created_at: string;
  error?: string | null;
}
const key = () => `sp.qa.results.${currentWorkspace() ?? "own"}`;
function load(): QueuedBatch[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(key()) ?? "[]") as unknown;
    return Array.isArray(v) ? (v as QueuedBatch[]) : [];
  } catch {
    return [];
  }
}
let queue: QueuedBatch[] = typeof window === "undefined" ? [] : load();
const listeners = new Set<() => void>();
function save(next: QueuedBatch[]) {
  queue = next;
  try {
    window.localStorage.setItem(key(), JSON.stringify(next));
  } catch {
    /* storage full: the batch stays in memory for this page */
  }
  listeners.forEach((l) => l());
}

/** Send a batch; when the server cannot be reached it is queued and replayed later. */
export async function submitResults(lotId: string, client_batch_id: string, results: ResultEntry[]): Promise<{ status: "sent"; res: ResultsBatchResponse } | { status: "queued" }> {
  if (queue.some((q) => q.lotId === lotId && !q.error)) {
    save([...queue, { lotId, client_batch_id, results, created_at: new Date().toISOString() }]);
    void syncResults();
    return { status: "queued" };
  }
  try {
    const res = await postResults(lotId, { client_batch_id, results });
    return { status: "sent", res };
  } catch (e) {
    if (isNetworkError(e)) {
      save([...queue, { lotId, client_batch_id, results, created_at: new Date().toISOString() }]);
      return { status: "queued" };
    }
    throw e;
  }
}

let syncing = false;
export async function syncResults(): Promise<void> {
  if (syncing) return;
  syncing = true;
  try {
    for (const b of [...queue]) {
      if (b.error) continue;
      try {
        await postResults(b.lotId, { client_batch_id: b.client_batch_id, results: b.results });
        save(queue.filter((x) => x.client_batch_id !== b.client_batch_id));
      } catch (e) {
        if (isNetworkError(e)) break;
        save(queue.map((x) => (x.client_batch_id === b.client_batch_id ? { ...x, error: e instanceof Error ? e.message : String(e) } : x)));
      }
    }
  } finally {
    syncing = false;
  }
}
export const discardQueued = (id: string) => save(queue.filter((x) => x.client_batch_id !== id));

export function useResultQueue(lotId?: string): QueuedBatch[] {
  const q = useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => queue,
  );
  useEffect(() => {
    const on = () => void syncResults();
    window.addEventListener("online", on);
    const id = window.setInterval(on, 15000);
    return () => {
      window.removeEventListener("online", on);
      window.clearInterval(id);
    };
  }, []);
  return lotId ? q.filter((x) => x.lotId === lotId) : q;
}
