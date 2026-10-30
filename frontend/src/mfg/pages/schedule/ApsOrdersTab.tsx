/** Orders and demand of a schedule run (M3 12, 8, #191-192): dates, lateness and the "why late" chain. */
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listApsDemand, listApsOrders } from "../../api/clientM3";
import type { LateChainStep, OrderRef, OrderResultRow } from "../../api/typesM3";
import { MfgError } from "../../components/Feedback";
import { fmtNum } from "../../lib/formatM2";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced, useLoad } from "../../lib/useMfg";
import { useApsRun } from "./ApsRunShell";

const KIND_LABEL: Record<string, string> = {
  material: "material",
  capacity: "capacity",
  calendar: "no shift",
  lead_time: "processing time",
  frozen: "frozen",
  locked: "locked",
  crew: "operators",
  tool: "tooling",
  predecessor: "previous step",
  setup: "changeover",
  as_of: "plan start",
};

/** Link of a work order / planned order reference. */
export function orderLink(o: OrderRef, runId?: string): string {
  return o.type === "wo" ? mfgPaths.workOrder(o.id) : runId ? mfgPaths.apsGantt(runId, { view: "order", order: o.id }) : mfgPaths.mrp();
}

/** "Why late": the server text plus one chip per binding step (material, capacity, calendar, ...). */
export function LateChain({ text, steps }: { text?: string; steps?: LateChainStep[] }) {
  if (!text && !steps?.length) return null;
  return (
    <div className="col" style={{ gap: 2 }} data-testid="late-chain">
      {text ? <span className="small">{text}</span> : null}
      {steps?.length ? (
        <div className="mfg-chip-row">
          {steps.map((s, i) => (
            <span key={i} className={`mfg-step-chip${i === steps.length - 1 ? " mfg-step-last" : ""}`} data-kind={s.kind}>
              <span className="faint">{KIND_LABEL[s.kind] ?? s.kind}:</span>
              <span>{s.text}</span>
              {s.refs.map((r) => (r.link ? <Link key={`${r.type}${r.id}`} to={r.link}>{r.label}</Link> : null))}
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
              <th>Rank</th>
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
              <tr key={o.order.id} data-testid="aps-order-row" data-number={o.order.number} data-late-minutes={o.late_minutes}>
                <td>
                  <Link to={orderLink(o.order, run.id)} className="mono">
                    {o.order.number}
                  </Link>{" "}
                  <Link to={mfgPaths.apsGantt(run.id, { view: "order", order: o.order.id })} className="small" title="Show in the Gantt" aria-label={`Show ${o.order.number} in the Gantt`}>
                    <Icon name="calendar" size={12} />
                  </Link>
                  {o.unscheduled_ops ? <div className="faint small">{o.unscheduled_ops} operations not scheduled</div> : null}
                </td>
                <td className="mono">{o.part_number}</td>
                <td className="right">{fmtNum(o.qty)}</td>
                <td className="small">{o.rank_label || `P${o.priority}`}</td>
                <td className="small">{clock.dateTime(o.due)}</td>
                <td className="small">
                  {clock.dateTime(o.start)} – {clock.dateTime(o.end)}
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
                  {o.demand_refs.map((d) => (
                    <span key={d.demand_line_id}>
                      {d.order_id ? <Link to={mfgPaths.demandOrder(d.order_id, d.demand_line_id)}>{`${d.order_number}/${d.line_no}`}</Link> : `${d.order_number}/${d.line_no}`}{" "}
                    </span>
                  ))}
                </td>
              </tr>,
              o.late_text || o.late_chain.length ? (
                <tr key={`${o.order.id}-c`} className="mfg-schedule-row">
                  <td colSpan={8}>
                    <LateChain text={o.late_text} steps={o.late_chain} />
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
  const c = d.data?.counts;
  return (
    <div className="col gap-lg">
      <div className="row wrap">
        <label className="checkbox">
          <input type="checkbox" checked={lateOnly} onChange={(e) => setLateOnly(e.target.checked)} /> Only late
        </label>
        {c ? (
          <span className="small muted">
            {c.on_time} on time · {c.late} late{c.unscheduled ? ` · ${c.unscheduled} not scheduled` : ""}
          </span>
        ) : null}
      </div>
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
              <th>Orders</th>
            </tr>
          </thead>
          <tbody>
            {(d.data?.items ?? []).length === 0 ? (
              <tr>
                <td colSpan={7} className="muted">
                  {d.loading ? "Loading…" : "No open demand lines."}
                </td>
              </tr>
            ) : null}
            {(d.data?.items ?? []).map((x) => [
              <tr key={x.demand_line_id} data-testid="aps-demand-row" data-late-minutes={x.late_minutes} data-line={`${x.order_number}/${x.line_no}`}>
                <td>
                  <Link to={mfgPaths.demandOrder(x.order_id, x.demand_line_id)} className="mono">
                    {x.order_number}/{x.line_no}
                  </Link>
                  {x.program ? <span className="faint small"> · {x.program}</span> : null}
                  <div className="faint small">P{x.priority}</div>
                </td>
                <td className="mono">{x.part_number}</td>
                <td className="right">{fmtNum(x.qty)}</td>
                <td className="small">{clock.dateTime(x.due)}</td>
                <td className="small">{x.scheduled_end ? clock.dateTime(x.scheduled_end) : <span className="faint">not scheduled</span>}</td>
                <td>
                  {!x.scheduled_end ? (
                    <span className="badge warn">
                      <Icon name="help" /> Not scheduled{x.late_minutes ? `, ≥ ${fmtDuration(x.late_minutes)} late` : ""}
                    </span>
                  ) : x.late_minutes > 0 ? (
                    <span className="badge danger">
                      <Icon name="alert" /> {fmtDuration(x.late_minutes)} late
                    </span>
                  ) : (
                    <span className="badge ok">
                      <Icon name="check" /> On time
                    </span>
                  )}
                </td>
                <td className="small">
                  {x.orders.map((o) => (
                    <Link key={o.id} to={orderLink(o, run.id)} className="mono" style={{ marginRight: 6 }}>
                      {o.number}
                    </Link>
                  ))}
                </td>
              </tr>,
              x.late_text ? (
                <tr key={`${x.demand_line_id}-c`} className="mfg-schedule-row">
                  <td colSpan={7} className="small">
                    {x.late_text}
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
