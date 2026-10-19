import { Icon } from "../../components/Icon";

/** "1 Write - 2 Answer and check - 3 Create" with the current step marked for screen readers. */
export function StepIndicator({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="step-indicator" aria-label="Steps">
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
