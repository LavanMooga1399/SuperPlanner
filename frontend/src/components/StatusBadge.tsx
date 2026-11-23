import type { Feasibility, RunStatus, ScheduleStatus } from "../api/types";
import { Icon, type IconName } from "./Icon";
import { t } from "../lib/i18n";

type Tone = "ok" | "warn" | "danger" | "info" | "accent";

export type BadgeKind =
  | Feasibility
  | RunStatus
  | ScheduleStatus
  | "late"
  | "on_time"
  | "error"
  | "warning";

const MAP: Record<BadgeKind, { label: string; tone: Tone; icon: IconName }> = {
  feasible: { label: t("studio.statusBadge.str.feasible"), tone: "ok", icon: "check" },
  infeasible: { label: t("studio.statusBadge.str.notFeasible"), tone: "danger", icon: "ban" },
  unknown: { label: t("studio.statusBadge.str.unknown"), tone: "warn", icon: "help" },
  queued: { label: t("studio.statusBadge.str.queued"), tone: "info", icon: "clock" },
  running: { label: t("studio.statusBadge.str.running"), tone: "accent", icon: "loader" },
  completed: { label: t("studio.statusBadge.str.completed"), tone: "ok", icon: "check" },
  failed: { label: t("studio.statusBadge.str.failed"), tone: "danger", icon: "x" },
  cancelled: { label: t("studio.statusBadge.str.cancelled"), tone: "info", icon: "stop" },
  candidate: { label: t("studio.statusBadge.str.candidate"), tone: "info", icon: "circle" },
  approved: { label: t("studio.statusBadge.str.approved"), tone: "ok", icon: "star" },
  superseded: { label: t("studio.statusBadge.str.superseded"), tone: "info", icon: "refresh" },
  late: { label: t("studio.statusBadge.str.late"), tone: "danger", icon: "clock" },
  on_time: { label: t("studio.statusBadge.str.onTime"), tone: "ok", icon: "check" },
  error: { label: t("studio.statusBadge.str.error"), tone: "danger", icon: "x" },
  warning: { label: t("studio.statusBadge.str.warning"), tone: "warn", icon: "alert" },
};

export interface StatusBadgeProps {
  kind: BadgeKind;
  label?: string;
  testId?: string;
  title?: string;
}

/** Status is always icon + text, never color alone. */
export function StatusBadge({ kind, label, testId, title }: StatusBadgeProps) {
  const m = MAP[kind] ?? { label: String(kind), tone: "info" as Tone, icon: "info" as IconName };
  return (
    <span className={`badge ${m.tone}`} data-testid={testId} data-status={kind} title={title}>
      <Icon name={m.icon} />
      {label ?? m.label}
    </span>
  );
}
