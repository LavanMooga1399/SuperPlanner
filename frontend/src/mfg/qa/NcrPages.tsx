/**
 * Nonconformance reports and material review (M7 6, 10): worklist, new NCR, and the NCR record - details,
 * dispositions (scrap, rework, use as is, return to supplier; quantities must add up to the nonconforming quantity),
 * signed approval (two steps by default: reviewed, approved), implementation that posts through the inventory ledger
 * and shop-floor log, and signed close. Material stays on hold until the dispositions are implemented.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { UnsavedChangesGuard } from "../../components/UnsavedChangesGuard";
import { listItemRoutings } from "../api/client";
import { listLocations, listLots } from "../api/clientM2";
import { createNcr, getNcr, getQaSettings, listNcrs, ncrStep, proposeNcr, recordAction, updateNcr } from "../api/clientM7";
import type { ItemRef } from "../api/types";
import type { DispositionInput, DispositionKind, Ncr, NcrInput, Severity3 } from "../api/typesM7";
import { ConflictBanner, MfgError, Spinner } from "../components/Feedback";
import { FormErrors, TextField } from "../components/Field";
import { ItemPicker } from "../components/ItemPicker";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { isConflict, useLoad } from "../lib/useMfg";
import { formatDateTime, formatNumber } from "../../lib/locale";
import { t, type StringKey } from "../../lib/i18n";
import { fmtQ, ItemCell, itemText, usePersonName, useSupplierName, useSuppliersList } from "./common";
import { DISPOSITION_LABEL, labelOf, NCR_STATUS, NcrStatusChip, SeverityChip } from "./labels";
import { AttachmentsTab, HistoryTab, LinksTab, NextStepBanner, RecordHeader, RecordTabs, Section, SignaturesTab, standardTabs, TabPanel, TextBlock, useChangeReason } from "./RecordShell";
import { QaWorklist } from "./Worklist";
import "./qa.css";

const SOURCE_KEYS: Record<string, StringKey> = {
  inspection: "qa.ncr.source.inspection",
  floor: "qa.ncr.source.floor",
  complaint: "qa.ncr.source.complaint",
  supplier: "qa.ncr.source.supplier",
  internal: "qa.ncr.source.internal",
  audit: "qa.ncr.source.audit",
};
const sourceText = (s: string) => (SOURCE_KEYS[s] ? t(SOURCE_KEYS[s]) : s);
const SEVS: Severity3[] = ["critical", "major", "minor"];
const sevKey = (s: string) => (s === "critical" ? "qa.severity.critical" : s === "major" ? "qa.severity.major" : "qa.severity.minor") as StringKey;

// ---------------------------------------------------------------- worklist
export function NcrsPage() {
  const canEdit = useCan("ncr_edit");
  useEffect(() => {
    document.title = t("qa.ncr.str.docTitle");
  }, []);
  const columns = useMemo<Column<Ncr>[]>(
    () => [
      {
        key: "number",
        header: t("qa.ncr.head.ncr"),
        width: "120px",
        sortKey: "number",
        sortKeyDesc: "-number",
        exportValue: (n) => n.number,
        render: (n) => (
          <Link to={mfgPaths.qaNcr(n.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {n.number}
          </Link>
        ),
      },
      { key: "status", header: t("qa.ncr.head.status"), width: "170px", exportValue: (n) => labelOf(NCR_STATUS, n.status), render: (n) => <NcrStatusChip s={n.status} /> },
      { key: "title", header: t("qa.ncr.head.title"), width: "minmax(200px, 2fr)", render: (n) => <span className="mfg-ellipsis">{n.title}</span> },
      { key: "sev", header: t("qa.ncr.head.severity"), width: "100px", exportValue: (n) => n.severity, render: (n) => <SeverityChip s={n.severity} /> },
      { key: "item", header: t("qa.lots.head.item"), width: "minmax(180px, 1.5fr)", exportValue: (n) => itemText(n.item), render: (n) => <ItemCell item={n.item} id={n.item_id} /> },
      { key: "qty", header: t("qa.ncr.head.qty"), width: "90px", align: "right", exportValue: (n) => n.qty_nc, render: (n) => fmtQ(n.qty_nc) },
      { key: "where", header: t("qa.ncr.head.place"), width: "minmax(120px, 1fr)", drop: 2, render: (n) => (n.place === "wip" ? t("qa.ncr.str.wip") : n.lot_code ? <span className="mono">{n.lot_code}</span> : t("qa.ncr.str.stock")) },
      { key: "src", header: t("qa.ncr.head.source"), width: "130px", drop: 1, render: (n) => sourceText(n.source) },
      { key: "created", header: t("qa.ncr.head.opened"), width: "150px", sortKey: "-created_at", render: (n) => formatDateTime(n.created_at) },
    ],
    [],
  );
  return (
    <QaWorklist<Ncr>
      title={t("qa.ncr.title")}
      description={t("qa.ncr.desc")}
      actions={
        canEdit ? (
          <Link className="btn primary" to={mfgPaths.qaNcr("new")} data-testid="ncr-new">
            <Icon name="plus" /> {t("qa.ncr.btn.new")}
          </Link>
        ) : null
      }
      pageKey="qa-ncrs"
      testId="qa-ncrs-page"
      searchPlaceholder={t("qa.ncr.ph.search")}
      views={[{ key: "review", label: t("qa.ncr.view.review"), query: { status: "proposed" } }]}
      statusOptions={[
        { value: "", label: t("qa.ncr.status.active") },
        ...(["draft", "open", "proposed", "approved", "implemented", "closed", "cancelled"] as const).map((s) => ({ value: s, label: labelOf(NCR_STATUS, s) })),
        { value: "all", label: t("qa.list.status.all") },
      ]}
      defaultStatus="draft,open,proposed,approved,implemented"
      filters={[{ param: "place", label: t("qa.ncr.head.place"), options: [{ value: "", label: t("qa.list.any") }, { value: "stock", label: t("qa.ncr.str.stock") }, { value: "wip", label: t("qa.ncr.str.wip") }] }]}
      fetch={(q, signal) => listNcrs({ ...q, status: q.status === "all" ? undefined : q.status }, signal)}
      columns={columns}
      card={{ title: "number", status: "status", fields: ["title", "item", "qty"] }}
      rowKey={(n) => n.id}
      rowExtras={(n) => ({ testId: "ncr-row", data: { status: n.status } })}
      rowPath={(n) => mfgPaths.qaNcr(n.id)}
      empty={t("qa.ncr.empty")}
      noun={t("qa.ncr.str.noun")}
    />
  );
}

// ---------------------------------------------------------------- record
const blank = (): NcrInput => ({
  title: "",
  source: "internal",
  severity: "major",
  item_id: null,
  lot_id: null,
  serial_ids: [],
  supplier_id: null,
  wo_id: null,
  complaint_id: null,
  location_id: null,
  place: "stock",
  qty_nc: 0,
  defect_codes: [],
  description: "",
  containment: "",
  investigation: "",
  capa_required: false,
  external_ref: null,
});
const toInput = (n: Ncr): NcrInput => ({
  title: n.title,
  source: n.source as NcrInput["source"],
  severity: n.severity,
  item_id: n.item_id,
  lot_id: n.lot_id,
  serial_ids: n.serial_ids,
  supplier_id: n.supplier_id,
  wo_id: n.wo_id,
  complaint_id: n.complaint_id,
  location_id: n.location_id,
  place: n.place,
  qty_nc: n.qty_nc,
  defect_codes: n.defect_codes,
  description: n.description,
  containment: n.containment,
  investigation: n.investigation,
  capa_required: n.capa_required,
  external_ref: n.external_ref,
});

type Sign = null | "approve" | "close" | "cancel";

export function NcrPage() {
  const { ncrId = "" } = useParams();
  const [params] = useSearchParams();
  const isNew = ncrId === "new";
  const navigate = useNavigate();
  const canEdit = useCan("ncr_edit");
  const canApprove = useCan("ncr_approve");
  const person = usePersonName();
  const supplier = useSupplierName();
  const suppliers = useSuppliersList();
  const reason = useChangeReason();
  const rec = useLoad((s) => (isNew ? null : getNcr(ncrId, s)), [ncrId]);
  const settings = useLoad((s) => getQaSettings(s).catch(() => null), []);
  const n = rec.data;
  const [form, setForm] = useState<NcrInput>(() => ({ ...blank(), complaint_id: params.get("complaint"), source: params.get("complaint") ? "complaint" : "internal" }));
  const [item, setItem] = useState<ItemRef | null>(null);
  const [lotCode, setLotCode] = useState("");
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("details");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sign, setSign] = useState<Sign>(null);
  const [implementing, setImplementing] = useState(false);
  const lots = useLoad((s) => (form.item_id && lotCode.trim().length >= 1 && !form.lot_id ? listLots({ item_id: form.item_id, q: lotCode.trim(), limit: 10 }, s) : null), [form.item_id, lotCode, form.lot_id]);
  useEffect(() => {
    if (n) {
      setForm(toInput(n));
      setItem(n.item ? ({ id: n.item.id, part_number: n.item.part_number, revision: n.item.revision, description: n.item.name, uom: "", make_buy: "buy", active: true } as ItemRef) : null);
      setLotCode(n.lot_code ?? "");
      setDirty(false);
      document.title = `${n.number} - ${t("qa.ncr.title")}`;
    } else if (isNew) document.title = t("qa.ncr.str.newDocTitle");
  }, [n, isNew]);
  if (!isNew && rec.loading && !n) return <Spinner />;
  if (!isNew && !n) return <MfgError error={rec.error} onRetry={rec.reload} />;
  const editable = canEdit && (isNew || n?.status === "draft" || n?.status === "open");
  const set = (p: Partial<NcrInput>) => {
    setForm((f) => ({ ...f, ...p }));
    setDirty(true);
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        const c = await createNcr(form);
        toast(t("qa.ncr.toast.created", { n: c.number }));
        setDirty(false);
        navigate(mfgPaths.qaNcr(c.id), { replace: true });
      } else if (n) {
        const r = await reason.ask(n.number);
        if (r === null) return;
        rec.setData(await updateNcr(n.id, form, n.row_version, r));
        setDirty(false);
        toast(t("qa.ncr.toast.saved"));
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const step = async (action: "open" | "implement") => {
    if (!n) return;
    const r = await reason.ask(n.number);
    if (r === null) return;
    setBusy(true);
    setError(null);
    try {
      rec.setData(await ncrStep(n.id, action, n.row_version, r));
      toast(action === "open" ? t("qa.ncr.toast.opened") : t("qa.ncr.toast.implemented"));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      setImplementing(false);
    }
  };
  const defectCodes = settings.data?.defect_codes ?? [];
  const form$ = (
    <FormErrors error={error}>
      <Section title={t("qa.ncr.head.what")}>
        <div className="qa-form-grid">
          <div className="span-2">
            <TextField label={t("qa.ncr.head.title")} name="title" value={form.title} onChange={(v) => set({ title: v })} disabled={!editable} required testId="ncr-title" />
          </div>
          <div className="field">
            <label htmlFor="ncr-sev">{t("qa.ncr.head.severity")}</label>
            <select id="ncr-sev" className="select" value={form.severity} disabled={!editable} onChange={(e) => set({ severity: e.target.value as Severity3 })}>
              {SEVS.map((s) => (
                <option key={s} value={s}>
                  {t(sevKey(s))}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ncr-src">{t("qa.ncr.head.source")}</label>
            <select id="ncr-src" className="select" value={form.source} disabled={!editable || !isNew} onChange={(e) => set({ source: e.target.value as NcrInput["source"] })}>
              {Object.keys(SOURCE_KEYS).map((s) => (
                <option key={s} value={s}>
                  {sourceText(s)}
                </option>
              ))}
            </select>
          </div>
          <div className="span-2">
            <ItemPicker label={t("qa.lots.head.item")} value={item} onChange={(i) => (setItem(i), set({ item_id: i.id, lot_id: null }), setLotCode(""))} disabled={!editable || !isNew} testId="ncr-item" />
          </div>
          <div className="field">
            <label htmlFor="ncr-place">{t("qa.ncr.head.place")}</label>
            <select id="ncr-place" className="select" value={form.place} disabled={!editable || !isNew} onChange={(e) => set({ place: e.target.value as "stock" | "wip" })}>
              <option value="stock">{t("qa.ncr.str.stock")}</option>
              <option value="wip">{t("qa.ncr.str.wip")}</option>
            </select>
          </div>
          {form.place === "stock" ? (
            <div className="field" style={{ position: "relative" }}>
              <label htmlFor="ncr-lot">{t("qa.ncr.label.lot")}</label>
              <input id="ncr-lot" className="input" value={lotCode} disabled={!editable || !isNew || !form.item_id} onChange={(e) => (setLotCode(e.target.value), set({ lot_id: null }))} placeholder={form.item_id ? t("qa.ncr.ph.lot") : t("qa.ncr.ph.itemFirst")} autoComplete="off" />
              {(lots.data?.items ?? []).length && !form.lot_id ? (
                <ul className="mfg-picker-list" style={{ position: "absolute", top: "100%", left: 0, right: 0 }}>
                  {(lots.data?.items ?? []).map((l) => (
                    <li key={l.id} onMouseDown={() => (set({ lot_id: l.id }), setLotCode(l.lot_code))}>
                      <span className="mono">{l.lot_code}</span>
                      <span className="muted small">{t("qa.ncr.tpl.onHand", { q: formatNumber(l.on_hand) })}</span>
                      <span />
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          <TextField label={t("qa.ncr.head.qty")} name="qty_nc" type="number" value={form.qty_nc ? String(form.qty_nc) : ""} onChange={(v) => set({ qty_nc: Number(v) || 0 })} disabled={!editable} required testId="ncr-qty" />
          {form.source === "supplier" || form.supplier_id ? (
            <div className="field">
              <label htmlFor="ncr-sup">{t("qa.plans.label.supplier")}</label>
              <select id="ncr-sup" className="select" value={form.supplier_id ?? ""} disabled={!editable} onChange={(e) => set({ supplier_id: e.target.value || null })}>
                <option value="">{t("qa.settings.str.none")}</option>
                {suppliers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          <fieldset className="mfg-fieldset span-all">
            <legend>{t("qa.ncr.label.defects")}</legend>
            {defectCodes.length ? (
              <div className="qa-role-checks">
                {defectCodes.map((c) => (
                  <label key={c.code} className="checkbox">
                    <input type="checkbox" disabled={!editable} checked={form.defect_codes.includes(c.code)} onChange={(e) => set({ defect_codes: e.target.checked ? [...form.defect_codes, c.code] : form.defect_codes.filter((x) => x !== c.code) })} />
                    <span className="mono">{c.code}</span> {c.name}
                  </label>
                ))}
              </div>
            ) : (
              <span className="small muted">
                {t("qa.ncr.text.noCodes")} <Link to={mfgPaths.qaSettings()}>{t("nav.mfg.section.qa-settings")}</Link>
              </span>
            )}
          </fieldset>
          {(["description", "containment", "investigation"] as const).map((k) => (
            <div key={k} className="field span-all">
              <label htmlFor={`ncr-${k}`}>{t(`qa.ncr.label.${k}` as StringKey)}</label>
              <textarea id={`ncr-${k}`} className="textarea" rows={k === "description" ? 3 : 2} disabled={!editable && !(k === "investigation" && canEdit && n && ["proposed", "approved"].includes(n.status))} value={form[k]} onChange={(e) => set({ [k]: e.target.value })} data-testid={`ncr-${k}`} />
            </div>
          ))}
          <label className="checkbox span-all">
            <input type="checkbox" disabled={!editable} checked={form.capa_required} onChange={(e) => set({ capa_required: e.target.checked })} /> {t("qa.ncr.label.capa")}
          </label>
        </div>
      </Section>
    </FormErrors>
  );
  if (isNew)
    return (
      <div className="col gap-lg" data-testid="ncr-new-page">
        <UnsavedChangesGuard when={dirty} what={t("qa.ncr.str.thisNcr")} />
        <PageHeader
          title={t("qa.ncr.str.newTitle")}
          description={t("qa.ncr.str.newDesc")}
          actions={
            <button type="button" className="btn primary" disabled={busy || !form.title.trim() || !form.item_id || form.qty_nc <= 0} onClick={() => void save()} data-testid="ncr-save">
              <Icon name="save" /> {t("qa.ncr.btn.create")}
            </button>
          }
        />
        <MfgError error={error} />
        {form$}
      </div>
    );
  const x = n!;
  const primary =
    x.status === "draft" && canEdit ? (
      <button type="button" className="btn primary" disabled={busy || dirty} onClick={() => void step("open")} data-testid="ncr-open">
        <Icon name="lock" /> {t("qa.ncr.btn.open")}
      </button>
    ) : (x.status === "open" || x.status === "proposed") && canEdit && tab !== "dispositions" && x.status === "open" ? (
      <button type="button" className="btn primary" onClick={() => setTab("dispositions")} data-testid="ncr-propose-go">
        <Icon name="list" /> {t("qa.ncr.btn.propose")}
      </button>
    ) : x.status === "proposed" && canApprove ? (
      <button type="button" className="btn primary" disabled={busy || dirty} onClick={() => setSign("approve")} data-testid="ncr-approve">
        <Icon name="check" /> {x.signatures.some((s) => s.action === "approve" && s.status === "valid") ? t("qa.ncr.btn.approveNext") : t("qa.ncr.btn.approve")}
      </button>
    ) : x.status === "approved" && canEdit ? (
      <button type="button" className="btn primary" disabled={busy} onClick={() => setImplementing(true)} data-testid="ncr-implement">
        <Icon name="play" /> {t("qa.ncr.btn.implement")}
      </button>
    ) : x.status === "implemented" && canApprove ? (
      <button type="button" className="btn primary" disabled={busy} onClick={() => setSign("close")} data-testid="ncr-close">
        <Icon name="lock" /> {t("qa.ncr.btn.close")}
      </button>
    ) : null;
  return (
    <div className="col gap-lg" data-testid="ncr-page" data-status={x.status}>
      <UnsavedChangesGuard when={dirty} what={t("qa.ncr.str.thisNcr")} />
      <RecordHeader
        crumbs={[[t("nav.mfg.section.qa-ncrs"), mfgPaths.qaNcrs()]]}
        number={x.number}
        title={x.title}
        status={<NcrStatusChip s={x.status} />}
        chips={
          <>
            <SeverityChip s={x.severity} />
            {x.capa_required ? (
              <span className="badge info">
                <Icon name="refresh" /> {t("qa.ncr.str.capaRequired")}
              </span>
            ) : null}
          </>
        }
        facts={[
          [t("qa.lots.head.item"), <ItemCell key="i" item={x.item} id={x.item_id} />],
          [t("qa.ncr.head.qty"), fmtQ(x.qty_nc)],
          [t("qa.ncr.head.place"), x.place === "wip" ? (x.wo_id ? <Link to={mfgPaths.workOrder(x.wo_id)}>{t("qa.ncr.tpl.wip", { seq: x.operation_seq ?? "" })}</Link> : t("qa.ncr.str.wip")) : x.lot_code ? <span className="mono">{x.lot_code}</span> : t("qa.ncr.str.stock")],
          [t("qa.ncr.head.source"), x.inspection_lot_id ? <Link to={mfgPaths.qaLot(x.inspection_lot_id)}>{sourceText(x.source)}</Link> : x.complaint_id ? <Link to={mfgPaths.qaComplaint(x.complaint_id)}>{sourceText(x.source)}</Link> : sourceText(x.source)],
          [t("qa.plans.label.supplier"), x.supplier_id ? supplier(x.supplier_id) : null],
          [t("qa.ncr.label.defects"), x.defect_codes.length ? <span className="mono">{x.defect_codes.join(", ")}</span> : null],
          [t("qa.ncr.label.author"), person(x.author_id)],
          [t("qa.ncr.head.opened"), formatDateTime(x.created_at)],
        ]}
        actions={
          <>
            {["draft", "open", "proposed"].includes(x.status) && canEdit ? (
              <button type="button" className="btn ghost" onClick={() => setSign("cancel")} data-testid="ncr-cancel">
                {t("qa.ncr.btn.cancel")}
              </button>
            ) : null}
            <Link className="btn ghost" to={mfgPaths.printQa("ncr", x.id)} target="_blank" rel="noopener">
              <Icon name="file" /> {t("qa.common.btn.print")}
            </Link>
            {editable ? (
              <button type="button" className="btn" disabled={busy || !dirty} onClick={() => void save()} data-testid="ncr-save">
                <Icon name="save" /> {t("qa.plans.btn.save")}
              </button>
            ) : null}
            {primary}
          </>
        }
      />
      <NcrGuide n={x} />
      {isConflict(error) ? <ConflictBanner onReload={() => (setError(null), rec.reload())} /> : <MfgError error={error} />}
      <RecordTabs label={t("qa.ncr.aria.tabs")} value={tab} onChange={setTab} tabs={[{ key: "details", label: t("qa.shell.tab.details") }, { key: "dispositions", label: t("qa.ncr.tab.dispositions"), count: x.dispositions.length }, ...standardTabs(x)]} />
      {tab === "details" ? (
        <TabPanel id="details">
          {editable ? (
            form$
          ) : (
            <Section title={t("qa.ncr.head.what")}>
              <div className="col">
                <TextBlock label={t("qa.ncr.label.description")} text={x.description} />
                <TextBlock label={t("qa.ncr.label.containment")} text={x.containment} />
                <TextBlock label={t("qa.ncr.label.investigation")} text={x.investigation} />
              </div>
            </Section>
          )}
        </TabPanel>
      ) : null}
      {tab === "dispositions" ? (
        <TabPanel id="dispositions">
          <Dispositions n={x} editable={canEdit && (x.status === "open" || x.status === "proposed")} onSaved={(r) => rec.setData(r)} ask={reason.ask} />
        </TabPanel>
      ) : null}
      {tab === "links" ? (
        <TabPanel id="links">
          <LinksTab links={x.links} fromType="ncr" fromId={x.id} canEdit={canEdit} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {tab === "attachments" ? (
        <TabPanel id="attachments">
          <AttachmentsTab attachments={x.attachments} entityType="ncr" entityId={x.id} canEdit={canEdit} locked={!["draft", "open"].includes(x.status)} onChanged={rec.reload} />
        </TabPanel>
      ) : null}
      {tab === "history" ? (
        <TabPanel id="history">
          <HistoryTab entityType="ncr" entityId={x.id} />
        </TabPanel>
      ) : null}
      {tab === "signatures" ? (
        <TabPanel id="signatures">
          <SignaturesTab signatures={x.signatures} recordType="ncr" recordId={x.id} />
        </TabPanel>
      ) : null}
      {reason.dialog}
      {implementing ? (
        <ConfirmDialog title={t("qa.ncr.tpl.implementTitle", { n: x.number })} confirmLabel={t("qa.ncr.btn.implement")} busy={busy} onCancel={() => setImplementing(false)} onConfirm={() => void step("implement")}>
          <p style={{ marginTop: 0 }}>{t("qa.ncr.text.implementIntro")}</p>
          <ul className="mfg-plain-list col" style={{ gap: 4 }}>
            {x.dispositions.map((d) => (
              <li key={d.id}>
                <strong>{t(DISPOSITION_LABEL[d.kind])}</strong> {fmtQ(d.qty)}: {t(effectKey(d.kind, x.place))}
              </li>
            ))}
          </ul>
        </ConfirmDialog>
      ) : null}
      {sign ? (
        <SignatureDialog<Ncr>
          title={sign === "approve" ? t("qa.ncr.tpl.approveTitle", { n: x.number }) : sign === "close" ? t("qa.ncr.tpl.closeTitle", { n: x.number }) : t("qa.ncr.tpl.cancelTitle", { n: x.number })}
          recordType="ncr"
          recordId={x.id}
          recordLabel={x.number}
          action={sign}
          meaning={sign === "close" ? "closed" : sign === "cancel" ? "closed" : undefined}
          danger={sign === "cancel"}
          commentRequired={sign === "cancel"}
          commentLabel={sign === "cancel" ? t("qa.lots.label.cancelReason") : undefined}
          submitLabel={sign === "approve" ? t("qa.ncr.btn.signApprove") : sign === "close" ? t("qa.ncr.btn.signClose") : t("qa.lots.btn.signCancel")}
          plainLabel={sign === "approve" ? t("qa.ncr.btn.approve") : sign === "close" ? t("qa.ncr.btn.close") : t("qa.ncr.btn.cancel")}
          effect={sign === "approve" ? t("qa.ncr.text.approveEffect") : sign === "close" ? t("qa.ncr.text.closeEffect") : t("qa.ncr.text.cancelEffect")}
          perform={(sig, comment) => recordAction<Ncr>("ncr", x.id, sign, sign === "cancel" ? { reason: comment } : { note: comment }, { version: x.row_version, signature: sig })}
          onDone={(res) => {
            toast(signedToast(res, sign === "approve" ? t("qa.ncr.toast.approved") : sign === "close" ? t("qa.ncr.toast.closed") : t("qa.ncr.toast.cancelled")));
            setSign(null);
            rec.reload();
          }}
          onClose={() => setSign(null)}
        />
      ) : null}
    </div>
  );
}

const effectKey = (kind: DispositionKind, place: string): StringKey =>
  (place === "wip" ? { scrap: "qa.ncr.eff.wipScrap", rework: "qa.ncr.eff.wipRework", use_as_is: "qa.ncr.eff.wipUse", return_to_supplier: "qa.ncr.eff.rtv" } : { scrap: "qa.ncr.eff.scrap", rework: "qa.ncr.eff.rework", use_as_is: "qa.ncr.eff.use", return_to_supplier: "qa.ncr.eff.rtv" })[kind] as StringKey;

/** What happens next on this NCR, in one sentence. */
function NcrGuide({ n }: { n: Ncr }) {
  const k: Partial<Record<string, StringKey>> = {
    draft: "qa.ncr.guide.draft",
    open: "qa.ncr.guide.open",
    proposed: "qa.ncr.guide.proposed",
    approved: "qa.ncr.guide.approved",
    implemented: n.capa_required && !n.links.some((l) => l.to_type === "capa" || l.from_type === "capa") ? "qa.ncr.guide.needCapa" : "qa.ncr.guide.implemented",
  };
  const key = k[n.status];
  return key ? <NextStepBanner text={t(key)} /> : null;
}

function Dispositions({ n, editable, onSaved, ask }: { n: Ncr; editable: boolean; onSaved(n: Ncr): void; ask(what: string): Promise<string | null> }) {
  const [rows, setRows] = useState<DispositionInput[]>(() => n.dispositions.map(({ kind, qty, location_id, rework_routing_id, rework_to_seq, instructions, justification }) => ({ kind, qty, location_id, rework_routing_id, rework_to_seq, instructions, justification })));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const locs = useLoad((s) => listLocations({ active: true }, s).catch(() => null), []);
  const routings = useLoad((s) => (n.item_id ? listItemRoutings(n.item_id, s).catch(() => null) : null), [n.item_id]);
  const total = rows.reduce((a, r) => a + (r.qty || 0), 0);
  const balanced = Math.abs(total - n.qty_nc) < 1e-9;
  const upd = (i: number, p: Partial<DispositionInput>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const missing = rows.some((r) => (r.kind === "use_as_is" && !r.justification.trim()) || (r.kind === "rework" && n.place === "stock" && !r.rework_routing_id) || (r.kind === "rework" && n.place === "wip" && !r.rework_to_seq) || r.qty <= 0);
  const kinds: DispositionKind[] = n.place === "wip" ? ["scrap", "rework", "use_as_is"] : ["scrap", "rework", "use_as_is", "return_to_supplier"];
  return (
    <section className="card card-table" data-testid="ncr-dispositions">
      <div className="card-header">
        <h2>{t("qa.ncr.tab.dispositions")}</h2>
        <span className={`badge ${balanced ? "ok" : "warn"}`} data-testid="ncr-disposition-total">
          <Icon name={balanced ? "check" : "alert"} /> {t("qa.ncr.tpl.allocated", { a: fmtQ(total), b: fmtQ(n.qty_nc) })}
        </span>
      </div>
      <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
        <table className="table mfg-grid-table">
          <thead>
            <tr>
              <th style={{ width: 40 }}>#</th>
              <th style={{ width: 170 }}>{t("qa.ncr.head.disposition")}</th>
              <th style={{ width: 100 }} className="num">{t("qa.fa.head.qty")}</th>
              <th style={{ width: 200 }}>{n.place === "wip" ? t("qa.ncr.head.reworkAt") : t("qa.ncr.head.fromTo")}</th>
              <th>{t("qa.ncr.head.instructions")}</th>
              <th style={{ width: 160 }}>{t("qa.ncr.head.state")}</th>
              {editable ? <th style={{ width: 40 }}><span className="sr-only">{t("qa.plans.head.remove")}</span></th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const done = n.dispositions[i]?.implemented_at;
              return (
                <tr key={i} data-testid="ncr-disposition-row" data-kind={r.kind}>
                  <td>{i + 1}</td>
                  <td>
                    <select className="select qa-grid-input" aria-label={t("qa.ncr.head.disposition")} disabled={!editable} value={r.kind} onChange={(e) => upd(i, { kind: e.target.value as DispositionKind })}>
                      {kinds.map((k) => (
                        <option key={k} value={k}>
                          {t(DISPOSITION_LABEL[k])}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input className="input qa-grid-input num" inputMode="decimal" aria-label={t("qa.fa.head.qty")} disabled={!editable} value={r.qty ? String(r.qty) : ""} onChange={(e) => upd(i, { qty: Number(e.target.value.replace(",", ".")) || 0 })} />
                  </td>
                  <td>
                    {n.place === "wip" ? (
                      r.kind === "rework" ? (
                        <input className="input qa-grid-input num" inputMode="numeric" aria-label={t("qa.ncr.head.reworkAt")} disabled={!editable} value={r.rework_to_seq ?? ""} onChange={(e) => upd(i, { rework_to_seq: Number(e.target.value.replace(/\D/g, "")) || null })} placeholder={t("qa.ncr.ph.seq")} />
                      ) : (
                        <span className="faint">—</span>
                      )
                    ) : r.kind === "rework" ? (
                      <select className="select qa-grid-input" aria-label={t("qa.ncr.head.routing")} disabled={!editable} value={r.rework_routing_id ?? ""} onChange={(e) => upd(i, { rework_routing_id: e.target.value || null })}>
                        <option value="">{t("qa.ncr.str.chooseRouting")}</option>
                        {(routings.data?.items ?? []).map((rt) => (
                          <option key={rt.id} value={rt.id}>
                            {t("qa.ncr.tpl.routing", { code: rt.code || rt.revision, v: rt.version })}
                          </option>
                        ))}
                      </select>
                    ) : r.kind === "use_as_is" ? (
                      <span className="faint">—</span>
                    ) : (
                      <select className="select qa-grid-input" aria-label={t("qa.ncr.head.fromTo")} disabled={!editable} value={r.location_id ?? ""} onChange={(e) => upd(i, { location_id: e.target.value || null })}>
                        <option value="">{t("qa.ncr.str.chooseLocation")}</option>
                        {(locs.data?.items ?? []).map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.code} {l.name}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td>
                    <input
                      className="input qa-grid-input"
                      aria-label={r.kind === "use_as_is" ? t("qa.ncr.head.justification") : t("qa.ncr.head.instructions")}
                      disabled={!editable}
                      value={r.kind === "use_as_is" ? r.justification : r.instructions}
                      onChange={(e) => upd(i, r.kind === "use_as_is" ? { justification: e.target.value } : { instructions: e.target.value })}
                      placeholder={r.kind === "use_as_is" ? t("qa.ncr.ph.justification") : ""}
                      aria-invalid={r.kind === "use_as_is" && !r.justification.trim() ? true : undefined}
                    />
                  </td>
                  <td>
                    {done ? (
                      <span className="badge ok">
                        <Icon name="check" /> {t("qa.ncr.tpl.implemented", { when: formatDateTime(done) })}
                      </span>
                    ) : (
                      <span className="small muted">{t(effectKey(r.kind, n.place))}</span>
                    )}
                  </td>
                  {editable ? (
                    <td>
                      <button type="button" className="btn ghost sm icon" aria-label={t("qa.ncr.tpl.remove", { n: i + 1 })} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                        <Icon name="trash" size={14} />
                      </button>
                    </td>
                  ) : null}
                </tr>
              );
            })}
            {!rows.length ? (
              <tr>
                <td colSpan={7} className="muted">
                  {editable ? t("qa.ncr.empty.dispEdit") : t("qa.ncr.empty.disp")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {n.rework_wos.length ? (
        <p className="small" style={{ margin: "8px 16px" }}>
          {t("qa.ncr.label.reworkWos")}{" "}
          {n.rework_wos.map((w, i) => (
            <span key={w.id}>
              {i ? ", " : ""}
              <Link to={mfgPaths.workOrder(w.id)} className="mono">
                {w.number}
              </Link>{" "}
              <span className="muted">({w.status})</span>
            </span>
          ))}
        </p>
      ) : null}
      {editable ? (
        <div className="card-footer row wrap" style={{ justifyContent: "space-between", gap: 8 }}>
          <button type="button" className="btn sm" onClick={() => setRows([...rows, { kind: "scrap", qty: Math.max(0, n.qty_nc - total), location_id: null, rework_routing_id: null, rework_to_seq: null, instructions: "", justification: "" }])} data-testid="ncr-disposition-add">
            <Icon name="plus" /> {t("qa.ncr.btn.addDisp")}
          </button>
          <div className="row" style={{ gap: 8 }}>
            <MfgError error={error} />
            <button
              type="button"
              className="btn primary"
              disabled={busy || !rows.length || !balanced || missing}
              title={!balanced ? t("qa.ncr.attr.balance") : missing ? t("qa.ncr.attr.missing") : undefined}
              onClick={async () => {
                const r = await ask(n.number);
                if (r === null) return;
                setBusy(true);
                setError(null);
                try {
                  onSaved(await proposeNcr(n.id, rows, n.row_version, r));
                  toast(t("qa.ncr.toast.proposed"));
                } catch (e) {
                  setError(e);
                } finally {
                  setBusy(false);
                }
              }}
              data-testid="ncr-propose"
            >
              <Icon name="arrow-right" /> {n.status === "proposed" ? t("qa.ncr.btn.repropose") : t("qa.ncr.btn.proposeSave")}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
