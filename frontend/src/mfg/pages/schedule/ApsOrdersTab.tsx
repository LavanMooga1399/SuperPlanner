/** Orders and demand of a schedule run (M3 12, 8, #191-192): dates, lateness and the "why late" chain. */
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listApsDemand, listApsOrders } from "../../api/clientM3";
import type { OrderResultRow } from "../../api/typesM3";
import { MfgError } from "../../components/Feedback";
import { fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced, useLoad } from "../../lib/useMfg";
import { useApsRun } from "./ApsRunShell";

const KIND_LABEL: Record<string, string> = { material: "material", capacity: "capacity", calendar: "no shift", lead_time: "processing time", frozen: "frozen", locked: "locked" };

export function LateChain({ chain }: { chain: OrderResultRow["late_chain"] }) {
  if (!chain) return null;
  return (
    <div className="col" style={{ gap: 2 }} data-testid="late-chain">
      <span className="small">{chain.text}</span>
      {chain.steps.length ? (
        <div className="mfg-chip-row">
          {chain.steps.map((s, i) => (
            <span key={i} className={`mfg-step-chip${i === chain.steps.length - 1 ? " mfg-step-last" : ""}`} data-kind={s.kind}>
              <span className="faint">{KIND_LABEL[s.kind] ?? s.kind}:</span>
              {s.ref?.link ? <Link to={s.ref.link}>{s.label}</Link> : <span>{s.label}</span>}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ApsOrdersTab() {
  const { run } = useApsRun();
  const clock = usePlantClock();
  const [params, setParams] = useSearchParams();
  const lateOnly = params.get("late") === "1";
  const type = params.get("type") ?? "";
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim(), 250);
  const data = usePaged<OrderResultRow>(
    (offset, limit, signal) => listApsOrders(run.id, { late_only: lateOnly || undefined, order_type: type || undefined, q: dq || undefined, sort: "-late_minutes", limit, offset }, signal),
    [run.id, lateOnly, type, dq],
  );
  return (
    <div className="col gap-lg">
      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 220px" }}>
          <label htmlFor="ao-q">Search</label>
          <input id="ao-q" className="input" type="search" placeholder="Order or part number" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ao-type">Orders</label>
          <select id="ao-type" className="select" value={type} onChange={(e) => setSearchParam(setParams, "type", e.target.value)}>
            <option value="">Work orders and planned orders</option>
            <option value="wo">Work orders</option>
            <option value="planned">MRP planned orders</option>
          </select>
        </div>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={lateOnly} onChange={(e) => setSearchParam(setParams, "late", e.target.checked ? "1" : "")} data-testid="aps-orders-late" /> Only late
        </label>
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="aps-orders">
          <thead>
            <tr>
              <th>Order</th>
              <th>Item</th>
              <th className="right">Qty</th>
              <th>Prio.</th>
              <th>Due</th>
              <th>Start / end</th>
              <th>Late</th>
              <th>For demand</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="muted">
                  {data.loading ? "Loading…" : "No orders."}
                </td>
              </tr>
            ) : null}
            {data.rows.map((o) => [
              <tr key={o.order_id} data-testid="aps-order-row" data-number={o.number} data-late-minutes={o.late_minutes}>
                <td>
                  {o.link ? (
                    <Link to={o.link} className="mono">
                      {o.number}
                    </Link>
                  ) : (
                    <span className="mono">{o.number}</span>
                  )}{" "}
                  <Link to={mfgPaths.apsGantt(run.id, { view: "order", order: o.order_id })} className="small" title="Show in the Gantt">
                    <Icon name="calendar" size={12} />
                  </Link>
                </td>
                <td className="mono">{o.item.part_number}</td>
                <td className="right">{fmtNum(o.qty)}</td>
                <td>P{o.priority}</td>
                <td className="small">{clock.dateTime(o.due_at)}</td>
                <td className="small">
                  {clock.dateTime(o.start_at)} – {clock.dateTime(o.end_at)}
                </td>
                <td>
                  {o.late_minutes > 0 ? (
                    <span className="badge danger">
                      <Icon name="alert" /> {fmtDuration(o.late_minutes)}
                    </span>
                  ) : (
                    <span className="badge ok">
                      <Icon name="check" /> on time
                    </span>
                  )}
                </td>
                <td className="small">
                  {o.demand_refs.map((d) => (d.link ? <Link key={d.demand_line_id} to={d.link}>{d.label} </Link> : <span key={d.demand_line_id}>{d.label} </span>))}
                </td>
              </tr>,
              o.late_chain ? (
                <tr key={`${o.order_id}-c`} className="mfg-schedule-row">
                  <td colSpan={8}>
                    <LateChain chain={o.late_chain} />
                  </td>
                </tr>
              ) : null,
            ])}
          </tbody>
        </table>
        {data.rows.length < data.total ? (
          <div className="card-footer">
            <button type="button" className="btn sm" onClick={data.onEndReached} disabled={data.loading}>
              Show more ({data.rows.length} of {data.total})
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ApsDemandTab() {
  const { run } = useApsRun();
  const clock = usePlantClock();
  const [lateOnly, setLateOnly] = useState(false);
  const d = useLoad((signal) => listApsDemand(run.id, { late_only: lateOnly || undefined }, signal), [run.id, lateOnly]);
  return (
    <div className="col gap-lg">
      <label className="checkbox">
        <input type="checkbox" checked={lateOnly} onChange={(e) => setLateOnly(e.target.checked)} /> Only late
      </label>
      <MfgError error={d.error} onRetry={d.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="aps-demand">
          <thead>
            <tr>
              <th>Demand line</th>
              <th>Item</th>
              <th className="right">Qty</th>
              <th>Due</th>
              <th>Scheduled completion</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(d.data?.items ?? []).length === 0 ? (
              <tr>
                <td colSpan={6} className="muted">
                  {d.loading ? "Loading…" : "No open demand lines."}
                </td>
              </tr>
            ) : null}
            {(d.data?.items ?? []).map((x) => [
              <tr key={x.demand_line_id} data-testid="aps-demand-row" data-late-minutes={x.late_minutes} data-line={x.order ? `${x.order.number}/${x.line_no}` : ""}>
                <td>
                  {x.link ? (
                    <Link to={x.link} className="mono">
                      {x.order?.number}/{x.line_no}
                    </Link>
                  ) : (
                    <span className="mono">
                      {x.order?.number}/{x.line_no}
                    </span>
                  )}
                  {x.order?.program ? <span className="faint small"> · {x.order.program}</span> : null}
                </td>
                <td className="mono">{x.item.part_number}</td>
                <td className="right">{fmtNum(x.qty)}</td>
                <td>{fmtDate(x.due_date)}</td>
                <td className="small">{x.scheduled_end ? clock.dateTime(x.scheduled_end) : <span className="faint">not scheduled</span>}</td>
                <td>
                  {x.status === "late" ? (
                    <span className="badge danger">
                      <Icon name="alert" /> {fmtDuration(x.late_minutes)} late
                    </span>
                  ) : x.status === "unscheduled" ? (
                    <span className="badge warn">
                      <Icon name="help" /> Not scheduled
                    </span>
                  ) : (
                    <span className="badge ok">
                      <Icon name="check" /> On time
                    </span>
                  )}
                </td>
              </tr>,
              x.late_chain?.text ? (
                <tr key={`${x.demand_line_id}-c`} className="mfg-schedule-row">
                  <td colSpan={6} className="small">
                    {x.late_chain.text}
                  </td>
                </tr>
              ) : null,
            ])}
          </tbody>
        </table>
      </div>
    </div>
  );
}
