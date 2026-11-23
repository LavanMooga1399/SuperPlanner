/**
 * `/mfg/purchasing/suppliers` and `/mfg/purchasing/suppliers/:supplierId?item_supplier=` (M2 14.2, 3.3):
 * supplier list, supplier details (edit) and the parts it supplies.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { ErpOwnedNotice } from "../../components/ErpOwned";
import { Icon } from "../../../components/Icon";
import { createSupplier, deleteItemSupplier, deleteSupplier, getSupplier, listSuppliers, updateSupplier } from "../../api/clientM2";
import type { ItemSupplierRecord, SupplierInput, SupplierRecord } from "../../api/typesM2";
import { EntityFormDialog } from "../../components/EntityFormDialog";
import { MfgError, NotFoundPanel, Spinner } from "../../components/Feedback";
import { CheckField, numOrNull, numText, strOrNull, TextField } from "../../components/Field";
import { ItemSupplierDialog } from "../../components/ItemSupplierDialog";
import { PermissionGate } from "../../components/PermissionGate";
import { ActiveBadge } from "../../components/StatusChip";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { isNotFound, useDebounced, useLoad } from "../../lib/useMfg";
import { ItemSupplierTable } from "../ItemSuppliersTab";
import { plural, t } from "../../../lib/i18n";
import { FilterBar } from "../../../components/FilterBar";

const SUPPLIER_COLS: Column<SupplierRecord>[] = [
  { key: "code", header: t("mfg.suppliersPage.str.code"), width: "140px", sortValue: (s) => s.code, exportValue: (s) => s.code, render: (s) => <Link to={mfgPaths.supplier(s.id)} className="mono">{s.code}</Link> },
  { key: "name", header: t("mfg.suppliersPage.str.name"), width: "minmax(200px, 2fr)", sortValue: (s) => s.name, render: (s) => s.name },
  { key: "lead", header: t("mfg.suppliersPage.str.leadTime"), width: "100px", align: "right", sortValue: (s) => s.lead_time_days, render: (s) => (s.lead_time_days === null ? "" : `${s.lead_time_days} d`) },
  { key: "parts", header: t("mfg.suppliersPage.str.parts"), width: "80px", align: "right", sortValue: (s) => s.item_count, render: (s) => s.item_count },
  { key: "contact", header: t("mfg.suppliersPage.str.contact"), width: "minmax(200px, 2fr)", render: (s) => [s.contact_name, s.email, s.phone].filter(Boolean).join(" · ") },
  { key: "status", header: t("mfg.suppliersPage.str.status"), width: "100px", sortValue: (s) => (s.active ? 0 : 1), exportValue: (s) => (s.active ? t("mfg.suppliersPage.str.active") : t("mfg.suppliersPage.str.inactive")), render: (s) => <ActiveBadge active={s.active} /> },
];

function SupplierDialog({ sup, onClose, onSaved }: { sup: SupplierRecord | null; onClose(): void; onSaved(s: SupplierRecord): void }) {
  const [f, setF] = useState({
    code: sup?.code ?? "",
    name: sup?.name ?? "",
    lead: numText(sup?.lead_time_days),
    currency: sup?.currency ?? "",
    contact_name: sup?.contact_name ?? "",
    email: sup?.email ?? "",
    phone: sup?.phone ?? "",
    address: sup?.address ?? "",
    active: sup?.active ?? true,
    external_ref: sup?.external_ref ?? "",
    note: sup?.note ?? "",
  });
  const body: SupplierInput = {
    code: f.code.trim(),
    name: f.name.trim(),
    lead_time_days: numOrNull(f.lead),
    currency: f.currency.trim(),
    contact_name: f.contact_name,
    email: f.email.trim(),
    phone: f.phone,
    address: f.address,
    active: f.active,
    external_ref: strOrNull(f.external_ref),
    note: f.note,
  };
  return (
    <EntityFormDialog
      title={sup ? t("mfg.suppliersPage.tpl.supplier", { code: sup.code }) : t("mfg.suppliersPage.str.newSupplier")}
      submitLabel={sup ? t("mfg.suppliersPage.str.saveSupplier") : t("mfg.suppliersPage.str.createSupplier")}
      testId="supplier-form"
      wide
      disabled={!body.code || !body.name}
      onClose={onClose}
      onSubmit={async () => onSaved(sup ? await updateSupplier(sup.id, body, sup.row_version) : await createSupplier(body))}
    >
      <div className="form-grid">
        <TextField label={t("mfg.suppliersPage.label.code")} value={f.code} onChange={(v) => setF({ ...f, code: v.toUpperCase() })} required maxLength={32} testId="supplier-code" />
        <TextField label={t("mfg.suppliersPage.label.name")} value={f.name} onChange={(v) => setF({ ...f, name: v })} required testId="supplier-name" />
        <TextField label={t("mfg.suppliersPage.label.defaultLeadTimeDays")} type="number" value={f.lead} onChange={(v) => setF({ ...f, lead: v })} hint={t("mfg.suppliersPage.hint.usedWhenAPartRow")} />
        <TextField label={t("mfg.suppliersPage.label.currency")} value={f.currency} onChange={(v) => setF({ ...f, currency: v })} maxLength={8} />
        <TextField label={t("mfg.suppliersPage.label.contact")} value={f.contact_name} onChange={(v) => setF({ ...f, contact_name: v })} />
        <TextField label={t("mfg.suppliersPage.label.email")} value={f.email} onChange={(v) => setF({ ...f, email: v })} />
        <TextField label={t("mfg.suppliersPage.label.phone")} value={f.phone} onChange={(v) => setF({ ...f, phone: v })} maxLength={50} />
        <TextField label={t("mfg.suppliersPage.label.externalReference")} value={f.external_ref} onChange={(v) => setF({ ...f, external_ref: v })} maxLength={64} hint={t("mfg.suppliersPage.hint.vendorCodeInYourErp")} />
      </div>
      <TextField label={t("mfg.suppliersPage.label.address")} value={f.address} onChange={(v) => setF({ ...f, address: v })} maxLength={500} />
      <CheckField label={t("mfg.suppliersPage.label.active")} checked={f.active} onChange={(v) => setF({ ...f, active: v })} hint={t("mfg.suppliersPage.hint.inactiveSuppliersAreNotUsed")} />
      <TextField label={t("mfg.suppliersPage.label.note")} value={f.note} onChange={(v) => setF({ ...f, note: v })} maxLength={500} />
    </EntityFormDialog>
  );
}

export function SuppliersPage() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim(), 250);
  const list = useLoad((signal) => listSuppliers({ q: dq || undefined }, signal), [dq]);
  const [creating, setCreating] = useState(false);
  return (
    <div className="col gap-lg">
      <FilterBar search={{ id: "sup-q", value: q, onChange: setQ, placeholder: "Code or name", testId: "suppliers-search" }} pageKey="SuppliersPage">
        <span className="grow" />
        <PermissionGate perm="supplier_edit">
          <button type="button" className="btn primary" style={{ alignSelf: "flex-end" }} onClick={() => setCreating(true)} data-testid="supplier-new">
            <Icon name="plus" /> {t("mfg.suppliersPage.btn.newSupplier")}
          </button>
        </PermissionGate>
      </FilterBar>
      <MfgError error={list.error} onRetry={list.reload} />
      <VirtualTable
        rows={list.data?.items ?? []}
        columns={SUPPLIER_COLS}
        rowKey={(s) => s.id}
        label={t("mfg.suppliersPage.label.suppliers")}
        testId="suppliers-table"
        loading={list.loading && !list.data}
        exportName="suppliers"
        rowExtras={(s) => ({ testId: "supplier-row", data: { code: s.code } })}
        onActivate={(s) => navigate(mfgPaths.supplier(s.id))}
        empty={dq ? t("mfg.suppliersPage.str.noSuppliersMatchTheSearch") : t("mfg.suppliersPage.str.noSuppliersYetAddOne")}
        card={{ title: "code", status: "status", fields: ["name", "lead", "parts"] }}
      />
      {creating ? <SupplierDialog sup={null} onClose={() => setCreating(false)} onSaved={(s) => navigate(mfgPaths.supplier(s.id))} /> : null}
    </div>
  );
}

export function SupplierPage() {
  const { supplierId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const highlight = params.get("item_supplier");
  const sup = useLoad((signal) => getSupplier(supplierId, signal), [supplierId]);
  const canEdit = useCan("supplier_edit");
  const [editing, setEditing] = useState(false);
  const [row, setRow] = useState<ItemSupplierRecord | "new" | null>(null);
  const [deleting, setDeleting] = useState<ItemSupplierRecord | "supplier" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const s = sup.data;
  const supRef = useMemo(() => (s ? { id: s.id, code: s.code, name: s.name } : null), [s]);

  useEffect(() => {
    if (highlight && s) document.querySelector(".mfg-highlight")?.scrollIntoView({ block: "center" });
  }, [highlight, s]);

  if (sup.error && isNotFound(sup.error)) return <NotFoundPanel what={t("mfg.suppliersPage.attr.supplier")} back={<Link className="btn" to={mfgPaths.suppliers()}>{t("mfg.suppliersPage.text.backToSuppliers")}</Link>} />;
  if (sup.error && !s) return <MfgError error={sup.error} onRetry={sup.reload} />;
  if (!s) return <Spinner />;

  return (
    <div className="col gap-lg" data-testid="supplier-page">
      <nav aria-label={t("mfg.suppliersPage.aria.breadcrumb")} className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.suppliers()}>{t("mfg.suppliersPage.text.suppliers")}</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{s.code}</span>
      </nav>
      <ErpOwnedNotice entity="suppliers" label={t("mfg.suppliersPage.label.suppliersExceptThePreferredFlag")} />
      <section className="card">
        <div className="card-header">
          <h2 className="row">
            <span className="mono">{s.code}</span> {s.name} <ActiveBadge active={s.active} />
          </h2>
          {canEdit ? (
            <div className="mfg-actions">
              <button type="button" className="btn" onClick={() => setEditing(true)} data-testid="supplier-edit">
                {t("mfg.suppliersPage.btn.edit")}
              </button>
              <button type="button" className="btn ghost" onClick={() => setDeleting("supplier")}>
                <Icon name="trash" /> {t("mfg.suppliersPage.btn.delete")}
              </button>
            </div>
          ) : null}
        </div>
        <div className="card-body">
          <dl className="mfg-dl">
            <dt>{t("mfg.suppliersPage.head.defaultLeadTime")}</dt>
            <dd>{s.lead_time_days === null ? "-" : plural(s.lead_time_days, "day")}</dd>
            <dt>{t("mfg.suppliersPage.head.currency")}</dt>
            <dd>{s.currency || "-"}</dd>
            <dt>{t("mfg.suppliersPage.head.contact")}</dt>
            <dd>{[s.contact_name, s.email, s.phone].filter(Boolean).join(" · ") || "-"}</dd>
            {s.address ? (
              <>
                <dt>{t("mfg.suppliersPage.head.address")}</dt>
                <dd>{s.address}</dd>
              </>
            ) : null}
            {s.external_ref ? (
              <>
                <dt>{t("mfg.suppliersPage.head.externalReference")}</dt>
                <dd className="mono">{s.external_ref}</dd>
              </>
            ) : null}
          </dl>
        </div>
      </section>
      <MfgError error={error} />
      <div className="row between">
        <h3 style={{ margin: 0 }}>{t("mfg.suppliersPage.text.partsSupplied", { length: s.items.length })}</h3>
        <div className="mfg-actions">
          <Link className="btn sm" to={`${mfgPaths.purchaseDocs("po")}?supplier=${encodeURIComponent(s.id)}`}>
            {t("mfg.suppliersPage.btn.purchaseOrders")}
          </Link>
          <PermissionGate perm="supplier_edit">
            <button type="button" className="btn sm primary" onClick={() => setRow("new")} data-testid="item-supplier-new">
              <Icon name="plus" /> {t("mfg.suppliersPage.btn.addPart")}
            </button>
          </PermissionGate>
        </div>
      </div>
      <ItemSupplierTable rows={s.items} show="item" highlight={highlight} onEdit={canEdit ? setRow : undefined} onDelete={canEdit ? (r) => setDeleting(r) : undefined} />
      {editing ? (
        <SupplierDialog
          sup={s}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            sup.reload();
          }}
        />
      ) : null}
      {row ? (
        <ItemSupplierDialog
          row={row === "new" ? null : row}
          supplier={supRef}
          onClose={() => setRow(null)}
          onSaved={() => {
            setRow(null);
            sup.reload();
          }}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title={deleting === "supplier" ? t("mfg.suppliersPage.tpl.deleteSupplier", { code: s.code }) : t("mfg.suppliersPage.tpl.remove", { partnumber: deleting.item.part_number })}
          confirmLabel={t("mfg.suppliersPage.btn.delete")}
          danger
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const d = deleting;
            setDeleting(null);
            setError(null);
            if (d === "supplier") deleteSupplier(s.id, s.row_version).then(() => navigate(mfgPaths.suppliers()), setError);
            else deleteItemSupplier(d.id, d.row_version).then(sup.reload, setError);
          }}
        >
          <p style={{ margin: 0 }}>
            {deleting === "supplier" ? t("mfg.suppliersPage.str.aSupplierWithPurchaseDocuments") : t("mfg.suppliersPage.str.existingPurchaseDocumentsAreNot")}
          </p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
