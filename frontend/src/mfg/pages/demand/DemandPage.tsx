/**
 * `/mfg/demand/{new|:orderId}?line=` (M2 14.2, 3.6, 6): demand order with lines (unit serial ranges, line
 * priority), the projection of the latest live MRP run per line, open / close / cancel, and Ship (posting).
 */
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Dialog } from "../../../components/Dialog";
import { Icon } from "../../../components/Icon";
import { createDemandOrder, createPosting, deleteDemandOrder, demandAction, getDemandOrder, newIdempotencyKey, updateDemandOrder } from "../../api/clientM2";
import type { ItemRef } from "../../api/types";
import { DEMAND_TYPES, type DemandLineInput, type DemandLineRecord, type DemandOrderInput, type DemandOrderRecord, type DemandType } from "../../api/typesM2";
import { ConflictBanner, MfgError, NotFoundPanel, Spinner } from "../../components/Feedback";
import { numOrNull, SelectField, strOrNull, TextField } from "../../components/Field";
import { ItemPicker } from "../../components/ItemPicker";
import { LocationSelect } from "../../components/PickersM2";
import { DemandStatusChip, ProjectionChip } from "../../components/StatusM2";
import { fmtDate } from "../../lib/format";
import { DEMAND_TYPE_LABEL, fmtNum, serialText } from "../../lib/formatM2";
import { isCountUom, useItemInfo } from "../../lib/itemCache";
import { mfgPaths } from "../../lib/paths";
import { useAccess } from "../../lib/permissions";
import { isConflict, isNotFound, useLoad } from "../../lib/useMfg";

interface LineDraft {
  key: number;
  id: string | null;
  line_no: number | null;
  item: ItemRef | null;
  qty: string;
  due_date: string;
  serial_from: string;
  serial_to: string;
  priority: string;
  note: string;
  rec: DemandLineRecord | null;
}

let k = 0;
const blank = (): LineDraft => ({ key: ++k, id: null, line_no: null, item: null, qty: "", due_date: "", serial_from: "", serial_to: "", priority: "", note: "", rec: null });
const fromRec = (l: DemandLineRecord): LineDraft => ({
  key: ++k,
  id: l.id,
  line_no: l.line_no,
  item: l.item,
  qty: String(l.qty),
  due_date: l.due_date,
  serial_from: l.serial_from === null ? "" : String(l.serial_from),
  serial_to: l.serial_to === null ? "" : String(l.serial_to),
  priority: l.priority === null ? "" : String(l.priority),
  note: l.note,
  rec: l,
});

function toInput(l: LineDraft): DemandLineInput {
  return {
    id: l.id,
    line_no: l.line_no,
    item_id: l.item!.id,
    qty: numOrNull(l.qty) ?? 0,
    due_date: l.due_date,
    serial_from: numOrNull(l.serial_from),
    serial_to: numOrNull(l.serial_to),
    priority: numOrNull(l.priority),
    note: l.note,
  };
}

function lineProblem(l: LineDraft): string | null {
  if (!l.item) return null;
  const q = numOrNull(l.qty);
  if (q === null || q <= 0) return "quantity must be more than 0";
  if (isCountUom(l.item.uom) && !Number.isInteger(q)) return `${l.item.uom} quantities are whole numbers`;
  if (!l.due_date) return "enter the due date";
  const f = numOrNull(l.serial_from);
  const t = numOrNull(l.serial_to);
  if ((f === null) !== (t === null)) return "give both serial numbers or neither";
  if (f !== null && t !== null && t - f + 1 !== q) return `serials ${f}-${t} are ${t - f + 1} units, the quantity is ${q}`;
  const p = numOrNull(l.priority);
  if (p !== null && !(Number.isInteger(p) && p >= 1 && p <= 9)) return "priority is 1 (most important) to 9";
  if (l.rec && q < l.rec.shipped_qty) return `cannot be less than the ${fmtNum(l.rec.shipped_qty)} already shipped`;
  return null;
}

function SerialHint({ item }: { item: ItemRef | null }) {
  const info = useItemInfo(item?.id);
  if (!info || info.serialized) return null;
  return <div className="faint small">Not serialized</div>;
}

function ShipDialog({ order, onClose, onDone }: { order: DemandOrderRecord; onClose(): void; onDone(number: string): void }) {
  const open = order.lines.filter((l) => l.open_qty > 0);
  const [rows, setRows] = useState(() => open.map((l) => ({ line: l, qty: "", location_id: "", lot_code: "" })));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const keyRef = useRef<{ body: string; key: string } | null>(null);
  const chosen = rows.filter((r) => (numOrNull(r.qty) ?? 0) > 0);
  const bad = chosen.some((r) => !r.location_id || (numOrNull(r.qty) ?? 0) > r.line.open_qty);
  const submit = async () => {
    const body = {
      type: "ship" as const,
      note: `Shipment ${order.number}`,
      lines: chosen.map((r) => ({ demand_line_id: r.line.id, location_id: r.location_id, lot_code: r.lot_code.trim() || null, qty: numOrNull(r.qty) ?? 0 })),
    };
    const text = JSON.stringify(body);
    if (!keyRef.current || keyRef.current.body !== text) keyRef.current = { body: text, key: newIdempotencyKey("ship") };
    setBusy(true);
    setError(null);
    try {
      const { record } = await createPosting(body, keyRef.current.key);
      onDone(record.number);
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={`Ship ${order.number}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={busy || !chosen.length || bad} data-testid="ship-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />} Post shipment
          </button>
        </>
      }
    >
      <div className="col">
        <table className="table mfg-grid-table">
          <thead>
            <tr>
              <th>Line</th>
              <th className="right">Open</th>
              <th>Ship now</th>
              <th>From location</th>
              <th>Lot</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.line.id} data-testid="ship-row">
                <td>
                  <span className="mono">{r.line.line_no}</span> {r.line.item.part_number}
                  {r.line.serial_from !== null ? <span className="faint small"> · units {serialText(r.line.serial_from, r.line.serial_to)}</span> : null}
                </td>
                <td className="right">
                  {fmtNum(r.line.open_qty)} {r.line.item.uom}
                </td>
                <td style={{ width: 100 }}>
                  <input className="input sm num" type="number" min={0} max={r.line.open_qty} aria-label={`Ship quantity line ${r.line.line_no}`} value={r.qty} onChange={(e) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} data-testid="ship-qty" />
                </td>
                <td style={{ minWidth: 180 }}>
                  <LocationSelect label={`Location line ${r.line.line_no}`} hideLabel value={r.location_id} kinds={["stores", "line_side"]} onChange={(v) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, location_id: v } : x)))} testId="ship-location" />
                </td>
                <td>
                  <input className="input sm" aria-label={`Lot line ${r.line.line_no}`} value={r.lot_code} placeholder="Earliest expiry" onChange={(e) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, lot_code: e.target.value } : x)))} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {bad ? <p className="field-error">Each shipped line needs a location and at most its open quantity.</p> : null}
        <MfgError error={error} title="Nothing was shipped" />
      </div>
    </Dialog>
  );
}

export function DemandPage() {
  const { orderId = "" } = useParams();
  const isNew = orderId === "new";
  const [params] = useSearchParams();
  const highlight = params.get("line");
  const navigate = useNavigate();
  const { can } = useAccess();
  const loaded = useLoad((signal) => (isNew ? null : getDemandOrder(orderId, signal)), [orderId]);
  const [order, setOrder] = useState<DemandOrderRecord | null>(null);
  const [head, setHead] = useState({ number: "", demand_type: "customer" as DemandType, customer: "", program: "", priority: "5", note: "", external_ref: "" });
  const [lines, setLines] = useState<LineDraft[]>(() => [blank()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"close" | "cancel" | "delete" | null>(null);
  const [shipping, setShipping] = useState(false);

  const reset = (o: DemandOrderRecord) => {
    setOrder(o);
    setHead({ number: o.number, demand_type: o.demand_type, customer: o.customer, program: o.program ?? "", priority: String(o.priority), note: o.note, external_ref: o.external_ref ?? "" });
    setLines(o.lines.map(fromRec));
    setConflict(false);
  };
  useEffect(() => {
    if (loaded.data) reset(loaded.data);
  }, [loaded.data]);
  useEffect(() => {
    if (highlight && order) document.querySelector(".mfg-highlight")?.scrollIntoView({ block: "center" });
  }, [highlight, order]);

  if (!isNew && loaded.error && isNotFound(loaded.error)) return <NotFoundPanel what="Demand order" back={<Link className="btn" to={mfgPaths.demand()}>Back to demand</Link>} />;
  if (!isNew && loaded.error && !order) return <MfgError error={loaded.error} onRetry={loaded.reload} />;
  if (!isNew && !order) return <Spinner />;

  const status = order?.status ?? "draft";
  const editable = can("demand_edit") && (isNew || status === "draft" || status === "open");
  const body: DemandOrderInput = {
    number: strOrNull(head.number),
    demand_type: head.demand_type,
    customer: head.customer,
    program: strOrNull(head.program),
    priority: numOrNull(head.priority) ?? 5,
    note: head.note,
    external_ref: strOrNull(head.external_ref),
    lines: lines.filter((l) => l.item).map(toInput),
  };
  const original: DemandOrderInput | null = order
    ? {
        number: order.number,
        demand_type: order.demand_type,
        customer: order.customer,
        program: order.program,
        priority: order.priority,
        note: order.note,
        external_ref: order.external_ref,
        lines: order.lines.map(fromRec).map(toInput),
      }
    : null;
  const dirty = isNew || JSON.stringify(body) !== JSON.stringify(original);
  const problems = lines.map((l, i) => (lineProblem(l) ? `Line ${l.line_no ?? (i + 1) * 10}: ${lineProblem(l)}.` : null)).filter((x): x is string => Boolean(x));
  if (!body.lines.length) problems.push("Add at least one line.");

  const save = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (isNew) {
        const o = await createDemandOrder(body);
        navigate(mfgPaths.demandOrder(o.id), { replace: true });
      } else if (order) {
        reset(await updateDemandOrder(order.id, body, order.row_version));
        setNotice("Saved.");
      }
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };
  const act = async (a: "open" | "close" | "cancel" | "delete") => {
    if (!order) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (a === "delete") {
        await deleteDemandOrder(order.id, order.row_version);
        navigate(mfgPaths.demand());
        return;
      }
      reset(await demandAction(order.id, a, order.row_version));
      setNotice(a === "open" ? "The order is open: the next MRP run plans it." : a === "close" ? "Closed." : "Cancelled.");
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };
  const patch = (i: number, p: Partial<LineDraft>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...p } : l)));
  const hasShipments = order?.lines.some((l) => l.shipped_qty > 0) ?? false;

  return (
    <div className="col gap-lg" data-testid="demand-page" data-status={status}>
      <nav aria-label="Breadcrumb" className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.demand()}>Demand</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{order?.number ?? "New demand order"}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h1 className="mono" data-testid="demand-title">
            {order?.number ?? "New demand order"}
          </h1>
          {order ? <DemandStatusChip status={order.status} testId="demand-status-chip" /> : null}
        </div>
        {order && can("demand_edit") ? (
          <div className="mfg-actions">
            {status === "draft" || status === "closed" ? (
              <button type="button" className="btn primary" onClick={() => void act("open")} disabled={busy || dirty} title={dirty ? "Save your changes first" : undefined} data-testid="demand-action-open">
                <Icon name="play" /> {status === "draft" ? "Open for planning" : "Re-open"}
              </button>
            ) : null}
            {status === "open" ? (
              <button type="button" className="btn" onClick={() => setConfirm("close")} disabled={busy || dirty} data-testid="demand-action-close">
                <Icon name="lock" /> Close
              </button>
            ) : null}
            {(status === "draft" || status === "open") && !hasShipments ? (
              <button type="button" className="btn" onClick={() => setConfirm("cancel")} disabled={busy} data-testid="demand-action-cancel">
                <Icon name="ban" /> Cancel
              </button>
            ) : null}
            {(status === "draft" || status === "cancelled") && !hasShipments ? (
              <button type="button" className="btn danger" onClick={() => setConfirm("delete")} disabled={busy}>
                <Icon name="trash" /> Delete
              </button>
            ) : null}
          </div>
        ) : null}
        {order && status === "open" && can("inventory") ? (
          <button type="button" className="btn" onClick={() => setShipping(true)} disabled={!order.lines.some((l) => l.open_qty > 0)} data-testid="demand-ship">
            <Icon name="arrow-right" /> Ship
          </button>
        ) : null}
      </div>

      {conflict ? <ConflictBanner onReload={() => void getDemandOrder(orderId).then(reset, setError)} what="this demand order" /> : null}
      {notice ? <Banner tone="ok" role="status" title={notice} /> : null}
      {status === "draft" && order ? (
        <Banner tone="warn" title="Draft: not planned yet">
          Open the order when it is confirmed; MRP plans only open orders.
        </Banner>
      ) : null}
      <MfgError error={error} title="That did not work" />

      <section className="card">
        <div className="card-body form-grid">
          <TextField label="Number" value={head.number} onChange={(v) => setHead({ ...head, number: v })} maxLength={32} placeholder="Next free number" disabled={!editable || !isNew} testId="demand-number" />
          <SelectField label="Type" value={head.demand_type} onChange={(v) => setHead({ ...head, demand_type: v })} options={DEMAND_TYPES.map((t) => ({ value: t, label: DEMAND_TYPE_LABEL[t] }))} disabled={!editable} testId="demand-type" />
          <TextField label="Customer" value={head.customer} onChange={(v) => setHead({ ...head, customer: v })} disabled={!editable} testId="demand-customer" />
          <TextField label="Programme" value={head.program} onChange={(v) => setHead({ ...head, program: v.toUpperCase() })} maxLength={32} disabled={!editable} hint="e.g. KVP-27; MRP can protect programmes" />
          <TextField label="Priority (1 = most important)" type="number" value={head.priority} onChange={(v) => setHead({ ...head, priority: v })} disabled={!editable} hint="1 to 9; lines can override" testId="demand-priority" />
          <TextField label="External reference" value={head.external_ref} onChange={(v) => setHead({ ...head, external_ref: v })} maxLength={64} disabled={!editable} />
          <div style={{ gridColumn: "span 2" }}>
            <TextField label="Note" value={head.note} onChange={(v) => setHead({ ...head, note: v })} maxLength={500} disabled={!editable} />
          </div>
        </div>
      </section>

      <div className="table-wrap card">
        <table className="table mfg-grid-table" data-testid="demand-lines">
          <thead>
            <tr>
              <th>Line</th>
              <th>Item</th>
              <th className="right">Quantity</th>
              <th>Due date</th>
              <th>Unit serials</th>
              <th>Priority</th>
              <th className="right">Shipped</th>
              <th>Latest plan</th>
              <th>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => {
              const n = l.line_no ?? (i + 1) * 10;
              const locked = !editable || (l.rec?.shipped_qty ?? 0) > 0;
              const pr = l.rec?.projection ?? null;
              return (
                <tr key={l.key} data-testid="demand-line" data-line-no={n} data-late-days={pr ? pr.late_days : ""} className={l.id && l.id === highlight ? "mfg-highlight" : undefined}>
                  <td className="mono">{n}</td>
                  <td style={{ minWidth: 220 }}>
                    {locked && l.item ? (
                      <Link to={mfgPaths.item(l.item.id)} className="mono">
                        {l.item.part_number}
                      </Link>
                    ) : (
                      <ItemPicker label={`Line ${n} item`} hideLabel value={l.item} onChange={(it) => patch(i, { item: it })} testId="demand-line-item" />
                    )}
                    {l.item ? <div className="faint small mfg-ellipsis">{l.item.description}</div> : null}
                  </td>
                  <td style={{ width: 96 }}>
                    {!editable ? fmtNum(numOrNull(l.qty)) : <input className="input sm num" type="number" aria-label={`Line ${n} quantity`} value={l.qty} onChange={(e) => patch(i, { qty: e.target.value })} data-testid="demand-line-qty" />}
                  </td>
                  <td style={{ width: 150 }}>
                    {!editable ? fmtDate(l.due_date) : <input className="input sm" type="date" aria-label={`Line ${n} due date`} value={l.due_date} onChange={(e) => patch(i, { due_date: e.target.value })} data-testid="demand-line-due" />}
                  </td>
                  <td style={{ width: 170 }}>
                    {locked ? (
                      serialText(numOrNull(l.serial_from), numOrNull(l.serial_to)) || <span className="faint">-</span>
                    ) : (
                      <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                        <input className="input sm num" type="number" aria-label={`Line ${n} serial from`} placeholder="from" value={l.serial_from} onChange={(e) => patch(i, { serial_from: e.target.value })} style={{ width: 72 }} />
                        <input className="input sm num" type="number" aria-label={`Line ${n} serial to`} placeholder="to" value={l.serial_to} onChange={(e) => patch(i, { serial_to: e.target.value })} style={{ width: 72 }} />
                      </div>
                    )}
                    {!locked ? <SerialHint item={l.item} /> : null}
                  </td>
                  <td style={{ width: 80 }}>
                    {!editable ? (
                      l.priority ? `P${l.priority}` : <span className="faint">P{head.priority}</span>
                    ) : (
                      <input className="input sm num" type="number" min={1} max={9} aria-label={`Line ${n} priority`} placeholder={head.priority} value={l.priority} onChange={(e) => patch(i, { priority: e.target.value })} />
                    )}
                  </td>
                  <td className="right">{l.rec ? fmtNum(l.rec.shipped_qty) : ""}</td>
                  <td className="small">
                    {pr ? (
                      <span className="col" style={{ gap: 2 }}>
                        <ProjectionChip status={pr.status} lateDays={pr.late_days} />
                        <span className="faint">
                          {pr.projected_date ? `Projected ${fmtDate(pr.projected_date)}` : ""} ·{" "}
                          <Link to={mfgPaths.runDemand(pr.run_id, l.id ?? undefined)}>run #{pr.run_no}</Link>
                        </span>
                      </span>
                    ) : l.rec ? (
                      <span className="faint">{status === "open" ? "Run MRP to see the projection" : "Not planned"}</span>
                    ) : null}
                  </td>
                  <td className="right">
                    <span className="row" style={{ gap: 2, justifyContent: "flex-end", flexWrap: "nowrap" }}>
                      {l.rec && l.item?.make_buy === "make" && can("wo_edit") && l.rec.open_qty > 0 ? (
                        <Link
                          className="btn sm ghost"
                          to={`${mfgPaths.workOrderNew()}?item=${encodeURIComponent(l.item.id)}&qty=${l.rec.open_qty}&due=${l.rec.due_date}&demand_line=${encodeURIComponent(l.rec.id)}${l.rec.serial_from !== null ? `&serial_from=${l.rec.serial_from}&serial_to=${l.rec.serial_to}` : ""}`}
                          title="Create a work order for this line"
                        >
                          <Icon name="plus" /> WO
                        </Link>
                      ) : null}
                      {editable && !locked ? (
                        <button type="button" className="btn sm ghost icon" aria-label={`Remove line ${n}`} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))} disabled={lines.length <= 1}>
                          <Icon name="trash" />
                        </button>
                      ) : null}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {editable ? (
          <div className="card-footer row">
            <button type="button" className="btn sm" onClick={() => setLines((ls) => [...ls, blank()])} disabled={lines.length >= 500} data-testid="demand-add-line">
              <Icon name="plus" /> Add line
            </button>
            <span className="faint small">Serial numbers (optional, serialized items): the BOM valid for those units is used.</span>
          </div>
        ) : null}
      </div>

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
            <button type="button" className="btn primary" onClick={() => void save()} disabled={busy || !dirty || problems.length > 0} data-testid="demand-save">
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {isNew ? "Create demand order" : "Save changes"}
            </button>
            {order ? (
              <button type="button" className="btn" disabled={!dirty || busy} onClick={() => reset(order)}>
                Undo changes
              </button>
            ) : null}
          </div>
        </>
      ) : null}

      {confirm ? (
        <ConfirmDialog
          title={confirm === "close" ? "Close this order?" : confirm === "cancel" ? "Cancel this order?" : "Delete this order?"}
          confirmLabel={confirm === "close" ? "Close" : confirm === "cancel" ? "Cancel order" : "Delete"}
          cancelLabel="Keep"
          danger={confirm !== "close"}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            const a = confirm;
            setConfirm(null);
            void act(a);
          }}
        >
          <p style={{ margin: 0 }}>{confirm === "close" ? "Open quantities are no longer planned. A closed order can be re-opened." : "The order is no longer planned."}</p>
        </ConfirmDialog>
      ) : null}
      {shipping && order ? (
        <ShipDialog
          order={order}
          onClose={() => setShipping(false)}
          onDone={(no) => {
            setShipping(false);
            setNotice(`Shipped: posting ${no}.`);
            void getDemandOrder(order.id).then(reset, setError);
          }}
        />
      ) : null}
    </div>
  );
}
