/**
 * M4 execution and replanning contract (docs/M4-DESIGN.md 3, 4, 5, 7-11), routes #200-226 under `/api/v1/mfg`.
 * Written from the design before the S0 fixture existed (16.WP-U); `contractExamplesM4.ts` holds typed examples.
 * Optional fields are the ones the design leaves open; the UI never relies on them being present.
 */
import type { EntityId, IsoDate, IsoDateTime, Ref } from "./types";
import type { OrderRef } from "./typesM3";

// ---------------------------------------------------------------- 4.2 operations
export type WoOpStatus = "pending" | "ready" | "setup" | "running" | "paused" | "completed" | "skipped";
export const WO_OP_STATUSES: readonly WoOpStatus[] = ["pending", "ready", "setup", "running", "paused", "completed", "skipped"];

export type FloorEventType = "setup_start" | "start" | "pause" | "resume" | "report" | "complete" | "reopen" | "correct" | "skip";
/** event types only a supervisor (`floor_supervise`) may post */
export const SUPERVISOR_EVENTS: readonly FloorEventType[] = ["reopen", "correct", "skip"];

/** `mfg_wo_operations` record (#206, #202 `operation`) */
export interface WoOperation {
  id: EntityId;
  wo_id: EntityId;
  seq: number;
  name: string;
  group_id: EntityId | null;
  group?: Ref | null;
  status: WoOpStatus;
  qty_planned: number;
  qty_good: number;
  qty_scrap: number;
  qty_rework_out: number;
  qty_rework_in: number;
  line_id: EntityId | null;
  line?: Ref | null;
  setup_minutes_actual: number | null;
  run_minutes_actual: number | null;
  labour_minutes: number | null;
  actual_start: IsoDateTime | null;
  actual_end: IsoDateTime | null;
  started_short: boolean;
  source: "release" | "lazy" | "migrated";
  capture_serial?: boolean;
  /** available input = predecessor good (op 1: WO qty_planned) + rework_in */
  available_input?: number;
  /** published plan for this operation, when any (adherence basis, 6.2) */
  planned_start?: IsoDateTime | null;
  planned_end?: IsoDateTime | null;
  row_version?: number;
}

export interface WoRefM4 {
  id: EntityId;
  number: string;
  item: { id: EntityId; part_number: string; description?: string; serialized?: boolean };
  qty: number;
  qty_planned?: number;
  qty_completed?: number;
  qty_scrapped?: number;
  status: string;
  due_date?: IsoDate | null;
  priority?: number;
  row_version?: number;
}

// ---------------------------------------------------------------- #201 queue
export type KitLight = "ok" | "short" | "pending_backflush" | "unknown";

export interface FloorQueueRow {
  wo_operation_id: EntityId;
  wo: { id: EntityId; number: string };
  seq: number;
  name: string;
  part_number: string;
  qty: number;
  qty_good: number;
  qty_scrap: number;
  status: WoOpStatus;
  kit: KitLight;
  planned_start: IsoDateTime | null;
  planned_end: IsoDateTime | null;
  /** published sequence position on the line (null = not in the published plan) */
  position: number | null;
  shift_label?: string | null;
  next_actions: FloorEventType[];
  batch_load_id?: EntityId | null;
  late_minutes?: number;
}

export interface FloorQueueResponse {
  line: { id: EntityId; code: string; name?: string; batch_merge?: boolean };
  date: IsoDate;
  shift: string | null;
  shifts?: { label: string | null; start: IsoDateTime; end: IsoDateTime; kind: string }[];
  published_run_id: EntityId | null;
  /** open downtime on the line, if any */
  downtime: Downtime | null;
  items: FloorQueueRow[];
}

// ---------------------------------------------------------------- #202 operation screen
export interface FloorComponent {
  item_id: EntityId;
  part_number: string;
  description?: string;
  qty_required: number;
  qty_issued: number;
  issue_method: "manual" | "backflush";
  kit: KitLight;
  pending_backflush_qty?: number;
  uom?: string;
  serialized?: boolean;
}

export interface FloorEventRecord {
  id: EntityId;
  seq: number;
  wo_operation_id: EntityId;
  wo_id: EntityId;
  wo_number?: string;
  op_seq?: number;
  event_type: FloorEventType;
  event_at: IsoDateTime;
  recorded_at: IsoDateTime;
  line_id: EntityId | null;
  line_code?: string | null;
  operator_ids: EntityId[];
  operators?: { id: EntityId; code: string; name?: string }[];
  qty_good: number | null;
  qty_scrap: number | null;
  qty_rework: number | null;
  rework_to_seq: number | null;
  reason_code: string | null;
  note: string;
  client_event_id: string | null;
  batch_load_id: EntityId | null;
  serials: FloorSerials | null;
  corrects_event_id: EntityId | null;
  corrected_by_event_id?: EntityId | null;
  actor_id: string;
  actor_name?: string | null;
}

export interface FloorOperationDetail {
  operation: WoOperation;
  wo: WoRefM4;
  instructions: string;
  components: FloorComponent[];
  tools: { tool_pool_id: EntityId; code?: string; qty: number }[];
  expected_input: number;
  events: FloorEventRecord[];
  allowed_actions: FloorEventType[];
  /** eligible active lines of the operation's group */
  lines?: { id: EntityId; code: string; down?: boolean }[];
  reason_codes?: ReasonCodes;
  predecessor?: { seq: number; status: WoOpStatus; qty_good: number } | null;
  is_last?: boolean;
}

export interface ReasonCodes {
  pause: { code: string; label: string }[];
  scrap: { code: string; label: string }[];
  rework: { code: string; label: string }[];
}

// ---------------------------------------------------------------- #203 events
export interface FloorSerials {
  produced?: string[];
  consumed?: { item_id: EntityId; serial: string }[];
}

export interface FloorEventInput {
  client_event_id: string;
  wo_operation_id?: EntityId;
  scan?: string;
  event_type: FloorEventType;
  event_at?: IsoDateTime;
  line_id?: EntityId;
  operator_ids?: EntityId[];
  operator_codes?: string[];
  qty_good?: number;
  qty_scrap?: number;
  qty_rework?: number;
  rework_to_seq?: number;
  reason_code?: string;
  note?: string;
  batch_load_id?: EntityId;
  serials?: FloorSerials;
  corrects_event_id?: EntityId;
  force?: { reason: string };
}

export interface FloorWarning {
  code: string;
  message: string;
}

export interface FloorEventResult {
  event?: FloorEventRecord;
  operation: WoOperation;
  wo: WoRefM4;
  postings: { id: EntityId; number?: string; type: string; qty?: number }[];
  warnings: FloorWarning[];
  triggers: ReplanTrigger[];
}

export interface FloorEventQuery {
  wo_id?: string;
  line_id?: string;
  operator_id?: string;
  type?: string;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------- #200 scan
export type ScanType = "wo" | "wo_operation" | "lot" | "serial" | "location" | "line" | "operator" | "batch_load";

export interface ScanResult {
  type: ScanType;
  id: EntityId;
  label: string;
  link: string | null;
  context?: {
    wo_id?: EntityId;
    wo_operation_id?: EntityId;
    seq?: number;
    line_id?: EntityId;
    item_id?: EntityId;
    operator_code?: string;
    status?: string;
  };
}

// ---------------------------------------------------------------- #205 backflush
export interface BackflushRetryResult {
  posted: { wo_id: EntityId; item_id: EntityId; qty: number }[];
  still_pending: { wo_id: EntityId; item_id: EntityId; qty: number; available: number }[];
}

// ---------------------------------------------------------------- #208-210 downtime
export type DowntimeKind = "breakdown" | "maintenance" | "no_crew" | "no_material" | "other";
export const DOWNTIME_KINDS: readonly DowntimeKind[] = ["breakdown", "maintenance", "no_crew", "no_material", "other"];

export interface DowntimeInput {
  line_id: EntityId;
  kind: DowntimeKind;
  planned?: boolean;
  start_at?: IsoDateTime;
  end_at?: IsoDateTime | null;
  expected_end_at?: IsoDateTime | null;
  reason?: string;
  note?: string;
  client_event_id?: string;
}

export interface DowntimeUpdate {
  end_at?: IsoDateTime | null;
  expected_end_at?: IsoDateTime | null;
  reason?: string;
  note?: string;
}

export interface Downtime {
  id: EntityId;
  line_id: EntityId;
  line?: Ref | null;
  kind: DowntimeKind;
  planned: boolean;
  start_at: IsoDateTime;
  end_at: IsoDateTime | null;
  expected_end_at: IsoDateTime | null;
  reason: string;
  note: string;
  reported_by: string | null;
  closed_by: string | null;
  row_version: number;
}

// ---------------------------------------------------------------- #211-213 batch loads
export interface BatchLoadInput {
  line_id: EntityId;
  members: { wo_operation_id: EntityId; qty: number }[];
}

export interface BatchLoad {
  id: EntityId;
  line_id: EntityId;
  line?: Ref | null;
  status: "open" | "running" | "completed" | "cancelled";
  started_at: IsoDateTime | null;
  ended_at: IsoDateTime | null;
  aps_run_id: EntityId | null;
  members: { wo_operation_id: EntityId; wo_number?: string; seq?: number; part_number?: string; qty: number }[];
  row_version: number;
}

// ---------------------------------------------------------------- #214-215 serials
export type SerialStatus = "wip" | "in_stock" | "consumed" | "shipped" | "scrapped";

export interface UnitSerial {
  id: EntityId;
  item_id: EntityId;
  item?: { id: EntityId; part_number: string; description?: string };
  serial: string;
  wo_id: EntityId | null;
  wo?: { id: EntityId; number: string } | null;
  status: SerialStatus;
  captured_at: IsoDateTime;
  captured_op_seq: number | null;
  parent_serial_id: EntityId | null;
  consumed_at: IsoDateTime | null;
  consumed_wo_id: EntityId | null;
}

export interface UnitSerialDetail extends UnitSerial {
  parent: UnitSerial | null;
  children: UnitSerial[];
  events?: FloorEventRecord[];
}

// ---------------------------------------------------------------- #216-221 replan, notifications
export type TriggerKind = "line_down" | "late_receipt" | "scrap_shortfall" | "overrun" | "rush_order" | "not_started" | "start_short";
export type TriggerStatus = "open" | "attached" | "handled" | "ignored";
export type Severity = "critical" | "warning" | "info";

export interface ReplanTrigger {
  id: EntityId;
  kind: TriggerKind;
  severity: Severity;
  ref_type: string;
  ref_id: EntityId;
  ref_label?: string;
  link?: string | null;
  detected_at: IsoDateTime;
  dedupe_key: string;
  details: Record<string, unknown> & { text?: string };
  status: TriggerStatus;
  aps_run_id: EntityId | null;
  handled_by: string | null;
  handled_at: IsoDateTime | null;
  note?: string;
}

export interface MfgNotification {
  id: EntityId;
  kind: string;
  severity: Severity;
  title: string;
  body: string;
  link: string | null;
  trigger_id: EntityId | null;
  created_at: IsoDateTime;
  acknowledged_at: IsoDateTime | null;
  acknowledged_by: string | null;
}

export type ReplanPolicy = "notify" | "auto_whatif" | "auto_publish";

// ---------------------------------------------------------------- #222-223 KPIs
export type KpiKey = "otd" | "wo_on_time" | "utilisation" | "availability" | "performance" | "fpy" | "oee" | "wip" | "setup" | "adherence" | "scrap_rate";

export interface KpiValue {
  value: number | null;
  num?: number;
  den?: number;
  /** extra figures (e.g. wip count/value/age, setup minutes/changeovers/planned) */
  extra?: Record<string, number | null>;
}

export interface KpiResponse {
  from: IsoDate;
  to: IsoDate;
  dim: "plant" | "group" | "line";
  dim_id: EntityId | null;
  bucket: "day" | "week";
  metrics: Partial<Record<KpiKey, KpiValue>>;
  /** one point per bucket per metric (sparklines, last 8 weeks for the tiles) */
  series: { bucket_start: IsoDate; metrics: Partial<Record<KpiKey, number | null>> }[];
  top_scrap: { reason_code: string; label?: string; qty: number; item_family?: string | null; op_name?: string | null }[];
  top_downtime: { kind: DowntimeKind | string; reason?: string; minutes: number; line_id?: EntityId | null }[];
  worst_adherence?: { line_id: EntityId; value: number | null; ops: number }[];
  by_dim?: { dim_id: EntityId; code?: string; metrics: Partial<Record<KpiKey, number | null>> }[];
}

export interface AdherenceRow {
  wo_operation_id: EntityId;
  wo: { id: EntityId; number: string };
  seq: number;
  name: string;
  line_id: EntityId | null;
  planned_start: IsoDateTime;
  planned_end: IsoDateTime;
  actual_start: IsoDateTime | null;
  actual_end: IsoDateTime | null;
  start_delta_minutes: number | null;
  end_delta_minutes: number | null;
  adherent: boolean;
}

// ---------------------------------------------------------------- #224-226 simulations
export interface SimulationInput {
  base_run_id: EntityId;
  samples?: number;
  seed?: number;
  horizon_days?: number;
}

export interface SimulationResultLine {
  demand_line_id: EntityId;
  order_number: string;
  line_no: number;
  part_number: string;
  due: IsoDateTime;
  p_on_time: number;
  p50: IsoDateTime | null;
  p90: IsoDateTime | null;
  /** completion per sample (minutes late, negative = early), for the histogram */
  samples_late_minutes?: number[];
}

export interface Simulation {
  id: EntityId;
  base_run_id: EntityId;
  base_run?: { id: EntityId; run_no: number; label: string } | null;
  status: "queued" | "running" | "completed" | "failed";
  samples: number;
  params: { seed?: number; horizon_days?: number };
  progress?: { done: number; total: number } | null;
  error?: { code: string; message: string } | null;
  created_at: IsoDateTime;
  results: {
    demand_lines: SimulationResultLine[];
    lines: { line_id: EntityId; code?: string; expected_lost_hours: number }[];
    suppliers: { supplier_id: EntityId; code?: string; name?: string; late_lines: number; share: number }[];
  } | null;
}

// ---------------------------------------------------------------- 11 summary, gantt and params additions
export interface FloorSummary {
  running_ops: number;
  lines_down: number;
  open_triggers: number;
  pending_backflush: number;
}

export interface SupplyDelay {
  schedule_id?: EntityId;
  wo_id?: EntityId;
  item_id?: EntityId;
  days: number;
}

export interface LineBreakdown {
  line_id: EntityId;
  start: IsoDateTime;
  hours: number;
}

/** run results gain per-operation actuals (11); drawn under the planned bar */
export interface OpActual {
  status: WoOpStatus;
  start: IsoDateTime | null;
  end: IsoDateTime | null;
}

export interface BatchResult {
  load_no: number;
  line_id: EntityId;
  start: IsoDateTime;
  end: IsoDateTime;
  members: { op_no: number; qty: number }[];
}

export type OrderRefM4 = OrderRef;

// ---------------------------------------------------------------- 3.1 master-field additions (intersection types)
export interface PlantM4Fields {
  replan_policy?: ReplanPolicy;
  replan_debounce_minutes?: number;
  overrun_tolerance_pct?: number;
  adherence_tolerance_minutes?: number;
  wo_receipt_location_id?: EntityId | null;
  backflush_location_id?: EntityId | null;
}

export interface ItemM4Fields {
  issue_method?: "manual" | "backflush";
}

export interface OperationM4Fields {
  capture_serial?: boolean;
}

export interface LineM4Fields {
  location_id?: EntityId | null;
  batch_merge?: boolean;
  batch_wait_minutes?: number;
}

export interface OperatorM4Fields {
  user_id?: string | null;
}

export interface WoM4Fields {
  receipt_location_id?: EntityId | null;
  released_to_floor_at?: IsoDateTime | null;
  release_override?: string | null;
}

/** 409 `WO_KIT_INCOMPLETE` details (4.1) */
export interface KitShortage {
  item_id: EntityId;
  part_number: string;
  required: number;
  available: number;
  short: number;
  operation_seq?: number | null;
}
