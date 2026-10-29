/** `/mfg/demand` (M2 14.2, #126): demand orders with open quantity, next due date and late lines (latest run). */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listDemandOrders } from "../../api/clientM2";
import { DEMAND_TYPES, type DemandOrderSummary, type DemandStatus, type DemandType } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { ImportShortcut } from "../../components/ImportShortcut";
import { PermissionGate } from "../../components/PermissionGate";
import { DemandStatusChip } from "../../components/StatusM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { DEMAND_TYPE_LABEL, fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced } from "../../lib/useMfg";

export function DemandList() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [program, setProgram] = useState(params.get("program") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const dProgram = useDebounced(program.trim(), 250);
  const status = (params.get("status") ?? "") as DemandStatus | "";
  const type = (params.get("type") ?? "") as DemandType | "";
  const lateOnly = params.get("late") === "1";
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => set("program", dProgram), [dProgram]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = usePaged<DemandOrderSummary>(
    (offset, limit, signal) =>
      listDemandOrders({ q: dq || undefined, status: status || undefined, demand_type: type || undefined, program: dProgram || undefined, late_only: lateOnly || undefined, limit, offset }, signal),
    [dq, status, type, dProgram, lateOnly],
  );

  const columns: Column<DemandOrderSummary>[] = useMemo(
    () => [
      {
        key: "no",
        header: "Order",
        width: "130px",
        render: (o) => (
          <Link to={mfgPaths.demandOrder(o.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {o.number}
          </Link>
        ),
      },
      { key: "st", header: "Status", width: "170px", render: (o) => <DemandStatusChip status={o.status} /> },
      { key: "type", header: "Type", width: "140px", render: (o) => DEMAND_TYPE_LABEL[o.demand_type] ?? o.demand_type },
      { key: "cust", header: "Customer", width: "minmax(150px, 1.4fr)", render: (o) => <span className="mfg-ellipsis">{o.customer}</span> },
      { key: "prog", header: "Programme", width: "110px", render: (o) => <span className="mono">{o.program ?? ""}</span> },
      { key: "prio", header: "Priority", width: "70px", align: "right", render: (o) => `P${o.priority}` },
      { key: "lines", header: "Lines", width: "60px", align: "right", render: (o) => o.line_count },
      { key: "open", header: "Open qty", width: "84px", align: "right", render: (o) => fmtNum(o.open_qty) },
      { key: "due", header: "Next due", width: "106px", render: (o) => fmtDate(o.next_due) },
      {
        key: "late",
        header: "Late lines",
        width: "100px",
        render: (o) =>
          o.late_lines > 0 ? (
            <span className="badge danger">
              <Icon name="alert" /> {o.late_lines} late
            </span>
          ) : o.status === "open" ? (
            <span className="faint">
              <Icon name="check" size={12} /> none
            </span>
          ) : null,
      },
    ],
    [],
  );

  return (
    <div className="col gap-lg">
      <div className="page-header mfg-header">
        <div>
          <h1>Demand</h1>
          <p>Customer orders, spares, internal and project demand. Only open orders are planned by MRP.</p>
        </div>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <ImportShortcut what="demand" />
          <PermissionGate perm="demand_edit">
            <Link className="btn primary" to={mfgPaths.demandNew()} data-testid="demand-new">
              <Icon name="plus" /> New demand order
            </Link>
          </PermissionGate>
        </div>
      </div>
      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 220px" }}>
          <label htmlFor="dm-q">Search</label>
          <input id="dm-q" className="input" type="search" placeholder="Order number or customer" value={q} onChange={(e) => setQ(e.target.value)} data-testid="demand-search" />
        </div>
        <div className="field">
          <label htmlFor="dm-status">Status</label>
          <select id="dm-status" className="select" value={status} onChange={(e) => set("status", e.target.value)} data-testid="demand-status">
            <option value="">All</option>
            <option value="draft">Draft</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="dm-type">Type</label>
          <select id="dm-type" className="select" value={type} onChange={(e) => set("type", e.target.value)}>
            <option value="">All types</option>
            {DEMAND_TYPES.map((t) => (
              <option key={t} value={t}>
                {DEMAND_TYPE_LABEL[t]}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ width: 140 }}>
          <label htmlFor="dm-prog">Programme</label>
          <input id="dm-prog" className="input" value={program} onChange={(e) => setProgram(e.target.value)} />
        </div>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={lateOnly} onChange={(e) => set("late", e.target.checked ? "1" : "")} data-testid="demand-late-only" /> Only late (latest MRP run)
        </label>
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(o) => o.id}
        label="Demand orders"
        testId="demand-table"
        totalCount={data.total}
        rowExtras={(o) => ({ testId: "demand-order-row", data: { number: o.number, status: o.status, late: o.late_lines } })}
        onRowClick={(o) => navigate(mfgPaths.demandOrder(o.id))}
        onActivate={(o) => navigate(mfgPaths.demandOrder(o.id))}
        onEndReached={data.onEndReached}
        empty={data.loading ? "Loading…" : "No demand orders match these filters."}
        footer={<span className="muted small">Showing {data.rows.length.toLocaleString()} of {data.total.toLocaleString()} orders</span>}
      />
    </div>
  );
}
