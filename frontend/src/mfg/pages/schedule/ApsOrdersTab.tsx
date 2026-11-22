/** Orders and demand of a schedule run (M3 12, 8, #191-192): dates, lateness and the "why late" chain. */
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listApsDemand, listApsOrders } from "../../api/clientM3";
import type { LateChainStep, OrderRef, OrderResultRow } from "../../api/typesM3";
import { MfgError } from "../../components/Feedback";
import { DataTable, ShowMore } from "../../components/DataTable";
import { fmtNum } from "../../lib/formatM2";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced, useLoad } from "../../lib/useMfg";
import { useApsRun } from "./ApsRunShell";
import { plural, t } from "../../../lib/i18n";
import { FilterBar } from "../../../components/FilterBar";

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
      <FilterBar search={{ id: "ao-q", value: q, onChange: setQ, placeholder: "Order or part number" }} pageKey="ApsOrdersTab">
        <div className="field">
          <label htmlFor="ao-type">{t("mfg.apsOrdersTab.label.orders")}</label>
          <select id="ao-type" className="select" value={type} onChange={(e) => setSearchParam(setParams, "type", e.target.value)}>
            <option value="">Work orders and planned orders</option>
            <option value="wo">Work orders</option>
            <option value="planned">MRP planned orders</option>
          </select>
        </div>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={lateOnly} onChange={(e) => setSearchParam(setParams, "late", e.target.checked ? "1" : "")} data-testid="aps-orders-late" /> Only late
        </label>
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      <DataTable
        rows={data.rows}
        columns={[
          {
            key: "order",
            header: "Order",
            width: "minmax(170px, 1.2fr)",
            wrap: true,
            exportValue: (o) => o.order.number,
            render: (o) => (
              <span>
                <Link to={orderLink(o.order, run.id)} className="mono">
                  {o.order.number}
                </Link>{" "}
                <Link to={mfgPaths.apsGantt(run.id, { view: "order", order: o.order.id })} className="small" title="Show in the Gantt" aria-label={`Show ${o.order.number} in the Gantt`}>
                  <Icon name="calendar" size={12} />
                </Link>
                {o.unscheduled_ops ? <span className="vt-sub">{plural(o.unscheduled_ops, "operation")} not scheduled</span> : null}
              </span>
            ),
          },
          { key: "item", header: "Item", width: "minmax(130px, 1fr)", sortValue: (o) => o.part_number, render: (o) => <span className="mono">{o.part_number}</span> },
          { key: "qty", header: "Qty", width: "80px", align: "right", sortValue: (o) => o.qty, render: (o) => fmtNum(o.qty) },
          { key: "rank", header: "Rank", width: "90px", sortValue: (o) => o.priority, render: (o) => o.rank_label || `P${o.priority}` },
          { key: "due", header: "Due", width: "140px", sortValue: (o) => o.due, render: (o) => clock.dateTime(o.due) },
          { key: "span", header: "Start / end", width: "minmax(220px, 1.4fr)", sortValue: (o) => o.start, render: (o) => `${clock.dateTime(o.start)} – ${clock.dateTime(o.end)}` },
          {
            key: "late",
            header: "Late",
            width: "110px",
            sortValue: (o) => o.late_minutes,
            exportValue: (o) => o.late_minutes,
            render: (o) =>
              o.late_minutes > 0 ? (
                <span className="badge danger">
                  <Icon name="alert" /> {fmtDuration(o.late_minutes)}
                </span>
              ) : (
                <span className="badge ok">
                  <Icon name="check" /> {t("mfg.apsOrdersTab.btn.onTime")}
                </span>
              ),
          },
          {
            key: "demand",
            header: "For demand",
            width: "minmax(130px, 1fr)",
            wrap: true,
            exportValue: (o) => o.demand_refs.map((d) => `${d.order_number}/${d.line_no}`).join(" "),
            render: (o) => (
              <span>
                {o.demand_refs.map((d) => (
                  <span key={d.demand_line_id}>
                    {d.order_id ? <Link to={mfgPaths.demandOrder(d.order_id, d.demand_line_id)}>{`${d.order_number}/${d.line_no}`}</Link> : `${d.order_number}/${d.line_no}`}{" "}
                  </span>
                ))}
              </span>
            ),
          },
        ]}
        rowKey={(o) => o.order.id}
        label="Orders in this schedule"
        testId="aps-orders"
        totalCount={data.total}
        loading={data.loading}
        exportName={`schedule-${run.run_no}-orders`}
        rowExtras={(o) => ({ testId: "aps-order-row", data: { number: o.order.number, "late-minutes": o.late_minutes } })}
        rowDetail={(o) => (o.late_text || o.late_chain.length ? <LateChain text={o.late_text} steps={o.late_chain} /> : null)}
        empty={lateOnly || type || dq ? "No orders match these filters." : "No orders in this schedule."}
        footer={<ShowMore shown={data.rows.length} total={data.total} noun="orders" loading={data.loading} onMore={data.onEndReached} />}
        card={{ title: "order", status: "late", fields: ["item", "qty", "due"] }}
      />
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
      <FilterBar
        end={
          c ? (
            <span className="small muted">
              {c.on_time} on time · {c.late} late{c.unscheduled ? ` · ${c.unscheduled} not scheduled` : ""}
            </span>
          ) : undefined
        }
      >
        <label className="checkbox">
          <input type="checkbox" checked={lateOnly} onChange={(e) => setLateOnly(e.target.checked)} /> Only late
        </label>
      </FilterBar>
      <MfgError error={d.error} onRetry={d.reload} />
      <DataTable
        rows={d.data?.items ?? []}
        columns={[
          {
            key: "line",
            header: "Demand line",
            width: "minmax(170px, 1.2fr)",
            sortValue: (x) => `${x.order_number}/${String(x.line_no).padStart(4, "0")}`,
            exportValue: (x) => `${x.order_number}/${x.line_no}`,
            render: (x) => (
              <span className="mfg-ellipsis">
                <Link to={mfgPaths.demandOrder(x.order_id, x.demand_line_id)} className="mono">
                  {x.order_number}/{x.line_no}
                </Link>
                {x.program ? <span className="faint small"> · {x.program}</span> : null}
                <span className="faint small"> · P{x.priority}</span>
              </span>
            ),
          },
          { key: "item", header: "Item", width: "minmax(130px, 1fr)", sortValue: (x) => x.part_number, render: (x) => <span className="mono">{x.part_number}</span> },
          { key: "qty", header: "Qty", width: "80px", align: "right", sortValue: (x) => x.qty, render: (x) => fmtNum(x.qty) },
          { key: "due", header: "Due", width: "140px", sortValue: (x) => x.due, render: (x) => clock.dateTime(x.due) },
          { key: "end", header: "Scheduled completion", width: "170px", sortValue: (x) => x.scheduled_end, render: (x) => (x.scheduled_end ? clock.dateTime(x.scheduled_end) : <span className="faint">not scheduled</span>) },
          {
            key: "status",
            header: "Status",
            width: "minmax(150px, 1fr)",
            sortValue: (x) => (x.scheduled_end ? x.late_minutes : Number.MAX_SAFE_INTEGER),
            exportValue: (x) => (!x.scheduled_end ? "Not scheduled" : x.late_minutes > 0 ? `${x.late_minutes} min late` : "On time"),
            render: (x) =>
              !x.scheduled_end ? (
                <span className="badge warn">
                  <Icon name="help" /> Not scheduled{x.late_minutes ? `, ≥ ${fmtDuration(x.late_minutes)} late` : ""}
                </span>
              ) : x.late_minutes > 0 ? (
                <span className="badge danger">
                  <Icon name="alert" /> {fmtDuration(x.late_minutes)} late
                </span>
              ) : (
                <span className="badge ok">
                  <Icon name="check" /> {t("mfg.apsOrdersTab.btn.onTime2")}
                </span>
              ),
          },
          {
            key: "orders",
            header: "Orders",
            width: "minmax(130px, 1fr)",
            wrap: true,
            exportValue: (x) => x.orders.map((o) => o.number).join(" "),
            render: (x) => (
              <span>
                {x.orders.map((o) => (
                  <Link key={o.id} to={orderLink(o, run.id)} className="mono" style={{ marginRight: 6 }}>
                    {o.number}
                  </Link>
                ))}
              </span>
            ),
          },
        ]}
        rowKey={(x) => x.demand_line_id}
        label="Demand lines in this schedule"
        testId="aps-demand"
        loading={d.loading && !d.data}
        exportName={`schedule-${run.run_no}-demand`}
        rowExtras={(x) => ({ testId: "aps-demand-row", data: { "late-minutes": x.late_minutes, line: `${x.order_number}/${x.line_no}` } })}
        rowDetail={(x) => (x.late_text ? x.late_text : null)}
        empty={lateOnly ? "No late demand lines." : "No open demand lines."}
        card={{ title: "line", status: "status", fields: ["item", "qty", "due"] }}
      />
    </div>
  );
}
