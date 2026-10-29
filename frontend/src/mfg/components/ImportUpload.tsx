/**
 * Step 1 Upload (M 11.5): file input / drop zone (xlsx, csv, zip), size shown and checked against the server's
 * `max_body_bytes` from `/meta`; for a single CSV the target sheet is chosen. The raw bytes are POSTed as
 * `application/octet-stream`.
 */
import { useState, type DragEvent } from "react";
import { Icon } from "../../components/Icon";
import { uploadImport } from "../api/client";
import type { ImportRecord } from "../api/types";
import { fmtBytes } from "../lib/importMapping";
import { useMeta } from "../lib/useMfg";
import { MfgError } from "./Feedback";

const SHEET_LABEL: Record<string, string> = {
  plant: "Plant settings",
  items: "Items",
  skills: "Skills",
  tool_pools: "Tooling",
  groups: "Stages",
  lines: "Lines",
  shift_templates: "Shift templates",
  shifts: "Shifts",
  shift_assignments: "Shift assignments",
  calendar_exceptions: "Holidays and maintenance",
  operators: "Operators",
  boms: "BOM headers",
  bom_lines: "BOM lines",
  routings: "Routing headers",
  operations: "Operations",
  locations: "Stores locations",
  suppliers: "Suppliers",
  item_suppliers: "Suppliers per part",
  stock: "Stock on hand",
  purchase_docs: "Purchase orders / requests",
  purchase_lines: "Purchase lines",
  purchase_schedules: "Purchase deliveries",
  demand_orders: "Demand orders",
  demand_lines: "Demand lines",
  work_orders: "Work orders",
  wo_components: "Work order components",
};

/** M2 11: what kind of data a sheet is, and which permission a commit with it needs (shown per card). */
export const SHEET_KIND: Record<string, { label: string; perm: string }> = {
  locations: { label: "Master data", perm: "Planner" },
  suppliers: { label: "Master data", perm: "Planner or Purchaser" },
  item_suppliers: { label: "Master data", perm: "Planner or Purchaser" },
  stock: { label: "Stock (posted as a count)", perm: "Store keeper" },
  purchase_docs: { label: "Purchasing", perm: "Purchaser (orders) or Planner (requests)" },
  purchase_lines: { label: "Purchasing", perm: "Purchaser (orders) or Planner (requests)" },
  purchase_schedules: { label: "Purchasing", perm: "Purchaser (orders) or Planner (requests)" },
  demand_orders: { label: "Demand", perm: "Planner" },
  demand_lines: { label: "Demand", perm: "Planner" },
  work_orders: { label: "Work orders", perm: "Planner" },
  wo_components: { label: "Work orders", perm: "Planner" },
};

export function sheetKind(name: string | null): { label: string; perm: string } {
  return (name && SHEET_KIND[name]) || { label: "Master data", perm: "Planner" };
}

export function sheetLabel(name: string): string {
  return SHEET_LABEL[name] ?? name;
}

export function ImportUpload({ onUploaded, reuseNote }: { onUploaded(rec: ImportRecord): Promise<void> | void; reuseNote?: string | null }) {
  const meta = useMeta();
  const [file, setFile] = useState<File | null>(null);
  const [sheet, setSheet] = useState("bom_lines");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [over, setOver] = useState(false);
  const limit = meta?.limits.max_body_bytes ?? null;
  const tooBig = file !== null && limit !== null && file.size > limit;
  const isCsv = file !== null && /\.(csv|txt)$/i.test(file.name);
  const sheets = meta?.import_spec.sheets.map((s) => s.name) ?? Object.keys(SHEET_LABEL);

  const pick = (f: File | null) => {
    setFile(f);
    setError(null);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    pick(e.dataTransfer.files[0] ?? null);
  };
  const upload = async () => {
    if (!file || tooBig) return;
    setBusy(true);
    setError(null);
    try {
      const rec = await uploadImport(file, file.name.slice(0, 200), isCsv ? sheet : undefined);
      await onUploaded(rec);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card" aria-labelledby="imp-up-title" data-testid="import-upload">
      <div className="card-header">
        <h2 id="imp-up-title">1. Choose a file</h2>
      </div>
      <div className="card-body col">
        {reuseNote ? (
          <p className="small" style={{ margin: 0 }} role="status">
            <Icon name="info" size={12} /> {reuseNote}
          </p>
        ) : null}
        <label
          className={`mfg-drop${over ? " over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
        >
          <Icon name="upload" size={28} />
          <span>
            <strong>Drop an Excel (.xlsx), CSV or zip file here</strong> or click to choose
          </span>
          <span className="muted small">
            Column names do not need to match exactly: you map them in the next step.
            {limit ? ` Up to ${fmtBytes(limit)}.` : ""}
          </span>
          <input type="file" accept=".xlsx,.xlsm,.csv,.txt,.zip" className="sr-only" onChange={(e) => pick(e.target.files?.[0] ?? null)} data-testid="import-file-input" />
        </label>
        {file ? (
          <div className="row wrap" data-testid="import-file-chosen">
            <Icon name="file" />
            <strong>{file.name}</strong>
            <span className="muted small">{fmtBytes(file.size)}</span>
          </div>
        ) : null}
        {tooBig && limit !== null ? (
          <span className="field-error" role="alert" data-testid="import-too-big">
            <Icon name="alert" size={12} /> This file is {fmtBytes(file.size)}; the server accepts at most {fmtBytes(limit)}. Split it into smaller files (for example items and BOMs separately).
          </span>
        ) : null}
        {isCsv ? (
          <div className="field" style={{ maxWidth: 320 }}>
            <label htmlFor="imp-sheet">What does this CSV contain?</label>
            <select id="imp-sheet" className="select" value={sheet} onChange={(e) => setSheet(e.target.value)} data-testid="import-csv-sheet">
              {sheets.map((s) => (
                <option key={s} value={s}>
                  {sheetLabel(s)}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <MfgError error={error} title="The file could not be read" />
        <div className="row">
          <button type="button" className="btn primary" disabled={!file || tooBig || busy} onClick={() => void upload()} data-testid="import-upload-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="upload" />} Upload and continue
          </button>
        </div>
      </div>
    </section>
  );
}
