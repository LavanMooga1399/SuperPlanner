import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ApiError, errorMessage } from "../../api/client";
import { NotFound } from "../../App";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { useStoredState } from "../../lib/useAsync";
import { createFinanceRun, validateFinancePlan } from "../api/client";
import type { FinanceIssue, FinancePlan, FinanceValidateResponse } from "../api/types";
import { usePreview } from "../lib/hooks";
import { useLoadedFinancePlan } from "../state/FinancePlanContext";
import { AssumptionsStep } from "../wizard/AssumptionsStep";
import type { StepProps } from "../wizard/common";
import { DebtsStep } from "../wizard/DebtsStep";
import { GoalsStep } from "../wizard/GoalsStep";
import { IncomeExpenseStep } from "../wizard/IncomeExpenseStep";
import { ProfileStep } from "../wizard/ProfileStep";
import { ReviewStep } from "../wizard/ReviewStep";
import { SavingsStep } from "../wizard/SavingsStep";
import { Stepper } from "../wizard/Stepper";
import { isStep, STEPS, stepOfIssue, type StepKey } from "../wizard/steps";
import { FinSaveIndicator } from "./FinancePlanShell";

function markCompleted(p: FinancePlan, step: StepKey): FinancePlan {
  const done = p.metadata?.wizard?.completed_steps ?? [];
  if (done.includes(step)) return p;
  return { ...p, metadata: { ...p.metadata, wizard: { ...(p.metadata?.wizard ?? {}), completed_steps: [...done, step] } } };
}

export function WizardPage() {
  const { step } = useParams();
  if (!isStep(step)) return <NotFound />;
  return <Wizard step={step} />;
}

function Wizard({ step }: { step: StepKey }) {
  const navigate = useNavigate();
  const ctx = useLoadedFinancePlan();
  const { draft, record, update, save, saveState, dirty, saveError } = ctx;
  const preview = usePreview(draft);
  const [expert, setExpert] = useStoredState<boolean>("sp.fin.expert", false);
  const [navBusy, setNavBusy] = useState(false);
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [runIssues, setRunIssues] = useState<FinanceIssue[] | null>(null);
  const [validation, setValidation] = useState<FinanceValidateResponse | null>(null);
  const [validating, setValidating] = useState(false);
  const [validateError, setValidateError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const idx = STEPS.findIndex((s) => s.key === step);
  const prev = idx > 0 ? STEPS[idx - 1] : null;
  const next = idx < STEPS.length - 1 ? STEPS[idx + 1] : null;
  const planId = record.id;

  // Move focus to the step heading on step change (keyboard and screen-reader users).
  useEffect(() => {
    headingRef.current?.focus();
    setRunIssues(null);
    setBuildError(null);
  }, [step]);

  // Review: save first, then validate the stored version (FINANCE.md 20.3).
  useEffect(() => {
    if (step !== "review") return;
    if (dirty) {
      void save();
      return;
    }
    if (validation && validation.plan_version === record.version) return;
    const ac = new AbortController();
    setValidating(true);
    setValidateError(null);
    validateFinancePlan(planId, ac.signal)
      .then((v) => !ac.signal.aborted && setValidation(v))
      .catch((err) => !ac.signal.aborted && setValidateError(errorMessage(err)))
      .finally(() => !ac.signal.aborted && setValidating(false));
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, dirty, record.version, planId]);

  const done = useMemo(() => new Set(draft.metadata?.wizard?.completed_steps ?? []), [draft.metadata]);
  const issueSteps = useMemo(() => {
    const s = new Set<StepKey>();
    for (const i of preview.data?.issues ?? []) {
      if (i.severity !== "error") continue;
      const k = stepOfIssue(i);
      if (done.has(k)) s.add(k);
    }
    return s;
  }, [preview.data, done]);

  const goNext = async () => {
    if (!next) return;
    setNavBusy(true);
    update((p) => markCompleted(p, step));
    // Single-flight: waits for any in-flight autosave, then saves with the latest version [R23].
    await save();
    setNavBusy(false);
    navigate(`/finance/${planId}/setup/${next.key}`);
  };
  const goBack = () => prev && navigate(`/finance/${planId}/setup/${prev.key}`);
  const skip = () => next && navigate(`/finance/${planId}/setup/${next.key}`);

  const currentValidation = validation && validation.plan_version === record.version && !dirty ? validation : null;
  const reviewErrors = (runIssues ?? currentValidation?.issues ?? []).filter((i) => i.severity === "error").length;
  const canBuild = step === "review" && !!currentValidation && !validating && reviewErrors === 0 && !building && saveState !== "conflict";

  const build = async () => {
    setBuilding(true);
    setBuildError(null);
    setRunIssues(null);
    try {
      update((p) => markCompleted(p, "review"));
      const ok = await save();
      if (!ok) {
        setBuildError("Your latest changes could not be saved, so the plan was not built.");
        return;
      }
      const created = await createFinanceRun(planId);
      navigate(`/finance/${planId}/results?run=${created.run_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "RUN_ALREADY_ACTIVE" && typeof err.details.run_id === "string") {
        navigate(`/finance/${planId}/results?run=${err.details.run_id}`);
        return;
      }
      if (err instanceof ApiError && err.code === "PREFLIGHT_FAILED" && Array.isArray(err.details.issues)) {
        setRunIssues(err.details.issues as FinanceIssue[]);
        setBuildError("Please fix the errors below first.");
      } else {
        setBuildError(errorMessage(err));
      }
    } finally {
      setBuilding(false);
    }
  };

  const props: StepProps = { plan: draft, update, preview, expert };
  const label = STEPS[idx].label;

  return (
    <div className="fin-wizard">
      <Stepper planId={planId} current={step} done={done} issues={issueSteps} />
      <section className="col gap-lg" aria-labelledby="fin-step-title" data-testid={`wizard-panel-${step}`}>
        <div className="row wrap between">
          <div className="col" style={{ gap: 2 }}>
            <span className="small muted">
              Step {idx + 1} of {STEPS.length}
            </span>
            <h1 id="fin-step-title" ref={headingRef} tabIndex={-1} style={{ outline: "none" }}>
              {label}
            </h1>
          </div>
          <div className="row wrap">
            <FinSaveIndicator state={saveState} dirty={dirty} error={saveError} />
            <label className="switch">
              <input type="checkbox" checked={expert} onChange={(e) => setExpert(e.target.checked)} data-testid="fin-expert-toggle" />
              <span>Show expert settings</span>
            </label>
          </div>
        </div>

        {step === "profile" ? <ProfileStep {...props} /> : null}
        {step === "income" ? <IncomeExpenseStep {...props} /> : null}
        {step === "debts" ? <DebtsStep {...props} /> : null}
        {step === "savings" ? <SavingsStep {...props} /> : null}
        {step === "goals" ? <GoalsStep {...props} /> : null}
        {step === "assumptions" ? <AssumptionsStep {...props} /> : null}
        {step === "review" ? (
          <ReviewStep
            {...props}
            planId={planId}
            validation={currentValidation}
            validating={validating || dirty || saveState === "saving"}
            validateError={validateError}
            runIssues={runIssues}
          />
        ) : null}

        {buildError ? <Banner tone="danger" role="alert">{buildError}</Banner> : null}

        <div className="wizard-nav">
          <div className="row">
            {prev ? (
              <button type="button" className="btn" onClick={goBack} data-testid="wizard-back">
                <Icon name="chevron-right" style={{ transform: "rotate(180deg)" }} /> Back
              </button>
            ) : null}
          </div>
          <div className="row wrap">
            {next ? (
              <>
                <button type="button" className="btn ghost" onClick={skip} data-testid="wizard-skip">
                  Skip - use defaults
                </button>
                <button type="button" className="btn primary" onClick={() => void goNext()} disabled={navBusy} data-testid="wizard-next">
                  {navBusy ? <span className="spinner" aria-hidden /> : null} Next: {next.label} <Icon name="chevron-right" />
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn primary"
                onClick={() => void build()}
                disabled={!canBuild}
                data-testid="build-plan"
                aria-describedby={reviewErrors ? "fin-build-hint" : undefined}
              >
                {building ? <span className="spinner" aria-hidden /> : <Icon name="play" />} Build my plan
              </button>
            )}
          </div>
        </div>
        {step === "review" && reviewErrors ? (
          <span id="fin-build-hint" className="small" style={{ color: "var(--danger)", textAlign: "right" }}>
            <Icon name="alert" /> Fix the {reviewErrors} error{reviewErrors === 1 ? "" : "s"} above to build your plan.
          </span>
        ) : null}
      </section>
    </div>
  );
}
