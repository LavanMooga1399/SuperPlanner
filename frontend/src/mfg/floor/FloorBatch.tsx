/**
 * `/mfg/floor/lines/:lineId/batch` (M4 6.3, #211-213): batch lines (oven, burn-in) run several work orders in one
 * load. Build a load from the waiting operations of the line, then start and complete it in one action for every
 * member (the event carries `batch_load_id`; quantities per member in `details.members`, see 16.WP-U).
 */
import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { Icon } from "../../components/Icon";
import { createBatchLoad, getFloorQueue, listBatchLoads } from "../api/clientM4";
import type { BatchLoad, FloorQueueRow } from "../api/typesM4";
import { MfgError, Spinner } from "../components/Feedback";
import { usePlantClock } from "../lib/plantTime";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { useLoad } from "../lib/useMfg";
import { crewForEvent, useFloor } from "./FloorLayout";
import { OpStatusChip, floorErrorText, fmtQty } from "./floorText";
import { newClientEventId, submitFloorEvent } from "./offlineQueue";

export function FloorBatch() {
  const { lineId = "" } = useParams();
  const [params] = useSearchParams();
  const focusLoad = params.get("load");
  const floor = useFloor();
  const clock = usePlantClock();
  const canReport = useCan("floor_report");
  const loads = useLoad((signal) => listBatchLoads({ line_id: lineId, limit: 50 }, signal), [lineId]);
  const queue = useLoad((signal) => getFloorQueue({ line_id: lineId }, signal), [lineId]);
  const [pick, setPick] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inLoad = useMemo(() => new Set((loads.data?.items ?? []).filter((l) => l.status === "open" || l.status === "running").flatMap((l) => l.members.map((m) => m.wo_operation_id))), [loads.data]);
  const waiting = (queue.data?.items ?? []).filter((r): r is FloorQueueRow & { wo_operation_id: string } => Boolean(r.wo_operation_id) && (r.status === "ready" || r.status === "pending") && !inLoad.has(r.wo_operation_id!));
  const active = (loads.data?.items ?? []).filter((l) => l.status === "open" || l.status === "running");

  const build = async () => {
    const members = Object.entries(pick)
      .filter(([, q]) => Number(q) > 0)
      .map(([id, q]) => ({ wo_operation_id: id, qty: Number(q) }));
    if (!members.length) return;
    setBusy(true);
    setError(null);
    try {
      await createBatchLoad({ line_id: lineId, members });
      setPick({});
      floor.flash("Load created");
      loads.reload();
    } catch (e) {
      setError(floorErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const act = async (l: BatchLoad, type: "start" | "complete") => {
    if (!l.members.length) return;
    setBusy(true);
    setError(null);
    try {
      // a batch_load_id alone applies the event to every member (FloorEventInput rules)
      const out = await submitFloorEvent(
        {
          client_event_id: newClientEventId(),
          batch_load_id: l.id,
          event_type: type,
          line_id: lineId,
          ...crewForEvent(floor.crew),
          ...(type === "complete" ? { qty_good: l.members.reduce((a, m) => a + m.qty, 0) } : {}),
        },
        `${type === "start" ? "Start" : "Complete"} load`,
      );
      floor.flash(out.status === "queued" ? "Saved on this tablet; it will sync when the network is back" : type === "start" ? "Load started" : "Load completed");
      loads.reload();
      queue.reload();
    } catch (e) {
      setError(floorErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section className="floor-card">
        <div className="row wrap" style={{ justifyContent: "space-between" }}>
          <h1>Batch loads{queue.data ? ` · ${queue.data.line.code}` : ""}</h1>
          <Link className="btn floor-btn" to={mfgPaths.floorLine(lineId)}>
            Back to the queue
          </Link>
        </div>
      </section>
      <MfgError error={loads.error ?? queue.error} onRetry={loads.reload} />
      {error ? (
        <div className="floor-flash danger" role="alert">
          <Icon name="alert" /> {error}
        </div>
      ) : null}
      {loads.loading && !loads.data ? <Spinner /> : null}
      {active.map((l) => (
        <section key={l.id} className={`floor-card${focusLoad === l.id ? " floor-tile active" : ""}`} data-testid="floor-batch-load" data-status={l.status}>
          <div className="row wrap" style={{ justifyContent: "space-between" }}>
            <h2>
              Load {l.load_no || l.id.slice(-6)} · {fmtQty(l.units)} units · {l.status === "running" ? `running since ${clock.time(l.started_at)}` : "ready to start"}
            </h2>
            {canReport ? (
              <div className="row">
                {l.status === "open" ? (
                  <button type="button" className="btn primary floor-action" disabled={busy} onClick={() => void act(l, "start")} data-testid="floor-batch-start">
                    <Icon name="play" /> Start load
                  </button>
                ) : (
                  <button type="button" className="btn primary floor-action" disabled={busy} onClick={() => void act(l, "complete")} data-testid="floor-batch-complete">
                    <Icon name="check" /> Complete load
                  </button>
                )}
              </div>
            ) : null}
          </div>
          <table className="floor-table">
            <tbody>
              {l.members.map((m) => (
                <tr key={m.wo_operation_id}>
                  <td className="mono">
                    {m.wo.number} / {m.seq}
                  </td>
                  <td>{fmtQty(m.qty)} units</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      {canReport ? (
        <section className="floor-card">
          <h2>New load</h2>
          {waiting.length === 0 ? <span className="muted">No waiting operations on this line.</span> : null}
          <table className="floor-table">
            <tbody>
              {waiting.map((r) => (
                <tr key={r.wo_operation_id}>
                  <td>
                    <span className="mono">{r.wo.number}</span> / {r.seq} {r.name}
                    <div className="small muted mono">{r.wo.item.part_number}</div>
                  </td>
                  <td>
                    <OpStatusChip status={r.status} />
                  </td>
                  <td style={{ width: 160 }}>
                    <label className="sr-only" htmlFor={`bq-${r.wo_operation_id}`}>
                      Units of {r.wo.number}
                    </label>
                    <input
                      id={`bq-${r.wo_operation_id}`}
                      className="input"
                      inputMode="decimal"
                      placeholder={`up to ${fmtQty((r.qty_planned || r.wo.qty) - r.qty_good)}`}
                      value={pick[r.wo_operation_id] ?? ""}
                      onChange={(e) => setPick({ ...pick, [r.wo_operation_id]: e.target.value.replace(/[^0-9.]/g, "") })}
                    />
                  </td>
                  <td>
                    <button type="button" className="btn" onClick={() => setPick({ ...pick, [r.wo_operation_id]: String((r.qty_planned || r.wo.qty) - r.qty_good) })}>
                      All
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" className="btn primary floor-action" disabled={busy || !Object.values(pick).some((q) => Number(q) > 0)} onClick={() => void build()} data-testid="floor-batch-create">
            <Icon name="layers" /> Create load
          </button>
        </section>
      ) : null}
    </>
  );
}
