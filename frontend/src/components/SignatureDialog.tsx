/**
 * Electronic signature dialog (M7 4.2, 10): one dialog for every signable action. It loads the server's preview
 * (`GET /mfg/esig/preview`: the content summary, its SHA-256, the policy step, the signer) and shows exactly that,
 * the meaning, "You are signing as <legal name> (<user name>)", user name + password (+ authenticator code) or an
 * SSO step-up, an optional comment and the signer's statement. The action is sent with the previewed hash, so a
 * record changed in between answers 409 `ESIG_CONTENT_CHANGED` and the dialog reloads the preview. 202 = a step
 * signature was recorded and the next step waits for another signer. 423 = signing locked after failed attempts.
 * When the plant is not in Part 11 mode (or the action has no policy) it is a plain confirmation.
 */
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router";
import { ApiError } from "../api/client";
import { Banner } from "./Banner";
import { Dialog } from "./Dialog";
import { Icon } from "./Icon";
import { getPreview, stepupUrl, type SignedResult } from "../mfg/api/clientM7";
import type { EsigPreview, Meaning, SignatureInput } from "../mfg/api/typesM7";
import { MfgError, RequestRef } from "../mfg/components/Feedback";
import { authText, manifestText, meaningText, recordTypeText, roleText } from "../mfg/qa/labels";
import { mfgPaths } from "../mfg/lib/paths";
import { formatDateTime, formatTime } from "../lib/locale";
import { errorMessage, plural, t } from "../lib/i18n";
import "../mfg/qa/qa.css";

export interface SignatureDialogProps<T> {
  /** what the action does, e.g. "Release inspection lot IL-000123" */
  title: string;
  recordType: string;
  recordId: string;
  action: string;
  /** inspection_lot.decide: accept | reject (preview content depends on it) */
  decision?: string;
  /** false for actions that are never signed (cancel, out of service): a plain confirmation without preview */
  signable?: boolean;
  /** the record's number for the "Record" line, e.g. "IL-000123" */
  recordLabel?: string;
  /** preset meaning (otherwise the step's only meaning, or a choice) */
  meaning?: Meaning;
  /** primary button when a signature is required, e.g. "Sign and release" */
  submitLabel: string;
  /** primary button without signature (Part 11 off), e.g. "Release" */
  plainLabel: string;
  /** what happens after signing (one sentence) */
  effect?: ReactNode;
  /** extra fields of the action (decision note, NCR) rendered above the signature */
  children?: ReactNode;
  canSubmit?: boolean;
  danger?: boolean;
  /** label of the comment field; the comment is also the change reason of the action */
  commentLabel?: string;
  commentRequired?: boolean;
  perform(signature: SignatureInput | null, comment: string): Promise<SignedResult<T>>;
  onDone(result: SignedResult<T>): void;
  onClose(): void;
}

type Problem = { kind: "auth"; remaining: number | null } | { kind: "locked"; until: string | null } | { kind: "changed" } | { kind: "other"; error: unknown } | null;

function decode(e: unknown): Problem {
  if (!(e instanceof ApiError)) return { kind: "other", error: e };
  if (e.code === "ESIG_AUTH_FAILED") {
    const r = Number(e.details.remaining);
    return { kind: "auth", remaining: Number.isFinite(r) ? r : null };
  }
  if (e.code === "ESIG_LOCKED" || e.status === 423) return { kind: "locked", until: typeof e.details.until === "string" ? e.details.until : null };
  if (e.code === "ESIG_CONTENT_CHANGED") return { kind: "changed" };
  return { kind: "other", error: e };
}

/** SSO step-up (4.2): a popup re-authenticates at the identity provider and posts a single-use token back. */
export function useStepup() {
  const [token, setToken] = useState<{ value: string; at: number } | null>(null);
  const [state, setState] = useState<"idle" | "waiting" | "blocked">("idle");
  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return;
      const d = e.data as { type?: string; token?: string } | null;
      if (d && d.type === "sp-esig-stepup" && typeof d.token === "string") {
        setToken({ value: d.token, at: Date.now() });
        setState("idle");
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);
  const start = () => {
    const w = window.open(stepupUrl(), "sp-esig-stepup", "width=520,height=680");
    setState(w ? "waiting" : "blocked");
  };
  return { token, state, start, clear: () => setToken(null) };
}

export function SignatureDialog<T>(props: SignatureDialogProps<T>) {
  const { recordType, recordId, action, decision } = props;
  const location = useLocation();
  const [preview, setPreview] = useState<EsigPreview | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [comment, setComment] = useState("");
  const [meaning, setMeaning] = useState<Meaning | "">(props.meaning ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>(null);
  const [changedNotice, setChangedNotice] = useState(false);
  const stepup = useStepup();
  const pwRef = useRef<HTMLInputElement>(null);
  const uid = useId().replace(/:/g, "");

  const signable = props.signable !== false;
  const load = useCallback(() => {
    const ctl = new AbortController();
    setLoadError(null);
    if (!signable) {
      // never-signed actions: a local, unsigned "preview" so the dialog is a plain confirmation
      setPreview({ record_type: recordType, record_id: recordId, action, record_version: 0, content_hash: "", content: {}, summary: [], required: false, part11_mode: false, policy: null, next_step: null, signatures: [], signer: { enrolled: false, legal_name: null, locked_until: null, methods: [], username: "" }, legal_statement: "" });
      return () => ctl.abort();
    }
    getPreview({ record_type: recordType, record_id: recordId, action, ...(decision ? { decision } : {}) }, ctl.signal).then(
      (p) => {
        setPreview(p);
        const ms = p.next_step?.meanings ?? [];
        if (!props.meaning && ms.length === 1) setMeaning(ms[0]);
      },
      (e: unknown) => {
        if (!ctl.signal.aborted) setLoadError(e);
      },
    );
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordType, recordId, action, decision, signable]);
  useEffect(() => load(), [load]);

  const required = Boolean(preview?.required);
  const signer = preview?.signer ?? null;
  const step = preview?.next_step ?? null;
  const totpNeeded = step?.auth === "password_totp";
  // SSO users without local signing credentials re-authenticate at the identity provider (step-up)
  const sso = Boolean(signer) && !signer!.methods.some((m) => m === "password" || m === "password_totp") && signer!.methods.some((m) => m === "sso" || m === "sso_mfa");
  const lockedUntil = problem?.kind === "locked" ? problem.until : signer?.locked_until && new Date(signer.locked_until).getTime() > Date.now() ? signer.locked_until : null;
  const locked = problem?.kind === "locked" || Boolean(lockedUntil);
  const notEnrolled = required && signer !== null && (!signer.enrolled || step?.blocked_reason === "ESIG_NOT_ENROLLED");
  const blockers = step && !step.can_sign && step.blocked_reason && step.blocked_reason !== "ESIG_NOT_ENROLLED" ? [step.blocked_reason] : [];
  const credsOk = sso ? Boolean(stepup.token) && Boolean(username.trim()) : Boolean(username.trim()) && Boolean(password) && (!totpNeeded || /^\d{6}$/.test(totp.trim()));
  const ready =
    preview !== null &&
    props.canSubmit !== false &&
    !busy &&
    (!props.commentRequired || Boolean(comment.trim())) &&
    (!required || (credsOk && Boolean(meaning) && !locked && !notEnrolled && blockers.length === 0));

  const submit = async () => {
    if (!preview || !ready) return;
    setBusy(true);
    setProblem(null);
    setChangedNotice(false);
    const sig: SignatureInput | null = required
      ? {
          meaning: meaning as Meaning,
          content_hash: preview.content_hash,
          username: username.trim(),
          ...(sso ? { stepup_token: stepup.token!.value } : { password }),
          ...(totpNeeded && !sso ? { totp_code: totp.trim() } : {}),
          ...(comment.trim() ? { comment: comment.trim() } : {}),
        }
      : null;
    try {
      const res = await props.perform(sig, comment.trim());
      props.onDone(res);
    } catch (e) {
      const p = decode(e);
      // credentials are never kept after an attempt; the step-up token is single use
      setPassword("");
      setTotp("");
      stepup.clear();
      if (p?.kind === "changed") {
        setChangedNotice(true);
        setPreview(null);
        load();
      } else setProblem(p);
      setBusy(false);
      if (p?.kind === "auth") window.setTimeout(() => pwRef.current?.focus(), 0);
    }
  };

  const title = preview && !required ? props.title.charAt(0).toUpperCase() + props.title.slice(1) : t("qa.esig.tpl.dialogTitle", { what: props.title });
  return (
    <Dialog
      title={title}
      onClose={props.onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={props.onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className={`btn ${props.danger ? "danger" : "primary"}`} onClick={() => void submit()} disabled={!ready} data-testid="esig-submit">
            {busy ? <span className="spinner" aria-hidden /> : required ? <Icon name="lock" /> : null}
            {required ? props.submitLabel : props.plainLabel}
          </button>
        </>
      }
    >
      <form
        className="col esig-form"
        data-testid="esig-dialog"
        data-required={required ? "true" : "false"}
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {loadError ? <MfgError error={loadError} onRetry={load} title={t("qa.esig.title.previewFailed")} /> : null}
        {changedNotice ? (
          <Banner tone="warn" role="alert" title={t("qa.esig.title.contentChanged")} testId="esig-changed">
            {t("qa.esig.text.contentChanged")}
          </Banner>
        ) : null}
        {!preview && !loadError ? (
          <div className="skel-rows" aria-busy="true" aria-label={t("qa.esig.aria.loadingPreview")}>
            <div className="skel skel-row" />
            <div className="skel skel-row" />
            <div className="skel skel-row" />
          </div>
        ) : null}
        {preview ? (
          <>
            {props.effect ? <p className="esig-effect">{props.effect}</p> : null}
            <section className="esig-content" aria-labelledby={`${uid}-what`}>
              <h3 id={`${uid}-what`}>{required ? t("qa.esig.head.whatYouSign") : t("qa.esig.head.record")}</h3>
              <dl className="mfg-dl">
                <dt>{t("qa.esig.label.record")}</dt>
                <dd>
                  {recordTypeText(preview.record_type)} <span className="mono">{props.recordLabel ?? preview.record_id}</span>{" "}
                  {signable ? <span className="muted small">{t("qa.esig.tpl.version", { v: preview.record_version })}</span> : null}
                </dd>
                {preview.summary.map((l, i) => (
                  <PreviewRow key={i} label={l.label} value={l.value} />
                ))}
                {required ? (
                  <>
                    <dt>{t("qa.esig.label.fingerprint")}</dt>
                    <dd>
                      <code className="esig-hash" data-testid="esig-hash">
                        {preview.content_hash}
                      </code>
                      <span className="muted small"> {t("qa.esig.text.fingerprintHint")}</span>
                    </dd>
                  </>
                ) : null}
              </dl>
              {required ? (
                <details className="esig-raw">
                  <summary>{t("qa.esig.btn.showContent")}</summary>
                  <pre>{JSON.stringify(preview.content, null, 2)}</pre>
                </details>
              ) : null}
            </section>
            {props.children}
            {required && preview.signatures.length ? (
              <section className="col" style={{ gap: 4 }}>
                <h3 className="esig-sub">{t("qa.esig.head.earlierSteps")}</h3>
                <ul className="esig-manifest-list">
                  {preview.signatures.map((s) => (
                    <li key={s.id} data-testid="esig-manifest">
                      <Icon name="check" size={14} /> {manifestText(s)}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            {required && step ? (
              <section className="esig-step" aria-label={t("qa.esig.aria.step")}>
                <div className="row wrap" style={{ gap: 8 }}>
                  <span className="badge accent">
                    <Icon name="flag" />
                    {preview.policy && preview.policy.steps.length > 1 ? t("qa.esig.tpl.stepOf", { n: step.step, m: preview.policy.steps.length }) : t("qa.esig.text.signature")}
                  </span>
                  <span className="small muted">{t("qa.esig.tpl.whoMaySign", { roles: step.roles.map(roleText).join(", ") })}</span>
                  <span className="small muted">· {authText(step.auth)}</span>
                </div>
                {step.meanings.length > 1 && !props.meaning ? (
                  <fieldset className="esig-meanings">
                    <legend>{t("qa.esig.label.meaning")}</legend>
                    {step.meanings.map((m) => (
                      <label key={m} className="checkbox">
                        <input type="radio" name={`${uid}-meaning`} value={m} checked={meaning === m} onChange={() => setMeaning(m)} />
                        {meaningText(m)}
                      </label>
                    ))}
                  </fieldset>
                ) : (
                  <p className="esig-meaning">
                    {t("qa.esig.label.meaning")} <strong data-testid="esig-meaning">{meaning ? meaningText(meaning) : ""}</strong>
                  </p>
                )}
              </section>
            ) : null}
            {required && blockers.length ? (
              <Banner tone="warn" role="alert" icon="lock" title={t("qa.esig.title.cannotSign")} testId="esig-blocked">
                <ul className="mfg-plain-list">
                  {blockers.map((b) => (
                    <li key={b}>{blockerText(b)}</li>
                  ))}
                </ul>
              </Banner>
            ) : null}
            {notEnrolled ? (
              <Banner
                tone="warn"
                role="alert"
                icon="user"
                title={t("qa.esig.title.notEnrolled")}
                testId="esig-not-enrolled"
                actions={
                  <Link className="btn sm" to={mfgPaths.esigEnroll(location.pathname + location.search)}>
                    {t("qa.esig.btn.enrolNow")}
                  </Link>
                }
              >
                {t("qa.esig.text.notEnrolled")}
              </Banner>
            ) : null}
            {required && locked ? (
              <Banner tone="danger" role="alert" icon="lock" title={t("qa.esig.title.locked")} testId="esig-locked">
                {lockedUntil ? t("qa.esig.tpl.lockedUntil", { time: formatTime(lockedUntil), date: formatDateTime(lockedUntil) }) : t("qa.esig.text.lockedNoTime")} {t("qa.esig.text.lockedNotified")}
              </Banner>
            ) : null}
            {required && !notEnrolled && !locked && signer ? (
              <section className="esig-signer" aria-labelledby={`${uid}-who`}>
                <h3 id={`${uid}-who`} className="esig-sub">
                  {t("qa.esig.head.reauth")}
                </h3>
                <p className="esig-as" data-testid="esig-signer">
                  <Icon name="user" size={14} /> {t("qa.esig.tpl.signingAs", { name: signer.legal_name ?? "", username: signer.username })}
                </p>
                <div className="esig-fields">
                  <div className="field">
                    <label htmlFor={`${uid}-u`}>{t("qa.esig.label.username")}</label>
                    <input
                      id={`${uid}-u`}
                      className="input"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      autoComplete="off"
                      autoCapitalize="off"
                      spellCheck={false}
                      data-autofocus
                      data-testid="esig-username"
                      aria-invalid={problem?.kind === "auth" || undefined}
                    />
                  </div>
                  {sso ? (
                    <div className="field">
                      <span className="field-label">{t("qa.esig.label.companyAccount")}</span>
                      {stepup.token ? (
                        <span className="badge ok" data-testid="esig-stepup-ok">
                          <Icon name="check" />
                          {t("qa.esig.tpl.reauthenticatedAt", { time: formatTime(stepup.token.at) })}
                        </span>
                      ) : (
                        <button type="button" className="btn" onClick={stepup.start} data-testid="esig-stepup">
                          <Icon name="external" /> {t("qa.esig.btn.stepup")}
                        </button>
                      )}
                      {stepup.state === "waiting" && !stepup.token ? <span className="hint">{t("qa.esig.text.stepupWaiting")}</span> : null}
                      {stepup.state === "blocked" ? <span className="field-error">{t("qa.esig.text.stepupBlocked")}</span> : null}
                    </div>
                  ) : (
                    <div className="field">
                      <label htmlFor={`${uid}-p`}>{t("qa.esig.label.password")}</label>
                      <input
                        ref={pwRef}
                        id={`${uid}-p`}
                        className="input"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete="current-password"
                        data-testid="esig-password"
                        aria-invalid={problem?.kind === "auth" || undefined}
                        aria-describedby={problem?.kind === "auth" ? `${uid}-autherr` : undefined}
                      />
                    </div>
                  )}
                  {totpNeeded && !sso ? (
                    <div className="field">
                      <label htmlFor={`${uid}-t`}>{t("qa.esig.label.totp")}</label>
                      <input
                        id={`${uid}-t`}
                        className="input esig-totp"
                        value={totp}
                        onChange={(e) => setTotp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={6}
                        placeholder="000000"
                        data-testid="esig-totp"
                      />
                    </div>
                  ) : null}
                </div>
                {problem?.kind === "auth" ? (
                  <p className="field-error" id={`${uid}-autherr`} role="alert" data-testid="esig-auth-error">
                    <Icon name="alert" size={12} />{" "}
                    {problem.remaining !== null
                      ? t("qa.esig.tpl.authFailed", { left: plural(problem.remaining, t("qa.esig.str.attempt"), t("qa.esig.str.attempts")) })
                      : t("qa.esig.text.authFailedNoCount")}
                  </p>
                ) : (
                  <p className="hint">{sso ? t("qa.esig.text.hintSso") : t("qa.esig.text.hintPassword")}</p>
                )}
              </section>
            ) : null}
            {!locked && !notEnrolled ? (
              <div className="field">
                <label htmlFor={`${uid}-c`}>
                  {props.commentLabel ?? (required ? t("qa.esig.label.comment") : t("qa.esig.label.note"))}
                  {props.commentRequired ? <span className="mfg-required" aria-hidden> *</span> : null}
                </label>
                <textarea id={`${uid}-c`} className="textarea" rows={2} maxLength={500} value={comment} onChange={(e) => setComment(e.target.value)} data-testid="esig-comment" />
                <span className="hint">{t("qa.esig.tpl.chars", { n: comment.length })}</span>
              </div>
            ) : null}
            {required && !locked && !notEnrolled ? (
              <p className="esig-statement" data-testid="esig-statement">
                {t("qa.esig.tpl.statement", { meaning: meaning ? meaningText(meaning).toLowerCase() : "…" })}
              </p>
            ) : null}
            {problem?.kind === "other" ? <SignError error={problem.error} /> : null}
          </>
        ) : null}
        <button type="submit" hidden tabIndex={-1} />
      </form>
    </Dialog>
  );
}

function PreviewRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

/** Signature refusals in words (role, same signer, author, clock) with the request reference. */
function SignError({ error }: { error: unknown }) {
  if (!(error instanceof ApiError)) return <MfgError error={error} />;
  const known: Record<string, "qa.esig.title.role" | "qa.esig.title.sameSigner" | "qa.esig.title.author" | "qa.esig.title.clock" | "qa.esig.title.mfa" | "qa.esig.title.notAllowed"> = {
    ESIG_ROLE: "qa.esig.title.role",
    ESIG_SAME_SIGNER: "qa.esig.title.sameSigner",
    ESIG_AUTHOR: "qa.esig.title.author",
    ESIG_CLOCK_SKEW: "qa.esig.title.clock",
    ESIG_MFA_UNAVAILABLE: "qa.esig.title.mfa",
    ESIG_NOT_ALLOWED: "qa.esig.title.notAllowed",
  };
  const k = known[error.code];
  if (!k) return <MfgError error={error} />;
  return (
    <Banner tone="danger" role="alert" title={t(k)} testId="esig-error" icon="lock">
      {errorMessage(error.code, error.message)}
      <RequestRef error={error} />
    </Banner>
  );
}

const BLOCKERS: Record<string, "qa.esig.title.role" | "qa.esig.title.sameSigner" | "qa.esig.title.author"> = {
  ESIG_ROLE: "qa.esig.title.role",
  ESIG_SAME_SIGNER: "qa.esig.title.sameSigner",
  ESIG_AUTHOR: "qa.esig.title.author",
};
const blockerText = (code: string) => (BLOCKERS[code] ? t(BLOCKERS[code]) : errorMessage(code, code));

/** Toast text after a signed action: done, or the next step waiting for someone else. */
export function signedToast(res: SignedResult<unknown>, done: string): string {
  if (res.status === 200) return done;
  const n = res.pending.next_step;
  const last = res.pending.signatures[res.pending.signatures.length - 1];
  const mine = last ? meaningText(last.meaning) : "";
  return n ? t("qa.esig.tpl.pendingNext", { mine, next: n.meanings.map(meaningText).join(" / "), roles: n.roles.map(roleText).join(", ") }) : t("qa.esig.tpl.pendingDone", { mine });
}
