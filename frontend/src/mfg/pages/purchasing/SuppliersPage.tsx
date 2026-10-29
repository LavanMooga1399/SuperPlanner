/**
 * `/mfg/purchasing/suppliers` and `/mfg/purchasing/suppliers/:supplierId?item_supplier=` (M2 14.2, 3.3):
 * supplier list, supplier details (edit) and the parts it supplies.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Icon } from "../../../components/Icon";
import { createSupplier, deleteItemSupplier, deleteSupplier, getSupplier, listSuppliers, updateSupplier } from "../../api/clientM2";
import type { ItemSupplierRecord, SupplierInput, SupplierRecord } from "../../api/typesM2";
import { EntityFormDialog } from "../../components/EntityFormDialog";
import { MfgError, NotFoundPanel, Spinner } from "../../components/Feedback";
import { CheckField, numOrNull, numText, strOrNull, TextField } from "../../components/Field";
import { ItemSupplierDialog } from "../../components/ItemSupplierDialog";
import { PermissionGate } from "../../components/PermissionGate";
import { ActiveBadge } from "../../components/StatusChip";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { isNotFound, useDebounced, useLoad } from "../../lib/useMfg";
import { ItemSupplierTable } from "../ItemSuppliersTab";

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
      title={sup ? `Supplier ${sup.code}` : "New supplier"}
      submitLabel={sup ? "Save supplier" : "Create supplier"}
      testId="supplier-form"
      wide
      disabled={!body.code || !body.name}
      onClose={onClose}
      onSubmit={async () => onSaved(sup ? await updateSupplier(sup.id, body, sup.row_version) : await createSupplier(body))}
    >
      <div className="form-grid">
        <TextField label="Code" value={f.code} onChange={(v) => setF({ ...f, code: v.toUpperCase() })} required maxLength={32} testId="supplier-code" />
        <TextField label="Name" value={f.name} onChange={(v) => setF({ ...f, name: v })} required testId="supplier-name" />
        <TextField label="Default lead time (days)" type="number" value={f.lead} onChange={(v) => setF({ ...f, lead: v })} hint="Used when a part row has none." />
        <TextField label="Currency" value={f.currency} onChange={(v) => setF({ ...f, currency: v })} maxLength={8} />
        <TextField label="Contact" value={f.contact_name} onChange={(v) => setF({ ...f, contact_name: v })} />
        <TextField label="Email" value={f.email} onChange={(v) => setF({ ...f, email: v })} />
        <TextField label="Phone" value={f.phone} onChange={(v) => setF({ ...f, phone: v })} maxLength={50} />
        <TextField label="External reference" value={f.external_ref} onChange={(v) => setF({ ...f, external_ref: v })} maxLength={64} hint="Vendor code in your ERP" />
      </div>
      <TextField label="Address" value={f.address} onChange={(v) => setF({ ...f, address: v })} maxLength={500} />
      <CheckField label="Active" checked={f.active} onChange={(v) => setF({ ...f, active: v })} hint="Inactive suppliers are not used by MRP." />
      <TextField label="Note" value={f.note} onChange={(v) => setF({ ...f, note: v })} maxLength={500} />
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
      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 260px" }}>
          <label htmlFor="sup-q">Search</label>
          <input id="sup-q" className="input" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Code or name" data-testid="suppliers-search" />
        </div>
        <span className="grow" />
        <PermissionGate perm="supplier_edit">
          <button type="button" className="btn primary" style={{ alignSelf: "flex-end" }} onClick={() => setCreating(true)} data-testid="supplier-new">
            <Icon name="plus" /> New supplier
          </button>
        </PermissionGate>
      </div>
      <MfgError error={list.error} onRetry={list.reload} />
      {list.loading && !list.data ? <Spinner /> : null}
      {list.data ? (
        <div className="table-wrap card">
          <table className="table" data-testid="suppliers-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th className="right">Lead time</th>
                <th className="right">Parts</th>
                <th>Contact</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    No suppliers{dq ? " match" : " yet"}.
                  </td>
                </tr>
              ) : null}
              {list.data.items.slice(0, 500).map((s) => (
                <tr key={s.id} data-testid="supplier-row" data-code={s.code}>
                  <td className="mono">
                    <Link to={mfgPaths.supplier(s.id)}>{s.code}</Link>
                  </td>
                  <td>{s.name}</td>
                  <td className="right">{s.lead_time_days === null ? "" : `${s.lead_time_days} d`}</td>
                  <td className="right">{s.item_count}</td>
                  <td className="small">{[s.contact_name, s.email, s.phone].filter(Boolean).join(" · ")}</td>
                  <td>
                    <ActiveBadge active={s.active} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.data.items.length > 500 ? <div className="card-footer muted small">First 500 of {list.data.items.length}; search to narrow down.</div> : null}
        </div>
      ) : null}
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

  if (sup.error && isNotFound(sup.error)) return <NotFoundPanel what="Supplier" back={<Link className="btn" to={mfgPaths.suppliers()}>Back to suppliers</Link>} />;
  if (sup.error && !s) return <MfgError error={sup.error} onRetry={sup.reload} />;
  if (!s) return <Spinner />;

  return (
    <div className="col gap-lg" data-testid="supplier-page">
      <nav aria-label="Breadcrumb" className="small muted mfg-breadcrumb">
        <Link to={mfgPaths.suppliers()}>Suppliers</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{s.code}</span>
      </nav>
      <section className="card">
        <div className="card-header">
          <h2 className="row">
            <span className="mono">{s.code}</span> {s.name} <ActiveBadge active={s.active} />
          </h2>
          {canEdit ? (
            <div className="mfg-actions">
              <button type="button" className="btn" onClick={() => setEditing(true)} data-testid="supplier-edit">
                Edit
              </button>
              <button type="button" className="btn ghost" onClick={() => setDeleting("supplier")}>
                <Icon name="trash" /> Delete
              </button>
            </div>
          ) : null}
        </div>
        <div className="card-body">
          <dl className="mfg-dl">
            <dt>Default lead time</dt>
            <dd>{s.lead_time_days === null ? "-" : `${s.lead_time_days} days`}</dd>
            <dt>Currency</dt>
            <dd>{s.currency || "-"}</dd>
            <dt>Contact</dt>
            <dd>{[s.contact_name, s.email, s.phone].filter(Boolean).join(" · ") || "-"}</dd>
            {s.address ? (
              <>
                <dt>Address</dt>
                <dd>{s.address}</dd>
              </>
            ) : null}
            {s.external_ref ? (
              <>
                <dt>External reference</dt>
                <dd className="mono">{s.external_ref}</dd>
              </>
            ) : null}
          </dl>
        </div>
      </section>
      <MfgError error={error} />
      <div className="row between">
        <h3 style={{ margin: 0 }}>Parts supplied ({s.items.length})</h3>
        <div className="mfg-actions">
          <Link className="btn sm" to={`${mfgPaths.purchaseDocs("po")}?supplier=${encodeURIComponent(s.id)}`}>
            Purchase orders
          </Link>
          <PermissionGate perm="supplier_edit">
            <button type="button" className="btn sm primary" onClick={() => setRow("new")} data-testid="item-supplier-new">
              <Icon name="plus" /> Add part
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
          title={deleting === "supplier" ? `Delete supplier ${s.code}?` : `Remove ${deleting.item.part_number}?`}
          confirmLabel="Delete"
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
            {deleting === "supplier" ? "A supplier with purchase documents cannot be deleted; make it inactive instead. Its part rows are removed." : "Existing purchase documents are not changed."}
          </p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
