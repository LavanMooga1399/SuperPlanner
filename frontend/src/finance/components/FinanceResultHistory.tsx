import { Link } from "react-router-dom";
import { ErrorBanner, Loading } from "../../components/Banner";
import { useAsync } from "../../lib/useAsync";
import { fmtLocal } from "../../lib/time";
import { listFinanceResults } from "../api/client";
import { formatMoney } from "../lib/money";
import { StatusPill } from "./StatusPill";

export function FinanceResultHistory({ planId, currentId, currency, locale, refreshKey }: { planId: string; currentId: string | null; currency: string; locale: string; refreshKey?: unknown }) {
  const list = useAsync((s) => listFinanceResults(planId, undefined, s), [planId, refreshKey]);
  return (
    <section className="card" aria-labelledby="fin-history-title" data-testid="fin-result-history">
      <div className="card-header">
        <h2 id="fin-history-title">Earlier results</h2>
      </div>
      {list.loading && !list.data ? (
        <Loading label="Loading results…" />
      ) : list.error ? (
        <div className="card-body"><ErrorBanner error={list.error} onRetry={list.reload} /></div>
      ) : (
        <div className="table-wrap" style={{ border: "none", borderRadius: 0 }}>
          <table className="table">
            <caption className="sr-only">Results of this plan, newest first</caption>
            <thead>
              <tr>
                <th scope="col">Made</th>
                <th scope="col">Kind</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">On track</th>
                <th scope="col" className="num">Monthly now</th>
                <th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {(list.data?.items ?? []).map((r) => (
                <tr key={r.id} aria-current={r.id === currentId ? "true" : undefined}>
                  <td>{fmtLocal(r.created_at)}{r.id === currentId ? <span className="chip" style={{ marginLeft: 6 }}>shown</span> : null}</td>
                  <td>{r.kind === "what_if" ? `What-if${r.label ? `: ${r.label}` : ""}` : `Plan v${r.base_plan_version}`}</td>
                  <td><StatusPill kind={r.feasibility} /></td>
                  <td className="num">{r.goals_on_track} / {r.goals_total}</td>
                  <td className="num">{formatMoney(r.monthly_contribution_now, currency, locale)}</td>
                  <td className="right nowrap">
                    <Link className="btn sm ghost" to={`/finance/${planId}/results?result=${r.id}`}>Open</Link>
                    {currentId && r.id !== currentId ? (
                      <Link className="btn sm ghost" to={`/finance/${planId}/compare?a=${currentId}&b=${r.id}`}>Compare</Link>
                    ) : null}
                  </td>
                </tr>
              ))}
              {list.data && !list.data.items.length ? (
                <tr><td colSpan={6} className="muted">No results yet.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
