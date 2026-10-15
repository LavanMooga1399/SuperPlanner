/** Immutable helpers for editing a Problem draft. */
import type { Calendar, Dependency, Problem, Resource, Task, TimeWindow, Weekday } from "../api/types";

/** First unused id `<prefix>1`, `<prefix>2`, ... (unique across tasks and resources). */
export function nextId(prefix: string, p: Problem): string {
  const used = new Set<string>([...p.tasks.map((t) => t.id), ...p.resources.map((r) => r.id)]);
  for (let i = 1; ; i++) {
    const id = `${prefix}${i}`;
    if (!used.has(id)) return id;
  }
}

export function makeTask(p: Problem, name: string, group: string | null = null): Task {
  return {
    id: nextId("T", p),
    name,
    description: "",
    group,
    type: "activity",
    duration_minutes: 60,
    priority: 5,
    earliest_start: null,
    deadline: null,
    deadline_hard: false,
    requirements: [],
    locked: null,
    metadata: {},
  };
}

export function makeResource(p: Problem, name: string): Resource {
  return {
    id: nextId("R", p),
    name,
    kind: "generic",
    capacity: 1,
    cost_per_hour: 0,
    calendar: null,
    metadata: {},
  };
}

export function updateTask(p: Problem, id: string, fn: (t: Task) => Task): Problem {
  return { ...p, tasks: p.tasks.map((t) => (t.id === id ? fn(t) : t)) };
}

export function updateResource(p: Problem, id: string, fn: (r: Resource) => Resource): Problem {
  return { ...p, resources: p.resources.map((r) => (r.id === id ? fn(r) : r)) };
}

export function removeTask(p: Problem, id: string): Problem {
  return {
    ...p,
    tasks: p.tasks.filter((t) => t.id !== id),
    dependencies: p.dependencies.filter((d) => d.predecessor !== id && d.successor !== id),
  };
}

/** Removes a resource and every reference to it (alternatives, locks). */
export function removeResource(p: Problem, id: string): Problem {
  return {
    ...p,
    resources: p.resources.filter((r) => r.id !== id),
    tasks: p.tasks.map((t) => {
      const touches = t.requirements.some((r) => r.alternatives.includes(id)) || t.locked?.resource_ids?.includes(id);
      if (!touches) return t;
      const requirements = t.requirements
        .map((r) => ({ ...r, alternatives: r.alternatives.filter((a) => a !== id) }))
        .filter((r) => r.alternatives.length > 0);
      const locked = t.locked ? { ...t.locked, resource_ids: null } : null;
      return { ...t, requirements, locked };
    }),
  };
}

export function setDependency(p: Problem, dep: Dependency): Problem {
  const exists = p.dependencies.some((d) => d.predecessor === dep.predecessor && d.successor === dep.successor);
  return {
    ...p,
    dependencies: exists
      ? p.dependencies.map((d) => (d.predecessor === dep.predecessor && d.successor === dep.successor ? dep : d))
      : [...p.dependencies, dep],
  };
}

export function removeDependency(p: Problem, pred: string, succ: string): Problem {
  return { ...p, dependencies: p.dependencies.filter((d) => !(d.predecessor === pred && d.successor === succ)) };
}

export const DEFAULT_WORK_WEEK: Calendar = {
  weekly: {
    mon: [["09:00", "17:00"]],
    tue: [["09:00", "17:00"]],
    wed: [["09:00", "17:00"]],
    thu: [["09:00", "17:00"]],
    fri: [["09:00", "17:00"]],
  },
  blocked: [],
};

export function hhmmToMin(s: string): number {
  if (s === "24:00") return 1440;
  const m = s.match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return NaN;
  return Number(m[1]) * 60 + Number(m[2]);
}

export function windowsOf(cal: Calendar | null, day: Weekday): TimeWindow[] {
  if (!cal || cal.weekly === null) return [["00:00", "24:00"]];
  return cal.weekly[day] ?? [];
}

/** Parse "90", "1h 30m", "1.5h", "2d", "45m" into minutes (null if invalid). */
export function parseDuration(text: string): number | null {
  const s = text.trim().toLowerCase();
  if (!s) return null;
  if (/^\d+$/.test(s)) return Number(s);
  let total = 0;
  let matched = false;
  const re = /(\d+(?:\.\d+)?)\s*(d|h|m|min|mins|hours?|days?)/g;
  let m: RegExpExecArray | null;
  let consumed = "";
  while ((m = re.exec(s))) {
    matched = true;
    consumed += m[0];
    const v = Number(m[1]);
    const u = m[2];
    if (u.startsWith("d")) total += v * 1440;
    else if (u.startsWith("h")) total += v * 60;
    else total += v;
  }
  if (!matched || consumed.replace(/\s/g, "").length !== s.replace(/\s/g, "").length) return null;
  return Math.round(total);
}
