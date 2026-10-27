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
  draft: { label: "Draft", tone: "warn", icon: "file" },
  submitted: { label: "Waiting for approval", tone: "accent", icon: "clock" },
  approved: { label: "Approved", tone: "ok", icon: "check" },
  rejected: { label: "Rejected", tone: "danger", icon: "x" },
  ordered: { label: "Ordered", tone: "ok", icon: "briefcase" },
  cancelled: { label: "Cancelled", tone: "info", icon: "ban" },
  open: { label: "Open", tone: "accent", icon: "briefcase" },
  partially_received: { label: "Partly received", tone: "warn", icon: "download" },
  received: { label: "Received", tone: "ok", icon: "check" },
  closed: { label: "Closed", tone: "info", icon: "lock" },
};

export function PurchaseStatusChip({ status, testId }: { status: PurchaseStatus; testId?: string }) {
  return <Chip m={PURCHASE[status] ?? fallback(status)} status={status} testId={testId} />;
}

const DEMAND: Record<DemandStatus, Meta> = {
  draft: { label: "Draft (not planned)", tone: "warn", icon: "file" },
  open: { label: "Open", tone: "accent", icon: "flag" },
  closed: { label: "Closed", tone: "info", icon: "lock" },
  cancelled: { label: "Cancelled", tone: "info", icon: "ban" },
};

export function DemandStatusChip({ status, testId }: { status: DemandStatus; testId?: string }) {
  return <Chip m={DEMAND[status] ?? fallback(status)} status={status} testId={testId} />;
}

const WO: Record<WoStatus, Meta> = {
  planned: { label: "Planned (firm)", tone: "warn", icon: "calendar" },
  released: { label: "Released", tone: "accent", icon: "play" },
  in_progress: { label: "In progress", tone: "accent", icon: "loader" },
  completed: { label: "Completed", tone: "ok", icon: "check" },
  closed: { label: "Closed", tone: "info", icon: "lock" },
  cancelled: { label: "Cancelled", tone: "info", icon: "ban" },
};

export function WoStatusChip({ status, testId }: { status: WoStatus; testId?: string }) {
  return <Chip m={WO[status] ?? fallback(status)} status={status} testId={testId} />;
}

const PROJECTION: Record<ProjectionStatus, Meta> = {
  on_time: { label: "On time", tone: "ok", icon: "check" },
  late: { label: "Late", tone: "danger", icon: "alert" },
  past_due: { label: "Past due", tone: "danger", icon: "clock" },
};

export function ProjectionChip({ status, lateDays }: { status: ProjectionStatus; lateDays?: number }) {
  const m = PROJECTION[status] ?? fallback(status);
  const label = status === "late" && lateDays ? `${lateDays} d late` : m.label;
  return <Chip m={{ ...m, label }} status={status} />;
}

const SEVERITY: Record<MrpSeverity, Meta> = {
  critical: { label: "Critical", tone: "danger", icon: "x" },
  warning: { label: "Warning", tone: "warn", icon: "alert" },
  info: { label: "Info", tone: "info", icon: "info" },
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
  start_in_past: { label: "Should have started", tone: "danger", icon: "clock", title: "The start date is already past: release now and expect a delay" },
  release_now: { label: "Release now", tone: "warn", icon: "play", title: "Starts within the release window" },
  later: { label: "Later", tone: "info", icon: "calendar", title: "Not due for release yet" },
};

export function ReleaseChip({ status }: { status: ReleaseStatus }) {
  return <Chip m={RELEASE[status] ?? fallback(status)} status={status} />;
}

const RUN_STATUS: Record<RunStatus, Meta> = {
  running: { label: "Running", tone: "accent", icon: "loader" },
  completed: { label: "Completed", tone: "ok", icon: "check" },
  failed: { label: "Failed", tone: "danger", icon: "x" },
};

export function RunStatusChip({ status }: { status: RunStatus }) {
  return <Chip m={RUN_STATUS[status] ?? fallback(status)} status={status} />;
}

export function RunKindBadge({ kind }: { kind: RunKind }) {
  return kind === "live" ? (
    <span className="badge accent" data-kind="live" title="Plan from today's data; planned orders can be firmed or released">
      <Icon name="play" /> Live
    </span>
  ) : (
    <span className="badge info" data-kind="what_if" title="A what-if scenario: for comparison only, nothing can be converted">
      <Icon name="help" /> What-if
    </span>
  );
}

export const LOCATION_KIND_LABEL: Record<LocationKind, string> = {
  stores: "Stores",
  line_side: "Line side",
  inspection: "Goods-in inspection",
  quarantine: "Quarantine",
};

const KIND_META: Record<LocationKind, Meta> = {
  stores: { label: "Stores", tone: "ok", icon: "layers", title: "Available for planning and kitting" },
  line_side: { label: "Line side", tone: "ok", icon: "factory", title: "Available for planning and kitting" },
  inspection: { label: "Inspection", tone: "warn", icon: "clock", title: "Available for planning after the goods-in inspection days" },
  quarantine: { label: "Quarantine", tone: "danger", icon: "ban", title: "Never used for planning or kitting" },
};

export function LocationKindBadge({ kind }: { kind: LocationKind }) {
  return <Chip m={KIND_META[kind] ?? fallback(kind)} status={kind} />;
}

export function OverdueBadge({ days }: { days: number }) {
  return (
    <span className="badge danger" data-overdue="true" title={`Dock date passed ${days} days ago and not fully received`}>
      <Icon name="clock" />
      {days > 0 ? `${days} d overdue` : "Overdue"}
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
    <span className="badge danger" title="On hold: not used for planning, cannot be issued">
      <Icon name="lock" /> On hold
    </span>
  );
}

export function SourceBadge({ source, runNo }: { source: "manual" | "mrp" | "import"; runNo?: number | null }) {
  if (source === "manual") return null;
  return (
    <span className="badge info" title={source === "mrp" ? `Created from MRP run ${runNo ?? ""}` : "Imported from a file"}>
      <Icon name={source === "mrp" ? "graph" : "upload"} />
      {source === "mrp" ? `MRP${runNo ? ` #${runNo}` : ""}` : "Imported"}
    </span>
  );
}
