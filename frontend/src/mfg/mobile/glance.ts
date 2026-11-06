/**
 * Mobile home figures per plant (M6 2 "home"): lines running / paused / down / idle, late demand lines (published
 * schedule), open replanning warnings and approvals waiting. Composed from existing endpoints with the plant's
 * workspace header, so other plants can be shown without switching. A figure the role cannot read is null.
 */
import { isNetworkError } from "../../api/client";
import { mfgRequest } from "../api/client";
import type { List, LineRecord, Page } from "../api/types";
import type { ApsRunRecord } from "../api/typesM3";
import type { Downtime, FloorQueueResponse, TriggerPage } from "../api/typesM4";
import type { ApprovalsResponse } from "../api/typesM6";
import { workspaceOverride } from "../api/clientM6";

export type LineState = "running" | "paused" | "down" | "idle";

export interface LineGlance {
  id: string;
  code: string;
  name: string;
  state: LineState;
  current: string | null;
  downtime: Downtime | null;
}

export interface PlantGlance {
  lines: LineGlance[] | null;
  late_demand: number | null;
  open_triggers: number | null;
  approvals: number | null;
}

export function lineState(q: FloorQueueResponse | null, down: Downtime | null): { state: LineState; current: string | null } {
  const cur = q?.items.find((r) => r.status === "running" || r.status === "setup") ?? q?.items.find((r) => r.status === "paused") ?? null;
  const label = cur ? `${cur.wo.number} op ${cur.seq} ${cur.name}` : null;
  if (down || q?.down) return { state: "down", current: label };
  if (cur?.status === "paused") return { state: "paused", current: label };
  if (cur) return { state: "running", current: label };
  return { state: "idle", current: null };
}

const MAX_LINES = 40;

/** A figure the role cannot read becomes null; a network failure or abort is passed on (offline glance). */
function soft(e: unknown): null {
  if (isNetworkError(e) || (e instanceof DOMException && e.name === "AbortError")) throw e;
  return null;
}

export async function loadLines(ws: string | null, signal?: AbortSignal): Promise<LineGlance[]> {
  const headers = workspaceOverride(ws);
  const [lines, down] = await Promise.all([
    mfgRequest<List<LineRecord>>("/lines", { query: { active: true }, signal, headers }),
    mfgRequest<Page<Downtime>>("/downtime", { query: { open: true, limit: 200 }, signal, headers }).catch(soft),
  ]);
  const downBy = new Map((down?.items ?? []).map((d) => [d.line.id, d]));
  const ls = lines.items.slice(0, MAX_LINES);
  const queues = await Promise.all(
    ls.map((l) => mfgRequest<FloorQueueResponse>("/floor/queue", { query: { line_id: l.id }, signal, headers }).catch(soft)),
  );
  return ls.map((l, i) => {
    const q = queues[i];
    const d = downBy.get(l.id) ?? q?.down ?? null;
    const s = lineState(q, d);
    return { id: l.id, code: l.code, name: l.name, state: s.state, current: s.current, downtime: d };
  });
}

export async function plantGlance(ws: string | null, signal?: AbortSignal): Promise<PlantGlance> {
  const headers = workspaceOverride(ws);
  const [lines, published, triggers, approvals] = await Promise.all([
    loadLines(ws, signal).catch(soft),
    mfgRequest<ApsRunRecord>("/aps/runs/published", { signal, headers }).catch(soft),
    mfgRequest<TriggerPage>("/replan/triggers", { query: { status: "open", limit: 1 }, signal, headers }).catch(soft),
    mfgRequest<ApprovalsResponse>("/approvals", { signal, headers }).catch(soft),
  ]);
  return {
    lines,
    late_demand: published?.summary ? published.summary.late_demand_count ?? published.summary.demand_lines_late ?? null : null,
    open_triggers: triggers ? triggers.counts?.open ?? triggers.total : null,
    approvals: approvals ? approvals.items.length : null,
  };
}

export function countStates(lines: LineGlance[] | null): Record<LineState, number> | null {
  if (!lines) return null;
  const c: Record<LineState, number> = { running: 0, paused: 0, down: 0, idle: 0 };
  for (const l of lines) c[l.state]++;
  return c;
}
