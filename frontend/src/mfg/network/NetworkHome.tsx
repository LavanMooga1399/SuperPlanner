/**
 * `/mfg/network` (M9 10): the network workspace's home - node/lane diagram (SVG; nodes by kind and country, lanes
 * with mode and transit days), the latest network run's KPIs and shortages, the current S&OP cycle's step, and the
 * run history with "New network run" (guided: horizon and capacity; expert: pre-build, firm zone, as-of date).
 */
import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router";
import { Banner } from "../../components/Banner";
import { DateInput } from "../../components/DateInput";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { toast } from "../../components/Toast";
import { plural, t } from "../../lib/i18n";
import { formatDateTime, formatDay, formatMoney, formatNumber } from "../../lib/locale";
import { createNetRun, getNetShortages, listCycles, listLanes, listNetRuns } from "../api/clientM9";
import type { NetLane, NetNodeInfo, NetRun, SopCycle } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { usePolling } from "../lib/usePolling";
import { useLoad } from "../lib/useMfg";
import { CauseChip, CycleChip, isRunning, JobChip, KpiCard, kindText, NodeTag, num, pct, useNodes, weekShort } from "./shared";
import { StepStrip } from "../sop/SopCyclesPage";

export function NetworkHome() {
  const canRun = useCan("network_plan");
  const navigate = useNavigate();
  const nodes = useNodes();
  const lanes = useLoad((s) => listLanes(s), []);
  const runs = useLoad((s) => listNetRuns({ limit: 30 }, s), []);
  const cycles = useLoad((s) => listCycles({ limit: 3 }, s).catch(() => null), []);
  const anyRunning = (runs.data?.items ?? []).some((r) => isRunning(r.status));
  usePolling(runs.reload, anyRunning);
  const [dialog, setDialog] = useState(false);
  useEffect(() => {
    document.title = t("net.home.title");
  }, []);
  const latest = (runs.data?.items ?? []).find((r) => r.status === "completed") ?? null;
  const published = (runs.data?.items ?? []).find((r) => r.published) ?? null;
  const cycle = (cycles.data?.items ?? []).find((c) => c.status !== "cancelled") ?? null;
  const columns = useMemo<Column<NetRun>[]>(
    () => [
      {
        key: "number",
        header: t("net.run.head.run"),
        width: "170px",
        sortValue: (r) => r.number,
        exportValue: (r) => r.number,
        render: (r) => (
          <span className="row" style={{ gap: 6 }}>
            <Link to={mfgPaths.netRun(r.id)} className="mono" onClick={(e) => e.stopPropagation()} tabIndex={-1}>
              {r.number}
            </Link>
            {r.published ? (
              <span className="badge ok">
                <Icon name="flag" /> {t("net.run.published")}
              </span>
            ) : null}
          </span>
        ),
      },
      { key: "status", header: t("net.run.head.status"), width: "130px", exportValue: (r) => r.status, render: (r) => <JobChip s={r.status} /> },
      { key: "asof", header: t("net.run.head.asOf"), width: "120px", sortValue: (r) => r.as_of, render: (r) => formatDay(r.as_of) },
      { key: "fill", header: t("net.kpi.fill"), width: "100px", align: "right", sortValue: (r) => r.summary?.fill_rate ?? -1, render: (r) => <span className="pl-num">{pct(r.summary?.fill_rate)}</span> },
      { key: "short", header: t("net.kpi.shortUnits"), width: "120px", align: "right", sortValue: (r) => r.summary?.shortage_units ?? 0, render: (r) => <span className="pl-num">{num(r.summary?.shortage_units)}</span> },
      { key: "transfers", header: t("net.kpi.transferUnits"), width: "120px", align: "right", drop: 2, sortValue: (r) => r.summary?.transfer_units ?? 0, render: (r) => <span className="pl-num">{num(r.summary?.transfer_units)}</span> },
      { key: "valid", header: t("net.run.head.validator"), width: "120px", drop: 1, render: (r) => (r.validator ? r.validator.ok ? <span className="badge ok"><Icon name="shield" /> {t("net.run.valid")}</span> : <span className="badge danger"><Icon name="alert" /> {t("net.run.invalid")}</span> : <span className="muted">–</span>) },
      { key: "created", header: t("net.run.head.created"), width: "150px", drop: 3, sortValue: (r) => r.created_at, render: (r) => formatDateTime(r.created_at) },
    ],
    [],
  );
  return (
    <div className="col gap-lg net-page" data-testid="net-home">
      <PageHeader
        title={t("net.home.title")}
        description={t("net.home.desc")}
        facts={[
          [t("net.home.fact.nodes"), formatNumber(nodes.nodes.length)],
          [t("net.home.fact.lanes"), formatNumber((lanes.data?.items ?? []).filter((l) => l.active).length)],
          [t("net.home.fact.published"), published ? published.number : t("net.home.none")],
        ]}
        actions={
          <>
            <Link className="btn" to={mfgPaths.networkSourcing()}>
              <Icon name="truck" /> {t("net.home.btn.sourcing")}
            </Link>
            <button type="button" className="btn primary" disabled={!canRun} title={canRun ? undefined : needsText("network_plan")} onClick={() => setDialog(true)} data-testid="net-run-new">
              <Icon name="play" /> {t("net.run.btn.new")}
            </button>
          </>
        }
      />
      <MfgError error={nodes.error} onRetry={nodes.reload} />
      <MfgError error={runs.error} onRetry={runs.reload} />
      <div className="pl-two">
        <section className="card col pl-gap" aria-labelledby="net-diagram-h">
          <div className="pl-card-header">
            <h2 className="pl-h2" id="net-diagram-h">
              {t("net.home.diagram")}
            </h2>
            <span className="muted small">{t("net.home.diagramHint")}</span>
          </div>
          <NetworkDiagram nodes={nodes.nodes} lanes={lanes.data?.items ?? []} />
        </section>
        <div className="col pl-gap">
          <CycleCard cycle={cycle} />
          <LatestRunCard run={latest} />
        </div>
      </div>
      {latest ? <ShortageCard run={latest} code={nodes.code} byId={nodes.byId} /> : null}
      <section className="card card-table" aria-label={t("net.home.runs")}>
        <DataTable<NetRun>
          rows={runs.data?.items ?? []}
          columns={columns}
          rowKey={(r) => r.id}
          label={t("net.home.runs")}
          testId="net-runs"
          loading={runs.loading && !runs.data}
          onRowClick={(r) => navigate(mfgPaths.netRun(r.id))}
          onActivate={(r) => navigate(mfgPaths.netRun(r.id))}
          rowExtras={(r) => ({ testId: "net-run-row", data: { status: r.status } })}
          exportName="network-runs"
          empty={t("net.home.runsEmpty")}
        />
      </section>
      {dialog ? <NewNetRunDialog onClose={() => setDialog(false)} onStarted={(r) => navigate(mfgPaths.netRun(r.id))} /> : null}
    </div>
  );
}

function CycleCard({ cycle }: { cycle: SopCycle | null }) {
  return (
    <section className="card col pl-gap" aria-labelledby="net-cycle-h" data-testid="net-cycle-card">
      <div className="pl-card-header">
        <h2 className="pl-h2" id="net-cycle-h">
          {t("net.home.cycle")}
        </h2>
        {cycle ? <CycleChip s={cycle.status} /> : null}
      </div>
      {cycle ? (
        <>
          <Link to={mfgPaths.sopCycle(cycle.id)} className="mono">
            {cycle.number}
          </Link>
          <StepStrip cycle={cycle} />
        </>
      ) : (
        <p className="muted small" style={{ margin: 0 }}>
          {t("net.home.noCycle")} <Link to={mfgPaths.sop()}>{t("net.nav.sop")}</Link>
        </p>
      )}
    </section>
  );
}

function LatestRunCard({ run }: { run: NetRun | null }) {
  const s = run?.summary;
  return (
    <section className="col pl-gap" aria-label={t("net.home.latest")} data-testid="net-latest">
      <div className="pl-card-header">
        <h2 className="pl-h2">{t("net.home.latest")}</h2>
        {run ? (
          <Link to={mfgPaths.netRun(run.id)} className="mono small">
            {run.number}
          </Link>
        ) : null}
      </div>
      {s ? (
        <div className="net-kpis">
          <KpiCard label={t("net.kpi.fill")} value={pct(s.fill_rate)} testId="kpi-fill" />
          <KpiCard label={t("net.kpi.shortUnits")} value={num(s.shortage_units)} unit={t("net.unit.units")} sub={plural(s.shortages, t("net.noun.shortage"), t("net.noun.shortages"))} />
          <KpiCard label={t("net.kpi.inventory")} value={formatMoney(s.inventory_value, s.currency, { compact: true })} unit={s.currency} />
          <KpiCard label={t("net.kpi.transferUnits")} value={num(s.transfer_units)} unit={t("net.unit.units")} sub={t("net.tpl.firmOf", { n: formatNumber(s.firm_transfers), m: formatNumber(s.transfers) })} />
        </div>
      ) : (
        <p className="muted small card" style={{ margin: 0 }}>
          {t("net.home.noRun")}
        </p>
      )}
    </section>
  );
}

function ShortageCard({ run, code, byId }: { run: NetRun; code(id: string): string; byId: Map<string, NetNodeInfo> }) {
  const sh = useLoad((s) => getNetShortages(run.id, s), [run.id]);
  const items = sh.data?.items ?? [];
  if (!items.length) return null;
  return (
    <section className="card col pl-gap" aria-labelledby="net-short-h" data-testid="net-home-shortages">
      <div className="pl-card-header">
        <h2 className="pl-h2" id="net-short-h">
          {t("net.home.shortages", { n: plural(items.length, t("net.noun.shortage"), t("net.noun.shortages")) })}
        </h2>
        <Link to={mfgPaths.netRun(run.id, "shortages")} className="small">
          {t("net.home.allShortages")}
        </Link>
      </div>
      <ul className="pl-bullets">
        {items.slice(0, 6).map((x) => (
          <li key={x.id} className="row wrap" style={{ gap: 8 }}>
            <NodeTag node={byId.get(x.node_owner_id)} id={code(x.node_owner_id)} />
            <span className="mono">{x.item_key}</span>
            <span className="muted">{weekShort(x.week)}</span>
            <span className="pl-num">{t("net.tpl.qtyUom", { q: num(x.qty), u: x.uom })}</span>
            <CauseChip cause={x.cause} />
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------- diagram
const NW = 150;
const NH = 46;
const COL = 230;
const ROW = 86;

/** Node/lane diagram: one column per country, plants above DCs; arrows carry mode and transit days. */
export function NetworkDiagram({ nodes, lanes }: { nodes: NetNodeInfo[]; lanes: NetLane[] }) {
  const [sel, setSel] = useState<string | null>(null);
  const layout = useMemo(() => {
    const countries = [...new Set(nodes.map((n) => n.country ?? "–"))].sort();
    const pos = new Map<string, { x: number; y: number }>();
    let rows = 1;
    countries.forEach((c, ci) => {
      const list = nodes.filter((n) => (n.country ?? "–") === c).sort((a, b) => (a.kind === b.kind ? a.code.localeCompare(b.code) : a.kind === "plant" ? -1 : 1));
      list.forEach((n, i) => pos.set(n.owner_id, { x: 20 + ci * COL, y: 34 + i * ROW }));
      rows = Math.max(rows, list.length);
    });
    return { countries, pos, w: Math.max(320, countries.length * COL), h: 34 + rows * ROW };
  }, [nodes]);
  if (!nodes.length) return <p className="muted small">{t("net.home.noNodes")}</p>;
  const active = lanes.filter((l) => l.active);
  const onKey = (e: KeyboardEvent<SVGGElement>, id: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setSel((s) => (s === id ? null : id));
    }
  };
  const selNode = nodes.find((n) => n.owner_id === sel);
  return (
    <div className="col pl-gap">
      <div className="net-diagram">
        <svg width={layout.w} height={layout.h} role="group" aria-label={t("net.home.diagramAria", { n: plural(nodes.length, t("net.noun.node"), t("net.noun.nodes")), l: plural(active.length, t("net.noun.lane"), t("net.noun.lanes")) })} data-testid="net-diagram">
          <defs>
            <marker id="net-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" className="net-arrow" />
            </marker>
          </defs>
          {layout.countries.map((c, i) => (
            <text key={c} x={20 + i * COL} y={18} className="net-lane-label" style={{ fontWeight: 600 }}>
              {c}
            </text>
          ))}
          {active.map((l) => {
            const a = layout.pos.get(l.from_owner_id);
            const b = layout.pos.get(l.to_owner_id);
            if (!a || !b) return null;
            const ax = a.x + NW / 2;
            const ay = a.y + NH / 2;
            const bx = b.x + NW / 2;
            const by = b.y + NH / 2;
            // start/end on the box edge facing the other node; a bend keeps opposite lanes apart
            const dx = bx - ax;
            const dy = by - ay;
            const sx = Math.abs(dx) > Math.abs(dy) ? ax + Math.sign(dx) * (NW / 2) : ax;
            const sy = Math.abs(dx) > Math.abs(dy) ? ay : ay + Math.sign(dy) * (NH / 2);
            const ex = Math.abs(dx) > Math.abs(dy) ? bx - Math.sign(dx) * (NW / 2) : bx;
            const ey = Math.abs(dx) > Math.abs(dy) ? by : by - Math.sign(dy) * (NH / 2);
            const len = Math.hypot(ex - sx, ey - sy) || 1;
            const bend = Math.abs(dx) < 1 ? 46 : 16;
            const mx = (sx + ex) / 2 + (-(ey - sy) / len) * bend;
            const my = (sy + ey) / 2 + ((ex - sx) / len) * bend;
            const dim = sel && sel !== l.from_owner_id && sel !== l.to_owner_id;
            return (
              <g key={l.id} opacity={dim ? 0.25 : 1} data-testid="net-lane">
                <path d={`M${sx},${sy} Q${mx},${my} ${ex},${ey}`} className="net-lane" markerEnd="url(#net-arrow)" />
                <text x={mx} y={my} textAnchor="middle" className="net-lane-label">
                  {t("net.tpl.laneLabel", { d: l.transit_days, m: modeText(l.mode) })}
                </text>
                <title>{t("net.tpl.laneTitle", { m: modeText(l.mode), d: l.transit_days, f: formatMoney(l.freight_per_unit, l.currency, { digits: 3 }) })}</title>
              </g>
            );
          })}
          {nodes.map((n) => {
            const p = layout.pos.get(n.owner_id)!;
            return (
              <g
                key={n.owner_id}
                className={`net-node ${n.kind}${sel === n.owner_id ? " sel" : ""}`}
                transform={`translate(${p.x},${p.y})`}
                tabIndex={0}
                role="button"
                aria-pressed={sel === n.owner_id}
                aria-label={t("net.tpl.nodeTitle", { name: n.name, kind: kindText(n.kind), country: n.country ?? "–", ccy: n.currency })}
                onClick={() => setSel((s) => (s === n.owner_id ? null : n.owner_id))}
                onKeyDown={(e) => onKey(e, n.owner_id)}
                data-testid={`net-node-${n.code}`}
              >
                <rect width={NW} height={NH} rx={6} />
                <text x={10} y={19} style={{ fontWeight: 600 }}>
                  {n.code}
                </text>
                <text x={10} y={36} className="sub">
                  {t("net.tpl.nodeSub", { kind: kindText(n.kind), ccy: n.currency })}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      {selNode ? (
        <p className="small" style={{ margin: 0 }} data-testid="net-node-detail">
          <strong>{selNode.name}</strong> · {kindText(selNode.kind)} · {selNode.country ?? "–"} · {selNode.currency} · {selNode.tz}
          {selNode.kind === "plant" ? ` · ${plural(selNode.lines, t("noun.line"), t("noun.lines"))}` : ""}
          {selNode.member ? null : <span className="muted"> · {t("net.home.notMember")}</span>}
        </p>
      ) : null}
    </div>
  );
}

export const modeText = (m: string) => (m === "rail" ? t("net.mode.rail") : m === "sea" ? t("net.mode.sea") : m === "air" ? t("net.mode.air") : t("net.mode.road"));

// ---------------------------------------------------------------- new run
export function NewNetRunDialog({ onClose, onStarted }: { onClose(): void; onStarted(r: NetRun): void }) {
  const [horizon, setHorizon] = useState("26");
  const [constrained, setConstrained] = useState(true);
  const [expert, setExpert] = useState(false);
  const [prebuild, setPrebuild] = useState("4");
  const [firm, setFirm] = useState("14");
  const [asOf, setAsOf] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const h = Number(horizon);
  const valid = h >= 4 && h <= 52 && Number(prebuild) >= 0 && Number(prebuild) <= 12 && Number(firm) >= 0 && Number(firm) <= 60;
  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await createNetRun({ label, horizon_weeks: h, constrained, ...(expert ? { prebuild_weeks: Number(prebuild), firm_days: Number(firm), as_of: asOf || null } : {}) });
      toast(t("net.run.toast.started", { n: r.number }));
      onStarted(r);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("net.run.dlg.newTitle")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!valid || busy} onClick={() => void start()} data-testid="net-run-start">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />} {t("net.run.btn.start")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{t("net.run.dlg.newBody")}</p>
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="nr-horizon">{t("net.run.label.horizon")}</label>
            <input id="nr-horizon" className="input pl-w-140" type="number" min={4} max={52} value={horizon} onChange={(e) => setHorizon(e.target.value)} aria-invalid={!valid} />
            <span className="hint">{t("net.run.hint.horizon")}</span>
          </div>
          <div className="field">
            <label htmlFor="nr-label">{t("net.run.label.label")}</label>
            <input id="nr-label" className="input" maxLength={100} value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
        </div>
        <fieldset className="pl-choice">
          <legend className="small muted">{t("net.run.label.capacity")}</legend>
          {[true, false].map((v) => (
            <label key={String(v)} className={`pl-choice-opt${constrained === v ? " on" : ""}`}>
              <input type="radio" name="nr-cap" checked={constrained === v} onChange={() => setConstrained(v)} />
              <span>
                <strong>{v ? t("net.run.cap.on") : t("net.run.cap.off")}</strong>
                <span className="muted small">{v ? t("net.run.cap.onHelp") : t("net.run.cap.offHelp")}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <button type="button" className="btn ghost sm pl-expert-toggle" aria-expanded={expert} onClick={() => setExpert((v) => !v)}>
          <Icon name={expert ? "chevron-down" : "chevron-right"} /> {t("plan.label.expert")}
        </button>
        {expert ? (
          <div className="pl-expert row wrap" style={{ gap: 12 }}>
            <div className="field">
              <label htmlFor="nr-prebuild">{t("net.run.label.prebuild")}</label>
              <input id="nr-prebuild" className="input pl-w-140" type="number" min={0} max={12} value={prebuild} onChange={(e) => setPrebuild(e.target.value)} />
              <span className="hint">{t("net.run.hint.prebuild")}</span>
            </div>
            <div className="field">
              <label htmlFor="nr-firm">{t("net.run.label.firm")}</label>
              <input id="nr-firm" className="input pl-w-140" type="number" min={0} max={60} value={firm} onChange={(e) => setFirm(e.target.value)} />
              <span className="hint">{t("net.run.hint.firm")}</span>
            </div>
            <div className="field">
              <label htmlFor="nr-asof">{t("net.run.label.asOf")}</label>
              <DateInput id="nr-asof" value={asOf} onChange={setAsOf} />
              <span className="hint">{t("net.run.hint.asOf")}</span>
            </div>
          </div>
        ) : null}
        {!constrained ? <Banner tone="warn">{t("net.run.cap.offWarn")}</Banner> : null}
      </div>
    </Dialog>
  );
}
