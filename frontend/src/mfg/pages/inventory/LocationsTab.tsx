/** `/mfg/inventory/locations?location=` (M2 14.2, 3.2): stores locations, CRUD for planners (master data). */
import { useState } from "react";
import { useSearchParams } from "react-router";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Icon } from "../../../components/Icon";
import { createLocation, deleteLocation, listLocations, updateLocation } from "../../api/clientM2";
import { LOCATION_KINDS, type LocationInput, type LocationKind, type LocationRecord } from "../../api/typesM2";
import { EntityFormDialog } from "../../components/EntityFormDialog";
import { MfgError, Spinner } from "../../components/Feedback";
import { CheckField, SelectField, strOrNull, TextField } from "../../components/Field";
import { PermissionGate } from "../../components/PermissionGate";
import { invalidateLocations } from "../../components/PickersM2";
import { ActiveBadge } from "../../components/StatusChip";
import { LOCATION_KIND_LABEL, LocationKindBadge } from "../../components/StatusM2";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { useLoad } from "../../lib/useMfg";
import { Link } from "react-router";

const KIND_HELP: Record<LocationKind, string> = {
  stores: "Usable stock: counted by MRP and kitting.",
  line_side: "Stock at the line: counted by MRP and kitting.",
  inspection: "Goods-in: counted by MRP after the item's inspection days; not kitted.",
  quarantine: "Blocked stock: never planned or kitted.",
};

function LocationDialog({ loc, onClose, onSaved }: { loc: LocationRecord | null; onClose(): void; onSaved(): void }) {
  const [f, setF] = useState({
    code: loc?.code ?? "",
    name: loc?.name ?? "",
    kind: (loc?.kind ?? "stores") as LocationKind,
    receipt_default: loc?.receipt_default ?? false,
    active: loc?.active ?? true,
    external_ref: loc?.external_ref ?? "",
    note: loc?.note ?? "",
  });
  const body: LocationInput = { ...f, code: f.code.trim(), name: f.name.trim(), external_ref: strOrNull(f.external_ref) };
  return (
    <EntityFormDialog
      title={loc ? `Location ${loc.code}` : "New location"}
      submitLabel={loc ? "Save location" : "Create location"}
      testId="location-form"
      disabled={!body.code || !body.name}
      onClose={onClose}
      onSubmit={async () => {
        if (loc) await updateLocation(loc.id, body, loc.row_version);
        else await createLocation(body);
        invalidateLocations();
        onSaved();
      }}
    >
      <div className="form-grid">
        <TextField label="Code" value={f.code} onChange={(v) => setF({ ...f, code: v.toUpperCase() })} required maxLength={32} testId="location-code" />
        <TextField label="Name" value={f.name} onChange={(v) => setF({ ...f, name: v })} required testId="location-name" />
        <SelectField
          label="Kind"
          value={f.kind}
          onChange={(v) => setF({ ...f, kind: v })}
          options={LOCATION_KINDS.map((k) => ({ value: k, label: LOCATION_KIND_LABEL[k] }))}
          hint={KIND_HELP[f.kind]}
          testId="location-kind"
        />
      </div>
      <CheckField
        label="Default location for goods receipts"
        checked={f.receipt_default}
        onChange={(v) => setF({ ...f, receipt_default: v })}
        hint="Receipts without a location go here. Only one location can be the default."
        testId="location-receipt-default"
      />
      <CheckField label="Active" checked={f.active} onChange={(v) => setF({ ...f, active: v })} hint="Nothing can be posted into an inactive location." />
      <div className="form-grid">
        <TextField label="External reference" value={f.external_ref} onChange={(v) => setF({ ...f, external_ref: v })} maxLength={64} hint="Code in your ERP" />
        <TextField label="Note" value={f.note} onChange={(v) => setF({ ...f, note: v })} maxLength={500} />
      </div>
    </EntityFormDialog>
  );
}

export function LocationsTab() {
  const [params] = useSearchParams();
  const selected = params.get("location");
  const list = useLoad((signal) => listLocations({}, signal), []);
  const canEdit = useCan("master_edit");
  const [editing, setEditing] = useState<LocationRecord | "new" | null>(null);
  const [deleting, setDeleting] = useState<LocationRecord | null>(null);
  const [error, setError] = useState<unknown>(null);

  const remove = async (l: LocationRecord) => {
    setError(null);
    try {
      await deleteLocation(l.id, l.row_version);
      invalidateLocations();
      list.reload();
    } catch (e) {
      setError(e);
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="col gap-lg">
      <div className="row between">
        <p className="muted small" style={{ margin: 0 }}>
          Stores and line-side stock is planned and kitted; goods-in stock is planned after inspection; quarantine is never used.
        </p>
        <PermissionGate perm="master_edit">
          <button type="button" className="btn primary" onClick={() => setEditing("new")} data-testid="location-new">
            <Icon name="plus" /> New location
          </button>
        </PermissionGate>
      </div>
      <MfgError error={list.error ?? error} onRetry={list.reload} title={error ? "The location could not be deleted" : undefined} />
      {list.loading && !list.data ? <Spinner /> : null}
      {list.data ? (
        <div className="table-wrap card">
          <table className="table" data-testid="locations-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Kind</th>
                <th>Receipts</th>
                <th>Status</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    No locations yet. Add at least one stores location before posting stock.
                  </td>
                </tr>
              ) : null}
              {list.data.items.map((l) => (
                <tr key={l.id} data-testid="location-row" data-code={l.code} className={l.id === selected ? "mfg-highlight" : undefined}>
                  <td className="mono">
                    <Link to={mfgPaths.inventory({ location: l.id })}>{l.code}</Link>
                  </td>
                  <td>{l.name}</td>
                  <td>
                    <LocationKindBadge kind={l.kind} />
                  </td>
                  <td>
                    {l.receipt_default ? (
                      <span className="badge accent">
                        <Icon name="download" /> Default
                      </span>
                    ) : null}
                  </td>
                  <td>
                    <ActiveBadge active={l.active} />
                  </td>
                  <td className="right">
                    {canEdit ? (
                      <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
                        <button type="button" className="btn sm" onClick={() => setEditing(l)} aria-label={`Edit location ${l.code}`}>
                          Edit
                        </button>
                        <button type="button" className="btn sm ghost icon" onClick={() => setDeleting(l)} aria-label={`Delete location ${l.code}`}>
                          <Icon name="trash" />
                        </button>
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {editing ? (
        <LocationDialog
          loc={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            list.reload();
          }}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog title={`Delete ${deleting.code}?`} confirmLabel="Delete location" danger onCancel={() => setDeleting(null)} onConfirm={() => void remove(deleting)}>
          <p style={{ margin: 0 }}>A location that has stock or ledger history cannot be deleted; make it inactive instead.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
