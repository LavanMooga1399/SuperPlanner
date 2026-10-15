import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, approveSchedule, errorMessage, getSchedule, listSchedules, scheduleCsvUrl } from "../../api/client";
import type { Issue, PlacementOut, Schedule, ScheduleSummary, Violation } from "../../api/types";
import { Banner, ErrorBanner, Loading } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Gantt, ZOOM_LEVELS, type GanttMode } from "../../components/Gantt";
import { Icon } from "../../components/Icon";
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

export function pickDefaultSchedule(items: ScheduleSummary[]): ScheduleSummary | null {
  return items.find((s) => s.status === "approved") ?? items.find((s) => s.rank === 0) ?? items[0] ?? null;
}

export function scheduleOptionLabel(s: ScheduleSummary): string {
  const status = s.status === "approved" ? "Approved" : s.status === "superseded" ? "Superseded" : "Candidate";
  return `${s.label} · ${status} · ${fmtLocal(s.created_at)}`;
}

function approveBlockReason(s: Schedule, terms: ReturnType<typeof useTerms>): string | null {
  if (s.status === "approved") return null;
  if (s.status === "superseded") return `A newer ${terms.scheduleL} was approved after this one; superseded ${terms.scheduleL}s cannot be approved again.`;
  if (s.feasibility === "unknown") return `This ${terms.scheduleL} breaks ${s.hard_violation_count} rule${s.hard_violation_count === 1 ? "" : "s"}; no valid ${terms.scheduleL} was found in time.`;
  if (s.feasibility === "infeasible") return `This plan cannot be scheduled without breaking a rule.`;
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
          ? `Approved. The previously approved ${terms.scheduleL} is now superseded.`
          : `Approved.`,
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

  if (list.loading && !list.data) return <Loading label={`Loading ${terms.scheduleL}s…`} />;
  if (list.error) return <ErrorBanner error={list.error} onRetry={list.reload} />;
  if (!items.length && !requestedId)
    return (
      <div className="card empty">
        <Icon name="calendar" size={32} />
        <strong>No {terms.scheduleL} yet</strong>
        <span>Run the optimizer to create one.</span>
        <Link className="btn primary" to="../optimize">
          <Icon name="play" /> Optimize
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
              by {methodLabel(schedule.solver)}
            </span>
          </>
        ) : null}
        <div className="grow" />
        {schedule ? (
          <>
            <a className="btn" href={scheduleCsvUrl(schedule.id)} download data-testid="export-csv">
              <Icon name="download" /> Export CSV
            </a>
            {approved && approved.id !== schedule.id ? (
              <Link className="btn" to={`../compare?a=${encodeURIComponent(approved.id)}&b=${encodeURIComponent(schedule.id)}`}>
                <Icon name="compare" /> Compare with approved
              </Link>
            ) : null}
            <button className="btn" onClick={() => setReplanOpen(true)} disabled={schedule.feasibility !== "feasible"} title={schedule.feasibility !== "feasible" ? "Only valid schedules can be the base of a replan" : undefined}>
              <Icon name="refresh" /> Replan…
            </button>
            <button
              className="btn primary"
              data-testid="approve-button"
              disabled={!!blockReason || schedule.status === "approved" || approving}
              title={blockReason ?? (schedule.status === "approved" ? "Already approved" : undefined)}
              aria-describedby={blockReason ? "approve-reason" : undefined}
              onClick={() => setConfirm(true)}
            >
              <Icon name="check" /> {schedule.status === "approved" ? "Approved" : "Approve"}
            </button>
          </>
        ) : null}
      </div>

      {loadError ? <ErrorBanner error={loadError} onRetry={() => current && void loadSchedule(current)} /> : null}
      {loading && !schedule ? <Loading label={`Loading ${terms.scheduleL}…`} /> : null}

      {schedule ? (
        <>
          {schedule.status === "approved" ? (
            <Banner tone="ok" icon="star" testId="approval-banner" title={`Approved on ${fmtLocal(schedule.approved_at)}`}>
              This is the {terms.scheduleL} in effect{schedule.approved_problem_version ? ` (approved against plan version ${schedule.approved_problem_version})` : ""}.
            </Banner>
          ) : schedule.status === "superseded" ? (
            <Banner tone="info" icon="refresh" testId="approval-banner" title={`Superseded on ${fmtLocal(schedule.superseded_at)}`}>
              A newer {terms.scheduleL} was approved. This one is kept for reference.
            </Banner>
          ) : (
            <Banner tone="accent" icon="info" testId="approval-banner" title="Candidate - not yet approved">
              {approved ? `The approved ${terms.scheduleL} stays in effect until you approve this one.` : `Nothing is approved yet for this plan.`}
            </Banner>
          )}
          {blockReason ? (
            <Banner tone="danger" role="status" title="Cannot be approved">
              <span id="approve-reason">{blockReason}</span>
            </Banner>
          ) : null}
          {stale && schedule.status !== "superseded" ? (
            <Banner tone="warn" title={`This ${terms.scheduleL} was made for version ${schedule.base_problem_version}; the plan is now version ${record.version}.`}>
              Approval re-checks it against the current plan and is refused if the changes break it.
            </Banner>
          ) : null}
          {notice ? <Banner tone="ok" title={notice} actions={<button className="btn sm ghost" onClick={() => setNotice(null)}>Dismiss</button>} /> : null}
          {approveError ? (
            <Banner tone="danger" role="alert" title="Approval refused">
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
              {schedule.explanation.summary.map((s, i) => (
                <div key={i} className="row" style={{ alignItems: "flex-start" }}>
                  <Icon name="info" style={{ marginTop: 2 }} /> {s}
                </div>
              ))}
            </div>
          ) : null}

          <ViolationsPanel violations={schedule.violations} open={violationsOpen} onToggle={() => setViolationsOpen(!violationsOpen)} onSelectTask={setSelected} />

          <div className="toolbar" style={{ marginBottom: 0 }}>
            <div className="btn-group" role="group" aria-label="Timeline view">
              <button className="btn sm" aria-pressed={mode === "tasks"} onClick={() => setMode("tasks")}>
                <Icon name="list" /> {terms.tasks}
              </button>
              <button className="btn sm" aria-pressed={mode === "resources"} onClick={() => setMode("resources")}>
                <Icon name="layers" /> {terms.resources}
              </button>
            </div>
            <div className="btn-group" role="group" aria-label="Zoom">
              <button className="btn sm icon" aria-label="Zoom out" disabled={zoom <= ZOOM_LEVELS[0]} onClick={() => setZoom(ZOOM_LEVELS[Math.max(0, ZOOM_LEVELS.indexOf(zoom) - 1)] ?? 8)}>
                <Icon name="zoom-out" />
              </button>
              <button className="btn sm" disabled aria-label={`Zoom ${zoom} pixels per hour`} style={{ opacity: 1, minWidth: 64 }}>
                {zoom} px/h
              </button>
              <button className="btn sm icon" aria-label="Zoom in" disabled={zoom >= ZOOM_LEVELS[ZOOM_LEVELS.length - 1]} onClick={() => setZoom(ZOOM_LEVELS[Math.min(ZOOM_LEVELS.length - 1, ZOOM_LEVELS.indexOf(zoom) + 1)] ?? 8)}>
                <Icon name="zoom-in" />
              </button>
            </div>
            <label className="checkbox small">
              <input type="checkbox" checked={arrows} onChange={(e) => setArrows(e.target.checked)} /> Dependencies
            </label>
            <label className="checkbox small">
              <input type="checkbox" checked={shading} onChange={(e) => setShading(e.target.checked)} /> Closed times
            </label>
            <div className="grow" />
            <span className="small muted">Times shown in {offsetLabel(off)}</span>
          </div>
          <div className="legend">
            <span className="legend-item"><span className="swatch" style={{ background: "var(--bar)" }} /> Scheduled</span>
            <span className="legend-item"><span className="swatch" style={{ background: "var(--bar-crit)", outline: "1.5px solid var(--text)" }} /> Critical chain</span>
            <span className="legend-item"><span className="swatch" style={{ background: "repeating-linear-gradient(45deg, var(--warn) 0 3px, #fff8 3px 5px)" }} /> Late</span>
            <span className="legend-item"><span className="swatch" style={{ border: "1.5px dashed var(--danger)" }} /> Rule broken</span>
            <span className="legend-item"><span style={{ color: "var(--warn)" }}>◆</span> {terms.deadline}</span>
            <span className="legend-item"><span style={{ color: "var(--danger)" }}>◆</span> Hard {terms.deadlineL}</span>
            <span className="legend-item"><span className="swatch" style={{ background: "var(--shade)" }} /> Closed</span>
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
            <div className="card empty">This {terms.scheduleL} has no placed {terms.tasksL}.</div>
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
          title={`Approve this ${terms.scheduleL}?`}
          confirmLabel="Approve"
          busy={approving}
          onCancel={() => setConfirm(false)}
          onConfirm={doApprove}
        >
          <p style={{ margin: 0 }}>
            “{schedule.label}” becomes the {terms.scheduleL} in effect.
          </p>
          {approved && approved.id !== schedule.id ? (
            <p style={{ margin: 0 }}>
              It replaces the currently approved “{approved.label}” from {fmtLocal(approved.approved_at)}, which will be marked as superseded.
            </p>
          ) : null}
          {stale ? <p className="small muted" style={{ margin: 0 }}>The plan changed since this {terms.scheduleL} was made; it will be re-checked first.</p> : null}
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
