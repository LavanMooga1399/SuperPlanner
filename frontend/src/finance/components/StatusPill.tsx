import { Icon, type IconName } from "../../components/Icon";
import type { FinFeasibility, FinRunStatus, GoalStatus } from "../api/types";
import { t } from "../../lib/i18n";

type Tone = "ok" | "warn" | "danger" | "info" | "accent";
export type FinPillKind = GoalStatus | FinFeasibility | FinRunStatus;

const MAP: Record<FinPillKind, { label: string; tone: Tone; icon: IconName }> = {
  on_track: { label: t("finance.statusPill.str.onTrack"), tone: "ok", icon: "check" },
  at_risk: { label: t("finance.statusPill.str.atRisk"), tone: "warn", icon: "alert" },
  off_track: { label: t("finance.statusPill.str.offTrack"), tone: "danger", icon: "x" },
  feasible: { label: t("finance.statusPill.str.planIsValid"), tone: "ok", icon: "check" },
  infeasible: { label: t("finance.statusPill.str.notEnoughCash"), tone: "danger", icon: "ban" },
  unknown: { label: t("finance.statusPill.str.needsReview"), tone: "warn", icon: "help" },
  queued: { label: t("finance.statusPill.str.queued"), tone: "info", icon: "clock" },
  running: { label: t("finance.statusPill.str.running"), tone: "accent", icon: "loader" },
  completed: { label: t("finance.statusPill.str.completed"), tone: "ok", icon: "check" },
  failed: { label: t("finance.statusPill.str.failed"), tone: "danger", icon: "x" },
  cancelled: { label: t("finance.statusPill.str.cancelled"), tone: "info", icon: "stop" },
};

/** Status is always icon + text, never color alone. */
export function StatusPill({ kind, label, testId, title }: { kind: FinPillKind; label?: string; testId?: string; title?: string }) {
  const m = MAP[kind] ?? { label: String(kind), tone: "info" as Tone, icon: "info" as IconName };
  return (
    <span className={`badge ${m.tone}`} data-testid={testId} data-status={kind} title={title}>
      <Icon name={m.icon} />
      {label ?? m.label}
    </span>
  );
}

export const goalStatusLabel = (s: GoalStatus | null | undefined) => (s ? MAP[s].label : "-");
