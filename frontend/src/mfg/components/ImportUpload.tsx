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
import { t } from "../../lib/i18n";

const SHEET_LABEL: Record<string, string> = {
  plant: t("mfg.importUpload.str.plantSettings"),
  items: t("mfg.importUpload.str.items"),
  skills: t("mfg.importUpload.str.skills"),
  tool_pools: t("mfg.importUpload.str.tooling"),
  groups: t("mfg.importUpload.str.stages"),
  lines: t("mfg.importUpload.str.lines"),
  shift_templates: t("mfg.importUpload.str.shiftTemplates"),
  shifts: t("mfg.importUpload.str.shifts"),
  shift_assignments: t("mfg.importUpload.str.shiftAssignments"),
  calendar_exceptions: t("mfg.importUpload.str.holidaysAndMaintenance"),
  operators: t("mfg.importUpload.str.operators"),
  boms: t("mfg.importUpload.str.bomHeaders"),
  bom_lines: t("mfg.importUpload.str.bomLines"),
  routings: t("mfg.importUpload.str.routingHeaders"),
  operations: t("mfg.importUpload.str.operations"),
  locations: t("mfg.importUpload.str.storesLocations"),
  suppliers: t("mfg.importUpload.str.suppliers"),
  item_suppliers: t("mfg.importUpload.str.suppliersPerPart"),
  stock: t("mfg.importUpload.str.stockOnHand"),
  purchase_docs: t("mfg.importUpload.str.purchaseOrdersRequests"),
  purchase_lines: t("mfg.importUpload.str.purchaseLines"),
  purchase_schedules: t("mfg.importUpload.str.purchaseDeliveries"),
  demand_orders: t("mfg.importUpload.str.demandOrders"),
  demand_lines: t("mfg.importUpload.str.demandLines"),
  work_orders: t("mfg.importUpload.str.workOrders"),
  wo_components: t("mfg.importUpload.str.workOrderComponents"),
};

/** M2 11: what kind of data a sheet is, and which permission a commit with it needs (shown per card). */
export const SHEET_KIND: Record<string, { label: string; perm: string }> = {
  locations: { label: t("mfg.importUpload.str.masterData"), perm: t("mfg.importUpload.str.planner") },
  suppliers: { label: t("mfg.importUpload.str.masterData"), perm: t("mfg.importUpload.str.plannerOrPurchaser") },
  item_suppliers: { label: t("mfg.importUpload.str.masterData"), perm: t("mfg.importUpload.str.plannerOrPurchaser") },
  stock: { label: t("mfg.importUpload.str.stockPostedAsACount"), perm: t("mfg.importUpload.str.storeKeeper") },
  purchase_docs: { label: t("mfg.importUpload.str.purchasing"), perm: t("mfg.importUpload.str.purchaserOrdersOrPlannerRequests") },
  purchase_lines: { label: t("mfg.importUpload.str.purchasing"), perm: t("mfg.importUpload.str.purchaserOrdersOrPlannerRequests") },
  purchase_schedules: { label: t("mfg.importUpload.str.purchasing"), perm: t("mfg.importUpload.str.purchaserOrdersOrPlannerRequests") },
  demand_orders: { label: t("mfg.importUpload.str.demand"), perm: t("mfg.importUpload.str.planner") },
  demand_lines: { label: t("mfg.importUpload.str.demand"), perm: t("mfg.importUpload.str.planner") },
  work_orders: { label: t("mfg.importUpload.str.workOrders"), perm: t("mfg.importUpload.str.planner") },
  wo_components: { label: t("mfg.importUpload.str.workOrders"), perm: t("mfg.importUpload.str.planner") },
};

export function sheetKind(name: string | null): { label: string; perm: string } {
  return (name && SHEET_KIND[name]) || { label: t("mfg.importUpload.str.masterData"), perm: t("mfg.importUpload.str.planner") };
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
        <h2 id="imp-up-title">{t("mfg.importUpload.head.1ChooseAFile")}</h2>
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
            <strong>{t("mfg.importUpload.text.dropAnExcelXlsxCsv")}</strong>{" "}{t("mfg.importUpload.text.orClickToChoose")}
          </span>
          <span className="muted small">
            {t("mfg.importUpload.text.columnNamesDoNotNeed", { v: limit ? t("mfg.importUpload.tpl.upTo", { limit: fmtBytes(limit) }) : "" })}
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
            <Icon name="alert" size={12} />{" "}{t("mfg.importUpload.text.thisFileIsTheServer", { size: fmtBytes(file.size), limit: fmtBytes(limit) })}
          </span>
        ) : null}
        {isCsv ? (
          <div className="field" style={{ maxWidth: 320 }}>
            <label htmlFor="imp-sheet">{t("mfg.importUpload.label.whatDoesThisCsvContain")}</label>
            <select id="imp-sheet" className="select" value={sheet} onChange={(e) => setSheet(e.target.value)} data-testid="import-csv-sheet">
              {sheets.map((s) => (
                <option key={s} value={s}>
                  {sheetLabel(s)}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <MfgError error={error} title={t("mfg.importUpload.attr.theFileCouldNotBe")} />
        <div className="row">
          <button type="button" className="btn primary" disabled={!file || tooBig || busy} onClick={() => void upload()} data-testid="import-upload-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="upload" />}{" "}{t("mfg.importUpload.text.uploadAndContinue")}
          </button>
        </div>
      </div>
    </section>
  );
}
