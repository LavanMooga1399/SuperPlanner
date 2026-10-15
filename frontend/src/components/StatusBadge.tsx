import type { Feasibility, RunStatus, ScheduleStatus } from "../api/types";
import { Icon, type IconName } from "./Icon";

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
  feasible: { label: "Feasible", tone: "ok", icon: "check" },
  infeasible: { label: "Not feasible", tone: "danger", icon: "ban" },
  unknown: { label: "Unknown", tone: "warn", icon: "help" },
  queued: { label: "Queued", tone: "info", icon: "clock" },
  running: { label: "Running", tone: "accent", icon: "loader" },
  completed: { label: "Completed", tone: "ok", icon: "check" },
  failed: { label: "Failed", tone: "danger", icon: "x" },
  cancelled: { label: "Cancelled", tone: "info", icon: "stop" },
  candidate: { label: "Candidate", tone: "info", icon: "circle" },
  approved: { label: "Approved", tone: "ok", icon: "star" },
  superseded: { label: "Superseded", tone: "info", icon: "refresh" },
  late: { label: "Late", tone: "danger", icon: "clock" },
  on_time: { label: "On time", tone: "ok", icon: "check" },
  error: { label: "Error", tone: "danger", icon: "x" },
  warning: { label: "Warning", tone: "warn", icon: "alert" },
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
