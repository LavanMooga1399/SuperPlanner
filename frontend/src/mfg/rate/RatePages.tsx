/**
 * Rate plan (M8 7, 12): `/mfg/rate` lists rate runs (campaign plans for flow lines) and starts new ones (guided:
 * horizon and overtime policy; expert: time budget, keep firm blocks); `/mfg/rate/runs/:runId/:tab` shows one run -
 * the rate grid (lines x days or shifts, cells = item with quantity in cases, utilisation per cell), the campaign
 * Gantt per line (the M3 Gantt: production bars with the changeover as their striped start, cleaning and clearance as
 * hatched bands), shortages with their explanation, a comparison with another run, and Publish (the firm zone
 * becomes repetitive work orders; later blocks become rate supplies for MRP). A run that failed the independent
 * validator can never be published (V3); a shortfall is always shown with its cause (V1).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { toast } from "../../components/Toast";
import { Legend } from "../../finance/charts/Legend";
import { plural, t } from "../../lib/i18n";
import { formatDateTime, formatDay, formatNumber } from "../../lib/locale";
import { listLines } from "../api/client";
import { compareRateRuns, createRateRun, getPlanningSettings, getRateBlocks, getRateGrid, getRateRun, listRateRuns, publishRateRun, runNightlyNow } from "../api/clientM8";
import type { GanttBand, GanttBar, GanttResponse } from "../api/typesM3";
import type { OvertimePolicy, RatePublishResult, RateBlock, RateExplanation, RateGrid, RateRun, RateShortage } from "../api/typesM8";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import { ProdGantt } from "../components/ProdGantt";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { usePlantClock } from "../lib/plantTime";
import { usePolling } from "../lib/usePolling";
import { errorCode, useLoad } from "../lib/useMfg";
import { useChangeReason } from "../qa/ChangeReason";
import { codeText, colorOf, isRunning, ItemById, JobChip, num, pct, Segmented } from "../forecast/shared";

type Tab = "grid" | "gantt" | "shortages" | "compare";
const TABS: Tab[] = ["grid", "gantt", "shortages", "compare"];

function PublishedBadge({ r }: { r: RateRun }) {
  if (!r.published) return null;
  return (
    <span className="badge ok" data-testid="rate-published">
      <Icon name="flag" /> {t("plan.rate.published")}
    </span>
  );
}

function useLineCodes(): (id: string | null | undefined) => string {
  const lines = useLoad((s) => listLines({}, s).catch(() => ({ items: [] })), []);
  const map = useMemo(() => new Map((lines.data?.items ?? []).map((l) => [l.id, l.code])), [lines.data]);
  return useCallback((id: string | null | undefined) => (id ? map.get(id) ?? "" : ""), [map]);
}

// ---------------------------------------------------------------- run list
export function RateRunsPage() {
  const canRun = useCan("rate_plan");
  const navigate = useNavigate();
  const runs = useLoad((s) => listRateRuns({ limit: 50 }, s), []);
  const anyRunning = (runs.data?.items ?? []).some((r) => isRunning(r.status));
  usePolling(runs.reload, anyRunning);
  const [dialog, setDialog] = useState(false);
  const [nightly, setNightly] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    document.title = t("plan.rate.title");
  }, []);
  const columns = useMemo<Column<RateRun>[]>(
    () => [
      {
        key: "number",
        header: t("plan.rate.head.run"),
        width: "180px",
        sortValue: (r) => r.number,
        exportValue: (r) => r.number,
        render: (r) => (
          <span className="row" style={{ gap: 6 }}>
            <Link to={mfgPaths.rateRun(r.id)} className="mono" onClick={(e) => e.stopPropagation()} tabIndex={-1}>
              {r.number}
            </Link>
            <PublishedBadge r={r} />
          </span>
        ),
      },
      { key: "label", header: t("plan.rate.head.label"), width: "minmax(120px, 1fr)", drop: 2, render: (r) => <span className="mfg-ellipsis">{r.label}</span> },
      { key: "status", header: t("plan.rate.head.status"), width: "150px", exportValue: (r) => r.status, render: (r) => <JobChip s={r.status} /> },
      { key: "horizon", header: t("plan.rate.head.horizon"), width: "170px", sortValue: (r) => r.as_of, render: (r) => t("plan.rate.tpl.horizon", { from: formatDay(r.as_of), n: r.horizon_days }) },
      { key: "campaigns", header: t("plan.rate.head.campaigns"), width: "100px", align: "right", sortValue: (r) => r.summary?.campaigns ?? 0, render: (r) => <span className="pl-num">{num(r.summary?.campaigns ?? null)}</span> },
      {
        key: "short",
        header: t("plan.rate.head.short"),
        width: "120px",
        align: "right",
        sortValue: (r) => r.summary?.shortage_qty ?? 0,
        exportValue: (r) => r.summary?.shortage_qty,
        render: (r) => <ShortQty v={r.summary?.shortage_qty ?? null} />,
      },
      { key: "co", header: t("plan.rate.head.changeover"), width: "120px", align: "right", drop: 1, sortValue: (r) => r.objective?.changeover_hours ?? 0, render: (r) => <span className="pl-num">{r.objective?.changeover_hours !== undefined ? t("plan.tpl.hours", { n: num(r.objective.changeover_hours, 1) }) : "–"}</span> },
      { key: "created", header: t("plan.rate.head.created"), width: "150px", drop: 3, sortValue: (r) => r.created_at, render: (r) => formatDateTime(r.created_at) },
    ],
    [],
  );
  return (
    <div className="col gap-lg" data-testid="rate-runs-page">
      <PageHeader
        title={t("plan.rate.title")}
        description={t("plan.rate.desc")}
        actions={
          <>
            <button type="button" className="btn" disabled={!canRun || nightly} title={canRun ? t("plan.rate.hint.nightly") : needsText("rate_plan")} onClick={() => {
              setNightly(true);
              setErr(null);
              runNightlyNow()
                .then(() => toast(t("plan.rate.toast.nightly")))
                .catch((e: unknown) => setErr(e))
                .finally(() => setNightly(false));
            }} data-testid="rate-nightly">
              <Icon name="refresh" /> {t("plan.rate.btn.nightly")}
            </button>
            <button type="button" className="btn primary" disabled={!canRun} title={canRun ? undefined : needsText("rate_plan")} onClick={() => setDialog(true)} data-testid="rate-new">
              <Icon name="play" /> {t("plan.rate.btn.new")}
            </button>
          </>
        }
      />
      <MfgError error={err} />
      <MfgError error={runs.error} onRetry={runs.reload} />
      <section className="card card-table">
        <DataTable<RateRun>
          rows={runs.data?.items ?? []}
          columns={columns}
          rowKey={(r) => r.id}
          label={t("plan.rate.aria.runs")}
          testId="rate-runs"
          loading={runs.loading && !runs.data}
          onRowClick={(r) => navigate(mfgPaths.rateRun(r.id))}
          onActivate={(r) => navigate(mfgPaths.rateRun(r.id))}
          rowExtras={(r) => ({ testId: "rate-run-row", data: { status: r.status } })}
          exportName="rate-runs"
          empty={t("plan.rate.empty")}
        />
      </section>
      {dialog ? <NewRunDialog onClose={() => setDialog(false)} onStarted={(r) => navigate(mfgPaths.rateRun(r.id))} /> : null}
    </div>
  );
}

function ShortQty({ v }: { v: number | null }) {
  if (v === null) return <span className="muted">–</span>;
  if (v <= 0) return <span className="pl-num muted">0</span>;
  return (
    <span className="badge danger pl-num-badge">
      <Icon name="alert" /> {num(v)}
    </span>
  );
}

function NewRunDialog({ onClose, onStarted }: { onClose(): void; onStarted(r: RateRun): void }) {
  const settings = useLoad((s) => getPlanningSettings(s).catch(() => null), []);
  const [horizon, setHorizon] = useState("");
  const [overtime, setOvertime] = useState<OvertimePolicy>("suggest");
  const [expert, setExpert] = useState(false);
  const [budget, setBudget] = useState("");
  const [keepFirm, setKeepFirm] = useState(true);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const def = settings.data?.rate_horizon_days ?? 30;
  const h = horizon ? Number(horizon) : def;
  const valid = h >= 7 && h <= 60 && (!budget || (Number(budget) >= 10 && Number(budget) <= 900));
  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await createRateRun({ label, horizon_days: horizon ? Number(horizon) : null, overtime, ...(expert ? { time_budget_s: budget ? Number(budget) : null, keep_firm: keepFirm } : {}) });
      toast(t("plan.rate.toast.started", { n: r.number }));
      onStarted(r);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const OT: { v: OvertimePolicy; label: string; help: string }[] = [
    { v: "off", label: t("plan.rate.ot.off"), help: t("plan.rate.ot.offHelp") },
    { v: "suggest", label: t("plan.rate.ot.suggest"), help: t("plan.rate.ot.suggestHelp") },
    { v: "allow", label: t("plan.rate.ot.allow"), help: t("plan.rate.ot.allowHelp") },
  ];
  return (
    <Dialog
      title={t("plan.rate.dlg.newTitle")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!valid || busy} onClick={() => void start()} data-testid="rate-start">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />} {t("plan.rate.btn.start")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{t("plan.rate.dlg.newBody")}</p>
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="rr-horizon">{t("plan.rate.label.horizon")}</label>
            <input id="rr-horizon" className="input pl-w-140" type="number" min={7} max={60} step={1} placeholder={String(def)} value={horizon} onChange={(e) => setHorizon(e.target.value)} aria-invalid={!valid} data-testid="rate-horizon" />
            <span className="hint">{t("plan.rate.hint.horizon")}</span>
          </div>
          <div className="field">
            <label htmlFor="rr-label">{t("plan.fc.label.runLabel")}</label>
            <input id="rr-label" className="input" maxLength={100} value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
        </div>
        <fieldset className="pl-choice">
          <legend className="small muted">{t("plan.rate.label.overtime")}</legend>
          {OT.map((o) => (
            <label key={o.v} className={`pl-choice-opt${overtime === o.v ? " on" : ""}`}>
              <input type="radio" name="rr-ot" checked={overtime === o.v} onChange={() => setOvertime(o.v)} />
              <span>
                <strong>{o.label}</strong>
                <span className="muted small">{o.help}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <button type="button" className="btn ghost sm pl-expert-toggle" aria-expanded={expert} onClick={() => setExpert((v) => !v)}>
          <Icon name={expert ? "chevron-down" : "chevron-right"} /> {t("plan.label.expert")}
        </button>
        {expert ? (
          <div className="pl-expert col pl-gap">
            <div className="field">
              <label htmlFor="rr-budget">{t("plan.rate.label.budget")}</label>
              <input id="rr-budget" className="input pl-w-140" type="number" min={10} max={900} placeholder={String(settings.data?.rate_time_budget_s ?? 240)} value={budget} onChange={(e) => setBudget(e.target.value)} />
              <span className="hint">{t("plan.rate.hint.budget")}</span>
            </div>
            <label className="row" style={{ gap: 6 }}>
              <input type="checkbox" checked={keepFirm} onChange={(e) => setKeepFirm(e.target.checked)} /> {t("plan.rate.label.keepFirm")}
            </label>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- one run
export function RateRunPage() {
  const { runId = "", tab: tabParam } = useParams();
  const tab: Tab = TABS.includes(tabParam as Tab) ? (tabParam as Tab) : "grid";
  const canPublish = useCan("rate_plan");
  const reason = useChangeReason();
  const settings = useLoad((s) => getPlanningSettings(s).catch(() => null), []);
  const run = useLoad((s) => getRateRun(runId, s), [runId]);
  const r = run.data;
  usePolling(run.reload, isRunning(r?.status));
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [result, setResult] = useState<RatePublishResult | null>(null);
  const [rerun, setRerun] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {
    if (r) document.title = `${r.number} - ${t("plan.rate.title")}`;
  }, [r]);
  if (run.error && !r) return <MfgError error={run.error} onRetry={run.reload} />;
  if (!r) return <Spinner />;
  const done = r.status === "completed";
  const validOk = Boolean(r.validator?.ok);
  const publishable = done && validOk && !r.published;
  const shortages = r.shortages ?? [];
  const publish = async () => {
    const why = await reason.ask(t("plan.rate.what", { n: r.number }));
    if (why === null) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await publishRateRun(r.id, why);
      toast(t("plan.rate.toast.published", { n: r.number, c: formatNumber(res.created_wo_ids.length), x: formatNumber(res.cancelled_wo_ids.length), s: formatNumber(res.rate_supplies) }));
      setResult(res);
      setConfirm(false);
      run.reload();
    } catch (e) {
      setErr(e);
      if (errorCode(e) === "RATE_RUN_STALE") setConfirm(false);
    } finally {
      setBusy(false);
    }
  };
  const util = Object.values(r.summary?.utilisation ?? {});
  const avgUtil = util.length ? util.reduce((a, x) => a + x, 0) / util.length : null;
  return (
    <div className="col gap-lg" data-testid="rate-run-page" data-status={r.status}>
      <div className="mfg-breadcrumb small muted">
        <Link to={mfgPaths.ratePlans()}>{t("plan.rate.title")}</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{r.number}</span>
      </div>
      <PageHeader
        title={t("plan.rate.tpl.runTitle", { n: r.number })}
        meta={
          <>
            <JobChip s={r.status} testId="rate-status" />
            <PublishedBadge r={r} />
          </>
        }
        description={r.label || undefined}
        facts={[
          [t("plan.rate.head.horizon"), t("plan.rate.tpl.horizon", { from: formatDay(r.as_of), n: r.horizon_days })],
          [t("plan.rate.head.campaigns"), num(r.summary?.campaigns ?? null)],
          [t("plan.rate.fact.produced"), num(r.summary?.production_qty ?? null)],
          [t("plan.rate.head.short"), num(r.summary?.shortage_qty ?? null)],
          [t("plan.rate.head.changeover"), r.objective?.changeover_hours !== undefined ? t("plan.tpl.hours", { n: num(r.objective.changeover_hours, 1) }) : "–"],
          [t("plan.rate.fact.util"), pct(avgUtil, 0)],
        ]}
        actions={
          <button
            type="button"
            className="btn primary"
            disabled={!canPublish || !publishable}
            title={!canPublish ? needsText("rate_plan") : r.published ? t("plan.rate.hint.isPublished") : !validOk && done ? t("plan.rate.hint.notValid") : undefined}
            onClick={() => setConfirm(true)}
            data-testid="rate-publish"
          >
            <Icon name="flag" /> {t("plan.rate.btn.publish")}
          </button>
        }
      />
      {errorCode(err) === "RATE_RUN_STALE" ? (
        <Banner tone="warn" role="alert" title={t("plan.rate.text.stale")} testId="rate-stale" actions={canPublish ? <button type="button" className="btn sm primary" onClick={() => setRerun(true)}><Icon name="play" /> {t("plan.rate.btn.new")}</button> : null}>
          {t("plan.rate.text.staleBody")}
        </Banner>
      ) : (
        <MfgError error={err} />
      )}
      {result ? <PublishResultPanel res={result} onClose={() => setResult(null)} /> : null}
      {rerun ? <NewRunDialog onClose={() => setRerun(false)} onStarted={(x) => navigate(mfgPaths.rateRun(x.id))} /> : null}
      {isRunning(r.status) ? (
        <Banner tone="accent" icon="loader" role="status" testId="rate-running">
          {t("plan.rate.text.running")}
        </Banner>
      ) : null}
      {r.status === "failed" ? (
        <Banner tone="danger" role="alert" title={t("plan.rate.text.failed")}>
          {r.error ?? ""}
        </Banner>
      ) : null}
      {r.validator && !r.validator.ok ? (
        <Banner tone="danger" icon="shield" role="alert" title={t("plan.rate.text.invalid", { n: plural(r.validator.violations.length, t("plan.noun.problem"), t("plan.noun.problems")) })} testId="rate-violations">
          <ul className="pl-bullets">
            {r.validator.violations.slice(0, 8).map((v, i) => (
              <li key={i}>
                <span className="mono small">{v.code}</span> {typeof v.detail === "string" ? v.detail : JSON.stringify(v.detail)}
              </li>
            ))}
          </ul>
        </Banner>
      ) : done && validOk ? (
        <p className="pl-note ok" style={{ margin: 0 }} data-testid="rate-valid">
          <Icon name="shield" size={14} /> {t("plan.rate.text.valid")}
          {r.duration_ms !== null ? <span>{t("plan.rate.tpl.duration", { s: formatNumber(r.duration_ms / 1000, 1) })}</span> : null}
        </p>
      ) : null}
      <nav className="tabs" aria-label={t("plan.rate.aria.tabs")}>
        {TABS.map((k) => (
          <NavLink key={k} to={mfgPaths.rateRun(r.id, k === "grid" ? undefined : k)} end className={() => `tab${tab === k ? " active" : ""}`} aria-current={tab === k ? "page" : undefined} data-testid={`rate-tab-${k}`}>
            {t(`plan.rate.tab.${k}` as const)}
            {k === "shortages" && shortages.length ? <span className="tab-count">{shortages.length}</span> : null}
          </NavLink>
        ))}
      </nav>
      {done || r.status === "failed_validation" ? (
        tab === "grid" ? (
          <GridTab run={r} firmDays={settings.data?.rate_firm_days ?? 3} />
        ) : tab === "gantt" ? (
          <GanttTab run={r} />
        ) : tab === "shortages" ? (
          <ShortagesTab run={r} />
        ) : (
          <CompareTab run={r} />
        )
      ) : null}
      {confirm ? (
        <ConfirmDialog title={t("plan.rate.dlg.publishTitle", { n: r.number })} confirmLabel={t("plan.rate.btn.publish")} busy={busy} onConfirm={() => void publish()} onCancel={() => setConfirm(false)}>
          <div className="col pl-gap">
            <p style={{ margin: 0 }}>{t("plan.rate.dlg.publishBody", { n: settings.data?.rate_firm_days ?? 3 })}</p>
            <ul className="pl-bullets">
              <li>{t("plan.rate.dlg.publish1")}</li>
              <li>{t("plan.rate.dlg.publish2")}</li>
              <li>{t("plan.rate.dlg.publish3")}</li>
            </ul>
            {shortages.length ? (
              <Banner tone="warn">{t("plan.rate.dlg.publishShort", { n: plural(shortages.length, t("plan.noun.shortage"), t("plan.noun.shortages")) })}</Banner>
            ) : null}
          </div>
        </ConfirmDialog>
      ) : null}
      {reason.dialog}
    </div>
  );
}

// ---------------------------------------------------------------- grid
const DAY = 86400000;
function bucketLabel(b: string, bucket: "shift" | "day"): { top: string; sub: string } {
  if (bucket === "day") {
    const d = new Date(`${b.slice(0, 10)}T00:00:00Z`);
    return { top: formatDay(b.slice(0, 10)).replace(/ \d{4}$/, ""), sub: t(`plan.wd.${d.getUTCDay()}` as "plan.wd.0") };
  }
  return { top: formatDay(b.slice(0, 10)).replace(/ \d{4}$/, ""), sub: `${b.slice(11, 13)}:00` };
}

function GridTab({ run, firmDays }: { run: RateRun; firmDays: number }) {
  const [bucket, setBucket] = useState<"day" | "shift">("day");
  const grid = useLoad((s) => getRateGrid(run.id, bucket, s), [run.id, bucket]);
  const g = grid.data;
  const firmUntil = Date.parse(`${run.as_of}T00:00:00Z`) + (firmDays + 1) * DAY;
  const cellMap = useMemo(() => {
    const m = new Map<string, RateGrid["cells"]>();
    for (const c of g?.cells ?? []) {
      const k = `${c.line_id}|${c.bucket}`;
      const arr = m.get(k);
      if (arr) arr.push(c);
      else m.set(k, [c]);
    }
    return m;
  }, [g]);
  const itemsSeen = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of g?.cells ?? []) if (c.item_id) m.set(c.item_id, c.part_number ?? c.item_id);
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [g]);
  return (
    <section className="card" aria-label={t("plan.rate.tab.grid")} data-testid="rate-grid">
      <div className="card-header pl-card-header">
        <Segmented<"day" | "shift">
          label={t("plan.rate.label.bucket")}
          value={bucket}
          onChange={setBucket}
          testId="rate-bucket"
          options={[
            { value: "day", label: t("plan.rate.bucket.day") },
            { value: "shift", label: t("plan.rate.bucket.shift") },
          ]}
        />
        <span className="muted small">{t("plan.rate.grid.hint")}</span>
      </div>
      <MfgError error={grid.error} onRetry={grid.reload} />
      {grid.loading && !g ? <Spinner /> : null}
      {g ? (
        g.lines.length ? (
          <div className="pl-pivot-wrap pl-grid-wrap">
            <table className="pl-pivot pl-rgrid">
              <thead>
                <tr>
                  <th scope="col">{t("plan.rate.head.line")}</th>
                  {g.buckets.map((b) => {
                    const l = bucketLabel(b, g.bucket);
                    const firm = Date.parse(b.length > 10 ? `${b}:00:00Z` : `${b}T00:00:00Z`) < firmUntil;
                    return (
                      <th key={b} scope="col" className={firm ? "pl-firm" : undefined} title={firm ? t("plan.rate.grid.firm") : undefined}>
                        <span className="pl-bh">{l.top}</span>
                        <span className="pl-bs">
                          {firm ? <Icon name="lock" size={10} /> : null} {l.sub}
                        </span>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {g.lines.map((ln) => {
                  const lineUtil = run.summary?.utilisation?.[ln.line_id];
                  return (
                    <tr key={ln.line_id} data-testid="rate-grid-line" data-line={ln.code}>
                      <th scope="row">
                        <span className="mono">{ln.code}</span>
                        {lineUtil !== undefined ? <UtilBar v={lineUtil} /> : null}
                      </th>
                      {g.buckets.map((b) => {
                        const cells = cellMap.get(`${ln.line_id}|${b}`) ?? [];
                        const u = ln.utilisation[b];
                        return (
                          <td key={b} className="pl-rcell">
                            {cells.map((c, i) => (
                              <div key={i} className="pl-ritem" title={`${c.part_number ?? ""}: ${num(c.qty)} (${t("plan.tpl.hours", { n: num(c.hours, 1) })})`}>
                                <span className="pl-sw" style={{ background: c.item_id ? colorOf(c.item_id) : "var(--text-faint)" }} aria-hidden />
                                <span className="mono pl-rpart">{c.part_number ?? "–"}</span>
                                <span className="pl-num">{c.cases !== null ? t("plan.rate.tpl.cs", { n: num(c.cases) }) : num(c.qty)}</span>
                              </div>
                            ))}
                            {u !== undefined ? <UtilBar v={u} thin /> : null}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="card-body muted" style={{ margin: 0 }}>{t("plan.rate.grid.empty")}</p>
        )
      ) : null}
      {itemsSeen.length ? (
        <div className="card-footer">
          <Legend label={t("plan.chart.legend")} items={itemsSeen.slice(0, 24).map(([id, pn]) => ({ label: pn, color: colorOf(id), kind: "box" as const }))} />
        </div>
      ) : null}
    </section>
  );
}

/** Utilisation as a bar with the percent as text (over 100 % shows the overload). */
function UtilBar({ v, thin }: { v: number; thin?: boolean }) {
  const p = Math.round(v * 100);
  const tone = v > 1 ? "danger" : v >= 0.9 ? "warn" : "ok";
  return (
    <span className={`pl-util${thin ? " thin" : ""}`} title={t("plan.rate.tpl.util", { p })}>
      <span className="pl-util-track" aria-hidden>
        <span className={`pl-util-fill ${tone}`} style={{ width: `${Math.min(100, p)}%` }} />
      </span>
      <span className="pl-util-text">{`${p} %`}</span>
    </span>
  );
}

// ---------------------------------------------------------------- campaign Gantt (M3 ProdGantt)
function toGantt(blocks: RateBlock[], codes: (id: string) => string): { data: GanttResponse; info: Map<number, string>; from: number; to: number } {
  const rows = new Map<string, string>();
  const bars: GanttBar[] = [];
  const bands: GanttBand[] = [];
  const info = new Map<number, string>();
  const byLine = new Map<string, RateBlock[]>();
  for (const b of blocks) {
    const arr = byLine.get(b.line_id);
    if (arr) arr.push(b);
    else byLine.set(b.line_id, [b]);
  }
  let from = Infinity;
  let to = -Infinity;
  let no = 0;
  for (const [lineId, list] of byLine) {
    const key = `line:${lineId}`;
    rows.set(key, list[0].line_code ?? codes(lineId) ?? lineId);
    list.sort((a, b) => a.start.localeCompare(b.start));
    let pendingCo: RateBlock | null = null;
    for (const b of list) {
      from = Math.min(from, Date.parse(b.start));
      to = Math.max(to, Date.parse(b.end));
      if (b.kind === "changeover") {
        pendingCo = b;
        continue;
      }
      if (b.kind === "production") {
        const co = pendingCo && pendingCo.end === b.start ? pendingCo : null;
        no += 1;
        bars.push({
          op_no: no,
          row_key: key,
          start: co ? co.start : b.start,
          end: b.end,
          setup_end: co ? co.end : null,
          pieces: [],
          label: t("plan.rate.gantt.bar", { part: b.part_number ?? "", c: b.campaign_no }),
          order_number: t("plan.rate.gantt.campaign", { c: b.campaign_no }),
          item_part_number: b.part_number ?? "",
          qty: b.qty,
          late_minutes: 0,
          frozen: Boolean(b.wo_id),
          locked: false,
          split: null,
          status_color: "",
        });
        const mins = co ? Math.round((Date.parse(co.end) - Date.parse(co.start)) / 60000) : 0;
        info.set(no, [b.cases !== null ? t("plan.rate.tpl.cases", { n: num(b.cases) }) : "", co ? t("plan.rate.gantt.co", { m: mins }) : t("plan.rate.gantt.noCo"), b.wo_id ? t("plan.rate.gantt.firm") : ""].filter(Boolean).join(" · "));
        pendingCo = null;
        continue;
      }
      if (pendingCo) {
        // a changeover not followed directly by production: show as a band
        bands.push({ row_key: key, start: pendingCo.start, end: pendingCo.end, kind: "absence" });
        pendingCo = null;
      }
      bands.push({ row_key: key, start: b.start, end: b.end, kind: b.kind === "down" ? "downtime" : "absence" });
    }
  }
  const sortedRows = [...rows.entries()].sort((a, b) => a[1].localeCompare(b[1])).map(([k, label]) => ({ key: k, label, kind: "line", parent_key: null }));
  return { data: { rows: sortedRows, bars, bands, truncated: false }, info, from: Number.isFinite(from) ? from : Date.now(), to: Number.isFinite(to) ? to : Date.now() + DAY };
}

function GanttTab({ run }: { run: RateRun }) {
  const clock = usePlantClock();
  const codes = useLineCodes();
  const blocks = useLoad((s) => getRateBlocks(run.id, { limit: 20000 }, s), [run.id]);
  const [zoom, setZoom] = useState(2);
  const [sel, setSel] = useState<number | null>(null);
  const model = useMemo(() => (blocks.data ? toGantt(blocks.data.items, codes) : null), [blocks.data, codes]);
  if (blocks.error) return <MfgError error={blocks.error} onRetry={blocks.reload} />;
  if (!model) return <Spinner />;
  const dayStart = Math.floor(model.from / DAY) * DAY;
  return (
    <section className="card" aria-label={t("plan.rate.tab.gantt")} data-testid="rate-gantt">
      <div className="card-header pl-card-header">
        <span className="muted small">{t("plan.rate.gantt.hint")}</span>
        <div className="btn-group" role="group" aria-label={t("plan.rate.label.zoom")}>
          <button type="button" className="btn sm icon" aria-label={t("plan.rate.btn.zoomOut")} onClick={() => setZoom((z) => Math.max(0, z - 1))} disabled={zoom === 0}>
            <Icon name="zoom-out" size={14} />
          </button>
          <button type="button" className="btn sm icon" aria-label={t("plan.rate.btn.zoomIn")} onClick={() => setZoom((z) => Math.min(7, z + 1))} disabled={zoom === 7}>
            <Icon name="zoom-in" size={14} />
          </button>
        </div>
      </div>
      {model.data.bars.length ? (
        <ProdGantt
          data={model.data}
          clock={clock}
          from={dayStart}
          to={Math.ceil(model.to / DAY) * DAY + DAY}
          zoom={zoom}
          onZoom={setZoom}
          editable={false}
          rowsAreLines
          selected={sel}
          onSelect={setSel}
          onDrop={() => undefined}
          preview={null}
          reasonOf={(op) => model.info.get(op) ?? null}
          onHover={() => undefined}
        />
      ) : (
        <p className="card-body muted" style={{ margin: 0 }}>{t("plan.rate.grid.empty")}</p>
      )}
      <div className="card-footer pl-gantt-legend" aria-label={t("plan.chart.legend")}>
        <span><span className="pl-lg-bar" aria-hidden /> {t("plan.rate.lg.production")}</span>
        <span><span className="pl-lg-bar co" aria-hidden /> {t("plan.rate.lg.changeover")}</span>
        <span><span className="pl-lg-band" aria-hidden /> {t("plan.rate.lg.cleaning")}</span>
        <span><span className="pl-lg-band down" aria-hidden /> {t("plan.rate.lg.down")}</span>
        <span><span className="pl-lg-bar firm" aria-hidden>F</span> {t("plan.rate.lg.firm")}</span>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- shortages and explanations
function ShortagesTab({ run }: { run: RateRun }) {
  const codes = useLineCodes();
  const shortages = run.shortages ?? [];
  const expl = (run.explanations ?? []).filter((e) => e.severity !== "info" || e.code === "RATE_SPLIT");
  const sevIcon = (s: string) => (s === "error" ? "alert" : s === "warning" ? "alert" : "info");
  return (
    <div className="col gap-lg">
      <section className="card card-table" aria-label={t("plan.rate.short.title")}>
        <div className="card-header pl-card-header">
          <h2 className="pl-h2">{t("plan.rate.short.title")}</h2>
          <span className="muted small">{t("plan.rate.short.hint")}</span>
        </div>
        <DataTable<RateShortage>
          rows={shortages}
          rowKey={(s, i) => `${s.item_id}-${s.due}-${i}`}
          label={t("plan.rate.short.title")}
          testId="rate-shortages"
          exportName={`rate-shortages-${run.number}`}
          empty={t("plan.rate.short.empty")}
          columns={[
            { key: "item", header: t("plan.fc.head.item"), width: "minmax(200px, 2fr)", render: (s) => <ItemById id={s.item_id} /> },
            { key: "due", header: t("plan.rate.short.due"), width: "120px", sortValue: (s) => s.due, render: (s) => formatDay(s.due) },
            { key: "qty", header: t("plan.rate.short.qty"), width: "110px", align: "right", sortValue: (s) => s.qty, render: (s) => <span className="pl-num">{num(s.qty)}</span> },
            {
              key: "cause",
              header: t("plan.rate.short.cause"),
              width: "minmax(220px, 2fr)",
              wrap: true,
              exportValue: (s) => s.cause,
              render: (s) => (
                <span className="row" style={{ gap: 6 }}>
                  <span className="badge danger"><Icon name="alert" /> {codeText(s.cause)}</span>
                  {typeof s.detail?.load_pct === "number" ? <span className="muted small">{t("plan.rate.tpl.load", { p: s.detail.load_pct })}</span> : null}
                </span>
              ),
            },
          ]}
        />
      </section>
      <section className="card card-table" aria-label={t("plan.rate.expl.title")}>
        <div className="card-header pl-card-header">
          <h2 className="pl-h2">{t("plan.rate.expl.title")}</h2>
        </div>
        <DataTable<RateExplanation>
          rows={expl}
          rowKey={(e, i) => `${e.code}-${i}`}
          label={t("plan.rate.expl.title")}
          testId="rate-explanations"
          empty={t("plan.rate.expl.empty")}
          columns={[
            {
              key: "status",
              header: t("plan.rate.expl.kind"),
              width: "minmax(180px, 1fr)",
              render: (e) => (
                <span className={`badge ${e.severity === "error" ? "danger" : e.severity === "warning" ? "warn" : "info"}`}>
                  <Icon name={sevIcon(e.severity)} /> {codeText(e.code)}
                </span>
              ),
            },
            { key: "line", header: t("plan.rate.head.line"), width: "100px", render: (e) => <span className="mono">{codes(e.line_id)}</span> },
            { key: "msg", header: t("plan.rate.expl.detail"), width: "minmax(260px, 3fr)", wrap: true, render: (e) => e.message },
          ]}
        />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- compare
function CompareTab({ run }: { run: RateRun }) {
  const runs = useLoad((s) => listRateRuns({ limit: 50 }, s), []);
  const others = (runs.data?.items ?? []).filter((x) => x.id !== run.id && x.status === "completed");
  const [other, setOther] = useState("");
  const b = other || others.find((x) => x.published)?.id || others[0]?.id || "";
  const cmp = useLoad((s) => (b ? compareRateRuns(b, run.id, s) : null), [b, run.id]);
  const c = cmp.data;
  const bRun = others.find((x) => x.id === b);
  const metricKey = (m: string) => (["shortage_unit_days", "changeover_cost", "changeover_hours", "excess_cover_unit_days", "overtime_cost"].includes(m) ? t(`plan.rate.obj.${m}` as "plan.rate.obj.changeover_cost") : m);
  const Delta = ({ v, lowerBetter = true }: { v: number; lowerBetter?: boolean }) => {
    if (Math.abs(v) < 1e-9) return <span className="muted pl-num">0</span>;
    const better = lowerBetter ? v < 0 : v > 0;
    return (
      <span className={`pl-num ${better ? "pl-better" : "pl-worse"}`}>
        {v > 0 ? "+" : "−"}
        {num(Math.abs(v), 1)} {better ? t("plan.rate.cmp.better") : t("plan.rate.cmp.worse")}
      </span>
    );
  };
  return (
    <div className="col gap-lg" data-testid="rate-compare">
      <div className="field">
        <label htmlFor="rc-other">{t("plan.rate.cmp.with")}</label>
        <select id="rc-other" className="select" value={b} onChange={(e) => setOther(e.target.value)} disabled={!others.length} data-testid="rate-compare-with">
          {!others.length ? <option value="">{t("plan.rate.cmp.none")}</option> : null}
          {others.map((x) => (
            <option key={x.id} value={x.id}>
              {`${x.number}${x.published ? ` (${t("plan.rate.published")})` : ""} · ${formatDateTime(x.created_at)}`}
            </option>
          ))}
        </select>
      </div>
      <MfgError error={cmp.error} onRetry={cmp.reload} />
      {c && bRun ? (
        <>
          <section className="card card-table" aria-label={t("plan.rate.cmp.objective")}>
            <div className="card-header pl-card-header">
              <h2 className="pl-h2">{t("plan.rate.cmp.objective")}</h2>
            </div>
            <table className="pl-edit-table">
              <thead>
                <tr>
                  <th scope="col">{t("plan.rate.cmp.measure")}</th>
                  <th scope="col" className="pl-r">{bRun.number}</th>
                  <th scope="col" className="pl-r">{run.number}</th>
                  <th scope="col" className="pl-r">{t("plan.rate.cmp.change")}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(c.objective).map(([m, v]) => (
                  <tr key={m}>
                    <th scope="row">{metricKey(m)}</th>
                    <td className="pl-r pl-num">{num(v.a, 1)}</td>
                    <td className="pl-r pl-num">{num(v.b, 1)}</td>
                    <td className="pl-r"><Delta v={v.delta} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <section className="card card-table">
            <DataTable
              rows={c.lines}
              rowKey={(l) => l.line_id}
              label={t("plan.rate.cmp.lines")}
              testId="rate-compare-lines"
              columns={[
                { key: "line", header: t("plan.rate.head.line"), width: "120px", render: (l) => <span className="mono">{l.code}</span> },
                { key: "qa", header: t("plan.rate.cmp.qtyOf", { n: bRun.number }), width: "140px", align: "right", render: (l) => <span className="pl-num">{num(l.a_qty)}</span> },
                { key: "qb", header: t("plan.rate.cmp.qtyOf", { n: run.number }), width: "140px", align: "right", render: (l) => <span className="pl-num">{num(l.b_qty)}</span> },
                { key: "ca", header: t("plan.rate.cmp.coOf", { n: bRun.number }), width: "140px", align: "right", render: (l) => <span className="pl-num">{num(l.a_changeovers)}</span> },
                { key: "cb", header: t("plan.rate.cmp.coOf", { n: run.number }), width: "140px", align: "right", render: (l) => <span className="pl-num">{num(l.b_changeovers)}</span> },
              ]}
            />
          </section>
          <section className="card card-table">
            <DataTable
              rows={c.items}
              rowKey={(i) => i.item_id}
              label={t("plan.rate.cmp.items")}
              testId="rate-compare-items"
              exportName="rate-compare-items"
              columns={[
                { key: "item", header: t("plan.fc.head.item"), width: "minmax(180px, 2fr)", render: (i) => <ItemById id={i.item_id} part={i.part_number} /> },
                { key: "qa", header: t("plan.rate.cmp.qtyOf", { n: bRun.number }), width: "130px", align: "right", sortValue: (i) => i.a_qty, render: (i) => <span className="pl-num">{num(i.a_qty)}</span> },
                { key: "qb", header: t("plan.rate.cmp.qtyOf", { n: run.number }), width: "130px", align: "right", sortValue: (i) => i.b_qty, render: (i) => <span className="pl-num">{num(i.b_qty)}</span> },
                { key: "sa", header: t("plan.rate.cmp.shortOf", { n: bRun.number }), width: "130px", align: "right", sortValue: (i) => i.a_short, render: (i) => <ShortQty v={i.a_short} /> },
                { key: "sb", header: t("plan.rate.cmp.shortOf", { n: run.number }), width: "130px", align: "right", sortValue: (i) => i.b_short, render: (i) => <ShortQty v={i.b_short} /> },
              ]}
            />
          </section>
        </>
      ) : cmp.loading && b ? (
        <Spinner />
      ) : !others.length ? (
        <p className="muted">{t("plan.rate.cmp.noneHint")}</p>
      ) : null}
    </div>
  );
}

/** Publish outcome (7.3): work orders created / cancelled / kept, rate supplies, and groups held by started work
 * orders whose quantity differs from the plan (no second work order is made; the difference is listed). */
function PublishResultPanel({ res, onClose }: { res: RatePublishResult; onClose(): void }) {
  return (
    <section className="card" data-testid="rate-publish-result" aria-labelledby="rpr-h">
      <div className="card-header pl-card-header">
        <h2 className="pl-h2" id="rpr-h">{t("plan.rate.pub.title")}</h2>
        <button type="button" className="btn sm ghost icon" aria-label={t("common.close")} onClick={onClose}>
          <Icon name="x" />
        </button>
      </div>
      <div className="card-body col pl-gap">
        <dl className="pl-facts">
          <div><dt>{t("plan.rate.pub.created")}</dt><dd>{formatNumber(res.created_wo_ids.length)}</dd></div>
          <div><dt>{t("plan.rate.pub.cancelled")}</dt><dd>{formatNumber(res.cancelled_wo_ids.length)}</dd></div>
          <div><dt>{t("plan.rate.pub.kept")}</dt><dd>{formatNumber(res.kept_wo_ids.length)}</dd></div>
          <div><dt>{t("plan.rate.pub.supplies")}</dt><dd>{formatNumber(res.rate_supplies)}</dd></div>
        </dl>
        {res.skipped?.length ? (
          <>
            <p className="pl-note" style={{ margin: 0 }}>
              <Icon name="alert" size={14} /> {t("plan.rate.pub.skippedText", { n: res.skipped?.length ?? 0 })}
            </p>
            <DataTable
              rows={res.skipped ?? []}
              rowKey={(x) => x.wo_id}
              label={t("plan.rate.pub.skipped")}
              testId="rate-publish-skipped"
              columnSettings={false}
              columns={[
                { key: "wo", header: t("plan.ster.head.wo"), width: "130px", render: (x) => <Link to={mfgPaths.workOrder(x.wo_id)} className="mono">{x.wo_number ?? t("plan.rate.pub.open")}</Link> },
                { key: "item", header: t("plan.fc.head.item"), width: "minmax(180px, 2fr)", render: (x) => <ItemById id={x.item_id} /> },
                { key: "due", header: t("plan.rate.short.due"), width: "120px", render: (x) => (x.due ? formatDay(x.due) : "") },
                { key: "wq", header: t("plan.rate.pub.woQty"), width: "110px", align: "right", render: (x) => <span className="pl-num">{num(x.wo_qty)}</span> },
                { key: "pq", header: t("plan.rate.pub.planQty"), width: "110px", align: "right", render: (x) => <span className="pl-num">{num(x.planned_qty)}</span> },
                { key: "d", header: t("plan.rate.pub.diff"), width: "110px", align: "right", render: (x) => <span className="pl-num">{num(x.planned_qty - x.wo_qty)}</span> },
              ]}
            />
          </>
        ) : null}
      </div>
    </section>
  );
}
