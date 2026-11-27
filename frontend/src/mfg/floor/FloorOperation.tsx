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
import { getQaSettings } from "../api/clientM7";
import type { FloorEventInput, FloorEventResult, FloorEventType, FloorOperationDetail, WoOperation } from "../api/typesM4";
import { MfgError, Spinner } from "../components/Feedback";
import { fmtDuration, usePlantClock } from "../lib/plantTime";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { crewForEvent, useFloor, useScanHandler } from "./FloorLayout";
import { IssueLotPanel } from "./IssueLotPanel";
import { ACTION, DEFAULT_REASONS, EVENT_LABEL, KitChip, OpStatusChip, floorErrorText, fmtQty, humanCode } from "./floorText";
import { newClientEventId, submitFloorEvent } from "./offlineQueue";
import { t, t as tr } from "../../lib/i18n";

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
  const [issuing, setIssuing] = useState(false);
  const op = d?.operation;
  /** M7 5.2: the inspection lot of an inspection-gate operation, when the server sends it */
  const gate = (d as (FloorOperationDetail & { inspection_lot?: { id: string; number: string; status: string } | null }) | null)?.inspection_lot ?? null;

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
        floor.flash(tr("floor.floorOperation.str.savedOnThisTabletIt"), "warn");
      } else {
        setLastResult(out.result);
        const posted = out.result.postings.length ? tr("floor.floorOperation.tpl.stockPosting", { length: out.result.postings.length, v: out.result.postings.length === 1 ? "" : "s" }) : "";
        floor.flash(`${EVENT_LABEL[type]}${posted}${out.result.replayed ? tr("floor.floorOperation.str.alreadyRecorded") : ""}`);
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

  if (det.loading && !d) return <Spinner label={t("floor.floorOperation.label.loadingTheOperation")} />;
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
                  <Icon name="chevron-right" style={{ transform: "rotate(180deg)" }} /> {t("floor.floorOperation.btn.queue")}
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
          <dt>{t("floor.floorOperation.head.inputHere")}</dt>
          <dd>
            {fmtQty(op.qty_input || d.expected_input)} {op.qty_rework_in ? `(incl. ${fmtQty(op.qty_rework_in)} rework)` : ""}
          </dd>
          <dt>{t("floor.floorOperation.head.doneSoFar")}</dt>
          <dd data-testid="floor-op-good" data-good={op.qty_good} data-scrap={op.qty_scrap}>
            {tr("floor.floorOperation.text.goodScrapToGo", { qtygood: fmtQty(op.qty_good), qtyscrap: fmtQty(op.qty_scrap), v: op.qty_rework_out ? tr("floor.floorOperation.tpl.sentToRework", { qtyreworkout: fmtQty(op.qty_rework_out) }) : "", remaining: fmtQty(remaining) })}
          </dd>
          {op.actual_start ? (
            <>
              <dt>{t("floor.floorOperation.head.started")}</dt>
              <dd>
                {clock.dateTime(op.actual_start)}
                {op.run_minutes_actual ? ` · run ${fmtDuration(op.run_minutes_actual)}` : ""}
                {op.setup_minutes_actual ? ` · setup ${fmtDuration(op.setup_minutes_actual)}` : ""}
              </dd>
            </>
          ) : null}
          {plan ? (
            <>
              <dt>{t("floor.floorOperation.head.plan")}</dt>
              <dd>
                {plan.line?.code ? `${plan.line.code} · ` : ""}
                {clock.dateTime(plan.start)} – {clock.time(plan.end)}
              </dd>
            </>
          ) : null}
        </dl>
        {op.started_short ? (
          <div className="badge warn">
            <Icon name="alert" /> {t("floor.floorOperation.btn.startedWithMaterialShort")}
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
              <label htmlFor="fo-line">{t("floor.floorOperation.label.line")}</label>
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
              <Icon name="alert" /> {t("floor.floorOperation.btn.thisLineIsReportedDown")}
            </div>
          ) : null}
          {!floor.crew.length && !floor.me ? (
            <div className="faint">{tr("floor.floorOperation.text.noOperatorSignedInOn")}</div>
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
            {allowed.length === 0 ? <span className="muted">{tr("floor.floorOperation.text.noActionIsPossibleIn")}</span> : null}
            {d.components.some((c) => !c.backflush) && op && op.status !== "completed" && op.status !== "skipped" ? (
              <button type="button" className={`btn floor-action${issuing ? " active" : ""}`} aria-pressed={issuing} onClick={() => setIssuing((v) => !v)} data-testid="floor-action-issue-lot">
                <Icon name="box" size={22} /> {tr("plan.fi.title")}
              </button>
            ) : null}
          </div>
          <details>
            <summary className="muted">{t("floor.floorOperation.head.itHappenedEarlierUpTo")}</summary>
            <div className="field" style={{ maxWidth: 320 }}>
              <label htmlFor="fo-at">{t("floor.floorOperation.label.when")}</label>
              <input id="fo-at" className="input" type="datetime-local" value={eventAt} onChange={(e) => setEventAt(e.target.value)} max={clock.toLocal(new Date().toISOString())} />
            </div>
          </details>
        </section>
      ) : (
        <div className="floor-card muted">{tr("floor.floorOperation.text.yourRoleCanSeeThe")}</div>
      )}

      {issuing ? <IssueLotPanel d={d} onCancel={() => setIssuing(false)} onDone={() => {
        setIssuing(false);
        det.reload();
      }} /> : null}
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

      {lastResult?.ncr ? (
        <section className="floor-card" data-testid="floor-ncr">
          <span className="badge warn">
            <Icon name="alert" /> {tr("qa.floor.tpl.ncr", { n: lastResult.ncr.number })}
          </span>
        </section>
      ) : null}
      {gate ? (
        <section className="floor-card" data-testid="floor-gate" data-status={gate.status}>
          <h2>{tr("qa.floor.head.gate")}</h2>
          <p style={{ margin: 0 }}>{gate.status === "accepted" ? tr("qa.floor.text.gateOk", { n: gate.number }) : tr("qa.floor.text.gateOpen", { n: gate.number })}</p>
          {gate.status !== "accepted" && gate.status !== "rejected" && gate.status !== "cancelled" ? (
            <Link className="btn primary floor-action" to={mfgPaths.floorInspect(gate.id)}>
              <Icon name="eye" /> {tr("qa.floor.btn.inspect")}
            </Link>
          ) : null}
        </section>
      ) : null}

      <Components d={d} />
      {d.instructions ? (
        <section className="floor-card">
          <h2>{t("floor.floorOperation.head.instructions")}</h2>
          <div style={{ whiteSpace: "pre-wrap" }}>{d.instructions}</div>
        </section>
      ) : null}
      {d.tools.length ? (
        <section className="floor-card">
          <h2>{t("floor.floorOperation.head.tools")}</h2>
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
      <span className="muted">{tr("floor.floorOperation.text.checkTheCountsASupervisor")}</span>
    </div>
  );
}

function PausePanel({ d, busy, onCancel, onSubmit }: { d: FloorOperationDetail; busy: boolean; onCancel(): void; onSubmit(reason: string, note: string): void }) {
  const reasons = d.reason_codes?.pause?.length ? d.reason_codes.pause : DEFAULT_REASONS.pause;
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  return (
    <section className="floor-card" aria-label={t("floor.floorOperation.aria.pause")}>
      <h2>{t("floor.floorOperation.head.whyAreYouPausing")}</h2>
      <div className="floor-grid" role="radiogroup" aria-label={t("floor.floorOperation.aria.pauseReason")} data-testid="floor-reason">
        {reasons.map((r) => (
          <button key={r.code} type="button" role="radio" aria-checked={reason === r.code} className={`floor-tile${reason === r.code ? " active" : ""}`} onClick={() => setReason(r.code)} data-code={r.code}>
            {r.label}
          </button>
        ))}
      </div>
      <div className="field">
        <label htmlFor="fp-note">{t("floor.floorOperation.label.noteOptional")}</label>
        <input id="fp-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </div>
      <div className="row wrap">
        <button type="button" className="btn primary floor-action" disabled={!reason || busy} onClick={() => onSubmit(reason, note)} data-testid="floor-pause-submit">
          <Icon name="stop" /> {t("floor.floorOperation.btn.pauseNow")}
        </button>
        <button type="button" className="btn floor-btn" onClick={onCancel}>
          {t("floor.floorOperation.btn.cancel")}
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
        <button type="button" className="btn" aria-label={tr("floor.floorOperation.tpl.minusOne", { label: label })} onClick={() => onChange(String(Math.max(0, n - 1)))}>
          −
        </button>
        <input id={id} className="input" inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value.replace(/[^0-9.]/g, ""))} data-testid={testId} aria-describedby={max !== undefined ? `${id}-max` : undefined} />
        <button type="button" className="btn" aria-label={tr("floor.floorOperation.tpl.plusOne", { label: label })} onClick={() => onChange(String(n + 1))}>
          +
        </button>
      </div>
      {max !== undefined ? (
        <span id={`${id}-max`} className="faint small">
          {tr("floor.floorOperation.text.stillToGo", { max: fmtQty(max) })}
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
  const [nc, setNc] = useState("");
  const [defect, setDefect] = useState("");
  const qaSettings = useLoad((signal) => getQaSettings(signal).catch(() => null), []);
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
  const ncq = Number(nc) || 0;
  const defectCodes = qaSettings.data?.defect_codes ?? [];
  const needReason = sc > 0 || rw > 0;
  const reasons = (sc > 0 ? d.reason_codes?.scrap : d.reason_codes?.rework) ?? (sc > 0 ? DEFAULT_REASONS.scrap : DEFAULT_REASONS.rework);
  const ops = useLoad((signal) => (rw > 0 ? listWoOperationsM4(d.wo.id, signal) : null), [d.wo.id, rw > 0]);
  const earlier: WoOperation[] = (ops.data?.items ?? []).filter((o) => o.seq <= op.seq);
  const serialsOk = !capture || g === 0 || serials.length === g;
  const qtyOk = (g + sc + rw + ncq > 0 || mode === "complete") && (ncq === 0 || Boolean(defect) || !defectCodes.length);

  const addSerial = (raw: string) => {
    let s = raw.trim();
    const m = /^S:([^:]+):(.+)$/i.exec(s);
    if (m) {
      if (m[1].toUpperCase() !== d.wo.item.part_number.toUpperCase()) {
        // a child's serial: consumed by this operation
        const comp = serialComps.find((c) => c.part_number.toUpperCase() === m[1].toUpperCase());
        if (comp) {
          if (!consumed.some((x) => x.item_id === comp.item_id && x.serial === m[2])) setConsumed([...consumed, { item_id: comp.item_id, serial: m[2] }]);
          floor.flash(tr("floor.floorOperation.tpl.consumedSerial", { partnumber: comp.part_number, v: m[2] }));
          return true;
        }
        floor.flash(tr("floor.floorOperation.tpl.serialOfDoesNotBelong", { v: m[1] }), "danger");
        return true;
      }
      s = m[2];
    }
    if (!s) return false;
    if (serials.includes(s)) {
      floor.flash(tr("floor.floorOperation.tpl.serialIsAlreadyInThe", { s: s }), "warn");
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
      ...(ncq ? { qty_nc: ncq, ...(defect ? { defect_code: defect } : {}) } : {}),
      ...(needReason ? { reason_code: reason } : {}),
      ...(note ? { note } : {}),
      ...(capture && serials.length ? { serials: { produced: serials, ...(consumed.length ? { consumed } : {}) } } : consumed.length ? { serials: { consumed } } : {}),
      ...(forceNeeded && forceReason ? { force: { reason: forceReason } } : {}),
    };
    await onSubmit(extra);
  };

  return (
    <section className="floor-card" aria-label={mode === "complete" ? tr("floor.floorOperation.str.complete") : tr("floor.floorOperation.str.reportQuantity")} data-testid="floor-qty-panel">
      <h2>{mode === "complete" ? tr("floor.floorOperation.str.completeTheOperation") : tr("floor.floorOperation.str.reportAQuantity")}</h2>
      <div className="floor-qty">
        <Stepper id="fq-good" label={t("floor.floorOperation.label.good")} value={good} onChange={setGood} testId="floor-qty-good" max={remaining} />
        <Stepper id="fq-scrap" label={t("floor.floorOperation.label.scrap")} value={scrap} onChange={setScrap} testId="floor-qty-scrap" />
        <Stepper id="fq-rework" label={t("floor.floorOperation.label.rework")} value={rework} onChange={setRework} testId="floor-qty-rework" />
        <Stepper id="fq-nc" label={tr("qa.floor.label.nc")} value={nc} onChange={setNc} testId="floor-qty-nc" />
      </div>
      {ncq > 0 ? (
        <div className="field">
          <label htmlFor="fq-defect">{tr("qa.floor.label.defect")}</label>
          <select id="fq-defect" className="select" value={defect} onChange={(e) => setDefect(e.target.value)} data-testid="floor-defect-code" required={defectCodes.length > 0}>
            <option value="">{tr("floor.floorOperation.text.choose")}</option>
            {defectCodes.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} {c.name}
              </option>
            ))}
          </select>
          <span className="hint">{tr("qa.floor.hint.nc")}</span>
        </div>
      ) : null}
      {needReason ? (
        <div className="field">
          <label htmlFor="fq-reason">{sc > 0 ? tr("floor.floorOperation.str.scrapReason") : tr("floor.floorOperation.str.reworkReason")}</label>
          <select id="fq-reason" className="select" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="floor-reason" required>
            <option value="">{tr("floor.floorOperation.text.choose")}</option>
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
          <label htmlFor="fq-rwto">{t("floor.floorOperation.label.reworkAtOperation")}</label>
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
            <strong>{tr("floor.floorOperation.text.serialNumbers")}</strong>{" "}
            <span className={serialsOk ? "badge ok" : "badge warn"} data-testid="floor-serial-count" data-count={serials.length}>
              <Icon name={serialsOk ? "check" : "alert"} /> {tr("common.nOfM", { n: serials.length, m: g })} scanned
            </span>
          </label>
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              if (addSerial(serialText)) setSerialText("");
            }}
          >
            <input id="fq-serial" className="input" style={{ flex: 1 }} value={serialText} onChange={(e) => setSerialText(e.target.value)} placeholder={t("floor.floorOperation.ph.scanTheUnitLabelOr")} autoComplete="off" data-testid="floor-serial-input" />
            <button type="submit" className="btn floor-btn">
              {t("floor.floorOperation.btn.add")}
            </button>
          </form>
          <div className="floor-serials">
            {serials.map((s) => (
              <span key={s} className="floor-serial" data-testid="floor-serial">
                {s}
                <button type="button" className="btn ghost icon" aria-label={tr("floor.floorOperation.tpl.removeSerial", { s: s })} onClick={() => setSerials(serials.filter((x) => x !== s))}>
                  <Icon name="x" />
                </button>
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {serialComps.length ? (
        <div className="col" style={{ gap: 4 }}>
          <strong>{t("floor.floorOperation.head.serialsOfComponentsFittedHere")}</strong>
          <span className="faint small">{tr("floor.floorOperation.text.scanTheChildUnitLabels")}</span>
          <div className="floor-serials">
            {consumed.map((c) => (
              <span key={`${c.item_id}${c.serial}`} className="floor-serial">
                {serialComps.find((x) => x.item_id === c.item_id)?.part_number ?? ""}: {c.serial}
                <button type="button" className="btn ghost icon" aria-label={tr("floor.floorOperation.tpl.remove", { serial: c.serial })} onClick={() => setConsumed(consumed.filter((x) => x !== c))}>
                  <Icon name="x" />
                </button>
              </span>
            ))}
          </div>
        </div>
      ) : null}
      <div className="field">
        <label htmlFor="fq-note">{t("floor.floorOperation.label.noteOptional")}</label>
        <input id="fq-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </div>
      {forceNeeded && canForce ? (
        <div className="field">
          <label htmlFor="fq-force">{t("floor.floorOperation.label.recordAnywaySupervisorReason")}</label>
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
          <Icon name="check" /> {mode === "complete" ? tr("floor.floorOperation.str.complete") : tr("floor.floorOperation.str.report")}
          {g ? ` ${fmtQty(g)} good` : ""}
        </button>
        <button type="button" className="btn floor-btn" onClick={onCancel}>
          {t("floor.floorOperation.btn.cancel")}
        </button>
      </div>
      {!serialsOk ? <span className="small">{tr("floor.floorOperation.text.scanOneSerialPerGood")}</span> : null}
    </section>
  );
}

function Components({ d }: { d: FloorOperationDetail }) {
  if (!d.components.length) return null;
  return (
    <section className="floor-card" data-testid="floor-components">
      <h2>{t("floor.floorOperation.head.components")}</h2>
      <table className="floor-table">
        <thead>
          <tr>
            <th>{t("floor.floorOperation.head.part")}</th>
            <th>{t("floor.floorOperation.head.needed")}</th>
            <th>{t("floor.floorOperation.head.issued")}</th>
            <th>{t("floor.floorOperation.head.how")}</th>
            <th>{t("floor.floorOperation.head.status")}</th>
          </tr>
        </thead>
        <tbody>
          {d.components.map((c) => (
            <tr key={c.component_id} data-testid="floor-component" data-issue={c.backflush ? "backflush" : "manual"}>
              <td>
                <span className="mono">{c.item.part_number}</span>
                {c.item.description ? <div className="faint small">{c.item.description}</div> : null}
              </td>
              <td>{fmtQty(c.required_qty, (c.item as { uom?: string }).uom)}</td>
              <td>{fmtQty(c.issued_qty, (c.item as { uom?: string }).uom)}</td>
              <td>
                {c.backflush ? tr("floor.floorOperation.str.automaticBackflush") : tr("floor.floorOperation.str.fromStores")}
                {c.backflush && c.location ? <div className="faint small">{tr("floor.floorOperation.text.from", { code: c.location.code })}</div> : null}
              </td>
              <td>
                <KitChip kit={c.kit} />
                {c.backflush_pending ? <div className="small">{tr("floor.floorOperation.text.waitingForStock", { backflushpending: fmtQty(c.backflush_pending) })}</div> : null}
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
      <h2>{t("floor.floorOperation.head.whatHappened")}</h2>
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
