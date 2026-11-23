/**
 * `/mfg/inventory?item=&location=` (M2 14.2): stock balances (item x location x lot) in a virtual table, pages of
 * 200 loaded while scrolling; filters in the URL; totals when one item is selected.
 */
import { useMemo, useState, useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listBalances } from "../../api/clientM2";
import type { BalancePage, BalanceRow, LocationKind } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { LocationSelect } from "../../components/PickersM2";
import { HoldBadge, LOCATION_KIND_LABEL, LocationKindBadge } from "../../components/StatusM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { fmtMoney, fmtNum } from "../../lib/formatM2";
import { useItemInfo } from "../../lib/itemCache";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced, usePlant } from "../../lib/useMfg";
import { FilterBar, type FilterChip } from "../../../components/FilterBar";
import { t } from "../../../lib/i18n";

export function BalancesTab() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const plant = usePlant();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const itemId = params.get("item") ?? "";
  const locationId = params.get("location") ?? "";
  const kind = (params.get("kind") ?? "") as LocationKind | "";
  const nettable = params.get("nettable") ?? "";
  const showZero = params.get("zero") === "1";
  const sort = (params.get("sort") ?? "part_number") as "part_number" | "location" | "-qty";
  const item = useItemInfo(itemId || null);
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = usePaged<BalanceRow, BalancePage>(
    (offset, limit, signal) =>
      listBalances(
        {
          q: dq || undefined,
          item_id: itemId || undefined,
          location_id: locationId || undefined,
          kind: kind || undefined,
          nettable: nettable === "" ? undefined : nettable === "true",
          only_nonzero: !showZero,
          sort,
          limit,
          offset,
        },
        signal,
      ),
    [dq, itemId, locationId, kind, nettable, showZero, sort],
  );
  const currency = plant.data?.currency ?? "";

  const columns: Column<BalanceRow>[] = useMemo(
    () => [
      {
        key: "pn",
        header: t("mfg.balancesTab.str.partNumber"),
        width: "minmax(150px, 1.2fr)",
        render: (b) => (
          <Link to={mfgPaths.itemStock(b.item.id)} className="mono mfg-ellipsis" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {b.item.part_number}
          </Link>
        ),
      },
      { key: "desc", header: t("mfg.balancesTab.str.description"), width: "minmax(160px, 1.6fr)", render: (b) => <span className="mfg-ellipsis">{b.item.description}</span> },
      {
        key: "loc",
        header: t("mfg.balancesTab.str.location"),
        width: "minmax(130px, 1fr)",
        render: (b) => (
          <span className="mfg-ellipsis" title={`${b.location.name} (${LOCATION_KIND_LABEL[b.location.kind]})`}>
            <span className="mono">{b.location.code}</span>
          </span>
        ),
      },
      { key: "kind", header: t("mfg.balancesTab.str.kind"), width: "118px", render: (b) => <LocationKindBadge kind={b.location.kind} /> },
      {
        key: "lot",
        header: t("mfg.balancesTab.str.lot"),
        width: "minmax(110px, 0.9fr)",
        render: (b) =>
          b.lot ? (
            <span className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
              <Link to={mfgPaths.lots(b.lot.id)} className="mono mfg-ellipsis" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
                {b.lot.lot_code}
              </Link>
              {b.lot.hold ? <HoldBadge /> : null}
            </span>
          ) : (
            <span className="faint">-</span>
          ),
      },
      { key: "exp", header: t("mfg.balancesTab.str.expires"), width: "100px", render: (b) => (b.lot?.expires_on ? fmtDate(b.lot.expires_on) : "") },
      { key: "oh", header: t("mfg.balancesTab.str.onHand"), width: "92px", align: "right", render: (b) => fmtNum(b.qty_on_hand) },
      { key: "res", header: t("mfg.balancesTab.str.reserved"), width: "86px", align: "right", render: (b) => (b.qty_reserved ? fmtNum(b.qty_reserved) : <span className="faint">0</span>) },
      { key: "av", header: t("mfg.balancesTab.str.available"), width: "92px", align: "right", render: (b) => <strong>{fmtNum(b.qty_available)}</strong> },
      { key: "uom", header: t("mfg.balancesTab.str.unit"), width: "50px", render: (b) => b.item.uom },
      {
        key: "net",
        header: t("mfg.balancesTab.str.plannable"),
        width: "92px",
        render: (b) =>
          b.nettable ? (
            <span className="mfg-yes" title={t("mfg.balancesTab.attr.countedByMrpAndKitting")}>
              <Icon name="check" size={14} /> {t("mfg.balancesTab.btn.yes")}
            </span>
          ) : (
            <span className="faint" title={t("mfg.balancesTab.attr.notCountedByMrpQuarantine")}>
              <Icon name="ban" size={12} /> {t("mfg.balancesTab.btn.no")}
            </span>
          ),
      },
      { key: "val", header: t("mfg.balancesTab.str.value"), width: "100px", align: "right", render: (b) => fmtMoney(b.value) },
      { key: "rcv", header: t("mfg.balancesTab.str.lastReceipt"), width: "104px", render: (b) => fmtDate(b.last_receipt_on) },
    ],
    [],
  );

  const totals = data.last?.totals;
  const filtered = Boolean(dq || itemId || locationId || kind || nettable);

  const chips: FilterChip[] = [];
  if (q.trim()) chips.push({ key: "q", label: t("mfg.balancesTab.str.search"), value: q.trim(), onClear: () => setQ("") });
  if (itemId) chips.push({ key: "item", label: t("mfg.balancesTab.str.item"), value: "One item", onClear: () => set("item", "") });
  if (locationId) chips.push({ key: "loc", label: t("mfg.balancesTab.str.location"), value: "One location", onClear: () => set("location", "") });
  if (kind) chips.push({ key: "kind", label: t("mfg.balancesTab.str.kind"), value: LOCATION_KIND_LABEL[kind], onClear: () => set("kind", "") });
  if (nettable) chips.push({ key: "net", label: t("mfg.balancesTab.str.plannable"), value: nettable === "true" ? "Yes" : "No", onClear: () => set("nettable", "") });
  if (showZero) chips.push({ key: "zero", label: t("mfg.balancesTab.str.balances"), value: "Including empty", onClear: () => set("zero", "") });

  return (
    <div className="col gap-lg">
      <FilterBar chips={chips} onClearAll={() => (setQ(""), setParams({}, { replace: true }))} search={{ id: "bal-q", value: q, onChange: setQ, placeholder: "Part number, description or lot", testId: "balances-search" }} pageKey="BalancesTab">
        <div style={{ minWidth: 220 }}>
          <LocationSelect label={t("mfg.balancesTab.label.location")} value={locationId} onChange={(v) => set("location", v)} allowEmpty emptyLabel="All locations" includeInactive testId="balances-location" />
        </div>
        <div className="field">
          <label htmlFor="bal-kind">{t("mfg.balancesTab.label.kind")}</label>
          <select id="bal-kind" className="select" value={kind} onChange={(e) => set("kind", e.target.value)} data-testid="balances-kind">
            <option value="">{t("mfg.balancesTab.text.allKinds")}</option>
            {(Object.keys(LOCATION_KIND_LABEL) as LocationKind[]).map((k) => (
              <option key={k} value={k}>
                {LOCATION_KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="bal-net">{t("mfg.balancesTab.label.plannable")}</label>
          <select id="bal-net" className="select" value={nettable} onChange={(e) => set("nettable", e.target.value)}>
            <option value="">{t("mfg.balancesTab.text.any")}</option>
            <option value="true">{t("mfg.balancesTab.text.countedByMrp")}</option>
            <option value="false">{t("mfg.balancesTab.text.notCounted")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="bal-sort">{t("mfg.balancesTab.label.sortBy")}</label>
          <select id="bal-sort" className="select" value={sort} onChange={(e) => set("sort", e.target.value === "part_number" ? "" : e.target.value)}>
            <option value="part_number">{t("mfg.balancesTab.text.partNumber")}</option>
            <option value="location">{t("mfg.balancesTab.text.location")}</option>
            <option value="-qty">{t("mfg.balancesTab.text.largestQuantity")}</option>
          </select>
        </div>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={showZero} onChange={(e) => set("zero", e.target.checked ? "1" : "")} />{" "}{t("mfg.balancesTab.text.showEmptyBalances")}
        </label>
      </FilterBar>

      {itemId ? (
        <div className="card card-body row wrap between" data-testid="balances-item-filter">
          <div className="row wrap">
            <span className="muted small">{t("mfg.balancesTab.text.item")}</span>
            <Link to={mfgPaths.itemStock(itemId)} className="mono">
              {item?.part_number ?? itemId}
            </Link>
            <span className="muted small">{item?.description}</span>
            <button type="button" className="btn sm ghost" onClick={() => set("item", "")}>
              <Icon name="x" /> {t("mfg.balancesTab.btn.showAllItems")}
            </button>
          </div>
          {totals ? (
            <div className="mfg-totals" data-testid="balances-totals">
              <div>
                <span className="mfg-total-label">{t("mfg.balancesTab.text.onHand")}</span>
                <span className="mfg-total-value">{fmtNum(totals.qty_on_hand)}</span>
              </div>
              <div>
                <span className="mfg-total-label">{t("mfg.balancesTab.text.reserved")}</span>
                <span className="mfg-total-value">{fmtNum(totals.qty_reserved)}</span>
              </div>
              <div>
                <span className="mfg-total-label">{t("mfg.balancesTab.text.value")}</span>
                <span className="mfg-total-value">{fmtMoney(totals.value, currency)}</span>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        card={{ title: "pn", fields: ["desc", "loc", "av"] }}
        rows={data.rows}
        columns={columns}
        rowKey={(b) => b.id}
        label={t("mfg.balancesTab.label.stockBalances")}
        testId="balances-table"
        totalCount={data.total}
        height="min(64vh, 700px)"
        rowExtras={(b) => ({
          testId: "balance-row",
          data: { item: b.item.part_number, location: b.location.code, qty: b.qty_on_hand, lot: b.lot?.lot_code },
          className: b.nettable ? undefined : "mfg-inactive",
        })}
        onActivate={(b) => navigate(mfgPaths.transactions({ item: b.item.id }))}
        onEndReached={data.onEndReached}
        empty={
          data.loading ? (
            <span className="row" role="status">
              <span className="spinner" aria-hidden />{" "}{t("mfg.balancesTab.text.loadingStock")}
            </span>
          ) : filtered ? (
            t("mfg.balancesTab.str.noStockMatchesTheseFilters")
          ) : (
            <span>
              {t("mfg.balancesTab.text.noStockYetPostA")}{" "}<Link to={mfgPaths.importStart()}>{t("mfg.balancesTab.text.importAStockList")}</Link>{" "}{t("mfg.balancesTab.text.or", { v: " " })}
              <Link to={mfgPaths.home()}>{t("mfg.balancesTab.text.loadASample")}</Link>.
            </span>
          )
        }
        footer={
          <span className="muted small" role="status" data-testid="balances-count">
            {data.loading && data.rows.length ? <span className="spinner" aria-hidden /> : null}{" "}{t("mfg.balancesTab.text.showingOfBalancesEnterOn", { length: data.rows.length.toLocaleString("en-IN"), v: " ", total: data.total.toLocaleString("en-IN") })}
          </span>
        }
      />
    </div>
  );
}
