/**
 * `/mfg/serials` and `/mfg/serials/:serialId` (M4 10, #214/#215): find a unit by serial, item or work order; the
 * detail shows its work order, the parent it went into and the units fitted into it (one level; multi-level
 * genealogy is M5). Labels print from the browser.
 */
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { getSerial, listSerials } from "../../api/clientM4";
import type { SerialStatus, UnitSerial } from "../../api/typesM4";
import { MfgError, Spinner } from "../../components/Feedback";
import { usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam, usePaged } from "../../lib/usePaged";
import { useDebounced, useLoad } from "../../lib/useMfg";

const STATUS: Record<SerialStatus, { label: string; tone: string; icon: "check" | "clock" | "layers" | "arrow-right" | "trash" }> = {
  wip: { label: "In production", tone: "accent", icon: "clock" },
  in_stock: { label: "In stock", tone: "ok", icon: "check" },
  consumed: { label: "Fitted into a parent", tone: "info", icon: "layers" },
  shipped: { label: "Shipped", tone: "info", icon: "arrow-right" },
  scrapped: { label: "Scrapped", tone: "danger", icon: "trash" },
};

export function SerialStatusChip({ s }: { s: SerialStatus }) {
  const m = STATUS[s] ?? { label: s, tone: "info", icon: "clock" as const };
  return (
    <span className={`badge ${m.tone}`} data-status={s}>
      <Icon name={m.icon} /> {m.label}
    </span>
  );
}

export function SerialsPage() {
  const clock = usePlantClock();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim(), 250);
  const status = (params.get("status") ?? "") as SerialStatus | "";
  const wo = params.get("wo") ?? "";
  const data = usePaged<UnitSerial>((offset, limit, signal) => listSerials({ q: dq || undefined, status: status || undefined, wo_id: wo || undefined, limit, offset }, signal), [dq, status, wo]);
  return (
    <div className="col gap-lg" data-testid="serials-page">
      <h1 style={{ margin: 0 }}>Unit serials</h1>
      <div className="toolbar mfg-filters" role="search">
        <div className="field" style={{ flex: "1 1 260px" }}>
          <label htmlFor="sr-q">Serial, part or work order</label>
          <input id="sr-q" className="input" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. TPU-000123" data-testid="serial-search" />
        </div>
        <div className="field">
          <label htmlFor="sr-status">Status</label>
          <select id="sr-status" className="select" value={status} onChange={(e) => setSearchParam(setParams, "status", e.target.value)}>
            <option value="">Any</option>
            {(Object.keys(STATUS) as SerialStatus[]).map((s) => (
              <option key={s} value={s}>
                {STATUS[s].label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <MfgError error={data.error} onRetry={data.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="serials-table">
          <thead>
            <tr>
              <th>Serial</th>
              <th>Item</th>
              <th>Work order</th>
              <th>Status</th>
              <th>Captured</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  {data.loading ? "Loading…" : "No serials found."}
                </td>
              </tr>
            ) : null}
            {data.rows.map((s) => (
              <tr key={s.id} data-testid="serial-row">
                <td>
                  <Link to={mfgPaths.serial(s.id)} className="mono">
                    {s.serial}
                  </Link>
                </td>
                <td className="mono">{s.item?.part_number ?? ""}</td>
                <td>{s.wo ? <Link to={mfgPaths.workOrder(s.wo.id)} className="mono">{s.wo.number}</Link> : ""}</td>
                <td>
                  <SerialStatusChip s={s.status} />
                </td>
                <td className="small">
                  {clock.dateTime(s.captured_at)}
                  {s.captured_op_seq ? ` at op ${s.captured_op_seq}` : ""}
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
    </div>
  );
}

function UnitLine({ u }: { u: UnitSerial }) {
  return (
    <span className="row wrap" style={{ gap: 6 }}>
      <Link to={mfgPaths.serial(u.id)} className="mono">
        {u.serial}
      </Link>
      <span className="mono faint">{u.item?.part_number ?? ""}</span>
      <SerialStatusChip s={u.status} />
    </span>
  );
}

export function SerialPage() {
  const { serialId = "" } = useParams();
  const clock = usePlantClock();
  const s = useLoad((signal) => getSerial(serialId, signal), [serialId]);
  const u = s.data;
  if (s.loading && !u) return <Spinner />;
  if (!u) return <MfgError error={s.error} onRetry={s.reload} />;
  return (
    <div className="col gap-lg" data-testid="serial-page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to={mfgPaths.serials()}>Serials</Link> <Icon name="chevron-right" size={12} /> <span>{u.serial}</span>
      </nav>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>
          <span className="mono">{u.serial}</span> <SerialStatusChip s={u.status} />
        </h1>
        <Link className="btn" to={mfgPaths.printLabels({ type: "serial", ids: u.id })}>
          <Icon name="file" /> Print label
        </Link>
      </div>
      <section className="card card-body">
        <dl className="floor-kv">
          <dt>Item</dt>
          <dd>
            {u.item ? (
              <Link to={mfgPaths.item(u.item.id)} className="mono">
                {u.item.part_number}
              </Link>
            ) : null}{" "}
            {u.item?.description ?? ""}
          </dd>
          <dt>Made in</dt>
          <dd>{u.wo ? <Link to={mfgPaths.workOrder(u.wo.id)} className="mono">{u.wo.number}</Link> : "-"}</dd>
          <dt>Captured</dt>
          <dd>
            {clock.dateTime(u.captured_at)}
            {u.captured_op_seq ? ` at operation ${u.captured_op_seq}` : ""}
          </dd>
          {u.consumed_at ? (
            <>
              <dt>Fitted</dt>
              <dd>{clock.dateTime(u.consumed_at)}</dd>
            </>
          ) : null}
        </dl>
      </section>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <section className="card" data-testid="serial-parent">
          <div className="card-header">
            <h2>Fitted into</h2>
          </div>
          <div className="card-body">{u.parent ? <UnitLine u={u.parent} /> : <span className="muted">Not fitted into another unit.</span>}</div>
        </section>
        <section className="card" data-testid="serial-children">
          <div className="card-header">
            <h2>Units fitted into it ({u.children.length})</h2>
          </div>
          <div className="card-body col" style={{ gap: 6 }}>
            {u.children.length ? u.children.map((c) => <UnitLine key={c.id} u={c} />) : <span className="muted">None recorded.</span>}
          </div>
        </section>
      </div>
      {u.consumed_by_wo ? (
        <p style={{ margin: 0 }}>
          Fitted in work order{" "}
          <Link to={mfgPaths.workOrder(u.consumed_by_wo.id)} className="mono">
            {u.consumed_by_wo.number}
          </Link>{" "}
          (the parent item has no serial numbers).
        </p>
      ) : null}
      {u.wo ? (
        <Link className="btn ghost sm" style={{ alignSelf: "flex-start" }} to={mfgPaths.floorEvents({ wo: u.wo.id })}>
          <Icon name="list" /> Floor events of {u.wo.number}
        </Link>
      ) : null}
      <p className="faint small" style={{ margin: 0 }}>
        One level shown. Full genealogy and recall reports come with traceability (M5).
      </p>
    </div>
  );
}
