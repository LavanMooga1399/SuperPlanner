/**
 * Pegging tree (M2 14.2 `PeggingTree`, 8.13): rows depth-first from the server (up: supply -> requirements ->
 * parent orders -> demand; down: requirement -> supplies -> components), on `VirtualTable` as a treegrid with
 * indentation, collapse/expand (Left/Right), late badges and server-built links.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import type { PeggingRow } from "../api/typesM2";
import { fmtDate } from "../lib/format";
import { fmtNum } from "../lib/formatM2";
import { LateBadge } from "./StatusM2";
import { VirtualTable, type Column } from "./VirtualTable";

export function PeggingTree({ rows, onPeg }: { rows: PeggingRow[]; onPeg?(r: PeggingRow): void }) {
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  const hasKids = useMemo(() => {
    const s = new Set<number>();
    rows.forEach((r, i) => {
      if (i + 1 < rows.length && rows[i + 1].level > r.level) s.add(r.row);
    });
    return s;
  }, [rows]);
  const visible = useMemo(() => {
    const out: PeggingRow[] = [];
    let skipBelow: number | null = null;
    for (const r of rows) {
      if (skipBelow !== null) {
        if (r.level > skipBelow) continue;
        skipBelow = null;
      }
      out.push(r);
      if (collapsed.has(r.row)) skipBelow = r.level;
    }
    return out;
  }, [rows, collapsed]);
  const toggle = (row: number, open?: boolean) =>
    setCollapsed((s) => {
      const n = new Set(s);
      const isOpen = !n.has(row);
      if (open === undefined ? isOpen : !open) n.add(row);
      else n.delete(row);
      return n;
    });

  const columns: Column<PeggingRow>[] = [
    {
      key: "item",
      header: "Item / order",
      width: "minmax(320px, 2.4fr)",
      render: (r) => (
        <span className="mfg-tree-cell" style={{ paddingLeft: r.level * 18 }}>
          {hasKids.has(r.row) ? (
            <button type="button" className="mfg-chevron" tabIndex={-1} aria-label={collapsed.has(r.row) ? "Expand" : "Collapse"} onClick={(e) => (e.stopPropagation(), toggle(r.row))}>
              <Icon name={collapsed.has(r.row) ? "chevron-right" : "chevron-down"} size={14} />
            </button>
          ) : (
            <span className="mfg-chevron-space" />
          )}
          <span className="mono">{r.item.part_number}</span>
          <span className="muted mfg-ellipsis">{r.label}</span>
        </span>
      ),
    },
    { key: "kind", header: "Kind", width: "130px", render: (r) => <span className="small mfg-ellipsis">{r.kind.replace(/_/g, " ")}</span> },
    { key: "qty", header: "Pegged qty", width: "96px", align: "right", render: (r) => `${fmtNum(r.qty)} ${r.item.uom}` },
    { key: "date", header: "Needed / available", width: "130px", render: (r) => fmtDate(r.date) },
    { key: "proj", header: "Projected", width: "110px", render: (r) => fmtDate(r.projected_date) },
    { key: "late", header: "Late", width: "90px", render: (r) => <LateBadge days={r.late_days} /> },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      label: "Actions",
      width: "150px",
      render: (r) => (
        <span className="row" style={{ gap: 4 }}>
          {r.link ? (
            <Link to={r.link} className="btn sm ghost" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
              Open
            </Link>
          ) : null}
          {onPeg ? (
            <button type="button" className="btn sm ghost" tabIndex={-1} onClick={(e) => (e.stopPropagation(), onPeg(r))} title="Peg from this row">
              <Icon name="graph" />
            </button>
          ) : null}
        </span>
      ),
    },
  ];
  return (
    <VirtualTable
      rows={visible}
      columns={columns}
      role="treegrid"
      rowKey={(r) => r.row}
      label="Pegging"
      testId="pegging-tree"
      height="min(66vh, 720px)"
      rowExtras={(r) => ({
        testId: "peg-row",
        data: { level: r.level, item: r.item.part_number, "late-days": r.late_days },
        ariaLevel: r.level + 1,
        ariaExpanded: hasKids.has(r.row) ? !collapsed.has(r.row) : undefined,
      })}
      onRowKey={(e, r) => {
        if (!hasKids.has(r.row)) return false;
        if (e.key === "ArrowLeft") toggle(r.row, false);
        else if (e.key === "ArrowRight") toggle(r.row, true);
        else return false;
        return true;
      }}
      empty="Nothing is pegged to this."
      footer={<span className="muted small">{visible.length.toLocaleString()} of {rows.length.toLocaleString()} rows · Left/Right collapse and expand</span>}
    />
  );
}
