import { useRef, useState, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage, importProblem, listProblems, listTemplates } from "../api/client";
import type { ExportFile, Problem } from "../api/types";
import { ErrorBanner, Loading } from "../components/Banner";
import { Icon } from "../components/Icon";
import { PlanList } from "../components/PlanList";
import { TemplateCard } from "../components/TemplateCard";
import { useAsync } from "../lib/useAsync";

function toExportFile(data: unknown): ExportFile {
  if (typeof data !== "object" || data === null) throw new Error("The file does not contain a JSON object.");
  const obj = data as Record<string, unknown>;
  if (obj.format === "superplanner.problem") return obj as unknown as ExportFile;
  if ("tasks" in obj && "horizon_start" in obj) {
    // A bare Problem document: wrap it.
    return { format: "superplanner.problem", format_version: 1, exported_at: new Date().toISOString(), problem: obj as unknown as Problem };
  }
  throw new Error("This is not a SuperPlanner plan file (expected format \"superplanner.problem\").");
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
      setImportError(err instanceof SyntaxError ? "The file is not valid JSON." : errorMessage(err));
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="col gap-lg">
      <div className="page-header">
        <div>
          <h1>Your plans</h1>
          <p>Describe what has to be done, with what and by when; SuperPlanner finds a schedule that works.</p>
        </div>
        <div className="row">
          <input ref={fileRef} type="file" accept=".json,application/json" className="sr-only" onChange={onFile} id="import-file" aria-label="Import plan JSON file" />
          <button className="btn" onClick={() => fileRef.current?.click()} disabled={importing}>
            {importing ? <span className="spinner" aria-hidden /> : <Icon name="upload" />}
            Import JSON
          </button>
        </div>
      </div>
      <ErrorBanner error={importError} />
      {plans.loading && !plans.data ? (
        <Loading label="Loading plans…" />
      ) : plans.error ? (
        <ErrorBanner error={plans.error} onRetry={plans.reload} />
      ) : (
        <PlanList items={plans.data?.items ?? []} onChanged={plans.reload} />
      )}

      <section aria-labelledby="templates-title" className="mt">
        <div className="section-title">
          <h2 id="templates-title">Create from template</h2>
        </div>
        {templates.loading && !templates.data ? (
          <Loading label="Loading templates…" />
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
