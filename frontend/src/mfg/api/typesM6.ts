/**
 * M6 types (docs/M6-DESIGN.md 1-3, 5), aligned to the frozen S0 contract: `superplanner/assistant/model.py`,
 * `superplanner/mfg/model_m6.py`, `superplanner/push/model.py` and their fixture
 * `superplanner/assistant/fixtures/example_m6.json` (typed copy: `contractExamplesM6.ts`).
 */
import type { Downtime } from "./typesM4";

type EntityId = string;
type IsoDateTime = string;

// ---------------------------------------------------------------- 1.1 status
/** P2 2.10 codes plus the assistant's own. Unknown codes are shown as they come. */
export type AiCode =
  | "AI_DISABLED"
  | "AI_SDK_MISSING"
  | "AI_NO_CREDENTIALS"
  | "AI_PLANT_OPTED_OUT"
  | "AI_FORBIDDEN"
  | "AI_BUSY"
  | "AI_BUDGET_EXCEEDED"
  | "AI_RATE_LIMITED"
  | "AI_AUTH_FAILED"
  | "AI_API_ERROR"
  | "AI_CONNECTION_ERROR"
  | "AI_UNEXPECTED"
  | "AI_REFUSED"
  | "AI_TRUNCATED"
  | "AI_ROUND_LIMIT"
  | "AI_TURN_LOST"
  | "AI_CANCELLED"
  | "AI_WHATIF_NOT_ALLOWED"
  | "AI_TURN_RUNNING"
  | (string & {});

export type QuickKind = "why_late" | "limits" | "changes";

export interface BudgetLeft {
  user: number;
  plant: number;
}

export interface AssistantPlantSettings {
  assistant_enabled: boolean;
  assistant_allow_whatif: boolean;
}

export interface AssistantStatus {
  available: boolean;
  /** AiCode when unavailable */
  code: AiCode | null;
  message: string;
  privacy_notice: string;
  budget_left: BudgetLeft;
  plant: AssistantPlantSettings;
  model: string;
  max_text_chars: number;
  max_tool_rounds: number;
  quick_kinds: QuickKind[];
}

// ---------------------------------------------------------------- 1.5 citations
export interface Citation {
  /** "R7" (assistant answers) or "Q2" (quick explanations) */
  ref: string;
  type: string;
  id: string;
  label: string;
  /** server-built internal path; anything that is not an app path is shown as text */
  link: string;
}

// ---------------------------------------------------------------- 1.4 draft cards
export type DraftKind = "expedite_po_schedule" | "release_planned_orders" | "open_overtime" | "schedule_edit" | "create_pr" | "raise_priority" | "whatif_run";

export interface IfMatchOf {
  type: string;
  id: string;
  row_version: number;
}

export interface DraftCard {
  draft_id: string;
  kind: DraftKind | (string & {});
  summary: string;
  method: "POST" | "PUT";
  /** the exact request, `/api/v1/...` */
  path: string;
  body: Record<string, unknown>;
  if_match_of: IfMatchOf | null;
  required_permission: string;
  /** the asking user holds `required_permission` (the UI disables Apply otherwise) */
  allowed: boolean;
  applied_at: IsoDateTime | null;
  applied_status: "succeeded" | "failed" | null;
  response_ref: string | null;
}

export interface DraftApplied {
  status: "succeeded" | "failed";
  response_ref: string | null;
}

// ---------------------------------------------------------------- 1.2 turns and conversations
export type TurnStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type ContextType = "demand_line" | "demand_order" | "work_order" | "item" | "purchase_order" | "line" | "aps_run" | "mrp_run" | "eco" | "supplier" | "page";

export interface TurnContext {
  type: ContextType;
  id: string;
}

export interface TurnStep {
  at: IsoDateTime;
  kind: "thinking" | "tool" | "answer" | "note";
  /** tool name */
  name: string | null;
  /** "tool: demand_status (DO-KV-003/10)" */
  summary: string;
  ok: boolean;
}

export interface TurnError {
  code: AiCode;
  message: string;
}

export interface AssistantTurn {
  id: EntityId;
  conversation_id: EntityId;
  status: TurnStatus;
  user_text: string;
  context: TurnContext | null;
  allow_whatif: boolean;
  steps: TurnStep[];
  /** markdown subset; markers [R7] resolved through `citations` */
  answer: string | null;
  citations: Citation[];
  drafts: DraftCard[];
  error: TurnError | null;
  model: string | null;
  fallback_code: string | null;
  tokens: { input: number; output: number; cache_read: number };
  rounds: number;
  created_at: IsoDateTime;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
}

export interface Conversation {
  id: EntityId;
  title: string;
  allow_whatif: boolean;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  /** number of turns */
  turns: number;
}

export interface ConversationDetail extends Conversation {
  /** oldest first */
  history: AssistantTurn[];
}

export interface ConversationInput {
  title: string;
  allow_whatif: boolean;
}

export interface TurnInput {
  text: string;
  context: TurnContext | null;
  allow_whatif: boolean;
}

export interface TurnAccepted {
  turn_id: string;
  conversation_id: string;
  status: TurnStatus;
}

// ---------------------------------------------------------------- 1.7 quick explanations (A2)
export interface QuickItem {
  text: string;
  /** citation refs (Q1, Q2, ...) */
  refs: string[];
}

export interface QuickExplanation {
  kind: QuickKind;
  title: string;
  subject: { type: string; id: string; label: string } | null;
  sections: { title: string; items: QuickItem[] }[];
  citations: Citation[];
  /** the existing endpoints the answer came from */
  sources: string[];
  empty_message: string;
}

// ---------------------------------------------------------------- 2 approvals (M5) and downtime ack (M4)
export type ApprovalKind = "pr" | "eco" | "replan_proposal" | "overtime";

export interface ApprovalAction {
  label: string;
  method: "POST" | "PUT";
  /** `/api/v1/...` */
  path: string;
  body: Record<string, unknown>;
}

export interface ApprovalItem {
  kind: ApprovalKind;
  /** PR / CR / run id; overtime: `<run>:<line>:<start>` */
  id: string;
  number: string;
  title: string;
  summary: string;
  waiting_since: IsoDateTime | null;
  permission: string;
  /** If-Match for the actions (null: none needed) */
  row_version: number | null;
  actions: ApprovalAction[];
  link: string;
}

export interface ApprovalsResponse {
  items: ApprovalItem[];
  counts: Partial<Record<ApprovalKind, number>>;
}

export type DowntimeM6 = Downtime & { acknowledged_by?: { id: string; code?: string; name: string } | null; acknowledged_at?: IsoDateTime | null };

// ---------------------------------------------------------------- 2 Web Push
export type PushTopic = "critical_alerts" | "approvals" | "digest_ready";

export interface VapidPublicKey {
  enabled: boolean;
  public_key: string | null;
  topics: PushTopic[];
}

export interface PushSubscriptionInput {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  topics: PushTopic[];
}

export interface PushSubscriptionRecord {
  id: EntityId;
  endpoint_host: string;
  topics: PushTopic[];
  user_agent: string;
  created_at: IsoDateTime;
  /** review: the list answers active / inactive only (no delivery failure details); older fields optional */
  active?: boolean;
  last_success_at?: IsoDateTime | null;
  failures?: number;
}

/** what the service worker receives */
export interface PushPayload {
  title: string;
  body: string;
  link: string;
  topic: PushTopic;
  tag: string | null;
}

// ---------------------------------------------------------------- 3 dashboards and digests
export type DashboardPeriod = "4w" | "13w" | "52w";
export type TileStatus = "ok" | "watch" | "alert" | "n/a";

export interface Threshold {
  alert_below?: number | null;
  watch_below?: number | null;
  watch_above?: number | null;
  alert_above?: number | null;
}

export interface DashboardTile {
  value: number | null;
  /** "%" (a fraction, 0.91 = 91 %), "h", "count", a currency code, "turns" */
  unit: string;
  trend: { period: string; value: number | null }[];
  status: TileStatus;
  thresholds: Threshold & Record<string, unknown>;
  /** internal UI paths */
  drill: { label: string; path: string }[];
  /** tile specific breakdown */
  details: Record<string, unknown>;
  note: string;
}

export interface DashboardResponse {
  as_of: IsoDateTime;
  period: DashboardPeriod;
  plant: { owner_id: string; name: string; currency?: string; time_zone?: string } & Record<string, unknown>;
  tiles: Record<string, DashboardTile>;
  source: "primary" | "replica";
  computed_ms: number;
}

export interface OrgDashboardResponse {
  as_of: IsoDateTime;
  period: DashboardPeriod;
  org: { id: string; name: string } & Record<string, unknown>;
  plants: { plant: { owner_id: string; code?: string | null; name: string }; tiles: Record<string, DashboardTile> }[];
  /** sums / weighted averages (`details.weights` states the weights) */
  totals: Record<string, DashboardTile>;
  computed_ms: number;
}

export type ThresholdKey = "otd" | "adherence" | "fpy" | "backlog_load" | "material_risk" | "late_pos";

export interface ThresholdsInput {
  thresholds: Partial<Record<ThresholdKey, Threshold>>;
}

export interface DigestInput {
  scope: "plant" | "org";
  scope_id: string;
  frequency: "daily" | "weekly";
  /** HH:MM, plant (or org) time */
  local_time: string;
  /** 0 = Monday; weekly only */
  weekday: number | null;
}

export interface DigestSubscription extends DigestInput {
  id: EntityId;
  scope_label: string;
  time_zone: string;
  created_at: IsoDateTime;
  last_sent_at: IsoDateTime | null;
}
