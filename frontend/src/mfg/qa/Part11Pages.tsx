/**
 * Part 11 administration (M7 4, 10 "Control"): signature policies (E1-E2, a change is itself signed), the plant's
 * Part 11 mode (E11-E12, switched on by a signed owner action, not switchable off) and the inspection-readiness
 * export (E8-E10). Copy states what the controls do; it never claims compliance (the customer validates).
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { Banner } from "../../components/Banner";
import { DateInput } from "../../components/DateInput";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { saveBlob } from "../api/client";
import { createPart11Export, downloadPart11Export, enablePart11, getMetaTime, listPart11Exports, listPolicies, updatePolicy } from "../api/clientM7";
import type { EsigPolicy, Meaning, Part11Export, PolicyAuth, PolicyStep } from "../api/typesM7";
import { MEANINGS } from "../api/typesM7";
import { MfgError, Spinner } from "../components/Feedback";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useAccess, useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { usePolling } from "../lib/usePolling";
import { formatDateTime, formatDateRange, formatNumber } from "../../lib/locale";
import { t } from "../../lib/i18n";
import { actionText, authText, meaningText, recordTypeText, roleText } from "./labels";
import { setPart11Mode, usePart11 } from "./part11";
import { SignatureList } from "./RecordShell";
import "./qa.css";

const POLICY_ROLES = ["qa_inspector", "qa_engineer", "qa_approver", "metrology", "approver", "supervisor", "owner", "plant_admin"];

function StepsView({ steps }: { steps: PolicyStep[] }) {
  return (
    <span className="qa-steps">
      {steps.map((s, i) => (
        <span key={i} className="qa-step">
          {i > 0 ? <Icon name="arrow-right" size={12} aria-hidden /> : null}
          <span className="qa-step-num" aria-hidden>
            {i + 1}
          </span>
          <strong>{meaningText(s.meaning)}</strong>
          <span className="muted">{s.roles.map(roleText).join(", ")}</span>
        </span>
      ))}
    </span>
  );
}

const stepsText = (steps: PolicyStep[]) => steps.map((s, i) => `${i + 1}. ${meaningText(s.meaning)}: ${s.roles.map(roleText).join(", ")}`).join("; ");

// ---------------------------------------------------------------- E1-E2 policies
export function PoliciesPage() {
  const canEdit = useCan("esig_policy_edit");
  const { enabled } = usePart11();
  const data = useLoad((s) => listPolicies(s), []);
  const [editing, setEditing] = useState<EsigPolicy | null>(null);
  const [signing, setSigning] = useState<{ policy: EsigPolicy; next: Omit<EsigPolicy, "id"> } | null>(null);
  useEffect(() => {
    document.title = t("qa.pol.str.docTitle");
  }, []);
  const cols: Column<EsigPolicy>[] = [
    {
      key: "what",
      header: t("qa.pol.head.action"),
      width: "minmax(220px, 1.2fr)",
      sortValue: (p) => `${p.record_type}.${p.action}`,
      exportValue: (p) => `${p.record_type}.${p.action}`,
      render: (p) => (
        <span className="col" style={{ gap: 0 }}>
          <span>
            {recordTypeText(p.record_type)} · {actionText(p.action)}
          </span>
        </span>
      ),
    },
    { key: "steps", header: t("qa.pol.head.steps"), width: "minmax(320px, 2.4fr)", wrap: true, exportValue: (p) => stepsText(p.steps), render: (p) => <StepsView steps={p.steps} /> },
    { key: "auth", header: t("qa.pol.head.auth"), width: "minmax(170px, 1fr)", wrap: true, sortValue: (p) => p.auth, exportValue: (p) => authText(p.auth), render: (p) => authText(p.auth) },
    {
      key: "rules",
      header: t("qa.pol.head.rules"),
      width: "minmax(170px, 1fr)",
      wrap: true,
      exportValue: (p) => [p.distinct_signers && p.steps.length > 1 ? t("qa.pol.str.distinct") : "", p.exclude_author ? t("qa.pol.str.noAuthor") : ""].filter(Boolean).join("; "),
      render: (p) => (
        <span className="col small" style={{ gap: 0 }}>
          {p.distinct_signers && p.steps.length > 1 ? <span>{t("qa.pol.str.distinct")}</span> : null}
          {p.exclude_author ? <span>{t("qa.pol.str.noAuthor")}</span> : null}
          {!(p.distinct_signers && p.steps.length > 1) && !p.exclude_author ? <span className="faint">—</span> : null}
        </span>
      ),
    },
    { key: "ver", header: t("qa.pol.head.version"), width: "80px", align: "right", sortValue: (p) => p.version, render: (p) => p.version },
    {
      key: "edit",
      header: "",
      label: t("qa.pol.head.edit"),
      width: "84px",
      hideable: false,
      render: (p) =>
        canEdit ? (
          <button type="button" className="btn sm" onClick={() => setEditing(p)} data-testid="policy-edit">
            {t("qa.pol.btn.edit")}
          </button>
        ) : null,
    },
  ];
  return (
    <div className="col gap-lg" data-testid="esig-policies">
      <PageHeader title={t("qa.pol.title")} description={t("qa.pol.desc")} />
      {!enabled ? (
        <Banner tone="info" title={t("qa.pol.title.modeOff")} actions={<Link className="btn sm" to={mfgPaths.part11()}>{t("qa.pol.btn.part11")}</Link>}>
          {t("qa.pol.text.modeOff")}
        </Banner>
      ) : null}
      <MfgError error={data.error} onRetry={data.reload} />
      <section className="card card-table">
        <DataTable rows={data.data?.items ?? []} columns={cols} rowKey={(p) => p.id} label={t("qa.pol.title")} tableId="esig-policies" loading={data.loading} exportName="signature-policies" empty={t("qa.pol.empty")} rowExtras={(p) => ({ testId: "policy-row", data: { key: `${p.record_type}.${p.action}` } })} />
      </section>
      <p className="small muted" style={{ margin: 0 }}>
        {t("qa.pol.text.footnote")}
      </p>
      {editing ? (
        <PolicyDialog
          policy={editing}
          onClose={() => setEditing(null)}
          onNext={(next) => {
            setSigning({ policy: editing, next });
            setEditing(null);
          }}
        />
      ) : null}
      {signing ? (
        <SignatureDialog<EsigPolicy>
          title={t("qa.pol.tpl.signTitle", { what: `${recordTypeText(signing.policy.record_type)} · ${actionText(signing.policy.action)}` })}
          recordType="esig_policy"
          recordId={signing.policy.id}
          action="update"
          meaning="approved"
          submitLabel={t("qa.pol.btn.signSave")}
          plainLabel={t("qa.pol.btn.save")}
          commentLabel={t("qa.pol.label.reason")}
          commentRequired
          effect={t("qa.pol.text.effect")}
          perform={(signature, comment) =>
            updatePolicy(signing.policy.record_type, signing.policy.action, { steps: signing.next.steps, auth: signing.next.auth, distinct_signers: signing.next.distinct_signers, exclude_author: signing.next.exclude_author, ...(signature ? { signature: { ...signature, comment } } : {}) }, signing.policy.row_version)
          }
          onDone={(res) => {
            toast(signedToast(res, t("qa.pol.toast.saved")));
            setSigning(null);
            data.reload();
          }}
          onClose={() => setSigning(null)}
        >
          <section className="esig-content">
            <h3>{t("qa.pol.head.newPolicy")}</h3>
            <dl className="mfg-dl">
              <dt>{t("qa.pol.head.steps")}</dt>
              <dd>{stepsText(signing.next.steps)}</dd>
              <dt>{t("qa.pol.head.auth")}</dt>
              <dd>{authText(signing.next.auth)}</dd>
              <dt>{t("qa.pol.head.rules")}</dt>
              <dd>{[signing.next.distinct_signers ? t("qa.pol.str.distinct") : "", signing.next.exclude_author ? t("qa.pol.str.noAuthor") : ""].filter(Boolean).join("; ") || "—"}</dd>
            </dl>
          </section>
        </SignatureDialog>
      ) : null}
    </div>
  );
}

function PolicyDialog({ policy, onClose, onNext }: { policy: EsigPolicy; onClose(): void; onNext(p: Omit<EsigPolicy, "id">): void }) {
  const [steps, setSteps] = useState<PolicyStep[]>(policy.steps.map((s) => ({ ...s, roles: [...s.roles] })));
  const [auth, setAuth] = useState<PolicyAuth>(policy.auth);
  const [distinct, setDistinct] = useState(policy.distinct_signers);
  const [noAuthor, setNoAuthor] = useState(policy.exclude_author);
  const problems: string[] = [];
  if (!steps.length) problems.push(t("qa.pol.err.noSteps"));
  steps.forEach((s, i) => {
    if (!s.roles.length) problems.push(t("qa.pol.err.noRoles", { n: i + 1 }));
  });
  if (policy.auth === "password_totp" && auth === "password") problems.push(t("qa.pol.err.lowerAuth"));
  return (
    <Dialog
      title={t("qa.pol.tpl.editTitle", { what: `${recordTypeText(policy.record_type)} · ${actionText(policy.action)}` })}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={problems.length > 0} onClick={() => onNext({ ...policy, steps, auth, distinct_signers: distinct, exclude_author: noAuthor })} data-testid="policy-continue">
            {t("qa.pol.btn.continue")}
          </button>
        </>
      }
    >
      <div className="col">
        <p className="muted" style={{ margin: 0 }}>
          {t("qa.pol.text.editIntro")}
        </p>
        <div role="group" aria-label={t("qa.pol.head.steps")}>
          {steps.map((s, i) => (
            <div key={i} className="qa-step-editor">
              <span className="qa-step-num" style={{ marginTop: 6 }}>
                {i + 1}
              </span>
              <div className="field">
                <label htmlFor={`ps-m-${i}`} className="sr-only">
                  {t("qa.pol.tpl.meaningOf", { n: i + 1 })}
                </label>
                <select id={`ps-m-${i}`} className="select" value={s.meaning} onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, meaning: e.target.value as Meaning } : x)))}>
                  {MEANINGS.map((m) => (
                    <option key={m} value={m}>
                      {meaningText(m)}
                    </option>
                  ))}
                </select>
              </div>
              <fieldset className="qa-role-checks" style={{ border: 0, padding: 0, margin: 0 }}>
                <legend className="sr-only">{t("qa.pol.tpl.rolesOf", { n: i + 1 })}</legend>
                {POLICY_ROLES.map((r) => (
                  <label key={r} className="checkbox small">
                    <input type="checkbox" checked={s.roles.includes(r)} onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, roles: e.target.checked ? [...x.roles, r] : x.roles.filter((y) => y !== r) } : x)))} />
                    {roleText(r)}
                  </label>
                ))}
              </fieldset>
              <button type="button" className="btn ghost sm icon" disabled={steps.length === 1 && policy.fixed} aria-label={t("qa.pol.tpl.removeStep", { n: i + 1 })} onClick={() => setSteps(steps.filter((_, j) => j !== i))}>
                <Icon name="trash" size={14} />
              </button>
            </div>
          ))}
        </div>
        <div>
          <button type="button" className="btn sm" onClick={() => setSteps([...steps, { meaning: "approved", roles: ["qa_approver"] }])}>
            <Icon name="plus" /> {t("qa.pol.btn.addStep")}
          </button>
        </div>
        <div className="qa-form-grid">
          <div className="field">
            <label htmlFor="pol-auth">{t("qa.pol.head.auth")}</label>
            <select id="pol-auth" className="select" value={auth} onChange={(e) => setAuth(e.target.value as PolicyAuth)}>
              <option value="password">{authText("password")}</option>
              <option value="password_totp">{authText("password_totp")}</option>
            </select>
          </div>
          <label className="checkbox" style={{ alignSelf: "end" }}>
            <input type="checkbox" checked={distinct} onChange={(e) => setDistinct(e.target.checked)} /> {t("qa.pol.str.distinct")}
          </label>
          <label className="checkbox" style={{ alignSelf: "end" }}>
            <input type="checkbox" checked={noAuthor} onChange={(e) => setNoAuthor(e.target.checked)} /> {t("qa.pol.str.noAuthor")}
          </label>
        </div>
        {problems.length ? (
          <ul className="field-error mfg-plain-list" role="alert">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- E11-E12 Part 11 mode
export function Part11Page() {
  const access = useAccess();
  const p11 = usePart11();
  const time = useLoad((s) => getMetaTime(s).catch(() => null), []);
  const [confirm, setConfirm] = useState(false);
  const [signing, setSigning] = useState(false);
  useEffect(() => {
    document.title = t("qa.p11.str.docTitle");
  }, []);
  const m = p11.mode;
  if (p11.loading) return <Spinner />;
  return (
    <div className="col gap-lg" data-testid="part11-page">
      <PageHeader
        title={t("qa.p11.title")}
        meta={
          m?.enabled ? (
            <span className="badge ok" data-testid="part11-state" data-on="true">
              <Icon name="lock" /> {t("qa.p11.str.on")}
            </span>
          ) : (
            <span className="badge info" data-testid="part11-state" data-on="false">
              <Icon name="unlock" /> {t("qa.p11.str.off")}
            </span>
          )
        }
        description={t("qa.p11.desc")}
        actions={
          !m?.enabled ? (
            <button type="button" className="btn primary" disabled={!access.isOwner || !m} title={access.isOwner ? undefined : t("qa.p11.str.ownerOnly")} onClick={() => setConfirm(true)} data-testid="part11-enable">
              <Icon name="lock" /> {t("qa.p11.btn.enable")}
            </button>
          ) : null
        }
      />
      <MfgError error={p11.error} onRetry={p11.refresh} />
      <div className="grid-2">
        <section className="card">
          <div className="card-header">
            <h2>{t("qa.p11.head.what")}</h2>
          </div>
          <div className="card-body col">
            <ul className="mfg-plain-list col" style={{ gap: 6 }}>
              {(["qa.p11.li.policies", "qa.p11.li.reason", "qa.p11.li.values", "qa.p11.li.delete", "qa.p11.li.final"] as const).map((k) => (
                <li key={k} className="row" style={{ alignItems: "flex-start", gap: 8 }}>
                  <Icon name="check" size={14} /> <span>{t(k)}</span>
                </li>
              ))}
            </ul>
            <p className="small muted" style={{ margin: 0 }}>
              {t("qa.p11.text.position")}
            </p>
          </div>
        </section>
        <section className="card">
          <div className="card-header">
            <h2>{m?.enabled ? t("qa.p11.head.switchedOn") : t("qa.p11.head.readiness")}</h2>
          </div>
          <div className="card-body col">
            {m?.enabled ? (
              <>
                <p style={{ margin: 0 }}>{t("qa.p11.tpl.since", { when: formatDateTime(m.enabled_at), who: m.enabled_by ?? "" })}</p>
                <SignatureList signatures={m.signatures} />
              </>
            ) : (
              <ul className="mfg-plain-list col" style={{ gap: 6 }} data-testid="part11-checks">
                {m
                  ? ([
                      [m.esig_enabled, t("qa.p11.check.esig")],
                      [m.secrets_configured, t("qa.p11.check.secrets")],
                      [m.clock_skew_ms !== null && Math.abs(m.clock_skew_ms) <= m.max_clock_skew_ms, t("qa.p11.check.clock")],
                    ] as [boolean, string][]).map(([ok, text]) => (
                      <li key={text} className="row" style={{ alignItems: "flex-start", gap: 8 }}>
                        <span className={`badge ${ok ? "ok" : "warn"}`}>
                          <Icon name={ok ? "check" : "alert"} /> {ok ? t("qa.p11.str.ready") : t("qa.p11.str.todo")}
                        </span>
                        <span>{text}</span>
                      </li>
                    ))
                  : <li className="muted">{t("qa.p11.text.noChecks")}</li>}
                <li className="row" style={{ alignItems: "flex-start", gap: 8 }}>
                  <span className="badge info">
                    <Icon name="info" /> {t("qa.p11.str.yours")}
                  </span>
                  <span>{t("qa.p11.check.enrol")}</span>
                </li>
              </ul>
            )}
            {time.data ? (
              <p className="small muted" style={{ margin: 0 }} data-testid="part11-clock">
                {t("qa.p11.tpl.clock", { ms: formatNumber(Math.abs(time.data.skew_ms)), limit: formatNumber(2000) })}
              </p>
            ) : null}
          </div>
        </section>
      </div>
      <section className="card">
        <div className="card-header">
          <h2>{t("qa.p11.head.related")}</h2>
        </div>
        <div className="card-body row wrap" style={{ gap: 8 }}>
          <Link className="btn" to={mfgPaths.esigPolicies()}>
            <Icon name="shield" /> {t("qa.p11.btn.policies")}
          </Link>
          <Link className="btn" to={mfgPaths.part11Exports()}>
            <Icon name="download" /> {t("qa.p11.btn.exports")}
          </Link>
          <Link className="btn" to={mfgPaths.audit()}>
            <Icon name="list" /> {t("qa.p11.btn.audit")}
          </Link>
          <Link className="btn" to={mfgPaths.members()}>
            <Icon name="users" /> {t("qa.p11.btn.members")}
          </Link>
        </div>
      </section>
      {confirm ? (
        <Dialog
          title={t("qa.p11.title.confirm")}
          onClose={() => setConfirm(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setConfirm(false)} data-dialog-close>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={() => {
                  setConfirm(false);
                  setSigning(true);
                }}
                data-testid="part11-continue"
              >
                {t("qa.p11.btn.continueSign")}
              </button>
            </>
          }
        >
          <Banner tone="warn" title={t("qa.p11.title.irreversible")}>
            {t("qa.p11.text.irreversible")}
          </Banner>
        </Dialog>
      ) : null}
      {signing && m ? (
        <SignatureDialog
          title={t("qa.p11.str.signTitle")}
          recordType="plant"
          recordId="plant"
          action="part11_on"
          meaning="approved"
          submitLabel={t("qa.p11.btn.signEnable")}
          plainLabel={t("qa.p11.btn.enable")}
          effect={t("qa.p11.text.effect")}
          perform={(sig, comment) => enablePart11(sig ? { ...sig, comment: comment || sig.comment } : null)}
          onDone={(res) => {
            if (res.status === 200) setPart11Mode(res.record);
            else p11.refresh();
            toast(signedToast(res, t("qa.p11.toast.on")));
            setSigning(false);
          }}
          onClose={() => setSigning(false)}
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- E8-E10 export
const EXPORT_TYPES = ["inspection_plan", "sampling_scheme", "inspection_lot", "hold", "ncr", "capa", "complaint", "field_action", "equipment", "calibration", "eco", "esig_policy"];

export function Part11ExportsPage() {
  const canView = useCan("audit_view");
  const today = new Date().toISOString().slice(0, 10);
  const yearAgo = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);
  const [from, setFrom] = useState(yearAgo);
  const [to, setTo] = useState(today);
  const [types, setTypes] = useState<string[]>(EXPORT_TYPES);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const data = useLoad((s) => (canView ? listPart11Exports(s) : null), [canView]);
  const running = (data.data?.items ?? []).some((x) => x.status === "queued" || x.status === "running");
  usePolling(() => data.reload(), running, 3000);
  useEffect(() => {
    document.title = t("qa.exp.str.docTitle");
  }, []);
  const cols = useMemo<Column<Part11Export>[]>(
    () => [
      { key: "when", header: t("qa.exp.head.requested"), width: "170px", sortValue: (x) => x.created_at, render: (x) => formatDateTime(x.created_at) },
      { key: "range", header: t("qa.exp.head.range"), width: "minmax(160px, 1fr)", render: (x) => formatDateRange(x.params.from ?? null, x.params.to ?? null) },
      { key: "types", header: t("qa.exp.head.types"), width: "minmax(200px, 2fr)", wrap: true, render: (x) => (x.params.record_types?.length ? x.params.record_types.map(recordTypeText).join(", ") : t("qa.exp.str.allTypes")) },
      {
        key: "status",
        header: t("qa.exp.head.status"),
        width: "130px",
        render: (x) =>
          x.status === "completed" ? (
            <span className="badge ok">
              <Icon name="check" /> {t("qa.exp.str.ready")}
            </span>
          ) : x.status === "failed" ? (
            <span className="badge danger" title={x.error ?? undefined}>
              <Icon name="x" /> {t("qa.exp.str.failed")}
            </span>
          ) : (
            <span className="badge accent">
              <Icon name="loader" /> {t("qa.exp.str.running")}
            </span>
          ),
      },
      { key: "sha", header: t("qa.exp.head.sha"), width: "minmax(150px, 1fr)", exportValue: (x) => x.sha256 ?? "", render: (x) => (x.sha256 ? <span className="mono small faint" title={x.sha256}>{x.sha256.slice(0, 16)}…</span> : "") },
      {
        key: "dl",
        header: "",
        label: t("qa.exp.head.download"),
        width: "120px",
        hideable: false,
        render: (x) =>
          x.status === "completed" ? (
            <button type="button" className="btn sm" onClick={async () => saveBlob(await downloadPart11Export(x.id))}>
              <Icon name="download" /> {t("qa.exp.btn.download")}
            </button>
          ) : null,
      },
    ],
    [],
  );
  return (
    <div className="col gap-lg" data-testid="part11-exports">
      <PageHeader title={t("qa.exp.title")} description={t("qa.exp.desc")} />
      {!canView ? (
        <Banner tone="warn" icon="lock" title={t("qa.history.title.noAccess")}>
          {needsText("audit_view")}
        </Banner>
      ) : (
        <>
          <section className="card">
            <div className="card-header">
              <h2>{t("qa.exp.head.new")}</h2>
            </div>
            <div className="card-body col">
              <div className="qa-form-grid">
                <div className="field">
                  <label htmlFor="exp-from">{t("qa.exp.label.from")}</label>
                  <DateInput id="exp-from" value={from} onChange={setFrom} max={to} />
                </div>
                <div className="field">
                  <label htmlFor="exp-to">{t("qa.exp.label.to")}</label>
                  <DateInput id="exp-to" value={to} onChange={setTo} min={from} />
                </div>
              </div>
              <fieldset className="mfg-fieldset">
                <legend>{t("qa.exp.label.types")}</legend>
                <div className="qa-role-checks">
                  {EXPORT_TYPES.map((x) => (
                    <label key={x} className="checkbox">
                      <input type="checkbox" checked={types.includes(x)} onChange={(e) => setTypes(e.target.checked ? [...types, x] : types.filter((y) => y !== x))} />
                      {recordTypeText(x)}
                    </label>
                  ))}
                </div>
              </fieldset>
              <MfgError error={error} />
              <div>
                <button
                  type="button"
                  className="btn primary"
                  disabled={busy || !types.length || !from || !to}
                  onClick={async () => {
                    setBusy(true);
                    setError(null);
                    try {
                      await createPart11Export({ from, to, record_types: types });
                      toast(t("qa.exp.toast.started"));
                      data.reload();
                    } catch (e) {
                      setError(e);
                    } finally {
                      setBusy(false);
                    }
                  }}
                  data-testid="part11-export-start"
                >
                  <Icon name="download" /> {t("qa.exp.btn.start")}
                </button>
              </div>
              <p className="small muted" style={{ margin: 0 }}>
                {t("qa.exp.text.contents")}
              </p>
            </div>
          </section>
          <MfgError error={data.error} onRetry={data.reload} />
          <section className="card card-table">
            <div className="card-header">
              <h2>{t("qa.exp.head.list")}</h2>
            </div>
            <DataTable rows={data.data?.items ?? []} columns={cols} rowKey={(x) => x.id} label={t("qa.exp.head.list")} tableId="part11-exports" loading={data.loading && !data.data} empty={t("qa.exp.empty")} />
          </section>
        </>
      )}
    </div>
  );
}
