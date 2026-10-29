/** `/mfg/mrp/runs/:runId/compare?with=` (M2 14.2 `CompareView`, #161): what changed between two runs. */
import { Link, useSearchParams } from "react-router";
import { Icon } from "../../../components/Icon";
import { compareRuns, listMrpRuns } from "../../api/clientM2";
import { MfgError, Spinner } from "../../components/Feedback";
import { RunKindBadge } from "../../components/StatusM2";
import { fmtDate } from "../../lib/format";
import { fmtMoney, fmtNum } from "../../lib/formatM2";
import { exceptionLabel } from "../../lib/mrpText";
import { mfgPaths } from "../../lib/paths";
import { setSearchParam } from "../../lib/usePaged";
import { useLoad } from "../../lib/useMfg";
import { runTitle } from "./MrpRunsPage";
import { useRun } from "./RunShell";

function Delta({ a, b, invert, days }: { a: number | null; b: number | null; invert?: boolean; days?: boolean }) {
  if (a === null || b === null) return null;
  const d = b - a;
  if (Math.abs(d) < 1e-9) return <span className="faint">no change</span>;
  const worse = invert ? d < 0 : d > 0;
  return (
    <span className={worse ? "mfg-neg" : "mfg-pos"} data-testid="compare-delta" data-delta={d}>
      <Icon name={worse ? "alert" : "check"} size={12} /> {d > 0 ? "+" : "−"}
      {fmtNum(Math.abs(d))}
      {days ? " d" : ""} {worse ? "worse" : "better"}
    </span>
  );
}

export function CompareView() {
  const { run } = useRun();
  const [params, setParams] = useSearchParams();
  const withId = params.get("with") ?? "";
  const runs = useLoad((signal) => listMrpRuns({ limit: 50, offset: 0 }, signal), []);
  const cmp = useLoad((signal) => (withId ? compareRuns(run.id, withId, signal) : null), [run.id, withId]);
  const others = (runs.data?.items ?? []).filter((r) => r.id !== run.id && r.status === "completed");
  const c = cmp.data;
  return (
    <div className="col gap-lg" data-testid="compare-view">
      <div className="toolbar mfg-filters">
        <div className="field" style={{ minWidth: 320 }}>
          <label htmlFor="cmp-with">Compare run #{run.run_no} with</label>
          <select id="cmp-with" className="select" value={withId} onChange={(e) => setSearchParam(setParams, "with", e.target.value)} data-testid="compare-with">
            <option value="">Choose a run…</option>
            {others.map((r) => (
              <option key={r.id} value={r.id}>
                {runTitle(r)} ({r.kind === "live" ? "live" : "what-if"}, as of {fmtDate(r.as_of)})
              </option>
            ))}
          </select>
        </div>
      </div>
      <MfgError error={runs.error ?? cmp.error} onRetry={cmp.reload} />
      {cmp.loading && withId && !c ? <Spinner label="Comparing…" /> : null}
      {c ? (
        <>
          <p className="small muted" style={{ margin: 0 }}>
            A = {runTitle(c.a)} <RunKindBadge kind={c.a.kind} /> · B = {runTitle(c.b)} <RunKindBadge kind={c.b.kind} />. Changes are B compared with A; only changed rows are listed.
          </p>
          <section className="card">
            <div className="card-header">
              <h3>Planned orders</h3>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th />
                    <th className="right">A</th>
                    <th className="right">B</th>
                    <th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Work orders to make</td>
                    <td className="right">{c.planned.a.make}</td>
                    <td className="right">{c.planned.b.make}</td>
                    <td>
                      <Delta a={c.planned.a.make} b={c.planned.b.make} />
                    </td>
                  </tr>
                  <tr>
                    <td>Quantity to make</td>
                    <td className="right">{fmtNum(c.planned.a.make_qty)}</td>
                    <td className="right">{fmtNum(c.planned.b.make_qty)}</td>
                    <td>
                      <Delta a={c.planned.a.make_qty} b={c.planned.b.make_qty} />
                    </td>
                  </tr>
                  <tr>
                    <td>Purchases</td>
                    <td className="right">{c.planned.a.buy}</td>
                    <td className="right">{c.planned.b.buy}</td>
                    <td>
                      <Delta a={c.planned.a.buy} b={c.planned.b.buy} />
                    </td>
                  </tr>
                  <tr>
                    <td>Purchase value</td>
                    <td className="right">{fmtMoney(c.planned.a.buy_value)}</td>
                    <td className="right">{fmtMoney(c.planned.b.buy_value)}</td>
                    <td>
                      <Delta a={c.planned.a.buy_value} b={c.planned.b.buy_value} />
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
          <section className="card" data-testid="compare-demand">
            <div className="card-header">
              <h3>Demand dates that changed ({c.demand.length})</h3>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Demand line</th>
                    <th>Due</th>
                    <th>Projected A</th>
                    <th>Projected B</th>
                    <th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {c.demand.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="muted">
                        No demand date changed.
                      </td>
                    </tr>
                  ) : null}
                  {c.demand.map((d, i) => (
                    <tr key={d.demand_line_id ?? i} data-testid="compare-demand-row">
                      <td className="mono">{d.label}</td>
                      <td>{fmtDate(d.due_date)}</td>
                      <td>{fmtDate(d.a_projected)}</td>
                      <td>{fmtDate(d.b_projected)}</td>
                      <td>{d.delta_days === null ? (d.b_projected ? "new" : "gone") : <Delta a={0} b={d.delta_days} days />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {c.truncated.demand ? <div className="card-footer small muted">Only the first 500 changes are listed.</div> : null}
          </section>
          <div className="grid-2" style={{ alignItems: "start" }}>
            <section className="card">
              <div className="card-header">
                <h3>Messages by kind</h3>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Message</th>
                    <th className="right">A</th>
                    <th className="right">B</th>
                    <th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {c.exceptions_by_code.map((e) => (
                    <tr key={e.code}>
                      <td>{exceptionLabel(e.code)}</td>
                      <td className="right">{e.a}</td>
                      <td className="right">{e.b}</td>
                      <td>
                        <Delta a={e.a} b={e.b} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section className="card">
              <div className="card-header">
                <h3>Parts that changed ({c.items.length})</h3>
              </div>
              <div className="table-wrap" style={{ maxHeight: 420, overflow: "auto" }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Part</th>
                      <th className="right">Planned A → B</th>
                      <th className="right">Short A → B</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.items.map((x) => (
                      <tr key={x.item.id}>
                        <td>
                          <Link to={mfgPaths.runItem(c.b.id, x.item.id)} className="mono">
                            {x.item.part_number}
                          </Link>
                        </td>
                        <td className="right">
                          {fmtNum(x.a_planned_qty)} → {fmtNum(x.b_planned_qty)}
                        </td>
                        <td className="right">
                          {fmtNum(x.a_short_qty)} → <span className={x.b_short_qty > x.a_short_qty ? "mfg-neg" : undefined}>{fmtNum(x.b_short_qty)}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {c.truncated.items ? <div className="card-footer small muted">Only the first 500 changes are listed.</div> : null}
            </section>
          </div>
        </>
      ) : !withId ? (
        <p className="muted">Pick a run to compare with, for example the live plan against a what-if scenario.</p>
      ) : null}
    </div>
  );
}
