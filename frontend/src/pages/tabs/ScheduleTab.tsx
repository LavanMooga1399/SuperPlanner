import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiError, approveSchedule, errorMessage, getSchedule, listSchedules, scheduleCsvUrl } from "../../api/client";
import type { Issue, PlacementOut, Schedule, ScheduleSummary, Violation } from "../../api/types";
import { Banner, ErrorBanner, Loading } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Gantt, ZOOM_LEVELS, type GanttMode } from "../../components/Gantt";
import { Icon } from "../../components/Icon";
import { Term } from "../../components/Term";
import { KpiCards } from "../../components/KpiCards";
import { ReplanDialog } from "../../components/ReplanDialog";
import { methodLabel } from "../../components/RunProgress";
import { StatusBadge } from "../../components/StatusBadge";
import { TaskDrawer } from "../../components/TaskDrawer";
import { ViolationsPanel } from "../../components/ViolationsPanel";
import { updateTask } from "../../lib/planEdit";
import { useTerms } from "../../lib/terms";
import { fmtLocal, offsetLabel, offsetMinutesOf } from "../../lib/time";
import { useAsync, useStoredState } from "../../lib/useAsync";
import { useLoadedPlan } from "../../state/PlanContext";
import { plural, t, t as tr } from "../../lib/i18n";

export function pickDefaultSchedule(items: ScheduleSummary[]): ScheduleSummary | null {
  return items.find((s) => s.status === "approved") ?? items.find((s) => s.rank === 0) ?? items[0] ?? null;
}

export function scheduleOptionLabel(s: ScheduleSummary): string {
  const status = s.status === "approved" ? tr("studio.scheduleTab.str.approved") : s.status === "superseded" ? tr("studio.scheduleTab.str.superseded") : tr("studio.scheduleTab.str.candidate");
  return `${s.label} · ${status} · ${fmtLocal(s.created_at)}`;
}

function approveBlockReason(s: Schedule, terms: ReturnType<typeof useTerms>): string | null {
  if (s.status === "approved") return null;
  if (s.status === "superseded") return tr("studio.scheduleTab.tpl.aNewerWasApprovedAfter", { scheduleL: terms.scheduleL, scheduleL2: terms.scheduleL });
  if (s.feasibility === "unknown") return tr("studio.scheduleTab.tpl.thisBreaksNoValidWas", { scheduleL: terms.scheduleL, hardviolationcount: plural(s.hard_violation_count, "rule"), scheduleL2: terms.scheduleL });
  if (s.feasibility === "infeasible") return tr("studio.scheduleTab.str.thisPlanCannotBeScheduled");
  return null;
}

export function ScheduleTab() {
  const plan = useLoadedPlan();
  const { draft, record } = plan;
  const terms = useTerms();
  const [params, setParams] = useSearchParams();
  const list = useAsync((s) => listSchedules(plan.planId, undefined, s), [plan.planId]);
  const requestedId = params.get("id");
  const items = list.data?.items ?? [];
  const current = requestedId ?? pickDefaultSchedule(items)?.id ?? null;

  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useStoredState<GanttMode>("sp.gantt.mode", "tasks");
  const [zoom, setZoom] = useStoredState("sp.gantt.zoom", 16);
  const [arrows, setArrows] = useStoredState("sp.gantt.arrows", true);
  const [shading, setShading] = useStoredState("sp.gantt.shading", true);
  const [selected, setSelected] = useState<string | null>(null);
  const [violationsOpen, setViolationsOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<{ message: string; violations: Violation[]; issues: Issue[] } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [replanOpen, setReplanOpen] = useState(false);
  const [lockBusy, setLockBusy] = useState(false);

  const loadSchedule = useCallback(
    async (id: string, signal?: AbortSignal) => {
      setLoading(true);
      setLoadError(null);
      try {
        const s = await getSchedule(id, signal);
        setSchedule(s);
        setViolationsOpen(s.feasibility !== "feasible");
      } catch (err) {
        if (!(err instanceof DOMException)) setLoadError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!current) return;
    const ac = new AbortController();
    setSelected(null);
    setApproveError(null);
    void loadSchedule(current, ac.signal);
    return () => ac.abort();
  }, [current, loadSchedule]);

  const approved = items.find((s) => s.status === "approved") ?? null;
  const blockReason = schedule ? approveBlockReason(schedule, terms) : null;
  const stale = schedule ? schedule.base_problem_version !== record.version : false;
  const off = offsetMinutesOf(schedule?.horizon_start ?? draft.horizon_start);

  const doApprove = async () => {
    if (!schedule) return;
    setApproving(true);
    setApproveError(null);
    try {
      const res = await approveSchedule(schedule.id);
      setConfirm(false);
      setNotice(
        res.superseded_schedule_id
          ? tr("studio.scheduleTab.tpl.approvedThePreviouslyApprovedIs", { scheduleL: terms.scheduleL })
          : tr("studio.scheduleTab.str.approved2"),
      );
      list.reload();
      await loadSchedule(schedule.id);
    } catch (err) {
      setConfirm(false);
      if (err instanceof ApiError) {
        setApproveError({
          message: err.message,
          violations: (err.details.violations as Violation[] | undefined) ?? [],
          issues: (err.details.issues as Issue[] | undefined) ?? [],
        });
      } else setApproveError({ message: errorMessage(err), violations: [], issues: [] });
    } finally {
      setApproving(false);
    }
  };

  const placementById = useMemo(() => new Map(schedule?.placements.map((p) => [p.task_id, p]) ?? []), [schedule]);

  const lockAt = async (p: PlacementOut) => {
    setLockBusy(true);
    plan.update((doc) =>
      updateTask(doc, p.task_id, (t) => ({
        ...t,
        locked: {
          start: p.start_at,
          resource_ids: p.resource_ids.length && p.resource_ids.length === t.requirements.length ? p.resource_ids : null,
        },
      })),
    );
    await plan.save();
    setLockBusy(false);
  };
  const unlock = async (taskId: string) => {
    setLockBusy(true);
    plan.update((doc) => updateTask(doc, taskId, (t) => ({ ...t, locked: null })));
    await plan.save();
    setLockBusy(false);
  };

  if (list.loading && !list.data) return <Loading label={tr("studio.scheduleTab.tpl.loadingS", { scheduleL: terms.scheduleL })} />;
  if (list.error) return <ErrorBanner error={list.error} onRetry={list.reload} />;
  if (!items.length && !requestedId)
    return (
      <div className="card empty">
        <Icon name="calendar" size={32} />
        <strong>{tr("studio.scheduleTab.text.noYet", { scheduleL: terms.scheduleL })}</strong>
        <span>{tr("studio.scheduleTab.text.runTheOptimizerToCreate")}</span>
        <Link className="btn primary" to="../optimize">
          <Icon name="play" /> {t("studio.scheduleTab.btn.optimize")}
        </Link>
      </div>
    );

  return (
    <div className="col gap-lg">
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <div className="field" style={{ minWidth: 260, maxWidth: 420 }}>
          <label htmlFor="schedule-pick" className="sr-only">{terms.schedule}</label>
          <select id="schedule-pick" className="select" value={current ?? ""} onChange={(e) => setParams({ id: e.target.value })}>
            {current && !items.some((s) => s.id === current) ? <option value={current}>{current}</option> : null}
            {items.map((s) => (
              <option key={s.id} value={s.id}>
                {scheduleOptionLabel(s)}
              </option>
            ))}
          </select>
        </div>
        {schedule ? (
          <>
            <span data-testid="schedule-status" data-status={schedule.status} className="row">
              <StatusBadge kind={schedule.status} />
              <StatusBadge kind={schedule.feasibility} />
            </span>
            <span className="small muted" title={schedule.solver}>
              {tr("studio.scheduleTab.text.by", { solver: methodLabel(schedule.solver) })}
            </span>
          </>
        ) : null}
        <div className="grow" />
        {schedule ? (
          <>
            <a className="btn" href={scheduleCsvUrl(schedule.id)} download data-testid="export-csv">
              <Icon name="download" /> {t("studio.scheduleTab.btn.exportCsv")}
            </a>
            {approved && approved.id !== schedule.id ? (
              <Link className="btn" to={`../compare?a=${encodeURIComponent(approved.id)}&b=${encodeURIComponent(schedule.id)}`}>
                <Icon name="compare" /> {t("studio.scheduleTab.btn.compareWithApproved")}
              </Link>
            ) : null}
            <button className="btn" onClick={() => setReplanOpen(true)} disabled={schedule.feasibility !== "feasible"} title={schedule.feasibility !== "feasible" ? tr("studio.scheduleTab.str.onlyValidSchedulesCanBe") : undefined}>
              <Icon name="refresh" /> {t("studio.scheduleTab.btn.replan")}
            </button>
            <button
              className="btn primary"
              data-testid="approve-button"
              disabled={!!blockReason || schedule.status === "approved" || approving}
              title={blockReason ?? (schedule.status === "approved" ? tr("studio.scheduleTab.str.alreadyApproved") : undefined)}
              aria-describedby={blockReason ? "approve-reason" : undefined}
              onClick={() => setConfirm(true)}
            >
              <Icon name="check" /> {schedule.status === "approved" ? tr("studio.scheduleTab.str.approved") : tr("studio.scheduleTab.str.approve")}
            </button>
          </>
        ) : null}
      </div>

      {loadError ? <ErrorBanner error={loadError} onRetry={() => current && void loadSchedule(current)} /> : null}
      {loading && !schedule ? <Loading label={tr("studio.scheduleTab.tpl.loading", { scheduleL: terms.scheduleL })} /> : null}

      {schedule ? (
        <>
          {schedule.status === "approved" ? (
            <Banner tone="ok" icon="star" testId="approval-banner" title={tr("studio.scheduleTab.tpl.approvedOn", { approvedat: fmtLocal(schedule.approved_at) })}>
              {tr("studio.scheduleTab.text.thisIsTheInEffect", { scheduleL: terms.scheduleL, v: schedule.approved_problem_version ? tr("studio.scheduleTab.tpl.approvedAgainstPlanVersion", { approvedproblemversion: schedule.approved_problem_version }) : "" })}
            </Banner>
          ) : schedule.status === "superseded" ? (
            <Banner tone="info" icon="refresh" testId="approval-banner" title={tr("studio.scheduleTab.tpl.supersededOn", { supersededat: fmtLocal(schedule.superseded_at) })}>
              {tr("studio.scheduleTab.text.aNewerWasApprovedThis", { scheduleL: terms.scheduleL })}
            </Banner>
          ) : (
            <Banner tone="accent" icon="info" testId="approval-banner" title={t("studio.scheduleTab.title.candidateNotYetApproved")}>
              {approved ? tr("studio.scheduleTab.tpl.theApprovedStaysInEffect", { scheduleL: terms.scheduleL }) : tr("studio.scheduleTab.str.nothingIsApprovedYetFor")}
            </Banner>
          )}
          {blockReason ? (
            <Banner tone="danger" role="status" title={t("studio.scheduleTab.title.cannotBeApproved")}>
              <span id="approve-reason">{blockReason}</span>
            </Banner>
          ) : null}
          {stale && schedule.status !== "superseded" ? (
            <Banner tone="warn" title={tr("studio.scheduleTab.tpl.thisWasMadeForVersion", { scheduleL: terms.scheduleL, baseproblemversion: schedule.base_problem_version, version: record.version })}>
              {tr("studio.scheduleTab.text.approvalReChecksItAgainst")}
            </Banner>
          ) : null}
          {notice ? <Banner tone="ok" title={notice} actions={<button className="btn sm ghost" onClick={() => setNotice(null)}>{tr("studio.scheduleTab.text.dismiss")}</button>} /> : null}
          {approveError ? (
            <Banner tone="danger" role="alert" title={t("studio.scheduleTab.title.approvalRefused")}>
              <div>{approveError.message}</div>
              {[...approveError.violations.map((v) => v.message), ...approveError.issues.map((i) => i.message)].length ? (
                <ul className="small" style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {approveError.violations.map((v, i) => <li key={`v${i}`}>{v.message}</li>)}
                  {approveError.issues.map((v, i) => <li key={`i${i}`}>{v.message}</li>)}
                </ul>
              ) : null}
            </Banner>
          ) : null}

          <KpiCards schedule={schedule} terms={terms} currency={draft.currency} />

          {schedule.explanation?.summary.length ? (
            <div className="card card-body small">
              {schedule.explanation.summary.filter((s) => s !== schedule.explanation?.duration_risk?.message).map((s, i) => (
                <div key={i} className="row" style={{ alignItems: "flex-start" }}>
                  <Icon name="info" style={{ marginTop: 2 }} /> {s}
                </div>
              ))}
              {schedule.explanation.duration_risk ? (
                <div className="row" style={{ alignItems: "flex-start" }} data-testid="duration-risk">
                  <Icon name="clock" style={{ marginTop: 2 }} />
                  <span>
                    {schedule.explanation.duration_risk.message} <Term k="duration_range" bare />
                  </span>
                </div>
              ) : null}
            </div>
          ) : null}

          <ViolationsPanel violations={schedule.violations} open={violationsOpen} onToggle={() => setViolationsOpen(!violationsOpen)} onSelectTask={setSelected} />

          <div className="toolbar" style={{ marginBottom: 0 }}>
            <div className="btn-group" role="group" aria-label={t("studio.scheduleTab.aria.timelineView")}>
              <button className="btn sm" aria-pressed={mode === "tasks"} onClick={() => setMode("tasks")}>
                <Icon name="list" /> {terms.tasks}
              </button>
              <button className="btn sm" aria-pressed={mode === "resources"} onClick={() => setMode("resources")}>
                <Icon name="layers" /> {terms.resources}
              </button>
            </div>
            <div className="btn-group" role="group" aria-label={t("studio.scheduleTab.aria.zoom")}>
              <button className="btn sm icon" aria-label={t("studio.scheduleTab.aria.zoomOut")} disabled={zoom <= ZOOM_LEVELS[0]} onClick={() => setZoom(ZOOM_LEVELS[Math.max(0, ZOOM_LEVELS.indexOf(zoom) - 1)] ?? 8)}>
                <Icon name="zoom-out" />
              </button>
              <button className="btn sm" disabled aria-label={tr("studio.scheduleTab.tpl.zoomPixelsPerHour", { zoom: zoom })} style={{ opacity: 1, minWidth: 64 }}>
                {zoom} px/h
              </button>
              <button className="btn sm icon" aria-label={t("studio.scheduleTab.aria.zoomIn")} disabled={zoom >= ZOOM_LEVELS[ZOOM_LEVELS.length - 1]} onClick={() => setZoom(ZOOM_LEVELS[Math.min(ZOOM_LEVELS.length - 1, ZOOM_LEVELS.indexOf(zoom) + 1)] ?? 8)}>
                <Icon name="zoom-in" />
              </button>
            </div>
            <label className="checkbox small">
              <input type="checkbox" checked={arrows} onChange={(e) => setArrows(e.target.checked)} />{" "}{tr("studio.scheduleTab.text.dependencies")}
            </label>
            <label className="checkbox small">
              <input type="checkbox" checked={shading} onChange={(e) => setShading(e.target.checked)} />{" "}{tr("studio.scheduleTab.text.closedTimes")}
            </label>
            <div className="grow" />
            <span className="small muted">{tr("studio.scheduleTab.text.timesShownIn", { off: offsetLabel(off) })}</span>
          </div>
          <div className="legend">
            <span className="legend-item"><span className="swatch" style={{ background: "var(--bar)" }} />{" "}{tr("studio.scheduleTab.text.scheduled")}</span>
            <span className="legend-item"><span className="swatch" style={{ background: "var(--bar-crit)", outline: "1.5px solid var(--text)" }} /> <Term k="critical_chain">{tr("studio.scheduleTab.text.criticalChain")}</Term></span>
            <span className="legend-item"><span className="swatch" style={{ background: "repeating-linear-gradient(45deg, var(--warn) 0 3px, #fff8 3px 5px)" }} />{" "}{tr("studio.scheduleTab.text.late")}</span>
            <span className="legend-item"><span className="swatch" style={{ border: "1.5px dashed var(--danger)" }} />{" "}{tr("studio.scheduleTab.text.ruleBroken")}</span>
            <span className="legend-item"><span style={{ color: "var(--warn)" }}>◆</span> {terms.deadline} <Term k="soft_deadline" bare /></span>
            <span className="legend-item"><span style={{ color: "var(--danger)" }}>◆</span>{" "}{tr("studio.scheduleTab.text.hard", { deadlineL: terms.deadlineL })}{" "}<Term k="hard_deadline" bare /></span>
            <span className="legend-item"><span className="swatch" style={{ background: "var(--shade)" }} />{" "}{tr("studio.scheduleTab.text.closed")}</span>
            {draft.tasks.some((t) => t.duration_estimate && t.type !== "milestone") ? (
              <span className="legend-item"><span aria-hidden style={{ color: "var(--text-muted)", letterSpacing: -1 }}>- - -|</span>{" "}{tr("studio.scheduleTab.text.couldTakeUpToIts")}{" "}<Term k="duration_range" bare /></span>
            ) : null}
          </div>
          {schedule.placements.length ? (
            <Gantt
              schedule={schedule}
              draft={draft}
              terms={terms}
              mode={mode}
              pxPerHour={ZOOM_LEVELS.includes(zoom) ? zoom : 8}
              showArrows={arrows}
              showShading={shading}
              selected={selected}
              onSelect={setSelected}
            />
          ) : (
            <div className="card empty">{tr("studio.scheduleTab.text.thisHasNoPlaced", { scheduleL: terms.scheduleL, tasksL: terms.tasksL })}</div>
          )}
        </>
      ) : null}

      {schedule && selected ? (
        <TaskDrawer
          schedule={schedule}
          placement={placementById.get(selected) ?? null}
          taskId={selected}
          draft={draft}
          terms={terms}
          onClose={() => setSelected(null)}
          onLock={lockAt}
          onUnlock={unlock}
          onSelectTask={setSelected}
          lockBusy={lockBusy}
        />
      ) : null}

      {confirm && schedule ? (
        <ConfirmDialog
          title={tr("studio.scheduleTab.tpl.approveThis", { scheduleL: terms.scheduleL })}
          confirmLabel={t("studio.scheduleTab.btn.approve")}
          busy={approving}
          onCancel={() => setConfirm(false)}
          onConfirm={doApprove}
        >
          <p style={{ margin: 0 }}>
            {tr("studio.scheduleTab.text.becomesTheInEffect", { label: schedule.label, scheduleL: terms.scheduleL })}
          </p>
          {approved && approved.id !== schedule.id ? (
            <p style={{ margin: 0 }}>
              {tr("studio.scheduleTab.text.itReplacesTheCurrentlyApproved", { label: approved.label, approvedat: fmtLocal(approved.approved_at) })}
            </p>
          ) : null}
          {stale ? <p className="small muted" style={{ margin: 0 }}>{tr("studio.scheduleTab.text.thePlanChangedSinceThis", { scheduleL: terms.scheduleL })}</p> : null}
        </ConfirmDialog>
      ) : null}

      {replanOpen && schedule ? (
        <ReplanDialog
          schedule={schedule}
          draft={draft}
          version={record.version}
          terms={terms}
          onClose={() => setReplanOpen(false)}
          beforeSubmit={async () => ((await plan.save()) ? plan.getVersion() : null)}
          afterSubmit={async () => {
            await plan.refreshRecord();
          }}
        />
      ) : null}
    </div>
  );
}
