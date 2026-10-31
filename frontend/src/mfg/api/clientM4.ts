/** M4 routes #200-226 (docs/M4-DESIGN.md 11) plus the extended M2/M3 ones the floor uses. */
import { ifMatch, mfgRaw, mfgRequest } from "./client";
import type { Page } from "./types";
import type { ApsRunRecord } from "./typesM3";
import type {
  AdherencePage,
  NotificationPage,
  TriggerPage,
  BackflushRetryResult,
  BatchLoad,
  BatchLoadInput,
  Downtime,
  DowntimeInput,
  DowntimeUpdate,
  FloorEventInput,
  FloorEventQuery,
  FloorEventRecord,
  FloorEventResult,
  FloorOperationDetail,
  FloorQueueResponse,
  KpiResponse,
  MfgNotification,
  ReplanTrigger,
  ScanResult,
  SerialStatus,
  Simulation,
  SimulationInput,
  UnitSerial,
  UnitSerialDetail,
  WoOperation,
} from "./typesM4";

const enc = encodeURIComponent;

// ---------------------------------------------------------------- #200-205 floor
export const floorScan = (code: string, signal?: AbortSignal) => mfgRequest<ScanResult>("/floor/scan", { query: { code }, signal });
export const getFloorQueue = (query: { line_id: string; shift?: string; date?: string }, signal?: AbortSignal) =>
  mfgRequest<FloorQueueResponse>("/floor/queue", { query: { ...query }, signal });
export const getFloorOperation = (woOpId: string, signal?: AbortSignal) => mfgRequest<FloorOperationDetail>(`/floor/operations/${enc(woOpId)}`, { signal });

/** #203; `replayed` = the server already had this `client_event_id` (200 + `Idempotent-Replay`). */
export async function postFloorEvent(body: FloorEventInput): Promise<FloorEventResult & { replayed: boolean }> {
  const r = await mfgRaw<FloorEventResult>("/floor/events", { method: "POST", body, headers: { "Idempotency-Key": body.client_event_id } });
  return { ...r.data, replayed: r.status === 200 || r.headers.get("Idempotent-Replay") === "true" };
}
export const listFloorEvents = (query: FloorEventQuery, signal?: AbortSignal) => mfgRequest<Page<FloorEventRecord>>("/floor/events", { query: { ...query }, signal });
export const retryBackflush = (woId?: string) => mfgRequest<BackflushRetryResult>("/floor/backflush/retry", { method: "POST", body: woId ? { wo_id: woId } : {} });

// ---------------------------------------------------------------- #206-207 WO operations
export const listWoOperationsM4 = (woId: string, signal?: AbortSignal) =>
  mfgRequest<{ wo: { id: string; number: string; row_version: number; status?: string; released_to_floor_at?: string | null }; items: WoOperation[] }>(`/work-orders/${enc(woId)}/operations`, { signal });
export const refreshWoOperations = (woId: string, woVersion: number) =>
  mfgRequest<{ items: WoOperation[] }>(`/work-orders/${enc(woId)}/operations/refresh`, { method: "POST", body: {}, headers: ifMatch(woVersion) });

// ---------------------------------------------------------------- #208-210 downtime
export const listDowntime = (query: { line_id?: string; open?: boolean; from?: string; to?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<Page<Downtime>>("/downtime", { query: { ...query }, signal });
/** `idemKey`: the device's action id; the server does not de-duplicate downtime yet (requested, 16.WP-U) but the header is harmless. */
export const createDowntime = (body: DowntimeInput, idemKey?: string) =>
  mfgRequest<Downtime>("/downtime", { method: "POST", body, headers: idemKey ? { "Idempotency-Key": idemKey } : undefined });
export const updateDowntime = (id: string, body: DowntimeUpdate, version: number) =>
  mfgRequest<Downtime>(`/downtime/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });

// ---------------------------------------------------------------- #211-213 batch loads
export const listBatchLoads = (query: { line_id?: string; status?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<Page<BatchLoad>>("/batch-loads", { query: { ...query }, signal });
export const createBatchLoad = (body: BatchLoadInput) => mfgRequest<BatchLoad>("/batch-loads", { method: "POST", body });
export const getBatchLoad = (id: string, signal?: AbortSignal) => mfgRequest<BatchLoad>(`/batch-loads/${enc(id)}`, { signal });

// ---------------------------------------------------------------- #214-215 serials
export const listSerials = (query: { item_id?: string; q?: string; status?: SerialStatus | ""; wo_id?: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
  mfgRequest<Page<UnitSerial>>("/serials", { query: { ...query }, signal });
export const getSerial = (id: string, signal?: AbortSignal) => mfgRequest<UnitSerialDetail>(`/serials/${enc(id)}`, { signal });

// ---------------------------------------------------------------- #216-221 replan, notifications
export const listTriggers = (query: { status?: string | readonly string[]; kind?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<TriggerPage>("/replan/triggers", { query: { ...query }, signal });
export const ignoreTrigger = (id: string, note = "") => mfgRequest<ReplanTrigger>(`/replan/triggers/${enc(id)}/ignore`, { method: "POST", body: { note } });
export const handleTrigger = (id: string, note = "") => mfgRequest<ReplanTrigger>(`/replan/triggers/${enc(id)}/handle`, { method: "POST", body: { note } });
export const runReplan = (triggerIds?: string[]) => mfgRequest<ApsRunRecord>("/replan/run", { method: "POST", body: triggerIds?.length ? { trigger_ids: triggerIds } : {} });
export const listNotifications = (query: { unacked?: boolean; limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<NotificationPage>("/notifications", { query: { ...query }, signal });
export const ackNotification = (id: string) => mfgRequest<MfgNotification>(`/notifications/${enc(id)}/ack`, { method: "POST", body: {} });

// ---------------------------------------------------------------- #222-223 KPIs
export const getKpis = (query: { from: string; to: string; dim?: "plant" | "group" | "line"; dim_id?: string; bucket?: "day" | "week" }, signal?: AbortSignal) =>
  mfgRequest<KpiResponse>("/kpis", { query: { ...query }, signal });
export const getAdherence = (query: { from: string; to: string; line_id?: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
  mfgRequest<AdherencePage>("/kpis/adherence", { query: { ...query }, signal });

// ---------------------------------------------------------------- #224-226 simulations
export const createSimulation = (body: SimulationInput) => mfgRequest<Simulation>("/aps/simulations", { method: "POST", body });
export const getSimulation = (id: string, signal?: AbortSignal) => mfgRequest<Simulation>(`/aps/simulations/${enc(id)}`, { signal });
export const listSimulations = (query: { limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<Page<Simulation>>("/aps/simulations", { query: { ...query }, signal });
