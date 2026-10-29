/** `/mfg/purchasing/orders` and `/mfg/purchasing/requests` (M2 14.2, #106/#117): paged document lists. */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listPurchaseDocs } from "../../api/clientM2";
import type { DocType, PurchaseDocSummary, PurchaseSort, PurchaseStatus } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { ImportShortcut } from "../../components/ImportShortcut";
import { PermissionGate } from "../../components/PermissionGate";
import { OverdueBadge, PurchaseStatusChip, SourceBadge } from "../../components/StatusM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { fmtMoney } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced } from "../../lib/useMfg";

export const PR_STATUSES: PurchaseStatus[] = ["draft", "submitted", "approved", "rejected", "ordered", "cancelled"];
export const PO_STATUSES: PurchaseStatus[] = ["draft", "open", "partially_received", "received", "closed", "cancelled"];
const OPEN_FILTER: Record<DocType, string> = { pr: "draft,submitted,approved,rejected", po: "draft,open,partially_received" };

export function PurchaseDocList({ docType }: { docType: DocType }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const status = params.get("status") ?? "open";
  const overdue = params.get("overdue") === "1";
  const source = params.get("source") ?? "";
  const supplier = params.get("supplier") ?? "";
  const sort = (params.get("sort") ?? "-created_at") as PurchaseSort;
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps
  const statuses = docType === "pr" ? PR_STATUSES : PO_STATUSES;
  const word = docType === "pr" ? "purchase requests" : "purchase orders";

  const data = usePaged<PurchaseDocSummary>(
    (offset, limit, signal) =>
      listPurchaseDocs(
        docType,
        {
          status: status === "all" ? undefined : status === "open" ? OPEN_FILTER[docType] : status,
          q: dq || undefined,
          overdue: overdue || undefined,
          source: (source || undefined) as PurchaseDocSummary["source"] | undefined,
          supplier_id: supplier || undefined,
          sort,
          limit,
          offset,
        },
        signal,
      ),
    [docType, status, dq, overdue, source, supplier, sort],
  );

  const columns: Column<PurchaseDocSummary>[] = useMemo(
    () => [
      {
        key: "no",
        header: "Number",
        width: "130px",
        render: (d) => (
          <Link to={mfgPaths.purchaseDoc(docType, d.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {d.number}
          </Link>
        ),
      },
      { key: "st", header: "Status", width: "180px", render: (d) => <PurchaseStatusChip status={d.status} /> },
      { key: "sup", header: "Supplier", width: "minmax(160px, 1.5fr)", render: (d) => <span className="mfg-ellipsis">{d.supplier ? `${d.supplier.code} · ${d.supplier.name}` : <span className="faint">No supplier yet</span>}</span> },
      { key: "lines", header: "Lines", width: "60px", align: "right", render: (d) => d.line_count },
      { key: "next", header: "Next delivery", width: "116px", render: (d) => fmtDate(d.next_dock_date) },
      { key: "od", header: "Overdue", width: "120px", render: (d) => (d.overdue_count > 0 ? <OverdueBadge days={0} /> : null) },
      { key: "val", header: "Open value", width: "120px", align: "right", render: (d) => fmtMoney(d.open_value, d.currency) },
      { key: "src", header: "Source", width: "100px", render: (d) => <SourceBadge source={d.source} runNo={d.source_run_no} /> },
      { key: "date", header: docType === "po" ? "Order date" : "Created", width: "110px", render: (d) => (docType === "po" ? fmtDate(d.order_date) : fmtDate(d.created_at.slice(0, 10))) },
    ],
    [docType],
  );

  return (
    <div className="col gap-lg">
      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 220px" }}>
          <label htmlFor="pd-q">Search</label>
          <input id="pd-q" className="input" type="search" placeholder="Number" value={q} onChange={(e) => setQ(e.target.value)} data-testid="docs-search" />
        </div>
        <div className="field">
          <label htmlFor="pd-status">Status</label>
          <select id="pd-status" className="select" value={status} onChange={(e) => set("status", e.target.value === "open" ? "" : e.target.value)} data-testid="docs-status">
            <option value="open">Open (not finished)</option>
            <option value="all">All</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="pd-src">Source</label>
          <select id="pd-src" className="select" value={source} onChange={(e) => set("source", e.target.value)}>
            <option value="">Any</option>
            <option value="manual">Entered by hand</option>
            <option value="mrp">From MRP</option>
            <option value="import">Imported</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="pd-sort">Sort by</label>
          <select id="pd-sort" className="select" value={sort} onChange={(e) => set("sort", e.target.value === "-created_at" ? "" : e.target.value)}>
            <option value="-created_at">Newest first</option>
            <option value="number">Number</option>
            <option value="next_dock_date">Next delivery</option>
          </select>
        </div>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={overdue} onChange={(e) => set("overdue", e.target.checked ? "1" : "")} data-testid="docs-overdue" /> Only with overdue deliveries
        </label>
        {supplier ? (
          <button type="button" className="btn sm" style={{ alignSelf: "flex-end" }} onClick={() => set("supplier", "")}>
            <Icon name="x" /> One supplier only
          </button>
        ) : null}
        <span className="grow" />
        <div className="row" style={{ alignSelf: "flex-end" }}>
          <ImportShortcut what={word} />
          <PermissionGate perm={docType === "pr" ? "pr_edit" : "po_edit"}>
            <Link className="btn primary" to={mfgPaths.purchaseDocNew(docType)} data-testid="doc-new">
              <Icon name="plus" /> New {docType === "pr" ? "request" : "order"}
            </Link>
          </PermissionGate>
        </div>
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(d) => d.id}
        label={word}
        testId="docs-table"
        totalCount={data.total}
        rowExtras={(d) => ({ testId: "doc-row", data: { number: d.number, status: d.status } })}
        onRowClick={(d) => navigate(mfgPaths.purchaseDoc(docType, d.id))}
        onActivate={(d) => navigate(mfgPaths.purchaseDoc(docType, d.id))}
        onEndReached={data.onEndReached}
        empty={data.loading ? "Loading…" : `No ${word} match these filters.`}
        footer={<span className="muted small">Showing {data.rows.length.toLocaleString()} of {data.total.toLocaleString()} {word}</span>}
      />
    </div>
  );
}
