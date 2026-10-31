/**
 * `/mfg/floor/lines/:lineId` (M4 12, #201): the line's queue for the current shift in the published order, with live
 * status and the kit light (icon + text). Tap a row to open the operation. Line down: a red card with "Line back up".
 * Batch lines get a "Batch loads" button. Refreshes every 20 s and after returning to the page.
 */
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { Icon } from "../../components/Icon";
import { getFloorQueue } from "../api/clientM4";
import type { FloorQueueRow } from "../api/typesM4";
import { MfgError, Spinner } from "../components/Feedback";
import { fmtDuration, usePlantClock } from "../lib/plantTime";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { setSearchParam } from "../lib/usePaged";
import { useLoad } from "../lib/useMfg";
import { usePolling } from "../lib/usePolling";
import { useFloor } from "./FloorLayout";
import { DOWNTIME, KitChip, OpStatusChip, fmtQty, floorErrorText } from "./floorText";
import { submitDowntimeUpdate } from "./offlineQueue";

export function FloorQueue() {
  const { lineId = "" } = useParams();
  const { setLineId, lineId: remembered, flash } = useFloor();
  const clock = usePlantClock();
  const canDowntime = useCan("downtime_report");
  const [params, setParams] = useSearchParams();
  const shift = params.get("shift") ?? "";
  const date = params.get("date") ?? "";
  const [showDone, setShowDone] = useState(false);
  const [closing, setClosing] = useState(false);
  useEffect(() => {
    if (lineId && lineId !== remembered) setLineId(lineId);
  }, [lineId, remembered, setLineId]);
  const q = useLoad((signal) => getFloorQueue({ line_id: lineId, shift: shift || undefined, date: date || undefined }, signal), [lineId, shift, date]);
  usePolling(q.reload, true, 20000);
  const reload = q.reload;
  useEffect(() => {
    const onVis = () => document.visibilityState === "visible" && reload();
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [reload]);
  const d = q.data;
  useEffect(() => {
    if (d) document.title = `${d.line.code} - Floor`;
  }, [d]);
  const rows = (d?.items ?? []).filter((r) => showDone || (r.status !== "completed" && r.status !== "skipped"));
  const doneCount = (d?.items ?? []).length - (d?.items ?? []).filter((r) => r.status !== "completed" && r.status !== "skipped").length;
  const down = d?.down ?? null;

  const lineUp = async () => {
    if (!down) return;
    setClosing(true);
    try {
      const out = await submitDowntimeUpdate(down.id, down.row_version, { close: true }, `${d?.line.code ?? "Line"} back up`);
      flash(out.status === "queued" ? "Saved on this tablet; it will sync when the network is back" : "Line is back up");
      q.reload();
    } catch (e) {
      flash(floorErrorText(e), "danger");
    } finally {
      setClosing(false);
    }
  };

  return (
    <>
      <section className="floor-card">
        <div className="row wrap" style={{ justifyContent: "space-between", gap: 10 }}>
          <div className="col" style={{ gap: 2 }}>
            <h1 data-testid="floor-line-title">{d ? `${d.line.code}${d.line.name ? ` · ${d.line.name}` : ""}` : "Line"}</h1>
            <span className="muted">
              {d ? `${d.shift ? `Shift ${d.shift} · ` : ""}${d.date} · times in ${clock.zoneLabel}` : ""}
              {d && !d.run_id ? " · no published schedule: work orders in due-date order" : ""}
            </span>
          </div>
          <div className="row wrap">
            {d?.shifts?.length ? (
              <select className="select" aria-label="Shift" value={shift} onChange={(e) => setSearchParam(setParams, "shift", e.target.value)}>
                <option value="">Current shift</option>
                {d.shifts
                  .filter((s) => s.label)
                  .map((s) => (
                    <option key={`${s.label}${s.start}`} value={s.label!}>
                      {s.label} {clock.time(s.start)}–{clock.time(s.end)}
                    </option>
                  ))}
              </select>
            ) : null}
            {d?.line.batch_merge ? (
              <Link className="btn" to={mfgPaths.floorBatch(lineId)} data-testid="floor-batch-link">
                <Icon name="layers" /> Batch loads
              </Link>
            ) : null}
            {canDowntime && !down ? (
              <Link className="btn danger" to={mfgPaths.floorDowntime(lineId)} data-testid="downtime-open">
                <Icon name="alert" /> Report line down
              </Link>
            ) : null}
            <Link className="btn ghost" to={`${mfgPaths.floor()}?pick=1`}>
              Change line
            </Link>
          </div>
        </div>
      </section>

      {down ? (
        <section className="floor-card floor-down" role="alert" data-testid="floor-line-down">
          <h2>
            <Icon name="alert" /> Line down: {DOWNTIME[down.kind]?.label ?? down.kind}
          </h2>
          <span>
            Since {clock.dateTime(down.start_at)}
            {down.expected_end_at ? `, expected back ${clock.dateTime(down.expected_end_at)}` : ", no expected end given"}
            {down.reason ? ` · ${down.reason}` : ""}
          </span>
          {canDowntime ? (
            <div className="row wrap">
              <button type="button" className="btn primary floor-btn" onClick={() => void lineUp()} disabled={closing} data-testid="downtime-close">
                <Icon name="check" /> Line back up
              </button>
              <Link className="btn floor-btn" to={`${mfgPaths.floorDowntime(lineId)}?edit=${encodeURIComponent(down.id)}`}>
                Change expected end
              </Link>
            </div>
          ) : null}
        </section>
      ) : null}

      <MfgError error={q.error} onRetry={q.reload} />
      {q.loading && !d ? <Spinner label="Loading the queue…" /> : null}
      {d ? (
        <section className="floor-queue" aria-label="Queue" data-testid="floor-queue">
          {rows.length === 0 ? <div className="floor-card muted">Nothing planned on this line for this shift.</div> : null}
          {rows.map((r, i) => (
            <QueueRow key={r.wo_operation_id ?? `${r.wo.id}-${r.seq}`} r={r} index={i} clock={clock} />
          ))}
          {doneCount ? (
            <button type="button" className="btn ghost floor-btn" onClick={() => setShowDone((v) => !v)}>
              {showDone ? "Hide finished" : `Show ${doneCount} finished`}
            </button>
          ) : null}
        </section>
      ) : null}
    </>
  );
}

/** minutes behind the published plan: running past the planned end, or not started by the planned start */
export function behindMinutes(r: Pick<FloorQueueRow, "status" | "planned_start" | "planned_end">, now = Date.now()): number {
  if (r.status === "completed" || r.status === "skipped") return 0;
  const ref = r.status === "pending" || r.status === "ready" ? r.planned_start : r.planned_end;
  if (!ref) return 0;
  return Math.max(0, Math.round((now - Date.parse(ref)) / 60000));
}

function QueueRow({ r, index, clock }: { r: FloorQueueRow; index: number; clock: ReturnType<typeof usePlantClock> }) {
  const qty = r.qty_planned || r.wo.qty;
  const pct = qty > 0 ? Math.min(100, (100 * r.qty_good) / qty) : 0;
  const behind = behindMinutes(r);
  const body = (
    <>
      <span className="floor-qpos" aria-label={r.op_no ? `Position ${index + 1} in the plan` : "Not in the plan"}>
        {index + 1}
      </span>
      <span className="floor-qmain">
        <span className="floor-qtitle">
          <span className="mono">{r.wo.number}</span> / {r.seq} {r.name}
        </span>
        <span className="muted">
          <span className="mono">{r.wo.item.part_number}</span> · {fmtQty(r.qty_good)} of {fmtQty(qty)} good
          {r.wo.due_date ? ` · due ${r.wo.due_date}` : ""}
        </span>
        {r.qty_good > 0 ? (
          <span className="floor-progress" aria-hidden>
            <span style={{ width: `${pct}%` }} />
          </span>
        ) : null}
      </span>
      <span className="floor-qside">
        <OpStatusChip status={r.status} large />
        <KitChip kit={r.kit} />
        <span className="small muted">
          {r.planned_start ? `Plan ${clock.time(r.planned_start)}–${clock.time(r.planned_end)}` : "not in the published plan"}
          {behind > 15 ? ` · ${fmtDuration(behind)} behind` : ""}
        </span>
      </span>
    </>
  );
  if (!r.wo_operation_id)
    return (
      <div className="floor-qrow" data-testid="floor-queue-row" data-status={r.status} data-wo={r.wo.number} data-seq={r.seq} title="The work order is not released to the floor yet">
        {body}
      </div>
    );
  return (
    <Link to={mfgPaths.floorOp(r.wo_operation_id)} className="floor-qrow" data-testid="floor-queue-row" data-status={r.status} data-wo={r.wo.number} data-seq={r.seq}>
      {body}
    </Link>
  );
}
