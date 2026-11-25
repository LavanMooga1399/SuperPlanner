/**
 * Forecast accuracy `/mfg/forecast/accuracy` (M8 4.5, 12): lag-1 / lag-3 tracking (the version that was active 1 or
 * 3 periods before each closed period, against what actually shipped), WAPE and bias by family, ABC class or item,
 * a WAPE trend per period, and the backtest of the latest forecast run (holdout WAPE per ABC class, method mix).
 */
import { useEffect, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { FilterBar } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { Legend } from "../../finance/charts/Legend";
import { niceTicks, useWidth } from "../../finance/charts/scales";
import { t } from "../../lib/i18n";
import { formatNumber } from "../../lib/locale";
import { getAccuracy } from "../api/clientM8";
import type { AccuracyGroup, AccuracyReport, AccuracyRow, ForecastMethod } from "../api/typesM8";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { setSearchParam } from "../lib/usePaged";
import { useLoad } from "../lib/useMfg";
import { BiasBadge, Facts, ItemLink, methodText, num, pct, periodLabel, periodShort, Segmented, signedPct, WapeBadge } from "./shared";

export function AccuracyPage() {
  const [params, setParams] = useSearchParams();
  const lag = params.get("lag") === "3" ? 3 : 1;
  const group = (["family", "abc", "item"].includes(params.get("group") ?? "") ? params.get("group") : "family") as AccuracyGroup;
  useEffect(() => {
    document.title = t("plan.acc.title");
  }, []);
  const rep = useLoad((s) => getAccuracy({ lag, group_by: group }, s), [lag, group]);
  const d = rep.data;
  const columns = useMemo<Column<AccuracyRow>[]>(
    () => [
      {
        key: "key",
        header: group === "item" ? t("plan.fc.head.item") : group === "abc" ? t("plan.fc.label.abc") : t("plan.fc.label.family"),
        width: "minmax(200px, 2fr)",
        sortValue: (r) => r.label,
        exportValue: (r) => r.label,
        render: (r) => (r.item ? <ItemLink item={r.item} /> : <span className="mfg-ellipsis">{r.label}</span>),
      },
      { key: "wape", header: t("plan.fc.head.wape"), width: "110px", align: "right", sortValue: (r) => r.wape ?? -1, exportValue: (r) => r.wape, render: (r) => <WapeBadge v={r.wape} /> },
      { key: "bias", header: t("plan.fc.head.bias"), width: "110px", align: "right", sortValue: (r) => r.bias ?? 0, exportValue: (r) => r.bias, render: (r) => <BiasBadge v={r.bias} /> },
      { key: "volume", header: t("plan.acc.head.volume"), width: "130px", align: "right", sortValue: (r) => r.volume, exportValue: (r) => r.volume, render: (r) => <span className="pl-num">{num(r.volume)}</span> },
      { key: "items", header: t("plan.acc.head.items"), width: "90px", align: "right", sortValue: (r) => r.items, render: (r) => <span className="pl-num">{num(r.items)}</span> },
    ],
    [group],
  );
  return (
    <div className="col gap-lg" data-testid="fc-accuracy-page">
      <PageHeader
        title={t("plan.acc.title")}
        description={t("plan.acc.desc")}
        facts={d ? [[t("plan.acc.fact.overall", { lag }), pct(d.overall.wape, 1)], [t("plan.fc.head.bias"), signedPct(d.overall.bias)], [t("plan.acc.fact.periods"), formatNumber(d.periods.length)]] : []}
        actions={
          <Link className="btn" to={mfgPaths.forecast()}>
            <Icon name="chart" /> {t("plan.acc.btn.workbench")}
          </Link>
        }
      />
      <FilterBar>
        <div className="field">
          <span className="field-label" id="acc-lag-l">{t("plan.acc.label.lag")}</span>
          <Segmented<"1" | "3">
            label={t("plan.acc.label.lag")}
            value={lag === 3 ? "3" : "1"}
            testId="acc-lag"
            options={[
              { value: "1", label: t("plan.acc.lag1") },
              { value: "3", label: t("plan.acc.lag3") },
            ]}
            onChange={(v) => setSearchParam(setParams, "lag", v === "1" ? "" : v)}
          />
        </div>
        <div className="field">
          <span className="field-label">{t("plan.acc.label.group")}</span>
          <Segmented<AccuracyGroup>
            label={t("plan.acc.label.group")}
            value={group}
            testId="acc-group"
            options={[
              { value: "family", label: t("plan.fc.label.family") },
              { value: "abc", label: t("plan.fc.label.abc") },
              { value: "item", label: t("plan.fc.head.item") },
            ]}
            onChange={(v) => setSearchParam(setParams, "group", v === "family" ? "" : v)}
          />
        </div>
      </FilterBar>
      <MfgError error={rep.error} onRetry={rep.reload} />
      {rep.loading && !d ? <Spinner /> : null}
      {d ? (
        <>
          <div className="pl-two">
            <section className="card">
              <div className="card-header pl-card-header">
                <h2 className="pl-h2">{t("plan.acc.trend.title", { lag })}</h2>
              </div>
              <div className="card-body">
                {d.trend.length ? <TrendChart rep={d} /> : <p className="muted" style={{ margin: 0 }}>{t("plan.acc.trend.empty")}</p>}
              </div>
            </section>
            <Backtest rep={d} />
          </div>
          <section className="card card-table" aria-label={t("plan.acc.table")}>
            <DataTable<AccuracyRow>
              rows={d.rows}
              columns={columns}
              rowKey={(r) => r.key}
              label={t("plan.acc.table")}
              testId="acc-table"
              exportName={`forecast-accuracy-lag${lag}`}
              empty={t("plan.acc.empty")}
            />
          </section>
        </>
      ) : null}
    </div>
  );
}

function Backtest({ rep }: { rep: AccuracyReport }) {
  const b = rep.backtest;
  return (
    <section className="card" data-testid="acc-backtest">
      <div className="card-header pl-card-header">
        <h2 className="pl-h2">{b ? t("plan.acc.bt.title", { n: b.run_number }) : t("plan.acc.bt.titleNone")}</h2>
      </div>
      <div className="card-body col pl-gap">
        {b ? (
          <>
            <p className="muted small" style={{ margin: 0 }}>{t("plan.acc.bt.hint")}</p>
            <Facts
              rows={[
                [t("plan.acc.bt.overall"), <WapeBadge key="o" v={b.summary.wape} />],
                ...(["A", "B", "C"] as const).map((c) => {
                  const x = b.summary.by_abc[c];
                  return [t("plan.acc.bt.class", { c }), x ? <span key={c}><WapeBadge v={x.wape} /> <span className="muted small">{t("plan.tpl.itemsN", { n: num(x.items) })}</span></span> : "–"] as [string, ReactNode];
                }),
              ]}
            />
            <div>
              <div className="small muted">{t("plan.acc.bt.mix")}</div>
              <ul className="pl-mix">
                {Object.entries(b.summary.method_mix)
                  .sort((a, c) => (c[1] ?? 0) - (a[1] ?? 0))
                  .map(([m, n]) => (
                    <li key={m}>
                      <span>{methodText(m as ForecastMethod)}</span>
                      <span className="pl-num">{num(n ?? 0)}</span>
                    </li>
                  ))}
              </ul>
            </div>
          </>
        ) : (
          <p className="muted" style={{ margin: 0 }}>{t("plan.acc.bt.none")}</p>
        )}
      </div>
    </section>
  );
}

const TH = 200;
const TM = { l: 44, r: 10, t: 10, b: 24 };

/** WAPE (solid) and absolute bias (dashed) per closed period, in percent. */
function TrendChart({ rep }: { rep: AccuracyReport }) {
  const [ref, width] = useWidth<HTMLDivElement>(560);
  const [cur, setCur] = useState<number | null>(null);
  const pts = rep.trend;
  const n = pts.length;
  const innerW = width - TM.l - TM.r;
  const innerH = TH - TM.t - TM.b;
  const x = (i: number) => TM.l + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  let hi = 0.1;
  for (const p of pts) hi = Math.max(hi, p.wape ?? 0, Math.abs(p.bias ?? 0));
  const ticks = niceTicks(0, hi * 100, 4);
  const top = (ticks[ticks.length - 1] || 10) / 100;
  const y = (v: number) => TM.t + innerH - (v / top) * innerH;
  const line = (f: (p: (typeof pts)[number]) => number | null) => {
    let s = "";
    let pen = false;
    pts.forEach((p, i) => {
      const v = f(p);
      if (v === null) {
        pen = false;
        return;
      }
      s += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return s;
  };
  const every = Math.max(1, Math.ceil(n / Math.max(3, Math.floor(innerW / 60))));
  const last = pts[n - 1];
  const aria = t("plan.acc.trend.aria", { n, from: periodLabel(pts[0].period_start, rep.bucket), to: periodLabel(last.period_start, rep.bucket), last: pct(last.wape, 0) });
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowRight") setCur((c) => Math.min(n - 1, (c ?? -1) + 1));
    else if (e.key === "ArrowLeft") setCur((c) => Math.max(0, (c ?? n) - 1));
    else if (e.key === "Escape") setCur(null);
    else return;
    e.preventDefault();
  };
  const c = cur !== null ? pts[cur] : null;
  return (
    <figure className="pl-chart" data-testid="acc-trend">
      <div ref={ref} className="pl-chart-area" tabIndex={0} role="group" aria-label={`${aria} ${t("plan.chart.keys")}`} onKeyDown={onKey} onBlur={() => setCur(null)} onMouseLeave={() => setCur(null)}>
        <svg width={width} height={TH} role="img" aria-label={aria}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={TM.l} x2={TM.l + innerW} y1={y(v / 100)} y2={y(v / 100)} stroke="var(--grid)" />
              <text x={TM.l - 6} y={y(v / 100) + 3} textAnchor="end" className="pl-axis">
                {`${formatNumber(v)} %`}
              </text>
            </g>
          ))}
          <line x1={TM.l} x2={TM.l + innerW} y1={y(0.25)} y2={y(0.25)} stroke="var(--ok)" strokeDasharray="2 4" />
          <path d={line((p) => (p.bias === null ? null : Math.abs(p.bias)))} fill="none" stroke="var(--warn)" strokeWidth={1.5} strokeDasharray="5 3" />
          <path d={line((p) => p.wape)} fill="none" stroke="var(--accent)" strokeWidth={2.25} />
          {pts.map((p, i) => (p.wape !== null ? <circle key={p.period_start} cx={x(i)} cy={y(p.wape)} r={cur === i ? 4.5 : 2.5} fill="var(--accent)" /> : null))}
          {pts.map((p, i) =>
            i % every === 0 ? (
              <text key={`l${p.period_start}`} x={x(i)} y={TH - 6} textAnchor="middle" className="pl-axis">
                {periodShort(p.period_start, rep.bucket)}
              </text>
            ) : null,
          )}
          {pts.map((p, i) => (
            <rect key={`h${p.period_start}`} x={x(i) - innerW / Math.max(1, n) / 2} y={TM.t} width={innerW / Math.max(1, n)} height={innerH} fill="transparent" onMouseEnter={() => setCur(i)} />
          ))}
        </svg>
        {c && cur !== null ? (
          <div className="pl-tip" role="status" style={{ left: Math.min(x(cur) + 12, width - 200), top: TM.t }}>
            <div className="pl-tip-title">{periodLabel(c.period_start, rep.bucket)}</div>
            <div className="pl-tip-row">
              <span>{t("plan.fc.head.wape")}</span>
              <span className="pl-num">{pct(c.wape)}</span>
            </div>
            <div className="pl-tip-row">
              <span>{t("plan.fc.head.bias")}</span>
              <span className="pl-num">{signedPct(c.bias)}</span>
            </div>
          </div>
        ) : null}
      </div>
      <figcaption>
        <Legend
          label={t("plan.chart.legend")}
          items={[
            { label: t("plan.fc.head.wape"), color: "var(--accent)", kind: "line" },
            { label: t("plan.acc.trend.absBias"), color: "var(--warn)", kind: "dashed" },
            { label: t("plan.acc.trend.target"), color: "var(--ok)", kind: "dashed" },
          ]}
        />
      </figcaption>
      <table className="sr-only">
        <caption>{aria}</caption>
        <thead>
          <tr>
            <th scope="col">{t("plan.fc.head.period")}</th>
            <th scope="col">{t("plan.fc.head.wape")}</th>
            <th scope="col">{t("plan.fc.head.bias")}</th>
          </tr>
        </thead>
        <tbody>
          {pts.map((p) => (
            <tr key={p.period_start}>
              <th scope="row">{periodLabel(p.period_start, rep.bucket)}</th>
              <td>{pct(p.wape)}</td>
              <td>{signedPct(p.bias)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
