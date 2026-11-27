/**
 * Shared bits of the M9 screens (network, S&OP, trade): node names, KPI cards with units and deltas, engine code
 * texts, heat tones (value text in every cell, icon past the limit) and money in the report currency.
 */
import { useCallback, useMemo, type ReactNode } from "react";
import { Icon, type IconName } from "../../components/Icon";
import { hasKey, t, type StringKey } from "../../lib/i18n";
import { formatMoney, formatNumber, formatSigned } from "../../lib/locale";
import { listNodes } from "../api/clientM9";
import type { M9Explanation, MilestoneStatus, NetNodeInfo, SopStatus, SopStep } from "../api/typesM9";
import { useLoad } from "../lib/useMfg";
import { Chip, periodLabel, periodShort } from "../forecast/shared";
import "./network.css";

export { JobChip, isRunning, num, pct, Facts, Segmented, periodLabel, periodShort } from "../forecast/shared";

export const monthLabel = (m: string) => periodLabel(m, "m");
export const monthShort = (m: string) => periodShort(m, "m");
export const weekShort = (w: string) => periodShort(w, "w");

/** The org's nodes (plants and DCs), looked up by owner id; scenario-only nodes are shown by their code. */
export function useNodes() {
  const res = useLoad((s) => listNodes(s), []);
  const byId = useMemo(() => new Map((res.data?.items ?? []).map((n) => [n.owner_id, n])), [res.data]);
  const code = useCallback((id: string | null | undefined) => (id ? byId.get(id)?.code ?? id : t("net.label.allNodes")), [byId]);
  return { nodes: res.data?.items ?? [], byId, code, loading: res.loading, error: res.error, reload: res.reload };
}

export function NodeTag({ node, id }: { node: NetNodeInfo | undefined; id?: string | null }) {
  if (!node) return <span className="mono">{id ?? "–"}</span>;
  const icon: IconName = node.kind === "dc" ? "box" : "factory";
  return (
    <span className="row" style={{ gap: 4, display: "inline-flex" }} title={t("net.tpl.nodeTitle", { name: node.name, kind: kindText(node.kind), country: node.country ?? "–", ccy: node.currency })}>
      <Icon name={icon} size={14} />
      <span className="mono">{node.code}</span>
    </span>
  );
}
export const kindText = (k: string) => (k === "dc" ? t("net.kind.dc") : k === "network" ? t("net.kind.network") : t("net.kind.plant"));

export function money(x: number | null | undefined, ccy: string, digits = 0) {
  return formatMoney(x, ccy, { digits });
}

/** Executive KPI card: label, value with unit, optional sub-line and delta versus the baseline. */
export function KpiCard({ label, value, unit, sub, delta, testId }: { label: string; value: ReactNode; unit?: string; sub?: ReactNode; delta?: ReactNode; testId?: string }) {
  return (
    <div className="card net-kpi" data-testid={testId}>
      <span className="net-kpi-label">{label}</span>
      <span className="net-kpi-value">
        {value}
        {unit ? <span className="net-kpi-unit">{unit}</span> : null}
      </span>
      {delta ? <span>{delta}</span> : null}
      {sub ? <span className="net-kpi-sub">{sub}</span> : null}
    </div>
  );
}

/**
 * Delta versus the baseline (`pts` = difference of two percentages given as 0..100): sign, value and a word (better / worse), tone by direction - never colour alone.
 * `better` says which direction is good (service up, unmet down); `kind` picks the formatter.
 */
export function Delta({ v, better, kind = "num", ccy = "USD", digits = 0 }: { v: number | null | undefined; better: "up" | "down"; kind?: "num" | "money" | "pts"; ccy?: string; digits?: number }) {
  if (v === null || v === undefined || !Number.isFinite(v)) return <span className="net-delta flat">–</span>;
  const flat = Math.abs(v) < (kind === "pts" ? 0.05 : 0.5);
  const good = !flat && (better === "up" ? v > 0 : v < 0);
  const text = kind === "money" ? formatMoney(v, ccy, { compact: Math.abs(v) >= 100000, signed: true }) : kind === "pts" ? t("net.tpl.pts", { v: formatSigned(v, 1) }) : formatSigned(v, digits);
  return (
    <span className={`net-delta ${flat ? "flat" : good ? "good" : "bad"}`} data-testid="kpi-delta" data-dir={flat ? "flat" : good ? "better" : "worse"}>
      <Icon name={flat ? "circle" : good ? "check" : "alert"} size={12} />
      {text}
      <span className="sr-only"> {flat ? t("net.delta.same") : good ? t("net.delta.better") : t("net.delta.worse")}</span>
    </span>
  );
}

/** Utilisation heat class: up to 85 % shades, 85-100 % watch, > 100 % alert (6.4). */
export function heatClass(u: number | null | undefined): string {
  if (u === null || u === undefined || !Number.isFinite(u)) return "h0";
  if (u > 1.0001) return "alert";
  if (u > 0.85) return "watch";
  return u > 0.5 ? "h2" : u > 0 ? "h1" : "h0";
}
export function HeatValue({ u }: { u: number | null | undefined }) {
  if (u === null || u === undefined) return <span className="muted">–</span>;
  const c = heatClass(u);
  return (
    <>
      {c === "alert" ? <Icon name="alert" size={12} /> : c === "watch" ? <Icon name="clock" size={12} /> : null}
      {formatNumber(u * 100, 0)}
    </>
  );
}

/** Texts of engine codes (shortage causes, warnings, flags); unknown codes stay readable. */
export function codeText9(code: string): string {
  const k = `net.code.${code}`;
  return hasKey(k) ? t(k as StringKey) : code.replace(/_/g, " ").toLowerCase();
}
export function ExplanationText({ e }: { e: M9Explanation }) {
  return <span>{codeText9(e.code)}</span>;
}

const CAUSE_ICON: Record<string, IconName> = {
  NET_CAPACITY_SHORT: "factory",
  NET_NO_SOURCE: "ban",
  NET_LEAD_TIME: "clock",
  NET_SUPPLIER_CAP: "truck",
};
export function CauseChip({ cause }: { cause: string }) {
  return (
    <span className="badge danger" data-testid="net-cause" data-cause={cause}>
      <Icon name={CAUSE_ICON[cause] ?? "alert"} />
      {codeText9(cause)}
    </span>
  );
}

type Tone = "ok" | "warn" | "danger" | "info" | "accent";
const STEP_DEF: Record<SopStatus, { label: StringKey; tone: Tone; icon: IconName }> = {
  draft: { label: "net.sop.step.draft", tone: "info", icon: "file" },
  demand_review: { label: "net.sop.step.demand_review", tone: "accent", icon: "flag" },
  supply_review: { label: "net.sop.step.supply_review", tone: "accent", icon: "factory" },
  pre_sop: { label: "net.sop.step.pre_sop", tone: "accent", icon: "compare" },
  executive: { label: "net.sop.step.executive", tone: "warn", icon: "lock" },
  approved: { label: "net.sop.step.approved", tone: "ok", icon: "check" },
  published: { label: "net.sop.step.published", tone: "ok", icon: "flag" },
  cancelled: { label: "net.sop.step.cancelled", tone: "info", icon: "ban" },
};
export const stepText = (s: SopStatus | SopStep) => t(STEP_DEF[s]?.label ?? "net.sop.step.draft");
export const CycleChip = ({ s, testId }: { s: SopStatus; testId?: string }) => <Chip def={STEP_DEF[s]} value={s} testId={testId ?? "sop-status"} />;

const MS: Record<MilestoneStatus, { label: StringKey; tone: Tone; icon: IconName }> = {
  met: { label: "net.trd.status.met", tone: "ok", icon: "check" },
  at_risk: { label: "net.trd.status.at_risk", tone: "warn", icon: "alert" },
  missed: { label: "net.trd.status.missed", tone: "danger", icon: "x" },
};
export const MilestoneChip = ({ s }: { s: MilestoneStatus }) => <Chip def={MS[s]} value={s} testId="trd-status" />;
export const milestoneText = (s: MilestoneStatus) => t(MS[s].label);

/** Percent of a 0..100 value ("97.5 %"). */
export const pct100 = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? "–" : `${formatNumber(v, digits)} %`);

/** Today's date (browser) as YYYY-MM-DD. */
export function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
/** First day of next month as YYYY-MM-DD. */
export function nextMonthIso(): string {
  const d = new Date();
  const n = new Date(d.getFullYear(), d.getMonth() + 1, 1);
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-01`;
}
