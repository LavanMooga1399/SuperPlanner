import { useCallback, useEffect, useMemo, useState } from "react";
import { Term } from "../../components/Term";
import { Link, useSearchParams } from "react-router";
import { ApiError, errorMessage, isAbort } from "../../api/client";
import { Banner, ErrorBanner, Loading } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { useStoredState } from "../../lib/useAsync";
import { createFinanceRun, getFinanceResult, listFinanceResults } from "../api/client";
import type { FinanceResult, FinanceResultRecord, FinanceRun } from "../api/types";
import { CashflowChart } from "../charts/CashflowChart";
import { LineChart } from "../charts/LineChart";
import { StackedAreaChart, type AreaLayer } from "../charts/StackedAreaChart";
import { ContributionTable } from "../components/ContributionTable";
import { ExplanationPanel } from "../components/ExplanationPanel";
import { FinanceResultHistory } from "../components/FinanceResultHistory";
import { FinRunProgress } from "../components/FinRunProgress";
import { FixList } from "../components/FixList";
import { GoalCard } from "../components/GoalCard";
import { RealNominalToggle, useMoneyBasis } from "../components/RealNominalToggle";
import { ResultHeader } from "../components/ResultHeader";
import { ResultKpis } from "../components/ResultKpis";
import { SendToPlannerDialog } from "../components/SendToPlannerDialog";
import { formatMoney } from "../lib/money";
import { classInfos } from "../lib/resultView";
import { useLoadedFinancePlan } from "../state/FinancePlanContext";

export function ResultsPage() {
  const ctx = useLoadedFinancePlan();
  const planId = ctx.record.id;
  const [params, setParams] = useSearchParams();
  const runId = params.get("run");
  const resultParam = params.get("result");
  const [resultId, setResultId] = useState<string | null>(resultParam);
  const [record, setRecord] = useState<FinanceResultRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [noResults, setNoResults] = useState(false);
  const [runEnd, setRunEnd] = useState<FinanceRun | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const [rerunError, setRerunError] = useState<string | null>(null);
  const [sendOpen, setSendOpen] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);

  // Which result to show: ?result=, else the latest baseline (unless a run is in progress).
  useEffect(() => {
    if (resultParam) {
      setResultId(resultParam);
      return;
    }
    if (runId) return;
    const ac = new AbortController();
    listFinanceResults(planId, "baseline", ac.signal)
      .then((r) => {
        if (r.items.length) setResultId(r.items[0].id);
        else setNoResults(true);
      })
      .catch((err) => !isAbort(err) && setError(errorMessage(err)));
    return () => ac.abort();
  }, [planId, resultParam, runId]);

  useEffect(() => {
    if (!resultId) return;
    const ac = new AbortController();
    setLoading(true);
    setError(null);
    getFinanceResult(resultId, ac.signal)
      .then((r) => !ac.signal.aborted && (setRecord(r), setNoResults(false)))
      .catch((err) => !isAbort(err) && setError(errorMessage(err)))
      .finally(() => !ac.signal.aborted && setLoading(false));
    return () => ac.abort();
  }, [resultId]);

  const onRunDone = useCallback(
    (run: FinanceRun | null) => {
      setRunEnd(run);
      setHistoryKey((k) => k + 1);
      if (run?.status === "completed" && run.result_id) {
        setParams({ result: run.result_id }, { replace: true });
      }
    },
    [setParams],
  );

  const rerun = async () => {
    setRerunning(true);
    setRerunError(null);
    try {
      const saved = await ctx.save();
      if (!saved) {
        setRerunError("Your latest changes could not be saved, so the plan was not re-run. Open Setup to save them, then try again.");
        return;
      }
      const created = await createFinanceRun(planId);
      setRunEnd(null);
      setParams({ run: created.run_id });
    } catch (err) {
      if (err instanceof ApiError && err.code === "RUN_ALREADY_ACTIVE" && typeof err.details.run_id === "string") {
        setParams({ run: err.details.run_id });
      } else if (err instanceof ApiError && err.code === "PREFLIGHT_FAILED") {
        setRerunError("Your plan has errors. Open Setup > Review to fix them.");
      } else setRerunError(errorMessage(err));
    } finally {
      setRerunning(false);
    }
  };

  const showRun = runId && !resultParam;

  return (
    <div className="col gap-lg">
      {showRun ? <FinRunProgress runId={runId} onDone={onRunDone} /> : null}
      {showRun && runEnd && runEnd.status !== "completed" ? (
        <Banner
          tone={runEnd.status === "cancelled" ? "info" : "danger"}
          role="alert"
          title={runEnd.status === "cancelled" ? "The run was cancelled." : "The run did not finish."}
          actions={<button className="btn sm" onClick={() => void rerun()}>Try again</button>}
        >
          {runEnd.error ?? "No result was stored."}
        </Banner>
      ) : null}
      {rerunError ? <Banner tone="danger" role="alert">{rerunError}</Banner> : null}
      <ErrorBanner error={error} />
      {!showRun && noResults && !record ? (
        <div className="empty">
          <Icon name="layers" size={32} />
          <h2>No results yet</h2>
          <p>Finish the setup and build your plan to see results here.</p>
          <Link className="btn primary" to={`/finance/${planId}/setup/review`}>Go to review</Link>
        </div>
      ) : null}
      {loading && !record ? <Loading label="Loading result…" /> : null}
      {record && !showRun ? (
        <ResultView
          planId={planId}
          record={record}
          planVersion={ctx.record.version}
          locale={ctx.draft.profile.locale}
          onRerun={() => void rerun()}
          rerunning={rerunning}
          onSend={() => setSendOpen(true)}
          historyKey={historyKey}
        />
      ) : null}
      {sendOpen && record ? <SendToPlannerDialog resultId={record.id} planName={ctx.draft.name} onClose={() => setSendOpen(false)} /> : null}
    </div>
  );
}

function ResultView({
  planId,
  record,
  planVersion,
  locale,
  onRerun,
  rerunning,
  onSend,
  historyKey,
}: {
  planId: string;
  record: FinanceResultRecord;
  planVersion: number;
  locale: string;
  onRerun(): void;
  rerunning: boolean;
  onSend(): void;
  historyKey: number;
}) {
  const r = record.result;
  const [basis, setBasis] = useMoneyBasis();
  return (
    <>
      <ResultHeader planId={planId} record={record} planVersion={planVersion} onRerun={onRerun} rerunning={rerunning} onSend={onSend} />
      <ResultKpis result={r} locale={locale} />
      <section aria-labelledby="fin-goals-title" className="col">
        <h2 id="fin-goals-title">Goals</h2>
        {r.goals.length ? (
          <div className="goal-cards">
            {r.goals.map((g) => (
              <GoalCard key={g.goal_id} goal={g} currency={r.currency} locale={locale} />
            ))}
          </div>
        ) : (
          <p className="muted">No goals in this plan. Add goals in Setup to see what to invest in.</p>
        )}
      </section>
      <CorpusCard result={r} locale={locale} />
      <section className="card" aria-labelledby="fin-contrib-title">
        <div className="card-header">
          <h2 id="fin-contrib-title">Monthly contributions</h2>
          <RealNominalToggle value={basis} onChange={setBasis} />
        </div>
        <div className="card-body col">
          <span className="small muted">
            {basis === "real"
              ? "Amounts in today's money. In practice, raise them with inflation each year."
              : `Expected future amounts, assuming ${r.assumptions_used.inflation_pct}% inflation a year.`}
          </span>
          <ContributionTable result={r} basis={basis} locale={locale} />
        </div>
      </section>
      <div className="grid-2">
        <GlideCard result={r} />
        <section className="card chart-card" aria-labelledby="fin-cf-title">
          <div className="card-header">
            <h2 id="fin-cf-title">Cash flow per year</h2>
            <span className="small muted">today's money</span>
          </div>
          <div className="card-body">
            <CashflowChart
              cashflow={r.cashflow}
              format={(v) => formatMoney(v, r.currency, locale)}
              formatAxis={(v) => formatMoney(v, r.currency, locale, { compact: true })}
              testId="cashflow-chart"
            />
          </div>
        </section>
      </div>
      <ExplanationPanel result={r} taxNote={record.plan.profile.tax_note} />
      {record.kind === "baseline" ? <FixList planId={planId} resultId={record.id} result={r} /> : null}
      <FinanceResultHistory planId={planId} currentId={record.id} currency={r.currency} locale={locale} refreshKey={historyKey} />
      <p className="small faint" style={{ margin: 0 }}>
        Engine {r.engine_version} · {r.simulation_settings.n_paths} simulated market paths · solver {r.diagnostics.solver}
        {r.optimality_proven ? "" : " (best found, not proven)"}
      </p>
    </>
  );
}

export function CorpusCard({ result: r, locale }: { result: FinanceResult; locale: string }) {
  const infos = useMemo(() => classInfos(r), [r]);
  const layers: AreaLayer[] = useMemo(() => {
    const order = r.assumptions_used.asset_classes.map((c) => c.id);
    const keys = Object.keys(r.series.corpus_by_class).sort((a, b) => order.indexOf(a) - order.indexOf(b));
    const out: AreaLayer[] = keys.map((k) => ({
      key: k,
      label: infos.get(k)?.name ?? k,
      color: infos.get(k)?.color ?? "var(--fin-c8)",
      values: r.series.corpus_by_class[k],
    }));
    out.push({ key: "emergency_fund", label: "Emergency fund", color: "var(--fin-c6)", values: r.series.emergency_fund });
    out.push({ key: "cash_buffer", label: "Cash buffer", color: "var(--fin-c7)", values: r.series.cash_buffer });
    out.push({ key: "unallocated", label: "Savings not assigned to a goal", color: "var(--fin-c8)", values: r.series.unallocated });
    return out.filter((l) => l.values.some((v) => v > 0.5));
  }, [r, infos]);
  const last = r.series.months.length - 1;
  const fmt = (v: number) => formatMoney(v, r.currency, locale, { compact: true });
  return (
    <section className="card chart-card" aria-labelledby="fin-corpus-title">
      <div className="card-header">
        <h2 id="fin-corpus-title">Your money over time</h2>
        <span className="small muted">today's money</span>
      </div>
      <div className="card-body">
        <span className="small muted">
          Coloured areas show the plan with expected returns; the shaded band shows where 8 in 10 simulated outcomes fall (p10 to p90). Money
          drops when a goal is paid.
        </span>
        <StackedAreaChart
          months={r.series.months}
          layers={layers}
          band={r.series.total_p50.length ? { p10: r.series.total_p10, p50: r.series.total_p50, p90: r.series.total_p90 } : null}
          format={fmt}
          formatAxis={fmt}
          testId="corpus-chart"
          ariaLabel={`Total savings and investments from ${r.start_month} to ${r.end_month}, stacked by asset class, emergency fund and cash, with the likely range.${
            last >= 0 ? ` At the end: ${fmt(r.series.total_p10[last] ?? 0)} to ${fmt(r.series.total_p90[last] ?? 0)}.` : ""
          }`}
          caption="Savings and investments by asset class, yearly, today's money"
        />
      </div>
    </section>
  );
}

function GlideCard({ result: r }: { result: FinanceResult }) {
  const ids = r.goals.map((g) => g.goal_id).filter((id) => (r.glide_paths[id]?.length ?? 0) > 0);
  const [stored, setStored] = useStoredState<string | null>("sp.fin.chartGoal", null);
  const goalId = stored && ids.includes(stored) ? stored : ids[0] ?? null;
  const pts = goalId ? r.glide_paths[goalId] ?? [] : [];
  const goal = r.goals.find((g) => g.goal_id === goalId);
  return (
    <section className="card chart-card" aria-labelledby="fin-glide-title">
      <div className="card-header">
        <h2 id="fin-glide-title">Growth assets as the goal gets closer</h2>
        {ids.length > 1 ? (
          <select className="select sm" style={{ width: "auto" }} value={goalId ?? ""} onChange={(e) => setStored(e.target.value)} aria-label="Goal shown in the chart" data-testid="glide-goal-select">
            {ids.map((id) => (
              <option key={id} value={id}>
                {r.goals.find((g) => g.goal_id === id)?.name ?? id}
              </option>
            ))}
          </select>
        ) : null}
      </div>
      <div className="card-body">
        {pts.length ? (
          <LineChart
            months={pts.map((p) => p.month)}
            series={[
              { key: "cap", label: "Allowed growth share", color: "var(--text-muted)", values: pts.map((p) => p.risky_cap_pct), dashed: true },
              { key: "share", label: "Planned growth share", color: "var(--fin-c1)", values: pts.map((p) => p.risky_share_pct) },
            ]}
            formatY={(v) => `${Math.round(v)}%`}
            testId="glide-chart"
            ariaLabel={`Share of growth assets for ${goal?.name ?? "the goal"} from ${pts[0].month} to ${pts[pts.length - 1].month}: planned share starts at ${Math.round(pts[0].risky_share_pct)}% and ends at ${Math.round(pts[pts.length - 1].risky_share_pct)}%.`}
            caption={`Glide path for ${goal?.name ?? "the goal"}`}
          />
        ) : (
          <div className="empty" data-testid="glide-chart">
            <p>No investment buckets to show yet.</p>
          </div>
        )}
        <p className="small muted" style={{ margin: "8px 0 0" }}>
          How much may be in <Term k="growth_assets">growth assets</Term> follows your <Term k="risk_level">risk level</Term> and the{" "}
          <Term k="glide_path">glide path</Term>.
        </p>
      </div>
    </section>
  );
}
