/** Plant material plan (M2 14.2 `RunItemsTab`, #154): every planned item in a virtual table (<= ~80 DOM rows). */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listRunItems } from "../../api/clientM2";
import type { MakeBuy } from "../../api/types";
import type { MrpItemRow, MrpItemSort } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { MakeBuyBadge } from "../../components/StatusChip";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { leadTimeText } from "../../lib/mrpText";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced } from "../../lib/useMfg";
import { useRun } from "./RunShell";

export function mrpItemColumns(runId: string): Column<MrpItemRow>[] {
  return [
    {
      key: "pn",
      header: "Part number",
      width: "minmax(150px, 1.2fr)",
      render: (r) => (
        <Link to={mfgPaths.runItem(runId, r.item.id)} className="mono mfg-ellipsis" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
          {r.item.part_number}
        </Link>
      ),
    },
    { key: "desc", header: "Description", width: "minmax(150px, 1.4fr)", render: (r) => <span className="mfg-ellipsis">{r.item.description}</span> },
    { key: "mb", header: "Make / buy", width: "100px", render: (r) => <MakeBuyBadge value={r.make_buy} /> },
    { key: "llc", header: "Level", width: "56px", align: "right", render: (r) => r.llc },
    { key: "oh", header: "On hand", width: "84px", align: "right", render: (r) => fmtNum(r.on_hand) },
    { key: "gross", header: "Needed", width: "84px", align: "right", render: (r) => fmtNum(r.gross_qty) },
    { key: "sup", header: "Open supply", width: "92px", align: "right", render: (r) => fmtNum(r.existing_supply_qty) },
    { key: "pl", header: "Planned", width: "92px", align: "right", render: (r) => (r.planned_count ? `${fmtNum(r.planned_qty)} (${r.planned_count})` : <span className="faint">0</span>) },
    {
      key: "short",
      header: "Short",
      width: "140px",
      render: (r) =>
        r.short_qty > 0 ? (
          <span className="badge danger" title={`Short ${fmtNum(r.short_qty)} from ${fmtDate(r.first_short_date)} before planned orders`}>
            <Icon name="alert" /> {fmtNum(r.short_qty)} from {fmtDate(r.first_short_date)}
          </span>
        ) : (
          <span className="faint">
            <Icon name="check" size={12} /> No
          </span>
        ),
    },
    { key: "late", header: "Late qty", width: "76px", align: "right", render: (r) => (r.late_qty ? <span className="mfg-neg">{fmtNum(r.late_qty)}</span> : "") },
    { key: "ex", header: "Messages", width: "80px", align: "right", render: (r) => (r.exception_count ? r.exception_count : "") },
    { key: "lt", header: "Lead time", width: "minmax(130px, 1fr)", render: (r) => <span className="mfg-ellipsis small" title={leadTimeText(r.lead_time)}>{`${r.lead_time.days} ${r.lead_time.unit === "working" ? "wd" : "d"}`}</span> },
  ];
}

export function RunItemsTab() {
  const { run } = useRun();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const makeBuy = (params.get("make_buy") ?? "") as MakeBuy | "";
  const shortOnly = params.get("short") === "1";
  const exOnly = params.get("ex") === "1";
  const plannedOnly = params.get("planned") === "1";
  const sort = (params.get("sort") ?? "llc") as MrpItemSort;
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps
  const data = usePaged<MrpItemRow>(
    (offset, limit, signal) =>
      listRunItems(run.id, { q: dq || undefined, make_buy: makeBuy || undefined, short_only: shortOnly || undefined, has_exceptions: exOnly || undefined, planned_only: plannedOnly || undefined, sort, limit, offset }, signal),
    [run.id, dq, makeBuy, shortOnly, exOnly, plannedOnly, sort],
  );
  const columns = useMemo(() => mrpItemColumns(run.id), [run.id]);
  return (
    <div className="col gap-lg">
      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 220px" }}>
          <label htmlFor="ri-q">Search</label>
          <input id="ri-q" className="input" type="search" placeholder="Part number or description" value={q} onChange={(e) => setQ(e.target.value)} data-testid="run-items-search" />
        </div>
        <div className="field">
          <label htmlFor="ri-mb">Make / buy</label>
          <select id="ri-mb" className="select" value={makeBuy} onChange={(e) => set("make_buy", e.target.value)}>
            <option value="">All</option>
            <option value="make">Make</option>
            <option value="buy">Buy</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="ri-sort">Sort by</label>
          <select id="ri-sort" className="select" value={sort} onChange={(e) => set("sort", e.target.value === "llc" ? "" : e.target.value)}>
            <option value="llc">BOM level</option>
            <option value="part_number">Part number</option>
            <option value="first_short_date">First short date</option>
            <option value="-short_qty">Largest shortage</option>
          </select>
        </div>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={shortOnly} onChange={(e) => set("short", e.target.checked ? "1" : "")} data-testid="run-items-short" /> Only short
        </label>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={plannedOnly} onChange={(e) => set("planned", e.target.checked ? "1" : "")} /> With planned orders
        </label>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={exOnly} onChange={(e) => set("ex", e.target.checked ? "1" : "")} /> With messages
        </label>
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(r) => r.item.id}
        label="Material plan"
        testId="run-items-table"
        totalCount={data.total}
        height="min(66vh, 720px)"
        rowExtras={(r) => ({ testId: "run-item-row", data: { item: r.item.part_number, short: r.short_qty > 0 } })}
        onRowClick={(r) => navigate(mfgPaths.runItem(run.id, r.item.id))}
        onActivate={(r) => navigate(mfgPaths.runItem(run.id, r.item.id))}
        onEndReached={data.onEndReached}
        empty={data.loading ? "Loading the plan…" : "No items match these filters."}
        footer={<span className="muted small">Showing {data.rows.length.toLocaleString()} of {data.total.toLocaleString()} items · "Short" is before planned orders</span>}
      />
    </div>
  );
}
