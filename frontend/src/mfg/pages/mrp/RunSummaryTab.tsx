/** Run summary (M2 14.2 `RunSummaryTab`): KPI tiles, exceptions by code, the 10 latest demand lines with why. */
import { Link } from "react-router";
import { Icon } from "../../../components/Icon";
import { listRunDemand } from "../../api/clientM2";
import { MRP_SEVERITIES, type MrpSeverity } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { RunKpis } from "../../components/RunKpis";
import { MrpSeverityBadge } from "../../components/StatusM2";
import { fmtDate } from "../../lib/format";
import { exceptionLabel } from "../../lib/mrpText";
import { mfgPaths } from "../../lib/paths";
import { useLoad } from "../../lib/useMfg";
import { LimitingPath } from "./DemandProjectionTab";
import { useRun } from "./RunShell";

const CODE_SEVERITY: Record<string, MrpSeverity> = {
  MRP_DEMAND_LATE: "critical",
  MRP_DEMAND_PAST_DUE: "critical",
  MRP_SHORTAGE: "warning",
  MRP_START_IN_PAST: "warning",
  MRP_EXPEDITE: "warning",
  MRP_PAST_DUE_SUPPLY: "warning",
  MRP_WO_LATE: "warning",
  MRP_EXPIRED_STOCK: "warning",
  MRP_EXPIRING_STOCK: "warning",
  MRP_CANCEL: "warning",
  MRP_DEMAND_SERIAL_OVERLAP: "warning",
  MRP_WO_COMPONENT_CYCLE: "warning",
};
export const severityOfCode = (code: string): MrpSeverity => CODE_SEVERITY[code] ?? "info";

export function RunSummaryTab() {
  const { run } = useRun();
  const late = useLoad((signal) => (run.status === "completed" ? listRunDemand(run.id, { late_only: true, sort: "-late_days", limit: 10, offset: 0 }, signal) : null), [run.id]);
  const s = run.summary;
  if (!s) return <p className="muted">No results{run.status === "running" ? " yet: the run is still in progress." : "."}</p>;
  const codes = Object.entries(s.exceptions.by_code)
    .filter(([, n]) => n > 0)
    .sort((a, b) => MRP_SEVERITIES.indexOf(severityOfCode(a[0])) - MRP_SEVERITIES.indexOf(severityOfCode(b[0])) || b[1] - a[1]);
  return (
    <div className="col gap-lg" data-testid="run-summary">
      <RunKpis run={run} />
      <div className="grid-2" style={{ alignItems: "start" }}>
        <section className="card" data-testid="run-late-demand">
          <div className="card-header">
            <h3>Latest demand lines</h3>
            <Link to={mfgPaths.runDemand(run.id)} className="small">
              All demand <Icon name="arrow-right" size={12} />
            </Link>
          </div>
          <MfgError error={late.error} onRetry={late.reload} />
          {late.data && late.data.items.length === 0 ? (
            <div className="card-body">
              <span className="badge ok">
                <Icon name="check" /> Every demand line is on time
              </span>
            </div>
          ) : null}
          <ul className="mfg-plain-list">
            {late.data?.items.map((d) => (
              <li key={d.demand_line_id ?? `${d.item.id}-${d.due_date}`} className="issue" data-testid="demand-line" data-late-days={d.late_days}>
                <span className="issue-icon" aria-hidden>
                  <Icon name="alert" />
                </span>
                <div className="grow col" style={{ gap: 2, minWidth: 0 }}>
                  <div className="row wrap" style={{ gap: 6 }}>
                    {d.link ? (
                      <Link to={d.link} className="mono">
                        {d.order ? `${d.order.number}/${d.line_no}` : "What-if demand"}
                      </Link>
                    ) : (
                      <span className="mono">{d.order ? `${d.order.number}/${d.line_no}` : "What-if demand"}</span>
                    )}
                    <span>
                      {d.qty} x <span className="mono">{d.item.part_number}</span>
                    </span>
                    <span className="badge danger">
                      <Icon name="alert" /> {d.late_days} d late
                    </span>
                  </div>
                  <div className="small muted">
                    Due {fmtDate(d.due_date)}, projected {fmtDate(d.projected_date)}
                  </div>
                  <LimitingPath steps={d.limiting} />
                </div>
              </li>
            ))}
          </ul>
        </section>
        <section className="card" data-testid="run-exception-codes">
          <div className="card-header">
            <h3>Exceptions</h3>
            <span className="row" style={{ gap: 4 }}>
              {MRP_SEVERITIES.map((sev) => (
                <Link key={sev} to={mfgPaths.runExceptions(run.id, { severity: sev })}>
                  <MrpSeverityBadge severity={sev} label={`${s.exceptions.by_severity[sev] ?? 0}`} />
                </Link>
              ))}
            </span>
          </div>
          {s.exceptions_truncated ? <div className="card-body small muted">Only the most important exceptions were kept; the counts are complete.</div> : null}
          <ul className="mfg-plain-list">
            {codes.map(([code, n]) => (
              <li key={code} className="issue">
                <MrpSeverityBadge severity={severityOfCode(code)} />
                <Link to={mfgPaths.runExceptions(run.id, { code })} className="grow" data-testid="run-exception-code" data-code={code}>
                  {exceptionLabel(code)}
                </Link>
                <span className="mfg-num">{n.toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <p className="faint small" style={{ margin: 0 }}>
        {s.iterations === 2 ? `Alternate parts used in ${s.alternates_used} places (second pass). ` : ""}
        Computed in {((run.duration_ms ?? 0) / 1000).toFixed(1)} s.
      </p>
    </div>
  );
}
