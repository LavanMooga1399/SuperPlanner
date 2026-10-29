/** `/mfg/mrp` (M2 14.2): MRP runs (kind, status, KPIs, stale, pinned) and the "Run MRP" form. */
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { listMrpRuns, updateMrpRun } from "../../api/clientM2";
import type { MrpRunRecord } from "../../api/typesM2";
import { MfgError, Spinner } from "../../components/Feedback";
import { PermissionGate } from "../../components/PermissionGate";
import { RunKindBadge, RunStatusChip } from "../../components/StatusM2";
import { fmtDate, fmtTimestamp } from "../../lib/format";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { useLoad } from "../../lib/useMfg";
import { MrpRunForm } from "./MrpRunForm";

export function runTitle(r: MrpRunRecord): string {
  return `Run #${r.run_no}${r.label ? ` · ${r.label}` : ""}`;
}

export function MrpRunsPage() {
  const navigate = useNavigate();
  const canRun = useCan("mrp_run");
  const runs = useLoad((signal) => listMrpRuns({ limit: 50, offset: 0 }, signal), []);
  const [form, setForm] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const items = runs.data?.items ?? [];
  const latestLive = items.find((r) => r.kind === "live" && r.status === "completed");

  const pin = async (r: MrpRunRecord) => {
    setError(null);
    try {
      await updateMrpRun(r.id, { label: r.label, note: r.note, pinned: !r.pinned }, r.row_version);
      runs.reload();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div className="col gap-lg">
      <div className="page-header mfg-header">
        <div>
          <h1>Material planning (MRP)</h1>
          <p>Plan what to make and buy for all open demand at once, see which orders will be late and why, then firm or release the planned orders.</p>
        </div>
        <PermissionGate perm="mrp_run">
          <button type="button" className="btn primary" onClick={() => setForm(true)} disabled={form} data-testid="mrp-new-run">
            <Icon name="play" /> Run MRP
          </button>
        </PermissionGate>
      </div>
      {form ? <MrpRunForm onClose={() => setForm(false)} onDone={(r) => navigate(mfgPaths.run(r.id))} /> : null}
      <MfgError error={runs.error ?? error} onRetry={runs.reload} />
      {runs.loading && !runs.data ? <Spinner /> : null}
      {runs.data && items.length === 0 && !form ? (
        <Banner tone="info" title="No plan yet" testId="mrp-empty">
          {canRun ? "Run MRP to plan materials for every open demand order." : "Nobody has run MRP in this plant yet."} Demand orders must be open, and data health must have no errors.
        </Banner>
      ) : null}
      {items.length ? (
        <div className="table-wrap card">
          <table className="table" data-testid="mrp-runs">
            <thead>
              <tr>
                <th>Run</th>
                <th>Kind</th>
                <th>Status</th>
                <th>As of</th>
                <th className="right">Late demand</th>
                <th className="right">Parts short</th>
                <th className="right">Planned make / buy</th>
                <th>Finished</th>
                <th>By</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => {
                const s = r.summary;
                return (
                  <tr key={r.id} data-testid="mrp-run-row" data-run-no={r.run_no} data-kind={r.kind} data-status={r.status}>
                    <td>
                      <Link to={mfgPaths.run(r.id)}>{runTitle(r)}</Link>
                      {r.id === latestLive?.id ? (
                        <span className="badge accent" style={{ marginLeft: 6 }} title="Planned orders can be firmed or released only from this run">
                          <Icon name="star" /> Latest
                        </span>
                      ) : null}
                      {r.pinned ? (
                        <span className="badge info" style={{ marginLeft: 6 }}>
                          <Icon name="lock" /> Kept
                        </span>
                      ) : null}
                      {r.stale?.is_stale ? (
                        <span className="badge warn" style={{ marginLeft: 6 }} title="Data changed after this run">
                          <Icon name="clock" /> Out of date
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <RunKindBadge kind={r.kind} />
                    </td>
                    <td>
                      <RunStatusChip status={r.status} />
                    </td>
                    <td>{fmtDate(r.as_of)}</td>
                    <td className="right">{s ? <span className={s.demand_late + s.demand_past_due ? "mfg-neg" : undefined}>{s.demand_late + s.demand_past_due} of {s.demand_lines}</span> : ""}</td>
                    <td className="right">{s ? s.items_short.toLocaleString() : ""}</td>
                    <td className="right">{s ? `${s.planned_make.toLocaleString()} / ${s.planned_buy.toLocaleString()}` : ""}</td>
                    <td className="small">{fmtTimestamp(r.finished_at)}</td>
                    <td className="small">{r.actor.name}</td>
                    <td className="right">
                      {canRun ? (
                        <button type="button" className="btn sm ghost" onClick={() => void pin(r)} title={r.pinned ? "Allow automatic clean-up of this run" : "Keep this run (otherwise only the last 10 are kept)"}>
                          <Icon name={r.pinned ? "unlock" : "lock"} /> {r.pinned ? "Unkeep" : "Keep"}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
