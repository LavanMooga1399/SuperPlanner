import { useId, useState } from "react";
import { useParams } from "react-router";
import { NotFound } from "../../App";
import { Icon } from "../../components/Icon";
import { KINDS, isPlanKind, type PlanKind } from "../../landing/kinds";
import { AiAssistToggle } from "../components/AiAssistToggle";
import { IntakeReview } from "../components/IntakeReview";
import { cpLength } from "../lib/codepoints";
import { IntakeProvider, useIntake } from "../state/IntakeContext";
import { IntakeShell } from "./IntakeShell";

export const PLACEHOLDER: Record<PlanKind, string> = {
  project:
    "For example:\nWebsite relaunch starting next Monday. Ravi and Priya are on the team.\n1. Gather requirements - 2-3 days (Priya)\n2. Design 1 week, after requirements, Priya\n3. Build the site: 2 weeks, Ravi\n4. Testing 3-5 days once the build is done\n5. Launch by 15 Dec 2026",
  study:
    "For example:\nMy exam is in 90 days. I can study three hours on weekdays and eight hours on weekends.\nSubjects: Physics, Chemistry and Maths. I want to revise everything twice and do ten mock tests.",
  production:
    "For example:\nTwo machines, two shifts Monday to Saturday.\nOrder A: cutting 3 h, then welding 2 h, then painting 1 h, due Friday.\nOrder B: cutting 2 h, then assembly 4-5 h, due next Wednesday.",
  money:
    "For example:\nI'm 34, take home about 1.2 lakh a month and my wife earns 60k. Household costs are 70-80k a month, school fees 18k every quarter. Car loan EMI 10k, about 3 lakh left at 9%. We have 6 lakh in savings and 8L in mutual funds. We want 15 lakh for a flat down payment in 3 years and to retire at 60.",
};

const STEPS = ["Write it down", "Answer and check", "Create the plan"];

function DescribeInner({ kind }: { kind: PlanKind }) {
  const { state, capabilities, limits, busy, describe, cancelRequest, setText, setStep } = useIntake();
  const [useAi, setUseAi] = useState(false); // never stored: off on every visit (P3b-2)
  const [tried, setTried] = useState(false);
  const textId = useId();
  const errId = `${textId}-err`;
  const count = cpLength(state.text);
  const max = limits.max_text_chars;
  const tooLong = count > max;
  const empty = !state.text.trim();
  const invalid = tooLong || (tried && empty);
  const aiOn = useAi && !!capabilities?.ai_available;
  const reading = busy === "describe";
  const info = KINDS[kind];

  const submit = () => {
    setTried(true);
    if (empty || tooLong || reading) return;
    void describe(aiOn);
  };

  const current = state.step !== "review" ? 0 : state.response?.questions.length === 0 && state.build?.ready ? 2 : 1;

  return (
    <IntakeShell
      kind={kind}
      title={`Describe your ${info.planNoun === "money" ? "money goals" : `${info.planNoun} plan`}`}
      intro="Write it the way you would explain it to a colleague. We turn it into a draft you can check and change; nothing is calculated or saved until you create the plan."
      steps={STEPS}
      current={current}
    >
      {state.step !== "review" ? (
        <section className="card" aria-labelledby={`${textId}-title`}>
          <div className="card-body col" style={{ gap: 12 }}>
            <form
              className="col"
              style={{ gap: 12 }}
              onSubmit={(e) => {
                e.preventDefault();
                submit();
              }}
            >
              <div className="field">
                <label htmlFor={textId} id={`${textId}-title`} style={{ fontSize: 14 }}>
                  Your {info.planNoun === "money" ? "situation and goals" : "plan"} in your own words
                </label>
                <textarea
                  id={textId}
                  className="textarea intake-textarea"
                  data-testid="intake-text"
                  rows={10}
                  value={state.text}
                  placeholder={PLACEHOLDER[kind]}
                  aria-invalid={invalid}
                  aria-describedby={`${textId}-count${invalid ? ` ${errId}` : ""}`}
                  disabled={reading}
                  onChange={(e) => setText(e.target.value)}
                />
                <div className="row small" style={{ justifyContent: "space-between" }}>
                  <span className="muted">Lists, sentences and ranges like "2-3 days" or "70-80k" all work.</span>
                  <span id={`${textId}-count`} className={tooLong ? "field-error" : "muted"} data-testid="intake-count">
                    {count.toLocaleString()} / {max.toLocaleString()} characters
                  </span>
                </div>
                {invalid ? (
                  <span id={errId} className="field-error" role="alert">
                    <Icon name="alert" size={12} />{" "}
                    {tooLong ? `The text is too long: at most ${max.toLocaleString()} characters.` : "Write a few lines about your plan first."}
                  </span>
                ) : null}
              </div>
              <AiAssistToggle capabilities={capabilities} on={aiOn} onChange={setUseAi} disabled={reading} />
              <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                <button type="submit" className="btn primary" data-testid="intake-submit" disabled={reading}>
                  {reading ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />}
                  {aiOn ? "Send to AI assist and make a draft" : "Make a draft"}
                </button>
                {reading ? (
                  <>
                    <span className="small muted" role="status">
                      {aiOn ? "AI assist is reading your text. This can take up to 3 minutes." : "Reading your text…"}
                    </span>
                    <button type="button" className="btn" data-testid="intake-cancel-request" onClick={cancelRequest}>
                      Stop
                    </button>
                  </>
                ) : null}
                {state.response ? (
                  <button type="button" className="btn ghost" onClick={() => setStep("review")}>
                    Back to the draft
                  </button>
                ) : null}
              </div>
              {state.response ? (
                <span className="small muted">Making a new draft replaces the current draft and your answers.</span>
              ) : null}
            </form>
          </div>
        </section>
      ) : (
        <>
          <div className="row" style={{ gap: 8 }}>
            <button type="button" className="btn sm" onClick={() => setStep("write")} data-testid="intake-edit-text">
              <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> Change the text
            </button>
          </div>
          <IntakeReview />
        </>
      )}
    </IntakeShell>
  );
}

/** `/new/:kind/describe`: write, then questions, review and create on one page (PHASE2.md 3.3). */
export function DescribePage() {
  const { kind } = useParams();
  if (!isPlanKind(kind)) return <NotFound />;
  return (
    <IntakeProvider key={`${kind}-describe`} kind={kind} flow="describe">
      <DescribeInner kind={kind} />
    </IntakeProvider>
  );
}
