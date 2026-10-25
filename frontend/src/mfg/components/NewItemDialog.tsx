import { useState } from "react";
import { createItem } from "../api/client";
import { UOM_CODES, type ItemRecord, type MakeBuy } from "../api/types";
import { EntityFormDialog } from "./EntityFormDialog";
import { numOrNull, SelectField, strOrNull, TextField } from "./Field";
import { useMeta } from "../lib/useMfg";

export const MAKE_BUY_OPTIONS: { value: MakeBuy; label: string }[] = [
  { value: "make", label: "Make - produced in this plant" },
  { value: "buy", label: "Buy - bought from a supplier" },
  { value: "phantom", label: "Phantom - kit, never stocked (parts used directly)" },
];

export function useUomOptions(): { value: string; label: string }[] {
  const meta = useMeta();
  const codes = meta?.uoms.map((u) => u.code) ?? [...UOM_CODES];
  const dims = new Map(meta?.uoms.map((u) => [u.code, u.dimension]) ?? []);
  return codes.map((c) => ({ value: c, label: dims.get(c) ? `${c} (${dims.get(c)})` : c }));
}

/** Guided "New item": the essentials only; everything else is on the item's Details tab. */
export function NewItemDialog({ onClose, onCreated }: { onClose(): void; onCreated(item: ItemRecord): void }) {
  const [pn, setPn] = useState("");
  const [description, setDescription] = useState("");
  const [makeBuy, setMakeBuy] = useState<MakeBuy>("buy");
  const [uom, setUom] = useState("EA");
  const [revision, setRevision] = useState("A");
  const [family, setFamily] = useState("");
  const [lead, setLead] = useState("");
  const uoms = useUomOptions();
  return (
    <EntityFormDialog
      title="New item"
      submitLabel="Create item"
      onClose={onClose}
      testId="new-item-form"
      disabled={!pn.trim()}
      onSubmit={async () => {
        const item = await createItem({
          part_number: pn.trim(),
          description: description.trim(),
          make_buy: makeBuy,
          uom,
          revision: revision.trim() || "A",
          family: strOrNull(family),
          lead_time_days: makeBuy === "buy" ? numOrNull(lead) : null,
        });
        onCreated(item);
      }}
    >
      <div className="form-grid">
        <TextField label="Part number" value={pn} onChange={setPn} required maxLength={64} testId="new-item-pn" />
        <TextField label="Revision" value={revision} onChange={setRevision} maxLength={16} />
      </div>
      <TextField label="Description" value={description} onChange={setDescription} maxLength={500} testId="new-item-description" />
      <SelectField label="Make or buy" value={makeBuy} onChange={setMakeBuy} options={MAKE_BUY_OPTIONS} testId="new-item-make-buy" />
      <div className="form-grid">
        <SelectField label="Unit" value={uom} onChange={setUom} options={uoms} hint="All quantities of this item use this unit." />
        <TextField label="Family" value={family} onChange={setFamily} maxLength={32} hint="Optional group, e.g. PCBA-HDI. Lines can be limited to families." />
        {makeBuy === "buy" ? (
          <TextField
            label="Supplier lead time (days)"
            type="number"
            value={lead}
            onChange={setLead}
            hint="Needed before planning; 0 if kept in stock locally."
          />
        ) : null}
      </div>
    </EntityFormDialog>
  );
}
