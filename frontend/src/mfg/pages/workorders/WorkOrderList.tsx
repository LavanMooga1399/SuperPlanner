/** `/mfg/work-orders` (M2 14.2, #134): work orders by start date, status filter, link to the kitting check. */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listWorkOrders } from "../../api/clientM2";
import type { WoSort, WorkOrderSummary } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { ImportShortcut } from "../../components/ImportShortcut";
import { PermissionGate } from "../../components/PermissionGate";
import { SourceBadge, WoStatusChip } from "../../components/StatusM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { fmtNum, serialText } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced } from "../../lib/useMfg";

const STATUS_SETS: Record<string, string | undefined> = {
  active: "planned,released,in_progress",
  planned: "planned",
  released: "released,in_progress",
  done: "completed,closed",
  cancelled: "cancelled",
  all: undefined,
};

export function WorkOrderList() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const st = params.get("status") ?? "active";
  const sort = (params.get("sort") ?? "start_date") as WoSort;
  const source = params.get("source") ?? "";
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = usePaged<WorkOrderSummary>(
    (offset, limit, signal) => listWorkOrders({ q: dq || undefined, status: STATUS_SETS[st], sort, source: (source || undefined) as WorkOrderSummary["source"] | undefined, limit, offset }, signal),
    [dq, st, sort, source],
  );

  const columns: Column<WorkOrderSummary>[] = useMemo(
    () => [
      {
        key: "no",
        header: "Work order",
        width: "130px",
        render: (w) => (
          <Link to={mfgPaths.workOrder(w.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {w.number}
          </Link>
        ),
      },
      { key: "st", header: "Status", width: "150px", render: (w) => <WoStatusChip status={w.status} /> },
      { key: "pn", header: "Item", width: "minmax(150px, 1.2fr)", render: (w) => <span className="mono mfg-ellipsis">{w.item.part_number}</span> },
      { key: "desc", header: "Description", width: "minmax(140px, 1.3fr)", render: (w) => <span className="mfg-ellipsis">{w.item.description}</span> },
      { key: "qty", header: "Qty", width: "70px", align: "right", render: (w) => fmtNum(w.qty) },
      { key: "done", header: "Done", width: "70px", align: "right", render: (w) => fmtNum(w.qty_completed) },
      { key: "start", header: "Start", width: "104px", render: (w) => fmtDate(w.start_date) },
      { key: "due", header: "Due", width: "104px", render: (w) => fmtDate(w.due_date) },
      { key: "prio", header: "Prio.", width: "56px", align: "right", render: (w) => `P${w.priority}` },
      { key: "ser", header: "Units", width: "90px", render: (w) => serialText(w.serial_from, w.serial_to) },
      { key: "dl", header: "For demand", width: "120px", render: (w) => (w.demand_line ? <span className="mono small">{w.demand_line.order_number}/{w.demand_line.line_no}</span> : "") },
      { key: "src", header: "Source", width: "96px", render: (w) => <SourceBadge source={w.source} runNo={w.source_run_no} /> },
    ],
    [],
  );

  return (
    <div className="col gap-lg">
      <div className="page-header mfg-header">
        <div>
          <h1>Work orders</h1>
          <p>What the plant makes: quantities, dates and frozen component lists, with reservations and kitting.</p>
        </div>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <Link className="btn" to={mfgPaths.kitting()} data-testid="wo-kitting-check">
            <Icon name="check" /> Kitting check
          </Link>
          <ImportShortcut what="work orders" />
          <PermissionGate perm="wo_edit">
            <Link className="btn primary" to={mfgPaths.workOrderNew()} data-testid="wo-new">
              <Icon name="plus" /> New work order
            </Link>
          </PermissionGate>
        </div>
      </div>
      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 220px" }}>
          <label htmlFor="wo-q">Search</label>
          <input id="wo-q" className="input" type="search" placeholder="Number or part number" value={q} onChange={(e) => setQ(e.target.value)} data-testid="wo-search" />
        </div>
        <div className="field">
          <label htmlFor="wo-status">Status</label>
          <select id="wo-status" className="select" value={st} onChange={(e) => set("status", e.target.value === "active" ? "" : e.target.value)} data-testid="wo-status">
            <option value="active">Not finished</option>
            <option value="planned">Planned (firm)</option>
            <option value="released">Released / in progress</option>
            <option value="done">Completed / closed</option>
            <option value="cancelled">Cancelled</option>
            <option value="all">All</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="wo-src">Source</label>
          <select id="wo-src" className="select" value={source} onChange={(e) => set("source", e.target.value)}>
            <option value="">Any</option>
            <option value="manual">Entered by hand</option>
            <option value="mrp">From MRP</option>
            <option value="import">Imported</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="wo-sort">Sort by</label>
          <select id="wo-sort" className="select" value={sort} onChange={(e) => set("sort", e.target.value === "start_date" ? "" : e.target.value)}>
            <option value="start_date">Start date</option>
            <option value="due_date">Due date</option>
            <option value="priority">Priority</option>
            <option value="number">Number</option>
          </select>
        </div>
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(w) => w.id}
        label="Work orders"
        testId="wo-table"
        totalCount={data.total}
        rowExtras={(w) => ({ testId: "wo-row", data: { number: w.number, status: w.status } })}
        onRowClick={(w) => navigate(mfgPaths.workOrder(w.id))}
        onActivate={(w) => navigate(mfgPaths.workOrder(w.id))}
        onEndReached={data.onEndReached}
        empty={data.loading ? "Loading…" : "No work orders match these filters. Firm planned orders from an MRP run, or create one."}
        footer={<span className="muted small">Showing {data.rows.length.toLocaleString()} of {data.total.toLocaleString()} work orders</span>}
      />
    </div>
  );
}
