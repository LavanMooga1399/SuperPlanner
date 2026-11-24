/**
 * Labels and status chips of the quality module (M7 10): every status is icon + text, never colour alone. One map
 * per record type; unknown values (a newer server) render as a neutral chip with the raw value.
 */
import { Icon, type IconName } from "../../components/Icon";
import { t, type StringKey } from "../../lib/i18n";
import { fmtDate } from "../lib/format";
import { formatDateTime } from "../../lib/locale";
import type { AuthMethod, Meaning, SignatureManifest } from "../api/typesM7";

export type Tone = "ok" | "warn" | "danger" | "info" | "accent";
interface ChipDef {
  label: StringKey;
  tone: Tone;
  icon: IconName;
}

function chip(map: Record<string, ChipDef>, value: string, testId?: string, extra?: Record<string, string>) {
  const m = map[value];
  return (
    <span className={`badge ${m?.tone ?? "info"}`} data-status={value} data-testid={testId} {...extra}>
      <Icon name={m?.icon ?? "info"} />
      {m ? t(m.label) : value}
    </span>
  );
}
export const labelOf = (map: Record<string, ChipDef>, value: string | null | undefined) => (value ? (map[value] ? t(map[value].label) : value) : "");

export const LOT_STATUS: Record<string, ChipDef> = {
  open: { label: "qa.status.lot.open", tone: "info", icon: "circle" },
  in_progress: { label: "qa.status.lot.inProgress", tone: "accent", icon: "play" },
  ready: { label: "qa.status.lot.ready", tone: "warn", icon: "flag" },
  accepted: { label: "qa.status.lot.accepted", tone: "ok", icon: "check" },
  rejected: { label: "qa.status.lot.rejected", tone: "danger", icon: "x" },
  cancelled: { label: "qa.status.lot.cancelled", tone: "info", icon: "ban" },
};
export const DOC_STATUS: Record<string, ChipDef> = {
  draft: { label: "qa.status.doc.draft", tone: "warn", icon: "file" },
  approved: { label: "qa.status.doc.approved", tone: "ok", icon: "check" },
  obsolete: { label: "qa.status.doc.obsolete", tone: "info", icon: "ban" },
};
export const NCR_STATUS: Record<string, ChipDef> = {
  draft: { label: "qa.status.ncr.draft", tone: "info", icon: "file" },
  open: { label: "qa.status.ncr.open", tone: "warn", icon: "alert" },
  proposed: { label: "qa.status.ncr.proposed", tone: "accent", icon: "clock" },
  approved: { label: "qa.status.ncr.approved", tone: "accent", icon: "check" },
  implemented: { label: "qa.status.ncr.implemented", tone: "ok", icon: "check" },
  closed: { label: "qa.status.ncr.closed", tone: "ok", icon: "lock" },
  cancelled: { label: "qa.status.ncr.cancelled", tone: "info", icon: "ban" },
};
export const CAPA_STATUS: Record<string, ChipDef> = {
  draft: { label: "qa.status.capa.draft", tone: "info", icon: "file" },
  investigation: { label: "qa.status.capa.investigation", tone: "warn", icon: "search" },
  plan_approval: { label: "qa.status.capa.planApproval", tone: "accent", icon: "clock" },
  implementation: { label: "qa.status.capa.implementation", tone: "accent", icon: "wrench" },
  effectiveness_check: { label: "qa.status.capa.effectivenessCheck", tone: "accent", icon: "eye" },
  closed: { label: "qa.status.capa.closed", tone: "ok", icon: "lock" },
  cancelled: { label: "qa.status.capa.cancelled", tone: "info", icon: "ban" },
};
export const COMPLAINT_STATUS: Record<string, ChipDef> = {
  open: { label: "qa.status.complaint.open", tone: "warn", icon: "alert" },
  investigation: { label: "qa.status.complaint.investigation", tone: "accent", icon: "search" },
  closed: { label: "qa.status.complaint.closed", tone: "ok", icon: "lock" },
};
export const FA_STATUS: Record<string, ChipDef> = {
  draft: { label: "qa.status.fa.draft", tone: "info", icon: "file" },
  approved: { label: "qa.status.fa.approved", tone: "accent", icon: "check" },
  in_progress: { label: "qa.status.fa.inProgress", tone: "warn", icon: "play" },
  completed: { label: "qa.status.fa.completed", tone: "ok", icon: "check" },
  closed: { label: "qa.status.fa.closed", tone: "ok", icon: "lock" },
  cancelled: { label: "qa.status.fa.cancelled", tone: "info", icon: "ban" },
};
export const UNIT_STATUS: Record<string, ChipDef> = {
  pending: { label: "qa.status.unit.pending", tone: "info", icon: "circle" },
  notified: { label: "qa.status.unit.notified", tone: "warn", icon: "bell" },
  acknowledged: { label: "qa.status.unit.acknowledged", tone: "accent", icon: "check" },
  returned: { label: "qa.status.unit.returned", tone: "ok", icon: "truck" },
  corrected: { label: "qa.status.unit.corrected", tone: "ok", icon: "wrench" },
  destroyed: { label: "qa.status.unit.destroyed", tone: "ok", icon: "trash" },
  not_reachable: { label: "qa.status.unit.notReachable", tone: "danger", icon: "x" },
};
export const EQ_STATUS: Record<string, ChipDef> = {
  active: { label: "qa.status.eq.active", tone: "ok", icon: "check" },
  out_of_service: { label: "qa.status.eq.outOfService", tone: "danger", icon: "ban" },
  retired: { label: "qa.status.eq.retired", tone: "info", icon: "x" },
};
export const CAL_STATE: Record<string, ChipDef> = {
  ok: { label: "qa.status.cal.ok", tone: "ok", icon: "check" },
  due_soon: { label: "qa.status.cal.dueSoon", tone: "warn", icon: "clock" },
  in_grace: { label: "qa.status.cal.inGrace", tone: "warn", icon: "alert" },
  overdue: { label: "qa.status.cal.overdue", tone: "danger", icon: "x" },
  not_required: { label: "qa.status.cal.notRequired", tone: "info", icon: "info" },
  out_of_service: { label: "qa.status.eq.outOfService", tone: "danger", icon: "ban" },
  retired: { label: "qa.status.eq.retired", tone: "info", icon: "x" },
};
export const HOLD_SOURCE: Record<string, ChipDef> = {
  inspection: { label: "qa.hold.source.inspection", tone: "warn", icon: "search" },
  ncr: { label: "qa.hold.source.ncr", tone: "danger", icon: "alert" },
  recall: { label: "qa.hold.source.recall", tone: "danger", icon: "flag" },
  field_action: { label: "qa.hold.source.fieldAction", tone: "danger", icon: "truck" },
  manual: { label: "qa.hold.source.manual", tone: "info", icon: "lock" },
};
export const SEVERITY: Record<string, ChipDef> = {
  critical: { label: "qa.severity.critical", tone: "danger", icon: "alert" },
  major: { label: "qa.severity.major", tone: "warn", icon: "alert" },
  minor: { label: "qa.severity.minor", tone: "info", icon: "info" },
};
export const VERDICT: Record<string, ChipDef> = {
  pending: { label: "qa.verdict.pending", tone: "info", icon: "clock" },
  accept: { label: "qa.verdict.accept", tone: "ok", icon: "check" },
  reject: { label: "qa.verdict.reject", tone: "danger", icon: "x" },
};

export const LotStatusChip = ({ s }: { s: string }) => chip(LOT_STATUS, s);
export const DocStatusChip = ({ s }: { s: string }) => chip(DOC_STATUS, s);
export const NcrStatusChip = ({ s }: { s: string }) => chip(NCR_STATUS, s);
export const CapaStatusChip = ({ s }: { s: string }) => chip(CAPA_STATUS, s);
export const ComplaintStatusChip = ({ s }: { s: string }) => chip(COMPLAINT_STATUS, s);
export const FaStatusChip = ({ s }: { s: string }) => chip(FA_STATUS, s);
export const UnitStatusChip = ({ s }: { s: string }) => chip(UNIT_STATUS, s);
export const EqStatusChip = ({ s }: { s: string }) => chip(EQ_STATUS, s);
export const SeverityChip = ({ s }: { s: string }) => chip(SEVERITY, s);
export const HoldSourceChip = ({ s }: { s: string }) => chip(HOLD_SOURCE, s);
export const VerdictChip = ({ s, testId }: { s: string; testId?: string }) => chip(VERDICT, s, testId);

/** Calibration validity: `data-valid` for tests, text says why (due date or state). */
export function CalChip({ state, valid, due }: { state: string; valid: boolean; due?: string | null }) {
  const m = CAL_STATE[state] ?? CAL_STATE.ok;
  return (
    <span className={`badge ${m.tone}`} data-testid="eq-status" data-valid={valid ? "true" : "false"} title={due ? t("qa.cal.tpl.dueOn", { date: fmtDate(due) }) : undefined}>
      <Icon name={m.icon} />
      {t(m.label)}
    </span>
  );
}

/** "On hold" chip of a lot / serial (`hold-chip`). */
export function HoldChip({ on }: { on: boolean }) {
  if (!on) return null;
  return (
    <span className="badge warn" data-testid="hold-chip">
      <Icon name="lock" />
      {t("qa.hold.chip")}
    </span>
  );
}

export const MEANING_LABEL: Record<Meaning, StringKey> = {
  authored: "qa.esig.meaning.authored",
  reviewed: "qa.esig.meaning.reviewed",
  approved: "qa.esig.meaning.approved",
  released: "qa.esig.meaning.released",
  rejected: "qa.esig.meaning.rejected",
  verified: "qa.esig.meaning.verified",
  performed: "qa.esig.meaning.performed",
  closed: "qa.esig.meaning.closed",
};
export const meaningText = (m: string) => (m in MEANING_LABEL ? t(MEANING_LABEL[m as Meaning]) : m);

export const AUTH_LABEL: Record<AuthMethod, StringKey> = {
  password: "qa.esig.auth.password",
  password_totp: "qa.esig.auth.passwordTotp",
  sso: "qa.esig.auth.sso",
  sso_mfa: "qa.esig.auth.ssoMfa",
};
export const authText = (a: string) => (a in AUTH_LABEL ? t(AUTH_LABEL[a as AuthMethod]) : a);

/**
 * Plant-local signing time with seconds, zone and UTC offset (4.2 manifestation). The server sends
 * "2026-11-23 14:05:12 EST (UTC-05:00)"; the date part is shown in the UI format: "23 Nov 2026 14:05:12 EST (UTC-05:00)".
 */
export function fmtSignedAt(m: Pick<SignatureManifest, "signed_at_local" | "signed_at">): string {
  const x = (m.signed_at_local || "").match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s*(.*)$/);
  if (x) return t("qa.esig.tpl.signedAt", { date: fmtDate(x[1]), time: x[2], zone: x[3] });
  return formatDateTime(m.signed_at);
}

/** "Approved by Marie Tremblay (mtremblay) on 23 Nov 2026 14:05:12 EST (UTC-05:00)". */
export function manifestText(m: SignatureManifest): string {
  return t("qa.esig.tpl.manifest", { meaning: m.meaning_label || meaningText(m.meaning), name: m.signer_legal_name, username: m.signer_username, when: fmtSignedAt(m) });
}

export const SCOPE_LABEL: Record<string, StringKey> = { incoming: "qa.scope.incoming", in_process: "qa.scope.inProcess", final: "qa.scope.final" };
export const scopeText = (s: string) => (SCOPE_LABEL[s] ? t(SCOPE_LABEL[s]) : s);

export const DISPOSITION_LABEL: Record<string, StringKey> = {
  scrap: "qa.disposition.scrap",
  rework: "qa.disposition.rework",
  use_as_is: "qa.disposition.useAsIs",
  return_to_supplier: "qa.disposition.returnToSupplier",
};

export const ROLE_KEYS: Record<string, StringKey> = {
  qa_inspector: "qa.roles.str.qaInspector",
  qa_engineer: "qa.roles.str.qaEngineer",
  qa_approver: "qa.roles.str.qaApprover",
  metrology: "qa.roles.str.metrology",
  owner: "mfg.permissions.str.owner",
  plant_admin: "mfg.permissions.str.plantAdmin",
  approver: "mfg.permissions.str.approver",
  supervisor: "mfg.permissions.str.supervisor",
  planner: "mfg.permissions.str.planner",
  operator: "mfg.permissions.str.operator",
};
export const roleText = (r: string) => (ROLE_KEYS[r] ? t(ROLE_KEYS[r]) : r);

/** Record type names for headings, history and exports. */
export const RECORD_TYPE_LABEL: Record<string, StringKey> = {
  inspection_plan: "qa.record.inspectionPlan",
  sampling_scheme: "qa.record.samplingScheme",
  inspection_lot: "qa.record.inspectionLot",
  hold: "qa.record.hold",
  ncr: "qa.record.ncr",
  capa: "qa.record.capa",
  complaint: "qa.record.complaint",
  field_action: "qa.record.fieldAction",
  calibration: "qa.record.calibration",
  equipment: "qa.record.equipment",
  eco: "qa.record.eco",
  esig_policy: "qa.record.esigPolicy",
  plant: "qa.record.plant",
};
export const recordTypeText = (r: string) => (RECORD_TYPE_LABEL[r] ? t(RECORD_TYPE_LABEL[r]) : r);

export const ACTION_LABEL: Record<string, StringKey> = {
  approve: "qa.action.approve",
  decide: "qa.action.decide",
  release: "qa.action.release",
  close: "qa.action.close",
  approve_plan: "qa.action.approvePlan",
  verify: "qa.action.verify",
  record: "qa.action.record",
  return_to_service: "qa.action.returnToService",
  update: "qa.action.update",
  part11_on: "qa.action.part11On",
};
export const actionText = (a: string) => (ACTION_LABEL[a] ? t(ACTION_LABEL[a]) : a);
