/**
 * `/mfg/schedule` (M3 12): schedule runs with status, live progress (polled every 2 s while a run is queued or
 * running), KPIs and the published badge; "New schedule" form. Router state `{ prefill: ApsParams }` opens the
 * form prefilled (overtime tab "Re-run with these opened").
 */
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { listApsRuns } from "../../api/clientM3";
import type { ApsParams, ApsRunRecord } from "../../api/typesM3";
import { ApsProgress, ApsStatusChip, PolicyBadge, PublishedBadge } from "../../components/ApsBits";
import { MfgError, Spinner } from "../../components/Feedback";
import { PermissionGate } from "../../components/PermissionGate";
import { RunKindBadge } from "../../components/StatusM2";
import { fmtTimestamp } from "../../lib/format";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { usePolling } from "../../lib/usePolling";
import { useLoad } from "../../lib/useMfg";
import { ApsRunForm } from "./ApsRunForm";

export function apsRunTitle(r: Pick<ApsRunRecord, "run_no" | "label">): string {
  return `Schedule #${r.run_no}${r.label ? ` · ${r.label}` : ""}`;
}

export function isActive(r: ApsRunRecord): boolean {
  return r.status === "queued" || r.status === "running";
}

export function ApsRunsPage() {
  const navigate = useNavigate();
  const loc = useLocation();
  const prefill = (loc.state as { prefill?: ApsParams } | null)?.prefill ?? null;
  const canRun = useCan("schedule_run");
  const clock = usePlantClock();
  const runs = useLoad((signal) => listApsRuns({ limit: 50, offset: 0 }, signal), []);
  const [form, setForm] = useState(Boolean(prefill));
  const items = runs.data?.items ?? [];
  usePolling(runs.reload, items.some(isActive));

  return (
    <div className="col gap-lg">
      <div className="page-header mfg-header">
        <div>
          <h1>Production schedule</h1>
          <p>Finite-capacity plan of every operation on the lines, shift by shift, for all orders at once. Publish one run as the plant plan.</p>
        </div>
        <PermissionGate perm="schedule_run">
          <button type="button" className="btn primary" onClick={() => setForm(true)} disabled={form} data-testid="aps-new-run">
            <Icon name="play" /> New schedule
          </button>
        </PermissionGate>
      </div>
      {form ? (
        <ApsRunForm
          initial={prefill}
          onClose={() => setForm(false)}
          onDone={(r) => {
            setForm(false);
            navigate(mfgPaths.apsRun(r.id));
          }}
        />
      ) : null}
      <MfgError error={runs.error} onRetry={runs.reload} />
      {runs.loading && !runs.data ? <Spinner /> : null}
      {runs.data && items.length === 0 && !form ? (
        <Banner tone="info" title="No schedule yet" testId="aps-empty">
          {canRun ? "Create a schedule to place every operation on the lines." : "Nobody has scheduled this plant yet."} It uses the latest MRP run for planned orders and
          material dates.
        </Banner>
      ) : null}
      {items.length ? (
        <div className="table-wrap card">
          <table className="table" data-testid="aps-runs">
            <thead>
              <tr>
                <th>Run</th>
                <th>Kind</th>
                <th>Status</th>
                <th>Overtime</th>
                <th>From</th>
                <th className="right">Late orders</th>
                <th className="right">Weighted lateness</th>
                <th className="right">Overtime</th>
                <th>Finished</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => {
                const s = r.summary;
                return (
                  <tr key={r.id} data-testid="aps-run-row" data-run-no={r.run_no} data-status={r.status} data-published={r.is_published}>
                    <td>
                      <Link to={mfgPaths.apsRun(r.id)}>{apsRunTitle(r)}</Link> {r.is_published ? <PublishedBadge /> : null}
                      {r.parent_run_id ? <div className="faint small">edited copy</div> : null}
                    </td>
                    <td>
                      <RunKindBadge kind={r.kind} />
                    </td>
                    <td>
                      {isActive(r) ? <ApsProgress run={r} /> : <ApsStatusChip run={r} />}
                    </td>
                    <td>
                      <PolicyBadge policy={r.policy} />
                    </td>
                    <td className="small">{clock.dateTime(r.as_of)}</td>
                    <td className="right">{s ? <span className={s.late_orders ? "mfg-neg" : undefined}>{s.late_orders}</span> : ""}</td>
                    <td className="right">{s ? fmtDuration(s.weighted_tardiness) || "0" : ""}</td>
                    <td className="right">{s ? fmtDuration(s.overtime_minutes) || "none" : ""}</td>
                    <td className="small">
                      {fmtTimestamp(r.finished_at)} {r.actor.name}
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
