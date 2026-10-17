import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { errorMessage, instantiateTemplate } from "../api/client";
import type { TemplateInfo, TemplateParameter } from "../api/types";
import { browserUtcOffset, todayDate } from "../lib/time";
import { Icon, type IconName } from "./Icon";

const ICONS: Record<string, IconName> = {
  manufacturing: "factory",
  exam_prep: "book",
  project: "briefcase",
  blank: "file",
};

type ParamValue = number | string | string[];

function initialValue(p: TemplateParameter): ParamValue {
  if (p.type === "string_list") return Array.isArray(p.default) ? (p.default as unknown[]).map(String) : [];
  if (p.type === "int") return typeof p.default === "number" ? p.default : Number(p.default ?? p.min ?? 0);
  return p.default === null || p.default === undefined ? "" : String(p.default);
}

/** Plain error for one parameter value, or null (checked on blur and on submit, PHASE2.md 3.6). */
function paramError(p: TemplateParameter, v: ParamValue): string | null {
  if (p.type === "int") {
    const n = v as number;
    if (!Number.isFinite(n)) return `Enter a whole number${p.min !== null && p.max !== null ? ` from ${p.min} to ${p.max}` : ""}.`;
    if (!Number.isInteger(n)) return "Enter a whole number.";
    if ((p.min !== null && n < p.min) || (p.max !== null && n > p.max))
      return `${p.label} must be between ${p.min ?? "…"} and ${p.max ?? "…"}.`;
  }
  if (p.type === "string_list") {
    const n = (v as string[]).map((x) => x.trim()).filter(Boolean).length;
    if (p.min !== null && n < p.min) return `Enter at least ${p.min} ${p.min === 1 ? "line" : "lines"}.`;
    if (p.max !== null && n > p.max) return `Enter at most ${p.max} lines.`;
  }
  return null;
}

function ParamInput({
  p,
  value,
  onChange,
  onBlur,
  idPrefix,
  error,
}: {
  p: TemplateParameter;
  value: ParamValue;
  onChange(v: ParamValue): void;
  onBlur(): void;
  idPrefix: string;
  error: string | null;
}) {
  const id = `${idPrefix}-${p.name}`;
  const errId = `${id}-error`;
  const hintIds = [p.type === "string_list" ? `${id}-hint` : null, error ? errId : null].filter(Boolean).join(" ") || undefined;
  const a11y = { "aria-invalid": error ? true : undefined, "aria-describedby": hintIds, onBlur } as const;
  let control;
  if (p.type === "int") {
    control = (
      <input
        id={id}
        className="input"
        type="number"
        min={p.min ?? undefined}
        max={p.max ?? undefined}
        step={1}
        value={Number.isFinite(value as number) ? (value as number) : ""}
        onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))}
        {...a11y}
      />
    );
  } else if (p.type === "date") {
    control = <input id={id} className="input" type="date" value={value as string} onChange={(e) => onChange(e.target.value)} {...a11y} />;
  } else if (p.type === "string_list") {
    const list = value as string[];
    control = (
      <textarea
        id={id}
        className="textarea"
        rows={3}
        value={list.join("\n")}
        onChange={(e) => onChange(e.target.value.split("\n"))}
        {...a11y}
      />
    );
  } else {
    control = <input id={id} className="input" type="text" value={value as string} onChange={(e) => onChange(e.target.value)} {...a11y} />;
  }
  return (
    <div className="field">
      <label htmlFor={id}>{p.label}</label>
      {control}
      {error ? (
        <span id={errId} className="field-error">
          <Icon name="alert" size={13} /> {error}
        </span>
      ) : null}
      {p.type === "string_list" ? (
        <span id={`${id}-hint`} className="hint">
          One per line
        </span>
      ) : null}
      {p.type === "int" && (p.min !== null || p.max !== null) ? (
        <span className="hint">
          {p.min ?? "…"} to {p.max ?? "…"}
        </span>
      ) : null}
      {p.help ? <span className="hint">{p.help}</span> : null}
    </div>
  );
}

export function TemplateCard({ template }: { template: TemplateInfo }) {
  const navigate = useNavigate();
  const [name, setName] = useState(template.id === "blank" ? "New plan" : template.name);
  const [startDate, setStartDate] = useState(todayDate());
  const [values, setValues] = useState<Record<string, ParamValue>>(() =>
    Object.fromEntries(template.parameters.map((p) => [p.name, initialValue(p)])),
  );
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const idPrefix = `tpl-${template.id}`;

  const [touched, setTouched] = useState<Set<string>>(() => new Set());
  const [submitted, setSubmitted] = useState(false);
  const summaryRef = useRef<HTMLDivElement>(null);
  const errors = template.parameters
    .map((p) => ({ p, error: paramError(p, values[p.name]) }))
    .filter((x): x is { p: TemplateParameter; error: string } => x.error !== null);
  const shownError = (p: TemplateParameter) => (submitted || touched.has(p.name) ? paramError(p, values[p.name]) : null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (errors.length) {
      setSubmitted(true);
      setOpen(true);
      requestAnimationFrame(() => summaryRef.current?.focus());
      return;
    }
    setBusy(true);
    setError(null);
    const parameters: Record<string, unknown> = {};
    for (const p of template.parameters) {
      const v = values[p.name];
      parameters[p.name] = p.type === "string_list" ? (v as string[]).map((s) => s.trim()).filter(Boolean) : v;
    }
    try {
      const rec = await instantiateTemplate(template.id, {
        name: name.trim() || undefined,
        start_date: startDate || undefined,
        utc_offset: browserUtcOffset(),
        parameters,
      });
      navigate(`/plans/${rec.id}/tasks`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  const t = template.terminology;
  return (
    <form className="card template-card" data-testid={`template-card-${template.id}`} onSubmit={submit}>
      <div className="card-body">
        <div className="row">
          <div className="template-icon">
            <Icon name={ICONS[template.id] ?? "file"} size={20} />
          </div>
          <div className="grow">
            <h3>{template.name}</h3>
            <div className="small muted">
              {t.tasks} · {t.resources}
            </div>
          </div>
        </div>
        <p className="muted" style={{ margin: 0 }}>
          {template.description}
        </p>
        <div className="field">
          <label htmlFor={`${idPrefix}-name`}>Plan name</label>
          <input id={`${idPrefix}-name`} className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </div>
        <button
          type="button"
          className="btn ghost sm"
          style={{ alignSelf: "flex-start" }}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <Icon name={open ? "chevron-down" : "chevron-right"} />
          Options
        </button>
        {open ? (
          <div className="col">
            <div className="field">
              <label htmlFor={`${idPrefix}-start`}>Start date</label>
              <input id={`${idPrefix}-start`} className="input" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </div>
            {template.parameters.map((p) => (
              <ParamInput
                key={p.name}
                p={p}
                idPrefix={idPrefix}
                value={values[p.name]}
                error={shownError(p)}
                onBlur={() => setTouched((t) => (t.has(p.name) ? t : new Set(t).add(p.name)))}
                onChange={(v) => setValues((s) => ({ ...s, [p.name]: v }))}
              />
            ))}
          </div>
        ) : null}
        {submitted && errors.length ? (
          <div className="small error-summary field-error" role="alert" tabIndex={-1} ref={summaryRef} data-testid={`${idPrefix}-errors`}>
            <Icon name="alert" size={13} />
            <div>
              Please fix {errors.length === 1 ? "this value" : "these values"} first:
              <ul>
                {errors.map(({ p, error }) => (
                  <li key={p.name}>
                    <a href={`#${idPrefix}-${p.name}`} onClick={(e) => (e.preventDefault(), document.getElementById(`${idPrefix}-${p.name}`)?.focus())}>
                      {error}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : null}
        {error ? (
          <div className="small" style={{ color: "var(--danger)" }} role="alert">
            {error}
          </div>
        ) : null}
      </div>
      <div className="card-footer row between">
        <span className="small faint">Times in your zone ({browserUtcOffset()})</span>
        <button type="submit" className="btn primary" disabled={busy}>
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="plus" />}
          Create plan
        </button>
      </div>
    </form>
  );
}
