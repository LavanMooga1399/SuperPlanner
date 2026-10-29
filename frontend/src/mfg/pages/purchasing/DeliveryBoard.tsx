/** `/mfg/purchasing/schedule?overdue=1&supplier=` (M2 14.2, #125): every open delivery line by dock date. */
import { useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listScheduleBoard } from "../../api/clientM2";
import type { Ref } from "../../api/types";
import type { DocType, ScheduleRow } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { SupplierPicker } from "../../components/PickersM2";
import { OverdueBadge, PurchaseStatusChip } from "../../components/StatusM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { setSearchParam, usePaged } from "../../lib/usePaged";

export function scheduleColumns(): Column<ScheduleRow>[] {
  return [
    {
      key: "doc",
      header: "Document",
      width: "170px",
      render: (s) => (
        <Link to={s.link} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
          {s.doc.number} / {s.line_no} / {s.seq}
        </Link>
      ),
    },
    { key: "pn", header: "Part number", width: "minmax(140px, 1fr)", render: (s) => <span className="mono mfg-ellipsis">{s.item.part_number}</span> },
    { key: "sup", header: "Supplier", width: "minmax(120px, 1fr)", render: (s) => <span className="mfg-ellipsis">{s.supplier?.code ?? ""}</span> },
    { key: "dock", header: "Dock date", width: "106px", render: (s) => <strong>{fmtDate(s.dock_date)}</strong> },
    {
      key: "conf",
      header: "Requested / confirmed",
      width: "170px",
      render: (s) => (
        <span className="small">
          {fmtDate(s.requested_date)}
          {s.confirmed_date ? ` / ${fmtDate(s.confirmed_date)}` : " / not confirmed"}
        </span>
      ),
    },
    { key: "av", header: "Available", width: "100px", render: (s) => fmtDate(s.available_date) },
    { key: "open", header: "Open", width: "84px", align: "right", render: (s) => `${fmtNum(s.open_qty)}` },
    { key: "qty", header: "Ordered", width: "80px", align: "right", render: (s) => fmtNum(s.qty) },
    { key: "od", header: "Status", width: "130px", render: (s) => (s.overdue ? <OverdueBadge days={s.overdue_days} /> : <PurchaseStatusChip status={s.doc.status} />) },
  ];
}

export function DeliveryBoard() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const overdue = params.get("overdue") === "1";
  const supplier = params.get("supplier") ?? "";
  const supplierLabel = params.get("supplier_label") ?? "";
  const docType = (params.get("doc_type") ?? "") as DocType | "";
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  const supRef: Ref | null = supplier ? { id: supplier, code: supplierLabel || supplier, name: "" } : null;
  const data = usePaged<ScheduleRow>(
    (offset, limit, signal) =>
      listScheduleBoard({ overdue_only: overdue || undefined, supplier_id: supplier || undefined, doc_type: docType || undefined, from: from || undefined, to: to || undefined, limit, offset }, signal),
    [overdue, supplier, docType, from, to],
  );
  const columns = useMemo(scheduleColumns, []);
  return (
    <div className="col gap-lg">
      <div className="toolbar mfg-filters" role="search">
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={overdue} onChange={(e) => set("overdue", e.target.checked ? "1" : "")} data-testid="board-overdue" /> Only overdue
        </label>
        <div style={{ width: 260 }}>
          <SupplierPicker
            label="Supplier"
            value={supRef}
            allowClear
            onChange={(s) =>
              setParams(
                (prev) => {
                  const n = new URLSearchParams(prev);
                  if (s) {
                    n.set("supplier", s.id);
                    n.set("supplier_label", s.code);
                  } else {
                    n.delete("supplier");
                    n.delete("supplier_label");
                  }
                  return n;
                },
                { replace: true },
              )
            }
          />
        </div>
        <div className="field">
          <label htmlFor="board-type">Documents</label>
          <select id="board-type" className="select" value={docType} onChange={(e) => set("doc_type", e.target.value)}>
            <option value="">Orders and requests</option>
            <option value="po">Purchase orders</option>
            <option value="pr">Purchase requests</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="board-from">Dock from</label>
          <input id="board-from" type="date" className="input" value={from} onChange={(e) => set("from", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="board-to">Dock to</label>
          <input id="board-to" type="date" className="input" value={to} onChange={(e) => set("to", e.target.value)} />
        </div>
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        <Icon name="info" size={12} /> Dock date = confirmed date, else requested date. Available = dock date + the part's goods-in inspection days.
      </p>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(s) => s.schedule_id}
        label="Delivery schedule"
        testId="board-table"
        totalCount={data.total}
        height="min(66vh, 720px)"
        rowExtras={(s) => ({ testId: "board-row", data: { overdue: s.overdue, doc: s.doc.number } })}
        onActivate={(s) => navigate(s.link)}
        onEndReached={data.onEndReached}
        empty={data.loading ? "Loading deliveries…" : "No open deliveries match these filters."}
        footer={<span className="muted small">Showing {data.rows.length.toLocaleString()} of {data.total.toLocaleString()} open deliveries</span>}
      />
    </div>
  );
}
