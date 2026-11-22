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
import { DataTable } from "./DataTable";
import { t } from "../../lib/i18n";

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
    <section className="card card-table" data-testid="wo-operations" data-m4="true">
      <div className="card-header row wrap" style={{ justifyContent: "space-between" }}>
        <h3>Operations on the floor</h3>
        <span className="row wrap">
          <Link className="btn sm" to={mfgPaths.printTraveller(woId)} data-testid="wo-print-traveller">
            <Icon name="file" /> {t("mfg.woOperations.btn.printTraveller")}
          </Link>
          <Link className="btn sm ghost" to={mfgPaths.floorEvents({ wo: woId })}>
            <Icon name="list" /> {t("mfg.woOperations.btn.eventLog")}
          </Link>
          {canEdit && !anyRecorded && !notReleased ? (
            <button type="button" className="btn sm ghost" disabled={busy !== null} onClick={() => void run("refresh", () => refreshWoOperations(woId, woVersion))} title="Re-derive from the routing (only while nothing was recorded)">
              <Icon name="refresh" /> {t("mfg.woOperations.btn.rederiveFromRouting")}
            </button>
          ) : null}
        </span>
      </div>
      {error ? <div className="banner danger" role="alert">{error}</div> : null}
      <DataTable
        rows={items}
        columns={[
          { key: "seq", header: "Op.", width: "64px", sortValue: (o) => o.seq, render: (o) => <span className="mono">{o.seq}</span> },
          {
            key: "name",
            header: "Name",
            width: "minmax(170px, 1.4fr)",
            wrap: true,
            exportValue: (o) => o.name,
            render: (o) => (
              <span>
                {o.name}
                {o.group?.code || o.capture_serial ? <span className="vt-sub">{[o.group?.code, o.capture_serial ? "serial point" : ""].filter(Boolean).join(" · ")}</span> : null}
              </span>
            ),
          },
          {
            key: "status",
            header: "Status",
            width: "130px",
            sortValue: (o) => o.status,
            exportValue: (o) => o.status,
            render: (o) => (
              <span>
                <OpStatusChip status={o.status} />
                {o.started_short ? <span className="vt-sub">started short</span> : null}
              </span>
            ),
          },
          {
            key: "qty",
            header: "Good / scrap",
            width: "130px",
            align: "right",
            sortValue: (o) => o.qty_good,
            exportValue: (o) => `${o.qty_good} / ${o.qty_scrap}`,
            render: (o) => (
              <span>
                {fmtQty(o.qty_good)} / {fmtQty(o.qty_scrap)}
                <span className="vt-sub">
                  of {fmtQty(o.qty_planned)}
                  {o.qty_rework_in ? ` · +${fmtQty(o.qty_rework_in)} rework in` : ""}
                </span>
              </span>
            ),
          },
          { key: "line", header: "Line", width: "90px", sortValue: (o) => o.line?.code ?? "", render: (o) => o.line?.code ?? "" },
          {
            key: "actual",
            header: "Actual",
            width: "minmax(170px, 1fr)",
            sortValue: (o) => o.actual_start ?? null,
            exportValue: (o) => o.actual_start ?? "",
            render: (o) => (
              <span>
                {o.actual_start ? `${clock.dateTime(o.actual_start)}${o.actual_end ? ` – ${clock.time(o.actual_end)}` : ""}` : ""}
                {o.run_minutes_actual ? <span className="vt-sub">run {fmtDuration(o.run_minutes_actual)}</span> : null}
              </span>
            ),
          },
          {
            key: "plan",
            header: "Plan",
            width: "minmax(190px, 1.2fr)",
            wrap: true,
            exportValue: (o) => o.placement[0]?.start ?? "",
            render: (o) =>
              o.placement[0] ? (
                `${o.placement[0].line?.code ? `${o.placement[0].line.code} · ` : ""}${clock.dateTime(o.placement[0].start)} – ${clock.time(o.placement[0].end)}`
              ) : (
                <span className="faint">not planned</span>
              ),
          },
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            label: "Actions",
            width: "210px",
            exportValue: () => "",
            render: (o) => (
              <span className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                {o.id ? (
                  <Link className="btn sm" to={mfgPaths.floorOp(o.id)} data-testid="wo-op-floor">
                    {t("mfg.woOperations.btn.openOnFloor")}
                  </Link>
                ) : (
                  <span className="faint small">created at release</span>
                )}
                {o.id && canSupervise && o.status !== "completed" && o.status !== "skipped" ? (
                  <button type="button" className="btn sm ghost" disabled={busy !== null} onClick={() => void run(o.id, () => setWoOperationDone(woId, o.seq, true, woVersion))} data-testid="op-done" title="Complete with the full available quantity (supervisor)">
                    {t("mfg.woOperations.btn.done")}
                  </button>
                ) : null}
                {o.id && canSupervise && (o.status === "pending" || o.status === "ready") ? (
                  <button type="button" className="btn sm ghost" disabled={busy !== null} onClick={() => setSkipping(o)} data-testid="op-skip">
                    {t("mfg.woOperations.btn.skip")}
                  </button>
                ) : null}
              </span>
            ),
          },
        ]}
        rowKey={(o) => o.id || `seq-${o.seq}`}
        label="Operations on the floor"
        tableId="wo-operations-floor"
        exportName={`${woId}-operations`}
        rowExtras={(o) => ({ testId: "wo-op-row", data: { seq: o.seq, status: o.status } })}
        card={{ title: "name", status: "status", actions: "actions", fields: ["qty", "line", "plan"] }}
      />
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
    <section className="card card-table" data-testid="wo-operations">
      <div className="card-header">
        <h3>Operations</h3>
        <span className="muted small">From the routing; "done" tells the scheduler not to plan them again.</span>
      </div>
      <MfgError error={ops.error ?? error} onRetry={ops.reload} />
      <DataTable
        rows={(ops.data?.items ?? []) as WoOperationRow[]}
        columns={[
          { key: "seq", header: "Op.", width: "64px", sortValue: (o) => o.seq, render: (o) => <span className="mono">{o.seq}</span> },
          { key: "name", header: "Name", width: "minmax(170px, 1.4fr)", sortValue: (o) => o.name, render: (o) => o.name },
          { key: "stage", header: "Stage", width: "100px", sortValue: (o) => o.group?.code ?? "", render: (o) => o.group?.code ?? "" },
          {
            key: "plan",
            header: "Published schedule",
            width: "minmax(220px, 1.6fr)",
            exportValue: (o) => o.placement?.start ?? "",
            render: (o) =>
              o.placement?.start ? (
                <Link to={mfgPaths.apsGantt(o.placement.run_id, { view: "order", order: woId })}>
                  {o.placement.line?.code ?? ""} · {clock.dateTime(o.placement.start)} – {clock.time(o.placement.end)}
                </Link>
              ) : (
                <span className="faint">{o.done ? "" : "not in the published schedule"}</span>
              ),
          },
          {
            key: "status",
            header: "Status",
            width: "minmax(220px, 1.2fr)",
            sortValue: (o) => (o.done ? 1 : 0),
            exportValue: (o) => (o.done ? "done" : "open"),
            render: (o) =>
              o.done ? (
                <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                  <span className="badge ok">
                    <Icon name="check" /> Done {o.done_at ? clock.dateTime(o.done_at) : ""}
                  </span>
                  {canEdit ? (
                    <button type="button" className="btn sm ghost" onClick={() => void toggle(o)} disabled={busy === o.seq} data-testid="op-reopen">
                      {t("mfg.woOperations.btn.reopen")}
                    </button>
                  ) : null}
                </span>
              ) : canEdit ? (
                <button type="button" className="btn sm" onClick={() => void toggle(o)} disabled={busy === o.seq} data-testid="op-done">
                  {busy === o.seq ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Mark done
                </button>
              ) : (
                <span className="faint small">open</span>
              ),
          },
        ]}
        rowKey={(o) => o.seq}
        label="Operations"
        tableId="wo-operations"
        exportName={`${woId}-operations`}
        rowExtras={(o) => ({ testId: "wo-op-row", data: { seq: o.seq, done: o.done } })}
        card={{ title: "name", status: "status", fields: ["stage", "plan"] }}
      />
    </section>
  );
}
