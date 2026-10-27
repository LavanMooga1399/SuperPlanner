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
        header: "Part number",
        width: "minmax(150px, 1.2fr)",
        render: (b) => (
          <Link to={mfgPaths.itemStock(b.item.id)} className="mono mfg-ellipsis" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {b.item.part_number}
          </Link>
        ),
      },
      { key: "desc", header: "Description", width: "minmax(160px, 1.6fr)", render: (b) => <span className="mfg-ellipsis">{b.item.description}</span> },
      {
        key: "loc",
        header: "Location",
        width: "minmax(130px, 1fr)",
        render: (b) => (
          <span className="mfg-ellipsis" title={`${b.location.name} (${LOCATION_KIND_LABEL[b.location.kind]})`}>
            <span className="mono">{b.location.code}</span>
          </span>
        ),
      },
      { key: "kind", header: "Kind", width: "118px", render: (b) => <LocationKindBadge kind={b.location.kind} /> },
      {
        key: "lot",
        header: "Lot",
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
      { key: "exp", header: "Expires", width: "100px", render: (b) => (b.lot?.expires_on ? fmtDate(b.lot.expires_on) : "") },
      { key: "oh", header: "On hand", width: "92px", align: "right", render: (b) => fmtNum(b.qty_on_hand) },
      { key: "res", header: "Reserved", width: "86px", align: "right", render: (b) => (b.qty_reserved ? fmtNum(b.qty_reserved) : <span className="faint">0</span>) },
      { key: "av", header: "Available", width: "92px", align: "right", render: (b) => <strong>{fmtNum(b.qty_available)}</strong> },
      { key: "uom", header: "Unit", width: "50px", render: (b) => b.item.uom },
      {
        key: "net",
        header: "Plannable",
        width: "92px",
        render: (b) =>
          b.nettable ? (
            <span className="mfg-yes" title="Counted by MRP and kitting">
              <Icon name="check" size={14} /> Yes
            </span>
          ) : (
            <span className="faint" title="Not counted by MRP (quarantine, held or expired)">
              <Icon name="ban" size={12} /> No
            </span>
          ),
      },
      { key: "val", header: "Value", width: "100px", align: "right", render: (b) => fmtMoney(b.value) },
      { key: "rcv", header: "Last receipt", width: "104px", render: (b) => fmtDate(b.last_receipt_on) },
    ],
    [],
  );

  const totals = data.last?.totals;
  const filtered = Boolean(dq || itemId || locationId || kind || nettable);

  return (
    <div className="col gap-lg">
      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 240px" }}>
          <label htmlFor="bal-q">Search</label>
          <input id="bal-q" className="input" type="search" placeholder="Part number, description or lot" value={q} onChange={(e) => setQ(e.target.value)} data-testid="balances-search" />
        </div>
        <div style={{ minWidth: 220 }}>
          <LocationSelect label="Location" value={locationId} onChange={(v) => set("location", v)} allowEmpty emptyLabel="All locations" includeInactive testId="balances-location" />
        </div>
        <div className="field">
          <label htmlFor="bal-kind">Kind</label>
          <select id="bal-kind" className="select" value={kind} onChange={(e) => set("kind", e.target.value)} data-testid="balances-kind">
            <option value="">All kinds</option>
            {(Object.keys(LOCATION_KIND_LABEL) as LocationKind[]).map((k) => (
              <option key={k} value={k}>
                {LOCATION_KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="bal-net">Plannable</label>
          <select id="bal-net" className="select" value={nettable} onChange={(e) => set("nettable", e.target.value)}>
            <option value="">Any</option>
            <option value="true">Counted by MRP</option>
            <option value="false">Not counted</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="bal-sort">Sort by</label>
          <select id="bal-sort" className="select" value={sort} onChange={(e) => set("sort", e.target.value === "part_number" ? "" : e.target.value)}>
            <option value="part_number">Part number</option>
            <option value="location">Location</option>
            <option value="-qty">Largest quantity</option>
          </select>
        </div>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={showZero} onChange={(e) => set("zero", e.target.checked ? "1" : "")} /> Show empty balances
        </label>
      </div>

      {itemId ? (
        <div className="card card-body row wrap between" data-testid="balances-item-filter">
          <div className="row wrap">
            <span className="muted small">Item</span>
            <Link to={mfgPaths.itemStock(itemId)} className="mono">
              {item?.part_number ?? itemId}
            </Link>
            <span className="muted small">{item?.description}</span>
            <button type="button" className="btn sm ghost" onClick={() => set("item", "")}>
              <Icon name="x" /> Show all items
            </button>
          </div>
          {totals ? (
            <div className="mfg-totals" data-testid="balances-totals">
              <div>
                <span className="mfg-total-label">On hand</span>
                <span className="mfg-total-value">{fmtNum(totals.qty_on_hand)}</span>
              </div>
              <div>
                <span className="mfg-total-label">Reserved</span>
                <span className="mfg-total-value">{fmtNum(totals.qty_reserved)}</span>
              </div>
              <div>
                <span className="mfg-total-label">Value</span>
                <span className="mfg-total-value">{fmtMoney(totals.value, currency)}</span>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(b) => b.id}
        label="Stock balances"
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
              <span className="spinner" aria-hidden /> Loading stock…
            </span>
          ) : filtered ? (
            "No stock matches these filters."
          ) : (
            <span>
              No stock yet. Post a receipt, <Link to={mfgPaths.importStart()}>import a stock list</Link> or{" "}
              <Link to={mfgPaths.home()}>load a sample</Link>.
            </span>
          )
        }
        footer={
          <span className="muted small" role="status" data-testid="balances-count">
            {data.loading && data.rows.length ? <span className="spinner" aria-hidden /> : null} Showing {data.rows.length.toLocaleString()} of{" "}
            {data.total.toLocaleString()} balances · Enter on a row opens its ledger
          </span>
        }
      />
    </div>
  );
}
