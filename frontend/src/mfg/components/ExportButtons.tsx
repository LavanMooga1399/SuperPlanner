/** Export (M 8.4) and blank import templates as file downloads with the server's file name. */
import { useState } from "react";
import { Icon } from "../../components/Icon";
import { downloadExport, downloadImportTemplate, saveBlob } from "../api/client";
import type { FileFormat } from "../api/types";
import { MfgError } from "./Feedback";

export function ExportButtons({ compact }: { compact?: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);
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
  const exp = (f: FileFormat) => run(`export-${f}`, () => downloadExport(f));
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="row wrap">
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
  const [error, setError] = useState<unknown>(null);
  const run = async (f: FileFormat) => {
    setBusy(f);
    setError(null);
    try {
      saveBlob(await downloadImportTemplate(f));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="row wrap">
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
