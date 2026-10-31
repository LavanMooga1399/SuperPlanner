/**
 * `/mfg/floor/overview` (M4 12): all lines at a glance for supervisors and planners: running / paused / down, the
 * current operation and its delay against the published plan. One #201 queue call per active line (refreshed every
 * 30 s) plus open downtime; fine for a plant's line count (16.WP-U).
 */
import { useMemo } from "react";
import { Link } from "react-router";
import { Icon } from "../../../components/Icon";
import { listGroups, listLines } from "../../api/client";
import { getFloorQueue, listDowntime } from "../../api/clientM4";
import type { FloorQueueResponse } from "../../api/typesM4";
import { MfgError, Spinner } from "../../components/Feedback";
import { behindMinutes } from "../../floor/FloorQueue";
import { DOWNTIME, KitChip, OpStatusChip, fmtQty } from "../../floor/floorText";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { useLoad } from "../../lib/useMfg";
import { usePolling } from "../../lib/usePolling";

export function FloorOverview() {
  const clock = usePlantClock();
  const lines = useLoad((signal) => listLines({ active: true }, signal), []);
  const groups = useLoad((signal) => listGroups({}, signal), []);
  const ids = (lines.data?.items ?? []).map((l) => l.id).join(",");
  const queues = useLoad(
    async (signal) => {
      const ls = lines.data?.items ?? [];
      const out = await Promise.all(ls.map((l) => getFloorQueue({ line_id: l.id }, signal).catch(() => null)));
      return out.filter((x): x is FloorQueueResponse => x !== null);
    },
    [ids],
  );
  const down = useLoad((signal) => listDowntime({ open: true, limit: 200 }, signal), []);
  usePolling(() => {
    queues.reload();
    down.reload();
  }, true, 30000);
  const gName = useMemo(() => new Map((groups.data?.items ?? []).map((g) => [g.id, g.code])), [groups.data]);
  const downBy = useMemo(() => new Map((down.data?.items ?? []).map((d) => [d.line.id, d])), [down.data]);
  const qBy = useMemo(() => new Map((queues.data ?? []).map((q) => [q.line.id, q])), [queues.data]);
  const counts = { running: 0, paused: 0, down: 0, idle: 0 };
  for (const l of lines.data?.items ?? []) {
    const q = qBy.get(l.id);
    const cur = q?.items.find((r) => r.status === "running" || r.status === "setup") ?? q?.items.find((r) => r.status === "paused");
    if (downBy.has(l.id) || q?.down) counts.down++;
    else if (cur?.status === "paused") counts.paused++;
    else if (cur) counts.running++;
    else counts.idle++;
  }

  return (
    <div className="col gap-lg" data-testid="floor-overview">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>Shop floor</h1>
        <div className="row wrap">
          <Link className="btn" to={mfgPaths.floorEvents()}>
            <Icon name="list" /> Event log
          </Link>
          <Link className="btn primary" to={mfgPaths.floor()}>
            <Icon name="factory" /> Open the floor screens
          </Link>
        </div>
      </div>
      <div className="kpis">
        <div className="card kpi">
          <div className="kpi-label">Running</div>
          <div className="kpi-value">{counts.running}</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">Paused</div>
          <div className="kpi-value">{counts.paused}</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">Down</div>
          <div className="kpi-value" style={{ color: counts.down ? "var(--danger)" : undefined }}>
            {counts.down}
          </div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">Idle</div>
          <div className="kpi-value">{counts.idle}</div>
        </div>
      </div>
      <MfgError error={lines.error ?? queues.error ?? down.error} onRetry={queues.reload} />
      {(lines.loading || queues.loading) && !queues.data ? <Spinner /> : null}
      <div className="table-wrap card">
        <table className="table">
          <thead>
            <tr>
              <th>Line</th>
              <th>State</th>
              <th>Now</th>
              <th>Against plan</th>
              <th>Next</th>
              <th>Material</th>
            </tr>
          </thead>
          <tbody>
            {(lines.data?.items ?? []).map((l) => {
              const q = qBy.get(l.id);
              const dt = downBy.get(l.id) ?? q?.down ?? null;
              const cur = q?.items.find((r) => r.status === "running" || r.status === "setup") ?? q?.items.find((r) => r.status === "paused") ?? null;
              const next = q?.items.find((r) => r !== cur && (r.status === "ready" || r.status === "pending")) ?? null;
              const delay = cur ? behindMinutes(cur) : null;
              return (
                <tr key={l.id} data-testid="overview-line" data-line={l.code} data-state={dt ? "down" : (cur?.status ?? "idle")}>
                  <td>
                    <Link to={mfgPaths.floorLine(l.id)}>
                      <strong>{l.code}</strong>
                    </Link>
                    <div className="faint small">{gName.get(l.group_id) ?? ""}</div>
                  </td>
                  <td>
                    {dt ? (
                      <span className="badge danger">
                        <Icon name="alert" /> Down: {DOWNTIME[dt.kind]?.label ?? dt.kind}
                      </span>
                    ) : cur ? (
                      <OpStatusChip status={cur.status} />
                    ) : (
                      <span className="badge info">
                        <Icon name="clock" /> Idle
                      </span>
                    )}
                    {dt ? (
                      <div className="small muted">
                        since {clock.time(dt.start_at)}
                        {dt.expected_end_at ? `, back ${clock.time(dt.expected_end_at)}` : ""}
                      </div>
                    ) : null}
                  </td>
                  <td>
                    {cur ? (
                      <>
                        <Link to={mfgPaths.workOrder(cur.wo.id)} className="mono">
                          {cur.wo.number}
                        </Link>{" "}
                        / {cur.seq} {cur.name}
                        <div className="small muted">
                          {fmtQty(cur.qty_good)} of {fmtQty(cur.qty_planned || cur.wo.qty)}
                        </div>
                      </>
                    ) : (
                      <span className="faint">nothing running</span>
                    )}
                  </td>
                  <td>
                    {delay === null || !cur ? (
                      <span className="faint">-</span>
                    ) : delay > 0 ? (
                      <span className="badge warn">
                        <Icon name="clock" /> {fmtDuration(delay)} behind
                      </span>
                    ) : (
                      <span className="badge ok">
                        <Icon name="check" /> on plan
                      </span>
                    )}
                  </td>
                  <td className="small">{next ? `${next.wo.number} / ${next.seq}${next.planned_start ? ` at ${clock.time(next.planned_start)}` : ""}` : ""}</td>
                  <td>{next ? <KitChip kit={next.kit} /> : null}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
