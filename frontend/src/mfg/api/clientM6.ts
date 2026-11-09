/** M6 calls (docs/M6-DESIGN.md 5): assistant A1-A10, push M1-M3, downtime ack M4, approvals M5, dashboards D1-D7. */
import { ifMatch, mfgDownload, mfgRequest, v1Raw, v1Request, type MfgRawResponse } from "./client";
import type {
  ApprovalAction,
  ApprovalsResponse,
  AssistantPlantSettings,
  AssistantStatus,
  AssistantTurn,
  Conversation,
  ConversationDetail,
  ConversationInput,
  DashboardPeriod,
  DashboardResponse,
  DigestInput,
  DigestSubscription,
  DowntimeM6,
  DraftApplied,
  DraftCard,
  OrgDashboardResponse,
  PushSubscriptionInput,
  PushSubscriptionRecord,
  QuickExplanation,
  QuickKind,
  ThresholdsInput,
  TurnAccepted,
  TurnInput,
  VapidPublicKey,
} from "./typesM6";

const enc = encodeURIComponent;
const A = "/assistant";

// ---------------------------------------------------------------- A1-A10 assistant
export const getAssistantStatus = (signal?: AbortSignal) => mfgRequest<AssistantStatus>(`${A}/status`, { signal });
export const getQuickExplanation = (query: { kind: QuickKind; type?: string; id?: string }, signal?: AbortSignal) =>
  mfgRequest<QuickExplanation>(`${A}/quick`, { query: { ...query }, signal });
export const listConversations = (signal?: AbortSignal) => mfgRequest<{ items: Conversation[] }>(`${A}/conversations`, { query: { limit: 50 }, signal });
export const createConversation = (body: ConversationInput) => mfgRequest<Conversation>(`${A}/conversations`, { method: "POST", body });
export const getConversation = (id: string, signal?: AbortSignal) => mfgRequest<ConversationDetail>(`${A}/conversations/${enc(id)}`, { signal });
export const deleteConversation = (id: string) => mfgRequest<void>(`${A}/conversations/${enc(id)}`, { method: "DELETE" });
export const startTurn = (conversationId: string, body: TurnInput) =>
  mfgRequest<TurnAccepted>(`${A}/conversations/${enc(conversationId)}/turns`, { method: "POST", body });
export const getTurn = (id: string, signal?: AbortSignal) => mfgRequest<AssistantTurn>(`${A}/turns/${enc(id)}`, { signal });
export const cancelTurn = (id: string) => mfgRequest<AssistantTurn>(`${A}/turns/${enc(id)}/cancel`, { method: "POST", body: {} });
export const reportDraftApplied = (draftId: string, body: DraftApplied) =>
  mfgRequest<unknown>(`${A}/drafts/${enc(draftId)}/applied`, { method: "POST", body });
/** owner / plant admin: plant opt-out and the what-if permission (1.1) */
export const putAssistantSettings = (body: AssistantPlantSettings) => mfgRequest<AssistantPlantSettings>("/plant/assistant", { method: "PUT", body });

/**
 * A server-built request (draft card, approval action), checked before it is sent: POST/PUT and an `/api/v1` path
 * without a scheme, host, query, `..` or `//` (the server allow-lists drafts too, 1.4). Returns the path relative
 * to `/api/v1`, or null.
 */
export function requestPath(r: { method: string; path: string }): string | null {
  if (r.method !== "POST" && r.method !== "PUT") return null;
  const p = r.path;
  if (typeof p !== "string" || !p.startsWith("/api/v1/")) return null;
  const rel = p.slice("/api/v1".length);
  if (/^\/\/|\\|\.\.|[\s?#]|:\/\//.test(rel) || rel.startsWith("/api/")) return null;
  if (!/^\/[A-Za-z0-9_\-/.~%:]+$/.test(rel)) return null;
  return rel;
}

/**
 * Send a server-built request as the user: session and CSRF (authFetch), workspace header, If-Match when the
 * record version is known (a change since then answers 412), and an idempotency key.
 */
export function sendBuiltRequest(r: { method: string; path: string; body: unknown }, opts: { version?: number | null; key: string }): Promise<MfgRawResponse<unknown>> {
  const path = requestPath(r);
  if (!path) return Promise.reject(new Error("This request cannot be sent from the app."));
  const headers: Record<string, string> = { "Idempotency-Key": opts.key };
  if (opts.version !== undefined && opts.version !== null) Object.assign(headers, ifMatch(opts.version));
  return v1Raw<unknown>(path, { method: r.method, body: r.body ?? {}, headers });
}

/** Apply = the draft's own request (1.4), If-Match of the record it was built from, the draft id as key. */
export const applyDraft = (d: DraftCard) => sendBuiltRequest(d, { version: d.if_match_of?.row_version ?? null, key: `asst-${d.draft_id}` });

/** An approval action (M5 `/mfg/approvals`), If-Match = the item's `row_version`. */
export const runApprovalAction = (a: ApprovalAction, version: number | null, body: Record<string, unknown>, key: string) =>
  sendBuiltRequest({ method: a.method, path: a.path, body }, { version, key });

// ---------------------------------------------------------------- M1-M3 push (session)
export const getVapidKey = (signal?: AbortSignal) => v1Request<VapidPublicKey>("/push/vapid-public-key", { signal });
export const listPushSubscriptions = (signal?: AbortSignal) => v1Request<{ items: PushSubscriptionRecord[] }>("/push/subscriptions", { signal });
export const createPushSubscription = (body: PushSubscriptionInput) => v1Request<PushSubscriptionRecord>("/push/subscriptions", { method: "POST", body });
export const deletePushSubscription = (id: string) => v1Request<void>(`/push/subscriptions/${enc(id)}`, { method: "DELETE" });

// ---------------------------------------------------------------- M4 downtime ack, M5 approvals
/** Idempotent on the server (key = the queued action id), so offline replays acknowledge once. */
export const acknowledgeDowntime = (id: string, key: string) =>
  mfgRequest<DowntimeM6>(`/downtime/${enc(id)}/acknowledge`, { method: "POST", body: { client_id: key.slice(0, 64) }, headers: { "Idempotency-Key": key } });
export const listApprovals = (signal?: AbortSignal, workspace?: string | null) =>
  mfgRequest<ApprovalsResponse>("/approvals", { signal, headers: workspaceOverride(workspace) });

// ---------------------------------------------------------------- D1-D7 dashboards and digests
export const getDashboard = (period: DashboardPeriod, signal?: AbortSignal) => mfgRequest<DashboardResponse>("/dashboard", { query: { period }, signal });
export const exportDashboard = (period: DashboardPeriod, format: "xlsx" | "csv") => mfgDownload("/dashboard/export", { period, format }, `dashboard.${format}`);
export const getOrgDashboard = (org: string, period: DashboardPeriod, signal?: AbortSignal) =>
  v1Request<OrgDashboardResponse>(`/orgs/${enc(org)}/dashboard`, { query: { period }, signal });
export const listDigests = (signal?: AbortSignal) => v1Request<{ items: DigestSubscription[]; smtp_enabled?: boolean }>("/digests", { signal });
export const createDigest = (body: DigestInput) => v1Request<DigestSubscription>("/digests", { method: "POST", body });
export const deleteDigest = (id: string) => v1Request<void>(`/digests/${enc(id)}`, { method: "DELETE" });
export const putDashboardThresholds = (body: ThresholdsInput) => mfgRequest<unknown>("/plant/dashboard-thresholds", { method: "PUT", body });

/**
 * Another plant's workspace for one call (mobile home over "my plants"): the explicit header wins over the stored
 * one (`rawAt` spreads `opts.headers` last). Null/undefined = the stored workspace.
 */
export function workspaceOverride(ws: string | null | undefined): Record<string, string> | undefined {
  return ws === undefined || ws === null ? undefined : { "X-SP-Workspace": ws };
}
