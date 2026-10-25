/** Import wizard helpers (M 11.5): initial mapping, re-applying a mapping by header names, checks, CSV of errors. */
import type { ImportMappingRequest, ImportOptions, ImportRecord, ImportSheet, ImportSheetSpec, RowError, SheetMapping } from "../api/types";

export const DEFAULT_OPTIONS: ImportOptions = { replace_children: true, release: false, default_effective_from: null };

function emptyMapping(sheet: ImportSheet): SheetMapping {
  return { target: null, columns: Object.fromEntries(sheet.headers.map((h) => [h, null])) };
}

/** Mapping to show in the Map step: the stored one, else the server's suggestion, else nothing mapped. */
export function initialMapping(rec: ImportRecord): ImportMappingRequest {
  const sheets: Record<string, SheetMapping> = {};
  for (const s of rec.sheets) {
    const stored = rec.mapping?.sheets[s.name];
    const base = stored ?? s.suggested ?? emptyMapping(s);
    sheets[s.name] = { target: base.target, columns: Object.fromEntries(s.headers.map((h) => [h, base.columns[h] ?? null])) };
  }
  return { sheets, options: rec.mapping?.options ?? { ...DEFAULT_OPTIONS } };
}

/**
 * "Fix the file and upload again" (M 11.5): carry the previous mapping over to a new upload by header names.
 * A new sheet takes the old sheet with the same name, else the old sheet sharing the most headers; columns are
 * matched by exact header text. Unmatched sheets keep the new server suggestion.
 */
export function remapByHeaders(prev: ImportMappingRequest, prevSheets: ImportSheet[], next: ImportRecord): ImportMappingRequest {
  const base = initialMapping({ ...next, mapping: null });
  const sheets: Record<string, SheetMapping> = {};
  for (const s of next.sheets) {
    let source: SheetMapping | undefined = prev.sheets[s.name];
    if (!source) {
      let best = 0;
      for (const ps of prevSheets) {
        const overlap = ps.headers.filter((h) => s.headers.includes(h)).length;
        if (overlap > best && prev.sheets[ps.name]) {
          best = overlap;
          source = prev.sheets[ps.name];
        }
      }
    }
    if (!source) {
      sheets[s.name] = base.sheets[s.name];
      continue;
    }
    const cols: Record<string, string | null> = {};
    for (const h of s.headers) cols[h] = h in source.columns ? source.columns[h] : base.sheets[s.name].columns[h] ?? null;
    sheets[s.name] = { target: source.target, columns: cols };
  }
  return { sheets, options: prev.options };
}

export interface MappingCheck {
  duplicates: string[];
  missingRequired: string[];
}

/** Two source columns mapped to one field (the server answers 422) and required fields left unmapped (hint only). */
export function checkSheet(mapping: SheetMapping, spec: ImportSheetSpec | undefined): MappingCheck {
  const seen = new Map<string, number>();
  for (const f of Object.values(mapping.columns)) if (f) seen.set(f, (seen.get(f) ?? 0) + 1);
  const duplicates = [...seen.entries()].filter(([, n]) => n > 1).map(([f]) => f);
  const mapped = new Set(seen.keys());
  const missingRequired = spec ? spec.columns.filter((c) => c.required_on_create && !mapped.has(c.field)).map((c) => c.field) : [];
  return { duplicates, missingRequired };
}

function csvCell(v: string | number | null): string {
  const s = v === null ? "" : String(v);
  const guarded = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\r\n]/.test(guarded) ? `"${guarded.replace(/"/g, '""')}"` : guarded;
}

/** Row errors as CSV (client-side "Download errors as CSV"). */
export function rowErrorsCsv(errors: RowError[]): string {
  const lines = [["sheet", "row", "column", "code", "message"].join(",")];
  for (const e of errors) lines.push([e.sheet, e.row, e.column, e.code, e.message].map(csvCell).join(","));
  return `${lines.join("\r\n")}\r\n`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
