/**
 * Dashboard tiles (M6 3.1), shared by the plant and organisation dashboards. Status = icon + text, never colour
 * alone. Tile details are tile-specific dicts (`model_m6.Tile.details`); they are shown as label / value pairs with
 * the units the key names imply (fractions as percent, `_h` as hours, `value*` in the plant currency).
 */
import { Link } from "react-router";
import { Icon, type IconName } from "../../../components/Icon";
import type { DashboardPeriod, DashboardTile, TileStatus } from "../../api/typesM6";
import { safeInternalLink } from "../../assistant/AnswerText";

export const PERIODS: { value: DashboardPeriod; label: string }[] = [
  { value: "4w", label: "Last 4 weeks" },
  { value: "13w", label: "Last 13 weeks" },
  { value: "52w", label: "Last 52 weeks" },
];

/** Display order and names of the S0 tiles (`model_m6.TILE_NAMES`); unknown ones follow in server order. */
export const TILE_NAMES: Record<string, { name: string; help: string }> = {
  otd: { name: "On-time delivery", help: "Demand lines shipped on time" },
  backlog: { name: "Backlog vs capacity", help: "Load of the next 4 weeks against base capacity" },
  material_risk: { name: "Material risk", help: "Items short within 4 weeks" },
  execution: { name: "Execution", help: "Schedule adherence" },
  inventory: { name: "Inventory", help: "Value on hand at standard cost" },
  late_pos: { name: "Late purchase orders", help: "Open overdue deliveries" },
  quality: { name: "Quality", help: "Open recalls" },
  integration: { name: "ERP integration", help: "Problems needing attention" },
};

export function orderedTiles(tiles: Record<string, DashboardTile>): [string, DashboardTile][] {
  const known = Object.keys(TILE_NAMES).filter((k) => k in tiles);
  const rest = Object.keys(tiles).filter((k) => !(k in TILE_NAMES));
  return [...known, ...rest].map((k) => [k, tiles[k]]);
}

export function humanize(key: string): string {
  const w = key
    .replace(/_4w$/, " (4 weeks)")
    .replace(/_8w$/, " (8 weeks)")
    .replace(/_7d$/, " (7 days)")
    .replace(/_12m$/, " (12 months)")
    .replace(/^weeks_(\d+)$/, "next $1 weeks")
    .replace(/_h$/, "")
    .replace(/_/g, " ");
  return w.replace(/\b(oee|fpy|otd|wo|eco|ecos|po|pos)\b/gi, (m) => m.toUpperCase()).replace(/^./, (c) => c.toUpperCase());
}

export function tileName(key: string): string {
  return TILE_NAMES[key]?.name ?? humanize(key);
}

const STATUS: Record<string, { text: string; icon: IconName; tone: string }> = {
  ok: { text: "On track", icon: "check", tone: "ok" },
  watch: { text: "Watch", icon: "alert", tone: "warn" },
  alert: { text: "Needs attention", icon: "alert", tone: "danger" },
  "n/a": { text: "No data yet", icon: "circle", tone: "info" },
};

export function TileStatusBadge({ status }: { status: TileStatus }) {
  const s = STATUS[status] ?? { text: String(status), icon: "info" as IconName, tone: "info" };
  return (
    <span className={`badge ${s.tone}`} data-testid="tile-status" data-status={status}>
      <Icon name={s.icon} /> {s.text}
    </span>
  );
}

const pct = (v: number) => `${(v * 100).toFixed(1).replace(/\.0$/, "")} %`;
const num = (v: number, digits = 1) => v.toLocaleString(undefined, { maximumFractionDigits: digits });

/** Tile value in its unit: "%" is a fraction (0.91 = 91 %), "count", "h", "turns", else a currency code. */
export function fmtValue(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined) return "n/a";
  switch (unit) {
    case "%":
      return pct(v);
    case "count":
    case "":
      return num(v, 0);
    case "h":
      return `${num(v)} h`;
    case "turns":
      return `${num(v)} turns`;
    default:
      return `${unit} ${num(v, 0)}`;
  }
}

const PCT_KEYS = /(^|_)(load|adherence|oee|fpy|scrap_rate|wo_on_time|otd|lateness|utilisation|ratio|share)(_|$)/;
const SKIP_KEYS = new Set(["id", "currency", "weights", "turns_note"]);

/** One detail value by its key: fractions as %, `_h` hours, `value*` in currency, booleans as yes / no. */
export function fmtDetail(key: string, v: unknown, currency?: string): string {
  if (v === null || v === undefined) return "n/a";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") {
    if (PCT_KEYS.test(key)) return pct(v);
    if (/_h$/.test(key)) return `${num(v)} h`;
    if (/(^|_)value(_|$)/.test(key)) return currency ? `${currency} ${num(v, 0)}` : num(v, 0);
    return num(v);
  }
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.map((x) => fmtObject(x, currency)).join("; ");
  return fmtObject(v, currency);
}

function fmtObject(o: unknown, currency?: string): string {
  if (o === null || typeof o !== "object") return fmtDetail("", o, currency);
  const rec = o as Record<string, unknown>;
  // a reference {id, code, name} reads as "AVN Avnet"
  if ("name" in rec && ("code" in rec || "id" in rec) && Object.keys(rec).every((k) => ["id", "code", "name"].includes(k)))
    return [rec.code, rec.name].filter(Boolean).join(" ");
  return Object.entries(rec)
    .filter(([k]) => !SKIP_KEYS.has(k) && !k.endsWith("_id"))
    .map(([k, x]) => {
      if (x !== null && typeof x === "object") return fmtObject(x, currency);
      if (typeof x === "string") return x;
      return `${humanize(k).toLowerCase()} ${fmtDetail(k, x, currency)}`;
    })
    .join(", ");
}

export function Sparkline({ tile, name }: { tile: DashboardTile; name: string }) {
  const vals = tile.trend ?? [];
  const pts = vals.map((v, i) => ({ i, v: v.value })).filter((p): p is { i: number; v: number } => typeof p.v === "number");
  if (pts.length < 2) return null;
  const W = 160;
  const H = 36;
  const min = Math.min(...pts.map((p) => p.v));
  const max = Math.max(...pts.map((p) => p.v));
  const span = max - min || 1;
  const x = (i: number) => (i / Math.max(1, vals.length - 1)) * (W - 4) + 2;
  const y = (v: number) => H - 3 - ((v - min) / span) * (H - 6);
  const d = pts.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const first = pts[0];
  const last = pts[pts.length - 1];
  const dir = last.v > first.v ? "rising" : last.v < first.v ? "falling" : "flat";
  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      className="kpi-spark"
      aria-label={`${name}: ${vals[0]?.period ?? ""} to ${vals[vals.length - 1]?.period ?? ""}, from ${fmtValue(first.v, tile.unit)} to ${fmtValue(last.v, tile.unit)} (${dir})`}
    >
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={1.6} />
      <circle cx={x(last.i)} cy={y(last.v)} r={2.5} fill="var(--accent)" />
    </svg>
  );
}

export function thresholdText(t: DashboardTile): string | null {
  const th = t.thresholds ?? {};
  const f = (v: unknown) => (typeof v === "number" ? fmtValue(v, t.unit) : null);
  const parts: string[] = [];
  if (f(th.alert_below)) parts.push(`needs attention below ${f(th.alert_below)}`);
  if (f(th.watch_below)) parts.push(`watch below ${f(th.watch_below)}`);
  if (f(th.watch_above)) parts.push(`watch above ${f(th.watch_above)}`);
  if (f(th.alert_above)) parts.push(`needs attention above ${f(th.alert_above)}`);
  return parts.length ? `Targets: ${parts.join(", ")}.` : null;
}

export function drillLinks(t: DashboardTile): { label: string; to: string }[] {
  return (t.drill ?? []).map((d) => ({ label: d.label, to: safeInternalLink(d.path) })).filter((d): d is { label: string; to: string } => Boolean(d.to));
}

function DetailList({ details, currency }: { details: Record<string, unknown>; currency?: string }) {
  const rows = Object.entries(details ?? {}).filter(([k, v]) => !SKIP_KEYS.has(k) && !(k === "turns" && v === null && "turns_note" in details));
  const note = typeof details?.turns_note === "string" && details.turns === null ? details.turns_note : null;
  if (!rows.length && !note) return null;
  return (
    <dl className="dash-details">
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{humanize(k)}</dt>
          <dd>{fmtDetail(k, v, currency)}</dd>
        </div>
      ))}
      {note ? (
        <div>
          <dt>Turns</dt>
          <dd>n/a ({note})</dd>
        </div>
      ) : null}
    </dl>
  );
}

export function TileCard({ name, tile, currency, extra }: { name: string; tile: DashboardTile; currency?: string; extra?: string | null }) {
  const title = tileName(name);
  const links = drillLinks(tile);
  const th = thresholdText(tile);
  const cur = typeof tile.details?.currency === "string" ? tile.details.currency : currency;
  return (
    <article className="card dash-tile" data-testid={`tile-${name}`} data-status={tile.status} aria-label={title}>
      <div className="card-body col" style={{ gap: 6 }}>
        <div className="row" style={{ justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
          <h3 className="dash-tile-title">{title}</h3>
          <TileStatusBadge status={tile.status} />
        </div>
        <div className="dash-tile-value" data-testid="tile-value">
          {fmtValue(tile.value, tile.unit)}
        </div>
        <span className="muted small">{extra ?? TILE_NAMES[name]?.help ?? ""}</span>
        <Sparkline tile={tile} name={title} />
        <DetailList details={tile.details} currency={cur} />
        {tile.note ? <span className="muted small">{tile.note}</span> : null}
        {th ? <span className="faint small">{th}</span> : null}
        {links.map((d) => (
          <Link key={d.to} to={d.to} className="small no-print" data-testid="tile-drill">
            {d.label} <Icon name="arrow-right" size={12} />
          </Link>
        ))}
      </div>
    </article>
  );
}

export function PeriodSelect({ value, onChange }: { value: DashboardPeriod; onChange(v: DashboardPeriod): void }) {
  return (
    <div className="field" style={{ margin: 0 }}>
      <label htmlFor="dash-period" className="sr-only">
        Period
      </label>
      <select id="dash-period" className="select" value={value} onChange={(e) => onChange(e.target.value as DashboardPeriod)} data-testid="dash-period">
        {PERIODS.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function isPeriod(v: string | null): v is DashboardPeriod {
  return v === "4w" || v === "13w" || v === "52w";
}
