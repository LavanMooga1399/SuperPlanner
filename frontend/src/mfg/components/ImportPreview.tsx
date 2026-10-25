/**
 * Step 3 Preview (M 11.5): counts per target sheet, row errors (virtualised; sheet, row, column, message) with
 * "Download errors as CSV" (client-side), warnings and a sample of the changes.
 */
import { Icon } from "../../components/Icon";
import type { ChangeSample, ImportPreview as Preview, RowError } from "../api/types";
import { rowErrorsCsv } from "../lib/importMapping";
import { saveBlob } from "../api/client";
import { sheetLabel } from "./ImportUpload";
import { VirtualTable, type Column } from "./VirtualTable";

const ACTION_LABEL: Record<string, string> = { create: "New", update: "Changed", delete: "Removed", unchanged: "Same" };

function keyText(k: ChangeSample["key"]): string {
  return Object.values(k)
    .filter((v) => v !== null && v !== "")
    .join(" / ");
}

export function ImportPreview({ preview, filename }: { preview: Preview; filename: string }) {
  const errorCols: Column<RowError>[] = [
    { key: "sheet", header: "Sheet", width: "120px", render: (e) => e.sheet },
    { key: "row", header: "Row", width: "64px", align: "right", render: (e) => e.row },
    { key: "col", header: "Column", width: "140px", render: (e) => <span className="mfg-ellipsis">{e.column ?? ""}</span> },
    { key: "msg", header: "Problem", width: "minmax(260px, 1fr)", render: (e) => <span className="mfg-ellipsis" title={`${e.code}: ${e.message}`}>{e.message}</span> },
    { key: "code", header: "Code", width: "190px", render: (e) => <code className="small">{e.code}</code> },
  ];
  const download = () =>
    saveBlob({ blob: new Blob([rowErrorsCsv(preview.row_errors)], { type: "text/csv;charset=utf-8" }), filename: `${filename.replace(/\.[^.]+$/, "")}-errors.csv` });
  const sheets = Object.entries(preview.counts);

  return (
    <div className="col gap-lg" data-testid="import-preview" data-ok={String(preview.ok)} data-error-count={preview.error_count}>
      <section className="card">
        <div className="card-header">
          <h3>What will change</h3>
        </div>
        <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
          <table className="table" data-testid="import-counts">
            <thead>
              <tr>
                <th>Data</th>
                <th className="num">New</th>
                <th className="num">Changed</th>
                <th className="num">Same</th>
                <th className="num">Removed</th>
                <th className="num">Errors</th>
              </tr>
            </thead>
            <tbody>
              {sheets.map(([name, c]) => (
                <tr key={name} data-testid="import-count-row" data-sheet={name}>
                  <td>{sheetLabel(name)}</td>
                  <td className="num">{c.create}</td>
                  <td className="num">{c.update}</td>
                  <td className="num">{c.unchanged}</td>
                  <td className="num">{c.delete}</td>
                  <td className="num">{c.error ? <span className="badge danger"><Icon name="x" />{c.error}</span> : 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {preview.error_count > 0 ? (
        <section className="card" aria-labelledby="imp-err-title">
          <div className="card-header">
            <h3 id="imp-err-title" className="row">
              <span className="badge danger">
                <Icon name="x" /> {preview.error_count.toLocaleString()} {preview.error_count === 1 ? "row error" : "row errors"}
              </span>
              {preview.row_errors.length < preview.error_count ? <span className="muted small">first {preview.row_errors.length} shown</span> : null}
            </h3>
            <button type="button" className="btn sm" onClick={download} data-testid="import-errors-csv">
              <Icon name="download" /> Download errors as CSV
            </button>
          </div>
          <div className="card-body">
            <VirtualTable
              rows={preview.row_errors}
              columns={errorCols}
              rowKey={(e, i) => `${e.sheet}-${e.row}-${e.column ?? ""}-${i}`}
              label="Row errors"
              height="min(40vh, 420px)"
              testId="import-row-errors"
              rowExtras={(e) => ({ testId: "import-row-error", data: { sheet: e.sheet, row: e.row, code: e.code } })}
            />
          </div>
        </section>
      ) : null}

      {preview.warnings.length ? (
        <section className="card card-body col">
          <h3>Notes</h3>
          <ul className="mfg-plain-list">
            {preview.warnings.map((w, i) => (
              <li key={i} className="row small" data-testid="import-warning">
                <Icon name="alert" size={12} /> {w.sheet ? <strong>{w.sheet}:</strong> : null} {w.message}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {preview.changes_sample.length ? (
        <details className="card">
          <summary className="card-header">
            <span>Examples of the changes ({preview.changes_sample.length})</span>
          </summary>
          <div className="table-wrap" style={{ border: 0 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Row</th>
                  <th>Change</th>
                  <th>Fields</th>
                </tr>
              </thead>
              <tbody>
                {preview.changes_sample.map((c, i) => (
                  <tr key={i}>
                    <td>{sheetLabel(c.sheet)}</td>
                    <td className="mono small">{keyText(c.key)}</td>
                    <td>{ACTION_LABEL[c.action] ?? c.action}</td>
                    <td className="small">
                      {c.fields
                        ? Object.entries(c.fields)
                            .map(([f, [a, b]]) => `${f}: ${a === null ? "-" : String(a)} → ${b === null ? "-" : String(b)}`)
                            .join("; ")
                        : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </div>
  );
}
