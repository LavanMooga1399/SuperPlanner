/** KPI tiles of an MRP run (M2 14.2 `RunKpis`): late demand, short parts, planned make/buy, release now. */
import { Link } from "react-router";
import { Icon, type IconName } from "../../components/Icon";
import type { MrpRunRecord } from "../api/typesM2";
import { mfgPaths } from "../lib/paths";
import { t as tr } from "../../lib/i18n";

export function RunKpis({ run }: { run: MrpRunRecord }) {
  const s = run.summary;
  if (!s) return null;
  const tiles: { key: string; label: string; value: number; sub: string; icon: IconName; bad?: boolean; to: string }[] = [
    {
      key: "late",
      label: tr("mfg.runKpis.str.lateDemandLines"),
      value: s.demand_late + s.demand_past_due,
      sub: tr("mfg.runKpis.tpl.onTime", { tr: tr("common.nOfM", { n: s.demand_on_time, m: s.demand_lines }), v: s.max_late_days ? tr("mfg.runKpis.tpl.worstD", { maxlatedays: s.max_late_days }) : "" }),
      icon: s.demand_late + s.demand_past_due ? "alert" : "check",
      bad: s.demand_late + s.demand_past_due > 0,
      to: mfgPaths.runDemand(run.id),
    },
    { key: "short", label: tr("mfg.runKpis.str.partsShort"), value: s.items_short, sub: tr("mfg.runKpis.tpl.ofPartsPlanned", { items: s.items.toLocaleString("en-IN") }), icon: s.items_short ? "alert" : "check", bad: s.items_short > 0, to: `${mfgPaths.runItems(run.id)}?short=1` },
    { key: "planned_make", label: tr("mfg.runKpis.str.plannedWorkOrders"), value: s.planned_make, sub: tr("mfg.runKpis.str.toMake"), icon: "factory", to: `${mfgPaths.runPlanned(run.id)}?kind=make` },
    { key: "planned_buy", label: tr("mfg.runKpis.str.plannedPurchases"), value: s.planned_buy, sub: tr("mfg.runKpis.str.toBuy"), icon: "briefcase", to: `${mfgPaths.runPlanned(run.id)}?kind=buy` },
    {
      key: "release_now",
      label: tr("mfg.runKpis.str.releaseNow"),
      value: s.release_now,
      sub: s.start_in_past ? tr("mfg.runKpis.tpl.shouldHaveStarted", { startinpast: s.start_in_past }) : tr("mfg.runKpis.str.startWithinTheReleaseWindow"),
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
            {t.value.toLocaleString("en-IN")}
          </div>
          <div className="kpi-sub">{t.sub}</div>
        </Link>
      ))}
    </div>
  );
}
