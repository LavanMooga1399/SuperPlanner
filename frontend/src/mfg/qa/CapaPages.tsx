/**
 * CAPA and complaints (M7 7, 10). CAPA: draft -> investigation -> plan approval (signed, needs a root cause and at
 * least one action) -> implementation -> effectiveness check (all actions done) -> verified (signed; not effective
 * returns to investigation) -> closed (signed). Complaints: open -> investigation -> closed (signed), with
 * reportability decision support (report due dates per regime) and follow-up actions (trace, NCR, CAPA, recall).
 * When the plant keeps these records in an external quality system, the records are link stubs.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Banner } from "../../components/Banner";
import { DateInput } from "../../components/DateInput";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { UnsavedChangesGuard } from "../../components/UnsavedChangesGuard";
import { addCapaAction, advanceCapa, advanceComplaint, createCapa, createComplaint, createLink, deleteCapaAction, getCapa, getComplaint, listCapas, listComplaints, recordAction, updateCapa, updateCapaAction, updateComplaint } from "../api/clientM7";
import type { ItemRef } from "../api/types";
import type { Capa, CapaAction, CapaActionInput, CapaInput, Channel, Complaint, ComplaintInput, EventType, RootCause } from "../api/typesM7";
import { ConflictBanner, MfgError, Spinner } from "../components/Feedback";
import { FormErrors, TextField } from "../components/Field";
import { ItemPicker } from "../components/ItemPicker";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { useAccess, useCan } from "../lib/permissions";
import { isConflict, useLoad } from "../lib/useMfg";
import { fmtDate } from "../lib/format";
import { t, type StringKey } from "../../lib/i18n";
import { DueCell, usePersonName } from "./common";
import { CAPA_STATUS, CapaStatusChip, COMPLAINT_STATUS, ComplaintStatusChip, labelOf } from "./labels";
import { AttachmentsTab, HistoryTab, LinksTab, NextStepBanner, RecordHeader, RecordTabs, Section, SignaturesTab, standardTabs, TabPanel, useChangeReason } from "./RecordShell";
import { QaWorklist } from "./Worklist";
import "./qa.css";

const today = () => new Date().toISOString().slice(0, 10);
const riskLevel = (s: number, o: number): "low" | "medium" | "high" => (s * o >= 15 ? "high" : s * o >= 6 ? "medium" : "low");
const RISK_KEY: Record<string, StringKey> = { low: "qa.capa.risk.low", medium: "qa.capa.risk.medium", high: "qa.capa.risk.high" };
const METHOD_KEY: Record<RootCause["method"], StringKey> = { "5_why": "qa.capa.method.5why", fishbone: "qa.capa.method.fishbone", fault_tree: "qa.capa.method.faultTree", "8d": "qa.capa.method.8d", other: "qa.capa.method.other" };
const ACTION_KIND_KEY: Record<string, StringKey> = { correction: "qa.capa.kind.correction", corrective: "qa.capa.kind.corrective", preventive: "qa.capa.kind.preventive" };
const ACTION_STATUS_KEY: Record<string, StringKey> = { open: "qa.capa.astatus.open", done: "qa.capa.astatus.done", cancelled: "qa.capa.astatus.cancelled" };

/** Owner choice: members (owners see the list) or the current person. */
function OwnerSelect({ id, value, onChange, disabled }: { id: string; value: string | null; onChange(v: string | null): void; disabled?: boolean }) {
  const access = useAccess();
  const person = usePersonName();
  const me = access.me?.user_id ?? "";
  const opts = [...new Set([me, value ?? ""].filter(Boolean))];
  return (
    <select id={id} className="select" value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{t("qa.capa.str.noOwner")}</option>
      {opts.map((o) => (
        <option key={o} value={o}>
          {person(o)}
        </option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------- CAPA list
export function CapasPage() {
  const canEdit = useCan("capa_edit");
  const person = usePersonName();
  useEffect(() => {
    document.title = t("qa.capa.str.docTitle");
  }, []);
  const columns = useMemo<Column<Capa>[]>(
    () => [
      {
        key: "number",
        header: t("qa.capa.head.capa"),
        width: "130px",
        sortKey: "number",
        sortKeyDesc: "-number",
        exportValue: (c) => c.number,
        render: (c) => (
          <Link to={mfgPaths.qaCapa(c.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {c.number}
          </Link>
        ),
      },
      { key: "status", header: t("qa.ncr.head.status"), width: "170px", exportValue: (c) => labelOf(CAPA_STATUS, c.status), render: (c) => <CapaStatusChip s={c.status} /> },
      { key: "title", header: t("qa.ncr.head.title"), width: "minmax(220px, 2fr)", render: (c) => <span className="mfg-ellipsis">{c.title}</span> },
      { key: "kind", header: t("qa.capa.head.kind"), width: "120px", render: (c) => t(ACTION_KIND_KEY[c.kind]) },
      { key: "risk", header: t("qa.capa.head.risk"), width: "100px", drop: 2, render: (c) => (c.risk ? t(RISK_KEY[c.risk.level ?? riskLevel(c.risk.severity, c.risk.occurrence)]) : "") },
      { key: "owner", header: t("qa.capa.head.owner"), width: "minmax(130px, 1fr)", drop: 1, render: (c) => <span className="mfg-ellipsis">{person(c.owner_user_id)}</span> },
      { key: "actions", header: t("qa.capa.head.actions"), width: "100px", align: "right", drop: 3, render: (c) => t("qa.capa.tpl.actionsDone", { d: c.actions.filter((a) => a.status !== "open").length, n: c.actions.length }) },
      { key: "due", header: t("qa.lots.head.due"), width: "170px", sortKey: "due_on", render: (c) => <DueCell at={c.due_on} overdue={c.overdue} /> },
    ],
    [person],
  );
  return (
    <QaWorklist<Capa>
      title={t("qa.capa.title")}
      description={t("qa.capa.desc")}
      actions={
        canEdit ? (
          <Link className="btn primary" to={mfgPaths.qaCapa("new")} data-testid="capa-new">
            <Icon name="plus" /> {t("qa.capa.btn.new")}
          </Link>
        ) : null
      }
      pageKey="qa-capas"
      testId="qa-capas-page"
      searchPlaceholder={t("qa.capa.ph.search")}
      views={[
        { key: "overdue", label: t("qa.lots.view.overdue"), query: { overdue: "true" } },
        { key: "approval", label: t("qa.capa.view.approval"), query: { status: "plan_approval,effectiveness_check,implementation" } },
      ]}
      statusOptions={[{ value: "", label: t("qa.ncr.status.active") }, ...Object.keys(CAPA_STATUS).map((s) => ({ value: s, label: labelOf(CAPA_STATUS, s) })), { value: "all", label: t("qa.list.status.all") }]}
      defaultStatus="draft,investigation,plan_approval,implementation,effectiveness_check"
      fetch={(q, signal) => listCapas({ ...q, status: q.status === "all" ? undefined : q.status }, signal)}
      columns={columns}
      card={{ title: "number", status: "status", fields: ["title", "owner", "due"] }}
      rowKey={(c) => c.id}
      rowExtras={(c) => ({ testId: "capa-row", data: { status: c.status } })}
      rowPath={(c) => mfgPaths.qaCapa(c.id)}
      empty={t("qa.capa.empty")}
      noun={t("qa.capa.str.noun")}
    />
  );
}

// ---------------------------------------------------------------- CAPA record
const blankCapa = (): CapaInput => ({ title: "", kind: "corrective", problem: "", risk: { severity: 3, occurrence: 3 }, owner_user_id: null, due_on: null, root_cause: null, effectiveness: { criteria: "", check_due_on: null, result: null, evidence: "" }, external_ref: null });
const capaInput = (c: Capa): CapaInput => ({ title: c.title, kind: c.kind, problem: c.problem, risk: c.risk, owner_user_id: c.owner_user_id, due_on: c.due_on, root_cause: c.root_cause, effectiveness: c.effectiveness, external_ref: c.external_ref });
type CapaSign = null | "approve-plan" | "verify" | "close" | "cancel";

export function CapaPage() {
  const { capaId = "" } = useParams();
  const isNew = capaId === "new";
  const navigate = useNavigate();
  const canEdit = useCan("capa_edit");
  const canApprove = useCan("capa_approve");
  const person = usePersonName();
  const reason = useChangeReason();
  const rec = useLoad((s) => (isNew ? null : getCapa(capaId, s)), [capaId]);
  const c = rec.data;
  const [form, setForm] = useState<CapaInput>(blankCapa());
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("details");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sign, setSign] = useState<CapaSign>(null);
  const [verifyResult, setVerifyResult] = useState<"effective" | "not_effective">("effective");
  const [evidence, setEvidence] = useState("");
  const [editAction, setEditAction] = useState<CapaAction | "new" | null>(null);
  useEffect(() => {
    if (c) {
      setForm(capaInput(c));
      setDirty(false);
      document.title = `${c.number} - ${t("qa.capa.title")}`;
    } else if (isNew) document.title = t("qa.capa.str.newDocTitle");
  }, [c, isNew]);
  if (!isNew && rec.loading && !c) return <Spinner />;
  if (!isNew && !c) return <MfgError error={rec.error} onRetry={rec.reload} />;
  const editable = canEdit && (isNew || ["draft", "investigation", "plan_approval"].includes(c!.status));
  const set = (p: Partial<CapaInput>) => {
    setForm((f) => ({ ...f, ...p }));
    setDirty(true);
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        const x = await createCapa(form);
        toast(t("qa.capa.toast.created", { n: x.number }));
        setDirty(false);
        navigate(mfgPaths.qaCapa(x.id), { replace: true });
      } else if (c) {
        const r = await reason.ask(c.number);
        if (r === null) return;
        rec.setData(await updateCapa(c.id, form, c.row_version, r));
        setDirty(false);
        toast(t("qa.capa.toast.saved"));
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const advance = async (to: "investigation" | "plan_approval" | "effectiveness_check") => {
    if (!c) return;
    setBusy(true);
    setError(null);
    try {
      rec.setData(await advanceCapa(c.id, to, c.row_version));
      toast(t("qa.capa.toast.advanced", { s: labelOf(CAPA_STATUS, to) }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const risk = form.risk ?? { severity: 3, occurrence: 3 };
  const formView = (
    <FormErrors error={error}>
      <Section title={t("qa.capa.head.problem")}>
        <div className="qa-form-grid">
          <div className="span-2">
            <TextField label={t("qa.ncr.head.title")} name="title" value={form.title} onChange={(v) => set({ title: v })} disabled={!editable} required testId="capa-title" />
          </div>
          <div className="field">
            <label htmlFor="capa-kind">{t("qa.capa.head.kind")}</label>
            <select id="capa-kind" className="select" value={form.kind} disabled={!editable} onChange={(e) => set({ kind: e.target.value as "corrective" })}>
              <option value="corrective">{t("qa.capa.kind.corrective")}</option>
              <option value="preventive">{t("qa.capa.kind.preventive")}</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="capa-owner">{t("qa.capa.head.owner")}</label>
            <OwnerSelect id="capa-owner" value={form.owner_user_id} onChange={(v) => set({ owner_user_id: v })} disabled={!editable} />
          </div>
          <div className="field">
            <label htmlFor="capa-due">{t("qa.lots.head.due")}</label>
            <DateInput id="capa-due" value={form.due_on ?? ""} onChange={(v) => set({ due_on: v || null })} disabled={!editable} />
          </div>
          <div className="field">
            <label htmlFor="capa-sev">{t("qa.capa.label.severity")}</label>
            <select id="capa-sev" className="select" value={risk.severity} disabled={!editable} onChange={(e) => set({ risk: { ...risk, severity: Number(e.target.value), level: riskLevel(Number(e.target.value), risk.occurrence) } })}>
              {[1, 2, 3, 4, 5].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="capa-occ">{t("qa.capa.label.occurrence")}</label>
            <select id="capa-occ" className="select" value={risk.occurrence} disabled={!editable} onChange={(e) => set({ risk: { ...risk, occurrence: Number(e.target.value), level: riskLevel(risk.severity, Number(e.target.value)) } })}>
              {[1, 2, 3, 4, 5].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <span className="field-label">{t("qa.capa.head.risk")}</span>
            <span style={{ lineHeight: "28px" }}>
              <strong>{t(RISK_KEY[riskLevel(risk.severity, risk.occurrence)])}</strong> <span className="muted small">{t("qa.capa.tpl.riskScore", { s: risk.severity * risk.occurrence })}</span>
            </span>
          </div>
          <div className="field span-all">
            <label htmlFor="capa-problem">{t("qa.capa.label.problem")}</label>
            <textarea id="capa-problem" className="textarea" rows={3} value={form.problem} disabled={!editable} onChange={(e) => set({ problem: e.target.value })} />
          </div>
        </div>
      </Section>
      {!isNew ? (
        <Section title={t("qa.capa.head.rootCause")}>
          <div className="qa-form-grid">
            <div className="field">
              <label htmlFor="capa-method">{t("qa.capa.label.method")}</label>
              <select id="capa-method" className="select" value={form.root_cause?.method ?? ""} disabled={!editable} onChange={(e) => set({ root_cause: e.target.value ? { method: e.target.value as RootCause["method"], text: form.root_cause?.text ?? "" } : null })}>
                <option value="">{t("qa.capa.str.notYet")}</option>
                {(Object.keys(METHOD_KEY) as RootCause["method"][]).map((m) => (
                  <option key={m} value={m}>
                    {t(METHOD_KEY[m])}
                  </option>
                ))}
              </select>
            </div>
            <div className="field span-all">
              <label htmlFor="capa-rc">{t("qa.capa.label.rootCause")}</label>
              <textarea id="capa-rc" className="textarea" rows={3} value={form.root_cause?.text ?? ""} disabled={!editable || !form.root_cause} onChange={(e) => set({ root_cause: { method: form.root_cause?.method ?? "other", text: e.target.value } })} />
            </div>
          </div>
        </Section>
      ) : null}
      {!isNew ? (
        <Section title={t("qa.capa.head.effectiveness")}>
          <div className="qa-form-grid">
            <div className="field span-2">
              <label htmlFor="capa-crit">{t("qa.capa.label.criteria")}</label>
              <input id="capa-crit" className="input" value={form.effectiveness?.criteria ?? ""} disabled={!editable} onChange={(e) => set({ effectiveness: { criteria: e.target.value, check_due_on: form.effectiveness?.check_due_on ?? null, result: form.effectiveness?.result ?? null, evidence: form.effectiveness?.evidence ?? "" } })} />
            </div>
            <div className="field">
              <label htmlFor="capa-check">{t("qa.capa.label.checkDue")}</label>
              <DateInput id="capa-check" value={form.effectiveness?.check_due_on ?? ""} disabled={!editable} onChange={(v) => set({ effectiveness: { criteria: form.effectiveness?.criteria ?? "", check_due_on: v || null, result: form.effectiveness?.result ?? null, evidence: form.effectiveness?.evidence ?? "" } })} />
            </div>
            {c?.effectiveness?.result ? (
              <div className="field">
                <span className="field-label">{t("qa.capa.label.result")}</span>
                <span style={{ lineHeight: "28px" }}>{c.effectiveness.result === "effective" ? t("qa.capa.str.effective") : t("qa.capa.str.notEffective")}</span>
              </div>
            ) : null}
          </div>
        </Section>
      ) : null}
    </FormErrors>
  );
  if (isNew)
    return (
      <div className="col gap-lg" data-testid="capa-new-page">
        <UnsavedChangesGuard when={dirty} what={t("qa.capa.str.thisCapa")} />
        <PageHeader
          title={t("qa.capa.str.newTitle")}
          description={t("qa.capa.str.newDesc")}
          actions={
            <button type="button" className="btn primary" disabled={busy || !form.title.trim()} onClick={() => void save()} data-testid="capa-save">
              <Icon name="save" /> {t("qa.ncr.btn.create")}
            </button>
          }
        />
        <MfgError error={error} />
        {formView}
      </div>
    );
  const x = c!;
  const external = x.sor === "external";
  const allDone = x.actions.length > 0 && x.actions.every((a) => a.status !== "open");
  const next: Record<string, { label: StringKey; run(): void; ok: boolean; testId: string } | undefined> = {
    draft: canEdit ? { label: "qa.capa.btn.investigate", run: () => void advance("investigation"), ok: true, testId: "capa-advance" } : undefined,
    investigation: canEdit ? { label: "qa.capa.btn.toApproval", run: () => void advance("plan_approval"), ok: Boolean(x.root_cause?.text) && x.actions.length > 0, testId: "capa-advance" } : undefined,
    plan_approval: canApprove ? { label: "qa.capa.btn.approvePlan", run: () => setSign("approve-plan"), ok: true, testId: "capa-approve-plan" } : undefined,
    implementation: canEdit ? { label: "qa.capa.btn.toCheck", run: () => void advance("effectiveness_check"), ok: allDone, testId: "capa-advance" } : undefined,
    effectiveness_check: canApprove ? { label: "qa.capa.btn.verify", run: () => setSign("verify"), ok: true, testId: "capa-verify" } : undefined,
  };
  const closable = canApprove && x.status === "effectiveness_check" && x.effectiveness?.result === "effective";
  const n = external ? undefined : next[x.status];
  const guide: Partial<Record<string, StringKey>> = {
    draft: "qa.capa.guide.draft",
    investigation: "qa.capa.guide.investigation",
    plan_approval: "qa.capa.guide.planApproval",
    implementation: "qa.capa.guide.implementation",
    effectiveness_check: "qa.capa.guide.check",
  };
  const actionCols: Column<CapaAction>[] = [
    { key: "seq", header: "#", width: "48px", render: (a) => a.seq },
    { key: "kind", header: t("qa.capa.head.kind"), width: "130px", render: (a) => t(ACTION_KIND_KEY[a.kind]) },
    { key: "desc", header: t("qa.capa.head.action"), width: "minmax(240px, 3fr)", wrap: true, render: (a) => a.description },
    { key: "owner", header: t("qa.capa.head.owner"), width: "minmax(120px, 1fr)", render: (a) => person(a.owner_user_id) },
    { key: "due", header: t("qa.lots.head.due"), width: "120px", render: (a) => fmtDate(a.due_on) },
    { key: "status", header: t("qa.ncr.head.status"), width: "130px", render: (a) => <span className={`badge ${a.status === "done" ? "ok" : a.status === "open" ? "info" : "info"}`}><Icon name={a.status === "done" ? "check" : a.status === "open" ? "circle" : "ban"} /> {t(ACTION_STATUS_KEY[a.status])}</span> },
    { key: "eco", header: t("qa.capa.head.eco"), width: "100px", render: (a) => (a.eco_id ? <Link to={mfgPaths.eco(a.eco_id)}>{t("qa.capa.str.eco")}</Link> : "") },
    {
      key: "edit",
      header: "",
      label: t("qa.pol.head.edit"),
      width: "84px",
      hideable: false,
      render: (a) =>
        canEdit && !["closed", "cancelled"].includes(x.status) ? (
          <button type="button" className="btn sm" onClick={() => setEditAction(a)}>
            {t("qa.pol.btn.edit")}
          </button>
        ) : null,
    },
  ];
  return (
    <div className="col gap-lg" data-testid="capa-page" data-status={x.status}>
      <UnsavedChangesGuard when={dirty} what={t("qa.capa.str.thisCapa")} />
      <RecordHeader
        crumbs={[[t("nav.mfg.section.qa-capas"), mfgPaths.qaCapas()]]}
        number={x.number}
        title={x.title}
        status={<CapaStatusChip s={x.status} />}
        chips={x.overdue ? <span className="badge danger"><Icon name="clock" /> {t("qa.common.str.overdue")}</span> : null}
        facts={[
          [t("qa.capa.head.kind"), t(ACTION_KIND_KEY[x.kind])],
          [t("qa.capa.head.owner"), person(x.owner_user_id)],
          [t("qa.lots.head.due"), fmtDate(x.due_on)],
          [t("qa.capa.head.risk"), x.risk ? t(RISK_KEY[x.risk.level ?? riskLevel(x.risk.severity, x.risk.occurrence)]) : null],
          [t("qa.capa.head.actions"), t("qa.capa.tpl.actionsDone", { d: x.actions.filter((a) => a.status !== "open").length, n: x.actions.length })],
          [t("qa.ncr.label.author"), person(x.author_id)],
        ]}
        actions={
          <>
            {!["closed", "cancelled"].includes(x.status) && canEdit ? (
              <button type="button" className="btn ghost" onClick={() => setSign("cancel")}>
                {t("qa.capa.btn.cancel")}
              </button>
            ) : null}
            <Link className="btn ghost" to={mfgPaths.printQa("capa", x.id)} target="_blank" rel="noopener">
              <Icon name="file" /> {t("qa.common.btn.print")}
            </Link>
            {editable ? (
              <button type="button" className="btn" disabled={busy || !dirty} onClick={() => void save()} data-testid="capa-save">
                <Icon name="save" /> {t("qa.plans.btn.save")}
              </button>
            ) : null}
            {closable ? (
              <button type="button" className="btn primary" onClick={() => setSign("close")} data-testid="capa-close">
                <Icon name="lock" /> {t("qa.capa.btn.close")}
              </button>
            ) : n ? (
              <button type="button" className="btn primary" disabled={busy || dirty || !n.ok} onClick={n.run} data-testid={n.testId} title={!n.ok ? t(x.status === "investigation" ? "qa.capa.attr.needPlan" : "qa.capa.attr.needDone") : undefined}>
                <Icon name="arrow-right" /> {t(n.label)}
              </button>
            ) : null}
          </>
        }
      />
      {external ? (
        <Banner tone="info" icon="external" title={t("qa.capa.title.external")}>
          {t("qa.capa.text.external", { ref: x.external_ref ?? "—" })}
        </Banner>
      ) : guide[x.status] ? (
        <NextStepBanner text={t(guide[x.status]!)} />
      ) : null}
      {isConflict(error) ? <ConflictBanner onReload={() => (setError(null), rec.reload())} /> : <MfgError error={error} />}
      <RecordTabs label={t("qa.capa.aria.tabs")} value={tab} onChange={setTab} tabs={[{ key: "details", label: t("qa.shell.tab.details") }, { key: "actions", label: t("qa.capa.head.actions"), count: x.actions.length }, ...standardTabs(x)]} />
      {tab === "details" ? <TabPanel id="details">{formView}</TabPanel> : null}
      {tab === "actions" ? (
        <TabPanel id="actions">
          <Section
            title={t("qa.capa.head.actions")}
            flush
            testId="capa-actions"
            actions={
              canEdit && !["closed", "cancelled", "effectiveness_check"].includes(x.status) ? (
                <button type="button" className="btn sm" onClick={() => setEditAction("new")} data-testid="capa-action-add">
                  <Icon name="plus" /> {t("qa.capa.btn.addAction")}
                </button>
              ) : null
            }
          >
            <DataTable rows={x.actions} columns={actionCols} rowKey={(a) => a.id} label={t("qa.capa.head.actions")} tableId="capa-actions" empty={t("qa.capa.empty.actions")} rowExtras={(a) => ({ testId: "capa-action-row", data: { status: a.status } })} />
          </Section>
        </TabPanel>
      ) : null}
      {tab === "links" ? (
        <TabPanel id="links">
          <LinksTab links={x.links} fromType="capa" fromId={x.id} canEdit={canEdit} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {tab === "attachments" ? (
        <TabPanel id="attachments">
          <AttachmentsTab attachments={x.attachments} entityType="capa" entityId={x.id} canEdit={canEdit} locked={["closed", "cancelled"].includes(x.status)} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {tab === "history" ? (
        <TabPanel id="history">
          <HistoryTab entityType="capa" entityId={x.id} />
        </TabPanel>
      ) : null}
      {tab === "signatures" ? (
        <TabPanel id="signatures">
          <SignaturesTab signatures={x.signatures} recordType="capa" recordId={x.id} />
        </TabPanel>
      ) : null}
      {reason.dialog}
      {editAction ? <ActionDialog capa={x} action={editAction === "new" ? null : editAction} onClose={() => setEditAction(null)} onSaved={(r) => (setEditAction(null), r ? rec.setData(r) : rec.reload())} /> : null}
      {sign ? (
        <SignatureDialog<Capa>
          title={t(sign === "approve-plan" ? "qa.capa.tpl.approveTitle" : sign === "verify" ? "qa.capa.tpl.verifyTitle" : sign === "close" ? "qa.capa.tpl.closeTitle" : "qa.capa.tpl.cancelTitle", { n: x.number })}
          recordType="capa"
          recordId={x.id}
          recordLabel={x.number}
          action={sign === "approve-plan" ? "approve_plan" : sign}
          meaning={sign === "approve-plan" ? "approved" : sign === "verify" ? "verified" : "closed"}
          danger={sign === "cancel"}
          commentRequired={sign === "cancel"}
          commentLabel={sign === "cancel" ? t("qa.lots.label.cancelReason") : undefined}
          submitLabel={t(sign === "approve-plan" ? "qa.capa.btn.signApprove" : sign === "verify" ? "qa.capa.btn.signVerify" : sign === "close" ? "qa.ncr.btn.signClose" : "qa.lots.btn.signCancel")}
          plainLabel={t(sign === "approve-plan" ? "qa.capa.btn.approvePlan" : sign === "verify" ? "qa.capa.btn.verify" : sign === "close" ? "qa.capa.btn.close" : "qa.capa.btn.cancel")}
          effect={sign === "verify" ? t("qa.capa.text.verifyEffect") : sign === "approve-plan" ? t("qa.capa.text.approveEffect") : undefined}
          canSubmit={sign !== "verify" || Boolean(evidence.trim())}
          perform={(sig, comment) =>
            recordAction<Capa>("capa", x.id, sign, sign === "verify" ? { result: verifyResult, evidence: evidence.trim() } : sign === "cancel" ? { reason: comment } : { note: comment }, { version: x.row_version, signature: sig })
          }
          onDone={(res) => {
            toast(signedToast(res, t("qa.capa.toast.signed")));
            setSign(null);
            rec.reload();
          }}
          onClose={() => setSign(null)}
        >
          {sign === "verify" ? (
            <div className="col" style={{ gap: 8 }}>
              <fieldset className="esig-meanings">
                <legend>{t("qa.capa.label.result")}</legend>
                <label className="checkbox">
                  <input type="radio" name="capa-res" checked={verifyResult === "effective"} onChange={() => setVerifyResult("effective")} /> {t("qa.capa.str.effective")}
                </label>
                <label className="checkbox">
                  <input type="radio" name="capa-res" checked={verifyResult === "not_effective"} onChange={() => setVerifyResult("not_effective")} /> {t("qa.capa.str.notEffective")}
                </label>
              </fieldset>
              <div className="field">
                <label htmlFor="capa-ev">{t("qa.capa.label.evidence")}</label>
                <textarea id="capa-ev" className="textarea" rows={2} value={evidence} onChange={(e) => setEvidence(e.target.value)} maxLength={2000} />
              </div>
            </div>
          ) : null}
        </SignatureDialog>
      ) : null}
    </div>
  );
}

function ActionDialog({ capa, action, onClose, onSaved }: { capa: Capa; action: CapaAction | null; onClose(): void; onSaved(c: Capa | null): void }) {
  const [f, setF] = useState<CapaActionInput>(action ? { kind: action.kind, description: action.description, owner_user_id: action.owner_user_id, due_on: action.due_on, status: action.status, evidence: action.evidence, eco_id: action.eco_id } : { kind: "corrective", description: "", owner_user_id: null, due_on: null, status: "open", evidence: "", eco_id: null });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = async (fn: () => Promise<Capa | void>) => {
    setBusy(true);
    setError(null);
    try {
      const r = await fn();
      toast(t("qa.capa.toast.actionSaved"));
      onSaved(r ?? null);
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={action ? t("qa.capa.tpl.editAction", { n: action.seq }) : t("qa.capa.btn.addAction")}
      onClose={onClose}
      wide
      footer={
        <>
          {action ? (
            <button type="button" className="btn ghost" style={{ marginRight: "auto" }} disabled={busy} onClick={() => void run(() => deleteCapaAction(capa.id, action.id, action.row_version))}>
              <Icon name="trash" /> {t("qa.plans.btn.delete")}
            </button>
          ) : null}
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={busy || !f.description.trim() || (f.status === "done" && !f.evidence.trim())} onClick={() => void run(() => (action ? updateCapaAction(capa.id, action.id, f, action.row_version) : addCapaAction(capa.id, f)))} data-testid="capa-action-save">
            {t("qa.plans.btn.save")}
          </button>
        </>
      }
    >
      <FormErrors error={error}>
        <div className="qa-form-grid">
          <div className="field">
            <label htmlFor="ca-kind">{t("qa.capa.head.kind")}</label>
            <select id="ca-kind" className="select" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as CapaActionInput["kind"] })}>
              {Object.keys(ACTION_KIND_KEY).map((k) => (
                <option key={k} value={k}>
                  {t(ACTION_KIND_KEY[k])}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ca-owner">{t("qa.capa.head.owner")}</label>
            <OwnerSelect id="ca-owner" value={f.owner_user_id} onChange={(v) => setF({ ...f, owner_user_id: v })} />
          </div>
          <div className="field">
            <label htmlFor="ca-due">{t("qa.lots.head.due")}</label>
            <DateInput id="ca-due" value={f.due_on ?? ""} onChange={(v) => setF({ ...f, due_on: v || null })} />
          </div>
          <div className="field">
            <label htmlFor="ca-status">{t("qa.ncr.head.status")}</label>
            <select id="ca-status" className="select" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as CapaActionInput["status"] })}>
              {Object.keys(ACTION_STATUS_KEY).map((k) => (
                <option key={k} value={k}>
                  {t(ACTION_STATUS_KEY[k])}
                </option>
              ))}
            </select>
          </div>
          <div className="field span-all">
            <label htmlFor="ca-desc">{t("qa.capa.head.action")}</label>
            <textarea id="ca-desc" className="textarea" rows={2} maxLength={2000} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} data-testid="capa-action-desc" />
          </div>
          <div className="field span-all">
            <label htmlFor="ca-ev">{t("qa.capa.label.evidence")}</label>
            <textarea id="ca-ev" className="textarea" rows={2} maxLength={2000} value={f.evidence} onChange={(e) => setF({ ...f, evidence: e.target.value })} />
            <span className="hint">{t("qa.capa.hint.evidence")}</span>
          </div>
        </div>
        <MfgError error={error} />
      </FormErrors>
    </Dialog>
  );
}

// ---------------------------------------------------------------- complaints
const EVENT_KEY: Record<EventType, StringKey> = { death: "qa.event.death", serious_injury: "qa.event.serious_injury", malfunction: "qa.event.malfunction", other: "qa.event.other" };
const CHANNEL_KEY: Record<Channel, StringKey> = { phone: "qa.cmp.ch.phone", email: "qa.cmp.ch.email", web: "qa.cmp.ch.web", field: "qa.cmp.ch.field", distributor: "qa.cmp.ch.distributor", other: "qa.cmp.ch.other" };

export function ComplaintsPage() {
  const canEdit = useCan("complaint_edit");
  useEffect(() => {
    document.title = t("qa.cmp.str.docTitle");
  }, []);
  const columns = useMemo<Column<Complaint>[]>(
    () => [
      {
        key: "number",
        header: t("qa.cmp.head.complaint"),
        width: "130px",
        sortKey: "number",
        sortKeyDesc: "-number",
        exportValue: (c) => c.number,
        render: (c) => (
          <Link to={mfgPaths.qaComplaint(c.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {c.number}
          </Link>
        ),
      },
      { key: "status", header: t("qa.ncr.head.status"), width: "140px", exportValue: (c) => labelOf(COMPLAINT_STATUS, c.status), render: (c) => <ComplaintStatusChip s={c.status} /> },
      { key: "customer", header: t("qa.cmp.head.customer"), width: "minmax(160px, 1.2fr)", render: (c) => <span className="mfg-ellipsis">{c.customer}</span> },
      { key: "desc", header: t("qa.ncr.label.description"), width: "minmax(220px, 2fr)", render: (c) => <span className="mfg-ellipsis">{c.description}</span> },
      { key: "event", header: t("qa.settings.head.eventType"), width: "140px", exportValue: (c) => t(EVENT_KEY[c.event_type]), render: (c) => <span className={c.event_type === "death" || c.event_type === "serious_injury" ? "badge danger" : undefined}>{t(EVENT_KEY[c.event_type])}</span> },
      { key: "received", header: t("qa.cmp.head.received"), width: "120px", sortKey: "received_on", sortKeyDesc: "-received_on", render: (c) => fmtDate(c.received_on) },
      {
        key: "report",
        header: t("qa.cmp.head.report"),
        width: "190px",
        exportValue: (c) => c.reporting_due.map((r) => `${r.regime} ${r.due_on}`).join("; "),
        render: (c) => {
          const next = [...c.reporting_due].sort((a, b) => a.due_on.localeCompare(b.due_on))[0];
          return next ? <DueCell at={next.due_on} overdue={next.overdue && c.status !== "closed"} /> : <span className="faint">—</span>;
        },
      },
    ],
    [],
  );
  return (
    <QaWorklist<Complaint>
      title={t("qa.cmp.title")}
      description={t("qa.cmp.desc")}
      actions={
        canEdit ? (
          <Link className="btn primary" to={mfgPaths.qaComplaint("new")} data-testid="complaint-new">
            <Icon name="plus" /> {t("qa.cmp.btn.new")}
          </Link>
        ) : null
      }
      pageKey="qa-complaints"
      testId="qa-complaints-page"
      searchPlaceholder={t("qa.cmp.ph.search")}
      statusOptions={[{ value: "", label: t("qa.ncr.status.active") }, ...Object.keys(COMPLAINT_STATUS).map((s) => ({ value: s, label: labelOf(COMPLAINT_STATUS, s) })), { value: "all", label: t("qa.list.status.all") }]}
      defaultStatus="open,investigation"
      fetch={(q, signal) => listComplaints({ ...q, status: q.status === "all" ? undefined : q.status }, signal)}
      columns={columns}
      card={{ title: "number", status: "status", fields: ["customer", "event", "report"] }}
      rowKey={(c) => c.id}
      rowExtras={(c) => ({ testId: "complaint-row", data: { status: c.status } })}
      rowPath={(c) => mfgPaths.qaComplaint(c.id)}
      empty={t("qa.cmp.empty")}
      noun={t("qa.cmp.str.noun")}
    />
  );
}

const blankComplaint = (): ComplaintInput => ({ received_on: today(), aware_on: today(), channel: "email", customer: "", country: null, item_id: null, lots: [], serials: [], qty_affected: null, description: "", event_type: "other", reportability: { assessed: false, reportable: null, regimes: [], report_ref: null }, investigation: "", external_ref: null });
const cmpInput = (c: Complaint): ComplaintInput => ({ received_on: c.received_on, aware_on: c.aware_on, channel: c.channel, customer: c.customer, country: c.country, item_id: c.item_id, lots: c.lots.map((l) => l.code), serials: c.serials.map((s) => s.code), qty_affected: c.qty_affected, description: c.description, event_type: c.event_type, reportability: c.reportability, investigation: c.investigation, external_ref: c.external_ref });
const splitCodes = (s: string) => s.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);

export function ComplaintPage() {
  const { complaintId = "" } = useParams();
  const isNew = complaintId === "new";
  const navigate = useNavigate();
  const canEdit = useCan("complaint_edit");
  const canCapa = useCan("capa_edit");
  const canNcr = useCan("ncr_edit");
  const person = usePersonName();
  const reason = useChangeReason();
  const rec = useLoad((s) => (isNew ? null : getComplaint(complaintId, s)), [complaintId]);
  const c = rec.data;
  const [form, setForm] = useState<ComplaintInput>(blankComplaint());
  const [lotsText, setLotsText] = useState("");
  const [serialsText, setSerialsText] = useState("");
  const [item, setItem] = useState<ItemRef | null>(null);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("details");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [closing, setClosing] = useState(false);
  useEffect(() => {
    if (c) {
      setForm(cmpInput(c));
      setLotsText(c.lots.map((l) => l.code).join(", "));
      setSerialsText(c.serials.map((l) => l.code).join(", "));
      setDirty(false);
      document.title = `${c.number} - ${t("qa.cmp.title")}`;
    } else if (isNew) document.title = t("qa.cmp.str.newDocTitle");
  }, [c, isNew]);
  if (!isNew && rec.loading && !c) return <Spinner />;
  if (!isNew && !c) return <MfgError error={rec.error} onRetry={rec.reload} />;
  const editable = canEdit && (isNew || c!.status !== "closed");
  const set = (p: Partial<ComplaintInput>) => {
    setForm((f) => ({ ...f, ...p }));
    setDirty(true);
  };
  const body = (): ComplaintInput => ({ ...form, lots: splitCodes(lotsText), serials: splitCodes(serialsText) });
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        const x = await createComplaint(body());
        toast(t("qa.cmp.toast.created", { n: x.number }));
        setDirty(false);
        navigate(mfgPaths.qaComplaint(x.id), { replace: true });
      } else if (c) {
        const r = await reason.ask(c.number);
        if (r === null) return;
        rec.setData(await updateComplaint(c.id, body(), c.row_version, r));
        setDirty(false);
        toast(t("qa.cmp.toast.saved"));
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const rep = form.reportability;
  const formView = (
    <FormErrors error={error}>
      <Section title={t("qa.cmp.head.complaint")}>
        <div className="qa-form-grid">
          <TextField label={t("qa.cmp.head.customer")} name="customer" value={form.customer} onChange={(v) => set({ customer: v })} disabled={!editable} required testId="complaint-customer" />
          <TextField label={t("qa.cmp.label.country")} name="country" value={form.country ?? ""} onChange={(v) => set({ country: v.toUpperCase().slice(0, 2) || null })} disabled={!editable} hint={t("qa.cmp.hint.country")} />
          <div className="field">
            <label htmlFor="cmp-ch">{t("qa.cmp.label.channel")}</label>
            <select id="cmp-ch" className="select" value={form.channel} disabled={!editable} onChange={(e) => set({ channel: e.target.value as Channel })}>
              {(Object.keys(CHANNEL_KEY) as Channel[]).map((k) => (
                <option key={k} value={k}>
                  {t(CHANNEL_KEY[k])}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="cmp-rec">{t("qa.cmp.head.received")}</label>
            <DateInput id="cmp-rec" value={form.received_on} onChange={(v) => set({ received_on: v })} disabled={!editable} />
          </div>
          <div className="field">
            <label htmlFor="cmp-aware">{t("qa.cmp.label.aware")}</label>
            <DateInput id="cmp-aware" value={form.aware_on} onChange={(v) => set({ aware_on: v })} min={form.received_on} disabled={!editable} />
          </div>
          <div className="field">
            <label htmlFor="cmp-ev">{t("qa.settings.head.eventType")}</label>
            <select id="cmp-ev" className="select" value={form.event_type} disabled={!editable} onChange={(e) => set({ event_type: e.target.value as EventType })}>
              {(Object.keys(EVENT_KEY) as EventType[]).map((k) => (
                <option key={k} value={k}>
                  {t(EVENT_KEY[k])}
                </option>
              ))}
            </select>
          </div>
          <div className="span-2">
            <ItemPicker label={t("qa.lots.head.item")} value={item} onChange={(i) => (setItem(i), set({ item_id: i.id }))} disabled={!editable} />
          </div>
          <TextField label={t("qa.cmp.label.qty")} type="number" value={form.qty_affected === null ? "" : String(form.qty_affected)} onChange={(v) => set({ qty_affected: v ? Number(v) : null })} disabled={!editable} />
          <div className="field span-2">
            <label htmlFor="cmp-lots">{t("qa.cmp.label.lots")}</label>
            <input id="cmp-lots" className="input mono" value={lotsText} disabled={!editable} onChange={(e) => (setLotsText(e.target.value), setDirty(true))} placeholder={t("qa.cmp.ph.codes")} />
          </div>
          <div className="field span-2">
            <label htmlFor="cmp-ser">{t("qa.cmp.label.serials")}</label>
            <input id="cmp-ser" className="input mono" value={serialsText} disabled={!editable} onChange={(e) => (setSerialsText(e.target.value), setDirty(true))} placeholder={t("qa.cmp.ph.codes")} />
          </div>
          <div className="field span-all">
            <label htmlFor="cmp-desc">{t("qa.ncr.label.description")}</label>
            <textarea id="cmp-desc" className="textarea" rows={3} value={form.description} disabled={!editable} onChange={(e) => set({ description: e.target.value })} data-testid="complaint-description" />
          </div>
          {!isNew ? (
            <div className="field span-all">
              <label htmlFor="cmp-inv">{t("qa.ncr.label.investigation")}</label>
              <textarea id="cmp-inv" className="textarea" rows={3} value={form.investigation} disabled={!editable} onChange={(e) => set({ investigation: e.target.value })} />
            </div>
          ) : null}
        </div>
      </Section>
      <Section title={t("qa.cmp.head.reportability")}>
        <div className="qa-form-grid">
          <div className="field">
            <label htmlFor="cmp-rep">{t("qa.cmp.label.reportable")}</label>
            <select id="cmp-rep" className="select" value={rep.reportable === null ? "" : rep.reportable ? "yes" : "no"} disabled={!editable} onChange={(e) => set({ reportability: { ...rep, assessed: e.target.value !== "", reportable: e.target.value === "" ? null : e.target.value === "yes" } })}>
              <option value="">{t("qa.cmp.str.notAssessed")}</option>
              <option value="yes">{t("qa.cmp.str.reportable")}</option>
              <option value="no">{t("qa.cmp.str.notReportable")}</option>
            </select>
          </div>
          <TextField label={t("qa.cmp.label.regimes")} value={rep.regimes.join(", ")} onChange={(v) => set({ reportability: { ...rep, regimes: splitCodes(v.toLowerCase()) } })} disabled={!editable} hint={t("qa.cmp.hint.regimes")} />
          <TextField label={t("qa.cmp.label.reportRef")} value={rep.report_ref ?? ""} onChange={(v) => set({ reportability: { ...rep, report_ref: v || null } })} disabled={!editable} />
        </div>
        {c?.reporting_due.length ? (
          <table className="table" style={{ marginTop: 12 }} data-testid="complaint-reporting">
            <thead>
              <tr>
                <th>{t("qa.settings.head.regime")}</th>
                <th className="num">{t("qa.settings.head.days")}</th>
                <th>{t("qa.cmp.head.reportDue")}</th>
              </tr>
            </thead>
            <tbody>
              {c.reporting_due.map((r) => (
                <tr key={r.regime}>
                  <td className="mono">{r.regime}</td>
                  <td className="num">{r.days}</td>
                  <td>
                    <DueCell at={r.due_on} overdue={r.overdue && c.status !== "closed"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        <p className="small muted" style={{ margin: "8px 0 0" }}>
          {t("qa.settings.text.reportability")}
        </p>
      </Section>
    </FormErrors>
  );
  if (isNew)
    return (
      <div className="col gap-lg" data-testid="complaint-new-page">
        <UnsavedChangesGuard when={dirty} what={t("qa.cmp.str.thisComplaint")} />
        <PageHeader
          title={t("qa.cmp.str.newTitle")}
          description={t("qa.cmp.str.newDesc")}
          actions={
            <button type="button" className="btn primary" disabled={busy || !form.customer.trim()} onClick={() => void save()} data-testid="complaint-save">
              <Icon name="save" /> {t("qa.cmp.btn.create")}
            </button>
          }
        />
        <MfgError error={error} />
        {formView}
      </div>
    );
  const x = c!;
  const firstLot = x.lots.find((l) => l.lot_id);
  const followUp = async (kind: "capa") => {
    setBusy(true);
    try {
      const capa = await createCapa({ ...blankCapa(), title: t("qa.cmp.tpl.capaTitle", { n: x.number, c: x.customer }), problem: x.description });
      await createLink({ from_type: "complaint", from_id: x.id, to_type: kind, to_id: capa.id });
      toast(t("qa.capa.toast.created", { n: capa.number }));
      navigate(mfgPaths.qaCapa(capa.id));
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <div className="col gap-lg" data-testid="complaint-page" data-status={x.status}>
      <UnsavedChangesGuard when={dirty} what={t("qa.cmp.str.thisComplaint")} />
      <RecordHeader
        crumbs={[[t("nav.mfg.section.qa-complaints"), mfgPaths.qaComplaints()]]}
        number={x.number}
        title={x.customer}
        status={<ComplaintStatusChip s={x.status} />}
        chips={x.event_type === "death" || x.event_type === "serious_injury" ? <span className="badge danger"><Icon name="alert" /> {t(EVENT_KEY[x.event_type])}</span> : null}
        facts={[
          [t("qa.cmp.head.received"), fmtDate(x.received_on)],
          [t("qa.cmp.label.aware"), fmtDate(x.aware_on)],
          [t("qa.cmp.label.channel"), t(CHANNEL_KEY[x.channel])],
          [t("qa.settings.head.eventType"), t(EVENT_KEY[x.event_type])],
          [t("qa.cmp.label.lots"), x.lots.length ? <span className="mono">{x.lots.map((l) => l.code).join(", ")}</span> : null],
          [t("qa.cmp.head.report"), x.reporting_due.length ? <DueCell at={[...x.reporting_due].sort((a, b) => a.due_on.localeCompare(b.due_on))[0].due_on} overdue={x.reporting_due.some((r) => r.overdue) && x.status !== "closed"} /> : null],
          [t("qa.ncr.label.author"), person(x.author_id)],
        ]}
        actions={
          <>
            <Link className="btn ghost" to={mfgPaths.printQa("complaint", x.id)} target="_blank" rel="noopener">
              <Icon name="file" /> {t("qa.common.btn.print")}
            </Link>
            {editable ? (
              <button type="button" className="btn" disabled={busy || !dirty} onClick={() => void save()} data-testid="complaint-save">
                <Icon name="save" /> {t("qa.plans.btn.save")}
              </button>
            ) : null}
            {x.status === "open" && canEdit ? (
              <button
                type="button"
                className="btn primary"
                disabled={busy || dirty}
                onClick={async () => {
                  try {
                    rec.setData(await advanceComplaint(x.id, x.row_version));
                    toast(t("qa.cmp.toast.investigation"));
                  } catch (e) {
                    setError(e);
                  }
                }}
                data-testid="complaint-advance"
              >
                <Icon name="search" /> {t("qa.cmp.btn.investigate")}
              </button>
            ) : x.status === "investigation" && canEdit ? (
              <button type="button" className="btn primary" disabled={busy || dirty} onClick={() => setClosing(true)} data-testid="complaint-close">
                <Icon name="lock" /> {t("qa.cmp.btn.close")}
              </button>
            ) : null}
          </>
        }
      />
      {x.sor === "external" ? (
        <Banner tone="info" icon="external" title={t("qa.capa.title.external")}>
          {t("qa.cmp.text.external", { ref: x.external_ref ?? "—" })}
        </Banner>
      ) : null}
      {x.warnings.length ? (
        <Banner tone="warn" title={t("qa.cmp.title.unresolved")}>
          <ul className="mfg-plain-list">
            {x.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {x.status !== "closed" ? (
        <section className="card">
          <div className="card-header">
            <h2>{t("qa.cmp.head.followUp")}</h2>
          </div>
          <div className="card-body row wrap" style={{ gap: 8 }}>
            {firstLot ? (
              <Link className="btn" to={mfgPaths.trace({ kind: "lot", id: firstLot.lot_id!, label: firstLot.code })}>
                <Icon name="link" /> {t("qa.cmp.btn.trace")}
              </Link>
            ) : null}
            {canNcr ? (
              <Link className="btn" to={`${mfgPaths.qaNcr("new")}?complaint=${encodeURIComponent(x.id)}`}>
                <Icon name="alert" /> {t("qa.cmp.btn.ncr")}
              </Link>
            ) : null}
            {canCapa ? (
              <button type="button" className="btn" disabled={busy} onClick={() => void followUp("capa")}>
                <Icon name="refresh" /> {t("qa.cmp.btn.capa")}
              </button>
            ) : null}
            {firstLot ? (
              <Link className="btn" to={`${mfgPaths.recalls()}?new=1&kind=lot&id=${encodeURIComponent(firstLot.lot_id!)}&label=${encodeURIComponent(firstLot.code)}`}>
                <Icon name="flag" /> {t("qa.cmp.btn.recall")}
              </Link>
            ) : null}
          </div>
        </section>
      ) : null}
      {isConflict(error) ? <ConflictBanner onReload={() => (setError(null), rec.reload())} /> : <MfgError error={error} />}
      <RecordTabs label={t("qa.cmp.aria.tabs")} value={tab} onChange={setTab} tabs={[{ key: "details", label: t("qa.shell.tab.details") }, ...standardTabs(x)]} />
      {tab === "details" ? <TabPanel id="details">{formView}</TabPanel> : null}
      {tab === "links" ? (
        <TabPanel id="links">
          <LinksTab links={x.links} fromType="complaint" fromId={x.id} canEdit={canEdit} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {tab === "attachments" ? (
        <TabPanel id="attachments">
          <AttachmentsTab attachments={x.attachments} entityType="complaint" entityId={x.id} canEdit={canEdit} locked={x.status === "closed"} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {tab === "history" ? (
        <TabPanel id="history">
          <HistoryTab entityType="complaint" entityId={x.id} />
        </TabPanel>
      ) : null}
      {tab === "signatures" ? (
        <TabPanel id="signatures">
          <SignaturesTab signatures={x.signatures} recordType="complaint" recordId={x.id} />
        </TabPanel>
      ) : null}
      {reason.dialog}
      {closing ? (
        <SignatureDialog<Complaint>
          title={t("qa.cmp.tpl.closeTitle", { n: x.number })}
          recordType="complaint"
          recordId={x.id}
          recordLabel={x.number}
          action="close"
          meaning="closed"
          submitLabel={t("qa.ncr.btn.signClose")}
          plainLabel={t("qa.cmp.btn.close")}
          effect={x.reportability.assessed ? t("qa.cmp.text.closeEffect") : t("qa.cmp.text.closeUnassessed")}
          perform={(sig, comment) => recordAction<Complaint>("complaint", x.id, "close", { note: comment }, { version: x.row_version, signature: sig })}
          onDone={(res) => {
            toast(signedToast(res, t("qa.cmp.toast.closed")));
            setClosing(false);
            rec.reload();
          }}
          onClose={() => setClosing(false)}
        />
      ) : null}
    </div>
  );
}

