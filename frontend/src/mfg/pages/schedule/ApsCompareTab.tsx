/**
 * Compare two schedule runs (M3 12, 9.5). When one run uses automatic overtime and the other does not (the 16 Q1
 * escalation "Re-run with automatic overtime (Allow)"), the top card states the trade-off: weighted lateness and
 * late orders saved against overtime hours and cost added. Both runs can be published from here. While the other
 * run is still calculating, its progress is shown and the comparison loads when it finishes.
 */
import { Link, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { compareApsRuns, getApsRun, listApsRuns } from "../../api/clientM3";
import type { ApsRunRecord } from "../../api/typesM3";
import { ApsProgress, PolicyBadge } from "../../components/ApsBits";
import { MfgError, Spinner } from "../../components/Feedback";
import { fmtNum } from "../../lib/formatM2";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam } from "../../lib/usePaged";
import { usePolling } from "../../lib/usePolling";
import { useResourceNames } from "../../lib/resourceNames";
import { useLoad } from "../../lib/useMfg";
import { orderLink } from "./ApsOrdersTab";
import { PublishButton, useApsRun } from "./ApsRunShell";
import { apsRunTitle, isActive } from "./ApsRunsPage";

function policyOf(r: ApsRunRecord) {
  return r.policy ?? r.summary?.policy ?? r.params?.overtime ?? null;
}

/** Labels of the compare KPIs (#198 carries only keys); all of them are "lower is better" except the listed ones. */
const KPI_LABEL: Record<string, { label: string; unit?: "min" | "num" | "pct"; higherBetter?: boolean }> = {
  weighted_tardiness: { label: "Weighted lateness", unit: "min" },
  late_demand_count: { label: "Late demand lines" },
  late_orders: { label: "Late orders" },
  late_wos: { label: "Late work orders" },
  max_lateness_minutes: { label: "Worst lateness", unit: "min" },
  overtime_minutes: { label: "Overtime", unit: "min" },
  overtime_cost: { label: "Overtime cost" },
  setup_minutes: { label: "Changeover time", unit: "min" },
  changeovers: { label: "Changeovers" },
  makespan_minutes: { label: "Time to finish everything", unit: "min" },
  avg_flow_days: { label: "Average days in production" },
  unscheduled: { label: "Operations not scheduled" },
  demand_lines_on_time: { label: "Demand lines on time", higherBetter: true },
};
const kpiText = (v: number | null, unit?: string) => (v === null ? "" : unit === "min" ? fmtDuration(v) || "0" : fmtNum(Math.round(v * 10) / 10));

function Delta({ v, unit, lowerIsBetter = true }: { v: number | null; unit?: "min" | "num"; lowerIsBetter?: boolean }) {
  if (v === null || Math.abs(v) < 1e-9) return <span className="faint">no change</span>;
  const better = lowerIsBetter ? v < 0 : v > 0;
  return (
    <span className={better ? "mfg-pos" : "mfg-neg"} data-testid="aps-compare-delta" data-delta={v}>
      <Icon name={better ? "check" : "alert"} size={12} /> {v > 0 ? "+" : "−"}
      {unit === "min" ? fmtDuration(Math.abs(v)) : fmtNum(Math.abs(Math.round(v * 10) / 10))} {better ? "better" : "worse"}
    </span>
  );
}

export function ApsCompareTab() {
  const { run, setRun } = useApsRun();
  const clock = usePlantClock();
  const names = useResourceNames();
  const [params, setParams] = useSearchParams();
  const withId = params.get("with") ?? "";
  const runs = useLoad((signal) => listApsRuns({ limit: 50, offset: 0 }, signal), []);
  const other = useLoad((signal) => (withId ? getApsRun(withId, signal) : null), [withId]);
  usePolling(other.reload, Boolean(other.data && isActive(other.data)));
  const ready = run.status === "completed" && other.data?.status === "completed";
  const cmp = useLoad((signal) => (withId && ready ? compareApsRuns(run.id, withId, signal) : null), [run.id, withId, ready]);
  const c = cmp.data;
  const choices = (runs.data?.items ?? []).filter((r) => r.id !== run.id && r.status === "completed");

  // full records of both runs (publish needs row state); the compare response only carries briefs
  const recordOf = (id: string): ApsRunRecord | null => (id === run.id ? run : other.data?.id === id ? other.data : null);

  // the trade-off between a run with automatic overtime and one without (16 Q1); `tradeoff` is B against A
  const trade = (() => {
    if (!c || !c.tradeoff) return null;
    if ((c.a.policy === "allow") === (c.b.policy === "allow")) return null;
    const allowIsB = c.b.policy === "allow";
    const sign = allowIsB ? 1 : -1;
    const t = c.tradeoff;
    return {
      allow: allowIsB ? c.b : c.a,
      base: allowIsB ? c.a : c.b,
      lateSaved: sign * t.weighted_tardiness_saved,
      lateMinutesSaved: sign * t.late_minutes_saved,
      demandSaved: sign * t.late_demand_saved,
      otHoursAdded: sign * t.overtime_hours_added,
      costAdded: sign * t.overtime_cost_added,
    };
  })();
  const kpi = (id: string, key: string) => {
    if (!c) return null;
    const k = c.kpis.find((x) => x.key === key);
    return k ? (c.a.id === id ? k.a : k.b) : null;
  };

  return (
    <div className="col gap-lg" data-testid="aps-compare">
      <div className="toolbar mfg-filters">
        <div className="field" style={{ minWidth: 340 }}>
          <label htmlFor="ac-with">Compare {apsRunTitle(run)} with</label>
          <select id="ac-with" className="select" value={withId} onChange={(e) => setSearchParam(setParams, "with", e.target.value)} data-testid="aps-compare-with">
            <option value="">Choose a run…</option>
            {withId && !choices.some((r) => r.id === withId) && other.data ? <option value={withId}>{apsRunTitle(other.data)}</option> : null}
            {choices.map((r) => (
              <option key={r.id} value={r.id}>
                {apsRunTitle(r)} ({policyOf(r) ?? "default"}, from {clock.dateTime(r.as_of)})
              </option>
            ))}
          </select>
        </div>
      </div>
      <MfgError error={runs.error ?? other.error ?? cmp.error} onRetry={cmp.reload} />
      {other.data && isActive(other.data) ? (
        <div className="card card-body row wrap" role="status" data-testid="aps-compare-waiting">
          <span>
            Waiting for <Link to={mfgPaths.apsRun(other.data.id)}>{apsRunTitle(other.data)}</Link> to finish:
          </span>
          <ApsProgress run={other.data} />
        </div>
      ) : null}
      {withId && ready && !c && cmp.loading ? <Spinner label="Comparing…" /> : null}
      {!withId ? <p className="muted">Pick a run to compare with, for example the same plan without overtime.</p> : null}

      {c && trade ? (
        <section className="card mfg-inline-form" data-testid="aps-tradeoff">
          <div className="card-header">
            <h2>Automatic overtime: what it buys</h2>
          </div>
          <div className="card-body col">
            <div className="kpis">
              <div className="card kpi" data-testid="aps-tradeoff-late">
                <div className="kpi-label">Weighted lateness saved</div>
                <div className="kpi-value" style={{ color: trade.lateSaved > 0 ? "var(--ok)" : undefined }}>
                  {fmtDuration(trade.lateSaved) || "0"}
                </div>
                <div className="kpi-sub">
                  {fmtNum(trade.demandSaved)} fewer late demand lines · {fmtDuration(trade.lateMinutesSaved) || "0"} less lateness in total
                </div>
              </div>
              <div className="card kpi" data-testid="aps-tradeoff-overtime">
                <div className="kpi-label">Overtime added</div>
                <div className="kpi-value">{trade.otHoursAdded.toFixed(1)} h</div>
                <div className="kpi-sub">cost {fmtNum(Math.round(trade.costAdded))}</div>
              </div>
            </div>
            <div className="grid-2">
              {[trade.base, trade.allow].map((r) => {
                const rec = recordOf(r.id);
                const late = kpi(r.id, "late_demand_count");
                const wt = kpi(r.id, "weighted_tardiness");
                const ot = kpi(r.id, "overtime_minutes");
                return (
                <div key={r.id} className="card card-body col" style={{ gap: 6 }} data-testid="aps-compare-run" data-policy={r.policy}>
                  <div className="row wrap">
                    <Link to={mfgPaths.apsRun(r.id)}>
                      <strong>{apsRunTitle(r)}</strong>
                    </Link>
                    <PolicyBadge policy={r.policy} />
                  </div>
                  <span className="small">
                    {late === null ? "" : `${fmtNum(late)} late demand lines · `}
                    {fmtDuration(wt ?? 0) || "0"} weighted lateness · overtime {fmtDuration(ot ?? 0) || "none"}
                  </span>
                  <div>
                    {rec ? (
                      <PublishButton run={rec} testId={`aps-publish-${r.policy === "allow" ? "allow" : "base"}`} onDone={(x) => (x.id === run.id ? setRun(x) : other.setData(x))} />
                    ) : (
                      <Link to={mfgPaths.apsRun(r.id)} className="btn sm">
                        Open to publish
                      </Link>
                    )}
                  </div>
                </div>
                );
              })}
            </div>
            <p className="faint small" style={{ margin: 0 }}>
              Publish the plan you want the plant to follow; the other stays available for reference.
            </p>
          </div>
        </section>
      ) : null}

      {c ? (
        <>
          <section className="card">
            <div className="card-header">
              <h3>Key figures</h3>
              <span className="muted small">
                A = {apsRunTitle(c.a)}, B = {apsRunTitle(c.b)}; change = B against A
              </span>
            </div>
            <div className="table-wrap">
              <table className="table" data-testid="aps-compare-kpis">
                <thead>
                  <tr>
                    <th />
                    <th className="right">A</th>
                    <th className="right">B</th>
                    <th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {c.kpis.map((k) => {
                    const m = KPI_LABEL[k.key];
                    return (
                      <tr key={k.key} data-key={k.key}>
                        <td>{m?.label ?? k.key.replace(/_/g, " ")}</td>
                        <td className="right">{kpiText(k.a, m?.unit)}</td>
                        <td className="right">{kpiText(k.b, m?.unit)}</td>
                        <td>
                          <Delta v={k.delta} unit={m?.unit === "min" ? "min" : "num"} lowerIsBetter={!m?.higherBetter} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
          <div className="grid-2" style={{ alignItems: "start" }}>
            <section className="card">
              <div className="card-header">
                <h3>Orders that end at another time ({c.orders.length})</h3>
              </div>
              <div className="table-wrap" style={{ maxHeight: 420, overflow: "auto" }}>
                <table className="table" data-testid="aps-compare-orders">
                  <thead>
                    <tr>
                      <th>Order</th>
                      <th>End A</th>
                      <th>End B</th>
                      <th>Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.orders.map((o) => (
                      <tr key={o.order.id} data-testid="aps-compare-order">
                        <td>
                          <Link to={orderLink(o.order, run.id)} className="mono">
                            {o.order.number}
                          </Link>
                        </td>
                        <td className="small">
                          {o.end_a ? clock.dateTime(o.end_a) : "not scheduled"} {o.late_a ? <span className="mfg-neg">({fmtDuration(o.late_a)} late)</span> : null}
                        </td>
                        <td className="small">
                          {o.end_b ? clock.dateTime(o.end_b) : "not scheduled"} {o.late_b ? <span className="mfg-neg">({fmtDuration(o.late_b)} late)</span> : null}
                        </td>
                        <td>
                          <Delta v={o.delta_minutes} unit="min" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {c.truncated ? <div className="card-footer small muted">Only the first 500 changes are listed.</div> : null}
            </section>
            <section className="card">
              <div className="card-header">
                <h3>Stage utilisation</h3>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th className="right">A</th>
                    <th className="right">B</th>
                  </tr>
                </thead>
                <tbody>
                  {c.utilisation.map((x) => (
                    <tr key={x.key}>
                      <td>{names.group(x.key).code}</td>
                      <td className="right">{Math.round(x.a * 100)}%</td>
                      <td className="right">{Math.round(x.b * 100)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}
