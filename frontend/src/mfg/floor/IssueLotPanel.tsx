/**
 * Floor action "Issue component lot" (demo review, `POST /mfg/floor/issue-lot`): scan (or type) the lot, choose the
 * component when several lines use that item, quantity defaults to the component's remaining requirement. Issuing
 * more than remains needs an explicit confirmation and a reason (422 `FLR_OVER_ISSUE`). Holds, expiry and
 * quarantine are enforced by the server; its message is shown as is.
 */
import { useState } from "react";
import { ApiError } from "../../api/client";
import { Icon } from "../../components/Icon";
import { t } from "../../lib/i18n";
import { formatNumber } from "../../lib/locale";
import { floorIssueLot } from "../api/clientM4";
import type { FloorOperationDetail } from "../api/typesM4";
import { floorErrorText } from "./floorText";
import { useFloor, useScanHandler } from "./FloorLayout";

export function IssueLotPanel({ d, onCancel, onDone }: { d: FloorOperationDetail; onCancel(): void; onDone(): void }) {
  const floor = useFloor();
  const comps = d.components.filter((c) => !c.backflush);
  const [lot, setLot] = useState("");
  const [comp, setComp] = useState("");
  const [qty, setQty] = useState("");
  const [over, setOver] = useState<{ remaining: number } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [eventId] = useState(() => `iss-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`);
  // scans while the panel is open fill the lot field
  useScanHandler(
    (code) => {
      setLot(code);
      setErr(null);
      setOver(null);
      return true;
    },
    [],
  );
  const chosen = comps.find((c) => c.component_id === comp) ?? null;
  const remaining = chosen ? Math.max(0, chosen.required_qty - chosen.issued_qty) : null;
  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await floorIssueLot({
        wo_operation_id: d.operation.id,
        scan: lot.trim(),
        wo_component_id: comp || null,
        qty: qty.trim() ? Number(qty) : null,
        over_issue: Boolean(over && confirm),
        reason: over && confirm ? reason.trim() : null,
        client_event_id: `${eventId}-${over && confirm ? "o" : "n"}`,
      });
      floor.flash(t("plan.fi.done", { qty: formatNumber(r.qty), lot: r.lot.lot_code, rem: formatNumber(r.component.remaining) }));
      onDone();
    } catch (e) {
      if (e instanceof ApiError && e.code === "FLR_OVER_ISSUE") {
        setOver({ remaining: Number((e.details as { remaining?: number })?.remaining ?? 0) });
        setConfirm(false);
      } else if (e instanceof ApiError && e.code === "FLR_CHOOSE_COMPONENT") setErr(t("plan.fi.choose"));
      else setErr(floorErrorText(e));
    } finally {
      setBusy(false);
    }
  };
  const ready = lot.trim().length > 0 && (!qty.trim() || Number(qty) > 0) && (!over || (confirm && reason.trim().length > 0));
  return (
    <section className="floor-card" aria-label={t("plan.fi.title")} data-testid="floor-issue-panel">
      <h2>{t("plan.fi.title")}</h2>
      <form
        className="col"
        style={{ gap: 12 }}
        onSubmit={(e) => {
          e.preventDefault();
          if (ready && !busy) void submit();
        }}
      >
        <div className="field">
          <label htmlFor="fi-lot">{t("plan.fi.lot")}</label>
          <input id="fi-lot" className="input mono" value={lot} onChange={(e) => {
            setLot(e.target.value);
            setOver(null);
          }} placeholder={t("plan.fi.lotPh")} autoComplete="off" data-testid="floor-issue-lot" data-autofocus />
        </div>
        <div className="field">
          <label htmlFor="fi-comp">{t("plan.fi.component")}</label>
          <select id="fi-comp" className="select" value={comp} onChange={(e) => {
            setComp(e.target.value);
            setOver(null);
          }} data-testid="floor-issue-component">
            <option value="">{t("plan.fi.auto")}</option>
            {comps.map((c) => (
              <option key={c.component_id} value={c.component_id}>
                {t("plan.fi.compOption", { part: c.item.part_number, rem: formatNumber(Math.max(0, c.required_qty - c.issued_qty)) })}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="fi-qty">{t("plan.fi.qty")}</label>
          <input id="fi-qty" className="input" type="number" inputMode="decimal" min={0} step="any" value={qty} onChange={(e) => {
            setQty(e.target.value);
            setOver(null);
          }} placeholder={remaining !== null ? formatNumber(remaining) : t("plan.fi.qtyPh")} data-testid="floor-issue-qty" />
          <span className="hint">{t("plan.fi.qtyHint")}</span>
        </div>
        {over ? (
          <div className="floor-card floor-down" role="alert" data-testid="floor-issue-over">
            <strong>{t("plan.fi.overTitle", { rem: formatNumber(over.remaining) })}</strong>
            <label className="row" style={{ gap: 8 }}>
              <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} data-testid="floor-issue-over-confirm" /> {t("plan.fi.overConfirm")}
            </label>
            <div className="field">
              <label htmlFor="fi-reason">{t("plan.fi.reason")}</label>
              <input id="fi-reason" className="input" maxLength={200} value={reason} disabled={!confirm} onChange={(e) => setReason(e.target.value)} data-testid="floor-issue-reason" />
            </div>
          </div>
        ) : null}
        {err ? (
          <div className="floor-flash danger" role="alert">
            <Icon name="alert" /> {err}
          </div>
        ) : null}
        <div className="floor-actions">
          <button type="submit" className="btn primary floor-action" disabled={!ready || busy} data-testid="floor-issue-submit">
            <Icon name="box" size={22} /> {over ? t("plan.fi.submitOver") : t("plan.fi.submit")}
          </button>
          <button type="button" className="btn floor-btn" onClick={onCancel}>
            {t("common.cancel")}
          </button>
        </div>
      </form>
    </section>
  );
}
