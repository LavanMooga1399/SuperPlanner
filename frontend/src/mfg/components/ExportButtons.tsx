/** Export (M 8.4) and blank import templates as file downloads with the server's file name. */
import { useState } from "react";
import { Icon } from "../../components/Icon";
import { downloadExport, downloadImportTemplate, saveBlob, type ExportScope } from "../api/client";
import type { FileFormat } from "../api/types";
import { MfgError } from "./Feedback";
import { t } from "../../lib/i18n";

const SCOPES: { value: ExportScope; label: string }[] = [
  { value: "master", label: "Master data" },
  { value: "transactions", label: "Stock, orders and work orders" },
  { value: "all", label: "Everything" },
];

function ScopeSelect({ value, onChange, testId }: { value: ExportScope; onChange(v: ExportScope): void; testId: string }) {
  return (
    <select className="select sm" style={{ width: "auto" }} aria-label={t("mfg.exportButtons.aria.whatToInclude")} value={value} onChange={(e) => onChange(e.target.value as ExportScope)} data-testid={testId}>
      {SCOPES.map((s) => (
        <option key={s.value} value={s.value}>
          {s.label}
        </option>
      ))}
    </select>
  );
}

export function ExportButtons({ compact, grouped }: { compact?: boolean; grouped?: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [scope, setScope] = useState<ExportScope>("master");
  const [error, setError] = useState<unknown>(null);
  const run = async (key: string, fn: () => ReturnType<typeof downloadExport>) => {
    setBusy(key);
    setError(null);
    try {
      saveBlob(await fn());
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  const exp = (f: FileFormat) => run(`export-${f}`, () => downloadExport(f, scope === "master" ? undefined : scope));
  if (grouped)
    // one grouped control: Export (Excel) | CSV (zip) | what to include
    return (
      <div className="col" style={{ gap: 6, alignItems: "flex-end" }}>
        <div className="btn-group export-group" role="group" aria-label={t("mfg.exportButtons.aria.export")}>
          <button type="button" className="btn" onClick={() => void exp("xlsx")} disabled={busy !== null} data-testid="mfg-export" title="Download as an Excel workbook (one sheet per kind of data)">
            {busy === "export-xlsx" ? <span className="spinner" aria-hidden /> : <Icon name="download" />} Export
          </button>
          <button type="button" className="btn" onClick={() => void exp("zip")} disabled={busy !== null} data-testid="mfg-export-zip" title="Download as CSV files in a zip">
            {busy === "export-zip" ? <span className="spinner" aria-hidden /> : null} CSV (zip)
          </button>
          <select className="btn seg-select" aria-label={t("mfg.exportButtons.aria.whatToExport")} value={scope} onChange={(e) => setScope(e.target.value as ExportScope)} data-testid="mfg-export-scope">
            {SCOPES.map((x) => (
              <option key={x.value} value={x.value}>
                {x.label}
              </option>
            ))}
          </select>
        </div>
        <MfgError error={error} title="Download failed" />
      </div>
    );
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="row wrap">
        <ScopeSelect value={scope} onChange={setScope} testId="mfg-export-scope" />
        <button
          type="button"
          className={`btn${compact ? " sm" : ""}`}
          onClick={() => void exp("xlsx")}
          disabled={busy !== null}
          data-testid="mfg-export"
          title="Download all manufacturing data as an Excel workbook (one sheet per kind of data)"
        >
          {busy === "export-xlsx" ? <span className="spinner" aria-hidden /> : <Icon name="download" />}
          Export to Excel
        </button>
        <button
          type="button"
          className={`btn ghost${compact ? " sm" : ""}`}
          onClick={() => void exp("zip")}
          disabled={busy !== null}
          data-testid="mfg-export-zip"
          title="Download all manufacturing data as CSV files in a zip"
        >
          {busy === "export-zip" ? <span className="spinner" aria-hidden /> : <Icon name="download" />}
          CSV (zip)
        </button>
      </div>
      <MfgError error={error} title="Download failed" />
    </div>
  );
}

export function TemplateButtons() {
  const [busy, setBusy] = useState<FileFormat | null>(null);
  const [scope, setScope] = useState<ExportScope>("master");
  const [error, setError] = useState<unknown>(null);
  const run = async (f: FileFormat) => {
    setBusy(f);
    setError(null);
    try {
      saveBlob(await downloadImportTemplate(f, scope === "master" ? undefined : scope));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="row wrap">
        <ScopeSelect value={scope} onChange={setScope} testId="import-template-scope" />
        <button type="button" className="btn sm" onClick={() => void run("xlsx")} disabled={busy !== null} data-testid="import-template-xlsx">
          {busy === "xlsx" ? <span className="spinner" aria-hidden /> : <Icon name="file" />}
          Blank template (Excel)
        </button>
        <button type="button" className="btn sm ghost" onClick={() => void run("zip")} disabled={busy !== null} data-testid="import-template-zip">
          {busy === "zip" ? <span className="spinner" aria-hidden /> : <Icon name="file" />}
          Blank template (CSV zip)
        </button>
      </div>
      <MfgError error={error} title="Download failed" />
    </div>
  );
}
