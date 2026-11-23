/** Plain-language names for MRP codes (M2 8.12); codes stay visible for support but are never the only text. */
import type { LeadTimeInfo, LimitingReason, RequirementKind, SupplyKind } from "../api/typesM2";
import { t } from "../../lib/i18n";

export const EXCEPTION_LABEL: Record<string, string> = {
  MRP_DEMAND_LATE: t("mfg.mrpText.str.demandWillBeLate"),
  MRP_DEMAND_PAST_DUE: t("mfg.mrpText.str.demandAlreadyPastDue"),
  MRP_SHORTAGE: t("mfg.mrpText.str.partShort"),
  MRP_START_IN_PAST: t("mfg.mrpText.str.shouldHaveStartedAlready"),
  MRP_EXPEDITE: t("mfg.mrpText.str.expediteBringForward"),
  MRP_PAST_DUE_SUPPLY: t("mfg.mrpText.str.deliveryOverdue"),
  MRP_WO_LATE: t("mfg.mrpText.str.workOrderWillBeLate"),
  MRP_EXPIRED_STOCK: t("mfg.mrpText.str.expiredStock"),
  MRP_EXPIRING_STOCK: t("mfg.mrpText.str.stockExpiringUnused"),
  MRP_CANCEL: t("mfg.mrpText.str.notNeededCancel"),
  MRP_REDUCE: t("mfg.mrpText.str.reduceQuantity"),
  MRP_DEFER: t("mfg.mrpText.str.pushOutDefer"),
  MRP_RELEASE_NOW: t("mfg.mrpText.str.releaseNow"),
  MRP_BELOW_SAFETY_STOCK: t("mfg.mrpText.str.belowSafetyStock"),
  MRP_ALTERNATE_USED: t("mfg.mrpText.str.alternatePartUsed"),
  MRP_NO_SUPPLIER: t("mfg.mrpText.str.noSupplier"),
  MRP_MERGE_INTO_PR: t("mfg.mrpText.str.addToAnExistingRequest"),
  MRP_DEMAND_SERIAL_OVERLAP: t("mfg.mrpText.str.serialRangesOverlap"),
  MRP_RESERVATION_EXCESS: t("mfg.mrpText.str.reservedMoreThanNeeded"),
  MRP_WO_COMPONENT_CYCLE: t("mfg.mrpText.str.componentLoop"),
  MRP_DEMAND_OUTSIDE_HORIZON: t("mfg.mrpText.str.demandBeyondTheHorizon"),
  APS_ORDER_LATE: t("mfg.mrpText.str.orderLate"),
  APS_MATERIAL_MISSING: t("mfg.mrpText.str.materialMissing"),
  APS_BEYOND_HORIZON: t("mfg.mrpText.str.beyondTheHorizon"),
  APS_OVERTIME_SUGGESTED: t("mfg.mrpText.str.overtimeSuggested"),
  APS_OVERTIME_LIMIT: t("mfg.mrpText.str.weeklyOvertimeLimitReached"),
  APS_NO_CREW: t("mfg.mrpText.str.waitedForOperators"),
  APS_PAST_OP_NOT_DONE: t("mfg.mrpText.str.pastOperationNotMarkedDone"),
  APS_FROZEN_DROPPED: t("mfg.mrpText.str.frozenOperationDropped"),
  APS_SPLIT: t("mfg.mrpText.str.operationSplit"),
  APS_BUDGET_CUT: t("mfg.mrpText.str.improvementTimeCutShort"),
};

export const exceptionLabel = (code: string) => EXCEPTION_LABEL[code] ?? code.replace(/^MRP_/, "").replace(/_/g, " ").toLowerCase();

export const LIMITING_REASON: Record<LimitingReason, string> = {
  lead_time: t("mfg.mrpText.str.leadTime"),
  start_in_past: t("mfg.mrpText.str.shouldHaveStarted"),
  supply_date: t("mfg.mrpText.str.supplyDate"),
  component: t("mfg.mrpText.str.waitsForParts"),
};

export const REQUIREMENT_KIND: Record<RequirementKind, string> = {
  demand: t("mfg.mrpText.str.demand"),
  extra_demand: t("mfg.mrpText.str.whatIfDemand"),
  safety_stock: t("mfg.mrpText.str.safetyStock"),
  planned_component: t("mfg.mrpText.str.forPlannedOrder"),
  wo_component: t("mfg.mrpText.str.forWorkOrder"),
};

export const SUPPLY_KIND: Record<SupplyKind, string> = {
  stock: t("mfg.mrpText.str.onHand"),
  inspection: t("mfg.mrpText.str.inInspection"),
  po: t("mfg.mrpText.str.purchaseOrder"),
  pr: t("mfg.mrpText.str.purchaseRequest"),
  wo: t("mfg.mrpText.str.workOrder"),
  planned: t("mfg.mrpText.str.plannedOrder"),
};

const LT_SOURCE: Record<LeadTimeInfo["source"], string> = {
  override: t("mfg.mrpText.str.whatIfOverride"),
  item_supplier: t("mfg.mrpText.str.supplierTermsOfThePart"),
  supplier: t("mfg.mrpText.str.supplierDefault"),
  item: "item",
  routing: t("mfg.mrpText.str.fromTheRouting"),
  fixed: t("mfg.mrpText.str.fixedOnTheItem"),
};

export function leadTimeText(lt: LeadTimeInfo): string {
  return t("mfg.mrpText.tpl.days", { days: lt.days, v: lt.unit === "working" ? "working" : "calendar", v2: LT_SOURCE[lt.source] ?? lt.source });
}
