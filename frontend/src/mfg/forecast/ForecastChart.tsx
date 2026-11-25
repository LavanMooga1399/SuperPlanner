/**
 * Forecast chart of one item (M8 12): history (solid grey), cleaned history where the cleaner clipped an outlier
 * (dashed grey, outliers as hollow diamonds), model fit over history (dotted), statistical forecast (dashed accent),
 * final forecast after overrides (solid accent) and customer orders that consumed forecast (bars). Series differ
 * by dash pattern and marker, not by colour alone; the legend repeats this. Keyboard: the chart is focusable and
 * Left/Right move a period cursor whose values are shown in the tooltip and announced; a screen-reader table holds
 * every value.
 */
import { useMemo, useState, type KeyboardEvent } from "react";
import { Legend } from "../../finance/charts/Legend";
import { niceTicks, useWidth } from "../../finance/charts/scales";
import { t } from "../../lib/i18n";
import type { Bucket } from "../api/typesM8";
import { num, periodLabel, periodShort } from "./shared";

const H = 260;
const M = { l: 56, r: 12, t: 12, b: 26 };

interface Row {
  p: string;
  hist: number | null;
  clean: number | null;
  outlier: boolean;
  fit: number | null;
  stat: number | null;
  final: number | null;
  consumed: number | null;
}

/** Chart input: one item's series by period start. */
export interface ForecastChartData {
  partNumber: string;
  bucket: Bucket;
  history: { period_start: string; qty: number; cleaned_qty: number | null; outlier: boolean }[];
  fitted: { period_start: string; qty: number }[];
  forecast: { period_start: string; stat_qty: number; final_qty: number }[];
  consumption: { period_start: string; consumed: number }[];
}

export function ForecastChart({ d }: { d: ForecastChartData }) {
  const [ref, width] = useWidth<HTMLDivElement>(900);
  const [cur, setCur] = useState<number | null>(null);
  const rows = useMemo<Row[]>(() => {
    const map = new Map<string, Row>();
    const get = (p: string) => {
      let r = map.get(p);
      if (!r) {
        r = { p, hist: null, clean: null, outlier: false, fit: null, stat: null, final: null, consumed: null };
        map.set(p, r);
      }
      return r;
    };
    for (const h of d.history) {
      const r = get(h.period_start);
      r.hist = h.qty;
      r.clean = h.cleaned_qty ?? h.qty;
      r.outlier = h.outlier || (h.cleaned_qty !== null && h.cleaned_qty !== h.qty);
    }
    for (const f of d.fitted) get(f.period_start).fit = f.qty;
    for (const f of d.forecast) {
      const r = get(f.period_start);
      r.stat = f.stat_qty;
      r.final = f.final_qty;
    }
    for (const c of d.consumption) get(c.period_start).consumed = c.consumed;
    return [...map.values()].sort((a, b) => a.p.localeCompare(b.p));
  }, [d]);

  const n = rows.length;
  const innerW = Math.max(100, width - M.l - M.r);
  const innerH = H - M.t - M.b;
  const step = innerW / Math.max(1, n);
  const x = (i: number) => M.l + step * (i + 0.5);
  let hi = 1;
  for (const r of rows) hi = Math.max(hi, r.hist ?? 0, r.clean ?? 0, r.fit ?? 0, r.stat ?? 0, r.final ?? 0, r.consumed ?? 0);
  const ticks = niceTicks(0, hi, 4);
  const top = ticks[ticks.length - 1] || 1;
  const y = (v: number) => M.t + innerH - (v / top) * innerH;
  const firstFc = rows.findIndex((r) => r.final !== null);
  const path = (key: keyof Row, from = 0, to = n) => {
    let s = "";
    let pen = false;
    for (let i = from; i < to; i++) {
      const v = rows[i][key] as number | null;
      if (v === null) {
        pen = false;
        continue;
      }
      s += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    }
    return s;
  };
  const anyClean = rows.some((r) => r.outlier);
  const labelEvery = Math.max(1, Math.ceil(n / Math.max(3, Math.floor(innerW / 64))));
  const barW = Math.max(2, Math.min(18, step * 0.5));
  const tot = rows.reduce((a, r) => a + (r.final ?? 0), 0);
  const summary = t("plan.fc.chart.aria", { item: d.partNumber, n: rows.filter((r) => r.hist !== null).length, m: rows.filter((r) => r.final !== null).length, total: num(tot) });

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!n) return;
    if (e.key === "ArrowRight") setCur((c) => Math.min(n - 1, (c ?? -1) + 1));
    else if (e.key === "ArrowLeft") setCur((c) => Math.max(0, (c ?? n) - 1));
    else if (e.key === "Home") setCur(0);
    else if (e.key === "End") setCur(n - 1);
    else if (e.key === "Escape") setCur(null);
    else return;
    e.preventDefault();
  };
  const c = cur !== null ? rows[cur] : null;
  const tipRows: [string, number | null][] = c
    ? [
        [t("plan.fc.series.history"), c.hist],
        ...(c.outlier ? ([[t("plan.fc.series.cleaned"), c.clean]] as [string, number | null][]) : []),
        [t("plan.fc.series.fitted"), c.fit],
        [t("plan.fc.series.stat"), c.stat],
        [t("plan.fc.series.final"), c.final],
        [t("plan.fc.series.consumed"), c.consumed],
      ].filter((r): r is [string, number | null] => r[1] !== null)
    : [];

  return (
    <figure className="pl-chart" data-testid="fc-chart" data-points={n}>
      <div
        ref={ref}
        className="pl-chart-area"
        tabIndex={0}
        role="group"
        aria-label={`${summary} ${t("plan.chart.keys")}`}
        onKeyDown={onKey}
        onBlur={() => setCur(null)}
        onMouseLeave={() => setCur(null)}
      >
        <svg width={width} height={H} role="img" aria-label={summary}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={M.l} x2={M.l + innerW} y1={y(v)} y2={y(v)} stroke="var(--grid)" />
              <text x={M.l - 6} y={y(v) + 3} textAnchor="end" className="pl-axis">
                {num(v, top < 10 ? 1 : 0)}
              </text>
            </g>
          ))}
          {firstFc > 0 ? (
            <g>
              <rect x={x(firstFc) - step / 2} y={M.t} width={M.l + innerW - (x(firstFc) - step / 2)} height={innerH} fill="var(--shade)" />
              <text x={x(firstFc) - step / 2 + 4} y={M.t + 11} className="pl-axis">
                {t("plan.fc.chart.forecastZone")}
              </text>
            </g>
          ) : null}
          {rows.map((r, i) =>
            r.consumed ? <rect key={`c${r.p}`} x={x(i) - barW / 2} y={y(r.consumed)} width={barW} height={Math.max(0, y(0) - y(r.consumed))} fill="var(--ok-soft)" stroke="var(--ok)" strokeWidth={1} /> : null,
          )}
          <line x1={M.l} x2={M.l + innerW} y1={y(0)} y2={y(0)} stroke="var(--grid-strong)" />
          <path d={path("hist")} fill="none" stroke="var(--text-muted)" strokeWidth={1.75} />
          {anyClean ? <path d={path("clean")} fill="none" stroke="var(--text-muted)" strokeWidth={1.5} strokeDasharray="5 3" /> : null}
          <path d={path("fit")} fill="none" stroke="var(--info)" strokeWidth={1.5} strokeDasharray="1.5 3" strokeLinecap="round" />
          <path d={path("stat")} fill="none" stroke="var(--accent)" strokeWidth={1.75} strokeDasharray="6 4" />
          <path d={path("final")} fill="none" stroke="var(--accent)" strokeWidth={2.5} />
          {rows.map((r, i) =>
            r.outlier && r.hist !== null ? (
              <path key={`o${r.p}`} d={`M${x(i)},${y(r.hist) - 5}l5,5l-5,5l-5,-5z`} fill="var(--surface)" stroke="var(--danger)" strokeWidth={1.5} data-testid="fc-outlier" />
            ) : null,
          )}
          {rows.map((r, i) =>
            i % labelEvery === 0 ? (
              <text key={`l${r.p}`} x={x(i)} y={H - 8} textAnchor="middle" className="pl-axis">
                {periodShort(r.p, d.bucket)}
              </text>
            ) : null,
          )}
          {cur !== null ? <line x1={x(cur)} x2={x(cur)} y1={M.t} y2={M.t + innerH} stroke="var(--text-faint)" strokeDasharray="2 2" /> : null}
          {rows.map((r, i) => (
            <rect key={`h${r.p}`} x={x(i) - step / 2} y={M.t} width={step} height={innerH} fill="transparent" onMouseEnter={() => setCur(i)} />
          ))}
        </svg>
        {c && cur !== null ? (
          <div className="pl-tip" role="status" style={{ left: Math.min(x(cur) + 12, width - 220), top: M.t }}>
            <div className="pl-tip-title">{periodLabel(c.p, d.bucket)}</div>
            {tipRows.map(([k, v]) => (
              <div key={k} className="pl-tip-row">
                <span>{k}</span>
                <span className="pl-num">{num(v)}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      <figcaption>
        <Legend
          label={t("plan.chart.legend")}
          items={[
            { label: t("plan.fc.series.history"), color: "var(--text-muted)", kind: "line" },
            ...(anyClean ? [{ label: t("plan.fc.series.cleaned"), color: "var(--text-muted)", kind: "dashed" as const }] : []),
            { label: t("plan.fc.series.fitted"), color: "var(--info)", kind: "dashed" },
            { label: t("plan.fc.series.stat"), color: "var(--accent)", kind: "dashed" },
            { label: t("plan.fc.series.final"), color: "var(--accent)", kind: "line" },
            { label: t("plan.fc.series.consumed"), color: "var(--ok-soft)", kind: "box" },
          ]}
        />
      </figcaption>
      <table className="sr-only">
        <caption>{summary}</caption>
        <thead>
          <tr>
            <th scope="col">{t("plan.fc.head.period")}</th>
            <th scope="col">{t("plan.fc.series.history")}</th>
            <th scope="col">{t("plan.fc.series.cleaned")}</th>
            <th scope="col">{t("plan.fc.series.fitted")}</th>
            <th scope="col">{t("plan.fc.series.stat")}</th>
            <th scope="col">{t("plan.fc.series.final")}</th>
            <th scope="col">{t("plan.fc.series.consumed")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.p}>
              <th scope="row">{periodLabel(r.p, d.bucket)}</th>
              <td>{num(r.hist)}</td>
              <td>{num(r.clean)}</td>
              <td>{num(r.fit)}</td>
              <td>{num(r.stat)}</td>
              <td>{num(r.final)}</td>
              <td>{num(r.consumed)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
