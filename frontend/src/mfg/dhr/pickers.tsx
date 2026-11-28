/**
 * Small pickers of the M10 screens: lot search (code), NCR and deviation selects limited to the lot / work orders of
 * a record (a disposition must reference a record of the same lot or WO, 422 `DHR_REF_SCOPE`).
 */
import { useId, useState } from "react";
import { Icon } from "../../components/Icon";
import { t } from "../../lib/i18n";
import { ItemPicker } from "../components/ItemPicker";
import { ItemById } from "../forecast/shared";
import { listLots, listWorkOrders } from "../api/clientM2";
import { listNcrs } from "../api/clientM7";
import { listDeviations } from "../api/clientM10";
import type { LotRecord } from "../api/typesM2";
import { useDebounced, useLoad } from "../lib/useMfg";

export interface LotRef {
  id: string;
  code: string;
  item_id?: string;
  part_number?: string;
}

/** Type-ahead on lot codes; shows the item of each lot. */
export function LotPicker({ id, value, onChange, itemId, label, testId, required }: { id?: string; value: LotRef | null; onChange(v: LotRef | null): void; itemId?: string | null; label: string; testId?: string; required?: boolean }) {
  const uid = useId().replace(/:/g, "");
  const fid = id ?? `lot-${uid}`;
  const [text, setText] = useState(value?.code ?? "");
  const dq = useDebounced(text.trim(), 200);
  const open = !value || value.code !== text;
  const res = useLoad((s) => (open && dq.length >= 1 ? listLots({ q: dq, item_id: itemId ?? undefined, limit: 8 }, s) : null), [dq, itemId, open]);
  const pick = (l: LotRecord) => {
    setText(l.lot_code);
    onChange({ id: l.id, code: l.lot_code, item_id: l.item.id, part_number: l.item.part_number });
  };
  return (
    <div className="field" style={{ position: "relative" }}>
      <label htmlFor={fid}>
        {label}
        {required ? <span className="req" aria-hidden /> : null}
      </label>
      <input
        id={fid}
        className="input mono"
        value={text}
        autoComplete="off"
        role="combobox"
        aria-expanded={open && Boolean(res.data?.items.length)}
        aria-controls={`${fid}-list`}
        placeholder={t("gxp.pick.lotPh")}
        onChange={(e) => {
          setText(e.target.value);
          if (value) onChange(null);
        }}
        data-testid={testId}
      />
      {open && res.data?.items.length ? (
        <ul id={`${fid}-list`} role="listbox" className="popover left gxp-suggest">
          {res.data.items.map((l) => (
            <li key={l.id} role="option" aria-selected={false}>
              <button type="button" className="menu-item" style={{ width: "100%", textAlign: "left" }} onClick={() => pick(l)} data-testid="lot-option">
                <span className="mono">{l.lot_code}</span> <span className="muted small">{l.item.part_number}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Work orders by number (type-ahead), for assembling a record of a WO without a lot. */
export function WoPicker({ value, onChange, label, testId }: { value: { id: string; number: string } | null; onChange(v: { id: string; number: string } | null): void; label: string; testId?: string }) {
  const uid = useId().replace(/:/g, "");
  const [text, setText] = useState(value?.number ?? "");
  const dq = useDebounced(text.trim(), 200);
  const open = !value || value.number !== text;
  const res = useLoad((s) => (open && dq.length >= 1 ? listWorkOrders({ q: dq, limit: 8 }, s) : null), [dq, open]);
  return (
    <div className="field" style={{ position: "relative" }}>
      <label htmlFor={`wo-${uid}`}>{label}</label>
      <input
        id={`wo-${uid}`}
        className="input mono"
        value={text}
        autoComplete="off"
        placeholder={t("gxp.pick.woPh")}
        onChange={(e) => {
          setText(e.target.value);
          if (value) onChange(null);
        }}
        data-testid={testId}
      />
      {open && res.data?.items.length ? (
        <ul role="listbox" className="popover left gxp-suggest">
          {res.data.items.map((w) => (
            <li key={w.id} role="option" aria-selected={false}>
              <button
                type="button"
                className="menu-item"
                style={{ width: "100%", textAlign: "left" }}
                onClick={() => {
                  setText(w.number);
                  onChange({ id: w.id, number: w.number });
                }}
              >
                <span className="mono">{w.number}</span> <span className="muted small">{w.item?.part_number ?? ""}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** NCRs of the record's item, limited to its lot / work orders. */
export function NcrSelect({ id, itemId, lotId, woIds, value, onChange, disabled, testId }: { id: string; itemId: string | null; lotId: string | null; woIds: string[]; value: string; onChange(v: string): void; disabled?: boolean; testId?: string }) {
  const res = useLoad((s) => (itemId ? listNcrs({ item_id: itemId, limit: 100 }, s) : null), [itemId]);
  const rows = (res.data?.items ?? []).filter((n) => (lotId && n.lot_id === lotId) || (n.wo_id && woIds.includes(n.wo_id)));
  return (
    <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} data-testid={testId}>
      <option value="">{res.loading ? t("gxp.pick.loading") : rows.length ? t("gxp.pick.chooseNcr") : t("gxp.pick.noNcr")}</option>
      {rows.map((n) => (
        <option key={n.id} value={n.id}>
          {n.number} · {n.title}
        </option>
      ))}
    </select>
  );
}

/** Deviations covering the lot (planned and approved, or unplanned of this lot). */
export function DeviationSelect({ id, lotId, itemId, value, onChange, disabled, testId }: { id: string; lotId: string | null; itemId: string | null; value: string; onChange(v: string): void; disabled?: boolean; testId?: string }) {
  const res = useLoad((s) => listDeviations({ lot_id: lotId ?? undefined, item_id: itemId ?? undefined, status: "draft,approved", limit: 100 }, s), [lotId, itemId]);
  const rows = res.data?.items ?? [];
  return (
    <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} data-testid={testId}>
      <option value="">{res.loading ? t("gxp.pick.loading") : rows.length ? t("gxp.pick.chooseDev") : t("gxp.pick.noDev")}</option>
      {rows.map((d) => (
        <option key={d.id} value={d.id}>
          {d.number} · {d.title}
          {d.status !== "approved" ? ` (${t("gxp.doc.draft")})` : ""}
        </option>
      ))}
    </select>
  );
}

/** A list of items (ids) edited with the item picker; each shown as a removable chip with its part number. */
export function ItemListPicker({ ids, onChange, label, disabled, testId }: { ids: string[]; onChange(ids: string[]): void; label: string; disabled?: boolean; testId?: string }) {
  return (
    <div className="field" data-testid={testId}>
      <span className="field-label">{label}</span>
      {ids.length ? (
        <div className="chips" style={{ marginBottom: 4 }}>
          {ids.map((id) => (
            <span key={id} className="chip">
              <ItemById id={id} />
              {!disabled ? (
                <button type="button" className="btn link sm" aria-label={t("gxp.pick.remove")} onClick={() => onChange(ids.filter((x) => x !== id))}>
                  <Icon name="x" size={12} />
                </button>
              ) : null}
            </span>
          ))}
        </div>
      ) : null}
      {!disabled ? <ItemPicker value={null} onChange={(it) => it && !ids.includes(it.id) && onChange([...ids, it.id])} label={label} hideLabel /> : null}
    </div>
  );
}

/** Lots (id + code) as removable chips plus a lot search to add one. */
export function LotListPicker({ lots, onChange, label, itemId, disabled, testId }: { lots: LotRef[]; onChange(l: LotRef[]): void; label: string; itemId?: string | null; disabled?: boolean; testId?: string }) {
  const [pick, setPick] = useState<LotRef | null>(null);
  const [k, setK] = useState(0);
  return (
    <div className="col" style={{ gap: 4 }} data-testid={testId}>
      {lots.length ? (
        <div className="chips">
          {lots.map((l) => (
            <span key={l.id} className="chip mono">
              {l.code}
              {!disabled ? (
                <button type="button" className="btn link sm" aria-label={t("gxp.pick.remove")} onClick={() => onChange(lots.filter((x) => x.id !== l.id))}>
                  <Icon name="x" size={12} />
                </button>
              ) : null}
            </span>
          ))}
        </div>
      ) : null}
      {!disabled ? (
        <LotPicker
          key={k}
          value={pick}
          itemId={itemId}
          label={label}
          onChange={(l) => {
            setPick(l);
            if (l && !lots.some((x) => x.id === l.id)) {
              onChange([...lots, l]);
              setPick(null);
              setK((x) => x + 1);
            }
          }}
        />
      ) : null}
    </div>
  );
}
