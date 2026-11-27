/**
 * `/mfg/dhr` (M10 4, 11): review queue of device history records - status, open major / minor exceptions, age of the
 * oldest open exception, item, lot, line, "changed after release" flag; quick views (to review, open exceptions,
 * changed after release), status filter, saved views. The header summarises the queue by age; "Assemble record"
 * builds (or rebuilds) the record of a lot or work order on demand.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { t } from "../../lib/i18n";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { assembleDhr, getReviewQueue, listDhr } from "../api/clientM10";
import type { DhrSummary } from "../api/typesM10";
import { MfgError } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { ItemCell, itemText, usePersonName } from "../qa/common";
import { QaWorklist } from "../qa/Worklist";
import { KpiCard } from "../network/shared";
import { AgeCell, chipText, DHR_STATUS, DhrStatusChip, OpenCounts } from "./shared";
import { LotPicker, WoPicker, type LotRef } from "./pickers";

export function DhrQueuePage() {
  const canReview = useCan("dhr_review");
  const person = usePersonName();
  const [assemble, setAssemble] = useState(false);
  const queue = useLoad((s) => getReviewQueue(s).catch(() => null), []);
  useEffect(() => {
    document.title = t("gxp.dhr.title");
  }, []);
  const columns = useMemo<Column<DhrSummary>[]>(
    () => [
      {
        key: "number",
        header: t("gxp.dhr.head.record"),
        width: "150px",
        sortKey: "number",
        sortKeyDesc: "-number",
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
        width: "200px",
        exportValue: (r) => chipText(DHR_STATUS, r.status) + (r.changed_after_release ? ` / ${t("gxp.dhr.changedAfterRelease")}` : ""),
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
      { key: "open", header: t("gxp.dhr.head.open"), width: "190px", sortKey: "-open", exportValue: (r) => `${r.counts.major}/${r.counts.minor}`, render: (r) => <OpenCounts major={openOf(r, "major")} minor={openOf(r, "minor")} testId="dhr-open" /> },
      { key: "age", header: t("gxp.dhr.head.age"), width: "130px", sortKey: "oldest_open_at", exportValue: (r) => r.oldest_open_at ?? "", render: (r) => (r.status === "released" || r.status === "rejected" ? <span className="faint">–</span> : <AgeCell since={r.oldest_open_at ?? r.assembled_at} />) },
      { key: "item", header: t("gxp.head.item"), width: "minmax(180px, 1.5fr)", exportValue: (r) => itemText(r.item), render: (r) => <ItemCell item={r.item} id={r.item_id} /> },
      { key: "lot", header: t("gxp.head.lot"), width: "120px", render: (r) => (r.lot_code ? <span className="mono">{r.lot_code}</span> : <span className="faint">–</span>) },
      { key: "wos", header: t("gxp.head.wos"), width: "minmax(110px, 1fr)", drop: 2, exportValue: (r) => r.wos.map((w) => w.number).join(" "), render: (r) => <span className="mono mfg-ellipsis">{r.wos.map((w) => w.number).join(", ") || "–"}</span> },
      { key: "line", header: t("gxp.head.line"), width: "90px", drop: 1, render: (r) => r.line_code ?? <span className="faint">–</span> },
      { key: "owner", header: t("gxp.dhr.head.owner"), width: "140px", drop: 3, exportValue: (r) => person(r.owner_id), render: (r) => (r.owner_id ? person(r.owner_id) : <span className="faint">–</span>) },
      { key: "assembled", header: t("gxp.dhr.head.assembled"), width: "150px", sortKey: "-assembled_at", render: (r) => (r.assembled_at ? formatDateTime(r.assembled_at) : "–") },
    ],
    [person],
  );
  const q = queue.data;
  return (
    <>
      <QaWorklist<DhrSummary>
        title={t("gxp.dhr.title")}
        description={t("gxp.dhr.desc")}
        actions={
          <button type="button" className="btn primary" disabled={!canReview} title={canReview ? undefined : needsText("dhr_review")} onClick={() => setAssemble(true)} data-testid="dhr-assemble">
            <Icon name="layers" /> {t("gxp.dhr.btn.assemble")}
          </button>
        }
        above={
          q ? (
            <div className="gxp-kpis" data-testid="dhr-queue-summary">
              <KpiCard label={t("gxp.dhr.kpi.awaiting")} value={formatNumber(q.awaiting_review)} testId="dhr-kpi-awaiting" />
              {q.buckets.map((b) => (
                <KpiCard key={b.bucket} label={t(`gxp.dhr.bucket.${b.bucket}` as const)} value={formatNumber(b.records)} sub={t("gxp.tpl.openExceptions", { n: formatNumber(b.exceptions) })} />
              ))}
              <KpiCard label={t("gxp.dhr.kpi.changed")} value={formatNumber(q.changed_after_release)} />
            </div>
          ) : null
        }
        pageKey="dhr-queue"
        testId="dhr-queue-page"
        searchPlaceholder={t("gxp.dhr.ph.search")}
        views={[
          { key: "review", label: t("gxp.dhr.view.review"), query: { status: "assembled,in_review" } },
          { key: "open", label: t("gxp.dhr.view.open"), query: { open_only: "true" } },
          { key: "changed", label: t("gxp.dhr.view.changed"), query: { changed_after_release: "true" } },
        ]}
        statusOptions={[{ value: "", label: t("gxp.list.any") }, ...(["assembled", "in_review", "released", "rejected"] as const).map((s) => ({ value: s, label: chipText(DHR_STATUS, s) }))]}
        fetch={(query, signal) => listDhr(query, signal)}
        columns={columns}
        card={{ title: "number", status: "status", fields: ["open", "item", "lot", "age"] }}
        rowKey={(r) => r.id}
        rowExtras={(r) => ({ testId: "dhr-row", data: { status: r.status, number: r.number } })}
        rowPath={(r) => mfgPaths.dhrRecord(r.id)}
        empty={t("gxp.dhr.empty")}
        noun={t("gxp.dhr.noun")}
      />
      {assemble ? <AssembleDialog onClose={() => setAssemble(false)} /> : null}
    </>
  );
}

const openOf = (r: DhrSummary, sev: "major" | "minor") => (sev === "major" ? r.counts.open_major : r.counts.open_minor);

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
