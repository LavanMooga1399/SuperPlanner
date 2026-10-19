import { useState } from "react";
import { useNavigate } from "react-router";
import { ApiError, errorMessage } from "../../api/client";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { createFinanceRun } from "../api/client";
import { useLoadedFinancePlan } from "../state/FinancePlanContext";

export const ENGINE_VERSIONS_DIFFER_TEXT =
  "These results come from different versions of the planner, so part of the difference is due to the update. Re-run your plan for a like-for-like comparison.";

/** PHASE2 1.13 / 3.4: shown on the what-if and compare screens when the two results come from different engine versions. */
export function EngineVersionBanner({ show }: { show: boolean | undefined }) {
  const ctx = useLoadedFinancePlan();
  const planId = ctx.record.id;
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!show) return null;

  const rerun = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (!(await ctx.save())) {
        setErr("Your latest changes could not be saved, so the plan was not re-run.");
        return;
      }
      const created = await createFinanceRun(planId);
      navigate(`/finance/${planId}/results?run=${created.run_id}`);
    } catch (e) {
      if (e instanceof ApiError && e.code === "RUN_ALREADY_ACTIVE" && typeof e.details.run_id === "string") {
        navigate(`/finance/${planId}/results?run=${e.details.run_id}`);
      } else if (e instanceof ApiError && e.code === "PREFLIGHT_FAILED") {
        setErr("Your plan has errors. Open Setup > Review to fix them.");
      } else setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Banner
      tone="warn"
      role="status"
      testId="fin-engine-versions-differ"
      title="Results from different planner versions"
      actions={
        <button type="button" className="btn sm" onClick={() => void rerun()} disabled={busy} data-testid="fin-engine-rerun">
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />} Re-run plan
        </button>
      }
    >
      {ENGINE_VERSIONS_DIFFER_TEXT}
      {err ? <div role="alert" style={{ color: "var(--danger)" }}>{err}</div> : null}
    </Banner>
  );
}
