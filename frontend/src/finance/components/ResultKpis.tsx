import type { FinanceResult } from "../api/types";
import { formatMoney, formatProb, roundDisplay } from "../lib/money";
import { fmtMonth } from "../lib/months";

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
  const nowTitle = (v: number, what: string) => `This month: ${m(v)} ${what}`;

  const surplusCard: Kpi =
    surplus >= 0
      ? {
          label: "Left over each month",
          value: w(surplus),
          sub: `${hasAvg ? "first-year average" : "this month"} after expenses and loans${ef >= 1 ? `; ${w(ef)} of it builds your emergency fund` : ""}`,
          title: nowTitle(s.monthly_investable_now, "left to invest after expenses, loans and the emergency fund"),
        }
      : {
          label: "Short each month",
          value: w(-surplus),
          sub: `${hasAvg ? "first-year average" : "this month"}: spending and loan payments are more than your income`,
          title: nowTitle(s.monthly_investable_now, "left to invest"),
          tone: "var(--danger)",
        };

  let investSub: string;
  if (contributing < 0.5) investSub = "no new monthly investments needed in the first year";
  else if (fromSurplus !== undefined && fromSavings !== undefined && fromSavings >= 1)
    investSub = `${w(fromSurplus)} from your monthly surplus + ${w(fromSavings)} from savings you already have`;
  else if (fromSurplus !== undefined) investSub = "all from your monthly surplus";
  else investSub = "per month across goals and emergency fund";

  const cards: Kpi[] = [
    surplusCard,
    {
      label: "Plan invests",
      value: w(contributing),
      sub: hasAvg ? `a month on average in the first year: ${investSub}` : investSub,
      title: nowTitle(s.monthly_contribution_now, "invested across goals and emergency fund"),
    },
    {
      label: "Emergency fund",
      value: m(s.emergency_fund_target),
      sub: s.emergency_fund_complete_month ? `target, complete by ${fmtMonth(s.emergency_fund_complete_month)}` : "target, not reached in the plan",
    },
    { label: "Goals on track", value: `${s.goals_on_track} / ${s.goals_total}`, sub: s.goals_at_risk ? `${s.goals_at_risk} at risk, ${s.goals_off_track} off track` : `${s.goals_off_track} off track` },
    {
      label: "Cash shortfall risk",
      value: formatProb(s.liquidity_risk_probability),
      sub: "estimated chance of at least one month without enough cash",
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
