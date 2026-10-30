/**
 * `/mfg/purchasing/{orders|requests}/{new|:docId}?line=&schedule=` (M2 14.2, 5): header, lines with staggered
 * deliveries, status actions (PR submit / approve / reject / revise / cancel / convert; PO issue / close /
 * cancel), Receive (PO) and receipt history. Actions are offered by status and role; the server is the
 * authority (409 wrong state, 403 role, 412 changed meanwhile -> reload banner).
 */
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Dialog } from "../../../components/Dialog";
import { Icon, type IconName } from "../../../components/Icon";
import {
  convertPr,
  createPurchaseDoc,
  deletePurchaseDoc,
  getPurchaseDoc,
  newIdempotencyKey,
  purchaseAction,
  updatePurchaseDoc,
  type PoAction,
  type PrAction,
} from "../../api/clientM2";
import type { Ref } from "../../api/types";
import type { DocType, Permission, PurchaseDocInput, PurchaseDocRecord, PurchaseStatus } from "../../api/typesM2";
import { DocLinesEditor, linesFromRecord, linesProblems, linesToInput, newDocLine, type LineDraft } from "../../components/DocLinesEditor";
import { ConflictBanner, MfgError, NotFoundPanel, Spinner } from "../../components/Feedback";
import { strOrNull, TextField } from "../../components/Field";
import { SupplierPicker } from "../../components/PickersM2";
import { ReceiveDialog } from "../../components/ReceiveDialog";
import { OverdueBadge, PurchaseStatusChip, SourceBadge } from "../../components/StatusM2";
import { fmtDate, fmtTimestamp } from "../../lib/format";
import { fmtMoney, POSTING_LABEL } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { needsText, useAccess } from "../../lib/permissions";
import { isConflict, isNotFound, useLoad } from "../../lib/useMfg";

const EDITABLE: Record<DocType, PurchaseStatus[]> = { pr: ["draft", "rejected"], po: ["draft", "open", "partially_received"] };

interface ActionDef {
  key: PrAction | PoAction | "convert" | "receive" | "delete";
  label: string;
  perm: Permission;
  from: PurchaseStatus[];
  icon: IconName;
  primary?: boolean;
  danger?: boolean;
  confirm?: string;
}

const PR_ACTIONS: ActionDef[] = [
  { key: "submit", label: "Submit for approval", perm: "pr_edit", from: ["draft"], icon: "arrow-right", primary: true },
  { key: "approve", label: "Approve", perm: "pr_approve", from: ["submitted"], icon: "check", primary: true },
  { key: "reject", label: "Reject", perm: "pr_approve", from: ["submitted"], icon: "x" },
  { key: "convert", label: "Convert to purchase order", perm: "po_edit", from: ["approved"], icon: "briefcase", primary: true },
  { key: "revise", label: "Back to draft", perm: "pr_edit", from: ["submitted", "rejected"], icon: "refresh" },
  { key: "cancel", label: "Cancel request", perm: "pr_edit", from: ["draft", "submitted", "approved", "rejected"], icon: "ban", confirm: "The request and its open lines are cancelled. Lines already converted stay on their purchase orders." },
  { key: "delete", label: "Delete", perm: "pr_edit", from: ["draft", "cancelled"], icon: "trash", danger: true, confirm: "The request is deleted for good." },
];

const PO_ACTIONS: ActionDef[] = [
  { key: "issue", label: "Issue to supplier", perm: "po_edit", from: ["draft"], icon: "arrow-right", primary: true, confirm: "The order becomes open: its deliveries are expected and can be received." },
  { key: "receive", label: "Receive", perm: "inventory", from: ["open", "partially_received"], icon: "download", primary: true },
  { key: "close", label: "Close", perm: "po_edit", from: ["open", "partially_received", "received"], icon: "lock", confirm: "Deliveries still open are closed and are no longer expected (short close)." },
  { key: "cancel", label: "Cancel order", perm: "po_edit", from: ["draft", "open"], icon: "ban", confirm: "The order is cancelled. Orders with receipts cannot be cancelled; close them instead." },
  { key: "delete", label: "Delete", perm: "po_edit", from: ["draft"], icon: "trash", danger: true, confirm: "The draft order is deleted for good." },
];

interface Header {
  number: string;
  supplier: Ref | null;
  currency: string;
  order_date: string;
  note: string;
  external_ref: string;
}

function headerOf(d: PurchaseDocRecord | null): Header {
  return {
    number: d?.number ?? "",
    supplier: d?.supplier ?? null,
    currency: d?.currency ?? "",
    order_date: d?.order_date ?? "",
    note: d?.note ?? "",
    external_ref: d?.external_ref ?? "",
  };
}

function ConvertDialog({ pr, onClose, onDone }: { pr: PurchaseDocRecord; onClose(): void; onDone(poId: string): void }) {
  const open = pr.lines.filter((l) => l.status === "open");
  const [ids, setIds] = useState<Set<string>>(new Set(open.map((l) => l.id)));
  const [supplier, setSupplier] = useState<Ref | null>(pr.supplier);
  const [number, setNumber] = useState("");
  const [issue, setIssue] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const key = useRef(newIdempotencyKey("conv"));
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await convertPr(
        pr.id,
        { line_ids: ids.size === open.length ? null : [...ids], supplier_id: supplier?.id ?? null, number: strOrNull(number), issue },
        pr.row_version,
        key.current,
      );
      onDone(r.po.id);
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={`Convert ${pr.number} to a purchase order`}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={busy || ids.size === 0} data-testid="convert-pr-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="briefcase" />} Create purchase order
          </button>
        </>
      }
    >
      <div className="col">
        <p className="muted small" style={{ margin: 0 }}>
          One purchase order line is created per request line, with the same deliveries and the supplier's price.
        </p>
        <fieldset className="mfg-fieldset">
          <legend>Lines</legend>
          {open.map((l) => (
            <label key={l.id} className="checkbox">
              <input
                type="checkbox"
                checked={ids.has(l.id)}
                onChange={(e) =>
                  setIds((s) => {
                    const n = new Set(s);
                    if (e.target.checked) n.add(l.id);
                    else n.delete(l.id);
                    return n;
                  })
                }
              />
              <span className="mono">{l.line_no}</span> {l.item.part_number} · {l.qty} {l.item.uom}
            </label>
          ))}
        </fieldset>
        <div className="form-grid">
          <SupplierPicker label="Supplier" value={supplier} onChange={setSupplier} allowClear testId="convert-pr-supplier" />
          <TextField label="Order number" value={number} onChange={setNumber} maxLength={32} placeholder="Next free number" hint="Empty = next number of the series" />
        </div>
        {!supplier ? <p className="hint" style={{ margin: 0 }}>Without a supplier, the preferred supplier common to all chosen parts is used.</p> : null}
        <label className="checkbox">
          <input type="checkbox" checked={issue} onChange={(e) => setIssue(e.target.checked)} /> Issue the order to the supplier right away
        </label>
        <MfgError error={error} title="Could not convert" />
      </div>
    </Dialog>
  );
}

/** Route element: a new instance per document, so no dialog or edit state leaks from one document to the next. */
export function PurchaseDocRoute({ docType }: { docType: DocType }) {
  const { docId = "" } = useParams();
  return <PurchaseDocPage key={`${docType}:${docId}`} docType={docType} />;
}

export function PurchaseDocPage({ docType }: { docType: DocType }) {
  const { docId = "" } = useParams();
  const isNew = docId === "new";
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { can } = useAccess();
  const loaded = useLoad((signal) => (isNew ? null : getPurchaseDoc(docType, docId, signal)), [docType, docId]);
  const [doc, setDoc] = useState<PurchaseDocRecord | null>(null);
  const [head, setHead] = useState<Header>(headerOf(null));
  const [lines, setLines] = useState<LineDraft[]>(() => [newDocLine()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ActionDef | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [receiving, setReceiving] = useState(false);
  const [converting, setConverting] = useState(false);
  const word = docType === "pr" ? "purchase request" : "purchase order";

  const reset = (d: PurchaseDocRecord) => {
    setDoc(d);
    setHead(headerOf(d));
    setLines(linesFromRecord(d.lines));
    setConflict(false);
  };
  useEffect(() => {
    if (loaded.data) reset(loaded.data);
  }, [loaded.data]);

  if (!isNew && loaded.error && isNotFound(loaded.error))
    return <NotFoundPanel what={docType === "pr" ? "Purchase request" : "Purchase order"} back={<Link className="btn" to={mfgPaths.purchaseDocs(docType)}>Back to the list</Link>} />;
  if (!isNew && loaded.error && !doc) return <MfgError error={loaded.error} onRetry={loaded.reload} />;
  if (!isNew && !doc) return <Spinner />;

  const status = doc?.status ?? "draft";
  const editPerm: Permission = docType === "pr" ? "pr_edit" : "po_edit";
  const editable = can(editPerm) && (isNew || EDITABLE[docType].includes(status));
  const body: PurchaseDocInput = {
    number: strOrNull(head.number),
    supplier_id: head.supplier?.id ?? null,
    currency: head.currency.trim(),
    order_date: head.order_date || null,
    note: head.note,
    external_ref: strOrNull(head.external_ref),
    lines: linesToInput(lines),
  };
  const dirty = isNew || (doc !== null && JSON.stringify(body) !== JSON.stringify(docBody(doc)));
  const problems = [...linesProblems(lines), ...(docType === "po" && !head.supplier ? ["Choose the supplier."] : [])];

  const save = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (isNew) {
        const created = await createPurchaseDoc(docType, body);
        navigate(mfgPaths.purchaseDoc(docType, created.id), { replace: true });
      } else if (doc) {
        reset(await updatePurchaseDoc(docType, doc.id, body, doc.row_version));
        setNotice("Saved.");
      }
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  const run = async (a: ActionDef, extra?: unknown) => {
    if (!doc) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (a.key === "delete") {
        await deletePurchaseDoc(docType, doc.id, doc.row_version);
        navigate(mfgPaths.purchaseDocs(docType));
        return;
      }
      reset(await purchaseAction(docType, doc.id, a.key as PrAction | PoAction, doc.row_version, extra ?? {}));
      setNotice(`${a.label}: done.`);
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  const click = (a: ActionDef) => {
    if (a.key === "receive") setReceiving(true);
    else if (a.key === "convert") setConverting(true);
    else if (a.key === "reject") setRejecting(true);
    else if (a.confirm) setConfirm(a);
    else void run(a);
  };

  const actions = (docType === "pr" ? PR_ACTIONS : PO_ACTIONS).filter((a) => doc && a.from.includes(status) && !(a.key === "delete" && docType === "pr" && status === "draft" && doc.source === "mrp"));
  const highlight = { line: params.get("line"), schedule: params.get("schedule") };

  return (
    <div className="col gap-lg" data-testid="doc-page" data-doc-type={docType} data-status={status}>
      <nav aria-label="Breadcrumb" className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.purchaseDocs(docType)}>{docType === "pr" ? "Purchase requests" : "Purchase orders"}</Link> <Icon name="chevron-right" size={12} />{" "}
        <span className="mono">{doc?.number ?? `New ${word}`}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h1 className="mono" data-testid="doc-title">
            {doc?.number ?? `New ${word}`}
          </h1>
          {doc ? <PurchaseStatusChip status={doc.status} testId="doc-status" /> : null}
          {doc ? <SourceBadge source={doc.source} runNo={doc.source_run_no} /> : null}
          {doc && doc.overdue_count > 0 ? <OverdueBadge days={0} /> : null}
        </div>
        {doc ? (
          <div className="mfg-actions" role="group" aria-label="Actions">
            {actions.map((a) =>
              can(a.perm) ? (
                <button
                  key={a.key}
                  type="button"
                  className={`btn${a.primary ? " primary" : ""}${a.danger ? " danger" : ""}`}
                  onClick={() => click(a)}
                  disabled={busy || (a.key !== "receive" && a.key !== "convert" && dirty && a.key !== "delete")}
                  title={dirty && a.key !== "receive" ? "Save your changes first" : undefined}
                  data-testid={a.key === "receive" ? "receive-open" : `doc-action-${a.key}`}
                >
                  <Icon name={a.icon} /> {a.label}
                </button>
              ) : a.primary ? (
                <button key={a.key} type="button" className="btn" disabled aria-disabled title={needsText(a.perm)} data-testid={a.key === "receive" ? "receive-open" : `doc-action-${a.key}`}>
                  <Icon name="lock" /> {a.label}
                </button>
              ) : null,
            )}
          </div>
        ) : null}
      </div>

      {conflict ? <ConflictBanner onReload={() => void getPurchaseDoc(docType, docId).then(reset, setError)} what={`this ${word}`} /> : null}
      {notice ? <Banner tone="ok" role="status" title={notice} /> : null}
      <MfgError error={error} title="That did not work" />
      {doc?.status === "rejected" && doc.rejected_reason ? (
        <Banner tone="danger" icon="x" title="Rejected">
          {doc.rejected_reason}
        </Banner>
      ) : null}

      <section className="card">
        <div className="card-body form-grid">
          <TextField label="Number" value={head.number} onChange={(v) => setHead({ ...head, number: v })} maxLength={32} placeholder="Next free number" disabled={!editable || !isNew} testId="doc-number" />
          <SupplierPicker
            label={docType === "po" ? "Supplier *" : "Suggested supplier"}
            value={head.supplier}
            onChange={(s) => setHead({ ...head, supplier: s, currency: head.currency || "" })}
            allowClear={docType === "pr"}
            disabled={!editable}
            testId="doc-supplier"
          />
          <TextField label="Currency" value={head.currency} onChange={(v) => setHead({ ...head, currency: v })} maxLength={8} disabled={!editable} hint="Empty = the supplier's" />
          {docType === "po" ? <TextField label="Order date" type="date" value={head.order_date} onChange={(v) => setHead({ ...head, order_date: v })} disabled={!editable} /> : null}
          <TextField label="External reference" value={head.external_ref} onChange={(v) => setHead({ ...head, external_ref: v })} maxLength={64} disabled={!editable} hint="Number in your ERP" />
          <div style={{ gridColumn: "span 2" }}>
            <TextField label="Note" value={head.note} onChange={(v) => setHead({ ...head, note: v })} maxLength={500} disabled={!editable} />
          </div>
        </div>
        {doc ? (
          <div className="card-footer row wrap small muted">
            <span>Value {fmtMoney(doc.value, doc.currency) || "-"}</span>
            <span>· Open {fmtMoney(doc.open_value, doc.currency) || "-"}</span>
            {doc.submitted_at ? <span>· Submitted {fmtTimestamp(doc.submitted_at)}</span> : null}
            {doc.approved_at ? <span>· Approved {fmtTimestamp(doc.approved_at)}</span> : null}
            <span>· Changed {fmtTimestamp(doc.updated_at)}</span>
          </div>
        ) : null}
      </section>

      <DocLinesEditor docType={docType} docId={doc?.id ?? null} lines={lines} onChange={setLines} readOnly={!editable} currency={doc?.currency || head.currency} highlight={highlight} />

      {editable ? (
        <>
          {problems.length && dirty ? (
            <ul className="mfg-problem-list">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : null}
          <div className="row mfg-sticky-actions">
            <button type="button" className="btn primary" onClick={() => void save()} disabled={busy || !dirty || problems.length > 0} data-testid="doc-save">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {isNew ? `Create ${word}` : "Save changes"}
            </button>
            {!isNew && doc ? (
              <button type="button" className="btn" disabled={!dirty || busy} onClick={() => reset(doc)}>
                Undo changes
              </button>
            ) : null}
          </div>
        </>
      ) : !isNew && doc && !can(editPerm) ? null : doc && !EDITABLE[docType].includes(status) ? (
        <p className="muted small" style={{ margin: 0 }}>
          <Icon name="lock" size={12} /> {docType === "pr" ? "Only draft or rejected requests can be changed." : "Received, closed and cancelled orders are read-only."}
        </p>
      ) : null}

      {doc?.receipts && doc.receipts.length ? (
        <section className="card" data-testid="doc-receipts">
          <div className="card-header">
            <h3>Receipts</h3>
          </div>
          <ul className="mfg-plain-list">
            {doc.receipts.map((r) => (
              <li key={r.id} className="issue">
                <Link to={mfgPaths.posting(r.id)} className="mono">
                  {r.number}
                </Link>
                <span>{fmtDate(r.txn_date)}</span>
                <span className="muted small">
                  {POSTING_LABEL[r.type]} · {r.line_count} lines · {r.actor.name}
                  {r.reversed_by_number ? ` · reversed by ${r.reversed_by_number}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {confirm ? (
        <ConfirmDialog
          title={`${confirm.label}?`}
          confirmLabel={confirm.label}
          danger={confirm.danger || confirm.key === "cancel"}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            const a = confirm;
            setConfirm(null);
            void run(a);
          }}
        >
          <p style={{ margin: 0 }}>{confirm.confirm}</p>
        </ConfirmDialog>
      ) : null}
      {rejecting ? (
        <Dialog
          title={`Reject ${doc?.number}`}
          onClose={() => setRejecting(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setRejecting(false)} data-dialog-close>
                Cancel
              </button>
              <button
                type="button"
                className="btn danger"
                disabled={!reason.trim()}
                onClick={() => {
                  setRejecting(false);
                  void run(PR_ACTIONS.find((a) => a.key === "reject")!, { reason: reason.trim() });
                }}
                data-testid="doc-reject-submit"
              >
                Reject
              </button>
            </>
          }
        >
          <div className="field">
            <label htmlFor="rej-reason">Reason (shown to the requester)</label>
            <textarea id="rej-reason" className="textarea" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="doc-reject-reason" />
          </div>
        </Dialog>
      ) : null}
      {receiving && doc ? (
        <ReceiveDialog
          doc={doc}
          scheduleId={highlight.schedule}
          onClose={() => setReceiving(false)}
          onDone={(p) => {
            setReceiving(false);
            setNotice(`Received: posting ${p.number}.`);
            void getPurchaseDoc(docType, doc.id).then(reset, setError);
          }}
        />
      ) : null}
      {converting && doc ? <ConvertDialog pr={doc} onClose={() => setConverting(false)} onDone={(poId) => {
            setConverting(false);
            navigate(mfgPaths.purchaseDoc("po", poId));
          }} /> : null}
    </div>
  );
}

/** The input a record would PUT unchanged (dirty check). */
function docBody(d: PurchaseDocRecord): PurchaseDocInput {
  return {
    number: d.number,
    supplier_id: d.supplier?.id ?? null,
    currency: d.currency,
    order_date: d.order_date,
    note: d.note,
    external_ref: d.external_ref,
    lines: linesToInput(linesFromRecord(d.lines)),
  };
}
