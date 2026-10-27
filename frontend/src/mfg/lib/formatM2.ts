/** Labels and number formatting for the M2 screens (plain words; codes only where planners use them). */
import type { DemandType, PostingType, Role } from "../api/typesM2";
import { fmtQty } from "./format";

export const POSTING_LABEL: Record<PostingType, string> = {
  receipt_misc: "Receipt (no order)",
  issue_misc: "Issue (scrap, return, sample)",
  adjust: "Adjustment",
  count: "Stock count",
  transfer: "Transfer",
  po_receipt: "Goods receipt (purchase order)",
  wo_issue: "Issue to work order",
  wo_return: "Return from work order",
  wo_receipt: "Work order output",
  ship: "Shipment",
};

export const DEMAND_TYPE_LABEL: Record<DemandType, string> = {
  customer: "Customer order",
  internal: "Internal",
  spares: "Spares",
  project: "Project / prototype",
};

export const ROLE_OPTIONS: { value: Role; label: string }[] = [
  { value: "planner", label: "Planner" },
  { value: "purchaser", label: "Purchaser" },
  { value: "store_keeper", label: "Store keeper" },
  { value: "approver", label: "Approver" },
  { value: "viewer", label: "Viewer" },
];

/** Quantity with the unit, e.g. "30 EA". */
export function qtyUom(q: number | null | undefined, uom?: string): string {
  const t = fmtQty(q);
  return t && uom ? `${t} ${uom}` : t;
}

/** Thousands separators for counts and large quantities. */
export function fmtNum(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "";
  return (Math.round(x * 1e6) / 1e6).toLocaleString(undefined, { maximumFractionDigits: 6 });
}

export function fmtMoney(x: number | null | undefined, currency?: string): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "";
  const t = x.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${t} ${currency}` : t;
}

/** "121-135" serial range text. */
export function serialText(from: number | null | undefined, to: number | null | undefined): string {
  if (from === null || from === undefined) return "";
  return to === null || to === undefined || to === from ? String(from) : `${from}-${to}`;
}

export function segmentText(seg: [number, number] | null | undefined): string {
  return seg ? `units ${serialText(seg[0], seg[1])}` : "";
}

/** Days between two ISO dates (b - a). */
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);
}
