/**
 * Recalls (M5 6.3): `/mfg/recalls` (list; `?new=1&kind=&id=` or `?item=&supplier_lot=` opens a new one from the
 * trace) and `/mfg/recalls/:id` (the report): every affected unit and lot by status - in stock (where), in production
 * (which work order), shipped (customer, date), fitted into a parent - each marked exact or possible, with counts per
 * customer and programme; export to Excel or print; "Quarantine" moves the in-stock affected lots to a quarantine
 * location and puts them on hold (store keepers, one transfer posting per balance).
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Banner } from "../../../components/Banner";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Icon } from "../../../components/Icon";
import { saveBlob } from "../../api/client";
import { listLocations } from "../../api/clientM2";
import { createRecall, exportRecall, getRecall, listRecalls, quarantineRecall } from "../../api/clientM5";
import type { Precision, QuarantineResult, Recall, RecallSource } from "../../api/typesM5";
import { MfgError, Spinner } from "../../components/Feedback";
import { fmtNum } from "../../lib/formatM2";
import { mfgPaths } from "../../lib/paths";
import { needsText, useCan } from "../../lib/permissions";
import { usePaged } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";
import { PrecisionTag } from "./TracePages";

const STATUS: Record<string, { label: string; tone: string; icon: "layers" | "play" | "flag" | "circle" }> = {
  in_stock: { label: "In stock", tone: "warn", icon: "layers" },
  wip: { label: "In production", tone: "accent", icon: "play" },
  shipped: { label: "Shipped", tone: "danger", icon: "flag" },
  consumed: { label: "Fitted into a parent", tone: "info", icon: "circle" },
};

export function RecallsPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const canView = useCan("trace_view");
  const data = usePaged<Recall>((offset, limit, signal) => listRecalls({ limit, offset }, signal), []);
  const fromTrace = params.get("new") === "1" || Boolean(params.get("supplier_lot"));
  const [name, setName] = useState(() => (params.get("label") ? `Recall ${params.get("label")}` : ""));
  const [possible, setPossible] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    document.title = "Recalls - SuperPlanner";
  }, []);
  const source: RecallSource | null = params.get("kind") && params.get("id") ? { kind: params.get("kind") as RecallSource["kind"], id: params.get("id")! } : params.get("item") && params.get("supplier_lot") ? { item_id: params.get("item")!, supplier_lot: params.get("supplier_lot")! } : null;
  return (
    <div className="col gap-lg" data-testid="recalls-page">
      <div className="mfg-page-head">
        <div>
          <h1>Recalls</h1>
          <p>Everything a suspect lot or unit may have reached, and where it is now.</p>
        </div>
        <Link className="btn" to={mfgPaths.trace()}>
          <Icon name="zoom-in" /> Trace something first
        </Link>
      </div>
      {fromTrace && source ? (
        <section className="card" data-testid="recall-new">
          <div className="card-header">
            <h2>New recall</h2>
          </div>
          <div className="card-body col">
            <p style={{ margin: 0 }}>
              Starting from <strong className="mono">{params.get("label") ?? source.id ?? source.supplier_lot}</strong>.
            </p>
            <div className="field" style={{ maxWidth: 480 }}>
              <label htmlFor="rc-name">Name</label>
              <input id="rc-name" className="input" value={name} onChange={(e) => setName(e.target.value)} data-testid="recall-name" />
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={possible} onChange={(e) => setPossible(e.target.checked)} />
              <span>
                <strong>Include possible links</strong> <span className="muted small">Units made from work orders that used the lot, even where the exact unit was not recorded (safer; more units).</span>
              </span>
            </label>
            <MfgError error={error} />
            <div>
              <button
                type="button"
                className="btn primary"
                disabled={!canView || busy || !name.trim()}
                title={canView ? undefined : needsText("trace_view")}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    const r = await createRecall({ name: name.trim(), sources: [source], include_possible: possible });
                    navigate(mfgPaths.recall(r.id));
                  } catch (e) {
                    setError(e);
                    setBusy(false);
                  }
                }}
                data-testid="recall-create"
              >
                <Icon name="alert" /> Build the recall report
              </button>
            </div>
          </div>
        </section>
      ) : null}
      <MfgError error={data.error} onRetry={data.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="recall-list">
          <thead>
            <tr>
              <th>Recall</th>
              <th>Created</th>
              <th className="right">Units</th>
              <th className="right">Shipped</th>
              <th className="right">Customers</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  {data.loading ? "Loading…" : "No recalls."}
                </td>
              </tr>
            ) : null}
            {data.rows.map((r) => (
              <tr key={r.id} data-testid="recall-row">
                <td>
                  <Link to={mfgPaths.recall(r.id)}>
                    <span className="mono">{r.number}</span> {r.name}
                  </Link>
                  {r.quarantined_at ? <div className="small faint">quarantined {new Date(r.quarantined_at).toLocaleDateString()}</div> : null}
                </td>
                <td className="small">{new Date(r.created_at).toLocaleString()}</td>
                <td className="right">{fmtNum(r.report?.units.length ?? 0)}</td>
                <td className="right">{fmtNum((r.report?.units ?? []).filter((u) => u.status === "shipped").length)}</td>
                <td className="right">{fmtNum(r.report?.by_customer.length ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function RecallPage() {
  const { recallId = "" } = useParams();
  const canQuarantine = useCan("inventory");
  const rc = useLoad((signal) => getRecall(recallId, signal), [recallId]);
  const locs = useLoad((signal) => listLocations({ active: true }, signal).catch(() => null), []);
  const [status, setStatus] = useState("");
  const [prec, setPrec] = useState<"" | Precision>("");
  const [loc, setLoc] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [qResult, setQResult] = useState<QuarantineResult | null>(null);
  const [qError, setQError] = useState<unknown>(null);
  const r = rc.data;
  const rep = r?.report ?? null;
  const units = useMemo(() => (rep?.units ?? []).filter((u) => (!status || u.status === status) && (!prec || u.precision === prec)), [rep, status, prec]);
  const quarantineLocs = (locs.data?.items ?? []).filter((l) => l.kind === "quarantine");
  useEffect(() => {
    if (!loc && quarantineLocs[0]) setLoc(quarantineLocs[0].id);
  }, [quarantineLocs, loc]);
  if (rc.loading && !r) return <Spinner label="Building the recall report…" />;
  if (!r) return <MfgError error={rc.error} onRetry={rc.reload} />;
  const all = rep?.units ?? [];
  const by = (st: string) => all.filter((u) => u.status === st).length;
  const exact = all.filter((u) => u.precision === "exact").length;
  const lotsToMove = (rep?.lots ?? []).filter((l) => l.on_hand > 0 && !l.on_hold);
  return (
    <div className="col gap-lg print-page" data-testid="recall-page">
      <nav className="breadcrumb no-print" aria-label="Breadcrumb">
        <Link to={mfgPaths.recalls()}>Recalls</Link> <Icon name="chevron-right" size={12} /> <span className="mono">{r.number}</span>
      </nav>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>
          <span className="mono">{r.number}</span> {r.name}
        </h1>
        <span className="row no-print">
          <button type="button" className="btn" onClick={async () => saveBlob(await exportRecall(r.id))} data-testid="recall-export">
            <Icon name="download" /> Excel
          </button>
          <button type="button" className="btn" onClick={() => window.print()}>
            <Icon name="file" /> Print
          </button>
        </span>
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        {r.include_possible ? "Includes possible links (lot level)." : "Exact links only."} Created {new Date(r.created_at).toLocaleString()}.
      </p>
      <div className="kpis" data-testid="recall-summary" data-units={all.length}>
        <div className="card kpi">
          <div className="kpi-label">Affected units</div>
          <div className="kpi-value">{fmtNum(all.length)}</div>
          <div className="kpi-sub">
            {fmtNum(exact)} exact · {fmtNum(all.length - exact)} possible
          </div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">Shipped</div>
          <div className="kpi-value" style={{ color: by("shipped") ? "var(--danger)" : undefined }}>
            {fmtNum(by("shipped"))}
          </div>
          <div className="kpi-sub">to {fmtNum(rep?.by_customer.length ?? 0)} customers</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">In stock</div>
          <div className="kpi-value">{fmtNum(by("in_stock"))}</div>
          <div className="kpi-sub">{fmtNum(rep?.lots.length ?? 0)} lots</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">In production</div>
          <div className="kpi-value">{fmtNum(by("wip"))}</div>
          <div className="kpi-sub">{fmtNum(rep?.wos.length ?? 0)} work orders</div>
        </div>
        <div className="card kpi">
          <div className="kpi-label">Fitted into parents</div>
          <div className="kpi-value">{fmtNum(by("consumed"))}</div>
        </div>
      </div>

      <section className="card no-print" data-testid="recall-quarantine">
        <div className="card-header">
          <h2>Stop it moving</h2>
        </div>
        <div className="card-body col">
          {r.quarantined_at ? (
            <Banner tone="ok" title="Quarantined">
              Affected stock was moved and put on hold on {new Date(r.quarantined_at).toLocaleString()}.
            </Banner>
          ) : null}
          {qResult ? (
            <Banner tone="ok" title="Quarantine done" testId="quarantine-done">
              {qResult.moved !== undefined ? `${qResult.moved} balances moved` : "Stock moved"}
              {qResult.lots_on_hold !== undefined ? `, ${qResult.lots_on_hold} lots on hold` : ""}.
            </Banner>
          ) : null}
          <table className="table">
            <tbody>
              {(rep?.lots ?? []).length === 0 ? (
                <tr>
                  <td className="muted">No affected stock on hand.</td>
                </tr>
              ) : null}
              {(rep?.lots ?? []).map((l, i) => (
                <tr key={i} data-testid="quarantine-lot">
                  <td className="mono">{l.item}</td>
                  <td className="mono">lot {l.lot_code}</td>
                  <td className="right">{fmtNum(l.on_hand)}</td>
                  <td>{l.location ?? ""}</td>
                  <td>
                    {l.on_hold ? (
                      <span className="badge warn">
                        <Icon name="lock" /> on hold
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rep?.open_pos.length ? (
            <p className="small" style={{ margin: 0 }}>
              Open purchase orders of the suspect item: {rep.open_pos.map((p) => `${p.number}${p.qty ? ` (${fmtNum(p.qty)})` : ""}`).join(", ")}. Check with the supplier before receiving more.
            </p>
          ) : null}
          {lotsToMove.length && !r.quarantined_at ? (
            <div className="row wrap" style={{ alignItems: "flex-end" }}>
              <div className="field">
                <label htmlFor="rc-loc">Move to</label>
                <select id="rc-loc" className="select" value={loc} onChange={(e) => setLoc(e.target.value)} data-testid="quarantine-location">
                  {quarantineLocs.length === 0 ? <option value="">No quarantine location: add one under Inventory, Locations</option> : null}
                  {quarantineLocs.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.code} · {l.name}
                    </option>
                  ))}
                </select>
              </div>
              <button type="button" className="btn danger" disabled={!canQuarantine || !loc} title={canQuarantine ? undefined : needsText("inventory")} onClick={() => setConfirm(true)} data-testid="quarantine-run">
                <Icon name="lock" /> Quarantine {lotsToMove.length} lot{lotsToMove.length === 1 ? "" : "s"}
              </button>
            </div>
          ) : null}
          <MfgError error={qError} />
        </div>
      </section>

      {rep?.by_customer.length || rep?.by_program.length ? (
        <div className="grid-2" style={{ alignItems: "start" }}>
          <section className="card">
            <div className="card-header">
              <h2>Per customer</h2>
            </div>
            <table className="table" data-testid="recall-customers">
              <tbody>
                {(rep?.by_customer ?? []).map((c, i) => (
                  <tr key={i}>
                    <td>{c.customer}</td>
                    <td className="right">{fmtNum(c.units)} units</td>
                    {c.exact !== undefined ? <td className="right small">{fmtNum(c.exact)} exact</td> : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          {rep?.by_program.length ? (
            <section className="card">
              <div className="card-header">
                <h2>Per programme</h2>
              </div>
              <table className="table">
                <tbody>
                  {rep.by_program.map((c, i) => (
                    <tr key={i}>
                      <td>{c.program}</td>
                      <td className="right">{fmtNum(c.units)} units</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}
        </div>
      ) : null}

      <section className="card">
        <div className="card-header row wrap" style={{ justifyContent: "space-between" }}>
          <h2>Affected units ({units.length})</h2>
          <span className="row no-print">
            <select className="select sm" style={{ width: "auto" }} aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any status</option>
              {Object.entries(STATUS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </select>
            <select className="select sm" style={{ width: "auto" }} aria-label="Precision" value={prec} onChange={(e) => setPrec(e.target.value as "" | Precision)}>
              <option value="">Exact and possible</option>
              <option value="exact">Exact only</option>
              <option value="possible">Possible only</option>
            </select>
          </span>
        </div>
        <div className="table-wrap">
          <table className="table" data-testid="recall-units">
            <thead>
              <tr>
                <th>Unit</th>
                <th>Item</th>
                <th>Status</th>
                <th>Where</th>
                <th>Link</th>
                <th>Path</th>
              </tr>
            </thead>
            <tbody>
              {units.map((u, i) => {
                const st = STATUS[u.status] ?? { label: u.status, tone: "info", icon: "circle" as const };
                return (
                  <tr key={`${u.serial}-${i}`} data-testid="recall-unit" data-status={u.status} data-precision={u.precision}>
                    <td className="mono">{u.serial}</td>
                    <td className="mono">{u.item}</td>
                    <td>
                      <span className={`badge ${st.tone}`}>
                        <Icon name={st.icon} /> {st.label}
                      </span>
                    </td>
                    <td className="small">
                      {u.status === "shipped" ? (
                        <>
                          {u.customer ?? ""} {u.demand_order ? <span className="mono">{u.demand_order}</span> : null}
                          {u.shipped_on ? <div className="faint">{u.shipped_on}</div> : null}
                        </>
                      ) : u.status === "wip" ? (
                        <span className="mono">{u.wo ?? ""}</span>
                      ) : u.status === "consumed" ? (
                        <>in {u.parent ?? "a parent unit"}</>
                      ) : (
                        u.location ?? ""
                      )}
                    </td>
                    <td>
                      <PrecisionTag p={u.precision} />
                    </td>
                    <td className="small faint">{u.path.join(" › ")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      {confirm ? (
        <ConfirmDialog
          title={`Quarantine ${lotsToMove.length} lot${lotsToMove.length === 1 ? "" : "s"}?`}
          confirmLabel="Move and hold"
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={async () => {
            setConfirm(false);
            setQError(null);
            try {
              setQResult(await quarantineRecall(r.id, { location_id: loc }));
              rc.reload();
            } catch (e) {
              setQError(e);
            }
          }}
        >
          <p style={{ margin: 0 }}>The in-stock quantities are moved to the quarantine location by transfer postings and the lots are put on hold, so MRP and issues stop using them. Units in production or shipped are listed for follow-up.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
