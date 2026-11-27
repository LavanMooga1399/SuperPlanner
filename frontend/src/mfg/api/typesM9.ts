/**
 * M9 contract (docs/M9-DESIGN.md 3, 5.1, 6, 7, 8, 9; S0 freeze): network topology and DRP runs, the S&OP/IBP cycle
 * with scenarios and signed approval, and trade (country of origin, tariffs, FX, landed cost, domestic content,
 * supplier risk). Mirrors `backend/superplanner/mfg/{network,sop,trade}/model.py`; field names are the JSON names.
 * `contractExamplesM9.ts` types the S0 fixture (`api/mfg/fixtures/example_m9.json`) against these declarations, so
 * `tsc` fails on drift. UI interpretations of shapes the design leaves open are listed in M9-DESIGN 13.
 */
import type { EntityId, IsoDate, IsoDateTime } from "./types";
import type { SignatureManifest } from "./typesM7";

export type { EntityId, IsoDate, IsoDateTime };

export interface M9Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface M9List<T> {
  items: T[];
}

export type M9RunStatus = "queued" | "running" | "completed" | "failed";
export interface M9Violation {
  code: string;
  detail: unknown;
}
export interface M9Validator {
  ok: boolean;
  violations: M9Violation[];
}
/** Engine explanation / warning: a code plus where it applies (texts are keyed in the UI by code). */
export interface M9Explanation {
  code: string;
  node?: EntityId | null;
  key?: string | null;
  family?: string | null;
  week?: IsoDate | null;
  month?: IsoDate | null;
  detail?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------- 4 topology (N1-N7, N16)
export type NodeKind = "plant" | "dc" | "network";
export type LaneMode = "road" | "rail" | "sea" | "air";
export const LANE_MODES: readonly LaneMode[] = ["road", "rail", "sea", "air"];

/** GET /net/nodes: the org's plant and DC workspaces. `member` = the caller may open that plant's records. */
export interface NetNodeInfo {
  owner_id: EntityId;
  code: string;
  name: string;
  kind: Exclude<NodeKind, "network">;
  country: string | null;
  currency: string;
  tz: string;
  member: boolean;
  lines: number;
}

export interface NetLaneInput {
  from_owner_id: EntityId;
  to_owner_id: EntityId;
  mode: LaneMode;
  transit_days: number;
  freight_per_unit: number;
  freight_per_kg: number | null;
  currency: string;
  active: boolean;
}
export interface NetLane extends NetLaneInput {
  id: EntityId;
  row_version: number;
  updated_at: IsoDateTime;
}

export type SourceKind = "plant" | "supplier";
export interface SourcingRuleInput {
  dest_owner_id: EntityId;
  /** exactly one of item_key / family */
  item_key: string | null;
  family: string | null;
  source_kind: SourceKind;
  source_owner_id: EntityId | null;
  supplier_code: string | null;
  priority: number;
  quota_pct: number | null;
  lane_id: EntityId | null;
  valid_from: IsoDate | null;
  valid_to: IsoDate | null;
  active: boolean;
}
export interface SourcingRule extends SourcingRuleInput {
  id: EntityId;
  row_version: number;
  updated_at: IsoDateTime;
}
export interface SourcingResolveSource {
  rule_id: EntityId;
  source_kind: SourceKind;
  source_owner_id: EntityId | null;
  supplier_code: string | null;
  priority: number;
  quota_pct: number | null;
  lane_id: EntityId | null;
  transit_days: number | null;
}
/** N7: which rules apply for (dest, key, date); `mode none` = the key is not networked at that node. */
export interface SourcingResolve {
  dest_owner_id: EntityId;
  key: string;
  date: IsoDate;
  family: string | null;
  matched_by: "item" | "family" | null;
  mode: "quota" | "priority" | "none";
  sources: SourcingResolveSource[];
  warnings: string[];
}

export interface RampPoint {
  week: number;
  rate_pct: number;
  yield_pct: number;
}
export interface RampCurve {
  code: string;
  name: string;
  points: RampPoint[];
}

// ---------------------------------------------------------------- 5 network runs (N8-N15)
export interface NetParams {
  as_of?: IsoDate | null;
  horizon_weeks?: number | null;
  constrained?: boolean | null;
  prebuild_weeks?: number | null;
  firm_days?: number | null;
  node_ids?: EntityId[] | null;
  forecast_versions?: Record<EntityId, EntityId> | null;
  label?: string;
}
export interface NetKpis {
  fill_rate: number | null;
  shortage_units: number;
  inventory_value: number | null;
  transfer_units: number;
  currency: string;
}
export interface NetRunSummary extends NetKpis {
  nodes: number;
  keys: number;
  transfers: number;
  firm_transfers: number;
  shortages: number;
  max_utilisation: number | null;
}
export type NetShortageCause = "NET_CAPACITY_SHORT" | "NET_NO_SOURCE" | "NET_LEAD_TIME" | "NET_SUPPLIER_CAP";
export interface NetPublishTo {
  to_id: EntityId;
  number: string;
  src_owner_id: EntityId;
  dst_owner_id: EntityId;
  ship_date: IsoDate;
  lines: number;
  qty: number;
}
export interface NetPublishResult {
  created: NetPublishTo[];
  kept: NetPublishTo[];
  cancelled: NetPublishTo[];
  network_demands: number;
  network_supplies: number;
  warnings: M9Explanation[];
}
export interface NetRun {
  id: EntityId;
  number: string;
  label: string;
  status: M9RunStatus;
  as_of: IsoDate;
  params: NetParams;
  input_hash: string | null;
  summary: NetRunSummary | null;
  validator: M9Validator | null;
  explanations: M9Explanation[];
  published: boolean;
  published_at: IsoDateTime | null;
  published_by: string | null;
  publish_result: NetPublishResult | null;
  error: string | null;
  actor_id: string | null;
  created_at: IsoDateTime;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  duration_ms: number | null;
}

export interface NetPeg {
  node: EntityId;
  kind: "order" | "forecast" | "ss" | "dependent" | "transfer";
  ref: string;
  qty: number;
}
export interface NetGridCell {
  week: IsoDate;
  gross: number;
  receipts: number;
  planned_in: number;
  planned_out: number;
  projected: number;
  ss: number;
}
/** N10: one (node, key) projection row over the run's weeks. */
export interface NetGridRow {
  node_owner_id: EntityId;
  item_key: string;
  item_id: EntityId | null;
  description: string | null;
  family: string | null;
  uom: string;
  cells: NetGridCell[];
}
export interface NetGrid extends M9Page<NetGridRow> {
  weeks: IsoDate[];
}
export interface NetTransfer {
  id: EntityId;
  src_owner_id: EntityId;
  dst_owner_id: EntityId;
  item_key: string;
  lane_id: EntityId | null;
  ship_date: IsoDate;
  receive_date: IsoDate;
  qty: number;
  uom: string;
  firm: boolean;
  to_id: EntityId | null;
  to_number: string | null;
  pegs: NetPeg[];
}
export interface NetShortage {
  id: EntityId;
  node_owner_id: EntityId;
  item_key: string;
  week: IsoDate;
  qty: number;
  uom: string;
  cause: NetShortageCause;
  detail: Record<string, unknown>;
}
export interface NetUtilisation {
  node: EntityId;
  cap_group: string;
  week: IsoDate;
  available: number;
  used: number;
}
export type NetPegKind = "demand" | "transfer" | "production" | "purchase" | "supply" | "component" | "shortage";
/** N14: pegging tree (down from a demand or up from a supply); `link` only for plants the caller is a member of. */
export interface NetPegNode {
  id: string;
  kind: NetPegKind;
  node_owner_id: EntityId;
  item_key: string;
  week: IsoDate | null;
  qty: number;
  ref: string | null;
  cause: string | null;
  link: string | null;
  children: NetPegNode[];
}
export interface NetPegging {
  direction: "down" | "up";
  root: NetPegNode;
}

// ---------------------------------------------------------------- 6 S&OP cycle (S1-S10)
export type SopStep = "draft" | "demand_review" | "supply_review" | "pre_sop" | "executive" | "approved" | "published";
export type SopStatus = SopStep | "cancelled";
export const SOP_STEPS: readonly SopStep[] = ["draft", "demand_review", "supply_review", "pre_sop", "executive", "approved", "published"];
export interface SopStepInfo {
  step: SopStep;
  due: IsoDate | null;
  owner_id: string | null;
  owner_name: string | null;
  done_at: IsoDateTime | null;
  done_by: string | null;
  note: string | null;
  overdue: boolean;
}
export interface SopPublishNode {
  node: EntityId;
  forecast_version_id: EntityId | null;
  targets: number;
  warnings: M9Explanation[];
}
export interface SopFollowUp {
  change_id: string;
  kind: ScenarioChangeKind;
  label: string;
  node: EntityId | null;
}
export interface SopPublishResult {
  nodes: SopPublishNode[];
  follow_ups: SopFollowUp[];
  published_at: IsoDateTime;
}
export interface SopCycle {
  id: EntityId;
  row_version: number;
  number: string;
  period: IsoDate;
  horizon_months: number;
  status: SopStatus;
  steps: SopStepInfo[];
  demand_sources: Record<EntityId, EntityId>;
  recommended_scenario_id: EntityId | null;
  recommend_note: string | null;
  approved_scenario_id: EntityId | null;
  content_hash: string | null;
  publish_result: SopPublishResult | null;
  publish_job_status: M9RunStatus | null;
  reopen_reason: string | null;
  report_currency: string;
  signatures: SignatureManifest[];
  people?: Record<string, string>;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export type AspSource = "history" | "cost" | "manual";
export interface SopDemandRow {
  id: EntityId;
  node_owner_id: EntityId;
  family: string;
  month: IsoDate;
  stat_qty: number;
  order_qty: number;
  base_qty: number;
  prior_consensus: number | null;
  consensus_qty: number;
  asp: number | null;
  asp_currency: string;
  asp_source: AspSource;
}
export interface SopOverride {
  id: EntityId;
  node_owner_id: EntityId | null;
  family: string;
  month_from: IsoDate;
  month_to: IsoDate;
  mode: "abs" | "pct";
  value: number;
  reason: string;
  seq: number;
  created_by: string;
  created_at: IsoDateTime;
  removed_at: IsoDateTime | null;
}
export interface SopOverrideInput {
  node_owner_id: EntityId | null;
  family: string;
  month_from: IsoDate;
  month_to: IsoDate;
  mode: "abs" | "pct";
  value: number;
  reason: string;
}
export interface SopDemand {
  months: IsoDate[];
  families: string[];
  items: SopDemandRow[];
  overrides: SopOverride[];
}
export interface SopAspInput {
  rows: { node_owner_id: EntityId; family: string; asp: number; currency: string }[];
  reason?: string;
}

// ---------------------------------------------------------------- 7 scenarios (S11-S21)
export type ScenarioChangeKind = "add_line" | "add_node" | "capacity_change" | "sourcing" | "make_vs_buy" | "supplier_allocation" | "demand_change" | "cost_change";
export const SCENARIO_CHANGE_KINDS: readonly ScenarioChangeKind[] = ["add_line", "add_node", "capacity_change", "sourcing", "make_vs_buy", "supplier_allocation", "demand_change", "cost_change"];
interface ChangeBase {
  id: string;
  label: string;
  note: string;
}
export interface AddLineChange extends ChangeBase {
  kind: "add_line";
  node: string;
  cap_group: string;
  name: string;
  start: IsoDate;
  hours_per_week: number;
  hpu_by_family: Record<string, number> | null;
  uph_by_family: Record<string, number> | null;
  oee: number | null;
  curve: string | null;
  points: RampPoint[] | null;
  capex: number | null;
  capex_currency: string | null;
  fixed_cost_per_month: number | null;
}
export interface AddNodeChange extends ChangeBase {
  kind: "add_node";
  code: string;
  name: string;
  node_kind: "plant" | "dc";
  country: string;
  currency: string;
  start: IsoDate;
  lanes: { from: string | null; to: string | null; mode: LaneMode; transit_days: number; freight_per_unit: number }[];
}
export interface CapacityChange extends ChangeBase {
  kind: "capacity_change";
  node: string;
  cap_group: string;
  from: IsoDate;
  to: IsoDate | null;
  pct: number;
}
export interface ShareRow {
  source_node?: string | null;
  supplier_code?: string | null;
  code?: string | null;
  min_share: number;
  max_share: number;
  cap_per_month?: number | null;
}
export interface SourcingChange extends ChangeBase {
  kind: "sourcing";
  dest_node: string;
  family: string;
  sources: ShareRow[];
}
export interface BuyOption {
  code: string;
  unit_price: number;
  currency: string;
  coo: string | null;
  hts_code: string | null;
  freight_per_unit: number | null;
  cap_per_month: number | null;
}
export interface MakeVsBuyChange extends ChangeBase {
  kind: "make_vs_buy";
  node: string;
  family: string;
  option: "make" | "buy" | "both";
  supplier: BuyOption | null;
}
export interface SupplierAllocationChange extends ChangeBase {
  kind: "supplier_allocation";
  node: string;
  family: string;
  suppliers: ShareRow[];
}
export interface DemandChange extends ChangeBase {
  kind: "demand_change";
  node: string | null;
  family: string | null;
  from: IsoDate;
  to: IsoDate | null;
  pct: number;
}
export interface CostChange extends ChangeBase {
  kind: "cost_change";
  tariff: TariffRateInput[] | null;
  fx: { from: string; to: string; rate: number; from_month: IsoDate } | null;
  freight: { lane: EntityId; pct: number } | null;
}
export type ScenarioChange = AddLineChange | AddNodeChange | CapacityChange | SourcingChange | MakeVsBuyChange | SupplierAllocationChange | DemandChange | CostChange;

export interface SopKpiSet {
  delivered_units: number;
  consensus_units: number;
  unmet_units: number;
  service_pct: number | null;
  revenue: number | null;
  cogs: number | null;
  gross_margin: number | null;
  gm_pct: number | null;
  inventory_value: number | null;
  days_of_cover: number | null;
  capex: number;
}
export interface SopKpis {
  currency: string;
  horizon: SopKpiSet;
  year: SopKpiSet;
  next3: SopKpiSet;
  utilisation: { node: EntityId | string; cap_group: string; max_pct: number; avg_pct: number }[];
  domestic: { milestone_id: EntityId; code: string; family: string | null; min_pct: number; share_pct: number | null; first_missed_month: IsoDate | null }[];
}
export type ScenarioStatus = "draft" | "running" | "completed" | "failed";
export interface SopScenarioInput {
  name: string;
  changes: ScenarioChange[];
  capex_note: string;
  enforce_milestones?: boolean;
}
export interface SopScenario extends SopScenarioInput {
  id: EntityId;
  row_version: number;
  number: string;
  cycle_id: EntityId | null;
  baseline: boolean;
  status: ScenarioStatus;
  input_hash: string | null;
  kpis: SopKpis | null;
  validator: M9Validator | null;
  warnings: M9Explanation[];
  error: string | null;
  run_at: IsoDateTime | null;
  updated_at: IsoDateTime;
}
export interface SopPlanRow {
  node_owner_id: EntityId | string;
  family: string;
  month: IsoDate;
  consensus: number;
  make: number;
  buy: Record<string, number>;
  ship_in: number;
  ship_out: number;
  inv: number;
  delivered: number;
  unmet: number;
  ss_short: number;
  ss_target: number;
}
export interface SopPlan {
  months: IsoDate[];
  items: SopPlanRow[];
}
export interface SopRoughCutRow {
  node_owner_id: EntityId | string;
  cap_group: string;
  month: IsoDate;
  available: number;
  required: number;
  planned: number;
  /** required / available, 0..n (1 = 100 %) */
  util: number | null;
  factor: number | null;
}
export interface SopRoughCut {
  months: IsoDate[];
  items: SopRoughCutRow[];
}
export interface SopFinRow {
  /** node owner id, family, or "total" */
  key: string;
  month: IsoDate | null;
  revenue: number | null;
  cogs: number | null;
  freight: number | null;
  gross_margin: number | null;
  gm_pct: number | null;
  inventory_value: number | null;
  days_of_cover: number | null;
  capex: number;
}
export interface SopFinancial {
  currency: string;
  group_by: "total" | "node" | "family";
  months: IsoDate[];
  rows: SopFinRow[];
  totals: { horizon: SopFinRow; year: SopFinRow; next3: SopFinRow };
  warnings: M9Explanation[];
}
export interface SopMakeBuyRow {
  node_owner_id: EntityId | string;
  family: string;
  currency: string;
  make_unit_cost: number | null;
  buy: { supplier_code: string; coo: string | null; landed_unit_cost: number | null; duty_share: number | null }[];
  split_make: number;
  split_buy: number;
  hours_freed: number;
}
export interface SopCompareEntry {
  scenario: { id: EntityId; number: string; name: string; status: ScenarioStatus; baseline: boolean; validator_ok: boolean | null };
  kpis: SopKpis | null;
  /** difference to the first scenario (null for the first) */
  delta: { horizon: Partial<SopKpiSet>; year: Partial<SopKpiSet>; next3: Partial<SopKpiSet> } | null;
}
export interface SopCompare {
  currency: string;
  items: SopCompareEntry[];
}

// ---------------------------------------------------------------- MPS targets (P5)
export interface MpsTarget {
  id: EntityId;
  cycle_id: string;
  cycle_number: string | null;
  family: string;
  month: IsoDate;
  qty_target: number;
  hours: Record<string, number>;
  actual_qty: number;
  attainment: number | null;
}

// ---------------------------------------------------------------- 8 trade (T1-T8, P1-P4)
export type TariffLayer = "mfn" | "s232" | "s301" | "surtax" | "reciprocal" | string;
export interface TariffRateInput {
  dest_country: string;
  hts_prefix: string;
  coo: string;
  layer: TariffLayer;
  rate_pct: number;
  per_unit: number | null;
  per_unit_currency: string | null;
  valid_from: IsoDate;
  valid_to: IsoDate | null;
  note: string;
}
export interface TariffRate extends TariffRateInput {
  id: EntityId;
}
export interface FxRateInput {
  from_ccy: string;
  to_ccy: string;
  month: IsoDate;
  rate: number;
  source: string;
}
export interface FxRate extends FxRateInput {
  id: EntityId;
}
export interface MilestoneRule {
  domestic_country: string;
  basis: "value" | "weight";
  material_classes: string[];
  include_conversion: boolean;
  min_pct: number;
}
export interface MilestoneInput {
  code: string;
  name: string;
  dest_country: string;
  family: string | null;
  hts_prefix: string | null;
  rule: MilestoneRule;
  effective: IsoDate;
  note: string;
}
export interface Milestone extends MilestoneInput {
  id: EntityId;
}
export interface CountryRiskInput {
  country: string;
  score: number;
  note: string;
}
export interface BulkResult {
  inserted: number;
  updated: number;
  deleted: number;
}

export type MilestoneStatus = "met" | "at_risk" | "missed";
export interface TradeReportCell {
  month: IsoDate;
  share_pct: number | null;
  status: MilestoneStatus | null;
  projected: boolean;
  lots: number;
  lots_below: number;
  qty_below_pct: number | null;
  estimated_pct: number | null;
}
export interface TradeReportLot {
  plant_owner_id: EntityId;
  lot_id: EntityId;
  lot_code: string;
  item_key: string;
  month: IsoDate;
  qty: number;
  share_pct: number | null;
  estimated: boolean;
}
export interface TradeReportMilestone {
  milestone_id: EntityId;
  code: string;
  name: string;
  min_pct: number;
  effective: IsoDate;
  basis: "value" | "weight";
  groups: { key: string; label: string; cells: TradeReportCell[] }[];
  first_missed_month: IsoDate | null;
  lots_below: TradeReportLot[];
}
export interface TradeReportParams {
  milestone_ids: EntityId[];
  from: IsoDate;
  to: IsoDate;
  nodes?: EntityId[] | null;
  group_by: "family" | "item";
  projection?: { scenario_id?: EntityId | null } | null;
}
export interface TradeReport {
  id: EntityId;
  number: string;
  params: TradeReportParams;
  status: M9RunStatus;
  result: { months: IsoDate[]; projection_from: IsoDate | null; projection_source: string | null; milestones: TradeReportMilestone[] } | null;
  error: string | null;
  actor_id: string | null;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

export interface ContentNode {
  kind: "made" | "bought" | "possible" | "conversion";
  lot_id: EntityId | null;
  lot_code: string | null;
  item_key: string;
  description: string | null;
  coo: string | null;
  material_class: string | null;
  qty: number;
  uom: string;
  value: number | null;
  weight_kg: number | null;
  domestic: number | null;
  estimated: boolean;
  children: ContentNode[];
}
/** T7 / P4: a lot's domestic share and its input tree. */
export interface LotContent {
  lot_id: EntityId;
  lot_code: string;
  item_key: string;
  coo: string | null;
  coo_source: CooSource | null;
  share_value: number | null;
  share_weight: number | null;
  estimated: boolean;
  computed_at: IsoDateTime | null;
  milestone_id: EntityId | null;
  currency: string;
  tree: ContentNode;
}
export type CooSource = "receipt" | "supplier" | "item" | "plant" | "transfer";

export interface DutyLayer {
  layer: TariffLayer;
  rate_pct: number;
  per_unit: number | null;
  amount: number;
}
/** 8.4 per base unit in plant currency; `total` null when FX is missing. */
export interface LandedCost {
  unit_price: number | null;
  freight: number;
  customs_value: number | null;
  duty: DutyLayer[];
  other: number | null;
  total: number | null;
  currency: string;
  fx_rate: number | null;
  flags: string[];
}
export interface LandedRow {
  item_supplier_id: EntityId;
  supplier_code: string;
  supplier_name: string;
  coo: string | null;
  hts_code: string | null;
  incoterm: string | null;
  preferred: boolean;
  landed: LandedCost;
}

export type RiskFlag = "single_source" | "sole_country";
export interface RiskSuggestion {
  supplier_code: string;
  supplier_name: string;
  node_owner_id: EntityId;
  coo: string | null;
  landed_delta: number | null;
  score: number | null;
  basis: "family" | "heading";
}
export interface RiskRow {
  node_owner_id: EntityId;
  item_id: EntityId;
  item_key: string;
  part_number: string;
  description: string;
  family: string | null;
  supplier_code: string;
  supplier_name: string;
  coo: string | null;
  score: number;
  parts: { single_source: number; country: number; lead_time: number; otd: number; tariff: number };
  flags: RiskFlag[];
  spend_12m: number;
  currency: string;
  otd_pct: number | null;
  lead_days: number | null;
  duty_pct: number | null;
  suggestions: RiskSuggestion[];
}

export interface ItemTradeInput {
  hts_code: string | null;
  coo: string | null;
  material_class: string | null;
  unit_weight_kg: number | null;
}
export interface ItemTrade extends ItemTradeInput {
  item_id: EntityId;
  row_version: number;
}

// ---------------------------------------------------------------- network workspace (O1) and tiles
export interface NetworkCreated {
  owner_id: EntityId;
  code: string;
  name: string;
}
