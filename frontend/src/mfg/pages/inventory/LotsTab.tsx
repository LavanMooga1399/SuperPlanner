/**
 * `/mfg/inventory/lots?lot=` (M2 14.2): lots by expiry with hold toggle and an edit dialog (store keeper).
 * `?lot=` (exception links) highlights that lot; further pages are loaded until it is found.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { listLots, updateLot } from "../../api/clientM2";
import type { LotRecord } from "../../api/typesM2";
import { EntityFormDialog } from "../../components/EntityFormDialog";
import { ConflictBanner, MfgError } from "../../components/Feedback";
import { CheckField, TextField } from "../../components/Field";
import { HoldBadge } from "../../components/StatusM2";
import { VirtualTable, type Column } from "../../components/VirtualTable";
import { fmtDate } from "../../lib/format";
import { fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { isConflict, todayInOffset, useDebounced, usePlant } from "../../lib/useMfg";

function LotDialog({ lot, onClose, onSaved }: { lot: LotRecord; onClose(): void; onSaved(l: LotRecord): void }) {
  const [f, setF] = useState({ expires_on: lot.expires_on ?? "", supplier_lot: lot.supplier_lot, hold: lot.hold, note: lot.note });
  const [conflict, setConflict] = useState(false);
  return (
    <EntityFormDialog
      title={`Lot ${lot.lot_code}`}
      submitLabel="Save lot"
      testId="lot-form"
      onClose={onClose}
      onSubmit={async () => {
        try {
          onSaved(await updateLot(lot.id, { expires_on: f.expires_on || null, supplier_lot: f.supplier_lot, hold: f.hold, note: f.note }, lot.row_version));
        } catch (e) {
          if (isConflict(e)) setConflict(true);
          throw e;
        }
      }}
    >
      {conflict ? <ConflictBanner onReload={onClose} what="this lot" /> : null}
      <p className="muted small" style={{ margin: 0 }}>
        <span className="mono">{lot.item.part_number}</span> {lot.item.description} · on hand {fmtNum(lot.on_hand)} {lot.item.uom}
      </p>
      <div className="form-grid">
        <TextField label="Expires on" type="date" value={f.expires_on} onChange={(v) => setF({ ...f, expires_on: v })} testId="lot-expires" />
        <TextField label="Supplier lot" value={f.supplier_lot} onChange={(v) => setF({ ...f, supplier_lot: v })} maxLength={64} />
      </div>
      <CheckField label="On hold" checked={f.hold} onChange={(v) => setF({ ...f, hold: v })} hint="Held stock is not planned and cannot be issued or shipped." testId="lot-hold" />
      <TextField label="Note" value={f.note} onChange={(v) => setF({ ...f, note: v })} maxLength={500} />
    </EntityFormDialog>
  );
}

export function LotsTab() {
  const [params, setParams] = useSearchParams();
  const plant = usePlant();
  const today = todayInOffset(plant.data?.utc_offset);
  const canEdit = useCan("inventory");
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const before = params.get("before") ?? "";
  const hold = params.get("hold") ?? "";
  const lotParam = params.get("lot") ?? "";
  const [editing, setEditing] = useState<LotRecord | null>(null);
  const [toggleError, setToggleError] = useState<unknown>(null);
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = usePaged<LotRecord>(
    (offset, limit, signal) => listLots({ q: dq || undefined, expiring_before: before || undefined, hold: hold === "" ? undefined : hold === "true", limit, offset }, signal),
    [dq, before, hold],
  );
  const found = lotParam ? data.rows.findIndex((l) => l.id === lotParam) : -1;
  // exception link: keep loading pages until the lot is in view (bounded)
  useEffect(() => {
    if (lotParam && found < 0 && !data.loading && data.rows.length < data.total && data.rows.length < 4000) data.onEndReached();
  }, [lotParam, found, data]);
  const scrollTo = useMemo(() => (found >= 0 ? { index: found, seq: found } : null), [found]);

  const replace = (l: LotRecord) => data.setRows((rows) => rows.map((r) => (r.id === l.id ? l : r)));
  const toggleHold = async (l: LotRecord) => {
    setToggleError(null);
    try {
      replace(await updateLot(l.id, { expires_on: l.expires_on, supplier_lot: l.supplier_lot, hold: !l.hold, note: l.note }, l.row_version));
    } catch (e) {
      setToggleError(e);
      if (isConflict(e)) data.reload();
    }
  };

  const columns: Column<LotRecord>[] = [
    { key: "lot", header: "Lot", width: "minmax(130px, 1fr)", render: (l) => <span className="mono mfg-ellipsis">{l.lot_code}</span> },
    {
      key: "pn",
      header: "Part number",
      width: "minmax(150px, 1fr)",
      render: (l) => (
        <Link to={mfgPaths.itemStock(l.item.id)} className="mono mfg-ellipsis" tabIndex={-1}>
          {l.item.part_number}
        </Link>
      ),
    },
    { key: "desc", header: "Description", width: "minmax(160px, 1.5fr)", render: (l) => <span className="mfg-ellipsis">{l.item.description}</span> },
    {
      key: "exp",
      header: "Expires",
      width: "130px",
      render: (l) =>
        l.expires_on ? (
          l.expires_on <= today ? (
            <span className="badge danger">
              <Icon name="x" /> Expired {fmtDate(l.expires_on)}
            </span>
          ) : (
            fmtDate(l.expires_on)
          )
        ) : (
          <span className="faint">No expiry</span>
        ),
    },
    { key: "rcv", header: "Received", width: "100px", render: (l) => fmtDate(l.received_on) },
    { key: "sl", header: "Supplier lot", width: "110px", render: (l) => <span className="mono mfg-ellipsis">{l.supplier_lot}</span> },
    { key: "oh", header: "On hand", width: "90px", align: "right", render: (l) => `${fmtNum(l.on_hand)} ${l.item.uom}` },
    { key: "hold", header: "Status", width: "100px", render: (l) => (l.hold ? <HoldBadge /> : <span className="faint">Usable</span>) },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      label: "Actions",
      width: "170px",
      render: (l) =>
        canEdit ? (
          <span className="row" style={{ gap: 4 }}>
            <button type="button" className="btn sm" onClick={() => void toggleHold(l)} data-testid="lot-hold-toggle" aria-pressed={l.hold}>
              <Icon name={l.hold ? "unlock" : "lock"} /> {l.hold ? "Release" : "Hold"}
            </button>
            <button type="button" className="btn sm ghost" onClick={() => setEditing(l)} aria-label={`Edit lot ${l.lot_code}`}>
              Edit
            </button>
          </span>
        ) : null,
    },
  ];

  return (
    <div className="col gap-lg">
      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 240px" }}>
          <label htmlFor="lots-q">Search</label>
          <input id="lots-q" className="input" type="search" placeholder="Lot code or part number" value={q} onChange={(e) => setQ(e.target.value)} data-testid="lots-search" />
        </div>
        <div className="field">
          <label htmlFor="lots-before">Expiring before</label>
          <input id="lots-before" className="input" type="date" value={before} onChange={(e) => set("before", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="lots-hold">Status</label>
          <select id="lots-hold" className="select" value={hold} onChange={(e) => set("hold", e.target.value)}>
            <option value="">All</option>
            <option value="true">On hold</option>
            <option value="false">Usable</option>
          </select>
        </div>
      </div>
      <MfgError error={data.error ?? toggleError} onRetry={data.reload} />
      <VirtualTable
        rows={data.rows}
        columns={columns}
        rowKey={(l) => l.id}
        label="Lots"
        testId="lots-table"
        totalCount={data.total}
        scrollTo={scrollTo}
        rowExtras={(l) => ({ testId: "lot-row", data: { lot: l.lot_code, hold: l.hold }, className: l.id === lotParam ? "mfg-selected" : undefined })}
        onEndReached={data.onEndReached}
        empty={data.loading ? "Loading lots…" : "No lots. Lots are created by receipts of lot-tracked items."}
        footer={<span className="muted small">Showing {data.rows.length.toLocaleString()} of {data.total.toLocaleString()} lots, earliest expiry first</span>}
      />
      {editing ? (
        <LotDialog
          lot={editing}
          onClose={() => setEditing(null)}
          onSaved={(l) => {
            replace(l);
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}
