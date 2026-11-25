/**
 * M8 contract (docs/M8-DESIGN.md 3, 7.1, 11; routes in `backend/superplanner/api/mfg/router_m8.py`): forecasting,
 * safety stock proposals, item planning and packaging, the rate/campaign engine, sterilisation load planning, kanban,
 * planning settings, SAP S/4HANA settings and the validation kit. Field names are the JSON names. Written from the
 * design before the S0 fixture (`api/mfg/fixtures/example_m8.json`); `contractExamplesM8.ts` types examples against
 * these declarations, so `tsc` fails on drift once the fixture is copied in. Shapes the design leaves open are listed
 * in docs/M8-DESIGN.md 15 (UI notes).
 */
import type { EntityId, IsoDate, IsoDateTime } from "./types";

export type { EntityId, IsoDate, IsoDateTime };

export interface M8Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** Compact item reference embedded in M8 rows. */
export interface M8ItemRef {
  id: EntityId;
  part_number: string;
  name: string;
  uom: string;
  family?: string | null;
}

export interface M8Ref {
  id: EntityId;
  code: string;
  name: string;
}

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export type Bucket = "m" | "w";
export type AbcClass = "A" | "B" | "C";
export type XyzClass = "X" | "Y" | "Z";
export type DemandClass = "smooth" | "erratic" | "intermittent" | "lumpy" | "short";
export type ForecastMethod = "snaive" | "ma" | "ses" | "holt_damped" | "hw_add" | "hw_mul" | "croston" | "sba" | "zero";

// ---------------------------------------------------------------- 4.1 history (F1-F3)
export type HistorySource = "ledger" | "import" | "sap";
export interface DemandHistoryRow {
  id: EntityId;
  item_id: EntityId;
  period_start: IsoDate;
  bucket: Bucket;
  qty: number;
  cleaned_qty: number | null;
  source: HistorySource;
  /** `FC_OUTLIER` when the cleaner clipped the value */
  flags: string[];
  updated_at: IsoDateTime;
  row_version: number;
}
/** PUT /forecast/history/{id}: `cleaned_qty` null resets to the raw value. Reason is required. */
export interface HistoryUpdate {
  cleaned_qty: number | null;
  reason: string;
}

// ---------------------------------------------------------------- 4.2 runs (F4-F6)
export interface ForecastRunParams {
  label?: string;
  bucket?: Bucket | null;
  horizon_periods?: number | null;
  item_ids?: EntityId[] | null;
  outlier_clean?: boolean | null;
}
export interface ClassAccuracy {
  wape: number | null;
  bias: number | null;
  items: number;
}
export interface ForecastRunSummary {
  wape: number | null;
  bias: number | null;
  by_abc: Partial<Record<AbcClass, ClassAccuracy>>;
  method_mix: Partial<Record<ForecastMethod, number>>;
  flags: Record<string, number>;
}
export interface ForecastRun {
  id: EntityId;
  number: string;
  label: string;
  status: JobStatus;
  params: ForecastRunParams;
  as_of: IsoDate;
  item_count: number;
  summary: ForecastRunSummary | null;
  version_id: EntityId | null;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  actor: string | null;
  error: string | null;
}
export interface ForecastItemResult {
  item_id: EntityId;
  item: M8ItemRef;
  class: DemandClass;
  method: ForecastMethod;
  params: Record<string, number>;
  holdout_wape: number | null;
  bias: number | null;
  rmse1: number | null;
  flags: string[];
}
export interface ForecastRunDetail extends ForecastRun {
  results: M8Page<ForecastItemResult>;
}

// ---------------------------------------------------------------- 4.3 versions, lines, overrides (F7-F15)
export type VersionStatus = "draft" | "active" | "archived";
export interface ForecastVersion {
  id: EntityId;
  number: string;
  name: string;
  run_id: EntityId | null;
  run_number: string | null;
  status: VersionStatus;
  bucket: Bucket;
  start: IsoDate;
  periods: number;
  item_count: number;
  override_count: number;
  activated_by: string | null;
  activated_at: IsoDateTime | null;
  note: string;
  created_at: IsoDateTime;
  row_version: number;
}
export interface VersionInput {
  run_id: EntityId;
  name: string;
  note?: string;
  copy_overrides?: boolean;
}
/** One item row of the period grid (GET /forecast/versions/{id}/lines, a page of items). */
export interface ForecastGridRow {
  item: M8ItemRef;
  abc: AbcClass | null;
  xyz: XyzClass | null;
  class: DemandClass | null;
  method: ForecastMethod | null;
  wape: number | null;
  bias: number | null;
  flags: string[];
  /** one value per `periods` entry */
  stat: number[];
  final: number[];
  /** true where an override changed the period */
  overridden: boolean[];
}
export interface ForecastGrid {
  version_id: EntityId;
  bucket: Bucket;
  periods: IsoDate[];
  items: ForecastGridRow[];
  total: number;
  limit: number;
  offset: number;
}
export interface ForecastLinesQuery {
  item_id?: string;
  family?: string;
  abc?: string;
  xyz?: string;
  method?: string;
  flag?: string;
  q?: string;
  limit?: number;
  offset?: number;
}
export type OverrideMode = "abs" | "pct";
export interface ForecastOverride {
  id: EntityId;
  version_id: EntityId;
  item_id: EntityId | null;
  item: M8ItemRef | null;
  item_family: string | null;
  period_from: IsoDate;
  period_to: IsoDate;
  mode: OverrideMode;
  value: number;
  reason: string;
  seq: number;
  created_by: string | null;
  created_at: IsoDateTime;
  removed_at: IsoDateTime | null;
}
export interface OverrideInput {
  item_id?: EntityId | null;
  item_family?: string | null;
  period_from: IsoDate;
  period_to: IsoDate;
  mode: OverrideMode;
  value: number;
  reason: string;
}

// ---------------------------------------------------------------- F16 item panel, F17 accuracy
export interface ForecastPoint {
  period_start: IsoDate;
  qty: number;
}
export interface ForecastItemDetail {
  item: M8ItemRef;
  bucket: Bucket;
  abc: AbcClass | null;
  xyz: XyzClass | null;
  version_id: EntityId | null;
  history: (DemandHistoryRow & { outlier: boolean })[];
  fitted: ForecastPoint[];
  forecast: { period_start: IsoDate; stat_qty: number; final_qty: number }[];
  /** consumption per period of the active version (4.4): orders consumed forecast; open = unconsumed */
  consumption: { period_start: IsoDate; forecast: number; consumed: number; open: number; orders: number }[];
  method: { name: ForecastMethod; class: DemandClass; params: Record<string, number>; holdout_wape: number | null; bias: number | null; rmse1: number | null; flags: string[] } | null;
  accuracy: { lag1_wape: number | null; lag1_bias: number | null; lag3_wape: number | null; lag3_bias: number | null };
  overrides: ForecastOverride[];
}
export type AccuracyGroup = "item" | "family" | "abc";
export interface AccuracyRow {
  key: string;
  label: string;
  item: M8ItemRef | null;
  wape: number | null;
  bias: number | null;
  volume: number;
  items: number;
}
export interface AccuracyReport {
  lag: 1 | 3;
  bucket: Bucket;
  group_by: AccuracyGroup;
  periods: IsoDate[];
  overall: { wape: number | null; bias: number | null; volume: number };
  /** WAPE per closed period (trend), oldest first */
  trend: { period_start: IsoDate; wape: number | null; bias: number | null }[];
  rows: AccuracyRow[];
  backtest: { run_id: EntityId; run_number: string; summary: ForecastRunSummary } | null;
}

// ---------------------------------------------------------------- 5 safety stock (I1-I4)
export type SsDecision = "pending" | "approved" | "rejected";
export interface SsMatrixCell {
  count: number;
  value: number;
  service_level: number;
}
export interface SsRun {
  id: EntityId;
  number: string;
  status: JobStatus;
  params: Record<string, unknown>;
  forecast_version_id: EntityId | null;
  forecast_version_number: string | null;
  summary: {
    lines: number;
    pending: number;
    approved: number;
    rejected: number;
    delta_value: number;
    currency: string | null;
    /** keys "AX".."CZ" */
    matrix: Record<string, SsMatrixCell>;
  } | null;
  created_at: IsoDateTime;
  finished_at: IsoDateTime | null;
  actor: string | null;
  error: string | null;
}
export interface SsLine {
  id: EntityId;
  run_id: EntityId;
  item_id: EntityId;
  item: M8ItemRef;
  abc: AbcClass;
  xyz: XyzClass;
  service_level: number;
  z: number;
  d_day: number;
  sigma_d_day: number;
  lt_days: number;
  sigma_lt_days: number;
  current_ss: number;
  proposed_ss: number;
  delta_value: number;
  cover_days: number | null;
  /** `SS_CAPPED`, `SS_NO_COST`, ... */
  flags: string[];
  decision: SsDecision;
  decided_by: string | null;
  decided_at: IsoDateTime | null;
}
export interface SsDecideInput {
  line_ids: EntityId[];
  decision: "approved" | "rejected";
  reason: string;
}
export interface SsDecideResult {
  updated: number;
  lines: SsLine[];
}

// ---------------------------------------------------------------- 3 item planning and packaging (I5-I7)
export type Replenishment = "mrp" | "rate" | "kanban";
export type ReleaseMode = "none" | "bi" | "parametric";
export type PackLevel = "each" | "inner" | "case" | "pallet";
export interface ItemPlanning {
  item_id: EntityId;
  replenishment: Replenishment;
  forecast: boolean;
  like_item_id: EntityId | null;
  like_item: M8ItemRef | null;
  like_factor: number;
  service_level: number | null;
  order_pack_level: PackLevel | null;
  campaign_key: string | null;
  campaign_min_hours: number;
  campaign_max_hours: number | null;
  target_cover_days: number;
  ster_cycle_code: string | null;
  aeration_hours: number | null;
  release_mode: ReleaseMode;
  release_days: number;
  post_days: number | null;
  abc: AbcClass | null;
  xyz: XyzClass | null;
  row_version: number;
}
export type ItemPlanningInput = Omit<ItemPlanning, "item_id" | "like_item" | "abc" | "xyz" | "row_version">;
export interface PackagingLevel {
  level: PackLevel;
  seq: number;
  code: string;
  qty_base: number;
  gtin: string | null;
  weight_kg: number | null;
}
export interface ItemPackaging {
  item_id: EntityId;
  levels: PackagingLevel[];
  row_version: number;
}
/** `packs` on MRP quantities of items with packaging (6). */
export interface Packs {
  case?: number | null;
  pallet?: number | null;
}

// ---------------------------------------------------------------- 7 rate engine (R4-R9)
export type RateRunStatus = JobStatus | "failed_validation";
export type RateBlockKind = "production" | "changeover" | "cleaning" | "clearance" | "down";
export type OvertimePolicy = "off" | "suggest" | "allow";
export interface RateParams {
  label?: string;
  mrp_run_id?: EntityId | null;
  horizon_days?: number | null;
  line_ids?: EntityId[] | null;
  overtime?: OvertimePolicy;
  time_budget_s?: number | null;
  keep_firm?: boolean;
}
export interface RateObjective {
  shortage_unit_days: number;
  changeover_cost: number;
  changeover_hours: number;
  excess_cover_unit_days: number;
  overtime_cost: number;
}
export interface RateShortage {
  item_id: EntityId;
  item: M8ItemRef | null;
  due: IsoDate;
  qty: number;
  /** RATE_CAPACITY | RATE_NO_LINE | RATE_MIN_CAMPAIGN | RATE_CHANGEOVER_BOUND */
  cause: string;
  line_id: EntityId | null;
  load_pct: number | null;
  detail: string;
}
export interface RateExplanation {
  code: string;
  severity: "error" | "warning" | "info";
  item_id: EntityId | null;
  line_id: EntityId | null;
  detail: string;
  load_pct?: number | null;
}
export interface RateViolation {
  code: string;
  line_id: EntityId | null;
  block_ix: number | null;
  detail: string;
}
export interface RateLineSummary {
  line: M8Ref;
  available_hours: number;
  production_hours: number;
  changeover_hours: number;
  cleaning_hours: number;
  overtime_hours: number;
  campaigns: number;
  utilisation: number;
}
export interface RateRun {
  id: EntityId;
  number: string;
  label: string;
  status: RateRunStatus;
  params: RateParams;
  mrp_run_id: EntityId | null;
  mrp_run_number: number | null;
  as_of: IsoDate;
  horizon_days: number;
  published: boolean;
  published_at: IsoDateTime | null;
  published_by: string | null;
  objective: RateObjective | null;
  summary: {
    lines: RateLineSummary[];
    campaigns: number;
    blocks: number;
    produced_qty: number;
    shortage_qty: number;
    shortage_items: number;
    firm_until: IsoDate | null;
  } | null;
  shortages: RateShortage[];
  explanations: RateExplanation[];
  validator: { ok: boolean; violations: RateViolation[] } | null;
  duration_ms: number | null;
  created_at: IsoDateTime;
  actor: string | null;
  error: string | null;
  row_version: number;
}
export interface RateBlock {
  id: EntityId;
  line_id: EntityId;
  kind: RateBlockKind;
  item_id: EntityId | null;
  item: M8ItemRef | null;
  campaign_no: number;
  start: IsoDateTime;
  end: IsoDateTime;
  qty: number;
  cases: number | null;
  prod_date: IsoDate;
  wo_id: EntityId | null;
  wo_number: string | null;
  firm: boolean;
}
export interface RateGridCell {
  item_id: EntityId;
  qty: number;
  cases: number | null;
}
export interface RateGrid {
  bucket: "shift" | "day";
  buckets: { start: IsoDateTime; end: IsoDateTime; label: string; firm: boolean }[];
  items: Record<EntityId, { part_number: string; name: string; campaign_key: string | null }>;
  lines: {
    line: M8Ref;
    /** per bucket */
    available_hours: number[];
    used_hours: number[];
    changeover_hours: number[];
    cells: RateGridCell[][];
  }[];
}
export interface RateCompare {
  a: { id: EntityId; number: string; label: string; objective: RateObjective | null };
  b: { id: EntityId; number: string; label: string; objective: RateObjective | null };
  lines: { line: M8Ref; a: RateLineSummary | null; b: RateLineSummary | null }[];
  items: { item: M8ItemRef; a_qty: number; b_qty: number; a_short: number; b_short: number; a_campaigns: number; b_campaigns: number }[];
}
export interface RatePublishResult {
  run: RateRun;
  wo_created: number;
  wo_cancelled: number;
  wo_kept: number;
  rate_supplies: number;
}

// ---------------------------------------------------------------- 8 sterilisation (S1-S7)
export type SterStatus = "planned" | "loaded" | "cycling" | "aerating" | "awaiting_release" | "released" | "failed" | "cancelled";
export interface SterMember {
  id: EntityId;
  wo_id: EntityId | null;
  wo_number: string | null;
  rate_block_id: EntityId | null;
  lot_id: EntityId | null;
  lot_code: string | null;
  item_id: EntityId;
  item: M8ItemRef | null;
  qty: number;
  pallets: number;
}
export interface SterLoad {
  id: EntityId;
  number: string;
  run_id: EntityId | null;
  chamber_line_id: EntityId;
  chamber: M8Ref | null;
  chamber_pallets: number | null;
  cycle_code: string;
  release_mode: ReleaseMode;
  status: SterStatus;
  pallets: number;
  planned_start: IsoDateTime;
  planned_end: IsoDateTime;
  aeration_end: IsoDateTime;
  release_due: IsoDate | null;
  actual_start: IsoDateTime | null;
  actual_end: IsoDateTime | null;
  actual_aeration_end: IsoDateTime | null;
  batch_load_id: EntityId | null;
  release_signature_id: EntityId | null;
  ncr_id: EntityId | null;
  ncr_number: string | null;
  /** `STER_AERATION_BOUND`, ... */
  flags: string[];
  members: SterMember[];
  row_version: number;
}
export interface SterLoadList extends M8Page<SterLoad> {
  /** pallet positions of the aeration group(s) (8), for the utilisation chart */
  aeration_capacity: number | null;
}
export interface SterPlanResult {
  loads: number;
  warnings: { code: string; item_id: EntityId | null; detail: string }[];
}

// ---------------------------------------------------------------- 6.2 kanban (K1-K6)
export type KanbanSource = "buy" | "make";
export type KanbanTrigger = "scan" | "consumption";
export type CardState = "full" | "empty" | "in_process";
export interface KanbanLoop {
  id: EntityId;
  number: string;
  item_id: EntityId;
  item: M8ItemRef | null;
  location_id: EntityId;
  location: M8Ref | null;
  source: KanbanSource;
  supplier_id: EntityId | null;
  supplier: M8Ref | null;
  line_id: EntityId | null;
  line: M8Ref | null;
  cards: number;
  container_qty: number;
  lead_time_days: number;
  trigger: KanbanTrigger;
  status: "active" | "inactive";
  card_states: Record<CardState, number>;
  /** 6.2 sizing: cards = ceil(d x LT x 1.2 / container) + 1 */
  suggestion: { cards: number; d_day: number } | null;
  row_version: number;
}
export type KanbanLoopInput = Pick<KanbanLoop, "item_id" | "location_id" | "source" | "supplier_id" | "line_id" | "cards" | "container_qty" | "lead_time_days" | "trigger" | "status">;
export interface KanbanCard {
  id: EntityId;
  loop_id: EntityId;
  card_no: number;
  state: CardState;
  /** `KB:<card id>` */
  code: string;
  doc_type: "pr" | "wo" | null;
  doc_id: EntityId | null;
  doc_number: string | null;
  changed_at: IsoDateTime;
}
export interface KanbanScanResult {
  card: KanbanCard;
  loop: KanbanLoop;
  signal: { doc_type: "pr" | "wo"; doc_id: EntityId; number: string } | null;
}

// ---------------------------------------------------------------- 4.6 planning settings (N1-N2)
export interface PlanningSettings {
  forecast_bucket: Bucket;
  horizon_periods: number;
  history_basis: "shipments" | "orders";
  outlier_clean: boolean;
  consume_back_days: number;
  consume_fwd_days: number;
  forecast_priority: number;
  daily_days: number;
  weekly_weeks: number;
  abc_cutoffs: [number, number];
  xyz_cutoffs: [number, number];
  sl_matrix: Record<string, number>;
  ss_max_cover_days: number;
  rate_horizon_days: number;
  rate_firm_days: number;
  rate_wo_split: "day" | "campaign";
  rate_time_budget_s: number;
  ster_max_wait_hours: number;
  nightly_at: string;
  auto_publish: boolean;
  row_version: number;
}

// ---------------------------------------------------------------- 10 validation kit (V1-V4)
export interface TraceMatrix {
  generated_at: IsoDateTime | null;
  git_sha: string | null;
  totals: { requirements: number; covered: number; gaps: number; high_gaps: number; passed: number; failed: number; not_run: number };
  rows: { id: string; title: string; source: string; risk: "high" | "medium" | "low"; assurance: string; tests: number; last_result: "passed" | "failed" | "skipped" | "not_run" }[];
}
export interface Baseline {
  id: EntityId;
  label: string;
  sha256: string;
  created_by: string | null;
  created_at: IsoDateTime;
}
export interface BaselineDiff {
  a: Baseline;
  b: Baseline;
  changes: { path: string; a: unknown; b: unknown; kind: "added" | "removed" | "changed" }[];
}

// ---------------------------------------------------------------- 9 SAP S/4HANA (X1-X2)
export type SapEntity = "product" | "bom" | "routing" | "supplier" | "info_record" | "stock" | "purchase_order" | "sales_order" | "demand_history" | "planned_order" | "purchase_requisition" | "pir" | "confirmation" | "goods_movement" | "inspection_lot";
export interface SapSettings {
  enabled: boolean;
  base_url: string;
  plant: string;
  auth: "basic" | "oauth2";
  username: string | null;
  client_id: string | null;
  token_url: string | null;
  /** secrets are write-only; true when one is stored */
  has_secret: boolean;
  storage_locations: Record<string, EntityId>;
  unit_map: Record<string, string>;
  strip_zeros: boolean;
  mrp_controllers: string[];
  schedule: Partial<Record<SapEntity, string>>;
  cursors: { entity: SapEntity; cursor: string | null; last_run_at: IsoDateTime | null; last_status: "ok" | "failed" | "running" | null; records: number | null; message: string | null }[];
  row_version: number;
}
export interface SapSettingsInput extends Omit<SapSettings, "has_secret" | "cursors" | "row_version"> {
  /** null keeps the stored secret */
  secret?: string | null;
}
