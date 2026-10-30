/**
 * `/mfg/schedule/runs/:runId/**` shell (M3 12): header, live progress (polled every 2 s), cancel, publish, export,
 * stale banner, the "Re-run with automatic overtime (Allow)" escalation (16 Q1) and the tabs.
 */
import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate, useOutletContext, useParams } from "react-router";
import { saveBlob } from "../../api/client";
import { Banner } from "../../../components/Banner";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Icon } from "../../../components/Icon";
import { cancelApsRun, downloadApsExport, getApsRun, publishApsRun, rerunWithPolicy } from "../../api/clientM3";
import type { ApsRunRecord } from "../../api/typesM3";
import { ApsProgress, ApsStatusChip, PolicyBadge, PublishedBadge } from "../../components/ApsBits";
import { MfgError, NotFoundPanel, Spinner } from "../../components/Feedback";
import { RunKindBadge } from "../../components/StatusM2";
import { fmtTimestamp } from "../../lib/format";
import { usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { needsText, useCan } from "../../lib/permissions";
import { usePolling } from "../../lib/usePolling";
import { isConflict, isNotFound, useLoad } from "../../lib/useMfg";
import { apsRunTitle, isActive } from "./ApsRunsPage";

export interface ApsRunContext {
  run: ApsRunRecord;
  reload(): void;
  setRun(r: ApsRunRecord): void;
}

export function useApsRun(): ApsRunContext {
  return useOutletContext<ApsRunContext>();
}

export function canPublish(r: ApsRunRecord): boolean {
  return r.kind === "live" && r.status === "completed" && Boolean(r.validation?.ok) && !r.is_published;
}

/** Late demand left and overtime not used automatically -> offer the Allow re-run (16 Q1). */
export function offersAllow(r: ApsRunRecord): boolean {
  const s = r.summary;
  const policy = s?.overtime_policy ?? r.params?.overtime ?? null;
  return r.status === "completed" && policy !== "allow" && Boolean(s && (s.demand_late > 0 || s.late_orders > 0));
}

export function PublishButton({ run, onDone, testId = "aps-publish" }: { run: ApsRunRecord; onDone(r: ApsRunRecord): void; testId?: string }) {
  const can = useCan("schedule_publish");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (run.is_published) return <PublishedBadge />;
  const why = !can
    ? needsText("schedule_publish")
    : run.kind !== "live"
      ? "What-if runs cannot be published"
      : run.status !== "completed"
        ? "Only completed runs can be published"
        : !run.validation?.ok
          ? "The plan breaks hard rules (see validation)"
          : undefined;
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await publishApsRun(run.id, run.row_version));
      setConfirm(false);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button type="button" className="btn primary" disabled={Boolean(why) || busy} title={why} aria-disabled={Boolean(why)} onClick={() => setConfirm(true)} data-testid={testId}>
        <Icon name="flag" /> Publish
      </button>
      {confirm ? (
        <ConfirmDialog title={`Publish ${apsRunTitle(run)}?`} confirmLabel="Publish" busy={busy} onCancel={() => setConfirm(false)} onConfirm={() => void go()}>
          <p style={{ margin: 0 }}>It becomes the plant plan: dispatch lists, the freeze window of the next run and MRP dates use it. It replaces the currently published schedule.</p>
          <MfgError error={error} title={isConflict(error) ? "The run changed meanwhile; reload" : "Could not publish"} />
        </ConfirmDialog>
      ) : null}
    </>
  );
}

/** "Re-run with automatic overtime (Allow)": same inputs, `allow`, then the compare view of both runs. */
export function RerunAllowBanner({ run }: { run: ApsRunRecord }) {
  const navigate = useNavigate();
  const can = useCan("schedule_run");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (!offersAllow(run)) return null;
  const s = run.summary!;
  const saved = s.suggested_tardiness_saved_minutes;
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await rerunWithPolicy(run.id, "allow", `${run.label || `Schedule #${run.run_no}`} with overtime`);
      navigate(mfgPaths.apsCompare(next.id, run.id));
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <Banner
      tone="warn"
      icon="clock"
      title={`${s.demand_late || s.late_orders} ${s.demand_late ? "demand lines" : "orders"} still late without overtime`}
      testId="aps-rerun-allow-banner"
      actions={
        <button type="button" className="btn primary" onClick={() => void go()} disabled={!can || busy} title={can ? undefined : needsText("schedule_run")} data-testid="aps-rerun-allow">
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />} Re-run with automatic overtime (Allow)
        </button>
      }
    >
      Creates a new run with the same inputs that opens extra shifts where work would otherwise be late, then compares both: lateness saved against overtime hours added.
      {saved ? ` The suggestions of this run would save about ${Math.round(saved / 60)} weighted late hours.` : ""} You then publish whichever plan you prefer.
      <MfgError error={error} title="Could not start the re-run" />
    </Banner>
  );
}

export function ApsRunShell() {
  const { runId = "" } = useParams();
  const clock = usePlantClock();
  const canRun = useCan("schedule_run");
  const run = useLoad((signal) => getApsRun(runId, signal), [runId]);
  const r = run.data && run.data.id === runId ? run.data : null;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  usePolling(run.reload, Boolean(r && isActive(r)));

  if (run.error && isNotFound(run.error)) return <NotFoundPanel what="Schedule run" back={<Link className="btn" to={mfgPaths.schedule()}>Back to schedules</Link>} />;
  if (run.error && !r) return <MfgError error={run.error} onRetry={run.reload} />;
  if (!r) return <Spinner label="Loading schedule…" />;

  const cancel = async () => {
    setBusy(true);
    setError(null);
    try {
      run.setData(await cancelApsRun(r.id));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const exp = async (f: "xlsx" | "zip") => {
    setError(null);
    try {
      saveBlob(await downloadApsExport(r.id, f));
    } catch (e) {
      setError(e);
    }
  };

  const tabs = [
    { to: mfgPaths.apsRun(r.id), label: "Summary", key: "summary", end: true },
    { to: mfgPaths.apsGantt(r.id), label: "Gantt", key: "gantt" },
    { to: mfgPaths.apsLoad(r.id), label: "Capacity load", key: "load" },
    { to: mfgPaths.apsDispatch(r.id), label: "Dispatch lists", key: "dispatch" },
    { to: mfgPaths.apsOrders(r.id), label: "Orders", key: "orders" },
    { to: mfgPaths.apsDemand(r.id), label: "Demand", key: "demand" },
    { to: mfgPaths.apsOvertime(r.id), label: "Overtime", key: "overtime" },
    { to: mfgPaths.apsExceptions(r.id), label: "Exceptions", key: "exceptions" },
    { to: mfgPaths.apsCompare(r.id), label: "Compare", key: "compare" },
  ];
  const ctx: ApsRunContext = { run: r, reload: run.reload, setRun: (x) => run.setData(x) };
  const done = r.status === "completed" || r.status === "cancelled";

  return (
    <div className="col" style={{ gap: 12 }} data-testid="aps-run-shell" data-run-no={r.run_no} data-status={r.status} data-kind={r.kind}>
      <nav aria-label="Breadcrumb" className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.schedule()}>Schedule</Link> <Icon name="chevron-right" size={12} /> <span>Run #{r.run_no}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h1 data-testid="aps-run-title">{apsRunTitle(r)}</h1>
          <RunKindBadge kind={r.kind} />
          <ApsStatusChip run={r} />
          <PolicyBadge policy={r.summary?.overtime_policy ?? r.params?.overtime ?? null} />
          {r.parent_run_id ? (
            <Link className="badge info" to={mfgPaths.apsRun(r.parent_run_id)} title="Created by manual edits of another run">
              <Icon name="copy" /> edited copy
            </Link>
          ) : null}
          <span className="muted small">
            From {clock.dateTime(r.as_of)} ({clock.zoneLabel}){r.mrp_run ? ` · MRP run #${r.mrp_run.run_no}` : ""} · {fmtTimestamp(r.finished_at ?? r.started_at)} by {r.actor.name}
          </span>
        </div>
        <div className="mfg-actions">
          {isActive(r) ? (
            <>
              <ApsProgress run={r} />
              {canRun ? (
                <button type="button" className="btn" onClick={() => void cancel()} disabled={busy} data-testid="aps-cancel">
                  <Icon name="stop" /> Cancel
                </button>
              ) : null}
            </>
          ) : (
            <>
              <PublishButton run={r} onDone={(x) => run.setData(x)} />
              {done ? (
                <>
                  <button type="button" className="btn sm" onClick={() => void exp("xlsx")} data-testid="aps-export">
                    <Icon name="download" /> Export
                  </button>
                  <button type="button" className="btn sm ghost" onClick={() => void exp("zip")}>
                    CSV (zip)
                  </button>
                </>
              ) : null}
            </>
          )}
        </div>
      </div>
      <MfgError error={error} />
      {r.stale?.is_stale ? (
        <Banner
          tone="warn"
          icon="clock"
          title="The data changed after this schedule was made"
          testId="aps-stale-banner"
          actions={
            <Link className="btn sm" to={mfgPaths.schedule()}>
              <Icon name="refresh" /> New schedule
            </Link>
          }
        >
          {[r.stale.master_changed ? "master data (routings, lines, shifts, people)" : "", r.stale.transactions_changed ? "orders, stock or progress" : ""].filter(Boolean).join(" and ") ||
            "Inputs"}{" "}
          changed. The plan is still readable but may be out of date.
        </Banner>
      ) : null}
      {r.kind === "what_if" ? (
        <Banner tone="info" icon="help" title="What-if scenario">
          For comparison only; it cannot be published.
        </Banner>
      ) : null}
      {r.status === "failed" ? <Banner tone="danger" title="This run failed">{r.error?.message ?? "Unexpected error."}</Banner> : null}
      {r.status === "cancelled" ? (
        <Banner tone="warn" title="Cancelled">
          {r.summary ? "The best plan found before cancelling is shown." : "No plan was finished before cancelling."}
        </Banner>
      ) : null}
      {r.status === "completed" && r.validation && !r.validation.ok ? (
        <Banner tone="danger" icon="x" title="This plan breaks hard rules and cannot be published" testId="aps-invalid-banner">
          {(r.validation.violations ?? []).slice(0, 5).map((v, i) => (
            <div key={i}>
              <code>{v.code}</code> {v.message}
            </div>
          ))}
        </Banner>
      ) : null}
      <RerunAllowBanner run={r} />
      <nav className="tabs" aria-label="Schedule sections">
        {tabs.map((t) => (
          <NavLink key={t.key} to={t.to} end={t.end} className={({ isActive: a }) => `tab${a ? " active" : ""}`} data-testid={`aps-tab-${t.key}`}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <div className="tab-panel" style={{ paddingTop: 4 }}>
        {isActive(r) ? (
          <div className="empty" role="status" data-testid="aps-waiting">
            <span className="spinner" aria-hidden />
            <span>The schedule is being calculated; results appear here when it finishes. You can leave this page.</span>
          </div>
        ) : done ? (
          <Outlet key={r.id} context={ctx} />
        ) : null}
      </div>
    </div>
  );
}
