import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, errorMessage } from "../../api/client";
import { Banner } from "../../components/Banner";
import { Icon } from "../../components/Icon";
import { createWhatIfRun } from "../api/client";
import type { FinanceResult, Fix } from "../api/types";
import { formatProb } from "../lib/money";

const KIND_LABEL: Record<Fix["kind"], string> = {
  DELAY_GOAL: "Move the date",
  INCREASE_SAVINGS: "Save more",
  SPEND_LESS: "Spend less",
  INCREASE_RISK: "Take more growth risk",
  REDUCE_TARGET: "Lower the target",
  LOWER_EF_BUILD_SHARE: "Build the emergency fund slower",
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
      if (err instanceof ApiError && err.code === "RUN_ALREADY_ACTIVE") setError("Wait for the current plan run to finish, then try again.");
      else setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="card" aria-labelledby="fin-fixes-title" data-testid="fin-fixes">
      <div className="card-header">
        <h2 id="fin-fixes-title">Ways to close the gap</h2>
        <span className="small muted">Each option was tested by re-planning; try one to see the full effect.</span>
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
                          <Icon name="star" /> Smallest change
                        </span>
                      ) : null}
                    </div>
                    <span>{f.message}</span>
                    {f.resulting_success_probability !== null ? (
                      <span className="small muted">Estimated chance afterwards: {formatProb(f.resulting_success_probability)}</span>
                    ) : null}
                  </div>
                  <button className="btn sm" onClick={() => void tryFix(f, key)} disabled={busy !== null}>
                    {busy === key ? <span className="spinner" aria-hidden /> : <Icon name="arrow-right" />} Try this
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
