/** `/mfg/purchasing/orders` and `/mfg/purchasing/requests` (M2 14.2, #106/#117): paged document lists. */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { FilterBar, type FilterChip } from "../../../components/FilterBar";
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
import { BulkActions, ReasonField, bulkRows, useSelection, type BulkActionDef } from "../../components/BulkActions";
import { useCan } from "../../lib/permissions";

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
        sortKey: "number",
        exportValue: (d) => d.number,
        render: (d) => (
          <Link to={mfgPaths.purchaseDoc(docType, d.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {d.number}
          </Link>
        ),
      },
      { key: "st", header: "Status", width: "180px", render: (d) => <PurchaseStatusChip status={d.status} /> },
      { key: "sup", header: "Supplier", width: "minmax(160px, 1.5fr)", render: (d) => <span className="mfg-ellipsis">{d.supplier ? `${d.supplier.code} · ${d.supplier.name}` : <span className="faint">No supplier yet</span>}</span> },
      { key: "lines", header: "Lines", width: "60px", align: "right", render: (d) => d.line_count },
      { key: "next", header: "Next delivery", width: "120px", sortKey: "next_dock_date", render: (d) => fmtDate(d.next_dock_date) },
      { key: "od", header: "Overdue", width: "120px", render: (d) => (d.overdue_count > 0 ? <OverdueBadge days={0} /> : null) },
      {
        key: "val",
        header: "Open value",
        width: "120px",
        align: "right",
        exportValue: (d) => d.open_value ?? "",
        // null = at least one line has no unit price (the server does not guess a value)
        render: (d) =>
          d.open_value === null ? (
            <span className="faint" title="At least one line has no unit price, so the value is unknown" data-testid="doc-value-unpriced">
              No price
            </span>
          ) : (
            fmtMoney(d.open_value, d.currency)
          ),
      },
      { key: "src", header: "Source", width: "100px", render: (d) => <SourceBadge source={d.source} runNo={d.source_run_no} /> },
      { key: "date", header: docType === "po" ? "Order date" : "Created", width: "110px", sortKey: "-created_at", render: (d) => (docType === "po" ? fmtDate(d.order_date) : fmtDate(d.created_at.slice(0, 10))) },
    ],
    [docType],
  );

  const canEditDocs = useCan(docType === "pr" ? "pr_edit" : "po_edit");
  const canApprove = useCan("pr_approve");
  const [selected, setSelected] = useSelection(`${docType}${params.toString()}`);
  const docNoun = (n: number) => (docType === "pr" ? (n === 1 ? "this purchase request" : `these ${n} purchase requests`) : n === 1 ? "this purchase order" : `these ${n} purchase orders`);
  const bulkDefs: BulkActionDef[] =
    docType === "pr"
      ? [
          ...(canEditDocs ? [{ action: "purchase-requests/submit" as const, label: "Submit", icon: "arrow-right" as const, testId: "bulk-pr-submit", what: (n: number) => `Submit ${docNoun(n)} for approval.`, effect: "Drafts go to the approvers." }] : []),
          ...(canApprove
            ? [
                { action: "purchase-requests/approve" as const, label: "Approve", icon: "check" as const, testId: "bulk-pr-approve", what: (n: number) => `Approve ${docNoun(n)}.`, effect: "Approved requests can be converted to purchase orders. You cannot approve your own requests." },
                {
                  action: "purchase-requests/reject" as const,
                  label: "Reject",
                  icon: "x" as const,
                  danger: true,
                  testId: "bulk-pr-reject",
                  what: (n: number) => `Reject ${docNoun(n)}.`,
                  effect: "The requester sees your reason.",
                  form: (f: Record<string, string>, set: (k: string, v: string) => void) => <ReasonField id="bulk-reject" label="Reason" required value={f.reason ?? ""} onChange={(v) => set("reason", v)} testId="bulk-reject-reason" />,
                  params: (f: Record<string, string>) => ({ reason: (f.reason ?? "").trim() }),
                  ready: (f: Record<string, string>) => Boolean(f.reason?.trim()),
                },
              ]
            : []),
        ]
      : canEditDocs
        ? [{ action: "purchase-orders/cancel", label: "Cancel", icon: "ban", danger: true, testId: "bulk-po-cancel", what: (n) => `Cancel ${docNoun(n)}.`, effect: "Open deliveries are no longer expected and MRP stops counting them as supply; this cannot be undone." }]
        : [];
  const chips: FilterChip[] = [];
  if (q.trim()) chips.push({ key: "q", label: "Search", value: q.trim(), onClear: () => setQ("") });
  if (status !== "open") chips.push({ key: "st", label: "Status", value: status.replace(/_/g, " "), onClear: () => set("status", "") });
  if (source) chips.push({ key: "src", label: "Source", value: source, onClear: () => set("source", "") });
  if (overdue) chips.push({ key: "od", label: "Deliveries", value: "Overdue only", onClear: () => set("overdue", "") });
  if (supplier) chips.push({ key: "sup", label: "Supplier", value: "One supplier", onClear: () => set("supplier", "") });

  return (
    <div className="col gap-lg">
      <FilterBar
        search={{ id: "pd-q", value: q, onChange: setQ, placeholder: "Number", testId: "docs-search" }}
        chips={chips}
        onClearAll={() => {
          setQ("");
          setParams({}, { replace: true });
        }}
        pageKey={`purchasing-${docType}`}
        end={
          <>
            <ImportShortcut what={word} />
            <PermissionGate perm={docType === "pr" ? "pr_edit" : "po_edit"}>
              <Link className="btn primary" to={mfgPaths.purchaseDocNew(docType)} data-testid="doc-new">
                <Icon name="plus" /> New {docType === "pr" ? "request" : "order"}
              </Link>
            </PermissionGate>
          </>
        }
      >
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
        <label className="checkbox" style={{ alignSelf: "flex-end", height: "var(--control-h)" }}>
          <input type="checkbox" checked={overdue} onChange={(e) => set("overdue", e.target.checked ? "1" : "")} data-testid="docs-overdue" /> Only with overdue deliveries
        </label>
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      {bulkDefs.length ? <BulkActions rows={bulkRows(data.rows, selected)} noun={docType === "pr" ? ["purchase request", "purchase requests"] : ["purchase order", "purchase orders"]} actions={bulkDefs} onDone={() => (setSelected(new Set()), data.reload())} onClear={() => setSelected(new Set())} /> : null}
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(d) => d.id}
        label={word}
        testId="docs-table"
        card={{ title: "no", status: "st", fields: ["sup", "next", "val"] }}
        selection={bulkDefs.length ? { selected, onChange: setSelected, rowId: (d) => d.id, rowLabel: (d) => d.number } : undefined}
        totalCount={data.total}
        rowExtras={(d) => ({ testId: "doc-row", data: { number: d.number, status: d.status } })}
        onRowClick={(d) => navigate(mfgPaths.purchaseDoc(docType, d.id))}
        onActivate={(d) => navigate(mfgPaths.purchaseDoc(docType, d.id))}
        onEndReached={data.onEndReached}
        loading={data.loading}
        sort={{ key: sort, dir: sort.startsWith("-") ? "desc" : "asc" }}
        onSortChange={(x) => set("sort", !x || x.key === "-created_at" ? "" : x.key)}
        exportName={docType === "po" ? "purchase-orders" : "purchase-requests"}
        empty={data.loading ? "Loading…" : `No ${word} match these filters.`}
        footer={<span>Showing {data.rows.length.toLocaleString("en-IN")} of {data.total.toLocaleString("en-IN")} {word}</span>}
      />
    </div>
  );
}
