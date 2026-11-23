import { useEffect, useRef } from "react";
import { Link } from "react-router";
import type { PlacementOut, Problem, Schedule, StartReasonCode } from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDuration, fmtIso, isoToMs, offsetMinutesOf } from "../lib/time";
import { Icon, type IconName } from "./Icon";
import { StatusBadge } from "./StatusBadge";
import { Term } from "./Term";
import { t, t as tr } from "../lib/i18n";

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
        <button className="btn ghost icon" onClick={onClose} aria-label={t("studio.taskDrawer.aria.closeDetails")}>
          <Icon name="x" />
        </button>
      </div>
      <div className="drawer-body">
        <div className="row wrap">
          {deadlineStatus === "late_soft" || deadlineStatus === "late_hard" ? (
            <StatusBadge kind="late" label={tr("studio.taskDrawer.tpl.lateBy", { fmtDuration: fmtDuration(ex?.lateness_minutes ?? 0), v: deadlineStatus === "late_hard" ? " (hard)" : "" })} />
          ) : deadlineStatus === "on_time" ? (
            <StatusBadge kind="on_time" />
          ) : null}
          {ex?.on_critical_chain ? <span className="badge accent"><Icon name="flag" />{" "}{tr("studio.taskDrawer.text.criticalChain")}</span> : null}
          {task?.locked ? <span className="badge info"><Icon name="lock" />{" "}{tr("studio.taskDrawer.text.fixed")}</span> : null}
        </div>
        <dl className="dl">
          <dt>{t("studio.taskDrawer.head.starts")}</dt>
          <dd>{fmtIso(placement.start_at, off)}</dd>
          <dt>{t("studio.taskDrawer.head.ends")}</dt>
          <dd>{fmtIso(placement.end_at, off)}</dd>
          <dt>{t("studio.taskDrawer.head.duration")}</dt>
          <dd>{fmtDuration(placement.end - placement.start)}</dd>
          {task?.duration_estimate && task.type !== "milestone" ? (
            <>
              <dt>
                {tr("studio.taskDrawer.text.durationRange")}{" "}<Term k="duration_range" bare />
              </dt>
              <dd data-testid="drawer-duration-range">
                {tr("studio.taskDrawer.text.toMostLikelyPlannedWith", { optimisticminutes: fmtDuration(task.duration_estimate.optimistic_minutes), pessimisticminutes: fmtDuration(task.duration_estimate.pessimistic_minutes), v: " ", likelyminutes: fmtDuration(task.duration_estimate.likely_minutes), v2: " " })}
                <Term k="expected_duration">{tr("studio.taskDrawer.text.expectedDuration")}</Term> {fmtDuration(task.duration_minutes)}
              </dd>
            </>
          ) : null}
          <dt>{terms.resources}</dt>
          <dd>{placement.resource_ids.length ? placement.resource_ids.map(resName).join(", ") : <span className="faint">none</span>}</dd>
          {task?.deadline ? (
            <>
              <dt>{terms.deadline}</dt>
              <dd>
                {fmtIso(task.deadline, off)} {task.deadline_hard ? <span className="chip">{tr("studio.taskDrawer.text.mustBeMet")}</span> : null}
              </dd>
            </>
          ) : null}
          {ex ? (
            <>
              <dt>{t("studio.taskDrawer.head.slack")}</dt>
              <dd>{ex.cpm_critical ? tr("studio.taskDrawer.str.noneCriticalInTheDependency") : fmtDuration(ex.cpm_slack_minutes)}</dd>
            </>
          ) : null}
        </dl>

        <section>
          <h3 className="mb">{t("studio.taskDrawer.head.whyItStartsThen")}</h3>
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
            <div className="small muted">{tr("studio.taskDrawer.text.noExplanationAvailable")}</div>
          )}
        </section>

        {violations.length ? (
          <section>
            <h3 className="mb">{t("studio.taskDrawer.head.problems")}</h3>
            {violations.map((v, i) => (
              <div key={i} className="small row" style={{ alignItems: "flex-start", marginBottom: 6 }}>
                <span className={`badge ${v.severity === "hard" ? "danger" : "warn"}`}>
                  <Icon name={v.severity === "hard" ? "x" : "clock"} />
                  {v.severity === "hard" ? tr("studio.taskDrawer.str.rule") : tr("studio.taskDrawer.str.late")}
                </span>
                <span>{v.message}</span>
              </div>
            ))}
          </section>
        ) : null}

        <section className="col">
          <h3>{t("studio.taskDrawer.head.adjust")}</h3>
          {task ? (
            lockedHere ? (
              <button className="btn" onClick={() => onUnlock(taskId)} disabled={lockBusy}>
                <Icon name="unlock" /> {t("studio.taskDrawer.btn.unlock")}
              </button>
            ) : (
              <button className="btn" onClick={() => onLock(placement)} disabled={lockBusy} data-testid="lock-at-time">
                {lockBusy ? <span className="spinner" aria-hidden /> : <Icon name="lock" />}
                {tr("studio.taskDrawer.text.lockAtThisTime")}
              </button>
            )
          ) : (
            <div className="small muted">{tr("studio.taskDrawer.text.thisNoLongerExistsIn", { taskL: terms.taskL })}</div>
          )}
          <span className="small faint">
            {tr("studio.taskDrawer.text.lockingFixesTheStartIn", { v: placement.resource_ids.length ? tr("studio.taskDrawer.tpl.andThe", { resourcesL: terms.resourcesL }) : "" })}
          </span>
          {task ? (
            <Link className="btn ghost sm" to={`../tasks?focus=${encodeURIComponent(taskId)}`} style={{ alignSelf: "flex-start" }}>
              {tr("studio.taskDrawer.text.edit", { taskL: terms.taskL })}{" "}<Icon name="arrow-right" />
            </Link>
          ) : null}
        </section>
      </div>
    </aside>
  );
}
