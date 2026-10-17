import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import { contributionsCsvUrl } from "../api/client";
import type { FinanceResultRecord } from "../api/types";
import { fmtLocal } from "../../lib/time";
import { StatusPill } from "./StatusPill";

export interface ResultHeaderProps {
  planId: string;
  record: FinanceResultRecord;
  planVersion: number;
  onRerun(): void;
  rerunning: boolean;
  onSend(): void;
}

export function ResultHeader({ planId, record, planVersion, onRerun, rerunning, onSend }: ResultHeaderProps) {
  const r = record.result;
  const s = r.summary;
  const short = s.goals_total - s.goals_on_track;
  const stale = planVersion > record.base_plan_version;
  const verdict =
    r.feasibility === "feasible"
      ? short > 0
        ? `Plan is valid; ${short} goal${short === 1 ? " is" : "s are"} short of the chance you asked for.`
        : "Plan is valid; every goal is on track."
      : r.feasibility === "infeasible"
        ? "Your cash flow cannot cover your fixed costs in some months, even after using existing savings. The plan below shows the closest it can get."
        : "The plan could not be fully checked. Review the details below before relying on it.";
  return (
    <div className="col">
      <div className="fin-header">
        <div className="col" style={{ gap: 4 }}>
          <div className="row wrap">
            <h1>{record.kind === "what_if" ? `What-if: ${record.label ?? "scenario"}` : "Your financial plan"}</h1>
            <StatusPill kind={r.feasibility} testId="fin-feasibility" />
            {record.label && record.kind === "baseline" ? <span className="chip">{record.label}</span> : null}
          </div>
          <span className="muted">{verdict}</span>
          <span className="small faint">
            Made {fmtLocal(record.created_at)} for version {record.base_plan_version} · {r.goals.length} goal{r.goals.length === 1 ? "" : "s"} · {r.horizon_months} months
          </span>
        </div>
        <div className="fin-actions">
          <Link className="btn" to={`/finance/${planId}/what-if${record.kind === "baseline" ? `?base=${record.id}` : ""}`} data-testid="open-what-if">
            <Icon name="refresh" /> What-if
          </Link>
          <Link className="btn" to={`/finance/${planId}/compare?a=${record.id}`} data-testid="open-compare">
            <Icon name="compare" /> Compare
          </Link>
          <a className="btn" href={contributionsCsvUrl(record.id)} download data-testid="fin-export-csv">
            <Icon name="download" /> Export CSV
          </a>
          <button
            className="btn"
            onClick={onSend}
            data-testid="send-to-planner"
            disabled={r.feasibility !== "feasible"}
            title={r.feasibility !== "feasible" ? "Only valid plans can be sent to the planner" : "Create a money calendar in the scheduler"}
          >
            <Icon name="calendar" /> Send to planner
          </button>
          <button className="btn primary" onClick={onRerun} disabled={rerunning} data-testid="fin-rerun">
            {rerunning ? <span className="spinner" aria-hidden /> : <Icon name="play" />} Re-run
          </button>
        </div>
      </div>
      {stale ? (
        <div className="banner warn" role="status" data-testid="fin-stale-result">
          <Icon name="alert" />
          <div className="banner-body">
            This result was made for version {record.base_plan_version} of your plan; you have edited it since (now version {planVersion}).
            Re-run to update it.
          </div>
        </div>
      ) : null}
    </div>
  );
}
