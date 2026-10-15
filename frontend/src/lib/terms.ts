import { useContext } from "react";
import { DEFAULT_TERMINOLOGY, type Terminology } from "../api/types";
import { PlanContextRaw } from "../state/PlanContext";

export interface Terms extends Terminology {
  /** lower-case singular/plural */
  taskL: string;
  tasksL: string;
  resourceL: string;
  resourcesL: string;
  groupL: string;
  deadlineL: string;
  scheduleL: string;
  /** "3 Operations" / "1 Operation" */
  countTasks(n: number): string;
  countResources(n: number): string;
  newTask: string;
  newResource: string;
}

const lower = (s: string) => s.toLocaleLowerCase();

export function makeTerms(t: Partial<Terminology> | null | undefined): Terms {
  const base: Terminology = { ...DEFAULT_TERMINOLOGY, ...(t ?? {}) };
  return {
    ...base,
    taskL: lower(base.task),
    tasksL: lower(base.tasks),
    resourceL: lower(base.resource),
    resourcesL: lower(base.resources),
    groupL: lower(base.group),
    deadlineL: lower(base.deadline),
    scheduleL: lower(base.schedule),
    countTasks: (n) => `${n} ${n === 1 ? base.task : base.tasks}`,
    countResources: (n) => `${n} ${n === 1 ? base.resource : base.resources}`,
    newTask: `New ${base.task}`,
    newResource: `New ${base.resource}`,
  };
}

/** Terminology of the plan currently open (falls back to generic words). */
export function useTerms(): Terms {
  const ctx = useContext(PlanContextRaw);
  return makeTerms(ctx?.draft?.terminology);
}
