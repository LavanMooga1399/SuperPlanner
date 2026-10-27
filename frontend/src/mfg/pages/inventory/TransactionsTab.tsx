/** `/mfg/inventory/transactions?item=&posting=` (M2 14.2): the stock ledger, newest first, with filters. */
import { useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listTransactions } from "../../api/clientM2";
import type { ItemRef } from "../../api/types";
import { POSTING_TYPES, type PostingType, type TransactionRow } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { ItemPicker } from "../../components/ItemPicker";
import { LocationSelect } from "../../components/PickersM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate, fmtTimestamp } from "../../lib/format";
import { fmtNum, POSTING_LABEL } from "../../lib/formatM2";
import { useItemInfo } from "../../lib/itemCache";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";

/** Link of a document reference on a ledger line. */
export function docRefLink(ref: TransactionRow["ref"]): string | null {
  if (!ref) return null;
  if (ref.type === "po" || ref.type === "pr") return mfgPaths.purchaseDoc(ref.type, ref.id);
  if (ref.type === "wo") return mfgPaths.workOrder(ref.id);
  if (ref.type === "demand") return mfgPaths.demandOrder(ref.id);
  return null;
}

export function TransactionsTab() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const itemId = params.get("item") ?? "";
  const postingId = params.get("posting") ?? "";
  const locationId = params.get("location") ?? "";
  const txnType = (params.get("type") ?? "") as PostingType | "";
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  const item = useItemInfo(itemId || null);
  const itemRef: ItemRef | null = item
    ? { id: item.id, part_number: item.part_number, revision: item.revision, description: item.description, uom: item.uom, make_buy: item.make_buy, active: item.active }
    : null;

  const data = usePaged<TransactionRow>(
    (offset, limit, signal) =>
      listTransactions(
        {
          item_id: itemId || undefined,
          posting_id: postingId || undefined,
          location_id: locationId || undefined,
          txn_type: txnType || undefined,
          from: from || undefined,
          to: to || undefined,
          limit,
          offset,
        },
        signal,
      ),
    [itemId, postingId, locationId, txnType, from, to],
  );

  const columns: Column<TransactionRow>[] = useMemo(
    () => [
      { key: "seq", header: "#", width: "74px", align: "right", render: (t) => <span className="faint mono">{t.seq}</span> },
      { key: "date", header: "Date", width: "100px", render: (t) => fmtDate(t.txn_date) },
      {
        key: "post",
        header: "Posting",
        width: "120px",
        render: (t) => (
          <Link to={mfgPaths.posting(t.posting_id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {t.posting_number}
          </Link>
        ),
      },
      { key: "type", header: "Type", width: "minmax(150px, 1fr)", render: (t) => <span className="mfg-ellipsis">{POSTING_LABEL[t.txn_type] ?? t.txn_type}</span> },
      {
        key: "pn",
        header: "Part number",
        width: "minmax(140px, 1fr)",
        render: (t) => (
          <Link to={mfgPaths.itemStock(t.item.id)} className="mono mfg-ellipsis" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {t.item.part_number}
          </Link>
        ),
      },
      { key: "loc", header: "Location", width: "110px", render: (t) => <span className="mono mfg-ellipsis">{t.location.code}</span> },
      { key: "lot", header: "Lot", width: "110px", render: (t) => <span className="mono mfg-ellipsis">{t.lot?.lot_code ?? ""}</span> },
      {
        key: "qty",
        header: "Change",
        width: "90px",
        align: "right",
        render: (t) => (
          <span className={t.qty < 0 ? "mfg-neg" : "mfg-pos"}>
            {t.qty > 0 ? "+" : t.qty < 0 ? "−" : ""}
            {fmtNum(Math.abs(t.qty))}
          </span>
        ),
      },
      { key: "after", header: "Balance after", width: "100px", align: "right", render: (t) => fmtNum(t.balance_after) },
      {
        key: "ref",
        header: "Document",
        width: "minmax(130px, 1fr)",
        render: (t) => {
          const href = docRefLink(t.ref);
          return t.ref ? (
            href ? (
              <Link to={href} className="mfg-ellipsis" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
                {t.ref.label}
              </Link>
            ) : (
              <span className="mfg-ellipsis">{t.ref.label}</span>
            )
          ) : (
            <span className="faint">-</span>
          );
        },
      },
      { key: "who", header: "By", width: "110px", render: (t) => <span className="mfg-ellipsis" title={fmtTimestamp(t.created_at)}>{t.actor.name}</span> },
    ],
    [],
  );

  return (
    <div className="col gap-lg">
      <div className="toolbar mfg-filters" role="search">
        <div style={{ width: 240 }}>
          <ItemPicker label="Item" value={itemRef} onChange={(it) => set("item", it.id)} testId="txn-item" placeholder="All items" />
        </div>
        {itemId ? (
          <button type="button" className="btn sm ghost" style={{ alignSelf: "flex-end" }} onClick={() => set("item", "")}>
            <Icon name="x" /> All items
          </button>
        ) : null}
        <div style={{ minWidth: 200 }}>
          <LocationSelect label="Location" value={locationId} onChange={(v) => set("location", v)} allowEmpty emptyLabel="All locations" includeInactive />
        </div>
        <div className="field">
          <label htmlFor="txn-type">Type</label>
          <select id="txn-type" className="select" value={txnType} onChange={(e) => set("type", e.target.value)} data-testid="txn-type">
            <option value="">All types</option>
            {POSTING_TYPES.map((t) => (
              <option key={t} value={t}>
                {POSTING_LABEL[t]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="txn-from">From</label>
          <input id="txn-from" className="input" type="date" value={from} onChange={(e) => set("from", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="txn-to">To</label>
          <input id="txn-to" className="input" type="date" value={to} onChange={(e) => set("to", e.target.value)} />
        </div>
        {postingId ? (
          <button type="button" className="btn sm" style={{ alignSelf: "flex-end" }} onClick={() => set("posting", "")}>
            <Icon name="x" /> Only posting {data.rows[0]?.posting_number ?? ""}
          </button>
        ) : null}
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(t) => t.id}
        label="Stock ledger"
        testId="txn-table"
        totalCount={data.total}
        height="min(64vh, 700px)"
        rowExtras={(t) => ({ testId: "txn-row", data: { type: t.txn_type, item: t.item.part_number, qty: t.qty, posting: t.posting_number } })}
        onActivate={(t) => navigate(mfgPaths.posting(t.posting_id))}
        onEndReached={data.onEndReached}
        empty={data.loading ? <span className="row" role="status"><span className="spinner" aria-hidden /> Loading the ledger…</span> : "No stock movements match these filters."}
        footer={
          <span className="muted small" role="status">
            Showing {data.rows.length.toLocaleString()} of {data.total.toLocaleString()} movements, newest first · Enter opens the posting
          </span>
        }
      />
    </div>
  );
}
