import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, errorMessage, isAbort } from "../../api/client";
import { Banner, ErrorBanner, Loading } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import {
  compareFinanceResults,
  createFinanceRun,
  createWhatIfRun,
  getFinanceResult,
  getFinanceRun,
  listFinanceResults,
} from "../api/client";
import type { FinanceComparison, FinancePlan, FinanceResultRecord, FinanceRun, WhatIfChanges } from "../api/types";
import { FinRunProgress } from "../components/FinRunProgress";
import { GoalCard } from "../components/GoalCard";
import { ScenarioCompareTable } from "../components/ScenarioCompareTable";
import { isEmptyChanges, WhatIfControls } from "../components/WhatIfControls";
import { nextId, WHATIF_PREFIX } from "../lib/ids";
import { useLoadedFinancePlan } from "../state/FinancePlanContext";
import { FinSaveIndicator } from "./FinancePlanShell";

const DEBOUNCE_MS = 800;

/**
 * "Apply to my plan" (FINANCE.md 20.5): turn what-if changes into ordinary edits of the draft.
 * Never writes `whatif_*` ids (rejected by the API) [R12]. An income drop is not applied.
 */
export function applyChangesToDraft(plan: FinancePlan, c: WhatIfChanges): FinancePlan {
  let p: FinancePlan = { ...plan };
  const extra = c.extra_monthly_savings ?? 0;
  if (extra > 0) {
    p = {
      ...p,
      incomes: [
        ...p.incomes,
        {
          id: nextId(p, "inc"),
          name: "Extra savings",
          kind: "other",
          amount: Math.round(extra * 100) / 100,
          frequency: "monthly",
          growth_pct: p.assumptions.inflation_pct,
          start_month: null,
          end_month: null,
          interruptible: false,
        },
      ],
    };
  } else if (extra < 0) {
    p = {
      ...p,
      expenses: [
        ...p.expenses,
        {
          id: nextId(p, "exp"),
          name: "Reduced savings",
          category: "other",
          amount: Math.round(-extra * 100) / 100,
          frequency: "monthly",
          essential: false,
          inflation_linked: true,
          inflation_pct: null,
          start_month: null,
          end_month: null,
        },
      ],
    };
  }
  for (const o of c.goal_overrides ?? []) {
    p = {
      ...p,
      goals: p.goals.map((g) =>
        g.id !== o.goal_id
          ? g
          : {
              ...g,
              ...(o.target_month ? { target_month: o.target_month } : {}),
              ...(o.target_amount ? { target_amount: o.target_amount } : {}),
              ...(o.priority ? { priority: o.priority } : {}),
              ...(o.enabled !== null && o.enabled !== undefined ? { enabled: o.enabled } : {}),
              ...(o.risk_tolerance ? { risk_tolerance: o.risk_tolerance } : {}),
            },
      ),
    };
  }
  if (c.risk_tolerance) p = { ...p, profile: { ...p.profile, risk_tolerance: c.risk_tolerance } };
  const shift = c.return_shift_pct ?? 0;
  if (shift) {
    p = {
      ...p,
      assumptions: {
        ...p.assumptions,
        asset_classes: p.assumptions.asset_classes.map((a) =>
          a.category === "cash" ? a : { ...a, expected_return_pct: Math.max(-20, Math.min(40, Math.round((a.expected_return_pct + shift) * 100) / 100)) },
        ),
      },
    };
  }
  if (c.inflation_pct !== null && c.inflation_pct !== undefined) p = { ...p, assumptions: { ...p.assumptions, inflation_pct: c.inflation_pct } };
  if (c.emergency_build_share) p = { ...p, emergency_fund: { ...p.emergency_fund, build_share: c.emergency_build_share } };
  // Defensive: a stored document may never contain what-if ids.
  const clean = <T extends { id: string }>(l: T[]) => l.filter((x) => !x.id.startsWith(WHATIF_PREFIX));
  return { ...p, incomes: clean(p.incomes), expenses: clean(p.expenses), one_offs: clean(p.one_offs) };
}

interface WhatIfView {
  runId: string;
  record: FinanceResultRecord;
  cmp: FinanceComparison;
}

/** Mean of the first 12 monthly surpluses (FINANCE.md 20.5 slider range). */
export function firstYearAvgSurplus(surplus: number[] | undefined): number {
  const first = (surplus ?? []).slice(0, 12).filter((v) => Number.isFinite(v));
  return first.length ? first.reduce((a, b) => a + b, 0) / first.length : 0;
}

export function WhatIfPage() {
  const ctx = useLoadedFinancePlan();
  const planId = ctx.record.id;
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const baseParam = params.get("base");
  const initialRun = useRef(params.get("run"));

  const [base, setBase] = useState<FinanceResultRecord | null>(null);
  const [baseMissing, setBaseMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changes, setChanges] = useState<WhatIfChanges>({});
  const [userEdited, setUserEdited] = useState(0);
  const [activeRun, setActiveRun] = useState<string | null>(initialRun.current);
  const latestRun = useRef<string | null>(initialRun.current);
  const reqSeq = useRef(0);
  const [view, setView] = useState<WhatIfView | null>(null);
  const [runNote, setRunNote] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  // Baseline = ?base= or the latest baseline result.
  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      let id = baseParam;
      if (!id) {
        const list = await listFinanceResults(planId, "baseline", ac.signal);
        id = list.items[0]?.id ?? null;
      }
      if (!id) {
        setBaseMissing(true);
        return;
      }
      setBase(await getFinanceResult(id, ac.signal));
    })().catch((err) => !isAbort(err) && setError(errorMessage(err)));
    return () => ac.abort();
  }, [planId, baseParam]);

  // A run opened from "Try this": show its changes in the controls.
  useEffect(() => {
    const rid = initialRun.current;
    if (!rid) return;
    getFinanceRun(rid)
      .then((run) => run.what_if && latestRun.current === rid && setChanges(run.what_if))
      .catch(() => undefined);
  }, []);

  // Debounced POST on user changes; only the latest request's run is followed [R23].
  useEffect(() => {
    if (!userEdited || !base) return;
    const t = setTimeout(async () => {
      const my = ++reqSeq.current;
      setRunNote(null);
      if (isEmptyChanges(changes)) {
        latestRun.current = null;
        setActiveRun(null);
        setView(null);
        return;
      }
      try {
        const created = await createWhatIfRun(planId, { changes, replace_active: true, base_result_id: base.id });
        if (my !== reqSeq.current) return;
        latestRun.current = created.run_id;
        setActiveRun(created.run_id);
        setParams((p) => {
          const n = new URLSearchParams(p);
          n.set("base", base.id);
          n.set("run", created.run_id);
          return n;
        }, { replace: true });
      } catch (err) {
        if (my !== reqSeq.current) return;
        if (err instanceof ApiError && err.code === "RUN_ALREADY_ACTIVE") setRunNote("Wait for the current plan run to finish, then move a control again.");
        else setRunNote(errorMessage(err));
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changes, userEdited, base?.id, planId]);

  const onRunDone = useCallback(
    async (run: FinanceRun | null) => {
      if (!run || run.id !== latestRun.current) return; // replaced run: ignore
      if (run.status !== "completed" || !run.result_id || !base) {
        if (run.status === "failed") setRunNote(run.error ?? "The what-if run failed.");
        return;
      }
      try {
        const [record, cmp] = await Promise.all([getFinanceResult(run.result_id), compareFinanceResults(base.id, run.result_id)]);
        if (run.id !== latestRun.current) return;
        setView({ runId: run.id, record, cmp });
      } catch (err) {
        if (run.id === latestRun.current) setRunNote(errorMessage(err));
      }
    },
    [base],
  );

  const onChange = (c: WhatIfChanges) => {
    setChanges(c);
    setUserEdited((n) => n + 1);
  };

  const apply = async () => {
    setApplying(true);
    setRunNote(null);
    try {
      ctx.update((p) => applyChangesToDraft(p, changes));
      const ok = await ctx.save();
      if (!ok) {
        setRunNote("Your plan could not be saved.");
        return;
      }
      const created = await createFinanceRun(planId);
      navigate(`/finance/${planId}/results?run=${created.run_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "RUN_ALREADY_ACTIVE" && typeof err.details.run_id === "string") {
        navigate(`/finance/${planId}/results?run=${err.details.run_id}`);
      } else setRunNote(errorMessage(err));
    } finally {
      setApplying(false);
    }
  };

  if (error) return <ErrorBanner error={error} />;
  if (baseMissing) {
    return (
      <div className="empty">
        <Icon name="refresh" size={32} />
        <h2>Build your plan first</h2>
        <p>What-if scenarios start from a built plan.</p>
        <Link className="btn primary" to={`/finance/${planId}/setup/review`}>Go to review</Link>
      </div>
    );
  }
  if (!base) return <Loading label="Loading your plan result…" />;

  const cur = base.result.currency;
  const loc = ctx.draft.profile.locale;
  const showing = view && view.runId === activeRun ? view : null;

  return (
    <div className="col gap-lg">
      <div className="fin-header">
        <div className="col" style={{ gap: 4 }}>
          <h1>What if…?</h1>
          <span className="muted">
            Move a control to test a change. Your plan is not changed until you choose "Apply to my plan". Compared with the result from{" "}
            <Link to={`/finance/${planId}/results?result=${base.id}`}>version {base.base_plan_version}</Link>.
          </span>
        </div>
        <div className="fin-actions">
          <FinSaveIndicator state={ctx.saveState} dirty={ctx.dirty} error={ctx.saveError} />
          {showing ? (
            <Link className="btn" to={`/finance/${planId}/compare?a=${base.id}&b=${showing.record.id}`}>
              <Icon name="compare" /> Open in compare
            </Link>
          ) : null}
          <button className="btn primary" onClick={() => void apply()} disabled={applying || isEmptyChanges(changes)} data-testid="whatif-apply">
            {applying ? <span className="spinner" aria-hidden /> : <Icon name="check" />} Apply to my plan
          </button>
        </div>
      </div>
      {changes.income_drop ? (
        <span className="small muted">
          <Icon name="info" /> An income drop is a test only; it is not added to your plan when you apply.
        </span>
      ) : null}
      <div className="whatif-grid">
        <section className="card" aria-labelledby="wi-controls-h">
          <div className="card-header">
            <h2 id="wi-controls-h">Change</h2>
            <button
              type="button"
              className="btn sm ghost"
              onClick={() => onChange({})}
              disabled={isEmptyChanges(changes)}
            >
              <Icon name="refresh" /> Reset
            </button>
          </div>
          <div className="card-body">
            <WhatIfControls plan={base.plan} changes={changes} onChange={onChange} avgSurplus={firstYearAvgSurplus(base.result.cashflow.surplus)} />
          </div>
        </section>
        <div className="col gap-lg" aria-live="polite">
          {runNote ? <Banner tone="warn" role="alert">{runNote}</Banner> : null}
          {activeRun && !showing ? <FinRunProgress key={activeRun} runId={activeRun} onDone={(r) => void onRunDone(r)} compact /> : null}
          {!activeRun ? (
            <div className="empty card">
              <Icon name="refresh" size={28} />
              <p>Move a control on the left. A new estimate appears about a second after you stop.</p>
            </div>
          ) : null}
          {showing ? (
            <section className="col gap-lg" data-testid="whatif-result" aria-labelledby="wi-result-h">
              <h2 id="wi-result-h">{showing.record.label ? `Effect of: ${showing.record.label}` : "Effect of your changes"}</h2>
              <ScenarioCompareTable cmp={showing.cmp} currency={cur} locale={loc} labelA="Your plan" labelB="What-if" testId="whatif-compare-table" />
              <div className="goal-cards">
                {showing.record.result.goals.map((g) => (
                  <GoalCard key={g.goal_id} goal={g} currency={cur} locale={loc} />
                ))}
              </div>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
