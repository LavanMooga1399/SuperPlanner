import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { errorMessage, validateProblem } from "../../api/client";
import type { ValidateResponse } from "../../api/types";
import { Banner, ErrorBanner, Loading } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { IssueList } from "../../components/IssueList";
import { StatusBadge } from "../../components/StatusBadge";
import { useTerms } from "../../lib/terms";
import { fmtDuration, fmtMinute } from "../../lib/time";
import { useLoadedPlan } from "../../state/PlanContext";

export function ValidateTab() {
  const plan = useLoadedPlan();
  const { draft, record } = plan;
  const terms = useTerms();
  const [report, setReport] = useState<ValidateResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const saved = await plan.save();
      if (!saved) {
        setError("Your latest edits could not be saved, so the stored version would be checked. Resolve the save problem first.");
        return;
      }
      setReport(await validateProblem(plan.planId));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }, [plan]);

  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const names = new Map(draft.tasks.map((t) => [t.id, t.name]));
  const errors = report?.issues.filter((i) => i.severity === "error").length ?? 0;
  const warnings = report?.issues.filter((i) => i.severity === "warning").length ?? 0;
  const stale = report && report.problem_version !== record.version;

  return (
    <div className="col gap-lg">
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <button className="btn primary" onClick={() => void run()} disabled={busy}>
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />}
          {report ? "Check again" : "Check plan"}
        </button>
        {report ? (
          report.ok ? (
            <StatusBadge kind="feasible" label={warnings ? `Ready, ${warnings} warning${warnings === 1 ? "" : "s"}` : "Ready to optimize"} testId="validate-status" />
          ) : (
            <StatusBadge kind="error" label={`${errors} error${errors === 1 ? "" : "s"} to fix`} testId="validate-status" />
          )
        ) : null}
        {report ? <span className="small muted">Checked version {report.problem_version}</span> : null}
        {stale ? <span className="badge warn"><Icon name="alert" /> Plan changed since this check</span> : null}
      </div>
      <ErrorBanner error={error} />
      {!report && busy ? <Loading label="Checking the plan…" /> : null}
      {report ? (
        <div className="split">
          <IssueList issues={report.issues} draft={draft} terms={terms} />
          <div className="col">
            {report.ok ? (
              <Banner tone="ok" title="Ready to optimize" actions={<Link className="btn sm primary" to="../optimize"><Icon name="play" /> Optimize</Link>}>
                No blocking problems.
              </Banner>
            ) : null}
            <div className="card">
              <div className="card-header"><h3>Critical path (lower bound)</h3></div>
              <div className="card-body col">
                {report.cpm ? (
                  <>
                    <div className="kpi" style={{ padding: 0 }}>
                      <div className="kpi-label">Shortest possible completion</div>
                      <div className="kpi-value">{fmtDuration(report.cpm.lower_bound_makespan_minutes)}</div>
                      <div className="kpi-sub">at the earliest {fmtMinute(report.cpm.lower_bound_makespan_minutes, draft.horizon_start)}, with unlimited {terms.resourcesL} and no closed times</div>
                    </div>
                    {report.cpm.critical_path.length ? (
                      <ol className="small" style={{ margin: 0, paddingLeft: 20 }}>
                        {report.cpm.critical_path.map((id) => (
                          <li key={id}>
                            {names.get(id) ?? id} <span className="faint">({fmtDuration(draft.tasks.find((t) => t.id === id)?.duration_minutes ?? 0)})</span>
                          </li>
                        ))}
                      </ol>
                    ) : null}
                    <div className="small muted">
                      {Object.values(report.cpm.tasks).filter((t) => t.critical).length} of {Object.keys(report.cpm.tasks).length} {terms.tasksL} have no slack.
                    </div>
                  </>
                ) : (
                  <div className="small muted">Available once structural errors (unknown references, loops) are fixed.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
