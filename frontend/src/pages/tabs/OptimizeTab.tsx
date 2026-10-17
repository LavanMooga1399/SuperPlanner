import { useCallback, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiError, createRun, errorMessage, listRuns } from "../../api/client";
import { ACTIVE_RUN_STATUSES, type Issue, type Objectives, type SolverRunRequest } from "../../api/types";
import { Banner, ErrorBanner } from "../../components/Banner";
import { DEFAULT_EXPERT, ExpertSettings, type ExpertValues } from "../../components/ExpertSettings";
import { GoalPresetPicker } from "../../components/GoalPresetPicker";
import { Icon } from "../../components/Icon";
import { IssueList } from "../../components/IssueList";
import { RunHistory } from "../../components/RunHistory";
import { RunProgress } from "../../components/RunProgress";
import { useTerms } from "../../lib/terms";
import { useAsync, useStoredState } from "../../lib/useAsync";
import { useLoadedPlan } from "../../state/PlanContext";

const BUDGETS = [
  { s: 5, label: "Quick", desc: "5 seconds" },
  { s: 10, label: "Standard", desc: "10 seconds" },
  { s: 30, label: "Thorough", desc: "30 seconds" },
  { s: 120, label: "Extended", desc: "2 minutes" },
];

export function OptimizeTab() {
  const plan = useLoadedPlan();
  const { draft } = plan;
  const terms = useTerms();
  const [params, setParams] = useSearchParams();
  const runId = params.get("run");
  const [expertOpen, setExpertOpen] = useStoredState("sp.expert", false);
  const [expert, setExpert] = useStoredState<ExpertValues>("sp.expert.values", DEFAULT_EXPERT);
  const [budget, setBudget] = useStoredState("sp.budget", 10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<Issue[] | null>(null);
  const runs = useAsync((s) => listRuns(plan.planId, s), [plan.planId, runId]);

  const objectives = draft.objectives;
  const setObjectives = (o: Objectives) => plan.update((p) => ({ ...p, objectives: o }));
  const customInvalid = objectives.preset === "custom" && objectives.weights.makespan <= 0 && objectives.weights.tardiness <= 0 && objectives.weights.cost <= 0;

  const activeRun = runs.data?.items.find((r) => ACTIVE_RUN_STATUSES.includes(r.status)) ?? null;

  const start = async () => {
    setBusy(true);
    setError(null);
    setPreflight(null);
    try {
      const saved = await plan.save();
      if (!saved) {
        setError("Your latest edits could not be saved. Resolve the save problem before optimizing.");
        return;
      }
      const body: SolverRunRequest = { time_limit_seconds: budget, objectives: null };
      if (expertOpen) {
        body.strategy = expert.strategy;
        body.seed = expert.seed;
        body.max_alternatives = expert.max_alternatives;
        body.ga = expert.ga;
        body.cpsat = expert.cpsat;
      }
      const created = await createRun(plan.planId, body);
      setParams({ run: created.run_id });
    } catch (err) {
      if (err instanceof ApiError && err.code === "PREFLIGHT_FAILED") {
        setPreflight((err.details.issues as Issue[] | undefined) ?? []);
        setError(err.message);
      } else if (err instanceof ApiError && err.code === "RUN_ALREADY_ACTIVE") {
        try {
          const { items } = await listRuns(plan.planId);
          const act = items.find((r) => ACTIVE_RUN_STATUSES.includes(r.status));
          if (act) setParams({ run: act.id });
          else setError(err.message);
        } catch {
          setError(err.message);
        }
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const onFinished = useCallback(() => {
    runs.reload();
    void plan.refreshRecord();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="col gap-lg">
      {runId ? (
        <>
          <div className="row">
            <Link className="btn sm ghost" to="." onClick={() => setParams({})}>
              <Icon name="chevron-right" style={{ transform: "rotate(180deg)" }} /> New run
            </Link>
          </div>
          <RunProgress key={runId} runId={runId} terms={terms} currency={draft.currency} onFinished={onFinished} onStatusChange={runs.reload} />
        </>
      ) : (
        <div className="card">
          <div className="card-header">
            <h2>What matters most?</h2>
            <label className="switch small">
              <input type="checkbox" checked={expertOpen} onChange={(e) => setExpertOpen(e.target.checked)} data-testid="expert-toggle" />
              <span>Expert settings</span>
            </label>
          </div>
          <div className="card-body col gap-lg">
            <GoalPresetPicker value={objectives} onChange={setObjectives} terms={terms} expert={expertOpen} />
            <div className="col">
              <h3>How long may it search?</h3>
              <div className="btn-group" role="radiogroup" aria-label="Time budget">
                {BUDGETS.map((b) => (
                  <button key={b.s} type="button" className="btn" role="radio" aria-checked={budget === b.s} aria-pressed={budget === b.s} onClick={() => setBudget(b.s)} title={b.desc}>
                    {b.label} <span className="faint small">{b.desc}</span>
                  </button>
                ))}
              </div>
              {expertOpen ? (
                <div className="row small">
                  <label htmlFor="budget-custom">Custom seconds</label>
                  <input id="budget-custom" className="input sm num" type="number" min={1} max={300} value={budget} onChange={(e) => setBudget(Math.max(1, Math.min(300, Number(e.target.value) || 1)))} />
                </div>
              ) : null}
              <span className="small muted">Longer searches can find better {terms.scheduleL}s on big plans. A first valid result usually appears within a second.</span>
            </div>
            {expertOpen ? <ExpertSettings value={expert} onChange={setExpert} /> : null}
          </div>
          <div className="card-footer row between wrap">
            <span className="small muted">
              {terms.countTasks(draft.tasks.length)}, {terms.countResources(draft.resources.length)}
            </span>
            <div className="row">
              {activeRun ? (
                <Link className="btn" to={`?run=${encodeURIComponent(activeRun.id)}`}>
                  <Icon name="loader" /> A run is in progress
                </Link>
              ) : null}
              <button className="btn primary" onClick={start} disabled={busy || customInvalid || draft.tasks.length === 0} data-testid="start-run">
                {busy ? <span className="spinner" aria-hidden /> : <Icon name="play" />}
                Optimize
              </button>
            </div>
            {draft.tasks.length === 0 ? (
              <p className="small muted" style={{ margin: "8px 0 0" }} data-testid="optimize-needs-tasks">
                Add at least one {terms.taskL} on the <Link to="../tasks">{terms.tasks} tab</Link> to optimize.
              </p>
            ) : null}
          </div>
        </div>
      )}
      <ErrorBanner error={error} />
      {preflight && preflight.length ? (
        <div className="col">
          <Banner tone="danger" title="Fix these problems before optimizing." actions={<Link className="btn sm" to="../validate">Open Validate</Link>} />
          <IssueList issues={preflight} draft={draft} terms={terms} />
        </div>
      ) : null}
      <RunHistory runs={runs.data?.items ?? []} currentRunId={runId} terms={terms} currency={draft.currency} onRefresh={runs.reload} />
    </div>
  );
}
