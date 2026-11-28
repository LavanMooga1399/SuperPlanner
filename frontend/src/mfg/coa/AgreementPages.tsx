/**
 * Customer quality agreements (M10 6, 11): `/mfg/quality/agreements` list and `/mfg/quality/agreements/:id` editor.
 * An agreement decides what a certificate of analysis reports for a customer (characteristics taken from the final
 * inspection plans, optionally with the customer's own limits), the statement (English / French) and which documents a
 * batch pack contains. Approval is signed; an approved agreement changes only through a new version. The record page
 * also lists its certificates and starts a CoA or a batch pack for released lots.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Banner } from "../../components/Banner";
import { DateInput } from "../../components/DateInput";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { UnsavedChangesGuard } from "../../components/UnsavedChangesGuard";
import { t } from "../../lib/i18n";
import { formatDateTime, formatDay } from "../../lib/locale";
import { listPlans } from "../api/clientM7";
import { approveAgreement, createAgreement, createBatchPack, createCoa, getAgreement, listAgreements, listCoas, newAgreementVersion, updateAgreement } from "../api/clientM10";
import { PACK_DOCS, type Agreement, type AgreementInput, type Coa, type CoaCharacteristic, type CoaReport } from "../api/typesM10";
import { DataTable } from "../components/DataTable";
import { MfgError, Spinner } from "../components/Feedback";
import { FormErrors } from "../components/Field";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { needsText, useCan } from "../lib/permissions";
import { errorCode, useLoad } from "../lib/useMfg";
import { HistoryTab, RecordHeader, RecordTabs, Section, SignatureList, TabPanel, useChangeReason } from "../qa/RecordShell";
import { QaWorklist } from "../qa/Worklist";
import { LotListPicker, ItemListPicker, type LotRef } from "../dhr/pickers";
import { chipText, codeText10, DOC_STATE, DocChip } from "../dhr/shared";
import { specText } from "./CoaPages";

// ---------------------------------------------------------------- list
export function AgreementsPage() {
  const canEdit = useCan("coa_edit");
  useEffect(() => {
    document.title = t("gxp.agr.title");
  }, []);
  const columns = useMemo<Column<Agreement>[]>(
    () => [
      {
        key: "number",
        header: t("gxp.agr.head.number"),
        width: "150px",
        exportValue: (a) => `${a.number} v${a.version}`,
        render: (a) => (
          <Link to={mfgPaths.agreement(a.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {a.number} <span className="muted">{t("gxp.tpl.version", { n: a.version })}</span>
          </Link>
        ),
      },
      { key: "status", header: t("gxp.head.status"), width: "130px", exportValue: (a) => chipText(DOC_STATE, a.status), render: (a) => <DocChip s={a.status} /> },
      { key: "customer", header: t("gxp.agr.head.customer"), width: "160px", render: (a) => a.customer },
      { key: "title", header: t("gxp.agr.head.title"), width: "minmax(200px, 2fr)", render: (a) => <span className="mfg-ellipsis">{a.title}</span> },
      { key: "chars", header: t("gxp.agr.head.chars"), width: "120px", align: "right", exportValue: (a) => a.coa.characteristics.length, render: (a) => <span className="pl-num">{a.coa.characteristics.length}</span> },
      { key: "ref", header: t("gxp.agr.head.ref"), width: "140px", drop: 1, render: (a) => (a.external_ref ? <span className="mono">{a.external_ref}</span> : <span className="faint">–</span>) },
      { key: "eff", header: t("gxp.agr.head.effective"), width: "130px", drop: 2, render: (a) => (a.effective_from ? formatDay(a.effective_from) : <span className="faint">–</span>) },
    ],
    [],
  );
  return (
    <QaWorklist<Agreement>
      title={t("gxp.agr.title")}
      description={t("gxp.agr.desc")}
      actions={
        <span className="row" style={{ gap: 8 }}>
          <Link className="btn" to={mfgPaths.coas()}>
            <Icon name="file" /> {t("gxp.nav.coa")}
          </Link>
          <Link className="btn" to={mfgPaths.batchPacks()}>
            <Icon name="box" /> {t("gxp.nav.packs")}
          </Link>
          {canEdit ? (
            <Link className="btn primary" to={mfgPaths.agreement("new")} data-testid="agr-new">
              <Icon name="plus" /> {t("gxp.agr.btn.new")}
            </Link>
          ) : null}
        </span>
      }
      pageKey="agreements"
      testId="agreements-page"
      statusOptions={[{ value: "", label: t("gxp.list.any") }, ...(["draft", "approved", "obsolete"] as const).map((s) => ({ value: s, label: chipText(DOC_STATE, s) }))]}
      fetch={(q, signal) => listAgreements(q, signal)}
      columns={columns}
      card={{ title: "number", status: "status", fields: ["customer", "title"] }}
      rowKey={(a) => a.id}
      rowExtras={(a) => ({ testId: "agr-row", data: { status: a.status } })}
      rowPath={(a) => mfgPaths.agreement(a.id)}
      empty={t("gxp.agr.empty")}
      noun={t("gxp.agr.noun")}
    />
  );
}

// ---------------------------------------------------------------- record
const blank = (): AgreementInput => ({
  customer: "",
  title: "",
  external_ref: "",
  item_ids: [],
  coa: { characteristics: [], statement: "", statement_fr: "", language: "en" },
  pack: { documents: ["coa", "coc"], per: "lot" },
  effective_from: null,
});
const toInput = (a: Agreement): AgreementInput => ({ customer: a.customer, title: a.title, external_ref: a.external_ref, item_ids: a.item_ids, coa: a.coa, pack: a.pack, effective_from: a.effective_from });

export function AgreementPage() {
  const { agreementId = "" } = useParams();
  const isNew = agreementId === "new";
  const navigate = useNavigate();
  const canEdit = useCan("coa_edit");
  const reason = useChangeReason();
  const rec = useLoad((s) => (isNew ? null : getAgreement(agreementId, s)), [agreementId]);
  const a = rec.data;
  const [form, setForm] = useState<AgreementInput>(blank);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("details");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sign, setSign] = useState(false);
  const [picker, setPicker] = useState(false);
  const [start, setStart] = useState<null | "coa" | "pack">(null);
  useEffect(() => {
    if (a) {
      setForm(toInput(a));
      setDirty(false);
      document.title = `${a.number} - ${t("gxp.agr.title")}`;
    } else if (isNew) document.title = t("gxp.agr.newTitle");
  }, [a, isNew]);
  if (!isNew && !a) return rec.error ? <MfgError error={rec.error} onRetry={rec.reload} /> : <Spinner />;
  const editable = canEdit && (isNew || a?.status === "draft");
  const set = (p: Partial<AgreementInput>) => (setForm((f) => ({ ...f, ...p })), setDirty(true));
  const setCoa = (p: Partial<AgreementInput["coa"]>) => set({ coa: { ...form.coa, ...p } });
  const setChar = (i: number, p: Partial<CoaCharacteristic>) => setCoa({ characteristics: form.coa.characteristics.map((c, j) => (j === i ? { ...c, ...p } : c)) });
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        const x = await createAgreement(form);
        setDirty(false);
        navigate(mfgPaths.agreement(x.id), { replace: true });
      } else if (a) {
        const why = await reason.ask(a.number);
        if (why === null) return;
        rec.setData(await updateAgreement(a, form, why));
        setDirty(false);
        toast(t("gxp.toast.saved"));
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const valid = Boolean(form.customer.trim() && form.title.trim());
  return (
    <div className="col gap-lg" data-testid="agreement-page" data-status={a?.status ?? "new"}>
      <UnsavedChangesGuard when={dirty} />
      <RecordHeader
        crumbs={[[t("gxp.agr.title"), mfgPaths.agreements()]]}
        number={a ? `${a.number} v${a.version}` : t("gxp.agr.newNumber")}
        title={a ? `${a.customer} · ${a.title}` : null}
        status={a ? <DocChip s={a.status} /> : null}
        facts={a ? [[t("gxp.agr.head.ref"), a.external_ref || null], [t("gxp.agr.head.effective"), a.effective_from ? formatDay(a.effective_from) : null], [t("gxp.agr.fact.updated"), formatDateTime(a.updated_at)]] : []}
        actions={
          <>
            {a && a.status === "approved" && canEdit ? (
              <>
                <button type="button" className="btn" onClick={() => setStart("pack")} data-testid="agr-pack">
                  <Icon name="box" /> {t("gxp.agr.btn.pack")}
                </button>
                <button type="button" className="btn" onClick={() => setStart("coa")} data-testid="agr-coa">
                  <Icon name="file" /> {t("gxp.agr.btn.coa")}
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() =>
                    newAgreementVersion(a).then(
                      (x) => navigate(mfgPaths.agreement(x.id)),
                      (e: unknown) => setError(e),
                    )
                  }
                  data-testid="agr-new-version"
                >
                  <Icon name="copy" /> {t("gxp.btn.newVersion")}
                </button>
              </>
            ) : null}
            {editable ? (
              <button type="button" className={`btn${isNew || dirty ? " primary" : ""}`} disabled={busy || !valid || (!isNew && !dirty)} onClick={() => void save()} data-testid="agr-save">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {isNew ? t("gxp.agr.btn.create") : t("gxp.btn.save")}
              </button>
            ) : null}
            {a && a.status === "draft" && !dirty ? (
              <button type="button" className="btn primary" disabled={!a.coa.characteristics.length} title={a.coa.characteristics.length ? undefined : t("gxp.agr.needChars")} onClick={() => setSign(true)} data-testid="agr-approve">
                <Icon name="lock" /> {t("gxp.agr.btn.approve")}
              </button>
            ) : null}
          </>
        }
      />
      {a && a.status === "approved" ? <Banner tone="info">{t("gxp.agr.approvedLocked")}</Banner> : null}
      {a ? (
        <RecordTabs
          label={t("gxp.agr.aria.tabs")}
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "details", label: t("gxp.tab.details") },
            { key: "coas", label: t("gxp.nav.coa") },
            { key: "signatures", label: t("gxp.dhr.nav.signatures"), count: a.signatures.length },
            { key: "history", label: t("gxp.dhr.nav.history") },
          ]}
        />
      ) : null}
      {tab === "details" || isNew ? (
        <TabPanel id="details">
          <FormErrors error={error}>
            <MfgError error={error} />
            <Section title={t("gxp.agr.sec.customer")}>
              <div className="qa-form-grid">
                <div className="field">
                  <label htmlFor="agr-cust">
                    {t("gxp.agr.head.customer")} <span className="req" aria-hidden />
                  </label>
                  <input id="agr-cust" name="customer" className="input" maxLength={100} value={form.customer} disabled={!editable} onChange={(e) => set({ customer: e.target.value })} data-testid="agr-customer" />
                </div>
                <div className="field" style={{ gridColumn: "span 2" }}>
                  <label htmlFor="agr-title">
                    {t("gxp.agr.head.title")} <span className="req" aria-hidden />
                  </label>
                  <input id="agr-title" name="title" className="input" maxLength={200} value={form.title} disabled={!editable} onChange={(e) => set({ title: e.target.value })} data-testid="agr-title" />
                </div>
                <div className="field">
                  <label htmlFor="agr-ref">{t("gxp.agr.head.ref")}</label>
                  <input id="agr-ref" name="external_ref" className="input mono" maxLength={64} value={form.external_ref} disabled={!editable} onChange={(e) => set({ external_ref: e.target.value })} />
                  <span className="hint">{t("gxp.agr.hint.ref")}</span>
                </div>
                <div className="field">
                  <label htmlFor="agr-eff">{t("gxp.agr.head.effective")}</label>
                  <DateInput id="agr-eff" value={form.effective_from ?? ""} onChange={(v) => set({ effective_from: v || null })} disabled={!editable} />
                </div>
              </div>
              <div style={{ marginTop: 12 }}>
                <ItemListPicker ids={form.item_ids} onChange={(ids) => set({ item_ids: ids })} label={t("gxp.agr.label.items")} disabled={!editable} testId="agr-items" />
              </div>
            </Section>
            <Section
              title={t("gxp.agr.sec.coa")}
              flush
              actions={
                editable ? (
                  <>
                    <button type="button" className="btn sm" disabled={!form.item_ids.length} title={form.item_ids.length ? undefined : t("gxp.agr.needItems")} onClick={() => setPicker(true)} data-testid="agr-from-plans">
                      <Icon name="list" /> {t("gxp.agr.btn.fromPlans")}
                    </button>
                    <button type="button" className="btn sm" onClick={() => setCoa({ characteristics: [...form.coa.characteristics, { item_id: null, code: "", label: "", label_fr: "", report: "value", spec: null }] })}>
                      <Icon name="plus" /> {t("gxp.agr.btn.addChar")}
                    </button>
                  </>
                ) : null
              }
            >
              <div className="table-wrap" style={{ border: 0 }}>
                <table className="table" data-testid="agr-chars">
                  <thead>
                    <tr>
                      <th scope="col">{t("gxp.agr.head.code")}</th>
                      <th scope="col">{t("gxp.agr.head.label")}</th>
                      <th scope="col">{t("gxp.agr.head.labelFr")}</th>
                      <th scope="col">{t("gxp.agr.head.report")}</th>
                      <th scope="col">{t("gxp.agr.head.spec")}</th>
                      {editable ? <th scope="col"><span className="sr-only">{t("gxp.head.actions")}</span></th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {form.coa.characteristics.map((c, i) => (
                      <tr key={i}>
                        <td>
                          <input className="input sm mono" aria-label={t("gxp.agr.head.code")} value={c.code} maxLength={32} disabled={!editable} onChange={(e) => setChar(i, { code: e.target.value })} style={{ width: 90 }} />
                        </td>
                        <td>
                          <input className="input sm" aria-label={t("gxp.agr.head.label")} value={c.label} maxLength={200} disabled={!editable} onChange={(e) => setChar(i, { label: e.target.value })} />
                        </td>
                        <td>
                          <input className="input sm" aria-label={t("gxp.agr.head.labelFr")} value={c.label_fr} maxLength={200} disabled={!editable} onChange={(e) => setChar(i, { label_fr: e.target.value })} />
                        </td>
                        <td>
                          <select className="select sm" aria-label={t("gxp.agr.head.report")} value={c.report} disabled={!editable} onChange={(e) => setChar(i, { report: e.target.value as CoaReport })}>
                            {(["value", "summary", "pass"] as const).map((r) => (
                              <option key={r} value={r}>
                                {t(`gxp.agr.report.${r}`)}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <SpecCell c={c} editable={editable} onChange={(spec) => setChar(i, { spec })} />
                        </td>
                        {editable ? (
                          <td>
                            <button type="button" className="btn sm" aria-label={t("gxp.tpl.removeChar", { c: c.code || String(i + 1) })} onClick={() => setCoa({ characteristics: form.coa.characteristics.filter((_, j) => j !== i) })}>
                              <Icon name="trash" />
                            </button>
                          </td>
                        ) : null}
                      </tr>
                    ))}
                    {!form.coa.characteristics.length ? (
                      <tr>
                        <td colSpan={6} className="muted">
                          {t("gxp.agr.charsEmpty")}
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
              <div className="card-body col" style={{ gap: 10 }}>
                <div className="qa-form-grid">
                  <div className="field">
                    <label htmlFor="agr-lang">{t("gxp.agr.label.language")}</label>
                    <select id="agr-lang" className="select" value={form.coa.language} disabled={!editable} onChange={(e) => setCoa({ language: e.target.value as AgreementInput["coa"]["language"] })}>
                      {(["en", "fr", "en_fr"] as const).map((l) => (
                        <option key={l} value={l}>
                          {t(`gxp.agr.lang.${l}`)}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                {form.coa.language !== "fr" ? (
                  <div className="field">
                    <label htmlFor="agr-st">{t("gxp.agr.label.statement")}</label>
                    <textarea id="agr-st" className="textarea" rows={2} maxLength={2000} value={form.coa.statement} disabled={!editable} onChange={(e) => setCoa({ statement: e.target.value })} />
                  </div>
                ) : null}
                {form.coa.language !== "en" ? (
                  <div className="field">
                    <label htmlFor="agr-st-fr">{t("gxp.agr.label.statementFr")}</label>
                    <textarea id="agr-st-fr" className="textarea" rows={2} maxLength={2000} value={form.coa.statement_fr} disabled={!editable} onChange={(e) => setCoa({ statement_fr: e.target.value })} lang="fr" />
                  </div>
                ) : null}
              </div>
            </Section>
            <Section title={t("gxp.agr.sec.pack")}>
              <fieldset className="popover-group" disabled={!editable}>
                <legend className="sr-only">{t("gxp.agr.sec.pack")}</legend>
                <div className="qa-role-checks" data-testid="agr-pack-docs">
                  {PACK_DOCS.map((doc) => (
                    <label key={doc} className="row" style={{ gap: 6 }}>
                      <input type="checkbox" checked={form.pack.documents.includes(doc)} onChange={(e) => set({ pack: { ...form.pack, documents: e.target.checked ? [...form.pack.documents, doc] : form.pack.documents.filter((x) => x !== doc) } })} />
                      {t(`gxp.doc.kind.${doc}`)}
                    </label>
                  ))}
                </div>
              </fieldset>
              <div className="field" style={{ marginTop: 12, maxWidth: 260 }}>
                <label htmlFor="agr-per">{t("gxp.agr.label.per")}</label>
                <select id="agr-per" className="select" value={form.pack.per} disabled={!editable} onChange={(e) => set({ pack: { ...form.pack, per: e.target.value as "lot" | "shipment" } })}>
                  <option value="lot">{t("gxp.agr.per.lot")}</option>
                  <option value="shipment">{t("gxp.agr.per.shipment")}</option>
                </select>
              </div>
            </Section>
          </FormErrors>
        </TabPanel>
      ) : tab === "coas" && a ? (
        <TabPanel id="coas">
          <AgreementCoas agreement={a} />
        </TabPanel>
      ) : tab === "signatures" && a ? (
        <TabPanel id="signatures">
          <Section title={t("gxp.dhr.nav.signatures")}>
            <SignatureList signatures={a.signatures} />
          </Section>
        </TabPanel>
      ) : a ? (
        <TabPanel id="history">
          <HistoryTab entityType="qa_customer_agreement" entityId={a.id} />
        </TabPanel>
      ) : null}
      {reason.dialog}
      {picker ? (
        <PlanCharsDialog
          itemIds={form.item_ids}
          existing={form.coa.characteristics.map((c) => c.code)}
          onClose={() => setPicker(false)}
          onAdd={(cs) => {
            setCoa({ characteristics: [...form.coa.characteristics, ...cs] });
            setPicker(false);
          }}
        />
      ) : null}
      {sign && a ? (
        <SignatureDialog<Agreement>
          title={t("gxp.tpl.approveAgr", { n: `${a.number} v${a.version}` })}
          recordType="customer_agreement"
          recordId={a.id}
          recordLabel={`${a.number} v${a.version}`}
          action="approve"
          submitLabel={t("gxp.agr.btn.signApprove")}
          plainLabel={t("gxp.agr.btn.approve")}
          effect={t("gxp.agr.approveEffect")}
          extraRows={[
            { label: t("gxp.agr.head.customer"), value: a.customer },
            { label: t("gxp.agr.head.chars"), value: a.coa.characteristics.map((c) => c.code).join(", ") },
            { label: t("gxp.agr.sec.pack"), value: a.pack.documents.map((d) => t(`gxp.doc.kind.${d}`)).join(", ") },
          ]}
          perform={(sig, comment) => approveAgreement(a, sig, comment)}
          onDone={(res) => {
            toast(signedToast(res, t("gxp.tpl.agrApproved", { n: a.number })));
            setSign(false);
            rec.reload();
          }}
          onClose={() => setSign(false)}
        />
      ) : null}
      {start && a ? <StartDialog agreement={a} kind={start} onClose={() => setStart(null)} /> : null}
      {!canEdit && isNew ? <Banner tone="warn">{needsText("coa_edit")}</Banner> : null}
    </div>
  );
}

function SpecCell({ c, editable, onChange }: { c: CoaCharacteristic; editable: boolean; onChange(s: CoaCharacteristic["spec"]): void }) {
  if (!c.spec)
    return (
      <span className="row" style={{ gap: 6 }}>
        <span className="small muted">{t("gxp.agr.specFromPlan")}</span>
        {editable ? (
          <button type="button" className="btn link sm" onClick={() => onChange({ nominal: null, lsl: null, usl: null, unit: "" })}>
            {t("gxp.agr.btn.override")}
          </button>
        ) : null}
      </span>
    );
  if (!editable) return <span className="small">{specText(c.spec)}</span>;
  const n = (v: string) => (v === "" ? null : Number(v));
  const s = c.spec;
  return (
    <span className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
      <input className="input sm" type="number" aria-label={t("gxp.agr.lsl")} placeholder={t("gxp.agr.lsl")} value={s.lsl ?? ""} onChange={(e) => onChange({ ...s, lsl: n(e.target.value) })} style={{ width: 70 }} />
      <input className="input sm" type="number" aria-label={t("gxp.agr.usl")} placeholder={t("gxp.agr.usl")} value={s.usl ?? ""} onChange={(e) => onChange({ ...s, usl: n(e.target.value) })} style={{ width: 70 }} />
      <input className="input sm" aria-label={t("gxp.agr.unit")} placeholder={t("gxp.agr.unit")} value={s.unit} maxLength={16} onChange={(e) => onChange({ ...s, unit: e.target.value })} style={{ width: 56 }} />
      <button type="button" className="btn sm" aria-label={t("gxp.agr.btn.usePlan")} title={t("gxp.agr.btn.usePlan")} onClick={() => onChange(null)}>
        <Icon name="x" size={12} />
      </button>
    </span>
  );
}

function PlanCharsDialog({ itemIds, existing, onClose, onAdd }: { itemIds: string[]; existing: string[]; onClose(): void; onAdd(c: CoaCharacteristic[]): void }) {
  const plans = useLoad((s) => Promise.all(itemIds.map((id) => listPlans({ item_id: id, scope: "final", status: "approved", limit: 20 }, s))), [itemIds.join(",")]);
  const rows = (plans.data ?? []).flatMap((p) => p.items.flatMap((pl) => pl.characteristics.map((c) => ({ plan: pl, c }))));
  const [sel, setSel] = useState<Set<string>>(new Set());
  const key = (r: (typeof rows)[number]) => `${r.plan.id}:${r.c.code}`;
  return (
    <Dialog
      title={t("gxp.agr.dlg.plansTitle")}
      wide
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={!sel.size}
            onClick={() => onAdd(rows.filter((r) => sel.has(key(r))).map((r) => ({ item_id: r.plan.item_id, code: r.c.code, label: r.c.name, label_fr: "", report: r.c.kind === "variable" ? "value" : "summary", spec: null })))}
            data-testid="agr-plans-add"
          >
            {t("gxp.tpl.addN", { n: sel.size })}
          </button>
        </>
      }
    >
      <MfgError error={plans.error} />
      {plans.loading ? <Spinner /> : null}
      {!plans.loading && !rows.length ? <p className="muted">{t("gxp.agr.noPlans")}</p> : null}
      <ul className="col" style={{ listStyle: "none", margin: 0, padding: 0, gap: 4 }}>
        {rows.map((r) => (
          <li key={key(r)}>
            <label className="row" style={{ gap: 8 }}>
              <input type="checkbox" disabled={existing.includes(r.c.code)} checked={sel.has(key(r))} onChange={(e) => setSel((s) => { const n = new Set(s); if (e.target.checked) n.add(key(r)); else n.delete(key(r)); return n; })} />
              <span className="mono">{r.c.code}</span> {r.c.name} <span className="muted small">{r.plan.number} · {specText({ lsl: r.c.lsl, usl: r.c.usl, nominal: r.c.nominal, unit: r.c.unit ?? "" })}</span>
              {existing.includes(r.c.code) ? <span className="badge info">{t("gxp.agr.already")}</span> : null}
            </label>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}

function AgreementCoas({ agreement }: { agreement: Agreement }) {
  const coas = useLoad((s) => listCoas({ agreement_id: agreement.id, limit: 200 }, s), [agreement.id]);
  const navigate = useNavigate();
  const columns = useMemo<Column<Coa>[]>(
    () => [
      { key: "number", header: t("gxp.coa.head.number"), width: "130px", render: (c) => <Link className="mono" to={mfgPaths.coa(c.id)}>{c.number}</Link> },
      { key: "status", header: t("gxp.head.status"), width: "120px", render: (c) => <DocChip s={c.status} /> },
      { key: "lot", header: t("gxp.head.lot"), width: "140px", render: (c) => <span className="mono">{c.lot_code ?? c.lot_id}</span> },
      { key: "dhr", header: t("gxp.coa.head.dhr"), width: "140px", render: (c) => <Link className="mono" to={mfgPaths.dhrRecord(c.dhr_id)}>{c.dhr_number ?? c.dhr_id}</Link> },
      { key: "created", header: t("gxp.dev.head.created"), width: "160px", render: (c) => formatDateTime(c.created_at) },
    ],
    [],
  );
  return (
    <section className="card card-table">
      <MfgError error={coas.error} />
      <DataTable<Coa> rows={coas.data?.items ?? []} columns={columns} rowKey={(c) => c.id} label={t("gxp.nav.coa")} loading={coas.loading} onRowClick={(c) => navigate(mfgPaths.coa(c.id))} empty={t("gxp.coa.emptyAgreement")} exportName="agreement-coas" />
    </section>
  );
}

/** Start a CoA (one lot) or a batch pack (one or more lots) under an approved agreement. */
export function StartDialog({ agreement, kind, onClose }: { agreement: Agreement; kind: "coa" | "pack"; onClose(): void }) {
  const navigate = useNavigate();
  const [lots, setLots] = useState<LotRef[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (kind === "coa") navigate(mfgPaths.coa((await createCoa({ lot_id: lots[0].id, agreement_id: agreement.id })).id));
      else navigate(mfgPaths.batchPack((await createBatchPack({ agreement_id: agreement.id, lot_ids: lots.map((l) => l.id) })).id));
    } catch (e) {
      setErr(e);
      setBusy(false);
    }
  };
  const code = errorCode(err);
  return (
    <Dialog
      title={kind === "coa" ? t("gxp.tpl.coaFor", { c: agreement.customer }) : t("gxp.tpl.packFor", { c: agreement.customer })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button type="button" className="btn primary" disabled={busy || !lots.length || (kind === "coa" && lots.length !== 1)} onClick={() => void go()} data-testid="agr-start-go">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />} {kind === "coa" ? t("gxp.agr.btn.coa") : t("gxp.agr.btn.pack")}
          </button>
        </>
      }
    >
      <div className="col" style={{ gap: 10 }}>
        {code === "COA_DHR_NOT_RELEASED" || code === "COA_OUT_OF_SPEC" ? (
          <Banner tone="danger" role="alert" title={codeText10(code)}>
            {t(code === "COA_OUT_OF_SPEC" ? "gxp.coa.outOfSpecBody" : "gxp.coa.notReleasedBody")}
          </Banner>
        ) : (
          <MfgError error={err} />
        )}
        <p style={{ margin: 0 }}>{kind === "coa" ? t("gxp.agr.coaBody") : t("gxp.agr.packBody")}</p>
        <LotListPicker lots={kind === "coa" ? lots.slice(0, 1) : lots} onChange={(l) => setLots(kind === "coa" ? l.slice(-1) : l)} label={t("gxp.head.lot")} itemId={agreement.item_ids.length === 1 ? agreement.item_ids[0] : null} testId="agr-start-lots" />
      </div>
    </Dialog>
  );
}
