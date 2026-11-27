/** `/account` (PHASE2B 4.10): who is signed in, and change password. Guarded; single_user redirects to `/`. */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router";
import { ApiError } from "../api/client";
import { Icon } from "../components/Icon";
import { useAuth } from "./AuthContext";
import { PageHeader } from "../components/PageHeader";
import { FormError, MAX_PASSWORD, MIN_PASSWORD, PasswordInput, authFailureText } from "./AuthFields";
import "./auth.css";
import { t } from "../lib/i18n";
import { formatDate } from "../lib/locale";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : formatDate(d);
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
    document.title = t("account.accountPage.str.accountSettingsSuperplanner");
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
    if (!current) return fail(t("account.accountPage.str.enterYourCurrentPassword"), "current");
    if ([...next].length < MIN_PASSWORD) return fail(t("account.accountPage.tpl.useAtLeastCharactersFor", { MINPASSWORD: MIN_PASSWORD }), "new");
    if ([...next].length > MAX_PASSWORD) return fail(t("account.accountPage.tpl.useAtMostCharactersFor", { MAXPASSWORD: MAX_PASSWORD }), "new");
    if (next === current) return fail(t("account.accountPage.str.chooseANewPasswordThat"), "new");
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
      <PageHeader title={t("account.accountPage.title.accountSettings")} description={t("account.accountPage.desc.yourPlansAndRunsAre")} />

      <section className="card" aria-labelledby="account-details">
        <div className="card-header">
          <h2 id="account-details" style={{ margin: 0, fontSize: 15 }}>{t("account.accountPage.head.yourAccount")}</h2>
        </div>
        <div className="card-body">
          <dl className="account-facts">
            <dt>{t("account.accountPage.head.name")}</dt>
            <dd>{user?.display_name || <span className="faint">{t("account.accountPage.text.notSet")}</span>}</dd>
            <dt>{t("account.accountPage.head.email")}</dt>
            <dd>{user?.email ?? "-"}</dd>
            <dt>{t("account.accountPage.head.memberSince")}</dt>
            <dd>{fmtDate(user?.created_at)}</dd>
            <dt>{t("account.accountPage.head.signedInUntil")}</dt>
            <dd>{auth.expiresAt ? t("account.accountPage.tpl.atTheLatest", { expiresAt: fmtDate(auth.expiresAt) }) : "-"}</dd>
          </dl>
        </div>
      </section>
      <section className="card auth-card" aria-label={t("account.accountPage.aria.security")}>
        <div className="card-body col" style={{ gap: 8 }}>
          <h2 style={{ margin: 0 }}>{t("account.accountPage.head.security")}</h2>
          <Link to="/account/security" data-testid="account-to-security">
            <Icon name="lock" />{" "}{t("account.accountPage.text.twoStepVerification", { v: user?.totp_enabled ? " (on)" : "" })}
          </Link>
          <Link to="/account/tokens" data-testid="account-to-tokens">
            <Icon name="copy" /> {t("account.accountPage.btn.apiTokens")}
          </Link>
          <Link to="/orgs">
            <Icon name="briefcase" /> {t("account.accountPage.btn.organisationsAndPlants")}
          </Link>
        </div>
      </section>

      <section className="card" aria-labelledby="account-password">
        <div className="card-header">
          <h2 id="account-password" style={{ margin: 0, fontSize: 15 }}>{t("account.accountPage.head.changePassword")}</h2>
        </div>
        <div className="card-body">
          <form className="auth-form" onSubmit={submit} noValidate>
            {done ? (
              <div className="banner ok" role="status" data-testid="pw-success">
                <Icon name="check" />
                <div className="banner-body">
                  {t("account.accountPage.text.yourPasswordWasChangedOther")}
                </div>
              </div>
            ) : null}
            <FormError id="pw-error" testId="pw-error">
              {error}
            </FormError>
            <div className="field">
              <label htmlFor="pw-current">{t("account.accountPage.label.currentPassword")}</label>
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
              <label htmlFor="pw-new">{t("account.accountPage.label.newPassword")}</label>
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
                {t("account.accountPage.text.atLeastCharacters", { MINPASSWORD: MIN_PASSWORD })}
              </span>
            </div>
            <div>
              <button type="submit" className="btn primary" style={{ width: "auto" }} disabled={busy} data-testid="pw-submit">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="lock" />}
                {busy ? t("account.accountPage.str.saving") : t("account.accountPage.str.changePassword")}
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}
