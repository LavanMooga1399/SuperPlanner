import { useState } from "react";
import { Icon } from "../../components/Icon";
import { KINDS } from "../../landing/kinds";
import type { Delimiter, DurationUnit, Frequency, TableOptions } from "../api/types";
import { UNIT_LABEL } from "../lib/pert";
import { useIntake } from "../state/IntakeContext";

export function fieldOptions(domain: "schedule" | "finance", kind: keyof typeof KINDS): { value: string; label: string }[] {
  if (domain === "finance") {
    return [
      { value: "row_kind", label: "Row type (income, expense, goal, loan, savings)" },
      { value: "name", label: "Name" },
      { value: "amount", label: "Amount" },
      { value: "frequency", label: "How often" },
      { value: "category", label: "Category" },
      { value: "essential", label: "Essential (yes / no)" },
      { value: "date", label: "Date (goal date)" },
      { value: "priority", label: "Priority" },
      { value: "asset_class", label: "Held in (savings type)" },
      { value: "interest_rate", label: "Interest rate" },
      { value: "emi", label: "Monthly instalment" },
      { value: "balance", label: "Loan balance" },
    ];
  }
  const t = KINDS[kind].terminology ?? KINDS.project.terminology!;
  return [
    { value: "name", label: `${t.task} name` },
    { value: "id", label: "ID (used by 'comes after')" },
    { value: "duration", label: "Duration (a range like 2-3 is fine)" },
    { value: "optimistic", label: "Shortest duration" },
    { value: "likely", label: "Most likely duration" },
    { value: "pessimistic", label: "Longest duration" },
    { value: "predecessors", label: "Comes after" },
    { value: "resources", label: `Who / which ${t.resource.toLowerCase()}` },
    { value: "deadline", label: t.deadline },
    { value: "earliest_start", label: "Not before (start date)" },
    { value: "priority", label: "Priority" },
    { value: "group", label: t.group },
    { value: "notes", label: "Notes" },
  ];
}

const DELIMS: { v: Delimiter; label: string }[] = [
  { v: "\t", label: "Tab (pasted from a spreadsheet)" },
  { v: ",", label: "Comma" },
  { v: ";", label: "Semicolon" },
  { v: "|", label: "Vertical bar" },
];

const FREQ: { v: Frequency; label: string }[] = [
  { v: "monthly", label: "Each month" },
  { v: "quarterly", label: "Each quarter" },
  { v: "half_yearly", label: "Twice a year" },
  { v: "yearly", label: "Each year" },
  { v: "once", label: "Once" },
];

/** Problems with the chosen mapping that the server would reject as BAD_MAPPING. */
export function mappingProblems(mapping: (string | null)[]): string[] {
  const out: string[] = [];
  if (!mapping.includes("name")) out.push('Choose which column holds the name ("Name").');
  const seen = new Map<string, number>();
  for (const f of mapping) if (f) seen.set(f, (seen.get(f) ?? 0) + 1);
  for (const [f, n] of seen) if (n > 1) out.push(`"${f}" is chosen for ${n} columns; choose it for one column only.`);
  return out;
}

/** One select per column ("Ignore" or a field), preview of the first rows and import options (PHASE2.md 3.3). */
export function ColumnMapper() {
  const { state, domain, busy, setTable, parseTable, applyTable } = useIntake();
  const [tried, setTried] = useState(false);
  const t = state.table;
  const parse = t.parse;
  if (!parse) return null;
  const fields = fieldOptions(domain, state.kind);
  const problems = mappingProblems(t.mapping);
  const setOpt = (patch: Partial<TableOptions>) => setTable({ options: { ...t.options, ...patch } });

  return (
    <section className="card" aria-labelledby="map-title">
      <div className="card-header">
        <h2 id="map-title" style={{ margin: 0, fontSize: 16 }}>
          Match the columns
        </h2>
        <span className="small muted">
          {parse.row_count} {parse.row_count === 1 ? "row" : "rows"}, {parse.columns.length} columns
        </span>
      </div>
      <div className="card-body col" style={{ gap: 12 }}>
        <p className="small muted" style={{ margin: 0 }}>
          We suggested what each column means. Change any that are wrong, or choose "Ignore".
        </p>
        <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={parse.has_header}
              disabled={busy !== null}
              onChange={(e) => void parseTable({ delimiter: parse.delimiter, has_header: e.target.checked })}
            />
            The first row holds column names
          </label>
          <label className="small row" style={{ gap: 6 }}>
            Columns separated by
            <select
              className="select sm"
              value={parse.delimiter}
              disabled={busy !== null}
              onChange={(e) => void parseTable({ delimiter: e.target.value as Delimiter, has_header: parse.has_header })}
            >
              {DELIMS.map((d) => (
                <option key={d.label} value={d.v}>
                  {d.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {parse.warnings.length ? (
          <ul className="intake-notes" aria-label="Table warnings">
            {parse.warnings.map((w, i) => (
              <li key={i} className="issue-line warning">
                <Icon name="alert" size={14} /> {w}
              </li>
            ))}
          </ul>
        ) : null}
        <div className="table-wrap">
          <table className="table map-table">
            <thead>
              <tr>
                {parse.columns.map((c) => (
                  <th key={c.index} scope="col">
                    <div className="col" style={{ gap: 4 }}>
                      <span>{c.header ?? `Column ${c.index + 1}`}</span>
                      <select
                        className="select sm"
                        data-testid={`import-map-${c.index}`}
                        aria-label={`Column ${c.index + 1}${c.header ? ` "${c.header}"` : ""} means`}
                        aria-invalid={tried && problems.length > 0 ? true : undefined}
                        value={t.mapping[c.index] ?? ""}
                        onChange={(e) => {
                          const m = [...t.mapping];
                          m[c.index] = e.target.value || null;
                          setTable({ mapping: m });
                        }}
                      >
                        <option value="">Ignore</option>
                        {fields.map((f) => (
                          <option key={f.value} value={f.value}>
                            {f.label}
                          </option>
                        ))}
                      </select>
                      {c.suggested_field ? (
                        <span className="small muted" style={{ fontWeight: 400 }}>
                          Suggested ({c.confidence >= 0.8 ? "high" : c.confidence >= 0.5 ? "medium" : "low"} confidence)
                        </span>
                      ) : (
                        <span className="small faint" style={{ fontWeight: 400 }}>
                          No suggestion
                        </span>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {parse.preview.map((row, r) => (
                <tr key={r}>
                  {parse.columns.map((c) => (
                    <td key={c.index} className={t.mapping[c.index] ? "" : "muted"}>
                      {row[c.index] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {parse.row_count > parse.preview.length ? (
          <span className="small muted">Showing the first {parse.preview.length} rows.</span>
        ) : null}

        <fieldset className="plain-fieldset">
          <legend className="field-label">Options</legend>
          <div className="row" style={{ gap: 16, flexWrap: "wrap" }}>
            {domain === "schedule" ? (
              <>
                <label className="small row" style={{ gap: 6 }}>
                  Numbers without a unit are
                  <select className="select sm" value={t.options.duration_unit} onChange={(e) => setOpt({ duration_unit: e.target.value as DurationUnit })}>
                    {(["minutes", "hours", "days", "weeks"] as DurationUnit[]).map((u) => (
                      <option key={u} value={u}>
                        {UNIT_LABEL[u]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="small row" style={{ gap: 6 }}>
                  "Comes after" refers to
                  <select className="select sm" value={t.options.predecessor_ref} onChange={(e) => setOpt({ predecessor_ref: e.target.value as TableOptions["predecessor_ref"] })}>
                    <option value="auto">Work it out</option>
                    <option value="id">The ID column</option>
                    <option value="name">Names</option>
                    <option value="row">Row numbers</option>
                  </select>
                </label>
              </>
            ) : (
              <>
                <label className="small row" style={{ gap: 6 }}>
                  Rows without a type are
                  <select className="select sm" value={t.options.default_row_kind} onChange={(e) => setOpt({ default_row_kind: e.target.value as TableOptions["default_row_kind"] })}>
                    <option value="expense">Spending</option>
                    <option value="income">Income</option>
                    <option value="goal">Goals</option>
                    <option value="debt">Loans</option>
                    <option value="holding">Savings</option>
                  </select>
                </label>
                <label className="small row" style={{ gap: 6 }}>
                  Amounts without "a month" or "a year" are
                  <select className="select sm" value={t.options.amount_frequency} onChange={(e) => setOpt({ amount_frequency: e.target.value as Frequency })}>
                    {FREQ.map((f) => (
                      <option key={f.v} value={f.v}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
          </div>
        </fieldset>

        {tried && problems.length ? (
          <div className="banner danger error-summary" role="alert" data-testid="import-map-errors">
            <Icon name="alert" />
            <div className="banner-body">
              <strong>Check the columns</strong>
              <ul>
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          </div>
        ) : null}
        <div className="row" style={{ gap: 8 }}>
          <button
            type="button"
            className="btn primary"
            data-testid="import-apply"
            disabled={busy !== null}
            onClick={() => {
              setTried(true);
              if (!problems.length) void applyTable();
            }}
          >
            {busy === "apply" ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Use these columns
          </button>
        </div>
      </div>
    </section>
  );
}
