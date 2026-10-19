import { Icon } from "../../components/Icon";
import type { FinanceDraft, IntakeNote, ScheduleDraft } from "../api/types";
import { useIntake } from "../state/IntakeContext";
import { CreatePlanBar } from "./CreatePlanBar";
import { ExtractorBanner } from "./ExtractorBanner";
import { FinanceDraftEditor } from "./FinanceDraftEditor";
import { QuestionPanel } from "./QuestionPanel";
import { ScheduleDraftEditor } from "./ScheduleDraftEditor";
import { SourceText } from "./SourceText";

function NoteList({ notes, testId, title, emptyText }: { notes: IntakeNote[]; testId: string; title: string; emptyText?: string }) {
  if (!notes.length && !emptyText) return null;
  return (
    <section className="card" aria-label={title} data-testid={testId}>
      <div className="card-body col" style={{ gap: 4 }}>
        <strong className="small">{title}</strong>
        {!notes.length ? <span className="small muted">{emptyText}</span> : null}
        <ul className="intake-notes">
          {notes.map((n, i) => (
            <li key={i} className={`issue-line ${n.severity}`} data-code={n.code}>
              <Icon name={n.severity === "warning" ? "alert" : "info"} size={14} />
              <span>
                <span className="sr-only">{n.severity === "warning" ? "Warning: " : "Note: "}</span>
                {n.message}
                {n.span ? <span className="muted"> ("{n.span.text}")</span> : null}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/** Questions on the left (with the source text), the editable draft on the right, review and create below. */
export function IntakeReview() {
  const { state } = useIntake();
  const resp = state.response;
  if (!resp) return null;
  const draft = resp.draft;
  return (
    <div className="col" style={{ gap: 14 }}>
      <ExtractorBanner info={resp.extractor} fromTable={state.flow === "import"} />
      <NoteList notes={resp.notes} testId="intake-notes" title="Notes about what was read" />
      {state.flow === "import" ? <NoteList notes={resp.row_notes} testId="import-row-notes" title="Rows to check" emptyText="Every row was read without problems." /> : null}
      <div className="intake-grid">
        <div className="col" style={{ gap: 14 }}>
          <QuestionPanel />
          {state.sourceText ? <SourceText text={state.sourceText} draft={draft} notes={resp.notes} questions={resp.questions} /> : null}
        </div>
        <section className="card" aria-labelledby="intake-draft-title">
          <div className="card-header">
            <h2 id="intake-draft-title" style={{ margin: 0, fontSize: 16 }}>
              Draft
            </h2>
            <span className="small muted">Change anything here; nothing is saved yet</span>
          </div>
          <div className="card-body" data-testid="intake-draft">
            {draft.domain === "schedule" ? <ScheduleDraftEditor draft={draft as ScheduleDraft} /> : <FinanceDraftEditor draft={draft as FinanceDraft} />}
          </div>
        </section>
      </div>
      <CreatePlanBar />
    </div>
  );
}
