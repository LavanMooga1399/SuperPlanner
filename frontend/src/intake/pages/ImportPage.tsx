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
import { t as tr } from "../../lib/i18n";

/** Files are read in the browser (PHASE2.md 2.13): at most 1 MB, .csv / .tsv / .txt. */
export const MAX_FILE_BYTES = 1024 * 1024;
const FILE_EXT = /\.(csv|tsv|txt)$/i;

const EXAMPLE: Record<PlanKind, string> = {
  project: tr("studio.importPage.str.taskDurationAfterOwnerDue"),
  study: tr("studio.importPage.str.subjectSessionHoursAfterPhysics"),
  production: tr("studio.importPage.str.jobOperationHoursAfterMachine"),
  money: tr("studio.importPage.str.typeNameAmountHowOften"),
};

/** Plain message if a file cannot be used; null if it is fine. Checked before anything is sent. */
export function fileProblem(file: File): string | null {
  if (!FILE_EXT.test(file.name)) return tr("studio.importPage.str.chooseACsvTsvOr");
  if (file.size > MAX_FILE_BYTES) return tr("studio.importPage.tpl.isLargerThan1Mb", { name: file.name });
  return null;
}

const STEPS = [tr("studio.importPage.str.pasteOrUpload"), tr("studio.importPage.str.matchTheColumns"), tr("studio.importPage.str.answerAndCheck"), tr("studio.importPage.str.createThePlan")];

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
      setFileError(tr("studio.importPage.tpl.couldNotBeReadTry", { name: file.name }));
    }
  };

  const step = state.step;
  const current = step === "write" ? 0 : step === "map" ? 1 : state.response?.questions.length === 0 && state.build?.ready ? 3 : 2;

  return (
    <IntakeShell
      kind={kind}
      title={`Import a table for your ${info.planNoun === "money" ? tr("studio.importPage.str.moneyGoals") : `${info.planNoun} plan`}`}
      intro="Paste cells from a spreadsheet or upload a CSV file. Each row becomes one item of a draft you can check and change before anything is saved."
      steps={STEPS}
      current={current}
    >
      {step === "write" ? (
        <section className="card" aria-label={tr("studio.importPage.aria.yourTable")}>
          <div className="card-body col" style={{ gap: 12 }}>
            <div className="field">
              <label htmlFor={pasteId} style={{ fontSize: 14 }}>
                {tr("studio.importPage.text.pasteYourTable")}
              </label>
              <textarea
                id={pasteId}
                className="textarea intake-textarea mono"
                data-testid="import-paste"
                rows={10}
                value={t.text}
                placeholder={tr("studio.importPage.tpl.forExampleCopiedFromA", { v: EXAMPLE[kind] })}
                aria-invalid={tooLong || (tried && empty)}
                aria-describedby={`${pasteId}-help`}
                onChange={(e) => setTable({ text: e.target.value, fileName: null, parse: null, mapping: [] })}
              />
              <span id={`${pasteId}-help`} className={tooLong || (tried && empty) ? "field-error" : "small muted"} role={tooLong || (tried && empty) ? "alert" : undefined}>
                {tooLong
                  ? tr("studio.importPage.tpl.theTableIsTooLong", { maxtablechars: limits.max_table_chars.toLocaleString("en-IN") })
                  : tried && empty
                    ? tr("studio.importPage.str.pasteATableOrChoose")
                    : tr("studio.importPage.tpl.upToRowsAndColumns", { maxtablerows: limits.max_table_rows.toLocaleString("en-IN"), maxtablecolumns: limits.max_table_columns })}
              </span>
            </div>
            <div className="field">
              <label htmlFor={fileId}>{tr("studio.importPage.text.orChooseAFileCsv")}</label>
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
                  <Icon name="file" size={12} />{" "}{tr("studio.importPage.text.loadedItIsReadIn", { fileName: t.fileName })}
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
                {busy === "parse" ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />}{" "}{tr("studio.importPage.text.readTheTable")}
              </button>
              {state.response ? (
                <button type="button" className="btn ghost" onClick={() => setStep("review")}>
                  {tr("studio.importPage.btn.backToTheDraft")}
                </button>
              ) : null}
            </div>
          </div>
        </section>
      ) : step === "map" ? (
        <>
          <div>
            <button type="button" className="btn sm" onClick={() => setStep("write")}>
              <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> {tr("studio.importPage.btn.changeTheTable")}
            </button>
          </div>
          <ColumnMapper />
        </>
      ) : (
        <>
          <div>
            <button type="button" className="btn sm" onClick={() => setStep(t.parse ? "map" : "write")}>
              <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> {tr("studio.importPage.btn.changeTheColumns")}
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
