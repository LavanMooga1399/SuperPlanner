import type { FinancePlan } from "../api/types";
import type { PreviewState } from "../lib/hooks";

export interface StepProps {
  plan: FinancePlan;
  update(fn: (p: FinancePlan) => FinancePlan): void;
  preview: PreviewState;
  expert: boolean;
}

type ListKey = "incomes" | "expenses" | "debts" | "holdings" | "one_offs" | "goals";

/** Immutable patch of one list item. */
export function patchItem<K extends ListKey>(plan: FinancePlan, key: K, index: number, patch: Partial<FinancePlan[K][number]>): FinancePlan {
  const list = plan[key] as FinancePlan[K][number][];
  return { ...plan, [key]: list.map((it, i) => (i === index ? { ...it, ...patch } : it)) };
}

export function removeItem<K extends ListKey>(plan: FinancePlan, key: K, index: number): FinancePlan {
  const list = plan[key] as FinancePlan[K][number][];
  return { ...plan, [key]: list.filter((_, i) => i !== index) };
}

export function addItem<K extends ListKey>(plan: FinancePlan, key: K, item: FinancePlan[K][number]): FinancePlan {
  const list = plan[key] as FinancePlan[K][number][];
  return { ...plan, [key]: [...list, item] };
}
