/** `/mfg/inventory/locations?location=` (M2 14.2, 3.2): stores locations, CRUD for planners (master data). */
import { useState } from "react";
import { useSearchParams } from "react-router";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Icon } from "../../../components/Icon";
import { createLocation, deleteLocation, listLocations, updateLocation } from "../../api/clientM2";
import { LOCATION_KINDS, type LocationInput, type LocationKind, type LocationRecord } from "../../api/typesM2";
import { EntityFormDialog } from "../../components/EntityFormDialog";
import { MfgError } from "../../components/Feedback";
import { DataTable } from "../../components/DataTable";
import type { Column } from "../../components/VirtualTable";
import { CheckField, SelectField, strOrNull, TextField } from "../../components/Field";
import { PermissionGate } from "../../components/PermissionGate";
import { invalidateLocations } from "../../components/PickersM2";
import { ActiveBadge } from "../../components/StatusChip";
import { LOCATION_KIND_LABEL, LocationKindBadge } from "../../components/StatusM2";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { useLoad } from "../../lib/useMfg";
import { Link } from "react-router";
import { t } from "../../../lib/i18n";

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
        <TextField label={t("mfg.locationsTab.label.code")} value={f.code} onChange={(v) => setF({ ...f, code: v.toUpperCase() })} required maxLength={32} testId="location-code" />
        <TextField label={t("mfg.locationsTab.label.name")} value={f.name} onChange={(v) => setF({ ...f, name: v })} required testId="location-name" />
        <SelectField
          label={t("mfg.locationsTab.label.kind")}
          value={f.kind}
          onChange={(v) => setF({ ...f, kind: v })}
          options={LOCATION_KINDS.map((k) => ({ value: k, label: LOCATION_KIND_LABEL[k] }))}
          hint={KIND_HELP[f.kind]}
          testId="location-kind"
        />
      </div>
      <CheckField
        label={t("mfg.locationsTab.label.defaultLocationForGoodsReceipts")}
        checked={f.receipt_default}
        onChange={(v) => setF({ ...f, receipt_default: v })}
        hint={t("mfg.locationsTab.hint.receiptsWithoutALocationGo")}
        testId="location-receipt-default"
      />
      <CheckField label={t("mfg.locationsTab.label.active")} checked={f.active} onChange={(v) => setF({ ...f, active: v })} hint={t("mfg.locationsTab.hint.nothingCanBePostedInto")} />
      <div className="form-grid">
        <TextField label={t("mfg.locationsTab.label.externalReference")} value={f.external_ref} onChange={(v) => setF({ ...f, external_ref: v })} maxLength={64} hint={t("mfg.locationsTab.hint.codeInYourErp")} />
        <TextField label={t("mfg.locationsTab.label.note")} value={f.note} onChange={(v) => setF({ ...f, note: v })} maxLength={500} />
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

  const columns: Column<LocationRecord>[] = [
    { key: "code", header: "Code", width: "130px", sortValue: (l) => l.code, exportValue: (l) => l.code, render: (l) => <Link to={mfgPaths.inventory({ location: l.id })} className="mono">{l.code}</Link> },
    { key: "name", header: "Name", width: "minmax(200px, 2fr)", sortValue: (l) => l.name, render: (l) => l.name },
    { key: "kind", header: "Kind", width: "140px", sortValue: (l) => l.kind, exportValue: (l) => LOCATION_KIND_LABEL[l.kind] ?? l.kind, render: (l) => <LocationKindBadge kind={l.kind} /> },
    {
      key: "receipts",
      header: "Receipts",
      width: "110px",
      sortValue: (l) => (l.receipt_default ? 0 : 1),
      exportValue: (l) => (l.receipt_default ? "Default" : ""),
      render: (l) =>
        l.receipt_default ? (
          <span className="badge accent">
            <Icon name="download" /> {t("mfg.locationsTab.btn.default")}
          </span>
        ) : null,
    },
    { key: "status", header: "Status", width: "100px", sortValue: (l) => (l.active ? 0 : 1), exportValue: (l) => (l.active ? "Active" : "Inactive"), render: (l) => <ActiveBadge active={l.active} /> },
  ];
  if (canEdit)
    columns.push({
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      label: "Actions",
      width: "96px",
      align: "right",
      exportValue: () => "",
      render: (l) => (
        <span className="row" style={{ gap: 4, justifyContent: "flex-end", flexWrap: "nowrap" }}>
          <button type="button" className="btn sm" onClick={() => setEditing(l)} aria-label={`Edit location ${l.code}`}>
            {t("mfg.locationsTab.btn.edit")}
          </button>
          <button type="button" className="btn sm ghost icon" onClick={() => setDeleting(l)} aria-label={`Delete location ${l.code}`}>
            <Icon name="trash" />
          </button>
        </span>
      ),
    });

  return (
    <div className="col gap-lg">
      <div className="row between">
        <p className="muted small" style={{ margin: 0 }}>
          Stores and line-side stock is planned and kitted; goods-in stock is planned after inspection; quarantine is never used.
        </p>
        <PermissionGate perm="master_edit">
          <button type="button" className="btn primary" onClick={() => setEditing("new")} data-testid="location-new">
            <Icon name="plus" /> {t("mfg.locationsTab.btn.newLocation")}
          </button>
        </PermissionGate>
      </div>
      <MfgError error={list.error ?? error} onRetry={list.reload} title={error ? "The location could not be deleted" : undefined} />
      <DataTable
        rows={list.data?.items ?? []}
        columns={columns}
        rowKey={(l) => l.id}
        label={t("mfg.locationsTab.label.locations")}
        testId="locations-table"
        loading={list.loading && !list.data}
        exportName="locations"
        rowExtras={(l) => ({ testId: "location-row", data: { code: l.code }, className: l.id === selected ? "mfg-highlight" : undefined })}
        empty={t("mfg.locationsTab.empty.noLocationsYetAddAt")}
        card={{ title: "code", status: "status", actions: canEdit ? "actions" : undefined, fields: ["name", "kind", "receipts"] }}
      />
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
        <ConfirmDialog title={`Delete ${deleting.code}?`} confirmLabel={t("mfg.locationsTab.btn.deleteLocation")} danger onCancel={() => setDeleting(null)} onConfirm={() => void remove(deleting)}>
          <p style={{ margin: 0 }}>{t("mfg.locationsTab.text.aLocationThatHasStock")}</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
