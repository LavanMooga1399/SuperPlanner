import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, errorMessage, replanSchedule } from "../api/client";
import type { Issue, Problem, ReplanRequest, ResourceUnavailable, Schedule, TaskUpdate } from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDuration, isoToMs, msToIso, offsetLabel, offsetMinutesOf } from "../lib/time";
import { Dialog } from "./Dialog";
import { Icon } from "./Icon";
import { DurationInput, PlanDateTimeInput } from "./Inputs";

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
}: {
  schedule: Schedule;
  draft: Problem;
  version: number;
  terms: Terms;
  onClose(): void;
  /** Save pending edits; resolves with the version to send, or null to abort. */
  beforeSubmit(): Promise<number | null>;
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
        setError("Your latest edits could not be saved. Resolve that first.");
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
      navigate(`../optimize?run=${encodeURIComponent(res.run_id)}`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 412) setError("The plan was changed elsewhere. Reload the plan and try again.");
        else if (err.code === "RUN_ALREADY_ACTIVE") setError("An optimization is already running for this plan. Wait for it or cancel it first.");
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
      title="Replan from now"
      wide
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={submit} disabled={busy || !cutoffValid} data-testid="replan-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />}
            Replan
          </button>
        </>
      }
    >
      <p className="muted" style={{ margin: 0 }}>
        Everything that starts before the cut-off stays exactly as in this {terms.scheduleL}. The rest is optimized again, taking
        your changes into account. The current approved {terms.scheduleL} stays approved until you approve a new one.
      </p>
      <div className="field">
        <label htmlFor="replan-cutoff">Cut-off ({offsetLabel(off)})</label>
        <div className="row wrap">
          <PlanDateTimeInput id="replan-cutoff" value={cutoff} offsetMin={off} allowEmpty={false} label="Cut-off" className="input" onChange={(v) => v && setCutoff(v)} />
          <span className="small muted">{frozen} of {schedule.placements.length} {terms.tasksL} will be kept as they are.</span>
        </div>
        {!cutoffValid ? <span className="small" style={{ color: "var(--danger)" }}>The cut-off must lie inside the planning horizon.</span> : null}
      </div>

      <section className="col">
        <h3>What changed?</h3>
        <div className="field-label">{terms.tasks} that take longer or shorter</div>
        {durations.map((d, i) => (
          <div className="row wrap" key={i}>
            <select
              className="select sm"
              style={{ width: 260 }}
              value={d.taskId}
              aria-label={`${terms.task} for change ${i + 1}`}
              onChange={(e) => {
                const t = draft.tasks.find((x) => x.id === e.target.value);
                setDurations(durations.map((x, k) => (k === i ? { taskId: e.target.value, minutes: t?.duration_minutes ?? x.minutes } : x)));
              }}
            >
              {activities.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            <span className="small muted">now takes</span>
            <DurationInput value={d.minutes} label={`New duration for ${taskName(d.taskId)}`} onChange={(m) => setDurations(durations.map((x, k) => (k === i ? { ...x, minutes: m } : x)))} />
            <span className="small faint">was {fmtDuration(draft.tasks.find((t) => t.id === d.taskId)?.duration_minutes ?? 0)}</span>
            <button className="btn ghost sm icon" aria-label={`Remove change ${i + 1}`} onClick={() => setDurations(durations.filter((_, k) => k !== i))}>
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
            <Icon name="plus" /> Changed duration
          </button>
        </div>

        <div className="field-label mt">{terms.resources} that are unavailable</div>
        {outages.map((o, i) => (
          <div className="row wrap" key={i}>
            <select className="select sm" style={{ width: 200 }} value={o.resource_id} aria-label={`${terms.resource} for outage ${i + 1}`} onChange={(e) => setOutages(outages.map((x, k) => (k === i ? { ...x, resource_id: e.target.value } : x)))}>
              {draft.resources.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
            <span className="small muted">from</span>
            <PlanDateTimeInput value={o.start} offsetMin={off} allowEmpty={false} label={`Outage ${i + 1} start`} onChange={(v) => v && setOutages(outages.map((x, k) => (k === i ? { ...x, start: v } : x)))} />
            <span className="small muted">to</span>
            <PlanDateTimeInput value={o.end} offsetMin={off} allowEmpty={false} label={`Outage ${i + 1} end`} onChange={(v) => v && setOutages(outages.map((x, k) => (k === i ? { ...x, end: v } : x)))} />
            <input className="input sm" style={{ width: 140 }} placeholder="Reason" aria-label={`Outage ${i + 1} reason`} value={o.reason} onChange={(e) => setOutages(outages.map((x, k) => (k === i ? { ...x, reason: e.target.value } : x)))} />
            <button className="btn ghost sm icon" aria-label={`Remove outage ${i + 1}`} onClick={() => setOutages(outages.filter((_, k) => k !== i))}>
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
            <Icon name="plus" /> Unavailable {terms.resourceL}
          </button>
        </div>
        <span className="small faint">If you enter changes, they are written into the plan (version {version} becomes {version + 1}) because they are real-world facts.</span>
      </section>

      <div className="field" style={{ maxWidth: 220 }}>
        <label htmlFor="replan-budget">Search time (seconds)</label>
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
