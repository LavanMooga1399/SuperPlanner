import { useNavigate } from "react-router";
import { Icon } from "../components/Icon";
import { ACTION_HINT, ACTION_ICON, ACTION_LABEL, KINDS, START_ACTIONS, actionPath, type PlanKind } from "./kinds";
import type { useStepByStep } from "./startPlan";

/** One kind of plan with its four ways to start (test ids of PHASE2.md 3.2). */
export function KindCard({
  kind,
  steps,
  headingLevel = 2,
  large = false,
}: {
  kind: PlanKind;
  steps: ReturnType<typeof useStepByStep>;
  headingLevel?: 2 | 3;
  large?: boolean;
}) {
  const navigate = useNavigate();
  const info = KINDS[kind];
  const titleId = `landing-kind-${kind}-title`;
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const busy = steps.busy === kind;
  const error = steps.error?.kind === kind ? steps.error.message : null;
  return (
    <section
      role="group"
      aria-labelledby={titleId}
      className={`card kind-card${large ? " large" : ""}`}
      data-testid={`landing-kind-${kind}`}
    >
      <div className="card-body">
        <div className="row">
          <span className="template-icon" aria-hidden>
            <Icon name={info.icon} size={20} />
          </span>
          <div className="grow">
            <Heading id={titleId} className="kind-title">
              {info.label}
            </Heading>
            <div className="small muted">{info.description}</div>
          </div>
        </div>
        <div className={`kind-actions${large ? " large" : ""}`}>
          {START_ACTIONS.map((a) => (
            <button
              key={a}
              type="button"
              className={`btn kind-action${a === "describe" ? " primary" : ""}`}
              data-testid={`landing-action-${kind}-${a}`}
              aria-describedby={large ? `landing-hint-${kind}-${a}` : undefined}
              disabled={steps.busy !== null && a === "steps"}
              onClick={() => (a === "steps" ? void steps.start(kind) : navigate(actionPath(kind, a)))}
            >
              {a === "steps" && busy ? <span className="spinner" aria-hidden /> : <Icon name={ACTION_ICON[a]} />}
              <span className="kind-action-text">
                <span>{ACTION_LABEL[a]}</span>
                {large ? (
                  <span id={`landing-hint-${kind}-${a}`} className="kind-action-hint">
                    {ACTION_HINT[a]}
                  </span>
                ) : null}
              </span>
            </button>
          ))}
        </div>
        {error ? (
          <div className="small field-error" role="alert">
            <Icon name="alert" size={14} /> {error}
          </div>
        ) : null}
      </div>
    </section>
  );
}
