import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { ErrorBanner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { KINDS, type PlanKind } from "../../landing/kinds";
import { useIntake } from "../state/IntakeContext";
import { StepIndicator } from "../components/StepIndicator";

/** Page frame shared by the describe and import flows: breadcrumb, title, steps, error, Cancel. */
export function IntakeShell({
  kind,
  title,
  intro,
  steps,
  current,
  children,
}: {
  kind: PlanKind;
  title: string;
  intro: string;
  steps: string[];
  current: number;
  children: ReactNode;
}) {
  const { error, clearError, cancel, state } = useIntake();
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    document.title = `${title} - SuperPlanner`;
    return () => {
      document.title = "SuperPlanner Studio";
    };
  }, [title]);
  const hasWork = !!state.response || !!state.text.trim() || !!state.table.text.trim();
  return (
    <div className="col gap-lg intake-page" data-testid={`intake-page-${kind}`}>
      <nav aria-label="Breadcrumb" className="small">
        <Link to={`/new/${kind}`}>
          <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> New {KINDS[kind].label.toLowerCase()}
        </Link>
      </nav>
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div>
          <h1>{title}</h1>
          <p>{intro}</p>
        </div>
        <button type="button" className="btn" data-testid="intake-cancel" onClick={() => (hasWork ? setConfirm(true) : cancel())}>
          Cancel
        </button>
      </div>
      <StepIndicator steps={steps} current={current} />
      <ErrorBanner error={error} />
      {error ? (
        <div>
          <button type="button" className="btn sm ghost" onClick={clearError}>
            Dismiss message
          </button>
        </div>
      ) : null}
      {children}
      {confirm ? (
        <ConfirmDialog
          title="Leave without creating a plan?"
          confirmLabel="Leave"
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            cancel();
          }}
        >
          Your {state.flow === "import" ? "table" : "text"}, the draft and your answers are discarded. Nothing was saved.
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
