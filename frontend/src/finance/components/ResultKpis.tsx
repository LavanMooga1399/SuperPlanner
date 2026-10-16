import type { FinanceResult } from "../api/types";
import { formatMoney, formatProb, roundDisplay } from "../lib/money";
import { fmtMonth } from "../lib/months";

export function ResultKpis({ result, locale }: { result: FinanceResult; locale: string }) {
  const s = result.summary;
  const m = (v: number) => formatMoney(roundDisplay(v), result.currency, locale);
  const cards = [
    { label: "You can invest now", value: m(s.monthly_investable_now), sub: "per month, after expenses and loans" },
    { label: "Plan invests now", value: m(s.monthly_contribution_now), sub: "per month across goals and emergency fund" },
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
        <div className="card kpi" key={c.label}>
          <div className="kpi-label">{c.label}</div>
          <div className="kpi-value" style={c.tone ? { color: c.tone } : undefined}>{c.value}</div>
          <div className="kpi-sub">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}
