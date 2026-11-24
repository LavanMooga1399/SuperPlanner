/**
 * TypeScript mirror of the M7 contract as frozen at S0 (`backend/superplanner/esig/model.py`, `qa/model.py`,
 * fixture `qa/fixtures/example_m7.json`): electronic signatures, Part 11 controls and the quality module. Field names
 * are the JSON names. `contractExamplesM7.ts` types the fixture against these declarations, so `tsc` fails on drift.
 */
import type { IsoDate, IsoDateTime } from "./types";

// ---------------------------------------------------------------- 4 signatures (esig/model.py)
export type Meaning = "authored" | "reviewed" | "approved" | "released" | "rejected" | "verified" | "performed" | "closed";
export const MEANINGS: readonly Meaning[] = ["authored", "reviewed", "approved", "released", "rejected", "verified", "performed", "closed"];
export type PolicyAuth = "password" | "password_totp";
export type AuthMethod = "password" | "password_totp" | "sso" | "sso_mfa";

export interface SignatureManifest {
  id: string;
  meaning: Meaning;
  meaning_label: string;
  signer_legal_name: string;
  signer_username: string;
  signed_at: IsoDateTime;
  /** plant time as text: "2026-11-23 14:05:12 EST (UTC-05:00)" */
  signed_at_local: string;
  auth_method: AuthMethod;
  action: string;
  step: number;
  status: "valid" | "superseded";
  record_version: number;
  comment: string;
  content_matches_current: boolean;
}

export interface SignatureInput {
  meaning: Meaning;
  content_hash: string;
  username: string;
  password?: string;
  totp_code?: string;
  stepup_token?: string;
  comment?: string;
}

export interface PolicyStep {
  meaning: Meaning;
  roles: string[];
}

export interface EsigPolicy {
  id: string;
  record_type: string;
  action: string;
  steps: PolicyStep[];
  auth: PolicyAuth;
  distinct_signers: boolean;
  exclude_author: boolean;
  version: number;
  fixed: boolean;
  row_version: number;
  updated_at: IsoDateTime;
  signatures: SignatureManifest[];
}

export interface PolicyInput {
  steps: PolicyStep[];
  auth: PolicyAuth;
  distinct_signers: boolean;
  exclude_author: boolean;
  signature?: SignatureInput;
}

export interface NextStep {
  step: number;
  meanings: Meaning[];
  roles: string[];
  auth: PolicyAuth;
  /** the caller holds a step role and is not excluded */
  can_sign: boolean;
  /** ESIG_ROLE | ESIG_SAME_SIGNER | ESIG_AUTHOR | ESIG_NOT_ENROLLED */
  blocked_reason: string | null;
}

export interface PreviewSigner {
  enrolled: boolean;
  legal_name: string | null;
  locked_until: IsoDateTime | null;
  methods: AuthMethod[];
  username: string;
}

/** E3 `GET /mfg/esig/preview`. */
export interface EsigPreview {
  record_type: string;
  record_id: string;
  action: string;
  record_version: number;
  content_hash: string;
  content: Record<string, unknown>;
  summary: { label: string; value: string }[];
  required: boolean;
  part11_mode: boolean;
  policy: EsigPolicy | null;
  next_step: NextStep | null;
  signatures: SignatureManifest[];
  signer: PreviewSigner;
  legal_statement: string;
}

export interface PendingSignatures {
  status: "pending_signatures";
  record_type: string;
  record_id: string;
  signatures: SignatureManifest[];
  next_step: NextStep | null;
}

export interface EnrollInput {
  legal_name: string;
  password?: string;
  stepup_token?: string;
  acknowledgement: true;
  signing_password?: string;
}

export interface EsigStatus {
  user_id: string;
  username: string;
  enrolled: boolean;
  legal_name: string | null;
  enrolled_at: IsoDateTime | null;
  ack_version: string | null;
  revoked_at: IsoDateTime | null;
  locked_until: IsoDateTime | null;
  methods: AuthMethod[];
  totp_enabled: boolean;
  sso_user: boolean;
  local_credentials: boolean;
  can_sign: boolean;
  /** {version, en, "fr-CA"} */
  acknowledgement: Record<string, string>;
}

export interface VerifyResult {
  signature_id: string;
  mac_ok: boolean;
  chain_ok: boolean;
  content_hash_ok: boolean;
  content_matches_current: boolean;
  record_version_signed: number;
  record_version_current: number | null;
  current_hash: string | null;
}

export interface FieldChange {
  path: string;
  old?: unknown;
  new?: unknown;
  old_sha256?: string | null;
  new_sha256?: string | null;
}

export interface RecordAuditEvent {
  id: number;
  at: IsoDateTime;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  record_version: number | null;
  reason: string | null;
  changes: FieldChange[];
  signature: SignatureManifest | null;
  details: Record<string, unknown>;
}

export interface RecordAuditPage {
  entity_type: string;
  entity_id: string;
  items: RecordAuditEvent[];
  total: number;
  limit: number;
  offset: number;
}

export interface Part11Mode {
  enabled: boolean;
  enabled_at: IsoDateTime | null;
  enabled_by: string | null;
  signatures: SignatureManifest[];
  esig_enabled: boolean;
  secrets_configured: boolean;
  clock_skew_ms: number | null;
  max_clock_skew_ms: number;
}

export interface Part11Package {
  record_type: string;
  record_id: string;
  record: Record<string, unknown>;
  signatures: SignatureManifest[];
  audit: RecordAuditEvent[];
  attachments: { id: string; filename: string; size: number; sha256: string }[];
  links: QaLink[];
  generated_at: IsoDateTime;
  generated_by: string;
  package_sha256: string;
}

export interface Part11Export {
  id: string;
  params: { from?: IsoDate; to?: IsoDate; record_types?: string[] };
  status: "queued" | "running" | "completed" | "failed";
  manifest: { counts?: Record<string, number>; [k: string]: unknown } | null;
  sha256: string | null;
  error: string | null;
  requested_by: string;
  created_at: IsoDateTime;
  finished_at: IsoDateTime | null;
  download_url: string | null;
}

export interface MetaTime {
  app_utc: IsoDateTime;
  db_utc: IsoDateTime;
  skew_ms: number;
  max_skew_ms: number;
  ok: boolean;
}

// ---------------------------------------------------------------- QA common (qa/model.py)
export interface AttachmentRef {
  id: string;
  entity_type: string;
  entity_id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  uploaded_by: string;
  uploaded_at: IsoDateTime;
}
export type LinkType = "ncr" | "capa" | "complaint" | "field_action" | "eco" | "inspection_lot" | "equipment";
export interface QaLink {
  id: string;
  from_type: string;
  from_id: string;
  to_type: string;
  to_id: string;
  /** number of the other side */
  label: string | null;
  created_by: string;
  created_at: IsoDateTime;
}
export interface QaRecordBase {
  id: string;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  signatures: SignatureManifest[];
  links: QaLink[];
  attachments: AttachmentRef[];
}
export interface QaItemRef {
  id: string;
  part_number: string;
  revision: string;
  name: string;
}
export type Severity3 = "critical" | "major" | "minor";
export type Scope = "incoming" | "in_process" | "final";
export type DocStatus = "draft" | "approved" | "obsolete";
export const LEVELS = ["S-1", "S-2", "S-3", "S-4", "I", "II", "III"] as const;

export interface DefectCode {
  code: string;
  name: string;
  severity: Severity3;
}
export interface ReportabilityRule {
  regime: string;
  event_type: "all" | "death" | "serious_injury" | "malfunction" | "other";
  days: number;
}
export interface QaSettingsInput {
  defect_codes: DefectCode[];
  mrb_location_id: string | null;
  cal_due_warning_days: number;
  inspection_due_hours: { incoming: number; in_process: number; final: number };
  reportability_rules: ReportabilityRule[];
  capa_sor: "superplanner" | "external";
  complaint_sor: "superplanner" | "external";
  final_release_role: "qa_approver" | "qa_engineer" | "qa_inspector";
}
export interface QaSettings extends QaSettingsInput {
  row_version: number;
}

// ---------------------------------------------------------------- schemes
export interface SamplePlan {
  n: number;
  ac: number;
  re: number;
}
export interface SchemeTable {
  levels: string[];
  lot_size_ranges: { min: number; max: number | null; letters: Record<string, string> }[];
  plans: Record<string, Record<string, Record<string, SamplePlan>>>;
  switching?: Record<string, Record<string, number>>;
}
export type SchemeKind = "fixed" | "percent" | "full" | "table";
export interface SchemeInput {
  code: string;
  name: string;
  kind: SchemeKind;
  fixed_n: number | null;
  percent: number | null;
  table: SchemeTable | null;
  switching: boolean;
  note: string;
}
export interface SamplingScheme extends QaRecordBase {
  code: string;
  name: string;
  kind: SchemeKind;
  fixed_n: number | null;
  percent: number | null;
  table: SchemeTable | null;
  switching: boolean;
  status: DocStatus;
  approved_at: IsoDateTime | null;
  note: string;
}
export interface SamplingPreview {
  lot_size: number;
  level: string;
  aql: string;
  state: string;
  n: number;
  ac: number;
  re: number;
  full: boolean;
}

// ---------------------------------------------------------------- plans
export interface CharacteristicInput {
  id?: string | null;
  seq: number;
  code: string;
  name: string;
  kind: "variable" | "attribute";
  severity: Severity3;
  unit: string | null;
  nominal: number | null;
  lsl: number | null;
  usl: number | null;
  method: string;
  equipment_class: string | null;
  sample_override: { scheme_id: string; level: string; aql: string } | null;
  destructive: boolean;
}
export interface Characteristic extends CharacteristicInput {
  id: string;
}
export interface PlanInput {
  name: string;
  item_id: string;
  scope: Scope;
  operation_seq: number | null;
  supplier_id: string | null;
  customer: string | null;
  scheme_id: string;
  inspection_level: string;
  aql: Record<Severity3, string>;
  effective_from: IsoDate | null;
  note: string;
  characteristics: CharacteristicInput[];
}
export interface InspectionPlan extends QaRecordBase {
  number: string;
  version: number;
  name: string;
  item_id: string;
  item: QaItemRef | null;
  scope: Scope;
  operation_seq: number | null;
  supplier_id: string | null;
  customer: string | null;
  scheme_id: string;
  scheme_code: string | null;
  inspection_level: string;
  aql: Record<string, string>;
  status: DocStatus;
  effective_from: IsoDate | null;
  supersedes_id: string | null;
  approved_at: IsoDateTime | null;
  note: string;
  characteristics: Characteristic[];
}

// ---------------------------------------------------------------- inspection lots
export type LotStatus = "open" | "in_progress" | "ready" | "accepted" | "rejected" | "cancelled";
export type Verdict = "pending" | "accept" | "reject";
export interface InspectionLotInput {
  plan_id: string;
  lot_id: string | null;
  wo_id: string | null;
  lot_size: number;
  hold: boolean;
  note: string;
}
export interface ResultEntry {
  characteristic_id: string;
  sample_no: number;
  value?: number | null;
  passed?: boolean | null;
  defects?: number | null;
  equipment_id?: string | null;
  note?: string;
  corrects_result_id?: string | null;
  reason?: string | null;
}
export interface InspectionResult {
  id: string;
  characteristic_id: string;
  sample_no: number;
  value: number | null;
  passed: boolean;
  defects: number;
  equipment_id: string | null;
  note: string;
  reason: string | null;
  entered_by: string;
  entered_at: IsoDateTime;
  corrects_result_id: string | null;
  superseded: boolean;
}
export interface CharVerdict {
  characteristic_id: string;
  code: string;
  n: number;
  ac: number;
  re: number;
  entered: number;
  defective: number;
  verdict: Verdict;
}
export interface LotVerdict {
  verdict: Verdict;
  characteristics: CharVerdict[];
}
export interface CharSampling {
  n: number;
  ac: number;
  re: number;
  aql?: string;
  severity_state?: string;
}
export interface InspectionLot extends QaRecordBase {
  number: string;
  plan_id: string;
  plan_number: string | null;
  plan_version: number;
  scope: Scope;
  item_id: string;
  item: QaItemRef | null;
  lot_id: string | null;
  lot_code: string | null;
  wo_id: string | null;
  wo_number: string | null;
  wo_operation_id: string | null;
  operation_seq: number | null;
  posting_id: string | null;
  supplier_id: string | null;
  customer: string | null;
  lot_size: number;
  /** characteristic id -> sampling */
  sampling: Record<string, CharSampling>;
  status: LotStatus;
  verdict: LotVerdict | null;
  decision: "accept" | "reject" | null;
  decided_by: string | null;
  decided_at: IsoDateTime | null;
  decision_note: string;
  ncr_id: string | null;
  hold: boolean;
  source: string;
  due_at: IsoDateTime | null;
  overdue: boolean;
  characteristics: Characteristic[];
  results: InspectionResult[];
}
export interface ResultsBatchResponse {
  inspection_lot_id: string;
  client_batch_id: string;
  accepted: number;
  replayed: boolean;
  results: InspectionResult[];
  verdict: LotVerdict;
  status: LotStatus;
  row_version: number;
}
export interface DecisionInput {
  decision: "accept" | "reject";
  note: string;
  ncr_id?: string | null;
  signature?: SignatureInput;
}

// ---------------------------------------------------------------- holds
export type HoldSource = "inspection" | "ncr" | "recall" | "field_action" | "manual";
export interface Hold extends QaRecordBase {
  lot_id: string | null;
  lot_code: string | null;
  serial_id: string | null;
  serial: string | null;
  item_id: string;
  item: QaItemRef | null;
  source: HoldSource;
  source_id: string | null;
  source_number: string | null;
  reason: string;
  placed_by: string;
  placed_at: IsoDateTime;
  released_by: string | null;
  released_at: IsoDateTime | null;
  release_signature_id: string | null;
  release_note: string;
  open: boolean;
}

// ---------------------------------------------------------------- NCR
export type NcrStatus = "draft" | "open" | "proposed" | "approved" | "implemented" | "closed" | "cancelled";
export type DispositionKind = "scrap" | "rework" | "use_as_is" | "return_to_supplier";
export type NcrSource = "inspection" | "floor" | "complaint" | "supplier" | "internal" | "audit";
export interface NcrInput {
  title: string;
  source: NcrSource;
  severity: Severity3;
  item_id: string | null;
  lot_id: string | null;
  serial_ids: string[];
  supplier_id: string | null;
  wo_id: string | null;
  complaint_id: string | null;
  location_id: string | null;
  place: "stock" | "wip";
  qty_nc: number;
  defect_codes: string[];
  description: string;
  containment: string;
  investigation: string;
  capa_required: boolean;
  external_ref: string | null;
}
export interface DispositionInput {
  kind: DispositionKind;
  qty: number;
  location_id: string | null;
  rework_routing_id: string | null;
  rework_to_seq: number | null;
  instructions: string;
  justification: string;
}
export interface Disposition extends DispositionInput {
  id: string;
  line_no: number;
  implemented_at: IsoDateTime | null;
  refs: Record<string, unknown>;
}
export interface Ncr extends QaRecordBase {
  number: string;
  title: string;
  source: string;
  severity: Severity3;
  item_id: string | null;
  item: QaItemRef | null;
  lot_id: string | null;
  lot_code: string | null;
  serial_ids: string[];
  supplier_id: string | null;
  wo_id: string | null;
  wo_operation_id: string | null;
  operation_seq: number | null;
  inspection_lot_id: string | null;
  complaint_id: string | null;
  place: "stock" | "wip";
  location_id: string | null;
  qty_nc: number;
  defect_codes: string[];
  description: string;
  containment: string;
  investigation: string;
  status: NcrStatus;
  capa_required: boolean;
  author_id: string;
  closed_at: IsoDateTime | null;
  external_ref: string | null;
  dispositions: Disposition[];
  rework_wos: { id: string; number: string; status: string }[];
  next_actions: string[];
}

// ---------------------------------------------------------------- CAPA
export type CapaStatus = "draft" | "investigation" | "plan_approval" | "implementation" | "effectiveness_check" | "closed" | "cancelled";
export interface CapaRisk {
  severity: number;
  occurrence: number;
  level?: "low" | "medium" | "high" | null;
}
export interface RootCause {
  method: "5_why" | "fishbone" | "fault_tree" | "8d" | "other";
  text: string;
}
export interface Effectiveness {
  criteria: string;
  check_due_on: IsoDate | null;
  result: "effective" | "not_effective" | null;
  evidence: string;
}
export interface CapaInput {
  title: string;
  kind: "corrective" | "preventive";
  problem: string;
  risk: CapaRisk | null;
  owner_user_id: string | null;
  due_on: IsoDate | null;
  root_cause: RootCause | null;
  effectiveness: Effectiveness | null;
  external_ref: string | null;
  external_status?: string | null;
}
export interface CapaActionInput {
  kind: "correction" | "corrective" | "preventive";
  description: string;
  owner_user_id: string | null;
  due_on: IsoDate | null;
  status: "open" | "done" | "cancelled";
  evidence: string;
  eco_id: string | null;
}
export interface CapaAction extends CapaActionInput {
  id: string;
  seq: number;
  done_at: IsoDateTime | null;
  row_version: number;
}
export interface Capa extends QaRecordBase {
  number: string;
  title: string;
  kind: "corrective" | "preventive";
  problem: string;
  risk: CapaRisk | null;
  owner_user_id: string | null;
  due_on: IsoDate | null;
  root_cause: RootCause | null;
  effectiveness: Effectiveness | null;
  status: CapaStatus;
  author_id: string;
  closed_at: IsoDateTime | null;
  external_ref: string | null;
  sor: "superplanner" | "external";
  overdue: boolean;
  actions: CapaAction[];
}

// ---------------------------------------------------------------- complaints
export type ComplaintStatus = "open" | "investigation" | "closed";
export type EventType = "death" | "serious_injury" | "malfunction" | "other";
export type Channel = "phone" | "email" | "web" | "field" | "distributor" | "other";
export interface Reportability {
  assessed: boolean;
  reportable: boolean | null;
  regimes: string[];
  report_ref: string | null;
}
export interface ComplaintInput {
  received_on: IsoDate;
  aware_on: IsoDate;
  channel: Channel;
  customer: string;
  country: string | null;
  item_id: string | null;
  lots: string[];
  serials: string[];
  qty_affected: number | null;
  description: string;
  event_type: EventType;
  reportability: Reportability;
  investigation: string;
  external_ref: string | null;
}
export interface Complaint extends QaRecordBase {
  number: string;
  received_on: IsoDate;
  aware_on: IsoDate;
  channel: Channel;
  customer: string;
  country: string | null;
  item_id: string | null;
  lots: { code: string; lot_id: string | null }[];
  serials: { code: string; serial_id: string | null }[];
  warnings: string[];
  qty_affected: number | null;
  description: string;
  event_type: EventType;
  reportability: Reportability;
  reporting_due: { regime: string; days: number; due_on: IsoDate; overdue: boolean }[];
  investigation: string;
  status: ComplaintStatus;
  author_id: string;
  closed_at: IsoDateTime | null;
  external_ref: string | null;
  sor: "superplanner" | "external";
}

// ---------------------------------------------------------------- field actions
export type FaStatus = "draft" | "approved" | "in_progress" | "completed" | "closed" | "cancelled";
export type FaKind = "recall" | "correction" | "removal" | "safety_notice" | "software_update";
export type UnitStatus = "pending" | "notified" | "acknowledged" | "returned" | "corrected" | "destroyed" | "not_reachable";
export interface FieldActionInput {
  title: string;
  kind: FaKind;
  class: "I" | "II" | "III" | null;
  regimes: string[];
  strategy: string;
  recall_id: string;
}
export type FieldActionUpdate = Omit<FieldActionInput, "recall_id">;
export interface FaShare {
  done: number;
  total: number;
  pct: number;
}
export interface FieldAction extends QaRecordBase {
  number: string;
  title: string;
  kind: FaKind;
  class: string | null;
  regimes: string[];
  strategy: string;
  recall_id: string;
  recall_number: string | null;
  status: FaStatus;
  complete_reason: string | null;
  author_id: string;
  closed_at: IsoDateTime | null;
  units_total: number;
  effectiveness: { overall?: FaShare; by_customer?: (FaShare & { customer: string })[] };
}
export interface FieldActionUnit {
  id: string;
  kind: "serial" | "lot";
  serial_id: string | null;
  lot_id: string | null;
  code: string;
  item_id: string;
  customer: string;
  demand_line_id: string | null;
  qty: number;
  in_stock: boolean;
  status: UnitStatus;
  note: string;
  updated_by: string | null;
  updated_at: IsoDateTime | null;
}

// ---------------------------------------------------------------- equipment
export type EquipmentKind = "gauge" | "instrument" | "fixture" | "tool" | "line_equipment" | "chamber";
export type EquipmentStatus = "active" | "out_of_service" | "retired";
export type DueState = "ok" | "due_soon" | "in_grace" | "overdue" | "not_required" | "out_of_service" | "retired";
export interface EquipmentInput {
  code: string;
  name: string;
  kind: EquipmentKind;
  equipment_class: string;
  line_id: string | null;
  tool_pool_id: string | null;
  serial_no: string;
  manufacturer: string;
  location: string;
  calibration_required: boolean;
  interval_days: number | null;
  grace_days: number;
  due_on: IsoDate | null;
  procedure_ref: string;
  provider: "internal" | "external";
  note: string;
}
export interface Equipment extends QaRecordBase {
  code: string;
  name: string;
  kind: EquipmentKind;
  equipment_class: string;
  line_id: string | null;
  tool_pool_id: string | null;
  serial_no: string;
  manufacturer: string;
  location: string;
  status: EquipmentStatus;
  calibration_required: boolean;
  interval_days: number | null;
  grace_days: number;
  last_calibrated_on: IsoDate | null;
  due_on: IsoDate | null;
  failed_on: IsoDate | null;
  procedure_ref: string;
  provider: string;
  note: string;
  valid: boolean;
  due_state: DueState;
}
export interface CalibrationInput {
  performed_on: IsoDate;
  performed_by: string | null;
  provider_name: string;
  result: "pass" | "adjusted_pass" | "fail";
  as_found: string;
  as_left: string;
  certificate_ref: string;
  next_due_on: IsoDate | null;
  signature?: SignatureInput;
}
export interface Calibration extends QaRecordBase {
  equipment_id: string;
  performed_on: IsoDate;
  performed_by: string | null;
  provider_name: string;
  result: "pass" | "adjusted_pass" | "fail";
  as_found: string;
  as_left: string;
  certificate_ref: string;
  next_due_on: IsoDate | null;
}
export interface EquipmentImpact {
  equipment_id: string;
  since: IsoDate | null;
  results: number;
  inspection_lots: { id: string; number: string; status: string; decision: "accept" | "reject" | null; lot_id: string | null; lot_code: string | null; item_id: string; results: number }[];
}

export interface QaSummary {
  open_lots: number;
  overdue_lots: number;
  open_ncrs: number;
  overdue_capas: number;
  equipment_due: number;
}

// ---------------------------------------------------------------- lists
export interface QaPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export type QaQuery = Record<string, string | number | boolean | undefined>;
