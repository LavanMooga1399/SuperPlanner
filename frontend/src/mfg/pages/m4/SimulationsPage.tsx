/**
 * `/mfg/schedule/simulations` and `/:simulationId` (M4 8, #224-226): the risk run. It replays the plan many times
 * with supplier delays and line breakdowns drawn from this plant's own history and shows, per demand line, the
 * chance of shipping on time and the typical (P50) and bad-case (P90) completion. Guided defaults (published plan,
 * 20 runs); seed and horizon are expert settings.
 */
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { getApsRun, getPublishedRun, listApsRuns } from "../../api/clientM3";
import { createSimulation, getSimulation, listSimulations } from "../../api/clientM4";
import type { Simulation, SimulationDemand } from "../../api/typesM4";
import { MfgError, Spinner } from "../../components/Feedback";
import { fmtDuration, usePlantClock } from "../../lib/plantTime";
import { mfgPaths } from "../../lib/paths";
import { needsText, useCan } from "../../lib/permissions";
import { useLoad } from "../../lib/useMfg";
import { usePolling } from "../../lib/usePolling";

const active = (s: Simulation) => s.status === "queued" || s.status === "running";

function SimStatus({ s }: { s: Simulation }) {
  if (s.status === "completed")
    return (
      <span className="badge ok">
        <Icon name="check" /> Done
      </span>
    );
  if (s.status === "failed")
    return (
      <span className="badge danger">
        <Icon name="alert" /> Failed
      </span>
    );
  return (
    <span className="badge accent" role="status">
      <span className="spinner" aria-hidden /> {s.status === "queued" ? "Waiting" : `Running${s.results ? ` ${s.results.samples_done}/${s.samples}` : ""}`}
    </span>
  );
}

export function SimulationsPage() {
  const clock = usePlantClock();
  const navigate = useNavigate();
  const canRun = useCan("schedule_run");
  const sims = useLoad((signal) => listSimulations({ limit: 50 }, signal), []);
  usePolling(sims.reload, (sims.data?.items ?? []).some(active));
  const runs = useLoad((signal) => listApsRuns({ status: "completed", limit: 50, offset: 0 }, signal), []);
  const published = useLoad((signal) => getPublishedRun(signal).catch(() => null), []);
  const [base, setBase] = useState(() => new URLSearchParams(window.location.search).get("base") ?? "");
  const [samples, setSamples] = useState("20");
  const [expert, setExpert] = useState(false);
  const [seed, setSeed] = useState("");
  const [horizon, setHorizon] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const baseId = base || published.data?.id || "";
  const runLabel = (id: string) => {
    const r = (runs.data?.items ?? []).find((x) => x.id === id);
    return r ? `Schedule #${r.run_no}${r.label ? ` · ${r.label}` : ""}` : "an earlier schedule";
  };

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = await createSimulation({
        base_run_id: baseId,
        samples: Math.min(50, Math.max(1, Number(samples) || 20)),
        ...(expert && seed ? { seed: Number(seed) } : {}),
        ...(expert && horizon ? { horizon_days: Number(horizon) } : {}),
      });
      navigate(mfgPaths.simulation(s.id));
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };

  return (
    <div className="col gap-lg" data-testid="sim-page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to={mfgPaths.schedule()}>Schedule</Link> <Icon name="chevron-right" size={12} /> <span>Risk</span>
      </nav>
      <h1 style={{ margin: 0 }}>Delivery risk</h1>
      <section className="card">
        <div className="card-header">
          <h2>Check a plan against real-world delays</h2>
        </div>
        <div className="card-body col">
          <p className="muted" style={{ margin: 0 }}>
            The plan is replayed many times with supplier delays and line breakdowns like the ones this plant has seen. You get the chance each demand line ships on time.
          </p>
          <div className="row wrap">
            <div className="field" style={{ minWidth: 320 }}>
              <label htmlFor="sim-base">Plan</label>
              <select id="sim-base" className="select" value={baseId} onChange={(e) => setBase(e.target.value)} data-testid="sim-base">
                {!baseId ? <option value="">Choose a schedule…</option> : null}
                {(runs.data?.items ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    Schedule #{r.run_no}
                    {r.label ? ` · ${r.label}` : ""}
                    {r.is_published ? " (published)" : ""}
                  </option>
                ))}
              </select>
            </div>
            <div className="field" style={{ width: 140 }}>
              <label htmlFor="sim-samples">Replays</label>
              <input id="sim-samples" className="input" type="number" min={1} max={50} value={samples} onChange={(e) => setSamples(e.target.value)} />
            </div>
          </div>
          <button type="button" className="btn ghost sm" style={{ alignSelf: "flex-start" }} aria-expanded={expert} onClick={() => setExpert((v) => !v)}>
            <Icon name="settings" /> Expert settings
          </button>
          {expert ? (
            <div className="row wrap">
              <div className="field" style={{ width: 160 }}>
                <label htmlFor="sim-seed">Random seed</label>
                <input id="sim-seed" className="input" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="automatic" />
                <span className="faint small">Same seed, same result.</span>
              </div>
              <div className="field" style={{ width: 160 }}>
                <label htmlFor="sim-h">Horizon (days)</label>
                <input id="sim-h" className="input" type="number" min={1} value={horizon} onChange={(e) => setHorizon(e.target.value)} placeholder="as the plan" />
              </div>
            </div>
          ) : null}
          <MfgError error={error} />
          <div>
            <button type="button" className="btn primary" disabled={!canRun || !baseId || busy} title={canRun ? undefined : needsText("schedule_run")} onClick={() => void start()} data-testid="sim-start">
              <Icon name="play" /> Check the risk
            </button>
          </div>
        </div>
      </section>
      <MfgError error={sims.error} onRetry={sims.reload} />
      <div className="table-wrap card">
        <table className="table" data-testid="sim-list">
          <thead>
            <tr>
              <th>Check</th>
              <th>Plan</th>
              <th>Replays</th>
              <th>Status</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {(sims.data?.items ?? []).length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  {sims.loading ? "Loading…" : "No risk checks yet."}
                </td>
              </tr>
            ) : null}
            {(sims.data?.items ?? []).map((s) => (
              <tr key={s.id}>
                <td>
                  <Link to={mfgPaths.simulation(s.id)}>Risk check {s.id.slice(-6)}</Link>
                </td>
                <td>{runLabel(s.base_run_id)}</td>
                <td>{s.samples}</td>
                <td>
                  <SimStatus s={s} />
                </td>
                <td className="small">{clock.dateTime(s.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Without per-sample detail: due date against base plan, P50 and P90 on one time strip. */
function RangeStrip({ r, clock }: { r: SimulationDemand; clock: ReturnType<typeof usePlantClock> }) {
  const pts = [
    { k: "Due", t: r.due, c: "var(--text)" },
    { k: "Plan", t: r.base_end, c: "var(--text-muted)" },
    { k: "P50", t: r.p50, c: "var(--accent)" },
    { k: "P90", t: r.p90, c: "var(--warn)" },
  ].filter((p): p is { k: string; t: string; c: string } => Boolean(p.t));
  const ms = pts.map((p) => Date.parse(p.t));
  const lo = Math.min(...ms);
  const hi = Math.max(...ms);
  const W = 420;
  const x = (m: number) => 10 + ((m - lo) / Math.max(1, hi - lo)) * (W - 20);
  return (
    <figure style={{ margin: 0 }}>
      <svg width={W} height={58} role="img" aria-label={pts.map((p) => `${p.k} ${clock.dateTime(p.t)}`).join(", ")}>
        <line x1={10} x2={W - 10} y1={24} y2={24} stroke="var(--border-strong)" />
        {r.p50 && r.p90 ? <rect x={x(Date.parse(r.p50))} y={18} width={Math.max(2, x(Date.parse(r.p90)) - x(Date.parse(r.p50)))} height={12} fill="var(--warn-soft)" /> : null}
        {pts.map((p, i) => (
          <g key={p.k}>
            <line x1={x(Date.parse(p.t))} x2={x(Date.parse(p.t))} y1={12} y2={36} stroke={p.c} strokeWidth={p.k === "Due" ? 2.5 : 2} strokeDasharray={p.k === "Due" ? "3 2" : undefined} />
            <text x={x(Date.parse(p.t))} y={i % 2 ? 50 : 9} textAnchor="middle" fontSize={10} fill={p.c}>
              {p.k}
            </text>
          </g>
        ))}
      </svg>
      <figcaption className="faint small">Shaded: half of the replays finish after P50, one in ten after P90.</figcaption>
    </figure>
  );
}

function Histogram({ r, clock }: { r: SimulationDemand; clock: ReturnType<typeof usePlantClock> }) {
  const vals = r.samples_late_minutes ?? [];
  if (!vals.length) return <RangeStrip r={r} clock={clock} />;
  // bins: early/on time, then late in 4 h steps up to 3 days, rest
  const edges = [0, 240, 480, 1440, 2880, 4320];
  const labels = ["on time", "< 4 h", "4-8 h", "8 h-1 d", "1-2 d", "2-3 d", "> 3 d"];
  const counts = new Array(labels.length).fill(0) as number[];
  for (const v of vals) {
    if (v <= 0) counts[0]++;
    else {
      let k = edges.findIndex((e, i) => i > 0 && v <= e);
      if (k === -1) k = edges.length;
      counts[k]++;
    }
  }
  const max = Math.max(...counts, 1);
  const W = 26;
  const H = 60;
  return (
    <figure className="sim-hist" style={{ margin: 0 }}>
      <svg width={labels.length * (W + 4)} height={H + 28} role="img" aria-label={`Completion spread: ${labels.map((l, i) => `${l} ${counts[i]}`).join(", ")}`}>
        {counts.map((c, i) => {
          const h = (c / max) * H;
          return (
            <g key={i} transform={`translate(${i * (W + 4)},0)`}>
              <rect x={0} y={H - h} width={W} height={h} fill={i === 0 ? "var(--ok)" : "var(--warn)"} />
              <text x={W / 2} y={H - h - 2} textAnchor="middle" fontSize={10} fill="var(--text)">
                {c || ""}
              </text>
              <text x={W / 2} y={H + 12} textAnchor="middle" fontSize={9} fill="var(--text-muted)">
                {labels[i]}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="faint small">Replays by how late the line finished</figcaption>
    </figure>
  );
}

export function SimulationPage() {
  const { simulationId = "" } = useParams();
  const clock = usePlantClock();
  const s = useLoad((signal) => getSimulation(simulationId, signal), [simulationId]);
  usePolling(s.reload, Boolean(s.data && active(s.data)));
  const [open, setOpen] = useState<string | null>(null);
  const [sort, setSort] = useState<"risk" | "due">("risk");
  const lines = useMemo(() => {
    const arr = [...(s.data?.results?.demand ?? [])];
    arr.sort((a, b) => (sort === "risk" ? a.p_on_time - b.p_on_time : Date.parse(a.due) - Date.parse(b.due)));
    return arr;
  }, [s.data, sort]);
  const sim = s.data;
  const base = useLoad((signal) => (sim?.base_run_id ? getApsRun(sim.base_run_id, signal).catch(() => null) : null), [sim?.base_run_id]);
  if (s.loading && !sim) return <Spinner />;
  if (!sim) return <MfgError error={s.error} onRetry={s.reload} />;
  const res = sim.results;
  const atRisk = lines.filter((l) => l.p_on_time < 0.8).length;
  const topSupplier = res ? [...res.suppliers].sort((a, b) => b.late_lines - a.late_lines)[0] ?? null : null;
  return (
    <div className="col gap-lg" data-testid="sim-detail" data-status={sim.status}>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to={mfgPaths.schedule()}>Schedule</Link> <Icon name="chevron-right" size={12} /> <Link to={mfgPaths.simulations()}>Risk</Link> <Icon name="chevron-right" size={12} />{" "}
        <span>Check {sim.id.slice(-6)}</span>
      </nav>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>Delivery risk</h1>
        <span className="row wrap">
          <SimStatus s={sim} />
          <Link to={mfgPaths.apsRun(sim.base_run_id)}>Plan: {base.data ? `schedule #${base.data.run_no}${base.data.label ? ` · ${base.data.label}` : ""}` : "schedule"}</Link>
          <span className="faint small">
            {sim.samples} replays{sim.params.seed !== undefined ? ` · seed ${sim.params.seed}` : ""}
          </span>
        </span>
      </div>
      {sim.status === "failed" ? <div className="banner danger">{sim.error?.message ?? "The risk check failed."}</div> : null}
      {active(sim) ? <Spinner label="Replaying the plan…" /> : null}
      {res ? (
        <>
          <div className="kpis">
            <div className="card kpi">
              <div className="kpi-label">Demand lines at risk</div>
              <div className="kpi-value">{atRisk}</div>
              <div className="kpi-sub">less than 80% chance on time, of {lines.length}</div>
            </div>
            <div className="card kpi">
              <div className="kpi-label">Biggest supplier risk</div>
              <div className="kpi-value" style={{ fontSize: 20 }}>
                {topSupplier ? topSupplier.supplier.code : "none"}
              </div>
              {topSupplier ? (
                <div className="kpi-sub">
                  {topSupplier.late_lines} late lines in the replays · typically {topSupplier.mean_delay_days.toFixed(1)} days late
                </div>
              ) : null}
            </div>
            <div className="card kpi">
              <div className="kpi-label">Expected lost line time</div>
              <div className="kpi-value">{fmtDuration(res.lines.reduce((a, l) => a + l.expected_lost_hours, 0) * 60) || "0"}</div>
            </div>
          </div>
          <section className="card">
            <div className="card-header row wrap" style={{ justifyContent: "space-between" }}>
              <h2>Demand lines</h2>
              <select className="select sm" style={{ width: "auto" }} aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value as "risk" | "due")}>
                <option value="risk">Most at risk first</option>
                <option value="due">By due date</option>
              </select>
            </div>
            <div className="table-wrap">
              <table className="table" data-testid="sim-table">
                <thead>
                  <tr>
                    <th>Demand line</th>
                    <th>Item</th>
                    <th>Due</th>
                    <th>Chance on time</th>
                    <th>Typical finish (P50)</th>
                    <th>Bad case (P90)</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l) => {
                    const p = Math.round(l.p_on_time * 100);
                    const tone = p >= 90 ? "ok" : p >= 60 ? "warn" : "danger";
                    return [
                      <tr key={l.demand_line_id} data-testid="sim-row" data-p-on-time={l.p_on_time}>
                        <td className="mono">{l.order}</td>
                        <td className="mono">{l.part_number}</td>
                        <td className="small">{clock.dateTime(l.due)}</td>
                        <td>
                          <span className={`badge ${tone}`}>
                            <Icon name={tone === "ok" ? "check" : "alert"} /> {p}%
                          </span>
                        </td>
                        <td className="small">{l.p50 ? clock.dateTime(l.p50) : "not finished"}</td>
                        <td className="small">{l.p90 ? clock.dateTime(l.p90) : "not finished"}</td>
                        <td>
                          <button type="button" className="btn sm ghost" aria-expanded={open === l.demand_line_id} onClick={() => setOpen(open === l.demand_line_id ? null : l.demand_line_id)}>
                            Spread
                          </button>
                        </td>
                      </tr>,
                      open === l.demand_line_id ? (
                        <tr key={`${l.demand_line_id}-h`}>
                          <td colSpan={7}>
                            <Histogram r={l} clock={clock} />
                          </td>
                        </tr>
                      ) : null,
                    ];
                  })}
                </tbody>
              </table>
            </div>
          </section>
          <div className="grid-2" style={{ alignItems: "start" }}>
            <section className="card">
              <div className="card-header">
                <h2>Suppliers behind late lines</h2>
              </div>
              <table className="table">
                <tbody>
                  {res.suppliers.length === 0 ? (
                    <tr>
                      <td className="muted">No supplier caused lateness in the replays.</td>
                    </tr>
                  ) : null}
                  {[...res.suppliers].sort((a, b) => b.late_lines - a.late_lines).map((x) => (
                    <tr key={x.supplier.id} data-testid="sim-supplier">
                      <td>
                        {x.supplier.code}
                        {x.supplier.name ? <div className="faint small">{x.supplier.name}</div> : null}
                      </td>
                      <td className="right">{x.late_lines} late lines</td>
                      <td className="right">
                        {x.mean_delay_days.toFixed(1)} days late on average
                        <div className="faint small">from {x.history_receipts} past deliveries</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section className="card">
              <div className="card-header">
                <h2>Expected breakdown time per line</h2>
              </div>
              <table className="table">
                <tbody>
                  {res.lines.map((x) => (
                    <tr key={x.line.id}>
                      <td>{x.line.code}</td>
                      <td className="right">{x.expected_lost_hours.toFixed(1)} h</td>
                      <td className="right faint small">{x.mtbf_hours ? `a breakdown every ${Math.round(x.mtbf_hours)} h on average` : "no breakdown history"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}
