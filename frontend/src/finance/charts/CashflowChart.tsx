import { useMemo, useState } from "react";
import type { ResultCashflow } from "../api/types";
import { ChartPoint, ChartTooltip, type TooltipRow } from "./ChartTooltip";
import { Legend } from "./Legend";
import { linearScale, niceTicks, useWidth } from "./scales";

interface YearRow {
  label: string;
  income: number;
  inflow: number;
  essential: number;
  discretionary: number;
  debt: number;
  oneOffOut: number;
  ef: number;
  goals: number;
  surplus: number;
  oneOffNet: number;
}

const OUT_KEYS: { key: keyof YearRow; label: string; color: string }[] = [
  { key: "essential", label: "Essential expenses", color: "var(--fin-c8)" },
  { key: "discretionary", label: "Other expenses", color: "var(--fin-c3)" },
  { key: "debt", label: "Loan payments", color: "var(--fin-c5)" },
  { key: "oneOffOut", label: "One-off expenses", color: "var(--fin-c4)" },
  { key: "ef", label: "Emergency fund", color: "var(--fin-c2)" },
  { key: "goals", label: "Goal contributions", color: "var(--fin-c1)" },
];

const M = { l: 64, r: 14, t: 14, b: 26 };

/** Stacked bars per plan year: income vs outflows, surplus line, one-off markers (FINANCE.md 20.2). */
export function CashflowChart({
  cashflow,
  format,
  formatAxis,
  testId,
  height = 280,
  maxYears = 40,
}: {
  cashflow: ResultCashflow;
  format(v: number): string;
  formatAxis(v: number): string;
  testId?: string;
  height?: number;
  maxYears?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const years = useMemo<YearRow[]>(() => {
    const out: YearRow[] = [];
    const n = cashflow.months.length;
    for (let s = 0; s < n && out.length < maxYears; s += 12) {
      const r: YearRow = { label: cashflow.months[s].slice(0, 4), income: 0, inflow: 0, essential: 0, discretionary: 0, debt: 0, oneOffOut: 0, ef: 0, goals: 0, surplus: 0, oneOffNet: 0 };
      for (let t = s; t < Math.min(n, s + 12); t++) {
        r.income += cashflow.income[t] ?? 0;
        r.essential += cashflow.essential[t] ?? 0;
        r.discretionary += cashflow.discretionary[t] ?? 0;
        r.debt += cashflow.debt_payments[t] ?? 0;
        const oo = cashflow.one_off_net[t] ?? 0;
        if (oo > 0) r.inflow += oo;
        else r.oneOffOut += -oo;
        r.oneOffNet += oo;
        r.ef += cashflow.emergency_fund_contribution[t] ?? 0;
        r.goals += cashflow.goal_contribution[t] ?? 0;
        r.surplus += cashflow.surplus[t] ?? 0;
      }
      r.label = `${cashflow.months[s]}`;
      out.push(r);
    }
    return out;
  }, [cashflow, maxYears]);

  const innerW = width - M.l - M.r;
  const innerH = height - M.t - M.b;
  const maxIn = Math.max(1, ...years.map((r) => r.income + r.inflow));
  const maxOut = Math.max(1, ...years.map((r) => OUT_KEYS.reduce((a, k) => a + (r[k.key] as number), 0)));
  const minSurplus = Math.min(0, ...years.map((r) => r.surplus));
  const ticks = niceTicks(minSurplus, Math.max(maxIn, maxOut), 4);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const y = linearScale(yMin, yMax, M.t + innerH, M.t);
  const group = innerW / Math.max(1, years.length);
  const barW = Math.max(2, Math.min(18, group * 0.38));
  const cx = (i: number) => M.l + group * i + group / 2;
  const labelEvery = Math.max(1, Math.ceil(years.length / Math.max(3, Math.floor(innerW / 60))));

  const rowsFor = (r: YearRow): TooltipRow[] => [
    { label: "Income", value: format(r.income), color: "var(--fin-income)" },
    ...(r.inflow > 0 ? [{ label: "One-off inflows", value: format(r.inflow), color: "var(--fin-c6)" }] : []),
    ...OUT_KEYS.filter((k) => (r[k.key] as number) > 0.5).map((k) => ({ label: k.label, value: format(r[k.key] as number), color: k.color })),
    { label: "Surplus before saving", value: format(r.surplus) },
  ];

  return (
    <figure className="chart-box" data-testid={testId} style={{ margin: 0 }}>
      <div ref={ref} style={{ position: "relative" }}>
        <svg width={width} height={height} role="img" aria-label={`Yearly cash flow over ${years.length} years: income compared with expenses, loan payments and savings, in today's money.`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.l} x2={M.l + innerW} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--grid-strong)" : "var(--grid)"} />
              <text x={M.l - 6} y={y(t) + 4} textAnchor="end">{formatAxis(t)}</text>
            </g>
          ))}
          {years.map((r, i) => {
            let acc = 0;
            return (
              <g key={r.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <rect x={M.l + group * i} y={M.t} width={group} height={innerH} fill={hover === i ? "var(--shade)" : "transparent"} />
                <rect x={cx(i) - barW - 1} y={y(r.income)} width={barW} height={Math.max(0, y(0) - y(r.income))} fill="var(--fin-income)" rx={1.5} />
                {r.inflow > 0 ? (
                  <rect x={cx(i) - barW - 1} y={y(r.income + r.inflow)} width={barW} height={Math.max(0, y(r.income) - y(r.income + r.inflow))} fill="var(--fin-c6)" rx={1.5} />
                ) : null}
                {OUT_KEYS.map((k) => {
                  const v = r[k.key] as number;
                  if (v <= 0) return null;
                  const y0 = y(acc);
                  acc += v;
                  return <rect key={k.key} x={cx(i) + 1} y={y(acc)} width={barW} height={Math.max(0, y0 - y(acc))} fill={k.color} />;
                })}
                {Math.abs(r.oneOffNet) > 0.5 ? (
                  <path d={`M${cx(i)},${M.t - 2}l4,-6h-8z`} fill="var(--fin-c4)" transform={`translate(0, 8)`}>
                    <title>One-off in this year</title>
                  </path>
                ) : null}
                {i % labelEvery === 0 ? (
                  <text x={cx(i)} y={height - 8} textAnchor="middle">{r.label.slice(0, 4)}</text>
                ) : null}
              </g>
            );
          })}
          <path
            d={years.map((r, i) => `${i ? "L" : "M"}${cx(i).toFixed(1)},${y(r.surplus).toFixed(1)}`).join("")}
            fill="none"
            stroke="var(--fin-surplus)"
            strokeWidth={2}
          />
        </svg>
        <div className="chart-points">
          {years.map((r, i) => (
            <ChartPoint
              key={r.label}
              x={cx(i)}
              y={y(r.surplus)}
              label={`Year from ${r.label}: income ${format(r.income)}, surplus ${format(r.surplus)}, goal contributions ${format(r.goals)}`}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            />
          ))}
        </div>
        {hover !== null && years[hover] ? (
          <ChartTooltip x={cx(hover)} y={y(years[hover].surplus)} width={width} title={`Year from ${years[hover].label}`} rows={rowsFor(years[hover])} />
        ) : null}
      </div>
      <Legend
        items={[
          { label: "Income", color: "var(--fin-income)" },
          { label: "One-off inflows", color: "var(--fin-c6)" },
          ...OUT_KEYS.map((k) => ({ label: k.label, color: k.color })),
          { label: "Surplus before saving", color: "var(--fin-surplus)", kind: "line" as const },
          { label: "One-off marker", color: "var(--fin-c4)" },
        ]}
      />
      <table className="sr-only">
        <caption>Cash flow per plan year, today's money</caption>
        <thead>
          <tr>
            <th scope="col">Year from</th>
            <th scope="col">Income</th>
            <th scope="col">One-off net</th>
            {OUT_KEYS.map((k) => (
              <th scope="col" key={k.key}>{k.label}</th>
            ))}
            <th scope="col">Surplus</th>
          </tr>
        </thead>
        <tbody>
          {years.map((r) => (
            <tr key={r.label}>
              <th scope="row">{r.label}</th>
              <td>{format(r.income)}</td>
              <td>{format(r.oneOffNet)}</td>
              {OUT_KEYS.map((k) => (
                <td key={k.key}>{format(r[k.key] as number)}</td>
              ))}
              <td>{format(r.surplus)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
