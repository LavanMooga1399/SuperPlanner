import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage } from "../../api/client";
import { ErrorBanner, Loading } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon, type IconName } from "../../components/Icon";
import { useAsync } from "../../lib/useAsync";
import { fmtRelative } from "../../lib/time";
import {
  deleteFinancePlan,
  importFinancePlan,
  instantiateFinanceTemplate,
  listFinancePlans,
  listFinanceTemplates,
} from "../api/client";
import type { FinanceExportFile, FinancePlan, FinancePlanSummary, FinanceTemplateInfo, FinanceTemplateParameter } from "../api/types";
import { StatusPill } from "../components/StatusPill";
import { currentUtcMonth } from "../lib/months";

const ICONS: Record<string, IconName> = {
  young_professional: "briefcase",
  family: "star",
  near_retirement: "flag",
  blank: "file",
};

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
  const templates = useAsync((s) => listFinanceTemplates(s), []);
  const fileRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const startBlank = async () => {
    setBusy("blank");
    setError(null);
    try {
      const rec = await instantiateFinanceTemplate("blank", { name: "My financial plan", start_month: currentUtcMonth() });
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

  const visibleTemplates = (templates.data?.items ?? []).filter((t) => t.id !== "blank");

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
        {templates.loading && !templates.data ? (
          <Loading label="Loading examples…" />
        ) : templates.error ? (
          <ErrorBanner error={templates.error} onRetry={templates.reload} />
        ) : (
          <div className="grid-3">
            {visibleTemplates.map((t) => (
              <FinTemplateCard key={t.id} template={t} />
            ))}
          </div>
        )}
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

function paramLabelHint(p: FinanceTemplateParameter): string {
  const parts: string[] = [];
  if (p.min !== null && p.max !== null) parts.push(`${p.min} to ${p.max}`);
  if (p.help) parts.push(p.help);
  return parts.join(" · ");
}

function FinTemplateCard({ template }: { template: FinanceTemplateInfo }) {
  const navigate = useNavigate();
  const [name, setName] = useState(template.name);
  const [values, setValues] = useState<Record<string, number>>(() => Object.fromEntries(template.parameters.map((p) => [p.name, p.default])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const idPrefix = `fin-tpl-${template.id}`;
  const valid = template.parameters.every((p) => {
    const v = values[p.name];
    return Number.isFinite(v) && (p.min === null || v >= p.min) && (p.max === null || v <= p.max);
  });

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      const rec = await instantiateFinanceTemplate(template.id, {
        name: name.trim() || template.name,
        start_month: currentUtcMonth(),
        parameters: values,
      });
      navigate(`/finance/${rec.id}/setup/profile`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <article className="card template-card" data-testid={`fin-template-card-${template.id}`} aria-labelledby={`${idPrefix}-title`}>
      <form className="card-body" onSubmit={(e) => void submit(e)}>
        <div className="row">
          <span className="template-icon" aria-hidden>
            <Icon name={ICONS[template.id] ?? "file"} size={18} />
          </span>
          <h3 id={`${idPrefix}-title`}>{template.name}</h3>
        </div>
        <p className="muted" style={{ margin: 0 }}>{template.description}</p>
        <div className="field">
          <label htmlFor={`${idPrefix}-name`}>Plan name</label>
          <input id={`${idPrefix}-name`} className="input" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        </div>
        {template.parameters.length ? (
          <details>
            <summary className="small" style={{ cursor: "pointer" }}>Adjust the example ({template.parameters.length} values)</summary>
            <div className="fin-form mt">
              {template.parameters.map((p) => (
                <div className="field" key={p.name}>
                  <label htmlFor={`${idPrefix}-${p.name}`}>{p.label}</label>
                  <input
                    id={`${idPrefix}-${p.name}`}
                    className="input sm"
                    type="number"
                    min={p.min ?? undefined}
                    max={p.max ?? undefined}
                    step={p.type === "money" ? 1000 : 1}
                    value={Number.isFinite(values[p.name]) ? values[p.name] : ""}
                    aria-invalid={!Number.isFinite(values[p.name]) || (p.min !== null && values[p.name] < p.min) || (p.max !== null && values[p.name] > p.max) || undefined}
                    onChange={(e) => setValues({ ...values, [p.name]: e.target.value === "" ? NaN : Number(e.target.value) })}
                  />
                  {paramLabelHint(p) ? <span className="hint">{paramLabelHint(p)}</span> : null}
                </div>
              ))}
            </div>
          </details>
        ) : null}
        {error ? <span className="small" role="alert" style={{ color: "var(--danger)" }}><Icon name="alert" /> {error}</span> : null}
        <div style={{ marginTop: "auto" }}>
          <button className="btn primary" type="submit" disabled={busy || !valid}>
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="plus" />} Create plan
          </button>
        </div>
      </form>
    </article>
  );
}
