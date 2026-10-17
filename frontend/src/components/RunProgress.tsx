import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { cancelRun, errorMessage, getRun, listRunEvents } from "../api/client";
import { subscribeRunEvents, type StreamMode } from "../api/sse";
import {
  ACTIVE_RUN_STATUSES,
  type ObjectiveValues,
  type RunEvent,
  type SolverRun,
  type TerminationReason,
} from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDuration, fmtMoney, fmtSeconds } from "../lib/time";
import { Banner, ErrorBanner, Loading } from "./Banner";
import { Icon } from "./Icon";
import { StatusBadge } from "./StatusBadge";

export const PHASE_LABEL: Record<string, string> = {
  heuristic: "Priority rules",
  cpsat: "Constraint solver",
  ga: "Genetic algorithm",
  cpm: "Critical path shortcut",
};

export const methodOf = (solver: string) => solver.split(":")[0];
export const methodLabel = (solver: string) => PHASE_LABEL[methodOf(solver)] ?? methodOf(solver);

export const TERMINATION_TEXT: Record<TerminationReason, string> = {
  optimal: "Proven best possible",
  proven_infeasible: "Proven impossible",
  time_limit: "Time budget used",
  generation_limit: "Generation limit reached",
  stagnation: "No further improvement",
  completed: "Completed",
  cancelled: "Cancelled",
  preflight_failed: "Plan has errors",
  no_solution: "No solution found",
  error: "Error",
};

interface PhaseView {
  solver: string;
  reason: string | null;
  done: boolean;
  status?: string;
  feasibility?: string;
  termination_reason?: TerminationReason;
  objectives: ObjectiveValues | null;
  iteration: number | null;
  started: number;
  ended: number | null;
  extra: Record<string, unknown>;
  feasibleFound: boolean;
}

function derivePhases(events: RunEvent[]): PhaseView[] {
  const phases: PhaseView[] = [];
  const current = () => phases[phases.length - 1];
  for (const ev of events) {
    if (ev.type === "phase_started") {
      phases.push({
        solver: ev.solver,
        reason: ev.reason,
        done: false,
        objectives: null,
        iteration: null,
        started: ev.elapsed_seconds,
        ended: null,
        extra: {},
        feasibleFound: false,
      });
    } else if (ev.type === "progress") {
      let p = current();
      if (!p || p.done || p.solver !== ev.solver) {
        p = { solver: ev.solver, reason: null, done: false, objectives: null, iteration: null, started: ev.elapsed_seconds, ended: null, extra: {}, feasibleFound: false };
        phases.push(p);
      }
      p.objectives = ev.best_objectives ?? p.objectives;
      p.iteration = ev.iteration;
      p.extra = ev.extra;
      p.feasibleFound = p.feasibleFound || ev.feasible_found;
    } else if (ev.type === "phase_completed") {
      let p = [...phases].reverse().find((x) => x.solver === ev.solver && !x.done);
      if (!p) {
        p = { solver: ev.solver, reason: null, done: false, objectives: null, iteration: null, started: ev.elapsed_seconds, ended: null, extra: {}, feasibleFound: false };
        phases.push(p);
      }
      p.done = true;
      p.status = ev.status;
      p.feasibility = ev.feasibility;
      p.termination_reason = ev.termination_reason;
      p.objectives = ev.objectives ?? p.objectives;
      p.ended = ev.elapsed_seconds;
    }
  }
  return phases;
}

function Sparkline({ points }: { points: Array<[number, number]> }) {
  if (points.length < 2) return null;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs) || 1;
  const y0 = Math.min(...ys);
  const y1 = Math.max(...ys);
  const w = 300;
  const h = 56;
  const sx = (x: number) => ((x - x0) / Math.max(1e-9, x1 - x0)) * (w - 8) + 4;
  const sy = (y: number) => (y1 === y0 ? h / 2 : 4 + (1 - (y - y0) / (y1 - y0)) * (h - 8));
  // step line: score only improves
  let d = `M${sx(points[0][0])},${sy(points[0][1])}`;
  for (let i = 1; i < points.length; i++) d += ` H${sx(points[i][0])} V${sy(points[i][1])}`;
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label={`Best score improved from ${ys[0].toFixed(3)} to ${ys[ys.length - 1].toFixed(3)}`}>
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function ObjectivesLine({ o, currency, terms }: { o: ObjectiveValues | null; currency: string; terms: Terms }) {
  if (!o) return <span className="faint">No complete {terms.scheduleL} yet</span>;
  return (
    <span className="row wrap small" style={{ gap: 12 }}>
      <span title="Total duration from the plan start"><Icon name="clock" /> {fmtDuration(o.makespan_minutes)}</span>
      <span title="Lateness weighted by priority"><Icon name="flag" /> {o.weighted_tardiness ? `${fmtDuration(o.weighted_tardiness)} weighted late` : "nothing late"}</span>
      <span title="Cost">{fmtMoney(o.cost, currency)}</span>
    </span>
  );
}

export function useRunStream(runId: string) {
  const [run, setRun] = useState<SolverRun | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [mode, setMode] = useState<StreamMode>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [lastAt, setLastAt] = useState<{ elapsed: number; at: number } | null>(null);

  useEffect(() => {
    let sub: { close(): void } | null = null;
    let alive = true;
    setRun(null);
    setEvents([]);
    setError(null);
    setLastAt(null);
    getRun(runId)
      .then(async (r) => {
        if (!alive) return;
        setRun(r);
        if (!ACTIVE_RUN_STATUSES.includes(r.status)) {
          setMode("closed");
          try {
            const { items } = await listRunEvents(runId, 0);
            if (alive) setEvents(items.sort((a, b) => a.seq - b.seq));
          } catch {
            /* events are optional for finished runs */
          }
          return;
        }
        sub = subscribeRunEvents(
          runId,
          (ev) => {
            if (!alive) return;
            setEvents((list) => [...list, ev]);
            setLastAt({ elapsed: ev.elapsed_seconds, at: performance.now() });
            if (ev.type === "run_started") setRun((cur) => (cur ? { ...cur, status: "running" } : cur));
          },
          (final) => {
            if (!alive) return;
            if (final) setRun(final);
            else getRun(runId).then((r) => alive && setRun(r)).catch(() => undefined);
          },
          { onModeChange: (m) => alive && setMode(m) },
        );
      })
      .catch((err) => alive && setError(errorMessage(err)));
    return () => {
      alive = false;
      sub?.close();
    };
  }, [runId]);

  return { run, events, mode, error, lastAt, setRun };
}

export function RunProgress({
  runId,
  terms,
  currency,
  onFinished,
  onStatusChange,
}: {
  runId: string;
  terms: Terms;
  currency: string;
  onFinished?(run: SolverRun): void;
  onStatusChange?(status: string): void;
}) {
  const { run, events, mode, error, lastAt, setRun } = useRunStream(runId);
  const [now, setNow] = useState(performance.now());
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const notified = useRef(false);

  const active = run ? ACTIVE_RUN_STATUSES.includes(run.status) : false;
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(performance.now()), 250);
    return () => clearInterval(t);
  }, [active]);

  useEffect(() => {
    if (run && !active && !notified.current) {
      notified.current = true;
      onFinished?.(run);
    }
  }, [run, active, onFinished]);

  const status = run?.status;
  useEffect(() => {
    if (status) onStatusChange?.(status);
  }, [status]); // eslint-disable-line react-hooks/exhaustive-deps

  const phases = useMemo(() => derivePhases(events), [events]);
  const scorePoints = useMemo(() => {
    const pts: Array<[number, number]> = [];
    let best = Infinity;
    for (const ev of events) {
      const s = ev.type === "progress" ? ev.best_score : ev.type === "phase_completed" ? ev.objectives?.score ?? null : null;
      if (s !== null && s !== undefined && s < best) {
        best = s;
        pts.push([ev.elapsed_seconds, s]);
      }
    }
    return pts;
  }, [events]);

  if (error) return <ErrorBanner error={error} />;
  if (!run) return <Loading label="Loading run…" />;

  const limit = Number(run.request?.time_limit_seconds ?? 10);
  const terminal = [...events].reverse().find((e) => e.type === "run_completed" || e.type === "run_cancelled" || e.type === "run_failed");
  const elapsed = active
    ? lastAt
      ? lastAt.elapsed + (now - lastAt.at) / 1000
      : 0
    : run.elapsed_seconds ?? terminal?.elapsed_seconds ?? 0;
  const pct = Math.min(100, (elapsed / Math.max(0.1, limit)) * 100);
  const best = [...phases].reverse().find((p) => p.objectives)?.objectives ?? null;
  const primaryId = run.primary_schedule_id ?? (terminal && "primary_schedule_id" in terminal ? terminal.primary_schedule_id : null);

  const doCancel = async () => {
    setCancelling(true);
    setCancelError(null);
    try {
      const res = await cancelRun(run.id);
      if (res.status === "cancelled") setRun({ ...run, status: "cancelled" });
    } catch (err) {
      setCancelError(errorMessage(err));
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div className="card" data-testid="run-progress" data-run-id={run.id} data-run-state={run.status}>
      <div className="card-header">
        <div className="row wrap">
          <h3>Optimization run</h3>
          <StatusBadge kind={run.status} testId="run-status" />
          {active ? (
            <span className="small muted">
              {mode === "live" ? "Live" : mode === "polling" ? "Updating every 2 s" : mode === "reconnecting" ? "Reconnecting…" : "Connecting…"}
            </span>
          ) : null}
        </div>
        <div className="row">
          {active ? (
            <button className="btn danger sm" onClick={doCancel} disabled={cancelling || run.status === "cancelled"}>
              {cancelling ? <span className="spinner" aria-hidden /> : <Icon name="stop" />}
              Cancel
            </button>
          ) : null}
        </div>
      </div>
      <div className="card-body col gap-lg">
        <ErrorBanner error={cancelError} />
        <div className="col" style={{ gap: 4 }}>
          <div className="row between small">
            <span className="muted">
              {active ? "Searching" : "Took"} {fmtSeconds(elapsed)} of {fmtSeconds(limit)} budget
            </span>
            <span className="muted">{run.request?.strategy ? `Method: ${String(run.request.strategy)}` : null}</span>
          </div>
          <div className="progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(active ? pct : 100)} aria-label="Time budget used">
            <div style={{ width: `${active ? pct : 100}%` }} />
          </div>
        </div>

        <div className="grid-2">
          <div className="col">
            <h3>Phases</h3>
            {phases.length === 0 ? (
              <div className="small muted row">{active ? <><span className="spinner" aria-hidden /> Waiting for the solver to start…</> : "No phase information recorded."}</div>
            ) : (
              <ol className="phase-list" aria-label="Solver phases">
                {phases.map((p, i) => {
                  const isActive = active && !p.done && i === phases.length - 1;
                  return (
                    <li key={`${p.solver}-${i}`} className={`phase${isActive ? " active" : ""}`} data-testid={`phase-${p.solver}`}>
                      <span className="phase-icon">
                        {isActive ? <span className="spinner" aria-hidden /> : p.done ? <Icon name={p.feasibility === "feasible" ? "check" : p.feasibility === "infeasible" ? "ban" : "help"} /> : <Icon name="circle" />}
                      </span>
                      <div className="grow col" style={{ gap: 2 }}>
                        <div className="row wrap between">
                          <strong>{methodLabel(p.solver)}</strong>
                          <span className="small muted">
                            {isActive ? "running" : p.termination_reason ? TERMINATION_TEXT[p.termination_reason] : ""}
                            {p.ended !== null ? ` · ${fmtSeconds(p.ended - p.started)}` : ""}
                          </span>
                        </div>
                        {p.reason ? <div className="small muted">{p.reason}</div> : null}
                        <ObjectivesLine o={p.objectives} currency={currency} terms={terms} />
                        {p.solver === "ga" && typeof p.extra.mutation_rate === "number" ? (
                          <div className="small faint">
                            generation {p.iteration ?? 0} · {Math.round(Number(p.extra.feasible_fraction ?? 0) * 100)}% valid · mutation {Number(p.extra.mutation_rate).toFixed(2)}
                          </div>
                        ) : null}
                        {p.solver === "cpsat" && p.iteration ? <div className="small faint">{p.iteration} improving solutions found</div> : null}
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
          <div className="col">
            <h3>Best so far</h3>
            <div className="kpis" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))" }}>
              <div className="card kpi">
                <div className="kpi-label">Duration</div>
                <div className="kpi-value">{best ? fmtDuration(best.makespan_minutes) : "-"}</div>
              </div>
              <div className="card kpi">
                <div className="kpi-label">Weighted lateness</div>
                <div className="kpi-value">{best ? fmtDuration(best.weighted_tardiness) : "-"}</div>
              </div>
              <div className="card kpi">
                <div className="kpi-label">Cost</div>
                <div className="kpi-value" style={{ fontSize: 17 }}>{best ? fmtMoney(best.cost, currency) : "-"}</div>
              </div>
            </div>
            {scorePoints.length > 1 ? (
              <div>
                <div className="small muted">Overall score over time (lower is better)</div>
                <Sparkline points={scorePoints} />
              </div>
            ) : null}
          </div>
        </div>

        {!active ? (
          <div className="col">
            {run.status === "completed" || run.status === "cancelled" ? (
              <Banner
                tone={run.feasibility === "feasible" ? "ok" : run.feasibility === "infeasible" ? "danger" : "warn"}
                title={
                  run.feasibility === "feasible"
                    ? `A valid ${terms.scheduleL} was found${run.optimality_proven ? " and it is proven to be the best possible" : ""}.`
                    : run.feasibility === "infeasible"
                      ? `No valid ${terms.scheduleL} exists for this plan.`
                      : `No valid ${terms.scheduleL} was found in time.`
                }
                actions={
                  primaryId ? (
                    <Link className="btn primary sm" to={`../schedule?id=${encodeURIComponent(primaryId)}`} data-testid="view-schedule">
                      View {terms.scheduleL} <Icon name="arrow-right" />
                    </Link>
                  ) : null
                }
              >
                <div className="row wrap" style={{ gap: 8, marginTop: 4 }}>
                  {run.feasibility ? <StatusBadge kind={run.feasibility} /> : null}
                  {run.termination_reason ? <span className="small muted">{TERMINATION_TEXT[run.termination_reason]}</span> : null}
                  {run.status === "cancelled" ? <span className="small muted">Stopped early; the best result so far was kept.</span> : null}
                  {run.feasibility !== "feasible" && run.feasibility !== null ? (
                    <span className="small muted">{run.feasibility === "infeasible" ? "Relax a hard deadline, a lock or add capacity." : "Try a longer time budget, or check hard deadlines and locks."}</span>
                  ) : null}
                </div>
              </Banner>
            ) : run.status === "failed" ? (
              <Banner tone="danger" title="The run failed." role="alert">
                {run.error ?? "Unknown error"}
              </Banner>
            ) : null}
            {run.selection?.reasons.length ? (
              <div className="small">
                <strong>Why this method:</strong>
                <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                  {run.selection.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {run.diagnostics.length ? (
              <div className="small">
                <strong>Notes:</strong>
                <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                  {run.diagnostics.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
