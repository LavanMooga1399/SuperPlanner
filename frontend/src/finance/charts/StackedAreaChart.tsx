import { useMemo, useState, type MouseEvent } from "react";
import { fmtMonth } from "../lib/months";
import { ChartPoint, ChartTooltip, type TooltipRow } from "./ChartTooltip";
import { Legend } from "./Legend";
import { linearScale, monthTickIndices, niceMax, niceTicks, useWidth } from "./scales";

export interface AreaLayer {
  key: string;
  label: string;
  color: string;
  values: number[];
}

export interface Band {
  p10: number[];
  p50: number[];
  p90: number[];
}

export interface StackedAreaChartProps {
  months: string[];
  layers: AreaLayer[];
  band?: Band | null;
  format(v: number): string;
  formatAxis(v: number): string;
  ariaLabel: string;
  testId?: string;
  height?: number;
  caption: string;
}

const M = { l: 64, r: 14, t: 10, b: 26 };

/** Corpus by class stacked + p10-p90 band + p50 line (FINANCE.md 20.2, [R20]). */
export function StackedAreaChart({ months, layers, band, format, formatAxis, ariaLabel, testId, height = 280, caption }: StackedAreaChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const n = months.length;

  const cum = useMemo(() => {
    const out: number[][] = [];
    let prev = new Array(n).fill(0) as number[];
    for (const l of layers) {
      const next = prev.map((p, i) => p + Math.max(0, l.values[i] ?? 0));
      out.push(next);
      prev = next;
    }
    return out;
  }, [layers, n]);

  const totals = cum.length ? cum[cum.length - 1] : (new Array(n).fill(0) as number[]);
  const maxV = Math.max(1, ...totals, ...(band ? band.p90 : [0]));
  const yMax = niceMax(maxV);
  const innerW = width - M.l - M.r;
  const innerH = height - M.t - M.b;
  const x = linearScale(0, Math.max(1, n - 1), M.l, M.l + innerW);
  const y = linearScale(0, yMax, M.t + innerH, M.t);

  const line = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = (top: number[], bottom: number[] | null) => {
    if (!n) return "";
    let d = line(top);
    for (let i = n - 1; i >= 0; i--) d += `L${x(i).toFixed(1)},${y(bottom ? bottom[i] : 0).toFixed(1)}`;
    return d + "Z";
  };

  const xTicks = monthTickIndices(months, Math.max(3, Math.floor(innerW / 90)));
  const yTicks = niceTicks(0, yMax, 4);
  const pointIdx = useMemo(() => {
    const out: number[] = [];
    for (let i = 0; i < n; i += 12) out.push(i);
    if (n && out[out.length - 1] !== n - 1) out.push(n - 1);
    return out;
  }, [n]);

  const rowsAt = (i: number): TooltipRow[] => {
    const rows: TooltipRow[] = layers
      .filter((l) => (l.values[i] ?? 0) > 0.5)
      .map((l) => ({ label: l.label, value: format(l.values[i] ?? 0), color: l.color }));
    rows.push({ label: "Total (expected returns)", value: format(totals[i] ?? 0) });
    if (band) rows.push({ label: "Likely range p10 - p90", value: `${format(band.p10[i] ?? 0)} - ${format(band.p90[i] ?? 0)}` });
    return rows;
  };
  const pointY = (i: number) => y(band ? band.p50[i] ?? 0 : totals[i] ?? 0);

  const onMove = (e: MouseEvent<SVGRectElement>) => {
    const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    const i = Math.round(((px - M.l) / Math.max(1, innerW)) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  const legend = [
    ...layers.map((l) => ({ label: l.label, color: l.color })),
    ...(band
      ? [
          { label: "Likely range (p10 - p90)", color: "var(--fin-band)", kind: "band" as const },
          { label: "Middle outcome (p50)", color: "var(--text)", kind: "dashed" as const },
        ]
      : []),
  ];

  return (
    <figure className="chart-box" data-testid={testId} style={{ margin: 0 }}>
      <div ref={ref} style={{ position: "relative" }}>
        <svg width={width} height={height} role="img" aria-label={ariaLabel}>
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={M.l} x2={M.l + innerW} y1={y(t)} y2={y(t)} stroke="var(--grid)" />
              <text x={M.l - 6} y={y(t) + 4} textAnchor="end">{formatAxis(t)}</text>
            </g>
          ))}
          {xTicks.map((i) => (
            <text key={i} x={x(i)} y={height - 8} textAnchor="middle">{months[i].slice(0, 4)}</text>
          ))}
          {layers.map((l, k) => (
            <path key={l.key} d={area(cum[k], k ? cum[k - 1] : null)} fill={l.color} fillOpacity={0.78} stroke={l.color} strokeWidth={0.5} />
          ))}
          {band ? (
            <>
              <path d={area(band.p90, band.p10)} fill="var(--fin-band)" stroke="var(--fin-band-line)" strokeWidth={1} />
              <path d={line(band.p50)} fill="none" stroke="var(--text)" strokeWidth={1.5} strokeDasharray="5 4" />
            </>
          ) : null}
          {hover !== null ? <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={M.t + innerH} stroke="var(--grid-strong)" /> : null}
          <rect x={M.l} y={M.t} width={innerW} height={innerH} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
        </svg>
        <div className="chart-points">
          {pointIdx.map((i) => (
            <ChartPoint
              key={i}
              x={x(i)}
              y={pointY(i)}
              label={`${fmtMonth(months[i])}: total ${format(totals[i] ?? 0)}${band ? `, likely range ${format(band.p10[i] ?? 0)} to ${format(band.p90[i] ?? 0)}` : ""}`}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            />
          ))}
        </div>
        {hover !== null && n ? <ChartTooltip x={x(hover)} y={pointY(hover)} width={width} title={fmtMonth(months[hover])} rows={rowsAt(hover)} /> : null}
      </div>
      <Legend items={legend} />
      <table className="sr-only">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Month</th>
            {layers.map((l) => (
              <th scope="col" key={l.key}>{l.label}</th>
            ))}
            <th scope="col">Total</th>
            {band ? (
              <>
                <th scope="col">p10</th>
                <th scope="col">p50</th>
                <th scope="col">p90</th>
              </>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {pointIdx.map((i) => (
            <tr key={i}>
              <th scope="row">{fmtMonth(months[i])}</th>
              {layers.map((l) => (
                <td key={l.key}>{format(l.values[i] ?? 0)}</td>
              ))}
              <td>{format(totals[i] ?? 0)}</td>
              {band ? (
                <>
                  <td>{format(band.p10[i] ?? 0)}</td>
                  <td>{format(band.p50[i] ?? 0)}</td>
                  <td>{format(band.p90[i] ?? 0)}</td>
                </>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
