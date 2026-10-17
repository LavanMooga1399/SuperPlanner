/**
 * The four kinds of plan offered on the landing page (PHASE2.md 3.1, 3.2).
 * Scheduling kinds map to an existing plan type (`Problem.domain`, P2D 8 item 6) and template;
 * "money" leads to the finance module.
 */
import type { Calendar, Terminology } from "../api/types";
import type { IconName } from "../components/Icon";

export type PlanKind = "project" | "study" | "production" | "money";
export type ScheduleKind = Exclude<PlanKind, "money">;
export type StartAction = "describe" | "example" | "import" | "steps";

export const PLAN_KINDS: PlanKind[] = ["project", "study", "production", "money"];
export const START_ACTIONS: StartAction[] = ["describe", "example", "import", "steps"];

/** `Problem.domain` for each scheduling kind; matches existing documents and `PlanList` labels. */
export const DOMAIN_OF_KIND: Record<ScheduleKind, string> = {
  project: "project",
  study: "exam_prep",
  production: "manufacturing",
};

export interface KindInfo {
  kind: PlanKind;
  label: string;
  description: string;
  icon: IconName;
  /** null for money (finance module) */
  scheduling: boolean;
  /** scheduling template id shown on the example page */
  templateId: string | null;
  /** used for "Build step by step" (scheduling only) */
  terminology: Terminology | null;
  /** the one working resource of an empty plan (scheduling only) */
  starterResource: { id: string; name: string; kind: string; calendar: Calendar } | null;
  /** "My <noun> plan" */
  planNoun: string;
}

const weekdays = (windows: [string, string][]) =>
  Object.fromEntries(["mon", "tue", "wed", "thu", "fri"].map((d) => [d, windows.map((w) => [...w])])) as Calendar["weekly"];

export const KINDS: Record<PlanKind, KindInfo> = {
  project: {
    kind: "project",
    label: "Project or schedule",
    description: "Tasks, people and deadlines",
    icon: "briefcase",
    scheduling: true,
    templateId: "project",
    terminology: {
      task: "Task", tasks: "Tasks", resource: "Team member", resources: "Team", group: "Workstream",
      milestone: "Milestone", schedule: "Project schedule", deadline: "Deadline",
    },
    starterResource: { id: "ME", name: "Me", kind: "person", calendar: { weekly: weekdays([["09:00", "17:00"]]), blocked: [] } },
    planNoun: "project",
  },
  study: {
    kind: "study",
    label: "Study plan",
    description: "Subjects, revision and an exam date",
    icon: "book",
    scheduling: true,
    templateId: "exam_prep",
    terminology: {
      task: "Study session", tasks: "Study sessions", resource: "Study time", resources: "Study time", group: "Subject",
      milestone: "Exam", schedule: "Study plan", deadline: "Target date",
    },
    starterResource: {
      id: "STUDENT",
      name: "My study time",
      kind: "time",
      calendar: {
        weekly: {
          ...weekdays([["06:00", "08:00"], ["18:00", "21:00"]]),
          sat: [["09:00", "13:00"], ["15:00", "19:00"]],
          sun: [["09:00", "13:00"], ["15:00", "19:00"]],
        },
        blocked: [],
      },
    },
    planNoun: "study",
  },
  production: {
    kind: "production",
    label: "Production",
    description: "Orders, machines and shifts",
    icon: "factory",
    scheduling: true,
    templateId: "manufacturing",
    terminology: {
      task: "Operation", tasks: "Operations", resource: "Machine", resources: "Machines", group: "Job",
      milestone: "Milestone", schedule: "Production schedule", deadline: "Due date",
    },
    starterResource: {
      id: "M1",
      name: "Machine 1",
      kind: "machine",
      calendar: { weekly: { ...weekdays([["06:00", "14:00"], ["14:00", "22:00"]]), sat: [["06:00", "14:00"]] }, blocked: [] },
    },
    planNoun: "production",
  },
  money: {
    kind: "money",
    label: "Money goals",
    description: "Income, savings and goals like a home or retirement",
    icon: "star",
    scheduling: false,
    templateId: null,
    terminology: null,
    starterResource: null,
    planNoun: "money",
  },
};

export const ACTION_LABEL: Record<StartAction, string> = {
  describe: "Describe it",
  example: "Start from an example",
  import: "Import a table",
  steps: "Build step by step",
};

export const ACTION_HINT: Record<StartAction, string> = {
  describe: "Write it in your own words; we turn it into a draft",
  example: "Begin with a ready-made plan and change it",
  import: "Paste from a spreadsheet or upload a CSV file",
  steps: "Fill in the details yourself, one screen at a time",
};

export const ACTION_ICON: Record<StartAction, IconName> = {
  describe: "list",
  example: "file",
  import: "upload",
  steps: "arrow-right",
};

export function isPlanKind(x: string | undefined): x is PlanKind {
  return x !== undefined && (PLAN_KINDS as string[]).includes(x);
}

/** Where an action leads, except "steps", which creates a plan first. */
export function actionPath(kind: PlanKind, action: Exclude<StartAction, "steps">): string {
  return `/new/${kind}/${action}`;
}
