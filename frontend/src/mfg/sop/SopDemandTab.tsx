/**
 * S&OP demand review (M9 6.2): family x month grid by node with statistical forecast, open orders, prior consensus
 * and consensus; a consensus cell opens the override dialog (absolute or %, one node or all, month range, reason
 * required). Overrides apply in order and stay listed with who/when/why; removing one needs a reason too. A chart
 * shows the selected family (or the total) as consensus vs forecast vs prior.
 */
import { useMemo, useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Dialog } from "../../components/Dialog";
import { FilterBar } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { toast } from "../../components/Toast";
import { LineChart } from "../../finance/charts/LineChart";
import { niceTicks } from "../../finance/charts/scales";
import { t } from "../../lib/i18n";
import { formatDateTime, formatMoney, formatNumber } from "../../lib/locale";
import { addOverride, getDemand, removeOverride } from "../api/clientM9";
import type { SopCycle, SopOverride, SopOverrideInput } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { useLoad } from "../lib/useMfg";
import { usePersonName } from "../qa/common";
import { codeText9, monthLabel, monthShort, num, Segmented, useNodes } from "../network/shared";

type Nodes = ReturnType<typeof useNodes>;
type Measure = "stat_qty" | "order_qty" | "prior_consensus" | "consensus_qty";
const MEASURES: { k: Measure; label: "net.dem.stat" | "net.dem.orders" | "net.dem.prior" | "net.dem.consensus" }[] = [
  { k: "stat_qty", label: "net.dem.stat" },
  { k: "order_qty", label: "net.dem.orders" },
  { k: "prior_consensus", label: "net.dem.prior" },
  { k: "consensus_qty", label: "net.dem.consensus" },
];

export function DemandTab({ cycle, nodes, locked }: { cycle: SopCycle; nodes: Nodes; locked: boolean }) {
  const [node, setNode] = useState("");
  const [family, setFamily] = useState("");
  const [chartFam, setChartFam] = useState("");
  const [ovr, setOvr] = useState<{ family: string; month: string } | null>(null);
  const [del, setDel] = useState<SopOverride | null>(null);
  const [view, setView] = useState<"units" | "value">("units");
  const demand = useLoad((s) => getDemand(cycle.id, { node: node || undefined }, s), [cycle.id, node]);
  const d = demand.data;
  const ccy = cycle.report_currency;
  // aggregate rows of the selected node(s) by family x month
  const agg = useMemo(() => {
    const m = new Map<string, Map<string, { stat_qty: number; order_qty: number; prior_consensus: number; consensus_qty: number; value: number; aspFlags: Set<string> }>>();
    for (const r of d?.items ?? []) {
      if (family && r.family !== family) continue;
      if (!m.has(r.family)) m.set(r.family, new Map());
      const fm = m.get(r.family)!;
      const c = fm.get(r.month) ?? { stat_qty: 0, order_qty: 0, prior_consensus: 0, consensus_qty: 0, value: 0, aspFlags: new Set<string>() };
      c.stat_qty += r.stat_qty;
      c.order_qty += r.order_qty;
      c.prior_consensus += r.prior_consensus ?? 0;
      c.consensus_qty += r.consensus_qty;
      c.value += r.asp === null ? 0 : r.consensus_qty * r.asp;
      if (r.asp_source !== "history") c.aspFlags.add(r.asp_source);
      fm.set(r.month, c);
    }
    return m;
  }, [d, family]);
  const ovrCells = useMemo(() => {
    const s = new Set<string>();
    for (const o of d?.overrides ?? []) {
      if (o.removed_at) continue;
      if (node && o.node_owner_id && o.node_owner_id !== node) continue;
      for (const m of d?.months ?? []) if (m >= o.month_from && m <= o.month_to) s.add(`${o.family}|${m}`);
    }
    return s;
  }, [d, node]);
  if (demand.error && !d) return <MfgError error={demand.error} onRetry={demand.reload} />;
  if (!d) return <Spinner />;
  const months = d.months;
  const fams = [...agg.keys()].sort();
  const chartRows = (k: Measure) => months.map((m) => (chartFam ? agg.get(chartFam)?.get(m)?.[k] ?? 0 : fams.reduce((a, f) => a + (agg.get(f)?.get(m)?.[k] ?? 0), 0)));
  const cons = chartRows("consensus_qty");
  const stat = chartRows("stat_qty");
  const prior = chartRows("prior_consensus");
  const yMax = niceTicks(0, Math.max(1, ...cons, ...stat, ...prior), 4).slice(-1)[0] ?? 1;
  const active = (d.overrides ?? []).filter((o) => !o.removed_at);
  const totalCons = fams.reduce((a, f) => a + months.reduce((b, m) => b + (agg.get(f)?.get(m)?.consensus_qty ?? 0), 0), 0);
  const totalStat = fams.reduce((a, f) => a + months.reduce((b, m) => b + (agg.get(f)?.get(m)?.stat_qty ?? 0), 0), 0);
  const totalVal = fams.reduce((a, f) => a + months.reduce((b, m) => b + (agg.get(f)?.get(m)?.value ?? 0), 0), 0);
  return (
    <div className="col pl-gap" data-testid="sop-demand">
      <FilterBar
        chips={[
          ...(node ? [{ key: "node", label: t("net.label.node"), value: nodes.code(node), onClear: () => setNode("") }] : []),
          ...(family ? [{ key: "family", label: t("net.label.family"), value: family, onClear: () => setFamily("") }] : []),
        ]}
        end={<Segmented value={view} onChange={(x) => setView(x as typeof view)} label={t("net.dem.show")} options={[{ value: "units", label: t("net.dem.units") }, { value: "value", label: t("net.dem.value", { c: ccy }) }]} testId="sop-dem-view" />}
      >
        <div className="field">
          <label htmlFor="sop-dem-node">{t("net.label.node")}</label>
          <select id="sop-dem-node" className="select sm" value={node} onChange={(e) => setNode(e.target.value)} data-testid="sop-dem-node">
            <option value="">{t("net.label.allNodes")}</option>
            {nodes.nodes.map((n) => (
              <option key={n.owner_id} value={n.owner_id}>
                {n.code}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="sop-dem-fam">{t("net.label.family")}</label>
          <select id="sop-dem-fam" className="select sm" value={family} onChange={(e) => setFamily(e.target.value)}>
            <option value="">{t("net.dem.allFamilies")}</option>
            {d.families.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>
      </FilterBar>
      <div className="net-kpis">
        <div className="card net-kpi">
          <span className="net-kpi-label">{t("net.dem.consensus")}</span>
          <span className="net-kpi-value">
            {formatNumber(totalCons)}
            <span className="net-kpi-unit">{t("net.unit.units")}</span>
          </span>
          <span className="net-kpi-sub">{totalStat ? t("net.dem.vsStatTpl", { v: formatNumber(((totalCons / totalStat) - 1) * 100, 1) }) : ""}</span>
        </div>
        <div className="card net-kpi">
          <span className="net-kpi-label">{t("net.dem.revenueAtAsp")}</span>
          <span className="net-kpi-value">
            {formatMoney(totalVal, ccy, { compact: true })}
            <span className="net-kpi-unit">{ccy}</span>
          </span>
        </div>
        <div className="card net-kpi">
          <span className="net-kpi-label">{t("net.dem.overrides")}</span>
          <span className="net-kpi-value">{formatNumber(active.length)}</span>
        </div>
      </div>
      {locked ? null : <p className="small muted" style={{ margin: 0 }}>{t("net.dem.hint")}</p>}
      <section className="card card-table">
        <div className="pl-pivot-wrap">
          <table className="pl-pivot" aria-label={t("net.dem.aria")} data-testid="sop-demand-grid">
            <thead>
              <tr>
                <th scope="col">{t("net.dem.row")}</th>
                {months.map((m) => (
                  <th key={m} scope="col">
                    {monthShort(m)}
                  </th>
                ))}
                <th scope="col">{t("net.dem.total")}</th>
              </tr>
            </thead>
            <tbody>
              {fams.map((f) => {
                const fm = agg.get(f)!;
                const flags = new Set([...fm.values()].flatMap((c) => [...c.aspFlags]));
                return [
                  <tr key={`${f}-h`}>
                    <th scope="rowgroup" colSpan={months.length + 2} style={{ background: "var(--surface-2)" }}>
                      <span className="row" style={{ gap: 8 }}>
                        <strong>{f}</strong>
                        {flags.has("cost") ? (
                          <span className="badge warn" title={codeText9("ASP_FROM_COST")}>
                            <Icon name="info" /> {t("net.dem.aspCost")}
                          </span>
                        ) : null}
                        <button type="button" className="btn ghost sm" onClick={() => setChartFam(chartFam === f ? "" : f)} aria-pressed={chartFam === f}>
                          <Icon name="chart" /> {t("net.dem.chartThis")}
                        </button>
                      </span>
                    </th>
                  </tr>,
                  ...MEASURES.map((ms) => {
                    const isCons = ms.k === "consensus_qty";
                    const sum = months.reduce((a, m) => a + (view === "value" && isCons ? fm.get(m)?.value ?? 0 : fm.get(m)?.[ms.k] ?? 0), 0);
                    return (
                      <tr key={`${f}-${ms.k}`} className={isCons ? "sop-total" : "net-grid-sub"} data-testid={isCons ? "sop-cons-row" : undefined} data-family={f}>
                        <th scope="row">{t(ms.label)}</th>
                        {months.map((m) => {
                          const c = fm.get(m);
                          const v = view === "value" && isCons ? c?.value ?? 0 : c?.[ms.k] ?? 0;
                          const text = view === "value" && isCons ? formatMoney(v, ccy, { compact: true }) : num(v);
                          const isO = isCons && ovrCells.has(`${f}|${m}`);
                          return (
                            <td key={m} className={isO ? "sop-cell-ovr" : undefined}>
                              {isCons && !locked ? (
                                <button type="button" className="sop-cell-btn" onClick={() => setOvr({ family: f, month: m })} aria-label={t("net.dem.ovrAria", { f, m: monthLabel(m), v: text })} data-testid="sop-cons-cell" data-month={m}>
                                  {isO ? <Icon name="flag" size={10} /> : null} {text}
                                </button>
                              ) : (
                                <>
                                  {isO ? <Icon name="flag" size={10} /> : null} {text}
                                </>
                              )}
                            </td>
                          );
                        })}
                        <td>{view === "value" && isCons ? formatMoney(sum, ccy, { compact: true }) : num(sum)}</td>
                      </tr>
                    );
                  }),
                ];
              })}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card col pl-gap" aria-labelledby="sop-dem-chart-h">
        <h2 className="pl-h2" id="sop-dem-chart-h">
          {chartFam ? t("net.dem.chartFam", { f: chartFam }) : t("net.dem.chartAll")}
        </h2>
        <LineChart
          months={months.map((m) => m.slice(0, 7))}
          series={[
            { key: "cons", label: t("net.dem.consensus"), color: "var(--pl-c1)", values: cons },
            { key: "stat", label: t("net.dem.stat"), color: "var(--pl-c3)", values: stat, dashed: true },
            { key: "prior", label: t("net.dem.prior"), color: "var(--pl-c8)", values: prior, dashed: true },
          ]}
          yMax={yMax}
          step={false}
          formatY={(v) => formatNumber(v)}
          ariaLabel={t("net.dem.chartAria")}
          caption={t("net.dem.chartCaption")}
          testId="sop-dem-chart"
        />
      </section>
      <OverridesList overrides={d.overrides ?? []} nodes={nodes} locked={locked} onRemove={setDel} />
      {ovr ? (
        <OverrideDialog
          cycle={cycle}
          family={ovr.family}
          month={ovr.month}
          months={months}
          node={node}
          nodes={nodes}
          current={agg.get(ovr.family)?.get(ovr.month)?.consensus_qty ?? 0}
          onClose={() => setOvr(null)}
          onSaved={() => {
            setOvr(null);
            demand.reload();
          }}
        />
      ) : null}
      {del ? (
        <RemoveOverride
          o={del}
          onClose={() => setDel(null)}
          onDone={() => {
            setDel(null);
            demand.reload();
          }}
        />
      ) : null}
    </div>
  );
}

function OverridesList({ overrides, nodes, locked, onRemove }: { overrides: SopOverride[]; nodes: Nodes; locked: boolean; onRemove(o: SopOverride): void }) {
  const personName = usePersonName();
  const columns = useMemo<Column<SopOverride>[]>(
    () => [
      { key: "seq", header: "#", width: "50px", align: "right", sortValue: (o) => o.seq, render: (o) => <span className="pl-num">{o.seq}</span> },
      { key: "scope", header: t("net.label.node"), width: "100px", render: (o) => (o.node_owner_id ? <span className="mono">{nodes.code(o.node_owner_id)}</span> : t("net.label.allNodes")) },
      { key: "family", header: t("net.label.family"), width: "100px", sortValue: (o) => o.family, render: (o) => o.family },
      { key: "months", header: t("net.dem.months"), width: "160px", render: (o) => (o.month_from === o.month_to ? monthLabel(o.month_from) : `${monthLabel(o.month_from)} – ${monthLabel(o.month_to)}`) },
      { key: "change", header: t("net.dem.change"), width: "110px", align: "right", render: (o) => <span className="pl-num">{o.mode === "pct" ? `${o.value > 0 ? "+" : ""}${formatNumber(o.value, 1)} %` : t("net.dem.setTo", { v: formatNumber(o.value) })}</span> },
      { key: "reason", header: t("plan.label.reason"), width: "minmax(200px, 1fr)", wrap: true, render: (o) => o.reason },
      { key: "by", header: t("net.dem.by"), width: "170px", drop: 1, render: (o) => <span className="pl-by"><span>{personName(o.created_by)}</span><span className="muted small">{formatDateTime(o.created_at)}</span></span> },
      {
        key: "state",
        header: <span className="sr-only">{t("plan.label.actions")}</span>,
        label: t("plan.label.actions"),
        width: "110px",
        render: (o) =>
          o.removed_at ? (
            <span className="badge info">
              <Icon name="ban" /> {t("net.dem.removed")}
            </span>
          ) : locked ? null : (
            <button type="button" className="btn ghost sm" onClick={() => onRemove(o)} data-testid="sop-ovr-remove">
              <Icon name="trash" /> {t("net.dem.remove")}
            </button>
          ),
      },
    ],
    [nodes, locked, onRemove, personName],
  );
  return (
    <section className="card card-table" aria-labelledby="sop-ovr-h">
      <div className="pl-card-header" style={{ padding: "8px 12px" }}>
        <h2 className="pl-h2" id="sop-ovr-h">
          {t("net.dem.overrides")}
        </h2>
        <span className="muted small">{t("net.dem.ovrOrder")}</span>
      </div>
      <DataTable<SopOverride> rows={overrides} columns={columns} rowKey={(o) => o.id} label={t("net.dem.overrides")} testId="sop-overrides" exportName="sop-overrides" empty={t("net.dem.noOverrides")} />
    </section>
  );
}

function OverrideDialog({ cycle, family, month, months, node, nodes, current, onClose, onSaved }: { cycle: SopCycle; family: string; month: string; months: string[]; node: string; nodes: Nodes; current: number; onClose(): void; onSaved(): void }) {
  const [scope, setScope] = useState(node);
  const [mode, setMode] = useState<"abs" | "pct">("pct");
  const [value, setValue] = useState("");
  const [from, setFrom] = useState(month);
  const [to, setTo] = useState(month);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const v = Number(value);
  const valid = value !== "" && Number.isFinite(v) && (mode === "pct" ? v >= -100 && v <= 500 : v >= 0) && reason.trim().length > 0 && to >= from;
  const preview = mode === "pct" ? current * (1 + v / 100) : v;
  const save = async () => {
    setBusy(true);
    setErr(null);
    const body: SopOverrideInput = { node_owner_id: scope || null, family, month_from: from, month_to: to, mode, value: v, reason: reason.trim() };
    try {
      await addOverride(cycle.id, body);
      toast(t("net.dem.toast.saved"));
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("net.dem.dlg.title", { f: family })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!valid || busy} onClick={() => void save()} data-testid="sop-ovr-save">
            <Icon name="save" /> {t("net.dem.btn.apply")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="ovr-node">{t("net.label.node")}</label>
            <select id="ovr-node" className="select" value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="">{t("net.label.allNodes")}</option>
              {nodes.nodes.map((n) => (
                <option key={n.owner_id} value={n.owner_id}>
                  {n.code}
                </option>
              ))}
            </select>
            <span className="hint">{scope ? "" : mode === "pct" ? t("net.dem.hint.allPct") : t("net.dem.hint.allAbs")}</span>
          </div>
          {(["from", "to"] as const).map((k) => (
            <div className="field" key={k}>
              <label htmlFor={`ovr-${k}`}>{k === "from" ? t("net.dem.from") : t("net.dem.to")}</label>
              <select id={`ovr-${k}`} className="select" value={k === "from" ? from : to} onChange={(e) => (k === "from" ? setFrom(e.target.value) : setTo(e.target.value))}>
                {months.map((m) => (
                  <option key={m} value={m}>
                    {monthLabel(m)}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          <Segmented value={mode} onChange={(x) => setMode(x as typeof mode)} label={t("net.dem.mode")} options={[{ value: "pct", label: t("net.dem.modePct") }, { value: "abs", label: t("net.dem.modeAbs") }]} />
          <div className="field">
            <label htmlFor="ovr-value">{mode === "pct" ? t("net.dem.valuePct") : t("net.dem.valueAbs")}</label>
            <input id="ovr-value" className="input pl-w-140" type="number" step={mode === "pct" ? 0.5 : 1} value={value} onChange={(e) => setValue(e.target.value)} data-testid="sop-ovr-value" data-autofocus />
          </div>
          {value !== "" && Number.isFinite(v) && from === to ? (
            <span className="small muted pl-num">{t("net.dem.preview", { a: formatNumber(current), b: formatNumber(Math.round(preview)) })}</span>
          ) : null}
        </div>
        <div className="field">
          <label htmlFor="ovr-reason">
            {t("plan.label.reason")} <span className="req" aria-hidden />
          </label>
          <textarea id="ovr-reason" className="textarea" rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="sop-ovr-reason" />
          <span className="hint">{t("net.dem.hint.reason")}</span>
        </div>
      </div>
    </Dialog>
  );
}

function RemoveOverride({ o, onClose, onDone }: { o: SopOverride; onClose(): void; onDone(): void }) {
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  return (
    <ConfirmDialog
      title={t("net.dem.dlg.removeTitle", { f: o.family })}
      confirmLabel={t("net.dem.remove")}
      danger
      busy={busy}
      confirmDisabled={!why.trim()}
      onCancel={onClose}
      onConfirm={() => {
        setBusy(true);
        removeOverride(o.id, why.trim())
          .then(onDone, (e: unknown) => setErr(e))
          .finally(() => setBusy(false));
      }}
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{o.reason}</p>
        <div className="field">
          <label htmlFor="ovr-rm-why">
            {t("plan.label.reason")} <span className="req" aria-hidden />
          </label>
          <textarea id="ovr-rm-why" className="textarea" rows={2} maxLength={500} value={why} onChange={(e) => setWhy(e.target.value)} />
        </div>
      </div>
    </ConfirmDialog>
  );
}

