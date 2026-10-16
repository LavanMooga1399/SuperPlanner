import { useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { errorMessage } from "../../api/client";
import { ErrorBanner, Loading } from "../../components/Banner";
import { listFinanceResults } from "../api/client";

/** `/finance/:planId`: to results if a result exists, else to the first setup step. */
export function FinancePlanIndex() {
  const { planId = "" } = useParams();
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    listFinanceResults(planId, undefined, ac.signal)
      .then((r) => setTarget(r.items.length ? "results" : "setup/profile"))
      .catch((err) => !ac.signal.aborted && setError(errorMessage(err)));
    return () => ac.abort();
  }, [planId]);
  if (error) return <ErrorBanner error={error} />;
  if (!target) return <Loading />;
  return <Navigate to={`/finance/${planId}/${target}`} replace />;
}
