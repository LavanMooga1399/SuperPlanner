/** Next free id per list (FINANCE.md 20.2). Ids are unique across every list of the plan (DUPLICATE_ID). */
import type { FinancePlan } from "../api/types";

export type IdPrefix = "inc" | "exp" | "debt" | "h" | "goal" | "oo";

export function allIds(plan: FinancePlan): Set<string> {
  const s = new Set<string>();
  for (const list of [plan.incomes, plan.expenses, plan.debts, plan.holdings, plan.one_offs, plan.goals]) {
    for (const it of list) s.add(it.id);
  }
  return s;
}

export function nextId(plan: FinancePlan, prefix: IdPrefix, taken: Set<string> = allIds(plan)): string {
  for (let i = 1; ; i++) {
    const id = `${prefix}${i}`;
    if (!taken.has(id)) return id;
  }
}

/** Ids reserved by the engine (F.4) and the what-if prefix that stored documents may never contain [R12]. */
export const RESERVED_IDS = ["emergency_fund", "cash_buffer", "unallocated"];
export const WHATIF_PREFIX = "whatif_";
