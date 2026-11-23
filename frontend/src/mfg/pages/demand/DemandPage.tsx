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
import { ErpOwnedNotice } from "../../components/ErpOwned";
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
import { toast } from "../../../components/Toast";
import { UnsavedChangesGuard } from "../../../components/UnsavedChangesGuard";
import { DateInput } from "../../../components/DateInput";
import { t, t as tr } from "../../../lib/i18n";

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
  if (q === null || q <= 0) return tr("mfg.demandPage.str.quantityMustBeMoreThan");
  if (isCountUom(l.item.uom) && !Number.isInteger(q)) return tr("mfg.demandPage.tpl.quantitiesAreWholeNumbers", { uom: l.item.uom });
  if (!l.due_date) return tr("mfg.demandPage.str.enterTheDueDate");
  const f = numOrNull(l.serial_from);
  const t = numOrNull(l.serial_to);
  if ((f === null) !== (t === null)) return tr("mfg.demandPage.str.giveBothSerialNumbersOr");
  if (f !== null && t !== null && t - f + 1 !== q) return tr("mfg.demandPage.tpl.serialsAreUnitsTheQuantity", { f: f, t: t, v: t - f + 1, q: q });
  const p = numOrNull(l.priority);
  if (p !== null && !(Number.isInteger(p) && p >= 1 && p <= 9)) return tr("mfg.demandPage.str.priorityIs1MostImportant");
  if (l.rec && q < l.rec.shipped_qty) return tr("mfg.demandPage.tpl.cannotBeLessThanThe", { shippedqty: fmtNum(l.rec.shipped_qty) });
  return null;
}

function SerialHint({ item }: { item: ItemRef | null }) {
  const info = useItemInfo(item?.id);
  if (!info || info.serialized) return null;
  return <div className="faint small">{tr("mfg.demandPage.text.notSerialized")}</div>;
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
      note: tr("mfg.demandPage.tpl.shipment", { number: order.number }),
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
      title={tr("mfg.demandPage.tpl.ship", { number: order.number })}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("mfg.demandPage.btn.cancel")}
          </button>
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={busy || !chosen.length || bad} data-testid="ship-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />}{" "}{tr("mfg.demandPage.text.postShipment")}
          </button>
        </>
      }
    >
      <div className="col">
        <table className="table mfg-grid-table">
          <thead>
            <tr>
              <th>{t("mfg.demandPage.head.line")}</th>
              <th className="right">{t("mfg.demandPage.head.open")}</th>
              <th>{t("mfg.demandPage.head.shipNow")}</th>
              <th>{t("mfg.demandPage.head.fromLocation")}</th>
              <th>{t("mfg.demandPage.head.lot")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.line.id} data-testid="ship-row">
                <td>
                  <span className="mono">{r.line.line_no}</span> {r.line.item.part_number}
                  {r.line.serial_from !== null ? <span className="faint small">{" "}{tr("mfg.demandPage.text.units", { serialfrom: serialText(r.line.serial_from, r.line.serial_to) })}</span> : null}
                </td>
                <td className="right">
                  {fmtNum(r.line.open_qty)} {r.line.item.uom}
                </td>
                <td style={{ width: 100 }}>
                  <input className="input sm num" type="number" min={0} max={r.line.open_qty} aria-label={tr("mfg.demandPage.tpl.shipQuantityLine", { lineno: r.line.line_no })} value={r.qty} onChange={(e) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} data-testid="ship-qty" />
                </td>
                <td style={{ minWidth: 180 }}>
                  <LocationSelect label={tr("mfg.demandPage.tpl.locationLine", { lineno: r.line.line_no })} hideLabel value={r.location_id} kinds={["stores", "line_side"]} onChange={(v) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, location_id: v } : x)))} testId="ship-location" />
                </td>
                <td>
                  <input className="input sm" aria-label={tr("mfg.demandPage.tpl.lotLine", { lineno: r.line.line_no })} value={r.lot_code} placeholder={t("mfg.demandPage.ph.earliestExpiry")} onChange={(e) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, lot_code: e.target.value } : x)))} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {bad ? <p className="field-error">{tr("mfg.demandPage.text.eachShippedLineNeedsA")}</p> : null}
        <MfgError error={error} title={tr("mfg.demandPage.attr.nothingWasShipped")} />
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

  if (!isNew && loaded.error && isNotFound(loaded.error)) return <NotFoundPanel what={tr("mfg.demandPage.attr.demandOrder")} back={<Link className="btn" to={mfgPaths.demand()}>{tr("mfg.demandPage.text.backToDemand")}</Link>} />;
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
  const problems = lines.map((l, i) => (lineProblem(l) ? tr("mfg.demandPage.tpl.line", { v: l.line_no ?? (i + 1) * 10, l: lineProblem(l) }) : null)).filter((x): x is string => Boolean(x));
  if (!body.lines.length) problems.push(tr("mfg.demandPage.str.addAtLeastOneLine"));

  const save = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (isNew) {
        const o = await createDemandOrder(body);
        toast(tr("mfg.demandPage.tpl.demandOrderCreated", { number: o.number }));
        navigate(mfgPaths.demandOrder(o.id), { replace: true });
      } else if (order) {
        reset(await updateDemandOrder(order.id, body, order.row_version));
        toast(t("mfg.demandPage.toast.changesSaved"));
        setNotice(tr("mfg.demandPage.str.saved"));
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
      setNotice(a === "open" ? tr("mfg.demandPage.str.theOrderIsOpenThe") : a === "close" ? tr("mfg.demandPage.str.closed") : tr("mfg.demandPage.str.cancelled"));
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
      <UnsavedChangesGuard when={!isNew && dirty && !busy} what={tr("mfg.demandPage.attr.thisDemandOrder")} />
      <nav aria-label={t("mfg.demandPage.aria.breadcrumb")} className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.demand()}>{tr("mfg.demandPage.text.demand")}</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{order?.number ?? tr("mfg.demandPage.str.newDemandOrder")}</span>
      </nav>
      <div className="ws-header">
        <div className="ws-title">
          <h1 className="mono" data-testid="demand-title">
            {order?.number ?? tr("mfg.demandPage.str.newDemandOrder")}
          </h1>
          {order ? <DemandStatusChip status={order.status} testId="demand-status-chip" /> : null}
        </div>
        {order && can("demand_edit") ? (
          <div className="mfg-actions">
            {status === "draft" || status === "closed" ? (
              <button type="button" className="btn primary" onClick={() => void act("open")} disabled={busy || dirty} title={dirty ? tr("mfg.demandPage.str.saveYourChangesFirst") : undefined} data-testid="demand-action-open">
                <Icon name="play" /> {status === "draft" ? tr("mfg.demandPage.str.openForPlanning") : "Re-open"}
              </button>
            ) : null}
            {status === "open" ? (
              <button type="button" className="btn" onClick={() => setConfirm("close")} disabled={busy || dirty} data-testid="demand-action-close">
                <Icon name="lock" /> {t("mfg.demandPage.btn.close")}
              </button>
            ) : null}
            {(status === "draft" || status === "open") && !hasShipments ? (
              <button type="button" className="btn" onClick={() => setConfirm("cancel")} disabled={busy} data-testid="demand-action-cancel">
                <Icon name="ban" /> {t("mfg.demandPage.btn.cancel")}
              </button>
            ) : null}
            {(status === "draft" || status === "cancelled") && !hasShipments ? (
              <button type="button" className="btn danger" onClick={() => setConfirm("delete")} disabled={busy}>
                <Icon name="trash" /> {t("mfg.demandPage.btn.delete")}
              </button>
            ) : null}
          </div>
        ) : null}
        {order && status === "open" && can("inventory") ? (
          <button type="button" className="btn" onClick={() => setShipping(true)} disabled={!order.lines.some((l) => l.open_qty > 0)} data-testid="demand-ship">
            <Icon name="arrow-right" /> {t("mfg.demandPage.btn.ship")}
          </button>
        ) : null}
      </div>

      {conflict ? <ConflictBanner onReload={() => void getDemandOrder(orderId).then(reset, setError)} what={tr("mfg.demandPage.attr.thisDemandOrder")} /> : null}
      <ErpOwnedNotice entity="demand_orders" label={t("mfg.demandPage.label.demandOrdersExceptPriority")} />
      {notice ? <Banner tone="ok" role="status" title={notice} /> : null}
      {status === "draft" && order ? (
        <Banner tone="warn" title={t("mfg.demandPage.title.draftNotPlannedYet")}>
          {tr("mfg.demandPage.text.openTheOrderWhenIt")}
        </Banner>
      ) : null}
      <MfgError error={error} title={tr("mfg.demandPage.attr.thatDidNotWork")} />

      <section className="card">
        <div className="card-body form-grid">
          <TextField label={t("mfg.demandPage.label.number")} value={head.number} onChange={(v) => setHead({ ...head, number: v })} maxLength={32} placeholder={t("mfg.demandPage.ph.nextFreeNumber")} disabled={!editable || !isNew} testId="demand-number" />
          <SelectField label={t("mfg.demandPage.label.type")} value={head.demand_type} onChange={(v) => setHead({ ...head, demand_type: v })} options={DEMAND_TYPES.map((t) => ({ value: t, label: DEMAND_TYPE_LABEL[t] }))} disabled={!editable} testId="demand-type" />
          <TextField label={t("mfg.demandPage.label.customer")} value={head.customer} onChange={(v) => setHead({ ...head, customer: v })} disabled={!editable} testId="demand-customer" />
          <TextField label={t("mfg.demandPage.label.programme")} value={head.program} onChange={(v) => setHead({ ...head, program: v.toUpperCase() })} maxLength={32} disabled={!editable} hint={t("mfg.demandPage.hint.egKvp27MrpCanProtect")} />
          <TextField label={t("mfg.demandPage.label.priority1MostImportant")} type="number" value={head.priority} onChange={(v) => setHead({ ...head, priority: v })} disabled={!editable} hint={t("mfg.demandPage.hint.1To9LinesCan")} testId="demand-priority" />
          <TextField label={t("mfg.demandPage.label.externalReference")} value={head.external_ref} onChange={(v) => setHead({ ...head, external_ref: v })} maxLength={64} disabled={!editable} />
          <div style={{ gridColumn: "span 2" }}>
            <TextField label={t("mfg.demandPage.label.note")} value={head.note} onChange={(v) => setHead({ ...head, note: v })} maxLength={500} disabled={!editable} />
          </div>
        </div>
      </section>

      <div className="table-wrap card">
        <table className="table mfg-grid-table" data-testid="demand-lines">
          <thead>
            <tr>
              <th>{t("mfg.demandPage.head.line")}</th>
              <th>{t("mfg.demandPage.head.item")}</th>
              <th className="right">{t("mfg.demandPage.head.quantity")}</th>
              <th>{t("mfg.demandPage.head.dueDate")}</th>
              <th>{t("mfg.demandPage.head.unitSerials")}</th>
              <th>{t("mfg.demandPage.head.priority")}</th>
              <th className="right">{t("mfg.demandPage.head.shipped")}</th>
              <th>{t("mfg.demandPage.head.latestPlan")}</th>
              <th>
                <span className="sr-only">{tr("mfg.demandPage.text.actions")}</span>
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
                      <ItemPicker label={tr("mfg.demandPage.tpl.lineItem", { n: n })} hideLabel value={l.item} onChange={(it) => patch(i, { item: it })} testId="demand-line-item" />
                    )}
                    {l.item ? <div className="faint small mfg-ellipsis">{l.item.description}</div> : null}
                  </td>
                  <td style={{ width: 96 }}>
                    {!editable ? fmtNum(numOrNull(l.qty)) : <input className="input sm num" type="number" aria-label={tr("mfg.demandPage.tpl.lineQuantity", { n: n })} value={l.qty} onChange={(e) => patch(i, { qty: e.target.value })} data-testid="demand-line-qty" />}
                  </td>
                  <td style={{ width: 150 }}>
                    {!editable ? fmtDate(l.due_date) : <DateInput small ariaLabel={`Line ${n} due date`} value={l.due_date} testId="demand-line-due" onChange={(v) => patch(i, { due_date: v })} />}
                  </td>
                  <td style={{ width: 170 }}>
                    {locked ? (
                      serialText(numOrNull(l.serial_from), numOrNull(l.serial_to)) || <span className="faint">-</span>
                    ) : (
                      <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                        <input className="input sm num" type="number" aria-label={tr("mfg.demandPage.tpl.lineSerialFrom", { n: n })} placeholder={t("mfg.demandPage.ph.from")} value={l.serial_from} onChange={(e) => patch(i, { serial_from: e.target.value })} style={{ width: 72 }} />
                        <input className="input sm num" type="number" aria-label={tr("mfg.demandPage.tpl.lineSerialTo", { n: n })} placeholder={t("mfg.demandPage.ph.to")} value={l.serial_to} onChange={(e) => patch(i, { serial_to: e.target.value })} style={{ width: 72 }} />
                      </div>
                    )}
                    {!locked ? <SerialHint item={l.item} /> : null}
                  </td>
                  <td style={{ width: 80 }}>
                    {!editable ? (
                      l.priority ? `P${l.priority}` : <span className="faint">P{head.priority}</span>
                    ) : (
                      <input className="input sm num" type="number" min={1} max={9} aria-label={tr("mfg.demandPage.tpl.linePriority", { n: n })} placeholder={head.priority} value={l.priority} onChange={(e) => patch(i, { priority: e.target.value })} />
                    )}
                  </td>
                  <td className="right">{l.rec ? fmtNum(l.rec.shipped_qty) : ""}</td>
                  <td className="small">
                    {pr ? (
                      <span className="col" style={{ gap: 2 }}>
                        <ProjectionChip status={pr.status} lateDays={pr.late_days} />
                        <span className="faint">
                          {pr.projected_date ? tr("mfg.demandPage.tpl.projected", { projecteddate: fmtDate(pr.projected_date) }) : ""} ·{" "}
                          <Link to={mfgPaths.runDemand(pr.run_id, l.id ?? undefined)}>{tr("common.runNoInline", { n: pr.run_no })}</Link>
                        </span>
                      </span>
                    ) : l.rec ? (
                      <span className="faint">{status === "open" ? tr("mfg.demandPage.str.runMrpToSeeThe") : tr("mfg.demandPage.str.notPlanned")}</span>
                    ) : null}
                  </td>
                  <td className="right">
                    <span className="row" style={{ gap: 2, justifyContent: "flex-end", flexWrap: "nowrap" }}>
                      {l.rec && l.item?.make_buy === "make" && can("wo_edit") && l.rec.open_qty > 0 ? (
                        <Link
                          className="btn sm ghost"
                          to={`${mfgPaths.workOrderNew()}?item=${encodeURIComponent(l.item.id)}&qty=${l.rec.open_qty}&due=${l.rec.due_date}&demand_line=${encodeURIComponent(l.rec.id)}${l.rec.serial_from !== null ? `&serial_from=${l.rec.serial_from}&serial_to=${l.rec.serial_to}` : ""}`}
                          title={tr("mfg.demandPage.attr.createAWorkOrderFor")}
                        >
                          <Icon name="plus" /> {t("mfg.demandPage.btn.wo")}
                        </Link>
                      ) : null}
                      {editable && !locked ? (
                        <button type="button" className="btn sm ghost icon" aria-label={tr("mfg.demandPage.tpl.removeLine", { n: n })} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))} disabled={lines.length <= 1}>
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
              <Icon name="plus" /> {t("mfg.demandPage.btn.addLine")}
            </button>
            <span className="faint small">{tr("mfg.demandPage.text.serialNumbersOptionalSerializedItems")}</span>
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
              {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} {isNew ? tr("mfg.demandPage.str.createDemandOrder") : tr("mfg.demandPage.str.saveChanges")}
            </button>
            {order ? (
              <button type="button" className="btn" disabled={!dirty || busy} onClick={() => reset(order)}>
                {t("mfg.demandPage.btn.undoChanges")}
              </button>
            ) : null}
          </div>
        </>
      ) : null}

      {confirm ? (
        <ConfirmDialog
          title={confirm === "close" ? tr("mfg.demandPage.str.closeThisOrder") : confirm === "cancel" ? tr("mfg.demandPage.str.cancelThisOrder") : tr("mfg.demandPage.str.deleteThisOrder")}
          confirmLabel={confirm === "close" ? tr("mfg.demandPage.str.close") : confirm === "cancel" ? tr("mfg.demandPage.str.cancelOrder") : "Delete"}
          cancelLabel={t("mfg.demandPage.btn.keep")}
          danger={confirm !== "close"}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            const a = confirm;
            setConfirm(null);
            void act(a);
          }}
        >
          <p style={{ margin: 0 }}>{confirm === "close" ? tr("mfg.demandPage.str.openQuantitiesAreNoLonger") : tr("mfg.demandPage.str.theOrderIsNoLonger")}</p>
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
