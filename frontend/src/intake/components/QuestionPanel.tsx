import { useEffect, useId, useRef, useState } from "react";
import { Icon } from "../../components/Icon";
import type { Question } from "../api/types";
import { quickAnswer, useIntake } from "../state/IntakeContext";
import { answerValue, initialValue, QuestionInput, type QValue } from "./QuestionInput";

function valueLabel(q: Question, v: unknown): string {
  if (v === undefined || v === null) return "";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) {
    return v.map((x) => q.options.find((o) => o.value === x)?.label ?? String(x)).join(", ");
  }
  if (typeof v === "object") {
    if ("text" in (v as object)) return String((v as { text: string }).text);
    if ("days" in (v as object)) {
      const wt = v as { days: string[]; windows: { start: string; end: string }[] };
      return `${wt.days.join(", ")} ${wt.windows.map((w) => `${w.start}-${w.end}`).join(", ")}`;
    }
    return JSON.stringify(v);
  }
  const s = String(v);
  return q.options.find((o) => o.value === s)?.label ?? s;
}

/**
 * Chat-like follow-up questions (PHASE2.md 3.3): earlier answers as bubbles, then the one open question with
 * its input, "Use suggestion", "Skip" and "Use suggestions for all remaining". The live region announces
 * the next question.
 */
export function QuestionPanel() {
  const { state, busy, answer, useAllSuggestions, setActivePath } = useIntake();
  const questions = state.response?.questions ?? [];
  const q = questions[0] ?? null;
  const [value, setValue] = useState<QValue>(q ? initialValue(q) : null);
  const [touchedEmpty, setTouchedEmpty] = useState(false);
  const promptId = useId();
  const listRef = useRef<HTMLOListElement>(null);
  const qKey = q ? `${q.id}|${q.error ?? ""}` : "";

  useEffect(() => {
    setValue(q ? initialValue(q) : null);
    setTouchedEmpty(false);
    // reset only when another question (or a new error for it) is shown
  }, [qKey]);

  useEffect(() => {
    listRef.current?.lastElementChild?.scrollIntoView?.({ block: "nearest" });
  }, [state.history.length]);

  const working = busy === "answer";
  const quickCount = questions.filter((x) => !x.error && quickAnswer(x) !== null).length;
  const hasDefault = !!q && q.default !== null && q.default !== undefined;

  const submit = () => {
    if (!q || working) return;
    const v = answerValue(q, value);
    if (v === undefined) {
      setTouchedEmpty(true);
      return;
    }
    void answer([{ question_id: q.id, value: v }], [{ id: q.id, prompt: q.prompt, answer: valueLabel(q, v) }]);
  };

  return (
    <section className="card question-panel" aria-labelledby="intake-questions-title">
      <div className="card-header">
        <h3 id="intake-questions-title" style={{ margin: 0 }}>
          A few questions
        </h3>
        <span className="small muted" data-testid="intake-questions-left">
          {questions.length === 0 ? "All done" : `${questions.length} left${questions.some((x) => x.required) ? `, ${questions.filter((x) => x.required).length} needed` : ""}`}
        </span>
      </div>
      <div className="card-body col" style={{ gap: 10 }}>
        {state.history.length ? (
          <ol className="chat-log" ref={listRef} aria-label="Questions answered so far">
            {state.history.map((h, i) => (
              <li key={`${h.id}-${i}`} className="chat-pair">
                <div className="bubble ask">{h.prompt}</div>
                <div className="bubble reply">{h.answer}</div>
              </li>
            ))}
          </ol>
        ) : null}

        <div aria-live="polite" className="sr-only" data-testid="intake-live">
          {q ? `Question: ${q.prompt}` : "No more questions."}
        </div>

        {q ? (
          <div
            className="bubble ask current"
            data-testid={`intake-question-${q.code}`}
            data-question-id={q.id}
            onMouseEnter={() => q.path && setActivePath(q.path)}
            onMouseLeave={() => setActivePath(null)}
          >
            <div className="row" style={{ alignItems: "flex-start", gap: 6 }}>
              <Icon name={q.required ? "alert" : "help"} size={16} />
              <div className="grow col" style={{ gap: 6 }}>
                <div id={promptId} className="question-prompt">
                  {q.prompt}
                  {q.required ? <span className="chip needed">Needed</span> : <span className="chip">Optional</span>}
                </div>
                {q.span ? <div className="small muted">From your text: "{q.span.text}"</div> : null}
                {hasDefault && q.default_label ? <div className="small muted">Suggestion: {q.default_label}</div> : null}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    submit();
                  }}
                  className="col"
                  style={{ gap: 8 }}
                >
                  <QuestionInput q={q} value={value} onChange={(v) => (setValue(v), setTouchedEmpty(false))} onSubmit={submit} labelId={promptId} />
                  {touchedEmpty ? (
                    <span className="field-error" role="alert">
                      <Icon name="alert" size={12} /> Enter an answer{hasDefault ? ", or use the suggestion" : ""}
                      {!q.required ? " or skip this question" : ""}.
                    </span>
                  ) : null}
                  <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
                    <button type="submit" className="btn primary sm" data-testid="intake-answer" disabled={working}>
                      {working ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Answer
                    </button>
                    {hasDefault ? (
                      <button
                        type="button"
                        className="btn sm"
                        data-testid="intake-use-default"
                        disabled={working}
                        onClick={() =>
                          void answer([{ question_id: q.id, use_default: true }], [
                            { id: q.id, prompt: q.prompt, answer: `Suggestion used${q.default_label ? `: ${q.default_label}` : ""}` },
                          ])
                        }
                      >
                        Use suggestion
                      </button>
                    ) : null}
                    {!q.required ? (
                      <button
                        type="button"
                        className="btn sm"
                        data-testid="intake-skip"
                        disabled={working}
                        onClick={() => void answer([{ question_id: q.id, skip: true }], [{ id: q.id, prompt: q.prompt, answer: "Skipped" }])}
                      >
                        Skip
                      </button>
                    ) : null}
                  </div>
                </form>
              </div>
            </div>
          </div>
        ) : (
          <div className="small muted row" data-testid="intake-no-questions">
            <Icon name="check" /> No open questions. Check the draft, then create the plan.
          </div>
        )}

        {quickCount > 0 ? (
          <button
            type="button"
            className="btn sm"
            data-testid="intake-use-all-defaults"
            disabled={working}
            onClick={() => void useAllSuggestions()}
          >
            <Icon name="check" /> Use suggestions for all remaining
          </button>
        ) : null}
      </div>
    </section>
  );
}
