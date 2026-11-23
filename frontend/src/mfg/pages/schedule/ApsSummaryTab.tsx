/** Schedule summary (M3 12, 9.4): KPI tiles, validation, bottlenecks with suggestions, late orders top 10. */
import { Link } from "react-router";
import { Icon, type IconName } from "../../../components/Icon";
import { getBottlenecks, listApsOrders } from "../../api/clientM3";
import { MfgError } from "../../components/Feedback";
import { fmtNum } from "../../lib/formatM2";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { useResourceNames } from "../../lib/resourceNames";
import { useLoad } from "../../lib/useMfg";
import { useApsRun } from "./ApsRunShell";
import { LateChain } from "./ApsOrdersTab";
import { t, t as tr } from "../../../lib/i18n";

export function ApsSummaryTab() {
  const { run } = useApsRun();
  const clock = usePlantClock();
  const s = run.summary;
  const names = useResourceNames();
  const late = useLoad((signal) => listApsOrders(run.id, { late_only: true, sort: "-late_minutes", limit: 10, offset: 0 }, signal), [run.id]);
  const bn = useLoad((signal) => getBottlenecks(run.id, signal), [run.id]);
  if (!s) return <p className="muted">{tr("mfg.apsSummaryTab.text.noResults")}</p>;
  const util = Object.entries(s.utilisation ?? {}).map(([gid, f]) => ({ gid, pct: f * 100 }));
  const top = util.length ? [...util].sort((a, b) => b.pct - a.pct)[0] : null;
  const tiles: { key: string; label: string; value: string; sub: string; icon: IconName; bad?: boolean; to: string }[] = [
    {
      key: "late",
      label: tr("mfg.apsSummaryTab.str.lateDemandLines"),
      value: String(s.demand_lines_late),
      sub: `${tr("common.nOfM", { n: s.demand_lines_on_time, m: s.demand_lines })} on time · ${s.late_orders} late orders${s.max_lateness_minutes ? ` · worst ${fmtDuration(s.max_lateness_minutes)}` : ""}`,
      icon: s.demand_lines_late ? "alert" : "check",
      bad: s.demand_lines_late > 0,
      to: mfgPaths.apsDemand(run.id),
    },
    {
      key: "overtime",
      label: s.overtime_minutes ? tr("mfg.apsSummaryTab.str.overtimeUsed") : tr("mfg.apsSummaryTab.str.overtime"),
      value: s.overtime_minutes ? fmtDuration(s.overtime_minutes) : "none",
      sub: s.overtime_minutes
        ? `cost ${fmtNum(Math.round(s.overtime_cost))}`
        : s.suggested_overtime_minutes
          ? tr("mfg.apsSummaryTab.tpl.suggestedSavesWeightedLateness", { suggestedovertimeminutes: fmtDuration(s.suggested_overtime_minutes), suggestedtardinesssaved: fmtDuration(s.suggested_tardiness_saved) })
          : tr("mfg.apsSummaryTab.str.regularShiftsOnly"),
      icon: "clock",
      to: mfgPaths.apsOvertime(run.id),
    },
    {
      key: "util",
      label: tr("mfg.apsSummaryTab.str.busiestStage"),
      value: top ? `${Math.round(top.pct)}%` : "-",
      sub: top ? `${names.group(top.gid).code} ${names.group(top.gid).name}` : "",
      icon: "factory",
      bad: Boolean(top && top.pct >= 95),
      to: mfgPaths.apsLoad(run.id),
    },
    { key: "setup", label: tr("mfg.apsSummaryTab.str.setups"), value: fmtDuration(s.setup_minutes) || "0", sub: `${s.changeovers} changeovers`, icon: "refresh", to: mfgPaths.apsGantt(run.id) },
  ];
  const unscheduled = Object.entries(s.unscheduled ?? {}).filter(([, n]) => n > 0);
  return (
    <div className="col gap-lg" data-testid="aps-summary">
      <div className="kpis">
        {tiles.map((t) => (
          <Link key={t.key} to={t.to} className="card kpi mfg-kpi" data-testid={`aps-kpi-${t.key}`}>
            <div className="kpi-label row" style={{ gap: 4 }}>
              <Icon name={t.icon} size={13} /> {t.label}
            </div>
            <div className="kpi-value" style={t.bad ? { color: "var(--danger)" } : undefined}>
              {t.value}
            </div>
            <div className="kpi-sub">{t.sub}</div>
          </Link>
        ))}
      </div>
      <div className="row wrap small muted" data-testid="aps-validation" data-ok={run.validation?.ok ? "true" : "false"}>
        {run.validation?.ok ?? s.validation_ok ? (
          <span className="badge ok">
            <Icon name="check" /> {t("mfg.apsSummaryTab.btn.allHardRulesHoldValidated")}
          </span>
        ) : (
          <span className="badge danger">
            <Icon name="x" />{" "}{tr("mfg.apsSummaryTab.text.rulesBroken", { violations: s.violations })}
          </span>
        )}
        <span>
          {tr("mfg.apsSummaryTab.text.operationsPlaced", { tr: tr("common.nOfM", { n: s.scheduled_operations, m: s.operations }), v: unscheduled.length ? ` · not placed: ${unscheduled.map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(", ")}` : "" })}
        </span>
        {s.avg_flow_days !== null ? <span>{tr("mfg.apsSummaryTab.text.averageWorkOrderFlowDays", { avgflowdays: s.avg_flow_days.toFixed(1) })}</span> : null}
        {s.budget_cut ? <span className="badge warn">{tr("mfg.apsSummaryTab.text.improvementTimeCutShort")}</span> : null}
      </div>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <section className="card" data-testid="aps-late-orders">
          <div className="card-header">
            <h3>{t("mfg.apsSummaryTab.head.latestOrders")}</h3>
            <Link to={mfgPaths.apsOrders(run.id)} className="small">
              {tr("mfg.apsSummaryTab.text.allOrders")}{" "}<Icon name="arrow-right" size={12} />
            </Link>
          </div>
          <MfgError error={late.error} onRetry={late.reload} />
          {late.data && late.data.items.length === 0 ? (
            <div className="card-body">
              <span className="badge ok">
                <Icon name="check" /> {t("mfg.apsSummaryTab.btn.noOrderIsLate")}
              </span>
            </div>
          ) : null}
          <ul className="mfg-plain-list">
            {late.data?.items.map((o) => (
              <li key={o.order.id} className="issue" data-testid="aps-late-order" data-late-minutes={o.late_minutes}>
                <span className="issue-icon" aria-hidden>
                  <Icon name="alert" />
                </span>
                <div className="grow col" style={{ gap: 2, minWidth: 0 }}>
                  <div className="row wrap" style={{ gap: 6 }}>
                    <Link to={mfgPaths.apsGantt(run.id, { view: "order", order: o.order.id })} className="mono">
                      {o.order.number}
                    </Link>
                    <span className="mono small">{o.part_number}</span>
                    <span className="badge danger">
                      <Icon name="alert" /> {fmtDuration(o.late_minutes)} late
                    </span>
                    <span className="small muted">
                      {tr("mfg.apsSummaryTab.text.dueEnds", { due: clock.dateTime(o.due), end: clock.dateTime(o.end), v: o.rank_label || `P${o.priority}` })}
                    </span>
                  </div>
                  <LateChain text={o.late_text} steps={o.late_chain} />
                </div>
              </li>
            ))}
          </ul>
        </section>
        <section className="card" data-testid="aps-bottlenecks">
          <div className="card-header">
            <h3>{t("mfg.apsSummaryTab.head.bottlenecks")}</h3>
          </div>
          <MfgError error={bn.error} onRetry={bn.reload} />
          <ul className="mfg-plain-list">
            {bn.data?.items.length === 0 ? <li className="issue muted">{tr("mfg.apsSummaryTab.text.noBottleneck")}</li> : null}
            {bn.data?.items.map((b) => (
              <li key={b.group_id} className="issue" data-testid="bottleneck-row" data-group={b.group.code}>
                <div className="grow col" style={{ gap: 2 }}>
                  <div className="row wrap" style={{ gap: 6 }}>
                    <Link to={mfgPaths.apsGantt(run.id, { view: "line", group: b.group_id })}>
                      <strong>{b.group.code}</strong> {b.group.name ?? names.group(b.group_id).name}
                    </Link>
                    <span className={`badge ${b.utilisation >= 0.95 ? "danger" : "warn"}`}>
                      <Icon name="factory" /> {Math.round(b.utilisation * 100)}% busy
                    </span>
                    {b.late_chains ? <span className="small muted">{tr("mfg.apsSummaryTab.text.holdsUpLateOrders", { latechains: b.late_chains })}</span> : null}
                  </div>
                  {b.suggestion ? (
                    <div className="small">
                      <Icon name="info" size={12} /> {b.suggestion}{" "}
                      <Link to={mfgPaths.apsOvertime(run.id)}>{tr("mfg.apsSummaryTab.text.seeOvertime")}</Link>
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
