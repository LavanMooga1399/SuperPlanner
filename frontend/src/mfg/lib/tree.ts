/**
 * BOM tree helpers over the indented explosion (M 11.2 `lib/tree.ts`, 11.4). Rows are depth-first with
 * `subtree_end` = first row after the subtree, so a collapsed row skips its subtree in O(1).
 */
import type { ExplosionRow } from "../api/types";

/** Indices of visible rows: O(visible rows + collapsed count). */
export function visibleRows(rows: readonly ExplosionRow[], collapsed: ReadonlySet<number>): number[] {
  const out: number[] = [];
  let i = 0;
  const n = rows.length;
  while (i < n) {
    out.push(i);
    const r = rows[i];
    if (r.has_children && collapsed.has(i)) {
      i = r.subtree_end > i ? r.subtree_end : i + 1;
    } else {
      i++;
    }
  }
  return out;
}

/** Collapse set showing levels 0..level (rows at `level` with children are collapsed). */
export function collapseToLevel(rows: readonly ExplosionRow[], level: number): Set<number> {
  const s = new Set<number>();
  for (const r of rows) if (r.has_children && r.level >= level) s.add(r.row);
  return s;
}

/** Every row with children collapsed (only the root stays open so its children show). */
export function collapseAll(rows: readonly ExplosionRow[]): Set<number> {
  return collapseToLevel(rows, 1);
}

/** Remove every ancestor of `row` from the collapse set (returns a new set when something changed). */
export function revealRow(rows: readonly ExplosionRow[], collapsed: ReadonlySet<number>, row: number): Set<number> {
  const next = new Set(collapsed);
  let p = rows[row]?.parent_row ?? null;
  while (p !== null) {
    next.delete(p);
    p = rows[p]?.parent_row ?? null;
  }
  return next;
}

/** Rows whose part number, description or reference designators contain `q` (case-insensitive). */
export function searchRows(rows: readonly ExplosionRow[], q: string): number[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return [];
  const out: number[] = [];
  for (const r of rows) {
    if (
      r.part_number.toLowerCase().includes(needle) ||
      r.description.toLowerCase().includes(needle) ||
      (r.find_number ?? "").toLowerCase() === needle
    )
      out.push(r.row);
  }
  return out;
}

/** Reveal every match (expands all their ancestors). */
export function revealAll(rows: readonly ExplosionRow[], collapsed: ReadonlySet<number>, matches: number[]): Set<number> {
  const next = new Set(collapsed);
  for (const m of matches) {
    let p = rows[m]?.parent_row ?? null;
    while (p !== null) {
      next.delete(p);
      p = rows[p]?.parent_row ?? null;
    }
  }
  return next;
}
