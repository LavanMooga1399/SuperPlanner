import type { FinanceIssue } from "../api/types";

export type StepKey = "profile" | "income" | "debts" | "savings" | "goals" | "assumptions" | "review";

export const STEPS: { key: StepKey; label: string }[] = [
  { key: "profile", label: "Profile" },
  { key: "income", label: "Income & expenses" },
  { key: "debts", label: "Debts" },
  { key: "savings", label: "Savings & holdings" },
  { key: "goals", label: "Goals" },
  { key: "assumptions", label: "Risk & assumptions" },
  { key: "review", label: "Review" },
];

export const isStep = (s: string | undefined): s is StepKey => STEPS.some((x) => x.key === s);

const CODE_STEP: Record<string, StepKey> = {
  GOAL_TOO_SOON: "goals",
  NO_GOALS: "goals",
  GOAL_TARGET_HUGE: "goals",
  NO_ALLOWED_CLASS: "goals",
  UNKNOWN_HOLDING: "goals",
  EARMARK_EXCEEDS_HOLDING: "goals",
  EARMARK_LOCKED_PAST_GOAL: "goals",
  TOO_LARGE: "goals",
  NO_INCOME: "income",
  NEGATIVE_SURPLUS: "income",
  END_BEFORE_START: "income",
  ONE_OFF_IN_PAST: "income",
  DEBT_NEVER_REPAID: "debts",
  DEBT_TERM_MISMATCH: "debts",
  HIGH_INTEREST_DEBT: "debts",
  HORIZON_TOO_LONG: "profile",
  HORIZON_BEFORE_GOAL: "profile",
  EF_CLASS_NOT_LIQUID: "savings",
  CASH_CLASS_INVALID: "assumptions",
  CORRELATION_NOT_PSD: "assumptions",
  UNKNOWN_ASSET_CLASS: "assumptions",
};

/** The wizard step where an issue can be fixed (by `field` JSON path first, then by code). */
export function stepOfIssue(issue: Pick<FinanceIssue, "code" | "field">): StepKey {
  const f = issue.field ?? "";
  const root = f.split(/[.[]/)[0];
  switch (root) {
    case "start_month":
    case "horizon_end_month":
    case "profile":
    case "name":
      return "profile";
    case "incomes":
    case "expenses":
    case "one_offs":
      return "income";
    case "debts":
      return "debts";
    case "holdings":
    case "emergency_fund":
      return "savings";
    case "goals":
      return "goals";
    case "assumptions":
    case "constraints":
      return "assumptions";
    default:
      return CODE_STEP[issue.code] ?? "review";
  }
}
