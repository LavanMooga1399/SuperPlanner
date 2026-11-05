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

const STATUS: Record<CrStatus, { label: string; tone: string; icon: IconName }> = {
  draft: { label: "Draft", tone: "info", icon: "file" },
  submitted: { label: "Waiting for approval", tone: "warn", icon: "clock" },
  approved: { label: "Approved", tone: "accent", icon: "check" },
  rejected: { label: "Rejected", tone: "danger", icon: "x" },
  implemented: { label: "Implemented", tone: "ok", icon: "check" },
  cancelled: { label: "Cancelled", tone: "info", icon: "ban" },
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
  if (!id) return <span className="faint">nothing (new)</span>;
  const x = d.data as { item: ItemRef; revision: string; version: number; status: string } | null;
  if (!x) return <span className="mono small">{id}</span>;
  const text = `${x.item.part_number} rev ${x.revision} v${x.version}`;
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
  c.effectivity.mode === "date" ? `from ${c.effectivity.date ? fmtDate(c.effectivity.date) : "a date to choose"}` : c.effectivity.mode === "serial" ? `from unit serial ${c.effectivity.serial_from ?? "?"}` : `when the old parts are used up${c.effectivity.date ? ` (${fmtDate(c.effectivity.date)})` : ""}`;

export function EcoListPage() {
  const navigate = useNavigate();
  const canEdit = useCan("eco_edit");
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const data = usePaged<ChangeRequest>((offset, limit, signal) => listEcos({ status: status || undefined, limit, offset }, signal), [status]);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    document.title = "Engineering changes - SuperPlanner";
  }, []);
  return (
    <div className="col gap-lg" data-testid="eco-list">
      <div className="mfg-page-head">
        <div>
          <h1>Engineering changes</h1>
          <p>Change BOMs and routings in a controlled way: see the impact, get approval, switch over on a date or serial number.</p>
        </div>
        <button type="button" className="btn primary" disabled={!canEdit} title={canEdit ? undefined : needsText("eco_edit")} onClick={() => setCreating(true)} data-testid="eco-new">
          <Icon name="plus" /> New change request
        </button>
      </div>
      <div className="row wrap" role="group" aria-label="Status">
        {(["", "draft", "submitted", "approved", "implemented"] as const).map((s) => (
          <button key={s || "all"} type="button" className={`btn sm${status === s ? " primary" : ""}`} aria-pressed={status === s} onClick={() => setSearchParam(setParams, "status", s)}>
            {s ? STATUS[s].label : "All"}
          </button>
        ))}
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="eco-table">
          <thead>
            <tr>
              <th>Change</th>
              <th>Status</th>
              <th>Takes effect</th>
              <th>Documents</th>
              <th>Requested by</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  {data.loading ? "Loading…" : "No change requests."}
                </td>
              </tr>
            ) : null}
            {data.rows.map((c) => (
              <tr key={c.id} data-testid="eco-row" data-status={c.status}>
                <td>
                  <Link to={mfgPaths.eco(c.id)}>
                    <span className="mono">{c.number}</span> {c.title}
                  </Link>
                  {c.source === "erp" ? <div className="small faint">from the ERP</div> : null}
                </td>
                <td>
                  <CrStatusChip s={c.status} />
                </td>
                <td className="small">{effText(c)}</td>
                <td className="small">{c.items.length ? `${c.items.length} document${c.items.length === 1 ? "" : "s"}` : "none yet"}</td>
                <td className="small">{who(c.requested_by)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {creating ? <CrDialog onClose={() => setCreating(false)} onSaved={(c) => navigate(mfgPaths.eco(c.id))} /> : null}
    </div>
  );
}

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
      title={cr ? `Edit ${cr.number}` : "New change request"}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
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
            {cr ? "Save" : "Create"}
          </button>
        </>
      }
    >
      <div className="col">
        <div className="field">
          <label htmlFor="cr-title">What changes</label>
          <input id="cr-title" className="input" value={f.title} onChange={(ev) => setF({ ...f, title: ev.target.value })} placeholder="e.g. Replace C12 100nF with 220nF on KV-PCB-CPU" data-testid="eco-title" />
        </div>
        <div className="field">
          <label htmlFor="cr-reason">Why</label>
          <textarea id="cr-reason" className="input" rows={2} value={f.reason} onChange={(ev) => setF({ ...f, reason: ev.target.value })} />
        </div>
        <fieldset className="mfg-fieldset">
          <legend>Takes effect</legend>
          <div className="col" role="radiogroup" aria-label="Takes effect" style={{ gap: 4 }}>
            <label className="checkbox">
              <input type="radio" checked={e.mode === "date"} onChange={() => setF({ ...f, effectivity: { mode: "date", date: e.date ?? null } })} data-testid="eco-eff-date" /> On a date
            </label>
            <label className="checkbox">
              <input type="radio" checked={e.mode === "use_up"} onChange={() => setF({ ...f, effectivity: { mode: "use_up", date: e.date ?? null } })} data-testid="eco-eff-useup" /> When the old parts are used up (date suggested from MRP)
            </label>
            <label className="checkbox">
              <input type="radio" checked={e.mode === "serial"} onChange={() => setF({ ...f, effectivity: { mode: "serial", serial_from: e.serial_from ?? null } })} /> From a unit serial number
            </label>
          </div>
          {e.mode === "serial" ? (
            <div className="field" style={{ maxWidth: 220 }}>
              <label htmlFor="cr-serial">First serial number</label>
              <input id="cr-serial" className="input" type="number" min={1} value={e.serial_from ?? ""} onChange={(ev) => setF({ ...f, effectivity: { mode: "serial", serial_from: ev.target.value ? Number(ev.target.value) : null } })} />
            </div>
          ) : (
            <div className="field" style={{ maxWidth: 220 }}>
              <label htmlFor="cr-date">{e.mode === "use_up" ? "Date (empty = use the suggestion)" : "Date"}</label>
              <input id="cr-date" className="input" type="date" value={e.date ?? ""} onChange={(ev) => setF({ ...f, effectivity: { ...e, date: ev.target.value || null } })} data-testid="eco-date" />
            </div>
          )}
        </fieldset>
        <div className="row wrap">
          <div className="field">
            <label htmlFor="cr-kind">Kind</label>
            <select id="cr-kind" className="select" value={f.kind} onChange={(ev) => setF({ ...f, kind: ev.target.value as "eco" | "ecn" })}>
              <option value="eco">Change order (needs approval)</option>
              <option value="ecn">Change notice (documentation)</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="cr-prio">Priority</label>
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
  const [note, setNote] = useState("");
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
    setBusy(true);
    setError(null);
    setIssues(null);
    try {
      cr.setData(await ecoAction(c.id, a, c.row_version, body));
    } catch (e) {
      if (e instanceof ApiError && e.code === "ECO_RELEASE_BLOCKED") setIssues((e.details.issues as ReleaseIssue[]) ?? []);
      else if (isConflict(e)) {
        setError(new Error("Someone changed this request meanwhile; it has been reloaded."));
        cr.reload();
      } else setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="col gap-lg" data-testid="eco-page" data-status={c.status}>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to={mfgPaths.ecos()}>Engineering changes</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{c.number}</span>
      </nav>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <div className="col" style={{ gap: 4 }}>
          <h1 style={{ margin: 0 }}>
            <span className="mono">{c.number}</span> {c.title}
          </h1>
          <span className="row wrap">
            <CrStatusChip s={c.status} />
            {c.source === "erp" ? <span className="badge info">from the ERP</span> : null}
            <span className="small muted">
              Takes effect {effText(c)} · P{c.priority}
              {c.requested_by ? ` · requested by ${who(c.requested_by)}` : ""}
              {c.approved_by ? ` · approved by ${who(c.approved_by)}` : ""}
              {c.implemented_at ? ` · implemented ${new Date(c.implemented_at).toLocaleDateString()}` : ""}
            </span>
          </span>
        </div>
        <div className="row wrap" role="group" aria-label="Actions">
          {draft && canEdit ? (
            <>
              <button type="button" className="btn" onClick={() => setEditing(true)}>
                Edit
              </button>
              <button type="button" className="btn primary" disabled={busy || !c.items.length} title={c.items.length ? undefined : "Add at least one draft BOM or routing"} onClick={() => void act("submit")} data-testid="eco-submit">
                <Icon name="arrow-right" /> Submit for approval
              </button>
            </>
          ) : null}
          {c.status === "submitted" && canApprove ? (
            <>
              <button type="button" className="btn primary" disabled={busy || selfApproveBlocked} title={selfApproveBlocked ? "You submitted it: someone else approves" : undefined} onClick={() => void act("approve")} data-testid="eco-approve">
                <Icon name="check" /> Approve
              </button>
              <button type="button" className="btn" disabled={busy} onClick={() => setRejecting(true)} data-testid="eco-reject">
                Reject
              </button>
            </>
          ) : null}
          {c.status === "approved" && canEdit ? (
            <button type="button" className="btn primary" disabled={busy} onClick={() => void act("implement")} data-testid="eco-implement">
              <Icon name="play" /> Implement now
            </button>
          ) : null}
          {(draft || c.status === "submitted" || c.status === "approved") && canEdit ? (
            <button type="button" className="btn ghost" disabled={busy} onClick={() => void act("cancel")} data-testid="eco-cancel">
              Cancel request
            </button>
          ) : null}
        </div>
      </div>
      {c.reason ? <p style={{ margin: 0 }}>{c.reason}</p> : null}
      {c.status === "approved" ? <Banner tone="info" title="Ready to implement">Implementing releases every draft below at once with the effectivity above and supersedes the current versions. If any draft fails the release checks, nothing is released.</Banner> : null}
      {issues ? (
        <Banner tone="danger" title="Nothing was released: fix these first" testId="eco-release-blocked">
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
      <nav className="tabs" aria-label="Change request">
        <button type="button" className={`tab${tab === "docs" ? " active" : ""}`} aria-pressed={tab === "docs"} onClick={() => setTab("docs")}>
          Documents ({c.items.length})
        </button>
        <button type="button" className={`tab${tab === "impact" ? " active" : ""}`} aria-pressed={tab === "impact"} onClick={() => setTab("impact")} data-testid="eco-tab-impact">
          Impact
        </button>
      </nav>
      {tab === "docs" ? (
        <section className="card" data-testid="eco-docs">
          <div className="card-header">
            <h2>Draft versions in this change</h2>
            {draft && canEdit ? (
              <button type="button" className="btn sm primary" onClick={() => setAdding(true)} data-testid="eco-add-doc">
                <Icon name="plus" /> Add a draft
              </button>
            ) : null}
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Replaces</th>
                <th>Open work orders</th>
                <th>Open purchase orders</th>
                <th>Old stock</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {c.items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    No drafts yet. Make a draft with "Copy as draft" on the item's BOM or routing, then add it here. Added drafts can only be edited while this request is a draft.
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
      {rejecting ? (
        <Dialog
          title={`Reject ${c.number}?`}
          onClose={() => setRejecting(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setRejecting(false)}>
                Cancel
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
                Reject
              </button>
            </>
          }
        >
          <div className="field">
            <label htmlFor="cr-note">Why (sent to the requester)</label>
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
        <span className="badge info">{i.doc_type === "bom" ? "BOM" : "Routing"}</span> <DocLabel type={i.doc_type} id={i.doc_id} link />
        {c.status === "draft" ? <div className="small faint">locked to this request while it is a draft</div> : null}
      </td>
      <td className="small">
        <DocLabel type={i.doc_type} id={i.supersedes_doc_id} />
      </td>
      <td>
        <select className="select sm" aria-label="Open work orders" value={D.open_wos} disabled={!editable || busy} onChange={(e) => void setDisp({ open_wos: e.target.value as CrItem["disposition"]["open_wos"] })}>
          <option value="keep">Keep as they are</option>
          <option value="refresh_planned">Update planned ones</option>
          <option value="flag">Flag for review</option>
        </select>
      </td>
      <td>
        <select className="select sm" aria-label="Open purchase orders" value={D.open_pos} disabled={!editable || busy} onChange={(e) => void setDisp({ open_pos: e.target.value as CrItem["disposition"]["open_pos"] })}>
          <option value="keep">Keep</option>
          <option value="flag_cancel">Flag the ones no longer needed</option>
        </select>
      </td>
      <td>
        <select className="select sm" aria-label="Old stock" value={D.stock} disabled={!editable || busy} onChange={(e) => void setDisp({ stock: e.target.value as CrItem["disposition"]["stock"] })}>
          <option value="use_up">Use it up</option>
          <option value="scrap">Scrap it</option>
          <option value="rework">Rework it</option>
        </select>
      </td>
      <td>
        {editable ? (
          <button type="button" className="btn sm ghost" disabled={busy} onClick={async () => onChanged(await removeEcoItem(c.id, i.id))}>
            Remove
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
      title="Add a draft"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
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
            Add
          </button>
        </>
      }
    >
      <div className="col">
        <div className="row" role="radiogroup" aria-label="Document">
          <label className="checkbox">
            <input type="radio" checked={type === "bom"} onChange={() => setType("bom")} /> BOM
          </label>
          <label className="checkbox">
            <input type="radio" checked={type === "routing"} onChange={() => setType("routing")} /> Routing
          </label>
        </div>
        <ItemPicker value={item} onChange={(it) => { setItem(it); setDoc(""); }} label="Item" makeBuy="make" />
        {item ? (
          <div className="field">
            <label htmlFor="eco-doc">Draft</label>
            <select id="eco-doc" className="select" value={doc} onChange={(e) => setDoc(e.target.value)} data-testid="eco-doc-pick">
              <option value="">{docs.data?.length ? "Choose…" : docs.loading ? "Loading…" : "No drafts: make one with Copy as draft first"}</option>
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
  if (!c.items.length) return <p className="muted">Add a draft to see what it changes.</p>;
  if (imp.loading && !d) return <Spinner label="Working out the impact (incl. an MRP what-if)…" />;
  if (!d) return <MfgError error={imp.error} onRetry={imp.reload} />;
  return (
    <div className="col gap-lg" data-testid="eco-impact">
      {d.use_up_date ? (
        <Banner
          tone="info"
          title={`Old parts run out around ${fmtDate(d.use_up_date)}`}
          testId="eco-useup"
          actions={
            canEdit && c.effectivity.mode !== "serial" && c.effectivity.date !== d.use_up_date ? (
              <button type="button" className="btn sm" onClick={() => void onUseDate(d.use_up_date!)} data-testid="eco-use-date">
                Take effect on that date
              </button>
            ) : null
          }
        >
          First day the projected stock of the phased-out part reaches zero in the latest MRP run.
        </Banner>
      ) : null}
      <section className="card">
        <div className="card-header">
          <h2>What changes in the structure</h2>
        </div>
        <table className="table" data-testid="eco-delta">
          <tbody>
            {d.explosion_delta.length === 0 ? (
              <tr>
                <td className="muted">No component changes.</td>
              </tr>
            ) : null}
            {d.explosion_delta.map((x, i) => (
              <tr key={i}>
                <td className="mono">{x.parent}</td>
                <td className="small">
                  {x.added.map((a, k) => (
                    <div key={`a${k}`}>
                      <span className="badge ok">
                        <Icon name="plus" size={12} /> added
                      </span>{" "}
                      <span className="mono">{entryText(a)}</span>
                    </div>
                  ))}
                  {x.removed.map((a, k) => (
                    <div key={`r${k}`}>
                      <span className="badge danger">
                        <Icon name="x" size={12} /> removed
                      </span>{" "}
                      <span className="mono">{entryText(a)}</span>
                    </div>
                  ))}
                  {x.changed.map((a, k) => (
                    <div key={`c${k}`}>
                      <span className="badge warn">
                        <Icon name="refresh" size={12} /> changed
                      </span>{" "}
                      <span className="mono">{entryText(a)}</span>
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <section className="card">
          <div className="card-header">
            <h2>Open work orders using the old parts ({d.open_wos.length})</h2>
          </div>
          <table className="table" data-testid="eco-open-wos">
            <tbody>
              {d.open_wos.map((w, i) => (
                <tr key={i}>
                  <td className="mono">{w.id ? <Link to={mfgPaths.workOrder(w.id)}>{w.number}</Link> : w.number}</td>
                  <td className="mono small">{w.component ?? ""}</td>
                  <td className="right">{w.qty !== undefined ? fmtNum(w.qty) : ""}</td>
                </tr>
              ))}
              {d.planned_orders.map((p, i) => (
                <tr key={`p${i}`}>
                  <td className="mono">{p.number ?? "planned"}</td>
                  <td className="mono small">{p.item ?? ""}</td>
                  <td className="right">{p.qty !== undefined ? fmtNum(p.qty) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="card">
          <div className="card-header">
            <h2>Purchases no longer needed ({d.open_purchases.length})</h2>
          </div>
          <table className="table">
            <tbody>
              {d.open_purchases.map((p, i) => (
                <tr key={i}>
                  <td className="mono">{p.number}</td>
                  <td className="mono">{p.item ?? ""}</td>
                  <td className="right">{p.qty !== undefined ? fmtNum(p.qty) : ""}</td>
                  <td className="small">{p.due ? fmtDate(p.due) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
      <section className="card">
        <div className="card-header">
          <h2>Parts being phased out</h2>
        </div>
        <table className="table" data-testid="eco-phased-out">
          <thead>
            <tr>
              <th>Part</th>
              <th className="right">In stock</th>
              <th className="right">On order</th>
              <th className="right">Value</th>
            </tr>
          </thead>
          <tbody>
            {d.phase_out_stock.map((p, i) => (
              <tr key={i}>
                <td className="mono">{p.item}</td>
                <td className="right">{fmtNum(p.on_hand)}</td>
                <td className="right">{fmtNum(p.on_order)}</td>
                <td className="right">{p.value === null ? "" : fmtNum(Math.round(p.value))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {d.mrp_delta.length ? (
        <section className="card">
          <div className="card-header">
            <h2>Customer dates that move (MRP what-if)</h2>
          </div>
          <table className="table" data-testid="eco-mrp-delta">
            <tbody>
              {d.mrp_delta.map((m, i) => (
                <tr key={i}>
                  <td className="mono">{m.order ?? m.demand_line}</td>
                  <td className="small">
                    {m.before ? fmtDate(m.before) : "—"} → {m.after ? fmtDate(m.after) : "not covered"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
      {d.computed_ms ? <p className="faint small">Worked out in {(d.computed_ms / 1000).toFixed(1)} s.</p> : null}
    </div>
  );
}
