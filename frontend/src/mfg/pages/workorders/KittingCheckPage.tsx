/**
 * `/mfg/work-orders/kitting` (M2 14.2, 7.4 #147): simulate kitting of the work orders starting soon, in priority
 * or start-date order (each takes free stock in turn), and the plant-wide component shortage list.
 */
import { useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../../components/Icon";
import { kittingCheck } from "../../api/clientM2";
import type { ItemShort, KittingCheckRequest } from "../../api/typesM2";
import { MfgError, Spinner } from "../../components/Feedback";
import { WoStatusChip } from "../../components/StatusM2";
import { fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { useLoad } from "../../lib/useMfg";

export function KittingCheckPage() {
  const [order, setOrder] = useState<KittingCheckRequest["order"]>("priority");
  const [horizon, setHorizon] = useState("14");
  const h = Number(horizon);
  const valid = Number.isInteger(h) && h >= 0 && h <= 365;
  const res = useLoad((signal) => (valid ? kittingCheck({ wo_ids: null, order, horizon_days: h }, signal) : null), [order, h, valid]);
  const r = res.data;
  return (
    <div className="col gap-lg">
      <nav aria-label="Breadcrumb" className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.workOrders()}>Work orders</Link> <Icon name="chevron-right" size={12} /> <span>Kitting check</span>
      </nav>
      <div className="page-header mfg-header">
        <div>
          <h1>Kitting check</h1>
          <p>Which released and soon-starting work orders can be kitted from today's stock, taking stock in turn by the order you choose.</p>
        </div>
      </div>
      <div className="toolbar mfg-filters">
        <div className="field">
          <label htmlFor="kc-order">Who gets stock first</label>
          <select id="kc-order" className="select" value={order} onChange={(e) => setOrder(e.target.value as KittingCheckRequest["order"])} data-testid="kitting-order">
            <option value="priority">Highest priority first</option>
            <option value="start_date">Earliest start first</option>
          </select>
        </div>
        <div className="field" style={{ width: 160 }}>
          <label htmlFor="kc-h">Planned orders starting within (days)</label>
          <input id="kc-h" className="input" type="number" min={0} max={365} value={horizon} aria-invalid={!valid} onChange={(e) => setHorizon(e.target.value)} />
        </div>
        <button type="button" className="btn" style={{ alignSelf: "flex-end" }} onClick={res.reload} disabled={res.loading}>
          {res.loading ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />} Check again
        </button>
      </div>
      <MfgError error={res.error} onRetry={res.reload} />
      {res.loading && !r ? <Spinner label="Checking kits…" /> : null}
      {r ? (
        <div className="grid-2" style={{ alignItems: "start" }}>
          <section className="card" data-testid="kitting-check-rows">
            <div className="card-header">
              <h3>Work orders ({r.rows.length})</h3>
              <span className="muted small">{r.rows.filter((x) => x.kit_complete).length} complete</span>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Work order</th>
                    <th>Start</th>
                    <th>Prio.</th>
                    <th>Kit</th>
                    <th>Missing</th>
                  </tr>
                </thead>
                <tbody>
                  {r.rows.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="muted">
                        No work orders in range.
                      </td>
                    </tr>
                  ) : null}
                  {r.rows.map((x) => (
                    <tr key={x.wo.id} data-testid="kitting-row" data-shortage={x.short_components} data-wo={x.wo.number}>
                      <td>
                        <Link to={mfgPaths.workOrder(x.wo.id)} className="mono">
                          {x.wo.number}
                        </Link>{" "}
                        {x.wo.item ? <span className="muted small">{x.wo.item.part_number}</span> : null}
                        <div>
                          <WoStatusChip status={x.status} />
                        </div>
                      </td>
                      <td>{fmtDate(x.start_date)}</td>
                      <td>P{x.priority}</td>
                      <td>
                        {x.kit_complete ? (
                          <span className="badge ok">
                            <Icon name="check" /> Complete
                          </span>
                        ) : (
                          <span className="badge danger">
                            <Icon name="alert" /> {x.short_components} short
                          </span>
                        )}
                      </td>
                      <td className="small">
                        {x.shortages.slice(0, 3).map((s) => (
                          <div key={s.item.id}>
                            <span className="mono">{s.item.part_number}</span> −{fmtNum(s.shortage)}
                          </div>
                        ))}
                        {x.shortages.length > 3 ? <div className="faint">+{x.shortages.length - 3} more</div> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <ItemsShortTable rows={r.items_short} />
        </div>
      ) : null}
    </div>
  );
}

export function ItemsShortTable({ rows, testId = "kitting-items-short", title = "Component shortage list" }: { rows: ItemShort[]; testId?: string; title?: string }) {
  return (
    <section className="card" data-testid={testId}>
      <div className="card-header">
        <h3>
          {title} ({rows.length})
        </h3>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Part</th>
              <th className="right">Missing</th>
              <th className="right">WOs</th>
              <th>First needed</th>
              <th>Next supply</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  <Icon name="check" size={12} /> Nothing missing.
                </td>
              </tr>
            ) : null}
            {rows.map((s) => (
              <tr key={s.item.id} data-testid="item-short-row" data-item={s.item.part_number}>
                <td>
                  <Link to={mfgPaths.itemStock(s.item.id)} className="mono">
                    {s.item.part_number}
                  </Link>
                  <div className="faint small mfg-ellipsis">{s.item.description}</div>
                </td>
                <td className="right mfg-neg">
                  {fmtNum(s.total_shortage)} {s.item.uom}
                </td>
                <td className="right">{s.wo_count}</td>
                <td>{fmtDate(s.first_start_date)}</td>
                <td className="small">
                  {s.next_supply ? (
                    <Link to={s.next_supply.link}>
                      {fmtNum(s.next_supply.qty)} on {fmtDate(s.next_supply.date)} ({s.next_supply.label})
                    </Link>
                  ) : (
                    <span className="badge danger">
                      <Icon name="x" /> No open supply
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
