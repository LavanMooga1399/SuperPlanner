import { instantiateFinanceTemplate } from "../api/client";
import type { FinancePlanRecord } from "../api/types";
import { currentUtcMonth } from "./months";
import { t } from "../../lib/i18n";

/** The "Start from scratch" flow: a blank financial plan, opened at the first wizard step by the caller. */
export function startBlankFinancePlan(): Promise<FinancePlanRecord> {
  return instantiateFinanceTemplate("blank", { name: t("finance.startBlank.str.myFinancialPlan"), start_month: currentUtcMonth() });
}
