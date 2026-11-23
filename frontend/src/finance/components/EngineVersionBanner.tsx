import { useState } from "react";
import { useNavigate } from "react-router";
import { ApiError, errorMessage } from "../../api/client";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { createFinanceRun } from "../api/client";
import { useLoadedFinancePlan } from "../state/FinancePlanContext";
import { t } from "../../lib/i18n";

export const ENGINE_VERSIONS_DIFFER_TEXT =
  t("finance.engineVersionBanner.str.theseResultsComeFromDifferent");

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
        setErr(t("finance.engineVersionBanner.str.yourLatestChangesCouldNot"));
        return;
      }
      const created = await createFinanceRun(planId);
      navigate(`/finance/${planId}/results?run=${created.run_id}`);
    } catch (e) {
      if (e instanceof ApiError && e.code === "RUN_ALREADY_ACTIVE" && typeof e.details.run_id === "string") {
        navigate(`/finance/${planId}/results?run=${e.details.run_id}`);
      } else if (e instanceof ApiError && e.code === "PREFLIGHT_FAILED") {
        setErr(t("finance.engineVersionBanner.str.yourPlanHasErrorsOpen"));
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
      title={t("finance.engineVersionBanner.title.resultsFromDifferentPlannerVersions")}
      actions={
        <button type="button" className="btn sm" onClick={() => void rerun()} disabled={busy} data-testid="fin-engine-rerun">
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="refresh" />}{" "}{t("finance.engineVersionBanner.text.reRunPlan")}
        </button>
      }
    >
      {ENGINE_VERSIONS_DIFFER_TEXT}
      {err ? <div role="alert" style={{ color: "var(--danger)" }}>{err}</div> : null}
    </Banner>
  );
}
