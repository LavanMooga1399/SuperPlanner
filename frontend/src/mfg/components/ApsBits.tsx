/** Small shared pieces of the schedule screens: run status chip, progress bar, overtime policy badge. */
import { Icon, type IconName } from "../../components/Icon";
import type { ApsRunRecord, ApsRunStatus, OvertimePolicy } from "../api/typesM3";

const STATUS: Record<ApsRunStatus, { label: string; tone: string; icon: IconName }> = {
  queued: { label: "Queued", tone: "info", icon: "clock" },
  running: { label: "Running", tone: "accent", icon: "loader" },
  completed: { label: "Completed", tone: "ok", icon: "check" },
  failed: { label: "Failed", tone: "danger", icon: "x" },
  cancelled: { label: "Cancelled", tone: "warn", icon: "stop" },
};

export function ApsStatusChip({ run }: { run: ApsRunRecord }) {
  const m = STATUS[run.status] ?? { label: run.status, tone: "info", icon: "info" as IconName };
  const invalid = run.status === "completed" && run.validation && !run.validation.ok;
  if (invalid)
    return (
      <span className="badge danger" data-status="infeasible" title="The validator found broken rules; this plan cannot be published">
        <Icon name="alert" /> Infeasible
      </span>
    );
  return (
    <span className={`badge ${m.tone}`} data-status={run.status}>
      <Icon name={m.icon} /> {m.label}
    </span>
  );
}

const PHASE: Record<string, string> = { load: "Loading data", construct: "Building the plan", improve: "Improving", validate: "Checking", store: "Saving" };

export function ApsProgress({ run }: { run: ApsRunRecord }) {
  if (run.status !== "queued" && run.status !== "running") return null;
  const pct = Math.max(0, Math.min(100, run.progress?.percent ?? 0));
  return (
    <div className="col" style={{ gap: 2, minWidth: 180 }} data-testid="aps-progress" data-percent={pct} data-phase={run.progress?.phase ?? run.status}>
      <div className="progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Schedule run progress">
        <div style={{ width: `${pct}%` }} />
      </div>
      <span className="faint small">
        {run.status === "queued" ? "Waiting to start" : `${PHASE[run.progress?.phase ?? ""] ?? "Running"} · ${Math.round(pct)}%`}
      </span>
    </div>
  );
}

export function PolicyBadge({ policy }: { policy: OvertimePolicy | null | undefined }) {
  if (!policy) return null;
  const m: Record<OvertimePolicy, { label: string; icon: IconName; tone: string }> = {
    off: { label: "No overtime", icon: "ban", tone: "info" },
    suggest: { label: "Overtime suggested", icon: "help", tone: "info" },
    allow: { label: "Overtime used", icon: "clock", tone: "warn" },
  };
  const x = m[policy];
  return (
    <span className={`badge ${x.tone}`} data-policy={policy}>
      <Icon name={x.icon} /> {x.label}
    </span>
  );
}

export function PublishedBadge() {
  return (
    <span className="badge ok" data-testid="aps-published-badge" title="The plant plan: dispatch lists and the freeze window use it">
      <Icon name="flag" /> Published
    </span>
  );
}
