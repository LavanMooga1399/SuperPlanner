/**
 * Route builders for the Manufacturing area's own navigation (M 11.1). Health "Fix" links never use these:
 * they come from the server (`issue.link`, M 11.3), so the UI never derives a link for a health entity itself.
 */
import { queryString } from "../api/client";

const enc = encodeURIComponent;

export const MFG = "/mfg";

export const mfgPaths = {
  home: () => MFG,
  items: () => `${MFG}/items`,
  item: (itemId: string) => `${MFG}/items/${enc(itemId)}`,
  itemBom: (itemId: string, q?: { bom?: string; line?: string; on?: string; serial?: string; qty?: string }) =>
    `${MFG}/items/${enc(itemId)}/bom${queryString(q)}`,
  bomEdit: (itemId: string, bomId: string, line?: string) =>
    `${MFG}/items/${enc(itemId)}/bom/${enc(bomId)}/edit${queryString({ line })}`,
  whereUsed: (itemId: string) => `${MFG}/items/${enc(itemId)}/where-used`,
  routing: (itemId: string, q?: { routing?: string; op?: string | number }) =>
    `${MFG}/items/${enc(itemId)}/routing${queryString(q)}`,
  plant: () => `${MFG}/plant`,
  groups: (q?: { group?: string; line?: string }) => `${MFG}/plant/groups${queryString(q)}`,
  shifts: (q?: { template?: string; assignment?: string }) =>
    `${MFG}/plant/shifts${queryString(q)}`,
  calendar: (q?: { line?: string; exception?: string }) =>
    `${MFG}/plant/calendar${queryString(q)}`,
  settings: () => `${MFG}/plant/settings`,
  resources: () => `${MFG}/resources`,
  skills: (skill?: string) => `${MFG}/resources/skills${queryString({ skill })}`,
  operators: (operator?: string) => `${MFG}/resources/operators${queryString({ operator })}`,
  tooling: (tool?: string) => `${MFG}/resources/tooling${queryString({ tool })}`,
  health: () => `${MFG}/health`,
  importStart: (reuse?: string) => `${MFG}/import${queryString({ reuse })}`,
  importStep: (importId: string, step?: "map" | "preview" | "done") =>
    `${MFG}/import/${enc(importId)}${queryString({ step })}`,

  // ---------------------------------------------------------------- M2 (14.2)
  itemStock: (itemId: string) => `${MFG}/items/${enc(itemId)}/stock`,
  itemSuppliers: (itemId: string) => `${MFG}/items/${enc(itemId)}/suppliers`,
  inventory: (q?: { item?: string; location?: string }) => `${MFG}/inventory${queryString(q)}`,
  transactions: (q?: { item?: string; posting?: string }) => `${MFG}/inventory/transactions${queryString(q)}`,
  posting: (postingId: string) => `${MFG}/inventory/postings/${enc(postingId)}`,
  post: (q?: { type?: string; item?: string; location?: string }) => `${MFG}/inventory/post${queryString(q)}`,
  lots: (lot?: string) => `${MFG}/inventory/lots${queryString({ lot })}`,
  locations: (location?: string) => `${MFG}/inventory/locations${queryString({ location })}`,
  purchasing: () => `${MFG}/purchasing`,
  purchaseDocs: (t: "po" | "pr") => `${MFG}/purchasing/${t === "po" ? "orders" : "requests"}`,
  purchaseDoc: (t: "po" | "pr", docId: string, q?: { line?: string; schedule?: string }) =>
    `${MFG}/purchasing/${t === "po" ? "orders" : "requests"}/${enc(docId)}${queryString(q)}`,
  purchaseDocNew: (t: "po" | "pr") => `${MFG}/purchasing/${t === "po" ? "orders" : "requests"}/new`,
  deliveryBoard: (q?: { overdue?: string; supplier?: string }) => `${MFG}/purchasing/schedule${queryString(q)}`,
  suppliers: () => `${MFG}/purchasing/suppliers`,
  supplier: (supplierId: string, itemSupplier?: string) =>
    `${MFG}/purchasing/suppliers/${enc(supplierId)}${queryString({ item_supplier: itemSupplier })}`,
  demand: () => `${MFG}/demand`,
  demandOrder: (orderId: string, line?: string) => `${MFG}/demand/${enc(orderId)}${queryString({ line })}`,
  demandNew: () => `${MFG}/demand/new`,
  workOrders: () => `${MFG}/work-orders`,
  workOrder: (woId: string, component?: string) => `${MFG}/work-orders/${enc(woId)}${queryString({ component })}`,
  workOrderNew: () => `${MFG}/work-orders/new`,
  kitting: () => `${MFG}/work-orders/kitting`,
  mrp: () => `${MFG}/mrp`,
  run: (runId: string) => `${MFG}/mrp/runs/${enc(runId)}`,
  runItems: (runId: string) => `${MFG}/mrp/runs/${enc(runId)}/items`,
  runItem: (runId: string, itemId: string) => `${MFG}/mrp/runs/${enc(runId)}/items/${enc(itemId)}`,
  runPlanned: (runId: string, order?: string) => `${MFG}/mrp/runs/${enc(runId)}/planned${queryString({ order })}`,
  runExceptions: (runId: string, q?: { code?: string; severity?: string }) =>
    `${MFG}/mrp/runs/${enc(runId)}/exceptions${queryString(q)}`,
  runDemand: (runId: string, line?: string) => `${MFG}/mrp/runs/${enc(runId)}/demand${queryString({ line })}`,
  runPegging: (runId: string, q: { item: string; node: number; kind: "requirement" | "supply"; direction: "up" | "down" }) =>
    `${MFG}/mrp/runs/${enc(runId)}/pegging${queryString(q)}`,
  runCompare: (runId: string, withId?: string) => `${MFG}/mrp/runs/${enc(runId)}/compare${queryString({ with: withId })}`,
  shortages: () => `${MFG}/shortages`,
  members: () => `${MFG}/settings/members`,

  // ---------------------------------------------------------------- M3 (12)
  schedule: () => `${MFG}/schedule`,
  apsRun: (runId: string) => `${MFG}/schedule/runs/${enc(runId)}`,
  apsGantt: (runId: string, q?: { view?: string; group?: string; line?: string; order?: string; from?: string; to?: string; op?: string | number }) =>
    `${MFG}/schedule/runs/${enc(runId)}/gantt${queryString(q)}`,
  apsLoad: (runId: string) => `${MFG}/schedule/runs/${enc(runId)}/load`,
  apsDispatch: (runId: string, q?: { line?: string; date?: string; shift?: string }) => `${MFG}/schedule/runs/${enc(runId)}/dispatch${queryString(q)}`,
  apsOrders: (runId: string) => `${MFG}/schedule/runs/${enc(runId)}/orders`,
  apsDemand: (runId: string) => `${MFG}/schedule/runs/${enc(runId)}/demand`,
  apsOvertime: (runId: string) => `${MFG}/schedule/runs/${enc(runId)}/overtime`,
  apsExceptions: (runId: string, q?: { code?: string; severity?: string }) => `${MFG}/schedule/runs/${enc(runId)}/exceptions${queryString(q)}`,
  apsCompare: (runId: string, withId?: string) => `${MFG}/schedule/runs/${enc(runId)}/compare${queryString({ with: withId })}`,
  setups: () => `${MFG}/plant/setups`,
};

/** M 11.1 `isMfgPath`. */
export function isMfgPath(pathname: string): boolean {
  return /^\/mfg(\/|$)/.test(pathname);
}
