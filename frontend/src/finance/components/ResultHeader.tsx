import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import { contributionsCsvUrl } from "../api/client";
import type { FinanceResultRecord } from "../api/types";
import { fmtLocal } from "../../lib/time";
import { StatusPill } from "./StatusPill";
import { plural, t } from "../../lib/i18n";

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
        ? t("finance.resultHeader.tpl.planIsValidGoalShort", { short: short, v: short === 1 ? " is" : "s are" })
        : t("finance.resultHeader.str.planIsValidEveryGoal")
      : r.feasibility === "infeasible"
        ? t("finance.resultHeader.str.yourCashFlowCannotCover")
        : t("finance.resultHeader.str.thePlanCouldNotBe");
  return (
    <div className="col">
      <div className="fin-header">
        <div className="col" style={{ gap: 4 }}>
          <div className="row wrap">
            <h1>{record.kind === "what_if" ? t("finance.resultHeader.tpl.whatIf", { v: record.label ?? "scenario" }) : t("finance.resultHeader.str.yourFinancialPlan")}</h1>
            <StatusPill kind={r.feasibility} testId="fin-feasibility" />
            {record.label && record.kind === "baseline" ? <span className="chip">{record.label}</span> : null}
          </div>
          <span className="muted">{verdict}</span>
          <span className="small faint">
            {t("finance.resultHeader.text.madeForVersionMonths", { createdat: fmtLocal(record.created_at), baseplanversion: record.base_plan_version, length: plural(r.goals.length, "goal"), horizonmonths: r.horizon_months })}
          </span>
        </div>
        <div className="fin-actions">
          <Link className="btn" to={`/finance/${planId}/what-if${record.kind === "baseline" ? `?base=${record.id}` : ""}`} data-testid="open-what-if">
            <Icon name="refresh" /> {t("finance.resultHeader.btn.whatif")}
          </Link>
          <Link className="btn" to={`/finance/${planId}/compare?a=${record.id}`} data-testid="open-compare">
            <Icon name="compare" /> {t("finance.resultHeader.btn.compare")}
          </Link>
          <a className="btn" href={contributionsCsvUrl(record.id)} download data-testid="fin-export-csv">
            <Icon name="download" /> {t("finance.resultHeader.btn.exportCsv")}
          </a>
          <button
            className="btn"
            onClick={onSend}
            data-testid="send-to-planner"
            disabled={r.feasibility !== "feasible"}
            title={r.feasibility !== "feasible" ? t("finance.resultHeader.str.onlyValidPlansCanBe") : t("finance.resultHeader.str.createAMoneyCalendarIn")}
          >
            <Icon name="calendar" /> {t("finance.resultHeader.btn.sendToPlanner")}
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
            {t("finance.resultHeader.text.thisResultWasMadeFor", { baseplanversion: record.base_plan_version, planVersion: planVersion })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
