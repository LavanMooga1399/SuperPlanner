/**
 * Traceability (M5 6, `trace_view`):
 * - `/mfg/trace?kind=&id=&dir=`: start from a serial, lot or work order (scan or type its code: `S:part:serial`,
 *   `L:part:lot`, a WO number), go backward ("what went into it") or forward ("where did it go"). Tree or graph view.
 *   Every link says whether it is exact (recorded unit by unit) or possible (lot level: any unit of that work order may
 *   contain it): an icon and text, plus a solid or dashed line, never colour alone.
 * - `/mfg/trace/where-used?item=&lot=|supplier_lot=`: which work orders, units and shipments used a lot / supplier lot.
 * From any node: trace again from there, or start a recall.
 */
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link, NavLink, useNavigate, useSearchParams } from "react-router";
import { Icon, type IconName } from "../../../components/Icon";
import type { ItemRef } from "../../api/types";
import { floorScan } from "../../api/clientM4";
import { listSerials } from "../../api/clientM4";
import { getTrace, getWhereUsed } from "../../api/clientM5";
import type { Precision, TraceKind, TraceNode, TraceResponse } from "../../api/typesM5";
import { MfgError, Spinner } from "../../components/Feedback";
import { ItemPicker } from "../../components/ItemPicker";
import { fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { setSearchParam } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";

const KIND: Record<TraceKind, { label: string; icon: IconName }> = {
  serial: { label: "Unit", icon: "circle" },
  lot: { label: "Lot", icon: "layers" },
  wo: { label: "Work order", icon: "play" },
  item_stock: { label: "Stock (no lot)", icon: "list" },
  transfer: { label: "Transfer", icon: "arrow-right" },
  demand_line: { label: "Shipped to", icon: "flag" },
};

export function PrecisionTag({ p }: { p: Precision }) {
  return p === "exact" ? (
    <span className="badge ok trace-exact" title="Recorded unit by unit" data-precision="exact">
      <Icon name="check" size={12} /> exact
    </span>
  ) : (
    <span className="badge warn trace-possible" title="Lot level: any unit made from this lot or work order may contain it" data-precision="possible">
      <Icon name="help" size={12} /> possible
    </span>
  );
}

export function normaliseTrace(t: TraceResponse): TraceNode {
  return t.root;
}

export function nodeLink(n: TraceNode): string | null {
  if (n.link) return n.link;
  if (n.kind === "serial") return mfgPaths.serial(n.id);
  if (n.kind === "wo") return mfgPaths.workOrder(n.id);
  return null;
}

function countNodes(n: TraceNode): { all: number; exact: number; possible: number } {
  let all = 0;
  let exact = 0;
  let possible = 0;
  const walk = (x: TraceNode, isRoot: boolean) => {
    all++;
    if (!isRoot) {
      if (x.precision === "exact") exact++;
      else possible++;
    }
    for (const c of x.children ?? []) walk(c, false);
  };
  walk(n, true);
  return { all, exact, possible };
}

function TraceTabs() {
  return (
    <nav className="tabs" aria-label="Traceability">
      <NavLink to={mfgPaths.trace()} end className={({ isActive }) => `tab${isActive ? " active" : ""}`}>
        Trace a unit, lot or order
      </NavLink>
      <NavLink to={mfgPaths.traceWhereUsed()} className={({ isActive }) => `tab${isActive ? " active" : ""}`}>
        Where a lot was used
      </NavLink>
      <NavLink to={mfgPaths.recalls()} className={({ isActive }) => `tab${isActive ? " active" : ""}`}>
        Recalls
      </NavLink>
    </nav>
  );
}

export function TracePage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const kind = (params.get("kind") ?? "") as TraceKind | "";
  const id = params.get("id") ?? "";
  const dir = (params.get("dir") ?? "backward") as "backward" | "forward";
  const label = params.get("label") ?? "";
  const [possible, setPossible] = useState(params.get("possible") !== "0");
  const [depth, setDepth] = useState(30);
  const [expert, setExpert] = useState(false);
  const [view, setView] = useState<"tree" | "graph">("tree");
  const [code, setCode] = useState("");
  const [finding, setFinding] = useState(false);
  const [findError, setFindError] = useState<string | null>(null);
  const tr = useLoad((signal) => (kind && id ? getTrace({ kind, id, direction: dir, depth, include_possible: possible }, signal) : null), [kind, id, dir, depth, possible]);
  const root = useMemo(() => (tr.data ? normaliseTrace(tr.data) : null), [tr.data]);
  const counts = useMemo(() => (root ? countNodes(root) : null), [root]);
  useEffect(() => {
    document.title = "Traceability - SuperPlanner";
  }, []);

  const start = (k: TraceKind, i: string, l: string) =>
    setParams((p) => {
      const n = new URLSearchParams(p);
      n.set("kind", k);
      n.set("id", i);
      n.set("label", l);
      return n;
    });

  const find = async (e: FormEvent) => {
    e.preventDefault();
    const c = code.trim();
    if (!c) return;
    setFinding(true);
    setFindError(null);
    try {
      try {
        const r = await floorScan(c);
        const k: TraceKind | null = r.type === "serial" ? "serial" : r.type === "lot" ? "lot" : r.type === "work_order" ? "wo" : null;
        if (k) {
          start(k, r.id, r.label);
          return;
        }
      } catch {
        /* not a barcode: try serial numbers */
      }
      const s = await listSerials({ q: c, limit: 2 });
      if (s.items.length === 1) start("serial", s.items[0].id, `${s.items[0].serial} (${s.items[0].item.part_number})`);
      else setFindError(s.items.length ? "Several units match; type the full serial or scan the label." : "Nothing found. Scan the label, or type S:part:serial, L:part:lot or a work order number.");
    } catch (err) {
      setFindError((err as Error).message);
    } finally {
      setFinding(false);
    }
  };

  return (
    <div className="col gap-lg" data-testid="trace-page">
      <div className="mfg-page-head">
        <div>
          <h1>Traceability</h1>
          <p>Follow units, lots and work orders back to their materials, or forward to the units and customers they went to.</p>
        </div>
      </div>
      <TraceTabs />
      <form className="toolbar mfg-filters" onSubmit={find} role="search">
        <div className="field" style={{ flex: "1 1 320px" }}>
          <label htmlFor="tr-code">Unit, lot or work order</label>
          <input id="tr-code" className="input mono" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Scan a label, or S:KV-TPU-1000:TPU-0123, L:part:lot, WO-000143" data-testid="trace-code" />
        </div>
        <button type="submit" className="btn primary" disabled={finding} style={{ alignSelf: "flex-end" }} data-testid="trace-find">
          <Icon name="zoom-in" /> Trace
        </button>
      </form>
      {findError ? <div className="banner warn" role="alert">{findError}</div> : null}

      {kind && id ? (
        <>
          <div className="row wrap" style={{ justifyContent: "space-between" }}>
            <div className="row wrap">
              <strong data-testid="trace-root">
                {KIND[kind as TraceKind]?.label}: {label || root?.label || id}
              </strong>
              <div className="row" role="group" aria-label="Direction">
                <button type="button" className={`btn sm${dir === "backward" ? " primary" : ""}`} aria-pressed={dir === "backward"} onClick={() => setSearchParam(setParams, "dir", "backward")} data-testid="trace-backward">
                  <Icon name="arrow-right" style={{ transform: "rotate(180deg)" }} /> What went into it
                </button>
                <button type="button" className={`btn sm${dir === "forward" ? " primary" : ""}`} aria-pressed={dir === "forward"} onClick={() => setSearchParam(setParams, "dir", "forward")} data-testid="trace-forward">
                  Where it went <Icon name="arrow-right" />
                </button>
              </div>
              <label className="checkbox">
                <input type="checkbox" checked={possible} onChange={(e) => setPossible(e.target.checked)} data-testid="trace-possible" /> Include possible links
              </label>
            </div>
            <div className="row">
              <div className="row" role="group" aria-label="View">
                <button type="button" className={`btn sm${view === "tree" ? " primary" : ""}`} aria-pressed={view === "tree"} onClick={() => setView("tree")}>
                  <Icon name="list" /> Tree
                </button>
                <button type="button" className={`btn sm${view === "graph" ? " primary" : ""}`} aria-pressed={view === "graph"} onClick={() => setView("graph")} data-testid="trace-view-graph">
                  <Icon name="graph" /> Graph
                </button>
              </div>
              <button type="button" className="btn sm ghost" aria-expanded={expert} onClick={() => setExpert((v) => !v)}>
                <Icon name="settings" /> Depth
              </button>
            </div>
          </div>
          {expert ? (
            <div className="field" style={{ maxWidth: 200 }}>
              <label htmlFor="tr-depth">Levels to follow (1-30)</label>
              <input id="tr-depth" className="input" type="number" min={1} max={30} value={depth} onChange={(e) => setDepth(Math.min(30, Math.max(1, Number(e.target.value) || 1)))} />
            </div>
          ) : null}
          <MfgError error={tr.error} onRetry={tr.reload} />
          {tr.loading && !root ? <Spinner label="Following the links…" /> : null}
          {root && counts ? (
            <>
              <p className="small muted" style={{ margin: 0 }} data-testid="trace-counts" data-nodes={counts.all}>
                {counts.all} entries · {counts.exact} exact links · {counts.possible} possible links
                {tr.data?.truncated ? " · stopped at 20,000 entries: narrow the depth" : ""}
              </p>
              {view === "tree" ? (
                <TraceTree root={root} onRetrace={(n) => start(n.kind, n.id, n.label)} onRecall={(n) => navigate(`${mfgPaths.recalls()}?new=1&kind=${n.kind}&id=${encodeURIComponent(n.id)}&label=${encodeURIComponent(n.label)}`)} />
              ) : (
                <TraceGraph root={root} dir={dir} />
              )}
            </>
          ) : null}
        </>
      ) : (
        <p className="muted">Scan or type what to trace. A finished unit traced backward shows its work order, the units fitted into it and the lots used; a supplier lot traced forward shows every unit and customer it may have reached.</p>
      )}
    </div>
  );
}

export function TraceTree({ root, onRetrace, onRecall, showRoot = true }: { root: TraceNode; onRetrace?(n: TraceNode): void; onRecall?(n: TraceNode): void; showRoot?: boolean }) {
  return (
    <ul className="trace-tree" role="tree" data-testid="trace-tree">
      {showRoot ? <TreeNode n={root} level={1} isRoot onRetrace={onRetrace} onRecall={onRecall} /> : (root.children ?? []).map((c, i) => <TreeNode key={`${c.kind}${c.id}${i}`} n={c} level={1} onRetrace={onRetrace} onRecall={onRecall} />)}
    </ul>
  );
}

function TreeNode({ n, level, isRoot, onRetrace, onRecall }: { n: TraceNode; level: number; isRoot?: boolean; onRetrace?(n: TraceNode): void; onRecall?(n: TraceNode): void }) {
  const kids = n.children ?? [];
  const [open, setOpen] = useState(level <= 3);
  const canRecall = useCan("trace_view");
  const link = nodeLink(n);
  const k = KIND[n.kind] ?? { label: n.kind, icon: "circle" as IconName };
  return (
    <li role="treeitem" aria-expanded={kids.length ? open : undefined} aria-level={level} className={`trace-node${isRoot ? "" : n.precision === "possible" ? " possible" : " exact"}`} data-testid="trace-node" data-kind={n.kind} data-precision={isRoot ? "root" : n.precision}>
      <div className="trace-row">
        {kids.length ? (
          <button type="button" className="btn ghost icon sm" aria-label={open ? "Collapse" : "Expand"} onClick={() => setOpen((v) => !v)}>
            <Icon name={open ? "chevron-down" : "chevron-right"} size={12} />
          </button>
        ) : (
          <span className="trace-spacer" />
        )}
        <span className="badge info" title={k.label}>
          <Icon name={k.icon} size={12} /> {k.label}
        </span>
        {link ? (
          <Link to={link} className="mono">
            {n.label}
          </Link>
        ) : (
          <span className="mono">{n.label}</span>
        )}
        {n.item ? <span className="mono faint small">{n.item.part_number}</span> : null}
        {n.qty !== null && n.qty !== undefined ? <span className="small">x {fmtNum(n.qty)}</span> : null}
        {!isRoot ? <PrecisionTag p={n.precision} /> : null}
        {n.status ? <span className="small muted">{n.status.replace(/_/g, " ")}</span> : null}
        {n.location ? <span className="small muted">at {n.location}</span> : null}
        {n.customer ? (
          <span className="small">
            <Icon name="flag" size={12} /> {n.customer}
          </span>
        ) : null}
        {n.at ? <span className="small faint">{new Date(n.at).toLocaleDateString()}</span> : null}
        {n.plant && !n.plant.visible ? <span className="badge info">in plant {n.plant.code}, not visible to you</span> : n.plant ? <span className="badge info">plant {n.plant.code}</span> : null}
        {!isRoot && onRetrace && (n.kind === "serial" || n.kind === "lot" || n.kind === "wo") ? (
          <button type="button" className="btn sm ghost" onClick={() => onRetrace(n)}>
            Trace from here
          </button>
        ) : null}
        {onRecall && canRecall && (n.kind === "lot" || n.kind === "serial") ? (
          <button type="button" className="btn sm ghost" onClick={() => onRecall(n)} data-testid="trace-recall">
            Recall
          </button>
        ) : null}
      </div>
      {kids.length && open ? (
        <ul role="group">
          {kids.map((c, i) => (
            <TreeNode key={`${c.kind}${c.id}${i}`} n={c} level={level + 1} onRetrace={onRetrace} onRecall={onRecall} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** Layered graph: one column per level, solid lines = exact, dashed = possible (with a "?" mark). */
function TraceGraph({ root, dir }: { root: TraceNode; dir: "backward" | "forward" }) {
  const MAX = 400;
  const layout = useMemo(() => {
    const cols: TraceNode[][] = [];
    const pos = new Map<TraceNode, { c: number; r: number }>();
    const edges: { a: TraceNode; b: TraceNode; p: Precision }[] = [];
    let count = 0;
    const walk = (n: TraceNode, d: number) => {
      if (count >= MAX) return;
      count++;
      (cols[d] ??= []).push(n);
      pos.set(n, { c: d, r: cols[d].length - 1 });
      for (const ch of n.children ?? []) {
        if (count >= MAX) break;
        edges.push({ a: n, b: ch, p: ch.precision });
        walk(ch, d + 1);
      }
    };
    walk(root, 0);
    return { cols, pos, edges, cut: count >= MAX };
  }, [root]);
  const W = 190;
  const H = 46;
  const GX = 60;
  const GY = 10;
  const rows = Math.max(...layout.cols.map((c) => c.length));
  const width = layout.cols.length * (W + GX);
  const height = rows * (H + GY) + 10;
  const xy = (n: TraceNode) => {
    const p = layout.pos.get(n)!;
    const colX = dir === "backward" ? (layout.cols.length - 1 - p.c) * (W + GX) : p.c * (W + GX);
    return { x: colX, y: 5 + p.r * (H + GY) };
  };
  return (
    <div className="card trace-graph" data-testid="trace-graph">
      {layout.cut ? <div className="card-body small muted">Only the first {MAX} entries are drawn; use the tree for the rest.</div> : null}
      <div style={{ overflow: "auto", maxHeight: "70vh" }}>
        <svg width={width} height={height} role="img" aria-label={`Trace graph with ${layout.pos.size} entries; solid lines are exact links, dashed lines possible links`}>
          {layout.edges.map((e, i) => {
            const a = xy(e.a);
            const b = xy(e.b);
            const ax = dir === "backward" ? a.x : a.x + W;
            const bx = dir === "backward" ? b.x + W : b.x;
            const ay = a.y + H / 2;
            const by = b.y + H / 2;
            const mx = (ax + bx) / 2;
            return (
              <g key={i}>
                <path d={`M${ax},${ay} C${mx},${ay} ${mx},${by} ${bx},${by}`} fill="none" stroke={e.p === "exact" ? "var(--text-muted)" : "var(--warn)"} strokeWidth={e.p === "exact" ? 1.6 : 1.4} strokeDasharray={e.p === "exact" ? undefined : "5 4"} />
                {e.p === "possible" ? (
                  <text x={mx} y={(ay + by) / 2 - 3} fontSize={11} textAnchor="middle" fill="var(--warn)">
                    ?
                  </text>
                ) : null}
              </g>
            );
          })}
          {[...layout.pos.keys()].map((n, i) => {
            const { x, y } = xy(n);
            return (
              <g key={i} transform={`translate(${x},${y})`}>
                <rect width={W} height={H} rx={6} fill="var(--surface)" stroke={n === root ? "var(--accent)" : "var(--border-strong)"} strokeWidth={n === root ? 2 : 1} />
                <text x={8} y={17} fontSize={11} fill="var(--text-muted)">
                  {(KIND[n.kind]?.label ?? n.kind).toUpperCase()}
                  {n !== root && n.precision === "possible" ? " · possible" : ""}
                </text>
                <text x={8} y={34} fontSize={12} fontFamily="var(--mono)" fill="var(--text)">
                  {n.label.length > 24 ? `${n.label.slice(0, 23)}…` : n.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

export function WhereUsedPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<ItemRef | null>(null);
  const itemId = params.get("item") ?? item?.id ?? "";
  const lot = params.get("lot") ?? "";
  const supplierLot = params.get("supplier_lot") ?? "";
  const [mode, setMode] = useState<"lot" | "supplier">(supplierLot ? "supplier" : "lot");
  const [text, setText] = useState(lot || supplierLot);
  const wu = useLoad((signal) => (itemId && (lot || supplierLot) ? getWhereUsed({ item_id: itemId, lot_code: lot || undefined, supplier_lot: supplierLot || undefined }, signal) : null), [itemId, lot, supplierLot]);
  const go = (e: FormEvent) => {
    e.preventDefault();
    if (!itemId || !text.trim()) return;
    setParams(() => {
      const n = new URLSearchParams();
      n.set("item", itemId);
      n.set(mode === "lot" ? "lot" : "supplier_lot", text.trim());
      return n;
    });
  };
  const d = wu.data;
  const root: TraceNode | null = d ? { kind: "lot", id: "", item: item, label: lot || supplierLot, qty: null, precision: "exact", at: null, children: d.items } : null;
  let result: ReactNode = null;
  if (d && root)
    result = (
      <>
        <p className="small muted" style={{ margin: 0 }} data-testid="whereused-count">
          {d.items.length} use{d.items.length === 1 ? "" : "s"} found{d.truncated ? " (list cut short)" : ""}.
        </p>
        {d.items.length ? (
          <TraceTree root={root} showRoot={false} onRetrace={(n) => navigate(mfgPaths.trace({ kind: n.kind, id: n.id, dir: "forward", label: n.label }))} onRecall={(n) => navigate(`${mfgPaths.recalls()}?new=1&kind=${n.kind}&id=${encodeURIComponent(n.id)}&label=${encodeURIComponent(n.label)}`)} />
        ) : (
          <p className="muted">Not used yet.</p>
        )}
        <div>
          <Link className="btn" to={`${mfgPaths.recalls()}?new=1&item=${encodeURIComponent(itemId)}&supplier_lot=${encodeURIComponent(supplierLot || lot)}&label=${encodeURIComponent(`${item?.part_number ?? ""} ${supplierLot || lot}`.trim())}`} data-testid="whereused-recall">
            <Icon name="alert" /> Start a recall for this lot
          </Link>
        </div>
      </>
    );
  return (
    <div className="col gap-lg" data-testid="whereused-page">
      <div className="mfg-page-head">
        <div>
          <h1>Traceability</h1>
          <p>Which work orders, units and shipments used a lot.</p>
        </div>
      </div>
      <TraceTabs />
      <form className="toolbar mfg-filters" onSubmit={go}>
        <div className="field" style={{ minWidth: 280 }}>
          <ItemPicker value={item} onChange={setItem} label="Item" />
        </div>
        <div className="field">
          <label htmlFor="wu-mode">Lot number from</label>
          <select id="wu-mode" className="select" value={mode} onChange={(e) => setMode(e.target.value as "lot" | "supplier")}>
            <option value="lot">Our lot code</option>
            <option value="supplier">The supplier's lot</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="wu-lot">Lot</label>
          <input id="wu-lot" className="input mono" value={text} onChange={(e) => setText(e.target.value)} data-testid="whereused-lot" />
        </div>
        <button type="submit" className="btn primary" style={{ alignSelf: "flex-end" }} disabled={!itemId || !text.trim()} data-testid="whereused-go">
          <Icon name="zoom-in" /> Find
        </button>
      </form>
      <MfgError error={wu.error} onRetry={wu.reload} />
      {wu.loading && itemId && (lot || supplierLot) && !d ? <Spinner /> : null}
      {result}
    </div>
  );
}
