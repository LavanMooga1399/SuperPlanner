/**
 * Field actions (M7 7, 10): built on a recall report - the affected units, lots and customers are frozen from the
 * report. Approval (signed) places field-action holds on affected stock; unit status per customer (single, bulk or
 * CSV "code,status,note"), effectiveness per customer and overall, completion, signed close (releases the holds),
 * export for the customer letters produced outside.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { saveBlob } from "../api/client";
import { listRecalls } from "../api/clientM5";
import { bulkUnitStatus, completeFieldAction, createFieldAction, exportFieldAction, getFieldAction, listFieldActions, listFieldActionUnits, recordAction, updateFieldAction } from "../api/clientM7";
import type { FaKind, FieldAction, FieldActionInput, FieldActionUnit, UnitStatus } from "../api/typesM7";
import { ConflictBanner, MfgError, Spinner } from "../components/Feedback";
import { FormErrors, TextField } from "../components/Field";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { isConflict, useLoad } from "../lib/useMfg";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { t, type StringKey } from "../../lib/i18n";
import { fmtQ } from "./common";
import { FA_STATUS, FaStatusChip, labelOf, UNIT_STATUS, UnitStatusChip } from "./labels";
import { AttachmentsTab, HistoryTab, LinksTab, NextStepBanner, RecordHeader, RecordTabs, Section, SignaturesTab, standardTabs, TabPanel, useChangeReason } from "./RecordShell";
import { QaWorklist } from "./Worklist";
import "./qa.css";

const KIND_KEY: Record<FaKind, StringKey> = { recall: "qa.fa.kind.recall", correction: "qa.fa.kind.correction", removal: "qa.fa.kind.removal", safety_notice: "qa.fa.kind.safetyNotice", software_update: "qa.fa.kind.softwareUpdate" };
const UNIT_STATUSES = Object.keys(UNIT_STATUS) as UnitStatus[];

export function FieldActionsPage() {
  const canEdit = useCan("field_action_edit");
  useEffect(() => {
    document.title = t("qa.fa.str.docTitle");
  }, []);
  const columns = useMemo<Column<FieldAction>[]>(
    () => [
      {
        key: "number",
        header: t("qa.fa.head.fa"),
        width: "120px",
        sortKey: "number",
        sortKeyDesc: "-number",
        exportValue: (f) => f.number,
        render: (f) => (
          <Link to={mfgPaths.qaFieldAction(f.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {f.number}
          </Link>
        ),
      },
      { key: "status", header: t("qa.ncr.head.status"), width: "130px", exportValue: (f) => labelOf(FA_STATUS, f.status), render: (f) => <FaStatusChip s={f.status} /> },
      { key: "title", header: t("qa.ncr.head.title"), width: "minmax(220px, 2fr)", render: (f) => <span className="mfg-ellipsis">{f.title}</span> },
      { key: "kind", header: t("qa.capa.head.kind"), width: "150px", render: (f) => `${t(KIND_KEY[f.kind])}${f.class ? ` · ${t("qa.fa.tpl.class", { c: f.class })}` : ""}` },
      { key: "units", header: t("qa.fa.head.units"), width: "90px", align: "right", render: (f) => formatNumber(f.units_total) },
      { key: "eff", header: t("qa.fa.head.effectiveness"), width: "180px", exportValue: (f) => f.effectiveness.overall?.pct ?? "", render: (f) => <EffBar pct={f.effectiveness.overall?.pct ?? 0} /> },
      { key: "recall", header: t("qa.fa.head.recall"), width: "120px", drop: 1, render: (f) => <span className="mono">{f.recall_number ?? ""}</span> },
    ],
    [],
  );
  return (
    <QaWorklist<FieldAction>
      title={t("qa.fa.title")}
      description={t("qa.fa.desc")}
      actions={
        canEdit ? (
          <Link className="btn primary" to={mfgPaths.qaFieldAction("new")} data-testid="fa-new">
            <Icon name="plus" /> {t("qa.fa.btn.new")}
          </Link>
        ) : null
      }
      pageKey="qa-field-actions"
      testId="qa-fa-page"
      searchPlaceholder={t("qa.fa.ph.search")}
      statusOptions={[{ value: "", label: t("qa.ncr.status.active") }, ...Object.keys(FA_STATUS).map((s) => ({ value: s, label: labelOf(FA_STATUS, s) })), { value: "all", label: t("qa.list.status.all") }]}
      defaultStatus="draft,approved,in_progress,completed"
      fetch={(q, signal) => listFieldActions({ ...q, status: q.status === "all" ? undefined : q.status }, signal)}
      columns={columns}
      card={{ title: "number", status: "status", fields: ["title", "units", "eff"] }}
      rowKey={(f) => f.id}
      rowExtras={(f) => ({ testId: "fa-row", data: { status: f.status } })}
      rowPath={(f) => mfgPaths.qaFieldAction(f.id)}
      empty={t("qa.fa.empty")}
      noun={t("qa.fa.str.noun")}
    />
  );
}

function EffBar({ pct }: { pct: number }) {
  return (
    <span className="row" style={{ gap: 6, width: "100%" }}>
      <span className={`qa-progress${pct >= 100 ? " ok" : ""}`} style={{ flex: 1 }} aria-hidden>
        <span style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
      </span>
      <span className="small" style={{ minWidth: 40, textAlign: "right" }}>
        {t("qa.fa.tpl.pct", { p: formatNumber(pct, 0) })}
      </span>
    </span>
  );
}

type FaSign = null | "approve" | "close" | "cancel";

export function FieldActionPage() {
  const { faId = "" } = useParams();
  const isNew = faId === "new";
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const canEdit = useCan("field_action_edit");
  const canApprove = useCan("capa_approve");
  const reason = useChangeReason();
  const rec = useLoad((s) => (isNew ? null : getFieldAction(faId, s)), [faId]);
  const recalls = useLoad((s) => (isNew ? listRecalls({ limit: 200 }, s) : null), [isNew]);
  const f = rec.data;
  const [form, setForm] = useState<FieldActionInput>({ title: "", kind: "recall", class: null, regimes: [], strategy: "", recall_id: params.get("recall") ?? "" });
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("units");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sign, setSign] = useState<FaSign>(null);
  const [completing, setCompleting] = useState(false);
  const [unitsTick, setUnitsTick] = useState(0);
  useEffect(() => {
    if (f) {
      setForm({ title: f.title, kind: f.kind, class: (f.class as FieldActionInput["class"]) ?? null, regimes: f.regimes, strategy: f.strategy, recall_id: f.recall_id });
      setDirty(false);
      document.title = `${f.number} - ${t("qa.fa.title")}`;
    } else if (isNew) document.title = t("qa.fa.str.newDocTitle");
  }, [f, isNew]);
  if (!isNew && rec.loading && !f) return <Spinner />;
  if (!isNew && !f) return <MfgError error={rec.error} onRetry={rec.reload} />;
  const editable = canEdit && (isNew || f!.status === "draft");
  const set = (p: Partial<FieldActionInput>) => {
    setForm((x) => ({ ...x, ...p }));
    setDirty(true);
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        const c = await createFieldAction(form);
        toast(t("qa.fa.toast.created", { n: c.number }));
        setDirty(false);
        navigate(mfgPaths.qaFieldAction(c.id), { replace: true });
      } else if (f) {
        const r = await reason.ask(f.number);
        if (r === null) return;
        const { recall_id: _r, ...body } = form;
        rec.setData(await updateFieldAction(f.id, body, f.row_version, r));
        setDirty(false);
        toast(t("qa.fa.toast.saved"));
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const formView = (
    <FormErrors error={error}>
      <Section title={t("qa.fa.head.details")}>
        <div className="qa-form-grid">
          <div className="span-2">
            <TextField label={t("qa.ncr.head.title")} name="title" value={form.title} onChange={(v) => set({ title: v })} disabled={!editable} required testId="fa-title" />
          </div>
          {isNew ? (
            <div className="field span-2">
              <label htmlFor="fa-recall">{t("qa.fa.head.recall")}</label>
              <select id="fa-recall" className="select" value={form.recall_id} onChange={(e) => set({ recall_id: e.target.value })} data-testid="fa-recall">
                <option value="">{t("qa.fa.str.chooseRecall")}</option>
                {(recalls.data?.items ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.number} {r.name}
                  </option>
                ))}
              </select>
              <span className="hint">{t("qa.fa.hint.recall")}</span>
            </div>
          ) : null}
          <div className="field">
            <label htmlFor="fa-kind">{t("qa.capa.head.kind")}</label>
            <select id="fa-kind" className="select" value={form.kind} disabled={!editable} onChange={(e) => set({ kind: e.target.value as FaKind })}>
              {(Object.keys(KIND_KEY) as FaKind[]).map((k) => (
                <option key={k} value={k}>
                  {t(KIND_KEY[k])}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="fa-class">{t("qa.fa.label.class")}</label>
            <select id="fa-class" className="select" value={form.class ?? ""} disabled={!editable} onChange={(e) => set({ class: (e.target.value || null) as FieldActionInput["class"] })}>
              <option value="">{t("qa.fa.str.noClass")}</option>
              {["I", "II", "III"].map((c) => (
                <option key={c} value={c}>
                  {t("qa.fa.tpl.class", { c })}
                </option>
              ))}
            </select>
          </div>
          <TextField label={t("qa.cmp.label.regimes")} value={form.regimes.join(", ")} onChange={(v) => set({ regimes: v.toLowerCase().split(/[\s,;]+/).filter(Boolean) })} disabled={!editable} hint={t("qa.cmp.hint.regimes")} />
          <div className="field span-all">
            <label htmlFor="fa-strategy">{t("qa.fa.label.strategy")}</label>
            <textarea id="fa-strategy" className="textarea" rows={3} value={form.strategy} disabled={!editable} onChange={(e) => set({ strategy: e.target.value })} />
          </div>
        </div>
      </Section>
    </FormErrors>
  );
  if (isNew)
    return (
      <div className="col gap-lg" data-testid="fa-new-page">
        <PageHeader
          title={t("qa.fa.str.newTitle")}
          description={t("qa.fa.str.newDesc")}
          actions={
            <button type="button" className="btn primary" disabled={busy || !form.title.trim() || !form.recall_id} onClick={() => void save()} data-testid="fa-save">
              <Icon name="save" /> {t("qa.ncr.btn.create")}
            </button>
          }
        />
        <MfgError error={error} />
        {formView}
      </div>
    );
  const x = f!;
  const ov = x.effectiveness.overall;
  const guide: Partial<Record<string, StringKey>> = { draft: "qa.fa.guide.draft", approved: "qa.fa.guide.inProgress", in_progress: "qa.fa.guide.inProgress", completed: "qa.fa.guide.completed" };
  return (
    <div className="col gap-lg" data-testid="fa-page" data-status={x.status}>
      <RecordHeader
        crumbs={[[t("nav.mfg.section.qa-field-actions"), mfgPaths.qaFieldActions()]]}
        number={x.number}
        title={x.title}
        status={<FaStatusChip s={x.status} />}
        facts={[
          [t("qa.capa.head.kind"), `${t(KIND_KEY[x.kind])}${x.class ? ` · ${t("qa.fa.tpl.class", { c: x.class })}` : ""}`],
          [t("qa.fa.head.recall"), <Link key="r" to={mfgPaths.recall(x.recall_id)} className="mono">{x.recall_number ?? x.recall_id}</Link>],
          [t("qa.cmp.label.regimes"), x.regimes.length ? <span className="mono">{x.regimes.join(", ")}</span> : null],
          [t("qa.fa.head.units"), formatNumber(x.units_total)],
          [t("qa.fa.head.effectiveness"), ov ? t("qa.fa.tpl.eff", { d: formatNumber(ov.done), n: formatNumber(ov.total), p: formatNumber(ov.pct, 0) }) : null],
        ]}
        actions={
          <>
            {["draft", "approved", "in_progress"].includes(x.status) && canEdit ? (
              <button type="button" className="btn ghost" onClick={() => setSign("cancel")}>
                {t("qa.fa.btn.cancel")}
              </button>
            ) : null}
            <button type="button" className="btn ghost" onClick={async () => saveBlob(await exportFieldAction(x.id, "xlsx"))} data-testid="fa-export">
              <Icon name="download" /> {t("qa.fa.btn.export")}
            </button>
            <Link className="btn ghost" to={mfgPaths.printQa("field_action", x.id)} target="_blank" rel="noopener">
              <Icon name="file" /> {t("qa.common.btn.print")}
            </Link>
            {editable ? (
              <button type="button" className="btn" disabled={busy || !dirty} onClick={() => void save()}>
                <Icon name="save" /> {t("qa.plans.btn.save")}
              </button>
            ) : null}
            {x.status === "draft" && canApprove ? (
              <button type="button" className="btn primary" disabled={busy || dirty} onClick={() => setSign("approve")} data-testid="fa-approve">
                <Icon name="check" /> {t("qa.fa.btn.approve")}
              </button>
            ) : (x.status === "in_progress" || x.status === "approved") && canEdit ? (
              <button type="button" className="btn primary" disabled={busy} onClick={() => setCompleting(true)} data-testid="fa-complete">
                <Icon name="check" /> {t("qa.fa.btn.complete")}
              </button>
            ) : x.status === "completed" && canApprove ? (
              <button type="button" className="btn primary" disabled={busy} onClick={() => setSign("close")} data-testid="fa-close">
                <Icon name="lock" /> {t("qa.fa.btn.close")}
              </button>
            ) : null}
          </>
        }
      />
      {guide[x.status] ? <NextStepBanner text={t(guide[x.status]!)} /> : null}
      {isConflict(error) ? <ConflictBanner onReload={() => (setError(null), rec.reload())} /> : <MfgError error={error} />}
      <RecordTabs
        label={t("qa.fa.aria.tabs")}
        value={tab}
        onChange={setTab}
        tabs={[{ key: "units", label: t("qa.fa.tab.units"), count: x.units_total }, { key: "effectiveness", label: t("qa.fa.head.effectiveness") }, { key: "details", label: t("qa.shell.tab.details") }, ...standardTabs(x)]}
      />
      {tab === "units" ? (
        <TabPanel id="units">
          <Units key={unitsTick} fa={x} editable={canEdit && ["approved", "in_progress", "completed"].includes(x.status)} onChanged={() => (rec.reload(), setUnitsTick((n) => n + 1))} />
        </TabPanel>
      ) : null}
      {tab === "effectiveness" ? (
        <TabPanel id="effectiveness">
          <Section title={t("qa.fa.head.byCustomer")} testId="fa-effectiveness">
            <div className="col" style={{ gap: 8 }}>
              {ov ? (
                <div className="qa-eff">
                  <strong>{t("qa.fa.str.overall")}</strong>
                  <EffBar pct={ov.pct} />
                  <span className="num">{t("qa.fa.tpl.dn", { d: formatNumber(ov.done), n: formatNumber(ov.total) })}</span>
                </div>
              ) : null}
              {(x.effectiveness.by_customer ?? []).map((c) => (
                <div key={c.customer} className="qa-eff">
                  <span className="mfg-ellipsis">{c.customer}</span>
                  <EffBar pct={c.pct} />
                  <span className="num">{t("qa.fa.tpl.dn", { d: formatNumber(c.done), n: formatNumber(c.total) })}</span>
                </div>
              ))}
              <p className="small muted" style={{ margin: 0 }}>
                {t("qa.fa.text.effHint")}
              </p>
            </div>
          </Section>
        </TabPanel>
      ) : null}
      {tab === "details" ? <TabPanel id="details">{formView}</TabPanel> : null}
      {tab === "links" ? (
        <TabPanel id="links">
          <LinksTab links={x.links} fromType="field_action" fromId={x.id} canEdit={canEdit} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {tab === "attachments" ? (
        <TabPanel id="attachments">
          <AttachmentsTab attachments={x.attachments} entityType="field_action" entityId={x.id} canEdit={canEdit} locked={["closed", "cancelled"].includes(x.status)} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {tab === "history" ? (
        <TabPanel id="history">
          <HistoryTab entityType="field_action" entityId={x.id} />
        </TabPanel>
      ) : null}
      {tab === "signatures" ? (
        <TabPanel id="signatures">
          <SignaturesTab signatures={x.signatures} recordType="field_action" recordId={x.id} />
        </TabPanel>
      ) : null}
      {reason.dialog}
      {completing ? (
        <CompleteDialog
          fa={x}
          onClose={() => setCompleting(false)}
          onDone={(r) => {
            setCompleting(false);
            rec.setData(r);
          }}
        />
      ) : null}
      {sign ? (
        <SignatureDialog<FieldAction>
          title={t(sign === "approve" ? "qa.fa.tpl.approveTitle" : sign === "close" ? "qa.fa.tpl.closeTitle" : "qa.fa.tpl.cancelTitle", { n: x.number })}
          recordType="field_action"
          recordId={x.id}
          recordLabel={x.number}
          action={sign}
          signable={sign !== "cancel"}
          meaning={sign === "approve" ? "approved" : "closed"}
          danger={sign === "cancel"}
          commentRequired={sign === "cancel"}
          commentLabel={sign === "cancel" ? t("qa.lots.label.cancelReason") : undefined}
          submitLabel={t(sign === "approve" ? "qa.ncr.btn.signApprove" : sign === "close" ? "qa.ncr.btn.signClose" : "qa.lots.btn.signCancel")}
          plainLabel={t(sign === "approve" ? "qa.fa.btn.approve" : sign === "close" ? "qa.fa.btn.close" : "qa.fa.btn.cancel")}
          effect={t(sign === "approve" ? "qa.fa.text.approveEffect" : sign === "close" ? "qa.fa.text.closeEffect" : "qa.fa.text.cancelEffect")}
          perform={(sig, comment) => recordAction<FieldAction>("field_action", x.id, sign, sign === "cancel" ? { reason: comment } : { note: comment }, { version: x.row_version, signature: sig })}
          onDone={(res) => {
            toast(signedToast(res, t("qa.capa.toast.signed")));
            setSign(null);
            rec.reload();
          }}
          onClose={() => setSign(null)}
        />
      ) : null}
    </div>
  );
}

function CompleteDialog({ fa, onClose, onDone }: { fa: FieldAction; onClose(): void; onDone(f: FieldAction): void }) {
  const open = (fa.effectiveness.overall?.total ?? 0) - (fa.effectiveness.overall?.done ?? 0);
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Dialog
      title={t("qa.fa.tpl.completeTitle", { n: fa.number })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || (open > 0 && !why.trim())}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                onDone(await completeFieldAction(fa.id, fa.row_version, why.trim() || null));
                toast(t("qa.fa.toast.completed"));
              } catch (e) {
                setError(e);
                setBusy(false);
              }
            }}
          >
            {t("qa.fa.btn.complete")}
          </button>
        </>
      }
    >
      <div className="col">
        {open > 0 ? <Banner tone="warn">{t("qa.fa.tpl.openUnits", { n: formatNumber(open) })}</Banner> : <p style={{ margin: 0 }}>{t("qa.fa.text.allDone")}</p>}
        {open > 0 ? (
          <div className="field">
            <label htmlFor="fa-why">{t("qa.fa.label.completeReason")}</label>
            <textarea id="fa-why" className="textarea" rows={2} value={why} maxLength={500} onChange={(e) => setWhy(e.target.value)} />
          </div>
        ) : null}
        <MfgError error={error} />
      </div>
    </Dialog>
  );
}

function Units({ fa, editable, onChanged }: { fa: FieldAction; editable: boolean; onChanged(): void }) {
  const [status, setStatus] = useState("");
  const [customer, setCustomer] = useState("");
  const data = useLoad((s) => listFieldActionUnits(fa.id, { status: status || undefined, customer: customer || undefined, limit: 5000 }, s), [fa.id, status, customer]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [bulk, setBulk] = useState<UnitStatus>("notified");
  const [note, setNote] = useState("");
  const [csv, setCsv] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const rows = data.data?.items ?? [];
  const customers = [...new Set((fa.effectiveness.by_customer ?? []).map((c) => c.customer))];
  const apply = async (body: Parameters<typeof bulkUnitStatus>[1]) => {
    setBusy(true);
    setError(null);
    try {
      await bulkUnitStatus(fa.id, body);
      toast(t("qa.fa.toast.units"));
      setSel(new Set());
      setCsv(null);
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const cols: Column<FieldActionUnit>[] = [
    { key: "code", header: t("qa.fa.head.unit"), width: "minmax(140px, 1fr)", sortValue: (u) => u.code, render: (u) => <span><span className="small muted">{u.kind === "serial" ? t("qa.holds.str.serial") : t("qa.holds.str.lot")}</span> <span className="mono">{u.code}</span></span> },
    { key: "customer", header: t("qa.cmp.head.customer"), width: "minmax(160px, 1.4fr)", sortValue: (u) => u.customer, render: (u) => <span className="mfg-ellipsis">{u.customer}</span> },
    { key: "qty", header: t("qa.fa.head.qty"), width: "90px", align: "right", sortValue: (u) => u.qty, render: (u) => fmtQ(u.qty) },
    { key: "stock", header: t("qa.fa.head.where"), width: "120px", render: (u) => (u.in_stock ? t("qa.fa.str.inStock") : t("qa.fa.str.shipped")) },
    { key: "status", header: t("qa.ncr.head.status"), width: "150px", sortValue: (u) => u.status, exportValue: (u) => labelOf(UNIT_STATUS, u.status), render: (u) => <UnitStatusChip s={u.status} /> },
    { key: "note", header: t("qa.lots.label.note"), width: "minmax(160px, 1.4fr)", render: (u) => <span className="mfg-ellipsis">{u.note}</span> },
    { key: "upd", header: t("qa.fa.head.updated"), width: "160px", sortValue: (u) => u.updated_at ?? "", render: (u) => formatDateTime(u.updated_at) },
  ];
  return (
    <section className="card card-table" data-testid="fa-units">
      <div className="card-header">
        <div className="row wrap" style={{ gap: 8 }}>
          <div className="field">
            <label htmlFor="fu-status">{t("qa.ncr.head.status")}</label>
            <select id="fu-status" className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("qa.list.any")}</option>
              {UNIT_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {labelOf(UNIT_STATUS, s)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="fu-cust">{t("qa.cmp.head.customer")}</label>
            <select id="fu-cust" className="select" value={customer} onChange={(e) => setCustomer(e.target.value)}>
              <option value="">{t("qa.list.any")}</option>
              {customers.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        </div>
        {editable ? (
          <button type="button" className="btn sm" onClick={() => setCsv("")} data-testid="fa-csv">
            <Icon name="upload" /> {t("qa.fa.btn.csv")}
          </button>
        ) : null}
      </div>
      {editable && sel.size ? (
        <div className="bulk-bar row wrap" style={{ gap: 8, padding: "8px 16px" }} role="region" aria-label={t("qa.fa.aria.bulk")}>
          <span className="bulk-count">{t("qa.fa.tpl.selected", { n: sel.size })}</span>
          <label htmlFor="fu-bulk" className="sr-only">
            {t("qa.fa.label.newStatus")}
          </label>
          <select id="fu-bulk" className="select" value={bulk} onChange={(e) => setBulk(e.target.value as UnitStatus)}>
            {UNIT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {labelOf(UNIT_STATUS, s)}
              </option>
            ))}
          </select>
          <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("qa.fa.ph.note")} aria-label={t("qa.lots.label.note")} maxLength={500} />
          <button type="button" className="btn primary sm" disabled={busy} onClick={() => void apply({ items: [...sel].map((id) => ({ unit_id: id, status: bulk, note })) })} data-testid="fa-bulk-apply">
            {t("qa.fa.btn.apply")}
          </button>
          <button type="button" className="btn ghost sm" onClick={() => setSel(new Set())}>
            {t("qa.fa.btn.clearSel")}
          </button>
        </div>
      ) : null}
      <MfgError error={error ?? data.error} />
      <DataTable
        rows={rows}
        columns={cols}
        rowKey={(u) => u.id}
        label={t("qa.fa.tab.units")}
        tableId="fa-units"
        loading={data.loading && !data.data}
        exportName={`${fa.number}-units`}
        empty={t("qa.fa.empty.units")}
        rowExtras={(u) => ({ testId: "fa-unit-row", data: { status: u.status } })}
        selection={editable ? { selected: sel, onChange: setSel, rowId: (u) => u.id, rowLabel: (u) => u.code } : undefined}
      />
      {csv !== null ? (
        <Dialog
          title={t("qa.fa.btn.csv")}
          onClose={() => setCsv(null)}
          wide
          footer={
            <>
              <button type="button" className="btn" onClick={() => setCsv(null)} data-dialog-close>
                {t("common.cancel")}
              </button>
              <button type="button" className="btn primary" disabled={busy || !csv.trim()} onClick={() => void apply({ csv })}>
                {t("qa.fa.btn.import")}
              </button>
            </>
          }
        >
          <div className="col">
            <p style={{ margin: 0 }}>{t("qa.fa.text.csv")}</p>
            <textarea className="textarea mono" rows={10} value={csv} onChange={(e) => setCsv(e.target.value)} placeholder={t("qa.fa.ph.csv")} aria-label={t("qa.fa.btn.csv")} />
            <MfgError error={error} />
          </div>
        </Dialog>
      ) : null}
    </section>
  );
}
