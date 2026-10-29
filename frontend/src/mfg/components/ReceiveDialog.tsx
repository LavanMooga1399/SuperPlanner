/**
 * Receive goods against a purchase order (M2 14.2 `ReceiveDialog`, 4.1 `po_receipt`, 5.3): open deliveries in
 * dock-date order with the quantity received now, location (empty = the default goods-receipt location) and
 * lot for lot-tracked parts. One posting for all rows; one `Idempotency-Key` per submitted body.
 */
import { useMemo, useRef, useState } from "react";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { createPosting, newIdempotencyKey } from "../api/clientM2";
import type { PoReceiptLine, PostingRecord, PurchaseDocRecord } from "../api/typesM2";
import { fmtDate } from "../lib/format";
import { fmtNum } from "../lib/formatM2";
import { isCountUom, useItemInfo } from "../lib/itemCache";
import { todayInOffset, usePlant } from "../lib/useMfg";
import { MfgError } from "./Feedback";
import { numOrNull } from "./Field";
import { LocationSelect, useLocations } from "./PickersM2";
import { OverdueBadge } from "./StatusM2";

interface Row {
  schedule_id: string;
  label: string;
  part: string;
  item_id: string;
  uom: string;
  dock: string;
  open: number;
  overdue: number;
  qty: string;
  location_id: string;
  lot_code: string;
  expires_on: string;
  supplier_lot: string;
}

function LotCells({ row, onChange }: { row: Row; onChange(p: Partial<Row>): void }) {
  const info = useItemInfo(row.item_id);
  if (!info?.lot_controlled) return <td colSpan={3} className="faint small">Not lot-tracked</td>;
  return (
    <>
      <td>
        <input className="input sm" aria-label={`Lot for ${row.label}`} value={row.lot_code} maxLength={64} onChange={(e) => onChange({ lot_code: e.target.value })} placeholder="Required" aria-invalid={!row.lot_code.trim() && Boolean(numOrNull(row.qty))} data-testid="receive-lot" />
      </td>
      <td>
        <input className="input sm" type="date" aria-label={`Expiry for ${row.label}`} value={row.expires_on} onChange={(e) => onChange({ expires_on: e.target.value })} />
      </td>
      <td>
        <input className="input sm" aria-label={`Supplier lot for ${row.label}`} value={row.supplier_lot} maxLength={64} onChange={(e) => onChange({ supplier_lot: e.target.value })} />
      </td>
    </>
  );
}

export function ReceiveDialog({ doc, onClose, onDone, scheduleId }: { doc: PurchaseDocRecord; onClose(): void; onDone(p: PostingRecord): void; scheduleId?: string | null }) {
  const plant = usePlant();
  const locs = useLocations();
  const defaultLoc = locs?.find((l) => l.receipt_default && l.active);
  const [rows, setRows] = useState<Row[]>(() =>
    doc.lines
      .flatMap((l) =>
        l.schedules
          .filter((s) => !s.closed && s.open_qty > 0)
          .map((s) => ({
            schedule_id: s.id,
            label: `${doc.number} / ${l.line_no} / ${s.seq}`,
            part: l.item.part_number,
            item_id: l.item.id,
            uom: l.item.uom,
            dock: s.dock_date,
            open: s.open_qty,
            overdue: s.overdue ? s.overdue_days : -1,
            qty: s.id === scheduleId ? String(s.open_qty) : "",
            location_id: "",
            lot_code: "",
            expires_on: "",
            supplier_lot: "",
          })),
      )
      .sort((a, b) => (a.dock < b.dock ? -1 : a.dock > b.dock ? 1 : a.label.localeCompare(b.label))),
  );
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const keyRef = useRef<{ body: string; key: string } | null>(null);
  const today = todayInOffset(plant.data?.utc_offset);
  const tolerance = ((plant.data as { over_receipt_pct?: number } | null)?.over_receipt_pct ?? 0) / 100;

  const patch = (i: number, p: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const chosen = rows.filter((r) => (numOrNull(r.qty) ?? 0) > 0);
  const problems = rows
    .map((r) => {
      const q = numOrNull(r.qty);
      if (q === null || q === 0) return null;
      if (q < 0) return `${r.label}: quantity cannot be negative.`;
      if (isCountUom(r.uom) && !Number.isInteger(q)) return `${r.label}: ${r.uom} quantities are whole numbers.`;
      if (q > r.open * (1 + tolerance) + 1e-6) return `${r.label}: more than the ${fmtNum(r.open)} still open${tolerance ? ` (+${tolerance * 100}% allowed)` : ""}.`;
      if (!r.location_id && !defaultLoc) return `${r.label}: choose a location (there is no default goods-receipt location).`;
      return null;
    })
    .filter((x): x is string => Boolean(x));

  const lines: PoReceiptLine[] = useMemo(
    () =>
      chosen.map((r) => ({
        schedule_id: r.schedule_id,
        location_id: r.location_id || null,
        qty: numOrNull(r.qty) ?? 0,
        lot_code: r.lot_code.trim() || null,
        expires_on: r.expires_on || null,
        supplier_lot: r.supplier_lot.trim(),
      })),
    [chosen],
  );

  const submit = async () => {
    if (!lines.length || problems.length || busy) return;
    const body = { type: "po_receipt" as const, txn_date: date || null, note, lines };
    const text = JSON.stringify(body);
    if (!keyRef.current || keyRef.current.body !== text) keyRef.current = { body: text, key: newIdempotencyKey("grn") };
    setBusy(true);
    setError(null);
    try {
      const { record } = await createPosting(body, keyRef.current.key);
      onDone(record);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      title={`Receive goods: ${doc.number}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn ghost" onClick={() => setRows((rs) => rs.map((r) => ({ ...r, qty: String(r.open) })))} data-testid="receive-all">
            Fill all open quantities
          </button>
          <span className="grow" />
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={busy || !lines.length || problems.length > 0} data-testid="receive-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="download" />} Post goods receipt
          </button>
        </>
      }
    >
      <div className="col" data-testid="receive-dialog">
        {rows.length === 0 ? <p className="muted">Nothing is open on this order.</p> : null}
        <div className="form-grid">
          <div className="field">
            <label htmlFor="rcv-date">Receipt date</label>
            <input id="rcv-date" className="input" type="date" max={today} value={date} onChange={(e) => setDate(e.target.value)} />
            <span className="hint">Empty = today</span>
          </div>
          <div className="field" style={{ gridColumn: "span 2" }}>
            <label htmlFor="rcv-note">Note</label>
            <input id="rcv-note" className="input" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. GRN or delivery note number" />
          </div>
        </div>
        <div className="table-wrap">
          <table className="table mfg-grid-table">
            <thead>
              <tr>
                <th>Delivery</th>
                <th>Dock date</th>
                <th className="right">Open</th>
                <th>Receive now</th>
                <th>Into location</th>
                <th>Lot</th>
                <th>Expires</th>
                <th>Supplier lot</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.schedule_id} data-testid="receive-row" data-schedule-id={r.schedule_id}>
                  <td>
                    <div className="mono small">{r.label}</div>
                    <div className="faint small">{r.part}</div>
                  </td>
                  <td className="small">
                    {fmtDate(r.dock)} {r.overdue >= 0 ? <OverdueBadge days={r.overdue} /> : null}
                  </td>
                  <td className="right">
                    {fmtNum(r.open)} {r.uom}
                  </td>
                  <td style={{ width: 110 }}>
                    <input className="input sm num" type="number" step="any" min={0} aria-label={`Quantity received for ${r.label}`} value={r.qty} onChange={(e) => patch(i, { qty: e.target.value })} data-testid="receive-qty" />
                  </td>
                  <td style={{ minWidth: 180 }}>
                    <LocationSelect
                      label={`Location for ${r.label}`}
                      hideLabel
                      value={r.location_id}
                      allowEmpty
                      emptyLabel={defaultLoc ? `Default: ${defaultLoc.code}` : "Choose a location"}
                      onChange={(v) => patch(i, { location_id: v })}
                      testId="receive-location"
                    />
                  </td>
                  <LotCells row={r} onChange={(p) => patch(i, p)} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {problems.length ? (
          <ul className="mfg-problem-list" role="alert">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : null}
        <MfgError error={error} title="Nothing was received" />
      </div>
    </Dialog>
  );
}
