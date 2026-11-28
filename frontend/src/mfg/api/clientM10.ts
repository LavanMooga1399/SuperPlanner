/**
 * M10 calls (docs/M10-DESIGN.md 10, `/api/v1/mfg`, `router_m10.py`; orgs O1-O2 under `/api/v1/orgs`): eDHR D1-D10,
 * deviations V1-V4, agreements / CoA / batch packs C1-C9, UDI U1-U5, labels L1-L13 and validation Q1-Q5. Signed
 * actions go through `signedAction` (M7 4.2: 202 = a step signature waits for the next signer); regulated writes carry
 * the Part 11 change reason (`X-SP-Change-Reason`) and If-Match.
 */
import { ifMatch, mfgDownload, mfgRequest, mfgUpload, v1Download, v1Request, type QueryParams } from "./client";
import { reasonHeaders, signedAction } from "./clientM7";
import type { SignatureInput } from "./typesM7";
import type {
  Agreement,
  AgreementInput,
  BatchPack,
  Coa,
  Deviation,
  DeviationInput,
  DhrDispositionInput,
  DhrException,
  DhrRecord,
  DhrReleaseInput,
  DhrSectionKey,
  DhrSectionPage,
  DhrSummary,
  EvidenceInput,
  OrgAuditPage,
  PackageInput,
  ReviewQueueRow,
  ExportFormat,
  ExportKind,
  IqResult,
  LabelAssignment,
  LabelTemplate,
  LabelTemplateInput,
  M10List,
  M10Page,
  PlantTemplateApplyResult,
  PrintEventInput,
  PrintJob,
  PrintJobInput,
  Printer,
  PrinterInput,
  Residency,
  ScanPosition,
  UdiDevice,
  UdiDeviceInput,
  UdiExport,
  UdiParse,
  ValPackage,
  VerifyResult,
} from "./typesM10";

const enc = encodeURIComponent;
type Q = Record<string, string | number | boolean | null | undefined>;
const q = (x: Q) => x as QueryParams;

/** Client event id for replay-safe floor / label events. */
export const clientEventId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

// ---------------------------------------------------------------- D1-D10 eDHR
export const listDhr = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10Page<DhrSummary>>("/dhr", { query: q(query), signal });
export const getDhr = (id: string, signal?: AbortSignal) => mfgRequest<DhrRecord>(`/dhr/${enc(id)}`, { signal });
export const getDhrLive = (query: { lot_id?: string; wo_id?: string }, signal?: AbortSignal) => mfgRequest<DhrRecord>("/dhr/live", { query: q(query), signal });
export const assembleDhr = (body: { lot_id?: string; wo_id?: string; reason?: string | null }) =>
  mfgRequest<DhrRecord>("/dhr", { method: "POST", body, headers: reasonHeaders(body.reason) });
export const getDhrSection = (id: string, section: DhrSectionKey, query: { page?: number; limit?: number } = {}, signal?: AbortSignal) =>
  mfgRequest<DhrSectionPage>(`/dhr/${enc(id)}/sections/${enc(section)}`, { query: q(query), signal });
/** D6: answers the updated exception (If-Match = the exception's row_version); reload the record after. */
export const dispositionException = (recordId: string, x: DhrException, body: DhrDispositionInput, reason?: string | null) =>
  mfgRequest<DhrException>(`/dhr/${enc(recordId)}/exceptions/${enc(x.id)}`, { method: "PUT", body, headers: reasonHeaders(reason, x.row_version) });
export const startDhrReview = (r: DhrRecord, note = "") => mfgRequest<DhrRecord>(`/dhr/${enc(r.id)}/start-review`, { method: "POST", body: { note }, headers: ifMatch(r.row_version) });
export const releaseDhr = (r: DhrRecord, body: DhrReleaseInput, signature: SignatureInput | null, comment: string) =>
  signedAction<DhrRecord>(`/dhr/${enc(r.id)}/release`, { ...body }, { version: r.row_version, signature, reason: comment || null });
export const exportDhr = (r: { id: string; number: string; version: number }, format: "pdf" | "json") =>
  mfgDownload(`/dhr/${enc(r.id)}/export`, { format }, `${r.number}-v${r.version}.${format}`);
export const getReviewQueue = (signal?: AbortSignal) => mfgRequest<M10List<ReviewQueueRow>>("/dhr/review-queue", { signal });

// ---------------------------------------------------------------- V1-V4 deviations
export const listDeviations = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10Page<Deviation>>("/deviations", { query: q(query), signal });
export const createDeviation = (body: DeviationInput) => mfgRequest<Deviation>("/deviations", { method: "POST", body });
export const getDeviation = (id: string, signal?: AbortSignal) => mfgRequest<Deviation>(`/deviations/${enc(id)}`, { signal });
export const updateDeviation = (d: Deviation, body: DeviationInput, reason?: string | null) =>
  mfgRequest<Deviation>(`/deviations/${enc(d.id)}`, { method: "PUT", body, headers: reasonHeaders(reason, d.row_version) });
export const approveDeviation = (d: Deviation, signature: SignatureInput | null, comment: string) =>
  signedAction<Deviation>(`/deviations/${enc(d.id)}/approve`, {}, { version: d.row_version, signature, reason: comment || null });
export const closeDeviation = (d: Deviation, outcome: string, cancel = false) =>
  mfgRequest<Deviation>(`/deviations/${enc(d.id)}/close`, { method: "POST", body: { outcome, cancel }, headers: reasonHeaders(outcome, d.row_version) });

// ---------------------------------------------------------------- C1-C3 customer agreements
export const listAgreements = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10Page<Agreement>>("/qa/agreements", { query: q(query), signal });
export const createAgreement = (body: AgreementInput) => mfgRequest<Agreement>("/qa/agreements", { method: "POST", body });
export const getAgreement = (id: string, signal?: AbortSignal) => mfgRequest<Agreement>(`/qa/agreements/${enc(id)}`, { signal });
export const updateAgreement = (a: Agreement, body: AgreementInput, reason?: string | null) =>
  mfgRequest<Agreement>(`/qa/agreements/${enc(a.id)}`, { method: "PUT", body, headers: reasonHeaders(reason, a.row_version) });
export const approveAgreement = (a: Agreement, signature: SignatureInput | null, comment: string) =>
  signedAction<Agreement>(`/qa/agreements/${enc(a.id)}/approve`, {}, { version: a.row_version, signature, reason: comment || null });
export const newAgreementVersion = (a: Agreement) => mfgRequest<Agreement>(`/qa/agreements/${enc(a.id)}/new-version`, { method: "POST", body: {}, headers: ifMatch(a.row_version) });

// ---------------------------------------------------------------- C4-C9 CoA and batch packs
export const createCoa = (body: { lot_id: string; agreement_id: string; demand_line_id?: string | null }) => mfgRequest<Coa>("/coa", { method: "POST", body });
export const listCoas = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10Page<Coa>>("/coa", { query: q(query), signal });
export const getCoa = (id: string, signal?: AbortSignal) => mfgRequest<Coa>(`/coa/${enc(id)}`, { signal });
export const approveCoa = (c: Coa, signature: SignatureInput | null, comment: string) =>
  signedAction<Coa>(`/coa/${enc(c.id)}/approve`, {}, { version: c.row_version, signature, reason: comment || null });
export const voidCoa = (c: Coa, reason: string) => mfgRequest<Coa>(`/coa/${enc(c.id)}/void`, { method: "POST", body: { reason }, headers: reasonHeaders(reason, c.row_version) });
export const exportCoa = (c: Coa, format: "pdf" | "json") => mfgDownload(`/coa/${enc(c.id)}/export`, { format }, `${c.number}.${format}`);
export const createBatchPack = (body: { agreement_id: string; lot_ids: string[]; demand_line_id?: string | null }) => mfgRequest<BatchPack>("/batch-packs", { method: "POST", body });
export const listBatchPacks = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10Page<BatchPack>>("/batch-packs", { query: q(query), signal });
export const getBatchPack = (id: string, signal?: AbortSignal) => mfgRequest<BatchPack>(`/batch-packs/${enc(id)}`, { signal });
export const downloadBatchPack = (p: BatchPack) => mfgDownload(`/batch-packs/${enc(p.id)}/download`, undefined, `${p.number}.zip`);

// ---------------------------------------------------------------- U1-U5 UDI
export const listUdiDevices = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10List<UdiDevice>>("/udi/devices", { query: q(query), signal });
/** U1 PUT: create (no If-Match) or update the draft DI record of a packaging row. */
export const putUdiDevice = (body: UdiDeviceInput, current: UdiDevice | null, reason?: string | null) =>
  mfgRequest<UdiDevice>("/udi/devices", { method: "PUT", body, headers: reasonHeaders(reason, current?.row_version) });
export const approveUdiDevice = (d: UdiDevice, signature: SignatureInput | null, comment: string) =>
  signedAction<UdiDevice>(`/udi/devices/${enc(d.id)}/approve`, {}, { version: d.row_version, signature, reason: comment || null });
export const parseUdi = (code: string, signal?: AbortSignal) => mfgRequest<UdiParse>("/udi/parse", { query: { code }, signal });
export const createUdiExport = (body: { kind: ExportKind; item_ids?: string[] | null; format: ExportFormat }) => mfgRequest<UdiExport>("/udi/exports", { method: "POST", body });
export const listUdiExports = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10Page<UdiExport>>("/udi/exports", { query: q(query), signal });
export const getUdiExport = (id: string, signal?: AbortSignal) => mfgRequest<UdiExport>(`/udi/exports/${enc(id)}`, { signal });
export const downloadUdiExport = (x: UdiExport) => mfgDownload(`/udi/exports/${enc(x.id)}/download`, undefined, x.rendition?.filename ?? `${x.number}.${x.params.format ?? "csv"}`);

// ---------------------------------------------------------------- L1-L6 labels
export const listTemplates = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10Page<LabelTemplate>>("/labels/templates", { query: q(query), signal });
export const createTemplate = (body: LabelTemplateInput) => mfgRequest<LabelTemplate>("/labels/templates", { method: "POST", body });
export const getTemplate = (id: string, signal?: AbortSignal) => mfgRequest<LabelTemplate>(`/labels/templates/${enc(id)}`, { signal });
export const updateTemplate = (tpl: LabelTemplate, body: LabelTemplateInput, reason?: string | null) =>
  mfgRequest<LabelTemplate>(`/labels/templates/${enc(tpl.id)}`, { method: "PUT", body, headers: reasonHeaders(reason, tpl.row_version) });
export const newTemplateVersion = (tpl: LabelTemplate) => mfgRequest<LabelTemplate>(`/labels/templates/${enc(tpl.id)}/new-version`, { method: "POST", body: {}, headers: ifMatch(tpl.row_version) });
/** L4: server-rendered SVG (watermarked "SPECIMEN"); the UI never encodes barcodes itself. */
export async function templatePreview(id: string, query: { item_id?: string; lot_id?: string; v?: number } = {}): Promise<string> {
  const f = await mfgDownload(`/labels/templates/${enc(id)}/preview.svg`, q(query), "preview.svg");
  return f.blob.text();
}
export const listAssignments = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10List<LabelAssignment>>("/labels/assignments", { query: q(query), signal });
/** L5: replaces the assignments of the items named in `rows`. */
export const putAssignments = (rows: LabelAssignment[], reason?: string | null) =>
  mfgRequest<M10List<LabelAssignment>>("/labels/assignments", { method: "PUT", body: { rows }, headers: reasonHeaders(reason) });
export const listPrinters = (signal?: AbortSignal) => mfgRequest<M10List<Printer>>("/labels/printers", { signal });
export const createPrinter = (body: PrinterInput) => mfgRequest<Printer>("/labels/printers", { method: "POST", body });
export const updatePrinter = (p: Printer, body: PrinterInput) => mfgRequest<Printer>(`/labels/printers/${enc(p.id)}`, { method: "PUT", body, headers: ifMatch(p.row_version) });

// ---------------------------------------------------------------- L7-L13 print jobs
export const createPrintJob = (body: PrintJobInput) => mfgRequest<PrintJob>("/labels/jobs", { method: "POST", body });
export const listPrintJobs = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10Page<PrintJob>>("/labels/jobs", { query: q(query), signal });
export const getPrintJob = (id: string, signal?: AbortSignal) => mfgRequest<PrintJob>(`/labels/jobs/${enc(id)}`, { signal });
/** First output = print; later outputs are reprints and need a reason and quantity. */
export const printJobOutput = (j: PrintJob, reprint?: { reason: string; qty: number }) =>
  mfgDownload(`/labels/jobs/${enc(j.id)}/output`, reprint ? { reprint_reason: reprint.reason, qty: reprint.qty } : undefined, `${j.number}.${j.output}`);
export const addPrintEvent = (j: PrintJob, body: PrintEventInput) => mfgRequest<PrintJob>(`/labels/jobs/${enc(j.id)}/events`, { method: "POST", body, headers: reasonHeaders(body.reason) });
export const verifyScan = (j: PrintJob, scan: string, position: ScanPosition) =>
  mfgRequest<VerifyResult>(`/labels/jobs/${enc(j.id)}/verify`, { method: "POST", body: { scan, position, client_event_id: clientEventId("vfy") } });
export const reconcileJob = (j: PrintJob, explanation: string, signature: SignatureInput | null) =>
  signedAction<PrintJob>(`/labels/jobs/${enc(j.id)}/reconcile`, { explanation: explanation || null }, { version: j.row_version, signature, reason: explanation || null });
export const voidJob = (j: PrintJob, reason: string) => mfgRequest<PrintJob>(`/labels/jobs/${enc(j.id)}/void`, { method: "POST", body: { reason }, headers: reasonHeaders(reason, j.row_version) });

// ---------------------------------------------------------------- Q1-Q5 validation
export const runIqCheck = () => mfgRequest<IqResult>("/validation/iq-check", { method: "POST", body: {} });
export const listPackages = (query: Q = {}, signal?: AbortSignal) => mfgRequest<M10Page<ValPackage>>("/validation/packages", { query: q(query), signal });
export const createPackage = (body: PackageInput) => mfgRequest<ValPackage>("/validation/packages", { method: "POST", body });
export const getPackage = (id: string, signal?: AbortSignal) => mfgRequest<ValPackage>(`/validation/packages/${enc(id)}`, { signal });
export const downloadPackage = (p: ValPackage) => mfgDownload(`/validation/packages/${enc(p.id)}/download`, undefined, `${p.number}.zip`);
export const approvePackage = (p: ValPackage, signature: SignatureInput | null, comment: string) =>
  signedAction<ValPackage>(`/validation/packages/${enc(p.id)}/approve`, {}, { version: p.row_version, signature, reason: comment || null });
/** Q5 (JSON body): an HA drill / load report / rehearsal record stored as evidence. */
export const uploadEvidence = (body: EvidenceInput) => mfgRequest<ValPackage>("/validation/evidence", { method: "POST", body });

// ---------------------------------------------------------------- O1-O2 organisation (orgs router)
export const getResidency = (org: string, signal?: AbortSignal) => v1Request<Residency>(`/orgs/${enc(org)}/residency`, { signal });
export const listOrgAudit = (org: string, query: Q = {}, signal?: AbortSignal) => v1Request<OrgAuditPage>(`/orgs/${enc(org)}/audit`, { query: q(query), signal });
export const downloadOrgAudit = (org: string, query: Q = {}) => v1Download(`/orgs/${enc(org)}/audit`, q({ ...query, format: "csv" }), `audit-${org}.csv`);

// ---------------------------------------------------------------- plant template (9.4; route not in the S0 table - UI interpretation)
export const exportPlantTemplate = () => mfgDownload("/plant/template", undefined, "plant-template.json");
export const applyPlantTemplate = (file: File, reason: string) => mfgUpload<PlantTemplateApplyResult>("/plant/template/apply", file, { reason });
