import { Link, NavLink, Outlet, useLocation, useParams } from "react-router";
import { Banner, ErrorBanner, Loading } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { FinancePlanProvider, useFinancePlan, type FinSaveState } from "../state/FinancePlanContext";
import { t, t as tr } from "../../lib/i18n";

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
  if (state === "saving") content = (<><span className="spinner" aria-hidden />{" "}{tr("finance.financePlanShell.text.saving")}</>);
  else if (state === "conflict") content = (<><Icon name="alert" />{" "}{tr("finance.financePlanShell.text.conflict")}</>);
  else if (state === "error") content = (<><Icon name="x" />{" "}{tr("finance.financePlanShell.text.notSaved", { v: error ? `: ${error}` : "" })}</>);
  else if (dirty) content = (<><Icon name="clock" />{" "}{tr("finance.financePlanShell.text.edited")}</>);
  else content = (<><Icon name="check" />{" "}{tr("finance.financePlanShell.text.saved")}</>);
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
  if (loading && !draft) return <Loading label={t("finance.financePlanShell.label.loadingYourPlan")} />;
  if (loadError && !draft) {
    if (loadStatus === 404) {
      return (
        <div className="empty">
          <Icon name="help" size={32} />
          <h2>{t("finance.financePlanShell.head.planNotFound")}</h2>
          <p>{t("finance.financePlanShell.text.thisFinancialPlanDoesNot")}</p>
          <Link className="btn" to="/finance">{tr("finance.financePlanShell.text.backToFinancialPlans")}</Link>
        </div>
      );
    }
    return <ErrorBanner error={loadError} onRetry={() => void plan.reload()} />;
  }
  if (!draft || !record) return null;
  const base = `/finance/${record.id}`;
  const tabs = [
    { to: `${base}/setup/profile`, label: tr("finance.financePlanShell.str.setup"), icon: "settings" as const, active: pathname.startsWith(`${base}/setup`) },
    { to: `${base}/results`, label: tr("finance.financePlanShell.str.results"), icon: "layers" as const, active: pathname.startsWith(`${base}/results`) },
    { to: `${base}/what-if`, label: "What-if", icon: "refresh" as const, active: pathname.startsWith(`${base}/what-if`) },
    { to: `${base}/compare`, label: tr("finance.financePlanShell.str.compare"), icon: "compare" as const, active: pathname.startsWith(`${base}/compare`) },
  ];
  return (
    <div className="col gap-lg">
      <div className="row wrap between">
        <div className="row wrap">
          <Link to="/finance" className="small">
            {t("finance.financePlanShell.btn.financialPlans")}
          </Link>
          <Icon name="chevron-right" size={12} />
          <strong>{draft.name}</strong>
          <span className="chip" title={tr("finance.financePlanShell.attr.serverVersionOfThisPlan")}>v{record.version}</span>
        </div>
      </div>
      <nav className="tabs" aria-label={t("finance.financePlanShell.aria.financialPlanSections")}>
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
          title={t("finance.financePlanShell.title.thisPlanWasChangedElsewhere")}
          actions={
            <>
              <button className="btn sm" onClick={() => void plan.reload()}>{tr("finance.financePlanShell.text.reloadDiscardYourEdits")}</button>
              <button className="btn sm" onClick={() => void plan.keepEditing()}>{tr("finance.financePlanShell.text.keepEditing")}</button>
            </>
          }
        >
          {tr("finance.financePlanShell.text.yourLatestEditsWereNot")}
        </Banner>
      ) : null}
      <Outlet />
    </div>
  );
}
