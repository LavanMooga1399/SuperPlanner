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

  // ---------------------------------------------------------------- M4 (12)
  floor: () => `${MFG}/floor`,
  floorLine: (lineId: string, q?: { shift?: string; date?: string }) => `${MFG}/floor/lines/${enc(lineId)}${queryString(q)}`,
  floorOp: (woOpId: string) => `${MFG}/floor/ops/${enc(woOpId)}`,
  floorWo: (woId: string) => `${MFG}/floor/wo/${enc(woId)}`,
  floorDowntime: (lineId: string) => `${MFG}/floor/lines/${enc(lineId)}/downtime`,
  floorBatch: (lineId: string) => `${MFG}/floor/lines/${enc(lineId)}/batch`,
  floorOverview: () => `${MFG}/floor/overview`,
  floorEvents: (q?: { wo?: string; line?: string; op?: string }) => `${MFG}/floor/events${queryString(q)}`,
  replan: () => `${MFG}/replan`,
  kpis: () => `${MFG}/kpis`,
  serials: () => `${MFG}/serials`,
  serial: (id: string) => `${MFG}/serials/${enc(id)}`,
  simulations: () => `${MFG}/schedule/simulations`,
  simulation: (id: string) => `${MFG}/schedule/simulations/${enc(id)}`,
  printTraveller: (woId: string) => `${MFG}/print/traveller/${enc(woId)}`,
  // ---------------------------------------------------------------- M5
  integration: (tab?: string) => `${MFG}/integration${tab ? `/${tab}` : ""}`,
  integrationBatch: (id: string) => `${MFG}/integration/batches/${enc(id)}`,
  integrationRecon: (id: string) => `${MFG}/integration/reconciliation/${enc(id)}`,
  trace: (q?: { kind?: string; id?: string; dir?: string; label?: string }) => `${MFG}/trace${queryString(q)}`,
  traceWhereUsed: (q?: { item?: string; lot?: string; supplier_lot?: string }) => `${MFG}/trace/where-used${queryString(q)}`,
  recalls: () => `${MFG}/recalls`,
  recall: (id: string) => `${MFG}/recalls/${enc(id)}`,
  ecos: () => `${MFG}/eco`,
  eco: (id: string) => `${MFG}/eco/${enc(id)}`,
  transfers: () => `${MFG}/transfers`,
  transfer: (id: string) => `${MFG}/transfers/${enc(id)}`,
  audit: () => `${MFG}/audit`,
  // ---------------------------------------------------------------- M6
  dashboard: (period?: string) => `${MFG}/dashboard${queryString({ period })}`,
  printLabels: (q: { type: "lot" | "serial" | "badge"; ids?: string; item?: string; codes?: string }) => `${MFG}/print/labels${queryString(q)}`,
  // ---------------------------------------------------------------- M7 quality and Part 11
  qaLots: (q?: Record<string, string>) => `${MFG}/qa/inspection-lots${queryString(q)}`,
  qaLot: (id: string) => `${MFG}/qa/inspection-lots/${enc(id)}`,
  qaHolds: (q?: Record<string, string>) => `${MFG}/qa/holds${queryString(q)}`,
  qaNcrs: (q?: Record<string, string>) => `${MFG}/qa/ncrs${queryString(q)}`,
  qaNcr: (id: string) => `${MFG}/qa/ncrs/${enc(id)}`,
  qaCapas: (q?: Record<string, string>) => `${MFG}/qa/capas${queryString(q)}`,
  qaCapa: (id: string) => `${MFG}/qa/capas/${enc(id)}`,
  qaComplaints: (q?: Record<string, string>) => `${MFG}/qa/complaints${queryString(q)}`,
  qaComplaint: (id: string) => `${MFG}/qa/complaints/${enc(id)}`,
  qaFieldActions: (q?: Record<string, string>) => `${MFG}/qa/field-actions${queryString(q)}`,
  qaFieldAction: (id: string) => `${MFG}/qa/field-actions/${enc(id)}`,
  qaEquipmentList: (q?: Record<string, string>) => `${MFG}/qa/equipment${queryString(q)}`,
  qaEquipment: (id: string) => `${MFG}/qa/equipment/${enc(id)}`,
  qaPlans: (q?: Record<string, string>) => `${MFG}/qa/plans${queryString(q)}`,
  qaPlan: (id: string) => `${MFG}/qa/plans/${enc(id)}`,
  qaSchemes: () => `${MFG}/qa/schemes`,
  qaScheme: (id: string) => `${MFG}/qa/schemes/${enc(id)}`,
  qaSettings: () => `${MFG}/qa/settings`,
  esigPolicies: () => `${MFG}/esig/policies`,
  part11: () => `${MFG}/part11`,
  part11Exports: () => `${MFG}/part11/exports`,
  printQa: (type: string, id: string) => `${MFG}/print/qa/${enc(type)}/${enc(id)}`,
  floorInspect: (lotId: string) => `${MFG}/floor/inspect/${enc(lotId)}`,
  esigEnroll: (next?: string) => `/account/signature${queryString({ next })}`,

  // ---------------------------------------------------------------- M8 planning at volume
  forecast: (q?: { v?: string; item?: string }) => `${MFG}/forecast${queryString(q)}`,
  forecastAccuracy: () => `${MFG}/forecast/accuracy`,
  invopt: (q?: { run?: string }) => `${MFG}/invopt${queryString(q)}`,
  ratePlans: () => `${MFG}/rate`,
  rateRun: (id: string, tab?: "grid" | "gantt" | "shortages" | "compare") => `${MFG}/rate/runs/${enc(id)}${tab ? `/${tab}` : ""}`,
  sterilisation: () => `${MFG}/sterilisation`,
  kanban: (q?: { loop?: string }) => `${MFG}/kanban${queryString(q)}`,
  kanbanCards: (loopId: string) => `${MFG}/print/kanban/${enc(loopId)}`,
  validation: () => `${MFG}/validation`,
  // ---------------------------------------------------------------- M9 network, S&OP, trade
  network: () => `${MFG}/network`,
  networkSourcing: () => `${MFG}/network/sourcing`,
  netRun: (id: string, tab?: string) => `${MFG}/network/runs/${enc(id)}${tab ? `/${tab}` : ""}`,
  sop: () => `${MFG}/sop`,
  sopCycle: (id: string, step?: string) => `${MFG}/sop/cycles/${enc(id)}${step ? `/${step}` : ""}`,
  sopScenario: (id: string) => `${MFG}/sop/scenarios/${enc(id)}`,
  trade: (tab?: string) => `${MFG}/trade${tab ? `/${tab}` : ""}`,
  tradeReport: (id: string) => `${MFG}/trade/reports/${enc(id)}`,
  sourcingRisk: () => `${MFG}/sourcing-risk`,
  mps: () => `${MFG}/mps`,
  itemTrade: (itemId: string) => `${MFG}/items/${enc(itemId)}/trade`,
  itemPlanning: (itemId: string) => `${MFG}/items/${enc(itemId)}/planning`,
  itemPackaging: (itemId: string) => `${MFG}/items/${enc(itemId)}/packaging`,
  // ---------------------------------------------------------------- M10 eDHR, CoA, labels, UDI, validation
  dhr: (q?: Record<string, string>) => `${MFG}/dhr${queryString(q)}`,
  dhrRecord: (id: string, q?: { section?: string; v?: string }) => `${MFG}/dhr/${enc(id)}${queryString(q)}`,
  deviations: (q?: Record<string, string>) => `${MFG}/deviations${queryString(q)}`,
  deviation: (id: string, q?: Record<string, string>) => `${MFG}/deviations/${enc(id)}${queryString(q)}`,
  agreements: () => `${MFG}/quality/agreements`,
  agreement: (id: string) => `${MFG}/quality/agreements/${enc(id)}`,
  coas: (q?: Record<string, string>) => `${MFG}/coa${queryString(q)}`,
  coa: (id: string) => `${MFG}/coa/${enc(id)}`,
  batchPacks: () => `${MFG}/batch-packs`,
  batchPack: (id: string) => `${MFG}/batch-packs/${enc(id)}`,
  labels: (tab?: "templates" | "assignments" | "printers") => `${MFG}/labels${tab && tab !== "templates" ? `?tab=${tab}` : ""}`,
  labelTemplate: (id: string) => `${MFG}/labels/templates/${enc(id)}`,
  labelJobs: (q?: Record<string, string>) => `${MFG}/labels/jobs${queryString(q)}`,
  labelJob: (id: string) => `${MFG}/labels/jobs/${enc(id)}`,
  udi: (tab?: "devices" | "exports") => `${MFG}/udi${tab === "exports" ? "?tab=exports" : ""}`,
  validationTab: (tab: string) => `${MFG}/validation?tab=${enc(tab)}`,
  plantTemplate: () => `${MFG}/plant-template`,
};

/** M 11.1 `isMfgPath`. */
export function isMfgPath(pathname: string): boolean {
  return /^\/mfg(\/|$)/.test(pathname);
}
