/**
 * Indented BOM tree on `VirtualTable` (M 11.2, 11.4): the full explosion is one array; collapse state is a
 * `Set<number>` of row indices and `visibleRows` skips collapsed subtrees via `subtree_end`. Default: expanded
 * to level 2. Search highlights matches and expands their ancestors. Keyboard: Up/Down move, Right expands
 * (or goes to the first child), Left collapses (or goes to the parent), Enter opens the item.
 */
import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import type { ExplosionRow } from "../api/types";
import { fmtQty } from "../lib/format";
import { mfgPaths } from "../lib/paths";
import { collapseAll, collapseToLevel, revealAll, revealRow, searchRows, visibleRows } from "../lib/tree";
import { MakeBuyBadge } from "./StatusChip";
import { VirtualTable, type Column } from "./VirtualTable";

export interface BomTreeProps {
  rows: ExplosionRow[];
  /** `?line=`: select and reveal the row brought in by this BOM line. */
  selectLineId?: string | null;
  height?: string;
}

export function BomTree({ rows, selectLineId, height }: BomTreeProps) {
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState<Set<number>>(() => collapseToLevel(rows, 2));
  const [activeRow, setActiveRow] = useState(0);
  const [pending, setPending] = useState<number | null>(null);
  const [scrollTo, setScrollTo] = useState<{ index: number; seq: number } | null>(null);
  const [q, setQ] = useState("");
  const [matchPos, setMatchPos] = useState(0);
  const [jumped, setJumped] = useState(false);
  const [alts, setAlts] = useState<ExplosionRow | null>(null);
  const maxLevel = useMemo(() => rows.reduce((m, r) => Math.max(m, r.level), 0), [rows]);

  // New data (other item / date / qty): reset to the default view.
  useEffect(() => {
    setCollapsed(collapseToLevel(rows, 2));
    setActiveRow(0);
  }, [rows]);

  useEffect(() => {
    if (!selectLineId) return;
    const target = rows.find((r) => r.line_id === selectLineId);
    if (!target) return;
    setCollapsed((c) => revealRow(rows, c, target.row));
    setActiveRow(target.row);
    setPending(target.row);
  }, [rows, selectLineId]);

  const vis = useMemo(() => visibleRows(rows, collapsed), [rows, collapsed]);
  const visRows = useMemo(() => vis.map((i) => rows[i]), [vis, rows]);
  const posOf = useMemo(() => {
    const m = new Map<number, number>();
    vis.forEach((r, i) => m.set(r, i));
    return m;
  }, [vis]);

  useEffect(() => {
    if (pending === null) return;
    const idx = posOf.get(pending);
    if (idx !== undefined) {
      setScrollTo({ index: idx, seq: Date.now() });
      setPending(null);
    }
  }, [pending, posOf]);

  const matches = useMemo(() => searchRows(rows, q), [rows, q]);
  const matchSet = useMemo(() => new Set(matches), [matches]);

  const goToMatch = (pos: number) => {
    if (!matches.length) return;
    const p = ((pos % matches.length) + matches.length) % matches.length;
    setJumped(true);
    setMatchPos(p);
    const r = matches[p];
    setCollapsed((c) => revealRow(rows, c, r));
    setActiveRow(r);
    setPending(r);
  };

  const toggle = (r: ExplosionRow) => {
    if (!r.has_children) return;
    setCollapsed((c) => {
      const next = new Set(c);
      if (next.has(r.row)) next.delete(r.row);
      else next.add(r.row);
      return next;
    });
  };

  const onRowKey = (e: KeyboardEvent<HTMLDivElement>, r: ExplosionRow) => {
    if (e.key === "ArrowRight") {
      if (r.has_children && collapsed.has(r.row)) toggle(r);
      else if (r.has_children) {
        setActiveRow(r.row + 1);
        setPending(r.row + 1);
      }
      return true;
    }
    if (e.key === "ArrowLeft") {
      if (r.has_children && !collapsed.has(r.row)) toggle(r);
      else if (r.parent_row !== null) {
        setActiveRow(r.parent_row);
        setPending(r.parent_row);
      }
      return true;
    }
    return false;
  };

  const columns: Column<ExplosionRow>[] = [
    { key: "fn", header: "Find no.", width: "64px", render: (r) => <span className="mono">{r.find_number ?? ""}</span> },
    {
      key: "pn",
      header: "Part number",
      width: "minmax(240px, 1.4fr)",
      render: (r) => (
        <span className="mfg-tree-cell" style={{ paddingLeft: r.level * 18 }}>
          {r.has_children ? (
            <button
              type="button"
              className="mfg-chevron"
              tabIndex={-1}
              aria-label={collapsed.has(r.row) ? `Expand ${r.part_number}` : `Collapse ${r.part_number}`}
              onClick={(e) => {
                e.stopPropagation();
                toggle(r);
              }}
            >
              <Icon name={collapsed.has(r.row) ? "chevron-right" : "chevron-down"} size={14} />
            </button>
          ) : (
            <span className="mfg-chevron-space" aria-hidden />
          )}
          <Link to={mfgPaths.item(r.item_id)} className={`mono mfg-ellipsis${matchSet.has(r.row) ? " mfg-match" : ""}`} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {r.part_number}
          </Link>
          {r.is_phantom ? (
            <span className="chip" title="Phantom: never stocked, its parts are used directly">
              <Icon name="layers" size={12} /> Phantom
            </span>
          ) : null}
          {r.is_shared ? (
            <span className="chip" title="Used under more than one parent in this structure">
              <Icon name="copy" size={12} /> Shared
            </span>
          ) : null}
          {!r.active ? (
            <span className="badge warn" title="Inactive item">
              <Icon name="ban" /> Inactive
            </span>
          ) : null}
        </span>
      ),
    },
    { key: "desc", header: "Description", width: "minmax(180px, 1.4fr)", render: (r) => <span className="mfg-ellipsis">{r.description}</span> },
    { key: "qty", header: "Qty per", width: "76px", align: "right", render: (r) => fmtQty(r.qty_per) },
    { key: "uom", header: "Unit", width: "50px", render: (r) => r.line_uom ?? r.uom },
    { key: "scrap", header: "Scrap %", width: "64px", align: "right", render: (r) => (r.scrap_pct ? fmtQty(r.scrap_pct) : "") },
    {
      key: "ext",
      header: "Total qty",
      label: "Total quantity needed, in the item's unit",
      width: "112px",
      align: "right",
      render: (r) => (
        <span title={`${fmtQty(r.extended_qty)} ${r.uom} needed in total`} data-value={r.extended_qty}>
          {fmtQty(r.extended_qty)} <span className="faint">{r.uom}</span>
        </span>
      ),
    },
    { key: "mb", header: "Make / buy", width: "100px", render: (r) => <MakeBuyBadge value={r.make_buy} /> },
    { key: "lt", header: "Lead time", width: "76px", align: "right", render: (r) => (r.lead_time_days === null ? "" : `${r.lead_time_days} d`) },
    {
      key: "ref",
      header: "Ref. des.",
      width: "minmax(100px, 0.8fr)",
      render: (r) => (
        <span className="row" style={{ gap: 4, minWidth: 0 }}>
          <span className="mfg-ellipsis small" title={r.ref_designators}>
            {r.ref_designators}
          </span>
          {r.alternates.length ? (
            <button
              type="button"
              className="btn sm ghost"
              tabIndex={-1}
              onClick={(e) => {
                e.stopPropagation();
                setAlts(r);
              }}
              data-testid="bom-alternates"
            >
              +{r.alternates.length} alt.
            </button>
          ) : null}
        </span>
      ),
    },
  ];

  const levelOptions = Array.from({ length: Math.max(1, maxLevel) }, (_, i) => i + 1);
  const activeIndex = posOf.get(activeRow) ?? 0;

  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <button type="button" className="btn sm" onClick={() => setCollapsed(new Set())} data-testid="bom-expand-all">
          <Icon name="chevron-down" /> Expand all
        </button>
        <button type="button" className="btn sm" onClick={() => setCollapsed(collapseAll(rows))} data-testid="bom-collapse-all">
          <Icon name="chevron-right" /> Collapse all
        </button>
        <label className="row small">
          <span className="muted">Show levels</span>
          <select
            className="select sm"
            style={{ width: 70 }}
            value=""
            onChange={(e) => e.target.value && setCollapsed(collapseToLevel(rows, Number(e.target.value)))}
            data-testid="bom-expand-level"
          >
            <option value="">…</option>
            {levelOptions.map((l) => (
              <option key={l} value={l}>
                0-{l}
              </option>
            ))}
          </select>
        </label>
        <span className="grow" />
        <div className="row" role="search">
          <input
            className="input sm"
            type="search"
            style={{ width: 220 }}
            placeholder="Find part number or description"
            aria-label="Find in structure"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setMatchPos(0);
              setJumped(false);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (!matches.length) return;
                if (!jumped) {
                  setCollapsed((c) => revealAll(rows, c, matches));
                  setJumped(true);
                  goToMatch(0);
                } else goToMatch(matchPos + (e.shiftKey ? -1 : 1));
              }
            }}
            data-testid="bom-search"
          />
          {q ? (
            <span className="small muted" role="status" aria-live="polite">
              {matches.length ? `${matchPos + 1} of ${matches.length}` : "No match"}
            </span>
          ) : null}
          <button type="button" className="btn sm icon" aria-label="Previous match" disabled={!matches.length} onClick={() => goToMatch(matchPos - 1)}>
            <Icon name="chevron-right" style={{ transform: "rotate(-90deg)" }} />
          </button>
          <button type="button" className="btn sm icon" aria-label="Next match" disabled={!matches.length} onClick={() => goToMatch(matchPos + 1)}>
            <Icon name="chevron-down" />
          </button>
        </div>
      </div>
      <VirtualTable
        rows={visRows}
        columns={columns}
        rowKey={(r) => r.row}
        label="BOM structure"
        role="treegrid"
        testId="bom-tree"
        height={height}
        totalCount={visRows.length}
        activeIndex={activeIndex}
        onActiveChange={(i) => setActiveRow(vis[i] ?? 0)}
        scrollTo={scrollTo}
        onRowKey={onRowKey}
        onActivate={(r) => navigate(mfgPaths.item(r.item_id))}
        rowExtras={(r) => ({
          testId: "bom-tree-row",
          data: { row: r.row, level: r.level, "part-number": r.part_number, "line-id": r.line_id ?? undefined },
          ariaLevel: r.level + 1,
          ariaExpanded: r.has_children ? !collapsed.has(r.row) : undefined,
          ariaSelected: r.line_id !== null && r.line_id === selectLineId,
          className: [
            r.line_id !== null && r.line_id === selectLineId ? "mfg-selected" : "",
            matchSet.has(r.row) ? "mfg-match-row" : "",
            r.active ? "" : "mfg-inactive",
          ]
            .filter(Boolean)
            .join(" "),
        })}
        footer={
          <span className="small muted" role="status">
            {vis.length.toLocaleString()} of {rows.length.toLocaleString()} rows shown
          </span>
        }
      />
      {alts ? (
        <Dialog
          title={`Alternatives for ${alts.part_number}`}
          onClose={() => setAlts(null)}
          footer={
            <button type="button" className="btn" onClick={() => setAlts(null)} data-dialog-close>
              Close
            </button>
          }
        >
          <p className="muted small" style={{ margin: 0 }}>
            Quantities use the primary part. Alternatives can replace it, in this order of preference.
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>Priority</th>
                <th>Part number</th>
                <th className="num">Qty per</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>1 (primary)</td>
                <td className="mono">{alts.part_number}</td>
                <td className="num">{fmtQty(alts.qty_per)}</td>
                <td>{alts.line_uom}</td>
              </tr>
              {alts.alternates.map((a) => (
                <tr key={a.line_id}>
                  <td>{a.alt_priority}</td>
                  <td className="mono">
                    <Link to={mfgPaths.item(a.item_id)}>{a.part_number}</Link>
                  </td>
                  <td className="num">{fmtQty(a.qty_per)}</td>
                  <td>{a.line_uom}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Dialog>
      ) : null}
    </div>
  );
}
