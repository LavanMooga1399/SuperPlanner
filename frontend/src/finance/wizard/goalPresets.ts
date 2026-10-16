import type { FinancePlan, Goal, GoalKind, Priority } from "../api/types";
import { nextId } from "../lib/ids";
import { addMonths, currentUtcMonth } from "../lib/months";

export interface GoalPreset {
  key: string;
  label: string;
  description: string;
  kind: GoalKind;
  priority: Priority;
  years: number;
  amount: number;
  inflation_pct: number | null;
  flexibility_months: number;
}

const FREQ_Q = { monthly: 1, quarterly: 1 / 3, half_yearly: 1 / 6, yearly: 1 / 12, once: 0 } as const;

/** 25 x annual (essential + discretionary) expenses at plan start (FINANCE.md 15). */
export function retirementTarget(plan: FinancePlan): number {
  const monthly = plan.expenses.reduce((a, e) => a + e.amount * FREQ_Q[e.frequency], 0);
  const v = Math.round(25 * 12 * monthly);
  return v > 0 ? v : 9000000;
}

export function presets(plan: FinancePlan): GoalPreset[] {
  const age = plan.profile.age;
  const retireYears = age !== null ? Math.max(1, plan.profile.retirement_age - age) : 25;
  return [
    { key: "retirement", label: "Retirement", description: "A corpus for when you stop working", kind: "retirement", priority: "must", years: retireYears, amount: retirementTarget(plan), inflation_pct: null, flexibility_months: 0 },
    { key: "education", label: "Child education", description: "Education costs often rise faster (9% a year)", kind: "education", priority: "must", years: 15, amount: 2500000, inflation_pct: 9, flexibility_months: 0 },
    { key: "home", label: "Home down payment", description: "The part of a home price you pay upfront", kind: "home", priority: "must", years: 5, amount: 1500000, inflation_pct: null, flexibility_months: 6 },
    { key: "vehicle", label: "Car", description: "A vehicle bought without a loan", kind: "vehicle", priority: "should", years: 4, amount: 800000, inflation_pct: null, flexibility_months: 12 },
    { key: "travel", label: "Travel", description: "A big trip", kind: "travel", priority: "nice", years: 2, amount: 300000, inflation_pct: null, flexibility_months: 12 },
    { key: "wedding", label: "Wedding", description: "Wedding costs for you or family", kind: "wedding", priority: "should", years: 3, amount: 1000000, inflation_pct: null, flexibility_months: 12 },
    { key: "other", label: "Other goal", description: "Anything else you want to fund", kind: "other", priority: "should", years: 5, amount: 500000, inflation_pct: null, flexibility_months: 0 },
  ];
}

export function goalFromPreset(plan: FinancePlan, p: GoalPreset): Goal {
  const start = plan.start_month ?? currentUtcMonth();
  const sameKind = plan.goals.filter((g) => g.kind === p.kind).length;
  return {
    id: nextId(plan, "goal"),
    name: sameKind ? `${p.label} ${sameKind + 1}` : p.label,
    kind: p.kind,
    target_amount: p.amount,
    target_month: addMonths(start, Math.max(1, Math.round(p.years * 12))),
    priority: p.priority,
    flexibility_months: p.flexibility_months,
    min_success_probability: null,
    inflation_pct: p.inflation_pct,
    risk_tolerance: null,
    allowed_asset_class_ids: null,
    earmarked: [],
    enabled: true,
  };
}
