import type { FinanceResult } from "../api/types";
import { formatPct } from "../lib/money";
import { realReturnPct } from "../lib/resultView";

const REASON_LABEL: Record<string, string> = {
  ALLOCATION_SPLIT: "Where the money goes",
  RISK_CAP: "Growth limit",
  GLIDE_DOWN: "Getting safer near the date",
  LOCKIN_EXCLUDED: "Lock-in not used",
  EF_GATED: "After the emergency fund",
  CASH_LIMITED: "Savings fully used",
  HOLDINGS_USED: "Existing savings",
  CAUTIOUS_RETURNS: "Cautious planning",
  SHORTFALL: "Shortfall",
  LOW_PROBABILITY: "Lower chance",
  ON_TRACK: "On track",
};

/** Computed explanations (FINANCE.md 12): every sentence comes from the engine's message catalog. */
export function ExplanationPanel({ result, taxNote }: { result: FinanceResult; taxNote?: string }) {
  const ex = result.explanation;
  const used = result.assumptions_used;
  return (
    <section className="card" data-testid="fin-explanations" aria-labelledby="fin-expl-title">
      <div className="card-header">
        <h2 id="fin-expl-title">Why the plan looks like this</h2>
      </div>
      <div className="card-body">
        <details className="explain-section" open>
          <summary>Summary</summary>
          <ul className="explain-list">
            {ex.summary.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </details>
        {result.goals.map((g) => {
          const ge = ex.goals[g.goal_id];
          if (!ge || !ge.reasons.length) return null;
          return (
            <details className="explain-section" key={g.goal_id} open={g.status !== "on_track"}>
              <summary>{g.name}</summary>
              <ul className="explain-list">
                {ge.reasons.map((r, i) => (
                  <li key={i}>
                    <span className="label-tag">{REASON_LABEL[r.code] ?? r.code.replace(/_/g, " ").toLowerCase()}</span> {r.message}
                  </li>
                ))}
              </ul>
            </details>
          );
        })}
        {ex.binding_constraints.length ? (
          <details className="explain-section">
            <summary>What limits the plan</summary>
            <ul className="explain-list">
              {ex.binding_constraints.map((b, i) => (
                <li key={i}>{b.message}</li>
              ))}
            </ul>
          </details>
        ) : null}
        <details className="explain-section">
          <summary>Assumptions</summary>
          <ul className="explain-list">
            {ex.assumptions.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
          <div className="table-wrap mt">
            <table className="table">
              <caption className="sr-only">Assumptions used for this result</caption>
              <thead>
                <tr>
                  <th scope="col">Asset class</th>
                  <th scope="col" className="num">Expected return<br /><span className="label-tag">Your assumption</span></th>
                  <th scope="col" className="num">Ups and downs<br /><span className="label-tag">Your assumption</span></th>
                  <th scope="col" className="num">After costs and inflation<br /><span className="label-tag">Calculated</span></th>
                </tr>
              </thead>
              <tbody>
                {used.asset_classes.map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}</td>
                    <td className="num">{formatPct(c.expected_return_pct, 1)}</td>
                    <td className="num">{formatPct(c.volatility_pct, 1)}</td>
                    <td className="num">{formatPct(realReturnPct(c, used.inflation_pct), 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">Inflation: {formatPct(used.inflation_pct, 1)} a year (your assumption).</p>
          {taxNote ? (
            <p className="small muted">
              Your tax note (not calculated): {taxNote}
            </p>
          ) : null}
        </details>
        <details className="explain-section">
          <summary>Limitations</summary>
          <ul className="explain-list">
            {ex.limitations.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </details>
        <details className="explain-section">
          <summary>When to re-plan</summary>
          <ul className="explain-list">
            {ex.replanning_triggers.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </details>
        {result.violations.length ? (
          <details className="explain-section" open={result.violations.some((v) => v.severity === "hard")}>
            <summary>Independent check findings ({result.violations.length})</summary>
            <ul className="explain-list">
              {result.violations.map((v, i) => (
                <li key={i}>
                  <span className="label-tag">{v.severity === "hard" ? "Rule broken" : "Note"}</span> {v.message}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    </section>
  );
}
