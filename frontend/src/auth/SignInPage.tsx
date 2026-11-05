/** `/sign-in?next=` (PHASE2B 4.10). Single_user mode redirects to `/`; a signed-in user goes on to `next`. */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { Icon } from "../components/Icon";
import { ApiError } from "../api/client";
import type { AuthConfig, PendingLogin } from "../mfg/api/typesM5";
import { authErrorMessage, fetchAuthConfig, oidcLoginUrl, pendingLoginOf, postLoginTotp } from "./api";
import { useAuth } from "./AuthContext";
import { EMAIL_RE, FormError, PasswordInput, authFailureText } from "./AuthFields";
import { safeNext } from "./nextPath";
import "./auth.css";

export function SignInPage() {
  const auth = useAuth();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState(auth.expired ? auth.user?.email ?? "" : "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  // M5 3.1-3.2: SSO button when configured; second step when the account has 2FA
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [pending, setPending] = useState<PendingLogin | null>(null);
  const ssoError = params.get("sso_error") ?? params.get("error");

  useEffect(() => {
    document.title = "Sign in - SuperPlanner";
    const ctl = new AbortController();
    fetchAuthConfig(ctl.signal)
      .then(setConfig)
      .catch(() => setConfig(null)); // older servers: no SSO, no 2FA
    return () => ctl.abort();
  }, []);
  useEffect(() => {
    if (ssoError) setError(authErrorMessage(new ApiError(403, ssoError, "")) ?? "Single sign-on did not complete. Try again or ask your administrator.");
  }, [ssoError]);

  if (auth.status === "loading") return <AuthLoading />;
  if (auth.mode !== "accounts") return <Navigate to="/" replace />;
  if (auth.status === "authenticated" && !auth.expired) return <Navigate to={next} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const addr = email.trim();
    if (!EMAIL_RE.test(addr)) {
      setError("Enter your email address, for example ana@example.com.");
      emailRef.current?.focus();
      return;
    }
    if (!password) {
      setError("Enter your password.");
      passwordRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const info = await auth.signIn({ email: addr, password });
      const p = pendingLoginOf(info);
      if (p) {
        setPending(p);
        setPassword("");
        setBusy(false);
      }
      // otherwise the redirect above takes over once the state says "authenticated"
    } catch (err) {
      const p = pendingLoginOf(err);
      if (p) {
        setPending(p);
        setPassword("");
        setBusy(false);
        return;
      }
      setError(authFailureText(err));
      setPassword("");
      setBusy(false);
    }
  };

  if (pending) return <TotpStep pending={pending} onBack={() => setPending(null)} next={next} />;
  const sso = config?.sso.enabled ? config.sso : null;

  const signUpTo = next === "/" ? "/sign-up" : `/sign-up?next=${encodeURIComponent(next)}`;

  return (
    <div className="auth-page">
      <section className="card auth-card" aria-labelledby="signin-title">
        <div className="card-body">
          <h1 id="signin-title">Sign in</h1>
          <p className="auth-lead">
            {auth.expired ? "Your session has ended. Sign in again to continue where you left off." : "Sign in to see your plans."}
          </p>
          {sso ? (
            <>
              <a className="btn primary auth-sso" href={oidcLoginUrl(next)} data-testid="signin-sso">
                <Icon name="lock" /> {sso.label ? `Sign in with ${sso.label}` : "Sign in with your company account"}
              </a>
              <div className="auth-or" role="separator">
                <span>or with email and password</span>
              </div>
            </>
          ) : null}
          <form className="auth-form" onSubmit={submit} noValidate aria-describedby={error ? "signin-error" : undefined}>
            <FormError id="signin-error" testId="signin-error">
              {error}
            </FormError>
            <div className="field">
              <label htmlFor="signin-email">Email</label>
              <input
                ref={emailRef}
                id="signin-email"
                className="input"
                type="email"
                inputMode="email"
                autoComplete="username"
                autoCapitalize="off"
                spellCheck={false}
                autoFocus
                required
                maxLength={254}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                data-testid="signin-email"
              />
            </div>
            <div className="field">
              <label htmlFor="signin-password">Password</label>
              <PasswordInput
                id="signin-password"
                testId="signin-password"
                inputRef={passwordRef}
                value={password}
                onChange={setPassword}
                autoComplete="current-password"
              />
            </div>
            <button type="submit" className={`btn${sso ? "" : " primary"}`} disabled={busy} data-testid="signin-submit">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />}
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
          {auth.signupEnabled ? (
            <p className="auth-switch">
              New here?{" "}
              <Link to={signUpTo} data-testid="signin-to-signup">
                Create an account
              </Link>
            </p>
          ) : (
            <p className="auth-switch">Need an account? Ask your administrator.</p>
          )}
        </div>
      </section>
    </div>
  );
}

/** Second sign-in step (M5 3.2): a 6-digit code, or one of the recovery codes. */
function TotpStep({ pending, onBack, next }: { pending: PendingLogin; onBack(): void; next: string }) {
  const auth = useAuth();
  const [useRecovery, setUseRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => ref.current?.focus(), [useRecovery]);
  if (pending.method === "setup") return <Navigate to={`/account/security?required=1&pending=${encodeURIComponent(pending.pending_token)}&next=${encodeURIComponent(next)}`} replace />;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const c = code.replace(/\s+/g, "");
    if (!useRecovery && !/^\d{6}$/.test(c)) {
      setError("Enter the 6-digit code shown in your authenticator app.");
      ref.current?.focus();
      return;
    }
    if (useRecovery && c.length < 6) {
      setError("Enter one of your recovery codes.");
      ref.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const info = await postLoginTotp(useRecovery ? { pending_token: pending.pending_token, recovery_code: c } : { pending_token: pending.pending_token, code: c });
      auth.applySession(info);
    } catch (err) {
      setError(authFailureText(err));
      setCode("");
      setBusy(false);
      ref.current?.focus();
    }
  };
  return (
    <div className="auth-page">
      <section className="card auth-card" aria-labelledby="totp-title" data-testid="signin-totp">
        <div className="card-body">
          <h1 id="totp-title">Two-step verification</h1>
          <p className="auth-lead">{useRecovery ? "Enter one of the recovery codes you saved when you turned on two-step verification. Each code works once." : "Open your authenticator app and enter the 6-digit code for SuperPlanner."}</p>
          <form className="auth-form" onSubmit={submit} noValidate aria-describedby={error ? "totp-error" : undefined}>
            <FormError id="totp-error" testId="totp-error">
              {error}
            </FormError>
            <div className="field">
              <label htmlFor="totp-code">{useRecovery ? "Recovery code" : "Code"}</label>
              <input
                ref={ref}
                id="totp-code"
                className="input auth-code"
                inputMode={useRecovery ? "text" : "numeric"}
                autoComplete="one-time-code"
                autoCapitalize="off"
                spellCheck={false}
                maxLength={useRecovery ? 32 : 7}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                data-testid="totp-code"
              />
            </div>
            <button type="submit" className="btn primary" disabled={busy} data-testid="totp-submit">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />}
              {busy ? "Checking…" : "Verify"}
            </button>
          </form>
          <p className="auth-switch">
            <button type="button" className="btn link" onClick={() => { setUseRecovery((v) => !v); setCode(""); setError(null); }} data-testid="totp-use-recovery">
              {useRecovery ? "Use a code from the app instead" : "Lost your phone? Use a recovery code"}
            </button>
            {" · "}
            <button type="button" className="btn link" onClick={onBack}>
              Start over
            </button>
          </p>
        </div>
      </section>
    </div>
  );
}

export function AuthLoading() {
  return (
    <div className="empty auth-loading" role="status">
      <span className="spinner" aria-hidden />
      <span>Checking your sign-in…</span>
    </div>
  );
}
