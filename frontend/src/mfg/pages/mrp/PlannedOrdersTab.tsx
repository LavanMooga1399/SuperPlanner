/**
 * Planned orders (M2 14.2 `PlannedOrdersTab`, 8.11, 8.14): filters, multi-select (max 500), and the Firm /
 * Release dialog (purchase request grouping, quantity and date overrides). Conversion only from the latest
 * live run; each planned order converts once (the server answers 409 otherwise).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { Dialog } from "../../../components/Dialog";
import { Icon } from "../../../components/Icon";
import { convertPlannedOrders, listPlannedOrders, newIdempotencyKey } from "../../api/clientM2";
import type { ConvertOrder, ConvertResponse, PlannedKind, PlannedOrderPage, PlannedOrderRow, PlannedSort, PlannedStatus, ReleaseStatus } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { numOrNull } from "../../components/Field";
import { MakeBuyBadge } from "../../components/StatusChip";
import { LateBadge, ReleaseChip } from "../../components/StatusM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { fmtNum, segmentText } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { needsText, useCan } from "../../lib/permissions";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced } from "../../lib/useMfg";
import { useRun } from "./RunShell";

const MAX_SELECT = 500;

function ConvertDialog({ runId, orders, onClose, onDone }: { runId: string; orders: PlannedOrderRow[]; onClose(): void; onDone(r: ConvertResponse): void }) {
  const [mode, setMode] = useState<"firm" | "release">("release");
  const [grouping, setGrouping] = useState<"per_supplier" | "per_order">("per_supplier");
  const [reserve, setReserve] = useState(false);
  const [over, setOver] = useState<Record<string, { qty: string; date: string }>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const key = useRef<{ body: string; key: string } | null>(null);
  const make = orders.filter((o) => o.kind === "make").length;
  const buy = orders.length - make;
  const body = {
    mode,
    pr_grouping: grouping,
    add_to_pr_id: null,
    reserve: mode === "release" && reserve,
    orders: orders.map((o): ConvertOrder => {
      const x = over[o.id];
      const q = x ? numOrNull(x.qty) : null;
      return { id: o.id, ...(q !== null && q !== o.qty ? { qty: q } : {}), ...(x?.date ? (o.kind === "make" ? { start_date: x.date } : { need_date: x.date }) : {}) };
    }),
  };
  const submit = async () => {
    const text = JSON.stringify(body);
    if (!key.current || key.current.body !== text) key.current = { body: text, key: newIdempotencyKey("mrpconv") };
    setBusy(true);
    setError(null);
    try {
      onDone(await convertPlannedOrders(runId, body, key.current.key));
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={`Convert ${orders.length} planned ${orders.length === 1 ? "order" : "orders"}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={busy} data-testid="convert-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />} {mode === "firm" ? "Firm" : "Release"} {orders.length}
          </button>
        </>
      }
    >
      <div className="col" data-testid="convert-dialog">
        <div className="row wrap" role="radiogroup" aria-label="How to convert">
          <label className={`card card-body col${mode === "firm" ? " mfg-inline-form" : ""}`} style={{ flex: "1 1 240px", gap: 4, cursor: "pointer" }}>
            <span className="row">
              <input type="radio" name="conv-mode" checked={mode === "firm"} onChange={() => setMode("firm")} data-testid="convert-mode-firm" />
              <strong>Firm</strong>
            </span>
            <span className="small muted">Work orders in status planned, purchase requests as drafts. Nothing goes to the floor or the supplier yet.</span>
          </label>
          <label className={`card card-body col${mode === "release" ? " mfg-inline-form" : ""}`} style={{ flex: "1 1 240px", gap: 4, cursor: "pointer" }}>
            <span className="row">
              <input type="radio" name="conv-mode" checked={mode === "release"} onChange={() => setMode("release")} data-testid="convert-mode-release" />
              <strong>Release</strong>
            </span>
            <span className="small muted">Work orders released to the floor, purchase requests submitted for approval.</span>
          </label>
        </div>
        <p className="small" style={{ margin: 0 }}>
          {make} to make → work orders · {buy} to buy → purchase requests
        </p>
        <div className="form-grid">
          {buy ? (
            <div className="field">
              <label htmlFor="conv-group">Purchase requests</label>
              <select id="conv-group" className="select" value={grouping} onChange={(e) => setGrouping(e.target.value as "per_supplier" | "per_order")}>
                <option value="per_supplier">One request per supplier</option>
                <option value="per_order">One request per planned order</option>
              </select>
            </div>
          ) : null}
          {make && mode === "release" ? (
            <label className="checkbox" style={{ alignSelf: "flex-end" }}>
              <input type="checkbox" checked={reserve} onChange={(e) => setReserve(e.target.checked)} /> Reserve free stock for the released work orders
            </label>
          ) : null}
        </div>
        <details>
          <summary className="small">Change quantities or dates ({orders.length})</summary>
          <div className="table-wrap" style={{ maxHeight: "40vh", overflow: "auto" }}>
            <table className="table mfg-grid-table">
              <thead>
                <tr>
                  <th>Planned</th>
                  <th>Item</th>
                  <th>Quantity</th>
                  <th>Start (make) / need date (buy)</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td className="mono">P-{o.planned_no}</td>
                    <td className="mono">{o.item.part_number}</td>
                    <td style={{ width: 120 }}>
                      <input
                        className="input sm num"
                        type="number"
                        aria-label={`Quantity P-${o.planned_no}`}
                        value={over[o.id]?.qty ?? String(o.qty)}
                        onChange={(e) => setOver((m) => ({ ...m, [o.id]: { qty: e.target.value, date: m[o.id]?.date ?? "" } }))}
                      />
                    </td>
                    <td style={{ width: 170 }}>
                      <input
                        className="input sm"
                        type="date"
                        aria-label={`Date P-${o.planned_no}`}
                        value={over[o.id]?.date || (o.kind === "make" ? o.start_date : o.need_date)}
                        onChange={(e) => setOver((m) => ({ ...m, [o.id]: { qty: m[o.id]?.qty ?? String(o.qty), date: e.target.value } }))}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
        <MfgError error={error} title="Nothing was converted" />
      </div>
    </Dialog>
  );
}

export function PlannedOrdersTab() {
  const { run, isLatestLive } = useRun();
  const canRun = useCan("mrp_run");
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const kind = (params.get("kind") ?? "") as PlannedKind | "";
  const release = (params.get("release") ?? "") as ReleaseStatus | "";
  const status = (params.get("status") ?? "open") as PlannedStatus | "all";
  const sort = (params.get("sort") ?? "start_date") as PlannedSort;
  const orderParam = params.get("order");
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps
  const [selected, setSelected] = useState<Map<string, PlannedOrderRow>>(new Map());
  const [converting, setConverting] = useState(false);
  const [result, setResult] = useState<ConvertResponse | null>(null);
  const data = usePaged<PlannedOrderRow, PlannedOrderPage>(
    (offset, limit, signal) =>
      listPlannedOrders(
        run.id,
        { q: dq || undefined, kind: kind || undefined, release_status: release || undefined, status: status === "all" ? undefined : status, sort, limit, offset },
        signal,
      ),
    [run.id, dq, kind, release, status, sort],
  );
  const hi = orderParam ? data.rows.findIndex((r) => r.id === orderParam) : -1;
  useEffect(() => {
    if (orderParam && hi < 0 && !data.loading && data.rows.length < data.total && data.rows.length < 4000) data.onEndReached();
  }, [orderParam, hi, data]);
  const scrollTo = useMemo(() => (hi >= 0 ? { index: hi, seq: 1 } : null), [hi]);
  const canConvert = isLatestLive && canRun;
  const toggle = (r: PlannedOrderRow) =>
    setSelected((m) => {
      const n = new Map(m);
      if (n.has(r.id)) n.delete(r.id);
      else if (n.size < MAX_SELECT && r.status === "open") n.set(r.id, r);
      return n;
    });
  const selectShown = () =>
    setSelected((m) => {
      const n = new Map(m);
      for (const r of data.rows) {
        if (n.size >= MAX_SELECT) break;
        if (r.status === "open") n.set(r.id, r);
      }
      return n;
    });

  const columns: Column<PlannedOrderRow>[] = [
    ...(canConvert
      ? [
          {
            key: "sel",
            header: <span className="sr-only">Select</span>,
            label: "Select",
            width: "36px",
            render: (r: PlannedOrderRow) =>
              r.status === "open" ? (
                <input type="checkbox" tabIndex={-1} aria-label={`Select P-${r.planned_no}`} checked={selected.has(r.id)} onChange={() => toggle(r)} onClick={(e) => e.stopPropagation()} data-testid="planned-select" />
              ) : null,
          } as Column<PlannedOrderRow>,
        ]
      : []),
    { key: "no", header: "No.", width: "70px", render: (r) => <span className="mono">P-{r.planned_no}</span> },
    { key: "kind", header: "Make / buy", width: "96px", render: (r) => <MakeBuyBadge value={r.kind} /> },
    {
      key: "pn",
      header: "Item",
      width: "minmax(150px, 1.2fr)",
      render: (r) => (
        <Link to={mfgPaths.runItem(run.id, r.item.id)} className="mono mfg-ellipsis" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
          {r.item.part_number}
        </Link>
      ),
    },
    { key: "qty", header: "Qty", width: "84px", align: "right", render: (r) => fmtNum(r.qty) },
    { key: "start", header: "Start / order by", width: "120px", render: (r) => fmtDate(r.start_date) },
    { key: "need", header: "Needed", width: "104px", render: (r) => fmtDate(r.need_date) },
    { key: "rel", header: "Release", width: "160px", render: (r) => <ReleaseChip status={r.release_status} /> },
    { key: "late", header: "Late", width: "84px", render: (r) => <LateBadge days={r.late_days} /> },
    { key: "sup", header: "Supplier", width: "minmax(100px, 0.8fr)", render: (r) => <span className="mfg-ellipsis">{r.supplier?.code ?? (r.kind === "buy" ? <span className="faint">none</span> : "")}</span> },
    { key: "for", header: "For", width: "minmax(140px, 1fr)", render: (r) => <span className="mfg-ellipsis small" title={r.peg_summary.map((p) => `${p.label} ${fmtNum(p.qty)}`).join(", ")}>{r.peg_summary.map((p) => p.label).join(", ")}{r.segment ? ` · ${segmentText(r.segment)}` : ""}</span> },
    { key: "lot", header: "Sizing", width: "minmax(120px, 1fr)", render: (r) => <span className="mfg-ellipsis faint small">{r.lot_note}</span> },
    {
      key: "conv",
      header: "Converted",
      width: "120px",
      render: (r) =>
        r.converted ? (
          <Link to={r.converted.type === "wo" ? mfgPaths.workOrder(r.converted.id) : mfgPaths.purchaseDoc("pr", r.converted.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            <Icon name="check" size={12} /> {r.converted.number}
          </Link>
        ) : null,
    },
  ];

  const counts = data.last?.counts;
  return (
    <div className="col gap-lg">
      {!isLatestLive ? (
        <Banner tone="info" icon="lock" title="Converting is only possible from the latest live plan">
          {run.kind === "what_if" ? "This is a what-if scenario." : "A newer live run exists, or this run did not complete."} <Link to={mfgPaths.mrp()}>Open the runs list</Link>.
        </Banner>
      ) : !canRun ? (
        <Banner tone="info" icon="lock" title="Read only">
          {needsText("mrp_run")}
        </Banner>
      ) : null}
      {result ? (
        <Banner tone="ok" role="status" title={`Converted ${result.converted.length} planned orders`} testId="convert-result">
          {result.created.work_orders.length ? (
            <>
              Work orders: {result.created.work_orders.slice(0, 10).map((w, i) => (
                <span key={w.id}>
                  {i ? ", " : ""}
                  <Link to={mfgPaths.workOrder(w.id)}>{w.number}</Link>
                </span>
              ))}
              {result.created.work_orders.length > 10 ? ` +${result.created.work_orders.length - 10}` : ""}.{" "}
            </>
          ) : null}
          {result.created.purchase_requests.length ? (
            <>
              Purchase requests: {result.created.purchase_requests.slice(0, 10).map((p, i) => (
                <span key={p.id}>
                  {i ? ", " : ""}
                  <Link to={mfgPaths.purchaseDoc("pr", p.id)}>{p.number}</Link>
                </span>
              ))}
              {result.created.purchase_requests.length > 10 ? ` +${result.created.purchase_requests.length - 10}` : ""}.
            </>
          ) : null}{" "}
          Run MRP again to see them as supply.
        </Banner>
      ) : null}
      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 200px" }}>
          <label htmlFor="po-q">Search</label>
          <input id="po-q" className="input" type="search" placeholder="Part number" value={q} onChange={(e) => setQ(e.target.value)} data-testid="planned-search" />
        </div>
        <div className="field">
          <label htmlFor="po-kind">Make / buy</label>
          <select id="po-kind" className="select" value={kind} onChange={(e) => set("kind", e.target.value)} data-testid="planned-kind">
            <option value="">All {counts?.by_kind ? `(${(counts.by_kind.make ?? 0) + (counts.by_kind.buy ?? 0)})` : ""}</option>
            <option value="make">Make{counts?.by_kind ? ` (${counts.by_kind.make ?? 0})` : ""}</option>
            <option value="buy">Buy{counts?.by_kind ? ` (${counts.by_kind.buy ?? 0})` : ""}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="po-rel">Release</label>
          <select id="po-rel" className="select" value={release} onChange={(e) => set("release", e.target.value)} data-testid="planned-release">
            <option value="">Any</option>
            <option value="start_in_past">Should have started{counts?.by_release_status ? ` (${counts.by_release_status.start_in_past ?? 0})` : ""}</option>
            <option value="release_now">Release now{counts?.by_release_status ? ` (${counts.by_release_status.release_now ?? 0})` : ""}</option>
            <option value="later">Later{counts?.by_release_status ? ` (${counts.by_release_status.later ?? 0})` : ""}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="po-st">Status</label>
          <select id="po-st" className="select" value={status} onChange={(e) => set("status", e.target.value === "open" ? "" : e.target.value)}>
            <option value="open">Not converted</option>
            <option value="converted">Converted</option>
            <option value="all">All</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="po-sort">Sort by</label>
          <select id="po-sort" className="select" value={sort} onChange={(e) => set("sort", e.target.value === "start_date" ? "" : e.target.value)}>
            <option value="start_date">Start date</option>
            <option value="need_date">Need date</option>
            <option value="part_number">Part number</option>
            <option value="supplier">Supplier</option>
          </select>
        </div>
      </div>
      {canConvert ? (
        <div className="row wrap">
          <button type="button" className="btn sm" onClick={selectShown} disabled={!data.rows.length}>
            Select shown ({Math.min(MAX_SELECT, data.rows.filter((r) => r.status === "open").length)})
          </button>
          {selected.size ? (
            <button type="button" className="btn sm ghost" onClick={() => setSelected(new Map())}>
              Clear selection
            </button>
          ) : null}
          <span className="small muted" data-testid="planned-selected-count">
            {selected.size} selected{selected.size >= MAX_SELECT ? ` (maximum ${MAX_SELECT})` : ""}
          </span>
          <button type="button" className="btn primary" onClick={() => setConverting(true)} disabled={!selected.size} data-testid="convert-open">
            <Icon name="check" /> Firm / release…
          </button>
        </div>
      ) : (
        <button type="button" className="btn" disabled aria-disabled title={!isLatestLive ? "Only from the latest live run" : needsText("mrp_run")} data-testid="convert-open" style={{ alignSelf: "flex-start" }}>
          <Icon name="lock" /> Firm / release…
        </button>
      )}
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(r) => r.id}
        label="Planned orders"
        testId="planned-table"
        totalCount={data.total}
        height="min(62vh, 680px)"
        scrollTo={scrollTo}
        rowExtras={(r) => ({
          testId: "planned-row",
          data: { "release-status": r.release_status, item: r.item.part_number, kind: r.kind, status: r.status },
          className: r.id === orderParam ? "mfg-selected" : undefined,
          ariaSelected: selected.has(r.id),
        })}
        onRowKey={(e, r) => {
          if (e.key === " " && canConvert) {
            toggle(r);
            return true;
          }
          return false;
        }}
        onEndReached={data.onEndReached}
        empty={data.loading ? "Loading planned orders…" : "No planned orders match these filters."}
        footer={<span className="muted small">Showing {data.rows.length.toLocaleString()} of {data.total.toLocaleString()} planned orders{canConvert ? " · Space selects the focused row" : ""}</span>}
      />
      {converting ? (
        <ConvertDialog
          runId={run.id}
          orders={[...selected.values()]}
          onClose={() => setConverting(false)}
          onDone={(r) => {
            setConverting(false);
            setResult(r);
            setSelected(new Map());
            data.reload();
          }}
        />
      ) : null}
    </div>
  );
}
