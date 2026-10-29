/** `/mfg/items/:itemId/suppliers` (M2 14.2): who supplies this part, on which terms; preferred first. */
import { useState } from "react";
import { Link } from "react-router";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { deleteItemSupplier, listItemSuppliers } from "../api/clientM2";
import type { ItemRef } from "../api/types";
import type { ItemSupplierRecord } from "../api/typesM2";
import { MfgError, Spinner } from "../components/Feedback";
import { ItemSupplierDialog } from "../components/ItemSupplierDialog";
import { PermissionGate } from "../components/PermissionGate";
import { ActiveBadge } from "../components/StatusChip";
import { fmtNum } from "../lib/formatM2";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { useItem } from "./ItemShell";

export function ItemSupplierTable({
  rows,
  show,
  onEdit,
  onDelete,
  highlight,
}: {
  rows: ItemSupplierRecord[];
  show: "item" | "supplier";
  onEdit?(r: ItemSupplierRecord): void;
  onDelete?(r: ItemSupplierRecord): void;
  highlight?: string | null;
}) {
  return (
    <div className="table-wrap card">
      <table className="table" data-testid="item-supplier-table">
        <thead>
          <tr>
            <th>{show === "item" ? "Part" : "Supplier"}</th>
            <th>Supplier part no.</th>
            <th className="right">Lead time</th>
            <th className="right">Min. order</th>
            <th className="right">Multiple</th>
            <th>Pack</th>
            <th className="right">Unit price</th>
            <th>Status</th>
            <th>
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={9} className="muted">
                No suppliers yet. Without one, MRP uses the item's lead time and creates purchase requests without a supplier.
              </td>
            </tr>
          ) : null}
          {rows.map((r) => (
            <tr key={r.id} data-testid="item-supplier-row" data-preferred={r.preferred} className={r.id === highlight ? "mfg-highlight" : undefined}>
              <td>
                {show === "item" ? (
                  <Link to={mfgPaths.itemSuppliers(r.item.id)} className="mono">
                    {r.item.part_number}
                  </Link>
                ) : (
                  <Link to={mfgPaths.supplier(r.supplier.id)}>
                    <span className="mono">{r.supplier.code}</span> {r.supplier.name}
                  </Link>
                )}{" "}
                {r.preferred ? (
                  <span className="badge accent" title="MRP orders from this supplier">
                    <Icon name="star" /> Preferred
                  </span>
                ) : null}
              </td>
              <td className="mono">{r.supplier_part_number}</td>
              <td className="right">{r.lead_time_days === null ? <span className="faint">default</span> : `${r.lead_time_days} d`}</td>
              <td className="right">{r.min_order_qty ? fmtNum(r.min_order_qty) : <span className="faint">item</span>}</td>
              <td className="right">{r.order_multiple ? fmtNum(r.order_multiple) : <span className="faint">item</span>}</td>
              <td>{r.units_per_purchase_unit !== 1 || r.purchase_unit ? `${r.purchase_unit ?? "pack"} of ${fmtNum(r.units_per_purchase_unit)}` : ""}</td>
              <td className="right">{r.unit_price === null ? "" : `${fmtNum(r.unit_price)} ${r.currency}`}</td>
              <td>
                <ActiveBadge active={r.active} />
              </td>
              <td className="right">
                {onEdit ? (
                  <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
                    <button type="button" className="btn sm" onClick={() => onEdit(r)}>
                      Edit
                    </button>
                    {onDelete ? (
                      <button type="button" className="btn sm ghost icon" aria-label="Remove" onClick={() => onDelete(r)}>
                        <Icon name="trash" />
                      </button>
                    ) : null}
                  </span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ItemSuppliersTab() {
  const { item } = useItem();
  const rows = useLoad((signal) => listItemSuppliers({ item_id: item.id }, signal), [item.id]);
  const canEdit = useCan("supplier_edit");
  const [editing, setEditing] = useState<ItemSupplierRecord | "new" | null>(null);
  const [deleting, setDeleting] = useState<ItemSupplierRecord | null>(null);
  const [error, setError] = useState<unknown>(null);
  const ref: ItemRef = { id: item.id, part_number: item.part_number, revision: item.revision, description: item.description, uom: item.uom, make_buy: item.make_buy, active: item.active };

  if (item.make_buy !== "buy")
    return <p className="muted">Suppliers apply to bought parts. This item is {item.make_buy === "make" ? "made in the plant" : "a phantom"}.</p>;

  return (
    <div className="col gap-lg">
      <div className="row between">
        <p className="muted small" style={{ margin: 0 }}>
          MRP orders from the preferred active supplier; without one, from the active supplier with the shortest lead time.
        </p>
        <PermissionGate perm="supplier_edit">
          <button type="button" className="btn primary" onClick={() => setEditing("new")} data-testid="item-supplier-new">
            <Icon name="plus" /> Add supplier
          </button>
        </PermissionGate>
      </div>
      <MfgError error={rows.error ?? error} onRetry={rows.reload} />
      {rows.loading && !rows.data ? <Spinner /> : null}
      {rows.data ? <ItemSupplierTable rows={rows.data.items} show="supplier" onEdit={canEdit ? setEditing : undefined} onDelete={canEdit ? setDeleting : undefined} /> : null}
      {editing ? (
        <ItemSupplierDialog
          row={editing === "new" ? null : editing}
          item={ref}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            rows.reload();
          }}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title={`Remove ${deleting.supplier.code} for this part?`}
          confirmLabel="Remove"
          danger
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const d = deleting;
            setDeleting(null);
            deleteItemSupplier(d.id, d.row_version).then(rows.reload, setError);
          }}
        >
          <p style={{ margin: 0 }}>Existing purchase documents are not changed.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
