/**
 * M6 types (docs/M6-DESIGN.md 1-3, 5): planning assistant, approvals inbox, downtime acknowledgement, Web Push,
 * dashboards and digests. Written from the design before the S0 fixture
 * (`backend/superplanner/assistant/fixtures/example_m6.json`); fields the design leaves open are the UI's reading
 * and listed in 11.WP-U. `contractExamplesM6.ts` is the typed copy of the fixture.
 */
import type { Downtime } from "./typesM4";
import type { OpenShift } from "./typesM3";
import type { Permission } from "./typesM2";

type EntityId = string;
type IsoDateTime = string;

// ---------------------------------------------------------------- 1.1 status
/** P2 2.10 codes plus the M6 ones (5). Unknown codes are shown as they come. */
export type AiCode =
  | "AI_DISABLED"
  | "AI_SDK_MISSING"
  | "AI_NO_CREDENTIALS"
  | "AI_PLANT_OPTED_OUT"
  | "AI_BUDGET_EXCEEDED"
  | "AI_WHATIF_NOT_ALLOWED"
  | "AI_TURN_RUNNING"
  | "AI_BUSY"
  | "AI_RATE_LIMITED"
  | "AI_AUTH_FAILED"
  | "AI_API_ERROR"
  | "AI_CONNECTION_ERROR"
  | "AI_REFUSED"
  | "AI_TRUNCATED"
  | "AI_UNEXPECTED"
  | "MFG_FORBIDDEN"
  | (string & {});

export interface AssistantStatus {
  available: boolean;
  /** why not available (null when available) */
  code: AiCode | null;
  privacy_notice: string;
  /** tokens left today; a number (the smaller of user / plant) or both */
  budget_left: number | { user: number; plant: number } | null;
  /** `plant.assistant_allow_whatif` (absent: the switch is offered and the server decides) */
  allow_whatif?: boolean;
}

// ---------------------------------------------------------------- 1.5 citations
export interface Citation {
  /** "R7" */
  ref: string;
  type: string;
  id: string;
  label: string;
  /** server-built internal path (M1 11.3 style); anything else is shown as text */
  link: string | null;
}

// ---------------------------------------------------------------- 1.4 draft cards
export type DraftKind =
  | "expedite_po_schedule"
  | "release_planned_orders"
  | "open_overtime"
  | "schedule_edit"
  | "create_pr"
  | "raise_priority"
  | "whatif_run"
  | (string & {});

export interface DraftCard {
  draft_id: string;
  kind: DraftKind;
  /** plain-language summary of what Apply does */
  summary: string;
  method: "POST" | "PUT" | "PATCH" | "DELETE";
  /** API path, `/api/v1/...` or relative to `/api/v1` */
  path: string;
  body: unknown;
  if_match_of?: { type: string; id: string; row_version: number } | null;
  required_permission: Permission | (string & {});
  applied_at?: IsoDateTime | null;
}

export interface DraftAppliedReport {
  status: "applied" | "failed";
  /** id of the record the call answered with, or the error code */
  response_ref: string | null;
}

// ---------------------------------------------------------------- 1.2 turns and conversations
export type TurnStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

/** Design: `thinking`, `tool: <name> (<summary>)`, `answer`; the object form is accepted too. */
export type TurnStep = string | { kind: "thinking" | "tool" | "answer" | (string & {}); name?: string | null; summary?: string | null; at?: IsoDateTime | null };

export interface AssistantTurn {
  id: EntityId;
  conversation_id: EntityId;
  status: TurnStatus;
  user_text: string;
  allow_whatif?: boolean;
  steps: TurnStep[];
  /** markdown subset: paragraphs, lists, bold, code; never HTML, images or links */
  answer: string | null;
  citations: Citation[];
  drafts: DraftCard[];
  /** failure (P2 2.10 code + readable message) */
  error?: { code: AiCode; message: string } | null;
  error_code?: AiCode | null;
  /** notes such as "draft dropped: ..." or the round limit */
  notes?: string[];
  model?: string | null;
  fallback_code?: string | null;
  started_at?: IsoDateTime | null;
  finished_at?: IsoDateTime | null;
  created_at?: IsoDateTime | null;
}

export interface Conversation {
  id: EntityId;
  title: string;
  allow_whatif: boolean;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  turns?: AssistantTurn[];
}

export interface TurnInput {
  text: string;
  context?: { type: string; id: string } | null;
  allow_whatif: boolean;
}

// ---------------------------------------------------------------- 1.7 quick explanations (A2)
export type QuickKind = "why_late" | "limits" | "changes";

export interface QuickExplanation {
  kind: QuickKind;
  title: string;
  /** same markdown subset and markers as an assistant answer */
  answer: string;
  citations: Citation[];
  /** nothing to explain (e.g. not late) */
  empty?: boolean;
}

// ---------------------------------------------------------------- 2 approvals (M5) and downtime (M4)
export type ApprovalKind = "pr" | "eco" | "proposal" | "overtime";

export interface ApprovalItem {
  kind: ApprovalKind;
  /** PR / ECO / proposal run id; for overtime the run whose suggestions these are */
  id: EntityId;
  row_version: number;
  /** "PR-0012", "ECO-0003", "Replan 05-11 14:20", "Overtime SMT-1 Sat" */
  label: string;
  summary: string;
  link: string | null;
  created_at: IsoDateTime | null;
  requested_by?: { id: string; name: string } | null;
  /** proposal: the published run it would replace */
  base_run_id?: EntityId | null;
  /** overtime: the windows to open with their effect */
  shifts?: OpenShift[];
  cost?: number | null;
  tardiness_saved_minutes?: number | null;
  /** PR: total value; ECO: affected items, ... */
  facts?: { label: string; value: string }[];
}

export interface ApprovalsResponse {
  items: ApprovalItem[];
  counts?: Partial<Record<ApprovalKind, number>>;
}

export type DowntimeM6 = Downtime & { acknowledged_by?: { id: string; code?: string; name: string } | null; acknowledged_at?: IsoDateTime | null };

// ---------------------------------------------------------------- 2 Web Push
export type PushTopic = "critical_alerts" | "approvals" | "digest_ready";

export interface PushSubscriptionInput {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  topics: PushTopic[];
}

export interface PushSubscriptionRecord {
  id: EntityId;
  topics: PushTopic[];
  created_at: IsoDateTime;
}

// ---------------------------------------------------------------- 3 dashboards and digests
export type DashboardPeriod = "4w" | "13w" | "52w";
export type TileStatus = "ok" | "watch" | "alert" | "na" | (string & {});

export interface TrendPoint {
  /** week start / label */
  x: string;
  y: number | null;
}

export interface DashboardTile {
  value: number | null;
  unit: string;
  trend: (number | null)[] | TrendPoint[];
  status: TileStatus;
  thresholds: Record<string, number> | null;
  /** internal link (server-built) or `{label, link}` */
  drill: string | { label: string; link: string } | null;
  label?: string;
  note?: string | null;
  /** secondary figures ("items short: 4", "value: 12,400") */
  details?: { label: string; value: number | string | null; unit?: string }[];
}

export interface DashboardResponse {
  as_of: IsoDateTime;
  period: DashboardPeriod;
  tiles: Record<string, DashboardTile>;
}

export interface OrgDashboardPlant {
  owner_id: string;
  plant_name: string;
  plant_code?: string | null;
  tiles: Record<string, DashboardTile>;
}

export interface OrgDashboardResponse {
  as_of: IsoDateTime;
  period: DashboardPeriod;
  plants: OrgDashboardPlant[];
  totals: Record<string, DashboardTile & { weights?: string | null }>;
}

export type DashboardThresholds = Record<string, { watch?: number | null; alert?: number | null }>;

export interface DigestSubscription {
  id: EntityId;
  scope: "plant" | "org";
  scope_id: string;
  frequency: "daily" | "weekly";
  local_time: string;
  weekday: number | null;
  last_sent_at: IsoDateTime | null;
}

export type DigestInput = Omit<DigestSubscription, "id" | "last_sent_at">;

export interface DigestList {
  items: DigestSubscription[];
  /** false when the server has no SMTP (digest subscriptions are refused, 422 DIGEST_NO_SMTP) */
  email_available?: boolean;
}

/** M6 plant columns (6), sent with the plant PUT when the server knows them. */
export interface PlantM6Fields {
  assistant_enabled?: boolean;
  assistant_allow_whatif?: boolean;
  dashboard_thresholds?: DashboardThresholds | null;
}
