/**
 * `/account/security` (M5 3.2): two-step verification for local accounts.
 * - Turn on: the server makes a secret; the app shows it as a QR code (drawn here, no external service) and as text,
 *   the user confirms with a 6-digit code and receives 10 recovery codes, shown once (copy / download).
 * - On: new recovery codes, or turn off (both need a current code; off is not offered when the organisation requires it).
 * - `?required=1` (organisation requires 2FA) and `&pending=` (setup forced during sign-in): finishing the setup
 *   completes the sign-in.
 * Accounts signed in through the company identity provider manage their second factor there.
 */
import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { Banner } from "../components/Banner";
import { Icon } from "../components/Icon";
import { QrCode } from "../components/QrCode";
import type { TotpSetup, TotpStatus } from "../mfg/api/typesM5";
import { fetchTotpStatus, postRecoveryCodes, postTotpDisable, postTotpEnable, postTotpSetup } from "./api";
import { useAuth } from "./AuthContext";
import { FormError, authFailureText } from "./AuthFields";
import { safeNext } from "./nextPath";
import type { SessionInfo } from "./types";
import "./auth.css";

const groups = (s: string) => s.replace(/\s+/g, "").match(/.{1,4}/g)?.join(" ") ?? s;

export function SecurityPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const required = params.get("required") === "1";
  const pendingToken = params.get("pending") ?? undefined;
  const next = safeNext(params.get("next"));
  const [status, setStatus] = useState<TotpStatus | null>(null);
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);
  const [code, setCode] = useState("");
  const [mode, setMode] = useState<null | "disable" | "recovery">(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Security - SuperPlanner";
  }, []);
  useEffect(() => {
    if (pendingToken) return; // not signed in yet: nothing to read
    const ctl = new AbortController();
    fetchTotpStatus(ctl.signal)
      .then(setStatus)
      .catch(() => setStatus({ enabled: Boolean(auth.user?.totp_enabled), enabled_at: null, recovery_codes_left: null, required_by_org: required }));
    return () => ctl.abort();
  }, [pendingToken, auth.user?.totp_enabled, required]);

  if (auth.mode !== "accounts") return <Navigate to="/" replace />;
  if (!pendingToken && auth.status !== "authenticated") return <Navigate to="/sign-in" replace />;
  const sso = Boolean(auth.user?.sso);

  const begin = async () => {
    setBusy(true);
    setError(null);
    try {
      setSetup(await postTotpSetup(pendingToken));
      setCode("");
    } catch (e) {
      setError(authFailureText(e));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (e: FormEvent) => {
    e.preventDefault();
    const c = code.replace(/\s+/g, "");
    if (!/^\d{6}$/.test(c)) return setError("Enter the 6-digit code your app shows for SuperPlanner.");
    setBusy(true);
    setError(null);
    try {
      const out = await postTotpEnable(c, pendingToken);
      setCodes(out.recovery_codes);
      setSetup(null);
      setCode("");
      // setup forced during sign-in: enabling completes the sign-in (the answer carries the session)
      if (out.auth_mode && out.authenticated !== undefined) auth.applySession(out as SessionInfo);
      setStatus({ enabled: true, enabled_at: new Date().toISOString(), recovery_codes_left: out.recovery_codes.length, required_by_org: status?.required_by_org ?? required });
    } catch (err) {
      setError(authFailureText(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  const withCode = async (e: FormEvent) => {
    e.preventDefault();
    const c = code.replace(/\s+/g, "");
    if (!/^\d{6}$/.test(c)) return setError("Enter the current 6-digit code from your app.");
    setBusy(true);
    setError(null);
    try {
      if (mode === "disable") {
        await postTotpDisable(c);
        setStatus({ enabled: false, enabled_at: null, recovery_codes_left: null, required_by_org: status?.required_by_org ?? false });
      } else {
        const out = await postRecoveryCodes(c);
        setCodes(out.recovery_codes);
        setSaved(false);
      }
      setMode(null);
      setCode("");
    } catch (err) {
      setError(authFailureText(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  const download = () => {
    const blob = new Blob([`SuperPlanner recovery codes (${auth.user?.email ?? ""})\nEach code works once.\n\n${(codes ?? []).join("\n")}\n`], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "superplanner-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="auth-page" style={{ alignItems: "flex-start" }}>
      <section className="card auth-card wide" aria-labelledby="sec-title" data-testid="security-page">
        <div className="card-body col" style={{ gap: 14 }}>
          <div className="row wrap" style={{ justifyContent: "space-between" }}>
            <h1 id="sec-title" style={{ margin: 0 }}>
              Two-step verification
            </h1>
            {!pendingToken ? (
              <span className="row">
                <Link to="/account">Account</Link>
                <span className="faint">·</span>
                <Link to="/account/tokens">API tokens</Link>
              </span>
            ) : null}
          </div>
          {required || status?.required_by_org ? (
            <Banner tone="warn" title="Required by your organisation" testId="security-required">
              Turn on two-step verification to continue. You will need your phone (or another authenticator app) each time you sign in with your password.
            </Banner>
          ) : null}
          {sso ? (
            <p style={{ margin: 0 }}>You sign in with your company account. Your company's sign-in page handles the second step, so there is nothing to set up here.</p>
          ) : null}
          <FormError id="sec-error" testId="security-error">
            {error}
          </FormError>

          {codes ? (
            <div className="col" style={{ gap: 10 }} data-testid="recovery-codes">
              <Banner tone="ok" title={status?.enabled ? "Two-step verification is on" : "New recovery codes"}>
                Save these recovery codes somewhere safe, away from your phone. Each one signs you in once if you lose the phone. They are shown only now.
              </Banner>
              <ol className="recovery-list mono">
                {codes.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ol>
              <div className="row wrap">
                <button type="button" className="btn" onClick={() => void navigator.clipboard?.writeText(codes.join("\n"))}>
                  <Icon name="copy" /> Copy
                </button>
                <button type="button" className="btn" onClick={download}>
                  <Icon name="download" /> Download
                </button>
              </div>
              <label className="checkbox">
                <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} data-testid="recovery-saved" /> I have saved my recovery codes
              </label>
              <div>
                <button
                  type="button"
                  className="btn primary"
                  disabled={!saved}
                  onClick={() => {
                    setCodes(null);
                    if (required || pendingToken) navigate(next, { replace: true });
                  }}
                  data-testid="recovery-done"
                >
                  {required || pendingToken ? "Continue" : "Done"}
                </button>
              </div>
            </div>
          ) : setup ? (
            <form className="col" style={{ gap: 12 }} onSubmit={confirm} data-testid="totp-setup">
              <ol className="setup-steps">
                <li>Open an authenticator app on your phone (for example Google Authenticator, Microsoft Authenticator or a password manager).</li>
                <li>Add an account and scan this code.</li>
              </ol>
              <div className="row wrap" style={{ gap: 20, alignItems: "flex-start" }}>
                <QrCode text={setup.otpauth_uri} size={196} label="QR code to add SuperPlanner to your authenticator app" testId="totp-qr" />
                <div className="col" style={{ gap: 6, maxWidth: 320 }}>
                  <span className="muted small">Cannot scan? Enter this key by hand (time-based, 6 digits):</span>
                  <code className="totp-secret" data-testid="totp-secret" data-secret={setup.secret}>
                    {groups(setup.secret)}
                  </code>
                </div>
              </div>
              <div className="field" style={{ maxWidth: 240 }}>
                <label htmlFor="totp-confirm">3. Enter the 6-digit code the app shows</label>
                <input id="totp-confirm" className="input auth-code" inputMode="numeric" autoComplete="one-time-code" maxLength={7} value={code} onChange={(e) => setCode(e.target.value)} autoFocus data-testid="totp-confirm" />
              </div>
              <div className="row">
                <button type="submit" className="btn primary" disabled={busy} data-testid="totp-enable">
                  {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Turn on
                </button>
                <button type="button" className="btn" onClick={() => setSetup(null)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : status?.enabled ? (
            <div className="col" style={{ gap: 10 }} data-testid="totp-on">
              <p style={{ margin: 0 }}>
                <span className="badge ok">
                  <Icon name="check" /> On
                </span>{" "}
                {status.enabled_at ? `since ${new Date(status.enabled_at).toLocaleDateString()}` : ""}
                {status.recovery_codes_left !== null ? ` · ${status.recovery_codes_left} recovery codes left` : ""}
              </p>
              {mode ? (
                <form className="row wrap" style={{ alignItems: "flex-end" }} onSubmit={withCode}>
                  <div className="field" style={{ maxWidth: 220 }}>
                    <label htmlFor="totp-current">Current code from your app</label>
                    <input id="totp-current" className="input auth-code" inputMode="numeric" autoComplete="one-time-code" maxLength={7} value={code} onChange={(e) => setCode(e.target.value)} autoFocus data-testid="totp-current" />
                  </div>
                  <button type="submit" className={`btn ${mode === "disable" ? "danger" : "primary"}`} disabled={busy} data-testid="totp-confirm-action">
                    {mode === "disable" ? "Turn off" : "Make new codes"}
                  </button>
                  <button type="button" className="btn" onClick={() => setMode(null)}>
                    Cancel
                  </button>
                </form>
              ) : (
                <div className="row wrap">
                  <button type="button" className="btn" onClick={() => setMode("recovery")} data-testid="totp-new-codes">
                    <Icon name="refresh" /> New recovery codes
                  </button>
                  {!status.required_by_org ? (
                    <button type="button" className="btn ghost" onClick={() => setMode("disable")} data-testid="totp-disable">
                      Turn off
                    </button>
                  ) : (
                    <span className="faint small">Your organisation requires two-step verification.</span>
                  )}
                </div>
              )}
            </div>
          ) : !sso ? (
            <div className="col" style={{ gap: 10 }}>
              <p style={{ margin: 0 }}>
                <span className="badge info">
                  <Icon name="lock" /> Off
                </span>{" "}
                Add a second step to signing in: after your password, a 6-digit code from an app on your phone.
              </p>
              <div>
                <button type="button" className="btn primary" onClick={() => void begin()} disabled={busy} data-testid="totp-begin">
                  <Icon name="lock" /> Turn on two-step verification
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
