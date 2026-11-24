/**
 * M7 calls (docs/M7-DESIGN.md 9): signatures and Part 11 (P1-P5, E1-E12), quality (Q1-Q64). Signable actions go
 * through `signedAction`: 200 = done (the record with `signatures`), 202 = a step signature recorded and the next
 * step pending. Regulated updates take an optional change reason (`X-SP-Change-Reason`, percent-encoded UTF-8).
 */
import { ifMatch, mfgDownload, mfgRaw, mfgRequest, v1Request, type QueryParams } from "./client";
import { API_BASE, ApiError } from "../../api/client";
import { authFetch } from "../../auth/authFetch";
import { workspaceHeaders } from "../lib/workspace";
import type {
  Calibration,
  CalibrationInput,
  Capa,
  CapaAction,
  CapaInput,
  Complaint,
  ComplaintInput,
  DecisionInput,
  EnrollInput,
  Equipment,
  EquipmentImpact,
  EquipmentInput,
  EsigPolicy,
  EsigPreview,
  EsigStatus,
  FieldAction,
  FieldActionInput,
  FieldActionUnit,
  Hold,
  InspectionLot,
  InspectionLotDetail,
  InspectionPlan,
  MetaTime,
  Ncr,
  NcrInput,
  Part11Export,
  Part11Mode,
  Part11Package,
  PendingSignatures,
  PlanInput,
  PolicyInput,
  QaLink,
  QaListQuery,
  QaPage,
  QaSettings,
  RecordAuditEvent,
  ResultEntry,
  SamplingResolve,
  SamplingScheme,
  SchemeInput,
  SignatureInput,
  SignatureRecord,
  UnitStatus,
  AttachmentRef,
  VerifyResult,
  Disposition,
} from "./typesM7";

const enc = encodeURIComponent;

/** `X-SP-Change-Reason` (4.4): percent-encoded UTF-8, only when a reason is given. */
export function reasonHeaders(reason?: string | null, version?: number): Record<string, string> {
  const h: Record<string, string> = version !== undefined ? ifMatch(version) : {};
  if (reason && reason.trim()) h["X-SP-Change-Reason"] = encodeURIComponent(reason.trim());
  return h;
}

export type SignedResult<T> = { status: 200; record: T } | { status: 202; pending: PendingSignatures };

/** POST a signable action (4.2): `signature` is optional (Part 11 off, or no policy for the action). */
export async function signedAction<T>(path: string, body: Record<string, unknown>, opts: { version?: number; signature?: SignatureInput | null; reason?: string | null } = {}): Promise<SignedResult<T>> {
  const res = await mfgRaw<T | PendingSignatures>(path, {
    method: "POST",
    body: opts.signature ? { ...body, signature: opts.signature } : body,
    headers: reasonHeaders(opts.reason, opts.version),
  });
  if (res.status === 202) return { status: 202, pending: res.data as PendingSignatures };
  return { status: 200, record: res.data as T };
}

const list = <T>(path: string, query: QaListQuery | QueryParams = {}, signal?: AbortSignal) => mfgRequest<QaPage<T>>(path, { query: { ...query } as QueryParams, signal });

// ---------------------------------------------------------------- P1-P5 (session)
export const getEsigStatus = (signal?: AbortSignal) => v1Request<EsigStatus>("/auth/esig/status", { signal });
export const enrollEsig = (body: EnrollInput) => v1Request<EsigStatus>("/auth/esig/enroll", { method: "POST", body });
/** P3: the step-up popup URL; the callback page posts `{type: "sp-esig-stepup", token}` to the opener. */
export const stepupUrl = (purpose: "esig" | "enroll" = "esig") => `${API_BASE}/auth/oidc/stepup?purpose=${enc(purpose)}`;
export const revokeEsig = (org: string, memberId: string) => v1Request<unknown>(`/orgs/${enc(org)}/members/${enc(memberId)}/esig-revoke`, { method: "POST", body: {} });
export const getMetaTime = (signal?: AbortSignal) => v1Request<MetaTime>("/meta/time", { signal });

// ---------------------------------------------------------------- E1-E12
export const listPolicies = (signal?: AbortSignal) => mfgRequest<{ items: EsigPolicy[] }>("/esig/policies", { signal });
export const updatePolicy = (recordType: string, action: string, body: PolicyInput, version: number) =>
  mfgRaw<EsigPolicy | PendingSignatures>(`/esig/policies/${enc(recordType)}/${enc(action)}`, { method: "PUT", body, headers: ifMatch(version) }).then((r) =>
    r.status === 202 ? ({ status: 202, pending: r.data as PendingSignatures } as const) : ({ status: 200, record: r.data as EsigPolicy } as const),
  );
export const getPreview = (query: { record_type: string; record_id: string; action: string; decision?: string }, signal?: AbortSignal) =>
  mfgRequest<EsigPreview>("/esig/preview", { query: { ...query }, signal });
export const listSignatures = (query: { record_type?: string; record_id?: string; signer?: string; from?: string; to?: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
  mfgRequest<QaPage<SignatureRecord>>("/esig/signatures", { query: { ...query }, signal });
export const verifySignature = (id: string, signal?: AbortSignal) => mfgRequest<VerifyResult>(`/esig/signatures/${enc(id)}/verify`, { signal });
export const getRecordAudit = (query: { entity_type: string; entity_id: string; limit?: number; offset?: number }, signal?: AbortSignal) =>
  mfgRequest<QaPage<RecordAuditEvent>>("/audit/record", { query: { ...query }, signal });
export const getPart11Package = (recordType: string, recordId: string, signal?: AbortSignal) =>
  mfgRequest<Part11Package>(`/part11/records/${enc(recordType)}/${enc(recordId)}`, { signal });
export const createPart11Export = (body: { from: string; to: string; record_types: string[] }) => mfgRequest<Part11Export>("/part11/exports", { method: "POST", body });
export const listPart11Exports = (signal?: AbortSignal) => mfgRequest<QaPage<Part11Export>>("/part11/exports", { signal });
export const downloadPart11Export = (id: string) => mfgDownload(`/part11/exports/${enc(id)}/download`, undefined, `part11-${id}.zip`);
export const getPart11Mode = (signal?: AbortSignal) => mfgRequest<Part11Mode>("/plant/part11", { signal });
export const enablePart11 = (signature: SignatureInput | null, version: number) =>
  mfgRaw<Part11Mode | PendingSignatures>("/plant/part11", { method: "PUT", body: { enabled: true, ...(signature ? { signature } : {}) }, headers: ifMatch(version) }).then((r) =>
    r.status === 202 ? ({ status: 202, pending: r.data as PendingSignatures } as const) : ({ status: 200, record: r.data as Part11Mode } as const),
  );

// ---------------------------------------------------------------- Q1-Q2 settings
export const getQaSettings = (signal?: AbortSignal) => mfgRequest<QaSettings>("/plant/qa-settings", { signal });
export const updateQaSettings = (body: Omit<QaSettings, "row_version">, version: number, reason?: string | null) =>
  mfgRequest<QaSettings>("/plant/qa-settings", { method: "PUT", body, headers: reasonHeaders(reason, version) });

// ---------------------------------------------------------------- Q3-Q7 schemes
const S = "/qa/schemes";
export const listSchemes = (query: QaListQuery = {}, signal?: AbortSignal) => list<SamplingScheme>(S, query, signal);
export const createScheme = (body: SchemeInput) => mfgRequest<SamplingScheme>(S, { method: "POST", body });
export const getScheme = (id: string, signal?: AbortSignal) => mfgRequest<SamplingScheme>(`${S}/${enc(id)}`, { signal });
export const updateScheme = (id: string, body: SchemeInput, version: number, reason?: string | null) =>
  mfgRequest<SamplingScheme>(`${S}/${enc(id)}`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const deleteScheme = (id: string, version: number, reason?: string | null) => mfgRequest<void>(`${S}/${enc(id)}`, { method: "DELETE", headers: reasonHeaders(reason, version) });
export const resolveSampling = (id: string, query: { lot_size: number; level?: string; aql?: number; state?: string }, signal?: AbortSignal) =>
  mfgRequest<SamplingResolve>(`${S}/${enc(id)}/resolve`, { query: { ...query }, signal });

// ---------------------------------------------------------------- Q8-Q14 plans
const P = "/qa/plans";
export const listPlans = (query: QaListQuery = {}, signal?: AbortSignal) => list<InspectionPlan>(P, query, signal);
export const createPlan = (body: PlanInput) => mfgRequest<InspectionPlan>(P, { method: "POST", body });
export const getPlan = (id: string, signal?: AbortSignal) => mfgRequest<InspectionPlan>(`${P}/${enc(id)}`, { signal });
export const updatePlan = (id: string, body: PlanInput, version: number, reason?: string | null) =>
  mfgRequest<InspectionPlan>(`${P}/${enc(id)}`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const deletePlan = (id: string, version: number, reason?: string | null) => mfgRequest<void>(`${P}/${enc(id)}`, { method: "DELETE", headers: reasonHeaders(reason, version) });
export const copyPlan = (id: string) => mfgRequest<InspectionPlan>(`${P}/${enc(id)}/copy`, { method: "POST", body: {} });

// ---------------------------------------------------------------- Q15-Q20 inspection lots
const L = "/qa/inspection-lots";
export const listInspectionLots = (query: QaListQuery = {}, signal?: AbortSignal) => list<InspectionLot>(L, query, signal);
export const createInspectionLot = (body: { plan_id: string; lot_id?: string | null; lot_size: number; hold: boolean; note?: string }) => mfgRequest<InspectionLot>(L, { method: "POST", body });
export const getInspectionLot = (id: string, signal?: AbortSignal) => mfgRequest<InspectionLotDetail>(`${L}/${enc(id)}`, { signal });
export const postResults = (id: string, body: { client_batch_id: string; results: ResultEntry[] }) => mfgRequest<InspectionLotDetail>(`${L}/${enc(id)}/results`, { method: "POST", body });
export const decideInspectionLot = (id: string, body: DecisionInput, version: number) =>
  signedAction<InspectionLotDetail>(`${L}/${enc(id)}/decision`, { decision: body.decision, note: body.note, ...(body.ncr_id ? { ncr_id: body.ncr_id } : {}) }, { version, signature: body.signature });
export const cancelInspectionLot = (id: string, version: number, reason: string) =>
  mfgRequest<InspectionLotDetail>(`${L}/${enc(id)}/cancel`, { method: "POST", body: {}, headers: reasonHeaders(reason, version) });

// ---------------------------------------------------------------- Q21-Q23 holds
export const listHolds = (query: QaListQuery = {}, signal?: AbortSignal) => list<Hold>("/qa/holds", query, signal);
export const placeHold = (body: { lot_id?: string; serial_id?: string; reason: string }) => mfgRequest<Hold>("/qa/holds", { method: "POST", body });

// ---------------------------------------------------------------- Q24-Q31 NCR
const N = "/qa/ncrs";
export const listNcrs = (query: QaListQuery = {}, signal?: AbortSignal) => list<Ncr>(N, query, signal);
export const createNcr = (body: NcrInput) => mfgRequest<Ncr>(N, { method: "POST", body });
export const getNcr = (id: string, signal?: AbortSignal) => mfgRequest<Ncr>(`${N}/${enc(id)}`, { signal });
export const updateNcr = (id: string, body: NcrInput, version: number, reason?: string | null) => mfgRequest<Ncr>(`${N}/${enc(id)}`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const proposeNcr = (id: string, dispositions: Disposition[], version: number, reason?: string | null) =>
  mfgRequest<Ncr>(`${N}/${enc(id)}/propose`, { method: "POST", body: { dispositions }, headers: reasonHeaders(reason, version) });
export const ncrStep = (id: string, action: "open" | "implement" | "cancel", version: number, reason?: string | null) =>
  mfgRequest<Ncr>(`${N}/${enc(id)}/${action}`, { method: "POST", body: {}, headers: reasonHeaders(reason, version) });

// ---------------------------------------------------------------- Q32-Q39 CAPA
const C = "/qa/capas";
export const listCapas = (query: QaListQuery = {}, signal?: AbortSignal) => list<Capa>(C, query, signal);
export const createCapa = (body: CapaInput) => mfgRequest<Capa>(C, { method: "POST", body });
export const getCapa = (id: string, signal?: AbortSignal) => mfgRequest<Capa>(`${C}/${enc(id)}`, { signal });
export const updateCapa = (id: string, body: CapaInput, version: number, reason?: string | null) => mfgRequest<Capa>(`${C}/${enc(id)}`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const addCapaAction = (id: string, body: Partial<CapaAction> & { owner_user_id?: string | null }) => mfgRequest<Capa>(`${C}/${enc(id)}/actions`, { method: "POST", body });
export const updateCapaAction = (id: string, actionId: string, body: Partial<CapaAction> & { owner_user_id?: string | null }, version: number, reason?: string | null) =>
  mfgRequest<Capa>(`${C}/${enc(id)}/actions/${enc(actionId)}`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const deleteCapaAction = (id: string, actionId: string, version: number) => mfgRequest<Capa>(`${C}/${enc(id)}/actions/${enc(actionId)}`, { method: "DELETE", headers: ifMatch(version) });
export const advanceCapa = (id: string, to: string, version: number, reason?: string | null) => mfgRequest<Capa>(`${C}/${enc(id)}/advance`, { method: "POST", body: { to }, headers: reasonHeaders(reason, version) });

// ---------------------------------------------------------------- Q40-Q44 complaints
const K = "/qa/complaints";
export const listComplaints = (query: QaListQuery = {}, signal?: AbortSignal) => list<Complaint>(K, query, signal);
export const createComplaint = (body: ComplaintInput) => mfgRequest<Complaint>(K, { method: "POST", body });
export const getComplaint = (id: string, signal?: AbortSignal) => mfgRequest<Complaint>(`${K}/${enc(id)}`, { signal });
export const updateComplaint = (id: string, body: ComplaintInput, version: number, reason?: string | null) => mfgRequest<Complaint>(`${K}/${enc(id)}`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const advanceComplaint = (id: string, version: number, reason?: string | null) => mfgRequest<Complaint>(`${K}/${enc(id)}/advance`, { method: "POST", body: {}, headers: reasonHeaders(reason, version) });

// ---------------------------------------------------------------- Q45-Q52 field actions
const F = "/qa/field-actions";
export const listFieldActions = (query: QaListQuery = {}, signal?: AbortSignal) => list<FieldAction>(F, query, signal);
export const createFieldAction = (body: FieldActionInput) => mfgRequest<FieldAction>(F, { method: "POST", body });
export const getFieldAction = (id: string, signal?: AbortSignal) => mfgRequest<FieldAction>(`${F}/${enc(id)}`, { signal });
export const updateFieldAction = (id: string, body: Omit<FieldActionInput, "recall_id">, version: number, reason?: string | null) =>
  mfgRequest<FieldAction>(`${F}/${enc(id)}`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const listFieldActionUnits = (id: string, query: QaListQuery = {}, signal?: AbortSignal) => list<FieldActionUnit>(`${F}/${enc(id)}/units`, query, signal);
export const bulkUnitStatus = (id: string, items: { unit_id: string; status: UnitStatus; note?: string | null }[]) =>
  mfgRequest<{ updated: number; errors: { unit_id: string; message: string }[] }>(`${F}/${enc(id)}/units/bulk`, { method: "POST", body: { items } });
export const completeFieldAction = (id: string, version: number, reason?: string | null) => mfgRequest<FieldAction>(`${F}/${enc(id)}/complete`, { method: "POST", body: reason ? { reason } : {}, headers: reasonHeaders(reason, version) });
export const exportFieldAction = (id: string, format: "xlsx" | "json") => mfgDownload(`${F}/${enc(id)}/export`, { format }, `field-action-${id}.${format}`);

// ---------------------------------------------------------------- Q53-Q59 equipment
const E = "/qa/equipment";
export const listEquipment = (query: QaListQuery = {}, signal?: AbortSignal) => list<Equipment>(E, query, signal);
export const createEquipment = (body: EquipmentInput) => mfgRequest<Equipment>(E, { method: "POST", body });
export const getEquipment = (id: string, signal?: AbortSignal) => mfgRequest<Equipment>(`${E}/${enc(id)}`, { signal });
export const updateEquipment = (id: string, body: EquipmentInput, version: number, reason?: string | null) => mfgRequest<Equipment>(`${E}/${enc(id)}`, { method: "PUT", body, headers: reasonHeaders(reason, version) });
export const getEquipmentImpact = (id: string, signal?: AbortSignal) => mfgRequest<EquipmentImpact>(`${E}/${enc(id)}/impact`, { signal });
export const listCalibrations = (id: string, signal?: AbortSignal) => mfgRequest<{ items: Calibration[] }>(`${E}/${enc(id)}/calibrations`, { signal });
export const recordCalibration = (id: string, body: CalibrationInput, version: number) => {
  const { signature, ...rest } = body;
  return signedAction<Equipment>(`${E}/${enc(id)}/calibrations`, rest as Record<string, unknown>, { version, signature });
};

// ---------------------------------------------------------------- Q60-Q64 attachments, links
export async function uploadAttachment(entityType: string, entityId: string, file: File): Promise<AttachmentRef> {
  const form = new FormData();
  form.append("entity_type", entityType);
  form.append("entity_id", entityId);
  form.append("file", file, file.name);
  const res = await authFetch(`${API_BASE}/mfg/qa/attachments`, { method: "POST", body: form, headers: { Accept: "application/json", ...workspaceHeaders() } });
  if (!res.ok) {
    // reuse the envelope parsing of the JSON helpers
    const text = await res.text();
    let code = `HTTP_${res.status}`;
    let message = res.statusText;
    let details: Record<string, unknown> = {};
    try {
      const j = JSON.parse(text) as { error?: { code: string; message: string; details?: Record<string, unknown> } };
      if (j.error) ({ code, message } = j.error), (details = j.error.details ?? {});
    } catch {
      /* not JSON */
    }
    const e = new ApiError(res.status, code, message, details);
    e.requestId = res.headers.get("x-request-id") ?? undefined;
    throw e;
  }
  return (await res.json()) as AttachmentRef;
}
export const downloadAttachment = (id: string, name: string) => mfgDownload(`/qa/attachments/${enc(id)}`, undefined, name);
export const deleteAttachment = (id: string) => mfgRequest<void>(`/qa/attachments/${enc(id)}`, { method: "DELETE" });
export const createLink = (body: { from_type: string; from_id: string; to_type: string; to_id: string }) => mfgRequest<QaLink>("/qa/links", { method: "POST", body });
export const deleteLink = (id: string) => mfgRequest<void>(`/qa/links/${enc(id)}`, { method: "DELETE" });

/** Generic signable action by record type (record pages): POST `<base>/<id>/<action>`. */
export const QA_BASE: Record<string, string> = {
  sampling_scheme: S,
  inspection_plan: P,
  inspection_lot: L,
  hold: "/qa/holds",
  ncr: N,
  capa: C,
  complaint: K,
  field_action: F,
  equipment: E,
};
export function recordAction<T>(recordType: string, id: string, action: string, body: Record<string, unknown>, opts: { version?: number; signature?: SignatureInput | null; reason?: string | null } = {}) {
  return signedAction<T>(`${QA_BASE[recordType]}/${enc(id)}/${action}`, body, opts);
}
