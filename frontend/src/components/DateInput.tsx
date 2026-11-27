/**
 * Date input with the app's date format ("21 Nov 2026", day - month - year in every number format) regardless of the browser locale. The native
 * `type="date"` control stays underneath (transparent) for the picker, keyboard entry and the label link, so
 * behaviour and accessibility are the browser's own; only the visible text is ours.
 */
import { Icon } from "./Icon";
import { formatDate } from "../lib/locale";
import { t } from "../lib/i18n";

export function DateInput({
  id,
  value,
  onChange,
  min,
  max,
  small,
  testId,
  disabled,
  ariaLabel,
  required,
  className,
}: {
  id?: string;
  ariaLabel?: string;
  required?: boolean;
  className?: string;
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
    <div className={`date-input input${small ? " sm" : ""}${disabled ? " disabled" : ""}${className ? ` ${className}` : ""}`}>
      <span className="date-text" aria-hidden>
        {value ? formatDate(`${value}T00:00:00`) : <span className="faint">{t("studio.dateInput.text.ddMmmYyyy")}</span>}
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
        required={required}
        aria-required={required || undefined}
        aria-label={ariaLabel}
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
