/**
 * Engineering changes (M5 5): `/mfg/eco` (list, new) and `/mfg/eco/:id`.
 * A change request bundles draft BOM / routing versions with when they take effect (a date, a unit serial number, or
 * "use up the old part" with a date suggested from MRP), what happens to open work orders, purchase orders and stock,
 * an impact analysis, approval by someone other than the requester, and one-step implementation (all drafts released
 * together, or nothing). Requests from the ERP arrive already implemented (source ERP).
 */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError } from "../../../api/client";
import { Banner } from "../../../components/Banner";
import { Dialog } from "../../../components/Dialog";
import { Icon, type IconName } from "../../../components/Icon";
import { getBom, getRouting, listItemBoms, listItemRoutings } from "../../api/client";
import { addEcoItem, createEco, ecoAction, getEco, getEcoImpact, listEcos, removeEcoItem, updateEco } from "../../api/clientM5";
import type { ItemRef } from "../../api/types";
import type { ChangeRequest, CrInput, CrItem, CrStatus, EcoImpact, ReleaseIssue } from "../../api/typesM5";
import { MfgError, Spinner } from "../../components/Feedback";
import { ItemPicker } from "../../components/ItemPicker";
import { fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { needsText, useAccess, useCan } from "../../lib/permissions";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { isConflict, useLoad } from "../../lib/useMfg";
import { formatDate } from "../../../lib/locale";
import { PageHeader } from "../../../components/PageHeader";
import { FilterBar } from "../../../components/FilterBar";
import { DataTable } from "../../components/DataTable";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { plural, t } from "../../../lib/i18n";
import { SignatureDialog, signedToast } from "../../../components/SignatureDialog";
import { toast } from "../../../components/Toast";
import { signedAction } from "../../api/clientM7";
import { useChangeReason } from "../../qa/ChangeReason";
import { usePart11 } from "../../qa/part11";

const STATUS: Record<CrStatus, { label: string; tone: string; icon: IconName }> = {
  draft: { label: t("mfg.ecoPages.str.draft"), tone: "info", icon: "file" },
  submitted: { label: t("mfg.ecoPages.str.waitingForApproval"), tone: "warn", icon: "clock" },
  approved: { label: t("mfg.ecoPages.str.approved"), tone: "accent", icon: "check" },
  rejected: { label: t("mfg.ecoPages.str.rejected"), tone: "danger", icon: "x" },
  implemented: { label: t("mfg.ecoPages.str.implemented"), tone: "ok", icon: "check" },
  cancelled: { label: t("mfg.ecoPages.str.cancelled"), tone: "info", icon: "ban" },
};

export function CrStatusChip({ s }: { s: CrStatus }) {
  const m = STATUS[s] ?? STATUS.draft;
  return (
    <span className={`badge ${m.tone}`} data-status={s}>
      <Icon name={m.icon} /> {m.label}
    </span>
  );
}

const who = (u: ChangeRequest["requested_by"]) => (u === null ? "" : typeof u === "string" ? u : (u.display_name ?? u.email ?? u.id));
const whoId = (u: ChangeRequest["requested_by"]) => (u === null ? null : typeof u === "string" ? u : u.id);

/** "BOM KV-PCB-CPU rev B v2" for a document id (the CR carries ids only) */
function DocLabel({ type, id, link }: { type: "bom" | "routing"; id: string | null; link?: boolean }) {
  const d = useLoad<{ item: ItemRef; revision: string; version: number; status: string } | null>(
    (signal) => (id ? (type === "bom" ? getBom(id, signal) : getRouting(id, signal)).catch(() => null) : null),
    [type, id],
  );
  if (!id) return <span className="faint">{t("mfg.ecoPages.text.nothingNew")}</span>;
  const x = d.data as { item: ItemRef; revision: string; version: number; status: string } | null;
  if (!x) return <span className="mono small">{id}</span>;
  const text = t("mfg.ecoPages.tpl.revV", { partnumber: x.item.part_number, revision: x.revision, version: x.version });
  return (
    <span>
      {link ? (
        <Link to={type === "bom" ? mfgPaths.itemBom(x.item.id, { bom: id }) : mfgPaths.routing(x.item.id, { routing: id })} className="mono">
          {text}
        </Link>
      ) : (
        <span className="mono">{text}</span>
      )}{" "}
      <span className="small faint">{x.status}</span>
    </span>
  );
}

const effText = (c: ChangeRequest) =>
  c.effectivity.mode === "date" ? `from ${c.effectivity.date ? fmtDate(c.effectivity.date) : t("mfg.ecoPages.str.aDateToChoose")}` : c.effectivity.mode === "serial" ? t("mfg.ecoPages.tpl.fromUnitSerial", { v: c.effectivity.serial_from ?? "?" }) : `when the old parts are used up${c.effectivity.date ? ` (${fmtDate(c.effectivity.date)})` : ""}`;

export function EcoListPage() {
  const navigate = useNavigate();
  const canEdit = useCan("eco_edit");
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const data = usePaged<ChangeRequest>((offset, limit, signal) => listEcos({ status: status || undefined, limit, offset }, signal), [status]);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    document.title = t("mfg.ecoPages.str.engineeringChangesSuperplanner");
  }, []);
  return (
    <div className="col gap-lg" data-testid="eco-list">
      <PageHeader
        title={t("mfg.ecoPages.title.engineeringChanges")}
        description={t("mfg.ecoPages.desc.changeBomsAndRoutingsIn")}
        actions={
          <>
            <button type="button" className="btn primary" disabled={!canEdit} title={canEdit ? undefined : needsText("eco_edit")} onClick={() => setCreating(true)} data-testid="eco-new">
            <Icon name="plus" /> {t("mfg.ecoPages.btn.newChangeRequest")}
            </button>
          </>
        }
      />
      <FilterBar>
        <div className="field">
          <span className="field-label" id="eco-status-label">
            {t("mfg.ecoPages.text.status")}
          </span>
          <div className="btn-group" role="group" aria-labelledby="eco-status-label">
            {(["", "draft", "submitted", "approved", "implemented"] as const).map((s) => (
              <button key={s || "all"} type="button" className="btn" aria-pressed={status === s} onClick={() => setSearchParam(setParams, "status", s)}>
                {s ? STATUS[s].label : t("mfg.ecoPages.str.all")}
              </button>
            ))}
          </div>
        </div>
      </FilterBar>
      <MfgError error={data.error} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={ECO_COLS}
        rowKey={(c) => c.id}
        label={t("mfg.ecoPages.label.changeRequests")}
        testId="eco-table"
        totalCount={data.total}
        loading={data.loading}
        onEndReached={data.onEndReached}
        exportName="change-requests"
        rowExtras={(c) => ({ testId: "eco-row", data: { status: c.status } })}
        empty={status ? t("mfg.ecoPages.str.noChangeRequestsWithThis") : t("mfg.ecoPages.str.noChangeRequestsYetCreate")}
        card={{ title: "change", status: "status", fields: ["effect", "docs", "by"] }}
      />
      {creating ? <CrDialog onClose={() => setCreating(false)} onSaved={(c) => navigate(mfgPaths.eco(c.id))} /> : null}
    </div>
  );
}

const ECO_COLS: Column<ChangeRequest>[] = [
  {
    key: "change",
    header: t("mfg.ecoPages.str.change"),
    width: "minmax(280px, 2fr)",
    exportValue: (c) => `${c.number} ${c.title}`,
    render: (c) => (
      <span className="mfg-ellipsis">
        <Link to={mfgPaths.eco(c.id)}>
          <span className="mono">{c.number}</span> {c.title}
        </Link>
        {c.source === "erp" ? <span className="small faint">{" "}{t("mfg.ecoPages.text.fromTheErp")}</span> : null}
      </span>
    ),
  },
  { key: "status", header: t("mfg.ecoPages.str.status"), width: "130px", exportValue: (c) => STATUS[c.status]?.label ?? c.status, render: (c) => <CrStatusChip s={c.status} /> },
  { key: "effect", header: t("mfg.ecoPages.str.takesEffect"), width: "minmax(160px, 1fr)", render: (c) => effText(c) },
  { key: "docs", header: t("mfg.ecoPages.str.documents"), width: "120px", render: (c) => (c.items.length ? `${plural(c.items.length, "document")}` : t("mfg.ecoPages.str.noneYet")) },
  { key: "by", header: t("mfg.ecoPages.str.requestedBy"), width: "minmax(140px, 1fr)", render: (c) => who(c.requested_by) },
];

function CrDialog({ cr, onClose, onSaved }: { cr?: ChangeRequest; onClose(): void; onSaved(c: ChangeRequest): void }) {
  const [f, setF] = useState<CrInput>(() => ({
    title: cr?.title ?? "",
    reason: cr?.reason ?? "",
    kind: cr?.kind ?? "eco",
    priority: cr?.priority ?? 3,
    effectivity: cr?.effectivity ?? { mode: "date", date: null },
    note: cr?.note ?? "",
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const e = f.effectivity;
  return (
    <Dialog
      title={cr ? t("mfg.ecoPages.tpl.edit", { number: cr.number }) : t("mfg.ecoPages.str.newChangeRequest")}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t("mfg.ecoPages.btn.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !f.title.trim()}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                onSaved(cr ? await updateEco(cr.id, f, cr.row_version) : await createEco(f));
              } catch (err) {
                setError(err);
                setBusy(false);
              }
            }}
            data-testid="eco-save"
          >
            {cr ? t("mfg.ecoPages.str.save") : t("mfg.ecoPages.str.create")}
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="cr-title">{t("mfg.ecoPages.label.whatChanges")}</label>
          <input id="cr-title" className="input" value={f.title} onChange={(ev) => setF({ ...f, title: ev.target.value })} placeholder={t("mfg.ecoPages.ph.egReplaceC12100nfWith")} data-testid="eco-title" />
        </div>
        <div className="field">
          <label htmlFor="cr-reason">{t("mfg.ecoPages.label.why")}</label>
          <textarea id="cr-reason" className="input" rows={2} value={f.reason} onChange={(ev) => setF({ ...f, reason: ev.target.value })} />
        </div>
        <fieldset className="mfg-fieldset">
          <legend>{t("mfg.ecoPages.head.takesEffect")}</legend>
          <div className="col" role="radiogroup" aria-label={t("mfg.ecoPages.aria.takesEffect")} style={{ gap: 4 }}>
            <label className="checkbox">
              <input type="radio" checked={e.mode === "date"} onChange={() => setF({ ...f, effectivity: { mode: "date", date: e.date ?? null } })} data-testid="eco-eff-date" />{" "}{t("mfg.ecoPages.text.onADate")}
            </label>
            <label className="checkbox">
              <input type="radio" checked={e.mode === "use_up"} onChange={() => setF({ ...f, effectivity: { mode: "use_up", date: e.date ?? null } })} data-testid="eco-eff-useup" />{" "}{t("mfg.ecoPages.text.whenTheOldPartsAre")}
            </label>
            <label className="checkbox">
              <input type="radio" checked={e.mode === "serial"} onChange={() => setF({ ...f, effectivity: { mode: "serial", serial_from: e.serial_from ?? null } })} />{" "}{t("mfg.ecoPages.text.fromAUnitSerialNumber")}
            </label>
          </div>
          {e.mode === "serial" ? (
            <div className="field" style={{ maxWidth: 220 }}>
              <label htmlFor="cr-serial">{t("mfg.ecoPages.label.firstSerialNumber")}</label>
              <input id="cr-serial" className="input" type="number" min={1} value={e.serial_from ?? ""} onChange={(ev) => setF({ ...f, effectivity: { mode: "serial", serial_from: ev.target.value ? Number(ev.target.value) : null } })} />
            </div>
          ) : (
            <div className="field" style={{ maxWidth: 220 }}>
              <label htmlFor="cr-date">{e.mode === "use_up" ? t("mfg.ecoPages.str.dateEmptyUseTheSuggestion") : t("mfg.ecoPages.str.date")}</label>
              <input id="cr-date" className="input" type="date" value={e.date ?? ""} onChange={(ev) => setF({ ...f, effectivity: { ...e, date: ev.target.value || null } })} data-testid="eco-date" />
            </div>
          )}
        </fieldset>
        <div className="row wrap">
          <div className="field">
            <label htmlFor="cr-kind">{t("mfg.ecoPages.label.kind")}</label>
            <select id="cr-kind" className="select" value={f.kind} onChange={(ev) => setF({ ...f, kind: ev.target.value as "eco" | "ecn" })}>
              <option value="eco">{t("mfg.ecoPages.text.changeOrderNeedsApproval")}</option>
              <option value="ecn">{t("mfg.ecoPages.text.changeNoticeDocumentation")}</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="cr-prio">{t("mfg.ecoPages.label.priority")}</label>
            <select id="cr-prio" className="select" value={f.priority} onChange={(ev) => setF({ ...f, priority: Number(ev.target.value) })}>
              {[1, 2, 3, 4, 5].map((p) => (
                <option key={p} value={p}>
                  P{p}
                  {p === 1 ? " (urgent)" : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
        <MfgError error={error} />
      </div>
    </Dialog>
  );
}

export function EcoPage() {
  const { ecoId = "" } = useParams();
  const access = useAccess();
  const canEdit = useCan("eco_edit");
  const canApprove = useCan("eco_approve");
  const cr = useLoad((signal) => getEco(ecoId, signal), [ecoId]);
  const [tab, setTab] = useState<"docs" | "impact">("docs");
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [issues, setIssues] = useState<ReleaseIssue[] | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [signingApprove, setSigningApprove] = useState(false);
  const [note, setNote] = useState("");
  // Part 11 (M7 review m4): every ECO action needs a reason; approval is signed per the plant's policy
  const part11 = usePart11().enabled;
  const reason = useChangeReason();
  const c = cr.data;
  useEffect(() => {
    if (c) document.title = `${c.number} - SuperPlanner`;
  }, [c]);
  if (cr.loading && !c) return <Spinner />;
  if (!c) return <MfgError error={cr.error} onRetry={cr.reload} />;
  const draft = c.status === "draft";
  const mine = Boolean(access.me && whoId(c.requested_by) === access.me.user_id);
  const selfApproveBlocked = mine && !access.isOwner && !(access.me?.roles ?? []).includes("plant_admin");

  const act = async (a: "submit" | "approve" | "reject" | "cancel" | "implement", body: { note?: string } = {}) => {
    if (a === "approve" && part11) {
      setSigningApprove(true);
      return;
    }
    // the reject note is the reason of a rejection; other actions ask for one in Part 11 mode
    const why = a === "reject" && body.note ? "" : await reason.ask(c.number);
    if (why === null) return;
    setBusy(true);
    setError(null);
    setIssues(null);
    try {
      cr.setData(await ecoAction(c.id, a, c.row_version, body, why));
    } catch (e) {
      if (e instanceof ApiError && e.code === "ECO_RELEASE_BLOCKED") setIssues((e.details.issues as ReleaseIssue[]) ?? []);
      else if (isConflict(e)) {
        setError(new Error(t("mfg.ecoPages.str.someoneChangedThisRequestMeanwhile")));
        cr.reload();
      } else setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="col gap-lg" data-testid="eco-page" data-status={c.status}>
      <nav className="breadcrumb" aria-label={t("mfg.ecoPages.aria.breadcrumb")}>
        <Link to={mfgPaths.ecos()}>{t("mfg.ecoPages.text.engineeringChanges")}</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{c.number}</span>
      </nav>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <div className="col" style={{ gap: 4 }}>
          <h1 style={{ margin: 0 }}>
            <span className="mono">{c.number}</span> {c.title}
          </h1>
          <span className="row wrap">
            <CrStatusChip s={c.status} />
            {c.source === "erp" ? <span className="badge info">{t("mfg.ecoPages.text.fromTheErp2")}</span> : null}
            <span className="small muted">
              {t("mfg.ecoPages.text.takesEffectP", { c: effText(c), priority: c.priority, v: c.requested_by ? t("mfg.ecoPages.tpl.requestedBy", { requestedby: who(c.requested_by) }) : "", v2: c.approved_by ? t("mfg.ecoPages.tpl.approvedBy", { approvedby: who(c.approved_by) }) : "", v3: c.implemented_at ? ` · implemented ${formatDate(c.implemented_at)}` : "" })}
            </span>
          </span>
        </div>
        <div className="row wrap" role="group" aria-label={t("mfg.ecoPages.aria.actions")}>
          {draft && canEdit ? (
            <>
              <button type="button" className="btn" onClick={() => setEditing(true)}>
                {t("mfg.ecoPages.btn.edit")}
              </button>
              <button type="button" className="btn primary" disabled={busy || !c.items.length} title={c.items.length ? undefined : t("mfg.ecoPages.str.addAtLeastOneDraft")} onClick={() => void act("submit")} data-testid="eco-submit">
                <Icon name="arrow-right" /> {t("mfg.ecoPages.btn.submitForApproval")}
              </button>
            </>
          ) : null}
          {c.status === "submitted" && canApprove ? (
            <>
              <button type="button" className="btn primary" disabled={busy || selfApproveBlocked} title={selfApproveBlocked ? t("mfg.ecoPages.str.youSubmittedItSomeoneElse") : undefined} onClick={() => void act("approve")} data-testid="eco-approve">
                <Icon name="check" /> {t("mfg.ecoPages.btn.approve")}
              </button>
              <button type="button" className="btn" disabled={busy} onClick={() => setRejecting(true)} data-testid="eco-reject">
                {t("mfg.ecoPages.btn.reject")}
              </button>
            </>
          ) : null}
          {c.status === "approved" && canEdit ? (
            <button type="button" className="btn primary" disabled={busy} onClick={() => void act("implement")} data-testid="eco-implement">
              <Icon name="play" /> {t("mfg.ecoPages.btn.implementNow")}
            </button>
          ) : null}
          {(draft || c.status === "submitted" || c.status === "approved") && canEdit ? (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act("cancel")} data-testid="eco-cancel">
              {t("mfg.ecoPages.btn.cancelRequest")}
            </button>
          ) : null}
        </div>
      </div>
      {c.reason ? <p style={{ margin: 0 }}>{c.reason}</p> : null}
      {c.status === "approved" ? <Banner tone="info" title={t("mfg.ecoPages.title.readyToImplement")}>{t("mfg.ecoPages.text.implementingReleasesEveryDraftBelow")}</Banner> : null}
      {issues ? (
        <Banner tone="danger" title={t("mfg.ecoPages.title.nothingWasReleasedFixThese")} testId="eco-release-blocked">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {issues.map((i, k) => (
              <li key={k}>
                {i.doc ? <strong>{i.doc}: </strong> : null}
                {i.message}
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}
      <MfgError error={error} />
      <nav className="tabs" aria-label={t("mfg.ecoPages.aria.changeRequest")}>
        <button type="button" className={`tab${tab === "docs" ? " active" : ""}`} aria-pressed={tab === "docs"} onClick={() => setTab("docs")}>
          {t("mfg.ecoPages.text.documents", { length: c.items.length })}
        </button>
        <button type="button" className={`tab${tab === "impact" ? " active" : ""}`} aria-pressed={tab === "impact"} onClick={() => setTab("impact")} data-testid="eco-tab-impact">
          {t("mfg.ecoPages.btn.impact")}
        </button>
      </nav>
      {tab === "docs" ? (
        <section className="card" data-testid="eco-docs">
          <div className="card-header">
            <h2>{t("mfg.ecoPages.head.draftVersionsInThisChange")}</h2>
            {draft && canEdit ? (
              <button type="button" className="btn sm primary" onClick={() => setAdding(true)} data-testid="eco-add-doc">
                <Icon name="plus" /> {t("mfg.ecoPages.btn.addADraft")}
              </button>
            ) : null}
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>{t("mfg.ecoPages.head.document")}</th>
                <th>{t("mfg.ecoPages.head.replaces")}</th>
                <th>{t("mfg.ecoPages.head.openWorkOrders")}</th>
                <th>{t("mfg.ecoPages.head.openPurchaseOrders")}</th>
                <th>{t("mfg.ecoPages.head.oldStock")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {c.items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    {t("mfg.ecoPages.text.noDraftsYetMakeA")}
                  </td>
                </tr>
              ) : null}
              {c.items.map((i) => (
                <DocRow key={i.id} c={c} i={i} editable={draft && canEdit} onChanged={cr.setData} />
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        <ImpactView c={c} onUseDate={async (d) => cr.setData(await updateEco(c.id, { title: c.title, reason: c.reason, kind: c.kind, priority: c.priority, note: c.note, effectivity: { mode: "use_up", date: d } }, c.row_version))} canEdit={draft && canEdit} />
      )}
      {editing ? <CrDialog cr={c} onClose={() => setEditing(false)} onSaved={(x) => { cr.setData(x); setEditing(false); }} /> : null}
      {adding ? <AddDocDialog c={c} onClose={() => setAdding(false)} onSaved={(x) => { cr.setData(x); setAdding(false); }} /> : null}
      {reason.dialog}
      {signingApprove ? (
        <SignatureDialog<ChangeRequest>
          title={t("mfg.ecoPages.tpl.approveTitle", { number: c.number })}
          recordType="eco"
          recordId={c.id}
          recordLabel={c.number}
          action="approve"
          meaning="approved"
          submitLabel={t("mfg.ecoPages.btn.signApprove")}
          plainLabel={t("mfg.ecoPages.btn.approve")}
          perform={(sig, comment) => signedAction<ChangeRequest>(`/eco/${encodeURIComponent(c.id)}/approve`, { note: comment }, { version: c.row_version, signature: sig, reason: comment })}
          onDone={(res) => {
            setSigningApprove(false);
            toast(signedToast(res, t("mfg.ecoPages.str.approved")));
            if (res.status === 200) cr.setData(res.record);
            else cr.reload();
          }}
          onClose={() => setSigningApprove(false)}
        />
      ) : null}
      {rejecting ? (
        <Dialog
          title={t("mfg.ecoPages.tpl.reject", { number: c.number })}
          onClose={() => setRejecting(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setRejecting(false)}>
                {t("mfg.ecoPages.btn.cancel")}
              </button>
              <button
                type="button"
                className="btn danger"
                disabled={!note.trim()}
                onClick={() => {
                  setRejecting(false);
                  void act("reject", { note: note.trim() });
                }}
              >
                {t("mfg.ecoPages.btn.reject")}
              </button>
            </>
          }
        >
          <div className="field">
            <label htmlFor="cr-note">{t("mfg.ecoPages.label.whySentToTheRequester")}</label>
            <input id="cr-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}

function DocRow({ c, i, editable, onChanged }: { c: ChangeRequest; i: CrItem; editable: boolean; onChanged(c: ChangeRequest): void }) {
  const [busy, setBusy] = useState(false);
  const D = i.disposition;
  const setDisp = async (patch: Partial<CrItem["disposition"]>) => {
    setBusy(true);
    try {
      // dispositions are set by re-adding the item (POST /eco/{id}/items replaces it for the same document)
      onChanged(await addEcoItem(c.id, { doc_type: i.doc_type, doc_id: i.doc_id, disposition: { ...D, ...patch } }));
    } finally {
      setBusy(false);
    }
  };
  return (
    <tr data-testid="eco-doc">
      <td>
        <span className="badge info">{i.doc_type === "bom" ? "BOM" : t("mfg.ecoPages.str.routing")}</span> <DocLabel type={i.doc_type} id={i.doc_id} link />
        {c.status === "draft" ? <div className="small faint">{t("mfg.ecoPages.text.lockedToThisRequestWhile")}</div> : null}
      </td>
      <td className="small">
        <DocLabel type={i.doc_type} id={i.supersedes_doc_id} />
      </td>
      <td>
        <select className="select sm" aria-label={t("mfg.ecoPages.aria.openWorkOrders")} value={D.open_wos} disabled={!editable || busy} onChange={(e) => void setDisp({ open_wos: e.target.value as CrItem["disposition"]["open_wos"] })}>
          <option value="keep">{t("mfg.ecoPages.text.keepAsTheyAre")}</option>
          <option value="refresh_planned">{t("mfg.ecoPages.text.updatePlannedOnes")}</option>
          <option value="flag">{t("mfg.ecoPages.text.flagForReview")}</option>
        </select>
      </td>
      <td>
        <select className="select sm" aria-label={t("mfg.ecoPages.aria.openPurchaseOrders")} value={D.open_pos} disabled={!editable || busy} onChange={(e) => void setDisp({ open_pos: e.target.value as CrItem["disposition"]["open_pos"] })}>
          <option value="keep">{t("mfg.ecoPages.text.keep")}</option>
          <option value="flag_cancel">{t("mfg.ecoPages.text.flagTheOnesNoLonger")}</option>
        </select>
      </td>
      <td>
        <select className="select sm" aria-label={t("mfg.ecoPages.aria.oldStock")} value={D.stock} disabled={!editable || busy} onChange={(e) => void setDisp({ stock: e.target.value as CrItem["disposition"]["stock"] })}>
          <option value="use_up">{t("mfg.ecoPages.text.useItUp")}</option>
          <option value="scrap">{t("mfg.ecoPages.text.scrapIt")}</option>
          <option value="rework">{t("mfg.ecoPages.text.reworkIt")}</option>
        </select>
      </td>
      <td>
        {editable ? (
          <button type="button" className="btn sm ghost" disabled={busy} onClick={async () => onChanged(await removeEcoItem(c.id, i.id))}>
            {t("mfg.ecoPages.btn.remove")}
          </button>
        ) : null}
      </td>
    </tr>
  );
}

function AddDocDialog({ c, onClose, onSaved }: { c: ChangeRequest; onClose(): void; onSaved(c: ChangeRequest): void }) {
  const [item, setItem] = useState<ItemRef | null>(null);
  const [type, setType] = useState<"bom" | "routing">("bom");
  const docs = useLoad(
    async (signal) => {
      if (!item) return null;
      const list = type === "bom" ? (await listItemBoms(item.id, signal)).items : (await listItemRoutings(item.id, signal)).items;
      return list.filter((d) => d.status === "draft").map((d) => ({ id: d.id, label: `rev ${d.revision} v${d.version}${"code" in d ? ` (${(d as { code: string }).code})` : ""}`, note: d.note }));
    },
    [item?.id, type],
  );
  const [doc, setDoc] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <Dialog
      title={t("mfg.ecoPages.title.addADraft")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t("mfg.ecoPages.btn.cancel")}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !doc}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                onSaved(await addEcoItem(c.id, { doc_type: type, doc_id: doc, disposition: { open_wos: "flag", open_pos: "flag_cancel", stock: "use_up" } }));
              } catch (e) {
                setError(e);
                setBusy(false);
              }
            }}
            data-testid="eco-doc-save"
          >
            {t("mfg.ecoPages.text.add")}
          </button>
        </>
      }
    >
      <div className="col">
        <div className="row" role="radiogroup" aria-label={t("mfg.ecoPages.aria.document")}>
          <label className="checkbox">
            <input type="radio" checked={type === "bom"} onChange={() => setType("bom")} /> BOM
          </label>
          <label className="checkbox">
            <input type="radio" checked={type === "routing"} onChange={() => setType("routing")} />{" "}{t("mfg.ecoPages.text.routing")}
          </label>
        </div>
        <ItemPicker value={item} onChange={(it) => { setItem(it); setDoc(""); }} label={t("mfg.ecoPages.label.item")} makeBuy="make" />
        {item ? (
          <div className="field">
            <label htmlFor="eco-doc">{t("mfg.ecoPages.label.draft")}</label>
            <select id="eco-doc" className="select" value={doc} onChange={(e) => setDoc(e.target.value)} data-testid="eco-doc-pick">
              <option value="">{docs.data?.length ? t("mfg.ecoPages.str.choose") : docs.loading ? t("mfg.ecoPages.str.loading") : t("mfg.ecoPages.str.noDraftsMakeOneWith")}</option>
              {(docs.data ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                  {d.note ? ` · ${d.note}` : ""}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <MfgError error={error ?? docs.error} />
      </div>
    </Dialog>
  );
}

const entryText = (e: string | { item: string; qty?: number; qty_before?: number; qty_after?: number }) =>
  typeof e === "string" ? e : e.qty_before !== undefined ? `${e.item} ${fmtNum(e.qty_before)} → ${fmtNum(e.qty_after ?? 0)}` : `${e.item}${e.qty !== undefined ? ` x ${fmtNum(e.qty)}` : ""}`;

function ImpactView({ c, onUseDate, canEdit }: { c: ChangeRequest; onUseDate(d: string): Promise<void>; canEdit: boolean }) {
  const imp = useLoad((signal) => (c.items.length ? getEcoImpact(c.id, signal) : null), [c.id, c.row_version]);
  const d: EcoImpact | null = imp.data;
  if (!c.items.length) return <p className="muted">{t("mfg.ecoPages.text.addADraftToSee")}</p>;
  if (imp.loading && !d) return <Spinner label={t("mfg.ecoPages.label.workingOutTheImpactIncl")} />;
  if (!d) return <MfgError error={imp.error} onRetry={imp.reload} />;
  return (
    <div className="col gap-lg" data-testid="eco-impact">
      {d.use_up_date ? (
        <Banner
          tone="info"
          title={t("mfg.ecoPages.tpl.oldPartsRunOutAround", { useupdate: fmtDate(d.use_up_date) })}
          testId="eco-useup"
          actions={
            canEdit && c.effectivity.mode !== "serial" && c.effectivity.date !== d.use_up_date ? (
              <button type="button" className="btn sm" onClick={() => void onUseDate(d.use_up_date!)} data-testid="eco-use-date">
                {t("mfg.ecoPages.btn.takeEffectOnThatDate")}
              </button>
            ) : null
          }
        >
          {t("mfg.ecoPages.text.firstDayTheProjectedStock")}
        </Banner>
      ) : null}
      <section className="card card-table">
        <div className="card-header">
          <h2>{t("mfg.ecoPages.head.whatChangesInTheStructure")}</h2>
        </div>
        <DataTable
          rows={d.explosion_delta}
          columns={[
            { key: "parent", header: "Assembly", width: "minmax(160px, 1fr)", sortValue: (x) => x.parent, render: (x) => <span className="mono">{x.parent}</span> },
            {
              key: "changes",
              header: "Component changes",
              width: "minmax(280px, 3fr)",
              wrap: true,
              exportValue: (x) => [...x.added.map((a) => `+${entryText(a)}`), ...x.removed.map((a) => `-${entryText(a)}`), ...x.changed.map((a) => `~${entryText(a)}`)].join("; "),
              render: (x) => (
                <span className="col" style={{ gap: 2 }}>
                  {x.added.map((a, k) => (
                    <span key={`a${k}`}>
                      <span className="badge ok">
                        <Icon name="plus" size={12} /> {t("mfg.ecoPages.btn.added")}
                      </span>{" "}
                      <span className="mono">{entryText(a)}</span>
                    </span>
                  ))}
                  {x.removed.map((a, k) => (
                    <span key={`r${k}`}>
                      <span className="badge danger">
                        <Icon name="x" size={12} /> {t("mfg.ecoPages.btn.removed")}
                      </span>{" "}
                      <span className="mono">{entryText(a)}</span>
                    </span>
                  ))}
                  {x.changed.map((a, k) => (
                    <span key={`c${k}`}>
                      <span className="badge warn">
                        <Icon name="refresh" size={12} /> {t("mfg.ecoPages.btn.changed")}
                      </span>{" "}
                      <span className="mono">{entryText(a)}</span>
                    </span>
                  ))}
                </span>
              ),
            },
          ]}
          rowKey={(_, i) => i}
          label={t("mfg.ecoPages.label.whatChangesInTheStructure")}
          testId="eco-delta"
          exportName={`${c.number}-structure-changes`}
          empty={t("mfg.ecoPages.empty.noComponentChanges")}
        />
      </section>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <section className="card card-table">
          <div className="card-header">
            <h2>{t("mfg.ecoPages.text.openWorkOrdersUsingThe", { length: d.open_wos.length })}</h2>
          </div>
          <DataTable
            rows={[
              ...d.open_wos.map((w) => ({ id: w.id, number: w.number, part: w.component ?? "", qty: w.qty })),
              ...d.planned_orders.map((p) => ({ id: undefined as string | undefined, number: p.number ?? "planned", part: p.item ?? "", qty: p.qty })),
            ]}
            columns={[
              { key: "order", header: "Order", width: "minmax(130px, 1fr)", sortValue: (w) => w.number, exportValue: (w) => w.number, render: (w) => <span className="mono">{w.id ? <Link to={mfgPaths.workOrder(w.id)}>{w.number}</Link> : w.number}</span> },
              { key: "part", header: "Old part", width: "minmax(130px, 1fr)", sortValue: (w) => w.part, render: (w) => <span className="mono small">{w.part}</span> },
              { key: "qty", header: "Qty", width: "90px", align: "right", sortValue: (w) => w.qty ?? null, render: (w) => (w.qty !== undefined ? fmtNum(w.qty) : "") },
            ]}
            rowKey={(_, i) => i}
            label={t("mfg.ecoPages.label.openWorkOrdersUsingThe")}
            testId="eco-open-wos"
            exportName={`${c.number}-open-orders`}
            empty={t("mfg.ecoPages.empty.none")}
          />
        </section>
        <section className="card card-table">
          <div className="card-header">
            <h2>{t("mfg.ecoPages.text.purchasesNoLongerNeeded", { length: d.open_purchases.length })}</h2>
          </div>
          <DataTable
            rows={d.open_purchases}
            columns={[
              { key: "doc", header: "Purchase order", width: "minmax(130px, 1fr)", sortValue: (p) => p.number, render: (p) => <span className="mono">{p.number}</span> },
              { key: "item", header: "Part", width: "minmax(120px, 1fr)", sortValue: (p) => p.item ?? "", render: (p) => <span className="mono">{p.item ?? ""}</span> },
              { key: "qty", header: "Qty", width: "80px", align: "right", sortValue: (p) => p.qty ?? null, render: (p) => (p.qty !== undefined ? fmtNum(p.qty) : "") },
              { key: "due", header: "Due", width: "110px", sortValue: (p) => p.due ?? null, render: (p) => (p.due ? fmtDate(p.due) : "") },
            ]}
            rowKey={(_, i) => i}
            label={t("mfg.ecoPages.label.purchasesNoLongerNeeded")}
            tableId="eco-open-purchases"
            exportName={`${c.number}-purchases`}
            empty={t("mfg.ecoPages.empty.none")}
          />
        </section>
      </div>
      <section className="card card-table">
        <div className="card-header">
          <h2>{t("mfg.ecoPages.head.partsBeingPhasedOut")}</h2>
        </div>
        <DataTable
          rows={d.phase_out_stock}
          columns={[
            { key: "item", header: "Part", width: "minmax(160px, 2fr)", sortValue: (p) => p.item, render: (p) => <span className="mono">{p.item}</span> },
            { key: "on_hand", header: "In stock", width: "110px", align: "right", sortValue: (p) => p.on_hand, render: (p) => fmtNum(p.on_hand) },
            { key: "on_order", header: "On order", width: "110px", align: "right", sortValue: (p) => p.on_order, render: (p) => fmtNum(p.on_order) },
            { key: "value", header: "Value", width: "120px", align: "right", sortValue: (p) => p.value, render: (p) => (p.value === null ? "" : fmtNum(Math.round(p.value))) },
          ]}
          rowKey={(_, i) => i}
          label={t("mfg.ecoPages.label.partsBeingPhasedOut")}
          testId="eco-phased-out"
          exportName={`${c.number}-phase-out`}
          empty={t("mfg.ecoPages.empty.noPartsArePhasedOut")}
        />
      </section>
      {d.mrp_delta.length ? (
        <section className="card card-table">
          <div className="card-header">
            <h2>{t("mfg.ecoPages.head.customerDatesThatMoveMrp")}</h2>
          </div>
          <DataTable
            rows={d.mrp_delta}
            columns={[
              { key: "order", header: "Demand", width: "minmax(160px, 1fr)", sortValue: (m) => m.order ?? m.demand_line ?? "", render: (m) => <span className="mono">{m.order ?? m.demand_line}</span> },
              { key: "before", header: "Before", width: "130px", sortValue: (m) => m.before ?? null, render: (m) => (m.before ? fmtDate(m.before) : "—") },
              { key: "after", header: "After", width: "130px", sortValue: (m) => m.after ?? null, render: (m) => (m.after ? fmtDate(m.after) : "not covered") },
            ]}
            rowKey={(_, i) => i}
            label={t("mfg.ecoPages.label.customerDatesThatMove")}
            testId="eco-mrp-delta"
            exportName={`${c.number}-date-changes`}
          />
        </section>
      ) : null}
      {d.computed_ms ? <p className="faint small">{t("mfg.ecoPages.text.workedOutInS", { toFixed: (d.computed_ms / 1000).toFixed(1) })}</p> : null}
    </div>
  );
}
