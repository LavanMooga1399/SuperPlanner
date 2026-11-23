/** M2 status chips: always icon + text (never color alone), `data-status` for tests. */
import { Icon, type IconName } from "../../components/Icon";
import type {
  DemandStatus,
  LocationKind,
  MrpSeverity,
  ProjectionStatus,
  PurchaseStatus,
  ReleaseStatus,
  RunKind,
  RunStatus,
  WoStatus,
} from "../api/typesM2";
import { plural, t } from "../../lib/i18n";

type Tone = "ok" | "warn" | "danger" | "info" | "accent";
interface Meta {
  label: string;
  tone: Tone;
  icon: IconName;
  title?: string;
}

function Chip({ m, status, testId }: { m: Meta; status: string; testId?: string }) {
  return (
    <span className={`badge ${m.tone}`} data-status={status} data-testid={testId} title={m.title}>
      <Icon name={m.icon} />
      {m.label}
    </span>
  );
}

const fallback = (s: string): Meta => ({ label: s.replace(/_/g, " "), tone: "info", icon: "info" });

const PURCHASE: Record<PurchaseStatus, Meta> = {
  draft: { label: t("mfg.statusM2.str.draft"), tone: "warn", icon: "file" },
  submitted: { label: t("mfg.statusM2.str.waitingForApproval"), tone: "accent", icon: "clock" },
  approved: { label: t("mfg.statusM2.str.approved"), tone: "ok", icon: "check" },
  rejected: { label: t("mfg.statusM2.str.rejected"), tone: "danger", icon: "x" },
  ordered: { label: t("mfg.statusM2.str.ordered"), tone: "ok", icon: "briefcase" },
  cancelled: { label: t("mfg.statusM2.str.cancelled"), tone: "info", icon: "ban" },
  open: { label: t("mfg.statusM2.str.open"), tone: "accent", icon: "briefcase" },
  partially_received: { label: t("mfg.statusM2.str.partlyReceived"), tone: "warn", icon: "download" },
  received: { label: t("mfg.statusM2.str.received"), tone: "ok", icon: "check" },
  closed: { label: t("mfg.statusM2.str.closed"), tone: "info", icon: "lock" },
};

export function PurchaseStatusChip({ status, testId }: { status: PurchaseStatus; testId?: string }) {
  return <Chip m={PURCHASE[status] ?? fallback(status)} status={status} testId={testId} />;
}

const DEMAND: Record<DemandStatus, Meta> = {
  draft: { label: t("mfg.statusM2.str.draftNotPlanned"), tone: "warn", icon: "file" },
  open: { label: t("mfg.statusM2.str.open"), tone: "accent", icon: "flag" },
  closed: { label: t("mfg.statusM2.str.closed"), tone: "info", icon: "lock" },
  cancelled: { label: t("mfg.statusM2.str.cancelled"), tone: "info", icon: "ban" },
};

export function DemandStatusChip({ status, testId }: { status: DemandStatus; testId?: string }) {
  return <Chip m={DEMAND[status] ?? fallback(status)} status={status} testId={testId} />;
}

const WO: Record<WoStatus, Meta> = {
  planned: { label: t("mfg.statusM2.str.plannedFirm"), tone: "warn", icon: "calendar" },
  released: { label: t("mfg.statusM2.str.released"), tone: "accent", icon: "play" },
  in_progress: { label: t("mfg.statusM2.str.inProgress"), tone: "accent", icon: "loader" },
  completed: { label: t("mfg.statusM2.str.completed"), tone: "ok", icon: "check" },
  closed: { label: t("mfg.statusM2.str.closed"), tone: "info", icon: "lock" },
  cancelled: { label: t("mfg.statusM2.str.cancelled"), tone: "info", icon: "ban" },
};

export function WoStatusChip({ status, testId }: { status: WoStatus; testId?: string }) {
  return <Chip m={WO[status] ?? fallback(status)} status={status} testId={testId} />;
}

const PROJECTION: Record<ProjectionStatus, Meta> = {
  on_time: { label: t("mfg.statusM2.str.onTime"), tone: "ok", icon: "check" },
  late: { label: t("mfg.statusM2.str.late"), tone: "danger", icon: "alert" },
  past_due: { label: t("mfg.statusM2.str.pastDue"), tone: "danger", icon: "clock" },
};

export function ProjectionChip({ status, lateDays }: { status: ProjectionStatus; lateDays?: number }) {
  const m = PROJECTION[status] ?? fallback(status);
  const label = status === "late" && lateDays ? `${lateDays} d late` : m.label;
  return <Chip m={{ ...m, label }} status={status} />;
}

const SEVERITY: Record<MrpSeverity, Meta> = {
  critical: { label: t("mfg.statusM2.str.critical"), tone: "danger", icon: "x" },
  warning: { label: t("mfg.statusM2.str.warning"), tone: "warn", icon: "alert" },
  info: { label: t("mfg.statusM2.str.info"), tone: "info", icon: "info" },
};

export function MrpSeverityBadge({ severity, label }: { severity: MrpSeverity; label?: string }) {
  const m = SEVERITY[severity] ?? fallback(severity);
  return (
    <span className={`badge ${m.tone}`} data-severity={severity}>
      <Icon name={m.icon} />
      {label ?? m.label}
    </span>
  );
}

export function mrpSeverityIcon(s: MrpSeverity): IconName {
  return (SEVERITY[s] ?? fallback(s)).icon;
}

const RELEASE: Record<ReleaseStatus, Meta> = {
  start_in_past: { label: t("mfg.statusM2.str.shouldHaveStarted"), tone: "danger", icon: "clock", title: t("mfg.statusM2.str.theStartDateIsAlready") },
  release_now: { label: t("mfg.statusM2.str.releaseNow"), tone: "warn", icon: "play", title: t("mfg.statusM2.str.startsWithinTheReleaseWindow") },
  later: { label: t("mfg.statusM2.str.later"), tone: "info", icon: "calendar", title: t("mfg.statusM2.str.notDueForReleaseYet") },
};

export function ReleaseChip({ status }: { status: ReleaseStatus }) {
  return <Chip m={RELEASE[status] ?? fallback(status)} status={status} />;
}

const RUN_STATUS: Record<RunStatus, Meta> = {
  running: { label: t("mfg.statusM2.str.running"), tone: "accent", icon: "loader" },
  completed: { label: t("mfg.statusM2.str.completed"), tone: "ok", icon: "check" },
  failed: { label: t("mfg.statusM2.str.failed"), tone: "danger", icon: "x" },
};

export function RunStatusChip({ status }: { status: RunStatus }) {
  return <Chip m={RUN_STATUS[status] ?? fallback(status)} status={status} />;
}

export function RunKindBadge({ kind }: { kind: RunKind }) {
  return kind === "live" ? (
    <span className="badge accent" data-kind="live" title={t("mfg.statusM2.attr.planFromTodaySData")}>
      <Icon name="play" /> {t("mfg.statusM2.btn.live")}
    </span>
  ) : (
    <span className="badge info" data-kind="what_if" title={t("mfg.statusM2.attr.aWhatIfScenarioFor")}>
      <Icon name="help" /> {t("mfg.statusM2.btn.whatif")}
    </span>
  );
}

export const LOCATION_KIND_LABEL: Record<LocationKind, string> = {
  stores: t("mfg.statusM2.str.stores"),
  line_side: t("mfg.statusM2.str.lineSide"),
  inspection: t("mfg.statusM2.str.goodsInInspection"),
  quarantine: t("mfg.statusM2.str.quarantine"),
};

const KIND_META: Record<LocationKind, Meta> = {
  stores: { label: t("mfg.statusM2.str.stores"), tone: "ok", icon: "layers", title: t("mfg.statusM2.str.availableForPlanningAndKitting") },
  line_side: { label: t("mfg.statusM2.str.lineSide"), tone: "ok", icon: "factory", title: t("mfg.statusM2.str.availableForPlanningAndKitting") },
  inspection: { label: t("mfg.statusM2.str.inspection"), tone: "warn", icon: "clock", title: t("mfg.statusM2.str.availableForPlanningAfterThe") },
  quarantine: { label: t("mfg.statusM2.str.quarantine"), tone: "danger", icon: "ban", title: t("mfg.statusM2.str.neverUsedForPlanningOr") },
};

export function LocationKindBadge({ kind }: { kind: LocationKind }) {
  return <Chip m={KIND_META[kind] ?? fallback(kind)} status={kind} />;
}

export function OverdueBadge({ days }: { days: number }) {
  return (
    <span className="badge danger" data-overdue="true" title={t("mfg.statusM2.tpl.dockDatePassedAgoAnd", { days: plural(days, "day") })}>
      <Icon name="clock" />
      {days > 0 ? `${days} d overdue` : t("mfg.statusM2.str.overdue")}
    </span>
  );
}

export function LateBadge({ days }: { days: number }) {
  if (days <= 0) return null;
  return (
    <span className="badge danger" data-late-days={days}>
      <Icon name="alert" />
      {days} d late
    </span>
  );
}

export function HoldBadge() {
  return (
    <span className="badge danger" title={t("mfg.statusM2.attr.onHoldNotUsedFor")}>
      <Icon name="lock" /> {t("mfg.statusM2.btn.onHold")}
    </span>
  );
}

export function SourceBadge({ source, runNo }: { source: "manual" | "mrp" | "import"; runNo?: number | null }) {
  if (source === "manual") return null;
  return (
    <span className="badge info" title={source === "mrp" ? t("mfg.statusM2.tpl.createdFromMrpRun", { v: runNo ?? "" }) : t("mfg.statusM2.str.importedFromAFile")}>
      <Icon name={source === "mrp" ? "graph" : "upload"} />
      {source === "mrp" ? `MRP${runNo ? ` #${runNo}` : ""}` : t("mfg.statusM2.str.imported")}
    </span>
  );
}
