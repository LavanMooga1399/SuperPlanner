/**
 * `/account/signature` (M7 4.1): electronic signature enrolment. A person signs only after enrolling once with
 * their legal name, their password (or an SSO step-up) and the acknowledgement that the electronic signature is
 * the legally binding equivalent of their handwritten signature (text in the UI language, versioned by the server).
 * Shows the enrolment, revocation by an administrator and an active signing lockout.
 */
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Banner } from "../components/Banner";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { useStepup } from "../components/SignatureDialog";
import { toast } from "../components/Toast";
import { enrollEsig } from "../mfg/api/clientM7";
import { MfgError, Spinner } from "../mfg/components/Feedback";
import { FormErrors, Field } from "../mfg/components/Field";
import { setEsigStatus, useEsigStatus } from "../mfg/qa/part11";
import { formatDateTime, formatTime } from "../lib/locale";
import { getLocale, t } from "../lib/i18n";
import "../mfg/qa/qa.css";

export function SignatureEnrolPage() {
  const [params] = useSearchParams();
  const next = params.get("next");
  const { status, loading, error, refresh } = useEsigStatus();
  const [legal, setLegal] = useState("");
  const [password, setPassword] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const stepup = useStepup("enroll");
  useEffect(() => {
    document.title = t("qa.enrol.str.docTitle");
  }, []);
  useEffect(() => {
    if (status?.legal_name && !legal) setLegal(status.legal_name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);
  if (loading) return <Spinner />;
  const sso = Boolean(status?.sso) && !status?.local_credentials;
  const ackText = status ? (status.ack_text[getLocale()] ?? status.ack_text.en ?? Object.values(status.ack_text)[0] ?? "") : "";
  const needsRenewal = Boolean(status?.enrolled && status.ack_version !== status.current_ack_version);
  const showForm = status && (!status.enrolled || needsRenewal) && !status.revoked_at;
  const locked = status?.locked_until && new Date(status.locked_until).getTime() > Date.now() ? status.locked_until : null;
  return (
    <div className="col gap-lg" style={{ maxWidth: 820 }} data-testid="esig-enrol">
      <PageHeader title={t("qa.enrol.title")} description={t("qa.enrol.desc")} />
      <MfgError error={error} onRetry={refresh} />
      {status === null && !error ? <Banner tone="info">{t("qa.enrol.text.unavailable")}</Banner> : null}
      {locked ? (
        <Banner tone="danger" icon="lock" title={t("qa.esig.title.locked")}>
          {t("qa.esig.tpl.lockedUntil", { time: formatTime(locked), date: formatDateTime(locked) })} {t("qa.esig.text.lockedNotified")}
        </Banner>
      ) : null}
      {status?.revoked_at ? (
        <Banner tone="warn" icon="ban" title={t("qa.enrol.title.revoked")} testId="esig-revoked">
          {t("qa.enrol.tpl.revoked", { when: formatDateTime(status.revoked_at) })}
        </Banner>
      ) : null}
      {status?.enrolled && !status.revoked_at ? (
        <section className="card">
          <div className="card-header">
            <h2>{t("qa.enrol.head.enrolled")}</h2>
            <span className="badge ok" data-testid="esig-enrolled">
              <Icon name="check" /> {t("qa.enrol.str.enrolled")}
            </span>
          </div>
          <div className="card-body">
            <dl className="mfg-dl">
              <dt>{t("qa.enrol.label.legalName")}</dt>
              <dd>{status.legal_name}</dd>
              <dt>{t("qa.esig.label.username")}</dt>
              <dd className="mono">{status.username}</dd>
              <dt>{t("qa.enrol.label.since")}</dt>
              <dd>{formatDateTime(status.enrolled_at)}</dd>
              <dt>{t("qa.enrol.label.method")}</dt>
              <dd>{sso ? t("qa.esig.auth.sso") : status.totp_enabled ? t("qa.enrol.str.pwTotp") : t("qa.esig.auth.password")}</dd>
            </dl>
            {next ? (
              <p style={{ marginBottom: 0 }}>
                <Link className="btn primary" to={next}>
                  <Icon name="arrow-right" /> {t("qa.enrol.btn.back")}
                </Link>
              </p>
            ) : null}
          </div>
        </section>
      ) : null}
      {needsRenewal ? <Banner tone="warn" title={t("qa.enrol.title.renew")}>{t("qa.enrol.text.renew")}</Banner> : null}
      {showForm ? (
        <FormErrors error={err}>
          <form
            className="card"
            onSubmit={async (e) => {
              e.preventDefault();
              if (busy) return;
              setBusy(true);
              setErr(null);
              try {
                const s = await enrollEsig({ legal_name: legal.trim(), ...(sso ? { stepup_token: stepup.token?.value } : { password }), acknowledgement: true });
                setEsigStatus(s);
                setPassword("");
                toast(t("qa.enrol.toast.done"));
              } catch (x) {
                setErr(x);
                setPassword("");
                stepup.clear();
              } finally {
                setBusy(false);
              }
            }}
          >
            <div className="card-header">
              <h2>{t("qa.enrol.head.form")}</h2>
            </div>
            <div className="card-body col">
              <Field label={t("qa.enrol.label.legalName")} name="legal_name" required hint={t("qa.enrol.hint.legalName")}>
                {(id) => <input id={id} className="input" value={legal} onChange={(e) => setLegal(e.target.value)} maxLength={200} autoComplete="name" data-testid="esig-legal-name" />}
              </Field>
              {sso ? (
                <div className="field">
                  <span className="label">{t("qa.esig.label.companyAccount")}</span>
                  {stepup.token ? (
                    <span className="badge ok">
                      <Icon name="check" /> {t("qa.esig.tpl.reauthenticatedAt", { time: formatTime(stepup.token.at) })}
                    </span>
                  ) : (
                    <div>
                      <button type="button" className="btn" onClick={stepup.start}>
                        <Icon name="external" /> {t("qa.esig.btn.stepup")}
                      </button>
                    </div>
                  )}
                  {stepup.state === "blocked" ? <span className="field-error">{t("qa.esig.text.stepupBlocked")}</span> : null}
                </div>
              ) : (
                <Field label={t("qa.enrol.label.password")} name="password" required hint={t("qa.enrol.hint.password")}>
                  {(id) => <input id={id} className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" data-testid="esig-enrol-password" style={{ maxWidth: 320 }} />}
                </Field>
              )}
              <div className="esig-statement" data-testid="esig-ack-text">
                {ackText}
              </div>
              <label className="checkbox" style={{ alignItems: "flex-start" }}>
                <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} data-testid="esig-ack" />
                <span>{t("qa.enrol.label.ack")}</span>
              </label>
              <MfgError error={err} />
              <div>
                <button type="submit" className="btn primary" disabled={busy || !ack || !legal.trim() || (sso ? !stepup.token : !password)} data-testid="esig-enrol-submit">
                  {busy ? <span className="spinner" aria-hidden /> : <Icon name="lock" />} {needsRenewal ? t("qa.enrol.btn.renew") : t("qa.enrol.btn.enrol")}
                </button>
              </div>
            </div>
          </form>
        </FormErrors>
      ) : null}
      <p className="small muted" style={{ margin: 0 }}>
        {t("qa.enrol.text.footer")}
      </p>
    </div>
  );
}
