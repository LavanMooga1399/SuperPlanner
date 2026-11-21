/**
 * Date input with the app's date format (en-IN "21 Nov 2026") regardless of the browser locale. The native
 * `type="date"` control stays underneath (transparent) for the picker, keyboard entry and the label link, so
 * behaviour and accessibility are the browser's own; only the visible text is ours.
 */
import { Icon } from "./Icon";
import { formatDate } from "../lib/locale";

export function DateInput({
  id,
  value,
  onChange,
  min,
  max,
  small,
  testId,
  disabled,
}: {
  id: string;
  /** `YYYY-MM-DD` or "" */
  value: string;
  onChange(v: string): void;
  min?: string;
  max?: string;
  small?: boolean;
  testId?: string;
  disabled?: boolean;
}) {
  return (
    <div className={`date-input input${small ? " sm" : ""}${disabled ? " disabled" : ""}`}>
      <span className="date-text" aria-hidden>
        {value ? formatDate(`${value}T00:00:00`) : <span className="faint">dd MMM yyyy</span>}
      </span>
      <Icon name="calendar" size={14} aria-hidden />
      <input
        id={id}
        className="date-native"
        type="date"
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onClick={(e) => {
          try {
            e.currentTarget.showPicker?.();
          } catch {
            /* not allowed: the native control still works */
          }
        }}
        data-testid={testId}
      />
    </div>
  );
}
