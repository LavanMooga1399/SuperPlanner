/**
 * `/mfg/work-orders/{new|:woId}?component=` (M2 14.2, 7): details, components with live kitting columns,
 * release (+ reserve), reserve / unreserve, Issue / Return / Report output (postings), complete / close /
 * cancel / refresh components, and the WO's ledger lines. `new` accepts `?item=&qty=&due=&demand_line=&serial_from=&serial_to=`.
 */
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Icon } from "../../../components/Icon";
import {
  createWorkOrder,
  deleteWorkOrder,
  getKitting,
  getWorkOrder,
  listTransactions,
  releaseWorkOrder,
  reserveWorkOrder,
  unreserveWorkOrder,
  updateWorkOrder,
  workOrderAction,
} from "../../api/clientM2";
import type { ItemRef } from "../../api/types";
import type { PostingWarning, WorkOrderInput, WorkOrderRecord } from "../../api/typesM2";
import type { KitShortage } from "../../api/typesM4";
import { ApiError } from "../../../api/client";
import { ConflictBanner, MfgError, NotFoundPanel, Spinner } from "../../components/Feedback";
import { numOrNull, strOrNull, TextField } from "../../components/Field";
import { ItemPicker } from "../../components/ItemPicker";
import { KittingTable } from "../../components/KittingTable";
import { WoOperations } from "../../components/WoOperations";
import { SourceBadge, WoStatusChip } from "../../components/StatusM2";
import { fmtDate } from "../../lib/format";
import { fmtNum, POSTING_LABEL, serialText } from "../../lib/formatM2";
import { isCountUom, loadItemInfo } from "../../lib/itemCache";
import { mfgPaths } from "../../lib/paths";
import { useAccess } from "../../lib/permissions";
import { isConflict, isNotFound, useLoad } from "../../lib/useMfg";
import { ComponentsEditor, IssueDialog, OutputDialog } from "./WoDialogs";

interface Form {
  number: string;
  item: ItemRef | null;
  qty: string;
  due_date: string;
  start_date: string;
  priority: string;
  serial_from: string;
  serial_to: string;
  demand_line_id: string;
  note: string;
  external_ref: string;
}

function formOf(w: WorkOrderRecord): Form {
  return {
    number: w.number,
    item: w.item,
    qty: String(w.qty),
    due_date: w.due_date,
    start_date: w.start_date,
    priority: String(w.priority),
    serial_from: w.serial_from === null ? "" : String(w.serial_from),
    serial_to: w.serial_to === null ? "" : String(w.serial_to),
    demand_line_id: w.demand_line_id ?? "",
    note: w.note,
    external_ref: w.external_ref ?? "",
  };
}

function inputOf(f: Form, keepStart: boolean): WorkOrderInput {
  return {
    number: strOrNull(f.number),
    item_id: f.item?.id ?? "",
    qty: numOrNull(f.qty) ?? 0,
    due_date: f.due_date,
    start_date: keepStart ? f.start_date || null : null,
    priority: numOrNull(f.priority) ?? 5,
    serial_from: numOrNull(f.serial_from),
    serial_to: numOrNull(f.serial_to),
    demand_line_id: f.demand_line_id || null,
    note: f.note,
    external_ref: strOrNull(f.external_ref),
    components: null,
  };
}

type Dlg = "issue" | "return" | "output" | "components" | "complete" | "close" | "cancel" | "delete" | "refresh" | "release" | null;

export function WorkOrderPage() {
  const { woId = "" } = useParams();
  const isNew = woId === "new";
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { can } = useAccess();
  const createdWarnings = ((useLocation().state as { warnings?: PostingWarning[] } | null)?.warnings ?? []);
  const loaded = useLoad((signal) => (isNew ? null : getWorkOrder(woId, signal)), [woId]);
  const [wo, setWo] = useState<WorkOrderRecord | null>(null);
  const [f, setF] = useState<Form>({
    number: "",
    item: null,
    qty: params.get("qty") ?? "",
    due_date: params.get("due") ?? "",
    start_date: "",
    priority: "5",
    serial_from: params.get("serial_from") ?? "",
    serial_to: params.get("serial_to") ?? "",
    demand_line_id: params.get("demand_line") ?? "",
    note: "",
    external_ref: "",
  });
  const [startTouched, setStartTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [dlg, setDlg] = useState<Dlg>(null);
  const [reserveOnRelease, setReserveOnRelease] = useState(true);
  const [kitBlock, setKitBlock] = useState<KitShortage[] | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const kitting = useLoad((signal) => (wo && ["planned", "released", "in_progress"].includes(wo.status) ? getKitting(wo.id, signal) : null), [wo?.id, wo?.row_version]);
  const txns = useLoad((signal) => (wo ? listTransactions({ ref_type: "wo", ref_id: wo.id, limit: 50, offset: 0 }, signal) : null), [wo?.id, wo?.row_version]);

  const reset = (w: WorkOrderRecord) => {
    setWo(w);
    setF(formOf(w));
    setStartTouched(false);
    setConflict(false);
  };
  useEffect(() => {
    if (loaded.data) reset(loaded.data);
  }, [loaded.data]);
  const itemParam = params.get("item");
  useEffect(() => {
    if (!isNew || !itemParam) return;
    loadItemInfo(itemParam).then(
      (it) => setF((x) => (x.item ? x : { ...x, item: { id: it.id, part_number: it.part_number, revision: it.revision, description: it.description, uom: it.uom, make_buy: it.make_buy, active: it.active } })),
      () => undefined,
    );
  }, [isNew, itemParam]);

  if (!isNew && loaded.error && isNotFound(loaded.error)) return <NotFoundPanel what="Work order" back={<Link className="btn" to={mfgPaths.workOrders()}>Back to work orders</Link>} />;
  if (!isNew && loaded.error && !wo) return <MfgError error={loaded.error} onRetry={loaded.reload} />;
  if (!isNew && !wo) return <Spinner />;

  const status = wo?.status ?? "planned";
  const canEdit = can("wo_edit");
  const active = ["planned", "released", "in_progress"].includes(status);
  const fullEdit = canEdit && (isNew || status === "planned");
  const partEdit = canEdit && active;
  const body = inputOf(f, startTouched || !isNew);
  const original = wo ? inputOf(formOf(wo), true) : null;
  const dirty = isNew || JSON.stringify(body) !== JSON.stringify(original);
  const q = numOrNull(f.qty);
  const sf = numOrNull(f.serial_from);
  const st = numOrNull(f.serial_to);
  const problem = !f.item
    ? "Choose the item to make."
    : q === null || q <= 0
      ? "Enter the quantity."
      : isCountUom(f.item.uom) && !Number.isInteger(q)
        ? `${f.item.uom} quantities are whole numbers.`
        : !f.due_date
          ? "Enter the due date."
          : f.start_date && f.start_date > f.due_date
            ? "The start date must be on or before the due date."
            : (sf === null) !== (st === null)
              ? "Give both serial numbers or neither."
              : sf !== null && st !== null && st - sf + 1 !== q
                ? `Serials ${sf}-${st} are ${st - sf + 1} units; the quantity is ${q}.`
                : wo && q < wo.qty_completed
                  ? `Cannot be less than the ${fmtNum(wo.qty_completed)} already completed.`
                  : null;

  const guard = async (fn: () => Promise<WorkOrderRecord | void>, msg?: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const r = await fn();
      if (r) reset(r);
      if (msg) setNotice(msg);
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    guard(async () => {
      if (isNew) {
        const created = await createWorkOrder(body);
        navigate(mfgPaths.workOrder(created.id), { replace: true, state: { warnings: created.warnings } });
        return;
      }
      return updateWorkOrder(wo!.id, body, wo!.row_version);
    }, isNew ? undefined : "Saved.");

  const afterPost = (msg: string) => {
    setDlg(null);
    setNotice(msg);
    void getWorkOrder(woId).then(reset, setError);
  };

  const shortages = kitting.data?.totals.short_components ?? wo?.shortage_count ?? 0;
  const reservedTotal = wo?.components.reduce((s, c) => s + c.reserved_qty, 0) ?? 0;

  return (
    <div className="col gap-lg" data-testid="wo-page" data-status={status}>
      <nav aria-label="Breadcrumb" className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.workOrders()}>Work orders</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{wo?.number ?? "New work order"}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h1 className="mono" data-testid="wo-title">
            {wo?.number ?? "New work order"}
          </h1>
          {wo ? <WoStatusChip status={wo.status} testId="wo-status" /> : null}
          {wo ? <SourceBadge source={wo.source} runNo={wo.source_run_no} /> : null}
          {wo && active ? (
            shortages > 0 ? (
              <span className="badge danger" data-testid="wo-kit-status" data-kit="short">
                <Icon name="alert" /> {shortages} short
              </span>
            ) : kitting.data ? (
              <span className="badge ok" data-testid="wo-kit-status" data-kit="complete">
                <Icon name="check" /> Kit complete
              </span>
            ) : null
          ) : null}
        </div>
        {wo && canEdit ? (
          <div className="mfg-actions" role="group" aria-label="Actions">
            {status === "planned" ? (
              <button type="button" className="btn primary" onClick={() => setDlg("release")} disabled={busy || dirty} data-testid="wo-action-release">
                <Icon name="play" /> Release
              </button>
            ) : null}
            {active ? (
              <>
                <button type="button" className="btn" onClick={() => void guard(() => reserveWorkOrder(wo.id, wo.row_version), "Free stock reserved for the open components.")} disabled={busy || dirty} data-testid="wo-reserve">
                  <Icon name="lock" /> Reserve stock
                </button>
                {reservedTotal > 0 ? (
                  <button type="button" className="btn ghost" onClick={() => void guard(() => unreserveWorkOrder(wo.id, wo.row_version), "Reservations released.")} disabled={busy || dirty} data-testid="wo-unreserve">
                    <Icon name="unlock" /> Release reservations
                  </button>
                ) : null}
              </>
            ) : null}
            {status === "released" || status === "in_progress" ? (
              <button type="button" className="btn" onClick={() => setDlg("complete")} disabled={busy} data-testid="wo-action-complete">
                <Icon name="check" /> Complete
              </button>
            ) : null}
            {status === "completed" ? (
              <button type="button" className="btn" onClick={() => setDlg("close")} disabled={busy} data-testid="wo-action-close">
                <Icon name="lock" /> Close
              </button>
            ) : null}
            {status === "planned" || status === "released" ? (
              <button type="button" className="btn ghost" onClick={() => setDlg("cancel")} disabled={busy} data-testid="wo-action-cancel">
                <Icon name="ban" /> Cancel
              </button>
            ) : null}
            {status === "planned" || status === "cancelled" ? (
              <button type="button" className="btn ghost danger" onClick={() => setDlg("delete")} disabled={busy}>
                <Icon name="trash" />
                <span className="sr-only">Delete</span>
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      {wo && (status === "released" || status === "in_progress") && can("inventory") ? (
        <div className="row wrap" role="group" aria-label="Stock postings">
          <button type="button" className="btn primary" onClick={() => setDlg("issue")} data-testid="wo-issue-open">
            <Icon name="arrow-right" /> Issue components
          </button>
          <button type="button" className="btn" onClick={() => setDlg("return")} disabled={!wo.components.some((c) => c.issued_qty > 0)} data-testid="wo-return-open">
            <Icon name="refresh" /> Return components
          </button>
          <button type="button" className="btn" onClick={() => setDlg("output")} data-testid="wo-receipt-open">
            <Icon name="download" /> Report output
          </button>
        </div>
      ) : null}

      {conflict ? <ConflictBanner onReload={() => void getWorkOrder(woId).then(reset, setError)} what="this work order" /> : null}
      {notice ? <Banner tone="ok" role="status" title={notice} /> : null}
      {wo?.reserved?.some((r) => r.shortage > 0) ? (
        <Banner tone="warn" title="Not everything could be reserved">
          {wo.reserved.filter((r) => r.shortage > 0).length} components lack free stock; see the Kit column.
        </Banner>
      ) : null}
      {[...(wo?.warnings ?? []), ...createdWarnings.filter((c) => !wo?.warnings?.some((w) => w.code === c.code))].map((w) => (
        <Banner key={w.code} tone="warn" title={w.code === "WO_NO_EFFECTIVE_BOM" ? "No effective BOM: no components were generated" : w.code}>
          {w.message}
        </Banner>
      ))}
      <MfgError error={error} title="That did not work" />

      <section className="card">
        <div className="card-body form-grid">
          {isNew ? (
            <ItemPicker label="Item to make" value={f.item} makeBuy="make" onChange={(it) => setF({ ...f, item: it })} testId="wo-item" />
          ) : (
            <div className="field">
              <span className="field-label">Item</span>
              <span>
                <Link to={mfgPaths.item(f.item?.id ?? "")} className="mono">
                  {f.item?.part_number}
                </Link>{" "}
                <span className="muted small">{f.item?.description}</span>
              </span>
            </div>
          )}
          <TextField label={`Good quantity${f.item ? ` (${f.item.uom})` : ""}`} type="number" value={f.qty} onChange={(v) => setF({ ...f, qty: v })} disabled={!partEdit && !isNew} testId="wo-qty" />
          <TextField label="Due date" type="date" value={f.due_date} onChange={(v) => setF({ ...f, due_date: v })} disabled={!partEdit && !isNew} testId="wo-due" />
          <TextField
            label="Start date"
            type="date"
            value={f.start_date}
            onChange={(v) => {
              setStartTouched(true);
              setF({ ...f, start_date: v });
            }}
            disabled={!partEdit && !isNew}
            hint={isNew && !startTouched ? "Empty = due date minus the manufacturing lead time" : undefined}
            testId="wo-start"
          />
          <TextField label="Priority (1 = most important)" type="number" value={f.priority} onChange={(v) => setF({ ...f, priority: v })} disabled={!partEdit && !isNew} />
          <TextField label="Number" value={f.number} onChange={(v) => setF({ ...f, number: v })} maxLength={32} placeholder="Next free number" disabled={!isNew} />
          <div className="field">
            <span className="field-label">Unit serials</span>
            <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
              <input className="input num" type="number" aria-label="Serial from" placeholder="from" value={f.serial_from} disabled={!fullEdit} onChange={(e) => setF({ ...f, serial_from: e.target.value })} />
              <input className="input num" type="number" aria-label="Serial to" placeholder="to" value={f.serial_to} disabled={!fullEdit} onChange={(e) => setF({ ...f, serial_to: e.target.value })} />
            </div>
            <span className="hint">Serialized items: selects the BOM valid for these units.</span>
          </div>
          <div style={{ gridColumn: "span 2" }}>
            <TextField label="Note" value={f.note} onChange={(v) => setF({ ...f, note: v })} maxLength={500} disabled={!partEdit && !isNew} />
          </div>
        </div>
        {wo ? (
          <div className="card-footer row wrap small muted">
            <span>
              Done {fmtNum(wo.qty_completed)} · scrapped {fmtNum(wo.qty_scrapped)} · open {fmtNum(wo.open_qty)} {wo.item.uom}
            </span>
            {wo.bom ? <span>· BOM rev. {wo.bom.revision} v{wo.bom.version}</span> : <span>· no BOM</span>}
            {wo.routing ? <span>· routing {wo.routing.code} v{wo.routing.version}</span> : null}
            {wo.serial_from !== null ? <span>· units {serialText(wo.serial_from, wo.serial_to)}</span> : null}
            {wo.demand_line ? (
              <span>
                · for{" "}
                <Link to={mfgPaths.demandOrder(wo.demand_line.order_id, wo.demand_line.id)}>
                  {wo.demand_line.order_number}/{wo.demand_line.line_no}
                </Link>
              </span>
            ) : null}
          </div>
        ) : null}
      </section>

      {fullEdit || partEdit ? (
        <div className="row mfg-sticky-actions">
          <button type="button" className="btn primary" onClick={() => void save()} disabled={busy || !dirty || Boolean(problem)} data-testid="wo-save">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {isNew ? "Create work order" : "Save changes"}
          </button>
          {problem && dirty ? <span className="field-error">{problem}</span> : null}
          {isNew ? <span className="faint small">Components are copied from the BOM valid at the start date.</span> : null}
        </div>
      ) : null}

      {wo ? (
        <section className="col" style={{ gap: 8 }}>
          <div className="row between">
            <h3 style={{ margin: 0 }}>Components ({wo.components.length})</h3>
            {partEdit ? (
              <div className="mfg-actions">
                {status === "planned" ? (
                  <button type="button" className="btn sm" onClick={() => setDlg("refresh")} disabled={busy}>
                    <Icon name="refresh" /> Refresh from BOM
                  </button>
                ) : null}
                <button type="button" className="btn sm" onClick={() => setDlg("components")} disabled={busy || dirty} data-testid="wo-components-edit">
                  Edit components
                </button>
              </div>
            ) : null}
          </div>
          <MfgError error={kitting.error} onRetry={kitting.reload} title="Kitting could not be checked" />
          <KittingTable components={wo.components} kitting={kitting.data?.rows ?? null} highlight={params.get("component")} showKitting={active} />
        </section>
      ) : null}

      {wo && wo.routing ? <WoOperations woId={wo.id} woVersion={wo.row_version} onChanged={() => void getWorkOrder(woId).then(reset, setError)} /> : null}

      {wo && txns.data && txns.data.items.length ? (
        <section className="card" data-testid="wo-transactions">
          <div className="card-header">
            <h3>Stock movements</h3>
            <Link to={mfgPaths.transactions()} className="small">
              Ledger
            </Link>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Posting</th>
                  <th>Type</th>
                  <th>Part</th>
                  <th>Location</th>
                  <th className="right">Change</th>
                </tr>
              </thead>
              <tbody>
                {txns.data.items.map((t) => (
                  <tr key={t.id} data-testid="txn-row">
                    <td>{fmtDate(t.txn_date)}</td>
                    <td>
                      <Link to={mfgPaths.posting(t.posting_id)} className="mono">
                        {t.posting_number}
                      </Link>
                    </td>
                    <td>{POSTING_LABEL[t.txn_type]}</td>
                    <td className="mono">{t.item.part_number}</td>
                    <td className="mono">{t.location.code}</td>
                    <td className={`right ${t.qty < 0 ? "mfg-neg" : "mfg-pos"}`}>{fmtNum(t.qty)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {dlg === "release" && wo ? (
        <ConfirmDialog
          title={`Release ${wo.number}?`}
          confirmLabel="Release"
          onCancel={() => setDlg(null)}
          onConfirm={() => {
            setDlg(null);
            void guard(async () => {
              try {
                return await releaseWorkOrder(wo.id, reserveOnRelease, wo.row_version);
              } catch (e) {
                if (e instanceof ApiError && e.code === "WO_KIT_INCOMPLETE") {
                  const d = e.details as { shortages?: KitShortage[]; items?: KitShortage[] };
                  setKitBlock(d.shortages ?? d.items ?? []);
                  return;
                }
                throw e;
              }
            }, undefined);
          }}
        >
          <p style={{ margin: 0 }}>The work order can then be issued and reported. Its component quantities stay as they are.</p>
          <label className="checkbox" style={{ marginTop: 8 }}>
            <input type="checkbox" checked={reserveOnRelease} onChange={(e) => setReserveOnRelease(e.target.checked)} data-testid="wo-release-reserve" /> Reserve free stock for the components now
          </label>
        </ConfirmDialog>
      ) : null}
      {kitBlock && wo ? (
        <ConfirmDialog
          title="Components are short for the first operation"
          confirmLabel="Release anyway"
          busy={busy}
          confirmDisabled={!overrideReason.trim()}
          onCancel={() => {
            setKitBlock(null);
            setOverrideReason("");
          }}
          onConfirm={() => {
            if (!overrideReason.trim()) return;
            const reason = overrideReason.trim();
            setKitBlock(null);
            setOverrideReason("");
            void guard(() => releaseWorkOrder(wo.id, reserveOnRelease, wo.row_version, reason), "Released to the shop floor despite the shortage.");
          }}
        >
          <div data-testid="wo-kit-incomplete">
            {kitBlock.length ? (
              <table className="table" style={{ marginBottom: 8 }}>
                <thead>
                  <tr>
                    <th>Part</th>
                    <th className="right">Needed</th>
                    <th className="right">Available</th>
                    <th className="right">Short</th>
                  </tr>
                </thead>
                <tbody>
                  {kitBlock.map((k) => (
                    <tr key={k.item_id}>
                      <td className="mono">{k.part_number}</td>
                      <td className="right">{fmtNum(k.required)}</td>
                      <td className="right">{fmtNum(k.available)}</td>
                      <td className="right">{fmtNum(k.short)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            <p style={{ marginTop: 0 }}>The floor can still start; the shortage is recorded with your reason.</p>
            <div className="field">
              <label htmlFor="wo-override">Reason (required)</label>
              <input id="wo-override" className="input" value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)} maxLength={200} data-testid="wo-release-override" />
            </div>
          </div>
        </ConfirmDialog>
      ) : null}
      {dlg && ["complete", "close", "cancel", "delete", "refresh"].includes(dlg) && wo ? (
        <ConfirmDialog
          title={dlg === "complete" ? "Complete now (short close)?" : dlg === "close" ? "Close the work order?" : dlg === "cancel" ? "Cancel the work order?" : dlg === "refresh" ? "Regenerate components?" : "Delete the work order?"}
          confirmLabel={dlg === "complete" ? "Complete" : dlg === "close" ? "Close" : dlg === "cancel" ? "Cancel work order" : dlg === "refresh" ? "Regenerate" : "Delete"}
          cancelLabel="Keep"
          danger={dlg === "cancel" || dlg === "delete"}
          onCancel={() => setDlg(null)}
          onConfirm={() => {
            const d = dlg;
            setDlg(null);
            if (d === "delete") void guard(async () => { await deleteWorkOrder(wo.id, wo.row_version); navigate(mfgPaths.workOrders()); });
            else void guard(() => workOrderAction(wo.id, d === "refresh" ? "refresh-components" : (d as "complete" | "close" | "cancel"), wo.row_version));
          }}
        >
          <p style={{ margin: 0 }}>
            {dlg === "complete"
              ? `The ${fmtNum(wo.open_qty)} ${wo.item.uom} still open will not be made and stop counting as supply. Reservations are released.`
              : dlg === "close"
                ? "Closing is final."
                : dlg === "cancel"
                  ? "Only possible without issues or receipts (return material first)."
                  : dlg === "refresh"
                    ? "The component list is replaced by the BOM valid at the start date."
                    : "Only planned or cancelled orders without stock movements can be deleted."}
          </p>
        </ConfirmDialog>
      ) : null}
      {(dlg === "issue" || dlg === "return") && wo ? <IssueDialog wo={wo} mode={dlg} kitting={kitting.data?.rows ?? null} onClose={() => setDlg(null)} onDone={(p) => afterPost(`Posted ${p.number}.`)} /> : null}
      {dlg === "output" && wo ? <OutputDialog wo={wo} onClose={() => setDlg(null)} onDone={(p) => afterPost(`Output posted: ${p.number}.`)} /> : null}
      {dlg === "components" && wo ? (
        <ComponentsEditor
          wo={wo}
          input={inputOf(formOf(wo), true)}
          onClose={() => setDlg(null)}
          onSaved={(w) => {
            setDlg(null);
            reset(w);
            setNotice("Components saved.");
          }}
        />
      ) : null}
    </div>
  );
}
