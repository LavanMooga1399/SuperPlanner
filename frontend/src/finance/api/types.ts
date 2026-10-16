/**
 * TypeScript mirrors of docs/FINANCE.md (cited "F.n"): sections 4, 6, 7, 10.1, 12-14, 18 and 19.
 * Field names are exactly the JSON names of the API (snake_case). Do not rename.
 */
import type { ProblemRecord } from "../../api/types";

// ---------------------------------------------------------------- F.4 basic types
/** `^[A-Za-z0-9_.:\-]{1,64}$` */
export type Id = string;
/** `"YYYY-MM"` */
export type Month = string;
export type Frequency = "monthly" | "quarterly" | "half_yearly" | "yearly" | "once";
export type Priority = "must" | "should" | "nice";

// ---------------------------------------------------------------- F.4.2 - 4.11
export interface Profile {
  currency: string;
  locale: string;
  age: number | null;
  retirement_age: number;
  risk_tolerance: number;
  tax_note: string;
}

export type IncomeKind = "salary" | "business" | "rental" | "pension" | "interest" | "other";

export interface IncomeStream {
  id: Id;
  name: string;
  kind: IncomeKind;
  /** nominal take-home per occurrence */
  amount: number;
  frequency: Frequency;
  growth_pct: number;
  start_month: Month | null;
  end_month: Month | null;
  interruptible: boolean;
}

export interface Expense {
  id: Id;
  name: string;
  category: string;
  /** today's money per occurrence */
  amount: number;
  frequency: Frequency;
  essential: boolean;
  inflation_linked: boolean;
  inflation_pct: number | null;
  start_month: Month | null;
  end_month: Month | null;
}

export type DebtKind = "home" | "vehicle" | "education" | "personal" | "credit_card" | "other";

export interface Debt {
  id: Id;
  name: string;
  kind: DebtKind;
  balance: number;
  interest_rate_pct: number;
  emi: number;
  remaining_months: number | null;
}

export interface Holding {
  id: Id;
  name: string;
  asset_class_id: Id;
  amount: number;
  locked_until_month: Month | null;
}

export interface OneOff {
  id: Id;
  name: string;
  kind: "expense" | "inflow";
  month: Month;
  amount: number;
  inflation_linked: boolean;
}

export interface Earmark {
  holding_id: Id;
  amount: number;
}

export type GoalKind = "retirement" | "education" | "home" | "vehicle" | "travel" | "wedding" | "business" | "other";

export interface Goal {
  id: Id;
  name: string;
  kind: GoalKind;
  /** today's money */
  target_amount: number;
  target_month: Month;
  priority: Priority;
  flexibility_months: number;
  min_success_probability: number | null;
  inflation_pct: number | null;
  risk_tolerance: number | null;
  allowed_asset_class_ids: Id[] | null;
  earmarked: Earmark[];
  enabled: boolean;
}

export interface EmergencyFundSettings {
  months_of_essentials: number;
  asset_class_id: Id;
  build_share: number;
}

export type AssetCategory = "cash" | "debt" | "equity" | "gold" | "other";

export interface AssetClass {
  id: Id;
  name: string;
  category: AssetCategory;
  expected_return_pct: number;
  volatility_pct: number;
  expense_ratio_pct: number;
  tax_drag_pct: number;
  liquidity_days: number;
  lock_in_months: number;
  min_monthly_contribution: number;
  description: string;
}

export interface Correlation {
  a: Id;
  b: Id;
  rho: number;
}

export interface GlideStep {
  min_months_to_goal: number;
  multiplier: number;
}

export interface Assumptions {
  inflation_pct: number;
  inflation_volatility_pct: number;
  cash_class_id: Id;
  asset_classes: AssetClass[];
  correlations: Correlation[];
  risky_cap_by_tolerance_pct: number[];
  glide_path: GlideStep[];
  source_note: string;
}

export interface PlanConstraints {
  max_equity_pct: number | null;
  max_class_pct: Record<Id, number>;
  min_cash_buffer: number;
  contribution_block_months: 6 | 12;
  rebalance_cost_pct: number;
}

export interface WizardMetadata {
  completed_steps?: string[];
}

/** F.4.1 stored document (as returned by the server: every field filled). */
export interface FinancePlan {
  id: Id;
  name: string;
  description: string;
  schema_version: 1;
  start_month: Month | null;
  horizon_end_month: Month | null;
  profile: Profile;
  incomes: IncomeStream[];
  expenses: Expense[];
  debts: Debt[];
  holdings: Holding[];
  one_offs: OneOff[];
  goals: Goal[];
  emergency_fund: EmergencyFundSettings;
  assumptions: Assumptions;
  constraints: PlanConstraints;
  metadata: { wizard?: WizardMetadata } & Record<string, unknown>;
}

/** POST bodies may omit every defaulted field (F8 flexible input). */
export type FinancePlanInput = Partial<FinancePlan> & { name: string };

// ---------------------------------------------------------------- F.6 preflight
export interface FinanceIssue {
  code: string;
  severity: "error" | "warning";
  message: string;
  field: string | null;
  item_ids: string[];
}

export interface FinancePreflightReport {
  ok: boolean;
  issues: FinanceIssue[];
}

// ---------------------------------------------------------------- F.7 cash-flow summary
export interface CashflowYear {
  year: number;
  start_month: Month;
  income: number;
  essential: number;
  discretionary: number;
  debt_payments: number;
  one_off_net: number;
  surplus: number;
}

export interface CashflowSummary {
  ef_target: number;
  ef_initial: number;
  ef_complete_month: Month | null;
  avg_monthly_surplus_first_year: number;
  min_monthly_surplus: number;
  negative_surplus_months: Month[];
  debts_paid_off: { debt_id: Id; month: Month | null }[];
  years: CashflowYear[];
}

// ---------------------------------------------------------------- F.10.1 run request
export interface IncomeInterruption {
  enabled: boolean;
  annual_probability: number;
  duration_months: number;
}

export interface SimulationSettings {
  n_paths: number;
  income_interruption: IncomeInterruption;
}

export interface FinanceRunRequest {
  time_limit_seconds?: number;
  seed?: number;
  simulation?: Partial<Omit<SimulationSettings, "income_interruption">> & {
    income_interruption?: Partial<IncomeInterruption>;
  };
  calibration_rounds?: number;
  compute_fixes?: boolean;
  label?: string | null;
}

// ---------------------------------------------------------------- F.13 what-if
export interface GoalOverride {
  goal_id: Id;
  target_month?: Month | null;
  target_amount?: number | null;
  priority?: Priority | null;
  enabled?: boolean | null;
  risk_tolerance?: number | null;
}

export interface IncomeDrop {
  start_month: Month;
  months: number;
  percent: number;
}

export interface WhatIfChanges {
  label?: string | null;
  extra_monthly_savings?: number;
  goal_overrides?: GoalOverride[];
  risk_tolerance?: number | null;
  return_shift_pct?: number;
  inflation_pct?: number | null;
  income_drop?: IncomeDrop | null;
  emergency_build_share?: number | null;
}

// ---------------------------------------------------------------- F.11 violations
export interface FinanceViolation {
  code: string;
  severity: "hard" | "soft";
  message: string;
  goal_id: string | null;
  asset_class_id: string | null;
  months: Month[];
  amount: number | null;
  details: Record<string, unknown>;
}

// ---------------------------------------------------------------- F.12 explanations
export interface Reason {
  code: string;
  message: string;
  months: Month[];
  asset_class_ids: string[];
  values: Record<string, number | string>;
}

export type FixKind =
  | "DELAY_GOAL"
  | "INCREASE_SAVINGS"
  | "SPEND_LESS"
  | "INCREASE_RISK"
  | "REDUCE_TARGET"
  | "LOWER_EF_BUILD_SHARE";

export interface Fix {
  kind: FixKind;
  goal_id: string | null;
  message: string;
  months: number | null;
  amount: number | null;
  new_target_month: Month | null;
  new_risk_tolerance: number | null;
  resulting_shortfall_real: number | null;
  resulting_success_probability: number | null;
  relative_change: number;
  smallest: boolean;
  what_if: WhatIfChanges;
}

export interface GoalExplanation {
  reasons: Reason[];
  fixes: Fix[];
}

export interface Binding {
  code: string;
  message: string;
  months: Month[];
  goal_ids: string[];
}

export interface Explanation {
  summary: string[];
  goals: Record<string, GoalExplanation>;
  binding_constraints: Binding[];
  assumptions: string[];
  limitations: string[];
  replanning_triggers: string[];
}

// ---------------------------------------------------------------- F.14 result
export type FinFeasibility = "feasible" | "infeasible" | "unknown";
export type GoalStatus = "on_track" | "at_risk" | "off_track";

export interface FinanceResultTotals {
  goals_total: number;
  goals_on_track: number;
  goals_at_risk: number;
  goals_off_track: number;
  monthly_investable_now: number;
  monthly_contribution_now: number;
  emergency_fund_target: number;
  emergency_fund_now: number;
  emergency_fund_complete_month: Month | null;
  liquidity_risk_probability: number;
  total_contributions_real: number;
}

export interface GoalResult {
  goal_id: Id;
  name: string;
  kind: GoalKind;
  priority: Priority;
  target_month: Month;
  months_to_goal: number;
  target_amount: number;
  target_real: number;
  target_nominal_expected: number;
  planned_value_real: number;
  projected_central_real: number;
  shortfall_real: number;
  shortfall_fraction: number;
  success_probability: number;
  min_success_probability: number;
  p10_real: number;
  p50_real: number;
  p90_real: number;
  expected_shortfall_real: number;
  scenario_low_real: number;
  scenario_high_real: number;
  status: GoalStatus;
  contribution_start_month: Month | null;
  contribution_end_month: Month | null;
  monthly_contribution_now: number;
  total_contributions_real: number;
  holdings_used_real: number;
  allocation_now_pct: Record<Id, number>;
  planning_z: number;
}

export interface ContributionLine {
  /** goal id or "emergency_fund" */
  goal_id: string;
  asset_class_id: Id;
  start_month: Month;
  end_month: Month;
  monthly_amount_real: number;
  monthly_amount_nominal_start: number;
  monthly_amount_nominal_end: number;
}

export type HoldingSource = "earmark" | "assigned" | "initial_ef" | "initial_cash" | "sold_to_cash" | "unallocated";

export interface HoldingAssignment {
  holding_id: Id;
  /** goal id or "emergency_fund" | "cash_buffer" | "unallocated" */
  goal_id: string;
  amount: number;
  source: HoldingSource;
}

export interface Rebalance {
  month: Month;
  goal_id: Id;
  sells: Record<Id, number>;
  buys: Record<Id, number>;
}

export interface GlidePoint {
  month: Month;
  months_to_goal: number;
  risky_cap_pct: number;
  risky_share_pct: number;
  weights_pct: Record<Id, number>;
}

export interface ResultSeries {
  months: Month[];
  corpus_by_class: Record<Id, number[]>;
  emergency_fund: number[];
  cash_buffer: number[];
  unallocated: number[];
  goal_withdrawals: number[];
  total_p10: number[];
  total_p50: number[];
  total_p90: number[];
}

export interface ResultCashflow {
  months: Month[];
  income: number[];
  essential: number[];
  discretionary: number[];
  debt_payments: number[];
  one_off_net: number[];
  surplus: number[];
  emergency_fund_contribution: number[];
  goal_contribution: number[];
  cash_buffer_end: number[];
}

export interface ScenarioValues {
  low: number;
  central: number;
  high: number;
}

export interface ResultScenarios {
  definitions: { low: string; central: string; high: string };
  goals: Record<Id, ScenarioValues>;
}

export interface AssumptionsUsed {
  inflation_pct: number;
  asset_classes: AssetClass[];
  glide_path: GlideStep[];
  risky_cap_by_tolerance_pct: number[];
  /** goal id -> class id -> cautious real return % */
  planning_returns_pct: Record<Id, Record<Id, number>>;
}

export interface TierDiagnostic {
  tier: string;
  status: string;
  objective: number | null;
  seconds: number;
}

export interface FinanceDiagnostics {
  solver: string;
  variables: number;
  constraints: number;
  tiers: TierDiagnostic[];
  calibration_rounds: number;
  simulation_seconds: number;
  fix_solves: number;
  warnings: string[];
}

export interface FinanceResult {
  engine_version: string;
  disclaimer: string;
  disclaimer_version: string;
  start_month: Month;
  horizon_months: number;
  end_month: Month;
  currency: string;
  feasibility: FinFeasibility;
  termination_reason: string;
  optimality_proven: boolean;
  summary: FinanceResultTotals;
  goals: GoalResult[];
  contributions: ContributionLine[];
  holdings_assignment: HoldingAssignment[];
  rebalances: Rebalance[];
  glide_paths: Record<Id, GlidePoint[]>;
  series: ResultSeries;
  cashflow: ResultCashflow;
  scenarios: ResultScenarios;
  explanation: Explanation;
  violations: FinanceViolation[];
  assumptions_used: AssumptionsUsed;
  simulation_settings: SimulationSettings & { seed: number };
  diagnostics: FinanceDiagnostics;
}

export type FinanceResultKind = "baseline" | "what_if";

/** F.14 `FinanceResultSummary` */
export interface FinanceResultSummary {
  id: Id;
  plan_id: Id;
  run_id: Id;
  plan_version_id: Id;
  base_plan_version: number;
  kind: FinanceResultKind;
  label: string | null;
  feasibility: FinFeasibility;
  goals_total: number;
  goals_on_track: number;
  goals_at_risk: number;
  goals_off_track: number;
  monthly_contribution_now: number;
  created_at: string;
  what_if: WhatIfChanges | null;
}

/** F.18.1 `FinanceResultRecord` */
export interface FinanceResultRecord extends FinanceResultSummary {
  result: FinanceResult;
  plan: FinancePlan;
}

// ---------------------------------------------------------------- F.13 comparison
export interface ComparisonTotals {
  monthly_contribution_now_a: number;
  monthly_contribution_now_b: number;
  monthly_contribution_now_delta: number;
  ef_complete_month_a: Month | null;
  ef_complete_month_b: Month | null;
  goals_on_track_a: number;
  goals_on_track_b: number;
  liquidity_risk_a: number;
  liquidity_risk_b: number;
}

export interface ComparisonGoal {
  goal_id: Id;
  name: string;
  in_a: boolean;
  in_b: boolean;
  target_month_a: Month | null;
  target_month_b: Month | null;
  success_a: number | null;
  success_b: number | null;
  success_delta: number | null;
  p50_a: number | null;
  p50_b: number | null;
  p50_delta: number | null;
  shortfall_a: number | null;
  shortfall_b: number | null;
  monthly_now_a: number | null;
  monthly_now_b: number | null;
  status_a: GoalStatus | null;
  status_b: GoalStatus | null;
}

export interface FinanceComparison {
  a: FinanceResultSummary;
  b: FinanceResultSummary;
  totals: ComparisonTotals;
  goals: ComparisonGoal[];
  what_if_b: WhatIfChanges | null;
}

// ---------------------------------------------------------------- F.15 templates
export interface FinanceTemplateParameter {
  name: string;
  label: string;
  type: "int" | "money" | "month_offset_years";
  default: number;
  min: number | null;
  max: number | null;
  help: string;
}

export interface FinanceTemplateInfo {
  id: string;
  name: string;
  description: string;
  parameters: FinanceTemplateParameter[];
}

export interface FinanceInstantiateRequest {
  name?: string;
  start_month?: Month;
  parameters?: Record<string, number>;
}

// ---------------------------------------------------------------- F.18 records and responses
export interface FinanceListResponse<T> {
  items: T[];
}

export interface FinancePlanRecord {
  id: Id;
  version: number;
  template_id: string | null;
  created_at: string;
  updated_at: string;
  plan: FinancePlan;
}

export type FinRunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface FinancePlanSummary {
  id: Id;
  name: string;
  version: number;
  currency: string;
  goal_count: number;
  template_id: string | null;
  updated_at: string;
  latest_run: { id: Id; status: FinRunStatus } | null;
  latest_result: { id: Id; feasibility: FinFeasibility; goals_on_track: number; goals_total: number } | null;
}

export interface FinanceRun {
  id: Id;
  plan_id: Id;
  plan_version_id: Id;
  kind: FinanceResultKind;
  label: string | null;
  status: FinRunStatus;
  request: FinanceRunRequest;
  what_if: WhatIfChanges | null;
  engine_version: string;
  feasibility: FinFeasibility | null;
  result_id: Id | null;
  error: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number | null;
}

export interface FinanceRunCreated {
  run_id: Id;
  status: "queued";
  plan_version_id: Id;
  status_url: string;
  events_url: string;
}

export interface FinanceCancelResponse {
  run_id: Id;
  status: "cancelled" | "running";
  cancel_requested: true;
}

export interface FinanceLimits {
  goals: number;
  incomes: number;
  expenses: number;
  debts: number;
  holdings: number;
  one_offs: number;
  asset_classes: number;
  horizon_months: number;
}

export interface FinanceDefaults {
  plan: FinancePlan;
  disclaimer: string;
  disclaimer_version: string;
  limits: FinanceLimits;
}

export interface FinanceExportFile {
  format: "superplanner.finance_plan";
  format_version: 1;
  exported_at: string;
  plan: FinancePlan;
}

export interface FinancePreviewResponse {
  ok: boolean;
  issues: FinanceIssue[];
  cashflow: CashflowSummary | null;
}

export interface FinanceValidateResponse extends FinancePreviewResponse {
  plan_version: number;
}

export interface WhatIfRequest {
  changes: WhatIfChanges;
  run?: FinanceRunRequest;
  replace_active?: boolean;
  expected_plan_version?: number;
  base_result_id?: Id;
}

export interface SendToPlannerRequest {
  name?: string;
  months?: number;
  utc_offset?: string;
  review_every_months?: number;
  include_rebalances?: boolean;
}

export interface SendToPlannerResponse {
  problem_id: Id;
  record: ProblemRecord;
  task_count: number;
  skipped: number;
  url: string;
}

// ---------------------------------------------------------------- F.19 events
export type FinStage = "preflight" | "cashflow" | "optimize" | "simulate" | "calibrate" | "validate" | "fixes";

interface FinEventBase {
  run_id: Id;
  seq: number;
  ts: string;
  elapsed_seconds: number;
}

export interface FinRunQueuedEvent extends FinEventBase {
  type: "run_queued";
  plan_version_id: Id;
  kind: FinanceResultKind;
}
export interface FinRunStartedEvent extends FinEventBase {
  type: "run_started";
}
export interface FinStageStartedEvent extends FinEventBase {
  type: "stage_started";
  stage: FinStage;
  message: string;
}
export interface FinProgressEvent extends FinEventBase {
  type: "progress";
  stage: FinStage;
  fraction: number;
  message: string;
  detail: Record<string, unknown>;
}
export interface FinStageCompletedEvent extends FinEventBase {
  type: "stage_completed";
  stage: FinStage;
  seconds: number;
}
export interface FinRunCompletedEvent extends FinEventBase {
  type: "run_completed";
  result_id: Id;
  feasibility: FinFeasibility;
  goals_on_track: number;
  goals_total: number;
}
export interface FinRunCancelledEvent extends FinEventBase {
  type: "run_cancelled";
}
export interface FinRunFailedEvent extends FinEventBase {
  type: "run_failed";
  error: string;
}

export type FinRunEvent =
  | FinRunQueuedEvent
  | FinRunStartedEvent
  | FinStageStartedEvent
  | FinProgressEvent
  | FinStageCompletedEvent
  | FinRunCompletedEvent
  | FinRunCancelledEvent
  | FinRunFailedEvent;

export type FinRunEventType = FinRunEvent["type"];

export const FIN_EVENT_TYPES: FinRunEventType[] = [
  "run_queued",
  "run_started",
  "stage_started",
  "progress",
  "stage_completed",
  "run_completed",
  "run_cancelled",
  "run_failed",
];

export const FIN_TERMINAL_EVENTS: FinRunEventType[] = ["run_completed", "run_cancelled", "run_failed"];
export const FIN_ACTIVE_STATUSES: FinRunStatus[] = ["queued", "running"];
export const FIN_STAGES: FinStage[] = ["preflight", "cashflow", "optimize", "simulate", "calibrate", "validate", "fixes"];

/** Reserved ids (F.4) used in results instead of goal ids. */
export const EF_ID = "emergency_fund";
export const CASH_BUFFER_ID = "cash_buffer";
export const UNALLOCATED_ID = "unallocated";

/** Exact F.21 text (also returned by the API in every result and in /finance/defaults). */
export const DISCLAIMER =
  "SuperPlanner Finance is an educational planning tool. It is not investment, tax or legal advice and " +
  "does not recommend specific financial products. Results are estimates based on the assumptions you " +
  "entered; actual returns, inflation and income can differ, and you could end up with less than your " +
  "goals need. Consider consulting a qualified, registered investment adviser before making investment " +
  "decisions.";
export const DISCLAIMER_VERSION = "fin-disclaimer-1";
