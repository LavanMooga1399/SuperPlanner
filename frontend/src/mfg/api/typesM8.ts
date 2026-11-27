/**
 * M8 contract (docs/M8-DESIGN.md 3, 7.1, 11; S0 freeze): forecasting, safety stock proposals, item planning and
 * packaging, the rate/campaign engine, sterilisation load planning, kanban, planning settings, SAP S/4HANA settings
 * and the validation kit. Mirrors `backend/superplanner/mfg/{forecast,invopt,rate,ster}/model.py` and
 * `mfg/model_m8.py`; field names are the JSON names. `contractExamplesM8.ts` types the S0 fixture
 * (`api/mfg/fixtures/example_m8.json`) against these declarations, so `tsc` fails on drift.
 */
import type { EntityId, IsoDate, IsoDateTime } from "./types";

export type { EntityId, IsoDate, IsoDateTime };

export interface M8Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** Item reference embedded in M8 records (`{id, part_number, name, revision}`). */
export interface M8ItemRef {
  id: EntityId;
  part_number: string;
  name: string;
  revision?: string | null;
}

export type RunStatus = "queued" | "running" | "completed" | "failed";
export type Bucket = "m" | "w";
export type AbcClass = "A" | "B" | "C";
export type XyzClass = "X" | "Y" | "Z";
export type DemandClass = "smooth" | "erratic" | "intermittent" | "lumpy" | "short";
export type ForecastMethod = "zero" | "snaive" | "ma" | "ses" | "holt_damped" | "hw_add" | "hw_mul" | "croston" | "sba";
export type ForecastFlag = "FC_OUTLIER" | "FC_HISTORY_SHORT" | "FC_HIGH_ERROR" | "FC_LIKE_ITEM" | "FC_OVERCONSUMED" | "FC_NO_COST";

// ---------------------------------------------------------------- 4.1 history (F1-F3)
export type HistorySource = "ledger" | "import" | "sap";
export interface HistoryRecord {
  id: EntityId;
  item_id: EntityId;
  period_start: IsoDate;
  bucket: Bucket;
  qty: number;
  cleaned_qty: number | null;
  source: HistorySource;
  outlier: boolean;
  updated_at: IsoDateTime;
}
/** PUT /forecast/history/{id}: `cleaned_qty` null = use the raw value. */
export interface HistoryUpdate {
  cleaned_qty: number | null;
  reason: string;
}
export interface HistoryRefreshResult {
  rows_written: number;
  items: number;
  periods: number;
  outliers: number;
}

// ---------------------------------------------------------------- 4.2 runs (F4-F6)
export interface ForecastParams {
  label?: string;
  as_of?: IsoDate | null;
  bucket?: Bucket | null;
  horizon_periods?: number | null;
  item_ids?: EntityId[] | null;
  methods?: ForecastMethod[] | null;
  create_version?: boolean;
}
export interface ClassAccuracy {
  wape: number | null;
  bias: number | null;
  items: number;
}
export interface ForecastSummary {
  wape?: number | null;
  bias?: number | null;
  by_abc?: Partial<Record<AbcClass, ClassAccuracy>>;
  method_mix?: Partial<Record<ForecastMethod, number>>;
  flags?: Record<string, number>;
}
export interface ForecastRun {
  id: EntityId;
  number: string;
  params: Record<string, unknown>;
  status: RunStatus;
  as_of: IsoDate;
  bucket: Bucket;
  first_period?: IsoDate | null;
  item_count: number;
  summary: ForecastSummary;
  version_id?: EntityId | null;
  error?: string | null;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  actor_id: string;
}
export interface ItemResult {
  item_id: EntityId;
  part_number?: string | null;
  demand_class: DemandClass;
  adi: number | null;
  cv2: number | null;
  method: ForecastMethod;
  params: Record<string, number>;
  holdout_wape: number | null;
  bias: number | null;
  rmse1: number | null;
  mean: number;
  n_periods: number;
  abc?: AbcClass | null;
  flags: ForecastFlag[];
  /** last 12 fitted values, aligned to the end of the history */
  fitted_tail: number[];
  /** statistical forecast from the run's first period */
  forecast: number[];
  candidates: Record<string, number | null>;
}
export interface ForecastRunDetail extends ForecastRun {
  results: M8Page<ItemResult>;
}

// ---------------------------------------------------------------- 4.3 versions, lines, overrides (F7-F15)
export type VersionStatus = "draft" | "active" | "archived";
export interface VersionInput {
  run_id: EntityId;
  name: string;
  copy_overrides?: boolean;
  note?: string;
}
export interface ForecastVersion {
  id: EntityId;
  number: string;
  name: string;
  run_id: EntityId | null;
  status: VersionStatus;
  bucket: Bucket;
  start: IsoDate;
  periods: number;
  item_count: number;
  total_stat: number;
  total_final: number;
  override_count: number;
  activated_by: string | null;
  activated_at: IsoDateTime | null;
  note: string;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
/** One item of a version (GET /forecast/versions/{id}/lines, a page of items). */
export interface ForecastLine {
  item_id: EntityId;
  part_number?: string | null;
  family?: string | null;
  abc?: string | null;
  xyz?: string | null;
  method?: string | null;
  periods: IsoDate[];
  stat: number[];
  final: number[];
  overridden: boolean[];
}
export interface ForecastLinesQuery {
  item_id?: string;
  family?: string;
  abc?: string;
  q?: string;
  limit?: number;
  offset?: number;
}
export type OverrideMode = "abs" | "pct";
export interface OverrideInput {
  item_id?: EntityId | null;
  item_family?: string | null;
  period_from: IsoDate;
  period_to: IsoDate;
  mode: OverrideMode;
  value: number;
  reason: string;
}
export interface ForecastOverride extends OverrideInput {
  id: EntityId;
  version_id: EntityId;
  seq: number;
  created_by: string;
  created_at: IsoDateTime;
  removed_at?: IsoDateTime | null;
  /** final values touched: [{item_id, period_start, old, new}] */
  changes: { item_id: EntityId; period_start: IsoDate; old: number; new: number }[];
}

// ---------------------------------------------------------------- F16 item view, F17 accuracy
export interface ConsumptionRow {
  item_id: EntityId;
  period_start: IsoDate;
  forecast: number;
  consumed: number;
  open: number;
  orders: number;
  overconsumed?: number;
}
export interface LagAccuracy {
  wape: number | null;
  bias: number | null;
  periods: number;
}
export interface ForecastItemView {
  item: M8ItemRef;
  planning: { abc?: AbcClass | null; xyz?: XyzClass | null; forecast?: boolean; replenishment?: string };
  history: HistoryRecord[];
  result: ItemResult | null;
  versions: { version_id: EntityId; number: string; status: VersionStatus; periods: IsoDate[]; final: number[] }[];
  consumption: ConsumptionRow[];
  accuracy: { lag1?: LagAccuracy | null; lag3?: LagAccuracy | null };
}
export type AccuracyGroup = "item" | "family" | "abc" | "all";
export interface AccuracyRow {
  key: string;
  label: string;
  periods: number;
  actual: number;
  forecast: number;
  wape: number | null;
  bias: number | null;
}
export interface AccuracyReport {
  lag: 1 | 3;
  group_by: AccuracyGroup;
  rows: AccuracyRow[];
  /** latest run summary (holdout backtest) */
  backtest?: ForecastSummary | null;
}

// ---------------------------------------------------------------- 5 safety stock (I1-I4)
export type SsDecision = "pending" | "approved" | "rejected";
export interface SsParams {
  label?: string;
  forecast_version_id?: EntityId | null;
  item_ids?: EntityId[] | null;
}
export interface SsRun {
  id: EntityId;
  number: string;
  params: Record<string, unknown>;
  status: RunStatus;
  forecast_version_id: EntityId | null;
  /** {lines, pending, delta_value, matrix: {AX: {count, value}}, capped} */
  summary: { lines?: number; pending?: number; delta_value?: number; capped?: number; matrix?: Record<string, { count: number; value: number }> };
  error?: string | null;
  created_at: IsoDateTime;
  finished_at: IsoDateTime | null;
}
export interface SsLine {
  id: EntityId;
  run_id: EntityId;
  item_id: EntityId;
  part_number?: string | null;
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
  decided: number;
  skipped: number;
  items_updated: number;
}

// ---------------------------------------------------------------- 3 item planning and packaging (I5-I7)
/** M9 2: `transfer` = supplied by the network run (no planned orders from plant MRP). */
export type Replenishment = "mrp" | "rate" | "kanban" | "transfer";
export type ReleaseMode = "none" | "bi" | "parametric";
export type PackLevel = "each" | "inner" | "case" | "pallet";
export interface ItemPlanningInput {
  replenishment: Replenishment;
  forecast: boolean;
  like_item_id: EntityId | null;
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
}
export interface ItemPlanning extends ItemPlanningInput {
  /** null until first saved (defaults shown) */
  id: EntityId | null;
  item_id: EntityId;
  abc?: AbcClass | null;
  xyz?: XyzClass | null;
  row_version: number;
}
export interface PackagingLevelInput {
  level: PackLevel;
  code: string;
  qty_base: number;
  gtin: string | null;
  weight_kg: number | null;
}
export interface PackagingLevel extends PackagingLevelInput {
  id: EntityId;
  seq: number;
}
export interface ItemPackaging {
  item_id: EntityId;
  levels: PackagingLevel[];
  /** the item planning row version (If-Match for PUT) */
  row_version: number;
}
/** `packs` on MRP quantities of items with packaging (6). */
export interface Packs {
  case?: number | null;
  pallet?: number | null;
}

// ---------------------------------------------------------------- R1-R3 line rates, changeover matrix
export interface LinePlanningInput {
  planning: "discrete" | "flow" | "sterilisation";
  oee: number;
  clearance_minutes: number;
  clean_every_hours: number | null;
  clean_minutes: number | null;
  chamber_pallets: number | null;
  cycle_hours: number | null;
}
export interface LineRates {
  line_id: EntityId;
  line_code: string;
  line: LinePlanningInput;
  rates: { id: EntityId; item_id: EntityId | null; item_family: string | null; units_per_hour: number; oee: number | null }[];
  row_version: number;
}
export interface ChangeoverMatrix {
  rows: { id: EntityId; line_setup_family: string; from_key: string; to_key: string; minutes: number; cost: number; kind: "changeover" | "cleaning" | "clearance" }[];
  version: number;
}

// ---------------------------------------------------------------- 7 rate engine (R4-R9)
export type RateRunStatus = RunStatus | "failed_validation";
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
  due: IsoDate;
  qty: number;
  /** RATE_CAPACITY | RATE_NO_LINE | RATE_MIN_CAMPAIGN | RATE_CHANGEOVER_BOUND */
  cause: string;
  detail?: Record<string, unknown>;
}
export interface RateExplanation {
  code: string;
  severity: "error" | "warning" | "info";
  item_id?: EntityId | null;
  line_id?: EntityId | null;
  message: string;
  detail?: Record<string, unknown>;
}
export interface RateViolation {
  code: string;
  line_id: EntityId | null;
  block_ix: number | null;
  detail: unknown;
}
export interface RateRun {
  id: EntityId;
  number: string;
  label: string;
  params: Record<string, unknown>;
  status: RateRunStatus;
  mrp_run_id: EntityId | null;
  as_of: IsoDate;
  horizon_days: number;
  published: boolean;
  published_at: IsoDateTime | null;
  published_by: string | null;
  objective: Partial<RateObjective> | null;
  /** {lines, blocks, campaigns, production_qty, shortage_qty, utilisation: {line_id: fraction}} */
  summary: { lines?: number; blocks?: number; campaigns?: number; production_qty?: number; shortage_qty?: number; utilisation?: Record<EntityId, number> } | null;
  explanations: RateExplanation[] | null;
  validator: { ok: boolean; violations: RateViolation[] } | null;
  shortages?: RateShortage[] | null;
  duration_ms: number | null;
  error?: string | null;
  created_at: IsoDateTime;
  finished_at?: IsoDateTime | null;
}
export interface RateBlock {
  id: EntityId;
  line_id: EntityId;
  line_code?: string | null;
  kind: RateBlockKind;
  item_id: EntityId | null;
  part_number?: string | null;
  campaign_no: number;
  start: IsoDateTime;
  end: IsoDateTime;
  qty: number;
  cases: number | null;
  prod_date: IsoDate;
  wo_id: EntityId | null;
}
export interface RateGridCell {
  line_id: EntityId;
  /** ISO date (day) or "YYYY-MM-DDTHH" shift start */
  bucket: string;
  item_id: EntityId | null;
  part_number?: string | null;
  qty: number;
  cases: number | null;
  hours: number;
}
export interface RateGrid {
  bucket: "shift" | "day";
  buckets: string[];
  lines: { line_id: EntityId; code: string; utilisation: Record<string, number> }[];
  cells: RateGridCell[];
}
export interface RateCompare {
  a: EntityId;
  b: EntityId;
  /** metric -> {a, b, delta} */
  objective: Record<string, { a: number; b: number; delta: number }>;
  lines: { line_id: EntityId; code: string; a_qty: number; b_qty: number; a_changeovers: number; b_changeovers: number }[];
  items: { item_id: EntityId; part_number?: string | null; a_qty: number; b_qty: number; a_short: number; b_short: number }[];
}
export interface RatePublishResult {
  run_id: EntityId;
  created_wo_ids: EntityId[];
  cancelled_wo_ids: EntityId[];
  kept_wo_ids: EntityId[];
  rate_supplies: number;
  /** groups held by started work orders whose quantity differs from the plan (no second WO) */
  skipped?: { wo_id: EntityId; wo_number?: string | null; item_id: EntityId; due: IsoDate | null; planned_qty: number; wo_qty: number }[];
}

// ---------------------------------------------------------------- 8 sterilisation (S1-S7)
export type SterStatus = "planned" | "loaded" | "cycling" | "aerating" | "awaiting_release" | "released" | "failed" | "cancelled";
export interface SterMember {
  id: EntityId;
  wo_id: EntityId | null;
  wo_number?: string | null;
  rate_block_id: EntityId | null;
  lot_id: EntityId | null;
  lot_code?: string | null;
  item_id: EntityId;
  part_number?: string | null;
  qty: number;
  pallets: number;
}
export interface SterLoad {
  id: EntityId;
  number: string;
  run_id: EntityId | null;
  chamber_line_id: EntityId;
  chamber_code?: string | null;
  cycle_code: string;
  status: SterStatus;
  pallets: number;
  planned_start: IsoDateTime;
  planned_end: IsoDateTime;
  aeration_end: IsoDateTime;
  release_due: IsoDate;
  actual_start?: IsoDateTime | null;
  actual_end?: IsoDateTime | null;
  actual_aeration_end?: IsoDateTime | null;
  batch_load_id: EntityId | null;
  release_signature_id: EntityId | null;
  ncr_id: EntityId | null;
  /** `STER_AERATION_BOUND`, ... */
  flags: string[];
  members: SterMember[];
  /** lots under this load's sterility holds (requested in M8-DESIGN 15; optional until the backend sends it) */
  lots?: { lot_id: EntityId; lot_code: string }[] | null;
  signatures: Record<string, unknown>[];
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
export interface SterPlanInput {
  from_date?: IsoDate | null;
  days?: number;
  chamber_line_ids?: EntityId[] | null;
}
export interface SterPlanResult {
  loads: number;
  pallets: number;
  skipped: { key?: string; item_id?: EntityId; code?: string }[];
  warnings: { code: string; load_ix?: number; detail?: Record<string, unknown> }[];
  load_ids: EntityId[];
}
export type SterAdvanceTo = "cycling" | "aerating" | "awaiting_release" | "cancelled";

// ---------------------------------------------------------------- 6.2 kanban (K1-K6)
export type KanbanSource = "buy" | "make";
export type KanbanTrigger = "scan" | "consumption";
export type CardState = "full" | "empty" | "in_process";
export interface KanbanLoopInput {
  item_id: EntityId;
  location_id: EntityId;
  source: KanbanSource;
  supplier_id: EntityId | null;
  line_id: EntityId | null;
  cards: number;
  container_qty: number;
  lead_time_days: number;
  trigger: KanbanTrigger;
  status: "active" | "inactive";
}
export interface KanbanLoop extends KanbanLoopInput {
  id: EntityId;
  number: string;
  item?: M8ItemRef | null;
  location_code?: string | null;
  card_counts: Partial<Record<CardState, number>>;
  consumed_since_signal: number;
  /** 6.2 sizing: cards = ceil(d x LT x 1.2 / container) + 1 */
  sizing: { daily_demand?: number | null; suggested_cards?: number | null; undersized?: boolean };
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
export interface KanbanCard {
  id: EntityId;
  loop_id: EntityId;
  card_no: number;
  /** `KB:<card id>` */
  code: string;
  state: CardState;
  doc_type?: "pr" | "wo" | string | null;
  doc_id?: EntityId | null;
  doc_number?: string | null;
  changed_at: IsoDateTime;
}
export interface KanbanScanResult {
  card: KanbanCard;
  loop_id: EntityId;
  signal: { doc_type: string; doc_id: EntityId; number: string; qty: number } | null;
}

// ---------------------------------------------------------------- 4.6 planning settings (N1-N2)
export interface PlanningSettingsInput {
  forecast_bucket: Bucket;
  horizon_periods: number;
  history_basis: "shipments" | "orders";
  outlier_clean: boolean;
  consume_back_days: number;
  consume_fwd_days: number;
  forecast_priority: number;
  daily_days: number;
  weekly_weeks: number;
  abc_cutoffs: number[];
  xyz_cutoffs: number[];
  sl_matrix: Record<string, number>;
  ss_max_cover_days: number;
  rate_horizon_days: number;
  rate_firm_days: number;
  rate_wo_split: "day" | "campaign";
  rate_time_budget_s: number;
  ster_max_wait_hours: number;
  nightly_at: string;
  nightly_enabled: boolean;
  auto_publish: boolean;
}
export interface PlanningSettings extends PlanningSettingsInput {
  row_version: number;
}
export interface NightlyRunResult {
  run_id: EntityId;
  status: string;
  steps: { step: string; status: string; ref_id: EntityId | null; error: string | null }[];
  started_at?: IsoDateTime | null;
}

// ---------------------------------------------------------------- 10 validation kit (V1-V4)
export interface TraceMatrixRow {
  id: string;
  title: string;
  risk: "high" | "medium" | "low";
  tests: string[];
  last_result: string | null;
}
export interface TraceMatrix {
  generated_at: IsoDateTime | null;
  requirements: number;
  covered: number;
  gaps: { id: string; title: string; risk: "high" | "medium" | "low" }[];
  high_risk_gaps: number;
  rows: TraceMatrixRow[];
  csv_url?: string | null;
}
export interface Baseline {
  id: EntityId;
  label: string;
  sha256: string;
  created_by: string;
  created_at: IsoDateTime;
  content?: Record<string, unknown> | null;
}
export interface BaselineDiff {
  a: EntityId;
  b: EntityId;
  a_sha256: string;
  b_sha256: string;
  same: boolean;
  changes: { path: string; kind: "added" | "removed" | "changed"; a: unknown; b: unknown }[];
}

// ---------------------------------------------------------------- 9 SAP S/4HANA (X1-X2)
export type SapEntity = "product" | "bom" | "routing" | "supplier" | "info_record" | "stock" | "purchase_order" | "sales_order" | "billing" | "planned_order_out" | "pr_out" | "pir_out" | "confirmation_out";
export const SAP_IN_ENTITIES: readonly SapEntity[] = ["product", "bom", "routing", "supplier", "info_record", "stock", "purchase_order", "sales_order", "billing"];
export interface SapSettingsInput {
  enabled: boolean;
  base_url: string;
  odata_version: "v2" | "v4";
  plant: string;
  auth: "basic" | "oauth2";
  username: string;
  /** write-only; null keeps the stored value */
  password?: string | null;
  token_url: string;
  client_id: string;
  client_secret?: string | null;
  location_map: Record<string, string>;
  unit_map: Record<string, string>;
  mrp_controllers: string[];
  strip_zeros: boolean;
  order_types: Record<string, string>;
  page_size: number;
  /** minutes between pulls per entity (0 = manual) */
  schedule: Partial<Record<SapEntity, number>>;
}
export interface SapSettings extends SapSettingsInput {
  password_set: boolean;
  client_secret_set: boolean;
  cursors: Record<string, string>;
  /** `error` = "<OData code or HTTP_<status>> (HTTP <status>)", never a response body */
  last_sync: Record<string, { at: IsoDateTime | null; status: string; records: number | null; error: string | null; packaging_skipped?: number | null }>;
  row_version: number;
}
export interface SapSyncResult {
  run_id: EntityId;
  status: string;
  entities: string[];
}
