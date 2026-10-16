import { Icon } from "../../components/Icon";
import type { GoalResult } from "../api/types";
import { formatMoney, formatProb, roundDisplay } from "../lib/money";
import { fmtMonth } from "../lib/months";
import { StatusPill } from "./StatusPill";

const PRIORITY_LABEL = { must: "Must have", should: "Should have", nice: "Nice to have" } as const;

export function GoalCard({ goal, currency, locale }: { goal: GoalResult; currency: string; locale: string }) {
  const m = (v: number) => formatMoney(roundDisplay(v), currency, locale);
  const pct = Math.max(0, Math.min(1, goal.success_probability));
  return (
    <article className="card goal-card" data-testid={`goal-card-${goal.goal_id}`} aria-labelledby={`gc-${goal.goal_id}`}>
      <div className="card-body">
        <div className="goal-card-head">
          <div>
            <h3 id={`gc-${goal.goal_id}`}>{goal.name}</h3>
            <div className="small muted">
              {PRIORITY_LABEL[goal.priority]} · due {fmtMonth(goal.target_month)}
            </div>
          </div>
          <StatusPill kind={goal.status} testId={`goal-status-${goal.goal_id}`} />
        </div>
        <div className="chance">
          <div className="chance-text" data-testid={`goal-success-${goal.goal_id}`}>
            <span>
              Estimated chance: <strong>{formatProb(goal.success_probability)}</strong>
            </span>
            <span className="small muted">you asked for {formatProb(goal.min_success_probability)}</span>
          </div>
          <div
            className="chance-bar"
            role="meter"
            aria-label={`Estimated chance of reaching ${goal.name} on time`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pct * 100)}
            aria-valuetext={`${formatProb(pct)}, target at least ${formatProb(goal.min_success_probability)}`}
          >
            <div className={`fill ${goal.status}`} style={{ width: `${pct * 100}%` }} />
            <div className="target" style={{ left: `${goal.min_success_probability * 100}%` }} title="Your minimum" />
          </div>
        </div>
        <dl className="goal-facts">
          <dt>Target (today's money)</dt>
          <dd>{m(goal.target_real)}</dd>
          <dt>Expected future cost</dt>
          <dd>{m(goal.target_nominal_expected)}</dd>
          <dt>Likely range (p10 - p90)</dt>
          <dd>
            {formatMoney(goal.p10_real, currency, locale, { compact: true })} - {formatMoney(goal.p90_real, currency, locale, { compact: true })}
          </dd>
          <dt>Projected (expected returns)</dt>
          <dd>{m(goal.projected_central_real)}</dd>
          <dt>In a weak market</dt>
          <dd>{m(goal.scenario_low_real)}</dd>
          <dt>Monthly now</dt>
          <dd>{m(goal.monthly_contribution_now)}</dd>
          <dt>Contributions</dt>
          <dd>
            {goal.contribution_start_month
              ? `${fmtMonth(goal.contribution_start_month)} - ${fmtMonth(goal.contribution_end_month)}`
              : "none planned"}
          </dd>
          {goal.holdings_used_real > 0 ? (
            <>
              <dt>Existing savings used</dt>
              <dd>{m(goal.holdings_used_real)}</dd>
            </>
          ) : null}
        </dl>
        {goal.shortfall_real > 0.5 ? (
          <div className="small row" style={{ color: "var(--danger)" }}>
            <Icon name="alert" /> Short by {m(goal.shortfall_real)} even with cautious planning.
          </div>
        ) : null}
        <div className="small faint">All values in today's money unless marked as future.</div>
      </div>
    </article>
  );
}
