/**
 * `/mfg/inventory/post?type=&item=&location=` (M2 14.2, 4.1): receipt / issue / transfer / adjustment / count
 * forms with a line grid. For lot-tracked items the lot can be left on "earliest expiry first" and the form shows
 * the FEFO pick the server will make. One `Idempotency-Key` per submitted body: a retry after a network error
 * reuses it (no double posting), any edit creates a new one.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ApiError } from "../../../api/client";
import { Banner } from "../../../components/Banner";
import { Icon } from "../../../components/Icon";
import { createPosting, getItemStock, newIdempotencyKey } from "../../api/clientM2";
import type { ItemRef } from "../../api/types";
import type { BalanceRow, PostingInput, PostingType } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { numOrNull } from "../../components/Field";
import { ItemPicker } from "../../components/ItemPicker";
import { PermissionGate } from "../../components/PermissionGate";
import { LocationSelect } from "../../components/PickersM2";
import { addDays, fmtDate } from "../../lib/format";
import { fmtNum, POSTING_LABEL } from "../../lib/formatM2";
import { isCountUom, loadItemInfo, useItemInfo } from "../../lib/itemCache";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { fieldErrors, isAbortError, todayInOffset, usePlant } from "../../lib/useMfg";
import { FORM_TYPES } from "./InventoryLayout";

const MAX_BACKDATE = 31;
const REASONS = ["SCRAP", "RTV", "SAMPLE", "DAMAGE", "FOUND", "LOST", "CORRECTION"];

const HELP: Record<string, string> = {
  receipt_misc: "Stock that arrives without a purchase order (free samples, returns from a customer, opening stock).",
  issue_misc: "Stock that leaves without a work order: scrap, return to vendor, samples. A reason is required.",
  transfer: "Move stock between locations, e.g. from goods-in inspection to stores, or stores to line side.",
  adjust: "Correct on-hand by a signed quantity (+ found, − lost). A reason is required.",
  count: "Enter what you counted; the difference is posted as an adjustment with reason COUNT.",
};

interface Line {
  key: number;
  item: ItemRef | null;
  location_id: string;
  to_location_id: string;
  lot_code: string;
  qty: string;
  expires_on: string;
  supplier_lot: string;
  unit_cost: string;
}

let lineSeq = 0;
const newLine = (item: ItemRef | null = null, location_id = ""): Line => ({
  key: ++lineSeq,
  item,
  location_id,
  to_location_id: "",
  lot_code: "",
  qty: "",
  expires_on: "",
  supplier_lot: "",
  unit_cost: "",
});

const isFormType = (t: string | null): t is PostingType => FORM_TYPES.includes(t as PostingType);

/** FEFO pick (M2 4.1): earliest expiry first, no expiry last, then lot code; held and expired lots skipped. */
export function fefoPick(balances: BalanceRow[], qty: number, txnDate: string): { lot: string; qty: number; expires: string | null }[] {
  const lots = balances
    .filter((b) => b.lot && !b.lot.hold && !(b.lot.expires_on && b.lot.expires_on <= txnDate) && b.qty_available > 0)
    .sort((a, b) => {
      const ea = a.lot?.expires_on ?? "9999-12-31";
      const eb = b.lot?.expires_on ?? "9999-12-31";
      return ea < eb ? -1 : ea > eb ? 1 : (a.lot?.lot_code ?? "").localeCompare(b.lot?.lot_code ?? "");
    });
  const out: { lot: string; qty: number; expires: string | null }[] = [];
  let rest = qty;
  for (const b of lots) {
    if (rest <= 1e-9) break;
    const take = Math.min(rest, b.qty_available);
    out.push({ lot: b.lot!.lot_code, qty: take, expires: b.lot!.expires_on });
    rest -= take;
  }
  return out;
}

function useBalances(itemId: string | undefined, locationId: string): BalanceRow[] | null {
  const [rows, setRows] = useState<BalanceRow[] | null>(null);
  useEffect(() => {
    if (!itemId || !locationId) {
      setRows(null);
      return;
    }
    const ctl = new AbortController();
    // `/items/{id}/stock` lists every non-zero balance of the item (all lots); keep this location's
    getItemStock(itemId, ctl.signal)
      .then((st) => setRows(st.balances.filter((b) => b.location.id === locationId)))
      .catch((e: unknown) => {
        if (!isAbortError(e)) setRows([]);
      });
    return () => ctl.abort();
  }, [itemId, locationId]);
  return rows;
}

function PostLineRow({
  type,
  line,
  index,
  txnDate,
  onChange,
  onRemove,
  canRemove,
  error,
}: {
  type: PostingType;
  line: Line;
  index: number;
  txnDate: string;
  onChange(patch: Partial<Line>): void;
  onRemove(): void;
  canRemove: boolean;
  error: string | null;
}) {
  const info = useItemInfo(line.item?.id);
  const lotTracked = Boolean(info?.lot_controlled);
  const balances = useBalances(type === "receipt_misc" ? undefined : line.item?.id, line.location_id);
  const available = balances?.filter((b) => (line.lot_code ? b.lot?.lot_code === line.lot_code : true)).reduce((s, b) => s + b.qty_available, 0);
  const onHand = balances?.filter((b) => (line.lot_code ? b.lot?.lot_code === line.lot_code : !b.lot)).reduce((s, b) => s + b.qty_on_hand, 0);
  const qty = numOrNull(line.qty);
  const isOut = type === "issue_misc" || type === "transfer";
  const pick = lotTracked && isOut && !line.lot_code && qty && balances ? fefoPick(balances, qty, txnDate) : null;
  const lotsHere = (balances ?? []).filter((b) => b.lot).map((b) => b.lot!);
  const uom = line.item?.uom ?? "";
  const fractional = qty !== null && isCountUom(uom) && !Number.isInteger(qty);
  const n = index + 1;

  const qtyLabel = type === "count" ? "Counted" : type === "adjust" ? "Change (+/−)" : "Quantity";

  return (
    <tr data-testid="post-line" data-index={index} className={error ? "mfg-line-error" : undefined}>
      <td className="faint">{n}</td>
      <td style={{ minWidth: 220 }}>
        <ItemPicker label={`Line ${n} item`} hideLabel value={line.item} onChange={(it) => onChange({ item: it, lot_code: "" })} testId="post-line-item" />
        {info ? (
          <div className="faint small mfg-ellipsis">
            {info.description}
            {lotTracked ? " · lot-tracked" : ""}
          </div>
        ) : null}
      </td>
      <td style={{ minWidth: 190 }}>
        <LocationSelect
          label={type === "transfer" ? `Line ${n} from location` : `Line ${n} location`}
          hideLabel
          value={line.location_id}
          onChange={(v) => onChange({ location_id: v, lot_code: isOut ? "" : line.lot_code })}
          testId="post-line-location"
        />
        {balances && type !== "receipt_misc" ? (
          <div className="faint small" data-testid="post-line-available">
            {type === "count" ? `Now on hand: ${fmtNum(onHand ?? 0)} ${uom}` : `Available: ${fmtNum(available ?? 0)} ${uom}`}
          </div>
        ) : null}
      </td>
      {type === "transfer" ? (
        <td style={{ minWidth: 190 }}>
          <LocationSelect label={`Line ${n} to location`} hideLabel value={line.to_location_id} onChange={(v) => onChange({ to_location_id: v })} testId="post-line-to-location" />
          {line.to_location_id && line.to_location_id === line.location_id ? <div className="field-error">Choose another location.</div> : null}
        </td>
      ) : null}
      <td style={{ minWidth: 150 }}>
        {!line.item ? (
          <span className="faint small">-</span>
        ) : !lotTracked ? (
          <span className="faint small">Not lot-tracked</span>
        ) : isOut ? (
          <select className="select sm" aria-label={`Line ${n} lot`} value={line.lot_code} onChange={(e) => onChange({ lot_code: e.target.value })} data-testid="post-line-lot">
            <option value="">Earliest expiry first</option>
            {lotsHere.map((l) => (
              <option key={l.id} value={l.lot_code} disabled={l.hold}>
                {l.lot_code}
                {l.expires_on ? ` (exp. ${fmtDate(l.expires_on)})` : ""}
                {l.hold ? " - on hold" : ""}
              </option>
            ))}
          </select>
        ) : (
          <>
            <input
              className="input sm"
              aria-label={`Line ${n} lot`}
              list={`lots-${line.key}`}
              value={line.lot_code}
              maxLength={64}
              onChange={(e) => onChange({ lot_code: e.target.value })}
              placeholder={type === "receipt_misc" ? "Required" : "Lot code"}
              aria-invalid={type === "receipt_misc" && !line.lot_code.trim()}
              data-testid="post-line-lot"
            />
            <datalist id={`lots-${line.key}`}>
              {lotsHere.map((l) => (
                <option key={l.id} value={l.lot_code} />
              ))}
            </datalist>
          </>
        )}
        {pick && pick.length ? (
          <div className="mfg-fefo" data-testid="post-line-fefo">
            Takes {pick.map((p) => `${fmtNum(p.qty)} from ${p.lot}`).join(", ")}
          </div>
        ) : null}
      </td>
      <td style={{ width: 120 }}>
        <input
          className="input sm num"
          type="number"
          step="any"
          aria-label={`Line ${n} ${qtyLabel.toLowerCase()}`}
          value={line.qty}
          onChange={(e) => onChange({ qty: e.target.value })}
          aria-invalid={fractional}
          data-testid="post-line-qty"
        />
        {fractional ? <div className="field-error">Whole {uom} only.</div> : null}
        {type === "count" && qty !== null && onHand !== undefined ? (
          <div className="faint small" data-testid="post-line-delta">
            Difference {qty - onHand >= 0 ? "+" : "−"}
            {fmtNum(Math.abs(qty - onHand))}
          </div>
        ) : null}
      </td>
      <td className="faint small">{uom}</td>
      {type === "receipt_misc" || ((type === "adjust" || type === "count") && lotTracked) ? (
        <td style={{ width: 150 }}>
          <input className="input sm" type="date" aria-label={`Line ${n} expires on`} value={line.expires_on} onChange={(e) => onChange({ expires_on: e.target.value })} disabled={!lotTracked && type !== "receipt_misc"} />
        </td>
      ) : type === "adjust" || type === "count" ? (
        <td />
      ) : null}
      {type === "receipt_misc" ? (
        <>
          <td style={{ width: 130 }}>
            <input className="input sm" aria-label={`Line ${n} supplier lot`} value={line.supplier_lot} maxLength={64} onChange={(e) => onChange({ supplier_lot: e.target.value })} />
          </td>
          <td style={{ width: 110 }}>
            <input className="input sm num" type="number" step="any" aria-label={`Line ${n} unit cost`} value={line.unit_cost} onChange={(e) => onChange({ unit_cost: e.target.value })} placeholder={info?.standard_cost != null ? String(info.standard_cost) : ""} />
          </td>
        </>
      ) : null}
      <td>
        <button type="button" className="btn sm ghost icon" aria-label={`Remove line ${n}`} onClick={onRemove} disabled={!canRemove}>
          <Icon name="trash" />
        </button>
      </td>
    </tr>
  );
}

function lineProblem(type: PostingType, l: Line): string | null {
  if (!l.item) return "Choose an item.";
  if (!l.location_id) return "Choose a location.";
  const q = numOrNull(l.qty);
  if (q === null) return type === "count" ? "Enter the counted quantity." : "Enter a quantity.";
  if (type === "count" ? q < 0 : type === "adjust" ? q === 0 : q <= 0)
    return type === "adjust" ? "The change cannot be 0." : type === "count" ? "Counted quantity cannot be negative." : "Quantity must be more than 0.";
  if (isCountUom(l.item.uom) && !Number.isInteger(q)) return `${l.item.uom} quantities are whole numbers.`;
  if (type === "transfer" && (!l.to_location_id || l.to_location_id === l.location_id)) return "Choose a different destination location.";
  return null;
}

function buildBody(type: PostingType, date: string, reason: string, note: string, lines: Line[]): PostingInput {
  const common = { txn_date: date || null, note, reason_code: reason.trim() || null };
  const lot = (l: Line) => l.lot_code.trim() || null;
  const qty = (l: Line) => numOrNull(l.qty) ?? 0;
  const items = lines.filter((l) => l.item);
  switch (type) {
    case "receipt_misc":
      return {
        ...common,
        type,
        lines: items.map((l) => ({
          item_id: l.item!.id,
          location_id: l.location_id,
          qty: qty(l),
          lot_code: lot(l),
          expires_on: l.expires_on || null,
          supplier_lot: l.supplier_lot.trim(),
          unit_cost: numOrNull(l.unit_cost),
        })),
      };
    case "issue_misc":
      return { ...common, type, lines: items.map((l) => ({ item_id: l.item!.id, location_id: l.location_id, lot_code: lot(l), qty: qty(l) })) };
    case "adjust":
      return { ...common, type, lines: items.map((l) => ({ item_id: l.item!.id, location_id: l.location_id, lot_code: lot(l), qty: qty(l), expires_on: l.expires_on || null })) };
    case "count":
      return {
        ...common,
        type,
        lines: items.map((l) => ({ item_id: l.item!.id, location_id: l.location_id, lot_code: lot(l), counted_qty: qty(l), expires_on: l.expires_on || null })),
      };
    default:
      return {
        ...common,
        type: "transfer",
        lines: items.map((l) => ({ item_id: l.item!.id, from_location_id: l.location_id, to_location_id: l.to_location_id, lot_code: lot(l), qty: qty(l) })),
      };
  }
}

/** Index of the line an API error points at (`details.line` or a field `loc` `["body","lines",i,...]`). */
function errorLine(err: unknown): number | null {
  if (!(err instanceof ApiError)) return null;
  if (typeof err.details.line === "number") return err.details.line;
  for (const f of fieldErrors(err)) {
    const i = f.loc.indexOf("lines");
    if (i >= 0 && typeof f.loc[i + 1] === "number") return f.loc[i + 1] as number;
  }
  return null;
}

export function PostingForm() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const plant = usePlant();
  const canPost = useCan("inventory");
  const typeParam = params.get("type");
  const type: PostingType = isFormType(typeParam) ? typeParam : "receipt_misc";
  const today = todayInOffset(plant.data?.utc_offset);
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<Line[]>(() => [newLine(null, params.get("location") ?? "")]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [touched, setTouched] = useState(false);
  const keyRef = useRef<{ body: string; key: string } | null>(null);

  // `?item=` preselects the first line's item
  const itemParam = params.get("item");
  useEffect(() => {
    if (!itemParam) return;
    let alive = true;
    loadItemInfo(itemParam).then(
      (it) =>
        alive &&
        setLines((ls) =>
          ls.length === 1 && !ls[0].item
            ? [{ ...ls[0], item: { id: it.id, part_number: it.part_number, revision: it.revision, description: it.description, uom: it.uom, make_buy: it.make_buy, active: it.active } }]
            : ls,
        ),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [itemParam]);

  const txnDate = date || today;
  const minDate = addDays(today, -MAX_BACKDATE);
  const dateBad = Boolean(date) && (date > today || date < minDate);
  const reasonRequired = type === "issue_misc" || type === "adjust";
  const problems = lines.map((l) => lineProblem(type, l));
  const errLine = errorLine(error);
  const blocking = problems.some(Boolean) || dateBad || (reasonRequired && !reason.trim());
  const body = useMemo(() => buildBody(type, date, reason, note, lines), [type, date, reason, note, lines]);

  const setType = (t: PostingType) => {
    setParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        n.set("type", t);
        return n;
      },
      { replace: true },
    );
    setError(null);
  };
  const patch = (i: number, p: Partial<Line>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...p } : l)));

  const submit = async () => {
    setTouched(true);
    if (blocking || busy) return;
    const text = JSON.stringify(body);
    if (!keyRef.current || keyRef.current.body !== text) keyRef.current = { body: text, key: newIdempotencyKey("post") };
    setBusy(true);
    setError(null);
    try {
      const { record, replay } = await createPosting(body, keyRef.current.key);
      keyRef.current = null;
      navigate(mfgPaths.posting(record.id), { state: { posted: true, replay } });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (!canPost)
    return (
      <Banner tone="warn" icon="lock" title="Posting is not available for your role" testId="forbidden-banner">
        Stock postings need the Store keeper role in this plant. You can still look at <Link to={mfgPaths.inventory()}>stock</Link> and the{" "}
        <Link to={mfgPaths.transactions()}>ledger</Link>.
      </Banner>
    );

  const showExpiry = type === "receipt_misc" || type === "adjust" || type === "count";

  return (
    <form
      className="col gap-lg"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      data-testid="posting-form"
      data-type={type}
    >
      <div className="row wrap" role="group" aria-label="Kind of stock movement">
        {FORM_TYPES.map((t) => (
          <button key={t} type="button" className={`btn sm${t === type ? " primary" : ""}`} aria-pressed={t === type} onClick={() => setType(t)} data-testid={`post-type-${t}`}>
            {POSTING_LABEL[t]}
          </button>
        ))}
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        {HELP[type]}
      </p>

      <section className="card">
        <div className="card-body form-grid">
          <div className="field">
            <label htmlFor="post-date">Posting date</label>
            <input id="post-date" className="input" type="date" value={date} min={minDate} max={today} placeholder={today} onChange={(e) => setDate(e.target.value)} aria-invalid={dateBad} data-testid="post-date" />
            <span className="hint">{dateBad ? `Between ${fmtDate(minDate)} and today.` : `Empty = today (${fmtDate(today)}). Up to ${MAX_BACKDATE} days back.`}</span>
          </div>
          <div className="field">
            <label htmlFor="post-reason">
              Reason{reasonRequired ? <span className="mfg-required" aria-hidden> *</span> : null}
            </label>
            <input
              id="post-reason"
              className="input"
              list="post-reasons"
              value={reason}
              maxLength={32}
              onChange={(e) => setReason(e.target.value.toUpperCase())}
              aria-required={reasonRequired}
              aria-invalid={touched && reasonRequired && !reason.trim()}
              placeholder={reasonRequired ? "e.g. SCRAP" : "Optional"}
              data-testid="post-reason"
            />
            <datalist id="post-reasons">
              {REASONS.map((r) => (
                <option key={r} value={r} />
              ))}
            </datalist>
            {touched && reasonRequired && !reason.trim() ? <span className="field-error">A reason is required for this movement.</span> : null}
          </div>
          <div className="field" style={{ gridColumn: "span 2" }}>
            <label htmlFor="post-note">Note</label>
            <input id="post-note" className="input" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. delivery note number" data-testid="post-note" />
          </div>
        </div>
      </section>

      <div className="table-wrap card">
        <table className="table mfg-grid-table" aria-label="Posting lines">
          <thead>
            <tr>
              <th>#</th>
              <th>Item</th>
              <th>{type === "transfer" ? "From" : "Location"}</th>
              {type === "transfer" ? <th>To</th> : null}
              <th>Lot</th>
              <th>{type === "count" ? "Counted" : type === "adjust" ? "Change (+/−)" : "Quantity"}</th>
              <th>Unit</th>
              {showExpiry ? <th>Expires on</th> : null}
              {type === "receipt_misc" ? (
                <>
                  <th>Supplier lot</th>
                  <th>Unit cost</th>
                </>
              ) : null}
              <th>
                <span className="sr-only">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <PostLineRow
                key={l.key}
                type={type}
                line={l}
                index={i}
                txnDate={txnDate}
                onChange={(p) => patch(i, p)}
                onRemove={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                canRemove={lines.length > 1}
                error={errLine === i ? "error" : touched ? problems[i] : null}
              />
            ))}
          </tbody>
        </table>
        <div className="card-footer row">
          <button type="button" className="btn sm" onClick={() => setLines((ls) => [...ls, newLine(null, ls[ls.length - 1]?.location_id ?? "")])} disabled={lines.length >= 500} data-testid="post-add-line">
            <Icon name="plus" /> Add line
          </button>
          <span className="faint small">{lines.length} of up to 500 lines</span>
        </div>
      </div>

      {touched && problems.some(Boolean) ? (
        <ul className="mfg-problem-list" role="alert">
          {problems.map((p, i) => (p ? <li key={i}>Line {i + 1}: {p}</li> : null))}
        </ul>
      ) : null}
      <MfgError error={error} title="Nothing was posted" />

      <div className="row mfg-sticky-actions">
        <PermissionGate perm="inventory" mode="disable">
          <button type="submit" className="btn primary" disabled={busy} data-testid="post-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Post {POSTING_LABEL[type].toLowerCase()}
          </button>
        </PermissionGate>
        <Link className="btn" to={mfgPaths.inventory()}>
          Cancel
        </Link>
        <span className="faint small">All lines are posted together, or none of them.</span>
      </div>
    </form>
  );
}
