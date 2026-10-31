/** `/mfg/floor/wo/:woId`: the operations of a scanned work order (traveller header) to pick one. */
import { Link, useParams } from "react-router";
import { listWoOperationsM4 } from "../api/clientM4";
import { MfgError, Spinner } from "../components/Feedback";
import { mfgPaths } from "../lib/paths";
import { useLoad } from "../lib/useMfg";
import { OpStatusChip, fmtQty } from "./floorText";

export function FloorWo() {
  const { woId = "" } = useParams();
  const ops = useLoad((signal) => listWoOperationsM4(woId, signal), [woId]);
  return (
    <section className="floor-card">
      <h1>Operations of this work order</h1>
      <MfgError error={ops.error} onRetry={ops.reload} />
      {ops.loading && !ops.data ? <Spinner /> : null}
      <div className="floor-queue">
        {(ops.data?.items ?? []).filter((o) => o.id).map((o) => (
          <Link key={o.id} to={mfgPaths.floorOp(o.id)} className="floor-qrow" data-status={o.status}>
            <span className="floor-qpos">{o.seq}</span>
            <span className="floor-qmain">
              <span className="floor-qtitle">{o.name}</span>
              <span className="muted">
                {fmtQty(o.qty_good)} of {fmtQty(o.qty_planned)} good{o.qty_scrap ? ` · ${fmtQty(o.qty_scrap)} scrap` : ""}
              </span>
            </span>
            <span className="floor-qside">
              <OpStatusChip status={o.status} large />
            </span>
          </Link>
        ))}
        {ops.data && !ops.data.items.some((o) => o.id) ? <span className="muted">This work order has no operations yet (not released to the floor).</span> : null}
      </div>
    </section>
  );
}
