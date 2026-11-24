/**
 * Inspection plans and sampling schemes (M7 5.1, 10) and the plant's quality settings (3 `qa_settings`). Plans are
 * edited as drafts (header fields, characteristic grid with limits and gauge class, sampling preview for a lot size),
 * approved with a signature (`inspection_plan.approve`) and changed through a new version. Schemes ship as a
 * mechanism: the customer loads its licensed tables; approved schemes are immutable.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Banner } from "../../components/Banner";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DateInput } from "../../components/DateInput";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { UnsavedChangesGuard } from "../../components/UnsavedChangesGuard";
import { listLocations } from "../api/clientM2";
import { copyPlan, createPlan, createScheme, deletePlan, deleteScheme, getPlan, getQaSettings, getScheme, listPlans, listSchemes, obsoletePlan, previewSampling, recordAction, updatePlan, updateQaSettings, updateScheme } from "../api/clientM7";
import type { ItemRef } from "../api/types";
import type { CharacteristicInput, DefectCode, InspectionPlan, PlanInput, QaSettings, QaSettingsInput, ReportabilityRule, SamplingScheme, SchemeInput, SchemeKind, Scope, Severity3 } from "../api/typesM7";
import { LEVELS } from "../api/typesM7";
import { ConflictBanner, MfgError, Spinner } from "../components/Feedback";
import { FormErrors, TextField, numOrNull } from "../components/Field";
import { ItemPicker } from "../components/ItemPicker";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { isConflict, useDebounced, useLoad } from "../lib/useMfg";
import { fmtDate } from "../lib/format";
import { formatNumber } from "../../lib/locale";
import { t } from "../../lib/i18n";
import { ItemCell, itemText, useSupplierName, useSuppliersList } from "./common";
import { DOC_STATUS, DocStatusChip, labelOf, roleText, scopeText } from "./labels";
import { AttachmentsTab, HistoryTab, LinksTab, RecordHeader, RecordTabs, Section, SignaturesTab, standardTabs, TabPanel, useChangeReason } from "./RecordShell";
import { QaWorklist } from "./Worklist";
import "./qa.css";

const SEVERITIES: Severity3[] = ["critical", "major", "minor"];
const sevKey = (s: string) => (s === "critical" ? "qa.severity.critical" : s === "major" ? "qa.severity.major" : "qa.severity.minor") as "qa.severity.critical";

// ---------------------------------------------------------------- plans list
export function PlansPage() {
  const canEdit = useCan("qa_plan_edit");
  const supplier = useSupplierName();
  useEffect(() => {
    document.title = t("qa.plans.str.docTitle");
  }, []);
  const columns = useMemo<Column<InspectionPlan>[]>(
    () => [
      {
        key: "number",
        header: t("qa.plans.head.plan"),
        width: "150px",
        sortKey: "number",
        exportValue: (p) => `${p.number} v${p.version}`,
        render: (p) => (
          <Link to={mfgPaths.qaPlan(p.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {p.number} <span className="faint">v{p.version}</span>
          </Link>
        ),
      },
      { key: "status", header: t("qa.plans.head.status"), width: "110px", exportValue: (p) => labelOf(DOC_STATUS, p.status), render: (p) => <DocStatusChip s={p.status} /> },
      { key: "name", header: t("qa.plans.head.name"), width: "minmax(180px, 1.5fr)", render: (p) => <span className="mfg-ellipsis">{p.name}</span> },
      { key: "item", header: t("qa.plans.head.item"), width: "minmax(180px, 1.5fr)", exportValue: (p) => itemText(p.item), render: (p) => <ItemCell item={p.item} id={p.item_id} /> },
      {
        key: "scope",
        header: t("qa.plans.head.scope"),
        width: "minmax(160px, 1fr)",
        exportValue: (p) => scopeText(p.scope),
        render: (p) => (
          <span className="mfg-ellipsis">
            {scopeText(p.scope)}
            <span className="muted">{p.operation_seq ? ` · ${t("qa.plans.tpl.op", { n: p.operation_seq })}` : p.supplier_id ? ` · ${supplier(p.supplier_id)}` : p.customer ? ` · ${p.customer}` : ""}</span>
          </span>
        ),
      },
      { key: "scheme", header: t("qa.plans.head.scheme"), width: "150px", drop: 2, render: (p) => <span className="mono small">{p.scheme_code ?? ""}</span> },
      { key: "chars", header: t("qa.plans.head.chars"), width: "110px", align: "right", drop: 1, render: (p) => p.characteristics.length },
      { key: "eff", header: t("qa.plans.head.effective"), width: "120px", drop: 3, render: (p) => fmtDate(p.effective_from) },
    ],
    [supplier],
  );
  return (
    <QaWorklist<InspectionPlan>
      title={t("qa.plans.title")}
      description={t("qa.plans.desc")}
      actions={
        canEdit ? (
          <Link className="btn primary" to={mfgPaths.qaPlan("new")} data-testid="qa-plan-new">
            <Icon name="plus" /> {t("qa.plans.btn.new")}
          </Link>
        ) : null
      }
      pageKey="qa-plans"
      testId="qa-plans-page"
      searchPlaceholder={t("qa.plans.ph.search")}
      statusOptions={[
        { value: "", label: t("qa.list.status.all") },
        { value: "draft", label: t("qa.status.doc.draft") },
        { value: "approved", label: t("qa.status.doc.approved") },
        { value: "obsolete", label: t("qa.status.doc.obsolete") },
      ]}
      filters={[{ param: "scope", label: t("qa.plans.head.scope"), options: [{ value: "", label: t("qa.list.any") }, { value: "incoming", label: t("qa.scope.incoming") }, { value: "in_process", label: t("qa.scope.inProcess") }, { value: "final", label: t("qa.scope.final") }] }]}
      fetch={(q, signal) => listPlans(q, signal)}
      columns={columns}
      card={{ title: "number", status: "status", fields: ["item", "scope", "chars"] }}
      rowKey={(p) => p.id}
      rowExtras={(p) => ({ testId: "qa-plan-row", data: { status: p.status } })}
      rowPath={(p) => mfgPaths.qaPlan(p.id)}
      empty={t("qa.plans.empty")}
      noun={t("qa.plans.str.noun")}
    />
  );
}

// ---------------------------------------------------------------- plan record / editor
const blankPlan = (): PlanInput => ({
  name: "",
  item_id: "",
  scope: "incoming",
  operation_seq: null,
  supplier_id: null,
  customer: null,
  scheme_id: "",
  inspection_level: "II",
  aql: { critical: "0.065", major: "0.65", minor: "2.5" },
  effective_from: null,
  note: "",
  characteristics: [],
});

const toInput = (p: InspectionPlan): PlanInput => ({
  name: p.name,
  item_id: p.item_id,
  scope: p.scope,
  operation_seq: p.operation_seq,
  supplier_id: p.supplier_id,
  customer: p.customer,
  scheme_id: p.scheme_id,
  inspection_level: p.inspection_level,
  aql: { critical: p.aql.critical ?? "0.065", major: p.aql.major ?? "0.65", minor: p.aql.minor ?? "2.5" },
  effective_from: p.effective_from,
  note: p.note,
  characteristics: p.characteristics.map((c) => ({ ...c })),
});

export function PlanPage() {
  const { planId = "" } = useParams();
  const isNew = planId === "new";
  const navigate = useNavigate();
  const canEdit = useCan("qa_plan_edit");
  const rec = useLoad((s) => (isNew ? null : getPlan(planId, s)), [planId]);
  const schemes = useLoad((s) => listSchemes({ status: "approved", limit: 200 }, s), []);
  const suppliers = useSuppliersList();
  const reason = useChangeReason();
  const p = rec.data;
  const [form, setForm] = useState<PlanInput>(blankPlan());
  const [item, setItem] = useState<ItemRef | null>(null);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("details");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [approving, setApproving] = useState(false);
  const [confirm, setConfirm] = useState<null | "delete" | "obsolete">(null);
  useEffect(() => {
    if (p) {
      setForm(toInput(p));
      setItem(p.item ? ({ id: p.item.id, part_number: p.item.part_number, revision: p.item.revision, description: p.item.name, uom: "", make_buy: "buy", active: true } as ItemRef) : null);
      setDirty(false);
      document.title = `${p.number} - ${t("qa.plans.title")}`;
    } else if (isNew) document.title = t("qa.plans.str.newDocTitle");
  }, [p, isNew]);
  if (!isNew && rec.loading && !p) return <Spinner />;
  if (!isNew && !p) return <MfgError error={rec.error} onRetry={rec.reload} />;
  const draft = isNew || p?.status === "draft";
  const editable = draft && canEdit;
  const set = (patch: Partial<PlanInput>) => {
    setForm((f) => ({ ...f, ...patch }));
    setDirty(true);
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        const created = await createPlan(form);
        toast(t("qa.plans.toast.created", { n: created.number }));
        setDirty(false);
        navigate(mfgPaths.qaPlan(created.id), { replace: true });
      } else if (p) {
        const r = await reason.ask(t("qa.plans.str.what", { n: p.number }));
        if (r === null) return;
        rec.setData(await updatePlan(p.id, form, p.row_version, r));
        toast(t("qa.plans.toast.saved"));
        setDirty(false);
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const header = p ? (
    <RecordHeader
      crumbs={[[t("nav.mfg.section.qa-plans"), mfgPaths.qaPlans()]]}
      number={`${p.number} v${p.version}`}
      title={p.name}
      status={<DocStatusChip s={p.status} />}
      facts={[
        [t("qa.plans.head.item"), <ItemCell key="i" item={p.item} id={p.item_id} />],
        [t("qa.plans.head.scope"), scopeText(p.scope)],
        [t("qa.plans.head.scheme"), p.scheme_code ? <Link to={mfgPaths.qaScheme(p.scheme_id)} className="mono">{p.scheme_code}</Link> : null],
        [t("qa.plans.label.level"), p.inspection_level],
        [t("qa.plans.label.aql"), t("qa.plans.tpl.aql", { c: p.aql.critical ?? "", M: p.aql.major ?? "", m: p.aql.minor ?? "" })],
        [t("qa.plans.head.effective"), fmtDate(p.effective_from)],
      ]}
      actions={
        canEdit ? (
          <>
            {draft ? (
              <button type="button" className="btn ghost" onClick={() => setConfirm("delete")} disabled={busy} data-testid="qa-plan-delete">
                <Icon name="trash" /> {t("qa.plans.btn.delete")}
              </button>
            ) : null}
            {p.status === "approved" ? (
              <>
                <button type="button" className="btn ghost" onClick={() => setConfirm("obsolete")} disabled={busy}>
                  <Icon name="ban" /> {t("qa.plans.btn.obsolete")}
                </button>
                <button
                  type="button"
                  className="btn primary"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      const c = await copyPlan(p.id);
                      toast(t("qa.plans.toast.copied", { v: c.version }));
                      navigate(mfgPaths.qaPlan(c.id));
                    } catch (e) {
                      setError(e);
                    } finally {
                      setBusy(false);
                    }
                  }}
                  data-testid="qa-plan-copy"
                >
                  <Icon name="copy" /> {t("qa.plans.btn.newVersion")}
                </button>
              </>
            ) : null}
            {draft ? (
              <>
                <button type="button" className="btn" onClick={() => void save()} disabled={busy || !dirty} data-testid="qa-plan-save">
                  <Icon name="save" /> {t("qa.plans.btn.save")}
                </button>
                <button type="button" className="btn primary" onClick={() => setApproving(true)} disabled={busy || dirty || !p.characteristics.length} title={dirty ? t("qa.plans.attr.saveFirst") : !p.characteristics.length ? t("qa.plans.attr.needChar") : undefined} data-testid="qa-plan-approve">
                  <Icon name="check" /> {t("qa.plans.btn.approve")}
                </button>
              </>
            ) : null}
          </>
        ) : null
      }
    />
  ) : (
    <PageHeader
      title={t("qa.plans.str.newTitle")}
      description={t("qa.plans.str.newDesc")}
      actions={
        <button type="button" className="btn primary" onClick={() => void save()} disabled={busy || !form.item_id || !form.scheme_id || !form.name.trim()} data-testid="qa-plan-save">
          <Icon name="save" /> {t("qa.plans.btn.create")}
        </button>
      }
    />
  );
  return (
    <div className="col gap-lg" data-testid="qa-plan-page">
      <UnsavedChangesGuard when={dirty} what={t("qa.plans.str.thisPlan")} />
      {header}
      {p && p.status === "approved" ? <Banner tone="info" icon="lock">{t("qa.plans.text.approvedLocked")}</Banner> : null}
      {isConflict(error) ? <ConflictBanner onReload={() => (setError(null), rec.reload())} /> : <MfgError error={error} />}
      {p ? <RecordTabs label={t("qa.plans.aria.tabs")} value={tab} onChange={setTab} tabs={[{ key: "details", label: t("qa.shell.tab.details") }, { key: "chars", label: t("qa.plans.tab.chars"), count: form.characteristics.length, testId: "qa-tab-chars" }, ...standardTabs(p)]} /> : null}
      {tab === "details" || isNew ? (
        <TabPanel id="details">
          <FormErrors error={error}>
            <Section title={t("qa.plans.head.details")}>
              <div className="qa-form-grid">
                <TextField label={t("qa.plans.head.name")} name="name" value={form.name} onChange={(v) => set({ name: v })} disabled={!editable} required testId="qa-plan-name" />
                <div className="field span-2">
                  <ItemPicker label={t("qa.plans.head.item")} value={item} onChange={(i) => (setItem(i), set({ item_id: i.id }))} disabled={!editable} testId="qa-plan-item" />
                </div>
                <div className="field">
                  <label htmlFor="pl-scope">{t("qa.plans.head.scope")}</label>
                  <select id="pl-scope" className="select" value={form.scope} disabled={!editable} onChange={(e) => set({ scope: e.target.value as Scope, operation_seq: null, supplier_id: null, customer: null })}>
                    <option value="incoming">{t("qa.scope.incoming")}</option>
                    <option value="in_process">{t("qa.scope.inProcess")}</option>
                    <option value="final">{t("qa.scope.final")}</option>
                  </select>
                </div>
                {form.scope === "in_process" ? <TextField label={t("qa.plans.label.opSeq")} name="operation_seq" type="number" value={form.operation_seq === null ? "" : String(form.operation_seq)} onChange={(v) => set({ operation_seq: numOrNull(v) })} disabled={!editable} required hint={t("qa.plans.hint.opSeq")} /> : null}
                {form.scope === "incoming" ? (
                  <div className="field">
                    <label htmlFor="pl-sup">{t("qa.plans.label.supplier")}</label>
                    <select id="pl-sup" className="select" value={form.supplier_id ?? ""} disabled={!editable} onChange={(e) => set({ supplier_id: e.target.value || null })}>
                      <option value="">{t("qa.plans.str.anySupplier")}</option>
                      {suppliers.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}
                {form.scope === "final" ? <TextField label={t("qa.plans.label.customer")} name="customer" value={form.customer ?? ""} onChange={(v) => set({ customer: v.trim() ? v : null })} disabled={!editable} hint={t("qa.plans.hint.customer")} /> : null}
                <div className="field">
                  <label htmlFor="pl-scheme">{t("qa.plans.head.scheme")}</label>
                  <select id="pl-scheme" className="select" value={form.scheme_id} disabled={!editable} onChange={(e) => set({ scheme_id: e.target.value })} data-testid="qa-plan-scheme">
                    <option value="">{t("qa.plans.str.chooseScheme")}</option>
                    {(schemes.data?.items ?? []).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.code} {s.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="pl-level">{t("qa.plans.label.level")}</label>
                  <select id="pl-level" className="select" value={form.inspection_level} disabled={!editable} onChange={(e) => set({ inspection_level: e.target.value })}>
                    {LEVELS.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </select>
                </div>
                {SEVERITIES.map((s) => (
                  <TextField key={s} label={t("qa.plans.tpl.aqlFor", { s: t(sevKey(s)) })} value={form.aql[s]} onChange={(v) => set({ aql: { ...form.aql, [s]: v } })} disabled={!editable} />
                ))}
                <div className="field">
                  <label htmlFor="pl-eff">{t("qa.plans.head.effective")}</label>
                  <DateInput id="pl-eff" value={form.effective_from ?? ""} onChange={(v) => set({ effective_from: v || null })} disabled={!editable} />
                </div>
                <div className="field span-all">
                  <label htmlFor="pl-note">{t("qa.plans.label.note")}</label>
                  <textarea id="pl-note" className="textarea" rows={2} maxLength={500} value={form.note} disabled={!editable} onChange={(e) => set({ note: e.target.value })} />
                </div>
              </div>
            </Section>
          </FormErrors>
          {form.scheme_id ? <SamplingPreviewCard schemeId={form.scheme_id} level={form.inspection_level} aql={form.aql.major} /> : null}
        </TabPanel>
      ) : null}
      {p && tab === "chars" ? (
        <TabPanel id="chars">
          <CharGrid chars={form.characteristics} editable={editable} onChange={(c) => set({ characteristics: c })} />
          {editable ? (
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button type="button" className="btn primary" onClick={() => void save()} disabled={busy || !dirty} data-testid="qa-chars-save">
                <Icon name="save" /> {t("qa.plans.btn.save")}
              </button>
            </div>
          ) : null}
        </TabPanel>
      ) : null}
      {p && tab === "links" ? (
        <TabPanel id="links">
          <LinksTab links={p.links} fromType="inspection_plan" fromId={p.id} canEdit={false} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {p && tab === "attachments" ? (
        <TabPanel id="attachments">
          <AttachmentsTab attachments={p.attachments} entityType="inspection_plan" entityId={p.id} canEdit={canEdit} locked={!draft} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {p && tab === "history" ? (
        <TabPanel id="history">
          <HistoryTab entityType="inspection_plan" entityId={p.id} />
        </TabPanel>
      ) : null}
      {p && tab === "signatures" ? (
        <TabPanel id="signatures">
          <SignaturesTab signatures={p.signatures} recordType="inspection_plan" recordId={p.id} />
        </TabPanel>
      ) : null}
      {reason.dialog}
      {approving && p ? (
        <SignatureDialog<InspectionPlan>
          title={t("qa.plans.tpl.approveTitle", { n: `${p.number} v${p.version}` })}
          recordType="inspection_plan"
          recordId={p.id}
          recordLabel={`${p.number} v${p.version}`}
          action="approve"
          meaning="approved"
          submitLabel={t("qa.plans.btn.signApprove")}
          plainLabel={t("qa.plans.btn.approve")}
          effect={t("qa.plans.text.approveEffect")}
          perform={(sig, comment) => recordAction<InspectionPlan>("inspection_plan", p.id, "approve", { note: comment }, { version: p.row_version, signature: sig })}
          onDone={(res) => {
            toast(signedToast(res, t("qa.plans.toast.approved")));
            setApproving(false);
            if (res.status === 200) rec.setData(res.record);
            else rec.reload();
          }}
          onClose={() => setApproving(false)}
        />
      ) : null}
      {confirm && p ? (
        <ConfirmDialog
          title={confirm === "delete" ? t("qa.plans.tpl.deleteTitle", { n: p.number }) : t("qa.plans.tpl.obsoleteTitle", { n: p.number })}
          confirmLabel={confirm === "delete" ? t("qa.plans.btn.delete") : t("qa.plans.btn.obsolete")}
          danger
          busy={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={async () => {
            const r = await reason.ask(t("qa.plans.str.what", { n: p.number }));
            if (r === null) return;
            setBusy(true);
            try {
              if (confirm === "delete") {
                await deletePlan(p.id, p.row_version, r);
                toast(t("qa.plans.toast.deleted"));
                navigate(mfgPaths.qaPlans());
              } else {
                rec.setData(await obsoletePlan(p.id, p.row_version, r));
                toast(t("qa.plans.toast.obsolete"));
              }
              setConfirm(null);
            } catch (e) {
              setError(e);
              setConfirm(null);
            } finally {
              setBusy(false);
            }
          }}
        >
          {confirm === "delete" ? t("qa.plans.text.deleteBody") : t("qa.plans.text.obsoleteBody")}
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function SamplingPreviewCard({ schemeId, level, aql }: { schemeId: string; level: string; aql: string }) {
  const [size, setSize] = useState("3200");
  const ds = useDebounced(size, 300);
  const n = Number(ds);
  const pv = useLoad((s) => (n > 0 ? previewSampling(schemeId, { lot_size: n, level, aql }, s) : null), [schemeId, level, aql, ds]);
  return (
    <Section title={t("qa.plans.head.preview")}>
      <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
        <div className="field">
          <label htmlFor="pv-size">{t("qa.plans.label.lotSize")}</label>
          <input id="pv-size" className="input" inputMode="numeric" value={size} onChange={(e) => setSize(e.target.value.replace(/[^\d]/g, ""))} style={{ width: 120 }} />
        </div>
        <div className="qa-preview-line grow" data-testid="qa-sampling-preview" aria-live="polite">
          {pv.data
            ? pv.data.full
              ? t("qa.plans.tpl.previewFull", { size: formatNumber(pv.data.lot_size), level: pv.data.level, aql: pv.data.aql, n: formatNumber(pv.data.n), ac: pv.data.ac, re: pv.data.re })
              : t("qa.plans.tpl.preview", { size: formatNumber(pv.data.lot_size), level: pv.data.level, aql: pv.data.aql, n: formatNumber(pv.data.n), ac: pv.data.ac, re: pv.data.re })
            : pv.error
              ? t("qa.plans.str.previewNone")
              : "…"}
        </div>
      </div>
      <p className="small muted" style={{ margin: "8px 0 0" }}>
        {t("qa.plans.text.previewHint")}
      </p>
    </Section>
  );
}

const blankChar = (seq: number): CharacteristicInput => ({ seq, code: "", name: "", kind: "variable", severity: "major", unit: null, nominal: null, lsl: null, usl: null, method: "", equipment_class: null, sample_override: null, destructive: false });

function CharGrid({ chars, editable, onChange }: { chars: CharacteristicInput[]; editable: boolean; onChange(c: CharacteristicInput[]): void }) {
  const upd = (i: number, patch: Partial<CharacteristicInput>) => onChange(chars.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const numCell = (i: number, k: "lsl" | "nominal" | "usl", c: CharacteristicInput) => (
    <td>
      <input className="input qa-grid-input num" inputMode="decimal" aria-label={t(k === "lsl" ? "qa.plans.head.lsl" : k === "usl" ? "qa.plans.head.usl" : "qa.plans.head.nominal")} disabled={!editable || c.kind === "attribute"} value={c[k] === null ? "" : String(c[k])} onChange={(e) => upd(i, { [k]: numOrNull(e.target.value.replace(",", ".")) })} />
    </td>
  );
  return (
    <section className="card card-table" data-testid="qa-char-grid">
      <div className="card-header">
        <h2>{t("qa.plans.tab.chars")}</h2>
        {editable ? (
          <button type="button" className="btn sm" onClick={() => onChange([...chars, blankChar((chars.reduce((m, c) => Math.max(m, c.seq), 0) || 0) + 10)])} data-testid="qa-char-add">
            <Icon name="plus" /> {t("qa.plans.btn.addChar")}
          </button>
        ) : null}
      </div>
      <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
        <table className="table mfg-grid-table">
          <thead>
            <tr>
              <th style={{ width: 64 }}>{t("qa.plans.head.seq")}</th>
              <th style={{ width: 110 }}>{t("qa.plans.head.code")}</th>
              <th>{t("qa.plans.head.charName")}</th>
              <th style={{ width: 110 }}>{t("qa.plans.head.kind")}</th>
              <th style={{ width: 110 }}>{t("qa.plans.head.severity")}</th>
              <th style={{ width: 70 }}>{t("qa.plans.head.unit")}</th>
              <th style={{ width: 84 }} className="num">{t("qa.plans.head.lsl")}</th>
              <th style={{ width: 84 }} className="num">{t("qa.plans.head.nominal")}</th>
              <th style={{ width: 84 }} className="num">{t("qa.plans.head.usl")}</th>
              <th style={{ width: 110 }}>{t("qa.plans.head.gauge")}</th>
              <th>{t("qa.plans.head.method")}</th>
              <th style={{ width: 80 }}>{t("qa.plans.head.destructive")}</th>
              {editable ? <th style={{ width: 40 }}><span className="sr-only">{t("qa.plans.head.remove")}</span></th> : null}
            </tr>
          </thead>
          <tbody>
            {chars.map((c, i) => (
              <tr key={c.id ?? `n${i}`} data-testid="qa-char-row">
                <td>
                  <input className="input qa-grid-input num" inputMode="numeric" aria-label={t("qa.plans.head.seq")} disabled={!editable} value={String(c.seq)} onChange={(e) => upd(i, { seq: Number(e.target.value.replace(/\D/g, "")) || 0 })} />
                </td>
                <td>
                  <input className="input qa-grid-input mono" aria-label={t("qa.plans.head.code")} disabled={!editable} value={c.code} maxLength={32} onChange={(e) => upd(i, { code: e.target.value.toUpperCase() })} />
                </td>
                <td>
                  <input className="input qa-grid-input" aria-label={t("qa.plans.head.charName")} disabled={!editable} value={c.name} maxLength={200} onChange={(e) => upd(i, { name: e.target.value })} />
                </td>
                <td>
                  <select className="select qa-grid-input" aria-label={t("qa.plans.head.kind")} disabled={!editable} value={c.kind} onChange={(e) => upd(i, { kind: e.target.value as "variable", ...(e.target.value === "attribute" ? { lsl: null, usl: null, nominal: null, unit: null } : {}) })}>
                    <option value="variable">{t("qa.plans.str.variable")}</option>
                    <option value="attribute">{t("qa.plans.str.attribute")}</option>
                  </select>
                </td>
                <td>
                  <select className="select qa-grid-input" aria-label={t("qa.plans.head.severity")} disabled={!editable} value={c.severity} onChange={(e) => upd(i, { severity: e.target.value as Severity3 })}>
                    {SEVERITIES.map((s) => (
                      <option key={s} value={s}>
                        {t(sevKey(s))}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input className="input qa-grid-input" aria-label={t("qa.plans.head.unit")} disabled={!editable || c.kind === "attribute"} value={c.unit ?? ""} maxLength={16} onChange={(e) => upd(i, { unit: e.target.value || null })} />
                </td>
                {numCell(i, "lsl", c)}
                {numCell(i, "nominal", c)}
                {numCell(i, "usl", c)}
                <td>
                  <input className="input qa-grid-input mono" aria-label={t("qa.plans.head.gauge")} disabled={!editable} value={c.equipment_class ?? ""} maxLength={32} onChange={(e) => upd(i, { equipment_class: e.target.value.toUpperCase() || null })} />
                </td>
                <td>
                  <input className="input qa-grid-input" aria-label={t("qa.plans.head.method")} disabled={!editable} value={c.method} maxLength={500} onChange={(e) => upd(i, { method: e.target.value })} />
                </td>
                <td style={{ textAlign: "center" }}>
                  <input type="checkbox" aria-label={t("qa.plans.head.destructive")} disabled={!editable} checked={c.destructive} onChange={(e) => upd(i, { destructive: e.target.checked })} />
                </td>
                {editable ? (
                  <td>
                    <button type="button" className="btn ghost sm icon" aria-label={t("qa.plans.tpl.removeChar", { code: c.code || c.seq })} onClick={() => onChange(chars.filter((_, j) => j !== i))}>
                      <Icon name="trash" size={14} />
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
            {!chars.length ? (
              <tr>
                <td colSpan={13} className="muted">
                  {t("qa.plans.empty.chars")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- schemes
const KIND_LABEL: Record<SchemeKind, "qa.schemes.kind.fixed" | "qa.schemes.kind.percent" | "qa.schemes.kind.full" | "qa.schemes.kind.table"> = {
  fixed: "qa.schemes.kind.fixed",
  percent: "qa.schemes.kind.percent",
  full: "qa.schemes.kind.full",
  table: "qa.schemes.kind.table",
};
const kindText = (s: SamplingScheme) =>
  s.kind === "fixed" ? t("qa.schemes.tpl.fixed", { n: s.fixed_n ?? "" }) : s.kind === "percent" ? t("qa.schemes.tpl.percent", { p: formatNumber(s.percent) }) : t(KIND_LABEL[s.kind]);

export function SchemesPage() {
  const canEdit = useCan("qa_plan_edit");
  useEffect(() => {
    document.title = t("qa.schemes.str.docTitle");
  }, []);
  const columns = useMemo<Column<SamplingScheme>[]>(
    () => [
      {
        key: "code",
        header: t("qa.schemes.head.code"),
        width: "minmax(140px, 1fr)",
        exportValue: (s) => s.code,
        render: (s) => (
          <Link to={mfgPaths.qaScheme(s.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {s.code}
          </Link>
        ),
      },
      { key: "status", header: t("qa.plans.head.status"), width: "110px", exportValue: (s) => labelOf(DOC_STATUS, s.status), render: (s) => <DocStatusChip s={s.status} /> },
      { key: "name", header: t("qa.plans.head.name"), width: "minmax(200px, 2fr)", render: (s) => <span className="mfg-ellipsis">{s.name}</span> },
      { key: "kind", header: t("qa.schemes.head.kind"), width: "minmax(160px, 1fr)", exportValue: kindText, render: kindText },
      { key: "sw", header: t("qa.schemes.head.switching"), width: "120px", render: (s) => (s.switching ? t("qa.shell.str.yes") : t("qa.shell.str.no")) },
      { key: "note", header: t("qa.plans.label.note"), width: "minmax(160px, 1.5fr)", drop: 1, render: (s) => <span className="mfg-ellipsis muted">{s.note}</span> },
    ],
    [],
  );
  return (
    <QaWorklist<SamplingScheme>
      title={t("qa.schemes.title")}
      description={t("qa.schemes.desc")}
      actions={
        canEdit ? (
          <Link className="btn primary" to={mfgPaths.qaScheme("new")}>
            <Icon name="plus" /> {t("qa.schemes.btn.new")}
          </Link>
        ) : null
      }
      pageKey="qa-schemes"
      testId="qa-schemes-page"
      searchPlaceholder={t("qa.schemes.ph.search")}
      statusOptions={[
        { value: "", label: t("qa.list.status.all") },
        { value: "draft", label: t("qa.status.doc.draft") },
        { value: "approved", label: t("qa.status.doc.approved") },
        { value: "obsolete", label: t("qa.status.doc.obsolete") },
      ]}
      fetch={(q, signal) => {
        const { sort: _s, ...rest } = q;
        return listSchemes(rest, signal);
      }}
      columns={columns}
      card={{ title: "code", status: "status", fields: ["name", "kind"] }}
      rowKey={(s) => s.id}
      rowExtras={(s) => ({ testId: "qa-scheme-row", data: { status: s.status } })}
      rowPath={(s) => mfgPaths.qaScheme(s.id)}
      empty={t("qa.schemes.empty")}
      noun={t("qa.schemes.str.noun")}
    />
  );
}

const blankScheme = (): SchemeInput => ({ code: "", name: "", kind: "fixed", fixed_n: 5, percent: null, table: null, switching: false, note: "" });

export function SchemePage() {
  const { schemeId = "" } = useParams();
  const isNew = schemeId === "new";
  const navigate = useNavigate();
  const canEdit = useCan("qa_plan_edit");
  const reason = useChangeReason();
  const rec = useLoad((s) => (isNew ? null : getScheme(schemeId, s)), [schemeId]);
  const s = rec.data;
  const [form, setForm] = useState<SchemeInput>(blankScheme());
  const [tableText, setTableText] = useState("");
  const [tableErr, setTableErr] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [approving, setApproving] = useState(false);
  const [tab, setTab] = useState("details");
  useEffect(() => {
    if (s) {
      setForm({ code: s.code, name: s.name, kind: s.kind, fixed_n: s.fixed_n, percent: s.percent, table: s.table, switching: s.switching, note: s.note });
      setTableText(s.table ? JSON.stringify(s.table, null, 2) : "");
      setDirty(false);
      document.title = `${s.code} - ${t("qa.schemes.title")}`;
    }
  }, [s]);
  if (!isNew && rec.loading && !s) return <Spinner />;
  if (!isNew && !s) return <MfgError error={rec.error} onRetry={rec.reload} />;
  const draft = isNew || s?.status === "draft";
  const editable = draft && canEdit;
  const set = (patch: Partial<SchemeInput>) => {
    setForm((f) => ({ ...f, ...patch }));
    setDirty(true);
  };
  const body = (): SchemeInput | null => {
    if (form.kind !== "table") return { ...form, table: null };
    try {
      const tbl = JSON.parse(tableText) as SchemeInput["table"];
      setTableErr(null);
      return { ...form, table: tbl };
    } catch (e) {
      setTableErr(t("qa.schemes.err.json", { msg: e instanceof Error ? e.message : String(e) }));
      return null;
    }
  };
  const save = async () => {
    const b = body();
    if (!b) return;
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        const c = await createScheme(b);
        toast(t("qa.schemes.toast.created", { code: c.code }));
        setDirty(false);
        navigate(mfgPaths.qaScheme(c.id), { replace: true });
      } else if (s) {
        const r = await reason.ask(s.code);
        if (r === null) return;
        rec.setData(await updateScheme(s.id, b, s.row_version, r));
        toast(t("qa.schemes.toast.saved"));
        setDirty(false);
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="col gap-lg" data-testid="qa-scheme-page">
      <UnsavedChangesGuard when={dirty} what={t("qa.schemes.str.thisScheme")} />
      {s ? (
        <RecordHeader
          crumbs={[[t("nav.mfg.section.qa-schemes"), mfgPaths.qaSchemes()]]}
          number={s.code}
          title={s.name}
          status={<DocStatusChip s={s.status} />}
          facts={[
            [t("qa.schemes.head.kind"), kindText(s)],
            [t("qa.schemes.head.switching"), s.switching ? t("qa.shell.str.yes") : t("qa.shell.str.no")],
            [t("qa.schemes.label.approved"), s.approved_at ? fmtDate(s.approved_at) : null],
          ]}
          actions={
            editable ? (
              <>
                <button
                  type="button"
                  className="btn ghost"
                  disabled={busy}
                  onClick={async () => {
                    const r = await reason.ask(s.code);
                    if (r === null) return;
                    try {
                      await deleteScheme(s.id, s.row_version, r);
                      toast(t("qa.schemes.toast.deleted"));
                      navigate(mfgPaths.qaSchemes());
                    } catch (e) {
                      setError(e);
                    }
                  }}
                >
                  <Icon name="trash" /> {t("qa.plans.btn.delete")}
                </button>
                <button type="button" className="btn" onClick={() => void save()} disabled={busy || !dirty}>
                  <Icon name="save" /> {t("qa.plans.btn.save")}
                </button>
                <button type="button" className="btn primary" onClick={() => setApproving(true)} disabled={busy || dirty} data-testid="qa-scheme-approve">
                  <Icon name="check" /> {t("qa.plans.btn.approve")}
                </button>
              </>
            ) : null
          }
        />
      ) : (
        <PageHeader
          title={t("qa.schemes.str.newTitle")}
          description={t("qa.schemes.desc")}
          actions={
            <button type="button" className="btn primary" onClick={() => void save()} disabled={busy || !form.code.trim() || !form.name.trim()}>
              <Icon name="save" /> {t("qa.plans.btn.create")}
            </button>
          }
        />
      )}
      {s?.note && /test only/i.test(s.note) ? <Banner tone="warn" title={t("qa.schemes.title.testOnly")}>{t("qa.schemes.text.testOnly")}</Banner> : null}
      {s && s.status !== "draft" ? <Banner tone="info" icon="lock">{t("qa.schemes.text.immutable")}</Banner> : null}
      <MfgError error={error} />
      {s ? <RecordTabs label={t("qa.schemes.aria.tabs")} value={tab} onChange={setTab} tabs={[{ key: "details", label: t("qa.shell.tab.details") }, { key: "history", label: t("qa.shell.tab.history") }, { key: "signatures", label: t("qa.shell.tab.signatures"), count: s.signatures.length }]} /> : null}
      {tab === "details" || isNew ? (
        <FormErrors error={error}>
          <Section title={t("qa.plans.head.details")}>
            <div className="qa-form-grid">
              <TextField label={t("qa.schemes.head.code")} name="code" value={form.code} onChange={(v) => set({ code: v.toUpperCase() })} disabled={!editable || !isNew} required maxLength={32} />
              <TextField label={t("qa.plans.head.name")} name="name" value={form.name} onChange={(v) => set({ name: v })} disabled={!editable} required />
              <div className="field">
                <label htmlFor="sc-kind">{t("qa.schemes.head.kind")}</label>
                <select id="sc-kind" className="select" value={form.kind} disabled={!editable} onChange={(e) => set({ kind: e.target.value as SchemeKind })}>
                  {(Object.keys(KIND_LABEL) as SchemeKind[]).map((k) => (
                    <option key={k} value={k}>
                      {t(KIND_LABEL[k])}
                    </option>
                  ))}
                </select>
              </div>
              {form.kind === "fixed" ? <TextField label={t("qa.schemes.label.fixedN")} name="fixed_n" type="number" value={form.fixed_n === null ? "" : String(form.fixed_n)} onChange={(v) => set({ fixed_n: numOrNull(v) })} disabled={!editable} required /> : null}
              {form.kind === "percent" ? <TextField label={t("qa.schemes.label.percent")} name="percent" type="number" value={form.percent === null ? "" : String(form.percent)} onChange={(v) => set({ percent: numOrNull(v) })} disabled={!editable} required /> : null}
              <label className="checkbox" style={{ alignSelf: "end" }}>
                <input type="checkbox" checked={form.switching} disabled={!editable || form.kind !== "table"} onChange={(e) => set({ switching: e.target.checked })} /> {t("qa.schemes.label.switching")}
              </label>
              <div className="field span-all">
                <label htmlFor="sc-note">{t("qa.plans.label.note")}</label>
                <input id="sc-note" className="input" value={form.note} maxLength={500} disabled={!editable} onChange={(e) => set({ note: e.target.value })} />
              </div>
            </div>
          </Section>
          {form.kind === "table" ? (
            <Section title={t("qa.schemes.head.table")}>
              <p className="small muted" style={{ marginTop: 0 }}>
                {t("qa.schemes.text.tableHint")}
              </p>
              {form.table ? <SchemeTableView table={form.table} /> : null}
              {editable ? (
                <div className="field" style={{ marginTop: 12 }}>
                  <label htmlFor="sc-json">{t("qa.schemes.label.json")}</label>
                  <textarea id="sc-json" className="textarea mono" rows={14} value={tableText} onChange={(e) => (setTableText(e.target.value), setDirty(true))} spellCheck={false} />
                  {tableErr ? <span className="field-error">{tableErr}</span> : null}
                </div>
              ) : null}
            </Section>
          ) : null}
        </FormErrors>
      ) : null}
      {s && tab === "history" ? <HistoryTab entityType="sampling_scheme" entityId={s.id} /> : null}
      {s && tab === "signatures" ? <SignaturesTab signatures={s.signatures} recordType="sampling_scheme" recordId={s.id} /> : null}
      {reason.dialog}
      {approving && s ? (
        <SignatureDialog<SamplingScheme>
          title={t("qa.schemes.tpl.approveTitle", { code: s.code })}
          recordType="sampling_scheme"
          recordId={s.id}
          recordLabel={s.code}
          action="approve"
          meaning="approved"
          submitLabel={t("qa.plans.btn.signApprove")}
          plainLabel={t("qa.plans.btn.approve")}
          effect={t("qa.schemes.text.approveEffect")}
          perform={(sig, comment) => recordAction<SamplingScheme>("sampling_scheme", s.id, "approve", { note: comment }, { version: s.row_version, signature: sig })}
          onDone={(res) => {
            toast(signedToast(res, t("qa.schemes.toast.approved")));
            setApproving(false);
            if (res.status === 200) rec.setData(res.record);
            else rec.reload();
          }}
          onClose={() => setApproving(false)}
        />
      ) : null}
    </div>
  );
}

/** Read-only view of a table scheme: code letters per lot size and the normal sampling plans. */
function SchemeTableView({ table }: { table: NonNullable<SchemeInput["table"]> }) {
  const normal = table.plans.normal ?? {};
  const letters = Object.keys(normal).sort();
  const aqls = [...new Set(letters.flatMap((l) => Object.keys(normal[l] ?? {})))].sort((a, b) => Number(a) - Number(b));
  return (
    <div className="grid-2">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t("qa.schemes.head.lotSize")}</th>
              {table.levels.map((l) => (
                <th key={l}>{l}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.lot_size_ranges.map((r, i) => (
              <tr key={i}>
                <td className="num">{r.max === null ? t("qa.schemes.tpl.rangeOpen", { min: formatNumber(r.min) }) : t("qa.schemes.tpl.range", { min: formatNumber(r.min), max: formatNumber(r.max) })}</td>
                {table.levels.map((l) => (
                  <td key={l} className="mono">
                    {r.letters[l] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t("qa.schemes.head.letter")}</th>
              {aqls.map((a) => (
                <th key={a} className="num">
                  {t("qa.schemes.tpl.aqlHead", { a })}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {letters.map((l) => (
              <tr key={l}>
                <td className="mono">{l}</td>
                {aqls.map((a) => {
                  const c = normal[l]?.[a];
                  return (
                    <td key={a} className="num">
                      {c ? t("qa.schemes.tpl.cell", { n: c.n, ac: c.ac, re: c.re }) : ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- QA settings
export function QaSettingsPage() {
  const canEdit = useCan("qa_plan_edit");
  const reason = useChangeReason();
  const rec = useLoad((s) => getQaSettings(s), []);
  const locs = useLoad((s) => listLocations({ active: true }, s).catch(() => null), []);
  const [form, setForm] = useState<QaSettingsInput | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    document.title = t("qa.settings.str.docTitle");
    if (rec.data) {
      const { row_version: _v, ...rest } = rec.data;
      setForm(rest);
      setDirty(false);
    }
  }, [rec.data]);
  if (rec.loading && !form) return <Spinner />;
  if (!form || !rec.data) return <MfgError error={rec.error} onRetry={rec.reload} />;
  const set = (patch: Partial<QaSettingsInput>) => {
    setForm({ ...form, ...patch });
    setDirty(true);
  };
  const cur: QaSettings = rec.data;
  const codes = form.defect_codes;
  const rules = form.reportability_rules;
  const updCode = (i: number, p: Partial<DefectCode>) => set({ defect_codes: codes.map((c, j) => (j === i ? { ...c, ...p } : c)) });
  const updRule = (i: number, p: Partial<ReportabilityRule>) => set({ reportability_rules: rules.map((c, j) => (j === i ? { ...c, ...p } : c)) });
  return (
    <div className="col gap-lg" data-testid="qa-settings-page">
      <UnsavedChangesGuard when={dirty} what={t("qa.settings.title")} />
      <PageHeader
        title={t("qa.settings.title")}
        description={t("qa.settings.desc")}
        actions={
          canEdit ? (
            <button
              type="button"
              className="btn primary"
              disabled={busy || !dirty}
              onClick={async () => {
                const r = await reason.ask(t("qa.settings.title"));
                if (r === null) return;
                setBusy(true);
                setError(null);
                try {
                  rec.setData(await updateQaSettings(form, cur.row_version, r));
                  toast(t("qa.settings.toast.saved"));
                } catch (e) {
                  setError(e);
                } finally {
                  setBusy(false);
                }
              }}
              data-testid="qa-settings-save"
            >
              <Icon name="save" /> {t("qa.plans.btn.save")}
            </button>
          ) : null
        }
      />
      {isConflict(error) ? <ConflictBanner onReload={rec.reload} /> : <MfgError error={error} />}
      <FormErrors error={error}>
        <Section title={t("qa.settings.head.general")}>
          <div className="qa-form-grid">
            <TextField label={t("qa.settings.label.incoming")} type="number" value={String(form.inspection_due_hours.incoming)} onChange={(v) => set({ inspection_due_hours: { ...form.inspection_due_hours, incoming: Number(v) || 1 } })} disabled={!canEdit} hint={t("qa.settings.hint.hours")} />
            <TextField label={t("qa.settings.label.inProcess")} type="number" value={String(form.inspection_due_hours.in_process)} onChange={(v) => set({ inspection_due_hours: { ...form.inspection_due_hours, in_process: Number(v) || 1 } })} disabled={!canEdit} hint={t("qa.settings.hint.hours")} />
            <TextField label={t("qa.settings.label.final")} type="number" value={String(form.inspection_due_hours.final)} onChange={(v) => set({ inspection_due_hours: { ...form.inspection_due_hours, final: Number(v) || 1 } })} disabled={!canEdit} hint={t("qa.settings.hint.hours")} />
            <TextField label={t("qa.settings.label.calWarn")} name="cal_due_warning_days" type="number" value={String(form.cal_due_warning_days)} onChange={(v) => set({ cal_due_warning_days: Number(v) || 0 })} disabled={!canEdit} />
            <div className="field">
              <label htmlFor="qs-mrb">{t("qa.settings.label.mrb")}</label>
              <select id="qs-mrb" className="select" value={form.mrb_location_id ?? ""} disabled={!canEdit} onChange={(e) => set({ mrb_location_id: e.target.value || null })}>
                <option value="">{t("qa.settings.str.none")}</option>
                {(locs.data?.items ?? []).map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.code} {l.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="qs-final">{t("qa.settings.label.finalRole")}</label>
              <select id="qs-final" className="select" value={form.final_release_role} disabled={!canEdit} onChange={(e) => set({ final_release_role: e.target.value as QaSettingsInput["final_release_role"] })}>
                {(["qa_approver", "qa_engineer", "qa_inspector"] as const).map((r) => (
                  <option key={r} value={r}>
                    {roleText(r)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="qs-capa">{t("qa.settings.label.capaSor")}</label>
              <select id="qs-capa" className="select" value={form.capa_sor} disabled={!canEdit} onChange={(e) => set({ capa_sor: e.target.value as "superplanner" })}>
                <option value="superplanner">{t("qa.settings.str.here")}</option>
                <option value="external">{t("qa.settings.str.external")}</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="qs-cmp">{t("qa.settings.label.complaintSor")}</label>
              <select id="qs-cmp" className="select" value={form.complaint_sor} disabled={!canEdit} onChange={(e) => set({ complaint_sor: e.target.value as "superplanner" })}>
                <option value="superplanner">{t("qa.settings.str.here")}</option>
                <option value="external">{t("qa.settings.str.external")}</option>
              </select>
            </div>
          </div>
        </Section>
        <section className="card card-table">
          <div className="card-header">
            <h2>{t("qa.settings.head.defects")}</h2>
            {canEdit ? (
              <button type="button" className="btn sm" onClick={() => set({ defect_codes: [...codes, { code: "", name: "", severity: "major" }] })}>
                <Icon name="plus" /> {t("qa.settings.btn.addCode")}
              </button>
            ) : null}
          </div>
          <table className="table mfg-grid-table">
            <thead>
              <tr>
                <th style={{ width: 160 }}>{t("qa.plans.head.code")}</th>
                <th>{t("qa.plans.head.name")}</th>
                <th style={{ width: 140 }}>{t("qa.plans.head.severity")}</th>
                {canEdit ? <th style={{ width: 40 }}><span className="sr-only">{t("qa.plans.head.remove")}</span></th> : null}
              </tr>
            </thead>
            <tbody>
              {codes.map((c, i) => (
                <tr key={i}>
                  <td>
                    <input className="input qa-grid-input mono" aria-label={t("qa.plans.head.code")} value={c.code} disabled={!canEdit} maxLength={32} onChange={(e) => updCode(i, { code: e.target.value.toUpperCase() })} />
                  </td>
                  <td>
                    <input className="input qa-grid-input" aria-label={t("qa.plans.head.name")} value={c.name} disabled={!canEdit} maxLength={200} onChange={(e) => updCode(i, { name: e.target.value })} />
                  </td>
                  <td>
                    <select className="select qa-grid-input" aria-label={t("qa.plans.head.severity")} value={c.severity} disabled={!canEdit} onChange={(e) => updCode(i, { severity: e.target.value as Severity3 })}>
                      {SEVERITIES.map((s) => (
                        <option key={s} value={s}>
                          {t(sevKey(s))}
                        </option>
                      ))}
                    </select>
                  </td>
                  {canEdit ? (
                    <td>
                      <button type="button" className="btn ghost sm icon" aria-label={t("qa.plans.tpl.removeChar", { code: c.code })} onClick={() => set({ defect_codes: codes.filter((_, j) => j !== i) })}>
                        <Icon name="trash" size={14} />
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
              {!codes.length ? (
                <tr>
                  <td colSpan={4} className="muted">
                    {t("qa.settings.empty.codes")}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </section>
        <section className="card card-table">
          <div className="card-header">
            <h2>{t("qa.settings.head.reportability")}</h2>
            {canEdit ? (
              <button type="button" className="btn sm" onClick={() => set({ reportability_rules: [...rules, { regime: "", event_type: "all", days: 30 }] })}>
                <Icon name="plus" /> {t("qa.settings.btn.addRule")}
              </button>
            ) : null}
          </div>
          <table className="table mfg-grid-table">
            <thead>
              <tr>
                <th style={{ width: 180 }}>{t("qa.settings.head.regime")}</th>
                <th>{t("qa.settings.head.eventType")}</th>
                <th style={{ width: 120 }} className="num">{t("qa.settings.head.days")}</th>
                {canEdit ? <th style={{ width: 40 }}><span className="sr-only">{t("qa.plans.head.remove")}</span></th> : null}
              </tr>
            </thead>
            <tbody>
              {rules.map((r, i) => (
                <tr key={i}>
                  <td>
                    <input className="input qa-grid-input mono" aria-label={t("qa.settings.head.regime")} value={r.regime} disabled={!canEdit} onChange={(e) => updRule(i, { regime: e.target.value.toLowerCase() })} />
                  </td>
                  <td>
                    <select className="select qa-grid-input" aria-label={t("qa.settings.head.eventType")} value={r.event_type} disabled={!canEdit} onChange={(e) => updRule(i, { event_type: e.target.value as ReportabilityRule["event_type"] })}>
                      {(["all", "death", "serious_injury", "malfunction", "other"] as const).map((x) => (
                        <option key={x} value={x}>
                          {t(`qa.event.${x}` as "qa.event.all")}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input className="input qa-grid-input num" aria-label={t("qa.settings.head.days")} inputMode="numeric" value={String(r.days)} disabled={!canEdit} onChange={(e) => updRule(i, { days: Number(e.target.value.replace(/\D/g, "")) || 0 })} />
                  </td>
                  {canEdit ? (
                    <td>
                      <button type="button" className="btn ghost sm icon" aria-label={t("qa.settings.tpl.removeRule", { n: i + 1 })} onClick={() => set({ reportability_rules: rules.filter((_, j) => j !== i) })}>
                        <Icon name="trash" size={14} />
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted" style={{ margin: "8px 16px" }}>
            {t("qa.settings.text.reportability")}
          </p>
        </section>
      </FormErrors>
      {reason.dialog}
    </div>
  );
}
