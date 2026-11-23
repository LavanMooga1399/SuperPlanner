import { useRef, useState, type ChangeEvent } from "react";
import { Link, useNavigate } from "react-router";
import { errorMessage } from "../../api/client";
import { ErrorBanner, Loading } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { useAsync } from "../../lib/useAsync";
import { fmtRelative } from "../../lib/time";
import { deleteFinancePlan, importFinancePlan, listFinancePlans } from "../api/client";
import type { FinanceExportFile, FinancePlan, FinancePlanSummary } from "../api/types";
import { FinanceTemplateCards } from "../components/FinanceTemplateCards";
import { StatusPill } from "../components/StatusPill";
import { startBlankFinancePlan } from "../lib/startBlank";
import { PageHeader } from "../../components/PageHeader";
import { plural, t } from "../../lib/i18n";

function toExportFile(data: unknown): FinanceExportFile {
  if (typeof data !== "object" || data === null) throw new Error(t("finance.financeHome.str.theFileDoesNotContain"));
  const obj = data as Record<string, unknown>;
  if (obj.format === "superplanner.finance_plan") return obj as unknown as FinanceExportFile;
  if ("goals" in obj && "name" in obj && !("tasks" in obj)) {
    return { format: "superplanner.finance_plan", format_version: 1, exported_at: new Date().toISOString(), plan: obj as unknown as FinancePlan };
  }
  throw new Error(t("finance.financeHome.str.thisIsNotASuperplanner"));
}

export function FinanceHome() {
  const navigate = useNavigate();
  const plans = useAsync((s) => listFinancePlans(s), []);
  const fileRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const startBlank = async () => {
    setBusy("blank");
    setError(null);
    try {
      const rec = await startBlankFinancePlan();
      navigate(`/finance/${rec.id}/setup/profile`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(null);
    }
  };

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy("import");
    setError(null);
    try {
      const rec = await importFinancePlan(toExportFile(JSON.parse(await file.text())));
      navigate(`/finance/${rec.id}/setup/review`);
    } catch (err) {
      setError(err instanceof SyntaxError ? t("finance.financeHome.str.theFileIsNotValid") : errorMessage(err));
      setBusy(null);
    }
  };

  return (
    <div className="col gap-lg">
      <PageHeader
        title={t("finance.financeHome.title.financialPlans")}
        description={t("finance.financeHome.desc.planWhereWhenAndHow")}
        actions={
          <>
            <input ref={fileRef} type="file" accept=".json,application/json" className="sr-only" onChange={onFile} id="fin-import-file" aria-label={t("finance.financeHome.aria.importFinancialPlanJsonFile")} />
          <button className="btn" onClick={() => fileRef.current?.click()} disabled={busy !== null}>
            {busy === "import" ? <span className="spinner" aria-hidden /> : <Icon name="upload" />}{" "}{t("finance.financeHome.text.importJson")}
          </button>
          <button className="btn primary" onClick={() => void startBlank()} disabled={busy !== null} data-testid="fin-start-blank">
            {busy === "blank" ? <span className="spinner" aria-hidden /> : <Icon name="plus" />}{" "}{t("finance.financeHome.text.startFromScratch")}
          </button></>} />
      <ErrorBanner error={error} />

      {plans.loading && !plans.data ? (
        <Loading label={t("finance.financeHome.label.loadingFinancialPlans")} />
      ) : plans.error ? (
        <ErrorBanner error={plans.error} onRetry={plans.reload} />
      ) : (
        <PlanList items={plans.data?.items ?? []} onChanged={plans.reload} />
      )}

      <section aria-labelledby="fin-templates-title" className="mt">
        <div className="section-title">
          <h2 id="fin-templates-title">{t("finance.financeHome.head.startFromAnExample")}</h2>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>{t("finance.financeHome.text.examplesComeWithSensibleDefaults")}</p>
        <FinanceTemplateCards />
      </section>
    </div>
  );
}

function PlanList({ items, onChanged }: { items: FinancePlanSummary[]; onChanged(): void }) {
  const [toDelete, setToDelete] = useState<FinancePlanSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const doDelete = async () => {
    if (!toDelete) return;
    setBusy(true);
    setError(null);
    try {
      await deleteFinancePlan(toDelete.id);
      setToDelete(null);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card" aria-labelledby="fin-plans-title">
      <div className="card-header">
        <h2 id="fin-plans-title">{t("finance.financeHome.head.yourFinancialPlans")}</h2>
        <span className="small muted">{plural(items.length, "plan")}</span>
      </div>
      {error ? <div className="card-body"><ErrorBanner error={error} /></div> : null}
      <div data-testid="fin-plan-list">
        {items.length === 0 ? (
          <div className="empty">
            <Icon name="briefcase" size={28} />
            <p>{t("finance.financeHome.text.noFinancialPlansYetStart")}</p>
          </div>
        ) : (
          items.map((p) => (
            <div className="fin-plan-row" key={p.id} data-testid={`fin-plan-${p.id}`}>
              <div className="grow col" style={{ gap: 2 }}>
                <Link to={`/finance/${p.id}`} className="plan-name" style={{ fontWeight: 620 }}>
                  {p.name}
                </Link>
                <span className="small muted">
                  {t("finance.financeHome.text.edited", { goalcount: plural(p.goal_count, "goal"), currency: p.currency, updatedat: fmtRelative(p.updated_at) })}
                </span>
              </div>
              {p.latest_result ? (
                <span className="row small">
                  <StatusPill kind={p.latest_result.feasibility} />
                  <span className="muted">
                    {t("finance.financeHome.text.onTrack", { t: t("common.nOfM", { n: p.latest_result.goals_on_track, m: p.latest_result.goals_total }) })}
                  </span>
                </span>
              ) : (
                <span className="small muted">{t("finance.financeHome.text.notBuiltYet")}</span>
              )}
              {p.latest_run && (p.latest_run.status === "queued" || p.latest_run.status === "running") ? <StatusPill kind={p.latest_run.status} /> : null}
              <button className="btn sm ghost" onClick={() => setToDelete(p)} aria-label={`Delete ${p.name}`}>
                <Icon name="trash" />
              </button>
            </div>
          ))
        )}
      </div>
      {toDelete ? (
        <ConfirmDialog title={t("finance.financeHome.title.deleteFinancialPlan")} confirmLabel={t("finance.financeHome.btn.delete")} danger busy={busy} onConfirm={() => void doDelete()} onCancel={() => setToDelete(null)}>
          <p style={{ margin: 0 }}>
            {t("finance.financeHome.text.andAllItsResultsWill", { name: toDelete.name })}
          </p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}
