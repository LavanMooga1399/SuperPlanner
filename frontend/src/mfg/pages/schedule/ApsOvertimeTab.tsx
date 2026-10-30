/**
 * Overtime of a schedule run (M3 12, 6.8, 16 Q1):
 * - `allow` runs: every extra shift the scheduler opened, with cost and why (the late or critical work using it).
 * - `suggest` runs: the extra shifts that would reduce lateness, each with the weighted late minutes it saves and its
 *   cost, ranked by saving per cost. The planner accepts the ones they want ("Accept" per row) and re-runs with
 *   those shifts opened (the run form, prefilled), or re-runs with automatic overtime (Allow).
 */
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { getApsOvertime, rerunWithOpenShifts } from "../../api/clientM3";
import type { OvertimeWindow } from "../../api/typesM3";
import { MfgError, Spinner } from "../../components/Feedback";
import { fmtNum } from "../../lib/formatM2";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { needsText, useCan } from "../../lib/permissions";
import { useResourceNames } from "../../lib/resourceNames";
import { useLoad } from "../../lib/useMfg";
import { orderLink } from "./ApsOrdersTab";
import { useApsRun } from "./ApsRunShell";

const STATUS: Record<OvertimeWindow["status"], { label: string; tone: string; icon: "check" | "help" | "lock" }> = {
  opened: { label: "Opened by the scheduler", tone: "warn", icon: "check" },
  suggested: { label: "Suggested", tone: "info", icon: "help" },
  forced: { label: "Opened by you", tone: "accent", icon: "lock" },
};

const keyOf = (w: OvertimeWindow) => w.assignment_id ? `${w.assignment_id}:${w.start}` : `${w.line_id}:${w.start}`;

export function ApsOvertimeTab() {
  const { run } = useApsRun();
  const clock = usePlantClock();
  const navigate = useNavigate();
  const canRun = useCan("schedule_run");
  const ot = useLoad((signal) => getApsOvertime(run.id, undefined, signal), [run.id]);
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const items = ot.data?.items ?? [];
  const opened = items.filter((w) => w.status !== "suggested");
  const suggested = useMemo(
    () => items.filter((w) => w.status === "suggested").sort((a, b) => (b.tardiness_saved_minutes ?? 0) / Math.max(1, b.cost) - (a.tardiness_saved_minutes ?? 0) / Math.max(1, a.cost)),
    [items],
  );
  const policy = run.policy ?? run.summary?.policy ?? run.params?.overtime ?? "suggest";
  const t = ot.data?.totals;
  const acceptedRows = suggested.filter((w) => accepted.has(keyOf(w)));

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // accept: a live, publishable copy of this run with the accepted shifts opened as planner overtime, then compare
  const rerunAccepted = async () => {
    setBusy(true);
    setError(null);
    try {
      const n = acceptedRows.length;
      const next = await rerunWithOpenShifts(
        run.id,
        acceptedRows.map((w) => ({ line_id: w.line_id, start: w.start, end: w.end })),
        `${run.label || `Schedule #${run.run_no}`} with ${n} extra shift${n === 1 ? "" : "s"}`,
      );
      navigate(mfgPaths.apsCompare(next.id, run.id));
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };

  return (
    <div className="col gap-lg" data-testid="aps-overtime" data-policy={policy}>
      <MfgError error={ot.error ?? error} onRetry={ot.reload} />
      {ot.loading && !ot.data ? <Spinner /> : null}
      {t ? (
        <div className="kpis">
          <div className="card kpi">
            <div className="kpi-label">Overtime used</div>
            <div className="kpi-value">{fmtDuration(t.opened_minutes) || "none"}</div>
            <div className="kpi-sub">cost {fmtNum(Math.round(t.opened_cost))}</div>
          </div>
          <div className="card kpi">
            <div className="kpi-label">Overtime suggested</div>
            <div className="kpi-value">{fmtDuration(t.suggested_minutes) || "none"}</div>
            <div className="kpi-sub">
              cost {fmtNum(Math.round(t.suggested_cost))} · saves {fmtDuration(t.tardiness_saved_minutes) || "0"} weighted lateness
            </div>
          </div>
        </div>
      ) : null}

      {policy === "off" ? (
        <Banner tone="info" title="This run used regular shifts only">
          Nothing was opened or suggested. Run with "Suggest overtime" to see which extra shifts would help.
        </Banner>
      ) : null}

      {opened.length || policy === "allow" ? (
        <section className="card" data-testid="overtime-opened">
          <div className="card-header">
            <h3>Extra shifts {policy === "allow" ? "opened by the scheduler" : "in this plan"} ({opened.length})</h3>
          </div>
          <OtTable rows={opened} clock={clock} mode="opened" runId={run.id} />
        </section>
      ) : null}

      {policy === "suggest" ? (
        <section className="card" data-testid="overtime-suggested">
          <div className="card-header">
            <h3>Suggested extra shifts ({suggested.length})</h3>
            <span className="muted small">Best saving per cost first</span>
          </div>
          {suggested.length === 0 ? (
            <div className="card-body muted">No extra shift would reduce lateness.</div>
          ) : (
            <OtTable
              runId={run.id}
              rows={suggested}
              clock={clock}
              mode="suggested"
              accepted={accepted}
              onToggle={(w) =>
                setAccepted((s) => {
                  const n = new Set(s);
                  const k = keyOf(w);
                  if (n.has(k)) n.delete(k);
                  else n.add(k);
                  return n;
                })
              }
              canAccept={canRun}
            />
          )}
          {suggested.length ? (
            <div className="card-footer row wrap">
              <button type="button" className="btn primary" disabled={!canRun || busy || acceptedRows.length === 0} title={canRun ? undefined : needsText("schedule_run")} onClick={() => void rerunAccepted()} data-testid="overtime-rerun-accepted">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />} Re-run with these opened ({acceptedRows.length})
              </button>
              <button type="button" className="btn ghost" disabled={!canRun} onClick={() => setAccepted(new Set(suggested.map(keyOf)))}>
                Accept all
              </button>
              <span className="faint small">
                Creates a new run with exactly the accepted shifts opened, then compares it with this one. Either run can be published.
              </span>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function OtTable({
  runId,
  rows,
  clock,
  mode,
  accepted,
  onToggle,
  canAccept,
}: {
  runId: string;
  rows: OvertimeWindow[];
  clock: ReturnType<typeof usePlantClock>;
  mode: "opened" | "suggested";
  accepted?: Set<string>;
  onToggle?(w: OvertimeWindow): void;
  canAccept?: boolean;
}) {
  const names = useResourceNames();
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {mode === "suggested" ? <th>Accept</th> : null}
            <th>Line</th>
            <th>When</th>
            <th className="right">Hours</th>
            <th className="right">Cost</th>
            <th>{mode === "suggested" ? "Lateness saved" : "Why"}</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={mode === "suggested" ? 7 : 6} className="muted">
                None: no work would otherwise be late.
              </td>
            </tr>
          ) : null}
          {rows.map((w) => {
            const s = STATUS[w.status];
            const k = keyOf(w);
            return (
              <tr key={k} data-testid="overtime-row" data-status={w.status} data-line={names.line(w.line_id).code} data-saved={w.tardiness_saved_minutes ?? ""}>
                {mode === "suggested" ? (
                  <td>
                    <input type="checkbox" checked={accepted?.has(k) ?? false} disabled={!canAccept} onChange={() => onToggle?.(w)} aria-label={`Accept extra shift on ${names.line(w.line_id).code} ${clock.dateTime(w.start)}`} data-testid="overtime-accept" />
                  </td>
                ) : null}
                <td className="mono">
                  {names.line(w.line_id).code}
                  {names.line(w.line_id).group_id ? <span className="faint small"> · {names.group(names.line(w.line_id).group_id).code}</span> : null}
                </td>
                <td className="small">
                  {clock.dateTime(w.start)} – {clock.time(w.end)}
                </td>
                <td className="right">{(w.minutes / 60).toFixed(1)}</td>
                <td className="right">{fmtNum(Math.round(w.cost))}</td>
                <td className="small">
                  {mode === "suggested" ? <strong>{fmtDuration(w.tardiness_saved_minutes ?? 0)} weighted</strong> : null}
                  {w.reason ? (
                    <div className={mode === "suggested" ? "faint" : undefined} data-testid="overtime-reason">
                      {w.reason}
                    </div>
                  ) : mode === "opened" ? (
                    <div>{w.status === "forced" ? "Opened by you." : "Opened for work that would otherwise be late."}</div>
                  ) : null}
                  {w.orders?.length ? (
                    <ul className="mfg-ot-orders" data-testid="overtime-orders">
                      {w.orders.map((o) => (
                        <li key={o.order.id}>
                          <Link to={orderLink(o.order, runId)} className="mono">
                            {o.order.number}
                          </Link>{" "}
                          <span className="faint">
                            {fmtDuration(o.minutes)} in this shift{o.op_nos.length ? ` (op ${o.op_nos.join(", ")})` : ""}
                            {o.late_minutes > 0 ? ` · ${fmtDuration(o.late_minutes)} late` : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </td>
                <td>
                  <span className={`badge ${s.tone}`}>
                    <Icon name={s.icon} /> {s.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
