import { useEffect, useId, useState, type KeyboardEvent, type ReactElement } from "react";
import type { DraftDuration, Question, WorkingTime, WindowHM, Weekday } from "../api/types";
import { num, unitWord } from "../lib/pert";

/** Local editing value of one question (strings for text-like kinds). */
export type QValue = string | string[] | boolean | WorkingTime | null;

const DAYS: { d: Weekday; label: string }[] = [
  { d: "mon", label: "Mon" },
  { d: "tue", label: "Tue" },
  { d: "wed", label: "Wed" },
  { d: "thu", label: "Thu" },
  { d: "fri", label: "Fri" },
  { d: "sat", label: "Sat" },
  { d: "sun", label: "Sun" },
];

export function durationText(d: DraftDuration): string {
  if (d.optimistic === d.pessimistic) return `${num(d.likely)} ${unitWord(d.likely, d.unit)}`;
  const mid = (d.optimistic + d.pessimistic) / 2;
  if (d.likely === mid) return `${num(d.optimistic)}-${num(d.pessimistic)} ${d.unit}`;
  return `${num(d.optimistic)}/${num(d.likely)}/${num(d.pessimistic)} ${d.unit}`;
}

export function windowsText(ws: WindowHM[] | null | undefined): string {
  return (ws ?? []).map((w) => `${w.start}-${w.end}`).join(", ");
}

const HM = "(?:[01]\\d|2[0-3]):[0-5]\\d|24:00";
const WINDOW_RE = new RegExp(`^\\s*(${HM})\\s*-\\s*(${HM})\\s*$`);

/** "09:00-13:00, 14:00-18:00" -> windows, or null if any part is not a valid window. */
export function parseWindows(text: string): WindowHM[] | null {
  const parts = text.split(/[,;]/).map((p) => p.trim()).filter(Boolean);
  if (!parts.length || parts.length > 4) return null;
  const out: WindowHM[] = [];
  for (const p of parts) {
    const m = p.match(WINDOW_RE);
    if (!m) return null;
    if (m[1] >= m[2] && m[2] !== "24:00") return null;
    out.push({ start: m[1], end: m[2] });
  }
  return out;
}

/** Start value of the input for a question (its suggestion, in the input's format). */
export function initialValue(q: Question): QValue {
  const d = q.default;
  switch (q.kind) {
    case "confirm":
      return typeof d === "boolean" ? d : null;
    case "multi_choice":
      return Array.isArray(d) ? d.map(String) : [];
    case "people":
      return Array.isArray(d) ? d.map(String).join(", ") : "";
    case "working_time":
      return d && typeof d === "object" ? (d as WorkingTime) : { days: ["mon", "tue", "wed", "thu", "fri"], windows: [{ start: "09:00", end: "17:00" }], weekend_windows: null };
    case "duration":
      return d && typeof d === "object" ? durationText(d as DraftDuration) : "";
    case "money":
      if (d && typeof d === "object" && "low" in (d as object)) {
        const a = d as { low: number; high: number };
        return a.low === a.high ? String(a.low) : `${a.low}-${a.high}`;
      }
      return d === null || d === undefined ? "" : String(d);
    default:
      return d === null || d === undefined ? "" : String(d);
  }
}

function plainNumber(s: string): number | null {
  const t = s.replace(/[,\s₹]/g, "");
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : null;
}

/** The answer `value` in the format of the question kind (PHASE2.md 2.8), or undefined when empty/invalid. */
export function answerValue(q: Question, v: QValue): unknown {
  switch (q.kind) {
    case "number":
    case "percent":
    case "money": {
      const s = String(v ?? "").trim();
      if (!s) return undefined;
      const n = plainNumber(s.replace(/%$/, ""));
      return n !== null ? n : { text: s };
    }
    case "duration": {
      const s = String(v ?? "").trim();
      return s ? { text: s } : undefined;
    }
    case "date": {
      const s = String(v ?? "").trim();
      if (!s) return undefined;
      return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : { text: s };
    }
    case "month": {
      const s = String(v ?? "").trim();
      if (!s) return undefined;
      return /^\d{4}-\d{2}$/.test(s) ? s : { text: s };
    }
    case "choice":
      return typeof v === "string" && v ? v : undefined;
    case "multi_choice":
      return Array.isArray(v) && v.length ? v : undefined;
    case "text": {
      const s = String(v ?? "").trim();
      return s ? s : undefined;
    }
    case "confirm":
      return typeof v === "boolean" ? v : undefined;
    case "people": {
      const names = String(v ?? "")
        .split(/,|;|\band\b/)
        .map((x) => x.trim())
        .filter(Boolean);
      return names.length ? names : undefined;
    }
    case "working_time": {
      const wt = v as WorkingTime | null;
      return wt && wt.days.length && wt.windows.length ? wt : undefined;
    }
  }
}

/** Day checkboxes plus "09:00-17:00" style windows; optional different weekend hours. */
export function WorkingTimeFields({
  value,
  onChange,
  idPrefix,
}: {
  value: WorkingTime;
  onChange(v: WorkingTime): void;
  idPrefix: string;
}) {
  const winId = `${idPrefix}-win`;
  const wkId = `${idPrefix}-wk`;
  const errId = `${idPrefix}-err`;
  const winText = windowsText(value.windows);
  const wkText = windowsText(value.weekend_windows);
  return (
    <div className="col" style={{ gap: 8 }}>
      <fieldset className="plain-fieldset">
        <legend className="field-label">Working days</legend>
        <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
          {DAYS.map(({ d, label }) => (
            <label key={d} className="checkbox day-check">
              <input
                type="checkbox"
                checked={value.days.includes(d)}
                onChange={(e) => {
                  const days = e.target.checked ? DAYS.map((x) => x.d).filter((x) => x === d || value.days.includes(x)) : value.days.filter((x) => x !== d);
                  onChange({ ...value, days });
                }}
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      <WindowsInput id={winId} errId={errId} label="Hours on those days" initial={winText} onValid={(windows) => onChange({ ...value, windows })} />
      <label className="checkbox">
        <input
          type="checkbox"
          checked={!!value.weekend_windows}
          onChange={(e) => onChange({ ...value, weekend_windows: e.target.checked ? value.windows : null })}
        />
        Different hours on Saturday and Sunday
      </label>
      {value.weekend_windows ? (
        <WindowsInput
          id={wkId}
          errId={`${errId}-wk`}
          label="Hours on Saturday and Sunday"
          initial={wkText}
          onValid={(weekend_windows) => onChange({ ...value, weekend_windows })}
        />
      ) : null}
    </div>
  );
}


function WindowsInput({ id, errId, label, initial, onValid }: { id: string; errId: string; label: string; initial: string; onValid(w: WindowHM[]): void }) {
  const [text, setText] = useState(initial);
  const [bad, setBad] = useState(false);
  useEffect(() => setText(initial), [initial]);
  const commit = () => {
    const w = parseWindows(text);
    if (!w) {
      setBad(true);
      return;
    }
    setBad(false);
    if (windowsText(w) !== initial) onValid(w);
  };
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className="input"
        value={text}
        placeholder="09:00-13:00, 14:00-18:00"
        aria-invalid={bad}
        aria-describedby={bad ? errId : undefined}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
      />
      {bad ? (
        <span id={errId} className="field-error" role="alert">
          Use times like 09:00-13:00, separated by commas (up to 4).
        </span>
      ) : (
        <span className="hint">For example 09:00-13:00, 14:00-18:00</span>
      )}
    </div>
  );
}

const HINT: Partial<Record<Question["kind"], string>> = {
  duration: 'A range like "2-3 days" is fine.',
  money: 'A range like "40-50k" or "1.2 lakh" is fine.',
  number: "",
  percent: "In percent, for example 9.5",
  people: "Names separated by commas",
};

/** One input per question kind (PHASE2.md 3.3). `onSubmit` fires on Enter in single-line inputs. */
export function QuestionInput({
  q,
  value,
  onChange,
  onSubmit,
  labelId,
}: {
  q: Question;
  value: QValue;
  onChange(v: QValue): void;
  onSubmit(): void;
  labelId: string;
}) {
  const base = useId();
  const hintId = `${base}-hint`;
  const hint = q.help || HINT[q.kind] || "";
  const describedBy = [hint ? hintId : "", q.error ? `${base}-err` : ""].filter(Boolean).join(" ") || undefined;
  const enter = (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onSubmit();
    }
  };
  let input: ReactElement;
  switch (q.kind) {
    case "choice":
      input = (
        <div role="radiogroup" aria-labelledby={labelId} aria-describedby={describedBy} className="col" style={{ gap: 4 }}>
          {q.options.map((o) => (
            <label key={o.value} className="checkbox">
              <input type="radio" name={`${base}-r`} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} />
              {o.label}
            </label>
          ))}
        </div>
      );
      break;
    case "multi_choice": {
      const sel = Array.isArray(value) ? value : [];
      input = (
        <div role="group" aria-labelledby={labelId} aria-describedby={describedBy} className="col" style={{ gap: 4 }}>
          {q.options.map((o) => (
            <label key={o.value} className="checkbox">
              <input
                type="checkbox"
                checked={sel.includes(o.value)}
                onChange={(e) => onChange(e.target.checked ? [...sel, o.value] : sel.filter((x) => x !== o.value))}
              />
              {o.label}
            </label>
          ))}
        </div>
      );
      break;
    }
    case "confirm":
      input = (
        <div role="radiogroup" aria-labelledby={labelId} aria-describedby={describedBy} className="row" style={{ gap: 12 }}>
          <label className="checkbox">
            <input type="radio" name={`${base}-c`} checked={value === true} onChange={() => onChange(true)} /> Yes
          </label>
          <label className="checkbox">
            <input type="radio" name={`${base}-c`} checked={value === false} onChange={() => onChange(false)} /> No
          </label>
        </div>
      );
      break;
    case "text":
      input = (
        <textarea
          className="textarea"
          aria-labelledby={labelId}
          aria-describedby={describedBy}
          aria-invalid={!!q.error}
          rows={4}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
      );
      break;
    case "working_time":
      input = (
        <div role="group" aria-labelledby={labelId} aria-describedby={describedBy}>
          <WorkingTimeFields value={value as WorkingTime} onChange={onChange} idPrefix={base} />
        </div>
      );
      break;
    default: {
      const type = q.kind === "date" ? "date" : q.kind === "month" ? "month" : "text";
      input = (
        <input
          className="input"
          type={type}
          inputMode={q.kind === "number" || q.kind === "percent" ? "decimal" : undefined}
          aria-labelledby={labelId}
          aria-describedby={describedBy}
          aria-invalid={!!q.error}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={enter}
        />
      );
    }
  }
  return (
    <div className="col" style={{ gap: 4 }} data-testid="intake-question-input">
      {input}
      {hint ? (
        <span id={hintId} className="small muted">
          {hint}
        </span>
      ) : null}
      {q.error ? (
        <span id={`${base}-err`} className="field-error" role="alert">
          {q.error}
        </span>
      ) : null}
    </div>
  );
}
