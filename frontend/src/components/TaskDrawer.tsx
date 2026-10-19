import { useEffect, useRef } from "react";
import { Link } from "react-router";
import type { PlacementOut, Problem, Schedule, StartReasonCode } from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDuration, fmtIso, isoToMs, offsetMinutesOf } from "../lib/time";
import { Icon, type IconName } from "./Icon";
import { StatusBadge } from "./StatusBadge";
import { Term } from "./Term";

const REASON_ICON: Record<StartReasonCode, IconName> = {
  LOCKED: "lock",
  HORIZON_START: "play",
  EARLIEST_START: "clock",
  DEPENDENCY: "graph",
  RESOURCE_BUSY: "layers",
  CALENDAR: "calendar",
  OPTIMIZER_CHOICE: "settings",
  NOT_SCHEDULED: "ban",
};

export function TaskDrawer({
  schedule,
  placement,
  draft,
  terms,
  onClose,
  onLock,
  onUnlock,
  onSelectTask,
  lockBusy,
}: {
  schedule: Schedule;
  placement: PlacementOut | null;
  taskId: string;
  draft: Problem;
  terms: Terms;
  onClose(): void;
  onLock(p: PlacementOut): void;
  onUnlock(taskId: string): void;
  onSelectTask(id: string): void;
  lockBusy: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const taskId = placement?.task_id ?? "";
  const task = draft.tasks.find((t) => t.id === taskId);
  const ex = schedule.explanation?.tasks[taskId];
  const off = offsetMinutesOf(schedule.horizon_start);
  const resName = (id: string) => draft.resources.find((r) => r.id === id)?.name ?? id;
  const taskName = (id: string) => draft.tasks.find((t) => t.id === id)?.name ?? id;
  const violations = schedule.violations.filter((v) => v.task_ids.includes(taskId));

  useEffect(() => {
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, taskId]);

  if (!placement) return null;
  const lockedHere =
    !!task?.locked && isoToMs(task.locked.start) === isoToMs(placement.start_at);
  const deadlineStatus = ex?.deadline_status ?? "none";

  return (
    <aside className="drawer" role="dialog" aria-modal="false" aria-labelledby="drawer-title" data-testid="task-drawer" tabIndex={-1} ref={ref}>
      <div className="drawer-header">
        <div className="grow">
          <div className="small muted">{task?.type === "milestone" ? terms.milestone : terms.task} · <span className="mono">{taskId}</span></div>
          <h2 id="drawer-title">{task?.name ?? taskId}</h2>
        </div>
        <button className="btn ghost icon" onClick={onClose} aria-label="Close details">
          <Icon name="x" />
        </button>
      </div>
      <div className="drawer-body">
        <div className="row wrap">
          {deadlineStatus === "late_soft" || deadlineStatus === "late_hard" ? (
            <StatusBadge kind="late" label={`Late by ${fmtDuration(ex?.lateness_minutes ?? 0)}${deadlineStatus === "late_hard" ? " (hard)" : ""}`} />
          ) : deadlineStatus === "on_time" ? (
            <StatusBadge kind="on_time" />
          ) : null}
          {ex?.on_critical_chain ? <span className="badge accent"><Icon name="flag" /> Critical chain</span> : null}
          {task?.locked ? <span className="badge info"><Icon name="lock" /> Fixed</span> : null}
        </div>
        <dl className="dl">
          <dt>Starts</dt>
          <dd>{fmtIso(placement.start_at, off)}</dd>
          <dt>Ends</dt>
          <dd>{fmtIso(placement.end_at, off)}</dd>
          <dt>Duration</dt>
          <dd>{fmtDuration(placement.end - placement.start)}</dd>
          {task?.duration_estimate && task.type !== "milestone" ? (
            <>
              <dt>
                Duration range <Term k="duration_range" bare />
              </dt>
              <dd data-testid="drawer-duration-range">
                {fmtDuration(task.duration_estimate.optimistic_minutes)} to {fmtDuration(task.duration_estimate.pessimistic_minutes)}, most likely{" "}
                {fmtDuration(task.duration_estimate.likely_minutes)}; planned with the{" "}
                <Term k="expected_duration">expected duration</Term> {fmtDuration(task.duration_minutes)}
              </dd>
            </>
          ) : null}
          <dt>{terms.resources}</dt>
          <dd>{placement.resource_ids.length ? placement.resource_ids.map(resName).join(", ") : <span className="faint">none</span>}</dd>
          {task?.deadline ? (
            <>
              <dt>{terms.deadline}</dt>
              <dd>
                {fmtIso(task.deadline, off)} {task.deadline_hard ? <span className="chip">must be met</span> : null}
              </dd>
            </>
          ) : null}
          {ex ? (
            <>
              <dt>Slack</dt>
              <dd>{ex.cpm_critical ? "None (critical in the dependency network)" : fmtDuration(ex.cpm_slack_minutes)}</dd>
            </>
          ) : null}
        </dl>

        <section>
          <h3 className="mb">Why it starts then</h3>
          {ex?.reasons.length ? (
            <ul className="col" style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {ex.reasons.map((r, i) => (
                <li key={i} className="row" style={{ alignItems: "flex-start" }}>
                  <Icon name={REASON_ICON[r.code] ?? "info"} style={{ marginTop: 2, flex: "0 0 auto" }} />
                  <div>
                    <div>{r.message}</div>
                    {r.related_task_ids.length ? (
                      <div className="row wrap small" style={{ gap: 4, marginTop: 2 }}>
                        {r.related_task_ids.map((id) => (
                          <button key={id} className="btn ghost sm" onClick={() => onSelectTask(id)}>
                            {taskName(id)}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="small muted">No explanation available.</div>
          )}
        </section>

        {violations.length ? (
          <section>
            <h3 className="mb">Problems</h3>
            {violations.map((v, i) => (
              <div key={i} className="small row" style={{ alignItems: "flex-start", marginBottom: 6 }}>
                <span className={`badge ${v.severity === "hard" ? "danger" : "warn"}`}>
                  <Icon name={v.severity === "hard" ? "x" : "clock"} />
                  {v.severity === "hard" ? "Rule" : "Late"}
                </span>
                <span>{v.message}</span>
              </div>
            ))}
          </section>
        ) : null}

        <section className="col">
          <h3>Adjust</h3>
          {task ? (
            lockedHere ? (
              <button className="btn" onClick={() => onUnlock(taskId)} disabled={lockBusy}>
                <Icon name="unlock" /> Unlock
              </button>
            ) : (
              <button className="btn" onClick={() => onLock(placement)} disabled={lockBusy} data-testid="lock-at-time">
                {lockBusy ? <span className="spinner" aria-hidden /> : <Icon name="lock" />}
                Lock at this time
              </button>
            )
          ) : (
            <div className="small muted">This {terms.taskL} no longer exists in the plan.</div>
          )}
          <span className="small faint">
            Locking fixes the start{placement.resource_ids.length ? ` and the ${terms.resourcesL}` : ""} in the plan, so the next optimization keeps it.
          </span>
          {task ? (
            <Link className="btn ghost sm" to={`../tasks?focus=${encodeURIComponent(taskId)}`} style={{ alignSelf: "flex-start" }}>
              Edit {terms.taskL} <Icon name="arrow-right" />
            </Link>
          ) : null}
        </section>
      </div>
    </aside>
  );
}
