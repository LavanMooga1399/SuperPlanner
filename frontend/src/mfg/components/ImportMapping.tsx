/**
 * Step 2 Map columns (M 11.5): one card per source sheet with its target sheet (suggestion preselected) and a
 * field per source column; required fields are marked and unmapped ones hinted; two columns mapped to one
 * field block "Preview". Options sit behind "More options".
 */
import { useState } from "react";
import { Icon } from "../../components/Icon";
import type { Cell, ImportMappingRequest, ImportRecord, ImportSheetSpec } from "../api/types";
import { checkSheet } from "../lib/importMapping";
import { useMeta } from "../lib/useMfg";
import { CheckField, TextField } from "./Field";
import { sheetKind, sheetLabel } from "./ImportUpload";

function cellText(c: Cell | undefined): string {
  if (c === null || c === undefined) return "";
  return String(c);
}

export function ImportMapping({
  record,
  value,
  onChange,
}: {
  record: ImportRecord;
  value: ImportMappingRequest;
  onChange(next: ImportMappingRequest): void;
}) {
  const meta = useMeta();
  const [more, setMore] = useState(false);
  const specs = meta?.import_spec.sheets ?? [];
  const specOf = (name: string | null): ImportSheetSpec | undefined => specs.find((s) => s.name === name);

  const setSheet = (name: string, patch: Partial<ImportMappingRequest["sheets"][string]>) =>
    onChange({ ...value, sheets: { ...value.sheets, [name]: { ...value.sheets[name], ...patch } } });

  return (
    <div className="col gap-lg" data-testid="import-mapping">
      {record.sheets.map((s) => {
        const m = value.sheets[s.name];
        if (!m) return null;
        const spec = specOf(m.target);
        const check = checkSheet(m, spec);
        return (
          <section key={s.name} className="card" aria-label={`Sheet ${s.name}`} data-testid="import-sheet-card" data-sheet={s.name}>
            <div className="card-header">
              <h3 className="row">
                <Icon name="file" /> {s.name} <span className="muted small">{s.row_count.toLocaleString()} rows</span>
                {m.target ? (
                  <span className="badge info" data-testid="import-sheet-kind" title={`Saving this sheet needs the role: ${sheetKind(m.target).perm}`}>
                    {sheetKind(m.target).label}
                  </span>
                ) : null}
              </h3>
              <label className="row small">
                <span className="muted">Import as</span>
                <select
                  className="select sm"
                  value={m.target ?? ""}
                  onChange={(e) => setSheet(s.name, { target: e.target.value || null })}
                  aria-label={`Import sheet ${s.name} as`}
                  data-testid="import-sheet-target"
                  style={{ minWidth: 200 }}
                >
                  <option value="">Ignore this sheet</option>
                  {specs.map((sp) => (
                    <option key={sp.name} value={sp.name}>
                      {sheetLabel(sp.name)} ({sp.name})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {m.target && spec ? (
              <div className="card-body col">
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Column in your file</th>
                        <th>Example values</th>
                        <th>Goes into</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.headers.map((h, ci) => {
                        const field = m.columns[h] ?? "";
                        const dup = field && check.duplicates.includes(field);
                        return (
                          <tr key={h} data-testid="import-column-row" data-header={h}>
                            <td>
                              <strong>{h}</strong>
                            </td>
                            <td className="small muted mfg-ellipsis" style={{ maxWidth: 260 }}>
                              {s.sample_rows
                                .slice(0, 3)
                                .map((r) => cellText(r[ci]))
                                .filter(Boolean)
                                .join(" · ")}
                            </td>
                            <td>
                              <select
                                className="select sm"
                                value={field}
                                aria-label={`Field for column ${h}`}
                                aria-invalid={dup ? true : undefined}
                                onChange={(e) => setSheet(s.name, { columns: { ...m.columns, [h]: e.target.value || null } })}
                                data-testid="import-column-field"
                                style={{ minWidth: 200 }}
                              >
                                <option value="">Do not import</option>
                                {spec.columns.map((c) => (
                                  <option key={c.field} value={c.field}>
                                    {c.field}
                                    {c.required_on_create ? " *" : ""}
                                    {c.key ? " (key)" : ""}
                                  </option>
                                ))}
                              </select>
                              {dup ? (
                                <span className="field-error">
                                  <Icon name="alert" size={12} /> Used twice
                                </span>
                              ) : null}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {check.duplicates.length ? (
                  <span className="field-error" role="alert" data-testid="import-duplicate-field">
                    <Icon name="alert" size={12} /> Each field can take only one column: {check.duplicates.join(", ")}.
                  </span>
                ) : null}
                {check.missingRequired.length ? (
                  <span className="small muted" data-testid="import-missing-required">
                    <Icon name="info" size={12} /> Not mapped: {check.missingRequired.join(", ")} (* required for new rows; existing rows are only updated in the mapped columns).
                  </span>
                ) : null}
              </div>
            ) : m.target ? null : (
              <div className="card-body muted small">This sheet will be skipped.</div>
            )}
          </section>
        );
      })}

      <div>
        <button type="button" className="btn ghost sm" aria-expanded={more} onClick={() => setMore((x) => !x)} data-testid="import-more-options">
          <Icon name={more ? "chevron-down" : "chevron-right"} /> More options
        </button>
      </div>
      {more ? (
        <section className="card card-body col" data-testid="import-options">
          <CheckField
            label="BOM lines and operations in the file replace the existing ones of those BOMs and routings"
            checked={value.options.replace_children}
            onChange={(v) => onChange({ ...value, options: { ...value.options, replace_children: v } })}
            hint="Off = only add and update lines; nothing is removed."
          />
          <CheckField
            label="Release new BOMs and routings right away"
            checked={value.options.release}
            onChange={(v) => onChange({ ...value, options: { ...value.options, release: v } })}
            hint="Otherwise they are created as drafts that you release when checked."
          />
          <div style={{ maxWidth: 260 }}>
            <TextField
              label="Start date for new BOMs and routings"
              type="date"
              value={value.options.default_effective_from ?? ""}
              onChange={(v) => onChange({ ...value, options: { ...value.options, default_effective_from: v || null } })}
              hint="Used when the file has no start date."
            />
          </div>
        </section>
      ) : null}
    </div>
  );
}

/** True when any mapped sheet maps two columns to one field (server would answer 422). */
export function mappingBlocked(value: ImportMappingRequest, specs: ImportSheetSpec[]): boolean {
  return Object.values(value.sheets).some((m) => m.target && checkSheet(m, specs.find((s) => s.name === m.target)).duplicates.length > 0);
}
