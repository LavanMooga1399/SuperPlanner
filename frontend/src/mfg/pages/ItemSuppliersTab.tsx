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
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/VirtualTable";
import { fmtNum } from "../lib/formatM2";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { useItem } from "./ItemShell";
import { t } from "../../lib/i18n";

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
  const columns: Column<ItemSupplierRecord>[] = [
    {
      key: "who",
      header: show === "item" ? "Part" : "Supplier",
      width: "minmax(220px, 2fr)",
      sortValue: (r) => (show === "item" ? r.item.part_number : r.supplier.code),
      exportValue: (r) => (show === "item" ? r.item.part_number : `${r.supplier.code} ${r.supplier.name}`),
      render: (r) => (
        <span className="row" style={{ gap: 6, flexWrap: "nowrap", minWidth: 0 }}>
          {show === "item" ? (
            <Link to={mfgPaths.itemSuppliers(r.item.id)} className="mono">
              {r.item.part_number}
            </Link>
          ) : (
            <Link to={mfgPaths.supplier(r.supplier.id)} className="mfg-ellipsis">
              <span className="mono">{r.supplier.code}</span> {r.supplier.name}
            </Link>
          )}
          {r.preferred ? (
            <span className="badge accent" title="MRP orders from this supplier">
              <Icon name="star" /> {t("mfg.itemSuppliersTab.btn.preferred")}
            </span>
          ) : null}
        </span>
      ),
    },
    { key: "spn", header: "Supplier part no.", width: "minmax(130px, 1fr)", sortValue: (r) => r.supplier_part_number, render: (r) => <span className="mono">{r.supplier_part_number}</span> },
    { key: "lead", header: "Lead time", width: "90px", align: "right", sortValue: (r) => r.lead_time_days, render: (r) => (r.lead_time_days === null ? <span className="faint">default</span> : `${r.lead_time_days} d`) },
    { key: "moq", header: "Min. order", width: "96px", align: "right", sortValue: (r) => r.min_order_qty, render: (r) => (r.min_order_qty ? fmtNum(r.min_order_qty) : <span className="faint">item</span>) },
    { key: "mult", header: "Multiple", width: "88px", align: "right", sortValue: (r) => r.order_multiple, render: (r) => (r.order_multiple ? fmtNum(r.order_multiple) : <span className="faint">item</span>) },
    { key: "pack", header: "Pack", width: "110px", render: (r) => (r.units_per_purchase_unit !== 1 || r.purchase_unit ? `${t("common.nOfM", { n: r.purchase_unit ?? "pack", m: fmtNum(r.units_per_purchase_unit) })}` : "") },
    { key: "price", header: "Unit price", width: "110px", align: "right", sortValue: (r) => r.unit_price, render: (r) => (r.unit_price === null ? "" : `${fmtNum(r.unit_price)} ${r.currency}`) },
    { key: "status", header: "Status", width: "96px", sortValue: (r) => (r.active ? 0 : 1), exportValue: (r) => (r.active ? "Active" : "Inactive"), render: (r) => <ActiveBadge active={r.active} /> },
  ];
  if (onEdit)
    columns.push({
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      label: "Actions",
      width: "100px",
      align: "right",
      exportValue: () => "",
      render: (r) => (
        <span className="row" style={{ gap: 4, justifyContent: "flex-end", flexWrap: "nowrap" }}>
          <button type="button" className="btn sm" onClick={() => onEdit(r)}>
            {t("mfg.itemSuppliersTab.btn.edit")}
          </button>
          {onDelete ? (
            <button type="button" className="btn sm ghost icon" aria-label={t("mfg.itemSuppliersTab.aria.remove")} onClick={() => onDelete(r)}>
              <Icon name="trash" />
            </button>
          ) : null}
        </span>
      ),
    });
  return (
    <DataTable
      rows={rows}
      columns={columns}
      rowKey={(r) => r.id}
      label={show === "item" ? "Parts from this supplier" : "Suppliers of this part"}
      testId="item-supplier-table"
      tableId={`item-supplier-table-${show}`}
      exportName={show === "item" ? "supplier-parts" : "item-suppliers"}
      rowExtras={(r) => ({ testId: "item-supplier-row", data: { preferred: r.preferred }, className: r.id === highlight ? "mfg-highlight" : undefined })}
      empty={t("mfg.itemSuppliersTab.empty.noSuppliersYetWithoutOne")}
      card={{ title: "who", status: "status", fields: ["lead", "moq", "price"] }}
    />
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
            <Icon name="plus" /> {t("mfg.itemSuppliersTab.btn.addSupplier")}
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
          confirmLabel={t("mfg.itemSuppliersTab.btn.remove")}
          danger
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const d = deleting;
            setDeleting(null);
            deleteItemSupplier(d.id, d.row_version).then(rows.reload, setError);
          }}
        >
          <p style={{ margin: 0 }}>{t("mfg.itemSuppliersTab.text.existingPurchaseDocumentsAreNot")}</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
