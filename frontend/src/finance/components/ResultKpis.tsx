import type { FinanceResult } from "../api/types";
import { formatMoney, formatProb, roundDisplay } from "../lib/money";
import { fmtMonth } from "../lib/months";
import { t } from "../../lib/i18n";

interface Kpi {
  label: string;
  value: string;
  sub: string;
  title?: string;
  tone?: string;
}

/**
 * PHASE2 3.4: the first two cards show first-year averages (1.11); month-0 values are in the card's title.
 * Results from older engine versions have no averages and fall back to the month-0 values.
 */
export function ResultKpis({ result, locale }: { result: FinanceResult; locale: string }) {
  const s = result.summary;
  const m = (v: number) => formatMoney(roundDisplay(v), result.currency, locale);
  // whole currency units, so the cards match the explanation sentences ("about ₹69,167/month")
  const w = (v: number) => formatMoney(Math.round(v), result.currency, locale);

  const surplus = s.monthly_surplus_avg_12m ?? s.monthly_investable_now;
  const ef = s.monthly_ef_contribution_avg_12m ?? 0;
  const contributing = s.monthly_contribution_avg_12m ?? s.monthly_contribution_now;
  const fromSurplus = s.monthly_from_surplus_avg_12m;
  const fromSavings = s.monthly_from_savings_avg_12m;
  const hasAvg = s.monthly_surplus_avg_12m !== undefined;
  const nowTitle = (v: number, what: string) => t("finance.resultKpis.tpl.thisMonth", { v: m(v), what: what });

  const surplusCard: Kpi =
    surplus >= 0
      ? {
          label: t("finance.resultKpis.str.leftOverEachMonth"),
          value: w(surplus),
          sub: t("finance.resultKpis.tpl.afterExpensesAndLoans", { v: hasAvg ? t("finance.resultKpis.str.firstYearAverage") : t("finance.resultKpis.str.thisMonth"), v2: ef >= 1 ? t("finance.resultKpis.tpl.ofItBuildsYourEmergency", { ef: w(ef) }) : "" }),
          title: nowTitle(s.monthly_investable_now, t("finance.resultKpis.str.leftToInvestAfterExpenses")),
        }
      : {
          label: t("finance.resultKpis.str.shortEachMonth"),
          value: w(-surplus),
          sub: t("finance.resultKpis.tpl.spendingAndLoanPaymentsAre", { v: hasAvg ? "first-year average" : "this month" }),
          title: nowTitle(s.monthly_investable_now, t("finance.resultKpis.str.leftToInvest")),
          tone: "var(--danger)",
        };

  let investSub: string;
  if (contributing < 0.5) investSub = t("finance.resultKpis.str.noNewMonthlyInvestmentsNeeded");
  else if (fromSurplus !== undefined && fromSavings !== undefined && fromSavings >= 1)
    investSub = t("finance.resultKpis.tpl.fromYourMonthlySurplusFrom", { fromSurplus: w(fromSurplus), fromSavings: w(fromSavings) });
  else if (fromSurplus !== undefined) investSub = t("finance.resultKpis.str.allFromYourMonthlySurplus");
  else investSub = t("finance.resultKpis.str.perMonthAcrossGoalsAnd");

  const cards: Kpi[] = [
    surplusCard,
    {
      label: t("finance.resultKpis.str.planInvests"),
      value: w(contributing),
      sub: hasAvg ? t("finance.resultKpis.tpl.aMonthOnAverageIn", { investSub: investSub }) : investSub,
      title: nowTitle(s.monthly_contribution_now, t("finance.resultKpis.str.investedAcrossGoalsAndEmergency")),
    },
    {
      label: t("finance.resultKpis.str.emergencyFund"),
      value: m(s.emergency_fund_target),
      sub: s.emergency_fund_complete_month ? t("finance.resultKpis.tpl.targetCompleteBy", { emergencyfundcompletemonth: fmtMonth(s.emergency_fund_complete_month) }) : t("finance.resultKpis.str.targetNotReachedInThe"),
    },
    { label: t("finance.resultKpis.str.goalsOnTrack"), value: `${s.goals_on_track} / ${s.goals_total}`, sub: s.goals_at_risk ? t("finance.resultKpis.tpl.atRiskOffTrack", { goalsatrisk: s.goals_at_risk, goalsofftrack: s.goals_off_track }) : t("finance.resultKpis.tpl.offTrack", { goalsofftrack: s.goals_off_track }) },
    {
      label: t("finance.resultKpis.str.cashShortfallRisk"),
      value: formatProb(s.liquidity_risk_probability),
      sub: t("finance.resultKpis.str.estimatedChanceOfAtLeast"),
      tone: s.liquidity_risk_probability > 0.1 ? "var(--warn)" : undefined,
    },
  ];
  return (
    <div className="kpis" data-testid="fin-kpis">
      {cards.map((c) => (
        <div className="card kpi" key={c.label} title={c.title}>
          <div className="kpi-label">{c.label}</div>
          <div className="kpi-value" style={c.tone ? { color: c.tone } : undefined}>{c.value}</div>
          <div className="kpi-sub">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}
