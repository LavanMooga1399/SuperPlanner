/**
 * `/mfg/schedule/runs/:runId/**` shell (M3 12): header, live progress (polled every 2 s), cancel, publish, export,
 * stale banner, the "Re-run with automatic overtime (Allow)" escalation (16 Q1) and the tabs.
 */
import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate, useOutletContext, useParams } from "react-router";
import { ApiError } from "../../../api/client";
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
import { toast } from "../../../components/Toast";
import { formatNumber } from "../../../lib/locale";
import { t, t as tr } from "../../../lib/i18n";

export interface ApsRunContext {
  run: ApsRunRecord;
  reload(): void;
  setRun(r: ApsRunRecord): void;
}

export function useApsRun(): ApsRunContext {
  return useOutletContext<ApsRunContext>();
}

export function canPublish(r: ApsRunRecord): boolean {
  return Boolean(r.publishable) && !r.is_published;
}

/** Late demand left and overtime not used automatically -> offer the Allow re-run (16 Q1). */
export function offersAllow(r: ApsRunRecord): boolean {
  // the server decides (`late_demand_remains`); status/policy guard records from older servers
  return r.status === "completed" && r.policy !== "allow" && Boolean(r.late_demand_remains);
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
      ? tr("mfg.apsRunShell.str.whatIfRunsCannotBe")
      : run.status !== "completed"
        ? tr("mfg.apsRunShell.str.onlyCompletedRunsCanBe")
        : !run.validation?.ok
          ? tr("mfg.apsRunShell.str.thePlanBreaksHardRules")
          : !run.publishable
            ? tr("mfg.apsRunShell.str.thisRunCannotBePublished")
            : undefined;
  // 409 APS_RUN_STALE_BASIS: another run was published after this one was computed; publish only on confirmation.
  const staleBasis = error instanceof ApiError && error.code === "APS_RUN_STALE_BASIS";
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await publishApsRun(run.id, run.row_version, staleBasis));
      toast(tr("mfg.apsRunShell.tpl.publishedToTheShopFloor", { tr: tr("common.scheduleNo", { n: run.run_no }) }));
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
        <Icon name="flag" /> {t("mfg.apsRunShell.btn.publish")}
      </button>
      {confirm ? (
        <ConfirmDialog title={tr("mfg.apsRunShell.tpl.publish", { run: apsRunTitle(run) })} confirmLabel={staleBasis ? tr("mfg.apsRunShell.str.publishAnyway") : tr("mfg.apsRunShell.str.publish")} busy={busy} onCancel={() => { setConfirm(false); setError(null); }} onConfirm={() => void go()}>
          <p style={{ margin: 0 }}>{t("mfg.apsRunShell.text.itBecomesThePlantPlan")}</p>
          {staleBasis ? (
            <p style={{ margin: "8px 0 0" }} data-testid="aps-publish-stale-basis">
              <strong>{tr("mfg.apsRunShell.text.anotherScheduleWasPublishedAfter")}</strong>{" "}{tr("mfg.apsRunShell.text.thisRunFrozeTheNext")}
            </p>
          ) : (
            <MfgError error={error} title={isConflict(error) ? tr("mfg.apsRunShell.str.theRunChangedMeanwhileReload") : tr("mfg.apsRunShell.str.couldNotPublish")} />
          )}
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
  const saved = s.suggested_tardiness_saved;
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await rerunWithPolicy(run.id, "allow", `${run.label || `${tr("common.scheduleNo", { n: run.run_no })}`} with overtime`);
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
      title={tr("mfg.apsRunShell.tpl.stillLateWithoutOvertime", { v: s.late_demand_count || s.late_orders, v2: s.late_demand_count ? (s.late_demand_count === 1 ? "demand line" : "demand lines") : "orders" })}
      testId="aps-rerun-allow-banner"
      actions={
        <button type="button" className="btn primary" onClick={() => void go()} disabled={!can || busy} title={can ? undefined : needsText("schedule_run")} data-testid="aps-rerun-allow">
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />}{" "}{tr("mfg.apsRunShell.text.reRunWithAutomaticOvertime")}
        </button>
      }
    >
      {tr("mfg.apsRunShell.text.aReRunWithThe", { v: saved ? tr("mfg.apsRunShell.tpl.estimatedSavingAboutPriorityWeighted", { formatNumber: formatNumber(Math.round(saved / 60), 0) }) : "" })}
      <MfgError error={error} title={tr("mfg.apsRunShell.attr.couldNotStartTheRe")} />
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

  if (run.error && isNotFound(run.error)) return <NotFoundPanel what={tr("mfg.apsRunShell.attr.scheduleRun")} back={<Link className="btn" to={mfgPaths.schedule()}>{tr("mfg.apsRunShell.text.backToSchedules")}</Link>} />;
  if (run.error && !r) return <MfgError error={run.error} onRetry={run.reload} />;
  if (!r) return <Spinner label={t("mfg.apsRunShell.label.loadingSchedule")} />;

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
    { to: mfgPaths.apsRun(r.id), label: tr("mfg.apsRunShell.str.summary"), key: "summary", end: true },
    { to: mfgPaths.apsGantt(r.id), label: tr("mfg.apsRunShell.str.gantt"), key: "gantt" },
    { to: mfgPaths.apsLoad(r.id), label: tr("mfg.apsRunShell.str.capacityLoad"), key: "load" },
    { to: mfgPaths.apsDispatch(r.id), label: tr("mfg.apsRunShell.str.dispatchLists"), key: "dispatch" },
    { to: mfgPaths.apsOrders(r.id), label: tr("mfg.apsRunShell.str.orders"), key: "orders" },
    { to: mfgPaths.apsDemand(r.id), label: tr("mfg.apsRunShell.str.demand"), key: "demand" },
    { to: mfgPaths.apsOvertime(r.id), label: tr("mfg.apsRunShell.str.overtime"), key: "overtime" },
    { to: mfgPaths.apsExceptions(r.id), label: tr("mfg.apsRunShell.str.exceptions"), key: "exceptions" },
    { to: mfgPaths.apsCompare(r.id), label: tr("mfg.apsRunShell.str.compare"), key: "compare" },
  ];
  const ctx: ApsRunContext = { run: r, reload: run.reload, setRun: (x) => run.setData(x) };
  const done = r.status === "completed" || r.status === "cancelled";

  return (
    <div className="col" style={{ gap: 12 }} data-testid="aps-run-shell" data-run-no={r.run_no} data-status={r.status} data-kind={r.kind}>
      <nav aria-label={t("mfg.apsRunShell.aria.breadcrumb")} className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.schedule()}>{tr("mfg.apsRunShell.text.schedule")}</Link> <Icon name="chevron-right" size={12} /> <span>{tr("common.runNo", { n: r.run_no })}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h1 data-testid="aps-run-title">{apsRunTitle(r)}</h1>
          <RunKindBadge kind={r.kind} />
          <ApsStatusChip run={r} />
          <PolicyBadge policy={r.policy} />
          {r.parent_run_id ? (
            <Link className="badge info" to={mfgPaths.apsRun(r.parent_run_id)} title={tr("mfg.apsRunShell.attr.createdByManualEditsOf")}>
              <Icon name="copy" /> {t("mfg.apsRunShell.btn.editedCopy")}
            </Link>
          ) : null}
          <span className="muted small">
            {tr("mfg.apsRunShell.text.fromBy", { asof: clock.dateTime(r.as_of), zoneLabel: clock.zoneLabel, v: r.mrp_run ? ` · ${tr("common.mrpRunNo", { n: r.mrp_run.run_no })}` : "", fmtTimestamp: fmtTimestamp(r.finished_at ?? r.started_at), name: r.actor.name })}
          </span>
        </div>
        <div className="mfg-actions">
          {isActive(r) ? (
            <>
              <ApsProgress run={r} />
              {canRun ? (
                <button type="button" className="btn" onClick={() => void cancel()} disabled={busy} data-testid="aps-cancel">
                  <Icon name="stop" /> {t("mfg.apsRunShell.btn.cancel")}
                </button>
              ) : null}
            </>
          ) : (
            <>
              <PublishButton run={r} onDone={(x) => run.setData(x)} />
              {done ? (
                <>
                  <button type="button" className="btn" onClick={() => void exp("xlsx")} data-testid="aps-export">
                    <Icon name="download" /> {t("mfg.apsRunShell.btn.exportExcel")}
                  </button>
                  <button type="button" className="btn" onClick={() => void exp("zip")}>
                    <Icon name="download" /> {t("mfg.apsRunShell.btn.exportCsvZip")}
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
          title={t("mfg.apsRunShell.title.theDataChangedAfterThis")}
          testId="aps-stale-banner"
          actions={
            <Link className="btn sm" to={mfgPaths.schedule()}>
              <Icon name="refresh" /> {t("mfg.apsRunShell.btn.newSchedule")}
            </Link>
          }
        >
          {tr("mfg.apsRunShell.text.changedThePlanIsStill", { v: [r.stale.master_changed ? tr("mfg.apsRunShell.str.masterDataRoutingsLinesShifts") : "", r.stale.transactions_changed ? tr("mfg.apsRunShell.str.ordersStockOrProgress") : ""].filter(Boolean).join(" and ") ||
            tr("mfg.apsRunShell.str.inputs"), v2: " " })}
        </Banner>
      ) : null}
      {r.kind === "what_if" ? (
        <Banner tone="info" icon="help" title={t("mfg.apsRunShell.title.whatifScenario")}>
          {tr("mfg.apsRunShell.text.forComparisonOnlyItCannot")}
        </Banner>
      ) : null}
      {r.status === "failed" ? <Banner tone="danger" title={t("mfg.apsRunShell.title.thisRunFailed")}>{r.error?.message ?? tr("mfg.apsRunShell.str.unexpectedError")}</Banner> : null}
      {r.status === "cancelled" ? (
        <Banner tone="warn" title={t("mfg.apsRunShell.title.cancelled")}>
          {r.summary ? tr("mfg.apsRunShell.str.theBestPlanFoundBefore") : tr("mfg.apsRunShell.str.noPlanWasFinishedBefore")}
        </Banner>
      ) : null}
      {r.status === "completed" && r.validation && !r.validation.ok ? (
        <Banner tone="danger" icon="x" title={t("mfg.apsRunShell.title.thisPlanBreaksHardRules")} testId="aps-invalid-banner">
          {r.summary?.violations ? tr("mfg.apsRunShell.tpl.ruleViolations", { violations: r.summary.violations }) : null}
          {(r.validation.violations ?? []).slice(0, 5).map((v, i) => (
            <div key={i}>
              <code>{v.code}</code> {v.message}
            </div>
          ))}
        </Banner>
      ) : null}
      <RerunAllowBanner run={r} />
      <nav className="tabs" aria-label={t("mfg.apsRunShell.aria.scheduleSections")}>
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
            <span>{tr("mfg.apsRunShell.text.theScheduleIsBeingCalculated")}</span>
          </div>
        ) : done ? (
          <Outlet key={r.id} context={ctx} />
        ) : null}
      </div>
    </div>
  );
}
