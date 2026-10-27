/**
 * TypeScript mirror of the M2 contract (docs/M2-DESIGN.md sections 3, 8.2, 10.2, 12.3 and 12.4). Field names are
 * the JSON names. `contractExamplesM2.ts` types every documented example against these declarations, so `tsc`
 * fails when they drift. M1 shapes stay in `types.ts`; the additive M1 fields of 3.1 are declared here as
 * `ItemM2Fields` / `PlantM2Fields` and merged into the M1 records by intersection.
 */
import type { EntityId, IsoDate, IsoDateTime, ItemRecord, ItemRef, LotRule, MakeBuy, Page, PlantRecord, Ref, Weekday } from "./types";

// ---------------------------------------------------------------- 3 common types
export type Role = "viewer" | "planner" | "purchaser" | "store_keeper" | "approver";
export const ROLES: readonly Role[] = ["viewer", "planner", "purchaser", "store_keeper", "approver"];
export type LocationKind = "stores" | "line_side" | "inspection" | "quarantine";
export const LOCATION_KINDS: readonly LocationKind[] = ["stores", "line_side", "inspection", "quarantine"];
export type LotRuleM2 = LotRule;

/** 10.2 permission names. */
export type Permission =
  | "view"
  | "master_edit"
  | "supplier_edit"
  | "inventory"
  | "pr_edit"
  | "pr_approve"
  | "po_edit"
  | "demand_edit"
  | "wo_edit"
  | "mrp_run"
  | "import"
  | "owner";

export interface Actor {
  id: string;
  name: string;
}

// ---------------------------------------------------------------- 3.1 additive M1 fields
export interface ItemM2Fields {
  external_ref?: string | null;
  standard_cost?: number | null;
  lot_controlled?: boolean;
  lot_period_days?: number | null;
  lot_rule?: LotRuleM2;
}

export type ItemRecordM2 = ItemRecord & Required<ItemM2Fields>;

export interface PlantM2Fields {
  mrp_workdays?: Weekday[];
  mrp_day_minutes?: number;
  mrp_defer_tolerance_days?: number;
  mrp_release_window_days?: number;
  over_receipt_pct?: number;
}

export type PlantRecordM2 = PlantRecord & PlantM2Fields;

/** M1 #2 `/summary` additive counts (12.3). */
export interface SummaryM2Counts {
  locations?: number;
  suppliers?: number;
  open_purchase_orders?: number;
  open_purchase_requests?: number;
  overdue_schedules?: number;
  open_demand_lines?: number;
  open_work_orders?: number;
}

export interface SummaryLatestRun {
  id: EntityId;
  run_no: number;
  finished_at: IsoDateTime | null;
  demand_late: number;
  stale: boolean;
}

// ---------------------------------------------------------------- 3.2 location
export interface LocationInput {
  code: string;
  name: string;
  kind: LocationKind;
  receipt_default?: boolean;
  active?: boolean;
  external_ref?: string | null;
  note?: string;
}

export interface LocationRecord {
  id: EntityId;
  code: string;
  name: string;
  kind: LocationKind;
  receipt_default: boolean;
  active: boolean;
  external_ref: string | null;
  note: string;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface LocationRef {
  id: EntityId;
  code: string;
  name: string;
  kind: LocationKind;
}

// ---------------------------------------------------------------- 3.3 supplier, item-supplier
export interface SupplierInput {
  code: string;
  name: string;
  lead_time_days?: number | null;
  currency?: string;
  contact_name?: string;
  email?: string;
  phone?: string;
  address?: string;
  active?: boolean;
  external_ref?: string | null;
  note?: string;
}

export interface SupplierRecord {
  id: EntityId;
  code: string;
  name: string;
  lead_time_days: number | null;
  currency: string;
  contact_name: string;
  email: string;
  phone: string;
  address: string;
  active: boolean;
  external_ref: string | null;
  note: string;
  item_count: number;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface ItemSupplierInput {
  item_id: EntityId;
  supplier_id: EntityId;
  supplier_part_number?: string;
  lead_time_days?: number | null;
  min_order_qty?: number;
  order_multiple?: number;
  purchase_unit?: string | null;
  units_per_purchase_unit?: number;
  unit_price?: number | null;
  currency?: string;
  preferred?: boolean;
  active?: boolean;
  note?: string;
}

export interface ItemSupplierRecord {
  id: EntityId;
  item_id: EntityId;
  supplier_id: EntityId;
  supplier_part_number: string;
  lead_time_days: number | null;
  min_order_qty: number;
  order_multiple: number;
  purchase_unit: string | null;
  units_per_purchase_unit: number;
  unit_price: number | null;
  currency: string;
  preferred: boolean;
  active: boolean;
  note: string;
  item: ItemRef;
  supplier: Ref;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface SupplierDetail extends SupplierRecord {
  items: ItemSupplierRecord[];
}

// ---------------------------------------------------------------- 3.4 lots, balances, ledger, reservations
export interface LotRef {
  id: EntityId;
  lot_code: string;
  expires_on: IsoDate | null;
  hold: boolean;
}

export interface LotRecord {
  id: EntityId;
  item: ItemRef;
  lot_code: string;
  expires_on: IsoDate | null;
  received_on: IsoDate | null;
  supplier_lot: string;
  hold: boolean;
  note: string;
  on_hand: number;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface LotUpdate {
  expires_on: IsoDate | null;
  supplier_lot: string;
  hold: boolean;
  note: string;
}

export interface BalanceRow {
  id: EntityId;
  item: ItemRef;
  location: LocationRef;
  lot: LotRef | null;
  qty_on_hand: number;
  qty_reserved: number;
  qty_available: number;
  nettable: boolean;
  last_receipt_on: IsoDate | null;
  value: number | null;
  updated_at: IsoDateTime;
}

export interface BalancePage extends Page<BalanceRow> {
  totals?: { qty_on_hand: number; qty_reserved: number; value: number | null };
}

export type DocRefType = "po" | "pr" | "wo" | "demand";

export interface DocRef {
  type: DocRefType;
  id: EntityId;
  number: string;
  line_no: number | null;
  schedule_seq: number | null;
  label: string;
}

export type PostingType =
  | "receipt_misc"
  | "issue_misc"
  | "adjust"
  | "count"
  | "transfer"
  | "po_receipt"
  | "wo_issue"
  | "wo_return"
  | "wo_receipt"
  | "ship";

export const POSTING_TYPES: readonly PostingType[] = [
  "receipt_misc",
  "issue_misc",
  "adjust",
  "count",
  "transfer",
  "po_receipt",
  "wo_issue",
  "wo_return",
  "wo_receipt",
  "ship",
];

export interface TransactionRow {
  id: EntityId;
  seq: number;
  posting_id: EntityId;
  posting_number: string;
  line_no: number;
  txn_type: PostingType;
  txn_date: IsoDate;
  item: ItemRef;
  location: LocationRef;
  lot: LotRef | null;
  qty: number;
  balance_after: number;
  unit_cost: number | null;
  ref: DocRef | null;
  actor: Actor;
  created_at: IsoDateTime;
}

export interface PostingWarning {
  code: string;
  message: string;
}

export interface PostingRecord {
  id: EntityId;
  number: string;
  type: PostingType;
  txn_date: IsoDate;
  note: string;
  reason_code: string | null;
  actor: Actor;
  created_at: IsoDateTime;
  reversal_of: { id: EntityId; number: string } | null;
  reversed_by: { id: EntityId; number: string } | null;
  lines: TransactionRow[];
  warnings: PostingWarning[];
}

export interface PostingHeader {
  id: EntityId;
  number: string;
  type: PostingType;
  txn_date: IsoDate;
  note: string;
  reason_code: string | null;
  actor: Actor;
  created_at: IsoDateTime;
  reversal_of: { id: EntityId; number: string } | null;
  reversed_by: { id: EntityId; number: string } | null;
  line_count: number;
}

export interface ReservationRow {
  id: EntityId;
  wo: { id: EntityId; number: string };
  component_id: EntityId;
  item: ItemRef;
  balance_id: EntityId;
  location: LocationRef;
  lot: LotRef | null;
  qty: number;
  created_at: IsoDateTime;
}

// ---------------------------------------------------------------- 4.1 posting inputs (discriminated union)
interface PostingCommon {
  txn_date?: IsoDate | null;
  note?: string;
  reason_code?: string | null;
}

export interface ReceiptMiscLine {
  item_id: EntityId;
  location_id: EntityId;
  qty: number;
  lot_code?: string | null;
  expires_on?: IsoDate | null;
  supplier_lot?: string;
  unit_cost?: number | null;
}
export interface IssueMiscLine {
  item_id: EntityId;
  location_id: EntityId;
  lot_code?: string | null;
  qty: number;
}
export interface AdjustLine {
  item_id: EntityId;
  location_id: EntityId;
  lot_code?: string | null;
  qty: number;
  expires_on?: IsoDate | null;
}
export interface CountLine {
  item_id: EntityId;
  location_id: EntityId;
  lot_code?: string | null;
  counted_qty: number;
  expires_on?: IsoDate | null;
}
export interface TransferLine {
  item_id: EntityId;
  from_location_id: EntityId;
  to_location_id: EntityId;
  lot_code?: string | null;
  qty: number;
}
export interface PoReceiptLine {
  schedule_id: EntityId;
  location_id: EntityId | null;
  qty: number;
  lot_code?: string | null;
  expires_on?: IsoDate | null;
  supplier_lot?: string;
  unit_cost?: number | null;
}
export interface WoIssueLine {
  wo_component_id: EntityId;
  location_id: EntityId;
  lot_code?: string | null;
  qty: number;
  over_issue?: boolean;
}
export interface WoReturnLine {
  wo_component_id: EntityId;
  location_id: EntityId;
  lot_code?: string | null;
  qty: number;
}
export interface WoReceiptLine {
  wo_id: EntityId;
  location_id: EntityId;
  qty: number;
  scrap_qty?: number;
  lot_code?: string | null;
  expires_on?: IsoDate | null;
}
export interface ShipLine {
  demand_line_id: EntityId;
  location_id: EntityId;
  lot_code?: string | null;
  qty: number;
}

export type PostingInput =
  | (PostingCommon & { type: "receipt_misc"; lines: ReceiptMiscLine[] })
  | (PostingCommon & { type: "issue_misc"; lines: IssueMiscLine[] })
  | (PostingCommon & { type: "adjust"; lines: AdjustLine[] })
  | (PostingCommon & { type: "count"; lines: CountLine[] })
  | (PostingCommon & { type: "transfer"; lines: TransferLine[] })
  | (PostingCommon & { type: "po_receipt"; lines: PoReceiptLine[] })
  | (PostingCommon & { type: "wo_issue"; lines: WoIssueLine[] })
  | (PostingCommon & { type: "wo_return"; lines: WoReturnLine[] })
  | (PostingCommon & { type: "wo_receipt"; lines: WoReceiptLine[] })
  | (PostingCommon & { type: "ship"; lines: ShipLine[] });

export interface InsufficientStockDetails {
  item_id: EntityId;
  location_id: EntityId;
  lot_code: string | null;
  on_hand: number;
  reserved: number;
  available: number;
  requested: number;
  line?: number;
}

// ---------------------------------------------------------------- 3.5 purchase documents
export type DocType = "pr" | "po";
export type PrStatus = "draft" | "submitted" | "approved" | "rejected" | "ordered" | "cancelled";
export type PoStatus = "draft" | "open" | "partially_received" | "received" | "closed" | "cancelled";
export type PurchaseStatus = PrStatus | PoStatus;
export type DocSource = "manual" | "mrp" | "import";
export type PurchaseLineStatus = "open" | "converted" | "cancelled" | "closed";

export interface ScheduleInput {
  id?: EntityId | null;
  seq?: number | null;
  requested_date: IsoDate;
  confirmed_date?: IsoDate | null;
  qty: number;
}

export interface PurchaseLineInput {
  id?: EntityId | null;
  line_no?: number | null;
  item_id: EntityId;
  unit_price?: number | null;
  note?: string;
  schedules: ScheduleInput[];
}

export interface PurchaseDocInput {
  number?: string | null;
  supplier_id?: EntityId | null;
  currency?: string;
  order_date?: IsoDate | null;
  note?: string;
  external_ref?: string | null;
  lines: PurchaseLineInput[];
}

export interface ScheduleRecord {
  id: EntityId;
  seq: number;
  requested_date: IsoDate;
  confirmed_date: IsoDate | null;
  qty: number;
  received_qty: number;
  open_qty: number;
  closed: boolean;
  dock_date: IsoDate;
  available_date: IsoDate;
  overdue: boolean;
  overdue_days: number;
}

export interface DocLineLink {
  doc_id: EntityId;
  number: string;
  line_no: number;
}

export interface PurchaseLineRecord {
  id: EntityId;
  line_no: number;
  item_id: EntityId;
  item: ItemRef;
  unit_price: number | null;
  note: string;
  status: PurchaseLineStatus;
  qty: number;
  received_qty: number;
  open_qty: number;
  converted_to: DocLineLink | null;
  source_pr: DocLineLink | null;
  schedules: ScheduleRecord[];
}

interface PurchaseDocBase {
  id: EntityId;
  doc_type: DocType;
  number: string;
  status: PurchaseStatus;
  supplier_id: EntityId | null;
  supplier: Ref | null;
  currency: string;
  order_date: IsoDate | null;
  note: string;
  external_ref: string | null;
  source: DocSource;
  source_run_no: number | null;
  submitted_at: IsoDateTime | null;
  submitted_by: string | null;
  approved_at: IsoDateTime | null;
  approved_by: string | null;
  rejected_reason: string;
  value: number | null;
  open_value: number | null;
  overdue_count: number;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface PurchaseDocRecord extends PurchaseDocBase {
  lines: PurchaseLineRecord[];
  /** #119 only (PO): receipt posting headers. */
  receipts?: PostingHeader[];
}

export interface PurchaseDocSummary extends PurchaseDocBase {
  line_count: number;
  next_dock_date: IsoDate | null;
}

export type PurchaseSort = "-created_at" | "number" | "next_dock_date";

export interface PurchaseQuery {
  status?: string;
  supplier_id?: EntityId;
  item_id?: EntityId;
  overdue?: boolean;
  q?: string;
  source?: DocSource;
  sort?: PurchaseSort;
  limit?: number;
  offset?: number;
}

export interface ConvertPrRequest {
  line_ids: EntityId[] | null;
  supplier_id: EntityId | null;
  number: string | null;
  issue: boolean;
}

export interface ConvertPrResponse {
  pr: PurchaseDocRecord;
  po: PurchaseDocRecord;
}

/** #125 schedule board row. */
export interface ScheduleRow {
  schedule_id: EntityId;
  seq: number;
  doc: { id: EntityId; doc_type: DocType; number: string; status: PurchaseStatus };
  line_no: number;
  item: ItemRef;
  supplier: Ref | null;
  requested_date: IsoDate;
  confirmed_date: IsoDate | null;
  dock_date: IsoDate;
  available_date: IsoDate;
  qty: number;
  received_qty: number;
  open_qty: number;
  overdue: boolean;
  overdue_days: number;
  link: string;
}

export interface ScheduleQuery {
  from?: IsoDate;
  to?: IsoDate;
  supplier_id?: EntityId;
  item_id?: EntityId;
  doc_type?: DocType;
  overdue_only?: boolean;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------- 3.6 demand
export type DemandType = "customer" | "internal" | "spares" | "project";
export const DEMAND_TYPES: readonly DemandType[] = ["customer", "internal", "spares", "project"];
export type DemandStatus = "draft" | "open" | "closed" | "cancelled";
export type ProjectionStatus = "on_time" | "late" | "past_due";

export interface DemandLineInput {
  id?: EntityId | null;
  line_no?: number | null;
  item_id: EntityId;
  qty: number;
  due_date: IsoDate;
  serial_from?: number | null;
  serial_to?: number | null;
  priority?: number | null;
  note?: string;
}

export interface DemandOrderInput {
  number?: string | null;
  demand_type: DemandType;
  customer?: string;
  program?: string | null;
  priority?: number;
  note?: string;
  external_ref?: string | null;
  lines: DemandLineInput[];
}

export interface DemandLineProjection {
  run_id: EntityId;
  run_no: number;
  projected_date: IsoDate | null;
  late_days: number;
  status: ProjectionStatus;
}

export interface DemandLineRecord {
  id: EntityId;
  line_no: number;
  item_id: EntityId;
  item: ItemRef;
  qty: number;
  due_date: IsoDate;
  serial_from: number | null;
  serial_to: number | null;
  priority: number | null;
  note: string;
  shipped_qty: number;
  open_qty: number;
  line_status: "open" | "shipped";
  effective_priority: number;
  projection: DemandLineProjection | null;
}

interface DemandOrderBase {
  id: EntityId;
  number: string;
  demand_type: DemandType;
  customer: string;
  program: string | null;
  priority: number;
  status: DemandStatus;
  note: string;
  external_ref: string | null;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface DemandOrderRecord extends DemandOrderBase {
  lines: DemandLineRecord[];
}

export interface DemandOrderSummary extends DemandOrderBase {
  line_count: number;
  open_qty: number;
  next_due: IsoDate | null;
  late_lines: number;
}

export interface DemandQuery {
  status?: DemandStatus;
  demand_type?: DemandType;
  program?: string;
  item_id?: EntityId;
  due_from?: IsoDate;
  due_to?: IsoDate;
  late_only?: boolean;
  q?: string;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------- 3.7 work orders
export type WoStatus = "planned" | "released" | "in_progress" | "completed" | "closed" | "cancelled";

export interface WoComponentInput {
  id?: EntityId | null;
  item_id: EntityId;
  required_qty: number;
  operation_seq?: number | null;
  find_number?: string | null;
  note?: string;
}

export interface WorkOrderInput {
  number?: string | null;
  item_id: EntityId;
  qty: number;
  due_date: IsoDate;
  start_date?: IsoDate | null;
  priority?: number;
  serial_from?: number | null;
  serial_to?: number | null;
  demand_line_id?: EntityId | null;
  note?: string;
  external_ref?: string | null;
  components?: WoComponentInput[] | null;
}

export interface WoComponentRecord {
  id: EntityId;
  item: ItemRef;
  required_qty: number;
  issued_qty: number;
  open_qty: number;
  reserved_qty: number;
  operation_seq: number | null;
  find_number: string | null;
  alt_group: string | null;
  bom_line_id: string | null;
  note: string;
}

interface WorkOrderBase {
  id: EntityId;
  number: string;
  status: WoStatus;
  item_id: EntityId;
  item: ItemRef;
  qty: number;
  qty_completed: number;
  qty_scrapped: number;
  open_qty: number;
  start_date: IsoDate;
  due_date: IsoDate;
  priority: number;
  serial_from: number | null;
  serial_to: number | null;
  demand_line_id: EntityId | null;
  demand_line: { id: EntityId; order_id: EntityId; order_number: string; line_no: number } | null;
  bom: { id: EntityId; revision: string; version: number } | null;
  routing: { id: EntityId; code: string; version: number } | null;
  source: DocSource;
  source_run_no: number | null;
  source_planned_no: number | null;
  released_at: IsoDateTime | null;
  completed_at: IsoDateTime | null;
  closed_at: IsoDateTime | null;
  note: string;
  external_ref: string | null;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface WorkOrderRecord extends WorkOrderBase {
  shortage_count?: number;
  components: WoComponentRecord[];
  warnings?: PostingWarning[];
  reserved?: ReserveResult[];
}

export interface WorkOrderSummary extends WorkOrderBase {
  component_count: number;
}

export interface ReserveResult {
  component_id: EntityId;
  qty: number;
  shortage: number;
}

export type WoSort = "start_date" | "due_date" | "number" | "priority";

export interface WoQuery {
  status?: string;
  item_id?: EntityId;
  q?: string;
  start_from?: IsoDate;
  start_to?: IsoDate;
  source?: DocSource;
  sort?: WoSort;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------- 7.4 kitting
export interface NextSupply {
  type: "po" | "pr" | "wo";
  label: string;
  date: IsoDate;
  qty: number;
  link: string;
}

export interface KittingLocation {
  location: LocationRef;
  lot: LotRef | null;
  qty_available: number;
}

export interface KittingComponent {
  component_id: EntityId;
  item: ItemRef;
  required: number;
  issued: number;
  open: number;
  reserved: number;
  free: number;
  shortage: number;
  locations: KittingLocation[];
  next_supply: NextSupply | null;
}

export interface KittingResponse {
  wo: { id: EntityId; number: string; status: WoStatus };
  components: KittingComponent[];
  totals: { components: number; short_components: number; kit_complete: boolean };
}

export interface KittingCheckRequest {
  wo_ids: EntityId[] | null;
  order: "priority" | "start_date";
  horizon_days: number;
}

export interface KittingCheckRow {
  wo: { id: EntityId; number: string; item: ItemRef };
  start_date: IsoDate;
  priority: number;
  status: WoStatus;
  kit_complete: boolean;
  short_components: number;
  shortages: { item: ItemRef; shortage: number; next_supply: NextSupply | null }[];
}

export interface ItemShort {
  item: ItemRef;
  total_shortage: number;
  wo_count: number;
  first_start_date: IsoDate;
  next_supply: NextSupply | null;
}

export interface KittingCheckResponse {
  rows: KittingCheckRow[];
  items_short: ItemShort[];
}

// ---------------------------------------------------------------- #100 item stock
export interface StockFlow {
  type: string;
  ref: DocRef | { label: string; link?: string | null };
  date: IsoDate;
  qty: number;
}

export interface ItemStock {
  item: ItemRef;
  totals: { nettable: number; inspection: number; quarantine: number; reserved: number; available: number; value: number | null };
  balances: BalanceRow[];
  open_supply: StockFlow[];
  open_demand: StockFlow[];
  latest_run: { run_id: EntityId; run_no: number; first_short_date: IsoDate | null; short_qty: number } | null;
}

// ---------------------------------------------------------------- 3.8 / 10 members, me, workspaces
export interface MemberInput {
  email: string;
  roles: Role[];
  active?: boolean;
}

export interface MemberUpdate {
  roles: Role[];
  active: boolean;
}

export interface MemberRecord {
  id: EntityId;
  user: { id: string; email: string; display_name: string };
  roles: Role[];
  active: boolean;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface MeResponse {
  user_id: string;
  workspace_owner_id: string;
  workspace_name: string;
  is_owner: boolean;
  roles: Role[];
  permissions: Permission[];
}

export interface WorkspaceInfo {
  owner_id: string;
  plant_name: string;
  is_owner: boolean;
  roles: Role[];
}

export interface ForbiddenDetails {
  permission: Permission;
  roles_allowed: Role[];
}

// ---------------------------------------------------------------- 8.2 MRP params
export interface DemandFilter {
  order_ids?: EntityId[] | null;
  programs?: string[] | null;
  types?: DemandType[] | null;
}

export interface ExtraDemand {
  item_id: EntityId;
  qty: number;
  due_date: IsoDate;
  priority?: number;
  serial_from?: number | null;
  serial_to?: number | null;
  label?: string;
}

export interface SupplyDateOverride {
  schedule_id?: EntityId | null;
  wo_id?: EntityId | null;
  date: IsoDate;
}

export interface LeadTimeOverride {
  item_id: EntityId;
  lead_time_days: number;
}

export interface MrpParams {
  label?: string;
  note?: string;
  as_of?: IsoDate | null;
  horizon_days?: number | null;
  allocation?: "priority" | "due_date";
  alternates?: "never" | "when_short";
  safety_stock?: boolean;
  include_pr_supply?: boolean;
  protect_programs?: string[];
  demand_filter?: DemandFilter | null;
  exclude_demand_line_ids?: EntityId[];
  extra_demand?: ExtraDemand[];
  supply_date_overrides?: SupplyDateOverride[];
  lead_time_overrides?: LeadTimeOverride[];
}

// ---------------------------------------------------------------- 12.4 MRP responses
export type RunKind = "live" | "what_if";
export type RunStatus = "running" | "completed" | "failed";
export type MrpSeverity = "critical" | "warning" | "info";
export const MRP_SEVERITIES: readonly MrpSeverity[] = ["critical", "warning", "info"];
export type ReleaseStatus = "start_in_past" | "release_now" | "later";
export type PlannedKind = "make" | "buy";
export type PlannedStatus = "open" | "converted";

export interface SeverityCountsM2 {
  critical: number;
  warning: number;
  info: number;
}

export interface MrpSummary {
  demand_lines: number;
  demand_on_time: number;
  demand_late: number;
  demand_past_due: number;
  max_late_days: number;
  items: number;
  items_short: number;
  planned_make: number;
  planned_buy: number;
  release_now: number;
  start_in_past: number;
  alternates_used: number;
  iterations: number;
  exceptions_truncated: boolean;
  exceptions: { by_severity: SeverityCountsM2; by_code: Record<string, number> };
  timings_ms: Record<string, number>;
}

export interface RunStale {
  is_stale: boolean;
  master_changed: boolean;
  transactions_changed: boolean;
}

export interface MrpRunRecord {
  id: EntityId;
  run_no: number;
  kind: RunKind;
  status: RunStatus;
  label: string;
  note: string;
  pinned: boolean;
  as_of: IsoDate;
  horizon_days: number;
  params?: MrpParams;
  master_fingerprint: string;
  row_version: number;
  started_at: IsoDateTime;
  finished_at: IsoDateTime | null;
  duration_ms: number | null;
  actor: Actor;
  summary: MrpSummary | null;
  stale?: RunStale;
  error: { code?: string; message: string } | null;
}

export interface RunRef {
  id: EntityId;
  run_no: number;
  as_of: IsoDate;
  stale: boolean | RunStale;
}

export type LeadTimeSource = "override" | "item_supplier" | "supplier" | "item" | "routing" | "fixed";

export interface LeadTimeInfo {
  source: LeadTimeSource;
  days: number;
  unit: "calendar" | "working";
}

export interface MrpItemRow {
  item: ItemRef;
  llc: number;
  make_buy: MakeBuy;
  uom: string;
  on_hand: number;
  gross_qty: number;
  existing_supply_qty: number;
  planned_qty: number;
  planned_count: number;
  first_short_date: IsoDate | null;
  short_qty: number;
  late_qty: number;
  min_balance: number;
  exception_count: number;
  lead_time: LeadTimeInfo;
  link: string;
}

export type MrpItemSort = "llc" | "part_number" | "first_short_date" | "-short_qty";

export interface MrpItemQuery {
  q?: string;
  make_buy?: MakeBuy;
  family?: string;
  short_only?: boolean;
  has_exceptions?: boolean;
  planned_only?: boolean;
  llc?: number;
  sort?: MrpItemSort;
  limit?: number;
  offset?: number;
}

export type TimelineKind = "on_hand" | "requirement" | "supply" | "planned";

export interface TimelineEvent {
  date: IsoDate;
  kind: TimelineKind;
  node: number | null;
  label: string;
  qty: number;
  balance_existing: number;
  balance_planned: number;
}

export interface Bucket {
  start: IsoDate;
  end: IsoDate;
  gross: number;
  existing_supply: number;
  planned: number;
  balance_existing_end: number;
  balance_planned_end: number;
  short: boolean;
}

export type RequirementKind = "demand" | "extra_demand" | "safety_stock" | "planned_component" | "wo_component";
export type SupplyKind = "stock" | "inspection" | "po" | "pr" | "wo" | "planned";

export interface PlanRequirement {
  node: number;
  kind: RequirementKind;
  need_date: IsoDate;
  qty: number;
  rank_label: string;
  segment: [number, number] | null;
  source: {
    type: "demand_line" | "planned_order" | "work_order" | "extra" | "safety_stock";
    id: EntityId | null;
    label: string;
    item_id: EntityId | null;
    node: number | null;
    link: string | null;
  };
  satisfied_date: IsoDate | null;
  late_days: number;
  pegs: { supply_node: number; supply_label: string; qty: number; late_days: number }[];
}

export interface PlanSupply {
  node: number;
  kind: SupplyKind;
  label: string;
  avail_date: IsoDate;
  projected_date: IsoDate | null;
  qty: number;
  pegged_qty: number;
  expires_on: IsoDate | null;
  ref: { type: string; id: EntityId | null; number: string | null; link: string | null };
  planned_no: number | null;
  exception_codes: string[];
}

export interface MrpItemPlan {
  run: RunRef;
  row: MrpItemRow;
  lot: { rule: LotRuleM2; moq: number; multiple: number; pack: number; period_days: number | null; fixed_qty: number | null };
  supplier: Ref | null;
  timeline: TimelineEvent[];
  buckets: Bucket[];
  requirements: PlanRequirement[];
  supplies: PlanSupply[];
}

export interface PegSummaryEntry {
  demand_line_id: EntityId | null;
  label: string;
  qty: number;
}

export interface PlannedOrderRow {
  id: EntityId;
  planned_no: number;
  kind: PlannedKind;
  item: ItemRef;
  supplier: Ref | null;
  qty: number;
  need_date: IsoDate;
  start_date: IsoDate;
  dock_date: IsoDate | null;
  projected_start: IsoDate;
  projected_due: IsoDate;
  late_days: number;
  release_status: ReleaseStatus;
  segment: [number, number] | null;
  lot_note: string;
  peg_summary: PegSummaryEntry[];
  status: PlannedStatus;
  converted: { type: "wo" | "pr"; id: EntityId; number: string } | null;
  link: string;
}

export interface PlannedOrderPage extends Page<PlannedOrderRow> {
  counts?: { by_kind?: Record<string, number>; by_release_status?: Record<string, number>; by_status?: Record<string, number> };
}

export type PlannedSort = "start_date" | "need_date" | "part_number" | "supplier";

export interface PlannedQuery {
  kind?: PlannedKind;
  item_id?: EntityId;
  supplier_id?: EntityId;
  release_status?: ReleaseStatus;
  status?: PlannedStatus;
  q?: string;
  sort?: PlannedSort;
  limit?: number;
  offset?: number;
}

export interface ConvertOrder {
  id: EntityId;
  qty?: number;
  start_date?: IsoDate;
  need_date?: IsoDate;
  supplier_id?: EntityId | null;
}

export interface ConvertRequest {
  mode: "firm" | "release";
  orders: ConvertOrder[];
  pr_grouping?: "per_supplier" | "per_order";
  add_to_pr_id?: EntityId | null;
  reserve?: boolean;
}

export interface ConvertResponse {
  converted: { planned_order_id: EntityId; type: "wo" | "pr"; id: EntityId; number: string; line_no?: number }[];
  created: {
    work_orders: { id: EntityId; number: string }[];
    purchase_requests: { id: EntityId; number: string; supplier: Ref | null; line_count: number }[];
  };
}

export interface RelatedRef {
  type: string;
  id: EntityId | null;
  label: string;
}

export interface MrpExceptionRow {
  id: EntityId;
  ex_no: number;
  code: string;
  severity: MrpSeverity;
  item: ItemRef | null;
  subject: RelatedRef;
  demand_line_id: EntityId | null;
  date: IsoDate | null;
  qty: number | null;
  days: number | null;
  message: string;
  action: string;
  suggested: { date?: IsoDate; qty?: number } | null;
  related: RelatedRef[];
  link: string | null;
}

export interface ExceptionPage extends Page<MrpExceptionRow> {
  counts: { by_severity: SeverityCountsM2; by_code: Record<string, number> };
}

export interface ExceptionQuery {
  code?: string;
  severity?: string;
  item_id?: EntityId;
  demand_line_id?: EntityId;
  q?: string;
  limit?: number;
  offset?: number;
}

export type LimitingReason = "lead_time" | "start_in_past" | "supply_date" | "component";

export interface LimitingStep {
  item: ItemRef;
  label: string;
  date: IsoDate | null;
  reason: LimitingReason;
}

export interface DemandProjectionRow {
  demand_line_id: EntityId | null;
  extra: boolean;
  order: { id: EntityId; number: string; demand_type: DemandType; customer: string; program: string | null } | null;
  line_no: number | null;
  item: ItemRef;
  qty: number;
  due_date: IsoDate;
  priority: number;
  segment: [number, number] | null;
  projected_date: IsoDate | null;
  late_days: number;
  status: ProjectionStatus;
  limiting: LimitingStep[];
  link: string | null;
}

export interface DemandProjectionQuery {
  status?: ProjectionStatus;
  program?: string;
  order_id?: EntityId;
  late_only?: boolean;
  sort?: "-late_days" | "due_date";
  limit?: number;
  offset?: number;
}

export interface PeggingRow {
  row: number;
  parent_row: number | null;
  level: number;
  item: ItemRef;
  node: number;
  kind: string;
  label: string;
  qty: number;
  date: IsoDate | null;
  projected_date: IsoDate | null;
  late_days: number;
  link: string | null;
}

export interface PeggingResponse {
  root: { item_id: EntityId; node: number; kind: "requirement" | "supply" };
  direction: "up" | "down";
  rows: PeggingRow[];
  truncated: boolean;
}

export interface PeggingQuery {
  item_id: EntityId;
  node: number;
  kind: "requirement" | "supply";
  direction: "up" | "down";
  max_depth?: number;
}

export interface PlannedTotals {
  make: number;
  buy: number;
  make_qty: number;
  buy_value: number | null;
}

export interface CompareResponse {
  a: MrpRunRecord;
  b: MrpRunRecord;
  demand: { demand_line_id: EntityId | null; label: string; due_date: IsoDate; a_projected: IsoDate | null; b_projected: IsoDate | null; delta_days: number | null }[];
  planned: { a: PlannedTotals; b: PlannedTotals };
  exceptions_by_code: { code: string; a: number; b: number }[];
  items: { item: ItemRef; a_planned_qty: number; b_planned_qty: number; a_short_qty: number; b_short_qty: number }[];
  truncated: { demand: boolean; items: boolean };
}

export interface ShortageDashboard {
  run: RunRef | null;
  counts: { late_demand: number; short_items: number; overdue_schedules: number; wo_short: number };
  late_demand: DemandProjectionRow[];
  short_items: MrpItemRow[];
  overdue_supply: ScheduleRow[];
  wo_shortages: ItemShort[];
}
