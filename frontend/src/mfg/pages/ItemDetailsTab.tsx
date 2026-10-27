/**
 * Item details (M 11.1): full edit form saved with If-Match. A 412 shows the conflict banner and keeps the
 * user's edits on screen until they choose "Reload latest". Expert fields sit behind "More details".
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { deleteItem, getItem, updateItem } from "../api/client";
import type { AttrValue, Attributes, ItemInput, ItemRecord, MakeBuy } from "../api/types";
import type { ItemM2Fields, LotRuleM2 } from "../api/typesM2";
import { ConflictBanner, MfgError, SaveState } from "../components/Feedback";
import { CheckField, numOr, numOrNull, numText, SelectField, strOrNull, TextField } from "../components/Field";
import { MAKE_BUY_OPTIONS, useUomOptions } from "../components/NewItemDialog";
import { fmtTimestamp } from "../lib/format";
import { mfgPaths } from "../lib/paths";
import { isConflict } from "../lib/useMfg";
import { useItem } from "./ItemShell";

interface AttrRow {
  key: string;
  type: "text" | "number" | "yes/no";
  value: string;
}

interface ItemForm {
  part_number: string;
  revision: string;
  description: string;
  uom: string;
  make_buy: MakeBuy;
  family: string;
  setup_family: string;
  lead_time_days: string;
  receiving_days: string;
  lot_rule: LotRuleM2;
  fixed_lot_qty: string;
  lot_period_days: string;
  lot_controlled: boolean;
  standard_cost: string;
  external_ref: string;
  /** The server returned the M2 item fields (3.1): send them back on PUT (full replacement). */
  m2: boolean;
  min_order_qty: string;
  order_multiple: string;
  safety_stock: string;
  serialized: boolean;
  shelf_life_days: string;
  handling_class: string;
  handling_note: string;
  active: boolean;
  attributes: AttrRow[];
}

function attrRows(a: Attributes): AttrRow[] {
  return Object.entries(a).map(([key, v]) => ({
    key,
    type: typeof v === "number" ? "number" : typeof v === "boolean" ? "yes/no" : "text",
    value: String(v),
  }));
}

function toForm(it: ItemRecord): ItemForm {
  const x = it as ItemRecord & ItemM2Fields;
  const m2 = "lot_controlled" in it;
  return {
    m2,
    lot_period_days: numText(x.lot_period_days),
    lot_controlled: Boolean(x.lot_controlled),
    standard_cost: numText(x.standard_cost),
    external_ref: x.external_ref ?? "",
    part_number: it.part_number,
    revision: it.revision,
    description: it.description,
    uom: it.uom,
    make_buy: it.make_buy,
    family: it.family ?? "",
    setup_family: it.setup_family ?? "",
    lead_time_days: numText(it.lead_time_days),
    receiving_days: String(it.receiving_days),
    lot_rule: it.lot_rule,
    fixed_lot_qty: numText(it.fixed_lot_qty),
    min_order_qty: String(it.min_order_qty),
    order_multiple: String(it.order_multiple),
    safety_stock: String(it.safety_stock),
    serialized: it.serialized,
    shelf_life_days: numText(it.shelf_life_days),
    handling_class: it.handling_class ?? "",
    handling_note: it.handling_note,
    active: it.active,
    attributes: attrRows(it.attributes),
  };
}

function toInput(f: ItemForm): ItemInput & ItemM2Fields {
  const attributes: Attributes = {};
  for (const r of f.attributes) {
    const k = r.key.trim();
    if (!k) continue;
    let v: AttrValue = r.value;
    if (r.type === "number") v = numOr(r.value, 0);
    else if (r.type === "yes/no") v = /^(true|yes|y|1)$/i.test(r.value.trim());
    attributes[k] = v;
  }
  const m2: ItemM2Fields = f.m2
    ? {
        external_ref: strOrNull(f.external_ref),
        standard_cost: numOrNull(f.standard_cost),
        lot_controlled: f.lot_controlled,
        lot_period_days: f.lot_rule === "period" ? numOrNull(f.lot_period_days) : null,
      }
    : {};
  return {
    ...m2,
    part_number: f.part_number.trim(),
    revision: f.revision.trim() || "A",
    description: f.description,
    uom: f.uom,
    make_buy: f.make_buy,
    family: strOrNull(f.family),
    setup_family: strOrNull(f.setup_family),
    lead_time_days: numOrNull(f.lead_time_days),
    receiving_days: numOr(f.receiving_days, 0),
    lot_rule: f.m2 || f.lot_rule !== "period" ? f.lot_rule : "lot_for_lot",
    fixed_lot_qty: f.lot_rule === "fixed" ? numOrNull(f.fixed_lot_qty) : null,
    min_order_qty: numOr(f.min_order_qty, 0),
    order_multiple: numOr(f.order_multiple, 0),
    safety_stock: numOr(f.safety_stock, 0),
    serialized: f.serialized,
    shelf_life_days: numOrNull(f.shelf_life_days),
    handling_class: strOrNull(f.handling_class),
    handling_note: f.handling_note,
    attributes,
    active: f.active,
  };
}

export function ItemDetailsTab() {
  const { item, setItem } = useItem();
  const navigate = useNavigate();
  const [form, setForm] = useState<ItemForm>(() => toForm(item));
  const [base, setBase] = useState<ItemRecord>(item);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);
  const [more, setMore] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<unknown>(null);
  const uoms = useUomOptions();

  // A different item (navigation) resets the form; the same item keeps the user's edits.
  useEffect(() => {
    if (item.id !== base.id) {
      setBase(item);
      setForm(toForm(item));
      setConflict(false);
      setError(null);
    }
  }, [item, base.id]);

  const dirty = JSON.stringify(toInput(form)) !== JSON.stringify(toInput(toForm(base)));
  const set = <K extends keyof ItemForm>(k: K, v: ItemForm[K]) => {
    setForm((f) => ({ ...f, [k]: v }));
    setSaved(false);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await updateItem(base.id, toInput(form), base.row_version);
      setBase(next);
      setItem(next);
      setForm(toForm(next));
      setSaved(true);
      setConflict(false);
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  const reloadLatest = async () => {
    try {
      const latest = await getItem(base.id);
      setBase(latest);
      setItem(latest);
      setForm(toForm(latest));
      setConflict(false);
      setError(null);
    } catch (e) {
      setError(e);
    }
  };

  const remove = async () => {
    try {
      await deleteItem(base.id, base.row_version);
      navigate(mfgPaths.items());
    } catch (e) {
      setDeleteError(e);
      setConfirmDelete(false);
    }
  };

  const fixedMissing = form.lot_rule === "fixed" && numOrNull(form.fixed_lot_qty) === null;
  const periodMissing = form.lot_rule === "period" && numOrNull(form.lot_period_days) === null;
  const buyNoLead = form.make_buy === "buy" && numOrNull(form.lead_time_days) === null;

  return (
    <form
      className="col gap-lg"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      data-testid="item-form"
    >
      {conflict ? <ConflictBanner onReload={() => void reloadLatest()} what="this item" /> : null}
      <MfgError error={error} title="Could not save the item" />
      <MfgError error={deleteError} title="The item could not be deleted" />

      <section className="card">
        <div className="card-header">
          <h2>Item</h2>
          <span className="muted small">Last changed {fmtTimestamp(base.updated_at)}</span>
        </div>
        <div className="card-body col">
          <div className="form-grid">
            <TextField label="Part number" value={form.part_number} onChange={(v) => set("part_number", v)} required maxLength={64} testId="item-part-number" />
            <TextField label="Revision" value={form.revision} onChange={(v) => set("revision", v)} maxLength={16} />
            <SelectField label="Make or buy" value={form.make_buy} onChange={(v) => set("make_buy", v)} options={MAKE_BUY_OPTIONS} testId="item-make-buy" />
            <SelectField label="Unit" value={form.uom} onChange={(v) => set("uom", v)} options={uoms} />
          </div>
          <TextField label="Description" value={form.description} onChange={(v) => set("description", v)} maxLength={500} testId="item-description" />
          <div className="form-grid">
            <TextField label="Family" value={form.family} onChange={(v) => set("family", v)} maxLength={32} hint="Groups similar items; lines can be limited to families." />
            <TextField
              label="Lead time (days)"
              type="number"
              value={form.lead_time_days}
              onChange={(v) => set("lead_time_days", v)}
              testId="item-lead-time"
              hint={
                form.make_buy === "buy"
                  ? buyNoLead
                    ? "Required before planning (0 if stocked locally)."
                    : "Supplier lead time."
                  : "Optional fixed lead time; empty = use the routing time."
              }
            />
            <CheckField
              label="Active"
              checked={form.active}
              onChange={(v) => set("active", v)}
              hint="Inactive items stay in old BOMs but are flagged when used."
              testId="item-active"
            />
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>Ordering and stock</h2>
        </div>
        <div className="card-body form-grid">
          <SelectField
            label="Lot size rule"
            value={form.lot_rule}
            onChange={(v) => set("lot_rule", v)}
            options={[
              { value: "lot_for_lot", label: "Order exactly what is needed" },
              { value: "fixed", label: "Always order a fixed quantity" },
              ...(form.m2 ? [{ value: "period" as const, label: "Combine needs of a period into one order" }] : []),
            ]}
            testId="item-lot-rule"
          />
          {form.lot_rule === "period" ? (
            <TextField
              label="Period (days)"
              type="number"
              value={form.lot_period_days}
              onChange={(v) => set("lot_period_days", v)}
              required
              hint={periodMissing ? "Required: 1 to 365 days." : "Needs within this many days become one order."}
              testId="item-lot-period"
            />
          ) : null}
          {form.lot_rule === "fixed" ? (
            <TextField
              label="Fixed lot quantity"
              type="number"
              value={form.fixed_lot_qty}
              onChange={(v) => set("fixed_lot_qty", v)}
              required
              hint={fixedMissing ? "Required for a fixed lot size." : undefined}
            />
          ) : null}
          <TextField label="Minimum order quantity" type="number" value={form.min_order_qty} onChange={(v) => set("min_order_qty", v)} hint="0 = no minimum" />
          <TextField label="Order multiple" type="number" value={form.order_multiple} onChange={(v) => set("order_multiple", v)} hint="e.g. reel of 5000; 0 = none" />
          <TextField label="Safety stock" type="number" value={form.safety_stock} onChange={(v) => set("safety_stock", v)} />
          <TextField label="Goods-in inspection (days)" type="number" value={form.receiving_days} onChange={(v) => set("receiving_days", v)} />
          {form.m2 ? (
            <>
              <TextField
                label="Standard cost"
                type="number"
                value={form.standard_cost}
                onChange={(v) => set("standard_cost", v)}
                hint="Per unit, in the plant currency; values stock."
                testId="item-standard-cost"
              />
              <CheckField
                label="Track lots"
                checked={form.lot_controlled}
                onChange={(v) => set("lot_controlled", v)}
                hint="Receipts need a lot code; issues pick the earliest expiry first."
                testId="item-lot-controlled"
              />
            </>
          ) : null}
        </div>
      </section>

      <div>
        <button type="button" className="btn ghost sm" aria-expanded={more} onClick={() => setMore((m) => !m)} data-testid="item-more-toggle">
          <Icon name={more ? "chevron-down" : "chevron-right"} /> More details (setup family, serial numbers, handling, attributes)
        </button>
      </div>
      {more ? (
        <section className="card" data-testid="item-more">
          <div className="card-body col">
            <div className="form-grid">
              <TextField
                label="Setup family"
                value={form.setup_family}
                onChange={(v) => set("setup_family", v)}
                maxLength={32}
                hint="Changeover class; empty = same as family."
              />
              <CheckField label="Serial numbers" checked={form.serialized} onChange={(v) => set("serialized", v)} hint="Units carry serial numbers (allows BOMs per serial range)." />
              <TextField label="Shelf life (days)" type="number" value={form.shelf_life_days} onChange={(v) => set("shelf_life_days", v)} />
              <TextField label="Handling class" value={form.handling_class} onChange={(v) => set("handling_class", v)} maxLength={32} hint="e.g. MSL3, ESD, HAZ" />
            </div>
            {form.m2 ? (
              <TextField
                label="External reference"
                value={form.external_ref}
                onChange={(v) => set("external_ref", v)}
                maxLength={64}
                hint="Code of this item in your ERP; must be unique."
                testId="item-external-ref"
              />
            ) : null}
            <TextField label="Handling note" value={form.handling_note} onChange={(v) => set("handling_note", v)} maxLength={500} />
            <AttributesEditor rows={form.attributes} onChange={(rows) => set("attributes", rows)} />
          </div>
        </section>
      ) : null}

      <div className="row mfg-sticky-actions">
        <button type="submit" className="btn primary" disabled={busy || !dirty || !form.part_number.trim() || periodMissing} data-testid="item-save">
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />} Save changes
        </button>
        <button type="button" className="btn" disabled={!dirty || busy} onClick={() => setForm(toForm(base))}>
          Undo changes
        </button>
        <SaveState busy={false} saved={saved && !dirty} />
        <span className="grow" />
        <button type="button" className="btn danger" onClick={() => setConfirmDelete(true)} data-testid="item-delete">
          <Icon name="trash" /> Delete item
        </button>
      </div>

      {confirmDelete ? (
        <ConfirmDialog
          title={`Delete ${base.part_number}?`}
          confirmLabel="Delete item"
          danger
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => void remove()}
        >
          <p style={{ margin: 0 }}>
            Items used in a BOM, or with their own BOM or routing, cannot be deleted; mark them inactive instead.
          </p>
        </ConfirmDialog>
      ) : null}
    </form>
  );
}

function AttributesEditor({ rows, onChange }: { rows: AttrRow[]; onChange(rows: AttrRow[]): void }) {
  const update = (i: number, patch: Partial<AttrRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <fieldset className="mfg-fieldset">
      <legend>Attributes</legend>
      <p className="hint" style={{ margin: 0 }}>
        Free fields such as manufacturer or manufacturer part number. Names use letters, digits and - _ . /
      </p>
      {rows.map((r, i) => (
        <div className="row" key={i}>
          <input className="input sm" aria-label={`Attribute ${i + 1} name`} value={r.key} maxLength={32} onChange={(e) => update(i, { key: e.target.value })} style={{ width: 180 }} />
          <select className="select sm" aria-label={`Attribute ${i + 1} type`} value={r.type} onChange={(e) => update(i, { type: e.target.value as AttrRow["type"] })} style={{ width: 100 }}>
            <option value="text">Text</option>
            <option value="number">Number</option>
            <option value="yes/no">Yes/no</option>
          </select>
          <input className="input sm grow" aria-label={`Attribute ${i + 1} value`} value={r.value} maxLength={500} onChange={(e) => update(i, { value: e.target.value })} />
          <button type="button" className="btn sm ghost icon" aria-label={`Remove attribute ${i + 1}`} onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            <Icon name="trash" />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn sm" onClick={() => onChange([...rows, { key: "", type: "text", value: "" }])}>
          <Icon name="plus" /> Add attribute
        </button>
      </div>
    </fieldset>
  );
}
