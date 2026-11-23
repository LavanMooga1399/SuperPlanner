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
import { t } from "../../lib/i18n";

export const PLACEHOLDER: Record<PlanKind, string> = {
  project:
    t("studio.describePage.str.forExampleWebsiteRelaunchStarting"),
  study:
    t("studio.describePage.str.forExampleMyExamIs"),
  production:
    t("studio.describePage.str.forExampleTwoMachinesTwo"),
  money:
    t("studio.describePage.str.forExampleIM34"),
};

const STEPS = [t("studio.describePage.str.writeItDown"), t("studio.describePage.str.answerAndCheck"), t("studio.describePage.str.createThePlan")];

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
      title={`Describe your ${info.planNoun === "money" ? t("studio.describePage.str.moneyGoals") : `${info.planNoun} plan`}`}
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
                  {t("studio.describePage.text.yourInYourOwnWords", { v: info.planNoun === "money" ? t("studio.describePage.str.situationAndGoals") : "plan" })}
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
                  <span className="muted">{t("studio.describePage.text.listsSentencesAndRangesLike")}</span>
                  <span id={`${textId}-count`} className={tooLong ? "field-error" : "muted"} data-testid="intake-count">
                    {count.toLocaleString("en-IN")} / {max.toLocaleString("en-IN")} characters
                  </span>
                </div>
                {invalid ? (
                  <span id={errId} className="field-error" role="alert">
                    <Icon name="alert" size={12} />{" "}
                    {tooLong ? t("studio.describePage.tpl.theTextIsTooLong", { max: max.toLocaleString("en-IN") }) : t("studio.describePage.str.writeAFewLinesAbout")}
                  </span>
                ) : null}
              </div>
              <AiAssistToggle capabilities={capabilities} on={aiOn} onChange={setUseAi} disabled={reading} />
              <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                <button type="submit" className="btn primary" data-testid="intake-submit" disabled={reading}>
                  {reading ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />}
                  {aiOn ? t("studio.describePage.str.sendToAiAssistAnd") : t("studio.describePage.str.makeADraft")}
                </button>
                {reading ? (
                  <>
                    <span className="small muted" role="status">
                      {aiOn ? t("studio.describePage.str.aiAssistIsReadingYour") : t("studio.describePage.str.readingYourText")}
                    </span>
                    <button type="button" className="btn" data-testid="intake-cancel-request" onClick={cancelRequest}>
                      {t("studio.describePage.btn.stop")}
                    </button>
                  </>
                ) : null}
                {state.response ? (
                  <button type="button" className="btn ghost" onClick={() => setStep("review")}>
                    {t("studio.describePage.btn.backToTheDraft")}
                  </button>
                ) : null}
              </div>
              {state.response ? (
                <span className="small muted">{t("studio.describePage.text.makingANewDraftReplaces")}</span>
              ) : null}
            </form>
          </div>
        </section>
      ) : (
        <>
          <div className="row" style={{ gap: 8 }}>
            <button type="button" className="btn sm" onClick={() => setStep("write")} data-testid="intake-edit-text">
              <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> {t("studio.describePage.btn.changeTheText")}
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
