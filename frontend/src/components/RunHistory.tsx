import { Link } from "react-router-dom";
import type { SolverRun } from "../api/types";
import type { Terms } from "../lib/terms";
import { fmtDuration, fmtLocal, fmtMoney, fmtSeconds } from "../lib/time";
import { Icon } from "./Icon";
import { methodLabel } from "./RunProgress";
import { StatusBadge } from "./StatusBadge";

export function RunHistory({
  runs,
  currentRunId,
  terms,
  currency,
  onRefresh,
}: {
  runs: SolverRun[];
  currentRunId: string | null;
  terms: Terms;
  currency: string;
  onRefresh(): void;
}) {
  return (
    <div className="card" data-testid="run-history">
      <div className="card-header">
        <h3>Run history</h3>
        <button className="btn ghost sm" onClick={onRefresh} aria-label="Refresh run history">
          <Icon name="refresh" />
        </button>
      </div>
      {runs.length === 0 ? (
        <div className="empty small">No runs yet.</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Started</th>
                <th>Status</th>
                <th>Result</th>
                <th>Method</th>
                <th className="num">Duration</th>
                <th className="num">Cost</th>
                <th className="num">Took</th>
                <th><span className="sr-only">Links</span></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className={r.id === currentRunId ? "highlight" : undefined} data-testid={`run-row-${r.id}`}>
                  <td className="nowrap">
                    {fmtLocal(r.created_at)}
                    {r.source_schedule_id ? <span className="chip" style={{ marginLeft: 6 }}>Replan</span> : null}
                  </td>
                  <td><StatusBadge kind={r.status} /></td>
                  <td>{r.feasibility ? <StatusBadge kind={r.feasibility} /> : <span className="faint">-</span>}</td>
                  <td className="small">{r.selection ? r.selection.used.map(methodLabel).join(" → ") : String(r.request?.strategy ?? "auto")}</td>
                  <td className="num">{r.objectives ? fmtDuration(r.objectives.makespan_minutes) : "-"}</td>
                  <td className="num">{r.objectives ? fmtMoney(r.objectives.cost, currency) : "-"}</td>
                  <td className="num">{fmtSeconds(r.elapsed_seconds)}</td>
                  <td className="nowrap">
                    <Link className="btn ghost sm" to={`?run=${encodeURIComponent(r.id)}`}>Details</Link>
                    {r.primary_schedule_id ? (
                      <Link className="btn ghost sm" to={`../schedule?id=${encodeURIComponent(r.primary_schedule_id)}`}>
                        {terms.schedule}
                      </Link>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
