/**
 * `/mfg/sourcing-risk` (M9 7, 10): supplier risk per item-supplier (score 0-100 from single source, country, lead
 * time, on-time delivery and tariff exposure; flags as text + icon) with dual-sourcing suggestions. "Create scenario"
 * builds a supplier split (60/40) in the network workspace's open S&OP cycle; from a plant it opens the network
 * workspace on this page.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { Dialog } from "../../components/Dialog";
import { FilterBar } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { t } from "../../lib/i18n";
import { formatMoney, formatNumber } from "../../lib/locale";
import { createScenario, getRisk, listCycles } from "../api/clientM9";
import type { RiskRow, RiskSuggestion, SupplierAllocationChange } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { isNetworkWs, useAccess, useCan } from "../lib/permissions";
import { switchWorkspace } from "../lib/workspace";
import { useLoad } from "../lib/useMfg";
import { NodeTag, pct100, Segmented, useNodes } from "../network/shared";

function ScoreBadge({ s }: { s: number }) {
  const tone = s >= 50 ? "danger" : s >= 30 ? "warn" : "ok";
  return (
    <span className={`badge ${tone} pl-num-badge`} data-testid="risk-score" data-tone={tone} title={tone === "danger" ? t("net.risk.high") : tone === "warn" ? t("net.risk.medium") : t("net.risk.low")}>
      <Icon name={tone === "ok" ? "check" : "alert"} />
      {s}
      <span className="sr-only"> {tone === "danger" ? t("net.risk.high") : tone === "warn" ? t("net.risk.medium") : t("net.risk.low")}</span>
    </span>
  );
}

export function SourcingRiskPage() {
  const access = useAccess();
  const isNet = access.isNetwork;
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const nodes = useNodes();
  const [minScore, setMinScore] = useState<"0" | "30" | "50">("30");
  const [q, setQ] = useState(params.get("item") ?? "");
  const [node, setNode] = useState("");
  const risk = useLoad((s) => getRisk({ min_score: Number(minScore), node: node || undefined }, s), [minScore, node]);
  const [create, setCreate] = useState<{ row: RiskRow; sug: RiskSuggestion } | null>(null);
  useEffect(() => {
    document.title = t("net.risk.title");
  }, []);
  const rows = (risk.data?.items ?? []).filter((r) => !q || `${r.part_number} ${r.item_key} ${r.supplier_code} ${r.supplier_name}`.toLowerCase().includes(q.toLowerCase()));
  const netWs = access.workspaces.find((w) => isNetworkWs(w));
  const columns = useMemo<Column<RiskRow>[]>(
    () => [
      { key: "score", header: t("net.risk.score"), width: "80px", align: "right", sortValue: (r) => r.score, exportValue: (r) => r.score, render: (r) => <ScoreBadge s={r.score} /> },
      ...(isNet ? [{ key: "node", header: t("net.label.node"), width: "90px", sortValue: (r: RiskRow) => nodes.code(r.node_owner_id), render: (r: RiskRow) => <NodeTag node={nodes.byId.get(r.node_owner_id)} id={r.node_owner_id} /> } as Column<RiskRow>] : []),
      { key: "item", header: t("net.risk.item"), width: "minmax(200px, 1fr)", sortValue: (r) => r.part_number, exportValue: (r) => r.part_number, render: (r) => <span className="mfg-ellipsis"><span className="mono">{r.part_number}</span> <span className="muted">{r.description}</span></span> },
      { key: "supplier", header: t("net.src.supplier"), width: "170px", sortValue: (r) => r.supplier_code, render: (r) => <span className="mfg-ellipsis"><span className="mono">{r.supplier_code}</span> <span className="muted">{r.supplier_name}</span></span> },
      { key: "coo", header: t("net.chg.coo"), width: "70px", sortValue: (r) => r.coo ?? "", render: (r) => r.coo ?? "–" },
      {
        key: "flags",
        header: t("net.risk.flags"),
        width: "200px",
        wrap: true,
        render: (r) => (
          <span className="row wrap" style={{ gap: 4 }}>
            {r.flags.map((f) => (
              <span key={f} className="badge warn">
                <Icon name="alert" /> {f === "single_source" ? t("net.risk.flag.single") : t("net.risk.flag.country")}
              </span>
            ))}
          </span>
        ),
      },
      { key: "spend", header: t("net.risk.spend"), width: "130px", align: "right", sortValue: (r) => r.spend_12m, exportValue: (r) => r.spend_12m, render: (r) => <span className="pl-num">{formatMoney(r.spend_12m, r.currency, { compact: true })}</span> },
      { key: "otd", header: t("net.risk.otd"), width: "90px", align: "right", drop: 2, sortValue: (r) => r.otd_pct ?? -1, render: (r) => <span className="pl-num">{pct100(r.otd_pct, 0)}</span> },
      { key: "lead", header: t("net.risk.lead"), width: "90px", align: "right", drop: 3, sortValue: (r) => r.lead_days ?? -1, render: (r) => <span className="pl-num">{r.lead_days === null ? "–" : t("net.tpl.days", { n: r.lead_days })}</span> },
      { key: "duty", header: t("net.landed.duty"), width: "80px", align: "right", drop: 1, sortValue: (r) => r.duty_pct ?? -1, render: (r) => <span className="pl-num">{pct100(r.duty_pct, 0)}</span> },
    ],
    [isNet, nodes],
  );
  return (
    <div className="col gap-lg" data-testid="risk-page">
      <PageHeader title={t("net.risk.title")} description={t("net.risk.desc")} facts={[[t("net.risk.fact.rows"), formatNumber(rows.length)], [t("net.risk.fact.high"), formatNumber(rows.filter((r) => r.score >= 50).length)]]} />
      <FilterBar
        search={{ id: "risk-q", value: q, onChange: setQ, placeholder: t("net.risk.searchPh") }}
        pageKey="sourcing-risk"
        end={<Segmented value={minScore} onChange={(v) => setMinScore(v as typeof minScore)} label={t("net.risk.min")} options={[{ value: "50", label: t("net.risk.minHigh") }, { value: "30", label: t("net.risk.minMedium") }, { value: "0", label: t("net.risk.minAll") }]} testId="risk-min" />}
      >
        {isNet ? (
          <div className="field">
            <label htmlFor="risk-node">{t("net.label.node")}</label>
            <select id="risk-node" className="select sm" value={node} onChange={(e) => setNode(e.target.value)}>
              <option value="">{t("net.label.allNodes")}</option>
              {nodes.nodes.map((n) => (
                <option key={n.owner_id} value={n.owner_id}>
                  {n.code}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </FilterBar>
      <MfgError error={risk.error} onRetry={risk.reload} />
      <section className="card card-table">
        <DataTable<RiskRow>
          rows={rows}
          columns={columns}
          rowKey={(r) => `${r.node_owner_id}|${r.item_id}|${r.supplier_code}`}
          label={t("net.risk.title")}
          testId="risk-table"
          loading={risk.loading && !risk.data}
          exportName="sourcing-risk"
          empty={t("net.risk.empty")}
          rowExtras={(r) => ({ testId: "risk-row", data: { score: r.score } })}
          rowDetail={(r) => (
            <div className="col small" style={{ gap: 4 }}>
              <span className="muted">{t("net.risk.parts", { s: r.parts.single_source, c: r.parts.country, l: r.parts.lead_time, o: r.parts.otd, tr: r.parts.tariff })}</span>
              {r.suggestions.length ? (
                <span className="row wrap" style={{ gap: 8 }}>
                  <strong>{t("net.risk.suggest")}</strong>
                  {r.suggestions.slice(0, 3).map((s) => (
                    <span key={`${s.node_owner_id}|${s.supplier_code}`} className="row" style={{ gap: 4 }}>
                      <span className="mono">{s.supplier_code}</span> {s.supplier_name} {s.coo ? `(${s.coo})` : ""}
                      {s.landed_delta !== null ? <span className="pl-num muted">{t("net.risk.deltaTpl", { v: formatMoney(s.landed_delta, r.currency, { digits: 4, signed: true }) })}</span> : null}
                      <span className="muted">{s.basis === "family" ? t("net.risk.sameFamily") : t("net.risk.sameHeading")}</span>
                      {isNet ? (
                        <button type="button" className="btn sm" onClick={() => setCreate({ row: r, sug: s })} data-testid="risk-create">
                          <Icon name="plus" /> {t("net.risk.create")}
                        </button>
                      ) : netWs ? (
                        <button type="button" className="btn sm" onClick={() => switchWorkspace(netWs.owner_id, null, `${mfgPaths.sourcingRisk()}?item=${encodeURIComponent(r.part_number)}`)}>
                          <Icon name="external" /> {t("net.risk.openNetwork")}
                        </button>
                      ) : null}
                    </span>
                  ))}
                </span>
              ) : r.score >= 50 ? (
                <span className="muted">{t("net.risk.noSuggest")}</span>
              ) : null}
            </div>
          )}
        />
      </section>
      {create ? <CreateScenarioDialog row={create.row} sug={create.sug} onClose={() => setCreate(null)} onCreated={(id) => navigate(mfgPaths.sopScenario(id))} /> : null}
    </div>
  );
}

function CreateScenarioDialog({ row, sug, onClose, onCreated }: { row: RiskRow; sug: RiskSuggestion; onClose(): void; onCreated(id: string): void }) {
  const canEdit = useCan("sop_edit");
  const nodes = useNodes();
  const cycles = useLoad((s) => listCycles({ limit: 6 }, s), []);
  const open = (cycles.data?.items ?? []).filter((c) => ["draft", "demand_review", "supply_review", "pre_sop"].includes(c.status));
  const [cycle, setCycle] = useState("");
  const [share, setShare] = useState(60);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const cyc = cycle || open[0]?.id || "";
  const go = async () => {
    setBusy(true);
    setErr(null);
    const node = nodes.code(row.node_owner_id);
    const change: SupplierAllocationChange = {
      id: `dual-${Date.now().toString(36)}`,
      kind: "supplier_allocation",
      label: t("net.risk.changeLabel", { f: row.family ?? row.part_number, a: row.supplier_code, b: sug.supplier_code }),
      note: t("net.risk.changeNote", { s: row.score }),
      node,
      family: row.family ?? row.item_key,
      suppliers: [
        { code: row.supplier_code, min_share: share / 100, max_share: share / 100 },
        { code: sug.supplier_code, min_share: 1 - share / 100, max_share: 1 - share / 100 },
      ],
    };
    try {
      const s = await createScenario({ cycle_id: cyc || null, name: change.label, changes: [change], capex_note: "" });
      onCreated(s.id);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("net.risk.create")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={!canEdit || busy} onClick={() => void go()} data-testid="risk-create-go">
            <Icon name="plus" /> {t("net.scn.btn.create")}
          </button>
        </>
      }
    >
      <div className="col pl-gap">
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{t("net.risk.createBody", { a: row.supplier_code, b: sug.supplier_code, f: row.family ?? row.part_number })}</p>
        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field">
            <label htmlFor="rk-cycle">{t("net.risk.cycle")}</label>
            <select id="rk-cycle" className="select" value={cyc} onChange={(e) => setCycle(e.target.value)}>
              {open.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.number}
                </option>
              ))}
              <option value="">{t("net.risk.template")}</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="rk-share">{t("net.risk.share", { s: row.supplier_code })}</label>
            <input id="rk-share" className="input pl-w-140" type="number" min={0} max={100} value={share} onChange={(e) => setShare(Math.max(0, Math.min(100, Number(e.target.value))))} />
            <span className="hint">{t("net.risk.shareHint", { b: sug.supplier_code, v: 100 - share })}</span>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
