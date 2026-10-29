/** Create / edit an item-supplier row (M2 3.3): source terms MRP uses for buy items. */
import { useState } from "react";
import { createItemSupplier, updateItemSupplier } from "../api/clientM2";
import type { ItemRef, Ref } from "../api/types";
import type { ItemSupplierInput, ItemSupplierRecord } from "../api/typesM2";
import { isCountUom } from "../lib/itemCache";
import { EntityFormDialog } from "./EntityFormDialog";
import { CheckField, numOr, numOrNull, numText, strOrNull, TextField } from "./Field";
import { ItemPicker } from "./ItemPicker";
import { SupplierPicker } from "./PickersM2";

export function ItemSupplierDialog({
  row,
  item,
  supplier,
  onClose,
  onSaved,
}: {
  row: ItemSupplierRecord | null;
  /** Fixed item (item page) or fixed supplier (supplier page) for new rows. */
  item?: ItemRef | null;
  supplier?: Ref | null;
  onClose(): void;
  onSaved(r: ItemSupplierRecord): void;
}) {
  const [it, setIt] = useState<ItemRef | null>(row?.item ?? item ?? null);
  const [sup, setSup] = useState<Ref | null>(row?.supplier ?? supplier ?? null);
  const [f, setF] = useState({
    supplier_part_number: row?.supplier_part_number ?? "",
    lead_time_days: numText(row?.lead_time_days),
    min_order_qty: String(row?.min_order_qty ?? 0),
    order_multiple: String(row?.order_multiple ?? 0),
    purchase_unit: row?.purchase_unit ?? "",
    units_per_purchase_unit: String(row?.units_per_purchase_unit ?? 1),
    unit_price: numText(row?.unit_price),
    currency: row?.currency ?? "",
    preferred: row?.preferred ?? false,
    active: row?.active ?? true,
    note: row?.note ?? "",
  });
  const pack = numOr(f.units_per_purchase_unit, 1);
  const packBad = pack <= 0 || (isCountUom(it?.uom) && !Number.isInteger(pack));
  const body: ItemSupplierInput | null =
    it && sup
      ? {
          item_id: it.id,
          supplier_id: sup.id,
          supplier_part_number: f.supplier_part_number.trim(),
          lead_time_days: numOrNull(f.lead_time_days),
          min_order_qty: numOr(f.min_order_qty, 0),
          order_multiple: numOr(f.order_multiple, 0),
          purchase_unit: strOrNull(f.purchase_unit),
          units_per_purchase_unit: pack,
          unit_price: numOrNull(f.unit_price),
          currency: f.currency.trim(),
          preferred: f.preferred,
          active: f.active,
          note: f.note,
        }
      : null;
  return (
    <EntityFormDialog
      title={row ? `${row.item.part_number} from ${row.supplier.code}` : "Add supplier for a part"}
      submitLabel={row ? "Save" : "Add"}
      testId="item-supplier-form"
      wide
      disabled={!body || packBad}
      onClose={onClose}
      onSubmit={async () => {
        if (!body) return;
        onSaved(row ? await updateItemSupplier(row.id, body, row.row_version) : await createItemSupplier(body));
      }}
    >
      <div className="form-grid">
        <ItemPicker label="Part (buy item)" value={it} onChange={setIt} makeBuy="buy" disabled={Boolean(row) || Boolean(item)} testId="item-supplier-item" />
        <SupplierPicker label="Supplier" value={sup} onChange={setSup} disabled={Boolean(row) || Boolean(supplier)} testId="item-supplier-supplier" />
        <TextField label="Supplier part number" value={f.supplier_part_number} onChange={(v) => setF({ ...f, supplier_part_number: v })} maxLength={64} />
        <TextField
          label="Lead time (days)"
          type="number"
          value={f.lead_time_days}
          onChange={(v) => setF({ ...f, lead_time_days: v })}
          hint="Calendar days from order to dock. Empty = the supplier's, else the item's."
          testId="item-supplier-lead"
        />
        <TextField label="Unit price" type="number" value={f.unit_price} onChange={(v) => setF({ ...f, unit_price: v })} hint={`Per ${it?.uom ?? "stock unit"}`} testId="item-supplier-price" />
        <TextField label="Currency" value={f.currency} onChange={(v) => setF({ ...f, currency: v })} maxLength={8} />
        <TextField label="Minimum order quantity" type="number" value={f.min_order_qty} onChange={(v) => setF({ ...f, min_order_qty: v })} hint="0 = the item's value" />
        <TextField label="Order multiple" type="number" value={f.order_multiple} onChange={(v) => setF({ ...f, order_multiple: v })} hint="0 = the item's value" />
        <TextField label="Pack name" value={f.purchase_unit} onChange={(v) => setF({ ...f, purchase_unit: v.toUpperCase() })} maxLength={32} placeholder="e.g. REEL" />
        <TextField
          label="Units per pack"
          type="number"
          value={f.units_per_purchase_unit}
          onChange={(v) => setF({ ...f, units_per_purchase_unit: v })}
          hint={packBad ? "A whole number greater than 0." : "Orders are rounded up to whole packs."}
        />
      </div>
      <CheckField label="Preferred supplier" checked={f.preferred} onChange={(v) => setF({ ...f, preferred: v })} hint="MRP orders from the preferred supplier. Only one per part." testId="item-supplier-preferred" />
      <CheckField label="Active" checked={f.active} onChange={(v) => setF({ ...f, active: v })} />
      <TextField label="Note" value={f.note} onChange={(v) => setF({ ...f, note: v })} maxLength={500} />
    </EntityFormDialog>
  );
}
