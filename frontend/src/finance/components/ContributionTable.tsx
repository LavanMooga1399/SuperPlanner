import { useMemo } from "react";
import type { FinanceResult } from "../api/types";
import { EF_ID } from "../api/types";
import { formatMoney } from "../lib/money";
import { addMonths, fmtMonthShort, monthsBetween } from "../lib/months";
import { classInfos, className, goalLabel, priceIndex } from "../lib/resultView";
import type { MoneyBasis } from "./RealNominalToggle";

/** Rows goal x class; columns = next 24 months, then the first month of each later plan year (FINANCE.md 20.4). */
export function ContributionTable({ result, basis, locale }: { result: FinanceResult; basis: MoneyBasis; locale: string }) {
  const infos = useMemo(() => classInfos(result), [result]);
  const T = result.horizon_months;
  const cols = useMemo(() => {
    const out: number[] = [];
    for (let t = 0; t < Math.min(24, T); t++) out.push(t);
    for (let t = 24; t < T; t += 12) out.push(t);
    return out;
  }, [T]);

  const rows = useMemo(() => {
    const goalOrder = new Map<string, number>([[EF_ID, -1], ...result.goals.map((g, i) => [g.goal_id, i] as [string, number])]);
    const classOrder = new Map(result.assumptions_used.asset_classes.map((c, i) => [c.id, i]));
    const keyed = new Map<string, { goal: string; cls: string; lines: typeof result.contributions }>();
    for (const l of result.contributions) {
      const k = `${l.goal_id}|${l.asset_class_id}`;
      if (!keyed.has(k)) keyed.set(k, { goal: l.goal_id, cls: l.asset_class_id, lines: [] });
      keyed.get(k)!.lines.push(l);
    }
    return [...keyed.values()].sort(
      (a, b) => (goalOrder.get(a.goal) ?? 99) - (goalOrder.get(b.goal) ?? 99) || (classOrder.get(a.cls) ?? 99) - (classOrder.get(b.cls) ?? 99),
    );
  }, [result]);

  const amountAt = (lines: typeof result.contributions, t: number) => {
    const m = addMonths(result.start_month, t);
    let v = 0;
    for (const l of lines) {
      if (monthsBetween(l.start_month, m) >= 0 && monthsBetween(m, l.end_month) >= 0) v += l.monthly_amount_real;
    }
    return basis === "nominal" ? v * priceIndex(result.assumptions_used.inflation_pct, t) : v;
  };

  const fmt = (v: number) => (v < 0.5 ? "-" : formatMoney(v, result.currency, locale));

  if (!rows.length) {
    return (
      <div className="empty" data-testid="contribution-table">
        <p>No contributions are planned.</p>
      </div>
    );
  }

  return (
    <div className="table-wrap" style={{ maxHeight: 460 }}>
      <table className="table contrib-table" data-testid="contribution-table">
        <caption className="sr-only">
          Monthly contributions per goal and asset class, {basis === "real" ? "in today's money" : "in expected future money"}
        </caption>
        <thead>
          <tr>
            <th className="sticky" scope="col">Goal · asset class</th>
            {cols.map((t) => (
              <th key={t} className="num" scope="col">
                {t >= 24 ? "from " : ""}
                {fmtMonthShort(addMonths(result.start_month, t))}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.goal}|${r.cls}`}>
              <th className="sticky" scope="row" style={{ fontWeight: 500 }}>
                <span style={{ fontWeight: 620 }}>{goalLabel(result, r.goal)}</span>
                <span className="small muted"> · {className(infos, r.cls)}</span>
              </th>
              {cols.map((t) => {
                const v = amountAt(r.lines, t);
                return (
                  <td key={t} className={`num${v < 0.5 ? " zero" : ""}`}>{fmt(v)}</td>
                );
              })}
            </tr>
          ))}
          <tr className="total">
            <th className="sticky" scope="row">Total per month</th>
            {cols.map((t) => (
              <td key={t} className="num">{fmt(rows.reduce((a, r) => a + amountAt(r.lines, t), 0))}</td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
