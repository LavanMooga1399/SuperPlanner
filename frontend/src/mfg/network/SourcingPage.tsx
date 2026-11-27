/**
 * `/mfg/network/sourcing` (M9 4, 10): sourcing rules by destination and key/family with a quota bar per rule set
 * (quota mode when any rule of the set has a quota; the quotas must add up to 100 %), a resolve tester ("where does
 * DCUS get NDL-21G on 1 Mar?") and the transit lane editor. Edits need `network_edit`; changes carry the Part 11
 * reason.
 */
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DateInput } from "../../components/DateInput";
import { Dialog } from "../../components/Dialog";
import { FilterBar } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { toast } from "../../components/Toast";
import { plural, t } from "../../lib/i18n";
import { formatDateRange, formatMoney, formatNumber } from "../../lib/locale";
import { createLane, createSourcing, deleteLane, deleteSourcing, listLanes, listSourcing, resolveSourcing, updateLane, updateSourcing } from "../api/clientM9";
import { LANE_MODES, type LaneMode, type NetLane, type NetLaneInput, type SourcingResolve, type SourcingRule, type SourcingRuleInput } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { needsText, useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { useChangeReason } from "../qa/ChangeReason";
import { colorOf } from "../forecast/shared";
import { modeText } from "./NetworkHome";
import { NodeTag, num, todayIso, useNodes } from "./shared";

type Nodes = ReturnType<typeof useNodes>;
const setKey = (r: SourcingRule) => `${r.dest_owner_id}|${r.item_key ? `k:${r.item_key}` : `f:${r.family}`}`;

export function SourcingPage() {
  const canEdit = useCan("network_edit");
  const nodes = useNodes();
  const reason = useChangeReason();
  const rules = useLoad((s) => listSourcing({}, s), []);
  const lanes = useLoad((s) => listLanes(s), []);
  const [dest, setDest] = useState("");
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState<SourcingRule | "new" | null>(null);
  const [laneEdit, setLaneEdit] = useState<NetLane | "new" | null>(null);
  const [del, setDel] = useState<{ kind: "rule"; r: SourcingRule } | { kind: "lane"; l: NetLane } | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    document.title = t("net.src.title");
  }, []);
  const all = rules.data?.items ?? [];
  const shown = all.filter((r) => (!dest || r.dest_owner_id === dest) && (!q || `${r.item_key ?? ""} ${r.family ?? ""} ${r.supplier_code ?? ""}`.toLowerCase().includes(q.toLowerCase())));
  const sets = useMemo(() => {
    const m = new Map<string, SourcingRule[]>();
    for (const r of all.filter((x) => x.active)) m.set(setKey(r), [...(m.get(setKey(r)) ?? []), r]);
    return m;
  }, [all]);
  const laneById = useMemo(() => new Map((lanes.data?.items ?? []).map((l) => [l.id, l])), [lanes.data]);
  const sourceText = (r: SourcingRule) => (r.source_kind === "plant" ? nodes.code(r.source_owner_id) : t("net.src.supplierTpl", { s: r.supplier_code ?? "–" }));
  const columns = useMemo<Column<SourcingRule>[]>(
    () => [
      { key: "dest", header: t("net.src.dest"), width: "100px", sortValue: (r) => nodes.code(r.dest_owner_id), exportValue: (r) => nodes.code(r.dest_owner_id), render: (r) => <NodeTag node={nodes.byId.get(r.dest_owner_id)} id={r.dest_owner_id} /> },
      { key: "scope", header: t("net.src.scope"), width: "170px", sortValue: (r) => r.item_key ?? `~${r.family}`, exportValue: (r) => r.item_key ?? r.family, render: (r) => (r.item_key ? <span className="mono">{r.item_key}</span> : <span>{t("net.src.familyTpl", { f: r.family ?? "" })}</span>) },
      { key: "source", header: t("net.src.source"), width: "150px", sortValue: (r) => sourceText(r), exportValue: (r) => sourceText(r), render: (r) => (r.source_kind === "plant" ? <NodeTag node={nodes.byId.get(r.source_owner_id ?? "")} id={r.source_owner_id} /> : <span className="row" style={{ gap: 4 }}><Icon name="briefcase" size={14} />{r.supplier_code}</span>) },
      { key: "prio", header: t("net.src.priority"), width: "80px", align: "right", sortValue: (r) => r.priority, render: (r) => <span className="pl-num">{r.priority}</span> },
      { key: "quota", header: t("net.src.quota"), width: "minmax(200px, 1fr)", sortValue: (r) => r.quota_pct ?? -1, exportValue: (r) => r.quota_pct, render: (r) => <QuotaBar set={sets.get(setKey(r)) ?? [r]} highlight={r.id} label={(x) => (x.source_kind === "plant" ? nodes.code(x.source_owner_id) : x.supplier_code ?? "")} /> },
      { key: "lane", header: t("net.src.lane"), width: "120px", drop: 2, render: (r) => { const l = r.lane_id ? laneById.get(r.lane_id) : null; return l ? t("net.tpl.laneLabel", { d: l.transit_days, m: modeText(l.mode) }) : <span className="muted">{r.source_kind === "plant" ? t("net.src.fastest") : "–"}</span>; } },
      { key: "valid", header: t("net.src.valid"), width: "150px", drop: 3, render: (r) => (r.valid_from || r.valid_to ? formatDateRange(r.valid_from, r.valid_to) || "–" : <span className="muted">{t("net.src.always")}</span>) },
      { key: "active", header: t("net.src.active"), width: "90px", drop: 1, render: (r) => (r.active ? <span className="badge ok"><Icon name="check" /> {t("net.src.on")}</span> : <span className="badge info"><Icon name="ban" /> {t("net.src.off")}</span>) },
      {
        key: "actions",
        header: <span className="sr-only">{t("plan.label.actions")}</span>,
        label: t("plan.label.actions"),
        width: "90px",
        render: (r) => (
          <span className="row" style={{ gap: 2 }}>
            <button type="button" className="btn ghost sm icon" disabled={!canEdit} aria-label={t("net.src.editAria")} title={canEdit ? t("net.src.editAria") : needsText("network_edit")} onClick={(e) => (e.stopPropagation(), setEdit(r))}>
              <Icon name="settings" />
            </button>
            <button type="button" className="btn ghost sm icon" disabled={!canEdit} aria-label={t("net.src.deleteAria")} onClick={(e) => (e.stopPropagation(), setDel({ kind: "rule", r }))}>
              <Icon name="trash" />
            </button>
          </span>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nodes, sets, laneById, canEdit],
  );
  const doDelete = async () => {
    if (!del) return;
    const why = await reason.ask(del.kind === "rule" ? t("net.src.whatRule") : t("net.src.whatLane"));
    if (why === null) return;
    setErr(null);
    try {
      if (del.kind === "rule") await deleteSourcing(del.r, why);
      else await deleteLane(del.l, why);
      toast(t("net.src.toast.deleted"));
      setDel(null);
      rules.reload();
      lanes.reload();
    } catch (e) {
      setErr(e);
      setDel(null);
    }
  };
  const badSets = [...sets.values()].filter((s) => s.some((r) => r.quota_pct !== null) && Math.abs(s.reduce((a, r) => a + (r.quota_pct ?? 0), 0) - 100) > 0.01);
  return (
    <div className="col gap-lg net-page" data-testid="net-sourcing">
      <PageHeader
        title={t("net.src.title")}
        description={t("net.src.desc")}
        facts={[
          [t("net.src.fact.rules"), formatNumber(all.length)],
          [t("net.src.fact.sets"), formatNumber(sets.size)],
          [t("net.home.fact.lanes"), formatNumber(lanes.data?.items.length ?? 0)],
        ]}
        actions={
          <button type="button" className="btn primary" disabled={!canEdit} title={canEdit ? undefined : needsText("network_edit")} onClick={() => setEdit("new")} data-testid="net-rule-new">
            <Icon name="plus" /> {t("net.src.btn.new")}
          </button>
        }
      />
      <MfgError error={err} />
      <MfgError error={rules.error} onRetry={rules.reload} />
      {badSets.length ? (
        <Banner tone="danger" role="alert" title={t("net.src.quotaBad", { n: plural(badSets.length, t("net.noun.ruleSet"), t("net.noun.ruleSets")) })}>
          {t("net.src.quotaBadBody")}
        </Banner>
      ) : null}
      <ResolveTester nodes={nodes} />
      <FilterBar
        search={{ id: "net-src-q", value: q, onChange: setQ, placeholder: t("net.src.searchPh"), testId: "net-src-search" }}
        chips={dest ? [{ key: "dest", label: t("net.src.dest"), value: nodes.code(dest), onClear: () => setDest("") }] : []}
        pageKey="net-sourcing"
      >
        <div className="field">
          <label htmlFor="net-src-dest">{t("net.src.dest")}</label>
          <select id="net-src-dest" className="select sm" value={dest} onChange={(e) => setDest(e.target.value)}>
            <option value="">{t("net.label.allNodes")}</option>
            {nodes.nodes.map((n) => (
              <option key={n.owner_id} value={n.owner_id}>
                {n.code}
              </option>
            ))}
          </select>
        </div>
      </FilterBar>
      <section className="card card-table">
        <DataTable<SourcingRule>
          rows={shown}
          columns={columns}
          rowKey={(r) => r.id}
          label={t("net.src.title")}
          testId="net-rules"
          loading={rules.loading && !rules.data}
          exportName="sourcing-rules"
          empty={t("net.src.empty")}
          rowExtras={() => ({ testId: "net-rule-row" })}
        />
      </section>
      <LanesSection lanes={lanes.data?.items ?? []} loading={lanes.loading && !lanes.data} nodes={nodes} canEdit={canEdit} onEdit={setLaneEdit} onDelete={(l) => setDel({ kind: "lane", l })} />
      {edit ? <RuleDialog rule={edit === "new" ? null : edit} nodes={nodes} lanes={lanes.data?.items ?? []} onClose={() => setEdit(null)} onSaved={() => (setEdit(null), rules.reload())} /> : null}
      {laneEdit ? <LaneDialog lane={laneEdit === "new" ? null : laneEdit} nodes={nodes} onClose={() => setLaneEdit(null)} onSaved={() => (setLaneEdit(null), lanes.reload())} /> : null}
      {del ? (
        <ConfirmDialog title={del.kind === "rule" ? t("net.src.dlg.deleteRule") : t("net.src.dlg.deleteLane")} confirmLabel={t("net.src.btn.delete")} danger onConfirm={() => void doDelete()} onCancel={() => setDel(null)}>
          <p style={{ margin: 0 }}>{del.kind === "rule" ? t("net.src.dlg.deleteRuleBody") : t("net.src.dlg.deleteLaneBody")}</p>
        </ConfirmDialog>
      ) : null}
      {reason.dialog}
    </div>
  );
}

/** Quota bar of one rule set: one segment per source with its share; red frame when the quotas miss 100 %. */
export function QuotaBar({ set, highlight, label }: { set: SourcingRule[]; highlight?: string; label(r: SourcingRule): string }) {
  const quota = set.some((r) => r.quota_pct !== null);
  if (!quota) return <span className="small muted">{t("net.src.priorityMode", { n: set.length })}</span>;
  const sum = set.reduce((a, r) => a + (r.quota_pct ?? 0), 0);
  const ok = Math.abs(sum - 100) <= 0.01;
  return (
    <span className="row" style={{ gap: 6 }}>
      <span className={`net-quota${ok ? "" : " bad"}`} role="img" aria-label={set.map((r) => `${label(r)} ${formatNumber(r.quota_pct ?? 0, 1)} %`).join(", ")} data-testid="net-quota-bar">
        {set.map((r) => (
          <span key={r.id} style={{ width: `${Math.max(0, r.quota_pct ?? 0)}%`, background: colorOf(label(r)), opacity: highlight && highlight !== r.id ? 0.55 : 1 }}>
            {(r.quota_pct ?? 0) >= 18 ? `${label(r)} ${formatNumber(r.quota_pct ?? 0, 0)}%` : ""}
          </span>
        ))}
      </span>
      {ok ? null : (
        <span className="badge danger">
          <Icon name="alert" /> {t("net.src.sumTpl", { v: formatNumber(sum, 1) })}
        </span>
      )}
    </span>
  );
}

function ResolveTester({ nodes }: { nodes: Nodes }) {
  const [dest, setDest] = useState("");
  const [key, setKey] = useState("");
  const [date, setDate] = useState(todayIso());
  const [res, setRes] = useState<SourcingResolve | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const go = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    resolveSourcing({ dest, key, date })
      .then(setRes, setErr)
      .finally(() => setBusy(false));
  };
  return (
    <section className="card col pl-gap" aria-labelledby="net-resolve-h" data-testid="net-resolve">
      <h2 className="pl-h2" id="net-resolve-h">
        {t("net.src.resolve")}
      </h2>
      <form className="row wrap" style={{ gap: 12, alignItems: "flex-end" }} onSubmit={go}>
        <div className="field">
          <label htmlFor="rs-dest">{t("net.src.dest")}</label>
          <select id="rs-dest" className="select sm" value={dest} onChange={(e) => setDest(e.target.value)} required>
            <option value="">{t("net.label.choose")}</option>
            {nodes.nodes.map((n) => (
              <option key={n.owner_id} value={n.owner_id}>
                {n.code}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="rs-key">{t("net.label.key")}</label>
          <input id="rs-key" className="input sm mono" value={key} onChange={(e) => setKey(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="rs-date">{t("net.label.date")}</label>
          <DateInput id="rs-date" small value={date} onChange={setDate} />
        </div>
        <button type="submit" className="btn sm" disabled={!dest || !key || busy} data-testid="net-resolve-go">
          <Icon name="search" /> {t("net.src.btn.resolve")}
        </button>
      </form>
      <MfgError error={err} />
      {res ? (
        <div className="small" data-testid="net-resolve-result" data-mode={res.mode}>
          {res.mode === "none" ? (
            <p style={{ margin: 0 }}>{t("net.src.res.none")}</p>
          ) : (
            <>
              <p style={{ margin: "0 0 4px" }}>{res.mode === "quota" ? t("net.src.res.quota", { by: res.matched_by === "item" ? t("net.src.res.byItem") : t("net.src.res.byFamily") }) : t("net.src.res.priority", { by: res.matched_by === "item" ? t("net.src.res.byItem") : t("net.src.res.byFamily") })}</p>
              <ol className="pl-bullets">
                {res.sources.map((s) => (
                  <li key={s.rule_id}>
                    {s.source_kind === "plant" ? nodes.code(s.source_owner_id) : t("net.src.supplierTpl", { s: s.supplier_code ?? "" })}
                    {s.quota_pct !== null ? ` · ${formatNumber(s.quota_pct, 1)} %` : ` · ${t("net.src.prioTpl", { n: s.priority })}`}
                    {s.transit_days !== null ? ` · ${plural(s.transit_days, t("noun.day"), t("noun.days"))}` : ""}
                  </li>
                ))}
              </ol>
            </>
          )}
          {res.warnings.map((w) => (
            <p key={w} className="pl-note" style={{ margin: 0 }}>
              <Icon name="alert" size={14} /> {w}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function LanesSection({ lanes, loading, nodes, canEdit, onEdit, onDelete }: { lanes: NetLane[]; loading: boolean; nodes: Nodes; canEdit: boolean; onEdit(l: NetLane | "new"): void; onDelete(l: NetLane): void }) {
  const columns = useMemo<Column<NetLane>[]>(
    () => [
      { key: "from", header: t("net.tr.from"), width: "110px", sortValue: (l) => nodes.code(l.from_owner_id), exportValue: (l) => nodes.code(l.from_owner_id), render: (l) => <NodeTag node={nodes.byId.get(l.from_owner_id)} id={l.from_owner_id} /> },
      { key: "to", header: t("net.tr.toNode"), width: "110px", sortValue: (l) => nodes.code(l.to_owner_id), exportValue: (l) => nodes.code(l.to_owner_id), render: (l) => <NodeTag node={nodes.byId.get(l.to_owner_id)} id={l.to_owner_id} /> },
      { key: "mode", header: t("net.lane.mode"), width: "90px", sortValue: (l) => l.mode, render: (l) => modeText(l.mode) },
      { key: "days", header: t("net.lane.transit"), width: "110px", align: "right", sortValue: (l) => l.transit_days, render: (l) => <span className="pl-num">{plural(l.transit_days, t("noun.day"), t("noun.days"))}</span> },
      { key: "fpu", header: t("net.lane.fpu"), width: "130px", align: "right", sortValue: (l) => l.freight_per_unit, exportValue: (l) => l.freight_per_unit, render: (l) => <span className="pl-num">{formatMoney(l.freight_per_unit, l.currency, { digits: 3 })}</span> },
      { key: "fkg", header: t("net.lane.fkg"), width: "120px", align: "right", drop: 1, render: (l) => <span className="pl-num">{l.freight_per_kg === null ? "–" : formatMoney(l.freight_per_kg, l.currency, { digits: 2 })}</span> },
      { key: "active", header: t("net.src.active"), width: "90px", render: (l) => (l.active ? <span className="badge ok"><Icon name="check" /> {t("net.src.on")}</span> : <span className="badge info"><Icon name="ban" /> {t("net.src.off")}</span>) },
      {
        key: "actions",
        header: <span className="sr-only">{t("plan.label.actions")}</span>,
        label: t("plan.label.actions"),
        width: "90px",
        render: (l) => (
          <span className="row" style={{ gap: 2 }}>
            <button type="button" className="btn ghost sm icon" disabled={!canEdit} aria-label={t("net.lane.editAria")} onClick={() => onEdit(l)}>
              <Icon name="settings" />
            </button>
            <button type="button" className="btn ghost sm icon" disabled={!canEdit} aria-label={t("net.lane.deleteAria")} onClick={() => onDelete(l)}>
              <Icon name="trash" />
            </button>
          </span>
        ),
      },
    ],
    [nodes, canEdit, onEdit, onDelete],
  );
  return (
    <section className="card card-table" aria-labelledby="net-lanes-h">
      <div className="pl-card-header" style={{ padding: "8px 12px" }}>
        <h2 className="pl-h2" id="net-lanes-h">
          {t("net.lane.title")}
        </h2>
        <button type="button" className="btn sm" disabled={!canEdit} title={canEdit ? undefined : needsText("network_edit")} onClick={() => onEdit("new")} data-testid="net-lane-new">
          <Icon name="plus" /> {t("net.lane.btn.new")}
        </button>
      </div>
      <DataTable<NetLane> rows={lanes} columns={columns} rowKey={(l) => l.id} label={t("net.lane.title")} testId="net-lanes" loading={loading} exportName="lanes" empty={t("net.lane.empty")} />
    </section>
  );
}

function RuleDialog({ rule, nodes, lanes, onClose, onSaved }: { rule: SourcingRule | null; nodes: Nodes; lanes: NetLane[]; onClose(): void; onSaved(): void }) {
  const reason = useChangeReason();
  const [f, setF] = useState<SourcingRuleInput>(
    rule ?? { dest_owner_id: "", item_key: "", family: null, source_kind: "plant", source_owner_id: null, supplier_code: null, priority: 1, quota_pct: null, lane_id: null, valid_from: null, valid_to: null, active: true },
  );
  const [scope, setScope] = useState<"key" | "family">(rule?.family ? "family" : "key");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const set = <K extends keyof SourcingRuleInput>(k: K, v: SourcingRuleInput[K]) => setF((x) => ({ ...x, [k]: v }));
  const valid = f.dest_owner_id && (scope === "key" ? f.item_key : f.family) && (f.source_kind === "plant" ? f.source_owner_id && f.source_owner_id !== f.dest_owner_id : f.supplier_code) && (f.quota_pct === null || (f.quota_pct >= 0 && f.quota_pct <= 100));
  const save = async () => {
    const body: SourcingRuleInput = { ...f, item_key: scope === "key" ? f.item_key : null, family: scope === "family" ? f.family : null, source_owner_id: f.source_kind === "plant" ? f.source_owner_id : null, supplier_code: f.source_kind === "supplier" ? f.supplier_code : null, lane_id: f.source_kind === "plant" ? f.lane_id : null };
    let why: string | null = null;
    if (rule) {
      why = await reason.ask(t("net.src.whatRule"));
      if (why === null) return;
    }
    setBusy(true);
    setErr(null);
    try {
      if (rule) await updateSourcing(rule, body, why);
      else await createSourcing(body);
      toast(t("net.src.toast.saved"));
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const laneOpts = lanes.filter((l) => l.to_owner_id === f.dest_owner_id && l.from_owner_id === f.source_owner_id);
  return (
    <Dialog
      title={rule ? t("net.src.dlg.edit") : t("net.src.dlg.new")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!valid || busy} onClick={() => void save()} data-testid="net-rule-save">
            <Icon name="save" /> {t("net.btn.save")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="sr-dest">{t("net.src.dest")}</label>
            <select id="sr-dest" className="select" value={f.dest_owner_id} onChange={(e) => set("dest_owner_id", e.target.value)}>
              <option value="">{t("net.label.choose")}</option>
              {nodes.nodes.map((n) => (
                <option key={n.owner_id} value={n.owner_id}>
                  {n.code} · {n.name}
                </option>
              ))}
            </select>
          </div>
          <fieldset className="pl-fieldset">
            <legend>{t("net.src.scope")}</legend>
            <label className="row" style={{ gap: 6 }}>
              <input type="radio" name="sr-scope" checked={scope === "key"} onChange={() => setScope("key")} /> {t("net.src.scopeKey")}
            </label>
            <label className="row" style={{ gap: 6 }}>
              <input type="radio" name="sr-scope" checked={scope === "family"} onChange={() => setScope("family")} /> {t("net.src.scopeFamily")}
            </label>
          </fieldset>
          <div className="field">
            <label htmlFor="sr-scope-v">{scope === "key" ? t("net.label.key") : t("net.label.family")}</label>
            <input id="sr-scope-v" className="input mono" value={(scope === "key" ? f.item_key : f.family) ?? ""} onChange={(e) => set(scope === "key" ? "item_key" : "family", e.target.value)} />
            <span className="hint">{scope === "key" ? t("net.src.hint.key") : t("net.src.hint.family")}</span>
          </div>
        </div>
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="sr-kind">{t("net.src.sourceKind")}</label>
            <select id="sr-kind" className="select" value={f.source_kind} onChange={(e) => set("source_kind", e.target.value as SourcingRuleInput["source_kind"])}>
              <option value="plant">{t("net.src.kindPlant")}</option>
              <option value="supplier">{t("net.src.kindSupplier")}</option>
            </select>
          </div>
          {f.source_kind === "plant" ? (
            <>
              <div className="field">
                <label htmlFor="sr-src">{t("net.src.source")}</label>
                <select id="sr-src" className="select" value={f.source_owner_id ?? ""} onChange={(e) => set("source_owner_id", e.target.value || null)}>
                  <option value="">{t("net.label.choose")}</option>
                  {nodes.nodes
                    .filter((n) => n.owner_id !== f.dest_owner_id)
                    .map((n) => (
                      <option key={n.owner_id} value={n.owner_id}>
                        {n.code} · {n.name}
                      </option>
                    ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="sr-lane">{t("net.src.lane")}</label>
                <select id="sr-lane" className="select" value={f.lane_id ?? ""} onChange={(e) => set("lane_id", e.target.value || null)}>
                  <option value="">{t("net.src.fastest")}</option>
                  {laneOpts.map((l) => (
                    <option key={l.id} value={l.id}>
                      {t("net.tpl.laneLabel", { d: l.transit_days, m: modeText(l.mode) })}
                    </option>
                  ))}
                </select>
              </div>
            </>
          ) : (
            <div className="field">
              <label htmlFor="sr-sup">{t("net.src.supplier")}</label>
              <input id="sr-sup" className="input mono" value={f.supplier_code ?? ""} onChange={(e) => set("supplier_code", e.target.value || null)} />
              <span className="hint">{t("net.src.hint.supplier")}</span>
            </div>
          )}
        </div>
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="sr-prio">{t("net.src.priority")}</label>
            <input id="sr-prio" className="input pl-w-140" type="number" min={1} max={9} value={f.priority} onChange={(e) => set("priority", Number(e.target.value) || 1)} />
            <span className="hint">{t("net.src.hint.priority")}</span>
          </div>
          <div className="field">
            <label htmlFor="sr-quota">{t("net.src.quotaPct")}</label>
            <input id="sr-quota" className="input pl-w-140" type="number" min={0} max={100} step={1} value={f.quota_pct ?? ""} onChange={(e) => set("quota_pct", e.target.value === "" ? null : Number(e.target.value))} />
            <span className="hint">{t("net.src.hint.quota")}</span>
          </div>
          <div className="field">
            <label htmlFor="sr-from">{t("net.src.validFrom")}</label>
            <DateInput id="sr-from" value={f.valid_from ?? ""} onChange={(v) => set("valid_from", v || null)} />
          </div>
          <div className="field">
            <label htmlFor="sr-to">{t("net.src.validTo")}</label>
            <DateInput id="sr-to" value={f.valid_to ?? ""} onChange={(v) => set("valid_to", v || null)} />
          </div>
        </div>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={f.active} onChange={(e) => set("active", e.target.checked)} /> {t("net.src.activeLabel")}
        </label>
      </div>
      {reason.dialog}
    </Dialog>
  );
}

function LaneDialog({ lane, nodes, onClose, onSaved }: { lane: NetLane | null; nodes: Nodes; onClose(): void; onSaved(): void }) {
  const reason = useChangeReason();
  const [f, setF] = useState<NetLaneInput>(lane ?? { from_owner_id: "", to_owner_id: "", mode: "road", transit_days: 2, freight_per_unit: 0, freight_per_kg: null, currency: "USD", active: true });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const set = <K extends keyof NetLaneInput>(k: K, v: NetLaneInput[K]) => setF((x) => ({ ...x, [k]: v }));
  const valid = f.from_owner_id && f.to_owner_id && f.from_owner_id !== f.to_owner_id && f.transit_days >= 0 && /^[A-Z]{3}$/.test(f.currency);
  const save = async () => {
    let why: string | null = null;
    if (lane) {
      why = await reason.ask(t("net.src.whatLane"));
      if (why === null) return;
    }
    setBusy(true);
    setErr(null);
    try {
      if (lane) await updateLane(lane, f, why);
      else await createLane(f);
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
      title={lane ? t("net.lane.dlg.edit") : t("net.lane.dlg.new")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!valid || busy} onClick={() => void save()} data-testid="net-lane-save">
            <Icon name="save" /> {t("net.btn.save")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <div className="row wrap" style={{ gap: 12 }}>
          {(["from_owner_id", "to_owner_id"] as const).map((k) => (
            <div className="field" key={k}>
              <label htmlFor={`ln-${k}`}>{k === "from_owner_id" ? t("net.tr.from") : t("net.tr.toNode")}</label>
              <select id={`ln-${k}`} className="select" value={f[k]} onChange={(e) => set(k, e.target.value)}>
                <option value="">{t("net.label.choose")}</option>
                {nodes.nodes.map((n) => (
                  <option key={n.owner_id} value={n.owner_id}>
                    {n.code} · {n.name}
                  </option>
                ))}
              </select>
            </div>
          ))}
          <div className="field">
            <label htmlFor="ln-mode">{t("net.lane.mode")}</label>
            <select id="ln-mode" className="select" value={f.mode} onChange={(e) => set("mode", e.target.value as LaneMode)}>
              {LANE_MODES.map((m) => (
                <option key={m} value={m}>
                  {modeText(m)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="ln-days">{t("net.lane.transit")}</label>
            <input id="ln-days" className="input pl-w-140" type="number" min={0} max={120} value={f.transit_days} onChange={(e) => set("transit_days", Number(e.target.value))} />
            <span className="hint">{t("net.lane.hint.transit")}</span>
          </div>
          <div className="field">
            <label htmlFor="ln-fpu">{t("net.lane.fpu")}</label>
            <input id="ln-fpu" className="input pl-w-140" type="number" min={0} step="0.001" value={f.freight_per_unit} onChange={(e) => set("freight_per_unit", Number(e.target.value))} />
          </div>
          <div className="field">
            <label htmlFor="ln-fkg">{t("net.lane.fkg")}</label>
            <input id="ln-fkg" className="input pl-w-140" type="number" min={0} step="0.01" value={f.freight_per_kg ?? ""} onChange={(e) => set("freight_per_kg", e.target.value === "" ? null : Number(e.target.value))} />
          </div>
          <div className="field">
            <label htmlFor="ln-ccy">{t("net.label.currency")}</label>
            <input id="ln-ccy" className="input mono" style={{ width: 80 }} maxLength={3} value={f.currency} onChange={(e) => set("currency", e.target.value.toUpperCase())} />
          </div>
        </div>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={f.active} onChange={(e) => set("active", e.target.checked)} /> {t("net.src.activeLabel")}
        </label>
        <p className="small muted" style={{ margin: 0 }}>{t("net.lane.note", { n: num(f.transit_days) })}</p>
      </div>
      {reason.dialog}
    </Dialog>
  );
}
