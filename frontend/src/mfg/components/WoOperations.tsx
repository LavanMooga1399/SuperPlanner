/**
 * Work-order operations.
 * - M4 (#206, full records): status (icon + text), good / scrap / rework, line, actual vs planned times, "Open on
 *   the floor", the traveller, the event log; supervisors get "Done" (complete with the available input, #177) and
 *   "Skip" (with a reason); planners can re-derive the operations while nothing was recorded (#207).
 * - M3 servers (#176 `done` markers): mark done / reopen as before.
 */
import { useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import { getWoOperations, setWoOperationDone } from "../api/clientM3";
import { postFloorEvent, refreshWoOperations } from "../api/clientM4";
import type { WoOperationRow } from "../api/typesM3";
import type { WoOperation } from "../api/typesM4";
import { OpStatusChip, floorErrorText, fmtQty } from "../floor/floorText";
import { newClientEventId } from "../floor/offlineQueue";
import { ReasonDialog } from "../pages/m4/FloorEvents";
import { fmtDuration, usePlantClock } from "../lib/plantTime";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { isNotFound, useLoad } from "../lib/useMfg";
import { MfgError } from "./Feedback";

type AnyOp = WoOperationRow | WoOperation;
const isM4 = (o: AnyOp): o is WoOperation => "status" in o;

export function WoOperations({ woId, woVersion, onChanged }: { woId: string; woVersion: number; onChanged(): void }) {
  const ops = useLoad((signal) => getWoOperations(woId, signal) as Promise<{ wo_id?: string; row_version?: number; wo?: { row_version?: number }; items: AnyOp[] }>, [woId, woVersion]);
  if (ops.error && isNotFound(ops.error)) return null; // server without M3
  const items = ops.data?.items ?? [];
  if (items.length && isM4(items[0])) return <M4Ops woId={woId} woVersion={ops.data?.wo?.row_version ?? ops.data?.row_version ?? woVersion} items={items as WoOperation[]} reload={ops.reload} onChanged={onChanged} />;
  return <M3Ops woId={woId} woVersion={woVersion} ops={ops} onChanged={onChanged} />;
}

function M4Ops({ woId, woVersion, items, reload, onChanged }: { woId: string; woVersion: number; items: WoOperation[]; reload(): void; onChanged(): void }) {
  const clock = usePlantClock();
  const canSupervise = useCan("floor_supervise");
  const canEdit = useCan("wo_edit");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [skipping, setSkipping] = useState<WoOperation | null>(null);
  const notReleased = items.every((o) => !o.id);
  const anyRecorded = items.some((o) => o.actual_start || o.status === "completed" || o.status === "skipped" || o.qty_good || o.qty_scrap);
  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      reload();
      onChanged();
    } catch (e) {
      setError(floorErrorText(e));
    } finally {
      setBusy(null);
    }
  };
  return (
    <section className="card" data-testid="wo-operations" data-m4="true">
      <div className="card-header row wrap" style={{ justifyContent: "space-between" }}>
        <h3>Operations on the floor</h3>
        <span className="row wrap">
          <Link className="btn sm" to={mfgPaths.printTraveller(woId)} data-testid="wo-print-traveller">
            <Icon name="file" /> Print traveller
          </Link>
          <Link className="btn sm ghost" to={mfgPaths.floorEvents({ wo: woId })}>
            <Icon name="list" /> Event log
          </Link>
          {canEdit && !anyRecorded && !notReleased ? (
            <button type="button" className="btn sm ghost" disabled={busy !== null} onClick={() => void run("refresh", () => refreshWoOperations(woId, woVersion))} title="Re-derive from the routing (only while nothing was recorded)">
              <Icon name="refresh" /> Re-derive from routing
            </button>
          ) : null}
        </span>
      </div>
      {error ? <div className="banner danger" role="alert">{error}</div> : null}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Op.</th>
              <th>Name</th>
              <th>Status</th>
              <th className="right">Good / scrap</th>
              <th>Line</th>
              <th>Actual</th>
              <th>Plan</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((o) => (
              <tr key={o.id || `seq-${o.seq}`} data-testid="wo-op-row" data-seq={o.seq} data-status={o.status}>
                <td className="mono">{o.seq}</td>
                <td>
                  {o.name}
                  {o.group?.code ? <div className="faint small">{o.group.code}</div> : null}
                  {o.capture_serial ? <div className="faint small">serial point</div> : null}
                </td>
                <td>
                  <OpStatusChip status={o.status} />
                  {o.started_short ? <div className="small">started short</div> : null}
                </td>
                <td className="right">
                  {fmtQty(o.qty_good)} / {fmtQty(o.qty_scrap)}
                  <div className="faint small">of {fmtQty(o.qty_planned)}</div>
                  {o.qty_rework_in ? <div className="faint small">+{fmtQty(o.qty_rework_in)} rework in</div> : null}
                </td>
                <td>{o.line?.code ?? ""}</td>
                <td className="small">
                  {o.actual_start ? `${clock.dateTime(o.actual_start)}${o.actual_end ? ` – ${clock.time(o.actual_end)}` : ""}` : ""}
                  {o.run_minutes_actual ? <div className="faint">run {fmtDuration(o.run_minutes_actual)}</div> : null}
                </td>
                <td className="small">{o.placement[0] ? `${o.placement[0].line?.code ? `${o.placement[0].line.code} · ` : ""}${clock.dateTime(o.placement[0].start)} – ${clock.time(o.placement[0].end)}` : <span className="faint">not planned</span>}</td>
                <td>
                  <span className="row" style={{ gap: 4 }}>
                    {o.id ? (
                      <Link className="btn sm" to={mfgPaths.floorOp(o.id)} data-testid="wo-op-floor">
                        Open on floor
                      </Link>
                    ) : (
                      <span className="faint small">created at release</span>
                    )}
                    {o.id && canSupervise && o.status !== "completed" && o.status !== "skipped" ? (
                      <button type="button" className="btn sm ghost" disabled={busy !== null} onClick={() => void run(o.id, () => setWoOperationDone(woId, o.seq, true, woVersion))} data-testid="op-done" title="Complete with the full available quantity (supervisor)">
                        Done
                      </button>
                    ) : null}
                    {o.id && canSupervise && (o.status === "pending" || o.status === "ready") ? (
                      <button type="button" className="btn sm ghost" disabled={busy !== null} onClick={() => setSkipping(o)} data-testid="op-skip">
                        Skip
                      </button>
                    ) : null}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {skipping ? (
        <ReasonDialog
          title={`Skip operation ${skipping.seq}?`}
          text="It will not be done on the floor and the scheduler stops planning it."
          confirm="Skip"
          onClose={() => setSkipping(null)}
          onConfirm={async (reason) => {
            await postFloorEvent({ client_event_id: newClientEventId(), wo_operation_id: skipping.id, event_type: "skip", reason_code: "supervisor", note: reason });
            setSkipping(null);
            reload();
            onChanged();
          }}
        />
      ) : null}
    </section>
  );
}

function M3Ops({ woId, woVersion, ops, onChanged }: { woId: string; woVersion: number; ops: ReturnType<typeof useLoad<{ wo_id?: string; row_version?: number; wo?: { row_version?: number }; items: AnyOp[] }>>; onChanged(): void }) {
  const clock = usePlantClock();
  const canEdit = useCan("wo_edit");
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const version = ops.data?.row_version ?? woVersion;
  const toggle = async (o: WoOperationRow) => {
    setBusy(o.seq);
    setError(null);
    try {
      ops.setData(await setWoOperationDone(woId, o.seq, !o.done, version));
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  return (
    <section className="card" data-testid="wo-operations">
      <div className="card-header">
        <h3>Operations</h3>
        <span className="muted small">From the routing; "done" tells the scheduler not to plan them again.</span>
      </div>
      <MfgError error={ops.error ?? error} onRetry={ops.reload} />
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Op.</th>
              <th>Name</th>
              <th>Stage</th>
              <th>Published schedule</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {((ops.data?.items ?? []) as WoOperationRow[]).map((o) => (
              <tr key={o.seq} data-testid="wo-op-row" data-seq={o.seq} data-done={o.done}>
                <td className="mono">{o.seq}</td>
                <td>{o.name}</td>
                <td>{o.group?.code ?? ""}</td>
                <td className="small">
                  {o.placement?.start ? (
                    <Link to={mfgPaths.apsGantt(o.placement.run_id, { view: "order", order: woId })}>
                      {o.placement.line?.code ?? ""} · {clock.dateTime(o.placement.start)} – {clock.time(o.placement.end)}
                    </Link>
                  ) : (
                    <span className="faint">{o.done ? "" : "not in the published schedule"}</span>
                  )}
                </td>
                <td>
                  {o.done ? (
                    <span className="row" style={{ gap: 6 }}>
                      <span className="badge ok">
                        <Icon name="check" /> Done {o.done_at ? clock.dateTime(o.done_at) : ""}
                      </span>
                      {canEdit ? (
                        <button type="button" className="btn sm ghost" onClick={() => void toggle(o)} disabled={busy === o.seq} data-testid="op-reopen">
                          Reopen
                        </button>
                      ) : null}
                    </span>
                  ) : canEdit ? (
                    <button type="button" className="btn sm" onClick={() => void toggle(o)} disabled={busy === o.seq} data-testid="op-done">
                      {busy === o.seq ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Mark done
                    </button>
                  ) : (
                    <span className="faint small">open</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
