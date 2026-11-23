import { useState } from "react";
import { useNavigate } from "react-router";
import { ApiError, errorMessage, replanSchedule } from "../api/client";
import type { Issue, Problem, ReplanRequest, ResourceUnavailable, Schedule, TaskUpdate } from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDuration, isoToMs, msToIso, offsetLabel, offsetMinutesOf } from "../lib/time";
import { Dialog } from "./Dialog";
import { Icon } from "./Icon";
import { DurationInput, PlanDateTimeInput } from "./Inputs";
import { t, t as tr } from "../lib/i18n";

interface DurationRow {
  taskId: string;
  minutes: number;
}

export function ReplanDialog({
  schedule,
  draft,
  version,
  terms,
  onClose,
  beforeSubmit,
  afterSubmit,
}: {
  schedule: Schedule;
  draft: Problem;
  version: number;
  terms: Terms;
  onClose(): void;
  /** Save pending edits; resolves with the version to send, or null to abort. */
  beforeSubmit(): Promise<number | null>;
  /**
   * Called once the replan was accepted. The replan writes its changes into the
   * plan and bumps its version (`problemVersion`), so the caller must reload it.
   */
  afterSubmit(problemVersion: number): Promise<void>;
}) {
  const navigate = useNavigate();
  const off = offsetMinutesOf(draft.horizon_start);
  const h0 = isoToMs(draft.horizon_start);
  const hEnd = h0 + draft.horizon_days * 1440 * 60000;
  const defaultCutoff = () => {
    const now = Math.ceil(Date.now() / 900000) * 900000;
    return msToIso(Math.min(Math.max(now, h0), hEnd - 60000), off);
  };
  const [cutoff, setCutoff] = useState<string>(defaultCutoff());
  const [durations, setDurations] = useState<DurationRow[]>([]);
  const [outages, setOutages] = useState<ResourceUnavailable[]>([]);
  const [budget, setBudget] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);

  const cutoffMs = isoToMs(cutoff);
  const cutoffValid = cutoffMs >= h0 && cutoffMs < hEnd;
  const frozen = schedule.placements.filter((p) => isoToMs(p.start_at) < cutoffMs).length;
  const taskName = (id: string) => draft.tasks.find((t) => t.id === id)?.name ?? id;
  const activities = draft.tasks.filter((t) => t.type === "activity");

  const submit = async () => {
    setBusy(true);
    setError(null);
    setIssues([]);
    try {
      const v = await beforeSubmit();
      if (v === null) {
        setError(tr("studio.replanDialog.str.yourLatestEditsCouldNot"));
        return;
      }
      const task_updates: TaskUpdate[] = durations
        .filter((d) => draft.tasks.find((t) => t.id === d.taskId)?.duration_minutes !== d.minutes)
        .map((d) => ({ id: d.taskId, duration_minutes: d.minutes }));
      const resource_unavailable = outages.filter((o) => isoToMs(o.end) > isoToMs(o.start));
      const body: ReplanRequest = {
        cutoff,
        changes: { task_updates, add_tasks: [], remove_task_ids: [], resource_unavailable },
        run: { strategy: "auto", time_limit_seconds: budget },
        expected_problem_version: v,
      };
      const res = await replanSchedule(schedule.id, body);
      await afterSubmit(res.problem_version);
      navigate(`../optimize?run=${encodeURIComponent(res.run_id)}`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 412) setError(tr("studio.replanDialog.str.thePlanWasChangedElsewhere"));
        else if (err.code === "RUN_ALREADY_ACTIVE") setError(tr("studio.replanDialog.str.anOptimizationIsAlreadyRunning"));
        else {
          setError(err.message);
          if (Array.isArray(err.details.issues)) setIssues(err.details.issues as Issue[]);
        }
      } else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={t("studio.replanDialog.title.replanFromNow")}
      wide
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>{tr("studio.replanDialog.text.cancel")}</button>
          <button className="btn primary" onClick={submit} disabled={busy || !cutoffValid} data-testid="replan-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />}
            {tr("studio.replanDialog.text.replan")}
          </button>
        </>
      }
    >
      <p className="muted" style={{ margin: 0 }}>
        {tr("studio.replanDialog.text.everythingThatStartsBeforeThe", { scheduleL: terms.scheduleL, scheduleL2: terms.scheduleL })}
      </p>
      <div className="field">
        <label htmlFor="replan-cutoff">{tr("studio.replanDialog.text.cutOff", { off: offsetLabel(off) })}</label>
        <div className="row wrap">
          <PlanDateTimeInput id="replan-cutoff" value={cutoff} offsetMin={off} allowEmpty={false} label={t("studio.replanDialog.label.cutoff")} className="input" onChange={(v) => v && setCutoff(v)} />
          <span className="small muted">{tr("studio.replanDialog.text.willBeKeptAsThey", { tr: tr("common.nOfM", { n: frozen, m: schedule.placements.length }), tasksL: terms.tasksL })}</span>
        </div>
        {!cutoffValid ? <span className="small" style={{ color: "var(--danger)" }}>{tr("studio.replanDialog.text.theCutOffMustLie")}</span> : null}
      </div>

      <section className="col">
        <h3>{t("studio.replanDialog.head.whatChanged")}</h3>
        <div className="field-label">{tr("studio.replanDialog.text.thatTakeLongerOrShorter", { tasks: terms.tasks })}</div>
        {durations.map((d, i) => (
          <div className="row wrap" key={i}>
            <select
              className="select sm"
              style={{ width: 260 }}
              value={d.taskId}
              aria-label={tr("studio.replanDialog.tpl.forChange", { task: terms.task, v: i + 1 })}
              onChange={(e) => {
                const t = draft.tasks.find((x) => x.id === e.target.value);
                setDurations(durations.map((x, k) => (k === i ? { taskId: e.target.value, minutes: t?.duration_minutes ?? x.minutes } : x)));
              }}
            >
              {activities.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            <span className="small muted">{tr("studio.replanDialog.text.nowTakes")}</span>
            <DurationInput value={d.minutes} label={tr("studio.replanDialog.tpl.newDurationFor", { taskId: taskName(d.taskId) })} onChange={(m) => setDurations(durations.map((x, k) => (k === i ? { ...x, minutes: m } : x)))} />
            <span className="small faint">{tr("studio.replanDialog.text.was", { fmtDuration: fmtDuration(draft.tasks.find((t) => t.id === d.taskId)?.duration_minutes ?? 0) })}</span>
            <button className="btn ghost sm icon" aria-label={tr("studio.replanDialog.tpl.removeChange", { v: i + 1 })} onClick={() => setDurations(durations.filter((_, k) => k !== i))}>
              <Icon name="x" />
            </button>
          </div>
        ))}
        <div>
          <button
            className="btn sm"
            disabled={activities.length === 0}
            onClick={() => {
              const t = activities.find((a) => !durations.some((d) => d.taskId === a.id)) ?? activities[0];
              setDurations([...durations, { taskId: t.id, minutes: t.duration_minutes }]);
            }}
          >
            <Icon name="plus" /> {t("studio.replanDialog.btn.changedDuration")}
          </button>
        </div>

        <div className="field-label mt">{tr("studio.replanDialog.text.thatAreUnavailable", { resources: terms.resources })}</div>
        {outages.map((o, i) => (
          <div className="row wrap" key={i}>
            <select className="select sm" style={{ width: 200 }} value={o.resource_id} aria-label={tr("studio.replanDialog.tpl.forOutage", { resource: terms.resource, v: i + 1 })} onChange={(e) => setOutages(outages.map((x, k) => (k === i ? { ...x, resource_id: e.target.value } : x)))}>
              {draft.resources.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
            <span className="small muted">from</span>
            <PlanDateTimeInput value={o.start} offsetMin={off} allowEmpty={false} label={tr("studio.replanDialog.tpl.outageStart", { v: i + 1 })} onChange={(v) => v && setOutages(outages.map((x, k) => (k === i ? { ...x, start: v } : x)))} />
            <span className="small muted">to</span>
            <PlanDateTimeInput value={o.end} offsetMin={off} allowEmpty={false} label={tr("studio.replanDialog.tpl.outageEnd", { v: i + 1 })} onChange={(v) => v && setOutages(outages.map((x, k) => (k === i ? { ...x, end: v } : x)))} />
            <input className="input sm" style={{ width: 140 }} placeholder={t("studio.replanDialog.ph.reason")} aria-label={tr("studio.replanDialog.tpl.outageReason", { v: i + 1 })} value={o.reason} onChange={(e) => setOutages(outages.map((x, k) => (k === i ? { ...x, reason: e.target.value } : x)))} />
            <button className="btn ghost sm icon" aria-label={tr("studio.replanDialog.tpl.removeOutage", { v: i + 1 })} onClick={() => setOutages(outages.filter((_, k) => k !== i))}>
              <Icon name="x" />
            </button>
          </div>
        ))}
        <div>
          <button
            className="btn sm"
            disabled={draft.resources.length === 0}
            onClick={() =>
              setOutages([
                ...outages,
                { resource_id: draft.resources[0].id, start: cutoff, end: msToIso(cutoffMs + 8 * 3600000, off), reason: "Breakdown" },
              ])
            }
          >
            <Icon name="plus" />{" "}{tr("studio.replanDialog.text.unavailable", { resourceL: terms.resourceL })}
          </button>
        </div>
        <span className="small faint">{tr("studio.replanDialog.text.ifYouEnterChangesThey", { version: version, v: version + 1 })}</span>
      </section>

      <div className="field" style={{ maxWidth: 220 }}>
        <label htmlFor="replan-budget">{t("studio.replanDialog.label.searchTimeSeconds")}</label>
        <input id="replan-budget" className="input" type="number" min={1} max={300} value={budget} onChange={(e) => setBudget(Math.max(1, Math.min(300, Number(e.target.value) || 1)))} />
      </div>

      {error ? (
        <div className="banner danger" role="alert">
          <Icon name="alert" />
          <div className="banner-body">
            {error}
            {issues.length ? (
              <ul className="small" style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {issues.map((i, k) => (
                  <li key={k}>{i.message}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}
