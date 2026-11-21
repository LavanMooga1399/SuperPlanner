/** `/mfg/work-orders` (M2 14.2, #134): work orders by start date, status filter, link to the kitting check. */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { FilterBar, type FilterChip } from "../../../components/FilterBar";
import { PageHeader } from "../../../components/PageHeader";
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
        sortKey: "number",
        exportValue: (w) => w.number,
        render: (w) => (
          <Link to={mfgPaths.workOrder(w.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {w.number}
          </Link>
        ),
      },
      { key: "st", header: "Status", width: "150px", render: (w) => <WoStatusChip status={w.status} /> },
      { key: "pn", header: "Item", width: "minmax(150px, 1.2fr)", render: (w) => <span className="mono mfg-ellipsis">{w.item.part_number}</span> },
      { key: "desc", header: "Description", width: "minmax(140px, 1.3fr)", render: (w) => <span className="mfg-ellipsis">{w.item.description}</span> },
      { key: "qty", header: "Qty", width: "80px", align: "right", render: (w) => fmtNum(w.qty) },
      { key: "done", header: "Done", width: "80px", align: "right", render: (w) => fmtNum(w.qty_completed) },
      { key: "start", header: "Start", width: "104px", sortKey: "start_date", render: (w) => fmtDate(w.start_date) },
      { key: "due", header: "Due", width: "104px", sortKey: "due_date", render: (w) => fmtDate(w.due_date) },
      { key: "prio", header: "Priority", width: "72px", align: "right", sortKey: "priority", render: (w) => `P${w.priority}` },
      { key: "ser", header: "Units", width: "90px", render: (w) => serialText(w.serial_from, w.serial_to) },
      { key: "dl", header: "For demand", width: "120px", render: (w) => (w.demand_line ? <span className="mono small">{w.demand_line.order_number}/{w.demand_line.line_no}</span> : "") },
      { key: "src", header: "Source", width: "96px", render: (w) => <SourceBadge source={w.source} runNo={w.source_run_no} /> },
    ],
    [],
  );

  const STATUS_LABEL: Record<string, string> = { planned: "Planned (firm)", released: "Released / in progress", done: "Completed / closed", cancelled: "Cancelled", all: "All" };
  const SOURCE_LABEL: Record<string, string> = { manual: "Entered by hand", mrp: "From MRP", import: "Imported" };
  const chips: FilterChip[] = [];
  if (dq) chips.push({ key: "q", label: "Search", value: dq, onClear: () => setQ("") });
  if (st !== "active") chips.push({ key: "status", label: "Status", value: STATUS_LABEL[st] ?? st, onClear: () => set("status", "") });
  if (source) chips.push({ key: "source", label: "Source", value: SOURCE_LABEL[source] ?? source, onClear: () => set("source", "") });

  return (
    <div className="col gap-lg">
      <PageHeader
        title="Work orders"
        description="Production orders with quantities, dates, frozen component lists, reservations and kitting."
        actions={
          <>
            <Link className="btn" to={mfgPaths.kitting()} data-testid="wo-kitting-check">
              <Icon name="check" /> Kitting check
            </Link>
            <ImportShortcut what="work orders" />
            <PermissionGate perm="wo_edit">
              <Link className="btn primary" to={mfgPaths.workOrderNew()} data-testid="wo-new">
                <Icon name="plus" /> New work order
              </Link>
            </PermissionGate>
          </>
        }
      />
      <FilterBar
        search={{ id: "wo-q", value: q, onChange: setQ, placeholder: "Number or part number", testId: "wo-search" }}
        chips={chips}
        onClearAll={() => {
          setQ("");
          setParams({}, { replace: true });
        }}
        pageKey="work-orders"
      >
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
      </FilterBar>
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
        loading={data.loading}
        sort={{ key: sort, dir: "asc" }}
        onSortChange={(x) => set("sort", !x || x.key === "start_date" ? "" : x.key)}
        exportName="work-orders"
        empty={data.loading ? "Loading…" : "No work orders match these filters. Firm planned orders from an MRP run, or create one."}
        footer={<span>Showing {fmtNum(data.rows.length)} of {fmtNum(data.total)} work orders</span>}
      />
    </div>
  );
}
