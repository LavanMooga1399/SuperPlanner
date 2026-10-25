/** Status chips: always icon + text, never color alone. */
import { Icon, type IconName } from "../../components/Icon";
import type { MakeBuy, Severity, Status } from "../api/types";

type Tone = "ok" | "warn" | "danger" | "info" | "accent";

const STATUS: Record<Status, { label: string; tone: Tone; icon: IconName }> = {
  draft: { label: "Draft", tone: "warn", icon: "file" },
  released: { label: "Released", tone: "ok", icon: "check" },
  obsolete: { label: "Obsolete", tone: "info", icon: "ban" },
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
  make: { label: "Make", icon: "factory", title: "Made in this plant" },
  buy: { label: "Buy", icon: "briefcase", title: "Bought from a supplier" },
  phantom: { label: "Phantom", icon: "layers", title: "Phantom: a kit that is never stocked; its parts are used directly" },
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
  error: { label: "Error", tone: "danger", icon: "x" },
  warning: { label: "Warning", tone: "warn", icon: "alert" },
  info: { label: "Info", tone: "info", icon: "info" },
};

export function SeverityBadge({ severity, label }: { severity: Severity; label?: string }) {
  const m = SEVERITY[severity];
  return (
    <span className={`badge ${m.tone}`} data-severity={severity}>
      <Icon name={m.icon} />
      {label ?? m.label}
    </span>
  );
}

export function severityIcon(severity: Severity): IconName {
  return SEVERITY[severity].icon;
}

export function ActiveBadge({ active }: { active: boolean }) {
  if (active) return null;
  return (
    <span className="badge info" title="Inactive: kept for history, flagged when used">
      <Icon name="ban" />
      Inactive
    </span>
  );
}

export function KindBadge({ kind }: { kind: "base" | "optional" }) {
  return kind === "base" ? (
    <span className="badge accent" title="Base shift: always available">
      <Icon name="clock" />
      Base
    </span>
  ) : (
    <span className="badge warn" title="Optional shift: overtime or an extra shift opened by the planner when needed">
      <Icon name="plus" />
      Optional
    </span>
  );
}
