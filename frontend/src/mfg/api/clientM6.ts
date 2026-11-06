/** M6 calls (docs/M6-DESIGN.md 5): assistant A1-A10, push M1-M3, downtime ack M4, approvals M5, dashboards D1-D7. */
import { ifMatch, mfgDownload, mfgRequest, v1Raw, v1Request, type MfgRawResponse } from "./client";
import type {
  ApprovalsResponse,
  AssistantStatus,
  AssistantTurn,
  Conversation,
  DashboardPeriod,
  DashboardResponse,
  DashboardThresholds,
  DigestInput,
  DigestList,
  DigestSubscription,
  DowntimeM6,
  DraftAppliedReport,
  DraftCard,
  OrgDashboardResponse,
  PushSubscriptionInput,
  PushSubscriptionRecord,
  QuickExplanation,
  QuickKind,
  TurnInput,
} from "./typesM6";

const enc = encodeURIComponent;
const A = "/assistant";

// ---------------------------------------------------------------- A1-A10 assistant
export const getAssistantStatus = (signal?: AbortSignal) => mfgRequest<AssistantStatus>(`${A}/status`, { signal });
export const getQuickExplanation = (query: { kind: QuickKind; type?: string; id?: string }, signal?: AbortSignal) =>
  mfgRequest<QuickExplanation>(`${A}/quick`, { query: { ...query }, signal });
export const listConversations = (signal?: AbortSignal) => mfgRequest<{ items: Conversation[] }>(`${A}/conversations`, { signal });
export const createConversation = (body: { title?: string; allow_whatif?: boolean } = {}) => mfgRequest<Conversation>(`${A}/conversations`, { method: "POST", body });
export const getConversation = (id: string, signal?: AbortSignal) => mfgRequest<Conversation>(`${A}/conversations/${enc(id)}`, { signal });
export const deleteConversation = (id: string) => mfgRequest<void>(`${A}/conversations/${enc(id)}`, { method: "DELETE" });
export const startTurn = (conversationId: string, body: TurnInput) =>
  mfgRequest<{ turn_id: string }>(`${A}/conversations/${enc(conversationId)}/turns`, { method: "POST", body });
export const getTurn = (id: string, signal?: AbortSignal) => mfgRequest<AssistantTurn>(`${A}/turns/${enc(id)}`, { signal });
export const cancelTurn = (id: string) => mfgRequest<AssistantTurn>(`${A}/turns/${enc(id)}/cancel`, { method: "POST", body: {} });
export const reportDraftApplied = (draftId: string, body: DraftAppliedReport) =>
  mfgRequest<unknown>(`${A}/drafts/${enc(draftId)}/applied`, { method: "POST", body });

/**
 * A draft's own request, checked before it is sent: a write method and an `/api/v1` path without a scheme, host,
 * `..` or `//` (the server allow-lists them too, 1.4). Returns the path relative to `/api/v1`, or null.
 */
export function draftRequestPath(d: Pick<DraftCard, "method" | "path">): string | null {
  if (!["POST", "PUT", "PATCH", "DELETE"].includes(d.method)) return null;
  let p = d.path;
  if (typeof p !== "string" || !p.startsWith("/")) return null;
  if (p.startsWith("/api/v1/")) p = p.slice("/api/v1".length);
  if (/^\/\/|\\|\.\.|[\s?#]|:\/\//.test(p) || p.startsWith("/api/")) return null;
  if (!/^\/[A-Za-z0-9_\-/.~%]+$/.test(p)) return null;
  return p;
}

/**
 * Apply = the normal API call with the user's session, CSRF (authFetch) and workspace header, If-Match of the
 * record the draft was built from (a change since then answers 412), and the draft id as idempotency key.
 */
export function applyDraft(d: DraftCard): Promise<MfgRawResponse<unknown>> {
  const path = draftRequestPath(d);
  if (!path) return Promise.reject(new Error("This draft does not contain a request the app can send."));
  const headers: Record<string, string> = { "Idempotency-Key": `asst-${d.draft_id}` };
  if (d.if_match_of) Object.assign(headers, ifMatch(d.if_match_of.row_version));
  return v1Raw<unknown>(path, { method: d.method, body: d.method === "DELETE" ? undefined : d.body ?? {}, headers });
}

// ---------------------------------------------------------------- M1-M3 push (session)
export const getVapidKey = (signal?: AbortSignal) => v1Request<{ public_key: string }>("/push/vapid-public-key", { signal });
export const createPushSubscription = (body: PushSubscriptionInput) => v1Request<PushSubscriptionRecord>("/push/subscriptions", { method: "POST", body });
export const deletePushSubscription = (id: string) => v1Request<void>(`/push/subscriptions/${enc(id)}`, { method: "DELETE" });

// ---------------------------------------------------------------- M4 downtime ack, M5 approvals
/** Idempotent on the server (an acknowledged downtime stays acknowledged); the key makes offline replays safe. */
export const acknowledgeDowntime = (id: string, key: string) =>
  mfgRequest<DowntimeM6>(`/downtime/${enc(id)}/acknowledge`, { method: "POST", body: {}, headers: { "Idempotency-Key": key } });
export const listApprovals = (signal?: AbortSignal, workspace?: string | null) =>
  mfgRequest<ApprovalsResponse>("/approvals", { signal, headers: workspaceOverride(workspace) });

// ---------------------------------------------------------------- D1-D7 dashboards and digests
export const getDashboard = (period: DashboardPeriod, signal?: AbortSignal) => mfgRequest<DashboardResponse>("/dashboard", { query: { period }, signal });
export const exportDashboard = (period: DashboardPeriod, format: "xlsx" | "csv") => mfgDownload("/dashboard/export", { period, format }, `dashboard.${format}`);
export const getOrgDashboard = (org: string, period: DashboardPeriod, signal?: AbortSignal) =>
  v1Request<OrgDashboardResponse>(`/orgs/${enc(org)}/dashboard`, { query: { period }, signal });
export const listDigests = (signal?: AbortSignal) => v1Request<DigestList>("/digests", { signal });
export const createDigest = (body: DigestInput) => v1Request<DigestSubscription>("/digests", { method: "POST", body });
export const deleteDigest = (id: string) => v1Request<void>(`/digests/${enc(id)}`, { method: "DELETE" });
export const putDashboardThresholds = (body: { thresholds: DashboardThresholds }) =>
  mfgRequest<{ thresholds: DashboardThresholds }>("/plant/dashboard-thresholds", { method: "PUT", body });

/**
 * Another plant's workspace for one call (mobile home over "my plants"): the explicit header wins over the stored
 * one (`rawAt` spreads `opts.headers` last). Null/undefined = the stored workspace.
 */
export function workspaceOverride(ws: string | null | undefined): Record<string, string> | undefined {
  return ws === undefined || ws === null ? undefined : { "X-SP-Workspace": ws };
}
