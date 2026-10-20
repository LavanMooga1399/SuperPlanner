/** Small form pieces shared by the sign-in, sign-up and account pages. */
import { useState, type ReactNode, type Ref } from "react";
import { errorMessage } from "../api/client";
import { Icon } from "../components/Icon";
import { authErrorMessage } from "./api";

export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
export const MIN_PASSWORD = 10;
export const MAX_PASSWORD = 256;

/** Message for a failed auth call: known codes in plain language, else the usual field/server message. */
export function authFailureText(err: unknown): string {
  return authErrorMessage(err) ?? errorMessage(err);
}

export function FormError({ id, testId, children }: { id: string; testId: string; children: ReactNode }) {
  if (!children) return null;
  return (
    <div className="banner danger" role="alert" id={id} data-testid={testId}>
      <Icon name="alert" />
      <div className="banner-body">{children}</div>
    </div>
  );
}

/** Password input with a show/hide toggle (the toggle never submits the form). */
export function PasswordInput({
  id,
  testId,
  value,
  onChange,
  autoComplete,
  describedBy,
  invalid,
  disabled,
  required = true,
  inputRef,
}: {
  id: string;
  testId: string;
  value: string;
  onChange(v: string): void;
  autoComplete: "current-password" | "new-password";
  describedBy?: string;
  invalid?: boolean;
  disabled?: boolean;
  required?: boolean;
  inputRef?: Ref<HTMLInputElement>;
}) {
  const [shown, setShown] = useState(false);
  return (
    <div className="pw-wrap">
      <input
        ref={inputRef}
        id={id}
        className="input"
        type={shown ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        required={required}
        disabled={disabled}
        maxLength={MAX_PASSWORD * 2}
        data-testid={testId}
        spellCheck={false}
        autoCapitalize="off"
      />
      <button
        type="button"
        className="btn ghost pw-toggle"
        onClick={() => setShown((s) => !s)}
        aria-pressed={shown}
        aria-controls={id}
        aria-label={shown ? "Hide password" : "Show password"}
      >
        {shown ? "Hide" : "Show"}
      </button>
    </div>
  );
}
