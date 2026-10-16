/** Derived view helpers over a FinanceResult (names, colors, money basis). */
import type { AssetClass, FinanceResult } from "../api/types";
import { CASH_BUFFER_ID, EF_ID, UNALLOCATED_ID } from "../api/types";
import { paletteColor } from "../charts/scales";

export interface ClassInfo {
  id: string;
  name: string;
  color: string;
  cls: AssetClass | null;
}

export function classInfos(result: FinanceResult): Map<string, ClassInfo> {
  const m = new Map<string, ClassInfo>();
  result.assumptions_used.asset_classes.forEach((c, i) => m.set(c.id, { id: c.id, name: c.name, color: paletteColor(i % 5), cls: c }));
  return m;
}

export const className = (infos: Map<string, ClassInfo>, id: string) => infos.get(id)?.name ?? id;

export function goalLabel(result: FinanceResult, id: string): string {
  if (id === EF_ID) return "Emergency fund";
  if (id === CASH_BUFFER_ID) return "Cash buffer";
  if (id === UNALLOCATED_ID) return "Not assigned to a goal";
  return result.goals.find((g) => g.goal_id === id)?.name ?? id;
}

/** Price index P_t = (1 + pi)^(t/12) (FINANCE.md 3): real -> expected nominal. */
export function priceIndex(inflationPct: number, t: number): number {
  return Math.pow(1 + inflationPct / 100, t / 12);
}

/** Annual real return after costs and inflation, in % (FINANCE.md 3). */
export function realReturnPct(c: Pick<AssetClass, "expected_return_pct" | "expense_ratio_pct" | "tax_drag_pct">, inflationPct: number): number {
  const r = (1 + c.expected_return_pct / 100 - c.expense_ratio_pct / 100 - c.tax_drag_pct / 100) / (1 + inflationPct / 100) - 1;
  return r * 100;
}
