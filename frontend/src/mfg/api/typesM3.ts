/**
 * TypeScript mirror of the M3 contract (docs/M3-DESIGN.md 3, 6.1, 9, 10, 11). JSON names. `contractExamplesM3.ts`
 * types an example of every shape so `tsc` fails when this mirror drifts. Where the design names a shape without
 * listing every field (gantt rows, load, dispatch, compare), the fields below are WP-U's reading, recorded in
 * M3-DESIGN 17.WP-U; fields the UI can live without are optional.
 */
import type { EntityId, IsoDate, IsoDateTime, ItemRef, Page, Ref } from "./types";
import type { Actor, RunStale, SeverityCountsM2 } from "./typesM2";

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
  /** with `copy_of` only: optional shifts to open as planner overtime (accepted suggestions); the run stays live */
  open_shifts?: OpenShift[];
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
export type ApsPhase = "load" | "construct" | "improve" | "validate" | "store" | "done";

/** 9.4 KPIs (names as the S0 fixture). `utilisation` is a fraction 0..1 per group id. */
export interface ApsSummary {
  policy: OvertimePolicy;
  operations: number;
  scheduled_operations: number;
  unscheduled: Record<string, number>;
  orders: number;
  late_orders: number;
  late_wos: number;
  demand_lines: number;
  demand_lines_on_time: number;
  demand_lines_late: number;
  late_demand_count: number;
  weighted_tardiness: number;
  max_lateness_minutes: number;
  overtime_minutes: number;
  overtime_cost: number;
  suggested_overtime_minutes: number;
  suggested_overtime_cost: number;
  suggested_tardiness_saved: number;
  utilisation: Record<EntityId, number>;
  bottlenecks: EntityId[];
  setup_minutes: number;
  changeovers: number;
  avg_flow_days: number | null;
  makespan_minutes: number | null;
  validation_ok: boolean;
  violations: number;
  splits?: number;
  iterations?: number;
  accepted_moves?: number;
  budget_used?: number;
  budget_cut: boolean;
  timings_ms?: Record<string, number>;
}

export interface ApsRunRecord {
  id: EntityId;
  run_no: number;
  kind: "live" | "what_if";
  status: ApsRunStatus;
  label: string;
  note: string;
  pinned: boolean;
  is_published: boolean;
  published_at: IsoDateTime | null;
  published_by: string | null;
  parent_run_id: EntityId | null;
  copy_of_run_id: EntityId | null;
  mrp_run: { id: EntityId; run_no: number } | null;
  as_of: IsoDateTime;
  horizon_end: IsoDateTime | null;
  horizon_days: number;
  policy: OvertimePolicy;
  master_fingerprint?: string;
  row_version: number;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  duration_ms: number | null;
  actor: Actor;
  progress: { phase: ApsPhase; percent: number; best_score?: number[] | null; updated_at: IsoDateTime } | null;
  summary: ApsSummary | null;
  score?: number[] | null;
  validation: { ok: boolean; counts?: Record<string, number>; violations?: Violation[] } | null;
  stale?: RunStale & { mrp_changed?: boolean };
  /** 16 Q1: the run is completed, not `allow`, and demand is still late -> offer the Allow re-run. */
  late_demand_remains: boolean;
  publishable: boolean;
  error: { code?: string; message: string } | null;
  link?: string;
  params?: ApsParams;
}

// ---------------------------------------------------------------- 6.1 / 11 operations
export interface OrderRef {
  type: "wo" | "planned";
  id: EntityId;
  number: string;
  planned_no: number | null;
  item_id: EntityId;
}

export interface Piece {
  start: IsoDateTime;
  end: IsoDateTime;
}

export interface RefAt {
  type: string;
  id: EntityId | null;
  label: string;
  at?: IsoDateTime | null;
  link?: string | null;
}

export interface ReasonInfo {
  code: string;
  text: string;
  refs: RefAt[];
}

export interface ScheduledOpRow {
  op_no: number;
  order: OrderRef;
  seq: number;
  name: string;
  group_id: EntityId;
  line_id: EntityId | null;
  qty: number;
  /** `index` is 0-based; `count` 1 = not split */
  split: { index: number; count: number };
  start: IsoDateTime | null;
  end: IsoDateTime | null;
  setup_minutes: number;
  run_minutes: number;
  pieces: Piece[];
  crew: { operator_id: EntityId; start: IsoDateTime; end: IsoDateTime }[];
  tools: { tool_pool_id: EntityId; qty: number }[];
  release: { material_at: IsoDateTime | null; predecessor_at: IsoDateTime | null; refs: RefAt[] } | null;
  locked: boolean;
  frozen: boolean;
  status: "scheduled" | "unscheduled";
  reason: ReasonInfo;
  due: IsoDateTime | null;
  late_minutes: number;
  family?: string | null;
  setup_from_family?: string | null;
  item: ItemRef;
  line: { id: EntityId; code: string } | null;
  group: { id: EntityId; code: string };
  link?: string;
}

/** #190 */
export interface OpDetail {
  op: ScheduledOpRow;
  reason: ReasonInfo;
  release: ScheduledOpRow["release"];
  neighbours: { before: ScheduledOpRow | null; after: ScheduledOpRow | null };
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
export type BandKind = "base" | "optional_opened" | "optional_suggested" | "closed" | "absence" | "downtime";

/** Row keys are `group:<id>`, `line:<id>`, `order:<id>`, `demand:<id>` (S0 fixture). */
export interface GanttRow {
  key: string;
  label: string;
  kind: string;
  parent_key: string | null;
}

export interface GanttBar {
  op_no: number;
  row_key: string;
  start: IsoDateTime;
  end: IsoDateTime;
  setup_end: IsoDateTime | null;
  pieces: Piece[];
  label: string;
  order_number: string;
  item_part_number: string;
  qty: number;
  late_minutes: number;
  frozen: boolean;
  locked: boolean;
  split: { index: number; count: number } | null;
  status_color: string;
  /** M4 (11): execution state of the WO operation, drawn as a thin bar under the planned one */
  actual?: { status: string; start?: IsoDateTime | null; end?: IsoDateTime | null; actual_start?: IsoDateTime | null; actual_end?: IsoDateTime | null; wo_operation_id?: string } | null;
  /** M4 6.3: the batch load this operation runs in */
  load_no?: number | null;
  moved_by_downtime?: boolean;
}

export interface GanttBand {
  row_key: string;
  start: IsoDateTime;
  end: IsoDateTime;
  kind: BandKind;
}

export interface GanttResponse {
  view?: GanttView;
  rows: GanttRow[];
  bars: GanttBar[];
  bands: GanttBand[];
  truncated: boolean;
  /** M4 6.3: batch loads (one bar with member markers) */
  batches?: { load_no: number; line_id: EntityId; row_key?: string; start: IsoDateTime; end: IsoDateTime; members: { op_no: number; qty: number }[] }[];
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

/** The line id of a gantt row key (`line:<id>`), else null. */
export function lineIdOfRow(key: string): string | null {
  return key.startsWith("line:") ? key.slice(5) : null;
}

// ---------------------------------------------------------------- orders, demand (#191-192)
export interface LateChainStep {
  kind: string; // material | capacity | calendar | lead_time | frozen | locked
  op_no: number | null;
  text: string;
  refs: RefAt[];
}

export interface OrderResultRow {
  order: OrderRef;
  part_number: string;
  qty: number;
  due: IsoDateTime | null;
  start: IsoDateTime | null;
  end: IsoDateTime | null;
  late_minutes: number;
  weight: number;
  priority: number;
  rank_label: string;
  demand_refs: { demand_line_id: EntityId; order_number: string; line_no: number; order_id?: EntityId }[];
  late_chain: LateChainStep[];
  late_text: string;
  unscheduled_ops: number;
}

export interface ApsDemandRow {
  demand_line_id: EntityId;
  order_id: EntityId;
  order_number: string;
  line_no: number;
  item_id: EntityId;
  part_number: string;
  qty: number;
  due: IsoDateTime;
  scheduled_end: IsoDateTime | null;
  late_minutes: number;
  priority: number;
  program: string | null;
  orders: OrderRef[];
  late_text: string;
}

export interface ApsDemandResponse {
  items: ApsDemandRow[];
  counts?: { on_time: number; late: number; unscheduled?: number };
}

// ---------------------------------------------------------------- 9.2 load (#193)
export interface LoadRow {
  group_id: EntityId;
  line_id: EntityId | null;
  /** bucket start (local date) */
  day: IsoDate;
  scheduled_minutes: number;
  required_minutes: number;
  base_minutes: number;
  optional_minutes: number;
  opened_minutes: number;
}

export interface LoadResponse {
  bucket: "day" | "week";
  items: LoadRow[];
}

// ---------------------------------------------------------------- 9.3 dispatch (#194)
export interface DispatchRow {
  op_no: number;
  position: number;
  start: IsoDateTime;
  end: IsoDateTime;
  order: OrderRef;
  part_number: string;
  qty: number;
  seq: number;
  name: string;
  setup_minutes: number;
  run_minutes: number;
  setup_from_family: string | null;
  family: string | null;
  crew: { operator_id: EntityId; start: IsoDateTime; end: IsoDateTime }[];
  tools: { tool_pool_id: EntityId; qty: number }[];
  predecessor_status: string; // none | done | scheduled_before | not_started
  material_status: string; // kitted | short | unknown | ...
  done: boolean;
  shift_label: string | null;
  /** If-Match for done / reopen of the WO operation (null for planned orders) */
  wo_row_version?: number | null;
}

export interface DispatchShift {
  label: string | null;
  start: IsoDateTime;
  end: IsoDateTime;
  kind: string; // base | optional | ...
}

export interface DispatchResponse {
  line: { id: EntityId; code: string };
  date: IsoDate;
  shift: string | null;
  run_id: EntityId;
  shifts?: DispatchShift[];
  items: DispatchRow[];
}

// ---------------------------------------------------------------- 6.8 overtime (#195)
export interface OvertimeWindow {
  line_id: EntityId;
  assignment_id: EntityId | null;
  start: IsoDateTime;
  end: IsoDateTime;
  minutes: number;
  cost: number;
  status: "opened" | "suggested" | "forced";
  tardiness_saved_minutes: number | null;
  /** why it is opened / suggested (which late work it helps) */
  reason?: string;
  orders?: OvertimeOrder[];
}

export interface OvertimeOrder {
  order: OrderRef;
  op_nos: number[];
  minutes: number;
  late_minutes: number;
}

/** accepting suggested overtime (with `copy_of`): opens the optional windows of the line overlapping [start, end) */
export interface OpenShift {
  line_id: EntityId;
  start: IsoDateTime;
  end: IsoDateTime;
}

export interface OvertimeResponse {
  items: OvertimeWindow[];
  totals: { opened_minutes: number; opened_cost: number; suggested_minutes: number; suggested_cost: number; tardiness_saved_minutes: number };
}

// ---------------------------------------------------------------- exceptions (#196)
export interface ApsExceptionRow {
  id: EntityId;
  ex_no: number;
  code: string;
  severity: "critical" | "warning" | "info";
  subject: RefAt;
  op_no: number | null;
  order: OrderRef | null;
  message: string;
  refs: RefAt[];
}

export type ApsExceptionPage = Page<ApsExceptionRow> & { counts?: { by_severity: SeverityCountsM2; by_code: Record<string, number> } };

// ---------------------------------------------------------------- 8 bottlenecks (#197)
export interface BottleneckRow {
  group_id: EntityId;
  group: { id: EntityId; code: string; name?: string };
  rank: number;
  /** fraction 0..1 */
  utilisation: number;
  late_chains: number;
  suggestion: string | null;
  saved_minutes: number | null;
}

// ---------------------------------------------------------------- 9.5 compare (#198)
export interface ApsRunBrief {
  id: EntityId;
  run_no: number;
  label: string;
  policy: OvertimePolicy;
}

export interface ApsCompareResponse {
  a: ApsRunBrief;
  b: ApsRunBrief;
  kpis: { key: string; a: number | null; b: number | null; delta: number | null }[];
  /** B against A: positive "saved" = better in B; "added" = more overtime in B */
  tradeoff: { weighted_tardiness_saved: number; late_minutes_saved: number; late_demand_saved: number; overtime_hours_added: number; overtime_cost_added: number } | null;
  orders: { order: OrderRef; end_a: IsoDateTime | null; end_b: IsoDateTime | null; delta_minutes: number | null; late_a: number; late_b: number }[];
  utilisation: { key: EntityId; a: number; b: number; delta: number }[];
  truncated: boolean;
}

// ---------------------------------------------------------------- summary addition
export interface PublishedScheduleSummary {
  id: EntityId;
  run_no: number;
  published_at: IsoDateTime;
  late_orders: number;
  stale: boolean;
}
