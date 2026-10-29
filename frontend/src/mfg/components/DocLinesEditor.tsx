/**
 * Purchase document lines with nested delivery schedules (M2 14.2 `DocLinesEditor`, 3.5): requested and
 * confirmed dock dates, quantities, received / open, available date and overdue badges. Lines or schedules with
 * receipts cannot be removed or reduced below what was received (the server checks the same, 5.1).
 */
import { useEffect } from "react";
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import type { ItemRef } from "../api/types";
import type { DocType, PurchaseLineInput, PurchaseLineRecord, ScheduleRecord } from "../api/typesM2";
import { addDays, fmtDate } from "../lib/format";
import { fmtMoney, fmtNum } from "../lib/formatM2";
import { isCountUom, useItemInfo } from "../lib/itemCache";
import { mfgPaths } from "../lib/paths";
import { numOrNull, numText } from "./Field";
import { ItemPicker } from "./ItemPicker";
import { OverdueBadge } from "./StatusM2";

export interface ScheduleDraft {
  key: number;
  id: string | null;
  requested_date: string;
  confirmed_date: string;
  qty: string;
  rec: ScheduleRecord | null;
}

export interface LineDraft {
  key: number;
  id: string | null;
  line_no: number | null;
  item: ItemRef | null;
  unit_price: string;
  note: string;
  rec: PurchaseLineRecord | null;
  schedules: ScheduleDraft[];
}

let seq = 0;
export const nextKey = () => ++seq;

export function newSchedule(date = ""): ScheduleDraft {
  return { key: nextKey(), id: null, requested_date: date, confirmed_date: "", qty: "", rec: null };
}

export function newDocLine(): LineDraft {
  return { key: nextKey(), id: null, line_no: null, item: null, unit_price: "", note: "", rec: null, schedules: [newSchedule()] };
}

export function linesFromRecord(lines: PurchaseLineRecord[]): LineDraft[] {
  return lines.map((l) => ({
    key: nextKey(),
    id: l.id,
    line_no: l.line_no,
    item: l.item,
    unit_price: numText(l.unit_price),
    note: l.note,
    rec: l,
    schedules: l.schedules.map((s) => ({
      key: nextKey(),
      id: s.id,
      requested_date: s.requested_date,
      confirmed_date: s.confirmed_date ?? "",
      qty: String(s.qty),
      rec: s,
    })),
  }));
}

export function linesToInput(lines: LineDraft[]): PurchaseLineInput[] {
  return lines
    .filter((l) => l.item)
    .map((l) => ({
      id: l.id,
      line_no: l.line_no,
      item_id: l.item!.id,
      unit_price: numOrNull(l.unit_price),
      note: l.note,
      schedules: l.schedules.map((s) => ({
        id: s.id,
        seq: s.rec?.seq ?? null,
        requested_date: s.requested_date,
        confirmed_date: s.confirmed_date || null,
        qty: numOrNull(s.qty) ?? 0,
      })),
    }));
}

/** Plain-language problems that block saving (the server re-checks everything). */
export function linesProblems(lines: LineDraft[]): string[] {
  const out: string[] = [];
  if (!lines.some((l) => l.item)) out.push("Add at least one line with a part.");
  lines.forEach((l, i) => {
    const n = l.line_no ?? (i + 1) * 10;
    if (!l.item) return;
    if (l.schedules.length === 0) out.push(`Line ${n}: add a delivery.`);
    l.schedules.forEach((s, j) => {
      const q = numOrNull(s.qty);
      if (!s.requested_date) out.push(`Line ${n}, delivery ${j + 1}: enter the requested dock date.`);
      if (q === null || q <= 0) out.push(`Line ${n}, delivery ${j + 1}: quantity must be more than 0.`);
      else if (isCountUom(l.item?.uom) && !Number.isInteger(q)) out.push(`Line ${n}, delivery ${j + 1}: ${l.item?.uom} quantities are whole numbers.`);
      else if (s.rec && q < s.rec.received_qty) out.push(`Line ${n}, delivery ${j + 1}: cannot be less than the ${fmtNum(s.rec.received_qty)} already received.`);
    });
  });
  return out;
}

function LineHint({ item }: { item: ItemRef | null }) {
  const info = useItemInfo(item?.id);
  if (!info) return null;
  return (
    <div className="faint small mfg-ellipsis">
      {info.description}
      {info.receiving_days ? ` · ${info.receiving_days} d inspection` : ""}
    </div>
  );
}

export function DocLinesEditor({
  docType,
  docId,
  lines,
  onChange,
  readOnly,
  currency,
  highlight,
}: {
  docType: DocType;
  docId: string | null;
  lines: LineDraft[];
  onChange(next: LineDraft[]): void;
  readOnly: boolean;
  currency?: string;
  /** `?line=` / `?schedule=` from server-built links. */
  highlight?: { line?: string | null; schedule?: string | null };
}) {
  useEffect(() => {
    if (highlight?.line || highlight?.schedule) document.querySelector(".mfg-highlight")?.scrollIntoView({ block: "center" });
  }, [highlight?.line, highlight?.schedule]);

  const setLine = (i: number, p: Partial<LineDraft>) => onChange(lines.map((l, j) => (j === i ? { ...l, ...p } : l)));
  const setSched = (i: number, k: number, p: Partial<ScheduleDraft>) =>
    setLine(i, { schedules: lines[i].schedules.map((s, j) => (j === k ? { ...s, ...p } : s)) });

  return (
    <div className="table-wrap card">
      <table className="table mfg-grid-table" aria-label="Lines and deliveries" data-testid="doc-lines">
        <thead>
          <tr>
            <th>Line</th>
            <th>Part / delivery</th>
            <th>Requested dock</th>
            <th>Confirmed dock</th>
            <th className="right">Quantity</th>
            <th className="right">Received</th>
            <th className="right">Open</th>
            <th>Available</th>
            <th className="right">Unit price</th>
            <th>
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => {
            const lineNo = l.line_no ?? (i + 1) * 10;
            const hasReceipts = (l.rec?.received_qty ?? 0) > 0;
            const lineLocked = readOnly || (l.rec !== null && l.rec.status !== "open");
            const total = l.schedules.reduce((s, x) => s + (numOrNull(x.qty) ?? 0), 0);
            const price = numOrNull(l.unit_price);
            return [
              <tr key={l.key} data-testid="doc-line" data-line-no={lineNo} className={l.id && l.id === highlight?.line ? "mfg-highlight" : undefined}>
                <td className="mono">{lineNo}</td>
                <td style={{ minWidth: 240 }}>
                  {readOnly || hasReceipts || (l.rec && l.rec.status !== "open") ? (
                    <>
                      <Link to={mfgPaths.item(l.item?.id ?? "")} className="mono">
                        {l.item?.part_number}
                      </Link>
                      {l.rec && l.rec.status !== "open" ? (
                        <span className="badge info" style={{ marginLeft: 6 }}>
                          {l.rec.status}
                          {l.rec.converted_to ? ` to ${l.rec.converted_to.number}` : ""}
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <ItemPicker label={`Line ${lineNo} part`} hideLabel value={l.item} makeBuy="buy" onChange={(it) => setLine(i, { item: it })} testId="doc-line-item" />
                  )}
                  <LineHint item={l.item} />
                  {l.rec?.source_pr ? (
                    <div className="faint small">
                      From <Link to={mfgPaths.purchaseDoc("pr", l.rec.source_pr.doc_id)}>{l.rec.source_pr.number}</Link> line {l.rec.source_pr.line_no}
                    </div>
                  ) : null}
                </td>
                <td colSpan={2} className="small muted">
                  {l.schedules.length} {l.schedules.length === 1 ? "delivery" : "deliveries"}
                </td>
                <td className="right">
                  <strong>{fmtNum(total)}</strong> {l.item?.uom}
                </td>
                <td className="right">{l.rec ? fmtNum(l.rec.received_qty) : ""}</td>
                <td className="right">{l.rec ? fmtNum(l.rec.open_qty) : ""}</td>
                <td />
                <td className="right" style={{ width: 120 }}>
                  {lineLocked ? (
                    price === null ? "" : fmtMoney(price, currency)
                  ) : (
                    <input
                      className="input sm num"
                      type="number"
                      step="any"
                      aria-label={`Line ${lineNo} unit price`}
                      value={l.unit_price}
                      placeholder="From supplier"
                      onChange={(e) => setLine(i, { unit_price: e.target.value })}
                    />
                  )}
                </td>
                <td className="right">
                  {!lineLocked ? (
                    <button type="button" className="btn sm ghost icon" aria-label={`Remove line ${lineNo}`} disabled={hasReceipts} title={hasReceipts ? "Has receipts" : undefined} onClick={() => onChange(lines.filter((_, j) => j !== i))}>
                      <Icon name="trash" />
                    </button>
                  ) : null}
                </td>
              </tr>,
              ...l.schedules.map((s, k) => {
                const r = s.rec;
                const received = r?.received_qty ?? 0;
                const locked = lineLocked || Boolean(r?.closed);
                const dock = s.confirmed_date || s.requested_date;
                return (
                  <tr
                    key={s.key}
                    data-testid="doc-schedule"
                    data-overdue={r?.overdue ? "true" : "false"}
                    data-seq={r?.seq ?? k + 1}
                    className={`mfg-schedule-row${r?.overdue ? " mfg-overdue" : ""}${s.id && s.id === highlight?.schedule ? " mfg-highlight" : ""}`}
                  >
                    <td />
                    <td className="small muted">
                      Delivery {r?.seq ?? k + 1}
                      {r?.closed ? " · closed" : ""}
                    </td>
                    <td>
                      {locked ? (
                        fmtDate(s.requested_date)
                      ) : (
                        <input className="input sm" type="date" aria-label={`Line ${lineNo} delivery ${k + 1} requested dock date`} value={s.requested_date} onChange={(e) => setSched(i, k, { requested_date: e.target.value })} data-testid="doc-schedule-requested" />
                      )}
                    </td>
                    <td>
                      {locked ? (
                        s.confirmed_date ? fmtDate(s.confirmed_date) : <span className="faint">not confirmed</span>
                      ) : (
                        <input className="input sm" type="date" aria-label={`Line ${lineNo} delivery ${k + 1} confirmed dock date`} value={s.confirmed_date} onChange={(e) => setSched(i, k, { confirmed_date: e.target.value })} data-testid="doc-schedule-confirmed" />
                      )}
                    </td>
                    <td className="right" style={{ width: 110 }}>
                      {locked ? (
                        fmtNum(numOrNull(s.qty))
                      ) : (
                        <input className="input sm num" type="number" step="any" min={received} aria-label={`Line ${lineNo} delivery ${k + 1} quantity`} value={s.qty} onChange={(e) => setSched(i, k, { qty: e.target.value })} data-testid="doc-schedule-qty" />
                      )}
                    </td>
                    <td className="right">{r ? fmtNum(received) : ""}</td>
                    <td className="right">{r ? fmtNum(r.open_qty) : ""}</td>
                    <td className="small">
                      {r ? fmtDate(r.available_date) : dock ? <span className="faint">{fmtDate(dock)}+</span> : ""}
                      {r?.overdue ? (
                        <>
                          {" "}
                          <OverdueBadge days={r.overdue_days} />
                        </>
                      ) : null}
                    </td>
                    <td />
                    <td className="right">
                      {!locked ? (
                        <button
                          type="button"
                          className="btn sm ghost icon"
                          aria-label={`Remove line ${lineNo} delivery ${k + 1}`}
                          disabled={received > 0 || l.schedules.length <= 1}
                          title={received > 0 ? "Has receipts" : undefined}
                          onClick={() => setLine(i, { schedules: l.schedules.filter((_, j) => j !== k) })}
                        >
                          <Icon name="x" />
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              }),
              !lineLocked ? (
                <tr key={`${l.key}-add`} className="mfg-schedule-row">
                  <td />
                  <td colSpan={9}>
                    <button
                      type="button"
                      className="btn sm ghost"
                      onClick={() => {
                        const last = l.schedules[l.schedules.length - 1];
                        const base = last?.confirmed_date || last?.requested_date;
                        setLine(i, { schedules: [...l.schedules, newSchedule(base ? addDays(base, 30) : "")] });
                      }}
                      data-testid="doc-add-schedule"
                      disabled={l.schedules.length >= 100}
                    >
                      <Icon name="plus" /> Add delivery (staggered)
                    </button>
                  </td>
                </tr>
              ) : null,
            ];
          })}
        </tbody>
      </table>
      {!readOnly ? (
        <div className="card-footer row">
          <button type="button" className="btn sm" onClick={() => onChange([...lines, newDocLine()])} disabled={lines.length >= 500} data-testid="doc-add-line">
            <Icon name="plus" /> Add line
          </button>
          <span className="faint small">
            {docType === "po" ? "Price empty = the supplier price of the part." : "A request can have its supplier chosen later, at conversion."}
            {docId ? "" : " Line numbers 10, 20, … are given on save."}
          </span>
        </div>
      ) : null}
    </div>
  );
}
