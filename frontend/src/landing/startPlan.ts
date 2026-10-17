import { useState } from "react";
import { useNavigate } from "react-router";
import { createProblem, errorMessage } from "../api/client";
import type { Problem } from "../api/types";
import { startBlankFinancePlan } from "../finance/lib/startBlank";
import { browserUtcOffset, todayDate } from "../lib/time";
import { DOMAIN_OF_KIND, KINDS, type PlanKind, type ScheduleKind } from "./kinds";

/** An empty plan in the kind's own words, with one working resource (PHASE2.md 3.1 "Build step by step"). */
export function emptyProblem(kind: ScheduleKind): Problem {
  const info = KINDS[kind];
  const r = info.starterResource!;
  return {
    id: "draft",
    name: `My ${info.planNoun} plan`,
    description: "",
    domain: DOMAIN_OF_KIND[kind],
    horizon_start: `${todayDate()}T00:00:00${browserUtcOffset()}`,
    horizon_days: 30,
    time_unit: "minutes",
    currency: "USD",
    terminology: { ...info.terminology! },
    tasks: [],
    resources: [{ id: r.id, name: r.name, kind: r.kind, capacity: 1, cost_per_hour: 0, calendar: r.calendar, metadata: {} }],
    dependencies: [],
    objectives: { preset: "balanced", weights: { makespan: 1, tardiness: 1, cost: 0.2 } },
    metadata: {},
  };
}

/** Creates the empty plan for a kind and opens it. One request at a time. */
export function useStepByStep() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState<PlanKind | null>(null);
  const [error, setError] = useState<{ kind: PlanKind; message: string } | null>(null);

  const start = async (kind: PlanKind) => {
    if (busy) return;
    setBusy(kind);
    setError(null);
    try {
      if (kind === "money") {
        const rec = await startBlankFinancePlan();
        navigate(`/finance/${rec.id}/setup/profile`);
      } else {
        const rec = await createProblem(emptyProblem(kind));
        navigate(`/plans/${rec.id}/tasks`);
      }
    } catch (err) {
      setError({ kind, message: errorMessage(err) });
      setBusy(null);
    }
  };
  return { start, busy, error, clearError: () => setError(null) };
}
