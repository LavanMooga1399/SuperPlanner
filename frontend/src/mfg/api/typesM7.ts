/**
 * TypeScript mirror of the M7 contract (docs/M7-DESIGN.md 3, 4, 5-9): electronic signatures, Part 11 controls and
 * the quality module. Field names are the JSON names. `contractExamplesM7.ts` types the documented examples against
 * these declarations, so `tsc` fails when they drift. Shapes not spelled out in the design (preview, step-up status,
 * list filters) are the UI's reading of the design text, recorded in docs/M7-DESIGN.md 14 (U notes).
 */
import type { EntityId, IsoDate, IsoDateTime, ItemRef, Page } from "./types";

// ---------------------------------------------------------------- 4 signatures
export type Meaning = "authored" | "reviewed" | "approved" | "released" | "rejected" | "verified" | "performed" | "closed";
export const MEANINGS: readonly Meaning[] = ["authored", "reviewed", "approved", "released", "rejected", "verified", "performed", "closed"];
export type PolicyAuth = "password" | "password_totp";
export type AuthMethod = "password" | "password_totp" | "sso" | "sso_mfa";
export type QaRole = "qa_inspector" | "qa_engineer" | "qa_approver" | "metrology";

/** Signature manifestation (4.2, 11.50): carried by every signed record. */
export interface SignatureManifest {
  id: EntityId;
  meaning: Meaning;
  meaning_label: string;
  signer_legal_name: string;
  signer_username: string;
  signed_at: IsoDateTime;
  /** plant zone with UTC offset, e.g. "2026-11-23T14:05:12-05:00" */
  signed_at_local: IsoDateTime;
  /** e.g. "EST" (display only) */
  zone_abbr?: string | null;
  auth_method: AuthMethod;
  step: number;
  status: "valid" | "superseded";
  content_matches_current: boolean;
}

/** E4: a signature row with its link to the record. */
export interface SignatureRecord extends SignatureManifest {
  record_type: string;
  record_id: EntityId;
  record_number?: string | null;
  record_version: number;
  action: string;
  policy_id: EntityId | null;
  policy_version: number | null;
  content_hash: string;
  comment: string | null;
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
  id: EntityId;
  record_type: string;
  action: string;
  /** "final" / "incoming,in_process" for scoped defaults (inspection_lot.decide) */
  scope?: string | null;
  steps: PolicyStep[];
  auth: PolicyAuth;
  distinct_signers: boolean;
  exclude_author: boolean;
  version: number;
  /** fixed actions (esig_policy.update, plant.part11_on) keep at least one step */
  fixed: boolean;
  row_version: number;
  updated_at: IsoDateTime | null;
  signatures: SignatureManifest[];
}

export interface PolicyInput {
  steps: PolicyStep[];
  auth: PolicyAuth;
  distinct_signers: boolean;
  exclude_author: boolean;
  signature?: SignatureInput;
}

/** The next step a signer completes (E3, 202 answers). */
export interface NextStep {
  step: number;
  /** a fixed meaning, or a choice (inspection_lot.decide: released | rejected) */
  meanings: Meaning[];
  roles: string[];
  auth: PolicyAuth;
  /** people of this plant who may sign it (display names), when known */
  eligible?: string[];
}

export interface PreviewLine {
  label: string;
  value: string;
}

/** E3 `GET /mfg/esig/preview`: what will be signed. */
export interface EsigPreview {
  record_type: string;
  record_id: EntityId;
  record_number: string | null;
  record_version: number;
  action: string;
  /** Part 11 mode on and a policy for (record_type, action) */
  required: boolean;
  content_hash: string;
  /** human summary of the canonical content (server-rendered, plant language) */
  summary: PreviewLine[];
  content: Record<string, unknown>;
  policy: Pick<EsigPolicy, "id" | "version" | "auth" | "steps" | "distinct_signers" | "exclude_author"> | null;
  next_step: NextStep | null;
  signatures: SignatureManifest[];
  signer: SignerState;
  /** reasons this person cannot sign this step now (ESIG_ROLE, ESIG_SAME_SIGNER, ESIG_AUTHOR, ESIG_NOT_ENROLLED) */
  blockers: { code: string; message: string }[];
}

export interface SignerState {
  user_id: EntityId;
  username: string;
  legal_name: string | null;
  enrolled: boolean;
  locked_until: IsoDateTime | null;
  /** SSO users sign with an OIDC step-up (or local signing credentials when the server allows them) */
  sso: boolean;
  stepup_available: boolean;
  local_credentials: boolean;
  totp_enabled: boolean;
}

/** 202 of a multi-step policy (4.2 step 8). */
export interface PendingSignatures {
  status: "pending_signatures";
  record_type: string;
  record_id: EntityId;
  signatures: SignatureManifest[];
  next_step: NextStep | null;
}

/** P1 `GET /auth/esig/status`. */
export interface EsigStatus extends SignerState {
  enrolled_at: IsoDateTime | null;
  ack_version: string | null;
  /** the acknowledgement text to accept, per language */
  ack_text: Record<string, string>;
  current_ack_version: string;
  revoked_at: IsoDateTime | null;
}

export interface EnrollInput {
  legal_name: string;
  password?: string;
  stepup_token?: string;
  acknowledgement: true;
}

export interface VerifyResult {
  mac_ok: boolean;
  chain_ok: boolean;
  content_hash_ok: boolean;
  content_matches_current: boolean;
  record_version_signed: number;
  record_version_current: number | null;
}

export interface FieldChange {
  path: string;
  old: unknown;
  new: unknown;
  old_sha256?: string | null;
  new_sha256?: string | null;
}

/** E6 `GET /mfg/audit/record`: one event of the record's trail. */
export interface RecordAuditEvent {
  id: number;
  at: IsoDateTime;
  at_local?: IsoDateTime | null;
  actor: { id: string | null; name: string; username?: string | null } | null;
  action: string;
  record_version: number | null;
  changes: FieldChange[] | null;
  reason: string | null;
  signature: SignatureManifest | null;
}

export interface AttachmentRef {
  id: EntityId;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  uploaded_by: string | null;
  uploaded_at: IsoDateTime;
}

export type LinkType = "ncr" | "capa" | "complaint" | "field_action" | "eco" | "inspection_lot" | "equipment";

export interface QaLink {
  id: EntityId;
  to_type: LinkType;
  to_id: EntityId;
  to_number: string | null;
  to_title: string | null;
  to_status: string | null;
  /** "from" when this record is the link's source */
  direction: "from" | "to";
  created_at: IsoDateTime;
}

/** E7 Part 11 package of one record. */
export interface Part11Package {
  record: Record<string, unknown>;
  record_type: string;
  record_number?: string | null;
  signatures: SignatureManifest[];
  audit: RecordAuditEvent[];
  attachments: Pick<AttachmentRef, "id" | "filename" | "size" | "sha256">[];
  links: QaLink[];
  generated_at: IsoDateTime;
  generated_by: string;
  package_sha256: string;
}

export interface Part11Export {
  id: EntityId;
  status: "queued" | "running" | "succeeded" | "failed";
  params: { from: IsoDate; to: IsoDate; record_types: string[] };
  manifest: { counts?: Record<string, number>; files?: { name: string; sha256: string; size: number }[] } | null;
  sha256: string | null;
  error: { code: string; message: string } | null;
  requested_by: string | null;
  created_at: IsoDateTime;
  finished_at: IsoDateTime | null;
}

/** E11 `GET /mfg/plant/part11`. */
export interface Part11Mode {
  enabled: boolean;
  enabled_at: IsoDateTime | null;
  enabled_by: string | null;
  signatures: SignatureManifest[];
  /** readiness hints shown before switching on */
  checks: { code: string; ok: boolean; message: string }[];
  row_version: number;
}

export interface MetaTime {
  app_utc: IsoDateTime;
  db_utc: IsoDateTime;
  skew_ms: number;
}

// ---------------------------------------------------------------- QA common
export interface QaRecordBase {
  id: EntityId;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  signatures: SignatureManifest[];
  links: QaLink[];
  attachments: AttachmentRef[];
}

export type Severity3 = "critical" | "major" | "minor";
export interface UserRef {
  id: EntityId;
  name: string;
}
export interface SupplierRef {
  id: EntityId;
  code: string;
  name: string;
}
export interface LotRef {
  id: EntityId;
  lot_code: string;
}

export interface QaSettings {
  defect_codes: { code: string; name: string; severity: Severity3 }[];
  mrb_location_id: EntityId | null;
  cal_due_warning_days: number;
  inspection_due_hours: { incoming: number; in_process: number; final: number };
  reportability_rules: { regime: string; event_type: string; days: number }[];
  capa_sor: "superplanner" | "external";
  complaint_sor: "superplanner" | "external";
  final_release_role: string;
  row_version: number;
}

// ---------------------------------------------------------------- 5.1 schemes and plans
export type DocStatus = "draft" | "approved" | "obsolete";
export type SchemeKind = "fixed" | "percent" | "full" | "table";
export interface SamplingPlanCell {
  n: number;
  ac: number;
  re: number;
}
export interface SchemeTable {
  levels: string[];
  lot_size_ranges: { min: number; max: number | null; letters: Record<string, string> }[];
  plans: { normal: Record<string, Record<string, SamplingPlanCell>>; tightened: Record<string, Record<string, SamplingPlanCell>> };
  switching?: { to_tightened: { rejected: number; of_last: number }; to_normal: { consecutive_accepted: number } };
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
  note: string | null;
  /** plans using the scheme */
  used_by: number;
}
export type SchemeInput = Pick<SamplingScheme, "code" | "name" | "kind" | "fixed_n" | "percent" | "table" | "switching" | "note">;

export type InspectionScope = "incoming" | "in_process" | "final";
export interface Characteristic {
  id: EntityId;
  seq: number;
  code: string;
  name: string;
  kind: "variable" | "attribute";
  severity: Severity3;
  unit: string | null;
  nominal: number | null;
  lsl: number | null;
  usl: number | null;
  method: string | null;
  equipment_class: string | null;
  sample_override: { scheme_id: EntityId; level: string; aql: number } | null;
  destructive: boolean;
}
export type CharacteristicInput = Omit<Characteristic, "id"> & { id?: EntityId };
export interface InspectionPlan extends QaRecordBase {
  number: string;
  version: number;
  item: ItemRef;
  scope: InspectionScope;
  operation_seq: number | null;
  supplier: SupplierRef | null;
  customer: string | null;
  scheme: { id: EntityId; code: string; name: string; kind: SchemeKind };
  inspection_level: string;
  aql: { critical: number; major: number; minor: number };
  status: DocStatus;
  effective_from: IsoDate | null;
  supersedes_id: EntityId | null;
  approved_at: IsoDateTime | null;
  note: string | null;
  characteristics: Characteristic[];
}
export interface PlanInput {
  item_id: EntityId;
  scope: InspectionScope;
  operation_seq: number | null;
  supplier_id: EntityId | null;
  customer: string | null;
  scheme_id: EntityId;
  inspection_level: string;
  aql: { critical: number; major: number; minor: number };
  effective_from: IsoDate | null;
  note: string | null;
  characteristics: CharacteristicInput[];
}
/** sampling preview for a lot size (Q-plan editor), from `GET /mfg/qa/schemes/{id}/resolve` */
export interface SamplingResolve {
  lot_size: number;
  level: string;
  aql: number;
  state: "normal" | "tightened";
  letter: string | null;
  n: number;
  ac: number;
  re: number;
  full: boolean;
}

// ---------------------------------------------------------------- 5.2 inspection lots
export type LotStatus = "open" | "in_progress" | "ready" | "accepted" | "rejected" | "cancelled";
export interface CharSampling {
  characteristic_id: EntityId;
  n: number;
  ac: number;
  re: number;
  severity_state: "normal" | "tightened";
}
export interface CharVerdict {
  characteristic_id: EntityId;
  entered: number;
  defective: number;
  verdict: "pending" | "accept" | "reject";
}
export interface InspectionResult {
  id: EntityId;
  characteristic_id: EntityId;
  sample_no: number;
  value: number | null;
  passed: boolean | null;
  defects: number | null;
  defective: boolean;
  equipment: { id: EntityId; code: string } | null;
  note: string | null;
  entered_by: string | null;
  entered_at: IsoDateTime;
  corrects_result_id: EntityId | null;
  superseded: boolean;
}
export interface InspectionLot extends QaRecordBase {
  number: string;
  plan: { id: EntityId; number: string; version: number };
  scope: InspectionScope;
  item: ItemRef;
  lot: LotRef | null;
  wo: { id: EntityId; number: string } | null;
  wo_operation: { id: EntityId; seq: number; name: string } | null;
  supplier: SupplierRef | null;
  po_number: string | null;
  lot_size: number;
  sampling: CharSampling[];
  status: LotStatus;
  verdict: { lot: "pending" | "accept" | "reject"; characteristics: CharVerdict[] } | null;
  decision: "accept" | "reject" | null;
  decided_by: string | null;
  decided_at: IsoDateTime | null;
  ncr: { id: EntityId; number: string } | null;
  due_at: IsoDateTime;
  overdue: boolean;
  hold: boolean;
}
export interface InspectionLotDetail extends InspectionLot {
  characteristics: Characteristic[];
  results: InspectionResult[];
}
export interface ResultEntry {
  characteristic_id: EntityId;
  sample_no: number;
  value?: number;
  passed?: boolean;
  defects?: number;
  equipment_id?: EntityId;
  note?: string;
  corrects_result_id?: EntityId;
  reason?: string;
}
export interface DecisionInput {
  decision: "accept" | "reject";
  note: string;
  ncr_id?: EntityId | null;
  signature?: SignatureInput;
}

// ---------------------------------------------------------------- 5.3 holds
export type HoldSource = "inspection" | "ncr" | "recall" | "field_action" | "manual";
export interface Hold {
  id: EntityId;
  row_version: number;
  lot: LotRef | null;
  serial: { id: EntityId; serial: string } | null;
  item: ItemRef;
  source: HoldSource;
  source_id: EntityId | null;
  source_number: string | null;
  reason: string;
  placed_by: string | null;
  placed_at: IsoDateTime;
  released_by: string | null;
  released_at: IsoDateTime | null;
  signatures: SignatureManifest[];
}

// ---------------------------------------------------------------- 6 NCR
export type NcrStatus = "draft" | "open" | "proposed" | "approved" | "implemented" | "closed" | "cancelled";
export type DispositionKind = "scrap" | "rework" | "use_as_is" | "return_to_supplier";
export interface Disposition {
  id?: EntityId;
  line_no: number;
  kind: DispositionKind;
  qty: number;
  location_id: EntityId | null;
  rework_routing_id: EntityId | null;
  rework_to_seq: number | null;
  instructions: string | null;
  justification: string | null;
  implemented_at?: IsoDateTime | null;
  refs?: { posting_ids?: EntityId[]; wo?: { id: EntityId; number: string; status: string } | null; floor_event_id?: EntityId | null } | null;
}
export interface Ncr extends QaRecordBase {
  number: string;
  title: string;
  source: "inspection" | "floor" | "complaint" | "manual" | "receiving";
  severity: Severity3;
  item: ItemRef;
  lot: LotRef | null;
  serials: string[];
  supplier: SupplierRef | null;
  wo: { id: EntityId; number: string } | null;
  wo_operation: { id: EntityId; seq: number; name: string } | null;
  inspection_lot: { id: EntityId; number: string } | null;
  complaint: { id: EntityId; number: string } | null;
  place: "stock" | "wip";
  qty_nc: number;
  defect_codes: string[];
  description: string;
  containment: string | null;
  investigation: string | null;
  status: NcrStatus;
  capa_required: boolean;
  author: UserRef | null;
  closed_at: IsoDateTime | null;
  external_ref: string | null;
  dispositions: Disposition[];
  /** pending step signatures and who signs next (multi-step approve) */
  next_step: NextStep | null;
}
export interface NcrInput {
  title: string;
  severity: Severity3;
  item_id: EntityId;
  lot_id: EntityId | null;
  serials: string[];
  supplier_id: EntityId | null;
  place: "stock" | "wip";
  qty_nc: number;
  defect_codes: string[];
  description: string;
  containment: string | null;
  investigation: string | null;
  capa_required: boolean;
}

// ---------------------------------------------------------------- 7 CAPA, complaints, field actions
export type CapaStatus = "draft" | "investigation" | "plan_approval" | "implementation" | "effectiveness_check" | "closed" | "cancelled";
export interface CapaAction {
  id: EntityId;
  seq: number;
  kind: "correction" | "corrective" | "preventive";
  description: string;
  owner: UserRef | null;
  due_on: IsoDate | null;
  status: "open" | "done" | "cancelled";
  done_at: IsoDateTime | null;
  evidence: string | null;
  eco: { id: EntityId; number: string } | null;
  row_version: number;
}
export interface Capa extends QaRecordBase {
  number: string;
  title: string;
  kind: "corrective" | "preventive";
  problem: string;
  risk: { severity: number; occurrence: number; level: "low" | "medium" | "high" } | null;
  owner: UserRef | null;
  due_on: IsoDate | null;
  root_cause: { method: string; text: string } | null;
  effectiveness: { criteria: string; check_due_on: IsoDate | null; result: "effective" | "not_effective" | null; evidence: string | null } | null;
  status: CapaStatus;
  external_ref: string | null;
  actions: CapaAction[];
  overdue: boolean;
}
export type CapaInput = Pick<Capa, "title" | "kind" | "problem" | "risk" | "due_on" | "root_cause" | "effectiveness" | "external_ref"> & { owner_user_id: EntityId | null };

export type ComplaintStatus = "open" | "investigation" | "closed";
export interface Complaint extends QaRecordBase {
  number: string;
  received_on: IsoDate;
  aware_on: IsoDate;
  channel: string;
  customer: string;
  country: string | null;
  item: ItemRef | null;
  lots: { code: string; lot_id: EntityId | null }[];
  serials: { code: string; serial_id: EntityId | null }[];
  qty_affected: number | null;
  description: string;
  event_type: "death" | "serious_injury" | "malfunction" | "other";
  reportability: { assessed: boolean; reportable: boolean | null; regimes: { regime: string; due_on: IsoDate | null; report_ref: string | null }[] } | null;
  investigation: string | null;
  status: ComplaintStatus;
  external_ref: string | null;
  next_report_due: IsoDate | null;
}
export type ComplaintInput = Pick<Complaint, "received_on" | "aware_on" | "channel" | "customer" | "country" | "qty_affected" | "description" | "event_type" | "investigation" | "external_ref"> & {
  item_id: EntityId | null;
  lots: string[];
  serials: string[];
  reportability?: Complaint["reportability"];
};

export type FieldActionStatus = "draft" | "approved" | "in_progress" | "completed" | "closed" | "cancelled";
export type UnitStatus = "pending" | "notified" | "acknowledged" | "returned" | "corrected" | "destroyed" | "not_reachable";
export interface FieldAction extends QaRecordBase {
  number: string;
  title: string;
  kind: "recall" | "correction" | "removal" | "safety_notice" | "software_update";
  class: string | null;
  regimes: string[];
  strategy: string | null;
  recall: { id: EntityId; number: string; name: string };
  status: FieldActionStatus;
  effectiveness: { overall: number; units: number; by_customer: { customer: string; units: number; done: number; share: number }[]; by_status: Partial<Record<UnitStatus, number>> };
}
export type FieldActionInput = Pick<FieldAction, "title" | "kind" | "class" | "regimes" | "strategy"> & { recall_id: EntityId };
export interface FieldActionUnit {
  id: EntityId;
  kind: "serial" | "lot";
  code: string;
  item: { id: EntityId; part_number: string };
  customer: string | null;
  demand_order: string | null;
  qty: number;
  status: UnitStatus;
  note: string | null;
  updated_by: string | null;
  updated_at: IsoDateTime | null;
}

// ---------------------------------------------------------------- 8 equipment
export type EquipmentKind = "gauge" | "instrument" | "fixture" | "tool" | "line_equipment" | "chamber";
export interface Equipment extends QaRecordBase {
  code: string;
  name: string;
  kind: EquipmentKind;
  equipment_class: string | null;
  line: { id: EntityId; code: string; name: string } | null;
  tool_pool: { id: EntityId; code: string; name: string } | null;
  serial_no: string | null;
  manufacturer: string | null;
  location: string | null;
  status: "active" | "out_of_service" | "retired";
  calibration_required: boolean;
  interval_days: number | null;
  grace_days: number;
  last_calibrated_on: IsoDate | null;
  due_on: IsoDate | null;
  procedure_ref: string | null;
  provider: "internal" | "external" | null;
  /** Valid(e, today) of 8 */
  valid: boolean;
  /** "ok" | "due_soon" (inside cal_due_warning_days) | "overdue" | "in_grace" | "not_required" */
  cal_state: "ok" | "due_soon" | "in_grace" | "overdue" | "not_required";
}
export type EquipmentInput = Pick<
  Equipment,
  "code" | "name" | "kind" | "equipment_class" | "serial_no" | "manufacturer" | "location" | "calibration_required" | "interval_days" | "grace_days" | "procedure_ref" | "provider"
> & { line_id: EntityId | null; tool_pool_id: EntityId | null };
export interface Calibration {
  id: EntityId;
  performed_on: IsoDate;
  performed_by: string | null;
  provider_name: string | null;
  result: "pass" | "adjusted_pass" | "fail";
  as_found: string | null;
  as_left: string | null;
  certificate_ref: string | null;
  next_due_on: IsoDate | null;
  signatures: SignatureManifest[];
  attachments: AttachmentRef[];
}
export interface CalibrationInput {
  performed_on: IsoDate;
  provider_name: string | null;
  result: Calibration["result"];
  as_found: string | null;
  as_left: string | null;
  certificate_ref: string | null;
  next_due_on: IsoDate | null;
  signature?: SignatureInput;
}
export interface EquipmentImpact {
  since: IsoDate | null;
  lots: { inspection_lot: { id: EntityId; number: string }; item: string; lot_code: string | null; results: number; decision: "accept" | "reject" | null; decided_at: IsoDateTime | null; released: boolean }[];
}

// ---------------------------------------------------------------- lists
export interface QaPage<T> extends Page<T> {
  counts?: Record<string, number>;
}
export interface QaListQuery {
  q?: string;
  status?: string;
  sort?: string;
  limit?: number;
  offset?: number;
  [k: string]: string | number | boolean | undefined;
}
