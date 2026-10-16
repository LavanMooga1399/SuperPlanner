/**
 * JSON examples of FINANCE.md 14, 18 and 19, typed against `types.ts`.
 * They exist to make `tsc` fail if the TS mirror drifts from the documented contract.
 */
import { exampleProblemRecord } from "../../api/contractExamples";
import {
  DISCLAIMER,
  DISCLAIMER_VERSION,
  type AssetClass,
  type FinanceCancelResponse,
  type FinanceComparison,
  type FinanceDefaults,
  type FinanceExportFile,
  type FinanceListResponse,
  type FinancePlan,
  type FinancePlanRecord,
  type FinancePlanSummary,
  type FinancePreviewResponse,
  type FinanceResult,
  type FinanceResultRecord,
  type FinanceResultSummary,
  type FinanceRun,
  type FinanceRunCreated,
  type FinanceRunRequest,
  type FinanceTemplateInfo,
  type FinanceValidateResponse,
  type FinRunEvent,
  type SendToPlannerRequest,
  type SendToPlannerResponse,
  type WhatIfChanges,
  type WhatIfRequest,
} from "./types";

export const exampleAssetClasses: AssetClass[] = [
  { id: "cash", name: "Cash / savings account", category: "cash", expected_return_pct: 3.0, volatility_pct: 0.5, expense_ratio_pct: 0, tax_drag_pct: 0, liquidity_days: 0, lock_in_months: 0, min_monthly_contribution: 0, description: "" },
  { id: "fixed_deposit", name: "Fixed deposit", category: "debt", expected_return_pct: 6.75, volatility_pct: 1.0, expense_ratio_pct: 0, tax_drag_pct: 0, liquidity_days: 2, lock_in_months: 0, min_monthly_contribution: 0, description: "" },
  { id: "short_debt", name: "Short-term debt fund", category: "debt", expected_return_pct: 7.0, volatility_pct: 2.0, expense_ratio_pct: 0.35, tax_drag_pct: 0, liquidity_days: 2, lock_in_months: 0, min_monthly_contribution: 0, description: "" },
  { id: "govt_long", name: "Government long lock-in savings (PPF-like)", category: "debt", expected_return_pct: 7.1, volatility_pct: 0.5, expense_ratio_pct: 0, tax_drag_pct: 0, liquidity_days: 7, lock_in_months: 180, min_monthly_contribution: 0, description: "" },
  { id: "equity_index", name: "Diversified equity index fund", category: "equity", expected_return_pct: 11.5, volatility_pct: 18.0, expense_ratio_pct: 0.2, tax_drag_pct: 0, liquidity_days: 3, lock_in_months: 0, min_monthly_contribution: 0, description: "" },
  { id: "gold", name: "Gold", category: "gold", expected_return_pct: 8.0, volatility_pct: 15.0, expense_ratio_pct: 0.4, tax_drag_pct: 0, liquidity_days: 3, lock_in_months: 0, min_monthly_contribution: 0, description: "" },
];

export const examplePlan: FinancePlan = {
  id: "fp_1a2b",
  name: "My plan",
  description: "",
  schema_version: 1,
  start_month: "2026-11",
  horizon_end_month: null,
  profile: { currency: "INR", locale: "en-IN", age: 24, retirement_age: 60, risk_tolerance: 4, tax_note: "" },
  incomes: [
    { id: "salary", name: "Salary", kind: "salary", amount: 60000, frequency: "monthly", growth_pct: 8, start_month: null, end_month: null, interruptible: true },
  ],
  expenses: [
    { id: "essentials", name: "Essentials", category: "rent", amount: 25000, frequency: "monthly", essential: true, inflation_linked: true, inflation_pct: null, start_month: null, end_month: null },
  ],
  debts: [{ id: "car_loan", name: "Car loan", kind: "vehicle", balance: 300000, interest_rate_pct: 9, emi: 10000, remaining_months: null }],
  holdings: [{ id: "h_cash", name: "Savings account", asset_class_id: "cash", amount: 50000, locked_until_month: null }],
  one_offs: [{ id: "oo1", name: "Bonus", kind: "inflow", month: "2027-03", amount: 50000, inflation_linked: true }],
  goals: [
    {
      id: "car", name: "Car", kind: "vehicle", target_amount: 800000, target_month: "2030-10", priority: "should",
      flexibility_months: 12, min_success_probability: null, inflation_pct: null, risk_tolerance: null,
      allowed_asset_class_ids: null, earmarked: [], enabled: true,
    },
  ],
  emergency_fund: { months_of_essentials: 6, asset_class_id: "fixed_deposit", build_share: 1 },
  assumptions: {
    inflation_pct: 6,
    inflation_volatility_pct: 1.5,
    cash_class_id: "cash",
    asset_classes: exampleAssetClasses,
    correlations: [{ a: "cash", b: "fixed_deposit", rho: 0.5 }],
    risky_cap_by_tolerance_pct: [20, 40, 60, 75, 90],
    glide_path: [
      { min_months_to_goal: 120, multiplier: 1 },
      { min_months_to_goal: 0, multiplier: 0 },
    ],
    source_note: "Illustrative long-run assumptions, not forecasts. Edit them to match your own view.",
  },
  constraints: { max_equity_pct: null, max_class_pct: {}, min_cash_buffer: 0, contribution_block_months: 12, rebalance_cost_pct: 0.1 },
  metadata: { wizard: { completed_steps: ["profile"] } },
};

export const examplePlanRecord: FinancePlanRecord = {
  id: "fp_1a2b",
  version: 3,
  template_id: "young_professional",
  created_at: "2026-10-16T09:00:00Z",
  updated_at: "2026-10-16T09:10:00Z",
  plan: examplePlan,
};

export const examplePlanSummary: FinancePlanSummary = {
  id: "fp_1a2b", name: "My plan", version: 3, currency: "INR", goal_count: 2, template_id: "young_professional",
  updated_at: "2026-10-16T09:10:00Z",
  latest_run: { id: "frun_9c", status: "completed" },
  latest_result: { id: "fres_77", feasibility: "feasible", goals_on_track: 1, goals_total: 2 },
};

export const exampleRunRequest: FinanceRunRequest = {
  time_limit_seconds: 30, seed: 0,
  simulation: { n_paths: 2000, income_interruption: { enabled: false, annual_probability: 0.05, duration_months: 3 } },
  calibration_rounds: 2, compute_fixes: true, label: null,
};

export const exampleWhatIf: WhatIfChanges = {
  label: null,
  extra_monthly_savings: 10000,
  goal_overrides: [{ goal_id: "car", target_month: "2031-06" }],
  risk_tolerance: null,
  return_shift_pct: 0,
  inflation_pct: null,
  income_drop: null,
  emergency_build_share: null,
};

export const exampleWhatIfRequest: WhatIfRequest = {
  changes: exampleWhatIf, replace_active: true, expected_plan_version: 3, base_result_id: "fres_77",
};

export const exampleResult: FinanceResult = {
  engine_version: "fin-0.1.0", disclaimer: DISCLAIMER, disclaimer_version: DISCLAIMER_VERSION,
  start_month: "2026-11", horizon_months: 408, end_month: "2060-10", currency: "INR",
  feasibility: "feasible", termination_reason: "optimal", optimality_proven: true,
  summary: {
    goals_total: 3, goals_on_track: 2, goals_at_risk: 1, goals_off_track: 0,
    monthly_investable_now: 25000.0, monthly_contribution_now: 21000.0,
    emergency_fund_target: 180000.0, emergency_fund_now: 50000.0,
    emergency_fund_complete_month: "2027-05", liquidity_risk_probability: 0.03,
    total_contributions_real: 9120000.0,
  },
  goals: [{
    goal_id: "car", name: "Car", kind: "vehicle", priority: "should",
    target_month: "2030-10", months_to_goal: 47, target_amount: 800000.0,
    target_real: 800000.0, target_nominal_expected: 1004000.0,
    planned_value_real: 800000.0, projected_central_real: 861000.0,
    shortfall_real: 0.0, shortfall_fraction: 0.0,
    success_probability: 0.74, min_success_probability: 0.7,
    p10_real: 712000.0, p50_real: 852000.0, p90_real: 1010000.0,
    expected_shortfall_real: 21000.0, scenario_low_real: 744000.0, scenario_high_real: 952000.0,
    status: "on_track", contribution_start_month: "2027-06", contribution_end_month: "2030-09",
    monthly_contribution_now: 0.0, total_contributions_real: 452000.0, holdings_used_real: 0.0,
    allocation_now_pct: { equity_index: 35.0, short_debt: 65.0 }, planning_z: 0.52,
  }],
  contributions: [{
    goal_id: "car", asset_class_id: "equity_index", start_month: "2027-06",
    end_month: "2028-10", monthly_amount_real: 3430.0,
    monthly_amount_nominal_start: 3690.0, monthly_amount_nominal_end: 3880.0,
  }],
  holdings_assignment: [{ holding_id: "h1", goal_id: "emergency_fund", amount: 50000.0, source: "initial_ef" }],
  rebalances: [{ month: "2029-11", goal_id: "car", sells: { equity_index: 120000.0 }, buys: { short_debt: 119880.0 } }],
  glide_paths: {
    car: [{ month: "2027-11", months_to_goal: 35, risky_cap_pct: 21.0, risky_share_pct: 21.0, weights_pct: { equity_index: 21.0, short_debt: 79.0 } }],
  },
  series: {
    months: ["2026-11"], corpus_by_class: { equity_index: [0.0] },
    emergency_fund: [50000], cash_buffer: [0], unallocated: [0], goal_withdrawals: [0],
    total_p10: [50000], total_p50: [50000], total_p90: [50000],
  },
  cashflow: {
    months: ["2026-11"], income: [60000], essential: [25000], discretionary: [10000], debt_payments: [0],
    one_off_net: [0], surplus: [25000], emergency_fund_contribution: [25000],
    goal_contribution: [0], cash_buffer_end: [0],
  },
  scenarios: {
    definitions: { low: "returns -0.5 x volatility, inflation +1pp", central: "expected returns", high: "returns +0.5 x volatility, inflation -1pp" },
    goals: { car: { low: 744000.0, central: 861000.0, high: 952000.0 } },
  },
  explanation: {
    summary: ["Plan is valid."],
    goals: {
      car: {
        reasons: [{ code: "ON_TRACK", message: "On track: estimated 88% chance.", months: [], asset_class_ids: [], values: { p: 0.88 } }],
        fixes: [{
          kind: "DELAY_GOAL", goal_id: "car", message: "Buy the car 6 months later.", months: 6, amount: null,
          new_target_month: "2031-04", new_risk_tolerance: null, resulting_shortfall_real: 0,
          resulting_success_probability: 0.8, relative_change: 0.12, smallest: true,
          what_if: { goal_overrides: [{ goal_id: "car", target_month: "2031-04" }] },
        }],
      },
    },
    binding_constraints: [{ code: "EF_BUILD", message: "Emergency fund builds until 2027-05.", months: ["2026-11", "2027-04"], goal_ids: [] }],
    assumptions: ["Inflation 6.0% a year."], limitations: ["No taxes are computed."], replanning_triggers: ["12 months elapsed."],
  },
  violations: [],
  assumptions_used: {
    inflation_pct: 6.0, asset_classes: exampleAssetClasses, glide_path: [], risky_cap_by_tolerance_pct: [20, 40, 60, 75, 90],
    planning_returns_pct: { car: { equity_index: 1.9, short_debt: 0.6 } },
  },
  simulation_settings: { n_paths: 2000, seed: 0, income_interruption: { enabled: false, annual_probability: 0.05, duration_months: 3 } },
  diagnostics: {
    solver: "GLOP", variables: 2140, constraints: 1210,
    tiers: [{ tier: "T0", status: "OPTIMAL", objective: 0.0, seconds: 0.02 }],
    calibration_rounds: 1, simulation_seconds: 0.8, fix_solves: 6, warnings: [],
  },
};

export const exampleResultSummary: FinanceResultSummary = {
  id: "fres_77", plan_id: "fp_1a2b", run_id: "frun_9c", plan_version_id: "fpv_3d", base_plan_version: 3,
  kind: "baseline", label: null, feasibility: "feasible", goals_total: 3, goals_on_track: 2, goals_at_risk: 1,
  goals_off_track: 0, monthly_contribution_now: 21000, created_at: "2026-10-16T09:12:00Z", what_if: null,
};

export const exampleResultRecord: FinanceResultRecord = { ...exampleResultSummary, result: exampleResult, plan: examplePlan };

export const exampleResultList: FinanceListResponse<FinanceResultSummary> = { items: [exampleResultSummary] };

export const exampleComparison: FinanceComparison = {
  a: exampleResultSummary,
  b: { ...exampleResultSummary, id: "fres_78", kind: "what_if", label: "+₹10,000/month", what_if: exampleWhatIf },
  totals: {
    monthly_contribution_now_a: 21000.0, monthly_contribution_now_b: 31000.0, monthly_contribution_now_delta: 10000.0,
    ef_complete_month_a: "2027-05", ef_complete_month_b: "2027-03",
    goals_on_track_a: 2, goals_on_track_b: 3, liquidity_risk_a: 0.03, liquidity_risk_b: 0.02,
  },
  goals: [{
    goal_id: "car", name: "Car", in_a: true, in_b: true,
    target_month_a: "2030-10", target_month_b: "2030-10",
    success_a: 0.62, success_b: 0.81, success_delta: 0.19,
    p50_a: 790000.0, p50_b: 860000.0, p50_delta: 70000.0,
    shortfall_a: 0.0, shortfall_b: 0.0,
    monthly_now_a: 9800.0, monthly_now_b: 12400.0,
    status_a: "at_risk", status_b: "on_track",
  }],
  what_if_b: exampleWhatIf,
};

export const exampleRun: FinanceRun = {
  id: "frun_9c", plan_id: "fp_1a2b", plan_version_id: "fpv_3d", kind: "baseline", label: null,
  status: "completed", request: exampleRunRequest, what_if: null,
  engine_version: "fin-0.1.0", feasibility: "feasible", result_id: "fres_77", error: null,
  cancel_requested: false, created_at: "2026-10-16T09:11:58Z", started_at: "2026-10-16T09:11:58Z",
  finished_at: "2026-10-16T09:12:00Z", elapsed_seconds: 2.4,
};

export const exampleRunCreated: FinanceRunCreated = {
  run_id: "frun_9c", status: "queued", plan_version_id: "fpv_3d",
  status_url: "/api/v1/finance/runs/frun_9c", events_url: "/api/v1/finance/runs/frun_9c/events",
};

export const exampleCancel: FinanceCancelResponse = { run_id: "frun_9c", status: "cancelled", cancel_requested: true };

export const exampleDefaults: FinanceDefaults = {
  plan: examplePlan, disclaimer: DISCLAIMER, disclaimer_version: DISCLAIMER_VERSION,
  limits: { goals: 12, incomes: 20, expenses: 100, debts: 20, holdings: 50, one_offs: 200, asset_classes: 10, horizon_months: 600 },
};

export const exampleTemplates: FinanceListResponse<FinanceTemplateInfo> = {
  items: [{
    id: "young_professional", name: "Young professional", description: "First job, a car and retirement.",
    parameters: [{ name: "take_home", label: "Monthly take-home pay", type: "money", default: 60000, min: 10000, max: 1e7, help: "" }],
  }],
};

export const exampleExport: FinanceExportFile = {
  format: "superplanner.finance_plan", format_version: 1, exported_at: "2026-10-16T09:20:00Z", plan: examplePlan,
};

export const examplePreview: FinancePreviewResponse = {
  ok: true,
  issues: [{ code: "NO_GOALS", severity: "warning", message: "No goals yet.", field: null, item_ids: [] }],
  cashflow: {
    ef_target: 150000, ef_initial: 50000, ef_complete_month: "2027-03", avg_monthly_surplus_first_year: 25000,
    min_monthly_surplus: 25000, negative_surplus_months: [], debts_paid_off: [{ debt_id: "car_loan", month: "2029-08" }],
    years: [{ year: 0, start_month: "2026-11", income: 720000, essential: 300000, discretionary: 120000, debt_payments: 0, one_off_net: 0, surplus: 300000 }],
  },
};

export const exampleValidate: FinanceValidateResponse = { ...examplePreview, plan_version: 3 };

export const exampleSendRequest: SendToPlannerRequest = {
  name: "Money calendar", months: 12, utc_offset: "+05:30", review_every_months: 3, include_rebalances: true,
};

export const exampleSendResponse: SendToPlannerResponse = {
  problem_id: exampleProblemRecord.id, record: exampleProblemRecord, task_count: 14, skipped: 0,
  url: `/plans/${exampleProblemRecord.id}/tasks`,
};

const ev = { run_id: "frun_9c", ts: "2026-10-16T09:11:58Z" };
export const exampleEvents: FinRunEvent[] = [
  { ...ev, seq: 1, type: "run_queued", elapsed_seconds: 0, plan_version_id: "fpv_3d", kind: "baseline" },
  { ...ev, seq: 2, type: "run_started", elapsed_seconds: 0.01 },
  { ...ev, seq: 3, type: "stage_started", elapsed_seconds: 0.02, stage: "optimize", message: "Optimizing contributions" },
  { ...ev, seq: 4, type: "progress", elapsed_seconds: 0.3, stage: "optimize", fraction: 0.4, message: "Tier T2a", detail: { tier: "T2a" } },
  { ...ev, seq: 5, type: "stage_completed", elapsed_seconds: 0.5, stage: "optimize", seconds: 0.48 },
  { ...ev, seq: 6, type: "run_completed", elapsed_seconds: 2.4, result_id: "fres_77", feasibility: "feasible", goals_on_track: 2, goals_total: 3 },
  { ...ev, seq: 7, type: "run_cancelled", elapsed_seconds: 1 },
  { ...ev, seq: 8, type: "run_failed", elapsed_seconds: 1, error: "Server restarted before the run finished." },
];
