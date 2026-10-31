/**
 * `/mfg/floor/events` (M4 12, #204): the append-only floor event log with filters. Supervisors correct an event
 * (a `correct` event that references it and replaces its quantities; the original stays visible) or reopen a
 * completed operation (reverses its automatic postings). Nothing is ever edited in place (decision 1).
 */
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Dialog } from "../../../components/Dialog";
import { Icon } from "../../../components/Icon";
import { listLines } from "../../api/client";
import { listFloorEvents, postFloorEvent } from "../../api/clientM4";
import type { FloorEventRecord, FloorEventType } from "../../api/typesM4";
import { MfgError } from "../../components/Feedback";
import { EVENT_LABEL, floorErrorText, fmtQty, humanCode } from "../../floor/floorText";
import { newClientEventId } from "../../floor/offlineQueue";
import { usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { useCan } from "../../lib/permissions";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";

const TYPES = Object.keys(EVENT_LABEL) as FloorEventType[];

export function FloorEvents() {
  const clock = usePlantClock();
  const canSupervise = useCan("floor_supervise");
  const [params, setParams] = useSearchParams();
  const line = params.get("line") ?? "";
  const type = params.get("type") ?? "";
  const wo = params.get("wo") ?? "";
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const set = (k: string, v: string) => setSearchParam(setParams, k, v);
  const lines = useLoad((signal) => listLines({}, signal), []);
  const data = usePaged<FloorEventRecord>(
    (offset, limit, signal) =>
      listFloorEvents({ line_id: line || undefined, type: type || undefined, wo_id: wo || undefined, from: from ? clock.fromLocal(`${from}T00:00`) : undefined, to: to ? clock.fromLocal(`${to}T23:59`) : undefined, limit, offset }, signal),
    [line, type, wo, from, to],
  );
  const [correcting, setCorrecting] = useState<FloorEventRecord | null>(null);
  const [reopening, setReopening] = useState<FloorEventRecord | null>(null);

  return (
    <div className="col gap-lg" data-testid="floor-events">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>Floor event log</h1>
        <Link className="btn" to={mfgPaths.floorOverview()}>
          Shop floor overview
        </Link>
      </div>
      <div className="toolbar mfg-filters" role="search">
        <div className="field">
          <label htmlFor="fe-line">Line</label>
          <select id="fe-line" className="select" value={line} onChange={(e) => set("line", e.target.value)}>
            <option value="">All lines</option>
            {(lines.data?.items ?? []).map((l) => (
              <option key={l.id} value={l.id}>
                {l.code}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="fe-type">Event</label>
          <select id="fe-type" className="select" value={type} onChange={(e) => set("type", e.target.value)}>
            <option value="">All events</option>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {EVENT_LABEL[t]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="fe-from">From</label>
          <input id="fe-from" className="input" type="date" value={from} onChange={(e) => set("from", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="fe-to">To</label>
          <input id="fe-to" className="input" type="date" value={to} onChange={(e) => set("to", e.target.value)} />
        </div>
        {wo ? (
          <button type="button" className="btn ghost" style={{ alignSelf: "flex-end" }} onClick={() => set("wo", "")}>
            <Icon name="x" /> Work order filter
          </button>
        ) : null}
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="floor-event-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Work order / step</th>
              <th>Event</th>
              <th>Quantities</th>
              <th>Line</th>
              <th>Who</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="muted">
                  {data.loading ? "Loading…" : "No events."}
                </td>
              </tr>
            ) : null}
            {data.rows.map((e) => (
              <tr key={e.id} data-testid="floor-event-row" data-type={e.event_type} className={e.corrected ? "faint" : undefined}>
                <td className="small">
                  {clock.dateTime(e.event_at)}
                  {Math.abs(Date.parse(e.recorded_at) - Date.parse(e.event_at)) > 5 * 60000 ? <div className="faint">recorded {clock.dateTime(e.recorded_at)}</div> : null}
                </td>
                <td>
                  <Link to={mfgPaths.workOrder(e.wo_id)} className="mono">
                    {e.wo_number ?? e.wo_id}
                  </Link>
                  {e.op_seq ? ` / ${e.op_seq}` : ""}
                </td>
                <td>
                  {EVENT_LABEL[e.event_type] ?? e.event_type}
                  {e.corrects_event_id ? <div className="faint small">corrects an earlier event</div> : null}
                  {e.corrected ? (
                    <div className="small">
                      <Icon name="refresh" size={12} /> corrected later
                    </div>
                  ) : null}
                  {e.reason_code ? <div className="faint small">reason: {humanCode(e.reason_code)}</div> : null}
                  {e.note ? <div className="faint small">{e.note}</div> : null}
                </td>
                <td className="small">
                  {e.qty_good !== null ? `${fmtQty(e.qty_good)} good ` : ""}
                  {e.qty_scrap ? `${fmtQty(e.qty_scrap)} scrap ` : ""}
                  {e.qty_rework ? `${fmtQty(e.qty_rework)} rework${e.rework_to_seq ? ` to ${e.rework_to_seq}` : ""}` : ""}
                  {e.serials?.produced?.length ? <div className="faint">{e.serials.produced.length} serials</div> : null}
                </td>
                <td className="small">{e.line?.code ?? ""}</td>
                <td className="small">
                  {e.operators.map((o) => o.name || o.code).join(", ")}
                  {e.actor?.name && !e.operators.some((o) => o.name === e.actor?.name) ? <div className="faint">by {e.actor.name}</div> : null}
                  {e.forced ? <div className="small">forced: {e.forced.reason}</div> : null}
                </td>
                <td>
                  {canSupervise && !e.corrected && ["report", "complete", "correct"].includes(e.event_type) ? (
                    <button type="button" className="btn sm" onClick={() => setCorrecting(e)} data-testid="event-correct">
                      Correct
                    </button>
                  ) : null}
                  {canSupervise && e.event_type === "complete" && !e.corrected ? (
                    <button type="button" className="btn sm ghost" onClick={() => setReopening(e)} data-testid="event-reopen">
                      Reopen
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.rows.length < data.total ? (
          <div className="card-footer">
            <button type="button" className="btn sm" onClick={data.onEndReached} disabled={data.loading}>
              Show more ({data.rows.length} of {data.total})
            </button>
          </div>
        ) : null}
      </div>
      {correcting ? (
        <CorrectDialog
          ev={correcting}
          onClose={() => setCorrecting(null)}
          onDone={() => {
            setCorrecting(null);
            data.reload();
          }}
        />
      ) : null}
      {reopening ? (
        <ReasonDialog
          title="Reopen this operation?"
          text="Its completion postings (receipt, backflush) are reversed and the operation goes back to paused."
          confirm="Reopen"
          onClose={() => setReopening(null)}
          onConfirm={async (reason) => {
            await postFloorEvent({ client_event_id: newClientEventId(), wo_operation_id: reopening.wo_operation_id, event_type: "reopen", note: reason, reason_code: "supervisor" });
            setReopening(null);
            data.reload();
          }}
        />
      ) : null}
    </div>
  );
}

function CorrectDialog({ ev, onClose, onDone }: { ev: FloorEventRecord; onClose(): void; onDone(): void }) {
  const [good, setGood] = useState(String(ev.qty_good ?? ""));
  const [scrap, setScrap] = useState(String(ev.qty_scrap ?? ""));
  const [rework, setRework] = useState(String(ev.qty_rework ?? ""));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      await postFloorEvent({
        client_event_id: newClientEventId(),
        wo_operation_id: ev.wo_operation_id,
        event_type: "correct",
        corrects_event_id: ev.id,
        qty_good: Number(good) || 0,
        qty_scrap: Number(scrap) || 0,
        qty_rework: Number(rework) || 0,
        note,
      });
      onDone();
    } catch (e) {
      setError(floorErrorText(e));
      setBusy(false);
    }
  };
  return (
    <Dialog
      title="Correct the event"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn primary" disabled={busy || !note.trim()} onClick={() => void go()} data-testid="correct-submit">
            Record correction
          </button>
        </>
      }
    >
      <p className="muted" style={{ marginTop: 0 }}>
        The original event stays in the log; the correction replaces its quantities. Stock postings follow.
      </p>
      <div className="grid-3">
        <div className="field">
          <label htmlFor="cr-good">Good</label>
          <input id="cr-good" className="input" inputMode="decimal" value={good} onChange={(e) => setGood(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="cr-scrap">Scrap</label>
          <input id="cr-scrap" className="input" inputMode="decimal" value={scrap} onChange={(e) => setScrap(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="cr-rework">Rework</label>
          <input id="cr-rework" className="input" inputMode="decimal" value={rework} onChange={(e) => setRework(e.target.value)} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="cr-note">Why (required)</label>
        <input id="cr-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </div>
      {error ? <div className="banner danger">{error}</div> : null}
    </Dialog>
  );
}

export function ReasonDialog({ title, text, confirm, onClose, onConfirm }: { title: string; text: string; confirm: string; onClose(): void; onConfirm(reason: string): Promise<void> }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || !reason.trim()}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onConfirm(reason.trim());
              } catch (e) {
                setError(floorErrorText(e));
                setBusy(false);
              }
            }}
            data-testid="reason-confirm"
          >
            {confirm}
          </button>
        </>
      }
    >
      <p style={{ marginTop: 0 }}>{text}</p>
      <div className="field">
        <label htmlFor="rd-reason">Reason (required)</label>
        <input id="rd-reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
      </div>
      {error ? <div className="banner danger">{error}</div> : null}
    </Dialog>
  );
}
