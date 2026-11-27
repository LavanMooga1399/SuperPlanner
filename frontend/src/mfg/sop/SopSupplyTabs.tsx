/**
 * S&OP supply review, financial view and scenario comparison (M9 6.3-6.5). Supply: the cycle's scenarios (baseline
 * first) with run status and headline KPIs, and the rough-cut heatmap of the chosen scenario (available vs required
 * hours per node x capacity group x month; watch > 85 %, alert > 100 % required). Financial: revenue, COGS, gross
 * margin, inventory and capex in the report currency by month. Compare: up to five scenarios side by side, deltas
 * against the first (baseline), with "Recommend" in pre-S&OP.
 */
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { toast } from "../../components/Toast";
import { LineChart } from "../../finance/charts/LineChart";
import { niceTicks } from "../../finance/charts/scales";
import { t, type StringKey } from "../../lib/i18n";
import { formatDateTime, formatMoney, formatNumber } from "../../lib/locale";
import { compareScenarios, copyScenario, createScenario, getFinancial, getRoughCut, recommendScenario, runScenario } from "../api/clientM9";
import type { SopCycle, SopKpiSet, SopKpis, SopScenario } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { Delta, HeatValue, heatClass, KpiCard, monthLabel, monthShort, NodeTag, num, pct, pct100, Segmented, useNodes } from "../network/shared";

type Nodes = ReturnType<typeof useNodes>;

export function ScenarioChip({ s }: { s: SopScenario }) {
  if (s.status === "running")
    return (
      <span className="badge accent">
        <Icon name="loader" /> {t("net.scn.status.running")}
      </span>
    );
  if (s.status === "failed")
    return (
      <span className="badge danger" title={s.error ?? undefined}>
        <Icon name="x" /> {t("net.scn.status.failed")}
      </span>
    );
  if (s.status === "draft")
    return (
      <span className="badge info">
        <Icon name="file" /> {t("net.scn.status.draft")}
      </span>
    );
  return s.validator && !s.validator.ok ? (
    <span className="badge danger">
      <Icon name="alert" /> {t("net.scn.invalid")}
    </span>
  ) : (
    <span className="badge ok">
      <Icon name="check" /> {t("net.scn.status.completed")}
    </span>
  );
}

// ---------------------------------------------------------------- supply review
export function SupplyTab({ cycle, nodes, scenarios, onChanged }: { cycle: SopCycle; nodes: Nodes; scenarios: SopScenario[]; onChanged(): void }) {
  const canEdit = useCan("sop_edit");
  const navigate = useNavigate();
  const [sel, setSel] = useState<string>(cycle.recommended_scenario_id ?? scenarios.find((s) => s.baseline)?.id ?? "");
  const [create, setCreate] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const done = scenarios.filter((s) => s.status === "completed");
  const shown = sel && done.some((s) => s.id === sel) ? sel : done[0]?.id ?? "";
  const run = (s: SopScenario) => {
    setErr(null);
    runScenario(s.id)
      .then(() => {
        toast(t("net.scn.toast.running", { n: s.number }));
        onChanged();
      })
      .catch((e: unknown) => setErr(e));
  };
  const copy = (s: SopScenario) => {
    setErr(null);
    copyScenario(s.id, cycle.id)
      .then((x) => navigate(mfgPaths.sopScenario(x.id)))
      .catch((e: unknown) => setErr(e));
  };
  const ccy = cycle.report_currency;
  const columns = useMemo<Column<SopScenario>[]>(
    () => [
      {
        key: "number",
        header: t("net.scn.head.scenario"),
        width: "minmax(220px, 1fr)",
        sortValue: (s) => `${s.baseline ? 0 : 1}${s.number}`,
        exportValue: (s) => `${s.number} ${s.name}`,
        render: (s) => (
          <span className="row" style={{ gap: 6, minWidth: 0 }}>
            <Link to={mfgPaths.sopScenario(s.id)} className="mono" onClick={(e) => e.stopPropagation()}>
              {s.number}
            </Link>
            <span className="mfg-ellipsis">{s.name}</span>
            {s.baseline ? <span className="badge info">{t("net.scn.baseline")}</span> : null}
            {s.id === cycle.recommended_scenario_id ? (
              <span className="badge accent">
                <Icon name="star" /> {t("net.cyc.recommended")}
              </span>
            ) : null}
          </span>
        ),
      },
      { key: "status", header: t("net.run.head.status"), width: "130px", render: (s) => <ScenarioChip s={s} /> },
      { key: "changes", header: t("net.scn.head.changes"), width: "100px", align: "right", sortValue: (s) => s.changes.length, render: (s) => <span className="pl-num">{num(s.changes.length)}</span> },
      { key: "service", header: t("net.kpi.service"), width: "100px", align: "right", sortValue: (s) => s.kpis?.horizon.service_pct ?? -1, render: (s) => <span className="pl-num">{pct100(s.kpis?.horizon.service_pct)}</span> },
      { key: "unmet", header: t("net.kpi.unmet"), width: "110px", align: "right", sortValue: (s) => s.kpis?.horizon.unmet_units ?? 0, render: (s) => <span className="pl-num">{num(s.kpis?.horizon.unmet_units)}</span> },
      { key: "gm", header: t("net.kpi.gm"), width: "130px", align: "right", drop: 2, sortValue: (s) => s.kpis?.horizon.gross_margin ?? 0, render: (s) => <span className="pl-num">{formatMoney(s.kpis?.horizon.gross_margin, ccy, { compact: true })}</span> },
      { key: "run", header: t("net.scn.head.runAt"), width: "140px", drop: 3, render: (s) => (s.run_at ? formatDateTime(s.run_at) : "–") },
      {
        key: "actions",
        header: <span className="sr-only">{t("plan.label.actions")}</span>,
        label: t("plan.label.actions"),
        width: "150px",
        render: (s) => (
          <span className="row" style={{ gap: 4 }}>
            <button type="button" className="btn sm" disabled={!canEdit || s.status === "running"} onClick={(e) => (e.stopPropagation(), run(s))} data-testid="sop-scn-run">
              <Icon name="play" /> {t("net.scn.btn.run")}
            </button>
            <button type="button" className="btn ghost sm icon" disabled={!canEdit} aria-label={t("net.scn.btn.copy")} title={t("net.scn.btn.copy")} onClick={(e) => (e.stopPropagation(), copy(s))}>
              <Icon name="copy" />
            </button>
          </span>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cycle, canEdit, ccy],
  );
  return (
    <div className="col pl-gap" data-testid="sop-supply">
      <MfgError error={err} />
      {!scenarios.some((s) => s.baseline && s.status === "completed") ? <Banner tone="warn">{t("net.scn.needBaseline")}</Banner> : null}
      <section className="card card-table" aria-labelledby="sop-scn-h">
        <div className="pl-card-header" style={{ padding: "8px 12px" }}>
          <h2 className="pl-h2" id="sop-scn-h">
            {t("net.scn.title")}
          </h2>
          <button type="button" className="btn sm" disabled={!canEdit} title={canEdit ? undefined : needsText("sop_edit")} onClick={() => setCreate(true)} data-testid="sop-scn-new">
            <Icon name="plus" /> {t("net.scn.btn.new")}
          </button>
        </div>
        <DataTable<SopScenario>
          rows={scenarios}
          columns={columns}
          rowKey={(s) => s.id}
          label={t("net.scn.title")}
          testId="sop-scenarios"
          onRowClick={(s) => setSel(s.id)}
          rowExtras={(s) => ({ testId: "sop-scn-row", ariaSelected: s.id === shown, data: { status: s.status } })}
          exportName="sop-scenarios"
          empty={t("net.scn.empty")}
        />
      </section>
      {shown ? <RoughCut scenarioId={shown} label={scenarios.find((s) => s.id === shown)} nodes={nodes} /> : null}
      {create ? <NewScenarioDialog cycle={cycle} scenarios={scenarios} onClose={() => setCreate(false)} onCreated={(s) => navigate(mfgPaths.sopScenario(s.id))} /> : null}
    </div>
  );
}

function RoughCut({ scenarioId, label, nodes }: { scenarioId: string; label: SopScenario | undefined; nodes: Nodes }) {
  const rc = useLoad((s) => getRoughCut(scenarioId, s), [scenarioId]);
  const [measure, setMeasure] = useState<"required" | "planned">("required");
  const data = useMemo(() => {
    const rows = new Map<string, { node: string; group: string; cells: Map<string, { a: number; r: number; p: number; f: number | null }> }>();
    for (const x of rc.data?.items ?? []) {
      const k = `${x.node_owner_id}|${x.cap_group}`;
      if (!rows.has(k)) rows.set(k, { node: String(x.node_owner_id), group: x.cap_group, cells: new Map() });
      rows.get(k)!.cells.set(x.month, { a: x.available, r: x.required, p: x.planned, f: x.factor });
    }
    return [...rows.values()];
  }, [rc.data]);
  if (rc.error) return <MfgError error={rc.error} onRetry={rc.reload} />;
  if (!rc.data) return <Spinner />;
  return (
    <section className="card col pl-gap" aria-labelledby="sop-rc-h" data-testid="sop-roughcut">
      <div className="pl-card-header">
        <h2 className="pl-h2" id="sop-rc-h">
          {t("net.rc.title", { s: label ? `${label.number} ${label.name}` : "" })}
        </h2>
        <Segmented value={measure} onChange={(x) => setMeasure(x as typeof measure)} label={t("net.rc.measure")} options={[{ value: "required", label: t("net.rc.required") }, { value: "planned", label: t("net.rc.planned") }]} />
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        {measure === "required" ? t("net.rc.legendReq") : t("net.rc.legendPlan")}
      </p>
      <div className="pl-pivot-wrap">
        <table className="pl-pivot net-heat" aria-label={t("net.rc.aria")}>
          <thead>
            <tr>
              <th scope="col">{t("net.cap.group")}</th>
              {rc.data.months.map((m) => (
                <th key={m} scope="col">
                  {monthShort(m)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={`${r.node}|${r.group}`}>
                <th scope="row">
                  <span className="row" style={{ gap: 6 }}>
                    <NodeTag node={nodes.byId.get(r.node)} id={r.node} /> {r.group}
                  </span>
                </th>
                {rc.data!.months.map((m) => {
                  const c = r.cells.get(m);
                  const u = c && c.a > 0 ? (measure === "required" ? c.r : c.p) / c.a : null;
                  return (
                    <td key={m} className={heatClass(u)} title={c ? t("net.rc.cellTitle", { r: num(c.r), p: num(c.p), a: num(c.a), f: c.f === null ? "–" : pct(c.f, 0) }) : undefined}>
                      <HeatValue u={u} />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function NewScenarioDialog({ cycle, scenarios, onClose, onCreated }: { cycle: SopCycle; scenarios: SopScenario[]; onClose(): void; onCreated(s: SopScenario): void }) {
  const [name, setName] = useState("");
  const [from, setFrom] = useState(scenarios.find((s) => s.baseline)?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      const s = from ? await copyScenario(from, cycle.id) : await createScenario({ cycle_id: cycle.id, name: name.trim(), changes: [], capex_note: "" });
      onCreated(s);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("net.scn.dlg.newTitle")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={busy || (!from && !name.trim())} onClick={() => void go()} data-testid="sop-scn-create">
            <Icon name="plus" /> {t("net.scn.btn.create")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{t("net.scn.dlg.newBody")}</p>
        <div className="field">
          <label htmlFor="scn-from">{t("net.scn.label.startFrom")}</label>
          <select id="scn-from" className="select" value={from} onChange={(e) => setFrom(e.target.value)}>
            <option value="">{t("net.scn.label.empty")}</option>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {t("net.scn.label.copyOf", { n: `${s.number} ${s.name}` })}
              </option>
            ))}
          </select>
        </div>
        {!from ? (
          <div className="field">
            <label htmlFor="scn-name">{t("net.scn.label.name")}</label>
            <input id="scn-name" className="input" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- financial
const FIN_ROWS: { k: "revenue" | "cogs" | "freight" | "gross_margin" | "gm_pct" | "inventory_value" | "days_of_cover" | "capex"; label: StringKey; money: boolean }[] = [
  { k: "revenue", label: "net.kpi.revenue", money: true },
  { k: "cogs", label: "net.kpi.cogs", money: true },
  { k: "freight", label: "net.kpi.freight", money: true },
  { k: "gross_margin", label: "net.kpi.gm", money: true },
  { k: "gm_pct", label: "net.kpi.gmPct", money: false },
  { k: "inventory_value", label: "net.kpi.inventory", money: true },
  { k: "days_of_cover", label: "net.kpi.cover", money: false },
  { k: "capex", label: "net.kpi.capex", money: true },
];

export function FinancialTab({ cycle, nodes, scenarios }: { cycle: SopCycle; nodes: Nodes; scenarios: SopScenario[] }) {
  const done = scenarios.filter((s) => s.status === "completed");
  const [sel, setSel] = useState(cycle.recommended_scenario_id ?? done[0]?.id ?? "");
  const [groupBy, setGroupBy] = useState<"total" | "node" | "family">("total");
  const fin = useLoad((s) => (sel ? getFinancial(sel, groupBy, s) : null), [sel, groupBy]);
  const f = fin.data;
  if (!done.length) return <p className="muted card">{t("net.fin.none")}</p>;
  const ccy = f?.currency ?? cycle.report_currency;
  const total = f?.rows.filter((r) => r.key === "total" && r.month) ?? [];
  const months = f?.months ?? [];
  const byMonth = new Map(total.map((r) => [r.month!, r]));
  const rev = months.map((m) => byMonth.get(m)?.revenue ?? 0);
  const cogs = months.map((m) => byMonth.get(m)?.cogs ?? 0);
  const gm = months.map((m) => byMonth.get(m)?.gross_margin ?? 0);
  const yMax = niceTicks(0, Math.max(1, ...rev, ...cogs), 4).slice(-1)[0] ?? 1;
  const keys = [...new Set((f?.rows ?? []).filter((r) => r.key !== "total").map((r) => r.key))];
  const cell = (key: string, m: string) => f?.rows.find((r) => r.key === key && r.month === m);
  const fmt = (v: number | null | undefined, money: boolean, k: string) => (money ? formatMoney(v, ccy, { compact: Math.abs(v ?? 0) >= 1e6 }) : k === "gm_pct" ? pct100(v) : num(v));
  return (
    <div className="col pl-gap" data-testid="sop-financial">
      <div className="filter-bar toolbar mfg-filters">
        <div className="field">
          <label htmlFor="fin-sc">{t("net.cyc.appr.scenario")}</label>
          <select id="fin-sc" className="select sm" value={sel} onChange={(e) => setSel(e.target.value)}>
            {done.map((s) => (
              <option key={s.id} value={s.id}>
                {s.number} · {s.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <span className="small muted">{t("net.fin.groupBy")}</span>
          <Segmented value={groupBy} onChange={(x) => setGroupBy(x as typeof groupBy)} label={t("net.fin.groupBy")} options={[{ value: "total", label: t("net.fin.total") }, { value: "node", label: t("net.label.node") }, { value: "family", label: t("net.label.family") }]} />
        </div>
        <span className="small muted">{t("net.fin.currency", { c: ccy })}</span>
      </div>
      <MfgError error={fin.error} onRetry={fin.reload} />
      {!f ? (
        <Spinner />
      ) : (
        <>
          <div className="net-kpis">
            <KpiCard label={t("net.kpi.revenue")} value={formatMoney(f.totals.horizon.revenue, ccy, { compact: true })} unit={ccy} sub={t("net.fin.next3", { v: formatMoney(f.totals.next3.revenue, ccy, { compact: true }) })} />
            <KpiCard label={t("net.kpi.cogs")} value={formatMoney(f.totals.horizon.cogs, ccy, { compact: true })} unit={ccy} />
            <KpiCard label={t("net.kpi.gm")} value={formatMoney(f.totals.horizon.gross_margin, ccy, { compact: true })} unit={ccy} sub={t("net.tpl.gmPct", { v: pct100(f.totals.horizon.gm_pct) })} />
            <KpiCard label={t("net.kpi.inventory")} value={formatMoney(f.totals.horizon.inventory_value, ccy, { compact: true })} unit={ccy} sub={f.totals.horizon.days_of_cover === null ? undefined : t("net.tpl.cover", { n: num(f.totals.horizon.days_of_cover) })} />
            <KpiCard label={t("net.kpi.capex")} value={formatMoney(f.totals.horizon.capex, ccy, { compact: true })} unit={ccy} />
            <KpiCard label={t("net.fin.year")} value={formatMoney(f.totals.year.gross_margin, ccy, { compact: true })} unit={ccy} sub={t("net.fin.yearSub")} />
          </div>
          {f.warnings.length ? <Banner tone="warn">{f.warnings.map((w) => w.code).join(", ")}</Banner> : null}
          <section className="card card-table">
            <div className="pl-pivot-wrap">
              <table className="pl-pivot" aria-label={t("net.fin.aria", { c: ccy })} data-testid="sop-pl">
                <thead>
                  <tr>
                    <th scope="col">{t("net.fin.line")}</th>
                    {months.map((m) => (
                      <th key={m} scope="col">
                        {monthShort(m)}
                      </th>
                    ))}
                    <th scope="col">{t("net.fin.horizon")}</th>
                  </tr>
                </thead>
                <tbody>
                  {groupBy === "total"
                    ? FIN_ROWS.map((r) => (
                        <tr key={r.k} className={r.k === "gross_margin" ? "sop-total" : undefined}>
                          <th scope="row">{t(r.label)}</th>
                          {months.map((m) => (
                            <td key={m}>{fmt(byMonth.get(m)?.[r.k], r.money, r.k)}</td>
                          ))}
                          <td>{fmt(f.totals.horizon[r.k], r.money, r.k)}</td>
                        </tr>
                      ))
                    : keys.flatMap((key) =>
                        (["revenue", "gross_margin", "gm_pct"] as const).map((k) => {
                          const def = FIN_ROWS.find((x) => x.k === k)!;
                          const sum = months.reduce((a, m) => a + (cell(key, m)?.[k] ?? 0), 0);
                          return (
                            <tr key={`${key}-${k}`} className={k === "revenue" ? undefined : "net-grid-sub"}>
                              <th scope="row">{k === "revenue" ? <span className="row" style={{ gap: 6 }}>{groupBy === "node" ? <NodeTag node={nodes.byId.get(key)} id={key} /> : <strong>{key}</strong>} {t(def.label)}</span> : t(def.label)}</th>
                              {months.map((m) => (
                                <td key={m}>{fmt(cell(key, m)?.[k], def.money, k)}</td>
                              ))}
                              <td>{k === "gm_pct" ? "" : fmt(sum, def.money, k)}</td>
                            </tr>
                          );
                        }),
                      )}
                </tbody>
              </table>
            </div>
          </section>
          <section className="card col pl-gap" aria-labelledby="fin-chart-h">
            <h2 className="pl-h2" id="fin-chart-h">
              {t("net.fin.chart", { c: ccy })}
            </h2>
            <LineChart
              months={months.map((m) => m.slice(0, 7))}
              series={[
                { key: "rev", label: t("net.kpi.revenue"), color: "var(--pl-c1)", values: rev },
                { key: "cogs", label: t("net.kpi.cogs"), color: "var(--pl-c3)", values: cogs, dashed: true },
                { key: "gm", label: t("net.kpi.gm"), color: "var(--pl-c2)", values: gm },
              ]}
              yMax={yMax}
              step={false}
              formatY={(v) => formatMoney(v, ccy, { compact: true })}
              ariaLabel={t("net.fin.chart", { c: ccy })}
              caption={t("net.fin.chartCaption")}
              testId="sop-fin-chart"
            />
          </section>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- compare
type KRow = { k: keyof SopKpiSet; label: StringKey; kind: "num" | "money" | "pct" | "days"; better: "up" | "down" };
const KROWS: KRow[] = [
  { k: "service_pct", label: "net.kpi.service", kind: "pct", better: "up" },
  { k: "unmet_units", label: "net.kpi.unmet", kind: "num", better: "down" },
  { k: "delivered_units", label: "net.kpi.delivered", kind: "num", better: "up" },
  { k: "revenue", label: "net.kpi.revenue", kind: "money", better: "up" },
  { k: "cogs", label: "net.kpi.cogs", kind: "money", better: "down" },
  { k: "gross_margin", label: "net.kpi.gm", kind: "money", better: "up" },
  { k: "gm_pct", label: "net.kpi.gmPct", kind: "pct", better: "up" },
  { k: "inventory_value", label: "net.kpi.inventory", kind: "money", better: "down" },
  { k: "days_of_cover", label: "net.kpi.cover", kind: "days", better: "down" },
  { k: "capex", label: "net.kpi.capex", kind: "money", better: "down" },
];

export function CompareTab({ cycle, scenarios, onChanged }: { cycle: SopCycle; scenarios: SopScenario[]; onChanged(): void }) {
  const canEdit = useCan("sop_edit");
  const done = scenarios.filter((s) => s.status === "completed");
  const initial = [...done].sort((a, b) => Number(b.baseline) - Number(a.baseline)).slice(0, 5).map((s) => s.id);
  const [ids, setIds] = useState<string[]>(initial);
  const [period, setPeriod] = useState<"horizon" | "year" | "next3">("horizon");
  const [rec, setRec] = useState<SopScenario | null>(null);
  const cmp = useLoad((s) => (ids.length ? compareScenarios(ids, s) : null), [ids.join(",")]);
  const c = cmp.data;
  if (!done.length) return <p className="muted card">{t("net.fin.none")}</p>;
  const ccy = c?.currency ?? cycle.report_currency;
  const toggle = (id: string) => setIds((x) => (x.includes(id) ? x.filter((y) => y !== id) : x.length >= 5 ? x : [...x, id]));
  const value = (k: KRow, v: number | null | undefined) => (k.kind === "money" ? formatMoney(v, ccy, { compact: Math.abs(v ?? 0) >= 1e5 }) : k.kind === "pct" ? pct100(v) : k.kind === "days" ? (v === null || v === undefined ? "–" : t("net.tpl.days", { n: num(v) })) : num(v));
  const domestic = domesticCodes(c?.items.map((x) => x.kpis) ?? []);
  const canRecommend = canEdit && cycle.status === "pre_sop";
  return (
    <div className="col pl-gap" data-testid="sop-compare">
      <fieldset className="pl-fieldset">
        <legend>{t("net.cmp.pick")}</legend>
        <div className="row wrap" style={{ gap: 12 }}>
          {done.map((s) => (
            <label key={s.id} className="row small" style={{ gap: 6 }}>
              <input type="checkbox" checked={ids.includes(s.id)} disabled={!ids.includes(s.id) && ids.length >= 5} onChange={() => toggle(s.id)} />
              <span className="mono">{s.number}</span> {s.name}
            </label>
          ))}
        </div>
        <span className="hint">{t("net.cmp.hint")}</span>
      </fieldset>
      <div className="row wrap" style={{ gap: 12, justifyContent: "space-between" }}>
        <Segmented value={period} onChange={(x) => setPeriod(x as typeof period)} label={t("net.cmp.period")} options={[{ value: "horizon", label: t("net.fin.horizon") }, { value: "year", label: t("net.cmp.year") }, { value: "next3", label: t("net.cmp.next3") }]} testId="sop-cmp-period" />
        <span className="small muted">{t("net.fin.currency", { c: ccy })}</span>
      </div>
      <MfgError error={cmp.error} onRetry={cmp.reload} />
      {!c ? (
        ids.length ? <Spinner /> : null
      ) : (
        <>
          <div className="net-kpis">
            {c.items.slice(1).map((e) => {
              const d = e.delta?.[period];
              return (
                <div className="card net-kpi" key={e.scenario.id} data-testid="sop-cmp-card">
                  <span className="net-kpi-label">
                    <span className="mono">{e.scenario.number}</span> {e.scenario.name}
                  </span>
                  <span className="small">
                    {t("net.kpi.gm")} <Delta v={d?.gross_margin} better="up" kind="money" ccy={ccy} />
                  </span>
                  <span className="small">
                    {t("net.kpi.service")} <Delta v={d?.service_pct} better="up" kind="pts" />
                  </span>
                  <span className="small">
                    {t("net.kpi.capex")} <Delta v={d?.capex} better="down" kind="money" ccy={ccy} />
                  </span>
                </div>
              );
            })}
          </div>
          <section className="card card-table">
            <div className="pl-pivot-wrap">
              <table className="pl-pivot sop-compare" aria-label={t("net.cmp.aria")} data-testid="sop-compare-table">
                <thead>
                  <tr>
                    <th scope="col">{t("net.cmp.kpi")}</th>
                    {c.items.map((e, i) => (
                      <th key={e.scenario.id} scope="col" style={{ textAlign: "right" }}>
                        <span className="mono">{e.scenario.number}</span> {e.scenario.name}
                        {i === 0 ? <span className="badge info" style={{ marginLeft: 6 }}>{t("net.cmp.base")}</span> : null}
                        {e.scenario.id === cycle.recommended_scenario_id ? (
                          <span className="badge accent" style={{ marginLeft: 6 }}>
                            <Icon name="star" /> {t("net.cyc.recommended")}
                          </span>
                        ) : null}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {KROWS.map((k) => (
                    <tr key={k.k}>
                      <th scope="row">{t(k.label)}</th>
                      {c.items.map((e, i) => (
                        <td key={e.scenario.id}>
                          <span className="pl-num">{value(k, e.kpis?.[period][k.k] as number | null | undefined)}</span>
                          {i > 0 ? <Delta v={e.delta?.[period][k.k] as number | null | undefined} better={k.better} kind={k.kind === "money" ? "money" : k.kind === "pct" ? "pts" : "num"} ccy={ccy} /> : null}
                        </td>
                      ))}
                    </tr>
                  ))}
                  <tr>
                    <th scope="row">{t("net.cmp.maxUtil")}</th>
                    {c.items.map((e) => {
                      const mx = Math.max(0, ...(e.kpis?.utilisation ?? []).map((u) => u.max_pct));
                      return (
                        <td key={e.scenario.id} className={heatClass(mx / 100)}>
                          <HeatValue u={e.kpis?.utilisation.length ? mx / 100 : null} />
                        </td>
                      );
                    })}
                  </tr>
                  {domestic.map((code) => (
                    <tr key={code}>
                      <th scope="row">{t("net.cmp.domestic", { m: code })}</th>
                      {c.items.map((e) => {
                        const d = e.kpis?.domestic.find((x) => x.code === code);
                        return (
                          <td key={e.scenario.id}>
                            <span className="pl-num">{d?.share_pct === null || d?.share_pct === undefined ? "–" : `${formatNumber(d.share_pct, 1)} %`}</span>
                            {d?.first_missed_month ? <span className="small net-delta bad"><Icon name="alert" size={12} /> {t("net.cmp.missedFrom", { m: monthLabel(d.first_missed_month) })}</span> : d ? <span className="small net-delta good"><Icon name="check" size={12} /> {t("net.trd.status.met")}</span> : null}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  {canRecommend ? (
                    <tr>
                      <th scope="row">{t("net.cmp.recommend")}</th>
                      {c.items.map((e) => {
                        const s = scenarios.find((x) => x.id === e.scenario.id);
                        return (
                          <td key={e.scenario.id}>
                            <button type="button" className="btn sm" disabled={!s || e.scenario.id === cycle.recommended_scenario_id || e.scenario.validator_ok === false} onClick={() => s && setRec(s)} data-testid="sop-recommend">
                              <Icon name="star" /> {t("net.cmp.recommendBtn")}
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
      {rec ? <RecommendDialog cycle={cycle} scenario={rec} onClose={() => setRec(null)} onDone={() => (setRec(null), onChanged())} /> : null}
    </div>
  );
}

function domesticCodes(kpis: (SopKpis | null)[]): string[] {
  return [...new Set(kpis.flatMap((k) => (k?.domestic ?? []).map((d) => d.code)))];
}

function RecommendDialog({ cycle, scenario, onClose, onDone }: { cycle: SopCycle; scenario: SopScenario; onClose(): void; onDone(): void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  return (
    <Dialog
      title={t("net.cmp.dlgTitle", { n: scenario.number })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !note.trim()}
            onClick={() => {
              setBusy(true);
              recommendScenario(cycle, scenario.id, note.trim())
                .then(() => {
                  toast(t("net.cmp.toast", { n: scenario.number }));
                  onDone();
                })
                .catch((e: unknown) => setErr(e))
                .finally(() => setBusy(false));
            }}
            data-testid="sop-recommend-go"
          >
            <Icon name="star" /> {t("net.cmp.recommendBtn")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{t("net.cmp.dlgBody")}</p>
        <div className="field">
          <label htmlFor="rec-note">
            {t("net.cmp.note")} <span className="req" aria-hidden />
          </label>
          <textarea id="rec-note" className="textarea" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} data-testid="sop-recommend-note" />
        </div>
      </div>
    </Dialog>
  );
}

