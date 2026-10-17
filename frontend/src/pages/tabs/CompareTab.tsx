import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { compareSchedules, errorMessage, listSchedules } from "../../api/client";
import type { Comparison } from "../../api/types";
import { ErrorBanner, Loading } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { ScheduleComparison } from "../../components/ScheduleComparison";
import { useTerms } from "../../lib/terms";
import { useAsync } from "../../lib/useAsync";
import { useLoadedPlan } from "../../state/PlanContext";
import { scheduleOptionLabel } from "./ScheduleTab";

export function CompareTab() {
  const { planId, draft } = useLoadedPlan();
  const terms = useTerms();
  const [params, setParams] = useSearchParams();
  const list = useAsync((s) => listSchedules(planId, undefined, s), [planId]);
  const items = list.data?.items ?? [];
  const approved = items.find((s) => s.status === "approved");
  const defA = approved?.id ?? items[1]?.id ?? items[0]?.id ?? "";
  const defB = items.find((s) => s.id !== defA)?.id ?? "";
  const a = params.get("a") ?? defA;
  const b = params.get("b") ?? defB;
  const [cmp, setCmp] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!a || !b || a === b) {
      setCmp(null);
      return;
    }
    const ac = new AbortController();
    setLoading(true);
    setError(null);
    compareSchedules(a, b, ac.signal)
      .then(setCmp)
      .catch((err) => !ac.signal.aborted && setError(errorMessage(err)))
      .finally(() => !ac.signal.aborted && setLoading(false));
    return () => ac.abort();
  }, [a, b]);

  if (list.loading && !list.data) return <Loading />;
  if (list.error) return <ErrorBanner error={list.error} onRetry={list.reload} />;
  if (items.length < 2)
    return (
      <div className="card empty">
        <Icon name="compare" size={32} />
        <strong>Nothing to compare yet</strong>
        <span>You need at least two {terms.scheduleL}s. Each optimization run creates a recommended one and usually some alternatives.</span>
      </div>
    );

  const set = (k: "a" | "b", v: string) => {
    const next = new URLSearchParams(params);
    next.set("a", k === "a" ? v : a);
    next.set("b", k === "b" ? v : b);
    setParams(next);
  };

  return (
    <div className="col gap-lg">
      <div className="toolbar" style={{ marginBottom: 0, alignItems: "flex-end" }}>
        <div className="field" style={{ minWidth: 280 }}>
          <label htmlFor="cmp-a">A (baseline)</label>
          <select id="cmp-a" className="select" value={a} onChange={(e) => set("a", e.target.value)}>
            {items.map((s) => <option key={s.id} value={s.id}>{scheduleOptionLabel(s)}</option>)}
          </select>
        </div>
        <button className="btn icon" aria-label="Swap A and B" title="Swap" onClick={() => setParams({ a: b, b: a })}>
          <Icon name="refresh" />
        </button>
        <div className="field" style={{ minWidth: 280 }}>
          <label htmlFor="cmp-b">B</label>
          <select id="cmp-b" className="select" value={b} onChange={(e) => set("b", e.target.value)}>
            {items.map((s) => <option key={s.id} value={s.id}>{scheduleOptionLabel(s)}</option>)}
          </select>
        </div>
      </div>
      {a === b ? <div className="small muted">Choose two different {terms.scheduleL}s.</div> : null}
      <ErrorBanner error={error} />
      {loading && !cmp ? <Loading label="Comparing…" /> : null}
      {cmp ? <ScheduleComparison cmp={cmp} draft={draft} terms={terms} /> : null}
    </div>
  );
}
