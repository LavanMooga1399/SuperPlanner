import { Icon, type IconName } from "../../components/Icon";
import type { FinFeasibility, FinRunStatus, GoalStatus } from "../api/types";

type Tone = "ok" | "warn" | "danger" | "info" | "accent";
export type FinPillKind = GoalStatus | FinFeasibility | FinRunStatus;

const MAP: Record<FinPillKind, { label: string; tone: Tone; icon: IconName }> = {
  on_track: { label: "On track", tone: "ok", icon: "check" },
  at_risk: { label: "At risk", tone: "warn", icon: "alert" },
  off_track: { label: "Off track", tone: "danger", icon: "x" },
  feasible: { label: "Plan is valid", tone: "ok", icon: "check" },
  infeasible: { label: "Not enough cash", tone: "danger", icon: "ban" },
  unknown: { label: "Needs review", tone: "warn", icon: "help" },
  queued: { label: "Queued", tone: "info", icon: "clock" },
  running: { label: "Running", tone: "accent", icon: "loader" },
  completed: { label: "Completed", tone: "ok", icon: "check" },
  failed: { label: "Failed", tone: "danger", icon: "x" },
  cancelled: { label: "Cancelled", tone: "info", icon: "stop" },
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
