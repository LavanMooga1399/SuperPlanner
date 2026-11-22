import { Icon } from "../../components/Icon";
import { t } from "../../lib/i18n";

/** "1 Write - 2 Answer and check - 3 Create" with the current step marked for screen readers. */
export function StepIndicator({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="step-indicator" aria-label={t("studio.stepIndicator.aria.steps")}>
      {steps.map((s, i) => (
        <li key={s} className={i === current ? "current" : i < current ? "done" : ""} aria-current={i === current ? "step" : undefined}>
          <span className="step-num" aria-hidden>
            {i < current ? <Icon name="check" size={12} /> : i + 1}
          </span>
          <span>
            {s}
            {i < current ? <span className="sr-only"> (done)</span> : null}
          </span>
        </li>
      ))}
    </ol>
  );
}
