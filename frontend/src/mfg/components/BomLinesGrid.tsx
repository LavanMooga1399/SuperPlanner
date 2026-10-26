/**
 * Editable single-level BOM line grid (M 11.2): plain table up to 100 lines, `VirtualTable` above that.
 * Add / duplicate / delete rows; picking a component fills its unit (see `uomAfterChildChange`). Rows with errors (client checks or the
 * server's `loc: ["body","lines",i,...]`) are marked and described in text.
 */
import { useMemo, type ReactNode } from "react";
import { Icon } from "../../components/Icon";
import type { ItemRef } from "../api/types";
import { useMeta } from "../lib/useMfg";
import { ItemPicker } from "./ItemPicker";
import { VirtualTable, type Column } from "./VirtualTable";

export interface LineDraft {
  key: string;
  id: string | null;
  find_number: string;
  child: ItemRef | null;
  qty_per: string;
  uom: string;
  scrap_pct: string;
  ref_designators: string;
  alt_group: string;
  alt_priority: string;
  operation_seq: string;
  note: string;
}

let keySeq = 0;
export const newKey = () => `k${++keySeq}`;

export function nextFindNumber(lines: LineDraft[]): string {
  let max = 0;
  for (const l of lines) if (/^\d+$/.test(l.find_number)) max = Math.max(max, Number(l.find_number));
  return String(Math.floor(max / 10) * 10 + 10);
}

export function blankLine(lines: LineDraft[]): LineDraft {
  return {
    key: newKey(),
    id: null,
    find_number: nextFindNumber(lines),
    child: null,
    qty_per: "1",
    uom: "",
    scrap_pct: "0",
    ref_designators: "",
    alt_group: "",
    alt_priority: "1",
    operation_seq: "",
    note: "",
  };
}

/**
 * The unit of a line after its component is replaced. A unit the user chose explicitly (different from the old
 * component's own unit) is kept only when it measures the same dimension as the new component's unit (e.g. M vs MM);
 * otherwise the line takes the new component's unit, so an EA line switched to a cable sold in M becomes M.
 */
export function uomAfterChildChange(line: Pick<LineDraft, "uom" | "child">, next: Pick<ItemRef, "uom">, dimensionOf: (uom: string) => string | undefined): string {
  const explicit = Boolean(line.uom) && Boolean(line.child) && line.uom !== line.child?.uom;
  if (!explicit) return next.uom;
  const a = dimensionOf(line.uom);
  const b = dimensionOf(next.uom);
  return a !== undefined && a === b ? line.uom : next.uom;
}

/** Client-side checks per line (empty = fine). */
export function lineProblems(l: LineDraft): string[] {
  const p: string[] = [];
  if (!l.find_number.trim()) p.push("Find number is required");
  if (!l.child) p.push("Pick a component");
  const q = Number(l.qty_per);
  if (!l.qty_per.trim() || !Number.isFinite(q) || q <= 0) p.push("Quantity must be more than 0");
  const s = Number(l.scrap_pct || "0");
  if (!Number.isFinite(s) || s < 0 || s >= 100) p.push("Scrap must be 0 to 99.9 %");
  return p;
}

export function BomLinesGrid({
  lines,
  onChange,
  readOnly,
  parentId,
  uoms,
  selectedLineId,
  serverErrors,
  scrollTo,
}: {
  lines: LineDraft[];
  onChange(next: LineDraft[]): void;
  readOnly: boolean;
  parentId: string;
  uoms: string[];
  selectedLineId: string | null;
  serverErrors: Map<number, string[]>;
  scrollTo: { index: number; seq: number } | null;
}) {
  const meta = useMeta();
  const dimensions = useMemo(() => new Map(meta?.uoms.map((u) => [u.code, u.dimension]) ?? []), [meta]);
  const update = (i: number, patch: Partial<LineDraft>) => onChange(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const remove = (i: number) => onChange(lines.filter((_, j) => j !== i));
  const duplicate = (i: number) => {
    const copy = { ...lines[i], key: newKey(), id: null, find_number: nextFindNumber(lines) };
    onChange([...lines.slice(0, i + 1), copy, ...lines.slice(i + 1)]);
  };

  const cell = (i: number, field: keyof LineDraft, label: string, width: number, type: "text" | "number" = "text"): ReactNode => (
    <input
      className="input sm"
      type={type}
      step={type === "number" ? "any" : undefined}
      style={{ width }}
      aria-label={`${label}, line ${i + 1}`}
      value={String(lines[i][field] ?? "")}
      readOnly={readOnly}
      data-testid={`bom-line-${field}`}
      onChange={(e) => update(i, { [field]: e.target.value })}
    />
  );

  const columns: Column<LineDraft>[] = useMemo(
    () => [
      { key: "fn", header: "Find no.", width: "76px", render: (_l, i) => cell(i, "find_number", "Find number", 62) },
      {
        key: "child",
        header: "Component",
        width: "minmax(190px, 1.2fr)",
        render: (l, i) =>
          readOnly ? (
            <span className="mono">{l.child?.part_number}</span>
          ) : (
            <ItemPicker
              value={l.child}
              label={`Component, line ${i + 1}`}
              hideLabel
              excludeId={parentId}
              testId="bom-line-child"
              onChange={(it) => update(i, { child: it, uom: uomAfterChildChange(l, it, (u) => dimensions.get(u)) })}
            />
          ),
      },
      { key: "desc", header: "Description", width: "minmax(140px, 1fr)", render: (l) => <span className="mfg-ellipsis small muted">{l.child?.description ?? ""}</span> },
      { key: "qty", header: "Qty per", width: "86px", render: (_l, i) => cell(i, "qty_per", "Quantity per", 72, "number") },
      {
        key: "uom",
        header: "Unit",
        width: "76px",
        render: (l, i) => (
          <select className="select sm" aria-label={`Unit, line ${i + 1}`} value={l.uom} disabled={readOnly} onChange={(e) => update(i, { uom: e.target.value })} style={{ width: 66 }}>
            <option value="">{l.child?.uom ?? "-"}</option>
            {uoms.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        ),
      },
      { key: "scrap", header: "Scrap %", width: "72px", render: (_l, i) => cell(i, "scrap_pct", "Scrap percent", 58, "number") },
      { key: "ref", header: "Ref. des.", width: "minmax(110px, 0.8fr)", render: (_l, i) => cell(i, "ref_designators", "Reference designators", 160) },
      { key: "ag", header: "Alt. group", width: "80px", render: (_l, i) => cell(i, "alt_group", "Alternate group", 66) },
      { key: "ap", header: "Alt. prio", width: "70px", render: (_l, i) => cell(i, "alt_priority", "Alternate priority", 56, "number") },
      { key: "op", header: "At op.", width: "70px", render: (_l, i) => cell(i, "operation_seq", "Consumed at operation", 56, "number") },
      { key: "note", header: "Note", width: "minmax(100px, 0.6fr)", render: (_l, i) => cell(i, "note", "Note", 140) },
      {
        key: "act",
        header: <span className="sr-only">Actions</span>,
        label: "Actions",
        width: "72px",
        render: (_l, i) =>
          readOnly ? null : (
            <span className="row" style={{ gap: 2 }}>
              <button type="button" className="btn sm ghost icon" aria-label={`Duplicate line ${i + 1}`} title="Duplicate" onClick={() => duplicate(i)}>
                <Icon name="copy" />
              </button>
              <button type="button" className="btn sm ghost icon" aria-label={`Delete line ${i + 1}`} title="Delete" onClick={() => remove(i)} data-testid="bom-line-delete">
                <Icon name="trash" />
              </button>
            </span>
          ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [lines, readOnly, parentId, uoms, dimensions],
  );

  const extras = (l: LineDraft, i: number) => {
    const probs = [...(l.child || l.qty_per !== "1" ? lineProblems(l) : []), ...(serverErrors.get(i) ?? [])];
    return {
      testId: "bom-line-row",
      data: { "line-id": l.id ?? undefined, index: i },
      className: [l.id && l.id === selectedLineId ? "mfg-selected" : "", probs.length ? "mfg-row-error" : ""].filter(Boolean).join(" "),
      title: probs.join("; ") || undefined,
      ariaSelected: Boolean(l.id && l.id === selectedLineId),
    };
  };

  return (
    <VirtualTable
      rows={lines}
      columns={columns}
      rowKey={(l) => l.key}
      label="BOM lines"
      testId="bom-lines-grid"
      height={lines.length > 100 ? "min(60vh, 640px)" : "100000px"}
      rowExtras={extras}
      scrollTo={scrollTo}
      empty={readOnly ? "No lines." : "No lines yet. Add the first component below."}
    />
  );
}
