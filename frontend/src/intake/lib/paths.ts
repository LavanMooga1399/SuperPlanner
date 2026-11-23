/** Plain labels for provenance paths ("/tasks/t1/duration" -> "Gather requirements: duration"). */
import type { AnyDraft } from "../api/types";
import { t } from "../../lib/i18n";

const FIELD_WORDS: Record<string, string> = {
  name: "name",
  duration: "duration",
  after: t("studio.paths.str.comesAfter"),
  resources: t("studio.paths.str.whoDoesIt"),
  deadline: "deadline",
  deadline_hard: t("studio.paths.str.deadlineMustBeMet"),
  earliest_start: t("studio.paths.str.notBefore"),
  milestone: "milestone",
  priority: "priority",
  group: "group",
  start_date: t("studio.paths.str.startDate"),
  working_time: t("studio.paths.str.workingTime"),
  count: t("studio.paths.str.howMany"),
  amount: "amount",
  frequency: t("studio.paths.str.howOften"),
  essential: "essential",
  balance: "balance",
  emi: t("studio.paths.str.monthlyInstalment"),
  interest_rate_pct: t("studio.paths.str.interestRate"),
  remaining_months: t("studio.paths.str.monthsLeft"),
  asset_class_id: t("studio.paths.str.heldIn"),
  target: "target amount",
  target_month: t("studio.paths.str.targetDate"),
  age: t("studio.paths.str.yourAge"),
  retirement_age: t("studio.paths.str.retirementAge"),
  risk_tolerance: t("studio.paths.str.riskLevel"),
  emergency_fund_months: t("studio.paths.str.emergencyFund"),
  start_month: t("studio.paths.str.startMonth"),
  growth_pct: t("studio.paths.str.yearlyRaise"),
  inflation_linked: t("studio.paths.str.risesWithInflation"),
  inflation_pct: t("studio.paths.str.yearlyPriceRise"),
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
