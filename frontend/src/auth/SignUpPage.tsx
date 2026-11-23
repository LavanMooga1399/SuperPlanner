/** `/sign-up?next=` (PHASE2B 4.10). Single_user mode redirects to `/`; a signed-in user goes on to `next`. */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";
import { ApiError } from "../api/client";
import { Icon } from "../components/Icon";
import { useAuth } from "./AuthContext";
import { EMAIL_RE, FormError, MAX_PASSWORD, MIN_PASSWORD, PasswordInput, authFailureText } from "./AuthFields";
import { AuthLoading } from "./SignInPage";
import { safeNext } from "./nextPath";
import "./auth.css";
import { t } from "../lib/i18n";

export function SignUpPage() {
  const auth = useAuth();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorField, setErrorField] = useState<"email" | "password" | "name" | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.title = t("account.signUpPage.str.createAnAccountSuperplanner");
  }, []);

  if (auth.status === "loading") return <AuthLoading />;
  if (auth.mode !== "accounts") return <Navigate to="/" replace />;
  if (auth.status === "authenticated" && !auth.expired) return <Navigate to={next} replace />;

  const signInTo = next === "/" ? "/sign-in" : `/sign-in?next=${encodeURIComponent(next)}`;

  const fail = (message: string, field: "email" | "password" | "name" | null) => {
    setError(message);
    setErrorField(field);
    const ref = field === "email" ? emailRef : field === "password" ? passwordRef : field === "name" ? nameRef : null;
    ref?.current?.focus();
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const addr = email.trim();
    const display = name.trim();
    if (display.length > 100) return fail(t("account.signUpPage.str.useAtMost100Characters"), "name");
    if (!EMAIL_RE.test(addr) || addr.length > 254) return fail(t("account.signUpPage.str.enterAValidEmailAddress"), "email");
    if ([...password].length < MIN_PASSWORD) return fail(t("account.signUpPage.tpl.useAtLeastCharactersFor", { MINPASSWORD: MIN_PASSWORD }), "password");
    if ([...password].length > MAX_PASSWORD) return fail(t("account.signUpPage.tpl.useAtMostCharactersFor", { MAXPASSWORD: MAX_PASSWORD }), "password");
    setBusy(true);
    setError(null);
    setErrorField(null);
    try {
      await auth.signUp({ email: addr, password, ...(display ? { display_name: display } : {}) });
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "";
      fail(authFailureText(err), code === "WEAK_PASSWORD" ? "password" : code === "EMAIL_TAKEN" ? "email" : null);
      setBusy(false);
    }
  };

  if (!auth.signupEnabled) {
    return (
      <div className="auth-page">
        <section className="card auth-card" aria-labelledby="signup-title">
          <div className="card-body">
            <h1 id="signup-title">{t("account.signUpPage.head.createAnAccount")}</h1>
            <div className="banner warn" role="status" data-testid="signup-disabled">
              <Icon name="lock" />
              <div className="banner-body">{t("account.signUpPage.text.newAccountsCannotBeCreated")}</div>
            </div>
            <p className="auth-switch">
              <Link to={signInTo}>{t("account.signUpPage.text.backToSignIn")}</Link>
            </p>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <section className="card auth-card" aria-labelledby="signup-title">
        <div className="card-body">
          <h1 id="signup-title">{t("account.signUpPage.head.createAnAccount")}</h1>
          <p className="auth-lead">{t("account.signUpPage.text.yourPlansArePrivateTo")}</p>
          <form className="auth-form" onSubmit={submit} noValidate>
            <FormError id="signup-error" testId="signup-error">
              {error}
            </FormError>
            <div className="field">
              <label htmlFor="signup-name">
                {t("account.signUpPage.text.yourName")}{" "}<span className="faint">(optional)</span>
              </label>
              <input
                ref={nameRef}
                id="signup-name"
                className="input"
                autoComplete="name"
                autoFocus
                maxLength={120}
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-invalid={errorField === "name" || undefined}
                aria-describedby={errorField === "name" ? "signup-error" : undefined}
                data-testid="signup-name"
              />
            </div>
            <div className="field">
              <label htmlFor="signup-email">{t("account.signUpPage.label.email")}</label>
              <input
                ref={emailRef}
                id="signup-email"
                className="input"
                type="email"
                inputMode="email"
                autoComplete="email"
                autoCapitalize="off"
                spellCheck={false}
                required
                maxLength={254}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                aria-invalid={errorField === "email" || undefined}
                aria-describedby={errorField === "email" ? "signup-error" : undefined}
                data-testid="signup-email"
              />
            </div>
            <div className="field">
              <label htmlFor="signup-password">{t("account.signUpPage.label.password")}</label>
              <PasswordInput
                id="signup-password"
                testId="signup-password"
                inputRef={passwordRef}
                value={password}
                onChange={setPassword}
                autoComplete="new-password"
                invalid={errorField === "password"}
                describedBy={errorField === "password" ? "signup-password-hint signup-error" : "signup-password-hint"}
              />
              <span className="hint" id="signup-password-hint">
                {t("account.signUpPage.text.atLeastCharactersAShort", { MINPASSWORD: MIN_PASSWORD })}
              </span>
            </div>
            <button type="submit" className="btn primary" disabled={busy} data-testid="signup-submit">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />}
              {busy ? t("account.signUpPage.str.creatingYourAccount") : t("account.signUpPage.str.createAccount")}
            </button>
          </form>
          <p className="auth-switch">
            {t("account.signUpPage.text.alreadyHaveAnAccount")}{" "}<Link to={signInTo}>{t("account.signUpPage.text.signIn")}</Link>
          </p>
        </div>
      </section>
    </div>
  );
}
