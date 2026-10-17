import { instantiateFinanceTemplate } from "../api/client";
import type { FinancePlanRecord } from "../api/types";
import { currentUtcMonth } from "./months";

/** The "Start from scratch" flow: a blank financial plan, opened at the first wizard step by the caller. */
export function startBlankFinancePlan(): Promise<FinancePlanRecord> {
  return instantiateFinanceTemplate("blank", { name: "My financial plan", start_month: currentUtcMonth() });
}
