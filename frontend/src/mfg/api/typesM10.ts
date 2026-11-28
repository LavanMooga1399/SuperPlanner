/**
 * M10 contract (docs/M10-DESIGN.md 3-10; S0 freeze): electronic device history record (eDHR) with review by
 * exception and signed release, deviations, customer quality agreements, certificates of analysis and batch packs,
 * UDI device records and GUDID / Health Canada exports, label templates, printers, print jobs with reconciliation and
 * verification scans, validation packages, IQ check, evidence, data residency and the organisation audit. Mirrors
 * `backend/superplanner/{dhr,udi,validation}/model.py` and `qa/model_m10.py`; field names are the JSON names.
 * `contractExamplesM10.ts` types the S0 fixture (`api/mfg/fixtures/example_m10.json`) against these declarations, so
 * `tsc` fails on drift.
 */
import type { EntityId, IsoDate, IsoDateTime } from "./types";
import type { QaLink, SignatureManifest } from "./typesM7";

export type { EntityId, IsoDate, IsoDateTime };

export interface M10Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface M10List<T> {
  items: T[];
}
export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface RenditionRef {
  id: EntityId;
  kind: "pdf" | "json" | "zip" | "zpl" | "csv" | "xlsx";
  filename: string;
  sha256: string;
  size: number;
  renderer_version: string;
  created_at: IsoDateTime;
  warnings: string[];
}
export interface M10ItemRef {
  id: EntityId;
  part_number: string | null;
  revision: string | null;
  name: string | null;
}

// ---------------------------------------------------------------- 4 eDHR
export type DhrStatus = "open" | "assembled" | "in_review" | "released" | "rejected";
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
export const DHR_SECTIONS: readonly DhrSectionKey[] = ["header", "materials", "operations", "equipment", "inspections", "nonconformance", "sterilisation", "labels", "serials", "genealogy", "holds", "review"];

export interface DhrCounts {
  major: number;
  minor: number;
  info: number;
  /** major + minor without a disposition */
  open: number;
}

/** D1 list row. */
export interface DhrSummary {
  id: EntityId;
  number: string;
  version: number;
  subject_kind: DhrSubject;
  lot_id: EntityId | null;
  lot_code: string | null;
  wo_ids: EntityId[];
  wo_numbers: string[];
  item: M10ItemRef;
  status: DhrStatus;
  changed_after_release: boolean;
  superseded_by_id: EntityId | null;
  assembled_at: IsoDateTime;
  age_days: number;
  counts: DhrCounts;
  released_at: IsoDateTime | null;
  decision: "released" | "rejected" | null;
  row_version: number;
}

/** D10: records waiting for review, oldest first. */
export interface ReviewQueueRow {
  id: EntityId;
  number: string;
  version: number;
  status: DhrStatus;
  item: M10ItemRef;
  lot_code: string | null;
  line_codes: string[];
  open_major: number;
  open_minor: number;
  oldest_exception_age_days: number;
  age_days: number;
  changed_after_release: boolean;
  reviewer_ids: EntityId[];
}

export interface DhrException {
  id: EntityId;
  record_id: EntityId;
  code: string;
  severity: ExcSeverity;
  section: DhrSectionKey;
  ref_type: string;
  ref_id: string | null;
  ref_number: string | null;
  message: string;
  data: Record<string, unknown>;
  fingerprint: string;
  disposition: DhrDisposition | null;
  disposition_ref: string | null;
  disposition_ref_number: string | null;
  comment: string | null;
  carried: boolean;
  reviewed_by: EntityId | null;
  reviewed_at: IsoDateTime | null;
  /** dispositions the rule allows (4.2); empty for `info` */
  allowed: DhrDisposition[];
  /** major / minor without a disposition */
  needs_disposition: boolean;
  row_version: number;
}
export interface DhrDispositionInput {
  disposition: DhrDisposition;
  disposition_ref: string | null;
  comment: string;
}

export type BlockingCode = "EXCEPTION_OPEN" | "NCR_OPEN" | "DEVIATION_NOT_APPROVED" | "FINAL_INSPECTION" | "STERILITY_HOLD" | "LABEL_NOT_RECONCILED" | "DHR_STALE";
/** One reason a record is not releasable (409 `DHR_NOT_RELEASABLE`, `details.blocking[]`). */
export interface DhrBlocking {
  code: BlockingCode | string;
  message: string;
  ref_type?: string | null;
  ref_id?: string | null;
  ref_number?: string | null;
}
export interface Releasable {
  ok: boolean;
  blocking: DhrBlocking[];
}

/** A section body: plain JSON (lists of row objects, facts, nested refs); keys per section in the S0 fixture. */
export type DhrSection = Record<string, unknown>;
export type DhrContent = Record<DhrSectionKey, DhrSection>;

export interface DhrVersion {
  id: EntityId;
  version: number;
  status: DhrStatus;
  content_sha256: string;
  section_hashes: Record<string, string>;
  assembled_at: IsoDateTime;
  changed_after_release: boolean;
  reassemble_reason: string | null;
}

/** D2 (stored version) and D3 (live: `id` = "live", `status` = "open", not stored). */
export interface DhrRecord extends DhrSummary {
  item_revision: Record<string, unknown>;
  content: DhrContent;
  content_sha256: string;
  section_hashes: Record<string, string>;
  exceptions: DhrException[];
  signatures: SignatureManifest[];
  versions: DhrVersion[];
  supersedes_id: EntityId | null;
  hold_id: EntityId | null;
  hold_open: boolean;
  dhr_required: boolean;
  releasable: Releasable;
  renditions: RenditionRef[];
  renderer_version: string | null;
  reassemble_reason: string | null;
}
/** D5: one section, its bulk list paged (serials, operation events). */
export interface DhrSectionPage {
  record_id: EntityId;
  section: DhrSectionKey;
  sha256: string;
  data: Record<string, unknown>;
  items: unknown[];
  total: number;
  page: number;
  limit: number;
}
export interface DhrReleaseInput {
  decision: "released" | "rejected";
  ncr_id?: string | null;
  note?: string;
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
  /** created from a DHR exception (unplanned): the exception is dispositioned `deviation` by the creation */
  from_exception_id?: EntityId | null;
}
export interface Deviation {
  id: EntityId;
  number: string;
  kind: DeviationKind;
  title: string;
  description: string;
  scope: DeviationScope;
  risk: DeviationRisk;
  risk_score: number;
  status: DeviationStatus;
  ncr_id: EntityId | null;
  capa_id: EntityId | null;
  author_id: EntityId;
  approved_at: IsoDateTime | null;
  closed_at: IsoDateTime | null;
  outcome: string | null;
  external_ref: string | null;
  sor: "superplanner" | "external";
  /** received qty of lots in scope (4.4) */
  used_qty: number;
  signatures: SignatureManifest[];
  links: (QaLink | Record<string, unknown>)[];
  people: Record<string, string>;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
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
  unit: string;
}
export interface CoaCharacteristic {
  item_id: EntityId | null;
  code: string;
  label: string;
  label_fr: string;
  report: CoaReport;
  /** customer spec override; null = the inspection plan's spec */
  spec: Spec | null;
}
export interface AgreementInput {
  customer: string;
  title: string;
  external_ref: string;
  item_ids: EntityId[];
  coa: { characteristics: CoaCharacteristic[]; statement: string; statement_fr: string; language: CoaLanguage };
  pack: { documents: PackDoc[]; per: "lot" | "shipment" };
  effective_from: IsoDate | null;
}
export interface Agreement extends AgreementInput {
  id: EntityId;
  number: string;
  version: number;
  status: DocState;
  supersedes_id: EntityId | null;
  signatures: SignatureManifest[];
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export type CoaStatus = "draft" | "approved" | "void";
export interface CoaLine {
  code: string;
  label: string;
  label_fr: string;
  report: CoaReport;
  spec: Spec | null;
  spec_source: "customer" | "plan" | "none";
  n: number;
  defects: number;
  mean: number | null;
  min: number | null;
  max: number | null;
  conforms: boolean;
  result_text: string;
}
export interface Coa {
  id: EntityId;
  number: string;
  agreement_id: EntityId;
  agreement_number: string | null;
  agreement_version: number;
  lot_id: EntityId;
  lot_code: string | null;
  item_id: EntityId | null;
  dhr_id: EntityId;
  dhr_number: string | null;
  customer: string;
  demand_line_id: EntityId | null;
  content: {
    lines: CoaLine[];
    statement: string;
    statement_fr?: string;
    language: CoaLanguage;
    lot?: { lot_code: string; expires_on: IsoDate | null };
    item?: { part_number: string; name: string };
    dhr?: { number: string; version: number; content_sha256: string };
  };
  content_sha256: string;
  status: CoaStatus;
  void_reason: string | null;
  rendition: RenditionRef | null;
  signatures: SignatureManifest[];
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
export type PackStatus = "building" | "ready" | "failed";
export interface PackDocument {
  kind: string;
  lot_id: EntityId | null;
  ref_id: EntityId | null;
  filename: string;
  sha256: string;
  size: number;
}
export interface BatchPack {
  id: EntityId;
  number: string;
  agreement_id: EntityId;
  lot_ids: EntityId[];
  customer: string;
  demand_line_id: EntityId | null;
  status: PackStatus;
  documents: PackDocument[];
  rendition: RenditionRef | null;
  manifest_sha256: string | null;
  error: string | null;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

// ---------------------------------------------------------------- 7 UDI
export type DiKind = "base" | "unit_of_use" | "package";
export interface PiFlags {
  lot: boolean;
  serial: boolean;
  expiry: boolean;
  mfg_date: boolean;
}
export type FdaClass = "" | "I" | "II" | "III" | "U";
export type HcClass = "" | "I" | "II" | "III" | "IV";
export type MriSafety = "" | "mr_safe" | "mr_conditional" | "mr_unsafe" | "not_evaluated" | "no_info";
/** GUDID / Health Canada attributes (14.1). */
export interface UdiAttrs {
  brand: string;
  version_model: string;
  catalog_no: string;
  description: string;
  gmdn_code: string;
  gmdn_term: string;
  fda_product_codes: string[];
  fda_class: FdaClass;
  premarket_nos: string[];
  hc_licence_no: string;
  hc_class: HcClass;
  sterile: boolean;
  ster_method: string;
  single_use: boolean;
  rx: boolean;
  kit: boolean;
  combination: boolean;
  mri_safety: MriSafety;
  latex: boolean;
  storage: Record<string, unknown>[];
}
/** U1 PUT `/udi/devices` (create when no record exists for the packaging row; If-Match on update). */
export interface UdiDeviceInput {
  packaging_id: EntityId;
  gtin: string;
  di_kind: DiKind;
  qty_per_package: number;
  contains_gtin: string | null;
  pi_flags: PiFlags;
  attrs: UdiAttrs;
  commercial_distribution_date: IsoDate | null;
}
export interface UdiDevice {
  id: EntityId;
  packaging_id: EntityId;
  item_id: EntityId;
  item_part_number: string | null;
  level: string;
  gtin: string;
  /** labels were printed with this GTIN: it cannot change (409 `UDI_GTIN_IN_USE`) */
  gtin_locked: boolean;
  di_kind: DiKind | string;
  qty_per_package: number;
  contains_gtin: string | null;
  pi_flags: PiFlags;
  attrs: UdiAttrs;
  status: DocState;
  commercial_distribution_date: IsoDate | null;
  signatures: SignatureManifest[];
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
export interface UdiParse {
  ok: boolean;
  symbology: string | null;
  ais: Record<string, string>;
  gtin_check_ok: boolean | null;
  expiry: IsoDate | null;
  production_date: IsoDate | null;
  data: string;
  hri: string;
  errors: string[];
}
export type ExportKind = "gudid" | "hc";
export type ExportFormat = "xlsx" | "csv" | "json";
export interface ExportIssue {
  gtin: string | null;
  element: string | null;
  message: string;
  code?: string | null;
}
export interface UdiExport {
  id: EntityId;
  number: string;
  kind: ExportKind;
  params: { item_ids?: EntityId[] | null; format?: ExportFormat };
  status: JobStatus;
  rule_version: string;
  result: { rows: number; errors: ExportIssue[]; warnings: ExportIssue[] } | null;
  rendition: RenditionRef | null;
  row_version: number;
  created_at: IsoDateTime;
}

// ---------------------------------------------------------------- 7.2 label templates
export type LabelElementKind = "text" | "field" | "barcode" | "box" | "line" | "symbol";
export type Symbology = "gs1_datamatrix" | "gs1_128" | "code128";
export type Ai = "01" | "11" | "17" | "10" | "21";
export const AIS: readonly Ai[] = ["01", "11", "17", "10", "21"];
export interface BarcodeSpec {
  symbology: Symbology;
  module_mm: number;
  ais: Ai[];
  hri: boolean;
}
export interface LabelElement {
  kind: LabelElementKind;
  x_mm: number;
  y_mm: number;
  w_mm: number;
  h_mm: number;
  rotation: 0 | 90 | 180 | 270;
  font_pt: number;
  bold: boolean;
  lang: "en" | "fr" | null;
  text: string | null;
  field: string | null;
  barcode: BarcodeSpec | null;
  /** `symbol`: SVG path data only */
  path: string | null;
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
  level: string;
  width_mm: number;
  height_mm: number;
  dpi: 203 | 300 | 600;
  languages: ("en" | "fr")[];
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
  /** validation findings (LBL_MODULE_TOO_SMALL ...) */
  issues: { code?: string; message?: string; element?: number; [k: string]: unknown }[];
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
export interface LabelAssignment {
  item_id: EntityId;
  level: string;
  customer: string | null;
  template_code: string;
}
export interface PrinterInput {
  code: string;
  name: string;
  kind: "zpl_raw" | "download";
  host: string;
  port: number;
  dpi: 203 | 300 | 600;
  line_id: EntityId | null;
  active: boolean;
}
export interface Printer extends PrinterInput {
  id: EntityId;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
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
  job_id: EntityId;
  kind: PrintEventKind;
  qty: number;
  serials: string[] | null;
  position: ScanPosition | null;
  scan: string | null;
  result: "match" | "mismatch" | null;
  mismatch: Record<string, { expected?: unknown; scanned?: unknown } | unknown> | null;
  reason: string | null;
  actor_id: EntityId;
  at: IsoDateTime;
  client_event_id: string;
}
export interface PrintJobInput {
  item_id: EntityId;
  level: string;
  lot_id: EntityId;
  wo_id: EntityId | null;
  customer?: string | null;
  qty: number;
  output: "pdf" | "zpl";
  target: "download" | "printer";
  printer_id: EntityId | null;
}
export interface PrintJob {
  id: EntityId;
  number: string;
  item_id: EntityId;
  item_part_number: string | null;
  level: string;
  udi_id: EntityId;
  gtin: string;
  lot_id: EntityId;
  lot_code: string | null;
  wo_id: EntityId | null;
  template_id: EntityId;
  template_code: string;
  template_version: number;
  qty: number;
  serials: string[] | null;
  data: Record<string, unknown>;
  data_sha256: string;
  element_string: string;
  hri: string;
  output: "pdf" | "zpl";
  target: "download" | "printer";
  printer_id: EntityId | null;
  status: PrintJobStatus;
  totals: PrintTotals;
  recon_explanation: string | null;
  reconciled_at: IsoDateTime | null;
  /** {first, last, mismatches} (7.4) */
  verify: { first?: boolean; last?: boolean; mismatches?: number };
  events: PrintEvent[];
  signatures: SignatureManifest[];
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
export interface PrintEventInput {
  kind: "printed" | "reprint" | "used" | "destroyed" | "retained" | "unblock";
  qty: number;
  serials?: string[] | null;
  reason?: string | null;
  client_event_id: string;
}
export interface VerifyResult {
  result: "match" | "mismatch";
  mismatch: Record<string, unknown>;
  parsed: UdiParse;
  job: PrintJob;
}

// ---------------------------------------------------------------- 8 validation package
export type PackageKind = "full" | "iq" | "oq" | "pq" | "periodic" | "evidence";
export interface ManifestFile {
  path: string;
  sha256: string;
  size: number;
  kind: string;
}
export interface ValPackage {
  id: EntityId;
  number: string;
  kind: PackageKind;
  params: Record<string, unknown>;
  status: JobStatus | "approved";
  baseline_id: EntityId | null;
  prev_baseline_id: EntityId | null;
  manifest: { files?: ManifestFile[]; baseline_diff?: Record<string, unknown>[]; kind?: string; package?: string; statement?: string; [k: string]: unknown } | null;
  sha256: string | null;
  size: number | null;
  error: string | null;
  signatures: SignatureManifest[];
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
export interface PackageInput {
  kind: "full" | "iq" | "oq" | "pq" | "periodic";
  junit_xml?: string | null;
  label?: string;
}
export type EvidenceKind = "ha_drill" | "load_report" | "ha_rehearsal" | "other";
export interface EvidenceInput {
  kind: EvidenceKind;
  title: string;
  provisional: boolean;
  content: Record<string, unknown>;
}
export interface IqCheck {
  code: string;
  label: string;
  status: "pass" | "fail" | "warn" | "skip";
  detail: string;
  observed: unknown;
  expected: unknown;
}
export interface IqResult {
  plant: string;
  at: IsoDateTime;
  ok: boolean;
  checks: IqCheck[];
}

// ---------------------------------------------------------------- 9 enterprise
export interface ResidencyItem {
  kind: "deployment" | "org" | "archive" | "backup" | "smtp" | "logs" | "ai" | "endpoint" | "assistant";
  name: string;
  region: string | null;
  ok: boolean;
  detail: string;
  exception_signature_id: string | null;
}
export interface Residency {
  org_id: EntityId;
  data_region: string;
  deployment_region: string;
  ok: boolean;
  mismatches: ResidencyItem[];
  items: ResidencyItem[];
}
export interface OrgAuditRow {
  id: number;
  plant: string | null;
  owner_id: EntityId | null;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_id: EntityId | null;
  created_at: IsoDateTime;
  reason: string | null;
  signature_id: string | null;
  details: Record<string, unknown>;
}
export interface OrgAuditPage {
  items: OrgAuditRow[];
  total: number;
  page: number;
  limit: number;
  people?: Record<string, string>;
}
export interface PlantTemplateApplyResult {
  applied: { key: string; count: number }[];
  drafts: { key: string; count: number }[];
  skipped: { key: string; reason: string }[];
}
