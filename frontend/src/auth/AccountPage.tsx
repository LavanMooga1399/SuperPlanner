/** `/account` (PHASE2B 4.10): who is signed in, and change password. Guarded; single_user redirects to `/`. */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate } from "react-router";
import { ApiError } from "../api/client";
import { Icon } from "../components/Icon";
import { useAuth } from "./AuthContext";
import { FormError, MAX_PASSWORD, MIN_PASSWORD, PasswordInput, authFailureText } from "./AuthFields";
import "./auth.css";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

export function AccountPage() {
  const auth = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorField, setErrorField] = useState<"current" | "new" | null>(null);
  const [done, setDone] = useState(false);
  const currentRef = useRef<HTMLInputElement>(null);
  const newRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.title = "Account settings - SuperPlanner";
  }, []);

  if (auth.mode !== "accounts") return <Navigate to="/" replace />;
  const user = auth.user;

  const fail = (message: string, field: "current" | "new" | null) => {
    setError(message);
    setErrorField(field);
    (field === "current" ? currentRef : field === "new" ? newRef : null)?.current?.focus();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setDone(false);
    if (!current) return fail("Enter your current password.", "current");
    if ([...next].length < MIN_PASSWORD) return fail(`Use at least ${MIN_PASSWORD} characters for the new password.`, "new");
    if ([...next].length > MAX_PASSWORD) return fail(`Use at most ${MAX_PASSWORD} characters for the new password.`, "new");
    if (next === current) return fail("Choose a new password that is different from the current one.", "new");
    setBusy(true);
    setError(null);
    setErrorField(null);
    try {
      await auth.changePassword({ current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setDone(true);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "";
      fail(authFailureText(err), code === "WRONG_PASSWORD" ? "current" : code === "WEAK_PASSWORD" ? "new" : null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="account-page">
      <div>
        <h1 style={{ margin: "0 0 4px" }}>Account settings</h1>
        <p className="muted" style={{ margin: 0 }}>Your plans and runs are visible only to this account.</p>
      </div>

      <section className="card" aria-labelledby="account-details">
        <div className="card-header">
          <h2 id="account-details" style={{ margin: 0, fontSize: 15 }}>Your account</h2>
        </div>
        <div className="card-body">
          <dl className="account-facts">
            <dt>Name</dt>
            <dd>{user?.display_name || <span className="faint">Not set</span>}</dd>
            <dt>Email</dt>
            <dd>{user?.email ?? "-"}</dd>
            <dt>Member since</dt>
            <dd>{fmtDate(user?.created_at)}</dd>
            <dt>Signed in until</dt>
            <dd>{auth.expiresAt ? `${fmtDate(auth.expiresAt)} at the latest` : "-"}</dd>
          </dl>
        </div>
      </section>

      <section className="card" aria-labelledby="account-password">
        <div className="card-header">
          <h2 id="account-password" style={{ margin: 0, fontSize: 15 }}>Change password</h2>
        </div>
        <div className="card-body">
          <form className="auth-form" onSubmit={submit} noValidate>
            {done ? (
              <div className="banner ok" role="status" data-testid="pw-success">
                <Icon name="check" />
                <div className="banner-body">
                  Your password was changed. Other devices and browsers where you were signed in have been signed out.
                </div>
              </div>
            ) : null}
            <FormError id="pw-error" testId="pw-error">
              {error}
            </FormError>
            <div className="field">
              <label htmlFor="pw-current">Current password</label>
              <PasswordInput
                id="pw-current"
                testId="pw-current"
                inputRef={currentRef}
                value={current}
                onChange={setCurrent}
                autoComplete="current-password"
                invalid={errorField === "current"}
                describedBy={errorField === "current" ? "pw-error" : undefined}
              />
            </div>
            <div className="field">
              <label htmlFor="pw-new">New password</label>
              <PasswordInput
                id="pw-new"
                testId="pw-new"
                inputRef={newRef}
                value={next}
                onChange={setNext}
                autoComplete="new-password"
                invalid={errorField === "new"}
                describedBy={errorField === "new" ? "pw-new-hint pw-error" : "pw-new-hint"}
              />
              <span className="hint" id="pw-new-hint">
                At least {MIN_PASSWORD} characters.
              </span>
            </div>
            <div>
              <button type="submit" className="btn primary" style={{ width: "auto" }} disabled={busy} data-testid="pw-submit">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="lock" />}
                {busy ? "Saving…" : "Change password"}
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}
