/** KPI tiles of an MRP run (M2 14.2 `RunKpis`): late demand, short parts, planned make/buy, release now. */
import { Link } from "react-router";
import { Icon, type IconName } from "../../components/Icon";
import type { MrpRunRecord } from "../api/typesM2";
import { mfgPaths } from "../lib/paths";

export function RunKpis({ run }: { run: MrpRunRecord }) {
  const s = run.summary;
  if (!s) return null;
  const tiles: { key: string; label: string; value: number; sub: string; icon: IconName; bad?: boolean; to: string }[] = [
    {
      key: "late",
      label: "Late demand lines",
      value: s.demand_late + s.demand_past_due,
      sub: `${s.demand_on_time} of ${s.demand_lines} on time${s.max_late_days ? ` · worst ${s.max_late_days} d` : ""}`,
      icon: s.demand_late + s.demand_past_due ? "alert" : "check",
      bad: s.demand_late + s.demand_past_due > 0,
      to: mfgPaths.runDemand(run.id),
    },
    { key: "short", label: "Parts short", value: s.items_short, sub: `of ${s.items.toLocaleString()} parts planned`, icon: s.items_short ? "alert" : "check", bad: s.items_short > 0, to: `${mfgPaths.runItems(run.id)}?short=1` },
    { key: "planned_make", label: "Planned work orders", value: s.planned_make, sub: "to make", icon: "factory", to: `${mfgPaths.runPlanned(run.id)}?kind=make` },
    { key: "planned_buy", label: "Planned purchases", value: s.planned_buy, sub: "to buy", icon: "briefcase", to: `${mfgPaths.runPlanned(run.id)}?kind=buy` },
    {
      key: "release_now",
      label: "Release now",
      value: s.release_now,
      sub: s.start_in_past ? `${s.start_in_past} should have started` : "start within the release window",
      icon: "play",
      bad: s.start_in_past > 0,
      to: `${mfgPaths.runPlanned(run.id)}?release=release_now`,
    },
  ];
  return (
    <div className="kpis" data-testid="run-kpis">
      {tiles.map((t) => (
        <Link key={t.key} to={t.to} className="card kpi mfg-kpi" data-testid={`run-kpi-${t.key}`} data-value={t.value}>
          <div className="kpi-label row" style={{ gap: 4 }}>
            <Icon name={t.icon} size={13} /> {t.label}
          </div>
          <div className="kpi-value" style={t.bad ? { color: "var(--danger)" } : undefined}>
            {t.value.toLocaleString()}
          </div>
          <div className="kpi-sub">{t.sub}</div>
        </Link>
      ))}
    </div>
  );
}
