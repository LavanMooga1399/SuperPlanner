/**
 * `/mfg/shortages` (M2 14.2, #163): one page for the daily stand-up: late demand (latest live run), short parts,
 * overdue deliveries (live) and work-order component shortages (live kitting).
 */
import { useState } from "react";
import { Link } from "react-router";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { getShortages } from "../api/clientM2";
import { MfgError, Spinner } from "../components/Feedback";
import { OverdueBadge } from "../components/StatusM2";
import { VirtualTable } from "../components/VirtualTable";
import { fmtDate } from "../lib/format";
import { fmtNum } from "../lib/formatM2";
import { mfgPaths } from "../lib/paths";
import { useLoad } from "../lib/useMfg";
import { LimitingPath } from "./mrp/DemandProjectionTab";
import { ItemsShortTable } from "./workorders/KittingCheckPage";
import { plural, t } from "../../lib/i18n";
import { PageHeader } from "../../components/PageHeader";

export function ShortagesPage() {
  const [horizon, setHorizon] = useState(30);
  const d = useLoad((signal) => getShortages(horizon, signal), [horizon]);
  const s = d.data;
  const stale = s?.run && (typeof s.run.stale === "boolean" ? s.run.stale : s.run.stale.is_stale);
  return (
    <div className="col gap-lg" data-testid="shortages-page">
      <PageHeader
        title={t("mfg.shortagesPage.title.shortages")}
        description={t("mfg.shortagesPage.desc.whatWillBeLateWhich")}
        actions={
          <>
            <div className="field">
            <label htmlFor="sh-h">{t("mfg.shortagesPage.label.workOrdersStartingWithin")}</label>
            <select id="sh-h" className="select" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
              {[7, 14, 30, 60, 90].map((n) => (
                <option key={n} value={n}>
                  {plural(n, "day")}
                </option>
              ))}
            </select>
          </div>
          <button type="button" className="btn" onClick={d.reload} disabled={d.loading}>
            {d.loading ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />}{" "}{t("mfg.shortagesPage.text.refresh")}
          </button>
          </>
        }
      />
      <MfgError error={d.error} onRetry={d.reload} />
      {d.loading && !s ? <Spinner /> : null}
      {s ? (
        <>
          {s.run ? (
            <p className="small muted" style={{ margin: 0 }}>
              {t("mfg.shortagesPage.text.lateDemandAndShortParts")}{" "}<Link to={mfgPaths.run(s.run.id)}>{t("common.mrpRunNo", { n: s.run.run_no })}</Link>{" "}{t("mfg.shortagesPage.text.asOf", { asof: fmtDate(s.run.as_of) })}
              {stale ? (
                <span className="badge warn" style={{ marginLeft: 6 }}>
                  <Icon name="clock" /> {t("mfg.shortagesPage.btn.dataChangedSince")}
                </span>
              ) : null}
              {t("mfg.shortagesPage.text.deliveriesAndWorkOrdersAre")}
            </p>
          ) : (
            <Banner tone="info" title={t("mfg.shortagesPage.title.noMrpRunYet")}>
              {t("mfg.shortagesPage.text.lateDemandAndShortParts2")}{" "}<Link to={mfgPaths.mrp()}>{t("mfg.shortagesPage.text.mrpRun")}</Link>. Deliveries and work orders below are live.
            </Banner>
          )}
          <div className="kpis">
            {(
              [
                ["late_demand", t("mfg.shortagesPage.str.lateDemandLines"), "demand"],
                ["short_items", t("mfg.shortagesPage.str.partsShort"), "items"],
                ["overdue_schedules", t("mfg.shortagesPage.str.overdueDeliveries"), "supply"],
                ["wo_short", t("mfg.shortagesPage.str.partsMissingForWorkOrders"), "wo"],
              ] as const
            ).map(([k, label, panel]) => (
              <a key={k} href={`#panel-${panel}`} className="card kpi mfg-kpi" data-testid={`shortage-count-${panel}`}>
                <div className="kpi-label">{label}</div>
                <div className="kpi-value" style={s.counts[k] ? { color: "var(--danger)" } : undefined}>
                  {s.counts[k].toLocaleString("en-IN")}
                </div>
              </a>
            ))}
          </div>
          <section className="card" id="panel-demand" data-testid="shortage-panel-demand">
            <div className="card-header">
              <h3>{t("mfg.shortagesPage.head.lateDemand")}</h3>
              {s.run ? (
                <Link to={mfgPaths.runDemand(s.run.id)} className="small">
                  {t("mfg.shortagesPage.btn.allDemand")}
                </Link>
              ) : null}
            </div>
            <ul className="mfg-plain-list">
              {s.late_demand.length === 0 ? (
                <li className="issue muted">
                  <Icon name="check" /> {t("mfg.shortagesPage.btn.nothingLate")}
                </li>
              ) : null}
              {s.late_demand.map((x, i) => (
                <li key={x.demand_line_id ?? i} className="issue" data-testid="demand-line" data-late-days={x.late_days}>
                  <div className="grow col" style={{ gap: 2 }}>
                    <div className="row wrap" style={{ gap: 6 }}>
                      {x.link ? (
                        <Link to={x.link} className="mono">
                          {x.order ? `${x.order.number}/${x.line_no}` : "What-if"}
                        </Link>
                      ) : null}
                      <span>
                        {fmtNum(x.qty)} x <span className="mono">{x.item.part_number}</span>
                      </span>
                      <span className="badge danger">
                        <Icon name="alert" /> {x.late_days} d late
                      </span>
                      <span className="small muted">
                        {t("mfg.shortagesPage.text.dueProjected", { duedate: fmtDate(x.due_date), projecteddate: fmtDate(x.projected_date) })}
                      </span>
                    </div>
                    <LimitingPath steps={x.limiting} runId={s.run?.id} />
                  </div>
                </li>
              ))}
            </ul>
          </section>
          <div className="grid-2" style={{ alignItems: "start" }}>
            <section className="card card-table" id="panel-items" data-testid="shortage-panel-items">
              <div className="card-header">
                <h3>{t("mfg.shortagesPage.head.shortParts")}</h3>
                {s.run ? (
                  <Link to={`${mfgPaths.runItems(s.run.id)}?short=1`} className="small">
                    {t("mfg.shortagesPage.btn.all")}
                  </Link>
                ) : null}
              </div>
              <VirtualTable
                rows={s.short_items}
                columns={[
                  {
                    key: "part",
                    header: "Part",
                    width: "minmax(200px, 2fr)",
                    sortValue: (x) => x.item.part_number,
                    exportValue: (x) => x.item.part_number,
                    render: (x) => (
                      <span className="mfg-ellipsis">
                        <Link to={x.link} className="mono">
                          {x.item.part_number}
                        </Link>{" "}
                        <span className="faint small">{x.item.description}</span>
                      </span>
                    ),
                  },
                  { key: "short", header: "Short", width: "120px", align: "right", sortValue: (x) => x.short_qty, render: (x) => <span className="mfg-neg">{fmtNum(x.short_qty)} {x.uom}</span> },
                  { key: "from", header: "From", width: "110px", sortValue: (x) => x.first_short_date, render: (x) => fmtDate(x.first_short_date) },
                ]}
                rowKey={(x) => x.item.id}
                label={t("mfg.shortagesPage.label.shortParts")}
                tableId="shortages-short-parts"
                height="420px"
                exportName="short-parts"
                rowExtras={() => ({ testId: "short-item-row" })}
                empty={t("mfg.shortagesPage.empty.noPartsShortInThe")}
                card={{ title: "part", fields: ["short", "from"] }}
              />
            </section>
            <section className="card card-table" id="panel-supply" data-testid="shortage-panel-supply">
              <div className="card-header">
                <h3>{t("mfg.shortagesPage.head.overdueDeliveries")}</h3>
                <Link to={mfgPaths.deliveryBoard({ overdue: "1" })} className="small">
                  {t("mfg.shortagesPage.btn.deliverySchedule")}
                </Link>
              </div>
              <VirtualTable
                rows={s.overdue_supply}
                columns={[
                  {
                    key: "delivery",
                    header: "Delivery",
                    width: "minmax(180px, 2fr)",
                    sortValue: (x) => x.doc.number,
                    exportValue: (x) => `${x.doc.number} / ${x.line_no} / ${x.seq}`,
                    render: (x) => (
                      <span className="mfg-ellipsis">
                        <Link to={x.link} className="mono">
                          {x.doc.number} / {x.line_no} / {x.seq}
                        </Link>{" "}
                        <span className="faint small">{x.item.part_number}</span>
                      </span>
                    ),
                  },
                  { key: "supplier", header: "Supplier", width: "minmax(90px, 1fr)", sortValue: (x) => x.supplier?.code ?? "", render: (x) => x.supplier?.code ?? "" },
                  { key: "open", header: "Open", width: "90px", align: "right", sortValue: (x) => x.open_qty, render: (x) => fmtNum(x.open_qty) },
                  { key: "overdue", header: "Overdue", width: "110px", sortValue: (x) => x.overdue_days, exportValue: (x) => x.overdue_days, render: (x) => <OverdueBadge days={x.overdue_days} /> },
                ]}
                rowKey={(x) => x.schedule_id}
                label={t("mfg.shortagesPage.label.overdueDeliveries")}
                tableId="shortages-overdue"
                height="420px"
                exportName="overdue-deliveries"
                rowExtras={() => ({ testId: "overdue-row" })}
                empty={t("mfg.shortagesPage.empty.noOverdueDeliveries")}
                card={{ title: "delivery", status: "overdue", fields: ["supplier", "open"] }}
              />
            </section>
          </div>
          <div id="panel-wo">
            <ItemsShortTable rows={s.wo_shortages} testId="shortage-panel-wo" title={t("mfg.shortagesPage.attr.partsMissingForWorkOrders")} />
          </div>
        </>
      ) : null}
    </div>
  );
}
