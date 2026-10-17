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

function toExportFile(data: unknown): FinanceExportFile {
  if (typeof data !== "object" || data === null) throw new Error("The file does not contain a JSON object.");
  const obj = data as Record<string, unknown>;
  if (obj.format === "superplanner.finance_plan") return obj as unknown as FinanceExportFile;
  if ("goals" in obj && "name" in obj && !("tasks" in obj)) {
    return { format: "superplanner.finance_plan", format_version: 1, exported_at: new Date().toISOString(), plan: obj as unknown as FinancePlan };
  }
  throw new Error('This is not a SuperPlanner financial plan file (expected format "superplanner.finance_plan").');
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
      setError(err instanceof SyntaxError ? "The file is not valid JSON." : errorMessage(err));
      setBusy(null);
    }
  };

  return (
    <div className="col gap-lg">
      <div className="page-header">
        <div>
          <h1>Financial plans</h1>
          <p>Plan where, when and how much to save for each goal, with an honest estimate of the chance of reaching it.</p>
        </div>
        <div className="row wrap">
          <input ref={fileRef} type="file" accept=".json,application/json" className="sr-only" onChange={onFile} id="fin-import-file" aria-label="Import financial plan JSON file" />
          <button className="btn" onClick={() => fileRef.current?.click()} disabled={busy !== null}>
            {busy === "import" ? <span className="spinner" aria-hidden /> : <Icon name="upload" />} Import JSON
          </button>
          <button className="btn primary" onClick={() => void startBlank()} disabled={busy !== null} data-testid="fin-start-blank">
            {busy === "blank" ? <span className="spinner" aria-hidden /> : <Icon name="plus" />} Start from scratch
          </button>
        </div>
      </div>
      <ErrorBanner error={error} />

      {plans.loading && !plans.data ? (
        <Loading label="Loading financial plans…" />
      ) : plans.error ? (
        <ErrorBanner error={plans.error} onRetry={plans.reload} />
      ) : (
        <PlanList items={plans.data?.items ?? []} onChanged={plans.reload} />
      )}

      <section aria-labelledby="fin-templates-title" className="mt">
        <div className="section-title">
          <h2 id="fin-templates-title">Start from an example</h2>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>Examples come with sensible defaults; you can change everything in the next steps.</p>
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
        <h2 id="fin-plans-title">Your financial plans</h2>
        <span className="small muted">{items.length} plan{items.length === 1 ? "" : "s"}</span>
      </div>
      {error ? <div className="card-body"><ErrorBanner error={error} /></div> : null}
      <div data-testid="fin-plan-list">
        {items.length === 0 ? (
          <div className="empty">
            <Icon name="briefcase" size={28} />
            <p>No financial plans yet. Start from scratch or pick an example below.</p>
          </div>
        ) : (
          items.map((p) => (
            <div className="fin-plan-row" key={p.id} data-testid={`fin-plan-${p.id}`}>
              <div className="grow col" style={{ gap: 2 }}>
                <Link to={`/finance/${p.id}`} className="plan-name" style={{ fontWeight: 620 }}>
                  {p.name}
                </Link>
                <span className="small muted">
                  {p.goal_count} goal{p.goal_count === 1 ? "" : "s"} · {p.currency} · edited {fmtRelative(p.updated_at)}
                </span>
              </div>
              {p.latest_result ? (
                <span className="row small">
                  <StatusPill kind={p.latest_result.feasibility} />
                  <span className="muted">
                    {p.latest_result.goals_on_track} of {p.latest_result.goals_total} on track
                  </span>
                </span>
              ) : (
                <span className="small muted">Not built yet</span>
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
        <ConfirmDialog title="Delete financial plan?" confirmLabel="Delete" danger busy={busy} onConfirm={() => void doDelete()} onCancel={() => setToDelete(null)}>
          <p style={{ margin: 0 }}>
            "{toDelete.name}" and all its results will be deleted. This cannot be undone.
          </p>
        </ConfirmDialog>
      ) : null}
    </section>
  );
}
