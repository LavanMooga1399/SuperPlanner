/**
 * `/mfg/mrp/runs/:runId/**` shell (M2 14.2): run header, stale banner (8.14: data changed after the run; never
 * blocks reading), export, and the tabs Summary / Material plan / Planned orders / Exceptions / Demand / Compare.
 */
import { useState } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { downloadRunExport, getLatestRun, getMrpRun } from "../../api/clientM2";
import { saveBlob } from "../../api/client";
import type { MrpRunRecord } from "../../api/typesM2";
import { MfgError, NotFoundPanel, Spinner } from "../../components/Feedback";
import { RunKindBadge, RunStatusChip } from "../../components/StatusM2";
import { fmtDate, fmtTimestamp } from "../../lib/format";
import { mfgPaths } from "../../lib/paths";
import { isNotFound, useLoad } from "../../lib/useMfg";
import { runTitle } from "./MrpRunsPage";
import { plural, t, t as tr } from "../../../lib/i18n";

export interface RunContext {
  run: MrpRunRecord;
  /** Planned orders can be converted only from the latest completed live run (8.14). */
  isLatestLive: boolean;
  reload(): void;
}

export function useRun(): RunContext {
  return useOutletContext<RunContext>();
}

function ExportMenu({ runId }: { runId: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = async (f: "xlsx" | "zip") => {
    setBusy(true);
    setError(null);
    try {
      saveBlob(await downloadRunExport(runId, f));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="col" style={{ gap: 4 }}>
      <div className="row" style={{ gap: 8 }}>
        <button type="button" className="btn" onClick={() => void run("xlsx")} disabled={busy} data-testid="run-export">
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="download" />}{" "}{tr("mfg.runShell.text.exportToExcel")}
        </button>
        <button type="button" className="btn" onClick={() => void run("zip")} disabled={busy}>
          <Icon name="download" /> {t("mfg.runShell.btn.csvZip")}
        </button>
      </div>
      <MfgError error={error} title={tr("mfg.runShell.attr.downloadFailed")} />
    </div>
  );
}

export function RunShell() {
  const { runId = "" } = useParams();
  const run = useLoad((signal) => getMrpRun(runId, signal), [runId]);
  const latest = useLoad((signal) => getLatestRun("live", signal).catch(() => null), [runId]);
  const r = run.data && run.data.id === runId ? run.data : null;
  if (run.error && isNotFound(run.error)) return <NotFoundPanel what={tr("mfg.runShell.attr.mrpRun")} back={<Link className="btn" to={mfgPaths.mrp()}>{tr("mfg.runShell.text.backToMrp")}</Link>} />;
  if (run.error && !r) return <MfgError error={run.error} onRetry={run.reload} />;
  if (!r) return <Spinner label={t("mfg.runShell.label.loadingPlan")} />;
  const isLatestLive = r.kind === "live" && r.status === "completed" && latest.data?.id === r.id;
  const stale = r.stale;
  const tabs = [
    { to: mfgPaths.run(r.id), label: tr("mfg.runShell.str.summary"), key: "summary", end: true },
    { to: mfgPaths.runItems(r.id), label: tr("mfg.runShell.str.materialPlan"), key: "items" },
    { to: mfgPaths.runPlanned(r.id), label: tr("mfg.runShell.str.plannedOrders"), key: "planned" },
    { to: mfgPaths.runExceptions(r.id), label: tr("mfg.runShell.str.exceptions"), key: "exceptions" },
    { to: mfgPaths.runDemand(r.id), label: tr("mfg.runShell.str.demand"), key: "demand" },
    { to: mfgPaths.runCompare(r.id), label: tr("mfg.runShell.str.compare"), key: "compare" },
  ];
  const ctx: RunContext = { run: r, isLatestLive, reload: run.reload };
  return (
    <div className="col" style={{ gap: 12 }} data-testid="run-shell" data-run-no={r.run_no} data-kind={r.kind}>
      <nav aria-label={t("mfg.runShell.aria.breadcrumb")} className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.mrp()}>MRP</Link> <Icon name="chevron-right" size={12} /> <span>{tr("common.runNo", { n: r.run_no })}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h1 data-testid="run-title">{runTitle(r)}</h1>
          <RunKindBadge kind={r.kind} />
          <RunStatusChip status={r.status} />
          {isLatestLive ? (
            <span className="badge accent" title={tr("mfg.runShell.attr.plannedOrdersOfThisRun")}>
              <Icon name="star" /> {t("mfg.runShell.btn.latestLivePlan")}
            </span>
          ) : null}
          <span className="muted small">
            {tr("mfg.runShell.text.asOfBy", { asof: fmtDate(r.as_of), horizondays: plural(r.horizon_days, "day"), fmtTimestamp: fmtTimestamp(r.finished_at ?? r.started_at), name: r.actor.name })}
          </span>
        </div>
        <ExportMenu runId={r.id} />
      </div>
      {stale?.is_stale ? (
        <Banner
          tone="warn"
          icon="clock"
          title={t("mfg.runShell.title.theDataChangedAfterThis")}
          testId="run-stale-banner"
          actions={
            <Link className="btn sm" to={mfgPaths.mrp()}>
              <Icon name="refresh" /> {t("mfg.runShell.btn.runAgain")}
            </Link>
          }
        >
          {tr("mfg.runShell.text.changedThePlanBelowIs", { join: [stale.master_changed ? tr("mfg.runShell.str.masterDataItemsBomsRoutings") : "", stale.transactions_changed ? tr("mfg.runShell.str.stockOrdersOrWorkOrders") : ""].filter(Boolean).join(" and ") })}
        </Banner>
      ) : null}
      {r.kind === "what_if" ? (
        <Banner tone="info" icon="help" title={t("mfg.runShell.title.whatifScenario")}>
          {tr("mfg.runShell.text.thisRunIsForComparison")}
        </Banner>
      ) : null}
      {r.status === "failed" ? <Banner tone="danger" title={t("mfg.runShell.title.thisRunFailed")}>{r.error?.message ?? tr("mfg.runShell.str.unexpectedError")}</Banner> : null}
      <nav className="tabs" aria-label={t("mfg.runShell.aria.planSections")}>
        {tabs.map((t) => (
          <NavLink key={t.key} to={t.to} end={t.end} className={({ isActive }) => `tab${isActive ? " active" : ""}`} data-testid={`run-tab-${t.key}`}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <div className="tab-panel" style={{ paddingTop: 4 }}>
        <Outlet key={r.id} context={ctx} />
      </div>
    </div>
  );
}
