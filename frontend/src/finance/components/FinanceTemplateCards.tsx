import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { errorMessage } from "../../api/client";
import { ErrorBanner, Loading } from "../../components/Banner";
import { Icon, type IconName } from "../../components/Icon";
import { instantiateFinanceTemplate, listFinanceTemplates } from "../api/client";
import type { FinanceTemplateInfo, FinanceTemplateParameter } from "../api/types";
import { useAsync } from "../../lib/useAsync";
import { currentUtcMonth } from "../lib/months";

const ICONS: Record<string, IconName> = {
  young_professional: "briefcase",
  family: "star",
  near_retirement: "flag",
  blank: "file",
};

/** The finance example cards (test ids `fin-template-card-<id>`), used on /finance and /new/money/example. */
export function FinanceTemplateCards() {
  const templates = useAsync((s) => listFinanceTemplates(s), []);
  const visible = (templates.data?.items ?? []).filter((t) => t.id !== "blank");
  if (templates.loading && !templates.data) return <Loading label="Loading examples…" />;
  if (templates.error) return <ErrorBanner error={templates.error} onRetry={templates.reload} />;
  return (
    <div className="grid-3">
      {visible.map((t) => (
        <FinTemplateCard key={t.id} template={t} />
      ))}
    </div>
  );
}

function paramLabelHint(p: FinanceTemplateParameter): string {
  const parts: string[] = [];
  if (p.min !== null && p.max !== null) parts.push(`${p.min} to ${p.max}`);
  if (p.help) parts.push(p.help);
  return parts.join(" · ");
}

function valueError(p: FinanceTemplateParameter, v: number): string | null {
  const range = p.min !== null && p.max !== null ? ` from ${p.min} to ${p.max}` : "";
  if (!Number.isFinite(v)) return `Enter a number${range}.`;
  if ((p.min !== null && v < p.min) || (p.max !== null && v > p.max)) return `${p.label} must be${range || " in range"}.`;
  return null;
}

function FinTemplateCard({ template }: { template: FinanceTemplateInfo }) {
  const navigate = useNavigate();
  const [name, setName] = useState(template.name);
  const [values, setValues] = useState<Record<string, number>>(() => Object.fromEntries(template.parameters.map((p) => [p.name, p.default])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const idPrefix = `fin-tpl-${template.id}`;
  const valid = template.parameters.every((p) => valueError(p, values[p.name]) === null);

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
      <form className="card-body" noValidate onSubmit={(e) => void submit(e)}>
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
              {template.parameters.map((p) => {
                const id = `${idPrefix}-${p.name}`;
                const err = valueError(p, values[p.name]);
                const hint = paramLabelHint(p);
                const describedBy = [hint ? `${id}-hint` : null, err ? `${id}-error` : null].filter(Boolean).join(" ") || undefined;
                return (
                  <div className="field" key={p.name}>
                    <label htmlFor={id}>{p.label}</label>
                    <input
                      id={id}
                      className="input sm"
                      type="number"
                      min={p.min ?? undefined}
                      max={p.max ?? undefined}
                      step={p.type === "money" ? "any" : 1}
                      value={Number.isFinite(values[p.name]) ? values[p.name] : ""}
                      aria-invalid={err ? true : undefined}
                      aria-describedby={describedBy}
                      onChange={(e) => setValues({ ...values, [p.name]: e.target.value === "" ? NaN : Number(e.target.value) })}
                    />
                    {err ? (
                      <span id={`${id}-error`} className="field-error">
                        <Icon name="alert" size={13} /> {err}
                      </span>
                    ) : null}
                    {hint ? <span id={`${id}-hint`} className="hint">{hint}</span> : null}
                  </div>
                );
              })}
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
