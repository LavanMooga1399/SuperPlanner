/**
 * `/mfg/floor/ops/:woOpId` (M4 12, #202/#203): one operation on the tablet.
 * - Big Start setup / Start / Pause / Resume / Report / Complete buttons from the server's `allowed_actions`.
 * - Quantity pad for good / scrap / rework (with a reason and the operation to rework at), steppers sized for gloves.
 * - Serial capture when the operation is a serial point (15 Q3): scan `S:<part>:<serial>` or type; one per good unit.
 * - Operators on the event: the badges signed in on this tablet (station login) or the personal login.
 * - Every action has a fresh `client_event_id`; offline actions queue and sync in order (offlineQueue).
 * - Supervisors may record over the input quantity with a reason (`force`, FLR_QTY_EXCEEDS_INPUT).
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "../../api/client";
import { Icon } from "../../components/Icon";
import { getFloorOperation, listWoOperationsM4 } from "../api/clientM4";
import type { FloorEventInput, FloorEventResult, FloorEventType, FloorOperationDetail, WoOperation } from "../api/typesM4";
import { MfgError, Spinner } from "../components/Feedback";
import { fmtDuration, usePlantClock } from "../lib/plantTime";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { crewForEvent, useFloor, useScanHandler } from "./FloorLayout";
import { ACTION, DEFAULT_REASONS, EVENT_LABEL, KitChip, OpStatusChip, floorErrorText, fmtQty, humanCode } from "./floorText";
import { newClientEventId, submitFloorEvent } from "./offlineQueue";

type Panel = null | "report" | "complete" | "pause";

const PRIMARY_ORDER: FloorEventType[] = ["setup_start", "start", "resume", "pause", "report", "complete"];

export function FloorOperation() {
  const { woOpId = "" } = useParams();
  const floor = useFloor();
  const clock = usePlantClock();
  const canReport = useCan("floor_report");
  const canSupervise = useCan("floor_supervise");
  const det = useLoad((signal) => getFloorOperation(woOpId, signal), [woOpId]);
  const d = det.data;
  const [panel, setPanel] = useState<Panel>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [lastResult, setLastResult] = useState<(FloorEventResult & { replayed: boolean }) | null>(null);
  const [lineId, setLineId] = useState<string>("");
  const [eventAt, setEventAt] = useState<string>(""); // local datetime, "" = now
  const op = d?.operation;

  useEffect(() => {
    if (!d) return;
    document.title = `${d.wo.number}/${d.operation.seq} - Floor`;
    const eligible = d.eligible_lines;
    if (!lineId) {
      const pick = eligible.find((l) => l.id === floor.lineId)?.id ?? d.operation.line?.id ?? eligible[0]?.id ?? floor.lineId ?? "";
      setLineId(pick);
    }
  }, [d, floor.lineId, lineId]);

  const allowed = useMemo(() => {
    const a = new Set(d?.allowed_actions ?? []);
    return PRIMARY_ORDER.filter((x) => a.has(x));
  }, [d]);

  const post = async (type: FloorEventType, extra: Partial<FloorEventInput> = {}) => {
    if (!d) return false;
    setBusy(true);
    setError(null);
    const body: FloorEventInput = {
      client_event_id: newClientEventId(),
      wo_operation_id: d.operation.id,
      event_type: type,
      ...crewForEvent(floor.crew),
      ...(type === "setup_start" || type === "start" ? (lineId ? { line_id: lineId } : {}) : {}),
      ...(eventAt ? { event_at: clock.fromLocal(eventAt) } : {}),
      ...extra,
    };
    try {
      const out = await submitFloorEvent(body, `${EVENT_LABEL[type]} ${d.wo.number}/${d.operation.seq}`);
      if (out.status === "queued") {
        floor.flash("Saved on this tablet; it will sync when the network is back", "warn");
      } else {
        setLastResult(out.result);
        const posted = out.result.postings.length ? ` · ${out.result.postings.length} stock posting${out.result.postings.length === 1 ? "" : "s"}` : "";
        floor.flash(`${EVENT_LABEL[type]}${posted}${out.result.replayed ? " (already recorded)" : ""}`);
      }
      setPanel(null);
      setEventAt("");
      det.reload();
      return true;
    } catch (e) {
      setError(e);
      return false;
    } finally {
      setBusy(false);
      floor.focusScan();
    }
  };

  if (det.loading && !d) return <Spinner label="Loading the operation…" />;
  if (!d || !op) return <MfgError error={det.error} onRetry={det.reload} />;

  const remaining = Math.max(0, op.qty_available);
  const lineDown = d.eligible_lines.find((l) => l.id === lineId)?.down;
  const plan = op.placement[0] ?? null;

  return (
    <>
      <section className="floor-card" data-testid="floor-op" data-status={op.status} data-wo={d.wo.number} data-seq={op.seq}>
        <div className="row wrap" style={{ justifyContent: "space-between", gap: 10 }}>
          <div className="col" style={{ gap: 4 }}>
            <span className="muted">
              {floor.lineId ? (
                <Link to={mfgPaths.floorLine(floor.lineId)}>
                  <Icon name="chevron-right" style={{ transform: "rotate(180deg)" }} /> Queue
                </Link>
              ) : null}
            </span>
            <h1>
              <span className="mono">{d.wo.number}</span> / {op.seq} {op.name}
            </h1>
            <span>
              <span className="mono">{d.wo.item.part_number}</span> {d.wo.item.description ?? ""}
            </span>
          </div>
          <OpStatusChip status={op.status} large />
        </div>
        <dl className="floor-kv">
          <dt>Input here</dt>
          <dd>
            {fmtQty(op.qty_input || d.expected_input)} {op.qty_rework_in ? `(incl. ${fmtQty(op.qty_rework_in)} rework)` : ""}
          </dd>
          <dt>Done so far</dt>
          <dd data-testid="floor-op-good" data-good={op.qty_good} data-scrap={op.qty_scrap}>
            {fmtQty(op.qty_good)} good · {fmtQty(op.qty_scrap)} scrap{op.qty_rework_out ? ` · ${fmtQty(op.qty_rework_out)} sent to rework` : ""} · {fmtQty(remaining)} to go
          </dd>
          {op.actual_start ? (
            <>
              <dt>Started</dt>
              <dd>
                {clock.dateTime(op.actual_start)}
                {op.run_minutes_actual ? ` · run ${fmtDuration(op.run_minutes_actual)}` : ""}
                {op.setup_minutes_actual ? ` · setup ${fmtDuration(op.setup_minutes_actual)}` : ""}
              </dd>
            </>
          ) : null}
          {plan ? (
            <>
              <dt>Plan</dt>
              <dd>
                {plan.line?.code ? `${plan.line.code} · ` : ""}
                {clock.dateTime(plan.start)} – {clock.time(plan.end)}
              </dd>
            </>
          ) : null}
        </dl>
        {op.started_short ? (
          <div className="badge warn">
            <Icon name="alert" /> Started with material short
          </div>
        ) : null}
      </section>

      {error && !(error instanceof ApiError && error.code === "FLR_QTY_EXCEEDS_INPUT") ? (
        <div className="floor-flash danger" role="alert" data-testid="floor-error">
          <Icon name="alert" /> {floorErrorText(error)}
        </div>
      ) : null}
      {error instanceof ApiError ? <ErrorCard error={error} /> : null}

      {canReport ? (
        <section className="floor-card">
          {(allowed.includes("setup_start") || allowed.includes("start")) && d.eligible_lines.length > 1 ? (
            <div className="field">
              <label htmlFor="fo-line">Line</label>
              <select id="fo-line" className="select" value={lineId} onChange={(e) => setLineId(e.target.value)} data-testid="floor-op-line">
                {d.eligible_lines.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.code}
                    {l.down ? " (down)" : ""}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {lineDown && (allowed.includes("setup_start") || allowed.includes("start")) ? (
            <div className="badge danger">
              <Icon name="alert" /> This line is reported down
            </div>
          ) : null}
          {!floor.crew.length && !floor.me ? (
            <div className="faint">No operator signed in on this tablet: the action is recorded under your login only.</div>
          ) : null}
          <div className="floor-actions">
            {allowed.map((a) => (
              <button
                key={a}
                type="button"
                className={`btn floor-action ${ACTION[a].tone}${panel === a ? " active" : ""}`}
                disabled={busy}
                aria-pressed={panel === a}
                onClick={() => {
                  setError(null);
                  if (a === "pause" || a === "report" || a === "complete") setPanel(panel === a ? null : a);
                  else void post(a);
                }}
                data-testid={`floor-action-${a}`}
              >
                <Icon name={ACTION[a].icon} size={22} /> {ACTION[a].label}
              </button>
            ))}
            {allowed.length === 0 ? <span className="muted">No action is possible in this state.</span> : null}
          </div>
          <details>
            <summary className="muted">It happened earlier (up to 24 hours back)</summary>
            <div className="field" style={{ maxWidth: 320 }}>
              <label htmlFor="fo-at">When</label>
              <input id="fo-at" className="input" type="datetime-local" value={eventAt} onChange={(e) => setEventAt(e.target.value)} max={clock.toLocal(new Date().toISOString())} />
            </div>
          </details>
        </section>
      ) : (
        <div className="floor-card muted">Your role can see the floor but not record work.</div>
      )}

      {panel === "pause" ? <PausePanel d={d} busy={busy} onCancel={() => setPanel(null)} onSubmit={(reason, note) => void post("pause", { reason_code: reason, ...(note ? { note } : {}) })} /> : null}
      {panel === "report" || panel === "complete" ? (
        <QtyPanel
          key={panel}
          d={d}
          mode={panel}
          remaining={remaining}
          busy={busy}
          canForce={canSupervise}
          forceNeeded={error instanceof ApiError && error.code === "FLR_QTY_EXCEEDS_INPUT"}
          onCancel={() => setPanel(null)}
          onSubmit={(extra) => post(panel, extra)}
        />
      ) : null}

      {lastResult?.warnings.length ? (
        <section className="floor-card" data-testid="floor-warnings">
          {lastResult.warnings.map((w) => (
            <span key={w.code} className="badge warn">
              <Icon name="alert" /> {w.message}
            </span>
          ))}
        </section>
      ) : null}

      <Components d={d} />
      {d.instructions ? (
        <section className="floor-card">
          <h2>Instructions</h2>
          <div style={{ whiteSpace: "pre-wrap" }}>{d.instructions}</div>
        </section>
      ) : null}
      {d.tools.length ? (
        <section className="floor-card">
          <h2>Tools</h2>
          <ul style={{ margin: 0 }}>
            {d.tools.map((t) => (
              <li key={t.tool_pool.id}>
                {t.tool_pool.code}
                {t.tool_pool.name ? ` · ${t.tool_pool.name}` : ""} x{t.qty}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <EventList d={d} clock={clock} />
    </>
  );
}

function ErrorCard({ error }: { error: ApiError }) {
  if (error.code !== "FLR_QTY_EXCEEDS_INPUT") return null;
  return (
    <div className="floor-card floor-down" role="alert" data-testid="floor-error">
      <strong>{floorErrorText(error)}</strong>
      <span className="muted">Check the counts. A supervisor can record it anyway with a reason.</span>
    </div>
  );
}

function PausePanel({ d, busy, onCancel, onSubmit }: { d: FloorOperationDetail; busy: boolean; onCancel(): void; onSubmit(reason: string, note: string): void }) {
  const reasons = d.reason_codes?.pause?.length ? d.reason_codes.pause : DEFAULT_REASONS.pause;
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  return (
    <section className="floor-card" aria-label="Pause">
      <h2>Why are you pausing?</h2>
      <div className="floor-grid" role="radiogroup" aria-label="Pause reason" data-testid="floor-reason">
        {reasons.map((r) => (
          <button key={r.code} type="button" role="radio" aria-checked={reason === r.code} className={`floor-tile${reason === r.code ? " active" : ""}`} onClick={() => setReason(r.code)} data-code={r.code}>
            {r.label}
          </button>
        ))}
      </div>
      <div className="field">
        <label htmlFor="fp-note">Note (optional)</label>
        <input id="fp-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </div>
      <div className="row wrap">
        <button type="button" className="btn primary floor-action" disabled={!reason || busy} onClick={() => onSubmit(reason, note)} data-testid="floor-pause-submit">
          <Icon name="stop" /> Pause now
        </button>
        <button type="button" className="btn floor-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}

function Stepper({ id, label, value, onChange, testId, max }: { id: string; label: string; value: string; onChange(v: string): void; testId: string; max?: number }) {
  const n = Number(value) || 0;
  return (
    <div className="floor-qty-field">
      <label htmlFor={id}>{label}</label>
      <div className="floor-stepper">
        <button type="button" className="btn" aria-label={`${label} minus one`} onClick={() => onChange(String(Math.max(0, n - 1)))}>
          −
        </button>
        <input id={id} className="input" inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value.replace(/[^0-9.]/g, ""))} data-testid={testId} aria-describedby={max !== undefined ? `${id}-max` : undefined} />
        <button type="button" className="btn" aria-label={`${label} plus one`} onClick={() => onChange(String(n + 1))}>
          +
        </button>
      </div>
      {max !== undefined ? (
        <span id={`${id}-max`} className="faint small">
          {fmtQty(max)} still to go
        </span>
      ) : null}
    </div>
  );
}

function QtyPanel({
  d,
  mode,
  remaining,
  busy,
  canForce,
  forceNeeded,
  onCancel,
  onSubmit,
}: {
  d: FloorOperationDetail;
  mode: "report" | "complete";
  remaining: number;
  busy: boolean;
  canForce: boolean;
  forceNeeded: boolean;
  onCancel(): void;
  onSubmit(extra: Partial<FloorEventInput>): Promise<boolean>;
}) {
  const floor = useFloor();
  const op = d.operation;
  const [good, setGood] = useState(mode === "complete" ? String(remaining) : "");
  const [scrap, setScrap] = useState("");
  const [rework, setRework] = useState("");
  const [reworkTo, setReworkTo] = useState<number>(op.seq);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [serials, setSerials] = useState<string[]>([]);
  const [serialText, setSerialText] = useState("");
  const [consumed, setConsumed] = useState<{ item_id: string; serial: string }[]>([]);
  const [forceReason, setForceReason] = useState("");
  const capture = Boolean(d.serials?.capture ?? op.capture_serial);
  const serialComps = d.serials?.consumable ?? [];
  const g = Number(good) || 0;
  const sc = Number(scrap) || 0;
  const rw = Number(rework) || 0;
  const needReason = sc > 0 || rw > 0;
  const reasons = (sc > 0 ? d.reason_codes?.scrap : d.reason_codes?.rework) ?? (sc > 0 ? DEFAULT_REASONS.scrap : DEFAULT_REASONS.rework);
  const ops = useLoad((signal) => (rw > 0 ? listWoOperationsM4(d.wo.id, signal) : null), [d.wo.id, rw > 0]);
  const earlier: WoOperation[] = (ops.data?.items ?? []).filter((o) => o.seq <= op.seq);
  const serialsOk = !capture || g === 0 || serials.length === g;
  const qtyOk = g + sc + rw > 0 || mode === "complete";

  const addSerial = (raw: string) => {
    let s = raw.trim();
    const m = /^S:([^:]+):(.+)$/i.exec(s);
    if (m) {
      if (m[1].toUpperCase() !== d.wo.item.part_number.toUpperCase()) {
        // a child's serial: consumed by this operation
        const comp = serialComps.find((c) => c.part_number.toUpperCase() === m[1].toUpperCase());
        if (comp) {
          if (!consumed.some((x) => x.item_id === comp.item_id && x.serial === m[2])) setConsumed([...consumed, { item_id: comp.item_id, serial: m[2] }]);
          floor.flash(`Consumed ${comp.part_number} serial ${m[2]}`);
          return true;
        }
        floor.flash(`Serial of ${m[1]} does not belong to this operation`, "danger");
        return true;
      }
      s = m[2];
    }
    if (!s) return false;
    if (serials.includes(s)) {
      floor.flash(`Serial ${s} is already in the list`, "warn");
      return true;
    }
    setSerials((x) => [...x, s]);
    return true;
  };
  // scanned serials land here while the panel is open (unknown codes are new serials)
  useScanHandler(
    (code, resolved) => {
      if (!capture && !serialComps.length) return false;
      if (/^S:/i.test(code) || (!resolved && capture)) return addSerial(code);
      return false;
    },
    [capture, serials, consumed],
  );

  const submit = async () => {
    const extra: Partial<FloorEventInput> = {
      ...(g ? { qty_good: g } : mode === "complete" ? { qty_good: 0 } : {}),
      ...(sc ? { qty_scrap: sc } : {}),
      ...(rw ? { qty_rework: rw, rework_to_seq: reworkTo } : {}),
      ...(needReason ? { reason_code: reason } : {}),
      ...(note ? { note } : {}),
      ...(capture && serials.length ? { serials: { produced: serials, ...(consumed.length ? { consumed } : {}) } } : consumed.length ? { serials: { consumed } } : {}),
      ...(forceNeeded && forceReason ? { force: { reason: forceReason } } : {}),
    };
    await onSubmit(extra);
  };

  return (
    <section className="floor-card" aria-label={mode === "complete" ? "Complete" : "Report quantity"} data-testid="floor-qty-panel">
      <h2>{mode === "complete" ? "Complete the operation" : "Report a quantity"}</h2>
      <div className="floor-qty">
        <Stepper id="fq-good" label="Good" value={good} onChange={setGood} testId="floor-qty-good" max={remaining} />
        <Stepper id="fq-scrap" label="Scrap" value={scrap} onChange={setScrap} testId="floor-qty-scrap" />
        <Stepper id="fq-rework" label="Rework" value={rework} onChange={setRework} testId="floor-qty-rework" />
      </div>
      {needReason ? (
        <div className="field">
          <label htmlFor="fq-reason">{sc > 0 ? "Scrap reason" : "Rework reason"}</label>
          <select id="fq-reason" className="select" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="floor-reason" required>
            <option value="">Choose…</option>
            {reasons.map((r) => (
              <option key={r.code} value={r.code}>
                {r.label}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {rw > 0 ? (
        <div className="field">
          <label htmlFor="fq-rwto">Rework at operation</label>
          <select id="fq-rwto" className="select" value={reworkTo} onChange={(e) => setReworkTo(Number(e.target.value))} data-testid="floor-rework-to">
            {(earlier.length ? earlier : [op]).map((o) => (
              <option key={o.seq} value={o.seq}>
                {o.seq} {o.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {capture ? (
        <div className="col" style={{ gap: 6 }} data-testid="floor-serials">
          <label htmlFor="fq-serial">
            <strong>Serial numbers</strong>{" "}
            <span className={serialsOk ? "badge ok" : "badge warn"} data-testid="floor-serial-count" data-count={serials.length}>
              <Icon name={serialsOk ? "check" : "alert"} /> {serials.length} of {g} scanned
            </span>
          </label>
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              if (addSerial(serialText)) setSerialText("");
            }}
          >
            <input id="fq-serial" className="input" style={{ flex: 1 }} value={serialText} onChange={(e) => setSerialText(e.target.value)} placeholder="Scan the unit label or type the serial, then Enter" autoComplete="off" data-testid="floor-serial-input" />
            <button type="submit" className="btn floor-btn">
              Add
            </button>
          </form>
          <div className="floor-serials">
            {serials.map((s) => (
              <span key={s} className="floor-serial" data-testid="floor-serial">
                {s}
                <button type="button" className="btn ghost icon" aria-label={`Remove serial ${s}`} onClick={() => setSerials(serials.filter((x) => x !== s))}>
                  <Icon name="x" />
                </button>
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {serialComps.length ? (
        <div className="col" style={{ gap: 4 }}>
          <strong>Serials of components fitted here</strong>
          <span className="faint small">Scan the child unit labels (S:part:serial). Optional.</span>
          <div className="floor-serials">
            {consumed.map((c) => (
              <span key={`${c.item_id}${c.serial}`} className="floor-serial">
                {serialComps.find((x) => x.item_id === c.item_id)?.part_number ?? ""}: {c.serial}
                <button type="button" className="btn ghost icon" aria-label={`Remove ${c.serial}`} onClick={() => setConsumed(consumed.filter((x) => x !== c))}>
                  <Icon name="x" />
                </button>
              </span>
            ))}
          </div>
        </div>
      ) : null}
      <div className="field">
        <label htmlFor="fq-note">Note (optional)</label>
        <input id="fq-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </div>
      {forceNeeded && canForce ? (
        <div className="field">
          <label htmlFor="fq-force">Record anyway (supervisor): reason</label>
          <input id="fq-force" className="input" value={forceReason} onChange={(e) => setForceReason(e.target.value)} data-testid="floor-force-reason" />
        </div>
      ) : null}
      <div className="row wrap">
        <button
          type="button"
          className="btn primary floor-action"
          disabled={busy || !qtyOk || (needReason && !reason) || !serialsOk || (forceNeeded && canForce && !forceReason)}
          onClick={() => void submit()}
          data-testid="floor-qty-submit"
        >
          <Icon name="check" /> {mode === "complete" ? "Complete" : "Report"}
          {g ? ` ${fmtQty(g)} good` : ""}
        </button>
        <button type="button" className="btn floor-btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {!serialsOk ? <span className="small">Scan one serial per good unit first.</span> : null}
    </section>
  );
}

function Components({ d }: { d: FloorOperationDetail }) {
  if (!d.components.length) return null;
  return (
    <section className="floor-card" data-testid="floor-components">
      <h2>Components</h2>
      <table className="floor-table">
        <thead>
          <tr>
            <th>Part</th>
            <th>Needed</th>
            <th>Issued</th>
            <th>How</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {d.components.map((c) => (
            <tr key={c.component_id} data-testid="floor-component" data-issue={c.backflush ? "backflush" : "manual"}>
              <td>
                <span className="mono">{c.item.part_number}</span>
                {c.item.description ? <div className="faint small">{c.item.description}</div> : null}
              </td>
              <td>{fmtQty(c.required_qty)}</td>
              <td>{fmtQty(c.issued_qty)}</td>
              <td>
                {c.backflush ? "Automatic (backflush)" : "From stores"}
                {c.backflush && c.location ? <div className="faint small">from {c.location.code}</div> : null}
              </td>
              <td>
                <KitChip kit={c.kit} />
                {c.backflush_pending ? <div className="small">{fmtQty(c.backflush_pending)} waiting for stock</div> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function EventList({ d, clock }: { d: FloorOperationDetail; clock: ReturnType<typeof usePlantClock> }) {
  if (!d.events.length) return null;
  const evs = [...d.events].sort((a, b) => b.seq - a.seq).slice(0, 20);
  return (
    <section className="floor-card" data-testid="floor-op-events">
      <h2>What happened</h2>
      <table className="floor-table">
        <tbody>
          {evs.map((e) => (
            <tr key={e.id} data-type={e.event_type}>
              <td className="mono">{clock.dateTime(e.event_at)}</td>
              <td>
                <strong>{EVENT_LABEL[e.event_type] ?? e.event_type}</strong>
                {e.qty_good ? ` · ${fmtQty(e.qty_good)} good` : ""}
                {e.qty_scrap ? ` · ${fmtQty(e.qty_scrap)} scrap` : ""}
                {e.qty_rework ? ` · ${fmtQty(e.qty_rework)} rework${e.rework_to_seq ? ` to ${e.rework_to_seq}` : ""}` : ""}
                {e.reason_code ? ` · ${humanCode(e.reason_code)}` : ""}
                {e.corrected ? <span className="faint"> (corrected)</span> : null}
              </td>
              <td className="small muted">{e.operators.map((o) => o.name || o.code).join(", ") || e.actor?.name || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
