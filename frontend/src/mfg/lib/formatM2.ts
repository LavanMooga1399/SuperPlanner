/** Labels and number formatting for the M2 screens (plain words; codes only where planners use them). */
import type { DemandType, PostingType, Role } from "../api/typesM2";
import { fmtQty } from "./format";
import { t as tr } from "../../lib/i18n";
import { LOCALE } from "../../lib/locale";

export const POSTING_LABEL: Record<PostingType, string> = {
  receipt_misc: tr("mfg.formatM2.str.receiptNoOrder"),
  issue_misc: tr("mfg.formatM2.str.issueScrapReturnSample"),
  adjust: tr("mfg.formatM2.str.adjustment"),
  count: tr("mfg.formatM2.str.stockCount"),
  transfer: tr("mfg.formatM2.str.transfer"),
  po_receipt: tr("mfg.formatM2.str.goodsReceiptPurchaseOrder"),
  wo_issue: tr("mfg.formatM2.str.issueToWorkOrder"),
  wo_return: tr("mfg.formatM2.str.returnFromWorkOrder"),
  wo_receipt: tr("mfg.formatM2.str.workOrderOutput"),
  ship: tr("mfg.formatM2.str.shipment"),
};

export const DEMAND_TYPE_LABEL: Record<DemandType, string> = {
  customer: tr("mfg.formatM2.str.customerOrder"),
  internal: tr("mfg.formatM2.str.internal"),
  spares: tr("mfg.formatM2.str.spares"),
  project: tr("mfg.formatM2.str.projectPrototype"),
};

export const ROLE_OPTIONS: { value: Role; label: string }[] = [
  { value: "planner", label: tr("mfg.formatM2.str.planner") },
  { value: "purchaser", label: tr("mfg.formatM2.str.purchaser") },
  { value: "store_keeper", label: tr("mfg.formatM2.str.storeKeeper") },
  { value: "approver", label: tr("mfg.formatM2.str.approver") },
  { value: "viewer", label: tr("mfg.formatM2.str.viewer") },
  { value: "qa_inspector", label: tr("qa.roles.str.qaInspector") },
  { value: "qa_engineer", label: tr("qa.roles.str.qaEngineer") },
  { value: "qa_approver", label: tr("qa.roles.str.qaApprover") },
  { value: "metrology", label: tr("qa.roles.str.metrology") },
];

/** Quantity with the unit, e.g. "30 EA". */
export function qtyUom(q: number | null | undefined, uom?: string): string {
  const t = fmtQty(q);
  return t && uom ? `${t} ${uom}` : t;
}

/** Thousands separators for counts and large quantities. */
export function fmtNum(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "";
  return (Math.round(x * 1e6) / 1e6).toLocaleString(LOCALE, { maximumFractionDigits: 6 });
}

export function fmtMoney(x: number | null | undefined, currency?: string): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "";
  const t = x.toLocaleString(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
