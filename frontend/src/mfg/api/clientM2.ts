/**
 * Typed wrappers for the M2 endpoints of docs/M2-DESIGN.md 12.3 (#78-#163). All go through `mfgRaw` (same A.14
 * envelope parsing, `X-SP-Workspace` header). Actions take the record's `row_version` for `If-Match`.
 */
import { ifMatch, mfgDownload, mfgRaw, mfgRequest, type QueryValue } from "./client";
import type { List, Page } from "./types";
import type {
  BalancePage,
  CompareResponse,
  ConvertPrRequest,
  ConvertPrResponse,
  ConvertRequest,
  ConvertResponse,
  DemandOrderInput,
  DemandOrderRecord,
  DemandOrderSummary,
  DemandProjectionQuery,
  DemandProjectionRow,
  DemandQuery,
  DocType,
  ExceptionPage,
  ExceptionQuery,
  ItemStock,
  ItemSupplierInput,
  ItemSupplierRecord,
  KittingCheckRequest,
  KittingCheckResponse,
  KittingResponse,
  LocationInput,
  LocationKind,
  LocationRecord,
  LotRecord,
  LotUpdate,
  MeResponse,
  MemberInput,
  MemberRecord,
  MemberUpdate,
  MrpItemPlan,
  MrpItemQuery,
  MrpItemRow,
  MrpParams,
  MrpRunRecord,
  PeggingQuery,
  PeggingResponse,
  PlannedOrderPage,
  PlannedQuery,
  PostingHeader,
  PostingInput,
  PostingRecord,
  PostingType,
  PurchaseDocInput,
  PurchaseDocRecord,
  PurchaseDocSummary,
  PurchaseQuery,
  RunKind,
  ScheduleQuery,
  ScheduleRow,
  ShortageDashboard,
  SupplierDetail,
  SupplierInput,
  SupplierRecord,
  TransactionRow,
  WoQuery,
  WorkOrderInput,
  WorkOrderRecord,
  WorkOrderSummary,
  WorkspaceInfo,
} from "./typesM2";

const enc = encodeURIComponent;

/** A fresh `Idempotency-Key` (pattern `^[A-Za-z0-9._:-]{1,128}$`), one per user submit. */
export function newIdempotencyKey(prefix = "ui"): string {
  const rnd =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${rnd}`.slice(0, 128);
}

/** Multi-value filters (`status`, `code`, `severity`) are sent as repeated parameters; "a,b" is split. */
function multi<Q extends object>(q: Q, keys: string[]): Record<string, QueryValue> {
  const out: Record<string, QueryValue> = { ...(q as Record<string, QueryValue>) };
  for (const k of keys) {
    const v = out[k];
    if (typeof v === "string" && v) out[k] = v.split(",").map((x) => x.trim()).filter(Boolean);
  }
  return out;
}

const act = <T>(path: string, version: number, body: unknown = {}, extra: Record<string, string> = {}) =>
  mfgRequest<T>(path, { method: "POST", body, headers: { ...ifMatch(version), ...extra } });

// ---------------------------------------------------------------- #78-83 me, workspaces, members
export const getMe = (signal?: AbortSignal) => mfgRequest<MeResponse>("/me", { signal });
export const listWorkspaces = (signal?: AbortSignal) => mfgRequest<List<WorkspaceInfo>>("/workspaces", { signal });
export const listMembers = (signal?: AbortSignal) => mfgRequest<List<MemberRecord>>("/members", { signal });
export const createMember = (body: MemberInput) => mfgRequest<MemberRecord>("/members", { method: "POST", body });
export const updateMember = (id: string, body: MemberUpdate, version: number) =>
  mfgRequest<MemberRecord>(`/members/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteMember = (id: string, version: number) =>
  mfgRequest<void>(`/members/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

// ---------------------------------------------------------------- #84-87 locations
export const listLocations = (query: { q?: string; kind?: LocationKind; active?: boolean } = {}, signal?: AbortSignal) =>
  mfgRequest<List<LocationRecord>>("/locations", { query: { ...query }, signal });
export const createLocation = (body: LocationInput) => mfgRequest<LocationRecord>("/locations", { method: "POST", body });
export const updateLocation = (id: string, body: LocationInput, version: number) =>
  mfgRequest<LocationRecord>(`/locations/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteLocation = (id: string, version: number) =>
  mfgRequest<void>(`/locations/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

// ---------------------------------------------------------------- #88-96 suppliers, item-suppliers
export const listSuppliers = (query: { q?: string; active?: boolean } = {}, signal?: AbortSignal) =>
  mfgRequest<List<SupplierRecord>>("/suppliers", { query: { ...query }, signal });
export const createSupplier = (body: SupplierInput) => mfgRequest<SupplierRecord>("/suppliers", { method: "POST", body });
export const getSupplier = (id: string, signal?: AbortSignal) => mfgRequest<SupplierDetail>(`/suppliers/${enc(id)}`, { signal });
export const updateSupplier = (id: string, body: SupplierInput, version: number) =>
  mfgRequest<SupplierRecord>(`/suppliers/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteSupplier = (id: string, version: number) =>
  mfgRequest<void>(`/suppliers/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

export const listItemSuppliers = (query: { item_id?: string; supplier_id?: string }, signal?: AbortSignal) =>
  mfgRequest<List<ItemSupplierRecord>>("/item-suppliers", { query: { ...query }, signal });
export const createItemSupplier = (body: ItemSupplierInput) =>
  mfgRequest<ItemSupplierRecord>("/item-suppliers", { method: "POST", body });
export const updateItemSupplier = (id: string, body: ItemSupplierInput, version: number) =>
  mfgRequest<ItemSupplierRecord>(`/item-suppliers/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteItemSupplier = (id: string, version: number) =>
  mfgRequest<void>(`/item-suppliers/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

// ---------------------------------------------------------------- #97-105 lots, inventory
export interface LotQuery {
  item_id?: string;
  q?: string;
  expiring_before?: string;
  hold?: boolean;
  limit?: number;
  offset?: number;
}
export const listLots = (query: LotQuery, signal?: AbortSignal) => mfgRequest<Page<LotRecord>>("/lots", { query: { ...query }, signal });
export const updateLot = (id: string, body: LotUpdate, version: number) =>
  mfgRequest<LotRecord>(`/lots/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });

export interface BalanceQuery {
  q?: string;
  item_id?: string;
  location_id?: string;
  kind?: LocationKind;
  nettable?: boolean;
  lot_id?: string;
  only_nonzero?: boolean;
  sort?: "part_number" | "location" | "-qty";
  limit?: number;
  offset?: number;
}
export const listBalances = (query: BalanceQuery, signal?: AbortSignal) =>
  mfgRequest<BalancePage>("/inventory/balances", { query: { ...query }, signal });
export const getItemStock = (itemId: string, signal?: AbortSignal) => mfgRequest<ItemStock>(`/items/${enc(itemId)}/stock`, { signal });

export interface TransactionQuery {
  item_id?: string;
  location_id?: string;
  lot_id?: string;
  txn_type?: PostingType;
  posting_id?: string;
  ref_type?: string;
  ref_id?: string;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}
export const listTransactions = (query: TransactionQuery, signal?: AbortSignal) =>
  mfgRequest<Page<TransactionRow>>("/inventory/transactions", { query: { ...query }, signal });

/** #102: the `Idempotency-Key` is created once per user submit by the caller and reused on a retry. */
export async function createPosting(body: PostingInput, idempotencyKey: string): Promise<{ record: PostingRecord; replay: boolean }> {
  const res = await mfgRaw<PostingRecord>("/inventory/postings", { method: "POST", body, headers: { "Idempotency-Key": idempotencyKey } });
  return { record: res.data, replay: res.headers.get("Idempotent-Replay") === "true" };
}
export const listPostings = (query: { type?: PostingType; from?: string; to?: string; q?: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
  mfgRequest<Page<PostingHeader>>("/inventory/postings", { query: { ...query }, signal });
export const getPosting = (id: string, signal?: AbortSignal) => mfgRequest<PostingRecord>(`/inventory/postings/${enc(id)}`, { signal });
export const reversePosting = (id: string, note = "") =>
  mfgRequest<PostingRecord>(`/inventory/postings/${enc(id)}/reverse`, { method: "POST", body: { note } });

// ---------------------------------------------------------------- #106-125 purchasing
const docBase = (t: DocType) => (t === "pr" ? "/purchase-requests" : "/purchase-orders");

export const listPurchaseDocs = (t: DocType, query: PurchaseQuery, signal?: AbortSignal) =>
  mfgRequest<Page<PurchaseDocSummary>>(docBase(t), { query: multi(query, ["status"]), signal });
export const createPurchaseDoc = (t: DocType, body: PurchaseDocInput) =>
  mfgRequest<PurchaseDocRecord>(docBase(t), { method: "POST", body });
export const getPurchaseDoc = (t: DocType, id: string, signal?: AbortSignal) =>
  mfgRequest<PurchaseDocRecord>(`${docBase(t)}/${enc(id)}`, { signal });
export const updatePurchaseDoc = (t: DocType, id: string, body: PurchaseDocInput, version: number) =>
  mfgRequest<PurchaseDocRecord>(`${docBase(t)}/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deletePurchaseDoc = (t: DocType, id: string, version: number) =>
  mfgRequest<void>(`${docBase(t)}/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });

export type PrAction = "submit" | "approve" | "reject" | "revise" | "cancel";
export type PoAction = "issue" | "close" | "cancel";
export const purchaseAction = (t: DocType, id: string, action: PrAction | PoAction, version: number, body: unknown = {}) =>
  act<PurchaseDocRecord>(`${docBase(t)}/${enc(id)}/${action}`, version, body);
export const convertPr = (id: string, body: ConvertPrRequest, version: number, idempotencyKey: string) =>
  act<ConvertPrResponse>(`/purchase-requests/${enc(id)}/convert`, version, body, { "Idempotency-Key": idempotencyKey });

export const listScheduleBoard = (query: ScheduleQuery, signal?: AbortSignal) =>
  mfgRequest<Page<ScheduleRow>>("/purchasing/schedule", { query: { ...query }, signal });

// ---------------------------------------------------------------- #126-133 demand
export const listDemandOrders = (query: DemandQuery, signal?: AbortSignal) =>
  mfgRequest<Page<DemandOrderSummary>>("/demand-orders", { query: { ...query }, signal });
export const createDemandOrder = (body: DemandOrderInput) => mfgRequest<DemandOrderRecord>("/demand-orders", { method: "POST", body });
export const getDemandOrder = (id: string, signal?: AbortSignal) => mfgRequest<DemandOrderRecord>(`/demand-orders/${enc(id)}`, { signal });
export const updateDemandOrder = (id: string, body: DemandOrderInput, version: number) =>
  mfgRequest<DemandOrderRecord>(`/demand-orders/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteDemandOrder = (id: string, version: number) =>
  mfgRequest<void>(`/demand-orders/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });
export const demandAction = (id: string, action: "open" | "close" | "cancel", version: number) =>
  act<DemandOrderRecord>(`/demand-orders/${enc(id)}/${action}`, version);

// ---------------------------------------------------------------- #134-147 work orders
export const listWorkOrders = (query: WoQuery, signal?: AbortSignal) =>
  mfgRequest<Page<WorkOrderSummary>>("/work-orders", { query: multi(query, ["status"]), signal });
export const createWorkOrder = (body: WorkOrderInput) => mfgRequest<WorkOrderRecord>("/work-orders", { method: "POST", body });
export const getWorkOrder = (id: string, signal?: AbortSignal) => mfgRequest<WorkOrderRecord>(`/work-orders/${enc(id)}`, { signal });
export const updateWorkOrder = (id: string, body: WorkOrderInput, version: number) =>
  mfgRequest<WorkOrderRecord>(`/work-orders/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteWorkOrder = (id: string, version: number) =>
  mfgRequest<void>(`/work-orders/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });
export const releaseWorkOrder = (id: string, reserve: boolean, version: number) =>
  act<WorkOrderRecord>(`/work-orders/${enc(id)}/release`, version, { reserve });
export const workOrderAction = (id: string, action: "complete" | "close" | "cancel" | "refresh-components", version: number) =>
  act<WorkOrderRecord>(`/work-orders/${enc(id)}/${action}`, version);
export const reserveWorkOrder = (id: string, version: number, componentIds: string[] | null = null) =>
  act<WorkOrderRecord>(`/work-orders/${enc(id)}/reserve`, version, { component_ids: componentIds });
export const unreserveWorkOrder = (id: string, version: number, componentIds: string[] | null = null) =>
  act<WorkOrderRecord>(`/work-orders/${enc(id)}/unreserve`, version, { component_ids: componentIds });
export const getKitting = (id: string, signal?: AbortSignal) => mfgRequest<KittingResponse>(`/work-orders/${enc(id)}/kitting`, { signal });
export const kittingCheck = (body: KittingCheckRequest, signal?: AbortSignal) =>
  mfgRequest<KittingCheckResponse>("/work-orders/kitting-check", { method: "POST", body, signal });

// ---------------------------------------------------------------- #148-163 MRP, shortages
export const createMrpRun = (body: MrpParams) => mfgRequest<MrpRunRecord>("/mrp/runs", { method: "POST", body });
export const listMrpRuns = (query: { kind?: RunKind; pinned?: boolean; limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<Page<MrpRunRecord>>("/mrp/runs", { query: { ...query }, signal });
export const getLatestRun = (kind: RunKind = "live", signal?: AbortSignal) =>
  mfgRequest<MrpRunRecord>("/mrp/runs/latest", { query: { kind }, signal });
export const getMrpRun = (id: string, signal?: AbortSignal) => mfgRequest<MrpRunRecord>(`/mrp/runs/${enc(id)}`, { signal });
export const updateMrpRun = (id: string, body: { label: string; note: string; pinned: boolean }, version: number) =>
  mfgRequest<MrpRunRecord>(`/mrp/runs/${enc(id)}`, { method: "PUT", body, headers: ifMatch(version) });
export const deleteMrpRun = (id: string, version: number) =>
  mfgRequest<void>(`/mrp/runs/${enc(id)}`, { method: "DELETE", headers: ifMatch(version) });
export const listRunItems = (id: string, query: MrpItemQuery, signal?: AbortSignal) =>
  mfgRequest<Page<MrpItemRow>>(`/mrp/runs/${enc(id)}/items`, { query: { ...query }, signal });
export const getRunItemPlan = (id: string, itemId: string, query: { bucket?: "day" | "week" | "month"; from?: string; to?: string } = {}, signal?: AbortSignal) =>
  mfgRequest<MrpItemPlan>(`/mrp/runs/${enc(id)}/items/${enc(itemId)}`, { query: { ...query }, signal });
export const listPlannedOrders = (id: string, query: PlannedQuery, signal?: AbortSignal) =>
  mfgRequest<PlannedOrderPage>(`/mrp/runs/${enc(id)}/planned-orders`, { query: { ...query }, signal });
export const convertPlannedOrders = (id: string, body: ConvertRequest, idempotencyKey: string) =>
  mfgRequest<ConvertResponse>(`/mrp/runs/${enc(id)}/planned-orders/convert`, {
    method: "POST",
    body,
    headers: { "Idempotency-Key": idempotencyKey },
  });
export const listRunExceptions = (id: string, query: ExceptionQuery, signal?: AbortSignal) =>
  mfgRequest<ExceptionPage>(`/mrp/runs/${enc(id)}/exceptions`, { query: multi(query, ["code", "severity"]), signal });
export const listRunDemand = (id: string, query: DemandProjectionQuery, signal?: AbortSignal) =>
  mfgRequest<Page<DemandProjectionRow>>(`/mrp/runs/${enc(id)}/demand`, { query: { ...query }, signal });
export const getPegging = (id: string, query: PeggingQuery, signal?: AbortSignal) =>
  mfgRequest<PeggingResponse>(`/mrp/runs/${enc(id)}/pegging`, { query: { ...query }, signal });
export const compareRuns = (id: string, withId: string, signal?: AbortSignal) =>
  mfgRequest<CompareResponse>(`/mrp/runs/${enc(id)}/compare`, { query: { with: withId }, signal });
export const downloadRunExport = (id: string, format: "xlsx" | "zip") =>
  mfgDownload(`/mrp/runs/${enc(id)}/export`, { format }, `mrp-run.${format}`);
export const getShortages = (horizonDays = 30, signal?: AbortSignal) =>
  mfgRequest<ShortageDashboard>("/shortages", { query: { horizon_days: horizonDays }, signal });

