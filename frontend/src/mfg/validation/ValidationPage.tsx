/**
 * Validation kit `/mfg/validation` (M8 10, 12): the latest requirement trace matrix (requirements, tests, last result,
 * CSA risk; high-risk requirements without a test are gaps that fail the gate) with CSV / HTML download, and the
 * configuration baselines (hash of plant, planning, QA and signature settings, roles and integration) with a diff
 * between any two.
 */
import { useEffect, useMemo, useState } from "react";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { FilterBar } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { toast } from "../../components/Toast";
import { t } from "../../lib/i18n";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { saveBlob } from "../api/client";
import { createBaseline, diffBaselines, downloadTraceMatrix, getTraceMatrix, listBaselines } from "../api/clientM8";
import type { Baseline, BaselineDiff, TraceMatrixRow } from "../api/typesM8";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { needsText, useAccess, useCan } from "../lib/permissions";
import { useDebounced, useLoad } from "../lib/useMfg";
import { usePersonName } from "../qa/common";
import { Chip, Segmented } from "../forecast/shared";

const RISK = {
  high: { label: "plan.val.risk.high", tone: "danger", icon: "alert" },
  medium: { label: "plan.val.risk.medium", tone: "warn", icon: "flag" },
  low: { label: "plan.val.risk.low", tone: "info", icon: "circle" },
} as const;
const RESULT = {
  passed: { label: "plan.val.res.passed", tone: "ok", icon: "check" },
  failed: { label: "plan.val.res.failed", tone: "danger", icon: "x" },
  skipped: { label: "plan.val.res.skipped", tone: "info", icon: "ban" },
  not_run: { label: "plan.val.res.notRun", tone: "info", icon: "circle" },
} as const;

export function ValidationPage() {
  const canView = useCan("validation_view");
  useEffect(() => {
    document.title = t("plan.val.title");
  }, []);
  const tm = useLoad((s) => (canView ? getTraceMatrix(s) : null), [canView]);
  const [risk, setRisk] = useState<"all" | "high" | "medium" | "low">("all");
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim().toLowerCase(), 200);
  const [dl, setDl] = useState<"csv" | "html" | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const m = tm.data;
  const rows = (m?.rows ?? []).filter((r) => (risk === "all" || r.risk === risk) && (!dq || `${r.id} ${r.title}`.toLowerCase().includes(dq)));
  const download = async (f: "csv" | "html") => {
    setDl(f);
    setErr(null);
    try {
      saveBlob(await downloadTraceMatrix(f));
    } catch (e) {
      setErr(e);
    } finally {
      setDl(null);
    }
  };
  const columns = useMemo<Column<TraceMatrixRow>[]>(
    () => [
      { key: "id", header: t("plan.val.head.id"), width: "140px", sortValue: (r) => r.id, render: (r) => <span className="mono">{r.id}</span> },
      { key: "title", header: t("plan.val.head.title"), width: "minmax(220px, 3fr)", wrap: true, sortValue: (r) => r.title, render: (r) => r.title },
      { key: "risk", header: t("plan.val.head.risk"), width: "110px", sortValue: (r) => ["high", "medium", "low"].indexOf(r.risk), exportValue: (r) => r.risk, render: (r) => <Chip def={RISK[r.risk]} value={r.risk} /> },
      { key: "tests", header: t("plan.val.head.tests"), width: "90px", align: "right", sortValue: (r) => r.tests.length, exportValue: (r) => r.tests.join(" "), render: (r) => <span className="pl-num" title={r.tests.join("\n")}>{r.tests.length}</span> },
      {
        key: "status",
        header: t("plan.val.head.result"),
        width: "130px",
        exportValue: (r) => r.last_result,
        render: (r) => (r.tests.length ? <Chip def={RESULT[(r.last_result ?? "not_run") as keyof typeof RESULT]} value={r.last_result ?? "not_run"} /> : <Chip def={{ label: "plan.val.res.noTest", tone: r.risk === "high" ? "danger" : "warn", icon: "alert" }} value="no_test" />),
      },
    ],
    [],
  );
  if (!canView)
    return (
      <div className="col gap-lg">
        <PageHeader title={t("plan.val.title")} />
        <Banner tone="warn">{needsText("validation_view")}</Banner>
      </div>
    );
  return (
    <div className="col gap-lg" data-testid="val-page">
      <PageHeader
        title={t("plan.val.title")}
        description={t("plan.val.desc")}
        facts={m ? [[t("plan.val.fact.reqs"), formatNumber(m.requirements)], [t("plan.val.fact.covered"), formatNumber(m.covered)], [t("plan.val.fact.gaps"), formatNumber(m.gaps.length)], [t("plan.val.fact.generated"), m.generated_at ? formatDateTime(m.generated_at) : "–"]] : []}
        actions={
          <>
            <button type="button" className="btn" disabled={!m || dl !== null} onClick={() => void download("html")} data-testid="val-html">
              {dl === "html" ? <span className="spinner" aria-hidden /> : <Icon name="download" />} {t("plan.val.btn.html")}
            </button>
            <button type="button" className="btn" disabled={!m || dl !== null} onClick={() => void download("csv")} data-testid="val-csv">
              {dl === "csv" ? <span className="spinner" aria-hidden /> : <Icon name="download" />} CSV
            </button>
          </>
        }
      />
      <MfgError error={err} />
      <MfgError error={tm.error} onRetry={tm.reload} />
      {tm.loading && !m ? <Spinner /> : null}
      {m ? (
        <>
          {m.high_risk_gaps > 0 ? (
            <Banner tone="danger" role="alert" title={t("plan.val.text.highGaps", { n: m.high_risk_gaps })} testId="val-high-gaps">
              {m.gaps.filter((g) => g.risk === "high").map((g) => g.id).join(", ")}
            </Banner>
          ) : (
            <Banner tone="ok" testId="val-no-high-gaps">{t("plan.val.text.noHighGaps")}</Banner>
          )}
          <FilterBar search={{ id: "val-q", value: q, onChange: setQ, placeholder: t("plan.val.ph.search") }}>
            <div className="field">
              <span className="field-label">{t("plan.val.head.risk")}</span>
              <Segmented<"all" | "high" | "medium" | "low">
                label={t("plan.val.head.risk")}
                value={risk}
                onChange={setRisk}
                options={[
                  { value: "all", label: t("plan.label.all") },
                  { value: "high", label: t("plan.val.risk.high") },
                  { value: "medium", label: t("plan.val.risk.medium") },
                  { value: "low", label: t("plan.val.risk.low") },
                ]}
              />
            </div>
          </FilterBar>
          <section className="card card-table">
            <DataTable<TraceMatrixRow> rows={rows} columns={columns} rowKey={(r) => r.id} label={t("plan.val.table")} testId="val-matrix" exportName="trace-matrix" empty={t("plan.val.empty")} />
          </section>
        </>
      ) : null}
      <Baselines />
    </div>
  );
}

function Baselines() {
  const access = useAccess();
  const person = usePersonName();
  const list = useLoad((s) => listBaselines(s), []);
  const items = list.data?.items ?? [];
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [creating, setCreating] = useState(false);
  const ia = a || items[1]?.id || "";
  const ib = b || items[0]?.id || "";
  const diff = useLoad((s) => (ia && ib && ia !== ib ? diffBaselines(ia, ib, s) : null), [ia, ib]);
  const label = (x: Baseline) => `${x.label} · ${formatDateTime(x.created_at)}`;
  return (
    <section className="card" aria-labelledby="val-bl-h" data-testid="val-baselines">
      <div className="card-header pl-card-header">
        <h2 className="pl-h2" id="val-bl-h">{t("plan.val.bl.title")}</h2>
        <button type="button" className="btn sm primary" disabled={!access.isOwner} title={access.isOwner ? undefined : needsText("owner")} onClick={() => setCreating(true)} data-testid="val-baseline-new">
          <Icon name="plus" /> {t("plan.val.bl.new")}
        </button>
      </div>
      <MfgError error={list.error} onRetry={list.reload} />
      <DataTable<Baseline>
        rows={items}
        rowKey={(x) => x.id}
        label={t("plan.val.bl.title")}
        testId="val-baseline-list"
        loading={list.loading && !list.data}
        empty={t("plan.val.bl.empty")}
        columns={[
          { key: "label", header: t("plan.val.bl.label"), width: "minmax(180px, 2fr)", render: (x) => x.label },
          { key: "sha", header: t("plan.val.bl.hash"), width: "160px", render: (x) => <span className="mono small" title={x.sha256}>{x.sha256.slice(0, 12)}</span> },
          { key: "by", header: t("plan.val.bl.by"), width: "160px", render: (x) => person(x.created_by) },
          { key: "at", header: t("plan.val.bl.at"), width: "160px", render: (x) => formatDateTime(x.created_at) },
        ]}
      />
      {items.length >= 2 ? (
        <div className="card-body col pl-gap">
          <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
            <div className="field">
              <label htmlFor="bl-a">{t("plan.val.bl.from")}</label>
              <select id="bl-a" className="select" value={ia} onChange={(e) => setA(e.target.value)} data-testid="val-diff-a">
                {items.map((x) => <option key={x.id} value={x.id}>{label(x)}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="bl-b">{t("plan.val.bl.to")}</label>
              <select id="bl-b" className="select" value={ib} onChange={(e) => setB(e.target.value)} data-testid="val-diff-b">
                {items.map((x) => <option key={x.id} value={x.id}>{label(x)}</option>)}
              </select>
            </div>
          </div>
          <MfgError error={diff.error} />
          {diff.data ? <DiffView d={diff.data} /> : ia === ib ? <p className="muted" style={{ margin: 0 }}>{t("plan.val.bl.pickTwo")}</p> : null}
        </div>
      ) : null}
      {creating ? <NewBaseline onClose={() => setCreating(false)} onDone={() => {
        setCreating(false);
        list.reload();
      }} /> : null}
    </section>
  );
}

function DiffView({ d }: { d: BaselineDiff }) {
  const show = (v: unknown) => (v === undefined || v === null ? "–" : typeof v === "string" ? v : JSON.stringify(v));
  if (d.same) return <Banner tone="ok" testId="val-diff-same">{t("plan.val.bl.same")}</Banner>;
  return (
    <DataTable
      rows={d.changes}
      rowKey={(c) => c.path}
      label={t("plan.val.bl.changes")}
      testId="val-diff"
      exportName="baseline-diff"
      columns={[
        { key: "path", header: t("plan.val.bl.path"), width: "minmax(220px, 2fr)", wrap: true, render: (c) => <span className="mono small">{c.path}</span> },
        { key: "status", header: t("plan.val.bl.kind"), width: "110px", render: (c) => <Chip def={{ label: c.kind === "added" ? "plan.val.bl.added" : c.kind === "removed" ? "plan.val.bl.removed" : "plan.val.bl.changed", tone: c.kind === "removed" ? "warn" : "info", icon: c.kind === "added" ? "plus" : c.kind === "removed" ? "trash" : "refresh" }} value={c.kind} /> },
        { key: "a", header: t("plan.val.bl.before"), width: "minmax(140px, 1fr)", wrap: true, render: (c) => <span className="mono small">{show(c.a)}</span> },
        { key: "b", header: t("plan.val.bl.after"), width: "minmax(140px, 1fr)", wrap: true, render: (c) => <span className="mono small">{show(c.b)}</span> },
      ]}
    />
  );
}

function NewBaseline({ onClose, onDone }: { onClose(): void; onDone(): void }) {
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const b = await createBaseline(label.trim());
      toast(t("plan.val.toast.baseline", { h: b.sha256.slice(0, 12) }));
      onDone();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("plan.val.bl.new")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>{t("common.cancel")}</button>
          <button type="button" className="btn primary" disabled={!label.trim() || busy} onClick={() => void save()} data-testid="val-baseline-save">
            {busy ? <span className="spinner" aria-hidden /> : null} {t("plan.val.bl.create")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <p style={{ margin: 0 }}>{t("plan.val.bl.newBody")}</p>
        <MfgError error={err} />
        <div className="field">
          <label htmlFor="bl-label">{t("plan.val.bl.label")}</label>
          <input id="bl-label" className="input" maxLength={200} value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("plan.val.ph.label")} data-autofocus data-testid="val-baseline-label" />
        </div>
      </div>
    </Dialog>
  );
}
