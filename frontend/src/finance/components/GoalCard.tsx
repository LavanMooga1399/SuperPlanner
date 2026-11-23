import { Icon } from "../../components/Icon";
import { Term } from "../../components/Term";
import type { GoalResult, Reason } from "../api/types";
import { formatMoney, formatProb, roundDisplay } from "../lib/money";
import { fmtMonth } from "../lib/months";
import { StatusPill } from "./StatusPill";
import { t } from "../../lib/i18n";

const PRIORITY_LABEL = { must: t("finance.goalCard.str.mustHave"), should: t("finance.goalCard.str.shouldHave"), nice: t("finance.goalCard.str.niceToHave") } as const;

/** The goal's "why this mix" reason (PHASE2 1.10): its first reason when that is a `GROWTH_*` one. */
export function growthReason(reasons: Reason[] | undefined): Reason | null {
  const r = reasons?.[0];
  return r && r.code.startsWith("GROWTH_") ? r : null;
}

export function GoalCard({ goal, currency, locale, reason }: { goal: GoalResult; currency: string; locale: string; reason?: Reason | null }) {
  const m = (v: number) => formatMoney(roundDisplay(v), currency, locale);
  const pct = Math.max(0, Math.min(1, goal.success_probability));
  const likelyPct = goal.target_real > 0 ? Math.round((goal.p50_real / goal.target_real) * 100) : null;
  const share = goal.growth_share_now_pct;
  const cap = goal.growth_cap_now_pct;
  const hasGrowth = share !== undefined && cap !== undefined;
  const fmtPct = (v: number) => `${Math.round(v)}%`;
  return (
    <article className="card goal-card" data-testid={`goal-card-${goal.goal_id}`} aria-labelledby={`gc-${goal.goal_id}`}>
      <div className="card-body">
        <div className="goal-card-head">
          <div>
            <h3 id={`gc-${goal.goal_id}`}>{goal.name}</h3>
            <div className="small muted">
              {t("finance.goalCard.text.due", { v: PRIORITY_LABEL[goal.priority], targetmonth: fmtMonth(goal.target_month) })}
            </div>
          </div>
          <StatusPill kind={goal.status} testId={`goal-status-${goal.goal_id}`} />
        </div>
        <div className="chance">
          <div className="chance-text" data-testid={`goal-success-${goal.goal_id}`}>
            <span>
              <Term k="chance_of_success">{t("finance.goalCard.text.estimatedChance")}</Term>: <strong>{formatProb(goal.success_probability)}</strong>
            </span>
            <span className="small muted">{t("finance.goalCard.text.youAskedFor", { minsuccessprobability: formatProb(goal.min_success_probability) })}</span>
          </div>
          <div
            className="chance-bar"
            role="meter"
            aria-label={t("finance.goalCard.tpl.estimatedChanceOfReachingOn", { name: goal.name })}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pct * 100)}
            aria-valuetext={`${formatProb(pct)}, target at least ${formatProb(goal.min_success_probability)}`}
          >
            <div className={`fill ${goal.status}`} style={{ width: `${pct * 100}%` }} />
            <div className="target" style={{ left: `${goal.min_success_probability * 100}%` }} title={t("finance.goalCard.attr.yourMinimum")} />
          </div>
        </div>
        {likelyPct !== null ? (
          <div className="small" data-testid={`goal-likely-${goal.goal_id}`}>
            {t("finance.goalCard.text.likelyOutcomeAboutOfThe", { likelyPct: likelyPct })}
            <span className="muted">{" "}{t("finance.goalCard.text.inATypicalMarket", { v: likelyPct < 100 && goal.success_probability < goal.min_success_probability ? t("finance.goalCard.str.theGapMayBeSmaller") : "" })}</span>
          </div>
        ) : null}
        {hasGrowth ? (
          <div className="chance" data-testid={`goal-growth-${goal.goal_id}`}>
            <div className="small">
              <Term k="growth_assets">{t("finance.goalCard.text.growthAssets")}</Term>{" "}{t("finance.goalCard.text.nowLimit", { share: fmtPct(share), cap: fmtPct(cap) })}
            </div>
            <div
              className="chance-bar growth-bar"
              role="meter"
              aria-label={t("finance.goalCard.tpl.shareOfGrowthAssetsFor", { name: goal.name })}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(share)}
              aria-valuetext={`${fmtPct(share)}, limit ${fmtPct(cap)}`}
            >
              <div className="fill" style={{ width: `${Math.max(0, Math.min(100, share))}%` }} />
              <div className="target" style={{ left: `${Math.max(0, Math.min(100, cap))}%` }} title={t("finance.goalCard.attr.limitForThisGoalNow")} />
            </div>
          </div>
        ) : null}
        {reason ? (
          <div className="small why-mix" data-testid={`goal-why-${goal.goal_id}`}>
            <strong>{t("finance.goalCard.text.whyThisMix")}</strong> {reason.message}
          </div>
        ) : null}
        <dl className="goal-facts">
          <dt>{t("finance.goalCard.head.targetTodaysMoney")}</dt>
          <dd>{m(goal.target_real)}</dd>
          <dt>{t("finance.goalCard.head.expectedFutureCost")}</dt>
          <dd>{m(goal.target_nominal_expected)}</dd>
          <dt>{t("finance.goalCard.head.likelyRangeP10P90")}</dt>
          <dd>
            {formatMoney(goal.p10_real, currency, locale, { compact: true })} - {formatMoney(goal.p90_real, currency, locale, { compact: true })}
          </dd>
          <dt>{t("finance.goalCard.head.projectedExpectedReturns")}</dt>
          <dd>{m(goal.projected_central_real)}</dd>
          <dt>{t("finance.goalCard.head.inAWeakMarket")}</dt>
          <dd>{m(goal.scenario_low_real)}</dd>
          <dt>{t("finance.goalCard.head.monthlyNow")}</dt>
          <dd>{m(goal.monthly_contribution_now)}</dd>
          <dt>{t("finance.goalCard.head.contributions")}</dt>
          <dd>
            {goal.contribution_start_month
              ? `${fmtMonth(goal.contribution_start_month)} - ${fmtMonth(goal.contribution_end_month)}`
              : t("finance.goalCard.str.nonePlanned")}
          </dd>
          {goal.holdings_used_real > 0 ? (
            <>
              <dt>{t("finance.goalCard.head.existingSavingsUsed")}</dt>
              <dd>{m(goal.holdings_used_real)}</dd>
            </>
          ) : null}
        </dl>
        {goal.shortfall_real > 0.5 ? (
          <div className="small row" style={{ color: "var(--danger)" }}>
            <Icon name="alert" />{" "}{t("finance.goalCard.text.shortByEvenWithCautious", { shortfallreal: m(goal.shortfall_real) })}{" "}<Term k="shortfall" bare />
          </div>
        ) : null}
        <div className="small faint">
          {t("finance.goalCard.text.allValuesIn")}{" "}<Term k="todays_money">today's money</Term>{" "}{t("finance.goalCard.text.unlessMarkedAsFuture")}
        </div>
      </div>
    </article>
  );
}
