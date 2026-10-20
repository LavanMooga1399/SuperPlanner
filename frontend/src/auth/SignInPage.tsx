/** `/sign-in?next=` (PHASE2B 4.10). Single_user mode redirects to `/`; a signed-in user goes on to `next`. */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { Icon } from "../components/Icon";
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

  useEffect(() => {
    document.title = "Sign in - SuperPlanner";
  }, []);

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
      await auth.signIn({ email: addr, password });
      // The redirect above takes over once the state says "authenticated".
    } catch (err) {
      setError(authFailureText(err));
      setPassword("");
      setBusy(false);
    }
  };

  const signUpTo = next === "/" ? "/sign-up" : `/sign-up?next=${encodeURIComponent(next)}`;

  return (
    <div className="auth-page">
      <section className="card auth-card" aria-labelledby="signin-title">
        <div className="card-body">
          <h1 id="signin-title">Sign in</h1>
          <p className="auth-lead">
            {auth.expired ? "Your session has ended. Sign in again to continue where you left off." : "Sign in to see your plans."}
          </p>
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
            <button type="submit" className="btn primary" disabled={busy} data-testid="signin-submit">
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

export function AuthLoading() {
  return (
    <div className="empty auth-loading" role="status">
      <span className="spinner" aria-hidden />
      <span>Checking your sign-in…</span>
    </div>
  );
}
