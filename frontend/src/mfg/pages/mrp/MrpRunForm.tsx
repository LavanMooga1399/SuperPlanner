/**
 * New MRP run (M2 14.2 `MrpRunForm`, 8.2 `MrpParams`). Guided default: one click plans the whole plant from
 * today's data. "Planning options" holds the expert settings; "What-if" builds a scenario (another date, only
 * some orders, extra demand, delayed deliveries, other lead times, without open requests). A what-if run is
 * for comparison only: its planned orders cannot be converted.
 */
import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "../../../components/Icon";
import { createMrpRun, listDemandOrders, listScheduleBoard, listWorkOrders } from "../../api/clientM2";
import type { ItemRef } from "../../api/types";
import { DEMAND_TYPES, type DemandOrderSummary, type DemandType, type MrpParams, type MrpRunRecord, type ScheduleRow, type WorkOrderSummary } from "../../api/typesM2";
import { MfgError } from "../../components/Feedback";
import { numOrNull } from "../../components/Field";
import { ItemPicker } from "../../components/ItemPicker";
import { fmtDate } from "../../lib/format";
import { DEMAND_TYPE_LABEL, fmtNum } from "../../lib/formatM2";
import { isAbortError, todayInOffset, usePlant } from "../../lib/useMfg";

interface Extra {
  key: number;
  item: ItemRef | null;
  qty: string;
  due: string;
  priority: string;
}
interface SupplyOv {
  key: number;
  item: ItemRef | null;
  target: string; // "s:<schedule id>" | "w:<wo id>"
  date: string;
}
interface LeadOv {
  key: number;
  item: ItemRef | null;
  days: string;
}
let n = 0;

function SupplyTargets({ item, value, onChange }: { item: ItemRef | null; value: string; onChange(v: string): void }) {
  const [opts, setOpts] = useState<{ value: string; label: string }[]>([]);
  useEffect(() => {
    if (!item) {
      setOpts([]);
      return;
    }
    const ctl = new AbortController();
    const load = item.make_buy === "buy"
      ? listScheduleBoard({ item_id: item.id, limit: 200, offset: 0 }, ctl.signal).then((p) =>
          p.items.map((s: ScheduleRow) => ({ value: `s:${s.schedule_id}`, label: `${s.doc.number} / ${s.line_no} / ${s.seq} · ${fmtNum(s.open_qty)} on ${fmtDate(s.dock_date)}` })),
        )
      : listWorkOrders({ item_id: item.id, status: "planned,released,in_progress", limit: 200, offset: 0 }, ctl.signal).then((p) =>
          p.items.map((w: WorkOrderSummary) => ({ value: `w:${w.id}`, label: `${w.number} · ${fmtNum(w.open_qty)} due ${fmtDate(w.due_date)}` })),
        );
    load.then(setOpts).catch((e: unknown) => !isAbortError(e) && setOpts([]));
    return () => ctl.abort();
  }, [item]);
  return (
    <select className="select sm" aria-label="Delivery or work order" value={value} onChange={(e) => onChange(e.target.value)} disabled={!item} data-testid="whatif-supply-target">
      <option value="">{item ? (opts.length ? "Choose…" : "No open supply") : "Choose a part first"}</option>
      {opts.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function MrpRunForm({ onClose, onDone }: { onClose(): void; onDone(r: MrpRunRecord): void }) {
  const plant = usePlant();
  const today = todayInOffset(plant.data?.utc_offset);
  const [label, setLabel] = useState("");
  const [expert, setExpert] = useState(false);
  const [whatIf, setWhatIf] = useState(false);
  const [allocation, setAllocation] = useState<"priority" | "due_date">("priority");
  const [alternates, setAlternates] = useState<"when_short" | "never">("when_short");
  const [safety, setSafety] = useState(true);
  const [horizon, setHorizon] = useState("");
  const [protect, setProtect] = useState("");
  const [asOf, setAsOf] = useState("");
  const [withPr, setWithPr] = useState(true);
  const [orders, setOrders] = useState<DemandOrderSummary[]>([]);
  const [onlyOrders, setOnlyOrders] = useState<Set<string>>(new Set());
  const [types, setTypes] = useState<Set<DemandType>>(new Set());
  const [extra, setExtra] = useState<Extra[]>([]);
  const [supplyOv, setSupplyOv] = useState<SupplyOv[]>([]);
  const [leadOv, setLeadOv] = useState<LeadOv[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!whatIf || orders.length) return;
    const ctl = new AbortController();
    listDemandOrders({ status: "open", limit: 200, offset: 0 }, ctl.signal)
      .then((p) => setOrders(p.items))
      .catch(() => undefined);
    return () => ctl.abort();
  }, [whatIf, orders.length]);

  const h = numOrNull(horizon);
  const params: MrpParams = {
    label: label.trim(),
    ...(expert
      ? {
          allocation,
          alternates,
          safety_stock: safety,
          horizon_days: h,
          protect_programs: protect
            .split(/[,\s]+/)
            .map((s) => s.trim().toUpperCase())
            .filter(Boolean)
            .slice(0, 20),
        }
      : {}),
    ...(whatIf
      ? {
          as_of: asOf || null,
          include_pr_supply: withPr,
          demand_filter: onlyOrders.size || types.size ? { order_ids: onlyOrders.size ? [...onlyOrders] : null, types: types.size ? [...types] : null } : null,
          extra_demand: extra
            .filter((e) => e.item && numOrNull(e.qty) && e.due)
            .map((e) => ({ item_id: e.item!.id, qty: numOrNull(e.qty)!, due_date: e.due, priority: numOrNull(e.priority) ?? 5, label: "What-if" })),
          supply_date_overrides: supplyOv
            .filter((s) => s.target && s.date)
            .map((s) => (s.target.startsWith("s:") ? { schedule_id: s.target.slice(2), date: s.date } : { wo_id: s.target.slice(2), date: s.date })),
          lead_time_overrides: leadOv.filter((l) => l.item && numOrNull(l.days) !== null).map((l) => ({ item_id: l.item!.id, lead_time_days: numOrNull(l.days)! })),
        }
      : {}),
  };
  const isWhatIf =
    whatIf &&
    ((Boolean(asOf) && asOf !== today) ||
      !withPr ||
      Boolean(params.demand_filter) ||
      Boolean(params.extra_demand?.length) ||
      Boolean(params.supply_date_overrides?.length) ||
      Boolean(params.lead_time_overrides?.length));
  const hBad = expert && h !== null && !(Number.isInteger(h) && h >= 7 && h <= 730);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await createMrpRun(params));
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };

  return (
    <section className="card mfg-inline-form" data-testid="mrp-run-form" aria-labelledby="mrp-form-title">
      <div className="card-header">
        <h2 id="mrp-form-title">Plan materials for the whole plant</h2>
        <button type="button" className="btn sm ghost" onClick={onClose}>
          <Icon name="x" /> Close
        </button>
      </div>
      <div className="card-body col">
        <p className="muted small" style={{ margin: 0 }}>
          Uses every open demand order, the stock, open purchase orders and requests (with their staggered deliveries) and work orders, and works out what to make and buy, how many and by when.
          Usually takes a few seconds.
        </p>
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="mrp-label">Name (optional)</label>
          <input id="mrp-label" className="input" maxLength={100} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Weekly plan" data-testid="mrp-label" />
        </div>
        <div className="row wrap">
          <button type="button" className="btn sm ghost" aria-expanded={expert} onClick={() => setExpert((x) => !x)} data-testid="mrp-expert-toggle">
            <Icon name={expert ? "chevron-down" : "chevron-right"} /> Planning options
          </button>
          <button type="button" className="btn sm ghost" aria-expanded={whatIf} onClick={() => setWhatIf((x) => !x)} data-testid="mrp-whatif-toggle">
            <Icon name={whatIf ? "chevron-down" : "chevron-right"} /> What-if scenario
          </button>
        </div>
        {expert ? (
          <fieldset className="mfg-fieldset" data-testid="mrp-expert">
            <legend>Planning options</legend>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="mrp-alloc">When stock is not enough for everyone</label>
                <select id="mrp-alloc" className="select" value={allocation} onChange={(e) => setAllocation(e.target.value as "priority" | "due_date")}>
                  <option value="priority">Higher priority orders get it first</option>
                  <option value="due_date">Earliest due date gets it first</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="mrp-alt">Alternate parts</label>
                <select id="mrp-alt" className="select" value={alternates} onChange={(e) => setAlternates(e.target.value as "when_short" | "never")}>
                  <option value="when_short">Use stock of alternates when the main part is late</option>
                  <option value="never">Never use alternates</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="mrp-h">Horizon (days)</label>
                <input id="mrp-h" className="input" type="number" min={7} max={730} value={horizon} onChange={(e) => setHorizon(e.target.value)} placeholder={String(plant.data?.planning_horizon_days ?? 90)} aria-invalid={hBad} />
                <span className="hint">{hBad ? "7 to 730 days." : "Demand due later is not planned."}</span>
              </div>
              <div className="field">
                <label htmlFor="mrp-protect">Protect programmes</label>
                <input id="mrp-protect" className="input" value={protect} onChange={(e) => setProtect(e.target.value)} placeholder="e.g. KVP-26, KVP-PROTO" />
                <span className="hint">Their demand is served before everything else.</span>
              </div>
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={safety} onChange={(e) => setSafety(e.target.checked)} /> Plan to keep safety stock
            </label>
          </fieldset>
        ) : null}
        {whatIf ? (
          <fieldset className="mfg-fieldset" data-testid="mrp-whatif">
            <legend>What-if scenario</legend>
            <p className="hint" style={{ margin: 0 }}>
              Changes here are only for this run; no data is changed. Compare the result with the live plan afterwards.
            </p>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="mrp-asof">Plan as of</label>
                <input id="mrp-asof" className="input" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} data-testid="whatif-as-of" />
                <span className="hint">Empty = today ({fmtDate(today)})</span>
              </div>
              <label className="checkbox" style={{ alignSelf: "flex-end" }}>
                <input type="checkbox" checked={!withPr} onChange={(e) => setWithPr(!e.target.checked)} data-testid="whatif-no-pr" /> As if open purchase requests did not exist
              </label>
            </div>
            <div className="field">
              <span className="field-label">Only plan these demand types</span>
              <div className="row wrap">
                {DEMAND_TYPES.map((t) => (
                  <label key={t} className="checkbox">
                    <input
                      type="checkbox"
                      checked={types.has(t)}
                      onChange={(e) =>
                        setTypes((s) => {
                          const x = new Set(s);
                          if (e.target.checked) x.add(t);
                          else x.delete(t);
                          return x;
                        })
                      }
                    />
                    {DEMAND_TYPE_LABEL[t]}
                  </label>
                ))}
              </div>
            </div>
            {orders.length ? (
              <div className="field">
                <span className="field-label">Only plan these orders (none ticked = all open orders)</span>
                <div className="row wrap" style={{ maxHeight: 120, overflow: "auto" }}>
                  {orders.map((o) => (
                    <label key={o.id} className="checkbox">
                      <input
                        type="checkbox"
                        checked={onlyOrders.has(o.id)}
                        onChange={(e) =>
                          setOnlyOrders((s) => {
                            const x = new Set(s);
                            if (e.target.checked) x.add(o.id);
                            else x.delete(o.id);
                            return x;
                          })
                        }
                      />
                      <span className="mono">{o.number}</span>
                    </label>
                  ))}
                </div>
              </div>
            ) : null}
            <WhatIfRows
              title="Delayed or earlier deliveries"
              add="Add a delivery date change"
              testId="whatif-supply"
              rows={supplyOv}
              setRows={setSupplyOv}
              blank={() => ({ key: ++n, item: null, target: "", date: "" })}
              render={(r, set) => (
                <>
                  <div style={{ width: 220 }}>
                    <ItemPicker label="Part" hideLabel value={r.item} onChange={(it) => set({ item: it, target: "" })} />
                  </div>
                  <div style={{ minWidth: 260 }}>
                    <SupplyTargets item={r.item} value={r.target} onChange={(v) => set({ target: v })} />
                  </div>
                  <input className="input sm" type="date" aria-label="New date" value={r.date} onChange={(e) => set({ date: e.target.value })} data-testid="whatif-supply-date" />
                </>
              )}
            />
            <WhatIfRows
              title="Extra demand"
              add="Add extra demand"
              testId="whatif-extra"
              rows={extra}
              setRows={setExtra}
              blank={() => ({ key: ++n, item: null, qty: "", due: "", priority: "5" })}
              render={(r, set) => (
                <>
                  <div style={{ width: 220 }}>
                    <ItemPicker label="Item" hideLabel value={r.item} onChange={(it) => set({ item: it })} />
                  </div>
                  <input className="input sm num" type="number" aria-label="Quantity" placeholder="Qty" value={r.qty} onChange={(e) => set({ qty: e.target.value })} style={{ width: 90 }} />
                  <input className="input sm" type="date" aria-label="Due date" value={r.due} onChange={(e) => set({ due: e.target.value })} />
                  <input className="input sm num" type="number" min={1} max={9} aria-label="Priority" value={r.priority} onChange={(e) => set({ priority: e.target.value })} style={{ width: 64 }} />
                </>
              )}
            />
            <WhatIfRows
              title="Other lead times"
              add="Add a lead-time change"
              testId="whatif-lead"
              rows={leadOv}
              setRows={setLeadOv}
              blank={() => ({ key: ++n, item: null, days: "" })}
              render={(r, set) => (
                <>
                  <div style={{ width: 220 }}>
                    <ItemPicker label="Item" hideLabel value={r.item} onChange={(it) => set({ item: it })} />
                  </div>
                  <input className="input sm num" type="number" min={0} aria-label="Lead time days" placeholder="days" value={r.days} onChange={(e) => set({ days: e.target.value })} style={{ width: 90 }} />
                  <span className="faint small">{r.item?.make_buy === "make" ? "working days" : "calendar days"}</span>
                </>
              )}
            />
          </fieldset>
        ) : null}
        {isWhatIf ? (
          <p className="small" role="status" style={{ margin: 0 }}>
            <Icon name="help" size={12} /> This will be a <strong>what-if</strong> run: for comparison only, its planned orders cannot be converted.
          </p>
        ) : null}
        <MfgError error={error} title="The plan could not be run" />
        <div className="row">
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={busy || hBad} data-testid="mrp-run-submit">
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />} {busy ? "Planning…" : isWhatIf ? "Run what-if" : "Run MRP"}
          </button>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </section>
  );
}

function WhatIfRows<R extends { key: number }>({
  title,
  add,
  rows,
  setRows,
  blank,
  render,
  testId,
}: {
  title: string;
  add: string;
  rows: R[];
  setRows(fn: (r: R[]) => R[]): void;
  blank(): R;
  render(r: R, set: (p: Partial<R>) => void): ReactNode;
  testId: string;
}) {
  return (
    <div className="col" style={{ gap: 6 }} data-testid={testId}>
      <span className="field-label">{title}</span>
      {rows.map((r, i) => (
        <div key={r.key} className="row wrap" style={{ gap: 6 }}>
          {render(r, (p) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, ...p } : x))))}
          <button type="button" className="btn sm ghost icon" aria-label="Remove" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
            <Icon name="trash" />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn sm" onClick={() => setRows((rs) => [...rs, blank()])} data-testid={`${testId}-add`}>
          <Icon name="plus" /> {add}
        </button>
      </div>
    </div>
  );
}
