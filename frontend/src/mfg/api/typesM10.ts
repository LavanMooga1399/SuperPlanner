/**
 * M10 contract (docs/M10-DESIGN.md 3-10; S0 freeze): electronic device history record (eDHR) with review by
 * exception and signed release, deviations, customer quality agreements, certificates of analysis and batch packs,
 * UDI device records and GUDID / Health Canada exports, label templates, printers, print jobs with reconciliation and
 * verification scans, validation packages, IQ check, evidence, data residency and the organisation audit. Field names
 * are the JSON names of `backend/superplanner/{dhr,udi,qa,validation}/model.py`. `contractExamplesM10.ts` types
 * example payloads against these declarations so `tsc` fails on drift. Shapes the design leaves open are UI
 * interpretations (listed in M10-DESIGN 14) and are adapted when the S0 fixture lands.
 */
import type { EntityId, IsoDate, IsoDateTime } from "./types";
import type { AttachmentRef, QaItemRef, QaLink, SignatureManifest } from "./typesM7";
import type { PackLevel } from "./typesM8";

export type { EntityId, IsoDate, IsoDateTime };

export interface M10Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  /** user id -> display name of people the page mentions */
  people?: Record<string, string>;
}
export interface M10List<T> {
  items: T[];
}
export type JobStatus = "queued" | "running" | "completed" | "failed";

// ---------------------------------------------------------------- 4 eDHR
export type DhrStatus = "open" | "assembled" | "in_review" | "released" | "rejected";
export const DHR_STATUSES: readonly DhrStatus[] = ["open", "assembled", "in_review", "released", "rejected"];
export type DhrSubject = "lot" | "wo";
export type ExcSeverity = "major" | "minor" | "info";
export type DhrDisposition = "accepted" | "ncr" | "deviation";
export type DhrSectionKey =
  | "header"
  | "materials"
  | "operations"
  | "equipment"
  | "inspections"
  | "nonconformance"
  | "sterilisation"
  | "labels"
  | "serials"
  | "genealogy"
  | "holds"
  | "review";
export const DHR_SECTIONS: readonly DhrSectionKey[] = [
  "header",
  "materials",
  "operations",
  "equipment",
  "inspections",
  "nonconformance",
  "sterilisation",
  "labels",
  "serials",
  "genealogy",
  "holds",
  "review",
];
export type DhrExceptionCode =
  | "DHR_NCR"
  | "DHR_DEVIATION"
  | "DHR_CORRECTION"
  | "DHR_OVERRIDE"
  | "DHR_TIME_WINDOW"
  | "DHR_YIELD"
  | "DHR_QTY_BALANCE"
  | "DHR_LATE_ENTRY"
  | "DHR_CAL"
  | "DHR_MATERIAL_HOLD"
  | "DHR_GENEALOGY_POSSIBLE"
  | "DHR_STER"
  | "DHR_LABEL_RECON"
  | "DHR_POST_RELEASE";

export interface DhrCounts {
  major: number;
  minor: number;
  info: number;
  /** major + minor without a disposition */
  open: number;
  open_major: number;
  open_minor: number;
}

export interface DhrRef {
  id: EntityId;
  number: string;
}

/** D1 list row / review queue row. */
export interface DhrSummary {
  id: EntityId;
  number: string;
  version: number;
  subject_kind: DhrSubject;
  lot_id: EntityId | null;
  lot_code: string | null;
  wo_ids: EntityId[];
  wos: DhrRef[];
  item_id: EntityId;
  item: QaItemRef | null;
  line_code: string | null;
  status: DhrStatus;
  changed_after_release: boolean;
  superseded_by_id: EntityId | null;
  assembled_at: IsoDateTime | null;
  released_at: IsoDateTime | null;
  decision: "released" | "rejected" | null;
  counts: DhrCounts;
  /** oldest undispositioned major/minor exception (age of the review) */
  oldest_open_at: IsoDateTime | null;
  /** person who last dispositioned or started the review */
  owner_id: EntityId | null;
  row_version: number;
}

export interface DhrException {
  id: EntityId;
  record_id: EntityId;
  code: DhrExceptionCode | string;
  severity: ExcSeverity;
  section: DhrSectionKey;
  ref_type: string;
  ref_id: string | null;
  ref_number: string | null;
  message: string;
  data: Record<string, unknown>;
  fingerprint: string;
  /** dispositions the rule allows (4.2); empty for `info` */
  allowed: DhrDisposition[];
  disposition: DhrDisposition | null;
  disposition_ref: string | null;
  disposition_ref_number: string | null;
  comment: string | null;
  carried: boolean;
  reviewed_by: EntityId | null;
  reviewed_at: IsoDateTime | null;
  row_version: number;
}
export interface DhrDispositionInput {
  disposition: DhrDisposition;
  disposition_ref: string | null;
  comment: string;
}

/** One releasability condition that fails (4.3, 409 `DHR_NOT_RELEASABLE` `details.blocking[]`). */
export interface DhrBlocking {
  code: string;
  message: string;
  ref_type?: string | null;
  ref_id?: string | null;
  ref_number?: string | null;
}

/** A generic section body: key facts plus tables; bulk lists are paged through D5. */
export interface DhrSectionTable {
  key: string;
  columns: { key: string; label?: string | null; unit?: string | null }[];
  rows: Record<string, unknown>[];
  /** rows in the full list when `rows` is a preview */
  total?: number;
}
export interface DhrSection {
  facts?: Record<string, unknown>;
  tables?: DhrSectionTable[];
  note?: string | null;
  /** extra fields of a section the UI shows as facts */
  [k: string]: unknown;
}
export type DhrContent = Partial<Record<DhrSectionKey, DhrSection>>;

export interface DhrVersion {
  id: EntityId;
  version: number;
  status: DhrStatus;
  content_sha256: string;
  section_hashes: Partial<Record<DhrSectionKey, string>>;
  assembled_at: IsoDateTime | null;
  changed_after_release: boolean;
  reassemble_reason: string | null;
}

export interface DhrRecord extends DhrSummary {
  item_revision: { bom_version_id?: string | null; routing_version_id?: string | null; ecos?: string[]; revision?: string | null } | null;
  content: DhrContent;
  content_sha256: string;
  section_hashes: Partial<Record<DhrSectionKey, string>>;
  exceptions: DhrException[];
  signatures: SignatureManifest[];
  versions: DhrVersion[];
  supersedes_id: EntityId | null;
  hold_id: EntityId | null;
  hold_status: "held" | "released" | null;
  rendition_id: EntityId | null;
  renderer_version: string | null;
  reassemble_reason: string | null;
  releasable: { ok: boolean; blocking: DhrBlocking[] };
  dhr_required: boolean;
  people?: Record<string, string>;
}
export interface DhrSectionPage {
  section: DhrSectionKey;
  table: string;
  items: Record<string, unknown>[];
  total: number;
  page: number;
  page_size: number;
}
export interface DhrQueueBucket {
  bucket: "lt1d" | "d1to3" | "d3to7" | "gt7d";
  records: number;
  exceptions: number;
}
export interface DhrReviewQueue {
  buckets: DhrQueueBucket[];
  by_owner: { owner_id: EntityId | null; records: number; exceptions: number }[];
  awaiting_review: number;
  changed_after_release: number;
}
export interface DhrReleaseInput {
  decision: "released" | "rejected";
  ncr_id?: string | null;
}

// ---------------------------------------------------------------- 4.4 deviations
export type DeviationKind = "planned" | "unplanned";
export type DeviationStatus = "draft" | "approved" | "closed" | "cancelled";
export interface DeviationScope {
  item_ids: EntityId[];
  lot_ids: EntityId[];
  wo_ids: EntityId[];
  valid_from: IsoDate | null;
  valid_to: IsoDate | null;
  max_qty: number | null;
}
export interface DeviationRisk {
  severity: number;
  occurrence: number;
  rationale: string;
}
export interface DeviationInput {
  kind: DeviationKind;
  title: string;
  description: string;
  scope: DeviationScope;
  risk: DeviationRisk;
  ncr_id: EntityId | null;
  capa_id: EntityId | null;
  external_ref: string | null;
  /** create from a DHR exception (unplanned) */
  from_exception_id?: EntityId | null;
}
export interface Deviation extends Omit<DeviationInput, "from_exception_id"> {
  id: EntityId;
  number: string;
  status: DeviationStatus;
  author_id: EntityId;
  approved_at: IsoDateTime | null;
  closed_at: IsoDateTime | null;
  outcome: string | null;
  /** quantity received in scope so far (scope matching counts receipts) */
  used_qty: number | null;
  items: QaItemRef[];
  lots: { id: EntityId; code: string }[];
  wos: DhrRef[];
  ncr_number: string | null;
  capa_number: string | null;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  signatures: SignatureManifest[];
  links: QaLink[];
  attachments: AttachmentRef[];
}

// ---------------------------------------------------------------- 6 agreements, CoA, batch packs
export type DocState = "draft" | "approved" | "obsolete";
export type CoaReport = "value" | "summary" | "pass";
export type PackDoc = "coa" | "coc" | "dhr_summary" | "dhr_full" | "ster_cert" | "genealogy" | "label_specimen";
export const PACK_DOCS: readonly PackDoc[] = ["coa", "coc", "dhr_summary", "dhr_full", "ster_cert", "genealogy", "label_specimen"];
export type CoaLanguage = "en" | "fr" | "en_fr";
export interface Spec {
  nominal: number | null;
  lsl: number | null;
  usl: number | null;
  unit: string | null;
}
export interface CoaCharacteristic {
  item_id: EntityId | null;
  code: string;
  label: string;
  report: CoaReport;
  /** customer spec override; null = the inspection plan's spec */
  spec: Spec | null;
}
export interface AgreementInput {
  customer: string;
  title: string;
  external_ref: string | null;
  item_ids: EntityId[];
  coa: { characteristics: CoaCharacteristic[]; statement: string; language: CoaLanguage };
  pack: { documents: PackDoc[]; per: "lot" | "shipment" };
  effective_from: IsoDate | null;
}
export interface Agreement extends AgreementInput {
  id: EntityId;
  number: string;
  version: number;
  status: DocState;
  supersedes_id: EntityId | null;
  items: QaItemRef[];
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  signatures: SignatureManifest[];
}
/** Characteristic codes of the approved final inspection plans of an item (agreement picker). */
export interface PlanCharacteristic {
  item_id: EntityId;
  plan_number: string;
  code: string;
  name: string;
  kind: "variable" | "attribute";
  spec: Spec | null;
}

export type CoaStatus = "draft" | "approved" | "void";
export interface CoaLine {
  code: string;
  label: string;
  report: CoaReport;
  spec: Spec | null;
  spec_source: "customer" | "plan";
  n: number;
  mean: number | null;
  min: number | null;
  max: number | null;
  defects: number | null;
  conforms: boolean;
}
export interface Coa {
  id: EntityId;
  number: string;
  agreement_id: EntityId;
  agreement_number: string;
  agreement_version: number;
  lot_id: EntityId;
  lot_code: string;
  item: QaItemRef | null;
  dhr_id: EntityId;
  dhr_number: string;
  customer: string;
  demand_line_id: EntityId | null;
  content: { lines: CoaLine[]; statement: string; language: CoaLanguage };
  content_sha256: string;
  status: CoaStatus;
  rendition_id: EntityId | null;
  void_reason: string | null;
  row_version: number;
  created_at: IsoDateTime;
  signatures: SignatureManifest[];
}
export type PackStatus = "building" | "ready" | "failed";
export interface PackDocument {
  kind: PackDoc | "manifest";
  ref_id: EntityId | null;
  lot_code?: string | null;
  filename: string;
  sha256: string;
  size: number;
}
export interface BatchPack {
  id: EntityId;
  number: string;
  agreement_id: EntityId;
  agreement_number: string;
  lot_ids: EntityId[];
  lots: { id: EntityId; code: string }[];
  customer: string;
  demand_line_id: EntityId | null;
  status: PackStatus;
  documents: PackDocument[];
  manifest_sha256: string | null;
  rendition_id: EntityId | null;
  error: string | null;
  created_at: IsoDateTime;
  created_by: EntityId;
}

// ---------------------------------------------------------------- 7 UDI
export type DiKind = "base" | "unit_of_use" | "package";
export interface PiFlags {
  lot: boolean;
  serial: boolean;
  expiry: boolean;
  mfg_date: boolean;
}
/** GUDID / Health Canada attributes (14.1). */
export interface UdiAttrs {
  brand: string | null;
  version_model: string | null;
  catalog_no: string | null;
  description: string | null;
  gmdn_code: string | null;
  gmdn_term: string | null;
  fda_product_codes: string[];
  fda_class: string | null;
  premarket_nos: string[];
  hc_licence_no: string | null;
  hc_class: string | null;
  sterile: boolean;
  ster_method: string | null;
  single_use: boolean;
  rx: boolean;
  kit: boolean;
  combination: boolean;
  mri_safety: string | null;
  latex: boolean;
  storage: string[];
}
export interface UdiDeviceInput {
  gtin: string;
  di_kind: DiKind;
  qty_per_package: number;
  contains_gtin: string | null;
  pi_flags: PiFlags;
  attrs: UdiAttrs;
  commercial_distribution_date: IsoDate | null;
}
export interface UdiDevice extends UdiDeviceInput {
  id: EntityId;
  packaging_id: EntityId;
  item_id: EntityId;
  item: QaItemRef | null;
  level: PackLevel;
  status: DocState;
  /** labels were printed with this GTIN: it cannot change (409 `UDI_GTIN_IN_USE`) */
  gtin_locked: boolean;
  row_version: number;
  updated_at: IsoDateTime;
  signatures: SignatureManifest[];
}
export interface UdiParse {
  ok: boolean;
  symbology: string | null;
  ais: Record<string, string>;
  gtin: string | null;
  lot: string | null;
  serial: string | null;
  expiry: IsoDate | null;
  mfg_date: IsoDate | null;
  hri: string | null;
  errors: { code: string; message: string }[];
}
export type ExportKind = "gudid" | "hc";
export type ExportFormat = "xlsx" | "csv" | "json";
export interface ExportIssue {
  gtin: string | null;
  item_id: EntityId | null;
  part_number?: string | null;
  element: string | null;
  code: string;
  message: string;
}
export interface UdiExport {
  id: EntityId;
  number: string;
  kind: ExportKind;
  params: { item_ids: EntityId[] | null; format: ExportFormat };
  status: JobStatus;
  rule_version: string | null;
  result: { rows: number; errors: ExportIssue[]; warnings: ExportIssue[] } | null;
  rendition_id: EntityId | null;
  created_at: IsoDateTime;
  created_by: EntityId;
}

// ---------------------------------------------------------------- 7.2 label templates
export type LabelElementKind = "text" | "field" | "barcode" | "box" | "line";
export type Symbology = "gs1_datamatrix" | "gs1_128" | "code128";
export type Ai = "01" | "17" | "10" | "21" | "11";
export const AIS: readonly Ai[] = ["01", "11", "17", "10", "21"];
export interface LabelElement {
  kind: LabelElementKind;
  x_mm: number;
  y_mm: number;
  w_mm: number;
  h_mm: number;
  rotation: 0 | 90 | 180 | 270;
  font_pt: number | null;
  bold: boolean;
  lang: string | null;
  text: string | null;
  field: string | null;
  barcode: { symbology: Symbology; module_mm: number; ais: Ai[] } | null;
}
export const LABEL_FIELDS = [
  "item.name",
  "item.part_number",
  "item.description",
  "udi.gtin",
  "udi.hri",
  "udi.brand",
  "udi.catalog_no",
  "udi.qty_per_package",
  "lot.number",
  "lot.expiry",
  "lot.mfg_date",
  "serial",
  "plant.name",
  "plant.address",
  "symbols.sterile_eo",
  "symbols.single_use",
] as const;
export type TemplateStatus = "draft" | "in_change" | "approved" | "obsolete";
export interface LabelTemplateInput {
  code: string;
  name: string;
  level: PackLevel;
  width_mm: number;
  height_mm: number;
  dpi: 203 | 300 | 600;
  languages: string[];
  elements: LabelElement[];
}
export interface LabelTemplate extends LabelTemplateInput {
  id: EntityId;
  version: number;
  status: TemplateStatus;
  eco_id: EntityId | null;
  eco_number: string | null;
  approved_at: IsoDateTime | null;
  supersedes_id: EntityId | null;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
export interface LabelAssignment {
  id: EntityId;
  item_id: EntityId;
  item: QaItemRef | null;
  level: PackLevel;
  customer: string | null;
  template_code: string;
}
export type LabelAssignmentInput = Omit<LabelAssignment, "id" | "item">;
export interface PrinterInput {
  code: string;
  name: string;
  kind: "zpl_raw";
  host: string;
  port: number;
  dpi: 203 | 300 | 600;
  line_id: EntityId | null;
  active: boolean;
}
export interface Printer extends PrinterInput {
  id: EntityId;
  row_version: number;
}

// ---------------------------------------------------------------- 7.3 print jobs
export type PrintJobStatus = "requested" | "issued" | "printed" | "blocked" | "reconciled" | "void";
export type PrintEventKind = "issued" | "printed" | "reprint" | "used" | "destroyed" | "retained" | "verify" | "unblock";
export type ScanPosition = "first" | "last" | "sample";
export interface PrintTotals {
  issued: number;
  printed: number;
  reprinted: number;
  used: number;
  destroyed: number;
  retained: number;
  diff: number;
}
export interface PrintEvent {
  id: EntityId;
  kind: PrintEventKind;
  qty: number | null;
  serials: string[] | null;
  position: ScanPosition | null;
  scan: string | null;
  result: "match" | "mismatch" | null;
  mismatch: Record<string, { expected: string | null; scanned: string | null }> | null;
  reason: string | null;
  actor_id: EntityId;
  actor_name?: string | null;
  at: IsoDateTime;
}
export interface PrintJobInput {
  item_id: EntityId;
  level: PackLevel;
  lot_id: EntityId;
  wo_id: EntityId | null;
  qty: number;
  output: "pdf" | "zpl";
  target: "download" | "printer";
  printer_id: EntityId | null;
  customer?: string | null;
}
export interface PrintJob {
  id: EntityId;
  number: string;
  item_id: EntityId;
  item: QaItemRef | null;
  level: PackLevel;
  udi_id: EntityId;
  gtin: string;
  lot_id: EntityId;
  lot_code: string;
  wo_id: EntityId | null;
  wo_number: string | null;
  template_id: EntityId;
  template_code: string;
  template_version: number;
  qty: number;
  serials: string[] | null;
  data: Record<string, unknown>;
  data_sha256: string;
  hri: string | null;
  output: "pdf" | "zpl";
  target: "download" | "printer";
  printer_id: EntityId | null;
  status: PrintJobStatus;
  totals: PrintTotals;
  recon_explanation: string | null;
  reconciled_at: IsoDateTime | null;
  /** first / last verification matched (7.4) */
  verified: { first: boolean; last: boolean };
  /** proposal for `used` (WO good qty at the level) */
  used_proposal: number | null;
  /** a signature is needed to reconcile (diff != 0 or Part 11 mode) */
  recon_signature_required: boolean;
  events: PrintEvent[];
  signatures: SignatureManifest[];
  row_version: number;
  created_at: IsoDateTime;
  created_by: EntityId;
}
export interface PrintEventInput {
  kind: Exclude<PrintEventKind, "issued" | "verify">;
  qty: number;
  serials?: string[] | null;
  reason?: string | null;
  client_event_id: string;
}
export interface VerifyResult {
  event: PrintEvent;
  job: PrintJob;
}

// ---------------------------------------------------------------- 8 validation package
export type PackageKind = "full" | "iq" | "oq" | "pq" | "periodic" | "evidence";
export interface ValPackageFile {
  path: string;
  sha256: string;
  size: number;
  kind?: string | null;
}
export interface ValPackage {
  id: EntityId;
  number: string;
  kind: PackageKind;
  params: Record<string, unknown>;
  status: JobStatus;
  approval: "none" | "pending" | "approved";
  baseline_id: EntityId | null;
  prev_baseline_id: EntityId | null;
  manifest: { files: ValPackageFile[]; baseline_diff?: { path: string; change: string }[]; periodic?: Record<string, unknown>; summary?: Record<string, unknown> } | null;
  sha256: string | null;
  error: string | null;
  evidence_kind?: "ha_drill" | "load_report" | "ha_rehearsal" | null;
  created_at: IsoDateTime;
  created_by: EntityId;
  row_version: number;
  signatures: SignatureManifest[];
}
export interface IqCheckRow {
  code: string;
  label: string;
  result: "pass" | "fail" | "warn";
  expected: string | null;
  observed: string | null;
  detail: string | null;
}
export interface IqCheck {
  ran_at: IsoDateTime;
  plant: string;
  app_version: string;
  ok: boolean;
  checks: IqCheckRow[];
}

// ---------------------------------------------------------------- 9 enterprise
export type RegionEndpoint = "archive" | "backup" | "smtp" | "logs" | "ai";
export interface Residency {
  org: string;
  data_region: string;
  deployment_region: string;
  ok: boolean;
  endpoints: { name: RegionEndpoint; region: string | null; ok: boolean }[];
  integrations: { id: EntityId; plant_code: string; name: string; region: string | null; ok: boolean; cross_region_signed: boolean }[];
  plants: { code: string; name: string; part11_mode: boolean; assistant_enabled: boolean; ok: boolean }[];
  mismatches: { code: string; subject: string; detail: string | null }[];
}
export interface OrgAuditRow {
  id: EntityId;
  at: IsoDateTime;
  plant_code: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_id: EntityId | null;
  actor_name: string | null;
  reason: string | null;
  changes: Record<string, unknown> | null;
}
export interface PlantTemplateSummary {
  plant: string;
  sections: { key: string; count: number }[];
}
export interface PlantTemplateApplyResult {
  applied: { key: string; count: number }[];
  drafts: { key: string; count: number }[];
  skipped: { key: string; reason: string }[];
}

/** M10 keys of `qa_settings` (3). */
export interface QaSettingsM10 {
  dhr_required: boolean | null;
  dhr_review_days: number;
  dhr_late_entry_hours: number;
  dhr_min_yield_pct: number | null;
  dhr_post_release_hold: boolean;
  label_recon_tolerance: number;
  label_verify_first_last: boolean;
  paper: "letter" | "a4";
  deviation_sor: "superplanner" | "external";
}
