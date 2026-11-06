/**
 * `/m/lines` and `/m/lines/:lineId` (M6 2): line status (running / paused / down / idle as icon + text), the
 * current and next operations, and open downtime with **Acknowledge** ("I have seen it", M4 endpoint of M6) and
 * **Close** (line back up). Both go through the M4 offline queue: offline they wait and are sent once.
 */
import { useState } from "react";
import { Link, useParams } from "react-router";
import { Icon, type IconName } from "../../components/Icon";
import { getFloorQueue, listDowntime } from "../api/clientM4";
import type { DowntimeM6 } from "../api/typesM6";
import { MfgError, Spinner } from "../components/Feedback";
import { DOWNTIME, OpStatusChip } from "../floor/floorText";
import { pendingIds, submitDowntimeAck, submitDowntimeUpdate, useFloorQueue } from "../floor/offlineQueue";
import { floorErrorText } from "../floor/floorText";
import { useCan } from "../lib/permissions";
import { usePolling } from "../lib/usePolling";
import { useLoad } from "../lib/useMfg";
import { loadLines, lineState, type LineState } from "./glance";
import { useOnline } from "./MobileLayout";

export const LINE_STATE: Record<LineState, { label: string; icon: IconName; tone: string }> = {
  running: { label: "Running", icon: "play", tone: "ok" },
  paused: { label: "Paused", icon: "stop", tone: "warn" },
  down: { label: "Down", icon: "alert", tone: "danger" },
  idle: { label: "Idle", icon: "circle", tone: "info" },
};

export function LineStateBadge({ state }: { state: LineState }) {
  const s = LINE_STATE[state];
  return (
    <span className={`badge ${s.tone}`} data-testid="m-line-state" data-state={state}>
      <Icon name={s.icon} /> {s.label}
    </span>
  );
}

export function MobileLines() {
  const online = useOnline();
  const lines = useLoad((signal) => loadLines(null, signal), [online]);
  usePolling(lines.reload, online, 30000);
  return (
    <div className="col" style={{ gap: 12 }} data-testid="m-lines">
      <h1>Lines</h1>
      {lines.error && !lines.data ? <MfgError error={lines.error} onRetry={lines.reload} /> : null}
      {lines.loading && !lines.data ? <Spinner /> : null}
      {lines.data && !lines.data.length ? <p className="muted">No active lines.</p> : null}
      <ul className="m-list">
        {(lines.data ?? []).map((l) => (
          <li key={l.id}>
            <Link to={`/m/lines/${encodeURIComponent(l.id)}`} className="m-row" data-testid="m-line-row" data-state={l.state}>
              <div className="grow">
                <strong>{l.code}</strong> <span className="muted">{l.name}</span>
                <div className="m-sub">{l.state === "down" && l.downtime ? `${DOWNTIME[l.downtime.kind]?.label ?? l.downtime.kind}${l.downtime.reason ? `: ${l.downtime.reason}` : ""}` : l.current ?? "Nothing running"}</div>
              </div>
              <LineStateBadge state={l.state} />
              <Icon name="chevron-right" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DowntimeCard({ d, onChanged }: { d: DowntimeM6; onChanged(): void }) {
  const canSee = useCan("floor_view");
  const canClose = useCan("downtime_report");
  const q = useFloorQueue();
  const ackWaiting = pendingIds("downtime_ack").has(d.id);
  const closeWaiting = q.pending.some((a) => a.kind === "downtime_update" && a.downtimeId === d.id);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; tone: "ok" | "danger" } | null>(null);
  const kind = DOWNTIME[d.kind] ?? { label: d.kind, icon: "alert" as IconName };
  const run = async (what: "ack" | "close") => {
    setBusy(what);
    setMsg(null);
    try {
      const out =
        what === "ack"
          ? await submitDowntimeAck(d.id, `${d.line.code}: downtime acknowledged`)
          : await submitDowntimeUpdate(d.id, d.row_version, { close: true }, `${d.line.code} back up`);
      setMsg(out.status === "queued" ? { text: "Saved on this phone; it is sent when you are back online.", tone: "ok" } : { text: what === "ack" ? "Acknowledged." : "Downtime closed.", tone: "ok" });
      onChanged();
    } catch (e) {
      setMsg({ text: floorErrorText(e), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };
  return (
    <section className="m-card" data-testid="m-downtime" aria-label="Open downtime">
      <h2>
        <Icon name={kind.icon} /> Down: {kind.label}
      </h2>
      <dl className="m-dl">
        <dt>Since</dt>
        <dd>{new Date(d.start_at).toLocaleString()}</dd>
        {d.expected_end_at ? (
          <>
            <dt>Expected back</dt>
            <dd>{new Date(d.expected_end_at).toLocaleString()}</dd>
          </>
        ) : null}
        {d.reason ? (
          <>
            <dt>Reason</dt>
            <dd>{d.reason}</dd>
          </>
        ) : null}
        {d.reported_by ? (
          <>
            <dt>Reported by</dt>
            <dd>{d.reported_by.name ?? d.reported_by.code}</dd>
          </>
        ) : null}
        <dt>Seen by</dt>
        <dd data-testid="m-downtime-ack">
          {d.acknowledged_at ? (
            <span className="m-state">
              <Icon name="check" size={14} /> {d.acknowledged_by?.name ?? "someone"}, {new Date(d.acknowledged_at).toLocaleTimeString()}
            </span>
          ) : ackWaiting ? (
            <span className="m-state">
              <Icon name="clock" size={14} /> You (waiting to sync)
            </span>
          ) : (
            <span className="m-state">
              <Icon name="circle" size={14} /> Not yet acknowledged
            </span>
          )}
        </dd>
      </dl>
      <div className="m-actions">
        {!d.acknowledged_at && !ackWaiting ? (
          <button type="button" className="btn primary" disabled={!canSee || busy !== null} onClick={() => void run("ack")} data-testid="m-downtime-ack-btn">
            {busy === "ack" ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Acknowledge
          </button>
        ) : null}
        {canClose && !closeWaiting ? (
          <button type="button" className="btn" disabled={busy !== null} onClick={() => void run("close")} data-testid="m-downtime-close">
            {busy === "close" ? <span className="spinner" aria-hidden /> : <Icon name="play" />} Line is back up
          </button>
        ) : null}
        {closeWaiting ? (
          <span className="m-state">
            <Icon name="clock" size={14} /> Close waiting to sync
          </span>
        ) : null}
      </div>
      {msg ? (
        <p className={msg.tone === "danger" ? "field-error" : "small"} role={msg.tone === "danger" ? "alert" : "status"} data-testid="m-downtime-msg" style={{ margin: 0 }}>
          {msg.text}
        </p>
      ) : null}
    </section>
  );
}

export function MobileLine() {
  const { lineId = "" } = useParams();
  const online = useOnline();
  const q = useLoad((signal) => getFloorQueue({ line_id: lineId }, signal), [lineId, online]);
  const down = useLoad((signal) => listDowntime({ line_id: lineId, open: true, limit: 5 }, signal), [lineId, online]);
  usePolling(() => {
    q.reload();
    down.reload();
  }, online, 30000);
  const d = (down.data?.items[0] ?? q.data?.down ?? null) as DowntimeM6 | null;
  const st = q.data ? lineState(q.data, d) : null;
  const open = (q.data?.items ?? []).filter((r) => r.status !== "completed" && r.status !== "skipped");
  return (
    <div className="col" style={{ gap: 12 }} data-testid="m-line">
      <Link to="/m/lines" className="small">
        <Icon name="chevron-right" size={12} style={{ transform: "rotate(180deg)" }} /> All lines
      </Link>
      <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
        <h1>{q.data?.line.code ?? "Line"}</h1>
        {st ? <LineStateBadge state={st.state} /> : null}
      </div>
      {q.error && !q.data ? <MfgError error={q.error} onRetry={q.reload} /> : null}
      {q.loading && !q.data ? <Spinner /> : null}
      {d && d.open !== false ? <DowntimeCard d={d} onChanged={() => down.reload()} /> : null}
      {q.data ? (
        <section className="m-card" aria-labelledby="m-ops-h">
          <h2 id="m-ops-h">Current and next operations</h2>
          {open.length === 0 ? <p className="muted" style={{ margin: 0 }}>Nothing planned for this shift.</p> : null}
          <ul className="m-list">
            {open.slice(0, 6).map((r, i) => (
              <li key={r.wo_operation_id ?? `${r.wo.id}-${r.seq}`}>
                <Link to={`/m/wo/${encodeURIComponent(r.wo.id)}`} className="m-row" data-testid="m-op-row">
                  <div className="grow">
                    <strong>{r.wo.number}</strong> op {r.seq} {r.name}
                    <div className="m-sub">
                      {i === 0 ? "Now · " : ""}
                      {r.wo.item.part_number} · {r.qty_good}/{r.qty_planned}
                      {r.planned_start ? ` · planned ${new Date(r.planned_start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}
                    </div>
                  </div>
                  <OpStatusChip status={r.status} />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
