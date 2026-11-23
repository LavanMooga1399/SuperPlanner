/** Status chips: always icon + text, never color alone. */
import { Icon, type IconName } from "../../components/Icon";
import type { MakeBuy, Severity, Status } from "../api/types";
import { t } from "../../lib/i18n";

type Tone = "ok" | "warn" | "danger" | "info" | "accent";

const STATUS: Record<Status, { label: string; tone: Tone; icon: IconName }> = {
  draft: { label: t("mfg.statusChip.str.draft"), tone: "warn", icon: "file" },
  released: { label: t("mfg.statusChip.str.released"), tone: "ok", icon: "check" },
  obsolete: { label: t("mfg.statusChip.str.obsolete"), tone: "info", icon: "ban" },
};

export function StatusChip({ status, testId }: { status: Status; testId?: string }) {
  const m = STATUS[status] ?? { label: status, tone: "info", icon: "info" };
  return (
    <span className={`badge ${m.tone}`} data-status={status} data-testid={testId}>
      <Icon name={m.icon} />
      {m.label}
    </span>
  );
}

const MAKE_BUY: Record<MakeBuy, { label: string; icon: IconName; title: string }> = {
  make: { label: t("mfg.statusChip.str.make"), icon: "factory", title: t("mfg.statusChip.str.madeInThisPlant") },
  buy: { label: t("mfg.statusChip.str.buy"), icon: "briefcase", title: t("mfg.statusChip.str.boughtFromASupplier") },
  phantom: { label: t("mfg.statusChip.str.phantom"), icon: "layers", title: t("mfg.statusChip.str.phantomAKitThatIs") },
};

export function MakeBuyBadge({ value }: { value: MakeBuy }) {
  const m = MAKE_BUY[value] ?? { label: value, icon: "info", title: value };
  return (
    <span className="badge info mfg-makebuy" data-make-buy={value} title={m.title}>
      <Icon name={m.icon} />
      {m.label}
    </span>
  );
}

const SEVERITY: Record<Severity, { label: string; tone: Tone; icon: IconName }> = {
  error: { label: t("mfg.statusChip.str.error"), tone: "danger", icon: "x" },
  warning: { label: t("mfg.statusChip.str.warning"), tone: "warn", icon: "alert" },
  info: { label: t("mfg.statusChip.str.info"), tone: "info", icon: "info" },
};

/** Unknown severities (a newer server) render as a neutral "Note" instead of failing. */
function severityMeta(severity: Severity): { label: string; tone: Tone; icon: IconName } {
  return SEVERITY[severity] ?? { label: String(severity || t("mfg.statusChip.str.note")), tone: "info", icon: "info" };
}

export function SeverityBadge({ severity, label }: { severity: Severity; label?: string }) {
  const m = severityMeta(severity);
  return (
    <span className={`badge ${m.tone}`} data-severity={severity}>
      <Icon name={m.icon} />
      {label ?? m.label}
    </span>
  );
}

export function severityIcon(severity: Severity): IconName {
  return severityMeta(severity).icon;
}

export function ActiveBadge({ active }: { active: boolean }) {
  if (active) return null;
  return (
    <span className="badge info" title={t("mfg.statusChip.attr.inactiveKeptForHistoryFlagged")}>
      <Icon name="ban" />
      {t("mfg.statusChip.text.inactive")}
    </span>
  );
}

export function KindBadge({ kind }: { kind: "base" | "optional" }) {
  return kind === "base" ? (
    <span className="badge accent" title={t("mfg.statusChip.attr.baseShiftAlwaysAvailable")}>
      <Icon name="clock" />
      {t("mfg.statusChip.text.base")}
    </span>
  ) : (
    <span className="badge warn" title={t("mfg.statusChip.attr.optionalShiftOvertimeOrAn")}>
      <Icon name="plus" />
      {t("mfg.statusChip.text.optional")}
    </span>
  );
}
