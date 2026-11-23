import { useState } from "react";
import { useNavigate } from "react-router";
import { ApiError, errorMessage } from "../../api/client";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { createWhatIfRun } from "../api/client";
import type { FinanceResult, Fix } from "../api/types";
import { formatProb } from "../lib/money";
import { t } from "../../lib/i18n";

const KIND_LABEL: Record<Fix["kind"], string> = {
  DELAY_GOAL: t("finance.fixList.str.moveTheDate"),
  INCREASE_SAVINGS: t("finance.fixList.str.saveMore"),
  SPEND_LESS: t("finance.fixList.str.spendLess"),
  INCREASE_RISK: t("finance.fixList.str.takeMoreGrowthRisk"),
  REDUCE_TARGET: t("finance.fixList.str.lowerTheTarget"),
  LOWER_EF_BUILD_SHARE: t("finance.fixList.str.buildTheEmergencyFundSlower"),
};

/** "Try this" fixes: POST the fix's exact what-if payload and open the what-if page with that run. */
export function FixList({ planId, resultId, result }: { planId: string; resultId: string; result: FinanceResult }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const goals = result.goals.filter((g) => (result.explanation.goals[g.goal_id]?.fixes.length ?? 0) > 0);
  if (!goals.length) return null;

  const tryFix = async (fix: Fix, key: string) => {
    setBusy(key);
    setError(null);
    try {
      const created = await createWhatIfRun(planId, { changes: fix.what_if, replace_active: true, base_result_id: resultId });
      navigate(`/finance/${planId}/what-if?base=${resultId}&run=${created.run_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "RUN_ALREADY_ACTIVE") setError(t("finance.fixList.str.waitForTheCurrentPlan"));
      else setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="card" aria-labelledby="fin-fixes-title" data-testid="fin-fixes">
      <div className="card-header">
        <h2 id="fin-fixes-title">{t("finance.fixList.head.waysToCloseTheGap")}</h2>
        <span className="small muted">{t("finance.fixList.text.eachOptionWasTestedBy")}</span>
      </div>
      <div className="card-body col gap-lg">
        {error ? <Banner tone="danger" role="alert">{error}</Banner> : null}
        {goals.map((g) => (
          <div key={g.goal_id} className="col">
            <h3>{g.name}</h3>
            {result.explanation.goals[g.goal_id].fixes.map((f, i) => {
              const key = `${g.goal_id}-${f.kind}-${i}`;
              return (
                <div key={key} className={`fix-item${f.smallest ? " smallest" : ""}`} data-testid={`fix-${g.goal_id}-${f.kind}`}>
                  <div className="grow col" style={{ gap: 4 }}>
                    <div className="row wrap">
                      <strong>{KIND_LABEL[f.kind]}</strong>
                      {f.smallest ? (
                        <span className="badge accent">
                          <Icon name="star" /> {t("finance.fixList.btn.smallestChange")}
                        </span>
                      ) : null}
                    </div>
                    <span>{f.message}</span>
                    {f.resulting_success_probability !== null ? (
                      <span className="small muted">{t("finance.fixList.text.estimatedChanceAfterwards", { resultingsuccessprobability: formatProb(f.resulting_success_probability) })}</span>
                    ) : null}
                  </div>
                  <button className="btn sm" onClick={() => void tryFix(f, key)} disabled={busy !== null}>
                    {busy === key ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />}{" "}{t("finance.fixList.text.tryThis")}
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </section>
  );
}
