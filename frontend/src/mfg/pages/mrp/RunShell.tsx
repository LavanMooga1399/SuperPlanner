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
      <div className="row" style={{ gap: 4 }}>
        <button type="button" className="btn sm" onClick={() => void run("xlsx")} disabled={busy} data-testid="run-export">
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="download" />} Export to Excel
        </button>
        <button type="button" className="btn sm ghost" onClick={() => void run("zip")} disabled={busy}>
          CSV (zip)
        </button>
      </div>
      <MfgError error={error} title="Download failed" />
    </div>
  );
}

export function RunShell() {
  const { runId = "" } = useParams();
  const run = useLoad((signal) => getMrpRun(runId, signal), [runId]);
  const latest = useLoad((signal) => getLatestRun("live", signal).catch(() => null), [runId]);
  const r = run.data && run.data.id === runId ? run.data : null;
  if (run.error && isNotFound(run.error)) return <NotFoundPanel what="MRP run" back={<Link className="btn" to={mfgPaths.mrp()}>Back to MRP</Link>} />;
  if (run.error && !r) return <MfgError error={run.error} onRetry={run.reload} />;
  if (!r) return <Spinner label="Loading plan…" />;
  const isLatestLive = r.kind === "live" && r.status === "completed" && latest.data?.id === r.id;
  const stale = r.stale;
  const tabs = [
    { to: mfgPaths.run(r.id), label: "Summary", key: "summary", end: true },
    { to: mfgPaths.runItems(r.id), label: "Material plan", key: "items" },
    { to: mfgPaths.runPlanned(r.id), label: "Planned orders", key: "planned" },
    { to: mfgPaths.runExceptions(r.id), label: "Exceptions", key: "exceptions" },
    { to: mfgPaths.runDemand(r.id), label: "Demand", key: "demand" },
    { to: mfgPaths.runCompare(r.id), label: "Compare", key: "compare" },
  ];
  const ctx: RunContext = { run: r, isLatestLive, reload: run.reload };
  return (
    <div className="col" style={{ gap: 12 }} data-testid="run-shell" data-run-no={r.run_no} data-kind={r.kind}>
      <nav aria-label="Breadcrumb" className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.mrp()}>MRP</Link> <Icon name="chevron-right" size={12} /> <span>Run #{r.run_no}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h1 data-testid="run-title">{runTitle(r)}</h1>
          <RunKindBadge kind={r.kind} />
          <RunStatusChip status={r.status} />
          {isLatestLive ? (
            <span className="badge accent" title="Planned orders of this run can be firmed or released">
              <Icon name="star" /> Latest live plan
            </span>
          ) : null}
          <span className="muted small">
            As of {fmtDate(r.as_of)} · {r.horizon_days} days · {fmtTimestamp(r.finished_at ?? r.started_at)} by {r.actor.name}
          </span>
        </div>
        <ExportMenu runId={r.id} />
      </div>
      {stale?.is_stale ? (
        <Banner
          tone="warn"
          icon="clock"
          title="The data changed after this plan was made"
          testId="run-stale-banner"
          actions={
            <Link className="btn sm" to={mfgPaths.mrp()}>
              <Icon name="refresh" /> Run again
            </Link>
          }
        >
          {[stale.master_changed ? "master data (items, BOMs, routings, suppliers or plant)" : "", stale.transactions_changed ? "stock, orders or work orders" : ""].filter(Boolean).join(" and ")} changed. The plan below is still readable but may be out of date.
        </Banner>
      ) : null}
      {r.kind === "what_if" ? (
        <Banner tone="info" icon="help" title="What-if scenario">
          This run is for comparison only; its planned orders cannot be firmed or released. Live data was not changed.
        </Banner>
      ) : null}
      {r.status === "failed" ? <Banner tone="danger" title="This run failed">{r.error?.message ?? "Unexpected error."}</Banner> : null}
      <nav className="tabs" aria-label="Plan sections">
        {tabs.map((t) => (
          <NavLink key={t.key} to={t.to} end={t.end} className={({ isActive }) => `tab${isActive ? " active" : ""}`} data-testid={`run-tab-${t.key}`}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <div className="tab-panel" style={{ paddingTop: 4 }}>
        <Outlet context={ctx} />
      </div>
    </div>
  );
}
