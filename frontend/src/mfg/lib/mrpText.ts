/** Plain-language names for MRP codes (M2 8.12); codes stay visible for support but are never the only text. */
import type { LeadTimeInfo, LimitingReason, RequirementKind, SupplyKind } from "../api/typesM2";

export const EXCEPTION_LABEL: Record<string, string> = {
  MRP_DEMAND_LATE: "Demand will be late",
  MRP_DEMAND_PAST_DUE: "Demand already past due",
  MRP_SHORTAGE: "Part short",
  MRP_START_IN_PAST: "Should have started already",
  MRP_EXPEDITE: "Expedite (bring forward)",
  MRP_PAST_DUE_SUPPLY: "Delivery overdue",
  MRP_WO_LATE: "Work order will be late",
  MRP_EXPIRED_STOCK: "Expired stock",
  MRP_EXPIRING_STOCK: "Stock expiring unused",
  MRP_CANCEL: "Not needed: cancel",
  MRP_REDUCE: "Reduce quantity",
  MRP_DEFER: "Push out (defer)",
  MRP_RELEASE_NOW: "Release now",
  MRP_BELOW_SAFETY_STOCK: "Below safety stock",
  MRP_ALTERNATE_USED: "Alternate part used",
  MRP_NO_SUPPLIER: "No supplier",
  MRP_MERGE_INTO_PR: "Add to an existing request",
  MRP_DEMAND_SERIAL_OVERLAP: "Serial ranges overlap",
  MRP_RESERVATION_EXCESS: "Reserved more than needed",
  MRP_WO_COMPONENT_CYCLE: "Component loop",
  MRP_DEMAND_OUTSIDE_HORIZON: "Demand beyond the horizon",
};

export const exceptionLabel = (code: string) => EXCEPTION_LABEL[code] ?? code.replace(/^MRP_/, "").replace(/_/g, " ").toLowerCase();

export const LIMITING_REASON: Record<LimitingReason, string> = {
  lead_time: "lead time",
  start_in_past: "should have started",
  supply_date: "supply date",
  component: "waits for parts",
};

export const REQUIREMENT_KIND: Record<RequirementKind, string> = {
  demand: "Demand",
  extra_demand: "What-if demand",
  safety_stock: "Safety stock",
  planned_component: "For planned order",
  wo_component: "For work order",
};

export const SUPPLY_KIND: Record<SupplyKind, string> = {
  stock: "On hand",
  inspection: "In inspection",
  po: "Purchase order",
  pr: "Purchase request",
  wo: "Work order",
  planned: "Planned order",
};

const LT_SOURCE: Record<LeadTimeInfo["source"], string> = {
  override: "what-if override",
  item_supplier: "supplier terms of the part",
  supplier: "supplier default",
  item: "item",
  routing: "from the routing",
  fixed: "fixed on the item",
};

export function leadTimeText(lt: LeadTimeInfo): string {
  return `${lt.days} ${lt.unit === "working" ? "working" : "calendar"} days (${LT_SOURCE[lt.source] ?? lt.source})`;
}
