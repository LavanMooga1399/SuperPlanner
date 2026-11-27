/**
 * `/mfg/trade/reports/:reportId` (M9 8.3, 10): tariff-milestone report - per milestone a status chip per family (or
 * item) and month (met / at risk / missed, text + icon; projected months in a hatched band, the first missed month
 * called out), the lots below the minimum with a drill-down into a lot's input tree, xlsx export and a print view.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { plural, t } from "../../lib/i18n";
import { formatDateRange, formatNumber } from "../../lib/locale";
import { saveBlob } from "../api/client";
import { downloadTradeReport, getNetLotContent, getTradeReport } from "../api/clientM9";
import type { TradeReportCell, TradeReportLot, TradeReportMilestone } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { usePolling } from "../lib/usePolling";
import { useLoad } from "../lib/useMfg";
import { isRunning, JobChip, monthLabel, monthShort, NodeTag, num, pct100, useNodes } from "../network/shared";
import { LotContentPanel } from "./TradeBits";

type Nodes = ReturnType<typeof useNodes>;

export function TradeReportPage() {
  const { reportId = "" } = useParams();
  const rep = useLoad((s) => getTradeReport(reportId, s), [reportId]);
  const r = rep.data;
  const nodes = useNodes();
  usePolling(rep.reload, isRunning(r?.status));
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (r) document.title = `${r.number} - ${t("net.trd.title")}`;
  }, [r]);
  if (rep.error && !r) return <MfgError error={rep.error} onRetry={rep.reload} />;
  if (!r) return <Spinner />;
  const res = r.result;
  return (
    <div className="col gap-lg" data-testid="trade-report" data-status={r.status}>
      <div className="mfg-breadcrumb small muted">
        <Link to={mfgPaths.trade("reports")}>{t("net.trd.title")}</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{r.number}</span>
      </div>
      <PageHeader
        title={t("net.trd.rep.title", { n: r.number })}
        meta={<JobChip s={r.status} />}
        facts={[
          [t("net.trd.rep.range"), formatDateRange(r.params.from, r.params.to)],
          [t("net.trd.rep.projectionFrom"), res?.projection_from ? monthLabel(res.projection_from) : "–"],
          [t("net.trd.rep.projection"), res?.projection_source ?? "–"],
        ]}
        actions={
          <>
            <button type="button" className="btn" onClick={() => window.print()}>
              <Icon name="file" /> {t("net.trd.rep.print")}
            </button>
            <button type="button" className="btn primary" disabled={r.status !== "completed"} onClick={() => downloadTradeReport(r.id).then(saveBlob, setErr)} data-testid="trd-rep-xlsx">
              <Icon name="download" /> {t("net.trd.rep.xlsx")}
            </button>
          </>
        }
      />
      <MfgError error={err} />
      {isRunning(r.status) ? (
        <Banner tone="accent" icon="loader" role="status">
          {t("net.trd.rep.running")}
        </Banner>
      ) : null}
      {r.status === "failed" ? <Banner tone="danger" title={t("net.trd.rep.failed")}>{r.error ?? ""}</Banner> : null}
      {res
        ? res.milestones.map((m) => <MilestoneSection key={m.milestone_id} m={m} months={res.months} projFrom={res.projection_from} nodes={nodes} />)
        : null}
    </div>
  );
}

function Cell({ c }: { c: TradeReportCell | undefined }) {
  if (!c || c.share_pct === null) return <span className="muted">–</span>;
  const icon = c.status === "met" ? "check" : c.status === "at_risk" ? "alert" : c.status === "missed" ? "x" : null;
  const tone = c.status === "met" ? "ok" : c.status === "at_risk" ? "warn" : c.status === "missed" ? "danger" : "";
  const title = [c.status ? t(`net.trd.status.${c.status}` as const) : t("net.trd.rep.beforeEffective"), c.projected ? t("net.trd.rep.projected") : t("net.trd.rep.lotsTpl", { n: c.lots, b: c.lots_below }), c.estimated_pct ? t("net.trd.rep.estTpl", { v: formatNumber(c.estimated_pct, 0) }) : ""].filter(Boolean).join(" · ");
  return (
    <span className={`trd-cell${c.projected ? " trd-proj" : ""}${tone ? ` badge ${tone}` : ""}`} title={title} data-status={c.status ?? "none"}>
      {icon ? <Icon name={icon} size={12} /> : null}
      {formatNumber(c.share_pct, 0)}
      <span className="sr-only"> {title}</span>
    </span>
  );
}

function MilestoneSection({ m, months, projFrom, nodes }: { m: TradeReportMilestone; months: string[]; projFrom: string | null; nodes: Nodes }) {
  const [lot, setLot] = useState<TradeReportLot | null>(null);
  const columns = useMemo<Column<TradeReportLot>[]>(
    () => [
      { key: "plant", header: t("net.label.node"), width: "100px", render: (l) => <NodeTag node={nodes.byId.get(l.plant_owner_id)} id={l.plant_owner_id} /> },
      { key: "lot", header: t("net.trd.rep.lot"), width: "150px", sortValue: (l) => l.lot_code, render: (l) => <span className="mono">{l.lot_code}</span> },
      { key: "key", header: t("net.label.key"), width: "140px", sortValue: (l) => l.item_key, render: (l) => <span className="mono">{l.item_key}</span> },
      { key: "month", header: t("net.label.month"), width: "110px", sortValue: (l) => l.month, render: (l) => monthLabel(l.month) },
      { key: "qty", header: t("net.label.qty"), width: "100px", align: "right", sortValue: (l) => l.qty, render: (l) => <span className="pl-num">{num(l.qty)}</span> },
      { key: "share", header: t("net.trd.rep.share"), width: "120px", align: "right", sortValue: (l) => l.share_pct ?? -1, render: (l) => <span className="pl-num">{pct100(l.share_pct)}{l.estimated ? <span className="badge warn" style={{ marginLeft: 4 }}><Icon name="info" /> {t("net.lc.est")}</span> : null}</span> },
      { key: "open", header: <span className="sr-only">{t("net.lc.inputs")}</span>, label: t("net.lc.inputs"), width: "110px", render: (l) => <button type="button" className="btn ghost sm" onClick={(e) => (e.stopPropagation(), setLot(l))} data-testid="trd-lot-open"><Icon name="layers" /> {t("net.lc.inputs")}</button> },
    ],
    [nodes],
  );
  return (
    <section className="card col pl-gap" aria-labelledby={`ms-${m.milestone_id}`} data-testid="trd-ms-section">
      <div className="pl-card-header">
        <h2 className="pl-h2" id={`ms-${m.milestone_id}`}>
          <span className="mono">{m.code}</span> {m.name}
        </h2>
        <span className="small muted">{t("net.trd.rep.msFacts", { min: formatNumber(m.min_pct, 1), b: m.basis === "value" ? t("net.trd.ms.value") : t("net.trd.ms.weight"), d: monthLabel(m.effective) })}</span>
      </div>
      {m.first_missed_month ? (
        <Banner tone="danger" title={t("net.trd.rep.firstMissed", { m: monthLabel(m.first_missed_month) })} testId="trd-first-missed">
          {t("net.trd.rep.firstMissedBody")}
        </Banner>
      ) : (
        <p className="pl-note ok" style={{ margin: 0 }}>
          <Icon name="check" size={14} /> {t("net.trd.rep.allMet")}
        </p>
      )}
      <div className="pl-pivot-wrap">
        <table className="pl-pivot" aria-label={t("net.trd.rep.gridAria", { m: m.code })} data-testid="trd-grid">
          <thead>
            <tr>
              <th scope="col">{t("net.trd.rep.group")}</th>
              {months.map((mo) => (
                <th key={mo} scope="col" className={projFrom && mo >= projFrom ? "trd-proj-band" : undefined} style={m.first_missed_month === mo ? { color: "var(--danger)" } : undefined}>
                  {monthShort(mo)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {m.groups.map((g) => {
              const by = new Map(g.cells.map((c) => [c.month, c]));
              return (
                <tr key={g.key}>
                  <th scope="row">
                    <span className="mono">{g.key}</span> <span className="muted small">{g.label}</span>
                  </th>
                  {months.map((mo) => (
                    <td key={mo} className={projFrom && mo >= projFrom ? "trd-proj-band" : undefined}>
                      <Cell c={by.get(mo)} />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        {t("net.trd.rep.legend")}
      </p>
      <h3 className="pl-h2">{t("net.trd.rep.below", { n: plural(m.lots_below.length, t("noun.lot"), t("noun.lots")) })}</h3>
      <div className="card-table">
        <DataTable<TradeReportLot> rows={m.lots_below} columns={columns} rowKey={(l) => l.lot_id} label={t("net.trd.rep.below", { n: m.lots_below.length })} testId="trd-lots-below" exportName={`lots-below-${m.code}`} empty={t("net.trd.rep.noneBelow")} />
      </div>
      {lot ? (
        <Dialog title={t("net.trd.rep.lotTitle", { l: lot.lot_code })} wide onClose={() => setLot(null)}>
          <LotContentPanel lotId={lot.lot_id} load={(s) => getNetLotContent(lot.plant_owner_id, lot.lot_id, m.milestone_id, s)} />
        </Dialog>
      ) : null}
    </section>
  );
}
