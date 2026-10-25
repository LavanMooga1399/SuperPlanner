/**
 * TypeScript mirrors of docs/M1-DESIGN.md sections 3 (models), 5 (computations), 7 (health) and 9 (REST shapes,
 * including the frozen 9.6 table). Field names are the JSON names. `contractExamples.ts` types every documented
 * example against these declarations, so `tsc` fails when they drift.
 */

// ---------------------------------------------------------------- 3.1 common types
export type EntityId = string;
/** `YYYY-MM-DD` (plant-local date). */
export type IsoDate = string;
/** ISO datetime; API-generated values are UTC `Z`, plant-time values carry the plant offset. */
export type IsoDateTime = string;
/** "HH:MM", "00:00".."23:59" or "24:00". */
export type HHMM = string;
export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export const WEEKDAYS: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export type Status = "draft" | "released" | "obsolete";
export type MakeBuy = "make" | "buy" | "phantom";
export type LotRule = "lot_for_lot" | "fixed";
export type RunPer = "unit" | "panel" | "batch";
export type Labor = "attended" | "unattended";
export type AssignmentKind = "base" | "optional";
export type TargetType = "group" | "line";
export type ExceptionScope = "plant" | "group" | "line";
export type ExceptionKind = "holiday" | "shutdown" | "maintenance";
export type Severity = "error" | "warning" | "info";

/** 3.2 fixed unit table (codes). The full table with factors comes from `GET /meta`. */
export type UomCode = "EA" | "M" | "CM" | "MM" | "KG" | "G" | "L" | "ML" | "M2";
export const UOM_CODES: readonly UomCode[] = ["EA", "M", "CM", "MM", "KG", "G", "L", "ML", "M2"];

export type AttrValue = string | number | boolean;
export type Attributes = Record<string, AttrValue>;

/** `{id, code, name}` reference (9.6: "refs are {id, code, name} unless stated"). */
export interface Ref {
  id: EntityId;
  code: string;
  name: string;
}

export interface ItemRef {
  id: EntityId;
  part_number: string;
  revision: string;
  description: string;
  uom: string;
  make_buy: MakeBuy;
  active: boolean;
}

interface RecordMeta {
  id: EntityId;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface List<T> {
  items: T[];
}

// ---------------------------------------------------------------- 3.3 plant
export interface PlantInput {
  name: string;
  utc_offset: string;
  planning_horizon_days: number;
  currency: string;
  attributes: Attributes;
}

/** Unsaved default (3.3): `id: null`, `row_version: 0`, ETag "0"; timestamps are then null as well. */
export interface PlantRecord extends PlantInput {
  id: EntityId | null;
  row_version: number;
  created_at: IsoDateTime | null;
  updated_at: IsoDateTime | null;
  data_version?: number;
}

// ---------------------------------------------------------------- 3.4 item
export interface ItemInput {
  part_number: string;
  revision?: string;
  description?: string;
  uom?: string;
  make_buy: MakeBuy;
  family?: string | null;
  setup_family?: string | null;
  lead_time_days?: number | null;
  receiving_days?: number;
  lot_rule?: LotRule;
  fixed_lot_qty?: number | null;
  min_order_qty?: number;
  order_multiple?: number;
  safety_stock?: number;
  serialized?: boolean;
  shelf_life_days?: number | null;
  handling_class?: string | null;
  handling_note?: string;
  attributes?: Attributes;
  active?: boolean;
}

export interface ItemRecord extends RecordMeta {
  part_number: string;
  revision: string;
  description: string;
  uom: string;
  make_buy: MakeBuy;
  family: string | null;
  setup_family: string | null;
  lead_time_days: number | null;
  receiving_days: number;
  lot_rule: LotRule;
  fixed_lot_qty: number | null;
  min_order_qty: number;
  order_multiple: number;
  safety_stock: number;
  serialized: boolean;
  shelf_life_days: number | null;
  handling_class: string | null;
  handling_note: string;
  attributes: Attributes;
  active: boolean;
  has_bom: boolean;
  has_routing: boolean;
  used_in_count: number;
}

export type ItemSort = "part_number" | "-updated_at" | "description";

export interface ItemQuery {
  q?: string;
  make_buy?: MakeBuy;
  family?: string;
  active?: boolean;
  has_bom?: boolean;
  has_routing?: boolean;
  sort?: ItemSort;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------- 3.5 BOM
export interface BomLineInput {
  id?: EntityId | null;
  find_number: string;
  child_item_id: EntityId;
  qty_per: number;
  uom?: string;
  scrap_pct?: number;
  ref_designators?: string;
  alt_group?: string | null;
  alt_priority?: number;
  operation_seq?: number | null;
  note?: string;
}

export interface BomInput {
  item_id: EntityId;
  revision?: string;
  version?: number;
  effective_from?: IsoDate | null;
  effective_to?: IsoDate | null;
  serial_from?: number | null;
  serial_to?: number | null;
  note?: string;
  lines?: BomLineInput[];
}

export interface BomLineRecord {
  id: EntityId;
  find_number: string;
  child_item_id: EntityId;
  qty_per: number;
  uom: string;
  scrap_pct: number;
  ref_designators: string;
  alt_group: string | null;
  alt_priority: number;
  operation_seq: number | null;
  note: string;
  child: ItemRef;
}

export interface BomHeader extends RecordMeta {
  item_id: EntityId;
  revision: string;
  version: number;
  status: Status;
  effective_from: IsoDate | null;
  effective_to: IsoDate | null;
  serial_from: number | null;
  serial_to: number | null;
  note: string;
  released_at: IsoDateTime | null;
  obsoleted_at: IsoDateTime | null;
  item: ItemRef;
}

export interface BomRecord extends BomHeader {
  lines: BomLineRecord[];
}

export interface BomSummary extends BomHeader {
  line_count: number;
}

export interface ReleaseRequest {
  effective_from: IsoDate | null;
  supersede_previous: boolean;
}

export interface Superseded {
  id: EntityId;
  version: number;
  effective_to: IsoDate;
}

export interface BomReleaseResponse {
  bom: BomRecord;
  superseded: Superseded[];
}

export interface BomCopyRequest {
  revision: string | null;
}

// ---------------------------------------------------------------- 3.6 routing
export interface OperationToolInput {
  tool_pool_id: EntityId;
  qty: number;
}

export interface OperationInput {
  id?: EntityId | null;
  seq: number;
  name: string;
  description?: string;
  group_id: EntityId;
  setup_minutes?: number;
  run_minutes?: number;
  run_per?: RunPer;
  units_per_panel?: number | null;
  units_per_batch?: number | null;
  queue_minutes?: number;
  move_minutes?: number;
  wait_minutes?: number;
  labor?: Labor;
  crew_size?: number;
  skill_id?: EntityId | null;
  tools?: OperationToolInput[];
  transfer_batch?: number | null;
  yield_pct?: number;
  inspection_gate?: boolean;
  interruptible?: boolean;
}

export interface RoutingInput {
  item_id: EntityId;
  revision?: string;
  code?: string;
  version?: number;
  priority?: number;
  effective_from?: IsoDate | null;
  effective_to?: IsoDate | null;
  serial_from?: number | null;
  serial_to?: number | null;
  note?: string;
  operations?: OperationInput[];
}

export interface OperationToolRecord {
  tool_pool_id: EntityId;
  qty: number;
  tool_pool: Ref;
}

export interface OperationRecord {
  id: EntityId;
  seq: number;
  name: string;
  description: string;
  group_id: EntityId;
  setup_minutes: number;
  run_minutes: number;
  run_per: RunPer;
  units_per_panel: number | null;
  units_per_batch: number | null;
  queue_minutes: number;
  move_minutes: number;
  wait_minutes: number;
  labor: Labor;
  crew_size: number;
  skill_id: EntityId | null;
  tools: OperationToolRecord[];
  transfer_batch: number | null;
  yield_pct: number;
  inspection_gate: boolean;
  interruptible: boolean;
  group: Ref;
  skill: Ref | null;
}

export interface RoutingHeader extends RecordMeta {
  item_id: EntityId;
  revision: string;
  code: string;
  version: number;
  priority: number;
  status: Status;
  effective_from: IsoDate | null;
  effective_to: IsoDate | null;
  serial_from: number | null;
  serial_to: number | null;
  note: string;
  released_at: IsoDateTime | null;
  obsoleted_at: IsoDateTime | null;
  item: ItemRef;
}

export interface RoutingRecord extends RoutingHeader {
  operations: OperationRecord[];
}

export interface RoutingSummary extends RoutingHeader {
  operation_count: number;
}

/** 9.3 #21-27 "as BOMs": the release response carries the routing under `routing`. */
export interface RoutingReleaseResponse {
  routing: RoutingRecord;
  superseded: Superseded[];
}

export interface RoutingCopyRequest {
  revision: string | null;
  code: string | null;
}

// ---------------------------------------------------------------- 3.7 groups and lines
export interface GroupInput {
  code: string;
  name: string;
  description?: string;
  kind?: string | null;
  active?: boolean;
}

export interface GroupRecord extends RecordMeta {
  code: string;
  name: string;
  description: string;
  kind: string | null;
  active: boolean;
  line_count: number;
}

export interface GroupDetail extends GroupRecord {
  lines: LineRecord[];
  assignments: ShiftAssignmentRecord[];
}

export interface LineInput {
  group_id: EntityId;
  code: string;
  name: string;
  speed_factor?: number;
  parallel_capacity?: number;
  setup_family?: string | null;
  eligible_families?: string[];
  eligible_item_ids?: EntityId[];
  cost_per_hour?: number;
  active?: boolean;
}

export interface LineRecord extends RecordMeta {
  group_id: EntityId;
  code: string;
  name: string;
  speed_factor: number;
  parallel_capacity: number;
  setup_family: string | null;
  eligible_families: string[];
  eligible_item_ids: EntityId[];
  cost_per_hour: number;
  active: boolean;
  group: Ref;
  eligible_items: ItemRef[];
}

// ---------------------------------------------------------------- 3.8 shifts and calendar
export interface ShiftBreak {
  name: string;
  start: HHMM;
  end: HHMM;
}

export interface ShiftDef {
  name: string;
  days: Weekday[];
  start: HHMM;
  end: HHMM;
  breaks: ShiftBreak[];
}

export interface ShiftTemplateInput {
  code: string;
  name: string;
  description?: string;
  shifts: ShiftDef[];
}

export interface ShiftTemplateRecord extends RecordMeta {
  code: string;
  name: string;
  description: string;
  shifts: ShiftDef[];
  assignment_count: number;
  operator_count: number;
}

export interface WeekWindow {
  shift: string;
  day: Weekday;
  start_minute: number;
  end_minute: number;
}

export interface ShiftPreview {
  week_windows: WeekWindow[];
  minutes_per_day: Partial<Record<Weekday, number>>;
  total_minutes: number;
}

export interface ShiftAssignmentInput {
  shift_template_id: EntityId;
  target_type: TargetType;
  group_id?: EntityId | null;
  line_id?: EntityId | null;
  kind?: AssignmentKind;
  shift_names?: string[];
  effective_from: IsoDate;
  effective_to?: IsoDate | null;
  cost_per_hour?: number | null;
  max_hours_per_week?: number | null;
  note?: string;
}

export interface TargetRef {
  type: TargetType;
  id: EntityId;
  code: string;
  name: string;
}

export interface ShiftAssignmentRecord extends RecordMeta {
  shift_template_id: EntityId;
  target_type: TargetType;
  group_id: EntityId | null;
  line_id: EntityId | null;
  kind: AssignmentKind;
  shift_names: string[];
  effective_from: IsoDate;
  effective_to: IsoDate | null;
  cost_per_hour: number | null;
  max_hours_per_week: number | null;
  note: string;
  template: Ref;
  target: TargetRef;
}

export interface AssignmentQuery {
  group_id?: EntityId;
  line_id?: EntityId;
  shift_template_id?: EntityId;
}

export interface CalendarExceptionInput {
  scope: ExceptionScope;
  group_id?: EntityId | null;
  line_id?: EntityId | null;
  kind: ExceptionKind;
  start: IsoDateTime;
  end: IsoDateTime;
  label?: string;
}

export interface CalendarExceptionRecord extends RecordMeta {
  scope: ExceptionScope;
  group_id: EntityId | null;
  line_id: EntityId | null;
  kind: ExceptionKind;
  start: IsoDateTime;
  end: IsoDateTime;
  label: string;
  target: { type: "group" | "line"; id: EntityId; code: string; name: string } | null;
}

export interface ExceptionQuery {
  from?: IsoDate;
  to?: IsoDate;
  scope?: ExceptionScope;
  group_id?: EntityId;
  line_id?: EntityId;
}

export interface Window {
  start: IsoDateTime;
  end: IsoDateTime;
  kind: AssignmentKind;
  assignment_id: EntityId | null;
  shift_label: string;
  cost_per_hour: number | null;
}

export interface LineWindows {
  line_id: EntityId;
  from: IsoDate;
  to: IsoDate;
  utc_offset: string;
  windows: Window[];
  totals: { base_minutes: number; optional_minutes: number };
}

// ---------------------------------------------------------------- 3.9 skills, operators, tooling
export interface SkillInput {
  code: string;
  name: string;
  description?: string;
}

export interface SkillRecord extends RecordMeta {
  code: string;
  name: string;
  description: string;
  operator_count: number;
  operation_count: number;
}

export interface OperatorInput {
  code: string;
  name: string;
  skill_ids?: EntityId[];
  shift_template_id?: EntityId | null;
  shift_names?: string[];
  home_group_id?: EntityId | null;
  active?: boolean;
}

export interface OperatorRecord extends RecordMeta {
  code: string;
  name: string;
  skill_ids: EntityId[];
  shift_template_id: EntityId | null;
  shift_names: string[];
  home_group_id: EntityId | null;
  active: boolean;
  skills: Ref[];
  shift_template: Ref | null;
  home_group: Ref | null;
}

export interface OperatorQuery {
  q?: string;
  active?: boolean;
  skill_id?: EntityId;
}

export interface ToolPoolInput {
  code: string;
  name: string;
  kind?: string | null;
  quantity: number;
  note?: string;
}

export interface ToolPoolRecord extends RecordMeta {
  code: string;
  name: string;
  kind: string | null;
  quantity: number;
  note: string;
  operation_count: number;
}

// ---------------------------------------------------------------- 5 explosion / where-used / time preview
export interface Alternate {
  line_id: EntityId;
  item_id: EntityId;
  part_number: string;
  qty_per: number;
  line_uom: string;
  alt_priority: number;
}

export interface ExplosionRow {
  row: number;
  parent_row: number | null;
  subtree_end: number;
  level: number;
  line_id: EntityId | null;
  bom_id: EntityId | null;
  item_id: EntityId;
  part_number: string;
  revision: string;
  description: string;
  make_buy: MakeBuy;
  uom: string;
  family: string | null;
  lead_time_days: number | null;
  active: boolean;
  find_number: string | null;
  ref_designators: string;
  qty_per: number | null;
  line_uom: string | null;
  scrap_pct: number | null;
  operation_seq: number | null;
  extended_qty: number;
  alternates: Alternate[];
  is_phantom: boolean;
  has_children: boolean;
  is_shared: boolean;
  routing_id: EntityId | null;
}

export interface SummarizedRow {
  item_id: EntityId;
  part_number: string;
  description: string;
  make_buy: MakeBuy;
  uom: string;
  total_qty: number;
  min_level: number;
  max_level: number;
  occurrences: number;
  lead_time_days: number | null;
}

export interface ExplosionTotals {
  rows: number;
  distinct_items: number;
  max_level: number;
  make_items: number;
  buy_items: number;
  phantom_items: number;
}

export interface ExplosionWarning {
  code: string;
  message: string;
  item_id: EntityId | null;
}

interface ExplosionBase {
  item_id: EntityId;
  part_number: string;
  on: IsoDate | null;
  serial: number | null;
  qty: number;
  totals: ExplosionTotals;
  warnings: ExplosionWarning[];
}

export interface IndentedExplosion extends ExplosionBase {
  mode: "indented";
  rows: ExplosionRow[];
}

export interface SummarizedExplosion extends ExplosionBase {
  mode: "summarized";
  rows: SummarizedRow[];
}

export type Explosion = IndentedExplosion | SummarizedExplosion;
export type ExplosionMode = Explosion["mode"];

export interface ExplosionQuery {
  on?: IsoDate;
  serial?: number;
  qty?: number;
  mode?: ExplosionMode;
  include_scrap?: boolean;
  include_yield?: boolean;
  max_depth?: number;
}

export interface WhereUsedRow {
  row: number;
  level: number;
  parent_row: number | null;
  item_id: EntityId;
  part_number: string;
  revision: string;
  description: string;
  make_buy: MakeBuy;
  bom_id: EntityId;
  bom_revision: string;
  bom_version: number;
  bom_status: Status;
  line_id: EntityId;
  find_number: string;
  qty_per: number;
  line_uom: string;
  is_top: boolean;
}

export type WhereUsedMode = "single" | "indented";
export type WhereUsedInclude = "effective" | "all";

export interface WhereUsed {
  item_id: EntityId;
  part_number: string;
  mode: WhereUsedMode;
  include: WhereUsedInclude;
  on: IsoDate | null;
  rows: WhereUsedRow[];
  totals: { rows: number; top_items: number };
}

export interface WhereUsedQuery {
  on?: IsoDate;
  include?: WhereUsedInclude;
  mode?: WhereUsedMode;
}

export interface TimePreviewLine {
  line_id: EntityId;
  code: string;
  speed_factor: number;
  eligible: boolean;
  reason?: string | null;
  setup_minutes: number;
  run_minutes: number;
  total_minutes: number;
}

export interface TimePreviewOperation {
  seq: number;
  name: string;
  /** 9.4 shows `{id, code}`; `name` is accepted when present. */
  group: { id: EntityId; code: string; name?: string };
  input_qty: number;
  output_qty: number;
  run_per: RunPer;
  loads: number;
  queue_minutes: number;
  move_minutes: number;
  wait_minutes: number;
  labor: Labor;
  lines: TimePreviewLine[];
}

export interface TimePreview {
  routing_id: EntityId;
  item_id: EntityId;
  qty: number;
  uom: string;
  operations: TimePreviewOperation[];
  totals: { fastest_minutes: number; slowest_minutes: number; passive_minutes: number; cumulative_yield: number };
}

// ---------------------------------------------------------------- 7 health
export type HealthEntityType =
  | "item"
  | "bom"
  | "bom_line"
  | "routing"
  | "operation"
  | "group"
  | "line"
  | "shift_template"
  | "shift_assignment"
  | "calendar_exception"
  | "skill"
  | "operator"
  | "tool_pool"
  | "plant";

export interface HealthEntity {
  type: HealthEntityType;
  id: EntityId | null;
  label: string;
}

export interface HealthIssue {
  code: string;
  severity: Severity;
  message: string;
  fix: string;
  entity: HealthEntity;
  related: HealthEntity[];
  /** Built by the server from `entity` (11.3); the UI never derives it. */
  link: string | null;
  field: string | null;
}

export interface SeverityCounts {
  error: number;
  warning: number;
  info: number;
}

export interface HealthReport {
  ok: boolean;
  as_of: IsoDate;
  horizon_days: number;
  fingerprint: string;
  counts: SeverityCounts;
  by_code: Record<string, number>;
  truncated: boolean;
  issues: HealthIssue[];
  data_version: number;
}

export interface HealthQuery {
  as_of?: IsoDate;
  horizon_days?: number;
}

// ---------------------------------------------------------------- 8 / 9.6 import
export type Cell = string | number | boolean | null;
export type ImportFormat = "xlsx" | "csv" | "zip";
export type ImportStatus = "uploaded" | "mapped" | "committed";

export interface SheetMapping {
  target: string | null;
  columns: Record<string, string | null>;
}

export interface ImportOptions {
  replace_children: boolean;
  release: boolean;
  default_effective_from: IsoDate | null;
}

export interface ImportMappingRequest {
  sheets: Record<string, SheetMapping>;
  options: ImportOptions;
}

export interface ImportSheet {
  name: string;
  row_count: number;
  headers: string[];
  sample_rows: Cell[][];
  suggested: SheetMapping | null;
}

export interface SheetCounts {
  create: number;
  update: number;
  unchanged: number;
  delete: number;
}

export interface PreviewSheetCounts extends SheetCounts {
  error: number;
}

export interface RowError {
  sheet: string;
  row: number;
  column: string | null;
  code: string;
  message: string;
}

export interface ImportWarning {
  code: string;
  message: string;
  sheet: string | null;
}

export type CellChange = [Cell, Cell];

export interface ChangeSample {
  sheet: string;
  key: Record<string, Cell>;
  action: "create" | "update" | "delete" | "unchanged";
  fields?: Record<string, CellChange>;
}

export interface ImportPreview {
  ok: boolean;
  counts: Record<string, PreviewSheetCounts>;
  error_count: number;
  row_errors: RowError[];
  warnings: ImportWarning[];
  changes_sample: ChangeSample[];
}

export interface ImportResult {
  /** 9.4 shows an elided sheet as `{}`, so the per-sheet counts are partial. */
  counts: Record<string, Partial<SheetCounts>>;
  duration_ms: number;
  data_version?: number;
}

export interface ImportRecord {
  id: EntityId;
  row_version: number;
  status: ImportStatus;
  filename: string;
  format: ImportFormat;
  created_at?: IsoDateTime;
  expires_at: IsoDateTime;
  committed_at?: IsoDateTime | null;
  sheets: ImportSheet[];
  mapping: ImportMappingRequest | null;
  preview: ImportPreview | null;
  result: ImportResult | null;
}

export type FileFormat = "xlsx" | "zip";

// ---------------------------------------------------------------- 9.6 meta, summary, samples, reset
export interface UomInfo {
  code: string;
  dimension: string;
  factor: number;
  aliases: string[];
}

export type ColumnType = "str" | "int" | "float" | "bool" | "date" | "datetime" | "list" | "enum";

export interface ImportColumnSpec {
  field: string;
  type: ColumnType;
  required_on_create: boolean;
  key: boolean;
  enum_values: string[] | null;
  synonyms: string[];
}

export interface ImportSheetSpec {
  name: string;
  columns: ImportColumnSpec[];
}

export interface SampleInfo {
  id: string;
  name: string;
  description: string;
  counts: Record<string, number>;
}

export type MfgLimits = Record<string, number> & { max_body_bytes: number };

export interface Meta {
  uoms: UomInfo[];
  enums: {
    make_buy: string[];
    lot_rule: string[];
    status: string[];
    run_per: string[];
    labor: string[];
    assignment_kind: string[];
    target_type: string[];
    exception_scope: string[];
    exception_kind: string[];
    weekday: string[];
  };
  limits: MfgLimits;
  import_spec: { sheets: ImportSheetSpec[] };
  samples: SampleInfo[];
  health_codes: { code: string; severity: Severity }[];
}

export interface SummaryCounts {
  items: number;
  make: number;
  buy: number;
  phantom: number;
  boms: number;
  bom_lines: number;
  routings: number;
  operations: number;
  groups: number;
  lines: number;
  shift_templates: number;
  operators: number;
  tool_pools: number;
}

export interface Summary {
  counts: SummaryCounts;
  end_items: ItemRef[];
  data_version: number;
}

export interface SampleLoadResponse {
  sample_id: string;
  result: ImportResult;
  health: { ok: boolean; counts: SeverityCounts };
}

export interface ResetResponse {
  deleted: Record<string, number>;
}

export const RESET_PHRASE = "DELETE ALL MANUFACTURING DATA";

// ---------------------------------------------------------------- 9.2 error details
export interface DuplicateKeyDetails {
  key: Record<string, Cell>;
  existing_id: EntityId;
}

export interface InUseDetails {
  references: Record<string, number>;
}

export interface VersionMismatchDetails {
  current_version: number;
}

export interface CycleDetails {
  cycle: string[];
}

export interface ReleaseBlockedDetails {
  issues: HealthIssue[];
}

export interface ImportHasErrorsDetails {
  row_errors: RowError[];
  error_count: number;
}
