/**
 * TypeScript mirror of the M3 contract (docs/M3-DESIGN.md 3, 6.1, 9, 10, 11). JSON names. `contractExamplesM3.ts`
 * types an example of every shape so `tsc` fails when this mirror drifts. Where the design names a shape without
 * listing every field (gantt rows, load, dispatch, compare), the fields below are WP-U's reading, recorded in
 * M3-DESIGN 17.WP-U; fields the UI can live without are optional.
 */
import type { EntityId, IsoDate, IsoDateTime, ItemRef, Page, Ref } from "./types";
import type { Actor, MrpExceptionRow, RunStale, SeverityCountsM2 } from "./typesM2";

export type OvertimePolicy = "off" | "suggest" | "allow";
export const OVERTIME_POLICIES: readonly OvertimePolicy[] = ["off", "suggest", "allow"];

// ---------------------------------------------------------------- 3.1 plant
export interface PlantM3Fields {
  time_zone?: string | null;
  aps_freeze_hours?: number;
  aps_horizon_days?: number;
  aps_overtime_policy?: OvertimePolicy;
}

// ---------------------------------------------------------------- 3.2 master tables
export interface OperationLineRateInput {
  operation_id: EntityId;
  line_id: EntityId;
  setup_minutes?: number | null;
  run_minutes?: number | null;
  note?: string;
}

export interface OperationLineRateRecord extends Required<OperationLineRateInput> {
  id: EntityId;
  line: Ref;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface SetupMatrixRowInput {
  line_setup_family: string;
  from_family: string;
  to_family: string;
  setup_minutes: number;
}

export interface SetupMatrixRowRecord extends SetupMatrixRowInput {
  id: EntityId;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export type AbsenceKind = "leave" | "training" | "sick" | "other";
export const ABSENCE_KINDS: readonly AbsenceKind[] = ["leave", "training", "sick", "other"];

export interface OperatorAbsenceInput {
  operator_id: EntityId;
  start: IsoDateTime;
  end: IsoDateTime;
  kind: AbsenceKind;
  note?: string;
}

export interface OperatorAbsenceRecord extends Required<OperatorAbsenceInput> {
  id: EntityId;
  operator?: Ref;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

// ---------------------------------------------------------------- 3.3 WO operations (#176-178)
export interface OpPlacement {
  run_id: EntityId;
  run_no?: number;
  line: { id: EntityId; code: string } | null;
  start: IsoDateTime | null;
  end: IsoDateTime | null;
}

export interface WoOperationRow {
  seq: number;
  name: string;
  group: Ref | null;
  done: boolean;
  done_at: IsoDateTime | null;
  done_by: string | null;
  placement: OpPlacement | null;
}

export interface WoOperations {
  wo_id?: EntityId;
  row_version?: number;
  items: WoOperationRow[];
}

// ---------------------------------------------------------------- 6.1 params, edits
export interface CapacityOverride {
  target_type: "line" | "group";
  target_id: EntityId;
  start: IsoDateTime;
  end: IsoDateTime;
  mode: "open_optional" | "close";
}

export type ScheduleEdit =
  | { kind: "move"; op_no: number; line_id?: EntityId | null; start?: IsoDateTime | null }
  | { kind: "lock"; op_no: number }
  | { kind: "unlock"; op_no: number }
  | { kind: "resequence"; line_id: EntityId; op_nos: number[] };

export interface ApsParams {
  label?: string;
  note?: string;
  as_of?: IsoDateTime | null;
  horizon_days?: number | null;
  mrp_run_id?: EntityId | null;
  include_planned?: boolean;
  overtime?: OvertimePolicy | null;
  split?: boolean;
  material?: "strict" | "ignore";
  improve_seconds?: number;
  capacity_overrides?: CapacityOverride[];
  edits?: ScheduleEdit[];
  /** M3-DESIGN 16 Q1 escalation: "same inputs as this run" (+ the `overtime` override). */
  copy_of?: EntityId | null;
}

export interface EditRequest {
  edits: ScheduleEdit[];
  override_freeze: boolean;
}

export interface Violation {
  code: string;
  op_no: number | null;
  message: string;
  refs?: unknown;
}

// ---------------------------------------------------------------- 10 runs
export type ApsRunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ApsPhase = "load" | "construct" | "improve" | "validate" | "store";

export interface ApsGroupUtil {
  group: Ref;
  utilisation_pct: number;
}

/** 9.4 KPIs. */
export interface ApsSummary {
  overtime_policy?: OvertimePolicy;
  operations: number;
  scheduled_operations?: number;
  demand_lines: number;
  demand_on_time: number;
  demand_late: number;
  orders?: number;
  late_orders: number;
  weighted_tardiness_minutes: number;
  max_late_minutes: number;
  overtime_minutes: number;
  overtime_cost: number;
  suggested_overtime_minutes?: number;
  suggested_overtime_cost?: number;
  suggested_tardiness_saved_minutes?: number;
  utilisation?: ApsGroupUtil[];
  bottlenecks?: Ref[];
  setup_minutes: number;
  changeovers: number;
  avg_flow_days: number | null;
  makespan_minutes: number | null;
  unscheduled?: Record<string, number>;
  budget_cut?: boolean;
  iterations?: number;
  timings_ms?: Record<string, number>;
  exceptions?: { by_severity: SeverityCountsM2; by_code: Record<string, number> };
}

export interface ApsRunRecord {
  id: EntityId;
  run_no: number;
  kind: "live" | "what_if";
  status: ApsRunStatus;
  label: string;
  note: string;
  pinned: boolean;
  as_of: IsoDateTime;
  horizon_end?: IsoDateTime | null;
  horizon_days?: number;
  params?: ApsParams;
  master_fingerprint?: string;
  row_version: number;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  duration_ms: number | null;
  actor: Actor;
  summary: ApsSummary | null;
  score?: number[] | null;
  stale?: RunStale;
  error: { code?: string; message: string } | null;
  progress: { phase: ApsPhase; percent: number; best_score?: number[] | null; updated_at: IsoDateTime } | null;
  parent_run_id: EntityId | null;
  mrp_run: { id: EntityId; run_no: number } | null;
  is_published: boolean;
  published_at?: IsoDateTime | null;
  published_by?: string | null;
  validation: { ok: boolean; counts?: Record<string, number>; violations?: Violation[] } | null;
}

// ---------------------------------------------------------------- 6.1 / 11 operations
export interface ReasonInfo {
  code: string;
  text: string;
  refs?: { type: string; id: EntityId | null; label: string; link?: string | null }[];
}

export interface ScheduledOpRow {
  op_no: number;
  order: { type: "wo" | "planned"; id: EntityId; number: string; planned_no: number | null; item_id: EntityId };
  item: ItemRef;
  seq: number;
  name: string;
  group: { id: EntityId; code: string };
  line: { id: EntityId; code: string } | null;
  qty: number;
  split: { index: number; count: number } | null;
  start: IsoDateTime | null;
  end: IsoDateTime | null;
  setup_minutes: number;
  run_minutes: number;
  pieces: [IsoDateTime, IsoDateTime][];
  crew: { operator_id: EntityId; code?: string; start: IsoDateTime; end: IsoDateTime }[];
  tools: { tool_pool_id: EntityId; code?: string; qty: number }[];
  release: { material_at: IsoDateTime | null; predecessor_at: IsoDateTime | null; refs?: ReasonInfo["refs"] } | null;
  locked: boolean;
  frozen: boolean;
  status: "scheduled" | "unscheduled";
  reason: ReasonInfo;
  due: IsoDateTime | null;
  late_minutes: number;
  link?: string;
}

export interface OpDetail extends ScheduledOpRow {
  neighbours?: { prev: ScheduledOpRow | null; next: ScheduledOpRow | null };
}

export interface OpQuery {
  line_id?: string;
  group_id?: string;
  order_id?: string;
  status?: string;
  late_only?: boolean;
  frozen?: boolean;
  from?: string;
  to?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------- 9.1 gantt (#188)
export type GanttView = "line" | "order" | "demand";
export type BandKind = "base" | "optional_opened" | "optional_suggested" | "closed" | "absence";

export interface GanttRow {
  key: string;
  label: string;
  kind: string; // group | line | order | demand | ...
  parent_key: string | null;
  /** line rows: the line id (drop target). */
  line_id?: EntityId | null;
}

export interface GanttBar {
  op_no: number;
  row_key: string;
  start: IsoDateTime;
  end: IsoDateTime;
  setup_end: IsoDateTime | null;
  pieces: [IsoDateTime, IsoDateTime][];
  label: string;
  order_number: string;
  item_part_number: string;
  qty: number;
  late_minutes: number;
  frozen: boolean;
  locked: boolean;
  split: { index: number; count: number } | null;
  /** server hint: "late" | "critical" | "ok" | "frozen" | ... */
  status_color: string;
}

export interface GanttBand {
  row_key: string;
  start: IsoDateTime;
  end: IsoDateTime;
  kind: BandKind;
}

export interface GanttResponse {
  rows: GanttRow[];
  bars: GanttBar[];
  bands: GanttBand[];
  truncated: boolean;
  from?: IsoDateTime;
  to?: IsoDateTime;
}

export interface GanttQuery {
  view: GanttView;
  from?: string;
  to?: string;
  group_id?: string;
  line_id?: string;
  order_id?: string;
  demand_order_id?: string;
}

// ---------------------------------------------------------------- orders, demand (#191-192)
export interface LateChainStep {
  kind: string; // material | capacity | calendar | lead_time | frozen | locked | ...
  label: string;
  op_no?: number | null;
  ref?: { type: string; id: EntityId | null; label: string; link?: string | null } | null;
}

export interface OrderResultRow {
  order_type: "wo" | "planned";
  order_id: EntityId;
  number: string;
  item: ItemRef;
  qty: number;
  due_at: IsoDateTime | null;
  start_at: IsoDateTime | null;
  end_at: IsoDateTime | null;
  late_minutes: number;
  weight: number;
  priority: number;
  demand_refs: { demand_line_id: EntityId; label: string; link?: string | null }[];
  late_chain: { text: string; steps: LateChainStep[] } | null;
  link?: string;
}

export interface ApsDemandRow {
  demand_line_id: EntityId;
  order: { id: EntityId; number: string; program?: string | null } | null;
  line_no: number;
  item: ItemRef;
  qty: number;
  due_date: IsoDate;
  scheduled_end: IsoDateTime | null;
  late_minutes: number;
  status: "on_time" | "late" | "unscheduled";
  late_chain?: { text: string } | null;
  link?: string | null;
}

// ---------------------------------------------------------------- 9.2 load (#193)
export interface LoadRow {
  group: Ref;
  line: { id: EntityId; code: string } | null;
  /** bucket start (local date) */
  day: IsoDate;
  scheduled_minutes: number;
  required_minutes: number;
  base_minutes: number;
  optional_minutes: number;
  opened_minutes: number;
}

// ---------------------------------------------------------------- 9.3 dispatch (#194)
export interface DispatchRow {
  op_no: number;
  seq: number;
  name: string;
  start: IsoDateTime;
  end: IsoDateTime;
  order: { type: "wo" | "planned"; id: EntityId; number: string };
  item: ItemRef;
  qty: number;
  setup_from_family: string | null;
  setup_to_family: string | null;
  setup_minutes: number;
  crew: { operator_id: EntityId; code: string; name?: string }[];
  tools: { tool_pool_id: EntityId; code: string; qty: number }[];
  predecessor_status: "done" | "scheduled_before" | "not_started" | "none";
  material: { kit_complete: boolean; short_components: number } | null;
  done: boolean;
  /** If-Match for the done action (WO row version). */
  wo_row_version?: number | null;
  link?: string;
}

export interface DispatchResponse {
  line: { id: EntityId; code: string; name?: string };
  date: IsoDate;
  shift: string | null;
  shifts: { name: string; start: IsoDateTime; end: IsoDateTime }[];
  rows: DispatchRow[];
}

// ---------------------------------------------------------------- 6.8 overtime (#195)
export interface OvertimeWindow {
  id?: EntityId;
  line: { id: EntityId; code: string };
  group?: Ref | null;
  assignment_id: EntityId | null;
  shift_label?: string;
  start: IsoDateTime;
  end: IsoDateTime;
  minutes: number;
  cost: number;
  status: "opened" | "suggested" | "forced";
  tardiness_saved_minutes: number | null;
  /** allow runs: why it was opened (the late/critical operations that use it). */
  reason?: string | null;
  orders?: { id: EntityId; number: string }[];
}

export interface OvertimeResponse {
  items: OvertimeWindow[];
  totals: { opened_minutes: number; opened_cost: number; suggested_minutes: number; suggested_cost: number; suggested_saved_minutes: number };
}

// ---------------------------------------------------------------- 8 bottlenecks (#197)
export interface BottleneckRow {
  group: Ref;
  utilisation_pct: number;
  late_chains: number;
  suggestion: { text: string; saved_minutes: number; line?: { id: EntityId; code: string } | null } | null;
}

// ---------------------------------------------------------------- 9.5 compare (#198)
export interface ApsCompareResponse {
  a: ApsRunRecord;
  b: ApsRunRecord;
  kpis: { key: string; label: string; a: number | null; b: number | null; delta: number | null; better: "lower" | "higher" }[];
  orders: { order_id: EntityId; number: string; due_at: IsoDateTime | null; a_end: IsoDateTime | null; b_end: IsoDateTime | null; a_late_minutes: number; b_late_minutes: number; delta_minutes: number | null }[];
  groups: { group: Ref; a_util: number; b_util: number }[];
  overtime: { a_minutes: number; b_minutes: number; a_cost: number; b_cost: number };
  truncated: boolean;
}

export type ApsExceptionPage = Page<MrpExceptionRow> & { counts: { by_severity: SeverityCountsM2; by_code: Record<string, number> } };

// ---------------------------------------------------------------- summary addition
export interface PublishedScheduleSummary {
  id: EntityId;
  run_no: number;
  published_at: IsoDateTime;
  late_orders: number;
  stale: boolean;
}
