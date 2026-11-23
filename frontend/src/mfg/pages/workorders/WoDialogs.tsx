/**
 * Work-order postings (M2 14.2, 4.1): Issue / Return components (`wo_issue` / `wo_return`) and Report output
 * (`wo_receipt`), plus the component-list editor (PUT with `components`).
 */
import { useRef, useState } from "react";
import { Dialog } from "../../../components/Dialog";
import { Icon } from "../../../components/Icon";
import { createPosting, newIdempotencyKey, updateWorkOrder } from "../../api/clientM2";
import type { ItemRef } from "../../api/types";
import type { KittingComponent, PostingInput, PostingRecord, WorkOrderInput, WorkOrderRecord } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { numOrNull } from "../../components/Field";
import { ItemPicker } from "../../components/ItemPicker";
import { LocationSelect } from "../../components/PickersM2";
import { fmtNum } from "../../lib/formatM2";
import { isCountUom, useItemInfo } from "../../lib/itemCache";
import { toast } from "../../../components/Toast";
import { DateInput } from "../../../components/DateInput";
import { t } from "../../../lib/i18n";

function usePost() {
  const keyRef = useRef<{ body: string; key: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const post = async (body: PostingInput): Promise<PostingRecord | null> => {
    const text = JSON.stringify(body);
    if (!keyRef.current || keyRef.current.body !== text) keyRef.current = { body: text, key: newIdempotencyKey("wo") };
    setBusy(true);
    setError(null);
    try {
      return (await createPosting(body, keyRef.current.key)).record;
    } catch (e) {
      setError(e);
      return null;
    } finally {
      setBusy(false);
    }
  };
  return { post, busy, error };
}

export function IssueDialog({
  wo,
  mode,
  kitting,
  onClose,
  onDone,
}: {
  wo: WorkOrderRecord;
  mode: "issue" | "return";
  kitting: KittingComponent[] | null;
  onClose(): void;
  onDone(p: PostingRecord): void;
}) {
  const kit = new Map((kitting ?? []).map((k) => [k.component_id, k]));
  const comps = wo.components.filter((c) => (mode === "issue" ? c.open_qty > 0 : c.issued_qty > 0));
  const [rows, setRows] = useState(() =>
    comps.map((c) => {
      const loc = kit.get(c.id)?.locations[0];
      return { c, qty: "", location_id: loc?.location_id ?? "", lot_code: "", over: false };
    }),
  );
  const { post, busy, error } = usePost();
  const chosen = rows.filter((r) => (numOrNull(r.qty) ?? 0) > 0);
  const problems = chosen
    .map((r) => {
      const q = numOrNull(r.qty) ?? 0;
      if (!r.location_id) return t("mfg.woDialogs.tpl.chooseALocation", { partnumber: r.c.item.part_number });
      if (isCountUom(r.c.item.uom) && !Number.isInteger(q)) return t("mfg.woDialogs.tpl.wholeOnly", { partnumber: r.c.item.part_number, uom: r.c.item.uom });
      if (mode === "issue" && q > r.c.open_qty + 1e-9 && !r.over) return t("mfg.woDialogs.tpl.moreThanTheStillOpen", { partnumber: r.c.item.part_number, openqty: fmtNum(r.c.open_qty) });
      if (mode === "return" && q > r.c.issued_qty + 1e-9) return t("mfg.woDialogs.tpl.atMostTheIssued", { partnumber: r.c.item.part_number, issuedqty: fmtNum(r.c.issued_qty) });
      return null;
    })
    .filter((x): x is string => Boolean(x));
  const patch = (i: number, p: Partial<(typeof rows)[number]>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const submit = async () => {
    const lines = chosen.map((r) => ({ wo_component_id: r.c.id, location_id: r.location_id, lot_code: r.lot_code.trim() || null, qty: numOrNull(r.qty) ?? 0, ...(mode === "issue" ? { over_issue: r.over } : {}) }));
    const body: PostingInput = mode === "issue" ? { type: "wo_issue", note: wo.number, lines } : { type: "wo_return", note: wo.number, lines };
    const p = await post(body);
    if (p) onDone(p);
  };
  return (
    <Dialog
      title={mode === "issue" ? t("mfg.woDialogs.tpl.issueComponentsTo", { number: wo.number }) : t("mfg.woDialogs.tpl.returnComponentsFrom", { number: wo.number })}
      onClose={onClose}
      wide
      footer={
        <>
          {mode === "issue" ? (
            <button
              type="button"
              className="btn ghost"
              onClick={() => setRows((rs) => rs.map((r) => ({ ...r, qty: String(Math.min(r.c.open_qty, Math.max(r.c.reserved_qty, kit.get(r.c.id)?.locations[0]?.available ?? 0))) })))}
              data-testid="wo-issue-fill"
            >
              {t("mfg.woDialogs.btn.fillOpenQuantitiesAsAvailable")}
            </button>
          ) : null}
          <span className="grow" />
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("mfg.woDialogs.btn.cancel")}
          </button>
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={busy || !chosen.length || problems.length > 0} data-testid={`wo-${mode}-submit`}>
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />} {mode === "issue" ? t("mfg.woDialogs.str.postIssue") : t("mfg.woDialogs.str.postReturn")}
          </button>
        </>
      }
    >
      <div className="col">
        {mode === "issue" ? <p className="muted small" style={{ margin: 0 }}>{t("mfg.woDialogs.text.stockReservedForThisWork")}</p> : null}
        <div className="table-wrap" style={{ maxHeight: "50vh", overflow: "auto" }}>
          <table className="table mfg-grid-table">
            <thead>
              <tr>
                <th>{t("mfg.woDialogs.head.part")}</th>
                <th className="right">{mode === "issue" ? t("mfg.woDialogs.str.open") : t("mfg.woDialogs.str.issued")}</th>
                <th className="right">{t("mfg.woDialogs.head.reserved")}</th>
                <th>{mode === "issue" ? t("mfg.woDialogs.str.issueNow") : t("mfg.woDialogs.str.return")}</th>
                <th>{t("mfg.woDialogs.head.location")}</th>
                <th>{t("mfg.woDialogs.head.lot")}</th>
                {mode === "issue" ? <th>Over-issue</th> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.c.id} data-testid={`wo-${mode}-row`} data-item={r.c.item.part_number}>
                  <td>
                    <span className="mono">{r.c.item.part_number}</span> <span className="faint small">{r.c.find_number ?? ""}</span>
                  </td>
                  <td className="right">
                    {fmtNum(mode === "issue" ? r.c.open_qty : r.c.issued_qty)} {r.c.item.uom}
                  </td>
                  <td className="right">{fmtNum(r.c.reserved_qty)}</td>
                  <td style={{ width: 100 }}>
                    <input className="input sm num" type="number" min={0} aria-label={t("mfg.woDialogs.tpl.quantity", { partnumber: r.c.item.part_number })} value={r.qty} onChange={(e) => patch(i, { qty: e.target.value })} data-testid={`wo-${mode}-qty`} />
                  </td>
                  <td style={{ minWidth: 170 }}>
                    <LocationSelect label={t("mfg.woDialogs.tpl.location", { partnumber: r.c.item.part_number })} hideLabel value={r.location_id} onChange={(v) => patch(i, { location_id: v })} />
                  </td>
                  <td>
                    <input className="input sm" aria-label={t("mfg.woDialogs.tpl.lot", { partnumber: r.c.item.part_number })} value={r.lot_code} maxLength={64} placeholder={t("mfg.woDialogs.ph.earliestExpiry")} onChange={(e) => patch(i, { lot_code: e.target.value })} />
                  </td>
                  {mode === "issue" ? (
                    <td>
                      <input type="checkbox" aria-label={t("mfg.woDialogs.tpl.allowOverIssue", { partnumber: r.c.item.part_number })} checked={r.over} onChange={(e) => patch(i, { over: e.target.checked })} />
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {problems.length ? (
          <ul className="mfg-problem-list" role="alert">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : null}
        <MfgError error={error} title={t("mfg.woDialogs.attr.nothingWasPosted")} />
      </div>
    </Dialog>
  );
}

export function OutputDialog({ wo, onClose, onDone }: { wo: WorkOrderRecord; onClose(): void; onDone(p: PostingRecord): void }) {
  const info = useItemInfo(wo.item.id);
  const [qty, setQty] = useState(String(wo.open_qty));
  const [scrap, setScrap] = useState("");
  const [loc, setLoc] = useState("");
  const [lot, setLot] = useState("");
  const [exp, setExp] = useState("");
  const { post, busy, error } = usePost();
  const q = numOrNull(qty) ?? 0;
  const s = numOrNull(scrap) ?? 0;
  const bad = !loc || q < 0 || s < 0 || q + s <= 0 || (isCountUom(wo.item.uom) && (!Number.isInteger(q) || !Number.isInteger(s))) || (Boolean(info?.lot_controlled) && q > 0 && !lot.trim());
  const submit = async () => {
    const p = await post({ type: "wo_receipt", note: wo.number, lines: [{ wo_id: wo.id, location_id: loc, qty: q, scrap_qty: s, lot_code: lot.trim() || null, expires_on: exp || null }] });
    if (p) onDone(p);
  };
  return (
    <Dialog
      title={t("mfg.woDialogs.tpl.reportOutputOf", { number: wo.number })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("mfg.woDialogs.btn.cancel")}
          </button>
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={busy || bad} data-testid="wo-receipt-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="check" />}{" "}{t("mfg.woDialogs.text.postOutput")}
          </button>
        </>
      }
    >
      <div className="col">
        <p className="muted small" style={{ margin: 0 }}>
          {t("mfg.woDialogs.text.doneSoFarReachingThe", { t: t("common.nOfM", { n: fmtNum(wo.qty_completed), m: fmtNum(wo.qty) }), uom: wo.item.uom })}
        </p>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="out-qty">{t("mfg.woDialogs.label.goodQuantity")}</label>
            <input id="out-qty" className="input num" type="number" min={0} value={qty} onChange={(e) => setQty(e.target.value)} data-testid="wo-receipt-qty" />
          </div>
          <div className="field">
            <label htmlFor="out-scrap">{t("mfg.woDialogs.label.scrapped")}</label>
            <input id="out-scrap" className="input num" type="number" min={0} value={scrap} onChange={(e) => setScrap(e.target.value)} />
          </div>
          <LocationSelect label={t("mfg.woDialogs.label.intoLocation")} value={loc} onChange={setLoc} testId="wo-receipt-location" />
          {info?.lot_controlled ? (
            <>
              <div className="field">
                <label htmlFor="out-lot">{t("mfg.woDialogs.label.lot")}</label>
                <input id="out-lot" className="input" maxLength={64} value={lot} onChange={(e) => setLot(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="out-exp">{t("mfg.woDialogs.label.expiresOn")}</label>
                <DateInput id="out-exp" value={exp} onChange={(v) => setExp(v)} />
              </div>
            </>
          ) : null}
        </div>
        <MfgError error={error} title={t("mfg.woDialogs.attr.nothingWasPosted")} />
      </div>
    </Dialog>
  );
}

interface CompDraft {
  key: number;
  id: string | null;
  item: ItemRef | null;
  required: string;
  operation_seq: string;
  find_number: string;
  note: string;
  issued: number;
}

let ck = 0;

export function ComponentsEditor({ wo, input, onClose, onSaved }: { wo: WorkOrderRecord; input: WorkOrderInput; onClose(): void; onSaved(w: WorkOrderRecord): void }) {
  const [rows, setRows] = useState<CompDraft[]>(() =>
    wo.components.map((c) => ({
      key: ++ck,
      id: c.id,
      item: c.item,
      required: String(c.required_qty),
      operation_seq: c.operation_seq === null ? "" : String(c.operation_seq),
      find_number: c.find_number ?? "",
      note: c.note,
      issued: c.issued_qty,
    })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const patch = (i: number, p: Partial<CompDraft>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const problems = rows
    .map((r) => {
      const q = numOrNull(r.required);
      if (!r.item) return t("mfg.woDialogs.str.chooseAPartForEvery");
      if (q === null || q < 0) return t("mfg.woDialogs.tpl.enterTheRequiredQuantity", { partnumber: r.item.part_number });
      if (q < r.issued) return t("mfg.woDialogs.tpl.cannotBeLessThanThe", { partnumber: r.item.part_number, issued: fmtNum(r.issued) });
      return null;
    })
    .filter((x): x is string => Boolean(x));
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const components = rows.map((r) => ({
        id: r.id,
        item_id: r.item!.id,
        required_qty: numOrNull(r.required) ?? 0,
        operation_seq: numOrNull(r.operation_seq),
        find_number: r.find_number.trim() || null,
        note: r.note,
      }));
      onSaved(await updateWorkOrder(wo.id, { ...input, components }, wo.row_version));
      toast(t("mfg.woDialogs.toast.workOrderSaved"));
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={t("mfg.woDialogs.tpl.componentsOf", { number: wo.number })}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={() => setRows((rs) => [...rs, { key: ++ck, id: null, item: null, required: "", operation_seq: "", find_number: "", note: "", issued: 0 }])}>
            <Icon name="plus" /> {t("mfg.woDialogs.btn.addComponent")}
          </button>
          <span className="grow" />
          <button type="button" className="btn" onClick={onClose} data-dialog-close>
            {t("mfg.woDialogs.btn.cancel")}
          </button>
          <button type="button" className="btn primary" onClick={() => void save()} disabled={busy || problems.length > 0} data-testid="wo-components-save">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="save" />}{" "}{t("mfg.woDialogs.text.saveComponents")}
          </button>
        </>
      }
    >
      <div className="col">
        <p className="muted small" style={{ margin: 0 }}>
          {t("mfg.woDialogs.text.theListWasCopiedFrom")}
        </p>
        <div className="table-wrap" style={{ maxHeight: "55vh", overflow: "auto" }}>
          <table className="table mfg-grid-table">
            <thead>
              <tr>
                <th>{t("mfg.woDialogs.head.pos")}</th>
                <th>{t("mfg.woDialogs.head.part")}</th>
                <th>{t("mfg.woDialogs.head.required")}</th>
                <th className="right">{t("mfg.woDialogs.head.issued")}</th>
                <th>{t("mfg.woDialogs.head.op")}</th>
                <th>
                  <span className="sr-only">{t("mfg.woDialogs.text.remove")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.key} data-testid="wo-component-edit-row">
                  <td style={{ width: 80 }}>
                    <input className="input sm" aria-label={t("mfg.woDialogs.tpl.position", { v: i + 1 })} value={r.find_number} maxLength={16} onChange={(e) => patch(i, { find_number: e.target.value })} />
                  </td>
                  <td style={{ minWidth: 220 }}>
                    {r.id ? <span className="mono">{r.item?.part_number}</span> : <ItemPicker label={t("mfg.woDialogs.tpl.component", { v: i + 1 })} hideLabel value={r.item} onChange={(it) => patch(i, { item: it })} />}
                  </td>
                  <td style={{ width: 110 }}>
                    <input className="input sm num" type="number" min={r.issued} aria-label={t("mfg.woDialogs.tpl.required", { v: r.item?.part_number ?? i + 1 })} value={r.required} onChange={(e) => patch(i, { required: e.target.value })} />
                  </td>
                  <td className="right">{fmtNum(r.issued)}</td>
                  <td style={{ width: 80 }}>
                    <input className="input sm num" type="number" aria-label={t("mfg.woDialogs.tpl.operation", { v: i + 1 })} value={r.operation_seq} onChange={(e) => patch(i, { operation_seq: e.target.value })} />
                  </td>
                  <td>
                    <button type="button" className="btn sm ghost icon" aria-label={t("mfg.woDialogs.tpl.removeComponent", { v: i + 1 })} disabled={r.issued > 0} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
                      <Icon name="trash" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {problems.length ? (
          <ul className="mfg-problem-list">
            {[...new Set(problems)].map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : null}
        <MfgError error={error} title={t("mfg.woDialogs.attr.couldNotSave")} />
      </div>
    </Dialog>
  );
}
