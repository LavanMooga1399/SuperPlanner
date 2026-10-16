import { Icon } from "../../components/Icon";
import type { FinanceComparison } from "../api/types";
import { formatMoney, formatProb } from "../lib/money";
import { fmtMonth } from "../lib/months";
import { goalStatusLabel } from "./StatusPill";

function Delta({ v, fmt, higherIsBetter = true }: { v: number | null; fmt(v: number): string; higherIsBetter?: boolean }) {
  if (v === null || Math.abs(v) < 1e-9) return <span className="muted">no change</span>;
  const good = higherIsBetter ? v > 0 : v < 0;
  return (
    <span className={good ? "delta-up" : "delta-down"}>
      <Icon name="arrow-right" style={{ transform: v > 0 ? "rotate(-90deg)" : "rotate(90deg)" }} />
      <span className="sr-only">{good ? "better: " : "worse: "}</span>
      {fmt(v)}
    </span>
  );
}

/** FINANCE.md 13 comparison table (deltas are b - a). */
export function ScenarioCompareTable({
  cmp,
  currency,
  locale,
  labelA = "A",
  labelB = "B",
  testId = "fin-compare-table",
}: {
  cmp: FinanceComparison;
  currency: string;
  locale: string;
  labelA?: string;
  labelB?: string;
  testId?: string;
}) {
  const m = (v: number | null) => (v === null ? "-" : formatMoney(v, currency, locale));
  const ms = (v: number) => formatMoney(v, currency, locale, { signed: true });
  const t = cmp.totals;
  return (
    <div className="table-wrap">
      <table className="table" data-testid={testId}>
        <caption className="sr-only">Comparison of {labelA} and {labelB}</caption>
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col" className="num">{labelA}</th>
            <th scope="col" className="num">{labelB}</th>
            <th scope="col" className="num">Change</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Monthly contribution now</th>
            <td className="num">{m(t.monthly_contribution_now_a)}</td>
            <td className="num">{m(t.monthly_contribution_now_b)}</td>
            <td className="num"><Delta v={t.monthly_contribution_now_delta} fmt={ms} higherIsBetter={false} /></td>
          </tr>
          <tr>
            <th scope="row">Goals on track</th>
            <td className="num">{t.goals_on_track_a}</td>
            <td className="num">{t.goals_on_track_b}</td>
            <td className="num"><Delta v={t.goals_on_track_b - t.goals_on_track_a} fmt={(v) => `${v > 0 ? "+" : ""}${v}`} /></td>
          </tr>
          <tr>
            <th scope="row">Emergency fund complete</th>
            <td className="num">{fmtMonth(t.ef_complete_month_a)}</td>
            <td className="num">{fmtMonth(t.ef_complete_month_b)}</td>
            <td className="num">{t.ef_complete_month_a === t.ef_complete_month_b ? <span className="muted">no change</span> : "changed"}</td>
          </tr>
          <tr>
            <th scope="row">Cash shortfall risk</th>
            <td className="num">{formatProb(t.liquidity_risk_a)}</td>
            <td className="num">{formatProb(t.liquidity_risk_b)}</td>
            <td className="num"><Delta v={t.liquidity_risk_b - t.liquidity_risk_a} fmt={(v) => formatProb(v, true)} higherIsBetter={false} /></td>
          </tr>
          {cmp.goals.map((g) => (
            <GoalRows key={g.goal_id} g={g} m={m} ms={ms} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GoalRows({ g, m, ms }: { g: FinanceComparison["goals"][number]; m(v: number | null): string; ms(v: number): string }) {
  const absent = (side: boolean) => (side ? null : <span className="muted">not in this scenario</span>);
  return (
    <>
      <tr>
        <th scope="rowgroup" colSpan={4} style={{ background: "var(--surface-2)" }}>{g.name}</th>
      </tr>
      <tr>
        <th scope="row" style={{ paddingLeft: 20, fontWeight: 500 }}>Estimated chance</th>
        <td className="num">{absent(g.in_a) ?? formatProb(g.success_a)}</td>
        <td className="num">{absent(g.in_b) ?? formatProb(g.success_b)}</td>
        <td className="num"><Delta v={g.success_delta} fmt={(v) => formatProb(v, true)} /></td>
      </tr>
      <tr>
        <th scope="row" style={{ paddingLeft: 20, fontWeight: 500 }}>Middle outcome (p50)</th>
        <td className="num">{absent(g.in_a) ?? m(g.p50_a)}</td>
        <td className="num">{absent(g.in_b) ?? m(g.p50_b)}</td>
        <td className="num"><Delta v={g.p50_delta} fmt={ms} /></td>
      </tr>
      <tr>
        <th scope="row" style={{ paddingLeft: 20, fontWeight: 500 }}>Due</th>
        <td className="num">{fmtMonth(g.target_month_a)}</td>
        <td className="num">{fmtMonth(g.target_month_b)}</td>
        <td className="num">{g.target_month_a === g.target_month_b ? <span className="muted">no change</span> : "moved"}</td>
      </tr>
      <tr>
        <th scope="row" style={{ paddingLeft: 20, fontWeight: 500 }}>Monthly now</th>
        <td className="num">{m(g.monthly_now_a)}</td>
        <td className="num">{m(g.monthly_now_b)}</td>
        <td className="num">
          {g.monthly_now_a !== null && g.monthly_now_b !== null ? (
            <Delta v={g.monthly_now_b - g.monthly_now_a} fmt={ms} higherIsBetter={false} />
          ) : "-"}
        </td>
      </tr>
      <tr>
        <th scope="row" style={{ paddingLeft: 20, fontWeight: 500 }}>Status</th>
        <td className="num">{goalStatusLabel(g.status_a)}</td>
        <td className="num">{goalStatusLabel(g.status_b)}</td>
        <td className="num">{g.status_a === g.status_b ? <span className="muted">no change</span> : "changed"}</td>
      </tr>
    </>
  );
}
