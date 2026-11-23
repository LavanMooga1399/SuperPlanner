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
import { FilterBar } from "../../../components/FilterBar";
import { t } from "../../../lib/i18n";

export function mrpItemColumns(runId: string): Column<MrpItemRow>[] {
  return [
    {
      key: "pn",
      header: t("mfg.runItemsTab.str.partNumber"),
      width: "minmax(150px, 1.2fr)",
      render: (r) => (
        <Link to={mfgPaths.runItem(runId, r.item.id)} className="mono mfg-ellipsis" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
          {r.item.part_number}
        </Link>
      ),
    },
    { key: "desc", header: t("mfg.runItemsTab.str.description"), width: "minmax(150px, 1.4fr)", render: (r) => <span className="mfg-ellipsis">{r.item.description}</span> },
    { key: "mb", header: t("mfg.runItemsTab.str.makeBuy"), width: "100px", render: (r) => <MakeBuyBadge value={r.make_buy} /> },
    { key: "llc", header: t("mfg.runItemsTab.str.level"), width: "56px", align: "right", render: (r) => r.llc },
    { key: "oh", header: t("mfg.runItemsTab.str.onHand"), width: "84px", align: "right", render: (r) => fmtNum(r.on_hand) },
    { key: "gross", header: t("mfg.runItemsTab.str.needed"), width: "84px", align: "right", render: (r) => fmtNum(r.gross_qty) },
    { key: "sup", header: t("mfg.runItemsTab.str.openSupply"), width: "92px", align: "right", render: (r) => fmtNum(r.existing_supply_qty) },
    { key: "pl", header: t("mfg.runItemsTab.str.planned"), width: "92px", align: "right", render: (r) => (r.planned_count ? `${fmtNum(r.planned_qty)} (${r.planned_count})` : <span className="faint">0</span>) },
    {
      key: "short",
      header: t("mfg.runItemsTab.str.short"),
      width: "140px",
      render: (r) =>
        r.short_qty > 0 ? (
          <span className="badge danger" title={t("mfg.runItemsTab.tpl.shortFromBeforePlannedOrders", { shortqty: fmtNum(r.short_qty), firstshortdate: fmtDate(r.first_short_date) })}>
            <Icon name="alert" />{" "}{t("mfg.runItemsTab.text.from", { shortqty: fmtNum(r.short_qty), firstshortdate: fmtDate(r.first_short_date) })}
          </span>
        ) : (
          <span className="faint">
            <Icon name="check" size={12} /> {t("mfg.runItemsTab.btn.no")}
          </span>
        ),
    },
    { key: "late", header: t("mfg.runItemsTab.str.lateQty"), width: "76px", align: "right", render: (r) => (r.late_qty ? <span className="mfg-neg">{fmtNum(r.late_qty)}</span> : "") },
    { key: "ex", header: t("mfg.runItemsTab.str.messages"), width: "80px", align: "right", render: (r) => (r.exception_count ? r.exception_count : "") },
    { key: "lt", header: t("mfg.runItemsTab.str.leadTime"), width: "minmax(130px, 1fr)", render: (r) => <span className="mfg-ellipsis small" title={leadTimeText(r.lead_time)}>{`${r.lead_time.days} ${r.lead_time.unit === "working" ? "wd" : "d"}`}</span> },
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
      <FilterBar search={{ id: "ri-q", value: q, onChange: setQ, placeholder: "Part number or description", testId: "run-items-search" }} pageKey="RunItemsTab">
        <div className="field">
          <label htmlFor="ri-mb">{t("mfg.runItemsTab.label.makeBuy")}</label>
          <select id="ri-mb" className="select" value={makeBuy} onChange={(e) => set("make_buy", e.target.value)}>
            <option value="">{t("mfg.runItemsTab.text.all")}</option>
            <option value="make">{t("mfg.runItemsTab.text.make")}</option>
            <option value="buy">{t("mfg.runItemsTab.text.buy")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="ri-sort">{t("mfg.runItemsTab.label.sortBy")}</label>
          <select id="ri-sort" className="select" value={sort} onChange={(e) => set("sort", e.target.value === "llc" ? "" : e.target.value)}>
            <option value="llc">{t("mfg.runItemsTab.text.bomLevel")}</option>
            <option value="part_number">{t("mfg.runItemsTab.text.partNumber")}</option>
            <option value="first_short_date">{t("mfg.runItemsTab.text.firstShortDate")}</option>
            <option value="-short_qty">{t("mfg.runItemsTab.text.largestShortage")}</option>
          </select>
        </div>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={shortOnly} onChange={(e) => set("short", e.target.checked ? "1" : "")} data-testid="run-items-short" />{" "}{t("mfg.runItemsTab.text.onlyShort")}
        </label>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={plannedOnly} onChange={(e) => set("planned", e.target.checked ? "1" : "")} />{" "}{t("mfg.runItemsTab.text.withPlannedOrders")}
        </label>
        <label className="checkbox" style={{ alignSelf: "flex-end", paddingBottom: 6 }}>
          <input type="checkbox" checked={exOnly} onChange={(e) => set("ex", e.target.checked ? "1" : "")} />{" "}{t("mfg.runItemsTab.text.withMessages")}
        </label>
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        card={{ title: "pn", fields: ["gross", "short", "late"] }}
        rows={data.rows}
        columns={columns}
        rowKey={(r) => r.item.id}
        label={t("mfg.runItemsTab.label.materialPlan")}
        testId="run-items-table"
        totalCount={data.total}
        height="min(66vh, 720px)"
        rowExtras={(r) => ({ testId: "run-item-row", data: { item: r.item.part_number, short: r.short_qty > 0 } })}
        onRowClick={(r) => navigate(mfgPaths.runItem(run.id, r.item.id))}
        onActivate={(r) => navigate(mfgPaths.runItem(run.id, r.item.id))}
        onEndReached={data.onEndReached}
        empty={data.loading ? t("mfg.runItemsTab.str.loadingThePlan") : t("mfg.runItemsTab.str.noItemsMatchTheseFilters")}
        footer={<span className="muted small">{t("mfg.runItemsTab.text.showingItemsShortIsBefore", { t: t("common.nOfM", { n: data.rows.length.toLocaleString("en-IN"), m: data.total.toLocaleString("en-IN") }) })}</span>}
      />
    </div>
  );
}
