/**
 * Shared bits of the M8 planning screens (forecast, safety stock, rate plan, sterilisation, kanban, validation):
 * status chips (icon + text, never colour alone), accuracy badges, period labels, percent and pack formatting.
 */
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Icon, type IconName } from "../../components/Icon";
import { t, type StringKey } from "../../lib/i18n";
import { formatDay, formatNumber } from "../../lib/locale";
import { mfgPaths } from "../lib/paths";
import { useItemInfo } from "../lib/itemCache";
import type { Bucket, DemandClass, ForecastMethod, RunStatus, M8ItemRef, Packs, RateRunStatus, SterStatus } from "../api/typesM8";
import "./planning.css";

type Tone = "ok" | "warn" | "danger" | "info" | "accent";
interface ChipDef {
  label: StringKey;
  tone: Tone;
  icon: IconName;
}

export function Chip({ def, value, testId }: { def: ChipDef | undefined; value: string; testId?: string }) {
  return (
    <span className={`badge ${def?.tone ?? "info"}`} data-status={value} data-testid={testId}>
      <Icon name={def?.icon ?? "info"} />
      {def ? t(def.label) : value}
    </span>
  );
}

const JOB: Record<string, ChipDef> = {
  queued: { label: "plan.status.queued", tone: "info", icon: "clock" },
  running: { label: "plan.status.running", tone: "accent", icon: "loader" },
  completed: { label: "plan.status.done", tone: "ok", icon: "check" },
  failed: { label: "plan.status.failed", tone: "danger", icon: "x" },
  cancelled: { label: "plan.status.cancelled", tone: "info", icon: "ban" },
  failed_validation: { label: "plan.status.failedValidation", tone: "danger", icon: "shield" },
};
export const JobChip = ({ s, testId }: { s: RunStatus | RateRunStatus; testId?: string }) => <Chip def={JOB[s]} value={s} testId={testId} />;
export const isRunning = (s: string | undefined | null) => s === "queued" || s === "running";

const VERSION: Record<string, ChipDef> = {
  draft: { label: "plan.version.draft", tone: "warn", icon: "file" },
  active: { label: "plan.version.active", tone: "ok", icon: "check" },
  archived: { label: "plan.version.archived", tone: "info", icon: "ban" },
};
export const VersionChip = ({ s }: { s: string }) => <Chip def={VERSION[s]} value={s} testId="fc-version-status" />;

export const STER: Record<SterStatus, ChipDef> = {
  planned: { label: "plan.ster.status.planned", tone: "info", icon: "calendar" },
  loaded: { label: "plan.ster.status.loaded", tone: "accent", icon: "box" },
  cycling: { label: "plan.ster.status.cycling", tone: "accent", icon: "refresh" },
  aerating: { label: "plan.ster.status.aerating", tone: "accent", icon: "clock" },
  awaiting_release: { label: "plan.ster.status.awaitingRelease", tone: "warn", icon: "lock" },
  released: { label: "plan.ster.status.released", tone: "ok", icon: "check" },
  failed: { label: "plan.ster.status.failed", tone: "danger", icon: "x" },
  cancelled: { label: "plan.ster.status.cancelled", tone: "info", icon: "ban" },
};
export const SterChip = ({ s }: { s: SterStatus }) => <Chip def={STER[s]} value={s} testId="ster-status" />;

const METHOD: Record<ForecastMethod, StringKey> = {
  snaive: "plan.method.snaive",
  ma: "plan.method.ma",
  ses: "plan.method.ses",
  holt_damped: "plan.method.holtDamped",
  hw_add: "plan.method.hwAdd",
  hw_mul: "plan.method.hwMul",
  croston: "plan.method.croston",
  sba: "plan.method.sba",
  zero: "plan.method.zero",
};
export const METHODS = Object.keys(METHOD) as ForecastMethod[];
export const methodText = (m: string | null | undefined) => (m ? (METHOD[m as ForecastMethod] ? t(METHOD[m as ForecastMethod]) : m) : "");

const CLASS: Record<DemandClass, StringKey> = {
  smooth: "plan.class.smooth",
  erratic: "plan.class.erratic",
  intermittent: "plan.class.intermittent",
  lumpy: "plan.class.lumpy",
  short: "plan.class.short",
};
export const classText = (c: string | null | undefined) => (c ? (CLASS[c as DemandClass] ? t(CLASS[c as DemandClass]) : c) : "");

/** Readable texts of engine codes (flags, exceptions, explanations); unknown codes stay as they are. */
const CODES: Record<string, StringKey> = {
  FC_OUTLIER: "plan.code.FC_OUTLIER",
  FC_HISTORY_SHORT: "plan.code.FC_HISTORY_SHORT",
  FC_HIGH_ERROR: "plan.code.FC_HIGH_ERROR",
  FC_OVERCONSUMED: "plan.code.FC_OVERCONSUMED",
  SS_CAPPED: "plan.code.SS_CAPPED",
  SS_NO_COST: "plan.code.SS_NO_COST",
  RATE_CAPACITY: "plan.code.RATE_CAPACITY",
  RATE_NO_LINE: "plan.code.RATE_NO_LINE",
  RATE_MIN_CAMPAIGN: "plan.code.RATE_MIN_CAMPAIGN",
  RATE_CHANGEOVER_BOUND: "plan.code.RATE_CHANGEOVER_BOUND",
  RATE_MATERIAL_SHORT: "plan.code.RATE_MATERIAL_SHORT",
  RATE_SPLIT: "plan.code.RATE_SPLIT",
  STER_AERATION_BOUND: "plan.code.STER_AERATION_BOUND",
  STER_NO_PALLET: "plan.code.STER_NO_PALLET",
  MRP_FORECAST_SHORT: "plan.code.MRP_FORECAST_SHORT",
  MRP_RATE_SHORT: "plan.code.MRP_RATE_SHORT",
  MRP_KANBAN_UNDERSIZED: "plan.code.MRP_KANBAN_UNDERSIZED",
  MRP_PACK_ROUNDING: "plan.code.MRP_PACK_ROUNDING",
};
export const codeText = (c: string) => (CODES[c] ? t(CODES[c]) : c.replace(/_/g, " ").toLowerCase());
export const FLAG_CODES = ["FC_OUTLIER", "FC_HISTORY_SHORT", "FC_HIGH_ERROR"];

/** 0.183 -> "18.3 %"; null -> "–". */
export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return `${formatNumber(v * 100, digits)} %`;
}
/** Signed percent for bias: "+4.2 %", "−3.0 %". */
export function signedPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const s = formatNumber(Math.abs(v * 100), 1);
  return v > 0.0005 ? `+${s} %` : v < -0.0005 ? `−${s} %` : `${s} %`;
}
export const num = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? "–" : formatNumber(v, digits));

/** WAPE badge: within 25 % on track, up to 50 % watch, above needs attention (A items flag `FC_HIGH_ERROR` there). */
export function WapeBadge({ v }: { v: number | null | undefined }) {
  if (v === null || v === undefined) return <span className="muted">–</span>;
  const tone: Tone = v <= 0.25 ? "ok" : v <= 0.5 ? "warn" : "danger";
  const icon: IconName = tone === "ok" ? "check" : "alert";
  return (
    <span className={`badge ${tone} pl-num-badge`} title={t("plan.fc.hint.wape")} data-testid="wape-badge" data-tone={tone}>
      <Icon name={icon} />
      {pct(v, 0)}
    </span>
  );
}
/** Bias: plain signed text; beyond +-10 % a warning badge with "over"/"under". */
export function BiasBadge({ v }: { v: number | null | undefined }) {
  if (v === null || v === undefined) return <span className="muted">–</span>;
  if (Math.abs(v) <= 0.1) return <span className="pl-num">{signedPct(v)}</span>;
  return (
    <span className="badge warn pl-num-badge" title={v > 0 ? t("plan.fc.hint.biasOver") : t("plan.fc.hint.biasUnder")}>
      <Icon name="alert" />
      {signedPct(v)}
    </span>
  );
}

/** "AX" class tag: plain mono text, the class is the information (no colour coding). */
export const ClassTag = ({ abc, xyz }: { abc: string | null | undefined; xyz?: string | null }) =>
  abc || xyz ? <span className="mono pl-class">{`${abc ?? "–"}${xyz ?? ""}`}</span> : <span className="muted">–</span>;

export function ItemLink({ item }: { item: M8ItemRef | null | undefined }) {
  if (!item) return <span className="muted">–</span>;
  return (
    <span className="pl-item mfg-ellipsis" title={`${item.part_number} ${item.name}`}>
      <Link to={mfgPaths.item(item.id)} className="mono" onClick={(e) => e.stopPropagation()} tabIndex={-1}>
        {item.part_number}
      </Link>{" "}
      <span className="muted">{item.name}</span>
    </span>
  );
}
export const itemLabel = (item: M8ItemRef | null | undefined) => (item ? `${item.part_number} ${item.name}` : "");

const MON: StringKey[] = ["mfg.format.str.jan", "mfg.format.str.feb", "mfg.format.str.mar", "mfg.format.str.apr", "mfg.format.str.may", "mfg.format.str.jun", "mfg.format.str.jul", "mfg.format.str.aug", "mfg.format.str.sep", "mfg.format.str.oct", "mfg.format.str.nov", "mfg.format.str.dec"];
/** Monthly "Mar 2027", weekly "8 Mar 2027" (the Monday). */
export function periodLabel(p: string, bucket: Bucket): string {
  const m = p.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return p;
  if (bucket === "m") return t("plan.tpl.month", { m: t(MON[Number(m[2]) - 1]), y: m[1] });
  return formatDay(p);
}
/** Short axis label: "Mar 27" / "8 Mar". */
export function periodShort(p: string, bucket: Bucket): string {
  const m = p.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return p;
  if (bucket === "m") return t("plan.tpl.month", { m: t(MON[Number(m[2]) - 1]), y: m[1].slice(2) });
  return `${Number(m[3])} ${t(MON[Number(m[2]) - 1])}`;
}

/** Quantities of packaged items: "12 cases / 0.5 pallet" (6). */
export function packsText(p: Packs | null | undefined): string {
  if (!p) return "";
  const parts: string[] = [];
  if (p.case !== null && p.case !== undefined) parts.push(t("plan.tpl.cases", { n: formatNumber(p.case, 1) }));
  if (p.pallet !== null && p.pallet !== undefined) parts.push(t("plan.tpl.pallets", { n: formatNumber(p.pallet, 1) }));
  return parts.join(" / ");
}

/** Label/value facts in a dense grid (detail panels). */
export function Facts({ rows, testId }: { rows: [string, ReactNode][]; testId?: string }) {
  return (
    <dl className="pl-facts" data-testid={testId}>
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Segmented control for quick filters / view switches (FilterBar `btn-group`). */
export function Segmented<V extends string>({ value, options, onChange, label, testId }: { value: V; options: { value: V; label: string }[]; onChange(v: V): void; label: string; testId?: string }) {
  return (
    <div className="btn-group" role="group" aria-label={label} data-testid={testId}>
      {options.map((o) => (
        <button key={o.value} type="button" className="btn sm" aria-pressed={value === o.value} onClick={() => onChange(o.value)} data-value={o.value}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

const CARD: Record<string, ChipDef> = {
  full: { label: "plan.kb.state.full", tone: "ok", icon: "check" },
  empty: { label: "plan.kb.state.empty", tone: "warn", icon: "circle" },
  in_process: { label: "plan.kb.state.inProcess", tone: "accent", icon: "truck" },
};
export const CardChip = ({ s }: { s: string }) => <Chip def={CARD[s]} value={s} testId="kb-card-state" />;
export const cardStateText = (s: string) => (CARD[s] ? t(CARD[s].label) : s);

/** Part number and name of an item known only by id (cached item record). */
export function ItemById({ id, part }: { id: string | null | undefined; part?: string | null }) {
  const info = useItemInfo(id);
  if (!id) return <span className="muted">–</span>;
  return (
    <span className="pl-item mfg-ellipsis" title={info ? `${info.part_number} ${info.description}` : part ?? id}>
      <Link to={mfgPaths.item(id)} className="mono" onClick={(e) => e.stopPropagation()} tabIndex={-1}>
        {info?.part_number ?? part ?? "…"}
      </Link>{" "}
      {info ? <span className="muted">{info.description}</span> : null}
    </span>
  );
}

/** Stable chart colour per key (item): `--pl-c1..8`, always shown with the part number next to it. */
export function colorOf(key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return `var(--pl-c${(h % 8) + 1})`;
}
