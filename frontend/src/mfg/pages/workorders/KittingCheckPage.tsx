/**
 * `/mfg/work-orders/kitting` (M2 14.2, 7.4 #147): simulate kitting of the work orders starting soon, in priority
 * or start-date order (each takes free stock in turn), and the plant-wide component shortage list.
 */
import { useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../../components/Icon";
import { kittingCheck } from "../../api/clientM2";
import type { ItemShort, KittingCheckRequest } from "../../api/typesM2";
import { MfgError, Spinner } from "../../components/Feedback";
import { WoStatusChip } from "../../components/StatusM2";
import { DataTable } from "../../components/DataTable";
import { fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { useLoad } from "../../lib/useMfg";
import { PageHeader } from "../../../components/PageHeader";
import { FilterBar } from "../../../components/FilterBar";
import { t } from "../../../lib/i18n";

export function KittingCheckPage() {
  const [order, setOrder] = useState<KittingCheckRequest["order"]>("priority");
  const [horizon, setHorizon] = useState("14");
  const h = Number(horizon);
  const valid = Number.isInteger(h) && h >= 0 && h <= 365;
  const res = useLoad((signal) => (valid ? kittingCheck({ wo_ids: null, order, horizon_days: h }, signal) : null), [order, h, valid]);
  const r = res.data;
  return (
    <div className="col gap-lg">
      <nav aria-label={t("mfg.kittingCheckPage.aria.breadcrumb")} className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.workOrders()}>Work orders</Link> <Icon name="chevron-right" size={12} /> <span>Kitting check</span>
      </nav>
      <PageHeader
        title={t("mfg.kittingCheckPage.title.kittingCheck")}
        description={t("mfg.kittingCheckPage.desc.whichReleasedAndSoonstartingWork")} />
      <FilterBar>
        <div className="field">
          <label htmlFor="kc-order">{t("mfg.kittingCheckPage.label.whoGetsStockFirst")}</label>
          <select id="kc-order" className="select" value={order} onChange={(e) => setOrder(e.target.value as KittingCheckRequest["order"])} data-testid="kitting-order">
            <option value="priority">Highest priority first</option>
            <option value="start_date">Earliest start first</option>
          </select>
        </div>
        <div className="field" style={{ width: 160 }}>
          <label htmlFor="kc-h">{t("mfg.kittingCheckPage.label.plannedOrdersStartingWithinDays")}</label>
          <input id="kc-h" className="input" type="number" min={0} max={365} value={horizon} aria-invalid={!valid} onChange={(e) => setHorizon(e.target.value)} />
        </div>
        <button type="button" className="btn" style={{ alignSelf: "flex-end" }} onClick={res.reload} disabled={res.loading}>
          {res.loading ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />} Check again
        </button>
      </FilterBar>
      <MfgError error={res.error} onRetry={res.reload} />
      {res.loading && !r ? <Spinner label={t("mfg.kittingCheckPage.label.checkingKits")} /> : null}
      {r ? (
        <div className="grid-2" style={{ alignItems: "start" }}>
          <section className="card card-table" data-testid="kitting-check-rows">
            <div className="card-header">
              <h3>Work orders ({r.rows.length})</h3>
              <span className="muted small">{r.rows.filter((x) => x.kit_complete).length} complete</span>
            </div>
            <DataTable
              rows={r.rows}
              columns={[
                {
                  key: "wo",
                  header: "Work order",
                  width: "minmax(190px, 1.6fr)",
                  sortValue: (x) => x.wo.number,
                  exportValue: (x) => x.wo.number,
                  render: (x) => (
                    <span className="mfg-ellipsis">
                      <Link to={mfgPaths.workOrder(x.wo.id)} className="mono">
                        {x.wo.number}
                      </Link>{" "}
                      {x.wo.item ? <span className="muted small">{x.wo.item.part_number}</span> : null}
                    </span>
                  ),
                },
                { key: "status", header: "Status", width: "110px", sortValue: (x) => x.status, exportValue: (x) => x.status, render: (x) => <WoStatusChip status={x.status} /> },
                { key: "start", header: "Start", width: "100px", sortValue: (x) => x.start_date, render: (x) => fmtDate(x.start_date) },
                { key: "prio", header: "Prio.", width: "56px", sortValue: (x) => x.priority, render: (x) => `P${x.priority}` },
                {
                  key: "kit",
                  header: "Kit",
                  width: "100px",
                  sortValue: (x) => x.short_components,
                  exportValue: (x) => (x.kit_complete ? "Complete" : `${x.short_components} short`),
                  render: (x) =>
                    x.kit_complete ? (
                      <span className="badge ok">
                        <Icon name="check" /> {t("mfg.kittingCheckPage.btn.complete")}
                      </span>
                    ) : (
                      <span className="badge danger">
                        <Icon name="alert" /> {x.short_components} short
                      </span>
                    ),
                },
                {
                  key: "missing",
                  header: "Missing",
                  width: "minmax(150px, 1.2fr)",
                  wrap: true,
                  exportValue: (x) => x.shortages.map((s) => `${s.item.part_number} -${s.shortage}`).join("; "),
                  render: (x) => (
                    <span className="small">
                      {x.shortages.slice(0, 3).map((s, i) => (
                        <span key={s.item.id}>
                          {i ? ", " : ""}
                          <span className="mono">{s.item.part_number}</span> −{fmtNum(s.shortage)}
                        </span>
                      ))}
                      {x.shortages.length > 3 ? <span className="faint"> +{x.shortages.length - 3} more</span> : null}
                    </span>
                  ),
                },
              ]}
              rowKey={(x) => x.wo.id}
              label={t("mfg.kittingCheckPage.label.workOrdersToKit")}
              tableId="kitting-check-wos"
              exportName="kitting-check"
              rowExtras={(x) => ({ testId: "kitting-row", data: { shortage: x.short_components, wo: x.wo.number } })}
              empty={t("mfg.kittingCheckPage.empty.noWorkOrdersInRange")}
              card={{ title: "wo", status: "kit", fields: ["start", "prio", "missing"] }}
            />
          </section>
          <ItemsShortTable rows={r.items_short} />
        </div>
      ) : null}
    </div>
  );
}

export function ItemsShortTable({ rows, testId = "kitting-items-short", title = "Component shortage list" }: { rows: ItemShort[]; testId?: string; title?: string }) {
  return (
    <section className="card card-table" data-testid={testId}>
      <div className="card-header">
        <h3>
          {title} ({rows.length})
        </h3>
      </div>
      <DataTable
        rows={rows}
        columns={[
          {
            key: "part",
            header: "Part",
            width: "minmax(180px, 2fr)",
            sortValue: (s) => s.item.part_number,
            exportValue: (s) => s.item.part_number,
            render: (s) => (
              <span className="mfg-ellipsis">
                <Link to={mfgPaths.itemStock(s.item.id)} className="mono">
                  {s.item.part_number}
                </Link>{" "}
                <span className="faint small">{s.item.description}</span>
              </span>
            ),
          },
          { key: "missing", header: "Missing", width: "110px", align: "right", sortValue: (s) => s.total_shortage, render: (s) => <span className="mfg-neg">{fmtNum(s.total_shortage)} {s.item.uom}</span> },
          { key: "wos", header: "WOs", width: "64px", align: "right", sortValue: (s) => s.wo_count, render: (s) => s.wo_count },
          { key: "first", header: "First needed", width: "110px", sortValue: (s) => s.first_start_date, render: (s) => fmtDate(s.first_start_date) },
          {
            key: "supply",
            header: "Next supply",
            width: "minmax(170px, 1.5fr)",
            sortValue: (s) => s.next_supply?.date ?? null,
            exportValue: (s) => (s.next_supply ? `${s.next_supply.qty} on ${s.next_supply.date} (${s.next_supply.label})` : "No open supply"),
            render: (s) =>
              s.next_supply ? (
                <Link to={s.next_supply.link} className="mfg-ellipsis">
                  {fmtNum(s.next_supply.qty)} on {fmtDate(s.next_supply.date)} ({s.next_supply.label})
                </Link>
              ) : (
                <span className="badge danger">
                  <Icon name="x" /> {t("mfg.kittingCheckPage.btn.noOpenSupply")}
                </span>
              ),
          },
        ]}
        rowKey={(s) => s.item.id}
        label={title}
        tableId={`${testId}-table`}
        exportName="component-shortages"
        rowExtras={(s) => ({ testId: "item-short-row", data: { item: s.item.part_number } })}
        empty={t("mfg.kittingCheckPage.empty.nothingMissing")}
        card={{ title: "part", fields: ["missing", "first", "supply"] }}
      />
    </section>
  );
}
