/**
 * Labelled form controls (label + control + hint) used by the Manufacturing forms. Values are controlled;
 * numbers are kept as text while typing and parsed by the form on save.
 */
import { createContext, useContext, useEffect, useId, useMemo, type ReactNode } from "react";
import { Icon } from "../../components/Icon";
import { fieldErrors, type FieldError } from "../lib/useMfg";
import { nodeText } from "./VirtualTable";

/**
 * Server validation errors (422 `details.errors[].loc`) for the fields inside (UX-STANDARD 4). A `Field` shows the
 * message under its control when the last `loc` segment matches its `name`, or its label text
 * ("part_number" matches "Part number"). The summary banner above the form stays as well.
 */
const FormErrorsContext = createContext<FieldError[]>([]);

export function FormErrors({ error, children }: { error: unknown; children: ReactNode }) {
  const list = useMemo(() => fieldErrors(error), [error]);
  return <FormErrorsContext.Provider value={list}>{children}</FormErrorsContext.Provider>;
}

const norm = (x: string) => x.toLowerCase().replace(/[_\s]+/g, " ").replace(/\s*\(.*\)\s*$/, "").trim();

function useFieldError(name: string | undefined, label: ReactNode): string | null {
  const list = useContext(FormErrorsContext);
  if (!list.length) return null;
  const key = norm(name ?? nodeText(label));
  if (!key) return null;
  const hit = list.find((e) => {
    const last = [...e.loc].reverse().find((x) => typeof x === "string");
    return typeof last === "string" && norm(last) === key;
  });
  return hit ? hit.message : null;
}

export function Field({
  label,
  hint,
  children,
  required,
  className,
  htmlFor,
  name,
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: (id: string) => ReactNode;
  required?: boolean;
  className?: string;
  htmlFor?: string;
  /** API field name for inline server errors (default: matched by label). */
  name?: string;
}) {
  const auto = useId();
  const id = htmlFor ?? `f${auto.replace(/:/g, "")}`;
  const error = useFieldError(name, label);
  useEffect(() => {
    const el = document.getElementById(id);
    if (!el) return;
    if (error) {
      el.setAttribute("aria-invalid", "true");
      el.setAttribute("aria-describedby", `${id}-err`);
    } else if (el.getAttribute("aria-describedby") === `${id}-err`) {
      el.removeAttribute("aria-invalid");
      el.removeAttribute("aria-describedby");
    }
  }, [error, id]);
  return (
    <div className={`field${className ? ` ${className}` : ""}${error ? " has-error" : ""}`}>
      <label htmlFor={id}>
        {label}
        {required ? (
          <span className="mfg-required" aria-hidden>
            {" "}
            *
          </span>
        ) : null}
      </label>
      {children(id)}
      {error ? (
        <span className="field-error" id={`${id}-err`} data-testid="field-error">
          <Icon name="alert" size={12} /> {error}
        </span>
      ) : hint ? (
        <span className="hint">{hint}</span>
      ) : null}
    </div>
  );
}

export function TextField({
  label,
  value,
  onChange,
  hint,
  required,
  placeholder,
  maxLength = 200,
  testId,
  disabled,
  type = "text",
  className,
  name,
}: {
  name?: string;
  label: ReactNode;
  value: string;
  onChange(v: string): void;
  hint?: ReactNode;
  required?: boolean;
  placeholder?: string;
  maxLength?: number;
  testId?: string;
  disabled?: boolean;
  type?: "text" | "number" | "date" | "time" | "datetime-local";
  className?: string;
}) {
  return (
    <Field label={label} hint={hint} required={required} className={className} name={name}>
      {(id) => (
        <input
          id={id}
          className="input"
          type={type}
          value={value}
          placeholder={placeholder}
          maxLength={type === "text" ? maxLength : undefined}
          required={required}
          aria-required={required}
          disabled={disabled}
          data-testid={testId}
          step={type === "number" ? "any" : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </Field>
  );
}

export function SelectField<V extends string>({
  label,
  value,
  onChange,
  options,
  hint,
  required,
  testId,
  disabled,
  name,
}: {
  name?: string;
  label: ReactNode;
  value: V;
  onChange(v: NoInfer<V>): void;
  options: { value: NoInfer<V>; label: string }[];
  hint?: ReactNode;
  required?: boolean;
  testId?: string;
  disabled?: boolean;
}) {
  return (
    <Field label={label} hint={hint} required={required} name={name}>
      {(id) => (
        <select
          id={id}
          className="select"
          value={value}
          disabled={disabled}
          data-testid={testId}
          onChange={(e) => onChange(e.target.value as V)}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

export function CheckField({
  label,
  checked,
  onChange,
  hint,
  testId,
  disabled,
}: {
  /** API field name (accepted for symmetry; checkboxes show errors in the summary only). */
  name?: string;
  label: ReactNode;
  checked: boolean;
  onChange(v: boolean): void;
  hint?: ReactNode;
  testId?: string;
  disabled?: boolean;
}) {
  return (
    <div className="field mfg-check-field">
      <label className="checkbox">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          data-testid={testId}
          onChange={(e) => onChange(e.target.checked)}
        />
        {label}
      </label>
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}

/** "" -> null, otherwise a finite number (NaN -> null). */
export function numOrNull(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}

export function numOr(text: string, fallback: number): number {
  const v = numOrNull(text);
  return v === null ? fallback : v;
}

export function strOrNull(text: string): string | null {
  const t = text.trim();
  return t ? t : null;
}

export const numText = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v));
