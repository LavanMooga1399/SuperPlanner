import { useState } from "react";
import { Icon } from "../../components/Icon";
import { KINDS } from "../../landing/kinds";
import type { Delimiter, DurationUnit, Frequency, TableOptions } from "../api/types";
import { UNIT_LABEL } from "../lib/pert";
import { useIntake } from "../state/IntakeContext";
import { t as tr } from "../../lib/i18n";

export function fieldOptions(domain: "schedule" | "finance", kind: keyof typeof KINDS): { value: string; label: string }[] {
  if (domain === "finance") {
    return [
      { value: "row_kind", label: tr("studio.columnMapper.str.rowTypeIncomeExpenseGoal") },
      { value: "name", label: tr("studio.columnMapper.str.name") },
      { value: "amount", label: tr("studio.columnMapper.str.amount") },
      { value: "frequency", label: tr("studio.columnMapper.str.howOften") },
      { value: "category", label: tr("studio.columnMapper.str.category") },
      { value: "essential", label: tr("studio.columnMapper.str.essentialYesNo") },
      { value: "date", label: tr("studio.columnMapper.str.dateGoalDate") },
      { value: "priority", label: tr("studio.columnMapper.str.priority") },
      { value: "asset_class", label: tr("studio.columnMapper.str.heldInSavingsType") },
      { value: "interest_rate", label: tr("studio.columnMapper.str.interestRate") },
      { value: "emi", label: tr("studio.columnMapper.str.monthlyInstalment") },
      { value: "balance", label: tr("studio.columnMapper.str.loanBalance") },
    ];
  }
  const t = KINDS[kind].terminology ?? KINDS.project.terminology!;
  return [
    { value: "name", label: `${t.task} name` },
    { value: "id", label: tr("studio.columnMapper.str.idUsedByComesAfter") },
    { value: "duration", label: tr("studio.columnMapper.str.durationARangeLike2") },
    { value: "optimistic", label: tr("studio.columnMapper.str.shortestDuration") },
    { value: "likely", label: tr("studio.columnMapper.str.mostLikelyDuration") },
    { value: "pessimistic", label: tr("studio.columnMapper.str.longestDuration") },
    { value: "predecessors", label: tr("studio.columnMapper.str.comesAfter") },
    { value: "resources", label: tr("studio.columnMapper.tpl.whoWhich", { resource: t.resource.toLowerCase() }) },
    { value: "deadline", label: t.deadline },
    { value: "earliest_start", label: tr("studio.columnMapper.str.notBeforeStartDate") },
    { value: "priority", label: tr("studio.columnMapper.str.priority") },
    { value: "group", label: t.group },
    { value: "notes", label: tr("studio.columnMapper.str.notes") },
  ];
}

const DELIMS: { v: Delimiter; label: string }[] = [
  { v: "\t", label: tr("studio.columnMapper.str.tabPastedFromASpreadsheet") },
  { v: ",", label: tr("studio.columnMapper.str.comma") },
  { v: ";", label: tr("studio.columnMapper.str.semicolon") },
  { v: "|", label: tr("studio.columnMapper.str.verticalBar") },
];

const FREQ: { v: Frequency; label: string }[] = [
  { v: "monthly", label: tr("studio.columnMapper.str.eachMonth") },
  { v: "quarterly", label: tr("studio.columnMapper.str.eachQuarter") },
  { v: "half_yearly", label: tr("studio.columnMapper.str.twiceAYear") },
  { v: "yearly", label: tr("studio.columnMapper.str.eachYear") },
  { v: "once", label: tr("studio.columnMapper.str.once") },
];

/** Problems with the chosen mapping that the server would reject as BAD_MAPPING. */
export function mappingProblems(mapping: (string | null)[]): string[] {
  const out: string[] = [];
  if (!mapping.includes("name")) out.push(tr("studio.columnMapper.str.chooseWhichColumnHoldsThe"));
  const seen = new Map<string, number>();
  for (const f of mapping) if (f) seen.set(f, (seen.get(f) ?? 0) + 1);
  for (const [f, n] of seen) if (n > 1) out.push(tr("studio.columnMapper.tpl.isChosenForColumnsChoose", { f: f, n: n }));
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
          {tr("studio.columnMapper.text.matchTheColumns")}
        </h2>
        <span className="small muted">
          {parse.row_count} {parse.row_count === 1 ? "row" : "rows"}, {parse.columns.length} columns
        </span>
      </div>
      <div className="card-body col" style={{ gap: 12 }}>
        <p className="small muted" style={{ margin: 0 }}>
          {tr("studio.columnMapper.text.weSuggestedWhatEachColumn")}
        </p>
        <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={parse.has_header}
              disabled={busy !== null}
              onChange={(e) => void parseTable({ delimiter: parse.delimiter, has_header: e.target.checked })}
            />
            {tr("studio.columnMapper.text.theFirstRowHoldsColumn")}
          </label>
          <label className="small row" style={{ gap: 6 }}>
            {tr("studio.columnMapper.text.columnsSeparatedBy")}
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
          <ul className="intake-notes" aria-label={tr("studio.columnMapper.aria.tableWarnings")}>
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
                      <span>{c.header ?? tr("studio.columnMapper.tpl.column", { v: c.index + 1 })}</span>
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
                        <option value="">{tr("studio.columnMapper.text.ignore")}</option>
                        {fields.map((f) => (
                          <option key={f.value} value={f.value}>
                            {f.label}
                          </option>
                        ))}
                      </select>
                      {c.suggested_field ? (
                        <span className="small muted" style={{ fontWeight: 400 }}>
                          {tr("studio.columnMapper.text.suggestedConfidence", { v: c.confidence >= 0.8 ? "high" : c.confidence >= 0.5 ? "medium" : "low" })}
                        </span>
                      ) : (
                        <span className="small faint" style={{ fontWeight: 400 }}>
                          {tr("studio.columnMapper.text.noSuggestion")}
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
          <span className="small muted">{tr("studio.columnMapper.text.showingTheFirstRows", { length: parse.preview.length })}</span>
        ) : null}

        <fieldset className="plain-fieldset">
          <legend className="field-label">{tr("studio.columnMapper.head.options")}</legend>
          <div className="row" style={{ gap: 16, flexWrap: "wrap" }}>
            {domain === "schedule" ? (
              <>
                <label className="small row" style={{ gap: 6 }}>
                  {tr("studio.columnMapper.text.numbersWithoutAUnitAre")}
                  <select className="select sm" value={t.options.duration_unit} onChange={(e) => setOpt({ duration_unit: e.target.value as DurationUnit })}>
                    {(["minutes", "hours", "days", "weeks"] as DurationUnit[]).map((u) => (
                      <option key={u} value={u}>
                        {UNIT_LABEL[u]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="small row" style={{ gap: 6 }}>
                  {tr("studio.columnMapper.text.comesAfterRefersTo")}
                  <select className="select sm" value={t.options.predecessor_ref} onChange={(e) => setOpt({ predecessor_ref: e.target.value as TableOptions["predecessor_ref"] })}>
                    <option value="auto">{tr("studio.columnMapper.text.workItOut")}</option>
                    <option value="id">{tr("studio.columnMapper.text.theIdColumn")}</option>
                    <option value="name">{tr("studio.columnMapper.text.names")}</option>
                    <option value="row">{tr("studio.columnMapper.text.rowNumbers")}</option>
                  </select>
                </label>
              </>
            ) : (
              <>
                <label className="small row" style={{ gap: 6 }}>
                  {tr("studio.columnMapper.text.rowsWithoutATypeAre")}
                  <select className="select sm" value={t.options.default_row_kind} onChange={(e) => setOpt({ default_row_kind: e.target.value as TableOptions["default_row_kind"] })}>
                    <option value="expense">{tr("studio.columnMapper.text.spending")}</option>
                    <option value="income">{tr("studio.columnMapper.text.income")}</option>
                    <option value="goal">{tr("studio.columnMapper.text.goals")}</option>
                    <option value="debt">{tr("studio.columnMapper.text.loans")}</option>
                    <option value="holding">{tr("studio.columnMapper.text.savings")}</option>
                  </select>
                </label>
                <label className="small row" style={{ gap: 6 }}>
                  {tr("studio.columnMapper.text.amountsWithoutAMonthOr")}
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
              <strong>{tr("studio.columnMapper.head.checkTheColumns")}</strong>
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
            {busy === "apply" ? <span className="spinner" aria-hidden /> : <Icon name="check" />}{" "}{tr("studio.columnMapper.text.useTheseColumns")}
          </button>
        </div>
      </div>
    </section>
  );
}
