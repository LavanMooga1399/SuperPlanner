/** Dashboard tiles (M6 3.1), shared by the plant and organisation dashboards. Status = icon + text, never colour alone. */
import { Link } from "react-router";
import { Icon, type IconName } from "../../../components/Icon";
import type { DashboardPeriod, DashboardTile, TileStatus, TrendPoint } from "../../api/typesM6";
import { safeInternalLink } from "../../assistant/AnswerText";

export const PERIODS: { value: DashboardPeriod; label: string }[] = [
  { value: "4w", label: "Last 4 weeks" },
  { value: "13w", label: "Last 13 weeks" },
  { value: "52w", label: "Last 52 weeks" },
];

/** Display order and names of the known tiles; unknown ones follow in server order. */
export const TILE_NAMES: Record<string, string> = {
  otd: "On-time delivery",
  wo_on_time: "Work orders on time",
  backlog: "Backlog vs capacity",
  material_risk: "Material risk",
  adherence: "Schedule adherence",
  oee: "Equipment effectiveness (OEE-lite)",
  fpy: "First-pass yield",
  scrap_rate: "Scrap rate",
  inventory_value: "Inventory value",
  inventory_turns: "Inventory turns",
  late_pos: "Late purchase orders",
  quality: "Quality",
  integration: "ERP integration health",
};

export function orderedTiles(tiles: Record<string, DashboardTile>): [string, DashboardTile][] {
  const known = Object.keys(TILE_NAMES).filter((k) => k in tiles);
  const rest = Object.keys(tiles).filter((k) => !(k in TILE_NAMES));
  return [...known, ...rest].map((k) => [k, tiles[k]]);
}

export function tileName(key: string, t?: DashboardTile): string {
  return t?.label || TILE_NAMES[key] || key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

const STATUS: Record<string, { text: string; icon: IconName; tone: string }> = {
  ok: { text: "On track", icon: "check", tone: "ok" },
  watch: { text: "Watch", icon: "alert", tone: "warn" },
  alert: { text: "Needs attention", icon: "alert", tone: "danger" },
  na: { text: "No data yet", icon: "circle", tone: "info" },
};

export function TileStatusBadge({ status }: { status: TileStatus }) {
  const s = STATUS[status] ?? { text: String(status), icon: "info" as IconName, tone: "info" };
  return (
    <span className={`badge ${s.tone}`} data-testid="tile-status" data-status={status}>
      <Icon name={s.icon} /> {s.text}
    </span>
  );
}

export function fmtTileValue(v: number | string | null | undefined, unit: string | undefined, currency?: string): string {
  if (v === null || v === undefined) return "n/a";
  if (typeof v === "string") return v;
  switch (unit) {
    case "ratio":
      return `${(v * 100).toFixed(1)} %`;
    case "pct":
    case "percent":
      return `${v.toFixed(1)} %`;
    case "currency":
      return `${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}${currency ? ` ${currency}` : ""}`;
    case "hours":
      return `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} h`;
    case "minutes":
      return `${Math.round(v).toLocaleString()} min`;
    case "turns":
      return `${v.toFixed(1)} x`;
    case "days":
      return `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} days`;
    default:
      return `${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}${unit && unit !== "count" ? ` ${unit}` : ""}`;
  }
}

function trendValues(trend: DashboardTile["trend"]): { label: string; y: number | null }[] {
  return (trend ?? []).map((p, i) => (typeof p === "object" && p !== null ? { label: (p as TrendPoint).x, y: (p as TrendPoint).y } : { label: `#${i + 1}`, y: p as number | null }));
}

export function Sparkline({ tile, name }: { tile: DashboardTile; name: string }) {
  const vals = trendValues(tile.trend);
  const pts = vals.map((v, i) => ({ i, v: v.y })).filter((p): p is { i: number; v: number } => typeof p.v === "number");
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
  const dir = last.v > first.v ? "up" : last.v < first.v ? "down" : "flat";
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" className="kpi-spark" aria-label={`${name}: ${vals.length} points, from ${fmtTileValue(first.v, tile.unit)} to ${fmtTileValue(last.v, tile.unit)} (${dir})`}>
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={1.6} />
      <circle cx={x(last.i)} cy={y(last.v)} r={2.5} fill="var(--accent)" />
    </svg>
  );
}

function thresholdText(t: DashboardTile): string | null {
  const th = t.thresholds;
  if (!th) return null;
  const parts: string[] = [];
  if (typeof th.alert === "number") parts.push(`needs attention below ${fmtTileValue(th.alert, t.unit)}`);
  if (typeof th.watch === "number") parts.push(`watch below ${fmtTileValue(th.watch, t.unit)}`);
  return parts.length ? `Targets: ${parts.join(", ")}.` : null;
}

export function drillOf(t: DashboardTile): { label: string; to: string } | null {
  const d = t.drill;
  if (!d) return null;
  const link = typeof d === "string" ? d : d.link;
  const to = safeInternalLink(link);
  if (!to) return null;
  return { label: typeof d === "string" ? "Open the details" : d.label, to };
}

export function TileCard({ name, tile, currency, extra }: { name: string; tile: DashboardTile; currency?: string; extra?: string | null }) {
  const title = tileName(name, tile);
  const drill = drillOf(tile);
  const th = thresholdText(tile);
  return (
    <article className="card dash-tile" data-testid={`tile-${name}`} data-status={tile.status} aria-label={title}>
      <div className="card-body col" style={{ gap: 6 }}>
        <div className="row" style={{ justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
          <h3 className="dash-tile-title">{title}</h3>
          <TileStatusBadge status={tile.status} />
        </div>
        <div className="dash-tile-value" data-testid="tile-value">
          {fmtTileValue(tile.value, tile.unit, currency)}
        </div>
        {extra ? <span className="muted small">{extra}</span> : null}
        <Sparkline tile={tile} name={title} />
        {tile.details?.length ? (
          <dl className="dash-details">
            {tile.details.map((d) => (
              <div key={d.label}>
                <dt>{d.label}</dt>
                <dd>{fmtTileValue(d.value, d.unit, currency)}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {tile.note ? <span className="muted small">{tile.note}</span> : null}
        {th ? <span className="faint small">{th}</span> : null}
        {drill ? (
          <Link to={drill.to} className="small no-print" data-testid="tile-drill">
            {drill.label} <Icon name="arrow-right" size={12} />
          </Link>
        ) : null}
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
