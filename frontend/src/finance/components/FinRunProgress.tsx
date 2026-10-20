import { useEffect, useRef, useState } from "react";
import { errorMessage } from "../../api/client";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { cancelFinanceRun } from "../api/client";
import { subscribeFinanceRunEvents, type FinStreamMode } from "../api/sse";
import { FIN_STAGES, type FinanceRun, type FinRunEvent, type FinRunRequeuedEvent, type FinStage } from "../api/types";
import { StatusPill } from "./StatusPill";

export const STAGE_LABEL: Record<FinStage, string> = {
  preflight: "Checking your inputs",
  cashflow: "Projecting your cash flow",
  optimize: "Planning contributions",
  simulate: "Testing many possible market outcomes",
  calibrate: "Adjusting for your target chances",
  validate: "Independent check of every rule",
  fixes: "Looking for simple fixes",
};

type StageState = "pending" | "active" | "done";

export interface FinRunProgressProps {
  runId: string;
  /** Called once with the final run (null if it could not be read). */
  onDone(run: FinanceRun | null): void;
  compact?: boolean;
}

/** Live progress of one finance run (SSE with polling fallback). */
export function FinRunProgress({ runId, onDone, compact }: FinRunProgressProps) {
  const [events, setEvents] = useState<FinRunEvent[]>([]);
  const [mode, setMode] = useState<FinStreamMode>("connecting");
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    setEvents([]);
    const sub = subscribeFinanceRunEvents(
      runId,
      (ev) => setEvents((list) => [...list, ev]),
      (run) => doneRef.current(run),
      { onModeChange: setMode },
    );
    return () => sub.close();
  }, [runId]);

  const stages = new Map<FinStage, StageState>();
  let fraction = 0;
  let message = "Waiting for a free worker…";
  let status: "queued" | "running" | "completed" | "failed" | "cancelled" = "queued";
  let error: string | null = null;
  let requeue: FinRunRequeuedEvent | null = null;
  for (const ev of events) {
    if (ev.type === "run_requeued") {
      // PHASE2B 2.11: another worker starts the run again from scratch.
      requeue = ev;
      stages.clear();
      fraction = 0;
      status = "queued";
      message = `Restarting on another worker (attempt ${ev.attempt} of ${ev.max_attempts})`;
    } else if (ev.type === "run_started") {
      status = "running";
      message = "Started";
    } else if (ev.type === "stage_started") {
      stages.set(ev.stage, "active");
      message = ev.message || STAGE_LABEL[ev.stage];
      fraction = 0;
    } else if (ev.type === "progress") {
      stages.set(ev.stage, "active");
      fraction = ev.fraction;
      if (ev.message) message = ev.message;
    } else if (ev.type === "stage_completed") {
      stages.set(ev.stage, "done");
    } else if (ev.type === "run_completed") {
      status = "completed";
      message = "Done";
    } else if (ev.type === "run_cancelled") {
      status = "cancelled";
      message = "Cancelled";
    } else if (ev.type === "run_failed") {
      status = "failed";
      error = ev.error;
      message = "Failed";
    }
  }
  const doneCount = FIN_STAGES.filter((s) => stages.get(s) === "done").length;
  const overall = status === "completed" ? 1 : Math.min(0.98, (doneCount + fraction) / FIN_STAGES.length);
  const active = status === "queued" || status === "running";

  const cancel = async () => {
    setCancelling(true);
    setCancelError(null);
    try {
      await cancelFinanceRun(runId);
    } catch (err) {
      setCancelError(errorMessage(err));
    } finally {
      setCancelling(false);
    }
  };

  return (
    <section className="card" data-testid="fin-run-progress" aria-labelledby={`frp-${runId}`}>
      <div className="card-header">
        <h2 id={`frp-${runId}`} className="row">
          {active ? <span className="spinner" aria-hidden /> : null}
          {active ? "Building your plan" : "Plan run"}
        </h2>
        <div className="row">
          <span data-testid="fin-run-status" role="status" aria-live="polite" className="row">
            <StatusPill kind={status} />
            <span className="small muted">{message}</span>
          </span>
          {active ? (
            <button className="btn sm" onClick={cancel} disabled={cancelling} data-testid="fin-run-cancel">
              <Icon name="stop" /> Cancel
            </button>
          ) : null}
        </div>
      </div>
      <div className="card-body col">
        <div
          className="progress-bar"
          role="progressbar"
          aria-label="Run progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(overall * 100)}
        >
          <div style={{ width: `${Math.round(overall * 100)}%` }} />
        </div>
        {!compact ? (
          <ol className="phase-list" aria-label="Stages">
            {FIN_STAGES.map((s) => {
              const st = stages.get(s) ?? "pending";
              return (
                <li key={s} className={`phase${st === "active" ? " active" : ""}`}>
                  <span className="phase-icon" aria-hidden>
                    {st === "done" ? <Icon name="check" style={{ color: "var(--ok)" }} /> : st === "active" ? <span className="spinner" /> : <Icon name="circle" style={{ color: "var(--text-faint)" }} />}
                  </span>
                  <span className="grow">{STAGE_LABEL[s]}</span>
                  <span className="small muted">{st === "done" ? "Done" : st === "active" ? "In progress" : "Waiting"}</span>
                </li>
              );
            })}
          </ol>
        ) : null}
        {requeue ? (
          <span className="small muted row" data-testid="fin-run-requeued">
            <Icon name="refresh" />{" "}
            {active
              ? `Restarting on another worker (attempt ${requeue.attempt} of ${requeue.max_attempts})`
              : `Finished after a restart on another worker (attempt ${requeue.attempt} of ${requeue.max_attempts}).`}
          </span>
        ) : null}
        {mode === "polling" ? <span className="small muted">Live updates unavailable; checking every few seconds.</span> : null}
        {error ? <Banner tone="danger" role="alert" title="The run failed">{error}</Banner> : null}
        {cancelError ? <Banner tone="danger" role="alert">{cancelError}</Banner> : null}
      </div>
    </section>
  );
}
