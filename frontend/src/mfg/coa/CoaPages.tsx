/**
 * Certificates of analysis and batch packs (M10 6, 11). `/mfg/coa` list and `/mfg/coa/:id`: the server-rendered
 * PDF in a preview frame, the reported lines (spec, result, conformance in words), signed approval and void with a
 * reason. A CoA needs the lot's device history record released and never prints a result outside the customer's
 * limits as conforming. `/mfg/batch-packs` and `/mfg/batch-packs/:id`: build status (polled), the documents with their
 * sha256 and the manifest hash, and the zip download.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { t } from "../../lib/i18n";
import { formatDateTime, formatDay, formatNumber } from "../../lib/locale";
import { approveCoa, downloadBatchPack, exportCoa, getBatchPack, getCoa, listBatchPacks, listCoas, voidCoa } from "../api/clientM10";
import type { BatchPack, Coa, CoaLine, PackDocument, Spec } from "../api/typesM10";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { fmtBytes } from "../lib/importMapping";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { usePolling } from "../lib/usePolling";
import { ReasonConfirm } from "../forecast/ForecastPage";
import { HistoryTab, RecordHeader, RecordTabs, Section, SignatureList, TabPanel } from "../qa/RecordShell";
import { QaWorklist } from "../qa/Worklist";
import { ItemById } from "../forecast/shared";
import { chipText, DOC_STATE, DocChip, HashText, KV, PdfFrame, useDownload } from "../dhr/shared";

/** "≤ 4 N", "1.0 – 2.0 mm", "nominal 3 mm"; "–" without limits. */
export function specText(s: Spec | null | undefined): string {
  if (!s) return t("gxp.agr.specFromPlan");
  const u = s.unit ? ` ${s.unit}` : "";
  const f = (v: number) => formatNumber(v);
  if (s.lsl !== null && s.usl !== null) return `${f(s.lsl)} – ${f(s.usl)}${u}`;
  if (s.usl !== null) return `≤ ${f(s.usl)}${u}`;
  if (s.lsl !== null) return `≥ ${f(s.lsl)}${u}`;
  if (s.nominal !== null) return t("gxp.tpl.nominal", { v: `${f(s.nominal)}${u}` });
  return "–";
}

function Conforms({ ok }: { ok: boolean }) {
  return ok ? (
    <span className="badge ok" data-testid="coa-conforms">
      <Icon name="check" /> {t("gxp.coa.conforms")}
    </span>
  ) : (
    <span className="badge danger" data-testid="coa-conforms">
      <Icon name="x" /> {t("gxp.coa.notConforms")}
    </span>
  );
}

// ---------------------------------------------------------------- CoA list
export function CoasPage() {
  useEffect(() => {
    document.title = t("gxp.coa.title");
  }, []);
  const columns = useMemo<Column<Coa>[]>(
    () => [
      {
        key: "number",
        header: t("gxp.coa.head.number"),
        width: "130px",
        render: (c) => (
          <Link className="mono" to={mfgPaths.coa(c.id)} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {c.number}
          </Link>
        ),
      },
      { key: "status", header: t("gxp.head.status"), width: "120px", exportValue: (c) => chipText(DOC_STATE, c.status), render: (c) => <DocChip s={c.status} testId="coa-status" /> },
      { key: "customer", header: t("gxp.agr.head.customer"), width: "150px", render: (c) => c.customer },
      { key: "lot", header: t("gxp.head.lot"), width: "130px", render: (c) => <span className="mono">{c.lot_code ?? "–"}</span> },
      { key: "item", header: t("gxp.head.item"), width: "minmax(160px, 1fr)", render: (c) => <ItemById id={c.item_id} /> },
      { key: "agr", header: t("gxp.coa.head.agreement"), width: "150px", drop: 1, render: (c) => <span className="mono">{c.agreement_number ? `${c.agreement_number} v${c.agreement_version}` : "–"}</span> },
      { key: "created", header: t("gxp.dev.head.created"), width: "150px", drop: 2, render: (c) => formatDateTime(c.created_at) },
    ],
    [],
  );
  return (
    <QaWorklist<Coa>
      title={t("gxp.coa.title")}
      description={t("gxp.coa.desc")}
      actions={
        <Link className="btn" to={mfgPaths.agreements()}>
          <Icon name="book" /> {t("gxp.agr.title")}
        </Link>
      }
      pageKey="coas"
      testId="coas-page"
      statusOptions={[{ value: "", label: t("gxp.list.any") }, ...(["draft", "approved", "void"] as const).map((s) => ({ value: s, label: chipText(DOC_STATE, s) }))]}
      fetch={(q, signal) => listCoas(q, signal)}
      columns={columns}
      card={{ title: "number", status: "status", fields: ["customer", "lot"] }}
      rowKey={(c) => c.id}
      rowExtras={(c) => ({ testId: "coa-row", data: { status: c.status } })}
      rowPath={(c) => mfgPaths.coa(c.id)}
      empty={t("gxp.coa.empty")}
      noun={t("gxp.coa.noun")}
    />
  );
}

// ---------------------------------------------------------------- CoA record
export function CoaPage() {
  const { coaId = "" } = useParams();
  const rec = useLoad((s) => getCoa(coaId, s), [coaId]);
  const c = rec.data;
  const canEdit = useCan("coa_edit");
  const dl = useDownload();
  const [tab, setTab] = useState("preview");
  const [sign, setSign] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (c) document.title = `${c.number} - ${t("gxp.coa.title")}`;
  }, [c]);
  const columns = useMemo<Column<CoaLine>[]>(
    () => [
      { key: "code", header: t("gxp.agr.head.code"), width: "90px", render: (l) => <span className="mono">{l.code}</span> },
      { key: "label", header: t("gxp.agr.head.label"), width: "minmax(160px, 1.5fr)", wrap: true, render: (l) => (l.label_fr ? `${l.label} / ${l.label_fr}` : l.label) },
      { key: "spec", header: t("gxp.agr.head.spec"), width: "150px", exportValue: (l) => specText(l.spec), render: (l) => (
          <span className="col" style={{ gap: 0 }}>
            <span>{l.spec ? specText(l.spec) : "–"}</span>
            <span className="vt-sub">{t(`gxp.coa.specSource.${l.spec_source}`)}</span>
          </span>
        ) },
      { key: "n", header: t("gxp.coa.head.n"), width: "70px", align: "right", render: (l) => <span className="pl-num">{formatNumber(l.n)}</span> },
      { key: "result", header: t("gxp.coa.head.result"), width: "minmax(180px, 1.5fr)", wrap: true, render: (l) => l.result_text },
      { key: "ok", header: t("gxp.coa.head.conformance"), width: "150px", exportValue: (l) => (l.conforms ? t("gxp.coa.conforms") : t("gxp.coa.notConforms")), render: (l) => <Conforms ok={l.conforms} /> },
    ],
    [],
  );
  if (!c) return rec.error ? <MfgError error={rec.error} onRetry={rec.reload} /> : <Spinner />;
  const lines = c.content.lines ?? [];
  const allOk = lines.every((l) => l.conforms);
  return (
    <div className="col gap-lg" data-testid="coa-page" data-status={c.status}>
      <RecordHeader
        crumbs={[[t("gxp.coa.title"), mfgPaths.coas()]]}
        number={c.number}
        title={`${c.customer} · ${c.lot_code ?? ""}`}
        status={<DocChip s={c.status} testId="coa-status" />}
        facts={[
          [t("gxp.coa.head.agreement"), <Link key="a" className="mono" to={mfgPaths.agreement(c.agreement_id)}>{`${c.agreement_number ?? ""} v${c.agreement_version}`}</Link>],
          [t("gxp.coa.head.dhr"), <Link key="d" className="mono" to={mfgPaths.dhrRecord(c.dhr_id)}>{c.dhr_number ?? c.dhr_id}</Link>],
          [t("gxp.head.item"), <ItemById key="i" id={c.item_id} />],
          [t("gxp.col.expiry"), c.content.lot?.expires_on ? formatDay(c.content.lot.expires_on) : null],
          [t("gxp.dhr.fact.hash"), <HashText key="h" h={c.content_sha256} />],
        ]}
        actions={
          <>
            <button type="button" className="btn" disabled={dl.busy !== null} onClick={() => void dl.run("pdf", () => exportCoa(c, "pdf"))} data-testid="coa-pdf">
              <Icon name="download" /> {t("gxp.btn.pdf")}
            </button>
            <button type="button" className="btn" disabled={dl.busy !== null} onClick={() => void dl.run("json", () => exportCoa(c, "json"))}>
              <Icon name="download" /> {t("gxp.btn.json")}
            </button>
            {c.status !== "void" && canEdit ? (
              <button type="button" className="btn danger" onClick={() => setVoiding(true)} data-testid="coa-void">
                <Icon name="ban" /> {t("gxp.coa.btn.void")}
              </button>
            ) : null}
            {c.status === "draft" ? (
              <button type="button" className="btn primary" disabled={!allOk} title={allOk ? undefined : t("gxp.coa.outOfSpecBody")} onClick={() => setSign(true)} data-testid="coa-approve">
                <Icon name="lock" /> {t("gxp.coa.btn.approve")}
              </button>
            ) : null}
          </>
        }
      />
      <MfgError error={err ?? dl.error} />
      {c.status === "void" ? (
        <Banner tone="danger" title={t("gxp.coa.voided")}>
          {c.void_reason}
        </Banner>
      ) : null}
      {!allOk ? <Banner tone="danger" title={t("gxp.code.COA_OUT_OF_SPEC")}>{t("gxp.coa.outOfSpecBody")}</Banner> : null}
      <RecordTabs
        label={t("gxp.coa.aria.tabs")}
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "preview", label: t("gxp.coa.tab.preview") },
          { key: "lines", label: t("gxp.coa.tab.lines"), count: lines.length },
          { key: "signatures", label: t("gxp.dhr.nav.signatures"), count: c.signatures.length },
          { key: "history", label: t("gxp.dhr.nav.history") },
        ]}
      />
      {tab === "preview" ? (
        <TabPanel id="preview">
          <PdfFrame load={() => exportCoa(c, "pdf")} title={t("gxp.tpl.previewOf", { n: c.number })} deps={[c.id, c.row_version]} />
        </TabPanel>
      ) : tab === "lines" ? (
        <TabPanel id="lines">
          <section className="card card-table">
            <DataTable<CoaLine> rows={lines} columns={columns} rowKey={(l) => l.code} label={t("gxp.coa.tab.lines")} testId="coa-lines" exportName={`coa-${c.number}`} rowExtras={(l) => ({ data: { conforms: l.conforms } })} />
          </section>
          <Section title={t("gxp.agr.label.statement")}>
            <p className="qa-text-block">{c.content.statement}</p>
            {c.content.statement_fr ? <p className="qa-text-block" lang="fr">{c.content.statement_fr}</p> : null}
          </Section>
        </TabPanel>
      ) : tab === "signatures" ? (
        <TabPanel id="signatures">
          <Section title={t("gxp.dhr.nav.signatures")}>
            <SignatureList signatures={c.signatures} />
          </Section>
        </TabPanel>
      ) : (
        <TabPanel id="history">
          <HistoryTab entityType="qa_coa" entityId={c.id} />
        </TabPanel>
      )}
      {sign ? (
        <SignatureDialog<Coa>
          title={t("gxp.tpl.approveCoa", { n: c.number })}
          recordType="coa"
          recordId={c.id}
          recordLabel={c.number}
          action="approve"
          submitLabel={t("gxp.coa.btn.signApprove")}
          plainLabel={t("gxp.coa.btn.approve")}
          effect={t("gxp.coa.approveEffect")}
          extraRows={[
            { label: t("gxp.agr.head.customer"), value: c.customer },
            { label: t("gxp.head.lot"), value: c.lot_code ?? "–" },
            { label: t("gxp.coa.tab.lines"), value: lines.map((l) => `${l.code}: ${l.result_text}`).join("; ") },
          ]}
          perform={(sig, comment) => approveCoa(c, sig, comment)}
          onDone={(res) => {
            toast(signedToast(res, t("gxp.tpl.coaApproved", { n: c.number })));
            setSign(false);
            rec.reload();
          }}
          onClose={() => setSign(false)}
        />
      ) : null}
      {voiding ? (
        <ReasonConfirm
          title={t("gxp.tpl.voidCoa", { n: c.number })}
          body={t("gxp.coa.voidBody")}
          confirm={t("gxp.coa.btn.void")}
          danger
          onClose={() => setVoiding(false)}
          run={async (why) => {
            try {
              rec.setData(await voidCoa(c, why));
              toast(t("gxp.coa.toast.voided"));
            } catch (e) {
              setErr(e);
            }
            setVoiding(false);
          }}
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- batch packs
export function BatchPacksPage() {
  useEffect(() => {
    document.title = t("gxp.pack.title");
  }, []);
  const columns = useMemo<Column<BatchPack>[]>(
    () => [
      { key: "number", header: t("gxp.pack.head.number"), width: "130px", render: (p) => <Link className="mono" to={mfgPaths.batchPack(p.id)} tabIndex={-1} onClick={(e) => e.stopPropagation()}>{p.number}</Link> },
      { key: "status", header: t("gxp.head.status"), width: "130px", exportValue: (p) => chipText(DOC_STATE, p.status), render: (p) => <DocChip s={p.status} testId="pack-status" /> },
      { key: "customer", header: t("gxp.agr.head.customer"), width: "160px", render: (p) => p.customer },
      { key: "lots", header: t("gxp.pack.head.lots"), width: "100px", align: "right", render: (p) => <span className="pl-num">{p.lot_ids.length}</span> },
      { key: "docs", header: t("gxp.pack.head.docs"), width: "110px", align: "right", render: (p) => <span className="pl-num">{p.documents.length}</span> },
      { key: "created", header: t("gxp.dev.head.created"), width: "160px", render: (p) => formatDateTime(p.created_at) },
    ],
    [],
  );
  return (
    <QaWorklist<BatchPack>
      title={t("gxp.pack.title")}
      description={t("gxp.pack.desc")}
      pageKey="batch-packs"
      testId="packs-page"
      statusOptions={[{ value: "", label: t("gxp.list.any") }, ...(["building", "ready", "failed"] as const).map((s) => ({ value: s, label: chipText(DOC_STATE, s) }))]}
      fetch={(q, signal) => listBatchPacks(q, signal)}
      columns={columns}
      card={{ title: "number", status: "status", fields: ["customer", "lots"] }}
      rowKey={(p) => p.id}
      rowExtras={(p) => ({ testId: "pack-row", data: { status: p.status } })}
      rowPath={(p) => mfgPaths.batchPack(p.id)}
      empty={t("gxp.pack.empty")}
      noun={t("gxp.pack.noun")}
    />
  );
}

export function BatchPackPage() {
  const { packId = "" } = useParams();
  const rec = useLoad((s) => getBatchPack(packId, s), [packId]);
  const p = rec.data;
  const dl = useDownload();
  usePolling(rec.reload, p?.status === "building");
  useEffect(() => {
    if (p) document.title = `${p.number} - ${t("gxp.pack.title")}`;
  }, [p]);
  const columns = useMemo<Column<PackDocument>[]>(
    () => [
      { key: "file", header: t("gxp.pack.head.file"), width: "minmax(220px, 2fr)", render: (d) => <span className="mono">{d.filename}</span> },
      { key: "kind", header: t("gxp.pack.head.kind"), width: "160px", exportValue: (d) => d.kind, render: (d) => t(`gxp.doc.kind.${d.kind}` as "gxp.doc.kind.coa") },
      { key: "size", header: t("gxp.pack.head.size"), width: "100px", align: "right", sortValue: (d) => d.size, render: (d) => fmtBytes(d.size) },
      { key: "sha", header: t("gxp.pack.head.sha"), width: "160px", exportValue: (d) => d.sha256, render: (d) => <HashText h={d.sha256} n={16} /> },
    ],
    [],
  );
  if (!p) return rec.error ? <MfgError error={rec.error} onRetry={rec.reload} /> : <Spinner />;
  return (
    <div className="col gap-lg" data-testid="pack-page" data-status={p.status}>
      <div className="mfg-breadcrumb small muted">
        <Link to={mfgPaths.batchPacks()}>{t("gxp.pack.title")}</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{p.number}</span>
      </div>
      <PageHeader
        title={t("gxp.tpl.packTitle", { n: p.number, c: p.customer })}
        meta={<DocChip s={p.status} testId="pack-status" />}
        facts={[
          [t("gxp.pack.head.lots"), formatNumber(p.lot_ids.length)],
          [t("gxp.pack.head.docs"), formatNumber(p.documents.length)],
          [t("gxp.pack.fact.manifest"), p.manifest_sha256 ? p.manifest_sha256.slice(0, 16) : "–"],
          [t("gxp.dev.head.created"), formatDateTime(p.created_at)],
        ]}
        actions={
          <button type="button" className="btn primary" disabled={p.status !== "ready" || dl.busy !== null} onClick={() => void dl.run("zip", () => downloadBatchPack(p))} data-testid="pack-download">
            {dl.busy ? <span className="spinner" aria-hidden /> : <Icon name="download" />} {t("gxp.pack.btn.download")}
          </button>
        }
      />
      <MfgError error={dl.error} />
      {p.status === "building" ? (
        <Banner tone="accent" icon="loader" role="status">
          {t("gxp.pack.building")}
        </Banner>
      ) : p.status === "failed" ? (
        <Banner tone="danger" title={t("gxp.pack.failed")}>
          {p.error}
        </Banner>
      ) : null}
      <section className="card card-table">
        <DataTable<PackDocument> rows={p.documents} columns={columns} rowKey={(d) => d.filename} label={t("gxp.pack.head.docs")} testId="pack-docs" exportName={`pack-${p.number}`} empty={t("gxp.pack.noDocs")} />
      </section>
      <Section title={t("gxp.pack.sec.manifest")}>
        <KV
          rows={[
            [t("gxp.pack.fact.manifest"), <HashText key="m" h={p.manifest_sha256} n={64} />],
            [t("gxp.pack.fact.zip"), p.rendition ? <HashText key="z" h={p.rendition.sha256} n={64} /> : null],
            [t("gxp.pack.head.size"), p.rendition ? fmtBytes(p.rendition.size) : null],
          ]}
        />
        <p className="small muted" style={{ marginBottom: 0 }}>
          {t("gxp.pack.manifestHelp")}
        </p>
      </Section>
    </div>
  );
}
