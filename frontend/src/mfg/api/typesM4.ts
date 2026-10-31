/**
 * M4 execution and replanning contract (docs/M4-DESIGN.md 3-11), routes #200-226 under `/api/v1/mfg`.
 * Aligned to the S0 fixture `backend/superplanner/mfg/floor/fixtures/example_floor.json` and
 * `superplanner/mfg/model_m4.py` (16.WP-U); `contractExamplesM4.ts` is the typed copy of that fixture.
 */
import type { EntityId, IsoDate, IsoDateTime } from "./types";

/** id + code (+ name) reference used throughout the M4 payloads */
export interface CodeRef {
  id: EntityId;
  code: string;
  name?: string;
}

export interface ItemBrief {
  id: EntityId;
  part_number: string;
  description?: string;
  serialized?: boolean;
}

// ---------------------------------------------------------------- 4.2 operations
export type WoOpStatus = "pending" | "ready" | "setup" | "running" | "paused" | "completed" | "skipped";
export const WO_OP_STATUSES: readonly WoOpStatus[] = ["pending", "ready", "setup", "running", "paused", "completed", "skipped"];

export type FloorEventType = "setup_start" | "start" | "pause" | "resume" | "report" | "complete" | "reopen" | "correct" | "skip";
export const SUPERVISOR_EVENTS: readonly FloorEventType[] = ["reopen", "correct", "skip"];

export interface OpPlacementM4 {
  run_id: EntityId;
  op_no: number;
  line: CodeRef | null;
  start: IsoDateTime;
  end: IsoDateTime;
  split?: { index: number; count: number } | null;
}

/** `WoOperationRecord` (#206 items, #202 `operation`) */
export interface WoOperation {
  id: EntityId;
  wo_id: EntityId;
  seq: number;
  name: string;
  group: CodeRef | null;
  status: WoOpStatus;
  qty_planned: number;
  qty_good: number;
  qty_scrap: number;
  qty_rework_out: number;
  qty_rework_in: number;
  /** what reached this operation (predecessor good, op 1: WO qty_planned) + rework in */
  qty_input: number;
  /** input not yet reported good or scrap */
  qty_available: number;
  line: CodeRef | null;
  setup_minutes_actual: number;
  run_minutes_actual: number;
  labour_minutes: number;
  actual_start: IsoDateTime | null;
  actual_end: IsoDateTime | null;
  started_short: boolean;
  source: "release" | "lazy" | "migrated";
  capture_serial: boolean;
  last_event_seq: number | null;
  setup_minutes: number;
  run_minutes: number;
  labor: string;
  done: boolean;
  done_at: IsoDateTime | null;
  done_by: CodeRef | null;
  /** published-schedule placements (empty = not planned) */
  placement: OpPlacementM4[];
  row_version: number;
  created_at?: IsoDateTime;
  updated_at?: IsoDateTime;
}

export interface WoBriefM4 {
  id: EntityId;
  number: string;
  status?: string;
  item: ItemBrief;
  qty: number;
  qty_completed?: number;
  qty_scrapped?: number;
  due_date?: IsoDate | null;
  priority?: number;
  row_version?: number;
  released_to_floor_at?: IsoDateTime | null;
  receipt_location_id?: EntityId | null;
}

// ---------------------------------------------------------------- #201 queue
export type KitLight = "kitted" | "partial" | "short" | "none";

export interface FloorQueueRow {
  wo_operation_id: EntityId | null;
  wo: WoBriefM4;
  seq: number;
  name: string;
  status: WoOpStatus;
  planned_start: IsoDateTime | null;
  planned_end: IsoDateTime | null;
  /** published-run operation number (sequence on the line); null = not in the published plan */
  op_no: number | null;
  qty_planned: number;
  qty_good: number;
  kit: KitLight;
  batch_load_id: EntityId | null;
  next_actions: FloorEventType[];
}

export interface QueueShift {
  label: string | null;
  start: IsoDateTime;
  end: IsoDateTime;
  kind: string;
}

export interface FloorQueueResponse {
  line: CodeRef & { batch_merge?: boolean };
  date: IsoDate;
  shift: string | null;
  run_id: EntityId | null;
  /** open downtime of the line */
  down: Downtime | null;
  shifts: QueueShift[];
  items: FloorQueueRow[];
}

// ---------------------------------------------------------------- #202 operation screen
export interface FloorComponent {
  component_id: EntityId;
  item: ItemBrief;
  required_qty: number;
  issued_qty: number;
  backflush: boolean;
  backflush_posted: number;
  backflush_pending: number;
  kit: KitLight;
  location: CodeRef | null;
}

export interface FloorEventRecord {
  id: EntityId;
  seq: number;
  wo_operation_id: EntityId;
  wo_id: EntityId;
  wo_number: string;
  op_seq: number;
  event_type: FloorEventType;
  event_at: IsoDateTime;
  recorded_at: IsoDateTime;
  line: CodeRef | null;
  operators: CodeRef[];
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
  /** a later `correct` event replaced this one */
  corrected: boolean;
  forced: { reason: string } | null;
  actor: CodeRef | null;
  details: Record<string, unknown>;
}

export interface OperationSerialsInfo {
  /** this operation captures serials of the WO item */
  capture: boolean;
  produced: string[];
  /** serialized components consumed here (child serials may be scanned) */
  consumable: { item_id: EntityId; part_number: string; serials?: string[] }[];
}

export interface FloorOperationDetail {
  operation: WoOperation;
  wo: WoBriefM4;
  instructions: string;
  components: FloorComponent[];
  tools: { tool_pool: CodeRef; qty: number }[];
  eligible_lines: (CodeRef & { down?: boolean })[];
  expected_input: number;
  events: FloorEventRecord[];
  allowed_actions: FloorEventType[];
  serials: OperationSerialsInfo;
  /** optional plant reason lists; the UI has defaults (16.WP-U) */
  reason_codes?: ReasonCodes;
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
  details?: Record<string, unknown>;
}

export interface FloorPosting {
  id: EntityId;
  number: string;
  type: string;
  lines: { item_id: EntityId; location_id: EntityId; qty: number; lot_code?: string | null }[];
}

export interface FloorEventResult {
  event: FloorEventRecord;
  operation: WoOperation;
  /** other operations changed by the event (rework re-opens) */
  operations: WoOperation[];
  wo: WoBriefM4;
  postings: FloorPosting[];
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
export type ScanType = "work_order" | "operation" | "lot" | "serial" | "location" | "line" | "operator" | "batch_load";

export interface ScanResult {
  type: ScanType;
  id: EntityId;
  label: string;
  link: string;
  context: { wo_id?: EntityId; seq?: number; status?: string; line_id?: EntityId; code?: string; item_id?: EntityId } & Record<string, unknown>;
}

// ---------------------------------------------------------------- #205 backflush
export interface BackflushRetryResult {
  results: { wo_operation_id: EntityId; wo: { id: EntityId; number: string }; component_id: EntityId; item_id: EntityId; part_number: string; qty: number; status: string; posting_id: EntityId | null }[];
  posted: number;
  pending: number;
}

// ---------------------------------------------------------------- #208-210 downtime
export type DowntimeKind = "breakdown" | "maintenance" | "no_crew" | "no_material" | "other";
export const DOWNTIME_KINDS: readonly DowntimeKind[] = ["breakdown", "maintenance", "no_crew", "no_material", "other"];

export interface DowntimeInput {
  line_id: EntityId;
  kind: DowntimeKind;
  planned?: boolean;
  start_at?: IsoDateTime | null;
  end_at?: IsoDateTime | null;
  expected_end_at?: IsoDateTime | null;
  reason?: string;
  note?: string;
}

/** `close: true` = closed now */
export interface DowntimeUpdate {
  close?: boolean;
  end_at?: IsoDateTime | null;
  expected_end_at?: IsoDateTime | null;
  kind?: DowntimeKind;
  reason?: string;
  note?: string;
}

export interface Downtime {
  id: EntityId;
  row_version: number;
  line: CodeRef;
  kind: DowntimeKind;
  planned: boolean;
  start_at: IsoDateTime;
  end_at: IsoDateTime | null;
  expected_end_at: IsoDateTime | null;
  open: boolean;
  minutes: number | null;
  reason: string;
  note: string;
  reported_by: CodeRef | null;
  closed_by: CodeRef | null;
  triggers?: ReplanTrigger[];
  created_at?: IsoDateTime;
  updated_at?: IsoDateTime;
}

// ---------------------------------------------------------------- #211-213 batch loads
export interface BatchLoadInput {
  line_id: EntityId;
  members: { wo_operation_id: EntityId; qty: number }[];
  aps_run_id?: EntityId | null;
}

export interface BatchLoad {
  id: EntityId;
  row_version: number;
  /** `BL:<suffix>` scan code */
  load_no: string;
  line: CodeRef;
  status: "open" | "running" | "completed" | "cancelled";
  started_at: IsoDateTime | null;
  ended_at: IsoDateTime | null;
  aps_run_id: EntityId | null;
  units: number;
  created_at?: IsoDateTime;
  updated_at?: IsoDateTime;
  members: { wo_operation_id: EntityId; wo: { id: EntityId; number: string }; seq: number; qty: number }[];
}

// ---------------------------------------------------------------- #214-215 serials
export type SerialStatus = "wip" | "in_stock" | "consumed" | "shipped" | "scrapped";

export interface UnitSerial {
  id: EntityId;
  item: ItemBrief;
  serial: string;
  wo: { id: EntityId; number: string } | null;
  status: SerialStatus;
  captured_at: IsoDateTime;
  captured_op_seq: number | null;
  parent_serial_id: EntityId | null;
  consumed_at: IsoDateTime | null;
  consumed_wo_id: EntityId | null;
  row_version?: number;
  created_at?: IsoDateTime;
  updated_at?: IsoDateTime;
}

export interface UnitSerialDetail extends UnitSerial {
  parent: UnitSerial | null;
  children: UnitSerial[];
  /** the parent WO when the parent item is not serialized */
  consumed_by_wo: { id: EntityId; number: string } | null;
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
  detected_at: IsoDateTime;
  dedupe_key: string;
  details: Record<string, unknown>;
  status: TriggerStatus;
  aps_run_id: EntityId | null;
  handled_by: CodeRef | null;
  handled_at: IsoDateTime | null;
  /** plain-language sentence */
  message: string;
}

export type TriggerPage = { items: ReplanTrigger[]; total: number; limit: number; offset: number; counts?: Partial<Record<TriggerStatus, number>> };

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
  acknowledged_by: CodeRef | null;
}

export type NotificationPage = { items: MfgNotification[]; total: number; limit: number; offset: number; unacked?: number };

export type ReplanPolicy = "notify" | "auto_whatif" | "auto_publish";

// ---------------------------------------------------------------- #222-223 KPIs
export type RatioKey = "otd" | "wo_on_time" | "utilisation" | "availability" | "performance" | "fpy" | "oee" | "scrap_rate" | "adherence";

export interface KpiRatio {
  value: number | null;
  num: number;
  den: number;
  unit: string;
}

export interface KpiResponse {
  period: { from: IsoDate; to: IsoDate; bucket: "day" | "week"; dim: "plant" | "group" | "line"; dim_id: EntityId | null; time_zone?: string | null };
  metrics: Partial<Record<RatioKey, KpiRatio>> & {
    wip?: { count: number; value: number; avg_age_days: number | null };
    setup?: { actual_minutes: number; planned_minutes: number | null; changeovers: number };
  };
  /** per metric, one point per bucket */
  series: Partial<Record<string, { bucket: IsoDate; value: number | null }[]>>;
  top_scrap: { reason_code: string; qty: number; item_family: string | null; operation: string | null }[];
  top_downtime: { reason: string; kind: string; minutes: number; line: CodeRef | null }[];
  worst_adherence_lines: { line: CodeRef; value: number | null; num: number; den: number }[];
  by_dim: ({ dim: "group" | "line"; ref: CodeRef } & Partial<Record<RatioKey, number | null>>)[];
}

export interface AdherenceRow {
  wo_operation_id: EntityId;
  wo: { id: EntityId; number: string };
  seq: number;
  line: CodeRef | null;
  planned_start: IsoDateTime;
  planned_end: IsoDateTime;
  actual_start: IsoDateTime | null;
  actual_end: IsoDateTime | null;
  start_delta_minutes: number | null;
  end_delta_minutes: number | null;
  adherent: boolean;
}

export type AdherencePage = { items: AdherenceRow[]; total: number; limit: number; offset: number; run_id: EntityId | null; tolerance_minutes: number };

// ---------------------------------------------------------------- #224-226 simulations
export interface SimulationInput {
  base_run_id: EntityId;
  samples?: number;
  seed?: number;
  horizon_days?: number;
}

export interface SimulationDemand {
  demand_line_id: EntityId;
  /** "DO-KV-003/1" */
  order: string;
  part_number: string;
  due: IsoDateTime;
  p_on_time: number;
  p50: IsoDateTime | null;
  p90: IsoDateTime | null;
  /** completion in the unperturbed base plan */
  base_end: IsoDateTime | null;
  /** optional (requested, 16.WP-U): minutes late per sample, for the histogram */
  samples_late_minutes?: number[];
}

export interface Simulation {
  id: EntityId;
  row_version?: number;
  created_at: IsoDateTime;
  updated_at?: IsoDateTime;
  base_run_id: EntityId;
  status: "queued" | "running" | "completed" | "failed";
  samples: number;
  params: { seed?: number; horizon_days?: number };
  results: {
    samples_done: number;
    seed: number;
    demand: SimulationDemand[];
    lines: { line: CodeRef; expected_lost_hours: number; mtbf_hours: number | null; breakdowns_sampled: number }[];
    suppliers: { supplier: CodeRef; late_lines: number; mean_delay_days: number; history_receipts: number }[];
  } | null;
  error: { code: string; message: string } | null;
  job_id?: string | null;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  duration_ms: number | null;
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

export interface BatchResult {
  load_no: number;
  line_id: EntityId;
  start: IsoDateTime;
  end: IsoDateTime;
  members: { op_no: number; qty: number }[];
}

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
  component_id?: EntityId;
  item_id: EntityId;
  part_number: string;
  required: number;
  available: number;
  short: number;
  operation_seq?: number | null;
}
