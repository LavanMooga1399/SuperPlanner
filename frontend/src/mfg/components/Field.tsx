/**
 * Labelled form controls (label + control + hint) used by the Manufacturing forms. Values are controlled;
 * numbers are kept as text while typing and parsed by the form on save.
 */
import { useId, type ReactNode } from "react";

export function Field({
  label,
  hint,
  children,
  required,
  className,
  htmlFor,
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: (id: string) => ReactNode;
  required?: boolean;
  className?: string;
  htmlFor?: string;
}) {
  const auto = useId();
  const id = htmlFor ?? `f${auto.replace(/:/g, "")}`;
  return (
    <div className={`field${className ? ` ${className}` : ""}`}>
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
      {hint ? <span className="hint">{hint}</span> : null}
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
}: {
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
    <Field label={label} hint={hint} required={required} className={className}>
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
}: {
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
    <Field label={label} hint={hint} required={required}>
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
