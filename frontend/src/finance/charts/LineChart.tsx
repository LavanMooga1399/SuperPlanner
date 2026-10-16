import { useState } from "react";
import { fmtMonth } from "../lib/months";
import { ChartPoint, ChartTooltip } from "./ChartTooltip";
import { Legend } from "./Legend";
import { linearScale, niceTicks, useWidth } from "./scales";

export interface LineSeries {
  key: string;
  label: string;
  color: string;
  values: number[];
  dashed?: boolean;
}

export interface LineChartProps {
  /** One x label (Month) per point. */
  months: string[];
  series: LineSeries[];
  yMax?: number;
  formatY(v: number): string;
  ariaLabel: string;
  caption: string;
  testId?: string;
  height?: number;
  /** Draw as steps (values hold until the next point, e.g. block starts). */
  step?: boolean;
}

const M = { l: 48, r: 14, t: 10, b: 26 };

/** Line chart over months; used for the glide path (cap dashed vs planned growth share). */
export function LineChart({ months, series, yMax = 100, formatY, ariaLabel, caption, testId, height = 240, step = true }: LineChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const n = months.length;
  const innerW = width - M.l - M.r;
  const innerH = height - M.t - M.b;
  const x = linearScale(0, Math.max(1, n - 1), M.l, M.l + innerW);
  const y = linearScale(0, yMax, M.t + innerH, M.t);
  const path = (vals: number[]) => {
    let d = "";
    vals.forEach((v, i) => {
      if (i === 0) d += `M${x(0).toFixed(1)},${y(v).toFixed(1)}`;
      else if (step) d += `H${x(i).toFixed(1)}V${y(v).toFixed(1)}`;
      else d += `L${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    });
    return d;
  };
  const yTicks = niceTicks(0, yMax, 4);
  const labelEvery = Math.max(1, Math.ceil(n / Math.max(3, Math.floor(innerW / 80))));
  const first = series[series.length - 1];

  return (
    <figure className="chart-box" data-testid={testId} style={{ margin: 0 }}>
      <div ref={ref} style={{ position: "relative" }}>
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={M.l} x2={M.l + innerW} y1={y(t)} y2={y(t)} stroke="var(--grid)" />
              <text x={M.l - 6} y={y(t) + 4} textAnchor="end">{formatY(t)}</text>
            </g>
          ))}
          {months.map((m, i) =>
            i % labelEvery === 0 ? (
              <text key={m + i} x={x(i)} y={height - 8} textAnchor="middle">{m.slice(0, 4)}</text>
            ) : null,
          )}
          {series.map((s) => (
            <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={s.dashed ? 2 : 2.5} strokeDasharray={s.dashed ? "6 4" : undefined} />
          ))}
          {hover !== null ? <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={M.t + innerH} stroke="var(--grid-strong)" /> : null}
        </svg>
        <div className="chart-points">
          {first
            ? months.map((m, i) => (
                <ChartPoint
                  key={m + i}
                  x={x(i)}
                  y={y(first.values[i] ?? 0)}
                  label={`${fmtMonth(m)}: ${series.map((s) => `${s.label} ${formatY(s.values[i] ?? 0)}`).join(", ")}`}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                />
              ))
            : null}
        </div>
        {hover !== null && first ? (
          <ChartTooltip
            x={x(hover)}
            y={y(first.values[hover] ?? 0)}
            width={width}
            title={fmtMonth(months[hover])}
            rows={series.map((s) => ({ label: s.label, value: formatY(s.values[hover] ?? 0), color: s.color }))}
          />
        ) : null}
      </div>
      <Legend items={series.map((s) => ({ label: s.label, color: s.color, kind: s.dashed ? "dashed" : "line" }))} />
      <table className="sr-only">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Month</th>
            {series.map((s) => (
              <th scope="col" key={s.key}>{s.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {months.map((m, i) => (
            <tr key={m + i}>
              <th scope="row">{fmtMonth(m)}</th>
              {series.map((s) => (
                <td key={s.key}>{formatY(s.values[i] ?? 0)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
