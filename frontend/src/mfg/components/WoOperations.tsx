/**
 * Work-order operations (M3 12, 3.3 #176-178): the operations derived from the WO's routing with "done"
 * (mark finished / reopen, `wo_edit`, If-Match on the WO) and where the published schedule places each one.
 */
import { useState } from "react";
import { Link } from "react-router";
import { Icon } from "../../components/Icon";
import { getWoOperations, setWoOperationDone } from "../api/clientM3";
import type { WoOperationRow } from "../api/typesM3";
import { usePlantClock } from "../lib/plantTime";
import { mfgPaths } from "../lib/paths";
import { useCan } from "../lib/permissions";
import { isNotFound, useLoad } from "../lib/useMfg";
import { MfgError } from "./Feedback";

export function WoOperations({ woId, woVersion, onChanged }: { woId: string; woVersion: number; onChanged(): void }) {
  const clock = usePlantClock();
  const canEdit = useCan("wo_edit");
  const ops = useLoad((signal) => getWoOperations(woId, signal), [woId, woVersion]);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  if (ops.error && isNotFound(ops.error)) return null; // server without M3
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
            {(ops.data?.items ?? []).map((o) => (
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
