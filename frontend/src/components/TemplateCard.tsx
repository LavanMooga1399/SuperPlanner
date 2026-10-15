import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
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

function ParamInput({
  p,
  value,
  onChange,
  idPrefix,
}: {
  p: TemplateParameter;
  value: ParamValue;
  onChange(v: ParamValue): void;
  idPrefix: string;
}) {
  const id = `${idPrefix}-${p.name}`;
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
      />
    );
  } else if (p.type === "date") {
    control = <input id={id} className="input" type="date" value={value as string} onChange={(e) => onChange(e.target.value)} />;
  } else if (p.type === "string_list") {
    const list = value as string[];
    control = (
      <textarea
        id={id}
        className="textarea"
        rows={3}
        value={list.join("\n")}
        onChange={(e) => onChange(e.target.value.split("\n"))}
        aria-describedby={`${id}-hint`}
      />
    );
  } else {
    control = <input id={id} className="input" type="text" value={value as string} onChange={(e) => onChange(e.target.value)} />;
  }
  return (
    <div className="field">
      <label htmlFor={id}>{p.label}</label>
      {control}
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

  const invalid = template.parameters.find((p) => {
    if (p.type !== "int") return false;
    const v = values[p.name] as number;
    return !Number.isFinite(v) || (p.min !== null && v < p.min) || (p.max !== null && v > p.max);
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (invalid) return;
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
                onChange={(v) => setValues((s) => ({ ...s, [p.name]: v }))}
              />
            ))}
          </div>
        ) : null}
        {invalid ? (
          <div className="small" style={{ color: "var(--danger)" }} role="alert">
            {invalid.label} must be between {invalid.min} and {invalid.max}.
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
        <button type="submit" className="btn primary" disabled={busy || !!invalid}>
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="plus" />}
          Create plan
        </button>
      </div>
    </form>
  );
}
