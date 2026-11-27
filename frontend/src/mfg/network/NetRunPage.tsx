/**
 * `/mfg/network/runs/:runId/:tab?` (M9 5, 10): one network (DRP) run - projection grid (node x week per key),
 * planned transfers (firm zone marked), shortages with their cause, capacity heatmap (node x cap group x week),
 * the pegging tree across plants, and Publish (firm transfers become transfer orders in both plants; later ones reach
 * plant MRP as network demand / supply). A run that failed the independent validator is never publishable (N3).
 */
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, NavLink, useParams, useSearchParams } from "react-router";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DateInput } from "../../components/DateInput";
import { FilterBar } from "../../components/FilterBar";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { toast } from "../../components/Toast";
import { plural, t } from "../../lib/i18n";
import { formatDay, formatMoney, formatNumber } from "../../lib/locale";
import { getNetGrid, getNetPegging, getNetRun, getNetShortages, getNetTransfers, getNetUtilisation, publishNetRun } from "../api/clientM9";
import type { NetGridRow, NetPegNode, NetPublishResult, NetPublishTo, NetRun, NetShortage, NetTransfer } from "../api/typesM9";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { usePolling } from "../lib/usePolling";
import { setSearchParam } from "../lib/usePaged";
import { switchWorkspace } from "../lib/workspace";
import { errorCode, useDebounced, useLoad } from "../lib/useMfg";
import { useChangeReason } from "../qa/ChangeReason";
import { CauseChip, codeText9, Facts, HeatValue, heatClass, isRunning, JobChip, KpiCard, NodeTag, num, pct, useNodes, weekShort } from "./shared";

const TABS = ["grid", "transfers", "shortages", "capacity", "pegging", "publish"] as const;
type Tab = (typeof TABS)[number];
type Nodes = ReturnType<typeof useNodes>;

export function NetRunPage() {
  const { runId = "", tab: tabParam } = useParams();
  const tab: Tab = TABS.includes(tabParam as Tab) ? (tabParam as Tab) : "grid";
  const canPublish = useCan("network_publish");
  const reason = useChangeReason();
  const nodes = useNodes();
  const run = useLoad((s) => getNetRun(runId, s), [runId]);
  const r = run.data;
  usePolling(run.reload, isRunning(r?.status));
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (r) document.title = `${r.number} - ${t("net.home.title")}`;
  }, [r]);
  if (run.error && !r) return <MfgError error={run.error} onRetry={run.reload} />;
  if (!r) return <Spinner />;
  const done = r.status === "completed";
  const validOk = Boolean(r.validator?.ok);
  const publishable = done && validOk && !r.published;
  const s = r.summary;
  const publish = async () => {
    const why = await reason.ask(t("net.run.what", { n: r.number }));
    if (why === null) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await publishNetRun(r.id, why);
      toast(t("net.run.toast.published", { n: r.number, c: formatNumber(res.created.length), k: formatNumber(res.kept.length), x: formatNumber(res.cancelled.length) }));
      setConfirm(false);
      run.reload();
    } catch (e) {
      setErr(e);
      setConfirm(false);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="col gap-lg" data-testid="net-run-page" data-status={r.status}>
      <div className="mfg-breadcrumb small muted">
        <Link to={mfgPaths.network()}>{t("net.home.title")}</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{r.number}</span>
      </div>
      <PageHeader
        title={t("net.run.tpl.title", { n: r.number })}
        meta={
          <>
            <JobChip s={r.status} testId="net-run-status" />
            {r.published ? (
              <span className="badge ok" data-testid="net-run-published">
                <Icon name="flag" /> {t("net.run.published")}
              </span>
            ) : null}
          </>
        }
        description={r.label || undefined}
        facts={[
          [t("net.run.head.asOf"), formatDay(r.as_of)],
          [t("net.run.fact.horizon"), plural(r.params.horizon_weeks ?? 26, t("plan.noun.week"), t("plan.noun.weeks"))],
          [t("net.run.fact.capacity"), r.params.constrained === false ? t("net.run.cap.off") : t("net.run.cap.on")],
          [t("net.run.fact.nodes"), formatNumber(s?.nodes ?? 0)],
          [t("net.run.fact.keys"), formatNumber(s?.keys ?? 0)],
        ]}
        actions={
          <button
            type="button"
            className="btn primary"
            disabled={!canPublish || !publishable}
            title={!canPublish ? needsText("network_publish") : r.published ? t("net.run.hint.isPublished") : done && !validOk ? t("net.run.hint.notValid") : undefined}
            onClick={() => setConfirm(true)}
            data-testid="net-publish"
          >
            <Icon name="flag" /> {t("net.run.btn.publish")}
          </button>
        }
      />
      {errorCode(err) === "NET_RUN_STALE" ? (
        <Banner tone="warn" role="alert" title={t("net.run.text.stale")} testId="net-stale">
          {t("net.run.text.staleBody")}
        </Banner>
      ) : (
        <MfgError error={err} />
      )}
      {isRunning(r.status) ? (
        <Banner tone="accent" icon="loader" role="status">
          {t("net.run.text.running")}
        </Banner>
      ) : null}
      {r.status === "failed" ? (
        <Banner tone="danger" role="alert" title={t("net.run.text.failed")}>
          {r.error ?? ""}
        </Banner>
      ) : null}
      {r.validator && !r.validator.ok ? (
        <Banner tone="danger" icon="shield" role="alert" title={t("net.run.text.invalid", { n: plural(r.validator.violations.length, t("plan.noun.problem"), t("plan.noun.problems")) })} testId="net-violations">
          <ul className="pl-bullets">
            {r.validator.violations.slice(0, 8).map((v, i) => (
              <li key={i}>
                <span className="mono small">{v.code}</span> {typeof v.detail === "string" ? v.detail : JSON.stringify(v.detail)}
              </li>
            ))}
          </ul>
        </Banner>
      ) : done && validOk ? (
        <p className="pl-note ok" style={{ margin: 0 }} data-testid="net-valid">
          <Icon name="shield" size={14} /> {t("net.run.text.valid")}
        </p>
      ) : null}
      {s ? (
        <div className="net-kpis" data-testid="net-run-kpis">
          <KpiCard label={t("net.kpi.fill")} value={pct(s.fill_rate)} />
          <KpiCard label={t("net.kpi.shortUnits")} value={num(s.shortage_units)} unit={t("net.unit.units")} sub={plural(s.shortages, t("net.noun.shortage"), t("net.noun.shortages"))} />
          <KpiCard label={t("net.kpi.inventory")} value={formatMoney(s.inventory_value, s.currency, { compact: true })} unit={s.currency} />
          <KpiCard label={t("net.kpi.transferUnits")} value={num(s.transfer_units)} unit={t("net.unit.units")} sub={t("net.tpl.firmOf", { n: formatNumber(s.firm_transfers), m: formatNumber(s.transfers) })} />
          <KpiCard label={t("net.kpi.maxUtil")} value={pct(s.max_utilisation, 0)} />
        </div>
      ) : null}
      {r.explanations.length ? (
        <details className="card">
          <summary className="small">{t("net.run.explanations", { n: plural(r.explanations.length, t("noun.note"), t("noun.notes")) })}</summary>
          <ul className="pl-bullets small" style={{ marginTop: 8 }}>
            {r.explanations.slice(0, 30).map((e, i) => (
              <li key={i}>
                {codeText9(e.code)} {e.node ? <span className="mono">{nodes.code(e.node)}</span> : null} {e.key ? <span className="mono">{e.key}</span> : null} {e.week ? weekShort(e.week) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <nav className="tabs" aria-label={t("net.run.aria.tabs")}>
        {TABS.map((k) => (
          <NavLink key={k} to={mfgPaths.netRun(r.id, k === "grid" ? undefined : k)} end className={() => `tab${tab === k ? " active" : ""}`} aria-current={tab === k ? "page" : undefined} data-testid={`net-tab-${k}`}>
            {t(`net.run.tab.${k}` as const)}
            {k === "shortages" && s?.shortages ? <span className="tab-count">{s.shortages}</span> : null}
          </NavLink>
        ))}
      </nav>
      {done ? (
        tab === "grid" ? (
          <GridTab run={r} nodes={nodes} />
        ) : tab === "transfers" ? (
          <TransfersTab run={r} nodes={nodes} />
        ) : tab === "shortages" ? (
          <ShortagesTab run={r} nodes={nodes} />
        ) : tab === "capacity" ? (
          <CapacityTab run={r} nodes={nodes} />
        ) : tab === "pegging" ? (
          <PeggingTab run={r} nodes={nodes} />
        ) : (
          <PublishTab run={r} nodes={nodes} />
        )
      ) : null}
      {confirm ? (
        <ConfirmDialog title={t("net.run.dlg.publishTitle", { n: r.number })} confirmLabel={t("net.run.btn.publish")} busy={busy} onConfirm={() => void publish()} onCancel={() => setConfirm(false)}>
          <div className="col pl-gap">
            <p style={{ margin: 0 }}>{t("net.run.dlg.publishBody", { n: r.params.firm_days ?? 14 })}</p>
            <ul className="pl-bullets">
              <li>{t("net.run.dlg.publish1")}</li>
              <li>{t("net.run.dlg.publish2")}</li>
              <li>{t("net.run.dlg.publish3")}</li>
            </ul>
            {s?.shortages ? <Banner tone="warn">{t("net.run.dlg.publishShort", { n: plural(s.shortages, t("net.noun.shortage"), t("net.noun.shortages")) })}</Banner> : null}
          </div>
        </ConfirmDialog>
      ) : null}
      {reason.dialog}
    </div>
  );
}

function NodeSelect({ id, value, onChange, nodes, label }: { id: string; value: string; onChange(v: string): void; nodes: Nodes; label: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} className="select sm" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("net.label.allNodes")}</option>
        {nodes.nodes.map((n) => (
          <option key={n.owner_id} value={n.owner_id}>
            {n.code} · {n.name}
          </option>
        ))}
      </select>
    </div>
  );
}

// ---------------------------------------------------------------- grid
const GRID_ROWS: { k: "gross" | "receipts" | "planned_in" | "planned_out" | "projected"; label: "net.grid.gross" | "net.grid.receipts" | "net.grid.plannedIn" | "net.grid.plannedOut" | "net.grid.projected" }[] = [
  { k: "gross", label: "net.grid.gross" },
  { k: "receipts", label: "net.grid.receipts" },
  { k: "planned_in", label: "net.grid.plannedIn" },
  { k: "planned_out", label: "net.grid.plannedOut" },
  { k: "projected", label: "net.grid.projected" },
];

function GridTab({ run, nodes }: { run: NetRun; nodes: Nodes }) {
  const [params, setParams] = useSearchParams();
  const node = params.get("node") ?? "";
  const [key, setKey] = useState(params.get("key") ?? "");
  const [family, setFamily] = useState("");
  const [page, setPage] = useState(1);
  const dKey = useDebounced(key, 300);
  const dFam = useDebounced(family, 300);
  const grid = useLoad((s) => getNetGrid(run.id, { node: node || undefined, key: dKey || undefined, family: dFam || undefined, page }, s), [run.id, node, dKey, dFam, page]);
  const g = grid.data;
  const firmUntil = useMemo(() => {
    const d = new Date(`${run.as_of}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + (run.params.firm_days ?? 14));
    return d.toISOString().slice(0, 10);
  }, [run]);
  const pages = g ? Math.max(1, Math.ceil(g.total / Math.max(1, g.limit))) : 1;
  return (
    <div className="col pl-gap">
      <FilterBar
        search={{ id: "net-grid-key", value: key, onChange: (v) => (setKey(v), setPage(1)), placeholder: t("net.grid.searchPh"), label: t("net.label.key"), testId: "net-grid-search" }}
        chips={[
          ...(node ? [{ key: "node", label: t("net.label.node"), value: nodes.code(node), onClear: () => setSearchParam(setParams, "node", "") }] : []),
          ...(family ? [{ key: "family", label: t("net.label.family"), value: family, onClear: () => setFamily("") }] : []),
        ]}
      >
        <NodeSelect id="net-grid-node" value={node} onChange={(v) => (setSearchParam(setParams, "node", v), setPage(1))} nodes={nodes} label={t("net.label.node")} />
        <div className="field">
          <label htmlFor="net-grid-fam">{t("net.label.family")}</label>
          <input id="net-grid-fam" className="input sm" value={family} onChange={(e) => (setFamily(e.target.value), setPage(1))} />
        </div>
      </FilterBar>
      <MfgError error={grid.error} onRetry={grid.reload} />
      {!g ? (
        <Spinner />
      ) : !g.items.length ? (
        <p className="muted card">{t("net.grid.empty")}</p>
      ) : (
        <section className="card card-table">
          <div className="pl-pivot-wrap">
            <table className="pl-pivot" aria-label={t("net.grid.aria")} data-testid="net-grid">
              <thead>
                <tr>
                  <th scope="col">{t("net.grid.row")}</th>
                  {g.weeks.map((w) => (
                    <th key={w} scope="col" className={w <= firmUntil ? "net-firm-zone" : undefined} title={w <= firmUntil ? t("net.grid.firmZone") : undefined}>
                      {weekShort(w)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {g.items.map((row) => (
                  <GridRows key={`${row.node_owner_id}|${row.item_key}`} row={row} weeks={g.weeks} nodes={nodes} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {g && pages > 1 ? (
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            {t("net.grid.prev")}
          </button>
          <span className="small muted">{t("common.nOfM", { n: page, m: pages })}</span>
          <button type="button" className="btn sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            {t("net.grid.next")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function GridRows({ row, weeks, nodes }: { row: NetGridRow; weeks: string[]; nodes: Nodes }) {
  const cells = new Map(row.cells.map((c) => [c.week, c]));
  return (
    <>
      <tr data-testid="net-grid-row">
        <th scope="rowgroup" colSpan={weeks.length + 1} style={{ background: "var(--surface-2)" }}>
          <span className="row" style={{ gap: 8 }}>
            <NodeTag node={nodes.byId.get(row.node_owner_id)} id={row.node_owner_id} />
            <span className="mono">{row.item_key}</span>
            <span className="muted">{row.description ?? ""}</span>
            {row.family ? <span className="muted small">{row.family}</span> : null}
            <span className="muted small">{row.uom}</span>
          </span>
        </th>
      </tr>
      {GRID_ROWS.map((gr) => (
        <tr key={gr.k} className="net-grid-sub">
          <th scope="row">{t(gr.label)}</th>
          {weeks.map((w) => {
            const c = cells.get(w);
            const v = c ? c[gr.k] : null;
            const neg = gr.k === "projected" && c && c.projected < 0;
            const below = gr.k === "projected" && c && c.projected >= 0 && c.projected < c.ss;
            return (
              <td key={w} className={neg ? "net-neg" : below ? "net-below" : undefined} title={gr.k === "projected" && c ? t("net.grid.ssTitle", { ss: num(c.ss) }) : undefined}>
                {neg ? <Icon name="alert" size={12} /> : null}
                {v === null || v === 0 ? (gr.k === "projected" && v === 0 ? "0" : "") : num(v)}
              </td>
            );
          })}
        </tr>
      ))}
    </>
  );
}

// ---------------------------------------------------------------- transfers
function FirmBadge({ firm }: { firm: boolean }) {
  return firm ? (
    <span className="badge accent" data-testid="net-firm">
      <Icon name="lock" /> {t("net.tr.firm")}
    </span>
  ) : (
    <span className="badge info">
      <Icon name="clock" /> {t("net.tr.planned")}
    </span>
  );
}

function TransfersTab({ run, nodes }: { run: NetRun; nodes: Nodes }) {
  const [src, setSrc] = useState("");
  const [dst, setDst] = useState("");
  const [firmOnly, setFirmOnly] = useState(false);
  const tr = useLoad((s) => getNetTransfers(run.id, { src: src || undefined, dst: dst || undefined }, s), [run.id, src, dst]);
  const rows = (tr.data?.items ?? []).filter((x) => !firmOnly || x.firm);
  const columns = useMemo<Column<NetTransfer>[]>(
    () => [
      { key: "route", header: t("net.tr.route"), width: "170px", sortValue: (x) => `${nodes.code(x.src_owner_id)}${nodes.code(x.dst_owner_id)}`, exportValue: (x) => `${nodes.code(x.src_owner_id)} > ${nodes.code(x.dst_owner_id)}`, render: (x) => <span className="row" style={{ gap: 4 }}><NodeTag node={nodes.byId.get(x.src_owner_id)} id={x.src_owner_id} /><Icon name="arrow-right" size={12} /><NodeTag node={nodes.byId.get(x.dst_owner_id)} id={x.dst_owner_id} /></span> },
      { key: "key", header: t("net.label.key"), width: "150px", sortValue: (x) => x.item_key, render: (x) => <span className="mono">{x.item_key}</span> },
      { key: "ship", header: t("net.tr.ship"), width: "110px", sortValue: (x) => x.ship_date, render: (x) => formatDay(x.ship_date) },
      { key: "receive", header: t("net.tr.receive"), width: "110px", sortValue: (x) => x.receive_date, render: (x) => formatDay(x.receive_date) },
      { key: "qty", header: t("net.label.qty"), width: "110px", align: "right", sortValue: (x) => x.qty, exportValue: (x) => x.qty, render: (x) => <span className="pl-num">{t("net.tpl.qtyUom", { q: num(x.qty), u: x.uom })}</span> },
      { key: "firm", header: t("net.tr.zone"), width: "110px", sortValue: (x) => Number(x.firm), exportValue: (x) => (x.firm ? "firm" : "planned"), render: (x) => <FirmBadge firm={x.firm} /> },
      { key: "to", header: t("net.tr.to"), width: "120px", drop: 2, render: (x) => (x.to_number ? <span className="mono">{x.to_number}</span> : <span className="muted">–</span>) },
      { key: "pegs", header: t("net.tr.pegs"), width: "minmax(160px, 1fr)", drop: 1, wrap: true, render: (x) => <span className="small">{x.pegs.slice(0, 3).map((p) => p.ref).join(", ")}{x.pegs.length > 3 ? ` +${x.pegs.length - 3}` : ""}</span> },
    ],
    [nodes],
  );
  return (
    <div className="col pl-gap">
      <FilterBar
        end={
          <label className="row small" style={{ gap: 6 }}>
            <input type="checkbox" checked={firmOnly} onChange={(e) => setFirmOnly(e.target.checked)} data-testid="net-firm-only" /> {t("net.tr.firmOnly")}
          </label>
        }
      >
        <NodeSelect id="net-tr-src" value={src} onChange={setSrc} nodes={nodes} label={t("net.tr.from")} />
        <NodeSelect id="net-tr-dst" value={dst} onChange={setDst} nodes={nodes} label={t("net.tr.toNode")} />
      </FilterBar>
      <MfgError error={tr.error} onRetry={tr.reload} />
      <section className="card card-table">
        <DataTable<NetTransfer> rows={rows} columns={columns} rowKey={(x) => x.id} label={t("net.run.tab.transfers")} testId="net-transfers" loading={tr.loading && !tr.data} exportName="network-transfers" empty={t("net.tr.empty")} rowExtras={(x) => ({ testId: "net-transfer-row", data: { firm: x.firm } })} />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- shortages
function ShortagesTab({ run, nodes }: { run: NetRun; nodes: Nodes }) {
  const sh = useLoad((s) => getNetShortages(run.id, s), [run.id]);
  const columns = useMemo<Column<NetShortage>[]>(
    () => [
      { key: "node", header: t("net.label.node"), width: "110px", sortValue: (x) => nodes.code(x.node_owner_id), render: (x) => <NodeTag node={nodes.byId.get(x.node_owner_id)} id={x.node_owner_id} /> },
      { key: "key", header: t("net.label.key"), width: "150px", sortValue: (x) => x.item_key, render: (x) => <span className="mono">{x.item_key}</span> },
      { key: "week", header: t("net.label.week"), width: "110px", sortValue: (x) => x.week, render: (x) => formatDay(x.week) },
      { key: "qty", header: t("net.label.qty"), width: "110px", align: "right", sortValue: (x) => x.qty, exportValue: (x) => x.qty, render: (x) => <span className="pl-num">{t("net.tpl.qtyUom", { q: num(x.qty), u: x.uom })}</span> },
      { key: "cause", header: t("net.sh.cause"), width: "minmax(190px, 1fr)", sortValue: (x) => x.cause, exportValue: (x) => x.cause, render: (x) => <CauseChip cause={x.cause} /> },
      {
        key: "peg",
        header: <span className="sr-only">{t("net.run.tab.pegging")}</span>,
        label: t("net.run.tab.pegging"),
        width: "120px",
        render: (x) => (
          <Link className="btn sm" to={`${mfgPaths.netRun(run.id, "pegging")}?node=${encodeURIComponent(x.node_owner_id)}&key=${encodeURIComponent(x.item_key)}&week=${x.week}`} onClick={(e) => e.stopPropagation()} data-testid="net-sh-peg">
            <Icon name="link" /> {t("net.sh.trace")}
          </Link>
        ),
      },
    ],
    [nodes, run.id],
  );
  return (
    <div className="col pl-gap">
      <MfgError error={sh.error} onRetry={sh.reload} />
      <section className="card card-table">
        <DataTable<NetShortage>
          rows={sh.data?.items ?? []}
          columns={columns}
          rowKey={(x) => x.id}
          label={t("net.run.tab.shortages")}
          testId="net-shortages"
          loading={sh.loading && !sh.data}
          exportName="network-shortages"
          empty={t("net.sh.empty")}
          rowDetail={(x) => (Object.keys(x.detail ?? {}).length ? <span className="small muted">{Object.entries(x.detail).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(" · ")}</span> : null)}
        />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- capacity heatmap
function CapacityTab({ run, nodes }: { run: NetRun; nodes: Nodes }) {
  const ut = useLoad((s) => getNetUtilisation(run.id, s), [run.id]);
  const data = useMemo(() => {
    const weeks = [...new Set((ut.data?.items ?? []).map((u) => u.week))].sort();
    const rows = new Map<string, { node: string; group: string; cells: Map<string, { a: number; u: number }> }>();
    for (const u of ut.data?.items ?? []) {
      const k = `${u.node}|${u.cap_group}`;
      if (!rows.has(k)) rows.set(k, { node: u.node, group: u.cap_group, cells: new Map() });
      rows.get(k)!.cells.set(u.week, { a: u.available, u: u.used });
    }
    return { weeks, rows: [...rows.values()].sort((a, b) => nodes.code(a.node).localeCompare(nodes.code(b.node)) || a.group.localeCompare(b.group)) };
  }, [ut.data, nodes]);
  if (ut.error) return <MfgError error={ut.error} onRetry={ut.reload} />;
  if (!ut.data) return <Spinner />;
  if (!data.rows.length) return <p className="muted card">{t("net.cap.empty")}</p>;
  return (
    <section className="card col pl-gap">
      <p className="small muted" style={{ margin: 0 }}>
        {t("net.cap.legend")}
      </p>
      <div className="pl-pivot-wrap">
        <table className="pl-pivot net-heat" aria-label={t("net.cap.aria")} data-testid="net-heatmap">
          <thead>
            <tr>
              <th scope="col">{t("net.cap.group")}</th>
              {data.weeks.map((w) => (
                <th key={w} scope="col">
                  {weekShort(w)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={`${r.node}|${r.group}`}>
                <th scope="row">
                  <span className="row" style={{ gap: 6 }}>
                    <NodeTag node={nodes.byId.get(r.node)} id={r.node} /> {r.group}
                  </span>
                </th>
                {data.weeks.map((w) => {
                  const c = r.cells.get(w);
                  const u = c && c.a > 0 ? c.u / c.a : c && c.u > 0 ? Infinity : null;
                  return (
                    <td key={w} className={heatClass(u)} title={c ? t("net.cap.cellTitle", { u: num(c.u, 1), a: num(c.a, 1) }) : undefined}>
                      {u === Infinity ? <Icon name="alert" size={12} /> : <HeatValue u={u} />}
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

// ---------------------------------------------------------------- pegging
const PEG_ICON: Record<string, "flag" | "truck" | "factory" | "briefcase" | "box" | "layers" | "alert"> = {
  demand: "flag",
  transfer: "truck",
  production: "factory",
  purchase: "briefcase",
  supply: "box",
  component: "layers",
  shortage: "alert",
};

function PeggingTab({ run, nodes }: { run: NetRun; nodes: Nodes }) {
  const [params, setParams] = useSearchParams();
  const [node, setNode] = useState(params.get("node") ?? "");
  const [key, setKey] = useState(params.get("key") ?? "");
  const [week, setWeek] = useState(params.get("week") ?? "");
  const q = { node: params.get("node") ?? "", key: params.get("key") ?? "", week: params.get("week") ?? "" };
  const peg = useLoad((s) => (q.node && q.key ? getNetPegging(run.id, { node: q.node, key: q.key, week: q.week || undefined }, s) : null), [run.id, q.node, q.key, q.week]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setParams(new URLSearchParams({ node, key, ...(week ? { week } : {}) }), { replace: true });
  };
  return (
    <div className="col pl-gap">
      <form className="filter-bar toolbar mfg-filters" onSubmit={submit} role="search">
        <NodeSelect id="net-peg-node" value={node} onChange={setNode} nodes={nodes} label={t("net.label.node")} />
        <div className="field">
          <label htmlFor="net-peg-key">{t("net.label.key")}</label>
          <input id="net-peg-key" className="input sm mono" value={key} onChange={(e) => setKey(e.target.value)} data-testid="net-peg-key" />
        </div>
        <div className="field">
          <label htmlFor="net-peg-week">{t("net.label.week")}</label>
          <DateInput id="net-peg-week" small value={week} onChange={setWeek} />
        </div>
        <button type="submit" className="btn sm primary" disabled={!node || !key} data-testid="net-peg-go">
          <Icon name="search" /> {t("net.peg.show")}
        </button>
      </form>
      <MfgError error={peg.error} onRetry={peg.reload} />
      {!q.node || !q.key ? (
        <p className="muted card">{t("net.peg.hint")}</p>
      ) : !peg.data ? (
        <Spinner />
      ) : (
        <section className="card" data-testid="net-pegging">
          <p className="small muted" style={{ marginTop: 0 }}>
            {peg.data.direction === "down" ? t("net.peg.down") : t("net.peg.up")}
          </p>
          <ul className="net-tree" role="tree" aria-label={t("net.run.tab.pegging")}>
            <PegNode n={peg.data.root} nodes={nodes} level={1} />
          </ul>
        </section>
      )}
    </div>
  );
}

function PegNode({ n, nodes, level }: { n: NetPegNode; nodes: Nodes; level: number }) {
  const node = nodes.byId.get(n.node_owner_id);
  return (
    <li role="treeitem" aria-level={level} aria-expanded={n.children.length ? true : undefined} data-testid="net-peg-node" data-kind={n.kind}>
      <div className="net-tree-row">
        <Icon name={PEG_ICON[n.kind] ?? "circle"} size={14} />
        <span className="small">{t(`net.peg.kind.${n.kind}` as const)}</span>
        <NodeTag node={node} id={n.node_owner_id} />
        <span className="mono">{n.item_key}</span>
        {n.week ? <span className="muted small">{weekShort(n.week)}</span> : null}
        {n.ref ? (
          n.link && node?.member ? (
            <button type="button" className="btn ghost sm" onClick={() => switchWorkspace(n.node_owner_id, null, n.link!)} title={t("net.peg.open", { p: node.code })}>
              <span className="mono">{n.ref}</span> <Icon name="external" size={12} />
            </button>
          ) : (
            <span className="mono small">{n.ref}</span>
          )
        ) : null}
        {n.cause ? <CauseChip cause={n.cause} /> : null}
        <span className="pl-num">{num(n.qty)}</span>
      </div>
      {n.children.length ? (
        <ul role="group">
          {n.children.map((c) => (
            <PegNode key={c.id} n={c} nodes={nodes} level={level + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

// ---------------------------------------------------------------- publish result
function PublishTab({ run, nodes }: { run: NetRun; nodes: Nodes }) {
  const res: NetPublishResult | null = run.publish_result;
  const columns = useMemo<Column<NetPublishTo>[]>(
    () => [
      { key: "number", header: t("net.tr.to"), width: "130px", sortValue: (x) => x.number, render: (x) => <span className="mono">{x.number}</span> },
      { key: "route", header: t("net.tr.route"), width: "170px", render: (x) => <span className="row" style={{ gap: 4 }}><NodeTag node={nodes.byId.get(x.src_owner_id)} id={x.src_owner_id} /><Icon name="arrow-right" size={12} /><NodeTag node={nodes.byId.get(x.dst_owner_id)} id={x.dst_owner_id} /></span> },
      { key: "ship", header: t("net.tr.ship"), width: "120px", sortValue: (x) => x.ship_date, render: (x) => formatDay(x.ship_date) },
      { key: "lines", header: t("net.pub.lines"), width: "90px", align: "right", sortValue: (x) => x.lines, render: (x) => <span className="pl-num">{num(x.lines)}</span> },
      { key: "qty", header: t("net.label.qty"), width: "110px", align: "right", sortValue: (x) => x.qty, render: (x) => <span className="pl-num">{num(x.qty)}</span> },
    ],
    [nodes],
  );
  if (!res) return <p className="muted card">{run.published ? t("net.pub.noDetail") : t("net.pub.notYet")}</p>;
  const block = (title: string, rows: NetPublishTo[], testId: string) => (
    <section className="card card-table" aria-label={title}>
      <div className="pl-card-header" style={{ padding: "8px 12px" }}>
        <h3 className="pl-h2">{title}</h3>
        <span className="muted small">{plural(rows.length, t("net.noun.order"), t("net.noun.orders"))}</span>
      </div>
      <DataTable<NetPublishTo> rows={rows} columns={columns} rowKey={(x) => x.to_id} label={title} testId={testId} exportName={testId} empty={t("net.pub.none")} />
    </section>
  );
  return (
    <div className="col pl-gap" data-testid="net-publish-result">
      <Facts
        rows={[
          [t("net.pub.created"), formatNumber(res.created.length)],
          [t("net.pub.kept"), formatNumber(res.kept.length)],
          [t("net.pub.cancelled"), formatNumber(res.cancelled.length)],
          [t("net.pub.demands"), formatNumber(res.network_demands)],
          [t("net.pub.supplies"), formatNumber(res.network_supplies)],
        ]}
      />
      {res.warnings.length ? (
        <Banner tone="warn" title={t("net.pub.warnings", { n: plural(res.warnings.length, t("noun.warning"), t("noun.warnings")) })}>
          <ul className="pl-bullets">
            {res.warnings.map((w, i) => (
              <li key={i}>
                {codeText9(w.code)} {w.node ? nodes.code(w.node) : ""} {w.key ?? ""}
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {block(t("net.pub.created"), res.created, "net-pub-created")}
      {block(t("net.pub.kept"), res.kept, "net-pub-kept")}
      {block(t("net.pub.cancelled"), res.cancelled, "net-pub-cancelled")}
    </div>
  );
}
