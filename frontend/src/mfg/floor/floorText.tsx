/** Floor wording (M4 12): statuses and lights as icon + text, never colour alone; server errors in plain words. */
import { formatQty } from "../../lib/locale";
import { ApiError } from "../../api/client";
import { Icon, type IconName } from "../../components/Icon";
import type { DowntimeKind, FloorEventType, KitLight, TriggerKind, WoOpStatus } from "../api/typesM4";
import { t } from "../../lib/i18n";

export const OP_STATUS: Record<WoOpStatus, { label: string; icon: IconName; tone: string }> = {
  pending: { label: t("floor.floorText.str.waiting"), icon: "clock", tone: "info" },
  ready: { label: t("floor.floorText.str.ready"), icon: "check", tone: "ok" },
  setup: { label: t("floor.floorText.str.settingUp"), icon: "settings", tone: "accent" },
  running: { label: t("floor.floorText.str.running"), icon: "play", tone: "accent" },
  paused: { label: t("floor.floorText.str.paused"), icon: "stop", tone: "warn" },
  completed: { label: t("floor.floorText.str.done"), icon: "check", tone: "ok" },
  skipped: { label: t("floor.floorText.str.skipped"), icon: "ban", tone: "info" },
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
  kitted: { label: t("floor.floorText.str.materialReady"), icon: "check", tone: "ok" },
  partial: { label: t("floor.floorText.str.materialPartlyThere"), icon: "clock", tone: "warn" },
  short: { label: t("floor.floorText.str.materialShort"), icon: "alert", tone: "danger" },
  none: { label: t("floor.floorText.str.materialNotChecked"), icon: "help", tone: "info" },
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
  setup_start: { label: t("floor.floorText.str.startSetup"), icon: "settings", tone: "" },
  start: { label: t("floor.floorText.str.start"), icon: "play", tone: "primary" },
  pause: { label: t("floor.floorText.str.pause"), icon: "stop", tone: "" },
  resume: { label: t("floor.floorText.str.resume"), icon: "play", tone: "primary" },
  report: { label: t("floor.floorText.str.reportQuantity"), icon: "plus", tone: "" },
  complete: { label: t("floor.floorText.str.complete"), icon: "check", tone: "primary" },
  reopen: { label: t("floor.floorText.str.reopen"), icon: "refresh", tone: "" },
  correct: { label: t("floor.floorText.str.correct"), icon: "settings", tone: "" },
  skip: { label: t("floor.floorText.str.skip"), icon: "ban", tone: "" },
};

export const EVENT_LABEL: Record<FloorEventType, string> = {
  setup_start: t("floor.floorText.str.setupStarted"),
  start: t("floor.floorText.str.started"),
  pause: t("floor.floorText.str.paused"),
  resume: t("floor.floorText.str.resumed"),
  report: t("floor.floorText.str.reported"),
  complete: t("floor.floorText.str.completed"),
  reopen: t("floor.floorText.str.reopened"),
  correct: t("floor.floorText.str.corrected"),
  skip: t("floor.floorText.str.skipped"),
};

export const DOWNTIME: Record<DowntimeKind, { label: string; icon: IconName }> = {
  breakdown: { label: t("floor.floorText.str.breakdown"), icon: "alert" },
  maintenance: { label: t("floor.floorText.str.maintenance"), icon: "settings" },
  no_crew: { label: t("floor.floorText.str.noOperators"), icon: "briefcase" },
  no_material: { label: t("floor.floorText.str.noMaterial"), icon: "layers" },
  other: { label: t("floor.floorText.str.other"), icon: "help" },
};

export const TRIGGER: Record<TriggerKind, { label: string; icon: IconName }> = {
  line_down: { label: t("floor.floorText.str.lineDown"), icon: "alert" },
  late_receipt: { label: t("floor.floorText.str.lateDelivery"), icon: "clock" },
  scrap_shortfall: { label: t("floor.floorText.str.scrapShortfall"), icon: "trash" },
  overrun: { label: t("floor.floorText.str.runningOverPlan"), icon: "clock" },
  rush_order: { label: t("floor.floorText.str.rushOrder"), icon: "flag" },
  not_started: { label: t("floor.floorText.str.notStartedOnTime"), icon: "clock" },
  start_short: { label: t("floor.floorText.str.startedWithMaterialShort"), icon: "layers" },
};

/** Default reason codes when the server sends none (#202 `reason_codes` is optional). */
export const DEFAULT_REASONS = {
  pause: [
    { code: "break", label: t("floor.floorText.str.break") },
    { code: "material", label: t("floor.floorText.str.waitingForMaterial") },
    { code: "quality", label: t("floor.floorText.str.qualityCheck") },
    { code: "machine", label: t("floor.floorText.str.machineProblem") },
    { code: "shift_end", label: t("floor.floorText.str.endOfShift") },
    { code: "other", label: t("floor.floorText.str.other") },
  ],
  scrap: [
    { code: "solder", label: t("floor.floorText.str.solderDefect") },
    { code: "component", label: t("floor.floorText.str.componentDefect") },
    { code: "damage", label: t("floor.floorText.str.handlingDamage") },
    { code: "test_fail", label: t("floor.floorText.str.failedTest") },
    { code: "other", label: t("floor.floorText.str.other") },
  ],
  rework: [
    { code: "solder", label: t("floor.floorText.str.solderRework") },
    { code: "component", label: t("floor.floorText.str.replaceComponent") },
    { code: "test_fail", label: t("floor.floorText.str.failedTest") },
    { code: "other", label: t("floor.floorText.str.other") },
  ],
};

const ERROR_TEXT: Record<string, string> = {
  FLR_INVALID_TRANSITION: t("floor.floorText.str.thatActionIsNotPossible"),
  FLR_LINE_DOWN: t("floor.floorText.str.thisLineIsReportedDown"),
  FLR_LINE_NOT_ELIGIBLE: t("floor.floorText.str.thisOperationCannotRunOn"),
  FLR_QTY_EXCEEDS_INPUT: t("floor.floorText.str.goodPlusScrapIsMore"),
  FLR_TIME_INVALID: t("floor.floorText.str.theTimeIsNotAllowed"),
  FLR_SERIALS_REQUIRED: t("floor.floorText.str.scanOrTypeOneSerial"),
  FLR_SERIAL_DUPLICATE: t("floor.floorText.str.oneOfTheseSerialNumbers"),
  FLR_SERIAL_NOT_AVAILABLE: t("floor.floorText.str.aConsumedSerialIsNot"),
  FLR_NO_RECEIPT_LOCATION: t("floor.floorText.str.noReceiptLocationIsSet"),
  FLR_REASON_REQUIRED: t("floor.floorText.str.chooseAReason"),
  FLR_OPERATOR_UNKNOWN: t("floor.floorText.str.anOperatorBadgeWasNot"),
  FLR_SCAN_UNKNOWN: t("floor.floorText.str.thisBarcodeIsNotKnown"),
  WO_KIT_INCOMPLETE: t("floor.floorText.str.componentsAreShortForThe"),
};

export function floorErrorText(e: unknown): string {
  if (e instanceof ApiError) {
    const base = ERROR_TEXT[e.code];
    if (e.code === "FLR_INVALID_TRANSITION") {
      const d = e.details as { status?: string; allowed?: string[] };
      return `${base}${d.status ? t("floor.floorText.tpl.itIs", { v: OP_STATUS[d.status as WoOpStatus]?.label.toLowerCase() ?? d.status }) : ""}`;
    }
    return base ? `${base}${e.message && !base.includes(e.message) ? ` (${e.message})` : ""}` : e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

/** Floor quantities: grouped in the plant's number format, by unit (count units whole, others up to 3 decimals). */
export const fmtQty = (n: number | null | undefined, uom?: string | null) => formatQty(n, uom);

/** "SOLDER_BRIDGE" / "break" -> "Solder bridge" / "Break" (reason codes are plant data) */
export const humanCode = (code: string | null | undefined) => (code ? code.charAt(0).toUpperCase() + code.slice(1).toLowerCase().replace(/_/g, " ") : "");
