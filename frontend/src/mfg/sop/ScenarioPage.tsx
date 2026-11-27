/**
 * `/mfg/sop/scenarios/:scenarioId` (M9 7, 10): a scenario's change list (one form per change kind: new line with
 * ramp-up and yield curve, new node, capacity change, sourcing shares, make or buy, supplier split, demand change,
 * cost/tariff/FX), the capex note, its KPIs once run, and the make-or-buy report. Ramp-up and yield are edited as
 * week points with a chart; the `STD26` template fills the usual curve. Structural changes are never applied to the
 * plants automatically - they become follow-ups when the cycle is published.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DateInput } from "../../components/DateInput";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { toast } from "../../components/Toast";
import { UnsavedChangesGuard } from "../../components/UnsavedChangesGuard";
import { useWidth } from "../../finance/charts/scales";
import { plural, t } from "../../lib/i18n";
import { formatDateTime, formatMoney, formatNumber } from "../../lib/locale";
import { deleteScenario, getCycle, getMakeBuy, getRampCurves, getScenario, putRampCurves, runScenario, updateScenario } from "../api/clientM9";
import { SCENARIO_CHANGE_KINDS, type RampCurve, type RampPoint, type ScenarioChange, type ScenarioChangeKind, type ShareRow, type SopMakeBuyRow, type SopScenario } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { usePolling } from "../lib/usePolling";
import { useLoad } from "../lib/useMfg";
import { useChangeReason } from "../qa/ChangeReason";
import { codeText9, KpiCard, NodeTag, num, pct, pct100, Segmented, useNodes } from "../network/shared";
import { ScenarioChip } from "./SopSupplyTabs";

type Nodes = ReturnType<typeof useNodes>;
/** `STD26` (M9 6.4): week, rate %, yield %. */
export const STD26: RampPoint[] = [
  { week: 0, rate_pct: 25, yield_pct: 85 },
  { week: 4, rate_pct: 50, yield_pct: 90 },
  { week: 8, rate_pct: 75, yield_pct: 94 },
  { week: 13, rate_pct: 90, yield_pct: 97 },
  { week: 26, rate_pct: 100, yield_pct: 98 },
];

let seq = 0;
const newId = () => `chg${Date.now().toString(36)}${(seq++).toString(36)}`;
function blank(kind: ScenarioChangeKind): ScenarioChange {
  const base = { id: newId(), label: "", note: "" };
  const today = new Date().toISOString().slice(0, 8) + "01";
  switch (kind) {
    case "add_line":
      return { ...base, kind, node: "", cap_group: "", name: "", start: today, hours_per_week: 120, hpu_by_family: null, uph_by_family: {}, oee: 0.85, curve: "STD26", points: null, capex: null, capex_currency: "USD", fixed_cost_per_month: null };
    case "add_node":
      return { ...base, kind, code: "", name: "", node_kind: "dc", country: "", currency: "USD", start: today, lanes: [] };
    case "capacity_change":
      return { ...base, kind, node: "", cap_group: "", from: today, to: null, pct: 20 };
    case "sourcing":
      return { ...base, kind, dest_node: "", family: "", sources: [{ source_node: "", min_share: 0, max_share: 1 }] };
    case "make_vs_buy":
      return { ...base, kind, node: "", family: "", option: "both", supplier: { code: "", unit_price: 0, currency: "USD", coo: null, hts_code: null, freight_per_unit: null, cap_per_month: null } };
    case "supplier_allocation":
      return { ...base, kind, node: "", family: "", suppliers: [{ code: "", min_share: 0.6, max_share: 0.6 }, { code: "", min_share: 0.4, max_share: 0.4 }] };
    case "demand_change":
      return { ...base, kind, node: null, family: null, from: today, to: null, pct: 10 };
    default:
      return { ...base, kind: "cost_change", tariff: null, fx: { from: "CAD", to: "USD", rate: 0.72, from_month: today }, freight: null };
  }
}

export function ScenarioPage() {
  const { scenarioId = "" } = useParams();
  const navigate = useNavigate();
  const canEdit = useCan("sop_edit");
  const nodes = useNodes();
  const sc = useLoad((s) => getScenario(scenarioId, s), [scenarioId]);
  const s = sc.data;
  const cycle = useLoad((sig) => (s?.cycle_id ? getCycle(s.cycle_id, sig) : null), [s?.cycle_id]);
  const curves = useLoad((sig) => getRampCurves(sig), []);
  usePolling(sc.reload, s?.status === "running");
  const [name, setName] = useState("");
  const [changes, setChanges] = useState<ScenarioChange[]>([]);
  const [capex, setCapex] = useState("");
  const [enforce, setEnforce] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [addKind, setAddKind] = useState<ScenarioChangeKind>("add_line");
  const [tab, setTab] = useState<"changes" | "makebuy">("changes");
  const [del, setDel] = useState(false);
  const [library, setLibrary] = useState(false);
  useEffect(() => {
    if (s && !dirty) {
      setName(s.name);
      setChanges(s.changes);
      setCapex(s.capex_note);
      setEnforce(Boolean(s.enforce_milestones));
    }
  }, [s, dirty]);
  useEffect(() => {
    if (s) document.title = `${s.number} - ${t("net.scn.title")}`;
  }, [s]);
  if (sc.error && !s) return <MfgError error={sc.error} onRetry={sc.reload} />;
  if (!s) return <Spinner />;
  const frozen = Boolean(cycle.data && (cycle.data.signatures.some((x) => x.status === "valid") || ["approved", "published", "cancelled"].includes(cycle.data.status)));
  const editable = canEdit && !frozen && s.status !== "running";
  const edit = (fn: (c: ScenarioChange[]) => ScenarioChange[]) => {
    setChanges(fn);
    setDirty(true);
  };
  const save = async (): Promise<SopScenario | null> => {
    setBusy(true);
    setErr(null);
    try {
      const x = await updateScenario(s, { name: name.trim() || s.name, changes, capex_note: capex, enforce_milestones: enforce });
      sc.setData(x);
      setDirty(false);
      toast(t("net.scn.toast.saved", { n: x.number }));
      return x;
    } catch (e) {
      setErr(e);
      return null;
    } finally {
      setBusy(false);
    }
  };
  const run = async () => {
    const x = dirty ? await save() : s;
    if (!x) return;
    setErr(null);
    try {
      sc.setData(await runScenario(x.id));
      toast(t("net.scn.toast.running", { n: x.number }));
    } catch (e) {
      setErr(e);
    }
  };
  const k = s.kpis?.horizon;
  const ccy = s.kpis?.currency ?? cycle.data?.report_currency ?? "USD";
  const nodeCodes = [...nodes.nodes.map((n) => n.code), ...changes.filter((c) => c.kind === "add_node").map((c) => (c as Extract<ScenarioChange, { kind: "add_node" }>).code).filter(Boolean)];
  return (
    <div className="col gap-lg net-page" data-testid="scenario-page" data-status={s.status}>
      <div className="mfg-breadcrumb small muted">
        <Link to={mfgPaths.sop()}>{t("net.sop.title")}</Link> <Icon name="chevron-right" size={12} />
        {cycle.data ? (
          <>
            <Link to={mfgPaths.sopCycle(cycle.data.id, "supply")} className="mono">
              {cycle.data.number}
            </Link>{" "}
            <Icon name="chevron-right" size={12} />{" "}
          </>
        ) : null}
        <span className="mono">{s.number}</span>
      </div>
      <PageHeader
        title={t("net.scn.tpl.title", { n: s.number, name: s.name })}
        meta={
          <>
            <ScenarioChip s={s} />
            {s.baseline ? <span className="badge info">{t("net.scn.baseline")}</span> : null}
          </>
        }
        facts={[
          [t("net.scn.head.changes"), formatNumber(changes.length)],
          [t("net.scn.head.runAt"), s.run_at ? formatDateTime(s.run_at) : "–"],
          [t("net.cyc.fact.currency"), ccy],
        ]}
        actions={
          <>
            <button type="button" className="btn" disabled={!editable || s.baseline} onClick={() => setDel(true)}>
              <Icon name="trash" /> {t("net.scn.btn.delete")}
            </button>
            <button type="button" className="btn" disabled={!editable || !dirty || busy} onClick={() => void save()} data-testid="scn-save">
              <Icon name="save" /> {t("net.btn.save")}
            </button>
            <button type="button" className="btn primary" disabled={!canEdit || frozen || s.status === "running" || busy} title={canEdit ? undefined : needsText("sop_edit")} onClick={() => void run()} data-testid="scn-run">
              <Icon name="play" /> {dirty ? t("net.scn.btn.saveRun") : t("net.scn.btn.run")}
            </button>
          </>
        }
      />
      <MfgError error={err} />
      {frozen ? <Banner tone="info" icon="lock">{t("net.scn.frozen")}</Banner> : null}
      {s.status === "running" ? (
        <Banner tone="accent" icon="loader" role="status">
          {t("net.scn.text.running")}
        </Banner>
      ) : null}
      {s.status === "failed" ? (
        <Banner tone="danger" role="alert" title={t("net.scn.text.failed")}>
          {s.error ? codeText9(s.error) : ""}
        </Banner>
      ) : null}
      {s.validator && !s.validator.ok ? (
        <Banner tone="danger" icon="shield" role="alert" title={t("net.scn.text.invalid", { n: plural(s.validator.violations.length, t("plan.noun.problem"), t("plan.noun.problems")) })}>
          <ul className="pl-bullets">
            {s.validator.violations.slice(0, 6).map((v, i) => (
              <li key={i}>
                <span className="mono small">{v.code}</span> {typeof v.detail === "string" ? v.detail : JSON.stringify(v.detail)}
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {k ? (
        <div className="net-kpis" data-testid="scn-kpis">
          <KpiCard label={t("net.kpi.service")} value={pct100(k.service_pct)} sub={t("net.tpl.unmet", { n: num(k.unmet_units) })} />
          <KpiCard label={t("net.kpi.revenue")} value={formatMoney(k.revenue, ccy, { compact: true })} unit={ccy} />
          <KpiCard label={t("net.kpi.gm")} value={formatMoney(k.gross_margin, ccy, { compact: true })} unit={ccy} sub={t("net.tpl.gmPct", { v: pct100(k.gm_pct) })} />
          <KpiCard label={t("net.kpi.inventory")} value={formatMoney(k.inventory_value, ccy, { compact: true })} unit={ccy} />
          <KpiCard label={t("net.kpi.capex")} value={formatMoney(k.capex, ccy, { compact: true })} unit={ccy} />
        </div>
      ) : null}
      {s.warnings.length ? (
        <p className="pl-note" style={{ margin: 0 }}>
          <Icon name="alert" size={14} /> {s.warnings.map((w) => codeText9(w.code)).join(" · ")}
        </p>
      ) : null}
      <div className="row wrap" style={{ gap: 12 }}>
        <div className="field">
          <label htmlFor="scn-name-e">{t("net.scn.label.name")}</label>
          <input id="scn-name-e" className="input" style={{ width: 320 }} maxLength={120} value={name} disabled={!editable} onChange={(e) => (setName(e.target.value), setDirty(true))} />
        </div>
        <label className="row small" style={{ gap: 6, alignSelf: "flex-end" }}>
          <input type="checkbox" checked={enforce} disabled={!editable} onChange={(e) => (setEnforce(e.target.checked), setDirty(true))} /> {t("net.scn.label.enforce")}
        </label>
      </div>
      <nav className="tabs" aria-label={t("net.scn.aria.tabs")}>
        {(["changes", "makebuy"] as const).map((x) => (
          <button key={x} type="button" className={`tab${tab === x ? " active" : ""}`} aria-current={tab === x ? "page" : undefined} onClick={() => setTab(x)} data-testid={`scn-tab-${x}`}>
            {x === "changes" ? t("net.scn.tab.changes") : t("net.scn.tab.makebuy")}
          </button>
        ))}
      </nav>
      {tab === "changes" ? (
        <div className="col pl-gap" data-testid="scn-changes">
          {changes.length === 0 ? <p className="muted card">{s.baseline ? t("net.scn.baselineEmpty") : t("net.scn.noChanges")}</p> : null}
          {changes.map((c, i) => (
            <ChangeCard
              key={c.id}
              c={c}
              index={i}
              editable={editable}
              nodeCodes={nodeCodes}
              curves={curves.data?.items ?? []}
              onChange={(x) => edit((all) => all.map((y) => (y.id === c.id ? x : y)))}
              onRemove={() => edit((all) => all.filter((y) => y.id !== c.id))}
            />
          ))}
          {editable ? (
            <div className="row wrap card" style={{ gap: 8 }}>
              <label htmlFor="scn-add-kind" className="small muted">
                {t("net.scn.label.addKind")}
              </label>
              <select id="scn-add-kind" className="select sm" value={addKind} onChange={(e) => setAddKind(e.target.value as ScenarioChangeKind)} data-testid="scn-add-kind">
                {SCENARIO_CHANGE_KINDS.map((x) => (
                  <option key={x} value={x}>
                    {t(`net.chg.kind.${x}` as const)}
                  </option>
                ))}
              </select>
              <button type="button" className="btn sm" onClick={() => edit((all) => [...all, blank(addKind)])} data-testid="scn-add">
                <Icon name="plus" /> {t("net.scn.btn.add")}
              </button>
              <span className="muted small">{t(`net.chg.help.${addKind}` as const)}</span>
              <span style={{ flex: 1 }} />
              <button type="button" className="btn ghost sm" onClick={() => setLibrary(true)}>
                <Icon name="chart" /> {t("net.curve.library")}
              </button>
            </div>
          ) : null}
          <div className="field">
            <label htmlFor="scn-capex">{t("net.scn.label.capexNote")}</label>
            <textarea id="scn-capex" className="textarea" rows={3} maxLength={2000} value={capex} disabled={!editable} onChange={(e) => (setCapex(e.target.value), setDirty(true))} />
            <span className="hint">{t("net.scn.hint.capexNote")}</span>
          </div>
        </div>
      ) : (
        <MakeBuyReport scenario={s} nodes={nodes} />
      )}
      {del ? (
        <ConfirmDialog
          title={t("net.scn.dlg.deleteTitle", { n: s.number })}
          confirmLabel={t("net.scn.btn.delete")}
          danger
          onCancel={() => setDel(false)}
          onConfirm={() => {
            deleteScenario(s)
              .then(() => navigate(s.cycle_id ? mfgPaths.sopCycle(s.cycle_id, "supply") : mfgPaths.sop()))
              .catch((e: unknown) => (setErr(e), setDel(false)));
          }}
        >
          <p style={{ margin: 0 }}>{t("net.scn.dlg.deleteBody")}</p>
        </ConfirmDialog>
      ) : null}
      {library ? <CurveLibrary curves={curves.data?.items ?? []} onClose={() => setLibrary(false)} onSaved={() => (setLibrary(false), curves.reload())} /> : null}
      <UnsavedChangesGuard when={dirty} what={t("net.scn.what", { n: s.number })} />
    </div>
  );
}

// ---------------------------------------------------------------- change cards
function F({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}

function NodePick({ id, value, onChange, codes, allowAll, disabled }: { id: string; value: string | null; onChange(v: string | null): void; codes: string[]; allowAll?: boolean; disabled?: boolean }) {
  return (
    <select id={id} className="select sm" value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{allowAll ? t("net.label.allNodes") : t("net.label.choose")}</option>
      {codes.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  );
}

const numOr = (v: string, d: number | null = null) => (v === "" ? d : Number(v));

function ChangeCard({ c, index, editable, nodeCodes, curves, onChange, onRemove }: { c: ScenarioChange; index: number; editable: boolean; nodeCodes: string[]; curves: RampCurve[]; onChange(c: ScenarioChange): void; onRemove(): void }) {
  const p = `chg-${index}`;
  const set = <K extends string>(k: K, v: unknown) => onChange({ ...c, [k]: v } as ScenarioChange);
  const dis = !editable;
  let body: ReactNode = null;
  if (c.kind === "add_line") {
    const map = c.uph_by_family ?? c.hpu_by_family ?? {};
    const useUph = c.hpu_by_family === null;
    body = (
      <>
        <div className="row wrap" style={{ gap: 12 }}>
          <F id={`${p}-node`} label={t("net.label.node")}>
            <NodePick id={`${p}-node`} value={c.node} onChange={(v) => set("node", v ?? "")} codes={nodeCodes} disabled={dis} />
          </F>
          <F id={`${p}-cg`} label={t("net.chg.capGroup")}>
            <input id={`${p}-cg`} className="input sm mono" value={c.cap_group} disabled={dis} onChange={(e) => set("cap_group", e.target.value)} />
          </F>
          <F id={`${p}-name`} label={t("net.chg.lineName")}>
            <input id={`${p}-name`} className="input sm" value={c.name} disabled={dis} onChange={(e) => set("name", e.target.value)} />
          </F>
          <F id={`${p}-start`} label={t("net.chg.start")}>
            <DateInput id={`${p}-start`} small value={c.start} disabled={dis} onChange={(v) => set("start", v)} />
          </F>
          <F id={`${p}-hpw`} label={t("net.chg.hoursPerWeek")}>
            <input id={`${p}-hpw`} className="input sm pl-w-140" type="number" min={1} max={168} value={c.hours_per_week} disabled={dis} onChange={(e) => set("hours_per_week", Number(e.target.value))} />
          </F>
        </div>
        <FamilyRates label={useUph ? t("net.chg.uph") : t("net.chg.hpu")} map={map} disabled={dis} onChange={(m) => onChange({ ...c, ...(useUph ? { uph_by_family: m } : { hpu_by_family: m }) })} />
        <div className="row wrap" style={{ gap: 12 }}>
          {useUph ? (
            <F id={`${p}-oee`} label={t("net.chg.oee")}>
              <input id={`${p}-oee`} className="input sm pl-w-140" type="number" min={1} max={100} value={c.oee === null ? "" : Math.round(c.oee * 100)} disabled={dis} onChange={(e) => set("oee", numOr(e.target.value) === null ? null : Number(e.target.value) / 100)} />
            </F>
          ) : null}
          <F id={`${p}-capex`} label={t("net.chg.capex")}>
            <input id={`${p}-capex`} className="input sm pl-w-140" type="number" min={0} value={c.capex ?? ""} disabled={dis} onChange={(e) => set("capex", numOr(e.target.value))} />
          </F>
          <F id={`${p}-ccy`} label={t("net.label.currency")}>
            <input id={`${p}-ccy`} className="input sm mono" style={{ width: 70 }} maxLength={3} value={c.capex_currency ?? ""} disabled={dis} onChange={(e) => set("capex_currency", e.target.value.toUpperCase() || null)} />
          </F>
          <F id={`${p}-fix`} label={t("net.chg.fixedCost")}>
            <input id={`${p}-fix`} className="input sm pl-w-140" type="number" min={0} value={c.fixed_cost_per_month ?? ""} disabled={dis} onChange={(e) => set("fixed_cost_per_month", numOr(e.target.value))} />
          </F>
        </div>
        <CurveField c={c} curves={curves} disabled={dis} onChange={onChange} idp={p} />
      </>
    );
  } else if (c.kind === "add_node") {
    body = (
      <div className="row wrap" style={{ gap: 12 }}>
        <F id={`${p}-code`} label={t("net.chg.code")}>
          <input id={`${p}-code`} className="input sm mono" style={{ width: 100 }} value={c.code} disabled={dis} onChange={(e) => set("code", e.target.value.toUpperCase())} />
        </F>
        <F id={`${p}-name`} label={t("net.scn.label.name")}>
          <input id={`${p}-name`} className="input sm" value={c.name} disabled={dis} onChange={(e) => set("name", e.target.value)} />
        </F>
        <F id={`${p}-kind`} label={t("net.chg.nodeKind")}>
          <select id={`${p}-kind`} className="select sm" value={c.node_kind} disabled={dis} onChange={(e) => set("node_kind", e.target.value)}>
            <option value="plant">{t("net.kind.plant")}</option>
            <option value="dc">{t("net.kind.dc")}</option>
          </select>
        </F>
        <F id={`${p}-cty`} label={t("net.chg.country")}>
          <input id={`${p}-cty`} className="input sm mono" style={{ width: 60 }} maxLength={2} value={c.country} disabled={dis} onChange={(e) => set("country", e.target.value.toUpperCase())} />
        </F>
        <F id={`${p}-ccy`} label={t("net.label.currency")}>
          <input id={`${p}-ccy`} className="input sm mono" style={{ width: 70 }} maxLength={3} value={c.currency} disabled={dis} onChange={(e) => set("currency", e.target.value.toUpperCase())} />
        </F>
        <F id={`${p}-start`} label={t("net.chg.start")}>
          <DateInput id={`${p}-start`} small value={c.start} disabled={dis} onChange={(v) => set("start", v)} />
        </F>
        <LaneRows c={c} codes={nodeCodes} disabled={dis} onChange={onChange} />
      </div>
    );
  } else if (c.kind === "capacity_change") {
    body = (
      <div className="row wrap" style={{ gap: 12 }}>
        <F id={`${p}-node`} label={t("net.label.node")}>
          <NodePick id={`${p}-node`} value={c.node} onChange={(v) => set("node", v ?? "")} codes={nodeCodes} disabled={dis} />
        </F>
        <F id={`${p}-cg`} label={t("net.chg.capGroup")}>
          <input id={`${p}-cg`} className="input sm mono" value={c.cap_group} disabled={dis} onChange={(e) => set("cap_group", e.target.value)} />
        </F>
        <F id={`${p}-from`} label={t("net.dem.from")}>
          <DateInput id={`${p}-from`} small value={c.from} disabled={dis} onChange={(v) => set("from", v)} />
        </F>
        <F id={`${p}-to`} label={t("net.dem.to")}>
          <DateInput id={`${p}-to`} small value={c.to ?? ""} disabled={dis} onChange={(v) => set("to", v || null)} />
        </F>
        <F id={`${p}-pct`} label={t("net.chg.pct")} hint={t("net.chg.hint.capPct")}>
          <input id={`${p}-pct`} className="input sm pl-w-140" type="number" min={-100} max={1000} value={c.pct} disabled={dis} onChange={(e) => set("pct", Number(e.target.value))} />
        </F>
      </div>
    );
  } else if (c.kind === "sourcing" || c.kind === "supplier_allocation") {
    const isSrc = c.kind === "sourcing";
    const rows: ShareRow[] = isSrc ? c.sources : c.suppliers;
    const setRows = (r: ShareRow[]) => onChange(isSrc ? { ...c, sources: r } : { ...c, suppliers: r });
    body = (
      <>
        <div className="row wrap" style={{ gap: 12 }}>
          <F id={`${p}-node`} label={isSrc ? t("net.src.dest") : t("net.label.node")}>
            <NodePick id={`${p}-node`} value={isSrc ? c.dest_node : c.node} onChange={(v) => set(isSrc ? "dest_node" : "node", v ?? "")} codes={nodeCodes} disabled={dis} />
          </F>
          <F id={`${p}-fam`} label={t("net.label.family")}>
            <input id={`${p}-fam`} className="input sm mono" value={c.family} disabled={dis} onChange={(e) => set("family", e.target.value)} />
          </F>
        </div>
        <ShareTable rows={rows} kind={isSrc ? "sourcing" : "supplier"} codes={nodeCodes} disabled={dis} onChange={setRows} />
      </>
    );
  } else if (c.kind === "make_vs_buy") {
    const sup = c.supplier ?? { code: "", unit_price: 0, currency: "USD", coo: null, hts_code: null, freight_per_unit: null, cap_per_month: null };
    const setSup = (k: keyof typeof sup, v: unknown) => onChange({ ...c, supplier: { ...sup, [k]: v } });
    body = (
      <>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          <F id={`${p}-node`} label={t("net.label.node")}>
            <NodePick id={`${p}-node`} value={c.node} onChange={(v) => set("node", v ?? "")} codes={nodeCodes} disabled={dis} />
          </F>
          <F id={`${p}-fam`} label={t("net.label.family")}>
            <input id={`${p}-fam`} className="input sm mono" value={c.family} disabled={dis} onChange={(e) => set("family", e.target.value)} />
          </F>
          <Segmented value={c.option} onChange={(v) => set("option", v)} label={t("net.chg.option")} options={[{ value: "make", label: t("net.chg.optMake") }, { value: "buy", label: t("net.chg.optBuy") }, { value: "both", label: t("net.chg.optBoth") }]} />
        </div>
        {c.option !== "make" ? (
          <div className="row wrap" style={{ gap: 12 }}>
            <F id={`${p}-sc`} label={t("net.src.supplier")}>
              <input id={`${p}-sc`} className="input sm mono" value={sup.code} disabled={dis} onChange={(e) => setSup("code", e.target.value)} />
            </F>
            <F id={`${p}-up`} label={t("net.chg.unitPrice")}>
              <input id={`${p}-up`} className="input sm pl-w-140" type="number" min={0} step="0.0001" value={sup.unit_price} disabled={dis} onChange={(e) => setSup("unit_price", Number(e.target.value))} />
            </F>
            <F id={`${p}-uc`} label={t("net.label.currency")}>
              <input id={`${p}-uc`} className="input sm mono" style={{ width: 70 }} maxLength={3} value={sup.currency} disabled={dis} onChange={(e) => setSup("currency", e.target.value.toUpperCase())} />
            </F>
            <F id={`${p}-coo`} label={t("net.chg.coo")}>
              <input id={`${p}-coo`} className="input sm mono" style={{ width: 60 }} maxLength={2} value={sup.coo ?? ""} disabled={dis} onChange={(e) => setSup("coo", e.target.value.toUpperCase() || null)} />
            </F>
            <F id={`${p}-hts`} label={t("net.chg.hts")}>
              <input id={`${p}-hts`} className="input sm mono" style={{ width: 120 }} maxLength={10} value={sup.hts_code ?? ""} disabled={dis} onChange={(e) => setSup("hts_code", e.target.value.replace(/\D/g, "") || null)} />
            </F>
            <F id={`${p}-fr`} label={t("net.lane.fpu")}>
              <input id={`${p}-fr`} className="input sm pl-w-140" type="number" min={0} step="0.0001" value={sup.freight_per_unit ?? ""} disabled={dis} onChange={(e) => setSup("freight_per_unit", numOr(e.target.value))} />
            </F>
            <F id={`${p}-cap`} label={t("net.chg.capPerMonth")}>
              <input id={`${p}-cap`} className="input sm pl-w-140" type="number" min={0} value={sup.cap_per_month ?? ""} disabled={dis} onChange={(e) => setSup("cap_per_month", numOr(e.target.value))} />
            </F>
          </div>
        ) : null}
      </>
    );
  } else if (c.kind === "demand_change") {
    body = (
      <div className="row wrap" style={{ gap: 12 }}>
        <F id={`${p}-node`} label={t("net.label.node")}>
          <NodePick id={`${p}-node`} value={c.node} onChange={(v) => set("node", v)} codes={nodeCodes} allowAll disabled={dis} />
        </F>
        <F id={`${p}-fam`} label={t("net.label.family")} hint={t("net.chg.hint.allFamilies")}>
          <input id={`${p}-fam`} className="input sm mono" value={c.family ?? ""} disabled={dis} onChange={(e) => set("family", e.target.value || null)} />
        </F>
        <F id={`${p}-from`} label={t("net.dem.from")}>
          <DateInput id={`${p}-from`} small value={c.from} disabled={dis} onChange={(v) => set("from", v)} />
        </F>
        <F id={`${p}-to`} label={t("net.dem.to")}>
          <DateInput id={`${p}-to`} small value={c.to ?? ""} disabled={dis} onChange={(v) => set("to", v || null)} />
        </F>
        <F id={`${p}-pct`} label={t("net.chg.pct")}>
          <input id={`${p}-pct`} className="input sm pl-w-140" type="number" min={-100} max={1000} value={c.pct} disabled={dis} onChange={(e) => set("pct", Number(e.target.value))} />
        </F>
      </div>
    );
  } else {
    const fx = c.fx;
    body = (
      <div className="col pl-gap">
        <Segmented
          value={c.fx ? "fx" : c.freight ? "freight" : "tariff"}
          onChange={(v) => onChange({ ...c, fx: v === "fx" ? fx ?? { from: "CAD", to: "USD", rate: 0.72, from_month: new Date().toISOString().slice(0, 8) + "01" } : null, freight: v === "freight" ? { lane: "", pct: 10 } : null, tariff: v === "tariff" ? c.tariff ?? [] : null })}
          label={t("net.chg.costKind")}
          options={[{ value: "fx", label: t("net.chg.fx") }, { value: "freight", label: t("net.chg.freight") }, { value: "tariff", label: t("net.chg.tariff") }]}
        />
        {fx ? (
          <div className="row wrap" style={{ gap: 12 }}>
            <F id={`${p}-fxf`} label={t("net.chg.fxFrom")}>
              <input id={`${p}-fxf`} className="input sm mono" style={{ width: 70 }} maxLength={3} value={fx.from} disabled={dis} onChange={(e) => onChange({ ...c, fx: { ...fx, from: e.target.value.toUpperCase() } })} />
            </F>
            <F id={`${p}-fxt`} label={t("net.chg.fxTo")}>
              <input id={`${p}-fxt`} className="input sm mono" style={{ width: 70 }} maxLength={3} value={fx.to} disabled={dis} onChange={(e) => onChange({ ...c, fx: { ...fx, to: e.target.value.toUpperCase() } })} />
            </F>
            <F id={`${p}-fxr`} label={t("net.chg.fxRate")} hint={t("net.chg.hint.fxRate", { f: fx.from, t: fx.to })}>
              <input id={`${p}-fxr`} className="input sm pl-w-140" type="number" min={0} step="0.0001" value={fx.rate} disabled={dis} onChange={(e) => onChange({ ...c, fx: { ...fx, rate: Number(e.target.value) } })} />
            </F>
            <F id={`${p}-fxm`} label={t("net.chg.fromMonth")}>
              <DateInput id={`${p}-fxm`} small value={fx.from_month} disabled={dis} onChange={(v) => onChange({ ...c, fx: { ...fx, from_month: v } })} />
            </F>
          </div>
        ) : c.freight ? (
          <div className="row wrap" style={{ gap: 12 }}>
            <F id={`${p}-fl`} label={t("net.src.lane")} hint={t("net.chg.hint.laneId")}>
              <input id={`${p}-fl`} className="input sm mono" value={c.freight.lane} disabled={dis} onChange={(e) => onChange({ ...c, freight: { ...c.freight!, lane: e.target.value } })} />
            </F>
            <F id={`${p}-fp`} label={t("net.chg.pct")}>
              <input id={`${p}-fp`} className="input sm pl-w-140" type="number" value={c.freight.pct} disabled={dis} onChange={(e) => onChange({ ...c, freight: { ...c.freight!, pct: Number(e.target.value) } })} />
            </F>
          </div>
        ) : (
          <p className="small muted" style={{ margin: 0 }}>
            {t("net.chg.tariffHint", { n: plural(c.tariff?.length ?? 0, t("net.noun.tariff"), t("net.noun.tariffs")) })}
          </p>
        )}
      </div>
    );
  }
  return (
    <section className="card col pl-gap" aria-label={t(`net.chg.kind.${c.kind}` as const)} data-testid="scn-change" data-kind={c.kind}>
      <div className="pl-card-header">
        <span className="row" style={{ gap: 8 }}>
          <span className="badge info">{t(`net.chg.kind.${c.kind}` as const)}</span>
          <input className="input sm" style={{ width: 320 }} aria-label={t("net.chg.label")} placeholder={t("net.chg.labelPh")} value={c.label} disabled={dis} onChange={(e) => set("label", e.target.value)} />
        </span>
        {editable ? (
          <button type="button" className="btn ghost sm" onClick={onRemove} aria-label={t("net.chg.remove")}>
            <Icon name="trash" /> {t("net.dem.remove")}
          </button>
        ) : null}
      </div>
      {body}
      <input className="input sm" aria-label={t("net.label.note")} placeholder={t("net.chg.notePh")} value={c.note} disabled={dis} onChange={(e) => set("note", e.target.value)} />
    </section>
  );
}

function FamilyRates({ label, map, disabled, onChange }: { label: string; map: Record<string, number>; disabled: boolean; onChange(m: Record<string, number>): void }) {
  const entries = Object.entries(map);
  const [fam, setFam] = useState("");
  return (
    <fieldset className="pl-fieldset">
      <legend>{label}</legend>
      <div className="row wrap" style={{ gap: 8 }}>
        {entries.map(([f, v]) => (
          <span key={f} className="row" style={{ gap: 4 }}>
            <span className="mono small">{f}</span>
            <input className="input sm" style={{ width: 90 }} type="number" min={0} aria-label={t("net.chg.rateFor", { f })} value={v} disabled={disabled} onChange={(e) => onChange({ ...map, [f]: Number(e.target.value) })} />
            {disabled ? null : (
              <button type="button" className="btn ghost sm icon" aria-label={t("net.chg.removeFam", { f })} onClick={() => onChange(Object.fromEntries(entries.filter(([k]) => k !== f)))}>
                <Icon name="x" />
              </button>
            )}
          </span>
        ))}
        {disabled ? null : (
          <span className="row" style={{ gap: 4 }}>
            <input className="input sm mono" style={{ width: 90 }} aria-label={t("net.label.family")} placeholder={t("net.label.family")} value={fam} onChange={(e) => setFam(e.target.value)} />
            <button type="button" className="btn sm" disabled={!fam.trim()} onClick={() => (onChange({ ...map, [fam.trim()]: 0 }), setFam(""))}>
              <Icon name="plus" /> {t("net.chg.addFam")}
            </button>
          </span>
        )}
      </div>
    </fieldset>
  );
}

function ShareTable({ rows, kind, codes, disabled, onChange }: { rows: ShareRow[]; kind: "sourcing" | "supplier"; codes: string[]; disabled: boolean; onChange(r: ShareRow[]): void }) {
  const upd = (i: number, patch: Partial<ShareRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const minSum = rows.reduce((a, r) => a + r.min_share, 0);
  return (
    <div className="col" style={{ gap: 4 }}>
      <table className="pl-pivot" style={{ minWidth: 0 }}>
        <thead>
          <tr>
            <th scope="col">{kind === "sourcing" ? t("net.src.source") : t("net.src.supplier")}</th>
            <th scope="col">{t("net.chg.minShare")}</th>
            <th scope="col">{t("net.chg.maxShare")}</th>
            {kind === "supplier" ? <th scope="col">{t("net.chg.capPerMonth")}</th> : null}
            <th scope="col">
              <span className="sr-only">{t("plan.label.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <th scope="row">
                {kind === "sourcing" ? (
                  <span className="row" style={{ gap: 4 }}>
                    <select className="select sm" aria-label={t("net.src.source")} value={r.source_node ?? ""} disabled={disabled} onChange={(e) => upd(i, { source_node: e.target.value || null, supplier_code: e.target.value ? null : r.supplier_code })}>
                      <option value="">{t("net.chg.orSupplier")}</option>
                      {codes.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                    {!r.source_node ? <input className="input sm mono" style={{ width: 90 }} aria-label={t("net.src.supplier")} value={r.supplier_code ?? ""} disabled={disabled} onChange={(e) => upd(i, { supplier_code: e.target.value || null })} /> : null}
                  </span>
                ) : (
                  <input className="input sm mono" style={{ width: 110 }} aria-label={t("net.src.supplier")} value={r.code ?? ""} disabled={disabled} onChange={(e) => upd(i, { code: e.target.value || null })} />
                )}
              </th>
              {(["min_share", "max_share"] as const).map((k) => (
                <td key={k}>
                  <input className="input sm" style={{ width: 80 }} type="number" min={0} max={100} aria-label={k === "min_share" ? t("net.chg.minShare") : t("net.chg.maxShare")} value={Math.round(r[k] * 1000) / 10} disabled={disabled} onChange={(e) => upd(i, { [k]: Number(e.target.value) / 100 })} />
                </td>
              ))}
              {kind === "supplier" ? (
                <td>
                  <input className="input sm" style={{ width: 110 }} type="number" min={0} aria-label={t("net.chg.capPerMonth")} value={r.cap_per_month ?? ""} disabled={disabled} onChange={(e) => upd(i, { cap_per_month: numOr(e.target.value) })} />
                </td>
              ) : null}
              <td>
                {disabled ? null : (
                  <button type="button" className="btn ghost sm icon" aria-label={t("net.chg.removeRow")} onClick={() => onChange(rows.filter((_, j) => j !== i))}>
                    <Icon name="x" />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ gap: 8 }}>
        {disabled ? null : (
          <button type="button" className="btn sm" onClick={() => onChange([...rows, kind === "sourcing" ? { source_node: "", min_share: 0, max_share: 1 } : { code: "", min_share: 0, max_share: 1 }])}>
            <Icon name="plus" /> {t("net.chg.addRow")}
          </button>
        )}
        <span className="small muted">{t("net.chg.shareHint")}</span>
        {minSum > 1.0001 ? (
          <span className="badge danger">
            <Icon name="alert" /> {t("net.chg.minTooHigh")}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function LaneRows({ c, codes, disabled, onChange }: { c: Extract<ScenarioChange, { kind: "add_node" }>; codes: string[]; disabled: boolean; onChange(c: ScenarioChange): void }) {
  const upd = (i: number, patch: Partial<(typeof c.lanes)[number]>) => onChange({ ...c, lanes: c.lanes.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  return (
    <fieldset className="pl-fieldset" style={{ flexBasis: "100%" }}>
      <legend>{t("net.lane.title")}</legend>
      {c.lanes.map((l, i) => (
        <div key={i} className="row wrap" style={{ gap: 6 }}>
          <select className="select sm" aria-label={t("net.chg.direction")} value={l.from ? "from" : "to"} disabled={disabled} onChange={(e) => upd(i, e.target.value === "from" ? { from: l.to ?? l.from, to: null } : { to: l.from ?? l.to, from: null })}>
            <option value="from">{t("net.chg.laneFrom")}</option>
            <option value="to">{t("net.chg.laneTo")}</option>
          </select>
          <select className="select sm" aria-label={t("net.label.node")} value={l.from ?? l.to ?? ""} disabled={disabled} onChange={(e) => upd(i, l.from !== null ? { from: e.target.value } : { to: e.target.value })}>
            <option value="">{t("net.label.choose")}</option>
            {codes.filter((x) => x !== c.code).map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
          <input className="input sm" style={{ width: 70 }} type="number" min={0} aria-label={t("net.lane.transit")} value={l.transit_days} disabled={disabled} onChange={(e) => upd(i, { transit_days: Number(e.target.value) })} />
          <span className="small muted">{t("net.chg.days")}</span>
          <input className="input sm" style={{ width: 90 }} type="number" min={0} step="0.001" aria-label={t("net.lane.fpu")} value={l.freight_per_unit} disabled={disabled} onChange={(e) => upd(i, { freight_per_unit: Number(e.target.value) })} />
          {disabled ? null : (
            <button type="button" className="btn ghost sm icon" aria-label={t("net.chg.removeRow")} onClick={() => onChange({ ...c, lanes: c.lanes.filter((_, j) => j !== i) })}>
              <Icon name="x" />
            </button>
          )}
        </div>
      ))}
      {disabled ? null : (
        <button type="button" className="btn sm" onClick={() => onChange({ ...c, lanes: [...c.lanes, { from: "", to: null, mode: "road", transit_days: 2, freight_per_unit: 0 }] })}>
          <Icon name="plus" /> {t("net.lane.btn.new")}
        </button>
      )}
    </fieldset>
  );
}

// ---------------------------------------------------------------- ramp-up and yield curves
function CurveField({ c, curves, disabled, onChange, idp }: { c: Extract<ScenarioChange, { kind: "add_line" }>; curves: RampCurve[]; disabled: boolean; onChange(c: ScenarioChange): void; idp: string }) {
  const custom = c.points !== null;
  const pts = custom ? c.points! : curves.find((x) => x.code === c.curve)?.points ?? (c.curve === "STD26" ? STD26 : []);
  return (
    <fieldset className="pl-fieldset">
      <legend>{t("net.curve.title")}</legend>
      <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
        <F id={`${idp}-curve`} label={t("net.curve.use")}>
          <select id={`${idp}-curve`} className="select sm" value={custom ? "" : c.curve ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value ? { ...c, curve: e.target.value, points: null } : { ...c, curve: null, points: pts.length ? pts : STD26 })} data-testid="scn-curve">
            {(curves.some((x) => x.code === "STD26") ? curves : [{ code: "STD26", name: t("net.curve.std26"), points: STD26 }, ...curves]).map((x) => (
              <option key={x.code} value={x.code}>
                {x.code} · {x.name}
              </option>
            ))}
            <option value="">{t("net.curve.custom")}</option>
          </select>
        </F>
      </div>
      <div className="pl-two">
        {custom ? <CurveEditor points={c.points!} disabled={disabled} onChange={(p) => onChange({ ...c, points: p })} /> : <CurveTable points={pts} />}
        <CurveChart points={pts} />
      </div>
    </fieldset>
  );
}

function CurveTable({ points }: { points: RampPoint[] }) {
  return (
    <table className="pl-pivot" style={{ minWidth: 0 }} aria-label={t("net.curve.title")}>
      <thead>
        <tr>
          <th scope="col">{t("net.curve.week")}</th>
          <th scope="col">{t("net.curve.rate")}</th>
          <th scope="col">{t("net.curve.yield")}</th>
          <th scope="col">{t("net.curve.effective")}</th>
        </tr>
      </thead>
      <tbody>
        {points.map((p) => (
          <tr key={p.week}>
            <th scope="row">{p.week}</th>
            <td>{formatNumber(p.rate_pct, 1)} %</td>
            <td>{formatNumber(p.yield_pct, 1)} %</td>
            <td>{formatNumber((p.rate_pct * p.yield_pct) / 100, 1)} %</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function CurveEditor({ points, disabled, onChange }: { points: RampPoint[]; disabled?: boolean; onChange(p: RampPoint[]): void }) {
  const upd = (i: number, patch: Partial<RampPoint>) => onChange(points.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  const ascending = points.every((p, i) => i === 0 || p.week > points[i - 1].week);
  const inRange = points.every((p) => p.rate_pct >= 0 && p.rate_pct <= 100 && p.yield_pct >= 0 && p.yield_pct <= 100);
  return (
    <div className="col net-curve-pts" style={{ gap: 4 }} data-testid="curve-editor">
      <table className="pl-pivot" style={{ minWidth: 0 }} aria-label={t("net.curve.title")}>
        <thead>
          <tr>
            <th scope="col">{t("net.curve.week")}</th>
            <th scope="col">{t("net.curve.rate")}</th>
            <th scope="col">{t("net.curve.yield")}</th>
            <th scope="col">
              <span className="sr-only">{t("plan.label.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {points.map((p, i) => (
            <tr key={i}>
              {(["week", "rate_pct", "yield_pct"] as const).map((k) => (
                <td key={k} style={{ textAlign: "left" }}>
                  <input className="input sm" type="number" min={0} max={k === "week" ? 260 : 100} aria-label={t(k === "week" ? "net.curve.week" : k === "rate_pct" ? "net.curve.rate" : "net.curve.yield")} value={p[k]} disabled={disabled} onChange={(e) => upd(i, { [k]: Number(e.target.value) })} />
                </td>
              ))}
              <td>
                {disabled ? null : (
                  <button type="button" className="btn ghost sm icon" aria-label={t("net.chg.removeRow")} onClick={() => onChange(points.filter((_, j) => j !== i))}>
                    <Icon name="x" />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {disabled ? null : (
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn sm" onClick={() => onChange([...points, { week: (points[points.length - 1]?.week ?? -4) + 4, rate_pct: 100, yield_pct: 98 }])}>
            <Icon name="plus" /> {t("net.curve.addPoint")}
          </button>
          <button type="button" className="btn ghost sm" onClick={() => onChange(STD26)} data-testid="curve-std26">
            {t("net.curve.useStd26")}
          </button>
        </div>
      )}
      {!ascending ? <span className="badge danger"><Icon name="alert" /> {t("net.curve.notAscending")}</span> : null}
      {!inRange ? <span className="badge danger"><Icon name="alert" /> {t("net.curve.outOfRange")}</span> : null}
    </div>
  );
}

/** Rate, yield and effective output (rate x yield) by week since start; the last point is held. */
export function CurveChart({ points }: { points: RampPoint[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const h = 170;
  const M = { l: 36, r: 10, t: 8, b: 22 };
  const maxW = Math.max(26, ...points.map((p) => p.week)) + 4;
  const x = (w: number) => M.l + (w / maxW) * Math.max(10, width - M.l - M.r);
  const y = (v: number) => M.t + (1 - v / 100) * (h - M.t - M.b);
  const line = (f: (p: RampPoint) => number) => (points.length ? `M${x(0)},${y(0)} ` + points.map((p) => `L${x(p.week)},${y(f(p))}`).join(" ") + ` L${x(maxW)},${y(f(points[points.length - 1]))}` : "");
  const lines = [
    { k: "rate", label: t("net.curve.rate"), color: "var(--pl-c1)", f: (p: RampPoint) => p.rate_pct, dash: undefined },
    { k: "yield", label: t("net.curve.yield"), color: "var(--pl-c2)", f: (p: RampPoint) => p.yield_pct, dash: "4 3" },
    { k: "eff", label: t("net.curve.effective"), color: "var(--pl-c3)", f: (p: RampPoint) => (p.rate_pct * p.yield_pct) / 100, dash: undefined },
  ];
  return (
    <figure className="pl-chart" style={{ margin: 0 }}>
      <div ref={ref} className="pl-chart-area">
        <svg width={width} height={h} role="img" aria-label={t("net.curve.chartAria", { n: points.length })} data-testid="curve-chart">
          {[0, 25, 50, 75, 100].map((v) => (
            <g key={v}>
              <line x1={M.l} x2={width - M.r} y1={y(v)} y2={y(v)} stroke="var(--grid, var(--border))" />
              <text x={M.l - 4} y={y(v) + 4} textAnchor="end" className="pl-axis">
                {v}
              </text>
            </g>
          ))}
          {[0, 4, 8, 13, 26, 39, 52].filter((w) => w <= maxW).map((w) => (
            <text key={w} x={x(w)} y={h - 6} textAnchor="middle" className="pl-axis">
              {t("net.curve.wk", { n: w })}
            </text>
          ))}
          {lines.map((l) => (
            <path key={l.k} d={line(l.f)} fill="none" stroke={l.color} strokeWidth={l.k === "eff" ? 2.5 : 1.5} strokeDasharray={l.dash} />
          ))}
        </svg>
      </div>
      <figcaption className="row wrap small muted" style={{ gap: 12 }}>
        {lines.map((l) => (
          <span key={l.k} className="row" style={{ gap: 4 }}>
            <svg width="16" height="8" aria-hidden>
              <line x1="0" x2="16" y1="4" y2="4" stroke={l.color} strokeWidth="2" strokeDasharray={l.dash} />
            </svg>
            {l.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

function CurveLibrary({ curves, onClose, onSaved }: { curves: RampCurve[]; onClose(): void; onSaved(): void }) {
  const canEdit = useCan("network_edit");
  const reason = useChangeReason();
  const [list, setList] = useState<RampCurve[]>(curves.length ? curves : [{ code: "STD26", name: t("net.curve.std26"), points: STD26 }]);
  const [sel, setSel] = useState(0);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const cur = list[sel];
  const valid = list.every((c) => /^[A-Z0-9_-]{1,16}$/.test(c.code) && c.points.length > 0 && c.points.every((p, i) => i === 0 || p.week > c.points[i - 1].week));
  const save = async () => {
    const why = await reason.ask(t("net.curve.what"));
    if (why === null) return;
    setBusy(true);
    setErr(null);
    try {
      await putRampCurves(list, why);
      toast(t("net.src.toast.saved"));
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("net.curve.library")}
      wide
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!canEdit || !valid || busy} title={canEdit ? undefined : needsText("network_edit")} onClick={() => void save()}>
            <Icon name="save" /> {t("net.btn.save")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p className="small muted" style={{ margin: 0 }}>{t("net.curve.libraryHint")}</p>
        <div className="row wrap" style={{ gap: 6 }}>
          {list.map((c, i) => (
            <button key={i} type="button" className="btn sm" aria-pressed={i === sel} onClick={() => setSel(i)}>
              {c.code || "…"}
            </button>
          ))}
          <button type="button" className="btn ghost sm" disabled={!canEdit} onClick={() => (setList([...list, { code: "", name: "", points: STD26 }]), setSel(list.length))}>
            <Icon name="plus" /> {t("net.curve.new")}
          </button>
        </div>
        {cur ? (
          <>
            <div className="row wrap" style={{ gap: 12 }}>
              <F id="cl-code" label={t("net.chg.code")}>
                <input id="cl-code" className="input sm mono" maxLength={16} value={cur.code} disabled={!canEdit} onChange={(e) => setList(list.map((x, i) => (i === sel ? { ...x, code: e.target.value.toUpperCase() } : x)))} />
              </F>
              <F id="cl-name" label={t("net.scn.label.name")}>
                <input id="cl-name" className="input sm" maxLength={80} value={cur.name} disabled={!canEdit} onChange={(e) => setList(list.map((x, i) => (i === sel ? { ...x, name: e.target.value } : x)))} />
              </F>
            </div>
            <div className="pl-two">
              <CurveEditor points={cur.points} disabled={!canEdit} onChange={(p) => setList(list.map((x, i) => (i === sel ? { ...x, points: p } : x)))} />
              <CurveChart points={cur.points} />
            </div>
          </>
        ) : null}
      </div>
      {reason.dialog}
    </Dialog>
  );
}

// ---------------------------------------------------------------- make or buy
function MakeBuyReport({ scenario, nodes }: { scenario: SopScenario; nodes: Nodes }) {
  const mb = useLoad((s) => (scenario.status === "completed" ? getMakeBuy(scenario.id, s) : null), [scenario.id, scenario.status]);
  const columns = useMemo<Column<SopMakeBuyRow>[]>(
    () => [
      { key: "node", header: t("net.label.node"), width: "100px", sortValue: (r) => nodes.code(String(r.node_owner_id)), render: (r) => <NodeTag node={nodes.byId.get(String(r.node_owner_id))} id={String(r.node_owner_id)} /> },
      { key: "family", header: t("net.label.family"), width: "100px", sortValue: (r) => r.family, render: (r) => <span className="mono">{r.family}</span> },
      { key: "make", header: t("net.mb.makeCost"), width: "120px", align: "right", sortValue: (r) => r.make_unit_cost ?? 0, render: (r) => <span className="pl-num">{formatMoney(r.make_unit_cost, r.currency, { digits: 4 })}</span> },
      {
        key: "buy",
        header: t("net.mb.buyCost"),
        width: "minmax(220px, 1fr)",
        wrap: true,
        render: (r) => (
          <span className="col" style={{ gap: 2 }}>
            {r.buy.map((b) => {
              const cheaper = b.landed_unit_cost !== null && r.make_unit_cost !== null && b.landed_unit_cost < r.make_unit_cost;
              return (
                <span key={b.supplier_code} className="small pl-num">
                  <span className="mono">{b.supplier_code}</span> {b.coo ? `(${b.coo})` : ""} {formatMoney(b.landed_unit_cost, r.currency, { digits: 4 })}
                  {b.duty_share !== null ? ` · ${t("net.mb.dutyShare", { v: pct(b.duty_share) })}` : ""}
                  {cheaper ? <span className="net-delta good"> <Icon name="check" size={12} /> {t("net.mb.cheaper")}</span> : null}
                </span>
              );
            })}
          </span>
        ),
      },
      { key: "split", header: t("net.mb.split"), width: "150px", render: (r) => { const tot = r.split_make + r.split_buy; return <span className="pl-num small">{tot ? t("net.mb.splitTpl", { m: pct(r.split_make / tot, 0), b: pct(r.split_buy / tot, 0) }) : "–"}</span>; } },
      { key: "hours", header: t("net.mb.hoursFreed"), width: "120px", align: "right", sortValue: (r) => r.hours_freed, render: (r) => <span className="pl-num">{t("plan.tpl.hours", { n: num(r.hours_freed) })}</span> },
    ],
    [nodes],
  );
  if (scenario.status !== "completed") return <p className="muted card">{t("net.mb.runFirst")}</p>;
  if (mb.error) return <MfgError error={mb.error} onRetry={mb.reload} />;
  return (
    <section className="card card-table">
      <DataTable<SopMakeBuyRow> rows={mb.data?.items ?? []} columns={columns} rowKey={(r) => `${r.node_owner_id}|${r.family}`} label={t("net.scn.tab.makebuy")} testId="scn-makebuy" loading={!mb.data} exportName="make-or-buy" empty={t("net.mb.empty")} />
    </section>
  );
}
