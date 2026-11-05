/**
 * M5 contract (docs/M5-DESIGN.md 3-9): identity, tokens, organisations, integration, trace/recall, ECO, transfers,
 * audit. Written from the design before the S0 fixture (`backend/superplanner/integration/fixtures/example_m5.json`)
 * existed; to be re-aligned to it as in M3/M4 (15.WP-U). Fields the design leaves open are optional.
 */
import type { EntityId, IsoDate, IsoDateTime, ItemRef } from "./types";
import type { Permission, Role } from "./typesM2";

export interface UserBrief {
  id: string;
  email: string | null;
  display_name: string | null;
}

// ---------------------------------------------------------------- 3.1 / 3.2 identity
/** `GET /auth/config` */
export interface AuthConfig {
  mode: "single_user" | "accounts";
  sso_enabled: boolean;
  sso_label: string;
  sso_required_domains: string[];
  /** false: password sign-in is off on this server */
  password_login: boolean;
}

/** sign-in answered "second factor needed" (200 with these fields, or 401/403 `AUTH_2FA_REQUIRED` details) */
export interface PendingLogin {
  pending_token: string;
  /** totp = enter a code; setup = the organisation requires 2FA and this account has none yet */
  method: "totp" | "setup";
  expires_at?: IsoDateTime | null;
}

export interface TotpStatus {
  enabled: boolean;
  enabled_at: IsoDateTime | null;
  recovery_codes_left: number | null;
  required_by_org: boolean;
}

export interface TotpSetup {
  secret: string;
  otpauth_uri: string;
}

export interface RecoveryCodes {
  recovery_codes: string[];
}

// ---------------------------------------------------------------- 3.3 tokens
export type TokenScope = Permission | "integration.read" | "integration.write";

export interface ApiToken {
  id: EntityId;
  kind: "personal" | "plant";
  name: string;
  prefix: string;
  scopes: TokenScope[];
  workspace_owner_id: string;
  plant_name?: string | null;
  expires_at: IsoDateTime;
  last_used_at: IsoDateTime | null;
  last_used_ip: string | null;
  created_at: IsoDateTime;
  created_by?: UserBrief | null;
  revoked_at: IsoDateTime | null;
}

export interface TokenCreate {
  kind: "personal" | "plant";
  name: string;
  scopes: TokenScope[];
  workspace_owner_id?: string | null;
  expires_days?: number;
}

/** the clear-text token is in this response only */
export interface TokenCreated extends ApiToken {
  token: string;
}

// ---------------------------------------------------------------- 3.4 organisations
export type OrgRole = "org_admin" | "org_member";

export interface Org {
  id: EntityId;
  name: string;
  slug: string;
  require_2fa: boolean;
  my_role?: OrgRole | null;
  plants?: number;
  members?: number;
  row_version?: number;
  created_at?: IsoDateTime;
}

export interface OrgMember {
  id: EntityId;
  user: UserBrief & { disabled?: boolean };
  org_role: OrgRole;
  plants?: { plant_owner_id: string; code: string; roles: (Role | "plant_admin")[] }[];
  row_version?: number;
}

export interface OrgPlant {
  id: EntityId;
  code: string;
  name: string;
  plant_owner_id: string;
  my_roles?: string[];
  row_version?: number;
  created_at?: IsoDateTime;
}

export interface PlantRoleGrant {
  user_id: string;
  roles: (Role | "plant_admin")[];
}

export interface PublishRequest {
  source_plant: string;
  target_plants: string[];
  scope: "items" | "master";
  part_number_prefix?: string | null;
}

export interface PublishJob {
  id: EntityId;
  org_id?: EntityId;
  status: "queued" | "running" | "completed" | "failed";
  /** per target plant owner id */
  results: Record<string, { status?: string; counts?: Record<string, number>; errors?: { message: string }[] }> | null;
}

export interface OrgOverviewPlant {
  plant: { code: string; name?: string; owner_id: string };
  visible: boolean;
  kpis?: { otd?: number | null; oee?: number | null; adherence?: number | null; utilisation?: number | null };
  late_demand?: number | null;
  open_triggers?: number | null;
  integration?: { enabled?: boolean; dead_deliveries?: number; pending_deliveries?: number; last_batch_at?: IsoDateTime | null } | null;
}

export interface OrgOverview {
  org: { id: EntityId; name: string; slug?: string };
  plants: OrgOverviewPlant[];
}

// ---------------------------------------------------------------- 4 integration
export type SorValue = "erp" | "superplanner" | "shared";
export const SOR_ENTITIES = [
  "items",
  "boms",
  "routings",
  "suppliers",
  "item_suppliers",
  "purchase_orders",
  "po_receipts",
  "demand_orders",
  "purchase_requests",
  "work_orders",
  "floor",
  "transfers",
  "stock",
] as const;
export type SorEntity = (typeof SOR_ENTITIES)[number];

/** `GET/PUT /integration/settings` */
export interface IntegrationSettings {
  enabled: boolean;
  adapter: string;
  /** folder name of this plant under the integration volume */
  plant_code: string;
  sor: Partial<Record<SorEntity, SorValue>>;
  /** 14 Q2: who books goods receipts against POs in this plant */
  goods_receipts_owner: "erp" | "superplanner";
  filedrop_enabled: boolean;
  export_enabled: boolean;
  export_interval_minutes: number;
  row_version: number;
  adapters?: string[];
}

export interface Endpoint {
  id: EntityId;
  name: string;
  url: string;
  event_types: string[];
  active: boolean;
  /** last event seq handed to this endpoint */
  cursor: number;
  secret_set: boolean;
  pending: number;
  dead: number;
  row_version: number;
  created_at?: IsoDateTime;
}

/** `secret` required on create (the UI generates one and shows it once); omitted on PUT = keep */
export interface EndpointInput {
  name: string;
  url: string;
  event_types: string[];
  active: boolean;
  secret?: string;
}

export interface ValueMap {
  domain: string;
  external_value: string;
  internal_value: string;
}

export interface RecordError {
  code: string;
  message: string;
  field?: string | null;
}

export interface BatchRecordResult {
  ref: string;
  status: "created" | "updated" | "unchanged" | "rejected";
  id: EntityId | null;
  errors: RecordError[];
}

export interface Batch {
  id: EntityId;
  source?: "rest" | "filedrop" | "publish" | string;
  entity: string;
  mode: string;
  idempotency_key?: string | null;
  filename?: string | null;
  status: "queued" | "processing" | "completed" | "partial" | "failed";
  counts: { created?: number; updated?: number; unchanged?: number; rejected?: number; total?: number };
  received_at: IsoDateTime;
  finished_at?: IsoDateTime | null;
}

export interface BatchDetail extends Batch {
  results: BatchRecordResult[] | null;
}

export interface OutboxEvent {
  seq: number;
  id?: string;
  type: string;
  occurred_at: IsoDateTime;
  entity_ref?: string | null;
  data?: unknown;
}

export interface EventPage {
  items: OutboxEvent[];
  next_after: number;
}

export type DeliveryStatus = "pending" | "delivered" | "dead";

export interface Delivery {
  id: EntityId;
  endpoint_id: EntityId;
  event_seq: number;
  event_type: string | null;
  status: DeliveryStatus;
  attempts: number;
  next_attempt_at: IsoDateTime | null;
  last_error: string | null;
  last_status_code: number | null;
  delivered_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

export interface MappingProfile {
  id: EntityId;
  name: string;
  file_pattern: string;
  mapping: Record<string, unknown>;
  row_version?: number;
}

export interface FiledropStatus {
  enabled: boolean;
  root: string | null;
  inbox: { name?: string; file?: string; size?: number; at?: IsoDateTime }[];
  recent: { file?: string; name?: string; status?: string; at?: IsoDateTime; counts?: Record<string, number>; errors?: number; batch_id?: EntityId | null }[];
  last_poll_at: IsoDateTime | null;
}

export type ReconKind = "missing_in_sp" | "missing_in_erp" | "different";

/** stock rows (other entities: fields as sent) */
export interface ReconRow {
  item?: string;
  item_ref?: string;
  location?: string;
  lot?: string;
  sp_qty?: number | null;
  erp_qty?: number | null;
  delta?: number;
  [k: string]: unknown;
}

export interface Reconciliation {
  id: EntityId;
  entities: string[];
  status: "queued" | "running" | "completed" | "failed";
  /** per entity */
  summary: Record<string, Partial<Record<ReconKind | "sor_conflicts", number>>> | null;
  results: Record<string, Partial<Record<ReconKind | "sor_conflicts", ReconRow[]>>> | null;
  created_at: IsoDateTime;
  finished_at: IsoDateTime | null;
}

/** superplanner.v1 stock_snapshot record (4.2) */
export interface StockSnapshotV1 {
  ref?: string;
  item_ref: string;
  location_code: string;
  lot_code?: string | null;
  qty: number;
  as_at?: IsoDateTime | null;
}

// ---------------------------------------------------------------- 6 trace
export type TraceKind = "lot" | "serial" | "wo" | "item_stock" | "transfer" | "demand_line";
export type Precision = "exact" | "possible";

export interface TraceNode {
  kind: TraceKind;
  id: EntityId;
  item?: ItemRef | null;
  label: string;
  qty?: number | null;
  /** precision of the link from the parent node */
  precision: Precision;
  at?: IsoDateTime | null;
  status?: string | null;
  location?: string | null;
  customer?: string | null;
  plant?: { code: string; visible: boolean } | null;
  link?: string | null;
  depth?: number;
  children?: TraceNode[];
}

export interface TraceResponse {
  root: TraceNode;
  direction: "backward" | "forward";
  depth: number;
  /** number of nodes */
  nodes: number;
  truncated: boolean;
}

export interface WhereUsedResponse {
  items: TraceNode[];
  truncated: boolean;
}

export interface RecallSource {
  kind?: "lot" | "serial" | "wo";
  id?: EntityId;
  item_id?: EntityId;
  supplier_lot?: string;
}

export interface RecallReport {
  units: { serial: string; item: string; status: string; precision: Precision; customer?: string | null; demand_order?: string | null; shipped_on?: IsoDate | null; location?: string | null; wo?: string | null; parent?: string | null; path: string[] }[];
  lots: { lot_code: string; item: string; on_hand: number; location: string | null; on_hold?: boolean; id?: EntityId }[];
  wos: { number: string; status: string; id?: EntityId }[];
  by_customer: { customer: string; units: number; exact?: number; possible?: number }[];
  by_program: { program: string; units: number }[];
  open_pos: { number: string; item?: string; qty?: number }[];
}

export interface Recall {
  id: EntityId;
  number: string;
  name: string;
  sources: RecallSource[];
  include_possible: boolean;
  report: RecallReport | null;
  quarantined_at: IsoDateTime | null;
  row_version: number;
  created_at: IsoDateTime;
  updated_at?: IsoDateTime;
}

export interface QuarantineResult {
  postings?: { id: EntityId; number?: string }[];
  moved?: number;
  lots_on_hold?: number;
  [k: string]: unknown;
}

// ---------------------------------------------------------------- 5 ECO
export type CrStatus = "draft" | "submitted" | "approved" | "rejected" | "implemented" | "cancelled";

export interface CrItem {
  id: EntityId;
  doc_type: "bom" | "routing";
  doc_id: EntityId;
  supersedes_doc_id: EntityId | null;
  disposition: { open_wos: "keep" | "refresh_planned" | "flag"; open_pos: "keep" | "flag_cancel"; stock: "use_up" | "scrap" | "rework" };
}

export interface ChangeRequest {
  id: EntityId;
  number: string;
  title: string;
  reason: string;
  kind: "eco" | "ecn";
  source: "manual" | "erp";
  status: CrStatus;
  priority: number;
  requested_by: UserBrief | string | null;
  approved_by: UserBrief | string | null;
  approved_at: IsoDateTime | null;
  implemented_at: IsoDateTime | null;
  effectivity: { mode: "date" | "serial" | "use_up"; date?: IsoDate | null; serial_from?: number | null };
  note: string;
  items: CrItem[];
  created_at?: IsoDateTime;
  updated_at?: IsoDateTime;
  row_version: number;
}

export interface CrInput {
  title: string;
  reason: string;
  kind: "eco" | "ecn";
  priority: number;
  effectivity: ChangeRequest["effectivity"];
  note: string;
}

export interface CrItemInput {
  doc_type: "bom" | "routing";
  doc_id: EntityId;
  disposition?: Partial<CrItem["disposition"]>;
}

type DeltaEntry = string | { item: string; qty_before?: number; qty_after?: number; qty?: number };

export interface EcoImpact {
  cr_id: EntityId;
  effectivity: ChangeRequest["effectivity"];
  explosion_delta: { parent: string; added: DeltaEntry[]; removed: DeltaEntry[]; changed: DeltaEntry[] }[];
  open_wos: { number: string; component?: string; qty?: number; id?: EntityId; status?: string }[];
  planned_orders: { number?: string; item?: string; qty?: number }[];
  open_purchases: { number: string; item?: string; qty?: number; due?: IsoDate | null }[];
  phase_out_stock: { item: string; on_hand: number; on_order: number; value: number | null }[];
  mrp_delta: { demand_line?: string; order?: string; before?: IsoDate | null; after?: IsoDate | null }[];
  use_up_date: IsoDate | null;
  computed_ms?: number;
}

export interface ReleaseIssue {
  code: string;
  message: string;
  doc?: string | null;
}

// ---------------------------------------------------------------- 3.5 transfers
export type TransferStatus = "draft" | "open" | "shipped" | "partly_shipped" | "received" | "closed" | "cancelled";

export interface PlantRef {
  owner_id: string;
  code: string;
  name?: string;
}

export interface TransferLine {
  id: EntityId;
  line_no: number;
  item_id: EntityId;
  qty: number;
  shipped_qty: number;
  received_qty: number;
  ship_date: IsoDate;
  receive_date: IsoDate;
}

export interface TransferOrder {
  id: EntityId;
  number: string;
  status: TransferStatus;
  /** out = this plant ships (source); in = the mirror in the receiving plant */
  direction: "out" | "in" | "outbound" | "inbound";
  source_plant: PlantRef;
  dest_plant: PlantRef;
  mirror_of: EntityId | null;
  from_location_id: EntityId | null;
  to_location_id: EntityId | null;
  lines: TransferLine[];
  note: string;
  created_at?: IsoDateTime;
  updated_at?: IsoDateTime;
  row_version: number;
}

export const isOutbound = (t: Pick<TransferOrder, "direction">) => t.direction === "out" || t.direction === "outbound";

export interface TransferInput {
  dest_plant_owner_id: string;
  note?: string;
  lines: { line_no?: number; item_id: EntityId; qty: number; ship_date: IsoDate; receive_date: IsoDate }[];
}

// ---------------------------------------------------------------- 7 audit
export interface AuditEvent {
  id: number;
  entity_type: string;
  entity_id: string | null;
  action: string;
  details: Record<string, unknown>;
  actor_id: string | null;
  owner_id: string | null;
  created_at: IsoDateTime;
  chain_hash: string | null;
}

export interface AuditVerify {
  ok: boolean;
  checked: number;
  first_broken?: { id: EntityId; at: IsoDateTime } | null;
}
