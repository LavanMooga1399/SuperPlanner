/**
 * Deviations (M10 4.4, 11): `/mfg/deviations` worklist and `/mfg/deviations/:id` record. Planned deviations are
 * approved (signed, two steps by default) before use; unplanned ones are created from a DHR exception or an NCR.
 * Scope = items, lots, work orders, a date window and a maximum quantity (received quantity counts against it);
 * risk = severity x occurrence with a rationale. Closing records the outcome. With `deviation_sor = external` the
 * record only references the customer's eQMS.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../components/Banner";
import { DateInput } from "../../components/DateInput";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { SignatureDialog, signedToast } from "../../components/SignatureDialog";
import { toast } from "../../components/Toast";
import { UnsavedChangesGuard } from "../../components/UnsavedChangesGuard";
import { t } from "../../lib/i18n";
import { formatDateRange, formatDateTime, formatNumber } from "../../lib/locale";
import { approveDeviation, closeDeviation, createDeviation, getDeviation, listDeviations, updateDeviation } from "../api/clientM10";
import type { Deviation, DeviationInput, DeviationKind } from "../api/typesM10";
import { MfgError, Spinner } from "../components/Feedback";
import { FormErrors } from "../components/Field";
import type { Column } from "../components/VirtualTable";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { usePersonName, rememberPeople } from "../qa/common";
import { HistoryTab, RecordHeader, RecordTabs, Section, SignatureList, TabPanel, useChangeReason } from "../qa/RecordShell";
import { QaWorklist } from "../qa/Worklist";
import { ItemListPicker, LotListPicker, type LotRef } from "./pickers";
import { chipText, DOC_STATE, DocChip, GxpChip, KV, type ChipDef } from "./shared";

const KIND: Record<DeviationKind, ChipDef> = {
  planned: { label: "gxp.dev.kind.planned", tone: "info", icon: "calendar" },
  unplanned: { label: "gxp.dev.kind.unplanned", tone: "warn", icon: "alert" },
};
const riskTone = (score: number) => (score >= 15 ? "danger" : score >= 8 ? "warn" : "ok");
function RiskBadge({ score }: { score: number }) {
  return (
    <span className={`badge ${riskTone(score)}`} data-testid="dev-risk">
      <Icon name={score >= 15 ? "alert" : score >= 8 ? "flag" : "check"} /> {t("gxp.tpl.risk", { n: score })} · {t(score >= 15 ? "gxp.dev.risk.high" : score >= 8 ? "gxp.dev.risk.medium" : "gxp.dev.risk.low")}
    </span>
  );
}

// ---------------------------------------------------------------- worklist
export function DeviationsPage() {
  const canEdit = useCan("deviation_edit");
  useEffect(() => {
    document.title = t("gxp.dev.title");
  }, []);
  const columns = useMemo<Column<Deviation>[]>(
    () => [
      {
        key: "number",
        header: t("gxp.dev.head.number"),
        width: "120px",
        render: (d) => (
          <Link to={mfgPaths.deviation(d.id)} className="mono" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
            {d.number}
          </Link>
        ),
      },
      { key: "status", header: t("gxp.head.status"), width: "130px", exportValue: (d) => chipText(DOC_STATE, d.status), render: (d) => <DocChip s={d.status} testId="dev-status" /> },
      { key: "kind", header: t("gxp.dev.head.kind"), width: "130px", exportValue: (d) => chipText(KIND, d.kind), render: (d) => <GxpChip def={KIND[d.kind]} value={d.kind} /> },
      { key: "title", header: t("gxp.dev.head.title"), width: "minmax(220px, 2fr)", render: (d) => <span className="mfg-ellipsis">{d.title}</span> },
      { key: "risk", header: t("gxp.dev.head.risk"), width: "150px", exportValue: (d) => d.risk_score, render: (d) => <RiskBadge score={d.risk_score} /> },
      { key: "window", header: t("gxp.dev.head.window"), width: "170px", drop: 2, render: (d) => (d.scope.valid_from || d.scope.valid_to ? formatDateRange(d.scope.valid_from, d.scope.valid_to) : <span className="faint">–</span>) },
      { key: "used", header: t("gxp.dev.head.used"), width: "150px", align: "right", drop: 1, exportValue: (d) => d.used_qty, render: (d) => <span className="pl-num">{d.scope.max_qty ? t("common.nOfM", { n: formatNumber(d.used_qty), m: formatNumber(d.scope.max_qty) }) : formatNumber(d.used_qty)}</span> },
      { key: "created", header: t("gxp.dev.head.created"), width: "150px", drop: 3, render: (d) => formatDateTime(d.created_at) },
    ],
    [],
  );
  return (
    <QaWorklist<Deviation>
      title={t("gxp.dev.title")}
      description={t("gxp.dev.desc")}
      actions={
        canEdit ? (
          <Link className="btn primary" to={mfgPaths.deviation("new")} data-testid="dev-new">
            <Icon name="plus" /> {t("gxp.dev.btn.new")}
          </Link>
        ) : null
      }
      pageKey="deviations"
      testId="deviations-page"
      statusOptions={[{ value: "", label: t("gxp.dev.status.active") }, ...(["draft", "approved", "closed", "cancelled"] as const).map((s) => ({ value: s, label: chipText(DOC_STATE, s) })), { value: "all", label: t("gxp.list.all") }]}
      defaultStatus="draft,approved"
      filters={[{ param: "kind", label: t("gxp.dev.head.kind"), options: [{ value: "", label: t("gxp.list.anyKind") }, { value: "planned", label: t("gxp.dev.kind.planned") }, { value: "unplanned", label: t("gxp.dev.kind.unplanned") }] }]}
      fetch={(q, signal) =>
        listDeviations({ ...q, status: q.status === "all" ? undefined : (q.status as string | undefined) }, signal).then((p) => {
          for (const d of p.items) rememberPeople(d.people);
          return p;
        })
      }
      columns={columns}
      card={{ title: "number", status: "status", fields: ["title", "kind", "risk"] }}
      rowKey={(d) => d.id}
      rowExtras={(d) => ({ testId: "dev-row", data: { status: d.status } })}
      rowPath={(d) => mfgPaths.deviation(d.id)}
      empty={t("gxp.dev.empty")}
      noun={t("gxp.dev.noun")}
    />
  );
}

// ---------------------------------------------------------------- record
const blank = (kind: DeviationKind = "planned"): DeviationInput => ({
  kind,
  title: "",
  description: "",
  scope: { item_ids: [], lot_ids: [], wo_ids: [], valid_from: null, valid_to: null, max_qty: null },
  risk: { severity: 1, occurrence: 1, rationale: "" },
  ncr_id: null,
  capa_id: null,
  external_ref: null,
});
const toInput = (d: Deviation): DeviationInput => ({ kind: d.kind, title: d.title, description: d.description, scope: d.scope, risk: d.risk, ncr_id: d.ncr_id, capa_id: d.capa_id, external_ref: d.external_ref });

export function DeviationPage() {
  const { deviationId = "" } = useParams();
  const [params] = useSearchParams();
  const isNew = deviationId === "new";
  const fromException = params.get("exception");
  const navigate = useNavigate();
  const canEdit = useCan("deviation_edit");
  const person = usePersonName();
  const reason = useChangeReason();
  const rec = useLoad((s) => (isNew ? null : getDeviation(deviationId, s)), [deviationId]);
  const d = rec.data;
  const [form, setForm] = useState<DeviationInput>(() => {
    const b = blank(fromException ? "unplanned" : "planned");
    const item = params.get("item");
    const lot = params.get("lot");
    return { ...b, scope: { ...b.scope, item_ids: item ? [item] : [], lot_ids: lot ? [lot] : [] } };
  });
  const [lots, setLots] = useState<LotRef[]>(() => (params.get("lot") ? [{ id: params.get("lot")!, code: params.get("lotCode") ?? params.get("lot")! }] : []));
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("details");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sign, setSign] = useState(false);
  const [closing, setClosing] = useState<null | "close" | "cancel">(null);
  useEffect(() => {
    if (d) {
      rememberPeople(d.people);
      setForm(toInput(d));
      setLots(d.scope.lot_ids.map((id) => ({ id, code: id })));
      setDirty(false);
      document.title = `${d.number} - ${t("gxp.dev.title")}`;
    } else if (isNew) document.title = t("gxp.dev.newTitle");
  }, [d, isNew]);
  if (!isNew && !d) return rec.error ? <MfgError error={rec.error} onRetry={rec.reload} /> : <Spinner />;
  const editable = canEdit && (isNew || d?.status === "draft") && d?.sor !== "external";
  const set = (p: Partial<DeviationInput>) => (setForm((f) => ({ ...f, ...p })), setDirty(true));
  const setScope = (p: Partial<DeviationInput["scope"]>) => set({ scope: { ...form.scope, ...p } });
  const setRisk = (p: Partial<DeviationInput["risk"]>) => set({ risk: { ...form.risk, ...p } });
  const score = form.risk.severity * form.risk.occurrence;
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        const x = await createDeviation({ ...form, from_exception_id: fromException });
        setDirty(false);
        toast(t("gxp.dev.toast.created", { n: x.number }));
        const back = params.get("dhr");
        navigate(back && fromException ? mfgPaths.dhrRecord(back) : mfgPaths.deviation(x.id), { replace: true });
      } else if (d) {
        const why = await reason.ask(d.number);
        if (why === null) return;
        rec.setData(await updateDeviation(d, form, why));
        setDirty(false);
        toast(t("gxp.toast.saved"));
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const approvedSigs = d?.signatures.filter((s) => s.status === "valid" && s.action === "approve") ?? [];
  return (
    <div className="col gap-lg" data-testid="deviation-page" data-status={d?.status ?? "new"}>
      <UnsavedChangesGuard when={dirty} />
      <RecordHeader
        crumbs={[[t("gxp.dev.title"), mfgPaths.deviations()]]}
        number={d?.number ?? t("gxp.dev.newNumber")}
        title={d?.title}
        status={d ? <DocChip s={d.status} testId="dev-status" /> : null}
        chips={
          <>
            <GxpChip def={KIND[form.kind]} value={form.kind} />
            {d ? <RiskBadge score={d.risk_score} /> : null}
            {d?.sor === "external" ? <span className="badge info">{t("gxp.dev.external")}</span> : null}
          </>
        }
        facts={
          d
            ? [
                [t("gxp.dev.fact.author"), person(d.author_id)],
                [t("gxp.dev.head.window"), d.scope.valid_from || d.scope.valid_to ? formatDateRange(d.scope.valid_from, d.scope.valid_to) : t("gxp.dev.noWindow")],
                [t("gxp.dev.head.used"), d.scope.max_qty ? t("common.nOfM", { n: formatNumber(d.used_qty), m: formatNumber(d.scope.max_qty) }) : formatNumber(d.used_qty)],
                [t("gxp.dev.fact.approved"), d.approved_at ? formatDateTime(d.approved_at) : null],
                [t("gxp.dev.fact.closed"), d.closed_at ? formatDateTime(d.closed_at) : null],
              ]
            : []
        }
        actions={
          <>
            {d && d.status === "approved" && canEdit ? (
              <button type="button" className="btn" onClick={() => setClosing("close")} data-testid="dev-close">
                <Icon name="check" /> {t("gxp.dev.btn.close")}
              </button>
            ) : null}
            {d && d.status === "draft" && canEdit ? (
              <button type="button" className="btn" onClick={() => setClosing("cancel")} data-testid="dev-cancel">
                <Icon name="ban" /> {t("gxp.dev.btn.cancel")}
              </button>
            ) : null}
            {editable ? (
              <button type="button" className={`btn${isNew || dirty ? " primary" : ""}`} disabled={busy || !form.title.trim() || (!isNew && !dirty)} onClick={() => void save()} data-testid="dev-save">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {isNew ? t("gxp.dev.btn.create") : t("gxp.btn.save")}
              </button>
            ) : null}
            {d && d.status === "draft" && !dirty ? (
              <button type="button" className="btn primary" onClick={() => setSign(true)} data-testid="dev-approve">
                <Icon name="lock" /> {approvedSigs.length ? t("gxp.dev.btn.signApprove") : t("gxp.dev.btn.signReview")}
              </button>
            ) : null}
          </>
        }
      />
      {fromException && isNew ? <Banner tone="info">{t("gxp.dev.fromException")}</Banner> : null}
      {d?.outcome ? (
        <Banner tone={d.status === "cancelled" ? "info" : "ok"} title={t("gxp.dev.outcome")}>
          {d.outcome}
        </Banner>
      ) : null}
      {!isNew && d ? (
        <RecordTabs
          label={t("gxp.dev.aria.tabs")}
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "details", label: t("gxp.tab.details") },
            { key: "signatures", label: t("gxp.dhr.nav.signatures"), count: d.signatures.length },
            { key: "history", label: t("gxp.dhr.nav.history") },
          ]}
        />
      ) : null}
      {tab === "details" || isNew ? (
        <TabPanel id="details">
          <FormErrors error={error}>
            <MfgError error={error} />
            <Section title={t("gxp.dev.sec.what")}>
              <div className="qa-form-grid">
                <div className="field">
                  <span className="field-label" id="dev-kind-l">
                    {t("gxp.dev.head.kind")}
                  </span>
                  <div className="btn-group" role="group" aria-labelledby="dev-kind-l">
                    {(["planned", "unplanned"] as const).map((k) => (
                      <button key={k} type="button" className="btn" disabled={!editable || !isNew} aria-pressed={form.kind === k} onClick={() => set({ kind: k })}>
                        {t(`gxp.dev.kind.${k}`)}
                      </button>
                    ))}
                  </div>
                  <span className="hint">{form.kind === "planned" ? t("gxp.dev.hint.planned") : t("gxp.dev.hint.unplanned")}</span>
                </div>
                <div className="field" style={{ gridColumn: "span 2" }}>
                  <label htmlFor="dev-title">
                    {t("gxp.dev.head.title")} <span className="req" aria-hidden />
                  </label>
                  <input id="dev-title" name="title" className="input" maxLength={200} value={form.title} disabled={!editable} onChange={(e) => set({ title: e.target.value })} data-testid="dev-title" />
                </div>
                <div className="field">
                  <label htmlFor="dev-ext">{t("gxp.dev.label.externalRef")}</label>
                  <input id="dev-ext" name="external_ref" className="input" maxLength={64} value={form.external_ref ?? ""} disabled={!editable} onChange={(e) => set({ external_ref: e.target.value || null })} />
                </div>
              </div>
              <div className="field" style={{ marginTop: 12 }}>
                <label htmlFor="dev-desc">{t("gxp.dev.label.description")}</label>
                <textarea id="dev-desc" name="description" className="textarea" rows={4} value={form.description} disabled={!editable} onChange={(e) => set({ description: e.target.value })} />
              </div>
            </Section>
            <Section title={t("gxp.dev.sec.scope")}>
              <p className="small muted" style={{ marginTop: 0 }}>
                {t("gxp.dev.hint.scope")}
              </p>
              <div className="qa-form-grid">
                <ItemListPicker ids={form.scope.item_ids} onChange={(ids) => setScope({ item_ids: ids })} label={t("gxp.dev.label.items")} disabled={!editable} testId="dev-items" />
                <LotListPicker
                  lots={lots}
                  label={t("gxp.dev.label.lots")}
                  itemId={form.scope.item_ids.length === 1 ? form.scope.item_ids[0] : null}
                  disabled={!editable}
                  onChange={(l) => {
                    setLots(l);
                    setScope({ lot_ids: l.map((x) => x.id) });
                  }}
                  testId="dev-lots"
                />
                <div className="field">
                  <label htmlFor="dev-from">{t("gxp.dev.label.validFrom")}</label>
                  <DateInput id="dev-from" value={form.scope.valid_from ?? ""} onChange={(v) => setScope({ valid_from: v || null })} disabled={!editable} />
                </div>
                <div className="field">
                  <label htmlFor="dev-to">{t("gxp.dev.label.validTo")}</label>
                  <DateInput id="dev-to" value={form.scope.valid_to ?? ""} min={form.scope.valid_from ?? undefined} onChange={(v) => setScope({ valid_to: v || null })} disabled={!editable} />
                </div>
                <div className="field">
                  <label htmlFor="dev-max">{t("gxp.dev.label.maxQty")}</label>
                  <input id="dev-max" name="max_qty" className="input" type="number" min={0} inputMode="decimal" value={form.scope.max_qty ?? ""} disabled={!editable} onChange={(e) => setScope({ max_qty: e.target.value === "" ? null : Number(e.target.value) })} data-testid="dev-max" />
                  <span className="hint">{t("gxp.dev.hint.maxQty")}</span>
                </div>
              </div>
            </Section>
            <Section title={t("gxp.dev.sec.risk")}>
              <div className="qa-form-grid">
                {(["severity", "occurrence"] as const).map((k) => (
                  <div className="field" key={k}>
                    <label htmlFor={`dev-${k}`}>{t(`gxp.dev.label.${k}`)}</label>
                    <select id={`dev-${k}`} className="select" value={form.risk[k]} disabled={!editable} onChange={(e) => setRisk({ [k]: Number(e.target.value) })} data-testid={`dev-${k}`}>
                      {[1, 2, 3, 4, 5].map((n) => (
                        <option key={n} value={n}>
                          {t(`gxp.dev.${k}.${n}` as "gxp.dev.severity.1")}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
                <div className="field">
                  <span className="field-label">{t("gxp.dev.head.risk")}</span>
                  <RiskBadge score={score} />
                  <span className="hint">{t("gxp.dev.hint.risk")}</span>
                </div>
              </div>
              <div className="field" style={{ marginTop: 12 }}>
                <label htmlFor="dev-rat">{t("gxp.dev.label.rationale")}</label>
                <textarea id="dev-rat" className="textarea" rows={3} maxLength={2000} value={form.risk.rationale} disabled={!editable} onChange={(e) => setRisk({ rationale: e.target.value })} />
              </div>
            </Section>
            {d && d.links.length ? (
              <Section title={t("gxp.dev.sec.links")}>
                <KV rows={d.links.map((l, i) => [String((l as Record<string, unknown>).to_type ?? i), String((l as Record<string, unknown>).label ?? (l as Record<string, unknown>).to_id ?? "")])} />
              </Section>
            ) : null}
          </FormErrors>
        </TabPanel>
      ) : tab === "signatures" && d ? (
        <TabPanel id="signatures">
          <Section title={t("gxp.dhr.nav.signatures")}>
            <SignatureList signatures={d.signatures} />
          </Section>
        </TabPanel>
      ) : d ? (
        <TabPanel id="history">
          <HistoryTab entityType="qa_deviation" entityId={d.id} />
        </TabPanel>
      ) : null}
      {reason.dialog}
      {sign && d ? (
        <SignatureDialog<Deviation>
          title={t("gxp.tpl.approveDev", { n: d.number })}
          recordType="deviation"
          recordId={d.id}
          recordLabel={d.number}
          action="approve"
          submitLabel={approvedSigs.length ? t("gxp.dev.btn.signApprove") : t("gxp.dev.btn.signReview")}
          plainLabel={t("gxp.dev.btn.approve")}
          effect={t("gxp.dev.approveEffect")}
          extraRows={[
            { label: t("gxp.dev.head.title"), value: d.title },
            { label: t("gxp.dev.head.risk"), value: t("gxp.tpl.risk", { n: d.risk_score }) },
            { label: t("gxp.dev.head.window"), value: d.scope.valid_from || d.scope.valid_to ? formatDateRange(d.scope.valid_from, d.scope.valid_to) : t("gxp.dev.noWindow") },
            { label: t("gxp.dev.label.maxQty"), value: d.scope.max_qty ? formatNumber(d.scope.max_qty) : "–" },
          ]}
          perform={(sig, comment) => approveDeviation(d, sig, comment)}
          onDone={(res) => {
            toast(signedToast(res, t("gxp.tpl.devApproved", { n: d.number })));
            setSign(false);
            rec.reload();
          }}
          onClose={() => setSign(false)}
        />
      ) : null}
      {closing && d ? (
        <CloseDialog
          dev={d}
          cancel={closing === "cancel"}
          onClose={() => setClosing(null)}
          onDone={(x) => {
            setClosing(null);
            rec.setData(x);
            toast(closing === "cancel" ? t("gxp.dev.toast.cancelled") : t("gxp.dev.toast.closed"));
          }}
        />
      ) : null}
    </div>
  );
}

function CloseDialog({ dev, cancel, onClose, onDone }: { dev: Deviation; cancel: boolean; onClose(): void; onDone(d: Deviation): void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  return (
    <Dialog
      title={cancel ? t("gxp.tpl.cancelDev", { n: dev.number }) : t("gxp.tpl.closeDev", { n: dev.number })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className={`btn ${cancel ? "danger" : "primary"}`}
            disabled={busy || !text.trim()}
            onClick={() => {
              setBusy(true);
              setErr(null);
              closeDeviation(dev, text.trim(), cancel)
                .then(onDone, (e: unknown) => setErr(e))
                .finally(() => setBusy(false));
            }}
            data-testid="dev-close-go"
          >
            {cancel ? t("gxp.dev.btn.cancel") : t("gxp.dev.btn.close")}
          </button>
        </>
      }
    >
      <div className="col" style={{ gap: 10 }}>
        <MfgError error={err} />
        <p style={{ margin: 0 }}>{cancel ? t("gxp.dev.cancelBody") : t("gxp.dev.closeBody")}</p>
        <div className="field">
          <label htmlFor="dev-outcome">
            {cancel ? t("gxp.dev.label.cancelReason") : t("gxp.dev.outcome")} <span className="req" aria-hidden />
          </label>
          <textarea id="dev-outcome" className="textarea" rows={3} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} data-testid="dev-outcome" />
        </div>
      </div>
    </Dialog>
  );
}
