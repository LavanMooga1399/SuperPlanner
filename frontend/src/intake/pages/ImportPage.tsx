import { useId, useRef, useState } from "react";
import { useParams } from "react-router";
import { NotFound } from "../../App";
import { Icon } from "../../components/Icon";
import { KINDS, isPlanKind, type PlanKind } from "../../landing/kinds";
import { ColumnMapper } from "../components/ColumnMapper";
import { IntakeReview } from "../components/IntakeReview";
import { cpLength } from "../lib/codepoints";
import { IntakeProvider, useIntake } from "../state/IntakeContext";
import { IntakeShell } from "./IntakeShell";

/** Files are read in the browser (PHASE2.md 2.13): at most 1 MB, .csv / .tsv / .txt. */
export const MAX_FILE_BYTES = 1024 * 1024;
const FILE_EXT = /\.(csv|tsv|txt)$/i;

const EXAMPLE: Record<PlanKind, string> = {
  project: "Task\tDuration\tAfter\tOwner\tDue\nRequirements\t2-3 d\t\tPriya\t\nDesign\t1 w\tRequirements\tPriya\t",
  study: "Subject\tSession\tHours\tAfter\nPhysics\tMechanics\t6\t\nPhysics\tRevision 1\t3\tMechanics",
  production: "Job\tOperation\tHours\tAfter\tMachine\tDue\nOrder A\tCutting\t3\t\tM1\t2026-11-20\nOrder A\tWelding\t2\tCutting\tM2\t",
  money: "Type\tName\tAmount\tHow often\nIncome\tSalary\t120000\tmonthly\nExpense\tRent\t25000\tmonthly\nGoal\tCar\t800000\t2028-06",
};

/** Plain message if a file cannot be used; null if it is fine. Checked before anything is sent. */
export function fileProblem(file: File): string | null {
  if (!FILE_EXT.test(file.name)) return "Choose a .csv, .tsv or .txt file. For a spreadsheet, copy the cells and paste them in the box instead.";
  if (file.size > MAX_FILE_BYTES) return `"${file.name}" is larger than 1 MB. Split it into smaller files, or paste only the rows you need.`;
  return null;
}

const STEPS = ["Paste or upload", "Match the columns", "Answer and check", "Create the plan"];

function ImportInner({ kind }: { kind: PlanKind }) {
  const { state, busy, limits, setTable, parseTable, setStep } = useIntake();
  const [fileError, setFileError] = useState<string | null>(null);
  const [tried, setTried] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const pasteId = useId();
  const fileId = useId();
  const t = state.table;
  const tooLong = cpLength(t.text) > limits.max_table_chars;
  const empty = !t.text.trim();
  const info = KINDS[kind];

  const onFile = async (file: File | undefined) => {
    setFileError(null);
    if (!file) return;
    const problem = fileProblem(file);
    if (problem) {
      setFileError(problem);
      if (fileRef.current) fileRef.current.value = "";
      return;
    }
    try {
      const text = await file.text();
      setTable({ text, fileName: file.name, parse: null, mapping: [] });
    } catch {
      setFileError(`"${file.name}" could not be read. Try saving it again as CSV.`);
    }
  };

  const step = state.step;
  const current = step === "write" ? 0 : step === "map" ? 1 : state.response?.questions.length === 0 && state.build?.ready ? 3 : 2;

  return (
    <IntakeShell
      kind={kind}
      title={`Import a table for your ${info.planNoun === "money" ? "money goals" : `${info.planNoun} plan`}`}
      intro="Paste cells from a spreadsheet or upload a CSV file. Each row becomes one item of a draft you can check and change before anything is saved."
      steps={STEPS}
      current={current}
    >
      {step === "write" ? (
        <section className="card" aria-label="Your table">
          <div className="card-body col" style={{ gap: 12 }}>
            <div className="field">
              <label htmlFor={pasteId} style={{ fontSize: 14 }}>
                Paste your table
              </label>
              <textarea
                id={pasteId}
                className="textarea intake-textarea mono"
                data-testid="import-paste"
                rows={10}
                value={t.text}
                placeholder={`For example (copied from a spreadsheet):\n${EXAMPLE[kind]}`}
                aria-invalid={tooLong || (tried && empty)}
                aria-describedby={`${pasteId}-help`}
                onChange={(e) => setTable({ text: e.target.value, fileName: null, parse: null, mapping: [] })}
              />
              <span id={`${pasteId}-help`} className={tooLong || (tried && empty) ? "field-error" : "small muted"} role={tooLong || (tried && empty) ? "alert" : undefined}>
                {tooLong
                  ? `The table is too long: at most ${limits.max_table_chars.toLocaleString()} characters.`
                  : tried && empty
                    ? "Paste a table or choose a file first."
                    : `Up to ${limits.max_table_rows.toLocaleString()} rows and ${limits.max_table_columns} columns. The first row may hold column names.`}
              </span>
            </div>
            <div className="field">
              <label htmlFor={fileId}>Or choose a file (.csv, .tsv or .txt, up to 1 MB)</label>
              <input
                id={fileId}
                ref={fileRef}
                type="file"
                accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain"
                data-testid="import-file"
                aria-describedby={fileError ? `${fileId}-err` : undefined}
                aria-invalid={fileError ? true : undefined}
                onChange={(e) => void onFile(e.target.files?.[0])}
              />
              {fileError ? (
                <span id={`${fileId}-err`} className="field-error" role="alert" data-testid="import-file-error">
                  <Icon name="alert" size={12} /> {fileError}
                </span>
              ) : t.fileName ? (
                <span className="small muted" data-testid="import-file-name">
                  <Icon name="file" size={12} /> Loaded "{t.fileName}". It is read in your browser and sent only to this server.
                </span>
              ) : null}
            </div>
            <div className="row" style={{ gap: 8 }}>
              <button
                type="button"
                className="btn primary"
                data-testid="import-parse"
                disabled={busy !== null}
                onClick={() => {
                  setTried(true);
                  if (!empty && !tooLong) void parseTable();
                }}
              >
                {busy === "parse" ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />} Read the table
              </button>
              {state.response ? (
                <button type="button" className="btn ghost" onClick={() => setStep("review")}>
                  Back to the draft
                </button>
              ) : null}
            </div>
          </div>
        </section>
      ) : step === "map" ? (
        <>
          <div>
            <button type="button" className="btn sm" onClick={() => setStep("write")}>
              <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> Change the table
            </button>
          </div>
          <ColumnMapper />
        </>
      ) : (
        <>
          <div>
            <button type="button" className="btn sm" onClick={() => setStep(t.parse ? "map" : "write")}>
              <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> Change the columns
            </button>
          </div>
          <IntakeReview />
        </>
      )}
    </IntakeShell>
  );
}

/** `/new/:kind/import`: paste or upload, map columns, then questions, review and create (PHASE2.md 3.3). */
export function ImportPage() {
  const { kind } = useParams();
  if (!isPlanKind(kind)) return <NotFound />;
  return (
    <IntakeProvider key={`${kind}-import`} kind={kind} flow="import">
      <ImportInner kind={kind} />
    </IntakeProvider>
  );
}
