/**
 * Per-line operation time preview (M 11.2): qty -> `GET /routings/{id}/time-preview`; shows the API numbers
 * as returned (rounded to 6 decimals only), eligible lines marked with icon + text.
 */
import { Fragment, useState } from "react";
import { Icon } from "../../components/Icon";
import { getTimePreview } from "../api/client";
import { fmtHours, fmtMinutes, fmtPct } from "../lib/format";
import { useDebounced, useLoad } from "../lib/useMfg";
import { MfgError } from "./Feedback";

export function OperationTimePreview({ routingId, version }: { routingId: string; version: number }) {
  const [qty, setQty] = useState("100");
  const dq = useDebounced(qty, 300);
  const n = Number(dq);
  const valid = dq.trim() !== "" && Number.isFinite(n) && n > 0;
  const tp = useLoad((signal) => (valid ? getTimePreview(routingId, n, signal) : null), [routingId, dq, version]);
  const d = tp.data;
  return (
    <section className="card" aria-labelledby="tp-title" data-testid="time-preview">
      <div className="card-header">
        <h3 id="tp-title">Time per lot</h3>
        <div className="row">
          <label htmlFor="tp-qty" className="small muted">
            Lot size
          </label>
          <input id="tp-qty" className="input sm" type="number" min={0} step="any" style={{ width: 100 }} value={qty} onChange={(e) => setQty(e.target.value)} data-testid="time-preview-qty" aria-invalid={!valid} />
          {d ? <span className="small muted">{d.uom}</span> : null}
          {tp.loading ? <span className="spinner" aria-hidden /> : null}
        </div>
      </div>
      <div className="card-body col">
        <p className="muted small" style={{ margin: 0 }}>
          Based on the saved routing. Setup + run time on each line of the stage (run time is divided by the line's speed); waiting and moving are shown separately.
        </p>
        <MfgError error={tp.error} onRetry={tp.reload} />
        {d ? (
          <>
            <div className="kpis" data-testid="time-preview-total" data-fastest={d.totals.fastest_minutes} data-slowest={d.totals.slowest_minutes}>
              <div className="card kpi">
                <div className="kpi-label">Fastest lines</div>
                <div className="kpi-value" data-testid="time-preview-fastest">{fmtMinutes(d.totals.fastest_minutes)} min</div>
                <div className="kpi-sub">{fmtHours(d.totals.fastest_minutes)}</div>
              </div>
              <div className="card kpi">
                <div className="kpi-label">Slowest lines</div>
                <div className="kpi-value" data-testid="time-preview-slowest">{fmtMinutes(d.totals.slowest_minutes)} min</div>
                <div className="kpi-sub">{fmtHours(d.totals.slowest_minutes)}</div>
              </div>
              <div className="card kpi">
                <div className="kpi-label">Waiting and moving</div>
                <div className="kpi-value" data-testid="time-preview-passive">{fmtMinutes(d.totals.passive_minutes)} min</div>
              </div>
              <div className="card kpi">
                <div className="kpi-label">Good output</div>
                <div className="kpi-value" data-testid="time-preview-yield">{fmtPct(d.totals.cumulative_yield)}</div>
                <div className="kpi-sub">overall yield</div>
              </div>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Op.</th>
                    <th>Name / line</th>
                    <th className="num">In → out</th>
                    <th className="num">Loads</th>
                    <th className="num">Setup</th>
                    <th className="num">Run</th>
                    <th className="num">Total (min)</th>
                    <th>Line can make it</th>
                  </tr>
                </thead>
                <tbody>
                  {d.operations.map((op) => (
                    <Fragment key={op.seq}>
                      <tr className="mfg-tp-op" data-testid="time-preview-op" data-seq={op.seq}>
                        <td className="mono">{op.seq}</td>
                        <td>
                          <strong>{op.name}</strong> <span className="muted small">{op.group.code}</span>
                        </td>
                        <td className="num">
                          {fmtMinutes(op.input_qty)} → {fmtMinutes(op.output_qty)}
                        </td>
                        <td className="num">{fmtMinutes(op.loads)}</td>
                        <td colSpan={3} className="small muted">
                          {op.queue_minutes || op.move_minutes || op.wait_minutes
                            ? `wait ${fmtMinutes(op.queue_minutes)} · move ${fmtMinutes(op.move_minutes)} · after ${fmtMinutes(op.wait_minutes)} min`
                            : ""}
                        </td>
                        <td className="small">{op.labor === "unattended" ? "Unattended" : ""}</td>
                      </tr>
                      {op.lines.map((l) => (
                        <tr key={l.line_id} data-testid="time-preview-line" data-line={l.code} className={l.eligible ? undefined : "mfg-inactive"}>
                          <td />
                          <td style={{ paddingLeft: 24 }}>
                            {l.code} <span className="faint small">speed {fmtMinutes(l.speed_factor)}</span>
                          </td>
                          <td />
                          <td />
                          <td className="num">{fmtMinutes(l.setup_minutes)}</td>
                          <td className="num">{fmtMinutes(l.run_minutes)}</td>
                          <td className="num" data-value={l.total_minutes}>
                            {fmtMinutes(l.total_minutes)}
                          </td>
                          <td className="small">
                            {l.eligible ? (
                              <span className="mfg-yes">
                                <Icon name="check" size={12} /> Yes
                              </span>
                            ) : (
                              <span className="muted">
                                <Icon name="ban" size={12} /> No{l.reason ? `: ${l.reason}` : ""}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                      {op.lines.length === 0 ? (
                        <tr>
                          <td />
                          <td colSpan={7} className="small muted">
                            <Icon name="alert" size={12} /> This stage has no lines yet.
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}
