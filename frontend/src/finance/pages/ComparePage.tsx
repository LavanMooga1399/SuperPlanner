import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { errorMessage, isAbort } from "../../api/client";
import { ErrorBanner, Loading } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { useAsync } from "../../lib/useAsync";
import { fmtLocal } from "../../lib/time";
import { compareFinanceResults, listFinanceResults } from "../api/client";
import type { FinanceComparison, FinanceResultSummary } from "../api/types";
import { ScenarioCompareTable } from "../components/ScenarioCompareTable";
import { useLoadedFinancePlan } from "../state/FinancePlanContext";

const resultLabel = (r: FinanceResultSummary) =>
  `${r.kind === "what_if" ? `What-if${r.label ? `: ${r.label}` : ""}` : `Plan v${r.base_plan_version}`} (${fmtLocal(r.created_at)})`;

export function ComparePage() {
  const ctx = useLoadedFinancePlan();
  const planId = ctx.record.id;
  const [params, setParams] = useSearchParams();
  const a = params.get("a");
  const b = params.get("b");
  const list = useAsync((s) => listFinanceResults(planId, undefined, s), [planId]);
  const [cmp, setCmp] = useState<FinanceComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Fill missing sides with sensible defaults: A = latest baseline, B = the newest other result.
  useEffect(() => {
    const items = list.data?.items;
    if (!items || (a && b)) return;
    const na = a ?? items.find((r) => r.kind === "baseline")?.id ?? items[0]?.id ?? null;
    const nb = b ?? items.find((r) => r.id !== na)?.id ?? null;
    if (na && nb && (na !== a || nb !== b)) setParams({ a: na, b: nb }, { replace: true });
  }, [list.data, a, b, setParams]);

  useEffect(() => {
    if (!a || !b) {
      setCmp(null);
      return;
    }
    const ac = new AbortController();
    setLoading(true);
    setError(null);
    compareFinanceResults(a, b, ac.signal)
      .then((c) => !ac.signal.aborted && setCmp(c))
      .catch((err) => !isAbort(err) && setError(errorMessage(err)))
      .finally(() => !ac.signal.aborted && setLoading(false));
    return () => ac.abort();
  }, [a, b]);

  const items = list.data?.items ?? [];
  const choose = (side: "a" | "b", id: string) => {
    const n = new URLSearchParams(params);
    n.set(side, id);
    setParams(n);
  };

  return (
    <div className="col gap-lg">
      <div className="fin-header">
        <div className="col" style={{ gap: 4 }}>
          <h1>Compare scenarios</h1>
          <span className="muted">Changes are shown as B compared with A.</span>
        </div>
      </div>
      {list.loading && !list.data ? <Loading label="Loading results…" /> : null}
      <ErrorBanner error={list.error} onRetry={list.reload} />
      {list.data && items.length < 2 ? (
        <div className="empty">
          <Icon name="compare" size={28} />
          <p>You need at least two results to compare. Try a what-if scenario first.</p>
        </div>
      ) : null}
      {items.length ? (
        <div className="row wrap gap-lg">
          {(["a", "b"] as const).map((side) => (
            <div className="field" key={side} style={{ minWidth: 280 }}>
              <label htmlFor={`cmp-${side}`}>Scenario {side.toUpperCase()}</label>
              <select id={`cmp-${side}`} className="select" value={(side === "a" ? a : b) ?? ""} onChange={(e) => choose(side, e.target.value)}>
                <option value="" disabled>
                  Choose a result
                </option>
                {items.map((r) => (
                  <option key={r.id} value={r.id}>
                    {resultLabel(r)}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
      ) : null}
      <ErrorBanner error={error} />
      {loading && !cmp ? <Loading label="Comparing…" /> : null}
      {cmp ? (
        <>
          {cmp.what_if_b?.label ? <p className="muted" style={{ margin: 0 }}>B changes: {cmp.what_if_b.label}</p> : null}
          <ScenarioCompareTable
            cmp={cmp}
            currency={ctx.draft.profile.currency}
            locale={ctx.draft.profile.locale}
            labelA={`A: ${cmp.a.kind === "what_if" ? cmp.a.label ?? "What-if" : `Plan v${cmp.a.base_plan_version}`}`}
            labelB={`B: ${cmp.b.kind === "what_if" ? cmp.b.label ?? "What-if" : `Plan v${cmp.b.base_plan_version}`}`}
          />
        </>
      ) : null}
    </div>
  );
}
