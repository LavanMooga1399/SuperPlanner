/** Small inputs shared by the draft editors: numbers, money ranges and duration ranges. All commit on blur/Enter. */
import { useEffect, useState } from "react";
import type { DraftAmount, DraftDuration, DurationUnit } from "../api/types";
import { formatRange, isRange, num, UNIT_LABEL } from "../lib/pert";

function parseNum(s: string): number | null {
  const t = s.replace(/[,\s₹$€]/g, "");
  if (!t) return null;
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : NaN;
}

/** Text box for a number (accepts "1,20,000"); empty -> null; not a number -> marked invalid, nothing sent. */
export function NumField({
  value,
  onChange,
  label,
  width = 90,
  allowEmpty = true,
  describedBy,
  invalid,
  testId,
}: {
  value: number | null;
  onChange(v: number | null): void;
  label: string;
  width?: number;
  allowEmpty?: boolean;
  describedBy?: string;
  invalid?: boolean;
  testId?: string;
}) {
  const shown = value === null || value === undefined ? "" : num(value);
  const [text, setText] = useState(shown);
  const [bad, setBad] = useState(false);
  useEffect(() => setText(shown), [shown]);
  const commit = () => {
    const v = parseNum(text);
    if (v === null && !allowEmpty) {
      setText(shown);
      return;
    }
    if (v !== null && Number.isNaN(v)) {
      setBad(true);
      return;
    }
    setBad(false);
    if (v !== value) onChange(v);
  };
  return (
    <input
      className="input sm"
      inputMode="decimal"
      style={{ width }}
      value={text}
      aria-label={label}
      aria-invalid={bad || invalid || undefined}
      aria-describedby={describedBy}
      title={bad ? "Enter a number" : undefined}
      data-testid={testId}
      onChange={(e) => {
        setText(e.target.value);
        setBad(false);
      }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setText(shown);
      }}
    />
  );
}

/** "from - to" pair for an amount (PHASE2.md 3.3). Leaving "to" empty means an exact amount. */
export function AmountRangeInput({
  value,
  onChange,
  label,
  describedBy,
  invalid,
}: {
  value: DraftAmount | null;
  onChange(v: DraftAmount | null): void;
  label: string;
  describedBy?: string;
  invalid?: boolean;
}) {
  const low = value?.low ?? null;
  const high = value && value.high !== value.low ? value.high : null;
  return (
    <span className="row amount-range" style={{ gap: 4 }}>
      <NumField
        value={low}
        label={`${label}, from`}
        describedBy={describedBy}
        invalid={invalid}
        onChange={(v) => onChange(v === null ? null : { low: v, high: high !== null && high >= v ? high : v })}
      />
      <span aria-hidden className="muted">
        to
      </span>
      <NumField
        value={high}
        label={`${label}, to (leave empty for an exact amount)`}
        describedBy={describedBy}
        invalid={invalid}
        onChange={(v) => {
          if (low === null) onChange(v === null ? null : { low: v, high: v });
          else onChange({ low, high: v === null ? low : v });
        }}
      />
    </span>
  );
}

const UNITS: DurationUnit[] = ["minutes", "hours", "days", "weeks"];

/**
 * A duration as one value, or as a range (shortest / most likely / longest) after "Add a range".
 * Shows "2-3 days, expected 2.5 days" under the inputs.
 */
export function DurationRangeInput({
  value,
  onChange,
  label,
  defaultUnit,
  describedBy,
  invalid,
}: {
  value: DraftDuration | null;
  onChange(v: DraftDuration | null): void;
  label: string;
  defaultUnit: DurationUnit;
  describedBy?: string;
  invalid?: boolean;
}) {
  const [expanded, setExpanded] = useState(isRange(value));
  useEffect(() => {
    if (isRange(value)) setExpanded(true);
  }, [value]);
  if (!value) {
    return (
      <button type="button" className="btn sm" onClick={() => onChange({ optimistic: 1, likely: 1, pessimistic: 1, unit: defaultUnit })}>
        Set duration
      </button>
    );
  }
  const unitSel = (
    <select
      className="select sm"
      aria-label={`${label}, unit`}
      value={value.unit}
      onChange={(e) => onChange({ ...value, unit: e.target.value as DurationUnit })}
    >
      {UNITS.map((u) => (
        <option key={u} value={u}>
          {UNIT_LABEL[u]}
        </option>
      ))}
    </select>
  );
  if (!expanded) {
    return (
      <span className="col" style={{ gap: 2 }}>
        <span className="row" style={{ gap: 4 }}>
          <NumField
            value={value.likely}
            width={64}
            allowEmpty={false}
            label={label}
            describedBy={describedBy}
            invalid={invalid}
            onChange={(v) => v !== null && onChange({ ...value, optimistic: v, likely: v, pessimistic: v })}
          />
          {unitSel}
        </span>
        <button type="button" className="link-btn small" onClick={() => setExpanded(true)}>
          Not sure? Add a range
        </button>
      </span>
    );
  }
  const set = (k: "optimistic" | "likely" | "pessimistic") => (v: number | null) => {
    if (v === null) return;
    const next = { ...value, [k]: v };
    // keep "likely" in the middle of a two-value range when it was there before
    if (k !== "likely" && value.likely === (value.optimistic + value.pessimistic) / 2) next.likely = (next.optimistic + next.pessimistic) / 2;
    onChange(next);
  };
  return (
    <span className="col" style={{ gap: 2 }}>
      <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>
        <NumField value={value.optimistic} width={56} allowEmpty={false} label={`${label}, shortest`} describedBy={describedBy} invalid={invalid} onChange={set("optimistic")} />
        <NumField value={value.likely} width={56} allowEmpty={false} label={`${label}, most likely`} describedBy={describedBy} invalid={invalid} onChange={set("likely")} />
        <NumField value={value.pessimistic} width={56} allowEmpty={false} label={`${label}, longest`} describedBy={describedBy} invalid={invalid} onChange={set("pessimistic")} />
        {unitSel}
      </span>
      <span className="small muted">
        <span aria-hidden>Shortest / likely / longest: </span>
        {formatRange(value)}
      </span>
      {!isRange(value) ? (
        <button type="button" className="link-btn small" onClick={() => setExpanded(false)}>
          Use one value
        </button>
      ) : null}
    </span>
  );
}
