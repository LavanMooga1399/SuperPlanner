import { useRef, useState, type ChangeEvent } from "react";
import { useNavigate } from "react-router";
import { errorMessage, importProblem, listProblems, listTemplates } from "../api/client";
import type { ExportFile, Problem } from "../api/types";
import { ErrorBanner, Loading } from "../components/Banner";
import { Icon } from "../components/Icon";
import { PlanList } from "../components/PlanList";
import { TemplateCard } from "../components/TemplateCard";
import { PlanChooser } from "../landing/PlanChooser";
import { useAsync } from "../lib/useAsync";
import { t, t as tr } from "../lib/i18n";

function toExportFile(data: unknown): ExportFile {
  if (typeof data !== "object" || data === null) throw new Error(tr("studio.homePage.str.theFileDoesNotContain"));
  const obj = data as Record<string, unknown>;
  if (obj.format === "superplanner.problem") return obj as unknown as ExportFile;
  if ("tasks" in obj && "horizon_start" in obj) {
    // A bare Problem document: wrap it.
    return { format: "superplanner.problem", format_version: 1, exported_at: new Date().toISOString(), problem: obj as unknown as Problem };
  }
  throw new Error(tr("studio.homePage.str.thisIsNotASuperplanner"));
}

export function HomePage() {
  const navigate = useNavigate();
  const plans = useAsync((s) => listProblems(s), []);
  const templates = useAsync((s) => listTemplates(s), []);
  const fileRef = useRef<HTMLInputElement>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImportError(null);
    setImporting(true);
    try {
      const text = await file.text();
      const rec = await importProblem(toExportFile(JSON.parse(text)));
      navigate(`/plans/${rec.id}/tasks`);
    } catch (err) {
      setImportError(err instanceof SyntaxError ? tr("studio.homePage.str.theFileIsNotValid") : errorMessage(err));
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="col gap-lg">
      <PlanChooser />
      <div className="page-header mt-lg" style={{ marginBottom: 0 }}>
        <div>
          <h2 id="plans-title">{t("studio.homePage.head.yourPlans")}</h2>
          <p>{t("studio.homePage.text.schedulesYouHaveMadeFinancial")}</p>
        </div>
        <div className="row">
          <input ref={fileRef} type="file" accept=".json,application/json" className="sr-only" onChange={onFile} id="import-file" aria-label={t("studio.homePage.aria.importPlanJsonFile")} />
          <button className="btn" onClick={() => fileRef.current?.click()} disabled={importing}>
            {importing ? <span className="spinner" aria-hidden /> : <Icon name="upload" />}
            {tr("studio.homePage.text.importJson")}
          </button>
        </div>
      </div>
      <ErrorBanner error={importError} />
      {plans.loading && !plans.data ? (
        <Loading label={t("studio.homePage.label.loadingPlans")} />
      ) : plans.error ? (
        <ErrorBanner error={plans.error} onRetry={plans.reload} />
      ) : (
        <PlanList items={plans.data?.items ?? []} onChanged={plans.reload} />
      )}

      <section aria-labelledby="templates-title" className="mt">
        <div className="section-title">
          <h2 id="templates-title">{t("studio.homePage.head.startFromAnExample")}</h2>
        </div>
        {templates.loading && !templates.data ? (
          <Loading label={t("studio.homePage.label.loadingTemplates")} />
        ) : templates.error ? (
          <ErrorBanner error={templates.error} onRetry={templates.reload} />
        ) : (
          <div className="grid-3">
            {(templates.data?.items ?? []).map((t) => (
              <TemplateCard key={t.id} template={t} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
