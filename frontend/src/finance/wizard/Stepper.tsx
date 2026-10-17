import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import { STEPS, type StepKey } from "./steps";

export function Stepper({ planId, current, done, issues }: { planId: string; current: StepKey; done: Set<string>; issues: Set<StepKey> }) {
  return (
    <nav aria-label="Plan setup steps">
      <ol className="stepper">
        {STEPS.map((s, i) => {
          const isCur = s.key === current;
          const hasIssue = issues.has(s.key);
          const isDone = done.has(s.key);
          const mark = hasIssue ? "issue" : isDone ? "done" : isCur ? "current" : "";
          const stateText = hasIssue ? "needs attention" : isDone ? "done" : isCur ? "current step" : "not started";
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
