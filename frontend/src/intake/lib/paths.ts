/** Plain labels for provenance paths ("/tasks/t1/duration" -> "Gather requirements: duration"). */
import type { AnyDraft } from "../api/types";

const FIELD_WORDS: Record<string, string> = {
  name: "name",
  duration: "duration",
  after: "comes after",
  resources: "who does it",
  deadline: "deadline",
  deadline_hard: "deadline must be met",
  earliest_start: "not before",
  milestone: "milestone",
  priority: "priority",
  group: "group",
  start_date: "start date",
  working_time: "working time",
  count: "how many",
  amount: "amount",
  frequency: "how often",
  essential: "essential",
  balance: "balance",
  emi: "monthly instalment",
  interest_rate_pct: "interest rate",
  remaining_months: "months left",
  asset_class_id: "held in",
  target: "target amount",
  target_month: "target date",
  age: "your age",
  retirement_age: "retirement age",
  risk_tolerance: "risk level",
  emergency_fund_months: "emergency fund",
  start_month: "start month",
  growth_pct: "yearly raise",
  inflation_linked: "rises with inflation",
  inflation_pct: "yearly price rise",
  kind: "type",
  category: "category",
};

export function pathLabel(draft: AnyDraft | null | undefined, path: string): string {
  const parts = path.split("/").filter(Boolean);
  const field = parts[parts.length - 1] ?? path;
  const word = FIELD_WORDS[field] ?? field.replace(/_/g, " ");
  if (parts.length >= 3 && draft) {
    const list = (draft as unknown as Record<string, unknown>)[parts[0]];
    if (Array.isArray(list)) {
      const item = list.find((x) => (x as { key?: string }).key === parts[1]) as { name?: string } | undefined;
      if (item?.name) return `${item.name}: ${word}`;
    }
  }
  return word[0] ? word[0].toUpperCase() + word.slice(1) : word;
}
