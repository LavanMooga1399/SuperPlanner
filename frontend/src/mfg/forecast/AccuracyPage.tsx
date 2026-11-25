/**
 * Forecast accuracy `/mfg/forecast/accuracy` (M8 4.5, 12): lag-1 / lag-3 tracking (the version that was active 1 or
 * 3 periods before each closed period, against what actually shipped) over the last N closed periods, WAPE and bias
 * by ABC class, family or item (bar chart and table), the overall figure, and the backtest of the latest forecast
 * run (holdout WAPE per ABC class, method mix).
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
import type { AccuracyGroup, AccuracyRow, ForecastMethod, ForecastSummary } from "../api/typesM8";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { setSearchParam } from "../lib/usePaged";
import { useLoad } from "../lib/useMfg";
import { BiasBadge, Facts, methodText, num, pct, Segmented, signedPct, WapeBadge } from "./shared";

type Group = Exclude<AccuracyGroup, "all">;
const PERIODS = ["3", "6", "12"] as const;

export function AccuracyPage() {
  const [params, setParams] = useSearchParams();
  const lag = params.get("lag") === "3" ? 3 : 1;
  const group = (["family", "abc", "item"].includes(params.get("group") ?? "") ? params.get("group") : "abc") as Group;
  const periods = Number((PERIODS as readonly string[]).includes(params.get("periods") ?? "") ? params.get("periods") : 6);
  useEffect(() => {
    document.title = t("plan.acc.title");
  }, []);
  const rep = useLoad((s) => getAccuracy({ lag, group_by: group, periods }, s), [lag, group, periods]);
  const all = useLoad((s) => getAccuracy({ lag, group_by: "all", periods }, s), [lag, periods]);
  const d = rep.data;
  const overall = all.data?.rows[0] ?? null;
  const groupLabel = group === "item" ? t("plan.fc.head.item") : group === "abc" ? t("plan.fc.label.abc") : t("plan.fc.label.family");
  const columns = useMemo<Column<AccuracyRow>[]>(
    () => [
      { key: "key", header: groupLabel, width: "minmax(180px, 2fr)", sortValue: (r) => r.label, exportValue: (r) => r.label, render: (r) => <span className={`mfg-ellipsis${group === "item" ? " mono" : ""}`}>{r.label}</span> },
      { key: "wape", header: t("plan.fc.head.wape"), width: "110px", align: "right", sortValue: (r) => r.wape ?? -1, exportValue: (r) => r.wape, render: (r) => <WapeBadge v={r.wape} /> },
      { key: "bias", header: t("plan.fc.head.bias"), width: "110px", align: "right", sortValue: (r) => r.bias ?? 0, exportValue: (r) => r.bias, render: (r) => <BiasBadge v={r.bias} /> },
      { key: "actual", header: t("plan.acc.head.actual"), width: "130px", align: "right", sortValue: (r) => r.actual, exportValue: (r) => r.actual, render: (r) => <span className="pl-num">{num(r.actual)}</span> },
      { key: "forecast", header: t("plan.acc.head.forecast"), width: "130px", align: "right", sortValue: (r) => r.forecast, exportValue: (r) => r.forecast, render: (r) => <span className="pl-num">{num(r.forecast)}</span> },
      { key: "periods", header: t("plan.acc.head.periods"), width: "90px", align: "right", drop: 1, sortValue: (r) => r.periods, render: (r) => <span className="pl-num">{num(r.periods)}</span> },
    ],
    [group, groupLabel],
  );
  return (
    <div className="col gap-lg" data-testid="fc-accuracy-page">
      <PageHeader
        title={t("plan.acc.title")}
        description={t("plan.acc.desc")}
        facts={overall ? [[t("plan.acc.fact.overall", { lag }), pct(overall.wape, 1)], [t("plan.fc.head.bias"), signedPct(overall.bias)], [t("plan.acc.fact.periods"), formatNumber(overall.periods)]] : []}
        actions={
          <Link className="btn" to={mfgPaths.forecast()}>
            <Icon name="chart" /> {t("plan.acc.btn.workbench")}
          </Link>
        }
      />
      <FilterBar>
        <div className="field">
          <span className="field-label">{t("plan.acc.label.lag")}</span>
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
          <Segmented<Group>
            label={t("plan.acc.label.group")}
            value={group}
            testId="acc-group"
            options={[
              { value: "abc", label: t("plan.fc.label.abc") },
              { value: "family", label: t("plan.fc.label.family") },
              { value: "item", label: t("plan.fc.head.item") },
            ]}
            onChange={(v) => setSearchParam(setParams, "group", v === "abc" ? "" : v)}
          />
        </div>
        <div className="field">
          <label htmlFor="acc-periods">{t("plan.acc.label.periods")}</label>
          <select id="acc-periods" className="select" value={String(periods)} onChange={(e) => setSearchParam(setParams, "periods", e.target.value === "6" ? "" : e.target.value)}>
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                {t("plan.acc.tpl.lastN", { n: p })}
              </option>
            ))}
          </select>
        </div>
      </FilterBar>
      <MfgError error={rep.error} onRetry={rep.reload} />
      {rep.loading && !d ? <Spinner /> : null}
      {d ? (
        <>
          <div className="pl-two">
            <section className="card">
              <div className="card-header pl-card-header">
                <h2 className="pl-h2">{t("plan.acc.chart.title", { group: groupLabel, lag })}</h2>
              </div>
              <div className="card-body">{d.rows.length ? <WapeBars rows={d.rows} mono={group === "item"} /> : <p className="muted" style={{ margin: 0 }}>{t("plan.acc.empty")}</p>}</div>
            </section>
            <Backtest b={d.backtest ?? null} />
          </div>
          <section className="card card-table" aria-label={t("plan.acc.table")}>
            <DataTable<AccuracyRow> rows={d.rows} columns={columns} rowKey={(r) => r.key} label={t("plan.acc.table")} testId="acc-table" exportName={`forecast-accuracy-lag${lag}`} empty={t("plan.acc.empty")} />
          </section>
        </>
      ) : null}
    </div>
  );
}

function Backtest({ b }: { b: ForecastSummary | null }) {
  const mix = Object.entries(b?.method_mix ?? {}).sort((x, y) => (y[1] ?? 0) - (x[1] ?? 0));
  return (
    <section className="card" data-testid="acc-backtest">
      <div className="card-header pl-card-header">
        <h2 className="pl-h2">{t("plan.acc.bt.title")}</h2>
      </div>
      <div className="card-body col pl-gap">
        {b ? (
          <>
            <p className="muted small" style={{ margin: 0 }}>{t("plan.acc.bt.hint")}</p>
            <Facts
              rows={[
                [t("plan.acc.bt.overall"), <WapeBadge key="o" v={b.wape} />],
                ...(["A", "B", "C"] as const).map((c): [string, ReactNode] => {
                  const x = b.by_abc?.[c];
                  return [t("plan.acc.bt.class", { c }), x ? <span key={c}><WapeBadge v={x.wape} /> <span className="muted small">{t("plan.tpl.itemsN", { n: num(x.items) })}</span></span> : "–"];
                }),
              ]}
            />
            {mix.length ? (
              <div>
                <div className="small muted">{t("plan.acc.bt.mix")}</div>
                <ul className="pl-mix">
                  {mix.map(([m, n]) => (
                    <li key={m}>
                      <span>{methodText(m as ForecastMethod)}</span>
                      <span className="pl-num">{num(n ?? 0)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        ) : (
          <p className="muted" style={{ margin: 0 }}>{t("plan.acc.bt.none")}</p>
        )}
      </div>
    </section>
  );
}

const ROW = 26;
const ML = 150;
const MR = 56;

/** Horizontal bars of WAPE per group (sorted worst first, at most 20), with the 25 % target as a dashed rule. */
function WapeBars({ rows, mono }: { rows: AccuracyRow[]; mono: boolean }) {
  const [ref, width] = useWidth<HTMLDivElement>(560);
  const [cur, setCur] = useState<number | null>(null);
  const data = [...rows].filter((r) => r.wape !== null).sort((a, b) => (b.wape ?? 0) - (a.wape ?? 0)).slice(0, 20);
  const innerW = Math.max(80, width - ML - MR);
  let hi = 0.3;
  for (const r of data) hi = Math.max(hi, r.wape ?? 0);
  const ticks = niceTicks(0, hi * 100, 4);
  const top = (ticks[ticks.length - 1] || 30) / 100;
  const x = (v: number) => ML + (v / top) * innerW;
  const H = data.length * ROW + 24;
  const aria = t("plan.acc.chart.aria", { n: data.length, worst: data[0]?.label ?? "", v: pct(data[0]?.wape ?? null, 0) });
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowDown") setCur((c) => Math.min(data.length - 1, (c ?? -1) + 1));
    else if (e.key === "ArrowUp") setCur((c) => Math.max(0, (c ?? data.length) - 1));
    else if (e.key === "Escape") setCur(null);
    else return;
    e.preventDefault();
  };
  const tone = (v: number) => (v <= 0.25 ? "var(--ok)" : v <= 0.5 ? "var(--warn)" : "var(--danger)");
  const c = cur !== null ? data[cur] : null;
  return (
    <figure className="pl-chart" data-testid="acc-bars">
      <div ref={ref} className="pl-chart-area" tabIndex={0} role="group" aria-label={`${aria} ${t("plan.chart.keysUpDown")}`} onKeyDown={onKey} onBlur={() => setCur(null)} onMouseLeave={() => setCur(null)}>
        <svg width={width} height={H} role="img" aria-label={aria}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={x(v / 100)} x2={x(v / 100)} y1={0} y2={H - 20} stroke="var(--grid)" />
              <text x={x(v / 100)} y={H - 6} textAnchor="middle" className="pl-axis">{`${formatNumber(v)} %`}</text>
            </g>
          ))}
          {data.map((r, i) => {
            const v = r.wape ?? 0;
            const y = i * ROW + 4;
            return (
              <g key={r.key} onMouseEnter={() => setCur(i)}>
                <rect x={0} y={y - 2} width={width} height={ROW} fill={cur === i ? "var(--shade)" : "transparent"} />
                <text x={ML - 8} y={y + 13} textAnchor="end" className={`pl-axis pl-bar-label${mono ? " mono" : ""}`}>
                  {r.label.length > 22 ? `${r.label.slice(0, 21)}…` : r.label}
                </text>
                <rect x={ML} y={y + 2} width={Math.max(1, x(v) - ML)} height={ROW - 10} rx={2} fill={tone(v)} opacity={0.85} />
                <text x={x(v) + 6} y={y + 13} className="pl-axis">{pct(v, 0)}</text>
              </g>
            );
          })}
          <line x1={x(0.25)} x2={x(0.25)} y1={0} y2={H - 20} stroke="var(--text-muted)" strokeDasharray="4 3" />
        </svg>
        {c && cur !== null ? (
          <div className="pl-tip" role="status" style={{ left: Math.min(x(c.wape ?? 0) + 40, width - 200), top: cur * ROW }}>
            <div className="pl-tip-title">{c.label}</div>
            <div className="pl-tip-row"><span>{t("plan.fc.head.wape")}</span><span>{pct(c.wape)}</span></div>
            <div className="pl-tip-row"><span>{t("plan.fc.head.bias")}</span><span>{signedPct(c.bias)}</span></div>
            <div className="pl-tip-row"><span>{t("plan.acc.head.actual")}</span><span>{num(c.actual)}</span></div>
          </div>
        ) : null}
      </div>
      <figcaption>
        <Legend
          label={t("plan.chart.legend")}
          items={[
            { label: t("plan.acc.legend.good"), color: "var(--ok)", kind: "box" },
            { label: t("plan.acc.legend.watch"), color: "var(--warn)", kind: "box" },
            { label: t("plan.acc.legend.poor"), color: "var(--danger)", kind: "box" },
            { label: t("plan.acc.trend.target"), color: "var(--text-muted)", kind: "dashed" },
          ]}
        />
      </figcaption>
      {rows.length > data.length ? <p className="muted small" style={{ margin: 0 }}>{t("plan.acc.chart.top", { n: data.length, m: rows.length })}</p> : null}
    </figure>
  );
}
