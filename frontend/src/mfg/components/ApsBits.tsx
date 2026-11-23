/** Small shared pieces of the schedule screens: run status chip, progress bar, overtime policy badge. */
import { Icon, type IconName } from "../../components/Icon";
import type { ApsRunRecord, ApsRunStatus, OvertimePolicy } from "../api/typesM3";
import { t } from "../../lib/i18n";

const STATUS: Record<ApsRunStatus, { label: string; tone: string; icon: IconName }> = {
  queued: { label: t("mfg.apsBits.str.queued"), tone: "info", icon: "clock" },
  running: { label: t("mfg.apsBits.str.running"), tone: "accent", icon: "loader" },
  completed: { label: t("mfg.apsBits.str.completed"), tone: "ok", icon: "check" },
  failed: { label: t("mfg.apsBits.str.failed"), tone: "danger", icon: "x" },
  cancelled: { label: t("mfg.apsBits.str.cancelled"), tone: "warn", icon: "stop" },
};

export function ApsStatusChip({ run }: { run: ApsRunRecord }) {
  const m = STATUS[run.status] ?? { label: run.status, tone: "info", icon: "info" as IconName };
  const invalid = run.status === "completed" && run.validation && !run.validation.ok;
  if (invalid)
    return (
      <span className="badge danger" data-status="infeasible" title={t("mfg.apsBits.attr.theValidatorFoundBrokenRules")}>
        <Icon name="alert" /> {t("mfg.apsBits.btn.infeasible")}
      </span>
    );
  return (
    <span className={`badge ${m.tone}`} data-status={run.status}>
      <Icon name={m.icon} /> {m.label}
    </span>
  );
}

const PHASE: Record<string, string> = { load: t("mfg.apsBits.str.loadingData"), construct: t("mfg.apsBits.str.buildingThePlan"), improve: t("mfg.apsBits.str.improving"), validate: t("mfg.apsBits.str.checking"), store: t("mfg.apsBits.str.saving") };

export function ApsProgress({ run }: { run: ApsRunRecord }) {
  if (run.status !== "queued" && run.status !== "running") return null;
  const pct = Math.max(0, Math.min(100, run.progress?.percent ?? 0));
  return (
    <div className="col" style={{ gap: 2, minWidth: 180 }} data-testid="aps-progress" data-percent={pct} data-phase={run.progress?.phase ?? run.status}>
      <div className="progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={t("mfg.apsBits.aria.scheduleRunProgress")}>
        <div style={{ width: `${pct}%` }} />
      </div>
      <span className="faint small">
        {run.status === "queued" ? t("mfg.apsBits.str.waitingToStart") : `${PHASE[run.progress?.phase ?? ""] ?? t("mfg.apsBits.str.running")} · ${Math.round(pct)}%`}
      </span>
    </div>
  );
}

export function PolicyBadge({ policy }: { policy: OvertimePolicy | null | undefined }) {
  if (!policy) return null;
  const m: Record<OvertimePolicy, { label: string; icon: IconName; tone: string }> = {
    off: { label: t("mfg.apsBits.str.noOvertime"), icon: "ban", tone: "info" },
    suggest: { label: t("mfg.apsBits.str.overtimeSuggested"), icon: "help", tone: "info" },
    allow: { label: t("mfg.apsBits.str.overtimeUsed"), icon: "clock", tone: "warn" },
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
    <span className="badge ok" data-testid="aps-published-badge" title={t("mfg.apsBits.attr.thePlantPlanDispatchLists")}>
      <Icon name="flag" /> {t("mfg.apsBits.btn.published")}
    </span>
  );
}
