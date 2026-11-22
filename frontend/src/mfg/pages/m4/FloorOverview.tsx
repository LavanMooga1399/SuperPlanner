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
import { MfgError } from "../../components/Feedback";
import { DataTable } from "../../components/DataTable";
import { behindMinutes } from "../../floor/FloorQueue";
import { DOWNTIME, KitChip, OpStatusChip, fmtQty } from "../../floor/floorText";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { useLoad } from "../../lib/useMfg";
import { usePolling } from "../../lib/usePolling";
import { PageHeader } from "../../../components/PageHeader";
import { t } from "../../../lib/i18n";

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

  const rowsOv = (lines.data?.items ?? []).map((l) => {
    const q = qBy.get(l.id);
    const dt = downBy.get(l.id) ?? q?.down ?? null;
    const cur = q?.items.find((x) => x.status === "running" || x.status === "setup") ?? q?.items.find((x) => x.status === "paused") ?? null;
    const next = q?.items.find((x) => x !== cur && (x.status === "ready" || x.status === "pending")) ?? null;
    const delay = cur ? behindMinutes(cur) : null;
    return { l, dt, cur, next, delay, state: dt ? "down" : (cur?.status ?? "idle") };
  });
  return (
    <div className="col gap-lg" data-testid="floor-overview">
      <PageHeader
        title={t("mfg.floorOverview.title.shopFloor")}
        actions={
          <>
            <Link className="btn" to={mfgPaths.floorEvents()}>
            <Icon name="list" /> {t("mfg.floorOverview.btn.eventLog")}
            </Link>
            <Link className="btn primary" to={mfgPaths.floor()}>
            <Icon name="factory" /> {t("mfg.floorOverview.btn.openTheFloorScreens")}
            </Link>
          </>
        }
      />
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
      <DataTable
        rows={rowsOv}
        columns={[
          {
            key: "line",
            header: "Line",
            width: "minmax(130px, 1fr)",
            sortValue: (r) => r.l.code,
            exportValue: (r) => r.l.code,
            render: (r) => (
              <span>
                <Link to={mfgPaths.floorLine(r.l.id)}>
                  <strong>{r.l.code}</strong>
                </Link>
                <span className="vt-sub">{gName.get(r.l.group_id) ?? ""}</span>
              </span>
            ),
          },
          {
            key: "state",
            header: "State",
            width: "minmax(170px, 1fr)",
            sortValue: (r) => r.state,
            exportValue: (r) => r.state,
            render: (r) => (
              <span>
                {r.dt ? (
                  <span className="badge danger">
                    <Icon name="alert" /> Down: {DOWNTIME[r.dt.kind]?.label ?? r.dt.kind}
                  </span>
                ) : r.cur ? (
                  <OpStatusChip status={r.cur.status} />
                ) : (
                  <span className="badge info">
                    <Icon name="clock" /> {t("mfg.floorOverview.btn.idle")}
                  </span>
                )}
                {r.dt ? (
                  <span className="vt-sub">
                    since {clock.time(r.dt.start_at)}
                    {r.dt.expected_end_at ? `, back ${clock.time(r.dt.expected_end_at)}` : ""}
                  </span>
                ) : null}
              </span>
            ),
          },
          {
            key: "now",
            header: "Now",
            width: "minmax(200px, 1.6fr)",
            exportValue: (r) => (r.cur ? `${r.cur.wo.number} / ${r.cur.seq}` : ""),
            render: (r) =>
              r.cur ? (
                <span>
                  <Link to={mfgPaths.workOrder(r.cur.wo.id)} className="mono">
                    {r.cur.wo.number}
                  </Link>{" "}
                  / {r.cur.seq} {r.cur.name}
                  <span className="vt-sub">
                    {fmtQty(r.cur.qty_good)} of {fmtQty(r.cur.qty_planned || r.cur.wo.qty)}
                  </span>
                </span>
              ) : (
                <span className="faint">nothing running</span>
              ),
          },
          {
            key: "plan",
            header: "Against plan",
            width: "140px",
            sortValue: (r) => r.delay,
            exportValue: (r) => r.delay ?? "",
            render: (r) =>
              r.delay === null || !r.cur ? (
                <span className="faint">-</span>
              ) : r.delay > 0 ? (
                <span className="badge warn">
                  <Icon name="clock" /> {fmtDuration(r.delay)} behind
                </span>
              ) : (
                <span className="badge ok">
                  <Icon name="check" /> {t("mfg.floorOverview.btn.onPlan")}
                </span>
              ),
          },
          { key: "next", header: "Next", width: "minmax(160px, 1fr)", render: (r) => (r.next ? `${r.next.wo.number} / ${r.next.seq}${r.next.planned_start ? ` at ${clock.time(r.next.planned_start)}` : ""}` : "") },
          { key: "material", header: "Material", width: "120px", exportValue: (r) => r.next?.kit ?? "", render: (r) => (r.next ? <KitChip kit={r.next.kit} /> : null) },
        ]}
        rowKey={(r) => r.l.id}
        label="Lines on the shop floor"
        tableId="floor-overview"
        loading={(lines.loading || queues.loading) && !queues.data}
        exportName="shop-floor"
        rowExtras={(r) => ({ testId: "overview-line", data: { line: r.l.code, state: r.state } })}
        empty="No lines yet. Add stages and lines under Plant."
        card={{ title: "line", status: "state", fields: ["now", "plan", "next"] }}
      />
    </div>
  );
}
