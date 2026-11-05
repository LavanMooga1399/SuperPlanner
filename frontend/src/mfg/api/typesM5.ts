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
export interface AuthConfig {
  auth_mode: "single_user" | "accounts";
  signup_enabled?: boolean;
  sso: { enabled: boolean; label?: string | null; required_domains?: string[] };
  totp: { available: boolean };
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
  expires_in_days?: number;
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
  plant_count?: number;
  member_count?: number;
  row_version?: number;
}

export interface OrgMember {
  id: EntityId;
  user: UserBrief & { kind?: string; disabled?: boolean; sso_linked?: boolean; totp_enabled?: boolean };
  org_role: OrgRole;
  disabled?: boolean;
  plants?: { plant_owner_id: string; code: string; roles: (Role | "plant_admin")[] }[];
}

export interface OrgPlant {
  id: EntityId;
  code: string;
  name: string;
  plant_owner_id: string;
  member_count?: number;
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
  status: "queued" | "running" | "completed" | "failed";
  results: { plant_owner_id: string; code?: string; status: string; counts?: Record<string, number>; errors?: { message: string }[] }[];
}

export interface OrgOverviewPlant {
  plant_owner_id: string;
  code: string;
  name: string;
  visible: boolean;
  kpis?: { otd?: number | null; oee?: number | null; adherence?: number | null; utilisation?: number | null };
  late_demand?: number;
  open_triggers?: number;
  integration?: { enabled: boolean; dead_deliveries?: number; pending_deliveries?: number; last_inbound_at?: IsoDateTime | null; rejected_last_24h?: number } | null;
}

export interface OrgOverview {
  org: Org;
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

export interface IntegrationSettings {
  enabled: boolean;
  adapter: string;
  sor: Partial<Record<SorEntity, SorValue>>;
  /** 14 Q2: who books goods receipts against POs in this plant */
  goods_receipts_owner: "erp" | "superplanner";
  /** ERP-owned fields per entity when SoR = erp (4.4), for the read-only indicators */
  erp_owned_fields?: Partial<Record<SorEntity, string[]>>;
  filedrop?: { enabled: boolean; plant_code?: string | null; poll_seconds?: number };
  export?: { enabled: boolean; interval_minutes: number };
  row_version: number;
}

export interface Endpoint {
  id: EntityId;
  name: string;
  url: string;
  event_types: string[];
  active: boolean;
  created_at?: IsoDateTime;
  stats?: { pending: number; dead: number; delivered_24h?: number; last_delivered_at?: IsoDateTime | null; last_error?: string | null; blocked?: boolean };
  row_version?: number;
}

export interface EndpointInput {
  name: string;
  url: string;
  event_types: string[];
  active: boolean;
}

/** the signing secret is in the create response only */
export interface EndpointCreated extends Endpoint {
  secret: string;
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
  source: "rest" | "filedrop" | "publish" | string;
  entity: string;
  mode: string;
  idempotency_key?: string | null;
  filename?: string | null;
  status: "queued" | "processing" | "completed" | "partial" | "failed";
  counts: { created: number; updated: number; unchanged: number; rejected: number; total?: number };
  received_at: IsoDateTime;
  finished_at?: IsoDateTime | null;
}

export interface BatchDetail extends Batch {
  results: BatchRecordResult[];
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

export type DeliveryStatus = "pending" | "retrying" | "delivered" | "dead";

export interface Delivery {
  id: EntityId;
  endpoint: { id: EntityId; name: string };
  event_seq: number;
  event_type: string;
  status: DeliveryStatus;
  attempts: number;
  next_attempt_at: IsoDateTime | null;
  last_error: string | null;
  last_status_code?: number | null;
  delivered_at?: IsoDateTime | null;
  /** waiting behind an earlier failing event of the same endpoint (FIFO) */
  blocked_by_seq?: number | null;
}

export interface MappingProfile {
  id: EntityId;
  name: string;
  file_pattern: string;
  entity: string;
  mapping: Record<string, unknown>;
}

export interface FiledropStatus {
  enabled: boolean;
  plant_code?: string | null;
  counts: { inbox: number; processing: number; error: number };
  last_scan_at: IsoDateTime | null;
  recent: { file: string; status: "archived" | "error" | "processing"; at: IsoDateTime; counts?: Record<string, number>; errors?: number; batch_id?: EntityId | null }[];
}

export type ReconKind = "missing_in_sp" | "missing_in_erp" | "different" | "sor_conflict";

export interface ReconRow {
  entity: string;
  kind: ReconKind;
  ref: string;
  label?: string;
  item?: ItemRef | null;
  location_code?: string | null;
  lot_code?: string | null;
  qty_sp?: number | null;
  qty_erp?: number | null;
  fields?: { field: string; sp: unknown; erp: unknown }[];
}

export interface Reconciliation {
  id: EntityId;
  status: "queued" | "running" | "completed" | "failed";
  entities: string[];
  snapshot: "inline" | "file" | "adapter";
  created_at: IsoDateTime;
  finished_at: IsoDateTime | null;
  summary: Partial<Record<ReconKind, number>> | null;
  results?: ReconRow[];
  error?: { message: string } | null;
}

// ---------------------------------------------------------------- 6 trace
export type TraceKind = "lot" | "serial" | "wo" | "item_stock" | "transfer" | "demand_line";
export type Precision = "exact" | "possible";

export interface TraceNode {
  key?: string;
  kind: TraceKind;
  id: EntityId;
  item: ItemRef | null;
  label: string;
  qty: number | null;
  /** precision of the link from the parent node */
  precision: Precision;
  at: IsoDateTime | null;
  location?: string | null;
  status?: string | null;
  link?: string | null;
  customer?: string | null;
  plant?: { code: string; visible: boolean } | null;
  children?: TraceNode[];
  /** flat form: parent node key (either form is accepted) */
  parent_key?: string | null;
  depth?: number;
}

export interface TraceResponse {
  direction: "backward" | "forward";
  root: TraceNode;
  nodes?: TraceNode[];
  truncated: boolean;
  counts?: { nodes: number; exact: number; possible: number };
}

export interface WhereUsedResponse {
  item: ItemRef;
  lots: { id: EntityId; lot_code: string; supplier_lot?: string | null; on_hand?: number }[];
  uses: TraceNode[];
  truncated?: boolean;
}

export interface RecallSource {
  kind?: "lot" | "serial" | "wo";
  id?: EntityId;
  item_id?: EntityId;
  supplier_lot?: string;
}

export interface RecallUnit {
  kind: "serial" | "lot";
  id: EntityId;
  label: string;
  item: ItemRef;
  status: "in_stock" | "wip" | "shipped" | "consumed" | string;
  precision: Precision;
  location?: string | null;
  wo?: { id: EntityId; number: string; op_seq?: number | null } | null;
  demand_order?: { id: EntityId; number: string } | null;
  customer?: string | null;
  programme?: string | null;
  shipped_at?: IsoDateTime | null;
  parent?: { kind: string; id: EntityId; label: string } | null;
  path: string[];
  on_hold?: boolean;
  qty?: number | null;
}

export interface Recall {
  id: EntityId;
  number: string;
  name: string;
  created_at: IsoDateTime;
  created_by?: UserBrief | null;
  sources: RecallSource[];
  include_possible: boolean;
  summary: { units: number; lots: number; wos: number; in_stock: number; wip: number; shipped: number; consumed: number; customers: number; exact: number; possible: number };
  units?: RecallUnit[];
  by_customer?: { customer: string; programme?: string | null; units: number; exact: number; possible: number }[];
  quarantine?: { lots: { id: EntityId; lot_code: string; item: ItemRef; on_hand: number; location: string | null; on_hold: boolean }[]; open_pos: { id: EntityId; number: string; item: ItemRef; qty: number }[] };
  quarantined_at?: IsoDateTime | null;
}

export interface QuarantineResult {
  postings: { id: EntityId; number?: string }[];
  lots_on_hold: number;
  moved: number;
}

// ---------------------------------------------------------------- 5 ECO
export type CrStatus = "draft" | "submitted" | "approved" | "rejected" | "implemented" | "cancelled";

export interface CrItem {
  id: EntityId;
  doc_type: "bom" | "routing";
  doc_id: EntityId;
  doc?: { id: EntityId; item: ItemRef; revision?: string; version?: number; status?: string; label?: string } | null;
  supersedes_doc_id: EntityId | null;
  supersedes?: { id: EntityId; revision?: string; version?: number; label?: string } | null;
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
  requested_by: UserBrief | null;
  submitted_by?: UserBrief | null;
  approved_by: UserBrief | null;
  approved_at: IsoDateTime | null;
  implemented_at: IsoDateTime | null;
  effectivity: { mode: "date" | "serial" | "use_up"; date?: IsoDate | null; serial_from?: number | null };
  note: string;
  items: CrItem[];
  created_at?: IsoDateTime;
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

export interface EcoImpact {
  computed_at?: IsoDateTime;
  explosion_delta: { parent: ItemRef; added: { item: ItemRef; qty: number }[]; removed: { item: ItemRef; qty: number }[]; changed: { item: ItemRef; qty_before: number; qty_after: number }[] }[];
  open_wos: { wo: { id: EntityId; number: string; status: string }; item: ItemRef; differences: string[] }[];
  planned_orders?: { order: { id: EntityId; number: string }; item: ItemRef; differences: string[] }[];
  open_pos: { po: { id: EntityId; number: string }; item: ItemRef; qty: number; due?: IsoDate | null }[];
  phased_out: { item: ItemRef; on_hand: number; on_order: number; value: number | null }[];
  mrp_delta: { demand_line: string; order?: string; before: IsoDate | null; after: IsoDate | null }[];
  suggested_use_up_date: IsoDate | null;
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
  name: string;
}

export interface TransferLine {
  id: EntityId;
  line_no: number;
  item: ItemRef;
  qty: number;
  qty_shipped: number;
  qty_received: number;
  ship_date: IsoDate;
  receive_date: IsoDate;
  /** destination item matched by external_ref / part number */
  dest_item?: ItemRef | null;
}

export interface TransferOrder {
  id: EntityId;
  number: string;
  status: TransferStatus;
  /** outbound = this plant ships (source); inbound = the mirror in the receiving plant */
  direction: "outbound" | "inbound";
  source_plant: PlantRef;
  dest_plant: PlantRef;
  mirror_of?: EntityId | null;
  lines: TransferLine[];
  note: string;
  created_at?: IsoDateTime;
  row_version: number;
}

export interface TransferInput {
  dest_plant_owner_id: string;
  note: string;
  lines: { line_no: number; item_id: EntityId; qty: number; ship_date: IsoDate; receive_date: IsoDate }[];
}

// ---------------------------------------------------------------- 7 audit
export interface AuditEvent {
  id: EntityId;
  seq?: number;
  at: IsoDateTime;
  actor: { id: string; name?: string | null; kind?: string | null; token_id?: string | null } | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary?: string | null;
  details?: Record<string, unknown> | null;
  chain_hash: string | null;
}

export interface AuditVerify {
  ok: boolean;
  checked: number;
  first_broken?: { id: EntityId; at: IsoDateTime } | null;
}

export type { Page as PageM5 } from "./types";
