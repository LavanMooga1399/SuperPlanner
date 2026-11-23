import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import { STEPS, type StepKey } from "./steps";
import { t } from "../../lib/i18n";

export function Stepper({ planId, current, done, issues }: { planId: string; current: StepKey; done: Set<string>; issues: Set<StepKey> }) {
  return (
    <nav aria-label={t("finance.stepper.aria.planSetupSteps")}>
      <ol className="stepper">
        {STEPS.map((s, i) => {
          const isCur = s.key === current;
          const hasIssue = issues.has(s.key);
          const isDone = done.has(s.key);
          const mark = hasIssue ? "issue" : isDone ? "done" : isCur ? "current" : "";
          const stateText = hasIssue ? t("finance.stepper.str.needsAttention") : isDone ? "done" : isCur ? t("finance.stepper.str.currentStep") : t("finance.stepper.str.notStarted");
          return (
            <li key={s.key}>
              <Link to={`/finance/${planId}/setup/${s.key}`} aria-current={isCur ? "step" : undefined} data-testid={`wizard-step-${s.key}`}>
                <span className={`step-mark ${mark}`} aria-hidden>
                  {hasIssue ? <Icon name="alert" size={12} /> : isDone ? <Icon name="check" size={12} /> : i + 1}
                </span>
                <span>{s.label}</span>
                <span className="sr-only">({stateText})</span>
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
