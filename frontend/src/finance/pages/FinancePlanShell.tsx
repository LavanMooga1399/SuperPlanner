import { Link, NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import { Banner, ErrorBanner, Loading } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { FinancePlanProvider, useFinancePlan, type FinSaveState } from "../state/FinancePlanContext";

export function FinancePlanShell() {
  const { planId } = useParams();
  if (!planId) return null;
  return (
    <FinancePlanProvider planId={planId} key={planId}>
      <ShellInner />
    </FinancePlanProvider>
  );
}

export function FinSaveIndicator({ state, dirty, error }: { state: FinSaveState; dirty: boolean; error: string | null }) {
  let content;
  if (state === "saving") content = (<><span className="spinner" aria-hidden /> Saving…</>);
  else if (state === "conflict") content = (<><Icon name="alert" /> Conflict</>);
  else if (state === "error") content = (<><Icon name="x" /> Not saved{error ? `: ${error}` : ""}</>);
  else if (dirty) content = (<><Icon name="clock" /> Edited</>);
  else content = (<><Icon name="check" /> Saved</>);
  return (
    <span
      className="save-state"
      data-testid="fin-save-state"
      data-state={state === "saved" && dirty ? "dirty" : state}
      role="status"
      aria-live="polite"
      style={state === "error" || state === "conflict" ? { color: "var(--danger)" } : undefined}
    >
      {content}
    </span>
  );
}

function ShellInner() {
  const plan = useFinancePlan();
  const { pathname } = useLocation();
  const { record, draft, loading, loadError, loadStatus } = plan;
  if (loading && !draft) return <Loading label="Loading your plan…" />;
  if (loadError && !draft) {
    if (loadStatus === 404) {
      return (
        <div className="empty">
          <Icon name="help" size={32} />
          <h2>Plan not found</h2>
          <p>This financial plan does not exist or was deleted.</p>
          <Link className="btn" to="/finance">Back to financial plans</Link>
        </div>
      );
    }
    return <ErrorBanner error={loadError} onRetry={() => void plan.reload()} />;
  }
  if (!draft || !record) return null;
  const base = `/finance/${record.id}`;
  const tabs = [
    { to: `${base}/setup/profile`, label: "Setup", icon: "settings" as const, active: pathname.startsWith(`${base}/setup`) },
    { to: `${base}/results`, label: "Results", icon: "layers" as const, active: pathname.startsWith(`${base}/results`) },
    { to: `${base}/what-if`, label: "What-if", icon: "refresh" as const, active: pathname.startsWith(`${base}/what-if`) },
    { to: `${base}/compare`, label: "Compare", icon: "compare" as const, active: pathname.startsWith(`${base}/compare`) },
  ];
  return (
    <div className="col gap-lg">
      <div className="row wrap between">
        <div className="row wrap">
          <Link to="/finance" className="small">
            Financial plans
          </Link>
          <Icon name="chevron-right" size={12} />
          <strong>{draft.name}</strong>
          <span className="chip" title="Server version of this plan">v{record.version}</span>
        </div>
      </div>
      <nav className="tabs" aria-label="Financial plan sections">
        {tabs.map((t) => (
          <NavLink key={t.label} to={t.to} className={() => `tab${t.active ? " active" : ""}`} aria-current={t.active ? "page" : undefined}>
            <Icon name={t.icon} />
            {t.label}
          </NavLink>
        ))}
      </nav>
      {plan.saveState === "conflict" && !plan.conflictDismissed ? (
        <Banner
          tone="danger"
          role="alert"
          testId="fin-conflict-banner"
          title="This plan was changed elsewhere."
          actions={
            <>
              <button className="btn sm" onClick={() => void plan.reload()}>Reload (discard your edits)</button>
              <button className="btn sm" onClick={() => void plan.keepEditing()}>Keep editing</button>
            </>
          }
        >
          Your latest edits were not saved, so nothing was overwritten. Reload to see the other changes, or keep editing to replace them
          with your version on the next save.
        </Banner>
      ) : null}
      <Outlet />
    </div>
  );
}
