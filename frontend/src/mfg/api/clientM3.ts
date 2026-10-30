/** Typed wrappers for the M3 endpoints of docs/M3-DESIGN.md 11 (#164-#199). */
import { ifMatch, mfgDownload, mfgRequest } from "./client";
import type { List, Page } from "./types";
import type {
  ApsCompareResponse,
  ApsDemandResponse,
  ApsExceptionPage,
  ApsParams,
  ApsRunRecord,
  BottleneckRow,
  DispatchResponse,
  EditRequest,
  GanttQuery,
  GanttResponse,
  LoadResponse,
  OpDetail,
  OperationLineRateInput,
  OperationLineRateRecord,
  OperatorAbsenceInput,
  OperatorAbsenceRecord,
  OpQuery,
  OrderResultRow,
  OpenShift,
  OvertimePolicy,
  OvertimeResponse,
  ScheduledOpRow,
  SetupMatrixRowInput,
  SetupMatrixRowRecord,
  WoOperations,
} from "./typesM3";

const enc = encodeURIComponent;
const R = "/aps/runs";

// ---------------------------------------------------------------- #164-175 master
export const listLineRates = (query: { operation_id?: string; line_id?: string }, signal?: AbortSignal) =>
  mfgRequest<List<OperationLineRateRecord>>("/operation-line-rates", { query: { ...query }, signal });
export const createLineRate = (body: OperationLineRateInput) => mfgRequest<OperationLineRateRecord>("/operation-line-rates", { method: "POST", body });
export const updateLineRate = (id: string, body: OperationLineRateInput, v: number) =>
  mfgRequest<OperationLineRateRecord>(`/operation-line-rates/${enc(id)}`, { method: "PUT", body, headers: ifMatch(v) });
export const deleteLineRate = (id: string, v: number) => mfgRequest<void>(`/operation-line-rates/${enc(id)}`, { method: "DELETE", headers: ifMatch(v) });

export const listSetupMatrix = (signal?: AbortSignal) => mfgRequest<List<SetupMatrixRowRecord>>("/setup-matrix", { signal });
export const createSetupRow = (body: SetupMatrixRowInput) => mfgRequest<SetupMatrixRowRecord>("/setup-matrix", { method: "POST", body });
export const updateSetupRow = (id: string, body: SetupMatrixRowInput, v: number) =>
  mfgRequest<SetupMatrixRowRecord>(`/setup-matrix/${enc(id)}`, { method: "PUT", body, headers: ifMatch(v) });
export const deleteSetupRow = (id: string, v: number) => mfgRequest<void>(`/setup-matrix/${enc(id)}`, { method: "DELETE", headers: ifMatch(v) });

export const listAbsences = (query: { operator_id?: string; from?: string; to?: string }, signal?: AbortSignal) =>
  mfgRequest<List<OperatorAbsenceRecord>>("/operator-absences", { query: { ...query }, signal });
export const createAbsence = (body: OperatorAbsenceInput) => mfgRequest<OperatorAbsenceRecord>("/operator-absences", { method: "POST", body });
export const updateAbsence = (id: string, body: OperatorAbsenceInput, v: number) =>
  mfgRequest<OperatorAbsenceRecord>(`/operator-absences/${enc(id)}`, { method: "PUT", body, headers: ifMatch(v) });
export const deleteAbsence = (id: string, v: number) => mfgRequest<void>(`/operator-absences/${enc(id)}`, { method: "DELETE", headers: ifMatch(v) });

// ---------------------------------------------------------------- #176-178 WO operations
export const getWoOperations = (woId: string, signal?: AbortSignal) => mfgRequest<WoOperations>(`/work-orders/${enc(woId)}/operations`, { signal });
export const setWoOperationDone = (woId: string, seq: number, done: boolean, woVersion: number) =>
  mfgRequest<WoOperations>(`/work-orders/${enc(woId)}/operations/${seq}/${done ? "done" : "reopen"}`, { method: "POST", body: {}, headers: ifMatch(woVersion) });

// ---------------------------------------------------------------- #179-187 runs
export const createApsRun = (body: ApsParams) => mfgRequest<ApsRunRecord>(R, { method: "POST", body });
/**
 * M3-DESIGN 16 Q1 escalation: a new run with the same inputs as `runId` and another overtime policy. Sent to #179
 * as `copy_of` + `overtime` (16 names it `POST /schedule/runs ... overtime_policy`; 11 is the frozen path and
 * field name; see 17.WP-U).
 */
export const rerunWithPolicy = (runId: string, overtime: OvertimePolicy, label?: string) =>
  createApsRun({ copy_of: runId, overtime, ...(label ? { label } : {}) });
/** Accept suggested overtime: a live, publishable copy of `runId` with these optional shifts opened ("forced"). */
export const rerunWithOpenShifts = (runId: string, shifts: OpenShift[], label?: string) =>
  createApsRun({ copy_of: runId, open_shifts: shifts, ...(label ? { label } : {}) });
export const listApsRuns = (query: { kind?: string; status?: string; pinned?: boolean; limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<Page<ApsRunRecord>>(R, { query: { ...query }, signal });
export const getPublishedRun = (signal?: AbortSignal) => mfgRequest<ApsRunRecord>(`${R}/published`, { signal });
export const getApsRun = (id: string, signal?: AbortSignal) => mfgRequest<ApsRunRecord>(`${R}/${enc(id)}`, { signal });
export const updateApsRun = (id: string, body: { label: string; note: string; pinned: boolean }, v: number) =>
  mfgRequest<ApsRunRecord>(`${R}/${enc(id)}`, { method: "PUT", body, headers: ifMatch(v) });
export const deleteApsRun = (id: string, v: number) => mfgRequest<void>(`${R}/${enc(id)}`, { method: "DELETE", headers: ifMatch(v) });
export const cancelApsRun = (id: string) => mfgRequest<ApsRunRecord>(`${R}/${enc(id)}/cancel`, { method: "POST", body: {} });
export const publishApsRun = (id: string, v: number, confirmStaleBasis = false) =>
  mfgRequest<ApsRunRecord>(`${R}/${enc(id)}/publish`, {
    method: "POST", body: confirmStaleBasis ? { confirm_stale_basis: true } : {}, headers: ifMatch(v),
  });
export const editApsRun = (id: string, body: EditRequest) => mfgRequest<ApsRunRecord>(`${R}/${enc(id)}/edits`, { method: "POST", body });

// ---------------------------------------------------------------- #188-199 views
export const getGantt = (id: string, query: GanttQuery, signal?: AbortSignal) =>
  mfgRequest<GanttResponse>(`${R}/${enc(id)}/gantt`, { query: { ...query }, signal });
export const listApsOperations = (id: string, query: OpQuery, signal?: AbortSignal) =>
  mfgRequest<Page<ScheduledOpRow>>(`${R}/${enc(id)}/operations`, { query: { ...query }, signal });
export const getApsOperation = (id: string, opNo: number, signal?: AbortSignal) => mfgRequest<OpDetail>(`${R}/${enc(id)}/operations/${opNo}`, { signal });
export const listApsOrders = (id: string, query: { late_only?: boolean; order_type?: string; q?: string; sort?: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
  mfgRequest<Page<OrderResultRow>>(`${R}/${enc(id)}/orders`, { query: { ...query }, signal });
export const listApsDemand = (id: string, query: { late_only?: boolean; program?: string }, signal?: AbortSignal) =>
  mfgRequest<ApsDemandResponse>(`${R}/${enc(id)}/demand`, { query: { ...query }, signal });
export const getApsLoad = (id: string, query: { group_id?: string; line_id?: string; bucket?: "day" | "week"; from?: string; to?: string }, signal?: AbortSignal) =>
  mfgRequest<LoadResponse>(`${R}/${enc(id)}/load`, { query: { ...query }, signal });
export const getDispatch = (id: string, query: { line_id: string; date?: string; shift?: string }, signal?: AbortSignal) =>
  mfgRequest<DispatchResponse>(`${R}/${enc(id)}/dispatch`, { query: { ...query }, signal });
export const getApsOvertime = (id: string, status?: string, signal?: AbortSignal) =>
  mfgRequest<OvertimeResponse>(`${R}/${enc(id)}/overtime`, { query: { status }, signal });
export const listApsExceptions = (id: string, query: { code?: string[]; severity?: string[]; q?: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
  mfgRequest<ApsExceptionPage>(`${R}/${enc(id)}/exceptions`, { query: { ...query }, signal });
export const getBottlenecks = (id: string, signal?: AbortSignal) => mfgRequest<{ items: BottleneckRow[] }>(`${R}/${enc(id)}/bottlenecks`, { signal });
export const compareApsRuns = (id: string, withId: string, signal?: AbortSignal) =>
  mfgRequest<ApsCompareResponse>(`${R}/${enc(id)}/compare`, { query: { with: withId }, signal });
export const downloadApsExport = (id: string, format: "xlsx" | "zip") => mfgDownload(`${R}/${enc(id)}/export`, { format }, `schedule-run.${format}`);

