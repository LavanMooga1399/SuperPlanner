/**
 * `/mfg/shortages` (M2 14.2, #163): one page for the daily stand-up: late demand (latest live run), short parts,
 * overdue deliveries (live) and work-order component shortages (live kitting).
 */
import { useState } from "react";
import { Link } from "react-router";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { getShortages } from "../api/clientM2";
import { MfgError, Spinner } from "../components/Feedback";
import { OverdueBadge } from "../components/StatusM2";
import { fmtDate } from "../lib/format";
import { fmtNum } from "../lib/formatM2";
import { mfgPaths } from "../lib/paths";
import { useLoad } from "../lib/useMfg";
import { LimitingPath } from "./mrp/DemandProjectionTab";
import { ItemsShortTable } from "./workorders/KittingCheckPage";

export function ShortagesPage() {
  const [horizon, setHorizon] = useState(30);
  const d = useLoad((signal) => getShortages(horizon, signal), [horizon]);
  const s = d.data;
  const stale = s?.run && (typeof s.run.stale === "boolean" ? s.run.stale : s.run.stale.is_stale);
  return (
    <div className="col gap-lg" data-testid="shortages-page">
      <div className="page-header mfg-header">
        <div>
          <h1>Shortages</h1>
          <p>What will be late, which parts are missing, which deliveries are overdue and which work orders cannot be kitted.</p>
        </div>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div className="field">
            <label htmlFor="sh-h">Work orders starting within</label>
            <select id="sh-h" className="select" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
              {[7, 14, 30, 60, 90].map((n) => (
                <option key={n} value={n}>
                  {n} days
                </option>
              ))}
            </select>
          </div>
          <button type="button" className="btn" onClick={d.reload} disabled={d.loading}>
            {d.loading ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />} Refresh
          </button>
        </div>
      </div>
      <MfgError error={d.error} onRetry={d.reload} />
      {d.loading && !s ? <Spinner /> : null}
      {s ? (
        <>
          {s.run ? (
            <p className="small muted" style={{ margin: 0 }}>
              Late demand and short parts from <Link to={mfgPaths.run(s.run.id)}>MRP run #{s.run.run_no}</Link> (as of {fmtDate(s.run.as_of)})
              {stale ? (
                <span className="badge warn" style={{ marginLeft: 6 }}>
                  <Icon name="clock" /> data changed since
                </span>
              ) : null}
              ; deliveries and work orders are live.
            </p>
          ) : (
            <Banner tone="info" title="No MRP run yet">
              Late demand and short parts appear after the first <Link to={mfgPaths.mrp()}>MRP run</Link>. Deliveries and work orders below are live.
            </Banner>
          )}
          <div className="kpis">
            {(
              [
                ["late_demand", "Late demand lines", "demand"],
                ["short_items", "Parts short", "items"],
                ["overdue_schedules", "Overdue deliveries", "supply"],
                ["wo_short", "Parts missing for work orders", "wo"],
              ] as const
            ).map(([k, label, panel]) => (
              <a key={k} href={`#panel-${panel}`} className="card kpi mfg-kpi" data-testid={`shortage-count-${panel}`}>
                <div className="kpi-label">{label}</div>
                <div className="kpi-value" style={s.counts[k] ? { color: "var(--danger)" } : undefined}>
                  {s.counts[k].toLocaleString()}
                </div>
              </a>
            ))}
          </div>
          <section className="card" id="panel-demand" data-testid="shortage-panel-demand">
            <div className="card-header">
              <h3>Late demand</h3>
              {s.run ? (
                <Link to={mfgPaths.runDemand(s.run.id)} className="small">
                  All demand
                </Link>
              ) : null}
            </div>
            <ul className="mfg-plain-list">
              {s.late_demand.length === 0 ? (
                <li className="issue muted">
                  <Icon name="check" /> Nothing late.
                </li>
              ) : null}
              {s.late_demand.map((x, i) => (
                <li key={x.demand_line_id ?? i} className="issue" data-testid="demand-line" data-late-days={x.late_days}>
                  <div className="grow col" style={{ gap: 2 }}>
                    <div className="row wrap" style={{ gap: 6 }}>
                      {x.link ? (
                        <Link to={x.link} className="mono">
                          {x.order ? `${x.order.number}/${x.line_no}` : "What-if"}
                        </Link>
                      ) : null}
                      <span>
                        {fmtNum(x.qty)} x <span className="mono">{x.item.part_number}</span>
                      </span>
                      <span className="badge danger">
                        <Icon name="alert" /> {x.late_days} d late
                      </span>
                      <span className="small muted">
                        due {fmtDate(x.due_date)}, projected {fmtDate(x.projected_date)}
                      </span>
                    </div>
                    <LimitingPath steps={x.limiting} runId={s.run?.id} />
                  </div>
                </li>
              ))}
            </ul>
          </section>
          <div className="grid-2" style={{ alignItems: "start" }}>
            <section className="card" id="panel-items" data-testid="shortage-panel-items">
              <div className="card-header">
                <h3>Short parts</h3>
                {s.run ? (
                  <Link to={`${mfgPaths.runItems(s.run.id)}?short=1`} className="small">
                    All
                  </Link>
                ) : null}
              </div>
              <div className="table-wrap" style={{ maxHeight: 420, overflow: "auto" }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Part</th>
                      <th className="right">Short</th>
                      <th>From</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.short_items.map((x) => (
                      <tr key={x.item.id} data-testid="short-item-row">
                        <td>
                          <Link to={x.link} className="mono">
                            {x.item.part_number}
                          </Link>
                          <div className="faint small mfg-ellipsis">{x.item.description}</div>
                        </td>
                        <td className="right mfg-neg">
                          {fmtNum(x.short_qty)} {x.uom}
                        </td>
                        <td>{fmtDate(x.first_short_date)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="card" id="panel-supply" data-testid="shortage-panel-supply">
              <div className="card-header">
                <h3>Overdue deliveries</h3>
                <Link to={mfgPaths.deliveryBoard({ overdue: "1" })} className="small">
                  Delivery schedule
                </Link>
              </div>
              <div className="table-wrap" style={{ maxHeight: 420, overflow: "auto" }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Delivery</th>
                      <th>Supplier</th>
                      <th className="right">Open</th>
                      <th>Overdue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.overdue_supply.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="muted">
                          None.
                        </td>
                      </tr>
                    ) : null}
                    {s.overdue_supply.map((x) => (
                      <tr key={x.schedule_id} data-testid="overdue-row">
                        <td>
                          <Link to={x.link} className="mono">
                            {x.doc.number} / {x.line_no} / {x.seq}
                          </Link>
                          <div className="faint small">{x.item.part_number}</div>
                        </td>
                        <td>{x.supplier?.code ?? ""}</td>
                        <td className="right">{fmtNum(x.open_qty)}</td>
                        <td>
                          <OverdueBadge days={x.overdue_days} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
          <div id="panel-wo">
            <ItemsShortTable rows={s.wo_shortages} testId="shortage-panel-wo" title="Parts missing for work orders" />
          </div>
        </>
      ) : null}
    </div>
  );
}
