/** Wizard inputs that commit on every valid change (so live previews update while typing). */
import { useEffect, useId, useState, type ReactNode } from "react";
import { currencySymbol } from "../lib/money";
import { isMonth } from "../lib/months";

export function Field({ label, hint, children, id, wide }: { label: ReactNode; hint?: ReactNode; children: (id: string) => ReactNode; id?: string; wide?: boolean }) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className={`field${wide ? " wide" : ""}`}>
      <label htmlFor={fid}>{label}</label>
      {children(fid)}
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}

export function FinNumber({
  value,
  onChange,
  label,
  min,
  max,
  step = 1,
  width,
  id,
  testId,
  placeholder,
}: {
  value: number | null;
  onChange(v: number): void;
  label?: string;
  min?: number;
  max?: number;
  step?: number;
  width?: number;
  id?: string;
  testId?: string;
  placeholder?: string;
}) {
  const [text, setText] = useState(value === null ? "" : String(value));
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    // Do not overwrite partial input such as "1." with the committed value.
    if (value === null) setText("");
    else if (Number(text) !== value) setText(String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  const parse = (s: string): number | null => {
    if (s.trim() === "") return null;
    const v = Number(s);
    if (!Number.isFinite(v)) return null;
    if (min !== undefined && v < min) return null;
    if (max !== undefined && v > max) return null;
    return v;
  };
  return (
    <input
      id={id}
      className="input sm"
      type="number"
      inputMode="decimal"
      value={text}
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      aria-label={label}
      aria-invalid={invalid || undefined}
      data-testid={testId}
      style={width ? { width } : undefined}
      onChange={(e) => {
        setText(e.target.value);
        const v = parse(e.target.value);
        setInvalid(v === null && e.target.value.trim() !== "");
        if (v !== null && v !== value) onChange(v);
      }}
      onBlur={() => {
        if (parse(text) === null) {
          setText(value === null ? "" : String(value));
          setInvalid(false);
        }
      }}
    />
  );
}

/** Optional number: empty input -> null. */
export function FinOptionalNumber({
  value,
  onChange,
  label,
  min,
  max,
  step = 1,
  id,
  placeholder,
}: {
  value: number | null;
  onChange(v: number | null): void;
  label?: string;
  min?: number;
  max?: number;
  step?: number;
  id?: string;
  placeholder?: string;
}) {
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => {
    if (value === null ? text !== "" : Number(text) !== value) setText(value === null ? "" : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <input
      id={id}
      className="input sm"
      type="number"
      value={text}
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      aria-label={label}
      onChange={(e) => {
        const s = e.target.value;
        setText(s);
        if (s.trim() === "") {
          if (value !== null) onChange(null);
          return;
        }
        const v = Number(s);
        if (!Number.isFinite(v) || (min !== undefined && v < min) || (max !== undefined && v > max)) return;
        if (v !== value) onChange(v);
      }}
      onBlur={() => setText(value === null ? "" : String(value))}
    />
  );
}

export function MoneyInput({
  value,
  onChange,
  currency,
  locale,
  id,
  label,
  testId,
  min = 0,
}: {
  value: number;
  onChange(v: number): void;
  currency: string;
  locale: string;
  id?: string;
  label?: string;
  testId?: string;
  min?: number;
}) {
  return (
    <div className="row" style={{ gap: 4 }}>
      <span className="muted" aria-hidden>{currencySymbol(currency, locale)}</span>
      <FinNumber id={id} label={label} value={value} onChange={onChange} min={min} max={1e12} step={100} testId={testId} />
    </div>
  );
}

export function FinText({
  value,
  onChange,
  id,
  label,
  required = true,
  maxLength = 200,
  testId,
  placeholder,
}: {
  value: string;
  onChange(v: string): void;
  id?: string;
  label?: string;
  required?: boolean;
  maxLength?: number;
  testId?: string;
  placeholder?: string;
}) {
  const [text, setText] = useState(value);
  useEffect(() => {
    if (text.trim() !== value) setText(value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <input
      id={id}
      className="input sm"
      value={text}
      maxLength={maxLength}
      aria-label={label}
      data-testid={testId}
      placeholder={placeholder}
      aria-invalid={required && !text.trim() ? true : undefined}
      onChange={(e) => {
        setText(e.target.value);
        const v = e.target.value.trim();
        if ((v || !required) && v !== value) onChange(v);
      }}
      onBlur={() => setText(value)}
    />
  );
}

/** `<input type="month">` with "YYYY-MM" values; empty -> null when optional. */
export function MonthInput({
  value,
  onChange,
  id,
  label,
  optional,
  min,
  testId,
}: {
  value: string | null;
  onChange(v: string | null): void;
  id?: string;
  label?: string;
  optional?: boolean;
  min?: string;
  testId?: string;
}) {
  const [text, setText] = useState(value ?? "");
  useEffect(() => setText(value ?? ""), [value]);
  return (
    <input
      id={id}
      className="input sm"
      type="month"
      value={text}
      min={min}
      aria-label={label}
      data-testid={testId}
      placeholder="YYYY-MM"
      onChange={(e) => {
        const s = e.target.value;
        setText(s);
        if (!s) {
          if (optional && value !== null) onChange(null);
          return;
        }
        if (isMonth(s) && s !== value) onChange(s);
      }}
      onBlur={() => setText(value ?? "")}
    />
  );
}

export function Select<T extends string>({
  value,
  onChange,
  options,
  id,
  label,
  testId,
}: {
  value: T;
  onChange(v: T): void;
  options: { value: T; label: string }[];
  id?: string;
  label?: string;
  testId?: string;
}) {
  return (
    <select id={id} className="select sm" value={value} aria-label={label} data-testid={testId} onChange={(e) => onChange(e.target.value as T)}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange(v: boolean): void; label: string; hint?: string }) {
  return (
    <label className="switch" title={hint}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

export const FREQUENCY_OPTIONS = [
  { value: "monthly" as const, label: "Every month" },
  { value: "quarterly" as const, label: "Every 3 months" },
  { value: "half_yearly" as const, label: "Every 6 months" },
  { value: "yearly" as const, label: "Every year" },
  { value: "once" as const, label: "Once" },
];
