import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { fmtDuration, inputToIso, isoToInput } from "../lib/time";
import { parseDuration } from "../lib/planEdit";
import { Icon } from "./Icon";

/** Duration in minutes, typed as "90", "1h 30m", "2d"... Commits on blur/Enter. */
export function DurationInput({
  value,
  onChange,
  label,
  min = 1,
  disabled,
  id,
  className = "input sm",
}: {
  value: number;
  onChange(v: number): void;
  label: string;
  min?: number;
  disabled?: boolean;
  id?: string;
  className?: string;
}) {
  const [text, setText] = useState(fmtDuration(value));
  const [invalid, setInvalid] = useState(false);
  useEffect(() => setText(fmtDuration(value)), [value]);
  const commit = () => {
    const v = parseDuration(text);
    if (v === null || v < min) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if (v !== value) onChange(v);
    else setText(fmtDuration(value));
  };
  return (
    <input
      id={id}
      className={className}
      style={{ width: 92 }}
      value={text}
      aria-label={label}
      aria-invalid={invalid}
      title={invalid ? `Enter a duration such as 90, 1h 30m or 2d (at least ${min} min)` : `${value} minutes`}
      disabled={disabled}
      onChange={(e) => {
        setText(e.target.value);
        setInvalid(false);
      }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setText(fmtDuration(value));
      }}
    />
  );
}

/** Datetime in the plan's UTC offset (datetime-local input, serialized with the offset). */
export function PlanDateTimeInput({
  value,
  onChange,
  offsetMin,
  label,
  id,
  className = "input sm",
  allowEmpty = true,
}: {
  value: string | null;
  onChange(v: string | null): void;
  offsetMin: number;
  label: string;
  id?: string;
  className?: string;
  allowEmpty?: boolean;
}) {
  const [text, setText] = useState(isoToInput(value, offsetMin));
  useEffect(() => setText(isoToInput(value, offsetMin)), [value, offsetMin]);
  const commit = (v: string) => {
    if (!v) {
      if (allowEmpty && value !== null) onChange(null);
      return;
    }
    const iso = inputToIso(v, offsetMin);
    if (iso && iso !== value && isoToInput(value, offsetMin) !== v) onChange(iso);
  };
  return (
    <input
      id={id}
      type="datetime-local"
      className={className}
      style={{ width: 190 }}
      value={text}
      aria-label={label}
      onChange={(e) => setText(e.target.value)}
      onBlur={(e) => commit(e.target.value)}
      onKeyDown={(e) => e.key === "Enter" && commit((e.target as HTMLInputElement).value)}
    />
  );
}

export interface Option {
  value: string;
  label: string;
  hint?: string;
}

/** Accessible checkbox popover multi-select. Selection order is preserved. */
export function MultiSelect({
  options,
  value,
  onChange,
  label,
  placeholder = "None",
  ordered,
}: {
  options: Option[];
  value: string[];
  onChange(v: string[]): void;
  label: string;
  placeholder?: string;
  ordered?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const popId = useId();
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const byValue = new Map(options.map((o) => [o.value, o]));
  const summary = value.length ? value.map((v) => byValue.get(v)?.label ?? v).join(ordered ? " › " : ", ") : placeholder;
  return (
    <div className="multi-select" ref={ref}>
      <button
        type="button"
        className="btn sm"
        aria-label={`${label}: ${summary}`}
        aria-expanded={open}
        aria-controls={popId}
        onClick={() => setOpen(!open)}
        style={{ maxWidth: 260, justifyContent: "space-between" }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }} className={value.length ? "" : "faint"}>
          {summary}
        </span>
        <Icon name="chevron-down" />
      </button>
      {open ? (
        <div className="multi-select-pop" id={popId} role="group" aria-label={label}>
          {options.length === 0 ? <div className="small muted" style={{ padding: 6 }}>Nothing to choose</div> : null}
          {options.map((o) => {
            const checked = value.includes(o.value);
            return (
              <label key={o.value}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onChange(checked ? value.filter((v) => v !== o.value) : [...value, o.value])}
                />
                <span className="grow">{o.label}</span>
                {o.hint ? <span className="small faint">{o.hint}</span> : null}
                {ordered && checked ? <span className="chip">{value.indexOf(o.value) + 1}</span> : null}
              </label>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

/** Number input that commits on blur, clamps to [min, max]. */
export function NumberInput({
  value,
  onChange,
  label,
  min,
  max,
  step = 1,
  width = 72,
  id,
  className = "input sm",
}: {
  value: number;
  onChange(v: number): void;
  label: string;
  min?: number;
  max?: number;
  step?: number;
  width?: number;
  id?: string;
  className?: string;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    let v = Number(text);
    if (text.trim() === "" || Number.isNaN(v)) {
      setText(String(value));
      return;
    }
    if (min !== undefined) v = Math.max(min, v);
    if (max !== undefined) v = Math.min(max, v);
    if (step === 1) v = Math.round(v);
    setText(String(v));
    if (v !== value) onChange(v);
  };
  return (
    <input
      id={id}
      type="number"
      className={className}
      style={{ width }}
      value={text}
      min={min}
      max={max}
      step={step}
      aria-label={label}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()}
    />
  );
}

/** Text input that commits on blur/Enter. */
export function TextInput({
  value,
  onChange,
  label,
  placeholder,
  id,
  className = "input sm",
  required,
  maxLength = 200,
  style,
}: {
  value: string;
  onChange(v: string): void;
  label: string;
  placeholder?: string;
  id?: string;
  className?: string;
  required?: boolean;
  maxLength?: number;
  style?: CSSProperties;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const commit = () => {
    const v = text.trim();
    if (required && !v) {
      setText(value);
      return;
    }
    if (v !== value) onChange(v);
  };
  return (
    <input
      id={id}
      className={className}
      value={text}
      placeholder={placeholder}
      aria-label={label}
      maxLength={maxLength}
      style={style}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setText(value);
      }}
    />
  );
}
