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
import { FilterBar, type FilterChip } from "../../../components/FilterBar";
import { DateInput } from "../../../components/DateInput";
import { t } from "../../../lib/i18n";
import { LOCALE } from "../../../lib/locale";

function LotDialog({ lot, onClose, onSaved }: { lot: LotRecord; onClose(): void; onSaved(l: LotRecord): void }) {
  const [f, setF] = useState({ expires_on: lot.expires_on ?? "", supplier_lot: lot.supplier_lot, hold: lot.hold, note: lot.note });
  const [conflict, setConflict] = useState(false);
  return (
    <EntityFormDialog
      title={t("mfg.lotsTab.tpl.lot", { lotcode: lot.lot_code })}
      submitLabel={t("mfg.lotsTab.btn.saveLot")}
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
      {conflict ? <ConflictBanner onReload={onClose} what={t("mfg.lotsTab.attr.thisLot")} /> : null}
      <p className="muted small" style={{ margin: 0 }}>
        <span className="mono">{lot.item.part_number}</span>{" "}{t("mfg.lotsTab.text.onHand", { description: lot.item.description, onhand: fmtNum(lot.on_hand), uom: lot.item.uom })}
      </p>
      <div className="form-grid">
        <TextField label={t("mfg.lotsTab.label.expiresOn")} type="date" value={f.expires_on} onChange={(v) => setF({ ...f, expires_on: v })} testId="lot-expires" />
        <TextField label={t("mfg.lotsTab.label.supplierLot")} value={f.supplier_lot} onChange={(v) => setF({ ...f, supplier_lot: v })} maxLength={64} />
      </div>
      <CheckField label={t("mfg.lotsTab.label.onHold")} checked={f.hold} onChange={(v) => setF({ ...f, hold: v })} hint={t("mfg.lotsTab.hint.heldStockIsNotPlanned")} testId="lot-hold" />
      <TextField label={t("mfg.lotsTab.label.note")} value={f.note} onChange={(v) => setF({ ...f, note: v })} maxLength={500} />
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
  const sort = params.get("sort") ?? "expires_on";
  const [editing, setEditing] = useState<LotRecord | null>(null);
  const [toggleError, setToggleError] = useState<unknown>(null);
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  useEffect(() => set("q", dq), [dq]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = usePaged<LotRecord>(
    (offset, limit, signal) => listLots({ q: dq || undefined, expiring_before: before || undefined, hold: hold === "" ? undefined : hold === "true", sort: sort === "expires_on" ? undefined : sort, limit, offset }, signal),
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
    { key: "lot", header: t("mfg.lotsTab.str.lot"), width: "minmax(130px, 1fr)", sortKey: "lot_code", sortKeyDesc: "-lot_code", render: (l) => <span className="mono mfg-ellipsis">{l.lot_code}</span> },
    {
      key: "pn",
      header: t("mfg.lotsTab.str.partNumber"),
      width: "minmax(150px, 1fr)",
      sortKey: "part_number",
      render: (l) => (
        <Link to={mfgPaths.itemStock(l.item.id)} className="mono mfg-ellipsis" tabIndex={-1}>
          {l.item.part_number}
        </Link>
      ),
    },
    { key: "desc", header: t("mfg.lotsTab.str.description"), width: "minmax(160px, 1.5fr)", render: (l) => <span className="mfg-ellipsis">{l.item.description}</span> },
    {
      key: "exp",
      header: t("mfg.lotsTab.str.expires"),
      width: "130px",
      sortKey: "expires_on",
      sortKeyDesc: "-expires_on",
      render: (l) =>
        l.expires_on ? (
          l.expires_on <= today ? (
            <span className="badge danger">
              <Icon name="x" />{" "}{t("mfg.lotsTab.text.expired", { expireson: fmtDate(l.expires_on) })}
            </span>
          ) : (
            fmtDate(l.expires_on)
          )
        ) : (
          <span className="faint">{t("mfg.lotsTab.text.noExpiry")}</span>
        ),
    },
    { key: "rcv", header: t("mfg.lotsTab.str.received"), width: "110px", sortKey: "received_on", sortKeyDesc: "-received_on", render: (l) => fmtDate(l.received_on) },
    { key: "sl", header: t("mfg.lotsTab.str.supplierLot"), width: "110px", render: (l) => <span className="mono mfg-ellipsis">{l.supplier_lot}</span> },
    { key: "oh", header: t("mfg.lotsTab.str.onHand"), width: "90px", align: "right", render: (l) => `${fmtNum(l.on_hand)} ${l.item.uom}` },
    { key: "hold", header: t("mfg.lotsTab.str.status"), width: "100px", render: (l) => (l.hold ? <HoldBadge /> : <span className="faint">{t("mfg.lotsTab.text.usable")}</span>) },
    {
      key: "act",
      header: <span className="sr-only">{t("mfg.lotsTab.text.actions")}</span>,
      label: t("mfg.lotsTab.str.actions"),
      width: "170px",
      render: (l) =>
        canEdit ? (
          <span className="row" style={{ gap: 4 }}>
            <button type="button" className="btn sm" onClick={() => void toggleHold(l)} data-testid="lot-hold-toggle" aria-pressed={l.hold}>
              <Icon name={l.hold ? "unlock" : "lock"} /> {l.hold ? t("mfg.lotsTab.str.release") : t("mfg.lotsTab.str.hold")}
            </button>
            <button type="button" className="btn sm ghost" onClick={() => setEditing(l)} aria-label={t("mfg.lotsTab.tpl.editLot", { lotcode: l.lot_code })}>
              {t("mfg.lotsTab.btn.edit")}
            </button>
          </span>
        ) : null,
    },
  ];

  const chips: FilterChip[] = [];
  if (q.trim()) chips.push({ key: "q", label: t("mfg.lotsTab.str.search"), value: q.trim(), onClear: () => setQ("") });
  if (before) chips.push({ key: "before", label: t("mfg.lotsTab.str.expiringBefore"), value: fmtDate(before), onClear: () => set("before", "") });
  if (hold) chips.push({ key: "hold", label: t("mfg.lotsTab.str.status"), value: hold === "true" ? "On hold" : "Released", onClear: () => set("hold", "") });

  return (
    <div className="col gap-lg">
      <FilterBar chips={chips} onClearAll={() => (setQ(""), setParams({}, { replace: true }))} search={{ id: "lots-q", value: q, onChange: setQ, placeholder: "Lot code or part number", testId: "lots-search" }} pageKey="LotsTab">
        <div className="field">
          <label htmlFor="lots-before">{t("mfg.lotsTab.label.expiringBefore")}</label>
          <DateInput id="lots-before" value={before} onChange={(v) => set("before", v)} />
        </div>
        <div className="field">
          <label htmlFor="lots-hold">{t("mfg.lotsTab.label.status")}</label>
          <select id="lots-hold" className="select" value={hold} onChange={(e) => set("hold", e.target.value)}>
            <option value="">{t("mfg.lotsTab.text.all")}</option>
            <option value="true">{t("mfg.lotsTab.text.onHold")}</option>
            <option value="false">{t("mfg.lotsTab.text.usable")}</option>
          </select>
        </div>
      </FilterBar>
      <MfgError error={data.error ?? toggleError} onRetry={data.reload} />
      <VirtualTable
        card={{ title: "lot", status: "hold", fields: ["pn", "exp", "oh"] }}
        rows={data.rows}
        columns={columns}
        rowKey={(l) => l.id}
        sort={{ key: sort, dir: sort.startsWith("-") ? "desc" : "asc" }}
        onSortChange={(x) => setSearchParam(setParams, "sort", !x || x.key === "expires_on" ? "" : x.key)}
        label={t("mfg.lotsTab.label.lots")}
        testId="lots-table"
        totalCount={data.total}
        scrollTo={scrollTo}
        rowExtras={(l) => ({ testId: "lot-row", data: { lot: l.lot_code, hold: l.hold }, className: l.id === lotParam ? "mfg-selected" : undefined })}
        onEndReached={data.onEndReached}
        empty={data.loading ? t("mfg.lotsTab.str.loadingLots") : t("mfg.lotsTab.str.noLotsLotsAreCreated")}
        footer={<span className="muted small">{t("mfg.lotsTab.text.showingLotsEarliestExpiryFirst", { t: t("common.nOfM", { n: data.rows.length.toLocaleString(LOCALE), m: data.total.toLocaleString(LOCALE) }) })}</span>}
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
