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
import { FilterBar, type FilterChip } from "../../../components/FilterBar";
import { DateInput } from "../../../components/DateInput";
import { t, t as tr } from "../../../lib/i18n";

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
  const sort = params.get("sort") ?? "-seq";
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
          sort: sort === "-seq" ? undefined : sort,
          limit,
          offset,
        },
        signal,
      ),
    [itemId, postingId, locationId, txnType, from, to, sort],
  );

  const columns: Column<TransactionRow>[] = useMemo(
    () => [
      { key: "seq", header: "#", width: "74px", sortKey: "seq", sortKeyDesc: "-seq", align: "right", render: (t) => <span className="faint mono">{t.seq}</span> },
      { key: "date", header: tr("mfg.transactionsTab.str.date"), width: "100px", sortKey: "txn_date", sortKeyDesc: "-txn_date", render: (t) => fmtDate(t.txn_date) },
      {
        key: "post",
        header: tr("mfg.transactionsTab.str.posting"),
        width: "120px",
        render: (t) => (
          <Link to={mfgPaths.posting(t.posting_id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {t.posting_number}
          </Link>
        ),
      },
      { key: "type", header: tr("mfg.transactionsTab.str.type"), width: "minmax(150px, 1fr)", sortKey: "txn_type", render: (t) => <span className="mfg-ellipsis">{POSTING_LABEL[t.txn_type] ?? t.txn_type}</span> },
      {
        key: "pn",
        header: tr("mfg.transactionsTab.str.partNumber"),
        width: "minmax(140px, 1fr)",
        sortKey: "part_number",
        render: (t) => (
          <Link to={mfgPaths.itemStock(t.item.id)} className="mono mfg-ellipsis" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {t.item.part_number}
          </Link>
        ),
      },
      { key: "loc", header: tr("mfg.transactionsTab.str.location"), width: "110px", render: (t) => <span className="mono mfg-ellipsis">{t.location.code}</span> },
      { key: "lot", header: tr("mfg.transactionsTab.str.lot"), width: "110px", render: (t) => <span className="mono mfg-ellipsis">{t.lot?.lot_code ?? ""}</span> },
      {
        key: "qty",
        header: tr("mfg.transactionsTab.str.change"),
        width: "96px",
        sortKey: "qty",
        sortKeyDesc: "-qty",
        align: "right",
        render: (t) => (
          <span className={t.qty < 0 ? "mfg-neg" : "mfg-pos"}>
            {t.qty > 0 ? "+" : t.qty < 0 ? "−" : ""}
            {fmtNum(Math.abs(t.qty))}
          </span>
        ),
      },
      { key: "after", header: tr("mfg.transactionsTab.str.balanceAfter"), width: "100px", align: "right", render: (t) => fmtNum(t.balance_after) },
      {
        key: "ref",
        header: tr("mfg.transactionsTab.str.document"),
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
      { key: "who", header: tr("mfg.transactionsTab.str.by"), width: "110px", render: (t) => <span className="mfg-ellipsis" title={fmtTimestamp(t.created_at)}>{t.actor.name}</span> },
    ],
    [],
  );

  const chips: FilterChip[] = [];
  if (itemId) chips.push({ key: "item", label: tr("mfg.transactionsTab.str.item"), value: "One item", onClear: () => set("item", "") });
  if (postingId) chips.push({ key: "posting", label: tr("mfg.transactionsTab.str.posting"), value: "One posting", onClear: () => set("posting", "") });
  if (locationId) chips.push({ key: "loc", label: tr("mfg.transactionsTab.str.location"), value: "One location", onClear: () => set("location", "") });
  if (txnType) chips.push({ key: "type", label: tr("mfg.transactionsTab.str.type"), value: POSTING_LABEL[txnType] ?? txnType, onClear: () => set("type", "") });
  if (from) chips.push({ key: "from", label: tr("mfg.transactionsTab.str.from"), value: fmtDate(from), onClear: () => set("from", "") });
  if (to) chips.push({ key: "to", label: tr("mfg.transactionsTab.str.to"), value: fmtDate(to), onClear: () => set("to", "") });

  return (
    <div className="col gap-lg">
      <FilterBar chips={chips} onClearAll={() => setParams({}, { replace: true })} pageKey="TransactionsTab">
        <div style={{ width: 240 }}>
          <ItemPicker label={t("mfg.transactionsTab.label.item")} value={itemRef} onChange={(it) => set("item", it.id)} testId="txn-item" placeholder={t("mfg.transactionsTab.ph.allItems")} />
        </div>
        {itemId ? (
          <button type="button" className="btn sm ghost" style={{ alignSelf: "flex-end" }} onClick={() => set("item", "")}>
            <Icon name="x" /> {t("mfg.transactionsTab.btn.allItems")}
          </button>
        ) : null}
        <div style={{ minWidth: 200 }}>
          <LocationSelect label={t("mfg.transactionsTab.label.location")} value={locationId} onChange={(v) => set("location", v)} allowEmpty emptyLabel="All locations" includeInactive />
        </div>
        <div className="field">
          <label htmlFor="txn-type">{t("mfg.transactionsTab.label.type")}</label>
          <select id="txn-type" className="select" value={txnType} onChange={(e) => set("type", e.target.value)} data-testid="txn-type">
            <option value="">{tr("mfg.transactionsTab.text.allTypes")}</option>
            {POSTING_TYPES.map((t) => (
              <option key={t} value={t}>
                {POSTING_LABEL[t]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="txn-from">{t("mfg.transactionsTab.label.from")}</label>
          <DateInput id="txn-from" value={from} onChange={(v) => set("from", v)} />
        </div>
        <div className="field">
          <label htmlFor="txn-to">{t("mfg.transactionsTab.label.to")}</label>
          <DateInput id="txn-to" value={to} onChange={(v) => set("to", v)} />
        </div>
        {postingId ? (
          <button type="button" className="btn sm" style={{ alignSelf: "flex-end" }} onClick={() => set("posting", "")}>
            <Icon name="x" />{" "}{tr("mfg.transactionsTab.text.onlyPosting", { v: data.rows[0]?.posting_number ?? "" })}
          </button>
        ) : null}
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        card={{ title: "post", fields: ["date", "type", "pn", "qty"] }}
        rows={data.rows}
        columns={columns}
        rowKey={(t) => t.id}
        sort={{ key: sort, dir: sort.startsWith("-") ? "desc" : "asc" }}
        onSortChange={(x) => setSearchParam(setParams, "sort", !x || x.key === "-seq" ? "" : x.key)}
        label={t("mfg.transactionsTab.label.stockLedger")}
        testId="txn-table"
        totalCount={data.total}
        height="min(64vh, 700px)"
        rowExtras={(t) => ({ testId: "txn-row", data: { type: t.txn_type, item: t.item.part_number, qty: t.qty, posting: t.posting_number } })}
        onActivate={(t) => navigate(mfgPaths.posting(t.posting_id))}
        onEndReached={data.onEndReached}
        empty={data.loading ? <span className="row" role="status"><span className="spinner" aria-hidden />{" "}{tr("mfg.transactionsTab.text.loadingTheLedger")}</span> : tr("mfg.transactionsTab.str.noStockMovementsMatchThese")}
        footer={
          <span className="muted small" role="status">
            {tr("mfg.transactionsTab.text.showingMovementsNewestFirstEnter", { tr: tr("common.nOfM", { n: data.rows.length.toLocaleString("en-IN"), m: data.total.toLocaleString("en-IN") }) })}
          </span>
        }
      />
    </div>
  );
}
