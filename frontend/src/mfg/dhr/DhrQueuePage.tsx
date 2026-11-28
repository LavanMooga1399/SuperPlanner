/**
 * `/mfg/dhr` (M10 4, 11): device history records. "Review queue" (default, D10): records waiting for review, oldest
 * first, with open major / minor exceptions, waiting time, item, lot, lines and the "changed after release" flag, and
 * a summary by waiting time. "All records" (D1): every version with status and date filters. "Assemble record" builds
 * (or rebuilds) the record of a lot or work order on demand.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { t } from "../../lib/i18n";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { assembleDhr, getReviewQueue, listDhr } from "../api/clientM10";
import type { DhrSummary, ReviewQueueRow } from "../api/typesM10";
import { DataTable } from "../components/DataTable";
import { MfgError } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { ItemCell, itemText, usePersonName } from "../qa/common";
import { QaWorklist } from "../qa/Worklist";
import { KpiCard, Segmented } from "../network/shared";
import { AgeDays, chipText, DHR_STATUS, DhrStatusChip, OpenCounts, qaItem } from "./shared";
import { LotPicker, WoPicker, type LotRef } from "./pickers";

type Tab = "queue" | "all";

export function DhrQueuePage() {
  const canReview = useCan("dhr_review");
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "all" ? "all" : "queue";
  const [assemble, setAssemble] = useState(false);
  useEffect(() => {
    document.title = t("gxp.dhr.title");
  }, []);
  const action = (
    <button type="button" className="btn primary" disabled={!canReview} title={canReview ? undefined : needsText("dhr_review")} onClick={() => setAssemble(true)} data-testid="dhr-assemble">
      <Icon name="layers" /> {t("gxp.dhr.btn.assemble")}
    </button>
  );
  const tabs = <Segmented<Tab> value={tab} onChange={(v) => setParams(v === "all" ? { tab: "all" } : {})} label={t("gxp.dhr.aria.tabs")} options={[{ value: "queue", label: t("gxp.dhr.tab.queue") }, { value: "all", label: t("gxp.dhr.tab.all") }]} testId="dhr-tabs" />;
  return (
    <>
      {tab === "queue" ? <QueueView action={action} tabs={tabs} /> : <AllView action={action} tabs={tabs} />}
      {assemble ? <AssembleDialog onClose={() => setAssemble(false)} /> : null}
    </>
  );
}

function QueueView({ action, tabs }: { action: React.ReactNode; tabs: React.ReactNode }) {
  const navigate = useNavigate();
  const person = usePersonName();
  const queue = useLoad((s) => getReviewQueue(s), []);
  const rows = queue.data?.items ?? [];
  const buckets = useMemo(() => {
    const b = { lt1d: 0, d1to3: 0, d3to7: 0, gt7d: 0 };
    for (const r of rows) {
      const d = r.oldest_exception_age_days ?? r.age_days;
      if (d < 1) b.lt1d++;
      else if (d < 3) b.d1to3++;
      else if (d < 7) b.d3to7++;
      else b.gt7d++;
    }
    return b;
  }, [rows]);
  const columns = useMemo<Column<ReviewQueueRow>[]>(
    () => [
      {
        key: "number",
        header: t("gxp.dhr.head.record"),
        width: "150px",
        sortValue: (r) => r.number,
        exportValue: (r) => `${r.number} v${r.version}`,
        render: (r) => (
          <Link to={mfgPaths.dhrRecord(r.id)} className="mono" onClick={(e) => e.stopPropagation()}>
            {r.number} <span className="muted">{t("gxp.tpl.version", { n: r.version })}</span>
          </Link>
        ),
      },
      {
        key: "status",
        header: t("gxp.head.status"),
        width: "210px",
        exportValue: (r) => chipText(DHR_STATUS, r.status),
        render: (r) => (
          <span className="row" style={{ gap: 4 }}>
            <DhrStatusChip s={r.status} />
            {r.changed_after_release ? (
              <span className="badge warn" title={t("gxp.dhr.changedAfterReleaseHelp")} data-testid="dhr-changed">
                <Icon name="refresh" /> {t("gxp.dhr.changed")}
              </span>
            ) : null}
          </span>
        ),
      },
      { key: "open", header: t("gxp.dhr.head.open"), width: "190px", sortValue: (r) => r.open_major * 1000 + r.open_minor, exportValue: (r) => `${r.open_major}/${r.open_minor}`, render: (r) => <OpenCounts major={r.open_major} minor={r.open_minor} testId="dhr-open" /> },
      { key: "age", header: t("gxp.dhr.head.age"), width: "140px", sortValue: (r) => r.oldest_exception_age_days, exportValue: (r) => r.oldest_exception_age_days, render: (r) => <AgeDays days={r.oldest_exception_age_days || r.age_days} /> },
      { key: "item", header: t("gxp.head.item"), width: "minmax(180px, 1.5fr)", sortValue: (r) => r.item.part_number ?? "", exportValue: (r) => itemText(qaItem(r.item)), render: (r) => <ItemCell item={qaItem(r.item)} id={r.item.id} /> },
      { key: "lot", header: t("gxp.head.lot"), width: "120px", sortValue: (r) => r.lot_code ?? "", render: (r) => (r.lot_code ? <span className="mono">{r.lot_code}</span> : <span className="faint">–</span>) },
      { key: "line", header: t("gxp.head.line"), width: "110px", drop: 1, exportValue: (r) => r.line_codes.join(" "), render: (r) => (r.line_codes.length ? r.line_codes.join(", ") : <span className="faint">–</span>) },
      { key: "owner", header: t("gxp.dhr.head.owner"), width: "150px", drop: 2, exportValue: (r) => r.reviewer_ids.map(person).join(", "), render: (r) => (r.reviewer_ids.length ? r.reviewer_ids.map(person).join(", ") : <span className="faint">–</span>) },
    ],
    [person],
  );
  return (
    <div className="col gap-lg" data-testid="dhr-queue-page">
      <PageHeader title={t("gxp.dhr.title")} description={t("gxp.dhr.desc")} actions={action} />
      {tabs}
      <div className="gxp-kpis" data-testid="dhr-queue-summary">
        <KpiCard label={t("gxp.dhr.kpi.awaiting")} value={formatNumber(rows.length)} testId="dhr-kpi-awaiting" />
        {(["lt1d", "d1to3", "d3to7", "gt7d"] as const).map((b) => (
          <KpiCard key={b} label={t(`gxp.dhr.bucket.${b}`)} value={formatNumber(buckets[b])} />
        ))}
        <KpiCard label={t("gxp.dhr.kpi.changed")} value={formatNumber(rows.filter((r) => r.changed_after_release).length)} />
      </div>
      <MfgError error={queue.error} onRetry={queue.reload} />
      <section className="card card-table">
        <DataTable<ReviewQueueRow>
          rows={rows}
          columns={columns}
          rowKey={(r) => r.id}
          label={t("gxp.dhr.tab.queue")}
          testId="dhr-queue-table"
          exportName="dhr-review-queue"
          loading={queue.loading && !queue.data}
          rowExtras={(r) => ({ testId: "dhr-row", data: { status: r.status, number: r.number } })}
          onRowClick={(r) => navigate(mfgPaths.dhrRecord(r.id))}
          onActivate={(r) => navigate(mfgPaths.dhrRecord(r.id))}
          empty={t("gxp.dhr.queueEmpty")}
        />
      </section>
    </div>
  );
}

function AllView({ action, tabs }: { action: React.ReactNode; tabs: React.ReactNode }) {
  const columns = useMemo<Column<DhrSummary>[]>(
    () => [
      {
        key: "number",
        header: t("gxp.dhr.head.record"),
        width: "150px",
        exportValue: (r) => `${r.number} v${r.version}`,
        render: (r) => (
          <Link to={mfgPaths.dhrRecord(r.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {r.number} <span className="muted">{t("gxp.tpl.version", { n: r.version })}</span>
          </Link>
        ),
      },
      {
        key: "status",
        header: t("gxp.head.status"),
        width: "210px",
        exportValue: (r) => chipText(DHR_STATUS, r.status),
        render: (r) => (
          <span className="row" style={{ gap: 4 }}>
            <DhrStatusChip s={r.status} />
            {r.changed_after_release ? (
              <span className="badge warn" data-testid="dhr-changed">
                <Icon name="refresh" /> {t("gxp.dhr.changed")}
              </span>
            ) : null}
            {r.superseded_by_id ? <span className="badge info">{t("gxp.dhr.supersededShort")}</span> : null}
          </span>
        ),
      },
      {
        key: "open",
        header: t("gxp.dhr.head.openShort"),
        width: "150px",
        exportValue: (r) => r.counts.open,
        render: (r) =>
          r.counts.open ? (
            <span className="badge warn">
              <Icon name="flag" /> {t("gxp.tpl.openN", { n: r.counts.open })}
            </span>
          ) : (
            <span className="badge ok">
              <Icon name="check" /> {t("gxp.str.noneOpen")}
            </span>
          ),
      },
      { key: "exc", header: t("gxp.dhr.fact.exceptions"), width: "170px", drop: 2, exportValue: (r) => `${r.counts.major}/${r.counts.minor}/${r.counts.info}`, render: (r) => <span className="small">{t("gxp.tpl.excSummary", { major: r.counts.major, minor: r.counts.minor, info: r.counts.info })}</span> },
      { key: "item", header: t("gxp.head.item"), width: "minmax(180px, 1.5fr)", exportValue: (r) => itemText(qaItem(r.item)), render: (r) => <ItemCell item={qaItem(r.item)} id={r.item.id} /> },
      { key: "lot", header: t("gxp.head.lot"), width: "120px", render: (r) => (r.lot_code ? <span className="mono">{r.lot_code}</span> : <span className="faint">–</span>) },
      { key: "wos", header: t("gxp.head.wos"), width: "minmax(110px, 1fr)", drop: 1, exportValue: (r) => r.wo_numbers.join(" "), render: (r) => <span className="mono mfg-ellipsis">{r.wo_numbers.join(", ") || "–"}</span> },
      { key: "assembled", header: t("gxp.dhr.head.assembled"), width: "150px", render: (r) => formatDateTime(r.assembled_at) },
      { key: "released", header: t("gxp.dhr.fact.releasedAt"), width: "150px", drop: 3, render: (r) => (r.released_at ? formatDateTime(r.released_at) : <span className="faint">–</span>) },
    ],
    [],
  );
  return (
    <QaWorklist<DhrSummary>
      title={t("gxp.dhr.title")}
      description={t("gxp.dhr.desc")}
      actions={action}
      above={tabs}
      pageKey="dhr-all"
      testId="dhr-all-page"
      views={[
        { key: "review", label: t("gxp.dhr.view.review"), query: { status: "assembled,in_review" } },
        { key: "open", label: t("gxp.dhr.view.open"), query: { open_only: "true" } },
      ]}
      statusOptions={[{ value: "", label: t("gxp.list.any") }, ...(["assembled", "in_review", "released", "rejected"] as const).map((s) => ({ value: s, label: chipText(DHR_STATUS, s) }))]}
      fetch={(query, signal) => listDhr({ ...query, tab: undefined }, signal)}
      columns={columns}
      card={{ title: "number", status: "status", fields: ["open", "item", "lot"] }}
      rowKey={(r) => r.id}
      rowExtras={(r) => ({ testId: "dhr-row", data: { status: r.status, number: r.number } })}
      rowPath={(r) => mfgPaths.dhrRecord(r.id)}
      empty={t("gxp.dhr.empty")}
      noun={t("gxp.dhr.noun")}
    />
  );
}

function AssembleDialog({ onClose }: { onClose(): void }) {
  const navigate = useNavigate();
  const [kind, setKind] = useState<"lot" | "wo">("lot");
  const [lot, setLot] = useState<LotRef | null>(null);
  const [wo, setWo] = useState<{ id: string; number: string } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const ok = kind === "lot" ? Boolean(lot) : Boolean(wo);
  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await assembleDhr(kind === "lot" ? { lot_id: lot!.id, reason: reason.trim() || null } : { wo_id: wo!.id, reason: reason.trim() || null });
      navigate(mfgPaths.dhrRecord(r.id));
    } catch (e) {
      setErr(e);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("gxp.dhr.dlg.assembleTitle")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!ok || busy} onClick={() => void go()} data-testid="dhr-assemble-go">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="layers" />} {t("gxp.dhr.btn.assembleShort")}
          </button>
        </>
      }
    >
      <div className="col" style={{ gap: 12 }}>
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{t("gxp.dhr.dlg.assembleBody")}</p>
        <div className="field">
          <span className="field-label" id="dhr-asm-kind">
            {t("gxp.dhr.label.subject")}
          </span>
          <div className="btn-group" role="group" aria-labelledby="dhr-asm-kind">
            <button type="button" className="btn" aria-pressed={kind === "lot"} onClick={() => setKind("lot")}>
              {t("gxp.dhr.subject.lot")}
            </button>
            <button type="button" className="btn" aria-pressed={kind === "wo"} onClick={() => setKind("wo")}>
              {t("gxp.dhr.subject.wo")}
            </button>
          </div>
          <span className="hint">{t("gxp.dhr.hint.subject")}</span>
        </div>
        {kind === "lot" ? <LotPicker value={lot} onChange={setLot} label={t("gxp.head.lot")} testId="dhr-asm-lot" required /> : <WoPicker value={wo} onChange={setWo} label={t("gxp.dhr.subject.wo")} testId="dhr-asm-wo" />}
        <div className="field">
          <label htmlFor="dhr-asm-reason">{t("gxp.dhr.label.reassembleReason")}</label>
          <textarea id="dhr-asm-reason" className="textarea" rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          <span className="hint">{t("gxp.dhr.hint.reassembleReason")}</span>
        </div>
      </div>
    </Dialog>
  );
}
