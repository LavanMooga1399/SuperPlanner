/** Floor wording (M4 12): statuses and lights as icon + text, never colour alone; server errors in plain words. */
import { ApiError } from "../../api/client";
import { Icon, type IconName } from "../../components/Icon";
import type { DowntimeKind, FloorEventType, KitLight, TriggerKind, WoOpStatus } from "../api/typesM4";

export const OP_STATUS: Record<WoOpStatus, { label: string; icon: IconName; tone: string }> = {
  pending: { label: "Waiting", icon: "clock", tone: "info" },
  ready: { label: "Ready", icon: "check", tone: "ok" },
  setup: { label: "Setting up", icon: "settings", tone: "accent" },
  running: { label: "Running", icon: "play", tone: "accent" },
  paused: { label: "Paused", icon: "stop", tone: "warn" },
  completed: { label: "Done", icon: "check", tone: "ok" },
  skipped: { label: "Skipped", icon: "ban", tone: "info" },
};

export function OpStatusChip({ status, large }: { status: WoOpStatus; large?: boolean }) {
  const s = OP_STATUS[status] ?? { label: status, icon: "help" as IconName, tone: "info" };
  return (
    <span className={`badge ${s.tone}${large ? " floor-badge-lg" : ""}`} data-status={status}>
      <Icon name={s.icon} /> {s.label}
    </span>
  );
}

export const KIT: Record<KitLight, { label: string; icon: IconName; tone: string }> = {
  kitted: { label: "Material ready", icon: "check", tone: "ok" },
  partial: { label: "Material partly there", icon: "clock", tone: "warn" },
  short: { label: "Material short", icon: "alert", tone: "danger" },
  none: { label: "Material not checked", icon: "help", tone: "info" },
};

export function KitChip({ kit }: { kit: KitLight }) {
  const k = KIT[kit] ?? KIT.none;
  return (
    <span className={`badge ${k.tone}`} data-kit={kit}>
      <Icon name={k.icon} /> {k.label}
    </span>
  );
}

export const ACTION: Record<FloorEventType, { label: string; icon: IconName; tone: string }> = {
  setup_start: { label: "Start setup", icon: "settings", tone: "" },
  start: { label: "Start", icon: "play", tone: "primary" },
  pause: { label: "Pause", icon: "stop", tone: "" },
  resume: { label: "Resume", icon: "play", tone: "primary" },
  report: { label: "Report quantity", icon: "plus", tone: "" },
  complete: { label: "Complete", icon: "check", tone: "primary" },
  reopen: { label: "Reopen", icon: "refresh", tone: "" },
  correct: { label: "Correct", icon: "settings", tone: "" },
  skip: { label: "Skip", icon: "ban", tone: "" },
};

export const EVENT_LABEL: Record<FloorEventType, string> = {
  setup_start: "Setup started",
  start: "Started",
  pause: "Paused",
  resume: "Resumed",
  report: "Reported",
  complete: "Completed",
  reopen: "Reopened",
  correct: "Corrected",
  skip: "Skipped",
};

export const DOWNTIME: Record<DowntimeKind, { label: string; icon: IconName }> = {
  breakdown: { label: "Breakdown", icon: "alert" },
  maintenance: { label: "Maintenance", icon: "settings" },
  no_crew: { label: "No operators", icon: "briefcase" },
  no_material: { label: "No material", icon: "layers" },
  other: { label: "Other", icon: "help" },
};

export const TRIGGER: Record<TriggerKind, { label: string; icon: IconName }> = {
  line_down: { label: "Line down", icon: "alert" },
  late_receipt: { label: "Late delivery", icon: "clock" },
  scrap_shortfall: { label: "Scrap shortfall", icon: "trash" },
  overrun: { label: "Running over plan", icon: "clock" },
  rush_order: { label: "Rush order", icon: "flag" },
  not_started: { label: "Not started on time", icon: "clock" },
  start_short: { label: "Started with material short", icon: "layers" },
};

/** Default reason codes when the server sends none (#202 `reason_codes` is optional). */
export const DEFAULT_REASONS = {
  pause: [
    { code: "break", label: "Break" },
    { code: "material", label: "Waiting for material" },
    { code: "quality", label: "Quality check" },
    { code: "machine", label: "Machine problem" },
    { code: "shift_end", label: "End of shift" },
    { code: "other", label: "Other" },
  ],
  scrap: [
    { code: "solder", label: "Solder defect" },
    { code: "component", label: "Component defect" },
    { code: "damage", label: "Handling damage" },
    { code: "test_fail", label: "Failed test" },
    { code: "other", label: "Other" },
  ],
  rework: [
    { code: "solder", label: "Solder rework" },
    { code: "component", label: "Replace component" },
    { code: "test_fail", label: "Failed test" },
    { code: "other", label: "Other" },
  ],
};

const ERROR_TEXT: Record<string, string> = {
  FLR_INVALID_TRANSITION: "That action is not possible in the operation's current state.",
  FLR_LINE_DOWN: "This line is reported down. Close the downtime first, or ask a supervisor.",
  FLR_LINE_NOT_ELIGIBLE: "This operation cannot run on that line.",
  FLR_QTY_EXCEEDS_INPUT: "Good plus scrap is more than the quantity that reached this operation.",
  FLR_TIME_INVALID: "The time is not allowed (in the future, before the work order started, or too far back).",
  FLR_SERIALS_REQUIRED: "Scan or type one serial number for each good unit.",
  FLR_SERIAL_DUPLICATE: "One of these serial numbers already exists.",
  FLR_SERIAL_NOT_AVAILABLE: "A consumed serial is not in stock or work in progress.",
  FLR_NO_RECEIPT_LOCATION: "No receipt location is set for finished goods (work order or plant settings).",
  FLR_REASON_REQUIRED: "Choose a reason.",
  FLR_OPERATOR_UNKNOWN: "An operator badge was not recognised.",
  FLR_SCAN_UNKNOWN: "This barcode is not known.",
  WO_KIT_INCOMPLETE: "Components are short for the first operation.",
};

export function floorErrorText(e: unknown): string {
  if (e instanceof ApiError) {
    const base = ERROR_TEXT[e.code];
    if (e.code === "FLR_INVALID_TRANSITION") {
      const d = e.details as { status?: string; allowed?: string[] };
      return `${base}${d.status ? ` It is ${OP_STATUS[d.status as WoOpStatus]?.label.toLowerCase() ?? d.status}.` : ""}`;
    }
    return base ? `${base}${e.message && !base.includes(e.message) ? ` (${e.message})` : ""}` : e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export const fmtQty = (n: number | null | undefined) => (n === null || n === undefined ? "" : Number.isInteger(n) ? String(n) : n.toFixed(2));

/** "SOLDER_BRIDGE" / "break" -> "Solder bridge" / "Break" (reason codes are plant data) */
export const humanCode = (code: string | null | undefined) => (code ? code.charAt(0).toUpperCase() + code.slice(1).toLowerCase().replace(/_/g, " ") : "");
